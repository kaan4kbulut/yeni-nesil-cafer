"""Sistem taraması (ilk kurulum): işletim sistemi, işlemci, bellek, ekran kartı, disk ve Ollama durumu.

Buna göre bilgisayara uygun yerel modeller önerilir. Linux, Windows ve macOS'ta çalışır.
"""

import atexit
import os
import platform
import shutil
import subprocess
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path

import httpx

# Yerel model basamakları (Eylül 2026, Ollama kayıt sunucusunda doğrulandı; boyut = indirme GB).
# Her yetenekte zayıf sistemden güçlüye; (model, boyut, en az VRAM GB, ya da ekran kartı yoksa en az RAM GB)
# Pakete gömülü temel model: 8 GB RAM'li sıradan bir bilgisayarda bile çalışır; sohbet, araç kullanma, resim görme
# ve düşünme tek modelde (ollama show: completion · vision · tools · thinking)
BASE_MODEL = ("qwen3.5:4b", 3.4)  # 2b testlerde çok adımlı işlerde dosya bozdu; 4b aynı işleri doğru yaptı
APP_DIR = Path(__file__).resolve().parent.parent
BUNDLE_DIR = APP_DIR / "modeller"  # paketteki model dosyası ve Modelfile
OLLAMA_DIR = APP_DIR / "ollama"  # pakete gömülü Ollama (kurulum paketinden gelmişse)
LADDERS = {
    "chat": ("Sohbet ve görevler", "araç kullanır: dosya, komut, web", [
        ("qwen3:1.7b", 1.4, 0, 4), ("qwen3:4b", 2.5, 4, 8), ("qwen3:8b", 5.2, 6, 16),
        ("qwen3:14b", 9.3, 11, 32), ("qwen3:30b", 18.6, 20, 64)]),
    "vision": ("Resim görme", "fotoğraf, ekran görüntüsü, taranmış belge", [
        ("gemma3:4b", 3.3, 4, 8), ("qwen3-vl:8b", 6.1, 7, 16), ("gemma3:12b", 8.1, 11, 32)]),
    "code": ("Kod", "yazılım, hata ayıklama", [
        ("qwen2.5-coder:7b", 4.7, 6, 16), ("qwen2.5-coder:14b", 9.0, 11, 32), ("qwen3-coder:30b", 18.6, 20, 64)]),
    "reasoning": ("Derin düşünme", "zor problem, matematik, plan", [
        ("deepseek-r1:8b", 5.2, 6, 16), ("deepseek-r1:14b", 9.0, 11, 32), ("gpt-oss:20b", 13.8, 16, 64)]),
}
MODEL_SIZES = {m: size for _, _, ladder in LADDERS.values() for m, size, _, _ in ladder}


@dataclass
class Suggestion:
    kind: str  # "base" | chat | vision | code | reasoning (birden çok yetenekte aynı model: "chat+vision")
    title: str
    note: str
    model: str
    size: float
    checked: bool  # varsayılan seçili mi (temel, sohbet); diğerleri isteğe bağlı
    alternative: bool = False  # ana önerinin yanındaki seçenek (daha hafif ya da başka aile)


@dataclass
class SystemInfo:
    os_name: str = ""
    cpu: str = ""
    cores: int = 0
    ram_gb: float = 0.0
    gpu: str = ""
    vram_gb: float = 0.0
    disk_free_gb: float = 0.0
    ollama_installed: bool = False
    ollama_running: bool = False
    ollama_models: list = field(default_factory=list)
    laptop: bool = False  # pil var: pildeyken program hafif moda geçer (power.py)


def _run(cmd: list[str]) -> str:
    try:
        return subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=5).stdout.strip()
    except (OSError, subprocess.SubprocessError):
        return ""


def _os_name() -> str:
    if platform.system() == "Linux":
        try:
            return platform.freedesktop_os_release().get("PRETTY_NAME", "Linux")
        except OSError:
            return "Linux"
    if platform.system() == "Windows":
        return f"Windows {platform.release()}"
    if platform.system() == "Darwin":
        return f"macOS {platform.mac_ver()[0]}"
    return platform.system()


def _cpu() -> str:
    if Path("/proc/cpuinfo").exists():
        for line in Path("/proc/cpuinfo").read_text(errors="ignore").splitlines():
            if line.startswith("model name"):
                return line.split(":", 1)[1].strip()
    return platform.processor() or platform.machine()


def _gpu() -> tuple[str, float]:
    """(ad, VRAM GB). NVIDIA: nvidia-smi; AMD (Linux): sysfs; Apple: birleşik bellek."""
    out = _run(["nvidia-smi", "--query-gpu=name,memory.total", "--format=csv,noheader,nounits"])
    if out:
        name, mib = out.splitlines()[0].rsplit(",", 1)
        return name.strip(), float(mib) / 1024
    for card in sorted(Path("/sys/class/drm").glob("card*/device/mem_info_vram_total")):
        try:
            return "AMD ekran kartı", int(card.read_text()) / 1024 ** 3
        except (OSError, ValueError):
            continue
    if platform.system() == "Darwin" and platform.machine() == "arm64":
        return "Apple Silicon (birleşik bellek)", 0.0
    return "", 0.0


def ollama_path() -> str:
    """Önce pakete gömülü Ollama, sonra PATH, sonra bilinen kurulum yerleri (PATH güncellenmemiş olabilir)."""
    candidates = [OLLAMA_DIR / "ollama.exe", OLLAMA_DIR / "bin" / "ollama"]
    found = shutil.which("ollama")
    if found:
        candidates.append(Path(found))
    if os.name == "nt":
        candidates += [Path(os.environ.get("LOCALAPPDATA", "")) / "Programs" / "Ollama" / "ollama.exe",
                       Path(os.environ.get("ProgramFiles", r"C:\Program Files")) / "Ollama" / "ollama.exe"]
    else:
        candidates += [Path("/usr/local/bin/ollama"), Path("/usr/bin/ollama"), Path("/opt/homebrew/bin/ollama"),
                       Path("/Applications/Ollama.app/Contents/Resources/ollama")]
    for path in candidates:
        if path.is_file():
            return str(path)
    return ""


_serve_lock = threading.Lock()
_serve_proc: subprocess.Popen | None = None


def _ollama_up(ollama_url: str) -> bool:
    try:
        return httpx.get(ollama_url.rstrip("/") + "/api/tags", timeout=2).status_code == 200
    except Exception:
        return False


def ensure_ollama(ollama_url: str = "http://localhost:11434", wait: float = 15) -> bool:
    """Ollama sunucusu çalışmıyorsa arka planda başlatır (kullanıcı elle açmak zorunda kalmasın).

    Yalnızca yerel adreste ve Ollama bulunabiliyorsa; programın başlattığı sunucu program kapanınca kapanır."""
    global _serve_proc
    with _serve_lock:
        if _ollama_up(ollama_url):
            return True
        if not any(h in ollama_url for h in ("localhost", "127.0.0.1")):
            return False
        exe = ollama_path()
        if not exe:
            return False
        if _serve_proc is None or _serve_proc.poll() is not None:
            flags = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
            host = ollama_url.split("://", 1)[-1].rstrip("/")
            env = {**os.environ, "OLLAMA_HOST": host}  # ayarlardaki adreste dinlesin
            try:
                _serve_proc = subprocess.Popen([exe, "serve"], stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                                               stderr=subprocess.DEVNULL, creationflags=flags, env=env,
                                               start_new_session=os.name != "nt")
            except OSError:
                return False
            atexit.register(_stop_ollama)
        deadline = time.time() + wait
        while time.time() < deadline:
            if _ollama_up(ollama_url):
                return True
            if _serve_proc.poll() is not None:  # hemen kapandıysa (ör. port başka bir şeyde)
                return _ollama_up(ollama_url)
            time.sleep(0.3)
        return False


_room_lock = threading.Lock()


def make_room(ollama_url: str, model: str) -> None:
    """Model ekran kartına tam sığsın diye bellekteki diğer yerel modelleri boşaltır (silmez).

    Ollama iki modeli birlikte tutarken yenisini kısmen işlemciye koyabiliyor: ölçümde 107 → 29 token/sn.
    Model zaten tamamen ekran kartındaysa ya da ekran kartı yoksa hiçbir şey yapılmaz."""
    base = ollama_url.rstrip("/")
    with _room_lock:
        try:
            loaded = httpx.get(base + "/api/ps", timeout=3).json().get("models", [])
        except Exception:
            return
        if not loaded or not any(m.get("size_vram") for m in loaded):
            return  # ekran kartı yok ya da boş: yapılacak bir şey yok
        mine = next((m for m in loaded if m.get("name") == model or m.get("model") == model), None)
        others = [m for m in loaded if m is not mine]
        if not others or (mine and mine.get("size_vram", 0) >= 0.97 * mine.get("size", 1)):
            return  # tek başına ya da zaten tamamen ekran kartında
        victims = others + ([mine] if mine else [])  # kısmen yüklüyse yeniden, bu sefer tamamen yüklensin
        for m in victims:
            try:
                httpx.post(base + "/api/generate", json={"model": m.get("name"), "keep_alive": 0}, timeout=10)
            except Exception:
                pass
        # boşaltma hemen olmaz: bitmeden istek gelirse eski (yarım yüklü) kopya kullanılır
        names = {m.get("name") for m in victims}
        deadline = time.time() + 8
        while time.time() < deadline:
            try:
                if not names & {m.get("name") for m in httpx.get(base + "/api/ps", timeout=3).json().get("models", [])}:
                    return
            except Exception:
                return
            time.sleep(0.2)


def _stop_ollama() -> None:
    if _serve_proc is not None and _serve_proc.poll() is None:
        _serve_proc.terminate()


def scan(ollama_url: str = "http://localhost:11434") -> SystemInfo:
    info = SystemInfo(os_name=_os_name(), cpu=_cpu(), cores=os.cpu_count() or 0)
    try:
        import psutil

        info.ram_gb = psutil.virtual_memory().total / 1024 ** 3
    except ImportError:
        if Path("/proc/meminfo").exists():
            info.ram_gb = int(Path("/proc/meminfo").read_text().split()[1]) / 1024 ** 2
    info.gpu, info.vram_gb = _gpu()
    if platform.system() == "Darwin" and info.gpu.startswith("Apple"):
        info.vram_gb = info.ram_gb * 0.66  # birleşik belleğin modele ayrılabilen kısmı
    info.disk_free_gb = shutil.disk_usage(Path.home()).free / 1024 ** 3
    from . import power

    info.laptop = power.state().has_battery
    info.ollama_installed = bool(ollama_path())
    ensure_ollama(ollama_url)
    try:
        resp = httpx.get(ollama_url.rstrip("/") + "/api/tags", timeout=3)
        info.ollama_running = resp.status_code == 200
        info.ollama_models = [m["name"] for m in resp.json().get("models", [])]
        info.ollama_installed = True
    except Exception:
        pass
    return info


def fits(info: "SystemInfo", size_gb: float) -> bool:
    """Model bu sistemde rahat çalışır mı? Ekran kartı varsa VRAM'e, yoksa RAM'e (işlemcide) sığmalı."""
    if info.vram_gb >= 4:
        return size_gb * 1.2 + 0.6 <= info.vram_gb
    return size_gb * 1.5 + 2 <= info.ram_gb


def _fallback_ladders() -> dict:
    """İnternet hiç yoksa: programla gelen liste (model_updates biçiminde)."""
    return {kind: [(m, size, m.split(":")[0]) for m, size, _, _ in ladder] for kind, (_, _, ladder) in LADDERS.items()}


# yetenek listesinde olmayan ama programın kullandığı modeller: (tür, başlık, not, model, GB, varsayılan seçili)
SUPPORT_MODELS = [
    ("memory", "Hafıza (anlamca arama)", "önceki sohbetlerden öğrenilenleri anlamca bulur; yoksa kelime araması",
     "nomic-embed-text:latest", 0.3, True),
    ("ocr", "Resimden yazı okuma (OCR)", "taranmış belge ve fotoğraftaki yazı", "glm-ocr:latest", 2.2, False),
]


def recommend(info: "SystemInfo", live: dict | None = None) -> tuple[str, list[Suggestion]]:
    """(sistem özeti, öneriler): gömülü temel model + her yetenek için sisteme sığan en iyi model ve 2 alternatif.

    live: model_updates.load() — günlük güncel liste (yoksa programla gelen liste)."""
    vram, ram = info.vram_gb, info.ram_gb
    if vram >= 11:
        text = "Güçlü ekran kartı: 12–14 milyar parametreli modeller ekran kartında hızlı çalışır."
    elif vram >= 6:
        text = "Orta seviye ekran kartı: 7–9 milyarlık modeller ekran kartında hızlı çalışır."
    elif ram >= 16:
        text = "Ayrı ekran kartı zayıf ya da yok: modeller işlemcide çalışır; küçük–orta modeller uygun."
    else:
        text = "Sınırlı donanım: gömülü temel model yeterli; zor işler için bulut modeli bağlaman iyi olur."
    if info.laptop:
        text += (" Dizüstü: pildeyken ekran kartı yavaşlar; program o sırada kendiliğinden küçük modele ve kısa "
                 "bağlama geçer, fişe takılınca tam güce döner.")
    from .model_updates import CAPABILITIES

    ladders = (live or {}).get("local") or _fallback_ladders()
    rows: dict[str, Suggestion] = {}  # model → öneri (aynı model birden çok yetenekte: başlıklar birleşir)
    base = Suggestion("base", "Temel asistan (gömülü)", "sohbet · araç · resim · düşünme — her bilgisayarda çalışır",
                      *BASE_MODEL, True)
    rows[base.model] = base
    for kind, (title, note) in CAPABILITIES.items():
        ladder = ladders.get(kind) or []
        families = list(dict.fromkeys(fam for _, _, fam in ladder))  # sıralı: en iyi aile başta
        picks = []
        for fam in families:
            fitting = [(m, size) for m, size, f in ladder if f == fam and fits(info, size)]
            if fitting:
                picks.append(max(fitting, key=lambda x: x[1]))  # ailenin sığan en büyüğü
        if picks:  # ana önerinin bir küçüğü: daha hızlı seçenek
            fam = picks[0][0].split(":")[0]
            smaller = [(m, size) for m, size, f in ladder if f == fam and size <= picks[0][1] * 0.7]  # belirgin hafif
            if smaller:
                picks.insert(1, max(smaller, key=lambda x: x[1]))
        for n, (model, size) in enumerate(picks[:3]):
            if model in rows:
                row = rows[model]
                if row.kind != "base" and title not in row.title:
                    row.title += f" · {title.lower()}"
                continue
            rows[model] = Suggestion(kind, title, note, model, size, checked=(kind == "chat" and n == 0),
                                     alternative=n > 0)
    for kind, title, note, model, size, checked in SUPPORT_MODELS:
        if model not in rows and fits(info, size):
            rows[model] = Suggestion(kind, title, note, model, size, checked)
    return text, list(rows.values())


def local_ranked(info: "SystemInfo", live: dict | None, cap: str | None = None, limit: int = 10) -> list[dict]:
    """Bugünün en iyi yerel modelleri (günlük listeden): cap verilirse o uzmanlıkta, yoksa genel.

    Çeşitlilik için aileler sırayla: önce her ailenin sistemine sığan en güçlüsü, sonra ikincisi…;
    sistemine ağır gelenler en sonda. Her satır: model, GB, aile, sığar mı."""
    ladders = (live or {}).get("local") or _fallback_ladders()
    caps = [cap] if cap else ["chat", "vision", "reasoning", "code"]
    entries: dict[str, tuple[float, str]] = {}
    families: list[str] = []
    for c in caps:
        for model, size, fam in ladders.get(c) or []:
            entries.setdefault(model, (size, fam))
            if fam not in families:
                families.append(fam)
    per_family = {f: sorted(((m, sz) for m, (sz, ff) in entries.items() if ff == f), key=lambda x: -x[1])
                  for f in families}
    fitting = {f: [t for t in tags if fits(info, t[1])] for f, tags in per_family.items()}
    rows, depth = [], 0
    while len(rows) < limit and depth < 2 and any(len(v) > depth for v in fitting.values()):  # aile başına en çok 2
        for f in families:
            if len(fitting[f]) > depth:
                m, sz = fitting[f][depth]
                rows.append({"model": m, "size": sz, "family": f, "fits": True})
        depth += 1
    heavy = sorted(((m, sz, f) for f, tags in per_family.items() for m, sz in tags if not fits(info, sz)),
                   key=lambda x: x[1])
    rows += [{"model": m, "size": sz, "family": f, "fits": False} for m, sz, f in heavy]
    return rows[:limit]


def bundled_modelfile() -> Path | None:
    """Pakete gömülü temel modelin Modelfile'ı (kurulum paketinden gelmişse)."""
    path = BUNDLE_DIR / "Modelfile"
    return path if path.exists() and any(BUNDLE_DIR.glob("*.gguf")) else None


def import_bundled(model: str = BASE_MODEL[0]) -> None:
    """Gömülü modeli internetsiz kurar: ollama create. Başarılı olunca paketteki kopya silinir (yer açılır)."""
    modelfile = bundled_modelfile()
    exe = ollama_path()
    if not modelfile or not exe:
        raise RuntimeError("gömülü model ya da Ollama bulunamadı")
    proc = subprocess.run([exe, "create", model, "-f", str(modelfile)], cwd=modelfile.parent,
                          capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=1800)
    if proc.returncode != 0:
        raise RuntimeError((proc.stderr or proc.stdout).strip()[-300:])
    for gguf in modelfile.parent.glob("*.gguf"):
        gguf.unlink(missing_ok=True)


def install_hint(info: SystemInfo) -> tuple[str, str]:
    """Ollama kurulumu için (açıklama, komut ya da adres)."""
    system = platform.system()
    if system == "Windows":
        return "Ollama'yı indirip kur, sonra “tekrar kontrol et”e bas.", "https://ollama.com/download/windows"
    if system == "Darwin":
        return "Ollama'yı indirip kur, sonra “tekrar kontrol et”e bas.", "https://ollama.com/download/mac"
    family = ""
    try:
        release = platform.freedesktop_os_release()
        family = f"{release.get('ID', '')} {release.get('ID_LIKE', '')}"
    except OSError:
        pass
    if "arch" in family:
        pkg = "ollama-cuda" if "NVIDIA" in info.gpu.upper() else ("ollama-rocm" if "AMD" in info.gpu else "ollama")
        return "Terminalde çalıştır, sonra “tekrar kontrol et”e bas:", \
            f"sudo pacman -S {pkg} && sudo systemctl enable --now ollama"
    return "Terminalde çalıştır, sonra “tekrar kontrol et”e bas:", "curl -fsSL https://ollama.com/install.sh | sh"


def pull(model: str, ollama_url: str, on_progress, cancelled) -> None:
    """Modeli indirir; on_progress(yüzde, durum metni). cancelled() True dönerse durur."""
    import json

    with httpx.stream("POST", ollama_url.rstrip("/") + "/api/pull", json={"model": model, "stream": True},
                      timeout=httpx.Timeout(None, connect=10)) as resp:
        resp.raise_for_status()
        for line in resp.iter_lines():
            if cancelled():
                raise InterruptedError("indirme durduruldu")
            if not line:
                continue
            data = json.loads(line)
            if data.get("error"):
                raise RuntimeError(data["error"])
            total, done = data.get("total") or 0, data.get("completed") or 0
            on_progress(int(done * 100 / total) if total else -1, data.get("status", ""))
