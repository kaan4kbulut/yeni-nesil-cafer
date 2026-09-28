"""Donanım profili ve kademe (K2): `asistan/cekirdek/profil.py`.

Sahte donanım verisiyle dört kademe, kilit önceliği (ayar.toml/ortam > arayüz > ölçüm), dusuk kademede kapanan ağır
özellikler (embedding, tarayıcı, uzun bağlam), ekran kartı çıktılarının ayrıştırılması, profil.json yazımı ve
`python -m asistan profil` komutu.
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

_GECICI = tempfile.mkdtemp(prefix="yeni-nesil-cafer-test-")
os.environ["XDG_CONFIG_HOME"] = str(Path(_GECICI) / "ayar")
os.environ["XDG_DATA_HOME"] = str(Path(_GECICI) / "veri")
os.environ.pop("CAFER_GENEL_KADEME_KILIDI", None)

from asistan.cekirdek import ayar, profil  # noqa: E402


def sahte(ram, vram=0.0, var=None, basliksiz=False, birlesik=False):
    """Sahte profil: yalnızca kademe hesabının baktığı alanlar."""
    gpu = {"var": bool(vram) if var is None else var, "ad": "sahte", "vram_gb": vram, "arka_uc": "cuda"}
    if birlesik:
        gpu["birlesik"] = True
    return {"ram_gb": ram, "gpu": gpu, "basliksiz": basliksiz}


class KademeHesabi(unittest.TestCase):
    def test_dort_kademe(self):
        self.assertEqual(profil.kademe_hesapla(sahte(7.6))[0], "dusuk")  # 8 GB, ekran kartı yok
        self.assertEqual(profil.kademe_hesapla(sahte(15.5))[0], "orta")  # 16 GB, ekran kartı yok
        self.assertEqual(profil.kademe_hesapla(sahte(15.5, 6.0))[0], "orta")  # 16 GB + 6 GB VRAM
        self.assertEqual(profil.kademe_hesapla(sahte(31.0, 11.9))[0], "yuksek")  # bu bilgisayar: 32 GB + 12 GB
        self.assertEqual(profil.kademe_hesapla(sahte(31.0, 11.9, basliksiz=True))[0], "sunucu")
        self.assertEqual(profil.kademe_hesapla(sahte(3.8, basliksiz=True))[0], "sunucu")  # küçük VPS de sunucu

    def test_sinirlar(self):
        self.assertEqual(profil.kademe_hesapla(sahte(63.0))[0], "orta")  # çok RAM ama ekran kartı yok
        self.assertEqual(profil.kademe_hesapla(sahte(63.0, 6.0))[0], "orta")  # ≤ 6 GB VRAM
        self.assertEqual(profil.kademe_hesapla(sahte(15.5, 12.0))[0], "orta")  # VRAM var ama RAM < 32
        self.assertEqual(profil.kademe_hesapla(sahte(31.0, 8.0))[0], "yuksek")  # 8 GB kart tam sınırda
        self.assertEqual(profil.kademe_hesapla(sahte(7.6, 8.0))[0], "orta")  # az RAM, ayrı kart kurtarır
        self.assertEqual(profil.kademe_hesapla(sahte(7.6, 2.0))[0], "dusuk")  # zayıf kart kurtarmaz
        # 8 GB Apple Silicon: birleşik bellek ayrı kart sayılmaz
        self.assertEqual(profil.kademe_hesapla(sahte(8.0, 5.2, birlesik=True))[0], "dusuk")
        self.assertEqual(profil.kademe_hesapla({})[0], "dusuk")  # ölçülemedi: en temkinli kademe

    def test_neden_yazilir(self):
        kademe, neden = profil.kademe_hesapla(sahte(31.0, 11.9))
        self.assertIn("31 GB RAM", neden)
        self.assertIn("12 GB", neden)


class Kilit(unittest.TestCase):
    def setUp(self):
        self.ayar_dosyasi = Path(_GECICI) / "ayar.toml"
        os.environ[ayar.DOSYA_ORTAMI] = str(self.ayar_dosyasi)
        self.ayar_dosyasi.unlink(missing_ok=True)
        os.environ.pop("CAFER_GENEL_KADEME_KILIDI", None)
        profil.kilitle(None)
        profil.dosya().unlink(missing_ok=True)

    def tearDown(self):
        os.environ.pop(ayar.DOSYA_ORTAMI, None)
        os.environ.pop("CAFER_GENEL_KADEME_KILIDI", None)
        profil.kilitle(None)
        profil._onbellek_temizle()

    def test_kilit_yokken_olcum(self):
        profil.kaydet(profil._kademe_yaz(sahte(31.0, 11.9)))
        profil._onbellek_temizle()
        self.assertIsNone(profil.kilit())
        self.assertEqual(profil.kademe(), "yuksek")

    def test_arayuz_kilidi_olcumu_ezer(self):
        profil.kaydet(profil._kademe_yaz(sahte(31.0, 11.9)))
        profil.kilitle("dusuk")
        self.assertEqual(profil.kademe(), "dusuk")
        self.assertEqual(profil.kilit_kaynagi(), "arayuz")
        kayit = profil.yukle()["kademe"]  # profil.json da güncellenir
        self.assertEqual((kayit["olculen"], kayit["kilitli"], kayit["etkin"]), ("yuksek", "dusuk", "dusuk"))
        self.assertEqual(ayar.Settings.load().extra.get("kademe_kilidi"), "dusuk")
        profil.kilitle(None)
        self.assertEqual(profil.kademe(), "yuksek")

    def test_ayar_toml_ve_ortam_arayuzu_ezer(self):
        profil.kilitle("orta")
        self.ayar_dosyasi.write_text('[genel]\nkademe_kilidi = "dusuk"\n', encoding="utf-8")
        profil._onbellek_temizle()
        self.assertEqual(profil.kademe(), "dusuk")
        self.assertEqual(profil.kilit_kaynagi(), "dosya")
        os.environ["CAFER_GENEL_KADEME_KILIDI"] = "sunucu"
        profil._onbellek_temizle()
        self.assertEqual(profil.kademe(), "sunucu")

    def test_gecersiz_kilit_yok_sayilir(self):
        os.environ["CAFER_GENEL_KADEME_KILIDI"] = "cok-yuksek"
        self.assertIsNone(profil.kilit())
        with self.assertRaises(ValueError):
            profil.kilitle("cok-yuksek")


class AgirOzellikler(unittest.TestCase):
    """dusuk kademede embedding, tarayıcı ve uzun bağlam kapalı; diğer kademelerde açık."""

    def tearDown(self):
        os.environ.pop("CAFER_GENEL_KADEME_KILIDI", None)
        profil._onbellek_temizle()

    def _kademe(self, k):
        os.environ["CAFER_GENEL_KADEME_KILIDI"] = k
        profil._onbellek_temizle()

    def test_acik_kapali(self):
        for k in ("orta", "yuksek", "sunucu"):
            self._kademe(k)
            self.assertTrue(all(profil.acik_mi(o) for o in profil.AGIR_OZELLIKLER), k)
            self.assertEqual(profil.kapali_notu("tarayici"), "")
        self._kademe("dusuk")
        self.assertFalse(any(profil.acik_mi(o) for o in profil.AGIR_OZELLIKLER))
        self.assertIn("bu kademede kapalı", profil.kapali_notu("embedding"))

    def test_embedding_kapali(self):
        from asistan import memory_db

        self._kademe("dusuk")
        with mock.patch("httpx.get") as get:
            self.assertFalse(memory_db.embedding_available())
            self.assertIsNone(memory_db.embed(["merhaba"]))
            get.assert_not_called()  # Ollama'ya hiç sorulmaz
        self.assertIn("bu kademede kapalı", memory_db.semantic_note())

    def test_tarayici_kapali(self):
        from asistan import browser

        self._kademe("dusuk")
        self.assertFalse(browser.available())

    def test_uzun_baglam_kapali(self):
        from asistan import power

        s = ayar.Settings(ollama_num_ctx=32768, power_mode="performans")
        with mock.patch("asistan.gpu.fault", return_value=""):
            self._kademe("yuksek")
            self.assertEqual(power.num_ctx(s), 32768)
            self._kademe("dusuk")
            self.assertEqual(power.num_ctx(s), profil.KISA_BAGLAM)


class EkranKartiAyristirma(unittest.TestCase):
    VULKAN = """Device Properties and Extensions:
==================================
GPU0:
VkPhysicalDeviceProperties:
\tdeviceType        = PHYSICAL_DEVICE_TYPE_INTEGRATED_GPU
\tdeviceName        = Intel(R) Graphics (RPL-S)
VkPhysicalDeviceMemoryProperties:
\tmemoryHeaps[0]:
\t\tsize   = 24996900864 (0x5d1ee7000) (23.28 GiB)
\t\tflags: count = 1
\t\t\tMEMORY_HEAP_DEVICE_LOCAL_BIT
GPU1:
VkPhysicalDeviceProperties:
\tdeviceType        = PHYSICAL_DEVICE_TYPE_DISCRETE_GPU
\tdeviceName        = NVIDIA GeForce RTX 5070 Ti Laptop GPU
VkPhysicalDeviceMemoryProperties:
\tmemoryHeaps[0]:
\t\tsize   = 12820938752 (0x2fc300000) (11.94 GiB)
\t\tflags: count = 1
\t\t\tMEMORY_HEAP_DEVICE_LOCAL_BIT
\tmemoryHeaps[1]:
\t\tsize   = 24996900864 (0x5d1ee7000) (23.28 GiB)
\t\tflags: count = 0
\t\t\tNone
"""

    def test_vulkan_ayri_kart(self):
        g = profil.vulkan_coz(self.VULKAN)  # bu bilgisayarın gerçek çıktısından kısaltıldı
        self.assertEqual(g["ad"], "NVIDIA GeForce RTX 5070 Ti Laptop GPU")
        self.assertEqual(g["vram_gb"], 11.9)  # tümleşik kartın 23 GB'lık (sistem belleği) yığını sayılmaz
        self.assertEqual(g["arka_uc"], "vulkan")

    def test_vulkan_yalniz_tumlesik(self):
        yalniz = self.VULKAN.split("GPU1:")[0]
        self.assertIsNone(profil.vulkan_coz(yalniz))
        self.assertIsNone(profil.vulkan_coz(""))

    def test_metal_intel_mac(self):
        metin = ("Graphics/Displays:\n\n    AMD Radeon Pro 5500M:\n\n      Chipset Model: AMD Radeon Pro 5500M\n"
                 "      Type: GPU\n      Bus: PCIe\n      VRAM (Total): 4 GB\n")
        g = profil.metal_coz(metin)
        self.assertEqual((g["ad"], g["vram_gb"], g["arka_uc"]), ("AMD Radeon Pro 5500M", 4.0, "metal"))

    def test_sira_nvidia_once(self):
        from asistan import gpu

        kart = gpu.Card("NVIDIA RTX", "nvidia", 12227, True)
        with mock.patch.object(gpu, "cards", return_value=[gpu.Card("Intel tümleşik", "intel", 0, False), kart]), \
                mock.patch.object(profil, "_gpu_torch") as torch, mock.patch.object(profil, "_gpu_vulkan") as vk:
            g = profil._gpu(31.0)
        self.assertEqual((g["ad"], g["vram_gb"], g["arka_uc"]), ("NVIDIA RTX", 11.9, "cuda"))
        torch.assert_not_called()  # ilk yol buldu: pahalı yollara inilmez
        vk.assert_not_called()

    def test_kart_yoksa_vulkana_iner(self):
        from asistan import gpu

        with mock.patch.object(gpu, "cards", return_value=[]), \
                mock.patch.object(profil, "_gpu_torch", return_value=None), \
                mock.patch.object(profil, "_gpu_vulkan", return_value=profil.vulkan_coz(self.VULKAN)):
            g = profil._gpu(31.0)
        self.assertEqual(g["arka_uc"], "vulkan")


class ProfilDosyasi(unittest.TestCase):
    def test_olc_ve_yaz(self):
        with mock.patch.object(profil, "_ollama", return_value={"calisiyor": False, "surum": "", "modeller": []}):
            p = profil.guncelle(sunucu=False)
        for alan in ("olcum_zamani", "isletim", "cpu", "ram_gb", "gpu", "disk_bos_gb", "ag", "ollama", "kademe"):
            self.assertIn(alan, p)  # docs/SEMALAR.md §4
        self.assertEqual(set(p["kademe"]) >= {"olculen", "kilitli", "etkin"}, True)
        self.assertIn(p["kademe"]["etkin"], profil.KADEMELER)
        # gerçek veri klasörüne yazılmaz (pytest'te XDG'yi ilk içe aktarılan test dosyası belirler)
        self.assertIn("yeni-nesil-cafer-test-", str(profil.dosya()))
        self.assertEqual(json.loads(profil.dosya().read_text(encoding="utf-8"))["ram_gb"], p["ram_gb"])
        self.assertGreater(p["ram_gb"], 0)

    def test_benchmark_korunur(self):
        profil.kaydet({"benchmark": {"x": {"tok_sn": 41.2}}})
        with mock.patch.object(profil, "_ollama", return_value={"calisiyor": False, "surum": "", "modeller": []}):
            p = profil.guncelle(sunucu=False)
        self.assertEqual(p["benchmark"], {"x": {"tok_sn": 41.2}})

    def test_ozet(self):
        metin = profil.ozet(profil._kademe_yaz({**sahte(7.6), "ag": False, "ollama": {"calisiyor": False}}))
        self.assertIn("Kademe: düşük", metin)
        self.assertIn("Bu kademede kapalı: Hafıza", metin)
        self.assertIn("Önerilen modeller: yerel", metin)


class Benchmark(unittest.TestCase):
    """Ollama sahte aktarıcıyla: token/sn, ilk token, yavaş işareti, embedding atlama, profil.json'a yazım."""

    def _istemci(self, tok_sn: float, capabilities=("completion",), kesik=False):
        import httpx

        def cevap(istek):
            yol, govde = istek.url.path, json.loads(istek.content or b"{}")
            if yol == "/api/tags":
                return httpx.Response(200, json={"models": [{"name": "hizli:1b"}, {"name": "gomme"}]})
            if yol == "/api/show":
                caps = ["embedding"] if govde["model"] == "gomme" else list(capabilities)
                return httpx.Response(200, json={"capabilities": caps})
            if yol == "/api/ps":
                return httpx.Response(200, json={"models": [{"name": govde.get("model", "hizli:1b"),
                                                             "size": 2 * 1024 ** 3, "size_vram": 1024 ** 3}]})
            if yol == "/api/generate" and "prompt" not in govde:
                return httpx.Response(200, json={"done": True})  # yükle / boşalt
            self.govdeler.append(govde)
            satirlar = [json.dumps({"response": "kelime "}) for _ in range(5)]
            if not kesik:
                satirlar.append(json.dumps({"done": True, "eval_count": 100, "eval_duration": int(100 / tok_sn * 1e9)}))
            return httpx.Response(200, content="\n".join(satirlar).encode())

        self.govdeler = []
        return httpx.Client(transport=httpx.MockTransport(cevap))

    def setUp(self):
        profil.kaydet({"ram_gb": 31.0, "benchmark": {"eski:model": {"tok_sn": 9.0}}})
        os.environ["CAFER_GENEL_KADEME_KILIDI"] = "orta"
        profil._onbellek_temizle()

    def tearDown(self):
        os.environ.pop("CAFER_GENEL_KADEME_KILIDI", None)
        profil._onbellek_temizle()

    def test_hizli_model_ve_embedding_atlanir(self):
        with self._istemci(41.2) as ist:
            b = profil.benchmark(ollama_url="http://sahte:11434", istemci=ist)
        s = b["hizli:1b"]
        self.assertEqual((s["tok_sn"], s["token"], s["yavas"], s["kademe"]), (41.2, 100, False, "orta"))
        for alan in ("ilk_token_ms", "yukleme_ms", "olcum", "sure_sn"):
            self.assertIn(alan, s)  # docs/SEMALAR.md §4: tok_sn, ilk_token_ms, olcum
        self.assertEqual((s["bellek_gb"], s["kartta_yuzde"]), (2.0, 50))
        self.assertIn("embedding", b["gomme"]["atlandi"])
        self.assertEqual(len(self.govdeler), 1)  # embedding modeline metin isteği gitmez
        self.assertEqual(b["eski:model"], {"tok_sn": 9.0})  # önceki ölçümler korunur
        self.assertEqual(profil.yukle()["benchmark"], b)  # profil.json'a yazıldı
        self.assertNotIn("think", self.govdeler[0])  # düşünmeyen modele think gönderilmez

    def test_yavas_model_isaretlenir(self):
        with self._istemci(2.4, capabilities=("completion", "thinking")) as ist:
            s = profil.benchmark(["hizli:1b"], ollama_url="http://sahte:11434", istemci=ist)["hizli:1b"]
        self.assertTrue(s["yavas"])
        self.assertEqual(s["not"], "bu kademe için yavaş")
        self.assertIs(self.govdeler[0]["think"], False)  # düşünen model: ölçüm düşünmesiz
        self.assertIn("yavaş", profil.benchmark_satiri("hizli:1b", s))
        self.assertIn("bu kademe için yavaş: hizli:1b", profil.ozet(profil._kademe_yaz(profil.yukle())))

    def test_sure_dolarsa_kendi_sayimi(self):
        saat = iter(range(0, 1000, 10))  # her çağrıda 10 sn ilerleyen saat: 30 sn tavanı hemen dolar
        with self._istemci(50, kesik=True) as ist:
            s = profil._model_olc(ist, "http://sahte:11434", "hizli:1b", 30, zaman=lambda: next(saat))
        self.assertTrue(s["kesildi"])
        self.assertLess(s["token"], 5)  # akış süre dolunca bırakıldı
        self.assertIn("tok_sn", s)

    def test_hata_kaydedilir(self):
        import httpx

        def cevap(istek):
            if istek.url.path == "/api/show":
                return httpx.Response(200, json={"capabilities": ["completion"]})
            return httpx.Response(500, text="model yüklenemedi: bellek yetmedi")

        with httpx.Client(transport=httpx.MockTransport(cevap)) as ist:
            s = profil.benchmark(["buyuk:70b"], ollama_url="http://sahte:11434", istemci=ist)["buyuk:70b"]
        self.assertIn("bellek yetmedi", s["hata"])
        self.assertNotIn("yavas", s)
        self.assertIn("HATA", profil.benchmark_satiri("buyuk:70b", s))


class Komut(unittest.TestCase):
    def test_python_m_asistan_profil(self):
        ortam = {**os.environ, "CAFER_GENEL_KADEME_KILIDI": "orta"}
        r = subprocess.run([sys.executable, "-m", "asistan", "profil", "--json"], cwd=KOK, env=ortam,
                           capture_output=True, text=True, timeout=120)
        self.assertEqual(r.returncode, 0, r.stderr)
        p = json.loads(r.stdout)
        self.assertEqual(p["kademe"]["etkin"], "orta")
        self.assertNotIn("PySide6", r.stderr)

    def test_yardim_ve_bilinmeyen(self):
        from asistan.arayuz import komut

        with mock.patch("sys.stdout"):
            self.assertEqual(komut.ana(["--help"]), 0)
        with mock.patch("sys.stderr"):
            self.assertEqual(komut.ana(["yok-boyle-komut"]), 2)

    def test_qt_yuklenmez(self):
        kod = "import sys; import asistan.arayuz.komut, asistan.cekirdek.profil; print('PySide6' in sys.modules)"
        r = subprocess.run([sys.executable, "-c", kod], cwd=KOK, capture_output=True, text=True, timeout=60)
        self.assertEqual(r.stdout.strip(), "False", r.stderr)


if __name__ == "__main__":
    unittest.main()
