"""Bulut model kataloğu: Online (sohbet) ve Kod menülerinde gösterilen firmalar ve öne çıkan modelleri.

Eylül 2026'da firmaların resmi model sayfalarına göre hazırlandı. Model adları sık değiştiği için bu
liste yalnızca "öne çıkanlar"dır: bir firmaya bağlanınca hesabın gerçekten sunduğu modeller de
(bağlantının model listesi) menüde gösterilir.
"""

from dataclasses import dataclass, field


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
        chat=[("claude-opus-5-5", "önerilen"), ("claude-fable-5-1", "en güçlü"), ("claude-sonnet-5", "dengeli"),
              ("claude-haiku-4-5", "hızlı, ucuz")],
        code=[("claude-opus-5-5", "önerilen"), ("claude-fable-5-1", "en zor işler"), ("claude-sonnet-5", "dengeli")],
        login="cli:claude",
    ),
    Provider(
        "openai", "OpenAI · GPT", "OpenAI", "openai.com", "https://platform.openai.com/api-keys",
        chat=[("gpt-6-astra", "en güçlü"), ("gpt-6-sol", "dengeli"), ("gpt-6-luna", "hızlı, ucuz")],
        code=[("gpt-6-sol", "kod ve ajan işleri"), ("gpt-6-astra", "en zor işler"), ("gpt-6-luna", "hızlı, ucuz")],
        login="cli:codex",
    ),
    Provider(
        "google", "Google · Gemini", "Google Gemini", "googleapis.com", "https://aistudio.google.com/apikey",
        note="ücretsiz kota var",
        chat=[("gemini-3.8-flash", "önerilen"), ("gemini-3.1-pro-preview", "en güçlü, önizleme"),
              ("gemini-3.5-flash-lite", "hızlı, ucuz")],
        code=[("gemini-3.8-flash", "yazılım ve ajan işleri"), ("gemini-3.1-pro-preview", "en güçlü, önizleme")],
        login="cli:gemini",
    ),
    Provider(
        "xai", "xAI · Grok", "xAI (Grok)", "x.ai", "https://console.x.ai",
        chat=[("grok-4.7", "en güçlü")],
        code=[("grok-4.7", "kod dahil her iş")],
    ),
    Provider(
        "deepseek", "DeepSeek", "DeepSeek", "deepseek.com", "https://platform.deepseek.com/api_keys",
        note="çok ucuz",
        chat=[("deepseek-v4-pro", "güçlü"), ("deepseek-flash", "hızlı, ucuz")],
        code=[("deepseek-v4-pro", "güçlü"), ("deepseek-flash", "hızlı, ucuz")],
    ),
    Provider(
        "groq", "Groq", "Groq", "groq.com", "https://console.groq.com/keys",
        note="ücretsiz kota, çok hızlı",
        chat=[("openai/gpt-oss-120b", "en güçlü, düşünür"), ("llama-3.3-70b-versatile", "dengeli"),
              ("llama-3.1-8b-instant", "en hızlı")],
        code=[("openai/gpt-oss-120b", "kod ve ajan işleri"), ("openai/gpt-oss-20b", "hızlı")],
    ),
    Provider(
        "openrouter", "OpenRouter", "OpenRouter", "openrouter.ai", "https://openrouter.ai/settings/keys",
        note="tek anahtarla yüzlerce model, ücretsizler dahil",
        chat=[("openrouter/auto", "işe göre en uygun modeli seçer")],
        code=[("openrouter/auto", "işe göre en uygun modeli seçer")],
        login="openrouter",
    ),
    Provider(
        "huggingface", "Hugging Face", "Hugging Face", "huggingface.co", "https://huggingface.co/settings/tokens",
        note="aylık ücretsiz kredi, açık modeller",
        chat=[("openai/gpt-oss-120b", "güçlü, düşünür"), ("meta-llama/Llama-3.3-70B-Instruct", "dengeli")],
        code=[("Qwen/Qwen3-Coder-480B-A35B-Instruct", "kod ve ajan işleri"), ("openai/gpt-oss-120b", "genel")],
        login="huggingface",
    ),
    Provider(
        "mistral", "Mistral", "Mistral", "mistral.ai", "https://console.mistral.ai/api-keys",
        note="ücretsiz kota",
        chat=[("mistral-medium-latest", "önerilen"), ("mistral-large-latest", "açık ağırlıklı, büyük"),
              ("mistral-small-latest", "hızlı, ucuz")],
        code=[("codestral-latest", "kod tamamlama"), ("mistral-medium-latest", "kod ve ajan işleri")],
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
