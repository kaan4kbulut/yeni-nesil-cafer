# YENİ NESİL CAFER — mimari, kurallar ve yol haritası

(2.2'ye kadarki adı: Yerel Asistan. İç ad `yeni-nesil-cafer` (`config.APP_ID`); eski `yerel-asistan` klasörleri
ilk açılışta `config.migrate_dir` ile taşınır, anahtarlar `keystore.OLD_SERVICE`'ten kopyalanır, kurulum betikleri
eski kurulumu ve kısayolları siler. Python paketi `asistan` adını korur.)

Python 3.12 + PySide6 masaüstü asistanı. Yerel modeller Ollama ile, bulut modelleri Claude / OpenAI uyumlu
API'lerle çalışır. Kullanıcıyla her zaman Türkçe konuşulur; kod yorumları Türkçedir.

Kurulu kopya: `~/.local/share/yeni-nesil-cafer-app/` (kendi Python'u `python/bin/python3`). Kaynaktaki değişiklik
kullanıcıya ancak kurulu kopyaya aktarılıp program yeniden başlatılınca ulaşır: `paketleme/aktar.sh` (yedek alır,
kopyalar, derler, yeniden başlatır; `--baslatma` ile yalnızca kopyalar). Her aşama git'e kaydedilir. Kurulum paketleri kendi kendine
yetmeli (Python, paketler, Ollama paketin içinde; kullanıcıya bir şey indirtilmez).

## Hedef: şirket gibi çalışan tek bir sistem

Kullanıcı model seçmek istemiyor. İsteği anlayan bir yönetici, işi parçalara ayırıp her parçayı uygun modele ve
araca verir, sonucu doğrular. Model yalnızca "yapıyorum" diye yazıp araç çağırmıyorsa bu sistemin hatasıdır:
program araç kullanabilen modeli bulup işi ona yönlendirmelidir.

### Parçalar

1. **Yönetici ajan (beyin).** Döngü: plan → alt görevler → her birine model/araç ata → sonucu kontrol et →
   gerekirse düzelt. Adımlar arayüzde görünür. Yöneticide eldeki en güçlü model (bulut ya da büyük yerel),
   işçilerde hızlı yerel modeller.
2. **Model yönlendirici.** Her modelin bir kimlik kartı var: neye iyi (araç kullanma, kod, görme, özet,
   Türkçe, yaratıcı yazı), hız (token/sn, bu donanımda ölçülmüş), maliyet, sansürsüz mü. Kart, üreticinin
   beyanına değil programın kendi kısa sınavlarına dayanır. Gerekli model yoksa `ollama pull` önerir.
3. **Araç kaydı (en kritik parça).** Her araç tek bir yerde, standart biçimde tanımlanır: ad, açıklama, JSON
   şeması, çalıştırıcı, risk sınıfı (okur / değiştirir / siler / internete gönderir). Biçim MCP ile uyumlu olur;
   hazır MCP sunucuları eklenti gibi takılır, asistanın yazdığı araçlar da aynı biçimdedir.
4. **Araç fabrikası.** Eksik araç fark edilince: önce hazır çözüm aranır (pip paketi, MCP sunucusu, Ollama
   modeli); yoksa Python ile araç + testi yazılır; ayrı bir sanal ortamda (sandbox) test edilir; testler geçerse
   kullanıcıya "şu aracı ekliyorum / şu paketi kuruyorum" diye sorulur, onaylanırsa kayda eklenir.
5. **Beceri kütüphanesi.** Başarıyla biten çok adımlı işler tarif olarak saklanır ve benzer işte yeniden kullanılır.
6. **Hafıza.** Tercihler, projeler, hangi aracın neden başarısız olduğu. Hedef: SQLite + embedding ile anlamsal
   arama (ör. `nomic-embed-text`).

### Tek gövde, iki beyin (yerel + bulut)

Araç kaydı, beceriler, hafıza ve güvenlik kuralları ortak koddur. Yerel ve bulut asistan arasında değişen tek
şey yönetici modeli ve erişilebilen araçlardır. Beceri ve hafıza, bilgisayar açıkken sunucuyla eşitlenir.
Bulut asistana başlangıçta bilgisayara komut gönderme yetkisi verilmez. Yerel dosya gerektiren işler, bilgisayar
açılınca yerel asistan yapsın diye kuyruğa alınır. Yönlendirme kuralı: hassas dosyalar hep yerelde, internet
araştırması ve karmaşık planlama bulutta. Haftalık model listesi 5 yerel + 5 bulut olarak, her biri kendi sınav
setinde değerlendirilir.

## Güvenlik — pazarlık dışı kurallar

- Asistanın yazdığı yeni kod önce sandbox'ta test edilir, doğrudan kullanıcının sisteminde çalıştırılmaz.
- Paket kurma, dosya silme ve internete veri gönderme kullanıcının onayıyla yapılır. Kullanıcı güvendiği
  işlemleri "otomatik onay" listesine alabilir. Güvenlik ajanı (`security.py`) açıkken onayları risk sınıfına
  göre o verir; sansürsüz modda güvenlik ajanı çalışamaz (aynı ekran kartına iki model sığmaz), o zaman riskli
  adımlar tek tek kullanıcıya sorulur.
- Asistanın kendi koduna yaptığı her değişiklik git ile sürümlenir; bozulursa geri alınır.
- Çekirdek (yönetici döngüsü, güvenlik kuralları, onay mantığı) asistanın kendisi tarafından değiştirilemez;
  asistan yalnızca araç ve beceri ekleyebilir.
- Reşit olmayanları çağrıştıran içerik, hangi model ve modda olursa olsun engellenir (`imagegen.check_prompt`).

## Bugünkü durum → hedef

| Parça | Bugün | Eksik |
|---|---|---|
| Yönetici | `manager.py` (sohbette çok parçalı iş: plan → adım adım yap → doğrula → bir kez düzelt → özet; plan kartı), `work.py` (grup görevi) | Yöneticiye en güçlü modeli, işçilere hızlı modeli seçmek (Aşama 3); adımları farklı modellere dağıtmak |
| Yönlendirici | `cards.py` (programın kendi sınavı: araç 3 görev, plan, Türkçe, hız), `roster.py` (kartlara göre; `worker_for`, `manager_for`), `categories.py` (7 kategori, bu donanım için sıralı modeller) | Kod/görme/Türkçe kalitesini ölçen daha zor sınavlar; adım başına farklı kategori modeli |
| Araç kaydı | `registry.py` tek kayıt; onay/eylem/etiket/doğrulama oradan; MCP araçları `sunucu__araç` adıyla; `agent._execute_tool` tek yol (izin → `_gate_<ad>` → `Agent._tool_<ad>` ya da Toolbox) | — |
| Araç fabrikası | `factory.py` (`request_tool`: hazır çözüm → yaz → paket onayı → internetsiz sandbox testi → kullanıcı onayı → kayıt, git) | Hazır MCP sunucusunu kendisi kurmak (bugün yalnızca öneriyor); çalışan aracı güncelleme |
| Beceriler | `learning.py` (beceriler + başarısızlıklar, anlamsal arama; `planning_prompt` yöneticinin planına girer) | Beceriyi çok adımlı plan olarak saklamak (bugün: çalışan kod ve adımlar) |
| Hafıza | `memory_db.py` (SQLite `hafiza.db` + `nomic-embed-text`; model yoksa kelime araması), `learning.memory_prompt(istek)` | Sohbet geçmişinde arama |
| Güvenlik | `permissions.py` (tek izin hattı: yasak → ✓ bekletme → güvenlik ajanı → kullanıcı; `agent._permit` yalnızca uygular), `security.py` (denetçi model yalnızca orta/yüksek riskte yüklenir), onay kipleri, `askpass.py`; proje ve fabrika araçları git'te | Çekirdek koruması kodla (bugün: programın kodu asistana salt okunur) |
| Bulut beyin | `cloud_server.py` (sunucu: API, web sayfası, Telegram botu, kuyruk), `cloud_sync.py` (eşitleme, işler), `sunucu/kur.sh` | Gerçek sunucuda kurulum; bilgisayardan buluta iş gönderme (araştırma) |

## Yol haritası (her aşama çalışır halde biter)

0. **Git** ✓: depo kuruldu, `paketleme/aktar.sh` ile aktarma.
1. **Araç kaydı + MCP** ✓: `registry.py` (tek kayıt: şema, risk sınıfı, Türkçe etiket, kaynak), `mcp.py` (stdio + HTTP
   istemcisi, `~/.config/yeni-nesil-cafer/mcp.json`, Claude Desktop biçimi), Ayarlar'da MCP bölümü, `testler/`.
2. **Yönetici döngüsü** ✓: `manager.py` — `needs_plan` (çok parçalı mı?), JSON plan (başlık, talimat, bitti ölçütü),
   adımlar aynı ajanla program mesajı (`_program`) olarak, doğrulama önce programın kanıtıyla (araç sonuçları, bu turda
   değişen dosyaların içeriği) sonra modelin JSON kararıyla; plan kullanıcı mesajında `_plan` alanında saklanır ve
   sohbette `PlanCard` olarak çizilir. `_` ile başlayan mesaj alanları sağlayıcıya gönderilmez (`agent._clean`).
3. **Model yönlendirici** ✓: `cards.py` kartları (boşken arka planda, Yardım → Model kartları), `roster.worker_for`
   (sohbet modeli araç kullanamıyorsa işi yapan model; metni `ask_specialist` → `writer_model` ile yine sohbet modeli
   yazar), `roster.manager_for`; `categories.py`: ajanlar 7 alanda (dil, görü, veri, ses, problem/kod, otonom,
   üretken), her alanın 12 GB ekran kartı için sıralı model listesi (`categories.models_for` donanıma göre süzer) ve ek kütüphaneleri (Yardım → Ajan
   kategorileri; indirme ve kurma yalnızca kullanıcının düğmesiyle). Deepfake yalnızca tespit, ses klonlama yok.
4. **Hafıza + beceri kütüphanesi** ✓: `memory_db.py` (tercih/bilgi/ders/beceri/hata tek tabloda, float32 vektör,
   eksik vektörler aramada tamamlanır), eski JSON'lar bir kez içe aktarılır; talimata tercihler hep, bilgiler isteğe
   göre; yönetici plan çıkarırken işe yarayan tarifleri ve başarısız yolları görür, başarısız adımı kendisi kaydeder
   (Hafıza ve öğrenme → Başarısızlıklar). Eşikler `learning.py` başında, gerçek ölçümle.
5. **Araç fabrikası** ✓: `factory.py` + `request_tool` aracı. Araçlar `f_` önekli, `DATA_DIR/arac-fabrikasi/araclar/<ad>/`
   (arac.py, test_arac.py, arac.json; klasör git deposu), paketleri ayrı `paketler/` klasöründe, her zaman `calistirir`
   risk sınıfında. Test Linux'ta `unshare -rn` ile internetsiz, 60 sn sınırlı; test geçmeyen araç kullanıcıya hiç
   sorulmaz. Yazar: yönetici modeli (yerel öncelik), olmazsa bağlı Claude. Yardım → Araç fabrikası.
6. **Bulut beyin** ✓ (kod ve yerel deneme; gerçek sunucu kurulmadı): aynı yönetici/ajan sunucuda, kısa talimat
   (`agent.base_system`), araçlar yalnızca web_search, fetch_url, remember, queue_for_computer. API Bearer anahtarlı;
   Telegram yalnızca `/baglan <kod>` ile eşleşen sohbete cevap verir; web ve program bağlantısı Tailscale üzerinden
   (sunucu Tailscale IP'sine bağlanır). Hafıza iki yönlü eşitlenir (`memory_db.changes_since/apply_changes`, silme izi).
   Kuyruktaki işler bilgisayarda ASLA kendiliğinden çalışmaz: durum çubuğu ☁ → "yap" → yeni sohbet → sonuç geri.
   Kurulum: `paketleme/bulut_paketi.sh` → sunucuda `sudo ./sunucu/kur.sh` (rehber: `sunucu/BENIOKU.md`).

## BrowserAgent (2026-09-26)

`browser.py` (Playwright + Chromium; Chromium programın `tarayici/` klasöründe, 658 MB — pakete gömerken
`chromium_headless_shell-*` çıkarılabilir, tarayıcı hep görünür), kalıcı profil `DATA_DIR/tarayici-profili`, yalnızca
http(s). Onay kapısı `browser.gate` (kullanıcı kararı: satın alma/ödeme, mesaj/paylaşım, hesap/silme, giriş/indirme hep
sorulur). Yönetici tarayıcı işlerini `manager.is_browser_task` ile tanır, bölmeden `_via_browser` ile Tarayıcı ajanına
verir ve sonucu doğrular (boş kalıp `[Fiyat]` ya da sayfadan okunmamış veri → bir kez yeniden, sonra dürüst "yapılamadı").
Gerçek denemeler (gemma4:12b): DuckDuckGo'da arama + ilk 3 sonuç ✓ (25 sn). Hepsiburada: site içi arama bir denemede
çalıştı, ürün adlarını okuyamadı; doğrulama uydurmayı yakaladı. Bilinen sınır: kendini yeniden çizen sayfalarda öğe
numaraları kayar (ajan yeniden okuyarak aşar, güvenilir değil); ürün kartlarının adı/fiyatı eşleştirilmeli.

## Açık işler

1. BrowserAgent: ürün listelerini (ad + fiyat) güvenilir okumak.
2. Bulut sunucusu gerçek bir sunucuda kurulmadı (`sunucu/BENIOKU.md`).
3. 3D baskı: dilimleme ve yazıcıya gönderme (yazıcı markasına göre; OctoPrint/Klipper için hazır MCP sunucuları var).

## İş klasörleri ve proje hafızası (2026-09-26)

Her yeni sohbet `<çalışma klasörü>/<kategori>/<başlık>-<id>` klasöründe çalışır (`work.chat_folder`, kategori:
kenar çubuğu klasörü ya da `work.guess_category`); `Conversation.work_dir` boşsa eski sohbet, kök klasör. Model
yalnızca kendi klasörüne yazar, diğer işler salt okunur (`WORK_DIR_NOTE`). Neden: model çalışma klasöründe
bulduğu eski işin dosyalarını yeni istekle karıştırıyordu. Her iş klasörü hafızada `proje` kaydıdır
(`learning.save_project/find_project`); "… devam et" isteği anlamca + ortak konu kelimesiyle eşleşirse yeni
klasör açılmaz, o projede sürer. Bağlam kırpmada (`agent.fit_context`) ▶/↻ mesajları istek sayılmaz, kullanıcının
kendi mesajları en son atılır.

## Bağlam özetleme ve ASISTAN.md (2026-09-26)

Ollama turu başında geçmiş bağlama sığmayacaksa ve en az `COMPACT_MIN` eski mesaj varsa (`agent._compact`), son
istekten önceki turlar sohbet modeline özetletilir. Eski mesajlar SİLİNMEZ: `_ozetlendi` işaretiyle sohbette
görünür, `_clean`/`fit_context` onları modele göndermez; yerlerine `_ozet` işaretli program mesajı gider ve
`fit_context` onu en son çare kırpmada da korur. Dökümde (`agent.transcript`) kullanıcının kendi yazdıkları en son
kısalır (canlı deneme: ilk mesajdaki "Bambu Lab A1" en eskiler atılınca özetten düşmüştü). Özet uzunluğu geçmişe
kalan bütçeye göre 80–250 kelime. Özet alınamazsa kırpma yine devrede.
Bulut: OpenAI uyumlu bağlantılar da `_compact` + `fit_context` kullanır; bağlam `agent.api_context` (model kataloğu
`cloud.index`/`free`, yoksa 32K); sağlayıcı 400/413 + "context/too long/n_ctx" derse bütçe yarıya (en az 4K, oturum
boyunca `_API_CTX`), özetlenip yeniden denenir. Claude "prompt is too long" → bir kez zorla özetle, yeniden dene.
Özeti her zaman yerel Ollama modeli yazar ve kendi bağlamını aşmaz (bulutun 1M'si Ollama'ya verilmez).
`ASISTAN.md`: iş klasörü → kategori → çalışma klasörü (en çok 3 düzey, çalışma klasörünün dışına çıkmaz) içindeki
dosyalar genelden özele sistem talimatına eklenir (`agent.instruction_files`, dosya başına 4000 karakter).

## Hook'lar (2026-09-26)

`hooks.py`, ayar `~/.config/yeni-nesil-cafer/hooks.json` (Claude Code biçimi: olay → [{matcher, hooks: [{type: command,
command, timeout}]}]). Olaylar: UserPromptSubmit (çıkış 2 → istek işlenmez; stdout modele program mesajı),
PreToolUse (izin verildikten SONRA; çıkış 2 → araç çalışmaz — hook onay kurallarını aşamaz, yalnızca engeller),
PostToolUse (çıkış 2 → stderr sonuca eklenir), Stop (yalnızca bildirim). Komut olayı JSON olarak stdin'den alır.
Hata/zaman aşımı işi durdurmaz, `DATA_DIR/hook-kayitlari.log`. Asistan hooks.json'a dokunamaz (`security._FORBIDDEN`).

## Dosyayla tanımlanan ajanlar ve beceriler (2026-09-26)

`definitions.py`. Ajanlar: `~/.config/yeni-nesil-cafer/ajanlar/*.md` (frontmatter name, description, tools, model,
category; gövde talimat). Claude Code araç adları (Read, Bash, Grep…) programın araçlarına çevrilir; `model` yalnızca
Ollama adıysa ("qwen3.5:9b") kullanılır, yoksa program seçer. `AgentProfile.source` dolu olanlar `ajanlar.json`'a
yazılmaz; arayüzde sağ tık "dosyayı aç". Beceriler: `beceriler/<ad>/SKILL.md`; talimata yalnızca ad + açıklama
(`skills_prompt`), tarif `use_skill` aracıyla (beceri yoksa araç da gönderilmez). Canlı deneme (qwen3.5:4b):
beceriyi tanıyıp tarifi aldı, başlıklara uydu, dosya adını tariften farklı seçti. Öğrenilen beceriler (learning.py)
ayrıdır.

## Arayüz denetimi (2026-09-26)

`testler/arayuz_denetimi.py` (unittest değil): programı kullanıcının ayarlarının kopyasıyla ekransız açar; her görünen
düğmeye, üst menüye, sekmeye, sağ tık menüsüne ve açılan pencerelerin düğmelerine basar. Sorular "Hayır", pencereler
kapalı döner; tarayıcı/dosya açma, arka plan işleri ve komutlar kaydedilir, yapılmaz (nvidia-smi gibi salt okuyan
sorgular gerçek). Her sürümden önce çalıştır: 0 hata beklenir (ilk tam tur: 626 eylem). Tuzaklar: PySide6'da
`QMenu.exec` sınıftan değiştirilemez → modüllerde `QMenu` adı alt sınıfla değiştirilir; "Çıkış" gerçek `close`a
bağlıdır (atlanır); aç/kapa seçenekleri iki kez tetiklenir. İlk turda bulunanlar: bozuk kartta ölçülen 2048 bağlam
kalıcı ayar olmuştu (`ctxprobe.FLOOR_CTX` 8K); tarayıcı metni hep sayfa başından veriyordu (`browser._VISIBLE_TEXT_JS`,
kaydırma işe yaramıyordu); anahtarsız bağlantı üst etiket ve uzmanlarda görünüyordu; model kartlarında ad sütunu ezik.

## Arayüz dosyaları (2026-09-26)

`gui/window.py` (kurulum, menü, ortak yardımcılar, `closeEvent`) yalnızca çekirdek; `MainWindow` konu karışım
sınıflarından türer: `window_help` (Yardım pencereleri, model sınavı, bulut iş kuyruğu), `window_models` (model
menüleri, bağlantılar, varsayılan/otomatik model), `window_bar` (ekler, üst çubuk, sağlayıcı seçici, klasör),
`window_modes` (sansürsüz, güvenlik, güç, resim kurulumu), `window_chats` (sohbet listesi, seçim, klasörler),
`window_run` (gönderme, işçi olayları, bağlam ölçümü; `WORK_DIR_NOTE`, `UNCENSORED_NOTE`), `window_group`
(görevler). `worker.py` (`AgentWorker`), `dialogs.py` (`SettingsDialog`, `ApprovalDialog`, `InputBox`). Bölme
metotları harfi harfine taşıdı (167 üyenin kaynağı önce/sonra aynı, pencere ekransız açılıp kapandı). Yeni metot
konusunun dosyasına; Qt sinyalleri yalnızca `MainWindow` gövdesinde tanımlanır.

## Sağ panel ve canlı görüntü (2026-09-26)

Sağ panel (2.3'ten beri, kullanıcının isteğiyle): üstte yalnızca üç sekme, adımlar · kayıt · klasörler. Adımlar
iş sürerken kendiliğinden en alta kayar (`ActivityPanel.stick`; kullanıcı yukarı kaydırınca durur, en alta dönünce
sürer). Canlı önizleme (`gui/media_panel.py`) sekmelerin altında YALNIZCA görsel iş yapılırken açılır: resim
üretimi (`_media_event`), görsel bir araç çağrısı (`window_run.visual_note`: generate_image, check_3d_model ya da
kodu/dosya adı build123d, trimesh, .stl, .png, .mp4… içeren çağrı) ya da iş sürerken klasöre yeni görsel yazılması
(`_new_media`); her yeni işin başında kapanır, ✕ ile de gizlenir. Bunu sürekli görünen bir bölüme ya da sekmeye
çevirme. Modeller ve belge önizlemesi (`RightPanel.windows`, `_PartWindow`) kendi pencerelerinde açılır; resim/
video/3D önizlemesi canlı önizlemede. İş sürerken Enter işi DURDURMAZ: mesaj sıraya girer (`_submit`,
`queued_send`), iş bitince gönderilir; durdurmak yalnızca ■ durdur ya da Esc. `RightPanel.set_root` hem dosyalara
hem canlı görüntüye klasörü verir. Resim üretimi
`imagegen.generate(preview=…)` ile `sd-cli --preview proj` her adımda `Resimler/.canli-onizleme.png`'ye 64×64
yaklaşık görüntü yazar (ek model yok, yavaşlatmaz; 16 adımda 15 farklı görüntü ölçüldü); ajan `on_media` →
`AgentWorker.media` → `window_run._media_event` (üretim başlayınca sağ panel açılır). Klasör taraması 1 sn'de bir
(gizli dosya/klasör atlanır, en çok 4 düzey / 5000 girdi); dosya iki taramada aynı kalınca "yazılması bitti" sayılır.
Resim (GIF oynar), video (QtMultimedia, sessiz başlar, döngü), 3D (`assets/model3d.qml`, Qt Quick 3D
`RuntimeLoader`: GLB/GLTF, OBJ, STL, PLY; ölçüler `bounds`'tan). 3D ekransız (offscreen) kipte ÇİZİLMEZ ve ölçü
hesaplanmaz: 3D'yi gerçek ekranda doğrula. Bölümler sıra numarasıyla değil widget'la gösterilir (`_show_tab(widget)` → `RightPanel.show_part`).

## Ekran kartı (2026-09-26)

Kullanıcının isteği: program her zaman ekran kartında, birden çok kart varsa en güçlüsünde çalışmalı ve bunu kendisi
denetlemeli; hafif modda (`power.saving`) tasarruf için başka seçenek kullanabilir. `gpu.py`: `cards` (NVIDIA
nvidia-smi + uuid; Linux sysfs AMD/Intel; Windows Win32_VideoController), `strongest` (ayrı > tümleşik, NVIDIA,
VRAM), `ollama_env` (programın başlattığı Ollama'ya `CUDA_VISIBLE_DEVICES=<uuid>`; hafif modda ya da kullanıcı
kendisi verdiyse yok), `check` (/api/ps GPU payı + nvidia-smi compute-apps ile Ollama süreçlerinin kartı; işlemcide /
yanlış kart / sığmadı ayrımı). Sorun varsa model panelinde uyarı; Ollama'yı program başlattıysa `window_modes._fix_gpu`
bir kez `sysinfo.restart_ollama` ile düzeltir, sistem servisine dokunmaz (düzeltme komutu önerilir). Resim motoru:
sd-cli çıktısındaki `ggml_vulkan: 0 = <kart>` → `gpu.note_device`/`image_report`, yanlış kartta ajana uyarı.
Durum çubuğunda kartın kısa adı (`window_bar._update_context_label`).

## Hesapla kullanma (2026-09-26)

Kullanıcının isteği: bulut modelleri yalnızca API anahtarıyla değil, abonelik/hesapla da kullanılabilsin. Firmalar
hesap oturumlarının başka programların API çağrılarında kullanılmasına izin vermez; bu yüzden iki yol var:
1. Resmi program, kullanıcının kendi girişiyle (`cli_agents.py`): Claude Code (`claude -p`, Claude aboneliği), Codex
   (`codex exec --json`, ChatGPT hesabı; `codex login`), Gemini CLI (`node gemini.js -p … --output-format stream-json`,
   Google hesabı; giriş: `~/.gemini/settings.json` → `security.auth.selectedType=oauth-personal` + başsız ilk çalıştırmada
   "Y"). Sağlayıcı adları `cli:claude|cli:codex|cli:gemini` (`cli_agents.is_cli`), `agent._run_cli` tek yol; adımları
   `cli_step` kartı olarak sağ panelde. Onay beklenen tur salt okunur (Codex `--sandbox read-only`, Gemini
   `--approval-mode plan`), onaylıda iş klasöründe düzenler (Codex `workspace-write`, Gemini `auto_edit`). Codex/Node/
   Gemini program içinden kurulur (`DATA_DIR/ajan-programlari`, GitHub sürümü + SHA-256; Node nodejs.org SHASUMS256;
   sistemde Node ≥ 20 varsa o). Yalnızca kullanıcının sohbette gönderdiği istekte çalışır (ChatGPT girişi resmi
   belgeye göre etkileşimli kullanım içindir): bulut kuyruğuna ya da zamanlanmış işe bağlama.
2. Resmi olarak başka programa hesap girişi veren servisler (`accounts.py`): OpenRouter OAuth PKCE (yerel adres,
   herhangi bir port), Hugging Face cihaz kodu (`HF_CLIENT_ID`, gizli anahtarsız uygulama; süreli anahtar
   `oturum:<bağlantı>` ile `Connection.key` → `accounts.fresh_key` yeniler). Arayüz: `gui/window_accounts.py`
   (firma alt menüsünde 🔑), API penceresinde "Hesabınla giriş yap". Claude/Gemini API'sine hesapla giriş yok;
   GitHub Models 30.07.2026'da kapatıldı.

## Dikte (2026-09-26)

Mesaj kutusunda 🎤 (`window_bar._toggle_dictation`, Ctrl+Shift+Space; Esc iptal). `dictation.py`: kayıt QtMultimedia
(mikrofonun biçimi → 16 bit WAV), yazıya çevirme `dictation_server.py` sürecinde (faster-whisper, ajan
kütüphanelerinden; model bir kez yüklenir, 5 dk boşta kalınca kapanır; kayıt BAŞLARKEN ön yüklenir), temizleme küçük
Ollama modeliyle (uzunluk çok değişirse ham metin: model cevap vermeye/özetlemeye kalkmasın). Model
`large-v3-turbo`: pakette `modeller/dikte`, geliştirmede `DATA_DIR/dikte-modeli`. Ekran kartı için CUDA 12 cublas/cudnn
gerekir (Ollama'nınki CUDA 13); yoksa işlemci int8: 30 sn'ye kadar her kayıt ~5 sn (32 çekirdek). Gerçek sesle
deneme: piper `tr_TR-dfki-medium` (tek Türkçe piper sesi; "fahrettin" diye ses YOK) → "Merhaba, yarın sabah saat
9'da toplantımız var." Dikte kodu dikte (GPLv3) projesinden kopyalanmadı, sıfırdan yazıldı.

## 3D baskı ve beceriler (2026-09-26)

`check_3d_model` (tools.py; trimesh ajan Python'unda: kapalı yüzey, parça sayısı `body_count`, ölçü mm, hacim,
tabla) ve `PRINT3D_NOTE` (yalnızca 3D isteğinde; `use_skill 3d-baski`'ye yönlendirir). Canlı deneme (qwen3.5:9b):
beceri YOKKEN build123d API'sini tahmin edip 10+ hatalı denemede dosya üretemedi; `asistan/beceriler/3d-baski`
(denenmiş iskelet + tuzaklar) ile 2 denemede 35 sn'de doğru STL/STEP/3MF ve denetim. Ders: yeni alan = denenmiş
kod iskeleti içeren hazır beceri. Beceri kaynakları (`definitions.load_skills`): kullanıcı > öğrenilen
(`learn_skill` → `DATA_DIR/ogrenilen-beceriler`, yasak liste + 4000 karakter sınırı, kullanıcı/hazır ezilemez) >
hazır (`asistan/beceriler`). Genel çözüm yöntemi `agent.method_prompt` (yalnızca var olan araçları anar).
Görsel denetim `inspect_output` (inspect_output.py: 3D üç görünüş trimesh+matplotlib, PDF/SVG Qt ile, video karesi
opencv; ofis belgesinde yapı raporu) → görme modeli; gemma4:12b iki delikli bloğa "tek delik mi?" sorusunda farkı
buldu. Devretme: yöneticide adım düzeltmeye rağmen olmazsa `roster.stronger` (yerelde kartı 6/6 olan daha yüksek
puanlı model; bulut yalnızca "güçlü" politikasında; sansürsüz↔normal yok) TEMİZ bir alt ajanla dener
(`Manager._escalate`; geçmiş aktarılmaz, istek + adım + neden olmadığı anlatılır). Aday yoksa bir kez öneri.
Ekipman: `learning` "ekipman" türü tercihler gibi HER istekte talimatta; `method_prompt` kritik bilgiyi sorup kaydettirir.
`install_app` (apps.py, risk "kurar"): Linux'ta Flatpak varsa --user, yoksa AppImage (GitHub "sahip/depo" → son
sürümün bu mimariye uygun AppImage'ı; ya da https .AppImage adresi) → `~/Applications` + .desktop; ELF değilse
reddedilir; FUSE yoksa `--appimage-extract-and-run`. Windows winget --scope user, macOS brew --cask. security:
GitHub/paket yöneticisi orta, rastgele https adresi yüksek risk. Geliştirme bilgisayarında Flatpak yoktu: AppImage yolu gerçek kurulumla denendi.

## Süs modelleri (2026-09-27)

Kullanıcı süs ve figür modellerini programın kendisinin yapmasını istedi. Yerel modeller süs geometrisini kodlayamıyor
("girdaplı lamba" → düz küre, "gerçekçi ateş" → açık yüzeyli, tablaya sığmayan ağ). `decor3d.py`: test edilmiş
üreticiler (vazo/abajur: profil × kesit × burgu halka örgüsü; girdap küre; süs topu; burgulu kule; yıldız; kafes küre;
kabartma/litofan yükseklik haritası; litofan silindiri; siluet: resim → Otsu eşiği → contourpy dış hat →
`CrossSection` → kalınlık + oval taban). Hepsi manifold3d ile kapalı; tablaya sığmazsa orantılı küçültülür; kapalılık
YAZILAN STL'de denetlenir; 3MF kendi yazıcımızla (trimesh'inki networkx ister). Ajan Python'unda ayrı süreçte çalışır
(`tools.make_decor_model`, risk "yazar", grup "ozel"): araç yalnızca son kullanıcı mesajlarında 3D/süs geçince eklenir
(`Agent._offer_decor`; bulut kopyasında ve dosya yazamayan ajanda yok). `PRINT3D_NOTE` süsleri araca, işlevsel parçaları
`3d-baski` becerisine yönlendirir. Tuzaklar: eklenen silindir/halka gövdenin açı ızgarasıyla aynı açılara denk gelirse
birleşim aynı konumda iki nokta bırakıyor, STL açık çıkıyordu → `_cylinder` 3.7° döndürür; `simplify(0.01)` hacimsiz
parça bırakıyordu → 0.001. Canlı deneme (qwen2.5:14b): "spiral dilimli gece lambası" → kod yazmadan `girdap_lamba`, kapalı
STL, görme modeli onayı (197 sn). Kedi figüründe model doğru yolu seçti (generate_image → siluet) ama resim üretimine
bellek yetmedi (açık programın işi ekran kartını tutuyordu); `imagegen.generate` artık bir kez boşaltıp yeniden dener.
Sonraki aşama (kullanıcıyla konuşuldu, yapılmadı): resimden gerçek 3D figür (TripoSR, ~1,7 GB, düğmeyle kurulur).

## Resimden 3D figür (2026-09-27)

Kullanıcı Aşama 2'yi istedi: resimden hacimli figür. `figure3d.py` (program tarafı): kurulum YALNIZCA düğmeyle
(Yardım → 3D figür motoru…, `window_modes._figure_setup`); TripoSR kodu GitHub'dan sabit commit'le (yalnızca `tsr/` +
LICENSE → `DATA_DIR/figur-motoru/kod`), model Hugging Face'ten sabit sürümle (model.ckpt 1,68 GB, config.yaml,
DINO'nun yalnızca config.json'u) — hepsi SHA-256 doğrulamalı, `imagegen._download` ile kaldığı yerden; eksik
kütüphaneler (omegaconf, einops, transformers, huggingface_hub, PyMCubes; torch yoksa NVIDIA'da cu130, yoksa CPU)
ajan kütüphane klasörüne. `figure3d_worker.py` (ajan Python'unda): arka plan kendi yöntemimizle (kenardan dolan
zemin rengi / saydamlık; rembg yok), girdi TripoSR'ın beklediği gibi (%85, gri zemin, 512), `torchmcubes`/`rembg`
sahte modülle geçilir, DINO yapı dosyası yerelden (`hf_hub_download` değiştirilir), yoğunluk ızgarası (GPU 256³, CPU
160³) → PyMCubes → Taubin yumuşatma (12 tur; ızgara basamaklarını siler) → en büyük parça, yükseklik, alt %3 kesilip
düz taban, 3 mm ayak (dış hattın dışbükey örtüsü) → `decor3d.save`. transformers 5 ViT katmanlarını yeniden adlandırdı
(`encoder.layer.N.attention.attention.query` → `layers.N.attention.q_proj`, `intermediate.dense` → `mlp.fc1`…):
yükleyici eski adları çevirir (`_VIT_RENAMES`); transformers'ı 5'in altına sabitlemek huggingface_hub'ı da geriletirdi.
Araç `make_3d_figure` (Agent._tool_; Ollama'yı ekran kartından boşaltır, `gpu.fault()`ta CPU) yalnızca motor kuruluysa
ve 3D/süs sohbetinde. Ölçüm (CPU, i9-13900HX): TripoSR örnekleri at/tilki/polis/robot ~23 sn, hepsi kapalı ve tek parça.
Kurulum bu bilgisayarda 358 sn (16 MB/sn). Ekran kartı o sırada "Reset required" durumundaydı (15:51, Xid 62/154):
GPU yolu yeniden başlatmadan sonra denenmeli. Sohbet denemesi (qwen3.5:4b, işlemcide, tilki resmi ek olarak):
model önce look_at_image ile resmi denetledi, sonra make_3d_figure'u doğru değerlerle çağırdı (120 mm, tabla,
ayak) → kapalı tek parça; ardından inspect_output işlemcide zaman aşımına uğradı (arızanın yavaşlığı). Filament
tahmini dolu gövdelerde kabuk 1.2 mm + %15 dolgu (`decor3d.save(infill=)`; tam hacim 3 kat fazla gösteriyordu).

## Yeniden başlatma sonrası ekran kartında denemeler (2026-09-27, 2.5.1)

Kedi figürü uçtan uca (qwen2.5:14b, 378 sn): generate_image → make_3d_figure. SDXL beyaz kediyi açık gri, renk geçişli
fonda ve aydınlık yer düzleminde çizdi; kenar rengine dayalı arka plan silme zemini de nesne sandı → 93×255×80 mm
kama. `figure3d_worker.cut_out` artık kenardan başlayıp keskin sınıra kadar yayılan yumuşak bölgeyi zemin sayar (Sobel
eşiği = en keskin %25), kenardan gövdeye uzanan ince yapıları (ufuk/masa çizgisi, kalınlık < %1.5) ayırır; nesne
karşılıklı iki kenara birden değerse ya da resmin %80'ini kaplarsa hata verir (gerçek nesneler kenara değmez, büst
yalnızca alta). Görme denetimi (gemma4:12b) kama bloğa "evet, oturan kedi" dedi: görsel onaya güvenme, kodla denetle.
Kart doluyken (Ollama 9.8 GB) TripoSR `OutOfMemoryError` → kendiliğinden CPU (28 sn); boşken GPU 13.6 sn.
Resim motoru: Vulkan 0 = Intel, 1 = RTX; ayarsız motor yükü ikisine dağıtıyordu (örnekleme 4.2 sn, uyarı yanıltıcı).
`imagegen` motorun yazdığı listeyi `resim/vulkan-kartlari.json`'a saklar, sonraki çalıştırmada `GGML_VK_VISIBLE_DEVICES`
ile en güçlü karta sabitler (3.2 sn; kullanıcı kendisi verdiyse dokunmaz). Küçük model hataları: üretilen resmin adını
kısaltma ("Resimler/resim-0.png") → `tools.missing_image` en yeni resimleri söyler; aracı run_python içinde işlev gibi
çağırma → NameError'a "bu bir araç" notu; qwen2.5:14b planını bir kez Çince yazdı. Testler: kütüphane yolu her zaman
gerçek kurulumdan (XDG_DATA_HOME başka test dosyasınca değiştirilmiş olabilir; 10 test sessizce atlanıyordu).

## Sonuçlar ve masaüstü düzeni (2026-09-27, 2.6)

Kullanıcının isteği: masaüstünde dağınık klasör olmasın, her şey `<masaüstü>/YENİ NESİL CAFER/` altında; işlerin
sonuçları (görsel, 3D, belge, kod) orada `Sonuçlar/`da toplansın. `results.py`: `desktop()` (xdg-user-dir; Windows
Desktop), `project_dir(alt)`, `collect(iş klasörü, çalışma klasörü, since)` → `Sonuçlar/<kategori>/<iş>/` içine KOPYA
(asıl dosya iş klasöründe; ajan orada devam eder). `Agent._collect_results` her turun sonunda (`run` içinde `finally`;
hata/durdurmada da), bulut kopyasında yok, `Settings.extra["sonuclari_topla"]` (varsayılan açık; Ayarlar'da onay
kutusu). Kopyalanmayanlar: gizli dosya/klasör (.denetim, canlı önizleme), `-girdi.png`, `ekler/`, `tarayici-goruntu/`,
JSON (resim yan dosyası), ASISTAN.md, turdan eski dosyalar; değişmeyen yeniden kopyalanmaz. Menü: Sohbet → Sonuçlar
klasörü (`window_help._open_results`). Sorun raporları `YENİ NESİL CAFER/Sorun Raporları`, geliştiricinin paketleri
`YENİ NESİL CAFER/Kurulum Paketleri/YENI-NESIL-CAFER.vX` (`paketle.paket_klasoru`, yayinla.sh da oradan okur).
Örnek çıktılar (13 süs, 7 figür, önizlemeleriyle): `Sonuçlar/Örnekler`. İlk kurulumda sihirbaz çalışma klasörünü
sorar (varsayılan `~/YeniNesilCafer`; bu bilgisayarda eski kurulumdan `~/YerelAsistan`).

## Sorun raporu (2026-09-26)

Kullanıcının kararı: program kendi kodunu DEĞİŞTİRMEZ; sorunu algılar ve geliştiriciye (Claude Code) verilecek raporu
hazırlar. `problem_report.py`: `build` (ne oldu, yerel modelin ön teşhisi ~20 sn, sistem/ayarlar anahtarsız, model
kartı, sohbetin sonu araç çağrıları ve hatalarıyla, `program-gunlugu.log` sonu, son sorun kayıtları), `redact`
(bilinen anahtar biçimleri + keystore'daki gerçek değerler), `write` (masaüstü; kopyası `DATA_DIR/sorun-raporlari`),
`claude_prompt` (panoya). Öneri kartı (`chat.ReportOffer`, "🐞 Sorunu raporla") hata / tamamlanamadı / boş cevap /
yakalanmamış hata (`install_crash_log`, main.py; `MainWindow.problem` sinyali) sonrası; Yardım → Sorun bildir…
Bir sorun raporu gelirse: rapordaki kanıtlardan başla, düzelt, test et, aktar, paketleri güncelle.

## GitHub ve güncellemeler (2026-09-26)

Kullanıcının kararı: herkese açık GitHub deposu, program içi güncelleme. `asistan.GITHUB_REPO` (sahip/ad; boşsa
kapalı). `updates.py`: son sürüm (GitHub API, giriş gerekmez), yalnızca kod paketi `yeni-nesil-cafer-guncelleme-<s>.zip`
(asistan/ + main.py, birkaç MB), SHA-256 (sürümdeki `digest` ya da `.sha256`), yol kaçışı denetimi, yedek
(`DATA_DIR/guncelleme-yedek/<eski>`), `guncelleme-durum.json`. `main.rollback_if_needed` asistan paketi içe
aktarılmadan önce çalışır: yeni sürüm 15 sn açık kalamadan yeniden başlatılırsa eski sürüme döner. Geliştirme
klasöründe (.git) güncelleyici kapalı. Yayın: `paketleme/yayinla.sh` (testler → etiket → paketler 1900 MB parçalar
+ birlestir.bat/sh → kod paketi → `gh release`). Büyük paket yalnızca ilk kurulum için; Python/Ollama/kütüphane
değişmedikçe sürümler kod paketiyle yeter. Yeni ajan kütüphanesi eklenirse eski kurulumlar onu ilk kullanımda
pip ile kurar.

## Araç ekleme kuralı

Yeni yerleşik araç: tanımı `tools.py`'de `REGISTRY.add(spec, risk, (etiket, bitince))` ile yaz, çalıştırıcıyı
`Toolbox._tool_<ad>` olarak ekle; ajanın durumuna (geri çağrılar, hafıza, alt ajan) ihtiyaç duyuyorsa `Agent._tool_<ad>`,
araca özgü ek onay kapısı gerekiyorsa `Agent._gate_<ad>`. Onay kuralları yalnızca `permissions.py`'de. Onay listesi,
etiket ya da doğrulama için başka bir yere dokunma. Testler:
`~/.local/share/yeni-nesil-cafer-app/python/bin/python3 -m unittest discover -s testler -v` (kurulu kopya yoksa `.venv/bin/python`)

## Bilinen tuzaklar

- Resim üretimi (sd-cli) ile Ollama modeli aynı anda ekran kartına sığmaya çalışırsa NVIDIA sürücüsü bozulabilir
  (2026-09-25: önce "can't alloc VA space", sonra "Reset required"; CUDA aygıt görmez, Ollama sessizce CPU'ya
  düşer ve her şey dakikalarca "takılır"). Düzelmesi için yeniden başlatma gerekir. `ollama ps` → "100% CPU".
  Aynı durum resim üretimi yokken de görüldü (çekirdek kaydında `Xid 62` / `Xid 154`, `NV_ERR_RESET_REQUIRED`;
  sürücü ya da güç yönetimi kaynaklı olabilir). Belirti: `nvidia-smi`'de `ERR!`.
  2026-09-26 22:15 yine oldu (Xid 62, `llama-server` sırasında; "GPU requires reset"). `gpu.fault()` bunu
  `nvidia-smi --query-gpu=temperature.gpu` çıktısından algılar (30 sn önbellek); o zaman `power.saving` her ayarda
  True (küçük model, 8K bağlam; `roster.default` hafif modda >5B yerel varsayılanı atlar) ve `gpu.check` "bilgisayarı
  yeniden başlat" der (Ollama'yı yeniden başlatmak düzeltmez). Testler `gpu.fault`'u taklit etmeli.
- Testler kullanıcının gerçek veri klasörüne yazmamalı: her test dosyası `asistan`'ı içe aktarmadan ÖNCE
  XDG_CONFIG_HOME/XDG_DATA_HOME'u geçici klasöre almalı (`config` yolları içe aktarılırken sabitlenir; yalıtılmamış
  bir test önce yüklenirse sonrakiler de gerçek klasörü kullanır — 2026-09-26'da `gelisim.jsonl`'e test satırı düştü).
- Bağlantılar: `Connection.needs_key`/`usable`; anahtarsız ya da 401 alan (`connections.key_error`, oturumluk
  `_REJECTED`) bağlantı yönlendiricide, menülerde ve varsayılanda (`roster.default`) atlanır; API penceresi anahtarsız
  kaydetmez. (2026-09-26: anahtarsız OpenAI bağlantısı varsayılan bulut modeliydi, her mesaj 401 veriyordu.)

- Gemma 4 (normal ve sansürsüz) sistem talimatı olmadan araç çağırmaz, komutu metin olarak yazar; ara sıra
  bozuk bir araç çağrısında dakikalarca tamponlayıp hiçbir şey akıtmaz. `agent.py`: `STALL_SECONDS`,
  `NUM_PREDICT`, "yazdı ama yapmadı" uyarısı (`_CLAIMS_WORK`).
- Sistem talimatı + araç tanımları ~5.600 token (2026-09-26 ölçümü): 4K bağlamda geçmişe hiç yer kalmaz, 8K'da
  ~1.100 token kalır. Bu yüzden Ollama'da bağlam `LEAN_CTX` altındaysa `agent.lean`: uygulama açma/kurma kuralları
  ve uzun program tanıtımı yalnızca istek gerektirince, `call_api` API listesi yalnızca adlar (4.1–4.7K token).
  Büyük bağlamda talimat birebir aynı. `call_api` 4xx'te API'nin doğru kullanımını hataya ekler (4B model yolu
  unutuyor/uyduruyor).
- Ollama'nın `capabilities` bilgisi ("tools") modelin gerçekten araç çağırdığını göstermez; ölçmek gerekir.
- Resim üretimi (sd-cli) sırasında Ollama modelleri ekran kartından boşaltılır (12 GB'a ikisi sığmaz).
- Yönetici şimdilik sohbet modeliyle planlar ve denetler. 4B gibi küçük modeller denetçi olarak gevşek kalabilir
  (bir denemede yanlış sayı bir kez kabul edildi); bu yüzden denetçiye dosya içerikleri gösteriliyor.
  Kalıcı çözüm: yöneticiye güçlü model (bulut önceliğinde bulut).
- Model kartları (2026-09-25): sansürsüz Gemma 4 araç 1/3, gemma3 ve dolphin3 0/3; gemma4:12b, qwen3.5:4b,
  sansürsüz qwen3.5 4b 3/3. İşçi olarak 4B model zayıf: yaz-ve-kaydet işinde metni kendisi yazıp konudan
  sapabiliyor; `qwen3.5:9b` kurulursa işçi olarak daha iyi olur.
