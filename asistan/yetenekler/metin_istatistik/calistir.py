"""metin_istatistik: metin dosyasının satır, kelime, karakter sayısı ve en sık geçen kelimeleri.

Sandbox'ta çalışır (izin yalnızca `dosya_oku`: çalışma klasörü ve kullanıcının okunabilir klasörleri). Yalnızca
standart kütüphane. Göreli yol çalışma klasörüne göredir.
"""

import os
import re
from collections import Counter

from asistan.cekirdek.yetenek import YetenekHatasi, gerekli

EN_KISA = 3  # bundan kısa kelimeler (ve, bu, de…) en sık listesine girmez


def kucuk(metin: str) -> str:
    """Türkçe küçük harf: I → ı, İ → i (str.lower "İ"yi "i̇" yapar)."""
    return metin.replace("I", "ı").replace("İ", "i").lower()


def calistir(girdi: dict, baglam) -> dict:
    gerekli(girdi, "yol")
    en_sik = girdi.get("en_sik", 5)
    if isinstance(en_sik, bool) or not isinstance(en_sik, int) or not 1 <= en_sik <= 50:
        raise YetenekHatasi("veri", "en_sik 1 ile 50 arasında bir tam sayı olmalı")
    yol = os.path.join(baglam.calisma_klasoru, str(girdi["yol"]))
    try:
        with open(yol, encoding="utf-8") as f:
            metin = f.read()
    except FileNotFoundError:
        raise YetenekHatasi("veri", f"dosya yok: {girdi['yol']}") from None
    except IsADirectoryError:
        raise YetenekHatasi("veri", f"bu bir klasör, metin dosyası değil: {girdi['yol']}") from None
    except UnicodeDecodeError:
        raise YetenekHatasi("veri", f"dosya UTF-8 metin değil: {girdi['yol']}") from None
    kelimeler = re.findall(r"\w+", kucuk(metin))
    sayac = Counter(k for k in kelimeler if len(k) >= EN_KISA and not k.isdigit())
    baglam.gunluk.info("%s: %d kelime", girdi["yol"], len(kelimeler))
    return {"satir": len(metin.splitlines()), "kelime": len(kelimeler), "karakter": len(metin),
            "en_sik_kelimeler": [{"kelime": k, "adet": n} for k, n in sayac.most_common(en_sik)]}
