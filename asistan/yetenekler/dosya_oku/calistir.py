"""dosya_oku: UTF-8 metin dosyasını satır numaralarıyla okur

Yerleşik yetenek: işi programın `read_file` aracı yapar; çağrı `baglam.arac` ile programın tek araç yolundan
(`Agent._execute_tool` → izin hattı `permissions.py`, araca özgü kapılar, hook'lar) geçer.
"""

from asistan.cekirdek.yetenek import arac_yolu, gerekli

ARAC = "read_file"
# yeteneğin girdisi → aracın girdisi: (araç alanı, varsayılan)
ESLEME = {"yol": ("path", None), "baslangic_satiri": ("start_line", None), "en_cok_satir": ("max_lines", None)}


def arac_cagrisi(girdi: dict) -> tuple[str, dict]:
    """(araç adı, araç girdisi): izin hattı onayı bununla önceden tahmin eder."""
    args = {}
    for ad, (alan, varsayilan) in ESLEME.items():
        deger = girdi.get(ad, varsayilan)
        if deger is not None:
            args[alan] = deger
    return ARAC, args


def calistir(girdi: dict, baglam) -> dict:
    gerekli(girdi, "yol")
    ad, args = arac_cagrisi(girdi)
    return {"sonuc": arac_yolu(baglam)(ad, args)}
