"""dosya_yaz yeteneği: manifestteki örnekler `write_file` aracına doğru girdiyle gider; araç yolu yoksa ve zorunlu
girdi eksikse `YetenekHatasi`. Ağ ve izin hattı yok (araç sahte); uçtan uca: `testler/test_yetenek_kaydi.py`."""

import importlib.util
import json
import sys
import unittest
from pathlib import Path

KLASOR = Path(__file__).resolve().parent
sys.path.insert(0, str(KLASOR.parents[2]))
from asistan.cekirdek.yetenek import Baglam, YetenekHatasi  # noqa: E402

_spec = importlib.util.spec_from_file_location("yetenek_dosya_yaz", KLASOR / "calistir.py")
yetenek = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(yetenek)
MANIFEST = json.loads((KLASOR / "manifest.json").read_text(encoding="utf-8"))


class Test_dosya_yaz(unittest.TestCase):
    def baglam(self):
        self.cagrilar = []

        def arac(ad, args):
            self.cagrilar.append((ad, args))
            return "tamam"
        return Baglam(calisma_klasoru=str(KLASOR), arac=arac)

    def test_ornekler_araca_gider(self):
        for ornek in MANIFEST["ornekler"]:
            self.assertEqual(yetenek.calistir(ornek["girdi"], self.baglam()), {"sonuc": "tamam"})
            ad, args = self.cagrilar[-1]
            self.assertEqual(ad, "write_file")
            for alan, (arac_alani, _) in yetenek.ESLEME.items():
                if alan in ornek["girdi"]:
                    self.assertEqual(args[arac_alani], ornek["girdi"][alan])

    def test_arac_yolu_olmadan_calismaz(self):
        with self.assertRaises(YetenekHatasi) as h:
            yetenek.calistir(MANIFEST["ornekler"][0]["girdi"], Baglam(calisma_klasoru=str(KLASOR)))
        self.assertEqual(h.exception.sinif, "kaynak")

    def test_eksik_girdi(self):
        with self.assertRaises(YetenekHatasi) as h:
            yetenek.calistir({}, self.baglam())  # zorunlu alan yok / nesne değil
        self.assertEqual(h.exception.sinif, "veri")
        self.assertEqual(self.cagrilar, [])


if __name__ == "__main__":
    unittest.main()
