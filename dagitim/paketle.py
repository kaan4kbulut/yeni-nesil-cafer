#!/usr/bin/env python3
"""Dağıtım paketleri (K11): Light (~200 MB: program + Python bağımlılıkları, model yok) ve Full (Light + gömülü
Ollama motoru + bütçeye sığan varsayılan yerel model; kurulur kurulmaz çevrimdışı). Windows `.exe`, macOS `.dmg`,
Linux `.AppImage` — her biri kendi platformunda derlenir (GitHub Actions `dagitim.yml`, üç platform).

    python dagitim/paketle.py --hafif            # bu platform için Light (PyInstaller)
    python dagitim/paketle.py --tam [--butce-gb 1.9]   # Full: Light + Ollama + bütçeye sığan model
    python dagitim/paketle.py --guncelleme       # uygulama içi güncelleme paketi (updates.ASSET, sha256)
    python dagitim/paketle.py --kuru [...]       # hiçbir şey üretmeden plan (dosyalar, boyutlar) → JSON
    python dagitim/paketle.py --eski-sil         # yeni sürüm Latest olduktan sonra: eski sürümleri etiketleriyle sil (gh)

Kurallar: GitHub sürüm dosyası 2 GB sınırı → Full ≤ 1,9 GB (model bütçeye sığmazsa Full modelsiz çıkar ve ilk açılış
modeli indirir; ekrana yazılır). İndirmeler sabit sürüm + SHA-256 (Ollama: `asistan/bootstrap.py`). Uygulama içi
güncelleme (`asistan/updates.py`) yalnızca `updates.ASSET` kod paketini ister; sürüm yüklerken o da eklenir.
"""

import argparse
import hashlib
import json
import os
import platform
import shutil
import subprocess
import sys
from pathlib import Path

PROJE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJE))
CIKTI = PROJE / "dist" / "dagitim"
AD = "YeniNesilCafer"
ATLA = {".venv", "__pycache__", ".git", "paketleme", "dagitim", ".pytest_cache", "modeller", "python", "ollama",
        "ajan-kutuphaneleri", "tarayici", "dist", "testler", "NOTLAR", "docs", ".claude", ".cafer", "sunucu"}
BUTCE_GB = 1.9  # GitHub sürüm dosyası sınırı 2 GB


def sistem() -> str:
    return {"Windows": "windows", "Darwin": "macos"}.get(platform.system(), "linux")


def surum() -> str:
    from asistan import __version__

    return __version__


def program_dosyalari() -> list[tuple[Path, str]]:
    """Light'a giren kaynak dosyalar: (yol, paket içi göreli yol). Testler, notlar, sunucu dosyaları girmez."""
    sonuc = []
    for p in sorted(PROJE.rglob("*")):
        rel = p.relative_to(PROJE)
        if p.is_dir() or any(x in ATLA for x in rel.parts) or p.suffix == ".pyc":
            continue
        if rel.parts[0] not in ("asistan",) and rel.name not in ("main.py", "requirements.txt", "README.md", "CHANGELOG.md", "LICENSE"):
            continue
        sonuc.append((p, rel.as_posix()))
    return sonuc


def boyut_mb(dosyalar) -> float:
    return round(sum(p.stat().st_size for p, _ in dosyalar) / 1e6, 1)


def model_sec(butce_gb: float = BUTCE_GB, hafif_gb: float = 0.2, ollama_gb: float = 0.35) -> str | None:
    """Full paket için bütçeye sığan EN BÜYÜK varsayılan model (`ayar/modeller.json → dagitim.tam_modeller`, boyutlar
    `kategoriler.boyutlar`). Hiçbiri sığmazsa None (Full modelsiz çıkar)."""
    from asistan.cekirdek import modeller

    adaylar = modeller.deger("dagitim.tam_modeller") or [modeller.deger("temel.model")]
    boyutlar = modeller.deger("kategoriler.boyutlar") or {}
    kalan = butce_gb - hafif_gb - ollama_gb
    uygun = [(boyutlar[m], m) for m in adaylar if m in boyutlar and boyutlar[m] <= kalan]
    return max(uygun)[1] if uygun else None


def ollama_paketi() -> dict:
    """Gömülü Ollama: sürüm ve SHA `asistan/bootstrap.py`'den (tek kaynak); indirme kurulum anında ya da --tam'da."""
    from asistan import bootstrap

    return {"surum": getattr(bootstrap, "OLLAMA_SURUM", "?"), "kaynak": "asistan/bootstrap.py"}


def plan(tur: str, butce_gb: float) -> dict:
    dosyalar = program_dosyalari()
    p = {"tur": tur, "sistem": sistem(), "surum": surum(), "dosya_sayisi": len(dosyalar),
         "kaynak_mb": boyut_mb(dosyalar), "cikti": str(CIKTI), "butce_gb": butce_gb,
         "urun": {"windows": f"{AD}-{surum()}-Windows.exe", "macos": f"{AD}-{surum()}-macOS.dmg",
                  "linux": f"{AD}-{surum()}-Linux.AppImage"}[sistem()]}
    if tur == "tam":
        p["model"] = model_sec(butce_gb)
        p["ollama"] = ollama_paketi()
        p["urun"] = p["urun"].replace(f"-{surum()}-", f"-{surum()}-Full-")
        if not p["model"]:
            p["not"] = "bütçeye sığan model yok: Full modelsiz çıkar, ilk açılış modeli indirir"
    else:
        p["urun"] = p["urun"].replace(f"-{surum()}-", f"-{surum()}-Light-")
    return p


def sha_yaz(dosya: Path) -> Path:
    sha = hashlib.sha256(dosya.read_bytes()).hexdigest()
    yol = dosya.with_name(dosya.name + ".sha256")
    yol.write_text(f"{sha}  {dosya.name}\n", encoding="utf-8")
    return yol


def pyinstaller(tek_dosya: bool) -> Path:
    """PyInstaller ile derleme (platformun kendisinde). Çıktı: dist/dagitim/build/<AD>[.exe|.app|/]."""
    if shutil.which("pyinstaller") is None:
        raise SystemExit("pyinstaller yok: pip install pyinstaller")
    ayrac = ";" if sistem() == "windows" else ":"
    veri = [f"{PROJE / 'asistan' / k}{ayrac}asistan/{k}" for k in ("ayar", "yetenekler", "beceriler", "cekirdek/semalar",
                                                                "gui/assets", "arayuz/web/statik") if (PROJE / "asistan" / k).exists()]
    argv = ["pyinstaller", "--noconfirm", "--clean", "--name", AD, "--windowed", "--distpath", str(CIKTI / "build"),
            "--workpath", str(CIKTI / "work"), "--specpath", str(CIKTI / "work"),
            "--collect-all", "asistan", *sum((["--add-data", v] for v in veri), []), str(PROJE / "main.py")]
    if tek_dosya:
        argv.insert(1, "--onefile")
    simge = PROJE / "asistan" / "gui" / "assets" / ("icon.ico" if sistem() == "windows" else "icon.png")
    if simge.exists():
        argv[1:1] = ["--icon", str(simge)]
    subprocess.run(argv, check=True, cwd=PROJE)
    return CIKTI / "build"


def sar(build: Path, urun: str) -> Path:
    """Platform kabı: Windows → onefile .exe zaten; macOS → hdiutil .dmg; Linux → appimagetool (yoksa .tar.gz)."""
    CIKTI.mkdir(parents=True, exist_ok=True)
    hedef = CIKTI / urun
    s = sistem()
    if s == "windows":
        shutil.copy2(build / f"{AD}.exe", hedef)
    elif s == "macos":
        app = build / f"{AD}.app"
        subprocess.run(["hdiutil", "create", "-volname", AD, "-srcfolder", str(app), "-ov", "-format", "UDZO", str(hedef)],
                       check=True)
    else:
        appdir = CIKTI / "AppDir"
        shutil.rmtree(appdir, ignore_errors=True)
        (appdir / "usr" / "bin").mkdir(parents=True)
        kaynak = build / AD
        if kaynak.is_dir():
            shutil.copytree(kaynak, appdir / "usr" / "bin" / AD)
            (appdir / "AppRun").write_text(f'#!/bin/sh\nHERE="$(dirname "$(readlink -f "$0")")"\nexec "$HERE/usr/bin/{AD}/{AD}" "$@"\n')
        else:
            shutil.copy2(kaynak, appdir / "usr" / "bin" / AD)
            (appdir / "AppRun").write_text(f'#!/bin/sh\nHERE="$(dirname "$(readlink -f "$0")")"\nexec "$HERE/usr/bin/{AD}" "$@"\n')
        os.chmod(appdir / "AppRun", 0o755)
        (appdir / f"{AD}.desktop").write_text(f"[Desktop Entry]\nType=Application\nName=YENİ NESİL CAFER\nExec={AD}\n"
                                              f"Icon={AD}\nCategories=Utility;\nTerminal=false\n")
        simge = PROJE / "asistan" / "gui" / "assets" / "icon.png"
        if simge.exists():
            shutil.copy2(simge, appdir / f"{AD}.png")
        if shutil.which("appimagetool"):
            subprocess.run(["appimagetool", str(appdir), str(hedef)], check=True, env={**os.environ, "ARCH": "x86_64"})
        else:
            hedef = hedef.with_suffix(".tar.gz")
            subprocess.run(["tar", "czf", str(hedef), "-C", str(CIKTI), "AppDir"], check=True)
            print("appimagetool yok: AppImage yerine tar.gz üretildi")
    sha_yaz(hedef)
    return hedef


def guncelleme_paketi() -> Path:
    from asistan import updates

    dest, _ = updates.build_package(PROJE, CIKTI)
    return dest


def tam(build: Path, butce_gb: float) -> None:
    """Full: Light çıktısının yanına gömülü Ollama + model (bootstrap ile indirilir; SHA doğrulanır)."""
    from asistan import bootstrap

    model = model_sec(butce_gb)
    uyg = build / AD if (build / AD).is_dir() else build
    bootstrap.ollama(uyg)
    if model:
        subprocess.run(["ollama", "pull", model], check=True)
        # paketleme/paketle.py gomulu_model ile aynı yol: blob + Modelfile program/modeller/ (ad çakışmasın: dosyadan yükle)
        import importlib.util

        spec = importlib.util.spec_from_file_location("paketleme_paketle", PROJE / "paketleme" / "paketle.py")
        eski = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(eski)
        for src, rel in eski.gomulu_model():
            hedef = uyg / Path(*rel.parts[1:])
            hedef.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, hedef)
    else:
        print("bütçeye sığan model yok: Full modelsiz (ilk açılış modeli indirir)")


def eski_surumleri_sil(kalan: str = "", calistir=subprocess.run) -> list[str]:
    """`--eski-sil`: Latest olan sürüm (ya da `kalan` etiketi) dışındaki YAYINLANMIŞ sürümleri etiketleriyle birlikte
    siler (`gh release delete <etiket> --cleanup-tag --yes`). Taslaklar dokunulmaz. Yeni sürüm Latest olduktan sonra
    çağrılır (`gh release edit vX --latest`); Latest yoksa hiçbir şey silinmez. Silinen etiketlerin listesi döner."""
    r = calistir(["gh", "release", "list", "--json", "tagName,isLatest,isDraft", "--limit", "100"],
                 capture_output=True, text=True)
    if r.returncode != 0:
        raise RuntimeError(f"gh release list başarısız: {(r.stderr or r.stdout or '').strip()[:300]}")
    liste = json.loads(r.stdout or "[]")
    kalan = kalan or next((s["tagName"] for s in liste if s.get("isLatest")), "")
    if not kalan:
        raise RuntimeError("Latest sürüm yok: önce yeni sürümü yayınla (gh release edit <etiket> --latest)")
    if kalan not in {s["tagName"] for s in liste}:
        raise RuntimeError(f"{kalan} sürüm listesinde yok; yanlışlıkla her şey silinmesin diye durduruldu")
    silinen = []
    for s in liste:
        if s["tagName"] == kalan or s.get("isDraft"):
            continue
        calistir(["gh", "release", "delete", s["tagName"], "--cleanup-tag", "--yes"], check=True)
        silinen.append(s["tagName"])
    return silinen


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Dağıtım paketleri (K11)")
    ap.add_argument("--hafif", action="store_true", help="Light: program + bağımlılıklar (PyInstaller)")
    ap.add_argument("--tam", action="store_true", help="Full: Light + Ollama + bütçeye sığan model")
    ap.add_argument("--guncelleme", action="store_true", help="uygulama içi güncelleme paketi (updates.ASSET)")
    ap.add_argument("--kuru", action="store_true", help="yalnızca plan (JSON), üretim yok")
    ap.add_argument("--butce-gb", type=float, default=BUTCE_GB)
    ap.add_argument("--tek-dosya", action="store_true", help="PyInstaller --onefile (Windows .exe için)")
    ap.add_argument("--eski-sil", action="store_true", help="Latest dışındaki yayınlanmış GitHub sürümlerini etiketleriyle sil (gh)")
    ap.add_argument("--kalan", default="", help="--eski-sil: korunacak etiket (boş: Latest olan)")
    a = ap.parse_args(argv)
    tur = "tam" if a.tam else "hafif"
    if a.eski_sil:
        silinen = eski_surumleri_sil(a.kalan)
        print("silinen: " + (", ".join(silinen) or "yok"))
        return 0
    if a.kuru or not (a.hafif or a.tam or a.guncelleme):
        print(json.dumps(plan(tur, a.butce_gb), ensure_ascii=False, indent=1))
        return 0
    if a.guncelleme:
        p = guncelleme_paketi()
        print(f"{p} ({p.stat().st_size / 1e6:.1f} MB) + .sha256")
    if a.hafif or a.tam:
        build = pyinstaller(a.tek_dosya or sistem() == "windows")
        if a.tam:
            tam(build, a.butce_gb)
        urun = sar(build, plan(tur, a.butce_gb)["urun"])
        print(f"{urun} ({urun.stat().st_size / 1e6:.0f} MB) + .sha256")
    return 0


if __name__ == "__main__":
    sys.exit(main())
