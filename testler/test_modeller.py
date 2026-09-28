"""Model adları koda gömülmez (K2, CLAUDE.md mimari kural 2): tek kaynak `asistan/ayar/modeller.json`.

Denetimler: (1) `/kontrol` 7'nin deseni `asistan/` altındaki Python kodunda eşleşmez (adresler hariç: Claude Code'un
kurulum sayfası bir model adı değil), (2) modeller.json'un yapısı (4 kademe, roller, modüllerin okuduğu anahtarlar),
(3) modüllerin sabitleri json'dan geliyor.
"""

import os
import re
import sys
import tempfile
import unittest
from pathlib import Path

KOK = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(KOK))

_GECICI = tempfile.mkdtemp(prefix="yeni-nesil-cafer-test-")
os.environ["XDG_CONFIG_HOME"] = str(Path(_GECICI) / "ayar")
os.environ["XDG_DATA_HOME"] = str(Path(_GECICI) / "veri")

from asistan.cekirdek import modeller  # noqa: E402

DESEN = re.compile(r"ollama run|:[0-9.]+b\b|claude-|gpt-")  # .claude/commands/kontrol.md madde 7
ADRES = re.compile(r"https?://\S+")


class KoddaModelAdiYok(unittest.TestCase):
    def test_desen_eslesmez(self):
        bulunan = []
        for yol in sorted((KOK / "asistan").rglob("*.py")):
            for no, satir in enumerate(yol.read_text(encoding="utf-8").splitlines(), 1):
                if DESEN.search(ADRES.sub("", satir)):
                    bulunan.append(f"{yol.relative_to(KOK)}:{no}: {satir.strip()}")
        self.assertEqual(bulunan, [], "model adı ayar/modeller.json'a taşınmalı:\n" + "\n".join(bulunan))

    def test_komut_yazdirilmaz(self):
        """CLAUDE.md: kullanıcıya hiçbir zaman komut yazdırılmaz (model indirme Modeller menüsünden)."""
        for yol in (KOK / "asistan").rglob("*.py"):
            self.assertNotIn("ollama pull ", yol.read_text(encoding="utf-8"), str(yol))


class ModellerDosyasi(unittest.TestCase):
    def test_kademeler_ve_roller(self):
        veri = modeller.yukle()
        self.assertEqual(set(veri["kademe"]), set(modeller.KADEMELER))
        for k in modeller.KADEMELER:
            liste = modeller.kademe_modelleri(k)
            self.assertIsInstance(liste["yerel"], list)
            self.assertTrue(liste["yerel"] or liste["bulut"], k)
        self.assertEqual(modeller.kademe_modelleri("sunucu")["yerel"], [])  # GPU'suz sunucu: yalnız bulut
        self.assertEqual(modeller.kademe_modelleri("yok"), {"yerel": [], "bulut": []})
        for rol in ("yonetici", "hizli", "kod"):
            self.assertTrue(modeller.rol(rol), rol)
        self.assertNotIn("gecici", veri)  # kademe listeleri onaylandı (2026-09-28); geçici işaret kalktı
        # varsayılan Claude modeli kademe listelerindeki adla aynı (yuksek kademenin ilk bulut modeli)
        self.assertEqual(veri["varsayilan"]["claude"], veri["kademe"]["yuksek"]["bulut"][0])

    def test_modullerin_okudugu_anahtarlar(self):
        for yol in ("temel.model", "temel.boyut_gb", "varsayilan.ollama", "varsayilan.claude", "varsayilan.bulut_sunucu",
                    "gomme", "gorme", "gorme_uzmani", "ocr", "arac_ustasi", "dikte_temizleme", "basamaklar", "destek",
                    "kategoriler.boyutlar", "kategoriler.kucuk", "kategoriler.modeller", "claude.modeller",
                    "claude.yedekli", "claude.dusunmesiz", "bulut_katalog", "cli", "sansursuz",
                    "aileler.kusak_puani", "aileler.arac_cagiramaz", "aileler.akil_yurutme", "aileler.kod",
                    "aileler.kod_menusu"):
            self.assertIsNotNone(modeller.deger(yol), yol)

    def test_kopya_doner(self):
        modeller.deger("kategoriler.kucuk").append("bozuk")
        self.assertNotIn("bozuk", modeller.deger("kategoriler.kucuk"))

    def test_kademe_modelleri_bilinen_modeller(self):
        """Kademe listelerindeki yerel modeller programın bildiği modellerden (boyutu belli)."""
        bilinen = set(modeller.deger("kategoriler.boyutlar"))
        bilinen |= {m[0] for b in modeller.deger("basamaklar").values() for m in b["modeller"]}
        for k in modeller.KADEMELER:
            for m in modeller.kademe_modelleri(k)["yerel"]:
                self.assertIn(m, bilinen, f"{k}: {m}")


class ModullerJsondanOkur(unittest.TestCase):
    def test_sabitler(self):
        from asistan import agent, cards, catalog, categories, cli_agents, config, memory_db, sysinfo

        self.assertEqual(sysinfo.BASE_MODEL, (modeller.deger("temel.model"), modeller.deger("temel.boyut_gb")))
        self.assertEqual(config.Settings().ollama_model, modeller.deger("varsayilan.ollama"))
        self.assertEqual(config.CLAUDE_MODELS, modeller.deger("claude.modeller"))
        self.assertEqual(memory_db.EMBED_MODEL, modeller.deger("gomme"))
        self.assertEqual(categories.BY_ID["dil"].models, modeller.deger("kategoriler.modeller.dil"))
        self.assertEqual(agent.CLAUDE_NO_THINKING, set(modeller.deger("claude.dusunmesiz")))
        self.assertEqual(cards.NO_TOOL_FAMILIES, tuple(modeller.deger("aileler.arac_cagiramaz")))
        self.assertEqual([m for m, _ in catalog.BY_ID["anthropic"].chat],
                         [m for m, _ in modeller.deger("bulut_katalog.anthropic.chat")])
        self.assertEqual(cli_agents.CLAUDE.default, modeller.deger("cli.cli:claude")[0][0])


if __name__ == "__main__":
    unittest.main()
