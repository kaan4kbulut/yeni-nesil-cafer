"""MCP (Model Context Protocol) istemcisi: hazır MCP sunucularını eklenti gibi takar.

Sunucular `mcp.json` dosyasında, Claude Desktop ile aynı biçimde tanımlanır; oradaki bir yapılandırma buraya
aynen kopyalanabilir:

    {"mcpServers": {
        "zaman": {"command": "uvx", "args": ["mcp-server-time"]},
        "dosyalar": {"command": "npx", "args": ["-y", "@modelcontextprotocol/server-filesystem", "~/Belgeler"]},
        "uzak": {"url": "https://ornek.com/mcp", "headers": {"Authorization": "Bearer …"}}
    }}

Ek alanlar: "disabled": true (başlatma), "trusted": true ya da ["araç", …] (bu araçlar onaysız çalışsın).
Bağlantı: "command" varsa stdio (satır başına bir JSON-RPC mesajı), "url" varsa HTTP (streamable HTTP).
Sunucunun araçları kayda (registry.py) "sunucu__araç" adıyla girer. Risk sınıfı MCP işaretlerinden çıkar:
readOnlyHint → okur (onaysız); diğerleri → calistirir (her seferinde onay; güvenlik ajanı açıksa o denetler).
"""

import json
import os
import queue
import shutil
import subprocess
import sys
import threading
import time
from pathlib import Path

import httpx

from .cekirdek.araclar import komut as _komut
from .config import CONFIG_DIR, DATA_DIR
from .registry import REGISTRY, Tool, safe_name

CONFIG_FILE = CONFIG_DIR / "mcp.json"
LOG_DIR = DATA_DIR / "mcp-kayitlari"  # sunucuların hata çıktıları (stderr)
PROTOCOL = "2025-06-18"
START_TIMEOUT = 90  # ilk açılışta npx / uvx paketi indirebilir
CALL_TIMEOUT = 180
NO_WINDOW = subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0

EXAMPLE = {"mcpServers": {}}


class McpError(Exception):
    pass


def load_config() -> dict:
    """mcp.json → {sunucu adı: ayarlar}; dosya yoksa boş örnek oluşturulur."""
    if not CONFIG_FILE.exists():
        CONFIG_DIR.mkdir(parents=True, exist_ok=True)
        CONFIG_FILE.write_text(json.dumps(EXAMPLE, indent=2, ensure_ascii=False), encoding="utf-8")
    try:
        data = json.loads(CONFIG_FILE.read_text(encoding="utf-8"))
    except ValueError as e:
        raise McpError(f"mcp.json okunamadı (JSON hatası): {e}") from None
    servers = data.get("mcpServers") if isinstance(data, dict) else None
    return servers if isinstance(servers, dict) else {}


# ---------------------------------------------------------------- bağlantılar


def sunucu_ortami(conf: dict) -> dict:
    """K12-B2: MCP sunucusu (npx/uvx ile inen üçüncü taraf kod) yalnızca beyaz listeli ortamı + mcp.json'daki `env`'i
    görür; ANTHROPIC_API_KEY / CAFER_* / OPENAI_API_KEY geçmez (CLAUDE.md pazarlık dışı)."""
    ek = {str(k): str(v) for k, v in (conf.get("env") or {}).items()}
    return _komut.guvenli_ortam(os.environ, ek=ek)


class _Stdio:
    """Yerel süreç: stdin'e istek yazılır, stdout'tan satır satır cevap okunur."""

    def __init__(self, name: str, conf: dict):
        command = os.path.expanduser(str(conf.get("command") or ""))
        exe = shutil.which(command) or command  # Windows: npx → npx.cmd
        args = [os.path.expanduser(str(a)) for a in conf.get("args") or []]
        env = sunucu_ortami(conf)
        LOG_DIR.mkdir(parents=True, exist_ok=True)
        self.log = open(LOG_DIR / f"{safe_name(name)}.log", "ab")
        try:
            self.proc = subprocess.Popen([exe, *args], stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                         stderr=self.log, env=env, cwd=conf.get("cwd") or None,
                                         creationflags=NO_WINDOW)
        except OSError as e:
            self.log.close()
            raise McpError(f"başlatılamadı ({command}): {e}") from None
        self.lines: queue.Queue = queue.Queue()
        threading.Thread(target=self._read, daemon=True).start()

    def _read(self):
        for raw in self.proc.stdout:
            self.lines.put(raw)
        self.lines.put(None)  # süreç kapandı

    def send(self, message: dict) -> None:
        try:
            self.proc.stdin.write((json.dumps(message, ensure_ascii=False) + "\n").encode("utf-8"))
            self.proc.stdin.flush()
        except (OSError, ValueError):
            raise McpError("sunucu kapandı") from None

    def receive(self, timeout: float) -> dict | None:
        """Sıradaki JSON mesajı; süre dolarsa None. JSON olmayan satırlar (günlük yazıları) atlanır."""
        end = time.monotonic() + timeout
        while True:
            left = end - time.monotonic()
            if left <= 0:
                return None
            try:
                raw = self.lines.get(timeout=left)
            except queue.Empty:
                return None
            if raw is None:
                raise McpError("sunucu kapandı" + self._last_error())
            try:
                msg = json.loads(raw)
            except ValueError:
                continue
            if isinstance(msg, dict):
                return msg

    def _last_error(self) -> str:
        try:
            self.log.flush()
            tail = (LOG_DIR / Path(self.log.name).name).read_bytes()[-400:].decode("utf-8", "replace").strip()
            return f": {tail.splitlines()[-1]}" if tail else ""
        except (OSError, IndexError):
            return ""

    def close(self):
        try:
            self.proc.stdin.close()
            self.proc.wait(timeout=3)
        except Exception:
            self.proc.kill()
        if self.proc.stdout:
            self.proc.stdout.close()
        self.log.close()


class _Http:
    """Uzak sunucu (streamable HTTP): her istek bir POST; cevap JSON ya da SSE akışı."""

    def __init__(self, name: str, conf: dict):
        self.url = str(conf["url"])
        self.headers = {str(k): str(v) for k, v in (conf.get("headers") or {}).items()}
        self.session = ""
        self.inbox: list[dict] = []

    def send(self, message: dict) -> None:
        headers = {**self.headers, "Accept": "application/json, text/event-stream",
                   "MCP-Protocol-Version": PROTOCOL}
        if self.session:
            headers["Mcp-Session-Id"] = self.session
        try:
            resp = httpx.post(self.url, json=message, headers=headers, timeout=CALL_TIMEOUT)
        except httpx.HTTPError as e:
            raise McpError(f"bağlanılamadı: {e}") from None
        if resp.status_code >= 400:
            raise McpError(f"HTTP {resp.status_code}: {resp.text[:200]}")
        self.session = resp.headers.get("Mcp-Session-Id", self.session)
        if "text/event-stream" in resp.headers.get("content-type", ""):
            for line in resp.text.splitlines():
                if line.startswith("data:"):
                    try:
                        self.inbox.append(json.loads(line[5:].strip()))
                    except ValueError:
                        pass
        elif resp.content.strip():
            data = resp.json()
            self.inbox.extend(data if isinstance(data, list) else [data])

    def receive(self, timeout: float) -> dict | None:
        return self.inbox.pop(0) if self.inbox else None

    def close(self):
        pass


# ---------------------------------------------------------------- sunucu


class Server:
    def __init__(self, name: str, conf: dict, workspace: str = ""):
        self.name, self.conf, self.workspace = name, conf, workspace
        self.state = "kapalı"  # kapalı · başlıyor · çalışıyor · hata
        self.error = ""
        self.tools: list[dict] = []
        self.link = None
        self._id = 0
        self._lock = threading.Lock()  # bir sunucuya aynı anda tek istek

    # -- JSON-RPC
    def _request(self, method: str, params: dict | None = None, timeout: float = CALL_TIMEOUT) -> dict:
        with self._lock:
            self._id += 1
            my_id = self._id
            self.link.send({"jsonrpc": "2.0", "id": my_id, "method": method, **({"params": params} if params else {})})
            end = time.monotonic() + timeout
            while True:
                msg = self.link.receive(max(0.0, end - time.monotonic()))
                if msg is None:
                    raise McpError(f"{method}: {timeout:.0f} sn içinde cevap gelmedi")
                if "method" in msg and "id" in msg:  # sunucudan bize istek (ping, roots/list…)
                    self._answer(msg)
                    continue
                if msg.get("id") != my_id:
                    continue  # bildirim ya da eski bir cevap
                if "error" in msg:
                    err = msg["error"] or {}
                    raise McpError(f"{method}: {err.get('message') or err}")
                return msg.get("result") or {}

    def _answer(self, msg: dict) -> None:
        if msg["method"] == "ping":
            result = {}
        elif msg["method"] == "roots/list":
            root = Path(self.workspace or Path.home()).expanduser().resolve()
            result = {"roots": [{"uri": root.as_uri(), "name": "çalışma klasörü"}]}
        else:
            self.link.send({"jsonrpc": "2.0", "id": msg["id"],
                            "error": {"code": -32601, "message": "desteklenmiyor"}})
            return
        self.link.send({"jsonrpc": "2.0", "id": msg["id"], "result": result})

    # -- yaşam döngüsü
    def start(self) -> None:
        self.state, self.error = "başlıyor", ""
        try:
            self.link = _Http(self.name, self.conf) if self.conf.get("url") else _Stdio(self.name, self.conf)
            self._request("initialize", {
                "protocolVersion": PROTOCOL,
                "capabilities": {"roots": {"listChanged": False}},
                "clientInfo": {"name": "yeni-nesil-cafer", "version": _version()},
            }, timeout=START_TIMEOUT)
            self.link.send({"jsonrpc": "2.0", "method": "notifications/initialized"})
            self.tools = self._list_tools()
            self.state = "çalışıyor"
        except Exception as e:
            self.state, self.error = "hata", str(e)
            self.stop(keep_state=True)
            raise

    def _list_tools(self) -> list[dict]:
        tools, cursor = [], None
        while True:
            result = self._request("tools/list", {"cursor": cursor} if cursor else None, timeout=START_TIMEOUT)
            tools += [t for t in result.get("tools") or [] if isinstance(t, dict) and t.get("name")]
            cursor = result.get("nextCursor")
            if not cursor:
                return tools

    def stop(self, keep_state: bool = False) -> None:
        if self.link is not None:
            try:
                self.link.close()
            except Exception:
                pass
            self.link = None
        if not keep_state:
            self.state = "kapalı"

    def call(self, tool: str, args: dict) -> str:
        """Aracı çalıştırır; sonuç içeriği modele gidecek düz metne çevrilir."""
        from .tools import ToolError

        if self.state != "çalışıyor" or self.link is None:
            raise ToolError(f"MCP sunucusu '{self.name}' çalışmıyor: {self.error or self.state}")
        try:
            result = self._request("tools/call", {"name": tool, "arguments": args or {}})
        except McpError as e:
            raise ToolError(str(e)) from None
        text = _content_text(result)
        if result.get("isError"):
            raise ToolError(text or "araç hata verdi")
        return text or "(araç boş sonuç döndürdü)"


def _content_text(result: dict) -> str:
    parts = []
    for item in result.get("content") or []:
        kind = item.get("type")
        if kind == "text":
            parts.append(str(item.get("text", "")))
        elif kind in ("image", "audio"):
            parts.append(f"[{kind}: {item.get('mimeType', '?')}, {len(item.get('data') or '') * 3 // 4} bayt]")
        elif kind == "resource":
            res = item.get("resource") or {}
            parts.append(str(res.get("text") or res.get("uri") or ""))
        elif kind == "resource_link":
            parts.append(f"{item.get('name', '')}: {item.get('uri', '')}")
    if not parts and result.get("structuredContent") is not None:
        parts.append(json.dumps(result["structuredContent"], ensure_ascii=False, indent=2))
    return "\n".join(p for p in parts if p)


def _version() -> str:
    try:
        from . import __version__
        return __version__
    except ImportError:
        return "0"


# ---------------------------------------------------------------- yönetici (programın bütün sunucuları)

_servers: dict[str, Server] = {}
_lock = threading.Lock()


def risk_sinifi(hints: dict, trusted: bool) -> str:
    """K12-A7: sunucunun `readOnlyHint` beyanı yalnızca kullanıcının mcp.json'da "trusted" dediği sunucuda/araçta
    onayı kaldırır ("okur"); diğer her şey "calistirir" (her seferinde kullanıcı ya da güvenlik ajanı)."""
    return "okur" if (hints or {}).get("readOnlyHint") and trusted else "calistirir"


def _register(server: Server) -> None:
    source = f"mcp:{server.name}"
    REGISTRY.remove_source(source)
    trusted = server.conf.get("trusted")
    for t in server.tools:
        hints = t.get("annotations") or {}
        name = safe_name(f"{server.name}__{t['name']}")
        schema = t.get("inputSchema") if isinstance(t.get("inputSchema"), dict) else {}
        schema = {"type": "object", "properties": {}, **schema}
        guvenilir = trusted is True or (isinstance(trusted, list) and t["name"] in trusted)
        REGISTRY.put(Tool(
            name=name,
            description=f"[MCP · {server.name}] {t.get('description') or t.get('title') or t['name']}"[:1024],
            schema=schema,
            risk=risk_sinifi(hints, guvenilir),
            label=(f"{server.name}: {t.get('title') or t['name']}", "bitti"),
            source=source,
            group="mcp",
            runner=lambda args, s=server, tool=t["name"]: s.call(tool, args),
            trusted=guvenilir,
            hints=hints,
        ))


def start_all(workspace: str = "", only: str | None = None) -> dict[str, str]:
    """mcp.json'daki sunucuları başlatır (arka planda çağrılır); sunucu → sonuç ("N araç" ya da hata)."""
    try:
        config = load_config()
    except McpError as e:
        return {"mcp.json": str(e)}
    report = {}
    for name, conf in config.items():
        if only and name != only:
            continue
        if not isinstance(conf, dict) or conf.get("disabled"):
            continue
        with _lock:
            old = _servers.pop(name, None)
        if old:
            old.stop()
            REGISTRY.remove_source(f"mcp:{name}")
        server = Server(name, conf, workspace)
        with _lock:
            _servers[name] = server
        try:
            server.start()
            _register(server)
            report[name] = f"{len(server.tools)} araç"
        except Exception as e:
            report[name] = f"hata: {e}"
    return report


def stop_all() -> None:
    with _lock:
        servers = list(_servers.values())
        _servers.clear()
    for s in servers:
        s.stop()
        REGISTRY.remove_source(f"mcp:{s.name}")


def reload(workspace: str = "") -> dict[str, str]:
    stop_all()
    return start_all(workspace)


def status() -> list[dict]:
    """Ayarlar penceresi için: yapılandırmadaki her sunucunun durumu."""
    try:
        config = load_config()
    except McpError as e:
        return [{"name": "mcp.json", "state": "hata", "tools": 0, "error": str(e)}]
    out = []
    for name, conf in config.items():
        s = _servers.get(name)
        if isinstance(conf, dict) and conf.get("disabled"):
            out.append({"name": name, "state": "devre dışı", "tools": 0, "error": ""})
        elif s is None:
            out.append({"name": name, "state": "kapalı", "tools": 0, "error": ""})
        else:
            out.append({"name": name, "state": s.state, "tools": len(s.tools), "error": s.error})
    return out
