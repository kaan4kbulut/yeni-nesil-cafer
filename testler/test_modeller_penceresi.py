"""K7 — Modeller penceresi (ekransız): kademe listeleri ve ölçümler görünür, "Varsayılan yap" kullanıcı katmanına
yazar, önerilen liste hesaplanır; Yardım menüsünde "Modeller…" var."""

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

from asistan.cekirdek import modeller, profil  # noqa: E402
from asistan.cekirdek.analiz import olcum  # noqa: E402
from asistan.config import Settings  # noqa: E402
from asistan.gui import modeller_dialog as md  # noqa: E402


class Pencere(unittest.TestCase):
    def setUp(self):
        modeller.ust_dosya().unlink(missing_ok=True)
        modeller.yenile()
        self.addCleanup(lambda: (modeller.ust_dosya().unlink(missing_ok=True), modeller.yenile()))
        orta = modeller.kademe_modelleri("orta")["yerel"][0]
        kayit = {"kademe": {"olculen": "orta", "etkin": "orta"}, "benchmark": {orta: {"tok_sn": 33.3, "ilk_token_ms": 210}},
                 "ollama": {"modeller": [orta]}}
        for p in (mock.patch.object(profil, "yukle", return_value=kayit), mock.patch.object(profil, "kademe", return_value="orta")):
            p.start()
            self.addCleanup(p.stop)
        olcum.basari_kaydet("ollama", orta, True, 1)
        self.orta = orta
        self.dlg = md.ModellerDialog(Settings())

    def _satir(self, model):
        for r in range(self.dlg.table.rowCount()):
            if self.dlg.table.item(r, 3).text() == model and self.dlg.table.item(r, 1).text() == "yerel":
                return r
        raise AssertionError(model)

    def test_liste_ve_olcumler(self):
        r = self._satir(self.orta)
        self.assertEqual(self.dlg.table.item(r, 2).text(), "varsayılan")
        self.assertEqual(self.dlg.table.item(r, 4).text(), "33")
        self.assertEqual(self.dlg.table.item(r, 6).text(), "%100 (1)")
        self.assertEqual(self.dlg.table.item(r, 7).text(), "✓")
        self.assertIn("◀", self.dlg.table.item(r, 0).text())  # etkin kademe işaretli
        self.assertGreater(self.dlg.table.rowCount(), 8)

    def test_varsayilan_yap(self):
        ikinci = modeller.kademe_modelleri("orta")["yerel"][1]
        self.dlg.table.selectRow(self._satir(ikinci))
        self.dlg._varsayilan_yap()
        self.assertEqual(modeller.kademe_modelleri("orta")["yerel"][0], ikinci)
        self.assertEqual(self.dlg.table.item(self._satir(ikinci), 2).text(), "varsayılan")
        self.assertIn(ikinci, self.dlg.status.text())

    def test_onerilen_liste(self):
        live = {"library": {"a:8b": ["x", 1, 9.0], "b:4b": ["x", 1, 5.0], "c:1b": ["x", 1, 8.0]},
                "arena": {"text": [{"model": "bulut-1"}, {"model": "bulut-2"}]}}
        with mock.patch("asistan.model_updates.arena_ranked", return_value=[{"model": "bulut-1"}, {"model": "bulut-2"}]):
            on = md.onerilen_liste(live, ["b:4b"])
        self.assertEqual(on["yerel"][0], "b:4b")  # kurulu önce
        self.assertEqual(on["yerel"][1:], ["a:8b", "c:1b"])
        self.assertEqual(on["bulut"], ["bulut-1", "bulut-2"])

    def test_yardim_menusunde(self):
        from asistan.gui import window_help

        self.assertTrue(hasattr(window_help.HelpMixin, "open_models"))
        kaynak = (KOK / "asistan" / "gui" / "window.py").read_text(encoding="utf-8")
        self.assertIn('QAction("Modeller…"', kaynak)


if __name__ == "__main__":
    unittest.main()
