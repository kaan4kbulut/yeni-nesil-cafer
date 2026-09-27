"""`python -m asistan gorev …` (docs/MIMARI.md §2 `cafer gorev "…"`) ve masaüstünün kullandığı `motor_kur`.

  gorev "<istek>"           yeni görev: anla → planla → koş (onay gereken adımda durur)
  gorev --liste             yarım görevler (--hepsi: bitenler de)
  gorev --goster <id>       planı ve adım durumlarını göster
  gorev --devam <id>        kaldığı yerden sür
  gorev --onayla <id>       onay bekleyen adımı onayla ve sür (--reddet: onaylama, görevi durdur)
  gorev --yanitla <id> "…"  motorun tek sorusuna cevap
  gorev --iptal <id>        görevi iptal et (kayıt kalır)

Komut satırı kullanıcının sohbeti değildir: CLI ajanları (Claude Code, Codex, Gemini CLI) seçilmez (CLAUDE.md;
`yonlendirici.EXTRA_KAYNAK = "komut"`).
"""

import json
import sys
from dataclasses import replace

from . import durum as durum_mod

ISARET = {"planlandi": "○", "calisiyor": "▶", "bekliyor_onay": "⏸", "bekliyor_kullanici": "?", "tamamlandi": "✓",
          "basarisiz": "✗", "iptal": "–"}
KAYNAK = "komut"


def gorev_klasoru(ayarlar, istek: str, gorev_id: str) -> str:
    """Görevin iş klasörü: <çalışma klasörü>/Görevler/<başlık>-<id> (her iş kendi klasöründe; CLAUDE.md)."""
    from ... import work

    return work.chat_folder(ayarlar.workspace, "Görevler", istek[:40], gorev_id.split("_")[-1])


def motor_kur(ayarlar=None, baglantilar=None, istek: str = "", gorev_id: str = "", olay=None, iptal=None,
              kaynak: str = KAYNAK):
    """Gerçek yetenekler + yönlendirici modeliyle yürütücü. `istek`/`gorev_id` iş klasörünü belirler."""
    from ...config import Settings
    from ...connections import load_connections
    from .. import profil, yonlendirici
    from .ajan import AjanYetenekleri
    from .model import YonlendiriciModeli
    from .yurutucu import Yurutucu

    ayarlar = ayarlar or Settings.load()
    ayarlar = replace(ayarlar, extra={**(ayarlar.extra or {}), yonlendirici.EXTRA_KAYNAK: kaynak})
    baglantilar = load_connections() if baglantilar is None else baglantilar
    depo = durum_mod.depo()
    if gorev_id and not istek:
        eski = depo.getir(gorev_id)
        istek = (eski or {}).get("istek", "")
    klasor = gorev_klasoru(ayarlar, istek or "gorev", gorev_id or durum_mod.yeni_id())
    okunur = ayarlar.workspace
    yetenekler = AjanYetenekleri(ayarlar, baglantilar, klasor, [okunur], olay, iptal)
    model = YonlendiriciModeli(ayarlar, baglantilar)
    return Yurutucu(depo, yetenekler, model, klasor, okunur, olay, iptal, profil.kademe())


def ozet(gorev: dict, ayrinti: bool = False) -> str:
    satirlar = [f"{ISARET.get(gorev['durum'], '?')} {gorev['gorev_id']}  [{gorev['durum']}]  {gorev['istek'][:70]}"]
    if ayrinti:
        for a in gorev.get("adimlar") or []:
            onay = " (onay gerekli)" if a.get("onay_gerekli") else ""
            model = (a.get("secim") or {}).get("model")
            satirlar.append(f"   {ISARET.get(a['durum'], '?')} {a['id']}. {a['amac']} · {a['yetenek']}{onay}"
                            + (f" · {model}" if model else ""))
            if a.get("sonuc_ozeti") or a.get("not"):
                satirlar.append(f"      {(a.get('sonuc_ozeti') or a.get('not'))[:160]}")
        if gorev.get("rapor") and gorev["durum"] in ("bekliyor_kullanici",):
            satirlar.append(f"   Soru: {gorev['rapor']}")
    return "\n".join(satirlar)


def _olay_yaz(tur: str, veri: dict) -> None:
    if tur == "plan":
        print(ozet(veri["gorev"], True), flush=True)
    elif tur == "adim":
        a = veri["adim"]
        print(f"   {ISARET.get(a['durum'], '?')} {a['id']}. {a['amac']}", flush=True)
    elif tur == "arac":
        print(f"      → {veri['ad']}", flush=True)
    elif tur == "tekrar":
        print(f"      ↻ tekrar: {veri['neden'][:160]}", flush=True)
    elif tur == "onay":
        a = veri["adim"]
        print(f"   ⏸ Adım {a['id']} onay bekliyor: {a['yetenek']} {json.dumps(a['girdi'], ensure_ascii=False)[:300]}\n"
              f"     Onaylamak için: gorev --onayla {veri['gorev']['gorev_id']}", flush=True)
    elif tur == "soru":
        print(f"? {veri['soru']}\n  Cevap için: gorev --yanitla {veri['gorev']['gorev_id']} \"…\"", flush=True)


def _bitis(gorev: dict) -> int:
    if gorev["durum"] in ("tamamlandi", "basarisiz", "iptal") and gorev.get("rapor"):
        print("\n" + gorev["rapor"])
    son = next((a for a in reversed(gorev.get("adimlar") or []) if a["durum"] == "tamamlandi"), None)
    if gorev["durum"] == "tamamlandi" and son and son.get("sonuc"):
        print("\n" + son["sonuc"][:4000])
    return 0 if gorev["durum"] in ("tamamlandi", "bekliyor_onay", "bekliyor_kullanici") else 1


def komut(argv: list[str]) -> int:
    from ..saglayici import Iptal

    if not argv or argv[0] in ("-h", "--help"):
        print(__doc__)
        return 0
    depo = durum_mod.depo()
    secenek, kalan = argv[0], argv[1:]
    try:
        if secenek == "--liste":
            gorevler = depo.listele() if "--hepsi" in kalan else depo.yarim()
            print("\n".join(ozet(g) for g in gorevler) or "Yarım görev yok.")
            return 0
        if secenek == "--goster":
            gorev = depo.getir(kalan[0])
            print(ozet(gorev, True) if gorev else f"Görev yok: {kalan[0]}")
            return 0 if gorev else 1
        if secenek == "--iptal":
            ok = depo.iptal_et(kalan[0])
            print("İptal edildi." if ok else "İptal edilecek yarım görev yok.")
            return 0 if ok else 1
        if secenek in ("--devam", "--onayla", "--reddet", "--yanitla"):
            if depo.getir(kalan[0]) is None:
                print(f"Görev yok: {kalan[0]}", file=sys.stderr)
                return 1
            motor = motor_kur(gorev_id=kalan[0], olay=_olay_yaz)
            if secenek == "--devam":
                return _bitis(motor.devam(kalan[0]))
            if secenek == "--yanitla":
                return _bitis(motor.yanitla(kalan[0], " ".join(kalan[1:])))
            return _bitis(motor.onayla(kalan[0], secenek == "--onayla"))
        if secenek.startswith("--"):
            print(f"Bilinmeyen seçenek: {secenek}\n{__doc__}", file=sys.stderr)
            return 2
        istek = " ".join(argv)
        gorev_id = durum_mod.yeni_id()
        motor = motor_kur(istek=istek, gorev_id=gorev_id, olay=_olay_yaz)
        return _bitis(motor.baslat(istek, gorev_id=gorev_id))
    except (KeyboardInterrupt, Iptal):
        print("\nDurduruldu; görev yarım kaldı. Sürdürmek için: gorev --liste, gorev --devam <id>", file=sys.stderr)
        return 130
