"""Tarayıcı (BrowserAgent'ın elleri ve gözleri): Playwright ile gerçek bir Chromium, kalıcı profil.

- Eller: aç, oku, tıkla, yaz, kaydır, geri; hepsi sayfadaki öğelerin NUMARASIYLA (koordinatla değil).
- Gözler: `read` sayfanın tıklanabilir/yazılabilir öğelerini numaralı listeler (rol, erişilebilir ad, değer) ve
  görünen metni verir; görsel olarak anlaşılması gereken yerlerde ekran görüntüsü görme modeline gider (agent.py).
- Kalıcı profil: DATA_DIR/tarayici-profili — kullanıcı görünür pencerede bir kez giriş yapar, oturumlar kalır.
- Onay kapısı (`gate`): satın alma / ödeme, mesaj / paylaşım, hesap / silme, giriş / indirme gruplarındaki her
  tıklama ve yazma, güvenlik ajanı açık olsa bile KULLANICIYA sorulur (kullanıcı kararı, 2026-09-26). Şüphede sorar.
  Onaysız başlayan dosya indirmeleri iptal edilir.

Playwright'ın senkron API'si iş parçacıkları arasında paylaşılamaz; program her sohbet turunu ayrı bir iş
parçacığında çalıştırır. Bu yüzden tarayıcı kendi iş parçacığında yaşar, komutlar ona sırayla iletilir.
"""

import os
import queue
import re
import threading
import time
from concurrent.futures import Future
from pathlib import Path

from .config import DATA_DIR

PROFILE_DIR = DATA_DIR / "tarayici-profili"
MAX_ELEMENTS = 120
MAX_TEXT = 3500
ACTION_TIMEOUT = 15_000  # ms
NAV_TIMEOUT = 45_000


def _browsers_path() -> str:
    """Chromium'un yeri: programın kendi klasörü (kurulum paketine gömülür)."""
    from .tools import PROGRAM_DIR

    for p in (PROGRAM_DIR / "tarayici", Path.home() / ".local/share/yeni-nesil-cafer-app/tarayici"):
        if p.is_dir():
            return str(p)
    return ""


def available() -> bool:
    try:
        import playwright  # noqa: F401
    except ImportError:
        return False
    return bool(_browsers_path())


# ---------------------------------------------------------------- onay kapısı

GATES = [
    ("satın alma / ödeme", re.compile(
        r"satın al|hemen al|şimdi al|tek tıkla al|sipariş(i)? (ver|onayla|tamamla)|siparişi|ödeme(yi)?|öde\b|ödemeye|sepeti onayla|alışverişi tamamla|"
        r"abone ol|aboneliği? başlat|kart(ı)? (ekle|kaydet)|\bbuy\b|purchase|checkout|place order|\bpay\b|pay now|"
        r"subscribe|confirm order|complete order", re.I)),
    ("mesaj / paylaşım", re.compile(
        r"gönder|paylaş|yayınla|yorum (yap|gönder)|tweetle|yanıtla|cevapla|\bsend\b|\bpost\b|publish|reply|tweet|"
        r"share|comment", re.I)),
    ("hesap / silme", re.compile(
        r"\bsil\b|sil\s|kaldır|iptal et|hesab(ı|ımı) (kapat|sil|dondur)|şifre(yi|mi)? değiştir|parola|ayarları kaydet|"
        r"değişiklikleri kaydet|delete|remove|deactivate|close account|change password|cancel (subscription|order)|"
        r"unsubscribe", re.I)),
    ("giriş / indirme", re.compile(
        r"giriş yap|oturum aç|kayıt ol|üye ol|sign in|log ?in|sign up|register|indir\b|download|kur\b|install", re.I)),
]
_CHECKOUT_URL = re.compile(r"checkout|payment|odeme|ödeme|sepet/onay|order/confirm|/pay\b", re.I)
_FILE_HREF = re.compile(r"\.(exe|msi|zip|rar|7z|deb|rpm|appimage|dmg|pkg|apk|sh|bat|iso|tar\.gz|tgz)(\?|$)", re.I)
_MONEY = re.compile(r"\d[\d.,]*\s?(TL|₺|\$|€|USD|EUR)\b|(₺|\$|€)\s?\d", re.I)
_SEARCH = re.compile(r"ara|search|arama|sorgu|query|\bq\b|find|bul", re.I)


def gate(action: str, element: dict, url: str, text: str = "", submit: bool = False) -> str | None:
    """Bu eylem kullanıcıya sorulmalı mı? Soruluyorsa grubu ve nedeni (Türkçe), değilse None.
    element: read()'in öğe bilgisi (role, name, type, href, form_sensitive, download)."""
    label = " ".join(str(element.get(k) or "") for k in ("name", "value", "title"))
    kind = str(element.get("type") or "").lower()
    role = str(element.get("role") or "").lower()
    if action == "type":
        if kind == "password" or element.get("autocomplete", "").startswith(("current-password", "new-password")):
            return "giriş / indirme: bir şifre alanına yazılacak"
        if element.get("payment") or re.search(r"cc-|card|kart|cvv|cvc|iban", str(element.get("autocomplete", "")) +
                                               " " + str(element.get("fieldname", "")), re.I):
            return "satın alma / ödeme: kart / ödeme bilgisi yazılacak"
        searchish = element.get("searchish") or role in ("searchbox", "combobox") or _SEARCH.search(
            label + " " + str(element.get("fieldname", "")))
        if submit and not searchish:
            return "mesaj / paylaşım: yazılan metin bir forma gönderilecek (Enter)"
        return None
    # tıklama
    if element.get("download") or _FILE_HREF.search(str(element.get("href") or "")):
        return "giriş / indirme: bir dosya indirilecek"
    href = str(element.get("href") or "")
    for group, rx in GATES:
        if not rx.search(label):
            continue
        # bağlantı yalnızca sayfa açar: "… Fiyatları & Satın Al" gibi arama sonuçları serbest; adresi ödeme / paylaşım
        # ise ya da hesap / giriş / indirme grubundaysa sorulur
        if role == "link" and group in ("satın alma / ödeme", "mesaj / paylaşım") and not (
                _CHECKOUT_URL.search(href) or re.search(r"share|intent/|compose|sendmail|mailto:", href, re.I)):
            continue
        return f"{group}: “{label.strip()[:80]}” öğesine tıklanacak"
    if element.get("form_sensitive") and (kind == "submit" or role == "button"):
        return "giriş / ödeme: şifre ya da kart alanı olan bir form gönderilecek"
    if _CHECKOUT_URL.search(url) and role == "button" and kind != "search":  # bağlantı sayfadan çıkar, düğme onaylar
        return "satın alma / ödeme: ödeme sayfasında bir düğmeye tıklanacak"
    return None


# ---------------------------------------------------------------- sayfa okuma (tarayıcıda çalışan betik)

_MARK_JS = r"""
(max) => {
  document.querySelectorAll('[data-ya-ref]').forEach(e => e.removeAttribute('data-ya-ref'));
  const sel = 'a[href], button, input:not([type=hidden]), textarea, select, summary, [role=button], [role=link], ' +
              '[role=tab], [role=menuitem], [role=checkbox], [role=radio], [role=option], [role=combobox], ' +
              '[role=searchbox], [role=textbox], [contenteditable=true], [onclick]';
  const out = [];
  const seen = new Set();
  const vh = window.innerHeight, vw = window.innerWidth;
  for (const el of document.querySelectorAll(sel)) {
    if (out.length >= max) break;
    const r = el.getBoundingClientRect();
    const st = getComputedStyle(el);
    if (r.width < 2 || r.height < 2 || st.visibility === 'hidden' || st.display === 'none') continue;
    // görünmez tuzak alanlar ve gizli öğeler (sayfa modeli gizli metinle yanıltmasın)
    // (pointer-events:none tek başına gizli sayılmaz: bazı siteler gerçek arama kutusunun üstüne tıklama katmanı koyar)
    if (parseFloat(st.opacity) < 0.05 || el.closest('[aria-hidden=true]') ||
        (el.getAttribute('tabindex') === '-1' && el.tagName === 'INPUT')) continue;
    if (r.bottom < -vh || r.top > vh * 3 || r.right < 0 || r.left > vw) continue;  // görünene yakın olanlar
    const tag = el.tagName.toLowerCase();
    const type = (el.getAttribute('type') || '').toLowerCase();
    let role = el.getAttribute('role') || ({a: 'link', button: 'button', select: 'combobox', textarea: 'textbox',
               summary: 'button'}[tag]) || (tag === 'input' ? ({checkbox: 'checkbox', radio: 'radio', submit: 'button',
               button: 'button', search: 'searchbox'}[type] || 'textbox') : (el.isContentEditable ? 'textbox' : 'button'));
    const lab = el.labels && el.labels[0] ? el.labels[0].innerText : '';
    let name = (el.getAttribute('aria-label') || lab || el.getAttribute('placeholder') || el.getAttribute('title') ||
                el.getAttribute('alt') || (tag === 'input' && ['submit','button'].includes(type) ? el.value : '') ||
                el.innerText || el.textContent || '').replace(/\s+/g, ' ').trim().slice(0, 100);
    if (!name && tag === 'a') { const img = el.querySelector('img[alt]'); if (img) name = img.alt; }
    const key = role + '|' + name + '|' + (el.getAttribute('href') || '');
    if (!name && !['textbox','searchbox','combobox'].includes(role)) continue;
    if (seen.has(key) && role === 'link') continue;
    seen.add(key);
    const form = el.form || el.closest('form');
    const formSensitive = !!(form && form.querySelector('input[type=password], [autocomplete^=cc-]'));
    const ref = out.length + 1;
    el.setAttribute('data-ya-ref', String(ref));
    out.push({ref, role, name, type, tag,
      value: (['input','textarea'].includes(tag) && type !== 'password') ? (el.value || '').slice(0, 80) : '',
      href: el.getAttribute('href') || '', title: el.getAttribute('title') || '',
      autocomplete: el.getAttribute('autocomplete') || '', fieldname: (el.getAttribute('name') || el.id || ''),
      download: el.hasAttribute('download'), form_sensitive: formSensitive,
      payment: /cc-|card|kart|cvv|cvc/i.test((el.getAttribute('autocomplete') || '') + ' ' + (el.getAttribute('name') || '')),
      searchish: type === 'search' || el.getAttribute('enterkeyhint') === 'search' || role === 'searchbox' ||
        !!el.closest('[role=search], form[action*=search], form[action*=arama], form[action*="/s"]') ||
        /(^|[^a-z])(q|query|search|ara|arama|keyword|k)([^a-z]|$)/i.test((el.getAttribute('name') || '') + ' ' + (el.id || '')),
      checked: el.checked === true, disabled: el.disabled === true, visible: r.top >= 0 && r.bottom <= vh});
  }
  return out;
}
"""


def _describe(e: dict) -> str:
    e = {"ref": "?", "role": "öğe", "name": "", **e}
    bits = [f"[{e['ref']}] {e['role']}"]
    if e.get("type") == "password":
        bits.append("(şifre alanı)")
    if e["name"]:
        bits.append(f"“{e['name']}”")
    if e.get("value"):
        bits.append(f"değer: “{e['value']}”")
    if e.get("href") and e["role"] == "link" and not e["href"].startswith("javascript"):
        bits.append(f"→ {e['href'][:90]}")
    if e.get("checked"):
        bits.append("(seçili)")
    if e.get("disabled"):
        bits.append("(pasif)")
    if not e.get("visible"):
        bits.append("(aşağıda)")
    return " ".join(bits)


# ---------------------------------------------------------------- tarayıcı iş parçacığı

class Browser:
    """Tek tarayıcı, tek iş parçacığı. Bütün yöntemler herhangi bir iş parçacığından çağrılabilir."""

    def __init__(self):
        self._q: queue.Queue = queue.Queue()
        self._thread: threading.Thread | None = None
        self.elements: dict[int, dict] = {}  # son read()'in öğeleri (onay kapısı bunlara bakar)
        self.allow_download = False
        self.approved_download = False  # kullanıcı bir sonraki tıklamanın indirmesini onayladı (agent.py)
        self.blocked_downloads: list[str] = []
        self.downloads_dir = DATA_DIR / "indirilenler"

    # -- iş parçacığı
    def _loop(self):
        os.environ.setdefault("PLAYWRIGHT_BROWSERS_PATH", _browsers_path())
        from playwright.sync_api import sync_playwright

        pw = ctx = None
        while True:
            fn, fut = self._q.get()
            if fn is None:
                break
            try:
                if ctx is None or not self._alive(ctx):
                    pw = pw or sync_playwright().start()
                    ctx = self._launch(pw)
                self.ctx = ctx
                fut.set_result(fn(ctx))
            except Exception as e:
                fut.set_exception(e)
        try:
            if ctx is not None:
                ctx.close()
            if pw is not None:
                pw.stop()
        except Exception:
            pass

    @staticmethod
    def _alive(ctx) -> bool:
        try:
            return bool(ctx.pages) or ctx.new_page() is not None
        except Exception:
            return False  # kullanıcı pencereyi kapattı: yeniden açılır

    def _launch(self, pw):
        PROFILE_DIR.mkdir(parents=True, exist_ok=True)
        ctx = pw.chromium.launch_persistent_context(
            str(PROFILE_DIR), headless=False, locale="tr-TR", viewport=None, accept_downloads=True,
            args=["--start-maximized"], timeout=NAV_TIMEOUT)
        ctx.set_default_timeout(ACTION_TIMEOUT)
        ctx.set_default_navigation_timeout(NAV_TIMEOUT)
        ctx.on("page", lambda page: page.on("download", self._on_download))
        for page in ctx.pages:
            page.on("download", self._on_download)
        return ctx

    def _on_download(self, download):
        if self.allow_download:
            self.downloads_dir.mkdir(parents=True, exist_ok=True)
            download.save_as(str(self.downloads_dir / download.suggested_filename))
        else:
            self.blocked_downloads.append(download.suggested_filename)
            download.cancel()

    def _call(self, fn, timeout: float = 120):
        if self._thread is None or not self._thread.is_alive():
            self._thread = threading.Thread(target=self._loop, name="tarayici", daemon=True)
            self._thread.start()
        fut: Future = Future()
        self._q.put((fn, fut))
        return fut.result(timeout=timeout)

    def close(self):
        if self._thread is not None and self._thread.is_alive():
            self._q.put((None, None))
            self._thread.join(10)  # program kapanırken tarayıcı düzgün kapansın (yarıda kalırsa süreç çöker)

    # -- yardımcılar (tarayıcı iş parçacığında çalışır)
    @staticmethod
    def _page(ctx):
        return ctx.pages[-1] if ctx.pages else ctx.new_page()

    @staticmethod
    def _settle(page, before_url: str = ""):
        """Eylemden sonra sayfanın oturmasını bekler; adres değişecekse (arama, bağlantı) önce onu bekler."""
        if before_url:
            try:
                page.wait_for_url(lambda u: u != before_url, timeout=6000)
            except Exception:
                pass  # aynı sayfada kalan eylem (sekme, açılır menü)
        try:
            page.wait_for_load_state("domcontentloaded", timeout=10_000)
        except Exception:
            pass
        page.wait_for_timeout(800)  # arama sonuçları gibi sonradan gelen içerik

    def _snapshot(self, page, find: str = "") -> str:
        elements = page.evaluate(_MARK_JS, MAX_ELEMENTS)
        self.elements = {e["ref"]: e for e in elements}
        text = page.evaluate("() => (document.body ? document.body.innerText : '')") or ""
        text = re.sub(r"\n\s*\n+", "\n", text).strip()
        shown = elements
        if find:
            words = [w for w in re.findall(r"\w{3,}", find.casefold())]
            money = any(w.startswith(("fiyat", "price", "ücret", "ucret", "tutar", "tl")) for w in words)

            def match(t: str) -> bool:  # "fiyat" aranınca "19.466 TL" gibi satırlar da eşleşir
                return any(w in t.casefold() for w in words) or (money and bool(_MONEY.search(t)))

            shown = [e for e in elements if e["role"] in ("textbox", "searchbox", "combobox")  # yazı alanları hep
                     or match(e["name"] + " " + e.get("href", ""))]
            if len(shown) < 8:
                shown = elements  # süzgeç çok daralttı: hepsi (ör. ürün adlarında "ürün" kelimesi geçmez)
            lines = text.splitlines()
            hits = [i for i, ln in enumerate(lines) if match(ln)]
            if len(hits) >= 3:  # eşleşen satırlar ve çevresi: fiyatın hemen üstündeki ürün adı da görünsün
                keep = sorted({j for i in hits for j in range(i - 2, i + 3) if 0 <= j < len(lines)})
                text = "\n".join(lines[j] for j in keep)
        out = [f"Sayfa: {page.title()[:120]} — {page.url[:200]}",
               "Öğeler (tıklamak ya da yazmak için numarayı kullan):"]
        out += [_describe(e) for e in shown] or ["(etkileşimli öğe yok)"]
        out.append("Görünen metin:\n" + (text[:MAX_TEXT] + (" […]" if len(text) > MAX_TEXT else "")))
        if self.blocked_downloads:
            out.append("İPTAL EDİLEN İNDİRMELER (onay yoktu): " + ", ".join(self.blocked_downloads))
            self.blocked_downloads = []
        return "\n".join(out)

    # -- araçlar
    def open(self, url: str) -> str:
        url = url.strip()
        if re.match(r"^[a-z][a-z0-9+.-]*:", url, re.I) and not re.match(r"https?://", url, re.I):
            # file://, chrome:// vb. yok: tarayıcı üzerinden bilgisayardaki dosyalar okunamasın
            raise ValueError("Only http(s) web addresses can be opened in the browser.")
        if not re.match(r"https?://", url, re.I):
            url = "https://" + url

        def run(ctx):
            page = self._page(ctx)
            page.bring_to_front()
            page.goto(url, wait_until="domcontentloaded")
            self._settle(page)
            return self._snapshot(page)
        return self._call(run)

    def read(self, find: str = "") -> str:
        return self._call(lambda ctx: self._snapshot(self._page(ctx), find))

    def element(self, ref: int) -> dict | None:
        return self.elements.get(int(ref))

    def url(self) -> str:
        try:
            return self._call(lambda ctx: self._page(ctx).url, timeout=10)
        except Exception:
            return ""

    def click(self, ref: int, allow_download: bool = False) -> str:
        def run(ctx):
            page = self._page(ctx)
            loc = page.locator(f'[data-ya-ref="{int(ref)}"]').first
            if loc.count() == 0:
                return f"Öğe [{ref}] artık sayfada yok; önce browser_read ile sayfayı yeniden oku."
            self.allow_download = allow_download
            try:
                before = len(ctx.pages)
                loc.scroll_into_view_if_needed()
                before_url = page.url
                loc.click()
                self._settle(page, before_url if self.elements.get(int(ref), {}).get("role") == "link" else "")
                if len(ctx.pages) > before:  # yeni sekme açıldı: ona geç
                    page = ctx.pages[-1]
                    page.bring_to_front()
                    self._settle(page)
                if allow_download:
                    page.wait_for_timeout(2000)
            finally:
                self.allow_download = False
            return self._snapshot(page)
        return self._call(run)

    def type(self, ref: int, text: str, submit: bool = False) -> str:
        def run(ctx):
            page = self._page(ctx)
            loc = page.locator(f'[data-ya-ref="{int(ref)}"]').first
            if loc.count() == 0:
                return f"Öğe [{ref}] artık sayfada yok; önce browser_read ile sayfayı yeniden oku."
            loc.scroll_into_view_if_needed()
            # bazı siteler ilk dokunuşta kutuyu gerçek arama penceresiyle değiştirir: önce tıkla, odaktaki alana yaz
            try:
                loc.click(force=True, timeout=3000)
                page.wait_for_timeout(500)
            except Exception:
                pass
            focused = page.locator(":focus")
            try:
                tag = focused.evaluate("e => e.tagName") if focused.count() else ""
            except Exception:
                tag = ""
            if tag in ("INPUT", "TEXTAREA"):
                loc = focused
            try:
                loc.fill(text)
            except Exception:  # contenteditable vb.
                page.keyboard.type(text)
            if submit:
                before_url = page.url
                try:
                    loc.press("Enter", timeout=4000)
                except Exception:  # üstünde tıklama katmanı var: alana doğrudan odaklanıp yeniden dene
                    try:
                        loc.focus(timeout=4000)
                        loc.press("Enter", timeout=8000)
                    except Exception:
                        page.keyboard.press("Enter")
                self._settle(page, before_url)
            return self._snapshot(page)
        return self._call(run)

    def scroll(self, direction: str = "down") -> str:
        def run(ctx):
            page = self._page(ctx)
            page.mouse.wheel(0, -800 if direction == "up" else 800)
            page.wait_for_timeout(600)
            return self._snapshot(page)
        return self._call(run)

    def back(self) -> str:
        def run(ctx):
            page = self._page(ctx)
            page.go_back()
            self._settle(page)
            return self._snapshot(page)
        return self._call(run)

    def screenshot(self, folder: Path) -> Path:
        folder.mkdir(parents=True, exist_ok=True)
        path = folder / f"sayfa-{time.strftime('%H%M%S')}.png"
        self._call(lambda ctx: self._page(ctx).screenshot(path=str(path)))
        return path


_browser: Browser | None = None


def get() -> Browser:
    global _browser
    if _browser is None:
        _browser = Browser()
    return _browser


def shutdown() -> None:
    if _browser is not None:
        _browser.close()
