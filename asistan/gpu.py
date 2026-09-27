"""Ekran kartı denetimi: program modelleri ekran kartında, birden çok kart varsa en güçlüsünde mi çalıştırıyor?

Dizüstülerde çoğunlukla iki kart olur: ekranı süren tümleşik kart (Intel/AMD) ve güçlü ayrı kart (NVIDIA/AMD).
Model tümleşik kartta ya da işlemcide çalışırsa yanıtlar 5-20 kat yavaşlar. Bu yüzden:
- en güçlü kart seçilir (ayrı kart tümleşikten önce, sonra VRAM'i büyük olan),
- programın kendi başlattığı Ollama o karta sabitlenir (`ollama_env`),
- model yüklendikten sonra Ollama'nın gerçekten o kartta olduğu denetlenir (`check`), resim motorunun seçtiği kart
  çıktısından okunur (`note_device`).
Hafif modda (pil / tasarruf) sabitleme ve uyarı yapılmaz: güç tasarrufu için başka kart ya da işlemci kullanılabilir.
"""

import os
import platform
import subprocess
import threading
import time
from dataclasses import dataclass
from pathlib import Path

VENDORS = {"0x10de": "nvidia", "0x1002": "amd", "0x8086": "intel"}
DISCRETE_MIN_MIB = 2048  # bundan az belleği olan AMD kartı tümleşik sayılır (paylaşılan bellek)


@dataclass
class Card:
    name: str
    vendor: str  # nvidia · amd · intel · apple · ?
    vram_mib: int = 0
    discrete: bool = True
    uuid: str = ""  # NVIDIA: CUDA_VISIBLE_DEVICES ile sabitlemek için (sıra numarası CUDA'da farklı olabilir)

    @property
    def short(self) -> str:
        return self.name.replace("NVIDIA ", "").replace("GeForce ", "").replace(" Laptop GPU", "").strip()


def _run(cmd: list[str], timeout: float = 4) -> str:
    try:
        flags = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout, creationflags=flags,
                           encoding="utf-8", errors="replace")
        return r.stdout if r.returncode == 0 else ""
    except (OSError, subprocess.SubprocessError):
        return ""


def _nvidia() -> list[Card]:
    out = _run(["nvidia-smi", "--query-gpu=name,memory.total,uuid", "--format=csv,noheader,nounits"])
    found = []
    for line in out.splitlines():
        parts = [p.strip() for p in line.split(",")]
        if len(parts) >= 3:
            try:
                found.append(Card(parts[0], "nvidia", int(float(parts[1])), True, parts[2]))
            except ValueError:
                continue
    return found


def _linux_others() -> list[Card]:
    """NVIDIA dışındaki kartlar (sysfs): AMD'nin VRAM'i okunur, Intel tümleşik sayılır."""
    found = []
    for dev in sorted(Path("/sys/class/drm").glob("card[0-9]*/device")):
        if "-" in dev.parent.name:
            continue  # card1-eDP-1 gibi bağlantı noktaları
        try:
            vendor = VENDORS.get(dev.joinpath("vendor").read_text().strip(), "?")
        except OSError:
            continue
        if vendor in ("nvidia", "?"):
            continue
        vram = 0
        try:
            vram = int(dev.joinpath("mem_info_vram_total").read_text()) // (1024 * 1024)
        except (OSError, ValueError):
            pass
        name = {"amd": "AMD Radeon", "intel": "Intel tümleşik"}[vendor]
        found.append(Card(name, vendor, vram, vendor == "amd" and vram >= DISCRETE_MIN_MIB))
    return found


def _windows_others() -> list[Card]:
    out = _run(["powershell", "-NoProfile", "-Command",
                "Get-CimInstance Win32_VideoController | ForEach-Object { $_.Name }"], timeout=8)
    found = []
    for name in (n.strip() for n in out.splitlines()):
        low = name.lower()
        if not name or "nvidia" in low or "basic" in low or "virtual" in low:
            continue
        vendor = "amd" if ("amd" in low or "radeon" in low) else "intel" if "intel" in low else "?"
        # AMD'de ayrı kart adında RX geçer; Intel Arc ayrı karttır
        discrete = (vendor == "amd" and " rx " in f" {low} ") or "arc" in low
        found.append(Card(name, vendor, 0, discrete))
    return found


_cache: list[Card] | None = None
_lock = threading.Lock()


def cards(refresh: bool = False) -> list[Card]:
    """Bilgisayardaki ekran kartları (bir kez okunur; kart takılıp çıkarılmaz)."""
    global _cache
    with _lock:
        if _cache is None or refresh:
            if platform.system() == "Darwin":
                _cache = [Card("Apple Silicon", "apple", 0, True)] if platform.machine() == "arm64" else []
            else:
                _cache = _nvidia() + (_windows_others() if os.name == "nt" else _linux_others())
        return list(_cache)


def strongest(found: list[Card] | None = None) -> Card | None:
    found = cards() if found is None else found
    return max(found, key=lambda c: (c.discrete, c.vendor == "nvidia", c.vram_mib), default=None)


def saving(settings) -> bool:
    from . import power

    return power.saving(settings)


_fault: tuple[float, str] = (0.0, "")
FAULT_SECONDS = 30
_FAULT_SIGNS = ("requires reset", "err!", "unable to determine", "fallen off", "unknown error", "no devices were found")


def fault() -> str:
    """NVIDIA kartının sürücüsü hata durumunda mı? Sebep metni; sorun yoksa (ya da NVIDIA yoksa) boş.

    Görülen durum (2026-09-26): Xid 62 → "GPU requires reset"; CUDA kartı görmez, Ollama sessizce işlemciye düşer.
    Ollama'yı yeniden başlatmak yetmez, bilgisayar yeniden başlatılmalı. 30 sn önbellek."""
    global _fault
    now = time.time()
    if now - _fault[0] < FAULT_SECONDS:
        return _fault[1]
    reason = ""
    if any(c.vendor == "nvidia" for c in cards()):
        try:
            flags = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
            r = subprocess.run(["nvidia-smi", "--query-gpu=temperature.gpu", "--format=csv,noheader"],
                               capture_output=True, text=True, timeout=5, creationflags=flags,
                               encoding="utf-8", errors="replace")
            text = (r.stdout + r.stderr).lower()
            if any(sign in text for sign in _FAULT_SIGNS) or (r.returncode != 0 and text.strip()):
                reason = "sürücü sıfırlama istiyor" if "reset" in text else "sürücü kartı göremiyor"
        except subprocess.TimeoutExpired:
            reason = "sürücü yanıt vermiyor"
        except OSError:
            pass
    _fault = (now, reason)
    return reason


def ollama_env(settings) -> dict[str, str]:
    """Programın başlattığı Ollama'ya eklenecek ortam: tam güçte yalnızca en güçlü kart görünsün.

    Tek NVIDIA kart varsa da sabitlenir (zararı yok); kullanıcı kendisi CUDA_VISIBLE_DEVICES verdiyse dokunulmaz."""
    if saving(settings) or "CUDA_VISIBLE_DEVICES" in os.environ:
        return {}
    best = strongest()
    if best and best.vendor == "nvidia" and best.uuid:
        return {"CUDA_VISIBLE_DEVICES": best.uuid}
    return {}


def _ollama_pids_by_gpu() -> dict[str, list[int]]:
    """NVIDIA kartlarında çalışan Ollama süreçleri: {kart uuid: [pid]}."""
    out = _run(["nvidia-smi", "--query-compute-apps=pid,process_name,gpu_uuid", "--format=csv,noheader"])
    found: dict[str, list[int]] = {}
    for line in out.splitlines():
        parts = [p.strip() for p in line.split(",")]
        if len(parts) < 3:
            continue
        name = parts[1].lower()
        if not name or "[" in name:  # başka kullanıcının süreci: ad gizli olabilir; /proc'tan bak
            try:
                name = Path(f"/proc/{parts[0]}/comm").read_text().strip().lower()
            except OSError:
                name = ""
        if "ollama" in name or "llama-server" in name or "llama_server" in name:
            try:
                found.setdefault(parts[2], []).append(int(parts[0]))
            except ValueError:
                continue
    return found


@dataclass
class Report:
    ok: bool
    text: str  # durum çubuğu / uyarı metni
    fix: str = ""  # kullanıcının yapabileceği düzeltme (komut ya da ayar); boşsa program kendisi hallediyor
    card: str = ""  # modelin çalıştığı kart (kısa ad)


_image_device: str = ""


def note_device(name: str) -> None:
    """Resim motorunun seçtiği kart (çıktısındaki "ggml_vulkan: 0 = …" satırından)."""
    global _image_device
    _image_device = name.strip()


def image_report(settings) -> Report | None:
    """Son resim üretimi en güçlü kartta mı yapıldı? (Henüz üretim yoksa None.)"""
    if not _image_device:
        return None
    best = strongest()
    if best is None or saving(settings) or _same(best, _image_device):
        return Report(True, f"resim: {_image_device}", card=_image_device)
    return Report(False, f"Resim motoru güçlü kart yerine {_image_device} üzerinde çalıştı ({best.short} "
                         f"kullanılmadı); resimler çok daha yavaş üretilir.",
                  fix="Ekran kartı sürücüsünün Vulkan desteği kurulu mu? (Linux: vulkan-icd-loader ve "
                      "nvidia-utils / vulkan-radeon)", card=_image_device)


def _same(card: Card, name: str) -> bool:
    low = name.lower()
    return card.short.lower() in low or card.name.lower() in low or (card.vendor != "intel" and card.vendor in low)


def is_embedding(model: dict) -> bool:
    """/api/ps kaydı bir gömme modeli mi (nomic-embed-text: aile nomic-bert)? Bunlar küçüktür; kart doluyken
    Ollama onları kısmen işlemciye koyar ve bu yanıtları yavaşlatmaz, ekran kartı teşhisine katılmamalı."""
    details = model.get("details") or {}
    families = [details.get("family") or "", *(details.get("families") or [])]
    return "embed" in (model.get("name") or "").lower() or any("bert" in f.lower() for f in families)


def check(running: list[dict], settings, program_owned: bool) -> Report:
    """Ollama'nın bellekteki modelleri en güçlü kartta mı? `running`: /api/ps'deki modeller.

    program_owned: Ollama'yı program başlattı (düzeltmeyi kendisi yapabilir: en güçlü karta sabitleyip yeniden
    başlatır); değilse sistem servisidir ve düzeltme kullanıcıya önerilir."""
    if platform.system() == "Darwin":  # NVIDIA/AMD kartı yok: Apple Silicon'da Ollama Metal ile birleşik belleği kullanır
        arm = platform.machine() == "arm64"
        return Report(True, "Apple Silicon · Metal" if arm else "Intel Mac · işlemci",
                      card="Apple Silicon" if arm else "işlemci")
    best = strongest()
    if best is None:
        return Report(True, "ekran kartı yok · işlemci")
    broken = fault()
    if broken:  # önce: hafif mod da bu yüzden açık, "işlemcide (hafif mod)" diye gizlenmesin
        return Report(False, f"Ekran kartı ({best.short}) hata verdi, {broken}: modeller işlemcide çalışıyor ve çok yavaş. "
                             f"Program bu arada küçük model ve kısa bağlam kullanıyor.",
                      fix="Bilgisayarı yeniden başlat (Ollama'yı yeniden başlatmak bunu düzeltmez).",
                      card="⚠ işlemci")
    # yalnızca sohbet modelleri: %74'ü işlemcideki gömme modeli "model sığmadı" uyarısı verdiriyordu (2026-09-27)
    running = [r for r in running if not is_embedding(r)]
    if not running:
        return Report(True, f"{best.short} hazır", card=best.short)
    share = min((r.get("size_vram", 0) / r["size"] if r.get("size") else 0) for r in running)
    light = saving(settings)
    restart = "" if program_owned else (
        "sudo systemctl restart ollama" if platform.system() == "Linux" else "Ollama'yı kapatıp yeniden aç")
    if share < 0.01:
        if light:
            return Report(True, "işlemcide (hafif mod)")
        return Report(False, f"Model ekran kartında değil, işlemcide çalışıyor ({best.short} kullanılmıyor); "
                             f"yanıtlar çok yavaş.", fix=restart)
    if best.vendor == "nvidia":
        on = _ollama_pids_by_gpu()
        if on and best.uuid not in on and not light:
            other = next((c.short for c in cards() if c.uuid in on), "başka bir kart")
            fix = "" if program_owned else (
                f"Ollama servisine en güçlü kartı göster: `sudo systemctl edit ollama` ile [Service] altına "
                f"Environment=\"CUDA_VISIBLE_DEVICES={best.uuid}\" ekle, sonra {restart}")
            return Report(False, f"Model en güçlü kart ({best.short}) yerine {other} üzerinde.", fix=fix,
                          card=other)
    if share < 0.99 and not light:
        return Report(False, f"Model ekran kartına ({best.short}) sığmadı: yalnızca %{share * 100:.0f}'i "
                             f"kartta, gerisi işlemcide; yanıtlar yavaş.",
                      fix="Program bağlamı küçültür ya da daha küçük bir model seçer; sürerse bağlamı ayarlardan "
                          "azalt.", card=best.short)
    where = best.short if share > 0.99 else f"%{share * 100:.0f} {best.short}"
    return Report(True, where, card=best.short)
