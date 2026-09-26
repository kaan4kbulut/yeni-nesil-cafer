#!/usr/bin/env bash
# Bulut sunucusuna gönderilecek paketi hazırlar: dist/yeni-nesil-cafer-bulut.tar.gz (arayüz kodu olmadan).
set -euo pipefail
KAYNAK="$(cd "$(dirname "$0")/.." && pwd)"
TMP=$(mktemp -d)
trap 'rm -rf "$TMP"' EXIT
mkdir -p "$TMP/yeni-nesil-cafer-bulut" "$KAYNAK/dist"
rsync -a --exclude __pycache__ --exclude gui "$KAYNAK/asistan" "$TMP/yeni-nesil-cafer-bulut/"
cp -r "$KAYNAK/sunucu" "$TMP/yeni-nesil-cafer-bulut/"
tar czf "$KAYNAK/dist/yeni-nesil-cafer-bulut.tar.gz" -C "$TMP" yeni-nesil-cafer-bulut
echo "Hazır: $KAYNAK/dist/yeni-nesil-cafer-bulut.tar.gz ($(du -h "$KAYNAK/dist/yeni-nesil-cafer-bulut.tar.gz" | cut -f1))"
