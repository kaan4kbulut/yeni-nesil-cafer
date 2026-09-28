"""Donanım/güç okuma (K13, MIMARI §13): fiş/pil, ekran kartı envanteri (hibrit grafik, uyuyan dGPU), Ollama'nın cihazı, CPU/RAM.

Qt'siz; her dış çağrı zaman aşımlıdır ve sonuç 10 sn önbelleklidir. Arayüz iş parçacığında (`gui_parcacigi_isaretle`)
hiçbir alt süreç açılmaz: orada çağıran son bilinen değeri alır, yenileme arka planda yapılır.

Ollama Linux'ta yalnızca NVIDIA (CUDA) ve ROCm'lu AMD kartları kullanır; Intel/AMD dahili GPU listelenir ama
`ollama_kullanabilir: False` işaretlenir (sahte "dahili GPU'ya geç" seçeneği yok).

Uygulanan karar (`olcum.donanim_karari`) burada tutulur (`karar`/`karar_yaz`); sağlayıcı `num_gpu`, güç/profil
modülleri kademe ve bağlamı buradan okur.
"""

import functools
import glob
import os
import platform
import re
import subprocess
import threading
import time
from pathlib import Path

ONBELLEK_SN = 10
ZAMAN_ASIMI_SN = 4
_SYS_GUC = "/sys/class/power_supply"

_kilit = threading.RLock()
_onbellek: dict[str, tuple[float, object]] = {}
_yenileme: dict[str, threading.Thread] = {}
_gui: threading.Thread | None = None


def gui_parcacigini_isaretle(parcacik: threading.Thread | None = None) -> None:
    """Arayüz iş parçacığını işaretler (varsayılan: çağıran). Orada alt süreç açılmaz."""
    global _gui
    _gui = parcacik or threading.current_thread()


def _gui_mi() -> bool:
    return _gui is not None and threading.current_thread() is _gui


def onbellek_temizle() -> None:
    with _kilit:
        _onbellek.clear()


def _onbellekli(varsayilan):
    """10 sn önbellek; arayüz iş parçacığında bayat değer + arka planda yenileme (asla alt süreç yok)."""
    def sarmal(islev):
        ad = islev.__name__

        @functools.wraps(islev)
        def cagri(yenile: bool = False):
            simdi = time.monotonic()
            with _kilit:
                kayit = _onbellek.get(ad)
            taze = kayit is not None and simdi - kayit[0] < ONBELLEK_SN
            if taze and not yenile:
                return kayit[1]
            if _gui_mi():
                _arka_planda_yenile(ad, islev)
                return kayit[1] if kayit else varsayilan()
            deger = islev()
            with _kilit:
                _onbellek[ad] = (time.monotonic(), deger)
            return deger

        return cagri
    return sarmal


def _arka_planda_yenile(ad: str, islev) -> None:
    with _kilit:
        is_ = _yenileme.get(ad)
        if is_ is not None and is_.is_alive():
            return

        def kos():
            try:
                deger = islev()
            except Exception:
                return
            with _kilit:
                _onbellek[ad] = (time.monotonic(), deger)

        _yenileme[ad] = threading.Thread(target=kos, daemon=True, name=f"donanim-{ad}")
        _yenileme[ad].start()


# ---------------------------------------------------------------- alt süreç

class ZamanAsimi(Exception):
    pass


def _calistir(komut: list[str], sure: float = ZAMAN_ASIMI_SN) -> str | None:
    """Çıktı; komut yok/hata ise None; zaman aşımında `ZamanAsimi`. Testler bunu değiştirir."""
    if _gui_mi():
        return None
    try:
        r = subprocess.run(komut, capture_output=True, text=True, timeout=sure, encoding="utf-8", errors="replace",
                           creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0)
    except subprocess.TimeoutExpired as e:
        raise ZamanAsimi(" ".join(komut)) from e
    except (OSError, subprocess.SubprocessError):
        return None
    return r.stdout if r.returncode == 0 else None


def _guvenli(komut: list[str], sure: float = ZAMAN_ASIMI_SN) -> str:
    try:
        return _calistir(komut, sure) or ""
    except ZamanAsimi:
        return ""


# ---------------------------------------------------------------- güç

def _guc_sys(kok: str) -> dict | None:
    """/sys/class/power_supply: {"fiste", "pil_yuzde"}; hiçbir kayıt yoksa None."""
    mains, pil_var, pil_yuzde, bosaliyor = [], False, None, False
    for dizin in sorted(glob.glob(os.path.join(kok, "*"))):
        d = Path(dizin)
        try:
            tur = (d / "type").read_text().strip()
        except OSError:
            continue
        if tur == "Mains" and (d / "online").exists():
            try:
                mains.append((d / "online").read_text().strip() == "1")
            except OSError:
                pass
        elif tur == "Battery" and (d / "capacity").exists():
            try:
                if (d / "scope").exists() and (d / "scope").read_text().strip() == "Device":
                    continue  # fare/kulaklık pili
                pil_yuzde = int((d / "capacity").read_text().strip())
                pil_var = True
                bosaliyor = bosaliyor or (d / "status").read_text().strip() == "Discharging"
            except (OSError, ValueError):
                pil_var = True
    if not mains and not pil_var:
        return None
    fiste = any(mains) if mains else not bosaliyor
    return {"fiste": fiste, "pil_yuzde": pil_yuzde}


def _guc_upower() -> dict | None:
    liste = _guvenli(["upower", "-e"])
    fiste, pil, yuzde = None, False, None
    for yol in liste.split():
        bilgi = _guvenli(["upower", "-i", yol])
        if "line_power" in yol:
            m = re.search(r"online:\s*(yes|no)", bilgi)
            if m:
                fiste = bool(fiste) or m.group(1) == "yes"
        elif "battery" in yol:
            pil = True
            m = re.search(r"percentage:\s*(\d+)", bilgi)
            if m:
                yuzde = int(m.group(1))
            if fiste is None and re.search(r"state:\s*discharging", bilgi):
                fiste = False
    if not pil and fiste is None:
        return None
    return {"fiste": True if fiste is None else fiste, "pil_yuzde": yuzde}


def _guc_windows() -> dict | None:
    import ctypes

    class _Durum(ctypes.Structure):
        _fields_ = [("AC", ctypes.c_byte), ("Bayrak", ctypes.c_byte), ("Yuzde", ctypes.c_byte),
                    ("Sistem", ctypes.c_byte), ("Sure", ctypes.c_ulong), ("TamSure", ctypes.c_ulong)]

    d = _Durum()
    if not ctypes.windll.kernel32.GetSystemPowerStatus(ctypes.byref(d)):
        return None
    yuzde = d.Yuzde & 0xFF
    return {"fiste": d.AC != 0, "pil_yuzde": yuzde if yuzde <= 100 else None}


def _guc_mac() -> dict | None:
    cikti = _guvenli(["pmset", "-g", "batt"])
    if not cikti:
        return None
    m = re.search(r"(\d+)%", cikti)
    return {"fiste": "Battery Power" not in cikti, "pil_yuzde": int(m.group(1)) if m else None}


@_onbellekli(lambda: {"fiste": True, "pil_yuzde": None})
def guc_durumu() -> dict:
    """{"fiste": bool, "pil_yuzde": int | None}. Bilgi alınamazsa fişte sayılır (masaüstü)."""
    try:
        if os.name == "nt":
            bulunan = _guc_windows()
        elif platform.system() == "Darwin":
            bulunan = _guc_mac()
        else:
            bulunan = _guc_sys(_SYS_GUC) or _guc_upower()
    except Exception:
        bulunan = None
    return bulunan or {"fiste": True, "pil_yuzde": None}


# ---------------------------------------------------------------- ekran kartı envanteri

_NVIDIA_SORGU = ("name,memory.total,memory.used,power.limit,power.draw,clocks.sm,clocks.max.sm,pstate,"
                 "utilization.gpu")


def _sayi(metin: str) -> float | None:
    try:
        return float(metin.strip().replace("MiB", "").replace("MHz", "").replace("W", "").replace("%", ""))
    except ValueError:
        return None  # "[N/A]", "Not Supported"


def nvidia_coz(cikti: str) -> list[dict]:
    kartlar = []
    for satir in cikti.splitlines():
        p = [x.strip() for x in satir.split(",")]
        if len(p) < 9 or not p[0] or p[0].lower() == "name":
            continue
        kartlar.append({
            "ad": p[0], "vram_toplam_mib": int(_sayi(p[1]) or 0), "vram_kullanilan_mib": int(_sayi(p[2]) or 0),
            "guc_siniri_w": _sayi(p[3]), "guc_w": _sayi(p[4]), "sm_mhz": _sayi(p[5]), "sm_max_mhz": _sayi(p[6]),
            "pstate": p[7], "kullanim_yuzde": int(_sayi(p[8]) or 0)})
    return kartlar


_DAHILI_AMD = re.compile(r"radeon\s+(graphics|vega|\d{3}m)|renoir|cezanne|barcelo|lucienne|phoenix|rembrandt|raphael|"
                         r"hawk point|strix|mendocino|picasso|raven", re.I)


def lspci_coz(cikti: str) -> list[dict]:
    """Görüntü denetleyicileri: {"ad", "uretici": nvidia|amd|intel|?, "dahili": bool}."""
    bulunan = []
    for satir in cikti.splitlines():
        if not re.search(r"VGA compatible|3D controller|Display controller", satir, re.I):
            continue
        ad = satir.split(": ", 1)[-1].strip()
        dusuk = ad.lower()
        if "nvidia" in dusuk:
            bulunan.append({"ad": ad, "uretici": "nvidia", "dahili": False})
        elif "intel" in dusuk:
            bulunan.append({"ad": ad, "uretici": "intel", "dahili": True})
        elif "amd" in dusuk or "ati " in dusuk or "advanced micro" in dusuk:
            bulunan.append({"ad": ad, "uretici": "amd", "dahili": bool(_DAHILI_AMD.search(ad))})
        else:
            bulunan.append({"ad": ad, "uretici": "?", "dahili": True})
    return bulunan


def ollama_ps_coz(cikti: str) -> list[dict]:
    """`ollama ps` → [{"model", "cpu_yuzde", "gpu_yuzde"}]."""
    modeller = []
    for satir in cikti.splitlines()[1:]:
        if not satir.strip():
            continue
        ad = satir.split()[0]
        m = re.search(r"(\d+)%/(\d+)%\s*CPU/GPU", satir)
        if m:
            cpu, gpu = int(m.group(1)), int(m.group(2))
        elif re.search(r"(\d+)%\s*CPU", satir):
            cpu = int(re.search(r"(\d+)%\s*CPU", satir).group(1))
            gpu = 100 - cpu
        elif re.search(r"(\d+)%\s*GPU", satir):
            gpu = int(re.search(r"(\d+)%\s*GPU", satir).group(1))
            cpu = 100 - gpu
        else:
            continue
        modeller.append({"model": ad, "cpu_yuzde": cpu, "gpu_yuzde": gpu})
    return modeller


def _bos_envanter() -> dict:
    return {"nvidia": [], "dahili": [], "harici_diger": [], "hibrit": False, "uyuyor": False, "nvidia_zaman_asimi": False,
            "ollama": [], "ollama_gpu_gormuyor": False}


@_onbellekli(_bos_envanter)
def gpu_envanteri() -> dict:
    """{"nvidia": [kart…], "dahili": [{"ad", "ollama_kullanabilir": False}], "hibrit", "uyuyor", "ollama": [model…],
    "ollama_gpu_gormuyor", "nvidia_zaman_asimi"}."""
    env = _bos_envanter()
    try:
        env["nvidia"] = nvidia_coz(_calistir(["nvidia-smi", f"--query-gpu={_NVIDIA_SORGU}",
                                              "--format=csv,noheader,nounits"]) or "")
    except ZamanAsimi:
        env["nvidia_zaman_asimi"] = True
    pci = lspci_coz(_guvenli(["lspci"]))
    for k in pci:
        if k["dahili"]:
            env["dahili"].append({"ad": k["ad"], "uretici": k["uretici"], "ollama_kullanabilir": False})
        elif k["uretici"] == "amd":
            env["harici_diger"].append({"ad": k["ad"], "ollama_kullanabilir": os.path.isdir("/opt/rocm")})
    nvidia_pci = any(k["uretici"] == "nvidia" for k in pci)
    dgpu_var = bool(env["nvidia"]) or nvidia_pci or bool(env["harici_diger"])
    env["hibrit"] = bool(env["dahili"]) and dgpu_var
    if env["hibrit"] and (env["nvidia"] or env["nvidia_zaman_asimi"]):
        pd = env["nvidia"][0] if env["nvidia"] else None
        env["uyuyor"] = env["nvidia_zaman_asimi"] or bool(
            pd and pd["pstate"].upper() == "P8" and pd["kullanim_yuzde"] == 0)
    env["ollama"] = ollama_ps_coz(_guvenli(["ollama", "ps"]))
    saglam = bool(env["nvidia"]) and not env["nvidia_zaman_asimi"]
    env["ollama_gpu_gormuyor"] = saglam and any(m["cpu_yuzde"] >= 100 for m in env["ollama"])
    return env


@_onbellekli(lambda: {"cekirdek": os.cpu_count() or 1, "bos_ram_gb": 0.0, "yuk_yuzde": 0})
def cpu_ram() -> dict:
    cekirdek = os.cpu_count() or 1
    bos = 0.0
    try:
        import psutil

        bos = psutil.virtual_memory().available / 1024 ** 3
        yuk = int(psutil.cpu_percent(interval=0.2))
    except ImportError:
        try:
            for satir in Path("/proc/meminfo").read_text().splitlines():
                if satir.startswith("MemAvailable"):
                    bos = int(satir.split()[1]) / 1024 ** 2
        except OSError:
            pass
        try:
            yuk = int(min(100, os.getloadavg()[0] / cekirdek * 100))
        except (OSError, AttributeError):
            yuk = 0
    return {"cekirdek": cekirdek, "bos_ram_gb": round(bos, 1), "yuk_yuzde": yuk}


def dgpu_uyandir() -> bool:
    """Uyuyan kartı tek bir nvidia-smi çağrısıyla uyandırmayı dener (8 sn). Kart yanıt verdiyse True."""
    try:
        cikti = _calistir(["nvidia-smi", "--query-gpu=name", "--format=csv,noheader"], 8)
    except ZamanAsimi:
        return False
    onbellek_temizle()
    return bool(cikti and cikti.strip())


# ---------------------------------------------------------------- uygulanan karar

_karar: dict | None = None


def karar() -> dict | None:
    with _kilit:
        return dict(_karar) if _karar else None


def karar_yaz(yeni: dict | None) -> None:
    global _karar
    with _kilit:
        _karar = dict(yeni) if yeni else None


def num_gpu_icin(model: str) -> int | None:
    """Ollama isteğine eklenecek `num_gpu`: CPU kararında her model 0; kısmi yüklemede yalnızca karardaki model."""
    k = karar()
    if not k or k.get("num_gpu") is None:
        return None
    if k.get("cihaz") == "cpu" or not k.get("model") or k["model"] == model:
        return int(k["num_gpu"])
    return None
