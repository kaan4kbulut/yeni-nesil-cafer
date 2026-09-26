"""Hook testleri: hooks.json'daki komutlar gerçek alt süreç olarak çalışır.

Çalıştırma (proje kökünde, programın Python'uyla):
    ~/.local/share/yeni-nesil-cafer-app/python/bin/python3 -m unittest discover -s testler -v
"""

import json
import os
import shlex
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

from asistan import hooks, permissions  # noqa: E402
from asistan.agent import PROGRAM, Agent  # noqa: E402
from asistan.config import Settings  # noqa: E402

KAYIT = Path(_GECICI) / "hook-cikti.json"


def _komut(*argv: str) -> str:
    """Kabuğa göre tırnaklanmış komut satırı (Windows'ta cmd, diğerlerinde sh)."""
    return subprocess.list2cmdline(argv) if sys.platform == "win32" else shlex.join(argv)


def py(code: str) -> str:
    """Hook komutu: olay JSON'unu okuyan küçük bir Python programı (tırnak sorunu olmasın diye dosyaya yazılır)."""
    betik = Path(tempfile.mkstemp(suffix=".py", dir=_GECICI)[1])
    betik.write_text("import sys, json; d = json.load(sys.stdin); " + code, encoding="utf-8")
    return _komut(sys.executable, str(betik))


def kur(ayar: dict) -> None:
    hooks.CONFIG_FILE.parent.mkdir(parents=True, exist_ok=True)
    hooks.CONFIG_FILE.write_text(json.dumps({"hooks": ayar}), encoding="utf-8")
    hooks._cache = (-1.0, {})


class _Cb:
    def __init__(self):
        self.text, self.ended = "", []

    def on_text(self, d): self.text += d
    def on_tool_start(self, *a): pass
    def on_tool_end(self, call_id, result, is_error): self.ended.append((result, is_error))
    def ask_approval(self, name, args): return True
    def is_cancelled(self): return False


def ajan() -> Agent:
    a = Agent(Settings(workspace=str(Path(_GECICI) / "is"), approval_mode="kullanici", confirm_commands=False), _Cb())
    a._provider = "ollama"
    return a


class HookTesti(unittest.TestCase):
    def tearDown(self):
        hooks.CONFIG_FILE.unlink(missing_ok=True)
        hooks._cache = (-1.0, {})
        KAYIT.unlink(missing_ok=True)

    def test_dosya_yoksa_hicbir_sey_olmaz(self):
        self.assertFalse(hooks.active("PreToolUse"))
        self.assertEqual(hooks.run("PreToolUse", {}, "run_command"), hooks.Outcome())

    def test_arac_oncesi_engeller(self):
        kur({"PreToolUse": [{"matcher": "run_command", "hooks": [{"type": "command", "command": py(
            "sys.stderr.write('rm yasak: ' + d['tool_input']['command']); sys.exit(2) "
            "if 'rm' in d['tool_input']['command'] else None")}]}]})
        a = ajan()
        with mock.patch.object(a.toolbox, "run", return_value="tamam") as run:
            result, is_error = a._execute_tool("1", "run_command", {"command": "rm a.txt", "purpose": ""})
            self.assertTrue(is_error)
            self.assertIn("rm yasak: rm a.txt", result)
            run.assert_not_called()
            result, is_error = a._execute_tool("2", "run_command", {"command": "touch a.txt", "purpose": ""})
            self.assertEqual((result, is_error), ("tamam", False))

    def test_eslestirici_baska_araca_dokunmaz(self):
        kur({"PreToolUse": [{"matcher": "run_python", "hooks": [{"command": py("sys.exit(2)")}]}]})
        a = ajan()
        with mock.patch.object(a.toolbox, "run", return_value="tamam"):
            self.assertEqual(a._execute_tool("1", "list_files", {"path": "."}), ("tamam", False))

    def test_arac_sonrasi_sorunu_sonuca_ekler(self):
        kur({"PostToolUse": [{"matcher": "write_file", "hooks": [{"command": py(
            "sys.stderr.write('satır sonu eksik'); sys.exit(2)")}]}]})
        a = ajan()
        with mock.patch.object(a.toolbox, "run", return_value="Wrote 1 characters"):
            result, _ = a._execute_tool("1", "write_file", {"path": "a.txt", "content": "x"})
        self.assertIn("Wrote 1 characters", result)
        self.assertIn("satır sonu eksik", result)

    def test_istek_hooku_bilgi_ekler_ve_engelleyebilir(self):
        kur({"UserPromptSubmit": [{"hooks": [{"command": py(
            "print('proje: site') if 'site' in d['prompt'] else (sys.stderr.write('mesai dışı'), sys.exit(2))")}]}]})
        a = ajan()
        msgs = []
        with mock.patch.object(a, "_run_ollama") as model:
            a.run("ollama", msgs, "site başlığını değiştir")
            model.assert_called_once()
            self.assertTrue(msgs[1].get(PROGRAM))
            self.assertIn("proje: site", msgs[1]["content"])
            msgs = []
            a.run("ollama", msgs, "başka iş")
            model.assert_called_once()  # engellendi: model hiç çağrılmadı
        self.assertIn("mesai dışı", msgs[-1]["content"])

    def test_tur_sonu_cevabi_alir(self):
        kur({"Stop": [{"hooks": [{"command": py(
            f"open({str(KAYIT)!r}, 'w').write(json.dumps(d))")}]}]})
        a = ajan()

        def cevap(messages):
            messages.append({"role": "assistant", "content": "bitti"})

        with mock.patch.object(a, "_run_ollama", side_effect=cevap):
            a.run("ollama", [], "bir iş")
        self.assertEqual(json.loads(KAYIT.read_text())["answer"], "bitti")

    def test_bozuk_ya_da_yavas_hook_isi_durdurmaz(self):
        kur({"PreToolUse": [{"hooks": [{"command": py("sys.exit(1)")},
                                       {"command": py("import time; time.sleep(5)"), "timeout": 0.5}]}]})
        self.assertFalse(hooks.run("PreToolUse", {}, "read_file").blocked)
        self.assertIn("zaman aşımı", hooks.LOG_FILE.read_text(encoding="utf-8"))

    def test_asistan_hooks_json_a_dokunamaz(self):
        for args in ({"command": "echo '{}' > ~/.config/yeni-nesil-cafer/hooks.json"},
                     {"command": "cat hooks.json"}):
            self.assertEqual(permissions.decide("run_command", args, permissions.Context(
                approval_mode="kullanici", confirm_commands=False)).kind, permissions.DENY)
        self.assertEqual(permissions.decide("run_python", {"code": "open('hooks.json','w')"},
                                            permissions.Context()).kind, permissions.DENY)


if __name__ == "__main__":
    unittest.main()
