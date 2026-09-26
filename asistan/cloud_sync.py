"""Bulut bağlantısı (Aşama 6, bilgisayar tarafı): hafıza eşitleme ve bulut asistanın bıraktığı işler.

Ayar: settings.extra["cloud"] = {"url": "http://sunucu:8765", "token": "...", "enabled": true}. Program açıkken
dakikada bir: yerel hafıza değişiklikleri sunucuya gider, sunucununkiler gelir (memory_db.changes_since /
apply_changes); bekleyen işler çekilir. İşler kendiliğinden ÇALIŞTIRILMAZ: program listeler, kullanıcı tıklarsa
yerel asistan yapar ve sonucu sunucuya geri yollar (sunucu da işin geldiği kanala iletir).
"""

import time

import httpx

from . import memory_db

TIMEOUT = httpx.Timeout(20, connect=5)


class CloudError(Exception):
    pass


def config(settings) -> dict:
    conf = settings.extra.get("cloud") or {}
    return conf if conf.get("url") and conf.get("token") else {}


def enabled(settings) -> bool:
    conf = config(settings)
    return bool(conf) and conf.get("enabled", True)


def _call(conf: dict, method: str, path: str, body: dict | None = None, timeout=TIMEOUT) -> dict:
    url = conf["url"].rstrip("/") + path
    try:
        resp = httpx.request(method, url, json=body, timeout=timeout,
                             headers={"Authorization": f"Bearer {conf['token']}"})
    except httpx.HTTPError as e:
        raise CloudError(f"sunucuya ulaşılamadı: {e}") from e
    if resp.status_code == 401:
        raise CloudError("erişim anahtarı yanlış")
    if resp.status_code >= 400:
        raise CloudError(f"sunucu hatası ({resp.status_code}): {resp.text[:200]}")
    return resp.json()


def check(settings) -> str:
    """Bağlantıyı dener: kısa Türkçe durum metni."""
    conf = config(settings)
    if not conf:
        return "adres ve anahtar girilmedi"
    _call(conf, "GET", "/api/queue?status=bekliyor")
    return "bağlantı tamam"


def sync(settings) -> tuple[int, int]:
    """Hafızayı iki yönlü eşitler: (gönderilen, alınan) kayıt sayısı."""
    conf = config(settings)
    if not conf:
        raise CloudError("bulut ayarlanmadı")
    pushed_until = float(memory_db.meta("cloud_pushed") or 0)
    pulled_until = float(memory_db.meta("cloud_pulled") or 0)
    now = time.time()
    local = memory_db.changes_since(pushed_until)
    reply = _call(conf, "POST", "/api/sync", {"since": pulled_until, "changes": local})
    got = memory_db.apply_changes(reply.get("changes") or {})
    memory_db.meta("cloud_pushed", str(now))
    memory_db.meta("cloud_pulled", str(reply.get("now") or now))
    return len(local["items"]) + len(local["deleted"]), got


def pending_jobs(settings) -> list[dict]:
    conf = config(settings)
    return _call(conf, "GET", "/api/queue?status=bekliyor").get("jobs", []) if conf else []


def finish_job(settings, job_id: str, status: str, result: str = "") -> None:
    """status: alindi (üzerinde çalışılıyor) · bitti · reddedildi."""
    conf = config(settings)
    if conf:
        _call(conf, "POST", f"/api/queue/{job_id}", {"status": status, "result": result})
