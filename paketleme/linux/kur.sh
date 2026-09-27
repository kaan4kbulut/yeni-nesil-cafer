#!/usr/bin/env bash
# YENİ NESİL CAFER — Linux kurulumu
# Tam paket: her şey içinde (taşınabilir Python ve kütüphaneleri, Ollama, temel model), internet gerekmez.
# İnternet paketi (GitHub'daki küçük dosya): Python, kütüphaneler, Ollama ve tarayıcı resmi kaynaklarından indirilir
# (asistan/bootstrap.py; sürümler sabit, SHA-256 doğrulamalı); modelleri ilk açılıştaki kurulum sihirbazı indirir.
# Programı ~/.local/share/yeni-nesil-cafer-app'e kopyalar, uygulama menüsüne ve masaüstüne kısayol ekler.
set -euo pipefail
KAYNAK="$(cd "$(dirname "$0")" && pwd)/program"
HEDEF="${XDG_DATA_HOME:-$HOME/.local/share}/yeni-nesil-cafer-app"
ESKI="${XDG_DATA_HOME:-$HOME/.local/share}/yerel-asistan-app"  # 2.2'ye kadarki kurulum: yeni kurulumdan sonra silinir
yaz() { printf '  \033[33m%s\033[0m\n' "$*"; }
hata() { printf '\n  \033[31m%s\033[0m\n' "$*"; exit 1; }

printf '\n  YENİ NESİL CAFER · kurulum\n\n'
[ -f "$KAYNAK/main.py" ] || hata "Kurulum dosyaları eksik. Arşivi tamamen çıkarıp kur.sh'ı çıkan klasörden çalıştır."
INTERNET=0
[ -x "$KAYNAK/python/bin/python3" ] || INTERNET=1  # küçük paket: Python ve gerisi indirilecek
PY_URL="@PY_URL_LINUX@"
PY_SHA="@PY_SHA_LINUX@"

# eski kurulumdan açık kalan program ya da Ollama varsa kapat
pkill -f "^$HEDEF/" 2>/dev/null || true
pkill -f "^$ESKI/" 2>/dev/null || true

yaz "Program kopyalanıyor: $HEDEF"
if [ "$INTERNET" = 0 ]; then
    rm -rf "$HEDEF/.venv" "$HEDEF/python" "$HEDEF/ollama"  # eski sürümün kalıntıları (tam paket yenilerini getirir)
fi
mkdir -p "$HEDEF"
cp -a "$KAYNAK/." "$HEDEF/"
PY="$HEDEF/python/bin/python3"

if [ "$INTERNET" = 1 ]; then  # önce taşınabilir Python, sonra gerisini o indirir (kurulu olan yeniden inmez)
    if [ "$(cat "$HEDEF/python/.surum" 2>/dev/null)" != "$PY_URL" ]; then
        yaz "Python indiriliyor (~35 MB)…"
        ARSIV="$HEDEF/kurulum/python.tar.gz"
        mkdir -p "$HEDEF/kurulum"
        if command -v curl >/dev/null; then
            curl -fL --retry 5 --retry-delay 3 -C - -o "$ARSIV" "$PY_URL" || hata "Python indirilemedi. İnterneti denetleyip kur.sh'ı yeniden çalıştır."
        else
            wget -c -O "$ARSIV" "$PY_URL" || hata "Python indirilemedi. İnterneti denetleyip kur.sh'ı yeniden çalıştır."
        fi
        echo "$PY_SHA  $ARSIV" | sha256sum -c --quiet - || { rm -f "$ARSIV"; hata "Python doğrulanamadı (SHA-256); kur.sh'ı yeniden çalıştır."; }
        rm -rf "$HEDEF/python"
        tar -xzf "$ARSIV" -C "$HEDEF" && rm -f "$ARSIV"
        echo "$PY_URL" > "$HEDEF/python/.surum"
    fi
    (cd "$HEDEF" && "$PY" -m asistan.bootstrap "$HEDEF") \
        || hata "Kurulum yarım kaldı. İnterneti denetleyip kur.sh'ı yeniden çalıştır; inenler korunur, kaldığı yerden sürer."
fi

yaz "Program denetleniyor…"
QT_QPA_PLATFORM=offscreen "$PY" -c "import PySide6.QtWidgets, httpx, anthropic, ddgs, bs4, keyring, psutil" 2>/dev/null \
    || hata "Programın parçaları yüklenemedi (Python denetimi başarısız)."

cat > "$HEDEF/yeni-nesil-cafer" <<SH
#!/usr/bin/env bash
cd "$HEDEF" && exec "$PY" main.py "\$@"
SH
chmod +x "$HEDEF/yeni-nesil-cafer"

yaz "Kısayollar oluşturuluyor…"
UYG="${XDG_DATA_HOME:-$HOME/.local/share}/applications"
mkdir -p "$UYG"
rm -f "$UYG/yerel-asistan.desktop"  # eski adlı kısayol
cat > "$UYG/yeni-nesil-cafer.desktop" <<DESK
[Desktop Entry]
Type=Application
Name=YENİ NESİL CAFER
Comment=Kişisel yapay zekâ asistanı
Exec=$HEDEF/yeni-nesil-cafer
Icon=$HEDEF/asistan/gui/assets/icon.png
Terminal=false
Categories=Utility;Development;
StartupWMClass=yeni-nesil-cafer
DESK
MASAUSTU="$(xdg-user-dir DESKTOP 2>/dev/null || echo "$HOME/Desktop")"
if [ -d "$MASAUSTU" ]; then
    rm -f "$MASAUSTU/yerel-asistan.desktop"
    cp "$UYG/yeni-nesil-cafer.desktop" "$MASAUSTU/"
    chmod +x "$MASAUSTU/yeni-nesil-cafer.desktop"
    gio set "$MASAUSTU/yeni-nesil-cafer.desktop" metadata::trusted true 2>/dev/null || true
fi

# gömülü temel model: sistemde çalışan bir Ollama varsa ona, yoksa paketteki Ollama ile internetsiz kurulur
if [ -f "$HEDEF/modeller/Modelfile" ]; then
    MODEL="$(cat "$HEDEF/modeller/MODEL")"
    OLLAMA="$HEDEF/ollama/bin/ollama"
    ADRES="${OLLAMA_HOST:-127.0.0.1:11434}"  # Ollama'nın kendi ayarı; sunucu ve istemci de bunu kullanır
    calisiyor() { "$PY" -c "import httpx; httpx.get('http://$ADRES/api/tags', timeout=2).raise_for_status()" 2>/dev/null; }
    SUNUCU=""
    if ! calisiyor; then
        "$OLLAMA" serve >/dev/null 2>&1 &
        SUNUCU=$!
        for _ in $(seq 30); do sleep 0.5; calisiyor && break; done
    fi
    if "$OLLAMA" list 2>/dev/null | awk '{print $1}' | grep -qx "$MODEL"; then
        yaz "Temel model ($MODEL) zaten kurulu."
        rm -f "$HEDEF/modeller/"*.gguf
    else
        yaz "Temel model ($MODEL) kuruluyor (internet gerekmez, 1-2 dakika)…"
        if (cd "$HEDEF/modeller" && "$OLLAMA" create "$MODEL" -f Modelfile >/dev/null 2>&1); then
            rm -f "$HEDEF/modeller/"*.gguf  # Ollama'ya kopyalandı: yer açılsın
        else
            yaz "Temel model şimdi kurulamadı; program ilk açılışta tekrar deneyecek."
        fi
    fi
    [ -n "$SUNUCU" ] && kill "$SUNUCU" 2>/dev/null || true
fi

if [ -d "$ESKI" ]; then  # eski adlı kurulum (Yerel Asistan); ayarlar ve sohbetler program açılınca yeni ada taşınır
    rm -rf "$ESKI"
    yaz "Eski adlı kurulum (Yerel Asistan) kaldırıldı; ayarların ve sohbetlerin korunuyor."
fi

echo
yaz "Kurulum bitti. Uygulama menüsünden ya da masaüstünden “YENİ NESİL CAFER”i aç."
yaz "İlk açılışta sistemini tarayıp sana uygun modelleri önerecek (internet paketinde modeller o zaman iner)."
