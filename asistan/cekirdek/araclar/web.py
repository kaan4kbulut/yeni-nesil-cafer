"""Web araçları: arama (DuckDuckGo, `ddgs`) ve sayfa okuma (httpx + BeautifulSoup; tarayıcı motoru gerekmez).

Tarayıcı otomasyonu (Playwright) ağır bağımlılık: çekirdekte değil, `browser.py`'de ve isteğe bağlı.
"""

import contextlib
import ipaddress
import socket
from urllib.parse import urljoin, urlsplit

import httpx
from bs4 import BeautifulSoup

from .temel import AracHatasi

TARAYICI_KIMLIGI = "Mozilla/5.0 (X11; Linux x86_64) yeni-nesil-cafer"
_GURULTU = ["script", "style", "nav", "footer", "header", "noscript", "svg"]
EN_COK_BAYT = 2_000_000  # okunan gövde sınırı (modele gidecek metin zaten kısa; sınırsız indirme yok)
KESILDI_NOTU = "\n\n[… sayfa gövdesi sınırı aştığı için kesildi]"


_CGNAT = ipaddress.ip_network("100.64.0.0/10")  # taşıyıcı NAT: `is_private` saymıyor ama yerel ağdır
EN_COK_YONLENDIRME = 5


def _adres_denetle(url: str) -> str:
    """Yerel ve özel ağ adresleri (localhost, 127/8, 10/8, 172.16/12, 192.168/16, 100.64/10, link-local, ::1) okunamaz:
    model Ollama API'sine, yönlendirici paneline ya da bulut meta veri servisine (169.254.169.254) bu araçla ulaşamaz.
    Denetlenen ilk adresi döner; `_indir` o adrese bağlanır (K12-B4: ikinci bir DNS çözümlemesi yok — rebinding kapalı)."""
    ana = (urlsplit(url).hostname or "").strip("[]").lower()
    if not ana:
        raise AracHatasi("Invalid URL: no host")
    if ana == "localhost" or ana.endswith(".localhost") or ana.endswith(".local"):
        raise AracHatasi(f"{ana}: local addresses cannot be read with web_fetch (private/local network).")
    try:
        ipaddress.ip_address(ana)
        adresler = [ana]  # IP literali: çözümleme yok, doğrudan denetlenir
    except ValueError:
        try:
            adresler = [bilgi[4][0] for bilgi in socket.getaddrinfo(ana, None)]
        except socket.gaierror:
            raise AracHatasi(f"Could not resolve {ana}. Check the address or the internet connection.") from None
    for a in dict.fromkeys(adresler):
        ip = ipaddress.ip_address(a.split("%")[0])
        if (ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved or ip.is_multicast or ip.is_unspecified
                or ip in _CGNAT):
            raise AracHatasi(f"{ana} ({a}) is a local/private network address and cannot be read with web_fetch.")
    return adresler[0]


def _sabit_istek(url: str, ip: str) -> tuple[str, dict, dict]:
    """URL'nin sunucu adını denetlenen IP ile değiştirir; asıl ad `Host` başlığı ve TLS SNI olarak gider."""
    p = urlsplit(url)
    ana = (p.hostname or "").strip("[]")
    ip_metni = f"[{ip}]" if ":" in ip else ip
    netloc = ip_metni + (f":{p.port}" if p.port else "")
    hedef = p._replace(netloc=netloc).geturl()
    host = ana + (f":{p.port}" if p.port else "")
    ek = {"sni_hostname": ana} if p.scheme == "https" else {}
    return hedef, {"User-Agent": TARAYICI_KIMLIGI, "Host": host}, ek


@contextlib.contextmanager
def _akis(hedef: str, basliklar: dict, ek: dict):
    """Tek GET akışı (`sni_hostname` uzantısı yalnızca `Client.stream`'de; üst düzey `httpx.stream` almıyor)."""
    with httpx.Client(follow_redirects=False, timeout=30) as istemci, \
            istemci.stream("GET", hedef, headers=basliklar, extensions=ek) as resp:
        yield resp


def _indir(url: str) -> tuple[str, str]:
    """(içerik türü, metin): gövde en çok EN_COK_BAYT; fazlası atılır ve nota düşülür. Yönlendirmeler elle izlenir ve
    her hedef `_adres_denetle`'den geçer (K12-B4: `follow_redirects=True` özel ağa denetimsiz gidiyordu)."""
    ip = _adres_denetle(url)
    for _ in range(EN_COK_YONLENDIRME + 1):
        hedef, basliklar, ek = _sabit_istek(url, ip)
        try:
            with _akis(hedef, basliklar, ek) as resp:
                if 300 <= resp.status_code < 400 and resp.headers.get("location"):
                    url = urljoin(url, resp.headers["location"])
                    if not url.startswith(("http://", "https://")):
                        raise AracHatasi(f"Redirected to an unsupported address: {url[:80]}")
                    ip = _adres_denetle(url)
                    continue
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
    raise AracHatasi(f"Too many redirects ({EN_COK_YONLENDIRME}) while fetching {url}")


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
    tur, govde = _indir(url)  # adres denetimi (ilk ve yönlendirilen her adres) _indir içinde
    if "html" not in tur:
        return govde
    kesildi = govde.endswith(KESILDI_NOTU)
    baslik, metin = sayfa_metni(govde.removesuffix(KESILDI_NOTU))
    return (f"{baslik}\n\n{metin}" if baslik else metin) + (KESILDI_NOTU if kesildi else "")
