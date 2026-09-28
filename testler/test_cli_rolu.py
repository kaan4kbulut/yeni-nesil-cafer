"""CLI ajanı görev motorunda (BÖLÜM 2.5): yalnızca `kod` rolünde seçilir (planlayıcı/analist/denetçi olamaz); çağrı
görevin iş klasöründe ve salt okunur (`klasor`, `duzenleyebilir=False`); adayın puanı sabit değil, kartından."""

import os
import sys
import tempfile
import unittest
from types import SimpleNamespace
from unittest import mock

KOK = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, KOK)
_GECICI = tempfile.mkdtemp(prefix="yeni-nesil-cafer-test-")
os.environ["XDG_CONFIG_HOME"] = os.path.join(_GECICI, "ayar")
os.environ["XDG_DATA_HOME"] = os.path.join(_GECICI, "veri")

from asistan import cards, cli_agents  # noqa: E402
from asistan.cekirdek import yonlendirici as y  # noqa: E402
from asistan.cekirdek.gorev import model as model_mod  # noqa: E402

YEREL = y.Aday("ollama", "yerel:12b", True, 20, 2, True, False, 7.0, {"tools"})
CLI = y.Aday("cli:claude", "claude-code", False, 95, 2, True, False, 0.0, {"tools", "code", "thinking"})


class MotordaYalnizcaKod(unittest.TestCase):
    def setUp(self):
        self.d = y.Durum(cevrimici=True, gizlilik="karma", kademe="yuksek", politika="otomatik", kullanici_istegi=True,
                         vram_gb=12)
        p = mock.patch.object(y, "adaylar", return_value=[YEREL, CLI])
        p.start()
        self.addCleanup(p.stop)

    def test_sohbette_bile_planlayici_cli_olmaz(self):
        for rol in ("planlama", "analiz", "siniflandirma", "ozet"):
            s = y.sec(SimpleNamespace(extra={}), rol, durum_=self.d, cli_yalnizca_kod=True)
            self.assertEqual(s.saglayici, "ollama", rol)
            self.assertNotIn(CLI.anahtar, s.zincir)
        self.assertEqual(y.sec(SimpleNamespace(extra={}), "kod", durum_=self.d, cli_yalnizca_kod=True).saglayici,
                         "cli:claude")

    def test_manager_yolu_degismedi(self):
        self.assertEqual(y.sec(SimpleNamespace(extra={}), "planlama", durum_=self.d).saglayici, "cli:claude")


class CliCagrisiKlasorde(unittest.TestCase):
    def setUp(self):
        y.gorev_basla()
        self.cagrilar = []

        def bul(ad, *_):
            def sohbet(m, s, model="", **secenek):
                self.cagrilar.append((ad, secenek))
                return SimpleNamespace(metin="tamam", son={})

            return SimpleNamespace(sohbet=sohbet, ad=ad, kullanim=lambda _y: (0, 0))

        for p in (mock.patch("asistan.cekirdek.saglayici.bul", side_effect=bul),
                  mock.patch.object(y, "harcama_ekle")):
            p.start()
            self.addCleanup(p.stop)

    def test_cli_klasor_ve_salt_okunur(self):
        karar = y.Secim("cli:claude", "claude-code", "kod", "kod")
        with mock.patch.object(y, "sec", return_value=karar):
            m = model_mod.YonlendiriciModeli(SimpleNamespace(extra={}), [], klasor="/tmp/is-klasoru")
            m("kod", [{"role": "user", "content": "x"}])
            m("kod", [{"role": "user", "content": "x"}], sema={"type": "object"})  # şema yolu da
        for ad, secenek in self.cagrilar:
            self.assertEqual(ad, "cli:claude")
            self.assertEqual(secenek.get("klasor"), "/tmp/is-klasoru")
            self.assertIs(secenek.get("duzenleyebilir"), False)
        self.assertEqual(len(self.cagrilar), 3)  # düz çağrı + şema yolu (cevap JSON değil: bir düzeltme turu)

    def test_yerel_modele_klasor_gonderilmez(self):
        karar = y.Secim("ollama", "yerel:12b", "hızlı", "hizli")
        with mock.patch.object(y, "sec", return_value=karar):
            model_mod.YonlendiriciModeli(SimpleNamespace(extra={}), [], klasor="/tmp/x")("ozet", [{"role": "user", "content": "x"}])
        self.assertNotIn("klasor", self.cagrilar[0][1])

    def test_motor_kur_klasoru_verir(self):
        from asistan.cekirdek import ayar
        from asistan.cekirdek.gorev import komut

        klasor = os.path.join(_GECICI, "is")
        with mock.patch("asistan.cekirdek.gorev.ajan.AjanYetenekleri") as ay, \
                mock.patch("asistan.cekirdek.gorev.yurutucu.Yurutucu"), \
                mock.patch("asistan.cekirdek.gorev.model.YonlendiriciModeli") as ym:
            ay.return_value.klasor = klasor
            komut.motor_kur(ayar.Settings(workspace=_GECICI), [], istek="x", klasor=klasor)
        self.assertEqual(ym.call_args.kwargs.get("klasor"), klasor)


class CliAdayiKarttan(unittest.TestCase):
    def test_kart_yoksa_sinanmadi_kart_varsa_karttan(self):
        with mock.patch.object(cli_agents, "available", return_value=True), \
                mock.patch("asistan.roster.candidates", return_value=[]):
            with mock.patch.object(cards, "card", return_value=None):
                aday = next(a for a in y.adaylar(SimpleNamespace(extra={})) if a.cli)
                self.assertIsNone(aday.arac)  # sınanmadı: "araç 2, plan True" diye uydurulmaz
                self.assertIsNone(aday.plan)
            with mock.patch.object(cards, "card", return_value={"tools": 1, "plan": False, "score": 40}):
                aday = next(a for a in y.adaylar(SimpleNamespace(extra={})) if a.cli)
                self.assertEqual((aday.arac, aday.plan, aday.puan), (1, False, 40.0))


if __name__ == "__main__":
    unittest.main()
