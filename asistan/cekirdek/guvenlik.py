"""Güvenlik politikası (MIMARI §10): kurulum, ağ, silme, sandbox süresi, kurulum kaynakları.

Tek izin hattı kuralı (CLAUDE.md) korunur: burası ikinci bir onay yolu AÇMAZ; politikayı okur ve `permissions.decide`'a
"bu çağrı politikayla yasak / politikayla serbest / hat karar versin" der. Kaynak: `asistan/ayar/guvenlik.toml`
(programla gelir) ← `ayar.toml → [guvenlik]` ← `CAFER_GUVENLIK_*`.
"""

import tomllib
from functools import cache
from pathlib import Path

from . import ayar

DOSYA = Path(__file__).resolve().parent.parent / "ayar" / "guvenlik.toml"
KURULUM = ("sor", "otomatik", "yasak")
AG = ("serbest", "sor")
DOSYA_SILME = ("sor", "yasak")
# hangi araçlar hangi politikaya bağlı (araç adı → politika anahtarı); yetenekler risk/izinden çözülür
KURULUM_ARACLARI = {"install_python_package", "install_app", "f_install_packages", "mcp_kur"}
AG_ARACLARI = {"web_search", "fetch_url", "call_api", "browser_open", "browser_type", "browser_click", "browser_extract_items"}
SILME_ARACLARI = {"delete_file", "delete_path"}


@cache
def _dosyadan() -> dict:
    try:
        with DOSYA.open("rb") as f:
            return dict(tomllib.load(f).get("guvenlik") or {})
    except (OSError, tomllib.TOMLDecodeError):
        return {}


def politika() -> dict:
    """Etkin politika (düz sözlük): guvenlik.toml ← ayar.toml [guvenlik] ← CAFER_GUVENLIK_*."""
    p = {"kurulum": "sor", "ag": "serbest", "dosya_silme": "sor", "sandbox_zaman_asimi_sn": 60,
         "uretilen_sandbox_calistirma": 5, "kaynaklar": ["pypi"]}
    p.update(_dosyadan())
    acik = ayar.acik_degerler()
    for anahtar in list(p):
        if f"guvenlik.{anahtar}" in acik:
            p[anahtar] = acik[f"guvenlik.{anahtar}"]
    if p["kurulum"] not in KURULUM:
        p["kurulum"] = "sor"
    if p["ag"] not in AG:
        p["ag"] = "serbest"
    if p["dosya_silme"] not in DOSYA_SILME:
        p["dosya_silme"] = "sor"
    p["sandbox_zaman_asimi_sn"] = max(1, int(p["sandbox_zaman_asimi_sn"] or 60))
    p["kaynaklar"] = [str(k).lower() for k in (p["kaynaklar"] or [])]
    return p


def kurulum() -> str:
    """Kurulum politikası; düşük kademede ve sunucuda "otomatik" olsa da "sor" (MIMARI §10)."""
    from . import profil

    k = politika()["kurulum"]
    if k == "otomatik" and (profil.kademe() in ("dusuk", "sunucu") or profil.basliksiz()):
        return "sor"
    return k


def kaynak_izinli(kaynak: str) -> bool:
    """Kurulum kaynağı allowlist'te mi (pypi, flathub, winget, brew, apt, npm, cafer-yetenekler)? Rastgele URL: hayır."""
    return str(kaynak or "").lower() in politika()["kaynaklar"]


def sandbox_zaman_asimi() -> int:
    return politika()["sandbox_zaman_asimi_sn"]


def karar(ad: str, args: dict | None = None, izinler=()) -> tuple[str | None, str]:
    """Politikanın bu araç çağrısı için sözü: ("yasak", neden) · ("izin", neden) · (None, "") = hat kendi kuralıyla
    karar verir. `izinler`: sandbox yeteneğinin manifest izinleri (`y_<ad>` için)."""
    p = politika()
    izin = set(izinler or ())
    if ad in KURULUM_ARACLARI:
        k = kurulum()
        if k == "yasak":
            return "yasak", "kurulum politikayla kapalı (guvenlik.toml → kurulum = \"yasak\")"
        if k == "otomatik":
            return "izin", "kurulum politikayla otomatik"
        return None, ""
    if ad in SILME_ARACLARI or "dosya_sil" in izin:
        if p["dosya_silme"] == "yasak":
            return "yasak", "dosya silme politikayla kapalı"
        return None, ""
    if ad in AG_ARACLARI or "ag" in izin:
        if p["ag"] == "sor":
            return "sor", "ağ politikası: internete giden her çağrı sorulur"
        return None, ""
    return None, ""


def temizle() -> None:
    """Testler: toml önbelleğini boşalt."""
    _dosyadan.cache_clear()
