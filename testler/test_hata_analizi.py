"""K6 — `cekirdek/analiz/hata.py`: 8 sınıf için desen tabanlı sınıflandırıcı + eylem tablosu (MIMARI §7), bilinmeyen →
hızlı modele şema-kısıtlı soru, hedef çıkarımı (pip/ikili/yetenek), kütük ve kalıcı desen ekleme."""

import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

KOK = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(KOK))
_GECICI = tempfile.mkdtemp(prefix="yeni-nesil-cafer-test-")
os.environ["XDG_CONFIG_HOME"] = str(Path(_GECICI) / "ayar")
os.environ["XDG_DATA_HOME"] = str(Path(_GECICI) / "veri")

from asistan.cekirdek import ayar, yonlendirici  # noqa: E402
from asistan.cekirdek.analiz import hata  # noqa: E402
from asistan.cekirdek.gorev import Cevap, yurutucu  # noqa: E402

ORNEKLER = {
    "eksik_bagimlilik": ["ModuleNotFoundError: No module named 'openpyxl'", "bash: ffmpeg: command not found",
                         "metin_istatistik kullanılamıyor: Python paketi kurulu değil: pandas"],
    "eksik_yetenek": ["'pdf_tablo' adlı yetenek yok (kayıtlı yetenekler: dosya_oku)", "bunu yapacak yeteneğim yok"],
    "izin": ["The user declined to run this.", "PermissionError: [Errno 13] Permission denied: '/etc/x'"],
    "ag": ["httpx.ConnectError: bağlanılamadı", "HTTP 503 Service Unavailable", "ReadTimeout: timed out"],
    "kaynak": ["CUDA out of memory. Tried to allocate 2 GiB", "OSError: No space left on device"],
    "veri": ["FileNotFoundError: rapor.txt", "dosya bulunamadı: not.txt", "UnicodeDecodeError: 'utf-8' codec"],
    "model_yetersiz": ["plan şemaya uymuyor: adimlar[0].yetenek eksik", "$: JSON nesnesi yok"],
    "mantik": ["liste boş döndü ama 3 satır bekleniyordu", "sayı toplamla tutarsız"],
}


class SahteModel:
    def __init__(self, sinif="kaynak"):
        self.sinif, self.cagrilar = sinif, 0

    def __call__(self, rol, mesajlar, sistem="", sema=None):
        self.cagrilar += 1
        return Cevap(json.dumps({"sinif": self.sinif}), {"sinif": self.sinif}, {"model": "sahte"})


class Siniflandirma(unittest.TestCase):
    def test_her_sinif_dogru_eyleme(self):
        beklenen = {"eksik_bagimlilik": "kur", "eksik_yetenek": "uret", "izin": "sor", "ag": "tekrar", "kaynak": "kucult",
                    "veri": "bildir", "model_yetersiz": "yukselt", "mantik": "yeniden_planla"}
        for sinif, metinler in ORNEKLER.items():
            for metin in metinler:
                self.assertEqual(hata.siniflandir(metin), sinif, metin)
                self.assertEqual(hata.eylem(sinif)["tip"], beklenen[sinif], sinif)
        self.assertEqual(set(hata.EYLEMLER), set(hata.SINIFLAR))

    def test_yanlis_pozitifler(self):
        self.assertEqual(hata.siniflandir("512 bayt okundu"), "mantik")
        self.assertEqual(hata.siniflandir("CUDA 12.4 ile derlendi ama sonuç yanlış"), "mantik")
        self.assertEqual(hata.siniflandir("liste bulunamadı (sayfada ürün yok)"), "mantik")

    def test_bilinmeyen_hizli_modele_sorulur(self):
        m = SahteModel("kaynak")
        self.assertEqual(hata.siniflandir("garip bir şey oldu", model=m), "kaynak")
        self.assertEqual(m.cagrilar, 1)
        self.assertEqual(hata.siniflandir("ModuleNotFoundError: x", model=m), "eksik_bagimlilik")
        self.assertEqual(m.cagrilar, 1)  # desen tutunca model sorulmaz
        self.assertEqual(hata.siniflandir("garip", model=None), "mantik")
        self.assertEqual(hata.siniflandir("", "", model_adimi=True), "model_yetersiz")

    def test_hedef(self):
        self.assertEqual(hata.hedef("eksik_bagimlilik", "No module named 'openpyxl.cell'"), "pip:openpyxl")
        self.assertEqual(hata.hedef("eksik_bagimlilik", "Python paketi kurulu değil: pandas"), "pip:pandas")
        self.assertEqual(hata.hedef("eksik_bagimlilik", "'ffmpeg' programı kurulu değil"), "ikili:ffmpeg")
        self.assertEqual(hata.hedef("eksik_bagimlilik", "bash: ffmpeg: command not found"), "ikili:ffmpeg")
        self.assertEqual(hata.hedef("eksik_yetenek", "'pdf_tablo' adlı yetenek yok"), "yetenek:pdf_tablo")
        self.assertEqual(hata.hedef("mantik", "x"), "")

    def test_yurutucu_devreder(self):
        self.assertEqual(yurutucu.siniflandir("No module named 'x'", "", False), "eksik_bagimlilik")
        self.assertEqual(yurutucu.siniflandir("", "", True), "model_yetersiz")


class Kutuk(unittest.TestCase):
    def setUp(self):
        for ad in ("hatalar.jsonl", "hata_desenleri.json"):
            (ayar.DATA_DIR / ad).unlink(missing_ok=True)

    def test_isle_tamamlar_ve_yazar(self):
        kayit = {"adim": 2, "belirti": "ModuleNotFoundError: No module named 'docx'", "kanit": "Traceback…"}
        k = hata.isle(kayit)
        self.assertEqual(k["sinif"], "eksik_bagimlilik")
        self.assertEqual(k["eylem"]["tip"], "kur")
        self.assertEqual(k["eylem"]["hedef"], "pip:docx")
        self.assertEqual(k["eylem"]["onay"], "sor")
        self.assertEqual(k["sonuc"], "vazgecildi")
        self.assertEqual(hata.kutuk()[0]["adim"], 2)
        # yürütücünün verdiği geçerli sınıf korunur; "mantik" yeniden sınıflandırılır
        self.assertEqual(hata.isle({"sinif": "veri", "belirti": "No module named 'x'"})["sinif"], "veri")
        self.assertEqual(hata.isle({"sinif": "mantik", "belirti": "No module named 'x'"})["sinif"], "eksik_bagimlilik")

    def test_devret_analize_gider(self):
        kayit = {"adim": 3, "sinif": "model_yetersiz", "belirti": "zincir bitti", "kanit": "", "eylem": {}, "sonuc": "x"}
        self.assertEqual(yonlendirici.devret(kayit), "analiz")
        self.assertEqual(hata.kutuk()[0]["eylem"]["tip"], "yukselt")

    def test_desen_ekle_kalici(self):
        self.assertEqual(hata.siniflandir("XYZ-42 sürücü hatası"), "mantik")
        hata.desen_ekle("kaynak", r"XYZ-\d+ sürücü hatası", "NVIDIA Xid")
        hata.desen_ekle("kaynak", r"XYZ-\d+ sürücü hatası")  # iki kez eklenmez
        self.assertEqual(hata.siniflandir("XYZ-42 sürücü hatası"), "kaynak")
        self.assertEqual(len(json.loads((ayar.DATA_DIR / "hata_desenleri.json").read_text(encoding="utf-8"))), 1)
        with self.assertRaises(ValueError):
            hata.desen_ekle("yok", "x")
        with self.assertRaises(Exception):
            hata.desen_ekle("ag", "(")


if __name__ == "__main__":
    unittest.main()
