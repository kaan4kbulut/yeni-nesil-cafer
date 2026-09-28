#!/usr/bin/env bash
# Sunucu doğrulama: her satır ✓/✗. Kullanım: ./sunucu/dogrula.sh [http://adres:8765] [anahtar]
# (anahtar verilmezse CAFER_TOKEN ortamından ya da /var/lib/yeni-nesil-cafer/yeni-nesil-cafer/bulut.json'dan okunur)
ADRES="${1:-http://127.0.0.1:8765}"
ANAHTAR="${2:-${CAFER_TOKEN:-}}"
CONF=/var/lib/yeni-nesil-cafer/yeni-nesil-cafer/bulut.json
[ -z "$ANAHTAR" ] && [ -r "$CONF" ] && ANAHTAR=$(python3 -c "import json;print(json.load(open('$CONF')).get('token',''))" 2>/dev/null)
ok() { echo "✓ $1"; }
hata() { echo "✗ $1"; SONUC=1; }
SONUC=0
if systemctl is-active --quiet yeni-nesil-cafer-bulut 2>/dev/null; then ok "servis yeni-nesil-cafer-bulut ayakta"; else
  docker compose -f "$(dirname "$0")/docker-compose.yml" ps 2>/dev/null | grep -q "cafer-web" && ok "docker: cafer-web ayakta" || hata "servis ayakta değil (systemd ya da docker)"; fi
KOD=$(curl -s -o /tmp/saglik.json -w "%{http_code}" "$ADRES/saglik" || echo 000)
[ "$KOD" = 200 ] && ok "GET /saglik 200: $(cat /tmp/saglik.json)" || hata "GET /saglik → $KOD"
KOD=$(curl -s -o /dev/null -w "%{http_code}" -X POST "$ADRES/gorev" -H "Content-Type: application/json" -d '{"istek":"x"}' || echo 000)
[ "$KOD" = 401 ] && ok "anahtarsız POST /gorev 401" || hata "anahtarsız POST /gorev → $KOD (401 bekleniyordu)"
if [ -n "$ANAHTAR" ]; then
  KOD=$(curl -s -o /dev/null -w "%{http_code}" "$ADRES/onaylar" -H "Authorization: Bearer $ANAHTAR" || echo 000)
  [ "$KOD" = 200 ] && ok "anahtarlı GET /onaylar 200" || hata "anahtarlı GET /onaylar → $KOD"
else hata "anahtar bulunamadı (CAFER_TOKEN ya da bulut.json)"; fi
curl -s "$ADRES/" | grep -q "manifest.webmanifest" && ok "PWA sayfası (manifest bağlı)" || hata "PWA sayfası yok"
if [ -r "$CONF" ]; then
  python3 -c "import json;t=json.load(open('$CONF')).get('telegram_token','');print('var' if t else 'yok')" | grep -q var && ok "Telegram anahtarı okunuyor" || echo "· Telegram anahtarı yok (isteğe bağlı)"
  VERI=$(dirname "$CONF"); [ -w "$VERI" ] && ok "veri klasörü yazılabilir: $VERI" || hata "veri klasörü yazılamıyor: $VERI"
fi
[ $SONUC = 0 ] && echo "Hepsi ✓" || echo "Eksikler var"
exit $SONUC
