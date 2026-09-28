"""Dikte: mesaj kutusu için konuşmayı yazıya çevirme (mikrofon → faster-whisper → isteğe bağlı temizleme).

Kayıt Qt ile (QtMultimedia; ek program gerekmez) arayüzde: `gui/dikte_kaydi.py` (`Dictation`); mikrofonun kendi
biçiminde WAV'a yazılır (faster-whisper kendisi 16 kHz'e çevirir). Bu modül Qt bilmez (K1).
Yazıya çevirme `dictation_server.py` sürecinde: ilk kullanımda başlar, model bellekte bekler.
Temizleme (ııı, tekrarlar, noktalama) küçük yerel modelle (Ollama); kapatılabilir, olmazsa ham metin kullanılır.
Ayarlar (Settings.extra): dikte_model, dikte_dil ("tr"; boş: kendisi bulur), dikte_temizle (True).
"""

import json
import subprocess
import threading
from pathlib import Path

import httpx

from . import eski
from .cekirdek import modeller
from .config import DATA_DIR

MODEL = "large-v3-turbo"  # Türkçede iyi, large-v3'ten ~6 kat hızlı
MODEL_DIR = DATA_DIR / "dikte-modeli"  # indirilmiş model (yoksa faster-whisper kendi önbelleğine indirir)
BUNDLED_DIR = Path(__file__).resolve().parent.parent / "modeller" / "dikte"  # kurulum paketine gömülü model
MAX_SECONDS = 300  # tek kayıt en çok 5 dakika
CLEAN_MODELS = tuple(modeller.deger("dikte_temizleme"))  # temizleme için küçük ve hızlı olan önce (modeller.json)

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


__getattr__ = eski.yonlendir(__name__)  # dictation.Dictation → gui.dikte_kaydi.Dictation (uyarıyla)
