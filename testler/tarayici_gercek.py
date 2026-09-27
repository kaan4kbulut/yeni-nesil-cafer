"""Gerçek tarayıcı testleri (BrowserAgent): Playwright Chromium açılır, yerel bir sayfada okuma, tıklama, onay kapısı
ve kaydırma denenir. Pencere açtığı için unittest'e (test_*.py) girmez; tarayıcıya dokunan bir değişiklikten sonra
elle çalıştırılır (2026-09-27'ye kadar YA_TARAYICI_TEST=1 ile test_tarayici.py'deydi, yayında hep atlanıyordu):

    ~/.local/share/yeni-nesil-cafer-app/python/bin/python3 testler/tarayici_gercek.py -v
"""

import os
import sys
import tempfile
import unittest
from pathlib import Path

KOK = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(KOK))
_GECICI = tempfile.mkdtemp(prefix="yeni-nesil-cafer-test-")
os.environ["XDG_CONFIG_HOME"] = str(Path(_GECICI) / "ayar")
os.environ["XDG_DATA_HOME"] = str(Path(_GECICI) / "veri")

from asistan import browser  # noqa: E402

if not browser.available():
    sys.exit("Playwright Chromium kurulu değil: tarayıcı testleri çalışamaz.")


PAGE = """<html><head><meta charset="utf-8"><title>Deneme</title></head><body><h1>Deneme mağazası</h1>
<input aria-hidden="true" tabindex="-1" style="opacity:0;position:absolute">
<label>Ara <input name="q" type="search"></label>
<button onclick="document.title='sepette'">Sepete ekle</button>
<button onclick="document.title='SIPARIS'">Siparişi onayla</button>
<form><input type="password" name="sifre"><button type="submit">Devam</button></form>
<a href="/dosya.zip" download>İndir</a></body></html>"""


class GercekTarayici(unittest.TestCase):
    def test_sayfa_okuma_ve_tiklama(self):
        import functools
        import http.server
        import threading

        d = Path(tempfile.mkdtemp(dir=_GECICI))
        (d / "magaza.html").write_text(PAGE, encoding="utf-8")
        httpd = http.server.ThreadingHTTPServer(("127.0.0.1", 0), functools.partial(
            http.server.SimpleHTTPRequestHandler, directory=str(d)))
        threading.Thread(target=httpd.serve_forever, daemon=True).start()
        url = f"http://127.0.0.1:{httpd.server_address[1]}/magaza.html"
        b = browser.get()
        try:
            with self.assertRaises(ValueError):
                b.open((d / "magaza.html").as_uri())  # file:// açılmaz
            text = b.open(url)
            names = [e["name"] for e in b.elements.values()]
            self.assertNotIn("", [e["name"] for e in b.elements.values() if e["role"] != "textbox"])
            self.assertEqual(sum(1 for e in b.elements.values() if e["role"] in ("textbox", "searchbox")), 2)  # tuzak yok
            self.assertIn("Sepete ekle", names)
            ids = {e["name"]: e for e in b.elements.values()}
            self.assertIsNone(browser.gate("click", ids["Sepete ekle"], url))
            self.assertIsNotNone(browser.gate("click", ids["Siparişi onayla"], url))
            self.assertIsNotNone(browser.gate("click", ids["Devam"], url))  # şifreli form
            self.assertIsNotNone(browser.gate("click", ids["İndir"], url))
            out = b.click(ids["Sepete ekle"]["ref"])
            self.assertIn("Sayfa: sepette", out)
            self.assertIn("Deneme mağazası", text)
        finally:
            browser.shutdown()
            httpd.shutdown()
            httpd.server_close()

    def test_kaydirinca_sayfanin_devami_okunur(self):
        """2026-09-26 denetimi: metin hep sayfanın başından veriliyordu; kaydırma modelin gördüğünü değiştirmiyordu."""
        import functools
        import http.server
        import re
        import threading

        d = Path(tempfile.mkdtemp(dir=_GECICI))
        rows = "".join(f"<p>ürün {i} — {100 + i} TL</p>" for i in range(300))
        (d / "liste.html").write_text(f"<html><head><meta charset='utf-8'><title>Liste</title></head><body>{rows}"
                                      "<p>LİSTENİN SONU</p></body></html>", encoding="utf-8")
        httpd = http.server.ThreadingHTTPServer(("127.0.0.1", 0), functools.partial(
            http.server.SimpleHTTPRequestHandler, directory=str(d)))
        threading.Thread(target=httpd.serve_forever, daemon=True).start()
        b = browser.get()
        try:
            first = b.open(f"http://127.0.0.1:{httpd.server_address[1]}/liste.html")
            after = b.scroll("down")
            self.assertIn("konum: %0", first)
            top = int(re.search(r"ürün (\d+)", first.split("Görünen metin:")[1]).group(1))
            below = int(re.search(r"ürün (\d+)", after.split("Görünen metin:")[1]).group(1))
            self.assertEqual(top, 0)
            self.assertGreater(below, top)  # kaydırınca ilk görünen satır ilerler
            self.assertIn("ürün 290", b.read(find="ürün 290"))  # aramalı okuma bütün sayfada
        finally:
            browser.shutdown()
            httpd.shutdown()
            httpd.server_close()


if __name__ == "__main__":
    unittest.main()
