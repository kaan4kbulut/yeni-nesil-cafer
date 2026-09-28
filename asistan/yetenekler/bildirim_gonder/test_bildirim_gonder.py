"""bildirim_gonder: araç eşlemesi ve eksik girdi; ağa çıkmaz (araç sahte)."""

import importlib.util
import os
import types
import unittest

from asistan.cekirdek.yetenek import YetenekHatasi

yol = os.path.join(os.path.dirname(os.path.abspath(__file__)), "calistir.py")
spec = importlib.util.spec_from_file_location("bildirim_gonder_c", yol)
c = importlib.util.module_from_spec(spec)
spec.loader.exec_module(c)


class T(unittest.TestCase):
    def test_arac_cagrisi(self):
        self.assertEqual(c.arac_cagrisi({"baslik": "a", "metin": "b"}), ("send_notification", {"title": "a", "text": "b"}))
        cagrilar = []
        b = types.SimpleNamespace(arac=lambda ad, args: cagrilar.append((ad, args)) or "ntfy ✓")
        self.assertEqual(c.calistir({"baslik": "a", "metin": "b"}, b), {"sonuc": "ntfy ✓"})
        self.assertEqual(cagrilar, [("send_notification", {"title": "a", "text": "b"})])

    def test_eksik(self):
        with self.assertRaises(YetenekHatasi):
            c.calistir({"baslik": "a"}, types.SimpleNamespace(arac=lambda *a: ""))


if __name__ == "__main__":
    unittest.main()
