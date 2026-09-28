"""K12-D — donma düzeltmeleri (`NOTLAR/inceleme-k12-2026-09-28.md` D1–D10).

D1 model paneli arka planda yenilenir · D2 `gpu.fault` eski değeri döner, ölçümü arka planda yeniler · D3 sistem taraması
arka planda · D5 sihirbaz model listesini arka planda alır · D6 "bağlantıyı dene" arka planda · D7 bilinen sağlıksız
sağlayıcı zincirde atlanır (+ motorda model başına bağlam) · D8 model çağrısı iptal edilebilir (sağlayıcı `iptal`,
`specialists.ask(cancelled=…)`) · D10 komut aracı süreç grubunu öldürür, MCP kapanışta bekler.

Çalıştırma (proje kökünde): QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest testler/test_k12_d.py -q
"""

import os
import subprocess
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
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QEvent, QObject  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

APP = QApplication.instance() or QApplication([])

from asistan import gpu, mcp, specialists  # noqa: E402
from asistan.cekirdek import baglam, yonlendirici  # noqa: E402
from asistan.cekirdek.araclar import komut  # noqa: E402
from asistan.cekirdek.araclar.temel import AracHatasi  # noqa: E402
from asistan.cekirdek.gorev import model as gorev_model  # noqa: E402
from asistan.cekirdek.saglayici import METIN, NABIZ, SON, Iptal, Parca, Saglayici, Saglik, Yanit  # noqa: E402
from asistan.config import Settings  # noqa: E402
from asistan.gui import dialogs, panels, setup_wizard, window_models  # noqa: E402


def bekle(kosul, sn: float = 5.0) -> bool:
    """Koşul sağlanana kadar Qt olaylarını işler; sonunda ertelenmiş silmeleri (`_Job.deleteLater`) HEMEN işletir —
    yoksa üst nesne toplandıktan sonra başka bir testin `processEvents`'i silinmiş nesneyi siler (Bus error)."""
    t0 = time.time()
    tamam = False
    while time.time() - t0 < sn:
        APP.processEvents()
        if kosul():
            tamam = True
            break
        time.sleep(0.02)
    APP.processEvents()
    APP.sendPostedEvents(None, QEvent.DeferredDelete)
    APP.processEvents()
    return tamam


class D1ModelPaneli(unittest.TestCase):
    def test_refresh_ana_is_parcacigini_bloklamaz(self):
        s = Settings(workspace=str(Path(_GECICI) / "is"))
        panel = panels.ModelsPanel(s)
        gelen = []
        panel.refreshed.connect(gelen.append)
        yavas = {"basladi": False}

        def sahte_modeller(url):
            yavas["basladi"] = True
            time.sleep(0.4)
            return [{"name": s.ollama_model, "size": 1, "details": {}}]

        rapor = SimpleNamespace(ok=True, text="", fix="", card="")
        with mock.patch.object(panels, "ollama_models", sahte_modeller), mock.patch.object(panels, "ollama_running", lambda u: []), \
                mock.patch("asistan.gpu.check", return_value=rapor), mock.patch("asistan.sysinfo.program_owned", return_value=False):
            t0 = time.time()
            self.assertIsNone(panel.refresh())
            self.assertLess(time.time() - t0, 0.2)  # hemen döndü: ağ ve nvidia-smi arka planda
            self.assertTrue(bekle(lambda: gelen, 5))
        self.assertEqual(panel.list.count(), 1)
        self.assertIn("bağlı", panel.ollama_state.text())
        panel.deleteLater()
        APP.sendPostedEvents(None, QEvent.DeferredDelete)


class D2GpuFault(unittest.TestCase):
    def test_eski_deger_hemen_doner_olcum_arka_planda(self):
        gpu._fault = (0.0, "")

        def yavas(*a, **k):
            time.sleep(0.3)
            return SimpleNamespace(stdout="ERR!", stderr="", returncode=0)

        with mock.patch.object(gpu, "cards", return_value=[SimpleNamespace(vendor="nvidia")]), \
                mock.patch.object(gpu.subprocess, "run", yavas):
            t0 = time.time()
            self.assertEqual(gpu.fault(), "")  # ilk çağrı: eski değer (bilinmiyor = arıza yok)
            self.assertLess(time.time() - t0, 0.15)
            self.assertTrue(bekle(lambda: gpu._fault[1] != "", 3))
            self.assertEqual(gpu.fault(), "sürücü kartı göremiyor")  # önbellek
            gpu._fault = (0.0, "")
            self.assertEqual(gpu.fault(bekle=True), "sürücü kartı göremiyor")  # ölçüm zorunlu: eşzamanlı
        gpu._fault = (0.0, "")


class D3SistemTaramasi(unittest.TestCase):
    def test_tarama_arka_planda(self):
        class Sahte(QObject):
            settings = SimpleNamespace(ollama_url="http://127.0.0.1:1")

        f = Sahte()
        bilgi = SimpleNamespace(ollama_models=[])
        with mock.patch.object(window_models.sysinfo, "scan", lambda url: (time.sleep(0.2), bilgi)[1]):
            t0 = time.time()
            self.assertIsNone(window_models.ModelsMixin._system_info(f))  # ilk açılış: tarama başladı, sonuç yok
            self.assertLess(time.time() - t0, 0.15)
            self.assertTrue(bekle(lambda: getattr(f, "_sysinfo_cache", None) is not None, 3))
            self.assertIs(window_models.ModelsMixin._system_info(f), bilgi)


class D5Sihirbaz(unittest.TestCase):
    def test_model_listesi_arka_planda(self):
        f = SimpleNamespace(checks=[], info=SimpleNamespace(ollama_running=False, ollama_models=[]),
                            reco_text=SimpleNamespace(setText=lambda t: None), _fill_models_devam=lambda *a: None)
        kayit = {}
        with mock.patch.object(setup_wizard, "run_in_background", lambda fn, done, parent: kayit.update(fn=fn, done=done)), \
                mock.patch("asistan.model_updates.refresh") as refresh:
            setup_wizard.SetupWizard._fill_models(f)
        refresh.assert_not_called()  # ana iş parçacığında indirme yok
        self.assertIs(kayit["fn"], refresh)


class D6BaglantiDenemesi(unittest.TestCase):
    def test_test_cloud_arka_planda(self):
        f = SimpleNamespace(cloud_url=SimpleNamespace(text=lambda: "https://x"), cloud_token=SimpleNamespace(text=lambda: "t"),
                            cloud_status=SimpleNamespace(setText=lambda t: None))
        kayit = {}
        with mock.patch.object(dialogs, "run_in_background", lambda fn, done, parent: kayit.update(fn=fn)), \
                mock.patch("asistan.cloud_sync.check") as check:
            dialogs.SettingsDialog._test_cloud(f)
        check.assert_not_called()
        self.assertIn("fn", kayit)


class _SahteSaglayici(Saglayici):
    ad = "ollama"

    def __init__(self, kayit: list, kapandi: list):
        self.kayit, self.kapandi = kayit, kapandi

    def akis(self, mesajlar, sistem="", araclar=None, **secenek):
        self.kayit.append(secenek)
        try:
            yield Parca(NABIZ)
            yield Parca(METIN, "merhaba")
            yield Parca(SON)
        finally:
            self.kapandi.append(True)

    def saglik(self):
        return Saglik(True)


class D7SagliksizAtlanir(unittest.TestCase):
    def _secim(self, zincir):
        return yonlendirici.Secim("ollama", "a", "test", "yonetici", zincir=list(zincir))

    def test_bilinen_sagliksiz_zincirde_atlanir(self):
        yonlendirici.SAGLIK.temizle()
        yonlendirici.SAGLIK.bildir("ollama", False, "bağlantı yok")
        cagrilan = []

        def bul(ad, ayarlar, baglantilar):
            cagrilan.append(ad)
            return _SahteSaglayici([], [])

        ayarlar = SimpleNamespace(ollama_num_ctx=32768, ollama_model="a", ctx_probe={}, ollama_url="http://127.0.0.1:1")
        m = gorev_model.YonlendiriciModeli(ayarlar, [])
        with mock.patch.object(yonlendirici, "sec", return_value=self._secim([("claude", "b")])), \
                mock.patch("asistan.cekirdek.saglayici.bul", bul), mock.patch.object(yonlendirici, "tavan_durumu", return_value=""), \
                mock.patch("asistan.cekirdek.yapisal.harcama_yaz"):
            c = m("yonetici", [{"role": "user", "content": "x"}])
        self.assertEqual(cagrilan, ["claude"])  # ollama sağlıksız: bağlantı zaman aşımı ödenmedi
        self.assertEqual(c.metin, "merhaba")
        # zincirde tek seçenek sağlıksızsa yine denenir (60 sn önbellek işi durdurmaz)
        cagrilan.clear()
        m2 = gorev_model.YonlendiriciModeli(ayarlar, [])
        with mock.patch.object(yonlendirici, "sec", return_value=self._secim([])), \
                mock.patch("asistan.cekirdek.saglayici.bul", bul), mock.patch("asistan.cekirdek.yapisal.harcama_yaz"):
            m2("yonetici", [{"role": "user", "content": "x"}])
        self.assertEqual(cagrilan, ["ollama"])
        yonlendirici.SAGLIK.temizle()

    def test_motorda_model_basina_baglam_ve_iptal(self):
        kayit = []
        ayarlar = SimpleNamespace(ollama_num_ctx=32768, ollama_model="buyuk:14b", ctx_probe={}, ollama_url="http://127.0.0.1:1")
        m = gorev_model.YonlendiriciModeli(ayarlar, [])
        m.iptal = lambda: False
        with mock.patch.object(yonlendirici, "sec", return_value=self._secim([])), \
                mock.patch("asistan.cekirdek.saglayici.bul", lambda *a: _SahteSaglayici(kayit, [])), \
                mock.patch.object(baglam, "model_ctx", return_value=9216), mock.patch("asistan.cekirdek.yapisal.harcama_yaz"):
            m("yonetici", [{"role": "user", "content": "x"}])
        self.assertEqual(kayit[0].get("num_ctx"), 9216)  # global 32K değil, modele özgü sınır (C3 motor yolu)
        m.iptal = lambda: True  # ■: sağlayıcı ilk parçada Iptal fırlatır, zincirde başka model denenmez
        with mock.patch.object(yonlendirici, "sec", return_value=self._secim([("claude", "b")])), \
                mock.patch("asistan.cekirdek.saglayici.bul", lambda *a: _SahteSaglayici(kayit, [])), \
                mock.patch.object(baglam, "model_ctx", return_value=9216):
            with self.assertRaises(Iptal):
                m("yonetici", [{"role": "user", "content": "x"}])
        self.assertEqual(len(kayit), 2)


class D8Iptal(unittest.TestCase):
    def test_saglayici_sohbet_iptal(self):
        kapandi = []
        s = _SahteSaglayici([], kapandi)
        self.assertEqual(s.sohbet([{"role": "user", "content": "x"}]).metin, "merhaba")
        with self.assertRaises(Iptal):
            s.sohbet([{"role": "user", "content": "x"}], iptal=lambda: True)
        self.assertTrue(kapandi)  # üreteç kapatıldı: bağlantı kesildi, üretim durdu
        self.assertIsInstance(s.sohbet([], iptal=lambda: False), Yanit)

    def test_specialists_ask_akisli_ve_iptal(self):
        satirlar = [b'{"message":{"content":"mer"}}', b'{"message":{"content":"haba"},"done":true}']

        class Cevap:
            status_code = 200

            def __enter__(self): return self
            def __exit__(self, *a): return False
            def iter_lines(self): yield from (s.decode() for s in satirlar)
            def read(self): return b""

        kayit = {}

        def stream(method, url, **k):
            kayit.update(k)
            return Cevap()

        s = Settings(workspace=str(Path(_GECICI) / "is"))
        with mock.patch.object(specialists.httpx, "stream", stream):
            self.assertEqual(specialists.ask(s, [], "ollama", "m", "soru"), "merhaba")
            self.assertTrue(kayit["json"]["stream"])
            sayac = {"n": 0}

            def iptal():
                sayac["n"] += 1
                return sayac["n"] > 1

            with self.assertRaises(InterruptedError):
                specialists.ask(s, [], "ollama", "m", "soru", cancelled=iptal)


@unittest.skipIf(sys.platform == "win32", "posix süreç grubu")
class D10SurecGrubu(unittest.TestCase):
    def test_zaman_asiminda_torunlar_da_olur(self):
        isaret = f"sleep 30.{os.getpid()}"
        with self.assertRaises(AracHatasi):
            komut.surec(["bash", "-c", f"{isaret} & {isaret}"], Path(_GECICI), komut.guvenli_ortam(), zaman_asimi=0.5)
        time.sleep(0.3)
        kalan = subprocess.run(["pgrep", "-f", isaret], capture_output=True, text=True).stdout.split()
        self.assertEqual(kalan, [])

    def test_mcp_kapanista_bekler(self):
        proc = mock.Mock()
        proc.stdin.close.side_effect = OSError("boru kapalı")
        s = object.__new__(mcp._Stdio)
        s.proc, s.log = proc, mock.Mock()
        s.close()
        proc.kill.assert_called_once()
        proc.wait.assert_called()  # kill sonrası bekleme: zombi kalmaz


if __name__ == "__main__":
    unittest.main()
