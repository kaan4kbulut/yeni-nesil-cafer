# Mimari ayrıntılar — durum tablosu, yol haritası ve tuzakların tam metni

CLAUDE.md'nin 2026-09-27 sürümünden birebir taşındı. CLAUDE.md'de bunların kısa hâli var; ayrıntı
(hangi modülde ne var, neden öyle yapıldı, tuzakların tarihçesi) burada.

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

## Ad değişikliği (2.2)

2.2'ye kadarki adı Yerel Asistan, iç adı `yerel-asistan` (`config.OLD_ID`): bu adla açılmış eski klasörler ilk
açılışta `config.migrate_dir` ile yeni ada taşınır.
