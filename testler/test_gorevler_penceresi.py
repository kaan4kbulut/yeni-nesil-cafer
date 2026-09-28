"""K4 — Görevler penceresi (`gui/gorevler_dialog.py`, ekransız): liste, adım durumları, düğmelerin durumu ve Onayla /
Devam düğmelerinin motoru doğru görevle çağırması. Motor sahte; model çağrılmaz.

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

from asistan.cekirdek.gorev import durum  # noqa: E402
from asistan.config import Settings  # noqa: E402
from asistan.gui import gorevler_dialog as gd  # noqa: E402


def gorev(durum_: str, adim_durumlari: list[str]) -> dict:
    return {"gorev_id": durum.yeni_id(), "istek": "txt say ve özetle", "olusturma": durum.simdi(), "kademe": "orta",
            "anlayis": {"niyet": "say"}, "durum": durum_, "checkpoint": {"son_adim": 1, "zaman": None},
            "hatalar": [], "rapor": None,
            "adimlar": [{"id": i + 1, "amac": f"adım {i + 1}", "yetenek": "read_file", "girdi": {"path": "a.txt"},
                         "basari_olcutu": "", "bagimli": [], "deneme_hakki": 0, "onay_gerekli": d == "bekliyor_onay",
                         "secim": {"saglayici": None, "model": None, "neden": "model gerekmiyor"}, "durum": d}
                        for i, d in enumerate(adim_durumlari)]}


class PencereTesti(unittest.TestCase):
    def setUp(self):
        durum._DEPO = durum.Depo(Path(tempfile.mkdtemp(dir=_GECICI)) / "gorevler.db")
        self.addCleanup(setattr, durum, "_DEPO", None)
        mock.patch.object(durum, "depo", return_value=durum._DEPO).start()
        self.addCleanup(mock.patch.stopall)

    def pencere(self):
        d = gd.GorevlerDialog(Settings.load())
        self.addCleanup(d.close)
        return d

    def test_bos_depo(self):
        d = self.pencere()
        self.assertEqual(d.list.count(), 0)
        self.assertFalse(d.approve_btn.isEnabled())
        d.start_btn.click()  # boş kutu: hiçbir şey başlamaz
        self.assertFalse(d.busy)

    def test_onay_bekleyen_gorev_ve_onayla(self):
        g = gorev("bekliyor_onay", ["tamamlandi", "bekliyor_onay"])
        durum._DEPO.kaydet(g)
        d = self.pencere()
        self.assertEqual(d.list.count(), 1)
        self.assertTrue(d.approve_btn.isEnabled())
        self.assertFalse(d.continue_btn.isEnabled())
        self.assertIn("onay bekliyor", d.detail.toPlainText())
        self.assertIn("Yapılacak", d.detail.toPlainText())
        motor = mock.Mock()
        with mock.patch.object(d, "_motor", return_value=motor) as kur:
            d.approve_btn.click()
            d._thread.join(2)
        kur.assert_called_once_with(gorev_id=g["gorev_id"])
        motor.onayla.assert_called_once_with(g["gorev_id"], True)

    def test_yarim_gorev_devam(self):
        g = gorev("calisiyor", ["tamamlandi", "calisiyor", "planlandi"])
        durum._DEPO.kaydet(g)
        d = self.pencere()
        self.assertTrue(d.continue_btn.isEnabled())
        d.only_open.setChecked(True)
        self.assertEqual(d.list.count(), 1)
        motor = mock.Mock()
        with mock.patch.object(d, "_motor", return_value=motor):
            d.continue_btn.click()
            d._thread.join(2)
        motor.devam.assert_called_once_with(g["gorev_id"])

    def test_iptal_kaydi_silmez(self):
        g = gorev("calisiyor", ["planlandi"])
        durum._DEPO.kaydet(g)
        d = self.pencere()
        d.cancel_btn.click()
        self.assertEqual(durum._DEPO.getir(g["gorev_id"])["durum"], "iptal")
        self.assertFalse(d.cancel_btn.isEnabled())


if __name__ == "__main__":
    unittest.main()
