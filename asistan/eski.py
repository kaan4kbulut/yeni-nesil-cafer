"""Eski modül yolları için geçici uyumluluk (K1). **Bir sonraki sürümde (2.8) kaldırılacak.**

Taşınan bir ad eski yolundan istenirse `DeprecationWarning` verilir ve nesne yeni yerinden getirilir:
    from asistan.dictation import Dictation   # eski modül: `__getattr__ = eski.yonlendir(__name__)`
    from asistan.eski import Dictation        # hangi modülde olduğu bilinmiyorsa
Uyarı normal çalışmada görünmez; testlerde görünür. Yeni kod yeni yolu kullanır.

Uyarısız yeniden dışa aktarılanlar (çok yerde kullanılıyor, uyarı yalnızca gürültü olurdu; K2'de gözden geçirilir):
`config` → `cekirdek.ayar`, `agent.describe_error/Cancelled/ollama_models…` → `cekirdek.saglayici`,
`tools.ToolError/unescape_code/SECRET_FILES` → `cekirdek.araclar`.
"""

import importlib
import warnings

# (eski modül, ad) → yeni modül
TASINANLAR: dict[tuple[str, str], str] = {
    ("asistan.dictation", "Dictation"): "asistan.gui.dikte_kaydi",  # Qt'li mikrofon kaydı arayüze
}


def _getir(eski_modul: str, ad: str, yeni_modul: str, stacklevel: int = 3):
    warnings.warn(f"{eski_modul}.{ad} taşındı, {yeni_modul}.{ad} kullan (eski yol 2.8'de kaldırılacak)",
                  DeprecationWarning, stacklevel=stacklevel)
    return getattr(importlib.import_module(yeni_modul), ad)


def yonlendir(eski_modul: str):
    """Eski modül için PEP 562 `__getattr__`: yalnızca TASINANLAR'daki adları yönlendirir."""

    def __getattr__(ad: str):
        yeni = TASINANLAR.get((eski_modul, ad))
        if yeni is None:
            raise AttributeError(f"module {eski_modul!r} has no attribute {ad!r}")
        return _getir(eski_modul, ad, yeni)

    return __getattr__


def __getattr__(ad: str):
    """`from asistan.eski import X`: X hangi eski modülden taşındıysa yeni yerinden."""
    for (eski_modul, eski_ad), yeni in TASINANLAR.items():
        if eski_ad == ad:
            return _getir(eski_modul, ad, yeni)
    raise AttributeError(f"module 'asistan.eski' has no attribute {ad!r}")
