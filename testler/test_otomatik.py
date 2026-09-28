"""BÖLÜM 8 + token tasarrufu — `otomatik.py` sürücüsü: model seçimi (sonnet/opus/haiku), kesin limit ifadeleri +
sıfırlanma saati + stash, alt başlık oturumları, denetçi SONUÇ satırı, son 10 madde, test süzgeci kancası; limit/zaman aşımı/boş/hata sınıfları, nazik zaman aşımı (SIGINT → bekle),
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

    def test_limit_kesin_ifadeler_uzunluga_bakmaz(self):
        """3b: "hit your session/weekly limit" ve "usage limit" uzun çıktının ortasında da limittir."""
        uzun = "çok iş yaptım " * 500
        for metin in ("You've hit your session limit. Resets 5pm", "You have hit your weekly limit",
                      "Error: usage limit exceeded for this organization"):
            sinif, neden = o.limit_mi(0, uzun + "\n" + metin + "\n" + uzun)
            self.assertEqual(sinif, "limit", metin)
            self.assertIn("limit", neden.lower())
        self.assertEqual(o.limit_mi(0, uzun + "\nSONUÇ: TAMAM"), (None, ""))

    def test_sifirlanma_zamani(self):
        simdi = time.mktime((2026, 9, 28, 13, 0, 0, 0, 0, -1))
        z = o.sifirlanma_zamani("You've hit your limit · resets at 5pm (Europe/Istanbul)", simdi)
        self.assertEqual(time.strftime("%d %H:%M", time.localtime(z)), "28 17:00")
        z = o.sifirlanma_zamani("limit reached, resets 3:30pm", simdi)
        self.assertEqual(time.strftime("%d %H:%M", time.localtime(z)), "28 15:30")
        z = o.sifirlanma_zamani("resets at 9am", simdi)  # geçmiş saat → yarın
        self.assertEqual(time.strftime("%d %H:%M", time.localtime(z)), "29 09:00")
        z = o.sifirlanma_zamani("Your limit will reset in 2 hours", simdi)
        self.assertEqual(z, simdi + 7200)
        self.assertIsNone(o.sifirlanma_zamani("hit your limit", simdi))

    def test_model_sec(self):
        self.assertEqual(o.model_sec("Görev motoru"), "sonnet")
        self.assertEqual(o.model_sec("Mimari yeniden düzenleme"), "opus")
        self.assertEqual(o.model_sec("Mimari", "haiku"), "haiku")

    def test_denetci_sonuc(self):
        self.assertEqual(o.denetci_sonuc("## Sonuç: GEÇTİ\n### Uyarı\n- x")[0], "GECTI")
        self.assertEqual(o.denetci_sonuc("bla\n## Sonuç: **KALDI**\n- a")[0], "KALDI")
        self.assertEqual(o.denetci_sonuc("Sonuc: SARTLI")[0], "SARTLI")
        self.assertEqual(o.denetci_sonuc("rapor yok"), (None, ""))

    def test_p_asama_ve_p_denetci_tuple(self):
        self.assertEqual(o.p_asama("K3", "ek"), ("asama", "K3", "ek"))
        self.assertEqual(o.p_denetci("K4")[:2], ("denetci", "K4"))
        self.assertIn("git diff k4-basi", o.p_denetci_metni("K4", "odak x"))
        self.assertIn("odak x", o.p_denetci_metni("K4", "odak x"))

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

    def test_alt_basliklar(self):
        """3c: `###` alt başlıkları ayrı oturum; ilk öğe ana maddeler; `###` yoksa boş liste."""
        kok = Path(tempfile.mkdtemp())
        (kok / "YAPILACAKLAR.md").write_text(
            "## Aşama K1 — x\n- [ ] a\n- [x] b\n\n### Alt bir\n- [ ] c\n- [ ] d\n\n### Alt iki ☐\n- [x] e\n\n"
            "## Aşama K2 — y\n- [ ] z\n", encoding="utf-8")
        with mock.patch.object(o, "KOK", kok):
            self.assertEqual(o.alt_basliklar("K1"), [("ana maddeler", 1), ("Alt bir", 2), ("Alt iki ☐", 0)])
            self.assertEqual(o.alt_basliklar("K2"), [])
            self.assertEqual(o.alt_basliklar("K7"), [])

    def test_son_maddeler_ve_onsoz(self):
        """3e: SORULAR/KONTROL_LISTEN'in tamamı değil son 10 maddesi isteme girer."""
        kok = Path(tempfile.mkdtemp())
        sorular = kok / "SORULAR.md"
        sorular.write_text("# Sorular\n" + "".join(f"- K{i} | soru {i} | karar\n" for i in range(25)) + "\nson satır\n",
                           encoding="utf-8")
        m = o.son_maddeler(sorular)
        self.assertEqual(len(m), 10)
        self.assertEqual(m[0], "- K15 | soru 15 | karar")
        self.assertEqual(m[-1], "- K24 | soru 24 | karar")
        self.assertEqual(o.son_maddeler(kok / "yok.md"), [])
        with mock.patch.object(o, "SORULAR", sorular), mock.patch.object(o, "KONTROL_LISTEN", kok / "yok.md"):
            metin = o.onsoz()
            self.assertTrue(metin.startswith(o.ONSOZ))
            self.assertIn("son 10 madde", metin)
            self.assertIn("soru 24", metin)
            self.assertNotIn("soru 3 |", metin)


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


class ClaudeKomutu(unittest.TestCase):
    def test_model_ve_zaman_asimi_komuta_gecer(self):
        """3a: `claude -p --model <model>`; oturuma özel dakika → saniye."""
        kok = Path(tempfile.mkdtemp())
        (kok / "NOTLAR").mkdir()
        gorulen = {}

        def sahte(cmd, girdi=None, zaman_asimi=None, **k):
            gorulen["cmd"], gorulen["zaman"] = cmd, zaman_asimi
            return 0, "SONUÇ: TAMAM"

        args = SimpleNamespace(tam_yetki=False, zaman_asimi=0)
        with mock.patch.object(o, "KOK", kok), mock.patch.object(o, "LOGLAR", kok / "NOTLAR" / "otomatik"), \
                mock.patch.object(o, "calistir_nazik", sahte), mock.patch.object(o, "claude_yolu", lambda: "claude"):
            o.claude_kos("K1", "istem", args, ad="t", model="haiku", zaman_asimi_dk=20)
            self.assertEqual(gorulen["cmd"][:7], ["claude", "-p", "--output-format", "text", "--model", "haiku", "--permission-mode"])
            self.assertEqual(gorulen["zaman"], 1200)
            o.claude_kos("K1", "istem", args, ad="t")
            self.assertIn("sonnet", gorulen["cmd"])
            self.assertIsNone(gorulen["zaman"])
            self.assertTrue(o.SON_LOG and o.SON_LOG.exists() and "MODEL sonnet" in o.SON_LOG.read_text(encoding="utf-8"))

    def test_limit_bekle_kisa(self):
        t0 = time.time()
        with mock.patch.object(o, "yaz", lambda *a, **k: None):
            o.limit_bekle(time.time() + 0.3, pay_sn=0)
        self.assertLess(time.time() - t0, 5)


class TestSuzgeciKancasi(unittest.TestCase):
    """`.claude/hooks/test-suz.sh`: pytest/unittest komutları süzgece bağlanır, diğerlerine dokunulmaz."""
    KANCA = KOK / ".claude" / "hooks" / "test-suz.sh"

    def kos(self, komut: str) -> str:
        p = subprocess.run([str(self.KANCA)], input=json.dumps({"tool_input": {"command": komut}}),
                           capture_output=True, text=True)
        self.assertEqual(p.returncode, 0, p.stderr)
        return p.stdout.strip()

    def test_test_komutlari_suzulur(self):
        self.assertTrue(os.access(self.KANCA, os.X_OK))
        for komut in ("pytest testler -q", "python -m pytest testler/test_ayar.py -x",
                      "QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest testler -q",
                      "cd /tmp && python3 -m unittest discover -s testler"):
            cikti = json.loads(self.kos(komut))
            yeni = cikti["hookSpecificOutput"]["updatedInput"]["command"]
            self.assertEqual(cikti["hookSpecificOutput"]["hookEventName"], "PreToolUse")
            self.assertTrue(yeni.startswith("{ " + komut + "; } 2>&1 | grep -A5 -E '(FAIL|ERROR|error:|passed|failed"), yeni)
            self.assertTrue(yeni.endswith("| head -80"), yeni)

    def test_digerlerine_dokunmaz(self):
        for komut in ("ls -la", "python otomatik.py --asama K3", "pytest -q | tail -3", "git status", "",
                      "python -m pytest testler > /tmp/x.log"):
            self.assertEqual(self.kos(komut), "", komut)


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

    def test_limitte_commit_yok_stash_ve_geri_alma(self):
        """3b: limitte commit ATILMAZ; yarım değişiklikler stash'e, sıfırlanma saati kaydedilir; aşama yeniden
        başlarken `limit_stash_geri_al` geri koyar."""
        (self.repo / "a.txt").write_text("3", encoding="utf-8")
        with mock.patch.object(o, "LOGLAR", self.repo / "NOTLAR" / "otomatik"):
            self.assertFalse(o.asama_durdur("K4", "limit doldu", "limit", 5.0,
                                            cikti="You've hit your session limit · resets at 11:30pm (Europe/Istanbul)"))
        self.assertIn("ilk", git(self.repo, "log", "-1", "--format=%s"))  # commit YOK
        self.assertIn("K4: limit (otomatik)", git(self.repo, "stash", "list"))
        d = json.loads((self.repo / ".cafer" / "otomatik.json").read_text())
        self.assertEqual((d["durum"], d["durma_sinifi"]), ("KISMEN", "limit"))
        self.assertGreater(d["limit_sifirlanma"], time.time())
        self.assertIn("23:30", (self.repo / "NOTLAR" / "KONTROL_LISTEN.md").read_text(encoding="utf-8"))
        self.assertIn("K4", (self.repo / "NOTLAR" / "otomatik" / "limit.log").read_text(encoding="utf-8"))
        self.assertEqual((self.repo / "a.txt").read_text(encoding="utf-8"), "1")  # çalışma ağacı temiz
        self.assertTrue(o.limit_stash_geri_al("K4"))
        self.assertEqual((self.repo / "a.txt").read_text(encoding="utf-8"), "3")  # yarım iş geri geldi
        self.assertFalse(o.limit_stash_geri_al("K4"))  # ikinci kez yok

    def test_hata_sinifinda_yarim_commit_surer(self):
        (self.repo / "a.txt").write_text("4", encoding="utf-8")
        self.assertFalse(o.asama_durdur("K4", "claude 2 ile çıktı", "hata", 5.0))
        self.assertIn("K4: yarım", git(self.repo, "log", "-1", "--format=%s"))

    def test_deneme_sureleri(self):
        o.deneme_kaydet("K2", "kosu1", 12.34, None)
        o.deneme_kaydet("K2", "duzeltme1", 3.0, "zaman_asimi")
        d = json.loads((self.repo / ".cafer" / "otomatik.json").read_text())
        self.assertEqual([x["ad"] for x in d["denemeler"]["K2"]], ["kosu1", "duzeltme1"])
        self.assertEqual(d["denemeler"]["K2"][0]["sure"], 12.3)


if __name__ == "__main__":
    unittest.main()
