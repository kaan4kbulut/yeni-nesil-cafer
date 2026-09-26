"""İzin hattı testleri (`permissions.decide` ve ajanın bu kararı uygulaması).

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

from asistan import permissions as p  # noqa: E402
from asistan import security  # noqa: E402
from asistan.agent import Agent  # noqa: E402
from asistan.config import Settings  # noqa: E402

RM_HOME = {"command": "rm -rf ~", "purpose": ""}
SIL = {"command": "rm eski.txt", "purpose": ""}
YAZ = {"path": "a.txt", "content": "x"}


def karar(name, args, **kw) -> str:
    return p.decide(name, dict(args), p.Context(**kw)).kind


class KararTesti(unittest.TestCase):
    def test_yasak_her_kipte_reddedilir(self):
        for kw in ({"approval_mode": "kullanici", "confirm_commands": False},
                   {"approval_mode": "kullanici", "always_allowed": True},
                   {"approval_mode": "guvenlik"},
                   {"approval_mode": "guvenlik", "uncensored": True}):
            self.assertEqual(karar("run_command", RM_HOME, **kw), p.DENY, kw)
        self.assertEqual(karar("run_python", {"code": "import shutil; shutil.rmtree('/')"}), p.DENY)

    def test_sansursuz_modelde_onay_kutusu_kapaliyken_de_sorulur(self):
        kw = {"approval_mode": "guvenlik", "uncensored": True, "confirm_commands": False}
        self.assertEqual(karar("run_command", SIL, **kw), p.ASK)
        self.assertEqual(karar("write_file", YAZ, **kw), p.ALLOW)  # çalışma klasörüne yazmak riskli değil
        self.assertEqual(karar("run_command", SIL, always_allowed=True, **{k: v for k, v in kw.items()}), p.ALLOW)

    def test_kullanici_kipi(self):
        self.assertEqual(karar("run_command", SIL), p.ASK)
        self.assertEqual(karar("run_command", SIL, confirm_commands=False), p.ALLOW)
        self.assertEqual(karar("run_command", SIL, auto_approve=lambda n, a: True), p.ALLOW)
        self.assertEqual(karar("run_command", {"command": "ls -la"}), p.ALLOW)  # salt okur
        self.assertEqual(karar("write_file", YAZ), p.ALLOW)
        self.assertEqual(karar("write_file", YAZ, must_act=True), p.ASK)  # ▶ turunda her değişiklik sorulur
        self.assertEqual(karar("generate_image", {"prompt": "kedi"}, must_act=True), p.ASK)
        self.assertEqual(karar("start_team_task", {"title": "t", "goal": "g"}, must_act=True), p.ASK)

    def test_guvenlik_kipi(self):
        self.assertEqual(karar("run_command", SIL, approval_mode="guvenlik"), p.REVIEW)
        self.assertEqual(karar("write_file", YAZ, approval_mode="guvenlik"), p.REVIEW)
        self.assertEqual(karar("generate_image", {"prompt": "kedi"}, approval_mode="guvenlik"), p.REVIEW)
        self.assertEqual(karar("read_file", {"path": "a.txt"}, approval_mode="guvenlik"), p.ALLOW)

    def test_onay_beklerken_degisiklik_bekletilir(self):
        self.assertEqual(karar("write_file", YAZ, gate_actions=True), p.PENDING)
        self.assertEqual(karar("start_team_task", {"title": "t", "goal": "g"}, gate_actions=True), p.PENDING)
        self.assertEqual(karar("read_file", {"path": "a.txt"}, gate_actions=True), p.ALLOW)

    def test_denetci_model_yalnizca_orta_ve_yuksekte(self):
        ws = _GECICI
        self.assertFalse(security.needs_model("write_file", YAZ, ws))
        self.assertFalse(security.needs_model("generate_image", {"prompt": "kedi"}, ws))
        self.assertTrue(security.needs_model("run_command", {"command": "sudo pacman -Syu"}, ws))


class _Cb:
    """Arayüz yerine: onay sorularını sayar."""

    def __init__(self, answer=True):
        self.answer, self.asked, self.ended = answer, [], []

    def on_tool_start(self, *a): pass
    def on_tool_end(self, call_id, result, is_error): self.ended.append((result, is_error))
    def ask_approval(self, name, args): self.asked.append(name); return self.answer
    def is_cancelled(self): return False
    def start_team_task(self, title, goal): return "ekibe verildi"


def ajan(cb, **ayar) -> Agent:
    s = Settings(workspace=str(Path(_GECICI) / "is"), **ayar)
    a = Agent(s, cb, team_tool=True)
    a._provider = "ollama"
    return a


class AjanTesti(unittest.TestCase):
    def test_yasak_komut_kullanici_kipinde_calismaz(self):
        cb = _Cb()
        a = ajan(cb, approval_mode="kullanici", confirm_commands=False)
        with mock.patch.object(a.toolbox, "run") as run:
            result, is_error = a._execute_tool("1", "run_command", dict(RM_HOME))
        run.assert_not_called()
        self.assertTrue(is_error)
        self.assertIn("REFUSED", result)

    def test_ekip_gorevi_izin_hattini_atlamaz(self):
        cb = _Cb(answer=False)
        a = ajan(cb, approval_mode="kullanici")
        a.must_act = True
        result, is_error = a._execute_tool("1", "start_team_task", {"title": "t", "goal": "g"})
        self.assertEqual(cb.asked, ["start_team_task"])
        self.assertTrue(is_error)

    def test_danisirken_iptal_yutulmaz(self):
        from asistan.agent import Cancelled

        a = ajan(_Cb())
        with mock.patch.object(a, "_consult", side_effect=Cancelled()):
            with self.assertRaises(Cancelled):
                a._execute_tool("1", "ask_specialist", {"role": "general", "question": "soru"})

    def test_programin_araci_ortak_yoldan_calisir(self):
        cb = _Cb()
        a = ajan(cb)
        with mock.patch("asistan.agent.learning.remember", return_value="kaydedildi"):
            result, is_error = a._execute_tool("1", "remember", {"text": "adım Deniz", "kind": "bilgi"})
        self.assertEqual((result, is_error), ("kaydedildi", False))
        self.assertEqual(a.remembered, ["adım Deniz"])
        self.assertEqual(cb.ended[-1], ("kaydedildi", False))

    def test_openai_bicimi_tekrar_eden_hatayi_soyler(self):
        a = ajan(_Cb())
        messages = []
        call = {"id": "c1", "function": {"name": "read_file", "arguments": '{"path": "olmayan.txt"}'}}
        a._run_calls([call], messages, ollama=False)
        a._run_calls([call], messages, ollama=False)
        self.assertEqual(messages[0]["tool_call_id"], "c1")
        self.assertNotIn("already ran exactly this", messages[0]["content"])
        self.assertIn("already ran exactly this", messages[1]["content"])

    def test_dusuk_riskte_sohbet_modeli_bosaltilmaz(self):
        cb = _Cb()
        a = ajan(cb, approval_mode="guvenlik", ollama_model="qwen3.5:4b")
        with mock.patch.object(security, "pick_reviewer") as pick, \
                mock.patch("asistan.agent.sysinfo.make_room") as room:
            result, is_error = a._execute_tool("1", "write_file", dict(YAZ))
        pick.assert_not_called()
        room.assert_not_called()
        self.assertFalse(is_error, result)


if __name__ == "__main__":
    unittest.main()
