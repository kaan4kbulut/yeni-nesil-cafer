"""Dikte (asistan/dictation.py) testleri.

Uçtan uca test gerçek sesle çalışır: piper (Türkçe ses tr_TR-dfki-medium) bir cümle seslendirir, dikte onu
yazıya çevirir. Piper, ses dosyaları ya da ses modeli yoksa o test atlanır; YA_PIPER_SES ortam değişkeni sesin
.onnx dosyasını gösterir.

Çalıştırma (proje kökünde, programın Python'uyla):
    ~/.local/share/yeni-nesil-cafer-app/python/bin/python3 -m unittest discover -s testler -v
"""

import array
import os
import subprocess
import sys
import tempfile
import time
import unittest
import wave
from pathlib import Path
from unittest import mock

KOK = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(KOK))
_GECICI = tempfile.mkdtemp(prefix="yeni-nesil-cafer-test-")
os.environ["XDG_CONFIG_HOME"] = str(Path(_GECICI) / "ayar")  # kullanıcının gerçek ayar ve verisine dokunulmaz
os.environ["XDG_DATA_HOME"] = str(Path(_GECICI) / "veri")
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtMultimedia import QAudioFormat  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

APP = QApplication.instance() or QApplication([])

from asistan import dictation as d  # noqa: E402
from asistan.config import Settings  # noqa: E402
from asistan.tools import agent_env, python_exe  # noqa: E402

CUMLE = "Merhaba, yarın sabah saat dokuzda toplantımız var."


def dikte(fmt_kind=QAudioFormat.SampleFormat.Int16) -> d.Dictation:
    x = d.Dictation(lambda: Settings(), lambda: [])
    x.fmt = QAudioFormat()
    x.fmt.setSampleRate(16000)
    x.fmt.setChannelCount(1)
    x.fmt.setSampleFormat(fmt_kind)
    return x


class _Cevap:
    def __init__(self, text):
        self.text = text

    def raise_for_status(self):
        pass

    def json(self):
        return {"message": {"content": self.text}}


class DikteTesti(unittest.TestCase):
    def test_ses_bicimleri_16_bite_cevrilir(self):
        x = dikte(QAudioFormat.SampleFormat.Float)
        raw = array.array("f", [0.0, 0.5, -1.0, 1.5]).tobytes()
        self.assertEqual(list(x._samples(raw)), [0, 16383, -32767, 32767])
        x = dikte(QAudioFormat.SampleFormat.Int32)
        self.assertEqual(list(x._samples(array.array("i", [65536 * 100, -65536 * 5]).tobytes())), [100, -5])
        x = dikte()
        self.assertEqual(list(x._samples(array.array("h", [1, -2, 3]).tobytes() + b"\x00")), [1, -2, 3])

    def test_temizleme_metni_bozarsa_ham_metin(self):
        ham = "ıı yarın sabah ee toplantı var var mı"
        with mock.patch.object(d.httpx, "post", return_value=_Cevap("Yarın sabah toplantı var mı?")):
            self.assertEqual(d.clean(ham, "http://x", ["qwen3.5:4b"]), "Yarın sabah toplantı var mı?")
        uzun = "Evet, yarın sabah saat dokuzda toplantınız var. Size bir hatırlatıcı kurmamı ister misiniz? " * 2
        with mock.patch.object(d.httpx, "post", return_value=_Cevap(uzun)):  # cevap vermeye kalktı
            self.assertEqual(d.clean(ham, "http://x", ["qwen3.5:4b"]), ham)
        with mock.patch.object(d.httpx, "post") as post:  # temizleme modeli kurulu değil
            self.assertEqual(d.clean(ham, "http://x", ["llama3.1:latest"]), ham)
            post.assert_not_called()

    def test_cok_kisa_kayit_yok_sayilir(self):
        x = dikte()
        durum = []
        x.busy.connect(durum.append)
        x.recording, x.started, x.data = True, time.monotonic(), bytearray(b"\x00\x01" * 100)
        with mock.patch("asistan.dictation.threading.Thread") as thread:
            x.stop()
        thread.assert_not_called()
        self.assertEqual(durum, [""])

    def test_kayit_wav_olarak_yazilir_ve_cevrilir(self):
        x = dikte()
        x.recording, x.started = True, time.monotonic() - 2
        x.data = bytearray(array.array("h", [0, 1000, -1000] * 16000).tobytes())
        yazilan = {}

        def calis(target, args, daemon):
            with wave.open(args[0]) as w:
                yazilan.update(rate=w.getframerate(), frames=w.getnframes(), channels=w.getnchannels())
            Path(args[0]).unlink()
            return mock.Mock()

        with mock.patch("asistan.dictation.threading.Thread", side_effect=calis):
            x.stop()
        self.assertEqual(yazilan, {"rate": 16000, "frames": 48000, "channels": 1})
        self.assertTrue(x.working)


class AyarTesti(unittest.TestCase):
    def test_dikte_ayarlari_pencerede_kaydedilir(self):
        from asistan.gui.dialogs import SettingsDialog

        s = Settings()
        d_ = SettingsDialog(s)
        self.assertEqual((d_.dictation_lang.currentData(), d_.dictation_clean.isChecked()), ("tr", True))
        d_.dictation_lang.setCurrentIndex(d_.dictation_lang.findData(""))
        d_.dictation_clean.setChecked(False)
        d_.apply_to(s)
        self.assertEqual((s.extra["dikte_dil"], s.extra["dikte_temizle"]), ("", False))
        again = SettingsDialog(s)
        self.assertEqual((again.dictation_lang.currentData(), again.dictation_clean.isChecked()), ("", False))


def _piper_sesi() -> str:
    ses = os.environ.get("YA_PIPER_SES", "")
    return ses if ses and Path(ses).exists() else ""


@unittest.skipUnless(_piper_sesi() and (d.MODEL_DIR / "model.bin").exists(),
                     "piper sesi (YA_PIPER_SES) ya da dikte modeli yok")
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
    unittest.main()
