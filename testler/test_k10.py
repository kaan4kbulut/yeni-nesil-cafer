"""K10 — kurulum sihirbazı (kademe → yerel/bulut/ikisi → gizlilik), düşük kademede sade arayüz, Gelişmiş menüsü,
açılış süresi (anthropic tembel), sürüm 3.0 + CHANGELOG + tanıtım, pyproject `cafer` komutu."""

import os
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

KOK = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(KOK))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
_GECICI = tempfile.mkdtemp(prefix="yeni-nesil-cafer-test-")
os.environ["XDG_CONFIG_HOME"] = str(Path(_GECICI) / "ayar")
os.environ["XDG_DATA_HOME"] = str(Path(_GECICI) / "veri")

from PySide6.QtWidgets import QApplication, QButtonGroup, QPushButton, QWidget  # noqa: E402

APP = QApplication.instance() or QApplication([])

import asistan  # noqa: E402
from asistan.cekirdek import profil  # noqa: E402
from asistan.config import Settings  # noqa: E402
from asistan.gui import setup_wizard, tour, window_modes  # noqa: E402


class Sihirbaz(unittest.TestCase):
    def _sihirbaz(self, kademe):
        s = Settings(workspace=str(Path(_GECICI) / "is"))
        with mock.patch.object(profil, "kademe", return_value=kademe), mock.patch.object(profil, "yukle", return_value={"kademe": {"neden": "test"}}):
            w = setup_wizard.SetupWizard(s)
            w._scan = lambda: None  # sistem taraması yok
            w.info = SimpleNamespace(ollama_models=[], ollama_running=False)
            w._go(2)
        return w, s

    def test_sayfalar_ve_kademe_varsayilani(self):
        w, _ = self._sihirbaz("dusuk")
        self.assertEqual(w.pages.count(), 5)
        self.assertIn("düşük", w.kademe_text.text())
        self.assertTrue(w.src_bulut.isChecked())  # düşük kademe: bulut önerilir
        self.assertEqual(w.gizlilik.currentData(), "bulut")
        w2, _ = self._sihirbaz("yuksek")
        self.assertTrue(w2.src_yerel.isChecked())
        w3, _ = self._sihirbaz("orta")
        self.assertTrue(w3.src_ikisi.isChecked())

    def test_bulut_secilince_model_sayfasi_atlanir_anahtar_zincire(self):
        w, s = self._sihirbaz("dusuk")
        w.api_key.setText("sk-ant-test")
        kaydedilen = []
        with mock.patch("asistan.keystore.set_secret", side_effect=lambda ad, v: kaydedilen.append((ad, v))), \
                mock.patch.object(profil, "kademe", return_value="dusuk"):
            w._next()
        self.assertEqual(w.pages.currentIndex(), 4)  # yerel model sayfası atlandı
        self.assertEqual(kaydedilen[0][1], "sk-ant-test")
        self.assertEqual(s.extra["gizlilik"], "bulut")
        self.assertEqual(s.extra["model_kaynagi"], "bulut")
        self.assertEqual(s.model_policy, "guclu")
        self.assertEqual(w.next_btn.text(), "Başla")

    def test_ikisi_secilince_model_sayfasi(self):
        w, s = self._sihirbaz("orta")
        w.gizlilik.setCurrentIndex(w.gizlilik.findData("yerel"))
        with mock.patch.object(w, "_fill_models"), mock.patch.object(profil, "kademe", return_value="orta"):
            w._next()
        self.assertEqual(w.pages.currentIndex(), 3)
        self.assertEqual(s.extra["gizlilik"], "yerel")


class SadeArayuz(unittest.TestCase):
    def _sahte(self, extra):
        f = SimpleNamespace(settings=Settings(workspace=_GECICI), model_tabs=QWidget(), toggle_right=QPushButton(),
                            side_tabs=QButtonGroup())
        f.settings.extra = dict(extra)
        for i in range(5):
            b = QPushButton(str(i))
            b.show()  # gösterilmemiş pencere Qt'de "gizli" sayılır: önce açık, sonra sade kip gizlesin
            f.side_tabs.addButton(b, i)
        f.model_tabs.show()
        f.toggle_right.show()
        f.toggle_right.setCheckable(True)
        f.toggle_right.setChecked(True)
        return f

    def test_dusuk_kademede_sade(self):
        f = self._sahte({})
        with mock.patch.object(profil, "kademe", return_value="dusuk"):
            self.assertTrue(window_modes.ModesMixin._sade_arayuz(f))
        self.assertTrue(f.side_tabs.button(1).isHidden())
        self.assertFalse(f.side_tabs.button(0).isHidden())  # sohbet kalır
        self.assertTrue(f.toggle_right.isHidden())
        self.assertFalse(f.toggle_right.isChecked())
        self.assertTrue(f.model_tabs.isHidden())

    def test_gelismis_arayuz_acar_orta_kademe_tam(self):
        f = self._sahte({"gelismis_arayuz": True, "model_cubugu": True})
        with mock.patch.object(profil, "kademe", return_value="dusuk"):
            self.assertFalse(window_modes.ModesMixin._sade_arayuz(f))
        self.assertFalse(f.side_tabs.button(3).isHidden())
        self.assertFalse(f.model_tabs.isHidden())
        f = self._sahte({})
        with mock.patch.object(profil, "kademe", return_value="orta"):
            self.assertFalse(window_modes.ModesMixin._sade_arayuz(f))
        self.assertTrue(f.model_tabs.isHidden())  # model çubuğu varsayılan gizli (Gelişmiş menüsü)

    def test_gelismis_menu_kaynakta(self):
        kaynak = (KOK / "asistan" / "gui" / "window.py").read_text(encoding="utf-8")
        self.assertIn('h.addMenu("Gelişmiş")', kaynak)
        for ad in ("Model önerileri…", "Ajan kategorileri…", "Model kartları…", "Modeller…", "Araç fabrikası…"):
            self.assertIn(f'QAction("{ad}"', kaynak, ad)
            self.assertLess(kaynak.index('h.addMenu("Gelişmiş")'), kaynak.index(f'QAction("{ad}"'), ad)


class SurumVeBaslangic(unittest.TestCase):
    def test_surum_changelog_tanitim_pyproject(self):
        self.assertEqual(asistan.__version__, "3.0")
        self.assertIn("## 3.0", (KOK / "CHANGELOG.md").read_text(encoding="utf-8"))
        self.assertIn("3.0", tour.NEWS)
        self.assertTrue(tour.pending(SimpleNamespace(extra={"tanitim_surumu": "2.7"})))
        py = (KOK / "pyproject.toml").read_text(encoding="utf-8")
        self.assertIn('cafer = "asistan.arayuz.komut:ana"', py)
        self.assertIn('version = "3.0"', py)
        from asistan import updates

        self.assertGreater(updates.version_tuple("3.0"), updates.version_tuple("2.7"))

    def test_acilis_ice_aktarma_hizli_ve_anthropic_tembel(self):
        python = str(KOK / ".venv" / "bin" / "python") if (KOK / ".venv" / "bin" / "python").is_file() else sys.executable
        kod = ("import sys, time\nt = time.time()\nimport asistan.gui.window\n"
               "print(round(time.time() - t, 2), 'anthropic' in sys.modules)\n")
        s = subprocess.run([python, "-c", kod], cwd=KOK, capture_output=True, text=True, timeout=120,
                           env=dict(os.environ, QT_QPA_PLATFORM="offscreen"))
        self.assertEqual(s.returncode, 0, s.stderr[-1500:])
        sure, yuklu = s.stdout.split()
        self.assertEqual(yuklu, "False")  # SDK ilk Claude çağrısında yüklenir
        self.assertLess(float(sure), 3.0, sure)


if __name__ == "__main__":
    unittest.main()
