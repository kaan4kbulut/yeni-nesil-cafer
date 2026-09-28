"""Süs modelleri (decor3d.py, make_decor_model aracı): her şekil kapalı yüzeyli, tek parça ve tablaya sığar;
araç yalnızca 3D / süs konuşulan sohbette ajana verilir.

manifold3d / trimesh / contourpy ajan kütüphanelerinde yoksa model üreten testler atlanır.

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

# ajan kütüphaneleri: kurulu programın gömülü kütüphaneleri ve kullanıcının kurdukları (geliştirme klasöründe yok)
# gerçek kurulum klasörü: başka bir test dosyası XDG_DATA_HOME'u geçici klasöre almış olabilir (birlikte
# çalışınca kütüphaneler bulunamayıp testler sessizce atlanıyordu)
_VERI = Path.home() / ".local/share"
import kutuphane_yolu  # noqa: E402  (testler/: yalnızca bu Python'la uyumlu kütüphane klasörleri PYTHONPATH'e)

_YOLLAR = kutuphane_yolu.pythonpath_ekle()
_GECICI = tempfile.mkdtemp(prefix="yeni-nesil-cafer-test-")
os.environ["XDG_CONFIG_HOME"] = str(Path(_GECICI) / "ayar")  # kullanıcının gerçek ayar ve verisine dokunulmaz
os.environ["XDG_DATA_HOME"] = str(Path(_GECICI) / "veri")

from asistan import agent as ag  # noqa: E402
from asistan.config import Settings  # noqa: E402
from asistan.profiles import AgentProfile  # noqa: E402
from asistan.tools import Toolbox, ToolError, agent_env, python_exe  # noqa: E402


def var(*moduller: str) -> bool:
    kod = "; ".join(f"import {m}" for m in moduller)
    return subprocess.run([python_exe(), "-c", kod], env=agent_env(), capture_output=True).returncode == 0


def denetle(path: Path) -> dict:
    """STL'i ajanların Python'unda trimesh ile okur: ölçü, kapalı mı, kaç parça."""
    kod = ("import json, sys, trimesh; m = trimesh.load(sys.argv[1], force='mesh'); "
           "print(json.dumps({'size': [float(x) for x in m.extents], 'watertight': bool(m.is_watertight), "
           "'bodies': int(m.body_count)}))")
    out = subprocess.run([python_exe(), "-c", kod, str(path)], env=agent_env(), capture_output=True, text=True)
    import json
    return json.loads(out.stdout)


def resimler(klasor: Path) -> None:
    """Deneme resimleri: beyaz zeminde siyah kedi silueti ve gri tonlu bir desen (litofan / kabartma için)."""
    kod = r"""
import sys
from PIL import Image, ImageDraw
k = sys.argv[1]
im = Image.new("L", (300, 400), 255); d = ImageDraw.Draw(im)
d.ellipse((75, 190, 225, 380), fill=0); d.ellipse((100, 75, 200, 175), fill=0); d.rectangle((140, 165, 160, 200), fill=0)
d.polygon([(107, 105), (120, 45), (145, 85)], fill=0); d.polygon([(193, 105), (180, 45), (155, 85)], fill=0)
im.save(k + "/kedi.png")
g = Image.radial_gradient("L").resize((200, 150)); g.save(k + "/desen.png")
"""
    subprocess.run([python_exe(), "-c", kod, str(klasor)], env=agent_env(), check=True)


@unittest.skipUnless(var("manifold3d", "trimesh", "contourpy", "PIL"), "3D kütüphaneleri kurulu değil")
class SusModelleri(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.box = Toolbox(tempfile.mkdtemp(prefix="sus-"))
        resimler(cls.box.root)

    def test_her_sekil_baskiya_hazir(self):
        istekler = {
            "vazo": {}, "abajur": {"profile": "kum_saati", "pattern": "yildiz", "sides": 7}, "girdap_lamba": {},
            "sus_topu": {"width": 50}, "burgulu_kule": {}, "yildiz": {}, "kafes_kure": {"width": 60},
            "kabartma": {"image": "desen.png"}, "litofan": {"image": "desen.png"},
            "litofan_lamba": {"image": "desen.png", "width": 60, "height": 60}, "siluet": {"image": "kedi.png"},
        }
        for sekil, ek in istekler.items():
            with self.subTest(sekil=sekil):
                sonuc = self.box.run("make_decor_model", {"shape": sekil, "bed": "260x260x260", **ek})
                self.assertIn("watertight (ready to slice)", sonuc)
                self.assertIn("1 body", sonuc)
                stl = self.box.root / "3D" / f"{sekil}.stl"
                bilgi = denetle(stl)
                self.assertTrue(bilgi["watertight"])
                self.assertEqual(bilgi["bodies"], 1)
                self.assertTrue(all(0 < s <= 260 for s in bilgi["size"]), bilgi)

    def test_vazo_modu_ve_olculer(self):
        sonuc = self.box.run("make_decor_model", {"shape": "vazo", "name": "Uzun Vazo", "height": 180, "width": 80,
                                                  "wall": 0, "pattern": "cokgen", "sides": 6, "twist": "90"})
        self.assertIn("VAZO MODU", sonuc)
        bilgi = denetle(self.box.root / "3D" / "uzun_vazo.stl")  # Türkçe ad dosya adına çevrilir
        self.assertAlmostEqual(bilgi["size"][2], 180, delta=0.5)

    def test_tablaya_sigmayan_kucultulur(self):
        sonuc = self.box.run("make_decor_model", {"shape": "vazo", "name": "dev", "height": 400, "bed": "260x260x260"})
        self.assertIn("küçültüldü", sonuc)
        self.assertLessEqual(max(denetle(self.box.root / "3D" / "dev.stl")["size"]), 260)

    def test_yanlis_resim_adinda_gercek_ad_soylenir(self):
        # küçük model üretilen resmin adını kısaltıyor: hata, klasördeki en yeni resmi göstermeli
        (self.box.root / "Resimler").mkdir(exist_ok=True)
        (self.box.root / "kedi.png").rename(self.box.root / "Resimler" / "resim-20260927-181140-0.png")
        with self.assertRaisesRegex(ToolError, "Resimler/resim-20260927-181140-0.png"):
            self.box.run("make_decor_model", {"shape": "siluet", "image": "Resimler/resim.png"})
        (self.box.root / "Resimler" / "resim-20260927-181140-0.png").rename(self.box.root / "kedi.png")

    def test_hatali_istekler(self):
        with self.assertRaises(ToolError):
            self.box.run("make_decor_model", {"shape": "ejderha"})
        with self.assertRaisesRegex(ToolError, "image"):
            self.box.run("make_decor_model", {"shape": "siluet"})
        with self.assertRaises(ToolError):
            self.box.run("make_decor_model", {"shape": "litofan", "image": "/etc/hostname"})
        with self.assertRaises(ToolError):
            self.box.run("make_decor_model", {"shape": "vazo", "profile": "kare"})


class AracSecimi(unittest.TestCase):
    """make_decor_model her sohbette talimatı büyütmesin: yalnızca 3D / süs konuşulunca verilir."""

    def ajan(self, profile=None):
        return ag.Agent(Settings(workspace=str(Path(_GECICI) / "is")), None, profile)

    def adlar(self, a):
        return {s["name"] for s in a.tool_specs}

    def test_yalnizca_3d_ve_sus_sohbetinde(self):
        a = self.ajan()
        a._offer_decor([{"role": "user", "content": "yarın hava nasıl olacak"}])
        self.assertNotIn("make_decor_model", self.adlar(a))
        a._offer_decor([{"role": "user", "content": "salon için burgulu bir vazo tasarla"}])
        self.assertIn("make_decor_model", self.adlar(a))
        b = self.ajan()  # takip mesajında 3D kelimesi yok: geçmişten anlaşılır
        b._offer_decor([{"role": "user", "content": "3D yazıcım için lamba"}, {"role": "assistant", "content": "tamam"},
                        {"role": "user", "content": "biraz daha büyük yap"}])
        self.assertIn("make_decor_model", self.adlar(b))
        b._offer_decor([{"role": "user", "content": "3D yazıcım için lamba"}])
        self.assertEqual(sum(s["name"] == "make_decor_model" for s in b.tool_specs), 1)  # iki kez eklenmez

    def test_dosya_yazamayan_ajana_ve_buluta_verilmez(self):
        yonetici = self.ajan(AgentProfile(id="yonetici", name="Yönetici", tools=[]))
        yonetici._offer_decor([{"role": "user", "content": "3D vazo"}])
        self.assertNotIn("make_decor_model", self.adlar(yonetici))
        bulut = self.ajan()
        bulut.base_system = "bulut"
        bulut._offer_decor([{"role": "user", "content": "3D vazo"}])
        self.assertNotIn("make_decor_model", self.adlar(bulut))

    def test_talimat_susleri_araca_yonlendirir(self):
        self.assertIn("make_decor_model", ag.PRINT3D_NOTE)
        self.assertIn("3d-baski", ag.PRINT3D_NOTE)


if __name__ == "__main__":
    unittest.main()
