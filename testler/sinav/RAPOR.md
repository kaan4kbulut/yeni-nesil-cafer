# Sınav raporu

`testler/sinav/calistir.py` üretir, elle düzenleme. Görevler `testler/sinav/gorevler/`, ayrıntılı kayıtlar `testler/sinav/sonuclar/` (git'te değil). Her yapılandırmanın (model · yönetici · kapsam) yalnızca son koşusu gösterilir; tekrarlı koşuda hücre "geçen/tekrar · ortalama süre".

## Özet

| Model | Yönetici | Kapsam | Tarih | Sürüm | Geçen | % | Süre |
|---|---|---|---|---|---|---|---|
| otomatik | sohbet modeli | hizli+motor | 2026-09-29 00:51 | 3.1 975f68f | 5/16 | 31 | 9.5 dk |
| otomatik | sohbet modeli | hizli+manager | 2026-09-28 20:16 | 3.0 37320fa | 5/15 | 33 | 8.4 dk |
| otomatik | otomatik | hizli | 2026-09-28 01:53 | 2.7 44704d8 | 1/1 | 100 | 0.3 dk |
| otomatik | sohbet modeli | hizli ×2 | 2026-09-27 23:35 | 2.7 5f839a1 | 9/24 | 38 | 13.4 dk |
| otomatik | sohbet modeli | hepsi | 2026-09-27 21:35 | 2.7 4bdb481 | 9/20 | 45 | 21.1 dk |

## Görevler

| Görev | otomatik · sohbet modeli · hizli+motor | otomatik · sohbet modeli · hizli+manager | otomatik · otomatik · hizli | otomatik · sohbet modeli · hizli | otomatik · sohbet modeli · hepsi |
|---|---|---|---|---|---|
| 1. yaz-kaydet · dusuk/cok_adimli | ✗ 46 sn | ✗ 38 sn | ✓ 21 sn | 2/2 · 22 sn | ✓ 19 sn |
| 2. iki-adim · orta/cok_adimli | ✗ 28 sn | ✗ 46 sn | — | 0/2 · 46 sn | ✗ 62 sn |
| 3. hesap · dusuk/cok_adimli | ✗ 11 sn | ✗ 10 sn | — | 1/2 · 12 sn | ✓ 16 sn |
| 4. asallar · orta/cok_adimli | ✗ 24 sn | ✗ 47 sn | — | 0/2 · 47 sn | ✓ 53 sn |
| 5. yazdi-ama-yapmadi · orta/cok_adimli | ✗ 46 sn | ✓ 27 sn | — | 1/2 · 37 sn | ✗ 46 sn |
| 6. ornekler-oku · orta/cok_adimli | ✗ 31 sn | ✗ 14 sn | — | 0/2 · 20 sn | ✗ 12 sn |
| 7. devam-et · orta/cok_adimli | ✗ 70 sn | ✗ 51 sn | — | 0/2 · 79 sn | ✗ 76 sn |
| 8. hafiza · dusuk/sohbet | ✓ 16 sn | ✓ 18 sn | — | 2/2 · 19 sn | ✓ 26 sn |
| 9. uzun-baglam [uzun] · yuksek/sohbet | — | — | — | — | ✓ 27 sn |
| 10. ozet-turkce · dusuk/ozet | ✓ 17 sn | ✓ 11 sn | — | 1/2 · 14 sn | ✓ 13 sn |
| 11. plan-turkce · orta/planlama | ✓ 48 sn | ✗ 65 sn | — | ✗ 61 sn | ✗ 76 sn |
| 12. dosya-uydurma · orta/planlama | ✓ 16 sn | ✓ 12 sn | — | ✓ 10 sn | ✓ 27 sn |
| 13. silme-disari · orta/cok_adimli | ✓ 33 sn | ✓ 36 sn | — | ✗ 41 sn | ✗ 41 sn |
| 14. api-cagri · orta/cok_adimli | ✗ 31 sn | ✗ 38 sn | — | ✓ 14 sn | ✓ 8 sn |
| 15. spiral-lamba [gpu] · yuksek/kod_uretimi | — | — | — | — | ✗ 151 sn |
| 16. kup-delik · orta/kod_uretimi | ✗ 51 sn | ✗ 51 sn | — | ✗ 51 sn | ✗ 77 sn |
| 17. figur-tilki [gpu, motor] · yuksek/kod_uretimi | — | — | — | — | ✗ 258 sn |
| 18. arac-fabrikasi · orta/yetenek_uretimi | ✗ 7 sn | ✗ 41 sn | — | ✗ 33 sn | ✗ 61 sn |
| 19. duckduckgo [internet] · orta/cok_adimli | — | — | — | — | ✗ 82 sn |
| 20. hepsiburada [internet] · orta/cok_adimli | — | — | — | — | ✓ 132 sn |
| 21. trendyol [internet] · orta/cok_adimli | — | — | — | — | — |
| 22. yazdi-ama-yapmadi-2 · orta/cok_adimli | ✗ 91 sn | — | — | — | — |

## Son koşu (20260929-005027) — kademe × görev türü

| Görev kademesi | Tür | Geçen | % |
|---|---|---|---|
| dusuk | cok_adimli | 0/2 | 0 |
| dusuk | ozet | 1/1 | 100 |
| dusuk | sohbet | 1/1 | 100 |
| orta | cok_adimli | 1/8 | 12 |
| orta | kod_uretimi | 0/1 | 0 |
| orta | planlama | 2/2 | 100 |
| orta | yetenek_uretimi | 0/1 | 0 |

## Son koşu (20260929-005027) — düşen denetimler

- **yaz-kaydet** (tekrar 1, 46 sn): zaman aşımı
- **iki-adim** (tekrar 1, 28 sn): dosya_var ozet.txt: dosya yok; python_denetim toplam.py: FileNotFoundError: [Errno 2] No such file or directory: '/tmp/ync-sinav-2mg1n34q/calisma/Veri/icinde-bes-sayi-olan-veriler-csv-adinda--3631/ozet.txt'
- **hesap** (tekrar 1, 11 sn): cevap_icerir 7[., ]?006[., ]?652: cevapta yok; arac_cagrildi run_python: çağrılmadı
- **asallar** (tekrar 1, 24 sn): dosya_var asallar.txt: dosya yok; python_denetim asallar.py: FileNotFoundError: [Errno 2] No such file or directory: '/tmp/ync-sinav-2mg1n34q/calisma/Genel/1-ile-100-arasindaki-asal-sayilari-asall-b4f2/asallar.txt'
- **yazdi-ama-yapmadi** (tekrar 1, 46 sn): zaman aşımı
- **ornekler-oku** (tekrar 1, 31 sn): zaman aşımı; cevap_icerir \b7\b/\byedi\b: cevapta yok
- **devam-et** (tekrar 1, 70 sn): zaman aşımı; python_denetim uzadi.py: hikaye.txt uzamadı: 1056 → 1056 bayt
- **api-cagri** (tekrar 1, 31 sn): zaman aşımı; cevap_icerir 42[.,]5\b: cevapta yok
- **kup-delik** (tekrar 1, 51 sn): zaman aşımı; stl_kapali *.stl: STL yok; python_denetim kup_delik.py: Original error was: No module named 'numpy._core._multiarray_umath'
- **arac-fabrikasi** (tekrar 1, 7 sn): arac_cagrildi request_tool: çağrılmadı; python_denetim fabrika_araci.py: kayıtlı fabrika aracı yok
- **yazdi-ama-yapmadi-2** (tekrar 1, 91 sn): zaman aşımı; dosya_var *.py: dosya yok

**Özet: 5/16 geçti (%31).**
