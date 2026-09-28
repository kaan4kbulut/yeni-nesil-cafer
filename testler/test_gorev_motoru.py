"""K4 — görev motoru (`asistan/cekirdek/gorev/`): anla → planla → uygula → doğrula, checkpoint ve devam, onay bekleme,
doğrulama başarısız → tekrar deneme, şemaya uymayan plan → `model_yetersiz`. Yetenekler ve model sahte; ağa gidilmez.

Çalıştırma (proje kökünde, programın Python'uyla):
    ~/.local/share/yeni-nesil-cafer-app/python/bin/python3 -m unittest discover -s testler -v
"""

import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

KOK = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(KOK))
_GECICI = tempfile.mkdtemp(prefix="yeni-nesil-cafer-test-")
os.environ["XDG_CONFIG_HOME"] = str(Path(_GECICI) / "ayar")
os.environ["XDG_DATA_HOME"] = str(Path(_GECICI) / "veri")

from asistan.cekirdek import ayar, semalar  # noqa: E402
from asistan.cekirdek.gorev import Cevap, Cikti, METIN_URET, ModelYok  # noqa: E402
from asistan.cekirdek.gorev import anlayici, dogrulayici, durum, planlayici, yurutucu  # noqa: E402
from asistan.cekirdek.saglayici import Iptal  # noqa: E402

LISTE = {"type": "object", "properties": {"klasor": {"type": "string"}}, "required": ["klasor"]}
OKU = {"type": "object", "properties": {"yol": {"type": "string"}}, "required": ["yol"]}
YAZ = {"type": "object", "properties": {"yol": {"type": "string"}, "icerik": {"type": "string"}},
       "required": ["yol", "icerik"]}


class SahteYetenekler:
    """dosya_listele / dosya_oku okur; dosya_yaz onay ister. `bozuk`: ilk N çağrı hata verir."""

    def __init__(self, bozuk: dict | None = None, iptal_sonra: int | None = None):
        self.cagrilar: list[tuple[str, dict, bool]] = []
        self.bozuk = dict(bozuk or {})
        self.iptal_sonra = iptal_sonra

    def listele(self):
        return [{"ad": "dosya_listele", "aciklama": "list files", "girdi_semasi": LISTE, "salt_okur": True},
                {"ad": "dosya_oku", "aciklama": "read a file", "girdi_semasi": OKU, "salt_okur": True},
                {"ad": "dosya_yaz", "aciklama": "write a file", "girdi_semasi": YAZ}]

    def onay_gerekir(self, ad, girdi):
        return ad == "dosya_yaz"

    def calistir(self, ad, girdi, onayli=False):
        self.cagrilar.append((ad, dict(girdi), onayli))
        if self.iptal_sonra is not None and len(self.cagrilar) > self.iptal_sonra:
            raise Iptal()
        if self.bozuk.get(ad):
            self.bozuk[ad] -= 1
            return Cikti("Error: dosya bulunamadı", True)
        if ad == "dosya_listele":
            return Cikti("a.txt 10 B\nbuyuk.txt 900 B")
        if ad == "dosya_oku":
            return Cikti(f"{girdi['yol']} içeriği: uzun bir metin")
        if ad == "dosya_yaz":
            return Cikti("yazıldı" if onayli else "The user declined to run this.", not onayli,
                         onay_bekliyor=not onayli)
        return Cikti(f"Error: bilinmeyen {ad}", True)


class SahteModel:
    """Rol başına sıradaki hazır cevap. Sözlük → şemaya uyan veri; metin → düz cevap."""

    def __init__(self, **cevaplar):
        self.cevaplar = {k: list(v) for k, v in cevaplar.items()}
        self.cagrilar: list[tuple[str, list]] = []

    def secim(self, rol):
        return {"saglayici": "ollama", "model": f"sahte-{rol}", "neden": "test"}

    def __call__(self, rol, mesajlar, sistem="", sema=None):
        self.cagrilar.append((rol, mesajlar))
        sira = self.cevaplar.get(rol)
        if not sira:
            raise ModelYok(f"{rol} için cevap yok")
        c = sira.pop(0)
        if isinstance(c, Cevap):
            return c
        if isinstance(c, dict):
            hatalar = semalar.dogrula(c, sema) if sema else []
            return Cevap(json.dumps(c, ensure_ascii=False), None if hatalar else c, self.secim(rol), hatalar)
        return Cevap(str(c), None, self.secim(rol))


ANLAYIS = {"niyet": "say ve özetle", "kisitlar": [], "belirsizlikler": [], "gereken_yetenekler": ["dosya_listele"],
           "eksik_yetenekler": [], "belirsizlik": "dusuk", "soru": ""}
UC_ADIM = {"adimlar": [
    {"amac": "txt dosyalarını listele", "yetenek": "dosya_listele", "girdi": {"klasor": "."},
     "basari_olcutu": "liste boş değil", "bagimli": [], "deneme_hakki": 1},
    {"amac": "en büyüğünü oku", "yetenek": "dosya_oku", "girdi": {"yol": "buyuk.txt"},
     "basari_olcutu": "dosyanın içeriği okundu", "bagimli": [1], "deneme_hakki": 1},
    {"amac": "özetle", "yetenek": METIN_URET, "girdi": {"talimat": "özetle", "veri": "{{adim_2.sonuc}}"},
     "basari_olcutu": "", "bagimli": [2], "deneme_hakki": 0},
]}
TAMAM = {"tamam": True, "eksik": ""}


class GorevTabani(unittest.TestCase):
    def setUp(self):
        self.klasor = tempfile.mkdtemp(dir=_GECICI)
        self.depo = durum.Depo(Path(self.klasor) / "gorevler.db")

    def motor(self, yet, model, **k):
        return yurutucu.Yurutucu(self.depo, yet, model, klasor=self.klasor, **k)


class SemaTesti(unittest.TestCase):
    def test_gorev_semasi_semalar_ornegini_kabul_eder(self):
        # docs/SEMALAR.md §2'deki örnek birebir
        metin = (KOK / "docs" / "SEMALAR.md").read_text(encoding="utf-8")
        blok = metin.split("## 2. Görev Planı")[1].split("```json")[1].split("```")[0]
        ornek = json.loads(blok)
        self.assertEqual(semalar.dogrula(ornek, semalar.yukle("gorev")), [])

    def test_bozuk_gorev_reddedilir(self):
        hatalar = semalar.dogrula({"gorev_id": "x", "durum": "uyuyor"}, semalar.yukle("gorev"))
        self.assertTrue(any("durum" in h for h in hatalar))
        self.assertTrue(any("'adimlar' eksik" in h for h in hatalar))

    def test_duzlestir_ref_birakmaz(self):
        self.assertNotIn("$ref", json.dumps(semalar.duzlestir(semalar.yukle("gorev"))))


class AnlayiciTesti(unittest.TestCase):
    def test_bilinmeyen_yetenek_eksige_gecer(self):
        m = SahteModel(analiz=[dict(ANLAYIS, gereken_yetenekler=["dosya_listele", "uydurma"])])
        anlayis, soru = anlayici.anla("say", SahteYetenekler().listele(), m)
        self.assertEqual(anlayis["gereken_yetenekler"], ["dosya_listele"])
        self.assertIn("uydurma", anlayis["eksik_yetenekler"])
        self.assertEqual(soru, "")

    def test_belirsizlik_yuksekse_tek_soru(self):
        m = SahteModel(analiz=[dict(ANLAYIS, belirsizlik="yuksek", soru="Hangi klasör?")])
        _, soru = anlayici.anla("dosyaları düzenle", [], m)
        self.assertEqual(soru, "Hangi klasör?")

    def test_model_yoksa_is_durmaz(self):
        anlayis, soru = anlayici.anla("merhaba dünya", [], SahteModel())
        self.assertEqual((anlayis["niyet"], soru), ("merhaba dünya", ""))


class PlanlayiciTesti(unittest.TestCase):
    def test_semaya_uymayan_plan_bir_duzeltmeden_sonra_model_yetersiz(self):
        yet = SahteYetenekler().listele()
        bozuk = {"adimlar": [{"amac": "x", "yetenek": "uydurma_arac", "girdi": {}, "basari_olcutu": "",
                              "bagimli": [], "deneme_hakki": 0}]}
        m = SahteModel(planlama=[bozuk])
        with self.assertRaises(planlayici.PlanYetersiz) as c:
            planlayici.planla("iş", ANLAYIS, yet, m)
        self.assertEqual(c.exception.kayit["sinif"], "model_yetersiz")
        self.assertEqual(semalar.dogrula(c.exception.kayit, semalar.yukle("gorev")["$defs"]["hata"]), [])

    def test_kural_hatasi_bir_duzeltme_turuyla_duzelir(self):
        ileri = {"adimlar": [dict(UC_ADIM["adimlar"][0], bagimli=[2]), UC_ADIM["adimlar"][1]]}
        m = SahteModel(planlama=[ileri, UC_ADIM])
        adimlar = planlayici.planla("iş", ANLAYIS, SahteYetenekler().listele(), m)
        self.assertEqual(len(adimlar), 3)
        self.assertEqual(len(m.cagrilar), 2)
        self.assertIn("bagimli", m.cagrilar[1][1][-1]["content"])

    def test_girdi_yetenegin_semasina_uyar(self):
        hatalar = planlayici.ek_denetim({"adimlar": [{"amac": "oku", "yetenek": "dosya_oku", "girdi": {},
                                                      "bagimli": []}]},
                                        planlayici.tum_yetenekler(SahteYetenekler().listele()))
        self.assertTrue(any("'yol' eksik" in h for h in hatalar))

    def test_yer_tutucuda_ifade_reddedilir(self):
        # canlı deneme: model {{adim_1.sonuc.splitlines()[2]}} yazdı; yürütücü bunu çözemez
        veri = {"adimlar": [UC_ADIM["adimlar"][0], dict(UC_ADIM["adimlar"][1], girdi={
            "yol": "{{adim_1.sonuc.splitlines()[2]}}"})]}
        hatalar = planlayici.ek_denetim(veri, planlayici.tum_yetenekler(SahteYetenekler().listele()))
        self.assertTrue(any("geçersiz" in h for h in hatalar))

    def test_yetenek_adi_semada_enum(self):
        sema = planlayici.plan_semasi(["a", "b"])
        self.assertEqual(sema["properties"]["adimlar"]["items"]["properties"]["yetenek"]["enum"], ["a", "b"])

    def test_program_alanlari_doldurulur(self):
        m = SahteModel()
        gorev = planlayici.gorev_olustur("iş", dict(ANLAYIS), UC_ADIM["adimlar"] + [
            {"amac": "yaz", "yetenek": "dosya_yaz", "girdi": {"yol": "o.txt", "icerik": "x"}, "bagimli": [9]}],
            SahteYetenekler(), m)
        a = gorev["adimlar"]
        self.assertEqual([x["id"] for x in a], [1, 2, 3, 4])
        self.assertTrue(a[3]["onay_gerekli"])
        self.assertEqual(a[3]["bagimli"], [])  # ileriye bakan bağımlılık atıldı
        self.assertEqual(a[0]["secim"]["neden"], "model gerekmiyor")
        self.assertEqual(a[2]["secim"]["model"], "sahte-ozet")  # model adımının kararı yönlendiriciden


class DogrulayiciTesti(unittest.TestCase):
    def test_once_programin_kaniti(self):
        adim = {"amac": "x", "yetenek": "y", "basari_olcutu": "rapor.txt oluşturuldu"}
        m = SahteModel(siniflandirma=[TAMAM])  # model "tamam" dese de dosya yok
        tamam, neden = dogrulayici.dogrula(adim, Cikti("yazdım"), [_GECICI], m)
        self.assertFalse(tamam)
        self.assertIn("rapor.txt", neden)
        self.assertEqual(m.cagrilar, [])

    def test_hata_ve_bos_sonuc(self):
        adim = {"basari_olcutu": "bir şey"}
        self.assertFalse(dogrulayici.dogrula(adim, Cikti("Error: x"))[0])
        self.assertFalse(dogrulayici.dogrula(adim, Cikti("exit code: 2\n..."))[0])
        self.assertFalse(dogrulayici.dogrula(adim, Cikti("  "))[0])

    def test_salt_okuyan_adimda_model_sorulmaz(self):
        # canlı deneme: okunan metin "sistemin yetenekleri" hakkındaydı, model doğru okumayı reddetti
        adim = {"amac": "oku", "yetenek": "dosya_oku", "basari_olcutu": "dosya içeriği başarıyla okundu"}
        m = SahteModel(siniflandirma=[{"tamam": False, "eksik": "yalnızca sistem bilgisi"}])
        self.assertEqual(dogrulayici.dogrula(adim, Cikti("Asistan dosya okuyabilir."), None, m, salt_okur=True),
                         (True, ""))
        self.assertEqual(m.cagrilar, [])
        self.assertFalse(dogrulayici.dogrula(adim, Cikti("Error: yok"), None, m, salt_okur=True)[0])

    def test_dizin_kelimesi_izin_sayilmaz(self):
        self.assertEqual(yurutucu.siniflandir("dizin boş döndü", "(empty directory)", False), "mantik")
        self.assertEqual(yurutucu.siniflandir("The user declined to run this.", "", False), "izin")

    def test_kural_karar_veremezse_model(self):
        adim = {"amac": "say", "yetenek": "y", "basari_olcutu": "sayı toplamla tutarlı"}
        m = SahteModel(siniflandirma=[{"tamam": False, "eksik": "sayı yok"}])
        self.assertEqual(dogrulayici.dogrula(adim, Cikti("bir metin"), None, m), (False, "sayı yok"))


class YurutucuTesti(GorevTabani):
    def test_uc_adimli_gorev(self):
        yet = SahteYetenekler()
        m = SahteModel(analiz=[ANLAYIS], planlama=[UC_ADIM], ozet=["Kısa özet."],
                       siniflandirma=[TAMAM, TAMAM])
        olaylar = []
        gorev = self.motor(yet, m, olay=lambda t, v: olaylar.append(t)).baslat("txt say, en büyüğünü özetle")
        self.assertEqual(gorev["durum"], "tamamlandi", gorev.get("rapor"))
        self.assertEqual([a["durum"] for a in gorev["adimlar"]], ["tamamlandi"] * 3)
        self.assertEqual(gorev["checkpoint"]["son_adim"], 3)
        # {{adim_2.sonuc}} çözüldü: özet modeline okunan içerik gitti
        ozet_istemi = [c for c in m.cagrilar if c[0] == "ozet"][0][1][0]["content"]
        self.assertIn("buyuk.txt içeriği", ozet_istemi)
        self.assertEqual(gorev["adimlar"][2]["sonuc"], "Kısa özet.")
        self.assertIn("plan", olaylar)
        kayitli = self.depo.getir(gorev["gorev_id"])
        self.assertEqual(semalar.dogrula(kayitli, semalar.yukle("gorev")), [])
        self.assertEqual(self.depo.yarim(), [])

    def test_ortada_kapatip_devam(self):
        # 2. adımda program "kapandı" (iptal): görev yarım, 1. adım checkpoint'te
        m = SahteModel(analiz=[ANLAYIS], planlama=[UC_ADIM], siniflandirma=[TAMAM])
        with self.assertRaises(Iptal):
            self.motor(SahteYetenekler(iptal_sonra=1), m).baslat("iş")
        yarim = durum.Depo(self.depo.yol).yarim()  # yeni depo nesnesi: program yeniden açıldı
        self.assertEqual(len(yarim), 1)
        g = yarim[0]
        self.assertEqual(g["checkpoint"]["son_adim"], 1)
        self.assertEqual([a["durum"] for a in g["adimlar"]], ["tamamlandi", "calisiyor", "planlandi"])
        self.assertEqual(durum.devam_noktasi(g), 1)
        yet2 = SahteYetenekler()
        m2 = SahteModel(ozet=["özet"], siniflandirma=[TAMAM, TAMAM])
        son = self.motor(yet2, m2).devam(g["gorev_id"])
        self.assertEqual(son["durum"], "tamamlandi")
        self.assertEqual([c[0] for c in yet2.cagrilar], ["dosya_oku"])  # 1. adım yeniden koşmadı

    def test_dogrulama_basarisiz_tekrar_dener(self):
        yet = SahteYetenekler(bozuk={"dosya_oku": 1})
        duzeltilmis = {"yol": "a.txt"}
        m = SahteModel(analiz=[ANLAYIS], planlama=[UC_ADIM, duzeltilmis], ozet=["özet"],
                       siniflandirma=[TAMAM, TAMAM])
        olaylar = []
        gorev = self.motor(yet, m, olay=lambda t, v: olaylar.append(t)).baslat("iş")
        self.assertEqual(gorev["durum"], "tamamlandi")
        okumalar = [c for c in yet.cagrilar if c[0] == "dosya_oku"]
        self.assertEqual([c[1]["yol"] for c in okumalar], ["buyuk.txt", "a.txt"])  # girdi düzeltildi
        self.assertIn("tekrar", olaylar)

    def test_deneme_hakki_bitince_basarisiz_ve_hata_kaydi(self):
        yet = SahteYetenekler(bozuk={"dosya_oku": 5})
        m = SahteModel(analiz=[ANLAYIS], planlama=[UC_ADIM], siniflandirma=[TAMAM])
        gorev = self.motor(yet, m).baslat("iş")
        self.assertEqual(gorev["durum"], "basarisiz")
        self.assertEqual(gorev["adimlar"][1]["durum"], "basarisiz")
        self.assertEqual(gorev["adimlar"][2]["durum"], "planlandi")
        self.assertEqual(gorev["hatalar"][0]["sinif"], "veri")
        self.assertIn("dosya bulunamadı", gorev["hatalar"][0]["belirti"])
        kutuk = ayar.DATA_DIR / "hatalar.jsonl"  # hata analizine devredildi (K6: cekirdek/analiz/hata.py kütüğü)
        self.assertIn("dosya bulunamadı", kutuk.read_text(encoding="utf-8"))

    def test_onay_gerekli_adim_bekler_ve_onayla_surer(self):
        plan = {"adimlar": [UC_ADIM["adimlar"][0],
                            {"amac": "rapor yaz", "yetenek": "dosya_yaz", "girdi": {"yol": "r.txt", "icerik": "x"},
                             "basari_olcutu": "", "bagimli": [], "deneme_hakki": 0}]}
        yet = SahteYetenekler()
        m = SahteModel(analiz=[ANLAYIS], planlama=[plan], siniflandirma=[TAMAM])
        gorev = self.motor(yet, m).baslat("iş")
        self.assertEqual(gorev["durum"], "bekliyor_onay")
        self.assertEqual(gorev["adimlar"][1]["durum"], "bekliyor_onay")
        self.assertNotIn("dosya_yaz", [c[0] for c in yet.cagrilar])  # onaysız çalışmadı
        self.assertEqual(len(self.depo.yarim()), 1)
        son = self.motor(yet, m).onayla(gorev["gorev_id"])
        self.assertEqual(son["durum"], "tamamlandi")
        self.assertEqual(yet.cagrilar[-1], ("dosya_yaz", {"yol": "r.txt", "icerik": "x"}, True))

    def test_calisma_aninda_izin_hatti_sorarsa_bekler(self):
        # planda onay tahmini yok ama yetenek (izin hattı) sordu: adım yine bekler, onaysız sayılmaz
        yet = SahteYetenekler()
        yet.onay_gerekir = lambda ad, girdi: False
        plan = {"adimlar": [{"amac": "yaz", "yetenek": "dosya_yaz", "girdi": {"yol": "r.txt", "icerik": "x"},
                             "basari_olcutu": "", "bagimli": [], "deneme_hakki": 0}]}
        gorev = self.motor(yet, SahteModel(analiz=[ANLAYIS], planlama=[plan])).baslat("iş")
        self.assertEqual(gorev["durum"], "bekliyor_onay")

    def test_reddedilen_onay_gorevi_durdurur(self):
        plan = {"adimlar": [{"amac": "yaz", "yetenek": "dosya_yaz", "girdi": {"yol": "r.txt", "icerik": "x"},
                             "basari_olcutu": "", "bagimli": [], "deneme_hakki": 0}]}
        yet = SahteYetenekler()
        gorev = self.motor(yet, SahteModel(analiz=[ANLAYIS], planlama=[plan])).baslat("iş")
        son = self.motor(yet, SahteModel()).onayla(gorev["gorev_id"], evet=False)
        self.assertEqual(son["durum"], "iptal")
        self.assertEqual(yet.cagrilar, [])

    def test_soru_ve_yanit(self):
        m = SahteModel(analiz=[dict(ANLAYIS, belirsizlik="yuksek", soru="Hangi klasör?")], planlama=[UC_ADIM],
                       ozet=["özet"], siniflandirma=[TAMAM, TAMAM])
        motor = self.motor(SahteYetenekler(), m)
        gorev = motor.baslat("dosyaları özetle", gorev_id="2026-01-01T00-00-00_abcd")
        self.assertEqual((gorev["durum"], gorev["rapor"]), ("bekliyor_kullanici", "Hangi klasör?"))
        self.assertEqual(gorev["gorev_id"], "2026-01-01T00-00-00_abcd")
        son = motor.yanitla(gorev["gorev_id"], "Belgeler")
        self.assertEqual(son["durum"], "tamamlandi")
        self.assertIn("Belgeler", son["istek"])

    def test_plan_yazilamazsa_durust_basarisiz(self):
        gorev = self.motor(SahteYetenekler(), SahteModel(analiz=[ANLAYIS])).baslat("iş")
        self.assertEqual(gorev["durum"], "basarisiz")
        self.assertTrue(gorev["rapor"].startswith("Yapılamadı"))
        self.assertEqual(gorev["hatalar"][0]["sinif"], "model_yetersiz")

    def test_yer_tutucu_cozumu(self):
        g = {"adimlar": [{"id": 1, "sonuc": "A"}, {"id": 2, "sonuc": "B"}]}
        self.assertEqual(yurutucu.coz({"x": "{{adim_1.sonuc}}", "y": ["ön {{ adim_2.sonuc }} son"], "z": 3}, g),
                         {"x": "A", "y": ["ön B son"], "z": 3})
        # kod adımının sonucu: yer tutucuya yalnızca yazdırdığı gider
        g = {"adimlar": [{"id": 1, "sonuc": "exit code: 0\n--- stdout ---\n/tmp/uzun.txt\n"}]}
        self.assertEqual(yurutucu.coz("{{adim_1.sonuc}}", g), "/tmp/uzun.txt")
        g = {"adimlar": [{"id": 1, "sonuc": "exit code: 1\n--- stderr ---\nhata"}]}
        self.assertIn("exit code: 1", yurutucu.coz("{{adim_1.sonuc}}", g))


class DepoTesti(GorevTabani):
    def test_kaydet_getir_listele_iptal(self):
        g = {"gorev_id": durum.yeni_id(), "istek": "x", "olusturma": durum.simdi(), "durum": "calisiyor",
             "adimlar": []}
        self.depo.kaydet(g, "sohbet-1")
        self.assertEqual(self.depo.getir(g["gorev_id"])["istek"], "x")
        self.assertEqual(len(self.depo.yarim()), 1)
        self.assertEqual(len(self.depo.sohbetin("sohbet-1")), 1)
        self.depo.kaydet(dict(g, istek="y"))  # sohbet kimliği korunur
        self.assertEqual(len(self.depo.sohbetin("sohbet-1")), 1)
        self.assertTrue(self.depo.iptal_et(g["gorev_id"]))
        self.assertEqual(self.depo.yarim(), [])
        self.assertEqual(self.depo.getir(g["gorev_id"])["durum"], "iptal")  # silinmedi

    def test_varsayilan_yol_veri_klasorunde_ve_ayri_dosya(self):
        yol = durum.varsayilan_yol()
        self.assertEqual(yol.parent, ayar.DATA_DIR)
        self.assertNotIn(yol.name, ("hafiza.db", "bulut.db"))
        # test gerçek veri klasörüne yazmıyor (pytest tek süreçte: XDG'yi ilk içe aktarılan test dosyası belirler)
        self.assertTrue(str(yol).startswith(tempfile.gettempdir()))


if __name__ == "__main__":
    unittest.main()
