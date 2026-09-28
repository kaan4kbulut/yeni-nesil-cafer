#!/bin/sh
# YENİ NESİL CAFER AppImage — masaüstüne kurulum (AppImage içine gömülü; `./YeniNesilCafer-…AppImage --install`).
# AppImage dosyasını olduğu yerde bırakır; menüye ve masaüstüne .desktop kısayolu + ikon ekler. `--uninstall` kaldırır.
# Kullanım: kur.sh <AppImage yolu> <ikon yolu> [--uninstall]
set -eu
APPIMAGE="${1:?AppImage yolu}"
IKON="${2:-}"
KIP="${3:-}"
AD="yeni-nesil-cafer"
UYG="${XDG_DATA_HOME:-$HOME/.local/share}/applications"
IKONLAR="${XDG_DATA_HOME:-$HOME/.local/share}/icons/hicolor/256x256/apps"
MASAUSTU="$(xdg-user-dir DESKTOP 2>/dev/null || echo "$HOME/Desktop")"
DESKTOP="$UYG/$AD.desktop"

if [ "$KIP" = "--uninstall" ]; then
    rm -f "$DESKTOP" "$MASAUSTU/$AD.desktop" "$IKONLAR/$AD.png"
    update-desktop-database "$UYG" 2>/dev/null || true
    echo "Kısayollar kaldırıldı (AppImage dosyası silinmedi): $APPIMAGE"
    exit 0
fi

chmod +x "$APPIMAGE" 2>/dev/null || true
mkdir -p "$UYG" "$IKONLAR"
[ -n "$IKON" ] && [ -f "$IKON" ] && cp "$IKON" "$IKONLAR/$AD.png"
cat > "$DESKTOP" <<EOF
[Desktop Entry]
Type=Application
Name=YENİ NESİL CAFER
Comment=Bilgisayarında çalışan kişisel yapay zekâ asistanı ve ekibi
Exec="$APPIMAGE" %F
Icon=$AD
Terminal=false
Categories=Utility;Office;
StartupNotify=true
Actions=uninstall;

[Desktop Action uninstall]
Name=Kısayolları kaldır
Exec="$APPIMAGE" --uninstall
EOF
chmod 755 "$DESKTOP"
if [ -d "$MASAUSTU" ]; then
    cp "$DESKTOP" "$MASAUSTU/$AD.desktop"
    chmod 755 "$MASAUSTU/$AD.desktop"
    gio set "$MASAUSTU/$AD.desktop" metadata::trusted true 2>/dev/null || true  # GNOME: "güvenilir" işareti
fi
update-desktop-database "$UYG" 2>/dev/null || true
gtk-update-icon-cache -q "${XDG_DATA_HOME:-$HOME/.local/share}/icons/hicolor" 2>/dev/null || true
echo "Kuruldu: uygulama menüsünde ve masaüstünde «YENİ NESİL CAFER» ($APPIMAGE)"
