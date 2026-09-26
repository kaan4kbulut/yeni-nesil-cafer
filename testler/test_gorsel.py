"""Görsel sekmesi (gui/media_panel.py) testleri: ekransız Qt ile gerçek dosyalar.

Çalıştırma (proje kökünde, programın Python'uyla):
    ~/.local/share/yeni-nesil-cafer-app/python/bin/python3 -m unittest discover -s testler -v
"""

import os
import shutil
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path

KOK = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(KOK))
_GECICI = tempfile.mkdtemp(prefix="yeni-nesil-cafer-test-")
os.environ["XDG_CONFIG_HOME"] = str(Path(_GECICI) / "ayar")  # kullanıcının gerçek ayar ve verisine dokunulmaz
os.environ["XDG_DATA_HOME"] = str(Path(_GECICI) / "veri")
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QEventLoop, QTimer  # noqa: E402
from PySide6.QtGui import QColor, QImage  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

APP = QApplication.instance() or QApplication([])

from asistan.gui import media_panel as mp  # noqa: E402

KUP_STL = "solid k\n" + "".join(
    f"facet normal 0 0 0\nouter loop\nvertex {a}\nvertex {b}\nvertex {c}\nendloop\nendfacet\n"
    for a, b, c in [("0 0 0", "40 0 0", "40 20 0"), ("0 0 0", "40 20 0", "0 20 0"),
                    ("0 0 10", "40 20 10", "40 0 10"), ("0 0 10", "0 20 10", "40 20 10")]) + "endsolid k\n"


def bekle(ms: int):
    loop = QEventLoop()
    QTimer.singleShot(ms, loop.quit)
    loop.exec()


def resim(path: Path, color="red", size=(64, 48)):
    img = QImage(*size, QImage.Format_RGB32)
    img.fill(QColor(color))
    path.parent.mkdir(parents=True, exist_ok=True)
    img.save(str(path))


class GorselTesti(unittest.TestCase):
    def setUp(self):
        self.dir = Path(tempfile.mkdtemp(prefix="gorsel-"))
        self.panel = mp.MediaPanel()
        self.panel.resize(420, 560)

    def tearDown(self):
        self.panel.shutdown()
        shutil.rmtree(self.dir, ignore_errors=True)

    def test_tarama_gizlileri_ve_derinligi_atlar(self):
        resim(self.dir / "a.png")
        resim(self.dir / "Resimler" / ".canli-onizleme.png")  # canlı önizleme: galeriye girmez
        resim(self.dir / ".gizli" / "b.png")
        (self.dir / "model.stl").write_text(KUP_STL)
        (self.dir / "notlar.txt").write_text("x")
        derin = self.dir / "1" / "2" / "3" / "4" / "5"
        resim(derin / "c.png")
        found = {Path(p).name for p in mp.scan(str(self.dir))}
        self.assertEqual(found, {"a.png", "model.stl"})

    def test_klasor_acilinca_en_yeni_gosterilir(self):
        resim(self.dir / "eski.png")
        t = time.time() - 60
        os.utime(self.dir / "eski.png", (t, t))
        resim(self.dir / "yeni.png", "blue")
        self.panel.set_root(str(self.dir))
        self.assertEqual(Path(self.panel.current).name, "yeni.png")
        self.assertEqual(self.panel.gallery.count(), 2)
        self.assertIs(self.panel.stack.currentWidget(), self.panel.image)

    def test_yeni_dosya_yazilinca_kendiliginden_acilir(self):
        self.panel.set_root(str(self.dir))
        self.assertIs(self.panel.stack.currentWidget(), self.panel.empty)
        gelen = []
        self.panel.new_media.connect(lambda: gelen.append(1))
        resim(self.dir / "kareler" / "kare-001.png")
        self.panel._scan()  # ilk görülüş: yazılıyor olabilir, bekler
        self.assertEqual(self.panel.current, "")
        self.panel._scan()  # iki taramadır aynı: yazılması bitti
        self.assertEqual(Path(self.panel.current).name, "kare-001.png")
        self.assertEqual(gelen, [1])

    def test_yenileri_goster_kapaliyken_yalnizca_galeriye_eklenir(self):
        self.panel.set_root(str(self.dir))
        self.panel.follow.setChecked(False)
        self.panel.show()
        resim(self.dir / "a.png")
        self.panel._scan()
        self.panel._scan()
        self.assertEqual(self.panel.gallery.count(), 1)
        self.assertEqual(self.panel.current, "")

    def test_canli_uretim(self):
        self.panel.set_root(str(self.dir))
        onizleme = self.dir / "Resimler" / ".canli-onizleme.png"
        resim(onizleme, "gray")
        self.panel.live(str(onizleme), 40, "adım 12/30")
        self.assertTrue(self.panel.live_active)
        self.assertFalse(self.panel.live_row.isHidden())
        self.assertEqual(self.panel.live_bar.value(), 40)
        self.assertIn("adım 12/30", self.panel.live_label.text())
        self.assertIs(self.panel.stack.currentWidget(), self.panel.image)
        sonuc = self.dir / "Resimler" / "resim-1.png"
        resim(sonuc, "green")
        self.panel.live("", -1, "")
        self.panel.live(str(sonuc), -1, "bitti")
        self.assertFalse(self.panel.live_active)
        self.assertTrue(self.panel.live_row.isHidden())
        self.assertEqual(self.panel.current, str(sonuc))
        self.assertEqual(self.panel.gallery.count(), 1)  # canlı önizleme galeriye girmedi

    def test_3d_model_olculeri(self):
        stl = self.dir / "parca.stl"
        stl.write_text(KUP_STL)
        self.panel.set_root(str(self.dir))
        self.assertIs(self.panel.stack.currentWidget(), self.panel._model)
        for _ in range(20):
            bekle(100)
            if not self.panel._model.timer.isActive():
                break
        info = self.panel._model.info.text()
        self.assertNotIn("hata", info)
        self.assertNotIn("yükleniyor", info)
        if os.environ.get("QT_QPA_PLATFORM") != "offscreen":  # ekransızda 3D çizilmez, sınırlar hesaplanmaz
            self.assertIn("40.0 × 20.0 × 10.0", info)

    @unittest.skipUnless(shutil.which("ffmpeg"), "ffmpeg yok (test videosu üretilemez)")
    def test_video(self):
        video = self.dir / "animasyon.mp4"
        subprocess.run(["ffmpeg", "-loglevel", "error", "-f", "lavfi", "-i", "testsrc=duration=1:size=160x120:rate=10",
                        "-pix_fmt", "yuv420p", str(video)], check=True)
        self.panel.set_root(str(self.dir))
        view = self.panel._video
        self.assertIs(self.panel.stack.currentWidget(), view)
        for _ in range(30):
            bekle(100)
            if view.player.duration() > 0 or view.error:
                break
        self.assertEqual(view.error, "")
        self.assertGreater(view.player.duration(), 500)


if __name__ == "__main__":
    unittest.main()
