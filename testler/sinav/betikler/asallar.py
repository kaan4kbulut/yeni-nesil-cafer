"""asallar: asallar.txt'deki sayılar tam olarak 1–100 arasındaki 25 asal. Argümanlar: iş klasörü, son cevap."""
import re
import sys
from pathlib import Path

ASALLAR = {n for n in range(2, 101) if all(n % d for d in range(2, int(n ** 0.5) + 1))}
bulunan = {int(s) for s in re.findall(r"\d+", (Path(sys.argv[1]) / "asallar.txt").read_text(encoding="utf-8",
                                                                                           errors="replace"))}
if bulunan != ASALLAR:
    sys.exit(f"eksik: {sorted(ASALLAR - bulunan)[:8]} fazla: {sorted(bulunan - ASALLAR)[:8]}")
print("25 asal tam")
