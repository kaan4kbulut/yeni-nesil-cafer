# Sunucu kurulumu (K8) — web + telefon (PWA), bilgisayar kapalıyken de çalışan görevler

Tek kurulum belgesi budur; `sunucu/BENIOKU.md` yalnızca buraya yönlendirir. Aynı paket sunucuda çalışır
(`python -m asistan sunucu`): FastAPI + PWA, masaüstü kodu (PySide6) yüklenmez; Telegram botu ve bilgisayara iş bırakma
kuyruğu (`cloud_server`) aynı süreçte sürer.

**Ucuz VPS yeter:** 2 vCPU / 4 GB (Hetzner CX22/CX23, Oracle Always Free A1). Ekran kartı yoksa çıkarım bulut
API'sinde (`ANTHROPIC_API_KEY` / OpenAI uyumlu) ya da sunucudaki küçük Ollama modelinde (yavaş).

## 10 adımda (Docker + Caddy, alan adı + HTTPS)

1. **Sunucu aç:** Ubuntu 24.04, 2 vCPU / 4 GB. Alan adının A kaydını sunucu IP'sine yönlendir (`cafer.ornek.com`).
2. **SSH ile gir**, Docker kur: `curl -fsSL https://get.docker.com | sh` (bir kez).
3. **Paketi kopyala:** bilgisayarında `paketleme/bulut_paketi.sh` → `scp dist/yeni-nesil-cafer-bulut.tar.gz sunucu:` →
   sunucuda `tar xzf yeni-nesil-cafer-bulut.tar.gz && cd yeni-nesil-cafer-bulut`.
4. **Ayarlar:** `cp sunucu/.env.ornek sunucu/.env`; `CAFER_TOKEN` (uzun rastgele: `python3 -c "import secrets;
   print(secrets.token_urlsafe(32))"`), `CAFER_ALAN_ADI`, bulut anahtarın (`ANTHROPIC_API_KEY`) — dosya git'e girmez.
5. **Başlat:** `docker compose -f sunucu/docker-compose.yml up -d --build` (GPU'lu sunucuda `--profile gpu` Ollama'yı da
   açar; `.env`'de `CAFER_SAGLAYICI_OLLAMA_URL=http://ollama:11434`).
6. **Doğrula:** `./sunucu/dogrula.sh http://127.0.0.1:8765 <CAFER_TOKEN>` → hepsi ✓ (servis, `/saglik`, 401, PWA).
7. **HTTPS:** Caddy alan adı için sertifikayı kendisi alır; tarayıcıda `https://cafer.ornek.com` → anahtarı gir.
8. **Telefon:** Aynı adresi telefonda aç → tarayıcı menüsü → **Ana ekrana ekle** (PWA). Sohbet · görevler · onaylar.
9. **Masaüstünü bağla:** Ayarlar → Bulut asistan → adres `https://cafer.ornek.com`, anahtar = `CAFER_TOKEN` →
   "Bağlantıyı dene". Hafıza dakikada bir eşitlenir; sunucunun bilgisayara bıraktığı işler ☁ ile görünür.
10. **Telegram (isteğe bağlı):** `docker compose exec cafer-web python -c "..."` yerine veri hacmindeki
    `bulut.json`'a `telegram_token` yaz (`docker compose restart cafer-web`), bota `/baglan <kod>`.

Alan adı yoksa: 5. adımda `caddy` servisini çıkar, portu `8765:8765` yap ve yalnızca **Tailscale** ağından eriş
(sunucuya `curl -fsSL https://tailscale.com/install.sh | sh; tailscale up`); internete açık HTTP kullanma.

## Docker'sız (systemd) yol

`sudo ./sunucu/kur.sh` (Ubuntu 22.04/24.04, idempotent): Python venv + `requirements-sunucu.txt`, Ollama (küçük
model), Tailscale, `yeni-nesil-cafer-bulut` servisi (`python -m asistan sunucu --host <tailscale-ip> --port 8765`).
Anahtar `bulut.json → token` (ilk açılışta üretilir, ekrana yazılır). `./sunucu/dogrula.sh` ile denetle.

## Yedekleme

Bütün durum tek klasörde: Docker'da `cafer-veri` hacmi (`docker run --rm -v cafer-veri:/veri -v $PWD:/yedek alpine
tar czf /yedek/cafer-veri.tgz /veri`), systemd'de `/var/lib/yeni-nesil-cafer`. İçinde: `gorevler.db` (görevler,
onaylar), `hafiza.db`, `bulut.db`/`bulut.json` (kuyruk, Telegram), `olcum.json`, `profil.json`, üretilen yetenekler.
Geri yükleme: klasörü/hacmi geri koy, servisi yeniden başlat.

## Güvenlik notları

- Tek kullanıcı, tek anahtar; anahtarsız yalnızca `/saglik` ve PWA dosyaları açılır.
- Web sohbeti bilgisayara erişemez (`cloud_server` kuralı); değişiklik yapan işler görev motoruna gider ve her yazan
  adım **/onaylar**'da onay bekler (izin hattı `permissions.py`, politika `ayar/guvenlik.toml`).
- Sunucu kademesinde (`CAFER_GENEL_KADEME_KILIDI=sunucu`) tarayıcı otomasyonu ve ağır motorlar kapalıdır.

## Sorun giderme

- `/saglik` 200 ama sohbet cevapsız: bulut anahtarı ya da Ollama yok → `docker compose logs cafer-web`.
- 401: `Authorization: Bearer <CAFER_TOKEN>`; PWA'da anahtarı yeniden gir (tarayıcı verisini temizle).
- Onay bekleyen görev ilerlemiyor: PWA → onaylar → onayla; ya da `POST /gorev/<id>/onayla {"evet": true}`.
