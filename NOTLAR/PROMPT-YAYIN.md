# YAYIN — v3.1 (Latest)

CLAUDE.md'yi oku. k-serisi dalında çalış. Soru sorma; karar gerekirse NOTLAR/SORULAR.md'ye geçici karar yaz. Yeni özellik ekleme.

1. Ön kontrol: `git status` temiz (değilse commit); tam takım `.venv/bin/python -m pytest testler -q` 0 hata (atlanan varsa sayısını
   nota yaz, engel değil); `testler/arayuz_denetimi.py` 0 hata; `/kontrol`; `testler/sinav/calistir.py --hizli --motor` sonucu
   RAPOR.md'de en az önceki (5/15) kadar — düşükse nedenini bul, düzeltilebiliyorsa düzelt, değilse SORULAR'a yaz ve devam et.
2. Sürüm: pyproject ve asistan sürümü 3.1; CHANGELOG'a K12 + temizlik + K13 özeti kullanıcı diliyle (kod adı, madde numarası yok).
3. `k-serisi`'ni `main`'e `--no-ff` ile birleştir, main'i push; `v3.1` etiketini it → CI üç platform derler.
   `gh run watch` ile CI'yi bekle (zaman aşımı 40 dk); kırmızıysa nedeni düzelt, etiketi taşı (`git tag -f v3.1` + `push -f origin v3.1`
   yalnızca etiket için), yeniden bekle.
4. CI bitince: release notu dagitim/RELEASE_NOTU.md şablonundan ("Hangisini indireyim?" tablosu başta); Latest işaretli, pre-release
   değil; `--eski-sil` ile v3.0-beta.1 dahil eski release'ler ve etiketleri silinir. `gh release view v3.1` ile son asset listesini
   nota yaz: platform başına tek kurulum dosyası + güncelleyici dosyaları, başka bir şey yok.
5. Kurulu kopyaya aktar (dagitim/aktar.sh); `main.py --surum` 3.1 desin; güncelleme kontrolünün /releases/latest'ten "güncel"
   döndüğünü CLI'dan doğrula (arayüz açmadan).
6. README: kurulum bölümü üç satır (OS → dosya → nasıl açılır), "Sorun bildir" bölümü (program içi Raporla düğmesi → dosyayı
   Issues'a bırak), ekran görüntüsü yer tutucu.
7. NOTLAR/2026-09-28-YAYIN.md özet; k-serisi'ni main ile hizala; push.
Son satır: `SONUÇ: TAM|KISMEN · SÜRÜM: v3.1 · TEST: N✓/M✗/K atlandı`
