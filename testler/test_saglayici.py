"""Sağlayıcı arayüzü (`asistan.cekirdek.saglayici`): Ollama, Claude, OpenAI uyumlu, CLI ajanı.

Gerçek sağlayıcıya gidilmez: httpx.stream / httpx.get, Anthropic istemcisi ve cli_agents.run sahte.

Çalıştırma (proje kökünde, programın Python'uyla):
    ~/.local/share/yeni-nesil-cafer-app/python/bin/python3 -m unittest discover -s testler -v
"""

import json
import os
import sys
import tempfile
import unittest
from contextlib import closing
from pathlib import Path
from unittest import mock

KOK = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(KOK))

_GECICI = tempfile.mkdtemp(prefix="yeni-nesil-cafer-test-")
os.environ["XDG_CONFIG_HOME"] = str(Path(_GECICI) / "ayar")
os.environ["XDG_DATA_HOME"] = str(Path(_GECICI) / "veri")

import httpx  # noqa: E402

from asistan import agent as ag  # noqa: E402
from asistan import cli_agents  # noqa: E402
from asistan.cekirdek import saglayici as sg  # noqa: E402
from asistan.cekirdek.saglayici import claude as sg_claude  # noqa: E402
from asistan.cekirdek.saglayici import cli_ajan as sg_cli  # noqa: E402
from asistan.cekirdek.saglayici import ollama as sg_ollama  # noqa: E402
from asistan.cekirdek.saglayici.openai_uyumlu import OpenAIUyumluSaglayici  # noqa: E402
from asistan.config import Settings  # noqa: E402
from asistan.connections import Connection  # noqa: E402


class _Akim:
    """httpx.stream yerine: satırları verir, kapatıldı mı ve kaç satır okundu kaydeder."""

    def __init__(self, satirlar, durum=200, govde=""):
        self.satirlar, self.status_code, self.text = list(satirlar), durum, govde
        self.okunan, self.kapandi = 0, False

    def __enter__(self): return self

    def __exit__(self, *a):
        self.kapandi = True
        return False

    def read(self): pass

    def iter_lines(self):
        for s in self.satirlar:
            self.okunan += 1
            yield s


def _ollama(*mesajlar, son=None):
    satirlar = [json.dumps({"message": m}) for m in mesajlar]
    satirlar.append(json.dumps({"message": {}, "done": True, **(son or {"done_reason": "stop", "eval_count": 3})}))
    return satirlar


class OllamaTesti(unittest.TestCase):
    def test_parcalar_ve_son(self):
        akim = _Akim(_ollama({"thinking": "düşün"}, {"content": "mer"}, {"content": "haba"},
                             {"tool_calls": [{"function": {"name": "list_files", "arguments": {}}}]}))
        gonderilen = {}

        def sahte(method, url, json=None, timeout=None):
            gonderilen.update(url=url, govde=json)
            return akim

        s = sg_ollama.OllamaSaglayici("http://kutu:11434/", "qwen")
        with mock.patch.object(httpx, "stream", sahte):
            parcalar = list(s.akis([{"role": "user", "content": "selam"}], "sistem", num_ctx=4096, dusunme=False))
        self.assertEqual([p.tur for p in parcalar], [sg.DUSUNCE, sg.METIN, sg.METIN, sg.ARAC, sg.SON])
        self.assertEqual(parcalar[-1].araclar[0]["function"]["name"], "list_files")
        self.assertEqual(parcalar[-1].son["eval_count"], 3)
        self.assertEqual(gonderilen["url"], "http://kutu:11434/api/chat")
        govde = gonderilen["govde"]
        self.assertEqual(govde["messages"][0], {"role": "system", "content": "sistem"})
        self.assertEqual(govde["options"], {"num_ctx": 4096})
        self.assertIs(govde["think"], False)
        self.assertNotIn("tools", govde)

    def test_sohbet_birlestirir(self):
        akim = _Akim(_ollama({"content": "a"}, {"content": "b"}))
        with mock.patch.object(httpx, "stream", lambda *a, **k: akim):
            yanit = sg_ollama.OllamaSaglayici("http://x", "m").sohbet([{"role": "user", "content": "?"}])
        self.assertEqual(yanit.metin, "ab")
        self.assertEqual(yanit.araclar, [])

    def test_erken_kapatma_akisi_keser(self):
        akim = _Akim(_ollama(*[{"content": "x"}] * 100))
        with mock.patch.object(httpx, "stream", lambda *a, **k: akim):
            with closing(sg_ollama.OllamaSaglayici("http://x", "m").akis([])) as akis:
                for i, _ in enumerate(akis):
                    if i == 2:
                        break
        self.assertTrue(akim.kapandi)
        self.assertLess(akim.okunan, 10)

    def test_arac_desteklemeyen_model(self):
        akim = _Akim([], 400, '{"error":"registry.ollama.ai/library/gemma3 does not support tools"}')
        with mock.patch.object(httpx, "stream", lambda *a, **k: akim):
            with self.assertRaises(sg_ollama.AracDesteklenmiyor):
                list(sg_ollama.OllamaSaglayici("http://x", "gemma3").akis([], araclar=[{"type": "function"}]))
        self.assertIs(ag._NoToolSupport, sg_ollama.AracDesteklenmiyor)

    def test_http_hatasi(self):
        akim = _Akim([], 500, "model yüklenemedi")
        with mock.patch.object(httpx, "stream", lambda *a, **k: akim):
            with self.assertRaises(sg.SaglayiciHatasi) as h:
                list(sg_ollama.OllamaSaglayici("http://x", "m").akis([]))
        self.assertEqual(h.exception.durum, 500)
        self.assertIn("Ollama hatası (500)", str(h.exception))

    def test_bos_akis_takilma_sayilir(self):
        akim = _Akim([json.dumps({"message": {}})] * 3)
        with mock.patch.object(httpx, "stream", lambda *a, **k: akim):
            with self.assertRaises(httpx.ReadTimeout):
                list(sg_ollama.OllamaSaglayici("http://x", "m").akis([], okuma_zaman_asimi=-1))

    def test_saglik(self):
        s = sg_ollama.OllamaSaglayici("http://x", "qwen")
        istek = httpx.Request("GET", "http://x/api/tags")
        with mock.patch.object(httpx, "get", return_value=httpx.Response(200, json={"models": [{"name": "qwen"}]},
                                                                         request=istek)):
            self.assertTrue(s.saglik().iyi)
            self.assertEqual(sg_ollama.model_adlari("http://x"), ["qwen"])
        with mock.patch.object(httpx, "get", return_value=httpx.Response(200, json={"models": []})):
            self.assertIn("kurulu değil", s.saglik().neden)
        with mock.patch.object(httpx, "get", side_effect=httpx.ConnectError("yok")):
            self.assertFalse(s.saglik().iyi)
        self.assertEqual(s.maliyet(1000, 1000), 0.0)


def _sse(*parcalar):
    return [f"data: {json.dumps(p)}" for p in parcalar] + ["data: [DONE]"]


class OpenAIUyumluTesti(unittest.TestCase):
    def baglanti(self, **k):
        return Connection(kind="llm", name="Groq", base_url="https://api.groq.com/openai/v1/", models=["m"], **k)

    def test_arac_parcalari_birlesir(self):
        akim = _Akim(_sse(
            {"choices": [{"delta": {"reasoning_content": "hmm"}}]},
            {"choices": [{"delta": {"content": "tamam"}}]},
            {"choices": [{"delta": {"tool_calls": [{"index": 0, "id": "c1", "function": {"name": "read_",
                                                                                          "arguments": "{\"pa"}}]}}]},
            {"choices": [{"delta": {"tool_calls": [{"index": 0, "function": {"name": "file", "arguments": "th\": 1}"}}]}}]},
            {"choices": [], "usage": {"prompt_tokens": 7, "completion_tokens": 2}}))
        gonderilen = {}

        def sahte(method, url, json=None, headers=None, timeout=None):
            gonderilen.update(url=url, govde=json, basliklar=headers)
            return akim

        s = OpenAIUyumluSaglayici(self.baglanti())
        with mock.patch.object(httpx, "stream", sahte):
            yanit = s.sohbet([{"role": "user", "content": "?"}], "sistem", [{"type": "function"}], json_bicimi=True)
        self.assertEqual(gonderilen["url"], "https://api.groq.com/openai/v1/chat/completions")
        self.assertEqual(gonderilen["govde"]["response_format"], {"type": "json_object"})
        self.assertEqual(yanit.metin, "tamam")
        self.assertEqual(yanit.dusunce, "hmm")
        self.assertEqual(yanit.araclar, [{"id": "c1", "type": "function",
                                          "function": {"name": "read_file", "arguments": "{\"path\": 1}"}}])
        self.assertEqual(yanit.son["usage"]["completion_tokens"], 2)
        self.assertEqual(yanit.son["parca"], 3)

    def test_hata_durum_kodunu_tasir(self):
        akim = _Akim([], 401, '{"error": "invalid api key"}')
        with mock.patch.object(httpx, "stream", lambda *a, **k: akim):
            with self.assertRaises(sg.SaglayiciHatasi) as h:
                list(OpenAIUyumluSaglayici(self.baglanti()).akis([]))
        self.assertEqual((h.exception.durum, h.exception.ad), (401, "Groq"))

    def test_saglik_anahtarsiz(self):
        s = OpenAIUyumluSaglayici(self.baglanti(auth="bearer"))
        with mock.patch.object(Connection, "usable", new_callable=mock.PropertyMock, return_value=False):
            self.assertFalse(s.saglik().iyi)
        with mock.patch.object(Connection, "usable", new_callable=mock.PropertyMock, return_value=True):
            self.assertTrue(s.saglik().iyi)
        self.assertIsNone(s.maliyet(1, 1))


class ClaudeTesti(unittest.TestCase):
    def test_parametreler(self):
        s = sg_claude.ClaudeSaglayici(model="m")
        p = s.parametreler("sistem", [{"name": "a"}], dusunme=False, sunucu_yedegi=True)
        self.assertEqual(p["tools"], [{"name": "a", "eager_input_streaming": True}])
        self.assertNotIn("thinking", p)
        self.assertEqual(p["fallbacks"], "default")
        self.assertIn("thinking", s.parametreler("sistem"))
        self.assertNotIn("tools", s.parametreler("sistem"))

    def test_akis_ve_son_yanit(self):
        olaylar = [mock.Mock(type="thinking", thinking="dü"), mock.Mock(type="text", text="selam")]
        akim = mock.MagicMock()
        akim.__enter__.return_value = akim
        akim.__iter__.return_value = iter(olaylar)
        akim.get_final_message.return_value = "SON"
        istemci = mock.Mock()
        istemci.beta.messages.stream.return_value = akim
        s = sg_claude.ClaudeSaglayici(lambda: istemci, "m")
        yanit = s.sohbet([{"role": "user", "content": "?"}], "sistem")
        self.assertEqual((yanit.metin, yanit.dusunce, yanit.son["yanit"]), ("selam", "dü", "SON"))
        self.assertEqual(istemci.beta.messages.stream.call_args.kwargs["system"], "sistem")

    def test_saglik(self):
        with mock.patch.dict(os.environ, {"ANTHROPIC_API_KEY": ""}):
            self.assertFalse(sg_claude.ClaudeSaglayici(anahtar_getir=lambda: "").saglik().iyi)
            self.assertTrue(sg_claude.ClaudeSaglayici(anahtar_getir=lambda: "sk-x").saglik().iyi)


class CliAjanTesti(unittest.TestCase):
    def test_istem_gecmisi_ekler(self):
        self.assertEqual(sg_cli.istem([{"role": "user", "content": "yalnız"}]), "yalnız")
        metin = sg_cli.istem([{"role": "user", "content": "önce"}, {"role": "assistant", "content": "cevap"},
                              {"role": "user", "content": "şimdi"}])
        self.assertTrue(metin.startswith("Earlier conversation:\nuser: önce"))
        self.assertTrue(metin.endswith("Current request:\nşimdi"))

    def test_sohbet_cli_calistirir(self):
        with mock.patch.object(cli_agents, "run", return_value="bitti") as run:
            yanit = sg_cli.CliAjanSaglayici("cli:codex", "gpt").sohbet(
                [{"role": "user", "content": "yap"}], "sistem", klasor="/tmp", duzenleyebilir=False)
        self.assertEqual(yanit.metin, "bitti")
        self.assertEqual(run.call_args.args[:4], ("cli:codex", "yap", "/tmp", "sistem"))
        self.assertEqual(run.call_args.kwargs["edits"], False)
        self.assertEqual(run.call_args.kwargs["model"], "gpt")

    def test_saglik_ve_bilinmeyen(self):
        with mock.patch.object(cli_agents, "installed", return_value=False):
            self.assertIn("kurulu değil", sg_cli.CliAjanSaglayici("cli:gemini").saglik().neden)
        with mock.patch.object(cli_agents, "installed", return_value=True), \
                mock.patch.object(cli_agents, "logged_in", return_value=True):
            self.assertTrue(sg_cli.CliAjanSaglayici("cli:gemini").saglik().iyi)
        with self.assertRaises(ValueError):
            sg_cli.CliAjanSaglayici("cli:yok")


class _Cb:
    def __init__(self, iptal_sonra=None):
        self.metin, self.sayac, self.iptal_sonra = "", 0, iptal_sonra

    def on_text(self, d): self.metin += d
    def on_thinking(self, d): pass
    def on_model_start(self, n): pass
    def on_model_end(self, s): pass
    def on_tool_start(self, *a): pass
    def on_tool_end(self, *a): pass
    def ask_approval(self, *a): return True

    def is_cancelled(self):
        self.sayac += 1
        return self.iptal_sonra is not None and self.sayac > self.iptal_sonra


def _ajan(cb, baglantilar=()):
    a = ag.Agent(Settings(workspace=str(Path(_GECICI) / "is"), auto_ctx=False, ollama_num_ctx=16384), cb, None,
                 list(baglantilar))
    a.tool_specs = []
    return a


class AjanDuzeyiTesti(unittest.TestCase):
    """Sağlayıcıya taşınan davranışın ajan tarafında korunduğu (K1 denetimi: ■ boş akışta da çalışmalı)."""

    def test_bos_ollama_akisinda_iptal(self):
        akim = _Akim([""] * 50 + [json.dumps({"message": {}})] * 50 + _ollama({"content": "geç"}))
        a = _ajan(_Cb(iptal_sonra=5))
        with mock.patch.object(httpx, "stream", lambda *k, **kw: akim), mock.patch.object(ag.sysinfo, "make_room"):
            with self.assertRaises(ag.Cancelled):
                a._ollama_call("http://x/api/chat", {"role": "system", "content": "s"}, [{"role": "user", "content": "?"}], [])
        self.assertLess(akim.okunan, 10)  # boş satırlarda da her satırda denetlendi
        self.assertTrue(akim.kapandi)

    def test_bos_openai_akisinda_iptal(self):
        akim = _Akim([": OPENROUTER PROCESSING"] * 50 + _sse({"choices": [{"delta": {"content": "geç"}}]}))
        conn = Connection(kind="llm", name="OR", base_url="http://x/v1", models=["m"], id="or1")
        a = _ajan(_Cb(iptal_sonra=5), [conn])
        with mock.patch.object(httpx, "stream", lambda *k, **kw: akim):
            with self.assertRaises(ag.Cancelled):
                a._run_openai([{"role": "user", "content": "?"}], conn)
        self.assertLess(akim.okunan, 10)

    def test_401_anahtar_hatasina_cevrilir(self):
        from asistan import connections

        conn = Connection(kind="llm", name="Groq", base_url="https://api.groq.com/openai/v1", models=["m"], id="g401")
        a = _ajan(_Cb(), [conn])
        with mock.patch.object(httpx, "stream", lambda *k, **kw: _Akim([], 401, '{"error": "invalid api key"}')):
            with self.assertRaises(RuntimeError) as h:
                a._run_openai([{"role": "user", "content": "x"}], conn)
        self.assertIn("API anahtarı", str(h.exception))
        self.assertIn("g401", connections._REJECTED)  # bu oturumda otomatik seçilmez
        self.assertNotIsInstance(h.exception, sg.SaglayiciHatasi)

    def test_http_hatasi_kullaniciya_eskisi_gibi(self):
        a = _ajan(_Cb())
        with mock.patch.object(httpx, "stream", lambda *k, **kw: _Akim([], 500, "x" * 700)), \
                mock.patch.object(ag.sysinfo, "make_room"):
            with self.assertRaises(RuntimeError) as h:
                a._ollama_call("http://x/api/chat", {"role": "system", "content": "s"}, [{"role": "user", "content": "?"}], [])
        self.assertEqual(ag.describe_error(h.exception), "RuntimeError: Ollama hatası (500): " + "x" * 700)
        conn = Connection(kind="llm", name="LM", base_url="http://x/v1", models=["m"], id="lm")
        with mock.patch.object(httpx, "stream", lambda *k, **kw: _Akim([], 503, "y" * 700)):
            with self.assertRaises(RuntimeError) as h:
                a._run_openai([{"role": "user", "content": "?"}], conn)
        self.assertEqual(ag.describe_error(h.exception), "RuntimeError: LM hatası (503): " + "y" * 500)

    def test_arac_desteklemeyen_modelde_aracsiz_yeniden_dener(self):
        a = _ajan(_Cb())
        a.tool_specs = [{"name": "list_files", "description": "d", "input_schema": {"type": "object", "properties": {}}}]
        akimlar = [_Akim([], 400, '{"error":"does not support tools"}'), _Akim(_ollama({"content": "araçsız cevap"}))]
        gonderilen = []

        def sahte(method, url, json=None, timeout=None):
            gonderilen.append(json)
            return akimlar.pop(0)

        with mock.patch.object(httpx, "stream", sahte), mock.patch.object(ag.sysinfo, "make_room"), \
                mock.patch.object(ag.specialists, "_capabilities", return_value=[]):
            a.run("ollama", [], "merhaba")
        self.assertIn("tools", gonderilen[0])
        self.assertNotIn("tools", gonderilen[1])
        self.assertTrue(a.no_tools)
        self.assertIn("araçsız cevap", a.cb.metin)


class BulTesti(unittest.TestCase):
    def test_kimlikten_sinif(self):
        s = Settings(ollama_url="http://kutu:1", ollama_model="qwen", claude_model="c", api_models={"b1": "m2"})
        conn = Connection(kind="llm", name="X", base_url="http://x/v1", models=["m1", "m2"], id="b1")
        self.assertIsInstance(sg.bul("ollama", s), sg_ollama.OllamaSaglayici)
        self.assertEqual(sg.bul("ollama", s).model, "qwen")
        self.assertIsInstance(sg.bul("claude", s), sg_claude.ClaudeSaglayici)
        self.assertIsInstance(sg.bul("cli:codex", s), sg_cli.CliAjanSaglayici)
        api = sg.bul("api:b1", s, [conn])
        self.assertEqual((api.ad, api.model), ("api:b1", "m2"))
        for ad in ("api:yok", "bilinmeyen"):
            with self.assertRaises(KeyError):
                sg.bul(ad, s, [conn])

    def test_eski_adlar_ayni_nesneler(self):
        self.assertIs(ag.Cancelled, sg.Iptal)
        self.assertIs(ag.describe_error, sg.hata_metni)
        self.assertIs(ag.list_ollama_models, sg_ollama.model_adlari)
        self.assertIn("Ollama", sg.hata_metni(httpx.ConnectError("x")))
        self.assertEqual(sg.hata_metni(ValueError("bozuk")), "ValueError: bozuk")


if __name__ == "__main__":
    unittest.main()
