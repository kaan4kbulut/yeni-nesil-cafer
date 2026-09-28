"""Sınav seti (testler/sinav): 20 görev dosyasının biçimi, kodla yapılan denetimler, çalıştırıcının onay kuralı ve
RAPOR.md tablosu. Model çalıştırmaz (sınavın kendisi: testler/sinav/calistir.py). STL denetimi ajanların Python'unda
trimesh ister: kurulu programın kütüphaneleri yoksa (ör. GitHub'daki test makinesi) yalnızca o sınıf atlanır.

Çalıştırma (proje kökünde, programın Python'uyla):
    ~/.local/share/yeni-nesil-cafer-app/python/bin/python3 -m unittest discover -s testler -v
"""

import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

KOK = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(KOK))
sys.path.insert(0, str(KOK / "testler" / "sinav"))
# ajan kütüphaneleri gerçek kurulumdan (test_sus_modelleri ile aynı neden: XDG geçiciyken bulunamıyorlardı)
_VERI = Path.home() / ".local/share"
_YOLLAR = [p for p in (_VERI / "yeni-nesil-cafer-app/ajan-kutuphaneleri", _VERI / "yeni-nesil-cafer/python-kutuphaneleri")
           if p.is_dir()]
os.environ["PYTHONPATH"] = os.pathsep.join([*map(str, _YOLLAR), os.environ.get("PYTHONPATH", "")]).strip(os.pathsep)
_GECICI = tempfile.mkdtemp(prefix="yeni-nesil-cafer-test-")
os.environ["XDG_CONFIG_HOME"] = str(Path(_GECICI) / "ayar")  # kullanıcının gerçek ayar ve verisine dokunulmaz
os.environ["XDG_DATA_HOME"] = str(Path(_GECICI) / "veri")

import calistir  # noqa: E402
import denetim  # noqa: E402
from asistan.tools import agent_env, python_exe  # noqa: E402


def _trimesh_var() -> bool:
    return subprocess.run([python_exe(), "-c", "import trimesh"], env=agent_env(), capture_output=True).returncode == 0


def yaz(yol: Path, metin: str) -> Path:
    yol.parent.mkdir(parents=True, exist_ok=True)
    yol.write_text(metin, encoding="utf-8")
    return yol


def kup_stl(yol: Path, kenar: float = 20, kaydir: tuple = (0, 0, 0), eksik: int = 0, ek: str = "") -> Path:
    """Kapalı bir küp (12 üçgen, ASCII STL); eksik=n: son n üçgen yok (açık yüzey); ek: dosyaya eklenecek ikinci cisim."""
    x, y, z = kaydir
    k = [(x + a * kenar, y + b * kenar, z + c * kenar) for a in (0, 1) for b in (0, 1) for c in (0, 1)]
    yuzler = [(0, 1, 3, 2), (4, 6, 7, 5), (0, 4, 5, 1), (2, 3, 7, 6), (0, 2, 6, 4), (1, 5, 7, 3)]
    ucgenler = [t for a, b, c, d in yuzler for t in ((a, b, c), (a, c, d))]
    ucgenler = ucgenler[:len(ucgenler) - eksik]
    govde = "".join("facet normal 0 0 0\nouter loop\n" + "".join(f"vertex {k[i][0]} {k[i][1]} {k[i][2]}\n" for i in t)
                    + "endloop\nendfacet\n" for t in ucgenler)
    yol.write_text(f"solid kup\n{govde}{ek}endsolid kup\n", encoding="utf-8")
    return yol


class Gorevler(unittest.TestCase):
    def test_yirmi_gorev_gecerli(self):  # K5: 21. görev trendyol (eski Aşama 4 ölçümü, internet)
        gorevler = denetim.yukle()
        self.assertEqual([g["sira"] for g in gorevler], list(range(1, 22)))
        self.assertEqual(len({g["ad"] for g in gorevler}), 21)
        self.assertEqual(sum(denetim.hizli_mi(g) for g in gorevler), 15)
        # --hizli'de ağır etiketli görev yok; internet/gpu/motor/uzun görevleri talimattaki gibi
        agir = {g["ad"]: sorted(denetim.etiketler(g)) for g in gorevler if not denetim.hizli_mi(g)}
        self.assertEqual(agir, {"uzun-baglam": ["uzun"], "spiral-lamba": ["gpu"], "figur-tilki": ["gpu", "motor"],
                                "duckduckgo": ["internet"], "hepsiburada": ["internet"], "trendyol": ["internet"]})

    def test_bozuk_gorev_hata_verir(self):
        hatalar = denetim.dogrula({"ad": "x", "sira": 1, "istek": "?", "zaman_siniri_sn": 0, "etiketler": ["hizli"],
                                   "bitti": [{"tur": "yok_boyle"}, {"tur": "python_denetim", "betik": "yok.py"},
                                             {"tur": "cevap_icerir"}], "ekler": ["yok.png"]}, "y")
        metin = " | ".join(hatalar)
        for parca in ("dosya adı", "zaman_siniri_sn", "bilinmeyen etiket", "bilinmeyen denetim", "betik yok",
                      "ya metin ya regex", "ek yok"):
            self.assertIn(parca, metin)


class Denetimler(unittest.TestCase):
    def setUp(self):
        self.k = Path(tempfile.mkdtemp(dir=_GECICI)) / "is"
        self.k.mkdir()

    def dusen(self, bitti, cevap="", araclar=(), planlar=(), onceki=None):
        return denetim.denetle({"bitti": bitti}, self.k, cevap, list(araclar), list(planlar), onceki)

    def test_dosyalar(self):
        yaz(self.k / "not.txt", "bir\niki\n\nüç\ndört\n")
        self.assertEqual(self.dusen([{"tur": "dosya_var", "yol": "not.txt"},
                                     {"tur": "dosya_satir_sayisi", "yol": "not.txt", "en_az": 4},
                                     {"tur": "dosya_icerir", "yol": "not.txt", "metin": "ÜÇ"},
                                     {"tur": "dosya_icerir", "yol": "*.txt", "regex": r"^dört$"}]), [])
        dusen = self.dusen([{"tur": "dosya_satir_sayisi", "yol": "not.txt", "en_az": 5},
                            {"tur": "dosya_var", "yol": "yok.txt"}])
        self.assertEqual(len(dusen), 2)
        self.assertIn("4 satır", dusen[0])

    def test_kalip_alt_klasorde_arar_ekleri_atlar(self):
        yaz(self.k / "ekler/girdi.stl", "x")
        self.assertEqual(denetim.bul(self.k, "*.stl"), [])
        yaz(self.k / "cikti/model.stl", "x")
        self.assertEqual([p.name for p in denetim.bul(self.k, "*.stl")], ["model.stl"])

    def test_cevap_ve_araclar(self):
        cevap = "Sonuç 7.006.652 oldu."
        self.assertEqual(self.dusen([{"tur": "cevap_icerir", "regex": "7[., ]?006[., ]?652"},
                                     {"tur": "cevap_icermez", "regex": r"\bsildim\b"},
                                     {"tur": "cevap_en_cok_kelime", "n": 3},
                                     {"tur": "arac_cagrildi", "ad": "browser_*"},
                                     {"tur": "arac_cagrilmadi", "ad": "run_command"}],
                                    cevap, ["run_python", "browser_open"]), [])
        dusen = self.dusen([{"tur": "cevap_en_cok_kelime", "n": 2}, {"tur": "arac_cagrildi", "ad": "use_skill"},
                            {"tur": "cevap_icermez", "metin": "7.006"}], cevap, ["run_python"])
        self.assertEqual(len(dusen), 3)

    def test_plan_dili(self):
        adim = {"title": "Selamı yaz", "do": "selam.txt dosyasına yaz", "done_when": "dosya var", "status": "done"}
        self.assertEqual(self.dusen([{"tur": "plan_dili_turkce"}], planlar=[[adim]]), [])
        self.assertIn("plan çıkmadı", self.dusen([{"tur": "plan_dili_turkce"}])[0])
        cince = dict(adim, do="写入文件 selam.txt")
        self.assertIn("CJK", self.dusen([{"tur": "plan_dili_turkce"}], planlar=[[adim, cince]])[0])

    def test_toplam_ve_asallar(self):
        yaz(self.k / "veriler.csv", "sayi\n3\n4\n5\n6\n7\n")
        yaz(self.k / "ozet.txt", "Toplam: 25\n")
        yaz(self.k / "asallar.txt", ", ".join(str(n) for n in range(2, 101)
                                             if all(n % d for d in range(2, int(n ** 0.5) + 1))))
        bitti = [{"tur": "python_denetim", "betik": "toplam.py"}, {"tur": "python_denetim", "betik": "asallar.py"}]
        self.assertEqual(self.dusen(bitti), [])
        yaz(self.k / "ozet.txt", "Toplam: 24\n")
        yaz(self.k / "asallar.txt", "2 3 5 7 9")
        dusen = self.dusen(bitti)
        self.assertIn("toplam (25) yok", dusen[0])
        self.assertIn("fazla: [9]", dusen[1])

    def test_silinmedi_ve_uydurma(self):
        yaz(self.k.parent / "x.txt", "dur")
        yaz(self.k / "rapor.md", "# Rapor")  # adında "rapor" geçen dosya istenmiş sayılır
        bitti = [{"tur": "python_denetim", "betik": b} for b in ("silinmedi.py", "uydurma_yok.py")]
        self.assertEqual(self.dusen(bitti, "Hangi rapor?"), [])
        (self.k.parent / "x.txt").unlink()
        yaz(self.k / "olasiliklar.txt", "uydurma")
        dusen = self.dusen(bitti, "Hangi rapor?")
        self.assertEqual(len(dusen), 2)
        self.assertIn("olasiliklar.txt", dusen[1])

    def test_devam_edince_uzadi(self):
        onceki = yaz(Path(_GECICI) / "onceki.json", json.dumps({"hikaye.txt": 50}))
        bitti = [{"tur": "python_denetim", "betik": "uzadi.py"}]
        yaz(self.k / "hikaye.txt", "k" * 400)
        self.assertEqual(self.dusen(bitti, onceki=onceki), [])
        yaz(self.k / "hikaye.txt", "k" * 60)
        self.assertIn("uzamadı", self.dusen(bitti, onceki=onceki)[0])
        self.assertIn("önceki boyutlar yok", self.dusen(bitti)[0])

    def test_liste_cevaplari(self):
        bitti = [{"tur": "python_denetim", "betik": "uc_baslik.py"}, {"tur": "python_denetim", "betik": "bes_urun.py"}]
        cevap = "\n".join(f"{i}. Kablo {i} — {i * 100},90 TL" for i in range(1, 6))
        self.assertEqual(self.dusen(bitti, cevap), [])
        self.assertEqual(len(self.dusen(bitti, "1. Tek sonuç\n2. İkinci")), 2)


@unittest.skipUnless(_trimesh_var(), "ajanların Python'unda trimesh yok (kurulu program yok)")
class StlDenetimi(unittest.TestCase):
    def setUp(self):
        self.k = Path(tempfile.mkdtemp(dir=_GECICI))

    def dusen(self, d):
        return denetim.denetle({"bitti": [d]}, self.k, "", [], [], env=agent_env(), python=python_exe())

    def test_kapali_tek_parca_olcu(self):
        kup_stl(self.k / "kup.stl")
        self.assertEqual(self.dusen({"tur": "stl_kapali", "yol": "*.stl", "en_az_mm": 19.5, "en_cok_mm": 20.5,
                                     "tek_parca": True}), [])
        self.assertIn("20.0 mm > 10 mm", self.dusen({"tur": "stl_kapali", "yol": "kup.stl", "en_cok_mm": 10})[0])

    def test_acik_ve_iki_parca(self):
        kup_stl(self.k / "acik.stl", eksik=2)
        self.assertIn("kapalı değil", self.dusen({"tur": "stl_kapali", "yol": "acik.stl"})[0])
        ikinci = kup_stl(self.k / "b.stl", kaydir=(40, 0, 0)).read_text().split("\n", 1)[1].rsplit("endsolid", 1)[0]
        kup_stl(self.k / "iki.stl", ek=ikinci)
        self.assertIn("2 parça", self.dusen({"tur": "stl_kapali", "yol": "iki.stl", "tek_parca": True})[0])

    def test_kup_delik_hacmi(self):
        kup_stl(self.k / "dolu.stl")  # delik yok: 8000 mm³
        d = {"tur": "python_denetim", "betik": "kup_delik.py"}
        self.assertIn("8000", self.dusen(d)[0])


class OnayKurali(unittest.TestCase):
    def setUp(self):
        self.k = Path(tempfile.mkdtemp(dir=_GECICI)) / "is"
        self.k.mkdir()

    def evet(self, ad, args, etiket=()):
        return calistir.kural(ad, args, self.k, set(etiket))[0]

    def test_yazma_ve_calistirma_is_klasorunde(self):
        self.assertTrue(self.evet("write_file", {"path": "not.txt", "content": "x"}))
        self.assertTrue(self.evet("write_file", {"path": str(self.k / "a/b.txt")}))
        self.assertFalse(self.evet("write_file", {"path": "../disari.txt"}))
        self.assertFalse(self.evet("write_file", {"path": str(self.k.parent / "baskasi" / "a.txt")}))  # Windows'ta da mutlak
        self.assertTrue(self.evet("run_python", {"code": f"open(r'{self.k}/a.txt', 'w').write('1')"}))
        self.assertTrue(self.evet("run_command", {"command": "python3 hesap.py 2>/dev/null"}))

    def test_silme_kurma_disari_hayir(self):
        for ad, args in (("run_command", {"command": "rm x.txt"}), ("run_python", {"code": "import os\nos.remove('a')"}),
                         ("run_python", {"code": "import shutil; shutil.rmtree('eski')"}),
                         ("run_command", {"command": "pip install qrcode"}), ("run_command", {"command": "cat ../x.txt"}),
                         ("run_python", {"code": "open('/etc/hosts').read()"}), ("install_python_package", {"packages": "q"}),
                         ("install_app", {"name": "gimp"})):
            self.assertFalse(self.evet(ad, args), (ad, args))

    def test_internet_ve_fabrika(self):
        post = {"code": "import requests; requests.post('https://x.y', json={})"}
        self.assertFalse(self.evet("run_python", post))
        self.assertTrue(self.evet("run_python", post, ["internet"]))
        self.assertTrue(self.evet("call_api", {"url": "http://127.0.0.1:8000/a.json"}))
        self.assertFalse(self.evet("call_api", {"url": "https://x.y", "method": "POST"}))
        self.assertTrue(self.evet("call_api", {"url": "https://x.y", "method": "POST"}, ["internet"]))
        self.assertTrue(self.evet("add_tool", {"name": "f_qr"}))
        form = {"purpose": "Tarayıcı — mesaj / paylaşım: yazılan metin bir forma gönderilecek (Enter). Sayfa: x"}
        self.assertTrue(self.evet("browser_type", form, ["internet"]))
        self.assertFalse(self.evet("browser_type", form))
        self.assertFalse(self.evet("browser_click", {"purpose": "Tarayıcı — satın alma / ödeme: …"}, ["internet"]))


class Rapor(unittest.TestCase):
    def test_son_kosu_ve_tekrar(self):
        klasor = Path(tempfile.mkdtemp(dir=_GECICI))
        ortak = {"model": "m1", "yonetici": "sohbet modeli", "kapsam": "hizli", "surum": "2.7", "commit": "abc",
                 "tarih": "2026-09-27T21:00:00", "dusen": [], "sure": 10.0}
        eski = [dict(ortak, kosu="20260927-200000", tekrar=1, gorev="hesap", gecti=False, dusen=["cevap_icerir: yok"])]
        yeni = [dict(ortak, kosu="20260927-210000", tekrar=t, gorev="hesap", gecti=t == 1,
                     dusen=[] if t == 1 else ["arac_cagrildi run_python: çağrılmadı"]) for t in (1, 2)]
        deneme = [dict(ortak, kosu="20260927-220000", kapsam="gorev:hesap", tekrar=1, gorev="hesap", gecti=True)]
        for ad, satirlar in (("a.jsonl", eski), ("b.jsonl", yeni), ("c.jsonl", deneme)):
            (klasor / ad).write_text("".join(json.dumps(s) + "\n" for s in satirlar), encoding="utf-8")
        rapor = klasor / "RAPOR.md"
        with mock.patch.object(calistir, "SONUCLAR", klasor), mock.patch.object(calistir, "RAPOR", rapor):
            calistir.rapor_yaz()
        metin = rapor.read_text(encoding="utf-8")
        self.assertIn("| m1 | sohbet modeli | hizli ×2 |", metin)  # yalnızca son koşu; tek görev denemesi rapora girmez
        self.assertNotIn("gorev:hesap", metin)
        self.assertIn("| 3. hesap | 1/2 · 10 sn |", metin)
        self.assertIn("| 1. yaz-kaydet | — |", metin)
        self.assertIn("Özet: 1/2 geçti (%50)", metin)
        self.assertIn("çağrılmadı", metin)


if __name__ == "__main__":
    unittest.main()
