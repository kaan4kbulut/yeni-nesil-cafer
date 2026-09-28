"""İnternet kurulumu (bootstrap.py) ve ilk kurulum sihirbazı: indirme doğrulaması, kurulu parçanın atlanması,
Ollama eksikse sihirbazın kendisi kurması; ayrıca 2026-09-27 canlı kaydında bulunan hatalar: Sonuçlar klasörü
okunabilir, yöneticinin uydurduğu dosyalar "istenen dosya" sayılmaz, 3D önizleme yumuşak gölgeli GLB.

Çalıştırma (proje kökünde, programın Python'uyla):
    ~/.local/share/yeni-nesil-cafer-app/python/bin/python3 -m unittest discover -s testler -v
"""

import hashlib
import os
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

KOK = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(KOK))
_VERI = Path.home() / ".local/share"  # ajan kütüphaneleri gerçek kurulumdan (trimesh)
import kutuphane_yolu  # noqa: E402  (testler/: yalnızca bu Python'la uyumlu kütüphane klasörleri PYTHONPATH'e)

_YOLLAR = kutuphane_yolu.pythonpath_ekle()
_GECICI = tempfile.mkdtemp(prefix="yeni-nesil-cafer-test-")
os.environ["XDG_CONFIG_HOME"] = str(Path(_GECICI) / "ayar")  # kullanıcının gerçek ayar ve verisine dokunulmaz
os.environ["XDG_DATA_HOME"] = str(Path(_GECICI) / "veri")
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication  # noqa: E402

from asistan import agent as ag, bootstrap, results  # noqa: E402
from asistan.config import Settings  # noqa: E402
from asistan.tools import Toolbox, agent_env, program_roots, python_exe  # noqa: E402

APP = QApplication.instance() or QApplication([])


class Indirme(unittest.TestCase):
    def setUp(self):
        self.k = Path(tempfile.mkdtemp(dir=_GECICI))
        self.kaynak = self.k / "kaynak.bin"
        self.kaynak.write_bytes(os.urandom(300_000))
        self.sha = hashlib.sha256(self.kaynak.read_bytes()).hexdigest()

    def test_indirir_dogrular_ve_ilerleme_bildirir(self):
        olaylar = []
        bootstrap.indir(self.kaynak.as_uri(), self.k / "inen.bin", self.sha, "deneme", lambda p, m: olaylar.append(m))
        self.assertEqual((self.k / "inen.bin").read_bytes(), self.kaynak.read_bytes())
        self.assertFalse((self.k / "inen.bin.part").exists())
        bootstrap.indir("file:///yok/boyle-bir-dosya", self.k / "inen.bin", self.sha, "deneme")  # zaten var: inmez

    def test_ozet_tutmazsa_silinir(self):
        with self.assertRaises(SystemExit):
            bootstrap.indir(self.kaynak.as_uri(), self.k / "bozuk.bin", "0" * 64, "deneme")
        self.assertFalse((self.k / "bozuk.bin").exists() or (self.k / "bozuk.bin.part").exists())

    def test_kurulu_ollama_yeniden_inmez(self):
        uyg = self.k / "uyg"
        (uyg / "ollama").mkdir(parents=True)
        (uyg / "ollama" / ".surum").write_text(bootstrap.OLLAMA_SURUM)
        with mock.patch.object(bootstrap, "indir", side_effect=AssertionError("indirmemeliydi")):
            bootstrap.ollama(uyg)


class MacKurulumu(unittest.TestCase):
    """macOS burada çalıştırılamaz: Mac'miş gibi davranılarak seçimler, Ollama arşivi ve bilgi metinleri denenir."""

    def mac(self, mimari="arm64"):
        p1 = mock.patch.object(bootstrap.sys, "platform", "darwin")
        p2 = mock.patch.object(bootstrap.platform, "machine", return_value=mimari)
        p1.start(); p2.start()
        self.addCleanup(p1.stop); self.addCleanup(p2.stop)

    def test_cipe_gore_liste_ve_rocm_yok(self):
        uyg = Path(tempfile.mkdtemp(dir=_GECICI))
        (uyg / "kurulum").mkdir()
        for ad in ("program-kutuphaneleri.txt", "program-kutuphaneleri-mac-arm64.txt"):
            (uyg / "kurulum" / ad).write_text("x==1\n")
        self.mac("arm64")
        self.assertEqual(bootstrap._sistem(), "mac")
        self.assertEqual(bootstrap._liste(uyg, "program-kutuphaneleri.txt").name, "program-kutuphaneleri-mac-arm64.txt")
        self.assertFalse(bootstrap._amd_kart())
        self.mac("x86_64")  # Intel listesi yoksa genel liste
        self.assertEqual(bootstrap._liste(uyg, "program-kutuphaneleri.txt").name, "program-kutuphaneleri.txt")

    def test_ollama_tgz_acilir_ve_bulunur(self):
        import io
        import tarfile

        from asistan import sysinfo

        uyg = Path(tempfile.mkdtemp(dir=_GECICI))
        arsiv = Path(tempfile.mkdtemp(dir=_GECICI)) / "ollama-darwin.tgz"
        with tarfile.open(arsiv, "w:gz") as t:  # gerçek arşiv gibi: ollama kökte
            veri = b"#!/bin/sh\necho ollama\n"
            bilgi = tarfile.TarInfo("ollama"); bilgi.size, bilgi.mode = len(veri), 0o755
            t.addfile(bilgi, io.BytesIO(veri))
        sha = hashlib.sha256(arsiv.read_bytes()).hexdigest()
        self.mac("arm64")
        with mock.patch.dict(bootstrap.OLLAMA_DOSYALARI, {"mac": [("ollama-darwin.tgz", sha)]}), \
                mock.patch.object(bootstrap, "OLLAMA_URL", arsiv.parent.as_uri() + "/{}"):
            bootstrap.ollama(uyg)
        self.assertTrue((uyg / "ollama" / "ollama").is_file())
        with mock.patch.object(sysinfo, "OLLAMA_DIR", uyg / "ollama"), mock.patch.object(sysinfo.shutil, "which",
                                                                                         return_value=None):
            self.assertEqual(sysinfo.ollama_path(), str(uyg / "ollama" / "ollama"))

    def test_ekran_karti_bilgisi_ve_betik(self):
        from asistan import gpu

        with mock.patch.object(gpu.platform, "system", return_value="Darwin"), \
                mock.patch.object(gpu.platform, "machine", return_value="arm64"):
            rapor = gpu.check([], Settings(), False)
        self.assertTrue(rapor.ok)
        self.assertIn("Metal", rapor.text)
        # eski tam paketleyici (Kur.command) NOTLAR/arsiv/paketleme'ye taşındı; macOS kurulumu artık CI'nin .dmg'si


class SihirbazOllama(unittest.TestCase):
    def sihirbaz(self, kurulu: bool, calisiyor: bool = False):
        from asistan import sysinfo
        from asistan.gui import setup_wizard

        info = sysinfo.SystemInfo(os_name="Linux", ollama_installed=kurulu, ollama_running=calisiyor)
        self.scan = mock.patch.object(sysinfo, "scan", return_value=info)
        self.scan.start()
        self.addCleanup(self.scan.stop)
        return setup_wizard.SetupWizard(Settings(workspace=str(Path(_GECICI) / "is")))

    def test_yoksa_indir_kur_dugmesi_ve_kurulum(self):
        from asistan import sysinfo

        w = self.sihirbaz(kurulu=False)
        w._scan()
        self.assertEqual(w.copy_btn.text(), "Ollama'yı indir ve kur")
        cagrilar = []
        with mock.patch.object(bootstrap, "ollama", side_effect=lambda uyg, ilerleme=None: (
                cagrilar.append(uyg), ilerleme(50, "Ollama: %50"))), \
                mock.patch.object(sysinfo, "ensure_ollama", return_value=True):
            w._ollama_action()
            son = time.time() + 5
            while w._ollama_busy and time.time() < son:
                APP.processEvents()
                time.sleep(0.02)
        self.assertEqual(cagrilar, [sysinfo.APP_DIR])
        self.assertFalse(w._ollama_busy)

    def test_kurulu_ama_kapaliysa_kendisi_baslatir(self):
        from asistan import sysinfo

        w = self.sihirbaz(kurulu=True)
        with mock.patch.object(sysinfo, "ensure_ollama", return_value=False) as baslat:
            w._scan()
        baslat.assert_called_once()  # komut yazdırmadan önce kendisi dener


class CanliKayitHatalari(unittest.TestCase):
    def test_sonuclar_klasoru_okunabilir_yazilamaz(self):
        masa = Path(tempfile.mkdtemp(dir=_GECICI))
        with mock.patch.object(results, "desktop", return_value=masa):
            self.assertIn(results.project_dir().resolve(), program_roots())
            box = Toolbox(tempfile.mkdtemp(dir=_GECICI))
            ornek = results.results_dir() / "Örnekler"
            ornek.mkdir(parents=True)
            (ornek / "vazo.stl").write_text("solid v\nendsolid v\n")
            self.assertIn("vazo.stl", box.run("list_files", {"path": str(ornek)}))
            with self.assertRaises(Exception):
                box.run("write_file", {"path": str(ornek / "yeni.txt"), "content": "x"})

    def test_uydurma_dosyalar_istenmez(self):
        a = ag.Agent(Settings(workspace=str(Path(_GECICI) / "is2")), None)
        a.user_text = "bu klasördeki modelleri düzenle ve 3D yazıcıya hazırla"
        a.focus = "run_python('model_duzenleme.py') ile olasiliklar.txt dosyasını düzenle"  # planlayıcının uydurması
        a.actions_tried = a.actions_done = 1  # bir adım başarıyla çalıştı: yalnızca "istenen dosya" denetimi
        self.assertIsNone(a._completion_check([]))
        a.user_text = "rapor.xlsx dosyası oluştur"
        a.focus = "rapor.xlsx dosyasını yaz"
        self.assertIn("rapor.xlsx", a._completion_check([]) or "")  # kullanıcının istediği dosya hâlâ denetlenir


@unittest.skipUnless(subprocess.run([python_exe(), "-c", "import trimesh"], env=agent_env()).returncode == 0,
                     "trimesh yok")
class YumusakOnizleme(unittest.TestCase):
    def test_glb_normallerle_ve_onbellekten(self):
        from asistan import inspect_output

        stl = Path(tempfile.mkdtemp(dir=_GECICI)) / "kure.stl"
        kod = f"import trimesh; trimesh.creation.icosphere(3, 20).export({str(stl)!r})"
        subprocess.run([python_exe(), "-c", kod], env=agent_env(), check=True)
        glb = inspect_output.smooth_preview(stl)
        self.assertTrue(glb and glb.suffix == ".glb" and glb.stat().st_size > 1000)
        import json
        import struct

        veri = glb.read_bytes()
        yapi = json.loads(veri[20:20 + struct.unpack("<I", veri[12:16])[0]])
        self.assertIn("NORMAL", yapi["meshes"][0]["primitives"][0]["attributes"])  # yumuşak gölge: köşe normalleri
        self.assertEqual(inspect_output.smooth_preview(stl), glb)  # değişmedi: önbellek


if __name__ == "__main__":
    unittest.main()
