"""K12-C — ayar / durum düzeltmeleri (`NOTLAR/inceleme-k12-2026-09-28.md` C1–C3).

C1 JSON dosyaları atomik yazılır (tmp + os.replace; yarım dosya kalmaz), bozuk `ayarlar.json` kenara alınır ·
C2 kademe kilidi GUI'nin `Settings` nesnesiyle kaydedilir (ayrı örnek ezmez) · C3 Ollama bağlamı model başına: ölçülmemiş
modelde VRAM'e göre tahmin (14B model 32K bağlamla karta sığmıyordu → her görev zaman aşımı).

Çalıştırma (proje kökünde): QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest testler/test_k12_c.py -q
"""

import json
import os
import stat
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

KOK = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(KOK))
_GECICI = tempfile.mkdtemp(prefix="yeni-nesil-cafer-test-")
os.environ["XDG_CONFIG_HOME"] = str(Path(_GECICI) / "ayar")
os.environ["XDG_DATA_HOME"] = str(Path(_GECICI) / "veri")

from asistan import connections, ctxprobe, keystore, power, profiles  # noqa: E402
from asistan.cekirdek import ayar, profil, uzak  # noqa: E402
from asistan.cekirdek.analiz import hata  # noqa: E402


class C1AtomikYazim(unittest.TestCase):
    def test_atomik_yaz_yarim_dosya_birakmaz(self):
        yol = Path(tempfile.mkdtemp()) / "a.json"
        ayar.atomik_yaz(yol, '{"a": 1}', mod=0o600)
        self.assertEqual(json.loads(yol.read_text(encoding="utf-8")), {"a": 1})
        self.assertEqual(stat.S_IMODE(yol.stat().st_mode), 0o600)
        with mock.patch.object(ayar.os, "replace", side_effect=OSError("disk dolu")):
            with self.assertRaises(OSError):
                ayar.atomik_yaz(yol, '{"a": 2}')
        self.assertEqual(json.loads(yol.read_text(encoding="utf-8")), {"a": 1})  # eski içerik bozulmadı
        self.assertEqual([p.name for p in yol.parent.iterdir()], ["a.json"])  # .tmp artığı yok

    def test_ayarlar_json_atomik(self):
        s = ayar.Settings(workspace=str(Path(_GECICI) / "is"))
        s.save()
        eski = ayar.CONFIG_FILE.read_text(encoding="utf-8")
        s.workspace = str(Path(_GECICI) / "baska")
        with mock.patch.object(ayar.os, "replace", side_effect=OSError("kesildi")):
            with self.assertRaises(OSError):
                s.save()
        self.assertEqual(ayar.CONFIG_FILE.read_text(encoding="utf-8"), eski)
        s.save()
        self.assertIn("baska", ayar.CONFIG_FILE.read_text(encoding="utf-8"))

    def test_bozuk_ayarlar_kenara_alinir(self):
        ayar.CONFIG_DIR.mkdir(parents=True, exist_ok=True)
        ayar.CONFIG_FILE.write_text('{"workspace": "x", ', encoding="utf-8")  # kesik JSON
        s = ayar.Settings.load()
        self.assertNotEqual(s.workspace, "x")
        self.assertFalse(ayar.CONFIG_FILE.exists())  # varsayılanlar sessizce kalıcılaşmaz: dosya kenara alındı
        bozuk = [p for p in ayar.CONFIG_DIR.iterdir() if p.name.startswith("ayarlar.json.bozuk-")]
        self.assertEqual(len(bozuk), 1)
        self.assertIn('"workspace": "x"', bozuk[0].read_text(encoding="utf-8"))
        bozuk[0].unlink()

    def test_diger_dosyalar_atomik(self):
        """anahtarlar.json, baglantilar.json, ajanlar.json, senkron.json, hata desenleri: yazma kesilirse eski kalır."""
        keystore._write_fallback({"k": "1"})
        connections.save_connections([])
        profiles.save_profiles([])
        uzak._senkron_yaz({"son": 1})
        hata.desen_ekle("ag", r"k12-test-\d+", "test")
        dosyalar = [keystore.FALLBACK_FILE, connections.CONNECTIONS_FILE, profiles.PROFILES_FILE, uzak._senkron_dosyasi(),
                    hata._desen_dosyasi()]
        eski = {d: d.read_text(encoding="utf-8") for d in dosyalar}
        with mock.patch.object(ayar.os, "replace", side_effect=OSError("kesildi")):
            for cagri in (lambda: keystore._write_fallback({"k": "2"}), lambda: connections.save_connections([]),
                          lambda: profiles.save_profiles([]), lambda: uzak._senkron_yaz({"son": 2}),
                          lambda: hata.desen_ekle("ag", r"k12-test-2-\d+", "test")):
                try:
                    cagri()
                except OSError:
                    pass
        for d in dosyalar:
            self.assertEqual(d.read_text(encoding="utf-8"), eski[d], d)
            self.assertFalse(list(d.parent.glob("*.tmp")), d)


class C2KademeKilidi(unittest.TestCase):
    def test_kilit_verilen_ayar_nesnesine_yazilir(self):
        s = ayar.Settings(workspace=str(Path(_GECICI) / "is"))
        with mock.patch.object(ayar.Settings, "load") as load, mock.patch.object(ayar.Settings, "save") as save, \
                mock.patch.object(profil, "yukle", return_value=None):
            profil.kilitle("orta", ayarlar=s)
        load.assert_not_called()  # ayrı bir örnek açılıp GUI'nin ayarı ezilmez
        save.assert_called_once()
        self.assertEqual(s.extra[profil.UI_KILIT_ANAHTARI], "orta")
        with mock.patch.object(ayar.Settings, "save"), mock.patch.object(profil, "yukle", return_value=None):
            profil.kilitle(None, ayarlar=s)
        self.assertNotIn(profil.UI_KILIT_ANAHTARI, s.extra)


class C3ModelBasinaBaglam(unittest.TestCase):
    def _ayar(self, model: str) -> SimpleNamespace:
        return SimpleNamespace(ollama_model=model, ollama_num_ctx=32768, ollama_url="http://127.0.0.1:11434",
                               power_mode="performans", ctx_probe={"kucuk:2b|12227": {"ctx": 32768, "max": 32768, "gpu": True}})

    def test_olculmemis_modelde_tahmin(self):
        with mock.patch.object(ctxprobe, "gpu_total_mib", return_value=12227), \
                mock.patch.object(ctxprobe, "tahmin", return_value={"ctx": 10240, "max": 32768, "gpu": False, "vram": 12227,
                                                                    "tahmin": True}) as tahmin, \
                mock.patch.object(profil, "acik_mi", return_value=True), mock.patch.object(power, "saving", return_value=False):
            s = self._ayar("buyuk:14b")
            self.assertEqual(power.num_ctx(s), 10240)
            self.assertEqual(power.num_ctx(s), 10240)  # önbellekten
            tahmin.assert_called_once()
            self.assertIn("buyuk:14b|12227", s.ctx_probe)
            self.assertEqual(power.num_ctx(self._ayar("kucuk:2b")), 32768)  # ölçülen model: eskisi gibi

    def test_ollama_kapaliyken_tek_deneme(self):
        power._tahmin_hatalari.clear()
        with mock.patch.object(ctxprobe, "gpu_total_mib", return_value=12227), \
                mock.patch.object(ctxprobe, "tahmin", side_effect=OSError("ollama yok")) as tahmin, \
                mock.patch.object(profil, "acik_mi", return_value=True), mock.patch.object(power, "saving", return_value=False):
            s = self._ayar("buyuk:14b")
            self.assertEqual(power.num_ctx(s), 32768)  # tahmin yok: genel ayar
            self.assertEqual(power.num_ctx(s), 32768)
            tahmin.assert_called_once()  # her etiket güncellemesinde Ollama'ya gidilmez

    def test_tahmin_hesabi(self):
        show = {"model_info": {"general.architecture": "qwen2", "qwen2.context_length": 32768, "qwen2.block_count": 48,
                               "qwen2.attention.head_count": 40, "qwen2.attention.head_count_kv": 8,
                               "qwen2.embedding_length": 5120}}
        tags = {"models": [{"name": "buyuk:14b", "size": 9_000_000_000}, {"name": "kucuk:2b", "size": 2_700_000_000}]}
        post = mock.Mock(return_value=SimpleNamespace(json=lambda: show, raise_for_status=lambda: None))
        get = mock.Mock(return_value=SimpleNamespace(json=lambda: tags, raise_for_status=lambda: None))
        with mock.patch.object(ctxprobe.httpx, "post", post), mock.patch.object(ctxprobe.httpx, "get", get):
            buyuk = ctxprobe.tahmin("http://x", "buyuk:14b", 12227)
            kucuk = ctxprobe.tahmin("http://x", "kucuk:2b", 12227)
        self.assertEqual(buyuk["ctx"], 9216)  # (12227 MiB·0.9 − 9 GB − 0.5 GB) / 196.608 KB ≈ 10.2K → 1K'ya aşağı yuvarlanır
        self.assertTrue(buyuk["tahmin"])
        self.assertEqual(kucuk["ctx"], 32768)  # model sınırı
        self.assertEqual(buyuk["max"], 32768)


if __name__ == "__main__":
    unittest.main()
