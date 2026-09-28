# İnceleme düzeltmeleri — BÖLÜM 2 (2026-09-28, `NOTLAR/INCELEME-2026-09-28.md` §6 sıra 4→8 ve §2 küçükler)

Her madde ayrı commit, önce başarısız test sonra kod. `.venv` pytest: 557 ✓ / 0 ✗ / 21 atlandı (3D kütüphaneleri).

| # | Sorun (rapor) | Düzeltme | Test |
|---|---|---|---|
| 2.1 | `araclar/komut.py` alt süreç bütün ortamı miras alıyordu (ANTHROPIC_API_KEY, CAFER_*) | `komut.guvenli_ortam`: beyaz liste (PATH, HOME, LANG, TERM, PYTHON*, LC_*, XDG_*, sertifika yolları, Windows sistem değişkenleri) + `izinli` (manifest `anahtar:<AD>`) + `ek` (SUDO_ASKPASS). CAFER_* ve ANTHROPIC_API_KEY istense de geçmez. bash, sudo, PowerShell, run_python yolları | `test_cekirdek_araclar.KomutTesti.test_alt_surecte_sir_yok` (gerçek `env`) |
| 2.2 | `Settings.anthropic_api_key` hâlâ vardı, `ayarlar.json` okunabiliyordu | Alan silindi; `ayar.eski_anahtar()` açılışta zincire taşır, `save()` dosyadan siler. `GIZLI_DOSYALAR` += `ayarlar.json`; `dosya.yol_coz` `CONFIG_DIR` altını okuma kökü olsa da reddeder | `test_gizli_ayarlar.py` |
| 2.3 | `gorev/model.py` her hatada sıradakine geçiyordu; `Zincir` ölü | Döngü `Zincir.secimden(karar)`: aynı modelde 2 hata → sıradaki; ulaşılamayan (bağlantı/zaman aşımı/401) → hemen sıradaki; `Iptal` yeniden fırlatılır; şema hatası zincir başarısızlığı değil. `Zincir.atla` (tavan), `Zincir.ekle` | `test_gorev_modeli.py` |
| 2.4 | Tavan karakter/4 tahminiyle, `yapisal.uret`'in 2. çağrısı sayılmıyordu, sayaç `threading.local`, defter yarışı | `Saglayici.kullanim` (Claude: input+cache_creation+cache_read / output; OpenAI: prompt/completion); `yapisal.harcama_yaz` her çağrıda; sayaçlar görev kimliğiyle (`gorev_basla(gorev_id)`, `harcama_ekle(..., gorev_id=)`; kimliksiz çağrı bu isteğin sayacı); defter `flock`/`msvcrt`; `maliyet()` `modeller.json → fiyatlar` (USD/1M) | `test_bulut_tavani.py` |
| 2.5 | CLI ajanı motorun planlayıcısı oluyordu, sürecin cwd'sinde | `sec(..., cli_yalnizca_kod=True)`: motor rollerinde (`planlama/analiz/siniflandirma/ozet`) CLI aday değil; `YonlendiriciModeli(klasor=)`: `cli:*` çağrıları `klasor=iş klasörü, duzenleyebilir=False`; `adaylar()` CLI adayı `cards.card("cli:claude")` varsa ondan, yoksa sınanmadı (`arac/plan None`) | `test_cli_rolu.py` |
| 2.6 | Rol `hizli` en güçlü yereli seçiyordu | Karta sığan + araç sınavını tam geçenlerden `profil.json → benchmark.tok_sn` en yüksek; ölçüm yoksa en küçük puanlı. `Durum.hiz`. Büyükler zincirde üst basamak | `test_cekirdek_yonlendirici` (güncellendi) |
| 2.7 | Küçükler | `_VAR_OLMALI` `\b`; denetleyici yoksa adım **ŞARTLI** (`adim["sartli"]`, raporda `✓?`, "N/M doğrulandı, k şartlı"); `siniflandir` 5xx yalnızca HTTP bağlamı, CUDA yalnızca bellek/hata, "bulunamadı" yalnızca dosya/klasör, "bağlı adım bitmedi" → `mantik`; `Depo.kaydet` kilit + `BEGIN IMMEDIATE` + `_surum` uyarısı; `web.oku` localhost/özel ağ/link-local engeli + 2 MB gövde (`httpx.stream`); OpenAI uyumlu okuma 150 sn; Ollama şemalı çağrıya `num_ctx`; `ayar.klasorleri_tasi` ilk `Settings.load/save/exists`'te | `test_kucuk_duzeltmeler.py` |

Yapılmayan / karar bekleyen: 2.5'te CLI ajanı için gerçek bir sınav yok (kart yoksa "sınanmadı"); sınav CLI'yi
`claude -p` ile çağırır, abonelik harcar → kullanıcının düğmesiyle olmalı (SORULAR). ₺ karşılığı (fiyat listesi TL)
K3'ten kalan açık iş, burada yalnızca USD listesi eklendi.
