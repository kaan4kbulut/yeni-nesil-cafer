
## K0 — Mevcut durum haritası (2026-09-27 23:07)
- [ ] NOTLAR/MEVCUT_DURUM.md'yi oku: projeni doğru anlamış mı? Mimari ihlal listesi mantıklı mı?

## K1 — Çekirdek / arayüz ayrımı (2026-09-28 00:08)
- [ ] Masaüstü uygulamasını aç: sohbet, dosya aracı, komut çalıştırma eskisi gibi mi?
- [ ] K2: 7 madde açık kaldı; NOTLAR/ altındaki K2 notunu oku, gerekirse `/asama K2` ile bitirt.

## K2 — Donanım profili ve kademe (2026-09-28 01:31)
- [ ] Durum çubuğundaki kademe laptop'unla uyuşuyor mu? (NOTLAR/<tarih>-K2.md ve .cafer/profil.json)
- [ ] NOTLAR/MODELLER_ONERI.md'ye bak, ayar/modeller.json'daki geçici seçimleri beğenmediysen değiştir, "gecici" alanını sil.

## K3 — Model yönlendirici (2026-09-28 01:54)
- [ ] Programı aç: cevapların yanında 'sağlayıcı/model — neden' görünüyor mu?
- [ ] Ollama'yı kapat, sohbet et → bulut anahtarı varsa buluta düşmeli, yoksa 'çevrimdışı' demeli.
- [ ] Gizlilik modunu 'yerel' yap → bulut kullanılmamalı. Sonra 'karma'ya al.
- [ ] **K4 DURDU:** claude 124 ile çıktı: zaman aşımı. Limit ise dolunca `python otomatik.py` yeter; kaldığı yerden sürer.

## K4 — Görev motoru (2026-09-28 03:24)
- [ ] Programa yaz: 'Çalışma klasöründeki .txt dosyalarını say, en büyüğünü özetle.' Plan görünüyor mu?
- [ ] Adım 1 bitince programı kapat/aç, 'devam et' de → kaldığı yerden sürüyor mu?

## K6 — Hata analizi ve kendini genişletme (2026-09-28 sabah)
- [ ] Bir yeteneğin pip paketini kaldır, o yeteneği kullan → görev "onay bekliyor: kurulum pip:…" demeli; onaylayınca kurup adımı tekrar etmeli.
- [ ] Yeteneği olmayan bir iş iste ("şu PDF'in tablolarını Excel'e çıkar") → "… adında yetenek yok; üreteyim mi?" sorusu; onaylayınca üretip (sandbox testi) görevi bitirmeli. Yeni yetenek Yardım → Yetenekler'de `[üretildi, güvenilmez]`.
- [ ] `ayar.toml`'a `[guvenlik] kurulum = "yasak"` yaz → kurulum "politikayla kapalı" diye reddedilmeli.

## K7 — Ölçüm ve sınav (2026-09-28 sabah)
- [ ] Yardım → Modeller…: tok/sn ve başarı sütunları dolu mu? "Varsayılan yap" listeyi değiştiriyor mu (DATA_DIR/modeller.json)? "Listeyi yenile" önerilen satırını dolduruyor mu?
- [ ] `python -m asistan profil --benchmark` koş; küçük model yavaşsa (< 3 tok/sn) durum çubuğunda "📐 Kademe … → …" bildirimi ve profil özetinde "hız ölçümüyle ayarlandı".
- [ ] `python testler/sinav/calistir.py --kademe dusuk --tekrar 1` → RAPOR.md'de "kademe × görev türü" tablosu; sonda "Yönlendirmeye geri beslendi" satırı.

## K8 — Sunucu modu (2026-09-28 sabah)
- [ ] `CAFER_TOKEN=test123 python -m asistan sunucu --host 0.0.0.0 --port 8765` → telefonu aynı Wi-Fi'ye bağla, `http://<bilgisayar-ip>:8765` aç, anahtarı gir, "Ana ekrana ekle"; sohbette bir soru sor, görevler'de bir iş başlat, onaylar'da onayla.
- [ ] `docker compose -f sunucu/docker-compose.yml up --build -d` → `./sunucu/dogrula.sh http://127.0.0.1:8765 <anahtar>` hepsi ✓; imaj boyutunu not et.
- [ ] VPS'e SSH ile gir, `docs/SUNUCU_KURULUM.md` adımları; `sunucu/kur.sh` iki kez çalıştırınca bozmuyor mu?
