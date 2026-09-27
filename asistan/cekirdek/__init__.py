"""Çekirdek: arayüz bilmeyen saf Python katmanı (docs/MIMARI.md §2).

Burada PySide6, Qt, fastapi içe aktarılamaz (`testler/test_cekirdek_ayrimi.py` denetler). Masaüstü (`arayuz/masaustu`),
web ve komut satırı yüzleri çekirdeği çağırır; çekirdek onları bilmez.

Alt modüller: `ayar` (tek ayar kaynağı), `saglayici` (model sağlayıcıları), `araclar` (dosya/komut/Python/web),
`istek` (bir isteği yönetici döngüsüyle çalıştırma).
"""
