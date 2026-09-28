"""Sansürsüz kip: seçilebilecek modeller yalnızca araç sınavını (cards.py) tam geçen kurulu sansürsüz modellerdir."""

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

from asistan import cards, roster  # noqa: E402


class SansursuzSecim(unittest.TestCase):
    def test_yalnizca_sinavi_tam_gecenler(self):
        kartlar = {"huihui_ai/qwen3-abliterated:14b": 2, "huihui_ai/gemma-4-abliterated:12b": 1, "dolphin3:8b": 0}
        kurulu = list(kartlar) + ["huihui_ai/yeni-abliterated:8b"]  # sonuncusu henüz sınanmadı (kart yok)
        with mock.patch.object(cards, "tools_level", side_effect=lambda m: kartlar.get(m)):
            self.assertEqual(roster.sansursuz_secilebilir(kurulu), ["huihui_ai/qwen3-abliterated:14b"])

    def test_sansurlu_model_listeye_girmez(self):
        with mock.patch.object(cards, "tools_level", return_value=2):
            self.assertEqual(roster.sansursuz_secilebilir(["qwen3.5:4b", "huihui_ai/qwen3-abliterated:14b"]),
                             ["huihui_ai/qwen3-abliterated:14b"])

    def test_ollama_beyani_yetmez(self):
        # kart yok: Ollama "tools" dese de sınanmamış model seçilemez (üreticinin beyanı kanıt değil)
        with mock.patch.object(cards, "tools_level", return_value=None):
            self.assertEqual(roster.sansursuz_secilebilir(["dolphin3:8b", "huihui_ai/qwen3-abliterated:14b"]), [])


if __name__ == "__main__":
    unittest.main()
