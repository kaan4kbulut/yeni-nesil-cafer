"""Bildirim (K9): onay bekleyen görev ve bitişler telefona — ntfy (`ayar.toml → [bildirim] ntfy_konu`) ve/veya
eşleşmiş Telegram sohbeti (`bulut.json`). Yapılandırılmamışsa sessiz; hiçbir hata programı durdurmaz.

Model bunu `send_notification` aracıyla (izin hattından, `calistirir`) çağırır; program onay beklerken kendisi çağırır
(`onay_bekliyor`, arka planda)."""

import logging
import threading

import httpx

from . import ayar

_gunluk = logging.getLogger(__name__)
ZAMAN = httpx.Timeout(15, connect=5)


def _telegram() -> dict:
    """Eşleşmiş Telegram sohbeti (cloud_server bulut.json): {token, chat} ya da boş."""
    if not ayar.deger("bildirim.telegram", True):
        return {}
    try:
        from .. import cloud_server

        conf = cloud_server.load_config()
    except Exception:
        return {}
    if conf.get("telegram_token") and conf.get("telegram_chat"):
        return {"token": conf["telegram_token"], "chat": int(conf["telegram_chat"])}
    return {}


def kanallar() -> list[str]:
    """Yapılandırılmış kanallar: ["ntfy", "telegram"] alt kümesi."""
    k = []
    if str(ayar.deger("bildirim.ntfy_konu") or "").strip():
        k.append("ntfy")
    if _telegram():
        k.append("telegram")
    return k


def ayarli() -> bool:
    return bool(kanallar())


KONU_EN_AZ = 12  # K12-A13: ntfy.sh'ta konuyu bilen herkes okur; kısa/sözlük konu tahmin edilir


def gonder(baslik: str, metin: str, oncelik: str = "default", istemci=None, gizli: str = "") -> str:
    """Bütün kanallara gönderir; "ntfy ✓, telegram ✗ (neden)" gibi özet döner. Kanal yoksa "bildirim ayarlanmadı".
    `gizli`: yalnızca özel kanala (Telegram) giden ek metin (istek içeriği); herkese açık ntfy sunucusuna gitmez."""
    sonuc = []
    konu = str(ayar.deger("bildirim.ntfy_konu") or "").strip()
    post = (istemci or httpx).post
    if konu and len(konu) < KONU_EN_AZ:
        sonuc.append(f"ntfy ⚠ konu kısa (tahmin edilebilir; en az {KONU_EN_AZ} karakter, rastgele olsun)")
    if konu:
        sunucu = str(ayar.deger("bildirim.ntfy_sunucu") or "https://ntfy.sh").rstrip("/")
        try:
            r = post(f"{sunucu}/{konu}", content=metin.encode("utf-8"), timeout=ZAMAN,
                     headers={"Title": baslik.encode("utf-8").decode("latin-1", "replace"), "Priority": oncelik,
                              "Tags": "robot"})
            sonuc.append("ntfy ✓" if r.status_code < 300 else f"ntfy ✗ ({r.status_code})")
        except Exception as e:
            sonuc.append(f"ntfy ✗ ({type(e).__name__})")
    tg = _telegram()
    if tg:
        try:
            r = post(f"https://api.telegram.org/bot{tg['token']}/sendMessage", timeout=ZAMAN,
                     json={"chat_id": tg["chat"], "text": f"{baslik}\n{metin}" + (f"\n{gizli}" if gizli else "")[:4000]})
            sonuc.append("telegram ✓" if r.status_code < 300 else f"telegram ✗ ({r.status_code})")
        except Exception as e:
            sonuc.append(f"telegram ✗ ({type(e).__name__})")
    return ", ".join(sonuc) or "bildirim ayarlanmadı (ayar.toml → [bildirim] ntfy_konu ya da Telegram eşleşmesi)"


def arka_planda(baslik: str, metin: str, gizli: str = "") -> None:
    """Programın kendi bildirimi (onay bekliyor, görev bitti): kanal yoksa hiç iş parçacığı açılmaz."""
    if not ayarli():
        return

    def kos():
        try:
            _gunluk.info("bildirim: %s", gonder(baslik, metin, "high", gizli=gizli))
        except Exception as e:  # asla yukarı çıkmaz
            _gunluk.info("bildirim gönderilemedi: %s", e)

    threading.Thread(target=kos, daemon=True).start()


def onay_bekliyor(gorev: dict) -> None:
    """Onay bekleyen görev: ne bekliyor + istek özeti (yürütücü `_bekle` ve eksik yetenek onayında)."""
    if not ayarli():
        return
    ne = ""
    if gorev.get("bekleyen_uretim"):
        ne = f"yetenek üretimi: {gorev['bekleyen_uretim'].get('ad')}"
    else:
        a = next((a for a in gorev.get("adimlar") or [] if a.get("durum") == "bekliyor_onay"), {})
        b = a.get("bekleyen") or {}
        ne = (f"kurulum: {b.get('hedef')}" if b.get("tip") == "kur" else f"yetenek üretimi: {b.get('ad')}" if b
              else f"adım {a.get('id')}: {a.get('amac', '')}")
    # K12-A13: istek metni (kişisel içerik) yalnızca özel kanala; ntfy'ye adım/görev kimliği
    arka_planda("Onay bekliyor — YENİ NESİL CAFER", f"{ne}\nGörev: {gorev.get('gorev_id')}",
                gizli=f"İş: {str(gorev.get('istek', ''))[:200]}")
