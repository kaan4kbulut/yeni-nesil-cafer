"""K12-F — düşük öncelikli düzeltmeler (`NOTLAR/inceleme-k12-2026-09-28.md` F1–F10).

F1 web olay/motor önbelleği sınırlı · F2 güncelleme geçici klasörü silinir · F3 sw.js önbellek adı sürümlü · F6 günlük
kırpması kilitli · F7 aynı görev için ikinci onay/devam 409 · F8 ASISTAN.md toplam 4000 karakter · F9 web kaynaklı görevde
CLI ajanı yok · F10 ■ sonrası araç çağrısı onay penceresi açmaz.

Çalıştırma (proje kökünde): QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest testler/test_k12_f.py -q
"""

import os
import sys
import tempfile
import threading
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

from asistan import __version__, agent as agent_mod, problem_report, updates  # noqa: E402
from asistan.agent import Agent, Cancelled  # noqa: E402
from asistan.arayuz import web  # noqa: E402
from asistan.cekirdek import yonlendirici  # noqa: E402
from asistan.cekirdek.gorev import durum as durum_mod  # noqa: E402
from asistan.config import Settings  # noqa: E402


class F1OlaylarSinirli(unittest.TestCase):
    def test_en_cok_200_gorev(self):
        o = web._Olaylar()
        for i in range(260):
            o("plan", {"gorev": {"gorev_id": f"g{i}"}})
        self.assertLessEqual(len(o.son), web.EN_COK_GOREV)
        self.assertIn("g259", o.son)
        self.assertNotIn("g0", o.son)


class F2GeciciKlasor(unittest.TestCase):
    def test_indirme_klasoru_temizlenir(self):
        d = Path(tempfile.mkdtemp(prefix="yeni-nesil-cafer-guncelleme-"))
        paket = d / "x.zip"
        paket.write_bytes(b"x")
        updates._gecici_temizle(paket)
        self.assertFalse(d.exists())
        baska = Path(tempfile.mkdtemp()) / "y.zip"
        baska.write_bytes(b"y")
        updates._gecici_temizle(baska)  # bilinmeyen klasöre dokunulmaz
        self.assertTrue(baska.exists())


class F3F7Web(unittest.TestCase):
    def setUp(self):
        from fastapi.testclient import TestClient

        self.depo = durum_mod.Depo(Path(_GECICI) / f"f-{time.time_ns()}.db")
        self.depo.kaydet({"gorev_id": "t1", "durum": "bekliyor_onay", "istek": "x", "adimlar": [], "anlayis": {},
                          "olusturma": "2026-09-28"})
        self.bekle = threading.Event()

        class Motor:
            def onayla(m, gid, evet=True):
                self.bekle.wait(3)

            def devam(m, gid):
                self.bekle.wait(3)

        app = web.uygulama("gizli", motor_kur=lambda **k: Motor(), depo=self.depo)
        self.c = TestClient(app)
        self.h = {"Authorization": "Bearer gizli"}

    def tearDown(self):
        self.bekle.set()

    def test_sw_js_surumlu(self):
        r = self.c.get("/sw.js")
        self.assertEqual(r.status_code, 200)
        self.assertIn(f'"cafer-kabuk-{__version__}"', r.text)
        self.assertNotIn("cafer-kabuk-v1", r.text)

    def test_ayni_gorev_ikinci_istek_409(self):
        self.assertEqual(self.c.post("/gorev/t1/onayla", json={"evet": True}, headers=self.h).status_code, 200)
        self.assertEqual(self.c.post("/gorev/t1/devam", headers=self.h).status_code, 409)
        self.assertEqual(self.c.post("/gorev/t1/onayla", json={"evet": True}, headers=self.h).status_code, 409)
        self.bekle.set()
        time.sleep(0.2)
        self.assertEqual(self.c.post("/gorev/t1/devam", headers=self.h).status_code, 200)


class F6GunlukKilidi(unittest.TestCase):
    def test_es_zamanli_yazim_satir_kaybetmez(self):
        dosya = Path(tempfile.mkdtemp()) / "gunluk.log"
        with mock.patch.object(problem_report, "LOG_FILE", dosya), mock.patch.object(problem_report, "LOG_LIMIT", 2000):
            def yaz(n):
                for i in range(120):
                    problem_report.log_line(f"is{n}-{i}")

            ts = [threading.Thread(target=yaz, args=(n,)) for n in range(4)]
            [t.start() for t in ts]
            [t.join() for t in ts]
        self.assertTrue(problem_report._log_kilit)
        satirlar = dosya.read_text(encoding="utf-8").splitlines()
        self.assertTrue(all(" is" in s for s in satirlar if s.strip()), satirlar[:3])  # kırpma satır ortasından kesmez


class F8AsistanMdButcesi(unittest.TestCase):
    def test_toplam_4000(self):
        kok = Path(tempfile.mkdtemp())
        alt = kok / "kategori" / "is-1"
        alt.mkdir(parents=True)
        for d in (kok, kok / "kategori", alt):
            (d / agent_mod.INSTRUCTIONS_FILE).write_text("x" * 3000, encoding="utf-8")
        metin = agent_mod.instruction_files(str(alt), str(kok))
        self.assertLessEqual(metin.count("x"), agent_mod.INSTRUCTIONS_LIMIT)
        self.assertEqual(metin.count("### "), 2)  # bütçe bitince kalan dosya alınmaz


class F9WebKaynagi(unittest.TestCase):
    def test_web_kaynakli_gorevde_cli_yok(self):
        s = SimpleNamespace(extra={yonlendirici.EXTRA_KAYNAK: "web"})
        self.assertFalse(yonlendirici.kullanici_istegi(s))
        self.assertTrue(yonlendirici.kullanici_istegi(SimpleNamespace(extra={yonlendirici.EXTRA_KAYNAK: "sohbet"})))


class F10IptalSonrasiOnayYok(unittest.TestCase):
    def test_durdurulunca_onay_penceresi_acilmaz(self):
        soruldu = []
        cb = SimpleNamespace(on_tool_start=lambda *a: None, on_tool_end=lambda *a: None,
                             ask_approval=lambda n, a: soruldu.append(n) or True, is_cancelled=lambda: True)
        a = Agent(Settings(workspace=str(Path(_GECICI) / "is"), approval_mode="kullanici"), cb)
        a._provider = "ollama"
        with self.assertRaises(Cancelled):
            a._execute_tool("1", "run_command", {"command": "rm eski.txt", "purpose": ""})
        self.assertEqual(soruldu, [])


if __name__ == "__main__":
    unittest.main()
