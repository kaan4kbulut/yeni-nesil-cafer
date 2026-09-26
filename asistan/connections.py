"""API bağlantıları: OpenAI uyumlu model sağlayıcıları ve ajanın çağırabildiği araç API'leri.

Bağlantı bilgileri `baglantilar.json` dosyasında, anahtarlar ise `keystore` üzerinden
sistem anahtar zincirinde tutulur.
"""

import json
import re
import uuid
from dataclasses import asdict, dataclass, field

import httpx

from .config import CONFIG_DIR
from .keystore import delete_secret, get_secret, set_secret

CONNECTIONS_FILE = CONFIG_DIR / "baglantilar.json"
ANTHROPIC_KEY = "anthropic"  # Claude anahtarının anahtar zincirindeki adı

# OpenAI uyumlu sohbet API'si sunan hazır sağlayıcılar: ad -> (adres, anahtar gerekli mi)
LLM_PRESETS = {
    "OpenAI": ("https://api.openai.com/v1", True),
    "Google Gemini": ("https://generativelanguage.googleapis.com/v1beta/openai", True),
    "Groq": ("https://api.groq.com/openai/v1", True),
    "OpenRouter": ("https://openrouter.ai/api/v1", True),
    "Hugging Face": ("https://router.huggingface.co/v1", True),
    "DeepSeek": ("https://api.deepseek.com/v1", True),
    "xAI (Grok)": ("https://api.x.ai/v1", True),
    "Mistral": ("https://api.mistral.ai/v1", True),
    "LM Studio (yerel)": ("http://localhost:1234/v1", False),
    "Özel (OpenAI uyumlu)": ("", True),
}

# Araç API'lerinde anahtarın nasıl gönderileceği
AUTH_MODES = {
    "bearer": "Authorization: Bearer <anahtar>",
    "header": "Özel başlık (ör. X-Api-Key)",
    "query": "Adres parametresi (ör. ?appid=)",
    "none": "Anahtar yok",
}


@dataclass
class Connection:
    kind: str  # "llm" (model sağlayıcı) veya "tool" (araç API'si)
    name: str
    base_url: str
    id: str = field(default_factory=lambda: uuid.uuid4().hex[:10])
    preset: str = ""
    models: list = field(default_factory=list)  # llm: bilinen model adları
    description: str = ""  # tool: modele gösterilen "ne işe yarar" açıklaması
    auth: str = "bearer"
    auth_param: str = ""  # header adı ya da sorgu parametresi adı
    enabled: bool = True

    @property
    def key(self) -> str:
        from .accounts import fresh_key  # hesapla girişte süreli anahtar: gerekirse yenilenir

        return fresh_key(self.id, get_secret(f"conn:{self.id}"))

    @key.setter
    def key(self, value: str) -> None:
        set_secret(f"conn:{self.id}", value)

    @property
    def slug(self) -> str:
        """Modelin araç çağrısında kullandığı kısa ad."""
        return re.sub(r"[^a-z0-9]+", "_", self.name.lower()).strip("_") or self.id

    def auth_request(self, headers: dict, params: dict, key: str | None = None) -> None:
        key = self.key if key is None else key
        if not key or self.auth == "none":
            return
        if self.auth == "bearer":
            headers["Authorization"] = f"Bearer {key}"
        elif self.auth == "header":
            headers[self.auth_param or "X-Api-Key"] = key
        elif self.auth == "query":
            params[self.auth_param or "key"] = key


def load_connections() -> list[Connection]:
    try:
        data = json.loads(CONNECTIONS_FILE.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    conns = []
    for item in data:
        known = {k: v for k, v in item.items() if k in Connection.__dataclass_fields__}
        try:
            conns.append(Connection(**known))
        except TypeError:
            continue
    return conns


def save_connections(conns: list[Connection]) -> None:
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    CONNECTIONS_FILE.write_text(
        json.dumps([asdict(c) for c in conns], indent=2, ensure_ascii=False), encoding="utf-8")


def remove_connection(conns: list[Connection], conn: Connection) -> None:
    conns.remove(conn)
    delete_secret(f"conn:{conn.id}")
    delete_secret(f"oturum:{conn.id}")  # hesapla girişin yenileme bilgisi (accounts.py)
    save_connections(conns)


# ---- bağlantı testleri (arka plan iş parçacığında çağrılır)

def fetch_llm_models(base_url: str, key: str) -> list[str]:
    headers = {"Authorization": f"Bearer {key}"} if key else {}
    resp = httpx.get(base_url.rstrip("/") + "/models", headers=headers, timeout=15)
    resp.raise_for_status()
    items = resp.json().get("data", [])
    names = [m.get("id", "") for m in items if m.get("id")]
    # Gemini "models/gemini-..." biçiminde döndürür
    return sorted(n.removeprefix("models/") for n in names)


def test_anthropic(key: str) -> str:
    import anthropic

    client = anthropic.Anthropic(api_key=key) if key else anthropic.Anthropic()
    models = client.models.list(limit=5)
    return f"Bağlantı başarılı · {len(models.data)} model görüldü"


def test_tool_api(conn: Connection, key: str) -> str:
    headers, params = {"User-Agent": "yeni-nesil-cafer"}, {}
    conn.auth_request(headers, params, key)
    resp = httpx.get(conn.base_url, headers=headers, params=params, timeout=15, follow_redirects=True)
    if resp.status_code in (401, 403):
        raise RuntimeError(f"Yetki reddedildi ({resp.status_code}) — anahtarı kontrol et")
    if resp.status_code >= 500:
        raise RuntimeError(f"Sunucu hatası ({resp.status_code})")
    return f"Sunucu yanıt verdi ({resp.status_code})"


def describe_http_error(exc: Exception) -> str:
    if isinstance(exc, httpx.HTTPStatusError):
        code = exc.response.status_code
        if code in (401, 403):
            return f"Anahtar geçersiz ya da yetkisiz ({code})"
        return f"Sunucu hatası ({code})"
    if isinstance(exc, httpx.ConnectError):
        return "Sunucuya bağlanılamadı"
    if isinstance(exc, httpx.TimeoutException):
        return "Zaman aşımı"
    return str(exc) or type(exc).__name__
