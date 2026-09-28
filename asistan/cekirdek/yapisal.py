"""Şema-kısıtlı üretim: modelden JSON şemasına uyan tek bir nesne almak (eski Aşama 3, YAPILACAKLAR K4).

Sağlayıcıya göre yol:
- Ollama: `format=<şema>` (gramer kısıtı; model şemanın dışına çıkamaz), düşünmesiz.
- OpenAI uyumlu: `response_format: {type: "json_schema"}`; bağlantı reddederse `json_object` + talimat.
- Claude API: şema tek zorunlu aracın girdi şeması (`tool_choice`); CLI ajanları: talimat + ayrıştırma.
Her yolda sonuç programın kendi doğrulayıcısından (`semalar.dogrula`) geçer; uymazsa hatalar modele gösterilip bir kez
düzelttirilir. Yine uymazsa `Sonuc.veri` None ve `hatalar` dolu döner (çağıran bunu `model_yetersiz` sayar).
"""

import json
import re
from dataclasses import dataclass, field

from . import semalar
from .saglayici import SaglayiciHatasi

TALIMAT = ("Respond with ONLY one JSON object that matches this JSON Schema (no prose, no code fence):\n{sema}")
CLAUDE_ARACI = "cevap"
DUZELT = ("Your JSON did not match the required schema:\n{hatalar}\nReturn the corrected JSON object only.")


@dataclass
class Sonuc:
    veri: dict | None  # şemaya uyan nesne; uymadıysa None
    hatalar: list[str] = field(default_factory=list)  # son denemenin şema hataları
    ham: str = ""  # modelin son ham cevabı
    deneme: int = 0  # kaç model çağrısı yapıldı


def json_ayikla(metin: str) -> dict | None:
    """Model cevabından ilk JSON nesnesi (``` içinde ya da metnin arasında olabilir)."""
    metin = (metin or "").strip()
    cit = re.search(r"```(?:json)?\s*(.*?)```", metin, re.S)
    if cit:
        metin = cit.group(1)
    bas, son = metin.find("{"), metin.rfind("}")
    if bas < 0 or son <= bas:
        return None
    try:
        veri = json.loads(metin[bas:son + 1])
    except ValueError:
        return None
    return veri if isinstance(veri, dict) else None


def _tur(saglayici) -> str:
    ad = getattr(saglayici, "ad", "") or ""
    if ad == "ollama":
        return "ollama"
    if ad.startswith("api:"):
        return "openai"
    return "talimat"  # claude, cli:* ve bilinmeyenler


def _cagir(saglayici, mesajlar: list, sistem: str, sema: dict, model: str, durum: dict,
           ollama_ek: dict | None = None) -> tuple[str, object]:
    """Tek çağrı; sağlayıcının JSON kısıtını kullanır. `durum["openai"]`: bağlantının desteklediği en iyi kip.
    (metin, sağlayıcının yanıtı) döner: yanıttan gerçek token kullanımı okunur."""
    tur = _tur(saglayici)
    duz = semalar.duzlestir(sema)
    secenek = {"model": model} if model else {}
    if tur == "ollama":
        y = saglayici.sohbet(mesajlar, sistem, bicim=duz, dusunme=False, **secenek, **(ollama_ek or {}))
        return y.metin, y
    if tur == "openai":
        while True:
            kip = durum.setdefault("openai", "json_schema")
            ek = {"json_semasi": duz} if kip == "json_schema" else {"json_bicimi": True}
            talimat = TALIMAT.format(sema=json.dumps(duz, ensure_ascii=False))
            ek_sistem = "" if kip == "json_schema" else "\n\n" + talimat
            try:
                y = saglayici.sohbet(mesajlar, sistem + ek_sistem, **ek, **secenek)
                return y.metin, y
            except SaglayiciHatasi as e:
                if e.durum == 400 and kip == "json_schema":
                    durum["openai"] = "json_object"  # bu bağlantı json_schema bilmiyor: bir alt kip
                    continue
                raise
    if getattr(saglayici, "ad", "") == "claude" and hasattr(saglayici, "parametreler"):
        # Claude: şema tek bir zorunlu aracın girdisi olur; model araç çağrısını şemaya göre doldurur
        params = saglayici.parametreler(sistem, [{"name": CLAUDE_ARACI, "description": "Return the answer.",
                                                  "input_schema": duz}], dusunme=False, **secenek)
        params["tool_choice"] = {"type": "tool", "name": CLAUDE_ARACI}
        params["tools"] = [{k: v for k, v in t.items() if k != "eager_input_streaming"} for t in params["tools"]]
        yanit = saglayici.sohbet(mesajlar, sistem, parametreler=params)
        for blok in getattr(yanit.son.get("yanit"), "content", None) or []:
            if getattr(blok, "type", "") == "tool_use":
                return json.dumps(blok.input, ensure_ascii=False), yanit
        return yanit.metin, yanit
    ek_sistem = TALIMAT.format(sema=json.dumps(duz, ensure_ascii=False))
    sistem = f"{sistem}\n\n{ek_sistem}" if sistem else ek_sistem
    y = saglayici.sohbet(mesajlar, sistem, **secenek)
    return y.metin, y


def harcama_yaz(saglayici, yanit, sistem: str, mesajlar: list, metin: str, gorev_id: str | None = None) -> None:
    """Ücretli sağlayıcının çağrısı bulut defterine: gerçek `usage` (yoksa karakter/4 tahmini). Yerel ve CLI sayılmaz."""
    ad = getattr(saglayici, "ad", "") or ""
    if not ad or ad == "ollama" or ad.startswith("cli:"):
        return
    from . import yonlendirici

    girdi, cikti = (0, 0)
    if yanit is not None and hasattr(saglayici, "kullanim"):
        try:
            girdi, cikti = saglayici.kullanim(yanit)
        except Exception:  # sağlayıcı beklenmedik biçim verdiyse tahmine düş
            girdi, cikti = 0, 0
    toplam = (girdi + cikti) or (len(sistem) + len(str(mesajlar)) + len(metin or "")) // 4
    yonlendirici.harcama_ekle(ad, toplam, gorev_id=gorev_id)


def uret(saglayici, mesajlar: list, sema: dict, sistem: str = "", model: str = "", deneme: int = 2,
         ek_denetim=None, ollama_ek: dict | None = None, gorev_id: str | None = None) -> Sonuc:
    """`sema`ya uyan tek JSON nesnesi. İlk deneme + (deneme-1) düzeltme turu; sağlayıcı hataları yukarı çıkar.

    `ek_denetim(veri) -> list[str]`: şemanın anlatamadığı kurallar (ör. adım bağımlılığı geriye bakmalı); hataları da
    düzeltme turunda modele gösterilir. `ollama_ek`: Ollama seçenekleri (num_ctx, num_predict). Ücretli sağlayıcıda
    HER çağrı (düzeltme turu dahil) gerçek `usage` ile bulut defterine yazılır (`gorev_id`: görev sayacı)."""
    mesajlar = list(mesajlar)
    durum: dict = {}
    sonuc = Sonuc(None)
    for i in range(max(1, deneme)):
        ham, yanit = _cagir(saglayici, mesajlar, sistem, sema, model, durum, ollama_ek)
        harcama_yaz(saglayici, yanit, sistem, mesajlar, ham, gorev_id)
        sonuc.ham, sonuc.deneme = ham, i + 1
        veri = json_ayikla(ham)
        sonuc.hatalar = ["$: JSON nesnesi yok"] if veri is None else semalar.dogrula(veri, sema)
        if not sonuc.hatalar and ek_denetim is not None:
            sonuc.hatalar = list(ek_denetim(veri) or [])
        if not sonuc.hatalar:
            sonuc.veri = veri
            return sonuc
        mesajlar += [{"role": "assistant", "content": ham or "(boş)"},
                     {"role": "user", "content": DUZELT.format(hatalar="\n".join(sonuc.hatalar[:12]))}]
    return sonuc
