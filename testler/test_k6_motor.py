"""K6 — yürütücü ↔ hata analizi: eksik bağımlılık → onaylı kurulum → adım tekrar; ağ hatası → 3 deneme; mantık →
en çok 2 yeniden planlama; izin → kullanıcıya soru; eksik yetenek → onay → üretim → yeniden planlama."""

import copy
import os
import sys
import tempfile
import unittest
from pathlib import Path

KOK = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(KOK))
sys.path.insert(0, str(KOK / "testler"))
_GECICI = tempfile.mkdtemp(prefix="yeni-nesil-cafer-test-")
os.environ["XDG_CONFIG_HOME"] = str(Path(_GECICI) / "ayar")
os.environ["XDG_DATA_HOME"] = str(Path(_GECICI) / "veri")

from asistan.cekirdek.gorev import Cikti, yurutucu  # noqa: E402
from test_gorev_motoru import ANLAYIS, TAMAM, UC_ADIM, GorevTabani, SahteModel, SahteYetenekler  # noqa: E402


class Yetenekler(SahteYetenekler):
    """+ kur / uret (K6). `bagimlilik_eksik`: dosya_oku kurulana kadar ModuleNotFoundError; `ag_hata`: N kez zaman aşımı."""

    def __init__(self, bagimlilik_eksik=False, ag_hata=0, izin_hatasi=False):
        super().__init__()
        self.bagimlilik_eksik, self.ag_hata, self.izin_hatasi = bagimlilik_eksik, ag_hata, izin_hatasi
        self.kurulumlar, self.uretimler, self.uretilenler = [], [], []

    def listele(self):
        liste = super().listele()
        return liste + [{"ad": ad, "aciklama": "üretildi", "girdi_semasi": {"type": "object", "properties": {}},
                         "salt_okur": True} for ad in self.uretilenler]

    def calistir(self, ad, girdi, onayli=False):
        if ad == "dosya_oku" and self.bagimlilik_eksik:
            self.cagrilar.append((ad, dict(girdi), onayli))
            return Cikti("Error: ModuleNotFoundError: No module named 'docx'", True)
        if ad == "dosya_oku" and self.ag_hata:
            self.ag_hata -= 1
            self.cagrilar.append((ad, dict(girdi), onayli))
            return Cikti("Error: ReadTimeout: timed out", True)
        if ad == "dosya_oku" and self.izin_hatasi:
            self.cagrilar.append((ad, dict(girdi), onayli))
            return Cikti("Error: PermissionError: [Errno 13] Permission denied", True)
        if ad in self.uretilenler:
            self.cagrilar.append((ad, dict(girdi), onayli))
            return Cikti("tablo çıkarıldı")
        return super().calistir(ad, girdi, onayli)

    def kur(self, hedef, amac="", onayli=False):
        self.kurulumlar.append((hedef, onayli))
        if not onayli:
            return Cikti("onay bekliyor", onay_bekliyor=True)
        self.bagimlilik_eksik = False
        return Cikti(f"{hedef} kuruldu")

    def uret(self, ad, aciklama, onayli=False, model=None):
        self.uretimler.append((ad, onayli, model is not None))
        if not onayli:
            return Cikti("onay gerekiyor", onay_bekliyor=True)
        self.uretilenler.append(ad)
        return Cikti(f"{ad} üretildi")


def plan(deneme=1, olcut=""):
    p = copy.deepcopy(UC_ADIM)
    for a in p["adimlar"]:
        a["deneme_hakki"] = deneme
    if olcut:
        p["adimlar"][2]["basari_olcutu"] = olcut  # özet adımı denetçi modele sorulsun
    return p


class EksikBagimlilik(GorevTabani):
    def test_kurulum_onayla_sonra_adim_tekrar(self):
        yet = Yetenekler(bagimlilik_eksik=True)
        m = SahteModel(analiz=[ANLAYIS], planlama=[plan(0)], ozet=["özet"], siniflandirma=[TAMAM] * 6)
        motor = self.motor(yet, m)
        g = motor.baslat("iş")
        self.assertEqual(g["durum"], "bekliyor_onay")
        adim = g["adimlar"][1]
        self.assertEqual(adim["bekleyen"], {"tip": "kur", "hedef": "pip:docx"})
        self.assertEqual(yet.kurulumlar, [("pip:docx", False)])
        g = motor.onayla(g["gorev_id"], True)
        self.assertEqual(g["durum"], "tamamlandi", g.get("rapor"))
        self.assertEqual(yet.kurulumlar[-1], ("pip:docx", True))
        self.assertNotIn("bekleyen", g["adimlar"][1])
        self.assertTrue(g["adimlar"][1].get("kuruldu"))

    def test_kurulum_reddedilirse_gorev_durur(self):
        yet = Yetenekler(bagimlilik_eksik=True)
        m = SahteModel(analiz=[ANLAYIS], planlama=[plan(0)], siniflandirma=[TAMAM] * 3)
        motor = self.motor(yet, m)
        g = motor.baslat("iş")
        g = motor.onayla(g["gorev_id"], False)
        self.assertEqual(g["durum"], "iptal")


class AgHatasi(GorevTabani):
    def test_uc_deneme_sonra_gecer(self):
        yet = Yetenekler(ag_hata=2)
        beklemeler = []
        m = SahteModel(analiz=[ANLAYIS], planlama=[plan(0)], ozet=["özet"], siniflandirma=[TAMAM] * 6)
        g = self.motor(yet, m, bekle=beklemeler.append).baslat("iş")
        self.assertEqual(g["durum"], "tamamlandi", g.get("rapor"))
        self.assertEqual(beklemeler, [1.0, 2.0])
        self.assertEqual(g["adimlar"][1]["ag_deneme"], 2)

    def test_dort_hata_vazgecer(self):
        yet = Yetenekler(ag_hata=9)
        m = SahteModel(analiz=[ANLAYIS], planlama=[plan(0)], siniflandirma=[TAMAM] * 6)
        g = self.motor(yet, m, bekle=lambda s: None).baslat("iş")
        self.assertEqual(g["durum"], "basarisiz")
        self.assertEqual(g["hatalar"][0]["sinif"], "ag")
        self.assertEqual(g["hatalar"][0]["eylem"]["tip"], "tekrar")
        self.assertEqual(len([c for c in yet.cagrilar if c[0] == "dosya_oku"]), 4)  # 1 + 3 deneme


class MantikYenidenPlan(GorevTabani):
    YENI = {"adimlar": [{"amac": "a.txt'yi oku", "yetenek": "dosya_oku", "girdi": {"yol": "a.txt"},
                         "basari_olcutu": "içerik okundu", "bagimli": [], "deneme_hakki": 0},
                        {"amac": "özetle", "yetenek": "metin_uret", "girdi": {"talimat": "özet: {{adim_1.sonuc}}"},
                         "basari_olcutu": "özet var", "bagimli": [1], "deneme_hakki": 0}]}

    def test_basarisiz_cikti_baglama_eklenir_yeniden_planlanir(self):
        # 1. ve 2. adım salt okur (model sorulmaz); 3. adım (metin_uret) denetçiye takılır → mantık → yeniden plan.
        # sınıflandırıcı da "siniflandirma" rolünü kullanır: TAMAM şemaya uymaz → mantik (varsayılan)
        yet = Yetenekler()
        m = SahteModel(analiz=[ANLAYIS], planlama=[plan(0, "özet 3 cümle içerir"), self.YENI], ozet=["özet", "özet 2"],
                       siniflandirma=[{"tamam": False, "eksik": "sayı yok"}, TAMAM, TAMAM, TAMAM, TAMAM])
        g = self.motor(yet, m).baslat("iş")
        self.assertEqual(g["durum"], "tamamlandi", g.get("rapor"))
        self.assertEqual(g["yeniden_plan"], 1)
        self.assertEqual([a["id"] for a in g["adimlar"]], [1, 2, 3, 4])  # biten 2 + yeni 2 adım
        self.assertEqual(g["adimlar"][3]["girdi"]["talimat"], "özet: {{adim_3.sonuc}}")  # yer tutucu kaydı
        planlama = [c for c in m.cagrilar if c[0] == "planlama"]
        self.assertEqual(len(planlama), 2)
        self.assertIn("Already done", planlama[1][1][0]["content"])
        self.assertIn("sayı yok", planlama[1][1][0]["content"])

    def test_en_cok_iki_yeniden_plan(self):
        yet = Yetenekler()
        kotu = {"tamam": False, "eksik": "olmadı"}
        o = "özet 3 cümle içerir"
        m = SahteModel(analiz=[ANLAYIS], planlama=[plan(0, o), plan(0, o), plan(0, o), plan(0, o)], ozet=["ö"] * 5,
                       siniflandirma=[kotu] * 20)
        g = self.motor(yet, m).baslat("iş")
        self.assertEqual(g["durum"], "basarisiz")
        self.assertEqual(g["yeniden_plan"], 2)
        self.assertEqual(g["hatalar"][0]["eylem"]["tip"], "yeniden_planla")


class IzinSorusu(GorevTabani):
    def test_izin_hatasi_kullaniciya_sorulur(self):
        yet = Yetenekler(izin_hatasi=True)
        m = SahteModel(analiz=[ANLAYIS], planlama=[plan(0)], siniflandirma=[TAMAM] * 3)
        g = self.motor(yet, m).baslat("iş")
        self.assertEqual(g["durum"], "bekliyor_kullanici")
        self.assertIn("izin gerektiriyor", g["rapor"])


class EksikYetenek(GorevTabani):
    ANLAYIS2 = dict(ANLAYIS, eksik_yetenekler=["pdf_tablo"], gereken_yetenekler=["pdf_tablo"])
    BOZUK = {"adimlar": [{"amac": "tablo çıkar", "yetenek": "pdf_tablo", "girdi": {}, "basari_olcutu": "x",
                          "bagimli": [], "deneme_hakki": 0}]}

    def test_onayla_uret_yeniden_planla(self):
        yet = Yetenekler()
        m = SahteModel(analiz=[self.ANLAYIS2], planlama=[self.BOZUK, self.BOZUK], ozet=["ö"], siniflandirma=[TAMAM] * 3)
        motor = self.motor(yet, m)
        g = motor.baslat("PDF tablolarını çıkar")
        self.assertEqual(g["durum"], "bekliyor_onay")
        self.assertEqual(g["bekleyen_uretim"]["ad"], "pdf_tablo")
        self.assertIn("üretip", g["rapor"])
        self.assertEqual(yet.uretimler, [])
        g = motor.onayla(g["gorev_id"], True)  # üret → yeniden planla → şimdi pdf_tablo kayıtlı, plan geçer
        self.assertEqual(yet.uretimler, [("pdf_tablo", True, True)])
        self.assertEqual(g["durum"], "tamamlandi", g.get("rapor"))
        self.assertEqual(g["adimlar"][0]["yetenek"], "pdf_tablo")
        self.assertNotIn("bekleyen_uretim", g)

    def test_reddedilirse_iptal(self):
        yet = Yetenekler()
        m = SahteModel(analiz=[self.ANLAYIS2], planlama=[self.BOZUK])
        motor = self.motor(yet, m)
        g = motor.baslat("PDF")
        g = motor.onayla(g["gorev_id"], False)
        self.assertEqual(g["durum"], "iptal")
        self.assertEqual(yet.uretimler, [])

    def test_uret_yoksa_eski_davranis(self):
        m = SahteModel(analiz=[self.ANLAYIS2], planlama=[self.BOZUK])
        g = self.motor(SahteYetenekler(), m).baslat("PDF")
        self.assertEqual(g["durum"], "basarisiz")


if __name__ == "__main__":
    unittest.main()
