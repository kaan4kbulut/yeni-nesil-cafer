"""Güncellemeler (updates.py) ve açılışta geri dönüş (main.rollback_if_needed). İnternete gidilmez; sahte kurulum
klasörü geçicidir.

Çalıştırma (proje kökünde, programın Python'uyla):
    ~/.local/share/yeni-nesil-cafer-app/python/bin/python3 -m unittest discover -s testler -v
"""

import hashlib
import json
import os
import sys
import tempfile
import unittest
import zipfile
from contextlib import contextmanager
from pathlib import Path
from unittest import mock

KOK = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(KOK))

_GECICI = tempfile.mkdtemp(prefix="yeni-nesil-cafer-test-")
os.environ["XDG_CONFIG_HOME"] = str(Path(_GECICI) / "ayar")
os.environ["XDG_DATA_HOME"] = str(Path(_GECICI) / "veri")

import main  # noqa: E402
from asistan import updates  # noqa: E402


def kurulum(surum: str, moduller=("agent.py", "eski_modul.py")) -> Path:
    """Sahte kurulu program: asistan/__init__.py (sürüm), birkaç modül, main.py."""
    d = Path(tempfile.mkdtemp(prefix="kurulu-"))
    (d / "asistan").mkdir()
    (d / "asistan" / "__init__.py").write_text(f'__version__ = "{surum}"\n', encoding="utf-8")
    for m in moduller:
        (d / "asistan" / m).write_text(f"# {surum} {m}\n", encoding="utf-8")
    (d / "main.py").write_text(f"# main {surum}\n", encoding="utf-8")
    return d


class _Yanit:
    def __init__(self, status=200, body=None, data=b""):
        self.status_code, self.body, self.data = status, body, data
        self.headers = {"content-length": str(len(data))}
        self.text = json.dumps(body) if body is not None else ""

    def json(self):
        return self.body

    def raise_for_status(self):
        pass

    def iter_bytes(self, n):
        yield self.data


class GuncellemeTesti(unittest.TestCase):
    def setUp(self):
        self.yeni = kurulum("2.3", ("agent.py",))  # yeni sürümde eski_modul.py kaldırıldı
        self.cikti = Path(tempfile.mkdtemp())
        self.paket, self.sha = updates.build_package(self.yeni, self.cikti)
        self.kurulu = kurulum("2.2")
        veri = Path(tempfile.mkdtemp())
        self.patches = [mock.patch.object(updates, "PROGRAM_DIR", self.kurulu),
                        mock.patch.object(updates, "BACKUP_DIR", veri / "yedek"),
                        mock.patch.object(updates, "STATE_FILE", veri / "durum.json"),
                        mock.patch.object(updates, "__version__", "2.2"),
                        mock.patch.object(updates, "GITHUB_REPO", "kullanici/yeni-nesil-cafer")]
        for p in self.patches:
            p.start()

    def tearDown(self):
        for p in self.patches:
            p.stop()

    def bilgi(self, digest=None):
        return {"version": "2.3", "notes": "", "url": "https://github.com/k/y/releases/download/v2.3/x.zip",
                "size": self.paket.stat().st_size, "digest": f"sha256:{digest or self.sha}", "sha_url": "", "page": ""}

    def test_kod_paketi_yalnizca_program_kodu(self):
        with zipfile.ZipFile(self.paket) as z:
            names = z.namelist()
        self.assertIn("main.py", names)
        self.assertTrue(all(n == "main.py" or n.startswith("asistan/") for n in names))
        self.assertTrue((self.cikti / (self.paket.name + ".sha256")).read_text().startswith(self.sha))

    def test_son_surum_ve_karsilastirma(self):
        yayin = {"tag_name": "v2.3", "body": "notlar", "html_url": "https://github.com/k/y",
                 "assets": [{"name": updates.ASSET.format(version="2.3"), "size": 10, "digest": "sha256:ab",
                             "browser_download_url": "https://github.com/k/y/releases/download/v2.3/p.zip"},
                            {"name": "asistan.v2.3-Linux.tar.gz.001", "size": 2, "browser_download_url": "x"}]}
        with mock.patch.object(updates.httpx, "get", return_value=_Yanit(200, yayin)):
            info = updates.latest()
        self.assertEqual(info["version"], "2.3")
        self.assertTrue(updates.newer(info))
        self.assertFalse(updates.newer({"version": "2.2"}))
        self.assertFalse(updates.newer({"version": "2.1.9"}))
        self.assertTrue(updates.version_tuple("2.10") > updates.version_tuple("2.9"))

    def indir(self, data):
        @contextmanager
        def s(*a, **k):
            yield _Yanit(200, data=data)
        return mock.patch.object(updates.httpx, "stream", side_effect=s)

    def test_ozet_tutmazsa_kurulmaz(self):
        with self.indir(self.paket.read_bytes()):
            self.assertTrue(updates.download(self.bilgi()).is_file())
        with self.indir(self.paket.read_bytes() + b"x"), self.assertRaises(updates.UpdateError):
            updates.download(self.bilgi())
        info = self.bilgi()
        info["url"] = "https://baska-site.com/p.zip"
        with self.assertRaises(updates.UpdateError):
            updates.download(info)

    def test_yol_kacisi_reddedilir(self):
        kotu = self.cikti / "kotu.zip"
        with zipfile.ZipFile(kotu, "w") as z:
            z.writestr("main.py", "x")
            z.writestr("asistan/__init__.py", '__version__ = "2.3"')
            z.writestr("asistan/../../evil.sh", "rm -rf ~")
        with self.assertRaises(updates.UpdateError):
            updates.apply(kotu, "2.3")
        self.assertEqual((self.kurulu / "main.py").read_text(), "# main 2.2\n")  # hiçbir şey değişmedi

    def test_kurulum_yedek_ve_eski_modul_temizligi(self):
        backup = updates.apply(self.paket, "2.3")
        self.assertIn('"2.3"', (self.kurulu / "asistan/__init__.py").read_text())
        self.assertFalse((self.kurulu / "asistan/eski_modul.py").exists())  # yeni sürümde yok
        self.assertEqual((self.kurulu / "main.py").read_text(), "# main 2.3\n")
        self.assertTrue((backup / "asistan/eski_modul.py").is_file())
        self.assertEqual(json.loads(updates.STATE_FILE.read_text())["to"], "2.3")
        with self.assertRaises(updates.UpdateError):  # sürüm tutmazsa kurulmaz
            updates.apply(self.paket, "9.9")

    def test_cokerse_eski_surume_donulur(self):
        updates.apply(self.paket, "2.3")
        self.assertEqual(main.rollback_if_needed(updates.STATE_FILE, self.kurulu), "")  # ilk açılış: deneniyor
        note = main.rollback_if_needed(updates.STATE_FILE, self.kurulu)  # onaylanmadan yeniden açıldı: çöktü
        self.assertIn("geri dönüldü", note)
        self.assertIn('"2.2"', (self.kurulu / "asistan/__init__.py").read_text())
        self.assertTrue((self.kurulu / "asistan/eski_modul.py").is_file())
        self.assertEqual((self.kurulu / "main.py").read_text(), "# main 2.2\n")
        self.assertFalse(updates.STATE_FILE.exists())

    def test_kisa_surede_duzgun_kapanis_geri_dondurmez(self):
        """Kullanıcı yeni sürümü 15 sn dolmadan kapattıysa bu çökme değildir: sonraki açılışta geri dönülmez,
        güncelleme notu yine gösterilir (kayıt durur); ancak düzgün kapanmayan ikinci açılış yine geri döner."""
        updates.apply(self.paket, "2.3")
        self.assertEqual(main.rollback_if_needed(updates.STATE_FILE, self.kurulu), "")  # ilk açılış
        main.mark_clean_exit(updates.STATE_FILE)  # pencere kapatıldı (aboutToQuit), onay süresi dolmadan
        self.assertEqual(main.rollback_if_needed(updates.STATE_FILE, self.kurulu), "")  # ikinci açılış: çökme yok
        self.assertIn('"2.3"', (self.kurulu / "asistan/__init__.py").read_text())
        self.assertIn("2.3", updates.confirm())  # not hâlâ verilebiliyor
        updates.apply(self.paket, "2.3")
        main.rollback_if_needed(updates.STATE_FILE, self.kurulu)
        main.mark_clean_exit(updates.STATE_FILE)
        main.rollback_if_needed(updates.STATE_FILE, self.kurulu)  # düzgün açıldı ama bu kez onaysız ve kapanışsız
        self.assertIn("geri dönüldü", main.rollback_if_needed(updates.STATE_FILE, self.kurulu))
        main.mark_clean_exit(updates.STATE_FILE)  # kayıt yokken sessiz

    def test_sorunsuz_acilis_onaylanir(self):
        updates.apply(self.paket, "2.3")
        main.rollback_if_needed(updates.STATE_FILE, self.kurulu)
        self.assertIn("2.3", updates.confirm())
        self.assertEqual(main.rollback_if_needed(updates.STATE_FILE, self.kurulu), "")  # artık geri dönülmez
        self.assertIn('"2.3"', (self.kurulu / "asistan/__init__.py").read_text())


class AcikMiTesti(unittest.TestCase):
    def test_gelistirme_klasorunde_ve_depo_yokken_kapali(self):
        with mock.patch.object(updates, "GITHUB_REPO", ""):
            self.assertFalse(updates.enabled()[0])
        with mock.patch.object(updates, "GITHUB_REPO", "k/y"):
            self.assertEqual(updates.enabled()[0], not (updates.PROGRAM_DIR / ".git").exists())
        self.assertEqual(Path(main.update_state_file()).name, updates.STATE_FILE.name)


class AdDegisikligiTesti(unittest.TestCase):
    """2.2'ye kadarki ad (yerel-asistan) → yeni-nesil-cafer: veri ve anahtarlar kaybolmadan taşınır."""

    def test_eski_klasor_tasinir_yenisi_ezilmez(self):
        from asistan.config import migrate_dir

        base = Path(tempfile.mkdtemp())
        (base / "yerel-asistan" / "sohbetler").mkdir(parents=True)
        (base / "yerel-asistan" / "hafiza.db").write_text("hafıza")
        self.assertTrue(migrate_dir(base / "yeni-nesil-cafer", base / "yerel-asistan"))
        self.assertEqual((base / "yeni-nesil-cafer" / "hafiza.db").read_text(), "hafıza")
        self.assertFalse((base / "yerel-asistan").exists())
        (base / "yerel-asistan").mkdir()  # yeni klasör zaten varsa eskisine dokunulmaz
        self.assertFalse(migrate_dir(base / "yeni-nesil-cafer", base / "yerel-asistan"))
        self.assertTrue((base / "yerel-asistan").exists())

    def test_anahtar_eski_addan_kopyalanir(self):
        from asistan import keystore

        depo = {("yerel-asistan", "anthropic"): "sk-eski"}
        sahte = mock.Mock()
        sahte.get_password.side_effect = lambda s, k: depo.get((s, k))
        sahte.set_password.side_effect = lambda s, k, v: depo.__setitem__((s, k), v)
        with mock.patch.object(keystore, "keyring", sahte):
            self.assertEqual(keystore.get_secret("anthropic"), "sk-eski")
        self.assertEqual(depo[("yeni-nesil-cafer", "anthropic")], "sk-eski")


if __name__ == "__main__":
    unittest.main()
