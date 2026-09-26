"""install_app: masaüstü uygulamasını yönetici (sudo) izni olmadan, yalnızca bu kullanıcıya kurar.

- Linux: Flatpak varsa `flatpak install --user` (Flathub); yoksa AppImage: GitHub sürüm sayfasından ya da
  doğrudan https adresinden `~/Applications/<ad>.AppImage` olarak indirilir, çalıştırılabilir yapılır ve uygulama
  menüsüne (.desktop) eklenir. AppImage her dağıtımda çalışır (FUSE yoksa `--appimage-extract-and-run` ile).
- Windows: `winget install --scope user`. macOS: `brew install --cask`.
Risk sınıfı "kurar": her kurulumu güvenlik ajanı ya da kullanıcı onaylar (security.classify: orta risk, adres görünür).
"""

import json
import os
import platform
import re
import shutil
import stat
import subprocess
import sys
import urllib.parse
from pathlib import Path

import httpx

APPS_DIR = Path.home() / "Applications"
DESKTOP_DIR = Path(os.environ.get("XDG_DATA_HOME", Path.home() / ".local/share")) / "applications"
TIMEOUT = 1800  # büyük uygulamalar (dilimleyici, Blender) yavaş bağlantıda uzun sürer
NO_WINDOW = subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0
_ARCH = ("x86_64", "amd64", "x64") if platform.machine() in ("x86_64", "AMD64") else ("aarch64", "arm64")


# bilinen yayıncılar (resmi kaynaklar): buradan kurulum orta risk; başka her kaynak yüksek risk (security.classify)
KNOWN_GITHUB = {  # sahip/depo (küçük harf)
    "softfever/orcaslicer", "prusa3d/prusaslicer", "ultimaker/cura", "bambulab/bambustudio", "freecad/freecad",
    "openscad/openscad", "audacity/audacity", "mltframework/shotcut", "obsproject/obs-studio", "krita-org/krita",
    "musescore/musescore", "keepassxreboot/keepassxc", "subsurface/subsurface", "appimage/appimagetool",
    "kicad/kicad-source-mirror", "librecad/librecad", "darktable-org/darktable", "gimp/gimp",
}
KNOWN_DOMAINS = {"download.kde.org", "files.openscad.org", "inkscape.org", "download.blender.org",
                 "download.documentfoundation.org", "www.freecad.org"}


class AppError(Exception):
    pass


def trusted(source: str) -> bool:
    """Kaynak bilinen bir yayıncının resmi yeri mi? Paket yöneticisinden (Flathub / winget / brew) ada göre kurulum
    da bilinen sayılır: oradaki paketler zaten denetlenir."""
    source = (source or "").strip()
    if not source:
        return True
    repo = re.sub(r"^https?://github\.com/", "", source).strip("/").lower()
    if re.fullmatch(r"[\w.-]+/[\w.-]+", repo):
        return repo in KNOWN_GITHUB
    if source.startswith("https://"):
        host = urllib.parse.urlparse(source).netloc.lower()
        if host == "github.com":  # doğrudan sürüm dosyası: depo sahibi de bilinen olmalı
            parts = urllib.parse.urlparse(source).path.strip("/").lower().split("/")
            return "/".join(parts[:2]) in KNOWN_GITHUB
        return host in KNOWN_DOMAINS
    return bool(re.fullmatch(r"[\w.+-]+", source))  # Flatpak / winget kimliği ya da Homebrew cask adı


def slug(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")[:40] or "uygulama"


def github_appimage(repo: str) -> tuple[str, str]:
    """GitHub deposunun son sürümündeki bu mimariye uygun AppImage: (indirme adresi, dosya adı)."""
    repo = re.sub(r"^https?://github\.com/", "", repo.strip()).strip("/")
    if not re.fullmatch(r"[\w.-]+/[\w.-]+", repo):
        raise AppError("GitHub source must look like owner/repo, e.g. SoftFever/OrcaSlicer")
    r = httpx.get(f"https://api.github.com/repos/{repo}/releases", timeout=30,
                  headers={"Accept": "application/vnd.github+json"}, follow_redirects=True)
    if r.status_code != 200:
        raise AppError(f"GitHub releases of {repo} could not be read (HTTP {r.status_code})")
    for release in r.json():
        if release.get("draft"):
            continue
        assets = [a for a in release.get("assets", []) if a["name"].lower().endswith(".appimage")]
        # bu mimari; birden çoksa adında "arm/aarch" olmayan ve en kısa olan (genelde ana paket)
        fitting = [a for a in assets if any(x in a["name"].lower() for x in _ARCH)] or \
            [a for a in assets if not re.search(r"arm|aarch", a["name"], re.I)]
        if fitting:
            best = min(fitting, key=lambda a: len(a["name"]))
            return best["browser_download_url"], best["name"]
    raise AppError(f"No AppImage for this computer in the releases of {repo}; look for another source")


def _download(url: str, dest: Path, progress=None, cancelled=lambda: False) -> None:
    part = dest.with_suffix(dest.suffix + ".part")
    with httpx.stream("GET", url, follow_redirects=True, timeout=httpx.Timeout(TIMEOUT, connect=20)) as r:
        if r.status_code != 200:
            raise AppError(f"download failed (HTTP {r.status_code})")
        total, have = int(r.headers.get("content-length") or 0), 0
        with part.open("wb") as f:
            for chunk in r.iter_bytes(1 << 20):
                if cancelled():
                    part.unlink(missing_ok=True)
                    raise InterruptedError("uygulama kurulumu durduruldu")
                f.write(chunk)
                have += len(chunk)
                if progress and total:
                    progress(int(have * 100 / total), f"{have / 1e6:.0f}/{total / 1e6:.0f} MB")
    with part.open("rb") as f:
        head = f.read(4)
    if head[:4] != b"\x7fELF":  # AppImage bir ELF dosyasıdır: HTML hata sayfası kurulmasın
        part.unlink(missing_ok=True)
        raise AppError("the downloaded file is not an AppImage (maybe a web page); check the address")
    part.replace(dest)


def _runs(path: Path) -> bool:
    """AppImage bu sistemde açılabiliyor mu (FUSE)? Açılamıyorsa çıkarıp çalıştırma ile denenir."""
    try:
        out = subprocess.run([str(path), "--appimage-version"], capture_output=True, timeout=30)
        return out.returncode == 0
    except (OSError, subprocess.TimeoutExpired):
        return False


def install_appimage(name: str, url: str, progress=None, cancelled=lambda: False) -> str:
    if not url.startswith("https://"):
        raise AppError("only https addresses are allowed")
    APPS_DIR.mkdir(parents=True, exist_ok=True)
    dest = APPS_DIR / f"{slug(name)}.AppImage"
    _download(url, dest, progress, cancelled)
    dest.chmod(dest.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
    launch = f'"{dest}"' if _runs(dest) else f'"{dest}" --appimage-extract-and-run'  # FUSE yoksa
    DESKTOP_DIR.mkdir(parents=True, exist_ok=True)
    (DESKTOP_DIR / f"{slug(name)}.desktop").write_text(
        f"[Desktop Entry]\nType=Application\nName={name}\nExec={launch} %F\nTerminal=false\n"
        f"Categories=Utility;\nComment=YENİ NESİL CAFER kurdu ({urllib.parse.urlparse(url).netloc})\n",
        encoding="utf-8")
    size = dest.stat().st_size / 1e6
    return (f"Installed {name} ({size:.0f} MB) as {dest}; it is in the application menu. Start it with open_app "
            f"'{name}' or run: {launch}")


def install(name: str, source: str = "", progress=None, cancelled=lambda: False) -> str:
    """source: Linux'ta GitHub "sahip/depo" ya da https AppImage adresi ya da Flatpak kimliği; Windows'ta winget
    kimliği; macOS'ta Homebrew cask adı. Boşsa paket yöneticisinde adla aranır (Flatpak / winget / brew)."""
    name, source = name.strip(), source.strip()
    if not name:
        raise AppError("name is required")
    if sys.platform == "win32":
        ident = source or name
        cmd = ["winget", "install", "--id" if "." in ident else "--name", ident, "--scope", "user", "--silent",
               "--accept-package-agreements", "--accept-source-agreements"]
    elif sys.platform == "darwin":
        cmd = ["brew", "install", "--cask", source or slug(name)]
    elif source.lower().endswith(".appimage") or (source.startswith("https://")
                                                   and not source.startswith("https://github.com/")):
        return install_appimage(name, source, progress, cancelled)
    elif re.fullmatch(r"(https://github\.com/)?[\w.-]+/[\w.-]+/?", source):
        url, _file = github_appimage(source)
        return install_appimage(name, url, progress, cancelled)
    elif shutil.which("flatpak"):
        subprocess.run(["flatpak", "remote-add", "--user", "--if-not-exists", "flathub",
                        "https://dl.flathub.org/repo/flathub.flatpakrepo"], capture_output=True, timeout=120)
        cmd = ["flatpak", "install", "--user", "-y", "--noninteractive", "flathub", source or name]
    else:
        raise AppError("Flatpak is not installed and no AppImage source was given: find the app's official "
                       "AppImage (its GitHub releases page or website) and call install_app again with "
                       "source='owner/repo' or the https address of the .AppImage")
    try:
        out = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=TIMEOUT, creationflags=NO_WINDOW)
    except FileNotFoundError:
        raise AppError(f"{cmd[0]} is not available on this computer")
    if out.returncode != 0:
        lines = [ln for ln in (out.stderr or out.stdout).splitlines() if ln.strip()]
        raise AppError("install failed: " + " | ".join(lines[-3:]))
    return f"Installed {name} with {cmd[0]}. Start it with open_app '{name}'."


def describe(args: dict) -> str:
    """Onay ve güvenlik denetimi için kurulumun kaynağı (düz metin)."""
    return json.dumps({"app": args.get("name"), "source": args.get("source") or "package manager search"},
                      ensure_ascii=False)
