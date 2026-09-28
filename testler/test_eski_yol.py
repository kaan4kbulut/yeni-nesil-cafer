"""Eski modül yolları için geçici uyumluluk (`asistan.eski`, K1; 2.8'de kaldırılacak).

Çalıştırma (proje kökünde, programın Python'uyla):
    ~/.local/share/yeni-nesil-cafer-app/python/bin/python3 -m unittest discover -s testler -v
"""

import importlib
import os
import sys
import tempfile
import unittest
import warnings
from pathlib import Path

KOK = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(KOK))

_GECICI = tempfile.mkdtemp(prefix="yeni-nesil-cafer-test-")
os.environ["XDG_CONFIG_HOME"] = str(Path(_GECICI) / "ayar")
os.environ["XDG_DATA_HOME"] = str(Path(_GECICI) / "veri")
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from asistan import dictation, eski  # noqa: E402
from asistan.gui import dikte_kaydi  # noqa: E402


class EskiYolTesti(unittest.TestCase):
    def test_eski_yol_uyarir_ve_ayni_nesneyi_verir(self):
        with warnings.catch_warnings(record=True) as uyarilar:
            warnings.simplefilter("always")
            sinif = dictation.Dictation
        self.assertIs(sinif, dikte_kaydi.Dictation)
        self.assertEqual(len(uyarilar), 1)
        self.assertIs(uyarilar[0].category, DeprecationWarning)
        self.assertIn("asistan.gui.dikte_kaydi.Dictation", str(uyarilar[0].message))
        self.assertEqual(Path(uyarilar[0].filename).name, Path(__file__).name)  # uyarı çağıranı gösterir

    def test_from_asistan_eski_import(self):
        with warnings.catch_warnings(record=True) as uyarilar:
            warnings.simplefilter("always")
            from asistan.eski import Dictation
        self.assertIs(Dictation, dikte_kaydi.Dictation)
        self.assertTrue(any(u.category is DeprecationWarning for u in uyarilar))

    def test_bilinmeyen_ad_hata(self):
        with self.assertRaises(AttributeError):
            dictation.YokBoyleBirSey  # noqa: B018
        with self.assertRaises(ImportError):
            from asistan.eski import YokBoyleBirSey  # noqa: F401

    def test_tablo_gecerli(self):
        for (eski_modul, ad), yeni in eski.TASINANLAR.items():
            with self.subTest(eski_modul=eski_modul, ad=ad):
                self.assertTrue(hasattr(importlib.import_module(yeni), ad))
                self.assertNotIn(ad, vars(importlib.import_module(eski_modul)))  # gerçekten taşındı

    def test_dikte_cekirdek_tarafi_qt_bilmez(self):
        self.assertNotIn("PySide6", (KOK / "asistan" / "dictation.py").read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
