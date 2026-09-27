"""Tek ayar kaynağı: programın klasörleri, `ayarlar.json` (Settings) ve üstünde `ayar.toml` + `CAFER_*` ortam değişkenleri.

Öncelik (düşükten yükseğe): `VARSAYILAN` → `ayarlar.json` (arayüzün yazdığı ayarlar) → `ayar.toml` → `CAFER_<BOLUM>_<ANAHTAR>`.
`ayar.toml` ve ortam değişkenleri isteğe bağlıdır (docs/SEMALAR.md §5); ikisi de yoksa davranış eskisiyle aynıdır.
Ezilen değerler `ayarlar.json`'a yazılmaz: sunucuda `CAFER_SAGLAYICI_OLLAMA_URL` vermek kullanıcının dosyasını değiştirmez.
Eski yol `asistan.config` aynı nesneleri dışa aktarır.
"""

import json
import logging
import os
import shutil
import tomllib
from dataclasses import asdict, dataclass, field
from pathlib import Path

from . import modeller

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

_gunluk = logging.getLogger(__name__)


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

# ---- ayar.toml + CAFER_* ----

ORTAM_ONEKI = "CAFER_"
DOSYA_ORTAMI = "CAFER_AYAR_DOSYASI"  # ayar.toml başka yerdeyse (sunucu); bölüm/anahtar olarak okunmaz

# docs/SEMALAR.md §5; anahtarlar "bolum.alt_bolum.anahtar" biçiminde düz
VARSAYILAN: dict = {
    "genel.dil": "tr",
    "genel.calisma_klasoru": "",  # boş: Settings.workspace (arayüzde seçilen klasör)
    "genel.kademe_kilidi": "",  # boş: otomatik (K2)
    "gizlilik.mod": "karma",  # yerel | karma | bulut (K3)
    "bulut.gunluk_tavan_token": 200000,
    "bulut.gorev_tavan_token": 40000,
    "saglayici.ollama.url": "http://localhost:11434",
    "saglayici.claude.anahtar_env": "ANTHROPIC_API_KEY",
    "saglayici.openai_uyumlu.url": "",
    "saglayici.openai_uyumlu.anahtar_env": "OPENAI_API_KEY",
    "cli_ajan.tercih": ["claude", "codex", "gemini"],
    "sunucu.port": 8765,
    "sunucu.token_env": "CAFER_TOKEN",
}

# ayar.toml / ortamda AÇIKÇA verilirse Settings alanını ezen anahtarlar (varsayılanlar ezmez)
ESLEME = {
    "genel.calisma_klasoru": "workspace",
    "saglayici.ollama.url": "ollama_url",
}


def ayar_dosyasi() -> Path:
    yol = os.environ.get(DOSYA_ORTAMI, "").strip()
    return Path(yol).expanduser() if yol else CONFIG_DIR / "ayar.toml"


def _duzlestir(veri: dict, onek: str = "") -> dict:
    duz = {}
    for anahtar, deger in veri.items():
        ad = f"{onek}{anahtar}"
        if isinstance(deger, dict):
            duz.update(_duzlestir(deger, ad + "."))
        else:
            duz[ad] = deger
    return duz


def dosyadan() -> dict:
    """`ayar.toml` içeriği (düz). Dosya yoksa ya da bozuksa boş (bozuksa günlüğe yazılır, program açılır)."""
    yol = ayar_dosyasi()
    try:
        with yol.open("rb") as f:
            return _duzlestir(tomllib.load(f))
    except FileNotFoundError:
        return {}
    except (OSError, tomllib.TOMLDecodeError) as e:
        _gunluk.warning("ayar.toml okunamadı (%s): %s", yol, e)
        return {}


def _cevir(metin: str, ornek):
    """Ortam değişkeninin metnini bilinen değerin türüne çevirir (bilinmiyorsa JSON dener, olmazsa metin)."""
    metin = metin.strip()
    if isinstance(ornek, bool):
        return metin.lower() in ("1", "true", "evet", "yes", "on", "acik", "açık")
    if isinstance(ornek, int):
        try:
            return int(metin)
        except ValueError:
            return ornek
    if isinstance(ornek, float):
        try:
            return float(metin)
        except ValueError:
            return ornek
    if isinstance(ornek, list):
        if metin.startswith("["):
            try:
                return list(json.loads(metin))
            except ValueError:
                pass
        return [p.strip() for p in metin.split(",") if p.strip()]
    if isinstance(ornek, str):
        return metin
    try:
        return json.loads(metin)
    except ValueError:
        return metin


def _ortam_adi(anahtar: str) -> str:
    return ORTAM_ONEKI + anahtar.replace(".", "_").upper()


def ortamdan(bilinen: dict | None = None) -> dict:
    """`CAFER_<BOLUM>_<ANAHTAR>` değişkenleri (düz). Bölüm adı bilinen anahtarlardan çözülür
    (`CAFER_SAGLAYICI_OLLAMA_URL` → `saglayici.ollama.url`); bilinmeyenler ilk alt çizgiden bölünür."""
    bilinen = {**VARSAYILAN, **(bilinen or {})}
    adlar = {_ortam_adi(k): k for k in bilinen}
    bolumler = sorted({k.rsplit(".", 1)[0] for k in bilinen if "." in k}, key=len, reverse=True)
    sonuc = {}
    for ad, metin in os.environ.items():
        if not ad.startswith(ORTAM_ONEKI) or ad == DOSYA_ORTAMI:
            continue
        anahtar = adlar.get(ad)
        if anahtar is None:
            kalan = ad[len(ORTAM_ONEKI):].lower()
            bolum = next((b for b in bolumler if kalan.startswith(b.replace(".", "_") + "_")), None)
            if bolum:
                anahtar = f"{bolum}.{kalan[len(bolum) + 1:]}"
            elif "_" in kalan:
                bas, son = kalan.split("_", 1)
                anahtar = f"{bas}.{son}"
            else:
                continue  # bölümsüz (ör. CAFER_TOKEN: sunucu anahtarının kendisi, ayar değil)
        sonuc[anahtar] = _cevir(metin, bilinen.get(anahtar))
    return sonuc


def acik_degerler() -> dict:
    """Kullanıcının `ayar.toml` ya da ortamla açıkça verdiği değerler (varsayılanlar hariç)."""
    dosya = dosyadan()
    return {**dosya, **ortamdan(dosya)}


def oku() -> dict:
    """Bütün ayarlar (düz): varsayılan ← ayar.toml ← CAFER_*."""
    return {**VARSAYILAN, **acik_degerler()}


def deger(anahtar: str, varsayilan=None):
    """Tek ayar: `deger("genel.kademe_kilidi")`."""
    return oku().get(anahtar, VARSAYILAN.get(anahtar, varsayilan))


def _ezilenler() -> dict:
    """Settings alanı → ayar.toml/ortamdan gelen değer (yalnızca açıkça verilenler)."""
    acik = acik_degerler()
    ezilen = {}
    for anahtar, alan in ESLEME.items():
        if anahtar in acik and acik[anahtar] not in ("", None):
            deger_ = acik[anahtar]
            if alan == "workspace":
                deger_ = str(Path(str(deger_)).expanduser())
            ezilen[alan] = deger_
    return ezilen


# ---- ayarlar.json (arayüzün yazdığı ayarlar; biçimi değişmez) ----


@dataclass
class Settings:
    provider: str = "ollama"  # "ollama" veya "claude"
    # yeni kurulumda pakete gömülü temel model (sysinfo.BASE_MODEL); adlar ayar/modeller.json → varsayilan
    ollama_model: str = field(default_factory=lambda: modeller.deger("varsayilan.ollama"))
    claude_model: str = field(default_factory=lambda: modeller.deger("varsayilan.claude"))
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
            data = {}
        known = {k: v for k, v in data.items() if k in cls.__dataclass_fields__}
        known.update(_ezilenler())  # ayar.toml / CAFER_* en üstte
        return cls(**known)

    @staticmethod
    def exists() -> bool:
        """Ayar dosyası var mı? Yoksa program ilk kez açılıyordur (kurulum sihirbazı)."""
        return CONFIG_FILE.exists()

    def save(self) -> None:
        data = asdict(self)
        ezilen = _ezilenler()
        if ezilen:  # ayar.toml / ortamdan gelen değer dosyaya işlenmesin: dosyadaki eski değer korunur
            try:
                diskte = json.loads(CONFIG_FILE.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                diskte = {}
            for alan, deger_ in ezilen.items():
                if data.get(alan) == deger_:
                    if alan in diskte:
                        data[alan] = diskte[alan]
                    else:
                        data.pop(alan, None)
        CONFIG_DIR.mkdir(parents=True, exist_ok=True)
        CONFIG_FILE.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
        # API anahtarı içerebileceği için yalnızca kullanıcı okuyabilsin
        CONFIG_FILE.chmod(0o600)
