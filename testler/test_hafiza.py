"""Hafıza (Aşama 4) testleri: SQLite deposu, JSON'dan içe aktarma, anlamsal ve kelime araması, beceriler,
başarısızlıklar ve planlama notu. Embedding modeli sahte: kelimelerden tutarlı küçük vektörler üretir."""

import json
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

from asistan import learning, memory_db  # noqa: E402

# anlam grupları: aynı gruptaki kelimeler aynı yöne düşer ("rapor" ~ "excel özet tablosu")
_GROUPS = [("rapor", "excel", "tablo", "özet", "xlsx"), ("çay", "demle", "kahve"), ("python", "kod", "betik"),
           ("isim", "adım", "deniz"), ("grafik", "çiz", "png")]


def _fake_embed(texts, task="document", url=""):
    out = []
    for t in texts:
        t = t.lower()
        vec = [float(sum(t.count(w) for w in g)) for g in _GROUPS] + [0.01]
        out.append(vec)
    return out


class _Depo(unittest.TestCase):
    semantic = True

    def setUp(self):
        d = Path(tempfile.mkdtemp(dir=_GECICI))
        memory_db.reset_for_tests(d / "hafiza.db")
        learning.MEMORY_FILE, learning.SKILLS_FILE = d / "hafiza.json", d / "beceriler.json"
        patches = [mock.patch.object(memory_db, "embedding_available", return_value=self.semantic)]
        if self.semantic:
            patches.append(mock.patch.object(memory_db, "embed", side_effect=_fake_embed))
        for p in patches:
            p.start()
            self.addCleanup(p.stop)


class AnlamsalHafiza(_Depo):
    def test_ekle_guncelle_sil(self):
        self.assertIn("eklendi", learning.remember("Excel raporlarında özet tablo en üstte olsun", "tercih"))
        self.assertIn("güncellendi", learning.remember("Excel raporlarında özet tablo en üstte olsun.", "tercih"))
        self.assertEqual(len(learning.memories()), 1)
        learning.forget(learning.memories()[0]["id"])
        self.assertEqual(learning.memories(), [])

    def test_talimata_ilgili_bilgi_ve_hep_tercihler(self):
        learning.remember("Cevapları kısa ver", "tercih")
        learning.remember("Çayı demlikte 15 dakika demlerim", "bilgi")
        learning.remember("Python betikleri ~/betikler klasöründe", "bilgi")
        prompt = learning.memory_prompt("bir python kodu yaz")
        self.assertIn("Cevapları kısa ver", prompt)  # tercih her zaman
        self.assertLess(prompt.index("betikler"), prompt.index("demlikte"))  # ilgili olan önce

    def test_beceri_anlamdan_bulunur(self):
        learning.save_skill("satış verisinden excel özet tablosu oluştur", [("run_python", {"code": "df.to_excel()"})])
        found = learning.find_skills("aylık rapor hazırla xlsx olarak")
        self.assertEqual(len(found), 1)
        self.assertIn("to_excel", found[0]["code"])
        self.assertEqual(learning.find_skills("çay nasıl demlenir anlat"), [])

    def test_basarisizlik_planlamaya_girer(self):
        learning.record_failure("grafik çiz ve kaydet", "grafik.png çiz", "matplotlib yok", ["run_python"], "qwen3.5:4b")
        learning.record_failure("grafik çiz ve kaydet", "grafik.png çiz", "matplotlib yok", ["run_python"], "qwen3.5:4b")
        self.assertEqual(len(learning.failures()), 1)
        self.assertEqual(learning.failures()[0]["count"], 2)  # aynı ders sayılır, çoğalmaz
        note = learning.planning_prompt("bir grafik çiz png olarak")
        self.assertIn("FAILED before (2x)", note)
        self.assertIn("matplotlib yok", note)
        self.assertEqual(learning.planning_prompt("çay demle"), "")


class KelimeAramasi(_Depo):
    semantic = False  # embedding modeli yok: eski kelime kökü araması

    def test_model_yokken_de_calisir(self):
        learning.save_skill("satış verisinden excel özet tablosu oluştur ve kaydet",
                            [("run_python", {"code": "x"})])
        self.assertEqual(len(learning.find_skills("satış verisinden excel özet tablosu hazırla")), 1)
        learning.remember("Adım Deniz", "bilgi")
        self.assertIn("Deniz", learning.memory_prompt("merhaba"))


class IceAktarma(_Depo):
    semantic = False

    def test_eski_json_bir_kez_aktarilir(self):
        learning.MEMORY_FILE.write_text(json.dumps([{"id": "a1", "text": "Koyu tema seviyorum", "kind": "tercih",
                                                     "created": 1.0}]), encoding="utf-8")
        learning.SKILLS_FILE.write_text(json.dumps([{"id": "s1", "title": "Rapor", "request": "rapor hazırla",
                                                     "code": "print(1)", "steps": [], "successes": 3}]),
                                        encoding="utf-8")
        self.assertEqual([m["text"] for m in learning.memories()], ["Koyu tema seviyorum"])
        sk = learning.skills()[0]
        self.assertEqual((sk["id"], sk["request"], sk["successes"], sk["code"]), ("s1", "rapor hazırla", 3, "print(1)"))
        learning.forget("a1")
        self.assertEqual(learning.memories(), [])  # ikinci çağrıda yeniden aktarılmaz
        self.assertTrue(learning.MEMORY_FILE.exists())  # eski dosya silinmez


class Projeler(_Depo):
    def test_devam_istegi_dogru_klasoru_bulur(self):
        kod = Path(tempfile.mkdtemp(dir=_GECICI))
        rapor = Path(tempfile.mkdtemp(dir=_GECICI))
        learning.save_project(str(kod), "python betik", "dosyaları yeniden adlandıran bir python betiği yaz")
        learning.save_project(str(rapor), "aylık rapor", "satışlardan excel özet tablosu hazırla")
        learning.save_project(str(rapor), "aylık rapor", "", last="özet tablo yazıldı")  # güncelleme, yeni kayıt değil
        found = learning.find_project("excel raporuna kaldığımız yerden devam et")
        self.assertEqual(found["folder"], str(rapor))
        self.assertEqual(found["last"], "özet tablo yazıldı")
        self.assertEqual(len(memory_db.items(("proje",))), 2)

    def test_devam_demeyen_istek_yeni_is_sayilir(self):
        rapor = Path(tempfile.mkdtemp(dir=_GECICI))
        learning.save_project(str(rapor), "aylık rapor", "satışlardan excel özet tablosu hazırla")
        self.assertIsNone(learning.find_project("yeni bir excel tablosu hazırla"))

    def test_silinmis_klasor_yok_sayilir(self):
        learning.save_project(str(Path(_GECICI, "yok")), "aylık rapor", "excel özet tablosu hazırla")
        self.assertIsNone(learning.find_project("excel tablosuna devam et"))


class EkipmanTesti(_Depo):
    semantic = False  # sahte vektörler grup dışı iki metni "aynı" sayar; burada kelime araması yeter

    def test_ekipman_ilgisiz_istekte_de_talimatta(self):
        learning.remember("3D yazıcı: Bambu Lab A1, tabla 256x256x256 mm", "ekipman")
        learning.remember("Kedimin adı Pamuk", "bilgi")
        text = learning.memory_prompt("telefon tutucu yap")
        self.assertIn("[Ekipman] 3D yazıcı: Bambu Lab A1", text)


if __name__ == "__main__":
    unittest.main()
