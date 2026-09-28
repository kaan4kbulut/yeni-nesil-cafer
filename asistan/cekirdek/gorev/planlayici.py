"""PLANLA: şema-kısıtlı JSON plan (SEMALAR §2 `adimlar`). Yetenek adı şemada enum: model listede olmayan bir işi
çağıramaz (planlayıcı yalnızca kayıtlı yetenekleri çağırır — MIMARI §6).

Şemaya ya da programın ek kurallarına (bağımlılık geriye bakar, yer tutucu önceki adıma, girdi yeteneğin şemasına
uyar) uymayan plan → bir düzeltme turu → yine uymuyorsa `PlanYetersiz` (`model_yetersiz`, SEMALAR §3).
Modelin yazmadığı alanları program doldurur: id, onay_gerekli (izin hattından), secim (yönlendiriciden), durum.
"""

import re

from .. import semalar
from . import METIN_URET, METIN_URET_ACIKLAMA, METIN_URET_SEMASI, ModelYok
from .durum import simdi, yeni_id

EN_COK_ADIM = 6
EN_COK_DENEME = 3
YER_TUTUCU = re.compile(r"\{\{\s*adim_(\d+)\.sonuc\s*\}\}")
# K12-E7: yeniden planlamada BİTEN adımların sonucu (numaraları kaymaz; yürütücü adim_N'e çevirir)
YER_TUTUCU_ONCEKI = re.compile(r"\{\{\s*onceki_(\d+)\.sonuc\s*\}\}")

SISTEM = ("You are the planner of a personal assistant running on the user's computer. You do not do the work: you "
          "split the request into a short ordered plan of capability calls. Answer with one JSON object only.")


class PlanYetersiz(Exception):
    """Model şemaya uyan plan yazamadı. `kayit`: SEMALAR §3 hata kaydı (`model_yetersiz`)."""

    def __init__(self, kayit: dict):
        super().__init__(kayit.get("belirti", "plan yazılamadı"))
        self.kayit = kayit


def tum_yetenekler(yetenekler: list[dict]) -> list[dict]:
    """Planlayıcının gördüğü liste: kayıtlı yetenekler + model adımı (`metin_uret`)."""
    return [*yetenekler, {"ad": METIN_URET, "aciklama": METIN_URET_ACIKLAMA, "girdi_semasi": METIN_URET_SEMASI}]


def plan_semasi(adlar: list[str]) -> dict:
    """Modelin dolduracağı kısım (Ollama `format` / json_schema); yetenek adı enum."""
    return {
        "type": "object",
        "properties": {"adimlar": {
            "type": "array", "minItems": 1, "maxItems": EN_COK_ADIM,
            "items": {
                "type": "object",
                "properties": {
                    "amac": {"type": "string", "minLength": 1},
                    "yetenek": {"type": "string", "enum": list(adlar)},
                    "girdi": {"type": "object"},
                    "basari_olcutu": {"type": "string"},
                    "bagimli": {"type": "array", "items": {"type": "integer", "minimum": 1}},
                    "deneme_hakki": {"type": "integer", "minimum": 0},
                },
                "required": ["amac", "yetenek", "girdi", "basari_olcutu", "bagimli", "deneme_hakki"],
            },
        }},
        "required": ["adimlar"],
    }


def _girdi_hatalari(girdi: dict, sema: dict, yol: str) -> list[str]:
    """Yer tutucular çalışma anında çözülür: türü metin olmayan alana yer tutucu yazılmışsa tür denetimi atlanır."""
    sade = {k: v for k, v in girdi.items()
            if not (isinstance(v, str) and (YER_TUTUCU.search(v) or YER_TUTUCU_ONCEKI.search(v)))}
    eksik = [f"{yol}: '{k}' eksik" for k in sema.get("required") or [] if k not in girdi]
    ozellik = {k: v for k, v in (sema.get("properties") or {}).items() if k in sade}
    return eksik + semalar.dogrula(sade, {"type": "object", "properties": ozellik}, _yol=yol)


def ek_denetim(veri: dict, yetenekler: list[dict]) -> list[str]:
    """Şemanın anlatamadığı kurallar."""
    semasi = {y["ad"]: y.get("girdi_semasi") or {} for y in yetenekler}
    hatalar = []
    for i, adim in enumerate(veri.get("adimlar") or [], 1):
        yol = f"$.adimlar[{i - 1}]"
        for b in adim.get("bagimli") or []:
            if not isinstance(b, int) or b >= i:
                hatalar.append(f"{yol}.bagimli: yalnızca önceki adımlar (1..{i - 1}) olabilir ({b} geldi)")
        metin = str(adim.get("girdi"))
        for n in YER_TUTUCU.findall(metin):
            if int(n) >= i:
                hatalar.append(f"{yol}.girdi: {{{{adim_{n}.sonuc}}}} yalnızca önceki adımlara bakabilir")
        for n in YER_TUTUCU_ONCEKI.findall(metin):
            if int(n) < 1:
                hatalar.append(f"{yol}.girdi: {{{{onceki_{n}.sonuc}}}} geçersiz")
        for bozuk in re.findall(r"\{\{.*?\}\}", YER_TUTUCU_ONCEKI.sub("", YER_TUTUCU.sub("", metin))):
            hatalar.append(f"{yol}.girdi: {bozuk[:60]} geçersiz; yalnızca tam olarak {{{{adim_N.sonuc}}}} yazılır "
                           "(ifade yok). Tek bir değer gerekiyorsa önceki adımın kodu YALNIZCA o değeri yazdırsın.")
        if isinstance(adim.get("girdi"), dict) and adim.get("yetenek") in semasi:
            hatalar += _girdi_hatalari(adim["girdi"], semasi[adim["yetenek"]], f"{yol}.girdi")
    return hatalar


def _istem(istek: str, anlayis: dict, yetenekler: list[dict], klasor: str, okunur: str, parcala: bool) -> str:
    liste = "\n".join(f"- {y['ad']}: {y.get('aciklama', '')[:200]}\n  input schema: "
                      f"{_kisa_sema(y.get('girdi_semasi') or {})}" for y in yetenekler)
    return (
        f"User's request:\n{istek}\n\n"
        f"Understanding: intent={anlayis.get('niyet')}; constraints={anlayis.get('kisitlar')}\n"
        f"Task folder: {klasor} — relative paths ('.', 'rapor.txt') and code's current directory point HERE; it "
        "starts empty. Write new files here.\n"
        + (f"User's working folder (READ ONLY): {okunur} — to READ the user's files ('çalışma klasörü') use this "
           "absolute path. Files you create always go to the task folder with a plain relative name (e.g. "
           "'liste.md'); writing into the working folder is refused.\n"
           if okunur and okunur != klasor else "")
        + f"\nCapabilities (use ONLY these names):\n{liste}\n\n"
        f"Split the work into 1-{EN_COK_ADIM} ordered steps; use as few as the job needs"
        + (" and keep every step very small (a weak model will run it)" if parcala else "") + ". For each step:\n"
        "- amac: what the step does, short, in the user's language\n"
        "- yetenek: one capability name from the list\n"
        "- girdi: the capability's input object (follow its input schema). To use an earlier step's result write "
        "exactly {{adim_N.sonuc}} (N = that step's number; no expressions inside) as a value: the program puts the "
        "earlier step's whole output there (for code: what it printed). If a later step needs one value (e.g. a "
        "file path), make the earlier code print ONLY that value.\n"
        "- basari_olcutu: how the program can tell from the result that the step really worked\n"
        "- bagimli: numbers of earlier steps whose results this step uses ([] if none)\n"
        "- deneme_hakki: extra attempts if it fails (0-2)\n"
        "Do not add steps for asking the user, for approval or only for reporting/printing the results (the "
        "program handles them and shows every step's result). Never invent helper files the user did not ask for.")


def _kisa_sema(sema: dict) -> str:
    ozellik = sema.get("properties") or {}
    gerekli = set(sema.get("required") or [])
    return ", ".join(f"{k}{'*' if k in gerekli else ''}: {v.get('type', '?') if isinstance(v, dict) else '?'}"
                     for k, v in ozellik.items()) or "{}"


def planla(istek: str, anlayis: dict, yetenekler: list[dict], model, klasor: str = "", okunur: str = "",
           parcala: bool = False) -> list[dict]:
    """Modelin adımları (henüz program alanları yok). Olmazsa `PlanYetersiz`."""
    hepsi = tum_yetenekler(yetenekler)
    sema = plan_semasi([y["ad"] for y in hepsi])
    istem = _istem(istek, anlayis, hepsi, klasor, okunur, parcala)
    try:
        cevap = model("planlama", [{"role": "user", "content": istem}], SISTEM, sema)
    except ModelYok as e:
        raise PlanYetersiz(_kayit(f"plan için model yok: {e}", "")) from e
    veri = cevap.veri
    hatalar = list(cevap.hatalar)
    if veri is not None and not hatalar:
        hatalar = ek_denetim(veri, hepsi)
        if hatalar:  # şema tuttu ama program kuralı tutmadı: bir düzeltme turu
            duzelt = [{"role": "user", "content": istem}, {"role": "assistant", "content": cevap.metin},
                      {"role": "user", "content": "Your plan broke these rules:\n" + "\n".join(hatalar[:12])
                       + "\nReturn the corrected plan JSON only."}]
            try:
                cevap = model("planlama", duzelt, SISTEM, sema)
            except ModelYok as e:
                raise PlanYetersiz(_kayit(f"plan için model yok: {e}", "")) from e
            veri, hatalar = cevap.veri, list(cevap.hatalar)
            if veri is not None and not hatalar:
                hatalar = ek_denetim(veri, hepsi)
    if veri is None or hatalar:
        raise PlanYetersiz(_kayit("şemaya uyan plan yazılamadı (" + (cevap.secim or {}).get("model", "?") + ")",
                                  "; ".join(hatalar[:6]) + " | " + (cevap.metin or "")[:300]))
    return veri["adimlar"]


def _kayit(belirti: str, kanit: str) -> dict:
    return {"adim": 0, "zaman": simdi(), "sinif": "model_yetersiz", "belirti": belirti[:300], "kanit": kanit[:1000],
            "eylem": {"tip": "ust_model", "hedef": "yonlendirici", "onay": "yok"}, "sonuc": "vazgecildi"}


def gorev_olustur(istek: str, anlayis: dict, adimlar: list[dict], yetenekler_: "object", model,
                  kademe: str = "orta") -> dict:
    """Modelin adımlarından SEMALAR §2 görevi: program alanları doldurulur, `gorev.json` şemasıyla denetlenir."""
    duz = []
    for i, a in enumerate(adimlar, 1):
        ad = a["yetenek"]
        girdi = dict(a.get("girdi") or {})
        if ad == METIN_URET:
            secim, onay = model.secim("ozet"), False
        else:
            secim = {"saglayici": None, "model": None, "neden": "model gerekmiyor"}
            onay = bool(yetenekler_.onay_gerekir(ad, girdi))
        duz.append({
            "id": i, "amac": str(a["amac"]).strip(), "yetenek": ad, "girdi": girdi,
            "basari_olcutu": str(a.get("basari_olcutu") or "").strip(),
            "bagimli": [b for b in a.get("bagimli") or [] if isinstance(b, int) and 0 < b < i],
            "deneme_hakki": max(0, min(EN_COK_DENEME, int(a.get("deneme_hakki") or 0))),
            "onay_gerekli": onay, "secim": secim, "durum": "planlandi",
        })
    gorev = {"gorev_id": yeni_id(), "istek": istek, "olusturma": simdi(), "kademe": kademe, "anlayis": anlayis,
             "adimlar": duz, "durum": "planlandi", "checkpoint": {"son_adim": 0, "zaman": None}, "hatalar": [],
             "rapor": None}
    hatalar = semalar.dogrula(gorev, semalar.yukle("gorev"))
    if hatalar:
        raise PlanYetersiz(_kayit("görev şemaya uymuyor", "; ".join(hatalar[:6])))
    return gorev


def duzelt_girdi(adim: dict, neden: str, sonuc: str, yetenekler: list[dict], model,
                 onceki: list[dict] | None = None) -> dict | None:
    """Başarısız adımın girdisini modele düzelttirir (MIMARI §7 `mantik`: başarısız çıktı bağlama eklenir).
    Şema: o yeteneğin kendi girdi şeması. `onceki`: biten adımlar — sonuçları istemde (model değer uydurmasın;
    canlı deneme: 1. adımın bulduğu dosya yerine "duman.txt" yazmıştı). Olmazsa None."""
    hepsi = {y["ad"]: y for y in tum_yetenekler(yetenekler)}
    sema = (hepsi.get(adim["yetenek"]) or {}).get("girdi_semasi")
    if not sema:
        return None
    gecmis = "".join(f"Step {a['id']} ({a['amac']}) result:\n{str(a.get('sonuc') or '')[:1200]}\n\n"
                     for a in onceki or [] if a.get("durum") == "tamamlandi")
    istem = (f"A step of a plan failed.\n\n{gecmis}Failed step: {adim['amac']}\nCapability: {adim['yetenek']}\n"
             f"Input used: {adim['girdi']}\nSuccess criterion: {adim.get('basari_olcutu')}\n"
             f"Why it failed: {neden}\nResult:\n{(sonuc or '')[:1500]}\n\n"
             "Give a corrected input object for the same capability. Use real values from the earlier results "
             "(copy them exactly); never invent names.")
    try:
        cevap = model("planlama", [{"role": "user", "content": istem}], SISTEM, sema)
    except ModelYok:
        return None
    return cevap.veri
