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

1. [Sürümler](../../releases/latest) sayfasındaki **"Hangisini indireyim?"** tablosundan işletim sistemine uygun tek dosyayı indir
   (Windows `…-Windows-Kurulum.exe`, macOS `…-macOS.dmg`, Linux `…-Linux.AppImage`).
2. Çift tıkla (Windows "bilgisayarınızı korudu" derse **Ek bilgi → Yine de çalıştır**; macOS'ta ilk açılış sağ tık → Aç; Linux'ta
   `chmod +x` sonra çalıştır, menüye eklemek için `--install`).
3. İlk açılışta kurulum sihirbazı bilgisayarını tarar; Ollama'yı ve sana uygun modelleri kendisi indirir. Senden komut istemez.

![Sohbet penceresi](docs/ekran-goruntusu.png)
<!-- ekran görüntüsü yeri: docs/ekran-goruntusu.png (sohbet + sağ panel), 1280×800 -->

Gerekenler: kurulum sırasında internet (~2,5 GB + modeller 3–10 GB), en az 8 GB RAM (önerilen 16 GB ve 8 GB+ ekran kartı ya da
16 GB+ Apple Silicon Mac), ~15 GB boş alan. Kurulum yarıda kesilirse programı yeniden aç: inenler korunur, kaldığı yerden sürer.

**Geliştiriciler (pipx):**
```sh
pipx install "git+https://github.com/kaan4kbulut/yeni-nesil-cafer.git[sunucu]"
cafer profil               # donanım profili ve kademe
cafer sunucu --port 8765   # web + telefon (PWA); masaüstü için main.py (PySide6)
```
Sunucu/telefon kullanımı için `docs/SUNUCU_KURULUM.md`.

## Güncelleme

Kurduktan sonra büyük paketi bir daha indirmen gerekmez. Yeni sürüm çıkınca program haber verir:
**Yardım → Güncelleme var → Güncelle** (yalnızca birkaç MB indirir). Kurmadan önce şimdiki sürüm yedeklenir;
yeni sürüm açılamazsa kendiliğinden eski sürüme dönülür.

## Sorun bildir

Bir şey ters giderse mesaj kutusunun yanındaki **🐞 sorun** düğmesine bas: program ne olduğunu, sohbetin ilgili kısmını,
hataları ve sistem bilgisini tek dosyada masaüstündeki `YENİ NESİL CAFER` klasörüne yazar (API anahtarları gizlenir) ve
geliştiriciye verilecek cümleyi panoya kopyalar. Bu dosyayı bir [Issue](../../issues/new) olarak ekle ya da doğrudan gönder.
Yardım → **Sorun bildir…** aynı raporu önizlemeli hazırlar.

## Geliştirme

Python 3.12 + PySide6. Mimari, kurallar ve bilinen tuzaklar [`CLAUDE.md`](CLAUDE.md)'de.

```sh
python -m venv .venv && .venv/bin/pip install -r requirements.txt
./calistir.sh                                              # geliştirme kopyasını çalıştır
QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest testler -q             # testler
git tag vX.Y && git push origin vX.Y                       # yeni sürüm: CI üç platformda derler ve yayımlar
```

Program kendi kodunu değiştirmez; sorunları algılayıp rapor hazırlar, düzeltmeyi geliştirici yapar.
