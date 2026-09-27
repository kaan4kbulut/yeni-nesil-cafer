"""hepsiburada: cevapta her birinde TL/₺ fiyatı olan en az beş ürün maddesi var. Argümanlar: iş klasörü, son cevap."""
import re
import sys

FIYAT = re.compile(r"\d[\d.,]*\s*(?:TL|₺)|₺\s*\d", re.I)
maddeler = re.findall(r"(?m)^\s*(?:\d+[.)]|[-*•]|\|)\s*\S.*$", sys.argv[2])
fiyatli = [m for m in maddeler if FIYAT.search(m)]
if len(fiyatli) < 5:
    sys.exit(f"fiyatlı ürün maddesi {len(fiyatli)} (en az 5 bekleniyordu)")
print(f"{len(fiyatli)} fiyatlı ürün")
