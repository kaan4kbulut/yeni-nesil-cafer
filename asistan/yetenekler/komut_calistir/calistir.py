"""komut_calistir: Çalışma klasöründe kabuk komutu çalıştırır (Linux/macOS: bash, Windows: PowerShell)

Yerleşik yetenek: işi programın `run_command` aracı yapar; çağrı `baglam.arac` ile programın tek araç yolundan
(`Agent._execute_tool` → izin hattı `permissions.py`, araca özgü kapılar, hook'lar) geçer.
"""

from asistan.cekirdek.yetenek import arac_yolu, gerekli

ARAC = "run_command"
# yeteneğin girdisi → aracın girdisi: (araç alanı, varsayılan)
ESLEME = {"komut": ("command", None), "amac": ("purpose", None)}


def arac_cagrisi(girdi: dict) -> tuple[str, dict]:
    """(araç adı, araç girdisi): izin hattı onayı bununla önceden tahmin eder."""
    args = {}
    for ad, (alan, varsayilan) in ESLEME.items():
        deger = girdi.get(ad, varsayilan)
        if deger is not None:
            args[alan] = deger
    return ARAC, args


def calistir(girdi: dict, baglam) -> dict:
    gerekli(girdi, "komut", "amac")
    ad, args = arac_cagrisi(girdi)
    return {"sonuc": arac_yolu(baglam)(ad, args)}
