"""K4 — şema-kısıtlı üretim (`cekirdek/yapisal.py`, eski Aşama 3) ve görev motorunun gerçek araç uyarlayıcısı
(`cekirdek/gorev/ajan.py`: `Agent._execute_tool` izin hattı). Sağlayıcılar sahte; ağa gidilmez.

Çalıştırma (proje kökünde, programın Python'uyla):
    ~/.local/share/yeni-nesil-cafer-app/python/bin/python3 -m unittest discover -s testler -v
"""

import os
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

KOK = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(KOK))
_GECICI = tempfile.mkdtemp(prefix="yeni-nesil-cafer-test-")
os.environ["XDG_CONFIG_HOME"] = str(Path(_GECICI) / "ayar")
os.environ["XDG_DATA_HOME"] = str(Path(_GECICI) / "veri")

from asistan.cekirdek import yapisal  # noqa: E402
from asistan.cekirdek.saglayici import SaglayiciHatasi, Yanit  # noqa: E402
from asistan.cekirdek.saglayici.openai_uyumlu import OpenAIUyumluSaglayici  # noqa: E402

SEMA = {"type": "object", "properties": {"eylem": {"type": "string", "enum": ["arac", "cevap"]},
                                          "gerekce": {"type": "string"}}, "required": ["eylem"]}


class SahteSaglayici:
    def __init__(self, ad, cevaplar, hata=None):
        self.ad, self.cevaplar, self.hata = ad, list(cevaplar), hata
        self.cagrilar = []

    def sohbet(self, mesajlar, sistem="", araclar=None, **secenek):
        self.cagrilar.append({"mesajlar": list(mesajlar), "sistem": sistem, **secenek})
        if self.hata and self.hata(secenek):
            raise SaglayiciHatasi(400, "response_format json_schema is not supported", "Sahte")
        c = self.cevaplar.pop(0)
        return c if isinstance(c, Yanit) else Yanit(c, [], {})


class YapisalTesti(unittest.TestCase):
    def test_ollama_format_ve_dusunmesiz(self):
        s = SahteSaglayici("ollama", ['{"eylem": "cevap"}'])
        sonuc = yapisal.uret(s, [{"role": "user", "content": "x"}], SEMA, model="m")
        self.assertEqual(sonuc.veri, {"eylem": "cevap"})
        self.assertEqual(s.cagrilar[0]["bicim"]["properties"]["eylem"]["enum"], ["arac", "cevap"])
        self.assertIs(s.cagrilar[0]["dusunme"], False)
        self.assertEqual(s.cagrilar[0]["model"], "m")

    def test_semaya_uymayan_bir_kez_duzelttirilir(self):
        s = SahteSaglayici("ollama", ['{"eylem": "uc"}', '```json\n{"eylem": "arac"}\n```'])
        sonuc = yapisal.uret(s, [{"role": "user", "content": "x"}], SEMA)
        self.assertEqual((sonuc.veri, sonuc.deneme), ({"eylem": "arac"}, 2))
        duzelt = s.cagrilar[1]["mesajlar"][-1]["content"]
        self.assertIn("eylem", duzelt)

    def test_iki_kez_uymazsa_veri_yok(self):
        s = SahteSaglayici("cli:claude", ["bilmiyorum", "yine metin"])
        sonuc = yapisal.uret(s, [{"role": "user", "content": "x"}], SEMA)
        self.assertIsNone(sonuc.veri)
        self.assertTrue(sonuc.hatalar)
        self.assertIn("JSON Schema", s.cagrilar[0]["sistem"])  # desteklemeyen sağlayıcı: talimat

    def test_ek_denetim_hatasi_da_duzeltilir(self):
        s = SahteSaglayici("ollama", ['{"eylem": "arac"}', '{"eylem": "cevap"}'])
        sonuc = yapisal.uret(s, [], SEMA, ek_denetim=lambda v: ["araç yok"] if v["eylem"] == "arac" else [])
        self.assertEqual(sonuc.veri, {"eylem": "cevap"})

    def test_openai_json_schema_desteklenmezse_json_object(self):
        s = SahteSaglayici("api:x", ['{"eylem": "cevap"}'], hata=lambda sec: "json_semasi" in sec)
        sonuc = yapisal.uret(s, [], SEMA)
        self.assertEqual(sonuc.veri, {"eylem": "cevap"})
        self.assertIs(s.cagrilar[-1]["json_bicimi"], True)
        self.assertIn("JSON Schema", s.cagrilar[-1]["sistem"])

    def test_openai_istek_govdesi(self):
        baglanti = SimpleNamespace(id="x", name="X", base_url="http://yok", key="k", models=["m"], usable=True)
        govde = OpenAIUyumluSaglayici(baglanti).istek([], "s", json_semasi=SEMA)
        self.assertEqual(govde["response_format"]["type"], "json_schema")
        self.assertEqual(govde["response_format"]["json_schema"]["schema"], SEMA)

    def test_claude_zorunlu_arac(self):
        from asistan.cekirdek.saglayici.claude import ClaudeSaglayici

        blok = SimpleNamespace(type="tool_use", input={"eylem": "arac", "gerekce": "g"})
        yanit = Yanit("", [], {"yanit": SimpleNamespace(content=[blok])})
        s = ClaudeSaglayici(lambda: None, "model")
        s.sohbet = lambda mesajlar, sistem="", araclar=None, **k: (setattr(s, "_param", k["parametreler"]) or yanit)
        sonuc = yapisal.uret(s, [], SEMA)
        self.assertEqual(sonuc.veri, {"eylem": "arac", "gerekce": "g"})
        self.assertEqual(s._param["tool_choice"], {"type": "tool", "name": yapisal.CLAUDE_ARACI})
        self.assertNotIn("thinking", s._param)


class AjanUyarlayiciTesti(unittest.TestCase):
    """Gerçek Agent + permissions: görev motoru izin hattını atlamaz."""

    def setUp(self):
        from asistan.config import Settings
        from asistan.cekirdek.gorev.ajan import AjanYetenekleri

        self.klasor = tempfile.mkdtemp(dir=_GECICI)
        Path(self.klasor, "not.txt").write_text("merhaba", encoding="utf-8")
        ayarlar = Settings.load()
        ayarlar.workspace = self.klasor
        ayarlar.approval_mode = "kullanici"
        ayarlar.confirm_commands = True
        self.yet = AjanYetenekleri(ayarlar, [], self.klasor)

    def test_yalnizca_manifestli_yetenekler(self):
        adlar = {y["ad"] for y in self.yet.listele()}  # K5: araç adları değil, yetenek manifestleri
        self.assertIn("dosya_oku", adlar)
        self.assertIn("python_calistir", adlar)
        self.assertNotIn("read_file", adlar)
        self.assertNotIn("delegate_to_agent", adlar)
        self.assertNotIn("remember", adlar)

    def test_yetenek_izin_hattindan_gecer(self):
        girdi = {"kod": "open('cikti.txt','w').write('x')", "amac": "test"}
        self.assertTrue(self.yet.onay_gerekir("python_calistir", girdi))
        c = self.yet.calistir("python_calistir", girdi)
        self.assertTrue(c.onay_bekliyor)
        self.assertFalse(Path(self.klasor, "cikti.txt").exists())
        c = self.yet.calistir("dosya_oku", {"yol": "not.txt"})
        self.assertFalse(c.hata or c.onay_bekliyor)
        self.assertIn("merhaba", c.metin)

    def test_okuma_onaysiz_calisir(self):
        self.assertFalse(self.yet.onay_gerekir("read_file", {"path": "not.txt"}))
        c = self.yet.calistir("read_file", {"path": "not.txt"})
        self.assertFalse(c.hata or c.onay_bekliyor)
        self.assertIn("merhaba", c.metin)

    def test_kod_calistirma_onay_bekler(self):
        girdi = {"code": "open('cikti.txt','w').write('x')", "purpose": "test"}
        self.assertTrue(self.yet.onay_gerekir("run_python", girdi))
        c = self.yet.calistir("run_python", girdi)
        self.assertTrue(c.onay_bekliyor)
        self.assertFalse(Path(self.klasor, "cikti.txt").exists())

    def test_yasak_islem_onayla_da_calismaz(self):
        c = self.yet.calistir("run_command", {"command": "rm -rf /", "purpose": "x"}, onayli=True)
        self.assertTrue(c.hata)
        self.assertFalse(c.onay_bekliyor)

    def test_listede_olmayan_arac_reddedilir(self):
        c = self.yet.calistir("uydurma", {})
        self.assertTrue(c.hata)


if __name__ == "__main__":
    unittest.main()
