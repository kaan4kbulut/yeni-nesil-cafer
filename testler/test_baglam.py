"""Bağlam özetleme ve ASISTAN.md talimat dosyası testleri.

Çalıştırma (proje kökünde, programın Python'uyla):
    ~/.local/share/yeni-nesil-cafer-app/python/bin/python3 -m unittest discover -s testler -v
"""

import os
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

KOK = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(KOK))

_GECICI = tempfile.mkdtemp(prefix="yeni-nesil-cafer-test-")
os.environ["XDG_CONFIG_HOME"] = str(Path(_GECICI) / "ayar")
os.environ["XDG_DATA_HOME"] = str(Path(_GECICI) / "veri")

from asistan import agent as ag  # noqa: E402
from asistan.config import Settings  # noqa: E402


class _Cb:
    def __init__(self):
        self.text = ""

    def on_text(self, d): self.text += d
    def is_cancelled(self): return False


def uzun_gecmis(tur: int = 8) -> list:
    msgs = []
    for i in range(tur):
        msgs += [{"role": "user", "content": f"istek {i}: " + "ayrıntı " * 150},
                 {"role": "assistant", "content": f"cevap {i}: " + "sonuç " * 150}]
    msgs.append({"role": "user", "content": "son istek"})
    return msgs


class OzetTesti(unittest.TestCase):
    def ajan(self, num_ctx=2048):
        s = Settings(workspace=str(Path(_GECICI) / "is"), auto_ctx=False, ollama_num_ctx=num_ctx)
        a = ag.Agent(s, _Cb())
        return a

    def test_uzun_gecmis_ozetlenir_mesajlar_silinmez(self):
        a = self.ajan()
        msgs = uzun_gecmis()
        with mock.patch.object(ag.power, "num_ctx", return_value=2048), \
                mock.patch.object(a, "_summarize", return_value="- kullanıcı 3D yazıcı aldı") as ozet:
            a._compact(msgs, {"role": "system", "content": "x"}, [])
        ozet.assert_called_once()
        self.assertEqual(len(msgs), 18)  # 17 eski + özet; hiçbiri silinmedi
        self.assertTrue(all(m.get(ag.COMPACTED) for m in msgs[:16]))
        self.assertTrue(msgs[16].get(ag.SUMMARY))
        giden = ag._clean(msgs)
        self.assertEqual([m["content"] for m in giden][-1], "son istek")
        self.assertIn("3D yazıcı", giden[0]["content"])
        self.assertEqual(len(giden), 2)
        self.assertTrue(all(not k.startswith("_") for m in giden for k in m))

    def test_kisa_gecmis_ozetlenmez(self):
        a = self.ajan(num_ctx=32768)
        msgs = uzun_gecmis(2)
        with mock.patch.object(ag.power, "num_ctx", return_value=32768), \
                mock.patch.object(a, "_summarize") as ozet:
            a._compact(msgs, {"role": "system", "content": "x"}, [])
        ozet.assert_not_called()
        self.assertFalse(any(m.get(ag.COMPACTED) for m in msgs))

    def test_ozet_alinamazsa_gecmis_degismez(self):
        a = self.ajan()
        msgs = uzun_gecmis()
        with mock.patch.object(ag.power, "num_ctx", return_value=2048), \
                mock.patch.object(a, "_summarize", return_value=""):
            a._compact(msgs, {"role": "system", "content": "x"}, [])
        self.assertEqual(len(msgs), 17)
        self.assertFalse(any(m.get(ag.COMPACTED) for m in msgs))

    def test_dokum_onceki_ozeti_korur_eskiyi_atar(self):
        msgs = [{"role": "user", ag.PROGRAM: True, ag.SUMMARY: True, "content": "ÖNCEKİ ÖZET"}]
        msgs += [{"role": "user", "content": f"mesaj {i} " + "x" * 300} for i in range(10)]
        text = ag.transcript(msgs, 1500)
        self.assertTrue(text.startswith("Earlier summary:\nÖNCEKİ ÖZET"))
        self.assertIn("mesaj 9", text)
        self.assertNotIn("mesaj 0 ", text)

    def test_dokum_kullanicinin_eski_bilgisini_korur(self):
        # canlı denemede (qwen3.5:4b, 4K bağlam) ilk mesajdaki "Bambu Lab A1" özete girmemişti
        msgs = [{"role": "user", "content": "Bambu Lab A1 marka 3D yazıcı aldım."}]
        for i in range(7):
            msgs += [{"role": "user", "content": f"Konu {i}: " + "ayrıntı ver " * 60},
                     {"role": "assistant", "content": f"Öneri {i}: " + "duvar 3, dolgu %15. " * 60}]
        self.assertIn("Bambu Lab A1", ag.transcript(msgs, 4700))

    def test_fit_context_ozeti_atmaz(self):
        msgs = [{"role": "user", "content": "eski " * 400}, {"role": "assistant", "content": "cevap " * 400},
                {"role": "user", ag.PROGRAM: True, ag.SUMMARY: True, "content": ag.SUMMARY_HEAD + "]\n- 3D yazıcı"},
                {"role": "user", "content": "son istek"}]
        out = ag.fit_context(msgs, 1900, 100)  # bütçe eski turlara yetmiyor
        heads = [m["content"][:5] for m in out]
        self.assertNotIn("eski ", heads)
        self.assertEqual(heads[-2:], [ag.SUMMARY_HEAD[:5], "son i"])

    def test_fit_context_ozetlenenleri_gondermez(self):
        msgs = uzun_gecmis(2)
        for m in msgs[:2]:
            m[ag.COMPACTED] = True
        out = ag.fit_context(msgs, 32768, 100)
        self.assertEqual(len(out), 3)


class KisaTalimatTesti(unittest.TestCase):
    """Küçük bağlamlı yerel model: istek gerektirmeyen bölümler talimata girmez."""

    def test_buyuk_baglamda_hepsi_var(self):
        text = ag.system_prompt("/tmp/ws", None, "excel özetle") + ag.program_prompt(Settings(), "excel özetle")
        self.assertIn("open_app with the app name", text)
        self.assertIn("Layout: left panel", text)

    def test_kucuk_baglamda_yalnizca_gerekenler(self):
        s = Settings()
        text = ag.system_prompt("/tmp/ws", None, "excel özetle", lean=True) + ag.program_prompt(s, "excel özetle", True)
        self.assertNotIn("open_app with the app name", text)
        self.assertNotIn("Layout: left panel", text)
        self.assertIn("read its files there", text)  # programı yine tanır
        self.assertIn("open_app with the app name", ag.system_prompt("/tmp/ws", None, "telegram aç", lean=True))
        self.assertIn("Layout: left panel", ag.program_prompt(s, "sol paneldeki ajanlar sekmesi ne", True))

    def test_kucuk_baglamda_api_listesi_kisa(self):
        a = ag.Agent(Settings(workspace=str(Path(_GECICI) / "is")), _Cb())
        spec = next(t for t in a.tool_specs if t["name"] == "call_api")
        a.lean = True
        short = a._describe(spec)
        self.assertLess(len(short), len(spec["description"]) / 2)
        self.assertIn("find_api", short)
        a.lean = False
        self.assertEqual(a._describe(spec), spec["description"])


class TalimatDosyasiTesti(unittest.TestCase):
    def test_genelden_ozele_ve_kok_disina_cikmaz(self):
        dis = Path(tempfile.mkdtemp(prefix="dis-"))
        kok = dis / "calisma"
        is_ = kok / "Kod" / "site-1"
        is_.mkdir(parents=True)
        (dis / "ASISTAN.md").write_text("DIŞARIDAKİ", encoding="utf-8")
        (kok / "ASISTAN.md").write_text("genel kural", encoding="utf-8")
        (is_ / "ASISTAN.md").write_text("bu işe özel kural", encoding="utf-8")
        text = ag.instruction_files(str(is_), str(kok))
        self.assertLess(text.index("genel kural"), text.index("bu işe özel kural"))
        self.assertNotIn("DIŞARIDAKİ", text)

    def test_dosya_yoksa_bos(self):
        self.assertEqual(ag.instruction_files(tempfile.mkdtemp()), "")


class YontemTesti(unittest.TestCase):
    def test_yalnizca_var_olan_araclar_anilir(self):
        text = ag.method_prompt({"web_search", "install_python_package"})
        self.assertIn("install_python_package", text)
        for yok in ("install_app", "inspect_output", "learn_skill", "use_skill"):
            self.assertNotIn(yok, text)

    def ajan(self):
        a = ag.Agent(Settings(workspace=tempfile.mkdtemp()), _Cb())
        a.user_text, a.run_started, a.tools_used, a.tool_errors = "QR kod hazırla", time.time() - 1, set(), 0
        return a

    def test_gorsel_cikti_denetlenmeden_bitmez(self):
        a = self.ajan()
        (a.toolbox.root / "qr.png").write_bytes(b"x")
        state = {}
        nudge = a._unfinished_nudge([], "Hazır! Kontrol etmek ister misiniz?", True, 3, state)  # soru olsa da
        self.assertIn("inspect_output", nudge)
        self.assertIn("qr.png", nudge)
        a.tools_used.add("inspect_output")
        self.assertNotIn("inspect_output", a._unfinished_nudge([], "Hazır.", True, 4, state) or "")

    def test_cok_denemeden_sonra_ogrenmesi_istenir(self):
        a = self.ajan()
        a.tool_errors, a.actions_done = 3, 1
        state = {}
        self.assertIn("learn_skill", a._unfinished_nudge([], "Bitti.", True, 5, state))
        self.assertIsNone(a._unfinished_nudge([], "Bitti?", True, 6, state))  # bir kez

    def test_soruyla_biten_cevap_durtulmez(self):
        a = ag.Agent(Settings(workspace=str(Path(_GECICI) / "is")), _Cb())
        a.user_text = "Telefon tutucu yap"
        self.assertIsNone(a._unfinished_nudge([], "Telefonunuzun genişliği kaç mm?", True, 1, {}))


if __name__ == "__main__":
    unittest.main()
