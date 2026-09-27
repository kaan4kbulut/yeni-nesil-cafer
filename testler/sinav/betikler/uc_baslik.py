"""duckduckgo: cevapta en az üç maddelik sonuç listesi var. Argümanlar: iş klasörü, son cevap."""
import re
import sys

maddeler = re.findall(r"(?m)^\s*(?:\d+[.)]|[-*•])\s+\S.{3,}", sys.argv[2])
if len(maddeler) < 3:
    sys.exit(f"{len(maddeler)} madde (en az 3 başlık bekleniyordu)")
print(f"{len(maddeler)} madde")
