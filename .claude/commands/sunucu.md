---
description: Sunucu (web/telefon) modunu yerelde ayağa kaldırır ve uçtan uca doğrular; Docker ile de dener
argument-hint: [isteğe bağlı: "docker" — docker compose ile de test et]
---

Mod: $ARGUMENTS

1. `asistan/arayuz/web/` yoksa dur: "Önce `/asama K8`".

2. **Çıplak çalıştırma.** Arka planda başlat: `CAFER_TOKEN=test123 CAFER_GENEL_KADEME_KILIDI=sunucu python -m asistan sunucu --port 8765` (gerçek komut adını `pyproject.toml`'dan al). 5 sn bekle.

3. **Uçtan uca kontrol** (curl ile, hepsini çalıştır):
   - `GET /saglik` → 200, `{"durum":"ok","kademe":"sunucu"}`
   - `GET /` → PWA HTML döner, `manifest.webmanifest` ve service worker linki var
   - Token'sız `POST /gorev` → 401
   - Token'lı `POST /gorev {"istek":"merhaba de"}` → 202 + `gorev_id`
   - `GET /gorev/<id>` → durum ilerliyor (en fazla 30 sn bekle)
   - `GET /onaylar` → liste (boş olabilir)
   - Çekirdek `PySide6` yüklemedi mi: sunucu sürecinde `sys.modules` içinde `PySide6` yok (bir debug uç noktası ya da `python -X importtime` ile göster)

4. **Telefon senaryosu.** Aynı ağdaki telefon için yazdır: `http://<yerel-ip>:8765` ve token. (IP'yi bul, yazdır; ben telefondan deneyeceğim.)

5. "docker" verildiyse:
   - `sunucu/Dockerfile` ve `docker-compose.yml` var mı? Yoksa `docs/MIMARI.md` §9'a göre yaz.
   - `docker compose -f sunucu/docker-compose.yml up --build -d` → aynı curl seti → `down`.
   - İmaj boyutunu yaz; 500 MB üstüyse nedenini (hangi bağımlılık) söyle.

6. Süreci kapat. Rapor: geçen/kalan kontroller, telefon adresi, imaj boyutu, açık sorunlar.
