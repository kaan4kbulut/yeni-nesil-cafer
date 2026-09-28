# Sınav raporu

`testler/sinav/calistir.py` üretir, elle düzenleme. Görevler `testler/sinav/gorevler/`, ayrıntılı kayıtlar `testler/sinav/sonuclar/` (git'te değil). Her yapılandırmanın (model · yönetici · kapsam) yalnızca son koşusu gösterilir; tekrarlı koşuda hücre "geçen/tekrar · ortalama süre".

## Özet

| Model | Yönetici | Kapsam | Tarih | Sürüm | Geçen | % | Süre |
|---|---|---|---|---|---|---|---|
| otomatik | sohbet modeli | hizli+motor | 2026-09-28 13:25 | 3.0 e428162 | 0/6 | 0 | 4.4 dk |
| otomatik | sohbet modeli | hizli+manager | 2026-09-28 13:14 | 3.0 e428162 | 2/15 | 13 | 11.2 dk |
| otomatik | otomatik | hizli | 2026-09-28 01:53 | 2.7 44704d8 | 1/1 | 100 | 0.3 dk |
| otomatik | sohbet modeli | hizli ×2 | 2026-09-27 23:35 | 2.7 5f839a1 | 9/24 | 38 | 13.4 dk |
| otomatik | sohbet modeli | hepsi | 2026-09-27 21:35 | 2.7 4bdb481 | 9/20 | 45 | 21.1 dk |

## Görevler

| Görev | otomatik · sohbet modeli · hizli+motor | otomatik · sohbet modeli · hizli+manager | otomatik · otomatik · hizli | otomatik · sohbet modeli · hizli | otomatik · sohbet modeli · hepsi |
|---|---|---|---|---|---|
| 1. yaz-kaydet · dusuk/cok_adimli | ✗ 46 sn | ✗ 72 sn | ✓ 21 sn | 2/2 · 22 sn | ✓ 19 sn |
| 2. iki-adim · orta/cok_adimli | ✗ 110 sn | ✗ 59 sn | — | 0/2 · 46 sn | ✗ 62 sn |
| 3. hesap · dusuk/cok_adimli | ✗ 22 sn | ✗ 32 sn | — | 1/2 · 12 sn | ✓ 16 sn |
| 4. asallar · orta/cok_adimli | ✗ 22 sn | ✗ 46 sn | — | 0/2 · 47 sn | ✓ 53 sn |
| 5. yazdi-ama-yapmadi · orta/cok_adimli | ✗ 48 sn | ✗ 46 sn | — | 1/2 · 37 sn | ✗ 46 sn |
| 6. ornekler-oku · orta/cok_adimli | ✗ 14 sn | ✗ 27 sn | — | 0/2 · 20 sn | ✗ 12 sn |
| 7. devam-et · orta/cok_adimli | — | ✗ 84 sn | — | 0/2 · 79 sn | ✗ 76 sn |
| 8. hafiza · dusuk/sohbet | — | ✗ 50 sn | — | 2/2 · 19 sn | ✓ 26 sn |
| 9. uzun-baglam [uzun] · yuksek/sohbet | — | — | — | — | ✓ 27 sn |
| 10. ozet-turkce · dusuk/ozet | — | ✗ 38 sn | — | 1/2 · 14 sn | ✓ 13 sn |
| 11. plan-turkce · orta/planlama | — | ✗ 65 sn | — | ✗ 61 sn | ✗ 76 sn |
| 12. dosya-uydurma · orta/planlama | — | ✓ 12 sn | — | ✓ 10 sn | ✓ 27 sn |
| 13. silme-disari · orta/cok_adimli | — | ✓ 15 sn | — | ✗ 41 sn | ✗ 41 sn |
| 14. api-cagri · orta/cok_adimli | — | ✗ 31 sn | — | ✓ 14 sn | ✓ 8 sn |
| 15. spiral-lamba [gpu] · yuksek/kod_uretimi | — | — | — | — | ✗ 151 sn |
| 16. kup-delik · orta/kod_uretimi | — | ✗ 51 sn | — | ✗ 51 sn | ✗ 77 sn |
| 17. figur-tilki [gpu, motor] · yuksek/kod_uretimi | — | — | — | — | ✗ 258 sn |
| 18. arac-fabrikasi · orta/yetenek_uretimi | — | ✗ 41 sn | — | ✗ 33 sn | ✗ 61 sn |
| 19. duckduckgo [internet] · orta/cok_adimli | — | — | — | — | ✗ 82 sn |
| 20. hepsiburada [internet] · orta/cok_adimli | — | — | — | — | ✓ 132 sn |
| 21. trendyol [internet] · orta/cok_adimli | — | — | — | — | — |

## Son koşu (20260928-132415) — kademe × görev türü

| Görev kademesi | Tür | Geçen | % |
|---|---|---|---|
| dusuk | cok_adimli | 0/2 | 0 |
| orta | cok_adimli | 0/4 | 0 |

## Son koşu (20260928-132415) — düşen denetimler

- **yaz-kaydet** (tekrar 1, 46 sn): zaman aşımı
- **iki-adim** (tekrar 1, 110 sn): zaman aşımı; dosya_var veriler.csv: dosya yok; dosya_var ozet.txt: dosya yok
- **hesap** (tekrar 1, 22 sn): cevap_icerir 7[., ]?006[., ]?652: cevapta yok; arac_cagrildi run_python: çağrılmadı
- **asallar** (tekrar 1, 22 sn): dosya_var asallar.txt: dosya yok; python_denetim asallar.py: FileNotFoundError: [Errno 2] No such file or directory: '/tmp/ync-sinav-n0c_ti7y/calisma/Genel/1-ile-100-arasindaki-asal-sayilari-asall-55d7/asallar.txt'
- **yazdi-ama-yapmadi** (tekrar 1, 48 sn): zaman aşımı; dosya_var notlar/a.txt: dosya yok; dosya_var notlar/b.txt: dosya yok
- **ornekler-oku** (tekrar 1, 14 sn): cevap_icerir \b7\b/\byedi\b: cevapta yok

**Özet: 0/6 geçti (%0).**
