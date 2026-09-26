"""Model kartları ve yönlendirici testleri: sınav değerlendirmesi, işçi / yönetici seçimi (sahte kartlarla)."""

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

from asistan import cards, roster  # noqa: E402
from asistan.roster import Candidate  # noqa: E402

KARTLAR = {
    "gemma4:12b": {"tools": 2, "plan": True, "turkish": True},
    "huihui_ai/gemma-4-abliterated:12b": {"tools": 1, "plan": True, "turkish": True},
    "huihui_ai/qwen3.5-abliterated:4b": {"tools": 2, "plan": True, "turkish": True},
    "qwen3.5:4b": {"tools": 2, "plan": True, "turkish": True},
    "gemma3:12b": {"tools": 0, "plan": False, "turkish": True},
}
ADAYLAR = [Candidate("ollama", m, {"tools"} if KARTLAR[m]["tools"] else set(), score, local=True)
           for m, score in (("gemma4:12b", 20), ("huihui_ai/gemma-4-abliterated:12b", 20),
                            ("huihui_ai/qwen3.5-abliterated:4b", 12), ("qwen3.5:4b", 12), ("gemma3:12b", 15))]


class Sinav(unittest.TestCase):
    def test_turkce_olcutu(self):
        self.assertTrue(cards.is_turkish("Çayı demliğe koyup üzerine kaynar su dökün ve bir süre bekleyin."))
        self.assertFalse(cards.is_turkish("Put the tea in the pot and pour boiling water with care."))
        self.assertFalse(cards.is_turkish("茶を入れて、お湯を注ぎます。"))

    def test_arac_cagrisi_degerlendirme(self):
        ok = {"message": {"tool_calls": [{"function": {"name": "write_file",
                                                        "arguments": {"path": "sinav.txt", "content": "merhaba"}}}]}}
        self.assertTrue(cards._tool_ok(ok, {"write_file"}, "sinav.txt"))
        self.assertFalse(cards._tool_ok(ok, {"run_python"}, "sinav.txt"))
        yazdi = {"message": {"content": "```python\nopen('sinav.txt','w').write('merhaba')\n```"}}
        self.assertFalse(cards._tool_ok(yazdi, {"write_file", "run_python"}, "sinav.txt"))  # yazdı ama yapmadı


class Yonlendirici(unittest.TestCase):
    def setUp(self):
        self.s = mock.Mock(model_policy="yerel", ollama_url="")
        patches = [mock.patch.object(roster, "candidates", return_value=ADAYLAR),
                   mock.patch.object(cards, "card", side_effect=lambda m: KARTLAR.get(m)),
                   mock.patch.object(cards, "tools_level", side_effect=lambda m: (KARTLAR.get(m) or {}).get("tools"))]
        for p in patches:
            p.start()
            self.addCleanup(p.stop)

    def test_araci_kullanan_model_kendi_isini_yapar(self):
        self.assertEqual(roster.worker_for(self.s, ("ollama", "gemma4:12b")), ("ollama", "gemma4:12b"))

    def test_sansursuz_gemma_isi_sansursuz_iscisine_verir(self):
        self.assertEqual(roster.worker_for(self.s, ("ollama", "huihui_ai/gemma-4-abliterated:12b")),
                         ("ollama", "huihui_ai/qwen3.5-abliterated:4b"))

    def test_aracsiz_model_normal_isci_alir(self):
        self.assertEqual(roster.worker_for(self.s, ("ollama", "gemma3:12b")), ("ollama", "gemma4:12b"))

    def test_bulut_modeli_kendisi(self):
        self.assertEqual(roster.worker_for(self.s, ("claude", "x")), ("claude", "x"))

    def test_plan_yapamayan_model_yerine_yonetici(self):
        self.assertEqual(roster.manager_for(self.s, ("ollama", "gemma3:12b")), ("ollama", "gemma4:12b"))
        self.assertEqual(roster.manager_for(self.s, ("ollama", "qwen3.5:4b")), ("ollama", "qwen3.5:4b"))


if __name__ == "__main__":
    unittest.main()


class Kategoriler(unittest.TestCase):
    def test_yedi_kategori_ve_ajanlari(self):
        from asistan import categories
        from asistan.profiles import AgentProfile, default_profiles

        self.assertEqual(len(categories.CATEGORIES), 7)
        profiles = default_profiles()
        self.assertTrue(categories.upgrade(profiles))
        by_id = {p.id: p for p in profiles}
        for cat in categories.CATEGORIES:
            self.assertIn(cat.agents[0], by_id, cat.id)  # her kategorinin bir ajanı var
            self.assertEqual(by_id[cat.agents[0]].category, cat.id)
        self.assertEqual(by_id["dosya"].category, "")  # kategorisiz yardımcı kalır
        self.assertFalse(categories.upgrade(profiles))  # ikinci kez bir şey değişmez
        self.assertIsInstance(AgentProfile(name="x").category, str)

    def test_kategori_modeli_kurulu_ve_arac_kullanan(self):
        from asistan import categories, power

        s = mock.Mock(ollama_url="")
        veri = categories.BY_ID["veri"]  # qwen2.5-coder:14b, qwen3.5:9b, gemma4:12b
        with mock.patch.object(power, "saving", return_value=False), \
                mock.patch.object(cards, "tools_level", side_effect=lambda m: {"gemma4:12b": 2, "qwen3.5:9b": 0}.get(m)), \
                mock.patch("asistan.specialists._capabilities", return_value=("tools",)):
            self.assertEqual(categories.model_for(s, veri, {"gemma4:12b"}), ("ollama", "gemma4:12b"))
            self.assertEqual(categories.model_for(s, veri, {"qwen2.5-coder:14b", "gemma4:12b"}),
                             ("ollama", "qwen2.5-coder:14b"))  # kartsız ama "tools" beyanı var: listede önde
            self.assertEqual(categories.model_for(s, veri, {"qwen3.5:9b", "gemma4:12b"}),
                             ("ollama", "gemma4:12b"))  # sınavda araç çağırmayan atlanır
            self.assertIsNone(categories.model_for(s, veri, set()))
        with mock.patch.object(power, "saving", return_value=True), \
                mock.patch.object(cards, "tools_level", return_value=2):
            self.assertEqual(categories.model_for(s, categories.BY_ID["dil"], {"gemma4:12b", "qwen3.5:4b"}),
                             ("ollama", "qwen3.5:4b"))  # pilde büyük model yerine küçüğü
