"""K5 kapanışı (BÖLÜM 3): (a) manifest izinleri → izin hattı eşlemesi ve `izin_kaynagi=None` iken yazan adımın
onay beklemesi; (b) sarmalayıcı yetenek ↔ araç kaydı tutarlılığı (tek kayıt bekçisi); (c) sandbox ortamı 2.1 beyaz
listesinden; (f) çekirdek Playwright'lı `browser` modülünü içe aktarmaz."""

import importlib
import os
import re
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

from asistan import permissions  # noqa: E402
from asistan.cekirdek import profil  # noqa: E402
from asistan.cekirdek.yetenek import calistirici  # noqa: E402
from asistan.cekirdek.yetenek.kayit import YERLESIK_KOK, Kayit  # noqa: E402
from asistan.config import Settings  # noqa: E402
from asistan.registry import REGISTRY  # noqa: E402


class IzinEslemesi(unittest.TestCase):
    """SEMALAR §1: izinler → risk sınıfı → permissions.decide."""

    def _yetenek(self, izinler, kaynak="yerlesik", guvenilir=True):
        from asistan.cekirdek.yetenek.kayit import Yetenek

        return Yetenek(ad="x", klasor=Path(_GECICI), manifest={"ad": "x", "izinler": izinler, "kaynak": kaynak,
                                                                "guvenilir": guvenilir, "sandbox": True})

    def test_risk_siniflari(self):
        self.assertEqual(self._yetenek(["dosya_oku"]).risk(), "okur")
        self.assertEqual(self._yetenek(["dosya_oku", "dosya_yaz"]).risk(), "yazar")
        for izin in ("komut", "dosya_sil", "ag", "anahtar:HF_TOKEN"):
            self.assertEqual(self._yetenek([izin]).risk(), "calistirir", izin)
        self.assertEqual(self._yetenek(["dosya_oku"], kaynak="uretildi", guvenilir=False).risk(), "calistirir")

    def test_izin_kaynagi_yokken_yazma_onay_bekler(self):
        """CLI ve Görevler penceresi (izin_kaynagi=None): yazan/çalıştıran adım izin hattında sorulur, kullanıcı
        onaylayana kadar `bekliyor_onay`; okuma adımı sorulmaz."""
        from asistan.cekirdek.gorev.ajan import AjanYetenekleri

        ayarlar = Settings.load()
        ayarlar.workspace = tempfile.mkdtemp(dir=_GECICI)
        ayarlar.approval_mode, ayarlar.confirm_commands = "kullanici", False  # kutu kapalı olsa da
        yet = AjanYetenekleri(ayarlar, [], ayarlar.workspace, [], kayit=Kayit([YERLESIK_KOK], kademe="orta"))
        self.assertTrue(yet.ajan.must_act)
        self.assertTrue(yet.onay_gerekir("dosya_yaz", {"yol": "a.txt", "icerik": "x"}))
        self.assertTrue(yet.onay_gerekir("komut_calistir", {"komut": "rm x"}))
        self.assertFalse(yet.onay_gerekir("dosya_oku", {"yol": "a.txt"}))
        c = yet.calistir("dosya_yaz", {"yol": "a.txt", "icerik": "x"})  # onaysız çağrı: yazmaz, bekler
        self.assertTrue(c.onay_bekliyor)
        self.assertFalse(Path(ayarlar.workspace, "a.txt").exists())

    def test_karar_tablosu(self):
        ctx = permissions.Context(approval_mode="kullanici", confirm_commands=True, must_act=True)
        self.assertEqual(permissions.decide("read_file", {"path": "a"}, ctx).kind, permissions.ALLOW)
        self.assertEqual(permissions.decide("write_file", {"path": "a", "content": ""}, ctx).kind, permissions.ASK)
        self.assertEqual(permissions.decide("run_command", {"command": "rm x"}, ctx).kind, permissions.ASK)
        g = permissions.Context(approval_mode="guvenlik")
        self.assertEqual(permissions.decide("write_file", {"path": "a", "content": ""}, g).kind, permissions.REVIEW)


class TekKayit(unittest.TestCase):
    def test_sarmalayici_yetenek_araca_uyumlu(self):
        """Yerleşik (sandbox dışı) yeteneğin ARAC'ı kayıtta var; ESLEME alanları aracın şemasında; risk sınıfı aracınkiyle
        aynı ya da daha sıkı. Böylece manifest tek kayıttır, ikinci bir el listesi yok."""
        kayit = Kayit([YERLESIK_KOK], kademe="yuksek")
        sayi = 0
        for y in kayit.aktifler() + kayit.pasifler():
            if y.sandbox:
                continue
            mod = importlib.import_module(f"asistan.yetenekler.{y.ad}.calistir")
            arac = REGISTRY.get(getattr(mod, "ARAC"))
            self.assertIsNotNone(arac, y.ad)
            alanlar = set(arac.spec["input_schema"].get("properties", {}))
            for ad, (alan, _v) in getattr(mod, "ESLEME", {}).items():
                self.assertIn(alan, alanlar, f"{y.ad}.{ad} → {alan}")
                self.assertIn(ad, y.manifest["girdi"], f"{y.ad}: {ad} manifestte yok")
            sira = ("okur", "danisir", "yazar", "ekip", "calistirir", "kurar")
            self.assertGreaterEqual(sira.index(y.risk()), sira.index(arac.risk) if arac.risk in sira else 0, y.ad)
            sayi += 1
        self.assertGreaterEqual(sayi, 10)


class SandboxOrtami(unittest.TestCase):
    def test_beyaz_liste_ve_anahtar(self):
        from asistan.cekirdek.yetenek.kayit import Yetenek

        y = Yetenek(ad="x", klasor=Path(_GECICI), manifest={"ad": "x", "izinler": ["anahtar:ANTHROPIC_API_KEY",
                                                                                  "anahtar:HF_TOKEN", "anahtar:CAFER_TOKEN"]})
        with mock.patch.dict(os.environ, {"ANTHROPIC_API_KEY": "sk", "HF_TOKEN": "hf", "CAFER_TOKEN": "c",
                                          "OPENAI_API_KEY": "o", "RASTGELE": "1"}):
            ortam = calistirici._ortam(y, _GECICI, [], lambda ad: "zincirden" if ad == "HF_TOKEN" else None)
            ortam2 = calistirici._ortam(y, _GECICI, [], lambda ad: "gizli")
        self.assertEqual(ortam["HF_TOKEN"], "zincirden")
        for ad in ("ANTHROPIC_API_KEY", "CAFER_TOKEN", "OPENAI_API_KEY", "RASTGELE"):
            self.assertNotIn(ad, ortam, ad)
            self.assertNotIn(ad, ortam2, ad)
        self.assertEqual(ortam["HOME"], _GECICI)
        self.assertIn("PYTHONPATH", ortam)


class TarayiciCekirdekte(unittest.TestCase):
    def test_cekirdek_browser_modulunu_ice_aktarmaz(self):
        desen = re.compile(r"^\s*(from\s+(\.\.\.|asistan)\s+import\s+.*\bbrowser\b|import\s+asistan\.browser)", re.M)
        bulunan = []
        for dosya in sorted((KOK / "asistan" / "cekirdek").rglob("*.py")):
            for e in desen.finditer(dosya.read_text(encoding="utf-8")):
                bulunan.append(f"{dosya.relative_to(KOK)}: {e.group(0).strip()}")
        self.assertEqual(bulunan, [], "\n".join(bulunan))

    def test_tarayici_hazir_playwright_yokken_yanlis(self):
        with mock.patch.object(profil, "find_spec", return_value=None):
            self.assertFalse(profil.tarayici_hazir())
        with mock.patch.object(profil, "acik_mi", return_value=False):
            self.assertFalse(profil.tarayici_hazir())


if __name__ == "__main__":
    unittest.main()
