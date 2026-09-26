"""Bulut modellerine hesapla giriş: API anahtarını kopyalayıp yapıştırmak yerine tarayıcıda "giriş yap → onayla".

Yalnızca firmanın başka programlara resmi olarak izin verdiği yollar (kullanıcının kararı, 2026-09-26):
- OpenRouter: OAuth PKCE; tarayıcı yerel adrese (herhangi bir port) döner, kod anahtarla değiştirilir. Kayıt gerekmez.
- Hugging Face: cihaz kodu girişi (gizli anahtarsız "public" uygulama, `HF_CLIENT_ID`); erişim anahtarı süreli,
  yenileme anahtarıyla kendiliğinden tazelenir (`fresh_key`).
- ChatGPT: resmi Codex programının kendi girişi (`codex login`, specialists.py); burada değil.
Claude ve Gemini hesap girişi başka programlara açık değil: onlar API anahtarıyla bağlanır.
GitHub Models 30.07.2026'da kapatıldı (resmi belge), bu yüzden GitHub hesabıyla giriş yok.
"""

import base64
import hashlib
import json
import secrets
import threading
import time
from http.server import BaseHTTPRequestHandler, HTTPServer
from urllib.parse import parse_qs, urlencode, urlparse

import httpx

OPENROUTER_AUTH = "https://openrouter.ai/auth"
OPENROUTER_KEYS = "https://openrouter.ai/api/v1/auth/keys"

HF_CLIENT_ID = ""  # huggingface.co/settings/applications: gizli anahtarsız uygulamanın kimliği (gizli değildir)
HF_DEVICE = "https://huggingface.co/oauth/device"
HF_TOKEN = "https://huggingface.co/oauth/token"
HF_SCOPES = "openid profile inference-api"

# bağlantı penceresindeki hazır ayar -> giriş yöntemi
LOGINS = {"OpenRouter": "openrouter", "Hugging Face": "huggingface"}

DONE_PAGE = """<!doctype html><meta charset="utf-8"><title>YENİ NESİL CAFER</title>
<body style="font-family:sans-serif;background:#16171d;color:#e8e8ea;display:grid;place-items:center;height:90vh">
<div style="text-align:center"><h2>{title}</h2><p>{text}</p></div></body>"""


class LoginError(RuntimeError):
    pass


def available(method: str) -> bool:
    return method == "openrouter" or (method == "huggingface" and bool(HF_CLIENT_ID))


def _pkce() -> tuple[str, str]:
    verifier = secrets.token_urlsafe(64)
    challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b"=").decode()
    return verifier, challenge


class _Callback:
    """Tarayıcının döneceği yerel adres: yalnızca bu bilgisayardan (127.0.0.1 ve ::1), tek istek, sonra kapanır."""

    def __init__(self, path: str = "/callback"):
        self.path, self.query, self.servers = path, None, []
        owner = self

        class Handler(BaseHTTPRequestHandler):
            def do_GET(self):  # noqa: N802
                url = urlparse(self.path)
                if url.path != owner.path:
                    self.send_error(404)
                    return
                owner.query = {k: v[0] for k, v in parse_qs(url.query).items()}
                ok = "code" in owner.query
                page = DONE_PAGE.format(
                    title="Giriş tamam ✓" if ok else "Giriş yapılmadı",
                    text="Bu sekmeyi kapatıp programa dönebilirsin." if ok else "Programa dönüp yeniden dene.")
                body = page.encode("utf-8")
                self.send_response(200)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def log_message(self, *args):  # konsola yazmasın
                pass

        v4 = HTTPServer(("127.0.0.1", 0), Handler)
        self.port = v4.server_address[1]
        self.servers.append(v4)
        try:  # tarayıcı "localhost"u önce ::1'e çözebilir: aynı portta IPv6 da dinle
            import socket

            class V6(HTTPServer):
                address_family = socket.AF_INET6

            self.servers.append(V6(("::1", self.port), Handler))
        except OSError:
            pass
        for s in self.servers:
            s.timeout = 0.3
            threading.Thread(target=self._serve, args=(s,), daemon=True).start()

    def _serve(self, server):
        while self.query is None and server in self.servers:
            server.handle_request()

    @property
    def url(self) -> str:
        return f"http://localhost:{self.port}{self.path}"

    def wait(self, cancelled, timeout: float) -> dict:
        deadline = time.time() + timeout
        try:
            while self.query is None:
                if cancelled():
                    raise InterruptedError("giriş iptal edildi")
                if time.time() > deadline:
                    raise LoginError("Tarayıcıda giriş 5 dakika içinde tamamlanmadı.")
                time.sleep(0.2)
            return self.query
        finally:
            self.close()

    def close(self):
        servers, self.servers = self.servers, []
        for s in servers:
            s.server_close()


def openrouter(open_url, cancelled=lambda: False, timeout: float = 300) -> str:
    """OpenRouter'a tarayıcıda giriş; kullanıcının hesabına bağlı bir API anahtarı döndürür."""
    verifier, challenge = _pkce()
    cb = _Callback()
    try:
        open_url(OPENROUTER_AUTH + "?" + urlencode({"callback_url": cb.url, "code_challenge": challenge,
                                                  "code_challenge_method": "S256"}))
        query = cb.wait(cancelled, timeout)
    finally:
        cb.close()
    if not query.get("code"):
        raise LoginError("OpenRouter girişi onaylanmadı.")
    r = httpx.post(OPENROUTER_KEYS, json={"code": query["code"], "code_verifier": verifier,
                                          "code_challenge_method": "S256"}, timeout=30)
    if r.status_code >= 400:
        raise LoginError(f"OpenRouter anahtar vermedi ({r.status_code}): {r.text[:200]}")
    key = r.json().get("key", "")
    if not key:
        raise LoginError("OpenRouter yanıtında anahtar yok.")
    return key


# ---------------------------------------------------------------- Hugging Face (cihaz kodu)

def huggingface(show_code, cancelled=lambda: False) -> dict:
    """Hugging Face'e cihaz koduyla giriş. show_code(kod, adres): kullanıcıya gösterilir (tarayıcı da açılır).
    Döner: {"access_token", "refresh_token", "expires_at"}."""
    if not HF_CLIENT_ID:
        raise LoginError("Hugging Face girişi bu sürümde ayarlanmadı.")
    r = httpx.post(HF_DEVICE, data={"client_id": HF_CLIENT_ID, "scope": HF_SCOPES}, timeout=30)
    if r.status_code >= 400:
        raise LoginError(f"Hugging Face giriş kodu vermedi ({r.status_code}): {r.text[:200]}")
    d = r.json()
    show_code(d["user_code"], d.get("verification_uri_complete") or d["verification_uri"])
    interval = max(int(d.get("interval", 5)), 1)
    deadline = time.time() + int(d.get("expires_in", 900))
    while time.time() < deadline:
        for _ in range(interval * 5):
            if cancelled():
                raise InterruptedError("giriş iptal edildi")
            time.sleep(0.2)
        t = httpx.post(HF_TOKEN, data={"grant_type": "urn:ietf:params:oauth:grant-type:device_code",
                                       "device_code": d["device_code"], "client_id": HF_CLIENT_ID}, timeout=30)
        body = _json(t)
        if t.status_code < 400 and body.get("access_token"):
            return _tokens(body)
        err = body.get("error", "")
        if err == "slow_down":
            interval += 5
        elif err != "authorization_pending":
            raise LoginError(f"Hugging Face girişi tamamlanmadı: {err or t.text[:200]}")
    raise LoginError("Giriş kodunun süresi doldu; yeniden dene.")


def _json(r: httpx.Response) -> dict:
    try:
        return r.json()
    except ValueError:
        return {}


def _tokens(body: dict, old: dict | None = None) -> dict:
    return {"access_token": body["access_token"],
            "refresh_token": body.get("refresh_token") or (old or {}).get("refresh_token", ""),
            "expires_at": time.time() + int(body.get("expires_in") or 8 * 3600)}


def _refresh_hf(tokens: dict) -> dict:
    r = httpx.post(HF_TOKEN, data={"grant_type": "refresh_token", "refresh_token": tokens["refresh_token"],
                                   "client_id": HF_CLIENT_ID}, timeout=30)
    body = _json(r)
    if r.status_code >= 400 or not body.get("access_token"):
        raise LoginError("Hugging Face oturumu sona erdi; API'ler sekmesinden yeniden giriş yap.")
    return _tokens(body, tokens)


# ---------------------------------------------------------------- süreli anahtarlar

def save_session(conn_id: str, method: str, tokens: dict) -> None:
    """Hesap girişinin yenileme bilgisi anahtar zincirinde (bağlantının anahtarı erişim anahtarıdır)."""
    from .keystore import set_secret

    set_secret(f"oturum:{conn_id}", json.dumps({"method": method, **tokens}))
    set_secret(f"conn:{conn_id}", tokens["access_token"])


_refresh_lock = threading.Lock()


def fresh_key(conn_id: str, key: str) -> str:
    """Bağlantının anahtarı; hesap girişiyle alınmış ve süresi dolmak üzereyse önce yenilenir."""
    from .keystore import get_secret

    raw = get_secret(f"oturum:{conn_id}")
    if not raw:
        return key
    with _refresh_lock:
        try:
            session = json.loads(get_secret(f"oturum:{conn_id}") or raw)
        except ValueError:
            return key
        if session.get("expires_at", 0) - time.time() > 300 or not session.get("refresh_token"):
            return key
        if session.get("method") == "huggingface":
            tokens = _refresh_hf(session)
            save_session(conn_id, "huggingface", tokens)
            return tokens["access_token"]
    return key
