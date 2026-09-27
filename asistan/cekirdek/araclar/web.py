"""Web araçları: arama (DuckDuckGo, `ddgs`) ve sayfa okuma (httpx + BeautifulSoup; tarayıcı motoru gerekmez).

Tarayıcı otomasyonu (Playwright) ağır bağımlılık: çekirdekte değil, `browser.py`'de ve isteğe bağlı.
"""

import httpx
from bs4 import BeautifulSoup

from .temel import AracHatasi

TARAYICI_KIMLIGI = "Mozilla/5.0 (X11; Linux x86_64) yeni-nesil-cafer"
_GURULTU = ["script", "style", "nav", "footer", "header", "noscript", "svg"]


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
    try:
        resp = httpx.get(url, follow_redirects=True, timeout=30, headers={"User-Agent": TARAYICI_KIMLIGI})
    except httpx.HTTPError as e:
        raise AracHatasi(f"Could not reach {url} ({type(e).__name__}). Check the address or the internet "
                         "connection.") from None
    if resp.status_code >= 400:
        raise AracHatasi(f"HTTP {resp.status_code}: the page could not be fetched ({url}). "
                         "Try another URL or use web_search.")
    if "html" not in resp.headers.get("content-type", "html"):
        return resp.text
    baslik, metin = sayfa_metni(resp.text)
    return f"{baslik}\n\n{metin}" if baslik else metin
