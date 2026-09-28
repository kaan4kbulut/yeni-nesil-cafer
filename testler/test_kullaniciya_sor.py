"""`kullaniciya_sor(soru)` aracı (sohbet yolu): model çağırınca tur biter, sohbet "cevap bekliyor" durumuna geçer, sonraki
kullanıcı mesajı aynı bağlamla modele cevap olarak gider; dürtü mekanizması bunu "yapmadı" saymaz. Arayüz sinyali motor
yolundaki soruyla aynı: soru metni `on_text` ile baloncuğa yazılır (seçenekler madde olarak → tıklanabilir baloncuk)."""

import os
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

KOK = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(KOK))
_GECICI = tempfile.mkdtemp(prefix="yeni-nesil-cafer-test-")
os.environ["XDG_CONFIG_HOME"] = str(Path(_GECICI) / "ayar")
os.environ["XDG_DATA_HOME"] = str(Path(_GECICI) / "veri")

from asistan import choices, permissions as p, storage  # noqa: E402
from asistan.agent import PROGRAM, Agent  # noqa: E402
from asistan.config import Settings  # noqa: E402
from asistan.registry import REGISTRY  # noqa: E402


class _Cb:
    def __init__(self):
        self.text, self.asked = "", []

    def on_text(self, delta): self.text += delta
    def on_thinking(self, *a): pass
    def on_model_start(self, *a): pass
    def on_model_end(self, *a): pass
    def on_tool_start(self, *a): pass
    def on_tool_end(self, *a): pass
    def ask_approval(self, name, args): self.asked.append(name); return True
    def is_cancelled(self): return False


def ajan(**ayar) -> tuple[Agent, _Cb]:
    cb = _Cb()
    a = Agent(Settings(workspace=str(Path(_GECICI) / "is"), **ayar), cb)
    a._provider = "ollama"
    return a, cb


class Kayit(unittest.TestCase):
    def test_arac_kayitli_ve_onaysiz(self):
        t = REGISTRY.get("kullaniciya_sor")
        self.assertIsNotNone(t)
        self.assertEqual(t.risk, "danisir")
        self.assertIn("kullaniciya_sor", [s["name"] for s in REGISTRY.specs("herkes")])
        for ctx in (p.Context(approval_mode="kullanici"), p.Context(approval_mode="guvenlik"),
                    p.Context(approval_mode="kullanici", must_act=True), p.Context(gate_actions=True)):
            self.assertEqual(p.decide("kullaniciya_sor", {"soru": "Hangi boy?"}, ctx).kind, p.ALLOW)


class Arac(unittest.TestCase):
    def test_soru_metni_ve_tur_sonu(self):
        a, cb = ajan()
        sonuc, hata = a._execute_tool("1", "kullaniciya_sor", {"soru": "Hangi boy?", "secenekler": ["S", "M", "L"]})
        self.assertFalse(hata)
        self.assertIn("ends now", sonuc)
        self.assertEqual(a.bekleyen_soru, "Hangi boy?\n- S\n- M\n- L")
        self.assertIn("Hangi boy?", cb.text)
        self.assertEqual(choices.parse(cb.text), ["S", "M", "L"])  # arayüz: tıklanabilir baloncuklar
        mesajlar = [{"role": "user", "content": "kutu yap"}]
        self.assertTrue(a._soru_ile_bitti(mesajlar))
        self.assertEqual(mesajlar[-1], {"role": "assistant", "content": "Hangi boy?\n- S\n- M\n- L"})
        self.assertIsNone(a._unfinished_nudge(mesajlar, "", True, 1, {}))  # dürtülmez
        self.assertEqual(cb.asked, [])

    def test_bos_soru_hata(self):
        a, cb = ajan()
        sonuc, hata = a._execute_tool("1", "kullaniciya_sor", {"soru": "  "})
        self.assertTrue(hata)
        self.assertFalse(a.bekleyen_soru)
        self.assertFalse(a._soru_ile_bitti([]))

    def test_ollama_dongusu_soruda_durur(self):
        a, cb = ajan()
        cagri = {"id": "c1", "function": {"name": "kullaniciya_sor", "arguments": {"soru": "Kaç adet?", "secenekler": ["1", "2"]}}}
        adimlar = []

        def sahte_step(url, system, messages, tools):
            adimlar.append(len(messages))
            return "", [cagri], {"done_reason": "stop"}

        with mock.patch.object(a, "_ollama_step", sahte_step), mock.patch.object(a, "_selector_turn", return_value=False):
            mesajlar = [{"role": "user", "content": "kutu yap"}]
            a._run_ollama(mesajlar)
        self.assertEqual(len(adimlar), 1)  # ikinci model çağrısı yok: tur soruyla bitti
        self.assertEqual(mesajlar[-1]["role"], "assistant")
        self.assertIn("Kaç adet?", mesajlar[-1]["content"])
        self.assertEqual(mesajlar[-2]["role"], "tool")

    def test_cevap_ayni_baglamla_gider(self):
        a, cb = ajan()
        a.cevaplanan_soru = "Hangi boy?\n- S\n- M"
        mesajlar = [{"role": "user", "content": "kutu yap"}, {"role": "assistant", "content": "Hangi boy?\n- S\n- M"}]
        with mock.patch.object(a, "_run_ollama", lambda m: None), mock.patch.object(a, "_hook",
                                                                                     return_value=SimpleNamespace(blocked=False, message="")):
            a.run("ollama", mesajlar, "M")
        self.assertEqual(mesajlar[-1], {"role": "user", "content": "M"})
        self.assertTrue(mesajlar[-2].get(PROGRAM))
        self.assertIn("Hangi boy?", mesajlar[-2]["content"])
        self.assertFalse(a.cevaplanan_soru)  # bir kez kullanılır


class SohbetKaydi(unittest.TestCase):
    def test_bekleyen_soru_alani(self):
        c = storage.Conversation(provider="ollama", messages=[{"role": "user", "content": "x"}])
        self.assertEqual(c.bekleyen_soru, "")
        c.bekleyen_soru = "Hangi boy?"
        with mock.patch.object(storage, "CHATS_DIR", Path(tempfile.mkdtemp())):
            c.save()
            yuklenen = [k for k in storage.load_all() if k.id == c.id][0]
        self.assertEqual(yuklenen.bekleyen_soru, "Hangi boy?")


if __name__ == "__main__":
    unittest.main()
