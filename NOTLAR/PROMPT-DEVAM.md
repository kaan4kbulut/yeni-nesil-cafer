# DEVAM — temizlik oturumunun kalanı

CLAUDE.md'yi oku. k-serisi dalında çalış. Soru sorma; karar gerekirse NOTLAR/SORULAR.md'ye geçici karar yaz. Yeni özellik ekleme.

Önce `.cafer/ilerleme.json`, `git status`, `git log --oneline -8` ve varsa `git stash list` (limit stash'i varsa `git stash pop`) ile
"TEMIZLIK+v3.1" oturumunun nerede kaldığına bak. Bölümler:

1. Depo temizliği: NOTLAR/arsiv/ taşımaları, .cafer geçici betikleri silindi, .gitignore, paketleme/ → dagitim/ birleştirmesi.
2. Yazdı-ama-yapmadı: (a) ikinci başarısızlıkta motora devir / sonraki model / dürüst mesaj, (b) meta sorular eylem değil,
   (c) dil bekçisi, (d) dürtü metni gizli, (e) `kullaniciya_sor` aracı, (f) sınav varyantı, (g) "Sorun raporla" düğmesi; testler/test_yapmadi.py.
3. 21 atlanan test: kütüphaneler .venv'de, requirements.txt, paket kararı, CI uyarısı; hedef atlanan 0.
4. Release sadeleştirme: adlar (Light yok), tek güncelleme zip'i "guncelleyici-icin-" önekli, -internet/BENIOKU/NOTLAR asset'leri yok,
   dagitim/RELEASE_NOTU.md şablonu, paketle.py + dagitim.yml adları, `--eski-sil`, v3.0-beta.1 Latest ve düzenlenmiş, v2.7/v2.6 silindi,
   AppImage --install, Flatpak → SONRAYA.
5. Bitiş: tam takım, arayuz_denetimi 0 hata, /kontrol, dagitim/aktar.sh, NOTLAR/2026-09-28-TEMIZLIK.md, YAPILACAKLAR'a K13 satırı, push.

Bitmemiş olanları bitir; her bölüm ayrı commit. Hepsi bitmişse hiçbir şey değiştirme.
Son satır: `SONUÇ: TAM|KISMEN · TEST: N✓/M✗/K atlandı`
