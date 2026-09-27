# YAPILACAKLAR — Ek Aşamalar (K serisi: Kademeli + Bulut)

> Bu dosyayı mevcut `YAPILACAKLAR.md`'nin **sonuna** yapıştır (ya da ayrı dosya olarak bırak; `/asama` komutu ikisine de bakar). Mevcut aşamalarınla çakışan bir madde varsa (ör. "bulut sunucu", "sınav seti", "şema kısıtlı araç seçimi") o maddeyi buradaki aşamaya taşı, ikisini birden bırakma.
>
> Kural: **bir oturum = bir aşama.** Aşama bitmeden sonrakine geçme. `/kontrol` yeşil olmadan aşama bitmiş sayılmaz.

---

## Aşama K0 — Hazırlık ve mevcut durum haritası
**Hedef:** Kod değişmeden, neyin var neyin yok olduğunu bilmek.

- [ ] `cafer-plan` paketi repoya kuruldu (`docs/`, `.claude/`, bu dosya)
- [ ] `CLAUDE_EKLENTI.md` içeriği `CLAUDE.md`'ye işlendi, `CLAUDE_EKLENTI.md` silindi
- [ ] `NOTLAR/MEVCUT_DURUM.md` yazıldı: mevcut modüller, giriş noktaları, mevcut araçlar (dosya/komut/python/web/tarayıcı), sağlayıcılar, ayar mekanizması, test durumu
- [ ] `docs/MIMARI.md` §2 hedef yapısı ile mevcut yapı arasındaki fark tablosu (`MEVCUT_DURUM.md` içinde)
- [ ] Mimari ihlaller listelendi (çekirdek/arayüz karışıklığı, gömülü model adları, onaysız kurulum/silme)
- [ ] `git tag v-k0-baslangic` atıldı (geri dönüş noktası)

**Bitti sayılır:** `MEVCUT_DURUM.md` var, hiçbir kod değişmedi, `/kontrol hizli` mevcut durumu raporladı (kırmızı olabilir — kayıt altında olması yeter).

---

## Aşama K1 — Çekirdek / arayüz ayrımı
**Hedef:** `asistan/cekirdek/` arayüz bilmez; masaüstü sadece çekirdeği çağırır.

- [ ] `asistan/cekirdek/` ve `asistan/arayuz/masaustu/` klasörleri oluşturuldu
- [ ] `ayar.py` tek ayar kaynağı (`ayar.toml` + `CAFER_*` env) — mevcut ayar okuma buraya taşındı, eski yol çalışır
- [ ] Sağlayıcı arayüzü `saglayici/temel.py` (`sohbet`, `akis`, `saglik`, `maliyet`); mevcut Ollama/Claude/OpenAI-uyumlu/CLI-ajan kodu bu arayüze taşındı
- [ ] Mevcut araçlar (dosya, komut, Python, web) çekirdeğe taşındı; UI'daki iş mantığı kalmadı
- [ ] Masaüstü UI çekirdeği `import` ederek çalışıyor; kullanıcı açısından hiçbir şey değişmedi
- [ ] `testler/test_cekirdek_ayrimi.py`: çekirdekte Qt import'u yok (grep tabanlı test)
- [ ] Eski modül yolları için geçici uyumluluk (`from asistan.eski import X` → uyarı + yeni yola yönlendirme), bir sonraki sürümde kaldırılacak notu

**Bitti sayılır:** Masaüstü uygulaması eskisi gibi açılıp sohbet ediyor; `/kontrol` 2, 3, 6 yeşil.

---

## Aşama K2 — Donanım profili ve kademe
**Hedef:** Program açılışta kendini tanır; kademe kararı görünür ve kilitlenebilir.

- [ ] `cekirdek/profil.py`: CPU, RAM, GPU/VRAM (nvidia-smi → torch → Vulkan/Metal), disk, ağ, Ollama durumu → `.cafer/profil.json` (`docs/SEMALAR.md` §4)
- [ ] Kademe hesabı `docs/MIMARI.md` §3 eşikleriyle; `ayar.toml → kademe_kilidi` ölçümü ezer
- [ ] `ayar/modeller.json` oluşturuldu (kademe başına yerel/bulut listeleri + roller); **kodda model adı kalmadı**
- [ ] `cafer profil` CLI komutu (ya da `python -m asistan profil`)
- [ ] Masaüstünde durum çubuğunda kademe + tıklayınca profil özeti ve kilitleme seçeneği
- [ ] Kademe `dusuk` iken ağır özellikler (embedding, tarayıcı otomasyonu, uzun bağlam) devre dışı ve UI'da "bu kademede kapalı" olarak görünür
- [ ] Testler: sahte donanım verileriyle 4 kademe için kademe hesabı

**Bitti sayılır:** `/profil` bu makinede doğru kademeyi veriyor ve gerçek donanımla uyuşuyor; `/kontrol` 7 (model adı) yeşil.

---

## Aşama K3 — Model yönlendirici ve yedekleme zinciri
**Hedef:** Her adım için "hangi model, neden" kararı; başarısızlıkta otomatik yükselme.

- [ ] `cekirdek/yonlendirici.py`: `docs/MIMARI.md` §4 kural sırası (çevrimdışı → gizlilik → görev türü → kademe → zincir)
- [ ] Sağlayıcı sağlık kontrolü 5 dk önbellek; sağlıksız sağlayıcı zincirden düşer
- [ ] Yedekleme zinciri: zaman aşımı / 2 başarısızlık → üst seviye; zincir sonu → hata analizine devret
- [ ] Bulut maliyet tavanı (`ayar.toml → [bulut]`); aşımda kullanıcıya sor
- [ ] Karar `secim = {saglayici, model, neden}` olarak dönüyor ve UI'da görünüyor
- [ ] Gizlilik modu `yerel | karma | bulut` ayarı ve UI anahtarı
- [ ] Testler: sahte sağlayıcılarla her kural için en az bir senaryo; zincir yükselme senaryosu

**Bitti sayılır:** Sohbet ekranında her cevabın yanında "ollama/x — neden: …" görünüyor; Ollama kapatılınca bulut varsa buluta, yoksa "çevrimdışı" mesajına düşüyor.

---

## Aşama K4 — Görev motoru (Anla → Planla → Uygula → Doğrula)
**Hedef:** Çok adımlı istekler planlanır, adım adım koşar, kaldığı yerden devam eder.

- [ ] `cekirdek/semalar/gorev.json` (JSON Schema) — `docs/SEMALAR.md` §2 ile birebir
- [ ] `gorev/anlayici.py`: niyet, kısıtlar, belirsizlikler, gereken/eksik yetenekler; belirsizlik yüksekse tek soru
- [ ] `gorev/planlayici.py`: şema kısıtlı plan üretimi (varsa mevcut "şema kısıtlı araç seçimi" aşamasının kodu buraya taşınır); şemaya uymayan plan → 1 düzeltme turu → yine uymuyorsa `model_yetersiz`
- [ ] `gorev/yurutucu.py`: adım koşma, `{{adim_N.sonuc}}` çözümleme, checkpoint, `onay_gerekli` adımlarda bekleme
- [ ] `gorev/dogrulayici.py`: `basari_olcutu` kontrolü (kural tabanlı + gerekirse `hizli` modele sor)
- [ ] `gorev/durum.py`: SQLite görev deposu; "yarım görevler" listesi; "devam et"
- [ ] `cafer gorev "…"` CLI; masaüstünde Görevler sekmesi (liste, adım durumu, onay düğmesi)
- [ ] Testler: sahte yeteneklerle 3 adımlı görev; ortada kapatıp devam ettirme; doğrulama başarısız → tekrar deneme

**Bitti sayılır:** "Çalışma klasöründeki .txt dosyalarını say, en büyüğünü özetle" gibi 2–3 adımlı bir istek plan olarak görünüyor, adım adım koşuyor, program kapatılıp açılınca devam ediyor.

---

## Aşama K5 — Yetenek kayıt defteri
**Hedef:** Planlayıcı yalnızca manifestli yetenekleri çağırır; mevcut araçlar yeteneğe dönüştü.

- [ ] `cekirdek/semalar/manifest.json` (JSON Schema) — `docs/SEMALAR.md` §1
- [ ] `yetenek/kayit.py`: `yetenekler/*/manifest.json` tarama, doğrulama, aktif/pasif listeleme (gereksinim karşılanmıyorsa pasif)
- [ ] `yetenek/calistirici.py`: `calistir(girdi, baglam)` çağrısı; `sandbox: true` ise ayrı venv + zaman aşımı + izin kontrolü
- [ ] Mevcut araçlar yeteneğe dönüştürüldü: `dosya_listele`, `dosya_oku`, `dosya_yaz`, `dosya_tasi`, `komut_calistir`, `python_calistir`, `web_arama`, `web_oku`, (varsa) `tarayici`
- [ ] Planlayıcı yetenek listesini **manifestlerden** okuyor; elle liste yok
- [ ] Masaüstünde Yetenekler sekmesi: aktif/pasif, izinler, kaynak, güvenilir mi
- [ ] `/yetenek-ekle` komutu ile bir deneme yeteneği eklendi ve planlayıcı onu kullandı
- [ ] Testler: manifest doğrulama (bozuk manifest pasif), sandbox zaman aşımı, izin dışı erişim engeli

**Bitti sayılır:** `/kontrol` 8 tüm yetenekler için yeşil; K4'teki görev artık yetenekler üzerinden koşuyor.

---

## Aşama K6 — Hata analizi ve kendini genişletme
**Hedef:** Yapamadığı işi sınıflandırır; bağımlılık kurar; yetenek üretir; hepsi onaylı ve sandbox'lı.

- [ ] `analiz/hata.py`: 8 sınıf için desen tabanlı sınıflandırıcı + eylem tablosu (`docs/MIMARI.md` §7); bilinmeyen → `hizli` modele sor
- [ ] `guvenlik.py` + `ayar/guvenlik.toml`: `kurulum`, `ag`, `dosya_silme`, `sandbox_zaman_asimi_sn`; kaynak allowlist
- [ ] `yetenek/yukleyici.py`: pip / winget / apt / brew ile kurulum; politika `sor` ise onay kuyruğuna
- [ ] `yetenek/uretici.py`: eksik yetenek → manifest yazdır → kod ajanı ile `calistir.py` + test üret → sandbox test → onay → kayıt (`kaynak: uretildi`, `guvenilir: false`); 3 tur sınırı
- [ ] Yürütücü ↔ hata analizi bağlantısı: başarısız adım → sınıf → eylem → adımı tekrar / kullanıcıya sor / vazgeç
- [ ] Onay kuyruğu: masaüstünde ve (K8 sonrası) web'de "bekleyen onaylar"
- [ ] `NOTLAR/HATALAR.md` başlatıldı; `/hata-analiz` komutu sınıflandırıcıya desen ekleyebiliyor
- [ ] Testler: her sınıf için sahte hata → doğru eylem; üretici sahte kod ajanıyla uçtan uca; sandbox'ta yasak erişim engellendi

**Bitti sayılır:** "Bu PDF'in tablolarını Excel'e çıkar" gibi mevcut yeteneği olmayan bir istekte program eksik yeteneği söylüyor, onay isteyip yetenek üretiyor, test ediyor, sonra görevi tamamlıyor. `pip` olmayan bir modül hatasında onay isteyip kuruyor.

---

## Aşama K7 — Ölçüm, sınav seti ve kademe otomatik ayarı
**Hedef:** Program kendi hızını ve başarısını ölçer; kademe gerçeğe göre kayar.

- [ ] `analiz/olcum.py`: model başına tok/sn, ilk-token, başarı oranı (doğrulayıcıdan), süre; `profil.json → benchmark`
- [ ] İlk kullanımda 30 sn benchmark; `/profil benchmark` ile elle
- [ ] Kademe otomatik düşürme/yükseltme kuralı + kullanıcıya bildirim + kilit varsa dokunma
- [ ] `testler/sinav/`: mevcut sınav seti kademe etiketlendi (hangi görev hangi kademede beklenir); `cafer sinav --kademe orta` koşar, başarı tablosu üretir
- [ ] Sınav sonuçları yönlendirme tablosuna geri besleniyor (kademe × görev türü → tercih edilen rol)
- [ ] Modeller sekmesi: `modeller.json` listesi, ölçümler, "varsayılanı değiştir"; "listeyi yenile" düğmesi (`modeller.json`'u katalogdan/elle güncelleme)

**Bitti sayılır:** Sınav tablosu üretiliyor; küçük bir modeli yavaşlatınca (ya da sahte ölçümle) kademe düşüyor ve bildiriyor.

---

## Aşama K8 — Sunucu modu (web + telefon)
**Hedef:** Aynı paket sunucuda çalışır; telefondan PWA ile kullanılır; bilgisayar kapalıyken görevler sürer.

- [ ] `arayuz/web/`: FastAPI; uç noktalar `/saglik`, `/gorev` (POST/GET), `/onaylar`, `/yetenekler`, `/profil`, `/sohbet` (SSE akış)
- [ ] Tek kullanıcı token kimliği (`CAFER_TOKEN`); yanlış/eksik → 401
- [ ] PWA: `manifest.webmanifest`, service worker, "ana ekrana ekle"; sohbet + görevler + onaylar ekranları (sade, masaüstüyle aynı retro dil)
- [ ] `cafer sunucu --port` giriş noktası; masaüstü kodu yüklenmez (`/sunucu` bunu doğrular)
- [ ] `sunucu/Dockerfile` (python:3.12-slim, sadece çekirdek + web), `docker-compose.yml` (cafer-web + isteğe bağlı `ollama` servisi GPU profiliyle), `Caddyfile`, `.env.ornek`
- [ ] `docs/SUNUCU_KURULUM.md`: 2 vCPU/4 GB VPS'e 10 adımda kurulum; alan adı + HTTPS; yedekleme (`.cafer/` klasörü)
- [ ] Testler: uç nokta testleri (TestClient), token, SSE akışı

**Bitti sayılır:** `/sunucu docker` tüm kontrolleri geçiyor; telefondan aynı ağda PWA açılıp bir görev başlatılıyor.

---

## Aşama K9 — Uzak mod ve senkron
**Hedef:** Masaüstü istemci sunucuya bağlanabilir; görevler ve ayarlar tek yerde.

- [ ] Masaüstünde "uzak sunucu" ayarı: URL + token; açıkken görev deposu ve sohbet sunucudan
- [ ] Çevrimdışıyken yerel kuyruk; bağlanınca senkron (basit: son-yazan-kazanır, çakışma listesi)
- [ ] Bildirim yeteneği (`bildirim_gonder`: ntfy ya da Telegram bot) — onay bekleyen görevlerde telefona bildirim
- [ ] Sunucudaki onay masaüstünde, masaüstündeki onay sunucuda görünür
- [ ] Testler: uzak mod ile yerel mod aynı testleri geçiyor (parametrize)

**Bitti sayılır:** Bilgisayar kapalıyken telefondan başlatılan görev, bilgisayar açılınca masaüstünde görünüyor.

---

## Aşama K10 — Kurulum, sadeleştirme ve sürüm
**Hedef:** Düşük sistemde bile tek komutla kurulup çalışan, sade bir program.

- [ ] Kurulum sihirbazı (ilk açılış): profil → kademe → "yerel model kur / bulut anahtarı gir / ikisi" → gizlilik modu → bitti
- [ ] Tek komut kurulum: `pipx install …` ya da platform yükleyicisi (Windows için `.exe`, mevcut güncelleme mekanizmasıyla uyumlu)
- [ ] Kademe `dusuk` profili: UI'da sadece sohbet + görevler + ayarlar; diğer sekmeler gizli ama açılabilir
- [ ] Başlangıç süresi ölçümü: `dusuk` kademede < 3 sn hedefi; ağır import'lar lazy
- [ ] Sürüm notu ve `CHANGELOG.md`; in-app güncelleme K serisi ile uyumlu
- [ ] `docs/MIMARI.md` gerçekle güncellendi (yapılamayan/değişen kararlar not edildi)

**Bitti sayılır:** Temiz bir sanal makinede (ya da düşük kademe kilidiyle) kurulum sihirbazından geçip bulut anahtarıyla bir görev tamamlanıyor; `/kontrol` tamamen yeşil.
