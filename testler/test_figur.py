"""Resimden 3D figür (figure3d.py, figure3d_worker.py): arka plan silme, girdi hazırlama, ağı baskıya hazırlama;
make_3d_figure aracı yalnızca motor kuruluyken ve 3D / süs sohbetinde verilir.

TripoSR modeli (1,68 GB) testlerde çalıştırılmaz; model gerektirmeyen adımlar ajanların Python'unda denenir.
numpy / scipy / pillow / trimesh / manifold3d / PyMCubes yoksa ilgili testler atlanır.

Çalıştırma (proje kökünde, programın Python'uyla):
    ~/.local/share/yeni-nesil-cafer-app/python/bin/python3 -m unittest discover -s testler -v
"""

import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

KOK = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(KOK))

_VERI = Path(os.environ.get("XDG_DATA_HOME") or Path.home() / ".local/share")
_YOLLAR = [p for p in (_VERI / "yeni-nesil-cafer-app/ajan-kutuphaneleri", _VERI / "yeni-nesil-cafer/python-kutuphaneleri")
           if p.is_dir()]
os.environ["PYTHONPATH"] = os.pathsep.join([*map(str, _YOLLAR), os.environ.get("PYTHONPATH", "")]).strip(os.pathsep)
_GECICI = tempfile.mkdtemp(prefix="yeni-nesil-cafer-test-")
os.environ["XDG_CONFIG_HOME"] = str(Path(_GECICI) / "ayar")  # kullanıcının gerçek ayar ve verisine dokunulmaz
os.environ["XDG_DATA_HOME"] = str(Path(_GECICI) / "veri")

from asistan import agent as ag, figure3d  # noqa: E402
from asistan.config import Settings  # noqa: E402
from asistan.tools import agent_env, python_exe  # noqa: E402

WORKER_DIR = KOK / "asistan"


def calistir(kod: str) -> dict:
    """Kodu ajanların Python'unda çalıştırır (figure3d_worker içe aktarılabilir); son satırdaki JSON döner."""
    out = subprocess.run([python_exe(), "-c", f"import sys; sys.path.insert(0, {str(WORKER_DIR)!r})\n" + kod],
                         env=agent_env(), capture_output=True, text=True, timeout=300)
    if out.returncode != 0:
        raise AssertionError(out.stderr[-2000:])
    return json.loads(out.stdout.strip().splitlines()[-1])


def var(*moduller: str) -> bool:
    kod = "; ".join(f"import {m}" for m in moduller)
    return subprocess.run([python_exe(), "-c", kod], env=agent_env(), capture_output=True).returncode == 0


@unittest.skipUnless(var("numpy", "scipy", "PIL", "trimesh", "manifold3d"), "kütüphaneler kurulu değil")
class GirdiHazirlama(unittest.TestCase):
    def test_zemin_silinir_icteki_acik_renk_kalir(self):
        r = calistir(r"""
import json, tempfile, numpy as np
from PIL import Image, ImageDraw
import figure3d_worker as w
k = tempfile.mkdtemp()
im = Image.new("RGB", (400, 300), (250, 250, 248)); d = ImageDraw.Draw(im)
d.ellipse((100, 50, 300, 250), fill=(90, 60, 30)); d.ellipse((180, 130, 220, 170), fill=(255, 255, 255))  # içte beyaz leke
im.save(k + "/a.png")
m = np.asarray(w.cut_out(k + "/a.png"))[..., 3] > 0
p = w.prepare(w.cut_out(k + "/a.png"))
print(json.dumps({"ic": bool(m[150, 200]), "zemin": bool(m[5, 5]), "oran": float(m.mean()),
                  "boyut": p.size, "kose": list(p.getpixel((2, 2)))}))
""")
        self.assertTrue(r["ic"])  # figürün içindeki beyaz leke figürde kalır
        self.assertFalse(r["zemin"])
        self.assertAlmostEqual(r["oran"], 3.1416 * 100 * 100 / (400 * 300), delta=0.03)
        self.assertEqual(r["boyut"], [512, 512])
        self.assertTrue(all(abs(c - 127) <= 2 for c in r["kose"]))  # TripoSR'ın beklediği gri zemin

    def test_saydam_png_ve_bos_resim(self):
        r = calistir(r"""
import json, tempfile, numpy as np
from PIL import Image, ImageDraw
import figure3d_worker as w
k = tempfile.mkdtemp()
im = Image.new("RGBA", (200, 200), (0, 0, 0, 0)); ImageDraw.Draw(im).rectangle((50, 60, 150, 140), fill=(255, 255, 255, 255))
im.save(k + "/s.png")
m = np.asarray(w.cut_out(k + "/s.png"))[..., 3] > 0  # beyaz nesne saydam zeminde: saydamlıktan bulunur
Image.new("RGB", (200, 200), (255, 255, 255)).save(k + "/bos.png")
try:
    w.cut_out(k + "/bos.png"); hata = ""
except w.FigureError as e:
    hata = str(e)
print(json.dumps({"alan": int(m.sum()), "hata": hata}))
""")
        self.assertAlmostEqual(r["alan"], 101 * 81, delta=200)
        self.assertIn("figür bulunamadı", r["hata"])


@unittest.skipUnless(var("numpy", "trimesh", "manifold3d", "mcubes"), "PyMCubes / manifold3d kurulu değil")
class BaskiyaHazirlama(unittest.TestCase):
    def test_ag_tek_parca_duz_tabanli_ayakli(self):
        r = calistir(r"""
import json, tempfile, numpy as np, mcubes
import figure3d_worker as w, decor3d
g = np.linspace(-1, 1, 64); X, Y, Z = np.meshgrid(g, g, g, indexing="ij")
vol = 60 * np.exp(-((X / 0.5) ** 2 + (Y / 0.35) ** 2 + (Z / 0.8) ** 2))  # yumurta biçimli "figür"
vol[2:6, 2:6, 2:6] = 60  # kopuk küçük parça: atılmalı
v, f = mcubes.marching_cubes(vol, w.THRESHOLD)
body, notes = w.printable(v, f.astype(np.int64), 80.0, True)
k = tempfile.mkdtemp()
info = decor3d.save(body, notes, [260, 260, 260], k + "/fig")
b = body.bounding_box()
print(json.dumps({"info": info, "zmin": b[2], "notes": notes}))
""")
        self.assertTrue(r["info"]["watertight"])
        self.assertEqual(r["info"]["bodies"], 1)
        self.assertAlmostEqual(r["zmin"], 0.0, places=3)
        self.assertAlmostEqual(r["info"]["size_mm"][2], 80 * 0.97 + 2.6, delta=1.0)  # kesilen alt + ayak
        self.assertTrue(any("ayak" in n for n in r["notes"]))
        self.assertTrue(any("kopuk" in n for n in r["notes"]))


class AracSunumu(unittest.TestCase):
    def ajan(self):
        return ag.Agent(Settings(workspace=str(Path(_GECICI) / "is")), None)

    def test_motor_kurulu_degilse_verilmez(self):
        self.assertFalse(figure3d.installed())
        a = self.ajan()
        a._offer_decor([{"role": "user", "content": "3D yazıcı için oturan kedi figürü"}])
        adlar = {s["name"] for s in a.tool_specs}
        self.assertIn("make_decor_model", adlar)
        self.assertNotIn("make_3d_figure", adlar)
        with self.assertRaisesRegex(RuntimeError, "kurulu değil"):
            figure3d.run("x.png", "y")

    def test_motor_kuruluysa_3d_sohbetinde_verilir(self):
        with mock.patch.object(figure3d, "installed", return_value=True):
            a = self.ajan()
            a._offer_decor([{"role": "user", "content": "hava nasıl"}])
            self.assertNotIn("make_3d_figure", {s["name"] for s in a.tool_specs})
            a._offer_decor([{"role": "user", "content": "3D yazıcı için oturan kedi figürü"}])
            self.assertIn("make_3d_figure", {s["name"] for s in a.tool_specs})
        self.assertIn("make_3d_figure", ag.PRINT3D_NOTE)

    def test_arac_resim_ister(self):
        a = self.ajan()
        with self.assertRaisesRegex(ag.ToolError, "image"):
            a._tool_make_3d_figure({})
        with self.assertRaises(ag.ToolError):
            a._tool_make_3d_figure({"image": "/etc/hostname"})


if __name__ == "__main__":
    unittest.main()
