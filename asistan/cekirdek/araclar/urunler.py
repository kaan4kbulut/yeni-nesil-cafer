"""Sayfadaki ürün/ilan listesini yapısal okuma: [{ad, fiyat, para_birimi, url}] (eski Aşama 4, `extract_items`).

Sıra: 1) JSON-LD (schema.org `ItemList` / `Product` / `Offer`) — büyük e-ticaret siteleri bunu veriyor; 2) DOM sezgisi:
aynı yapıda (etiket + sınıf) tekrar eden kardeş kartlar, kartta fiyat deseni ve bir bağlantı → ad; 3) hiçbiri yoksa
boş liste — çağıran dürüstçe "liste bulunamadı" der, uydurma yok. Siteye özel seçici yok (site adına göre dal yok).
Saf fonksiyon (HTML metni → liste): tarayıcı her çağrıda DOM'u yeniden okuyup buraya verir; öğe numarası kullanılmaz.
"""

import json
import re
from collections import deque
from urllib.parse import urljoin

from bs4 import BeautifulSoup

EN_COK = 60
_PARA = {"TL": "TRY", "₺": "TRY", "TRY": "TRY", "$": "USD", "USD": "USD", "€": "EUR", "EUR": "EUR", "£": "GBP",
         "GBP": "GBP"}
# 1.299,90 TL · 1299 TL · ₺1.299,90 · 12,50 € · £51.77 · $1,299.90 — binlik ayırıcı üç haneli gruplar, ondalık sonda
# 1-2 hane ("1.299" Türk biçimiyle 1299 sayılır)
_SAYI = r"(\d{1,3}(?:[.,]\d{3})+|\d+)(?:[.,](\d{1,2}))?"
_FIYAT = re.compile(rf"(?<![\d.,]){_SAYI}\s*(TL|₺|TRY|€|EUR|\$|USD|£|GBP)(?![A-Za-z])|(₺|\$|€|£)\s*{_SAYI}(?![\d])")
_TAKSIT = re.compile(r"(\d+\s*[xX×]\s*$)|taksit|/\s*ay\b|aylık", re.I)


def sayi(tam: str, ondalik: str | None) -> float:
    return float(re.sub(r"[.,]", "", tam) + (f".{ondalik}" if ondalik else ""))


def fiyatlar(metin: str) -> list[tuple[float, str]]:
    """Metindeki fiyatlar [(tutar, para birimi)]; taksit tutarları ("3 x 433 TL", "aylık") atlanır."""
    bulunan = []
    for m in _FIYAT.finditer(metin or ""):
        once, sonra = metin[max(0, m.start() - 12):m.start()], metin[m.end():m.end() + 8]
        if _TAKSIT.search(once) or _TAKSIT.search(sonra):
            continue
        if m.group(1):
            tutar, birim = sayi(m.group(1), m.group(2)), m.group(3)
        else:
            tutar, birim = sayi(m.group(5), m.group(6)), m.group(4)
        if tutar > 0:
            bulunan.append((tutar, _PARA.get(birim, birim)))
    return bulunan


def _sade(metin) -> str:
    return " ".join(str(metin or "").split())[:200]


# ---------------------------------------------------------------- 1) JSON-LD

def _ld_nesneleri(soup) -> list:
    nesneler = []
    for betik in soup.find_all("script", type=re.compile(r"ld\+json", re.I)):
        try:
            veri = json.loads(betik.string or betik.get_text() or "")
        except ValueError:
            continue
        kuyruk = deque([veri])  # kuyruk: sayfadaki sıra korunur (site "en ucuz önce" sıralamış olabilir)
        while kuyruk:
            n = kuyruk.popleft()
            if isinstance(n, list):
                kuyruk.extend(n)
            elif isinstance(n, dict):
                nesneler.append(n)
                for k in ("@graph", "itemListElement", "item", "mainEntity", "hasVariant"):
                    if isinstance(n.get(k), (list, dict)):
                        kuyruk.append(n[k])
    return nesneler


def _turler(n: dict) -> set:
    t = n.get("@type")
    return {str(x) for x in (t if isinstance(t, list) else [t]) if x}


def _teklif(teklifler) -> tuple[float | None, str]:
    for o in teklifler if isinstance(teklifler, list) else [teklifler]:
        if not isinstance(o, dict):
            continue
        ham = o.get("price", o.get("lowPrice"))
        if ham is None and isinstance(o.get("priceSpecification"), dict):
            ham = o["priceSpecification"].get("price")
        try:
            tutar = float(str(ham).replace(",", ".")) if ham not in (None, "") else None
        except ValueError:
            bulunan = fiyatlar(str(ham) + " TL")
            tutar = bulunan[0][0] if bulunan else None
        if tutar:
            return tutar, str(o.get("priceCurrency") or "TRY")
    return None, ""


def json_ld(soup, taban: str) -> list[dict]:
    liste = []
    for n in _ld_nesneleri(soup):
        if not _turler(n) & {"Product", "Offer", "IndividualProduct", "ProductModel", "Car", "Vehicle"}:
            continue
        ad = n.get("name")
        if not ad and isinstance(n.get("itemOffered"), dict):  # Offer: ad sunulan üründe
            ad = n["itemOffered"].get("name")
        ad = _sade(ad)
        tutar, birim = _teklif(n.get("offers") if "Offer" not in _turler(n) else n)
        if ad and tutar:
            liste.append({"ad": ad, "fiyat": tutar, "para_birimi": birim,
                          "url": urljoin(taban, str(n.get("url") or "")) if n.get("url") else ""})
    return liste


# ---------------------------------------------------------------- 2) DOM sezgisi

def _imza(e) -> tuple:
    return e.name, tuple(sorted(c for c in (e.get("class") or []) if not re.search(r"\d{3,}", c)))


def _fiyat_dugumleri(soup) -> list:
    """Fiyat içeren en küçük öğeler."""
    dugumler = []
    for e in soup.find_all(string=_FIYAT):
        ust = e.parent
        if ust is not None and ust.name not in ("script", "style", "noscript", "title"):
            dugumler.append(ust)
    return dugumler


def _baglanti(kart):
    """Kartın bağlantısı: kartın kendisi (`<a class="product-card" href>`) ya da içindeki ilk bağlantı."""
    if kart.name == "a" and kart.get("href"):
        return kart
    return kart.find("a", href=True)


def _kart(fiyat_dugumu, en_cok_duzey: int = 10):
    """Fiyattan yukarı çıkarak tekrar eden kardeşleri olan ve bağlantı içeren (ya da bağlantı olan) ilk ata (kart)."""
    e = fiyat_dugumu
    for _ in range(en_cok_duzey):
        ust = e.parent
        if ust is None or ust.name in ("body", "html", "[document]"):
            return None
        imza = _imza(e)
        kardes = [k for k in ust.find_all(recursive=False) if _imza(k) == imza]
        if len(kardes) >= 2 and _baglanti(e) is not None:
            return e
        e = ust
    return None


_AD_SINIFI = re.compile(r"name|title|baslik|başlık|isim|desc", re.I)


def _kart_ad(kart) -> str:
    """Öncelik: bağlantı `title`'ı, başlıklar, sınıfında name/title geçen öğeler → resim `alt` → bağlantı metni."""
    baglantilar = ([kart] if kart.name == "a" else []) + kart.find_all("a", href=True)
    gruplar = [
        [a.get("title") or "" for a in baglantilar]
        + [h.get_text(" ", strip=True) for h in kart.find_all(["h1", "h2", "h3", "h4", "h5"])]
        + [e.get_text(" ", strip=True) for e in kart.find_all(class_=_AD_SINIFI)],
        [img.get("alt") or "" for img in kart.find_all("img")],
        [a.get_text(" ", strip=True) for a in baglantilar],
    ]
    for adaylar in gruplar:
        temiz = [_sade(re.sub(_FIYAT, "", x)) for x in adaylar]
        temiz = [x for x in temiz if len(x) >= 3 and not re.fullmatch(r"[\d\s.,%₺$€£TLx×-]+", x)]
        if temiz:
            return max(temiz, key=len)
    return ""


def dom_sezgisi(soup, taban: str) -> list[dict]:
    gruplar: dict = {}
    for d in _fiyat_dugumleri(soup):
        kart = _kart(d)
        if kart is not None:
            gruplar.setdefault((id(kart.parent), _imza(kart)), (kart.parent, _imza(kart)))
    en_iyi: list[dict] = []
    for ust, imza in gruplar.values():
        liste = []
        for kart in ust.find_all(recursive=False):
            if _imza(kart) != imza:
                continue
            bulunan = fiyatlar(kart.get_text(" ", strip=True))
            ad = _kart_ad(kart)
            a = _baglanti(kart)
            if bulunan and ad:
                tutar, birim = min(bulunan)  # eski/indirimli çiftinde satış fiyatı küçük olandır
                liste.append({"ad": ad, "fiyat": tutar, "para_birimi": birim,
                              "url": urljoin(taban, a["href"]) if a is not None else ""})
        if len(liste) > len(en_iyi):
            en_iyi = liste
    return en_iyi if len(en_iyi) >= 2 else []


# ---------------------------------------------------------------- giriş

def cikar(html: str, taban_url: str = "", en_cok: int = EN_COK) -> tuple[list[dict], str]:
    """(öğeler, yöntem). Yöntem "json-ld" · "dom" · "" (bulunamadı)."""
    soup = BeautifulSoup(html or "", "html.parser")
    ld = json_ld(soup, taban_url)
    for gurultu in soup(["script", "style", "noscript", "svg"]):
        gurultu.decompose()
    dom = dom_sezgisi(soup, taban_url)
    liste, yontem = (ld, "json-ld") if len(ld) >= max(2, len(dom)) or (ld and not dom) else (dom, "dom" if dom else "")
    gorulen, tekil = set(), []
    for o in liste:
        anahtar = (o["ad"].casefold(), o["fiyat"], o["url"])
        if anahtar not in gorulen:
            gorulen.add(anahtar)
            tekil.append(o)
    return tekil[:max(1, en_cok)], yontem if tekil else ""


def suz(liste: list[dict], kelimeler: str) -> list[dict]:
    """Ad içinde aranan kelimelerin hepsi geçenler (boşsa hepsi)."""
    parcalar = [w for w in re.findall(r"\w{2,}", (kelimeler or "").casefold())]
    if not parcalar:
        return liste
    return [o for o in liste if all(w in o["ad"].casefold() for w in parcalar)]


def tl(tutar: float) -> str:
    """1299.9 → "1.299,90" """
    return f"{tutar:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
