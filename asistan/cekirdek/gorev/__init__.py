"""Görev motoru (docs/MIMARI.md §5): Anla → Planla → Uygula → Doğrula; adım adım checkpoint, kaldığı yerden devam.

Modüller: `anlayici` (niyet, kısıtlar, tek soru), `planlayici` (şema-kısıtlı plan), `yurutucu` (adım koşma, yer tutucu,
onay bekleme), `dogrulayici` (önce programın kanıtı, sonra hızlı model), `durum` (SQLite deposu), `ajan` (yetenekleri
`Agent._execute_tool` izin hattına bağlayan uyarlayıcı), `model` (yönlendiriciyle model çağrısı), `komut` (CLI).

Motor iki arayüze bağlıdır; ikisi de sahtesiyle sınanır:
- `Yetenekler`: planlayıcının çağırabileceği işler. K5'ten beri yalnızca manifestli yetenekler (`yetenek/kayit.py`,
  uyarlayıcı `ajan.AjanYetenekleri`); isteğe bağlı `pasifler()` kayıtlı ama kullanılamayanları anlayıcıya verir.
- `ModelCagir`: rol/görev türüyle model çağrısı (`model.YonlendiriciModeli`), `secim` kararını da verir.
"""

from dataclasses import dataclass, field
from typing import Protocol

METIN_URET = "metin_uret"  # model adımı (özet, yazı, sınıflandırma): araç değil, yönlendiricinin seçtiği model
METIN_URET_SEMASI = {
    "type": "object",
    "properties": {"talimat": {"type": "string"}, "veri": {"type": "string"}},
    "required": ["talimat"],
}
METIN_URET_ACIKLAMA = ("Write text with a language model (summary, report, classification, answer) from the given "
                       "instruction and data. Inputs: talimat (what to write), veri (text to work on, e.g. "
                       "{{adim_1.sonuc}}).")


@dataclass
class Cikti:
    """Bir yeteneğin sonucu."""

    metin: str
    hata: bool = False
    onay_bekliyor: bool = False  # izin hattı kullanıcıya sordu, cevap henüz yok: adım bekler


@dataclass
class Cevap:
    """Model cevabı. `veri`: şema istendiyse şemaya uyan nesne (uymadıysa None, `hatalar` dolu)."""

    metin: str
    veri: dict | None = None
    secim: dict = field(default_factory=dict)
    hatalar: list = field(default_factory=list)


class Yetenekler(Protocol):
    def listele(self) -> list[dict]:
        """[{"ad", "aciklama", "girdi_semasi", "salt_okur"}] — planlayıcıya giden liste."""

    def onay_gerekir(self, ad: str, girdi: dict) -> bool:
        """İzin hattı bu çağrıyı kullanıcıya soracak mı? (planda `onay_gerekli`)"""

    def calistir(self, ad: str, girdi: dict, onayli: bool = False) -> Cikti:
        """Yeteneği çalıştırır. `onayli`: kullanıcı bu adımı onayladı (izin hattı sorarsa cevap "evet")."""


class ModelCagir(Protocol):
    def __call__(self, rol: str, mesajlar: list, sistem: str = "", sema: dict | None = None) -> Cevap:
        """`rol`: yönlendiricinin rolü ya da görev türü ("planlama", "ozet", "siniflandirma"…)."""

    def secim(self, rol: str) -> dict:
        """Çağırmadan karar: {"saglayici", "model", "neden"} (plana yazılır)."""


class ModelYok(RuntimeError):
    """Bu rol için çalışan model yok (çevrimdışı, Ollama kapalı…)."""
