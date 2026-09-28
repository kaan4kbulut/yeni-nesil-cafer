"""Uzak mod ve senkron (K9): masaüstü sunucuya (`arayuz/web`) bağlanır — görev deposu ve motor sunucuda; çevrimdışı
yerel kuyruk bağlanınca eşitlenir (son yazan kazanır, çakışma listesi `DATA_DIR/senkron.json`).

`UzakDepo`/`UzakMotor` yerel `Depo`/`Yurutucu` ile aynı çağrıları sunar (Görevler penceresi ve komut satırı ikisini de
kullanır). Ayar: `settings.extra["cloud"] = {url, token, enabled, uzak_mod}`."""

import json
import logging
import time

import httpx

from . import ayar
from .gorev import durum as durum_mod

_gunluk = logging.getLogger(__name__)
ZAMAN = httpx.Timeout(30, connect=5)


class UzakHata(RuntimeError):
    pass


class Istemci:
    def __init__(self, url: str, anahtar: str, http=None):
        self.url, self.anahtar, self.http = url.rstrip("/"), anahtar, http or httpx

    def istek(self, yontem: str, yol: str, govde: dict | None = None) -> dict:
        try:
            r = self.http.request(yontem, self.url + yol, json=govde, timeout=ZAMAN,
                                  headers={"Authorization": f"Bearer {self.anahtar}"})
        except httpx.HTTPError as e:
            raise UzakHata(f"sunucuya ulaşılamadı: {e}") from e
        if r.status_code == 401:
            raise UzakHata("erişim anahtarı yanlış")
        if r.status_code == 404:
            return {}
        if r.status_code >= 400:
            raise UzakHata(f"sunucu hatası ({r.status_code}): {r.text[:200]}")
        return r.json() if r.content else {}


def ayarlardan(settings) -> Istemci | None:
    conf = (getattr(settings, "extra", None) or {}).get("cloud") or {}
    if conf.get("url") and conf.get("token") and conf.get("enabled", True):
        return Istemci(conf["url"], conf["token"])
    return None


def uzak_mod(settings) -> bool:
    """Görevler sunucuda (Görevler penceresi ve komut satırı sunucuyu kullanır)."""
    conf = (getattr(settings, "extra", None) or {}).get("cloud") or {}
    return bool(conf.get("uzak_mod")) and ayarlardan(settings) is not None


class UzakDepo:
    """`durum.Depo`'nun okuma yüzü, sunucudan."""

    def __init__(self, istemci: Istemci):
        self.i = istemci
        self.yol = f"uzak:{istemci.url}"

    def listele(self, durumlar=None, sinir: int = 100) -> list[dict]:
        sonuc = []
        for oz in self.i.istek("GET", f"/gorev?sinir={int(sinir)}").get("gorevler") or []:
            if durumlar and oz.get("durum") not in durumlar:
                continue
            g = self.getir(oz["gorev_id"])
            if g:
                sonuc.append(g)
        return sonuc

    def getir(self, gorev_id: str) -> dict | None:
        g = self.i.istek("GET", f"/gorev/{gorev_id}")
        return g or None

    def yarim(self) -> list[dict]:
        return self.listele(durum_mod.YARIM)

    def sohbet_yarim(self) -> list[dict]:
        return [g for g in self.yarim() if g.get("_sohbet_id")]

    def iptal_et(self, gorev_id: str) -> bool:
        return bool(self.i.istek("POST", f"/gorev/{gorev_id}/iptal").get("iptal"))


class UzakMotor:
    """`Yurutucu`'nun giriş noktaları sunucuda; sonuç görevin sunucudaki son hâli (kısa bekleme ile)."""

    def __init__(self, istemci: Istemci, bekle_sn: float = 0.0):
        self.i, self.bekle_sn = istemci, bekle_sn

    def _son(self, gorev_id: str) -> dict:
        if self.bekle_sn:
            time.sleep(self.bekle_sn)
        return self.i.istek("GET", f"/gorev/{gorev_id}") or {"gorev_id": gorev_id, "durum": "planlandi", "adimlar": []}

    def baslat(self, istek: str, parcala: bool = False, gorev_id: str = "") -> dict:
        r = self.i.istek("POST", "/gorev", {"istek": istek, "gorev_id": gorev_id})
        return self._son(r["gorev_id"])

    def onayla(self, gorev_id: str, evet: bool = True) -> dict:
        self.i.istek("POST", f"/gorev/{gorev_id}/onayla", {"evet": bool(evet)})
        return self._son(gorev_id)

    def yanitla(self, gorev_id: str, cevap: str) -> dict:
        self.i.istek("POST", f"/gorev/{gorev_id}/yanit", {"cevap": cevap})
        return self._son(gorev_id)

    def devam(self, gorev_id: str) -> dict:
        self.i.istek("POST", f"/gorev/{gorev_id}/devam")
        return self._son(gorev_id)


# ---------------------------------------------------------------- senkron

def _senkron_dosyasi():
    return ayar.DATA_DIR / "senkron.json"


def senkron_durumu() -> dict:
    try:
        veri = json.loads(_senkron_dosyasi().read_text(encoding="utf-8"))
        return veri if isinstance(veri, dict) else {}
    except (OSError, ValueError):
        return {}


def _senkron_yaz(veri: dict) -> None:
    _senkron_dosyasi().parent.mkdir(parents=True, exist_ok=True)
    _senkron_dosyasi().write_text(json.dumps(veri, ensure_ascii=False, indent=1), encoding="utf-8")


def gorevleri_esitle(depo, istemci: Istemci) -> dict:
    """İki yönlü görev eşitleme: yerelde `son`dan beri değişenler sunucuya, sunucuda değişenler yerele; son yazan
    kazanır, iki yanda da değişmiş görevler `cakismalar`a yazılır. Döner: {gonderilen, alinan, cakismalar}."""
    d = senkron_durumu()
    since_yerel, since_uzak = float(d.get("son_yerel") or 0), float(d.get("son_uzak") or 0)
    yerel = depo.degisenler(since_yerel)
    simdi = time.time()
    cevap = istemci.istek("POST", "/gorev/esitle", {
        "since": since_uzak, "gorevler": [{"gorev": {k: v for k, v in g.items() if k != "_surum"}, "guncelleme": g["_surum"]}
                                          for g in yerel]})
    cakismalar = list(cevap.get("cakismalar") or [])
    alinan = 0
    for kayit in cevap.get("gorevler") or []:
        sonuc = depo.ice_aktar(kayit["gorev"], float(kayit["guncelleme"]), since_yerel)
        if sonuc == "cakisma":
            cakismalar.append({"gorev_id": kayit["gorev"]["gorev_id"], "yer": "yerel", "zaman": simdi})
        if sonuc != "eski":
            alinan += 1
    d.update(son_yerel=simdi, son_uzak=float(cevap.get("now") or simdi),
             cakismalar=(list(d.get("cakismalar") or []) + cakismalar)[-50:], son_esitleme=simdi)
    _senkron_yaz(d)
    return {"gonderilen": len(yerel), "alinan": alinan, "cakismalar": cakismalar}


def esitle(settings, depo=None) -> dict | None:
    """Ayarlar bulut bağlantısı içeriyorsa görevleri eşitler; yoksa None. Hata yukarı (çağıran günlüğe yazar)."""
    i = ayarlardan(settings)
    if i is None:
        return None
    return gorevleri_esitle(depo or durum_mod.depo(), i)
