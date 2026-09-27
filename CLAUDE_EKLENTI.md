# CLAUDE.md'ye eklenecek bölüm

> Bu dosyanın içeriğini mevcut `CLAUDE.md`'nin sonuna yapıştır, sonra bu dosyayı sil. `CLAUDE.md` zaten parçalara bölünmüşse (`.claude/` altında ayrı dosyalar), aşağıdaki iki bölümü uygun parçalara dağıt.

---

## Mimari (v3 — kademeli + bulut)

Tek kaynak: `docs/MIMARI.md`. Şemalar: `docs/SEMALAR.md`. Aşama planı: `YAPILACAKLAR.md` (K serisi). Mevcut durum haritası: `NOTLAR/MEVCUT_DURUM.md`.

Değişmez kurallar (`docs/MIMARI.md` §11'in özeti):

1. **Çekirdek arayüz bilmez.** `asistan/cekirdek/` içinde `PySide6`, `Qt`, `fastapi` import'u olamaz. Masaüstü, web ve CLI çekirdeği çağırır.
2. **Model adı koda gömülmez.** `ayar/modeller.json`'dan, kademe ve role göre okunur.
3. **Kademe farkındalığı.** Ağır iş (`embedding`, tarayıcı, uzun bağlam, büyük model) `profil.kademe()`'ye bakar; `dusuk`'te kapalıdır.
4. **Planlayıcı yalnızca kayıtlı yetenekleri çağırır.** Her yetenek `yetenekler/<ad>/manifest.json` + `calistir.py` + test.
5. **Kurulum, silme, ağ üzerinden gönderme `guvenlik.py`'den geçer.** Onaysız kurulum yok. Üretilen yetenekler sandbox'ta.
6. **Her başarısız adım `analiz/hata.py`'den geçer.** Yeni bir hata deseni görürsen sınıflandırıcıya ekle.
7. **Her yeni modülün testi olur.** `/kontrol` yeşil değilse aşama bitmedi.
8. **Çalışan davranışı bozma.** Refaktör: yenisini yanına kur → eski çalışır kalsın → sonra taşı.
9. **Ağır bağımlılık çekirdeğe girmez.** Yetenek gereksinimi olarak isteğe bağlı kalır.
10. **Türkçe adlandırma**, İngilizce yalnızca kütüphane API'lerinde.

## Çalışma düzeni

- **Bir oturum = bir aşama.** Aşamaya `/asama K<n>` ile başla. Aşama bitmeden başka aşamaya dokunma; başka bir sorun görürsen `NOTLAR/`'a yaz, geç.
- **Görev listesi zorunlu.** 3 adımdan uzun her işte `TaskCreate`/`TaskUpdate` kullan; başladığın maddeyi `in_progress`, bitirdiğini `completed` yap. Terminaldeki ilerleme çubuğu (`.claude/ilerleme/`) bu listeden beslenir; güncellemezsen kullanıcı nerede olduğunu göremez.
- Büyük refaktörden önce `mimar` ajanıyla plan çıkar; bitince `denetci` ajanıyla denetle.
- Hata görünce `/hata-analiz`. Yeni yetenek gerekince `/yetenek-ekle`. Aşama sonunda `/kontrol`.
- Commit atma; commit mesajı öner. Kullanıcı "commitle" derse at.
- Bir şeyi tahmin etme; dosyayı aç, komutu çalıştır, sonucu göster.
- Kullanıcıya soru soracaksan tek soru sor, geri kalan kararları makul varsayımla ver ve varsayımını yaz.

## Komutlar

| Komut | Ne yapar |
|---|---|
| `/asama K3` | K3 aşamasını plan → kod → test → not sırasıyla uygular |
| `/kontrol` (`hizli`) | Test, import dumanı, çekirdek-arayüz ayrımı, model adı, manifest doğrulama |
| `/hata-analiz <log\|metin\|son>` | Hatayı sınıflandırır, kök nedeni kanıtlar, düzeltir, sınıflandırıcıya ekler |
| `/yetenek-ekle <ad> "<açıklama>"` | Manifest + kod + test ile yetenek iskeleti |
| `/profil` (`benchmark`) | Donanım profili, kademe, gerçekle karşılaştırma |
| `/sunucu` (`docker`) | Web modunu ayağa kaldırıp uçtan uca test eder |

## Ajanlar

- `mimar` — kod yazmaz; aşama öncesi etkilenecek dosyalar, riskler, sıra.
- `denetci` — kod değiştirmez; diff'i mimari kurallara ve testlere karşı denetler, GEÇTİ/ŞARTLI/KALDI verir.
