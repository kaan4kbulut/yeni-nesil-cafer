"""Tek ayar kaynağı (`asistan.cekirdek.ayar`): ayarlar.json + ayar.toml + CAFER_* ortam değişkenleri.

Çalıştırma (proje kökünde, programın Python'uyla):
    ~/.local/share/yeni-nesil-cafer-app/python/bin/python3 -m unittest discover -s testler -v
"""

import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

KOK = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(KOK))

_GECICI = tempfile.mkdtemp(prefix="yeni-nesil-cafer-test-")
os.environ["XDG_CONFIG_HOME"] = str(Path(_GECICI) / "ayar")
os.environ["XDG_DATA_HOME"] = str(Path(_GECICI) / "veri")

from asistan import config  # noqa: E402
from asistan.cekirdek import ayar  # noqa: E402


def _temiz_ortam() -> dict:
    return {k: v for k, v in os.environ.items() if not k.startswith("CAFER_")}


class AyarTesti(unittest.TestCase):
    def setUp(self):
        klasor = Path(tempfile.mkdtemp(prefix="ayar-"))
        self.dosya = klasor / "ayar.toml"
        # pytest tek süreçte koşar: ortak ayarlar.json'a yazılırsa sonraki testler (pencere) bozuk adrese bağlanır
        for yama in (mock.patch.dict(os.environ, {**_temiz_ortam(), ayar.DOSYA_ORTAMI: str(self.dosya)}, clear=True),
                     mock.patch.object(ayar, "CONFIG_DIR", klasor),
                     mock.patch.object(ayar, "CONFIG_FILE", klasor / "ayarlar.json")):
            yama.start()
            self.addCleanup(yama.stop)

    def test_eski_yol_ayni_nesneler(self):
        self.assertIs(config.Settings, ayar.Settings)
        self.assertIs(config.migrate_dir, ayar.migrate_dir)
        self.assertEqual(config.DATA_DIR, ayar.DATA_DIR)
        # testler gerçek veri klasörüne yazmaz (pytest tek süreçte koşunca ilk test dosyasının geçici klasörü)
        self.assertTrue(config.CONFIG_DIR.is_relative_to(tempfile.gettempdir()), config.CONFIG_DIR)

    def test_dosya_yokken_varsayilanlar(self):
        self.assertEqual(ayar.dosyadan(), {})
        self.assertEqual(ayar.deger("gizlilik.mod"), "karma")
        self.assertEqual(ayar.deger("sunucu.port"), 8765)
        self.assertEqual(ayar.deger("yok.boyle", "x"), "x")

    def test_toml_okunur_ve_duzlesir(self):
        self.dosya.write_text('[genel]\nkademe_kilidi = "dusuk"\n[saglayici.ollama]\nurl = "http://kutu:11434"\n'
                              '[cli_ajan]\ntercih = ["codex"]\n', encoding="utf-8")
        self.assertEqual(ayar.deger("genel.kademe_kilidi"), "dusuk")
        self.assertEqual(ayar.deger("saglayici.ollama.url"), "http://kutu:11434")
        self.assertEqual(ayar.deger("cli_ajan.tercih"), ["codex"])

    def test_bozuk_toml_programi_durdurmaz(self):
        self.dosya.write_text("[genel\nbozuk", encoding="utf-8")
        with self.assertLogs(ayar.__name__, "WARNING"):
            self.assertEqual(ayar.dosyadan(), {})
        self.assertEqual(ayar.deger("gizlilik.mod"), "karma")

    def test_ortam_dosyayi_ezer_ve_turu_korur(self):
        self.dosya.write_text('[sunucu]\nport = 9000\n', encoding="utf-8")
        with mock.patch.dict(os.environ, {"CAFER_SUNUCU_PORT": "9100", "CAFER_GENEL_KADEME_KILIDI": "orta",
                                          "CAFER_CLI_AJAN_TERCIH": "gemini, claude",
                                          "CAFER_SAGLAYICI_OPENAI_UYUMLU_URL": "http://x/v1",
                                          "CAFER_YENI_BOLUM_ANAHTAR": "true", "CAFER_TOKEN": "gizli"}):
            degerler = ayar.oku()
        self.assertEqual(degerler["sunucu.port"], 9100)
        self.assertEqual(degerler["genel.kademe_kilidi"], "orta")
        self.assertEqual(degerler["cli_ajan.tercih"], ["gemini", "claude"])
        self.assertEqual(degerler["saglayici.openai_uyumlu.url"], "http://x/v1")
        self.assertIs(degerler["yeni.bolum_anahtar"], True)
        self.assertNotIn("gizli", degerler.values())  # CAFER_TOKEN ayar değil, sunucu anahtarı

    def test_settings_eskisi_gibi(self):
        s = ayar.Settings()
        s.ollama_url = "http://eski:11434"
        s.save()
        self.assertEqual(oct(ayar.CONFIG_FILE.stat().st_mode & 0o777), "0o600")
        self.assertEqual(ayar.Settings.load().ollama_url, "http://eski:11434")
        self.assertEqual(json.loads(ayar.CONFIG_FILE.read_text(encoding="utf-8"))["ollama_url"], "http://eski:11434")

    def test_ezilen_deger_dosyaya_yazilmaz(self):
        s = ayar.Settings()
        s.ollama_url, s.workspace = "http://eski:11434", "/tmp/eski-klasor"
        s.save()
        with mock.patch.dict(os.environ, {"CAFER_SAGLAYICI_OLLAMA_URL": "http://sunucu:11434",
                                          "CAFER_GENEL_CALISMA_KLASORU": "~/Cafer"}):
            yuklu = ayar.Settings.load()
            self.assertEqual(yuklu.ollama_url, "http://sunucu:11434")
            self.assertEqual(yuklu.workspace, str(Path.home() / "Cafer"))
            yuklu.accent = "#000000"  # arayüz başka bir ayarı değiştirip kaydediyor
            yuklu.save()
        diskte = json.loads(ayar.CONFIG_FILE.read_text(encoding="utf-8"))
        self.assertEqual(diskte["ollama_url"], "http://eski:11434")
        self.assertEqual(diskte["workspace"], "/tmp/eski-klasor")
        self.assertEqual(diskte["accent"], "#000000")
        self.assertEqual(ayar.Settings.load().ollama_url, "http://eski:11434")  # ortam kalkınca eski değer

    def test_varsayilan_settingsi_ezmez(self):
        s = ayar.Settings()
        s.ollama_url = "http://baska:11434"
        s.save()
        self.assertEqual(ayar.Settings.load().ollama_url, "http://baska:11434")  # VARSAYILAN'daki url değil


if __name__ == "__main__":
    unittest.main()
