"""BÖLÜM 2.7 küçük düzeltmeler: doğrulayıcı kelime sınırı ve ŞARTLI adım, sınıflandırıcı yanlış pozitifleri, görev
deposunda kilit, web okumada yerel ağ engeli + gövde sınırı, OpenAI uyumlu okuma zaman aşımı, ayar klasörü taşıma
içe aktarma anında değil."""

import os
import subprocess
import sys
import tempfile
import threading
import unittest
from pathlib import Path
from unittest import mock

KOK = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(KOK))
_GECICI = tempfile.mkdtemp(prefix="yeni-nesil-cafer-test-")
os.environ["XDG_CONFIG_HOME"] = str(Path(_GECICI) / "ayar")
os.environ["XDG_DATA_HOME"] = str(Path(_GECICI) / "veri")

import httpx  # noqa: E402

from asistan.cekirdek.araclar import AracHatasi, web  # noqa: E402
from asistan.cekirdek.gorev import Cikti, ModelYok, dogrulayici, durum, yurutucu  # noqa: E402
from asistan.cekirdek.saglayici import openai_uyumlu  # noqa: E402


class Dogrulayici(unittest.TestCase):
    def test_varsayilan_kelimesi_dosya_denetimi_tetiklemez(self):
        adim = {"amac": "x", "yetenek": "y", "basari_olcutu": "varsayılan klasördeki rapor.txt listelendi"}
        # "var" kelimesi yok ("varsayılan" var): dosya var mı diye bakılmaz, karar modelin/ölçütün
        karar, neden = dogrulayici.kural(adim, Cikti("rapor.txt 12 bayt"), [_GECICI])
        self.assertIsNone(karar)
        adim["basari_olcutu"] = "rapor.txt var"
        self.assertEqual(dogrulayici.kural(adim, Cikti("yazdım"), [_GECICI])[0], False)

    def test_denetleyici_yoksa_sartli(self):
        adim = {"amac": "say", "yetenek": "y", "basari_olcutu": "sayı toplamla tutarlı"}
        tamam, neden = dogrulayici.dogrula(adim, Cikti("bir metin"), None, None)
        self.assertTrue(tamam)
        self.assertTrue(neden.startswith(dogrulayici.SARTLI), neden)

        class Yok:
            def __call__(self, *a, **k):
                raise ModelYok("kapalı")

        tamam, neden = dogrulayici.dogrula(adim, Cikti("bir metin"), None, Yok())
        self.assertTrue(tamam)
        self.assertTrue(neden.startswith(dogrulayici.SARTLI), neden)

    def test_sartli_adim_raporda_gecmis_sayilmaz(self):
        gorev = {"adimlar": [{"id": 1, "amac": "a", "durum": "tamamlandi", "sonuc_ozeti": "x"},
                             {"id": 2, "amac": "b", "durum": "tamamlandi", "sartli": "denetleyici model yok"}]}
        rapor = yurutucu.Yurutucu._rapor(gorev)
        self.assertNotIn("Tamamlandı\n", rapor)
        self.assertIn("1 adım şartlı", rapor)
        self.assertIn("✓?", rapor)


class Siniflandirici(unittest.TestCase):
    def test_yanlis_pozitifler(self):
        s = yurutucu.siniflandir
        self.assertEqual(s("512 bayt okundu, beklenen 600", "", False), "mantik")
        self.assertEqual(s("HTTP 503 Service Unavailable", "", False), "ag")
        self.assertEqual(s("CUDA 12.4 sürümü ile derlendi ama sonuç yanlış", "", False), "mantik")
        self.assertEqual(s("CUDA out of memory", "", False), "kaynak")
        self.assertEqual(s("liste bulunamadı (sayfada ürün yok)", "", False), "mantik")
        self.assertEqual(s("dosya bulunamadı: rapor.txt", "", False), "veri")
        self.assertEqual(s("", "FileNotFoundError: x", False), "veri")

    def test_bagli_adim_bitmedi_veri_degil(self):
        self.assertEqual(yurutucu.BAGIMLILIK_SINIFI, "mantik")


class Depo(unittest.TestCase):
    def test_es_zamanli_kaydet_kilitli(self):
        depo = durum.Depo(Path(_GECICI) / "gorevler-test.db")
        gorev = {"gorev_id": "g1", "durum": "calisiyor", "istek": "x", "olusturma": "t", "adimlar": []}
        hatalar = []

        def yaz(n):
            try:
                for i in range(20):
                    depo.kaydet({**gorev, "sayac": f"{n}-{i}"})
            except Exception as e:  # pragma: no cover
                hatalar.append(e)

        isler = [threading.Thread(target=yaz, args=(n,)) for n in range(4)]
        for t in isler:
            t.start()
        for t in isler:
            t.join()
        self.assertEqual(hatalar, [])
        self.assertEqual(depo.getir("g1")["gorev_id"], "g1")
        self.assertTrue(hasattr(durum.Depo, "_kilit"))


class WebOku(unittest.TestCase):
    def test_yerel_ag_engeli(self):
        for url in ("http://localhost:11434/api/tags", "http://127.0.0.1/", "http://[::1]:8080/", "http://192.168.1.5/x",
                    "http://10.0.0.7/", "http://172.16.0.1/", "http://169.254.169.254/latest/meta-data"):
            with self.assertRaisesRegex(AracHatasi, "local|private|yerel", msg=url):
                web.oku(url)

    def _akis(self, govde: bytes, durum_kodu=200, tur="text/html"):
        class Cevap:
            status_code = durum_kodu
            headers = {"content-type": tur}

            def iter_bytes(self, chunk_size=65536):
                for i in range(0, len(govde), chunk_size):
                    yield govde[i:i + chunk_size]

        class CM:
            def __enter__(self_):
                return Cevap()

            def __exit__(self_, *a):
                return False

        return mock.patch.object(httpx, "stream", return_value=CM())

    def test_govde_siniri(self):
        buyuk = b"<title>T</title><p>" + b"a" * (web.EN_COK_BAYT + 100_000) + b"</p>"
        with self._akis(buyuk), mock.patch.object(web, "_adres_denetle"):
            metin = web.oku("http://ornek.test/")
        self.assertLessEqual(len(metin.encode()), web.EN_COK_BAYT + 1000)
        self.assertIn("kesildi", metin)  # kullanıcı/model gövdenin kısaltıldığını görür

    def test_normal_okuma(self):
        with self._akis(b"<title>T</title><p>g\xc3\xb6vde</p>"), mock.patch.object(web, "_adres_denetle"):
            self.assertEqual(web.oku("http://ornek.test/"), "T\n\ngövde")


class OpenAIZamanAsimi(unittest.TestCase):
    def test_okuma_zaman_asimi_150(self):
        self.assertEqual(openai_uyumlu.OKUMA_ZAMAN_ASIMI, 150)
        from types import SimpleNamespace

        s = openai_uyumlu.OpenAIUyumluSaglayici(SimpleNamespace(id="x", name="x", base_url="http://b", key="k",
                                                                models=["m"], usable=True))
        with mock.patch.object(httpx, "stream") as st:
            st.return_value.__enter__.return_value.status_code = 500
            st.return_value.__enter__.return_value.text = "x"
            with self.assertRaises(Exception):
                list(s.akis([{"role": "user", "content": "x"}]))
        zaman = st.call_args.kwargs["timeout"]
        self.assertEqual(zaman.read, 150)


class AyarTasima(unittest.TestCase):
    def test_ice_aktarma_aninda_tasinmaz_ilk_yuklemede_tasinir(self):
        kok = Path(tempfile.mkdtemp(prefix="tasima-", dir=_GECICI))
        (kok / "ayar" / "yerel-asistan").mkdir(parents=True)
        (kok / "ayar" / "yerel-asistan" / "ayarlar.json").write_text("{}", encoding="utf-8")
        kod = ("from pathlib import Path\nimport asistan.cekirdek.ayar as a\n"
               f"eski, yeni = Path({str(kok / 'ayar' / 'yerel-asistan')!r}), Path({str(kok / 'ayar' / 'yeni-nesil-cafer')!r})\n"
               "print(eski.exists(), yeni.exists())\na.Settings.load()\nprint(eski.exists(), yeni.exists())\n")
        python = str(KOK / ".venv" / "bin" / "python") if (KOK / ".venv" / "bin" / "python").is_file() else sys.executable
        s = subprocess.run([python, "-c", kod], cwd=KOK, capture_output=True, text=True, timeout=120,
                           env=dict(os.environ, XDG_CONFIG_HOME=str(kok / "ayar"), XDG_DATA_HOME=str(kok / "veri")))
        self.assertEqual(s.returncode, 0, s.stderr[-1500:])
        self.assertEqual(s.stdout.strip().splitlines(), ["True False", "False True"])


if __name__ == "__main__":
    unittest.main()
