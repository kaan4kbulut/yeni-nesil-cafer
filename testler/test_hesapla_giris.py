"""Bulut modellerine hesapla giriş: OpenRouter tarayıcı girişi, Hugging Face cihaz kodu, süreli anahtar yenileme
(accounts.py) ve aboneliğinle çalışan resmi programlar (cli_agents.py: Codex, Gemini CLI olay akışı).

İnternet, gerçek hesap ve gerçek anahtar zinciri kullanılmaz: sunucular ve programlar sahte.

Çalıştırma (proje kökünde, programın Python'uyla):
    ~/.local/share/yeni-nesil-cafer-app/python/bin/python3 -m unittest discover -s testler -v
"""

import base64
import hashlib
import json
import os
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest import mock

import httpx

KOK = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(KOK))

_GECICI = tempfile.mkdtemp(prefix="yeni-nesil-cafer-test-")
os.environ["XDG_CONFIG_HOME"] = str(Path(_GECICI) / "ayar")
os.environ["XDG_DATA_HOME"] = str(Path(_GECICI) / "veri")

from asistan import accounts, cli_agents, keystore  # noqa: E402


class _Yanit:
    def __init__(self, status: int, body: dict):
        self.status_code, self._body, self.text = status, body, json.dumps(body)

    def json(self):
        return self._body


class BellekAnahtarZinciri:
    """Gerçek anahtar zincirine dokunmadan get/set/delete_secret."""

    def setUp(self):
        self.kasa = {}
        for ad, fn in (("get_secret", lambda k: self.kasa.get(k, "")),
                       ("set_secret", lambda k, v: self.kasa.__setitem__(k, v)),
                       ("delete_secret", lambda k: self.kasa.pop(k, None))):
            p = mock.patch.object(keystore, ad, side_effect=fn)
            p.start()
            self.addCleanup(p.stop)


class OpenRouterGirisi(unittest.TestCase):
    def test_tarayici_yerel_adrese_doner_kod_anahtarla_degisir(self):
        istekler = []

        def tarayici(url):  # kullanıcı onaylayınca OpenRouter tarayıcıyı callback_url?code=… adresine yollar
            from urllib.parse import parse_qs, urlparse

            q = {k: v[0] for k, v in parse_qs(urlparse(url).query).items()}
            istekler.append(q)
            threading.Thread(target=lambda: httpx.get(q["callback_url"] + "?code=KOD123", timeout=5)).start()

        def post(url, json=None, timeout=None):
            self.assertEqual(url, accounts.OPENROUTER_KEYS)
            dogru = base64.urlsafe_b64encode(hashlib.sha256(json["code_verifier"].encode()).digest()).rstrip(b"=")
            self.assertEqual(dogru.decode(), istekler[0]["code_challenge"])  # PKCE: doğrulayıcı tutuyor
            self.assertEqual(json["code"], "KOD123")
            return _Yanit(200, {"key": "sk-or-v1-ornek"})

        with mock.patch.object(accounts.httpx, "post", side_effect=post):
            anahtar = accounts.openrouter(tarayici, timeout=10)
        self.assertEqual(anahtar, "sk-or-v1-ornek")
        self.assertTrue(istekler[0]["callback_url"].startswith("http://localhost:"))
        self.assertEqual(istekler[0]["code_challenge_method"], "S256")

    def test_iptal_ve_onaysiz_donus(self):
        with self.assertRaises(InterruptedError):
            accounts.openrouter(lambda url: None, cancelled=lambda: True, timeout=10)

        def reddet(url):
            from urllib.parse import parse_qs, urlparse

            cb = parse_qs(urlparse(url).query)["callback_url"][0]
            threading.Thread(target=lambda: httpx.get(cb + "?error=access_denied", timeout=5)).start()

        with self.assertRaises(accounts.LoginError):
            accounts.openrouter(reddet, timeout=10)


class HuggingFaceGirisi(BellekAnahtarZinciri, unittest.TestCase):
    def test_cihaz_kodu_bekler_sonra_anahtar_alir(self):
        yanitlar = [_Yanit(200, {"device_code": "D", "user_code": "ABCD-1234", "interval": 1, "expires_in": 60,
                                 "verification_uri": "https://huggingface.co/oauth/device"}),
                    _Yanit(400, {"error": "authorization_pending"}),
                    _Yanit(200, {"access_token": "hf_oauth_a", "refresh_token": "yen", "expires_in": 28800})]
        gosterilen = []
        with mock.patch.object(accounts, "HF_CLIENT_ID", "istemci"), \
                mock.patch.object(accounts.httpx, "post", side_effect=lambda *a, **k: yanitlar.pop(0)):
            t = accounts.huggingface(lambda kod, url: gosterilen.append(kod))
        self.assertEqual(gosterilen, ["ABCD-1234"])
        self.assertEqual(t["access_token"], "hf_oauth_a")
        self.assertGreater(t["expires_at"], time.time() + 28000)

    def test_suresi_dolan_anahtar_kendiliginden_yenilenir(self):
        accounts.save_session("b1", "huggingface", {"access_token": "eski", "refresh_token": "yen",
                                                     "expires_at": time.time() + 10})
        with mock.patch.object(accounts, "HF_CLIENT_ID", "istemci"), \
                mock.patch.object(accounts.httpx, "post",
                                  return_value=_Yanit(200, {"access_token": "yeni", "expires_in": 3600})) as post:
            self.assertEqual(accounts.fresh_key("b1", "eski"), "yeni")
            self.assertEqual(self.kasa["conn:b1"], "yeni")
            self.assertEqual(json.loads(self.kasa["oturum:b1"])["refresh_token"], "yen")  # eskisi korunur
            self.assertEqual(accounts.fresh_key("b1", "yeni"), "yeni")  # süresi uzun: yeniden istenmez
        post.assert_called_once()
        self.assertEqual(accounts.fresh_key("elle", "anahtar"), "anahtar")  # hesapla girilmemiş bağlantı

    def test_istemci_kimligi_yoksa_secenek_gorunmez(self):
        with mock.patch.object(accounts, "HF_CLIENT_ID", ""):
            self.assertFalse(accounts.available("huggingface"))
        self.assertTrue(accounts.available("openrouter"))


SAHTE_CODEX = r'''#!/usr/bin/env python3
import json, sys
args = sys.argv[1:]
if args[:2] == ["login", "status"]:
    print("Logged in using ChatGPT"); sys.exit(0)
out = args[args.index("-o") + 1]
sandbox = args[args.index("--sandbox") + 1]
for e in [{"type": "thread.started", "thread_id": "t"},
          {"type": "item.completed", "item": {"type": "command_execution", "command": "ls", "aggregated_output": "a.txt",
                                              "exit_code": 0}},
          {"type": "item.completed", "item": {"type": "file_change", "changes": [{"path": "/is/lamba.py", "kind": "add"}]}},
          {"type": "item.completed", "item": {"type": "agent_message", "text": "Lamba hazır (" + sandbox + ")."}},
          {"type": "turn.completed"}]:
    print(json.dumps(e), flush=True)
open(out, "w").write("Lamba hazır (" + sandbox + ").")
'''

SAHTE_GEMINI = r'''import json, sys
args = sys.argv[1:]
mode = args[args.index("--approval-mode") + 1]
for e in [{"type": "init"}, {"type": "tool_use", "tool_name": "run_shell_command", "tool_id": "1",
                             "parameters": {"command": "ls"}},
          {"type": "tool_result", "tool_id": "1", "status": "success", "output": "a.txt"},
          {"type": "message", "role": "assistant", "content": "Mer", "delta": True},
          {"type": "message", "role": "assistant", "content": "haba (" + mode + ")", "delta": True},
          {"type": "result", "status": "success"}]:
    print(json.dumps(e), flush=True)
'''


class ResmiProgramlar(unittest.TestCase):
    def setUp(self):
        self.klasor = Path(tempfile.mkdtemp(dir=_GECICI))
        self.codex = self.klasor / "codex"
        self.codex.write_text(SAHTE_CODEX.replace("/usr/bin/env python3", sys.executable), encoding="utf-8")
        self.codex.chmod(0o755)
        self.gemini = self.klasor / "gemini.py"
        self.gemini.write_text(SAHTE_GEMINI, encoding="utf-8")
        cli_agents._login_cache.clear()

    @unittest.skipIf(os.name == "nt", "sahte program betik olarak çalışır")
    def test_codex_adimlari_ve_son_cevap(self):
        adimlar = []
        with mock.patch.object(cli_agents, "codex_path", return_value=str(self.codex)):
            self.assertTrue(cli_agents.available("cli:codex"))
            cevap = cli_agents.run("cli:codex", "lamba yap", str(self.klasor), edits=True,
                                   on_step=lambda *s: adimlar.append(s))
            salt = cli_agents.run("cli:codex", "bak", str(self.klasor), edits=False)
        self.assertEqual(cevap, "Lamba hazır (workspace-write).")
        self.assertEqual(salt, "Lamba hazır (read-only).")  # onay beklenen tur: salt okunur
        self.assertEqual(adimlar[0], ("ls", "a.txt", False))
        self.assertEqual(adimlar[1][0], "dosya: lamba.py")

    def test_gemini_akis_parcalari_birlesir(self):
        adimlar = []
        with mock.patch.object(cli_agents, "gemini_command", return_value=[sys.executable, str(self.gemini)]):
            cevap = cli_agents.run("cli:gemini", "selam", str(self.klasor), edits=True,
                                   on_step=lambda *s: adimlar.append(s))
            plan = cli_agents.run("cli:gemini", "selam", str(self.klasor), edits=False)
        self.assertEqual(cevap, "Merhaba (auto_edit)")
        self.assertEqual(plan, "Merhaba (plan)")
        self.assertEqual(adimlar, [("run_shell_command ls", "a.txt", False)])

    def test_kurulu_degilse_ve_etiketler(self):
        with mock.patch.object(cli_agents, "codex_path", return_value=""):
            self.assertFalse(cli_agents.available("cli:codex"))
            with self.assertRaises(RuntimeError):
                cli_agents.run("cli:codex", "x", str(self.klasor))
        self.assertEqual(cli_agents.label("cli:claude", "opus"), "Claude Code · opus")
        self.assertEqual(cli_agents.label("cli:codex", "codex"), "Codex")
        self.assertTrue(cli_agents.is_cli("cli:gemini"))
        self.assertFalse(cli_agents.is_cli("api:x"))

    def test_gemini_google_girisi_secilir_diger_ayarlar_korunur(self):
        ev = self.klasor / "ev"
        (ev / ".gemini").mkdir(parents=True)
        (ev / ".gemini" / "settings.json").write_text('{"ui": {"theme": "Dracula"}}', encoding="utf-8")
        with mock.patch.object(Path, "home", return_value=ev):
            cli_agents._select_google_login()
            ayar = json.loads((ev / ".gemini" / "settings.json").read_text(encoding="utf-8"))
            self.assertEqual(cli_agents._gemini_auth_type(), "oauth-personal")
        self.assertEqual(ayar["ui"]["theme"], "Dracula")


if __name__ == "__main__":
    unittest.main()
