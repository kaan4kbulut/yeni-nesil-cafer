"""Sınav görevlerinin tanımı ve denetimleri: hepsi KODLA, model kararı yok (YAPILACAKLAR Aşama 1).

Görev dosyası `gorevler/<ad>.json`: ad, sira, istek, etiketler, zaman_siniri_sn, bitti (denetim listesi) ve isteğe bağlı
ekler, onceki_mesajlar, yeni_sohbette, gecmis, hazirla. Denetim: {"tur": "<tür>", ...}; yollar iş klasörüne görelidir,
`*` içeren yol kalıptır (ör. `*.stl`, adı bilinmeyen çıktı). Bu modül arayüzü ve programı yüklemez: çalıştırıcı
(calistir.py) ve birim testi (testler/test_sinav.py) ikisi de kullanır.
"""

import fnmatch
import json
import re
import subprocess
import sys
from pathlib import Path

SINAV = Path(__file__).resolve().parent
GOREVLER = SINAV / "gorevler"
EKLER = SINAV / "ekler"
BETIKLER = SINAV / "betikler"

AGIR = {"internet", "gpu", "motor", "uzun"}  # --hizli bunları atlar; hiçbiri yoksa görev "hizli"
ALANLAR = {"ad", "sira", "istek", "ekler", "onceki_mesajlar", "yeni_sohbette", "gecmis", "hazirla", "etiketler",
           "zaman_siniri_sn", "bitti"}
CJK = re.compile(r"[぀-ヿ㐀-䶿一-鿿가-힯豈-﫿]")
# denetim türü → zorunlu alanlar
TURLER = {
    "dosya_var": {"yol"}, "dosya_icerir": {"yol"}, "dosya_satir_sayisi": {"yol", "en_az"}, "stl_kapali": {"yol"},
    "cevap_icerir": set(), "cevap_icermez": set(), "cevap_en_cok_kelime": {"n"}, "arac_cagrildi": {"ad"},
    "arac_cagrilmadi": {"ad"}, "plan_dili_turkce": set(), "python_denetim": {"betik"},
}
_METIN_YA_DA_REGEX = {"dosya_icerir", "cevap_icerir", "cevap_icermez"}

# STL denetimi ajanların Python'unda (trimesh orada): ölçü, kapalılık, parça sayısı, hacim
_STL_BETIGI = r"""
import json, sys
import trimesh
m = trimesh.load(sys.argv[1], force="mesh")
kapali = bool(m.is_watertight)
print(json.dumps({"kapali": kapali, "olcu": [float(x) for x in m.extents],
                  "parca": len(m.split(only_watertight=False)), "hacim": float(m.volume) if kapali else None}))
"""


def etiketler(gorev: dict) -> set:
    return set(gorev.get("etiketler") or [])


def hizli_mi(gorev: dict) -> bool:
    return not (etiketler(gorev) & AGIR)


def yukle(klasor: Path = GOREVLER) -> list[dict]:
    """Görevler sıra numarasıyla; bozuk dosya hata verir (sessizce atlanmaz)."""
    gorevler = []
    for yol in sorted(klasor.glob("*.json")):
        gorev = json.loads(yol.read_text(encoding="utf-8"))
        hatalar = dogrula(gorev, yol.stem)
        if hatalar:
            raise ValueError(f"{yol.name}: " + "; ".join(hatalar))
        gorevler.append(gorev)
    return sorted(gorevler, key=lambda g: g["sira"])


def dogrula(gorev: dict, dosya_adi: str = "") -> list[str]:
    """Görev tanımındaki hatalar (boş liste = geçerli)."""
    h = []
    for alan in ("ad", "sira", "istek", "zaman_siniri_sn", "bitti"):
        if alan not in gorev:
            h.append(f"{alan} yok")
    if h:
        return h
    if dosya_adi and gorev["ad"] != dosya_adi:
        h.append(f"dosya adı ({dosya_adi}) ile ad ({gorev['ad']}) aynı değil")
    if set(gorev) - ALANLAR:
        h.append("bilinmeyen alan: " + ", ".join(sorted(set(gorev) - ALANLAR)))
    if etiketler(gorev) - AGIR:
        h.append("bilinmeyen etiket: " + ", ".join(sorted(etiketler(gorev) - AGIR)))
    if not isinstance(gorev["zaman_siniri_sn"], int) or gorev["zaman_siniri_sn"] <= 0:
        h.append("zaman_siniri_sn pozitif tam sayı olmalı")
    for ek in gorev.get("ekler") or []:
        if not (EKLER / ek).is_file():
            h.append(f"ek yok: ekler/{ek}")
    if gorev.get("gecmis") and not (EKLER / gorev["gecmis"]).is_file():
        h.append(f"geçmiş dosyası yok: ekler/{gorev['gecmis']}")
    for hz in gorev.get("hazirla") or []:
        if not str(hz.get("hedef", "")).startswith(("{is}/", "{proje}/")):
            h.append("hazirla.hedef {is}/ ya da {proje}/ ile başlamalı")
        if "kaynak" in hz and not (EKLER / hz["kaynak"]).exists():
            h.append(f"hazırlık kaynağı yok: ekler/{hz['kaynak']}")
        if ("kaynak" in hz) == ("metin" in hz):
            h.append("hazirla: ya kaynak ya metin")
    if not gorev["bitti"]:
        h.append("bitti boş")
    for d in gorev["bitti"]:
        tur = d.get("tur")
        if tur not in TURLER:
            h.append(f"bilinmeyen denetim: {tur}")
            continue
        if TURLER[tur] - set(d):
            h.append(f"{tur}: eksik alan " + ", ".join(sorted(TURLER[tur] - set(d))))
        if tur in _METIN_YA_DA_REGEX and ("metin" in d) == ("regex" in d):
            h.append(f"{tur}: ya metin ya regex")
        if tur == "python_denetim" and not (BETIKLER / d["betik"]).is_file():
            h.append(f"betik yok: betikler/{d['betik']}")
    return h


def bul(is_klasoru: Path, yol: str) -> list[Path]:
    """Yol ya da kalıp (`*`); kalıp klasörde yoksa alt klasörlerde de aranır (ekler/ hariç)."""
    if not any(c in yol for c in "*?["):
        p = is_klasoru / yol
        return [p] if p.is_file() else []
    bulunan = sorted(p for p in is_klasoru.glob(yol) if p.is_file())
    if not bulunan and "/" not in yol:
        bulunan = sorted(p for p in is_klasoru.rglob(yol)
                         if p.is_file() and "ekler" not in p.relative_to(is_klasoru).parts)
    return bulunan


def _eslesir(metin: str, d: dict) -> bool:
    if "regex" in d:
        return re.search(d["regex"], metin, re.I | re.M) is not None
    return d["metin"].lower() in metin.lower()


def _oku(p: Path) -> str:
    return p.read_text(encoding="utf-8", errors="replace")


def stl_bilgisi(yol: Path, env: dict | None = None, python: str = sys.executable) -> dict:
    out = subprocess.run([python, "-c", _STL_BETIGI, str(yol)], capture_output=True, text=True, env=env, timeout=120)
    satirlar = [s for s in out.stdout.splitlines() if s.startswith("{")]
    if out.returncode != 0 or not satirlar:
        return {"hata": (out.stderr.strip().splitlines() or ["STL okunamadı"])[-1]}
    return json.loads(satirlar[-1])


def _stl_denetle(d: dict, dosyalar: list[Path], env, python) -> tuple[bool, str]:
    if not dosyalar:
        return False, "STL yok"
    sorunlar = []
    for p in dosyalar:  # birden çok STL varsa biri koşulları sağlaması yeter (deneme dosyaları olabilir)
        b = stl_bilgisi(p, env, python)
        if "hata" in b:
            sorunlar.append(f"{p.name}: {b['hata']}")
            continue
        en_buyuk = max(b["olcu"])
        neden = []
        if not b["kapali"]:
            neden.append("kapalı değil")
        if "en_cok_mm" in d and en_buyuk > d["en_cok_mm"] * 1.01:
            neden.append(f"{en_buyuk:.1f} mm > {d['en_cok_mm']} mm")
        if "en_az_mm" in d and en_buyuk < d["en_az_mm"] * 0.99:
            neden.append(f"{en_buyuk:.1f} mm < {d['en_az_mm']} mm")
        if d.get("tek_parca") and b["parca"] != 1:
            neden.append(f"{b['parca']} parça")
        if not neden:
            return True, p.name
        sorunlar.append(f"{p.name}: " + ", ".join(neden))
    return False, "; ".join(sorunlar)


def denetle(gorev: dict, is_klasoru: Path, cevap: str, araclar: list[str], planlar: list[list[dict]],
            onceki: Path | None = None, env: dict | None = None, python: str = sys.executable) -> list[str]:
    """Düşen denetimlerin açıklamaları (boş liste = görev geçti)."""
    dusen = []
    for d in gorev["bitti"]:
        ok, neden = denetim(d, is_klasoru, cevap, araclar, planlar, onceki, env, python)
        if not ok:
            ad = d.get("yol") or d.get("ad") or d.get("betik") or d.get("metin") or d.get("regex") or ""
            dusen.append(f"{d['tur']} {ad}: {neden}".replace("  ", " "))
    return dusen


def denetim(d: dict, is_klasoru: Path, cevap: str, araclar: list[str], planlar: list[list[dict]],
            onceki: Path | None, env: dict | None, python: str) -> tuple[bool, str]:
    tur = d["tur"]
    if tur == "dosya_var":
        return bool(bul(is_klasoru, d["yol"])), "dosya yok"
    if tur == "dosya_icerir":
        dosyalar = bul(is_klasoru, d["yol"])
        return any(_eslesir(_oku(p), d) for p in dosyalar), "dosya yok" if not dosyalar else "içerik tutmuyor"
    if tur == "dosya_satir_sayisi":
        dosyalar = bul(is_klasoru, d["yol"])
        if not dosyalar:
            return False, "dosya yok"
        n = max(sum(1 for s in _oku(p).splitlines() if s.strip()) for p in dosyalar)
        return n >= d["en_az"], f"{n} satır"
    if tur == "stl_kapali":
        return _stl_denetle(d, bul(is_klasoru, d["yol"]), env, python)
    if tur == "cevap_icerir":
        return _eslesir(cevap, d), "cevapta yok"
    if tur == "cevap_icermez":
        return not _eslesir(cevap, d), "cevapta var"
    if tur == "cevap_en_cok_kelime":
        n = len(cevap.split())
        return n <= d["n"], f"{n} kelime"
    if tur == "arac_cagrildi":
        return any(fnmatch.fnmatch(a, d["ad"]) for a in araclar), "çağrılmadı"
    if tur == "arac_cagrilmadi":
        return not any(fnmatch.fnmatch(a, d["ad"]) for a in araclar), "çağrıldı"
    if tur == "plan_dili_turkce":
        if not planlar:
            return False, "plan çıkmadı"
        metin = " ".join(str(v) for plan in planlar for adim in plan for k, v in adim.items()
                         if k in ("title", "do", "done_when"))
        bulunan = CJK.findall(metin)
        return not bulunan, "planda CJK: " + "".join(bulunan[:10])
    if tur == "python_denetim":
        komut = [python, str(BETIKLER / d["betik"]), str(is_klasoru), cevap]
        if onceki is not None:
            komut.append(str(onceki))
        try:
            out = subprocess.run(komut, capture_output=True, text=True, env=env, timeout=120)
        except subprocess.TimeoutExpired:
            return False, "betik zaman aşımı"
        son = (out.stdout.strip() + "\n" + out.stderr.strip()).strip().splitlines()
        return out.returncode == 0, (son[-1] if son else f"çıkış {out.returncode}")[:200]
    return False, f"bilinmeyen denetim {tur}"
