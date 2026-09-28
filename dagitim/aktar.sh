#!/usr/bin/env bash
# Kaynaktaki değişiklikleri kurulu programa aktarır: önce yedek alır, kopyalar, derler, programı yeniden başlatır.
# Kullanım: dagitim/aktar.sh [--baslatma]   (--baslatma: yalnızca kopyala, programı yeniden başlatma)
set -euo pipefail

KAYNAK="$(cd "$(dirname "$0")/.." && pwd)"
KURULU="${YNC_KURULU:-$HOME/.local/share/yeni-nesil-cafer-app}"
[ -d "$KURULU" ] || [ ! -d "$HOME/.local/share/yerel-asistan-app" ] || KURULU="$HOME/.local/share/yerel-asistan-app"  # eski adlı kurulum
PY="$KURULU/python/bin/python3"
[ -x "$PY" ] || { echo "Kurulu program bulunamadı: $KURULU"; exit 1; }

# yalnızca değişen dosyaların yedeği (git'teki sürüm de geri dönüş yolu)
YEDEK="$KURULU-yedek-$(date +%Y%m%d-%H%M%S)"
DEGISEN=$(diff -rq "$KAYNAK/asistan" "$KURULU/asistan" -x __pycache__ 2>/dev/null | grep -oP "(?<=$KAYNAK/)asistan/\S+(?= ve| and)" || true)
if [ -z "$DEGISEN" ] && cmp -s "$KAYNAK/main.py" "$KURULU/main.py"; then
    echo "Kurulu program zaten güncel."
else
    for f in $DEGISEN; do
        [ -f "$KURULU/$f" ] && install -D -m 644 "$KURULU/$f" "$YEDEK/$f"
    done
    echo "Değişen dosyalar:"; printf '  %s\n' $DEGISEN
    [ -d "$YEDEK" ] && echo "Yedek: $YEDEK"
    rsync -a --exclude __pycache__ "$KAYNAK/asistan/" "$KURULU/asistan/"
    cp "$KAYNAK/main.py" "$KURULU/main.py"
    "$PY" -m compileall -q "$KURULU/asistan" >/dev/null && echo "Derleme: tamam"
fi

[ "${1:-}" = "--baslatma" ] && exit 0
PID=$(pgrep -f "^$KURULU/python/bin/python3 main.py" || true)
if [ -n "$PID" ]; then
    kill $PID
    for _ in $(seq 20); do kill -0 $PID 2>/dev/null || break; sleep 0.5; done
fi
BASLAT=./yeni-nesil-cafer; [ -x "$KURULU/$BASLAT" ] || BASLAT=./yerel-asistan  # eski adlı kurulumun başlatıcısı
(cd "$KURULU" && setsid nohup "$BASLAT" >/dev/null 2>&1 < /dev/null &)
sleep 3
pgrep -f "^$KURULU/python/bin/python3 main.py" >/dev/null && echo "Program yeniden başladı." || echo "UYARI: program açılmadı."
