"""Güçlü modele devretme: roster.stronger (seçim) ve Manager._escalate (temiz alt ajanla yeniden deneme).

Gerçek modele gidilmez: aday listesi, kartlar ve alt ajanın çalışması sahte.

Çalıştırma (proje kökünde, programın Python'uyla):
    ~/.local/share/yeni-nesil-cafer-app/python/bin/python3 -m unittest discover -s testler -v
"""

import os
import sys
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path
from unittest import mock

KOK = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(KOK))

_GECICI = tempfile.mkdtemp(prefix="yeni-nesil-cafer-test-")
os.environ["XDG_CONFIG_HOME"] = str(Path(_GECICI) / "ayar")
os.environ["XDG_DATA_HOME"] = str(Path(_GECICI) / "veri")

from asistan import manager as mg  # noqa: E402
from asistan import roster  # noqa: E402
from asistan.agent import Agent  # noqa: E402
from asistan.config import Settings  # noqa: E402

C = roster.Candidate
ADAYLAR = [C("ollama", "qwen3.5:4b", {"tools"}, 8, True), C("ollama", "qwen3.5:9b", {"tools"}, 14, True),
           C("ollama", "gemma4:12b", {"tools"}, 23, True), C("ollama", "qwen2.5-coder:14b", {"code"}, 30, True),
           C("ollama", "zayif:12b", {"tools"}, 25, True), C("api:gemini", "gemini-3-flash", {"tools"}, 90),
           C("ollama", "huihui_ai/qwen3.5-abliterated:4b", {"tools"}, 9, True)]
KART = {"qwen3.5:4b": 2, "qwen3.5:9b": 2, "gemma4:12b": 2, "zayif:12b": 1, "huihui_ai/qwen3.5-abliterated:4b": 2}


def secim(current: str, policy: str = "yerel"):
    from asistan.cekirdek import yonlendirici

    with mock.patch.object(roster, "candidates", return_value=ADAYLAR), \
            mock.patch.object(roster.cards, "tools_level", side_effect=lambda m: KART.get(m)), \
            mock.patch.object(yonlendirici, "cevrimici", return_value=True):  # K3: çevrimdışıyken bulut yok
        c = roster.stronger(Settings(model_policy=policy), ("ollama", current))
    return c.model if c else None


class SecimTesti(unittest.TestCase):
    def test_yerel_politikada_en_guclu_yerel(self):
        self.assertEqual(secim("qwen3.5:4b"), "gemma4:12b")  # zayif:12b (4/6) ve kod modeli (araçsız) atlanır

    def test_guclu_politikada_bulut(self):
        self.assertEqual(secim("qwen3.5:4b", "guclu"), "gemini-3-flash")

    def test_en_gucluden_sonrasi_yok(self):
        self.assertIsNone(secim("gemma4:12b"))

    def test_sansursuz_normale_gecmez(self):
        self.assertIsNone(secim("huihui_ai/qwen3.5-abliterated:4b"))


class _Cb:
    def __init__(self):
        self.text = ""

    def on_text(self, d): self.text += d
    def on_tool_start(self, *a): pass
    def on_tool_end(self, *a): pass
    def ask_approval(self, *a): return True
    def is_cancelled(self): return False


class DevretmeTesti(unittest.TestCase):
    def setUp(self):
        cb = _Cb()
        self.cb = cb
        a = Agent(Settings(workspace=str(Path(_GECICI) / "is"), ollama_model="qwen3.5:4b"), cb)
        a._provider = "ollama"
        self.m = mg.Manager(a)
        self.step = {"title": "Rapor", "do": "rapor.docx yaz", "done_when": "rapor.docx var", "status": "running"}
        self.m.plan = [self.step]

    def test_guclu_model_temiz_alt_ajanla_dener(self):
        gorev = {}

        def calis(sub, provider, messages, text, step=""):
            gorev.update(provider=provider, model=sub.settings.ollama_model, gecmis=list(messages), text=text)
            sub.cb.on_text("gemma yaptı")

        with mock.patch.object(mg.roster, "stronger", return_value=C("ollama", "gemma4:12b", {"tools"}, 23, True)), \
                mock.patch.object(Agent, "run", autospec=True, side_effect=calis), \
                mock.patch.object(self.m, "check", return_value=(True, "")):
            self.assertTrue(self.m._escalate("rapor yaz", 0, self.step, "dosya yok", self.cb))
        self.assertEqual((gorev["provider"], gorev["model"]), ("ollama", "gemma4:12b"))
        self.assertEqual(gorev["gecmis"], [])  # temiz bağlam: sohbet geçmişi aktarılmadı
        self.assertIn("dosya yok", gorev["text"])  # neden olmadığı anlatıldı
        self.assertEqual(self.step["status"], "done")
        self.assertIn("gemma4:12b devralıyor", self.cb.text)

    def test_daha_guclu_yoksa_bir_kez_oneri(self):
        with mock.patch.object(mg.roster, "stronger", return_value=None):
            self.assertFalse(self.m._escalate("x", 0, self.step, "olmadı", self.cb))
            self.assertFalse(self.m._escalate("x", 0, self.step, "olmadı", self.cb))
        self.assertEqual(self.cb.text.count("model politikasını"), 1)

    def test_guclu_politikada_oneri_yok(self):
        self.m.agent.settings = replace(self.m.agent.settings, model_policy="guclu")
        with mock.patch.object(mg.roster, "stronger", return_value=None):
            self.m._escalate("x", 0, self.step, "olmadı", self.cb)
        self.assertNotIn("model politikasını", self.cb.text)


if __name__ == "__main__":
    unittest.main()
