"""arac-fabrikasi: geçici veri klasöründe onaylanmış bir f_ aracı kayıtlı (SINAV_VERI ortam değişkeni).
Argümanlar: iş klasörü, son cevap."""
import json
import os
import sys
from pathlib import Path

araclar = Path(os.environ["SINAV_VERI"]) / "arac-fabrikasi" / "araclar"
adlar = []
for f in sorted(araclar.glob("*/arac.json")) if araclar.is_dir() else []:
    meta = json.loads(f.read_text(encoding="utf-8"))
    if str(meta.get("name", "")).startswith("f_") and not meta.get("disabled"):
        adlar.append(meta["name"])
if not adlar:
    sys.exit("kayıtlı fabrika aracı yok")
print("kayıtlı: " + ", ".join(adlar))
