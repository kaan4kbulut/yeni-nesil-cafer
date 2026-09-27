#!/usr/bin/env bash
# Yeni sürümü GitHub'da yayımlar (asistan/__init__.py'deki __version__ ve GITHUB_REPO):
#   testler → git etiketi ve gönderme → internet kurulum dosyaları (~1 MB; gerisini kurulum indirir) → kod
#   güncelleme paketi → GitHub sürümü (notlar BENIOKU'nun "SÜRÜM x'DE YENİ" bölümünden).
# Bağlantı koparsa her dosya kendiliğinden yeniden denenir; betik yarıda kalırsa yeniden çalıştır: yüklenmiş
# dosyaları atlayıp kaldığı yerden devam eder. Sürüm, her şey yüklenene kadar taslaktır (kimse yarım sürümü görmez).
# Kullanım: paketleme/yayinla.sh [--tam | --paketsiz]
#   (varsayılan: küçük kurulum dosyaları + kod güncellemesi; --tam: ayrıca ~8 GB'lık tam paketler 2 GB'lık
#    parçalar halinde, saatler sürebilir; --paketsiz: yalnızca kod güncellemesi)
# Gerekenler: gh (pkexec pacman -S github-cli) ve bir kez `gh auth login`.
set -euo pipefail
KAYNAK="$(cd "$(dirname "$0")/.." && pwd)"
cd "$KAYNAK"
PY="$KAYNAK/.venv/bin/python"
yaz() { printf '\n  \033[33m%s\033[0m\n' "$*"; }
hata() { printf '\n  \033[31m%s\033[0m\n' "$*"; exit 1; }

SURUM=$("$PY" -c "import asistan; print(asistan.__version__)")
PAKET=$("$PY" -c "import asistan; print(asistan.SURUM_ADI)")
REPO=$("$PY" -c "import asistan; print(asistan.GITHUB_REPO)")
[ -n "$REPO" ] || hata "asistan/__init__.py içinde GITHUB_REPO boş (ör. kullanici/yeni-nesil-cafer)."
command -v gh >/dev/null || hata "gh yok: pkexec pacman -S github-cli, sonra gh auth login"
gh auth status >/dev/null 2>&1 || hata "GitHub'a giriş yapılmamış: gh auth login"
git diff --quiet && git diff --cached --quiet || hata "Commit edilmemiş değişiklik var; önce commit et."
DEVAM=0
if gh release view "v$SURUM" --repo "$REPO" >/dev/null 2>&1; then
    [ "$(gh release view "v$SURUM" --repo "$REPO" --json isDraft -q .isDraft)" = "true" ] \
        || hata "v$SURUM zaten yayımlanmış; önce sürümü artır."
    DEVAM=1
fi
CIKTI="$("$PY" -c "import sys; sys.path.insert(0, 'paketleme'); import paketle; print(paketle.paket_klasoru())")/$PAKET"
YAYIN="$CIKTI/github"

# Bağlantı koparsa bekleyip yeniden dener (en çok ~1 saat)
yukle() {
    local f="$1" i
    for i in $(seq 1 60); do
        gh release upload "v$SURUM" --repo "$REPO" "$f" --clobber && return 0
        yaz "Yüklenemedi (bağlantı?); 60 sn sonra yeniden denenecek ($i/60): $(basename "$f")"
        sleep 60
    done
    hata "$(basename "$f") yüklenemedi. İnternet gelince betiği yeniden çalıştır; kaldığı yerden devam eder."
}

if [ "$DEVAM" = 1 ] && [ -d "$YAYIN" ]; then
    yaz "v$SURUM taslağı var: eksik dosyaların yüklenmesine devam ediliyor"
else

yaz "1/5 Testler"
QT_QPA_PLATFORM=offscreen "$PY" -m unittest discover -s testler 2>&1 | tail -3
QT_QPA_PLATFORM=offscreen "$PY" -m unittest discover -s testler >/dev/null 2>&1 || hata "Testler geçmedi; yayımlanmadı."

yaz "2/5 Git: v$SURUM etiketi ve gönderme"
git tag -f "v$SURUM"
git push origin HEAD --tags

rm -rf "$YAYIN"; mkdir -p "$YAYIN"
if [ "${1:-}" != "--paketsiz" ]; then
    yaz "3/5 Kurulum dosyaları (internet paketi)"
    "$PY" paketleme/paketle.py --internet
    cp "$CIKTI/$PAKET-Windows-internet.zip" "$CIKTI/$PAKET-Linux-internet.tar.gz" "$CIKTI/BENIOKU.txt" "$YAYIN/"
fi
if [ "${1:-}" = "--tam" ]; then
    # Paketler son program değişikliğinden sonra üretildiyse yeniden üretilmez (testler, CI ve bu betik sayılmaz)
    SON=$(git log -1 --format=%ct -- . ':!testler' ':!.github' ':!paketleme/yayinla.sh')
    if [ -f "$CIKTI/$PAKET-Linux.tar.gz" ] && [ -f "$CIKTI/$PAKET-Windows.zip" ] \
        && [ "$(stat -c %Y "$CIKTI/$PAKET-Linux.tar.gz")" -gt "$SON" ] && [ "$(stat -c %Y "$CIKTI/$PAKET-Windows.zip")" -gt "$SON" ]; then
        yaz "3/5 Kurulum paketleri güncel; yeniden üretilmiyor"
    else
        yaz "3/5 Kurulum paketleri (20-30 dk)"
        "$PY" paketleme/paketle.py
    fi
    for f in "$CIKTI/$PAKET-Windows.zip" "$CIKTI/$PAKET-Linux.tar.gz"; do
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
Aşağıdaki **Assets** bölümünden sistemine uygun **tek dosyayı** indir (yaklaşık 1 MB). Kurulum gereken her şeyi
(Python, kütüphaneler, Ollama, tarayıcı; ~2,5 GB) resmi kaynaklarından kendisi indirir; yapay zekâ modellerini ilk
açılıştaki sihirbaz indirir. Kesilirse yeniden çalıştır, kaldığı yerden sürer.

- **Windows 10 / 11:** `YENI-NESIL-CAFER.v{surum}-Windows-internet.zip` → sağ tık → **Tümünü ayıkla…** → çıkan klasörde
  **`Kur.bat`**'a çift tıkla. "Windows bilgisayarınızı korudu" çıkarsa: **Ek bilgi → Yine de çalıştır**.
- **Linux:** `tar xzf YENI-NESIL-CAFER.v{surum}-Linux-internet.tar.gz && ./YENI-NESIL-CAFER.v{surum}/kur.sh`
- **macOS** (Apple Silicon: macOS 14+, Intel: macOS 12+): `YENI-NESIL-CAFER.v{surum}-macOS-internet.zip` → çift tıkla →
  çıkan klasörde **`Kur.command`**'a **sağ tık → Aç → Aç** (imzasız olduğu için; "Apple doğrulayamadı" derse Sistem
  Ayarları → Gizlilik ve Güvenlik → Yine de Aç).

Gerekenler: kurulum sırasında internet, en az 8 GB RAM (önerilen 16 GB ve 8 GB+ ekran kartı), ~15 GB boş alan.
Ayrıntılar: `BENIOKU.txt`.

### Güncelleme (zaten kuruluysa)
Program yeni sürümü kendisi haber verir: **Yardım → Güncelleme var → Güncelle** (yalnızca birkaç MB indirir;
sorun çıkarsa eski sürüme kendiliğinden döner).""")
PYNOT
[ "$DEVAM" = 1 ] || gh release create "v$SURUM" --repo "$REPO" --draft --title "YENİ NESİL CAFER $SURUM" --notes-file "$YAYIN/notlar.md"
fi

# Yüklenmiş ve boyutu tutan dosyalar atlanır (yarıda kalan yükleme yeniden çalıştırınca devam eder)
declare -A VAR
while IFS=$'\t' read -r ad boyut; do VAR["$ad"]=$boyut; done \
    < <(gh release view "v$SURUM" --repo "$REPO" --json assets -q '.assets[] | [.name, (.size|tostring)] | @tsv')
DOSYALAR=("$YAYIN"/yeni-nesil-cafer-guncelleme-"$SURUM".zip "$YAYIN"/yeni-nesil-cafer-guncelleme-"$SURUM".zip.sha256)
[ "${1:-}" != "--paketsiz" ] && DOSYALAR+=("$YAYIN"/*-internet.* "$YAYIN"/BENIOKU.txt)
[ "${1:-}" = "--tam" ] && DOSYALAR+=("$YAYIN"/*.00* "$YAYIN"/birlestir.bat "$YAYIN"/birlestir.sh)
SAYI=${#DOSYALAR[@]}; SIRA=0
for f in "${DOSYALAR[@]}"; do
    SIRA=$((SIRA + 1)); ad=$(basename "$f")
    if [ "${VAR[$ad]:-}" = "$(stat -c %s "$f")" ]; then yaz "[$SIRA/$SAYI] zaten yüklü: $ad"; continue; fi
    yaz "[$SIRA/$SAYI] yükleniyor: $ad ($(( $(stat -c %s "$f") / 1048576 )) MB)"
    yukle "$f"
done
gh release edit "v$SURUM" --repo "$REPO" --draft=false --latest
yaz "Yayımlandı: https://github.com/$REPO/releases/tag/v$SURUM"
