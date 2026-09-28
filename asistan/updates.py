"""Güncellemeler: GitHub'da yayımlanan resmi sürümü indirip kurar (programın kendisi kod yazmaz; kullanıcının
yayımladığı sürümü alır). Büyük kurulum paketi (Python, Ollama, modeller) bir kez indirilir; sonraki sürümler
yalnızca birkaç MB'lık kod paketidir: `yeni-nesil-cafer-guncelleme-<sürüm>.zip` (içinde `asistan/` ve `main.py`).

Güvenlik: yalnızca GitHub (https), paketin SHA-256 özeti sürümdeki `digest` ile ya da `.sha256` dosyasıyla doğrulanır,
ZIP'te yalnızca `asistan/…` ve `main.py` kabul edilir (yol kaçışı yok). Kurmadan önce eski sürüm yedeklenir;
yeni sürüm açılışını onaylayamazsa (çöker) bir sonraki başlatmada `main.rollback_if_needed` eski sürümü
geri yükler (asistan paketi içe aktarılmadan: yeni kod bozuksa da çalışsın).
Geliştirme klasöründe (git deposu) güncelleyici çalışmaz: kaynak kodun üzerine yazılmasın.
"""

import hashlib
import json
import re
import shutil
import sys
import tempfile
import time
import zipfile
from pathlib import Path

import httpx

from . import GITHUB_REPO, __version__
from .config import DATA_DIR

PROGRAM_DIR = Path(__file__).resolve().parent.parent
STATE_FILE = DATA_DIR / "guncelleme-durum.json"  # kurulan sürüm onaylanana kadar (geri dönüş için)
BACKUP_DIR = DATA_DIR / "guncelleme-yedek"
ASSET = "guncelleyici-icin-yeni-nesil-cafer-guncelleme-{version}.zip"  # sürüm sayfasında insan için değil (öneki)
CHECK_EVERY = 24 * 3600  # otomatik denetim sıklığı


class UpdateError(Exception):
    pass


def version_tuple(v: str) -> tuple:
    return tuple(int(x) for x in re.findall(r"\d+", v)[:3]) or (0,)


def enabled() -> tuple[bool, str]:
    """(açık mı, neden değil). Geliştirme klasöründe ve yazılamayan kurulumda kapalı."""
    if not GITHUB_REPO:
        return False, "Güncelleme deposu tanımlı değil."
    if getattr(sys, "frozen", False):  # K12-E3: PyInstaller tek dosya — geçici klasöre "güncelleme" sahte döngü yaratıyordu
        return False, "Tek dosya (PyInstaller) kurulum: uygulama içi güncelleme yok; yeni sürümü indirme sayfasından al."
    if (PROGRAM_DIR / ".git").exists():
        return False, "Geliştirme klasöründen çalışıyor (git deposu): güncellemeler git ile alınır."
    try:
        probe = PROGRAM_DIR / ".yazma-denemesi"
        probe.write_text("")
        probe.unlink()
    except OSError:
        return False, f"Program klasörüne yazılamıyor: {PROGRAM_DIR}"
    return True, ""


def latest(timeout: float = 15) -> dict | None:
    """GitHub'daki son sürüm: {version, notes, url, size, digest, sha_url, page}; kod paketi yoksa None."""
    r = httpx.get(f"https://api.github.com/repos/{GITHUB_REPO}/releases/latest", timeout=timeout,
                  headers={"Accept": "application/vnd.github+json"}, follow_redirects=True)
    if r.status_code == 404:
        return None
    r.raise_for_status()
    data = r.json()
    version = str(data.get("tag_name", "")).lstrip("vV")
    assets = {a["name"]: a for a in data.get("assets", [])}
    pack = assets.get(ASSET.format(version=version))
    if not version or pack is None:
        return None
    sha = assets.get(ASSET.format(version=version) + ".sha256")
    return {"version": version, "notes": data.get("body") or "", "url": pack["browser_download_url"],
            "size": pack.get("size", 0), "digest": str(pack.get("digest") or ""),
            "sha_url": sha["browser_download_url"] if sha else "", "page": data.get("html_url", "")}


def atlanan_surum() -> str:
    """K12-E4: geri alınan (açılamayan) sürüm; bir daha önerilmez (`main.rollback_if_needed` yazar)."""
    try:
        return str(json.loads(STATE_FILE.with_name("guncelleme-atla.json").read_text(encoding="utf-8")).get("version") or "")
    except (OSError, ValueError, AttributeError):
        return ""


def newer(info: dict | None) -> bool:
    return (bool(info) and version_tuple(info["version"]) > version_tuple(__version__)
            and str(info["version"]) != atlanan_surum())


def _expected_sha(info: dict) -> str:
    if info["digest"].startswith("sha256:"):
        return info["digest"].split(":", 1)[1].lower()
    if info["sha_url"]:
        text = httpx.get(info["sha_url"], timeout=30, follow_redirects=True).text
        found = re.search(r"\b[0-9a-f]{64}\b", text.lower())
        if found:
            return found.group(0)
    raise UpdateError("Güncelleme paketinin özeti (SHA-256) bulunamadı; güvenlik için kurulmadı.")


def download(info: dict, progress=None, cancelled=lambda: False) -> Path:
    if not info["url"].startswith("https://github.com/"):
        raise UpdateError("Güncelleme yalnızca GitHub'dan indirilir.")
    dest = Path(tempfile.mkdtemp(prefix="yeni-nesil-cafer-guncelleme-")) / ASSET.format(version=info["version"])
    digest = hashlib.sha256()
    with httpx.stream("GET", info["url"], follow_redirects=True, timeout=httpx.Timeout(300, connect=20)) as r:
        if r.status_code != 200:
            raise UpdateError(f"İndirilemedi (HTTP {r.status_code}).")
        total, have = int(r.headers.get("content-length") or info["size"] or 0), 0
        with dest.open("wb") as f:
            for chunk in r.iter_bytes(1 << 16):
                if cancelled():
                    raise InterruptedError("güncelleme durduruldu")
                f.write(chunk)
                digest.update(chunk)
                have += len(chunk)
                if progress and total:
                    progress(int(have * 100 / total))
    if digest.hexdigest() != _expected_sha(info):
        dest.unlink(missing_ok=True)
        raise UpdateError("İndirilen paket bozuk ya da değiştirilmiş (SHA-256 tutmuyor); kurulmadı.")
    return dest


def _members(z: zipfile.ZipFile) -> list[zipfile.ZipInfo]:
    """Yalnızca asistan/… ve main.py; yol kaçışı (../, mutlak yol) olan paket reddedilir."""
    ok = []
    for m in z.infolist():
        name = m.filename.replace("\\", "/")
        if name.startswith("/") or ".." in Path(name).parts or re.match(r"^[A-Za-z]:", name):
            raise UpdateError(f"Pakette geçersiz yol: {m.filename}")
        if name == "main.py" or name.startswith("asistan/"):
            ok.append(m)
    if not any(m.filename == "asistan/__init__.py" for m in ok) or not any(m.filename == "main.py" for m in ok):
        raise UpdateError("Paket eksik (asistan/__init__.py ya da main.py yok).")
    return ok


def _gecici_temizle(package: Path) -> None:
    """`download`'ın açtığı geçici klasörü siler (yalnızca kendi önekimizle; başka yola dokunulmaz)."""
    if package.parent.name.startswith("yeni-nesil-cafer-guncelleme-"):
        shutil.rmtree(package.parent, ignore_errors=True)


def apply(package: Path, version: str) -> Path:
    """Paketi kurar: eski sürüm yedeklenir, yeni kod yerine konur; yedeğin yolu döner."""
    stage = Path(tempfile.mkdtemp(prefix="yeni-nesil-cafer-kur-"))
    with zipfile.ZipFile(package) as z:
        for m in _members(z):
            z.extract(m, stage)
    got = re.search(r'__version__ = "([^"]+)"', (stage / "asistan/__init__.py").read_text(encoding="utf-8"))
    if not got or got.group(1) != version:
        raise UpdateError("Paketin içindeki sürüm beklenenden farklı; kurulmadı.")
    backup = BACKUP_DIR / __version__
    shutil.rmtree(backup, ignore_errors=True)
    backup.mkdir(parents=True)
    shutil.copytree(PROGRAM_DIR / "asistan", backup / "asistan", ignore=shutil.ignore_patterns("__pycache__"))
    shutil.copy2(PROGRAM_DIR / "main.py", backup / "main.py")
    old = PROGRAM_DIR / "asistan.eski"
    shutil.rmtree(old, ignore_errors=True)
    (PROGRAM_DIR / "asistan").rename(old)  # yeni kod eksiksiz gelsin (silinen modüller eski sürümden kalmasın)
    try:
        shutil.copytree(stage / "asistan", PROGRAM_DIR / "asistan")
        shutil.copy2(stage / "main.py", PROGRAM_DIR / "main.py")
    except Exception:
        shutil.rmtree(PROGRAM_DIR / "asistan", ignore_errors=True)
        old.rename(PROGRAM_DIR / "asistan")
        shutil.copy2(backup / "main.py", PROGRAM_DIR / "main.py")
        raise
    shutil.rmtree(old, ignore_errors=True)
    shutil.rmtree(stage, ignore_errors=True)
    _gecici_temizle(package)  # K12-F2: indirilen paket ve geçici klasörü
    from .cekirdek.ayar import atomik_yaz

    atomik_yaz(STATE_FILE, json.dumps({"from": __version__, "to": version, "backup": str(backup), "tries": 0,
                                       "time": time.time()}))  # K12-C1: yarım durum dosyası = geri alma kararı bozulur
    return backup


def confirm() -> str:
    """Yeni sürüm sorunsuz açıldı: geri dönüş kaydı silinir. Yeni kurulduysa kullanıcıya not döner."""
    try:
        state = json.loads(STATE_FILE.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return ""
    STATE_FILE.unlink(missing_ok=True)
    return f"YENİ NESİL CAFER {state.get('to')} sürümüne güncellendi."


def build_package(source_dir: Path, out_dir: Path) -> tuple[Path, str]:
    """Yayın için kod paketi (dagitim/paketle.py --guncelleme, CI): (zip yolu, sha256)."""
    got = re.search(r'__version__ = "([^"]+)"', (source_dir / "asistan/__init__.py").read_text(encoding="utf-8"))
    version = got.group(1)
    out_dir.mkdir(parents=True, exist_ok=True)
    dest = out_dir / ASSET.format(version=version)
    with zipfile.ZipFile(dest, "w", zipfile.ZIP_DEFLATED) as z:
        z.write(source_dir / "main.py", "main.py")
        for f in sorted((source_dir / "asistan").rglob("*")):
            if f.is_file() and "__pycache__" not in f.parts and f.suffix != ".pyc":
                z.write(f, f.relative_to(source_dir).as_posix())
    sha = hashlib.sha256(dest.read_bytes()).hexdigest()
    (out_dir / (dest.name + ".sha256")).write_text(f"{sha}  {dest.name}\n", encoding="utf-8")
    return dest, sha
