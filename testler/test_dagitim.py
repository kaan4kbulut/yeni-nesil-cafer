"""K11 — `dagitim/paketle.py` (kuru plan, model bütçesi, dosya listesi), CI iş akışı, güncelleme paketi uyumu,
sihirbazın yetenek özeti."""

import json
import os
import subprocess
import sys
import tempfile
import unittest
from types import SimpleNamespace
from pathlib import Path
from unittest import mock

KOK = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(KOK))
_GECICI = tempfile.mkdtemp(prefix="yeni-nesil-cafer-test-")
os.environ["XDG_CONFIG_HOME"] = str(Path(_GECICI) / "ayar")
os.environ["XDG_DATA_HOME"] = str(Path(_GECICI) / "veri")

import importlib.util  # noqa: E402

_spec = importlib.util.spec_from_file_location("dagitim_paketle", KOK / "dagitim" / "paketle.py")  # paketleme/paketle ile ad çakışmasın
paketle = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(paketle)
from asistan import updates  # noqa: E402
from asistan.cekirdek import modeller  # noqa: E402


class Paketleme(unittest.TestCase):
    def test_kuru_plan(self):
        p = paketle.plan("hafif", 1.9)
        self.assertEqual(p["tur"], "hafif")
        self.assertNotIn("Light", p["urun"])  # platform başına tek dosya, ad ne yapacağını söyler
        self.assertTrue(p["urun"].startswith("YeniNesilCafer-") and p["urun"].endswith((".AppImage", "-Kurulum.exe", ".dmg")))
        self.assertGreater(p["dosya_sayisi"], 100)
        self.assertLess(p["kaynak_mb"], 200)  # Light ~200 MB hedefi: kaynak kod çok altında (bağımlılıklar PyInstaller'da)
        dosyalar = {rel for _, rel in paketle.program_dosyalari()}
        self.assertIn("main.py", dosyalar)
        self.assertIn("asistan/gui/window.py", dosyalar)  # masaüstü Light'a girer
        self.assertIn("asistan/ayar/modeller.json", dosyalar)
        self.assertFalse({d for d in dosyalar if d.startswith(("testler/", "NOTLAR/", "sunucu/", ".venv/"))})
        t = paketle.plan("tam", 1.9)
        self.assertIn("Full", t["urun"])
        self.assertIn("ollama", t)

    def test_model_butcesi(self):
        boyut = modeller.deger("kategoriler.boyutlar")
        self.assertIsNone(paketle.model_sec(1.9))  # bugünkü listede 1,9 GB'a sığan model yok (dürüstçe None)
        self.assertEqual(paketle.model_sec(2.7 + 0.55 + 0.01), "qwen3.5:2b")
        self.assertEqual(paketle.model_sec(10), "qwen3.5:4b")  # sığanların en büyüğü
        self.assertIn("qwen3.5:2b", boyut)
        self.assertIn("qwen3.5:4b", modeller.deger("dagitim.tam_modeller"))

    def test_komut_satiri_kuru(self):
        s = subprocess.run([sys.executable, str(KOK / "dagitim" / "paketle.py"), "--kuru", "--tam"], capture_output=True,
                           text=True, timeout=60, cwd=KOK, env=dict(os.environ))
        self.assertEqual(s.returncode, 0, s.stderr[-800:])
        p = json.loads(s.stdout)
        self.assertEqual(p["tur"], "tam")
        self.assertIn("not", p)  # bütçeye sığan model yok notu

    def test_guncelleme_paketi_uyumlu(self):
        cikti = Path(_GECICI) / "g"
        with mock.patch.object(paketle, "CIKTI", cikti):
            p = paketle.guncelleme_paketi()
        self.assertEqual(p.name, updates.ASSET.format(version=paketle.surum()))
        self.assertTrue((cikti / (p.name + ".sha256")).is_file())
        import zipfile

        with zipfile.ZipFile(p) as z:
            uyeler = updates._members(z)  # güncelleyicinin kabul ettiği biçim
        self.assertTrue(any(m.filename == "asistan/__init__.py" for m in uyeler))

    def test_ci_is_akisi(self):
        y = (KOK / ".github" / "workflows" / "dagitim.yml").read_text(encoding="utf-8")
        for parca in ("ubuntu-latest", "windows-latest", "macos-latest", "dagitim/paketle.py --hafif",
                      "paketle.py --guncelleme", "action-gh-release", 'tags: ["v*"]', "pyinstaller"):
            self.assertIn(parca, y, parca)


class SihirbazYetenekOzeti(unittest.TestCase):
    def test_ozet_metni(self):
        os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
        from PySide6.QtWidgets import QApplication

        QApplication.instance() or QApplication([])
        from asistan.config import Settings
        from asistan.gui.setup_wizard import SetupWizard

        w = SetupWizard(Settings(workspace=_GECICI))
        metin = w._yetenek_ozeti()
        self.assertIn("Yetenekler:", metin)
        self.assertRegex(metin, r"\d+ hazır")


if __name__ == "__main__":
    unittest.main()


class EskiSurumleriSil(unittest.TestCase):
    """`--eski-sil`: Latest (ya da --kalan) dışındaki yayınlanmış sürümler --cleanup-tag ile silinir; taslak kalır."""

    def _gh(self, liste, komutlar):
        def calistir(cmd, **k):
            komutlar.append(cmd)
            if cmd[:3] == ["gh", "release", "list"]:
                return SimpleNamespace(returncode=0, stdout=json.dumps(liste), stderr="")
            return SimpleNamespace(returncode=0, stdout="", stderr="")
        return calistir

    def test_latest_disindakiler_silinir(self):
        liste = [{"tagName": "v3.0-beta.1", "isLatest": True, "isDraft": False},
                 {"tagName": "v2.7", "isLatest": False, "isDraft": False},
                 {"tagName": "v3.1", "isLatest": False, "isDraft": True}]
        komutlar = []
        self.assertEqual(paketle.eski_surumleri_sil(calistir=self._gh(liste, komutlar)), ["v2.7"])
        self.assertIn(["gh", "release", "delete", "v2.7", "--cleanup-tag", "--yes"], komutlar)
        self.assertFalse(any("v3.1" in c or "v3.0-beta.1" in c for c in komutlar if c[2] == "delete"))

    def test_latest_yoksa_durur(self):
        liste = [{"tagName": "v2.7", "isLatest": False, "isDraft": False}]
        with self.assertRaises(RuntimeError):
            paketle.eski_surumleri_sil(calistir=self._gh(liste, []))
        with self.assertRaises(RuntimeError):  # --kalan listede yok: hiçbir şey silinmez
            paketle.eski_surumleri_sil("v9", calistir=self._gh(liste, []))
        komutlar = []
        self.assertEqual(paketle.eski_surumleri_sil("v2.7", calistir=self._gh(liste, komutlar)), [])


class SurumSayfasi(unittest.TestCase):
    """Sürüm sayfası kullanıcı için: ad platformu ve işi söyler, not başında "Hangisini indireyim?" tablosu,
    güncelleyici paketi "guncelleyici-icin-" önekli, AppImage --install ile masaüstüne kısayol."""

    def test_urun_adlari(self):
        self.assertEqual(paketle.urun_adi("linux", v="3.1"), "YeniNesilCafer-3.1-Linux.AppImage")
        self.assertEqual(paketle.urun_adi("windows", v="3.1"), "YeniNesilCafer-3.1-Windows-Kurulum.exe")
        self.assertEqual(paketle.urun_adi("macos", v="3.1"), "YeniNesilCafer-3.1-macOS.dmg")
        self.assertEqual(paketle.urun_adi("linux", "tam", v="3.1"), "YeniNesilCafer-3.1-Full-Linux.AppImage")
        from asistan import updates

        self.assertTrue(updates.ASSET.startswith("guncelleyici-icin-"))

    def test_surum_notu(self):
        from asistan import updates

        n = paketle.surum_notu("3.1")
        self.assertTrue(n.startswith("# YENİ NESİL CAFER 3.1\n\n## Hangisini indireyim?"))
        for ad in ("YeniNesilCafer-3.1-Linux.AppImage", "YeniNesilCafer-3.1-Windows-Kurulum.exe", "YeniNesilCafer-3.1-macOS.dmg",
                   "--install", "Bunları indirmeyin", updates.ASSET.format(version="3.1"), "## Bu sürümde"):
            self.assertIn(ad, n)
        self.assertNotIn("{", n.replace("{", "", 0))  # şablonda doldurulmamış alan kalmadı
        self.assertNotIn("{surum}", n)

    def test_apprun_install(self):
        m = paketle.apprun_metni("usr/bin/X/X")
        self.assertIn("--install) exec \"$HERE/kur.sh\"", m)
        self.assertIn("--uninstall)", m)
        self.assertTrue(m.rstrip().endswith('exec "$HERE/usr/bin/X/X" "$@"'))

    @unittest.skipIf(sys.platform == "win32", "posix betiği")
    def test_kur_sh_masaustu_kisayolu(self):
        ev = Path(tempfile.mkdtemp())
        (ev / "Masaüstü").mkdir()
        app = ev / "YeniNesilCafer-3.1-Linux.AppImage"
        app.write_text("#!/bin/sh\n", encoding="utf-8")
        ikon = ev / "ikon.png"
        ikon.write_bytes(b"png")
        ortam = {**os.environ, "HOME": str(ev), "XDG_DATA_HOME": str(ev / "veri"), "PATH": "/usr/bin:/bin"}
        betik = KOK / "dagitim" / "linux" / "kur.sh"
        sahte = ev / "bin"
        sahte.mkdir()
        (sahte / "xdg-user-dir").write_text(f"#!/bin/sh\necho {ev}/Masaüstü\n", encoding="utf-8")
        os.chmod(sahte / "xdg-user-dir", 0o755)
        ortam["PATH"] = f"{sahte}:" + ortam["PATH"]
        s = subprocess.run(["sh", str(betik), str(app), str(ikon)], capture_output=True, text=True, env=ortam)
        self.assertEqual(s.returncode, 0, s.stderr)
        d = ev / "veri" / "applications" / "yeni-nesil-cafer.desktop"
        self.assertTrue(d.is_file())
        self.assertIn(f'Exec="{app}" %F', d.read_text(encoding="utf-8"))
        self.assertTrue((ev / "Masaüstü" / "yeni-nesil-cafer.desktop").is_file())
        self.assertTrue((ev / "veri" / "icons" / "hicolor" / "256x256" / "apps" / "yeni-nesil-cafer.png").is_file())
        self.assertTrue(os.access(app, os.X_OK))
        s = subprocess.run(["sh", str(betik), str(app), str(ikon), "--uninstall"], capture_output=True, text=True, env=ortam)
        self.assertEqual(s.returncode, 0, s.stderr)
        self.assertFalse(d.exists())
        self.assertTrue(app.exists())  # AppImage silinmez
