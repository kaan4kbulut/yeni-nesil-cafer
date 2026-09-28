# YENİ NESİL CAFER — mimari ve kurallar

Python 3.12 + PySide6 masaüstü asistanı; aynı paket sunucuda web + telefon (PWA) olarak çalışır. Yerel modeller Ollama
ile, bulut modelleri Claude / OpenAI uyumlu API'lerle ve kullanıcının kendi hesabıyla giren resmi CLI programlarıyla
(`cli:claude|cli:codex|cli:gemini`). Kullanıcıyla her zaman Türkçe konuşulur; kod yorumları Türkçedir. Python paketi
`asistan`, iç ad `yeni-nesil-cafer` (`config.APP_ID`); 2.2'ye kadarki adı Yerel Asistan (eski klasörler ilk ayar
yüklemesinde `ayar.klasorleri_tasi` ile taşınır, anahtarlar `keystore.OLD_SERVICE`'ten kopyalanır).

Kurulu kopya `~/.local/share/yeni-nesil-cafer-app/` (kendi Python'u `python/bin/python3`). Kaynaktaki değişiklik
kullanıcıya ancak `paketleme/aktar.sh` ile ulaşır. Kurulum kendi kendine yeter; kullanıcıya hiçbir zaman komut
yazdırılmaz, elle bir şey indirtilmez. Her indirme sabit sürüm + SHA-256.

**Bu dosya kısa kalır (≤ 150 satır).** Yalnızca kalıcı kural, karar ve harita. Tarihli deneyler `NOTLAR/<tarih>-K<n>.md`;
durum ve yol haritası ayrıntısı `NOTLAR/mimari-ayrintilar.md`; hedef mimari `docs/MIMARI.md`, şemalar `docs/SEMALAR.md`,
aşama planı `YAPILACAKLAR.md` (K0–K11), geçici kararlar `NOTLAR/SORULAR.md`. **Oturuma `YAPILACAKLAR.md`'den başla.**

## Hedef: şirket gibi çalışan tek bir sistem

Kullanıcı model seçmek istemiyor. İsteği anlayan bir yönetici işi parçalara ayırır, her parçayı uygun modele ve
yeteneğe verir, sonucu doğrular. Model "yapıyorum" deyip araç çağırmıyorsa bu sistemin hatasıdır.

1. **Görev motoru** (`cekirdek/gorev/`): anla → planla (şema kısıtlı, yalnızca kayıtlı yetenekler) → uygula → doğrula;
   `DATA_DIR/gorevler.db` ile devam; başarısız adım hata analizine (`cekirdek/analiz/hata.py`) gider: eksik paket
   kur (onaylı), eksik yetenek üret (onaylı, sandbox testli), ağda 3 deneme, mantıkta en çok 2 yeniden planlama.
   Masaüstü sohbeti Manager (`manager.py`) ile; motor bayrakla (`extra["gorev_motoru"]`, SORULAR K4/BÖLÜM 7).
2. **Model yönlendirici** (`cekirdek/yonlendirici.py`): rol hızlı/yönetici/kod, kademe, gizlilik, sağlık önbelleği,
   yedekleme zinciri (`Zincir`), bulut tavanı (gerçek `usage`), sınav geri beslemesi. Kartlar (`cards.py`) programın kendi
   sınavıdır; üreticinin beyanı kanıt değildir. Model adları yalnızca `asistan/ayar/modeller.json` (+ kullanıcı katmanı
   `DATA_DIR/modeller.json`).
3. **Yetenek kayıt defteri** (`cekirdek/yetenek/`): `asistan/yetenekler/<ad>/manifest.json + calistir.py + test`;
   üretilenler `DATA_DIR/yetenekler/`. Yerleşikler programın aracını `baglam.arac` ile çağırır (tek araç yolu);
   sandbox yetenekleri izin hattına `y_<ad>` adıyla girer (ayrı venv, beyaz listeli ortam, ağsız, zaman aşımı).
4. **Araç kaydı** (`registry.py`, `tools.py`): ad, açıklama, JSON şeması, çalıştırıcı, risk sınıfı. MCP uyumlu.
5. **Hafıza ve beceriler** (`memory_db.py`, `learning.py`), **araç fabrikası** (`factory.py`).

**Tek gövde, iki beyin.** Araç kaydı, beceriler, hafıza ve güvenlik kuralları ortak; yerel ile sunucu arasında değişen
yalnızca model ve erişilebilen araçlar. Sunucudaki kopya bilgisayara erişemez; yerel dosya gerektiren işleri kuyruğa
bırakır, bilgisayarda kendiliğinden ASLA çalışmaz (☁ → "yap"). Görevler sunucuyla eşitlenir (son yazan kazanır).

## Güvenlik — pazarlık dışı kurallar

- Onay kuralları yalnızca `permissions.py`'de (tek izin hattı: yasak → ✓ bekletme → güvenlik ajanı → kullanıcı).
  `cekirdek/guvenlik.py` (politika `asistan/ayar/guvenlik.toml`: kurulum/ağ/silme/sandbox süresi/kaynak allowlist)
  ikinci bir onay yolu açmaz; `permissions.decide` uygular. İzin bağlamı olmayan yollarda (komut satırı, Görevler
  penceresi, web) yazan/çalıştıran her adım onay bekler.
- Asistanın yazdığı yeni kod (üretilen yetenek, fabrika aracı) önce sandbox'ta test edilir. Paket kurma, dosya silme,
  internete gönderme kullanıcı onayıyla; "otomatik onay" listesi ve güvenlik ajanı bunları geçebilir, bulut tavanını
  geçemez. Sansürsüz modda güvenlik ajanı çalışamaz; riskli adımlar tek tek sorulur.
- Alt süreçlere yalnızca beyaz listeli ortam geçer (`araclar/komut.guvenli_ortam`); `CAFER_*` ve `ANTHROPIC_API_KEY`
  hiçbir zaman. `ayarlar.json`, `anahtarlar.json` ve ayar klasörü okunamaz. `web_fetch` yerel/özel ağı okumaz.
- Çekirdek (yönetici döngüsü, izin hattı, `hooks.json`) asistan tarafından değiştirilemez; program kendi kodunu
  DEĞİŞTİRMEZ, sorun raporu hazırlar (`problem_report.py`). Asistanın eklediği her şey git ile sürümlenir.
- Tarayıcıda satın alma/ödeme, mesaj/paylaşım, hesap/silme, giriş/indirme her zaman sorulur (`browser.gate`).
  Reşit olmayanları çağrıştıran içerik her modda engellenir (`imagegen.check_prompt`). Deepfake yalnızca tespit.
- CLI ajanları yalnızca kullanıcının sohbette gönderdiği istekte; görev motorunda yalnızca `kod` rolünde, iş
  klasöründe, salt okunur. Claude/Gemini API'sine hesapla giriş yok. Ağır motorların kurulumu yalnızca düğmeyle.

## Kalıcı kararlar (kullanıcının istekleri — değiştirme)

- **Model çıktısına güvenme, kodla denetle.** Doğrulama önce programın kanıtı; denetleyici model yoksa adım ŞARTLI
  (geçmiş sayılmaz). Görme modelinin "evet" demesi kanıt değildir.
- Adımda yalnızca isteğin dosyaları; planlayıcı yardımcı dosya uydurmaz; sonuç yoksa dürüstçe "yapılamadı".
- Her sohbet kendi iş klasöründe (`<çalışma klasörü>/<kategori>/<başlık>-<id>`); sonuçlar `<masaüstü>/YENİ NESİL
  CAFER/Sonuçlar/`e KOPYA (`results.py`). Eski mesajlar silinmez, yerel modelle özetlenir. `ASISTAN.md` talimata
  genelden özele (en çok 3 düzey, 4000 karakter).
- Program en güçlü ekran kartında çalışır (`gpu.py`); resim üretimi ile Ollama aynı anda karta sığmaz.
- Kademe (`dusuk/orta/yuksek/sunucu`) açılışta ölçülür, hız ölçümüyle kayar, kilitlenebilir; `dusuk`'te ağır
  özellikler kapalı ve arayüz sade (Görünüm → Gelişmiş arayüz açar). Model seçimi Yardım → Gelişmiş altında.
- Arayüz: sağ panelde üç sekme (adımlar · kayıt · klasörler); yeni pencereler `Yardım` altında (sekme eklenmez).
  Yeni metot konusunun dosyasına (`gui/window_*.py`); Qt sinyalleri yalnızca `MainWindow` gövdesinde.
- Sürümler kod paketiyle (`updates.py`, 15 sn açık kalamazsa geri alma; düzgün kapanış çökme sayılmaz). Yayın
  `paketleme/yayinla.sh`: testler geçmeden, atlanan test varken, sınav eşiğin altındayken yayın yok.

## Dosya haritası (`asistan/`)

- **Çekirdek (`cekirdek/`, Qt/fastapi yasak; eski gövdeye içe aktarmalar `test_cekirdek_ayrimi` listesiyle sınırlı):**
  `ayar.py` (tek ayar kaynağı: `ayarlar.json` + `ayar.toml` + `CAFER_*`), `modeller.py`, `profil.py` (donanım → kademe),
  `yonlendirici.py`, `yapisal.py` (şema kısıtlı üretim), `semalar/`, `saglayici/` (Ollama/Claude/OpenAI uyumlu/CLI),
  `araclar/` (dosya, komut, web, ürün listesi), `istek.py` (ajanı kur + çalıştır), `gorev/` (anlayici, planlayici,
  yurutucu, dogrulayici, durum, model, ajan, sohbet, komut), `yetenek/` (kayit, calistirici, yukleyici, uretici, komut),
  `analiz/` (hata, olcum), `guvenlik.py`, `bildirim.py`, `uzak.py`.
- **Yüzler (`arayuz/`):** `masaustu` (= `gui/`), `web/` (FastAPI + PWA), `komut/` (`python -m asistan profil|gorev|
  yetenek|sinav|sunucu`).
- **Eski gövde:** `agent.py` (araç döngüsü, `_execute_tool`), `manager.py` (sohbet yöneticisi), `tools.py` + `registry.py`
  (araç kaydı), `permissions.py` + `security.py`, `roster.py`/`cards.py`/`categories.py`/`specialists.py`/`cli_agents.py`,
  `memory_db.py`/`learning.py`, `factory.py`/`mcp.py`/`browser.py`/`apps.py`/`libraries.py`, `cloud_server.py`/`cloud_sync.py`,
  `updates.py`/`bootstrap.py`/`problem_report.py`/`gpu.py`/`power.py`/`results.py`, görsel/3D/ses modülleri.
- **Arayüz (`gui/`):** `window.py` + `window_*.py`, `worker.py`, `panels.py`, `sidebar.py`, `dialogs.py`, `setup_wizard.py`,
  `tour.py`, pencereler `*_dialog.py`, `theme.py`.
- **Veri:** `asistan/ayar/` (modeller.json, guvenlik.toml), `asistan/yetenekler/`, `asistan/beceriler/`.
- **Dağıtım:** `paketleme/` (aktar.sh, paketle.py, yayinla.sh, bulut_paketi.sh), `dagitim/` (Light/Full, CI), `sunucu/`.
- **Testler:** `testler/` (unittest; `pytest.ini` yalnızca burayı toplar), `testler/arayuz_denetimi.py` (0 hata),
  `testler/sinav/` (gerçek görevli sınav: `calistir.py --hizli|--kademe|--motor`, RAPOR.md, `esik.json`). Komut:
  `~/.local/share/yeni-nesil-cafer-app/python/bin/python3 -m unittest discover -s testler -v` (ya da `.venv` pytest).

## Araç ve yetenek ekleme kuralı

Yeni yerleşik araç: `tools.py`'de `REGISTRY.add(spec, risk, (etiket, bitince))`, çalıştırıcı `Toolbox._tool_<ad>`;
ajanın durumu gerekiyorsa `Agent._tool_<ad>`, özel kapı `Agent._gate_<ad>`. Onay kuralı yalnızca `permissions.py`.
Fabrika araçları `f_` önekli, `calistirir`. Planlayıcı yalnızca manifestli yetenekleri görür: yeni iş =
`asistan/yetenekler/<ad>/` (`/yetenek-ekle`); yerleşik yetenek aracı `baglam.arac` ile çağırır, sandbox yeteneği
`y_<ad>` adıyla izin hattına girer. Manifest `izinler` → risk sınıfı eşlemesi `docs/SEMALAR.md` §1.

## Hâlâ geçerli tuzaklar (tam metin: `NOTLAR/mimari-ayrintilar.md`)

- NVIDIA sürücüsü bellek baskısında bozulabilir (Xid, "Reset required"); `gpu.fault()` algılar, yeniden başlatma.
- Testler gerçek veri klasörüne yazmamalı: her test dosyası `asistan`'ı içe aktarmadan ÖNCE XDG_CONFIG_HOME/
  XDG_DATA_HOME'u geçici klasöre alır; sessizce atlanan test kabul edilmez.
- Anahtarsız ya da 401 alan bağlantı yönlendiricide ve menülerde atlanır (`Connection.usable`).
- Gemma 4 sistem talimatı olmadan araç çağırmaz; kartlar: gemma3/dolphin3 araç 0/3. Araç sınavını tam geçemeyen
  model işçi yoksa araç seçici kipinde (`agent._run_selector`). Küçük modeller dosya adını kısaltır, planı Çince yazar.
- Sistem talimatı + araç tanımları ~5.600 token; 8K bağlamda `agent.lean`. `anthropic` SDK'sı tembel yüklenir.
- Aynı süreçte `testler/` ve `asistan/yetenekler/*/test_*.py` aynı modül adıyla çakışır (`pytest.ini testpaths`).

## Çalışma düzeni

- **Bir oturum = bir aşama.** `/asama K<n>` ile başla; başka sorun görürsen `NOTLAR/`'a yaz, geç. Görev listesi zorunlu
  (`TaskCreate`/`TaskUpdate`; yoksa `.cafer/gorev.py`). Büyük refaktörden önce `mimar`, bitince `denetci`.
- Hata görünce `/hata-analiz` (sınıflandırıcıya desen ekler). Aşama sonunda `/kontrol`. `/profil`, `/sunucu`, `/yetenek-ekle`.
- Commit atma; commit mesajı öner ("commitle" denince at). Tahmin etme: dosyayı aç, komutu çalıştır, sonucu göster.
- Kullanıcıya tek soru sor, kalan kararları makul varsayımla ver ve `NOTLAR/SORULAR.md`'ye yaz.

## Açık işler

1. Adımları kategorisine göre uzman modele dağıtmak (K3); bulut maliyetinin ₺ karşılığı.
2. Görev motorunu sohbette varsayılan yapmak (sınav karşılaştırması: `--motor` / `--motorsuz`, NOTLAR BÖLÜM 7).
3. Sunucuyu gerçek makinede kurmak (K8/K9 KONTROL_LISTEN); Full dağıtım paketi için küçük model (K11).
4. 3D baskı: dilimleme ve yazıcıya gönderme (Sonraya).
