"""Sağ panel (üç bölüm, üstte yalnızca adımlar ve kayıt) ve iş sürerken Enter (durdurmaz, sıraya alır).

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


class SagPanelTesti(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.w = MainWindow()

    def test_ust_sekmeler_yalnizca_adimlar_ve_kayit(self):
        tabs = self.w.right.tabs
        self.assertEqual([tabs.tabText(i) for i in range(tabs.count())], ["adımlar", "kayıt"])
        split = self.w.right.split  # dosyalar ve canlı görüntü sekmede değil, hep görünür bölümler
        self.assertEqual([split.widget(i) for i in range(3)], [tabs, self.w.right.files, self.w.right.media])

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
