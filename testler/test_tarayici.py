"""Tarayıcı (BrowserAgent) testleri: onay kapısı, tarayıcı işi tanıma, ajan tarafında her zaman sorma, profil ekleme.
Gerçek tarayıcı açan testler unittest'te değil (pencere açar): testler/tarayici_gercek.py, elle çalıştırılır."""

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

from asistan import browser, manager, tools  # noqa: E402,F401
from asistan.agent import Agent, build_tool_specs  # noqa: E402
from asistan.categories import BROWSER_AGENT  # noqa: E402


class Kapi(unittest.TestCase):
    def test_gruplar(self):
        sor = [("click", {"role": "button", "name": "Siparişi onayla"}, ""),
               ("click", {"role": "button", "name": "Hemen Al"}, ""),
               ("click", {"role": "button", "name": "Devam"}, "https://x.com/checkout"),
               ("click", {"role": "button", "name": "Gönder"}, ""),
               ("click", {"role": "link", "name": "Hesabımı sil", "href": "/h"}, ""),
               ("click", {"role": "link", "name": "Kur", "href": "/a/setup.exe"}, ""),
               ("click", {"role": "button", "name": "Giriş yap"}, ""),
               ("click", {"role": "button", "name": "Devam", "form_sensitive": True}, ""),
               ("type", {"role": "textbox", "type": "password"}, ""),
               ("type", {"role": "textbox", "autocomplete": "cc-number"}, "")]
        for action, el, url in sor:
            self.assertIsNotNone(browser.gate(action, el, url), el)
        serbest = [("click", {"role": "button", "name": "Sepete ekle"}, ""),
                   ("click", {"role": "link", "name": "Fiyatları & Satın Al", "href": "/laptop"}, ""),
                   ("click", {"role": "link", "name": "Ürün detayı"}, "https://x.com/checkout"),
                   ("type", {"role": "combobox", "name": "Ara"}, ""),
                   ("type", {"role": "textbox", "searchish": True}, "")]
        for action, el, url in serbest:
            self.assertIsNone(browser.gate(action, el, url, submit=True), el)
        # arama dışı bir alana yazıp Enter: forma gönderme sayılır
        self.assertIsNotNone(browser.gate("type", {"role": "textbox", "name": "Mesaj"}, "", "selam", submit=True))

    def test_tarayici_isi_tanima(self):
        for t in ("Hepsiburada'da ekran kartı fiyatlarına bak", "youtube'a gir ve son videoyu bul",
                  "https://example.com sayfasını aç", "internetten mağazalara gir, yağları karşılaştır"):
            self.assertTrue(manager.is_browser_task(t), t)
        for t in ("bugün dolar kaç", "rapor.xlsx oluştur", "merhaba"):
            self.assertFalse(manager.is_browser_task(t), t)


class _Olay:
    def __init__(self, answer):
        self.answer, self.asked = answer, []

    def ask_approval(self, name, args):
        self.asked.append((name, args))
        return self.answer

    def __getattr__(self, name):
        return lambda *a, **k: None


class AjanKapisi(unittest.TestCase):
    def _agent(self, answer):
        a = Agent.__new__(Agent)
        a.cb = _Olay(answer)
        return a

    def _fake(self, element, url="https://shop.example/sepet"):
        b = mock.Mock(url=mock.Mock(return_value=url), element=mock.Mock(return_value=element), approved_download=False)
        return mock.patch.object(browser, "get", return_value=b), b

    def test_hep_izin_ver_secili_olsa_bile_sorar_ve_reddi_uygular(self):
        a = self._agent(False)
        a.always_allowed = True  # "bu oturumda hep izin ver": tarayıcı kapısını etkilemez
        p, _ = self._fake({"role": "button", "name": "Siparişi onayla", "ref": 3})
        with p:
            msg = a._browser_gate("browser_click", {"ref": 3})
        self.assertEqual(len(a.cb.asked), 1)
        self.assertIn("NOT DONE", msg)

    def test_sifre_gizli_gosterilir_indirme_onayi(self):
        a = self._agent(True)
        p, _ = self._fake({"role": "textbox", "type": "password", "ref": 5})
        with p:
            self.assertIsNone(a._browser_gate("browser_type", {"ref": 5, "text": "gizli123"}))
        self.assertEqual(a.cb.asked[0][1]["text"], "••••••")
        p, b = self._fake({"role": "link", "name": "İndir", "href": "/x.zip", "ref": 2})
        with p:
            a._browser_gate("browser_click", {"ref": 2})
        self.assertTrue(b.approved_download)

    def test_serbest_eylem_sorulmaz(self):
        a = self._agent(False)
        p, _ = self._fake({"role": "button", "name": "Sepete ekle", "ref": 1}, "https://shop.example/urun")
        with p:
            self.assertIsNone(a._browser_gate("browser_click", {"ref": 1}))
        self.assertEqual(a.cb.asked, [])


class Profil(unittest.TestCase):
    def test_araclar_yalniz_tarayici_ajaninda(self):
        with mock.patch.object(browser, "available", return_value=True):
            names = {s["name"] for s in build_tool_specs(BROWSER_AGENT, [])}
            main = {s["name"] for s in build_tool_specs(None, [])}
        self.assertTrue({"browser_open", "browser_click", "browser_look"} <= names)
        self.assertFalse(any(n.startswith("browser_") for n in main))  # ana asistan işi tarayıcı ajanına devreder

    def test_profil_bir_kez_eklenir(self):
        from asistan import profiles

        d = Path(tempfile.mkdtemp(dir=_GECICI))
        with mock.patch.object(profiles, "CONFIG_DIR", d), mock.patch.object(profiles, "PROFILES_FILE", d / "ajanlar.json"):
            (d / ".ajan-kategorileri").write_text("1")  # kategoriler daha önce eklenmiş kullanıcı
            ps = profiles.default_profiles()
            self.assertTrue(profiles._categorize(ps))
            self.assertIn("tarayici", [p.id for p in ps])
            ps = [p for p in ps if p.id != "tarayici"]  # kullanıcı sildi
            self.assertFalse(profiles._categorize(ps))
            self.assertNotIn("tarayici", [p.id for p in ps])  # geri gelmez


if __name__ == "__main__":
    unittest.main()
