"""K5 — yetenek kayıt defteri (`asistan/cekirdek/yetenek/`): manifest şeması (SEMALAR §1), bozuk manifest → pasif,
gereksinim denetimi, sandbox (ayrı venv, zaman aşımı, izin dışı dosya / ağ / komut / anahtar erişimi engeli), görev
motorunun uyarlayıcısı (izin hattı, eski araç adları) ve planlayıcının listeyi yalnızca manifestlerden alması.
Ayrıca her yeteneğin kendi `test_<ad>.py` dosyası buradan koşulur (unittest `-s testler` onları görmez).

Çalıştırma (proje kökünde, programın Python'uyla):
    ~/.local/share/yeni-nesil-cafer-app/python/bin/python3 -m unittest discover -s testler -v
"""

import json
import os
import re
import sys
import tempfile
import time
import unittest
from pathlib import Path

KOK = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(KOK))
_GECICI = tempfile.mkdtemp(prefix="yeni-nesil-cafer-test-")
os.environ["XDG_CONFIG_HOME"] = str(Path(_GECICI) / "ayar")
os.environ["XDG_DATA_HOME"] = str(Path(_GECICI) / "veri")

from asistan.cekirdek import semalar  # noqa: E402
from asistan.cekirdek.gorev import Cevap, ModelYok, durum, yurutucu  # noqa: E402
from asistan.cekirdek.yetenek import Baglam, YetenekHatasi, calistirici, cikti_metni, nesne_semasi  # noqa: E402
from asistan.cekirdek.yetenek.kayit import YERLESIK_KOK, Kayit, surum_uyar  # noqa: E402

ORTAMLAR = Path(_GECICI) / "ortamlar"
YERLESIKLER = {"dosya_listele", "dosya_oku", "dosya_ara", "dosya_yaz", "dosya_duzenle", "dosya_tasi", "komut_calistir",
               "python_calistir", "web_arama", "web_oku", "tarayici", "metin_istatistik"}


def manifest(ad: str, **ek) -> dict:
    m = {"ad": ad, "surum": "1.0.0", "aciklama": "deneme", "girdi": {"yol": {"tip": "string"}},
         "cikti": {"sonuc": {"tip": "string"}}, "gereksinimler": {}, "izinler": [], "zaman_asimi_sn": 10,
         "sandbox": True, "kaynak": "uretildi", "guvenilir": False}
    m.update(ek)
    return m


def yetenek_yaz(kok: Path, ad: str, kod: str, manifest_=None, ham: str | None = None) -> Path:
    klasor = kok / ad
    klasor.mkdir(parents=True, exist_ok=True)
    (klasor / "manifest.json").write_text(ham if ham is not None else json.dumps(manifest_ or manifest(ad)),
                                          encoding="utf-8")
    if kod is not None:
        (klasor / "calistir.py").write_text(kod, encoding="utf-8")
    return klasor


# ---------------------------------------------------------------- şema

class ManifestSemasiTesti(unittest.TestCase):
    def test_semalar_md_ornegi_gecerli(self):
        metin = (KOK / "docs" / "SEMALAR.md").read_text(encoding="utf-8")
        ornek = json.loads(re.search(r"## 1\..*?```json\n(.*?)```", metin, re.S).group(1))
        self.assertEqual(semalar.dogrula(ornek, semalar.yukle("manifest")), [])

    def test_yerlesikler_gecerli(self):
        kayit = Kayit([YERLESIK_KOK], kademe="yuksek")
        adlar = {y.ad for y in kayit.tara()}
        self.assertTrue(YERLESIKLER <= adlar, YERLESIKLER - adlar)
        for y in kayit.tara():
            self.assertEqual(y.hatalar, [], y.ad)
            self.assertEqual(y.kaynak, "yerlesik", y.ad)
            self.assertGreaterEqual(len(y.manifest.get("ornekler") or []), 2, y.ad)
            self.assertTrue((y.klasor / f"test_{y.ad}.py").exists(), y.ad)

    def test_dogrulayici_yeni_anahtarlar(self):
        sema = {"type": "object", "additionalProperties": {"type": "integer", "maximum": 5},
                "properties": {"ad": {"type": "string", "pattern": "^[a-z]+$"}}}
        self.assertEqual(semalar.dogrula({"ad": "abc", "x": 3}, sema), [])
        hatalar = semalar.dogrula({"ad": "A1", "x": 9, "y": "metin"}, sema)
        self.assertEqual(len(hatalar), 3, hatalar)

    def test_manifest_alanlari_sema_olur(self):
        sema = nesne_semasi({"a": {"tip": "int", "zorunlu": True}, "b": {"tip": "list", "eleman": {"k": "string"}},
                             "c": {"tip": "string", "secenekler": ["x", "y"]}})
        self.assertEqual(sema["required"], ["a"])
        self.assertEqual(sema["properties"]["b"]["items"]["properties"]["k"]["type"], "string")
        self.assertEqual(sema["properties"]["c"]["enum"], ["x", "y"])

    def test_surum_kosulu(self):
        self.assertTrue(surum_uyar("0.28.1", ">=0.27"))
        self.assertFalse(surum_uyar("0.26", ">=0.27"))
        self.assertTrue(surum_uyar("1.5", ">=1,<2"))
        self.assertFalse(surum_uyar("2.0", ">=1,<2"))


# ---------------------------------------------------------------- kayıt: aktif / pasif

class KayitTesti(unittest.TestCase):
    def setUp(self):
        self.kok = Path(tempfile.mkdtemp(dir=_GECICI))
        self.iyi = "def calistir(girdi, baglam):\n    return {'sonuc': 'ok'}\n"

    def kayit(self, kademe="orta", kokler=None):
        return Kayit(kokler or [self.kok], kademe=kademe)

    def pasif_mi(self, ad: str, parca: str, kademe="orta"):
        y = self.kayit(kademe).getir(ad)
        self.assertIsNotNone(y, ad)
        self.assertFalse(y.aktif, ad)
        self.assertIn(parca, y.neden)
        return y

    def test_saglam_yetenek_aktif(self):
        yetenek_yaz(self.kok, "saglam", self.iyi)
        y = self.kayit().getir("saglam")
        self.assertTrue(y.aktif, y.neden)
        self.assertEqual(y.risk(), "calistirir")  # üretilmiş, güvenilmez: her seferinde onay

    def test_bozuk_json_pasif(self):
        yetenek_yaz(self.kok, "bozuk", self.iyi, ham="{ad: bozuk")
        self.pasif_mi("bozuk", "manifest bozuk")

    def test_eksik_alan_pasif(self):
        m = manifest("eksik")
        del m["izinler"]
        yetenek_yaz(self.kok, "eksik", self.iyi, m)
        y = self.pasif_mi("eksik", "manifest geçersiz")
        self.assertTrue(any("izinler" in h for h in y.hatalar))

    def test_gecersiz_izin_ve_ad(self):
        yetenek_yaz(self.kok, "izin", self.iyi, manifest("izin", izinler=["her_sey"]))
        self.pasif_mi("izin", "manifest geçersiz")
        yetenek_yaz(self.kok, "farkli", self.iyi, manifest("baska_ad"))
        self.pasif_mi("farkli", "klasör adıyla")

    def test_calistir_yoksa_ya_da_islevsizse_pasif(self):
        yetenek_yaz(self.kok, "kodsuz", None)
        self.pasif_mi("kodsuz", "calistir.py yok")
        yetenek_yaz(self.kok, "islevsiz", "def baska():\n    pass\n")
        self.pasif_mi("islevsiz", "işlevi yok")
        yetenek_yaz(self.kok, "derlenmez", "def calistir(:\n")
        self.pasif_mi("derlenmez", "derlenmiyor")

    def test_ornek_semaya_uymazsa_pasif(self):
        m = manifest("ornekli", girdi={"n": {"tip": "int", "zorunlu": True}},
                     ornekler=[{"girdi": {"n": "üç"}, "beklenen": "x"}])
        yetenek_yaz(self.kok, "ornekli", self.iyi, m)
        self.pasif_mi("ornekli", "ornekler[0]")

    def test_gereksinimler(self):
        yetenek_yaz(self.kok, "paketli", self.iyi, manifest("paketli", gereksinimler={"pip": ["yok-boyle-paket-k5"]}))
        self.pasif_mi("paketli", "kurulu değil: yok-boyle-paket-k5")
        yetenek_yaz(self.kok, "ikili", self.iyi, manifest("ikili", gereksinimler={"ikili": ["yok-boyle-program-k5"]}))
        self.pasif_mi("ikili", "programı kurulu değil")
        yetenek_yaz(self.kok, "agir", self.iyi, manifest("agir", gereksinimler={"min_kademe": "yuksek"}))
        self.pasif_mi("agir", "kademe")
        self.assertTrue(self.kayit("yuksek").getir("agir").aktif)
        baska = "windows" if sys.platform != "win32" else "linux"
        yetenek_yaz(self.kok, "isletim", self.iyi, manifest("isletim", gereksinimler={"isletim": [baska]}))
        self.pasif_mi("isletim", "işletim sisteminde")

    def test_guven_kurallari(self):
        yetenek_yaz(self.kok, "sahte_yerlesik", self.iyi, manifest("sahte_yerlesik", kaynak="yerlesik", guvenilir=True))
        self.pasif_mi("sahte_yerlesik", "'yerlesik' olamaz")
        yetenek_yaz(self.kok, "sandboxsuz", self.iyi, manifest("sandboxsuz", sandbox=False))
        self.pasif_mi("sandboxsuz", "sandbox dışında")

    def test_ayni_ad_ikinci_kok_pasif(self):
        yetenek_yaz(self.kok, "dosya_oku", self.iyi)  # üretilen yetenek yerleşiği ezemez
        kayit = Kayit([YERLESIK_KOK, self.kok], kademe="orta")
        aktif = [y for y in kayit.tara() if y.ad == "dosya_oku" and y.aktif]
        self.assertEqual(len(aktif), 1)
        self.assertEqual(aktif[0].kaynak, "yerlesik")
        self.assertEqual(kayit.getir("dosya_oku").kaynak, "yerlesik")

    def test_planlayici_listesi_yalnizca_aktifler(self):
        yetenek_yaz(self.kok, "saglam", self.iyi)
        yetenek_yaz(self.kok, "kodsuz", None)
        adlar = [y["ad"] for y in self.kayit().planlayici_listesi()]
        self.assertEqual(adlar, ["saglam"])


# ---------------------------------------------------------------- sandbox

class SandboxTesti(unittest.TestCase):
    def setUp(self):
        self.kok = Path(tempfile.mkdtemp(dir=_GECICI))
        self.calisma = Path(tempfile.mkdtemp(dir=_GECICI))
        (self.calisma / "not.txt").write_text("merhaba", encoding="utf-8")
        self.disari = Path(tempfile.mkdtemp())  # çalışma klasörü ve okuma kökleri dışında
        (self.disari / "gizli.txt").write_text("gizli", encoding="utf-8")

    def calistir(self, ad: str, kod: str, veri=None, **m):
        yetenek_yaz(self.kok, ad, kod, manifest(ad, **m))
        y = Kayit([self.kok], kademe="orta").getir(ad)
        self.assertTrue(y.aktif, y.neden)
        return calistirici.calistir(y, veri or {}, Baglam(str(self.calisma)), ortamlar=ORTAMLAR)

    def izin_hatasi(self, ad: str, kod: str, veri=None, **m) -> str:
        with self.assertRaises(YetenekHatasi) as h:
            self.calistir(ad, kod, veri, **m)
        self.assertEqual(h.exception.sinif, "izin", h.exception.mesaj)
        return h.exception.mesaj

    def test_ayri_venv(self):
        sonuc = self.calistir("venvli", "import sys\ndef calistir(g, b):\n    return {'sonuc': sys.prefix}\n")
        self.assertEqual(Path(sonuc["sonuc"]).resolve(), (ORTAMLAR / "venvli").resolve())

    def test_zaman_asimi(self):
        basla = time.monotonic()
        with self.assertRaises(YetenekHatasi) as h:
            self.calistir("uyur", "import time\ndef calistir(g, b):\n    time.sleep(60)\n", zaman_asimi_sn=2)
        self.assertLess(time.monotonic() - basla, 15)
        self.assertEqual(h.exception.sinif, "kaynak")
        self.assertIn("zaman aşımı", h.exception.mesaj)

    def test_izinsiz_okuma_engellenir(self):
        oku = "def calistir(g, b):\n    return {'sonuc': open(g['yol']).read()}\n"
        self.izin_hatasi("okumaz", oku, {"yol": str(self.calisma / "not.txt")})  # dosya_oku yok
        self.izin_hatasi("disari", oku, {"yol": str(self.disari / "gizli.txt")}, izinler=["dosya_oku"])
        self.assertEqual(self.calistir("okur", oku, {"yol": "not.txt"}, izinler=["dosya_oku"]), {"sonuc": "merhaba"})

    def test_izinsiz_yazma_engellenir(self):
        disari = self.disari / "kacak.txt"
        self.izin_hatasi("yazmaz", "def calistir(g, b):\n    open('yeni.txt', 'w').write('x')\n")
        self.izin_hatasi("disari_yaz", f"def calistir(g, b):\n    open({str(disari)!r}, 'w').write('x')\n",
                         izinler=["dosya_yaz"])
        self.assertFalse(disari.exists())
        self.assertFalse((self.calisma / "yeni.txt").exists())
        self.calistir("icer_yaz", "def calistir(g, b):\n    open('yeni.txt', 'w').write('x')\n    return {}\n",
                      izinler=["dosya_yaz"])
        self.assertTrue((self.calisma / "yeni.txt").exists())

    def test_izinsiz_silme_engellenir(self):
        sil = "import os\ndef calistir(g, b):\n    os.remove('not.txt')\n    return {}\n"
        self.izin_hatasi("silmez", sil, izinler=["dosya_oku", "dosya_yaz"])
        self.assertTrue((self.calisma / "not.txt").exists())

    def test_anahtar_dosyasi_hic_okunmaz(self):
        """Çalışma klasörü ev klasörü seçilse bile: ayar klasörü ve adıyla anahtar dosyası (K5 denetimi)."""
        from asistan.cekirdek.ayar import CONFIG_DIR

        (self.calisma / "anahtarlar.json").write_text('{"anthropic": "gizli"}', encoding="utf-8")
        oku = "def calistir(g, b):\n    return {'sonuc': open(g['yol']).read()}\n"
        self.izin_hatasi("anahtar_adi", oku, {"yol": "anahtarlar.json"}, izinler=["dosya_oku"])
        CONFIG_DIR.mkdir(parents=True, exist_ok=True)
        (CONFIG_DIR / "ayarlar.json").write_text("{}", encoding="utf-8")
        self.izin_hatasi("ayar_klasoru", oku, {"yol": str(CONFIG_DIR / "ayarlar.json")}, izinler=["dosya_oku"])

    def test_alt_surec_dusuk_seviyeden_de_acilmaz(self):
        kod = ("import _posixsubprocess, subprocess\ndef calistir(g, b):\n"
               "    subprocess.Popen(['true']).wait()\n    return {}\n")
        if sys.platform != "win32":
            self.izin_hatasi("fork_exec", kod)

    def test_ag_izni_onay_ister(self):
        yetenek_yaz(self.kok, "agli", "def calistir(g, b):\n    return {}\n",
                    manifest("agli", izinler=["dosya_oku", "ag"], kaynak="uretildi"))
        self.assertEqual(Kayit([self.kok], kademe="orta").getir("agli").risk(), "calistirir")
        yerel = Kayit([YERLESIK_KOK], kademe="orta")
        self.assertEqual(yerel.getir("metin_istatistik").risk(), "okur")

    def test_ag_ve_komut_engellenir(self):
        self.izin_hatasi("agsiz", "import socket\ndef calistir(g, b):\n"
                                  "    socket.create_connection(('127.0.0.1', 9), 2)\n")
        self.izin_hatasi("komutsuz", "import subprocess\ndef calistir(g, b):\n    subprocess.run(['true'])\n")
        self.izin_hatasi("sistemsiz", "import os\ndef calistir(g, b):\n    os.system('true')\n")

    def test_anahtarlar_gecmez(self):
        os.environ["K5_TEST_ANAHTARI"] = "gizli-deger"
        self.addCleanup(os.environ.pop, "K5_TEST_ANAHTARI", None)
        kod = "import os\ndef calistir(g, b):\n    return {'sonuc': os.environ.get('K5_TEST_ANAHTARI', 'yok')}\n"
        self.assertEqual(self.calistir("anahtarsiz", kod), {"sonuc": "yok"})
        self.assertEqual(self.calistir("anahtarli", kod, izinler=["anahtar:K5_TEST_ANAHTARI"]),
                         {"sonuc": "gizli-deger"})

    def test_girdi_ve_cikti_denetlenir(self):
        m = {"girdi": {"n": {"tip": "int", "zorunlu": True}, "kat": {"tip": "int", "varsayilan": 2}},
             "cikti": {"sonuc": {"tip": "int"}}}
        kod = "def calistir(g, b):\n    return {'sonuc': g['n'] * g['kat']}\n"
        self.assertEqual(self.calistir("carp", kod, {"n": 4}, **m), {"sonuc": 8})  # varsayılan uygulandı
        with self.assertRaises(YetenekHatasi) as h:
            self.calistir("carp2", kod, {"n": "dört"}, **m)
        self.assertEqual(h.exception.sinif, "veri")
        with self.assertRaises(YetenekHatasi) as h:
            self.calistir("yanlis", "def calistir(g, b):\n    return {'sonuc': 'metin'}\n", {"n": 1}, **m)
        self.assertEqual(h.exception.sinif, "mantik")
        with self.assertRaises(YetenekHatasi) as h:
            self.calistir("liste", "def calistir(g, b):\n    return [1]\n")
        self.assertEqual(h.exception.sinif, "mantik")

    def test_yetenegin_hata_sinifi_korunur(self):
        kod = ("from asistan.cekirdek.yetenek import YetenekHatasi\ndef calistir(g, b):\n"
               "    raise YetenekHatasi('veri', 'dosya bozuk')\n")
        with self.assertRaises(YetenekHatasi) as h:
            self.calistir("sinifli", kod)
        self.assertEqual((h.exception.sinif, h.exception.mesaj), ("veri", "dosya bozuk"))

    def test_print_sonucu_bozmaz(self):
        kod = "def calistir(g, b):\n    print('günlük satırı')\n    return {'sonuc': 'tamam'}\n"
        self.assertEqual(self.calistir("konuskan", kod), {"sonuc": "tamam"})

    def test_cikti_metni(self):
        self.assertEqual(cikti_metni({"sonuc": "düz"}), "düz")
        self.assertIn('"a": 1', cikti_metni({"a": 1, "b": "x"}))


# ---------------------------------------------------------------- görev motoru

class SahteModel:
    """Rol başına sıradaki hazır cevap (sözlük → şemaya uyan veri). İstemler `cagrilar`da."""

    def __init__(self, **cevaplar):
        self.cevaplar = {k: list(v) for k, v in cevaplar.items()}
        self.cagrilar: list[tuple[str, list, dict | None]] = []

    def secim(self, rol):
        return {"saglayici": "ollama", "model": f"sahte-{rol}", "neden": "test"}

    def __call__(self, rol, mesajlar, sistem="", sema=None):
        self.cagrilar.append((rol, mesajlar, sema))
        sira = self.cevaplar.get(rol)
        if not sira:
            raise ModelYok(f"{rol} için cevap yok")
        c = sira.pop(0)
        hatalar = semalar.dogrula(c, sema) if sema else []
        return Cevap(json.dumps(c, ensure_ascii=False), None if hatalar else c, self.secim(rol), hatalar)


class MotorTesti(unittest.TestCase):
    """Gerçek `AjanYetenekleri` + gerçek izin hattı + gerçek sandbox; yalnızca model sahte."""

    def setUp(self):
        from asistan.config import Settings

        self.klasor = tempfile.mkdtemp(dir=_GECICI)
        Path(self.klasor, "not.txt").write_text("merhaba dünya merhaba", encoding="utf-8")
        self.ayarlar = Settings.load()
        self.ayarlar.workspace = self.klasor
        self.ayarlar.approval_mode = "kullanici"
        self.ayarlar.confirm_commands = True
        self.kok = Path(tempfile.mkdtemp(dir=_GECICI))
        from asistan.cekirdek.yetenek import calistirici as c

        eski = c.ortam_koku
        c.ortam_koku = lambda: ORTAMLAR
        self.addCleanup(setattr, c, "ortam_koku", eski)

    def yet(self, kokler=None):
        from asistan.cekirdek.gorev.ajan import AjanYetenekleri

        kayit = Kayit(kokler or [YERLESIK_KOK], kademe="orta")
        return AjanYetenekleri(self.ayarlar, [], self.klasor, [self.klasor], kayit=kayit)

    def test_liste_manifestlerden(self):
        yet = self.yet()
        self.assertEqual({y["ad"] for y in yet.listele()},
                         {y.ad for y in Kayit([YERLESIK_KOK], kademe="orta").aktifler()})
        self.assertIn("y_metin_istatistik", {s["name"] for s in yet.ajan.tool_specs})  # sandbox yeteneği motorda
        from asistan.agent import build_tool_specs

        sohbet = {s["name"] for s in build_tool_specs(None, [])}
        self.assertFalse({"y_metin_istatistik", "move_file"} & sohbet)  # sohbet ajanlarının listesi değişmedi

    def test_uretilen_yetenek_onay_ister(self):
        yetenek_yaz(self.kok, "uretilen", "def calistir(g, b):\n    return {'sonuc': 'yaptım'}\n")
        yet = self.yet([YERLESIK_KOK, self.kok])
        self.assertTrue(yet.onay_gerekir("uretilen", {"yol": "x"}))
        c = yet.calistir("uretilen", {"yol": "x"})
        self.assertTrue(c.onay_bekliyor)
        c = yet.calistir("uretilen", {"yol": "x"}, onayli=True)
        self.assertFalse(c.hata, c.metin)
        self.assertEqual(c.metin, "yaptım")

    def test_yerlesik_onay_tahmini_araca_gore(self):
        yet = self.yet()
        self.assertFalse(yet.onay_gerekir("dosya_oku", {"yol": "not.txt"}))
        self.assertFalse(yet.onay_gerekir("metin_istatistik", {"yol": "not.txt"}))  # güvenilir, yalnızca okur
        self.assertTrue(yet.onay_gerekir("komut_calistir", {"komut": "touch x", "amac": "t"}))
        self.assertFalse(yet.onay_gerekir("komut_calistir", {"komut": "ls", "amac": "t"}))  # salt okuyan komut

    def test_tasima_hata_dallari(self):
        yet = self.yet()
        Path(self.klasor, "b.txt").write_text("b", encoding="utf-8")
        Path(self.klasor, "alt").mkdir()
        Path(self.klasor, "alt", "not.txt").write_text("eski", encoding="utf-8")
        for girdi, parca in (({"kaynak": "yok.txt", "hedef": "x.txt"}, "Not found"),
                             ({"kaynak": "not.txt", "hedef": "b.txt"}, "already exists"),
                             ({"kaynak": "not.txt", "hedef": "alt/"}, "already exists"),
                             ({"kaynak": "alt", "hedef": "alt/ic/"}, "into itself"),
                             ({"kaynak": ".", "hedef": "baska"}, "workspace folder itself"),
                             ({"kaynak": "not.txt", "hedef": "/tmp/k5-disari.txt"}, "outside the workspace")):
            c = yet.calistir("dosya_tasi", girdi)
            self.assertTrue(c.hata, girdi)
            self.assertIn(parca, c.metin, girdi)
        self.assertEqual(Path(self.klasor, "b.txt").read_text(encoding="utf-8"), "b")  # üstüne yazılmadı
        self.assertTrue(Path(self.klasor, "not.txt").exists())

    def test_yetenek_guvenlik_siniflamasi(self):
        from asistan import security

        yetenek_yaz(self.kok, "uretilen2", "def calistir(g, b):\n    return {}\n")
        self.yet([YERLESIK_KOK, self.kok])
        katman, neden = security.classify("y_uretilen2", {"yol": "x"}, self.klasor)
        self.assertEqual(katman, security.HIGH)
        self.assertIn("yeteneği", neden[0])
        self.assertNotIn("MCP", neden[0])
        self.assertEqual(security.classify("y_metin_istatistik", {"yol": "x"}, self.klasor)[0], security.LOW)
        self.assertTrue(security.forbidden("y_uretilen2", {"yol": "rm -rf /"}))  # yasak listesi yeteneklere de

    def test_tasima_ve_eski_adlar(self):
        yet = self.yet()
        c = yet.calistir("dosya_tasi", {"kaynak": "not.txt", "hedef": "arsiv/"})
        self.assertFalse(c.hata, c.metin)
        self.assertTrue(Path(self.klasor, "arsiv", "not.txt").exists())
        c = yet.calistir("read_file", {"path": "arsiv/not.txt"})  # K4'te kaydedilmiş görev adımı
        self.assertIn("merhaba", c.metin)
        c = yet.calistir("uydurma", {})
        self.assertTrue(c.hata)
        self.assertIn("metin_istatistik", c.metin)

    def test_pasif_yetenek_calismaz_ve_anlayiciya_gider(self):
        yetenek_yaz(self.kok, "kurulmamis", "def calistir(g, b):\n    return {}\n",
                    manifest("kurulmamis", gereksinimler={"pip": ["yok-boyle-paket-k5"]}))
        yet = self.yet([YERLESIK_KOK, self.kok])
        self.assertIn("kurulmamis", {p["ad"] for p in yet.pasifler()})
        c = yet.calistir("kurulmamis", {})
        self.assertTrue(c.hata)
        self.assertIn("kullanılamıyor", c.metin)

    def test_planlayici_deneme_yetenegini_kullanir(self):
        """/yetenek-ekle ile eklenen `metin_istatistik`: planlayıcı manifestten görür, seçer; adım sandbox'ta koşar."""
        anlayis = {"niyet": "kelime istatistiği", "kisitlar": [], "belirsizlikler": [],
                   "gereken_yetenekler": ["metin_istatistik"], "eksik_yetenekler": [], "belirsizlik": "dusuk",
                   "soru": ""}
        plan = {"adimlar": [{"amac": "not.txt'nin kelime istatistiği", "yetenek": "metin_istatistik",
                             "girdi": {"yol": "not.txt", "en_sik": 1}, "basari_olcutu": "kelime sayısı var",
                             "bagimli": [], "deneme_hakki": 0}]}
        model = SahteModel(analiz=[anlayis], planlama=[plan])
        yet = self.yet()
        depo = durum.Depo(Path(self.klasor) / "gorevler.db")
        gorev = yurutucu.Yurutucu(depo, yet, model, self.klasor, self.klasor).baslat("not.txt kaç kelime?")
        self.assertEqual(gorev["durum"], "tamamlandi", gorev.get("rapor"))
        sonuc = json.loads(gorev["adimlar"][0]["sonuc"])
        self.assertEqual(sonuc["kelime"], 3)
        self.assertEqual(sonuc["en_sik_kelimeler"], [{"kelime": "merhaba", "adet": 2}])
        rol, mesajlar, sema = next(c for c in model.cagrilar if c[0] == "planlama")
        self.assertIn("metin_istatistik", mesajlar[0]["content"])  # istemde manifestin açıklaması
        enum = sema["properties"]["adimlar"]["items"]["properties"]["yetenek"]["enum"]
        self.assertEqual(set(enum) - {"metin_uret"}, {y["ad"] for y in yet.listele()})


# ---------------------------------------------------------------- yeteneklerin kendi testleri

class YeteneklerinKendiTestleri(unittest.TestCase):
    """`asistan/yetenekler/*/test_*.py` (unittest `-s testler` ve pytest `testler/` onları kendiliğinden görmez)."""

    def test_her_yetenegin_testi_gecer(self):
        import importlib.util
        import io

        dosyalar = sorted(YERLESIK_KOK.glob("*/test_*.py"))
        self.assertEqual({d.parent.name for d in dosyalar}, {d.parent.name for d in YERLESIK_KOK.glob("*/manifest.json")})
        for dosya in dosyalar:
            with self.subTest(yetenek=dosya.parent.name):
                spec = importlib.util.spec_from_file_location(f"yetenek_testi_{dosya.parent.name}", dosya)
                modul = importlib.util.module_from_spec(spec)
                spec.loader.exec_module(modul)
                takim = unittest.defaultTestLoader.loadTestsFromModule(modul)
                cikti = io.StringIO()
                sonuc = unittest.TextTestRunner(stream=cikti, verbosity=0).run(takim)
                self.assertTrue(sonuc.testsRun > 0)
                self.assertEqual(len(sonuc.skipped), 0, "atlanan test kabul edilmez")
                self.assertTrue(sonuc.wasSuccessful(), cikti.getvalue()[-2000:])


if __name__ == "__main__":
    unittest.main()
