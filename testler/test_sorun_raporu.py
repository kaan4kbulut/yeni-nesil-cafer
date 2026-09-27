"""Sorun raporu (problem_report.py): içerik, anahtar gizleme, dosya, çökme günlüğü, sohbetteki kart.

Masaüstüne yazılmaz (geçici klasör); ön teşhis modeli sahte.

Çalıştırma (proje kökünde, programın Python'uyla):
    ~/.local/share/yeni-nesil-cafer-app/python/bin/python3 -m unittest discover -s testler -v
"""

import os
import sys
import tempfile
import threading
import time
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

from asistan import learning  # noqa: E402
from asistan import problem_report as pr  # noqa: E402
from asistan import results  # noqa: E402
from asistan.config import Settings  # noqa: E402

ANAHTAR = "sk-ant-api03-GERCEKANAHTAR1234567890"
SOHBET = [
    {"role": "user", "content": "rapor.xlsx dosyasına grafik ekle"},
    {"role": "assistant", "content": "", "tool_calls": [{"function": {"name": "run_python",
                                                                      "arguments": {"code": "import openpyxl"}}}]},
    {"role": "tool", "tool_name": "run_python", "content": "Traceback: ModuleNotFoundError: No module named 'xlsxwriter'"},
    {"role": "user", "_program": True, "content": "Step 1 is NOT done yet."},
    {"role": "assistant", "content": [{"type": "text", "text": "Deniyorum"},
                                      {"type": "tool_use", "name": "call_api", "input": {"api": "x", "key": ANAHTAR}},
                                      {"type": "tool_result", "content": "401 unauthorized", "is_error": True}]},
]


class RaporTesti(unittest.TestCase):
    def rapor(self, **kw):
        with mock.patch.object(pr, "secrets", return_value=[ANAHTAR]), \
                mock.patch.object(pr, "diagnose", return_value="- xlsxwriter kurulu değil olabilir"):
            return pr.build(kw.get("kind", "tamamlanamadi"), "ModuleNotFoundError: xlsxwriter", SOHBET[0]["content"],
                            "qwen3.5:9b", Settings(), SOHBET, "/tmp/is", kw.get("note", ""))

    def test_bolumler_ve_claude_code_yonergesi(self):
        text = self.rapor()
        for baslik in ("# YENİ NESİL CAFER sorun raporu", "Claude Code için", "CLAUDE.md", "## Ne oldu",
                       "## Programın ön teşhisi", "xlsxwriter kurulu değil", "## Sistem", "## Sohbetin son bölümü",
                       "## Program günlüğünün sonu", "İş tamamlanamadı"):
            self.assertIn(baslik, text)

    def test_sohbet_bicimleri_okunur(self):
        text = self.rapor()
        self.assertIn("→ araç run_python", text)  # Ollama/OpenAI araç çağrısı
        self.assertIn("No module named 'xlsxwriter'", text)  # araç sonucu
        self.assertIn("→ araç call_api", text)  # Claude tool_use bloğu
        self.assertIn("sonuç (HATA): 401", text)
        self.assertIn("**[program]**", text)  # programın uyarısı ayrı görünür

    def test_anahtar_hic_yazilmaz(self):
        text = self.rapor(note=f"anahtarım {ANAHTAR} ve Bearer abcdefghijklmnopqrstuvwx")
        self.assertNotIn(ANAHTAR, text)
        self.assertNotIn("abcdefghijklmnopqrstuvwx", text)
        self.assertIn("«gizlendi»", text)

    def test_dosya_masaustune_ve_kopyasi(self):
        masa = Path(tempfile.mkdtemp())
        with mock.patch.object(results, "desktop", return_value=masa):
            path = pr.write("# rapor")
        self.assertEqual(path.parent, masa / "YENİ NESİL CAFER" / "Sorun Raporları")  # masaüstü dağılmasın
        self.assertTrue((pr.REPORTS_DIR / path.name).is_file())
        self.assertIn(str(path), pr.claude_prompt(path))


class CokmeTesti(unittest.TestCase):
    def test_is_parcacigi_hatasi_gunluge_ve_oneriye(self):
        gelen = []
        eski_sys, eski_thr = sys.excepthook, threading.excepthook
        try:
            pr.install_crash_log(gelen.append)
            t = threading.Thread(target=lambda: 1 / 0)
            t.start()
            t.join()
        finally:
            sys.excepthook, threading.excepthook = eski_sys, eski_thr
        self.assertEqual(gelen, ["ZeroDivisionError: division by zero"])
        self.assertIn("ZeroDivisionError", pr.log_tail())
        self.assertEqual(learning.issues()[-1]["kind"], "cokme")


class KartTesti(unittest.TestCase):
    def test_dugme_raporu_hazirlar_ve_panoya_koyar(self):
        from asistan.gui.chat import ReportOffer

        cagri = []
        card = ReportOffer("Sorun oldu", cagri.append)
        card.button.click()
        self.assertEqual(cagri, [card])
        self.assertFalse(card.button.isEnabled())
        card.done("/tmp/rapor.md", "rapor.md dosyasını oku")
        self.assertEqual(APP.clipboard().text(), "rapor.md dosyasını oku")
        self.assertIn("/tmp/rapor.md", card.label.text())


class OnizlemeTesti(unittest.TestCase):
    def pencere(self):
        from PySide6.QtWidgets import QWidget

        from asistan.gui.window_help import HelpMixin

        class Pencere(HelpMixin, QWidget):
            pass
        return Pencere()

    def test_duzenlenen_metin_gizlenerek_kaydedilir(self):
        from asistan.gui import window_help

        card = mock.Mock()
        masa = Path(tempfile.mkdtemp())

        def onayla(dlg):
            dlg.editor.setPlainText("# rapor\nkişisel satır silindi\nsonradan yapıştırılan " + ANAHTAR)
            return 1

        with mock.patch.object(window_help.ReportPreview, "exec", onayla), \
                mock.patch.object(results, "desktop", return_value=masa), mock.patch.object(pr, "secrets", return_value=[]):
            self.pencere()._report_built("# rapor\nkişisel satır", "", card)
        yazilan = next(masa.rglob("*.md")).read_text()
        self.assertIn("kişisel satır silindi", yazilan)
        self.assertNotIn(ANAHTAR, yazilan)
        self.assertTrue(card.done.called)

    def test_iptalde_dosya_yazilmaz(self):
        from asistan.gui import window_help

        card = mock.Mock()
        masa = Path(tempfile.mkdtemp())
        with mock.patch.object(window_help.ReportPreview, "exec", lambda dlg: 0), \
                mock.patch.object(results, "desktop", return_value=masa):
            self.pencere()._report_built("# rapor", "", card)
        self.assertEqual(list(masa.rglob("*.md")), [])
        self.assertTrue(card.cancelled.called)


if __name__ == "__main__":
    unittest.main()
