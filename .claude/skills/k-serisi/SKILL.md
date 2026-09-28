---
name: k-serisi
description: K serisi aşamalarını (K0–K12, /asama K<n>) uygularken, otomatik.py sürücüsüyle ya da "OTOMATİK MOD" önsözlü bir istemle çalışırken yükle — aşama akışı, görev listesi, NOTLAR/SORULAR düzeni, SONUÇ satırı biçimi ve açık işler burada.
---

# K serisi — çalışma düzeni

**Bir oturum = bir aşama.** `/asama K<n>` ile başla (plan → kod → test → not). Aşamanın maddeleri ve "Bitti sayılır"
ölçütü `YAPILACAKLAR.md`'de (`## Aşama K<n>` bölümü, `###` alt başlıkları ayrı oturum olabilir). Oturuma
`YAPILACAKLAR.md`'nin yalnızca ilgili bölümünü okuyarak başla; dosyanın tamamını yükleme.

## Sıra

1. Aşamayı bul, "Bitti sayılır" maddelerini kendi kontrol listen yap. İlgili `docs/MIMARI.md` / `docs/SEMALAR.md`
   bölümlerini oku (tamamını değil). Etkilenecek dosyaları Grep/Glob ile bul; tahmin etme.
2. Görev listesi zorunlu (`TaskCreate`/`TaskUpdate`; ilk görevin başlığı aşama koduyla başlar, son görev
   `K<n>: /kontrol + NOTLAR`). Bu liste `.cafer/ilerleme.json` üzerinden terminaldeki ilerleme çubuğunu besler.
3. Kısa plan (≤ 25 satır): değişecek dosyalar, korunacak davranış, riskler/geri dönüş, test stratejisi. Geri alınması
   zor iş (taşıma, şema/ayar biçimi değişikliği) varsa onay bekle; "onaysız" argümanı ya da yalnızca ekleme ise sürdür.
   Büyük refaktörden önce `mimar` ajanı, bitince `denetci` ajanı.
4. Uygula: çalışan davranışı bozma (yenisini yanına kur, sonra taşı); çekirdeğe Qt/fastapi girmez; model adı kodda
   sabitlenmez; her yeni modül için `testler/` altına test; ağır bağımlılık çekirdeğe giremez; Türkçe adlandırma.
5. Doğrula: `denetci` becerisindeki `/kontrol` adımları. Kırmızıyı düzelt; düzeltemiyorsan nedenini yaz, aşamayı
   "tamamlandı" işaretleme. Hata görünce `/hata-analiz` (sınıflandırıcıya desen ekler).
6. Kaydet: `YAPILACAKLAR.md`'de biten maddeler `[x]`; `NOTLAR/<tarih>-K<n>.md` (ne yapıldı, ne kaldı, sorunlar, öneri).
   Başka sorun görürsen `NOTLAR/`'a yaz, geç; kapsam dışı fikir `YAPILACAKLAR.md → Sonraya` ya da `NOTLAR/SONRAYA.md`.
7. Rapor: değişen dosyalar, test sonucu, açık sorular, önerilen commit mesajı. Commit atma ("commitle" denince at).

## Otomatik mod (otomatik.py sürücüsü)

- Kimse onay veremez: en makul varsayımı seç, aşama notuna yaz, devam et. Kullanıcıya soru gerekiyorsa
  `NOTLAR/SORULAR.md`'ye `K<n> | soru | geçici karar` satırı ekle (dosyanın sonuna; tamamını okuma — sürücü son
  10 maddeyi isteme ekler). Elle yapılacak işler `NOTLAR/KONTROL_LISTEN.md`'ye `- [ ]` satırı olarak.
- Commit ATMA; sürücü atar. `git push`, `git reset --hard`, `rm -rf` yok.
- Son mesaj zorunlu biçimde: `SONUÇ: TAMAM | KISMEN | KALDI` · `DEĞİŞEN: <dosya sayısı>` · `TEST: <geçti/kaldı>` ·
  `NOT: <tek satır>`. SONUÇ satırı yoksa sürücü aşamayı bitmiş saymaz.
- Sürücü her alt başlığı ayrı `claude -p` oturumunda (20 dk) koşar; zaman aşımında SIGINT gönderir — o anda dosyaları
  tutarlı bırak. Kullanım limiti mesajı gelirse sürücü aşamayı bitmiş saymaz, sıfırlanma saatini bekler (`--bekle`).
- Denetçi turu ayrı bir haiku oturumudur; ana oturuma yalnızca `Sonuç:` satırı ve rapor dosyasının yolu geçer.

## Açık işler (kalıcı liste)

1. Adımları kategorisine göre uzman modele dağıtmak (K3); bulut maliyetinin ₺ karşılığı.
2. Görev motorunu sohbette varsayılan yapmak (sınav karşılaştırması `--motor` / `--motorsuz`, SORULAR B7).
3. Sunucuyu gerçek makinede kurmak (K8/K9 KONTROL_LISTEN); Full dağıtım paketi için küçük model (K11).
4. 3D baskı: dilimleme ve yazıcıya gönderme (Sonraya).
