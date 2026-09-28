"""Donanım profili ve kademe (docs/MIMARI.md §3, şema docs/SEMALAR.md §4).

Program kendini tanır: işlemci, bellek, ekran kartı (nvidia-smi → sysfs/Windows → torch → Vulkan → Metal), disk, ağ,
Ollama. Sonuç `DATA_DIR/profil.json`'a yazılır (NOTLAR/SORULAR.md: MIMARI'deki `.cafer/` programın veri klasörüdür).

Kademe: `dusuk` · `orta` · `yuksek` · `sunucu`. Kilit ölçümü ezer; öncelik: `ayar.toml`/`CAFER_GENEL_KADEME_KILIDI`
→ arayüzden seçilen (`ayarlar.json` → extra `kademe_kilidi`) → ölçüm. `dusuk`'te ağır özellikler (embedding, tarayıcı
otomasyonu, uzun bağlam) kapalıdır: `acik_mi(ozellik)`.

Komut satırı: `python -m asistan profil` ya da `python -m asistan.cekirdek.profil`.
"""

import json
import os
import platform
import re
import shutil
import socket
import subprocess
import sys
import threading
import time
from datetime import datetime
from importlib.util import find_spec
from pathlib import Path

from . import ayar

KADEMELER = ("dusuk", "orta", "yuksek", "sunucu")
ADLAR = {"dusuk": "düşük", "orta": "orta", "yuksek": "yüksek", "sunucu": "sunucu"}

# MIMARI §3 eşikleri. İşletim sistemi belleğin bir kısmını ayırır: "32 GB" bilgisayar ~31 GiB, "8 GB" ~7,6 GiB
# gösterir; eşikler bu payla yazıldı.
ESIK = {
    "yuksek_ram_gb": 28,  # ≥ 32 GB RAM
    "yuksek_vram_gb": 7.5,  # ≥ 8 GB VRAM
    "dusuk_ram_gb": 12,  # ≤ 8 GB RAM (12'nin altı)
    "ayri_kart_vram_gb": 6,  # düşük RAM'i kurtaran ayrı ekran kartı (7–8B model VRAM'e sığar)
}

# dusuk kademede kapalı ağır özellikler (MIMARI §3): ad → arayüzde görünen ad
AGIR_OZELLIKLER = {
    "embedding": "Hafıza: anlamca arama (embedding)",
    "tarayici": "Tarayıcı otomasyonu",
    "uzun_baglam": "Uzun bağlam (8K üstü)",
}
KAPALI = {"dusuk": frozenset(AGIR_OZELLIKLER)}
KISA_BAGLAM = 8192  # dusuk kademede Ollama bağlam tavanı (uzun_baglam kapalı)

UI_KILIT_ANAHTARI = "kademe_kilidi"  # Settings.extra içinde


def dosya() -> Path:
    return ayar.DATA_DIR / "profil.json"


# ---------------------------------------------------------------- ölçüm parçaları

def _calistir(komut: list[str], zaman_asimi: float = 5) -> str:
    try:
        bayrak = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
        r = subprocess.run(komut, capture_output=True, text=True, encoding="utf-8", errors="replace",
                           timeout=zaman_asimi, creationflags=bayrak)
        return r.stdout if r.returncode == 0 else ""
    except (OSError, subprocess.SubprocessError):
        return ""


def _isletim() -> str:
    sistem = platform.system()
    if sistem == "Windows":
        surum = platform.version().split(".")
        # Windows 11 platform.release()'te "10" görünür; yapı numarası 22000 ve üstü 11'dir
        adi = "11" if len(surum) > 2 and surum[2].isdigit() and int(surum[2]) >= 22000 else platform.release()
        return f"windows-{adi}"
    if sistem == "Darwin":
        return f"macos-{platform.mac_ver()[0] or '?'}"
    if sistem == "Linux":
        try:
            return f"linux-{platform.freedesktop_os_release().get('ID', 'linux')}"
        except OSError:
            return "linux"
    return sistem.lower() or "?"


def _cpu() -> dict:
    iplik = os.cpu_count() or 0
    cekirdek = iplik
    try:
        import psutil

        cekirdek = psutil.cpu_count(logical=False) or iplik
    except ImportError:
        pass
    model = ""
    if Path("/proc/cpuinfo").exists():
        for satir in Path("/proc/cpuinfo").read_text(errors="ignore").splitlines():
            if satir.startswith("model name"):
                model = satir.split(":", 1)[1].strip()
                break
    elif platform.system() == "Darwin":
        model = _calistir(["sysctl", "-n", "machdep.cpu.brand_string"]).strip()
    return {"cekirdek": cekirdek, "iplik": iplik, "model": model or platform.processor() or platform.machine()}


def _ram_gb() -> float:
    try:
        import psutil

        return round(psutil.virtual_memory().total / 1024 ** 3, 1)
    except ImportError:
        pass
    try:
        if Path("/proc/meminfo").exists():
            return round(int(Path("/proc/meminfo").read_text().split()[1]) / 1024 ** 2, 1)
        if platform.system() == "Darwin":
            return round(int(_calistir(["sysctl", "-n", "hw.memsize"]) or 0) / 1024 ** 3, 1)
    except (OSError, ValueError):
        pass
    return 0.0


def _gpu_yok() -> dict:
    return {"var": False, "ad": "", "vram_gb": 0.0, "arka_uc": ""}


def _gpu_kartlardan() -> dict | None:
    """nvidia-smi + Linux sysfs / Windows (asistan.gpu): en güçlü ayrı kart."""
    from .. import gpu

    kart = gpu.strongest(gpu.cards())
    if kart is None or kart.vendor == "apple" or not kart.discrete:
        return None
    uc = {"nvidia": "cuda", "amd": "rocm"}.get(kart.vendor, "")
    return {"var": True, "ad": kart.name, "vram_gb": round(kart.vram_mib / 1024, 1), "arka_uc": uc}


_TORCH_BETIK = ("import json, torch\n"
                "if torch.cuda.is_available():\n"
                "    p = torch.cuda.get_device_properties(0)\n"
                "    print(json.dumps([p.name, p.total_memory]))\n")


def _gpu_torch() -> dict | None:
    """torch kuruluysa ayrı süreçte (içe aktarması saniyeler sürer, programın belleğine girmesin)."""
    if find_spec("torch") is None:
        return None
    cikti = _calistir([sys.executable, "-c", _TORCH_BETIK], zaman_asimi=30).strip()
    try:
        ad, bayt = json.loads(cikti)
    except ValueError:
        return None
    return {"var": True, "ad": ad, "vram_gb": round(bayt / 1024 ** 3, 1), "arka_uc": "cuda"}


def vulkan_coz(metin: str) -> dict | None:
    """`vulkaninfo` çıktısından ayrı ekran kartı: ad + cihaza ait (DEVICE_LOCAL) en büyük bellek yığını.

    Tümleşik kartın DEVICE_LOCAL yığını sistem belleğidir, sayılmaz."""
    en_iyi = None
    for blok in re.split(r"^GPU\d+:\s*$", metin, flags=re.M)[1:]:
        if "PHYSICAL_DEVICE_TYPE_DISCRETE_GPU" not in blok:
            continue
        ad = re.search(r"deviceName\s*=\s*(.+)", blok)
        vram, boyut = 0, 0
        for satir in blok.splitlines():
            m = re.match(r"\s*size\s*=\s*(\d+)", satir)
            if m:
                boyut = int(m.group(1))
            elif "MEMORY_HEAP_DEVICE_LOCAL_BIT" in satir:
                vram = max(vram, boyut)
        aday = {"var": True, "ad": ad.group(1).strip() if ad else "Vulkan ekran kartı",
                "vram_gb": round(vram / 1024 ** 3, 1), "arka_uc": "vulkan"}
        if en_iyi is None or aday["vram_gb"] > en_iyi["vram_gb"]:
            en_iyi = aday
    return en_iyi


def _gpu_vulkan() -> dict | None:
    if not shutil.which("vulkaninfo"):
        return None
    return vulkan_coz(_calistir(["vulkaninfo"], zaman_asimi=20))


def metal_coz(metin: str) -> dict | None:
    """Intel Mac: `system_profiler SPDisplaysDataType` çıktısından ayrı kart ("VRAM (Total): 4 GB")."""
    m = re.search(r"Chipset Model:\s*(.+?)\n(?:.*\n)*?\s*VRAM \((?:Total|Dynamic, Max)\):\s*([\d.]+)\s*(GB|MB)", metin)
    if not m:
        return None
    vram = float(m.group(2)) / (1024 if m.group(3) == "MB" else 1)
    return {"var": True, "ad": m.group(1).strip(), "vram_gb": round(vram, 1), "arka_uc": "metal"}


def _gpu_metal(ram_gb: float) -> dict | None:
    if platform.system() != "Darwin":
        return None
    if platform.machine() == "arm64":  # birleşik bellek: Metal varsayılan olarak yaklaşık üçte ikisini kullanır
        return {"var": True, "ad": "Apple Silicon (birleşik bellek)", "vram_gb": round(ram_gb * 0.65, 1),
                "arka_uc": "metal", "birlesik": True}
    return metal_coz(_calistir(["system_profiler", "SPDisplaysDataType"], zaman_asimi=15))


def _gpu(ram_gb: float) -> dict:
    """Sıra: nvidia-smi (+ AMD sysfs / Windows) → torch → Vulkan → Metal. Bulunan ilk ayrı kart."""
    for dene in (_gpu_kartlardan, _gpu_torch, _gpu_vulkan):
        try:
            sonuc = dene()
        except Exception:
            sonuc = None
        if sonuc:
            return sonuc
    try:
        return _gpu_metal(ram_gb) or _gpu_yok()
    except Exception:
        return _gpu_yok()


def _disk_bos_gb() -> float:
    try:
        return round(shutil.disk_usage(Path.home()).free / 1024 ** 3, 1)
    except OSError:
        return 0.0


def _ag() -> bool:
    """Ağ var mı? UDP soketini bağlamak yalnızca yönlendirme tablosuna bakar; dışarı paket gitmez."""
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            s.connect(("192.0.2.1", 9))  # belgeleme adresi (TEST-NET-1)
            return not s.getsockname()[0].startswith("127.")
    except OSError:
        return False


def ag_var() -> bool:
    """Şu an ağ var mı? (yönlendirici: çevrimdışıysa yalnızca yerel modeller)"""
    return _ag()


def _ollama(url: str) -> dict:
    """Ollama çalışıyor mu (başlatmaz): sürüm ve kurulu modeller."""
    import httpx

    kok = url.rstrip("/")
    try:
        surum = httpx.get(kok + "/api/version", timeout=2).json().get("version", "")
        modeller = [m["name"] for m in httpx.get(kok + "/api/tags", timeout=3).json().get("models", [])]
        return {"calisiyor": True, "surum": surum, "modeller": modeller}
    except Exception:
        return {"calisiyor": False, "surum": "", "modeller": []}


def basliksiz() -> bool:
    """Ekransız (sunucu) mu? Linux'ta masaüstü oturumu yoksa. Windows ve macOS masaüstü sayılır."""
    if platform.system() != "Linux":
        return False
    return not (os.environ.get("DISPLAY") or os.environ.get("WAYLAND_DISPLAY"))


# ---------------------------------------------------------------- kademe

def kademe_hesapla(profil: dict) -> tuple[str, str]:
    """(kademe, neden) — MIMARI §3 tablosu; kilide bakmaz."""
    if profil.get("basliksiz"):
        return "sunucu", "ekransız çalışıyor (sunucu)"
    ram = float(profil.get("ram_gb") or 0)
    gpu = profil.get("gpu") or {}
    vram = float(gpu.get("vram_gb") or 0) if gpu.get("var") else 0.0
    ayri = vram >= ESIK["ayri_kart_vram_gb"] and not gpu.get("birlesik")
    if ram >= ESIK["yuksek_ram_gb"] and vram >= ESIK["yuksek_vram_gb"]:
        return "yuksek", f"{ram:.0f} GB RAM ve {vram:.0f} GB ekran kartı belleği (≥ 32 GB RAM, ≥ 8 GB VRAM)"
    if ram < ESIK["dusuk_ram_gb"] and not ayri:
        return "dusuk", f"{ram:.0f} GB RAM, ayrı ekran kartı yok (≤ 8 GB RAM)"
    if ram < ESIK["yuksek_ram_gb"]:
        return "orta", f"{ram:.0f} GB RAM" + (f", {vram:.0f} GB VRAM" if vram else ", ekran kartı yok") + \
            " (yüksek için ≥ 32 GB RAM)"
    return "orta", f"{ram:.0f} GB RAM ama ekran kartı belleği {vram:.0f} GB (yüksek için ≥ 8 GB VRAM)"


def kilit() -> str | None:
    """Kilitli kademe: ayar.toml / CAFER_GENEL_KADEME_KILIDI önce, sonra arayüzde seçilen. Geçersiz değer yok sayılır."""
    deger = str(ayar.acik_degerler().get("genel.kademe_kilidi") or "").strip().lower()
    if deger in KADEMELER:
        return deger
    try:
        deger = str(ayar.Settings.load().extra.get(UI_KILIT_ANAHTARI) or "").strip().lower()
    except Exception:
        deger = ""
    return deger if deger in KADEMELER else None


def kilit_kaynagi() -> str:
    """"dosya" (ayar.toml/ortam: arayüzden değiştirilemez) · "arayuz" · "" (kilit yok)."""
    if str(ayar.acik_degerler().get("genel.kademe_kilidi") or "").strip().lower() in KADEMELER:
        return "dosya"
    return "arayuz" if kilit() else ""


def kilitle(kademe: str | None, ayarlar=None) -> None:
    """Arayüzden kilitle (None: kilidi aç, ölçüm geçerli). `ayarlar.json`'a yazılır. `ayarlar`: arayüzün canlı
    `Settings` nesnesi (K12-C2: ayrı bir örnek açıp kaydetmek arayüzün sonraki `save()`'inde kilidi ezdiriyordu)."""
    if kademe is not None and kademe not in KADEMELER:
        raise ValueError(f"bilinmeyen kademe: {kademe}")
    s = ayarlar if ayarlar is not None else ayar.Settings.load()
    if kademe:
        s.extra[UI_KILIT_ANAHTARI] = kademe
    else:
        s.extra.pop(UI_KILIT_ANAHTARI, None)
    s.save()
    _onbellek_temizle()
    try:
        p = yukle()
        if p:
            _kademe_yaz(p)
            kaydet(p)
    except OSError:
        pass


def _kademe_yaz(profil: dict) -> dict:
    olculen, neden = kademe_hesapla(profil)
    kilitli = kilit()
    eski = profil.get("kademe") or {}
    otomatik = eski.get("otomatik") if eski.get("otomatik") in KADEMELER else None  # K7 ölçüm ayarı korunur
    profil["kademe"] = {"olculen": olculen, "kilitli": kilitli, "etkin": kilitli or otomatik or olculen, "neden": neden}
    if otomatik:
        profil["kademe"]["otomatik"] = otomatik
        profil["kademe"]["otomatik_neden"] = eski.get("otomatik_neden", "")
    return profil


# ---------------------------------------------------------------- ölç, yaz, oku

def olc(ollama_url: str | None = None, sunucu: bool | None = None, hafif: bool = False) -> dict:
    """Profili ölçer (yazmaz). sunucu: None → ortamdan (`basliksiz`); masaüstü False verir.
    hafif: ağ ve Ollama denetimi yok (açılışta kademe gerektiğinde hızlı yol)."""
    ram = _ram_gb()
    profil = {
        "olcum_zamani": datetime.now().isoformat(timespec="seconds"),
        "isletim": _isletim(),
        "cpu": _cpu(),
        "ram_gb": ram,
        "gpu": _gpu(ram),
        "disk_bos_gb": _disk_bos_gb(),
        "basliksiz": basliksiz() if sunucu is None else bool(sunucu),
    }
    if not hafif:
        profil["ag"] = _ag()
        profil["ollama"] = _ollama(ollama_url or ayar.deger("saglayici.ollama.url"))
    return _kademe_yaz(profil)


def yukle() -> dict | None:
    try:
        return json.loads(dosya().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def kaydet(profil: dict) -> Path:
    yol = dosya()
    yol.parent.mkdir(parents=True, exist_ok=True)
    gecici = yol.with_suffix(".tmp")
    gecici.write_text(json.dumps(profil, indent=2, ensure_ascii=False), encoding="utf-8")
    gecici.replace(yol)
    return yol


def guncelle(ollama_url: str | None = None, sunucu: bool | None = None) -> dict:
    """Ölç + yaz; önceki ölçümdeki `benchmark` korunur (K7 doldurur)."""
    eski = yukle() or {}
    profil = olc(ollama_url, sunucu)
    if eski.get("benchmark"):
        profil["benchmark"] = eski["benchmark"]
    if (eski.get("kademe") or {}).get("otomatik") in KADEMELER:  # K7: ölçüme dayalı kademe yeniden ölçümde kaybolmasın
        profil["kademe"]["otomatik"] = eski["kademe"]["otomatik"]
        profil["kademe"]["otomatik_neden"] = eski["kademe"].get("otomatik_neden", "")
        if not profil["kademe"].get("kilitli"):
            profil["kademe"]["etkin"] = eski["kademe"]["otomatik"]
    kaydet(profil)
    _onbellek_temizle()
    return profil


# ---------------------------------------------------------------- model ölçümü (benchmark, MIMARI §8)

BENCHMARK_SN = 30  # model başına ölçülen isteğin süre tavanı (yükleme hariç)
YAVAS_TOK_SN = 3.0  # altı "bu kademe için yavaş"
BENCHMARK_ISTEM = ("Bilgisayarların nasıl çalıştığını, işlemci, bellek ve depolamayı anlatarak, "
                   "dört paragrafta Türkçe açıkla.")


def _model_olc(istemci, kok: str, model: str, sure_sn: float, zaman=time.monotonic) -> dict:
    """Tek model: önce yükle (ayrı ölçülür), sonra `sure_sn` saniyelik akışla ilk token ve token/sn.

    tok_sn Ollama'nın kendi sayacından (eval_count / eval_duration); süre dolup akış kesilirse gelen parça sayısı /
    ilk tokenden sonraki süre. Ölçümden sonra model bellekten boşaltılır (sıradaki model karta sığsın)."""
    try:
        bilgi = istemci.post(kok + "/api/show", json={"model": model}, timeout=10).json()
    except Exception:
        bilgi = {}
    yetenek = set(bilgi.get("capabilities") or ())
    if yetenek and "completion" not in yetenek:
        return {"atlandi": "metin üretmiyor (" + ", ".join(sorted(yetenek)) + ")"}
    dusunme = {"think": False} if "thinking" in yetenek else {}
    sonuc: dict = {}
    try:
        basla = zaman()
        r = istemci.post(kok + "/api/generate", json={"model": model, "keep_alive": "2m"}, timeout=180)
        if r.status_code != 200:
            return {"hata": f"yüklenemedi: {r.status_code} {r.text[:200]}"}
        sonuc["yukleme_ms"] = round((zaman() - basla) * 1000)

        govde = {"model": model, "prompt": BENCHMARK_ISTEM, "stream": True, "keep_alive": "2m",
                 "options": {"num_predict": 512, "temperature": 0}, **dusunme}
        basla, ilk, parca, son = zaman(), None, 0, {}
        with istemci.stream("POST", kok + "/api/generate", json=govde, timeout=sure_sn + 30) as akis:
            if akis.status_code != 200:
                akis.read()
                return {**sonuc, "hata": f"{akis.status_code} {akis.text[:200]}"}
            for satir in akis.iter_lines():
                if not satir:
                    continue
                veri = json.loads(satir)
                if veri.get("error"):
                    return {**sonuc, "hata": str(veri["error"])[:200]}
                if veri.get("response") or veri.get("thinking"):
                    parca += 1
                    if ilk is None:
                        ilk = zaman()
                if veri.get("done"):
                    son = veri
                    break
                if zaman() - basla >= sure_sn:
                    break
        bitti = zaman()
        if ilk is None:
            return {**sonuc, "hata": f"{sure_sn:.0f} sn içinde token gelmedi"}
        sonuc["ilk_token_ms"] = round((ilk - basla) * 1000)
        if son.get("eval_count") and son.get("eval_duration"):
            sonuc["token"] = son["eval_count"]
            sonuc["tok_sn"] = round(son["eval_count"] / (son["eval_duration"] / 1e9), 1)
        else:  # süre doldu: kendi sayımımız
            sonuc["token"] = parca
            sonuc["tok_sn"] = round(parca / max(bitti - ilk, 1e-3), 1)
            sonuc["kesildi"] = True
        sonuc["sure_sn"] = round(bitti - basla, 1)
        try:  # bellek: kartta ne kadarı (Ollama bölünmüşse kalan RAM'de, yavaşlığın nedeni)
            for m in istemci.get(kok + "/api/ps", timeout=5).json().get("models", []):
                if m.get("name") == model or m.get("model") == model:
                    boyut, kart = m.get("size") or 0, m.get("size_vram") or 0
                    sonuc["bellek_gb"] = round(boyut / 1024 ** 3, 1)
                    sonuc["kartta_yuzde"] = round(100 * kart / boyut) if boyut else 0
        except Exception:
            pass
    except Exception as e:
        sonuc["hata"] = f"{type(e).__name__}: {e}"[:200]
    finally:
        try:
            istemci.post(kok + "/api/generate", json={"model": model, "keep_alive": 0}, timeout=15)
        except Exception:
            pass
    return sonuc


def benchmark(modeller: list[str] | None = None, ollama_url: str | None = None, sure_sn: float = BENCHMARK_SN,
              istemci=None, ilerleme=None) -> dict:
    """Ollama'daki modelleri (ya da verilenleri) sırayla ölçer, `profil.json → benchmark`'a yazar (öncekiler korunur).

    Her model: {tok_sn, ilk_token_ms, yukleme_ms, token, sure_sn, bellek_gb, kartta_yuzde, olcum, kademe, yavas};
    3 tok/sn altı `yavas: true` + not. Metin üretmeyen (embedding) modeller atlanır."""
    import httpx

    kok = (ollama_url or ayar.deger("saglayici.ollama.url")).rstrip("/")
    profil = yukle() or guncelle(ollama_url)
    kapat = istemci is None
    istemci = istemci or httpx.Client()
    try:
        if modeller is None:
            modeller = [m["name"] for m in istemci.get(kok + "/api/tags", timeout=5).json().get("models", [])]
        etkin = kademe()
        tablo = dict(profil.get("benchmark") or {})
        for model in modeller:
            if ilerleme:
                ilerleme(model, None)
            s = _model_olc(istemci, kok, model, sure_sn)
            s["olcum"] = datetime.now().isoformat(timespec="seconds")
            s["kademe"] = etkin
            if "tok_sn" in s:
                s["yavas"] = s["tok_sn"] < YAVAS_TOK_SN
                if s["yavas"]:
                    s["not"] = "bu kademe için yavaş"
            tablo[model] = s
            profil["benchmark"] = tablo
            kaydet(profil)  # her modelden sonra: yarıda kesilse de ölçülenler kalır
            if ilerleme:
                ilerleme(model, s)
    finally:
        if kapat:
            istemci.close()
    return profil.get("benchmark") or {}


def benchmark_satiri(model: str, s: dict) -> str:
    if s.get("atlandi"):
        return f"{model}: atlandı — {s['atlandi']}"
    if s.get("hata") and "tok_sn" not in s:
        return f"{model}: HATA — {s['hata']}"
    satir = (f"{model}: {s['tok_sn']} tok/sn · ilk token {s['ilk_token_ms']} ms · yükleme {s.get('yukleme_ms', '?')} ms"
             f" · {s.get('bellek_gb', '?')} GB (%{s.get('kartta_yuzde', '?')} kartta)")
    return satir + (" · ⚠ bu kademe için yavaş" if s.get("yavas") else "")


_kilit = threading.Lock()
_etkin: tuple[float, str] | None = None  # (zaman, etkin kademe) — süreç içi önbellek
ONBELLEK_SN = 30  # ayar.toml'daki kilit en geç bu kadar sonra geçerli olur; arayüzden kilit hemen


_hafif: str | None = None


def _hafif_kademe() -> str:
    """profil.json yokken: donanım süreçte bir kez ölçülür (kart denetimi Vulkan/torch'a düşerse saniyeler sürer)."""
    global _hafif
    if _hafif is None:
        _hafif = kademe_hesapla(olc(hafif=True))[0]
    return _hafif


def _onbellek_temizle() -> None:
    global _etkin
    with _kilit:
        _etkin = None


def temel_kademe() -> str:
    """Güç/donanım kararı (K13) uygulanmadan etkin kademe: kilit → K7 otomatik → ölçülen → hafif ölçüm."""
    etkin = kilit()
    if not etkin:
        k = (yukle() or {}).get("kademe") or {}
        etkin = k.get("otomatik") if k.get("otomatik") in KADEMELER else k.get("olculen")  # K7: ölçüme göre kayar
        if etkin not in KADEMELER:
            etkin = _hafif_kademe()
    return etkin


def kademe() -> str:
    """Etkin kademe: kilit → profil.json'daki ölçüm → (dosya yoksa) hafif ölçüm; kilit YOKKEN K13 güç/donanım kararı
    (pilde yüksek kapalı) üst sınır olarak uygulanır. Her model çağrısında sorulur (bağlam tavanı): 30 sn önbellekli."""
    global _etkin
    with _kilit:
        if _etkin and time.time() - _etkin[0] < ONBELLEK_SN:
            return _etkin[1]
    etkin = temel_kademe()
    if not kilit():
        from . import donanim

        sinir = (donanim.karar() or {}).get("kademe")
        sira = ("dusuk", "orta", "yuksek")
        if sinir in sira and etkin in sira and sira.index(sinir) < sira.index(etkin):
            etkin = sinir
    with _kilit:
        _etkin = (time.time(), etkin)
    return etkin


def acik_mi(ozellik: str) -> bool:
    """Ağır özellik bu kademede açık mı? (`embedding`, `tarayici`, `uzun_baglam`)"""
    return ozellik not in KAPALI.get(kademe(), ())


def tarayici_klasoru() -> str:
    """Chromium'un yeri: programın kendi klasörü (kurulum paketine gömülür); yoksa boş."""
    kok = Path(__file__).resolve().parents[2]  # <program>/asistan/cekirdek/profil.py → <program>
    for p in (kok / "tarayici", Path.home() / ".local/share/yeni-nesil-cafer-app/tarayici"):
        if p.is_dir():
            return str(p)
    return ""


def tarayici_hazir() -> bool:
    """Tarayıcı otomasyonu kullanılabilir mi: kademe açık + `playwright` paketi + gömülü Chromium. Çekirdek bunu
    `asistan.browser`'ı (Playwright'a bağlı, ağır) içe aktarmadan sorar (MIMARI §11.7); `browser.available` buraya devreder."""
    return acik_mi("tarayici") and find_spec("playwright") is not None and bool(tarayici_klasoru())


def kapali_notu(ozellik: str) -> str:
    """Arayüz metni: "… — bu kademede kapalı (düşük)"; açıksa boş."""
    if acik_mi(ozellik):
        return ""
    return f"{AGIR_OZELLIKLER.get(ozellik, ozellik)} — bu kademede kapalı ({ADLAR[kademe()]})"


# ---------------------------------------------------------------- özet

def ozet(profil: dict) -> str:
    """İnsan okunur, çok satırlı Türkçe özet (komut satırı ve arayüz)."""
    from . import modeller

    k = profil.get("kademe") or {}
    cpu, gpu, oll = profil.get("cpu") or {}, profil.get("gpu") or {}, profil.get("ollama")
    satirlar = [
        f"Kademe: {ADLAR.get(k.get('etkin'), '?')}"
        + (f" (kilitli; ölçülen: {ADLAR.get(k.get('olculen'), '?')})" if k.get("kilitli")
           else f" (hız ölçümüyle ayarlandı; donanıma göre: {ADLAR.get(k.get('olculen'), '?')} — {k.get('otomatik_neden', '')})"
           if k.get("otomatik") else " (ölçüldü)"),
        f"Neden: {k.get('neden', '')}",
        f"İşletim sistemi: {profil.get('isletim', '?')}",
        f"İşlemci: {cpu.get('model', '?')} · {cpu.get('cekirdek', 0)} çekirdek / {cpu.get('iplik', 0)} iş parçacığı",
        f"Bellek: {profil.get('ram_gb', 0)} GB",
        "Ekran kartı: " + (f"{gpu.get('ad')} · {gpu.get('vram_gb')} GB ({gpu.get('arka_uc')})" if gpu.get("var")
                           else "yok (ya da ayrı kart bulunamadı)"),
        f"Boş disk: {profil.get('disk_bos_gb', 0)} GB",
    ]
    if "ag" in profil:
        satirlar.append(f"Ağ: {'var' if profil['ag'] else 'yok'}")
    if oll is not None:
        satirlar.append("Ollama: " + (f"çalışıyor {oll.get('surum', '')} · {len(oll.get('modeller', []))} model"
                                      if oll.get("calisiyor") else "çalışmıyor"))
    etkin = k.get("etkin")
    kapali = [AGIR_OZELLIKLER[o] for o in AGIR_OZELLIKLER if o in KAPALI.get(etkin, ())]
    satirlar.append("Bu kademede kapalı: " + (", ".join(kapali) if kapali else "hiçbir şey"))
    oneriler = modeller.kademe_modelleri(etkin) if etkin else {"yerel": [], "bulut": []}
    satirlar.append("Önerilen modeller: yerel " + (", ".join(oneriler["yerel"]) or "—")
                    + " · bulut " + (", ".join(oneriler["bulut"]) or "—"))
    olcum = {m: s for m, s in (profil.get("benchmark") or {}).items() if "tok_sn" in s}
    if olcum:
        yavas = [m for m, s in olcum.items() if s.get("yavas")]
        satirlar.append(f"Ölçülen modeller: {len(olcum)}"
                        + (" · bu kademe için yavaş: " + ", ".join(yavas) if yavas else " · hepsi yeterince hızlı"))
    return "\n".join(satirlar)


def komut(argv: list[str]) -> int:
    """`profil` komutu: ölç, yaz, özeti bas. `--json` ham profil; `--kilitle <kademe>`, `--kilidi-ac`;
    `--benchmark [model …]` modelleri ölçer."""
    import argparse

    ap = argparse.ArgumentParser(prog="cafer profil", description="Donanım profili ve kademe")
    ap.add_argument("--json", action="store_true", help="profili JSON olarak yaz")
    ap.add_argument("--kilitle", choices=KADEMELER, help="kademeyi elle sabitle (ölçüm ezmez)")
    ap.add_argument("--kilidi-ac", action="store_true", help="kilidi kaldır, ölçülen kademe geçerli olsun")
    ap.add_argument("--masaustu", action="store_true", help="ekransız olsa da sunucu sayma")
    ap.add_argument("--benchmark", nargs="*", metavar="MODEL",
                    help=f"Ollama modellerini {BENCHMARK_SN} sn'lik kısa istekle ölç (model verilmezse hepsi)")
    a = ap.parse_args(argv)
    if a.kilitle or a.kilidi_ac:
        if kilit_kaynagi() == "dosya":
            print("Kademe ayar.toml ya da CAFER_GENEL_KADEME_KILIDI ile kilitli; oradan değiştir.", file=sys.stderr)
            return 2
        kilitle(a.kilitle if a.kilitle else None)
    profil = guncelle(sunucu=False if a.masaustu else None)
    if a.benchmark is not None:
        def ilerleme(model, s):
            print(f"… {model} ölçülüyor" if s is None else benchmark_satiri(model, s), flush=True)

        benchmark(a.benchmark or None, ilerleme=None if a.json else ilerleme)
        profil = yukle() or profil
    if a.json:
        print(json.dumps(profil, indent=2, ensure_ascii=False))
    else:
        print(ozet(profil))
        print(f"\nKaydedildi: {dosya()}")
    return 0


if __name__ == "__main__":
    sys.exit(komut(sys.argv[1:]))
