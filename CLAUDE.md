# YENİ NESİL CAFER — kurallar ve harita

Python 3.12 + PySide6 masaüstü asistanı; aynı paket sunucuda web + telefon (PWA). Yerel modeller Ollama ile, bulut
modelleri Claude / OpenAI uyumlu API'lerle ve kullanıcının hesabıyla giren resmi CLI'larla (`cli:claude|codex|gemini`).
Kullanıcıyla her zaman Türkçe konuşulur; kod yorumları Türkçedir. Paket `asistan`, iç ad `yeni-nesil-cafer`
(`config.APP_ID`); 2.2'ye kadarki adı Yerel Asistan (eski klasörler `ayar.klasorleri_tasi` ile taşınır).

**Bu dosya ≤ 100 satır: yalnızca kalıcı kural, karar ve harita.** Aşamaya özel talimatlar beceri dosyalarında, gerekince
yüklenir: `.claude/skills/k-serisi` (aşama akışı, otomatik sürücü, not düzeni), `.claude/skills/kurulum` (kurulu kopya,
paketleme, dağıtım, sürüm), `.claude/skills/denetci` (denetim adımları, bilinen tuzaklar). Hedef mimari `docs/MIMARI.md`,
şemalar `docs/SEMALAR.md`, aşama planı `YAPILACAKLAR.md`, geçici kararlar `NOTLAR/SORULAR.md`, tarihli deneyler
`NOTLAR/<tarih>-K<n>.md`. Bunları ihtiyaç olunca oku; oturum başında hepsini yükleme.

## Hedef: şirket gibi çalışan tek bir sistem

Kullanıcı model seçmek istemiyor. İsteği anlayan bir yönetici işi parçalara ayırır, her parçayı uygun modele ve
yeteneğe verir, sonucu doğrular. Model "yapıyorum" deyip araç çağırmıyorsa bu sistemin hatasıdır.

1. **Görev motoru** (`cekirdek/gorev/`): anla → planla (şema kısıtlı, yalnızca kayıtlı yetenekler) → uygula → doğrula;
   `DATA_DIR/gorevler.db` ile devam; başarısız adım hata analizine (`cekirdek/analiz/hata.py`) gider. Masaüstü sohbeti
   Manager (`manager.py`) ile; motor bayrakla (`extra["gorev_motoru"]`).
2. **Model yönlendirici** (`cekirdek/yonlendirici.py`): rol hızlı/yönetici/kod, kademe, gizlilik, sağlık önbelleği,
   yedekleme zinciri, bulut tavanı, sınav geri beslemesi. Kartlar (`cards.py`) programın kendi sınavıdır. Model adları
   yalnızca `asistan/ayar/modeller.json` (+ kullanıcı katmanı `DATA_DIR/modeller.json`).
3. **Yetenek kayıt defteri** (`cekirdek/yetenek/`): `asistan/yetenekler/<ad>/manifest.json + calistir.py + test`;
   üretilenler `DATA_DIR/yetenekler/`. Sandbox yetenekleri izin hattına `y_<ad>` adıyla girer.
4. **Araç kaydı** (`registry.py`, `tools.py`), **hafıza/beceriler** (`memory_db.py`, `learning.py`), **fabrika** (`factory.py`).

**Tek gövde, iki beyin.** Araç kaydı, beceriler, hafıza ve güvenlik kuralları ortak; yerel ile sunucu arasında değişen
yalnızca model ve araçlar. Sunucudaki kopya bilgisayara erişemez; yerel iş kuyruğa düşer, kendiliğinden ASLA çalışmaz.

## Güvenlik — pazarlık dışı kurallar

- Onay kuralları yalnızca `permissions.py`'de (tek hat: yasak → ✓ bekletme → güvenlik ajanı → kullanıcı).
  `cekirdek/guvenlik.py` (politika `asistan/ayar/guvenlik.toml`) ikinci bir onay yolu açmaz. İzin bağlamı olmayan
  yollarda (komut satırı, Görevler penceresi, web) yazan/çalıştıran her adım onay bekler.
- Asistanın yazdığı yeni kod önce sandbox'ta test edilir. Paket kurma, dosya silme, internete gönderme kullanıcı onayıyla;
  otomatik onay listesi ve güvenlik ajanı bunları geçebilir, bulut tavanını geçemez. Sansürsüz modda güvenlik ajanı
  çalışamaz; riskli adımlar tek tek sorulur.
- Alt süreçlere yalnızca beyaz listeli ortam geçer (`araclar/komut.guvenli_ortam`); `CAFER_*` ve `ANTHROPIC_API_KEY`
  hiçbir zaman. `ayarlar.json`, `anahtarlar.json` ve ayar klasörü okunamaz. `web_fetch` yerel/özel ağı okumaz.
- Program kendi kodunu DEĞİŞTİRMEZ, sorun raporu hazırlar (`problem_report.py`). Asistanın eklediği her şey git'te.
- Tarayıcıda satın alma/ödeme, paylaşım, hesap/silme, giriş/indirme her zaman sorulur (`browser.gate`). Reşit olmayanları
  çağrıştıran içerik her modda engellenir (`imagegen.check_prompt`). Deepfake yalnızca tespit.
- CLI ajanları yalnızca kullanıcının sohbette gönderdiği istekte; görev motorunda yalnızca `kod` rolünde, iş
  klasöründe, salt okunur. Claude/Gemini API'sine hesapla giriş yok. Ağır motorların kurulumu yalnızca düğmeyle.

## Kalıcı kararlar (kullanıcının istekleri — değiştirme)

- **Model çıktısına güvenme, kodla denetle.** Denetleyici model yoksa adım ŞARTLI; görme modelinin "evet"i kanıt değil.
- Adımda yalnızca isteğin dosyaları; planlayıcı yardımcı dosya uydurmaz; sonuç yoksa dürüstçe "yapılamadı".
- Her sohbet kendi iş klasöründe (`<çalışma klasörü>/<kategori>/<başlık>-<id>`); sonuçlar `<masaüstü>/YENİ NESİL
  CAFER/Sonuçlar/`e KOPYA. Eski mesajlar silinmez, yerel modelle özetlenir. `ASISTAN.md` en çok 3 düzey, 4000 karakter.
- Program en güçlü ekran kartında çalışır (`gpu.py`); resim üretimi ile Ollama aynı anda karta sığmaz.
- Kademe (`dusuk/orta/yuksek/sunucu`) açılışta ölçülür, kilitlenebilir; `dusuk`'te ağır özellikler kapalı, arayüz sade.
- Arayüz: sağ panelde üç sekme; yeni pencereler `Yardım` altında (sekme eklenmez). Yeni metot konusunun dosyasına
  (`gui/window_*.py`); Qt sinyalleri yalnızca `MainWindow` gövdesinde. Etiketler `#araç #görme` biçiminde.
- Kurulum kendi kendine yeter: kullanıcıya komut yazdırılmaz, elle indirtilmez; her indirme sabit sürüm + SHA-256.
- Sürümler kod paketiyle (`updates.py`); yayın kuralları ve dağıtım `kurulum` becerisinde.

## Dosya haritası (`asistan/`)

- **Çekirdek `cekirdek/`** (Qt/fastapi yasak; eski gövdeye içe aktarmalar `test_cekirdek_ayrimi` listesiyle sınırlı):
  `ayar.py` (tek ayar kaynağı), `modeller.py`, `profil.py`, `yonlendirici.py`, `yapisal.py`, `semalar/`, `saglayici/`,
  `araclar/`, `istek.py`, `gorev/`, `yetenek/`, `analiz/`, `guvenlik.py`, `bildirim.py`, `uzak.py`.
- **Yüzler `arayuz/`:** `masaustu` (= `gui/`), `web/` (FastAPI + PWA), `komut/` (`python -m asistan …`).
- **Eski gövde:** `agent.py`, `manager.py`, `tools.py` + `registry.py`, `permissions.py` + `security.py`, `roster.py`/
  `cards.py`, `memory_db.py`/`learning.py`, `factory.py`/`mcp.py`/`browser.py`/`apps.py`, `cloud_server.py`/`cloud_sync.py`,
  `updates.py`/`bootstrap.py`/`problem_report.py`/`gpu.py`, görsel/3D/ses modülleri.
- **Arayüz `gui/`:** `window.py` + `window_*.py`, `worker.py`, `panels.py`, `sidebar.py`, `dialogs.py`, `setup_wizard.py`.
- **Veri:** `asistan/ayar/` (modeller.json, guvenlik.toml), `asistan/yetenekler/`. **Dağıtım:** `paketleme/`, `dagitim/`, `sunucu/`.
- **Testler:** `testler/` (unittest; `pytest.ini` yalnızca burayı toplar), `testler/arayuz_denetimi.py` (0 hata olmalı),
  `testler/sinav/` (gerçek görevli sınav: `calistir.py --hizli|--motor`, RAPOR.md).

## Araç ve yetenek ekleme

Yeni yerleşik araç: `tools.py`'de `REGISTRY.add(spec, risk, …)`, çalıştırıcı `Toolbox._tool_<ad>`; onay kuralı yalnızca
`permissions.py`. Yeni yetenek: `asistan/yetenekler/<ad>/` (`/yetenek-ekle`); manifest `izinler` → risk eşlemesi
`docs/SEMALAR.md` §1. Model adı kodda sabitlenmez. Testler gerçek veri klasörüne yazmaz (XDG geçici klasöre).

## Test komutu

```
QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest testler -q      # tam takım (~650 test)
.venv/bin/python testler/arayuz_denetimi.py                          # 0 hata beklenir
```

Commit atma; mesaj öner ("commitle" denince at). Tahmin etme: dosyayı aç, komutu çalıştır, sonucu göster.
