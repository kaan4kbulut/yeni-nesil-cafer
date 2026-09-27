"""Model sağlayıcıları: hepsi `temel.Saglayici` arayüzünü uygular (`sohbet`, `akis`, `saglik`, `maliyet`).

`bul(ad, ...)` sohbetin sağlayıcı kimliğinden ("ollama", "claude", "api:<id>", "cli:<ad>") nesneyi kurar.
`hata_metni` sağlayıcı hatalarını kullanıcıya gösterilecek Türkçe metne çevirir (eski adı `agent.describe_error`).
"""

import anthropic
import httpx

from .temel import ARAC, DUSUNCE, METIN, SON, Iptal, Parca, Saglayici, SaglayiciHatasi, Saglik, Yanit  # noqa: F401


def bul(ad: str, ayarlar=None, baglantilar: list | None = None) -> Saglayici:
    """Sağlayıcı kimliğinden nesne. `ayarlar`: `cekirdek.ayar.Settings` (model ve adresler buradan)."""
    from ... import cli_agents

    if ad == "ollama":
        from .ollama import OllamaSaglayici

        return OllamaSaglayici(getattr(ayarlar, "ollama_url", ""), getattr(ayarlar, "ollama_model", ""))
    if ad == "claude":
        from ...connections import ANTHROPIC_KEY
        from ...keystore import get_secret
        from .. import ayar
        from .claude import ClaudeSaglayici, istemci

        return ClaudeSaglayici(lambda: istemci(get_secret(ANTHROPIC_KEY)), getattr(ayarlar, "claude_model", ""),
                               anahtar_getir=lambda: get_secret(ANTHROPIC_KEY),
                               anahtar_env=ayar.deger("saglayici.claude.anahtar_env"))
    if cli_agents.is_cli(ad):
        from .cli_ajan import CliAjanSaglayici

        return CliAjanSaglayici(ad, (getattr(ayarlar, "extra", None) or {}).get("cli_model", ""))
    if ad.startswith("api:"):
        from .openai_uyumlu import OpenAIUyumluSaglayici

        conn = next((c for c in baglantilar or [] if c.id == ad[4:]), None)
        if conn is None:
            raise KeyError(f"API bağlantısı yok: {ad}")
        return OpenAIUyumluSaglayici(conn, (getattr(ayarlar, "api_models", None) or {}).get(conn.id, ""))
    raise KeyError(f"bilinmeyen sağlayıcı: {ad}")


def hata_metni(exc: Exception) -> str:
    """Hataları kullanıcıya gösterilecek Türkçe metne çevirir."""
    if isinstance(exc, anthropic.AuthenticationError):
        return "Claude API anahtarı geçersiz ya da eksik. Sol paneldeki API'ler sekmesinden anahtarını gir."
    if isinstance(exc, anthropic.RateLimitError):
        return "Claude API hız sınırına ulaşıldı. Biraz bekleyip tekrar dene."
    if isinstance(exc, anthropic.APIStatusError):
        return f"Claude API hatası ({exc.status_code}): {exc.message}"
    if isinstance(exc, anthropic.APIConnectionError):
        return "Claude API'ye bağlanılamadı. İnternet bağlantını kontrol et."
    if isinstance(exc, httpx.ConnectError):
        return "Ollama'ya bağlanılamadı. `ollama serve` çalışıyor mu?"
    if isinstance(exc, TypeError) and "api_key" in str(exc).lower():
        return "Claude API anahtarı bulunamadı. Sol paneldeki API'ler sekmesinden anahtarını gir."
    return f"{type(exc).__name__}: {exc}"
