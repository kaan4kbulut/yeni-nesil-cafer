"""K6 — `yetenek/yukleyici.py` (kurulum tek araç yolundan, politika, MCP allowlist) ve `yetenek/uretici.py` (sahte kod
ajanıyla uçtan uca: manifest → kod → gerçek sandbox venv'inde test → onay → kayıt; 3 tur; taslak temizliği)."""

import json
import os
import sys
import tempfile
import textwrap
import unittest
from pathlib import Path
from unittest import mock

KOK = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(KOK))
_GECICI = tempfile.mkdtemp(prefix="yeni-nesil-cafer-test-")
os.environ["XDG_CONFIG_HOME"] = str(Path(_GECICI) / "ayar")
os.environ["XDG_DATA_HOME"] = str(Path(_GECICI) / "veri")

from asistan.cekirdek import guvenlik  # noqa: E402
from asistan.cekirdek.gorev import Cevap  # noqa: E402
from asistan.cekirdek.yetenek import YetenekHatasi, calistirici, uretici, yukleyici  # noqa: E402

ORTAMLAR = Path(_GECICI) / "ortamlar"


class Yukleyici(unittest.TestCase):
    def test_hedef_coz(self):
        self.assertEqual(yukleyici.hedef_coz("pip:openpyxl"), ("pip", "openpyxl"))
        self.assertEqual(yukleyici.hedef_coz("ikili:ffmpeg"), ("ikili", "ffmpeg"))
        self.assertEqual(yukleyici.hedef_coz("x"), ("", "x"))

    def test_pip_tek_arac_yolundan(self):
        cagrilar = []
        with mock.patch.object(guvenlik, "kurulum", return_value="sor"):
            sonuc = yukleyici.kur("pip:openpyxl>=3", lambda ad, a: cagrilar.append((ad, a)) or "kuruldu", "tablo için")
        self.assertEqual(sonuc, "kuruldu")
        self.assertEqual(cagrilar, [("install_python_package", {"packages": "openpyxl>=3", "purpose": "tablo için"})])
        with self.assertRaises(YetenekHatasi):
            yukleyici.kur("pip:rm -rf /", lambda *a: "x")
        with mock.patch.object(guvenlik, "kurulum", return_value="yasak"):
            with self.assertRaises(YetenekHatasi) as c:
                yukleyici.kur("pip:openpyxl", lambda *a: "x")
            self.assertEqual(c.exception.sinif, "izin")
        with self.assertRaises(YetenekHatasi) as c:  # komut satırı programı: kullanıcıya bırakılır
            yukleyici.kur("ikili:ffmpeg", lambda *a: "x")
        self.assertEqual(c.exception.sinif, "izin")

    def test_mcp_allowlist(self):
        dosya = Path(_GECICI) / "mcp.json"
        with mock.patch.object(guvenlik, "kurulum", return_value="sor"):
            m = yukleyici.mcp_ekle("zaman", {"command": "uvx", "args": ["mcp-server-time"]}, dosya)
            self.assertIn("eklendi", m)
            self.assertEqual(json.loads(dosya.read_text())["mcpServers"]["zaman"]["args"], ["mcp-server-time"])
            self.assertIn("zaten", yukleyici.mcp_ekle("zaman", {"command": "uvx", "args": ["mcp-server-time"]}, dosya))
            for tanim in ({"command": "bash", "args": ["-c", "x"]}, {"command": "npx", "args": ["-y", "kotu-paket"]},
                          {"command": "uvx", "args": []}):
                with self.assertRaises(YetenekHatasi, msg=tanim):
                    yukleyici.mcp_ekle("k", tanim, dosya)
            self.assertIn("eklendi", yukleyici.mcp_ekle("dosya", {"command": "npx", "args": ["-y", "@modelcontextprotocol/server-filesystem"]}, dosya))


MANIFEST = {"aciklama": "Metni büyük harfe çevirir.",
            "girdi": [{"ad": "metin", "tip": "string", "zorunlu": True, "aciklama": "metin"}],
            "cikti": [{"ad": "sonuc", "tip": "string", "aciklama": "büyük harfli"}],
            "izinler": [], "pip": [],
            "ornekler": [{"girdi": {"metin": "abc"}, "beklenen": "ABC"}, {"girdi": {}, "beklenen": "veri hatası"}]}
DOGRU = textwrap.dedent('''
    """buyuk_harf: metni büyük harfe çevirir."""
    from asistan.cekirdek.yetenek import YetenekHatasi, gerekli


    def calistir(girdi: dict, baglam) -> dict:
        gerekli(girdi, "metin")
        return {"sonuc": str(girdi["metin"]).upper()}
''')
BOZUK = DOGRU.replace('{"sonuc": str(girdi["metin"]).upper()}', '{"sonuc": str(girdi["metin"]).lower()}')
TEST = textwrap.dedent('''
    import importlib.util, os, unittest, logging, tempfile, types
    yol = os.path.join(os.path.dirname(os.path.abspath(__file__)), "calistir.py")
    spec = importlib.util.spec_from_file_location("c", yol); c = importlib.util.module_from_spec(spec); spec.loader.exec_module(c)
    from asistan.cekirdek.yetenek import YetenekHatasi
    B = types.SimpleNamespace(calisma_klasoru=tempfile.mkdtemp(), kademe="orta", gunluk=logging.getLogger("t"), okuma_kokleri=(), ayar={})

    class T(unittest.TestCase):
        def test_ornek(self):
            self.assertEqual(c.calistir({"metin": "abc"}, B), {"sonuc": "ABC"})
        def test_eksik(self):
            with self.assertRaises(YetenekHatasi):
                c.calistir({}, B)

    if __name__ == "__main__":
        unittest.main()
''')


class SahteKodAjani:
    """planlama → manifest; kod → sırayla verilen calistir.py sürümleri (test hep aynı)."""

    def __init__(self, kodlar):
        self.kodlar, self.cagrilar = list(kodlar), []

    def __call__(self, rol, mesajlar, sistem="", sema=None):
        self.cagrilar.append((rol, len(mesajlar)))
        self.son = list(mesajlar)
        if rol == "planlama":
            return Cevap(json.dumps(MANIFEST), MANIFEST, {"model": "sahte"})
        kod = self.kodlar.pop(0) if self.kodlar else None
        if kod is None:
            return Cevap("(boş)", None, {"model": "sahte"}, ["$: JSON nesnesi yok"])
        veri = {"calistir_py": kod, "test_py": TEST}
        return Cevap(json.dumps(veri), veri, {"model": "sahte"})


class Uretici(unittest.TestCase):
    def setUp(self):
        self.kok = Path(tempfile.mkdtemp(dir=_GECICI)) / "yetenekler"
        p = mock.patch.object(calistirici, "ortam_koku", lambda: ORTAMLAR)
        p.start()
        self.addCleanup(p.stop)

    def uret(self, kodlar, **k):
        m = SahteKodAjani(kodlar)
        s = uretici.uret("buyuk_harf", "metni büyük harfe çevir", m, kok=self.kok, kademe="orta",
                         python=sys.executable, **k)
        return s, m

    def test_ilk_turda_gecer_onay_kayit(self):
        onaylar = []
        s, m = self.uret([DOGRU], sor=lambda ozet: onaylar.append(ozet) or True)
        self.assertIsNotNone(s.yetenek, s.rapor)
        self.assertTrue(s.yetenek.aktif, s.yetenek.neden)
        self.assertEqual((s.yetenek.kaynak, s.yetenek.guvenilir, s.yetenek.sandbox), ("uretildi", False, True))
        self.assertTrue((self.kok / "buyuk_harf" / "test_buyuk_harf.py").is_file())
        self.assertFalse((self.kok / ".taslak").exists())
        self.assertIn("calistir.py", onaylar[0])
        self.assertEqual([r for r, _ in m.cagrilar], ["planlama", "kod"])
        # üretilen yetenek gerçek sandbox'ta çalışır
        from asistan.cekirdek.yetenek import Baglam

        cikti = calistirici.calistir(s.yetenek, {"metin": "selam"}, Baglam(calisma_klasoru=_GECICI), python=sys.executable)
        self.assertEqual(cikti, {"sonuc": "SELAM"})

    def test_bozuk_kod_ikinci_turda_duzelir(self):
        s, m = self.uret([BOZUK, DOGRU], sor=lambda _: True)
        self.assertIsNotNone(s.yetenek, s.rapor)
        self.assertEqual(s.tur, 3)
        self.assertEqual([r for r, _ in m.cagrilar], ["planlama", "kod", "kod"])
        self.assertGreater(m.cagrilar[-1][1], m.cagrilar[-2][1])  # hata metni bağlama eklendi

    def test_uc_tur_gecmezse_vazgecer_taslak_silinir(self):
        s, m = self.uret([BOZUK, BOZUK, BOZUK], sor=lambda _: True)
        self.assertIsNone(s.yetenek)
        self.assertIn("yapamadım", s.rapor)
        self.assertFalse((self.kok / ".taslak").exists())
        self.assertFalse((self.kok / "buyuk_harf").exists())
        self.assertEqual(len([r for r, _ in m.cagrilar if r == "kod"]), 3)

    def test_onay_yoksa_taslak_kalir_kaydet_ile_tasinir(self):
        s, _ = self.uret([DOGRU])  # sor=None
        self.assertTrue(s.onay_bekliyor)
        self.assertTrue((self.kok / ".taslak" / "buyuk_harf" / "calistir.py").is_file())
        y = uretici.kaydet(s.klasor, self.kok)
        self.assertTrue(y.aktif)
        self.assertTrue((self.kok / "buyuk_harf" / "manifest.json").is_file())
        s2, _ = self.uret([DOGRU], sor=lambda _: False)  # reddedilirse silinir, eski kalır
        self.assertIsNone(s2.yetenek)
        self.assertTrue((self.kok / "buyuk_harf" / "manifest.json").is_file())

    def test_guncelle(self):
        self.uret([DOGRU], sor=lambda _: True)
        m = SahteKodAjani([DOGRU])
        s = uretici.guncelle("buyuk_harf", "aynı işi yap", m, kok=self.kok, sor=lambda _: True, python=sys.executable)
        self.assertIsNotNone(s.yetenek, s.rapor)
        self.assertTrue((self.kok / "buyuk_harf.eski").is_dir())
        self.assertIn("Existing files", m.son[0]["content"])  # mevcut dosyalar bağlam olarak verildi
        self.assertIsNone(uretici.guncelle("yok", "x", m, kok=self.kok).yetenek)


if __name__ == "__main__":
    unittest.main()
