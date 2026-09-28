"""UYGULA: görevi adım adım koşar; her adımdan sonra checkpoint (`durum.Depo`), kapanıp açılınca kaldığı yerden sürer.

- `{{adim_N.sonuc}}` yer tutucuları önceki adımın sonucuyla çözülür (değerin tamamıysa olduğu gibi, metnin içindeyse
  metin olarak).
- Onay: planda `onay_gerekli` (izin hattının tahmini) olan adımda görev `bekliyor_onay` olur ve durur; kullanıcı
  `onayla` deyince sürer. Onay kuralını yürütücü vermez: yetenek yine izin hattından geçer (`permissions.py`), hat
  kullanıcıya sorarsa cevap kullanıcının bu adıma verdiği onaydır. Hat tahminden farklı olarak çalışma anında sorarsa
  (`Cikti.onay_bekliyor`) adım yine bekler.
- Doğrulama başarısız → deneme hakkı varsa girdi modele düzelttirilip tekrar; yoksa adım ve görev `basarisiz`, hata
  kaydı (SEMALAR §3) göreve yazılır ve hata analizine devredilir (`yonlendirici.devret`; K6'da `analiz/hata.py`).
"""

import re
import time
from collections.abc import Callable

from .. import bildirim, yonlendirici
from ..analiz import hata
from ..saglayici import Iptal
from . import METIN_URET, Cikti, ModelYok, anlayici, dogrulayici, planlayici
from .durum import BITMIS, KLASOR_ALANI, Depo, devam_noktasi, simdi

SONUC_SINIRI = 20000  # adımın saklanan sonucu (karakter); görev JSON'u şişmesin
OZET_SINIRI = 200
YER_TUTUCU = planlayici.YER_TUTUCU
_BUTUN = re.compile(r"^\s*\{\{\s*adim_(\d+)\.sonuc\s*\}\}\s*$")


_KOMUT_CIKTISI = re.compile(r"^exit code: 0\n--- stdout ---\n(.*?)(?:\n--- stderr ---\n.*)?$", re.S)


def temiz_sonuc(sonuc: str) -> str:
    """Yer tutucuya giden değer: başarılı kod/komut adımında yalnızca stdout (ör. yalnızca dosya yolu yazdırıldıysa)."""
    m = _KOMUT_CIKTISI.match(sonuc or "")
    return m.group(1).strip() if m else (sonuc or "")


def coz(deger, gorev: dict):
    """Girdideki `{{adim_N.sonuc}}` yer tutucularını çözer (sözlük ve listelerin içinde de)."""
    sonuclar = {a["id"]: temiz_sonuc(a.get("sonuc", "")) for a in gorev.get("adimlar") or []}
    if isinstance(deger, dict):
        return {k: coz(v, gorev) for k, v in deger.items()}
    if isinstance(deger, list):
        return [coz(v, gorev) for v in deger]
    if isinstance(deger, str):
        butun = _BUTUN.match(deger)
        if butun:
            return sonuclar.get(int(butun.group(1)), "")
        return YER_TUTUCU.sub(lambda m: str(sonuclar.get(int(m.group(1)), "")), deger)
    return deger


def _kaydir(deger, n: int):
    """Yeniden planlanan adımların `{{adim_N.sonuc}}` yer tutucularını `n` kadar kaydırır."""
    if isinstance(deger, dict):
        return {k: _kaydir(v, n) for k, v in deger.items()}
    if isinstance(deger, list):
        return [_kaydir(v, n) for v in deger]
    if isinstance(deger, str):
        deger = re.sub(r"\{\{\s*adim_(\d+)\.sonuc\s*\}\}", lambda m: "{{adim_%d.sonuc}}" % (int(m.group(1)) + n), deger)
        # K12-E7: biten adımların sonucu — numarası kaymaz (yeni plan 1'den sayar; eskiden {{adim_N}} n kaydırılınca
        # biten 1. adım yeni 1. adıma bağlanıyordu, biten adımların çıktısı hiç kullanılamıyordu)
        return planlayici.YER_TUTUCU_ONCEKI.sub(lambda m: "{{adim_%d.sonuc}}" % int(m.group(1)), deger)
    return deger


def siniflandir(neden: str, sonuc: str, model_adimi: bool, model=None) -> str:
    """Sınıf (SEMALAR §3): `analiz/hata.py` (desen → hızlı model → mantik)."""
    from ..analiz import hata

    return hata.siniflandir(neden, sonuc, model_adimi, model)


BAGIMLILIK_SINIFI = "mantik"  # "bağlı olduğu adım bitmedi" plan/mantık hatasıdır, girdi verisi eksikliği değil


class Yurutucu:
    def __init__(self, depo: Depo, yetenekler, model, klasor: str = "", okunur: str = "",
                 olay: Callable[[str, dict], None] | None = None, iptal: Callable[[], bool] | None = None,
                 kademe: str = "orta", sohbet_id: str = "", bekle: Callable[[float], None] | None = None):
        self.depo, self.yetenekler, self.model = depo, yetenekler, model
        self.bekle = bekle or time.sleep  # ağ hatasında üstel bekleme (testler sahte verir)
        self.klasor, self.okunur = klasor, okunur
        self.olay_fn, self.iptal_fn = olay, iptal
        self.kademe, self.sohbet_id = kademe, sohbet_id

    # ---- bildirim ve kayıt
    def _olay(self, tur: str, gorev: dict, **ek) -> None:
        if self.olay_fn:
            self.olay_fn(tur, {"gorev": gorev, **ek})

    def _kaydet(self, gorev: dict) -> None:
        if self.klasor:
            gorev.setdefault(KLASOR_ALANI, self.klasor)
        self.depo.kaydet(gorev, self.sohbet_id or None)

    def _iptal_mi(self) -> None:
        if self.iptal_fn and self.iptal_fn():
            raise Iptal()

    # ---- giriş noktaları
    def baslat(self, istek: str, parcala: bool = False, gorev_id: str = "") -> dict:
        """Anla → planla → kaydet → koş. Belirsizlik yüksekse görev `bekliyor_kullanici` (rapor = soru).
        `gorev_id`: önceden verilen kimlik (iş klasörünün adı ona göre kurulduysa)."""
        liste = self.yetenekler.listele()
        pasifler = getattr(self.yetenekler, "pasifler", None)  # K5: kayıtlı ama kullanılamayan yetenekler
        anlayis, soru = anlayici.anla(istek, liste, self.model, pasifler() if pasifler else None)
        if soru:
            gorev = planlayici.gorev_olustur(istek, anlayis, [], self.yetenekler, self.model, self.kademe)
            gorev["gorev_id"] = gorev_id or gorev["gorev_id"]
            gorev["durum"], gorev["rapor"] = "bekliyor_kullanici", soru
            self._kaydet(gorev)
            self._olay("soru", gorev, soru=soru)
            return gorev
        return self._planla_ve_kos(istek, anlayis, liste, parcala, gorev_id)

    def yanitla(self, gorev_id: str, cevap: str) -> dict:
        """Kullanıcının tek soruya cevabı: istek cevapla genişler, görev aynı kimlikle planlanıp koşar."""
        eski = self._getir(gorev_id)
        istek = f"{eski['istek']}\n\n(Kullanıcının cevabı: {cevap.strip()})"
        anlayis = dict(eski["anlayis"], belirsizlikler=[])
        return self._planla_ve_kos(istek, anlayis, self.yetenekler.listele(), False, gorev_id=gorev_id)

    def devam(self, gorev_id: str) -> dict:
        """Yarım görevi `checkpoint`'ten sonraki ilk bitmemiş adımdan sürdürür. Yarıda kalan adım baştan koşar."""
        gorev = self._getir(gorev_id)
        if gorev["durum"] in BITMIS or gorev["durum"] == "bekliyor_kullanici":
            return gorev
        for adim in gorev["adimlar"]:
            if adim["durum"] == "calisiyor":
                adim["durum"] = "planlandi"
        return self.kos(gorev)

    def onayla(self, gorev_id: str, evet: bool = True) -> dict:
        """Onay bekleyen adım: evet → sürer; hayır → görev iptal (adım yapılmaz)."""
        gorev = self._getir(gorev_id)
        bekleyen = gorev.pop("bekleyen_uretim", None)
        if bekleyen:  # planlanamadı: eksik yetenek üretimi onayı (K6)
            if not evet:
                gorev["durum"] = "iptal"
                gorev["rapor"] = f"'{bekleyen['ad']}' yeteneğinin üretimi onaylanmadı; görev durduruldu."
                self._kaydet(gorev)
                self._olay("bitti", gorev)
                return gorev
            if bekleyen.get("kur") and hasattr(self.yetenekler, "kur"):  # K12-A9: paket onayı verildi → kur → üret
                k = self.yetenekler.kur(bekleyen["kur"], f"{bekleyen['ad']} yeteneği için", onayli=True)
                if k.hata:
                    gorev["durum"], gorev["rapor"] = "basarisiz", f"Yapılamadı: kurulum — {k.metin[:300]}"
                    self._kaydet(gorev)
                    self._olay("bitti", gorev)
                    return gorev
                self._olay("kurulum", gorev, metin=k.metin)
            c = self._uret(bekleyen["ad"], bekleyen["aciklama"])
            if c.onay_bekliyor and not bekleyen.get("kur"):  # üretim bir paket istiyor: ayrı onay (K12-A9)
                gorev["bekleyen_uretim"] = dict(bekleyen, kur=getattr(self.yetenekler, "bekleyen_kurulum", ""))
                gorev["durum"], gorev["rapor"] = "bekliyor_onay", f"{c.metin} Kurulsun mu?"
                self._kaydet(gorev)
                self._olay("onay", gorev, uretim=gorev["bekleyen_uretim"])
                bildirim.onay_bekliyor(gorev)
                return gorev
            if c.hata or c.onay_bekliyor:
                kayit = hata.isle({"adim": 0, "zaman": simdi(), "sinif": "eksik_yetenek", "belirti": c.metin[:300],
                                   "kanit": "", "sonuc": "vazgecildi"})
                gorev["durum"], gorev["hatalar"] = "basarisiz", gorev.get("hatalar", []) + [kayit]
                gorev["rapor"] = f"Yapılamadı: {c.metin[:300]}"
                self._kaydet(gorev)
                self._olay("bitti", gorev)
                return gorev
            self._olay("yetenek", gorev, ad=bekleyen["ad"], metin=c.metin)
            return self._planla_ve_kos(gorev["istek"], gorev["anlayis"], self.yetenekler.listele(), False, gorev_id,
                                       uretim_denendi=True)
        adim = next((a for a in gorev["adimlar"] if a["durum"] == "bekliyor_onay"), None)
        if adim is None:
            return gorev
        if not evet:
            adim["durum"], gorev["durum"] = "iptal", "iptal"
            gorev["rapor"] = f"Adım {adim['id']} onaylanmadı; görev durduruldu."
            self._kaydet(gorev)
            self._olay("bitti", gorev)
            return gorev
        adim["onay"], adim["durum"] = "verildi", "planlandi"
        return self.kos(gorev)

    def _getir(self, gorev_id: str) -> dict:
        gorev = self.depo.getir(gorev_id)
        if gorev is None:
            raise KeyError(f"görev yok: {gorev_id}")
        return gorev

    def _planla_ve_kos(self, istek: str, anlayis: dict, liste: list[dict], parcala: bool,
                       gorev_id: str = "", uretim_denendi: bool = False) -> dict:
        try:
            adimlar = planlayici.planla(istek, anlayis, liste, self.model, self.klasor, self.okunur, parcala)
        except planlayici.PlanYetersiz as e:
            gorev = planlayici.gorev_olustur(istek, anlayis, [], self.yetenekler, self.model, self.kademe)
            if gorev_id:
                gorev["gorev_id"] = gorev_id
            eksik = [a for a in (anlayis.get("eksik_yetenekler") or []) if re.fullmatch(r"[a-z][a-z0-9_]{1,40}", str(a))]
            if eksik and hasattr(self.yetenekler, "uret") and not uretim_denendi:
                # MIMARI §7 eksik_yetenek: üretim yalnızca onayla; görev onay bekler, onayla → üret → yeniden planla
                gorev["bekleyen_uretim"] = {"ad": eksik[0], "aciklama": f"{istek[:300]} — gereken yetenek: {eksik[0]}"}
                gorev["durum"] = "bekliyor_onay"
                gorev["rapor"] = (f"'{eksik[0]}' adında bir yetenek yok; bu iş için onu üretip (sandbox'ta test edip) "
                                  "kaydedeyim mi?")
                self._kaydet(gorev)
                self._olay("onay", gorev, uretim=gorev["bekleyen_uretim"])
                bildirim.onay_bekliyor(gorev)
                return gorev
            gorev["durum"], gorev["hatalar"] = "basarisiz", [e.kayit]
            gorev["rapor"] = f"Yapılamadı: {e.kayit['belirti']}"
            self._kaydet(gorev)
            yonlendirici.devret(e.kayit)
            self._olay("bitti", gorev)
            return gorev
        gorev = planlayici.gorev_olustur(istek, anlayis, adimlar, self.yetenekler, self.model, self.kademe)
        if gorev_id:
            gorev["gorev_id"] = gorev_id
        self._kaydet(gorev)
        self._olay("plan", gorev)
        return self.kos(gorev)

    # ---- döngü
    def kos(self, gorev: dict) -> dict:
        if hasattr(self.model, "gorev_id"):  # bulut sayacı görev başına (Görevler penceresi ayrı iş parçacığında)
            self.model.gorev_id = gorev["gorev_id"]
        gorev["durum"] = "calisiyor"
        self._kaydet(gorev)
        adimlar = gorev["adimlar"]
        i = devam_noktasi(gorev)
        while i < len(adimlar):
            self._iptal_mi()
            adim = adimlar[i]
            if adim["durum"] == "tamamlandi":
                i += 1
                continue
            eksik = [b for b in adim.get("bagimli") or [] if adimlar[b - 1]["durum"] != "tamamlandi"]
            if eksik:
                return self._basarisiz(gorev, adim, f"bağlı olduğu adım bitmedi: {eksik}", "", BAGIMLILIK_SINIFI)
            if adim.get("onay_gerekli") and adim.get("onay") != "verildi":
                return self._bekle(gorev, adim)
            sonuc = self._adim(gorev, adim)
            if sonuc is not None:
                return sonuc  # bekliyor ya da başarısız: görev burada durdu
            i += 1
        gorev["durum"] = "tamamlandi"
        gorev["rapor"] = self._rapor(gorev)
        self._kaydet(gorev)
        self._olay("bitti", gorev)
        return gorev

    def _adim(self, gorev: dict, adim: dict) -> dict | None:
        """Adımı koşar, doğrular, gerekirse tekrar dener. Görev durduysa görevi, sürüyorsa None döndürür."""
        adim["durum"] = "calisiyor"
        self._kaydet(gorev)
        self._olay("adim", gorev, adim=adim)
        basla = time.monotonic()
        neden, cikti = "", Cikti("")
        klasorler = [k for k in (self.klasor, self.okunur) if k]
        bekleyen = adim.get("bekleyen")
        if bekleyen and adim.get("onay") == "verildi":  # onaylanan kurulum / üretim önce yapılır (K6)
            adim.pop("bekleyen", None)
            adim.pop("onay", None)
            c = self._eylem_uygula(bekleyen, onayli=True)
            if c.hata:
                return self._basarisiz(gorev, adim, c.metin[:300], "", "eksik_bagimlilik" if bekleyen["tip"] == "kur"
                                       else "eksik_yetenek")
            adim[bekleyen["tip"] + "uldu" if bekleyen["tip"] == "kur" else "uretildi"] = True
            self._olay("yetenek" if bekleyen["tip"] == "uret" else "kurulum", gorev, adim=adim, metin=c.metin)
        for deneme in range(1 + int(adim.get("deneme_hakki") or 0)):
            self._iptal_mi()
            girdi = coz(adim["girdi"], gorev)
            cikti = self._calistir(adim, girdi, neden if deneme else "")
            if cikti.onay_bekliyor:
                return self._bekle(gorev, adim)
            tamam, neden = dogrulayici.dogrula(adim, cikti, klasorler, self.model, self._salt_okur(adim["yetenek"]))
            if adim["yetenek"] == METIN_URET and (adim.get("secim") or {}).get("model"):  # K7: başarı oranı
                from ..analiz import olcum

                olcum.basari_kaydet(adim["secim"].get("saglayici") or "", adim["secim"]["model"],
                                    tamam and not neden.startswith(dogrulayici.SARTLI), time.monotonic() - basla)
            if tamam:
                adim["durum"] = "tamamlandi"
                if neden.startswith(dogrulayici.SARTLI):  # denetlenemedi: geçti sayılmaz, raporda ✓?
                    adim["sartli"] = neden[len(dogrulayici.SARTLI):].lstrip(": ")
                else:
                    adim.pop("sartli", None)
                adim["sonuc"] = (cikti.metin or "")[:SONUC_SINIRI]
                adim["sonuc_ozeti"] = " ".join((cikti.metin or "").split())[:OZET_SINIRI]
                adim["sure_sn"] = round(time.monotonic() - basla, 2)
                gorev["checkpoint"] = {"son_adim": adim["id"], "zaman": simdi()}
                self._kaydet(gorev)
                self._olay("adim", gorev, adim=adim)
                return None
            adim["not"] = neden[:300]
            if deneme < int(adim.get("deneme_hakki") or 0) and adim["yetenek"] != METIN_URET:
                yeni = planlayici.duzelt_girdi(adim, neden, cikti.metin, self.yetenekler.listele(), self.model,
                                               gorev["adimlar"])
                if yeni:
                    adim["girdi"] = yeni
                    adim.pop("onay", None)  # kullanıcı eski girdiyi onaylamıştı: yenisi yeniden sorulur
            self._olay("tekrar", gorev, adim=adim, neden=neden)
        adim["sure_sn"] = round(time.monotonic() - basla, 2)
        return self._hata_eylemi(gorev, adim, neden, cikti.metin)

    # ---- hata analizi → eylem (MIMARI §7; K6)
    def _hata_eylemi(self, gorev: dict, adim: dict, neden: str, sonuc: str) -> dict | None:
        kayit = hata.isle({"adim": adim["id"], "zaman": simdi(), "belirti": neden[:300],
                           "kanit": "\n".join((sonuc or "").strip().splitlines()[-5:])[:1000],
                           "model_adimi": adim["yetenek"] == METIN_URET, "sonuc": "vazgecildi"}, self.model)
        e, tip, hedef = kayit["eylem"], kayit["eylem"]["tip"], kayit["eylem"].get("hedef", "")
        if tip == "kur" and hedef and not adim.get("kuruldu") and hasattr(self.yetenekler, "kur"):
            c = self.yetenekler.kur(hedef, f"{adim['amac']} için eksik bağımlılık", onayli=False)
            if c.onay_bekliyor:
                adim["bekleyen"] = {"tip": "kur", "hedef": hedef}
                return self._bekle(gorev, adim)
            if not c.hata:
                adim["kuruldu"] = True
                kayit["sonuc"] = "kuruldu_ve_tekrar_denendi"
                self._olay("kurulum", gorev, adim=adim, metin=c.metin)
                return self._adim(gorev, adim)
            neden = f"{neden}; kurulum: {c.metin[:200]}"
        elif tip == "uret" and hasattr(self.yetenekler, "uret") and not adim.get("uretildi"):
            ad = hedef.split(":", 1)[1] if hedef.startswith("yetenek:") else adim["yetenek"]
            if re.fullmatch(r"[a-z][a-z0-9_]{1,40}", ad):
                adim["bekleyen"] = {"tip": "uret", "ad": ad, "aciklama": f"{gorev['istek'][:300]} — adım: {adim['amac']}"}
                return self._bekle(gorev, adim)
        elif tip == "tekrar":
            n = int(adim.get("ag_deneme") or 0)
            if n < int(e.get("deneme") or 3):
                adim["ag_deneme"] = n + 1
                self._olay("tekrar", gorev, adim=adim, neden=f"ağ hatası, {n + 1}. deneme: {neden[:120]}")
                self.bekle(float((e.get("bekleme_sn") or [1, 2, 4])[min(n, 2)]))
                return self._adim(gorev, adim)
        elif tip == "yeniden_planla":
            if int(gorev.get("yeniden_plan") or 0) < int(e.get("en_cok") or 2):
                return self._yeniden_planla(gorev, adim, neden, sonuc)
        elif tip == "sor":
            adim["durum"] = "planlandi"
            gorev["durum"] = "bekliyor_kullanici"
            gorev["rapor"] = (f"Adım {adim['id']} ({adim['amac']}) izin gerektiriyor: {neden[:200]}. "
                              "Nasıl devam edeyim?")
            self._kaydet(gorev)
            self._olay("soru", gorev, soru=gorev["rapor"])
            return gorev
        return self._basarisiz(gorev, adim, neden, sonuc, kayit)

    def _eylem_uygula(self, bekleyen: dict, onayli: bool) -> Cikti:
        if bekleyen["tip"] == "kur":
            return self.yetenekler.kur(bekleyen["hedef"], "onaylanan kurulum", onayli=onayli)
        return self._uret(bekleyen["ad"], bekleyen["aciklama"])

    def _uret(self, ad: str, aciklama: str) -> Cikti:
        try:
            return self.yetenekler.uret(ad, aciklama, onayli=True, model=self.model)
        except TypeError:  # eski uyarlayıcı: model almaz
            return self.yetenekler.uret(ad, aciklama, onayli=True)

    def _yeniden_planla(self, gorev: dict, adim: dict, neden: str, sonuc: str) -> dict:
        """MIMARI §7 `mantik`: başarısız çıktı bağlama eklenip kalan iş yeniden planlanır (en çok 2 kez). Biten adımlar
        kalır; yeni adımlar onların ardına numaralanır."""
        gorev["yeniden_plan"] = int(gorev.get("yeniden_plan") or 0) + 1
        bitenler = [a for a in gorev["adimlar"] if a["durum"] == "tamamlandi"]
        n = len(bitenler)
        gecmis = "".join(f"Done step {a['id']} ({a['amac']}): {str(a.get('sonuc') or '')[:800]}\n" for a in bitenler)
        istek = (f"{gorev['istek']}\n\n(Replanning after a failure. Already done — do NOT repeat:\n{gecmis}"
                 f"Failed step: {adim['amac']} — {neden[:300]}\nIts output:\n{(sonuc or '')[:1000]}\n"
                 "Plan only the remaining work. Number the new steps from 1. To use an earlier result write exactly "
                 "{{onceki_N.sonuc}} with N = the done step's number above (NOT adim_N).)")
        try:
            adimlar = planlayici.planla(istek, gorev["anlayis"], self.yetenekler.listele(), self.model, self.klasor,
                                        self.okunur)
            yeni = planlayici.gorev_olustur(gorev["istek"], gorev["anlayis"], adimlar, self.yetenekler, self.model,
                                            self.kademe)["adimlar"]
        except planlayici.PlanYetersiz as e:
            return self._basarisiz(gorev, adim, f"{neden}; yeniden planlanamadı: {e.kayit['belirti']}", sonuc, "mantik")
        for a in yeni:
            a["id"] += n
            a["bagimli"] = [b + n for b in a["bagimli"]]
            a["girdi"] = _kaydir(a["girdi"], n)
        adim["durum"] = "iptal"
        adim["not"] = f"yeniden planlandı: {neden[:200]}"
        gorev["adimlar"] = bitenler + yeni
        gorev["checkpoint"] = {"son_adim": n, "zaman": simdi()}
        self._kaydet(gorev)
        self._olay("plan", gorev, yeniden=True)
        return self.kos(gorev)

    def _salt_okur(self, ad: str) -> bool:
        return any(y["ad"] == ad and y.get("salt_okur") for y in self.yetenekler.listele())

    def _calistir(self, adim: dict, girdi: dict, onceki_neden: str) -> Cikti:
        if adim["yetenek"] == METIN_URET:
            istem = str(girdi.get("talimat") or adim["amac"])
            if girdi.get("veri"):
                istem += "\n\n---\n" + str(girdi["veri"])[:SONUC_SINIRI]
            if onceki_neden:
                istem += f"\n\n(Önceki deneme yetersizdi: {onceki_neden}. Buna dikkat et.)"
            try:
                cevap = self.model("ozet", [{"role": "user", "content": istem}],
                                   "Answer in the user's language (usually Turkish).")
            except ModelYok as e:
                return Cikti(f"Error: model yok: {e}", True)
            adim["secim"] = cevap.secim or adim.get("secim")
            return Cikti(cevap.metin)
        return self.yetenekler.calistir(adim["yetenek"], girdi, adim.get("onay") == "verildi")

    def _bekle(self, gorev: dict, adim: dict) -> dict:
        adim["durum"] = gorev["durum"] = "bekliyor_onay"
        adim.pop("onay", None)  # verilen onay yalnızca bir çalıştırma içindi
        self._kaydet(gorev)
        self._olay("onay", gorev, adim=adim)
        bildirim.onay_bekliyor(gorev)  # K9: telefona (ntfy/Telegram); ayarlı değilse hiçbir şey yapmaz
        return gorev

    def _basarisiz(self, gorev: dict, adim: dict, neden: str, sonuc: str, sinif) -> dict:
        """`sinif`: sınıf adı ya da hata analizinin tamamladığı kayıt (SEMALAR §3)."""
        adim["durum"] = "basarisiz"
        adim["sonuc_ozeti"] = " ".join((sonuc or neden).split())[:OZET_SINIRI]
        if isinstance(sinif, dict):
            kayit = {k: v for k, v in sinif.items() if k != "model_adimi"}
            kayit["belirti"] = neden[:300]
        else:
            kayit = {"adim": adim["id"], "zaman": simdi(), "sinif": sinif, "belirti": neden[:300],
                     "kanit": "\n".join((sonuc or "").strip().splitlines()[-5:])[:1000],
                     "eylem": hata.eylem(sinif, neden, sonuc), "sonuc": "vazgecildi"}
        gorev["hatalar"].append(kayit)
        gorev["durum"] = "basarisiz"
        gorev["rapor"] = self._rapor(gorev)
        self._kaydet(gorev)
        yonlendirici.devret(kayit)
        self._olay("bitti", gorev)
        return gorev

    @staticmethod
    def _rapor(gorev: dict) -> str:
        """Kısa özet: ne yapıldı, ne yapılamadı."""
        satirlar = []
        for a in gorev["adimlar"]:
            isaret = {"tamamlandi": "✓", "basarisiz": "✗", "iptal": "–"}.get(a["durum"], "○")
            if a["durum"] == "tamamlandi" and a.get("sartli"):
                isaret = "✓?"  # şartlı: denetlenemedi, geçti sayılmaz
            ek = a.get("sonuc_ozeti") or a.get("not") or ""
            if a.get("sartli"):
                ek = f"şartlı ({a['sartli']})" + (f" · {ek}" if ek else "")
            satirlar.append(f"{isaret} {a['id']}. {a['amac']}" + (f" — {ek[:140]}" if ek else ""))
        bitti = sum(a["durum"] == "tamamlandi" and not a.get("sartli") for a in gorev["adimlar"])
        sartli = sum(a["durum"] == "tamamlandi" and bool(a.get("sartli")) for a in gorev["adimlar"])
        n = len(gorev["adimlar"])
        if bitti == n:
            bas = "Tamamlandı"
        elif bitti + sartli == n:
            bas = f"{bitti}/{n} adım doğrulandı, {sartli} adım şartlı (denetlenemedi)"
        else:
            bas = f"{bitti}/{n} adım yapıldı" + (f", {sartli} adım şartlı" if sartli else "")
        return bas + "\n" + "\n".join(satirlar)
