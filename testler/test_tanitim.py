"""Tanıtım (gui/tour.py): ilk kurulumda ve her yeni sürümde bir kez; düğmeler özelliği açar.

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

from PySide6.QtWidgets import QApplication, QPushButton  # noqa: E402

APP = QApplication.instance() or QApplication([])

from asistan.config import Settings  # noqa: E402
from asistan.gui import tour  # noqa: E402


class TanitimTesti(unittest.TestCase):
    def test_bir_kez_gosterilir_yeni_surumde_yine(self):
        s = Settings()
        self.assertTrue(tour.pending(s))  # bu sürümün yenilikleri tanımlı
        tour.mark_seen(s)
        self.assertEqual(tour.pending(s), [])
        with mock.patch.object(tour, "__version__", "9.9"), mock.patch.dict(tour.NEWS, {"9.9": [("x", "y", "", "")]}):
            self.assertEqual(len(tour.pending(s)), 1)  # yeni sürüm: yeniden

    def test_dugme_ozelligi_acar(self):
        acilan = []
        # hata düzeltme sürümünün (ör. 2.3.1) kendi tanıtımı yok: bu sürüme kadarki en yeni tanıtım
        son = max((v for v in tour.NEWS if tour._key(v) <= tour._key(tour.__version__)), key=tour._key)
        madde = next(m for m in tour.NEWS[son] if m[2])  # düğmesi olan ilk madde
        dlg = tour.TourDialog(tour.NEWS[son], acilan.append)
        next(b for b in dlg.findChildren(QPushButton) if b.text() == madde[2]).click()
        self.assertEqual(acilan, [madde[3]])


if __name__ == "__main__":
    unittest.main()
