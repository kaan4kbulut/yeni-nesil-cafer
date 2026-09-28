# Değişiklikler

Biçim: sürüm → başlıklar. Tarihli deneyler `NOTLAR/`, kalıcı kurallar `CLAUDE.md`.

## 3.1 — 2026-09-29 (inceleme, temizlik, "yazdı ama yapmadı", güç ve donanım farkındalığı)

- **Kod incelemesi ve 50'den fazla düzeltme:** üç bağımsız incelemede bulunan güvenlik, onay, sandbox, ayar, donma ve
  bulut sorunları giderildi. Onay listesi artık salt okunur işlemlerle sınırlı; sırlar (anahtar dosyaları, bulut ayarı)
  hiçbir araçtan okunamaz; bozuk ayar dosyası kenara alınıp program yine açılır; ekran kartı ve model listesi
  denetimleri arayüzü dondurmaz; uzun bekleyen istekler "Durdur" ile hemen kesilir.
- **Ekran kartına sığan bağlam:** bağlam boyutu ölçülen boş belleğe göre seçilir; 12 GB kartta 14B model artık işlemciye
  taşmaz, cevaplar zaman aşımına düşmez.
- **"Yapıyorum" deyip yapmama sona erdi:** model bir iş isteğinde araç çalıştırmadan yalnızca anlatırsa bir kez uyarılır;
  yine yapmazsa iş görev motoruna ya da daha güçlü bir modele devredilir, o da yoksa tek satırla dürüstçe söylenir.
  "Araç kullanmak ister misiniz?" gibi izin soruları soru sayılmaz. Türkçe olmayan cevap yeniden yazdırılır.
  Bu uyarı metinleri sohbette değil sağ paneldeki durum satırında görünür.
- **Soru sorma aracı:** model sonucu belirleyen bir şeyi soracaksa tek soru sorar, sohbet "cevap bekliyor" olur; sonraki
  mesajın cevap olduğu bilinir.
- **🐞 sorun düğmesi:** sohbet penceresinde tek tıkla sorun raporu (masaüstündeki YENİ NESİL CAFER klasörüne) ve
  geliştiriciye verilecek cümle panoya.
- **Sürüm sayfası sade:** platform başına tek kurulum dosyası, "Hangisini indireyim?" tablosu, Linux'ta `--install` ile
  menü ve masaüstü kısayolu; eski ve ön sürümler kaldırıldı. Kurulum sırasında model indirmesi yarıda kalırsa kaldığı
  yerden sürer.
- **Testler ve depo:** 824 test, hiçbiri atlanmıyor; deney notları arşivlendi, paketleme betikleri tek klasörde.
- **Güç ve donanım farkındalığı:** dizüstü pilde mi fişte mi olduğunu, ekran kartının uyuyup uyumadığını ve modelin
  kartın yerine işlemciye düşüp düşmediğini fark eder; hızlı bir ölçümle o an en uygun ayarı seçer. Donanım profili
  penceresinde "Şimdi ölç", "Otomatik uyarla" ve onaylı Ollama yeniden başlatma düğmeleri var; sohbet ya da görev
  sürerken ayar değişmez.
- **Görev motoru sohbette varsayılan açık:** çok adımlı işler önce plana bölünüp adım adım yapılır ve doğrulanır;
  ayarlardan kapatılırsa eski yol aynen çalışır.

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
