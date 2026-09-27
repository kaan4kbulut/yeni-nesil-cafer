"""DOĞRULA: adımın `basari_olcutu` sağlandı mı? Önce programın kanıtı (hata, boş sonuç, reddedilen çağrı, ölçütte adı
geçen dosya gerçekten var mı), sonra — kural karar veremediyse — hızlı modele şema-kısıtlı soru.

CLAUDE.md: "Model çıktısına güvenme, kodla denetle." Kural bir eksik bulduysa model sorulmaz; modelin "tamam" demesi
programın bulduğu eksiği ezmez.
"""

import re
from pathlib import Path

from . import Cikti, ModelYok

# araç sonucunun ilk satırı bunlardan biriyse çalışmamıştır (manager._Recorder ile aynı işaretler)
_BASARISIZ = re.compile(r"^(Error|REFUSED|NOT RUN|NOT EXECUTED|BLOCKED|The user declined|exit code: [1-9])")
_DOSYA = re.compile(r"(?<![\w/])([\w\-.]+\.(?:txt|md|csv|json|py|html|xlsx|xls|docx|pdf|png|jpg|jpeg|svg|stl|log|yaml"
                    r"|yml|zip))\b", re.I)
_VAR_OLMALI = re.compile(r"\b(var|vardır|oluştur|oluşur|yazıl|kaydedil|mevcut|bulunur|exists?|created|saved|written)",
                         re.I)
_BOS_DEGIL = re.compile(r"boş değil|bos degil|not empty|non-empty", re.I)

SEMA = {"type": "object", "properties": {"tamam": {"type": "boolean"}, "eksik": {"type": "string"}},
        "required": ["tamam", "eksik"]}
SISTEM = ("You check whether one step of a plan really worked, from the program's evidence (the capability's result). "
          "Words alone are not evidence. Answer with one JSON object only; 'eksik' in the user's language.")


def kural(adim: dict, cikti: Cikti, klasorler: list[str] | None = None) -> tuple[bool | None, str]:
    """Programın kendi denetimi: (False, neden) eksik bulundu · (True, "") ölçüt kuralla sağlandı · (None, "") karar
    modelin."""
    metin = (cikti.metin or "").strip()
    if cikti.onay_bekliyor:
        return False, "onay bekliyor"
    if cikti.hata or _BASARISIZ.match(metin) or "Traceback (most recent call last)" in metin:
        ilk = next((s.strip() for s in reversed(metin.splitlines()) if s.strip()), "hata")
        return False, f"yetenek hata verdi: {ilk[:200]}"
    if not metin:
        return False, "sonuç boş"
    olcut = adim.get("basari_olcutu") or ""
    if klasorler and _VAR_OLMALI.search(olcut):
        eksik = [ad for ad in dict.fromkeys(_DOSYA.findall(olcut))
                 if not any((Path(k) / ad).exists() for k in klasorler)]
        if eksik:
            return False, "dosya yok: " + ", ".join(eksik)
        if _DOSYA.search(olcut) and len(_DOSYA.sub("", olcut).split()) <= 3:
            return True, ""  # ölçüt yalnızca "x.txt var" diyordu: dosya var
    if not olcut.strip() or (_BOS_DEGIL.search(olcut) and len(olcut) < 40):
        return True, ""  # ölçüt yok ya da yalnızca "boş değil": sonuç var
    return None, ""


def dogrula(adim: dict, cikti: Cikti, klasorler: list[str] | None = None, model=None,
            salt_okur: bool = False) -> tuple[bool, str]:
    """(tamam mı, eksik ne). `salt_okur`: yetenek yalnızca bilgi okur (dosya/web okuma, listeleme)."""
    karar, neden = kural(adim, cikti, klasorler)
    if karar is not None:
        return karar, neden
    if salt_okur:
        # okuma hatasız ve boş değilse okuma yapılmıştır; içeriğin doğruluğunu onu kullanan adım gösterir. Canlı
        # deneme (2026-09-28): okunan dosya "asistanın yetenekleri" hakkındaydı, denetçi model "dosya okunmamış,
        # yalnızca sistem bilgisi döndü" deyip doğru okumayı reddetti.
        return True, ""
    if model is None:
        return True, ""  # denetleyecek model yok: programın kanıtı temiz, adım durdurulmaz
    istem = (f"Step: {adim.get('amac')}\nCapability: {adim.get('yetenek')}\n"
             f"Success criterion: {adim.get('basari_olcutu')}\n\nResult (program's evidence):\n"
             f"{(cikti.metin or '')[:3000]}\n\nDoes the result meet the criterion? If not, say briefly what is "
             "missing.")
    try:
        cevap = model("siniflandirma", [{"role": "user", "content": istem}], SISTEM, SEMA)
    except ModelYok:
        return True, ""
    if not cevap.veri:
        return True, ""  # denetçi cevap veremedi: adımı durdurma (manager.check ile aynı)
    return bool(cevap.veri.get("tamam")), str(cevap.veri.get("eksik") or "").strip()
