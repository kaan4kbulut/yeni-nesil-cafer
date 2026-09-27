"""iki-adim: veriler.csv'de beş sayı var, ozet.txt'deki toplam doğru. Argümanlar: iş klasörü, son cevap."""
import re
import sys
from pathlib import Path

SAYI = re.compile(r"-?\d+(?:[.,]\d+)?")


def sayilar(metin: str) -> list[float]:
    return [float(s.replace(",", ".")) for s in SAYI.findall(metin)]


is_klasoru = Path(sys.argv[1])
veri = sayilar((is_klasoru / "veriler.csv").read_text(encoding="utf-8", errors="replace"))
if len(veri) != 5:
    sys.exit(f"veriler.csv'de {len(veri)} sayı var (beş olmalı)")
ozet = sayilar((is_klasoru / "ozet.txt").read_text(encoding="utf-8", errors="replace"))
if not any(abs(x - sum(veri)) < 1e-6 for x in ozet):
    sys.exit(f"ozet.txt'de toplam ({sum(veri):g}) yok: {ozet[:5]}")
print("toplam doğru")
