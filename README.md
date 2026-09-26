# YENİ NESİL CAFER

Bilgisayarında çalışan kişisel yapay zekâ asistanı ve ekibi. Sohbet eder, dosyalarınla çalışır, web'de araştırır,
işleri uzman ajanlara dağıtır. Yerel modellerle ([Ollama](https://ollama.com)) **ücretsiz ve çevrimdışı** çalışır;
istersen Claude, GPT, Gemini gibi bulut modellerine de bağlanır. Arayüz ve konuşma Türkçedir.

## Neler yapar

- **İşleri kendi başına çözer:** bilmediği bir işi araştırır, gereken kütüphaneyi ya da uygulamayı kurar (onayınla),
  yapar, sonucu gözle kontrol eder ve bulduğu yolu "beceri" olarak kaydeder. Sonucu belirleyen bir bilgi eksikse sorar.
- **Hazır beceriler:** 3D baskı (ölçülü STL/3MF/STEP ve baskıya uygunluk denetimi), veri analizi (Excel/CSV, grafik),
  Word/PowerPoint/PDF rapor, ses (konuşmayı yazıya çevirme, Türkçe seslendirme), video (animasyon, slayt, ses ekleme).
- **Sağ panel üç bölüm:** adımlar, dosyalar ve canlı görüntü hep görünür; resim üretimini adım adım canlı izleme; resim, video ve 3D model önizleme.
- **Konuşarak yazma:** mesaj kutusundaki 🎤; tamamen bilgisayarında.
- **Model seçmek zorunda değilsin:** program modelleri kendi sınavından geçirir, işe göre seçer, zorlanınca daha
  güçlüsüne devreder.
- **Güvenlik ajanı:** zararsız adımlar hemen yapılır, riskliler incelenir, zararlılar (ör. `rm -rf ~`) her durumda
  reddedilir. Kapatırsan her adım sana sorulur.
- **Sorun raporu:** bir şey ters giderse "🐞 Sorunu raporla" ile geliştiriciye verilecek raporu hazırlar
  (API anahtarları gizlenir).

## Kurulum

[Sürümler (Releases)](../../releases/latest) sayfasından sistemine uygun dosyaları indir. Paketler kendi kendine
yeter: Python, gerekli kütüphaneler, Ollama, temel yapay zekâ modeli ve ses tanıma modeli içindedir; kurulum
internetsiz çalışır. Paket ~8 GB olduğu için 2 GB'lık parçalara bölünmüştür:

**Windows 10/11**
1. `YENI-NESIL-CAFER.v…-Windows.zip.001`, `.002`, … parçalarının **hepsini** ve `birlestir.bat`'ı aynı klasöre indir.
2. `birlestir.bat`'a çift tıkla → tek bir `.zip` oluşur.
3. Zip'e sağ tık → "Tümünü ayıkla…" → çıkan klasörde `Kur.bat`.

**Linux (64 bit)**
```sh
./birlestir.sh                                   # parçalarla aynı klasörde
tar xzf YENI-NESIL-CAFER.v*-Linux.tar.gz && ./YENI-NESIL-CAFER.v*/kur.sh
```

Gerekenler: en az 8 GB RAM (önerilen 16 GB ve 8 GB+ ekran kartı), kurulum için ~10 GB boş alan.

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
