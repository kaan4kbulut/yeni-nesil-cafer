"""tarayici yeteneği: aç → oku / ürünleri çıkar sırası, ürün satırlarının ayrıştırılması, liste yoksa dürüst hata.
Gerçek tarayıcı açılmaz (araç sahte); `extract_items`'ın HTML testleri `testler/test_urun_listesi.py`'de."""

import importlib.util
import json
import sys
import unittest
from pathlib import Path

KLASOR = Path(__file__).resolve().parent
sys.path.insert(0, str(KLASOR.parents[2]))
from asistan.cekirdek.yetenek import Baglam, YetenekHatasi  # noqa: E402

_spec = importlib.util.spec_from_file_location("yetenek_tarayici", KLASOR / "calistir.py")
yetenek = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(yetenek)
MANIFEST = json.loads((KLASOR / "manifest.json").read_text(encoding="utf-8"))

URUNLER = ("2 ürün (yapısal veri) — https://site.test/ara\n"
           + json.dumps({"ad": "Kahve Makinesi", "fiyat": 1299.9, "para_birimi": "TRY", "url": "https://site.test/1"})
           + "\n" + json.dumps({"ad": "Çaydanlık", "fiyat": 450.0, "para_birimi": "TRY", "url": "https://site.test/2"}))


class TestTarayici(unittest.TestCase):
    def baglam(self, urunler=URUNLER):
        self.cagrilar = []

        def arac(ad, args):
            self.cagrilar.append((ad, args))
            return {"browser_open": "Sayfa: Example Domain", "browser_read": "süzülmüş metin",
                    "browser_extract_items": urunler}[ad]
        return Baglam(calisma_klasoru=str(KLASOR), arac=arac)

    def test_oku(self):
        self.assertEqual(yetenek.calistir(MANIFEST["ornekler"][0]["girdi"], self.baglam()),
                         {"sonuc": "Sayfa: Example Domain"})
        self.assertEqual([a for a, _ in self.cagrilar], ["browser_open"])

    def test_oku_bul_ile(self):
        sonuc = yetenek.calistir({"url": "https://example.com", "bul": "fiyat"}, self.baglam())
        self.assertEqual(sonuc, {"sonuc": "süzülmüş metin"})
        self.assertEqual(self.cagrilar[-1], ("browser_read", {"find": "fiyat"}))

    def test_urunler(self):
        sonuc = yetenek.calistir(MANIFEST["ornekler"][1]["girdi"], self.baglam())
        self.assertEqual([a for a, _ in self.cagrilar], ["browser_open", "browser_extract_items"])
        self.assertEqual(len(sonuc["urunler"]), 2)
        self.assertEqual(sonuc["urunler"][0]["fiyat"], 1299.9)

    def test_liste_yoksa_uydurmaz(self):
        with self.assertRaises(YetenekHatasi) as h:
            yetenek.calistir({"url": "https://example.com", "islem": "urunler"}, self.baglam("0 ürün\n"))
        self.assertEqual(h.exception.sinif, "veri")

    def test_eksik_girdi_ve_gecersiz_islem(self):
        with self.assertRaises(YetenekHatasi):
            yetenek.calistir({}, self.baglam())
        with self.assertRaises(YetenekHatasi):
            yetenek.calistir({"url": "https://example.com", "islem": "tikla"}, self.baglam())
        self.assertEqual(self.cagrilar, [])


if __name__ == "__main__":
    unittest.main()
