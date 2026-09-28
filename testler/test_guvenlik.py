"""K6 — `cekirdek/guvenlik.py` + `ayar/guvenlik.toml`: politika okuma (toml ← ayar.toml ← CAFER_GUVENLIK_*), kurulum
yasak/otomatik/sor, ağ "sor", kaynak allowlist, sandbox süresi; `permissions.decide` politikayı uygular (ikinci onay yolu yok)."""

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

from asistan import permissions  # noqa: E402
from asistan.cekirdek import ayar, guvenlik, profil  # noqa: E402
from asistan.cekirdek.yetenek import calistirici  # noqa: E402


def ortam(**k):
    return mock.patch.dict(os.environ, {f"CAFER_GUVENLIK_{a.upper()}": v for a, v in k.items()})


class Politika(unittest.TestCase):
    def test_varsayilanlar_dosyadan(self):
        p = guvenlik.politika()
        self.assertEqual((p["kurulum"], p["ag"], p["dosya_silme"]), ("sor", "serbest", "sor"))
        self.assertEqual(p["sandbox_zaman_asimi_sn"], 60)
        self.assertIn("pypi", p["kaynaklar"])
        self.assertTrue(guvenlik.kaynak_izinli("PyPI"))
        self.assertFalse(guvenlik.kaynak_izinli("https://rastgele.site/kur.sh"))

    def test_ayar_toml_ve_ortam_ezer(self):
        ayar.CONFIG_DIR.mkdir(parents=True, exist_ok=True)
        (ayar.CONFIG_DIR / "ayar.toml").write_text('[guvenlik]\nkurulum = "yasak"\nsandbox_zaman_asimi_sn = 15\n',
                                                   encoding="utf-8")
        try:
            self.assertEqual(guvenlik.politika()["kurulum"], "yasak")
            self.assertEqual(guvenlik.sandbox_zaman_asimi(), 15)
            self.assertEqual(calistirici.ust_zaman_siniri(), 15)
            with ortam(kurulum="otomatik", ag="sor"):
                self.assertEqual(guvenlik.politika()["kurulum"], "otomatik")
                self.assertEqual(guvenlik.politika()["ag"], "sor")
            with ortam(kurulum="saçma"):
                self.assertEqual(guvenlik.politika()["kurulum"], "sor")  # bilinmeyen değer → güvenli varsayılan
        finally:
            (ayar.CONFIG_DIR / "ayar.toml").unlink()

    def test_otomatik_kurulum_dusuk_kademede_ve_sunucuda_sor(self):
        with ortam(kurulum="otomatik"), mock.patch.object(profil, "kademe", return_value="dusuk"):
            self.assertEqual(guvenlik.kurulum(), "sor")
        with ortam(kurulum="otomatik"), mock.patch.object(profil, "kademe", return_value="yuksek"), \
                mock.patch.object(profil, "basliksiz", return_value=False):
            self.assertEqual(guvenlik.kurulum(), "otomatik")


class IzinHattiUygular(unittest.TestCase):
    """Politika permissions.decide içinde uygulanır: yasak → DENY, otomatik → ALLOW, sor → hat kuralı; ag sor → ASK."""

    K = permissions.Context(approval_mode="kullanici", confirm_commands=True)
    KUR = ("install_python_package", {"packages": "openpyxl", "purpose": "t"})

    def test_kurulum(self):
        with mock.patch.object(profil, "kademe", return_value="yuksek"), mock.patch.object(profil, "basliksiz", return_value=False):
            self.assertEqual(permissions.decide(*self.KUR, self.K).kind, permissions.ASK)
            with ortam(kurulum="yasak"):
                d = permissions.decide(*self.KUR, self.K)
                self.assertEqual(d.kind, permissions.DENY)
                self.assertIn("politika", d.reason)
                g = permissions.Context(approval_mode="guvenlik")
                self.assertEqual(permissions.decide(*self.KUR, g).kind, permissions.DENY)  # güvenlik ajanı da geçemez
            with ortam(kurulum="otomatik"):
                self.assertEqual(permissions.decide(*self.KUR, self.K).kind, permissions.ALLOW)
                bekle = permissions.Context(approval_mode="kullanici", gate_actions=True)
                self.assertEqual(permissions.decide(*self.KUR, bekle).kind, permissions.PENDING)  # ✓ turu yine bekler

    def test_ag_ve_silme(self):
        self.assertEqual(permissions.decide("web_search", {"query": "x"}, self.K).kind, permissions.ALLOW)
        with ortam(ag="sor"):
            self.assertEqual(permissions.decide("web_search", {"query": "x"}, self.K).kind, permissions.ASK)
            self.assertEqual(permissions.decide("read_file", {"path": "a"}, self.K).kind, permissions.ALLOW)
        with ortam(dosya_silme="yasak"):
            self.assertEqual(guvenlik.karar("delete_file", {})[0], "yasak")
            self.assertEqual(guvenlik.karar("y_x", {}, izinler=["dosya_sil"])[0], "yasak")
        self.assertEqual(guvenlik.karar("read_file", {}), (None, ""))


if __name__ == "__main__":
    unittest.main()
