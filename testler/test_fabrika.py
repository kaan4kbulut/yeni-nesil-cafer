"""Araç fabrikası (Aşama 5) testleri: doğrulama, gerçek sandbox (internetsiz), düzeltme döngüsü, onay, kayıt, git.
Model sahte: sıradaki hazır araç tanımını döndürür."""

import json
import os
import shutil
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

from asistan import factory, tools  # noqa: E402,F401  (tools: yerleşik araçlar kayda girsin)
from asistan.registry import REGISTRY  # noqa: E402

SAYAC = {
    "name": "word_count", "description": "Count words in a text file in the workspace.",
    "input_schema": {"type": "object", "properties": {"path": {"type": "string", "description": "file"}},
                     "required": ["path"]},
    "packages": [],
    "code": "from pathlib import Path\n\ndef run(path: str) -> str:\n"
            "    return f\"{len(Path(path).read_text(encoding='utf-8').split())} words\"\n",
    "test": "import arac\nopen('a.txt', 'w').write('bir iki üç')\nassert arac.run(path='a.txt') == '3 words'\n",
}
BOZUK = {**SAYAC, "code": "def run(path: str) -> str:\n    return 'yanlış'\n"}


def _cevaplar(*items):
    it = iter(json.dumps(x) for x in items)
    return mock.patch("asistan.specialists.ask", side_effect=lambda *a, **k: next(it))


class Fabrika(unittest.TestCase):
    def setUp(self):
        d = Path(tempfile.mkdtemp(dir=_GECICI))
        self.ws = d / "calisma"
        self.ws.mkdir()
        patches = [mock.patch.object(factory, "TOOLS_DIR", d / "araclar"),
                   mock.patch.object(factory, "PACKAGES_DIR", d / "paketler"),
                   mock.patch.object(factory, "_writers", return_value=[("ollama", "sahte-model")])]
        for p in patches:
            p.start()
            self.addCleanup(p.stop)
        self.addCleanup(lambda: REGISTRY.remove_source(factory.SOURCE))
        self.asked = []

    def _onay(self, answer=True):
        def ask(name, args):
            self.asked.append(name)
            return answer
        return ask

    def _build(self, answer=True):
        return factory.build("metin dosyasındaki kelimeleri say", "", mock.Mock(), [], ("ollama", "x"),
                             self._onay(answer))

    def test_arac_eklenir_calisir_ve_git_kaydi(self):
        with _cevaplar(SAYAC):
            result = self._build()
        self.assertIn("NEW TOOL READY: f_word_count", result)
        self.assertEqual(self.asked, ["add_tool"])  # paket yok: yalnızca ekleme onayı
        tool = REGISTRY.get("f_word_count")
        self.assertEqual((tool.risk, tool.source), ("calistirir", "fabrika"))  # her çalıştırma denetlenir
        (self.ws / "not.txt").write_text("merhaba dünya", encoding="utf-8")
        factory.set_workspace(str(self.ws))
        self.assertEqual(tool.runner({"path": "not.txt"}), "2 words")
        if shutil.which("git"):
            self.assertTrue((factory.TOOLS_DIR / ".git").is_dir())
        factory.load_all()  # program yeniden açılınca da kayıtta
        self.assertIsNotNone(REGISTRY.get("f_word_count"))
        factory.remove("f_word_count")
        self.assertIsNone(REGISTRY.get("f_word_count"))
        self.assertFalse((factory.TOOLS_DIR / "f_word_count").exists())

    def test_hatali_arac_duzelttirilir(self):
        with _cevaplar(BOZUK, SAYAC) as ask:
            result = self._build()
        self.assertIn("NEW TOOL READY", result)
        prompt = ask.call_args_list[1].args[4]
        self.assertIn("The test failed", prompt)  # hata modele geri verildi

    def test_kullanici_reddederse_eklenmez(self):
        with _cevaplar(SAYAC):
            result = self._build(answer=False)
        self.assertIn("did not approve", result)
        self.assertIsNone(REGISTRY.get("f_word_count"))
        self.assertFalse((factory.TOOLS_DIR / "f_word_count").exists())

    def test_hep_basarisizsa_durustce_soyler(self):
        with _cevaplar(*[BOZUK] * factory.MAX_ATTEMPTS):
            result = self._build()
        self.assertIn("could not build", result)
        self.assertEqual(self.asked, [])  # test geçmeyen araç kullanıcıya hiç sorulmaz

    def test_dogrulama(self):
        self.assertEqual(factory.validate(SAYAC)["name"], "f_word_count")
        with self.assertRaises(factory.FactoryError):
            factory.validate({**SAYAC, "code": "import os\ndef run(**k):\n    os.system('sudo rm x')\n"})
        with self.assertRaises(factory.FactoryError):
            factory.validate({**SAYAC, "test": "print('test yok')"})
        with self.assertRaises(factory.FactoryError):
            factory.validate({**SAYAC, "input_schema": {"type": "string"}})
        # yerleşik araç adı alınamaz (önek de olsa çakışan fabrika dışı araç)
        REGISTRY.put(REGISTRY.get("read_file").__class__(name="f_read_file", description="x", schema={}, risk="okur"))
        try:
            with self.assertRaises(factory.FactoryError):
                factory.validate({**SAYAC, "name": "read_file"})
        finally:
            REGISTRY.tools.pop("f_read_file", None)

    @unittest.skipUnless(factory._offline_prefix(), "unshare yok")
    def test_sandbox_internetsiz(self):
        net = {**SAYAC, "test": "import arac, socket\n"
                                "try:\n    socket.create_connection(('1.1.1.1', 53), timeout=3)\n    ok = True\n"
                                "except OSError:\n    ok = False\nassert not ok, 'internet açık'\n"}
        passed, output = factory.sandbox_test(net)
        self.assertTrue(passed, output)

    def test_hazir_cozum(self):
        ready = factory.find_ready("ses kaydını konuşmayı yazıya çevirme, Türkçe")
        self.assertIn("faster-whisper", [p for p, _ in ready["packages"]])
        self.assertTrue(factory.find_ready("sqlite veritabanı sorgula")["mcp"])


if __name__ == "__main__":
    unittest.main()
