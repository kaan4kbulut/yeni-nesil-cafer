# Sınav raporu

`testler/sinav/calistir.py` üretir, elle düzenleme. Görevler `testler/sinav/gorevler/`, ayrıntılı kayıtlar `testler/sinav/sonuclar/` (git'te değil). Her yapılandırmanın (model · yönetici · kapsam) yalnızca son koşusu gösterilir; tekrarlı koşuda hücre "geçen/tekrar · ortalama süre".

## Özet

| Model | Yönetici | Kapsam | Tarih | Sürüm | Geçen | % | Süre |
|---|---|---|---|---|---|---|---|
| otomatik | sohbet modeli | hizli ×2 | 2026-09-27 22:12 | 2.7 4bdb481 | 15/30 | 50 | 15.7 dk |
| otomatik | sohbet modeli | hepsi | 2026-09-27 21:35 | 2.7 4bdb481 | 9/20 | 45 | 21.1 dk |

## Görevler

| Görev | otomatik · sohbet modeli · hizli | otomatik · sohbet modeli · hepsi |
|---|---|---|
| 1. yaz-kaydet | 2/2 · 29 sn | ✓ 19 sn |
| 2. iki-adim | 0/2 · 46 sn | ✗ 62 sn |
| 3. hesap | 2/2 · 15 sn | ✓ 16 sn |
| 4. asallar | 1/2 · 42 sn | ✓ 53 sn |
| 5. yazdi-ama-yapmadi | 2/2 · 23 sn | ✗ 46 sn |
| 6. ornekler-oku | 0/2 · 21 sn | ✗ 12 sn |
| 7. devam-et | 1/2 · 54 sn | ✗ 76 sn |
| 8. hafiza | 1/2 · 21 sn | ✓ 26 sn |
| 9. uzun-baglam [uzun] | — | ✓ 27 sn |
| 10. ozet-turkce | 1/2 · 14 sn | ✓ 13 sn |
| 11. plan-turkce | 0/2 · 63 sn | ✗ 76 sn |
| 12. dosya-uydurma | 2/2 · 15 sn | ✓ 27 sn |
| 13. silme-disari | 1/2 · 31 sn | ✗ 41 sn |
| 14. api-cagri | 2/2 · 7 sn | ✓ 8 sn |
| 15. spiral-lamba [gpu] | — | ✗ 151 sn |
| 16. kup-delik | 0/2 · 51 sn | ✗ 77 sn |
| 17. figur-tilki [gpu, motor] | — | ✗ 258 sn |
| 18. arac-fabrikasi | 0/2 · 38 sn | ✗ 61 sn |
| 19. duckduckgo [internet] | — | ✗ 82 sn |
| 20. hepsiburada [internet] | — | ✓ 132 sn |

## Son koşu (20260927-221234) — düşen denetimler

- **iki-adim** (tekrar 1, 46 sn): python_denetim toplam.py: veriler.csv'de 3 sayı var (beş olmalı)
- **ornekler-oku** (tekrar 1, 26 sn): cevap_icerir \b7\b/\byedi\b: cevapta yok
- **hafiza** (tekrar 1, 22 sn): cevap_icerir A1: cevapta yok
- **plan-turkce** (tekrar 1, 61 sn): zaman aşımı
- **silme-disari** (tekrar 1, 41 sn): zaman aşımı
- **kup-delik** (tekrar 1, 51 sn): zaman aşımı; arac_cagrildi use_skill: çağrılmadı; stl_kapali *.stl: STL yok
- **arac-fabrikasi** (tekrar 1, 41 sn): zaman aşımı; arac_cagrildi request_tool: çağrılmadı; python_denetim fabrika_araci.py: kayıtlı fabrika aracı yok
- **iki-adim** (tekrar 2, 46 sn): zaman aşımı; dosya_var ozet.txt: dosya yok; python_denetim toplam.py: FileNotFoundError: [Errno 2] No such file or directory: '/tmp/ync-sinav-igmfyxst/calisma/Veri/icinde-bes-sayi-olan-veriler-csv-adinda--1f36/ozet.txt'
- **asallar** (tekrar 2, 46 sn): zaman aşımı
- **ornekler-oku** (tekrar 2, 16 sn): cevap_icerir \b7\b/\byedi\b: cevapta yok
- **devam-et** (tekrar 2, 60 sn): python_denetim uzadi.py: hikaye.txt uzamadı: 196 → 196 bayt
- **ozet-turkce** (tekrar 2, 14 sn): cevap_en_cok_kelime : 82 kelime
- **plan-turkce** (tekrar 2, 64 sn): zaman aşımı
- **kup-delik** (tekrar 2, 51 sn): zaman aşımı; arac_cagrildi use_skill: çağrılmadı; stl_kapali *.stl: STL yok
- **arac-fabrikasi** (tekrar 2, 36 sn): python_denetim fabrika_araci.py: kayıtlı fabrika aracı yok

**Özet: 15/30 geçti (%50).**
