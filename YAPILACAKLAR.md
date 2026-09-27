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

## Aşama 1 — Sınav seti: başarıyı sayıyla ölçmek ✓

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

**Bitti:** 20 görev tanımlı; `--hizli` 10 dakikanın altında; RAPOR.md'de ilk ölçüm var (kaç geçti önemli değil — bu taban
çizgisi); `yayinla.sh` eşiğin altında durduğunu bir deneme ile gösterdi.

---

## Aşama 2 — Yöneticiye en güçlü model, işçiye hızlı model ☐

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

**Bitti:** otomatik politikada sınav başarısı yerelden düşük değil (beklenti: belirgin yüksek); plan kartı yöneticiyi
gösteriyor; anahtarsız bağlantı hiçbir zaman yönetici seçilmiyor (unittest).

---

## Aşama 3 — Araç çağıramayan modeller için şema-kısıtlı karar ☐

Gemma 4, gemma3, dolphin3 araç çağrısını metin olarak yazıyor. Ollama'nın `format` alanına JSON şeması verilince model
gramer kısıtıyla üretir; "yazdı ama yapmadı" büyük ölçüde biter. Plan zaten JSON; aynı yolu araç seçimine de uygula.

```
Şema-kısıtlı üretim. `agent.structured(messages, schema, model)`: Ollama'da `format=<JSON şeması>`; OpenAI uyumlu
bağlantıda `response_format: {type: "json_schema"}`; desteklemeyen sağlayıcıda talimat + ayrıştırma + bir kez yeniden deneme.
Kullan: `manager.needs_plan`, plan üretimi, `_completion_check` kararı (üçü zaten JSON istiyor; şemayı kesinleştir).
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

**Bitti:** kartlarda 0/3 olan modeller ≥ 2/3; 3/3 modellerde gerileme yok; `yazdi-ama-yapmadi` görevi Gemma ile geçiyor.

---

## Aşama 4 — Tarayıcı: ürün listelerini güvenilir okumak ☐

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

**Bitti:** üç internet görevi 3/3 geçiyor; boş sonuçta cevap "bulunamadı", uydurma yok.

---

## Aşama 5 — Bulut beyni gerçek sunucuya kurmak ☐

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

**Bitti:** bilgisayar kapalıyken telefondan bir araştırma isteği cevaplandı; `dogrula.sh` sunucuda tümü ✓.

---

## Aşama 6 — Arayüzü hedefe göre sadeleştirmek ☐

CLAUDE.md'nin hedefi "kullanıcı model seçmek istemiyor". Aşama 2–3 oturunca model menüleri, kategoriler ve kipler ana
menüden Yardım → Gelişmiş altına iner; ana ekranda yalnızca sohbet, iş klasörü ve durum çubuğu kalır.

```
Ana pencerede model seçimiyle ilgili menü ve düğmeleri (model menüleri, ajan kategorileri, varsayılan model, güç kipi)
Yardım → Gelişmiş alt menüsüne taşı; sağlayıcı seçici ve sansürsüz/güvenlik kipleri Ayarlar'a. Durum çubuğunda kullanılan
modelin adı ve ekran kartı kalır. Hiçbir işlevi silme, yalnızca yerini değiştir. `arayuz_denetimi` 0 hata; 626 eylem sayısı
azalabilir ama hiçbir eylemin kaybolmadığını eylem listesini önce/sonra karşılaştırarak göster.
```

**Bitti:** ana menüde model seçimi yok; tüm eylemler Gelişmiş/Ayarlar altında bulunuyor; denetim 0 hata.

---

## Ölçüm defteri (her aşamadan sonra bir satır)

| Tarih | Aşama | Yönetici | İşçi | Sınav (hizli) | Süre | Not |
|---|---|---|---|---|---|---|
| 2026-09-27 | 1 (taban) | sohbet modeli (otomatik: qwen2.5:14b) | — | 15/30 (15 görev ×2, %50) | 7,7 + 7,9 dk | ilk ölçüm; süre sınırı olmasa 19/30; hep ✓ 5, hep ✗ 5, kararsız 5; --hepsi 9/20 |

## Sonraya (aşamaları bölmemek için buraya)

- 3D baskı: dilimleme ve yazıcıya gönderme (OctoPrint/Klipper MCP).
- Araç fabrikası: hazır MCP sunucusunu kendisi kurmak; çalışan aracı güncellemek.
- Bilgisayardan buluta iş gönderme (araştırma).
- Beceriyi çok adımlı plan olarak saklamak.
