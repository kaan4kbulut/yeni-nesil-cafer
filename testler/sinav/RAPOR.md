# Sınav raporu

`testler/sinav/calistir.py` üretir, elle düzenleme. Görevler `testler/sinav/gorevler/`, ayrıntılı kayıtlar `testler/sinav/sonuclar/` (git'te değil). Her yapılandırmanın (model · yönetici · kapsam) yalnızca son koşusu gösterilir; tekrarlı koşuda hücre "geçen/tekrar · ortalama süre".

## Özet

| Model | Yönetici | Kapsam | Tarih | Sürüm | Geçen | % | Süre |
|---|---|---|---|---|---|---|---|
| otomatik | otomatik | hizli | 2026-09-28 01:53 | 2.7 44704d8 | 1/1 | 100 | 0.3 dk |
| otomatik | sohbet modeli | hizli ×2 | 2026-09-27 23:35 | 2.7 5f839a1 | 9/24 | 38 | 13.4 dk |
| otomatik | sohbet modeli | hepsi | 2026-09-27 21:35 | 2.7 4bdb481 | 9/20 | 45 | 21.1 dk |

## Görevler

| Görev | otomatik · otomatik · hizli | otomatik · sohbet modeli · hizli | otomatik · sohbet modeli · hepsi |
|---|---|---|---|
| 1. yaz-kaydet · dusuk/cok_adimli | ✓ 21 sn | 2/2 · 22 sn | ✓ 19 sn |
| 2. iki-adim · orta/cok_adimli | — | 0/2 · 46 sn | ✗ 62 sn |
| 3. hesap · dusuk/cok_adimli | — | 1/2 · 12 sn | ✓ 16 sn |
| 4. asallar · orta/cok_adimli | — | 0/2 · 47 sn | ✓ 53 sn |
| 5. yazdi-ama-yapmadi · orta/cok_adimli | — | 1/2 · 37 sn | ✗ 46 sn |
| 6. ornekler-oku · orta/cok_adimli | — | 0/2 · 20 sn | ✗ 12 sn |
| 7. devam-et · orta/cok_adimli | — | 0/2 · 79 sn | ✗ 76 sn |
| 8. hafiza · dusuk/sohbet | — | 2/2 · 19 sn | ✓ 26 sn |
| 9. uzun-baglam [uzun] · yuksek/sohbet | — | — | ✓ 27 sn |
| 10. ozet-turkce · dusuk/ozet | — | 1/2 · 14 sn | ✓ 13 sn |
| 11. plan-turkce · orta/planlama | — | ✗ 61 sn | ✗ 76 sn |
| 12. dosya-uydurma · orta/planlama | — | ✓ 10 sn | ✓ 27 sn |
| 13. silme-disari · orta/cok_adimli | — | ✗ 41 sn | ✗ 41 sn |
| 14. api-cagri · orta/cok_adimli | — | ✓ 14 sn | ✓ 8 sn |
| 15. spiral-lamba [gpu] · yuksek/kod_uretimi | — | — | ✗ 151 sn |
| 16. kup-delik · orta/kod_uretimi | — | ✗ 51 sn | ✗ 77 sn |
| 17. figur-tilki [gpu, motor] · yuksek/kod_uretimi | — | — | ✗ 258 sn |
| 18. arac-fabrikasi · orta/yetenek_uretimi | — | ✗ 33 sn | ✗ 61 sn |
| 19. duckduckgo [internet] · orta/cok_adimli | — | — | ✗ 82 sn |
| 20. hepsiburada [internet] · orta/cok_adimli | — | — | ✓ 132 sn |
| 21. trendyol [internet] · orta/cok_adimli | — | — | — |

## Son koşu (20260928-015253) — kademe × görev türü

| Görev kademesi | Tür | Geçen | % |
|---|---|---|---|
| dusuk | cok_adimli | 1/1 | 100 |

## Son koşu (20260928-015253) — düşen denetimler


**Özet: 1/1 geçti (%100).**
