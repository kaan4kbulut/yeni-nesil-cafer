#!/usr/bin/env bash
# YENİ NESİL CAFER · sunucu kurulumu (Ubuntu 22.04 / 24.04; ARM ya da x86, ekran kartı gerekmez). K8: web + PWA
# (python -m asistan sunucu) + Telegram; belge docs/SUNUCU_KURULUM.md. İdempotent: iki kez çalıştırmak bozmaz.
# Kullanım:   sudo ./kur.sh [model]            (varsayılan model: qwen3.5:4b)
#             sudo ./kur.sh --telegram TOKEN   (BotFather'dan alınan bot anahtarını ekler)
set -euo pipefail

SRC="$(cd "$(dirname "$0")/.." && pwd)"   # paketin açıldığı klasör (asistan/ burada)
DEST=/opt/yeni-nesil-cafer
DATA=/var/lib/yeni-nesil-cafer
CONF="$DATA/yeni-nesil-cafer/bulut.json"
SERVICE=yeni-nesil-cafer-bulut
[ "$(id -u)" = 0 ] || { echo "Bu betik sudo ile çalıştırılmalı: sudo $0 $*"; exit 1; }

json_set() {  # json_set anahtar değer — bulut.json'daki bir alanı günceller
    "$DEST/venv/bin/python" - "$CONF" "$1" "$2" <<'PY'
import json, sys
path, key, value = sys.argv[1:]
try:
    conf = json.load(open(path, encoding="utf-8"))
except (OSError, ValueError):
    conf = {}
conf[key] = int(value) if value.isdigit() and key == "port" else value
json.dump(conf, open(path, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
PY
    chown asistan:asistan "$CONF"; chmod 600 "$CONF"
}

if [ "${1:-}" = "--telegram" ]; then
    [ -n "${2:-}" ] || { echo "Kullanım: sudo $0 --telegram BOT_ANAHTARI"; exit 1; }
    json_set telegram_token "$2"
    systemctl restart "$SERVICE"
    CODE=$("$DEST/venv/bin/python" -c "import json; print(json.load(open('$CONF'))['pair_code'])")
    echo "Telegram botu eklendi. Telefondan bota şunu yaz:  /baglan $CODE"
    exit 0
fi

MODEL="${1:-qwen3.5:4b}"
echo "[1/7] Sistem paketleri"
apt-get update -qq
apt-get install -y -qq python3 python3-venv curl ca-certificates >/dev/null

echo "[2/7] Ollama"
command -v ollama >/dev/null || curl -fsSL https://ollama.com/install.sh | sh
systemctl enable --now ollama >/dev/null 2>&1 || true

echo "[3/7] Modeller: $MODEL ve nomic-embed-text (bağlantına göre birkaç dakika)"
ollama pull "$MODEL"
ollama pull nomic-embed-text

echo "[4/7] Program ($DEST) ve kullanıcı"
id asistan >/dev/null 2>&1 || useradd --system --home "$DATA" --shell /usr/sbin/nologin asistan
mkdir -p "$DEST" "$DATA/yeni-nesil-cafer" "$DATA/ayar"
rm -rf "$DEST/asistan"
cp -r "$SRC/asistan" "$DEST/"
[ -x "$DEST/venv/bin/python" ] || python3 -m venv "$DEST/venv"
cp "$SRC/requirements-sunucu.txt" "$DEST/" 2>/dev/null || true
"$DEST/venv/bin/pip" install -q --disable-pip-version-check -r "$DEST/requirements-sunucu.txt" 2>/dev/null || \
"$DEST/venv/bin/pip" install -q --disable-pip-version-check fastapi uvicorn httpx anthropic ddgs beautifulsoup4 keyring psutil
chown -R asistan:asistan "$DATA"

echo "[5/7] Tailscale (web sayfası ve program yalnızca senin cihazlarından erişsin)"
if ! command -v tailscale >/dev/null; then
    curl -fsSL https://tailscale.com/install.sh | sh
fi
if ! tailscale ip -4 >/dev/null 2>&1; then
    echo "  Aşağıdaki bağlantıyı aç ve Tailscale hesabınla giriş yap (telefonunda ve bilgisayarında da aynı hesap):"
    tailscale up
fi
HOST=$(tailscale ip -4 2>/dev/null | head -1 || true)
HOST=${HOST:-127.0.0.1}

echo "[6/7] Ayarlar"
json_set model "$MODEL"
json_set host "$HOST"
json_set port 8765

echo "[7/7] Servis"
cat > "/etc/systemd/system/$SERVICE.service" <<UNIT
[Unit]
Description=YENİ NESİL CAFER bulut
After=network-online.target ollama.service tailscaled.service
Wants=network-online.target

[Service]
User=asistan
Environment=XDG_DATA_HOME=$DATA XDG_CONFIG_HOME=$DATA/ayar HOME=$DATA
WorkingDirectory=$DEST
Environment=CAFER_GENEL_KADEME_KILIDI=sunucu
ExecStart=$DEST/venv/bin/python -m asistan sunucu --host $HOST --port 8765
Restart=on-failure
RestartSec=5
NoNewPrivileges=true
ProtectSystem=strict
ProtectHome=true
PrivateTmp=true
ReadWritePaths=$DATA

[Install]
WantedBy=multi-user.target
UNIT
systemctl daemon-reload
systemctl enable --now "$SERVICE" >/dev/null
sleep 3
systemctl restart "$SERVICE"
sleep 2

TOKEN=$("$DEST/venv/bin/python" -c "import json; print(json.load(open('$CONF'))['token'])" 2>/dev/null || echo "?")
echo
echo "Kurulum bitti."
echo "  Web sayfası (Tailscale'e bağlı cihazlarından): http://$HOST:8765"
echo "  Programda Ayarlar → Bulut asistan:  Adres: http://$HOST:8765   Anahtar: $TOKEN"
echo "  Telegram botu için:  sudo $0 --telegram BOT_ANAHTARI"
echo "  Durum: systemctl status $SERVICE   ·   Kayıt: journalctl -u $SERVICE -f"
