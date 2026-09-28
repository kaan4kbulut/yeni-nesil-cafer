"""BÖLÜM 8 — `otomatik.py` sürücüsü: limit/zaman aşımı/boş/hata sınıfları, nazik zaman aşımı (SIGINT → bekle),
zaman aşımında yarım değişiklikler stash'e + KISMEN, ilk denemenin süresi, YAPILACAKLAR'da bölüm yoksa geçmiş
sayılmaz, SONUÇ satırı zorunlu, --python seçimi. Gerçek claude çağrılmaz."""

import importlib.util
import json
import os
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

KOK = Path(__file__).resolve().parent.parent
_spec = importlib.util.spec_from_file_location("otomatik_surucu", KOK / "otomatik.py")
o = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(o)


def git(repo, *a):
    return subprocess.run(["git", *a], cwd=repo, capture_output=True, text=True,
                          env={**os.environ, "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t", "GIT_COMMITTER_NAME": "t",
                               "GIT_COMMITTER_EMAIL": "t@t"}).stdout


class Siniflar(unittest.TestCase):
    def test_limit_mi(self):
        self.assertEqual(o.limit_mi(124, "yarım çıktı"), ("zaman_asimi", mock.ANY))
        self.assertEqual(o.limit_mi(0, "   ")[0], "bos")
        self.assertEqual(o.limit_mi(0, "You've hit your usage limit. Resets at 5pm")[0], "limit")
        self.assertEqual(o.limit_mi(1, "Error: not logged in")[0], "limit")
        self.assertEqual(o.limit_mi(2, "kısa hata")[0], "hata")
        self.assertEqual(o.limit_mi(0, "uzun normal çıktı " * 200 + "\nSONUÇ: TAMAM"), (None, ""))

    def test_sonuc_oku_zorunlu(self):
        self.assertIsNone(o.sonuc_oku("bir şeyler yaptım, bitti")["sonuc"])
        self.assertEqual(o.sonuc_oku("…\nSONUÇ: KISMEN\nTEST: kaldı (3 kırmızı)")["sonuc"], "KISMEN")
        self.assertTrue(o.sonuc_oku("SONUÇ: TAMAM\nTEST: kaldı")["test_kaldi"])

    def test_python_sec(self):
        self.assertEqual(o.python_sec("/x/python"), "/x/python")
        self.assertTrue(o.python_sec("").endswith(("python", "python3", "python.exe")))


class AcikKutular(unittest.TestCase):
    def test_bolum_yoksa_none(self):
        kok = Path(tempfile.mkdtemp())
        with mock.patch.object(o, "KOK", kok):
            self.assertIsNone(o.acik_kutular("K1"))  # dosya yok
            (kok / "YAPILACAKLAR.md").write_text("## Aşama K1 — x\n- [ ] a\n- [x] b\n- [ ] c\n\n## Aşama K2 — y\n- [ ] z\n"
                                                 "\n## Ölçüm defteri\n- [ ] sayılmaz\n", encoding="utf-8")
            self.assertEqual(o.acik_kutular("K1"), 2)
            self.assertEqual(o.acik_kutular("K2"), 1)  # sonraki başlık "## Ölçüm" olsa da bölüm orada biter
            self.assertIsNone(o.acik_kutular("K9"))


class NazikZamanAsimi(unittest.TestCase):
    def test_sigint_ile_durur_cikti_korunur(self):
        betik = ("import signal, sys, time\n"
                 "def d(*a):\n    print('SIGINT alindi, toparlaniyorum'); sys.stdout.flush(); sys.exit(0)\n"
                 "signal.signal(signal.SIGINT, d)\nprint('basladi'); sys.stdout.flush()\ntime.sleep(30)\n")
        t0 = time.time()
        kod, cikti = o.calistir_nazik([sys.executable, "-c", betik], girdi="", zaman_asimi=1, bekleme=10)
        self.assertEqual(kod, 124)
        self.assertIn("basladi", cikti)
        self.assertIn("SIGINT alindi", cikti)  # öldürülmedi: toparlanıp çıktı
        self.assertLess(time.time() - t0, 12)

    def test_sigint_dinlemeyen_oldurulur(self):
        betik = "import signal, time\nsignal.signal(signal.SIGINT, signal.SIG_IGN)\nsignal.signal(signal.SIGTERM, signal.SIG_IGN)\ntime.sleep(60)\n"
        kod, cikti = o.calistir_nazik([sys.executable, "-c", betik], girdi="", zaman_asimi=0.5, bekleme=1)
        self.assertEqual(kod, 124)
        self.assertIn("öldürüldü", cikti)


class Durdurma(unittest.TestCase):
    def setUp(self):
        self.repo = Path(tempfile.mkdtemp(prefix="oto-"))
        git(self.repo, "init", "-q")
        git(self.repo, "config", "user.email", "t@t")
        git(self.repo, "config", "user.name", "t")
        (self.repo / "a.txt").write_text("1", encoding="utf-8")
        git(self.repo, "add", "-A")
        git(self.repo, "commit", "-q", "-m", "ilk")
        (self.repo / ".cafer").mkdir()
        (self.repo / "NOTLAR").mkdir()
        self.yamalar = [mock.patch.object(o, "KOK", self.repo), mock.patch.object(o, "DURUM", self.repo / ".cafer" / "otomatik.json"),
                        mock.patch.object(o, "KONTROL_LISTEN", self.repo / "NOTLAR" / "KONTROL_LISTEN.md"),
                        mock.patch.object(o, "bildir", lambda *a, **k: None)]
        for y in self.yamalar:
            y.start()
            self.addCleanup(y.stop)
        # git() sürücüde KOK'ta koşar: cwd yamalı KOK olsun
        orijinal = o.calistir
        self.addCleanup(setattr, o, "calistir", orijinal)
        o.calistir = lambda cmd, cwd=None, **k: orijinal(cmd, cwd=self.repo, **k)

    def test_zaman_asiminda_stash_ve_kismen(self):
        (self.repo / "a.txt").write_text("2", encoding="utf-8")
        (self.repo / "yeni.py").write_text("x = 1\n", encoding="utf-8")
        self.assertFalse(o.asama_durdur("K3", "zaman aşımı", "zaman_asimi", 42.0))
        self.assertEqual(git(self.repo, "status", "--porcelain", "--", ".", ":!.cafer", ":!NOTLAR").strip(), "")  # kod temiz: stash'e gitti (sürücü dosyaları hariç)
        self.assertIn("K3: zaman aşımı", git(self.repo, "stash", "list"))
        self.assertIn("ilk", git(self.repo, "log", "-1", "--format=%s"))  # yarım commit YOK
        d = json.loads((self.repo / ".cafer" / "otomatik.json").read_text())
        self.assertEqual((d["durum"], d["durma_sinifi"], d["yarim_sureler"]["K3"]), ("KISMEN", "zaman_asimi", 42.0))
        self.assertIn("git stash pop", (self.repo / "NOTLAR" / "KONTROL_LISTEN.md").read_text(encoding="utf-8"))

    def test_limitte_yarim_commit(self):
        (self.repo / "a.txt").write_text("3", encoding="utf-8")
        self.assertFalse(o.asama_durdur("K4", "limit doldu", "limit", 5.0))
        self.assertIn("K4: yarım", git(self.repo, "log", "-1", "--format=%s"))
        self.assertEqual(git(self.repo, "stash", "list").strip(), "")
        self.assertEqual(json.loads((self.repo / ".cafer" / "otomatik.json").read_text())["durum"], "KALDI")

    def test_deneme_sureleri(self):
        o.deneme_kaydet("K2", "kosu1", 12.34, None)
        o.deneme_kaydet("K2", "duzeltme1", 3.0, "zaman_asimi")
        d = json.loads((self.repo / ".cafer" / "otomatik.json").read_text())
        self.assertEqual([x["ad"] for x in d["denemeler"]["K2"]], ["kosu1", "duzeltme1"])
        self.assertEqual(d["denemeler"]["K2"][0]["sure"], 12.3)


if __name__ == "__main__":
    unittest.main()
