"""K9 — uzak mod ve senkron: `Depo.degisenler/ice_aktar` (son yazan kazanır, çakışma), `UzakDepo`/`UzakMotor` yerel
depoyla aynı çağrılar (parametrize), iki yönlü görev eşitleme (`/gorev/esitle`), bildirim (ntfy/Telegram; onay
bekleyince), `send_notification` aracı ve `bildirim_gonder` yeteneği."""

import json
import os
import sys
import tempfile
import time
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

KOK = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(KOK))
sys.path.insert(0, str(KOK / "testler"))
_GECICI = tempfile.mkdtemp(prefix="yeni-nesil-cafer-test-")
os.environ["XDG_CONFIG_HOME"] = str(Path(_GECICI) / "ayar")
os.environ["XDG_DATA_HOME"] = str(Path(_GECICI) / "veri")

from fastapi.testclient import TestClient  # noqa: E402

from asistan.arayuz import web  # noqa: E402
from asistan.cekirdek import ayar, bildirim, uzak  # noqa: E402
from asistan.cekirdek.gorev import durum as durum_mod  # noqa: E402
from test_web import SahteMotor  # noqa: E402

B = {"Authorization": "Bearer gizli"}


def gorev(gid, durum="planlandi", istek="x"):
    return {"gorev_id": gid, "istek": istek, "durum": durum, "olusturma": "t", "adimlar": [], "hatalar": [], "rapor": None}


class DepoSenkron(unittest.TestCase):
    def setUp(self):
        self.depo = durum_mod.Depo(Path(_GECICI) / f"s-{time.time_ns()}.db")

    def test_degisenler_ve_ice_aktar(self):
        self.depo.kaydet(gorev("a"), zaman=100.0)
        self.depo.kaydet(gorev("b"), zaman=200.0)
        self.assertEqual([g["gorev_id"] for g in self.depo.degisenler(150)], ["b"])
        self.assertEqual(self.depo.degisenler(150)[0]["_surum"], 200.0)
        # gelen daha eski: yazılmaz
        self.assertEqual(self.depo.ice_aktar(gorev("b", "tamamlandi"), 150.0, since=0), "eski")
        self.assertEqual(self.depo.getir("b")["durum"], "planlandi")
        # gelen daha yeni, yerel since'ten beri değişmemiş: yazılır, damga korunur
        self.assertEqual(self.depo.ice_aktar(gorev("b", "tamamlandi"), 300.0, since=250), "yazildi")
        self.assertEqual(self.depo.getir("b")["durum"], "tamamlandi")
        self.assertEqual(self.depo.getir("b")["_surum"], 300.0)
        # iki yanda da değişmiş: son yazan kazanır ama çakışma
        self.assertEqual(self.depo.ice_aktar(gorev("b", "iptal"), 400.0, since=250), "cakisma")
        self.assertEqual(self.depo.getir("b")["durum"], "iptal")
        self.assertEqual(self.depo.ice_aktar(gorev("yeni"), 50.0, since=0), "yazildi")


class YerelVeUzakAyni(unittest.TestCase):
    """Aynı senaryo yerel Depo/Yurutucu ve UzakDepo/UzakMotor (TestClient üzerinden) ile."""

    def _uzak(self):
        depo = durum_mod.Depo(Path(_GECICI) / f"u-{time.time_ns()}.db")
        app = web.uygulama("gizli", motor_kur=lambda gorev_id, istek, olay: SahteMotor(depo, gorev_id, olay), depo=depo)
        c = TestClient(app)
        i = uzak.Istemci("http://testserver", "gizli", http=c)
        return depo, uzak.UzakDepo(i), uzak.UzakMotor(i, bekle_sn=0.2)

    def test_parametrize(self):
        yerel_depo = durum_mod.Depo(Path(_GECICI) / f"y-{time.time_ns()}.db")
        yerel_motor = SahteMotor(yerel_depo, "", lambda *a: None)
        _, uzak_depo, uzak_motor = self._uzak()
        for ad, depo, motor in (("yerel", yerel_depo, yerel_motor), ("uzak", uzak_depo, uzak_motor)):
            with self.subTest(ad):
                g = motor.baslat("raporu yaz", gorev_id="g1")
                self.assertEqual(g["durum"], "bekliyor_onay")
                self.assertEqual([x["gorev_id"] for x in depo.yarim()], ["g1"])
                self.assertEqual(depo.getir("g1")["istek"], "raporu yaz")
                self.assertIsNone(depo.getir("yok"))
                g = motor.onayla("g1", True)
                self.assertEqual(g["durum"], "tamamlandi")
                self.assertEqual(depo.yarim(), [])
                motor.baslat("ikinci", gorev_id="g2")
                self.assertTrue(depo.iptal_et("g2"))
                self.assertEqual(depo.getir("g2")["durum"], "iptal")
                self.assertFalse(depo.iptal_et("g2"))
                self.assertEqual({x["gorev_id"] for x in depo.listele()}, {"g1", "g2"})

    def test_sunucudan_gelen_gorev_kaynakli(self):
        depo, uzak_depo, uzak_motor = self._uzak()
        uzak_motor.baslat("telefondan", gorev_id="t1")
        self.assertEqual(depo.getir("t1").get("_kaynak"), "sunucu")


class Esitleme(unittest.TestCase):
    def setUp(self):
        (ayar.DATA_DIR / "senkron.json").unlink(missing_ok=True)
        self.sunucu = durum_mod.Depo(Path(_GECICI) / f"srv-{time.time_ns()}.db")
        self.yerel = durum_mod.Depo(Path(_GECICI) / f"loc-{time.time_ns()}.db")
        app = web.uygulama("gizli", motor_kur=lambda **k: None, depo=self.sunucu)
        self.i = uzak.Istemci("http://testserver", "gizli", http=TestClient(app))

    def test_iki_yonlu_son_yazan_kazanir(self):
        self.yerel.kaydet(gorev("y1", istek="bilgisayarda çevrimdışı açıldı"), zaman=1000.0)
        self.sunucu.kaydet(gorev("s1", "bekliyor_onay", "telefondan"), zaman=1100.0)
        s = uzak.gorevleri_esitle(self.yerel, self.i)
        self.assertEqual((s["gonderilen"], s["alinan"], s["cakismalar"]), (1, 1, []))
        self.assertEqual(self.sunucu.getir("y1")["istek"], "bilgisayarda çevrimdışı açıldı")  # yerel kuyruk sunucuya
        self.assertEqual(self.yerel.getir("s1")["durum"], "bekliyor_onay")  # sunucudaki onay masaüstünde görünür
        d = uzak.senkron_durumu()
        self.assertGreater(d["son_yerel"], 0)
        # ikinci tur: değişiklik yok → hiçbir şey gitmez/gelmez
        s = uzak.gorevleri_esitle(self.yerel, self.i)
        self.assertEqual((s["gonderilen"], s["alinan"]), (0, 0))
        # çakışma: aynı görev iki yanda değişti; daha yeni damga kazanır, çakışma listeye düşer
        self.sunucu.kaydet(gorev("s1", "tamamlandi", "telefondan"), zaman=time.time() + 5)
        self.yerel.kaydet(gorev("s1", "iptal", "telefondan"))
        s = uzak.gorevleri_esitle(self.yerel, self.i)
        self.assertEqual(self.yerel.getir("s1")["durum"], "tamamlandi")
        self.assertEqual([c["gorev_id"] for c in s["cakismalar"]], ["s1"])
        self.assertEqual(uzak.senkron_durumu()["cakismalar"][-1]["gorev_id"], "s1")

    def test_ayarlardan(self):
        self.assertIsNone(uzak.ayarlardan(SimpleNamespace(extra={})))
        s = SimpleNamespace(extra={"cloud": {"url": "http://x", "token": "t"}})
        self.assertEqual(uzak.ayarlardan(s).url, "http://x")
        self.assertFalse(uzak.uzak_mod(s))
        s.extra["cloud"]["uzak_mod"] = True
        self.assertTrue(uzak.uzak_mod(s))
        s.extra["cloud"]["enabled"] = False
        self.assertFalse(uzak.uzak_mod(s))
        with mock.patch.object(uzak, "gorevleri_esitle", return_value={"gonderilen": 0, "alinan": 0, "cakismalar": []}):
            self.assertIsNone(uzak.esitle(SimpleNamespace(extra={})))
            self.assertEqual(uzak.esitle(SimpleNamespace(extra={"cloud": {"url": "http://x", "token": "t"}}), self.yerel)["alinan"], 0)


class Bildirim(unittest.TestCase):
    def test_ayarsiz_sessiz(self):
        with mock.patch.dict(os.environ, {"CAFER_BILDIRIM_NTFY_KONU": ""}), mock.patch.object(bildirim, "_telegram", return_value={}):
            self.assertFalse(bildirim.ayarli())
            self.assertIn("ayarlanmadı", bildirim.gonder("a", "b"))
            with mock.patch("threading.Thread") as t:
                bildirim.onay_bekliyor(gorev("g"))
            t.assert_not_called()

    def test_ntfy_ve_telegram(self):
        cagrilar = []

        def post(url, **k):
            cagrilar.append((url, k))
            return SimpleNamespace(status_code=200)

        with mock.patch.dict(os.environ, {"CAFER_BILDIRIM_NTFY_KONU": "cafer-abc"}), \
                mock.patch.object(bildirim, "_telegram", return_value={"token": "T", "chat": 5}):
            self.assertEqual(bildirim.kanallar(), ["ntfy", "telegram"])
            self.assertEqual(bildirim.gonder("Başlık", "metin", istemci=SimpleNamespace(post=post)), "ntfy ✓, telegram ✓")
        self.assertEqual(cagrilar[0][0], "https://ntfy.sh/cafer-abc")
        self.assertEqual(cagrilar[0][1]["content"], b"metin")
        self.assertEqual(cagrilar[1][1]["json"]["chat_id"], 5)
        self.assertIn("api.telegram.org/botT/", cagrilar[1][0])
        with mock.patch.dict(os.environ, {"CAFER_BILDIRIM_NTFY_KONU": "k"}), mock.patch.object(bildirim, "_telegram", return_value={}):
            def bozuk(url, **k):
                raise ConnectionError("yok")

            self.assertEqual(bildirim.gonder("a", "b", istemci=SimpleNamespace(post=bozuk)), "ntfy ✗ (ConnectionError)")

    def test_onay_bekleyince_bildirim(self):
        from test_gorev_motoru import ANLAYIS, TAMAM, UC_ADIM, GorevTabani, SahteModel, SahteYetenekler

        class T(GorevTabani):
            def runTest(self):
                pass

        t = T()
        t.setUp()
        plan = json.loads(json.dumps(UC_ADIM))
        plan["adimlar"].append({"amac": "yaz", "yetenek": "dosya_yaz", "girdi": {"yol": "a.txt", "icerik": "x"},
                                "basari_olcutu": "", "bagimli": [], "deneme_hakki": 0})
        m = SahteModel(analiz=[ANLAYIS], planlama=[plan], ozet=["ö"], siniflandirma=[TAMAM] * 4)
        with mock.patch.object(bildirim, "ayarli", return_value=True), mock.patch.object(bildirim, "arka_planda") as ap:
            g = t.motor(SahteYetenekler(), m).baslat("iş")
        self.assertEqual(g["durum"], "bekliyor_onay")
        ap.assert_called_once()
        self.assertIn("adım 4", ap.call_args.args[1])

    def test_arac_ve_yetenek(self):
        from asistan.cekirdek.yetenek.kayit import YERLESIK_KOK, Kayit
        from asistan.registry import REGISTRY
        from asistan.tools import Toolbox

        t = REGISTRY.get("send_notification")
        self.assertEqual(t.risk, "calistirir")  # internete gönderir: her seferinde onay
        self.assertTrue(hasattr(Toolbox, "_tool_send_notification"))
        y = Kayit([YERLESIK_KOK], kademe="dusuk").getir("bildirim_gonder")
        self.assertTrue(y and y.aktif, getattr(y, "neden", "yok"))
        self.assertEqual(y.risk(), "calistirir")


if __name__ == "__main__":
    unittest.main()
