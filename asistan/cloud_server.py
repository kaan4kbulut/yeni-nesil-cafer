"""Bulut beyin (Aşama 6): aynı asistan, bilgisayar kapalıyken bir sunucuda. Telegram botu + web sayfası.

"Tek gövde, iki beyin": yönetici döngüsü (manager.py), ajan (agent.py), hafıza (memory_db.py) aynı koddur; bulutta
değişen yalnızca model (sunucudaki yerel model) ve araçlardır. Bulut asistan kullanıcının bilgisayarına ERİŞEMEZ:
yerel dosya / uygulama gerektiren işleri `queue_for_computer` ile kuyruğa bırakır; bilgisayar açılınca program
bunları listeler ve kullanıcı tıklarsa yerel asistan yapar (sunucu ele geçirilse bile bilgisayarda kendiliğinden bir
şey çalışmaz). Sonuç kuyruk üzerinden geri gelir ve işin geldiği kanala (Telegram / web) iletilir.

Çalıştırma (sunucuda): python -m asistan.cloud_server  — ayarlar DATA_DIR/bulut.json (ilk açılışta anahtar ve
eşleşme kodu üretilir, ekrana yazılır). Ek paket gerekmez (httpx + standart kütüphane).
"""

import hmac
import json
import secrets
import sqlite3
import threading
import time
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import httpx

from .config import DATA_DIR
from .registry import REGISTRY

CONFIG_FILE = DATA_DIR / "bulut.json"
DB_FILE = DATA_DIR / "bulut.db"
HISTORY_LIMIT = 24  # kanal başına saklanan mesaj (küçük model, küçük bağlam)
CLOUD_TOOLS = {"web_search", "fetch_url", "remember", "queue_for_computer"}
JOB_STATES = ("bekliyor", "alindi", "bitti", "reddedildi")

def cloud_prompt() -> str:
    """Bulut kopyasının kısa talimatı (yerel programın pencere/menü anlatımı yok: küçük modelde hızlı ve doğru)."""
    from datetime import date

    return (
        f"You are YENİ NESİL CAFER, the user's personal assistant. Today is {date.today().isoformat()}. Always reply in "
        "the user's language (usually Turkish), briefly and clearly — they read on a phone. Use web_search and "
        "fetch_url for current facts instead of guessing, and cite the source briefly. When the user asks you to "
        "remember something or states a lasting preference, call remember. Never pretend to have done something you "
        "did not do.")


CLOUD_NOTE = (
    "\n\n## You are the cloud copy\nYou are the user's assistant running on a small server while their computer "
    "may be off. You can search the web, read pages and use long-term memory. You can NOT reach the user's computer, "
    "files, apps or accounts. When a request needs their computer (their files, installed programs, local models, "
    "anything on that machine), call queue_for_computer with a complete, self-contained task; tell the user it "
    "will run when the computer is on and they approve it. The user reads on a phone: keep answers short.")

QUEUE_SPEC = {
    "name": "queue_for_computer",
    "description": (
        "Leave a job for the user's own computer (their files, installed programs, local models). It runs when the "
        "computer is on and the user approves it there; the result comes back here. Write the task in plain words, "
        "as the user would ask it (not shell commands), complete enough for the local assistant to do it without "
        "this conversation."),
    "input_schema": {
        "type": "object",
        "properties": {
            "task": {"type": "string", "description": "Complete task for the local assistant, in the user's language"},
            "reason": {"type": "string", "description": "Why it needs the computer (one short sentence)"},
        },
        "required": ["task"],
    },
}

_lock = threading.RLock()
_conn: sqlite3.Connection | None = None
_local = threading.local()  # bu isteğin kanalı (queue_for_computer işi nereye bağlayacağını bilsin)


# ---------------------------------------------------------------- ayarlar ve veritabanı

def load_config() -> dict:
    try:
        conf = json.loads(CONFIG_FILE.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        conf = {}
    changed = False
    for key, make in (("token", lambda: secrets.token_urlsafe(24)), ("pair_code", lambda: f"{secrets.randbelow(10**6):06d}")):
        if not conf.get(key):
            conf[key], changed = make(), True
    conf.setdefault("port", 8765)
    conf.setdefault("host", "127.0.0.1")  # dışarı açmak için 0.0.0.0 — önerilen: Tailscale ile yalnızca kendi cihazların
    conf.setdefault("model", "qwen3.5:4b")
    conf.setdefault("telegram_token", "")
    conf.setdefault("telegram_chat", 0)
    if changed:
        save_config(conf)
    return conf


def save_config(conf: dict) -> None:
    CONFIG_FILE.parent.mkdir(parents=True, exist_ok=True)
    tmp = CONFIG_FILE.with_suffix(".tmp")
    tmp.write_text(json.dumps(conf, ensure_ascii=False, indent=1), encoding="utf-8")
    tmp.replace(CONFIG_FILE)
    try:
        CONFIG_FILE.chmod(0o600)  # anahtarlar başkası tarafından okunmasın
    except OSError:
        pass


def _db() -> sqlite3.Connection:
    global _conn
    if _conn is None:
        DB_FILE.parent.mkdir(parents=True, exist_ok=True)
        _conn = sqlite3.connect(str(DB_FILE), check_same_thread=False, timeout=10)
        _conn.row_factory = sqlite3.Row
        _conn.execute("""CREATE TABLE IF NOT EXISTS jobs (id TEXT PRIMARY KEY, task TEXT NOT NULL, reason TEXT,
            channel TEXT, status TEXT NOT NULL, result TEXT, created REAL NOT NULL, updated REAL NOT NULL)""")
        _conn.execute("CREATE TABLE IF NOT EXISTS chats (channel TEXT PRIMARY KEY, messages TEXT NOT NULL)")
        _conn.commit()
    return _conn


def reset_for_tests(data_dir: Path) -> None:
    global _conn, CONFIG_FILE, DB_FILE
    with _lock:
        if _conn is not None:
            _conn.close()
        _conn, CONFIG_FILE, DB_FILE = None, data_dir / "bulut.json", data_dir / "bulut.db"


# ---------------------------------------------------------------- iş kuyruğu

def add_job(task: str, reason: str = "", channel: str = "") -> dict:
    now = time.time()
    job = {"id": uuid.uuid4().hex[:10], "task": task.strip()[:4000], "reason": reason.strip()[:300],
           "channel": channel, "status": "bekliyor", "result": "", "created": now, "updated": now}
    with _lock:
        _db().execute("INSERT INTO jobs VALUES (:id, :task, :reason, :channel, :status, :result, :created, :updated)", job)
        _db().commit()
    return job


def jobs(status: str | None = None) -> list[dict]:
    with _lock:
        if status:
            rows = _db().execute("SELECT * FROM jobs WHERE status=? ORDER BY created", (status,)).fetchall()
        else:
            rows = _db().execute("SELECT * FROM jobs ORDER BY created DESC LIMIT 50").fetchall()
    return [dict(r) for r in rows]


def update_job(job_id: str, status: str, result: str = "") -> dict | None:
    if status not in JOB_STATES:
        raise ValueError("bilinmeyen durum")
    with _lock:
        _db().execute("UPDATE jobs SET status=?, result=?, updated=? WHERE id=?",
                      (status, result[:8000], time.time(), job_id))
        _db().commit()
        r = _db().execute("SELECT * FROM jobs WHERE id=?", (job_id,)).fetchone()
    job = dict(r) if r else None
    if job and status in ("bitti", "reddedildi"):
        text = (f"✅ Bilgisayarındaki iş bitti: {job['task'][:200]}\n\n{result[:3500]}" if status == "bitti"
                else f"✗ Bilgisayarındaki iş reddedildi: {job['task'][:200]}")
        notify(job["channel"], text)
    return job


def _queue_runner(args: dict) -> str:
    job = add_job(str(args.get("task", "")), str(args.get("reason") or ""), getattr(_local, "channel", ""))
    return (f"QUEUED (job {job['id']}). It will run on the user's computer when it is on and they approve it; the "
            "result will be sent here. Tell the user this in one sentence.")


# yalnızca bulutta: "ozel" grubunda olduğu için yerel ajanların araç listesine girmez
REGISTRY.add(QUEUE_SPEC, "danisir", ("bilgisayara iş bırak", "kuyruğa alındı"), group="ozel", runner=_queue_runner)


# ---------------------------------------------------------------- sohbet geçmişi ve asistan

def history(channel: str) -> list:
    with _lock:
        r = _db().execute("SELECT messages FROM chats WHERE channel=?", (channel,)).fetchone()
    return json.loads(r["messages"]) if r else []


def _save_history(channel: str, messages: list) -> None:
    # küçük bağlam: son mesajlar, ama bir araç sonucu çağrısından kopmasın
    trimmed = messages[-HISTORY_LIMIT:]
    # baştaki kopuk parçalar atılır: çağrısı kesilmiş araç sonucu, programın adım mesajı (asistan notları kalır:
    # ör. bilgisayarda biten işin sonucu)
    while trimmed and (trimmed[0].get("role") == "tool" or trimmed[0].get("_program")
                       or (trimmed[0].get("role") == "assistant" and trimmed[0].get("tool_calls"))):
        trimmed.pop(0)
    with _lock:
        _db().execute("INSERT OR REPLACE INTO chats (channel, messages) VALUES (?, ?)",
                      (channel, json.dumps(trimmed, ensure_ascii=False)))
        _db().commit()


class _Collect:
    """Ajan olayları: metni toplar; onay gerektiren hiçbir şey bulutta yapılmaz."""

    def __init__(self):
        self.text = ""

    def on_text(self, delta): self.text += delta
    def on_thinking(self, delta): pass
    def on_model_start(self, step): pass
    def on_model_end(self, stats): pass
    def on_tool_start(self, *a): pass
    def on_tool_end(self, *a): pass
    def ask_approval(self, name, args): return False
    def is_cancelled(self): return False
    def start_team_task(self, *a): return "Not available in the cloud."


def settings_for_cloud(conf: dict):
    from dataclasses import replace

    from .config import Settings

    s = Settings.load()
    return replace(s, provider="ollama", ollama_model=conf["model"], approval_mode="kullanici",
                   workspace=str(DATA_DIR / "bulut-calisma"), auto_model=False, model_policy="yerel")


_agent_lock = threading.Lock()  # küçük sunucuda aynı anda tek model çağrısı


def answer(channel: str, text: str, conf: dict | None = None) -> str:
    """Kanalın geçmişiyle bir tur çalıştırır, cevabı döndürür."""
    from .agent import Agent
    from .manager import Manager

    conf = conf or load_config()
    settings = settings_for_cloud(conf)
    Path(settings.workspace).mkdir(parents=True, exist_ok=True)
    cb = _Collect()
    agent = Agent(settings, cb)
    agent.tool_specs = [s for s in agent.tool_specs if s["name"] in CLOUD_TOOLS] + [QUEUE_SPEC]
    agent.base_system = cloud_prompt()
    agent.extra_system = CLOUD_NOTE
    messages = history(channel)
    with _agent_lock:
        _local.channel = channel
        try:
            Manager(agent).run("ollama", messages, text)
        finally:
            _local.channel = ""
    _save_history(channel, messages)
    return cb.text.strip() or "(cevap üretilemedi)"


# ---------------------------------------------------------------- Telegram

def _tg(conf: dict, method: str, **params) -> dict:
    resp = httpx.post(f"https://api.telegram.org/bot{conf['telegram_token']}/{method}", json=params,
                      timeout=httpx.Timeout(70, connect=10))
    return resp.json()


def notify(channel: str, text: str) -> None:
    """İşin geldiği kanala haber verir (Telegram mesajı ya da web geçmişine not)."""
    conf = load_config()
    if channel.startswith("telegram:") and conf.get("telegram_token"):
        try:
            for i in range(0, len(text), 4000):
                _tg(conf, "sendMessage", chat_id=int(channel.split(":", 1)[1]), text=text[i:i + 4000])
        except Exception:
            pass
    elif channel == "web":
        messages = history("web")
        messages.append({"role": "assistant", "content": text})
        _save_history("web", messages)


def handle_telegram(conf: dict, update: dict) -> str | None:
    """Tek bir Telegram güncellemesi: eşleşme ya da sohbet. Gönderilecek cevabı döndürür (yabancılara None)."""
    msg = update.get("message") or {}
    chat = (msg.get("chat") or {}).get("id")
    text = (msg.get("text") or "").strip()
    if not chat or not text:
        return None
    if not conf.get("telegram_chat"):
        if text.split()[:2] == ["/baglan", conf["pair_code"]]:
            conf["telegram_chat"] = chat
            save_config(conf)
            return "✅ Eşleşti. Artık bu sohbetten asistanına yazabilirsin."
        return None  # eşleşmemiş biri: cevap verilmez (bot varlığını bile belli etmez)
    if chat != conf["telegram_chat"]:
        return None
    if text == "/isler":
        pending = jobs("bekliyor") + jobs("alindi")
        return "\n".join(f"• [{j['status']}] {j['task'][:120]}" for j in pending) or "Bekleyen iş yok."
    return answer(f"telegram:{chat}", text, conf)


def telegram_loop(stop: threading.Event) -> None:
    offset = 0
    while not stop.is_set():
        conf = load_config()
        if not conf.get("telegram_token"):
            stop.wait(30)
            continue
        try:
            data = _tg(conf, "getUpdates", offset=offset, timeout=50)
        except Exception:
            stop.wait(10)
            continue
        for update in data.get("result") or []:
            offset = update["update_id"] + 1
            chat = ((update.get("message") or {}).get("chat") or {}).get("id")
            try:
                if chat and chat == conf.get("telegram_chat"):
                    _tg(conf, "sendChatAction", chat_id=chat, action="typing")
                reply = handle_telegram(conf, update)
            except Exception as e:
                reply = f"⚠ Hata: {type(e).__name__}: {e}"
            if reply and chat:
                for i in range(0, len(reply), 4000):
                    try:
                        _tg(conf, "sendMessage", chat_id=chat, text=reply[i:i + 4000])
                    except Exception:
                        pass


# ---------------------------------------------------------------- HTTP (API + web sayfası)

WEB_PAGE = """<!doctype html><html lang="tr"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1"><title>YENİ NESİL CAFER · Bulut</title>
<style>
:root{--bg:#14120F;--card:#1B1814;--text:#E8E1D5;--muted:#8A8174;--accent:#E5A54B;--line:#3D362E}
@media (prefers-color-scheme: light){:root{--bg:#F7F4EE;--card:#FFF;--text:#1F1B16;--muted:#6B6358;--accent:#B7771F;--line:#DDD5C8}}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--text);font:16px/1.5 system-ui,sans-serif}
main{max-width:760px;margin:0 auto;padding:16px;display:flex;flex-direction:column;height:100vh}
h1{font-size:17px;font-weight:600;margin:4px 0 12px}#log{flex:1;overflow-y:auto}
.m{background:var(--card);border:1px solid var(--line);border-radius:10px;padding:10px 12px;margin:8px 0;white-space:pre-wrap}
.u{border-color:var(--accent)}.muted{color:var(--muted);font-size:13px}
form{display:flex;gap:8px;padding-top:8px}textarea{flex:1;min-height:48px;background:var(--card);color:var(--text);
border:1px solid var(--line);border-radius:10px;padding:10px;font:inherit}
button{background:var(--accent);color:#14120F;border:0;border-radius:10px;padding:0 18px;font:inherit;font-weight:600}
</style></head><body><main><h1>YENİ NESİL CAFER · Bulut</h1><div id="log"></div>
<form id="f"><textarea id="t" placeholder="Asistanına yaz…"></textarea><button>Gönder</button></form>
<div class="muted">Bilgisayarındaki dosyalar gereken işler kuyruğa girer; bilgisayar açılınca onaylarsan yapılır.</div></main>
<script>
let key=localStorage.getItem("anahtar")||"";
if(!key){key=prompt("Erişim anahtarı (sunucu kurulurken verildi):")||"";localStorage.setItem("anahtar",key)}
const log=document.getElementById("log");
function add(text,user){const d=document.createElement("div");d.className="m"+(user?" u":"");d.textContent=text;log.appendChild(d);log.scrollTop=1e9;return d}
async function api(path,body){const r=await fetch(path,{method:body?"POST":"GET",headers:{"Authorization":"Bearer "+key,"Content-Type":"application/json"},body:body?JSON.stringify(body):undefined});
 if(r.status==401){localStorage.removeItem("anahtar");alert("Anahtar yanlış");location.reload()}return r.json()}
api("/api/history").then(h=>h.messages.forEach(m=>add(m.content,m.role=="user")));
document.getElementById("f").onsubmit=async e=>{e.preventDefault();const t=document.getElementById("t");const text=t.value.trim();if(!text)return;
 t.value="";add(text,true);const w=add("… düşünüyor (sunucudaki model yavaş olabilir)");
 try{const r=await api("/api/chat",{text});w.textContent=r.reply||r.error}catch(err){w.textContent="⚠ "+err}};
</script></body></html>"""


class Handler(BaseHTTPRequestHandler):
    server_version = "YeniNesilCaferBulut/1"

    def log_message(self, fmt, *args):  # erişim kaydı ekrana dökülmesin (anahtar URL'de değil ama yine de)
        pass

    def _send(self, code: int, body, content_type: str = "application/json"):
        data = body.encode("utf-8") if isinstance(body, str) else json.dumps(body, ensure_ascii=False).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", content_type + "; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.send_header("X-Content-Type-Options", "nosniff")
        self.end_headers()
        self.wfile.write(data)

    def _authed(self) -> bool:
        given = self.headers.get("Authorization", "").removeprefix("Bearer ").strip()
        return bool(given) and hmac.compare_digest(given, load_config()["token"])

    def _body(self) -> dict:
        n = int(self.headers.get("Content-Length") or 0)
        if n > 5_000_000:
            raise ValueError("istek çok büyük")
        return json.loads(self.rfile.read(n) or b"{}")

    def do_GET(self):  # noqa: N802
        url = urlparse(self.path)
        if url.path == "/":
            return self._send(200, WEB_PAGE, "text/html")
        if url.path == "/api/health":
            return self._send(200, {"ok": True, "time": time.time()})
        if not self._authed():
            return self._send(401, {"error": "yetkisiz"})
        if url.path == "/api/history":
            return self._send(200, {"messages": [m for m in history("web") if isinstance(m.get("content"), str)
                                                 and m["content"].strip() and not m.get("_program")]})
        if url.path == "/api/queue":
            status = (parse_qs(url.query).get("status") or [None])[0]
            return self._send(200, {"jobs": jobs(status)})
        return self._send(404, {"error": "yok"})

    def do_POST(self):  # noqa: N802
        url = urlparse(self.path)
        if not self._authed():
            return self._send(401, {"error": "yetkisiz"})
        try:
            body = self._body()
            if url.path == "/api/chat":
                return self._send(200, {"reply": answer("web", str(body.get("text", ""))[:4000])})
            if url.path == "/api/sync":
                from . import memory_db

                now = time.time()
                applied = memory_db.apply_changes(body.get("changes") or {})
                out = memory_db.changes_since(float(body.get("since") or 0))
                return self._send(200, {"changes": out, "applied": applied, "now": now})
            if url.path.startswith("/api/queue/"):
                job = update_job(url.path.rsplit("/", 1)[1], str(body.get("status", "")), str(body.get("result") or ""))
                return self._send(200 if job else 404, {"job": job})
        except Exception as e:
            return self._send(400, {"error": f"{type(e).__name__}: {e}"})
        return self._send(404, {"error": "yok"})


def make_server(conf: dict | None = None) -> ThreadingHTTPServer:
    conf = conf or load_config()
    return ThreadingHTTPServer((conf["host"], int(conf["port"])), Handler)


def main() -> None:
    conf = load_config()
    print(f"YENİ NESİL CAFER · bulut — http://{conf['host']}:{conf['port']}  (model: {conf['model']})")
    print(f"Erişim anahtarı (programın Ayarlar → Bulut asistan kısmına ve web sayfasına): {conf['token']}")
    if conf.get("telegram_token") and not conf.get("telegram_chat"):
        print(f"Telegram: bota şunu yaz → /baglan {conf['pair_code']}")
    elif not conf.get("telegram_token"):
        print(f"Telegram botu için {CONFIG_FILE} içine telegram_token yaz ve yeniden başlat.")
    stop = threading.Event()
    threading.Thread(target=telegram_loop, args=(stop,), daemon=True).start()
    server = make_server(conf)
    try:
        server.serve_forever()
    finally:
        stop.set()


if __name__ == "__main__":
    main()
