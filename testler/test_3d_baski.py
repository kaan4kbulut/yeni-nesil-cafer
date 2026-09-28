"""3D baskı: check_3d_model aracı (trimesh) ve build123d ile ölçülü parça; talimat notu yalnızca 3D isteklerinde.

trimesh / build123d ajan kütüphanelerinde yoksa ilgili testler atlanır.

Çalıştırma (proje kökünde, programın Python'uyla):
    ~/.local/share/yeni-nesil-cafer-app/python/bin/python3 -m unittest discover -s testler -v
"""

import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

KOK = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(KOK))

# ajan kütüphaneleri gerçek veri klasöründe: ayarlar geçici klasöre gitse de trimesh / build123d oradan bulunsun
_VERI = Path.home() / ".local/share"  # gerçek kurulum: başka test dosyası XDG_DATA_HOME'u geçiciye almış olabilir
_KUTUPHANE = next((d for d in (_VERI / "yeni-nesil-cafer/python-kutuphaneleri", _VERI / "yerel-asistan/python-kutuphaneleri")
                   if d.is_dir()), _VERI / "yeni-nesil-cafer/python-kutuphaneleri")  # eski adlı klasör henüz taşınmadıysa
import kutuphane_yolu  # noqa: E402  (yalnızca bu Python'la uyumlu kütüphane klasörleri)

kutuphane_yolu.pythonpath_ekle()
_GECICI = tempfile.mkdtemp(prefix="yeni-nesil-cafer-test-")
os.environ["XDG_CONFIG_HOME"] = str(Path(_GECICI) / "ayar")
os.environ["XDG_DATA_HOME"] = str(Path(_GECICI) / "veri")

from asistan import agent as ag  # noqa: E402
from asistan.tools import Toolbox, ToolError, agent_env, python_exe  # noqa: E402


def var(modul: str) -> bool:
    return subprocess.run([python_exe(), "-c", f"import {modul}"], env=agent_env(), capture_output=True).returncode == 0


def kutu_stl(path: Path, x: float, y: float, z: float, acik: bool = False):
    """Eksenlere hizalı kutu (ASCII STL); acik: üst yüz yok (kapalı olmayan yüzey)."""
    v = [(0, 0, 0), (x, 0, 0), (x, y, 0), (0, y, 0), (0, 0, z), (x, 0, z), (x, y, z), (0, y, z)]
    f = [(0, 2, 1), (0, 3, 2), (0, 1, 5), (0, 5, 4), (1, 2, 6), (1, 6, 5), (2, 3, 7), (2, 7, 6), (3, 0, 4),
         (3, 4, 7)] + ([] if acik else [(4, 5, 6), (4, 6, 7)])
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("solid k\n" + "".join(
        "facet normal 0 0 0\nouter loop\n" + "".join(f"vertex {a} {b} {c}\n" for a, b, c in (v[i], v[j], v[k]))
        + "endloop\nendfacet\n" for i, j, k in f) + "endsolid k\n")


@unittest.skipUnless(var("trimesh"), "trimesh kurulu değil")
class DenetimTesti(unittest.TestCase):
    def setUp(self):
        self.box = Toolbox(tempfile.mkdtemp(prefix="uc-boyut-"))

    def test_kapali_kutu_hazir(self):
        kutu_stl(self.box.root / "3D" / "kutu.stl", 40, 20, 10)
        out = self.box.run("check_3d_model", {"path": "3D/kutu.stl"})
        self.assertIn("40.0 × 20.0 × 10.0 mm", out)
        self.assertIn("volume: 8.0 cm³", out)
        self.assertIn("OK: watertight", out)

    def test_acik_yuzey_yakalanir(self):
        kutu_stl(self.box.root / "acik.stl", 40, 20, 10, acik=True)
        out = self.box.run("check_3d_model", {"path": "acik.stl"})
        self.assertIn("NOT watertight", out)

    def test_tablaya_sigmayan_ve_cok_kucuk(self):
        kutu_stl(self.box.root / "buyuk.stl", 300, 20, 10)
        self.assertIn("does not fit the 220x220x250", self.box.run("check_3d_model", {"path": "buyuk.stl"}))
        self.assertIn("OK", self.box.run("check_3d_model", {"path": "buyuk.stl", "bed": "350x350x350"}))
        kutu_stl(self.box.root / "metre.stl", 0.04, 0.02, 0.01)  # 40 mm yerine 0.04 çizilmiş
        self.assertIn("metres or centimetres", self.box.run("check_3d_model", {"path": "metre.stl"}))

    def test_calisma_klasoru_disi_ve_bozuk_tabla(self):
        with self.assertRaises(ToolError):
            self.box.run("check_3d_model", {"path": "/etc/passwd"})
        kutu_stl(self.box.root / "k.stl", 1, 1, 1)
        with self.assertRaises(ToolError):
            self.box.run("check_3d_model", {"path": "k.stl", "bed": "220; rm -rf ~"})


@unittest.skipUnless(var("build123d") and var("trimesh"), "build123d ya da trimesh kurulu değil")
class OlculuParcaTesti(unittest.TestCase):
    def test_delikli_blok(self):
        box = Toolbox(tempfile.mkdtemp(prefix="uc-parca-"))
        stl = box.root / "3D" / "blok.stl"
        stl.parent.mkdir()
        kod = ("from build123d import *\n"
               "with BuildPart() as p:\n"
               "    Box(40, 20, 10)\n"
               "    Hole(radius=2.5)\n"
               f"export_stl(p.part, {str(stl)!r})\n")
        out = subprocess.run([python_exe(), "-c", kod], env=agent_env(), capture_output=True, text=True, timeout=300)
        self.assertEqual(out.returncode, 0, out.stderr[-500:])
        rapor = box.run("check_3d_model", {"path": "3D/blok.stl"})
        self.assertIn("40.0 × 20.0 × 10.0 mm", rapor)
        self.assertIn("OK: watertight", rapor)
        hacim = float(rapor.split("volume: ")[1].split(" ")[0])
        self.assertAlmostEqual(hacim, (40 * 20 * 10 - 3.14159 * 2.5 ** 2 * 10) / 1000, delta=0.05)  # delik çıkarıldı


class TalimatTesti(unittest.TestCase):
    def test_not_yalnizca_3d_isteklerinde(self):
        from asistan.config import Settings

        a = ag.Agent(Settings(workspace=str(Path(_GECICI) / "is")), object())
        a.user_text = "Telefon tutucu yap, 3D yazıcıda basacağım"
        self.assertIn("check_3d_model", a._system())
        a.user_text = "Bu Excel dosyasını özetle"
        self.assertNotIn("check_3d_model", a._system())


if __name__ == "__main__":
    unittest.main()
