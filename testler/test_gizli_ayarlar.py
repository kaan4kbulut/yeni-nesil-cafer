"""Sır sızıntısı (BÖLÜM 2.2): `Settings`'te anahtar alanı yok, anahtar yalnızca anahtar zincirinde; `ayarlar.json` ve
`anahtarlar.json` okunamaz; programın ayar klasörü (`CONFIG_DIR`) `read_file` ile hiç okunamaz."""

import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

KOK = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(KOK))
_GECICI = tempfile.mkdtemp(prefix="yeni-nesil-cafer-test-")
os.environ["XDG_CONFIG_HOME"] = str(Path(_GECICI) / "ayar")
os.environ["XDG_DATA_HOME"] = str(Path(_GECICI) / "veri")

from asistan.cekirdek import ayar  # noqa: E402
from asistan.cekirdek.araclar import AracHatasi, dosya  # noqa: E402


class AnahtarAlaniYok(unittest.TestCase):
    def test_settings_anahtar_tasimaz(self):
        self.assertNotIn("anthropic_api_key", ayar.Settings.__dataclass_fields__)
        s = ayar.Settings(workspace=_GECICI)
        s.save()
        self.assertNotIn("anthropic_api_key", json.loads(ayar.CONFIG_FILE.read_text(encoding="utf-8")))

    def test_eski_dosyadaki_anahtar_bir_kez_okunur_ve_kaydedince_silinir(self):
        ayar.CONFIG_DIR.mkdir(parents=True, exist_ok=True)
        ayar.CONFIG_FILE.write_text(json.dumps({"workspace": _GECICI, "anthropic_api_key": "sk-eski"}), encoding="utf-8")
        self.assertEqual(ayar.eski_anahtar(), "sk-eski")  # açılışta anahtar zincirine taşınacak
        s = ayar.Settings.load()
        self.assertFalse(hasattr(s, "anthropic_api_key"))
        s.save()  # dosyada artık yok
        self.assertNotIn("sk-eski", ayar.CONFIG_FILE.read_text(encoding="utf-8"))
        self.assertEqual(ayar.eski_anahtar(), "")


class AyarKlasoruOkunamaz(unittest.TestCase):
    def setUp(self):
        self.kok = Path(tempfile.mkdtemp(prefix="is-", dir=_GECICI)).resolve()
        ayar.CONFIG_DIR.mkdir(parents=True, exist_ok=True)
        (ayar.CONFIG_DIR / "ayarlar.json").write_text("{}", encoding="utf-8")
        (ayar.CONFIG_DIR / "anahtarlar.json").write_text("{}", encoding="utf-8")
        (ayar.CONFIG_DIR / "not.txt").write_text("x", encoding="utf-8")

    def test_config_dir_okuma_koku_olsa_da_okunamaz(self):
        kokler = [ayar.CONFIG_DIR.resolve()]
        for ad in ("ayarlar.json", "anahtarlar.json", "not.txt"):
            with self.assertRaises(AracHatasi, msg=ad):
                dosya.oku(self.kok, kokler, str(ayar.CONFIG_DIR / ad))
        with self.assertRaises(AracHatasi):
            dosya.listele(self.kok, kokler, str(ayar.CONFIG_DIR))

    def test_gizli_adlar_calisma_klasorunde_de_okunamaz(self):
        for ad in ("ayarlar.json", "anahtarlar.json"):
            (self.kok / ad).write_text("{}", encoding="utf-8")
            with self.assertRaises(AracHatasi, msg=ad):
                dosya.oku(self.kok, [], ad)
        (self.kok / "veri.json").write_text("{}", encoding="utf-8")
        self.assertIn("{}", dosya.oku(self.kok, [], "veri.json"))


if __name__ == "__main__":
    unittest.main()
