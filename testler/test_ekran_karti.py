"""Ekran kartı denetimi (gpu.py): en güçlü kart seçimi, Ollama'nın o karta sabitlenmesi, yanlış kart / işlemci uyarısı.

Kartlar ve nvidia-smi çıktısı sahte; gerçek ekran kartı gerekmez.

Çalıştırma (proje kökünde, programın Python'uyla):
    ~/.local/share/yeni-nesil-cafer-app/python/bin/python3 -m unittest discover -s testler -v
"""

import os
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

KOK = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(KOK))
_GECICI = tempfile.mkdtemp(prefix="yeni-nesil-cafer-test-")
os.environ["XDG_CONFIG_HOME"] = str(Path(_GECICI) / "ayar")  # kullanıcının gerçek ayar ve verisine dokunulmaz
os.environ["XDG_DATA_HOME"] = str(Path(_GECICI) / "veri")

from asistan import gpu  # noqa: E402

INTEL = gpu.Card("Intel tümleşik", "intel", 0, False)
RTX = gpu.Card("NVIDIA GeForce RTX 5070 Ti Laptop GPU", "nvidia", 12227, True, "GPU-guclu")
MX = gpu.Card("NVIDIA GeForce MX550", "nvidia", 2048, True, "GPU-zayif")
TAM_GUC = SimpleNamespace(power_mode="performans")
HAFIF = SimpleNamespace(power_mode="tasarruf")
YUKLU = [{"name": "gemma4:12b", "size": 100, "size_vram": 100}]


class _GercekKartaBakma(unittest.TestCase):
    """Testler bu bilgisayardaki kartın gerçek durumunu (ör. sürücü hatası) okumasın."""

    def setUp(self):
        p = mock.patch.object(gpu, "fault", return_value="")
        p.start()
        self.addCleanup(p.stop)


class EnGucluKart(_GercekKartaBakma):
    def test_ayri_kart_tumlesikten_once_sonra_bellek(self):
        self.assertIs(gpu.strongest([INTEL, MX, RTX]), RTX)
        self.assertIs(gpu.strongest([INTEL]), INTEL)
        self.assertIsNone(gpu.strongest([]))

    def test_ollama_en_guclu_karta_sabitlenir_hafif_modda_sabitlenmez(self):
        with mock.patch.object(gpu, "cards", return_value=[INTEL, MX, RTX]), \
                mock.patch.dict(os.environ, {}, clear=False):
            os.environ.pop("CUDA_VISIBLE_DEVICES", None)
            self.assertEqual(gpu.ollama_env(TAM_GUC), {"CUDA_VISIBLE_DEVICES": "GPU-guclu"})
            self.assertEqual(gpu.ollama_env(HAFIF), {})
            os.environ["CUDA_VISIBLE_DEVICES"] = "0"  # kullanıcının kendi seçimine dokunulmaz
            self.assertEqual(gpu.ollama_env(TAM_GUC), {})


class Denetim(_GercekKartaBakma):
    def setUp(self):
        super().setUp()
        p = mock.patch.object(gpu, "cards", return_value=[INTEL, MX, RTX])
        p.start()
        self.addCleanup(p.stop)

    def _check(self, running, settings=TAM_GUC, owned=False, pids=None):
        with mock.patch.object(gpu, "_ollama_pids_by_gpu", return_value=pids or {"GPU-guclu": [11]}):
            return gpu.check(running, settings, owned)

    def test_dogru_kartta_tamam(self):
        r = self._check(YUKLU)
        self.assertTrue(r.ok)
        self.assertEqual(r.card, "RTX 5070 Ti")

    def test_yanlis_kart_uyarir_sistem_servisine_duzeltme_onerir(self):
        r = self._check(YUKLU, pids={"GPU-zayif": [11]})
        self.assertFalse(r.ok)
        self.assertIn("MX550", r.text)
        self.assertIn("CUDA_VISIBLE_DEVICES=GPU-guclu", r.fix)
        # Ollama'yı program başlattıysa düzeltmeyi kendisi yapar (öneri boş: yeniden başlatır)
        self.assertEqual(self._check(YUKLU, owned=True, pids={"GPU-zayif": [11]}).fix, "")

    def test_islemcide_calisma_uyarir_hafif_modda_normal(self):
        cpu = [{"name": "gemma4:12b", "size": 100, "size_vram": 0}]
        self.assertFalse(self._check(cpu).ok)
        self.assertIn("işlemcide", self._check(cpu).text)
        self.assertTrue(self._check(cpu, settings=HAFIF).ok)

    def test_sigmayan_model_yeniden_baslatmayla_duzelmez(self):
        r = self._check([{"name": "buyuk", "size": 100, "size_vram": 60}], owned=True)
        self.assertFalse(r.ok)
        self.assertIn("%60", r.text)
        self.assertTrue(r.fix)  # boş değil: pencere Ollama'yı boşuna yeniden başlatmaz

    def test_kart_yoksa_ve_model_yoksa(self):
        with mock.patch.object(gpu, "cards", return_value=[]):
            self.assertTrue(gpu.check(YUKLU, TAM_GUC, False).ok)
        self.assertTrue(self._check([]).ok)

    def test_resim_motorunun_karti(self):
        gpu.note_device(" Intel(R) UHD Graphics 770 ")
        self.assertFalse(gpu.image_report(TAM_GUC).ok)
        self.assertTrue(gpu.image_report(HAFIF).ok)
        gpu.note_device(" NVIDIA GeForce RTX 5070 Ti Laptop GPU ")
        self.assertTrue(gpu.image_report(TAM_GUC).ok)
        gpu.note_device("")


class SurucuHatasi(unittest.TestCase):
    """2026-09-26: Xid 62 sonrası "GPU requires reset"; Ollama sessizce işlemciye düştü, 14B model dakikalarca bekletti."""

    def setUp(self):
        gpu._fault = (0.0, "")
        self.addCleanup(lambda: setattr(gpu, "_fault", (0.0, "")))

    def _cikti(self, stdout, code=0):
        return mock.patch.object(gpu.subprocess, "run", return_value=mock.Mock(stdout=stdout, stderr="",
                                                                               returncode=code))

    def test_sifirlama_isteyen_kart_algilanir_ve_yeniden_baslatma_onerilir(self):
        with mock.patch.object(gpu, "cards", return_value=[INTEL, RTX]), self._cikti("[GPU requires reset]\n"):
            self.assertEqual(gpu.fault(), "sürücü sıfırlama istiyor")
            r = gpu.check(YUKLU, TAM_GUC, True)
        self.assertFalse(r.ok)
        self.assertIn("Bilgisayarı yeniden başlat", r.fix)
        self.assertTrue(r.fix)  # boş değil: pencere Ollama'yı boşuna yeniden başlatmaz

    def test_saglam_kart_ve_nvidia_yok(self):
        with mock.patch.object(gpu, "cards", return_value=[INTEL, RTX]), self._cikti("45\n"):
            self.assertEqual(gpu.fault(), "")
        gpu._fault = (0.0, "")
        with mock.patch.object(gpu, "cards", return_value=[INTEL]), self._cikti("[GPU requires reset]\n") as run:
            self.assertEqual(gpu.fault(), "")
        run.assert_not_called()

    def test_kart_bozukken_hafif_mod_kucuk_baglam(self):
        from asistan import power

        with mock.patch.object(gpu, "fault", return_value="sürücü sıfırlama istiyor"):
            s = SimpleNamespace(power_mode="performans", ollama_num_ctx=16384)
            self.assertTrue(power.saving(s))
            self.assertEqual(power.num_ctx(s), power.BATTERY_CTX)
            self.assertIn("ekran kartı hatası", power.label(s))


class NvidiaCiktisi(unittest.TestCase):
    def test_kartlar_ve_surecler_okunur(self):
        kartlar = "NVIDIA GeForce RTX 5070 Ti Laptop GPU, 12227, GPU-a\n"
        surecler = "13277, [Not Found], GPU-a\n1601, /usr/bin/kwin_wayland, GPU-a\n9, /usr/bin/ollama, GPU-a\n"
        with mock.patch.object(gpu, "_run", side_effect=[kartlar, surecler]), \
                mock.patch.object(Path, "read_text", return_value="llama-server\n"):
            self.assertEqual(gpu._nvidia(), [gpu.Card("NVIDIA GeForce RTX 5070 Ti Laptop GPU", "nvidia", 12227,
                                                      True, "GPU-a")])
            self.assertEqual(gpu._ollama_pids_by_gpu(), {"GPU-a": [13277, 9]})


if __name__ == "__main__":
    unittest.main()
