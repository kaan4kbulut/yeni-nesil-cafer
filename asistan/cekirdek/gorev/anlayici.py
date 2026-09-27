"""ANLA: istek → niyet, kısıtlar, belirsizlikler, gereken/eksik yetenekler (SEMALAR §2 `anlayis`). Belirsizlik
yüksekse kullanıcıya TEK soru.

Model şema-kısıtlı cevap verir; yetenek adlarını program denetler (listede olmayan "gereken" yetenek eksiğe geçer).
Model yoksa ya da cevap şemaya uymadıysa iş durmaz: niyet isteğin kendisi, gerisi boş kalır.
"""

from .. import semalar
from . import METIN_URET, ModelYok

SISTEM = ("You analyse a user's request for a personal assistant before it is planned. You do not do the work. "
          "Answer with one JSON object only; write texts in the user's language (usually Turkish).")


def anlayis_semasi() -> dict:
    sema = semalar.duzlestir(semalar.yukle("gorev"))["properties"]["anlayis"]
    sema["properties"]["belirsizlik"] = {"type": "string", "enum": ["dusuk", "yuksek"]}
    sema["properties"]["soru"] = {"type": "string"}
    sema["required"] = [*sema["required"], "belirsizlik"]
    return sema


def bos_anlayis(istek: str) -> dict:
    return {"niyet": " ".join((istek or "").split())[:120], "kisitlar": [], "belirsizlikler": [],
            "gereken_yetenekler": [], "eksik_yetenekler": []}


def anla(istek: str, yetenekler: list[dict], model) -> tuple[dict, str]:
    """(anlayis, soru). `soru` boş değilse görev kullanıcının cevabını bekler."""
    adlar = [y["ad"] for y in yetenekler] + [METIN_URET]
    liste = "\n".join(f"- {y['ad']}: {y.get('aciklama', '')[:160]}" for y in yetenekler)
    istem = (f"User's request:\n{istek}\n\nCapabilities the assistant has:\n{liste}\n- {METIN_URET}: write text with "
             "a language model\n\n"
             "Give: niyet (the intent in a few words), kisitlar (limits the user set: folders, formats, what must not "
             "change), belirsizlikler (what is really unclear), gereken_yetenekler (names from the list above), "
             "eksik_yetenekler (what is needed but not in the list), belirsizlik ('yuksek' only if the request "
             "cannot be done without asking the user), soru (one short question for the user when belirsizlik is "
             "'yuksek', otherwise empty).")
    try:
        cevap = model("analiz", [{"role": "user", "content": istem}], SISTEM, anlayis_semasi())
    except ModelYok:
        return bos_anlayis(istek), ""
    veri = cevap.veri
    if not veri:
        return bos_anlayis(istek), ""
    anlayis = {k: veri.get(k) for k in bos_anlayis("")}
    anlayis["niyet"] = str(anlayis["niyet"] or "").strip() or bos_anlayis(istek)["niyet"]
    for k in ("kisitlar", "belirsizlikler", "gereken_yetenekler", "eksik_yetenekler"):
        anlayis[k] = [str(x).strip() for x in anlayis.get(k) or [] if str(x).strip()]
    bilinmeyen = [a for a in anlayis["gereken_yetenekler"] if a not in adlar]
    anlayis["gereken_yetenekler"] = [a for a in anlayis["gereken_yetenekler"] if a in adlar]
    anlayis["eksik_yetenekler"] = list(dict.fromkeys(anlayis["eksik_yetenekler"] + bilinmeyen))
    soru = str(veri.get("soru") or "").strip() if veri.get("belirsizlik") == "yuksek" else ""
    return anlayis, soru
