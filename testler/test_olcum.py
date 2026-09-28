"""K7 — `cekirdek/analiz/olcum.py`: başarı oranı (doğrulayıcıdan), hız (profil benchmark), ilk ölçüm, kademe otomatik
düşürme/yükseltme (kilit varsa dokunmaz, bildirir), sınav → yönlendirme geri beslemesi; `modeller` kullanıcı katmanı."""

import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

KOK = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(KOK))
sys.path.insert(0, str(KOK / "testler"))
_GECICI = tempfile.mkdtemp(prefix="yeni-nesil-cafer-test-")
os.environ["XDG_CONFIG_HOME"] = str(Path(_GECICI) / "ayar")
os.environ["XDG_DATA_HOME"] = str(Path(_GECICI) / "veri")

from asistan.cekirdek import ayar, modeller, profil, yonlendirici as y  # noqa: E402
from asistan.cekirdek.analiz import olcum  # noqa: E402

YEREL = {"dusuk": "kucuk:2b", "orta": "orta:9b", "yuksek": "buyuk:12b"}


def _kademe_modelleri(k):
    return {"yerel": [YEREL[k]] if k in YEREL else [], "bulut": ["bulut-x"]}


def kayit(olculen="orta", benchmark=None, otomatik=None):
    k = {"olculen": olculen, "kilitli": None, "etkin": otomatik or olculen, "neden": "test"}
    if otomatik:
        k["otomatik"] = otomatik
    return {"kademe": k, "benchmark": benchmark or {}, "ram_gb": 16, "gpu": {"var": True, "vram_gb": 8}}


class Basari(unittest.TestCase):
    def setUp(self):
        (ayar.DATA_DIR / "olcum.json").unlink(missing_ok=True)

    def test_kaydet_ve_oran(self):
        self.assertEqual(olcum.basari_orani("ollama", "m"), (None, 0))
        olcum.basari_kaydet("ollama", "m", True, 1.5)
        olcum.basari_kaydet("ollama", "m", False, 0.5)
        olcum.basari_kaydet("ollama", "m", True, 1.0)
        oran, toplam = olcum.basari_orani("ollama", "m")
        self.assertAlmostEqual(oran, 2 / 3)
        self.assertEqual(toplam, 3)
        oz = olcum.model_ozeti("ollama", "m")
        self.assertEqual(oz["ort_sure_sn"], 1.0)
        olcum.basari_kaydet("", "m", True)  # sağlayıcısız kayıt yazılmaz
        self.assertEqual(olcum.basari_orani("ollama", "m")[1], 3)

    def test_yurutucu_model_adiminda_kaydeder(self):
        from test_gorev_motoru import ANLAYIS, TAMAM, UC_ADIM, GorevTabani, SahteModel, SahteYetenekler

        class T(GorevTabani):
            def runTest(self):
                pass

        t = T()
        t.setUp()
        m = SahteModel(analiz=[ANLAYIS], planlama=[UC_ADIM], ozet=["özet"], siniflandirma=[TAMAM] * 3)
        g = t.motor(SahteYetenekler(), m).baslat("iş")
        self.assertEqual(g["durum"], "tamamlandi")
        self.assertEqual(olcum.basari_orani("ollama", "sahte-ozet"), (1.0, 1))


class Hiz(unittest.TestCase):
    def test_hizlar_ve_ilk_olcum(self):
        with mock.patch.object(profil, "yukle", return_value=kayit(benchmark={"orta:9b": {"tok_sn": 12.5}, "x": {"atlandi": "y"}})), \
                mock.patch.object(modeller, "kademe_modelleri", side_effect=_kademe_modelleri), \
                mock.patch.object(profil, "kademe", return_value="orta"):
            self.assertEqual(olcum.hizlar(), {"orta:9b": 12.5})
            self.assertEqual(olcum.ilk_olcum_gerekli(), "")
            self.assertEqual(olcum.ilk_olcum_gerekli("yuksek"), "buyuk:12b")


class KademeAyari(unittest.TestCase):
    def setUp(self):
        p = mock.patch.object(modeller, "kademe_modelleri", side_effect=_kademe_modelleri)
        p.start()
        self.addCleanup(p.stop)

    def test_yavassa_dusurur_hizliysa_yukseltir(self):
        self.assertEqual(olcum.kademe_onerisi(kayit("orta", {"orta:9b": {"tok_sn": 2.1}}))[0], "dusuk")
        self.assertEqual(olcum.kademe_onerisi(kayit("yuksek", {"buyuk:12b": {"tok_sn": 1.0}}))[0], "orta")
        self.assertEqual(olcum.kademe_onerisi(kayit("orta", {"orta:9b": {"tok_sn": 20}, "buyuk:12b": {"tok_sn": 15, "kartta_yuzde": 100}}))[0], "yuksek")
        self.assertEqual(olcum.kademe_onerisi(kayit("orta", {"orta:9b": {"tok_sn": 20}, "buyuk:12b": {"tok_sn": 15, "kartta_yuzde": 60}}))[0], None)
        self.assertEqual(olcum.kademe_onerisi(kayit("orta", {"orta:9b": {"tok_sn": 20}}))[0], None)
        self.assertEqual(olcum.kademe_onerisi(kayit("dusuk", {"kucuk:2b": {"tok_sn": 1.0}}))[0], None)  # daha alt yok
        self.assertEqual(olcum.kademe_onerisi(kayit("orta"))[0], None)  # ölçüm yok

    def test_ayarla_yazar_bildirir_kilitliyse_dokunmaz(self):
        profil.kaydet(kayit("orta", {"orta:9b": {"tok_sn": 2.0}}))
        profil._onbellek_temizle()
        bildirimler = []
        with mock.patch.object(profil, "kilit", return_value=None):
            self.assertEqual(olcum.kademe_ayarla(bildirimler.append), "dusuk")
            self.assertEqual(profil.kademe(), "dusuk")  # etkin kademe kaydı
            k = profil.yukle()["kademe"]
            self.assertEqual((k["olculen"], k["otomatik"], k["etkin"]), ("orta", "dusuk", "dusuk"))
            self.assertIn("→ düşük", bildirimler[0])
            self.assertIsNone(olcum.kademe_ayarla(bildirimler.append))  # değişiklik yok: sessiz
            self.assertEqual(len(bildirimler), 1)
            # yeniden ölçüm otomatik ayarı korur
            with mock.patch.object(profil, "olc", return_value=profil._kademe_yaz(dict(kayit("orta")))):
                profil.guncelle()
            self.assertEqual(profil.yukle()["kademe"]["otomatik"], "dusuk")
            self.assertIn("hız ölçümüyle", profil.ozet(profil.yukle()))
            # model hızlanınca ölçülene döner
            p = profil.yukle()
            p["benchmark"]["orta:9b"]["tok_sn"] = 9
            profil.kaydet(p)
            self.assertIsNone(olcum.kademe_ayarla(bildirimler.append))
            self.assertNotIn("otomatik", profil.yukle()["kademe"])
            self.assertIn("ölçülen değere döndü", bildirimler[-1])
        profil.kaydet(kayit("orta", {"orta:9b": {"tok_sn": 2.0}}))
        with mock.patch.object(profil, "kilit", return_value="yuksek"):
            self.assertIsNone(olcum.kademe_ayarla())  # kilit: dokunma
            self.assertNotIn("otomatik", profil.yukle()["kademe"])

    def test_acilis_olcumu(self):
        profil.kaydet(kayit("orta"))
        profil._onbellek_temizle()
        with mock.patch.object(profil, "kilit", return_value=None), \
                mock.patch.object(profil, "benchmark", side_effect=lambda ms, url, **k: {}) as b:
            s = olcum.acilis("http://x")
        self.assertEqual(s["olculen"], "orta:9b")
        self.assertEqual(b.call_args.args[0], ["orta:9b"])


class SinavGeriBesleme(unittest.TestCase):
    def setUp(self):
        (ayar.DATA_DIR / "olcum.json").unlink(missing_ok=True)

    def test_tablo_ve_tercih(self):
        kayitlar = [{"tur": "ozet", "gecti": False}, {"tur": "ozet", "gecti": False}, {"tur": "ozet", "gecti": True},
                    {"tur": "cok_adimli", "gecti": True}, {"gecti": True}]
        self.assertEqual(olcum.sinav_geri_besle(kayitlar, "orta"), {"ozet": {"gecen": 1, "toplam": 3},
                                                                    "cok_adimli": {"gecen": 1, "toplam": 1}})
        self.assertEqual(olcum.tercih_rolu("orta", "ozet"), "yonetici")
        self.assertIsNone(olcum.tercih_rolu("orta", "cok_adimli"))  # zaten yönetici
        self.assertIsNone(olcum.tercih_rolu("yuksek", "ozet"))  # o kademede ölçüm yok
        self.assertIsNone(olcum.tercih_rolu("orta", "sohbet"))

    def test_yonlendirici_kullanir(self):
        olcum.sinav_geri_besle([{"tur": "ozet", "gecti": False}] * 3, "orta")
        KUCUK = y.Aday("ollama", "kucuk:4b", True, 12, 2, True, boyut_gb=3)
        BUYUK = y.Aday("ollama", "buyuk:12b", True, 20, 2, True, boyut_gb=8)
        d = y.Durum(kademe="orta", vram_gb=12)
        with mock.patch.object(y, "adaylar", return_value=[KUCUK, BUYUK]):
            s = y.sec(None, "ozet", durum_=d)
            self.assertEqual(s.model, "buyuk:12b")  # hızlı rol küçüğü seçerdi; sınav yönetici dedi
            self.assertIn("sınav", s.neden)
            self.assertEqual(y.sec(None, "ozet", durum_=y.Durum(kademe="yuksek", vram_gb=12)).model, "kucuk:4b")


class ModellerKatmani(unittest.TestCase):
    def setUp(self):
        modeller.ust_dosya().unlink(missing_ok=True)
        modeller.yenile()
        self.addCleanup(lambda: (modeller.ust_dosya().unlink(missing_ok=True), modeller.yenile()))

    def test_varsayilan_yap_ust_katmana_yazar(self):
        taban = json.loads(modeller.DOSYA.read_text(encoding="utf-8"))
        ikinci = taban["kademe"]["orta"]["yerel"][1]
        modeller.varsayilan_yap("orta", ikinci)
        self.assertEqual(modeller.kademe_modelleri("orta")["yerel"][0], ikinci)
        self.assertEqual(modeller.deger("varsayilan.ollama"), ikinci)
        self.assertEqual(modeller.kademe_modelleri("yuksek"), {"yerel": taban["kademe"]["yuksek"]["yerel"],
                                                               "bulut": taban["kademe"]["yuksek"]["bulut"]})
        self.assertEqual(json.loads(modeller.DOSYA.read_text(encoding="utf-8")), taban)  # programın dosyası değişmedi
        ust = json.loads(modeller.ust_dosya().read_text(encoding="utf-8"))
        self.assertEqual(set(ust), {"kademe", "varsayilan"})
        modeller.ust_yaz({"onerilen": {"yerel": ["a"], "bulut": ["b"]}, "aileler": {"x": 1}})
        self.assertEqual(modeller.deger("onerilen.yerel"), ["a"])
        self.assertIsNone(modeller.deger("aileler.x"))  # yalnızca izinli anahtarlar
        with self.assertRaises(ValueError):
            modeller.varsayilan_yap("yok", "m")


if __name__ == "__main__":
    unittest.main()
