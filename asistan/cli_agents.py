"""Aboneliğinle çalışan resmi ajan programları: Claude Code (Claude), Codex (ChatGPT), Gemini CLI (Google hesabı).

Kullanıcının kararı (2026-09-26): bulut modelleri API anahtarı olmadan, abonelik/hesapla da kullanılabilsin. Firmalar
hesap oturumlarının başka programların API çağrılarında kullanılmasına izin vermez; izin verilen yol firmanın kendi
programını kullanıcının kendi girişiyle çalıştırmaktır. Bu yüzden:
- anahtar/oturum bilgisine program hiç dokunmaz (programın kendisi saklar: ~/.claude, ~/.codex, ~/.gemini),
- yalnızca kullanıcının sohbette gönderdiği istekte çalışır (zamanlanmış iş, bulut kuyruğu yok; ChatGPT girişi
  resmi belgeye göre etkileşimli kullanım içindir),
- onay beklenen turda salt okunur (Claude: plan önerisi, Codex: read-only, Gemini: plan), onaylı turda yalnızca iş
  klasöründe düzenler (komut çalıştırma Claude/Gemini'de kapalı; Codex kendi korumalı alanında).
Codex ve Gemini CLI program içinden kurulur (kullanıcının düğmesiyle; SHA-256 doğrulamalı): `DATA_DIR/ajan-programlari`.
"""

import hashlib
import json
import os
import platform
import shutil
import subprocess
import tarfile
import tempfile
import threading
import time
import zipfile
from dataclasses import dataclass, field
from pathlib import Path

import httpx

from .cekirdek import modeller
from .config import DATA_DIR

ROOT = DATA_DIR / "ajan-programlari"
NODE_MIN = 20  # Gemini CLI'ın istediği en eski Node sürümü


@dataclass
class CliAgent:
    provider: str  # sohbet sağlayıcısı: "cli:claude"
    default: str  # model yokken kullanılan ad (programın kendi varsayılanı)
    title: str  # "Claude Code"
    account: str  # "Claude aboneliğin"
    via: str  # "Claude aboneliğinle" (Türkçe ek hazır: menü ve uyarı metinleri)
    models: list = field(default_factory=list)  # [(model, not)]; ilk sıradaki `default`
    tool: str = ""  # sohbetteki adım kartının adı (gui/chat.py TOOL_LABELS)


def _takma_adlar(provider: str) -> list:
    """[(model takma adı, not)] — ayar/modeller.json → cli; ilk sıradaki programın varsayılanı."""
    return [tuple(m) for m in modeller.deger(f"cli.{provider}", [])]


def _cli(provider: str, title: str, account: str, via: str, tool: str) -> CliAgent:
    models = _takma_adlar(provider)
    return CliAgent(provider, models[0][0], title, account, via, models, tool)


CLAUDE = _cli("cli:claude", "Claude Code", "Claude aboneliğin", "Claude aboneliğinle", "claude_code")
CODEX = _cli("cli:codex", "Codex", "ChatGPT hesabın", "ChatGPT hesabınla", "codex")
GEMINI = _cli("cli:gemini", "Gemini CLI", "Google hesabın", "Google hesabınla", "gemini_cli")
AGENTS = {a.provider: a for a in (CLAUDE, CODEX, GEMINI)}


def is_cli(provider: str) -> bool:
    return provider in AGENTS


def label(provider: str, model: str = "") -> str:
    """"Claude Code · opus" — varsayılan modelde yalnızca program adı."""
    a = AGENTS.get(provider)
    if a is None:
        return model
    return a.title + ("" if not model or model == a.default else f" · {model}")


def _exe_name(name: str) -> str:
    return name + (".exe" if os.name == "nt" else "")


# ---------------------------------------------------------------- nerede?

def codex_path() -> str:
    found = shutil.which("codex")
    own = ROOT / "codex" / _exe_name("codex")
    return found or (str(own) if own.is_file() else "")


def _node_version(exe: str) -> int:
    try:
        out = subprocess.run([exe, "--version"], capture_output=True, text=True, timeout=10).stdout
        return int(out.strip().lstrip("v").split(".")[0])
    except (OSError, ValueError, subprocess.SubprocessError):
        return 0


def node_path() -> str:
    own = next(iter(sorted((ROOT / "node").glob("node-*/bin/node" if os.name != "nt" else "node-*/node.exe"))), None)
    if own and own.is_file():
        return str(own)
    system = shutil.which("node")
    return system if system and _node_version(system) >= NODE_MIN else ""


def gemini_command() -> list[str]:
    """Gemini CLI'ı çalıştıran komut: sistemdeki `gemini` ya da programın kurduğu paket (Node ile)."""
    found = shutil.which("gemini")
    if found:
        return [found]
    script = ROOT / "gemini" / "gemini.js"
    node = node_path()
    return [node, str(script)] if node and script.is_file() else []


def installed(provider: str) -> bool:
    if provider == CLAUDE.provider:
        return shutil.which("claude") is not None
    if provider == CODEX.provider:
        return bool(codex_path())
    if provider == GEMINI.provider:
        return bool(gemini_command())
    return False


def _run(cmd: list[str], timeout: float = 20, env: dict | None = None) -> subprocess.CompletedProcess | None:
    try:
        flags = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
        return subprocess.run(cmd, capture_output=True, text=True, timeout=timeout, stdin=subprocess.DEVNULL,
                              encoding="utf-8", errors="replace", creationflags=flags, env=env)
    except (OSError, subprocess.SubprocessError):
        return None


_login_cache: dict[str, tuple[float, bool]] = {}


def logged_in(provider: str, refresh: bool = False) -> bool:
    """Kullanıcı bu programa kendi hesabıyla giriş yapmış mı? (Claude Code: kuruluysa girişli sayılır.)"""
    if not installed(provider):
        return False
    if provider == CLAUDE.provider:
        return True
    hit = _login_cache.get(provider)
    if hit and not refresh and time.time() - hit[0] < 60:
        return hit[1]
    ok = False
    if provider == CODEX.provider:
        r = _run([codex_path(), "login", "status"])
        ok = bool(r and r.returncode == 0 and "not logged in" not in (r.stdout + r.stderr).lower())
    elif provider == GEMINI.provider:
        home = Path.home() / ".gemini"
        ok = (home / "oauth_creds.json").is_file() and _gemini_auth_type() == "oauth-personal"
    _login_cache[provider] = (time.time(), ok)
    return ok


def available(provider: str) -> bool:
    """Kurulu ve girişli: sohbette seçilebilir."""
    return installed(provider) and logged_in(provider)


def available_agents() -> list[CliAgent]:
    return [a for a in AGENTS.values() if available(a.provider)]


# ---------------------------------------------------------------- kurulum

def _download(url: str, dest: Path, sha256: str, progress, cancelled, label_: str) -> None:
    from .imagegen import _download as download  # kaldığı yerden süren indirme

    download(url, dest, progress, cancelled, label_)
    if sha256:
        h = hashlib.sha256()
        with open(dest, "rb") as f:
            for chunk in iter(lambda: f.read(1 << 20), b""):
                h.update(chunk)
        if h.hexdigest() != sha256.lower():
            dest.unlink(missing_ok=True)
            raise RuntimeError(f"{label_} doğrulanamadı (SHA-256 tutmuyor); indirme silindi.")


def _release_asset(repo: str, name_ok) -> tuple[str, str, str]:
    """GitHub'daki son sürümden (ad, adres, sha256)."""
    rel = httpx.get(f"https://api.github.com/repos/{repo}/releases/latest", timeout=20,
                    follow_redirects=True).json()
    for a in rel.get("assets", []):
        if name_ok(a["name"]):
            return a["name"], a["browser_download_url"], (a.get("digest") or "").removeprefix("sha256:")
    raise RuntimeError("Bu işletim sistemi için paket bulunamadı.")


def _codex_asset() -> str:
    system, machine = platform.system(), platform.machine().lower()
    arch = "aarch64" if machine in ("arm64", "aarch64") else "x86_64"
    if system == "Linux":
        return f"codex-{arch}-unknown-linux-musl.tar.gz"
    if system == "Windows":
        return f"codex-{arch}-pc-windows-msvc.exe.zip"
    if system == "Darwin":
        return f"codex-{arch}-apple-darwin.tar.gz"
    raise RuntimeError("Codex bu işletim sisteminde yok.")


def _extract(archive: Path, target: Path) -> None:
    target.mkdir(parents=True, exist_ok=True)
    if archive.name.endswith(".zip"):
        with zipfile.ZipFile(archive) as z:
            z.extractall(target)
    else:
        with tarfile.open(archive) as t:
            t.extractall(target, filter="data")


def install_codex(progress=None, cancelled=lambda: False) -> str:
    wanted = _codex_asset()
    name, url, digest = _release_asset("openai/codex", lambda n: n == wanted)
    archive = ROOT / name
    _download(url, archive, digest, progress, cancelled, "Codex")
    target = ROOT / "codex"
    shutil.rmtree(target, ignore_errors=True)
    _extract(archive, target)
    archive.unlink(missing_ok=True)
    exe = next((f for f in target.rglob("codex*") if f.is_file() and not f.name.endswith((".sigstore", ".zst"))), None)
    if exe is None:
        raise RuntimeError("Codex paketinde program bulunamadı.")
    final = target / _exe_name("codex")
    if exe != final:
        exe.replace(final)
    if os.name != "nt":
        final.chmod(0o755)
    return str(final)


def _node_file() -> tuple[str, str]:
    """(dosya adı eki, arşiv türü) — nodejs.org/dist adlandırması."""
    system, machine = platform.system(), platform.machine().lower()
    arch = "arm64" if machine in ("arm64", "aarch64") else "x64"
    if system == "Linux":
        return f"linux-{arch}", "tar.xz"
    if system == "Windows":
        return f"win-{arch}", "zip"
    if system == "Darwin":
        return f"darwin-{arch}", "tar.gz"
    raise RuntimeError("Node.js bu işletim sisteminde yok.")


def install_node(progress=None, cancelled=lambda: False) -> str:
    """Taşınabilir Node.js (yalnızca programın klasörüne; sistem değişmez)."""
    index = httpx.get("https://nodejs.org/dist/index.json", timeout=20).json()
    lts = next(v["version"] for v in index if v.get("lts") and int(v["version"][1:].split(".")[0]) >= 22)
    suffix, kind = _node_file()
    name = f"node-{lts}-{suffix}.{kind}"
    sums = httpx.get(f"https://nodejs.org/dist/{lts}/SHASUMS256.txt", timeout=20).text
    digest = next((line.split()[0] for line in sums.splitlines() if line.endswith(name)), "")
    if not digest:
        raise RuntimeError("Node.js doğrulama bilgisi alınamadı.")
    archive = ROOT / name
    _download(f"https://nodejs.org/dist/{lts}/{name}", archive, digest, progress, cancelled, "Node.js")
    shutil.rmtree(ROOT / "node", ignore_errors=True)
    _extract(archive, ROOT / "node")
    archive.unlink(missing_ok=True)
    found = node_path()
    if not found:
        raise RuntimeError("Node.js kurulamadı.")
    return found


def install_gemini(progress=None, cancelled=lambda: False) -> list[str]:
    if not node_path():
        install_node(progress, cancelled)
    name, url, digest = _release_asset("google-gemini/gemini-cli", lambda n: n == "gemini-cli-bundle.zip")
    archive = ROOT / name
    _download(url, archive, digest, progress, cancelled, "Gemini CLI")
    shutil.rmtree(ROOT / "gemini", ignore_errors=True)
    _extract(archive, ROOT / "gemini")
    archive.unlink(missing_ok=True)
    cmd = gemini_command()
    if not cmd:
        raise RuntimeError("Gemini CLI kurulamadı.")
    return cmd


def install(provider: str, progress=None, cancelled=lambda: False) -> None:
    ROOT.mkdir(parents=True, exist_ok=True)
    if provider == CODEX.provider:
        install_codex(progress, cancelled)
    elif provider == GEMINI.provider:
        install_gemini(progress, cancelled)
    else:
        raise RuntimeError("Claude Code'u Anthropic'in sayfasından kur: https://claude.com/claude-code")


# ---------------------------------------------------------------- giriş

def _gemini_settings() -> Path:
    return Path.home() / ".gemini" / "settings.json"


def _gemini_auth_type() -> str:
    try:
        data = json.loads(_gemini_settings().read_text(encoding="utf-8"))
        return data.get("security", {}).get("auth", {}).get("selectedType", "")
    except (OSError, ValueError, AttributeError):
        return ""


def _select_google_login() -> None:
    """Gemini CLI'da "Google ile giriş" seçilsin (diğer ayarlara dokunmadan)."""
    path = _gemini_settings()
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        data = {}
    data.setdefault("security", {}).setdefault("auth", {})["selectedType"] = "oauth-personal"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def login(provider: str, cancelled=lambda: False, timeout: float = 600) -> None:
    """Resmi programın kendi girişi: tarayıcıda hesabınla giriş yaparsın, program oturumu kendisi saklar."""
    if provider == CODEX.provider:
        cmd = [codex_path(), "login"]
        feed = None
    elif provider == GEMINI.provider:
        _select_google_login()
        # başsız ilk çalıştırma: "tarayıcıda giriş sayfası açılsın mı? [Y/n]" → Y; giriş bitince kısa bir cevap verir
        cmd = gemini_command() + ["-p", "Yalnızca 'tamam' yaz.", "--output-format", "json", "--skip-trust"]
        feed = "Y\n"
    else:
        raise RuntimeError("Claude Code girişi kendi penceresinde yapılır: terminalde `claude` yaz.")
    flags = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
    proc = subprocess.Popen(cmd, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                            text=True, encoding="utf-8", errors="replace", creationflags=flags,
                            cwd=tempfile.gettempdir())
    if feed:
        proc.stdin.write(feed)
        proc.stdin.flush()
    proc.stdin.close()
    out: list[str] = []
    reader = threading.Thread(target=lambda: out.extend(proc.stdout), daemon=True)
    reader.start()
    deadline = time.time() + timeout
    while proc.poll() is None:
        if cancelled() or time.time() > deadline:
            proc.kill()
            raise InterruptedError("giriş iptal edildi" if cancelled() else "giriş 10 dakikada tamamlanmadı")
        time.sleep(0.3)
    reader.join(2)
    _login_cache.pop(provider, None)
    if not logged_in(provider, refresh=True):
        raise RuntimeError("Giriş tamamlanmadı:\n" + "".join(out)[-400:].strip())


# ---------------------------------------------------------------- çalıştırma

def _step_codex(event: dict) -> tuple[str, str, bool] | None:
    """Codex --json olayından (başlık, sonuç, hata mı); gösterilecek bir adım değilse None."""
    if event.get("type") != "item.completed":
        return None
    item = event.get("item") or {}
    kind = item.get("type")
    if kind == "command_execution":
        code = item.get("exit_code")
        return str(item.get("command", ""))[:200], str(item.get("aggregated_output", ""))[-1500:], bool(code)
    if kind == "file_change":
        paths = [c.get("path", "") for c in item.get("changes", [])]
        return "dosya: " + ", ".join(Path(p).name for p in paths)[:200], "\n".join(paths), False
    if kind == "web_search":
        return "web: " + str(item.get("query", ""))[:200], "", False
    if kind == "mcp_tool_call":
        return f"{item.get('server', '')}: {item.get('tool', '')}", "", item.get("status") == "failed"
    return None


def _step_gemini(event: dict, pending: dict) -> tuple[str, str, bool] | None:
    kind = event.get("type")
    if kind == "tool_use":
        params = event.get("parameters") or {}
        detail = params.get("command") or params.get("file_path") or params.get("path") or params.get("query") or ""
        pending[event.get("tool_id", "")] = f"{event.get('tool_name', '')} {detail}".strip()[:200]
        return None
    if kind == "tool_result":
        title = pending.pop(event.get("tool_id", ""), "araç")
        output = event.get("output") or (event.get("error") or {}).get("message", "")
        return title, str(output)[-1500:], event.get("status") == "error"
    return None


def _message(event: dict) -> str:
    """Hata olayının metni ("error" bir sözlük ya da düz metin olabilir)."""
    err = event.get("error")
    return str((err.get("message") if isinstance(err, dict) else err) or event.get("message") or "")


def run(provider: str, prompt: str, cwd: str, system: str = "", edits: bool = False, cancelled=None,
        model: str = "", on_step=None, timeout: int = 1800) -> str:
    """Resmi programı iş klasöründe çalıştırır; son cevabı döndürür. on_step(başlık, sonuç, hata) her adımda."""
    if provider == CLAUDE.provider:
        from .specialists import claude_code

        return claude_code(prompt, cwd, system, edits=edits, cancelled=cancelled, timeout=timeout, model=model)
    agent = AGENTS[provider]
    if not installed(provider):
        raise RuntimeError(f"{agent.title} kurulu değil. Model menüsünde firmanın altındaki “{agent.via} kullan” ile kur.")
    model = "" if model == agent.default else model
    full = f"{system}\n\n---\n\n{prompt}" if system else prompt
    last_file = None
    if provider == CODEX.provider:
        last_file = Path(tempfile.mkstemp(prefix="codex-son-", suffix=".txt")[1])
        cmd = [codex_path(), "exec", "--json", "--skip-git-repo-check", "--color", "never", "-C", cwd,
               "--sandbox", "workspace-write" if edits else "read-only", "-o", str(last_file)]
        if model:
            cmd += ["-m", model]
        cmd.append(full)
    else:
        cmd = gemini_command() + ["-p", full, "--output-format", "stream-json", "--skip-trust",
                                  "--approval-mode", "auto_edit" if edits else "plan"]
        if model:
            cmd += ["-m", model]
    flags = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
    proc = subprocess.Popen(cmd, cwd=cwd, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                            text=True, encoding="utf-8", errors="replace", creationflags=flags)
    lines: "list[str]" = []
    errors: "list[str]" = []
    err_reader = threading.Thread(target=lambda: errors.extend(proc.stderr), daemon=True)
    err_reader.start()
    reader_done = threading.Event()

    def read():
        for line in proc.stdout:
            lines.append(line)
        reader_done.set()

    threading.Thread(target=read, daemon=True).start()
    start, seen, pending, texts, failure = time.time(), 0, {}, [], ""
    while True:
        finished = reader_done.wait(0.3)
        while seen < len(lines):
            raw = lines[seen].strip()
            seen += 1
            try:
                event = json.loads(raw)
            except ValueError:
                continue
            if provider == CODEX.provider:
                step = _step_codex(event)
                item = event.get("item") or {}
                if event.get("type") == "item.completed" and item.get("type") == "agent_message":
                    texts.append(str(item.get("text", "")))
                if event.get("type") in ("turn.failed", "error"):
                    failure = _message(event) or failure
            else:
                step = _step_gemini(event, pending)
                if event.get("type") == "message" and event.get("role") == "assistant":
                    texts.append(str(event.get("content", "")))
                if event.get("type") == "error" or (event.get("type") == "result" and event.get("status") == "error"):
                    failure = _message(event) or failure
            if step and on_step:
                on_step(*step)
        if finished:
            break
        if (cancelled and cancelled()) or time.time() - start > timeout:
            proc.kill()
            proc.wait()
            raise InterruptedError(f"{agent.title} durduruldu")
    proc.wait()
    err_reader.join(2)
    proc.stdout.close()
    proc.stderr.close()
    answer = ""
    if last_file is not None:
        try:
            answer = last_file.read_text(encoding="utf-8").strip()
        except OSError:
            pass
        last_file.unlink(missing_ok=True)
    # Gemini cevabı parça parça (delta) akıtır; Codex'te her mesaj tamdır
    answer = answer or ("".join(texts) if provider == GEMINI.provider else "\n\n".join(texts)).strip()
    if proc.returncode != 0 and not answer:
        detail = failure or "".join(errors).strip()[-400:] or "".join(lines).strip()[-400:]
        if "auth" in detail.lower() or "login" in detail.lower() or "401" in detail:
            _login_cache.pop(provider, None)
            detail += f"\n{agent.via} yeniden giriş gerekebilir (model menüsü → bağlan)."
        raise RuntimeError(f"{agent.title} hatası: {detail}")
    return answer or f"{agent.title} bir cevap yazmadı."
