"""K4 — araç seçici kipi (eski Aşama 3): araç sınavını tam geçemeyen yerel model iş yaparken tur karar (şema-kısıtlı
JSON) + programın araç çalıştırması olarak bölünür; 3/3 modellerde ve sohbet mesajında eski yol aynen kalır.
Model çağrıları sahte (`Agent.structured`, `_ollama_step`); araçlar gerçek Toolbox + izin hattıyla geçici klasörde.

Çalıştırma (proje kökünde, programın Python'uyla):
    ~/.local/share/yeni-nesil-cafer-app/python/bin/python3 -m unittest discover -s testler -v
"""

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

from asistan import agent as ag, cards, roster, specialists  # noqa: E402
from asistan.config import Settings  # noqa: E402


class _Cb:
    def __init__(self):
        self.text, self.tools = "", []

    def on_text(self, d): self.text += d
    def on_thinking(self, d): pass
    def on_model_start(self, s): pass
    def on_model_end(self, s): pass
    def on_tool_start(self, call_id, name, args): self.tools.append(name)
    def on_tool_end(self, *a): pass
    def ask_approval(self, *a): return True
    def is_cancelled(self): return False


def ajan(klasor: str) -> ag.Agent:
    s = Settings.load()
    s.workspace, s.ollama_model, s.approval_mode = klasor, "zayif:12b", "kullanici"
    a = ag.Agent(s, _Cb())
    a._provider = "ollama"
    return a


class SeciciTesti(unittest.TestCase):
    def setUp(self):
        self.klasor = tempfile.mkdtemp(dir=_GECICI)
        Path(self.klasor, "not.txt").write_text("gizli sayı 42", encoding="utf-8")

    def calistir(self, kararlar, istek="not.txt dosyasını oku ve sayıyı söyle"):
        a = ajan(self.klasor)
        sira = list(kararlar)
        cagrilar = []

        def structured(messages, schema, model=None, system=""):
            cagrilar.append((messages, schema, system))
            return sira.pop(0) if sira else {"eylem": "cevap", "gerekce": "bitti"}

        def son_cevap(url, system, messages, tools):
            a.cb.on_text("Sayı 42.")
            son_cevap.gorulen = messages
            return "Sayı 42.", [], {}

        mesajlar = []
        with mock.patch.object(roster, "arac_kipi", return_value="secici"), \
                mock.patch.object(specialists, "_capabilities", return_value=("completion",)), \
                mock.patch.object(a, "structured", side_effect=structured), \
                mock.patch.object(a, "_ollama_step", side_effect=son_cevap):
            a.run("ollama", mesajlar, istek)
        return a, mesajlar, cagrilar, son_cevap

    def test_karar_arac_program_calistirir_sonra_cevap_akar(self):
        a, mesajlar, cagrilar, son = self.calistir([
            {"eylem": "arac", "arac": "read_file", "argumanlar": {"path": "not.txt"}, "gerekce": "oku"}])
        self.assertEqual(a.cb.tools, ["read_file"])  # _execute_tool (izin hattı) üzerinden
        arac = [m for m in mesajlar if m.get("role") == "tool"]
        self.assertIn("gizli sayı 42", arac[0]["content"])
        self.assertEqual(mesajlar[-1], {"role": "assistant", "content": "Sayı 42."})
        # karar şeması: araç adı kayıtlı araçlardan enum
        enum = cagrilar[0][1]["properties"]["arac"]["enum"]
        self.assertIn("read_file", enum)
        self.assertNotIn("uydurma", enum)
        # araç şablonu olmayan modele sonuç düz metin gider
        self.assertTrue(any("[result of read_file]" in str(m.get("content")) for m in son.gorulen))
        self.assertFalse(any(m.get("role") == "tool" for m in son.gorulen))

    def test_argumanlar_uymazsa_aracin_semasiyla_ikinci_karar(self):
        _, _, cagrilar, _ = self.calistir([
            {"eylem": "arac", "arac": "read_file", "argumanlar": {"dosya": "not.txt"}, "gerekce": "oku"},
            {"path": "not.txt"}])
        self.assertIn("path", cagrilar[1][1]["properties"])  # ikinci çağrı read_file'ın kendi şeması
        self.assertIn("read_file", cagrilar[1][0][-1]["content"])

    def test_riskli_arac_izin_hattindan_gecer(self):
        a = ajan(self.klasor)
        a.cb.ask_approval = lambda *x: False  # kullanıcı reddetti
        sira = [{"eylem": "arac", "arac": "run_command", "argumanlar": {"command": "touch x", "purpose": "t"},
                 "gerekce": "g"}]
        with mock.patch.object(roster, "arac_kipi", return_value="secici"), \
                mock.patch.object(specialists, "_capabilities", return_value=()), \
                mock.patch.object(a, "structured", side_effect=lambda *x, **k: sira.pop(0) if sira else None), \
                mock.patch.object(a, "_ollama_step", return_value=("Yapamadım.", [], {})):
            mesajlar = []
            a.run("ollama", mesajlar, "x dosyası oluştur")
        self.assertFalse(Path(self.klasor, "x").exists())
        self.assertIn("declined", [m for m in mesajlar if m.get("role") == "tool"][0]["content"])

    def test_sohbet_mesajinda_ve_tam_modelde_secici_yok(self):
        a = ajan(self.klasor)
        with mock.patch.object(roster, "arac_kipi", return_value="secici"):
            a.user_text = "merhaba, nasılsın?"
            self.assertFalse(a._selector_turn())
            a.user_text = "not.txt dosyasını oku"
            self.assertTrue(a._selector_turn())
        with mock.patch.object(roster, "arac_kipi", return_value="yerlesik"):
            self.assertFalse(a._selector_turn())


class KipSecimiTesti(unittest.TestCase):
    def test_kart_ve_beyan(self):
        s = Settings.load()
        with mock.patch.object(cards, "tools_level", return_value=2):
            self.assertEqual(roster.arac_kipi(s, "m"), "yerlesik")
        with mock.patch.object(cards, "tools_level", return_value=1):
            self.assertEqual(roster.arac_kipi(s, "m"), "secici")
        with mock.patch.object(cards, "tools_level", return_value=None), \
                mock.patch.object(specialists, "_capabilities", return_value=("completion",)):
            self.assertEqual(roster.arac_kipi(s, "m"), "secici")  # araç desteklemiyor (gemma3, dolphin3)
        with mock.patch.object(cards, "tools_level", return_value=None), \
                mock.patch.object(specialists, "_capabilities", return_value=()):
            self.assertEqual(roster.arac_kipi(s, "m"), "yerlesik")  # bilinmiyor: eski yol


if __name__ == "__main__":
    unittest.main()
