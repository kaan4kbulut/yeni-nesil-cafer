"""dosya_duzenle: Var olan dosyada tam olarak bir kez geçen bir metin parçasını değiştirir

Yerleşik yetenek: işi programın `edit_file` aracı yapar; çağrı `baglam.arac` ile programın tek araç yolundan
(`Agent._execute_tool` → izin hattı `permissions.py`, araca özgü kapılar, hook'lar) geçer.
"""

from asistan.cekirdek.yetenek import arac_yolu, gerekli

ARAC = "edit_file"
# yeteneğin girdisi → aracın girdisi: (araç alanı, varsayılan)
ESLEME = {"yol": ("path", None), "eski": ("old_text", None), "yeni": ("new_text", None)}


def arac_cagrisi(girdi: dict) -> tuple[str, dict]:
    """(araç adı, araç girdisi): izin hattı onayı bununla önceden tahmin eder."""
    args = {}
    for ad, (alan, varsayilan) in ESLEME.items():
        deger = girdi.get(ad, varsayilan)
        if deger is not None:
            args[alan] = deger
    return ARAC, args


def calistir(girdi: dict, baglam) -> dict:
    gerekli(girdi, "yol", "eski", "yeni")
    ad, args = arac_cagrisi(girdi)
    return {"sonuc": arac_yolu(baglam)(ad, args)}
