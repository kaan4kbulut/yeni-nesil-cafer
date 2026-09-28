"""K12-E — döngü / güncelleme / bulut düzeltmeleri (`NOTLAR/inceleme-k12-2026-09-28.md` E1–E10).

E1 görev eşitlemesinde saat kayması düzeltilir (sunucu damgayı kırpar, istemci kaymayı hesaplar) · E2 PWA kanalına
bilgisayar işinin sonucu döner · E3 tek dosya (PyInstaller) kurulumda güncelleyici kapalı · E4 geri alınan sürüm bir
daha önerilmez · E5 bozuk bulut.json yeni anahtar üretmez · E6 CLI ajanı iptali zincirde başka model denemez ·
E7 yeniden planlamada biten adımların sonucu `{{onceki_N.sonuc}}` ile bağlanır · E8 denetleyici model yoksa adım
ŞARTLI · E10 ntfy başlığı UTF-8.

Çalıştırma (proje kökünde): QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest testler/test_k12_e.py -q
"""

import base64
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
_GECICI = tempfile.mkdtemp(prefix="yeni-nesil-cafer-test-")
os.environ["XDG_CONFIG_HOME"] = str(Path(_GECICI) / "ayar")
os.environ["XDG_DATA_HOME"] = str(Path(_GECICI) / "veri")

from asistan import cloud_server, updates  # noqa: E402
from asistan.arayuz import web  # noqa: E402
from asistan.cekirdek import ayar, bildirim, uzak  # noqa: E402
from asistan.cekirdek.gorev import durum as durum_mod, planlayici, yurutucu  # noqa: E402
from asistan.cekirdek.saglayici import Iptal, cli_ajan  # noqa: E402
from asistan.manager import Manager  # noqa: E402

GERCEK = time.time


def gorev(gid: str, durum: str = "planlandi", istek: str = "iş") -> dict:
    return {"gorev_id": gid, "durum": durum, "istek": istek, "olusturma": "2026-09-28T13:00:00", "adimlar": [],
            "anlayis": {}, "rapor": ""}


class E1SaatKaymasi(unittest.TestCase):
    """Masaüstü saati sunucudan 120 sn ilerideyken sunucudaki onay masaüstüne gelmiyordu ("eski")."""

    def setUp(self):
        from fastapi.testclient import TestClient

        (ayar.DATA_DIR / "senkron.json").unlink(missing_ok=True)
        ayar.DATA_DIR.mkdir(parents=True, exist_ok=True)
        self.sunucu = durum_mod.Depo(Path(_GECICI) / f"srv-{time.time_ns()}.db")
        self.yerel = durum_mod.Depo(Path(_GECICI) / f"loc-{time.time_ns()}.db")
        app = web.uygulama("gizli", motor_kur=lambda **k: None, depo=self.sunucu)
        self.ic = uzak.Istemci("http://testserver", "gizli", http=TestClient(app))

    def test_ileri_saatli_masaustu_sunucudaki_onayi_alir(self):
        ileri = lambda: GERCEK() + 120  # noqa: E731  masaüstü saati
        kendisi = self

        class KaymaliIstemci:  # istek sunucuda gerçek saatle işlenir, masaüstü kodu ileri saatle koşar
            def istek(self, method, path, govde=None):
                with mock.patch.object(time, "time", GERCEK):
                    return kendisi.ic.istek(method, path, govde)

        with mock.patch.object(time, "time", ileri):
            self.yerel.kaydet(gorev("y1", "bekliyor_onay", "telefondan onaylanacak"))
            uzak.gorevleri_esitle(self.yerel, KaymaliIstemci())
        self.assertEqual(self.sunucu.getir("y1")["durum"], "bekliyor_onay")
        g = self.sunucu.getir("y1")
        g["durum"] = "calisiyor"  # telefondan onaylandı (sunucu saati)
        self.sunucu.kaydet(g)
        with mock.patch.object(time, "time", ileri):
            s = uzak.gorevleri_esitle(self.yerel, KaymaliIstemci())
        self.assertEqual(s["alinan"], 1)
        self.assertEqual(self.yerel.getir("y1")["durum"], "calisiyor")
        self.assertAlmostEqual(uzak.senkron_durumu().get("kayma", 0), -120, delta=5)


class E2PwaKanali(unittest.TestCase):
    def test_web_kanalina_sonuc_doner(self):
        dosya = Path(tempfile.mkdtemp()) / "bulut.json"
        with mock.patch.object(cloud_server, "CONFIG_FILE", dosya), \
                mock.patch.object(cloud_server, "DB_FILE", dosya.with_name("bulut.db")), \
                mock.patch.object(cloud_server, "_conn", None):
            job = cloud_server.add_job("dosyaları say", "bilgisayar gerekli", channel="web:web-123")
            cloud_server.update_job(job["id"], "bitti", "12 dosya var")
            son = cloud_server.history("web:web-123")
        self.assertTrue(son and "12 dosya" in son[-1]["content"], son)


class E3TekDosyaKurulum(unittest.TestCase):
    def test_frozen_kopyada_guncelleyici_kapali(self):
        with mock.patch.object(updates.sys, "frozen", True, create=True):
            acik, neden = updates.enabled()
        self.assertFalse(acik)
        self.assertIn("tek dosya", neden.lower())
        import main as ana

        state = Path(tempfile.mkdtemp()) / "guncelleme-durum.json"
        state.write_text(json.dumps({"from": "1", "to": "2", "backup": "/yok", "tries": 1}), encoding="utf-8")
        with mock.patch.object(ana.sys, "frozen", True, create=True):
            self.assertEqual(ana.rollback_if_needed(state, Path(tempfile.mkdtemp())), "")
        self.assertEqual(json.loads(state.read_text(encoding="utf-8"))["tries"], 1)  # dokunulmadı


class E4GeriAlinanSurumAtlanir(unittest.TestCase):
    def test_rollback_sonrasi_ayni_surum_onerilmez(self):
        import main as ana

        kok = Path(tempfile.mkdtemp())
        yedek = kok / "yedek"
        (yedek / "asistan").mkdir(parents=True)
        (yedek / "asistan" / "__init__.py").write_text('__version__ = "3.0"\n', encoding="utf-8")
        app = kok / "app"
        (app / "asistan").mkdir(parents=True)
        state = kok / "guncelleme-durum.json"
        state.write_text(json.dumps({"from": "3.0", "to": "3.1", "backup": str(yedek), "tries": 1, "clean_exit": False}),
                         encoding="utf-8")
        not_ = ana.rollback_if_needed(state, app)
        self.assertIn("geri dönüldü", not_)
        atla = state.with_name("guncelleme-atla.json")
        self.assertEqual(json.loads(atla.read_text(encoding="utf-8"))["version"], "3.1")
        with mock.patch.object(updates, "STATE_FILE", state), mock.patch.object(updates, "__version__", "3.0"):
            self.assertFalse(updates.newer({"version": "3.1"}))  # açılamayan sürüm bir daha önerilmez
            self.assertTrue(updates.newer({"version": "3.2"}))
            self.assertEqual(updates.atlanan_surum(), "3.1")


class E5BozukBulutJson(unittest.TestCase):
    def test_bozuk_dosya_yeni_anahtar_uretmez(self):
        dosya = Path(tempfile.mkdtemp()) / "bulut.json"
        with mock.patch.object(cloud_server, "CONFIG_FILE", dosya):
            ilk = cloud_server.load_config()["token"]
            self.assertEqual(cloud_server.load_config()["token"], ilk)
            dosya.write_text('{"token": "abc', encoding="utf-8")  # kesik
            with self.assertRaises(RuntimeError):
                cloud_server.load_config()
        self.assertEqual(dosya.read_text(encoding="utf-8"), '{"token": "abc')  # üstüne yazılmadı


class E6CliIptali(unittest.TestCase):
    def test_interrupted_iptal_olur(self):
        with mock.patch.object(cli_ajan.cli_agents, "is_cli", return_value=True), \
                mock.patch.object(cli_ajan.cli_agents, "AGENTS", {"cli:claude": SimpleNamespace(title="Claude Code")}), \
                mock.patch.object(cli_ajan.cli_agents, "run", side_effect=InterruptedError("durduruldu")):
            s = cli_ajan.CliAjanSaglayici("cli:claude")
            with self.assertRaises(Iptal):
                list(s.akis([{"role": "user", "content": "x"}]))


class E7YenidenPlanlama(unittest.TestCase):
    def test_onceki_yer_tutucu(self):
        self.assertEqual(yurutucu._kaydir({"a": "{{onceki_1.sonuc}} ve {{adim_1.sonuc}}"}, 2),
                         {"a": "{{adim_1.sonuc}} ve {{adim_3.sonuc}}"})
        veri = {"adimlar": [{"amac": "x", "yetenek": "dosya_oku", "girdi": {"yol": "{{onceki_2.sonuc}}"}, "bagimli": []}]}
        self.assertEqual(planlayici.ek_denetim(veri, [{"ad": "dosya_oku", "girdi_semasi": {}}]), [])
        veri = {"adimlar": [{"amac": "x", "yetenek": "dosya_oku", "girdi": {"yol": "{{adim_1.sonuc}}"}, "bagimli": []}]}
        self.assertTrue(planlayici.ek_denetim(veri, [{"ad": "dosya_oku", "girdi_semasi": {}}]))  # kendisine bakamaz
        g = {"adimlar": [{"id": 1, "sonuc": "birinci", "durum": "tamamlandi"}, {"id": 3, "girdi": {}}]}
        self.assertEqual(yurutucu.coz("{{adim_1.sonuc}}", g), "birinci")


class E8DenetciYoksaSartli(unittest.TestCase):
    def test_check_sartli(self):
        m = object.__new__(Manager)
        m.agent = SimpleNamespace(security_stop=False)
        m.plan = []
        rec = SimpleNamespace(events=[{"action": True, "error": False, "result": "ok", "name": "write_file", "args": {}}],
                              text="yaptım")
        with mock.patch.object(Manager, "_ask_json", return_value=None), mock.patch.object(Manager, "_files", return_value=""):
            ok, eksik = m.check("ollama", {"do": "yaz", "done_when": "dosya var"}, rec)
        self.assertTrue(ok)
        self.assertIn("ŞARTLI", eksik)
        self.assertTrue(m.sartli)


class E10NtfyBasligi(unittest.TestCase):
    def test_turkce_baslik_bozulmaz(self):
        gonderilen = []

        class Istemci:
            @staticmethod
            def post(url, **k):
                gonderilen.append(k)
                return SimpleNamespace(status_code=200)

        with mock.patch.object(bildirim.ayar, "deger", lambda ad, *a: {"bildirim.ntfy_konu": "cafer-abc-x7k2q9"}.get(ad, a[0] if a else None)), \
                mock.patch.object(bildirim, "_telegram", return_value={}):
            bildirim.gonder("Onay bekliyor — YENİ NESİL CAFER", "metin", istemci=Istemci)
        baslik = gonderilen[0]["headers"]["Title"]
        self.assertTrue(baslik.startswith("=?UTF-8?B?"), baslik)
        self.assertEqual(base64.b64decode(baslik[len("=?UTF-8?B?"):-2]).decode("utf-8"), "Onay bekliyor — YENİ NESİL CAFER")
        self.assertTrue(baslik.isascii())


if __name__ == "__main__":
    unittest.main()
