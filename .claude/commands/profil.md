---
description: Bu makinede donanım profilini çıkarır, kademeyi hesaplar, gerçek donanımla karşılaştırıp yanlış ölçümleri düzeltir
argument-hint: [isteğe bağlı: "benchmark" — yerel modellerde 30 sn hız ölçümü de yap]
---

Mod: $ARGUMENTS

1. `asistan/cekirdek/profil.py` henüz yoksa dur: "Önce `/asama K2`" de.

2. Profili çalıştır: `python -m asistan.cekirdek.profil` (ya da `cafer profil`). Çıktıyı ve `.cafer/profil.json`'u göster.

3. **Gerçekle karşılaştır.** Bağımsız kaynaklardan aynı bilgiyi al ve tablo yap:
   - RAM: `psutil` ya da işletim sistemi komutu (Windows: `wmic`/`Get-CimInstance`, Linux: `free -g`, macOS: `sysctl hw.memsize`)
   - GPU/VRAM: `nvidia-smi --query-gpu=name,memory.total --format=csv` → yoksa `torch.cuda` → yoksa Vulkan/Metal
   - CPU: `os.cpu_count()` + model adı
   - Ollama: `curl localhost:11434/api/tags` (ya da `ollama list`)
   
   | Alan | profil.py dedi | Gerçek | Uyum |

4. Uyumsuzluk varsa `profil.py`'yi düzelt (kanıtla), testini ekle, tekrar çalıştır.

5. Kademe kararını açıkla: hangi eşikten dolayı bu kademe? `docs/MIMARI.md` §3 tablosuyla tutarlı mı? Değilse tabloyu mu kodu mu düzeltmek gerektiğini söyle ve bana sor.

6. "benchmark" verildiyse: Ollama'daki her modeli sırayla 30 sn'lik kısa istekle ölç (token/sn, ilk-token ms), `profil.json` → `benchmark` alanına yaz. 3 tok/sn altındaki modelleri "bu kademe için yavaş" olarak işaretle.

7. Rapor: profil özeti, kademe + nedeni, düzeltilen şeyler.
