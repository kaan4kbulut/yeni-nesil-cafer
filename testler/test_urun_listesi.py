"""K5 (eski Aşama 4) — ürün/ilan listesini yapısal okuma: `cekirdek/araclar/urunler.py` (JSON-LD → tekrar eden kartlar
→ bulunamadı), `browser_extract_items` aracı, tarayıcı ajanının profili ve yöneticinin fiyat denetimi
(`manager.fiyat_eksigi`). Tarayıcı açılmaz: sayfa HTML'i elle verilir.

Çalıştırma (proje kökünde, programın Python'uyla):
    ~/.local/share/yeni-nesil-cafer-app/python/bin/python3 -m unittest discover -s testler -v
"""

import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

KOK = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(KOK))
_GECICI = tempfile.mkdtemp(prefix="yeni-nesil-cafer-test-")
os.environ["XDG_CONFIG_HOME"] = str(Path(_GECICI) / "ayar")
os.environ["XDG_DATA_HOME"] = str(Path(_GECICI) / "veri")

from asistan.cekirdek.araclar import urunler  # noqa: E402
from asistan.cekirdek.araclar.temel import AracHatasi  # noqa: E402

JSON_LD = """<html><head><script type="application/ld+json">
{"@context": "https://schema.org", "@type": "ItemList", "itemListElement": [
  {"@type": "ListItem", "position": 1, "item": {"@type": "Product", "name": "Kahve Makinesi X",
   "url": "/urun/1", "offers": {"@type": "Offer", "price": "1299.90", "priceCurrency": "TRY"}}},
  {"@type": "ListItem", "position": 2, "item": {"@type": "Product", "name": "Çay Makinesi Y",
   "url": "https://site.test/urun/2", "offers": [{"@type": "AggregateOffer", "lowPrice": 849, "priceCurrency": "TRY"}]}},
  {"@type": "ListItem", "position": 3, "item": {"@type": "Product", "name": "Fiyatsız Ürün", "url": "/urun/3"}}
]}</script></head><body><p>Sayfa</p></body></html>"""

KARTLAR = """<html><body><div class="liste">
  <div class="kart p-1234"><a href="/p/1" title="Philips Airfryer XXL 7.3 L">Philips Airfryer</a>
     <span class="eski">1.599,00 TL</span><span class="fiyat">1.299,90 TL</span><small>3 x 433,30 TL taksit</small></div>
  <div class="kart p-1235"><a href="/p/2"><h3>Tefal Easy Fry</h3></a><span class="fiyat">₺2.450</span></div>
  <div class="kart p-1236"><a href="/p/3"><img alt="Xiaomi Mi Fritöz"></a><span class="fiyat">999 TL</span></div>
  <div class="reklam">Kampanya!</div>
</div><footer>Kargo 49,90 TL üzeri bedava</footer></body></html>"""

KITAPLAR = """<html><body><ol class="row">
  <li class="col-xs-6 col-sm-4"><article class="product_pod"><h3><a href="a/index.html" title="A Light in the Attic">A
     Light in the ...</a></h3><div class="product_price"><p class="price_color">£51.77</p></div></article></li>
  <li class="col-xs-6 col-sm-4"><article class="product_pod"><h3><a href="b/index.html" title="Tipping the Velvet">Tipping
     the ...</a></h3><div class="product_price"><p class="price_color">£53.74</p></div></article></li>
</ol></body></html>"""

# kartın kendisi bağlantı, ad sınıfında "name" geçen öğede, üstte rozet metni (canlı deneme: büyük bir TR sitesi)
BAGLANTI_KART = """<html><body><div class="sonuclar">
  <a class="product-card" href="/marka/fritoz-p-1"><div class="rozet">Kargo Bedava</div>
     <div class="info"><span class="product-name">Marka Airfryer XL Siyah</span>
     <div class="price"><div class="single-price">3.299 TL</div></div></div></a>
  <a class="product-card" href="/marka/fritoz-p-2"><div class="rozet">Hızlı Teslimat</div>
     <div class="info"><span class="product-name">Başka Fritöz 6.5 Litre</span>
     <div class="price"><div class="single-price">2.055,14 TL</div></div></div></a>
</div></body></html>"""

LISTESIZ ="<html><body><h1>Hakkımızda</h1><p>Kargo 49,90 TL üzeri bedava.</p><a href='/iletisim'>İletişim</a></body></html>"


class CikaricTesti(unittest.TestCase):
    def test_json_ld(self):
        liste, yontem = urunler.cikar(JSON_LD, "https://site.test/ara?q=makine")
        self.assertEqual(yontem, "json-ld")
        self.assertEqual([(o["ad"], o["fiyat"], o["para_birimi"]) for o in liste],
                         [("Kahve Makinesi X", 1299.9, "TRY"), ("Çay Makinesi Y", 849.0, "TRY")])  # fiyatsız yok
        self.assertEqual(liste[0]["url"], "https://site.test/urun/1")

    def test_tekrar_eden_kartlar(self):
        liste, yontem = urunler.cikar(KARTLAR, "https://magaza.test/fritoz")
        self.assertEqual(yontem, "dom")
        self.assertEqual([o["fiyat"] for o in liste], [1299.9, 2450.0, 999.0])  # eski fiyat ve taksit değil
        self.assertEqual(liste[0]["ad"], "Philips Airfryer XXL 7.3 L")
        self.assertEqual(liste[1]["ad"], "Tefal Easy Fry")
        self.assertEqual(liste[2]["ad"], "Xiaomi Mi Fritöz")
        self.assertEqual(liste[1]["url"], "https://magaza.test/p/2")

    def test_nokta_ondalikli_sterlin(self):
        liste, _ = urunler.cikar(KITAPLAR, "https://books.toscrape.com/")
        self.assertEqual([(o["ad"], o["fiyat"], o["para_birimi"]) for o in liste],
                         [("A Light in the Attic", 51.77, "GBP"), ("Tipping the Velvet", 53.74, "GBP")])

    def test_kartin_kendisi_baglanti(self):
        liste, yontem = urunler.cikar(BAGLANTI_KART, "https://site.test/sr?q=fritoz")
        self.assertEqual(yontem, "dom")
        self.assertEqual([(o["ad"], o["fiyat"], o["url"]) for o in liste],
                         [("Marka Airfryer XL Siyah", 3299.0, "https://site.test/marka/fritoz-p-1"),
                          ("Başka Fritöz 6.5 Litre", 2055.14, "https://site.test/marka/fritoz-p-2")])

    def test_liste_yoksa_bos(self):
        self.assertEqual(urunler.cikar(LISTESIZ, "https://site.test"), ([], ""))
        self.assertEqual(urunler.cikar("", ""), ([], ""))

    def test_fiyat_bicimleri(self):
        self.assertEqual(urunler.fiyatlar("1.299,90 TL"), [(1299.9, "TRY")])
        self.assertEqual(urunler.fiyatlar("₺12.345"), [(12345.0, "TRY")])
        self.assertEqual(urunler.fiyatlar("$1,299.90"), [(1299.9, "USD")])
        self.assertEqual(urunler.fiyatlar("12,50 €"), [(12.5, "EUR")])
        self.assertEqual(urunler.fiyatlar("6 x 216,65 TL"), [])  # taksit
        self.assertEqual(urunler.fiyatlar("aylık 99 TL"), [])
        self.assertEqual(urunler.fiyatlar("2024 yılında 15 model"), [])

    def test_suz_ve_bicim(self):
        liste, _ = urunler.cikar(KARTLAR, "")
        self.assertEqual([o["ad"] for o in urunler.suz(liste, "tefal fry")], ["Tefal Easy Fry"])
        self.assertEqual(urunler.tl(1299.9), "1.299,90")


class AracTesti(unittest.TestCase):
    def tarayici(self, html: str):
        from asistan import browser

        b = browser.Browser()
        b._call = lambda fn, timeout=120: (html, "https://magaza.test/fritoz")  # sayfa: DOM her çağrıda okunur
        return b

    def test_satirlar_json(self):
        metin = self.tarayici(KARTLAR).extract_items()
        satirlar = metin.splitlines()
        self.assertIn("3 ürün", satirlar[0])
        self.assertEqual(json.loads(satirlar[1])["fiyat"], 1299.9)

    def test_bulunamazsa_durust_hata(self):
        with self.assertRaises(AracHatasi) as h:
            self.tarayici(LISTESIZ).extract_items()
        self.assertIn("liste bulunamadı", str(h.exception))
        with self.assertRaises(AracHatasi):
            self.tarayici(KARTLAR).extract_items(find="bulaşık makinesi")

    def test_kayit_ve_tarayici_ajani(self):
        from asistan import browser
        from asistan.agent import build_tool_specs
        from asistan.categories import BROWSER_AGENT
        from asistan.registry import REGISTRY

        t = REGISTRY.get("browser_extract_items")
        self.assertEqual((t.group, t.risk), ("tarayici", "danisir"))
        with mock.patch.object(browser, "available", return_value=True):
            self.assertIn("browser_extract_items", {s["name"] for s in build_tool_specs(BROWSER_AGENT, [])})
            self.assertNotIn("browser_extract_items", {s["name"] for s in build_tool_specs(None, [])})
        self.assertIn("browser_extract_items", BROWSER_AGENT.prompt)

    def test_kayitli_profil_guncellenir(self):
        from asistan import profiles
        from asistan.categories import BROWSER_PROMPT_OLD, BROWSER_PROMPT_EXTRA
        from asistan.profiles import AgentProfile

        d = Path(tempfile.mkdtemp(dir=_GECICI))
        with mock.patch.object(profiles, "CONFIG_DIR", d), mock.patch.object(profiles, "PROFILES_FILE",
                                                                            d / "ajanlar.json"):
            (d / ".ajan-kategorileri").write_text("3")
            eski = AgentProfile(id="tarayici", name="Tarayıcı", prompt=BROWSER_PROMPT_OLD,
                                tools=["browser_open", "browser_read", "browser_click"])
            kendi = AgentProfile(id="tarayici", name="Tarayıcı", prompt="Benim talimatım",
                                 tools=["browser_open", "browser_read"])
            self.assertTrue(profiles._categorize([eski]))
            self.assertEqual(eski.tools, ["browser_open", "browser_read", "browser_extract_items", "browser_click"])
            self.assertEqual(eski.prompt, BROWSER_PROMPT_OLD + BROWSER_PROMPT_EXTRA)
            (d / ".ajan-kategorileri").write_text("3")
            profiles._categorize([kendi])
            self.assertEqual(kendi.prompt, "Benim talimatım")  # kullanıcının talimatına dokunulmaz
            self.assertIn("browser_extract_items", kendi.tools)
            self.assertEqual((d / ".ajan-kategorileri").read_text(), "4")


class YoneticiDenetimiTesti(unittest.TestCase):
    def test_fiyat_eksigi(self):
        from asistan.manager import fiyat_eksigi

        cevap3 = "1. Airfryer — 1.299,90 TL\n2. Easy Fry — 2.450 TL\n3. Mi Fritöz — 999 TL"
        self.assertEqual(fiyat_eksigi("Trendyol'da en ucuz 3 fritözü fiyatlarıyla listele", cevap3), "")
        self.assertIn("only 2", fiyat_eksigi("en ucuz 3 fritöz fiyatı", "\n".join(cevap3.splitlines()[:2])))
        self.assertIn("no line", fiyat_eksigi("hepsiburada'da airfryer fiyatlarına bak",
                                              "Sayfada ürün listesi bulunamadı."))
        self.assertEqual(fiyat_eksigi("haber sitesini aç ve manşeti oku", "Manşet: …"), "")  # fiyat isteği değil

    def test_fiyat_listesi_olmayan_istekler(self):
        """K5 denetimi: kelime içinde geçen parçalar ve işlem istekleri fiyat listesi sayılmaz (tekrar koşturulmaz)."""
        from asistan.manager import fiyat_eksigi, fiyat_listesi_mi

        for istek in ("AC Milan maçının skorunu oku", "şirketin bilançosunu özetle", "sahibinden.com'da ilan ver",
                      "trendyol'da bu ürünü sepete ekle, fiyatına bak", "ürün yorumlarını özetle",
                      "Hepsiburada'da en ucuz kabloyu satın al"):
            self.assertFalse(fiyat_listesi_mi(istek), istek)
            self.assertEqual(fiyat_eksigi(istek, "Tamam, yapıldı."), "", istek)
        self.assertTrue(fiyat_listesi_mi("Hepsiburada'da 'usb c kablo' ara, ilk 5 ürünün adını ve fiyatını yaz."))

    def test_sayi_model_adindan_alinmaz(self):
        from asistan.manager import fiyat_eksigi

        self.assertEqual(fiyat_eksigi("iPhone 15 ürün fiyatlarını listele", "1. iPhone 15 128 GB — 52.999 TL"), "")
        self.assertIn("only 1", fiyat_eksigi("en ucuz 3 iPhone 15 fiyatı", "1. iPhone 15 — 52.999 TL"))

    def test_cevap_araci_kanitindan(self):
        """Model yer tutucu yazdı ama araç sayfadan okudu: cevabı program o satırlardan yazar; satır azsa yazmaz."""
        from asistan import browser
        from asistan.manager import fiyat_eksigi, urun_cevabi

        b = browser.Browser()
        b._call = lambda fn, timeout=120: (KARTLAR, "https://magaza.test/fritoz")
        olay = {"name": "browser_extract_items", "args": {}, "result": b.extract_items(), "error": False}
        cevap = urun_cevabi("Mağazada fritöz ara, ilk 3 ürünün adını ve fiyatını yaz", [olay])
        self.assertIn("1. Philips Airfryer XXL 7.3 L — 1.299,90 TL — https://magaza.test/p/1", cevap)
        self.assertEqual(fiyat_eksigi("ilk 3 ürünün fiyatı", cevap), "")
        self.assertEqual(urun_cevabi("ilk 5 ürünün fiyatını yaz", [olay]), "")  # 3 satır var, 5 istendi: uydurma yok
        hata = {"name": "browser_extract_items", "args": {}, "result": "Error: liste bulunamadı", "error": True}
        self.assertEqual(urun_cevabi("ilk 3 ürünün fiyatı", [hata]), "")
        self.assertEqual(urun_cevabi("ilk 3 sonucun başlığını yaz", [olay]), "")  # fiyat isteği değil


if __name__ == "__main__":
    unittest.main()
