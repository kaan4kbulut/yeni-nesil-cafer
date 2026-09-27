"""devam-et: "devam et"ten sonra hikaye.txt uzadı. Argümanlar: iş klasörü, son cevap, önceki dosya boyutları (JSON)."""
import json
import sys
from pathlib import Path

if len(sys.argv) < 4:
    sys.exit("önceki boyutlar yok (ilk mesaj bitmedi mi?)")
once = json.loads(Path(sys.argv[3]).read_text(encoding="utf-8")).get("hikaye.txt")
if once is None:
    sys.exit("ilk mesajdan sonra hikaye.txt yoktu")
simdi = (Path(sys.argv[1]) / "hikaye.txt").stat().st_size
if simdi < once + 100:
    sys.exit(f"hikaye.txt uzamadı: {once} → {simdi} bayt")
print(f"{once} → {simdi} bayt")
