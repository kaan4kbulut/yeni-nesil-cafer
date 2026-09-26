"""inspect_output (görsel denetim): çıktıyı resme çevirme ve yapı raporu. Görme modeline gidilmez.

Ajan kütüphaneleri (matplotlib, trimesh, python-docx…) yoksa ilgili testler atlanır.

Çalıştırma (proje kökünde, programın Python'uyla):
    ~/.local/share/yeni-nesil-cafer-app/python/bin/python3 -m unittest discover -s testler -v
"""

import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

KOK = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(KOK))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
# kurulu programın hazır kütüphaneleri ve sonradan kurulanlar (kaynak klasöründen çalışırken de bulunsun)
_EK = [Path.home() / ".local/share/yeni-nesil-cafer-app/ajan-kutuphaneleri",
       Path.home() / ".local/share/yerel-asistan-app/ajan-kutuphaneleri",  # eski adlı kurulum
       Path(os.environ.get("XDG_DATA_HOME") or Path.home() / ".local/share") / "yerel-asistan/python-kutuphaneleri",
       Path(os.environ.get("XDG_DATA_HOME") or Path.home() / ".local/share") / "yeni-nesil-cafer/python-kutuphaneleri"]
os.environ["PYTHONPATH"] = os.pathsep.join([str(p) for p in _EK if p.is_dir()] + [os.environ.get("PYTHONPATH", "")])

from PySide6.QtGui import QColor, QImage  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

APP = QApplication.instance() or QApplication([])

from asistan import inspect_output as io  # noqa: E402
from asistan.tools import agent_env, python_exe  # noqa: E402

KUP = "solid k\n" + "".join(
    f"facet normal 0 0 0\nouter loop\nvertex {a}\nvertex {b}\nvertex {c}\nendloop\nendfacet\n" for a, b, c in [
        ("0 0 0", "10 10 0", "10 0 0"), ("0 0 0", "0 10 0", "10 10 0"), ("0 0 5", "10 0 5", "10 10 5"),
        ("0 0 5", "10 10 5", "0 10 5"), ("0 0 0", "10 0 0", "10 0 5"), ("0 0 0", "10 0 5", "0 0 5"),
        ("10 0 0", "10 10 0", "10 10 5"), ("10 0 0", "10 10 5", "10 0 5"), ("10 10 0", "0 10 0", "0 10 5"),
        ("10 10 0", "0 10 5", "10 10 5"), ("0 10 0", "0 0 0", "0 0 5"), ("0 10 0", "0 0 5", "0 10 5")]) + "endsolid\n"


def var(*moduller: str) -> bool:
    code = "; ".join(f"import {m}" for m in moduller)
    return subprocess.run([python_exe(), "-c", code], env=agent_env(), capture_output=True).returncode == 0


class DenetimTesti(unittest.TestCase):
    def setUp(self):
        self.dir = Path(tempfile.mkdtemp(prefix="denetim-"))
        self.out = self.dir / ".denetim"

    def test_resim_oldugu_gibi(self):
        img = QImage(20, 20, QImage.Format_RGB32)
        img.fill(QColor("red"))
        img.save(str(self.dir / "a.png"))
        self.assertEqual(io.render(self.dir / "a.png", self.out), (self.dir / "a.png", ""))

    def test_pdf_ve_svg_resme_cevrilir(self):
        from PySide6.QtGui import QPageSize, QPainter, QPdfWriter

        pdf = QPdfWriter(str(self.dir / "r.pdf"))
        pdf.setPageSize(QPageSize(QPageSize.A4))
        painter = QPainter(pdf)
        painter.drawText(100, 100, "Rapor")
        pdf.newPage()
        painter.drawText(100, 100, "Sayfa 2")
        painter.end()
        png, facts = io.render(self.dir / "r.pdf", self.out)
        self.assertTrue(png.is_file())
        self.assertIn("2 pages", facts)
        (self.dir / "c.svg").write_text('<svg xmlns="http://www.w3.org/2000/svg" width="100" height="50">'
                                        '<rect width="100" height="50" fill="blue"/></svg>')
        png, facts = io.render(self.dir / "c.svg", self.out)
        self.assertTrue(png.is_file())
        self.assertEqual(QImage(str(png)).width(), 1000)

    @unittest.skipUnless(var("trimesh", "matplotlib"), "trimesh ya da matplotlib yok")
    def test_3d_uc_gorunus(self):
        (self.dir / "kup.stl").write_text(KUP)
        png, facts = io.render(self.dir / "kup.stl", self.out)
        self.assertTrue(png.is_file())
        self.assertIn("3 views", facts)
        self.assertGreater(QImage(str(png)).width(), 1000)

    @unittest.skipUnless(var("docx"), "python-docx yok")
    def test_word_yapi_raporu(self):
        subprocess.run([python_exe(), "-c", "from docx import Document; d = Document(); d.add_heading('Satış', 0); "
                        f"d.add_table(rows=2, cols=2); d.save({str(self.dir / 'r.docx')!r})"], env=agent_env(),
                       check=True)
        png, facts = io.render(self.dir / "r.docx", self.out)
        self.assertIsNone(png)
        self.assertIn('"tables": 1', facts)
        self.assertIn("Satış", facts)

    def test_desteklenmeyen_tur(self):
        (self.dir / "x.bin").write_bytes(b"\x00")
        with self.assertRaises(ValueError):
            io.render(self.dir / "x.bin", self.out)


class AracTesti(unittest.TestCase):
    def test_gorme_modeline_soruyla_gider(self):
        from asistan import agent as ag
        from asistan.config import Settings

        ws = Path(tempfile.mkdtemp(prefix="denetim-is-"))
        img = QImage(20, 20, QImage.Format_RGB32)
        img.fill(QColor("red"))
        img.save(str(ws / "a.png"))
        a = ag.Agent(Settings(workspace=str(ws)), mock.Mock())
        with mock.patch.object(a, "_consult", return_value="Yes. Red square.") as consult:
            out = a._tool_inspect_output({"path": "a.png", "question": "Is it a red square?"})
        self.assertIn("Vision check: Yes. Red square.", out)
        self.assertIn("Is it a red square?", consult.call_args.args[1]["question"])
        with self.assertRaises(ag.ToolError):
            a._tool_inspect_output({"path": "yok.png", "question": "?"})


if __name__ == "__main__":
    unittest.main()
