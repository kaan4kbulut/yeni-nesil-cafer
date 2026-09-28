"""saat_dilimi yeteneği: manifestteki örnekler (yer arama sahte), ağ yokken yerel eşleşme, API cevabının okunması
(urlopen sahte), hata yolları (eksik/bozuk girdi, bulunamayan şehir, ağ hatası), gerçek sandbox'ta ağsız çalışma
(IANA girdisi). Gerçek ağa çıkılmaz (atlanan test kabul edilmediği için): gerçek API `python -m asistan yetenek --duman
saat_dilimi` ile denenir. Veri klasörüne yazılmaz (venv geçici klasörde)."""

import importlib.util
import io
import json
import os
import sys
import tempfile
import unittest
import urllib.error
from datetime import datetime
from pathlib import Path
from unittest import mock
from zoneinfo import ZoneInfo

KLASOR = Path(__file__).resolve().parent
sys.path.insert(0, str(KLASOR.parents[2]))
_GECICI = tempfile.mkdtemp(prefix="yeni-nesil-cafer-test-")
os.environ["XDG_CONFIG_HOME"] = str(Path(_GECICI) / "ayar")
os.environ["XDG_DATA_HOME"] = str(Path(_GECICI) / "veri")

from asistan.cekirdek.yetenek import Baglam, YetenekHatasi  # noqa: E402
from asistan.cekirdek.yetenek import calistirici  # noqa: E402
from asistan.cekirdek.yetenek.kayit import Kayit  # noqa: E402

_spec = importlib.util.spec_from_file_location("yetenek_saat_dilimi", KLASOR / "calistir.py")
yetenek = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(yetenek)
MANIFEST = json.loads((KLASOR / "manifest.json").read_text(encoding="utf-8"))

# yer arama API'sinin cevabı (ilk sonuç), gerçek cevaptan kısaltılmış
SAHTE_YERLER = {
    "Ankara": {"name": "Ankara", "country": "Türkiye Cumhuriyeti", "timezone": "Europe/Istanbul"},
    "Tokyo": {"name": "Tokyo", "country": "Japonya", "timezone": "Asia/Tokyo"},
}


def sahte_ara(sehir):
    return SAHTE_YERLER.get(sehir)


def agsiz(sehir):
    raise YetenekHatasi("ag", "yer arama servisine ulaşılamadı: sahte")


def beklenen_fark(dilim: str) -> str:
    dk = int(datetime.now(ZoneInfo(dilim)).utcoffset().total_seconds() // 60)
    return yetenek.utc_fark_metni(dk)


def baglam() -> Baglam:
    return Baglam(calisma_klasoru=tempfile.mkdtemp(dir=_GECICI))


class TestSaatDilimi(unittest.TestCase):
    def dogrula(self, sonuc: dict, dilim: str):
        self.assertEqual(sonuc["saat_dilimi"], dilim)
        self.assertEqual(sonuc["utc_fark"], beklenen_fark(dilim))
        self.assertRegex(sonuc["saat"], r"^\d{4}-\d{2}-\d{2} \d{2}:\d{2}$")
        simdi = datetime.now(ZoneInfo(dilim)).replace(tzinfo=None)
        fark = abs((datetime.strptime(sonuc["saat"], "%Y-%m-%d %H:%M") - simdi).total_seconds())
        self.assertLess(fark, 120, "dönen saat o dilimin şu anki saati değil")

    def test_ornekler(self):
        beklenen = {"Ankara": "Europe/Istanbul", "Tokyo": "Asia/Tokyo", "Europe/London": "Europe/London"}
        with mock.patch.object(yetenek, "ara", side_effect=sahte_ara) as ara:
            for ornek in MANIFEST["ornekler"]:
                sehir = ornek["girdi"]["sehir"]
                sonuc = yetenek.calistir(ornek["girdi"], baglam())
                self.dogrula(sonuc, beklenen[sehir])
        self.assertEqual([c.args[0] for c in ara.call_args_list], ["Ankara", "Tokyo"])  # IANA adı ağa gitmez
        self.assertEqual(sonuc["yer"], "London")

    def test_yer_bilgisi_ve_sabit_farklar(self):
        with mock.patch.object(yetenek, "ara", side_effect=sahte_ara):
            ankara = yetenek.calistir({"sehir": " Ankara "}, baglam())
            tokyo = yetenek.calistir({"sehir": "Tokyo"}, baglam())
        self.assertEqual(ankara["yer"], "Ankara, Türkiye Cumhuriyeti")
        self.assertEqual(ankara["utc_fark"], "UTC+03:00")  # Türkiye'de yaz saati yok
        self.assertEqual(tokyo["utc_fark"], "UTC+09:00")

    def test_ag_yoksa_saat_dilimi_adindan_bulur(self):
        with mock.patch.object(yetenek, "ara", side_effect=agsiz):
            self.dogrula(yetenek.calistir({"sehir": "tokyo"}, baglam()), "Asia/Tokyo")
            istanbul = yetenek.calistir({"sehir": "İstanbul"}, baglam())
            self.assertIn(istanbul["saat_dilimi"], ("Europe/Istanbul", "Asia/Istanbul"))
            self.assertEqual(istanbul["utc_fark"], "UTC+03:00")
            self.dogrula(yetenek.calistir({"sehir": "new york"}, baglam()), "America/New_York")
            with self.assertRaises(YetenekHatasi) as h:  # dilim adlarında olmayan şehir: ağ hatası olduğu gibi
                yetenek.calistir({"sehir": "Ankara"}, baglam())
            self.assertEqual(h.exception.sinif, "ag")

    def test_utc_fark_metni(self):
        self.assertEqual(yetenek.utc_fark_metni(180), "UTC+03:00")
        self.assertEqual(yetenek.utc_fark_metni(0), "UTC+00:00")
        self.assertEqual(yetenek.utc_fark_metni(-210), "UTC-03:30")
        self.assertEqual(yetenek.utc_fark_metni(345), "UTC+05:45")

    def test_api_cevabi_okunur(self):
        govde = json.dumps({"results": [SAHTE_YERLER["Tokyo"]]}).encode("utf-8")
        with mock.patch("urllib.request.urlopen", return_value=io.BytesIO(govde)) as urlopen:
            self.assertEqual(yetenek.ara("Tokyo")["timezone"], "Asia/Tokyo")
        url = urlopen.call_args.args[0].full_url
        self.assertTrue(url.startswith(yetenek.ARAMA_URL + "?"))
        self.assertIn("name=Tokyo", url)
        self.assertIn("language=tr", url)
        with mock.patch("urllib.request.urlopen", return_value=io.BytesIO(b'{"generationtime_ms": 0.1}')):
            self.assertIsNone(yetenek.ara("xqzyw"))

    def test_ag_hatasi_sinifi(self):
        for hata in (urllib.error.URLError("ad çözülemedi"), TimeoutError("zaman aşımı")):
            with mock.patch("urllib.request.urlopen", side_effect=hata):
                with self.assertRaises(YetenekHatasi) as h:
                    yetenek.ara("Ankara")
                self.assertEqual(h.exception.sinif, "ag")
        with mock.patch("urllib.request.urlopen", return_value=io.BytesIO(b"<html>")):
            with self.assertRaises(YetenekHatasi) as h:
                yetenek.ara("Ankara")
            self.assertEqual(h.exception.sinif, "ag")

    def test_hata_yollari(self):
        for girdi in ({}, {"sehir": ""}, {"sehir": "   "}, {"sehir": 5}, {"sehir": "a" * 101}, "Ankara"):
            with self.assertRaises(YetenekHatasi) as h:
                yetenek.calistir(girdi, baglam())
            self.assertEqual(h.exception.sinif, "veri", girdi)
        with mock.patch.object(yetenek, "ara", return_value=None):
            with self.assertRaises(YetenekHatasi) as h:
                yetenek.calistir({"sehir": "xqzyw"}, baglam())
        self.assertEqual(h.exception.sinif, "veri")
        self.assertIn("bulunamadı", h.exception.mesaj)
        with mock.patch.object(yetenek, "ara", return_value={"name": "Bir yer"}):
            with self.assertRaises(YetenekHatasi) as h:
                yetenek.calistir({"sehir": "Bir yer"}, baglam())
        self.assertEqual(h.exception.sinif, "veri")

    def test_sandboxta_calisir(self):
        kayit = Kayit([KLASOR.parent], kademe="dusuk")
        y = kayit.getir("saat_dilimi")
        self.assertTrue(y.aktif, y.neden)
        self.assertTrue(y.sandbox)
        self.assertEqual(y.izinler, ["ag"])
        sonuc = calistirici.calistir(y, {"sehir": "Asia/Kolkata"}, baglam(), ortamlar=Path(_GECICI) / "ortamlar")
        self.assertEqual(sonuc["utc_fark"], "UTC+05:30")
        self.assertEqual(sonuc["saat_dilimi"], "Asia/Kolkata")
        with self.assertRaises(YetenekHatasi) as h:  # girdi şeması sandbox'tan önce denetlenir
            calistirici.calistir(y, {}, baglam(), ortamlar=Path(_GECICI) / "ortamlar")
        self.assertEqual(h.exception.sinif, "veri")


if __name__ == "__main__":
    unittest.main()
