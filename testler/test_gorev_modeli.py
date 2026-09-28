"""Görev motorunun model çağrısı (`gorev/model.py`) yedekleme zincirini `yonlendirici.Zincir` ile yürütür (MIMARI §4.5):
aynı modelde 2 başarısızlık → sıradaki; ulaşılamayan sağlayıcı (bağlantı, zaman aşımı, 401) → hemen sıradaki;
`Iptal` zinciri ilerletmez, yeniden fırlatılır; şema hatası zincir başarısızlığı değildir."""

import os
import sys
import tempfile
import unittest
from types import SimpleNamespace
from unittest import mock

import httpx

KOK = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, KOK)
_GECICI = tempfile.mkdtemp(prefix="yeni-nesil-cafer-test-")
os.environ["XDG_CONFIG_HOME"] = os.path.join(_GECICI, "ayar")
os.environ["XDG_DATA_HOME"] = os.path.join(_GECICI, "veri")

from asistan.cekirdek import yonlendirici  # noqa: E402
from asistan.cekirdek.gorev import ModelYok, model as model_mod  # noqa: E402
from asistan.cekirdek.saglayici import Iptal  # noqa: E402

A, B, C = ("ollama", "kucuk"), ("ollama", "buyuk"), ("api:x", "bulut")


class ZincirTesti(unittest.TestCase):
    def test_atla_ve_ekle(self):
        z = yonlendirici.Zincir([A, B])
        z.basarisiz("bir")
        z.atla("tavan")  # sayılmaz: basamak kullanılamıyor
        self.assertEqual(z.su_an, B)
        self.assertEqual(z.sayac, 0)
        z.ekle([C, B])  # B zaten var
        self.assertEqual(z.sira, [A, B, C])
        self.assertIn("tavan", z.gecmis[-1])


class ModelZinciri(unittest.TestCase):
    def setUp(self):
        yonlendirici.gorev_basla()
        self.cagrilar: list = []
        self.hatalar: dict = {}
        karar = yonlendirici.Secim(*A, "test", "ozet", zincir=[B, C])

        def bul(ad, *_):
            def sohbet(m, s, model, **_k):
                self.cagrilar.append((ad, model))
                sira = self.hatalar.get((ad, model)) or []
                if sira:
                    raise sira.pop(0)
                return SimpleNamespace(metin="tamam", son={})

            return SimpleNamespace(sohbet=sohbet, ad=ad, kullanim=lambda y: (0, 0))

        yamalar = [mock.patch.object(yonlendirici, "sec", return_value=karar),
                   mock.patch.object(yonlendirici, "harcama_ekle"),
                   mock.patch.object(yonlendirici.SAGLIK, "bildir"),
                   mock.patch("asistan.cekirdek.saglayici.bul", side_effect=bul)]
        for y in yamalar:
            y.start()
            self.addCleanup(y.stop)
        self.model = model_mod.YonlendiriciModeli(SimpleNamespace(ollama_num_ctx=4096, extra={}), [])

    def test_bir_hata_ayni_model_tekrar(self):
        self.hatalar[A] = [RuntimeError("500 sunucu")]
        c = self.model("ozet", [{"role": "user", "content": "x"}])
        self.assertEqual(self.cagrilar, [A, A])
        self.assertEqual(c.secim["model"], "kucuk")

    def test_iki_hata_siradaki_model(self):
        self.hatalar[A] = [RuntimeError("1"), RuntimeError("2")]
        c = self.model("ozet", [{"role": "user", "content": "x"}])
        self.assertEqual(self.cagrilar, [A, A, B])
        self.assertEqual(c.secim["model"], "buyuk")
        self.assertIn("yedek", c.secim["neden"])

    def test_ulasilamayan_saglayici_hemen_siradaki(self):
        self.hatalar[A] = [httpx.ConnectError("yok")]
        self.model("ozet", [{"role": "user", "content": "x"}])
        self.assertEqual(self.cagrilar, [A, B])
        yonlendirici.SAGLIK.bildir.assert_called_once()

    def test_iptal_yeniden_firlatilir_zincir_ilerlemez(self):
        self.hatalar[A] = [Iptal()]
        with self.assertRaises(Iptal):
            self.model("ozet", [{"role": "user", "content": "x"}])
        self.assertEqual(self.cagrilar, [A])

    def test_zincir_bitince_model_yok(self):
        for k in (A, B, C):
            self.hatalar[k] = [RuntimeError("a"), RuntimeError("b")]
        with self.assertRaises(ModelYok):
            self.model("ozet", [{"role": "user", "content": "x"}])
        self.assertEqual(len(self.cagrilar), 6)

    def test_sema_hatasi_zinciri_ilerletmez(self):
        # şemaya uymayan cevap: yapisal.uret hatalarla döner; bu "model olmadı" değildir, çağıran karar verir
        with mock.patch.object(model_mod.yapisal, "uret",
                               return_value=SimpleNamespace(ham="{}", veri=None, hatalar=["eksik"], deneme=2)):
            c = self.model("planlama", [{"role": "user", "content": "x"}], sema={"type": "object"})
        self.assertIsNone(c.veri)
        self.assertEqual(c.hatalar, ["eksik"])
        self.assertEqual(c.secim["model"], "kucuk")


if __name__ == "__main__":
    unittest.main()
