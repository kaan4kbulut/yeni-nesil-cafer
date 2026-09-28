"""Hata analizi (MIMARI §7, SEMALAR §3): başarısız adım → sınıf → eylem.

Sınıflandırma önce desenle (`DESENLER`; kullanıcı klasöründeki `hata_desenleri.json` ile genişler, `/hata-analiz`
`desen_ekle` ile yazar), desen tutmazsa `hizli` rolündeki modele şema-kısıtlı tek soru; o da olmazsa `mantik`.
`isle()` kaydı tamamlar (sınıf, eylem, hedef), `DATA_DIR/hatalar.jsonl`'e yazar ve döndürür; eylemi UYGULAMAZ —
uygulayan yürütücü (`gorev/yurutucu.py`): kur/üret onaylı, yeniden planlama en çok 2, ağ 3 deneme.
"""

import json
import logging
import re
import time

from .. import ayar

_gunluk = logging.getLogger(__name__)

SINIFLAR = ("model_yetersiz", "eksik_bagimlilik", "eksik_yetenek", "izin", "ag", "mantik", "veri", "kaynak")

# sınıf → eylem (MIMARI §7 tablosu). `onay`: "sor" → kullanıcı onaylamadan yapılmaz (guvenlik.toml → kurulum)
EYLEMLER = {
    "model_yetersiz": {"tip": "yukselt", "aciklama": "bir üst model; hâlâ olmuyorsa görev parçalanır"},
    "eksik_bagimlilik": {"tip": "kur", "onay": "sor", "aciklama": "eksik paket/program kurulur, adım tekrar"},
    "eksik_yetenek": {"tip": "uret", "onay": "sor", "aciklama": "katalogda ara, yoksa yetenek üret (sandbox test), adım tekrar"},
    "izin": {"tip": "sor", "aciklama": "kullanıcıya net soru; sunucuda bildirim"},
    "ag": {"tip": "tekrar", "deneme": 3, "bekleme_sn": [1, 2, 4], "aciklama": "üstel bekleme ile 3 deneme, sonra çevrimdışı"},
    "mantik": {"tip": "yeniden_planla", "en_cok": 2, "aciklama": "başarısız çıktı bağlama eklenip yeniden planlanır"},
    "veri": {"tip": "bildir", "aciklama": "hangi verinin eksik/bozuk olduğu kullanıcıya söylenir"},
    "kaynak": {"tip": "kucult", "aciklama": "daha küçük model, kısa bağlam, kademe düşürme"},
}

# sıra önemli: ilk eşleşen sınıf (bağımlılık > yetenek > izin > ağ > kaynak > veri > model)
DESENLER: list[tuple[str, re.Pattern]] = [
    ("eksik_bagimlilik", re.compile(r"ModuleNotFoundError|No module named|command not found|not recognized as an internal"
                                    r"|\.so\b: cannot open|\.dll\b|Python paketi kurulu değil|programı kurulu değil"
                                    r"|kurulu değil: |pip paketi|ImportError: cannot import", re.I)),
    ("eksik_yetenek", re.compile(r"adlı yetenek yok|yetene[ğg]i(m)? yok|eksik yetenek|no (such )?capability"
                                 r"|bunu yapacak (araç|yetenek)|kayıtlı yetenek(ler)? arasında yok", re.I)),
    ("izin", re.compile(r"declined|reddetti|Permission denied|EACCES|\b(izin|izni|onay)\b|REFUSED|BLOCKED"
                        r"|not permitted|yasak", re.I)),
    ("ag", re.compile(r"Timeout|timed out|ConnectError|ConnectionError|zaman aşımı|bağlanılamadı|Name or service not known"
                      r"|DNS|\bHTTP[ /]?5\d\d\b|\b5\d\d (Internal Server Error|Bad Gateway|Service Unavailable|Gateway Timeout)"
                      r"|status(?:_code)?[=: ]+5\d\d\b|çevrimdışı|network is unreachable|SSL", re.I)),
    ("kaynak", re.compile(r"MemoryError|out of memory|No space left|CUDA (error|out of memory)|cudaError|CUBLAS_STATUS_ALLOC"
                          r"|bellek yetersiz|disk dolu|karta sığm|context length|too many tokens", re.I)),
    ("veri", re.compile(r"No such file|FileNotFoundError|(dosya|klasör|dizin) bulunamadı|dosya yok|UnicodeDecodeError"
                        r"|JSONDecodeError|girdi (bozuk|eksik)|boş dosya|is not UTF-8|IsADirectoryError|geçersiz (girdi|değer)",
                        re.I)),
    ("model_yetersiz", re.compile(r"şemaya uymuyor|JSON nesnesi yok|plan yazılamadı|model cevap veremedi|boş cevap"
                                  r"|model yetersiz|anlamsız çıktı|halüsinasyon", re.I)),
]

SEMA = {"type": "object", "properties": {"sinif": {"type": "string", "enum": list(SINIFLAR)}},
        "required": ["sinif"]}
SISTEM = ("Classify a failed task step into exactly one error class. Classes: model_yetersiz (empty/nonsense model "
          "output), eksik_bagimlilik (missing package/program), eksik_yetenek (no capability for the job), izin "
          "(permission denied), ag (network/timeout/5xx), mantik (output exists but criterion unmet), veri (input "
          "missing/broken), kaynak (RAM/VRAM/disk). Answer with one JSON object only.")

_PAKET = re.compile(r"No module named '?([A-Za-z0-9_.\-]+)|Python paketi kurulu değil: ([A-Za-z0-9_.\-]+)"
                    r"|ImportError: cannot import name .* from '([A-Za-z0-9_.]+)'")
_IKILI = re.compile(r"'([A-Za-z0-9_.\-]+)' programı kurulu değil|(?:bash: )?([A-Za-z0-9_.\-]+): command not found"
                    r"|'([A-Za-z0-9_.\-]+)' is not recognized")
_YETENEK = re.compile(r"'([a-z0-9_]+)' adlı yetenek yok|yetenek(?:ler)?: ([a-z0-9_]+)")


def _desen_dosyasi():
    return ayar.DATA_DIR / "hata_desenleri.json"


def _kutuk_dosyasi():
    return ayar.DATA_DIR / "hatalar.jsonl"


def ek_desenler() -> list[tuple[str, re.Pattern]]:
    """Kullanıcı klasöründeki ek desenler (`desen_ekle` ile yazılır; bozuk satır atlanır)."""
    try:
        veri = json.loads(_desen_dosyasi().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    sonuc = []
    for kayit in veri if isinstance(veri, list) else []:
        try:
            if kayit.get("sinif") in SINIFLAR:
                sonuc.append((kayit["sinif"], re.compile(kayit["desen"], re.I)))
        except (re.error, AttributeError, TypeError):
            continue
    return sonuc


def desen_ekle(sinif: str, desen: str, not_: str = "") -> None:
    """Sınıflandırıcıya kalıcı desen (`/hata-analiz` 4. adım). Geçersiz sınıf ya da regex `ValueError`."""
    if sinif not in SINIFLAR:
        raise ValueError(f"bilinmeyen sınıf: {sinif}")
    re.compile(desen)
    try:
        veri = json.loads(_desen_dosyasi().read_text(encoding="utf-8"))
        veri = veri if isinstance(veri, list) else []
    except (OSError, ValueError):
        veri = []
    if any(k.get("sinif") == sinif and k.get("desen") == desen for k in veri):
        return
    veri.append({"sinif": sinif, "desen": desen, "not": not_, "zaman": time.strftime("%Y-%m-%d")})
    from .. import ayar

    ayar.atomik_yaz(_desen_dosyasi(), json.dumps(veri, ensure_ascii=False, indent=1))  # K12-C1


def desenle(metin: str) -> str | None:
    """Yalnızca desenle sınıf; tutmazsa None."""
    for sinif, desen in ek_desenler() + DESENLER:
        if desen.search(metin):
            return sinif
    return None


def siniflandir(belirti: str, kanit: str = "", model_adimi: bool = False, model=None) -> str:
    """Sınıf: desen → (model adımı ve boş sonuç: model_yetersiz) → hızlı model → `mantik`."""
    metin = f"{belirti}\n{kanit}"
    sinif = desenle(metin)
    if sinif:
        return sinif
    if model_adimi and not (kanit or "").strip():
        return "model_yetersiz"
    if model is not None:
        try:
            cevap = model("siniflandirma", [{"role": "user", "content": f"Failure: {belirti[:500]}\n\nEvidence:\n"
                                                                        f"{(kanit or '')[:1500]}"}], SISTEM, SEMA)
            if cevap.veri and cevap.veri.get("sinif") in SINIFLAR:
                return cevap.veri["sinif"]
        except Exception as e:  # sınıflandırma programı durdurmaz
            _gunluk.info("hata sınıflandırma modeli cevap veremedi: %s", e)
    return "mantik"


def hedef(sinif: str, belirti: str, kanit: str = "") -> str:
    """Eylemin hedefi: `pip:<paket>`, `ikili:<program>`, `yetenek:<ad>`; bilinmiyorsa boş."""
    metin = f"{belirti}\n{kanit}"
    if sinif == "eksik_bagimlilik":
        m = _PAKET.search(metin)
        if m:
            return "pip:" + next(g for g in m.groups() if g).split(".")[0]
        m = _IKILI.search(metin)
        if m:
            return "ikili:" + next(g for g in m.groups() if g)
    if sinif == "eksik_yetenek":
        m = _YETENEK.search(metin)
        if m:
            return "yetenek:" + next(g for g in m.groups() if g)
    return ""


def eylem(sinif: str, belirti: str = "", kanit: str = "") -> dict:
    """SEMALAR §3 `eylem`: {"tip", "hedef", "onay"} (+ tablo bilgileri)."""
    e = dict(EYLEMLER.get(sinif) or EYLEMLER["mantik"])
    e["hedef"] = hedef(sinif, belirti, kanit)
    e.setdefault("onay", "yok")
    return e


def isle(kayit: dict, model=None) -> dict:
    """Hata kaydını tamamlar (sınıf, eylem), kütüğe yazar, döndürür. `yonlendirici.devret` ve yürütücü çağırır."""
    belirti, kanit = str(kayit.get("belirti") or ""), str(kayit.get("kanit") or "")
    if kayit.get("sinif") not in SINIFLAR or kayit.get("sinif") == "mantik":
        kayit["sinif"] = siniflandir(belirti, kanit, bool(kayit.get("model_adimi")), model)
    kayit["eylem"] = eylem(kayit["sinif"], belirti, kanit)
    kayit.setdefault("sonuc", "vazgecildi")
    kayit.setdefault("zaman", time.strftime("%Y-%m-%dT%H:%M:%S%z"))
    try:
        _kutuk_dosyasi().parent.mkdir(parents=True, exist_ok=True)
        with _kutuk_dosyasi().open("a", encoding="utf-8") as f:
            f.write(json.dumps({k: v for k, v in kayit.items() if k != "model_adimi"}, ensure_ascii=False) + "\n")
    except OSError as e:
        _gunluk.warning("hata kütüğü yazılamadı: %s", e)
    return kayit


def kutuk(son: int = 50) -> list[dict]:
    """Son hata kayıtları (yeniden eskiye)."""
    try:
        satirlar = _kutuk_dosyasi().read_text(encoding="utf-8").splitlines()
    except OSError:
        return []
    sonuc = []
    for s in reversed(satirlar[-son:]):
        try:
            sonuc.append(json.loads(s))
        except ValueError:
            continue
    return sonuc
