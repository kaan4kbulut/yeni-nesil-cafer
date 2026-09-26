"""Dosyayla tanımlanan ajanlar ve beceriler (Claude Code'daki `.claude/agents/*.md` ve `SKILL.md` biçimi).

Ajanlar: `~/.config/yeni-nesil-cafer/ajanlar/<ad>.md`
    ---
    name: Çevirmen
    description: Metinleri Türkçe ile İngilizce arasında çevirir
    tools: read_file, write_file          (Claude Code adları da olur: Read, Write, Edit, Bash, Grep, Glob…)
    model: qwen3.5:9b                     (isteğe bağlı; "sonnet", "inherit" gibi adlar yok sayılır → otomatik)
    category: dil                         (isteğe bağlı: categories.py)
    ---
    Talimat (modele verilen rol tarifi)…
Beceriler: `<klasör>/<ad>/SKILL.md` (frontmatter: name, description; gövde: tarif), üç kaynaktan, aynı adda
öncelik sırasıyla: kullanıcının (`~/.config/yeni-nesil-cafer/beceriler`), asistanın öğrendikleri (`learn_skill` →
`DATA_DIR/ogrenilen-beceriler`), programla gelenler (`asistan/beceriler`). Talimata yalnızca adlar ve açıklamalar
girer; model gerektiğinde `use_skill` ile tam metni alır. Asistan yalnızca kendi öğrendiklerini yazar/günceller.

Dosyalar kullanıcınındır: asistan çalışma klasörü dışına yazamaz, bu klasörleri yalnızca okuyabilir.
Programın kendi öğrendiği beceriler (learning.py, hafıza veritabanı) bunlardan ayrıdır.
"""

import re
from dataclasses import dataclass
from pathlib import Path

from .config import CONFIG_DIR, DATA_DIR
from .profiles import AgentProfile

AGENTS_DIR = CONFIG_DIR / "ajanlar"
SKILLS_DIR = CONFIG_DIR / "beceriler"  # kullanıcının
LEARNED_DIR = DATA_DIR / "ogrenilen-beceriler"  # asistanın araştırıp kaydettikleri (learn_skill)
BUILTIN_DIR = Path(__file__).resolve().parent / "beceriler"  # programla gelenler
LEARN_LIMIT = 4000  # öğrenilen tarif en çok bu kadar karakter (her seferinde talimata değil, istenince okunur)
SKILL_LIMIT = 12000  # use_skill'in döndürdüğü en çok karakter

# Claude Code araç adları → programın araçları (Claude Code için yazılmış ajan dosyaları da çalışsın)
CLAUDE_TOOLS = {"read": "read_file", "write": "write_file", "edit": "edit_file", "multiedit": "edit_file",
                "bash": "run_command", "grep": "search_files", "glob": "list_files", "ls": "list_files",
                "websearch": "web_search", "webfetch": "fetch_url"}


def parse(text: str) -> tuple[dict, str]:
    """`---` arasındaki `anahtar: değer` satırları ve gövde (YAML'ın bu kadarı yeter; paket gerekmez)."""
    m = re.match(r"\A---\s*\n(.*?)\n---\s*(?:\n|\Z)", text, re.S)
    if not m:
        return {}, text.strip()
    meta = {}
    for line in m.group(1).splitlines():
        key, sep, value = line.partition(":")
        if sep and key.strip() and not line.startswith((" ", "\t", "#")):
            meta[key.strip().lower()] = value.strip().strip("\"'")
    return meta, text[m.end():].strip()


def _tools(value: str) -> list | None:
    names = [n.strip() for n in re.split(r"[,\s]+", value.strip("[]")) if n.strip()]
    return [CLAUDE_TOOLS.get(n.lower(), n) for n in names] or None


def load_agents() -> list[AgentProfile]:
    """ajanlar/*.md dosyalarındaki ajanlar (bozuk ya da adsız dosyalar atlanır)."""
    found = []
    for path in sorted(AGENTS_DIR.glob("*.md")):
        try:
            meta, body = parse(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError):
            continue
        name = meta.get("name") or path.stem
        if not body:
            continue
        model = meta.get("model", "")
        local = ":" in model  # "qwen3.5:9b" gibi Ollama adı; "sonnet" / "inherit": program seçer
        found.append(AgentProfile(
            id="dosya-" + re.sub(r"[^\w-]+", "-", path.stem.lower()).strip("-"), name=name,
            icon=meta.get("icon") or "bot", description=meta.get("description", ""), prompt=body,
            tools=_tools(meta["tools"]) if meta.get("tools") else None,
            provider="ollama" if local else "", model=model if local else "", category=meta.get("category", ""),
            source=str(path)))
    return found


@dataclass
class Skill:
    name: str
    description: str
    path: Path
    source: str = "kullanıcı"  # kullanıcı · öğrenilen · hazır


def load_skills() -> list[Skill]:
    """Üç kaynaktaki beceriler; aynı ad birden çok yerdeyse öncelikli olan (kullanıcı > öğrenilen > hazır)."""
    skills: dict[str, Skill] = {}
    for folder, source in ((SKILLS_DIR, "kullanıcı"), (LEARNED_DIR, "öğrenilen"), (BUILTIN_DIR, "hazır")):
        for path in sorted(folder.glob("*/SKILL.md")):
            try:
                meta, _ = parse(path.read_text(encoding="utf-8"))
            except (OSError, UnicodeDecodeError):
                continue
            name = meta.get("name") or path.parent.name
            skills.setdefault(name.lower(), Skill(name, meta.get("description", ""), path, source))
    return list(skills.values())


def learn(name: str, description: str, recipe: str) -> str:
    """learn_skill: asistanın bulduğu yolu tarif olarak kaydeder (yalnızca kendi öğrendiklerine yazar)."""
    from . import security
    from .registry import safe_name

    slug = safe_name(name.strip().lower()).replace("_", "-")[:48]
    if not slug or not description.strip() or len(recipe.strip()) < 40:
        raise ValueError("A skill needs a short name, a one-line description and a real recipe (tools, steps, pitfalls).")
    if len(recipe) > LEARN_LIMIT:
        raise ValueError(f"Recipe too long ({len(recipe)} characters); keep it under {LEARN_LIMIT}: only what you "
                         "would need next time.")
    why = security.forbidden("run_command", {"command": recipe})
    if why:  # tarif ileride talimat olarak okunur: zararlı komut içeremez
        raise ValueError(f"Recipe refused: {why}.")
    import difflib

    skills = load_skills()
    taken = next((s for s in skills if s.name.lower() in (name.strip().lower(), slug)), None)
    if taken is None:  # "qr-kod-olustur" ile "qr-kod-olusturma" aynı beceri: yenisi eskisini günceller
        taken = next((s for s in skills if s.source == "öğrenilen" and (
            difflib.SequenceMatcher(None, s.name.lower(), slug).ratio() >= 0.85
            or s.name.lower().startswith(slug) or slug.startswith(s.name.lower()))), None)
        if taken is not None:
            slug = taken.path.parent.name
    if taken is not None and taken.source != "öğrenilen":
        raise ValueError(f"'{taken.name}' is the user's or a built-in skill; choose another name.")
    path = LEARNED_DIR / slug / "SKILL.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    one_line = " ".join(description.split())[:200]
    path.write_text(f"---\nname: {slug}\ndescription: {one_line}\n---\n{recipe.strip()}\n", encoding="utf-8")
    return f"{'Updated' if taken else 'Saved'} skill '{slug}'. It will be listed under Skills from now on."


def skills_prompt(skills: list[Skill]) -> str:
    """Talimata giren kısa liste: yalnızca adlar ve açıklamalar."""
    if not skills:
        return ""
    lines = "\n".join(f"- {s.name}: {s.description}" + (" (learned)" if s.source == "öğrenilen" else "")
                      for s in skills)
    return ("\n\n## Skills (tested recipes)\nWhen a request matches one of these, call use_skill with its name "
            "first and follow the recipe.\n" + lines)


def skill_text(name: str) -> str:
    """use_skill: becerinin tam metni ve klasöründeki diğer dosyalar (read_file ile okunabilir)."""
    skills = load_skills()
    key = name.strip().lower()
    skill = next((s for s in skills if key in (s.name.lower(), s.path.parent.name.lower())), None)
    if skill is None:
        return "Unknown skill. Available: " + (", ".join(s.name for s in skills) or "(none)")
    text = skill.path.read_text(encoding="utf-8")[:SKILL_LIMIT]
    extra = sorted(p for p in skill.path.parent.rglob("*") if p.is_file() and p != skill.path)[:30]
    if extra:
        text += "\n\nFiles of this skill (read them with read_file when the recipe needs them):\n" + \
            "\n".join(f"- {p}" for p in extra)
    return text


def save_skill_text(skill: Skill, text: str) -> None:
    """Arayüzden düzenlenen tarif (yalnızca öğrenilen ya da kullanıcının; hazırlar salt okunur)."""
    from . import security

    if skill.source == "hazır":
        raise ValueError("Programla gelen tarif değiştirilemez; aynı adla kendi tarifini yazarak yerine geçebilirsin.")
    meta, body = parse(text)
    if not meta.get("name") or not meta.get("description") or not body.strip():
        raise ValueError("Tarifin başında --- arasında name ve description, altında tarifin kendisi olmalı.")
    if skill.source == "öğrenilen" and len(body) > LEARN_LIMIT:
        raise ValueError(f"Öğrenilen tarif en çok {LEARN_LIMIT} karakter olabilir.")
    why = security.forbidden("run_command", {"command": body})
    if why:
        raise ValueError(f"Tarif kaydedilmedi: {why}.")
    skill.path.write_text(text.rstrip() + "\n", encoding="utf-8")


def delete_skill_dir(skill: Skill) -> None:
    """Tarifi siler (klasörüyle); hazırlar silinmez."""
    import shutil

    if skill.source == "hazır":
        raise ValueError("Programla gelen tarif silinemez.")
    root = LEARNED_DIR if skill.source == "öğrenilen" else SKILLS_DIR
    folder = skill.path.parent
    if folder.parent.resolve() != root.resolve():  # yalnızca kendi klasöründeki tarif klasörü
        raise ValueError("Beklenmeyen tarif yolu.")
    shutil.rmtree(folder)

