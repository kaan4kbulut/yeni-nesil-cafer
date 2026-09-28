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

import httpx

from .. import ayar, baglam, donanim, modeller, profil

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


# ---------------------------------------------------------------- K13: güç/donanıma göre cihaz, kademe, bağlam

SONDA_ISTEMI = "Sırayla say: bir, iki, üç, dört, beş, altı, yedi, sekiz, dokuz, on, on bir, on iki."  # sabit
SONDA_TOKEN = 32
SONDA_KAYIT_SAYISI = 60
GPU_CPU_ORANI = 1.5  # gpu tok/sn bunun altındaysa CPU'ya geçilir
SIRA = ("dusuk", "orta", "yuksek")
PIL_KADEME_TAVANI = "orta"
MIN_PIL_CTX = 4096
_sonda_hatasi = 0.0  # Ollama yanıtsızken her turda yeniden denenmez


def _olcum_dosyasi():
    return ayar.DATA_DIR / "donanim_olcum.json"


def donanim_olcumleri() -> list[dict]:
    """`DATA_DIR/donanim_olcum.json`: [{model, cihaz, fiste, tok_sn, yukleme_sn, tarih}] (eskiden yeniye)."""
    try:
        veri = json.loads(_olcum_dosyasi().read_text(encoding="utf-8"))
        return [o for o in veri if isinstance(o, dict)] if isinstance(veri, list) else []
    except (OSError, ValueError):
        return []


def _donanim_olcum_ekle(kayit: dict) -> None:
    with _kilit:
        liste = (donanim_olcumleri() + [kayit])[-SONDA_KAYIT_SAYISI:]
        _olcum_dosyasi().parent.mkdir(parents=True, exist_ok=True)
        gecici = _olcum_dosyasi().with_suffix(".tmp")
        gecici.write_text(json.dumps(liste, ensure_ascii=False, indent=1), encoding="utf-8")
        gecici.replace(_olcum_dosyasi())


def hizli_sonda(model: str, cihaz: str, ollama_url: str | None = None, fiste: bool | None = None) -> dict | None:
    """32 token'lık sabit istemle anlık hız: {model, cihaz, fiste, tok_sn, yukleme_sn, tarih}. cihaz "gpu" → normal,
    "cpu" → `num_gpu=0`. Sonucu `donanim_olcum.json`'a ekler. Yanıt yoksa/zaman aşımında None."""
    if cihaz not in ("gpu", "cpu"):
        raise ValueError(f"bilinmeyen cihaz: {cihaz}")
    url = (ollama_url or ayar.Settings.load().ollama_url).rstrip("/")
    secenek = {"num_predict": SONDA_TOKEN, "temperature": 0, **({"num_gpu": 0} if cihaz == "cpu" else {})}
    try:
        r = httpx.post(url + "/api/generate", json={"model": model, "prompt": SONDA_ISTEMI, "stream": False,
                                                    "options": secenek, "think": False},
                       timeout=httpx.Timeout(180 if cihaz == "cpu" else 90, connect=5))
        r.raise_for_status()
        v = r.json()
        sure = float(v.get("eval_duration") or 0) / 1e9
        tok_sn = round(int(v.get("eval_count") or 0) / sure, 2) if sure > 0 else 0.0
    except (httpx.HTTPError, ValueError, TypeError):
        return None
    if tok_sn <= 0:
        return None
    kayit = {"model": model, "cihaz": cihaz, "fiste": donanim.guc_durumu()["fiste"] if fiste is None else fiste,
             "tok_sn": tok_sn, "yukleme_sn": round(float(v.get("load_duration") or 0) / 1e9, 2),
             "tarih": time.strftime("%Y-%m-%dT%H:%M:%S")}
    _donanim_olcum_ekle(kayit)
    return kayit


def sonda_kos(gerekli: list[tuple[str, str]], bosta, ollama_url: str | None = None, en_cok: int = 2) -> list[dict]:
    """Eksik ölçümleri (model, cihaz) arka planda, YALNIZCA `bosta()` doğruyken koşar (en çok 2; her sondadan önce bakılır,
    sohbet başlarsa durur). Ollama yanıtsızsa 10 dk sessiz kalır."""
    global _sonda_hatasi
    yapilan = []
    if time.time() - _sonda_hatasi < 600:
        return yapilan
    for model, cihaz in gerekli[:en_cok]:
        if not bosta():
            break
        kayit = hizli_sonda(model, cihaz, ollama_url)
        if kayit is None:
            _sonda_hatasi = time.time()
            break
        yapilan.append(kayit)
    return yapilan


def son_olcum(olcumler: list[dict], model: str, cihaz: str, fiste: bool) -> float | None:
    """Bu model + cihaz + güç durumu için en son tok/sn (yoksa None)."""
    for o in reversed(olcumler):
        if o.get("model") == model and o.get("cihaz") == cihaz and bool(o.get("fiste")) == fiste and o.get("tok_sn"):
            return float(o["tok_sn"])
    return None


def kismi_gpu(boyut_mib: float, katman: int, vram_mib: float, kv_mib: float = 0.0) -> int | None:
    """Modelin GPU'ya konabilecek katman sayısı: tamamı sığıyorsa None (varsayılan), hiç sığmıyorsa 0, aksi hâlde
    kısmi. Pay: %15 + 1 GB (baglam.tahmin ile aynı)."""
    if katman <= 0 or boyut_mib <= 0 or not vram_mib:
        return None
    kullanilabilir = vram_mib * 0.85 - 1024 - kv_mib
    if kullanilabilir >= boyut_mib:
        return None
    return max(0, int(kullanilabilir / (boyut_mib / (katman + 1))))  # +1: çıkış katmanı


def donanim_karari(guc: dict, envanter: dict, olcumler: list[dict], *, model: str = "", model_ctx: int = 8192,
                   temel_kademe: str = "orta", model_bilgi: dict | None = None, uyandir=None,
                   yeniden_baslatildi: bool = False) -> dict:
    """Güç + kart + ölçümlerden {"cihaz", "kademe", "num_gpu", "num_ctx", "neden", "model", "fiste", "oneri",
    "olcum_gerekli"}. Saf (dış çağrı yalnızca `uyandir`): kurallar —
    pilde: yüksek kademe kapalı, bağlam yarıya · pil/güç sınırı kısıtlıysa ölçülen gpu tok/sn < 1.5 × cpu tok/sn → CPU ·
    dGPU uyuyorsa tek uyandırma, olmazsa CPU · VRAM'e sığmayan modelde kısmi `num_gpu` · Ollama kartı görmüyorsa
    yeniden başlatma önerisi (sonra hâlâ görmüyorsa CPU). Fişe takılınca aynı fonksiyon tam gücü verir."""
    fiste = bool(guc.get("fiste", True))
    kademe, ctx, nedenler = temel_kademe, model_ctx, []
    cihaz, num_gpu, oneri, gerekli = "gpu", None, None, []
    if not fiste:
        if kademe in SIRA and SIRA.index(kademe) > SIRA.index(PIL_KADEME_TAVANI):
            kademe = PIL_KADEME_TAVANI
        ctx = max(model_ctx // 2, MIN_PIL_CTX)
        nedenler.append("pilde")
    kart = (envanter.get("nvidia") or [None])[0]
    rocm = next((k for k in envanter.get("harici_diger") or [] if k.get("ollama_kullanabilir")), None)
    if not kart and not rocm:
        cihaz = "cpu"
        dahili = envanter.get("dahili") or []
        nedenler.append("Ollama'nın kullanabileceği ekran kartı yok"
                        + (" (dahili GPU'yu Ollama göremez)" if dahili else ""))
    elif envanter.get("uyuyor"):
        if not (uyandir and uyandir()):
            cihaz = "cpu"
            nedenler.append("ekran kartı uyuyor ve uyanmadı")
    if cihaz == "gpu" and envanter.get("ollama_gpu_gormuyor"):
        if yeniden_baslatildi:
            cihaz = "cpu"
            nedenler.append("Ollama yeniden başlatıldı ama kartı hâlâ görmüyor")
        else:
            oneri = "ollama_yeniden_baslat"
            nedenler.append("Ollama kartı görmüyor: yeniden başlatılması önerilir")
    if cihaz == "gpu" and kart and model:
        kisik = not fiste or (kart.get("kullanim_yuzde", 0) >= 50 and kart.get("sm_max_mhz")
                              and (kart.get("sm_mhz") or 0) < 0.6 * kart["sm_max_mhz"])
        if kisik:
            g, c = son_olcum(olcumler, model, "gpu", fiste), son_olcum(olcumler, model, "cpu", fiste)
            if g is None:
                gerekli.append((model, "gpu"))
            if c is None:
                gerekli.append((model, "cpu"))
            if g is not None and c is not None and g < GPU_CPU_ORANI * c:
                cihaz = "cpu"
                nedenler.append(f"kart güç sınırında yavaş ({g:.1f} tok/sn < {GPU_CPU_ORANI} × CPU {c:.1f})")
    if cihaz == "gpu" and kart and model_bilgi:
        kv = model_bilgi.get("kv_token_bayt", 0) * ctx / (1024 * 1024)
        n = kismi_gpu(model_bilgi.get("boyut_mib", 0), model_bilgi.get("katman", 0), kart.get("vram_toplam_mib", 0), kv)
        if n == 0:
            cihaz = "cpu"
            nedenler.append("model karta hiç sığmıyor")
        elif n is not None:
            num_gpu = n
            nedenler.append(f"model VRAM'e sığmıyor: {n} katman kartta")
    if cihaz == "cpu":
        if kart or rocm:
            num_gpu = 0
        if kademe in SIRA and SIRA.index(kademe) > SIRA.index(PIL_KADEME_TAVANI):
            kademe = PIL_KADEME_TAVANI
    return {"cihaz": cihaz, "kademe": kademe, "num_gpu": num_gpu, "num_ctx": int(ctx),
            "neden": "; ".join(nedenler) or "fişte, tam güç", "model": model, "fiste": fiste, "oneri": oneri,
            "olcum_gerekli": gerekli}


def durum_satiri(eski: dict | None, yeni: dict) -> str:
    """Tek satır durum metni: "Pile geçildi → orta kademe, 8K bağlam, GPU"."""
    if eski is None or eski.get("fiste") != yeni["fiste"]:
        onek = "Fişe takıldı" if yeni["fiste"] else "Pile geçildi"
    else:
        onek = "Donanım kararı değişti"
    cihaz = "CPU" if yeni["cihaz"] == "cpu" else ("GPU" if yeni["num_gpu"] is None else f"kısmi GPU ({yeni['num_gpu']} katman)")
    return f"{onek} → {profil.ADLAR.get(yeni['kademe'], yeni['kademe'])} kademe, {yeni['num_ctx'] // 1024}K bağlam, {cihaz}"


def otomatik_uyarla_acik(ayarlar=None) -> bool:
    """"Otomatik uyarla" anahtarı (varsayılan açık); kapalıyken kullanıcı kademeyi kendi seçer."""
    try:
        return bool((ayarlar or ayar.Settings.load()).extra.get("donanim_otomatik", True))
    except Exception:
        return True


_uyandirma = {"denendi": False}
_yeniden = {"baslatildi": False}


def _tek_uyandirma() -> bool:
    """Uyuyan kart için yalnızca BİR deneme; kart uyandığı görülene kadar tekrar denenmez."""
    if _uyandirma["denendi"]:
        return False
    _uyandirma["denendi"] = True
    return donanim.dgpu_uyandir()


def ollama_yeniden_baslatildi() -> None:
    """Kullanıcı onaylı yeniden başlatma yapıldı: bir sonraki kararda kart hâlâ görülmezse CPU."""
    _yeniden["baslatildi"] = True
    donanim.onbellek_temizle()


def uyarla(ayarlar, bildir=None, mesgul=None) -> dict | None:
    """Kararı hesaplar ve (istek sürmüyorsa) uygular: `donanim.karar_yaz` + kademe önbelleği + tek satır durum.
    Otomatik uyarlama kapalıysa önceki karar silinir. Döner: uygulanan yeni karar; değişiklik yoksa/ertelendiyse None."""
    if not otomatik_uyarla_acik(ayarlar):
        if donanim.karar():
            donanim.karar_yaz(None)
            profil._onbellek_temizle()
        return None
    env = donanim.gpu_envanteri()
    if not env.get("uyuyor"):
        _uyandirma["denendi"] = False
    if not env.get("ollama_gpu_gormuyor"):
        _yeniden["baslatildi"] = False
    model = getattr(ayarlar, "ollama_model", "") or ""
    url = getattr(ayarlar, "ollama_url", None) or "http://localhost:11434"
    tam_ctx = baglam.model_ctx(ayarlar) or int(getattr(ayarlar, "ollama_num_ctx", 0) or 8192)
    bilgi = baglam.model_boyutlari(url, model) if model and env.get("nvidia") else None
    yeni = donanim_karari(donanim.guc_durumu(), env, donanim_olcumleri(), model=model, model_ctx=tam_ctx,
                          temel_kademe=profil.temel_kademe(), model_bilgi=bilgi, uyandir=_tek_uyandirma,
                          yeniden_baslatildi=_yeniden["baslatildi"])
    eski = donanim.karar()
    anahtar = ("cihaz", "kademe", "num_gpu", "num_ctx")
    if eski and all(eski.get(a) == yeni[a] for a in anahtar):
        donanim.karar_yaz({**eski, "oneri": yeni["oneri"], "olcum_gerekli": yeni["olcum_gerekli"],
                           "neden": yeni["neden"]})
        return None
    if mesgul and mesgul():
        return None  # süren istek bitince (sonraki turda) uygulanır
    donanim.karar_yaz(yeni)
    profil._onbellek_temizle()
    if bildir and (eski is not None or not (yeni["fiste"] and yeni["cihaz"] == "gpu" and yeni["num_gpu"] is None)):
        try:
            bildir(durum_satiri(eski, yeni))
        except Exception:  # bildirim programı durdurmaz
            pass
    return yeni


class GucIzleyici(threading.Thread):
    """Arka plan: güç kaynağını `aralik_sn`'de (15) bir yoklar; değişince (ve `tam_tur` turda bir) `uyarla` çalışır,
    eksik ölçümler yalnızca boşta koşulur. `mesgul()` doğruyken karar ertelenir, sonda koşulmaz."""

    def __init__(self, ayarlar, bildir=None, mesgul=None, aralik_sn: float = 15, tam_tur: int = 4):
        super().__init__(daemon=True, name="guc-izleyici")
        self.ayarlar, self.bildir, self.mesgul = ayarlar, bildir, mesgul or (lambda: False)
        self.aralik_sn, self.tam_tur = aralik_sn, tam_tur
        self._dur = threading.Event()
        self._son_fiste: bool | None = None

    def dur(self) -> None:
        self._dur.set()

    def tur(self, sayac: int = 0) -> None:
        """Tek yoklama (testler doğrudan çağırır)."""
        fiste = donanim.guc_durumu(yenile=True)["fiste"]
        degisti = fiste != self._son_fiste
        self._son_fiste = fiste
        if degisti or sayac % self.tam_tur == 0 or (donanim.karar() or {}).get("neden") is None:
            donanim.gpu_envanteri(yenile=True)
            karar = uyarla(self.ayarlar, self.bildir, self.mesgul) or donanim.karar()
            if karar and karar.get("olcum_gerekli") and not self.mesgul():
                sonda_kos(karar["olcum_gerekli"], lambda: not self.mesgul(), getattr(self.ayarlar, "ollama_url", None))
                uyarla(self.ayarlar, self.bildir, self.mesgul)

    def run(self) -> None:
        sayac = 0
        while not self._dur.is_set():
            try:
                self.tur(sayac)
            except Exception as e:  # izleyici asla ölmez
                _gunluk.info("güç izleyici turu başarısız: %s", e)
            sayac += 1
            self._dur.wait(self.aralik_sn)


def donanim_ozeti() -> str:
    """Arayüzdeki "Donanım" bölümü için çok satırlı metin (alt süreç açar: arka planda çağrılır)."""
    guc, env = donanim.guc_durumu(), donanim.gpu_envanteri()
    satir = ["Güç: " + ("fişte" if guc["fiste"] else "pilde") + (f" · pil %{guc['pil_yuzde']}" if guc["pil_yuzde"] is not None else "")]
    for k in env["nvidia"]:
        satir.append(f"Ayrı kart: {k['ad']} · güç sınırı {k['guc_siniri_w'] if k['guc_siniri_w'] is not None else '?'} W · "
                     f"pstate {k['pstate']} · saat {k['sm_mhz'] or '?'}/{k['sm_max_mhz'] or '?'} MHz · kullanım %{k['kullanim_yuzde']}")
    if env["nvidia_zaman_asimi"]:
        satir.append("Ayrı kart: nvidia-smi yanıt vermedi (kart uyuyor olabilir)")
    for k in env["dahili"]:
        satir.append(f"Dahili kart: {k['ad']} (Ollama kullanamaz)")
    if env["hibrit"]:
        satir.append("Hibrit grafik: evet" + (" · ayrı kart uyuyor" if env["uyuyor"] else ""))
    if env["ollama"]:
        satir.append("Ollama: " + ", ".join(f"{m['model']} %{m['cpu_yuzde']} CPU / %{m['gpu_yuzde']} GPU" for m in env["ollama"]))
        if env["ollama_gpu_gormuyor"]:
            satir.append("⚠ Kart sağlam ama Ollama modeli tamamen CPU'da çalıştırıyor")
    k = donanim.karar()
    satir.append(f"Seçili cihaz: {'CPU' if k and k['cihaz'] == 'cpu' else 'GPU'}"
                 + (f" · {profil.ADLAR.get(k['kademe'], k['kademe'])} kademe · {k['num_ctx'] // 1024}K bağlam · {k['neden']}"
                    if k else " · (otomatik uyarlama kapalı ya da henüz karar yok)"))
    son = donanim_olcumleri()[-3:]
    satir.append("Son ölçüm: " + (" · ".join(f"{o['model']} {o['cihaz'].upper()} {o['tok_sn']} tok/sn "
                                            f"({'fişte' if o['fiste'] else 'pilde'})" for o in son) if son else "yok"))
    return "\n".join(satir)
