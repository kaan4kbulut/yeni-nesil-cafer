"""Bulut model kataloğu: Online (sohbet) ve Kod menülerinde gösterilen firmalar ve öne çıkan modelleri.

Eylül 2026'da firmaların resmi model sayfalarına göre hazırlandı. Model adları sık değiştiği için bu
liste yalnızca "öne çıkanlar"dır: bir firmaya bağlanınca hesabın gerçekten sunduğu modeller de
(bağlantının model listesi) menüde gösterilir.
"""

from dataclasses import dataclass, field

from .cekirdek import modeller


def _katalog(firma: str, tur: str) -> list:
    """Firmanın öne çıkan modelleri [(model id, kısa açıklama)] — ayar/modeller.json → bulut_katalog."""
    return [tuple(m) for m in modeller.deger(f"bulut_katalog.{firma}.{tur}", [])]


@dataclass
class Provider:
    id: str
    name: str
    preset: str  # bağlantı penceresindeki hazır ayar ("anthropic": Claude anahtar penceresi)
    host: str  # bağlı mı? — bağlantı adresinde geçen parça
    key_url: str  # API anahtarının alındığı sayfa
    note: str = ""  # menüde firma adının yanında kısa bilgi
    chat: list = field(default_factory=list)  # [(model id, kısa açıklama)] — ilk sıradaki önerilen
    code: list = field(default_factory=list)
    # hesapla kullanma yolu: "openrouter"/"huggingface" (tarayıcıda giriş, accounts.py) ya da resmi programın
    # sağlayıcısı "cli:codex"/"cli:gemini"/"cli:claude" (aboneliğinle; cli_agents.py). Boş: yalnızca API anahtarı.
    login: str = ""


PROVIDERS = [
    Provider(
        "anthropic", "Anthropic · Claude", "anthropic", "anthropic.com", "https://console.anthropic.com/settings/keys",
        chat=_katalog("anthropic", "chat"),
        code=_katalog("anthropic", "code"),
        login="cli:claude",
    ),
    Provider(
        "openai", "OpenAI · GPT", "OpenAI", "openai.com", "https://platform.openai.com/api-keys",
        chat=_katalog("openai", "chat"),
        code=_katalog("openai", "code"),
        login="cli:codex",
    ),
    Provider(
        "google", "Google · Gemini", "Google Gemini", "googleapis.com", "https://aistudio.google.com/apikey",
        note="ücretsiz kota var",
        chat=_katalog("google", "chat"),
        code=_katalog("google", "code"),
        login="cli:gemini",
    ),
    Provider(
        "xai", "xAI · Grok", "xAI (Grok)", "x.ai", "https://console.x.ai",
        chat=_katalog("xai", "chat"),
        code=_katalog("xai", "code"),
    ),
    Provider(
        "deepseek", "DeepSeek", "DeepSeek", "deepseek.com", "https://platform.deepseek.com/api_keys",
        note="çok ucuz",
        chat=_katalog("deepseek", "chat"),
        code=_katalog("deepseek", "code"),
    ),
    Provider(
        "groq", "Groq", "Groq", "groq.com", "https://console.groq.com/keys",
        note="ücretsiz kota, çok hızlı",
        chat=_katalog("groq", "chat"),
        code=_katalog("groq", "code"),
    ),
    Provider(
        "openrouter", "OpenRouter", "OpenRouter", "openrouter.ai", "https://openrouter.ai/settings/keys",
        note="tek anahtarla yüzlerce model, ücretsizler dahil",
        chat=_katalog("openrouter", "chat"),
        code=_katalog("openrouter", "code"),
        login="openrouter",
    ),
    Provider(
        "huggingface", "Hugging Face", "Hugging Face", "huggingface.co", "https://huggingface.co/settings/tokens",
        note="aylık ücretsiz kredi, açık modeller",
        chat=_katalog("huggingface", "chat"),
        code=_katalog("huggingface", "code"),
        login="huggingface",
    ),
    Provider(
        "mistral", "Mistral", "Mistral", "mistral.ai", "https://console.mistral.ai/api-keys",
        note="ücretsiz kota",
        chat=_katalog("mistral", "chat"),
        code=_katalog("mistral", "code"),
    ),
]


def by_host(base_url: str) -> Provider | None:
    """Bağlantı adresinden firmayı bulur (Anthropic hariç; o ayrı anahtarla bağlanır)."""
    return next((p for p in PROVIDERS if p.id != "anthropic" and p.host in base_url), None)


def ranked(models: list[str], provider: Provider | None, code: bool = False) -> list[str]:
    """Bağlantının modellerini katalog sırasına göre dizer (öne çıkanlar önce)."""
    featured = [m for m, _ in ((provider.code if code else provider.chat) if provider else [])]
    return sorted(models, key=lambda m: featured.index(m) if m in featured else len(featured))


BY_ID = {p.id: p for p in PROVIDERS}
