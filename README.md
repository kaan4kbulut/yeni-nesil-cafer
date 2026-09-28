# YENİ NESİL CAFER

Bilgisayarında çalışan kişisel yapay zekâ asistanı ve ekibi. Sohbet eder, dosyalarınla çalışır, web'de araştırır,
işleri uzman ajanlara dağıtır. Yerel modellerle ([Ollama](https://ollama.com)) **ücretsiz ve çevrimdışı** çalışır;
istersen Claude, GPT, Gemini gibi bulut modellerine de bağlanır. Arayüz ve konuşma Türkçedir.

## Neler yapar

- **İşleri kendi başına çözer:** bilmediği bir işi araştırır, gereken kütüphaneyi ya da uygulamayı kurar (onayınla),
  yapar, sonucu gözle kontrol eder ve bulduğu yolu "beceri" olarak kaydeder. Sonucu belirleyen bir bilgi eksikse sorar.
- **Hazır beceriler:** 3D baskı (ölçülü STL/3MF/STEP ve baskıya uygunluk denetimi), veri analizi (Excel/CSV, grafik),
  Word/PowerPoint/PDF rapor, ses (konuşmayı yazıya çevirme, Türkçe seslendirme), video (animasyon, slayt, ses ekleme).
- **Canlı önizleme:** görsel iş yapılırken sağ panelde açılır; resim üretimini adım adım canlı izleme; resim, video ve 3D model önizleme.
- **Konuşarak yazma:** mesaj kutusundaki 🎤; tamamen bilgisayarında.
- **Model seçmek zorunda değilsin:** program modelleri kendi sınavından geçirir, işe göre seçer, zorlanınca daha
  güçlüsüne devreder.
- **Güvenlik ajanı:** zararsız adımlar hemen yapılır, riskliler incelenir, zararlılar (ör. `rm -rf ~`) her durumda
  reddedilir. Kapatırsan her adım sana sorulur.
- **Sorun raporu:** bir şey ters giderse "🐞 Sorunu raporla" ile geliştiriciye verilecek raporu hazırlar
  (API anahtarları gizlenir).

## Kurulum

[Sürümler (Releases)](../../releases/latest) sayfasından sistemine uygun **tek dosyayı** indir (yaklaşık 1 MB).
Kurulum gereken her şeyi (Python, kütüphaneler, Ollama, tarayıcı; ~2,5 GB) resmi kaynaklarından **kendisi indirir**,
doğrular ve kurar; senden hiçbir şey kurmanı istemez. Yapay zekâ modellerini ilk açılıştaki kurulum sihirbazı
bilgisayarına uygun olanları seçip indirir.

**Windows 10 / 11**
1. `YENI-NESIL-CAFER.v…-Windows-internet.zip` dosyasını indir → sağ tık → **Tümünü ayıkla…**
2. Çıkan klasördeki **`Kur.bat`**'a çift tıkla. "Windows bilgisayarınızı korudu" çıkarsa: **Ek bilgi → Yine de
   çalıştır** (program imzasız olduğu için Windows bu uyarıyı gösterir; kurulum betiği açık metindir).
3. Kurulum internet hızına göre 5–15 dakika sürer; ilerlemeyi pencerede görürsün. Bitince program açılır.

**Linux (64 bit)**
```sh
tar xzf YENI-NESIL-CAFER.v*-Linux-internet.tar.gz
./YENI-NESIL-CAFER.v*/kur.sh
```

**macOS** (Apple Silicon M1 ve sonrası: macOS 14+; Intel Mac: macOS 12+)
1. `YENI-NESIL-CAFER.v…-macOS-internet.zip` dosyasını indir → çift tıkla (açılır).
2. Çıkan klasördeki **`Kur.command`**'a **sağ tık → Aç → Aç** (program imzasız olduğu için ilk seferde böyle açılır;
   "Apple doğrulayamadı" derse: Sistem Ayarları → Gizlilik ve Güvenlik → **Yine de Aç**).
3. Terminal penceresinde kurulum ilerler (5–15 dk); bitince program açılır. Uygulamalar klasöründe ve masaüstünde
   "YENİ NESİL CAFER" olarak durur. Intel Mac'lerde yerel modeller yalnızca işlemcide ve yavaş çalışır.

Kurulum yarıda kesilirse aynı dosyayı yeniden çalıştır: inenler korunur, kaldığı yerden sürer.

Gerekenler: kurulum sırasında internet (kurulum ~2,5 GB, modeller bilgisayarına göre 3–10 GB), en az 8 GB RAM
(önerilen 16 GB ve 8 GB+ ekran kartı ya da 16 GB+ Apple Silicon Mac), ~15 GB boş alan.

İnternetsiz kurulum için her şeyi içeren tam paket de var (~8 GB, GitHub sınırı yüzünden 2 GB'lık parçalar); isteyene
elden verilir.

**Tek komutla (geliştiriciler, pipx):**
```sh
pipx install "git+https://github.com/kaan4kbulut/yeni-nesil-cafer.git[sunucu]"
cafer profil            # donanım profili ve kademe
cafer sunucu --port 8765   # web + telefon (PWA); masaüstü için main.py (PySide6)
```
Masaüstü uygulaması paketli kurulumla gelir (yukarıda); sunucu/telefon kullanımı için `docs/SUNUCU_KURULUM.md`.

## Güncelleme

Kurduktan sonra büyük paketi bir daha indirmen gerekmez. Yeni sürüm çıkınca program haber verir:
**Yardım → Güncelleme var → Güncelle** (yalnızca birkaç MB indirir). Kurmadan önce şimdiki sürüm yedeklenir;
yeni sürüm açılamazsa kendiliğinden eski sürüme dönülür.

## Geliştirme

Python 3.12 + PySide6. Mimari, kurallar ve bilinen tuzaklar [`CLAUDE.md`](CLAUDE.md)'de.

```sh
python -m venv .venv && .venv/bin/pip install -r requirements.txt
./calistir.sh                                              # geliştirme kopyasını çalıştır
QT_QPA_PLATFORM=offscreen .venv/bin/python -m unittest discover -s testler   # testler
paketleme/yayinla.sh                                       # yeni sürümü GitHub'da yayımla
```

Program kendi kodunu değiştirmez; sorunları algılayıp rapor hazırlar, düzeltmeyi geliştirici yapar.
