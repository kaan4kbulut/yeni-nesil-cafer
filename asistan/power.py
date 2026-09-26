"""Güç durumu: bilgisayar fişte mi, pilde mi? Pildeyken program kendini ve modelleri hafifletir.

Dizüstülerde ekran kartı pilde güç sınırına takılır (ölçüm, 12 GB'lık bir dizüstü ekran kartı: bellek saati 405–810 MHz'e
kilitli; 12B model 3.9, 4B 9.5, 2B 12.7 token/sn; güç profilini "performans" yapmak da değiştirmedi). Model
değiştirmek de pilde çok pahalı (tek yükleme 5–65 sn). Bu yüzden pilde: küçük model, küçük bağlam, uzun düşünme
yok, modeller arasında gidip gelme yok. Linux, Windows ve macOS'ta çalışır.
"""

import os
import platform
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path

# pildeyken otomatik seçilen yerel modelin üst sınırı (milyar parametre) ve bağlam üst sınırı (token)
BATTERY_MAX_PARAMS = 5.0
BATTERY_CTX = 8192
CACHE_SECONDS = 10

MODES = {  # ayar değeri -> ayarlar penceresindeki metin
    "otomatik": "Otomatik: pildeyken hafif, fişteyken tam güç (önerilen)",
    "performans": "Her zaman tam güç (pilde yavaş olabilir)",
    "tasarruf": "Her zaman hafif (fişteyken de küçük model)",
}


@dataclass
class PowerState:
    has_battery: bool = False  # dizüstü mü (pil var mı)
    on_battery: bool = False  # şu an pilde mi
    percent: int | None = None


_cache: tuple[float, PowerState] | None = None


def _linux() -> PowerState:
    state = PowerState()
    root = Path("/sys/class/power_supply")
    mains_online = None
    for dev in root.glob("*") if root.exists() else []:
        try:
            kind = (dev / "type").read_text().strip()
        except OSError:
            continue
        if kind == "Battery" and (dev / "capacity").exists():
            if (dev / "scope").exists() and (dev / "scope").read_text().strip() == "Device":
                continue  # fare, kulaklık gibi aygıtların pili
            state.has_battery = True
            try:
                state.percent = int((dev / "capacity").read_text())
                if (dev / "status").read_text().strip() == "Discharging":
                    state.on_battery = True
            except (OSError, ValueError):
                pass
        elif kind in ("Mains", "USB") and (dev / "online").exists():
            try:
                mains_online = bool(mains_online) or (dev / "online").read_text().strip() == "1"
            except OSError:
                pass
    if state.has_battery and mains_online is not None:
        state.on_battery = not mains_online  # adaptör bilgisi varsa o esas (dolu pilde "Not charging" olur)
    return state


def _windows() -> PowerState:
    import ctypes

    class _Status(ctypes.Structure):
        _fields_ = [("ACLineStatus", ctypes.c_byte), ("BatteryFlag", ctypes.c_byte),
                    ("BatteryLifePercent", ctypes.c_byte), ("SystemStatusFlag", ctypes.c_byte),
                    ("BatteryLifeTime", ctypes.c_ulong), ("BatteryFullLifeTime", ctypes.c_ulong)]

    s = _Status()
    if not ctypes.windll.kernel32.GetSystemPowerStatus(ctypes.byref(s)):
        return PowerState()
    has = not (s.BatteryFlag & 128) and s.BatteryFlag != -1  # 128: pil yok, 255 (-1): bilinmiyor
    pct = s.BatteryLifePercent & 0xFF
    return PowerState(has, has and s.ACLineStatus == 0, pct if pct <= 100 else None)


def _mac() -> PowerState:
    try:
        out = subprocess.run(["pmset", "-g", "batt"], capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=3).stdout
    except (OSError, subprocess.SubprocessError):
        return PowerState()
    has = "InternalBattery" in out
    pct = None
    if has and "%" in out:
        try:
            pct = int(out.split("%")[0].split()[-1])
        except ValueError:
            pass
    return PowerState(has, has and "Battery Power" in out, pct)


def state(refresh: bool = False) -> PowerState:
    """Anlık güç durumu (birkaç saniye önbellekte)."""
    global _cache
    now = time.time()
    if not refresh and _cache and now - _cache[0] < CACHE_SECONDS:
        return _cache[1]
    try:
        system = platform.system()
        found = _windows() if os.name == "nt" else _mac() if system == "Darwin" else _linux()
    except Exception:
        found = PowerState()
    _cache = (now, found)
    return found


def saving(settings) -> bool:
    """Hafif modda mı çalışılmalı? Ayar: otomatik (pildeyken) · performans (hiç) · tasarruf (her zaman)."""
    mode = getattr(settings, "power_mode", "otomatik")
    if mode == "performans":
        return False
    if mode == "tasarruf":
        return True
    return state().on_battery


def num_ctx(settings) -> int:
    """Ollama'ya gönderilecek bağlam: hafif modda en çok 8K (uzun geçmiş pilde her adımı dakikalarca bekletir)."""
    return min(settings.ollama_num_ctx, BATTERY_CTX) if saving(settings) else settings.ollama_num_ctx


def label(settings) -> str:
    """Durum çubuğu için kısa metin ("" : fişte, tam güç)."""
    s = state()
    if not saving(settings):
        return "🔋 pil · tam güç" if s.on_battery else ""
    pct = f" %{s.percent}" if s.on_battery and s.percent is not None else ""
    return f"🔋{pct} hafif mod"
