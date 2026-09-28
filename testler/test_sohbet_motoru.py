"""K4 — görev motorunun masaüstü sohbetine bağlanması (`asistan/cekirdek/gorev/sohbet.py`): plan kartı ve adım
durumları sohbetin geri çağrılarıyla, `_plan` + `_gorev_id` mesajda, onay sohbetin onay penceresiyle, "devam et" yarım
görevi kaldığı yerden sürdürür; bayrak kapalıyken Manager yolu aynen. Yetenekler ve model sahte; ağa gidilmez.

Çalıştırma (proje kökünde, programın Python'uyla):
    ~/.local/share/yeni-nesil-cafer-app/python/bin/python3 -m unittest discover -s testler -v
"""

import json
import os
import sys
import tempfile
import unittest
from dataclasses import asdict
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

KOK = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(KOK))
_GECICI = tempfile.mkdtemp(prefix="yeni-nesil-cafer-test-")
os.environ["XDG_CONFIG_HOME"] = str(Path(_GECICI) / "ayar")
os.environ["XDG_DATA_HOME"] = str(Path(_GECICI) / "veri")

sys.path.insert(0, str(KOK / "testler"))
from test_gorev_motoru import ANLAYIS, TAMAM, UC_ADIM, SahteModel, SahteYetenekler  # noqa: E402

from asistan.cekirdek import istek  # noqa: E402
from asistan.cekirdek.gorev import durum, sohbet, yurutucu  # noqa: E402
from asistan.cekirdek.saglayici import Iptal  # noqa: E402
from asistan.storage import Conversation  # noqa: E402

YAZAN = {"adimlar": [
    {"amac": "dosyaları listele", "yetenek": "dosya_listele", "girdi": {"klasor": "."},
     "basari_olcutu": "liste boş değil", "bagimli": [], "deneme_hakki": 0},
    {"amac": "listeyi yaz", "yetenek": "dosya_yaz", "girdi": {"yol": "liste.md", "icerik": "{{adim_1.sonuc}}"},
     "basari_olcutu": "", "bagimli": [1], "deneme_hakki": 0},
]}


class Kayitci:
    """Sohbetin geri çağrısı (AgentWorker yerine): olayları toplar, onaya hazır cevap verir."""

    def __init__(self, onay=True, onaydan_sonra_iptal=False):
        self.olaylar: list[tuple] = []
        self.onay, self.onaydan_sonra_iptal, self._iptal = onay, onaydan_sonra_iptal, False

    def on_plan(self, adimlar):
        self.olaylar.append(("plan", None if adimlar is None else [dict(a) for a in adimlar]))

    def on_step(self, i, durum_, not_):
        self.olaylar.append(("adim", i, durum_))

    def on_text(self, metin):
        self.olaylar.append(("metin", metin))

    def on_route(self, metin):
        self.olaylar.append(("not", metin))

    def ask_approval(self, ad, girdi):
        self.olaylar.append(("onay", ad, dict(girdi)))
        self._iptal = self.onaydan_sonra_iptal
        return self.onay

    def is_cancelled(self):
        return self._iptal

    def tur(self, t):
        return [o for o in self.olaylar if o[0] == t]


def sahte_ajan(cb, klasor, gate=False, must_act=False):
    return SimpleNamespace(cb=cb, settings=SimpleNamespace(extra={}, workspace=klasor), connections=[],
                           toolbox=SimpleNamespace(root=klasor), gate_actions=gate, must_act=must_act,
                           always_allowed=False, auto_approve=None, profile=None, user_text="",
                           gorev_baglami={"sohbet_id": "sohbet1", "ana_klasor": klasor})


class SohbetTabani(unittest.TestCase):
    def setUp(self):
        self.klasor = tempfile.mkdtemp(dir=_GECICI)
        self.depo = durum.Depo(Path(self.klasor) / "gorevler.db")

    def kurucu(self, yet, model):
        """`komut.motor_kur` yerine: sahte yetenek ve modelle yürütücü (sohbetin verdiği olay/iptal/sohbet_id ile)."""
        def kur(ayarlar, baglantilar, istek="", gorev_id="", olay=None, iptal=None, sohbet_id="", **_):
            return yurutucu.Yurutucu(self.depo, yet, model, klasor=self.klasor, olay=olay, iptal=iptal,
                                     sohbet_id=sohbet_id)
        return kur


class SohbetteGorevTesti(SohbetTabani):
    def test_plan_karti_adimlar_ve_mesaj(self):
        cb = Kayitci()
        m = SahteModel(analiz=[ANLAYIS], planlama=[UC_ADIM], ozet=["Kısa özet."], siniflandirma=[TAMAM, TAMAM])
        mesajlar: list = []
        g = sohbet.calistir(sahte_ajan(cb, self.klasor), mesajlar, "txt'leri say, en büyüğünü özetle", "sohbet1",
                            motor_kur=self.kurucu(SahteYetenekler(), m))
        self.assertEqual(g["durum"], "tamamlandi")
        planlar = cb.tur("plan")
        self.assertIsNone(planlar[0][1])  # önce "plan çıkarılıyor…"
        self.assertEqual([a["title"] for a in planlar[1][1]],
                         ["txt dosyalarını listele", "en büyüğünü oku", "özetle"])
        self.assertIn((("adim", 0, "running")), cb.olaylar)
        self.assertIn((("adim", 2, "done")), cb.olaylar)
        self.assertIn("Kısa özet.", cb.tur("metin")[-1][1])
        # mesajda plan kartı (son durumlarıyla) ve görev kimliği; sohbet kaydı bu alanlarla açılır
        kullanici, cevap = mesajlar
        self.assertEqual(kullanici["_gorev_id"], g["gorev_id"])
        self.assertEqual([a["status"] for a in kullanici["_plan"]], ["done", "done", "done"])
        self.assertEqual(cevap["role"], "assistant")
        self.assertIn("Kısa özet.", cevap["content"])
        kayit = json.loads(json.dumps(asdict(Conversation(provider="ollama", messages=mesajlar)), ensure_ascii=False))
        self.assertEqual(Conversation(**kayit).messages[0]["_gorev_id"], g["gorev_id"])
        # görev sohbete bağlı ve iş klasörü kayıtlı
        self.assertEqual([x["gorev_id"] for x in self.depo.sohbetin("sohbet1")], [g["gorev_id"]])
        self.assertEqual(self.depo.getir(g["gorev_id"])[durum.KLASOR_ALANI], self.klasor)

    def test_kapatip_devam_et(self):
        cb = Kayitci()
        m = SahteModel(analiz=[ANLAYIS], planlama=[UC_ADIM], siniflandirma=[TAMAM])
        mesajlar: list = []
        with self.assertRaises(Iptal):  # 2. adımda program "kapandı"
            sohbet.calistir(sahte_ajan(cb, self.klasor), mesajlar, "say ve özetle", "sohbet1",
                            motor_kur=self.kurucu(SahteYetenekler(iptal_sonra=1), m))
        self.assertIn("yarım kaldı", mesajlar[-1]["content"])
        # program yeniden açıldı: yeni depo nesnesi, aynı sohbette "devam et"
        self.depo = durum.Depo(self.depo.yol)
        yarim = sohbet.yarim_gorev("sohbet1", mesajlar, "devam et", self.depo)
        self.assertIsNotNone(yarim)
        self.assertIsNone(sohbet.yarim_gorev("sohbet1", mesajlar, "hava nasıl?", self.depo))  # başka iş: normal yol
        yet2, cb2 = SahteYetenekler(), Kayitci()
        m2 = SahteModel(ozet=["özet"], siniflandirma=[TAMAM, TAMAM])
        g = sohbet.calistir(sahte_ajan(cb2, self.klasor), mesajlar, "devam et", "sohbet1", yarim,
                            motor_kur=self.kurucu(yet2, m2))
        self.assertEqual(g["durum"], "tamamlandi")
        self.assertEqual([c[0] for c in yet2.cagrilar], ["dosya_oku"])  # 1. adım yeniden koşmadı
        self.assertEqual(cb2.tur("plan")[0][1][0]["status"], "done")  # kart kaldığı yerden çizildi
        self.assertTrue(any("Yarım görev sürüyor" in o[1] for o in cb2.tur("not")))
        self.assertEqual(mesajlar[-2]["_gorev_id"], g["gorev_id"])

    def yarim_birak(self, sohbet_id="sohbet1"):
        m = SahteModel(analiz=[ANLAYIS], planlama=[UC_ADIM], siniflandirma=[TAMAM])
        with self.assertRaises(Iptal):
            sohbet.calistir(sahte_ajan(Kayitci(), self.klasor), [], "say", sohbet_id,
                            motor_kur=self.kurucu(SahteYetenekler(iptal_sonra=1), m))

    def test_icinde_devam_gecen_yeni_istek_gorevi_surdurmez(self):
        # denetçi (K4): "devam" kelimesi geçen yeni istek eski görevi sürdürüp kullanıcının isteğini yutmamalı
        self.yarim_birak()
        for metin in ("hikâyenin devamını yaz", "sürdürülebilirlik raporu hazırla", "kaldığı yer neresiydi?",
                      "▶ devam eden işleri listele"):
            self.assertIsNone(sohbet.yarim_gorev("sohbet1", [{"role": "user"}], metin, self.depo), metin)
        for metin in ("devam et", "Göreve devam et.", "kaldığın yerden devam", "sürdür lütfen"):
            self.assertIsNotNone(sohbet.yarim_gorev("sohbet1", [{"role": "user"}], metin, self.depo), metin)

    def test_vazgec_gorevi_birakir(self):
        self.yarim_birak()
        mesajlar = [{"role": "user", "content": "say"}]
        yarim = sohbet.yarim_gorev("sohbet1", mesajlar, "vazgeç", self.depo)
        self.assertIsNotNone(yarim)
        cb = Kayitci()
        g = sohbet.calistir(sahte_ajan(cb, self.klasor), mesajlar, "vazgeç", "sohbet1", yarim, depo=self.depo)
        self.assertEqual(g["durum"], "iptal")
        self.assertEqual(self.depo.sohbetin("sohbet1")[0]["durum"], "iptal")  # kayıt kalır, yarım değil
        self.assertIn("bırakıldı", mesajlar[-1]["content"])
        self.assertIsNone(sohbet.yarim_gorev("sohbet1", mesajlar, "devam et", self.depo))

    def test_olumsuz_cumle_gorevi_birakmaz(self):
        # denetçi (K4): "vazgeçme", "iptal etme" görevi bırakmanın tersi; eşleşirse görev geri alınamaz biçimde biterdi
        self.yarim_birak()
        for metin in ("iptal etme", "vazgeçme", "vazgeçmedim", "bırakma", "görevi iptal etme!", "iptaller"):
            self.assertIsNone(sohbet._VAZGEC.match(metin), metin)
            self.assertIsNone(sohbet.yarim_gorev("sohbet1", [{"role": "user"}], metin, self.depo), metin)
        for metin in ("iptal", "iptal et", "Görevi iptal et.", "vazgeç", "vazgeçtim", "bırak", "işi bırak lütfen"):
            self.assertIsNotNone(sohbet._VAZGEC.match(metin), metin)
        self.assertIn(self.depo.sohbetin("sohbet1")[0]["durum"], durum.YARIM)  # hâlâ yarım

    def test_yeni_sohbette_devam_soru_bekleyeni_almaz(self):
        m = SahteModel(analiz=[dict(ANLAYIS, belirsizlik="yuksek", soru="Hangi klasör?")])
        sohbet.calistir(sahte_ajan(Kayitci(), self.klasor), [], "dosyaları özetle", "soran",
                        motor_kur=self.kurucu(SahteYetenekler(), m))
        self.assertIsNone(sohbet.yarim_gorev("yeni", [], "devam et", self.depo))

    def test_yeni_sohbette_yalniz_devam_et(self):
        m = SahteModel(analiz=[ANLAYIS], planlama=[UC_ADIM], siniflandirma=[TAMAM])
        with self.assertRaises(Iptal):
            sohbet.calistir(sahte_ajan(Kayitci(), self.klasor), [], "say", "eski",
                            motor_kur=self.kurucu(SahteYetenekler(iptal_sonra=1), m))
        cli = {"gorev_id": "cli", "istek": "komut satırı", "durum": "calisiyor", "adimlar": []}
        self.depo.kaydet(cli)  # komut satırının görevi (sohbet_id yok) yeni sohbette seçilmez
        self.assertEqual(sohbet.yarim_gorev("yeni", [], "devam et", self.depo)["istek"], "say")
        self.assertEqual(sohbet.yarim_gorev("yeni", [], "Kaldığın yerden devam et.", self.depo)["istek"], "say")
        self.assertIsNone(sohbet.yarim_gorev("yeni", [], "3D projeme devam et, kapağı ekle", self.depo))
        self.assertIsNone(sohbet.yarim_gorev("", [], "devam et", self.depo))  # bulut/komut: sohbet yok

    def test_onay_sohbet_penceresinden(self):
        cb = Kayitci(onay=True)
        yet = SahteYetenekler()
        m = SahteModel(analiz=[ANLAYIS], planlama=[YAZAN], siniflandirma=[TAMAM])
        g = sohbet.calistir(sahte_ajan(cb, self.klasor), [], "listele ve yaz", "sohbet1",
                            motor_kur=self.kurucu(yet, m))
        self.assertEqual(g["durum"], "tamamlandi")
        onay = cb.tur("onay")
        self.assertEqual(len(onay), 1)
        self.assertEqual(onay[0][1], "dosya_yaz")
        self.assertIn("a.txt", onay[0][2]["icerik"])  # yer tutucu çözülmüş hâli sorulur
        self.assertIn(("dosya_yaz", {"yol": "liste.md", "icerik": "a.txt 10 B\nbuyuk.txt 900 B"}, True),
                      yet.cagrilar)

    def test_onay_reddedilirse_durur(self):
        cb = Kayitci(onay=False)
        yet = SahteYetenekler()
        m = SahteModel(analiz=[ANLAYIS], planlama=[YAZAN], siniflandirma=[TAMAM])
        mesajlar: list = []
        g = sohbet.calistir(sahte_ajan(cb, self.klasor), mesajlar, "listele ve yaz", "sohbet1",
                            motor_kur=self.kurucu(yet, m))
        self.assertEqual(g["durum"], "iptal")
        self.assertNotIn("dosya_yaz", [c[0] for c in yet.cagrilar])
        self.assertIn("onaylanmadı", mesajlar[-1]["content"])
        self.assertEqual(mesajlar[0]["_plan"][1]["status"], "skipped")

    def test_durdur_onay_bekleyen_gorevi_iptal_etmez(self):
        # ■ onay penceresini "hayır"la kapatır: görev iptal olmamalı, onay bekler (sonra "devam et")
        cb = Kayitci(onay=False, onaydan_sonra_iptal=True)
        m = SahteModel(analiz=[ANLAYIS], planlama=[YAZAN], siniflandirma=[TAMAM])
        with self.assertRaises(Iptal):
            sohbet.calistir(sahte_ajan(cb, self.klasor), [], "listele ve yaz", "sohbet1",
                            motor_kur=self.kurucu(SahteYetenekler(), m))
        self.assertEqual([g["durum"] for g in self.depo.sohbetin("sohbet1")], ["bekliyor_onay"])

    def test_motorun_sorusu_ve_cevap(self):
        cb = Kayitci()
        m = SahteModel(analiz=[dict(ANLAYIS, belirsizlik="yuksek", soru="Hangi klasör?")], planlama=[UC_ADIM],
                       ozet=["özet"], siniflandirma=[TAMAM, TAMAM])
        mesajlar: list = []
        kur = self.kurucu(SahteYetenekler(), m)
        g = sohbet.calistir(sahte_ajan(cb, self.klasor), mesajlar, "dosyaları özetle", "sohbet1", motor_kur=kur)
        self.assertEqual(g["durum"], "bekliyor_kullanici")
        self.assertEqual(mesajlar[-1]["content"], "Hangi klasör?")
        self.assertEqual(cb.tur("plan")[-1][1], [])  # plan yok: kart gizlenir
        yarim = sohbet.yarim_gorev("sohbet1", mesajlar, "Belgeler", self.depo)  # her cevap soruya gider
        g = sohbet.calistir(sahte_ajan(Kayitci(), self.klasor), mesajlar, "Belgeler", "sohbet1", yarim,
                            motor_kur=kur)
        self.assertEqual(g["durum"], "tamamlandi")
        self.assertIn("Belgeler", g["istek"])

    def test_bekletme_turunda_degisiklik_sorulur(self):
        # ✓ bekletme turunda (▶ basılmadı) "devam et": motor her değişikliği tek tek sorar (▶ turu gibi)
        tur = sohbet.SohbetGorevi(sahte_ajan(Kayitci(), self.klasor, gate=True), "sohbet1")
        self.assertTrue(tur.izin.must_act)
        self.assertTrue(tur.izin.confirm_commands)
        tur = sohbet.SohbetGorevi(sahte_ajan(Kayitci(), self.klasor), "sohbet1")  # güvenlik ajanı kipi
        self.assertFalse(tur.izin.must_act)
        self.assertFalse(tur.izin.confirm_commands)

    def test_basarisiz_gorev_durustce_yapilamadi(self):
        g = {"durum": "basarisiz", "rapor": "0/2 adım yapıldı\n✗ 1. oku — dosya yok", "adimlar": []}
        self.assertTrue(sohbet.sonuc_metni(g).startswith("**Yapılamadı.**"))


class AjanUyarlayiciSohbetTesti(unittest.TestCase):
    """Gerçek Agent + izin hattı: sohbetin izin bağlamı ve araç olayları motor ajanına geçer."""

    def setUp(self):
        from asistan.cekirdek.gorev.ajan import AjanYetenekleri
        from asistan.config import Settings

        self.klasor = tempfile.mkdtemp(dir=_GECICI)
        Path(self.klasor, "not.txt").write_text("merhaba", encoding="utf-8")
        self.ayarlar = Settings.load()
        self.ayarlar.workspace = self.klasor
        self.ayarlar.approval_mode = "kullanici"
        self.ayarlar.confirm_commands = True
        self.Yet = AjanYetenekleri

    def test_uygula_turunda_yazma_sorulur(self):
        girdi = {"path": "yeni.txt", "content": "x"}
        serbest = self.Yet(self.ayarlar, [], self.klasor)
        uygula = self.Yet(self.ayarlar, [], self.klasor,
                          izin_kaynagi=SimpleNamespace(must_act=True, always_allowed=False, auto_approve=None))
        self.assertFalse(serbest.onay_gerekir("write_file", girdi))  # izin bağlamı verilmezse (komut satırı) eskisi gibi
        self.assertTrue(uygula.onay_gerekir("write_file", girdi))
        hep = self.Yet(self.ayarlar, [], self.klasor,
                       izin_kaynagi=SimpleNamespace(must_act=True, always_allowed=True, auto_approve=None))
        self.assertFalse(hep.onay_gerekir("write_file", girdi))  # "bu oturumda hep izin ver"

    def test_bekletme_turunda_komut_onayi_kapali_olsa_da_sorulur(self):
        self.ayarlar.confirm_commands = False  # kullanıcı "komutları onayla"yı kapatmış
        kod = {"code": "print(1)", "purpose": "test"}
        uygula = self.Yet(self.ayarlar, [], self.klasor,
                          izin_kaynagi=SimpleNamespace(must_act=True, always_allowed=False, auto_approve=None))
        self.assertFalse(uygula.onay_gerekir("run_python", kod))  # ▶ turu: kullanıcının ayarı geçerli
        bekletme = self.Yet(self.ayarlar, [], self.klasor,
                            izin_kaynagi=SimpleNamespace(must_act=True, confirm_commands=True, always_allowed=False,
                                                         auto_approve=None))
        self.assertTrue(bekletme.onay_gerekir("run_python", kod))

    def test_arac_olaylari_sohbete_gider(self):
        cb = mock.Mock()
        yet = self.Yet(self.ayarlar, [], self.klasor, ust_cb=cb)
        c = yet.calistir("read_file", {"path": "not.txt"})
        self.assertIn("merhaba", c.metin)
        cb.on_tool_start.assert_called_once()
        self.assertEqual(cb.on_tool_start.call_args[0][1], "read_file")
        cb.on_tool_end.assert_called_once()


class BulutTavaniTesti(unittest.TestCase):
    """Denetçi (K4): motorun model çağrısı bulut tavanı aşılınca ücretli modeli kullanıcıya sorar (Manager gibi);
    "hayır" ya da soracak pencere yoksa yerel modelle sürer. Sessiz harcama yok."""

    BULUT = ("api:x", "buyuk-bulut")
    YEREL = ("ollama", "yerel-model")

    def setUp(self):
        from asistan.cekirdek import yonlendirici
        from asistan.cekirdek.gorev import model as model_mod

        self.y, self.model_mod = yonlendirici, model_mod
        yonlendirici.gorev_basla()
        self.cagrilanlar: list = []
        karar = yonlendirici.Secim(*self.BULUT, "güçlü bulut", "yonetici")
        yerel = yonlendirici.Secim(*self.YEREL, "yerel", "yonetici")

        def bul(ad, *_):
            return SimpleNamespace(sohbet=lambda m, s, model: (self.cagrilanlar.append((ad, model)),
                                                               SimpleNamespace(metin="tamam"))[1])

        self.yamalar = [mock.patch.object(yonlendirici, "sec", return_value=karar),
                        mock.patch.object(yonlendirici, "yerel_sec", return_value=yerel),
                        mock.patch.object(yonlendirici, "harcama_ekle"),
                        mock.patch("asistan.cekirdek.saglayici.bul", side_effect=bul)]
        for y in self.yamalar:
            y.start()
        self.addCleanup(lambda: [y.stop() for y in self.yamalar])

    def tavan(self, asim):
        return mock.patch.object(self.y, "tavan_durumu", return_value=asim)

    def test_tavan_asilmadiysa_sorulmaz(self):
        sor = mock.Mock()
        with self.tavan(""):
            c = self.model_mod.YonlendiriciModeli(SimpleNamespace(), [], sor)("planlama", [])
        sor.assert_not_called()
        self.assertEqual(self.cagrilanlar, [self.BULUT])
        self.assertEqual(c.secim["model"], "buyuk-bulut")

    def test_tavan_asildi_hayir_yerel_modelle_surer(self):
        from asistan import permissions

        sor = mock.Mock(return_value=False)
        m = self.model_mod.YonlendiriciModeli(SimpleNamespace(), [], sor)
        with self.tavan("bu iş 50.000 token harcadı"), self.assertLogs("asistan.cekirdek.gorev.model", "WARNING"):
            c = m("planlama", [])
            m("analiz", [])  # aynı görevde ikinci kez sorulmaz
        self.assertEqual(sor.call_count, 1)
        self.assertEqual(sor.call_args[0][0], permissions.BULUT_TAVANI)
        self.assertIn("50.000", sor.call_args[0][1]["purpose"])
        self.assertEqual(self.cagrilanlar, [self.YEREL, self.YEREL])
        self.assertIn("bulut tavanı", c.secim["neden"])

    def test_tavan_asildi_evet_bulut_ve_bir_kez_sorulur(self):
        sor = mock.Mock(return_value=True)
        m = self.model_mod.YonlendiriciModeli(SimpleNamespace(), [], sor)
        with self.tavan("bugünkü bulut kullanımı çok"):
            m("planlama", [])
            m("planlama", [])
        self.assertEqual(sor.call_count, 1)  # onay bu istek boyunca geçerli (`tavan_onayla`)
        self.assertEqual(self.cagrilanlar, [self.BULUT, self.BULUT])
        self.assertTrue(self.y.tavan_onaylandi())

    def test_soracak_pencere_yoksa_yerel(self):
        with self.tavan("aşıldı"), self.assertLogs("asistan.cekirdek.gorev.model", "WARNING"):
            self.model_mod.YonlendiriciModeli(SimpleNamespace(), [])("planlama", [])
        self.assertEqual(self.cagrilanlar, [self.YEREL])

    def test_motor_kur_sohbetin_onay_penceresini_verir(self):
        from asistan.cekirdek.gorev import komut
        from asistan.config import Settings

        cb = Kayitci()
        with mock.patch("asistan.cekirdek.gorev.yurutucu.Yurutucu") as Y, \
                mock.patch("asistan.cekirdek.gorev.ajan.AjanYetenekleri"), \
                mock.patch.object(durum, "depo", return_value=mock.Mock(getir=lambda _: None)):
            komut.motor_kur(Settings.load(), [], istek="x", gorev_id="g1",
                            klasor=_GECICI, ust_cb=cb)
        self.assertEqual(Y.call_args[0][2].sor, cb.ask_approval)


class IstekYoluTesti(unittest.TestCase):
    """`istek.calistir`: bayrak kapalıyken Manager yolu aynen; açıkken plan işi motora; yarım görev "devam et"le."""

    def ajan(self, bayrak=False, sohbet_id="sohbet1", profil=None):
        return SimpleNamespace(cb=None, settings=SimpleNamespace(extra={"gorev_motoru": bayrak}), profile=profil,
                               gorev_baglami={"sohbet_id": sohbet_id, "ana_klasor": ""})

    def calistir(self, ajan, yarim=None):
        motorlar = []
        with mock.patch("asistan.manager.Manager.run", lambda self, *a: motorlar.append(self.motor)), \
                mock.patch.object(sohbet, "yarim_gorev", return_value=yarim), \
                mock.patch.object(sohbet, "calistir") as motor_calisti:
            istek.calistir(ajan, "ollama", [], "a.txt'yi oku, sonra özetle")
        return motorlar, motor_calisti

    def test_bayrak_kapali_manager_aynen(self):
        motorlar, calisti = self.calistir(self.ajan(False))
        self.assertEqual(motorlar, [None])
        calisti.assert_not_called()

    def test_bayrak_acik_motor_verilir(self):
        motorlar, _ = self.calistir(self.ajan(True))
        self.assertIsNotNone(motorlar[0])

    def test_sohbet_yoksa_motor_yok(self):  # bulut sunucu, yardımcı ajan sohbeti
        self.assertEqual(self.calistir(self.ajan(True, sohbet_id=""))[0], [None])
        self.assertEqual(self.calistir(self.ajan(True, profil=object()))[0], [None])

    def test_gorev_veritabani_bozuksa_manager_yolu(self):
        # gorevler.db okunamazsa (bozuk/kilitli) sohbet hata vermez: bayrak kapalıyken eski yol aynen
        motorlar = []
        with mock.patch("asistan.manager.Manager.run", lambda self, *a: motorlar.append(self.motor)), \
                mock.patch.object(sohbet, "yarim_gorev", side_effect=durum.sqlite3.OperationalError("locked")), \
                self.assertLogs("asistan.cekirdek.istek", "WARNING"):
            istek.calistir(self.ajan(False), "ollama", [], "a.txt'yi oku, sonra özetle")
        self.assertEqual(motorlar, [None])

    def test_yarim_gorev_manager_a_gitmez(self):
        motorlar, calisti = self.calistir(self.ajan(False), yarim={"gorev_id": "g1", "durum": "calisiyor"})
        self.assertEqual(motorlar, [])
        calisti.assert_called_once()

    def test_manager_plan_yerine_motoru_cagirir(self):
        from asistan.manager import Manager

        cagri = []
        a = SimpleNamespace(cb=None, profile=None, settings=SimpleNamespace(extra={}))
        y = Manager(a)
        y.motor = lambda m, t: cagri.append(t)
        with mock.patch.object(Manager, "_route_chat", return_value=None), \
                mock.patch.object(Manager, "_pick_models"), mock.patch.object(Manager, "_announce"), \
                mock.patch.object(Manager, "should_plan", return_value=True), \
                mock.patch.object(Manager, "make_plan", side_effect=AssertionError("eski plan yolu")):
            y.run("ollama", [], "iki adımlı iş")
        self.assertEqual(cagri, ["iki adımlı iş"])

    def test_gorev_mu(self):
        self.assertTrue(sohbet.gorev_mu("Çalışma klasöründeki .txt dosyalarını say, en büyüğünü özetle"))
        self.assertTrue(sohbet.gorev_mu("rapor.md yaz, sonra tabloyu csv olarak kaydet"))  # Manager'ın kararı
        self.assertFalse(sohbet.gorev_mu("a.txt dosyasını oku"))  # tek adım
        self.assertFalse(sohbet.gorev_mu("Python'da listeyi nasıl sıralar ve filtrelerim?"))  # soru
        self.assertFalse(sohbet.gorev_mu("↻ dosyaları say, en büyüğünü özetle"))  # yeniden deneme işareti

    def test_bekletme_turunda_plan_karari(self):
        # ✓ bekletme turu: bayrak kapalıyken plan yok (eskisi gibi); motor varken plan (adım adım onayla)
        from asistan.manager import Manager

        a = SimpleNamespace(cb=None, profile=None, gate_actions=True, no_tools=False, tool_specs=[{"name": "x"}],
                            settings=SimpleNamespace(extra={}))
        metin = "Çalışma klasöründeki .txt dosyalarını say, en büyüğünü özetle"
        y = Manager(a)
        y.worker = ("ollama", "isci")
        self.assertFalse(y.should_plan("ollama", metin))
        y.motor, y.motor_karari = mock.Mock(), sohbet.gorev_mu
        self.assertTrue(y.should_plan("ollama", metin))
        self.assertFalse(y.should_plan("cli:claude", metin))  # CLI ajanı kendi planını yapar

    def test_plan_karari_yoksa_motor_devreye_girmez(self):
        # should_plan False (tek adımlı iş): bayrak açık olsa da Manager'ın plansız yolu
        from asistan.manager import Manager

        a = SimpleNamespace(cb=None, profile=None, settings=SimpleNamespace(extra={}))
        y = Manager(a)
        y.motor = mock.Mock()
        with mock.patch.object(Manager, "_route_chat", return_value=None), \
                mock.patch.object(Manager, "_pick_models"), mock.patch.object(Manager, "_announce"), \
                mock.patch.object(Manager, "should_plan", return_value=False), \
                mock.patch.object(Manager, "_direct") as direct:
            y.run("ollama", [], "iki adımlı iş")
        y.motor.assert_not_called()
        direct.assert_called_once()


if __name__ == "__main__":
    unittest.main()
