"""bildirim_gonder: kullanıcının telefonuna kısa bildirim (ntfy / Telegram)

Yerleşik yetenek: işi programın `send_notification` aracı yapar (`cekirdek/bildirim.py`); çağrı `baglam.arac` ile tek
araç yolundan geçer (izin hattı: internete gönderir → her seferinde onay / güvenlik ajanı).
"""

from asistan.cekirdek.yetenek import arac_yolu, gerekli

ARAC = "send_notification"
ESLEME = {"baslik": ("title", None), "metin": ("text", None)}


def arac_cagrisi(girdi: dict) -> tuple[str, dict]:
    return ARAC, {alan: girdi[ad] for ad, (alan, _v) in ESLEME.items() if ad in girdi}


def calistir(girdi: dict, baglam) -> dict:
    gerekli(girdi, "baslik", "metin")
    ad, args = arac_cagrisi(girdi)
    return {"sonuc": arac_yolu(baglam)(ad, args)}
