"""Bulut bağlantılarında bağlam: OpenAI uyumlu (kırpma, aşımda yarıya inip yeniden deneme) ve Claude ("too long").

Gerçek sağlayıcıya gidilmez: httpx.stream ve Anthropic istemcisi sahte.

Çalıştırma (proje kökünde, programın Python'uyla):
    ~/.local/share/yeni-nesil-cafer-app/python/bin/python3 -m unittest discover -s testler -v
"""

import json
import os
import sys
import tempfile
import unittest
from contextlib import contextmanager
from pathlib import Path
from unittest import mock

KOK = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(KOK))

_GECICI = tempfile.mkdtemp(prefix="yeni-nesil-cafer-test-")
os.environ["XDG_CONFIG_HOME"] = str(Path(_GECICI) / "ayar")
os.environ["XDG_DATA_HOME"] = str(Path(_GECICI) / "veri")

import anthropic  # noqa: E402
import httpx  # noqa: E402

from asistan import agent as ag  # noqa: E402
from asistan.config import Settings  # noqa: E402
from asistan.connections import Connection  # noqa: E402


class _Cb:
    def __init__(self):
        self.text = ""

    def on_text(self, d): self.text += d
    def on_thinking(self, d): pass
    def on_model_start(self, n): pass
    def on_model_end(self, s): pass
    def on_tool_start(self, *a): pass
    def on_tool_end(self, *a): pass
    def ask_approval(self, *a): return True
    def is_cancelled(self): return False


class _Resp:
    def __init__(self, status, text="", lines=()):
        self.status_code, self.text, self.lines = status, text, list(lines)

    def read(self):
        pass

    def iter_lines(self):
        yield from self.lines


def gecmis(tur: int) -> list:
    out = []
    for i in range(tur):
        out += [{"role": "user", "content": f"istek {i} " + "ayrıntı " * 400},
                {"role": "assistant", "content": f"cevap {i} " + "sonuç " * 400}]
    return out


def ajan() -> Agent:
    a = ag.Agent(Settings(workspace=str(Path(_GECICI) / "is")), _Cb())
    a.tool_specs = []  # araç tanımları testte gereksiz: bütçeyi mesajlar belirlesin
    return a


Agent = ag.Agent


class OpenAIBaglamTesti(unittest.TestCase):
    def setUp(self):
        ag._API_CTX.clear()

    def test_bilinmeyen_model_temkinli_varsayilan(self):
        self.assertEqual(ag.api_context("lm-studio-yerel-model"), ag.API_CTX)

    def test_asimda_yariya_inip_yeniden_dener(self):
        a = ajan()
        conn = Connection(kind="llm", name="LM Studio", base_url="http://localhost:1234/v1", models=["yerel"])
        gonderilen = []
        cevaplar = [_Resp(400, '{"error": "The number of tokens to keep from the initial prompt is greater than the '
                               'context length (n_ctx)"}'),
                    _Resp(200, lines=['data: ' + json.dumps({"choices": [{"delta": {"content": "tamam"}}]}),
                                      "data: [DONE]"])]

        @contextmanager
        def sahte(method, url, json=None, headers=None, timeout=None):
            gonderilen.append(len(json["messages"]))
            yield cevaplar.pop(0)

        msgs = gecmis(20) + [{"role": "user", "content": "son istek"}]  # ~16K token: 32K'ya sığar, 16K'ya sığmaz
        with mock.patch.object(ag.httpx, "stream", side_effect=sahte), \
                mock.patch.object(a, "_summarize", return_value=""):  # özet yok: kırpma devreye girer
            a._run_openai(msgs, conn)
        self.assertEqual(ag._API_CTX["yerel"], ag.API_CTX // 2)
        self.assertEqual(len(gonderilen), 2)
        self.assertLess(gonderilen[1], gonderilen[0])  # ikinci istekte eski turlar kırpıldı
        self.assertIn("tamam", a.cb.text)

    def test_baska_hata_yine_hata(self):
        a = ajan()
        conn = Connection(kind="llm", name="Groq", base_url="https://api.groq.com/openai/v1", models=["m"])

        @contextmanager
        def sahte(*_a, **_k):
            yield _Resp(401, '{"error": "invalid api key"}')

        with mock.patch.object(ag.httpx, "stream", side_effect=sahte):
            with self.assertRaises(RuntimeError):
                a._run_openai([{"role": "user", "content": "x"}], conn)
        self.assertNotIn("m", ag._API_CTX)

    def test_ozetleyici_yerel_baglami_asmaz(self):
        a = ajan()
        msgs = gecmis(10) + [{"role": "user", "content": "son istek"}]
        with mock.patch.object(a, "_summarize", return_value="- özet") as ozet, \
                mock.patch.object(ag.power, "num_ctx", return_value=8192):
            a._compact(msgs, {"content": "x"}, [], 1_000_000, force=True)
        self.assertEqual(ozet.call_args.args[1], 8192)  # bulut bağlamı 1M olsa da Ollama'ya 8K


class ClaudeBaglamTesti(unittest.TestCase):
    def test_cok_uzun_olunca_ozetleyip_yeniden_dener(self):
        a = ajan()
        hata = anthropic.BadRequestError("prompt is too long: 250000 tokens > 200000 maximum",
                                         response=httpx.Response(400, request=httpx.Request("POST", "http://x")),
                                         body=None)
        cagri = []

        class _Stream:
            def __enter__(self):
                if not cagri:
                    cagri.append(1)
                    raise hata
                cagri.append(2)
                return self

            def __exit__(self, *e):
                return False

            def __iter__(self):
                return iter([])

            def get_final_message(self):
                usage = mock.Mock(input_tokens=1, output_tokens=1, cache_read_input_tokens=0,
                                  cache_creation_input_tokens=0)
                return mock.Mock(stop_reason="end_turn", content=[], usage=usage, model="claude")

        client = mock.Mock()
        client.beta.messages.stream.side_effect = lambda **k: _Stream()
        with mock.patch.object(a, "_claude_client", return_value=client), \
                mock.patch.object(a, "_compact") as compact:
            a._run_claude(gecmis(3) + [{"role": "user", "content": "son"}])
        self.assertEqual(cagri, [1, 2])
        self.assertTrue(compact.call_args.kwargs.get("force"))


if __name__ == "__main__":
    unittest.main()
