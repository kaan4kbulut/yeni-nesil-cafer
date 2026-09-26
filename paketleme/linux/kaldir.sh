#!/usr/bin/env bash
# YENİ NESİL CAFER'i kaldırır. Sohbetlerin ve ayarların silinmez (~/.config/yeni-nesil-cafer, ~/.local/share/yeni-nesil-cafer).
VERI="${XDG_DATA_HOME:-$HOME/.local/share}"
MASAUSTU="$(xdg-user-dir DESKTOP 2>/dev/null || echo "$HOME/Desktop")"
for HEDEF in "$VERI/yeni-nesil-cafer-app" "$VERI/yerel-asistan-app"; do  # yeni ve 2.2'ye kadarki kurulum
    pkill -f "^$HEDEF/" 2>/dev/null  # açık kalan program ve paketteki Ollama
    rm -rf "$HEDEF"
done
rm -f "$VERI/applications/yeni-nesil-cafer.desktop" "$VERI/applications/yerel-asistan.desktop" \
      "$MASAUSTU/yeni-nesil-cafer.desktop" "$MASAUSTU/yerel-asistan.desktop"
echo "YENİ NESİL CAFER kaldırıldı. Sohbetlerin ve ayarların duruyor."
echo "Yüklenen yapay zekâ modelleri ~/.ollama klasöründe; yer açmak istersen o klasörü silebilirsin."
