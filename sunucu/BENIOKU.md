# YENİ NESİL CAFER · sunucu

Kurulum belgesi tek: **[docs/SUNUCU_KURULUM.md](../docs/SUNUCU_KURULUM.md)** (Docker + Caddy ile 10 adım, Docker'sız
`kur.sh` yolu, yedekleme, Telegram, sorun giderme).

Bu klasör: `Dockerfile`, `docker-compose.yml`, `Caddyfile`, `.env.ornek` (kopyalayıp doldur), `kur.sh` (systemd yolu,
idempotent), `dogrula.sh` (✓/✗ denetimi).

Bilgisayarın kapalıyken asistanına telefondan (PWA ya da Telegram) ulaşırsın. Sunucudaki kopya **bilgisayarına
erişemez**: dosyaların gereken işleri kuyruğa bırakır; bilgisayar açılınca programda ☁ ile görünür, "yap" dersen yerel
asistan yapar. Değişiklik yapan görev adımları telefonda **onaylar** sekmesinde bekler.
