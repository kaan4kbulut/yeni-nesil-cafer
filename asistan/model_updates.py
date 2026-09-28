"""Günlük güncellenen model kataloğu: en iyi yerel (Ollama) ve bulut modelleri, ücretli ve ücretsiz.

İnternet varsa günde bir kez arka planda güncellenir (program açılışında ve kurulum sihirbazında):
- Yerel: ollama.com/library — her modelin yetenekleri (tools, vision, thinking…), boyutları, indirme sayısı,
  güncellenme zamanı; seçilen etiketlerin kesin indirme boyutu Ollama kayıt sunucusundan.
- Bulut: OpenRouter'ın herkese açık model listesi — firmaların güncel modelleri, fiyatları, ücretsiz olanlar.
İnternet yoksa son indirilen liste, o da yoksa sysinfo.LADDERS (programla gelen liste) kullanılır.
"""

import json
import re
import time

import httpx

from .cekirdek import modeller
from .config import DATA_DIR

CACHE = DATA_DIR / "model_katalogu.json"
MAX_AGE = 20 * 3600  # günde bir: 20 saatten eskiyse yenile
VERSION = 3  # listenin biçimi; program yeni bilgi (sıralama, etiket) istediğinde yaşına bakılmadan yenilenir
FAMILIES_PER_CAPABILITY = 3

CAPABILITIES = {
    "chat": ("Sohbet ve görevler", "araç kullanır: dosya, komut, web"),
    "vision": ("Resim görme", "fotoğraf, ekran görüntüsü, taranmış belge"),
    "code": ("Kod", "yazılım, hata ayıklama"),
    "reasoning": ("Derin düşünme", "zor problem, matematik, plan"),
}
# Online menüdeki uzmanlıklar: LMArena sıralaması (kullanıcı oylarıyla; günlük) → (başlık, açıklama)
ARENA = {
    "text": ("Genel sohbet", "yazı, soru-cevap, genel bilgi"),
    "agent": ("Ajan · araç kullanma", "çok adımlı işler, komut, dosya"),
    "webdev": ("Kod", "yazılım ve web geliştirme"),
    "vision": ("Görme", "resim, ekran görüntüsü"),
    "document": ("Belge", "uzun belge okuma ve anlama"),
    "search": ("Arama · araştırma", "web'de araştırıp kaynaklı cevap"),
}
# Offline menüdeki ek uzmanlıklar (CAPABILITIES'e ek; yalnızca menüde gösterilir)
LOCAL_EXTRA = {
    "ocr": ("Belge okuma (OCR)", "taranmış belge, fatura, tablo"),
    "embedding": ("Belge arama (embedding)", "kendi dosyalarında anlamsal arama"),
}
# LMArena kuruluş adı → OpenRouter kimlik öneki (eşleştirme için)
ARENA_ORGS = {"anthropic": "anthropic", "openai": "openai", "google": "google", "xai": "x-ai", "alibaba": "qwen",
              "deepseek": "deepseek", "moonshot": "moonshotai", "meta": "meta", "mistral": "mistralai",
              "zhipu": "z-ai", "tencent": "tencent", "minimax": "minimax"}
# bulutta izlenen firmalar: OpenRouter kimlik öneki → görünen ad
CLOUD_VENDORS = {"anthropic/": "Anthropic · Claude", "openai/": "OpenAI · GPT", "google/": "Google · Gemini",
                 "x-ai/": "xAI · Grok", "deepseek/": "DeepSeek", "mistralai/": "Mistral", "qwen/": "Alibaba · Qwen"}
# kalıcı ücretsiz kota veren sağlayıcılar (Eylül 2026 araştırması; ayrıntılar sık değişir)
FREE_TIERS = [
    ("Google AI Studio (Gemini)", "kart gerekmez; Gemini Flash modelleri, günlük istek sınırıyla", "google"),
    ("Groq", "kart gerekmez; GPT-OSS 120B, Llama 3.3 70B; çok hızlı", "groq"),
    ("Mistral", "kart gerekmez; Mistral Small/Medium ve Codestral, aylık kota", "mistral"),
    ("OpenRouter", "kart gerekmez; “:free” modeller, günde 50 istek", "openrouter"),
]


def _days(text: str) -> float:
    """"3 weeks ago" → 21 gün (yaklaşık); "yesterday" → 1."""
    text = (text or "").replace("\xa0", " ").lower()
    if "yesterday" in text or "today" in text or "just now" in text:
        return 1
    m = re.search(r"(\d+|an?)\s+(minute|hour|day|week|month|year)", text or "")
    if not m:
        return 9999
    n = 1 if m.group(1) in ("a", "an") else int(m.group(1))
    return n * {"minute": 1 / 1440, "hour": 1 / 24, "day": 1, "week": 7, "month": 30, "year": 365}[m.group(2)]


def _pulls(text: str) -> float:
    m = re.match(r"([\d.]+)([KMB]?)", text or "")
    if not m:
        return 0.0
    return float(m.group(1)) * {"": 1e-6, "K": 1e-3, "M": 1, "B": 1e3}[m.group(2)]  # milyon


def _parse_library(html: str) -> list[dict]:
    from bs4 import BeautifulSoup

    out = []
    for a in BeautifulSoup(html, "html.parser").select('a[href^="/library/"]'):
        name = a["href"].split("/")[-1]
        if not name or "/" in a["href"][9:]:
            continue
        spans = [s.get_text(strip=True) for s in a.select("span.rounded-md")]
        sizes = [s for s in spans if re.fullmatch(r"e?[\d.]+[bm]|\d+x[\d.]+b", s)]
        caps = [s for s in spans if s not in sizes]
        text = a.get_text(" ", strip=True).replace("\xa0", " ")
        pulls = re.search(r"([\d.]+[KMB]?)\s*Pulls", text)
        updated = re.search(r"Updated\s+(.{1,20}?ago|yesterday|today)", text)
        out.append({"name": name, "caps": caps, "sizes": sizes, "pulls": _pulls(pulls.group(1) if pulls else ""),
                    "days": _days(updated.group(1) if updated else "")})
    return out


def _capability(entry: dict, cap: str) -> bool:
    name, caps = entry["name"], entry["caps"]
    if cap == "embedding":
        return "embedding" in caps
    if cap == "ocr":
        return "ocr" in name
    if "embedding" in caps or not entry["sizes"]:
        return False
    if cap == "code":
        return any(k in name for k in ("coder", "codestral", "devstral"))
    if cap == "chat":
        return "tools" in caps and "coder" not in name
    return {"vision": "vision", "reasoning": "thinking"}[cap] in caps


def _score(entry: dict) -> float:
    """Yeni ve çok kullanılan önde: indirme sayısı yaşla hızla azalır (1 yıllık popüler model, yeni kuşağın
    gerisinde kalır). Birden çok yeteneği bir arada taşıyanlar biraz öne çıkar."""
    breadth = 1 + 0.15 * len({"tools", "vision", "thinking", "audio"} & set(entry["caps"]))
    return breadth * entry["pulls"] / (1 + entry["days"] / 30) ** 1.5


def _tag_size(name: str, tag: str) -> float | None:
    """Kayıt sunucusundan kesin indirme boyutu (GB). Topluluk modelleri "hesap/model" adıyla gelir."""
    path = name if "/" in name else f"library/{name}"
    try:
        resp = httpx.get(f"https://registry.ollama.ai/v2/{path}/manifests/{tag}", timeout=8,
                         headers={"Accept": "application/vnd.docker.distribution.manifest.v2+json"})
        if resp.status_code != 200:
            return None
        return round(sum(layer["size"] for layer in resp.json().get("layers", [])) / 1e9, 1)
    except Exception:
        return None


def _local(html: str) -> dict:
    """Yetenek → [(model:etiket, GB)] — en iyi 3 aile, her aile küçükten büyüğe."""
    from concurrent.futures import ThreadPoolExecutor

    entries = _parse_library(html)
    picked = {cap: sorted((e for e in entries if _capability(e, cap)), key=_score, reverse=True)
              [:FAMILIES_PER_CAPABILITY] for cap in [*CAPABILITIES, *LOCAL_EXTRA]}
    # boyut etiketi olmayan (tek sürüm) aileler: "latest"
    tags = {(f["name"], t) for fams in picked.values() for f in fams for t in (f["sizes"] or ["latest"])}
    with ThreadPoolExecutor(8) as pool:  # boyutları paralel sor
        sizes = dict(zip(tags, pool.map(lambda nt: _tag_size(*nt), tags)))
    ladders = {}
    for cap, fams in picked.items():
        ladders[cap] = [(f"{f['name']}:{t}", sizes[(f["name"], t)], f["name"]) for f in fams
                        for t in (f["sizes"] or ["latest"])
                        if sizes.get((f["name"], t)) and sizes[(f["name"], t)] <= 40]  # ev bilgisayarına anlamlı
    return ladders


def _cloud(models: list[dict]) -> dict:
    """Firma başına en yeni modeller ve ücretsiz modeller (fiyat: 1M token başına $)."""
    def row(m: dict) -> dict:
        price = m.get("pricing", {})
        inputs = m.get("architecture", {}).get("input_modalities") or []
        params = m.get("supported_parameters") or []
        return {"id": m["id"], "name": m.get("name", m["id"]), "created": m.get("created", 0),
                "in": round(float(price.get("prompt") or 0) * 1e6, 2),
                "out": round(float(price.get("completion") or 0) * 1e6, 2),
                "vision": "image" in inputs, "audio": "audio" in inputs, "tools": "tools" in params,
                "reasoning": "reasoning" in params, "ctx": m.get("context_length") or 0}

    # sohbet modelleri: metin üretenler (resim/ses üreten modeller hariç), toplu iş ve gizli sürümler hariç
    usable = [m for m in models if ":batch" not in m["id"] and not m["id"].startswith("stealth/")
              and (m.get("architecture", {}).get("output_modalities") or ["text"]) == ["text"]]
    vendors = {}
    for prefix, label in CLOUD_VENDORS.items():
        ms = [row(m) for m in usable if m["id"].startswith(prefix) and ":free" not in m["id"]]
        if not ms:
            continue
        # tek bir "en iyi" yanıltıcı: son 4 ayın modellerinden en yeni, en üst seviye (en pahalı) ve en ucuz
        newest = max(ms, key=lambda r: r["created"])
        recent = [r for r in ms if r["created"] >= newest["created"] - 120 * 86400]
        vendors[label] = {"newest": newest, "top": max(recent, key=lambda r: (r["in"] + r["out"], r["created"])),
                          "cheap": min(recent, key=lambda r: (r["in"] + r["out"], -r["created"]))}
    free = [row(m) for m in usable
            if (m.get("pricing", {}).get("prompt") in ("0", 0)) and (m.get("pricing", {}).get("completion") in ("0", 0))]
    free.sort(key=lambda r: -r["created"])
    # LMArena adlarını OpenRouter kimliklerine bağlamak için: sadeleştirilmiş ad → model (ücretli sürüm öncelikli)
    index = {}
    for m in usable:
        index.setdefault(_norm(m["id"]), row(m))
    return {"vendors": vendors, "free": free[:10], "index": index}


def _norm(name: str) -> str:
    """Model adını karşılaştırma için sadeleştir: düşünme düzeyi ekleri ve biçim farkları atılır.
    "<ad>-5-high" ve "<Ad> 5 (High)" → "<ad>-5"; "<ad>-5.1" → "<ad>-5-1"."""
    name = name.lower().split("/")[-1].replace(":free", "")
    name = re.sub(r"\s*\((x?high|max|medium|low|thinking[^)]*)\)", "", name)
    name = re.sub(r"[-_ ](x?high|max|medium|low|minimal|thinking)$", "", name)
    return re.sub(r"[ ._]+", "-", name).strip("-")


def _arena() -> dict:
    """LMArena sıralamaları (Hugging Face veri seti, günlük): uzmanlık → [{name, org, open, rank}] (ilk 100)."""
    out = {}
    for cfg in ARENA:
        try:
            resp = httpx.get("https://datasets-server.huggingface.co/rows", timeout=20, params={
                "dataset": "lmarena-ai/leaderboard-dataset", "config": cfg, "split": "latest",
                "offset": 0, "length": 100})
            rows = [r["row"] for r in resp.json().get("rows", [])]
        except Exception:
            continue
        rows = sorted((r for r in rows if r.get("category") in (None, "overall")), key=lambda r: r.get("rank") or 999)
        seen, ranked = set(), []
        for r in rows:  # aynı modelin düşünme düzeyleri (high, max…) tek satır: en iyi sırası
            base = _norm(r["model_name"])
            if base in seen:
                continue
            seen.add(base)
            ranked.append({"name": base, "org": (r.get("organization") or "").lower(), "rank": len(ranked) + 1,
                           "open": (r.get("license") or "Proprietary") != "Proprietary"})
        out[cfg] = ranked[:40]
    return out


def arena_ranked(data: dict | None, category: str, limit: int = 10) -> list[dict]:
    """Uzmanlıkta en iyi `limit` bulut modeli; OpenRouter'daki karşılığı (kimlik, fiyat, ücretsiz) eklenmiş."""
    if not data:
        return []
    index = (data.get("cloud") or {}).get("index") or {}
    out = []
    for r in (data.get("arena") or {}).get(category, [])[:limit]:
        match = index.get(r["name"])
        if match is None:  # OpenRouter adında tarih/ek olabilir: önekle eşleştir
            match = next((v for k, v in index.items() if k.startswith(r["name"] + "-")), None)
        out.append({**r, "or": match})
    return out


def load() -> dict | None:
    try:
        return json.loads(CACHE.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def stale() -> bool:
    """Liste yok, eski biçimde ya da 20 saatten eski mi?"""
    data = load()
    return not data or data.get("v") != VERSION or time.time() - data.get("time", 0) >= MAX_AGE


def age_hours() -> float | None:
    data = load()
    return None if not data else (time.time() - data.get("time", 0)) / 3600


_UNRUNNABLE = re.compile(r"mlx|nvfp4|awq|gptq|exl2|safetensors", re.I)  # Ollama'nın burada çalıştıramadığı biçimler


def _parse_search(html: str) -> list[dict]:
    """ollama.com/search sonuçları (topluluk modelleri dahil): ad, yetenek, boyut, indirme, güncellik."""
    from bs4 import BeautifulSoup

    out = []
    for a in BeautifulSoup(html, "html.parser").select("a[href]"):
        href = a["href"]
        if not re.fullmatch(r"/[\w.-]+/[\w.-]+", href) or href.startswith(("/library/", "/search", "/blog", "/public")):
            continue
        name = href[1:]
        spans = [x.get_text(strip=True) for x in a.select("span")]
        sizes = [x for x in spans if re.fullmatch(r"e?[\d.]+[bm]", x)]
        text = " ".join(a.get_text(" ", strip=True).replace("\xa0", " ").split())
        caps = [c for c in ("tools", "vision", "thinking") if re.search(rf"\b{c}\b", text)]
        pulls = re.search(r"([\d.]+[KMB]?)\s*Pulls", text)
        updated = re.search(r"Updated\s+(.{1,20}?ago|yesterday|today)", text)
        out.append({"name": name, "caps": caps, "sizes": sizes, "pulls": _pulls(pulls.group(1) if pulls else ""),
                    "days": _days(updated.group(1) if updated else "")})
    return out


def _uncensored_roles(entry: dict) -> list[str]:
    """Bir model birden çok işe yarayabilir (ör. gemma-4: görme + araç + düşünme). İlk rol etikette görünür."""
    name, caps = entry["name"].lower(), entry["caps"]
    roles = []
    if "coder" in name or "code" in name:
        roles.append("code")
    if "tools" in caps or not caps:
        roles.append("chat")
    if "vision" in caps or re.search(r"-vl\b|vision|llava", name):
        roles.append("vision")
    if "thinking" in caps or re.search(r"\br1\b|-r1|reason|think", name):
        roles.append("reasoning")
    return roles or ["chat"]


def _uncensored_live() -> list[dict]:
    """Güncel sansürsüz modeller: her rol için en yeni/popüler aileler, ev bilgisayarına uygun boyutlar."""
    from concurrent.futures import ThreadPoolExecutor

    entries: dict[str, dict] = {}
    # sitenin kendi arayüzü gibi (htmx) istenince popülerlik sıralaması ve sayfalama çalışıyor
    for q in ("abliterated", "uncensored", "dolphin", "heretic"):
        for page in (1, 2, 3):
            html = httpx.get("https://ollama.com/search", params={"q": q, "o": "popular", "page": page}, timeout=20,
                             follow_redirects=True, headers={"HX-Request": "true"}).text
            found = _parse_search(html)
            for e in found:
                if (is_uncensored(e["name"]) or "heretic" in e["name"].lower()) and not _UNRUNNABLE.search(e["name"]):
                    entries.setdefault(e["name"], e)
            if len(found) < 20:
                break
    by_role: dict[str, list] = {}
    for e in sorted(entries.values(), key=_score, reverse=True):
        for role in _uncensored_roles(e):
            by_role.setdefault(role, []).append(e)
    picked = list({e["name"]: e for fams in by_role.values() for e in fams[:FAMILIES_PER_CAPABILITY]}.values())
    tags = [(e["name"], t) for e in picked for t in (e["sizes"] or ["latest"])]
    with ThreadPoolExecutor(8) as pool:
        sizes = dict(zip(tags, pool.map(lambda nt: _tag_size(*nt), tags)))
    out = []
    for e in picked:
        for t in (e["sizes"] or ["latest"]):
            gb = sizes.get((e["name"], t))
            if gb and gb <= 40:
                note = " · ".join(filter(None, [", ".join(e["caps"]), f"{e['pulls'] * 1e3:.0f}B indirme"
                                                if e["pulls"] < 1 else f"{e['pulls']:.1f}M indirme"]))
                roles = _uncensored_roles(e)
                out.append({"model": f"{e['name']}:{t}", "size": gb, "role": roles[0], "roles": roles,
                            "note": note, "caps": e["caps"], "score": _score(e)})
    return out


def uncensored_models(live: dict | None = None) -> list[dict]:
    """Menü ve ekip için sansürsüz modeller: günlük güncel liste + (yoksa ya da eksikse) programdaki sabit liste."""
    live = live if live is not None else load()
    current = list((live or {}).get("uncensored") or [])
    seen = {u["model"] for u in current}
    return current + [u for u in UNCENSORED_MODELS if u["model"] not in seen]


def refresh(force: bool = False) -> dict | None:
    """Günde bir kez (ya da force) güncel listeyi indirir ve saklar; internet yoksa eskisi kalır."""
    data = load()
    fresh = data and data.get("v") == VERSION and time.time() - data.get("time", 0) < MAX_AGE
    if fresh and not force:
        return data
    try:
        html = httpx.get("https://ollama.com/library?sort=popular", timeout=20, follow_redirects=True).text
        local = _local(html)
        models = httpx.get("https://openrouter.ai/api/v1/models", timeout=20).json().get("data", [])
        cloud = _cloud(models)
    except Exception:
        return data  # internet yok ya da kaynak değişti: eldeki liste kullanılır
    if not any(local.values()):
        return data
    library = {e["name"]: [e["caps"], e["days"]] for e in _parse_library(html)}  # etiketler için
    try:
        uncensored = _uncensored_live()
    except Exception:
        uncensored = (data or {}).get("uncensored") or []  # arama alınamadı: eldeki liste kalır
    new = {"v": VERSION, "time": time.time(), "local": local, "cloud": cloud, "arena": _arena(), "library": library,
           "uncensored": uncensored}
    from .cekirdek.ayar import atomik_yaz

    atomik_yaz(CACHE, json.dumps(new, ensure_ascii=False, indent=1))  # K12-C1
    return new


# ---- etiketler: her modelin yanında kısa Türkçe etiketler (yetenek önce, sonra özellik)
_LOCAL_CAPS = {"tools": "araç", "vision": "görme", "thinking": "düşünme", "audio": "ses", "embedding": "arama"}
_FAST = ("flash", "mini", "lite", "instant", "haiku", "luna", "nano", "small", "turbo")


# Sansürsüz (filtresiz) modeller: reddetme davranışı kaldırılmış. Menüde uzmanlıklar arasında (Sansürsüz), "sansürsüz" etiketiyle;
# otomatik model seçimi ve güvenlik ajanı bunları kendiliğinden kullanmaz, yalnızca kullanıcı seçerse çalışır.
UNCENSORED = re.compile(r"abliterat|uncensor|dolphin|huihui|lexi|nsfw|unfilter|jailbreak|obliterat|heretic", re.I)
# role: sansürsüz modda hangi işi yapar (ekip ajanları ve uzmanlar da sansürsüz olsun); ayar/modeller.json
UNCENSORED_MODELS = modeller.deger("sansursuz")
UNCENSORED_ROLES = {"chat": "ana asistan", "code": "kod", "reasoning": "düşünme", "vision": "görme"}


def uncensored_team(installed: list[str], main: str) -> dict:
    """Sansürsüz ekip: rol → kurulu sansürsüz model (listede sıralı; kurulu değilse ana modele düşer, görme hariç)."""
    have = [u for u in uncensored_models() if u["model"] in installed or u["model"].split(":")[0] + ":latest" in installed]
    pick = lambda role: next((u["model"] for u in have if role in u.get("roles", [u["role"]])), "")  # noqa: E731
    return {"chat": main, "code": pick("code") or main, "reasoning": pick("reasoning") or main,
            "vision": pick("vision")}


def is_uncensored(model: str) -> bool:
    return bool(UNCENSORED.search(model or ""))


def hashtags(tags) -> str:
    """Etiketler her zaman # ile gösterilir: ["araç", "sadece sohbet"] → "#araç #sadece_sohbet"."""
    return " ".join("#" + t.strip().replace(" ", "_") for t in tags if t and t.strip())


def local_tags(model: str, size: float, live: dict | None, caps: set | None = None) -> list[str]:
    """Yerel model: yetenekler (Ollama kütüphanesi ya da kurulu modelin bildirdikleri), boyut, yenilik."""
    family = model.split(":")[0]
    known = ((live or {}).get("library") or {}).get(family)
    found = set(known[0]) if known else set()
    if caps:  # kurulu modelin kendi bildirdiği yetenekler (roster: tools, vision, thinking, code)
        found |= {"thinking" if c == "thinking" else c for c in caps}
    tags = [label for key, label in _LOCAL_CAPS.items() if key in found]
    if any(k in family for k in ("coder", "codestral", "devstral")) or "code" in found:
        tags.insert(0, "kod")
    if "ocr" in family:
        tags.insert(0, "OCR")
    if size:
        tags.append("hafif" if size <= 3 else "orta" if size <= 10 else "büyük")
    if known and known[1] < 60:
        tags.append("yeni")
    if is_uncensored(model):
        entry = next((u for u in uncensored_models(live) if u["model"] == model), {})
        for role in reversed([r for r in entry.get("roles", [entry.get("role", "")]) if r and r != "chat"]):
            tags.insert(0, UNCENSORED_ROLES[role])  # sansürsüz ekipteki görevleri (kod · düşünme · görme)
        if "tools" in entry.get("caps", []) and "araç" not in tags:
            tags.insert(0, "araç")
        tags.insert(0, "sansürsüz")  # her zaman ilk sırada görünsün
    return list(dict.fromkeys(tags))[:6]  # aynı etiket iki kez görünmesin


def cloud_tags(row: dict, live: dict | None) -> list[str]:
    """Bulut modeli: yetenekler (OpenRouter), uzmanlık (LMArena ilk 3), fiyat, hız, yenilik, açık model."""
    match = row.get("or") or {}
    tags = []
    if match.get("tools"):
        tags.append("araç")
    if match.get("vision"):
        tags.append("görme")
    if match.get("audio"):
        tags.append("ses")
    if match.get("reasoning"):
        tags.append("düşünme")
    arena = (live or {}).get("arena") or {}
    for cat, label in (("webdev", "kodda güçlü"), ("agent", "ajanda güçlü"), ("document", "belgede güçlü")):
        if any(r["name"] == row.get("name") and r["rank"] <= 3 for r in arena.get(cat, [])):
            tags.append(label)
    if match:
        total = (match.get("in") or 0) + (match.get("out") or 0)
        tags.append("ücretsiz" if total == 0 else "ucuz" if total <= 2 else "pahalı" if total >= 30 else "")
    if any(k in (match.get("id") or row.get("name", "")) for k in _FAST):
        tags.append("hızlı")
    if match.get("ctx", 0) >= 500_000:
        tags.append("uzun bağlam")
    if match.get("created") and time.time() - match["created"] < 60 * 86400:
        tags.append("yeni")
    if row.get("open"):
        tags.append("açık model")
    return [t for t in tags if t][:6]
