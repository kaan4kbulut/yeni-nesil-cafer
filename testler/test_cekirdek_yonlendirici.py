"""K3 — model yönlendirici (`asistan/cekirdek/yonlendirici.py`): MIMARI §4 kural sırası, sağlık önbelleği, yedekleme
zinciri, bulut tavanı ve yönetici politikası (eski Aşama 2). Sağlayıcılar ve adaylar sahte; ağa ve modele gidilmez.

Çalıştırma (proje kökünde, programın Python'uyla):
    ~/.local/share/yeni-nesil-cafer-app/python/bin/python3 -m unittest discover -s testler -v
"""

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

from asistan import connections, permissions, roster  # noqa: E402
from asistan.cekirdek import ayar, yonlendirici as y  # noqa: E402
from asistan.cekirdek.saglayici import Saglik  # noqa: E402
from asistan.config import Settings  # noqa: E402

A = y.Aday
KUCUK = A("ollama", "kucuk:4b", True, 12, 2, True, boyut_gb=3)
BUYUK = A("ollama", "buyuk:12b", True, 20, 2, True, boyut_gb=8)
DEV = A("ollama", "dev:27b", True, 30, 2, True, boyut_gb=18)  # 12 GB karta sığmaz
ARACSIZ = A("ollama", "aracsiz:12b", True, 25, 0, False, boyut_gb=8)
SANSURSUZ = A("ollama", "serbest:4b", True, 11, 2, True, sansursuz=True, boyut_gb=3)
UCUZ = A("api:x", "ucuz-bulut", False, 70, 2)
GUCLU = A("claude", "guclu-bulut", False, 100, 2)
CLI = A("cli:claude", "claude-code", False, 95, 2, True)
HEPSI = [KUCUK, BUYUK, DEV, ARACSIZ, SANSURSUZ, UCUZ, GUCLU, CLI]


def durum(**k):
    k.setdefault("vram_gb", 12)
    k.setdefault("kademe", "yuksek")
    return y.Durum(**k)


class KuralSirasi(unittest.TestCase):
    """MIMARI §4: çevrimdışı → gizlilik → görev türü → kademe (her kural için en az bir senaryo)."""

    def test_1_cevrimdisi_yalnizca_yerel(self):
        s = y.karar(HEPSI, "yonetici", durum(cevrimici=False))
        self.assertEqual(s.saglayici, "ollama")
        self.assertIn("çevrimdışı", s.neden)
        self.assertTrue(all(k[0] == "ollama" for k in s.zincir))

    def test_1_cevrimdisi_yerel_yoksa_bekler(self):
        s = y.karar([UCUZ, GUCLU], "hizli", durum(cevrimici=False))
        self.assertIsNone(s.saglayici)
        self.assertTrue(s.bekleyen)
        self.assertIn("çevrimdışı", s.etiket())

    def test_2_gizlilik_yerel_bulutu_kapatir(self):
        s = y.karar(HEPSI, "kod", durum(gizlilik="yerel"))
        self.assertEqual(s.saglayici, "ollama")
        self.assertIn("gizlilik yerel", s.neden)
        self.assertIsNone(y.karar([GUCLU], "hizli", durum(gizlilik="yerel")).saglayici)

    def test_2_gizlilik_bulut_hizli_isi_ucuz_buluta(self):
        self.assertEqual(y.karar(HEPSI, "hizli", durum(gizlilik="bulut")).model, "ucuz-bulut")

    def test_3_gorev_turu_rolleri(self):
        # özet → hızlı: karta sığan, araç sınavını geçen EN KÜÇÜK yerel (BÖLÜM 2.6; modeller.json roller.hizli
        # "en ucuz/hızlı"); ölçüm varsa tok/sn en yüksek olan (dev:27b sığmıyor, aracsiz araç kullanamıyor)
        s = y.karar(HEPSI, "ozet", durum())
        self.assertEqual(s.model, "kucuk:4b")
        self.assertEqual(s.zincir[:2], [BUYUK.anahtar, DEV.anahtar])  # büyükler zincirde üst basamak
        self.assertEqual(y.karar(HEPSI, "ozet", durum(hiz={"buyuk:12b": 60.0, "kucuk:4b": 40.0})).model, "buyuk:12b")
        s = y.karar(HEPSI, "ozet", durum(hiz={"kucuk:4b": 40.0}))
        self.assertEqual(s.model, "kucuk:4b")
        self.assertIn("40 tok/sn", s.neden)
        self.assertEqual(y.karar(HEPSI, "planlama", durum()).saglayici, "cli:claude")  # yönetici
        self.assertEqual(y.karar(HEPSI, "kod_uretimi", durum()).saglayici, "cli:claude")  # CLI ajan varsa o
        self.assertEqual(y.karar([KUCUK, UCUZ, GUCLU], "kod_uretimi", durum()).model, "guclu-bulut")  # sonra bulut
        self.assertEqual(y.karar([KUCUK, BUYUK], "kod_uretimi", durum()).model, "buyuk:12b")  # yoksa yerel
        with self.assertRaises(ValueError):
            y.karar(HEPSI, "bilinmeyen", durum())

    def test_3_kuyruktan_gelen_istekte_cli_yok(self):
        s = y.karar(HEPSI, "kod", durum(kullanici_istegi=False))
        self.assertEqual(s.model, "guclu-bulut")

    def test_4_dusuk_kademede_yonetici_buluta(self):
        zayif = A("ollama", "zayif:2b", True, 8, 2, False, boyut_gb=2)  # plan sınavını geçemedi
        s = y.karar([zayif, UCUZ], "yonetici", durum(kademe="dusuk", politika="yerel"))
        self.assertEqual(s.saglayici, "ollama")  # "yerel" politikası buluta gitmez
        s = y.karar([zayif, UCUZ], "yonetici", durum(kademe="dusuk", politika="otomatik"))
        self.assertEqual(s.model, "ucuz-bulut")

    def test_4_dusuk_kademe_bulut_yoksa_parcala(self):
        zayif = A("ollama", "zayif:2b", True, 8, 2, None, boyut_gb=2)
        s = y.karar([zayif], "yonetici", durum(kademe="dusuk"))
        self.assertEqual(s.model, "zayif:2b")
        self.assertTrue(s.parcala)
        self.assertIn("parçalan", s.neden)

    def test_karta_sigmayan_yerel_geride(self):
        s = y.karar([DEV, BUYUK], "hizli", durum(vram_gb=12))
        self.assertEqual(s.model, "buyuk:12b")
        self.assertEqual(s.zincir, [DEV.anahtar])  # sığmayan büyük model zincirde üst basamak
        # 24 GB kartta ikisi de sığar: hızlı rol yine küçüğü seçer, ölçüm büyüğü daha hızlı gösterirse büyüğü
        self.assertEqual(y.karar([DEV, BUYUK], "hizli", durum(vram_gb=24)).model, "buyuk:12b")
        self.assertEqual(y.karar([DEV, BUYUK], "hizli", durum(vram_gb=24, hiz={"dev:27b": 70.0})).model, "dev:27b")

    def test_durum_benchmarktan_hiz_okur(self):
        from asistan.cekirdek import profil

        kayit = {"gpu": {"vram_gb": 12}, "benchmark": {"kucuk:4b": {"tok_sn": 41.2}, "bozuk": {"atlandi": "x"}}}
        with mock.patch.object(profil, "yukle", return_value=kayit), mock.patch.object(profil, "kademe", return_value="yuksek"):
            self.assertEqual(y.durum(Settings()).hiz, {"kucuk:4b": 41.2})

    def test_yonetici_ile_sohbet_karta_sigmazsa_sohbet_modeli(self):
        orta = A("ollama", "orta:9b", True, 16, 2, True, boyut_gb=6)
        d = durum(politika="yerel", vram_gb=12)
        self.assertEqual(y.karar([KUCUK, BUYUK], "yonetici", d, sohbet=KUCUK.anahtar).model, "buyuk:12b")  # 3+8 sığar
        s = y.karar([orta, BUYUK], "yonetici", d, sohbet=orta.anahtar)  # 6+8 > 12: gidip gelmesin
        self.assertEqual(s.model, "orta:9b")
        self.assertIn("birlikte karta sığmaz", s.neden)
        self.assertEqual(y.karar([orta, BUYUK], "yonetici", durum(politika="yerel", vram_gb=24),
                                 sohbet=orta.anahtar).model, "buyuk:12b")

    def test_sansursuz_normale_gecmez(self):
        s = y.karar(HEPSI, "hizli", durum(sansursuz=True))
        self.assertEqual(s.model, "serbest:4b")
        self.assertNotIn(SANSURSUZ.anahtar, [a.anahtar for a in y.havuz(HEPSI, durum())[0]])

    def test_secim_bicimi(self):
        s = y.karar(HEPSI, "ozet", durum())
        self.assertEqual(set(s.sozluk()), {"saglayici", "model", "neden"})  # SEMALAR §2 adimlar[i].secim
        self.assertTrue(s.etiket().startswith("ollama/kucuk:4b — neden: "))


class Saglik_(unittest.TestCase):
    def setUp(self):
        self.saat = [0.0]
        self.sorular = []

        def sorgu(ad, _=None):
            self.sorular.append(ad)
            return Saglik(ad != "claude", "anahtar yok" if ad == "claude" else "")

        self.o = y.SaglikOnbellegi(sorgu=sorgu, saat=lambda: self.saat[0])

    def test_bes_dakika_onbellek(self):
        self.assertTrue(self.o.iyi("ollama"))
        self.saat[0] = 299
        self.assertTrue(self.o.iyi("ollama"))
        self.assertEqual(self.sorular, ["ollama"])  # 5 dk içinde yeniden sorulmadı
        self.saat[0] = 301
        self.o.iyi("ollama")
        self.assertEqual(self.sorular, ["ollama", "ollama"])

    def test_sagliksiz_daha_kisa_ve_bildir(self):
        self.assertFalse(self.o.iyi("claude"))
        self.saat[0] = 61
        self.o.iyi("claude")
        self.assertEqual(self.sorular.count("claude"), 2)  # sağlıksız sonuç 1 dk'da tazelenir
        self.o.bildir("ollama", False, "bağlanılamadı")
        self.assertEqual(self.o.bilinen_sagliksiz("ollama").neden, "bağlanılamadı")
        self.assertNotIn("ollama", self.sorular)

    def test_sagliksiz_saglayici_zincirden_duser(self):
        s = y.karar(HEPSI, "yonetici", durum(), saglik=lambda ad: Saglik(False, "401") if ad.startswith("cli:")
                    or ad == "claude" else None)
        self.assertEqual(s.model, "ucuz-bulut")
        self.assertNotIn(CLI.anahtar, s.zincir)

    def test_sorgu_hatasi_programi_durdurmaz(self):
        o = y.SaglikOnbellegi(sorgu=lambda ad, _=None: 1 / 0)
        self.assertFalse(o.iyi("ollama"))


class YedeklemeZinciri(unittest.TestCase):
    def test_iki_basarisizlikta_ust_basamak(self):
        s = y.karar([KUCUK, BUYUK, DEV, UCUZ], "hizli", durum(vram_gb=12))
        z = y.Zincir.secimden(s)
        self.assertEqual(z.su_an, KUCUK.anahtar)  # hızlı rol: en küçük; zincir yukarı doğru
        self.assertEqual(z.basarisiz("dosya yok"), KUCUK.anahtar)  # 1. başarısızlık: aynı model
        self.assertEqual(z.basarisiz("yine yok"), BUYUK.anahtar)  # 2. → yerel büyük
        self.assertEqual(z.basarisiz("zaman", zaman_asimi=True), DEV.anahtar)  # zaman aşımı → hemen üst basamak
        self.assertEqual(z.basarisiz("zaman", zaman_asimi=True), UCUZ.anahtar)  # → bulut
        z.basarisiz("x")
        self.assertIsNone(z.basarisiz("x"))
        self.assertTrue(z.bitti)
        self.assertEqual(len(z.gecmis), 4)

    def test_zincir_sonu_hata_analizine_devredilir(self):
        z = y.Zincir([KUCUK.anahtar], esik=1)
        z.basarisiz("rapor.docx yok")
        kayit = z.hata_kaydi(3)
        self.assertEqual(kayit["sinif"], "model_yetersiz")  # SEMALAR §3
        self.assertEqual(set(kayit), {"adim", "zaman", "sinif", "belirti", "kanit", "eylem", "sonuc"})
        self.assertEqual(y.devret(kayit), "analiz")  # K6: cekirdek/analiz/hata.py sınıf + eylem, kütüğe yazar
        satir = (ayar.DATA_DIR / "hatalar.jsonl").read_text(encoding="utf-8").splitlines()[-1]
        self.assertEqual(json.loads(satir)["adim"], 3)
        self.assertEqual(json.loads(satir)["eylem"]["tip"], "yukselt")


class BulutTavani(unittest.TestCase):
    def setUp(self):
        y.gorev_basla()
        yol = ayar.DATA_DIR / "bulut_harcama.json"
        if yol.exists():
            yol.unlink()

    def test_harcama_ve_tavan(self):
        with mock.patch.dict(os.environ, {"CAFER_BULUT_GOREV_TAVAN_TOKEN": "1000",
                                          "CAFER_BULUT_GUNLUK_TAVAN_TOKEN": "5000"}):
            y.harcama_ekle("ollama", 900)  # yerel sayılmaz
            y.harcama_ekle("cli:claude", 900)  # abonelik sayılmaz
            self.assertEqual(y.tavan_durumu(), "")
            y.harcama_ekle("claude", 1200)
            self.assertIn("görev tavanı", y.tavan_durumu())
            self.assertEqual(y.gunluk_token(), 1200)
            y.gorev_basla()
            self.assertEqual(y.tavan_durumu(), "")
            y.harcama_ekle("api:x", 4000)
            self.assertIn("günlük tavan", y.tavan_durumu())

    def test_tavan_asilinca_karar_onay_ister(self):
        s = y.karar([KUCUK, GUCLU], "yonetici", durum(tavan="günlük tavan doldu"))
        self.assertEqual(s.model, "guclu-bulut")
        self.assertEqual(s.onay_gerekli, "günlük tavan doldu")
        self.assertIn(KUCUK.anahtar, s.zincir)  # onay verilmezse yerel yedek
        self.assertEqual(y.karar([KUCUK, CLI], "yonetici", durum(tavan="dolu")).onay_gerekli, "")  # abonelik

    def test_onay_kurali_permissions_da(self):
        self.assertEqual(permissions.bulut_tavani("").kind, permissions.ALLOW)
        self.assertEqual(permissions.bulut_tavani("doldu").kind, permissions.ASK)
        self.assertEqual(permissions.bulut_tavani("doldu", onaylandi=True).kind, permissions.ALLOW)


class Ayarlar(unittest.TestCase):
    def test_gizlilik_onceligi(self):
        s = Settings(extra={"gizlilik": "yerel"})
        self.assertEqual(y.gizlilik(Settings()), "karma")  # varsayılan (SEMALAR §5)
        self.assertEqual(y.gizlilik(s), "yerel")
        with mock.patch.dict(os.environ, {"CAFER_GIZLILIK_MOD": "bulut"}):
            self.assertEqual(y.gizlilik(s), "bulut")  # ayar.toml / ortam arayüzü ezer
            self.assertTrue(y.gizlilik_kilitli())
        self.assertEqual(y.politika(s), "yerel")  # gizlilik yerelken yönetici de yerel

    def test_kaynak(self):
        self.assertTrue(y.kullanici_istegi(Settings()))
        self.assertFalse(y.kullanici_istegi(Settings(extra={"istek_kaynagi": "kuyruk"})))
        from asistan import cloud_server

        s = cloud_server.settings_for_cloud({"model": "m"})
        self.assertFalse(y.kullanici_istegi(s))  # bulut kuyruğunda CLI ajanı seçilmez


class YoneticiPolitikasi(unittest.TestCase):
    """Eski Aşama 2: giriş yok / 401 / sansürsüz / kuyruktan gelen istek (sahte bağlantılarla)."""

    ADAYLAR = [roster.Candidate("ollama", "kucuk:4b", {"tools"}, 12, True, 4),
               roster.Candidate("ollama", "buyuk:12b", {"tools"}, 20, True, 12),
               roster.Candidate("ollama", "serbest:4b", {"tools"}, 11, True, 4)]
    KART = {"kucuk:4b": 2, "buyuk:12b": 2, "serbest:4b": 2}

    def setUp(self):
        roster._cache = None
        yamalar = [
            mock.patch.object(roster, "_ollama", return_value=list(self.ADAYLAR)),
            mock.patch.object(roster.cards, "tools_level", side_effect=lambda m: self.KART.get(m)),
            mock.patch.object(roster.cards, "card", side_effect=lambda m: {"tools": 2, "plan": True}
                              if m in self.KART else None),
            mock.patch.object(roster.model_updates, "is_uncensored", side_effect=lambda m: m.startswith("serbest")),
            mock.patch.object(roster.specialists, "_claude_available", return_value=False),
            mock.patch.object(y, "cevrimici", return_value=True),
            mock.patch("asistan.cekirdek.profil.kademe", return_value="yuksek"),
            mock.patch.object(y, "SAGLIK", y.SaglikOnbellegi(sorgu=lambda ad, _=None: Saglik(True))),
        ]
        self.baglantilar = []
        yamalar.append(mock.patch("asistan.connections.load_connections", side_effect=lambda: self.baglantilar))
        self.cli = mock.patch.object(roster.cli_agents, "available", return_value=False)
        yamalar.append(self.cli)
        for yama in yamalar:
            yama.start()
            self.addCleanup(yama.stop)
        self.addCleanup(lambda: setattr(roster, "_cache", None))

    def _baglanti(self, anahtar: str | None, reddedildi: bool = False):
        c = connections.Connection("llm", "OpenAI", "https://api.openai.com/v1", id="oa", preset="OpenAI",
                                   models=["bulut-model"])
        self.baglantilar[:] = [c]
        if reddedildi:
            connections._REJECTED.add("oa")
            self.addCleanup(connections._REJECTED.discard, "oa")
        return mock.patch.object(connections, "get_secret", return_value=anahtar)

    def secim(self, sohbet=("ollama", "kucuk:4b"), **extra):
        roster._cache = None
        return y.yonetici_sec(Settings(extra=extra), sohbet)

    def test_giris_yok_bulut_yok_en_guclu_yerel(self):
        s = self.secim()
        self.assertEqual(s.anahtar, ("ollama", "buyuk:12b"))
        self.assertIn("en güçlü yerel", s.neden)

    def test_claude_code_girisliyse_once_o(self):
        with mock.patch.object(roster.cli_agents, "available", return_value=True):
            s = self.secim()
            self.assertEqual(s.saglayici, "cli:claude")
            self.assertIn(("ollama", "buyuk:12b"), s.zincir)  # CLI hata verirse yedek
            self.assertEqual(self.secim(istek_kaynagi="kuyruk").saglayici, "ollama")  # kuyruktan: CLI yok
            self.assertEqual(self.secim(yonetici_politikasi="yerel").saglayici, "ollama")
            self.assertEqual(self.secim(gizlilik="yerel").saglayici, "ollama")

    def test_anahtarli_bulut_yonetici(self):
        with self._baglanti("sk-test"):
            s = self.secim()
        self.assertEqual(s.anahtar, ("api:oa", "bulut-model"))

    def test_anahtarsiz_ya_da_401_baglanti_hic_secilmez(self):
        with self._baglanti(None):
            self.assertEqual(self.secim().saglayici, "ollama")
            self.assertEqual(self.secim(yonetici_politikasi="bulut").saglayici, "ollama")  # bulut yoksa yerel
        with self._baglanti("sk-test", reddedildi=True):
            self.assertEqual(self.secim().saglayici, "ollama")

    def test_sansursuz_modda_yonetici_yalnizca_yerel(self):
        with self._baglanti("sk-test"), mock.patch.object(roster.cli_agents, "available", return_value=True):
            s = self.secim(("ollama", "serbest:4b"))
        self.assertEqual(s.anahtar, ("ollama", "serbest:4b"))
        self.assertIn("sansürsüz", s.neden)


class YoneticiDongusuyle(unittest.TestCase):
    """Manager: yönetici hata verirse sıradaki aday ("Yönetici: X → Y"); sohbet sağlayıcısı yoksa dürüst mesaj."""

    class _Olaylar:
        def __init__(self):
            self.notlar, self.text = [], ""

        def on_route(self, t): self.notlar.append(t)
        def on_text(self, d): self.text += d

    def _yonetici(self):
        from asistan import manager

        ajan = mock.Mock(settings=Settings(), connections=[], cb=self._Olaylar())
        ajan._model.return_value = "kucuk:4b"
        m = manager.Manager(ajan)
        m.chat = ("ollama", "kucuk:4b")
        m.boss = ("api:oa", "bulut-model")
        m.boss_chain = y.Zincir([m.boss, ("ollama", "buyuk:12b"), m.chat], esik=1)
        return manager, m

    def test_yonetici_401_verirse_siradaki(self):
        manager, m = self._yonetici()

        def ask(settings, conns, provider, model, *a, **k):
            if provider == "api:oa":
                raise RuntimeError("OpenAI hatası (401): invalid key")
            return '{"done": true, "missing": ""}'

        with mock.patch.object(manager.specialists, "ask", side_effect=ask), \
                mock.patch.object(y, "SAGLIK", y.SaglikOnbellegi(sorgu=lambda ad, _=None: Saglik(True))):
            self.assertEqual(m._ask_json("ollama", "s", "p", {}), {"done": True, "missing": ""})
            self.assertEqual(y.SAGLIK.bilinen_sagliksiz("api:oa").iyi, False)  # 401 önbelleğe yazıldı
        self.assertEqual(m.boss, ("ollama", "buyuk:12b"))
        self.assertTrue(any("Yönetici: bulut-model → buyuk:12b" in n for n in m.agent.cb.notlar))

    def test_cevrimdisi_durust_mesaj(self):
        manager, m = self._yonetici()
        messages = []
        m._run_elsewhere(y.Secim(None, None, "çevrimdışı: ollama çalışmıyor", "hizli", bekleyen=True), messages,
                         "merhaba")
        self.assertEqual(messages[0], {"role": "user", "content": "merhaba"})
        self.assertIn("cevap verecek model yok", messages[1]["content"])
        self.assertIn("Ollama çalışınca", m.agent.cb.text)

    def test_ollama_kapaliysa_sohbet_buluta(self):
        bulut = y.Secim("claude", "guclu-bulut", "rol hızlı", "hizli")
        with mock.patch.object(y, "SAGLIK", y.SaglikOnbellegi(sorgu=lambda ad, _=None: Saglik(ad != "ollama", "kapalı"))), \
                mock.patch.object(y, "sec", return_value=bulut):
            s = y.sohbet_secimi(Settings(), "ollama", "kucuk:4b", True)
        self.assertEqual(s.anahtar, ("claude", "guclu-bulut"))
        self.assertIn("ollama çalışmıyor", s.neden)
        yok = y.Secim(None, None, "çevrimdışı ve çalışan yerel model yok", "hizli", bekleyen=True)
        with mock.patch.object(y, "SAGLIK", y.SaglikOnbellegi(sorgu=lambda ad, _=None: Saglik(False, "kapalı"))), \
                mock.patch.object(y, "sec", return_value=yok):
            s = y.sohbet_secimi(Settings(), "ollama", "kucuk:4b", True)
        self.assertIsNone(s.saglayici)
        self.assertIn("çevrimdışı", s.neden)


if __name__ == "__main__":
    unittest.main()
