# K12 — Kod incelemesi ve düzeltme (Claude Code talimatı)

CLAUDE.md'yi oku. k-serisi dalında tek başına çalış. Bana soru sorma; karar gerekirse NOTLAR/SORULAR.md'ye "geçici karar" yaz, devam et. Testler için yalnızca `.venv/bin/python`; `QT_QPA_PLATFORM=offscreen`. Yeni özellik ekleme; kapsam dışı fikri NOTLAR/SONRAYA.md'ye yaz.

## 0. Ön hazırlık
- `NOTLAR/claude-settings.json` dosyasını `.claude/settings.json` üzerine kopyala (`cp`), sonra `NOTLAR/claude-settings.json`'u `git rm` ile kaldır. (İzinler yeni oturumda geçerli olur; bu oturumda push için izin sorarsa onaylayacağım.)
- `git status` temiz mi, `git log --oneline -5`; `git push -u origin k-serisi` (izin verildi; `--force` yasak).
- `nvidia-smi` çalıştır. Kart görünüyorsa `testler/sinav/calistir.py --hizli --motorsuz` ve `--motor` koş, RAPOR.md'ye yaz, SORULAR.md'deki B7 (motor varsayılan mı) sorusunu sonuca göre karara bağla. Kart görünmüyorsa "gpu.fault sürüyor" diye NOTLAR'a yaz, sınavı atla.

## 1. İNCELEME (kod değiştirme)
Üç alt ajanı paralel başlat; her biri kendi alanındaki dosyaları TAM okusun ve yalnızca doğruladığı, dosya:satır ile gösterdiği gerçek hataları raporlasın (stil değil):
- a) Çekirdek: `asistan/cekirdek/*` (gorev, yonlendirici, saglayici, ayar, istek, analiz, yetenek) + eski gövde agent/manager/permissions/security/work/storage. Odak: onay hattı atlatmaları, GUI↔worker paylaşılan durum, bağlam sıkıştırma, Ollama takılması, CLAUDE.md "pazarlık dışı" kurallarıyla çelişki, çekirdek→eski gövde bağımlılığı.
- b) Araç katmanı: `araclar/*`, yetenek manifestleri, sandbox, registry/factory/mcp/browser/apps/libraries/hooks/cli_agents/keystore/learning/memory_db. Odak: komut enjeksiyonu, iş klasörü dışına yazma, sandbox'ın gerçekten yalıtıp yalıtmadığı, sır sızıntısı, MCP güveni, subprocess zombileri.
- c) Arayüz + dağıtım + bulut: `arayuz/masaustu`, `arayuz/web` (FastAPI+PWA), main, bootstrap, updates, cloud_server, cloud_sync, `dagitim/`, `sunucu/`, `paketleme/`. Odak: GUI iş parçacığında ağ/subprocess (donma), atomik olmayan kayıt, güncelleme/geri alma döngüleri, token/kimlik doğrulama, senkron çakışmaları, sızıntılar.

Raporları birleştirip `NOTLAR/inceleme-k12-2026-09-28.md`'ye yaz: A güvenlik/onay, B sandbox/sırlar, C ayar/durum, D donmalar, E döngü/güncelleme/bulut, F düşük. Her madde: dosya:satır — sorun — neden önemli — düzeltme. Commit: "K12: inceleme raporu".

## 2. DÜZELTME
A'dan başla, bölüm bitince commit, sonra B, C, D, E, F. Her madde: önce başarısız test (`testler/`, XDG kuralıyla), sonra düzeltme, yeşil test. Onay kuralları yalnızca permissions.py'de. Düzeltemediğin maddeyi rapora "ertelendi: <neden>" diye işaretle, silme. Limit gelirse kaldığın bölümü `.cafer/ilerleme.json`'a yaz; "devam et" dediğimde oradan sür.

## 3. BİTİŞ
Tam test takımı yeşil, `testler/arayuz_denetimi.py` 0 hata, `/kontrol`. Raporun başına durum tablosu; `NOTLAR/2026-09-28-K12.md` özet; `.cafer/otomatik.json` tamamlanan'a K12; `git push`. Son satır: `SONUÇ: TAM|KISMEN · TEST: N✓/M✗/K atlandı`.
