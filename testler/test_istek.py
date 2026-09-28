"""İstek çalıştırma (`asistan.cekirdek.istek`): ajan kurulumu (onay kipi × ▶ × sansürsüz × öneri, iş klasörü,
beceriler) ve sonucun arayüze dönüşü. Davranış K1'den önce `gui/window_run.py` ve `gui/worker.py`'deydi.

Çalıştırma (proje kökünde, programın Python'uyla):
    ~/.local/share/yeni-nesil-cafer-app/python/bin/python3 -m unittest discover -s testler -v
"""

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

from asistan import learning, manager  # noqa: E402
from asistan.cekirdek import istek  # noqa: E402
from asistan.cekirdek.saglayici import Iptal  # noqa: E402
from asistan.config import Settings  # noqa: E402


def baglam(metin="bir dosya yaz", kip="kullanici", **k) -> istek.IstekBaglami:
    ana = str(Path(_GECICI) / "calisma")
    return istek.IstekBaglami(metin=metin, ayarlar=Settings(workspace=ana, approval_mode=kip), **k)


class AjanHazirlaTesti(unittest.TestCase):
    def setUp(self):
        yama = mock.patch.object(learning, "find_skills", return_value=[])
        yama.start()
        self.addCleanup(yama.stop)

    def test_onay_kipleri(self):
        durumlar = [  # (kip, metin, sansürsüz) → (gate_actions, must_act)
            ("guvenlik", "dosya yaz", False, (False, False)),
            ("guvenlik", "▶ dosya yaz", False, (False, False)),
            ("kullanici", "dosya yaz", False, (True, False)),
            ("kullanici", "▶ dosya yaz", False, (False, True)),
            ("kullanici", "dosya yaz", True, (False, False)),
            ("kullanici", "▶ dosya yaz", True, (False, True)),
        ]
        for kip, metin, sansursuz, beklenen in durumlar:
            with self.subTest(kip=kip, metin=metin, sansursuz=sansursuz):
                ajan, _ = istek.ajan_hazirla(baglam(metin, kip, sansursuz=sansursuz))
                self.assertEqual((ajan.gate_actions, ajan.must_act), beklenen)
                self.assertEqual(istek.SANSURSUZ_NOTU in (ajan.extra_system or ""), sansursuz)

    def test_yalnizca_oneri_istenince_dokunmaz(self):
        ajan, _ = istek.ajan_hazirla(baglam("bilgisayarımı hızlandırmak için ne önerirsin?", "guvenlik"))
        self.assertIn(istek.ONERI_NOTU, ajan.extra_system)
        ajan, _ = istek.ajan_hazirla(baglam("bilgisayarımı hızlandırmak için ne önerirsin?", "kullanici"))
        self.assertNotIn(istek.ONERI_NOTU, ajan.extra_system or "")
        ajan, _ = istek.ajan_hazirla(baglam("klasörü düzenle, ne önerirsin?", "guvenlik"))  # eylem de var
        self.assertNotIn(istek.ONERI_NOTU, ajan.extra_system or "")

    def test_is_klasoru_ve_devam_eden_proje(self):
        is_ = str(Path(_GECICI) / "calisma" / "Genel" / "deneme-1")
        with mock.patch.object(learning, "project_note", return_value="\n[proje notu]") as not_:
            ajan, _ = istek.ajan_hazirla(baglam(is_klasoru=is_, devam_projesi={"title": "Deneme"},
                                                her_zaman_izinli=True, cli_modeli="opus"))
        ana = (Path(_GECICI) / "calisma").resolve()
        self.assertEqual(ajan.toolbox.root, Path(is_).resolve())
        self.assertIn(ana, ajan.toolbox.read_roots)  # diğer işler salt okunur
        self.assertIn("belongs only to this conversation", ajan.extra_system)
        self.assertTrue(ajan.extra_system.endswith("[proje notu]"))
        not_.assert_called_once_with({"title": "Deneme"})
        self.assertTrue(ajan.always_allowed)
        self.assertEqual(ajan.cli_model, "opus")

    def test_ana_klasorde_not_yok(self):
        ajan, _ = istek.ajan_hazirla(baglam())
        self.assertNotIn("belongs only to this conversation", ajan.extra_system or "")

    def test_beceriler_eklenir(self):
        beceri = [{"id": "b1", "title": "PDF birleştir"}]
        with mock.patch.object(learning, "find_skills", return_value=beceri), \
                mock.patch.object(learning, "skills_prompt", return_value="\n[beceri]"):
            ajan, bulunan = istek.ajan_hazirla(baglam("iki pdf'i birleştir"))
            self.assertEqual(bulunan, beceri)
            self.assertTrue(ajan.extra_system.endswith("[beceri]"))
            _, bulunan = istek.ajan_hazirla(baglam("📈 gelişim raporu"))
            self.assertEqual(bulunan, [])


class CalistirTesti(unittest.TestCase):
    def test_sonuclar(self):
        with mock.patch.object(learning, "find_skills", return_value=[]):
            ajan, _ = istek.ajan_hazirla(baglam())
        with mock.patch.object(manager.Manager, "run") as run:
            self.assertEqual(istek.istegi_calistir(ajan, "ollama", [], "selam").durum, "tamam")
        run.assert_called_once_with("ollama", [], "selam")
        with mock.patch.object(manager.Manager, "run", side_effect=Iptal()):
            self.assertEqual(istek.istegi_calistir(ajan, "ollama", [], "selam").durum, "durduruldu")
        with mock.patch.object(manager.Manager, "run", side_effect=RuntimeError("model yok")):
            sonuc = istek.istegi_calistir(ajan, "ollama", [], "selam")
        self.assertEqual((sonuc.durum, sonuc.hata), ("hata", "RuntimeError: model yok"))
        with mock.patch.object(manager.Manager, "run", side_effect=RuntimeError("model yok")):
            with self.assertRaises(RuntimeError):  # bulut sunucu hatayı kendisi ele alır
                istek.calistir(ajan, "ollama", [], "selam")


if __name__ == "__main__":
    unittest.main()
