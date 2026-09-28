"""saat_dilimi: şehrin şu anki yerel saati ve UTC farkı.

Sandbox'ta çalışır (izin yalnızca `ag`). Yalnızca standart kütüphane. Sıra: girdi IANA saat dilimiyse ağsız çözülür →
değilse şehir Open-Meteo'nun anahtarsız yer arama API'sinde aranır (ağa giden tek bilgi şehir adı) → ağ yoksa şehir adı
saat dilimi adlarında aranır (Tokyo → Asia/Tokyo). Saat ve fark programın kendi saat dilimi veritabanıyla hesaplanır
(yaz saati dahil); API'nin saatine güvenilmez.
"""

import json
import unicodedata
from datetime import datetime

from asistan.cekirdek.yetenek import YetenekHatasi, gerekli

ARAMA_URL = "https://geocoding-api.open-meteo.com/v1/search"
AG_ZAMAN_ASIMI = 10  # sn
EN_UZUN = 100  # karakter


def sadelestir(metin: str) -> str:
    """Karşılaştırma anahtarı: Türkçe harfler ve aksanlar sade, boşluk/tire alt çizgi, küçük harf."""
    metin = metin.strip().replace("İ", "i").replace("I", "ı").replace("ı", "i").lower()
    metin = unicodedata.normalize("NFKD", metin)
    metin = "".join(c for c in metin if not unicodedata.combining(c))
    return "_".join(metin.replace("-", " ").split())


def dilim_yukle(ad: str):
    """IANA adından `ZoneInfo`; ad geçersizse None. Veritabanı hiç yoksa (Windows, tzdata yok) eksik bağımlılık."""
    from zoneinfo import ZoneInfo, ZoneInfoNotFoundError, available_timezones

    if not available_timezones():
        raise YetenekHatasi("eksik_bagimlilik", "saat dilimi veritabanı yok (Python paketi: tzdata)")
    try:
        return ZoneInfo(ad)
    except (ZoneInfoNotFoundError, ValueError):
        return None


def yerel_eslesme(sehir: str) -> str | None:
    """Şehir adı saat dilimi adlarının son parçasıyla eşleşirse (Tokyo → Asia/Tokyo) o dilim; yoksa None."""
    from zoneinfo import available_timezones

    anahtar = sadelestir(sehir)
    adaylar = sorted(d for d in available_timezones()
                     if "/" in d and not d.startswith(("Etc/", "SystemV/")) and sadelestir(d.rsplit("/", 1)[1]) == anahtar)
    return adaylar[0] if adaylar else None


def ara(sehir: str) -> dict | None:
    """Yer arama API'si: ilk sonuç (`timezone`, `name`, `country`) ya da bulunamadıysa None. Ağ hatası: `ag`."""
    import urllib.error
    import urllib.parse
    import urllib.request

    url = ARAMA_URL + "?" + urllib.parse.urlencode({"name": sehir, "count": 1, "language": "tr", "format": "json"})
    istek = urllib.request.Request(url, headers={"User-Agent": "yeni-nesil-cafer"})
    try:
        with urllib.request.urlopen(istek, timeout=AG_ZAMAN_ASIMI) as cevap:
            veri = json.loads(cevap.read(200_000).decode("utf-8"))
    except (urllib.error.URLError, TimeoutError, OSError) as e:
        raise YetenekHatasi("ag", f"yer arama servisine ulaşılamadı: {getattr(e, 'reason', e)}") from None
    except ValueError:
        raise YetenekHatasi("ag", "yer arama servisi anlaşılmayan cevap verdi") from None
    sonuclar = veri.get("results") if isinstance(veri, dict) else None
    return sonuclar[0] if sonuclar and isinstance(sonuclar[0], dict) else None


def utc_fark_metni(dakika: int) -> str:
    isaret = "+" if dakika >= 0 else "-"
    saat, dk = divmod(abs(dakika), 60)
    return f"UTC{isaret}{saat:02d}:{dk:02d}"


def calistir(girdi: dict, baglam) -> dict:
    gerekli(girdi, "sehir")
    sehir = girdi["sehir"]
    if not isinstance(sehir, str) or not sehir.strip() or len(sehir) > EN_UZUN:
        raise YetenekHatasi("veri", f"sehir 1-{EN_UZUN} karakterlik bir ad olmalı")
    sehir = sehir.strip()

    dilim_adi, yer = None, ""
    if "/" in sehir and dilim_yukle(sehir) is not None:  # zaten IANA adı: ağa gerek yok
        dilim_adi, yer = sehir, sehir.rsplit("/", 1)[1].replace("_", " ")
    else:
        try:
            bulunan = ara(sehir)
        except YetenekHatasi as e:
            dilim_adi = yerel_eslesme(sehir)  # ağ yok: şehir adı saat dilimi adlarında olabilir
            if dilim_adi is None:
                raise
            baglam.gunluk.info("ağ yok (%s); %s yerel eşleşmeyle bulundu", e.mesaj, dilim_adi)
            yer = dilim_adi.rsplit("/", 1)[1].replace("_", " ")
        else:
            if bulunan is None:
                raise YetenekHatasi("veri", f"şehir bulunamadı: {sehir}")
            dilim_adi = str(bulunan.get("timezone") or "")
            yer = ", ".join(str(p) for p in (bulunan.get("name"), bulunan.get("country")) if p)
            if not dilim_adi:
                raise YetenekHatasi("veri", f"{yer or sehir} için saat dilimi bilinmiyor")

    dilim = dilim_yukle(dilim_adi)
    if dilim is None:
        raise YetenekHatasi("eksik_bagimlilik", f"saat dilimi veritabanında yok: {dilim_adi} (tzdata eski olabilir)")
    simdi = datetime.now(dilim)
    fark = int(simdi.utcoffset().total_seconds() // 60)
    return {"saat": simdi.strftime("%Y-%m-%d %H:%M"), "utc_fark": utc_fark_metni(fark),
            "saat_dilimi": dilim_adi, "yer": yer}
