#!/usr/bin/env bash
# Yeni sürümü GitHub'da yayımlar (asistan/__init__.py'deki __version__ ve GITHUB_REPO):
#   testler → git etiketi ve gönderme → kurulum paketleri (2 GB'lık parçalara bölünür) → kod güncelleme paketi
#   → GitHub sürümü (notlar BENIOKU'nun "SÜRÜM x'DE YENİ" bölümünden).
# Kullanım: paketleme/yayinla.sh [--paketsiz]   (--paketsiz: yalnızca kod güncellemesi; büyük paketler yüklenmez)
# Gerekenler: gh (pkexec pacman -S github-cli) ve bir kez `gh auth login`.
set -euo pipefail
KAYNAK="$(cd "$(dirname "$0")/.." && pwd)"
cd "$KAYNAK"
PY="$KAYNAK/.venv/bin/python"
yaz() { printf '\n  \033[33m%s\033[0m\n' "$*"; }
hata() { printf '\n  \033[31m%s\033[0m\n' "$*"; exit 1; }

SURUM=$("$PY" -c "import asistan; print(asistan.__version__)")
REPO=$("$PY" -c "import asistan; print(asistan.GITHUB_REPO)")
[ -n "$REPO" ] || hata "asistan/__init__.py içinde GITHUB_REPO boş (ör. kullanici/yeni-nesil-cafer)."
command -v gh >/dev/null || hata "gh yok: pkexec pacman -S github-cli, sonra gh auth login"
gh auth status >/dev/null 2>&1 || hata "GitHub'a giriş yapılmamış: gh auth login"
git diff --quiet && git diff --cached --quiet || hata "Commit edilmemiş değişiklik var; önce commit et."
gh release view "v$SURUM" --repo "$REPO" >/dev/null 2>&1 && hata "v$SURUM zaten yayımlanmış; önce sürümü artır."

yaz "1/5 Testler"
QT_QPA_PLATFORM=offscreen "$PY" -m unittest discover -s testler 2>&1 | tail -3
QT_QPA_PLATFORM=offscreen "$PY" -m unittest discover -s testler >/dev/null 2>&1 || hata "Testler geçmedi; yayımlanmadı."

yaz "2/5 Git: v$SURUM etiketi ve gönderme"
git tag -f "v$SURUM"
git push origin HEAD --tags

CIKTI="$("$PY" -c "import sys; sys.path.insert(0, 'paketleme'); import paketle; print(paketle.masaustu())")/asistan.v$SURUM"
YAYIN="$CIKTI/github"
rm -rf "$YAYIN"; mkdir -p "$YAYIN"
DOSYALAR=()
if [ "${1:-}" != "--paketsiz" ]; then
    yaz "3/5 Kurulum paketleri (20-30 dk)"
    "$PY" paketleme/paketle.py
    for f in "$CIKTI"/asistan.v"$SURUM"-Windows.zip "$CIKTI"/asistan.v"$SURUM"-Linux.tar.gz; do
        split -b 1900M --numeric-suffixes=1 -a 3 "$f" "$YAYIN/$(basename "$f")."   # GitHub: dosya başına en çok 2 GB
    done
    cat > "$YAYIN/birlestir.bat" <<'BAT'
@echo off
rem Windows: indirilen parçaları (…zip.001, …zip.002…) tek zip dosyasında birleştirir. Parçalarla aynı klasörde çalıştır.
setlocal enabledelayedexpansion
cd /d "%~dp0"
for %%f in (*.zip.001) do set BASE=%%~nf
if not defined BASE ( echo Parçalar bulunamadı: .zip.001 dosyası bu klasörde olmalı. & pause & exit /b 1 )
set LIST=
for %%p in ("!BASE!.0*") do ( if defined LIST ( set LIST=!LIST!+"%%p" ) else ( set LIST="%%p" ) )
copy /b !LIST! "!BASE!" >nul && echo Hazır: !BASE! — şimdi sağ tık, "Tümünü ayıkla…" ve Kur.bat.
pause
BAT
    cat > "$YAYIN/birlestir.sh" <<'SH'
#!/usr/bin/env bash
# Linux: indirilen parçaları (…tar.gz.001, …tar.gz.002…) birleştirir; sonra: tar xzf <dosya> && ./YENI-NESIL-CAFER.v*/kur.sh
cd "$(dirname "$0")"
for first in *.tar.gz.001; do
    base="${first%.001}"; cat "$base".0* > "$base" && echo "Hazır: $base"
done
SH
    chmod +x "$YAYIN/birlestir.sh"
    cp "$CIKTI/BENIOKU.txt" "$YAYIN/"
fi

yaz "4/5 Kod güncelleme paketi"
"$PY" -c "
from pathlib import Path
from asistan.updates import build_package
p, sha = build_package(Path('.'), Path('$YAYIN'))
print(p.name, round(p.stat().st_size / 1e6, 2), 'MB', sha[:16])"

yaz "5/5 GitHub sürümü (büyük dosyaların yüklenmesi bağlantına göre uzun sürebilir)"
"$PY" - "$SURUM" > "$YAYIN/notlar.md" <<'PYNOT'
import re, sys
surum = sys.argv[1]
beni = open("paketleme/BENIOKU.txt", encoding="utf-8").read()
m = re.search(rf"SÜRÜM {re.escape(surum)}'DE YENİ\n(.*?)\n\n", beni, re.S)
yeni = m.group(1) if m else "  - (notlar BENIOKU'da)"
print(f"## YENİ NESİL CAFER {surum}\n\n### Yenilikler\n" + "\n".join(
    "- " + satir.strip()[2:] if satir.strip().startswith("- ") else "  " + satir.strip() for satir in yeni.splitlines()))
print(f"""
### Kurulum (ilk kez)
1. Sistemine uygun parçaların **hepsini** ve birleştirme betiğini indir (Windows: `…Windows.zip.00*` +
   `birlestir.bat`; Linux: `…Linux.tar.gz.00*` + `birlestir.sh`), aynı klasöre koy.
2. Birleştir: Windows'ta `birlestir.bat`'a çift tıkla; Linux'ta `./birlestir.sh`.
3. Windows: zip'i çıkar → `Kur.bat`. Linux: `tar xzf asistan.v{surum}-Linux.tar.gz && ./asistan.v{surum}/kur.sh`.
Ayrıntılar: `BENIOKU.txt`.

### Güncelleme (zaten kuruluysa)
Program yeni sürümü kendisi haber verir: **Yardım → Güncelleme var → Güncelle** (yalnızca birkaç MB indirir;
sorun çıkarsa eski sürüme kendiliğinden döner).""")
PYNOT
gh release create "v$SURUM" --repo "$REPO" --title "YENİ NESİL CAFER $SURUM" --notes-file "$YAYIN/notlar.md" \
    "$YAYIN"/yeni-nesil-cafer-guncelleme-"$SURUM".zip "$YAYIN"/yeni-nesil-cafer-guncelleme-"$SURUM".zip.sha256
if [ "${1:-}" != "--paketsiz" ]; then
    for f in "$YAYIN"/*.00* "$YAYIN"/birlestir.bat "$YAYIN"/birlestir.sh "$YAYIN"/BENIOKU.txt; do
        yaz "yükleniyor: $(basename "$f")"
        gh release upload "v$SURUM" --repo "$REPO" "$f" --clobber
    done
fi
yaz "Yayımlandı: https://github.com/$REPO/releases/tag/v$SURUM"
