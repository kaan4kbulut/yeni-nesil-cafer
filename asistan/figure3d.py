"""Resimden gerçek 3D figür (TripoSR, MIT lisanslı): kurulum ve çalıştırma.

Siluet figür (decor3d) yalnızca kalınlık verilmiş bir dış hattır; burada tek bir resimden hacimli bir heykelcik çıkar
(hayvan, karakter, biblo). Kurulum YALNIZCA kullanıcının düğmesiyle (Yardım → 3D figür motoru…): kod GitHub'dan sabit
sürümle, model Hugging Face'ten (1,68 GB) SHA-256 doğrulanarak `DATA_DIR/figur-motoru`'na iner; eksik Python
kütüphaneleri ajanların kütüphane klasörüne kurulur (torch yoksa NVIDIA kartta CUDA sürümü, yoksa işlemci sürümü).
Üretim ajanların Python'unda ayrı süreçte çalışır (figure3d_worker.py): torch programın kendi sürecine yüklenmez.
TripoSR'ın derleme isteyen torchmcubes'u ve rembg'si kullanılmaz (marching cubes: PyMCubes; arka plan: kendi yöntemimiz).
"""

import hashlib
import json
import shutil
import subprocess
import time
import zipfile
from pathlib import Path

from .config import DATA_DIR

ROOT = DATA_DIR / "figur-motoru"
CODE_DIR = ROOT / "kod"  # tsr/ paketi + LICENSE
MODEL_DIR = ROOT / "model"  # config.yaml, model.ckpt, dino-config.json
MARKER = ROOT / "kuruldu.json"
WORKER = Path(__file__).resolve().parent / "figure3d_worker.py"

_COMMIT = "107cefdc244c39106fa830359024f6a2f1c78871"  # VAST-AI-Research/TripoSR, 2026-06-04
_REV = "5b521936b01fbe1890f6f9baed0254ab6351c04a"  # stabilityai/TripoSR
_DINO_REV = "f205d5d8e640a89a2b8ef0369670dfc37cc07fc2"  # facebook/dino-vitb16: yalnızca yapı dosyası (ağırlıklar TripoSR'da)
# (adres, hedef, sha256, boyut GB)
FILES = [
    (f"https://github.com/VAST-AI-Research/TripoSR/archive/{_COMMIT}.zip", ROOT / "triposr.zip",
     "a7b3871a1b4377bef96cbfb99bdc952bdd4f5df9f65fea4208d978a343fd1162", 0.03),
    (f"https://huggingface.co/stabilityai/TripoSR/resolve/{_REV}/config.yaml", MODEL_DIR / "config.yaml",
     "74ca708ce086bf68e97709ea6b3d91f14717921c04691e84043f0eb8fcc68e62", 0.0),
    (f"https://huggingface.co/stabilityai/TripoSR/resolve/{_REV}/model.ckpt", MODEL_DIR / "model.ckpt",
     "429e2c6b22a0923967459de24d67f05962b235f79cde6b032aa7ed2ffcd970ee", 1.68),
    (f"https://huggingface.co/facebook/dino-vitb16/resolve/{_DINO_REV}/config.json", MODEL_DIR / "dino-config.json",
     "b87c0270b97db085fd82cf114a761fd0f62ae7914fbd407c752a2260646b689c", 0.0),
]
# modül adı → pip adı (torch ayrı: hangi sürümün kurulacağı ekran kartına bağlı)
PACKAGES = {"omegaconf": "omegaconf", "einops": "einops", "transformers": "transformers",
            "huggingface_hub": "huggingface_hub", "mcubes": "PyMCubes"}
TORCH_INDEX = {"cuda": "https://download.pytorch.org/whl/cu130", "cpu": "https://download.pytorch.org/whl/cpu",
               "mac": ""}  # macOS: PyPI'daki torch (Apple Silicon'da Metal/MPS destekli)
TORCH_GB = {"cuda": 3.0, "cpu": 0.25, "mac": 0.2}


def installed() -> bool:
    ckpt = MODEL_DIR / "model.ckpt"
    return MARKER.is_file() and (CODE_DIR / "tsr" / "system.py").is_file() and ckpt.is_file() \
        and ckpt.stat().st_size >= 1.6e9


def _torch_kind() -> str:
    """NVIDIA kart varsa CUDA'lı torch (Blackwell dahil: cu130), yoksa işlemci sürümü."""
    import sys

    from . import gpu

    if sys.platform == "darwin":
        return "mac"
    best = gpu.strongest()
    return "cuda" if best is not None and best.vendor == "nvidia" else "cpu"


def missing_packages() -> list[str]:
    """Ajanların Python'unda içe aktarılamayan modüller (torch dahil)."""
    from .tools import NO_WINDOW, agent_env, python_exe

    code = ("import importlib.util, json; print(json.dumps([m for m in %r if importlib.util.find_spec(m) is None]))"
            % [*PACKAGES, "torch"])
    out = subprocess.run([python_exe(), "-c", code], capture_output=True, text=True, env=agent_env(), timeout=60,
                         creationflags=NO_WINDOW)
    try:
        return json.loads(out.stdout.strip().splitlines()[-1])
    except (ValueError, IndexError):
        return [*PACKAGES, "torch"]


def download_gb() -> float:
    """Kurulumun indireceği yaklaşık boyut (GB): model + eksik kütüphaneler."""
    need = sum(gb for url, dest, sha, gb in FILES if not dest.is_file())
    missing = missing_packages()
    if "torch" in missing:
        need += TORCH_GB[_torch_kind()]
    return need + (0.1 if set(missing) - {"torch"} else 0.0)


def _pip(args: list[str], label: str, progress) -> None:
    from .tools import NO_WINDOW, USER_LIBS, python_exe

    USER_LIBS.mkdir(parents=True, exist_ok=True)
    if progress:
        progress(-1, f"{label} kuruluyor…")
    out = subprocess.run([python_exe(), "-m", "pip", "install", "--disable-pip-version-check", "--target",
                          str(USER_LIBS), *args], capture_output=True, text=True, encoding="utf-8", errors="replace",
                         timeout=3600, creationflags=NO_WINDOW)
    if out.returncode != 0:
        lines = [ln for ln in (out.stderr or out.stdout).splitlines() if ln.strip()]
        raise RuntimeError(f"{label} kurulamadı: " + ("\n".join(lines[-4:]) or "pip hatası"))


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def install(progress=None, cancelled=lambda: False) -> None:
    """Kütüphaneler + TripoSR kodu + model; var olanlar atlanır. progress(yüzde, metin)."""
    from .imagegen import _download

    missing = missing_packages()
    if "torch" in missing:
        kind = _torch_kind()
        index = ["--index-url", TORCH_INDEX[kind]] if TORCH_INDEX[kind] else []
        _pip([*index, "torch"], f"torch ({ {'cuda': 'ekran kartı', 'cpu': 'işlemci', 'mac': 'Mac'}[kind]} sürümü, "
             f"~{TORCH_GB[kind]:g} GB)", progress)
    rest = [PACKAGES[m] for m in missing if m in PACKAGES]
    if rest:
        _pip(rest, "3D figür kütüphaneleri", progress)
    for url, dest, sha, gb in FILES:
        if dest.is_file() and _sha256(dest) == sha:
            continue
        dest.unlink(missing_ok=True)
        _download(url, dest, progress, cancelled, "3D figür modeli" if gb > 1 else dest.name, gb)
        if _sha256(dest) != sha:
            dest.unlink(missing_ok=True)
            raise RuntimeError(f"{dest.name} doğrulanamadı (SHA-256 tutmuyor); dosya silindi, yeniden deneyin.")
    archive = ROOT / "triposr.zip"
    shutil.rmtree(CODE_DIR, ignore_errors=True)
    with zipfile.ZipFile(archive) as z:  # yalnızca tsr/ paketi ve lisans
        for name in z.namelist():
            rel = name.split("/", 1)[1] if "/" in name else ""
            if rel and not rel.endswith("/") and (rel.startswith("tsr/") or rel == "LICENSE") and ".." not in rel:
                target = CODE_DIR / rel
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(z.read(name))
    MARKER.write_text(json.dumps({"code": _COMMIT, "model": _REV, "time": time.time()}), encoding="utf-8")


def run(image: str, out: str, height: float = 0, base: bool = True, bed: str = "220x220x250",
        ollama_url: str = "", use_gpu: bool = True, timeout: int = 1200) -> dict:
    """Resimden figür üretir (ayrı süreç); decor3d.save'in sonuç bilgisini döner."""
    from . import gpu, imagegen
    from .tools import NO_WINDOW, agent_env, python_exe

    if not installed():
        raise RuntimeError("3D figür motoru kurulu değil (Yardım → 3D figür motoru…).")
    use_gpu = use_gpu and not gpu.fault()
    if use_gpu and ollama_url:  # model ~6 GB ister: Ollama modelleri ekran kartından boşaltılır (silinmez)
        imagegen.free_gpu(ollama_url)
    args = {"image": image, "out": out, "height": height, "base": base, "bed": bed, "gpu": use_gpu,
            "code": str(CODE_DIR), "model": str(MODEL_DIR)}
    proc = subprocess.run([python_exe(), str(WORKER), json.dumps(args)], capture_output=True, text=True,
                          encoding="utf-8", errors="replace", timeout=timeout, env=agent_env(), creationflags=NO_WINDOW)
    lines = [ln for ln in proc.stdout.splitlines() if ln.startswith("{")]
    if proc.returncode != 0 or not lines:
        last = (proc.stderr.strip().splitlines() or ["?"])[-1]
        raise RuntimeError(f"figür üretilemedi: {last}")
    result = json.loads(lines[-1])
    if result.get("error"):
        raise RuntimeError(result["error"])
    return result
