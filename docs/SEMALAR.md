# Şemalar

Planlayıcı ve yetenek kayıt defteri bu şemalara **sıkı** uyar. Şemalar `asistan/cekirdek/semalar/` altında JSON Schema (Draft 2020-12) olarak da tutulur; burası okunabilir açıklamadır. Şema değişince ikisi birlikte değişir.

---

## 1. Yetenek Manifesti — `yetenekler/<ad>/manifest.json`

```json
{
  "ad": "web_arama",
  "surum": "1.0.0",
  "aciklama": "Web'de arama yapar; başlık, url ve özet listesi döner.",
  "etiketler": ["ag", "arastirma"],

  "girdi": {
    "sorgu": {"tip": "string", "zorunlu": true, "aciklama": "Arama ifadesi"},
    "adet":  {"tip": "int",    "zorunlu": false, "varsayilan": 5}
  },
  "cikti": {
    "sonuclar": {"tip": "list", "eleman": {"baslik": "string", "url": "string", "ozet": "string"}}
  },

  "gereksinimler": {
    "pip": ["httpx>=0.27"],
    "ikili": [],
    "min_kademe": "dusuk",
    "isletim": ["windows", "linux", "macos"],
    "python": ">=3.12"
  },

  "izinler": ["ag"],
  "zaman_asimi_sn": 30,
  "sandbox": true,
  "kaynak": "yerlesik",
  "guvenilir": true,

  "ornekler": [
    {"girdi": {"sorgu": "PySide6 QListView örnek"}, "beklenen": "en az 1 sonuç, her sonucun url'si http ile başlar"}
  ]
}
```

Alanlar:

| Alan | Açıklama |
|---|---|
| `ad` | Klasör adıyla aynı; `[a-z0-9_]+` |
| `izinler` | `ag`, `dosya_oku`, `dosya_yaz`, `dosya_sil`, `komut`, `anahtar:<AYAR_ADI>` (bir API anahtarını alt sürece geçirme izni) |
| `sandbox` | `true` ise ayrı venv + zaman aşımı + izin dışı erişim engeli |
| `kaynak` | `yerlesik` · `katalog` · `uretildi` |
| `guvenilir` | `uretildi` yetenekler `false` başlar; kullanıcı yükseltir |
| `ornekler` | `/kontrol` bunları duman testi olarak koşar |

**İzinler → izin hattı eşlemesi (K5/BÖLÜM 3a).** Manifestteki `izinler` kümesi `kayit.Yetenek.risk()` ile tek bir risk
sınıfına iner; sandbox yeteneği izin hattına `y_<ad>` adıyla bu sınıfla girer, yerleşik (sarmalayıcı) yetenek ise
sardığı aracın kendi sınıfıyla. Onay kuralı yalnızca `permissions.decide`'da:

| `izinler` | risk sınıfı | izin hattı (`permissions.decide`) |
|---|---|---|
| yalnızca `dosya_oku` (ya da boş) | `okur` | izin; ✓ beklemez, sorulmaz |
| `dosya_yaz` (+ okuma) | `yazar` | değişiklik: ✓ turunda bekler (`gate_actions`), ▶ turunda ve izin bağlamı olmayan yolda (komut satırı, Görevler penceresi: `must_act`) sorulur, güvenlik ajanı kipinde ajan denetler |
| `komut`, `dosya_sil`, `ag`, `anahtar:<AD>` | `calistirir` | her seferinde sorulur / güvenlik ajanı denetler ("hep izin ver" ve otomatik onay listesi geçebilir; bulut tavanı geçemez) |
| `kaynak ≠ yerlesik` ya da `guvenilir: false` | `calistirir` | izinleri ne olursa olsun her seferinde sorulur |

`anahtar:<AD>` yalnızca o değişkeni alt sürece geçirir (`komut.guvenli_ortam` beyaz listesi); `CAFER_*` ve
`ANTHROPIC_API_KEY` istense de geçmez.

`calistir.py` sözleşmesi:

```python
def calistir(girdi: dict, baglam: "Baglam") -> dict:
    """girdi manifestteki 'girdi'ye, dönen dict 'cikti'ya uyar.
    baglam: calisma_klasoru, kademe, gunluk (logger), ayar (salt okunur), okuma_kokleri,
            arac (yalnızca yerleşik, sandbox dışı: programın tek araç yolu → izin hattı).
    Hata durumunda YetenekHatasi(sinif=..., mesaj=...) fırlat."""
```

Yer (K5): yerleşikler `asistan/yetenekler/<ad>/` (programla ve güncelleme paketiyle gelir; paketler yalnızca `asistan/`
taşır), üretilen / katalogdan gelenler `DATA_DIR/yetenekler/<ad>/`. `sandbox: false` yalnızca yerleşik ve
`kaynak: "yerlesik"` olanda geçerlidir; programla gelmeyen bir yetenek "yerleşik" olamaz (pasif kalır).
Yerleşik yeteneğin isteğe bağlı işlevleri: `arac_cagrisi(girdi) -> (araç, girdi)` (izin hattı onayı önceden tahmin
eder), `hazir_mi() -> str` (boş değilse yetenek pasif, metin nedenidir). Klasörde `ornek_dosyalar/` varsa duman testi
(`python -m asistan yetenek --duman`) onu her örnekten önce geçici çalışma klasörüne kopyalar.

---

## 2. Görev Planı — `DATA_DIR/gorevler.db` içinde JSON (`.cafer/` yalnızca geliştirme klasörü)

```json
{
  "gorev_id": "2026-09-27T20-41-03_a1b2",
  "istek": "Masaüstündeki fotoğrafları tarihe göre klasörle, sonra özet rapor çıkar",
  "olusturma": "2026-09-27T20:41:03+03:00",
  "kademe": "orta",

  "anlayis": {
    "niyet": "dosya_duzenleme + rapor",
    "kisitlar": ["yalnızca Masaüstü klasörü", "orijinaller silinmeyecek"],
    "belirsizlikler": [],
    "gereken_yetenekler": ["dosya_listele", "dosya_tasi", "rapor_yaz"],
    "eksik_yetenekler": []
  },

  "adimlar": [
    {
      "id": 1,
      "amac": "Masaüstündeki görsel dosyaları listele",
      "yetenek": "dosya_listele",
      "girdi": {"klasor": "~/Desktop", "uzantilar": [".jpg", ".png", ".heic"]},
      "basari_olcutu": "liste boş değil ve her öğede 'yol' ile 'degistirme_tarihi' var",
      "bagimli": [],
      "deneme_hakki": 2,
      "onay_gerekli": false,
      "secim": {"saglayici": null, "model": null, "neden": "model gerekmiyor"},
      "durum": "tamamlandi",
      "sonuc_ozeti": "142 dosya bulundu",
      "sure_sn": 0.4
    },
    {
      "id": 2,
      "amac": "Dosyaları YYYY-AA klasörlerine taşı",
      "yetenek": "dosya_tasi",
      "girdi": {"plan": "{{adim_1.sonuc}}", "hedef_kok": "~/Desktop/Fotoğraflar"},
      "basari_olcutu": "taşınan sayısı == listelenen sayısı; hiçbir dosya silinmedi",
      "bagimli": [1],
      "deneme_hakki": 1,
      "onay_gerekli": true,
      "secim": {"saglayici": null, "model": null, "neden": "model gerekmiyor"},
      "durum": "bekliyor_onay"
    },
    {
      "id": 3,
      "amac": "Özet rapor yaz",
      "yetenek": "rapor_yaz",
      "girdi": {"veri": "{{adim_2.sonuc}}", "bicim": "markdown"},
      "basari_olcutu": "rapor 3 başlık içerir ve toplam sayı adım 1 ile tutarlı",
      "bagimli": [2],
      "deneme_hakki": 2,
      "onay_gerekli": false,
      "secim": {"saglayici": "ollama", "model": "<orta-7b>", "neden": "kısa metin üretimi, rol=hizli"},
      "durum": "planlandi"
    }
  ],

  "durum": "bekliyor_onay",
  "checkpoint": {"son_adim": 1, "zaman": "2026-09-27T20:41:05+03:00"},
  "hatalar": [],
  "rapor": null
}
```

Durum değerleri: `planlandi` · `calisiyor` · `bekliyor_onay` · `bekliyor_kullanici` · `tamamlandi` · `basarisiz` · `iptal`.

`{{adim_N.sonuc}}` yer tutucuları yürütücü tarafından çözülür.

---

## 3. Hata Kaydı — `gorev.hatalar[]`

```json
{
  "adim": 3,
  "zaman": "…",
  "sinif": "eksik_bagimlilik",
  "belirti": "ModuleNotFoundError: No module named 'markdown'",
  "kanit": "traceback son 5 satır",
  "eylem": {"tip": "kur", "hedef": "pip:markdown", "onay": "sor"},
  "sonuc": "kuruldu_ve_tekrar_denendi | kullaniciya_soruldu | vazgecildi"
}
```

Sınıflar (bkz. MIMARI §7): `model_yetersiz` · `eksik_bagimlilik` · `eksik_yetenek` · `izin` · `ag` · `mantik` · `veri` · `kaynak`.

---

## 4. Donanım Profili — `DATA_DIR/profil.json`

```json
{
  "olcum_zamani": "…",
  "isletim": "windows-11",
  "cpu": {"cekirdek": 8, "iplik": 16, "model": "…"},
  "ram_gb": 32,
  "gpu": {"var": true, "ad": "…", "vram_gb": 8, "arka_uc": "cuda"},
  "disk_bos_gb": 210,
  "ag": true,
  "ollama": {"calisiyor": true, "surum": "…", "modeller": ["…"]},
  "kademe": {"olculen": "yuksek", "kilitli": null, "etkin": "yuksek"},
  "benchmark": {"<model>": {"tok_sn": 41.2, "ilk_token_ms": 380, "olcum": "…"}}
}
```

`kademe.kilitli` doluysa kullanıcı elle seçmiştir; ölçüm onu ezmez.

---

## 5. Ayar — `ayar.toml`

```toml
[genel]
dil = "tr"
calisma_klasoru = "~/Cafer"
kademe_kilidi = ""          # boş = otomatik

[gizlilik]
mod = "karma"               # yerel | karma | bulut

[bulut]
gunluk_tavan_token = 200000
gorev_tavan_token  = 40000

[saglayici.ollama]
url = "http://localhost:11434"

[saglayici.claude]
anahtar_env = "ANTHROPIC_API_KEY"

[saglayici.openai_uyumlu]
url = ""
anahtar_env = "OPENAI_API_KEY"

[cli_ajan]
tercih = ["claude", "codex", "gemini"]   # sırayla; bulunan ilk kullanılır

[sunucu]
port = 8765
token_env = "CAFER_TOKEN"
```

Ortam değişkeni `CAFER_<BOLUM>_<ANAHTAR>` her değeri ezer (`CAFER_GENEL_KADEME_KILIDI=dusuk` gibi). Sunucu modunda ayar dosyası yerine tamamen env kullanılabilir.
