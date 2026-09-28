---
name: kurulum
description: Kurulum, kurulu kopyaya aktarma, paketleme, dağıtım paketleri (Light/Full, Windows/macOS/Linux), sunucu/Docker kurulumu, sürüm ve yayın işlerinde yükle — paketleme/aktar.sh, dagitim/paketle.py, updates.py, yayinla.sh kuralları burada.
---

# Kurulum, paketleme, dağıtım ve sürüm

## Kurulu kopya

- Kullanıcının çalıştırdığı kopya `~/.local/share/yeni-nesil-cafer-app/` (kendi Python'u `python/bin/python3`,
  kütüphaneler `ajan-kutuphaneleri/`). Kaynaktaki değişiklik kullanıcıya ancak `paketleme/aktar.sh` ile ulaşır; testler
  ve sınav kütüphane yolunu hep gerçek kurulumdan bağlar.
- Veri `~/.local/share/yeni-nesil-cafer/` (DATA_DIR), ayarlar `~/.config/yeni-nesil-cafer/`. 2.2 öncesi Yerel Asistan
  klasörleri ilk ayar yüklemesinde `ayar.klasorleri_tasi` ile taşınır, anahtarlar `keystore.OLD_SERVICE`'ten kopyalanır.
- Masaüstüne konan her şey (kurulum paketleri, sonuçlar, sorun raporları) tek `YENİ NESİL CAFER` klasöründe;
  programın ürettiği görseller/modeller `Sonuçlar/` altında (`results.py`).

## Kurulum kendi kendine yeter (pazarlık dışı)

- Kullanıcıya hiçbir zaman komut yazdırılmaz, elle bir şey indirtilmez. Tam paket her şeyi içerir; GitHub'dan inen
  paket eksikleri ilk açılışta kendisi indirir. Her indirme sabit sürüm + SHA-256 (`bootstrap.indir`: kaldığı yerden
  sürer, 416'yı ele alır).
- Ağır motorlar (resim üretimi, 3D, dikte) yalnızca düğmeyle kurulur. Kurulum sihirbazı (`gui/setup_wizard.py`):
  sistem analizi → "yerleşik modelle başla" → yetenek önerisi; ağ işleri arka planda.
- Bulut modelleri yalnızca API anahtarıyla değil, kullanıcının abonelik hesabıyla da kullanılabilmeli: yol resmi CLI
  programlarını çalıştırmak (`cli_agents.py`); Claude/Gemini API'sine hesapla giriş yok.
- Program kendi kodunu güncellemez; sorunları algılayıp Claude Code'a verilecek rapor hazırlar (`problem_report.py`).

## Sürüm ve güncelleme

- Sürümler kod paketiyle (`updates.py`: yalnızca `https://github.com/`, SHA-256, zip yol kaçışı denetimi, sürüm
  karşılaştırması tuple). Yeni sürüm 15 sn açık kalamazsa `main.rollback_if_needed` geri alır; düzgün kapanış çökme
  sayılmaz. Tek dosya (PyInstaller onefile) kopyada uygulama içi güncelleme uyumsuzdur (onedir + zip ya da
  "yeni sürümü indir"; SORULAR K11).
- Yayın `paketleme/yayinla.sh`: testler geçmeden, atlanan test varken, sınav eşiğin (`testler/sinav/esik.json`)
  altındayken yayın yok. CHANGELOG.md'ye sürüm notu, `pyproject.toml` sürümü.

## Dağıtım paketleri (K11)

- `dagitim/paketle.py`: `--hafif` (PyInstaller, platform kabı .exe/.dmg/AppImage), `--tam` (Light + Ollama + bütçeye
  sığan model, `--butce-gb 1.9`), `--guncelleme` (updates.ASSET + sha256), `--kuru` (plan). `.github/workflows/dagitim.yml`
  `v*` etiketinde üç platformda derler, taslak sürüme yükler. Büyük model dosyası repoya girmez.
- Paylaşılan paketlere geliştirici artıkları girmez: `.venv`, `.git`, `.cafer`, `.claude`, `NOTLAR`, `testler/sinav/sonuclar`,
  `sunucu/.env`, `__pycache__` her paketleyicide hariç (`paketleme/paketle.py` ve `dagitim/paketle.py` aynı listeyi kullanmalı).
- Her yeni değişiklikten sonra kurulum paketleri (Linux/Windows + bulut) yeniden üretilir; kullanıcı bunları
  arkadaşlarıyla paylaşıp denetiyor. Bulut paketi `paketleme/bulut_paketi.sh` → `dist/`.

## Sunucu (K8/K9)

- `python -m asistan sunucu` (FastAPI + PWA), Docker/Caddy `sunucu/` (`kur.sh` idempotent, `.env` → `CAFER_TOKEN`),
  kurulum adımları `docs/SUNUCU_KURULUM.md`, yerelde deneme `/sunucu` komutu. Sunucu anahtarı günlüğe basılmaz.
- Uzak mod: masaüstü Ayarlar → sunucu adresi + anahtar; görevler eşitlenir (son yazan kazanır), sunucudan gelen iş
  bilgisayarda yalnızca kullanıcı "yap" deyince çalışır. Bildirim ntfy/Telegram (`cekirdek/bildirim.py`).
