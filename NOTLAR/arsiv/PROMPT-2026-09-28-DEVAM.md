# Claude Code görev listesi — 2026-09-28 (K5'ten kapanışa)

Bu oturumda k-serisi dalında tek başına, sırayla ve commit'leyerek çalış.

## Kurallar
- Her BÖLÜM sonunda `QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest -q` koş (pytest yoksa `-m unittest`); atlanan testler geçmiş sayılmaz; kırmızıysa ilerleme; commit at ("Kx/Bölüm-N: ...").
- Testler ve alt süreçler için yalnızca `.venv/bin/python`; sistem Python'unu kullanma.
- Bana soru sorma. Karar gerekiyorsa en makul kararı ver, NOTLAR/SORULAR.md'ye "geçici karar" olarak yaz, devam et.
- Her düzeltmede önce başarısız test, sonra kod.
- İlerlemeyi TaskCreate ile tut; her bölüm bitince `.cafer/ilerleme.json` güncelle. Limit gelirse kaldığın yer ilerleme.json'da yazılı olsun; "devam et" dediğimde oradan sür.
- Her bölüm sonunda tek satır: `SONUÇ: TAM|KISMEN · TEST: N✓/M✗/K atlandı`.
- Yeni özellik ekleme; kapsam YAPILACAKLAR.md, docs/MIMARI.md, docs/SEMALAR.md ve iki inceleme raporudur. Model adları yalnızca ayar/modeller.json'da; koda yazma.
- Ayrı bir "LM Studio benzeri program" fikri bu projenin dışında; ona dokunma.

## Önce oku
CLAUDE.md, YAPILACAKLAR.md, docs/MIMARI.md, docs/SEMALAR.md, NOTLAR/INCELEME-2026-09-28.md (K-serisi raporu; "rapor §" atıfları buna), NOTLAR/inceleme-2026-09-28.md (70 maddelik A–F raporu, K12), NOTLAR/SORULAR.md, NOTLAR/KONTROL_LISTEN.md, NOTLAR/MEVCUT_DURUM.md, .cafer/otomatik.json, .cafer/ilerleme.json, otomatik.py, .claude/settings.json, .claude/commands/*.

## BÖLÜM 0 — Durum tespiti (K5 yarıda kesildi)
otomatik.py K5'i 03:24'te başlattı, 04:09'da ikinci deneme başladı, sonra Ctrl+C ile durduruldu. `git status`, `git log --oneline -20`, `git diff --stat`:
- Çalışma ağacındaki ve varsa "yarım"/"WIP" commit'lerindeki K5 değişikliklerini incele; tutarlı ve derleneni koru, kırığı geri al ya da tamamla. Ne tuttuğunu NOTLAR/2026-09-28-K5.md'ye yaz.
- `.cafer/otomatik.json`: `tamamlanan` = K0–K4 (doğru); `sureler`'den K5–K10'un 6–13 sn'lik sahte değerlerini sil.
- `NOTLAR/KONTROL_LISTEN.md`: 00:08–00:10 tarihli K2–K10 blokları (sahte tamamlanma) silinecek; 01:31 sonrası gerçek K2/K3/K4 blokları kalacak.
- `.claude/settings.json` allow: `Bash(.venv/bin/python:*)`, `Bash(/home/caferkaandebana/.local/share/yeni-nesil-cafer-app/python/bin/python3:*)`. "workspace not trusted" uyarısının kaynağını bul, gerekirse `.claude/settings.local.json` ile çöz ve NOTLAR'a yaz.
- `ayar/modeller.json`: `"gecici": true` kaldır; `varsayilan.claude`'u kademe listeleriyle aynı ada getir; `install_hint` K10'a kalıyor.
- Sansürsüz model: mevcut opt-in davranışı korunur, varsayılan değişmez; sansürsüz seçim yalnızca `cards.py` sınavını geçen modellerden yapılabilsin (test ekle).
Commit.

## BÖLÜM 1 — K4'ten kalanlar
- test_cekirdek_ayrimi alt süreç testlerini `sys.executable` yerine proje Python'una bağla; düşen 2 test yeşil.
- test_bulut.Esitleme kararsızlığını deterministik yap.
- Atlanan 21 testin nedenlerini listele; ortamda koşabilecekleri (Qt offscreen, httpx) koşar hale getir.
- main.py geri alma (rollback) eşiği ve sahte pozitif limit tespiti — varsa düzelt.
Commit.

## BÖLÜM 2 — Öncelikli düzeltmeler (rapor §6 sıra 4→8, sonra §2 küçükler; her madde ayrı commit)
2.1 Sır sızıntısı (araclar/komut.py:192,195): alt sürece beyaz listeli ortam (PATH, HOME, LANG, TERM, PYTHONPATH + manifest `anahtar:<ad>` ile açıkça istenenler). ANTHROPIC_API_KEY, CAFER_TOKEN, CAFER_* hiçbir zaman geçmez. Test: alt süreçte `env` çıktısında yok.
2.2 ayar.py: `Settings.anthropic_api_key` alanını kaldır, anahtar yalnızca anahtarlar.json'da; araclar/dosya.py gizleme listesine ayarlar.json + anahtarlar.json; read_file CONFIG_DIR'i okuyamasın.
2.3 Zincir (gorev/model.py:283-305): döngü `yonlendirici.Zincir.secimden(karar)` üzerinden; MIMARI §4.5 eşiği (2 başarısızlık ya da zaman aşımı); `Iptal` ve şema/400 "sıradaki modele geç" sayılmaz, `Iptal` yeniden fırlatılır. Zincir üretimde kullanılıyor olmalı.
2.4 Bulut tavanı (model.py:306-307): sağlayıcı `usage` verisi; `yapisal.uret` her çağrıda `harcama_ekle`; `saglayici.maliyet()` gerçek değer; görev sayacı threading.local yerine görev id; `_defter_kilidi` için dosya kilidi.
2.5 CLI ajanı (gorev/komut.py:48, model.py:294): motorda `cli:claude` yalnızca `kod` rolünde; `sohbet(..., klasor=self.klasor, duzenleyebilir=False)`; yonlendirici.py:586-588 sabit puan yerine gerçek sınav.
2.6 `hizli` rolü (yonlendirici.py:376-395): karta sığan + araç sınavını geçenlerden `benchmark.tok_sn` en yüksek (yoksa en küçük puan); modeller.json.roller.hizli ile uyumlu.
2.7 Küçükler: dogrulayici.py:297 regex `\b`; :342-353 denetleyici yoksa adım ŞARTLI, geçmiş sayılmaz; yurutucu.py:55-64 siniflandir yanlış pozitifleri; durum.py:60 kilit; web.py:274-286 localhost/LAN engeli + gövde sınırı; openai_uyumlu.py:174 zaman aşımı 150; model.py:296 `num_ctx`; ayar.py:48-49 migrate_dir içe aktarma anında çalışmasın.

## BÖLÜM 3 — K5 (kaldığı yerden)
YAPILACAKLAR.md K5 bölümü. K4'ten devralınan riskler: (a) manifest `izinler` → `permissions.decide` eşlemesi tanımla ve SEMALAR.md'ye yaz; `izin_kaynagi=None` iken dosya yazma onaysız olmasın. (b) REGISTRY + manifest tek kayıt. (c) sandbox 2.1 beyaz listesini zorunlu kılsın. (e) `/kontrol` duman testi çalıştırıcısı. (f) Playwright bağımlı `tarayici` çekirdeğe girmesin.
NOTLAR/2026-09-28-K5.md, commit, SONUÇ.

## BÖLÜM 4 — K6 … K10
YAPILACAKLAR.md sırasıyla; her aşama: uygula → test → NOTLAR/2026-09-28-Kn.md → commit → otomatik.json.tamamlanan → SONUÇ. KISMEN kalırsa sıradakine geçme, dur.
Hatırlatmalar: K6 hata sınıfları `analiz/hata.py` üzerinden akmalı (hata_sirasi.jsonl'e yazıp geçmek yetmez), üretilen yetenek sandbox testi geçmeden kayda girmez. K7 Modeller sekmesinde "listeyi yenile" ile 10 önerilen bulut+yerel model listesi güncellenir. K8 PWA masaüstüyle aynı retro/sade dilde; ucuz VPS (2 vCPU/4 GB) için docs/SUNUCU_KURULUM.md. K9 bildirim (ntfy/Telegram). K10 kurulum sihirbazı, `dusuk` kademede sade UI ve <3 sn açılış, CHANGELOG.md; arayüz genel olarak daha sade ve retro.

## BÖLÜM 5 — K11 dağıtım (planda eksik, önce plana ekle)
YAPILACAKLAR.md'ye K11'i yaz (otomatik.py'deki prompt ile aynı tanım): Windows .exe, macOS .dmg, Linux .AppImage; Full sürüm ≤1.9 GB (GitHub 2 GB sınırı; gömülü llama.cpp motoru + varsayılan yerel model, kurulur kurulmaz çevrimdışı çalışır) ve Light ~200 MB; `dagitim/paketle.py`; GitHub Actions ile üç platform derleme ve sürüm yükleme; ilk açılışta sistem analizi + yetenek önerisi sihirbazı; mevcut in-app güncelleme mekanizmasıyla uyum. Sonra uygula.

## BÖLÜM 6 — K12: NOTLAR/inceleme-2026-09-28.md
Rapor K1 öncesi koda göre yazıldı: her maddeyi işlev adıyla yeni yerinde bul; K serisinde çözülmüşse "çözüldü (Kn)" yaz ve geç. Sıra A (onay hattı atlatmaları) → B (sandbox/sır) → C (ayar/durum) → D (GUI donmaları) → E (ajan döngüsü/güncelleme/bulut) → F (düşük öncelik). Her madde önce test, sonra düzeltme, ayrı commit. Sonunda raporun başına durum tablosu ekle.

## BÖLÜM 7 — Belge tutarlılığı
- MIMARI §2 `.cafer/` → DATA_DIR; §3 `yuksek` sınırı 12 GB karta göre; §4.3 `hizli` tanımı 2.6 ile hizalı; §4.5 ve §5 hata akışı kodla eşleşsin; K11 MIMARI'ye eklensin.
- CLAUDE.md ≤150 satır; dosya haritası `cekirdek/` yapısına göre; manager.py/registry.py "en kritik parça" anlatımı kalksın.
- Çekirdek→eski gövde içe aktarmaları (istek.py, gorev/ajan.py, cli_ajan.py) test_cekirdek_ayrimi'ye bekçi olarak eklensin ve giderilsin.
- Manager ↔ gorev/ çift planlayıcı, çift yükselme yolu, çift şema üretimi: bayrak kaldırılıp tek yol kalsın; kalkamıyorsa nedeni SORULAR.md'ye.
Commit.

## BÖLÜM 8 — otomatik.py sürücüsü
Bir dahaki gecelik koşu için: zaman aşımında Claude'u öldürüp yarım commit atma (önce SIGINT, bekle, yarım değişiklikleri stash'le ve aşamayı KISMEN say); ilk denemenin süresini kaydet; `acik_kutular` YAPILACAKLAR'da bölüm yoksa aşamayı geçmiş saymasın; `--python` seçeneği; limit tespiti ile zaman aşımı ayrı sınıflar; SONUÇ satırı zorunlu. Testleriyle. Commit.

## BÖLÜM 9 — Kapanış
Tam test takımı, `/kontrol`, `git push -u origin k-serisi`, NOTLAR/2026-09-28-KAPANIS.md: yapılanlar, açık kalanlar, SORULAR.md'de karar bekleyen en önemli 5 madde. Son satır `SONUÇ: ...`.

Başla: BÖLÜM 0.
