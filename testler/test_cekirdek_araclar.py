"""Çekirdekteki temel araçlar (`asistan.cekirdek.araclar`): dosya, komut/Python, web. `Toolbox` bunlara devreder.

Çalıştırma (proje kökünde, programın Python'uyla):
    ~/.local/share/yeni-nesil-cafer-app/python/bin/python3 -m unittest discover -s testler -v
"""

import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

KOK = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(KOK))

_GECICI = tempfile.mkdtemp(prefix="yeni-nesil-cafer-test-")
os.environ["XDG_CONFIG_HOME"] = str(Path(_GECICI) / "ayar")
os.environ["XDG_DATA_HOME"] = str(Path(_GECICI) / "veri")

import httpx  # noqa: E402

from asistan import tools  # noqa: E402
from asistan.cekirdek.araclar import AracHatasi, dosya, komut, web  # noqa: E402


class DosyaTesti(unittest.TestCase):
    def setUp(self):
        self.kok = Path(tempfile.mkdtemp(prefix="is-")).resolve()
        self.program = Path(tempfile.mkdtemp(prefix="program-")).resolve()
        (self.program / "kod.py").write_text("x = 1\n", encoding="utf-8")
        (self.program / "anahtarlar.json").write_text("{}", encoding="utf-8")

    def test_yol_denetimi(self):
        self.assertEqual(dosya.yol_coz(self.kok, [], "a/b.txt"), self.kok / "a" / "b.txt")
        with self.assertRaisesRegex(AracHatasi, "outside the workspace"):
            dosya.yol_coz(self.kok, [], "../../etc/passwd")
        self.assertEqual(dosya.yol_coz(self.kok, [self.program], str(self.program / "kod.py"), okuma=True),
                         self.program / "kod.py")
        with self.assertRaisesRegex(AracHatasi, "only allowed inside the workspace"):
            dosya.yol_coz(self.kok, [self.program], str(self.program / "kod.py"))
        with self.assertRaisesRegex(AracHatasi, "API keys"):
            dosya.yol_coz(self.kok, [self.program], str(self.program / "anahtarlar.json"), okuma=True)

    def test_yaz_oku_duzenle_listele_ara(self):
        self.assertIn("Wrote 10 characters", dosya.yaz(self.kok, [], "not/a.txt", "bir\niki\nüç"))
        self.assertEqual(dosya.oku(self.kok, [], "not/a.txt"), "1\tbir\n2\tiki\n3\tüç")
        self.assertIn("[satır 2-2 / toplam 3", dosya.oku(self.kok, [], "not/a.txt", 2, 1))
        self.assertEqual(dosya.duzenle(self.kok, [], "not/a.txt", "iki", "İKİ"), "Edited not/a.txt")
        with self.assertRaisesRegex(AracHatasi, "exactly once"):
            dosya.duzenle(self.kok, [], "not/a.txt", "yok", "x")
        self.assertEqual(dosya.listele(self.kok, []), "not/")
        self.assertIn("not/a.txt:2: İKİ", dosya.ara(self.kok, [], "iki"))
        self.assertIn("No matches", dosya.ara(self.kok, [], "zzz"))
        # anahtar dosyası aramada da atlanır
        self.assertNotIn("anahtarlar", dosya.ara(self.kok, [self.program], "{", str(self.program)))

    def test_toolbox_devreder(self):
        kutu = tools.Toolbox(str(self.kok))
        kutu.read_roots = [self.program]
        kutu.run("write_file", {"path": "b.txt", "content": "merhaba"})
        self.assertEqual(kutu.run("read_file", {"path": "b.txt"}), "1\tmerhaba")
        self.assertIs(tools.ToolError, AracHatasi)
        self.assertIs(tools.unescape_code, komut.kacislari_coz)
        self.assertIs(tools.SECRET_FILES, dosya.GIZLI_DOSYALAR)
        with self.assertRaises(tools.ToolError):
            kutu.run("write_file", {"path": str(self.program / "kod.py"), "content": "bozuk"})


class KomutTesti(unittest.TestCase):
    def setUp(self):
        self.kok = Path(tempfile.mkdtemp(prefix="is-")).resolve()

    def test_surec_ciktisi_ve_zaman_asimi(self):
        cikti = komut.surec([sys.executable, "-c", "import sys; print('a'); print('b', file=sys.stderr)"], self.kok)
        self.assertTrue(cikti.startswith("exit code: 0\n--- stdout ---\na"))
        self.assertIn("--- stderr ---\nb", cikti)
        with self.assertRaisesRegex(AracHatasi, "Timed out"):
            komut.surec([sys.executable, "-c", "import time; time.sleep(5)"], self.kok, zaman_asimi=0.5)

    @unittest.skipIf(sys.platform == "win32", "bash yolu")
    def test_komut_ve_sudo_ortami(self):
        cagrilar = []

        def sahte(argv, kok, ortam=None, zaman_asimi=0):
            cagrilar.append((argv, ortam))
            return "tamam"

        with mock.patch.object(komut, "surec", sahte):
            komut.komut_calistir("ls", self.kok, python_yolu=lambda: "py", ajan_ortami=dict, askpass=lambda: "/a.sh")
            komut.komut_calistir("sudo pacman -S x", self.kok, python_yolu=lambda: "py", ajan_ortami=dict,
                                 askpass=lambda: "/a.sh")
        self.assertEqual(cagrilar[0], (["bash", "-c", "ls"], None))
        self.assertEqual(cagrilar[1][0], ["bash", "-c", "sudo -A pacman -S x"])
        self.assertEqual(cagrilar[1][1]["SUDO_ASKPASS"], "/a.sh")

    def test_python_ve_arac_uyarisi(self):
        cikti = komut.python_calistir("print(2 + 3)", self.kok, python_yolu=sys.executable, ortam=dict(os.environ))
        self.assertIn("5", cikti)
        cikti = komut.python_calistir("make_decor_model(shape='vazo')", self.kok, python_yolu=sys.executable,
                                      ortam=dict(os.environ), arac_adlari={"make_decor_model"})
        self.assertIn("is a TOOL, not a Python function", cikti)

    def test_kacislari_coz(self):
        self.assertEqual(komut.kacislari_coz("x = 1\\nprint(x)"), "x = 1\nprint(x)")
        self.assertEqual(komut.kacislari_coz('print("a\\nb")'), 'print("a\\nb")')


class WebTesti(unittest.TestCase):
    def test_sayfa_metni(self):
        baslik, metin = web.sayfa_metni("<html><head><title>Başlık</title><script>x()</script></head>"
                                        "<body><nav>menü</nav><p>asıl  metin</p></body></html>")
        self.assertEqual(baslik, "Başlık")
        self.assertEqual(metin, "asıl  metin")

    def test_oku(self):
        with self.assertRaisesRegex(AracHatasi, "http"):
            web.oku("file:///etc/passwd")
        yanit = httpx.Response(200, headers={"content-type": "text/html"},
                               text="<title>T</title><p>gövde</p>", request=httpx.Request("GET", "http://x"))
        with mock.patch.object(httpx, "get", return_value=yanit):
            self.assertEqual(web.oku("http://x"), "T\n\ngövde")
        with mock.patch.object(httpx, "get", return_value=httpx.Response(404, request=httpx.Request("GET", "http://x"))):
            with self.assertRaisesRegex(AracHatasi, "HTTP 404"):
                web.oku("http://x")
        with mock.patch.object(httpx, "get", side_effect=httpx.ConnectError("yok")):
            with self.assertRaisesRegex(AracHatasi, "Could not reach"):
                web.oku("http://x")


if __name__ == "__main__":
    unittest.main()
