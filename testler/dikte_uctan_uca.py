"""Dikte uçtan uca: piper (Türkçe ses, ör. tr_TR-dfki-medium) bir cümle seslendirir, dikte (faster-whisper) onu yazıya
çevirir; ikinci çeviri model bellekteyken daha hızlı olmalı. Piper ve ses dosyası gerektirdiği için unittest'e
(test_*.py) girmez (2026-09-27'ye kadar test_dikte.py'deydi, yayında hep atlanıyordu); dikteye dokunan bir
değişiklikten sonra elle çalıştırılır. Dikte modeli gerçek kurulumdan okunur (yalnızca okunur):

    YA_PIPER_SES=/yol/tr_TR-dfki-medium.onnx ~/.local/share/yeni-nesil-cafer-app/python/bin/python3 testler/dikte_uctan_uca.py -v
"""

import os
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path

KOK = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(KOK))
_GECICI = tempfile.mkdtemp(prefix="yeni-nesil-cafer-test-")
os.environ["XDG_CONFIG_HOME"] = str(Path(_GECICI) / "ayar")  # kullanıcının gerçek ayar ve verisine dokunulmaz
os.environ["XDG_DATA_HOME"] = str(Path(_GECICI) / "veri")

from asistan import dictation as d  # noqa: E402
from asistan.tools import agent_env, python_exe  # noqa: E402

d.MODEL_DIR = Path.home() / ".local/share/yeni-nesil-cafer/dikte-modeli"  # indirilmiş gerçek model
CUMLE = "Merhaba, yarın sabah saat dokuzda toplantımız var."


def _piper_sesi() -> str:
    ses = os.environ.get("YA_PIPER_SES", "")
    return ses if ses and Path(ses).exists() else ""


class UctanUcaTesti(unittest.TestCase):
    def test_turkce_cumle_yaziya_cevrilir(self):
        wav = Path(tempfile.mkdtemp()) / "cumle.wav"
        subprocess.run([python_exe(), "-m", "piper", "-m", _piper_sesi(), "-f", str(wav)], input=CUMLE, text=True,
                       env=agent_env(), check=True, capture_output=True)
        started = time.monotonic()
        result = d.SERVER.transcribe(str(wav), "tr")
        ilk = time.monotonic() - started
        started = time.monotonic()
        tekrar = d.SERVER.transcribe(str(wav), "tr")  # model bellekte: çok daha hızlı
        ikinci = time.monotonic() - started
        d.SERVER.stop()
        print(f"\n  cihaz: {result.get('device')}  ilk: {ilk:.1f} sn (model yükleme dahil)  ikinci: {ikinci:.1f} sn"
              f"\n  metin: {result.get('text')}")
        self.assertNotIn("error", result)
        metin = result["text"].lower()
        for kelime in ("merhaba", "yarın", "toplantı"):
            self.assertIn(kelime, metin)
        self.assertEqual(tekrar["text"], result["text"])
        self.assertLess(ikinci, ilk)


if __name__ == "__main__":
    if not _piper_sesi():
        sys.exit("YA_PIPER_SES bir piper sesinin .onnx dosyasını göstermeli.")
    if not (d.MODEL_DIR / "model.bin").exists():
        sys.exit(f"dikte modeli yok: {d.MODEL_DIR} (programda Ayarlar → Dikte ile indir)")
    unittest.main()
