# Değişiklikler

Biçim: sürüm → başlıklar. Tarihli deneyler `NOTLAR/`, kalıcı kurallar `CLAUDE.md`.

## 3.0 — 2026-09-28 (K serisi: kademeli + bulut mimarisi)

- **Sürüm sayfası:** platform başına tek kurulum dosyası (`…-Linux.AppImage` / `…-Windows-Kurulum.exe` / `…-macOS.dmg`),
  notun başında "Hangisini indireyim?" tablosu; AppImage `--install` ile masaüstü kısayolu; güncelleyici paketi
  `guncelleyici-icin-…` önekli (insan için değil).
- **`kullaniciya_sor` aracı** (sohbet yolu): model sonucu belirleyen bir şeyi soracaksa tek soru sorar, tur biter, sohbet
  "cevap bekliyor" olur; sonraki mesaj aynı bağlamla cevap olarak gider (motorun `anlayici.soru`su ile aynı arayüz).
- **Çekirdek / arayüz ayrımı** (`asistan/cekirdek/`): ayar (`ayar.toml` + `CAFER_*`), sağlayıcılar (Ollama, Claude,
  OpenAI uyumlu, CLI ajanları), araçlar, istek; çekirdekte Qt/FastAPI yok.
- **Donanım profili ve kademe** (`dusuk/orta/yuksek/sunucu`): açılışta ölçülür, kilitlenebilir; hız ölçümüyle
  (benchmark) kendini ayarlar; model adları yalnızca `ayar/modeller.json`.
- **Model yönlendirici**: rol (hızlı/yönetici/kod), sağlık önbelleği, yedekleme zinciri, bulut maliyet tavanı
  (gerçek `usage`), gizlilik modu, sınav sonuçlarından geri besleme.
- **Görev motoru**: anla → planla → uygula → doğrula; `gorevler.db` ile devam; onaylar tek izin hattından.
- **Yetenek kayıt defteri**: manifestli yetenekler, sandbox (ayrı venv, beyaz listeli ortam, ağsız, zaman aşımı),
  Yardım → Yetenekler; tarayıcıda ürün listesi okuma.
- **Hata analizi ve kendini genişletme**: 8 hata sınıfı → eylem; eksik paket kurma ve yetenek üretme (onaylı,
  sandbox testli); güvenlik politikası `ayar/guvenlik.toml`.
- **Ölçüm ve sınav**: kademe etiketli sınav seti, `python -m asistan sinav --kademe`; Modeller penceresi.
- **Sunucu modu**: FastAPI + PWA (`python -m asistan sunucu`), Docker/Caddy, `docs/SUNUCU_KURULUM.md`.
- **Uzak mod ve senkron**: görevler sunucuyla eşitlenir (son yazan kazanır), ntfy/Telegram bildirimi.
- **Kurulum ve sadeleştirme**: kurulum sihirbazında kademe → yerel/bulut/ikisi → gizlilik; düşük kademede sade
  arayüz; model seçimi Yardım → Gelişmiş altında; `pipx install .` ile `cafer` komutu; açılışta anthropic SDK'sı
  tembel yüklenir.
- Güvenlik: alt süreçlere beyaz listeli ortam (API anahtarları geçmez), `ayarlar.json`/ayar klasörü okunamaz,
  web okumada yerel ağ engeli, sansürsüz kip yalnızca sınavı geçen modellerle.

## 2.7 ve öncesi

`NOTLAR/2026-09-26.md`, `NOTLAR/2026-09-27.md` ve `NOTLAR/mimari-ayrintilar.md`.
