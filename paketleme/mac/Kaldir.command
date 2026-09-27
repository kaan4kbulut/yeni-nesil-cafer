#!/usr/bin/env bash
# YENİ NESİL CAFER — macOS'tan kaldırır (sohbetlerin, ayarların ve çalışma klasörün silinmez)
HEDEF="$HOME/.local/share/yeni-nesil-cafer-app"
pkill -f "^$HEDEF/" 2>/dev/null || true
rm -rf "$HEDEF" "$HOME/Applications/YENİ NESİL CAFER.app" "$HOME/Desktop/YENİ NESİL CAFER"
printf '\n  YENİ NESİL CAFER kaldırıldı. Sohbetler ve ayarlar ~/.local/share/yeni-nesil-cafer ve\n'
printf '  ~/.config/yeni-nesil-cafer klasörlerinde duruyor; istersen onları da silebilirsin.\n\n'
read -r -p "  Kapatmak için Enter'a bas… " _ || true
