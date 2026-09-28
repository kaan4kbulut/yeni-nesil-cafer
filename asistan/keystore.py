"""API anahtarlarının saklanması: sistem anahtar zinciri (KDE Cüzdanı / Secret Service).

Anahtar zinciri kullanılamazsa yalnızca kullanıcının okuyabildiği bir JSON dosyasına düşer.
"""

import json

from .config import CONFIG_DIR

SERVICE = "yeni-nesil-cafer"
OLD_SERVICE = "yerel-asistan"  # 2.2'ye kadarki ad: anahtar yeni adla yoksa buradan okunup yeni ada kopyalanır
FALLBACK_FILE = CONFIG_DIR / "anahtarlar.json"

try:
    import keyring
except ImportError:  # paket kurulu değilse dosyaya düş
    keyring = None


def _read_fallback() -> dict:
    try:
        return json.loads(FALLBACK_FILE.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def _write_fallback(data: dict) -> None:
    from .cekirdek.ayar import atomik_yaz

    atomik_yaz(FALLBACK_FILE, json.dumps(data, indent=2), mod=0o600)  # K12-C1: anahtarlar yarım dosyada kaybolmasın


def backend_name() -> str:
    if keyring is None:
        return "dosya"
    try:
        name = type(keyring.get_keyring()).__module__
    except Exception:
        return "dosya"
    return "dosya" if "fail" in name or "null" in name else "sistem anahtar zinciri"


def get_secret(key_id: str) -> str:
    if keyring is not None:
        try:
            value = keyring.get_password(SERVICE, key_id)
            if value:
                return value
            value = keyring.get_password(OLD_SERVICE, key_id)
            if value:
                keyring.set_password(SERVICE, key_id, value)  # bir kez taşınır
                return value
        except Exception:
            pass
    return _read_fallback().get(key_id, "")


def set_secret(key_id: str, value: str) -> None:
    if not value:
        delete_secret(key_id)
        return
    if keyring is not None:
        try:
            keyring.set_password(SERVICE, key_id, value)
            # daha önce dosyaya düşmüşse oradan temizle
            data = _read_fallback()
            if data.pop(key_id, None) is not None:
                _write_fallback(data)
            return
        except Exception:
            pass
    data = _read_fallback()
    data[key_id] = value
    _write_fallback(data)


def delete_secret(key_id: str) -> None:
    if keyring is not None:
        try:
            keyring.delete_password(SERVICE, key_id)
        except Exception:  # zaten yoksa da hata verir
            pass
    data = _read_fallback()
    if data.pop(key_id, None) is not None:
        _write_fallback(data)
