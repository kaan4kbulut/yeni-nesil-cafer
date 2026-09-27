---
description: Tüm sağlık kontrollerini koşar (test, import dumanı, çekirdek-arayüz ayrımı, manifest doğrulama) ve tablo halinde raporlar
argument-hint: [isteğe bağlı: "hizli" — sadece test + import]
---

Mod: $ARGUMENTS

Aşağıdaki kontrolleri sırayla koş. Her birinin sonucunu ✅/❌ ile tabloya yaz. Hiçbir kontrolü "sanırım geçer" diye atlama; komutu gerçekten çalıştır.

| # | Kontrol | Komut / yöntem |
|---|---|---|
| 1 | Testler | `python -m pytest testler/ -q` (klasör yoksa "yok" yaz, ❌ değil) |
| 2 | Çekirdek import dumanı | `python -c "import asistan.cekirdek"` ve varsa alt modüller (`profil`, `yonlendirici`, `gorev`, `yetenek`, `analiz`) — henüz olmayan modülleri atla, listele |
| 3 | Masaüstü import dumanı | `python -c "import asistan.arayuz.masaustu"` (ya da mevcut giriş modülü; `pyproject.toml`/`setup.py`'den bul). GUI açma, sadece import. |
| 4 | Web import dumanı | `python -c "import asistan.arayuz.web"` — yoksa "henüz yok" |
| 5 | CLI | `python -m asistan --help` ya da `cafer --help` — hangisi tanımlıysa |
| 6 | Çekirdek-arayüz ayrımı | `asistan/cekirdek/` içinde `PySide6`, `PyQt`, `qt`, `fastapi`, `starlette` import'u grep'le → 0 eşleşme olmalı |
| 7 | Model adı sabitleme | `asistan/` içinde `ollama run`, `:7b`, `:8b`, `:14b`, `claude-`, `gpt-` gibi model adı desenleri grep'le → `modeller.json` dışında eşleşme olmamalı (varsa listele; ❌ yerine ⚠️) |
| 8 | Manifest doğrulama | `yetenekler/*/manifest.json` dosyalarını `docs/SEMALAR.md` §1'e göre doğrula; `ad` klasör adıyla aynı mı, zorunlu alanlar var mı, `izinler` geçerli mi. Her yetenek için `ornekler` varsa `calistir.py` ile duman testi koş (sandbox, 30 sn). |
| 9 | Üretilen yetenekler | `kaynak: "uretildi"` ve `guvenilir: false` olanları ayrı listele |
| 10 | Lint | `ruff check asistan/` (ruff yoksa "kurulu değil" yaz, kurma) |

"hizli" modunda sadece 1, 2, 3, 6 koş.

Sonunda:
- Tablo
- Kırmızıların her biri için tek satır teşhis (dosya:satır)
- Bir cümle: aşama bitmiş sayılabilir mi?

Kırmızıları bu komut içinde **düzeltme**; sadece raporla. Düzeltme `/asama` ya da `/hata-analiz` işi.
