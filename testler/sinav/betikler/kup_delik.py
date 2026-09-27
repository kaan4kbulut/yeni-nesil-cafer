"""kup-delik: 20 mm küpte 5 mm delik gerçekten var (hacim: dolu küp 8000 mm³, boydan boya delikle ~7607 mm³).
Ajanların Python'unda (trimesh) çalışır. Argümanlar: iş klasörü, son cevap."""
import sys
from pathlib import Path

import trimesh

hacimler = []
for p in sorted(Path(sys.argv[1]).rglob("*.stl")):
    if "ekler" in p.parts:
        continue
    m = trimesh.load(p, force="mesh")
    if m.is_watertight:
        hacimler.append((p.name, float(m.volume)))
        if 7000 <= m.volume <= 7950:
            print(f"{p.name}: {m.volume:.0f} mm³")
            sys.exit(0)
sys.exit("delikli küp hacmi tutmuyor: " + (", ".join(f"{a} {h:.0f} mm³" for a, h in hacimler) or "kapalı STL yok"))
