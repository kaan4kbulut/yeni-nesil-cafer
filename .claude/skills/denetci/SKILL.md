---
name: denetci
description: Bir aşama ya da değişiklik bitince denetim yaparken, /kontrol koşarken, denetci ajanını çalıştırırken ya da bir hata/donma/çökme ayıklarken yükle — sağlık kontrolü adımları, mimari kural listesi, rapor biçimi ve bilinen tuzaklar (NVIDIA sürücüsü, XDG test yalıtımı, küçük modellerin davranışı) burada.
---

# Denetim

**Düzeltme yapma; bul ve raporla.** "Amaç neydi" diye değil "ne yapıyor" diye bak. Değişiklik `git diff` (ya da
`git diff <etiket>`); yoksa son commit.

## /kontrol adımları (hepsini gerçekten koş; "sanırım geçer" yok)

| # | Kontrol | Komut |
|---|---|---|
| 1 | Testler | `QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest testler -q` (~650 ✓ / 0 ✗ / 21 atlandı: 3D/belge kütüphanesi yokluğu) |
| 2 | Çekirdek import dumanı | `python -c "import asistan.cekirdek"` + `profil, yonlendirici, gorev, yetenek, analiz, guvenlik, uzak, bildirim` |
| 3 | Masaüstü / web import dumanı | `python -c "import asistan.arayuz.masaustu"`, `python -c "import asistan.arayuz.web"` (GUI açma) |
| 4 | CLI | `python -m asistan --help` |
| 5 | Çekirdek–arayüz ayrımı | `asistan/cekirdek/` içinde `PySide6|PyQt|fastapi|starlette` import'u → 0 (`test_cekirdek_ayrimi`) |
| 6 | Model adı sabitleme | `asistan/` içinde `:7b`, `:14b`, `claude-`, `gpt-` desenleri → yalnızca `modeller.json` |
| 7 | Manifest doğrulama | `python -m asistan yetenek --dogrula` ve `--duman` (her yeteneğin `ornekler`i izin hattından) |
| 8 | Arayüz denetimi | `.venv/bin/python testler/arayuz_denetimi.py` → 0 hata |
| 9 | Lint | `ruff check asistan/` (yoksa "kurulu değil", kurma) |

"hizli" kipinde yalnızca 1, 2, 3, 5. Sonda tablo + her kırmızı için tek satır teşhis (dosya:satır) + "aşama bitmiş
sayılabilir mi?" cümlesi.

## Diff'te aranacaklar

- Çekirdekte Qt/fastapi; koda gömülü model adı; yeni modülün testi yok; kurulum/silme/ağ gönderme `permissions.decide`
  dışından; ağır bağımlılık çekirdeğe (`pyproject.toml` diff'i).
- `except: pass` / log'suz `except Exception`; zaman aşımsız alt süreç ya da ağ çağrısı; GUI iş parçacığında ağ/
  `subprocess`/`sleep`; onaysız silen/üzerine yazan kod; atomik olmayan JSON yazımı (tmp + `os.replace` yok);
  iş klasörü dışına yol (`..`, sembolik bağ, mutlak yol); `shell=True` ile model girdisi; alt sürece tam ortam.
- Türkçe/İngilizce karışık adlandırma; test edilmeyen hata dalı.

## Rapor biçimi

```
## Sonuç: GEÇTİ | ŞARTLI | KALDI
### Engelleyici (aşama bitmiş sayılmaz)
- dosya:satır — sorun — neden engelleyici
### Uyarı
- dosya:satır — sorun
### Testler
- N geçti / M kaldı / K atlandı
### İyi olan
- (1–3 madde)
```
Engelleyici yoksa ve testler yeşilse GEÇTİ. Stil sorunları "Uyarı"dır.

## Bilinen tuzaklar (tam metin: `NOTLAR/arsiv/mimari-ayrintilar.md`)

- NVIDIA sürücüsü bellek baskısında bozulabilir (Xid 62/154, "Reset required"): Ollama sessizce CPU'ya düşer, her şey
  "takılır", `nvidia-smi` `ERR!`. `gpu.fault()` algılar (30 sn önbellek), `power.saving` True, çözüm yeniden başlatma.
  Testler `gpu.fault`'u taklit eder. 12 GB karta 14B model 32K bağlamla sığmaz (kısmen CPU → zaman aşımı).
- Testler gerçek veri klasörüne yazmamalı: her test dosyası `asistan`'ı içe aktarmadan ÖNCE `XDG_CONFIG_HOME`/
  `XDG_DATA_HOME`'u geçici klasöre alır; sessizce atlanan test kabul edilmez (21 atlanan listesi bilinir).
- Anahtarsız ya da 401 alan bağlantı yönlendiricide ve menülerde atlanır (`Connection.usable`).
- Gemma 4 sistem talimatı olmadan araç çağırmaz; kartlar: gemma3/dolphin3 araç 0/3. Araç sınavını geçemeyen model
  işçi yoksa araç seçici kipinde (`agent._run_selector`). Küçük modeller dosya adını kısaltır, planı Çince yazar.
- Sistem talimatı + araç tanımları ~5.600 token; 8K bağlamda `agent.lean`. `anthropic` SDK'sı tembel yüklenir.
- Aynı süreçte `testler/` ve `asistan/yetenekler/*/test_*.py` aynı modül adıyla çakışır (`pytest.ini testpaths`).
- Alt süreç testleri projenin Python'uyla koşar (`.venv/bin/python`); `sys.executable` sonucu değiştiriyordu.
