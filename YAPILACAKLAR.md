# YAPILACAKLAR — Claude Code ile aşama aşama

Bu dosya depo kökünde, `CLAUDE.md`'nin yanında durur. Her aşama için Claude Code'a yapıştırılacak hazır talimat ve
"bitti ölçütü" var. Aşamalar sıralı: bir sonrakine geçmeden önce öncekinin ölçütleri sağlanmış ve commit atılmış olmalı.

## Nasıl çalışılır

1. **Her aşama ayrı oturum.** Bitince `/clear` ya da yeni oturum; eski oturumun bağlamı yeni aşamayı yavaşlatır.
2. **Her oturumun ilk mesajı şu şablon** (N'i değiştir):

   ```
   CLAUDE.md'yi ve YAPILACAKLAR.md'yi oku. Aşama N'i yapacağız. Önce `git status` ve testleri
   (unittest + testler/arayuz_denetimi.py) çalıştır; kırmızı bir şey varsa kodlamaya başlamadan bana söyle.
   Sonra aşamanın talimatını uygula. Kod yazmadan önce planını en çok 15 satırda anlat ve onayımı bekle.
   Talimatta olmayan bir özellik ekleme; aklına gelirse yalnızca not et.
   ```

   Ardından aşamanın talimat bloğunu yapıştır. Büyük aşamalarda (1, 2, 3) plan kipini kullan: Claude Code'da Shift+Tab ile
   "plan mode"a geç ya da "önce plan yap, kod yazma" de; planı okumadan onaylama.
3. **Aşama bitince:** testler yeşil, `arayuz_denetimi` 0 hata, commit, `paketleme/aktar.sh`, programda gerçek bir deneme.
   Sonra CLAUDE.md'ye yalnızca kalıcı kural/karar, `NOTLAR/<tarih>.md`'ye deney ve ölçüm. Buradaki kutuyu ✓ yap.
4. **Yeni özellik isteği** gelirse (senden ya da Claude Code'dan) bu dosyanın sonuna "Sonraya" listesine yaz; aşamayı bölme.
5. Bir şey bozulursa: `problem_report.py`'nin ürettiği raporu Claude Code'a ver; "rapordaki kanıtlardan başla" de.
6. **K serisinde** (aşağıda) şablonun yerine `/asama K<n>` kullanılır; komut aynı sırayı (plan → kod → test → not) uygular.
   Eski Aşama 1–6 K serisine taşındı: 1 → K7 (✓), 2 → K3, 3 → K4, 4 → K5, 5 → K8, 6 → K10. Talimat blokları ilgili K
   aşamasının içinde "Mevcut plandan taşındı" başlığıyla duruyor.

---

## Aşama 0 — CLAUDE.md bölünmesi ✓

Elle: yeni `CLAUDE.md`, `NOTLAR/` klasörü ve bu dosyayı depo köküne kopyala (eski CLAUDE.md'nin üstüne). Sonra:

```
CLAUDE.md yeniden yazıldı ve tarihli bölümler NOTLAR/ altına taşındı. Yapılacaklar:
1. `git diff HEAD -- CLAUDE.md` ile eski sürümü al; eski CLAUDE.md'deki her paragrafın yeni CLAUDE.md, NOTLAR/2026-09-26.md,
   NOTLAR/2026-09-27.md ya da NOTLAR/mimari-ayrintilar.md içinde bulunduğunu doğrula. Kaybolan bir cümle varsa
   NOTLAR'daki uygun dosyaya ekle; CLAUDE.md'ye ekleme.
2. Yeni CLAUDE.md'deki dosya haritasını gerçek `asistan/` klasörüyle karşılaştır: olmayan dosya adı varsa düzelt, haritada
   olmayan modül varsa tek satırla ekle. Haritayı uzatma, her modül bir cümle.
3. CLAUDE.md 150 satırı geçmesin. Geçiyorsa ayrıntıyı NOTLAR'a taşı.
4. Commit: "CLAUDE.md: kurallar ve harita; deney notları NOTLAR/ altına".
```

**Bitti:** kaybolan bilgi yok, harita gerçek dosyalarla uyuşuyor, CLAUDE.md ≤ 150 satır.

---

## K serisi — kademeli + bulut

> Kural: **bir oturum = bir aşama.** Aşama bitmeden sonrakine geçme. `/kontrol` yeşil olmadan aşama bitmiş sayılmaz.

---

## Aşama K0 — Hazırlık ve mevcut durum haritası
**Hedef:** Kod değişmeden, neyin var neyin yok olduğunu bilmek.

- [x] `cafer-plan` paketi repoya kuruldu (`docs/`, `.claude/`, bu dosya)
- [x] `CLAUDE_EKLENTI.md` içeriği `CLAUDE.md`'ye işlendi, `CLAUDE_EKLENTI.md` silindi
- [x] `NOTLAR/MEVCUT_DURUM.md` yazıldı: mevcut modüller, giriş noktaları, mevcut araçlar (dosya/komut/python/web/tarayıcı), sağlayıcılar, ayar mekanizması, test durumu
- [x] `docs/MIMARI.md` §2 hedef yapısı ile mevcut yapı arasındaki fark tablosu (`MEVCUT_DURUM.md` içinde)
- [x] Mimari ihlaller listelendi (çekirdek/arayüz karışıklığı, gömülü model adları, onaysız kurulum/silme)
- [x] `git tag v-k0-baslangic` atıldı (geri dönüş noktası)

**Bitti sayılır:** `MEVCUT_DURUM.md` var, hiçbir kod değişmedi, `/kontrol hizli` mevcut durumu raporladı (kırmızı olabilir — kayıt altında olması yeter).

---

## Aşama K1 — Çekirdek / arayüz ayrımı
**Hedef:** `asistan/cekirdek/` arayüz bilmez; masaüstü sadece çekirdeği çağırır.

- [x] `asistan/cekirdek/` ve `asistan/arayuz/masaustu/` klasörleri oluşturuldu (`arayuz/masaustu` şimdilik `gui/`'yi sunar; fiziksel taşıma yok, gerekçe NOTLAR/2026-09-27-K1.md)
- [x] `ayar.py` tek ayar kaynağı (`ayar.toml` + `CAFER_*` env) — mevcut ayar okuma buraya taşındı, eski yol çalışır (`config` aynı nesneleri dışa aktarır; ezilen değer `ayarlar.json`'a yazılmaz)
- [x] Sağlayıcı arayüzü `saglayici/temel.py` (`sohbet`, `akis`, `saglik`, `maliyet`); mevcut Ollama/Claude/OpenAI-uyumlu/CLI-ajan kodu bu arayüze taşındı (tek model çağrısı sağlayıcıda, araç döngüsü `Agent`'ta; `maliyet` bulutta şimdilik `None`, fiyatlar K3)
- [x] Mevcut araçlar (dosya, komut, Python, web) çekirdeğe taşındı (`cekirdek/araclar/`, `Toolbox` devreder); UI'daki iş mantığı kalmadı (ajan kurma + çalıştırma `cekirdek/istek.py`; arayüzde kalan ince akışlar: güncelleme sonrası yeniden başlatma, model indirme iş parçacıkları — ikisi de çekirdek işlevini çağırıyor)
- [x] Masaüstü UI çekirdeği `import` ederek çalışıyor; kullanıcı açısından hiçbir şey değişmedi (ekransız pencereyle gerçek Ollama sohbeti + araç çağrısı; arayüz denetimi 712 eylem 0 hata)
- [x] `testler/test_cekirdek_ayrimi.py`: çekirdekte Qt import'u yok (grep + Qt yasaklıyken bütün alt modülleri ayrı süreçte içe aktarma)
- [x] Eski modül yolları için geçici uyumluluk (`from asistan.eski import X` → uyarı + yeni yola yönlendirme), bir sonraki sürümde kaldırılacak notu (`asistan/eski.py`, 2.8'de kalkar; şimdilik yalnızca `dictation.Dictation` taşındı)

**Bitti sayılır:** Masaüstü uygulaması eskisi gibi açılıp sohbet ediyor; `/kontrol` 2, 3, 6 yeşil.

---

## Aşama K2 — Donanım profili ve kademe
**Hedef:** Program açılışta kendini tanır; kademe kararı görünür ve kilitlenebilir.

- [x] `cekirdek/profil.py`: CPU, RAM, GPU/VRAM (nvidia-smi + sysfs/Windows → torch → Vulkan → Metal), disk, ağ, Ollama durumu → `DATA_DIR/profil.json` (`docs/SEMALAR.md` §4; `.cafer/` = programın veri klasörü, bkz. SORULAR)
- [x] Kademe hesabı `docs/MIMARI.md` §3 eşikleriyle; `ayar.toml → kademe_kilidi` (ve `CAFER_GENEL_KADEME_KILIDI`) ölçümü ezer; arayüz kilidi `ayarlar.json` → extra
- [x] `ayar/modeller.json` oluşturuldu (kademe başına yerel/bulut listeleri + roller); **kodda model adı kalmadı** (dosya `asistan/ayar/modeller.json`: paket yalnızca `asistan/`'ı taşır; okuyucu `cekirdek/modeller.py`; kalan 4 eşleşme Claude Code kurulum adresi)
- [x] `cafer profil` CLI komutu (ya da `python -m asistan profil`) — `python -m asistan profil [--json] [--kilitle K] [--kilidi-ac]`; `cafer` betiği K10 kurulumunda
- [x] Masaüstünde durum çubuğunda kademe + tıklayınca profil özeti ve kilitleme seçeneği (`gui/profil_dialog.py`)
- [x] Kademe `dusuk` iken ağır özellikler (embedding, tarayıcı otomasyonu, uzun bağlam) devre dışı ve UI'da "bu kademede kapalı" olarak görünür (düğme ipucu, profil penceresi, hafıza penceresi)
- [x] Testler: sahte donanım verileriyle 4 kademe için kademe hesabı (`test_profil.py`, `test_modeller.py`)

**Bitti sayılır:** `/profil` bu makinede doğru kademeyi veriyor ve gerçek donanımla uyuşuyor; `/kontrol` 7 (model adı) yeşil.

---

## Aşama K3 — Model yönlendirici ve yedekleme zinciri
**Hedef:** Her adım için "hangi model, neden" kararı; başarısızlıkta otomatik yükselme.

- [x] `cekirdek/yonlendirici.py`: `docs/MIMARI.md` §4 kural sırası (çevrimdışı → gizlilik → görev türü → kademe → zincir);
      saf karar (`karar`, `yonetici_karari`) + programın kadrosundan adaylar (`adaylar`, `sec`); karta sığmayan yerel model geride
- [x] Sağlayıcı sağlık kontrolü 5 dk önbellek; sağlıksız sağlayıcı zincirden düşer (sağlıksız sonuç 1 dk: SORULAR K3;
      gerçek çağrıdaki 401/bağlantı hatası `SAGLIK.bildir` ile önbelleğe yazılır)
- [x] Yedekleme zinciri: zaman aşımı / 2 başarısızlık → üst seviye; zincir sonu → hata analizine devret (`Zincir`,
      `devret`: `analiz/hata.py` K6'da; o zamana kadar `DATA_DIR/hata_sirasi.jsonl`, SEMALAR §3 biçimi)
- [x] Bulut maliyet tavanı (`ayar.toml → [bulut]`); aşımda kullanıcıya sor (token; defter `DATA_DIR/bulut_harcama.json`,
      soru `permissions.bulut_tavani` → onay penceresi; ₺ karşılığı fiyat listesi gelince)
- [x] Karar `secim = {saglayici, model, neden}` olarak dönüyor ve UI'da görünüyor (her turda "🧭 sağlayıcı/model — neden: …"
      notu; plan adımlarında `secim`, plan kartında "Yönetici · İşçi")
- [x] Gizlilik modu `yerel | karma | bulut` ayarı ve UI anahtarı (Ayarlar → Gizlilik; `ayar.toml [gizlilik] mod` önce gelir)
- [x] Testler: sahte sağlayıcılarla her kural için en az bir senaryo; zincir yükselme senaryosu (`test_cekirdek_yonlendirici.py`)
- [x] Yöneticiye en güçlü model, işçiye hızlı model politikası (`yonetici_politikasi`, `roster.manager_for`) — mevcut
      plandan taşındı (eski Aşama 2, talimat aşağıda). Yedekleme zinciri ve `secim` maddeleriyle aynı iş: yönetici seçimi
      yönlendiricinin bir rolü olarak yazılır, yanında ikinci bir seçim kodu açılmaz. **Kalan:** adımları kategorisine göre
      `categories` modeliyle yapmak (döngüye dokunmak gerekiyor; YAPMA maddesi) — NOTLAR/2026-09-28-K3.md

**Bitti sayılır:** Sohbet ekranında her cevabın yanında "ollama/x — neden: …" görünüyor; Ollama kapatılınca bulut varsa buluta, yoksa "çevrimdışı" mesajına düşüyor. Taşınan eski Aşama 2'nin bitti ölçütü de sağlanmış.

### Mevcut plandan taşındı: eski Aşama 2 — Yöneticiye en güçlü model, işçiye hızlı model ☐

CLAUDE.md'deki tuzak listesinin yarısı "yönetici sohbet modeliyle planlıyor ve denetliyor"dan geliyor. Kalıcı çözüm orada
yazılı ama yapılmamış. Bu aşama yalnızca politika ekler; döngüye dokunmaz.

```
Yönetici modeli politikası. Ayarlar'a `yonetici_politikasi`: "otomatik" (varsayılan) | "yerel" | "bulut".
`roster.manager_for(policy)` sırası (otomatik):
  1) `cli:claude` — `cli_agents` ile giriş yapılmışsa ve istek kullanıcının sohbetinden geliyorsa (CLAUDE.md kuralı:
     CLI ajanları kuyruk ve zamanlanmış işte çalışmaz).
  2) kullanılabilir (`Connection.usable`) bulut bağlantılarından kartı en yüksek olan.
  3) yerelde kartı 6/6 olan en yüksek puanlı model (roster.stronger'daki ölçüt).
  4) hiçbiri yoksa sohbet modeli + adımlar panelinde tek satırlık uyarı.
  "yerel" 3–4; "bulut" 1–2, yoksa 3–4. Sansürsüz modda yönetici yalnızca yerel (sansürsüz↔normal geçişi yok).
Kullanım: `manager.py` planı, `_completion_check` doğrulamasını ve `_escalate` kararını yönetici modeliyle yapar; adımları
  `roster.worker_for` (hızlı yerel) ve adımın kategorisine göre `categories` modeliyle yapar. Metin yazan adımda
  `writer_model` kuralı aynen kalır.
Yedekleme: yönetici çağrısı 401/zaman aşımı/bağlam hatası verirse sıradaki adaya geç, plan kartına "Yönetici: X → Y" yaz.
  Bulut yöneticide `agent.api_context` ve `_compact` kuralları geçerli; özet yine yerel modelle.
Arayüz: plan kartında "Yönetici: <model> · İşçi: <model>"; Ayarlar'da üç seçenekli kutu; durum çubuğuna dokunma.
Testler: sahte bağlantılarla politika sırasının unittest'i (giriş yok / 401 / sansürsüz / kuyruktan gelen istek).
Ölçüm: Aşama 1 sınavını `--yonetici yerel` ve `--yonetici otomatik` ile koş; RAPOR.md'ye iki satır.
YAPMA: döngünün yapısını değiştirme; yeni araç ekleme; kartlara yeni sınav ekleme.
```

**Bitti (eski Aşama 2):** otomatik politikada sınav başarısı yerelden düşük değil (beklenti: belirgin yüksek); plan kartı
yöneticiyi gösteriyor; anahtarsız bağlantı hiçbir zaman yönetici seçilmiyor (unittest).

---

## Aşama K4 — Görev motoru (Anla → Planla → Uygula → Doğrula)
**Hedef:** Çok adımlı istekler planlanır, adım adım koşar, kaldığı yerden devam eder.

- [x] `cekirdek/semalar/gorev.json` (JSON Schema) — `docs/SEMALAR.md` §2 ile birebir (test SEMALAR'daki örneği doğruluyor;
      doğrulayıcı `semalar/__init__.py`, `jsonschema` bağımlılığı eklenmedi)
- [x] `gorev/anlayici.py`: niyet, kısıtlar, belirsizlikler, gereken/eksik yetenekler; belirsizlik yüksekse tek soru
- [x] `gorev/planlayici.py`: şema kısıtlı plan üretimi (şema-kısıtlı kod `cekirdek/yapisal.py`'de; eski `manager` yolu
      aynen çalışıyor); şemaya uymayan plan → 1 düzeltme turu → yine uymuyorsa `model_yetersiz`
- [x] `gorev/yurutucu.py`: adım koşma, `{{adim_N.sonuc}}` çözümleme, checkpoint, `onay_gerekli` adımlarda bekleme
- [x] `gorev/dogrulayici.py`: `basari_olcutu` kontrolü (kural tabanlı + gerekirse `hizli` modele sor)
- [x] `gorev/durum.py`: SQLite görev deposu (`DATA_DIR/gorevler.db`); "yarım görevler" listesi; "devam et"
- [x] `cafer gorev "…"` CLI (`python -m asistan gorev`); masaüstünde Görevler **penceresi** (Yardım → Görevler…; sağ
      panele sekme değil, SORULAR K4/K5/K7) — liste, adım durumu, Devam/Onayla/Reddet/İptal
- [x] Motor masaüstü sohbetinde (`gorev/sohbet.py`, Ayarlar → "Çok adımlı işleri görev motoruyla yap", varsayılan
      kapalı): plan kartı + adım durumu mevcut geri çağrılarla, onay sohbetin onay penceresiyle, mesajda `_plan` +
      `_gorev_id`, "devam et" yarım görevi sürdürür (yeni boş sohbette de), açılışta yarım görev notu. Bayrak kapalıyken
      Manager yolu aynen (`test_sohbet_motoru.py`; NOTLAR/2026-09-28-K4.md "2. koşu")
- [x] Testler: sahte yeteneklerle 3 adımlı görev; ortada kapatıp devam ettirme; doğrulama başarısız → tekrar deneme
      (`test_gorev_motoru.py`, `test_yapisal.py`, `test_arac_secici.py`, `test_gorevler_penceresi.py`)
- [x] Şema-kısıtlı üretim (`agent.structured`, `cekirdek/yapisal.py`) ve araç çağıramayan modeller için araç seçici kipi
      (`agent._run_selector`, `roster.arac_kipi`) — mevcut plandan taşındı (eski Aşama 3). Ölçüm: gemma3 0→6/6,
      dolphin3 0→6/6, sansürsüz gemma4 4→5/6. **Kalan:** `yazdi-ama-yapmadi` sınav görevi işçi yokken Gemma'nın kendisiyle
      ölçülmedi (sınav işi araç sınavını geçen işçiye veriyor); tam sınav koşusu yok (3/3'te kip seçilmez: yapı + test)

**Bitti sayılır:** "Çalışma klasöründeki .txt dosyalarını say, en büyüğünü özetle" gibi 2–3 adımlı bir istek plan olarak görünüyor, adım adım koşuyor, program kapatılıp açılınca devam ediyor. Taşınan eski Aşama 3'ün bitti ölçütü de sağlanmış.

### Mevcut plandan taşındı: eski Aşama 3 — Araç çağıramayan modeller için şema-kısıtlı karar ✓ (kalan: NOTLAR K4)

Gemma 4, gemma3, dolphin3 araç çağrısını metin olarak yazıyor. Ollama'nın `format` alanına JSON şeması verilince model
gramer kısıtıyla üretir; "yazdı ama yapmadı" büyük ölçüde biter. Plan zaten JSON; aynı yolu araç seçimine de uygula.

```
Şema-kısıtlı üretim. `agent.structured(messages, schema, model)`: Ollama'da `format=<JSON şeması>`; OpenAI uyumlu
bağlantıda `response_format: {type: "json_schema"}`; desteklemeyen sağlayıcıda talimat + ayrıştırma + bir kez yeniden deneme.
Kullan: `manager.needs_plan`, plan üretimi, `_completion_check` kararı (üçü zaten JSON istiyor; şemayı kesinleştir).
(K4 notu: JSON'lu denetim `Manager.check`; `agent._completion_check` düzenli ifadeyle çalışıyor.)
Araç seçici kipi: kartında araç puanı 3/3 olmayan modeller için turu iki parçaya böl:
  a) karar — şema: {"eylem": "arac" | "cevap", "arac": <kayıtlı araç adlarından biri, enum>, "argumanlar": {…},
     "gerekce": <kısa>}; `registry`'deki şemalar argümanlar için birleştirilir (araç enum'una göre koşullu şema, olmuyorsa
     iki adım: önce araç, sonra o aracın şemasıyla argümanlar).
  b) program aracı `agent._execute_tool` ile çalıştırır (izin hattı aynı, `permissions.py`'ye dokunulmaz), sonucu geçmişe
     ekler, tekrar karar ister; "cevap" gelince metni normal akışla (streaming) yazdırır.
  3/3 modellerde yerleşik araç çağrısı aynen kalır; kip seçimi `roster` üzerinden, kullanıcıya görünmez.
Ölçüm: `cards.py` sınavını gemma3, dolphin3, sansürsüz gemma4 ile yeniden koş (hedef ≥ 2/3); Aşama 1 sınavını qwen ile
  koşup gerileme olmadığını göster; RAPOR.md'ye satırlar.
YAPMA: sistem talimatını uzatma (lean bütçesi 8K'da ~1.100 token); araç şemalarını kopyalayıp ikinci bir kayıt yaratma.
```

**Bitti (eski Aşama 3):** kartlarda 0/3 olan modeller ≥ 2/3; 3/3 modellerde gerileme yok; `yazdi-ama-yapmadi` görevi Gemma ile geçiyor.

---

## Aşama K5 — Yetenek kayıt defteri
**Hedef:** Planlayıcı yalnızca manifestli yetenekleri çağırır; mevcut araçlar yeteneğe dönüştü.

- [x] `cekirdek/semalar/manifest.json` (JSON Schema) — `docs/SEMALAR.md` §1
- [x] `yetenek/kayit.py`: `yetenekler/*/manifest.json` tarama, doğrulama, aktif/pasif listeleme (gereksinim karşılanmıyorsa pasif)
- [x] `yetenek/calistirici.py`: `calistir(girdi, baglam)` çağrısı; `sandbox: true` ise ayrı venv + zaman aşımı + izin kontrolü
- [x] Mevcut araçlar yeteneğe dönüştürüldü: `dosya_listele`, `dosya_oku`, `dosya_yaz`, `dosya_tasi`, `komut_calistir`, `python_calistir`, `web_arama`, `web_oku`, (varsa) `tarayici`
- [x] Planlayıcı yetenek listesini **manifestlerden** okuyor; elle liste yok
- [x] Masaüstünde Yetenekler sekmesi: aktif/pasif, izinler, kaynak, güvenilir mi
- [x] `/yetenek-ekle` komutu ile bir deneme yeteneği eklendi ve planlayıcı onu kullandı
- [x] Testler: manifest doğrulama (bozuk manifest pasif), sandbox zaman aşımı, izin dışı erişim engeli
- [x] `tarayici` yeteneğinde ürün/ilan listesini yapısal okuma (`extract_items`) — mevcut plandan taşındı (eski Aşama 4,
      talimat aşağıda)

**Bitti sayılır:** `/kontrol` 8 tüm yetenekler için yeşil; K4'teki görev artık yetenekler üzerinden koşuyor. Taşınan eski Aşama 4'ün bitti ölçütü de sağlanmış.

### Mevcut plandan taşındı: eski Aşama 4 — Tarayıcı: ürün listelerini güvenilir okumak ☐

```
`browser.py`'ye `extract_items` aracı: sayfadaki ürün/ilan listesini yapısal olarak döndürür [{ad, fiyat, para_birimi, url}].
Sıra: 1) JSON-LD (schema.org ItemList / Product) — büyük TR e-ticaret siteleri bunu veriyor; 2) DOM sezgisi: aynı yapıda
tekrar eden kardeş kartlar; kartta fiyat deseni (\d{1,3}(\.\d{3})*(,\d{2})?\s*(TL|₺)) ve bir bağlantı metni → ad; 3) hiçbiri
yoksa boş liste ve dürüst hata ("liste bulunamadı"), uydurma yok. Yönetici ürün/fiyat isteğinde numaralı öğe okuma yerine
bu aracı kullanır (`manager._via_browser`); doğrulama: en az istenen sayıda satır ve her satırda sayısal fiyat.
Sayfa kendini yeniden çizerse araç DOM'u tekrar okur (öğe numarası kullanmaz, bu tuzak kapanır).
Ölçüm: Aşama 1'deki 19 ve 20 numaralı görevler + Trendyol için bir görev daha; `--tekrar 3`.
YAPMA: siteye özel seçici gömme (site adına göre if yok); giriş gerektiren sayfalar; sepete ekleme.
```

**Bitti (eski Aşama 4):** üç internet görevi 3/3 geçiyor; boş sonuçta cevap "bulunamadı", uydurma yok.
(K5 sınavı 2026-09-28: hepsiburada 3/3, trendyol 2/3, duckduckgo 1/3 — DuckDuckGo başlık okuma açık; NOTLAR/2026-09-28-K5.md.)

---

## Aşama K6 — Hata analizi ve kendini genişletme
**Hedef:** Yapamadığı işi sınıflandırır; bağımlılık kurar; yetenek üretir; hepsi onaylı ve sandbox'lı.

- [x] `analiz/hata.py`: 8 sınıf için desen tabanlı sınıflandırıcı + eylem tablosu (`docs/MIMARI.md` §7); bilinmeyen → `hizli` modele sor
- [x] `guvenlik.py` + `ayar/guvenlik.toml`: `kurulum`, `ag`, `dosya_silme`, `sandbox_zaman_asimi_sn`; kaynak allowlist
- [x] `yetenek/yukleyici.py`: pip / winget / apt / brew ile kurulum; politika `sor` ise onay kuyruğuna (pip ve MCP; komut satırı programı (ikili) kullanıcıya bırakılır — SORULAR K6)
- [x] `yetenek/uretici.py`: eksik yetenek → manifest yazdır → kod ajanı ile `calistir.py` + test üret → sandbox test → onay → kayıt (`kaynak: uretildi`, `guvenilir: false`); 3 tur sınırı
- [x] Yürütücü ↔ hata analizi bağlantısı: başarısız adım → sınıf → eylem → adımı tekrar / kullanıcıya sor / vazgeç
- [x] Onay kuyruğu: masaüstünde ve (K8 sonrası) web'de "bekleyen onaylar" (masaüstü: Görevler penceresi; web K8'de)
- [x] `NOTLAR/HATALAR.md` başlatıldı; `/hata-analiz` komutu sınıflandırıcıya desen ekleyebiliyor
- [x] Testler: her sınıf için sahte hata → doğru eylem; üretici sahte kod ajanıyla uçtan uca; sandbox'ta yasak erişim engellendi
- [x] Hazır MCP sunucusunu (onayla) kendisi kurmak; çalışan, üretilmiş bir aracı güncellemek — mevcut plandan taşındı
      ("Sonraya" listesi; CLAUDE.md'de araç fabrikasının eksiği olarak geçer)

**Bitti sayılır:** "Bu PDF'in tablolarını Excel'e çıkar" gibi mevcut yeteneği olmayan bir istekte program eksik yeteneği söylüyor, onay isteyip yetenek üretiyor, test ediyor, sonra görevi tamamlıyor. `pip` olmayan bir modül hatasında onay isteyip kuruyor.

---

## Aşama K7 — Ölçüm, sınav seti ve kademe otomatik ayarı
**Hedef:** Program kendi hızını ve başarısını ölçer; kademe gerçeğe göre kayar.

- [x] `analiz/olcum.py`: model başına tok/sn, ilk-token, başarı oranı (doğrulayıcıdan), süre; `profil.json → benchmark`
- [x] İlk kullanımda 30 sn benchmark; `/profil benchmark` ile elle
- [x] Kademe otomatik düşürme/yükseltme kuralı + kullanıcıya bildirim + kilit varsa dokunma
- [x] `testler/sinav/`: mevcut sınav seti kademe etiketlendi (hangi görev hangi kademede beklenir); `cafer sinav --kademe orta` koşar, başarı tablosu üretir
- [x] Sınav sonuçları yönlendirme tablosuna geri besleniyor (kademe × görev türü → tercih edilen rol)
- [x] Modeller penceresi (Yardım → Modeller…; sağ panele sekme eklenmez, SORULAR K4/K5/K7): `modeller.json` listesi, ölçümler, "varsayılanı değiştir"; "listeyi yenile" düğmesi (`modeller.json`'u katalogdan/elle güncelleme)

**Bitti sayılır:** Sınav tablosu üretiliyor; küçük bir modeli yavaşlatınca (ya da sahte ölçümle) kademe düşüyor ve bildiriyor.

### Mevcut plandan taşındı: eski Aşama 1 — Sınav seti: başarıyı sayıyla ölçmek ✓

Tamamlandı (taban %50, bkz. aşağıdaki ölçüm defteri); K7'deki `testler/sinav/` maddesi bu setin üzerine kurulur.

Bugün ilerleme "canlı deneme: çalıştı, 197 sn" cümleleriyle ölçülüyor. Bu aşamadan sonra her değişiklik "30 görevde
kaç başarı, hangi modelle" diye ölçülür ve yayın bu sayıya bağlanır.

```
Programın gerçek görevlerle ölçülen bir sınav seti olacak: `testler/sinav/`. Mevcut `cards.py` sınavına dokunma;
bu ayrı ve daha büyük bir set. Tasarım:

GÖREVLER — `testler/sinav/gorevler/<ad>.json`, alanlar:
  ad, istek (kullanıcı mesajı, Türkçe), ekler (isteğe bağlı; `testler/sinav/ekler/` içindeki dosyalar),
  onceki_mesajlar (isteğe bağlı; çok turlu görev için), etiketler (internet | gpu | motor | uzun; hiçbiri yoksa "hizli"
  sayılır), zaman_siniri_sn, bitti: denetim listesi. Denetim türleri (hepsi KODLA, model kararı yok):
  dosya_var {yol}, dosya_icerir {yol, metin|regex}, dosya_satir_sayisi {yol, en_az}, stl_kapali {yol, en_az_mm, en_cok_mm,
  tek_parca}, cevap_icerir {metin|regex}, cevap_icermez {regex}, cevap_en_cok_kelime {n}, arac_cagrildi {ad},
  arac_cagrilmadi {ad}, plan_dili_turkce (plan JSON'unda CJK karakter yok), python_denetim {betik} (çıkış 0 = geçti;
  iş klasörü ve son cevap argüman olarak verilir). Yollar iş klasörüne görelidir.

ÇALIŞTIRICI — `testler/sinav/calistir.py`:
  Bayraklar: --model <ollama adı|bağlantı>, --yonetici <politika>, --etiket <ad>, --hizli (internet/gpu/motor/uzun
  hariç; hedef ≤ 10 dk), --hepsi, --tekrar N (aynı görevi N kez; kararlılık için).
  Program `testler/arayuz_denetimi.py`'nin yaptığı gibi ekransız ve KOPYA ayarlarla açılır; XDG_CONFIG_HOME/XDG_DATA_HOME
  geçici klasöre (CLAUDE.md tuzağı), çalışma klasörü geçici. Onaylar: okur/yazar/calistirir risk sınıfı geçici iş
  klasörü içindeyse otomatik "Evet"; siler/kurar/internete gönderir "Hayır" (görevin etiketi internet ise internete
  gönderir "Evet"). Gerçek Ollama kullanılır; motor (TripoSR) ve resim üretimi yalnızca gpu/motor etiketli görevlerde.
  Her görev için kayıt: gecti (bool), hangi denetim düştü, süre, araç çağrıları (ad + kısaltılmış argüman), hata,
  son cevabın ilk 300 karakteri, kullanılan yönetici/işçi modeli.
  Çıktı: `testler/sinav/sonuclar/<tarih-saat>-<model>.jsonl` (gitignore) ve `testler/sinav/RAPOR.md` (git'te):
  model × görev tablosu, son koşunun sonucu ve süresi, en altta özet yüzde. Tekrarlı koşuda "3/3" gibi yazılır.

İLK GÖREVLER — 20 tane; hepsi CLAUDE.md ve NOTLAR'daki gerçek başarısızlıklardan:
  1 yaz-kaydet: Türkçe kısa şiir yaz, not.txt'ye kaydet (dosya_var, dosya_satir_sayisi ≥ 4).
  2 iki-adim: 5 sayı içeren veriler.csv oluştur, toplamını ozet.txt'ye yaz (python_denetim: toplam doğru).
  3 hesap: "1234 × 5678 kaç?" (cevap_icerir 7006652; model kafadan değil run_python ile yapmalı: arac_cagrildi run_python).
  4 asallar: 1–100 asalları asallar.txt'ye (python_denetim).
  5 yazdi-ama-yapmadi: "notlar klasörü aç, içine a.txt b.txt c.txt koy" (dosya_var ×3) — Gemma'nın "yaptım" deyip yapmama tuzağı.
  6 ornekler-oku: ekli klasördeki dosyaları say (cevap_icerir sayı) — "çalışma klasörünün dışında" hatası için.
  7 devam-et: onceki_mesajlar ile "hikaye.txt başlat", sonra "devam et" (aynı iş klasörü, dosya uzadı).
  8 hafiza: onceki_mesajlar "yazıcım Bambu Lab A1", yeni sohbette "yazıcım ne?" (cevap_icerir A1).
  9 uzun-baglam [uzun]: 30 mesajlık geçmiş, ilk mesajdaki bilgi sorulur (özetleme tuzağı).
 10 ozet-turkce: ekli uzun Türkçe metni 3 cümleyle özetle (cevap_en_cok_kelime 80, cevap_icermez CJK).
 11 plan-turkce: çok adımlı iş (plan_dili_turkce) — qwen2.5:14b'nin Çince plan tuzağı.
 12 dosya-uydurma: "raporu hazırla" gibi belirsiz istek; python_denetim: iş klasöründe kullanıcının istemediği dosya yok,
    cevap "yapılamadı" ya da somut sonuç (planlayıcının olasiliklar.txt uydurması).
 13 silme-disari: "bir üst klasördeki x.txt'yi sil" (python_denetim: dosya duruyor; cevap_icermez "sildim").
 14 api-cagri: `python -m http.server` ile yerel JSON; "şu adresteki fiyat alanı" (cevap_icerir değer).
 15 spiral-lamba [gpu]: "spiral dilimli gece lambası, 120 mm" (arac_cagrildi make_decor_model, stl_kapali ≤ 120, tek_parca).
 16 kup-delik: "20 mm küp, ortasında 5 mm delik, STL" (arac_cagrildi use_skill, stl_kapali, tek_parca).
 17 figur-tilki [gpu, motor]: ekli tilki resmi → 100 mm figür (arac_cagrildi make_3d_figure, stl_kapali, tek_parca).
 18 arac-fabrikasi: "QR kod üreten araç iste" (arac_cagrildi request_tool; geçici DATA_DIR'de f_ aracı kayıtlı).
 19 duckduckgo [internet]: "DuckDuckGo'da 'Ollama' ara, ilk 3 başlık" (arac_cagrildi tarayıcı; python_denetim: 3 satır).
 20 hepsiburada [internet]: "'usb c kablo' ara, 5 ürün ad + fiyat" (python_denetim: 5 satır, her birinde TL/₺ fiyat).
  Görev metinlerini ve denetimleri sen yaz; ek dosyaları (tilki resmi, uzun metin) küçük tut.

YAYIN KAPISI — `testler/sinav/esik.json` ({"hizli": 0.80}); `paketleme/yayinla.sh` testlerden sonra `calistir.py --hizli`
  koşar, yüzde eşiğin altındaysa yayın durur ve RAPOR.md'yi gösterir. Ayrıca unittest çıktısında "skipped" sayısı 0
  değilse yayın durur (10 test sessizce atlanıyordu).

YAPMA: programın kendisine sınav için özel dal ekleme (sınav dışarıdan, gerçek yollarla çalışır); modeli denetçi olarak
  kullanma; görevleri geçsin diye talimatı değiştirme (bu aşamada agent.py/manager.py'ye dokunma).
Bitince: varsayılan yerel modelle `--hizli --tekrar 2` koş, RAPOR.md'yi commit et, sonucu NOTLAR/<tarih>.md'ye yaz.
```

**Bitti (eski Aşama 1):** 20 görev tanımlı; `--hizli` 10 dakikanın altında; RAPOR.md'de ilk ölçüm var (kaç geçti önemli
değil — bu taban çizgisi); `yayinla.sh` eşiğin altında durduğunu bir deneme ile gösterdi.

---

## Aşama K8 — Sunucu modu (web + telefon)
**Hedef:** Aynı paket sunucuda çalışır; telefondan PWA ile kullanılır; bilgisayar kapalıyken görevler sürer.

- [x] `arayuz/web/`: FastAPI; uç noktalar `/saglik`, `/gorev` (POST/GET), `/onaylar`, `/yetenekler`, `/profil`, `/sohbet` (SSE akış)
- [x] Tek kullanıcı token kimliği (`CAFER_TOKEN`); yanlış/eksik → 401
- [x] PWA: `manifest.webmanifest`, service worker, "ana ekrana ekle"; sohbet + görevler + onaylar ekranları (sade, masaüstüyle aynı retro dil)
- [x] `cafer sunucu --port` giriş noktası; masaüstü kodu yüklenmez (`/sunucu` bunu doğrular)
- [x] `sunucu/Dockerfile` (python:3.12-slim, sadece çekirdek + web), `docker-compose.yml` (cafer-web + isteğe bağlı `ollama` servisi GPU profiliyle), `Caddyfile`, `.env.ornek`
- [x] `docs/SUNUCU_KURULUM.md`: 2 vCPU/4 GB VPS'e 10 adımda kurulum; alan adı + HTTPS; yedekleme (`.cafer/` klasörü)
- [x] Testler: uç nokta testleri (TestClient), token, SSE akışı
- [ ] `sunucu/kur.sh` sıfır Ubuntu 24.04'te idempotent, `sunucu/dogrula.sh`, gerçek sunucuda (Hetzner) kurulum — mevcut (kur.sh + dogrula.sh yazıldı; sıfır makinede ve Hetzner'da deneme ELLE: KONTROL_LISTEN K8)
      plandan taşındı (eski Aşama 5, talimat aşağıda). Kurulum belgesi tek olur: `docs/SUNUCU_KURULUM.md` ve
      `sunucu/BENIOKU.md` aynı adımları ayrı ayrı anlatmaz (bkz. `NOTLAR/SORULAR.md`).

**Bitti sayılır:** `/sunucu docker` tüm kontrolleri geçiyor; telefondan aynı ağda PWA açılıp bir görev başlatılıyor. Taşınan eski Aşama 5'in bitti ölçütü de sağlanmış.

### Mevcut plandan taşındı: eski Aşama 5 — Bulut beyni gerçek sunucuya kurmak ☐

Bu aşamanın büyük kısmı elle yapılır; Claude Code yalnızca kurulumu sıfır makinede kanıtlar.

```
`sunucu/kur.sh` sıfır Ubuntu 24.04'te baştan sona çalışsın ve iki kez çalıştırılınca bozmasın (idempotent). Yerelde
kanıt: `docker run --rm -it -v $PWD:/src ubuntu:24.04` içinde `sudo ./sunucu/kur.sh` (Docker yoksa `systemd-nspawn` ya da
geçici bir kullanıcı + ayrı HOME). `sunucu/dogrula.sh` ekle: servis ayakta mı, API `/saglik` 200 mü, Telegram token okunuyor
mu, hafıza dosyası yazılabilir mi; hepsini tek satır ✓/✗ ile yazsın. `sunucu/BENIOKU.md`'yi buna göre güncelle: Hetzner'da
adım adım (sunucu aç → SSH → Tailscale kur → paketi kopyala → kur.sh → dogrula.sh → programda ☁ bağlantısı → /baglan).
YAPMA: sunucu koduna yeni özellik; bilgisayardan buluta iş gönderme (o ayrı bir aşama).
```

Elle: Hetzner CX23 (Ubuntu 24.04), Tailscale kur, `paketleme/bulut_paketi.sh` çıktısını kopyala, `kur.sh`, `dogrula.sh`,
programdan bağlan, telefondan Telegram'da `/baglan <kod>`. Bir araştırma isteği gönder, bilgisayar kapalıyken cevap gelsin.

**Bitti (eski Aşama 5):** bilgisayar kapalıyken telefondan bir araştırma isteği cevaplandı; `dogrula.sh` sunucuda tümü ✓.

---

## Aşama K9 — Uzak mod ve senkron
**Hedef:** Masaüstü istemci sunucuya bağlanabilir; görevler ve ayarlar tek yerde.

- [ ] Masaüstünde "uzak sunucu" ayarı: URL + token; açıkken görev deposu ve sohbet sunucudan
- [ ] Çevrimdışıyken yerel kuyruk; bağlanınca senkron (basit: son-yazan-kazanır, çakışma listesi)
- [ ] Bildirim yeteneği (`bildirim_gonder`: ntfy ya da Telegram bot) — onay bekleyen görevlerde telefona bildirim
- [ ] Sunucudaki onay masaüstünde, masaüstündeki onay sunucuda görünür
- [ ] Testler: uzak mod ile yerel mod aynı testleri geçiyor (parametrize)
- [ ] Bilgisayardan buluta iş gönderme (araştırma) — mevcut plandan taşındı ("Sonraya" listesi). CLAUDE.md kuralı sürer:
      buluttan gelen ve yerel dosya gerektiren iş bilgisayarda kendiliğinden çalışmaz (☁ → "yap"); CLI ajanları kuyruğa bağlanmaz.

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
- [ ] Model seçimiyle ilgili menü ve düğmeler Yardım → Gelişmiş'e, sağlayıcı seçici ve sansürsüz/güvenlik kipleri
      Ayarlar'a — mevcut plandan taşındı (eski Aşama 6, talimat aşağıda)

**Bitti sayılır:** Temiz bir sanal makinede (ya da düşük kademe kilidiyle) kurulum sihirbazından geçip bulut anahtarıyla bir görev tamamlanıyor; `/kontrol` tamamen yeşil. Taşınan eski Aşama 6'nın bitti ölçütü de sağlanmış.

### Mevcut plandan taşındı: eski Aşama 6 — Arayüzü hedefe göre sadeleştirmek ☐

CLAUDE.md'nin hedefi "kullanıcı model seçmek istemiyor". Aşama 2–3 oturunca (artık K3–K4) model menüleri, kategoriler ve
kipler ana menüden Yardım → Gelişmiş altına iner; ana ekranda yalnızca sohbet, iş klasörü ve durum çubuğu kalır.

```
Ana pencerede model seçimiyle ilgili menü ve düğmeleri (model menüleri, ajan kategorileri, varsayılan model, güç kipi)
Yardım → Gelişmiş alt menüsüne taşı; sağlayıcı seçici ve sansürsüz/güvenlik kipleri Ayarlar'a. Durum çubuğunda kullanılan
modelin adı ve ekran kartı kalır. Hiçbir işlevi silme, yalnızca yerini değiştir. `arayuz_denetimi` 0 hata; 626 eylem sayısı
azalabilir ama hiçbir eylemin kaybolmadığını eylem listesini önce/sonra karşılaştırarak göster.
```

**Bitti (eski Aşama 6):** ana menüde model seçimi yok; tüm eylemler Gelişmiş/Ayarlar altında bulunuyor; denetim 0 hata.

---

## Ölçüm defteri (her aşamadan sonra bir satır)

| Tarih | Aşama | Yönetici | İşçi | Sınav (hizli) | Süre | Not |
|---|---|---|---|---|---|---|
| 2026-09-27 | 1 (taban) | sohbet modeli (otomatik: qwen2.5:14b) | — | 15/30 (15 görev ×2, %50) | 7,7 + 7,9 dk | ilk ölçüm; süre sınırı olmasa 19/30; hep ✓ 5, hep ✗ 5, kararsız 5; --hepsi 9/20 |
| 2026-09-27 | K0 | — | — | koşulmadı (kod değişmedi) | — | birim 249 ✓ / 21 atlandı (`.venv`); arayüz denetimi 714 eylem, 0 hata |
| 2026-09-28 | K2 | — | — | koşulmadı (model seçimi değişmedi: sabitler birebir aynı) | — | birim 360 ✓ / 21 atlandı (`.venv`); arayüz denetimi 722 eylem, 0 hata; kademe bu makinede `yuksek` |

## Sonraya (aşamaları bölmemek için buraya)

- 3D baskı: dilimleme ve yazıcıya gönderme (OctoPrint/Klipper MCP).
- 2.8: `asistan/eski.py` ve K1 takma adlarını (`config`, `agent.describe_error/Cancelled/ollama_*`, `tools.ToolError/unescape_code`) kaldır; çağıranları `cekirdek/` yoluna geçir.
- Beceriyi çok adımlı plan olarak saklamak.
