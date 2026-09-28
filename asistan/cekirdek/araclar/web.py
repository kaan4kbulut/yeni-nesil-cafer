"""Web araçları: arama (DuckDuckGo, `ddgs`) ve sayfa okuma (httpx + BeautifulSoup; tarayıcı motoru gerekmez).

Tarayıcı otomasyonu (Playwright) ağır bağımlılık: çekirdekte değil, `browser.py`'de ve isteğe bağlı.
"""

import ipaddress
import socket
from urllib.parse import urlsplit

import httpx
from bs4 import BeautifulSoup

from .temel import AracHatasi

TARAYICI_KIMLIGI = "Mozilla/5.0 (X11; Linux x86_64) yeni-nesil-cafer"
_GURULTU = ["script", "style", "nav", "footer", "header", "noscript", "svg"]
EN_COK_BAYT = 2_000_000  # okunan gövde sınırı (modele gidecek metin zaten kısa; sınırsız indirme yok)
KESILDI_NOTU = "\n\n[… sayfa gövdesi sınırı aştığı için kesildi]"


def _adres_denetle(url: str) -> None:
    """Yerel ve özel ağ adresleri (localhost, 127/8, 10/8, 172.16/12, 192.168/16, link-local, ::1) okunamaz: model
    Ollama API'sine, yönlendirici paneline ya da bulut meta veri servisine (169.254.169.254) bu araçla ulaşamaz."""
    ana = (urlsplit(url).hostname or "").strip("[]").lower()
    if not ana:
        raise AracHatasi("Invalid URL: no host")
    if ana == "localhost" or ana.endswith(".localhost") or ana.endswith(".local"):
        raise AracHatasi(f"{ana}: local addresses cannot be read with web_fetch (private/local network).")
    try:
        adresler = {bilgi[4][0] for bilgi in socket.getaddrinfo(ana, None)}
    except socket.gaierror:
        raise AracHatasi(f"Could not resolve {ana}. Check the address or the internet connection.") from None
    for a in adresler:
        ip = ipaddress.ip_address(a.split("%")[0])
        if ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved or ip.is_multicast or ip.is_unspecified:
            raise AracHatasi(f"{ana} ({a}) is a local/private network address and cannot be read with web_fetch.")


def _indir(url: str) -> tuple[str, str]:
    """(içerik türü, metin): gövde en çok EN_COK_BAYT; fazlası atılır ve nota düşülür."""
    try:
        with httpx.stream("GET", url, follow_redirects=True, timeout=30, headers={"User-Agent": TARAYICI_KIMLIGI}) as resp:
            if resp.status_code >= 400:
                raise AracHatasi(f"HTTP {resp.status_code}: the page could not be fetched ({url}). "
                                 "Try another URL or use web_search.")
            parcalar, toplam, kesildi = [], 0, False
            for parca in resp.iter_bytes(65536):
                if toplam + len(parca) > EN_COK_BAYT:
                    parcalar.append(parca[:EN_COK_BAYT - toplam])
                    kesildi = True
                    break
                parcalar.append(parca)
                toplam += len(parca)
            tur = resp.headers.get("content-type", "html")
    except httpx.HTTPError as e:
        raise AracHatasi(f"Could not reach {url} ({type(e).__name__}). Check the address or the internet "
                         "connection.") from None
    metin = b"".join(parcalar).decode("utf-8", "replace")
    return tur, metin + (KESILDI_NOTU if kesildi else "")


def ara(sorgu: str, en_cok: int = 5) -> str:
    from ddgs import DDGS

    try:
        sonuclar = DDGS().text(sorgu, max_results=min(max(en_cok, 1), 10))
    except Exception as e:  # ağ yok, hız sınırı, sonuç yok…
        if "no results" in str(e).lower():
            return "No results."
        raise AracHatasi(f"Web search failed ({type(e).__name__}). Check the internet connection or retry with a "
                         "different query.") from None
    if not sonuclar:
        return "No results."
    return "\n\n".join(f"{r['title']}\n{r['href']}\n{r['body']}" for r in sonuclar)


def sayfa_metni(html: str) -> tuple[str, str]:
    """HTML → (başlık, gövde metni); betik, stil, menü gibi gürültü atılır."""
    soup = BeautifulSoup(html, "html.parser")
    for etiket in soup(_GURULTU):
        etiket.decompose()
    baslik = soup.title.get_text(strip=True) if soup.title else ""
    if soup.title:
        soup.title.decompose()  # başlık metinde bir daha geçmesin (üstte ayrıca yazılıyor)
    satirlar = [satir.strip() for satir in soup.get_text("\n").splitlines()]
    return baslik, "\n".join(satir for satir in satirlar if satir)


def oku(url: str) -> str:
    if not url.startswith(("http://", "https://")):
        raise AracHatasi("Only http(s) URLs are supported")
    _adres_denetle(url)
    tur, govde = _indir(url)
    if "html" not in tur:
        return govde
    kesildi = govde.endswith(KESILDI_NOTU)
    baslik, metin = sayfa_metni(govde.removesuffix(KESILDI_NOTU))
    return (f"{baslik}\n\n{metin}" if baslik else metin) + (KESILDI_NOTU if kesildi else "")
