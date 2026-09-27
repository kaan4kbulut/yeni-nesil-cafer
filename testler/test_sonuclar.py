"""Sonuçlar (results.py): işlerin görsel, 3D model, belge ve kod çıktıları masaüstündeki YENİ NESİL CAFER/Sonuçlar'a
kopyalanır; ara dosyalar, gizli önizlemeler, figür girdisi, ekler ve eski dosyalar kopyalanmaz.

Çalıştırma (proje kökünde, programın Python'uyla):
    ~/.local/share/yeni-nesil-cafer-app/python/bin/python3 -m unittest discover -s testler -v
"""

import os
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

KOK = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(KOK))
_GECICI = tempfile.mkdtemp(prefix="yeni-nesil-cafer-test-")
os.environ["XDG_CONFIG_HOME"] = str(Path(_GECICI) / "ayar")  # kullanıcının gerçek ayar ve verisine dokunulmaz
os.environ["XDG_DATA_HOME"] = str(Path(_GECICI) / "veri")

from asistan import agent as ag, results  # noqa: E402
from asistan.config import Settings  # noqa: E402


def yaz(path: Path, text: str = "x", yas: float = 0) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)
    if yas:
        os.utime(path, (time.time() - yas, time.time() - yas))
    return path


class Toplama(unittest.TestCase):
    def setUp(self):
        self.ws = Path(tempfile.mkdtemp(prefix="calisma-"))
        self.is_ = self.ws / "3D Modeller" / "oturan-kedi-4f2a"
        self.hedef = Path(tempfile.mkdtemp(prefix="sonuclar-"))
        self.bas = time.time() - 1

    def test_yalnizca_bu_turun_sonuclari(self):
        yaz(self.is_ / "3D" / "kedi.stl")
        yaz(self.is_ / "Resimler" / "resim-1.png")
        yaz(self.is_ / "hesap.py", "print(1)")  # bilerek yazılmış kod: sonuçtur
        yaz(self.is_ / "eski.png", yas=3600)  # önceki turdan
        yaz(self.is_ / "3D" / "kedi-girdi.png")  # figürün girdi resmi
        yaz(self.is_ / ".denetim" / "kedi-denetim.png")  # gizli önizleme
        yaz(self.is_ / "ekler" / "foto.jpg")  # kullanıcının kendi eki
        yaz(self.is_ / "Resimler" / "resim-1.json")  # resim üretiminin yan dosyası
        yaz(self.is_ / "ASISTAN.md")
        kopya = results.collect(self.is_, self.ws, self.bas, target_root=self.hedef)
        adlar = sorted(str(p.relative_to(self.hedef)) for p in kopya)
        self.assertEqual(adlar, ["3D Modeller/oturan-kedi-4f2a/3D/kedi.stl",
                                 "3D Modeller/oturan-kedi-4f2a/Resimler/resim-1.png",
                                 "3D Modeller/oturan-kedi-4f2a/hesap.py"])
        self.assertEqual(results.collect(self.is_, self.ws, self.bas, target_root=self.hedef), [])  # değişmedi
        time.sleep(0.01)
        yaz(self.is_ / "hesap.py", "print(2)")  # değişen dosya yeniden kopyalanır
        self.assertEqual(len(results.collect(self.is_, self.ws, self.bas, target_root=self.hedef)), 1)

    def test_eski_sohbet_genel_klasorune(self):
        yaz(self.ws / "tablo.xlsx")
        kopya = results.collect(self.ws, self.ws, self.bas, target_root=self.hedef)
        self.assertEqual([p.relative_to(self.hedef) for p in kopya], [Path("Genel/tablo.xlsx")])

    def test_masaustu_klasoru(self):
        with mock.patch.object(results, "desktop", return_value=self.hedef):
            self.assertEqual(results.results_dir(), self.hedef / "YENİ NESİL CAFER" / "Sonuçlar")


class AjanTopluyor(unittest.TestCase):
    def ajan(self, extra):
        ws = Path(tempfile.mkdtemp(prefix="calisma-"))
        a = ag.Agent(Settings(workspace=str(ws), extra=extra), None)
        a.run_started = time.time() - 1
        yaz(Path(a.toolbox.root) / "Resimler" / "logo.png")
        return a

    def test_ayara_gore(self):
        hedef = Path(tempfile.mkdtemp(prefix="sonuclar-"))
        with mock.patch.object(results, "results_dir", return_value=hedef):
            self.ajan({})._collect_results()  # varsayılan: açık
            self.assertEqual(len(list(hedef.rglob("logo.png"))), 1)
            bos = Path(tempfile.mkdtemp(prefix="sonuclar-"))
        with mock.patch.object(results, "results_dir", return_value=bos):
            self.ajan({"sonuclari_topla": False})._collect_results()
            self.assertEqual(list(bos.rglob("*")), [])
        bulut = self.ajan({})
        bulut.base_system = "bulut"
        with mock.patch.object(results, "results_dir", return_value=bos):
            bulut._collect_results()
            self.assertEqual(list(bos.rglob("*")), [])


if __name__ == "__main__":
    unittest.main()
