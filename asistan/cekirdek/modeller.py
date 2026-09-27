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


@lru_cache(maxsize=1)
def _ham() -> dict:
    return json.loads(DOSYA.read_text(encoding="utf-8"))


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
