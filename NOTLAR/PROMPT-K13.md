# K13 — Güç ve donanım farkındalığı

CLAUDE.md'yi oku. k-serisi dalında çalış. Soru sorma; karar gerekirse NOTLAR/SORULAR.md'ye geçici karar yaz. Mevcut parçaların
üstüne kur, yeniden yazma: sysinfo.scan, gpu.fault, K7 kademe otomatik ayarı, cekirdek/baglam.py (VRAM'e göre bağlam), roster/profil.
Onay kuralları permissions.py'de kalır. Ollama Linux'ta yalnızca NVIDIA (CUDA) ve ROCm destekli AMD kullanır; Intel/AMD dahili GPU'yu
görmez — sahte "dahili GPU'ya geçti" seçeneği üretme; gerçek seçenekler harici GPU / kısmi GPU (num_gpu) / CPU.

Amaç: dizüstü fişte/pilde farklı davranır (NVIDIA pilde saat ve güç sınırını düşürür; hibrit grafikte dGPU uyuyabilir). Program bunu
fark etsin, "ekran kartı performans vermiyor" demek yerine kendini uyarlasın ve ölçüme dayalı en iyi seçeneği seçsin.

1. cekirdek/donanim.py (yeni, Qt'siz, tüm çağrılar zaman aşımlı, asla GUI iş parçacığında, sonuç 10 sn önbellekli):
   - guc_durumu(): Linux /sys/class/power_supply/*/online ve type=Mains, yoksa `upower -i`; Windows GetSystemPowerStatus (ctypes);
     macOS `pmset -g batt`. Dönüş {"fiste": bool, "pil_yuzde": int|None}.
   - gpu_envanteri(): `nvidia-smi --query-gpu=name,memory.total,memory.used,power.limit,power.draw,clocks.sm,clocks.max.sm,pstate,utilization.gpu
     --format=csv`; lspci ile dahili GPU listelenir ama "ollama_kullanabilir": false. Hem iGPU hem dGPU varsa "hibrit": true; dGPU
     uyuyorsa (nvidia-smi zaman aşımı ya da pstate P8 + 0 kullanım) "uyuyor": true. Ayrıca `ollama ps` çıktısından yüklü modelin CPU/GPU
     yüzdesi okunur; kart sağlamken model %100 CPU'daysa "ollama_gpu_gormuyor": true.
   - cpu_ram(): çekirdek sayısı, boş RAM, anlık yük.

2. Anlık ölçüm — cekirdek/analiz/olcum.py'ye ekle:
   - hizli_sonda(model, cihaz): Ollama'ya 32 token'lık sabit istem (num_predict=32); eval_rate (tok/sn) ve yükleme süresi.
     cihaz "gpu" → normal; "cpu" → num_gpu=0. DATA_DIR/donanim_olcum.json'a {model, cihaz, fiste, tok_sn, tarih} biriktir.
   - En fazla 2 sondayı arka planda, boşta koş; sohbet sırasında koşma.

3. Karar — K7 kademe ayarının olduğu modüle:
   - Girdi: guc_durumu + gpu_envanteri + son ölçümler. Çıktı {"cihaz": "gpu"|"cpu", "kademe": dusuk|orta|yuksek, "num_gpu": int|None,
     "num_ctx": int, "neden": str}.
   - Kurallar: pilde → yüksek kademe kapalı, bağlam yarıya; dGPU güç sınırı düşükse ölçülen tok/sn'ye göre karar (gpu tok/sn < 1.5 × cpu
     tok/sn ise CPU'ya geç); fişe takılınca eski karara dön; dGPU uyuyorsa tek uyandırma denemesi, başarısızsa CPU; VRAM'e sığmayan modelde
     num_gpu katman sayısını VRAM'e göre kıs (tam CPU'ya düşmeden önce kısmi yükleme); "ollama_gpu_gormuyor" ise kullanıcıya
     "Ollama'yı yeniden başlat" öner (onaylı `systemctl restart ollama`), sonra ölçümü yinele.
   - Karar değişince tek satır durum (durum çubuğu/log), rahatsız edici pencere yok: "Pile geçildi → orta kademe, 8K bağlam, GPU".

4. Olay: arka plan iş parçacığı güç kaynağını 15 sn'de bir yoklar (Linux'ta mümkünse UPower dbus sinyali); değişince karar yeniden
   çalışır ve roster/profil kademesi güncellenir. Süren istek bitene kadar bekler, sonraki istekte uygular.

5. Arayüz: Modeller penceresi/Ayarlar'da "Donanım" bölümü: fiş/pil, dGPU adı + güç sınırı + pstate, Ollama CPU/GPU yüzdesi, seçili cihaz,
   son ölçüm tok/sn, "Şimdi ölç" (arka planda), "Otomatik uyarla" anahtarı (kapalıysa kullanıcı kademeyi kendi seçer). Sihirbazın
   sistem taramasına hibrit bilgisi.

6. Testler (testler/test_k13_donanim.py): sahte /sys ve sahte nvidia-smi/ollama ps çıktısıyla guc_durumu/gpu_envanteri; karar tablosu
   (fişte/pilde × VRAM yeter/yetmez × ölçüm var/yok); güç değişiminde kademe güncellemesi; GUI iş parçacığında hiç subprocess yok
   (QT_QPA_PLATFORM=offscreen).

7. Bitiş: MIMARI'ye §13 "Donanım/güç", KONTROL_LISTEN'e "fişi çek → 30 sn içinde durum satırı değişti mi", NOTLAR/2026-09-28-K13.md,
   YAPILACAKLAR K13 tamam. Tam takım .venv pytest, /kontrol, commit "K13: güç ve donanım farkındalığı", git push.
Son satır: `SONUÇ: TAM|KISMEN · TEST: N✓/M✗/K atlandı`
