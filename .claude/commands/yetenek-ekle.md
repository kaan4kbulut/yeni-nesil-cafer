---
description: yetenekler/ altına manifest + calistir.py + test ile yeni yetenek iskeleti kurar ve kayıt defterine kaydeder
argument-hint: <yetenek_adi> "<ne yapar, girdi ne, çıktı ne>" [izinler: ag,dosya_oku,...]
---

İstek: $ARGUMENTS

1. **Adı doğrula.** `[a-z0-9_]+` olmalı; `yetenekler/<ad>/` zaten varsa dur ve söyle.

2. **Manifest yaz.** `docs/SEMALAR.md` §1 şemasına birebir uyan `yetenekler/<ad>/manifest.json`. Açıklamadan girdi/çıktı alanlarını türet; belirsizse en fazla **bir** soru sor. `izinler` sadece gerçekten gerekeni içersin (en az ayrıcalık). `gereksinimler.min_kademe`'yi işin ağırlığına göre seç; emin değilsen `dusuk`. `kaynak: "yerlesik"`, `guvenilir: true` (ben yazdırıyorum). En az 2 `ornekler` girişi.

3. **Kodu yaz.** `yetenekler/<ad>/calistir.py`:
   - `def calistir(girdi: dict, baglam) -> dict` sözleşmesi
   - Girdi doğrulaması en başta; eksikse `YetenekHatasi(sinif="veri", ...)`
   - Ağ/dosya hatalarını doğru sınıfla fırlat (`ag`, `izin`, `eksik_bagimlilik`)
   - Ağır import'lar fonksiyon içinde (lazy) — modül yüklenince bağımlılık patlamasın
   - Türkçe docstring, kısa

4. **Test yaz.** `yetenekler/<ad>/test_<ad>.py`: manifestteki `ornekler`i koşar + en az bir hata yolu testi (eksik girdi). Ağ gerektiren testleri `pytest.mark.ag` ile işaretle ki çevrimdışı atlanabilsin.

5. **Kaydet ve doğrula.**
   - `python -m pytest yetenekler/<ad>/ -q`
   - Kayıt defterinin yeteneği gördüğünü göster: `python -c "from asistan.cekirdek.yetenek.kayit import Kayit; print(Kayit().listele())"` (modül henüz yoksa bunu belirt, atla)
   - `/kontrol hizli`

6. **Planlayıcıya tanıt.** Planlayıcının yetenek listesini manifestlerden otomatik okuduğunu doğrula. Elle bir listeye ekleme gerekiyorsa bu bir mimari ihlaldir: ekle ama `NOTLAR/`'a "planlayıcı yetenekleri manifestten okumalı, elle liste var" diye uyarı düş.

7. **Rapor.** Dosyalar, test sonucu, manifest özeti (izinler, kademe), commit mesajı önerisi.
