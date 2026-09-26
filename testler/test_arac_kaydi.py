"""Araç kaydı ve MCP istemcisi testleri.

Çalıştırma (proje kökünde, programın Python'uyla):
    ~/.local/share/yeni-nesil-cafer-app/python/bin/python3 -m unittest discover -s testler -v
"""

import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

KOK = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(KOK))

# ayarlar ve veriler geçici klasöre: kullanıcının gerçek mcp.json'una dokunulmaz
_GECICI = tempfile.mkdtemp(prefix="yeni-nesil-cafer-test-")
os.environ["XDG_CONFIG_HOME"] = str(Path(_GECICI) / "ayar")
os.environ["XDG_DATA_HOME"] = str(Path(_GECICI) / "veri")

from asistan import mcp, tools  # noqa: E402
from asistan.agent import build_tool_specs, is_action  # noqa: E402
from asistan.profiles import AgentProfile  # noqa: E402
from asistan.registry import REGISTRY, RISKS  # noqa: E402

ESKI_ONAY = {"run_command", "run_python", "install_python_package"}  # kayıttan önceki elle yazılmış liste
ONAY = ESKI_ONAY | {"install_app"}  # sonradan eklenen, bilerek onaya tabi araçlar (internetten program kurar)
ESKI_EYLEM = {"write_file", "edit_file", "run_command", "run_python", "start_team_task", "install_python_package"}


class AracKaydi(unittest.TestCase):
    def test_her_yerlesik_arac_kayitli_ve_tutarli(self):
        for name, t in REGISTRY.tools.items():
            if t.source != "yerlesik":
                continue
            self.assertIn(t.risk, RISKS, name)
            self.assertTrue(t.label[0], f"{name}: Türkçe etiket yok")
            self.assertEqual(t.schema.get("type"), "object", name)
            ornek = {"integer": 1, "number": 1.0, "boolean": True, "array": [], "object": {}}  # türe uygun sahte değer
            props = t.schema.get("properties", {})
            self.assertIsNone(tools.validate_input(name, {k: ornek.get(props.get(k, {}).get("type"), "x")
                                                         for k in t.schema.get("required", [])})
                              if name not in ("generate_image",) else None)

    def test_onay_kurallari_eskisiyle_ayni(self):
        for name in REGISTRY.tools:
            if REGISTRY.tools[name].source != "yerlesik" or name == "call_api":
                continue
            self.assertEqual(tools.needs_approval(name, {}), name in ONAY, name)
        self.assertFalse(tools.needs_approval("call_api", {"method": "GET"}))
        self.assertTrue(tools.needs_approval("call_api", {"method": "POST"}))
        self.assertTrue(tools.needs_approval("olmayan_arac", {}))

    def test_eylem_siniflari(self):
        for name in ESKI_EYLEM:
            self.assertTrue(is_action(name, {"command": "rm x"}), name)
        self.assertTrue(is_action("generate_image", {}))  # bilinçli değişiklik: resim de dosya yazar
        self.assertTrue(is_action("install_app", {"name": "x"}))  # ✓ beklenirken kurulmaz
        for name in ("read_file", "web_search", "remember", "look_at_image", "delegate_to_agent"):
            self.assertFalse(is_action(name, {}), name)
        self.assertFalse(is_action("run_command", {"command": "ls -la"}))  # salt okunur komut

    def test_resim_araci_dogrulanabiliyor(self):
        # eski hata: generate_image ALL_SPECS'te yoktu, her çağrı "Unknown tool" dönüyordu
        self.assertIsNone(tools.validate_input("generate_image", {"prompt": "a cat"}))

    def test_profil_araclari(self):
        ana = {s["name"] for s in build_tool_specs(None, [])}
        self.assertTrue({"run_command", "write_file", "remember", "look_at_image", "install_python_package"} <= ana)
        arastirma = AgentProfile(id="t", name="t", tools=["web_search", "fetch_url"])
        kisitli = {s["name"] for s in build_tool_specs(arastirma, [])}
        self.assertNotIn("run_command", kisitli)
        self.assertNotIn("install_python_package", kisitli)
        self.assertIn("remember", kisitli)

    def test_dogrulama_turleri(self):
        self.assertIsNone(tools.validate_input("read_file", {"path": "a", "start_line": "5"}))
        self.assertEqual(tools.validate_input("read_file", {}), "Missing required argument: path")
        self.assertEqual(tools.validate_input("yok", {}), "Unknown tool: yok")


class Mcp(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        mcp.CONFIG_DIR.mkdir(parents=True, exist_ok=True)
        mcp.CONFIG_FILE.write_text(json.dumps({"mcpServers": {
            "ornek": {"command": sys.executable, "args": [str(KOK / "testler" / "ornek_mcp_sunucu.py")],
                      "trusted": ["not_yaz"]},
            "bozuk": {"command": "boyle-bir-komut-yok-123"},
            "kapali": {"command": "x", "disabled": True},
        }}), encoding="utf-8")
        cls.rapor = mcp.start_all(_GECICI)

    @classmethod
    def tearDownClass(cls):
        mcp.stop_all()

    def test_baslatma_raporu(self):
        self.assertEqual(self.rapor["ornek"], "3 araç")
        self.assertTrue(self.rapor["bozuk"].startswith("hata"))
        self.assertNotIn("kapali", self.rapor)
        durum = {d["name"]: d["state"] for d in mcp.status()}
        self.assertEqual(durum, {"ornek": "çalışıyor", "bozuk": "hata", "kapali": "devre dışı"})

    def test_araclar_kayitta(self):
        topla = REGISTRY.get("ornek__topla")
        self.assertIsNotNone(topla)
        self.assertEqual(topla.risk, "okur")  # readOnlyHint
        self.assertEqual(REGISTRY.get("ornek__not_yaz").risk, "calistirir")
        self.assertFalse(tools.needs_approval("ornek__topla", {}))
        self.assertFalse(tools.needs_approval("ornek__not_yaz", {}))  # trusted listesinde
        self.assertTrue(tools.needs_approval("ornek__hata_ver", {}))
        self.assertTrue(is_action("ornek__not_yaz", {}))
        self.assertFalse(is_action("ornek__topla", {}))
        self.assertIn("ornek__topla", {s["name"] for s in build_tool_specs(None, [])})
        kisitli = AgentProfile(id="t", name="t", tools=["web_search"])
        self.assertNotIn("ornek__topla", {s["name"] for s in build_tool_specs(kisitli, [])})

    def test_arac_cagirma(self):
        box = tools.Toolbox(_GECICI)
        self.assertIsNone(tools.validate_input("ornek__topla", {"a": 2, "b": 3.5}))
        self.assertEqual(box.run("ornek__topla", {"a": 2, "b": 3.5}), "5.5")
        self.assertEqual(box.run("ornek__not_yaz", {"metin": "merhaba"}), "kaydedildi: merhaba")
        with self.assertRaises(tools.ToolError) as hata:
            box.run("ornek__hata_ver", {})
        self.assertIn("bilerek hata", str(hata.exception))

    def test_durdurunca_kayittan_cikar(self):
        mcp.start_all(_GECICI, only="ornek")  # yeniden başlatma: eski araçlar silinip yenisi eklenir
        self.assertEqual(len([t for t in REGISTRY.external() if t.source == "mcp:ornek"]), 3)


class CagriIpucu(unittest.TestCase):
    def test_api_404_dogru_kullanimi_gosterir(self):
        from unittest import mock

        import httpx

        from asistan import api_catalog

        conn = api_catalog.builtin_connections()[0]
        box = tools.Toolbox(tempfile.mkdtemp(), [conn])
        resp = httpx.Response(404, json={"error": True}, request=httpx.Request("GET", conn.base_url))
        with mock.patch.object(tools.httpx, "request", return_value=resp):
            out = box._tool_call_api(conn.slug, path="/weather")
        self.assertIn("How to use this API", out)
        self.assertIn(conn.description[:30], out)


if __name__ == "__main__":
    unittest.main()
