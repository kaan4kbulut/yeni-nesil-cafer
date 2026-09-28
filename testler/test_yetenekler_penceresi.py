"""K5 — Yetenekler penceresi (`gui/yetenekler_dialog.py`, ekransız): aktif/pasif, izinler, kaynak, güvenilir ve
pasifin nedeni görünüyor; Yardım menüsünde "Yetenekler…" var. Pencere hiçbir şey çalıştırmaz.

Çalıştırma (proje kökünde, programın Python'uyla):
    ~/.local/share/yeni-nesil-cafer-app/python/bin/python3 -m unittest discover -s testler -v
"""

import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

KOK = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(KOK))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
_GECICI = tempfile.mkdtemp(prefix="yeni-nesil-cafer-test-")
os.environ["XDG_CONFIG_HOME"] = str(Path(_GECICI) / "ayar")
os.environ["XDG_DATA_HOME"] = str(Path(_GECICI) / "veri")

from PySide6.QtWidgets import QApplication  # noqa: E402

APP = QApplication.instance() or QApplication([])

from asistan.cekirdek.yetenek.kayit import YERLESIK_KOK, Kayit  # noqa: E402
from asistan.gui import yetenekler_dialog as yd  # noqa: E402


class PencereTesti(unittest.TestCase):
    def setUp(self):
        kok = Path(tempfile.mkdtemp(dir=_GECICI))
        klasor = kok / "kurulmamis"
        klasor.mkdir()
        (klasor / "manifest.json").write_text(json.dumps({
            "ad": "kurulmamis", "surum": "1.0.0", "aciklama": "paketi olmayan yetenek", "girdi": {},
            "cikti": {}, "gereksinimler": {"pip": ["yok-boyle-paket-k5"]}, "izinler": ["ag"],
            "zaman_asimi_sn": 5, "sandbox": True, "kaynak": "uretildi", "guvenilir": False}), encoding="utf-8")
        (klasor / "calistir.py").write_text("def calistir(g, b):\n    return {}\n", encoding="utf-8")
        self.dlg = yd.YeteneklerDialog(kayit=Kayit([YERLESIK_KOK, kok], kademe="yuksek"))
        self.addCleanup(self.dlg.deleteLater)

    def satir(self, ad: str) -> int:
        return next(r for r in range(self.dlg.table.rowCount()) if self.dlg.table.item(r, 0).text() == ad)

    def hucre(self, ad: str, sutun: int) -> str:
        return self.dlg.table.item(self.satir(ad), sutun).text()

    def test_aktif_ve_pasif_gorunur(self):
        self.assertIn("aktif", self.hucre("dosya_oku", 1))
        self.assertIn("pasif", self.hucre("kurulmamis", 1))
        self.assertIn("yok-boyle-paket-k5", self.dlg.table.item(self.satir("kurulmamis"), 1).toolTip())
        self.assertIn("pasif", self.dlg.status.text())

    def test_izin_kaynak_guven(self):
        self.assertEqual(self.hucre("komut_calistir", 2).split(", ")[0], "komut / kod çalıştırır")
        self.assertEqual(self.hucre("metin_istatistik", 3), "yerleşik")
        self.assertEqual(self.hucre("metin_istatistik", 5), "sandbox")
        self.assertEqual(self.hucre("kurulmamis", 3), "üretildi")
        self.assertEqual(self.hucre("kurulmamis", 4), "hayır")

    def test_ayrinti_nedeni_gosterir(self):
        self.dlg.table.selectRow(self.satir("kurulmamis"))
        metin = self.dlg.detail.toPlainText()
        self.assertIn("Pasif", metin)
        self.assertIn("yok-boyle-paket-k5", metin)

    def test_menude_var(self):
        from asistan.gui import window_help

        self.assertTrue(hasattr(window_help.HelpMixin, "open_capabilities"))
        self.assertIn('"Yetenekler…"', (KOK / "asistan/gui/window.py").read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
