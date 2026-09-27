"""Sonuçlar: işlerin ürettiği görseller, 3D modeller, belgeler, kodlar, ses ve videolar masaüstünde tek klasörde toplanır.

Kullanıcı masaüstünün dağılmasını da, sonuçları çalışma klasöründe (iş klasörleri, betikler, ara dosyalar) aramayı da
istemedi (2026-09-27): programın masaüstüne koyduğu her şey `<masaüstü>/YENİ NESİL CAFER/` altında (Sonuçlar, Sorun
Raporları; geliştiricinin kurulum paketleri de). Bir işin sonuç dosyaları `Sonuçlar/<kategori>/<iş>/` içine KOPYALANIR:
asıl dosya iş klasöründe kalır, asistan sonraki mesajlarda orada çalışmaya devam eder.
"""

import os
import shutil
import subprocess
from pathlib import Path

PROJECT = "YENİ NESİL CAFER"
# görsel, 3D, ses/video, belge ve kod ("belgeler, görseller, kodlar"); asistanın iş için çalıştırdığı betikler geçici
# klasöre yazılır (run_python), iş klasöründeki kod dosyaları bilerek yazılmış çıktılardır. JSON yok: resim
# üretiminin yan dosyası (ayarlar) karışmasın.
RESULT_SUFFIXES = {".png", ".jpg", ".jpeg", ".webp", ".gif", ".svg", ".pdf", ".stl", ".3mf", ".step", ".stp", ".obj",
                   ".glb", ".gltf", ".ply", ".mp4", ".webm", ".mov", ".mp3", ".wav", ".ogg", ".docx", ".pptx", ".xlsx",
                   ".odt", ".txt", ".md", ".csv", ".html", ".css", ".js", ".ts", ".py", ".ipynb", ".sh", ".sql",
                   ".java", ".c", ".cpp", ".h", ".go", ".rs"}
SKIP_NAMES = {"ASISTAN.md"}  # kullanıcının talimat dosyası
SKIP_DIRS = {"tarayici-goruntu", "ekler", "__pycache__"}  # tarayıcı ekran görüntüleri, kullanıcının kendi ekleri


def desktop() -> Path:
    """Kullanıcının masaüstü (Linux: xdg-user-dir; Windows: kullanıcı klasöründeki Desktop); yoksa ev klasörü."""
    if os.name != "nt":
        try:
            out = subprocess.run(["xdg-user-dir", "DESKTOP"], capture_output=True, text=True, encoding="utf-8",
                                 errors="replace", timeout=5).stdout.strip()
            if out and Path(out).is_dir() and Path(out) != Path.home():
                return Path(out)
        except (OSError, subprocess.TimeoutExpired):
            pass
    for name in ("Desktop", "Masaüstü"):
        if (Path.home() / name).is_dir():
            return Path.home() / name
    return Path.home()


def project_dir(sub: str = "") -> Path:
    """`<masaüstü>/YENİ NESİL CAFER[/alt klasör]` (oluşturulmaz; yazan oluşturur)."""
    return desktop() / PROJECT / sub if sub else desktop() / PROJECT


def results_dir() -> Path:
    return project_dir("Sonuçlar")


def collect(work_dir, workspace, since: float, target_root: Path | None = None) -> list[Path]:
    """İş klasöründe `since`'ten sonra yazılan sonuç dosyalarını Sonuçlar'a kopyalar; kopyalananlar döner.

    Hedef, iş klasörünün çalışma klasörüne göre yolu (ör. `3D Modeller/oturan-kedi-4f2a`); iş klasörü çalışma
    klasörünün kendisiyse (eski sohbetler) `Genel`. Gizli dosya/klasörler (önizleme, denetim resimleri), figürün girdi
    resmi (`-girdi.png`), tarayıcı ekran görüntüleri ve kullanıcının ekleri kopyalanmaz. Değişmemiş dosya yeniden
    kopyalanmaz."""
    root, ws = Path(work_dir).resolve(), Path(workspace).expanduser().resolve()
    rel = root.relative_to(ws) if root != ws and root.is_relative_to(ws) else Path("Genel")
    dest = (target_root or results_dir()) / rel
    copied = []
    for folder, dirs, files in os.walk(root):
        depth = len(Path(folder).relative_to(root).parts)
        dirs[:] = [d for d in dirs if not d.startswith(".") and d not in SKIP_DIRS] if depth < 3 else []
        for name in files:
            path = Path(folder) / name
            if name.startswith(".") or name in SKIP_NAMES or path.suffix.lower() not in RESULT_SUFFIXES \
                    or path.stem.endswith("-girdi"):
                continue
            try:
                info = path.stat()
                if info.st_mtime < since:
                    continue
                target = dest / path.relative_to(root)
                if target.exists() and target.stat().st_size == info.st_size and target.stat().st_mtime >= info.st_mtime:
                    continue
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(path, target)
                copied.append(target)
            except OSError:
                continue
    return copied
