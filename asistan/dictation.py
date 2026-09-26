"""Dikte: mesaj kutusu için konuşmayı yazıya çevirme (mikrofon → faster-whisper → isteğe bağlı temizleme).

Kayıt Qt ile (QtMultimedia; ek program gerekmez), mikrofonun kendi biçiminde WAV'a yazılır (faster-whisper kendisi
16 kHz'e çevirir). Yazıya çevirme `dictation_server.py` sürecinde: ilk kullanımda başlar, model bellekte bekler.
Temizleme (ııı, tekrarlar, noktalama) küçük yerel modelle (Ollama); kapatılabilir, olmazsa ham metin kullanılır.
Ayarlar (Settings.extra): dikte_model, dikte_dil ("tr"; boş: kendisi bulur), dikte_temizle (True).
"""

import array
import json
import subprocess
import tempfile
import threading
import time
import wave
from pathlib import Path

import httpx
from PySide6.QtCore import QObject, QTimer, Signal

from .config import DATA_DIR

MODEL = "large-v3-turbo"  # Türkçede iyi, large-v3'ten ~6 kat hızlı
MODEL_DIR = DATA_DIR / "dikte-modeli"  # indirilmiş model (yoksa faster-whisper kendi önbelleğine indirir)
BUNDLED_DIR = Path(__file__).resolve().parent.parent / "modeller" / "dikte"  # kurulum paketine gömülü model
MAX_SECONDS = 300  # tek kayıt en çok 5 dakika
CLEAN_MODELS = ("qwen3.5:4b", "qwen3.5:9b", "gemma4:12b")  # temizleme için küçük ve hızlı olan önce

CLEAN_PROMPT = (
    "Below is a raw speech-to-text transcript. Return it cleaned up: fix punctuation and capitalisation, remove "
    "filler sounds (ıı, ee, hmm, şey used as filler) and accidental repetitions, keep the speaker's words, meaning "
    "and language exactly. Do not answer it, summarise it, translate it or add anything. Output only the cleaned "
    "text.\n\nTranscript:\n")


def model_source() -> str:
    """Pakete gömülü ya da önceden indirilmiş model klasörü; ikisi de yoksa adı (ilk kullanımda indirilir)."""
    return next((str(d) for d in (BUNDLED_DIR, MODEL_DIR) if (d / "model.bin").exists()), MODEL)


def installed() -> bool:
    """faster-whisper ajan kütüphanelerinde kurulu mu? (programın kendi paketleri arasında değil)"""
    from .tools import agent_env, python_exe

    out = subprocess.run([python_exe(), "-c", "import faster_whisper"], env=agent_env(), capture_output=True)
    return out.returncode == 0


class _Server:
    """dictation_server.py süreci: bir istek, bir cevap (aynı anda tek istek)."""

    def __init__(self):
        self.proc: subprocess.Popen | None = None
        self.device = ""
        self.lock = threading.Lock()

    def _start(self):
        from .tools import NO_WINDOW, agent_env, python_exe

        script = Path(__file__).with_name("dictation_server.py")
        self.proc = subprocess.Popen([python_exe(), str(script), model_source()], stdin=subprocess.PIPE,
                                     stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True, encoding="utf-8",
                                     env=agent_env(), creationflags=NO_WINDOW)
        first = json.loads(self.proc.stdout.readline() or '{"error": "dikte süreci açılamadı"}')
        if first.get("error"):
            self.stop()
            raise RuntimeError(first["error"])
        self.device = first.get("device", "")

    def warm(self):
        """Kayıt başlarken modeli yükler: kullanıcı konuşurken hazır olsun (işlemcide yükleme ~5 sn)."""
        with self.lock:
            if self.proc is None or self.proc.poll() is not None:
                try:
                    self._start()
                except Exception:
                    pass  # hata, çeviri sırasında yeniden denenip kullanıcıya gösterilir

    def transcribe(self, wav: str, language: str | None) -> dict:
        with self.lock:
            for attempt in range(2):  # süreç boşta kalıp kapandıysa bir kez yeniden başlat
                if self.proc is None or self.proc.poll() is not None:
                    self._start()
                try:
                    self.proc.stdin.write(json.dumps({"wav": wav, "language": language}) + "\n")
                    self.proc.stdin.flush()
                    line = self.proc.stdout.readline()
                except (BrokenPipeError, OSError):
                    line = ""
                if line:
                    return json.loads(line)
                self.stop()
            raise RuntimeError("dikte süreci cevap vermedi")

    def stop(self):
        if self.proc is not None:
            try:
                self.proc.kill()
                self.proc.wait(5)
            except (OSError, subprocess.TimeoutExpired):
                pass
            for pipe in (self.proc.stdin, self.proc.stdout):
                if pipe:
                    pipe.close()
            self.proc = None


SERVER = _Server()


def clean(text: str, ollama_url: str, installed_models: list[str]) -> str:
    """Küçük yerel modelle temizler; model yoksa ya da cevap tuhafsa ham metin döner."""
    model = next((m for m in CLEAN_MODELS if m in installed_models), "")
    if not model or len(text) < 12:
        return text
    try:
        r = httpx.post(ollama_url.rstrip("/") + "/api/chat", json={
            "model": model, "messages": [{"role": "user", "content": CLEAN_PROMPT + text}], "stream": False,
            "think": False, "keep_alive": "10m", "options": {"temperature": 0, "num_predict": len(text) + 200}},
            timeout=60)
        r.raise_for_status()
        out = ((r.json().get("message") or {}).get("content") or "").strip().strip('"')
    except (httpx.HTTPError, ValueError):
        return text
    # model metni cevaplamaya ya da özetlemeye kalkarsa: uzunluk çok değiştiyse ham metin daha güvenli
    return out if out and 0.6 * len(text) <= len(out) <= 1.3 * len(text) + 20 else text


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
