#!/usr/bin/env bash
# YENİ NESİL CAFER — macOS kurulumu (Finder'da çift tıkla; ilk seferde: sağ tık → Aç → Aç)
# Küçük paket: Python, kütüphaneler, Ollama ve tarayıcı resmi kaynaklarından indirilir (asistan/bootstrap.py;
# sürümler sabit, SHA-256 doğrulamalı); modelleri ilk açılıştaki kurulum sihirbazı indirir.
# Apple Silicon (M1 ve sonrası) macOS 14+, Intel Mac macOS 12+. Programı ~/.local/share/yeni-nesil-cafer-app'e
# kurar; ~/Applications'a "YENİ NESİL CAFER" uygulamasını, masaüstüne kısayolunu ekler.
set -euo pipefail
cd "$(dirname "$0")"
KAYNAK="$(pwd)/program"
HEDEF="$HOME/.local/share/yeni-nesil-cafer-app"
UYGULAMA="$HOME/Applications/YENİ NESİL CAFER.app"
yaz() { printf '  \033[33m%s\033[0m\n' "$*"; }
hata() { printf '\n  \033[31m%s\033[0m\n\n' "$*"; read -r -p "  Kapatmak için Enter'a bas… " _ || true; exit 1; }

printf '\n  YENİ NESİL CAFER · kurulum (macOS)\n\n'
[ -f "$KAYNAK/main.py" ] || hata "Kurulum dosyaları eksik. Zip'i açıp çıkan klasördeki Kur.command'ı çalıştır."

MIMARI="$(uname -m)"
SURUM="$(sw_vers -productVersion)"
ANA="${SURUM%%.*}"
case "$MIMARI" in
    arm64) PY_URL="@PY_URL_MAC_ARM64@"; PY_SHA="@PY_SHA_MAC_ARM64@"; EN_AZ=14 ;;
    x86_64) PY_URL="@PY_URL_MAC_X86_64@"; PY_SHA="@PY_SHA_MAC_X86_64@"; EN_AZ=12 ;;
    *) hata "Bu işlemci türü desteklenmiyor: $MIMARI" ;;
esac
[ "$ANA" -ge "$EN_AZ" ] || hata "macOS $EN_AZ ya da daha yenisi gerekiyor (bu Mac: $SURUM). Sistem Ayarları → Genel → Yazılım Güncelleme."
yaz "Mac: $MIMARI · macOS $SURUM"

pkill -f "^$HEDEF/" 2>/dev/null || true  # eski kurulumdan açık kalan program ya da Ollama

yaz "Program kopyalanıyor: $HEDEF"
mkdir -p "$HEDEF"
cp -R "$KAYNAK/." "$HEDEF/"
xattr -dr com.apple.quarantine "$HEDEF" 2>/dev/null || true  # indirilen zip'ten gelen "internetten" işareti
PY="$HEDEF/python/bin/python3"

if [ "$(cat "$HEDEF/python/.surum" 2>/dev/null)" != "$PY_URL" ]; then
    yaz "Python indiriliyor (~25 MB)…"
    ARSIV="$HEDEF/kurulum/python.tar.gz"
    mkdir -p "$HEDEF/kurulum"
    curl -fL --retry 5 --retry-delay 3 -C - -o "$ARSIV" "$PY_URL" || hata "Python indirilemedi. İnterneti denetleyip Kur.command'ı yeniden çalıştır."
    [ "$(shasum -a 256 "$ARSIV" | cut -d' ' -f1)" = "$PY_SHA" ] || { rm -f "$ARSIV"; hata "Python doğrulanamadı (SHA-256); Kur.command'ı yeniden çalıştır."; }
    rm -rf "$HEDEF/python"
    tar -xzf "$ARSIV" -C "$HEDEF" && rm -f "$ARSIV"
    echo "$PY_URL" > "$HEDEF/python/.surum"
fi
(cd "$HEDEF" && "$PY" -m asistan.bootstrap "$HEDEF") \
    || hata "Kurulum yarım kaldı. İnterneti denetleyip Kur.command'ı yeniden çalıştır; inenler korunur, kaldığı yerden sürer."

yaz "Program denetleniyor…"
QT_QPA_PLATFORM=offscreen "$PY" -c "import PySide6.QtWidgets, httpx, anthropic, ddgs, bs4, keyring, psutil" 2>/dev/null \
    || hata "Programın parçaları yüklenemedi (Python denetimi başarısız)."

yaz "Uygulama oluşturuluyor: $UYGULAMA"
rm -rf "$UYGULAMA"
mkdir -p "$UYGULAMA/Contents/MacOS" "$UYGULAMA/Contents/Resources"
cat > "$UYGULAMA/Contents/MacOS/yeni-nesil-cafer" <<LAUNCH
#!/bin/bash
cd "$HEDEF" && exec "$PY" main.py "\$@"
LAUNCH
chmod +x "$UYGULAMA/Contents/MacOS/yeni-nesil-cafer"
cat > "$UYGULAMA/Contents/Info.plist" <<PLIST
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict>
  <key>CFBundleName</key><string>YENİ NESİL CAFER</string>
  <key>CFBundleDisplayName</key><string>YENİ NESİL CAFER</string>
  <key>CFBundleIdentifier</key><string>com.github.kaan4kbulut.yeni-nesil-cafer</string>
  <key>CFBundleExecutable</key><string>yeni-nesil-cafer</string>
  <key>CFBundleIconFile</key><string>icon</string>
  <key>CFBundlePackageType</key><string>APPL</string>
  <key>LSMinimumSystemVersion</key><string>$EN_AZ.0</string>
  <key>NSHighResolutionCapable</key><true/>
  <key>NSMicrophoneUsageDescription</key><string>Konuşarak yazma (dikte) için mikrofon kullanılır; ses bilgisayarından çıkmaz.</string>
</dict></plist>
PLIST
# simge: programın PNG'sinden (sips ve iconutil macOS'ta hazır gelir); olmazsa simgesiz de çalışır
SIMGE="$HEDEF/asistan/gui/assets/icon.png"
if [ -f "$SIMGE" ] && command -v iconutil >/dev/null; then
    SET="$(mktemp -d)/icon.iconset"; mkdir -p "$SET"
    for n in 16 32 128 256 512; do
        sips -z $n $n "$SIMGE" --out "$SET/icon_${n}x${n}.png" >/dev/null 2>&1 || true
        sips -z $((n * 2)) $((n * 2)) "$SIMGE" --out "$SET/icon_${n}x${n}@2x.png" >/dev/null 2>&1 || true
    done
    iconutil -c icns "$SET" -o "$UYGULAMA/Contents/Resources/icon.icns" 2>/dev/null || true
fi
ln -sfn "$UYGULAMA" "$HOME/Desktop/YENİ NESİL CAFER" 2>/dev/null || true

echo
yaz "Kurulum bitti. YENİ NESİL CAFER açılıyor (Uygulamalar ve masaüstünde de var)."
yaz "İlk açılışta sistemini tarayıp sana uygun modelleri önerecek; modeller o zaman iner."
open "$UYGULAMA" || true
