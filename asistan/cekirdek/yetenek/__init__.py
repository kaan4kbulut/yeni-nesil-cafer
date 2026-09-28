"""Yetenek kayıt defteri (docs/MIMARI.md §6, SEMALAR §1): planlayıcı yalnızca manifestli yetenekleri çağırır.

Her yetenek bir klasör: `manifest.json` + `calistir.py` (`calistir(girdi, baglam) -> dict`) + `test_<ad>.py`.
Yerleşikler programla gelir (`asistan/yetenekler/`), üretilen ve katalogdan gelenler `DATA_DIR/yetenekler/`'de.

- `kayit`: tarama, manifest doğrulama, gereksinim denetimi → aktif / pasif (pasifin nedeni)
- `calistirici`: girdi/çıktı doğrulama; `sandbox: true` → ayrı venv + zaman aşımı + izin dışı erişim engeli
  (`_kum_giris.py` alt süreci); yerleşik `sandbox: false` → süreç içinde, programın tek araç yolu `baglam.arac` ile

Bu modül sandbox alt sürecinde de içe aktarılır (`calistir.py` `YetenekHatasi`'nı buradan alır): yalnızca standart
kütüphane, ağır ya da ayar okuyan içe aktarma yok.
"""

import logging
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from types import MappingProxyType

# SEMALAR §3 hata sınıfları (MIMARI §7)
SINIFLAR = ("model_yetersiz", "eksik_bagimlilik", "eksik_yetenek", "izin", "ag", "mantik", "veri", "kaynak")
IZINLER = ("ag", "dosya_oku", "dosya_yaz", "dosya_sil", "komut")  # + "anahtar:<AYAR_ADI>"

_TIPLER = {"string": "string", "int": "integer", "float": "number", "bool": "boolean", "list": "array",
           "dict": "object"}


class YetenekHatasi(Exception):
    """Yeteneğin bildirdiği hata: `sinif` SEMALAR §3 sınıflarından biri, `mesaj` kullanıcının diliyle."""

    def __init__(self, sinif: str = "mantik", mesaj: str = ""):
        self.sinif = sinif if sinif in SINIFLAR else "mantik"
        self.mesaj = str(mesaj or sinif)
        super().__init__(f"{self.sinif}: {self.mesaj}")


@dataclass
class Baglam:
    """`calistir.py`'ye giden bağlam. `ayar` salt okunur; `arac` yalnızca yerleşik (süreç içi) yeteneklerde dolu:
    programın tek araç yolu (`Agent._execute_tool` → izin hattı), sonuç metni döner, hata `YetenekHatasi`."""

    calisma_klasoru: str
    kademe: str = "orta"
    gunluk: logging.Logger = field(default_factory=lambda: logging.getLogger("asistan.yetenek"))
    ayar: Mapping = field(default_factory=lambda: MappingProxyType({}))
    okuma_kokleri: tuple = ()
    arac: Callable[[str, dict], str] | None = None


def gerekli(girdi, *adlar: str) -> None:
    """`calistir.py`'lerin ilk satırı: zorunlu girdiler boş olamaz; yoksa `YetenekHatasi("veri")`."""
    if not isinstance(girdi, dict):
        raise YetenekHatasi("veri", "girdi bir nesne olmalı")
    eksik = [ad for ad in adlar if girdi.get(ad) in (None, "")]
    if eksik:
        raise YetenekHatasi("veri", "eksik girdi: " + ", ".join(eksik))


def arac_yolu(baglam: "Baglam") -> Callable[[str, dict], str]:
    """Yerleşik yeteneğin araç yolu; yoksa (sandbox, test) açık hata."""
    if baglam.arac is None:
        raise YetenekHatasi("kaynak", "yerleşik yetenek programın araç yolu (izin hattı) olmadan çalışmaz")
    return baglam.arac


def alan_semasi(alan: dict) -> dict:
    """Manifest alanı (`{"tip": "int", ...}`) → JSON şeması."""
    sema: dict = {"type": _TIPLER.get(alan.get("tip"), "string")}
    if alan.get("aciklama"):
        sema["description"] = alan["aciklama"]
    if "secenekler" in alan:
        sema["enum"] = list(alan["secenekler"])
    eleman = alan.get("eleman")
    if sema["type"] == "array" and eleman:
        if isinstance(eleman, str):
            sema["items"] = {"type": _TIPLER.get(eleman, "string")}
        elif isinstance(eleman, dict):
            sema["items"] = {"type": "object", "properties": {
                k: {"type": _TIPLER.get(v, "string")} if isinstance(v, str) else alan_semasi(v)
                for k, v in eleman.items()}}
    return sema


def nesne_semasi(alanlar: dict, zorunlu_hepsi: bool = False) -> dict:
    """Manifestin `girdi`/`cikti` bölümü → nesne şeması (planlayıcı ve doğrulama bunu kullanır)."""
    ozellik = {ad: alan_semasi(a) for ad, a in (alanlar or {}).items()}
    gerekli = [ad for ad, a in (alanlar or {}).items() if zorunlu_hepsi or a.get("zorunlu")]
    return {"type": "object", "properties": ozellik, "required": gerekli}


def cikti_metni(cikti: dict) -> str:
    """Görev motoruna giden metin: tek metin alanlı çıktı olduğu gibi, gerisi JSON."""
    import json

    if isinstance(cikti, dict) and len(cikti) == 1 and isinstance(next(iter(cikti.values())), str):
        return next(iter(cikti.values()))
    return json.dumps(cikti, ensure_ascii=False, indent=1)
