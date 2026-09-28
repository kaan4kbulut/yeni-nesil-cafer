# modeller.json kademe listeleri — geçici öneri (2026-09-28, otomatik mod)

`asistan/ayar/modeller.json → kademe` otomatik modda, kullanıcıya sorulamadan dolduruldu; dosyada `"gecici": true` ve
`"gecici_not"` bunu işaretler. Beğenmezsen listeyi değiştir, bu iki alanı sil; kod dokunulmaz. Her listede **ilk ad o
kademenin varsayılanı** (kademe tanımları: `docs/MIMARI.md` §3).

İlk sürümdeki (K2) seçimden farklar: bulutta Gemini yerine OpenAI (istek: Claude + OpenAI uyumlu), `orta`'da 9B öne
alındı (kademe 7–8B sınıfı), `yuksek`'ten `qwen2.5-coder:14b` çıktı (kartlarda araç 0/6; yönetici/işçi olamaz) ve 32B
sınıfı için `qwen3.6:27b` eklendi (`kategoriler.boyutlar`'a 18 GB olarak yazıldı; test bilinen boyut istiyor).

## Adaylar (araştırma)

| Sınıf | Aday | Boyut (Ollama) | Neden | Yedek |
|---|---|---|---|---|
| 3B | `qwen3.5:2b` | 2,7 GB | Qwen3.5 ailesi (Ollama'da en çok indirilen yeni kuşak, 21 M): her boyutta araç + düşünme + görme, 256K bağlam. 8 GB RAM'de temel modelin (4b) yanında da sığar. | `qwen3.5:4b` (3,4 GB; küçük modeller içinde araç çağırmada en iyisi, bu makinede 2b'nin bozduğu işleri doğru yaptı) · `llama3.2:3b` (araç çağırmada daha zayıf) |
| 7–8B | `qwen3.5:9b` | 6,6 GB | Ailenin 8 GB karta sığan en büyüğü; bu makinede kurulu ve kategorilerde zaten ilk sıralarda. Ollama'da 7–8B'lik yeni kuşak araç+görme modeli yok (qwen3:8b bir kuşak eski). | `qwen3:8b` (5,2 GB, yalnız metin) |
| 14B | `gemma4:12b` | 7,6 GB | Yeni kuşak (Gemma 4, 5 gün önce güncellendi), yerleşik işlev çağırma, görme + ses, 256K; 12 GB karta rahat sığar, 27–31B'lere göre ~2,5 kat hızlı. Tuzak: sistem talimatı olmadan araç çağırmaz (CLAUDE.md). Qwen3.5/3.6'da 14B yok. | `qwen3:14b` (9,3 GB, araç + düşünme) |
| 32B | `qwen3.6:27b` | 18 GB | 3.5'e göre ajan tipi kod ve araç kullanımında belirgin ilerleme (TAU2'de Gemma 4 31B'yi geçiyor); 24 GB karta sınırlı bağlamla sığar. | `gemma4:31b` (20 GB, daha hızlı, araç çağırması daha kararlı) · `qwen3.6:35b` (23 GB, MoE 3B etkin: işlemciye taşarken de hızlı) |

| Sağlayıcı | Rol | Aday | Fiyat ($/M token, giriş/çıkış) | Neden | Yedek |
|---|---|---|---|---|---|
| Claude | ucuz-hızlı | `claude-haiku-4-5` | 1 / 5 | Serinin en hızlısı, araç + görme. **Dikkat: emeklilik "15 Ekim 2026'dan önce değil"** — o tarihten sonra `claude-sonnet-5`'e geçilmeli. | `claude-sonnet-5` (2 / 10, hızlı, 1M bağlam) |
| Claude | güçlü | `claude-opus-5-5` | 4 / 20 | Anthropic'in "çoğu iş için önce bunu dene" önerisi; uzun ajan işleri ve kod. | `claude-fable-5-1` (10 / 50; en zor akıl yürütme) |
| OpenAI uyumlu | ucuz-hızlı | `gpt-6-luna` | 0,10 / 0,50 | Güncel kuşağın en ekonomik modeli; `bulut_katalog.openai`'de zaten var. | `gpt-6-sol` |
| OpenAI uyumlu | güçlü | `gpt-6-astra` | 10 / 50 | Güncel kuşağın en yeteneklisi. | `gpt-6-sol` (2 / 10, dengeli; 21 Kasım 2026'ya dek indirimli) |

## Kademe × rol

Roller `modeller.json → roller`: yönetici = en güçlü erişilebilir, hızlı = en ucuz/hızlı erişilebilir, kod = CLI ajanı >
bulut > yerel. Seçimi K3 yönlendiricisi yapar; bu tablo onun hedefi. "Bulut" sütunu anahtar varsa geçerli
(`Connection.usable`); yoksa yerel sütun.

| Kademe | Rol | Yerel | Bulut | Neden |
|---|---|---|---|---|
| dusuk | yönetici | `qwen3.5:2b` (yalnız bulut yoksa; iş küçük parçalara bölünür) | `claude-haiku-4-5` · `gpt-6-luna` | ≤ 8 GB RAM, GPU yok: yerelde plan kalitesi düşük; MIMARI §4 madde 4 gereği bulut varsa bulut. Ucuz bulut modeli bile 2B'den iyi planlar. |
| dusuk | hızlı | `qwen3.5:2b` | `gpt-6-luna` | Yerel 2,7 GB işlemcide çalışır; bulutta en ucuzu. |
| dusuk | kod | `qwen3.5:2b` (yalnız basit betik) | `claude-haiku-4-5` | Küçük model kodda dosya bozuyor; kod işi buluta gitmeli. |
| orta | yönetici | `qwen3.5:9b` | `claude-sonnet-5` · `gpt-6-sol` | 16 GB RAM / ≤ 6 GB VRAM: 9B yavaş ama planlayabilir; MIMARI "karmaşık işler bulut" dediği için dengeli bulut modeli. |
| orta | hızlı | `qwen3.5:4b` | `gpt-6-luna` | 4B pakete gömülü temel model, CPU'da kabul edilebilir hız; araç çağırmada 2B'den belirgin iyi. |
| orta | kod | `qwen3.5:9b` | `claude-sonnet-5` | Kod üretimi MIMARI'de buluta yönlendirilir; yerel yalnız bulut yoksa. |
| yuksek | yönetici | `qwen3.6:27b` (≥ 20 GB VRAM) / yoksa `gemma4:12b` | `claude-opus-5-5` · `gpt-6-astra` | ≥ 8 GB VRAM'de yerel varsayılan; 27B yalnız karta sığıyorsa (12 GB kartta sığmaz, işlemciye taşar, yavaş). |
| yuksek | hızlı | `gemma4:12b` (8 GB kartta `qwen3.5:9b`) | `claude-haiku-4-5` | Gemma 4 12B hız/kalite dengesi; 27–31B'nin ~2,5 katı hızlı. |
| yuksek | kod | `qwen3.6:27b` / yoksa `gemma4:12b` | `claude-opus-5-5` | CLI ajanı (`cli:claude`, `cli:codex`) varsa önce o; `qwen2.5-coder` araç çağıramadığı için ajan işine uygun değil. |
| sunucu | yönetici | — | `claude-opus-5-5` · `gpt-6-astra` | GPU'suz sunucuda yerel çıkarım yok (MIMARI §3). |
| sunucu | hızlı | — | `claude-haiku-4-5` · `gpt-6-luna` | Kuyruktaki küçük işler, özet, sınıflandırma. |
| sunucu | kod | — | `claude-opus-5-5` | CLI ajanları sunucuya/kuyruğa bağlanmaz (CLAUDE.md kalıcı karar). |

## Açık noktalar

- Bu makine (12 GB kart) `yuksek`; `qwen3.6:27b` burada karta sığmaz. K3 yönlendiricisi aday seçerken
  `kategoriler.boyutlar` ile VRAM'i karşılaştırmalı (`categories.fits` benzeri); liste yalnız öneri.
- `claude-haiku-4-5` emekliliği yakın (15 Ekim 2026 sonrası). Tarih geçince `dusuk`/`sunucu` listelerinde
  `claude-sonnet-5` ile değiştir; `model_updates.py` bunu kendisi yakalamıyor.
- `basamaklar.chat` hâlâ bir kuşak eski `qwen3:*` modellerini öneriyor; bu işin kapsamı dışında bırakıldı.
- Fiyatlar ve boyutlar 2026-09-28'de şu kaynaklardan: ollama.com/library (qwen3.5, gemma4, qwen3.6 etiket sayfaları),
  platform.claude.com/docs/en/about-claude/models/overview, developers.openai.com/api/docs/pricing; karşılaştırmalar
  betterclaw.io (Gemma 4 31B vs Qwen 3.6 27B), regolo.ai (Gemma 4 31B vs Qwen3.6 35B-A3B), promptquorum.com (yerel araç çağırma).
