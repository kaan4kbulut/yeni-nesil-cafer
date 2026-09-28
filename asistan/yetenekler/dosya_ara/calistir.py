"""dosya_ara: Dosyaların içinde metin arar (grep gibi)

Yerleşik yetenek: işi programın `search_files` aracı yapar; çağrı `baglam.arac` ile programın tek araç yolundan
(`Agent._execute_tool` → izin hattı `permissions.py`, araca özgü kapılar, hook'lar) geçer.
"""

from asistan.cekirdek.yetenek import arac_yolu, gerekli

ARAC = "search_files"
# yeteneğin girdisi → aracın girdisi: (araç alanı, varsayılan)
ESLEME = {"desen": ("pattern", None), "yol": ("path", "."), "en_cok": ("max_results", 200)}


def arac_cagrisi(girdi: dict) -> tuple[str, dict]:
    """(araç adı, araç girdisi): izin hattı onayı bununla önceden tahmin eder."""
    args = {}
    for ad, (alan, varsayilan) in ESLEME.items():
        deger = girdi.get(ad, varsayilan)
        if deger is not None:
            args[alan] = deger
    return ARAC, args


def calistir(girdi: dict, baglam) -> dict:
    gerekli(girdi, "desen")
    ad, args = arac_cagrisi(girdi)
    return {"sonuc": arac_yolu(baglam)(ad, args)}
