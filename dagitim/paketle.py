#!/usr/bin/env python3
"""Dağıtım paketleri (K11): Light (~200 MB: program + Python bağımlılıkları, model yok) ve Full (Light + gömülü
Ollama motoru + bütçeye sığan varsayılan yerel model; kurulur kurulmaz çevrimdışı). Windows `.exe`, macOS `.dmg`,
Linux `.AppImage` — her biri kendi platformunda derlenir (GitHub Actions `dagitim.yml`, üç platform).

    python dagitim/paketle.py --hafif            # bu platform için Light (PyInstaller)
    python dagitim/paketle.py --tam [--butce-gb 1.9]   # Full: Light + Ollama + bütçeye sığan model
    python dagitim/paketle.py --guncelleme       # uygulama içi güncelleme paketi (updates.ASSET, sha256)
    python dagitim/paketle.py --kuru [...]       # hiçbir şey üretmeden plan (dosyalar, boyutlar) → JSON
    python dagitim/paketle.py --eski-sil         # yeni sürüm Latest olduktan sonra: eski sürümleri etiketleriyle sil (gh)
    python dagitim/paketle.py --surum-notu       # GitHub sürüm notu (dagitim/RELEASE_NOTU.md şablonu) → stdout

Ürün adları (platform başına tek dosya, "Light" yok): YeniNesilCafer-<sürüm>-Linux.AppImage (`--install` ile masaüstüne
kısayol), YeniNesilCafer-<sürüm>-Windows-Kurulum.exe, YeniNesilCafer-<sürüm>-macOS.dmg. Güncelleyici paketi
`guncelleyici-icin-…zip` (+ .sha256): sürüm sayfasında insan için değil.

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
         "urun": urun_adi(sistem(), tur)}
    if tur == "tam":
        p["model"] = model_sec(butce_gb)
        p["ollama"] = ollama_paketi()
        if not p["model"]:
            p["not"] = "bütçeye sığan model yok: Full modelsiz çıkar, ilk açılış modeli indirir"
    return p


def urun_adi(s: str, tur: str = "hafif", v: str = "") -> str:
    """Platform başına tek kurulum dosyası; ad ne yapacağını söyler ("Light" yok: Full GitHub'a girmez, ayrım anlamsız).
    Full yalnızca elle üretilir ve `-Full-` ekiyle ayrılır."""
    v = v or surum()
    ad = {"windows": f"{AD}-{v}-Windows-Kurulum.exe", "macos": f"{AD}-{v}-macOS.dmg", "linux": f"{AD}-{v}-Linux.AppImage"}[s]
    return ad.replace(f"-{v}-", f"-{v}-Full-") if tur == "tam" else ad


def surum_notu(v: str = "", sablon: Path | None = None) -> str:
    """GitHub sürüm notu (`dagitim/RELEASE_NOTU.md` şablonu): en başta "Hangisini indireyim?" tablosu, sonra CHANGELOG'un
    ilk bölümü, "Gelişmiş" altında internet paketleri ve BENIOKU. `--surum-notu` ile CI yazar (dosya olarak yüklenmez)."""
    import re

    from asistan import SURUM_ADI, updates

    v = v or surum()
    sablon = sablon or (PROJE / "dagitim" / "RELEASE_NOTU.md")
    m = (PROJE / "CHANGELOG.md").read_text(encoding="utf-8")
    b = re.split(r"^## ", m, flags=re.M)
    degisiklikler = "\n".join(b[1].splitlines()[1:]).strip() if len(b) > 1 else ""
    internet = "\n".join(f"- `{SURUM_ADI}-{s}-internet.{u}`" for s, u in (("Windows", "zip"), ("Linux", "tar.gz"), ("macOS", "zip")))
    benioku_yolu = PROJE / "dagitim" / "BENIOKU.txt"
    benioku = ""
    if benioku_yolu.exists():
        metin = benioku_yolu.read_text(encoding="utf-8").replace("@PAKET@", SURUM_ADI).replace("@SURUM@", v)
        benioku = "**BENIOKU (internet paketleri):**\n\n```text\n" + metin.strip() + "\n```"
    return sablon.read_text(encoding="utf-8").format(
        surum=v, linux=urun_adi("linux", v=v), windows=urun_adi("windows", v=v), macos=urun_adi("macos", v=v),
        guncelleme=updates.ASSET.format(version=v), degisiklikler=degisiklikler, internet=internet, benioku=benioku)


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


def apprun_metni(exe: str) -> str:
    """AppImage giriş betiği: `--install` / `--uninstall` gömülü kur.sh'a gider (AppImage'ın kendi yolu $APPIMAGE), diğer
    her şey programa."""
    return (
        '#!/bin/sh\nHERE="$(dirname "$(readlink -f "$0")")"\n'
        'case "${1:-}" in\n'
        f'  --install) exec "$HERE/kur.sh" "${{APPIMAGE:-$HERE/AppRun}}" "$HERE/{AD}.png" ;;\n'
        f'  --uninstall) exec "$HERE/kur.sh" "${{APPIMAGE:-$HERE/AppRun}}" "$HERE/{AD}.png" --uninstall ;;\n'
        'esac\n'
        f'exec "$HERE/{exe}" "$@"\n'
    )


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
        exe = f"usr/bin/{AD}/{AD}" if kaynak.is_dir() else f"usr/bin/{AD}"
        if kaynak.is_dir():
            shutil.copytree(kaynak, appdir / "usr" / "bin" / AD)
        else:
            shutil.copy2(kaynak, appdir / "usr" / "bin" / AD)
        shutil.copy2(PROJE / "dagitim" / "linux" / "kur.sh", appdir / "kur.sh")  # --install / --uninstall: masaüstü kısayolu
        os.chmod(appdir / "kur.sh", 0o755)
        (appdir / "AppRun").write_text(apprun_metni(exe))
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
        # eski tam paketleyicinin (NOTLAR/arsiv/paketleme) gomulu_model yolu: blob + Modelfile program/modeller/ (ad çakışmasın: dosyadan yükle)
        import importlib.util

        spec = importlib.util.spec_from_file_location("paketleme_paketle", PROJE / "NOTLAR" / "arsiv" / "paketleme" / "paketle.py")
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
    ap.add_argument("--surum-notu", action="store_true", help="GitHub sürüm notunu şablondan yaz (dagitim/RELEASE_NOTU.md) → stdout")
    ap.add_argument("--kalan", default="", help="--eski-sil: korunacak etiket (boş: Latest olan)")
    a = ap.parse_args(argv)
    tur = "tam" if a.tam else "hafif"
    if a.surum_notu:
        sys.stdout.write(surum_notu())
        return 0
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
