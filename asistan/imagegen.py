"""Yerel resim üretimi: stable-diffusion.cpp (sd-cli) + sansürsüz SDXL modeli (LUSTIFY v2.0).

Motor ve model program içinden kurulur (kullanıcı bir şey indirmez): motor GitHub sürümünden (Vulkan: NVIDIA,
AMD, Intel'de çalışır), model Hugging Face'ten; kesilen indirme kaldığı yerden sürer. Üretim öncesi Ollama
modelleri ekran kartından boşaltılır (SDXL ~7 GB ister). Reşit olmayanları çağrıştıran istekler kesin engellenir.
"""

import json
import os
import platform
import re
import shutil
import subprocess
import time
import zipfile
from pathlib import Path

import httpx

from .config import DATA_DIR

ROOT = DATA_DIR / "resim"
ENGINE_DIR = ROOT / "motor"
MODEL_DIR = ROOT / "modeller"
BUNDLED_ENGINE = Path(__file__).resolve().parent.parent / "resim-motoru"  # kurulum paketine gömülüyse
RELEASE_API = "https://api.github.com/repos/leejet/stable-diffusion.cpp/releases/latest"

MODELS = {
    "lustify-v2": {
        "title": "LUSTIFY v2.0 — gerçekçi, sansürsüz (SDXL)",
        "file": "lustify-v2.safetensors",
        "url": "https://huggingface.co/shootstuff/LUSTIFY-v2.0/resolve/main/lustifySDXLNSFWSFW_v20.safetensors",
        "size": 6.94,  # GB
        # modelin önerdiği ayarlar (SDXL): DPM++ 2M Karras, düşük CFG
        "sampler": "dpm++2m", "scheduler": "karras", "cfg": 4.5, "steps": 26,
    },
}
DEFAULT_MODEL = "lustify-v2"
NEGATIVE = ("child, children, kid, minor, underage, teen, young girl, young boy, loli, shota, "
            "lowres, bad anatomy, bad hands, extra fingers, deformed, blurry, watermark, text, logo")

# reşit olmayanlar: her dilde, her bağlamda kesin yasak (istem modeli ne derse desin)
_MINOR = re.compile(
    r"\b(child|children|kid|kids|minor|minors|underage|under[- ]?age|preteen|pre-teen|teen|teens|teenage[rd]?|"
    r"adolescen\w*|juvenile|toddler|infant|baby|babies|loli\w*|shota\w*|schoolgirl|schoolboy|middle school|"
    r"high school|elementary|jailbait|little girl|little boy|young girl|young boy|"
    r"çocuk\w*|cocuk\w*|küçük kız\w*|kucuk kiz\w*|küçük oğlan\w*|ergen\w*|reşit olmayan|resit olmayan|"
    r"bebek\w*|ilkokul\w*|ortaokul\w*|lise\w*|liseli\w*|öğrenci kız\w*|kız öğrenci\w*)\b"
    r"|\b(1[0-7]|[1-9])\s*(yo|y/o|years?[- ]old|yaş\w*|yas\w*)\b",
    re.I)


class Blocked(ValueError):
    """İstem kesin yasak bir içerik istiyor."""


def check_prompt(prompt: str) -> None:
    m = _MINOR.search(prompt or "")
    if m:
        raise Blocked(f"Reşit olmayanları çağrıştıran içerik üretilemez («{m.group(0)}»). Tüm karakterler "
                      "açıkça yetişkin olmalı.")


def engine_path() -> Path | None:
    name = "sd-cli.exe" if os.name == "nt" else "sd-cli"
    for d in (BUNDLED_ENGINE, ENGINE_DIR):
        exe = d / name
        if exe.is_file():
            return exe
    return None


def model_path(key: str = DEFAULT_MODEL) -> Path:
    return MODEL_DIR / MODELS[key]["file"]


def installed(key: str = DEFAULT_MODEL) -> bool:
    path = model_path(key)
    return engine_path() is not None and path.is_file() and path.stat().st_size >= MODELS[key]["size"] * 0.99e9


def _asset_name(names: list[str]) -> str | None:
    """Bu sisteme uygun motor paketi (Vulkan: ekran kartı markasından bağımsız)."""
    system, machine = platform.system(), platform.machine().lower()
    if system == "Linux" and machine in ("x86_64", "amd64"):
        wanted = ["Linux", "x86_64-vulkan.zip"]
    elif system == "Windows":
        wanted = ["win-vulkan-x64.zip"]
    elif system == "Darwin" and machine == "arm64":
        wanted = ["Darwin", "arm64.zip"]
    else:
        return None
    return next((n for n in names if all(w in n for w in wanted)), None)


def _download(url: str, dest: Path, progress, cancelled, label: str, total_hint: float = 0) -> None:
    """Kaldığı yerden süren indirme (bağlantı takılırsa yeniden dener)."""
    dest.parent.mkdir(parents=True, exist_ok=True)
    part = dest.with_suffix(dest.suffix + ".part")
    for attempt in range(30):
        have = part.stat().st_size if part.exists() else 0
        headers = {"Range": f"bytes={have}-"} if have else {}
        try:
            with httpx.stream("GET", url, headers=headers, follow_redirects=True,
                              timeout=httpx.Timeout(60, connect=15)) as resp:
                if resp.status_code == 416:  # zaten tamamı inmiş
                    break
                resp.raise_for_status()
                if have and resp.status_code != 206:  # sunucu devam etmeyi desteklemiyor: baştan
                    have = 0
                    part.unlink(missing_ok=True)
                total = have + int(resp.headers.get("content-length") or 0) or int(total_hint * 1e9)
                last = 0.0
                with open(part, "ab") as f:
                    for chunk in resp.iter_bytes(1 << 20):
                        if cancelled():
                            raise InterruptedError("indirme durduruldu")
                        f.write(chunk)
                        have += len(chunk)
                        if progress and time.time() - last > 0.5:
                            last = time.time()
                            progress(int(have * 100 / total) if total else -1,
                                     f"{label}: {have / 1e9:.2f} / {total / 1e9:.2f} GB")
            break
        except (httpx.HTTPError, OSError) as e:
            if isinstance(e, httpx.HTTPStatusError) and e.response.status_code in (401, 403, 404):
                raise RuntimeError(f"{label} indirilemedi ({e.response.status_code})") from e
            if progress:
                progress(-1, f"{label}: bağlantı takıldı, yeniden deneniyor ({attempt + 1})")
            time.sleep(3)
    else:
        raise RuntimeError(f"{label} indirilemedi: bağlantı sürekli kesildi")
    part.replace(dest)


def install(progress=None, cancelled=lambda: False, key: str = DEFAULT_MODEL) -> None:
    """Motoru ve modeli kurar (varsa atlar). progress(yüzde, metin)."""
    if engine_path() is None:
        rel = httpx.get(RELEASE_API, timeout=20, follow_redirects=True).json()
        assets = {a["name"]: a["browser_download_url"] for a in rel.get("assets", [])}
        name = _asset_name(list(assets))
        if not name:
            raise RuntimeError("Bu işletim sistemi için resim motoru yok.")
        archive = ROOT / name
        _download(assets[name], archive, progress, cancelled, "resim motoru")
        ENGINE_DIR.mkdir(parents=True, exist_ok=True)
        with zipfile.ZipFile(archive) as z:
            z.extractall(ENGINE_DIR)
        archive.unlink(missing_ok=True)
        for f in ENGINE_DIR.rglob("*"):  # bazı paketler alt klasörle gelir: hepsi tek klasöre
            if f.is_file() and f.parent != ENGINE_DIR:
                shutil.move(str(f), ENGINE_DIR / f.name)
        if os.name != "nt":
            for f in ENGINE_DIR.iterdir():
                if f.name.startswith("sd-") or f.suffix == ".so" or ".so." in f.name:
                    f.chmod(0o755)
    info = MODELS[key]
    if not installed(key):
        _download(info["url"], model_path(key), progress, cancelled, "resim modeli", info["size"])


VULKAN_CACHE = ROOT / "vulkan-kartlari.json"  # motorun kart numaraları: {"0": "Intel…", "1": "NVIDIA…"}
_VK_LINE = re.compile(r"^ggml_vulkan: (\d+) = (.+?) \(")


def _vulkan_index(saving: bool = False) -> int | None:
    """Motorun en güçlü kart için kullandığı Vulkan numarası (son çalıştırmanın listesinden). Birden çok kart varken
    motor yükü tümleşik Intel dahil hepsine dağıtıyordu (0 = Intel, 1 = RTX; örnekleme 4.2 → 3.2 sn, 2026-09-27)."""
    from . import gpu

    best = gpu.strongest()
    if saving or best is None:
        return None
    try:
        found = json.loads(VULKAN_CACHE.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    match = [int(i) for i, name in found.items() if gpu._same(best, name)]
    return match[0] if len(found) > 1 and match else None


def _note_devices(devices: dict[str, str], chosen: bool) -> None:
    """Motorun kullandığı kartı bildirir; tam liste (kart seçilmeden görülen) bir sonraki çalıştırma için saklanır."""
    from . import gpu

    if not devices:
        return
    if not chosen and len(devices) > 1:
        try:
            VULKAN_CACHE.parent.mkdir(parents=True, exist_ok=True)
            VULKAN_CACHE.write_text(json.dumps(devices, ensure_ascii=False), encoding="utf-8")
        except OSError:
            pass
    best = gpu.strongest()
    strong = next((name for name in devices.values() if best is not None and gpu._same(best, name)), None)
    gpu.note_device(strong or devices[min(devices, key=int)])


def free_gpu(ollama_url: str) -> None:
    """Ollama modellerini ekran kartından boşaltır (silmez; sonraki mesajda yeniden yüklenir)."""
    base = ollama_url.rstrip("/")
    try:
        loaded = httpx.get(base + "/api/ps", timeout=3).json().get("models", [])
    except Exception:
        return
    for m in loaded:
        try:
            httpx.post(base + "/api/generate", json={"model": m.get("name"), "keep_alive": 0}, timeout=10)
        except Exception:
            pass
    deadline = time.time() + 10
    while time.time() < deadline:
        try:
            if not httpx.get(base + "/api/ps", timeout=3).json().get("models"):
                return
        except Exception:
            return
        time.sleep(0.3)


def _vram_mib() -> int:
    from .ctxprobe import gpu_total_mib

    return gpu_total_mib() or 0


def generate(prompt: str, out_dir: Path, negative: str = "", width: int = 1024, height: int = 1024,
             count: int = 1, seed: int = -1, saving: bool = False, ollama_url: str = "",
             cancelled=lambda: False, progress=None, key: str = DEFAULT_MODEL,
             preview: Path | None = None) -> list[Path]:
    """Resim üretir; kaydedilen dosyaların yolları. saving (hafif mod): daha az adım, pilde çok daha kısa sürer.
    preview: her örnekleme adımında ara görüntünün yazılacağı dosya (canlı görüntü bölümünde canlı izleme). "proj"
    yöntemi ek model istemez ve üretimi yavaşlatmaz; görüntü düşük çözünürlüklü bir yaklaşımdır."""
    check_prompt(prompt)
    check_prompt(negative)  # olumsuz isteme yazıp yasağı ters çevirmek de olmaz
    exe = engine_path()
    if exe is None or not installed(key):
        raise RuntimeError("Resim üretimi kurulu değil.")
    info = MODELS[key]
    width = max(512, min(int(width) // 64 * 64, 1536))
    height = max(512, min(int(height) // 64 * 64, 1536))
    count = max(1, min(int(count), 4))
    steps = 16 if saving else info["steps"]
    if saving and width * height > 832 * 832:  # pilde: daha az piksel (çözme süresi piksel sayısıyla artar)
        scale = (832 * 832 / (width * height)) ** 0.5
        width, height = max(512, int(width * scale) // 64 * 64), max(512, int(height * scale) // 64 * 64)
    if seed is None or int(seed) < 0:
        seed = int.from_bytes(os.urandom(4), "little") & 0x7FFFFFFF
    if ollama_url:
        free_gpu(ollama_url)
    out_dir.mkdir(parents=True, exist_ok=True)
    stamp = time.strftime("%Y%m%d-%H%M%S")
    pattern = out_dir / f"resim-{stamp}-%d.png"
    cmd = [str(exe), "-m", str(model_path(key)), "-p", prompt,
           "-n", ", ".join(x for x in (negative.strip(), NEGATIVE) if x),
           "-W", str(width), "-H", str(height), "--steps", str(steps), "--cfg-scale", str(info["cfg"]),
           "--sampling-method", info["sampler"], "--scheduler", info["scheduler"], "-s", str(seed),
           "-b", str(count), "--diffusion-fa", "-o", str(pattern)]
    if preview is not None:
        cmd += ["--preview", "proj", "--preview-path", str(preview), "--preview-interval", "1"]
    if _vram_mib() < 10000:  # az bellekli kartta parça parça çöz (12 GB'ta gereksiz yavaşlatıyor: 62 → 43 sn)
        cmd.append("--vae-tiling")
    env = {**os.environ}
    chosen = "GGML_VK_VISIBLE_DEVICES" in env  # kullanıcı kendisi seçtiyse dokunulmaz
    if not chosen:
        index = _vulkan_index(saving)
        if index is not None:
            env["GGML_VK_VISIBLE_DEVICES"] = str(index)
            chosen = True
    devices: dict[str, str] = {}
    if os.name != "nt":
        env["LD_LIBRARY_PATH"] = os.pathsep.join(filter(None, [str(exe.parent), env.get("LD_LIBRARY_PATH", "")]))
    flags = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
    for attempt in range(2):
        proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, encoding="utf-8", errors="replace",
                                env=env, cwd=str(exe.parent), creationflags=flags)
        tail: list[str] = []
        step_re = re.compile(r"\|\s*(\d+)/(\d+) - [\d.]+(?:s/it|it/s)")  # yalnızca örnekleme adımları (yükleme değil)
        buf = ""
        while True:
            ch = proc.stdout.read(1)
            if not ch:
                break
            if cancelled():
                proc.kill()
                proc.wait()
                raise InterruptedError("resim üretimi durduruldu")
            if ch in "\r\n":
                line, buf = buf.strip(), ""
                if not line:
                    continue
                tail = (tail + [line])[-15:]
                vk = _VK_LINE.match(line)
                if vk:  # motorun gördüğü kartlar (gpu.image_report ve bir sonraki çalıştırmanın kart seçimi)
                    devices[vk.group(1)] = vk.group(2).strip()
                m = step_re.search(line)
                if m and progress:
                    done, total = int(m.group(1)), int(m.group(2))
                    progress(int(done * 100 / max(total, 1)), f"adım {done}/{total}")
            else:
                buf += ch
        proc.wait()
        _note_devices(devices, chosen)
        files = sorted(out_dir.glob(f"resim-{stamp}-*.png"))
        if proc.returncode == 0 and files:
            break
        if attempt == 0 and ollama_url and "memory" in "\n".join(tail).lower():
            # boşaltmadan sonra başka bir istek (arka plan işi, açık program) Ollama modelini karta yeniden yükledi:
            # bir kez daha boşalt ve dene (2026-09-27: "cannot make enough memory available", 695 MB boş kalmıştı)
            free_gpu(ollama_url)
            time.sleep(2)
            continue
        raise RuntimeError("Resim üretilemedi:\n" + "\n".join(tail[-6:]))
    meta = {"prompt": prompt, "negative": negative, "seed": seed, "steps": steps, "size": f"{width}x{height}",
            "model": info["title"]}
    for f in files:
        f.with_suffix(".json").write_text(json.dumps(meta, ensure_ascii=False, indent=1), encoding="utf-8")
    return files
