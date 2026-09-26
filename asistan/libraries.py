"""Kod kütüphaneleri: programın kendi Python kütüphaneleri, ajanlar için pakete gömülü hazır set ve sonradan
kurulanlar (ajanın kütüphane klasöründe). Sol paneldeki "kütüphaneler" sekmesi bunları listeler, kurar, kaldırır."""

import importlib.metadata as md
import re
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path

from .tools import BUNDLED_LIBS, NO_WINDOW, USER_LIBS, python_exe

PROJECT = Path(__file__).resolve().parent.parent
# kısa Türkçe açıklamalar (listede adın yanında görünür)
NOTES = {
    "pandas": "tablo ve veri analizi", "numpy": "sayısal hesap", "matplotlib": "grafik çizimi",
    "openpyxl": "Excel dosyaları", "python-docx": "Word dosyaları", "python-pptx": "PowerPoint dosyaları",
    "pypdf": "PDF okuma", "reportlab": "PDF oluşturma", "pillow": "resim işleme", "requests": "web istekleri",
    "pyyaml": "YAML dosyaları", "pyside6": "pencere ve arayüz", "anthropic": "Claude bağlantısı",
    "httpx": "web istekleri", "ddgs": "web araması", "beautifulsoup4": "web sayfası okuma",
    "keyring": "anahtarları güvenli saklama", "psutil": "sistem bilgisi (CPU, RAM)",
}


@dataclass
class Library:
    name: str
    version: str
    group: str  # "program" · "hazir" · "kurulan"
    note: str = ""

    @property
    def removable(self) -> bool:
        return self.group == "kurulan"


def _key(name: str) -> str:
    return re.split(r"[\[=<>!~ ;]", name.strip(), maxsplit=1)[0].lower().replace("_", "-")


def _wanted(path: Path) -> list[str]:
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return []
    return [_key(ln) for ln in lines if ln.strip() and not ln.lstrip().startswith("#")]


def _dists(paths: list[str]) -> dict[str, md.Distribution]:
    found = {}
    for d in md.distributions(path=paths):
        name = d.metadata["Name"] or ""
        if name:
            found.setdefault(_key(name), d)
    return found


def list_libraries() -> list[Library]:
    """Üç grup: programın kullandıkları, ajanlara hazır gelenler, ajanların ya da kullanıcının sonradan kurdukları."""
    import sys

    everywhere = _dists([str(USER_LIBS), str(BUNDLED_LIBS), *sys.path])
    result = []
    for name in _wanted(PROJECT / "requirements.txt"):
        d = everywhere.get(name)
        result.append(Library(d.metadata["Name"] if d else name, d.version if d else "kurulu değil", "program",
                              NOTES.get(name, "")))
    ready = _wanted(PROJECT / "paketleme" / "ajan-kutuphaneleri.txt") or \
        [_key(n) for n in "pandas numpy matplotlib openpyxl python-docx python-pptx pypdf reportlab pillow requests pyyaml".split()]
    for name in ready:
        d = everywhere.get(name)
        result.append(Library(d.metadata["Name"] if d else name, d.version if d else "kurulu değil", "hazir",
                              NOTES.get(name, "")))
    shown = {_key(x.name) for x in result}
    for key, d in sorted(_dists([str(USER_LIBS)]).items()) if USER_LIBS.exists() else []:
        if key not in shown:
            result.append(Library(d.metadata["Name"], d.version, "kurulan", NOTES.get(key, "")))
    return result


def install(packages: str) -> str:
    """pip ile ajanın kütüphane klasörüne kurar (programın kendi kütüphanelerine dokunmaz). İnternet gerekir."""
    names = [p for p in packages.replace(",", " ").split() if p]
    if not names or any(not re.fullmatch(r"[A-Za-z0-9._\-\[\]=<>!~]+", p) for p in names):
        raise ValueError("Yalnızca kütüphane adları yazılmalı (ör. pandas openpyxl).")
    USER_LIBS.mkdir(parents=True, exist_ok=True)
    out = subprocess.run([python_exe(), "-m", "pip", "install", "--disable-pip-version-check", "--target",
                          str(USER_LIBS), "--upgrade", *names], capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=900,
                         creationflags=NO_WINDOW)
    if out.returncode != 0:
        lines = [ln for ln in (out.stderr or out.stdout).splitlines() if ln.strip()]
        raise RuntimeError("\n".join(lines[-6:]) or "kurulum başarısız")
    return ", ".join(names)


def remove(name: str) -> None:
    """Sonradan kurulan bir kütüphaneyi ajanın klasöründen siler (pip --target kaldırmayı bilmez)."""
    d = _dists([str(USER_LIBS)]).get(_key(name))
    if d is None:
        raise ValueError(f"{name} sonradan kurulanlar arasında yok.")
    root = USER_LIBS.resolve()
    for f in d.files or []:
        path = Path(d.locate_file(f)).resolve()
        if root in path.parents and path.is_file():
            path.unlink(missing_ok=True)
    info = Path(d._path).resolve()  # .dist-info klasörü
    if root in info.parents:
        shutil.rmtree(info, ignore_errors=True)
    for folder in sorted((p for p in root.rglob("*") if p.is_dir()), key=lambda p: -len(p.parts)):
        try:
            folder.rmdir()  # boş kalan paket klasörleri
        except OSError:
            pass
