---
description: Bir hatayı/logu sınıflandırır, kök nedeni kanıtlar, küçük ve geri alınabilir düzeltme uygular, hata desenini sınıflandırıcıya ekler
argument-hint: <log dosyası yolu | yapıştırılmış hata metni | "son" (son çalıştırmanın günlüğü)>
---

Girdi: $ARGUMENTS

"son" verildiyse `.cafer/gunluk/` altındaki en yeni günlük dosyasını al.

1. **Sınıflandır.** Hatayı `docs/MIMARI.md` §7'deki sınıflardan tam birine sok:
   `model_yetersiz` · `eksik_bagimlilik` · `eksik_yetenek` · `izin` · `ag` · `mantik` · `veri` · `kaynak` · (hiçbiri değilse `arayuz` ya da `gelistirme` — yani programın kendi kodundaki bug).
   Sınıfı ve neden o sınıf olduğunu tek cümleyle yaz.

2. **Kök nedeni kanıtla.** İlgili dosya ve satırı aç, göster. "Muhtemelen" ile bitirme; kanıt yoksa tek soru sor ve dur.

3. **Düzelt.** En küçük, geri alınabilir değişiklik. Semptomu değil nedeni düzelt. Düzeltmeyi kilitleyen bir test ekle (`testler/`), testi çalıştır, geçtiğini göster.

4. **Genelleştir.** Şunu sor ve cevapla: *Bu hata, program kullanıcıda çalışırken de olabilir mi?* Olabilirse:
   - `asistan/cekirdek/analiz/hata.py` içindeki sınıflandırıcıya bu hata desenini (regex/anahtar kelime) ve eylemini ekle.
   - Eylem "kur" ise `yukleyici.py`'nin bunu yapabildiğini kontrol et; yapamıyorsa ekle.
   - Bunların da testi olsun.

5. **Kaydet.** `NOTLAR/HATALAR.md`'ye tek satır ekle:
   `YYYY-AA-GG | <sınıf> | <belirti kısa> | <düzeltme kısa> | <sınıflandırıcıya eklendi mi>`

6. **Rapor.** Sınıf, kök neden, değişen dosyalar, test sonucu, commit mesajı önerisi. Commit atma.
