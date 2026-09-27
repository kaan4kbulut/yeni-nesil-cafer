"""YENİ NESİL CAFER'i paylaşılabilir kurulum paketlerine dönüştürür (masaüstünde bir klasöre).

    .venv/bin/python paketleme/paketle.py   (--modelsiz: temel model olmadan, küçük paket)

Çıktı: <Masaüstü>/YENİ NESİL CAFER/Kurulum Paketleri/YENI-NESIL-CAFER.v2.2/   (ad, asistan/__init__.py'deki tam sürümden gelir: sürüm değişince adlar da değişir)
    YENI-NESIL-CAFER.v2.2-Windows.zip   → çıkar, Kur.bat'a çift tıkla
    YENI-NESIL-CAFER.v2.2-Linux.tar.gz  → çıkar, kur.sh'ı çalıştır
    BENIOKU.txt                (paketleme/BENIOKU.txt; @PAKET@ ve @SURUM@ burada doldurulur)

Paketler kendi kendine yeter: içlerinde taşınabilir Python, önceden kurulmuş kütüphaneler ve Ollama vardır.
Kurulum hiçbir şey indirmez. Bunlar ilk paketlemede bir kez indirilip ~/.cache/yeni-nesil-cafer-paketleme'de tutulur.
"""

import hashlib
import io
import os
import re
import shutil
import subprocess
import sys
import tarfile
import time
import urllib.request
import zipfile
from pathlib import Path

PROJE = Path(__file__).resolve().parent.parent
PAKET = Path(__file__).resolve().parent
ATLA = {".venv", "__pycache__", ".git", "paketleme", ".pytest_cache", ".ruff_cache", "modeller", "python", "ollama",
        "ajan-kutuphaneleri", "tarayici", "dist"}  # dist: bulut sunucusu paketi (kuruluma girmez)
# Playwright'ın Chromium'u hangi sistem için indirileceği (Linux'tan Windows sürümü de indirilebilir)
PW_PLATFORM = {"windows": "win64", "linux": ""}
ONBELLEK = Path.home() / ".cache" / "yeni-nesil-cafer-paketleme"
if not ONBELLEK.exists() and (Path.home() / ".cache" / "yerel-asistan-paketleme").is_dir():  # eski adı: 11 GB yeniden inmesin
    (Path.home() / ".cache" / "yerel-asistan-paketleme").rename(ONBELLEK)

# sabit sürümler: paket her seferinde aynı çıksın
PY_SURUM, PY_ETIKET = "3.12.14", "20260901"
PY_URL = ("https://github.com/astral-sh/python-build-standalone/releases/download/{etiket}/"
          "cpython-{surum}+{etiket}-{hedef}-install_only_stripped.tar.gz")
# internet paketinin kurucusu Python arşivini bu özetle doğrular (kur.sh / kur.ps1'e paketlemede yazılır)
PY_SHA = {"windows": "7c45c9622400d578709a9b2cddbe8124cc21d382409d9f13406d706d28e31b14",
          "linux": "72748da13197c1fb161e3afeef20a6a385ff24f2165e6e2758e47008e7faba4c"}
OLLAMA_SURUM = "v0.34.4"  # asistan/bootstrap.py'deki sürüm ve özetlerle aynı olmalı
OLLAMA_URL = "https://github.com/ollama/ollama/releases/download/{surum}/{dosya}"
PLATFORM = {
    "windows": {"py": "x86_64-pc-windows-msvc", "pip": ["win_amd64"],
                "ollama": ["ollama-windows-amd64.zip", "ollama-windows-amd64-rocm.zip"],
                "site": "Lib/site-packages",
                # pip --platform ortam işaretlerini (sys_platform) çevirmez: Windows'a özgü bağımlılıklar elle
                "ek": ["pywin32-ctypes", "colorama", "tzdata"]},
    "linux": {"py": "x86_64-unknown-linux-gnu",
              "pip": ["manylinux_2_28_x86_64", "manylinux_2_17_x86_64", "manylinux2014_x86_64"],
              "ollama": ["ollama-linux-amd64.tar.zst"], "site": "lib/python3.12/site-packages", "ek": []},
}


def indir(url: str) -> Path:
    hedef = ONBELLEK / "indirilen" / url.rsplit("/", 1)[1].replace("%2B", "+")
    if not hedef.exists():
        hedef.parent.mkdir(parents=True, exist_ok=True)
        print(f"indiriliyor: {hedef.name}", flush=True)
        gecici = hedef.with_suffix(hedef.suffix + ".part")
        with urllib.request.urlopen(url) as cevap, open(gecici, "wb") as f:
            shutil.copyfileobj(cevap, f, 1 << 20)
        gecici.rename(hedef)
    return hedef


def calisma_zamani(sistem: str) -> Path:
    """<önbellek>/<sistem>/ altında python/ (kütüphaneleri kurulu) ve ollama/ hazırlar; hazırsa yeniden yapmaz."""
    ayar = PLATFORM[sistem]
    gereken = (PROJE / "requirements.txt").read_text() + str(ayar) + PY_SURUM + PY_ETIKET + OLLAMA_SURUM
    imza = hashlib.sha256(gereken.encode()).hexdigest()[:16]
    kok = ONBELLEK / sistem
    if (kok / "HAZIR").exists() and (kok / "HAZIR").read_text() == imza:
        return kok
    shutil.rmtree(kok, ignore_errors=True)
    kok.mkdir(parents=True)

    arsiv = indir(py_url(sistem))
    if hashlib.sha256(arsiv.read_bytes()).hexdigest() != PY_SHA[sistem]:
        sys.exit(f"{arsiv.name}: SHA-256 PY_SHA ile tutmuyor (sürüm değiştiyse PY_SHA'yı da güncelle)")
    with tarfile.open(arsiv) as t:
        t.extractall(kok, filter="tar")  # python/ klasörü

    # kütüphaneler hedef sistemin hazır paketlerinden (wheel) kurulur; derleme yok
    pip = calisma_zamani("linux") / "python" / "bin" / "python3" if sistem != "linux" else kok / "python/bin/python3"
    platformlar = [a for p in ayar["pip"] for a in ("--platform", p)]
    print(f"{sistem}: kütüphaneler hazırlanıyor…", flush=True)
    subprocess.run([str(pip), "-m", "pip", "install", "--quiet", "--disable-pip-version-check", "--no-compile",
                    "--target", str(kok / "python" / ayar["site"]), "--upgrade",
                    "--only-binary=:all:", "--python-version", "3.12", "--implementation", "cp", *platformlar,
                    "-r", str(PROJE / "requirements.txt"), *ayar["ek"]], check=True)

    ollama = kok / "ollama"
    ollama.mkdir()
    for dosya in ayar["ollama"]:
        arsiv = indir(OLLAMA_URL.format(surum=OLLAMA_SURUM, dosya=dosya))
        print(f"{sistem}: {dosya} açılıyor…", flush=True)
        if dosya.endswith(".zip"):
            with zipfile.ZipFile(arsiv) as z:
                z.extractall(ollama)
        else:
            subprocess.run(["tar", "--zstd", "-xf", str(arsiv), "-C", str(ollama)], check=True)
    (kok / "HAZIR").write_text(imza)
    return kok


def ajan_kutuphaneleri(sistem: str) -> Path:
    """Ajanların Python kodu için hazır kütüphaneler (paketleme/ajan-kutuphaneleri.txt) → <önbellek>/<sistem>/ajan-…"""
    kok = calisma_zamani(sistem)
    ayar = PLATFORM[sistem]
    liste = PAKET / "ajan-kutuphaneleri.txt"
    imza = hashlib.sha256((liste.read_text() + str(ayar)).encode()).hexdigest()[:16]
    hedef = kok / "ajan-kutuphaneleri"
    isaret = kok / "AJAN_HAZIR"
    if isaret.exists() and isaret.read_text() == imza:
        return hedef
    shutil.rmtree(hedef, ignore_errors=True)
    print(f"{sistem}: ajan kütüphaneleri hazırlanıyor…", flush=True)
    platformlar = [a for p in ayar["pip"] for a in ("--platform", p)]
    subprocess.run([str(ONBELLEK / "linux" / "python" / "bin" / "python3"), "-m", "pip", "install", "--quiet",
                    "--disable-pip-version-check", "--no-compile", "--target", str(hedef),
                    "--only-binary=:all:", "--python-version", "3.12", "--implementation", "cp", *platformlar,
                    "-r", str(liste), *ayar["ek"]], check=True)
    isaret.write_text(imza)
    return hedef


def tarayici(sistem: str) -> Path:
    """BrowserAgent'ın Chromium'u → <önbellek>/<sistem>/tarayici (program/tarayici olarak pakete girer).
    Sürüm, paketteki Playwright'la birebir eşleşir; görünmez mod tarayıcısı alınmaz (tarayıcı hep görünür)."""
    import importlib.metadata as md

    kok = calisma_zamani(sistem)
    linux_py = ONBELLEK / "linux" / "python" / "bin" / "python3"
    calisma_zamani("linux")  # indirici Linux çalışma zamanındaki Playwright
    surum = next(d.version for d in md.distributions(path=[str(ONBELLEK / "linux" / "python" / PLATFORM["linux"]["site"])])
                 if (d.metadata["Name"] or "").lower() == "playwright")
    hedef, isaret = kok / "tarayici", kok / "TARAYICI_HAZIR"
    if isaret.exists() and isaret.read_text() == surum and hedef.is_dir():
        return hedef
    shutil.rmtree(hedef, ignore_errors=True)
    print(f"{sistem}: Chromium indiriliyor (Playwright {surum})…", flush=True)
    env = {**os.environ, "PLAYWRIGHT_BROWSERS_PATH": str(hedef)}
    if PW_PLATFORM[sistem]:
        env["PLAYWRIGHT_HOST_PLATFORM_OVERRIDE"] = PW_PLATFORM[sistem]
    subprocess.run([str(linux_py), "-m", "playwright", "install", "--no-shell", "chromium"], env=env, check=True)
    isaret.write_text(surum)
    return hedef


def calisma_zamani_dosyalari(sistem: str):
    """(kaynak, paketteki göreli yol): program/python/…, program/ollama/…, program/ajan-kutuphaneleri/…,
    program/tarayici/…"""
    kok = calisma_zamani(sistem)
    ajan_kutuphaneleri(sistem)
    tarayici(sistem)
    for ad in ("python", "ollama", "ajan-kutuphaneleri", "tarayici"):
        for path in sorted((kok / ad).rglob("*")):
            if path.is_dir() and not path.is_symlink():
                continue
            if "__pycache__" in path.parts:
                continue
            yield path, Path("program") / path.relative_to(kok)


def py_url(sistem: str) -> str:
    return PY_URL.format(etiket=PY_ETIKET, surum=PY_SURUM, hedef=PLATFORM[sistem]["py"])


def betik(path: Path) -> bytes:
    """Kurulum betiği; internet kurulumunun Python adresi ve SHA-256 yer tutucuları doldurulur."""
    ps1 = path.suffix == ".ps1"
    text = path.read_text(encoding="utf-8-sig" if ps1 else "utf-8")
    for sistem in ("linux", "windows"):
        text = text.replace(f"@PY_URL_{sistem.upper()}@", py_url(sistem)).replace(f"@PY_SHA_{sistem.upper()}@",
                                                                                   PY_SHA[sistem])
    return text.encode("utf-8-sig" if ps1 else "utf-8")  # PowerShell 5.1 BOM'suz dosyayı ANSI sanar


def kilit(sistem: str) -> dict[str, bytes]:
    """İnternet kurulumunun indireceği kütüphane listeleri: tam paketteki kurulu sürümler birebir (denenmiş bileşim)."""
    import importlib.metadata as md

    def liste(klasor: Path) -> bytes:
        surumler: dict[str, tuple] = {}
        for d in md.distributions(path=[str(klasor)]):
            ad = d.metadata["Name"] or ""
            if not ad or ad.lower() in ("pip", "setuptools", "wheel"):
                continue
            anahtar = tuple(int(x) if x.isdigit() else 0 for x in d.version.replace("-", ".").split("."))
            if ad.lower() not in surumler or anahtar > surumler[ad.lower()][0]:  # aynı paketin eski izi kalmışsa yenisi
                surumler[ad.lower()] = (anahtar, f"{ad}=={d.version}")
        return ("\n".join(v[1] for _, v in sorted(surumler.items())) + "\n").encode()

    kok = calisma_zamani(sistem)
    return {"program-kutuphaneleri.txt": liste(kok / "python" / PLATFORM[sistem]["site"]),
            "ajan-kutuphaneleri.txt": liste(ajan_kutuphaneleri(sistem))}


def paket_klasoru() -> Path:
    """Paketler masaüstünde tek klasörde toplanır (kullanıcı masaüstünün dağılmasını istemedi, 2026-09-27)."""
    return masaustu() / "YENİ NESİL CAFER" / "Kurulum Paketleri"


def masaustu() -> Path:
    try:
        out = subprocess.run(["xdg-user-dir", "DESKTOP"], capture_output=True, text=True).stdout.strip()
        if out:
            return Path(out)
    except OSError:
        pass
    return Path.home() / "Desktop"


def program_dosyalari():
    """(proje içindeki yol, paketteki göreli yol) — sanal ortam ve önbellekler hariç."""
    for path in sorted(PROJE.rglob("*")):
        rel = path.relative_to(PROJE)
        if path.is_dir() or any(part in ATLA for part in rel.parts) or path.suffix == ".pyc":
            continue
        if rel.name in ("calistir.sh",):  # geliştirici başlatıcısı; kurulum kendi başlatıcısını yazar
            continue
        yield path, Path("program") / rel


def gomulu_model() -> list[tuple[Path, Path]]:
    """Temel modeli (sysinfo.BASE_MODEL) pakete koymak için: (kaynak, paketteki yol) — model dosyası ve Modelfile.

    Model bu bilgisayarda Ollama'da kurulu olmalı; Modelfile'daki FROM satırı paketteki dosyaya çevrilir."""
    sys.path.insert(0, str(PROJE))
    from asistan.sysinfo import BASE_MODEL

    model = BASE_MODEL[0]
    try:
        modelfile = subprocess.run(["ollama", "show", model, "--modelfile"], capture_output=True, text=True,
                                   check=True).stdout
    except (OSError, subprocess.CalledProcessError):
        sys.exit(f"Temel model kurulu değil: önce `ollama pull {model}` çalıştır.")
    froms = re.findall(r"^FROM (\S+)$", modelfile, re.M)
    if len(froms) != 1:
        sys.exit(f"Beklenmeyen Modelfile (FROM satırı: {len(froms)})")
    blob = Path(froms[0])
    gguf = model.replace(":", "-") + ".gguf"
    gecici = PAKET / "build"
    gecici.mkdir(exist_ok=True)
    mf = gecici / "Modelfile"
    lines = [ln for ln in modelfile.splitlines() if not ln.startswith("#")]
    mf.write_text("\n".join(f"FROM ./{gguf}" if ln.startswith("FROM ") else ln for ln in lines) + "\n",
                  encoding="utf-8")
    (gecici / "MODEL").write_text(model + "\n", encoding="utf-8")  # kurulum betikleri modelin adını buradan okur
    return [(blob, Path("program/modeller") / gguf), (mf, Path("program/modeller/Modelfile")),
            (gecici / "MODEL", Path("program/modeller/MODEL"))]


def dikte_modeli() -> list[tuple[Path, Path]]:
    """Dikte'nin ses modeli (asistan/dictation.py): bu bilgisayarda indirilmişse pakete gömülür, kurulum indirmez."""
    sys.path.insert(0, str(PROJE))
    from asistan.dictation import MODEL_DIR

    if not (MODEL_DIR / "model.bin").exists():
        print(f"UYARI: dikte modeli yok ({MODEL_DIR}); pakette dikte ilk kullanımda modeli indirecek.")
        return []
    return [(f, Path("program/modeller/dikte") / f.relative_to(MODEL_DIR))
            for f in sorted(MODEL_DIR.rglob("*")) if f.is_file() and ".cache" not in f.parts]


def internet_paketleri(cikti: Path, kok: str, benioku: Path, surum_adi: str) -> list[Path]:
    """GitHub'daki küçük kurulum dosyaları (birkaç MB): yalnızca kod, kurulum betikleri ve kütüphane listeleri; Python,
    kütüphaneler, Ollama ve tarayıcıyı kurucu indirir (asistan/bootstrap.py). Kullanıcının isteği: tek dosya, 2 GB'ın
    çok altında, gereken her şey kurulumda internetten (2026-09-27)."""
    zip_yolu = cikti / f"{surum_adi}-Windows-internet.zip"
    with zipfile.ZipFile(zip_yolu, "w", zipfile.ZIP_DEFLATED, compresslevel=9) as z:
        for src, rel in program_dosyalari():
            z.write(src, f"{kok}/{rel.as_posix()}")
        for ad, veri in kilit("windows").items():
            z.writestr(f"{kok}/program/kurulum/{ad}", veri)
        for name in ("Kur.bat", "Kaldir.bat", "kur.ps1"):
            z.writestr(f"{kok}/{name}", betik(PAKET / "windows" / name))
        z.write(benioku, f"{kok}/BENIOKU.txt")
    tar_yolu = cikti / f"{surum_adi}-Linux-internet.tar.gz"
    with tarfile.open(tar_yolu, "w:gz", compresslevel=9) as t:
        for src, rel in program_dosyalari():
            t.add(src, f"{kok}/{rel.as_posix()}", recursive=False)
        ekler = {f"program/kurulum/{ad}": (veri, 0o644) for ad, veri in kilit("linux").items()}
        ekler.update({name: (betik(PAKET / "linux" / name), 0o755) for name in ("kur.sh", "kaldir.sh")})
        for ad, (veri, kip) in ekler.items():
            bilgi = tarfile.TarInfo(f"{kok}/{ad}")
            bilgi.size, bilgi.mode, bilgi.mtime = len(veri), kip, int(time.time())
            t.addfile(bilgi, io.BytesIO(veri))
        t.add(benioku, f"{kok}/BENIOKU.txt")
    return [zip_yolu, tar_yolu]


def main():
    """Varsayılan: tam paketler + internet paketleri. --internet: yalnızca internet paketleri (saniyeler);
    --tam: yalnızca tam paketler; --modelsiz: tam paket temel model ve dikte modeli olmadan."""
    sys.path.insert(0, str(PROJE))
    from asistan import SURUM_ADI, __version__

    cikti = paket_klasoru() / SURUM_ADI
    cikti.mkdir(parents=True, exist_ok=True)
    kok = SURUM_ADI
    benioku = cikti / "BENIOKU.txt"  # dosya adları ve sürüm her pakette doğru yazsın
    benioku.write_text((PAKET / "BENIOKU.txt").read_text(encoding="utf-8").replace("@PAKET@", SURUM_ADI)
                       .replace("@SURUM@", __version__), encoding="utf-8")
    uretilen = [] if "--tam" in sys.argv else internet_paketleri(cikti, kok, benioku, SURUM_ADI)
    if "--internet" in sys.argv:
        for p in uretilen:
            print(f"{p}  ({p.stat().st_size / 1e6:.1f} MB)")
        return
    model_dosyalari = [] if "--modelsiz" in sys.argv else gomulu_model() + dikte_modeli()

    zip_yolu = cikti / f"{SURUM_ADI}-Windows.zip"
    with zipfile.ZipFile(zip_yolu, "w", zipfile.ZIP_DEFLATED, compresslevel=1) as z:
        for src, rel in [*program_dosyalari(), *calisma_zamani_dosyalari("windows")]:
            z.write(src, f"{kok}/{rel.as_posix()}")
        for src, rel in model_dosyalari:  # model dosyası zaten sıkıştırılmış: olduğu gibi (hızlı)
            z.write(src, f"{kok}/{rel.as_posix()}", compress_type=zipfile.ZIP_STORED)
        for name in ("Kur.bat", "Kaldir.bat", "kur.ps1"):
            z.writestr(f"{kok}/{name}", betik(PAKET / "windows" / name))
        z.write(benioku, f"{kok}/BENIOKU.txt")

    tar_yolu = cikti / f"{SURUM_ADI}-Linux.tar.gz"
    with tarfile.open(tar_yolu, "w:gz", compresslevel=1) as t:
        for src, rel in [*program_dosyalari(), *calisma_zamani_dosyalari("linux"), *model_dosyalari]:
            t.add(src, f"{kok}/{rel.as_posix()}", recursive=False)
        for name in ("kur.sh", "kaldir.sh"):
            veri = betik(PAKET / "linux" / name)
            bilgi = tarfile.TarInfo(f"{kok}/{name}")
            bilgi.size, bilgi.mode, bilgi.mtime = len(veri), 0o755, int(time.time())
            t.addfile(bilgi, io.BytesIO(veri))
        t.add(benioku, f"{kok}/BENIOKU.txt")

    for p in (zip_yolu, tar_yolu):
        print(f"{p}  ({p.stat().st_size / 1e9:.2f} GB)")
    for p in uretilen:
        print(f"{p}  ({p.stat().st_size / 1e6:.1f} MB)")


if __name__ == "__main__":
    main()
