"""Model adlarının tek kaynağı: `asistan/ayar/modeller.json` (docs/MIMARI.md §3).

Kod model adı içermez; her modül adı buradan okur. Dosya pakette gelir (aktarma, güncelleme ve kurulum paketi
`asistan/` klasörünü taşır). Kademe listeleri `kademe_modelleri`, roller `rol` ile okunur.
"""

import copy
import json
from functools import lru_cache
from pathlib import Path

DOSYA = Path(__file__).resolve().parent.parent / "ayar" / "modeller.json"
KADEMELER = ("dusuk", "orta", "yuksek", "sunucu")


UST_ANAHTARLAR = ("kademe", "varsayilan", "onerilen", "guncelleme")  # kullanıcı katmanının ezebildikleri


def ust_dosya() -> Path:
    """Kullanıcı katmanı (K7 Modeller penceresi: varsayılanı değiştir, listeyi yenile): `DATA_DIR/modeller.json`.
    Güncelleme paketi programın dosyasını değiştirir, kullanıcının seçimleri burada kalır."""
    from .ayar import DATA_DIR

    return DATA_DIR / "modeller.json"


def _birlestir(taban: dict, ust: dict) -> dict:
    for anahtar in UST_ANAHTARLAR:
        if anahtar not in ust:
            continue
        if isinstance(taban.get(anahtar), dict) and isinstance(ust[anahtar], dict):
            for k, v in ust[anahtar].items():
                if isinstance(taban[anahtar].get(k), dict) and isinstance(v, dict):
                    taban[anahtar][k] = {**taban[anahtar][k], **v}
                else:
                    taban[anahtar][k] = v
        else:
            taban[anahtar] = ust[anahtar]
    return taban


@lru_cache(maxsize=1)
def _ham() -> dict:
    veri = json.loads(DOSYA.read_text(encoding="utf-8"))
    try:
        ust = json.loads(ust_dosya().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return veri
    return _birlestir(veri, ust) if isinstance(ust, dict) else veri


def ust_yaz(degisiklik: dict) -> None:
    """Kullanıcı katmanına yazar (yalnızca UST_ANAHTARLAR; iç sözlükler birleştirilir) ve önbelleği tazeler."""
    yol = ust_dosya()
    try:
        ust = json.loads(yol.read_text(encoding="utf-8"))
        ust = ust if isinstance(ust, dict) else {}
    except (OSError, ValueError):
        ust = {}
    _birlestir(ust, {k: v for k, v in degisiklik.items() if k in UST_ANAHTARLAR})
    yol.parent.mkdir(parents=True, exist_ok=True)
    yol.write_text(json.dumps(ust, ensure_ascii=False, indent=1), encoding="utf-8")
    yenile()


def varsayilan_yap(kademe: str, model: str, yerel: bool = True) -> None:
    """Kademe listesinde modeli başa alır (listede yoksa ekler); yerel ise `varsayilan.ollama` da o olur."""
    if kademe not in KADEMELER:
        raise ValueError(f"bilinmeyen kademe: {kademe}")
    tur = "yerel" if yerel else "bulut"
    liste = [m for m in kademe_modelleri(kademe)[tur] if m != model]
    degisiklik = {"kademe": {kademe: {tur: [model] + liste}}}
    if yerel:
        degisiklik["varsayilan"] = {"ollama": model}
    ust_yaz(degisiklik)


def yukle() -> dict:
    """Dosyanın tamamı (kopya: çağıran değiştirse de önbellek bozulmaz)."""
    return copy.deepcopy(_ham())


def deger(yol: str, varsayilan=None):
    """Noktalı yolla tek değer: `deger("temel.model")`, `deger("kategoriler.kucuk")`."""
    dugum = _ham()
    for parca in yol.split("."):
        if not isinstance(dugum, dict) or parca not in dugum:
            return varsayilan
        dugum = dugum[parca]
    return copy.deepcopy(dugum)


def kademe_modelleri(kademe: str) -> dict:
    """{"yerel": [...], "bulut": [...]} — bilinmeyen kademe için boş listeler."""
    liste = _ham().get("kademe", {}).get(kademe) or {}
    return {"yerel": list(liste.get("yerel", [])), "bulut": list(liste.get("bulut", []))}


def rol(ad: str) -> str:
    """Rolün tanımı (`yonetici`, `hizli`, `kod`); seçimin kendisi yönlendiricinin işi (K3)."""
    return str(_ham().get("roller", {}).get(ad, ""))


def yenile() -> None:
    """Dosya değiştiyse sonraki okumada yeniden yüklensin (testler ve K7 'listeyi yenile')."""
    _ham.cache_clear()
