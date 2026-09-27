"""Model kadrosu: kurulu ve bağlı modelleri tanır, her işe en uygun modeli kendisi seçer.

Kullanıcı model seçmek zorunda değildir. Ana asistan, ajanlar ve yönetici için model, işin
ihtiyacına (araç kullanımı, görme, kod, derin düşünme) ve modellerin yeteneklerine bakılarak atanır.

Politika (Ayarlar'da):
- "yerel": önce ücretsiz yerel modeller; yerelde o yetenek yoksa bulut (Claude, Gemini, OpenAI…).
- "guclu": en güçlü model, bulut dahil (ücretli olabilir).
"""

import re
import time
from dataclasses import dataclass, field

import httpx

from . import cards, cli_agents, model_updates, catalog, power, specialists
from .cekirdek import modeller
from .config import CLAUDE_MODELS, Settings
from .profiles import AgentProfile

CACHE_SECONDS = 30

# yerel model ailelerine göre kuşak puanı (aynı boyutta yeni kuşak daha yetenekli)
_FAMILY_BONUS = modeller.deger("aileler.kusak_puani")  # ayar/modeller.json

PREF_LABELS = {"tools": "araç", "vision": "görme", "code": "kod", "thinking": "düşünme"}


@dataclass
class Candidate:
    provider: str  # "ollama", "claude" ya da "api:<bağlantı id>"
    model: str
    caps: set = field(default_factory=set)  # tools, vision, thinking, code
    score: float = 0.0
    local: bool = False
    params: float = 0.0  # yerel modelde milyar parametre (bilinmiyorsa 0)

    @property
    def key(self) -> tuple[str, str]:
        return self.provider, self.model


_cache: tuple[float, tuple, list[Candidate]] | None = None


def _params(size: str) -> float:
    m = re.match(r"([\d.]+)\s*([BM])", size or "")
    if not m:
        return 0.0
    value = float(m.group(1))
    return value / 1000 if m.group(2) == "M" else value


def _ollama(settings: Settings) -> list[Candidate]:
    try:
        resp = httpx.get(settings.ollama_url.rstrip("/") + "/api/tags", timeout=5)
        resp.raise_for_status()
        models = resp.json().get("models", [])
    except Exception:
        return []
    out = []
    saving = power.saving(settings)
    for m in models:
        name = m.get("name", "")
        if "embed" in name:
            continue
        caps = set(specialists._capabilities(settings.ollama_url, name)) - {"completion", "insert"}
        if any(h in name for h in specialists._NAME_HINTS["code"]):
            caps.add("code")
        if any(h in name for h in specialists._NAME_HINTS["reasoning"]):
            caps.add("thinking")
        size = _params(m.get("details", {}).get("parameter_size", ""))
        bonus = next((b for fam, b in _FAMILY_BONUS.items() if name.startswith(fam)), 0)
        card = cards.card(name)  # programın kendi sınavı: beyandan önce gelir
        if card is not None:
            if card.get("tools"):
                caps.add("tools")
            else:
                caps.discard("tools")  # "araç desteği var" diyor ama sınavda hiç çağırmadı
            bonus += {0: 0, 1: -3, 2: 3}.get(card.get("tools", 0), 0) + (0 if card.get("turkish") else -3)
        # 14B civarı 12 GB karta sığar; çok büyükler RAM'e taşar ve yavaşlar
        fit = -((size - 16) * 0.8) if size > 16 else 0
        if saving and size > power.BATTERY_MAX_PARAMS:  # pilde büyük model çok yavaş (12B: 4 token/sn)
            fit -= (size - power.BATTERY_MAX_PARAMS) * 3
        out.append(Candidate("ollama", name, caps, size + bonus + fit, local=True, params=size))
    return out


def _cloud(settings: Settings) -> list[Candidate]:
    from .connections import load_connections

    out = []
    if specialists._claude_available():
        model = settings.claude_model if settings.claude_model in CLAUDE_MODELS else CLAUDE_MODELS[0]
        out.append(Candidate("claude", model, {"tools", "vision", "thinking", "code"}, 100))
    for c in load_connections():
        if c.kind != "llm" or not c.usable or any(h in c.base_url for h in ("localhost", "127.0.0.1")):
            continue  # anahtarsız ya da anahtarı reddedilmiş bağlantı otomatik seçilmez
        # katalogdaki önerilen model (hesapta varsa); katalogda olmayan firmada listenin ilki
        provider = catalog.by_host(c.base_url)
        featured = [m for m, _ in provider.chat] if provider else []
        m = next((m for m in featured if not c.models or m in c.models), None) or (c.models[0] if c.models else None)
        if m:
            out.append(Candidate(f"api:{c.id}", m, {"tools", "vision", "code"}, 90 if provider else 70))
    return out


def candidates(settings: Settings, refresh: bool = False) -> list[Candidate]:
    """Kullanılabilir tüm modeller (kısa süre önbellekte tutulur)."""
    from .cekirdek import yonlendirici

    global _cache
    now = time.time()
    local_only = yonlendirici.gizlilik(settings) == "yerel"  # K3: gizlilik "yalnızca yerel" → bulut otomatik seçilmez
    key = (settings.ollama_url, power.saving(settings), local_only)  # fişe takılınca/çıkınca puanlar değişir
    if not refresh and _cache and now - _cache[0] < CACHE_SECONDS and _cache[1] == key:
        return _cache[2]
    found = _ollama(settings) + ([] if local_only else _cloud(settings))
    _cache = (now, key, found)
    return found


def _loaded(settings: Settings) -> set[str]:
    """Şu an ekran kartında yüklü yerel modeller (aynı kartta ikinci modeli yüklememek için)."""
    try:
        resp = httpx.get(settings.ollama_url.rstrip("/") + "/api/ps", timeout=2)
        return {m.get("name", "") for m in resp.json().get("models", [])}
    except Exception:
        return set()


def default(settings: Settings, kind: str) -> Candidate | None:
    """Üst menüden seçilen varsayılan model ("online", "code", "offline"); seçilmemişse None."""
    value = settings.defaults.get(kind, "")
    if "|" not in value:
        return None
    provider, model = value.split("|", 1)
    if cli_agents.is_cli(provider):  # aboneliğinle çalışan resmi program (Claude Code, Codex, Gemini CLI)
        if not cli_agents.available(provider):
            return None
        return Candidate(provider, model, {"tools", "code", "thinking", "vision"}, 95)
    if provider.startswith("api:"):  # seçilen bağlantı silinmiş, anahtarsız ya da anahtarı reddedilmiş: otomatiğe dön
        from .connections import load_connections

        conn = next((c for c in load_connections() if c.id == provider[4:]), None)
        if conn is None or not conn.usable:
            return None
    found = next((c for c in candidates(settings) if c.key == (provider, model)), None)
    if found and found.local and found.params > power.BATTERY_MAX_PARAMS and power.saving(settings) \
            and not model_updates.is_uncensored(found.model):
        return None  # hafif modda (pil, ekran kartı hatası) büyük yerel model yerine otomatik seçilen küçük model
    if found:
        return found
    if provider == "ollama":
        caps = set(specialists._capabilities(settings.ollama_url, model)) - {"completion", "insert"}
        return Candidate(provider, model, caps, 0, local=True)
    if provider == "claude" and not specialists._claude_available():
        return None
    return Candidate(provider, model, {"tools", "vision", "code"}, 90)  # bulut: araç ve görme var sayılır


def pick(settings: Settings, need: set | None = None, prefer: set | None = None,
         providers: set | None = None) -> Candidate | None:
    """İhtiyaca en uygun model.

    need: şart olan yetenekler (ör. {"tools"}); prefer: varsa tercih edilenler (ör. {"code"});
    providers: yalnızca bu sağlayıcılar (sürmekte olan sohbetin biçimi değişmesin diye).
    """
    need, prefer = need or set(), prefer or set()

    def usable(c: Candidate | None) -> bool:
        return c is not None and need <= c.caps and (providers is None or c.provider in providers)

    code = default(settings, "code") if "code" in prefer else None
    if usable(code):
        return code
    # sansürsüz modeller otomatik seçilmez: yalnızca kullanıcı menüden seçerse (varsayılan yaparsa) kullanılır
    # sansürsüz modda yalnızca sansürsüz modeller; normalde sansürsüzler otomatik seçilmez (kullanıcı seçerse kullanılır)
    only_free = bool(settings.extra.get("uncensored_only"))
    pool = [c for c in candidates(settings) if need <= c.caps and (providers is None or c.provider in providers)
            and model_updates.is_uncensored(c.model) == only_free]
    if not pool:
        return None
    local_first = settings.model_policy != "guclu"
    loaded = _loaded(settings) if any(c.local for c in pool) else set()

    def rank(c: Candidate):
        return (
            c.local if local_first else 0,
            len(prefer & c.caps),
            round(c.score),
            c.model in loaded,  # eşitlikte yüklü olan: modeller arasında gidip gelmesin
        )

    best = max(pool, key=rank)
    # seçilen varsayılan, aynı taraftaki (yerel/bulut) otomatik seçimin yerine geçer
    chosen = default(settings, "offline" if best.local else "online")
    return chosen if usable(chosen) else best


def needs_for(profile: AgentProfile | None) -> tuple[set, set]:
    """Ajanın işi için (şart, tercih) yetenekleri."""
    tools = None if profile is None else profile.tools
    need = {"tools"}  # her ajan en azından danışma araçlarını (resme bak, uzmana danış) kullanır
    prefer = set()
    # kod tercihi yalnızca kod işi yapan ajanlarda (ana asistan her işi yapar; Kod menüsü onu ele geçirmesin)
    if profile is not None and (profile.id == "kod" or any(t in (tools or []) for t in ("run_python", "edit_file"))):
        prefer.add("code")
    if tools and ("look_at_image" in tools or "browser_look" in tools):
        prefer.add("vision")
    if profile is None or profile.id in ("yonetici",):
        prefer.add("thinking")
    return need, prefer


def pick_for(settings: Settings, profile: AgentProfile | None, providers: set | None = None) -> Candidate | None:
    """Ajanın kendi modeli yoksa işine uygun model."""
    need, prefer = needs_for(profile)
    # üst menüden seçilen alan (Online / Kod / Offline) etkinse onun modeli; kod ajanı yine Kod varsayılanını alır
    active = default(settings, settings.active_kind) if settings.active_kind else None
    code = default(settings, "code") if "code" in prefer else None
    if active and not code and (providers is None or active.provider in providers):
        # ana asistan açık seçime uyar (araç kullanamayan modelde işleri uzmanlara verir); ajanlar araç ister
        if profile is None or need <= active.caps:
            return active
    return pick(settings, need, prefer, providers) or pick(settings, set(), prefer, providers)


def assign(settings: Settings, profile: AgentProfile | None, fallback: tuple[str, str]) -> tuple[str, str]:
    """(sağlayıcı, model): ajanın kendi modeli > otomatik seçim > verilen yedek."""
    if profile and profile.provider:
        return profile.provider, profile.model
    if settings.auto_model and settings.model_policy != "guclu":  # bulut önceliğinde genel seçim (bulut) geçerli
        from . import categories

        cat = categories.category_of(profile)
        if cat and cat.id == "problem" and default(settings, "code"):
            cat = None  # kod için seçilen model (ör. Claude Code) yerel listeden önce gelir
        found = categories.model_for(settings, cat) if cat else None
        if found:
            return found  # kategorinin bu bilgisayar için sıralı listesinden kurulu, araç kullanan ilk model
    if settings.auto_model:
        found = pick_for(settings, profile)
        if found:
            return found.key
    return fallback


# ---------------------------------------------------------------- yönetici ve işçi (Aşama 3: kartlarla)

def _tools_ok(settings: Settings, model: str) -> int:
    """Kart varsa sınav sonucu; yoksa Ollama beyanı (araç var diyorsa 2 sayılır, sınanınca düzelir)."""
    level = cards.tools_level(model)
    if level is not None:
        return level
    return 2 if "tools" in specialists._capabilities(settings.ollama_url, model) else 0


def worker_for(settings: Settings, chat: tuple[str, str]) -> tuple[str, str] | None:
    """İşi yapacak (araç çağıracak) model. Sohbet modeli araç sınavını geçtiyse kendisi (ekran kartında modeller
    arasında gidip gelinmesin); geçemediyse sınavı geçen en uygun yerel model. Hiçbiri yoksa None.

    Sansürsüz modelle sohbette önce sansürsüz işçi seçilir (içeriği reddetmesin)."""
    provider, model = chat
    if provider != "ollama":
        return chat  # bulut modelleri araç kullanır
    own = _tools_ok(settings, model)
    if own == 2:
        return chat
    free = model_updates.is_uncensored(model)
    pool = [c for c in candidates(settings) if c.local and c.model != model and cards.tools_level(c.model) == 2]
    if not pool:
        return chat if own == 1 else None
    best = max(pool, key=lambda c: (model_updates.is_uncensored(c.model) == free, round(c.score)))
    return best.key


def manager_for(settings: Settings, chat: tuple[str, str], policy: str | None = None) -> tuple[str, str]:
    """Plan çıkarıp denetleyecek model. Karar yönlendiricinin "yönetici" rolünde (`cekirdek/yonlendirici.py`,
    politika otomatik | yerel | bulut); model bulunamazsa sohbet modeli."""
    from .cekirdek import yonlendirici

    secim = yonlendirici.yonetici_sec(settings, chat, politika_=policy)
    return secim.anahtar or tuple(chat)


def stronger(settings: Settings, current: tuple[str, str]) -> Candidate | None:
    """Başarısız bir adımı devralacak daha güçlü model: yönlendiricinin yedekleme zincirinde bir üst basamak
    (`yonlendirici.daha_guclu`; kurallar orada)."""
    from .cekirdek import yonlendirici

    return yonlendirici.daha_guclu(settings, current)
