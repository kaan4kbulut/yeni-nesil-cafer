"""Sağ panel (sekmeler adımlar · kayıt · klasörler; canlı önizleme yalnızca görsel işte) ve iş sürerken Enter (durdurmaz, sıraya alır).

Çalıştırma (proje kökünde, programın Python'uyla):
    ~/.local/share/yeni-nesil-cafer-app/python/bin/python3 -m unittest discover -s testler -v
"""

import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

KOK = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(KOK))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
_GECICI = tempfile.mkdtemp(prefix="yeni-nesil-cafer-test-")
os.environ["XDG_CONFIG_HOME"] = str(Path(_GECICI) / "ayar")
os.environ["XDG_DATA_HOME"] = str(Path(_GECICI) / "veri")

from PySide6.QtWidgets import QApplication  # noqa: E402

APP = QApplication.instance() or QApplication([])

from asistan.config import Settings  # noqa: E402
from asistan.gui import tour  # noqa: E402
from asistan.gui.window import MainWindow  # noqa: E402
from asistan.gui.window_run import visual_note  # noqa: E402


class SagPanelTesti(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.w = MainWindow()

    def test_sekmeler_adimlar_kayit_klasorler(self):
        tabs = self.w.right.tabs
        self.assertEqual([tabs.tabText(i) for i in range(tabs.count())], ["adımlar", "kayıt", "klasörler"])

    def test_canli_onizleme_yalnizca_gorsel_iste(self):
        r = self.w.right
        self.w.show()
        try:
            self.assertFalse(r.media.isVisible())  # görsel iş yokken yer kaplamaz
            self.assertEqual(visual_note("run_python", {"code": "print(2 + 2)"}), "")
            self.assertEqual(visual_note("read_file", {"path": "a.stl"}), "")
            not3d = visual_note("run_python", {"code": "from build123d import *\nexport_stl(b, 'kup.stl')"})
            self.assertIn("3D", not3d)
            self.assertTrue(visual_note("generate_image", {"prompt": "kedi"}))
            r.show_media(not3d)
            self.assertTrue(r.media.isVisible())
            self.assertIn("3D", r.media.empty.text())
            r.hide_media()  # yeni iş başlayınca
            self.assertFalse(r.media.isVisible())
            self.w._new_media()  # iş yokken klasöre görsel gelse de açılmaz
            self.assertFalse(r.media.isVisible())
        finally:
            self.w.hide()

    def test_adimlar_en_alta_kayar(self):
        a = self.w.right.activity
        self.w.resize(1400, 700)
        self.w.show()
        self.w.toggle_right.setChecked(True)
        self.w.right.tabs.setCurrentWidget(a)
        try:
            a.begin_run("model")
            for i in range(40):
                a.tool_start(str(i), "run_python", f"adım {i}")
            for _ in range(5):
                APP.processEvents()
            bar = a.scroll.verticalScrollBar()
            self.assertGreater(bar.maximum(), 0)
            self.assertEqual(bar.value(), bar.maximum())
            bar.setValue(0)  # kullanıcı yukarı kaydırdı: takip durur
            a.tool_start("x", "run_python", "yeni adım")
            APP.processEvents()
            self.assertEqual(bar.value(), 0)
        finally:
            self.w.hide()

    def test_modeller_kendi_penceresinde(self):
        self.w.right.show_part(self.w.right.models)
        self.assertTrue(self.w.right.windows[self.w.right.models].isVisible())
        self.w.right.windows[self.w.right.models].hide()

    def test_is_surerken_enter_durdurmaz_siraya_alir(self):
        worker = mock.Mock()
        self.w.worker = worker
        try:
            self.w.input.setPlainText("sonra şunu da yap")
            self.w._submit()
            worker.cancel.assert_not_called()
            self.assertTrue(self.w.queued_send)
            self.w._submit()  # ikinci Enter da durdurmaz
            worker.cancel.assert_not_called()
            self.w._escape()  # Esc durdurur
            worker.cancel.assert_called_once()
        finally:
            self.w.worker = None
            self.w.queued_send = False

    def test_atlanan_surumlerin_yenilikleri_de_gosterilir(self):
        s = Settings()
        s.extra = {"tanitim_surumu": "2.1"}
        with mock.patch.object(tour, "__version__", "2.3"):
            self.assertEqual(len(tour.pending(s)), len(tour.NEWS["2.3"]) + len(tour.NEWS["2.2"]))
            s.extra = {"tanitim_surumu": "2.3"}
            self.assertEqual(tour.pending(s), [])


if __name__ == "__main__":
    unittest.main()
