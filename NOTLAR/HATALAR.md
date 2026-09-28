# Hata kütüğü (K6) — `/hata-analiz` her düzeltmede bir satır ekler

Biçim: `YYYY-AA-GG | <sınıf> | <belirti kısa> | <düzeltme kısa> | <sınıflandırıcıya eklendi mi>`
Sınıflar (MIMARI §7): model_yetersiz · eksik_bagimlilik · eksik_yetenek · izin · ag · mantik · veri · kaynak.
Programın kendi kütüğü çalışma anında `DATA_DIR/hatalar.jsonl` (`cekirdek/analiz/hata.py → isle`), kalıcı ek desenler
`DATA_DIR/hata_desenleri.json` (`hata.desen_ekle`).

2026-09-28 | ag | "512 bayt" ve "CUDA 12.4" gibi metinler ağ/kaynak hatası sayılıyordu (BÖLÜM 2.7) | 5xx yalnızca HTTP bağlamında, CUDA yalnızca bellek/hata bağlamında | evet (`DESENLER`)
2026-09-28 | veri | "liste bulunamadı" (mantık) `veri` sayılıyordu | "bulunamadı" yalnızca dosya/klasör için | evet (`DESENLER`)
