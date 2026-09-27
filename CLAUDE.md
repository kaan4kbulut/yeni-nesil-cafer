# YENİ NESİL CAFER — mimari ve kurallar

Python 3.12 + PySide6 masaüstü asistanı. Yerel modeller Ollama ile, bulut modelleri Claude / OpenAI uyumlu API'lerle
ve kullanıcının kendi hesabıyla giren resmi CLI programlarıyla (`cli:claude|cli:codex|cli:gemini`) çalışır. Kullanıcıyla her
zaman Türkçe konuşulur; kod yorumları Türkçedir. Python paketi `asistan`, iç ad `yeni-nesil-cafer` (`config.APP_ID`);
2.2'ye kadarki adı Yerel Asistan (eski klasörler ilk açılışta `config.migrate_dir` ile taşınır, anahtarlar
`keystore.OLD_SERVICE`'ten kopyalanır, kurulum betikleri eski kurulumu ve kısayolları siler).

Kurulu kopya `~/.local/share/yeni-nesil-cafer-app/` (kendi Python'u `python/bin/python3`). Kaynaktaki değişiklik kullanıcıya
ancak `paketleme/aktar.sh` (yedek alır, kopyalar, derler, yeniden başlatır; `--baslatma`: yalnızca kopyalar) ile ulaşır.
Her aşama git'e kaydedilir. Kurulum kendi kendine yeter: tam paket Python, paketler ve Ollama'yı içinde taşır; internet
paketi bunları sabit SHA ile kendisi indirir. Kullanıcıya hiçbir zaman komut yazdırılmaz, elle bir şey indirtilmez.

**Bu dosya kısa kalır.** Buraya yalnızca kalıcı kural, karar ve harita yazılır. Tarihli deneyler, ölçümler, tek seferlik hata
hikâyeleri `NOTLAR/<tarih>.md`'ye; durum tablosu ve yol haritasının ayrıntısı `NOTLAR/mimari-ayrintilar.md`'de. Bir NOTLAR
dosyasını yalnızca o konuda çalışırken oku. **Şu anki iş sırası `YAPILACAKLAR.md`'de; oturuma oradan başla.**
Yeni özellik istemeden önce oradaki aşama bitmiş olmalı.

## Hedef: şirket gibi çalışan tek bir sistem

Kullanıcı model seçmek istemiyor. İsteği anlayan bir yönetici, işi parçalara ayırıp her parçayı uygun modele ve araca verir,
sonucu doğrular. Model yalnızca "yapıyorum" diye yazıp araç çağırmıyorsa bu sistemin hatasıdır: program araç kullanabilen
modeli bulup işi ona yönlendirmelidir.

1. **Yönetici ajan** (`manager.py`): plan → alt görevler → her birine model/araç ata → sonucu kontrol et → düzelt. Adımlar
   arayüzde görünür. Yöneticide eldeki en güçlü model (CLI/bulut ya da büyük yerel), işçilerde hızlı yerel modeller.
2. **Model yönlendirici** (`cards.py`, `roster.py`, `categories.py`): her modelin kimlik kartı — neye iyi (araç, kod,
   görme, özet, Türkçe, yaratıcı yazı), hız (token/sn, bu donanımda ölçülmüş), maliyet, sansürsüz mü — programın kendi
   sınavına dayanır, üreticinin beyanına değil (Ollama'nın `capabilities: tools` bilgisi araç çağırdığını göstermez).
   Model yoksa `ollama pull` önerir; indirme ve kurma yalnızca kullanıcının düğmesiyle.
3. **Araç kaydı** (`registry.py`, en kritik parça): her araç tek yerde — ad, açıklama, JSON şeması, çalıştırıcı, risk sınıfı
   (okur / yazar / siler / calistirir / kurar / internete gönderir). MCP uyumlu; hazır MCP sunucuları eklenti gibi takılır,
   asistanın yazdığı araçlar da aynı biçimdedir.
4. **Araç fabrikası** (`factory.py`): önce hazır çözüm (pip paketi, MCP sunucusu, Ollama modeli) → yoksa Python araç + test
   → internetsiz sandbox → "şu aracı ekliyorum / şu paketi kuruyorum" diye kullanıcıya sor → onaylanırsa kayıt, git.
5. **Beceri kütüphanesi** (`learning.py`, `definitions.py`): biten çok adımlı işler tarif olarak saklanır ve yeniden kullanılır.
6. **Hafıza** (`memory_db.py`): tercihler, projeler, hangi aracın neden başarısız olduğu; SQLite + `nomic-embed-text`.

**Tek gövde, iki beyin.** Araç kaydı, beceriler, hafıza ve güvenlik kuralları ortak kod; yerel ile bulut asistan arasında
değişen yalnızca yönetici modeli ve erişilebilen araçlar. Beceri ve hafıza bilgisayar açıkken sunucuyla eşitlenir. Bulut
asistana başlangıçta bilgisayara komut gönderme yetkisi yok; yerel dosya gerektiren işler kuyruğa alınır ve bilgisayarda ASLA
kendiliğinden çalışmaz (☁ → "yap" → yeni sohbet). Hassas dosyalar hep yerelde, internet araştırması ve karmaşık planlama
bulutta. Haftalık liste 5 yerel + 5 bulut, her biri kendi sınav setinde.

## Güvenlik — pazarlık dışı kurallar

- Asistanın yazdığı yeni kod önce sandbox'ta test edilir, doğrudan kullanıcının sisteminde çalıştırılmaz.
- Paket kurma, dosya silme ve internete veri gönderme kullanıcının onayıyla yapılır. Kullanıcı güvendiği işlemleri "otomatik
  onay" listesine alabilir. Güvenlik ajanı (`security.py`) açıkken onayları risk sınıfına göre o verir; sansürsüz modda
  güvenlik ajanı çalışamaz (aynı ekran kartına iki model sığmaz), o zaman riskli adımlar tek tek kullanıcıya sorulur.
- Asistanın kendi koduna yaptığı her değişiklik git ile sürümlenir; bozulursa geri alınır.
- Çekirdek (yönetici döngüsü, güvenlik kuralları, onay mantığı, `hooks.json`) asistanın kendisi tarafından değiştirilemez;
  asistan yalnızca araç ve beceri ekleyebilir. Program kendi kodunu DEĞİŞTİRMEZ: sorunu algılar, geliştiriciye rapor hazırlar
  (`problem_report.py`). Bir sorun raporu gelirse rapordaki kanıtlardan başla, düzelt, test et, aktar, paketleri güncelle.
- Onay kuralları yalnızca `permissions.py`'de (tek izin hattı: yasak → ✓ bekletme → güvenlik ajanı → kullanıcı).
  Tarayıcıda satın alma/ödeme, mesaj/paylaşım, hesap/silme, giriş/indirme her zaman kullanıcıya sorulur (`browser.gate`).
- Reşit olmayanları çağrıştıran içerik, hangi model ve modda olursa olsun engellenir (`imagegen.check_prompt`).
  Deepfake yalnızca tespit, ses klonlama yok.
- Her indirme sabit sürüm + SHA-256 (Ollama, python-build-standalone, TripoSR, Node, Codex, Gemini CLI, güncelleme paketi).

## Kalıcı kararlar (kullanıcının istekleri — değiştirme)

- **Model çıktısına güvenme, kodla denetle.** Doğrulama önce programın kanıtıyla (araç sonuçları, değişen dosyaların içeriği,
  STL kapalı mı, ölçü), sonra modelin kararıyla. Görme modelinin "evet, doğru" demesi kanıt değildir.
- Adımda yalnızca kullanıcının isteğinde geçen dosyalar istenir; planlayıcı yardımcı dosya uydurmaz; iki adım başarısızsa
  kalan adımlar atlanır; sonuç yoksa dürüstçe "yapılamadı". Yeni alan = denenmiş kod iskeleti içeren hazır beceri.
- Her sohbet kendi iş klasöründe (`<çalışma klasörü>/<kategori>/<başlık>-<id>`), diğer işler salt okunur; "… devam et"
  aynı projede sürer. Sonuçlar `<masaüstü>/YENİ NESİL CAFER/Sonuçlar/`e KOPYA (`results.py`); masaüstünde başka klasör yok.
- Eski mesajlar silinmez, özetlenir (`_ozetlendi`/`_ozet`); özeti hep yerel model yazar; kullanıcının kendi mesajları en son
  kırpılır. `ASISTAN.md` dosyaları talimata genelden özele eklenir (en çok 3 düzey, 4000 karakter).
- Program her zaman en güçlü ekran kartında çalışır ve bunu kendisi denetler (`gpu.py`); resim üretimi ile Ollama aynı anda
  karta sığmaz, biri boşaltılır. `gpu.fault()` varsa hafif mod ve "bilgisayarı yeniden başlat".
- CLI ajanları (`claude -p`, `codex exec`, Gemini CLI) yalnızca kullanıcının sohbette gönderdiği istekte çalışır; bulut kuyruğuna
  ya da zamanlanmış işe bağlanmaz. Onay beklenen tur salt okunur. Claude/Gemini API'sine hesapla giriş yok.
- Ağır motorların kurulumu (TripoSR, resim, dikte modeli, CLI ajanları) YALNIZCA kullanıcının düğmesiyle.
- Arayüz: sağ panelde üç sekme (adımlar · kayıt · klasörler); canlı önizleme yalnızca görsel iş sürerken açılır, sürekli
  bölüme ya da sekmeye çevirme. İş sürerken Enter işi durdurmaz, mesaj sıraya girer; durdurmak ■ ya da Esc.
  Yeni metot konusunun dosyasına (`gui/window_*.py`); Qt sinyalleri yalnızca `MainWindow` gövdesinde. 3D önizleme ekransız
  kipte çizilmez: 3D'yi gerçek ekranda doğrula.
- Herkese açık GitHub deposu; sürümler kod paketiyle (`updates.py`, 15 sn açık kalamazsa geri alma); büyük paket yalnızca ilk
  kurulum. Yayın `paketleme/yayinla.sh`: testler geçmeden, atlanan test varken ya da sınav (`testler/sinav`) eşiğin
  altındayken yayın yok (`--deneme` yalnızca kapıyı dener).

## Dosya haritası (`asistan/`)

- Çekirdek döngü: `agent.py` (tek araç yolu `_execute_tool`, `_clean`, `fit_context`, `_compact`, `lean`), `manager.py`
  (plan/doğrulama/`_escalate`), `work.py` (iş klasörleri `chat_folder`, grup görevi), `storage.py` (sohbetler JSON),
  `choices.py` (sorudaki seçenekler → baloncuk), `suggest.py` (karşılama önerileri).
- Modeller: `cards.py` (sınav), `roster.py` (`worker_for`, `manager_for`, `stronger`, `default`), `categories.py`,
  `connections.py`, `catalog.py` (bulut model kataloğu), `model_updates.py` (günlük model listesi), `specialists.py`
  (uzman modele danışma), `profiles.py` (yardımcı ajanlar), `cli_agents.py`, `accounts.py` (OpenRouter OAuth, HF cihaz
  kodu), `ctxprobe.py`.
- Araçlar: `registry.py`, `tools.py` (`Toolbox._tool_*`), `factory.py`, `mcp.py`, `browser.py`, `apps.py` (`install_app`),
  `api_catalog.py` (hazır HTTP API'leri), `libraries.py` (Python kütüphaneleri), `hooks.py`, `definitions.py` (dosyayla
  ajan/beceri), `beceriler/` (hazır beceriler; ör. `3d-baski`).
- Hafıza/öğrenme: `memory_db.py`, `learning.py`.
- Güvenlik: `permissions.py`, `security.py`, `askpass.py`, `keystore.py`.
- Görsel/3D/ses: `imagegen.py`, `inspect_output.py`, `decor3d.py`, `figure3d.py` + `figure3d_worker.py`, `dictation.py` +
  `dictation_server.py`, `gpu.py`.
- Bulut: `cloud_server.py` (API, web, Telegram, kuyruk), `cloud_sync.py`; `sunucu/kur.sh`, `sunucu/BENIOKU.md`.
- Sistem/dağıtım: `sysinfo.py` (sistem taraması), `power.py` (pilde hafif mod), `results.py`, `problem_report.py`,
  `updates.py`, `bootstrap.py` (yalnızca standart kütüphane), `config.py`; `paketleme/` (`aktar.sh`, `paketle.py`,
  `yayinla.sh`, `bulut_paketi.sh`), `main.py` (`rollback_if_needed`).
- Arayüz (`gui/`): `window.py` (çekirdek) + `window_help/models/bar/modes/chats/run/group/accounts.py`, `worker.py`
  (ajanı ayrı iş parçacığında çalıştırır), `panels.py` (sağ panel), `sidebar.py` (sol panel), `chat.py`, `media_panel.py`,
  `work.py` (grup alanı), `dialogs.py`, `setup_wizard.py` (ilk kurulum), `tour.py` (sürüm tanıtımı), `model_advisor.py`,
  `cards_dialog`/`categories_dialog`/`factory_dialog`/`learning_dialog.py` (pencereler), `share.py` (paylaş),
  `sysmon.py` (durum çubuğu), `theme.py` + `icons.py` + `widgets.py` (görünüm), `assets/model3d.qml`.
- Testler: `testler/` (unittest), `testler/arayuz_denetimi.py` (her sürümden önce, 0 hata), `testler/sinav/` (gerçek
  görevli sınav: `calistir.py --hizli`, RAPOR.md, eşik `esik.json`). Komut, HEP kurulu programın Python'uyla (`.venv`
  3.14: ajan kütüphaneleri yüklenmez, 3D testleri atlanır):
  `~/.local/share/yeni-nesil-cafer-app/python/bin/python3 -m unittest discover -s testler -v`.

## Aşamalar (ayrıntı: `NOTLAR/mimari-ayrintilar.md`)

0. Git + aktarma ✓ · 1. Araç kaydı + MCP ✓ · 2. Yönetici döngüsü ✓ · 3. Model yönlendirici: kartlar ve `roster` ✓, **yöneticiye
en güçlü / işçiye hızlı model politikası ve adımların farklı modellere dağıtımı EKSİK** · 4. Hafıza + beceriler ✓ ·
5. Araç fabrikası ✓ (MCP sunucusunu kendisi kurma ve çalışan aracı güncelleme eksik) · 6. Bulut beyin: kod ✓, **gerçek
sunucu kurulmadı**. Ek: BrowserAgent, hook'lar, dosyayla ajanlar, dikte, 3D süs/figür, sonuç toplama, internet kurulumu,
otomatik güncelleme ✓ (NOTLAR/2026-09-26 ve 27).

## Araç ekleme kuralı

Yeni yerleşik araç: tanımı `tools.py`'de `REGISTRY.add(spec, risk, (etiket, bitince))` ile yaz, çalıştırıcıyı
`Toolbox._tool_<ad>` olarak ekle; ajanın durumuna (geri çağrılar, hafıza, alt ajan) ihtiyaç duyuyorsa `Agent._tool_<ad>`,
araca özgü ek onay kapısı gerekiyorsa `Agent._gate_<ad>`. Onay kuralları yalnızca `permissions.py`'de. Onay listesi,
etiket ya da doğrulama için başka bir yere dokunma. Fabrika araçları `f_` önekli, hep `calistirir` risk sınıfında.

## Hâlâ geçerli tuzaklar (tam metin ve tarihçe: `NOTLAR/mimari-ayrintilar.md`)

- NVIDIA sürücüsü bellek baskısında bozulabilir (Xid 62/154, "Reset required"; Ollama sessizce CPU'ya düşer). Yalnızca
  yeniden başlatma düzeltir. `gpu.fault()` algılar; testler onu taklit etmeli.
- Testler gerçek veri klasörüne yazmamalı: her test dosyası `asistan`'ı içe aktarmadan ÖNCE XDG_CONFIG_HOME/XDG_DATA_HOME'u
  geçici klasöre alır. Kütüphane yolu her zaman gerçek kurulumdan; sessizce atlanan test kabul edilmez.
- Anahtarsız ya da 401 alan bağlantı yönlendiricide, menülerde ve varsayılanda atlanır (`Connection.usable`).
- Gemma 4 sistem talimatı olmadan araç çağırmaz, komutu metin yazar; bozuk çağrıda dakikalarca tamponlayabilir
  (`STALL_SECONDS`, `NUM_PREDICT`, `_CLAIMS_WORK`). Kartlar: gemma3/dolphin3 araç 0/3, sansürsüz gemma4 1/3.
- Sistem talimatı + araç tanımları ~5.600 token; 8K bağlamda geçmişe ~1.100 token kalır → `LEAN_CTX` altında `agent.lean`.
- 4B modeller işçi ve denetçi olarak zayıf; yönetici hâlâ sohbet modeliyle planlıyor. Kalıcı çözüm: YAPILACAKLAR K3–K4.
- Küçük modeller dosya adını kısaltır, aracı `run_python` içinde işlev gibi çağırır, planı ara sıra Çince yazar.

## Açık işler (sıra ve talimatlar: `YAPILACAKLAR.md`, K serisi)

1. Yöneticiye en güçlü model politikası; işçi/denetçi ayrımı (K3).
2. Araç çağıramayan modeller için şema-kısıtlı karar (K4).
3. BrowserAgent: ürün listelerini (ad + fiyat) güvenilir okumak (K5).
4. Bulut sunucuyu gerçek sunucuda kurmak (K8).
5. 3D baskı: dilimleme ve yazıcıya gönderme (OctoPrint/Klipper MCP sunucuları) (Sonraya).

## Mimari v3 — kademeli + bulut (K serisi)

Hedef mimarinin tek kaynağı `docs/MIMARI.md`, şemalar `docs/SEMALAR.md`, aşama planı `YAPILACAKLAR.md` (K0–K10), mevcut
durum haritası `NOTLAR/MEVCUT_DURUM.md` (K0'da yazılır). Aşağıdaki kurallar `docs/MIMARI.md` §11'in özeti. Parantezdeki
aşamada kurulan yol (`cekirdek/`, `ayar/modeller.json`, `yetenekler/`, `guvenlik.py`, `analiz/hata.py`) henüz yoksa o yol
kurulana kadar yukarıdaki kurallar ve dosya haritası geçerlidir.

1. **Çekirdek arayüz bilmez** (K1). `asistan/cekirdek/` içinde `PySide6`, `Qt`, `fastapi` import'u olamaz. Masaüstü, web ve
   CLI çekirdeği çağırır.
2. **Model adı koda gömülmez** (K2). `ayar/modeller.json`'dan, kademe ve role göre okunur.
3. **Kademe farkındalığı** (K2). Ağır iş (`embedding`, tarayıcı, uzun bağlam, büyük model) `profil.kademe()`'ye bakar;
   `dusuk`'te kapalıdır.
4. **Planlayıcı yalnızca kayıtlı yetenekleri çağırır** (K5). Her yetenek `yetenekler/<ad>/manifest.json` + `calistir.py` + test.
5. **Kurulum, silme, ağ üzerinden gönderme `guvenlik.py`'den geçer** (K6). Onaysız kurulum yok. Üretilen yetenekler
   sandbox'ta. Tek izin hattı kuralı sürer: `guvenlik.py` `permissions.py`'nin yanında ikinci bir onay yolu açmaz.
6. **Her başarısız adım `analiz/hata.py`'den geçer** (K6). Yeni bir hata deseni görürsen sınıflandırıcıya ekle.
7. **Her yeni modülün testi olur.** `/kontrol` yeşil değilse aşama bitmedi.
8. **Çalışan davranışı bozma.** Refaktör: yenisini yanına kur → eski çalışır kalsın → sonra taşı.
9. **Ağır bağımlılık çekirdeğe girmez.** Yetenek gereksinimi olarak isteğe bağlı kalır.
10. **Türkçe adlandırma** (yeni kodda), İngilizce yalnızca kütüphane API'lerinde.

## Çalışma düzeni

- **Bir oturum = bir aşama.** Aşamaya `/asama K<n>` ile başla. Aşama bitmeden başka aşamaya dokunma; başka bir sorun
  görürsen `NOTLAR/`'a yaz, geç.
- **Görev listesi zorunlu.** 3 adımdan uzun her işte `TaskCreate`/`TaskUpdate` kullan; başladığın maddeyi `in_progress`,
  bitirdiğini `completed` yap. Terminaldeki ilerleme çubuğu (`.claude/ilerleme/`) bu listeden beslenir; güncellemezsen
  kullanıcı nerede olduğunu göremez.
- Büyük refaktörden önce `mimar` ajanıyla plan çıkar; bitince `denetci` ajanıyla denetle.
- Hata görünce `/hata-analiz`. Yeni yetenek gerekince `/yetenek-ekle`. Aşama sonunda `/kontrol` (testler yine kurulu
  programın Python'uyla; bkz. dosya haritası → Testler).
- Commit atma; commit mesajı öner. Kullanıcı "commitle" derse at.
- Bir şeyi tahmin etme; dosyayı aç, komutu çalıştır, sonucu göster.
- Kullanıcıya soru soracaksan tek soru sor, geri kalan kararları makul varsayımla ver ve varsayımını yaz.

Komutlar: `/asama K3` (aşamayı plan → kod → test → not sırasıyla uygular) · `/kontrol` (`hizli`) (test, import dumanı,
çekirdek-arayüz ayrımı, model adı, manifest doğrulama) · `/hata-analiz <log|metin|son>` (hatayı sınıflandırır, kök nedeni
kanıtlar, düzeltir, sınıflandırıcıya ekler) · `/yetenek-ekle <ad> "<açıklama>"` (manifest + kod + test ile yetenek iskeleti)
· `/profil` (`benchmark`) (donanım profili, kademe, gerçekle karşılaştırma) · `/sunucu` (`docker`) (web modunu ayağa
kaldırıp uçtan uca test eder).

Ajanlar: `mimar` — kod yazmaz; aşama öncesi etkilenecek dosyalar, riskler, sıra. `denetci` — kod değiştirmez; diff'i mimari
kurallara ve testlere karşı denetler, GEÇTİ/ŞARTLI/KALDI verir.
