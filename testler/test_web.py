"""K8 — web yüzü (`arayuz/web`): uç noktalar (TestClient), token (401), SSE akışı, PWA dosyaları, onaylar listesi,
eski bulut API'si aynı uygulamada; çekirdek + web PySide6 yüklemez (ayrı süreç)."""

import json
import os
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path

KOK = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(KOK))
_GECICI = tempfile.mkdtemp(prefix="yeni-nesil-cafer-test-")
os.environ["XDG_CONFIG_HOME"] = str(Path(_GECICI) / "ayar")
os.environ["XDG_DATA_HOME"] = str(Path(_GECICI) / "veri")

from fastapi.testclient import TestClient  # noqa: E402

from asistan.arayuz import web  # noqa: E402
from asistan.cekirdek.gorev import durum as durum_mod  # noqa: E402

B = {"Authorization": "Bearer gizli"}


class SahteMotor:
    """Görev motoru yerine: baslat → planlandi + bir adım onay bekler; onayla(True) → tamamlandi."""

    def __init__(self, depo, gorev_id, olay):
        self.depo, self.gorev_id, self.olay = depo, gorev_id, olay

    def baslat(self, istek, gorev_id=""):
        g = {"gorev_id": gorev_id or self.gorev_id, "istek": istek, "durum": "bekliyor_onay", "olusturma": "t",
             "adimlar": [{"id": 1, "amac": "dosya yaz", "yetenek": "dosya_yaz", "durum": "bekliyor_onay",
                          "bekleyen": {"tip": "kur", "hedef": "pip:docx"}}], "hatalar": [], "rapor": None}
        self.depo.kaydet(g)
        self.olay("onay", {"gorev": g, "adim": g["adimlar"][0]})
        return g

    def onayla(self, gorev_id, evet=True):
        g = self.depo.getir(gorev_id)
        g["durum"] = "tamamlandi" if evet else "iptal"
        g["adimlar"][0]["durum"] = g["durum"]
        g["rapor"] = "Tamamlandı" if evet else "reddedildi"
        self.depo.kaydet(g)
        return g

    def yanitla(self, gorev_id, cevap):
        return self.onayla(gorev_id, True)

    def devam(self, gorev_id):
        return self.depo.getir(gorev_id)


def sahte_sohbet(metin, sohbet_id, olay):
    olay({"tur": "arac", "ad": "web_search"})
    for parca in ("Merhaba ", sohbet_id or "", " — ", metin[::-1]):
        olay({"tur": "metin", "metin": parca})


class WebTesti(unittest.TestCase):
    def setUp(self):
        self.depo = durum_mod.Depo(Path(_GECICI) / f"web-{time.time_ns()}.db")
        self.app = web.uygulama("gizli", motor_kur=lambda gorev_id, istek, olay: SahteMotor(self.depo, gorev_id, olay),
                                sohbet_calistir=sahte_sohbet, depo=self.depo)
        self.c = TestClient(self.app)

    def _bekle(self, gid, durum, sn=5):
        for _ in range(int(sn * 20)):
            g = self.c.get(f"/gorev/{gid}", headers=B).json()
            if g.get("durum") == durum:
                return g
            time.sleep(0.05)
        raise AssertionError(f"{gid} {durum} olmadı")

    def test_saglik_ve_pwa_anahtarsiz(self):
        s = self.c.get("/saglik").json()
        self.assertEqual(s["durum"], "ok")
        self.assertIn(s["kademe"], ("dusuk", "orta", "yuksek", "sunucu"))
        self.assertIn("masaustu_yuklu", s)  # aynı süreçte başka testler Qt yükler; ayrı süreç denetimi MasaustuYuklenmez
        html = self.c.get("/").text
        self.assertIn("manifest.webmanifest", html)
        self.assertIn("sw.js", html)
        self.assertEqual(self.c.get("/manifest.webmanifest").json()["display"], "standalone")
        self.assertIn("caches", self.c.get("/sw.js").text)
        self.assertEqual(self.c.get("/api/health").json()["ok"], True)

    def test_token(self):
        for yol in ("/gorev", "/onaylar", "/yetenekler", "/profil", "/api/queue"):
            self.assertEqual(self.c.get(yol).status_code, 401, yol)
            self.assertEqual(self.c.get(yol, headers={"Authorization": "Bearer yanlis"}).status_code, 401, yol)
        self.assertEqual(self.c.post("/gorev", json={"istek": "x"}).status_code, 401)
        self.assertEqual(self.c.post("/sohbet", json={"metin": "x"}).status_code, 401)
        self.assertEqual(self.c.get("/onaylar", headers=B).status_code, 200)

    def test_gorev_onay_akisi(self):
        r = self.c.post("/gorev", json={"istek": "raporu yaz"}, headers=B)
        self.assertEqual(r.status_code, 202)
        gid = r.json()["gorev_id"]
        g = self._bekle(gid, "bekliyor_onay")
        self.assertEqual(g["olaylar"][-1]["tur"], "onay")
        o = self.c.get("/onaylar", headers=B).json()["onaylar"]
        self.assertEqual([x["gorev_id"] for x in o], [gid])
        self.assertEqual(o[0]["ne"], "kurulum: pip:docx")
        self.assertEqual(self.c.get("/gorev", headers=B).json()["gorevler"][0]["durum"], "bekliyor_onay")
        self.c.post(f"/gorev/{gid}/onayla", json={"evet": True}, headers=B)
        self.assertEqual(self._bekle(gid, "tamamlandi")["rapor"], "Tamamlandı")
        self.assertEqual(self.c.get("/onaylar", headers=B).json()["onaylar"], [])
        self.assertEqual(self.c.get("/gorev/yok", headers=B).status_code, 404)
        self.assertEqual(self.c.post("/gorev", json={"istek": ""}, headers=B).status_code, 400)

    def test_sohbet_sse(self):
        with self.c.stream("POST", "/sohbet", json={"metin": "abc", "sohbet_id": "s1"}, headers=B) as r:
            self.assertEqual(r.status_code, 200)
            self.assertTrue(r.headers["content-type"].startswith("text/event-stream"))
            govde = b"".join(r.iter_bytes()).decode("utf-8")
        olaylar = [json.loads(s[5:]) for s in govde.split("\n\n") if s.startswith("data:")]
        self.assertEqual(olaylar[0], {"tur": "arac", "ad": "web_search"})
        self.assertEqual("".join(o["metin"] for o in olaylar if o["tur"] == "metin"), "Merhaba s1 — cba")
        self.assertEqual(olaylar[-1], {"tur": "bitti"})

    def test_yetenekler_ve_profil(self):
        y = self.c.get("/yetenekler", headers=B).json()["yetenekler"]
        self.assertIn("dosya_oku", {x["ad"] for x in y})
        self.assertIn("kademe_etkin", self.c.get("/profil", headers=B).json())

    def test_eski_bulut_apisi_ayni_uygulamada(self):
        from asistan import cloud_server

        cloud_server.reset_for_tests(Path(_GECICI) / "bulut")
        job = cloud_server.add_job("PDF'leri listele", "yerel", "web")
        self.assertEqual([j["id"] for j in self.c.get("/api/queue?status=bekliyor", headers=B).json()["jobs"]], [job["id"]])
        self.assertEqual(self.c.post(f"/api/queue/{job['id']}", json={"status": "bitti", "result": "ok"}, headers=B).status_code, 200)
        self.assertEqual(self.c.post("/api/queue/yok", json={"status": "bitti"}, headers=B).status_code, 404)
        s = self.c.post("/api/sync", json={"since": 0, "changes": {"items": [], "deleted": []}}, headers=B).json()
        self.assertIn("now", s)

    def test_anahtar_ortamdan(self):
        with unittest.mock.patch.dict(os.environ, {"CAFER_TOKEN": "ortam-anahtari"}):
            self.assertEqual(web.anahtar_bul(), "ortam-anahtari")


class MasaustuYuklenmez(unittest.TestCase):
    def test_web_ice_aktarinca_pyside_yok(self):
        python = str(KOK / ".venv" / "bin" / "python") if (KOK / ".venv" / "bin" / "python").is_file() else sys.executable
        kod = ("import sys\nfrom asistan.arayuz import web\napp = web.uygulama('t')\n"
               "print('PySide6' in sys.modules, 'asistan.gui' in sys.modules, len(app.routes) > 10)\n")
        s = subprocess.run([python, "-c", kod], cwd=KOK, capture_output=True, text=True, timeout=120,
                           env=dict(os.environ, XDG_CONFIG_HOME=str(Path(_GECICI) / "a2"), XDG_DATA_HOME=str(Path(_GECICI) / "v2")))
        self.assertEqual(s.returncode, 0, s.stderr[-1500:])
        self.assertEqual(s.stdout.strip(), "False False True")


import unittest.mock  # noqa: E402

if __name__ == "__main__":
    unittest.main()
