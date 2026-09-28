"""tarayici: gerçek tarayıcıda sayfayı açar; okur ya da ürün/ilan listesini yapısal çıkarır.

Yerleşik yetenek: `browser_open` → `browser_read` / `browser_extract_items` araçları `baglam.arac` ile programın tek
araç yolundan (izin hattı, `browser.gate`, hook'lar) geçer. Tarayıcı motoru yoksa ya da kademe düşükse pasif
(`hazir_mi`). Ürün listesi yoksa `YetenekHatasi("veri")`: satır uydurulmaz.
"""

import json

from asistan.cekirdek.yetenek import YetenekHatasi, arac_yolu, gerekli

ARAC = "browser_open"


def hazir_mi() -> str:
    """Boş: kullanılabilir. Değilse neden (Yetenekler penceresinde görünür)."""
    from asistan import browser
    from asistan.cekirdek import profil

    if browser.available():
        return ""
    return profil.kapali_notu("tarayici") or "tarayıcı motoru (Chromium) kurulu değil"


def arac_cagrisi(girdi: dict) -> tuple[str, dict]:
    """İlk araç çağrısı (izin tahmini için): sayfayı açmak."""
    return ARAC, {"url": str(girdi.get("url") or "")}


def urun_satirlari(metin: str) -> list[dict]:
    """`browser_extract_items` sonucu: ilk satır başlık, sonrası satır başına bir JSON nesnesi."""
    liste = []
    for satir in (metin or "").splitlines()[1:]:
        try:
            o = json.loads(satir)
        except ValueError:
            continue
        if isinstance(o, dict) and o.get("ad") and isinstance(o.get("fiyat"), (int, float)):
            liste.append({"ad": str(o["ad"]), "fiyat": float(o["fiyat"]),
                          "para_birimi": str(o.get("para_birimi") or ""), "url": str(o.get("url") or "")})
    return liste


def calistir(girdi: dict, baglam) -> dict:
    gerekli(girdi, "url")
    arac = arac_yolu(baglam)
    islem = girdi.get("islem") or "oku"
    if islem not in ("oku", "urunler"):
        raise YetenekHatasi("veri", f"islem 'oku' ya da 'urunler' olmalı ({islem!r} geldi)")
    acilis = arac(*arac_cagrisi(girdi))
    bul = str(girdi.get("bul") or "")
    if islem == "oku":
        return {"sonuc": arac("browser_read", {"find": bul}) if bul else acilis}
    urunler = urun_satirlari(arac("browser_extract_items", {"find": bul, "max_items": 30}))
    if not urunler:
        raise YetenekHatasi("veri", "sayfada ürün listesi bulunamadı")
    return {"urunler": urunler}
