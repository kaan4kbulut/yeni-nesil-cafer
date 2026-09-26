"""Model önerileri farklı donanımlarda: kurulum sihirbazı (sysinfo.recommend) ve ajan kategorileri (categories.models_for).

Çalıştırma (proje kökünde, programın Python'uyla):
    ~/.local/share/yeni-nesil-cafer-app/python/bin/python3 -m unittest discover -s testler -v
"""

import sys
import unittest
from pathlib import Path

KOK = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(KOK))

from asistan import categories, sysinfo  # noqa: E402

GUCLU = sysinfo.SystemInfo(vram_gb=11.9, ram_gb=31.0)  # 12 GB ekran kartlı dizüstü
ORTA = sysinfo.SystemInfo(vram_gb=6.0, ram_gb=16.0)
ZAYIF = sysinfo.SystemInfo(vram_gb=0.0, ram_gb=8.0)  # ekran kartsız dizüstü


class OneriTesti(unittest.TestCase):
    def test_sihirbaz_hafiza_modelini_hep_onerir(self):
        for info in (GUCLU, ORTA, ZAYIF):
            _, sug = sysinfo.recommend(info, {})
            hafiza = [s for s in sug if s.model == "nomic-embed-text:latest"]
            self.assertEqual(len(hafiza), 1, info)
            self.assertTrue(hafiza[0].checked)

    def test_sihirbaz_ocr_yalnizca_sigarsa_ve_secili_gelmez(self):
        _, sug = sysinfo.recommend(GUCLU, {})
        ocr = [s for s in sug if s.kind == "ocr"]
        self.assertEqual(len(ocr), 1)
        self.assertFalse(ocr[0].checked)
        _, sug = sysinfo.recommend(ZAYIF, {})
        self.assertTrue(any(s.kind == "ocr" for s in sug))  # işlemcide 8 GB RAM'e sığar (2.2×1.5+2 = 5.3)
        _, sug = sysinfo.recommend(sysinfo.SystemInfo(vram_gb=0.0, ram_gb=4.0), {})
        self.assertFalse(any(s.kind == "ocr" for s in sug))  # 4 GB RAM: sığmaz

    def test_kategoriler_donanima_gore(self):
        kod = categories.BY_ID["problem"]
        self.assertEqual(categories.models_for(kod, GUCLU), kod.models)  # 12 GB: liste olduğu gibi
        orta = categories.models_for(kod, ORTA)
        self.assertNotIn("qwen2.5-coder:14b", orta)  # 9 GB model 6 GB karta sığmaz
        self.assertTrue(orta)
        for cat in categories.CATEGORIES:
            for info in (GUCLU, ORTA, ZAYIF):
                models = categories.models_for(cat, info)
                self.assertTrue(models, (cat.id, info))
                for m in models:  # önerilen her model sığar (hiçbiri sığmıyorsa en küçük tek model)
                    self.assertTrue(sysinfo.fits(info, categories.SIZES.get(m, 0.0)) or models == ["qwen3.5:2b"],
                                    (cat.id, m, info))
        self.assertEqual(categories.models_for(kod), kod.models)  # donanım bilinmiyorsa değişmez

    def test_eksik_modeller_donanima_gore(self):
        kod = categories.BY_ID["problem"]
        eksik = {m for m, _ in categories.missing_models(kod, set(), ORTA)}
        self.assertNotIn("qwen2.5-coder:14b", eksik)


class KartsizTesti(unittest.TestCase):
    def test_bilinen_aracsiz_aileler_kart_yokken_de_secilmez(self):
        from unittest import mock

        from asistan import cards

        with mock.patch.object(cards, "card", return_value=None):  # yeni kurulum: hiç kart yok
            self.assertEqual(cards.tools_level("qwen2.5-coder:14b"), 0)
            self.assertEqual(cards.tools_level("gemma3:12b"), 0)
            self.assertIsNone(cards.tools_level("qwen3.5:9b"))  # bilinmiyor: Ollama'nın beyanına bakılır
        with mock.patch.object(cards, "card", return_value={"tools": 2}):  # sınav yapıldıysa kart geçerli
            self.assertEqual(cards.tools_level("qwen2.5-coder:14b"), 2)


if __name__ == "__main__":
    unittest.main()
