"""K12-B — sandbox / sırlar düzeltmeleri (`NOTLAR/inceleme-k12-2026-09-28.md` B1–B10).

B1 sandbox kancası `_posixsubprocess` yeniden içe aktarımını engeller · B2 MCP stdio sunucusuna beyaz listeli ortam ·
B3 pip/Claude Code/CLI ajanı/fabrika git/open_app alt süreçlerine sır geçmez · B4 web_fetch yönlendirme + DNS sabitleme
+ CGNAT · B5 DATA_DIR'deki sırlar (bulut.json, tarayıcı profili, MCP kayıtları) okunamaz · B6 Claude Code salt okunur
bayrakları · B7 anahtar zinciri erişimi yüksek risk · B8 fabrika sandbox'ı Linux'ta unshare'siz koşmaz · B9 kurulum
paketine geliştirici artıkları girmez · B10 sunucu anahtarı günlüğe maskeli.

Çalıştırma (proje kökünde): QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest testler/test_k12_b.py -q
"""

import os
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

from asistan import cli_agents, cloud_server, factory, mcp, security, specialists, tools  # noqa: E402
from asistan.arayuz import web as web_arayuz  # noqa: E402
from asistan.cekirdek import ayar  # noqa: E402
from asistan.cekirdek.araclar import dosya, temel, web  # noqa: E402
from asistan.cekirdek.araclar.temel import AracHatasi  # noqa: E402
from asistan.cekirdek.yetenek import calistirici  # noqa: E402

SIRLAR = {"ANTHROPIC_API_KEY": "sk-ant-gizli", "CAFER_TOKEN": "cafer-gizli", "OPENAI_API_KEY": "sk-gizli"}


def _python() -> str:
    for aday in (KOK / ".venv" / "bin" / "python", KOK / ".venv" / "Scripts" / "python.exe"):
        if aday.is_file():
            return str(aday)
    return sys.executable


def sir_yok(ortam: dict) -> bool:
    return not any(k in ortam for k in SIRLAR) and not any(k.startswith("CAFER_") for k in ortam)


@unittest.skipIf(sys.platform == "win32", "posix sandbox")
class B1SandboxKancasi(unittest.TestCase):
    def test_fork_exec_yeniden_ice_aktarilamaz(self):
        """İnceleme b: modül sys.modules'tan silinip yeniden içe aktarılınca yamasız fork_exec ile komut çalışıyordu."""
        tmp = tempfile.mkdtemp()
        betik = f"""
import json, os, sys, importlib
sys.path.insert(0, {str(KOK / "asistan" / "cekirdek" / "yetenek")!r})
import _kum_giris
_kum_giris.kanca_kur({{"izinler": [], "gecici": {tmp!r}, "calisma_klasoru": {tmp!r}, "program_koku": {str(KOK)!r},
                      "yetenek_klasoru": {tmp!r}, "kutuphane_yollari": [], "okuma_kokleri": []}})
import subprocess
try:
    subprocess.run(["true"]); print("SUBPROCESS:ACIK")
except PermissionError as e: print("SUBPROCESS:ENGEL")
sys.modules.pop("_posixsubprocess", None); sys.modules.pop("subprocess", None)
try:
    m = importlib.import_module("_posixsubprocess"); print("REIMPORT:ACIK")
except PermissionError: print("REIMPORT:ENGEL")
try:
    os.fork(); print("FORK:ACIK")
except PermissionError: print("FORK:ENGEL")
"""
        p = subprocess.run([_python(), "-c", betik], capture_output=True, text=True, timeout=60)
        self.assertIn("SUBPROCESS:ENGEL", p.stdout, p.stdout + p.stderr)
        self.assertIn("REIMPORT:ENGEL", p.stdout, p.stdout + p.stderr)
        self.assertIn("FORK:ENGEL", p.stdout, p.stdout + p.stderr)


class B2McpOrtami(unittest.TestCase):
    def test_stdio_sunucusuna_yalnizca_beyaz_liste(self):
        with mock.patch.dict(os.environ, {**SIRLAR, "PATH": "/usr/bin", "HOME": "/home/x"}):
            o = mcp.sunucu_ortami({"command": "npx", "env": {"MCP_ANAHTAR": "kullanici verdi"}})
        self.assertTrue(sir_yok(o), o)
        self.assertEqual(o["MCP_ANAHTAR"], "kullanici verdi")
        self.assertEqual(o["PATH"], "/usr/bin")


class B3AltSurecOrtami(unittest.TestCase):
    def test_pip_kurulumu_beyaz_listeli(self):
        tb = tools.Toolbox(tempfile.mkdtemp())
        with mock.patch.dict(os.environ, SIRLAR), mock.patch.object(tools.a_komut, "surec", return_value="ok") as surec:
            tb._run_process([_python(), "-m", "pip", "list"], python=True)
        ortam = surec.call_args.args[2]
        self.assertTrue(sir_yok(ortam), ortam)
        self.assertIn("PYTHONPATH", ortam)

    def test_check_3d_ortami(self):
        with mock.patch.dict(os.environ, SIRLAR):
            self.assertTrue(sir_yok(tools.guvenli_ajan_ortami()))
            self.assertIn("PYTHONPATH", tools.guvenli_ajan_ortami())

    def test_claude_code_ve_cli_ajanlari(self):
        with mock.patch.dict(os.environ, {**SIRLAR, "CLAUDECODE": "1", "CLAUDE_CODE_ENTRYPOINT": "cli", "NODE_OPTIONS": "x",
                                          "PATH": "/usr/bin"}):
            o = specialists.claude_ortami()
            self.assertTrue(sir_yok(o), o)
            self.assertNotIn("CLAUDECODE", o)
            self.assertNotIn("CLAUDE_CODE_ENTRYPOINT", o)
            o2 = cli_agents.ajan_ortami()
            self.assertTrue(sir_yok(o2), o2)
            self.assertEqual(o2.get("NODE_OPTIONS"), "x")  # Node/npm ayarları CLI için gerekli
            self.assertEqual(o2["PATH"], "/usr/bin")

    def test_fabrika_git_ve_pip(self):
        with mock.patch.dict(os.environ, SIRLAR):
            o = factory.git_ortami()
        self.assertTrue(sir_yok(o), o)
        self.assertEqual(o["GIT_AUTHOR_NAME"], "YENİ NESİL CAFER")

    def test_open_app_ortami(self):
        with mock.patch.dict(os.environ, {**SIRLAR, "DBUS_SESSION_BUS_ADDRESS": "unix:x", "DISPLAY": ":0"}):
            o = tools.uygulama_ortami()
        self.assertTrue(sir_yok(o), o)
        self.assertEqual((o["DBUS_SESSION_BUS_ADDRESS"], o["DISPLAY"]), ("unix:x", ":0"))


class B4WebFetch(unittest.TestCase):
    def _addr(self, ip):
        return lambda host, *a, **k: [(2, 1, 6, "", (ip, 0))]

    def test_cgnat_ozel(self):
        with mock.patch.object(web.socket, "getaddrinfo", self._addr("100.64.0.9")):
            with self.assertRaises(AracHatasi):
                web._adres_denetle("http://x.example/")

    def test_yonlendirme_ozel_aga_gitmez(self):
        cagrilar = []

        class Cevap:
            def __init__(self, status, headers):
                self.status_code, self.headers = status, headers

            def __enter__(self): return self
            def __exit__(self, *a): return False
            def iter_bytes(self, n): yield b"<html><title>t</title>ok</html>"

        def akis(hedef, basliklar, ek):
            cagrilar.append((hedef, {"headers": basliklar, "extensions": ek}))
            if len(cagrilar) == 1:
                return Cevap(302, {"location": "http://127.0.0.1:11434/api/tags"})
            return Cevap(200, {"content-type": "text/html"})

        with mock.patch.object(web.socket, "getaddrinfo", self._addr("93.184.216.34")), \
                mock.patch.object(web, "_akis", akis):
            with self.assertRaises(AracHatasi) as cm:
                web.oku("http://example.com/yonlendir")
        self.assertIn("private", str(cm.exception).lower())
        self.assertEqual(len(cagrilar), 1)
        self.assertFalse(cagrilar[0][1].get("follow_redirects", False))

    def test_dns_sabitleme_ve_izinli_yonlendirme(self):
        cagrilar = []

        class Cevap:
            def __init__(self, status, headers):
                self.status_code, self.headers = status, headers

            def __enter__(self): return self
            def __exit__(self, *a): return False
            def iter_bytes(self, n): yield b"<html><title>Basl</title><p>govde</p></html>"

        def akis(hedef, basliklar, ek):
            cagrilar.append((hedef, {"headers": basliklar, "extensions": ek}))
            if len(cagrilar) == 1:
                return Cevap(301, {"location": "https://www.example.com/son"})
            return Cevap(200, {"content-type": "text/html"})

        with mock.patch.object(web.socket, "getaddrinfo", self._addr("93.184.216.34")), \
                mock.patch.object(web, "_akis", akis):
            metin = web.oku("https://example.com/ilk")
        self.assertIn("govde", metin)
        self.assertEqual(len(cagrilar), 2)
        for url, k in cagrilar:
            self.assertIn("93.184.216.34", url)  # çözülen IP'ye bağlanılır (yeniden çözümleme yok)
        self.assertEqual(cagrilar[0][1]["headers"]["Host"], "example.com")
        self.assertEqual(cagrilar[1][1]["headers"]["Host"], "www.example.com")
        self.assertEqual(cagrilar[0][1]["extensions"]["sni_hostname"], "example.com")


class B5DataDirSirlari(unittest.TestCase):
    def test_bulut_json_ve_profil_okunamaz(self):
        veri = ayar.DATA_DIR.resolve()
        veri.mkdir(parents=True, exist_ok=True)
        (veri / "bulut.json").write_text("{}", encoding="utf-8")
        (veri / "tarayici-profili").mkdir(exist_ok=True)
        (veri / "tarayici-profili" / "Cookies").write_text("x", encoding="utf-8")
        (veri / "sohbetler").mkdir(exist_ok=True)
        (veri / "sohbetler" / "a.json").write_text("{}", encoding="utf-8")
        kok = Path(tempfile.mkdtemp())
        for yol in ("bulut.json", "tarayici-profili/Cookies", "tarayici-profili", "mcp-kayitlari/x.log"):
            with self.assertRaises(AracHatasi, msg=yol):
                dosya.yol_coz(kok, [veri], str(veri / yol), okuma=True)
        self.assertTrue(dosya.yol_coz(kok, [veri], str(veri / "sohbetler" / "a.json"), okuma=True).is_file())
        self.assertIn("bulut.json", temel.GIZLI_DOSYALAR)
        self.assertTrue(any(p.name == "tarayici-profili" for p in temel.gizli_yollar(veri)))

    def test_sandbox_yasak_kokleri(self):
        is_ = calistirici.sandbox_isi_yasaklari()
        self.assertIn("bulut.json", is_["yasak_adlar"])
        self.assertTrue(any(k.endswith("tarayici-profili") for k in is_["yasak_kokler"]))


class B6ClaudeCodeBayraklari(unittest.TestCase):
    def test_salt_okunur_ve_duzenleme(self):
        salt = specialists.claude_komutu("claude", "istem", "", False, "")
        self.assertIn("--disallowedTools", salt)
        yasak = salt[salt.index("--disallowedTools") + 1]
        for arac in ("Bash", "Edit", "Write", "MultiEdit", "NotebookEdit"):
            self.assertIn(arac, yasak)
        self.assertNotIn("acceptEdits", salt)
        duz = specialists.claude_komutu("claude", "istem", "", True, "sistem")
        yasak = duz[duz.index("--disallowedTools") + 1]
        self.assertIn("Bash", yasak)
        self.assertNotIn("Edit", yasak.split(","))
        self.assertIn("acceptEdits", duz)
        self.assertIn("--append-system-prompt", duz)


class B7AnahtarZinciri(unittest.TestCase):
    def test_secretstorage_yuksek_risk(self):
        for kod in ("import secretstorage; print(secretstorage.get_default_collection(bus))",
                    "from jeepney import DBusAddress; SecretService", "kwallet-query kdewallet"):
            self.assertEqual(security.classify("run_python", {"code": kod}, _GECICI)[0], security.HIGH, kod)


class B8FabrikaSandbox(unittest.TestCase):
    def test_linuxta_unshare_yoksa_kosmaz(self):
        with mock.patch.object(factory, "_offline_prefix", return_value=[]), mock.patch.object(factory.sys, "platform", "linux"), \
                mock.patch.object(factory.subprocess, "run") as run:
            gecti, cikti = factory.sandbox_test({"code": "def run(): return 1", "test": "import arac"})
        run.assert_not_called()
        self.assertFalse(gecti)
        self.assertIn("izole", cikti)


class B9KurulumPaketi(unittest.TestCase):
    def test_gelistirici_artiklari_pakete_girmez(self):
        sys.path.insert(0, str(KOK / "paketleme"))
        import paketle

        yasak = {".cafer", ".claude", "NOTLAR", "sunucu", ".github", ".venv", ".git"}
        for kaynak, hedef in paketle.program_dosyalari():
            rel = kaynak.relative_to(paketle.PROJE)
            self.assertFalse(set(rel.parts) & yasak, rel)
            self.assertNotEqual(rel.name, ".env", rel)
            self.assertFalse(rel.parts[:3] == ("testler", "sinav", "sonuclar"), rel)
            self.assertNotIn("__pycache__", rel.parts)


class B10AnahtarMaskesi(unittest.TestCase):
    def test_maske(self):
        self.assertEqual(web_arayuz.maskele("abcdefghijklmnop"), "abcd…(16 karakter)")
        self.assertEqual(cloud_server.maskele("abcdefghijklmnop"), "abcd…(16 karakter)")
        self.assertEqual(web_arayuz.maskele("kisa"), "…(4 karakter)")


if __name__ == "__main__":
    unittest.main()
