"""install_app (apps.py): yönetici izni olmadan uygulama kurma. İnternete gidilmez (GitHub ve indirme sahte).

Çalıştırma (proje kökünde, programın Python'uyla):
    ~/.local/share/yeni-nesil-cafer-app/python/bin/python3 -m unittest discover -s testler -v
"""

import sys
import tempfile
import unittest
from contextlib import contextmanager
from pathlib import Path
from unittest import mock

KOK = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(KOK))

from asistan import apps, security  # noqa: E402
from asistan import permissions as p  # noqa: E402

SURUMLER = [{"draft": False, "assets": [
    {"name": "Orca-aarch64.AppImage", "browser_download_url": "https://github.com/x/arm"},
    {"name": "OrcaSlicer_Linux_AppImage_Ubuntu2404_x86_64.AppImage", "browser_download_url": "https://github.com/x/uzun"},
    {"name": "OrcaSlicer-x86_64.AppImage", "browser_download_url": "https://github.com/x/dogru"},
    {"name": "OrcaSlicer-x86_64.zip", "browser_download_url": "https://github.com/x/zip"}]}]


class _Yanit:
    def __init__(self, status, body=None, data=b""):
        self.status_code, self.body, self.data = status, body, data
        self.headers = {"content-length": str(len(data))}

    def json(self):
        return self.body

    def iter_bytes(self, n):
        yield self.data


class UygulamaTesti(unittest.TestCase):
    def setUp(self):
        d = Path(tempfile.mkdtemp(prefix="uygulama-"))
        self.patches = [mock.patch.object(apps, "APPS_DIR", d / "Applications"),
                        mock.patch.object(apps, "DESKTOP_DIR", d / "applications"),
                        mock.patch.object(apps, "_ARCH", ("x86_64", "amd64", "x64")),
                        mock.patch.object(apps, "_runs", return_value=False),
                        mock.patch.object(apps.sys, "platform", "linux")]  # AppImage yolu her sistemde denensin
        for x in self.patches:
            x.start()
        self.d = d

    def tearDown(self):
        for x in self.patches:
            x.stop()

    def test_github_dogru_dosyayi_secer(self):
        with mock.patch.object(apps.httpx, "get", return_value=_Yanit(200, SURUMLER)):
            url, name = apps.github_appimage("https://github.com/SoftFever/OrcaSlicer")
        self.assertEqual((url, name), ("https://github.com/x/dogru", "OrcaSlicer-x86_64.AppImage"))
        with self.assertRaises(apps.AppError):
            apps.github_appimage("bu bir depo değil")

    def test_appimage_kurulur_ve_menuye_eklenir(self):
        @contextmanager
        def indir(*a, **k):
            yield _Yanit(200, data=b"\x7fELF" + b"\x00" * 100)

        with mock.patch.object(apps.httpx, "stream", side_effect=indir):
            out = apps.install("OrcaSlicer", "https://orca.example.org/Orca.AppImage")
        app = self.d / "Applications" / "orcaslicer.AppImage"
        self.assertTrue(app.stat().st_mode & 0o100)  # çalıştırılabilir
        desktop = (self.d / "applications" / "orcaslicer.desktop").read_text()
        self.assertIn("--appimage-extract-and-run", desktop)  # FUSE yok: çıkarıp çalıştır
        self.assertIn("Installed OrcaSlicer", out)

    def test_html_sayfasi_ve_http_reddedilir(self):
        @contextmanager
        def sayfa(*a, **k):
            yield _Yanit(200, data=b"<!DOCTYPE html>")

        with mock.patch.object(apps.httpx, "stream", side_effect=sayfa):
            with self.assertRaises(apps.AppError):
                apps.install_appimage("X", "https://ornek.org/x.AppImage")
        self.assertFalse(list((self.d / "Applications").glob("*.AppImage")))
        with self.assertRaises(apps.AppError):
            apps.install_appimage("X", "http://ornek.org/x.AppImage")

    def test_flatpak_yoksa_kaynak_istenir(self):
        with mock.patch.object(apps.sys, "platform", "linux"), mock.patch.object(apps.shutil, "which",
                                                                                 return_value=None):
            with self.assertRaises(apps.AppError) as e:
                apps.install("OrcaSlicer")
        self.assertIn("AppImage", str(e.exception))


class GuvenlikTesti(unittest.TestCase):
    def test_risk_seviyeleri_ve_onay(self):
        ws = tempfile.mkdtemp()
        self.assertEqual(security.classify("install_app", {"name": "Orca", "source": "SoftFever/OrcaSlicer"}, ws)[0],
                         security.MEDIUM)
        self.assertEqual(security.classify("install_app", {"name": "X", "source": "https://bilinmeyen.site/x.AppImage"},
                                           ws)[0], security.HIGH)
        # bilinen yayıncı listesinde olmayan GitHub hesabı (taklit ad) de yüksek risk
        self.assertEqual(security.classify("install_app", {"name": "Orca", "source": "kotuadam/orcaslicer-hizli"}, ws)[0],
                         security.HIGH)
        self.assertEqual(security.classify("install_app", {"name": "Krita", "source": "com.krita.Krita"}, ws)[0],
                         security.MEDIUM)  # paket yöneticisi kimliği
        self.assertEqual(p.decide("install_app", {"name": "Orca"}, p.Context(approval_mode="guvenlik")).kind,
                         p.REVIEW)  # güvenlik ajanı denetler
        self.assertEqual(p.decide("install_app", {"name": "Orca"}, p.Context()).kind, p.ASK)  # kullanıcıya sorulur


if __name__ == "__main__":
    unittest.main()
