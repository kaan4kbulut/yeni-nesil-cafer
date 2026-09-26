"""Uygulama ayarları ve sohbet kayıtlarının diskteki yeri."""

import json
import os
import shutil
from dataclasses import asdict, dataclass, field
from pathlib import Path

APP_ID = "yeni-nesil-cafer"  # klasör ve kimlik adı
OLD_ID = "yerel-asistan"  # 2.2'ye kadarki adı: klasörleri ilk açılışta yeni ada taşınır (veri kaybolmasın)

if os.name == "nt":  # Windows: %APPDATA% (ayarlar) ve %LOCALAPPDATA% (sohbetler, görevler)
    _CONFIG_BASE = Path(os.environ.get("APPDATA", Path.home() / "AppData/Roaming"))
    _DATA_BASE = Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData/Local"))
else:
    _CONFIG_BASE = Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config"))
    _DATA_BASE = Path(os.environ.get("XDG_DATA_HOME", Path.home() / ".local/share"))
CONFIG_DIR = _CONFIG_BASE / APP_ID
DATA_DIR = _DATA_BASE / APP_ID


def migrate_dir(new: Path, old: Path) -> bool:
    """Eski adlı klasör varsa ve yenisi yoksa yeni ada taşır (aynı diskte anında; değilse kopyalar)."""
    if new.exists() or not old.is_dir():
        return False
    try:
        old.rename(new)
    except OSError:
        try:
            shutil.copytree(old, new)
        except OSError:
            return False
    return True


migrate_dir(CONFIG_DIR, _CONFIG_BASE / OLD_ID)
migrate_dir(DATA_DIR, _DATA_BASE / OLD_ID)
CONFIG_FILE = CONFIG_DIR / "ayarlar.json"
CHATS_DIR = DATA_DIR / "sohbetler"

CLAUDE_MODELS = [  # önerilen başta
    "claude-opus-5-5",
    "claude-fable-5-1",
    "claude-sonnet-5",
    "claude-haiku-4-5",
    "claude-opus-5",
]


@dataclass
class Settings:
    provider: str = "ollama"  # "ollama" veya "claude"
    ollama_model: str = "qwen3.5:4b"  # yeni kurulumda pakete gömülü temel model (sysinfo.BASE_MODEL)
    claude_model: str = "claude-opus-5"
    ollama_url: str = "http://localhost:11434"
    ollama_num_ctx: int = 8192  # 14B model + 16K bağlam 12 GB VRAM'e sığmaz
    anthropic_api_key: str = ""  # eski sürümlerden kalma; açılışta anahtar zincirine taşınır
    api_models: dict = field(default_factory=dict)  # API bağlantısı id -> seçili model
    workspace: str = str(Path.home() / "YeniNesilCafer")  # yeni kurulumda; mevcut ayarlardaki klasör korunur
    confirm_commands: bool = True
    approval_mode: str = "guvenlik"  # varsayılan "guvenlik": güvenlik ajanı onaylar · "kullanici": ▶ düğmesi + her adımda kullanıcıya sor
    chat_folders: list = field(default_factory=lambda: ["Genel"])  # sohbet klasörleri (sıralı)
    specialists: dict = field(default_factory=dict)  # rol -> "sağlayıcı|model" (boş: otomatik)
    auto_model: bool = True  # modelleri program seçer (ana asistan, ajanlar, yönetici)
    model_policy: str = "yerel"  # "yerel": önce ücretsiz yerel modeller · "guclu": en güçlü, bulut dahil
    defaults: dict = field(default_factory=dict)  # "online" | "code" | "offline" -> "sağlayıcı|model" (boş: otomatik)
    active_kind: str = ""  # üst menüden son seçilen alan; sohbet onun varsayılanıyla yapılır ("": otomatik)
    accent: str = "#F2A93B"  # vurgu rengi (kehribar)
    auto_ctx: bool = True  # Ollama bağlamını ekran kartına sığan en büyük değere ayarla
    ctx_probe: dict = field(default_factory=dict)  # "model|VRAM" -> ölçüm sonucu
    power_mode: str = "otomatik"  # "otomatik": pildeyken hafif model ve bağlam · "performans" · "tasarruf" (power.py)
    extra: dict = field(default_factory=dict)

    @classmethod
    def load(cls) -> "Settings":
        try:
            data = json.loads(CONFIG_FILE.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return cls()
        known = {k: v for k, v in data.items() if k in cls.__dataclass_fields__}
        return cls(**known)

    @staticmethod
    def exists() -> bool:
        """Ayar dosyası var mı? Yoksa program ilk kez açılıyordur (kurulum sihirbazı)."""
        return CONFIG_FILE.exists()

    def save(self) -> None:
        CONFIG_DIR.mkdir(parents=True, exist_ok=True)
        CONFIG_FILE.write_text(json.dumps(asdict(self), indent=2, ensure_ascii=False), encoding="utf-8")
        # API anahtarı içerebileceği için yalnızca kullanıcı okuyabilsin
        CONFIG_FILE.chmod(0o600)
