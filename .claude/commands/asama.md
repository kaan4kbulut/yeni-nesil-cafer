---
description: YAPILACAKLAR.md'deki bir aşamayı baştan sona uygular (plan → kod → test → not)
argument-hint: [aşama kodu, örn. K2] [isteğe bağlı: "onaysız" — plan onayı beklemeden devam et]
---

Aşama: $ARGUMENTS

Sıra şu, atlama yok:

1. **Aşamayı bul.** `YAPILACAKLAR.md`'yi oku. "$ARGUMENTS" ile başlayan aşamayı bul. Kod verilmemişse ilk tamamlanmamış aşamayı seç ve seçtiğini bana söyle. Aşamanın "Bitti sayılır" maddelerini kendi kontrol listen olarak al.

2. **Bağlamı yükle.** `docs/MIMARI.md` ve `docs/SEMALAR.md`'de bu aşamayla ilgili bölümleri oku. `NOTLAR/arsiv/MEVCUT_DURUM.md` varsa oku (K0'da üretilir). Mevcut kodda etkilenecek dosyaları Grep/Glob ile bul; tahmin etme, bak.

2b. **Görev listesini kur.** Aşamanın her maddesi için `TaskCreate` ile bir görev aç; ilk görevin başlığı aşama koduyla başlasın (ör. `K3: yonlendirici.py iskeleti`). Son görev her zaman `K<n>: /kontrol + NOTLAR` olsun. Bir maddeye başlarken onu `in_progress`, bitirince `completed` yap — **atlamadan, sırayla**. Bu liste terminaldeki ilerleme çubuğunu besler; güncellemezsen kullanıcı nerede olduğunu göremez. Çalışırken bir madde daha ortaya çıkarsa `TaskCreate` ile ekle (çubuk kendini ayarlar).

3. **Kısa plan yaz.** Şu başlıklarla, en fazla 25 satır:
   - Değişecek / eklenecek dosyalar
   - Korunacak mevcut davranış (kırılmaması gerekenler)
   - Riskler ve geri dönüş yolu
   - Test stratejisi
   
   Plan **geri alınması zor** bir iş içeriyorsa (dosya/klasör taşıma, veri şeması değişikliği, mevcut ayar dosyasının biçimini değiştirme) burada dur ve onayımı bekle. Argümanda "onaysız" varsa ya da plan sadece ekleme/yeni modül ise durmadan devam et.

4. **Uygula.** Kurallar:
   - Çalışan davranışı bozma. Refaktör = yenisini yanına kur, eskiyi çalışır tut, sonra taşı.
   - `asistan/cekirdek/` içine PySide6/Qt/fastapi import'u koyma.
   - Model adı kodda sabitleme; `modeller.json`'dan oku.
   - Her yeni modül için `testler/` altına en az bir test.
   - Yeni bağımlılık eklemen gerekirse önce nedenini söyle; ağır bağımlılık (torch, transformers, tarayıcı motoru) çekirdeğe giremez.
   - Türkçe adlandırma; docstring'ler Türkçe ve kısa.

5. **Doğrula.** `/kontrol` komutunun yaptığı kontrolleri çalıştır (test, import dumanı, çekirdek-arayüz ayrımı, manifest doğrulama). Kırmızı varsa düzelt; düzeltemiyorsan neden düzeltemediğini yaz, aşamayı "tamamlandı" işaretleme.

6. **Kaydet.**
   - `YAPILACAKLAR.md`'de biten maddeleri `[x]` yap; yarım kalanları `[ ]` bırak ve yanına kısa not düş.
   - `NOTLAR/` altına `YYYY-AA-GG-<aşama-kodu>.md` yaz: ne yapıldı, ne kaldı, karşılaşılan sorunlar, sonraki aşamaya öneri. Dosya varsa üstüne ekle.

7. **Bana rapor ver.** Değişen dosya listesi, test sonucu (kaç geçti/kaç kaldı), açık sorular, önerdiğin commit mesajı. Ben "commitle" demeden commit atma.
