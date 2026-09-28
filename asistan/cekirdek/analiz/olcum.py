"""Ölçüm (MIMARI §8, K7): model başına hız (tok/sn, ilk token — `profil.benchmark`), başarı oranı (doğrulayıcıdan),
süre; kademe otomatik ayarı; sınav sonuçlarının yönlendirmeye geri beslenmesi.

Veriler: hız `profil.json → benchmark` (profil.py yazar), başarı/süre ve sınav özetleri `DATA_DIR/olcum.json`.
Kademe otomatik ayarı yalnızca kilit YOKKEN: sonucu `profil.json → kademe.otomatik` (ölçülen kademe silinmez,
kullanıcı görür); `profil.kademe()` kilit → otomatik → ölçülen sırasıyla okur.
"""

import json
import logging
import threading
import time

from .. import ayar, modeller, profil

_gunluk = logging.getLogger(__name__)
_kilit = threading.Lock()
YAVAS_TOK_SN = profil.YAVAS_TOK_SN  # 3.0: altı "bu kademe için yavaş" (MIMARI §8)
HIZLI_TOK_SN = 3 * YAVAS_TOK_SN  # üst kademenin varsayılan modeli bu hızda ve kartta ise yükselt
SINAV_ESIGI = 0.5  # (kademe × görev türü) başarı bunun altındaysa "hızlı" rol yerine "yönetici" tercih edilir
ALT = {"yuksek": "orta", "orta": "dusuk"}
UST = {"dusuk": "orta", "orta": "yuksek"}


def _dosya():
    return ayar.DATA_DIR / "olcum.json"


def _oku() -> dict:
    try:
        veri = json.loads(_dosya().read_text(encoding="utf-8"))
        return veri if isinstance(veri, dict) else {}
    except (OSError, ValueError):
        return {}


def _yaz(veri: dict) -> None:
    _dosya().parent.mkdir(parents=True, exist_ok=True)
    gecici = _dosya().with_suffix(".tmp")
    gecici.write_text(json.dumps(veri, ensure_ascii=False, indent=1), encoding="utf-8")
    gecici.replace(_dosya())


# ---------------------------------------------------------------- başarı ve süre (doğrulayıcıdan)

def basari_kaydet(saglayici: str, model: str, gecti: bool, sure_sn: float = 0.0) -> None:
    """Bir model adımının doğrulayıcı sonucu (yürütücü her model adımında çağırır)."""
    if not saglayici or not model:
        return
    anahtar = f"{saglayici}/{model}"
    with _kilit:
        veri = _oku()
        m = veri.setdefault("modeller", {}).setdefault(anahtar, {"basari": 0, "toplam": 0, "sure_toplam": 0.0})
        m["toplam"] += 1
        m["basari"] += int(bool(gecti))
        m["sure_toplam"] = round(float(m.get("sure_toplam") or 0) + float(sure_sn or 0), 2)
        m["son"] = time.strftime("%Y-%m-%dT%H:%M:%S")
        try:
            _yaz(veri)
        except OSError as e:
            _gunluk.warning("olcum.json yazılamadı: %s", e)


def basari_orani(saglayici: str, model: str) -> tuple[float | None, int]:
    """(oran, toplam); hiç kayıt yoksa (None, 0)."""
    m = (_oku().get("modeller") or {}).get(f"{saglayici}/{model}") or {}
    toplam = int(m.get("toplam") or 0)
    return (m["basari"] / toplam if toplam else None), toplam


def model_ozeti(saglayici: str, model: str) -> dict:
    """Arayüz: {"tok_sn", "ilk_token_ms", "basari", "toplam", "ort_sure_sn"} (bilinmeyenler None)."""
    b = ((profil.yukle() or {}).get("benchmark") or {}).get(model) or {} if saglayici == "ollama" else {}
    oran, toplam = basari_orani(saglayici, model)
    m = (_oku().get("modeller") or {}).get(f"{saglayici}/{model}") or {}
    return {"tok_sn": b.get("tok_sn"), "ilk_token_ms": b.get("ilk_token_ms"), "basari": oran, "toplam": toplam,
            "ort_sure_sn": (round(m["sure_toplam"] / toplam, 1) if toplam and m.get("sure_toplam") else None)}


# ---------------------------------------------------------------- hız (benchmark, profil.py'ye devreder)

def benchmark(modeller_: list[str] | None = None, ollama_url: str | None = None, **k) -> dict:
    return profil.benchmark(modeller_, ollama_url, **k)


def hizlar() -> dict:
    """model → tok/sn (ölçülmüş olanlar)."""
    return {m: float(s["tok_sn"]) for m, s in ((profil.yukle() or {}).get("benchmark") or {}).items()
            if isinstance(s, dict) and s.get("tok_sn")}


def varsayilan_yerel(kademe: str) -> str:
    return (modeller.kademe_modelleri(kademe)["yerel"] or [""])[0]


def ilk_olcum_gerekli(kademe: str | None = None) -> str:
    """İlk kullanımda 30 sn benchmark: etkin kademenin varsayılan yerel modeli ölçülmemişse adı, yoksa boş."""
    model = varsayilan_yerel(kademe or profil.kademe())
    return model if model and model not in hizlar() else ""


# ---------------------------------------------------------------- kademe otomatik ayarı (MIMARI §8)

def kademe_onerisi(kayit: dict | None = None) -> tuple[str | None, str]:
    """Ölçülen kademeye göre öneri: varsayılan yerel model yavaşsa (< 3 tok/sn) bir alt kademe; üst kademenin
    varsayılan modeli hızlı (≥ 9 tok/sn) ve karta sığıyorsa (≥ %90) bir üst kademe. (kademe | None, neden)."""
    kayit = kayit if kayit is not None else (profil.yukle() or {})
    k = kayit.get("kademe") or {}
    olculen = k.get("olculen")
    if olculen not in ("dusuk", "orta", "yuksek"):
        return None, ""
    tablo = kayit.get("benchmark") or {}
    model = varsayilan_yerel(olculen)
    s = tablo.get(model) or {}
    if model and s.get("tok_sn") is not None and float(s["tok_sn"]) < YAVAS_TOK_SN and olculen in ALT:
        return ALT[olculen], (f"{model} bu bilgisayarda {s['tok_sn']} tok/sn (< {YAVAS_TOK_SN:.0f}): "
                              f"{profil.ADLAR[olculen]} kademesinin varsayılanları çok yavaş")
    ust = UST.get(olculen)
    if ust:
        ust_model = varsayilan_yerel(ust)
        su = tablo.get(ust_model) or {}
        if ust_model and su.get("tok_sn") and float(su["tok_sn"]) >= HIZLI_TOK_SN and int(su.get("kartta_yuzde") or 0) >= 90:
            return ust, (f"{ust_model} bu bilgisayarda {su['tok_sn']} tok/sn ve tamamen kartta: "
                         f"{profil.ADLAR[ust]} kademesinin varsayılanları rahat çalışır")
    return None, ""


def kademe_ayarla(bildir=None) -> str | None:
    """Öneriyi uygular (kilit varsa dokunmaz): `profil.json → kademe.otomatik`; değişince `bildir(metin)`.
    Döner: etkinleşen otomatik kademe ya da None (değişiklik yok / kilitli)."""
    if profil.kilit():
        return None
    kayit = profil.yukle()
    if not kayit:
        return None
    k = kayit.setdefault("kademe", {})
    yeni, neden = kademe_onerisi(kayit)
    eski = k.get("otomatik")
    if yeni == eski:
        return None
    if yeni:
        k["otomatik"], k["otomatik_neden"] = yeni, neden
        metin = f"Kademe {profil.ADLAR[k.get('olculen', yeni)]} → {profil.ADLAR[yeni]}: {neden}"
    else:
        k.pop("otomatik", None)
        k.pop("otomatik_neden", None)
        metin = f"Kademe ölçülen değere döndü ({profil.ADLAR.get(k.get('olculen'), '?')})"
    k["etkin"] = k.get("kilitli") or yeni or k.get("olculen")
    profil.kaydet(kayit)
    profil._onbellek_temizle()
    if bildir:
        try:
            bildir(metin)
        except Exception:  # bildirim programı durdurmaz
            pass
    return yeni


def acilis(ollama_url: str | None = None, bildir=None, sure_sn: float | None = None) -> dict:
    """Açılış ölçümü (arka planda): varsayılan yerel model ölçülmemişse 30 sn benchmark, sonra kademe ayarı.
    Ollama kapalıysa sessizce geçer. Döner: {"olculen": model|"", "kademe": yeni|None}."""
    sonuc = {"olculen": "", "kademe": None}
    model = ilk_olcum_gerekli()
    if model:
        try:
            profil.benchmark([model], ollama_url, **({"sure_sn": sure_sn} if sure_sn else {}))
            sonuc["olculen"] = model
        except Exception as e:  # Ollama yok / ağ yok: ölçüm bir sonraki açılışa kalır
            _gunluk.info("açılış ölçümü yapılamadı (%s): %s", model, e)
    sonuc["kademe"] = kademe_ayarla(bildir)
    return sonuc


# ---------------------------------------------------------------- sınav → yönlendirme (MIMARI §8 son madde)

def sinav_geri_besle(kayitlar: list[dict], kademe: str) -> dict:
    """Sınav koşusunun kayıtları (`gecti`, `tur`) → `olcum.json → sinav[kademe][tur] = {gecen, toplam}` (üstüne yazar:
    her koşu o kademe × tür için en son ölçümdür). Döner: yazılan tablo."""
    tablo: dict[str, dict] = {}
    for s in kayitlar:
        tur = str(s.get("tur") or "")
        if not tur:
            continue
        t = tablo.setdefault(tur, {"gecen": 0, "toplam": 0})
        t["toplam"] += 1
        t["gecen"] += int(bool(s.get("gecti")))
    if not tablo:
        return {}
    with _kilit:
        veri = _oku()
        veri.setdefault("sinav", {}).setdefault(kademe, {}).update(tablo)
        veri["sinav"][kademe]["_zaman"] = time.strftime("%Y-%m-%dT%H:%M:%S")
        _yaz(veri)
    return tablo


def sinav_tablosu() -> dict:
    return _oku().get("sinav") or {}


def tercih_rolu(kademe: str, gorev_turu: str) -> str | None:
    """Yönlendirmeye geri besleme: bu kademede bu görev türü sınavda %50'nin altında kaldıysa ve varsayılan rolü
    `hizli` ise `yonetici`; aksi hâlde None (varsayılan tablo)."""
    from .. import yonlendirici

    if yonlendirici.GOREV_ROLU.get(gorev_turu) != "hizli":
        return None
    t = ((sinav_tablosu().get(kademe) or {}).get(gorev_turu)) or {}
    toplam = int(t.get("toplam") or 0)
    if toplam and t.get("gecen", 0) / toplam < SINAV_ESIGI:
        return "yonetici"
    return None
