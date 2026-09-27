"""Bulut beyin (Aşama 6) testleri: gerçek HTTP sunucusu (süreç içinde), iki ayrı hafıza arasında eşitleme,
iş kuyruğu, Telegram eşleşmesi ve yetki. Model çağrılmaz (answer sahte)."""

import json
import os
import sys
import tempfile
import threading
import unittest
from pathlib import Path
from unittest import mock

import httpx

KOK = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(KOK))
_GECICI = tempfile.mkdtemp(prefix="yeni-nesil-cafer-test-")
os.environ["XDG_CONFIG_HOME"] = str(Path(_GECICI) / "ayar")
os.environ["XDG_DATA_HOME"] = str(Path(_GECICI) / "veri")

from asistan import cloud_server, cloud_sync, memory_db  # noqa: E402


class _Sunucu(unittest.TestCase):
    def setUp(self):
        base = Path(tempfile.mkdtemp(dir=_GECICI))
        self.server_dir, self.local_db = base / "sunucu", base / "yerel.db"
        self.server_dir.mkdir()
        cloud_server.reset_for_tests(self.server_dir)
        cloud_server.save_config({"token": "gizli", "pair_code": "424242", "host": "127.0.0.1", "port": 0,
                                  "model": "x", "telegram_token": "", "telegram_chat": 0})
        self.httpd = cloud_server.make_server()
        threading.Thread(target=self.httpd.serve_forever, daemon=True).start()
        self.addCleanup(self.httpd.server_close)
        self.addCleanup(self.httpd.shutdown)
        self.url = f"http://127.0.0.1:{self.httpd.server_address[1]}"
        self.settings = mock.Mock(extra={"cloud": {"url": self.url, "token": "gizli", "enabled": True}})
        p = mock.patch.object(memory_db, "embedding_available", return_value=False)
        p.start()
        self.addCleanup(p.stop)

    def _as_server(self):
        memory_db.reset_for_tests(self.server_dir / "hafiza.db")

    def _as_local(self):
        memory_db.reset_for_tests(self.local_db)


class Yetki(_Sunucu):
    def test_anahtarsiz_ve_yanlis_anahtar_reddedilir(self):
        self.assertEqual(httpx.get(self.url + "/api/queue").status_code, 401)
        self.assertEqual(httpx.get(self.url + "/api/queue", headers={"Authorization": "Bearer x"}).status_code, 401)
        self.assertEqual(httpx.get(self.url + "/").status_code, 200)  # web sayfası açılır, veri anahtarla
        self.assertEqual(cloud_sync.check(self.settings), "bağlantı tamam")
        bad = mock.Mock(extra={"cloud": {"url": self.url, "token": "yanlis"}})
        with self.assertRaises(cloud_sync.CloudError):
            cloud_sync.check(bad)


class Esitleme(_Sunucu):
    def test_iki_yonlu_ekleme_ve_silme(self):
        # sunucuda (bulut asistan) öğrenilen bir bilgi
        self._as_server()
        server_item = memory_db.put("bilgi", "Telefonda kısa cevap isterim")
        # bilgisayarda öğrenilen bir tercih
        self._as_local()
        local_item = memory_db.put("tercih", "Raporlar Excel olsun")
        # eşitleme: istemci yerel DB ile, sunucu (HTTP içinde) kendi DB'siyle çalışır — süreç içinde tek DB
        # bağlantısı olduğu için sunucu tarafını istek sırasında değiştiriyoruz
        with mock.patch.object(cloud_server.Handler, "do_POST", _swap_db(self, cloud_server.Handler.do_POST)):
            sent, got = cloud_sync.sync(self.settings)
        self.assertEqual((sent, got), (1, 1))
        self.assertEqual({i["text"] for i in memory_db.items()}, {"Telefonda kısa cevap isterim", "Raporlar Excel olsun"})
        # bilgisayarda silinen kayıt sunucuda da silinir
        memory_db.delete(server_item["id"])
        with mock.patch.object(cloud_server.Handler, "do_POST", _swap_db(self, cloud_server.Handler.do_POST)):
            cloud_sync.sync(self.settings)
        self._as_server()
        self.assertEqual([i["id"] for i in memory_db.items()], [local_item["id"]])


def _swap_db(test, original):
    def handler(self_):
        test._as_server()
        try:
            return original(self_)
        finally:
            test._as_local()
    return handler


class Kuyruk(_Sunucu):
    def test_is_birakilir_bitince_kanala_iletilir(self):
        job = cloud_server.add_job("Masaüstündeki fotoğrafları tarihe göre ayır", "yerel dosya", "web")
        pending = cloud_sync.pending_jobs(self.settings)
        self.assertEqual([j["id"] for j in pending], [job["id"]])
        cloud_sync.finish_job(self.settings, job["id"], "bitti", "42 fotoğraf 5 klasöre ayrıldı")
        self.assertEqual(cloud_sync.pending_jobs(self.settings), [])
        web = cloud_server.history("web")
        self.assertIn("42 fotoğraf", web[-1]["content"])  # sonuç web sohbetine düştü

    def test_kuyruk_araci_kanali_bilir(self):
        cloud_server._local.channel = "telegram:77"
        try:
            text = cloud_server._queue_runner({"task": "PDF'leri listele", "reason": "yerel"})
        finally:
            cloud_server._local.channel = ""
        self.assertIn("QUEUED", text)
        self.assertEqual(cloud_server.jobs("bekliyor")[0]["channel"], "telegram:77")


class Telegram(_Sunucu):
    def _msg(self, chat, text):
        return {"update_id": 1, "message": {"chat": {"id": chat}, "text": text}}

    def test_eslesme_ve_yabancilar(self):
        conf = cloud_server.load_config()
        self.assertIsNone(cloud_server.handle_telegram(conf, self._msg(5, "merhaba")))  # eşleşmemiş: sessiz
        self.assertIsNone(cloud_server.handle_telegram(conf, self._msg(5, "/baglan 000000")))  # yanlış kod
        self.assertIn("Eşleşti", cloud_server.handle_telegram(conf, self._msg(5, "/baglan 424242")))
        self.assertEqual(cloud_server.load_config()["telegram_chat"], 5)
        self.assertIsNone(cloud_server.handle_telegram(conf, self._msg(9, "/baglan 424242")))  # başkası: sessiz
        with mock.patch.object(cloud_server, "answer", return_value="selam") as ans:
            self.assertEqual(cloud_server.handle_telegram(conf, self._msg(5, "nasılsın")), "selam")
        ans.assert_called_once()
        self.assertEqual(ans.call_args.args[0], "telegram:5")
        self.assertEqual(cloud_server.handle_telegram(conf, self._msg(5, "/isler")), "Bekleyen iş yok.")


class WebSohbet(_Sunucu):
    def test_sohbet_uc_noktasi(self):
        with mock.patch.object(cloud_server, "answer", return_value="Merhaba!") as ans:
            r = httpx.post(self.url + "/api/chat", json={"text": "selam"}, headers={"Authorization": "Bearer gizli"},
                           timeout=10)
        self.assertEqual(r.json(), {"reply": "Merhaba!"})
        self.assertEqual(ans.call_args.args[:2], ("web", "selam"))

    def test_answer_masaustuyle_ayni_yoldan(self):
        # answer → istek.calistir → Manager.run (model çağrılmaz); bulut notu, araç süzgeci ve geçmiş korunur
        from asistan import manager

        def sahte(yonetici, saglayici, mesajlar, metin):
            self.assertEqual(saglayici, "ollama")
            self.assertIs(yonetici.agent.extra_system, cloud_server.CLOUD_NOTE)
            self.assertLessEqual({s["name"] for s in yonetici.agent.tool_specs}, cloud_server.CLOUD_TOOLS)
            mesajlar += [{"role": "user", "content": metin}, {"role": "assistant", "content": "bulut cevap"}]
            yonetici.agent.cb.on_text("bulut cevap")

        with mock.patch.object(manager.Manager, "run", autospec=True, side_effect=sahte) as run:
            self.assertEqual(cloud_server.answer("web", "selam"), "bulut cevap")
        run.assert_called_once()
        self.assertEqual(cloud_server.history("web")[-1]["content"], "bulut cevap")


if __name__ == "__main__":
    unittest.main()
