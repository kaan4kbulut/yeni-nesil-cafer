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

from .. import yonlendirici
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


def siniflandir(neden: str, sonuc: str, model_adimi: bool) -> str:
    """Kaba sınıf (SEMALAR §3); ayrıntılı sınıflandırıcı K6'da `analiz/hata.py`."""
    metin = f"{neden}\n{sonuc}"
    if re.search(r"ModuleNotFoundError|No module named|command not found|not recognized as|\.so\b|\.dll\b", metin):
        return "eksik_bagimlilik"
    if re.search(r"declined|reddetti|Permission denied|\b(izin|izni|onay)|REFUSED|BLOCKED", metin, re.I):
        return "izin"
    if re.search(r"Timeout|timed out|ConnectError|zaman aşımı|bağlanılamadı|\b5\d\d\b", metin, re.I):
        return "ag"
    if re.search(r"MemoryError|out of memory|No space left|CUDA", metin):
        return "kaynak"
    if re.search(r"No such file|FileNotFoundError|bulunamadı|dosya yok", metin):
        return "veri"
    if model_adimi and not (sonuc or "").strip():
        return "model_yetersiz"
    return "mantik"


class Yurutucu:
    def __init__(self, depo: Depo, yetenekler, model, klasor: str = "", okunur: str = "",
                 olay: Callable[[str, dict], None] | None = None, iptal: Callable[[], bool] | None = None,
                 kademe: str = "orta", sohbet_id: str = ""):
        self.depo, self.yetenekler, self.model = depo, yetenekler, model
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
        anlayis, soru = anlayici.anla(istek, liste, self.model)
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
                       gorev_id: str = "") -> dict:
        try:
            adimlar = planlayici.planla(istek, anlayis, liste, self.model, self.klasor, self.okunur, parcala)
        except planlayici.PlanYetersiz as e:
            gorev = planlayici.gorev_olustur(istek, anlayis, [], self.yetenekler, self.model, self.kademe)
            if gorev_id:
                gorev["gorev_id"] = gorev_id
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
                return self._basarisiz(gorev, adim, f"bağlı olduğu adım bitmedi: {eksik}", "", "veri")
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
        for deneme in range(1 + int(adim.get("deneme_hakki") or 0)):
            self._iptal_mi()
            girdi = coz(adim["girdi"], gorev)
            cikti = self._calistir(adim, girdi, neden if deneme else "")
            if cikti.onay_bekliyor:
                return self._bekle(gorev, adim)
            tamam, neden = dogrulayici.dogrula(adim, cikti, klasorler, self.model, self._salt_okur(adim["yetenek"]))
            if tamam:
                adim["durum"] = "tamamlandi"
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
        sinif = siniflandir(neden, cikti.metin, adim["yetenek"] == METIN_URET)
        return self._basarisiz(gorev, adim, neden, cikti.metin, sinif)

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
        return gorev

    def _basarisiz(self, gorev: dict, adim: dict, neden: str, sonuc: str, sinif: str) -> dict:
        adim["durum"] = "basarisiz"
        adim["sonuc_ozeti"] = " ".join((sonuc or neden).split())[:OZET_SINIRI]
        kayit = {"adim": adim["id"], "zaman": simdi(), "sinif": sinif, "belirti": neden[:300],
                 "kanit": "\n".join((sonuc or "").strip().splitlines()[-5:])[:1000],
                 "eylem": {"tip": "devret", "hedef": "analiz/hata", "onay": "yok"}, "sonuc": "vazgecildi"}
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
            ek = a.get("sonuc_ozeti") or a.get("not") or ""
            satirlar.append(f"{isaret} {a['id']}. {a['amac']}" + (f" — {ek[:120]}" if ek else ""))
        bitti = sum(a["durum"] == "tamamlandi" for a in gorev["adimlar"])
        bas = "Tamamlandı" if bitti == len(gorev["adimlar"]) else f"{bitti}/{len(gorev['adimlar'])} adım yapıldı"
        return bas + "\n" + "\n".join(satirlar)
