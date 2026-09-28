"""Yazdı-ama-yapmadı (BÖLÜM 2): iş isteğinde araç çağırmadan duran model bir kez dürtülür, ikinci kez görev motoruna /
zincirdeki bir üst modele devredilir ya da tek satır dürüst mesaj yazılır. Dürtü metinleri kullanıcıya gösterilmez
(durum satırına gider); "Araç kullanmak ister misiniz?" gibi üst-sorular gerçek soru sayılmaz; Türkçe olmayan cevap
bir kez yeniden yazdırılır, ikincide sonraki model. Sınav ikinci varyantı ve sohbet penceresindeki tek tıkla rapor."""

import json
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

from asistan import agent as agent_mod, manager  # noqa: E402
from asistan.agent import PROGRAM, Agent, meta_soru, turkce_mi  # noqa: E402
from asistan.config import Settings  # noqa: E402


class _Cb:
    def __init__(self):
        self.text, self.durum, self.geri, self.notlar = "", [], 0, []

    def on_text(self, delta): self.text += delta
    def on_status(self, msg): self.durum.append(msg)
    def on_retract(self): self.geri += 1; self.text = ""
    def on_route(self, msg): self.notlar.append(msg)
    def on_thinking(self, *a): pass
    def on_model_start(self, *a): pass
    def on_model_end(self, *a): pass
    def on_tool_start(self, *a): pass
    def on_tool_end(self, *a): pass
    def ask_approval(self, name, args): return True
    def is_cancelled(self): return False


def ajan() -> tuple[Agent, _Cb]:
    cb = _Cb()
    a = Agent(Settings(workspace=str(Path(_GECICI) / "is")), cb)
    a._provider = "ollama"
    a.user_text = "notlar klasörü aç, içine a.txt yaz"
    return a, cb


class MetaSoru(unittest.TestCase):
    def test_izin_sorulari_soru_sayilmaz(self):
        for s in ("Araç kullanmak ister misiniz?", "Dosyaları oluşturmamı ister misin?", "Devam edeyim mi?",
                  "Şimdi başlayayım mı?", "Would you like me to create the files?", "Shall I proceed?",
                  "Bu adımları uygulayayım mı?"):
            self.assertTrue(meta_soru(s), s)

    def test_gercek_sorular_kalir(self):
        for s in ("Hangi klasöre yazayım?", "Dosyaların içine ne yazılsın?", "Kaç satır olsun?", "Boyut kaç mm?"):
            self.assertFalse(meta_soru(s), s)


class Dil(unittest.TestCase):
    def test_turkce(self):
        self.assertTrue(turkce_mi("Dosyaları oluşturdum: notlar/a.txt, b.txt ve c.txt. İçlerine kısa birer not yazdım."))
        self.assertTrue(turkce_mi("Tamam."))  # kısa metin yargılanmaz
        self.assertTrue(turkce_mi("Betik hazır:\n```python\nimport os\nfor f in files:\n    print(f)\n```\nÇalıştırdım, sonuç dosyada."))

    def test_ingilizce_ve_cince(self):
        self.assertFalse(turkce_mi("I have created the folder and the three files. Each file contains a short note "
                                   "and you can open them from the workspace."))
        self.assertFalse(turkce_mi("我已经创建了文件夹和三个文件，每个文件都包含一个简短的说明。"))


class Durtme(unittest.TestCase):
    def test_bir_kez_durt_sonra_devret(self):
        a, cb = ajan()
        content = "Şimdi notlar klasörünü oluşturuyorum ve dosyaları yazıyorum."
        state = {}
        n1 = a._unfinished_nudge([], content, True, 1, state)
        self.assertTrue(n1 and "Nothing was executed" in n1)
        self.assertNotIn("Şimdi gerçekten", cb.text)  # dürtü metni kullanıcıya gösterilmez
        self.assertTrue(cb.durum)  # durum satırına gider
        self.assertFalse(a.yapmadi)
        n2 = a._unfinished_nudge([], "1. klasör aç\n2. dosyaları yaz", True, 2, state)
        self.assertIsNone(n2)  # ikinci kez dürtülmez
        self.assertTrue(a.yapmadi)  # yönetici devralır

    def test_meta_soru_durtulur_gercek_soru_durtulmez(self):
        a, cb = ajan()
        self.assertIsNone(a._unfinished_nudge([], "Dosyaların içine ne yazılsın?", True, 1, {}))
        a2, _ = ajan()
        self.assertIsNotNone(a2._unfinished_nudge([], "Araç kullanmak ister misiniz?", True, 1, {}))

    def test_dil_denetimi(self):
        a, cb = ajan()
        state = {}
        en = "I created the folder and wrote the three files. You can open them now from the workspace folder."
        n = a._dil_denetimi(en, state)
        self.assertTrue(n and "Turkish" in n)
        self.assertEqual(cb.geri, 1)  # İngilizce metin baloncuktan geri alınır
        self.assertFalse(a.dil_hatasi)
        self.assertIsNone(a._dil_denetimi(en, state))  # ikinci kez: sonraki model
        self.assertTrue(a.dil_hatasi)
        b, _ = ajan()
        self.assertIsNone(b._dil_denetimi("Dosyaları oluşturdum ve içlerini yazdım.", {}))
        self.assertFalse(b.dil_hatasi)

    def test_bitti_denetimi_metni_gizli(self):
        a, cb = ajan()
        a.actions_tried, a.actions_done = 1, 0
        a.user_text = "rapor.txt dosyasını oluştur"
        n = a._unfinished_nudge([], "Rapor hazır.", True, 3, {})
        self.assertTrue(n and "NOT done" in n)
        self.assertNotIn("Henüz bitmedi", cb.text)


class _Olaylar(_Cb):
    pass


class Devir(unittest.TestCase):
    """Manager._direct: ajan `yapmadi` deyince görev motoru → zincirdeki üst model → dürüst tek satır."""

    def _yonetici(self):
        a, cb = ajan()
        m = manager.Manager(a)
        m.chat = m.worker = m.boss = ("ollama", "sahte")

        def run(provider, messages, text, step=""):
            messages.append({"role": "user", "content": text})
            cb.on_text("Şunları yapacağım: 1. klasör 2. dosyalar")
            messages.append({"role": "assistant", "content": "Şunları yapacağım"})
            a.yapmadi = True
        a.run = run
        return a, cb, m

    def test_motor_devralir(self):
        a, cb, m = self._yonetici()
        gelen = []
        m.motor = lambda msgs, text: gelen.append((list(msgs), text))
        msgs = []
        with mock.patch.object(m, "_hands"):
            m._direct("ollama", msgs, "notlar klasörü aç, içine a.txt yaz")
        self.assertEqual(len(gelen), 1)
        self.assertEqual(gelen[0][1], "notlar klasörü aç, içine a.txt yaz")
        self.assertEqual(gelen[0][0], [])  # konuşup bırakan tur geçmişten çıkar, motor kendi mesajını ekler
        self.assertEqual(cb.geri, 1)  # kullanıcı boş vaadi görmez
        self.assertFalse(a.yapmadi)

    def test_ust_model_devralir(self):
        a, cb, m = self._yonetici()
        alt = mock.Mock(provider="claude", model="guclu", key=("claude", "guclu"))
        sub_calls = []

        class _Sub:
            def __init__(self, settings, rel, *a_, **k):
                self.cb, self.pending_actions = rel, []
                self.toolbox = mock.Mock(read_roots=[])

            def run(self, provider, messages, text):
                sub_calls.append((provider, text))
                self.cb.on_text("Yaptım: notlar/a.txt oluşturuldu.")
        msgs = []
        with mock.patch.object(manager.roster, "stronger", return_value=alt), \
                mock.patch.object(manager, "Agent", _Sub), mock.patch.object(m, "_budget_ok", return_value=True):
            m._direct("ollama", msgs, "notlar klasörü aç, içine a.txt yaz")
        self.assertEqual(sub_calls[0][0], "claude")
        self.assertIn("notlar klasörü aç", sub_calls[0][1])
        self.assertEqual(msgs[-1]["role"], "assistant")
        self.assertIn("Yaptım", msgs[-1]["content"])
        self.assertIn("Yaptım", cb.text)
        self.assertTrue(any("guclu" in n for n in cb.notlar))

    def test_kimse_yoksa_durust_tek_satir(self):
        a, cb, m = self._yonetici()
        msgs = []
        with mock.patch.object(manager.roster, "stronger", return_value=None):
            m._direct("ollama", msgs, "notlar klasörü aç, içine a.txt yaz")
        self.assertEqual(msgs[-1]["role"], "assistant")
        self.assertIn("yapamadım", msgs[-1]["content"].lower())
        self.assertEqual(msgs[-1]["content"].count("\n"), 0)  # tek satır
        self.assertIn("yapamadım", cb.text.lower())


class Sinav(unittest.TestCase):
    def test_ikinci_varyant(self):
        sys.path.insert(0, str(KOK / "testler" / "sinav"))
        import denetim
        p = KOK / "testler" / "sinav" / "gorevler" / "yazdi-ama-yapmadi-2.json"
        g = json.loads(p.read_text(encoding="utf-8"))
        self.assertIn("denetleyici", g["istek"])
        self.assertEqual(denetim.dogrula(g), [])
        turler = {d["tur"] for d in g["bitti"]}
        self.assertEqual(turler, {"dosya_var", "arac_cagrildi"})
        self.assertTrue(any(d.get("yol", "").endswith("*.py") for d in g["bitti"]))
        self.assertNotEqual(g["sira"], 5)


class HizliRapor(unittest.TestCase):
    """Sohbet penceresindeki 🐞 düğmesi: önizlemesiz — rapor yazılır, Claude Code cümlesi panoya."""

    def test_onizlemesiz_yaz_ve_kopyala(self):
        os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
        from PySide6.QtWidgets import QApplication
        app = QApplication.instance() or QApplication([])
        from asistan import problem_report
        from asistan.gui import window_help

        class _P(window_help.HelpMixin):
            def __init__(self): self.bildirim = []
            def _notify(self, text, ms=0): self.bildirim.append(text)
        p = _P()
        yol = Path(_GECICI) / "rapor.md"
        with mock.patch.object(problem_report, "write", return_value=yol) as w, \
                mock.patch.object(problem_report, "redact", side_effect=lambda t: t), \
                mock.patch.object(problem_report, "claude_prompt", return_value="Şu raporu incele: rapor.md"):
            p._report_built("# rapor", "", None, preview=False)
        w.assert_called_once_with("# rapor")
        self.assertEqual(app.clipboard().text(), "Şu raporu incele: rapor.md")
        self.assertTrue(p.bildirim and "rapor" in p.bildirim[-1])


if __name__ == "__main__":
    unittest.main()
