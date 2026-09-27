# ADIMLAR — Elle yol (yedek)

> **Otomatik yol varken buna gerek yok:** repo kökünde `python otomatik.py` bütün bu adımları kendisi yapar. Bu dosya, otomatik sürücüyü kullanmak istemezsen ya da tek bir aşamayı elle sürdürmek istersen diye duruyor.

Her adımda yalnızca üç tür iş var:

- 🖥️ **Terminal** — komutu yaz, Enter.
- 🤖 **Claude Code** — kutudaki metni olduğu gibi yapıştır, Enter. Claude Code onay sorarsa (dosya yazma, komut çalıştırma) kabul et; **"onayımı bekle"** dediği yerlerde planı oku, "devam" ya da düzeltme yaz.
- 👀 **Kontrol** — senin bakacağın şey. Doğruysa kutucuğu işaretle, sonrakine geç. Yanlışsa aynı adımın sonundaki "takılırsan" satırını uygula.

Kurallar:
- Her ADIM ayrı bir Claude Code oturumu. Adım bitince `/clear` yaz.
- Bir adımı bitirmeden sonrakine geçme.
- Claude Code "bitti" dese bile 👀 kontrolünü sen yap.

Takılınca (her adımda geçerli):
- Hata çıktısı gördün → 🤖 `/hata-analiz` yazıp altına hatayı yapıştır.
- Claude Code plandan saptı → 🤖 `Dur. YAPILACAKLAR.md'de hangi K aşamasının hangi maddesindesin? Oraya dön.`
- Oturum uzadı, karıştı → `/clear` → 🤖 `/asama K<n>` (NOTLAR/'daki notundan devam eder).
- Testler kırmızı ama "bitti" diyor → 🤖 `Aşama bitmedi; /kontrol kırmızı. Kırmızıları düzelt, düzeltemediğin maddeyi [ ] bırak ve nedenini yaz.`

## İlerleme çubuğu ve bildirimler (ADIM 1'de kurulur)

Claude Code bir işe başlarken kaç adım süreceğini önceden bilmez; o yüzden "kesin yüzde / kalan dakika" diye bir şey yoktur. En yakını şu üçlü:

1. **Görev listesi** — `/asama` her aşamanın maddelerini Claude Code'un görev listesine yazar; Claude ilerledikçe maddeler terminalde işaretlenir. Bu, Claude Code'un kendi yerleşik özelliğidir.
2. **Durum çubuğu** (terminalin en altı) — `.claude/ilerleme/durum.py`: 
   `K3 ████████░░░░ 6/9 %66 │ ▶ yönlendirici testleri │ 23dk · ~11dk kaldı │ bağlam %31 │ Opus`
   Yüzde = biten madde / toplam madde. "~kaldı" = biten maddelerin ortalama süresi × kalan madde; kaba tahmindir, maddeler eşit değildir.
   "bağlam %" yükseldikçe oturum yavaşlar ve unutkanlaşır; %70'i geçince aşama bitmemişse `/clear` + `/asama K<n>` daha sağlıklıdır.
3. **Bildirim** — `.claude/ilerleme/bildir.py`: Claude cevabını bitirince ya da senden onay/soru beklediğinde masaüstüne balon bildirim + ses. Başka pencerede işine bakabilirsin.

Çubuk `aşama yok` diyorsa Claude görev listesi açmamıştır: 🤖 `Görev listesini aç (TaskCreate) ve maddeleri işaretleyerek ilerle.`

---

## ADIM 1 — Paketi kur (Claude Code kurar)

- [ ] 🖥️ `cafer-plan.zip` dosyasını **repo klasörünün köküne** kopyala. Açma, dokunma.
- [ ] 🖥️
  ```
  cd <repo-klasoru>
  git checkout -b k-serisi
  claude
  ```
- [ ] 🤖
  ```
  Repo kökünde cafer-plan.zip var. Sırayla:
  1. Zip'i aç. İçindeki cafer-plan/ klasörünün içeriğini repo köküne taşı: .claude/ zaten varsa birleştir (mevcut komut/ajan dosyalarımı silme, aynı ad varsa bana sor); docs/ zaten varsa dosyaları içine koy. Sonra zip'i ve boş cafer-plan/ klasörünü sil.
  2. CLAUDE_EKLENTI.md içeriğini CLAUDE.md'nin sonuna işle (CLAUDE.md parçalara bölünmüşse uygun parçaya). Sonra CLAUDE_EKLENTI.md'yi sil.
  3. YAPILACAKLAR_EK.md'deki K0–K10 aşamalarını YAPILACAKLAR.md'nin sonuna taşı. Mevcut planımdaki sınav seti, güçlü yönetici model, şema kısıtlı araç seçimi, bulut sunucu, UI sadeleştirme gibi maddeler K serisiyle çakışıyorsa ilgili K aşamasının içine "mevcut plandan taşındı" notuyla birleştir; çift madde bırakma. Sonra YAPILACAKLAR_EK.md'yi sil.
  4. BENIOKU.md'yi sil. ADIMLAR.md kalsın.
  5. İlerleme çubuğu ve bildirimleri kur: .claude/settings.ornek.json içeriğini .claude/settings.json ile birleştir (mevcut ayarlarımı ezme; hooks dizilerini ekle). Bu makinede Python komutu "python" mı "python3" mü, kontrol et ve komutları ona göre yaz. Sonra üç betiği test et: (a) echo '{"model":{"display_name":"test"},"context_window":{"used_percentage":12}}' | python .claude/ilerleme/durum.py → tek satır çıktı vermeli; (b) kaydet.py'ye sahte bir PostToolUse JSON'u ver, .cafer/ilerleme.json oluşmalı; (c) bildir.py'ye {"hook_event_name":"Stop","last_assistant_message":"deneme"} ver → masaüstünde bildirim çıkmalı (çıkmadıysa nedenini söyle, düzelt). Testten sonra .cafer/ilerleme.json'u sil. settings.ornek.json'u sil.
  6. .gitignore'a `.cafer/` ekle (yoksa oluştur).
  7. git add -A && git commit -m "K serisi: mimari doküman, komutlar, aşama planı, ilerleme çubuğu" && git tag v-k0-baslangic
  8. Bana repo ağacını (2 seviye) göster ve .claude/commands ile .claude/agents içindeki dosyaları listele. Hiçbir Python dosyasına dokunma (asistan/ altı).
  ```
- [ ] 👀 Claude'un listesinde `asama, kontrol, hata-analiz, yetenek-ekle, profil, sunucu` ve `mimar, denetci` var mı? Claude Code'da `/` yazınca `asama` görünüyor mu?
- [ ] 👀 Testte (c) bildirimi gördün mü? Görmediysen 🤖 `Bildirim çıkmadı. bildir.py'yi bu işletim sisteminde çalışan bir yöntemle düzelt ve tekrar test et.`
- [ ] 🖥️ `git tag` → `v-k0-baslangic` var mı.
- [ ] 🖥️ Claude Code'dan çık (`/exit`), tekrar `claude` yaz → terminalin altında `aşama yok · /asama K<n> ile başla` satırı görünmeli. Görünmüyorsa 🤖 `Durum çubuğu görünmüyor. statusLine ayarı proje settings.json'da geçerli olmuyorsa ~/.claude/settings.json'a taşı ve komutta mutlak yol kullan.`
- [ ] `/clear`

Takılırsan: `/` yazınca komutlar görünmüyorsa 🤖 `Claude Code sürümüm slash komutları .claude/skills/<ad>/SKILL.md biçiminde bekliyor olabilir. Kontrol et; öyleyse .claude/commands/*.md dosyalarını .claude/skills/<ad>/SKILL.md olarak taşı, içerik aynı kalsın.`

---

## ADIM 2 — Mevcut durum haritası (K0, kod değişmez)

- [ ] 🤖 `/asama K0`
- [ ] 👀 Terminalin altındaki çubuk `K0 ██░░░░ 1/6` gibi ilerliyor mu? İlerlemiyorsa 🤖 `Görev listesini aç (TaskCreate) ve maddeleri işaretleyerek ilerle.`
- [ ] 👀 `NOTLAR/MEVCUT_DURUM.md` oluştu mu? İçinde "mimari ihlaller" listesi var mı? Oku — projeni doğru anlamış mı? Yanlış anladığı yer varsa 🤖 `MEVCUT_DURUM.md'de şu yanlış: … Düzelt.`
- [ ] 🖥️ `git status` → hiçbir `.py` dosyası değişmemiş olmalı.
- [ ] 🤖 `commitle`
- [ ] `/clear`

---

## ADIM 3 — Çekirdek / arayüz ayrımı (K1) — en riskli adım

- [ ] 🤖
  ```
  mimar ajanını kullan: K1 (çekirdek/arayüz ayrımı) için plan çıkar. NOTLAR/MEVCUT_DURUM.md'yi temel al. Özellikle: hangi dosyalar nereye taşınacak, taşıma sırası, her adımdan sonra masaüstü uygulaması hâlâ açılıyor mu, geri dönüş yolu. Planı bana göster ve onayımı bekle.
  ```
- [ ] 👀 Planı oku. Anlamadığın yer varsa sor. Uygunsa 🤖 `Plan onaylandı.`
- [ ] 🤖 `/asama K1`
- [ ] 🤖 `denetci ajanıyla K1 değişikliğini denetle. Engelleyici varsa düzelt ve tekrar denetle; GEÇTİ alana kadar sürdür.`
- [ ] 👀 **Masaüstü uygulamasını kendin aç.** Sohbet et, dosya aracını kullan, bir komut çalıştır. Eskisi gibi mi? Değilse hatayı kopyala → 🤖 `/hata-analiz` + hata.
- [ ] 🤖 `commitle`
- [ ] `/clear`

---

## ADIM 4 — Donanım profili ve kademe (K2)

- [ ] 🤖 `/asama K2 onaysız`
- [ ] 🤖 `/profil benchmark`
- [ ] 👀 Kademe laptop'unla uyuşuyor mu (RAM, GPU/VRAM doğru okunmuş mu)? Tabloya bak.
- [ ] 🤖
  ```
  ayar/modeller.json'daki örnek model adlarını gerçek adlarla değiştireceğiz. Web'de araştır: şu an Ollama'da yaygın kullanılan, iyi puanlanan açık modellerden 3B, 7–8B, 14B ve 32B sınıfında ikişer aday; Claude ve OpenAI-uyumlu bulut sağlayıcılardan "ucuz-hızlı" ve "güçlü" rolleri için ikişer aday. Kademe × rol tablosu olarak göster, her adayın yanına tek satır neden. Dosyaya henüz yazma; ben seçeceğim.
  ```
- [ ] 👀 Tablodan seç. 🤖 `Seçimlerim: dusuk yerel …, orta yerel …, yuksek yerel …, bulut ucuz-hızlı …, bulut güçlü …. modeller.json'a yaz, güncelleme tarihini bugün yap.`
- [ ] 🤖 `/kontrol hizli`
- [ ] 🤖 `commitle`
- [ ] `/clear`

---

## ADIM 5 — Model yönlendirici (K3)

- [ ] 🤖 `/asama K3 onaysız`
- [ ] 👀 Programı aç. Cevapların yanında "ollama/… — neden: …" görünüyor mu?
- [ ] 👀 Ollama'yı kapat, sohbet et → bulut anahtarı girdiysen buluta düşmeli; girmediysen "çevrimdışı" demeli.
- [ ] 👀 Ayarlardan gizlilik modunu `yerel` yap, sohbet et → bulut kullanılmamalı. Sonra `karma`ya geri al.
- [ ] 🤖 `commitle`
- [ ] `/clear`

---

## ADIM 6 — Görev motoru (K4)

- [ ] 🤖
  ```
  mimar ajanıyla K4 için plan çıkar. Özellikle: mevcut "şema kısıtlı araç seçimi" kodu planlayıcıya nasıl taşınacak; SQLite görev deposu mevcut veri dosyalarıyla çakışıyor mu; program kapanıp açılınca devam etme nasıl çalışacak. Planı göster, onayımı bekle.
  ```
- [ ] 👀 Planı oku. 🤖 `Plan onaylandı.`
- [ ] 🤖 `/asama K4`
- [ ] 👀 Programa şunu yaz: *"Çalışma klasöründeki .txt dosyalarını say, en büyüğünü özetle."* Plan (adımlar) görünüyor mu? Adım 1 bitince **programı kapat, aç**, "devam et" de → kaldığı yerden sürüyor mu?
- [ ] 🤖 `denetci ajanıyla K4'ü denetle; GEÇTİ alana kadar düzelt.`
- [ ] 🤖 `commitle`
- [ ] `/clear`

---

## ADIM 7 — Yetenek kayıt defteri (K5)

- [ ] 🤖 `/asama K5`
- [ ] 🤖 `/yetenek-ekle saat_dilimi "Verilen şehir adı için şu anki saati ve UTC farkını döner. Girdi: sehir (string). Çıktı: saat (string), utc_fark (string). İzin: ag."`
- [ ] 👀 Programda Yetenekler sekmesi: `saat_dilimi` aktif mi? "İstanbul'da saat kaç?" deyince planlayıcı bu yeteneği seçiyor mu?
- [ ] 👀 ADIM 6'daki .txt görevini tekrar ver → artık yetenekler üzerinden koşuyor mu (adımlarda yetenek adları görünmeli)?
- [ ] 🤖 `commitle`
- [ ] `/clear`

---

## ADIM 8 — Hata analizi + kurulum (K6, birinci yarı)

- [ ] 🤖
  ```
  /asama K6 — sadece şu maddeleri yap: analiz/hata.py sınıflandırıcı, guvenlik.py + ayar/guvenlik.toml, yetenek/yukleyici.py, yürütücü↔hata analizi bağlantısı, onay kuyruğu, NOTLAR/HATALAR.md. uretici.py maddesini bu oturumda YAPMA, [ ] bırak.
  ```
- [ ] 👀 Test: bir yeteneğin pip bağımlılığını kaldır (Claude'a sor: 🤖 `Hangi yeteneğin hangi pip paketini kaldırırsam eksik_bagimlilik senaryosunu güvenle test ederim? Komutu ver.`), 🖥️ o komutu çalıştır, programda o yeteneği kullan → "eksik bağımlılık, kurayım mı?" sormalı; onaylayınca kurup devam etmeli.
- [ ] 🤖 `commitle`
- [ ] `/clear`

## ADIM 9 — Kendini genişletme (K6, ikinci yarı)

- [ ] 🤖
  ```
  /asama K6 — kalan madde: yetenek/uretici.py ve testleri. Kod ajanı olarak ayar.toml [cli_ajan] tercihindeki ilk bulunanı kullan; hiçbiri yoksa bulut "kod" rolü. Sandbox testi geçmeden hiçbir üretilen yetenek kayıt defterine girmesin; giren yetenek kaynak=uretildi, guvenilir=false olsun.
  ```
- [ ] 👀 Programa mevcut yeteneği olmayan bir iş ver: *"Şu PDF'in tablolarını Excel'e çıkar"* (bir PDF ver). Program eksik yeteneği söyleyip **üretme onayı** istiyor mu? Onaylayınca üretip test edip görevi bitiriyor mu? Yetenekler sekmesinde `uretildi / güvenilir: hayır` görünüyor mu?
- [ ] 🤖 `denetci ajanıyla K6'nın tamamını denetle. Özellikle: onaysız kurulum yolu var mı, sandbox gerçekten izin dışı erişimi engelliyor mu, API anahtarları alt sürece sızıyor mu. GEÇTİ alana kadar düzelt.`
- [ ] 🤖 `commitle`
- [ ] `/clear`

---

## ADIM 10 — Ölçüm ve sınav (K7)

- [ ] 🤖 `/asama K7 onaysız`
- [ ] 🤖 `cafer sinav (ya da eşdeğeri) komutunu benim kademem için çalıştır, tabloyu göster.`
- [ ] 👀 Modeller sekmesinde tok/sn ve başarı oranları var mı? "Listeyi yenile" düğmesi `modeller.json`'u güncelliyor mu?
- [ ] 🤖 `commitle`
- [ ] `/clear`

---

## ADIM 11 — Sunucu modu (K8)

- [ ] 🤖 `/asama K8`
- [ ] 🤖 `/sunucu docker`
- [ ] 👀 Telefonunu aynı Wi-Fi'ye bağla, Claude'un verdiği `http://<ip>:8765` adresini aç, token'ı gir, "ana ekrana ekle", bir görev başlat. Çalışıyor mu?
- [ ] 🤖 `commitle`
- [ ] `/clear`

## ADIM 12 — VPS'e kur (K8 devamı)

- [ ] 🤖
  ```
  docs/SUNUCU_KURULUM.md'yi, üzerinde sadece SSH olan taze bir Ubuntu VPS'te kopyala-yapıştır ile çalışacak tek bir betiğe dönüştür: sunucu/kur.sh. Betik: Docker + compose kurar, repoyu klonlar (public GitHub), .env'i soru sorarak doldurur (CAFER_TOKEN'ı kendisi üretir, API anahtarlarını sorar, alan adını sorar), docker compose up -d yapar, Caddy ile alan adına HTTPS bağlar, sonunda adres + token'ı ekrana yazar. Betiği idempotent yaz (ikinci çalıştırma bozmasın). Bana betiği ve VPS'te çalıştıracağım tek satır komutu ver.
  ```
- [ ] 🤖 `commitle` (betik repoya girsin ki VPS'ten çekilsin)
- [ ] 🖥️ VPS'e SSH ile gir, Claude'un verdiği tek satırı çalıştır, soruları cevapla.
- [ ] 👀 Telefondan `https://<alan-adin>` açılıyor mu? Bilgisayarını kapat, telefondan görev başlat → sürüyor mu?
- [ ] Takılırsan: VPS'teki hata çıktısını kopyala → 🤖 `/hata-analiz` + hata (Claude Code laptop'ta, betiği düzeltir; sen VPS'te `git pull` + betiği tekrar çalıştırırsın).
- [ ] `/clear`

---

## ADIM 13 — Uzak mod ve senkron (K9)

- [ ] 🤖 `/asama K9`
- [ ] 👀 Masaüstünde "uzak sunucu" ayarına VPS adresi + token gir. Bilgisayarı kapat, telefondan görev ver, bilgisayarı aç → görev masaüstünde görünüyor mu? Onay bekleyen görevde telefona bildirim geldi mi?
- [ ] 🤖 `commitle`
- [ ] `/clear`

---

## ADIM 14 — Kurulum sihirbazı ve sadeleştirme (K10)

- [ ] 🤖 `/asama K10`
- [ ] 👀 `ayar.toml`'da `kademe_kilidi = "dusuk"` yap, programı aç → sade arayüz, açılış 3 sn altı, bulut anahtarıyla bir görev bitiyor mu? Sonra kilidi boşalt.
- [ ] 🤖 `commitle`
- [ ] `/clear`

---

## ADIM 15 — Kapanış

- [ ] 🤖
  ```
  docs/MIMARI.md'yi gerçekle karşılaştır: yapılmayan, değişen ya da farklı çözülen kararları dokümana işle (silme, "değişti: …" notu düş). /kontrol çalıştır, tamamen yeşil olana kadar düzelt. NOTLAR/ altına K serisi kapanış notu yaz: ne yapıldı, ne ertelendi, sonraki 5 öneri. CHANGELOG.md'ye sürüm notu ekle.
  ```
- [ ] 🤖 `commitle`
- [ ] 🖥️ `git checkout main && git merge k-serisi && git tag v3.0.0 && git push --tags` (ana dalının adı `main` değilse onu yaz)
- [ ] 👀 In-app güncelleme mekanizmanla yeni sürüm iniyor mu?

Bitti. Bundan sonra: yeni bir hata → `/hata-analiz`; yeni yetenek → `/yetenek-ekle`; model listesi eskidi → ADIM 4'teki model araştırma metnini tekrar yapıştır.
