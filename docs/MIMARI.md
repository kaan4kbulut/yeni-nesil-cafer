# YENİ NESİL CAFER — Hedef Mimari (v3: Kademeli ve Bulut Uyumlu)

Bu doküman, Claude Code'un her aşamada başvuracağı **tek mimari kaynak**tır.
Mevcut kodla çelişen bir yer varsa önce bu dokümana bakılır; doküman yanlışsa
doküman düzeltilir, kod "sessizce" farklı yöne gitmez.

---

## 1. Amaç

Tek çekirdek, üç yüz, dört kademe:

| Boyut | Hedef |
|---|---|
| **Tek çekirdek** | `asistan/cekirdek/` arayüz bilmez. Masaüstü, web (telefon) ve komut satırı aynı çekirdeği çağırır. |
| **Üç yüz** | `masaustu` (PySide6), `web` (FastAPI + PWA — sunucu/telefon), `komut` (`cafer` CLI). |
| **Dört kademe** | `dusuk` · `orta` · `yuksek` · `sunucu`. Program açılışta donanımı ölçer, kendini kademeye göre ayarlar. |
| **Anla → Planla → Uygula → Doğrula** | Her istek adımlara bölünür; her adım doğrulanır; kaldığı yerden devam edebilir. |
| **Kendini genişletme** | Yapamadığı işi analiz eder: daha güçlü model, eksik bağımlılık, eksik yetenek → onaylı kurulum ya da yeni yetenek üretimi. |

---

## 2. Dizin Yapısı (hedef)

```
asistan/
  cekirdek/                 # UI bilmez, saf Python; PySide6 import'u YASAK
    ayar.py                 # tek ayar kaynağı: ayar.toml + ortam değişkenleri
    profil.py               # donanım ölçümü → kademe (dusuk/orta/yuksek/sunucu)
    yonlendirici.py         # görev → sağlayıcı/model seçimi + yedekleme zinciri
    guvenlik.py             # politika: kurulum izni, sandbox, zaman aşımı, onay
    saglayici/              # model sağlayıcılar, hepsi aynı arayüzü uygular
      temel.py              # Saglayici sınıfı: sohbet(), akis(), saglik(), maliyet()
      ollama.py
      claude.py
      openai_uyumlu.py      # OpenAI/OpenRouter/Groq/… tek dosya, farklı base_url
      cli_ajan.py           # claude -p, codex, gemini → alt süreç
    gorev/                  # görev motoru
      anlayici.py           # istek → niyet, kısıtlar, gereken yetenekler
      planlayici.py         # → şema kısıtlı JSON plan (docs/SEMALAR.md)
      yurutucu.py           # adım adım çalıştırma, checkpoint, devam
      dogrulayici.py        # adım başarı ölçütü kontrolü
      durum.py              # görev deposu (SQLite): .cafer/gorevler.db
    yetenek/                # yetenek kayıt defteri
      kayit.py              # manifest tarama, listeleme, şema doğrulama
      calistirici.py        # yeteneği sandbox'ta çalıştırma
      yukleyici.py          # eksik pip/ikili kurma (guvenlik.py onayıyla)
      uretici.py            # yeni yetenek iskeleti üretme (kod ajanı ile) + test
    analiz/
      hata.py               # hata sınıflandırma → eylem
      olcum.py              # hız/başarı ölçümü; kademe otomatik ayarı
  arayuz/
    masaustu/               # PySide6 (mevcut UI buraya taşınır)
    web/                    # FastAPI + PWA (telefon)
    komut/                  # `cafer` CLI: cafer profil | cafer gorev "…" | cafer sunucu
  yetenekler/               # yerleşik yetenekler (K5): her biri manifest.json + calistir.py + test_<ad>.py
                            # (asistan/ içinde: güncelleme paketi yalnızca asistan/ taşır; üretilenler DATA_DIR/yetenekler)
sunucu/                     # Dockerfile, docker-compose.yml, Caddyfile, .env.ornek
testler/
docs/
NOTLAR/
```

**Kural:** `asistan/cekirdek/` içinde `PySide6`, `Qt`, `fastapi` import'u olamaz.
`/kontrol` komutu bunu grep ile denetler.

---

## 3. Kademeler

Açılışta `profil.py` ölçer: CPU çekirdek, RAM, GPU/VRAM (nvidia-smi → torch → Vulkan/Metal sırayla dener), disk, işletim sistemi, ağ var mı, Ollama çalışıyor mu. Sonuç `.cafer/profil.json`'a yazılır; kullanıcı elle kademeyi kilitleyebilir.

| Kademe | Tipik donanım | Yerel model | Varsayılan davranış |
|---|---|---|---|
| `dusuk` | ≤ 8 GB RAM, GPU yok | ≤ 3B parametreli, isteğe bağlı | Bulut API varsa bulut; yoksa küçük model + görevleri küçük parçalara bölme. Embedding, tarayıcı otomasyonu, uzun bağlam kapalı. |
| `orta` | 16 GB RAM, GPU yok ya da ≤ 6 GB VRAM | 7–8B | Basit işler yerel, karmaşık işler (kod üretimi, çok adımlı plan) bulut. |
| `yuksek` | ≥ 32 GB RAM, ≥ 8 GB VRAM | 14–32B | Yerel varsayılan; bulut isteğe bağlı ve gizlilik ayarına göre. |
| `sunucu` | Başsız (headless), GPU yok/var | GPU varsa Ollama | GPU yoksa tüm çıkarım bulut API; web arayüzü ve görev deposu sunucuda. |

Model adları **kodda sabit değil**, `ayar/modeller.json`'da kademe başına liste halinde tutulur. "10 önerilen model" listesi yenilendikçe bu dosya güncellenir; kod dokunulmaz.

Örnek `modeller.json` yapısı (adlar örnektir, güncel listeyle değiştirilir):

```json
{
  "guncelleme": "2026-09-27",
  "kademe": {
    "dusuk":  {"yerel": ["<kucuk-3b-model>"],          "bulut": ["<ucuz-hizli-bulut>"]},
    "orta":   {"yerel": ["<7b-model>", "<8b-model>"],   "bulut": ["<dengeli-bulut>"]},
    "yuksek": {"yerel": ["<14b-model>", "<32b-model>"], "bulut": ["<guclu-bulut>"]},
    "sunucu": {"yerel": [],                              "bulut": ["<guclu-bulut>", "<ucuz-hizli-bulut>"]}
  },
  "roller": {
    "yonetici": "en güçlü erişilebilir",
    "hizli":    "en ucuz/hızlı erişilebilir",
    "kod":      "cli_ajan > bulut > yerel"
  }
}
```

---

## 4. Model Yönlendirme (`yonlendirici.py`)

Her adım için sağlayıcı+model seçimi şu sırayla karar verilir:

1. **Çevrimdışı mı?** → sadece yerel. Yerel yoksa: görevi "bekleyen" olarak kaydet, kullanıcıya söyle.
2. **Gizlilik ayarı `yerel`** → bulut hiç kullanılmaz.
3. **Görev türü:**
   - `sohbet` / `ozet` / `siniflandirma` → rol `hizli`
   - `planlama` / `analiz` / `cok_adimli` → rol `yonetici`
   - `kod_uretimi` / `yetenek_uretimi` → rol `kod` (CLI ajan varsa o)
4. **Kademe kısıtı:** `dusuk` kademede rol `yonetici` yerelde karşılanamıyorsa → bulut varsa bulut, yoksa görevi parçala ve `hizli` ile dene.
5. **Yedekleme zinciri:** zaman aşımı ya da 2 başarısız deneme → bir üst güç seviyesine yükselt (yerel küçük → yerel büyük → bulut). Zincirin sonunda hâlâ başarısızsa `analiz/hata.py`'ye devret.
6. **Sağlık:** her sağlayıcının `saglik()` sonucu 5 dk önbelleklenir; sağlıksız sağlayıcı zincirden düşer.
7. **Maliyet tavanı:** bulut için görev başına ve günlük token/₺ tavanı (`ayar.toml`); aşılınca kullanıcıya sor.

Yönlendirici kararını her adımda `gorev.adimlar[i].secim = {saglayici, model, neden}` olarak plana yazar — böylece "neden bu modeli seçti" hep görünür.

---

## 5. Görev Motoru (`gorev/`)

```
İstek
  │
  ▼
ANLA (anlayici.py)      → niyet, kısıtlar, belirsizlikler, gereken yetenekler
  │   belirsizlik yüksekse → tek soru sor, devam et
  ▼
PLANLA (planlayici.py)  → JSON plan (şema kısıtlı; docs/SEMALAR.md)
  │   her adım: amaç, yetenek, girdi, başarı ölçütü, bağımlılık, deneme hakkı
  ▼
UYGULA (yurutucu.py)    → adımı yönlendirici seçimiyle çalıştır
  │   her adım sonrası checkpoint (durum.py)
  ▼
DOĞRULA (dogrulayici.py) → başarı ölçütü sağlandı mı?
  │   evet → sonraki adım
  │   hayır → deneme hakkı varsa tekrar; yoksa ▼
  ▼
HATA ANALİZİ (analiz/hata.py) → sınıf + eylem (bkz. §7)
  │
  ▼
RAPORLA → kısa özet + ne yapıldı + ne yapılamadı + öneri
```

**Devam etme:** Program kapanıp açılsa da `.cafer/gorevler.db`'den yarım görevler listelenir; kullanıcı "devam et" der, `checkpoint.son_adim + 1`'den sürer.

**Onay noktaları:** dosya silme, ödeme/hesap işlemi, paket kurma, ağ üzerinden veri gönderme → `guvenlik.py` politikasına göre ya otomatik ya da kullanıcı onayı ister. Sunucu modunda onay web arayüzünden/telefondan verilir.

---

## 6. Yetenek Kayıt Defteri (`yetenek/`)

Planlayıcı **yalnızca kayıtlı yetenekleri** çağırabilir. Mevcut araçlar (dosya okuma/yazma, komut çalıştırma, Python çalıştırma, web araştırma, tarayıcı) birer yeteneğe dönüştürülür; böylece hepsi aynı kapıdan geçer ve aynı güvenlik politikasına tabi olur.

Her yetenek: `<kök>/<ad>/manifest.json` + `calistir.py` + `test_<ad>.py`; kökler `asistan/yetenekler/` (yerleşik) ve
`DATA_DIR/yetenekler/` (üretilen, katalog). Manifest şeması `docs/SEMALAR.md`'de.

Yerleşik yetenekler programın araçlarını `baglam.arac` ile çağırır: tek araç yolu (`Agent._execute_tool` →
`permissions.py`) değişmez. Sandbox yetenekleri izin hattına `y_<ad>` adıyla, manifestin izinlerinden çıkan risk
sınıfıyla girer (programla gelmeyen ya da güvenilmeyen: her seferinde onay).

Kayıt defteri açılışta tarar; manifesti bozuk ya da gereksinimi karşılanmayan yetenekler "pasif" listelenir (planlayıcıya "var ama kurulmamış" olarak görünür — böylece planlayıcı "bu iş için X yeteneği kurulursa yapılabilir" diyebilir).

Yetenek kaynakları:
- `yerlesik` — repoyla gelir
- `katalog` — GitHub'daki ayrı bir `cafer-yetenekler` deposundan indirilir (imzalı/allowlist)
- `uretildi` — kod ajanı üretti, sandbox testinden geçti, kullanıcı onayladı

---

## 7. Hata Analizi ve Kendini Genişletme (`analiz/hata.py`)

Her başarısız adım şu sınıflardan birine sokulur ve eylem tetiklenir:

| Sınıf | Belirti | Eylem |
|---|---|---|
| `model_yetersiz` | boş/anlamsız çıktı, şemaya uymayan plan, halüsinasyon | yönlendirici → bir üst model; hâlâ olmuyorsa görevi parçala |
| `eksik_bagimlilik` | `ModuleNotFoundError`, `command not found`, `.dll/.so` yok | `yukleyici.py`: pip/winget/apt/brew ile kur (politika onayı) → adımı tekrar |
| `eksik_yetenek` | planlayıcı "bunu yapacak yeteneğim yok" dedi | 1) katalogda ara 2) yoksa `uretici.py` ile iskelet üret → sandbox test → onay → kaydet → adımı tekrar |
| `izin` | dosya/ağ/işletim sistemi izni reddi | kullanıcıya net soru; sunucu modunda bildirim |
| `ag` | zaman aşımı, DNS, 5xx | 3 deneme üstel bekleme; sonra çevrimdışı moda düş |
| `mantik` | çıktı var ama ölçüt sağlanmıyor | başarısız çıktıyı bağlama ekleyip yeniden planla (en fazla 2 kez) |
| `veri` | girdi bozuk/eksik | kullanıcıya hangi verinin eksik olduğunu söyle |
| `kaynak` | RAM/VRAM/disk yetersiz | daha küçük model; bağlamı kısalt; kademeyi düşür |

**Yetenek üretme döngüsü (`uretici.py`):**
1. Eksik yeteneğin manifestini planlayıcıya yazdır (ne yapacak, girdi/çıktı, gereksinim).
2. Kod ajanı (`cli_ajan` → yoksa bulut → yoksa yerel `kod` rolü) `calistir.py` ve `test_*.py` üretir.
3. Sandbox'ta (ayrı venv, zaman aşımı, ağ izni manifeste göre) test çalışır.
4. Geçtiyse kullanıcıya diff + manifest gösterilir; onayla kayıt defterine girer.
5. Geçmediyse hata metniyle 2 tur daha dener; yine olmazsa "yapamadım, şu nedenle" raporu.

Her üretilen yetenek `kaynak: "uretildi"` ile işaretlenir ve `/kontrol` listesinde ayrı görünür.

---

## 8. Ölçüm (`analiz/olcum.py`)

- Her yerel model için ilk kullanımda 30 sn'lik kısa benchmark: token/sn, ilk-token gecikmesi, bellek. Sonuç `profil.json`'a yazılır.
- Sağlayıcı/model başına başarı oranı (doğrulayıcıdan) ve ortalama süre tutulur.
- Kademe otomatik ayarı: `orta` kademede 7B model 3 tok/sn altına düşüyorsa bir alt kademenin varsayılanlarına geç; kullanıcıya "kademe düşürüldü, nedeni" bildir.
- Sınav seti (`testler/sinav/`) kademe bazlı koşulur: hangi kademede hangi görev tipinin başarı oranı düşük → yönlendirme tablosuna geri beslenir.

---

## 9. Sunucu / Bulut Modu

**Aynı paket, farklı giriş noktası:** `cafer sunucu` → FastAPI + PWA. Masaüstü kodu yüklenmez.

```
sunucu/
  Dockerfile              # python:3.12-slim, sadece cekirdek + web
  docker-compose.yml      # cafer-web (+ isteğe bağlı ollama servisi, GPU profili)
  Caddyfile               # otomatik HTTPS
  .env.ornek              # CAFER_TOKEN, API anahtarları, CAFER_KADEME=sunucu
```

- **Kimlik:** tek kullanıcı, uzun rastgele `CAFER_TOKEN`; PWA ilk açılışta ister, saklar.
- **Telefon:** PWA "ana ekrana ekle" ile uygulama gibi çalışır; bilgisayar kapalıyken görevler sunucuda sürer.
- **Onaylar:** bekleyen onaylar web arayüzünde liste; isteğe bağlı bildirim (ntfy/Telegram bot — yetenek olarak).
- **Maliyet:** GPU'suz 2 vCPU / 4 GB VPS yeterli (çıkarım bulut API'de). Yerel model istenirse GPU'lu sunucu ya da masaüstü bilgisayarın Ollama'sına tünel (isteğe bağlı, ileri aşama).
- **Senkron:** görev deposu ve ayarlar sunucuda; masaüstü istemci sunucuya bağlanabilir ("uzak mod") ya da tamamen bağımsız çalışır.

---

## 10. Güvenlik İlkeleri (`guvenlik.py`)

- Politika dosyası `ayar/guvenlik.toml`: `kurulum = "sor" | "otomatik" | "yasak"`, `ag = "sor" | "serbest"`, `dosya_silme = "sor"`, `sandbox_zaman_asimi_sn = 60`.
- Kademe `dusuk`'te ve sunucuda `kurulum` varsayılanı `sor`.
- Üretilen yetenekler ilk 5 çalıştırmada her zaman sandbox'ta; sonra kullanıcı "güvenilir" işaretleyebilir.
- Kurulum kaynakları allowlist: PyPI, resmi paket yöneticileri, `cafer-yetenekler` kataloğu. Rastgele URL'den script indirme yasak.
- Tüm alt süreçler zaman aşımıyla; çıktı boyutu sınırlı; ortam değişkenlerinden API anahtarları alt sürece geçirilmez (manifest `izinler` içinde `anahtar:<ad>` yoksa).

---

## 11. Değişmez Kurallar (Claude Code için)

1. Çalışan davranışı bozmadan ilerle; refaktör = eski yol çalışırken yenisini yanına kur, sonra eskiyi kaldır.
2. Çekirdek arayüz bilmez.
3. Model adları koda gömülmez; `modeller.json`'dan okunur.
4. Her yeni modülün testi olur; `/kontrol` yeşil olmadan aşama bitmiş sayılmaz.
5. Kurulum, silme, ağ üzerinden gönderme → `guvenlik.py`'den geçer.
6. Türkçe adlandırma (mevcut proje diliyle uyumlu), İngilizce sadece kütüphane API'lerinde.
7. Ağır bağımlılık (torch, transformers, tarayıcı motoru vb.) çekirdeğe girmez; yetenek gereksinimi olarak isteğe bağlı kalır.
