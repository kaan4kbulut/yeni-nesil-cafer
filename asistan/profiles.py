"""Yardımcı ajan tanımları: rol, model ve kullanabileceği araçlar."""

import json
import uuid
from dataclasses import asdict, dataclass, field

from .config import CONFIG_DIR

PROFILES_FILE = CONFIG_DIR / "ajanlar.json"


@dataclass
class AgentProfile:
    name: str
    icon: str = "bot"  # simge adı (gui/icons.py); eski profillerde emoji olabilir
    description: str = ""  # listede görünen kısa açıklama
    prompt: str = ""  # modele verilen rol tarifi
    tools: list | None = None  # None: tüm araçlar
    provider: str = ""  # boş: o an seçili sağlayıcı/model kullanılır
    model: str = ""
    id: str = field(default_factory=lambda: uuid.uuid4().hex[:10])
    category: str = ""  # categories.py: dil · goru · veri · ses · problem · otonom · uretken (boş: kategorisiz)
    source: str = ""  # boş: ajanlar.json · dolu: tanımlandığı .md dosyası (definitions.py; kaydedilmez)


def default_profiles() -> list[AgentProfile]:
    return [
        AgentProfile(
            id="kod", name="Kod yazıcı", icon="code",
            description="Kod yazar, hata ayıklar, çalıştırıp dener",
            prompt=(
                "You are an expert software engineer. Write clean, working code that follows the "
                "conventions of the existing project. Read the relevant files before changing them, "
                "make focused edits, and run the code or tests to verify your changes work. "
                "Explain what you changed briefly."
            ),
            tools=["list_files", "read_file", "search_files", "write_file", "edit_file", "run_command", "run_python"],
        ),
        AgentProfile(
            id="arastirmaci", name="Araştırmacı", icon="globe",
            description="Web'de araştırır, kaynaklarıyla özetler",
            prompt=(
                "You are a careful researcher. For every question, search the web, open and read the "
                "most relevant sources, cross-check facts between sources, and answer with a clear, "
                "well-structured summary. Always list the source URLs you used at the end. "
                "Say clearly when sources disagree or information could not be verified."
            ),
            tools=["web_search", "fetch_url", "write_file"],
        ),
        AgentProfile(
            id="dosya", name="Dosya düzenleyici", icon="folder",
            description="Çalışma klasörünü düzenler, dosyaları toplar",
            prompt=(
                "You organize files in the workspace. First list and inspect what is there, then "
                "propose a clear folder structure. Prefer moving and renaming over deleting; never "
                "delete files unless the user explicitly asks. Report exactly what you changed."
            ),
            tools=["list_files", "read_file", "search_files", "write_file", "run_command"],
        ),
        AgentProfile(
            id="gorsel", name="Görsel analist", icon="eye",
            description="Resim, ekran görüntüsü ve taranmış belgeleri inceler",
            prompt=(
                "You analyse images with look_at_image: photos, screenshots, charts, scanned documents. "
                "Look at every relevant image, transcribe any text exactly, describe what matters for the "
                "task, and extract data into tables or files when useful. Never say you cannot see images."
            ),
            tools=["list_files", "read_file", "search_files", "write_file", "look_at_image"],
        ),
        AgentProfile(
            id="ozet", name="Özetleyici", icon="pen",
            description="Metin, dosya ve sayfaları kısa ve net özetler",
            prompt=(
                "You write concise, accurate summaries. When given a file or URL, read it fully "
                "first. Start with a 2-3 sentence overview, then the key points as bullets. "
                "Keep the original meaning; do not add information that is not in the source."
            ),
            tools=["list_files", "read_file", "search_files", "fetch_url"],
        ),
    ]


def load_profiles() -> list[AgentProfile]:
    try:
        data = json.loads(PROFILES_FILE.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        profiles = default_profiles()
        _categorize(profiles)
        save_profiles(profiles)
        return profiles + _file_agents({p.id for p in profiles})
    profiles = []
    for item in data:
        known = {k: v for k, v in item.items() if k in AgentProfile.__dataclass_fields__}
        try:
            profiles.append(AgentProfile(**known))
        except TypeError:
            continue
    if _categorize(profiles):
        save_profiles(profiles)
    return profiles + _file_agents({p.id for p in profiles})


def _file_agents(taken: set) -> list[AgentProfile]:
    """ajanlar/*.md dosyalarındaki ajanlar (definitions.py); aynı kimlikteki json profili önce gelir."""
    from .definitions import load_agents

    return [p for p in load_agents() if p.id not in taken]


def _categorize(profiles: list[AgentProfile]) -> bool:
    """Ajanları yedi kategoriye bağlar ve eksik kategori ajanlarını bir kez ekler (sonra kullanıcı silebilir)."""
    from .categories import BROWSER_AGENT, upgrade

    marker = CONFIG_DIR / ".ajan-kategorileri"
    try:
        done = int(marker.read_text(encoding="utf-8").strip() or 0)
    except (OSError, ValueError):
        done = 0
    changed = False
    if done < 1:  # yedi kategori
        changed = upgrade(profiles)
    if done < 2 and not any(p.id == BROWSER_AGENT.id for p in profiles):  # tarayıcı ajanı (bir kez; silinirse gelmez)
        profiles.append(AgentProfile(**{k: getattr(BROWSER_AGENT, k) for k in AgentProfile.__dataclass_fields__}))
        changed = True
    if done < 3:  # ses ajanı: var olmayan piper sesi (fahrettin) ve yeniden indirilen whisper modeli düzeltildi
        from .categories import NEW_AGENTS

        new = next((a for a in NEW_AGENTS if a.id == "ses"), None)
        for p in profiles:
            if p.id == "ses" and new is not None and "tr_TR-fahrettin-medium" in p.prompt:  # kullanıcı değiştirmemiş
                p.prompt = new.prompt
                changed = True
    if done < 4:  # K5: tarayıcı ajanı ürün listelerini yapısal okur (browser_extract_items)
        from .categories import BROWSER_PROMPT_EXTRA, BROWSER_PROMPT_OLD

        for p in profiles:
            if p.id == "tarayici" and p.tools is not None and "browser_read" in p.tools \
                    and "browser_extract_items" not in p.tools:
                p.tools.insert(p.tools.index("browser_read") + 1, "browser_extract_items")
                if p.prompt == BROWSER_PROMPT_OLD:  # kullanıcı talimatı değiştirmemiş
                    p.prompt += BROWSER_PROMPT_EXTRA
                changed = True
    if done < 4:
        try:
            CONFIG_DIR.mkdir(parents=True, exist_ok=True)
            marker.write_text("4", encoding="utf-8")
        except OSError:
            pass
    return changed


def save_profiles(profiles: list[AgentProfile]) -> None:
    """ajanlar.json'a yazar; dosyadan gelen ajanlar yazılmaz (kaynakları kendi .md dosyaları)."""
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    PROFILES_FILE.write_text(
        json.dumps([asdict(p) for p in profiles if not p.source], indent=2, ensure_ascii=False), encoding="utf-8")
