"""Bulut maliyet tavanı (BÖLÜM 2.4): sağlayıcının gerçek `usage` verisi sayılır, `yapisal.uret` her model çağrısında
harcama yazar, görev sayacı görev kimliğiyle tutulur (iş parçacığına bağlı değil), defter dosya kilidiyle yazılır,
`maliyet()` fiyat listesinden (ayar/modeller.json → fiyatlar) gerçek değer döner."""

import os
import sys
import tempfile
import threading
import unittest
from types import SimpleNamespace
from unittest import mock

KOK = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, KOK)
_GECICI = tempfile.mkdtemp(prefix="yeni-nesil-cafer-test-")
os.environ["XDG_CONFIG_HOME"] = os.path.join(_GECICI, "ayar")
os.environ["XDG_DATA_HOME"] = os.path.join(_GECICI, "veri")

from asistan.cekirdek import ayar, modeller, yapisal, yonlendirici as y  # noqa: E402
from asistan.cekirdek.saglayici import Yanit  # noqa: E402
from asistan.cekirdek.saglayici.claude import ClaudeSaglayici  # noqa: E402
from asistan.cekirdek.saglayici.openai_uyumlu import OpenAIUyumluSaglayici  # noqa: E402
from asistan.cekirdek.saglayici.temel import Saglayici  # noqa: E402


class Kullanim(unittest.TestCase):
    def test_claude_usage(self):
        s = ClaudeSaglayici(lambda: None, "m")
        usage = SimpleNamespace(input_tokens=100, output_tokens=20, cache_creation_input_tokens=30,
                                cache_read_input_tokens=5)
        self.assertEqual(s.kullanim(Yanit("", [], {"yanit": SimpleNamespace(usage=usage)})), (135, 20))
        self.assertEqual(s.kullanim(Yanit("", [], {})), (0, 0))

    def test_openai_usage(self):
        s = OpenAIUyumluSaglayici.__new__(OpenAIUyumluSaglayici)
        self.assertEqual(s.kullanim(Yanit("", [], {"usage": {"prompt_tokens": 40, "completion_tokens": 7}})), (40, 7))
        self.assertEqual(s.kullanim(Yanit("", [], {"usage": {}})), (0, 0))

    def test_maliyet_fiyat_listesinden(self):
        fiyatlar = {"pahali-model": [10.0, 50.0]}  # USD / 1M token (girdi, çıktı)
        with mock.patch.object(modeller, "deger", side_effect=lambda yol, v=None: fiyatlar if yol == "fiyatlar" else v):
            s = ClaudeSaglayici(lambda: None, "pahali-model")
            self.assertAlmostEqual(s.maliyet(1_000_000, 100_000), 15.0)
            self.assertIsNone(s.maliyet(10, 10, model="bilinmeyen"))
            self.assertEqual(Saglayici.maliyet(SimpleNamespace(ad="ollama"), 10, 10, "x"), 0.0)
            self.assertEqual(Saglayici.maliyet(SimpleNamespace(ad="cli:claude"), 10, 10, "x"), 0.0)

    def test_fiyat_listesi_dosyada(self):
        fiyatlar = modeller.deger("fiyatlar")
        self.assertTrue(fiyatlar)
        for model, deger in fiyatlar.items():
            if not model.startswith("_"):
                self.assertGreater(deger[1], deger[0], model)


class SahteUcretli:
    """OpenAI uyumlu gibi görünen sağlayıcı: her çağrı sabit usage döner; ilk cevap şemaya uymaz."""
    ad = "api:x"

    def __init__(self):
        self.cevaplar = ['{"yanlis": 1}', '{"ad": "tamam"}']

    def sohbet(self, mesajlar, sistem="", **_):
        return Yanit(self.cevaplar.pop(0), [], {"usage": {"prompt_tokens": 500, "completion_tokens": 50}})

    def kullanim(self, yanit):
        u = yanit.son["usage"]
        return u["prompt_tokens"], u["completion_tokens"]


class YapisalHarcama(unittest.TestCase):
    def test_her_cagrida_gercek_usage(self):
        sema = {"type": "object", "properties": {"ad": {"type": "string"}}, "required": ["ad"]}
        with mock.patch.object(y, "harcama_ekle") as h:
            sonuc = yapisal.uret(SahteUcretli(), [{"role": "user", "content": "x"}], sema, gorev_id="g7")
        self.assertEqual(sonuc.veri, {"ad": "tamam"})
        self.assertEqual(sonuc.deneme, 2)
        self.assertEqual(h.call_args_list, [mock.call("api:x", 550, gorev_id="g7"), mock.call("api:x", 550, gorev_id="g7")])


class GorevSayaci(unittest.TestCase):
    def setUp(self):
        yol = ayar.DATA_DIR / "bulut_harcama.json"
        if yol.exists():
            yol.unlink()
        y.gorev_basla()

    def test_gorev_kimligiyle_sayilir_is_parcacigina_bagli_degil(self):
        with mock.patch.dict(os.environ, {"CAFER_BULUT_GOREV_TAVAN_TOKEN": "1000"}):
            y.harcama_ekle("api:x", 800, gorev_id="g1")
            y.harcama_ekle("api:x", 300, gorev_id="g2")
            self.assertEqual((y.gorev_token("g1"), y.gorev_token("g2")), (800, 300))
            self.assertEqual(y.tavan_durumu("g1"), "")
            sonuc = {}

            def baska_is_parcacigi():
                y.harcama_ekle("api:x", 400, gorev_id="g1")  # Görevler penceresi kendi iş parçacığında
                sonuc["durum"] = y.tavan_durumu("g1")

            t = threading.Thread(target=baska_is_parcacigi)
            t.start()
            t.join()
            self.assertIn("görev tavanı", sonuc["durum"])
            self.assertIn("görev tavanı", y.tavan_durumu("g1"))
            self.assertEqual(y.tavan_durumu("g2"), "")
            y.tavan_onayla("g1")
            self.assertTrue(y.tavan_onaylandi("g1"))
            self.assertFalse(y.tavan_onaylandi("g2"))
            self.assertEqual(y.gunluk_token(), 1500)

    def test_kimliksiz_cagri_eski_gibi_bu_istegin_sayaci(self):
        y.gorev_basla()
        y.harcama_ekle("api:x", 5)
        self.assertEqual(y.gorev_token(), 5)
        y.gorev_basla()
        self.assertEqual(y.gorev_token(), 0)

    def test_defter_dosya_kilidiyle_yazilir(self):
        yollar = []
        orijinal = y._dosya_kilidi

        def izle(yol):
            yollar.append(yol)
            return orijinal(yol)

        with mock.patch.object(y, "_dosya_kilidi", izle):
            y.harcama_ekle("api:x", 1)
        self.assertEqual(len(yollar), 1)
        self.assertTrue(yollar[0].name.endswith(".lock"))
        self.assertEqual(y.gunluk_token(), 1)


if __name__ == "__main__":
    unittest.main()
