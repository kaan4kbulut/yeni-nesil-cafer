"""K13 — güç ve donanım farkındalığı: `cekirdek/donanim.py`, `olcum.donanim_karari/uyarla/GucIzleyici`, arayüz iş parçacığı.

Sahte /sys ağacı, sahte nvidia-smi / lspci / ollama ps çıktısı; gerçek alt süreç ve gerçek ağ yok.
Çalıştırma: QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest testler/test_k13_donanim.py -q
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

from asistan.cekirdek import donanim, profil  # noqa: E402
from asistan.cekirdek.analiz import olcum  # noqa: E402
from asistan.cekirdek.saglayici.ollama import OllamaSaglayici  # noqa: E402

NVIDIA_CIKTI = "NVIDIA GeForce RTX 3060 Laptop GPU, 6144, 500, 80.00, 25.10, 1500, 1900, P2, 60\n"
NVIDIA_UYKU = "NVIDIA GeForce RTX 3060 Laptop GPU, 6144, 0, [N/A], 3.00, 210, 1900, P8, 0\n"
LSPCI = ("00:02.0 VGA compatible controller: Intel Corporation Alder Lake-P GT2 [Iris Xe Graphics] (rev 0c)\n"
         "01:00.0 3D controller: NVIDIA Corporation GA106M [GeForce RTX 3060 Mobile] (rev a1)\n")
PS_CPU = "NAME  ID  SIZE  PROCESSOR  UNTIL\nqwen2.5:14b  abc  10 GB  100% CPU  4 minutes from now\n"
PS_GPU = "NAME  ID  SIZE  PROCESSOR  UNTIL\nqwen2.5:14b  abc  10 GB  100% GPU  4 minutes from now\n"
PS_KISMI = "NAME  ID  SIZE  PROCESSOR  UNTIL\nbuyuk:32b  abc  20 GB  48%/52% CPU/GPU  4 minutes from now\n"


def sahte_sys(kok: Path, mains: bool | None, pil: tuple[int, str] | None):
    for ad in list(kok.glob("*")):
        for f in ad.glob("*"):
            f.unlink()
        ad.rmdir()
    if mains is not None:
        (kok / "AC").mkdir()
        (kok / "AC" / "type").write_text("Mains\n")
        (kok / "AC" / "online").write_text("1\n" if mains else "0\n")
    if pil:
        (kok / "BAT0").mkdir()
        (kok / "BAT0" / "type").write_text("Battery\n")
        (kok / "BAT0" / "capacity").write_text(f"{pil[0]}\n")
        (kok / "BAT0" / "status").write_text(pil[1] + "\n")


def sahte_calistir(nvidia=NVIDIA_CIKTI, lspci=LSPCI, ps=PS_GPU, upower=None, nvidia_zaman_asimi=False):
    def calistir(komut, sure=4):
        ad = komut[0]
        if ad == "nvidia-smi":
            if nvidia_zaman_asimi:
                raise donanim.ZamanAsimi("nvidia-smi")
            return nvidia
        if ad == "lspci":
            return lspci
        if ad == "ollama":
            return ps
        if ad == "upower":
            return (upower or {}).get(" ".join(komut[1:]), "")
        return None
    return calistir


class GucDurumu(unittest.TestCase):
    def setUp(self):
        self.kok = Path(tempfile.mkdtemp(dir=_GECICI))

    def test_fiste_ve_pilde(self):
        sahte_sys(self.kok, True, (80, "Charging"))
        self.assertEqual(donanim._guc_sys(str(self.kok)), {"fiste": True, "pil_yuzde": 80})
        sahte_sys(self.kok, False, (55, "Discharging"))
        self.assertEqual(donanim._guc_sys(str(self.kok)), {"fiste": False, "pil_yuzde": 55})

    def test_dolu_pilde_adaptor_esas(self):
        sahte_sys(self.kok, True, (100, "Not charging"))
        self.assertTrue(donanim._guc_sys(str(self.kok))["fiste"])

    def test_adaptor_kaydi_yoksa_pil_durumuna_bakilir(self):
        sahte_sys(self.kok, None, (40, "Discharging"))
        self.assertFalse(donanim._guc_sys(str(self.kok))["fiste"])

    def test_kayit_yoksa_none_sonra_upower(self):
        sahte_sys(self.kok, None, None)
        self.assertIsNone(donanim._guc_sys(str(self.kok)))
        up = {"-e": "/org/freedesktop/UPower/devices/line_power_AC\n/org/freedesktop/UPower/devices/battery_BAT0\n",
              "-i /org/freedesktop/UPower/devices/line_power_AC": "  online:  no\n",
              "-i /org/freedesktop/UPower/devices/battery_BAT0": "  state: discharging\n  percentage: 42%\n"}
        with mock.patch.object(donanim, "_calistir", sahte_calistir(upower=up)):
            self.assertEqual(donanim._guc_upower(), {"fiste": False, "pil_yuzde": 42})

    def test_guc_durumu_sys_kullanir_ve_onbellekler(self):
        sahte_sys(self.kok, False, (70, "Discharging"))
        donanim.onbellek_temizle()
        with mock.patch.object(donanim, "_SYS_GUC", str(self.kok)), \
                mock.patch.object(donanim.platform, "system", return_value="Linux"):
            self.assertEqual(donanim.guc_durumu(), {"fiste": False, "pil_yuzde": 70})
            sahte_sys(self.kok, True, (70, "Charging"))
            self.assertFalse(donanim.guc_durumu()["fiste"])  # 10 sn önbellek
            self.assertTrue(donanim.guc_durumu(yenile=True)["fiste"])
        donanim.onbellek_temizle()


class GpuEnvanteri(unittest.TestCase):
    def setUp(self):
        donanim.onbellek_temizle()

    def tearDown(self):
        donanim.onbellek_temizle()

    def envanter(self, **k):
        with mock.patch.object(donanim, "_calistir", sahte_calistir(**k)):
            return donanim.gpu_envanteri(yenile=True)

    def test_nvidia_alanlari(self):
        k = self.envanter()["nvidia"][0]
        self.assertEqual((k["vram_toplam_mib"], k["guc_siniri_w"], k["sm_mhz"], k["sm_max_mhz"], k["pstate"]),
                         (6144, 80.0, 1500.0, 1900.0, "P2"))

    def test_dahili_gpu_ollama_kullanamaz_ve_hibrit(self):
        e = self.envanter()
        self.assertTrue(e["hibrit"])
        self.assertEqual(len(e["dahili"]), 1)
        self.assertIs(e["dahili"][0]["ollama_kullanabilir"], False)
        self.assertFalse(e["uyuyor"])

    def test_yalniz_dahili_hibrit_degil(self):
        e = self.envanter(nvidia="", lspci=LSPCI.splitlines()[0] + "\n")
        self.assertFalse(e["hibrit"])
        self.assertEqual(e["nvidia"], [])

    def test_uyuyan_dgpu_p8_ve_sifir_kullanim(self):
        self.assertTrue(self.envanter(nvidia=NVIDIA_UYKU)["uyuyor"])

    def test_uyuyan_dgpu_zaman_asimi(self):
        e = self.envanter(nvidia_zaman_asimi=True)
        self.assertTrue(e["uyuyor"])
        self.assertTrue(e["nvidia_zaman_asimi"])

    def test_ollama_gpu_gormuyor_yalniz_kart_saglamken_ve_yuzde_yuz_cpu(self):
        self.assertTrue(self.envanter(ps=PS_CPU)["ollama_gpu_gormuyor"])
        self.assertFalse(self.envanter(ps=PS_GPU)["ollama_gpu_gormuyor"])
        self.assertFalse(self.envanter(ps=PS_KISMI)["ollama_gpu_gormuyor"])
        self.assertFalse(self.envanter(ps=PS_CPU, nvidia="", lspci="")["ollama_gpu_gormuyor"])  # kart yok

    def test_ollama_ps_yuzdeleri(self):
        m = donanim.ollama_ps_coz(PS_KISMI)[0]
        self.assertEqual((m["model"], m["cpu_yuzde"], m["gpu_yuzde"]), ("buyuk:32b", 48, 52))

    def test_cpu_ram(self):
        r = donanim.cpu_ram(yenile=True)
        self.assertGreaterEqual(r["cekirdek"], 1)
        self.assertGreaterEqual(r["bos_ram_gb"], 0)


def guc(fiste=True):
    return {"fiste": fiste, "pil_yuzde": None if fiste else 50}


def env(**k):
    e = {"nvidia": [{"ad": "RTX", "vram_toplam_mib": 6144, "guc_siniri_w": 80.0, "guc_w": 20.0, "sm_mhz": 1500.0,
                     "sm_max_mhz": 1900.0, "pstate": "P2", "kullanim_yuzde": 60}],
         "dahili": [], "harici_diger": [], "hibrit": False, "uyuyor": False, "nvidia_zaman_asimi": False,
         "ollama": [], "ollama_gpu_gormuyor": False}
    e.update(k)
    return e


def olc(cihaz, tok, fiste, model="m"):
    return {"model": model, "cihaz": cihaz, "fiste": fiste, "tok_sn": tok}


SIGAR = {"boyut_mib": 3000, "katman": 32, "kv_token_bayt": 20_000}
SIGMAZ = {"boyut_mib": 12000, "katman": 40, "kv_token_bayt": 100_000}


class KararTablosu(unittest.TestCase):
    def karar(self, g=True, e=None, o=(), bilgi=SIGAR, **k):
        return olcum.donanim_karari(guc(g), e or env(), list(o), model="m", model_ctx=16384, temel_kademe="yuksek",
                                    model_bilgi=bilgi, **k)

    def test_fiste_tam_guc(self):
        k = self.karar()
        self.assertEqual((k["cihaz"], k["kademe"], k["num_gpu"], k["num_ctx"]), ("gpu", "yuksek", None, 16384))

    def test_pilde_yuksek_kapali_baglam_yarim(self):
        k = self.karar(g=False, o=[olc("gpu", 30, False), olc("cpu", 5, False)])
        self.assertEqual((k["cihaz"], k["kademe"], k["num_ctx"]), ("gpu", "orta", 8192))
        self.assertIn("pilde", k["neden"])

    def test_pilde_olcum_yoksa_gpu_kalir_ve_olcum_istenir(self):
        k = self.karar(g=False)
        self.assertEqual(k["cihaz"], "gpu")
        self.assertEqual(sorted(c for _, c in k["olcum_gerekli"]), ["cpu", "gpu"])

    def test_pilde_gpu_1_5_katindan_yavassa_cpu(self):
        k = self.karar(g=False, o=[olc("gpu", 6, False), olc("cpu", 5, False)])  # 6 < 7.5
        self.assertEqual((k["cihaz"], k["num_gpu"], k["kademe"]), ("cpu", 0, "orta"))
        self.assertIn("tok/sn", k["neden"])

    def test_pilde_sinirda_gpu_1_5_kat_ve_uzeri_gpu(self):
        k = self.karar(g=False, o=[olc("gpu", 8, False), olc("cpu", 5, False)])
        self.assertEqual(k["cihaz"], "gpu")

    def test_fisteki_olcum_pil_kararini_etkilemez(self):
        k = self.karar(g=False, o=[olc("gpu", 1, True), olc("cpu", 9, True)])
        self.assertEqual(k["cihaz"], "gpu")  # pil ölçümü yok → gpu + ölçüm iste

    def test_fiste_guc_siniri_dusukse_olcume_gore(self):
        kisik = env()
        kisik["nvidia"][0].update(sm_mhz=600.0, kullanim_yuzde=90)
        k = self.karar(e=kisik, o=[olc("gpu", 4, True), olc("cpu", 5, True)])
        self.assertEqual(k["cihaz"], "cpu")

    def test_fiseye_donunce_eski_karar(self):
        pil = self.karar(g=False, o=[olc("gpu", 4, False), olc("cpu", 5, False)])
        self.assertEqual(pil["cihaz"], "cpu")
        fis = self.karar(g=True, o=[olc("gpu", 4, False), olc("cpu", 5, False)])
        self.assertEqual((fis["cihaz"], fis["kademe"], fis["num_ctx"]), ("gpu", "yuksek", 16384))

    def test_uyuyan_dgpu_tek_uyandirma_basarili(self):
        cagri = []
        k = self.karar(e=env(uyuyor=True, hibrit=True), uyandir=lambda: cagri.append(1) or True)
        self.assertEqual((k["cihaz"], len(cagri)), ("gpu", 1))

    def test_uyuyan_dgpu_uyanmazsa_cpu(self):
        k = self.karar(e=env(uyuyor=True, hibrit=True), uyandir=lambda: False)
        self.assertEqual(k["cihaz"], "cpu")
        self.assertIn("uyu", k["neden"])

    def test_vram_yetmezse_kismi_num_gpu(self):
        k = self.karar(bilgi=SIGMAZ)
        self.assertEqual(k["cihaz"], "gpu")
        self.assertTrue(0 < k["num_gpu"] < 40)

    def test_hic_sigmazsa_tam_cpu(self):
        k = self.karar(e=env(nvidia=[{**env()["nvidia"][0], "vram_toplam_mib": 1500}]))
        self.assertEqual((k["cihaz"], k["num_gpu"]), ("cpu", 0))

    def test_ollama_gormuyor_yeniden_baslat_onerisi_sonra_cpu(self):
        e = env(ollama_gpu_gormuyor=True)
        self.assertEqual(self.karar(e=e)["oneri"], "ollama_yeniden_baslat")
        self.assertEqual(self.karar(e=e)["cihaz"], "gpu")
        k = self.karar(e=e, yeniden_baslatildi=True)
        self.assertEqual((k["cihaz"], k["oneri"]), ("cpu", None))

    def test_kart_yoksa_cpu_dahili_gpu_secenegi_yok(self):
        e = env(nvidia=[], dahili=[{"ad": "Intel Iris", "uretici": "intel", "ollama_kullanabilir": False}])
        k = self.karar(e=e)
        self.assertEqual((k["cihaz"], k["num_gpu"]), ("cpu", None))
        self.assertNotIn("gpu'ya geç", k["neden"].lower())

    def test_kismi_gpu_hesabi(self):
        self.assertIsNone(olcum.kismi_gpu(1000, 32, 8192))
        self.assertEqual(olcum.kismi_gpu(50000, 40, 2048), 0)

    def test_durum_satiri(self):
        k = self.karar(g=False, o=[olc("gpu", 30, False), olc("cpu", 5, False)])
        self.assertEqual(olcum.durum_satiri({**k, "fiste": True}, k), "Pile geçildi → orta kademe, 8K bağlam, GPU")
        self.assertTrue(olcum.durum_satiri(k, {**k, "fiste": True}).startswith("Fişe takıldı"))


class Uygulama(unittest.TestCase):
    """uyarla / izleyici: güç değişince kademe güncellenir; istek sürerken ertelenir."""

    def setUp(self):
        donanim.onbellek_temizle()
        donanim.karar_yaz(None)
        profil._onbellek_temizle()
        self.durum = {"fiste": True}
        self.ayarlar = SimpleNamespace(extra={}, ollama_model="", ollama_url="http://x", ollama_num_ctx=16384, ctx_probe=None)
        self.notlar = []
        self.yamalar = [
            mock.patch.object(donanim, "guc_durumu", lambda yenile=False: {"fiste": self.durum["fiste"], "pil_yuzde": 50}),
            mock.patch.object(donanim, "gpu_envanteri", lambda yenile=False: env()),
            mock.patch.object(profil, "temel_kademe", lambda: "yuksek"),
            mock.patch.object(olcum, "donanim_olcumleri", lambda: []),
        ]
        for y in self.yamalar:
            y.start()

    def tearDown(self):
        for y in self.yamalar:
            y.stop()
        donanim.karar_yaz(None)
        profil._onbellek_temizle()

    def test_guc_degisimi_kademeyi_gunceller_ve_tek_satir_bildirir(self):
        olcum.uyarla(self.ayarlar, self.notlar.append)
        self.assertEqual(self.notlar, [])  # fişte varsayılan: sessiz
        self.assertEqual(profil.kademe(), "yuksek")
        self.durum["fiste"] = False
        olcum.uyarla(self.ayarlar, self.notlar.append)
        self.assertEqual(len(self.notlar), 1)
        self.assertTrue(self.notlar[0].startswith("Pile geçildi → orta kademe"))
        self.assertEqual(profil.kademe(), "orta")
        self.durum["fiste"] = True
        olcum.uyarla(self.ayarlar, self.notlar.append)
        self.assertTrue(self.notlar[-1].startswith("Fişe takıldı → yüksek kademe"))
        self.assertEqual(profil.kademe(), "yuksek")

    def test_kilit_varsa_karar_kademeyi_ezmez(self):
        self.durum["fiste"] = False
        with mock.patch.object(profil, "kilit", lambda: "yuksek"):
            olcum.uyarla(self.ayarlar)
            profil._onbellek_temizle()
            self.assertEqual(profil.kademe(), "yuksek")

    def test_otomatik_kapaliysa_karar_yok(self):
        self.ayarlar.extra = {"donanim_otomatik": False}
        self.durum["fiste"] = False
        self.assertIsNone(olcum.uyarla(self.ayarlar, self.notlar.append))
        self.assertIsNone(donanim.karar())
        self.assertEqual(profil.kademe(), "yuksek")

    def test_mesgulken_ertelenir_bitince_uygulanir(self):
        olcum.uyarla(self.ayarlar)
        self.durum["fiste"] = False
        mesgul = {"v": True}
        self.assertIsNone(olcum.uyarla(self.ayarlar, self.notlar.append, lambda: mesgul["v"]))
        self.assertEqual(donanim.karar()["kademe"], "yuksek")
        mesgul["v"] = False
        olcum.uyarla(self.ayarlar, self.notlar.append, lambda: mesgul["v"])
        self.assertEqual(donanim.karar()["kademe"], "orta")

    def test_pil_num_ctx_yarim(self):
        olcum.uyarla(self.ayarlar)
        self.durum["fiste"] = False
        olcum.uyarla(self.ayarlar)
        self.assertEqual(donanim.karar()["num_ctx"], 8192)

    def test_izleyici_turu_degisimi_yakalar(self):
        iz = olcum.GucIzleyici(self.ayarlar, self.notlar.append)
        iz.tur(0)
        self.durum["fiste"] = False
        iz.tur(1)
        self.assertTrue(any(n.startswith("Pile geçildi") for n in self.notlar))

    def test_karar_num_gpu_saglayici_istegine_girer(self):
        s = OllamaSaglayici("http://x", "m")
        self.assertNotIn("num_gpu", s.istek([], "sis", num_ctx=8192).get("options", {}))
        donanim.karar_yaz({"cihaz": "cpu", "num_gpu": 0, "model": "m", "kademe": "orta", "num_ctx": 8192})
        self.assertEqual(s.istek([], "sis", num_ctx=8192)["options"]["num_gpu"], 0)
        donanim.karar_yaz({"cihaz": "gpu", "num_gpu": 12, "model": "baska", "kademe": "orta", "num_ctx": 8192})
        self.assertNotIn("num_gpu", s.istek([], "sis", num_ctx=8192)["options"])


class Sonda(unittest.TestCase):
    def test_hizli_sonda_cihaza_gore_num_gpu_ve_kayit(self):
        gonderilen = []

        def post(url, json=None, timeout=None):
            gonderilen.append(json)
            return SimpleNamespace(raise_for_status=lambda: None,
                                   json=lambda: {"eval_count": 32, "eval_duration": 2_000_000_000,
                                                 "load_duration": 500_000_000})

        with mock.patch.object(olcum.httpx, "post", post):
            g = olcum.hizli_sonda("m", "gpu", "http://x", fiste=True)
            c = olcum.hizli_sonda("m", "cpu", "http://x", fiste=False)
        self.assertNotIn("num_gpu", gonderilen[0]["options"])
        self.assertEqual(gonderilen[1]["options"]["num_gpu"], 0)
        self.assertEqual(gonderilen[0]["options"]["num_predict"], 32)
        self.assertEqual((g["tok_sn"], g["yukleme_sn"]), (16.0, 0.5))
        kayitlar = olcum.donanim_olcumleri()
        self.assertEqual([k["cihaz"] for k in kayitlar[-2:]], ["gpu", "cpu"])
        self.assertEqual(olcum.son_olcum(kayitlar, "m", "cpu", False), 16.0)

    def test_sonda_yalniz_bostayken_en_cok_iki(self):
        cagrilar = []
        with mock.patch.object(olcum, "hizli_sonda", lambda m, c, u=None: cagrilar.append((m, c)) or {"tok_sn": 1}):
            olcum._sonda_hatasi = 0.0
            self.assertEqual(olcum.sonda_kos([("m", "gpu"), ("m", "cpu"), ("x", "gpu")], lambda: False), [])
            self.assertEqual(cagrilar, [])
            self.assertEqual(len(olcum.sonda_kos([("m", "gpu"), ("m", "cpu"), ("x", "gpu")], lambda: True)), 2)


class GuiParcacigi(unittest.TestCase):
    def test_gui_parcaciginda_alt_surec_yok(self):
        """İşaretli (GUI) iş parçacığında donanım okumaları subprocess açmaz; bayat/varsayılan değer döner."""
        donanim.onbellek_temizle()
        sonuc = {}

        def gui():
            donanim.gui_parcacigini_isaretle()
            gui_parcacigi = threading.current_thread()
            gui_cagrilari = []

            def run(*a, **k):  # arka plan yenilemesi (GUI dışı iş parçacığı) serbest; GUI'de yasak
                if threading.current_thread() is gui_parcacigi:
                    gui_cagrilari.append(a)
                return SimpleNamespace(stdout="", returncode=1)

            with mock.patch.object(donanim.subprocess, "run", run):
                sonuc["guc"] = donanim.guc_durumu()
                sonuc["env"] = donanim.gpu_envanteri()
                sonuc["cpu"] = donanim.cpu_ram()
                sonuc["cagri"] = len(gui_cagrilari)
                self.assertIsNone(donanim._calistir(["nvidia-smi"]))
            donanim.gui_parcacigini_isaretle(threading.Thread())  # işareti başka bir parçacığa taşı

        t = threading.Thread(target=gui)
        t.start()
        t.join()
        self.assertEqual(sonuc["cagri"], 0)
        self.assertEqual(sonuc["env"]["nvidia"], [])
        donanim.onbellek_temizle()

    def test_profil_dialogu_offscreen_acilir_ve_gui_de_alt_surec_acmaz(self):
        os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
        from PySide6.QtWidgets import QApplication

        from asistan.gui.profil_dialog import ProfileDialog

        app = QApplication.instance() or QApplication([])
        donanim.gui_parcacigini_isaretle()
        try:
            with mock.patch.object(olcum, "donanim_ozeti", lambda: "Güç: fişte"):
                ayarlar = SimpleNamespace(extra={}, ollama_model="", ollama_url="http://x", save=lambda: None)
                d = ProfileDialog(ayarlar=ayarlar)
                self.assertTrue(d.auto_hw.isChecked())
                self.assertTrue(d.hw_restart.isHidden())
                bitis = time.time() + 5  # arka plan işleri bitmeden pencere silinmesin (sinyal ölü nesneye gitmesin)
                while d.hw_text.toPlainText() != "Güç: fişte" and time.time() < bitis:
                    app.processEvents()
                    time.sleep(0.02)
                self.assertEqual(d.hw_text.toPlainText(), "Güç: fişte")
                d.close()
                d.deleteLater()
                app.processEvents()
        finally:
            donanim.gui_parcacigini_isaretle(threading.Thread())


if __name__ == "__main__":
    unittest.main()
