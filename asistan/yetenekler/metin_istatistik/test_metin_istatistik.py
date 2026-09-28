"""metin_istatistik yeteneği: manifestteki örnekler (doğrudan ve gerçek sandbox'ta), hata yolları (eksik girdi, dosya
yok), sandbox'ta izin dışı okuma engeli. Ağ yok; veri klasörüne yazılmaz (venv geçici klasörde)."""

import importlib.util
import json
import os
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

KLASOR = Path(__file__).resolve().parent
sys.path.insert(0, str(KLASOR.parents[2]))
_GECICI = tempfile.mkdtemp(prefix="yeni-nesil-cafer-test-")
os.environ["XDG_CONFIG_HOME"] = str(Path(_GECICI) / "ayar")
os.environ["XDG_DATA_HOME"] = str(Path(_GECICI) / "veri")

from asistan.cekirdek.yetenek import Baglam, YetenekHatasi  # noqa: E402
from asistan.cekirdek.yetenek import calistirici  # noqa: E402
from asistan.cekirdek.yetenek.kayit import Kayit  # noqa: E402

_spec = importlib.util.spec_from_file_location("yetenek_metin_istatistik", KLASOR / "calistir.py")
yetenek = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(yetenek)
MANIFEST = json.loads((KLASOR / "manifest.json").read_text(encoding="utf-8"))


def calisma_klasoru() -> str:
    klasor = tempfile.mkdtemp(dir=_GECICI)
    shutil.copytree(KLASOR / "ornek_dosyalar", klasor, dirs_exist_ok=True)
    return klasor


class TestMetinIstatistik(unittest.TestCase):
    def test_ornekler(self):
        birinci = yetenek.calistir(MANIFEST["ornekler"][0]["girdi"], Baglam(calisma_klasoru()))
        self.assertEqual((birinci["satir"], birinci["kelime"]), (3, 13))
        self.assertEqual(birinci["en_sik_kelimeler"][0], {"kelime": "kedi", "adet": 3})
        ikinci = yetenek.calistir(MANIFEST["ornekler"][1]["girdi"], Baglam(calisma_klasoru()))
        self.assertEqual(len(ikinci["en_sik_kelimeler"]), 2)

    def test_turkce_buyuk_harf(self):
        klasor = calisma_klasoru()
        Path(klasor, "t.txt").write_text("İSTANBUL istanbul IŞIK ışık", encoding="utf-8")
        sonuc = yetenek.calistir({"yol": "t.txt", "en_sik": 2}, Baglam(klasor))
        self.assertEqual({k["kelime"]: k["adet"] for k in sonuc["en_sik_kelimeler"]}, {"istanbul": 2, "ışık": 2})

    def test_hata_yollari(self):
        with self.assertRaises(YetenekHatasi) as h:
            yetenek.calistir({}, Baglam(calisma_klasoru()))
        self.assertEqual(h.exception.sinif, "veri")
        with self.assertRaises(YetenekHatasi) as h:
            yetenek.calistir({"yol": "yok.txt"}, Baglam(calisma_klasoru()))
        self.assertEqual(h.exception.sinif, "veri")
        with self.assertRaises(YetenekHatasi):
            yetenek.calistir({"yol": "ornek.txt", "en_sik": 0}, Baglam(calisma_klasoru()))

    def test_sandboxta_calisir_ve_disari_okuyamaz(self):
        kayit = Kayit([KLASOR.parent], kademe="orta")
        y = kayit.getir("metin_istatistik")
        self.assertTrue(y.aktif, y.neden)
        self.assertTrue(y.sandbox)
        ortamlar = Path(_GECICI) / "ortamlar"
        sonuc = calistirici.calistir(y, {"yol": "ornek.txt"}, Baglam(calisma_klasoru()), ortamlar=ortamlar)
        self.assertEqual(sonuc["kelime"], 13)
        disarida = Path(tempfile.mkdtemp()) / "gizli.txt"  # çalışma klasörü ve okuma kökleri dışında
        disarida.write_text("gizli", encoding="utf-8")
        with self.assertRaises(YetenekHatasi) as h:
            calistirici.calistir(y, {"yol": str(disarida)}, Baglam(calisma_klasoru()), ortamlar=ortamlar)
        self.assertEqual(h.exception.sinif, "izin")


if __name__ == "__main__":
    unittest.main()
