"""Eksik bağımlılık kurma (MIMARI §7 `eksik_bagimlilik` → `yukleyici.py`): pip paketi, program (ikili), MCP sunucusu.

Kurulum tek araç yolundan gider: `arac("install_python_package", …)` → `Agent._execute_tool` → `permissions.decide`
(politika `guvenlik.kurulum`: yasak → ret, otomatik → izin, sor → kullanıcı/güvenlik ajanı) → `libraries.install`
(ajanın kütüphane klasörü; sandbox yeteneklerinin PYTHONPATH'inde). Burası kendi başına hiçbir şey kurmaz.
"""

import json
import re
from pathlib import Path

from .. import guvenlik
from . import YetenekHatasi

_PAKET = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._\-]*(\[[A-Za-z0-9,_\-]+\])?([<>=!~]=?[A-Za-z0-9.*]+(,[<>=!~]=?[A-Za-z0-9.*]+)*)?$")
# MCP sunucusu allowlist: yalnızca paket yöneticisinden (npm/PyPI) bilinen önekle; rastgele komut ya da URL yok
_MCP_KOMUT = {"npx": re.compile(r"^(-y|@modelcontextprotocol/server-[a-z0-9\-]+|mcp-server-[a-z0-9\-]+)$"),
              "uvx": re.compile(r"^mcp-server-[a-z0-9\-]+$")}


def hedef_coz(hedef: str) -> tuple[str, str]:
    """`pip:openpyxl` → ("pip", "openpyxl"); `ikili:ffmpeg`; `mcp:zaman`. Bilinmeyen: ("", hedef)."""
    tur, _, ad = (hedef or "").partition(":")
    return (tur, ad) if ad and tur in ("pip", "ikili", "mcp") else ("", hedef or "")


def kur(hedef: str, arac, amac: str = "") -> str:
    """Hedefi kurar; sonuç metni döner. `arac(ad, args) -> str`: programın tek araç yolu (izin hattı burada sorar;
    hat reddederse/beklerse `YetenekHatasi("izin")`). Politika `yasak` ise hiç denenmez."""
    tur, ad = hedef_coz(hedef)
    if not tur:
        raise YetenekHatasi("veri", f"kurulacak hedef anlaşılamadı: {hedef}")
    if guvenlik.kurulum() == "yasak":
        raise YetenekHatasi("izin", "kurulum politikayla kapalı (guvenlik.toml → kurulum)")
    if tur == "pip":
        if not _PAKET.match(ad):
            raise YetenekHatasi("veri", f"geçersiz paket adı: {ad}")
        if not guvenlik.kaynak_izinli("pypi"):
            raise YetenekHatasi("izin", "PyPI kurulum kaynakları listesinde değil")
        return str(arac("install_python_package", {"packages": ad, "purpose": amac or f"eksik bağımlılık: {ad}"}))
    if tur == "ikili":
        # kullanıcı düzeyinde program kurma yolu (apps.install) masaüstü uygulamaları içindir; komut satırı programı
        # sistem paket yöneticisi ister → kullanıcıya bırakılır (MIMARI §7 izin/eksik: net soru)
        raise YetenekHatasi("izin", f"'{ad}' programı kurulu değil; bilgisayara yönetici olarak kurulması gerekiyor "
                                    "(Ayarlar → Uygulamalar'dan kurulabilirse oradan).")
    return mcp_ekle(ad, json.loads(amac) if amac.strip().startswith("{") else {})


def mcp_ekle(ad: str, tanim: dict, dosya: Path | None = None) -> str:
    """Hazır MCP sunucusunu `mcp.json`'a ekler (allowlist: `npx -y @modelcontextprotocol/server-*`, `uvx mcp-server-*`).
    Sunucu bir sonraki `mcp.reload` ile başlar; araçları kayda o zaman girer."""
    if not re.fullmatch(r"[a-z0-9_\-]+", ad or ""):
        raise YetenekHatasi("veri", f"geçersiz MCP sunucu adı: {ad}")
    komut, args = str(tanim.get("command") or ""), [str(a) for a in tanim.get("args") or []]
    desen = _MCP_KOMUT.get(komut)
    if desen is None or not args or not all(desen.match(a) for a in args):
        raise YetenekHatasi("izin", f"MCP sunucusu allowlist dışında: {komut} {' '.join(args)}")
    if not guvenlik.kaynak_izinli("npm" if komut == "npx" else "pypi"):
        raise YetenekHatasi("izin", "MCP kaynağı kurulum kaynakları listesinde değil")
    if dosya is None:
        from ... import mcp

        dosya = Path(mcp.CONFIG_FILE)
    try:
        veri = json.loads(dosya.read_text(encoding="utf-8")) if dosya.exists() else {}
    except ValueError:
        raise YetenekHatasi("veri", "mcp.json bozuk; düzeltilmeden sunucu eklenemez") from None
    sunucular = veri.setdefault("mcpServers", {}) if isinstance(veri, dict) else None
    if sunucular is None:
        raise YetenekHatasi("veri", "mcp.json beklenen biçimde değil")
    if ad in sunucular:
        return f"{ad} zaten mcp.json'da"
    sunucular[ad] = {"command": komut, "args": args}
    dosya.parent.mkdir(parents=True, exist_ok=True)
    dosya.write_text(json.dumps(veri, indent=2, ensure_ascii=False), encoding="utf-8")
    return f"{ad} MCP sunucusu mcp.json'a eklendi; bir sonraki bağlantı yenilemesinde başlar"
