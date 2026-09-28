"""Yetenek çalıştırıcı: `calistir(girdi, baglam)` çağrısını manifestin sözleşmesiyle yapar.

Sıra: yetenek aktif mi → girdi (varsayılanlar + şema) → çalıştır → çıktı şeması. Hata hep `YetenekHatasi`.
- `sandbox: true`: ayrı süreç, yeteneğe ait ayrı venv (`DATA_DIR/yetenek-ortamlari/<ad>`, `--system-site-packages`:
  programın paketlerini görür, kendi kurduğu paketler oraya gider), manifestteki zaman aşımı (süreç grubu öldürülür),
  anahtarsız ortam (`anahtar:<AD>` izni olan değişken geçer), ağ izni yoksa Linux'ta ağsız ad alanı (`unshare -rn`),
  izin dışı dosya/ağ/komut erişimi denetim kancasıyla engelli (`_kum_giris.py`). Çıktı boyutu sınırlı.
- `sandbox: false` (yalnızca yerleşik): süreç içinde; yan etkili her iş `baglam.arac` ile programın tek araç yolundan
  (`Agent._execute_tool` → `permissions.decide`) geçer.

Onay burada verilmez: çağıran (görev motorunun uyarlayıcısı) çağrıyı önce izin hattından geçirir.
"""

import json
import logging
import os
import shutil
import signal
import subprocess
import sys
import tempfile
from functools import cache
from pathlib import Path

from .. import semalar
from . import Baglam, YetenekHatasi
from .kayit import Yetenek, modul_yukle

GIRIS = Path(__file__).resolve().parent / "_kum_giris.py"
PROGRAM_KOKU = Path(__file__).resolve().parents[3]  # asistan/'ın üstü: sandbox PYTHONPATH'i
UST_ZAMAN_SINIRI = 600  # sn; manifest daha azını ister (K6: ayar/guvenlik.toml)
MAKS_CIKTI = 1_000_000  # bayt
_log = logging.getLogger("asistan.yetenek")


def ortam_koku() -> Path:
    from ..ayar import DATA_DIR

    return DATA_DIR / "yetenek-ortamlari"


def girdi_hazirla(yetenek: Yetenek, girdi: dict) -> dict:
    """Varsayılanları doldurur, şemaya göre denetler; uymazsa `YetenekHatasi("veri")`."""
    if not isinstance(girdi, dict):
        raise YetenekHatasi("veri", "girdi bir nesne olmalı")
    tam = dict(girdi)
    for ad, alan in (yetenek.manifest.get("girdi") or {}).items():
        if ad not in tam and "varsayilan" in alan:
            tam[ad] = alan["varsayilan"]
    hatalar = semalar.dogrula(tam, yetenek.girdi_semasi(), _yol="girdi")
    if hatalar:
        raise YetenekHatasi("veri", f"{yetenek.ad} girdisi uymuyor: " + "; ".join(hatalar[:5]))
    return tam


def cikti_denetle(yetenek: Yetenek, cikti) -> dict:
    if not isinstance(cikti, dict):
        raise YetenekHatasi("mantik", f"{yetenek.ad} sözlük döndürmedi ({type(cikti).__name__})")
    sema = dict(yetenek.cikti_semasi(), required=[])
    hatalar = semalar.dogrula(cikti, sema, _yol="cikti")
    if hatalar:
        raise YetenekHatasi("mantik", f"{yetenek.ad} çıktısı manifeste uymuyor: " + "; ".join(hatalar[:5]))
    return cikti


def calistir(yetenek: Yetenek, girdi: dict, baglam: Baglam, *, python: str | None = None,
             ortamlar: Path | None = None, kutuphane_yollari: list | tuple = (), anahtar_bul=None) -> dict:
    """Yeteneği çalıştırır, manifestteki `cikti`ya uyan sözlük döndürür."""
    if not yetenek.aktif:
        sinif = "eksik_bagimlilik" if "kurulu değil" in yetenek.neden else "eksik_yetenek"
        raise YetenekHatasi(sinif, f"{yetenek.ad} kullanılamıyor: {yetenek.neden}")
    girdi = girdi_hazirla(yetenek, girdi)
    if yetenek.sandbox:
        cikti = kum_havuzunda(yetenek, girdi, baglam, python=python, ortamlar=ortamlar,
                              kutuphane_yollari=kutuphane_yollari, anahtar_bul=anahtar_bul)
    else:
        try:
            cikti = modul_yukle(yetenek).calistir(girdi, baglam)
        except YetenekHatasi:
            raise
        except PermissionError as e:
            raise YetenekHatasi("izin", str(e)) from e
        except Exception as e:
            raise YetenekHatasi("mantik", f"{type(e).__name__}: {e}") from e
    return cikti_denetle(yetenek, cikti)


# ---------------------------------------------------------------- sandbox

@cache
def _agsiz_onek() -> tuple[str, ...]:
    """Linux'ta ağsız ad alanı (unshare -rn); desteklenmiyorsa boş (kanca yine ağı engeller)."""
    if sys.platform != "linux" or not shutil.which("unshare"):
        return ()
    try:
        tamam = subprocess.run(["unshare", "-rn", "true"], capture_output=True, timeout=5).returncode == 0
    except (OSError, subprocess.SubprocessError):
        tamam = False
    return ("unshare", "-rn") if tamam else ()


def venv_python(ad: str, python: str, ortamlar: Path) -> str:
    """Yeteneğin ayrı venv'i (bir kez kurulur). Kurulamazsa programın Python'u (günlüğe yazılır)."""
    klasor = ortamlar / ad
    exe = klasor / ("Scripts/python.exe" if sys.platform == "win32" else "bin/python")
    cfg = klasor / "pyvenv.cfg"
    ev = str(Path(python).resolve().parent)
    if exe.exists() and cfg.exists() and f"home = {ev}" in cfg.read_text(encoding="utf-8", errors="replace"):
        return str(exe)
    if klasor.exists():  # programın Python'u değişti (güncelleme): venv yeniden kurulur
        shutil.rmtree(klasor, ignore_errors=True)
    ortamlar.mkdir(parents=True, exist_ok=True)
    try:
        subprocess.run([python, "-m", "venv", "--system-site-packages", "--without-pip", str(klasor)],
                       capture_output=True, timeout=120, check=True)
    except (OSError, subprocess.SubprocessError) as e:
        _log.warning("yetenek venv'i kurulamadı (%s): %s; programın Python'u kullanılıyor", ad, e)
        return python
    return str(exe) if exe.exists() else python


def _ortam(yetenek: Yetenek, gecici: str, kutuphane_yollari, anahtar_bul) -> dict:
    """Alt sürecin ortamı: yalnızca gerekenler; API anahtarları yok (izin verilen hariç)."""
    ortam = {"PATH": os.environ.get("PATH", ""), "HOME": gecici, "TMPDIR": gecici, "TEMP": gecici, "TMP": gecici,
             "LANG": os.environ.get("LANG") or "C.UTF-8", "PYTHONIOENCODING": "utf-8", "PYTHONUTF8": "1",
             "PYTHONDONTWRITEBYTECODE": "1", "PYTHONNOUSERSITE": "1",
             "PYTHONPATH": os.pathsep.join([str(PROGRAM_KOKU), *[str(y) for y in kutuphane_yollari]])}
    if sys.platform == "win32":
        ortam["SYSTEMROOT"] = os.environ.get("SYSTEMROOT", r"C:\Windows")
    for izin in yetenek.izinler:
        if izin.startswith("anahtar:"):
            ad = izin.split(":", 1)[1]
            deger = (anahtar_bul(ad) if anahtar_bul else None) or os.environ.get(ad)
            if deger:
                ortam[ad] = deger
    return ortam


def _durdur(proc: subprocess.Popen) -> None:
    try:
        if sys.platform == "win32":
            proc.kill()
        else:
            os.killpg(proc.pid, signal.SIGKILL)
    except (OSError, ProcessLookupError):
        pass
    try:
        proc.wait(5)
    except subprocess.TimeoutExpired:
        pass


def kum_havuzunda(yetenek: Yetenek, girdi: dict, baglam: Baglam, *, python: str | None = None,
                  ortamlar: Path | None = None, kutuphane_yollari=(), anahtar_bul=None,
                  ust_sinir: int = UST_ZAMAN_SINIRI) -> dict:
    """Yeteneği sandbox alt sürecinde çalıştırır; `cikti` sözlüğünü döndürür."""
    python = python or sys.executable
    exe = venv_python(yetenek.ad, python, ortamlar or ortam_koku())
    sure = max(1, min(yetenek.zaman_asimi, ust_sinir))
    gecici = tempfile.mkdtemp(prefix=f"yetenek-{yetenek.ad}-")
    ayar = {k: v for k, v in dict(baglam.ayar or {}).items() if isinstance(v, (str, int, float, bool, type(None)))}
    from ..araclar.temel import GIZLI_DOSYALAR
    from ..ayar import CONFIG_DIR
    is_ = {"ad": yetenek.ad, "yetenek_klasoru": str(yetenek.klasor.resolve()),
           "calisma_klasoru": str(Path(baglam.calisma_klasoru).resolve()),
           "okuma_kokleri": [str(k) for k in baglam.okuma_kokleri], "kademe": baglam.kademe, "ayar": ayar,
           "izinler": yetenek.izinler, "gecici": gecici, "program_koku": str(PROGRAM_KOKU),
           "kutuphane_yollari": [str(y) for y in kutuphane_yollari], "girdi": girdi,
           "yasak_kokler": [str(CONFIG_DIR)], "yasak_adlar": sorted(GIZLI_DOSYALAR)}
    onek = () if "ag" in yetenek.izinler else _agsiz_onek()
    argv = [*onek, exe, "-B", str(GIRIS)]
    try:
        with tempfile.TemporaryFile() as cikis, tempfile.TemporaryFile() as hata:
            proc = subprocess.Popen(argv, stdin=subprocess.PIPE, stdout=cikis, stderr=hata, cwd=gecici,
                                    env=_ortam(yetenek, gecici, kutuphane_yollari, anahtar_bul),
                                    start_new_session=sys.platform != "win32",
                                    creationflags=getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
                                    | getattr(subprocess, "CREATE_NO_WINDOW", 0))
            try:
                proc.communicate(json.dumps(is_, ensure_ascii=False).encode("utf-8"), timeout=sure)
            except subprocess.TimeoutExpired:
                _durdur(proc)
                raise YetenekHatasi("kaynak", f"{yetenek.ad}: zaman aşımı ({sure} sn); süreç durduruldu") from None
            cikis.seek(0)
            ham = cikis.read(MAKS_CIKTI).decode("utf-8", errors="replace")
            hata.seek(0, os.SEEK_END)
            boy = hata.tell()
            hata.seek(max(0, boy - 4000))
            gunluk = hata.read().decode("utf-8", errors="replace").strip()
    finally:
        shutil.rmtree(gecici, ignore_errors=True)
    if gunluk:
        baglam.gunluk.info("[%s] %s", yetenek.ad, gunluk[-2000:])
    satir = next((s for s in reversed(ham.splitlines()) if s.strip()), "")
    try:
        cevap = json.loads(satir)
    except ValueError:
        son = "\n".join(gunluk.splitlines()[-5:])
        raise YetenekHatasi("mantik", f"{yetenek.ad} sonuç vermedi (çıkış kodu {proc.returncode})"
                            + (f":\n{son}" if son else "")) from None
    if not cevap.get("tamam"):
        mesaj = str(cevap.get("mesaj") or "bilinmeyen hata")
        if cevap.get("iz"):
            mesaj += "\n" + str(cevap["iz"])
        raise YetenekHatasi(str(cevap.get("sinif") or "mantik"), mesaj)
    return cevap.get("cikti")
