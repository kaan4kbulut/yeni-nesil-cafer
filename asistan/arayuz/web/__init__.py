"""Web yüzü (K8, MIMARI §9): FastAPI + PWA. Masaüstü kodu (`gui`, PySide6) YÜKLENMEZ; çekirdeği çağırır.

Uç noktalar: `/saglik` (anahtarsız), `/` + PWA dosyaları, `/gorev` (POST/GET, `/gorev/{id}`, `/onayla`, `/yanit`,
`/devam`), `/onaylar`, `/yetenekler`, `/profil`, `/sohbet` (SSE). Eski bulut API'si (`/api/health`, `/api/sync`,
`/api/queue…`, `/api/chat`, `/api/history`: masaüstünün `cloud_sync`'i ve Telegram kuyruğu) aynı uygulamada sürer.
Kimlik: tek kullanıcı, `CAFER_TOKEN` (yoksa `bulut.json → token`); yanlış/eksik → 401. Onay kuralı yine
`permissions.py`'de: web'den gelen görevlerde izin bağlamı yok → yazan/çalıştıran her adım `/onaylar`'da bekler.
"""

import json
import queue
import secrets
import threading
import time
from pathlib import Path

from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse

from ...cekirdek import profil
from ...cekirdek.gorev import durum as durum_mod

STATIK = Path(__file__).resolve().parent / "statik"
DOSYALAR = {"/": ("index.html", "text/html"), "/stil.css": ("stil.css", "text/css"),
            "/uygulama.js": ("uygulama.js", "application/javascript"), "/sw.js": ("sw.js", "application/javascript"),
            "/manifest.webmanifest": ("manifest.webmanifest", "application/manifest+json"),
            "/simge.svg": ("simge.svg", "image/svg+xml")}


def maskele(anahtar: str) -> str:
    """K12-B10: anahtar günlüğe (docker/journald) tam yazılmaz; tamamı `bulut.json`/`CAFER_TOKEN`'da."""
    a = str(anahtar or "")
    return (a[:4] if len(a) >= 12 else "") + f"…({len(a)} karakter)"


def anahtar_bul() -> str:
    """`CAFER_TOKEN` → `bulut.json → token` (cloud_server ilk açılışta üretir) → rastgele (ekrana yazılır)."""
    import os

    a = os.environ.get("CAFER_TOKEN", "").strip()
    if a:
        return a
    try:
        from ... import cloud_server

        return str(cloud_server.load_config().get("token") or "")
    except Exception:
        return secrets.token_urlsafe(24)


class _Olaylar:
    """Görev motorunun olayları (web: son olaylar bellekte; durum deposu zaten `gorevler.db`)."""

    def __init__(self):
        self.son: dict[str, list[dict]] = {}
        self.kilit = threading.Lock()

    def __call__(self, tur: str, veri: dict) -> None:
        gid = (veri.get("gorev") or {}).get("gorev_id", "")
        with self.kilit:
            liste = self.son.setdefault(gid, [])
            liste.append({"tur": tur, "zaman": time.time(),
                          "adim": (veri.get("adim") or {}).get("id"), "not": str(veri.get("neden") or veri.get("soru") or "")[:200]})
            del liste[:-50]


class _SohbetCb:
    """Ajanın olaylarını SSE kuyruğuna çevirir; onay isteyen her şey reddedilir (web sohbeti salt okunur;
    değişiklik gerektiren iş `/gorev` ile görev motoruna verilir ve `/onaylar`'da onaylanır)."""

    def __init__(self, k: "queue.Queue"):
        self.k = k

    def on_text(self, delta):
        self.k.put({"tur": "metin", "metin": delta})

    def on_tool_start(self, call_id, name, args):
        self.k.put({"tur": "arac", "ad": name})

    def on_route(self, text):
        self.k.put({"tur": "not", "metin": text})

    def on_plan(self, steps):
        if steps:
            self.k.put({"tur": "not", "metin": "plan: " + " → ".join(str(s.get("title") or s.get("amac") or "") for s in steps)})

    def ask_approval(self, name, args):
        self.k.put({"tur": "not", "metin": f"'{name}' onay gerektirir; web sohbetinde yapılmaz — görev olarak başlat"})
        return False

    def is_cancelled(self):
        return False

    def __getattr__(self, ad):  # on_thinking, on_model_start… : sessiz
        return lambda *a, **k: None


def _varsayilan_sohbet(metin: str, sohbet_id: str, olay) -> None:
    """Sunucu sohbeti: bulut kopyasının araçları (arama, sayfa okuma, hafıza, bilgisayara iş bırakma), geçmiş
    `cloud_server.history(kanal)`. Bilgisayara erişim yok (cloud_server ile aynı kural)."""
    from ... import cloud_server
    from ...agent import Agent
    from ...cekirdek import istek

    conf = cloud_server.load_config()
    ayarlar = cloud_server.settings_for_cloud(conf)
    Path(ayarlar.workspace).mkdir(parents=True, exist_ok=True)
    k: queue.Queue = queue.Queue()
    ajan = Agent(ayarlar, _SohbetCb(k))
    ajan.tool_specs = [s for s in ajan.tool_specs if s["name"] in cloud_server.CLOUD_TOOLS] + [cloud_server.QUEUE_SPEC]
    ajan.base_system = cloud_server.cloud_prompt()
    ajan.extra_system = cloud_server.CLOUD_NOTE
    kanal = f"web:{sohbet_id}" if sohbet_id else "web"
    mesajlar = cloud_server.history(kanal)

    def kos():
        try:
            with cloud_server._agent_lock:
                cloud_server._local.channel = kanal
                try:
                    istek.calistir(ajan, ayarlar.provider, mesajlar, metin)
                finally:
                    cloud_server._local.channel = ""
            cloud_server._save_history(kanal, mesajlar)
        except Exception as e:
            k.put({"tur": "hata", "metin": f"{type(e).__name__}: {e}"[:300]})
        finally:
            k.put(None)

    threading.Thread(target=kos, daemon=True).start()
    while True:
        o = k.get()
        if o is None:
            break
        olay(o)


def uygulama(anahtar: str | None = None, motor_kur=None, sohbet_calistir=None, depo=None) -> FastAPI:
    """Uygulama fabrikası. Testler sahte `motor_kur` (görev motoru), `sohbet_calistir(metin, sohbet_id, olay)` ve
    `depo` verir; üretimde çekirdeğin gerçek motoru ve deposu."""
    from ... import __version__

    anahtar = anahtar or anahtar_bul()
    app = FastAPI(title="YENİ NESİL CAFER", version=__version__, docs_url=None, redoc_url=None)
    olaylar = _Olaylar()
    motorlar: dict[str, object] = {}
    kilit = threading.Lock()

    def depo_al():
        return depo if depo is not None else durum_mod.depo()

    def motor_al(gorev_id: str, istek: str = ""):
        if gorev_id in motorlar:
            return motorlar[gorev_id]
        if motor_kur is not None:
            m = motor_kur(gorev_id=gorev_id, istek=istek, olay=olaylar)
        else:
            from ...cekirdek.gorev.komut import motor_kur as gercek

            m = gercek(istek=istek, gorev_id=gorev_id, olay=olaylar, kaynak="web")
        motorlar[gorev_id] = m
        return m

    def yetki(request: Request) -> None:
        verilen = request.headers.get("Authorization", "").removeprefix("Bearer ").strip()
        if not verilen or not secrets.compare_digest(verilen, anahtar):
            raise HTTPException(401, "yetkisiz: Authorization: Bearer <CAFER_TOKEN>")

    def arka_planda(fn):
        t = threading.Thread(target=fn, daemon=True)
        t.start()
        return t

    # ---- anahtarsız
    @app.get("/saglik")
    def saglik():
        import sys

        return {"durum": "ok", "kademe": profil.kademe(), "surum": __version__, "masaustu_yuklu": "PySide6" in sys.modules,
                "zaman": time.time()}

    for yol, (dosya, tur) in DOSYALAR.items():
        def _sun(dosya=dosya, tur=tur):
            return FileResponse(STATIK / dosya, media_type=tur, headers={"Cache-Control": "no-cache"})

        app.get(yol, include_in_schema=False)(_sun)

    # ---- görevler
    @app.post("/gorev", status_code=202, dependencies=[Depends(yetki)])
    def gorev_baslat(govde: dict):
        istek = str(govde.get("istek") or "").strip()
        if not istek:
            raise HTTPException(400, "istek boş")
        gid = str(govde.get("gorev_id") or "").strip() or durum_mod.yeni_id()
        m = motor_al(gid, istek)

        def kos():
            g = m.baslat(istek, gorev_id=gid)
            try:  # K9: sunucuda başlayan görev masaüstünde "sunucu" kaynaklı görünür (onay sunucuya gider)
                if isinstance(g, dict) and not g.get("_kaynak"):
                    g["_kaynak"] = "sunucu"
                    depo_al().kaydet(g)
            except Exception:
                pass

        arka_planda(kos)
        return {"gorev_id": gid, "durum": "planlandi"}

    @app.get("/gorev", dependencies=[Depends(yetki)])
    def gorevler(durum: str | None = None, sinir: int = 50):
        liste = depo_al().listele((durum,) if durum else None, sinir)
        return {"gorevler": [{"gorev_id": g["gorev_id"], "istek": g.get("istek", ""), "durum": g.get("durum"),
                              "olusturma": g.get("olusturma"), "adim": len(g.get("adimlar") or [])} for g in liste]}

    @app.get("/gorev/{gorev_id}", dependencies=[Depends(yetki)])
    def gorev(gorev_id: str):
        g = depo_al().getir(gorev_id)
        if g is None:
            raise HTTPException(404, "görev yok")
        g["olaylar"] = olaylar.son.get(gorev_id, [])[-20:]
        return g

    @app.post("/gorev/{gorev_id}/onayla", dependencies=[Depends(yetki)])
    def onayla(gorev_id: str, govde: dict | None = None):
        evet = bool((govde or {}).get("evet", True))
        m = motor_al(gorev_id)
        with kilit:
            arka_planda(lambda: m.onayla(gorev_id, evet))
        return {"gorev_id": gorev_id, "onay": evet}

    @app.post("/gorev/{gorev_id}/yanit", dependencies=[Depends(yetki)])
    def yanitla(gorev_id: str, govde: dict):
        cevap = str(govde.get("cevap") or "").strip()
        if not cevap:
            raise HTTPException(400, "cevap boş")
        m = motor_al(gorev_id)
        arka_planda(lambda: m.yanitla(gorev_id, cevap))
        return {"gorev_id": gorev_id, "durum": "calisiyor"}

    @app.post("/gorev/{gorev_id}/devam", dependencies=[Depends(yetki)])
    def devam(gorev_id: str):
        m = motor_al(gorev_id)
        arka_planda(lambda: m.devam(gorev_id))
        return {"gorev_id": gorev_id, "durum": "calisiyor"}

    @app.post("/gorev/{gorev_id}/iptal", dependencies=[Depends(yetki)])
    def iptal(gorev_id: str):
        return {"gorev_id": gorev_id, "iptal": bool(depo_al().iptal_et(gorev_id))}

    @app.post("/gorev/esitle", dependencies=[Depends(yetki)])
    def esitle(govde: dict):
        """K9 senkron: istemcinin değişen görevleri (son yazan kazanır, çakışma listesi) + sunucuda `since`'ten sonra
        değişenler. Sunucu tarafı çakışması: aynı görev iki yanda da değişmişse."""
        since = float(govde.get("since") or 0)
        now = time.time()
        cakismalar = []
        d = depo_al()
        for kayit in govde.get("gorevler") or []:
            g = kayit.get("gorev") or {}
            if not g.get("gorev_id"):
                continue
            sonuc = d.ice_aktar(g, float(kayit.get("guncelleme") or now), since)
            if sonuc == "cakisma":
                cakismalar.append({"gorev_id": g["gorev_id"], "yer": "sunucu", "zaman": now})
        degisen = [{"gorev": {k: v for k, v in g.items() if k != "_surum"}, "guncelleme": g["_surum"]}
                   for g in d.degisenler(since)]
        return {"gorevler": degisen, "now": now, "cakismalar": cakismalar}

    @app.get("/onaylar", dependencies=[Depends(yetki)])
    def onaylar():
        sonuc = []
        for g in depo_al().listele(("bekliyor_onay",), 100):
            if g.get("bekleyen_uretim"):
                ne = f"yetenek üretimi: {g['bekleyen_uretim'].get('ad')}"
            else:
                a = next((a for a in g.get("adimlar") or [] if a.get("durum") == "bekliyor_onay"), {})
                b = a.get("bekleyen") or {}
                ne = (f"kurulum: {b.get('hedef')}" if b.get("tip") == "kur" else f"yetenek üretimi: {b.get('ad')}"
                      if b else f"adım {a.get('id')}: {a.get('amac', '')} · {a.get('yetenek', '')}")
            sonuc.append({"gorev_id": g["gorev_id"], "istek": g.get("istek", ""), "ne": ne, "rapor": g.get("rapor") or ""})
        return {"onaylar": sonuc}

    @app.get("/yetenekler", dependencies=[Depends(yetki)])
    def yetenekler():
        from ...cekirdek.yetenek.kayit import Kayit

        k = Kayit()
        return {"yetenekler": [y.ozet() for y in k.aktifler() + k.pasifler()]}

    @app.get("/profil", dependencies=[Depends(yetki)])
    def profil_bilgisi():
        p = profil.yukle() or {}
        return {**p, "kademe_etkin": profil.kademe()}

    # ---- sohbet (SSE)
    @app.post("/sohbet", dependencies=[Depends(yetki)])
    def sohbet(govde: dict):
        metin = str(govde.get("metin") or "").strip()
        if not metin:
            raise HTTPException(400, "metin boş")
        sohbet_id = str(govde.get("sohbet_id") or "")
        calistir = sohbet_calistir or _varsayilan_sohbet
        k: queue.Queue = queue.Queue()

        def kos():
            try:
                calistir(metin, sohbet_id, k.put)
            except Exception as e:
                k.put({"tur": "hata", "metin": f"{type(e).__name__}: {e}"[:300]})
            finally:
                k.put(None)

        arka_planda(kos)

        def akis():
            while True:
                try:
                    o = k.get(timeout=15)
                except queue.Empty:
                    yield ": nabız\n\n"  # bağlantı açık kalsın
                    continue
                if o is None:
                    yield "data: " + json.dumps({"tur": "bitti"}, ensure_ascii=False) + "\n\n"
                    break
                yield "data: " + json.dumps(o, ensure_ascii=False) + "\n\n"

        return StreamingResponse(akis(), media_type="text/event-stream",
                                 headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})

    # ---- eski bulut API'si (masaüstü cloud_sync + Telegram kuyruğu), aynı süreçte
    @app.get("/api/health")
    def api_health():
        return {"ok": True, "time": time.time()}

    @app.get("/api/queue", dependencies=[Depends(yetki)])
    def api_queue(status: str | None = None):
        from ... import cloud_server

        return {"jobs": cloud_server.jobs(status)}

    @app.post("/api/queue/{job_id}", dependencies=[Depends(yetki)])
    def api_queue_update(job_id: str, govde: dict):
        from ... import cloud_server

        job = cloud_server.update_job(job_id, str(govde.get("status", "")), str(govde.get("result") or ""))
        return JSONResponse({"job": job}, status_code=200 if job else 404)

    @app.post("/api/sync", dependencies=[Depends(yetki)])
    def api_sync(govde: dict):
        from ... import memory_db

        now = time.time()
        applied = memory_db.apply_changes(govde.get("changes") or {})
        out = memory_db.changes_since(float(govde.get("since") or 0))
        return {"changes": out, "applied": applied, "now": now}

    @app.get("/api/history", dependencies=[Depends(yetki)])
    def api_history():
        from ... import cloud_server

        return {"messages": [m for m in cloud_server.history("web") if isinstance(m.get("content"), str)
                             and m["content"].strip() and not m.get("_program")]}

    @app.post("/api/chat", dependencies=[Depends(yetki)])
    def api_chat(govde: dict):
        from ... import cloud_server

        return {"reply": cloud_server.answer("web", str(govde.get("text", ""))[:4000])}

    app.state.anahtar = anahtar
    return app


def calistir(host: str = "127.0.0.1", port: int = 8765, telegram: bool = True) -> None:
    """`cafer sunucu --port`: uvicorn ile; Telegram anahtarı varsa bot döngüsü de bu süreçte (cloud_server)."""
    import uvicorn

    app = uygulama()
    print(f"YENİ NESİL CAFER · sunucu — http://{host}:{port}  (kademe: {profil.kademe()})")
    print(f"Erişim anahtarı (CAFER_TOKEN): {maskele(app.state.anahtar)} — tamamı bulut.json'da (günlüğe yazılmaz)")
    if telegram:
        try:
            from ... import cloud_server

            if cloud_server.load_config().get("telegram_token"):
                stop = threading.Event()
                threading.Thread(target=cloud_server.telegram_loop, args=(stop,), daemon=True).start()
                print("Telegram botu açık")
        except Exception as e:
            print(f"Telegram başlatılamadı: {e}")
    uvicorn.run(app, host=host, port=port, log_level="warning")
