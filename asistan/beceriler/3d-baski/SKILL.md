---
name: 3d-baski
description: 3D yazıcıda basılacak ölçülü parça (kutu, tutucu, braket, kapak…): build123d ile model, STL/3MF/STEP, denetim
---
# 3D printable part with build123d (tested with build123d 0.13)

Units are millimetres. Use the user's sizes exactly; if a size that decides fit is missing (inner diameter, screw
size, clearance), ask first. Write ONE complete script with run_python, like this template (algebra mode: shapes
are objects, combine them with + and -):

```python
from pathlib import Path
from build123d import *

out = Path("3D"); out.mkdir(exist_ok=True)
L, W, H, hole_d = 40, 20, 10, 5                      # the user's dimensions

part = Box(L, W, H)                                   # centred on the origin
part -= Cylinder(hole_d / 2, H)                       # through hole in the middle (radius, height)
part -= Pos(14, 0, 0) * Cylinder(1.5, H)              # another hole, moved with Pos(x, y, z)
part = fillet(part.edges().filter_by(Axis.Z), radius=2)          # round the vertical edges
part = chamfer(part.edges().group_by(Axis.Z)[-1], length=0.5)    # chamfer the top edges
part = part.moved(Location((0, 0, H / 2)))            # sit on the bed: bottom at z = 0

bb = part.bounding_box()
print("size", round(bb.size.X, 2), round(bb.size.Y, 2), round(bb.size.Z, 2), "solids", len(part.solids()))
export_stl(part, str(out / "parca.stl"))
export_step(part, str(out / "parca.step"))            # for editing in CAD
m = Mesher(); m.add_shape(part); m.write(str(out / "parca.3mf"))
```

Useful pieces:
- `Box(x, y, z)`, `Cylinder(radius, height)`, `Sphere(radius)`, `Cone(bottom_radius, top_radius, height)`
- hollow tube: `Cylinder(15, 30) - Cylinder(13, 30)` (outer radius 15, wall 2 mm)
- move / rotate: `Pos(x, y, z) * shape`, `Rot(0, 0, 45) * shape`; several copies: `for x in (-10, 10): part -= Pos(x, 0, 0) * Cylinder(1.6, H)`
- screw holes (clearance): M3 → 3.4 mm, M4 → 4.5 mm, M5 → 5.5 mm diameter
- press fit / sliding fit on FDM printers: make holes 0.2–0.4 mm larger than the part that goes in
- edges: `part.edges().filter_by(Axis.Z)` (vertical), `part.edges().group_by(Axis.Z)[-1]` (top), `[0]` (bottom)

Pitfalls seen before (do not do these): keyword arguments that do not exist (`offset=`, `height=` on Box),
names that are not in build123d (`Direction`), extruding sketches when a Box/Cylinder difference does the job,
building in metres (0.04 instead of 40), leaving several loose solids (check `len(part.solids()) == 1`).
If the script fails, read the error, change only the failing line, and run again; after two failures fall back to
simple Box/Cylinder differences.

Then:
1. `check_3d_model` on `3D/parca.stl` with `bed` = the user's printer bed from memory ([Ekipman]); if the printer
   is unknown, ask once which printer they have and remember it with its bed size (kind ekipman), e.g.
   "3D yazıcı: Bambu Lab A1, tabla 256x256x256 mm". Fix every problem it reports.
2. `inspect_output` on the STL with a yes/no question that describes the request, e.g. "Is this a 40x20x10 mm
   block with one round hole through the middle?"; if the answer finds a mismatch, fix the script and repeat.
3. Answer with the final size in mm, the file names, and print hints: which face down, whether supports are
   needed (overhangs over 45°), suggested layer height 0.2 mm. The model is shown in the Görsel tab.
