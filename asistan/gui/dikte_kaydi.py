"""Dikte kaydı (Qt): mikrofon → WAV → `dictation` (yazıya çevirme ve temizleme, Qt'siz çekirdek tarafı).

K1'de `asistan/dictation.py`'den ayrıldı: ses kaydı QtMultimedia istediği için arayüzde durur.
"""

import array
import tempfile
import threading
import time
import wave
from pathlib import Path

from PySide6.QtCore import QObject, QTimer, Signal

from ..dictation import MAX_SECONDS, SERVER, clean


class Dictation(QObject):
    """Mesaj kutusu dikte düğmesinin arkası: start → stop (yazıya çevir) ya da cancel."""

    level = Signal(float, float)  # (0-1 ses seviyesi, geçen saniye)
    busy = Signal(str)  # "kayıt" · "çeviriliyor" · "temizleniyor" · "" (bitti)
    text_ready = Signal(str)
    failed = Signal(str)
    _done = Signal(str, str)  # iş parçacığından: (metin, hata)

    def __init__(self, settings_fn, installed_models_fn, parent=None):
        super().__init__(parent)
        self.settings_fn, self.installed_models_fn = settings_fn, installed_models_fn
        self.source = None
        self.io = None
        self.data = bytearray()
        self.fmt = None
        self.started = 0.0
        self.recording = False
        self.working = False
        self.timer = QTimer(self)
        self.timer.setInterval(100)
        self.timer.timeout.connect(self._tick)
        self._done.connect(self._finished)

    def start(self) -> None:
        from PySide6.QtMultimedia import QAudioFormat, QAudioSource, QMediaDevices

        if self.recording or self.working:
            return
        device = QMediaDevices.defaultAudioInput()
        if device.isNull():
            self.failed.emit("Mikrofon bulunamadı. Sistem ayarlarından bir mikrofon seçip tekrar dene.")
            return
        fmt = QAudioFormat()
        fmt.setSampleRate(16000)
        fmt.setChannelCount(1)
        fmt.setSampleFormat(QAudioFormat.SampleFormat.Int16)
        if not device.isFormatSupported(fmt):
            fmt = device.preferredFormat()
        self.fmt = fmt
        self.source = QAudioSource(device, fmt, self)
        self.data = bytearray()
        self.io = self.source.start()
        if self.io is None:
            self.failed.emit("Mikrofon açılamadı (başka bir program kullanıyor olabilir).")
            return
        self.io.readyRead.connect(self._read)
        threading.Thread(target=SERVER.warm, daemon=True).start()
        self.recording = True
        self.started = time.monotonic()
        self.timer.start()
        self.busy.emit("kayıt")

    def _read(self):
        if self.io is not None:
            self.data += bytes(self.io.readAll())

    def _samples(self, raw: bytes) -> array.array:
        """Ham ses → 16 bit tamsayılar (mikrofon float ya da 32 bit verebilir)."""
        from PySide6.QtMultimedia import QAudioFormat

        kind = self.fmt.sampleFormat()
        if kind == QAudioFormat.SampleFormat.Float:
            src = array.array("f", raw[: len(raw) // 4 * 4])
            return array.array("h", (max(-32768, min(32767, int(x * 32767))) for x in src))
        if kind == QAudioFormat.SampleFormat.Int32:
            src = array.array("i", raw[: len(raw) // 4 * 4])
            return array.array("h", (x >> 16 for x in src))
        if kind == QAudioFormat.SampleFormat.UInt8:
            return array.array("h", ((b - 128) << 8 for b in raw))
        return array.array("h", raw[: len(raw) // 2 * 2])

    def _tick(self):
        seconds = time.monotonic() - self.started
        tail = bytes(self.data[-int(self.fmt.bytesPerFrame() * self.fmt.sampleRate() * 0.1):]) if self.data else b""
        samples = self._samples(tail) if tail else []
        peak = max((abs(s) for s in samples), default=0) / 32768
        self.level.emit(min(1.0, peak * 1.5), seconds)
        if seconds >= MAX_SECONDS:
            self.stop()

    def _close(self):
        self.timer.stop()
        self._read()
        if self.source is not None:
            self.source.stop()
        self.source, self.io = None, None
        self.recording = False

    def cancel(self) -> None:
        if self.recording:
            self._close()
            self.data = bytearray()
            self.busy.emit("")

    def stop(self) -> None:
        if not self.recording:
            return
        self._close()
        if time.monotonic() - self.started < 0.4 or not self.data:
            self.busy.emit("")
            return
        wav = Path(tempfile.gettempdir()) / f"yeni-nesil-cafer-dikte-{int(time.time() * 1000)}.wav"
        samples = self._samples(bytes(self.data))
        with wave.open(str(wav), "wb") as w:
            w.setnchannels(self.fmt.channelCount())
            w.setsampwidth(2)
            w.setframerate(self.fmt.sampleRate())
            w.writeframes(samples.tobytes())
        self.data = bytearray()
        self.working = True
        self.busy.emit("çeviriliyor")
        threading.Thread(target=self._work, args=(str(wav),), daemon=True).start()

    def _work(self, wav: str):
        settings = self.settings_fn()
        extra = settings.extra or {}
        try:
            result = SERVER.transcribe(wav, extra.get("dikte_dil", "tr") or None)
            if result.get("error"):
                raise RuntimeError(result["error"])
            text = result.get("text", "")
            if text and extra.get("dikte_temizle", True):
                self.busy.emit("temizleniyor")
                text = clean(text, settings.ollama_url, self.installed_models_fn())
            self._done.emit(text, "")
        except Exception as e:
            self._done.emit("", str(e))
        finally:
            Path(wav).unlink(missing_ok=True)

    def _finished(self, text: str, error: str):
        self.working = False
        self.busy.emit("")
        if error:
            self.failed.emit(error)
        elif text:
            self.text_ready.emit(text)
        else:
            self.failed.emit("Konuşma anlaşılamadı (ses çok kısa ya da sessiz olabilir).")

    def shutdown(self):
        self.cancel()
        SERVER.stop()
