"""Çekirdek / arayüz ayrımı (K1): `asistan/cekirdek/` arayüz bilmez.

İki denetim: (1) kaynakta Qt/fastapi içe aktarması yok (grep), (2) Qt ve fastapi yasaklıyken çekirdeğin bütün alt
modülleri ayrı bir süreçte içe aktarılabiliyor (dolaylı içe aktarmayı da yakalar: çekirdeğin çağırdığı eski modüllerden
biri Qt'ye bağlanırsa bu test kırılır).

Çalıştırma (proje kökünde, programın Python'uyla):
    ~/.local/share/yeni-nesil-cafer-app/python/bin/python3 -m unittest discover -s testler -v
"""

import os
import re
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

KOK = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(KOK))

_GECICI = tempfile.mkdtemp(prefix="yeni-nesil-cafer-test-")
os.environ["XDG_CONFIG_HOME"] = str(Path(_GECICI) / "ayar")
os.environ["XDG_DATA_HOME"] = str(Path(_GECICI) / "veri")

CEKIRDEK = KOK / "asistan" / "cekirdek"


def _proje_python() -> str:
    """Alt süreç testleri projenin Python'uyla koşar: `.venv` varsa o (httpx/bs4 orada), yoksa bu yorumlayıcı.
    `sys.executable` kullanılınca sonuç testi başlatan Python'a göre değişiyordu (K4 denetçisinde 2 test düştü)."""
    for aday in (KOK / ".venv" / "bin" / "python", KOK / ".venv" / "Scripts" / "python.exe"):
        if aday.is_file():
            return str(aday)
    return sys.executable


PYTHON = _proje_python()
YASAK = ("PySide6", "shiboken6", "PyQt5", "PyQt6", "fastapi", "starlette")
# `import PySide6`, `from PySide6.QtCore import …`, `from fastapi import …`; arayüz paketleri de yasak
_YASAK_SATIR = re.compile(
    r"^\s*(?:from|import)\s+(?:" + "|".join(YASAK) + r")\b"
    r"|^\s*from\s+(?:\.\.+|asistan\.)(?:gui|arayuz)\b"
    r"|^\s*import\s+asistan\.(?:gui|arayuz)\b",
    re.M,
)

# Qt/fastapi'yi yasaklayan içe aktarma bekçisi: ayrı süreçte çalışır (bu süreçte PySide6 zaten yüklü olabilir)
_BEKCI = (
    "import sys, importlib.abc, importlib, pkgutil\n"
    "class Bekci(importlib.abc.MetaPathFinder):\n"
    "    def find_spec(self, ad, yol=None, hedef=None):\n"
    f"        if ad.split('.')[0] in {YASAK!r}:\n"
    "            raise ImportError('YASAK: ' + ad)\n"
    "sys.meta_path.insert(0, Bekci())\n"
    "import asistan.cekirdek as c\n"
    "adlar = ['asistan.cekirdek']\n"
    "for m in pkgutil.walk_packages(c.__path__, 'asistan.cekirdek.'):\n"
    "    importlib.import_module(m.name)\n"
    "    adlar.append(m.name)\n"
    "print(len(adlar))\n"
)


class CekirdekAyrimiTesti(unittest.TestCase):
    def test_cekirdek_klasoru_var(self):
        self.assertTrue((CEKIRDEK / "__init__.py").is_file())
        self.assertTrue((KOK / "asistan" / "arayuz" / "masaustu" / "__init__.py").is_file())

    def test_kaynakta_qt_import_yok(self):
        bulunan = []
        for dosya in sorted(CEKIRDEK.rglob("*.py")):
            metin = dosya.read_text(encoding="utf-8")
            for eslesme in _YASAK_SATIR.finditer(metin):
                satir = metin.count("\n", 0, eslesme.start()) + 1
                bulunan.append(f"{dosya.relative_to(KOK)}:{satir}: {eslesme.group(0).strip()}")
        self.assertEqual(bulunan, [], "çekirdekte arayüz içe aktarması:\n" + "\n".join(bulunan))

    def test_qt_yokken_cekirdek_ice_aktarilir(self):
        ortam = dict(os.environ, XDG_CONFIG_HOME=str(Path(_GECICI) / "ayar2"),
                     XDG_DATA_HOME=str(Path(_GECICI) / "veri2"))
        s = subprocess.run([PYTHON, "-c", _BEKCI], cwd=KOK, env=ortam, capture_output=True, text=True,
                           timeout=180)
        self.assertEqual(s.returncode, 0, s.stderr[-2000:])
        self.assertGreaterEqual(int(s.stdout.strip().splitlines()[-1]), 1)

    def test_qt_yokken_istek_kurulur(self):
        """İçe aktarma yetmez: çekirdek çağrı anında eski modülleri yükler (agent, learning); Qt'siz çalışmalı."""
        kod = _BEKCI + (
            "from asistan.cekirdek import istek\n"
            "from asistan.config import Settings\n"
            f"ajan, _ = istek.ajan_hazirla(istek.IstekBaglami('dosya yaz', Settings(workspace={str(Path(_GECICI) / 'is')!r})))\n"
            "print(type(ajan).__name__)\n")
        ortam = dict(os.environ, XDG_CONFIG_HOME=str(Path(_GECICI) / "ayar4"), XDG_DATA_HOME=str(Path(_GECICI) / "veri4"))
        s = subprocess.run([PYTHON, "-c", kod], cwd=KOK, env=ortam, capture_output=True, text=True, timeout=180)
        self.assertEqual(s.returncode, 0, s.stderr[-2000:])
        self.assertEqual(s.stdout.strip().splitlines()[-1], "Agent")

    def test_masaustu_ice_aktarilir(self):
        os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
        import asistan.arayuz.masaustu as masaustu
        from asistan.gui import window

        self.assertIs(masaustu.MainWindow, window.MainWindow)

    def test_bekci_gercekten_yakalar(self):
        """Denetimin kendisi çalışıyor mu: Qt'ye bağlı bir modül (gui) bekçiye takılmalı."""
        kod = _BEKCI.split("import asistan.cekirdek")[0] + "import asistan.gui.worker\n"
        s = subprocess.run([PYTHON, "-c", kod], cwd=KOK, capture_output=True, text=True, timeout=180,
                           env=dict(os.environ, XDG_CONFIG_HOME=str(Path(_GECICI) / "ayar3"),
                                    XDG_DATA_HOME=str(Path(_GECICI) / "veri3")))
        self.assertNotEqual(s.returncode, 0)
        self.assertIn("YASAK", s.stderr)

    # çekirdek → eski gövde (agent, manager, tools, registry, permissions, learning, work, connections, keystore,
    # cli_agents, mcp) içe aktarmaları: bağımlılık yönü ters (BÖLÜM 7 bekçisi). Liste büyüyemez; taşındıkça küçülür.
    ESKI_GOVDE_IZINLI = {
        "gorev/ajan.py": {"tools", "agent", "registry", "permissions"},
        "gorev/komut.py": {"work", "connections"},
        "gorev/model.py": {"permissions"},
        "gorev/sohbet.py": {"learning", "agent", "manager"},
        "saglayici/cli_ajan.py": {"cli_agents"},
        "saglayici/__init__.py": {"cli_agents", "connections", "keystore"},
        "yetenek/yukleyici.py": {"mcp"},
        "yetenek/calistirici.py": set(),
        "istek.py": {"learning", "agent", "manager"},
        "yonlendirici.py": {"cards", "model_updates", "cli_agents", "roster", "connections"},
        "profil.py": set(), "bildirim.py": {"cloud_server"}, "guvenlik.py": set(), "uzak.py": set(),
        "analiz/olcum.py": set(), "analiz/hata.py": set(), "yapisal.py": set(), "modeller.py": set(), "ayar.py": set(),
        "araclar/web.py": set(), "araclar/komut.py": set(), "araclar/dosya.py": set(), "araclar/urunler.py": set(),
    }
    _ESKI = re.compile(r"^\s*from \.\.\.(?:\s+import\s+([\w, ]+)|([\w.]+)\s+import)", re.M)

    def test_cekirdek_eski_govdeye_yeni_bagimlilik_eklemiyor(self):
        """Çekirdekten eski gövdeye içe aktarmalar bilinen listeyle sınırlı; yeni bir tane eklenirse test kırılır
        (giderilmesi: o modülü çekirdeğe taşımak ya da çekirdekten çağırmamak; SORULAR BÖLÜM 7)."""
        fazla = []
        for dosya in sorted(CEKIRDEK.rglob("*.py")):
            ad = dosya.relative_to(CEKIRDEK).as_posix()
            bulunan = set()
            for e in self._ESKI.finditer(dosya.read_text(encoding="utf-8")):
                if e.group(1):
                    bulunan |= {x.strip().split(" as ")[0] for x in e.group(1).split(",") if x.strip()}
                else:
                    bulunan.add(e.group(2).split(".")[0])
            izinli = self.ESKI_GOVDE_IZINLI.get(ad, set())
            if bulunan - izinli:
                fazla.append(f"{ad}: {sorted(bulunan - izinli)}")
        self.assertEqual(fazla, [], "çekirdekten eski gövdeye yeni içe aktarma:\n" + "\n".join(fazla))

    def test_yasak_desen_ornekleri(self):
        for satir in ("from PySide6.QtCore import QObject", "import fastapi", "from ..gui import chat",
                      "    from PySide6 import QtGui", "from asistan.arayuz.masaustu import x"):
            self.assertRegex(satir, _YASAK_SATIR, satir)
        for satir in ("# PySide6 burada yok", "from .ayar import Ayar", "import httpx"):
            self.assertIsNone(_YASAK_SATIR.search(satir), satir)


if __name__ == "__main__":
    unittest.main()
