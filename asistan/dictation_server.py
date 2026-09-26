"""Dikte: sesi yazıya çeviren arka plan süreci (faster-whisper). Tek başına çalışan betik: `dictation.py` başlatır.

Ajanların Python'u ve kütüphane klasörleriyle çalışır (tools.python_exe / agent_env): faster-whisper programın
kendi paketlerinden değil, ajan kütüphanelerinden gelir; arayüz süreci ağır kütüphaneleri yüklemez, bir çökme de
programı düşürmez. Model bir kez yüklenir ve istek beklenir; IDLE saniye istek gelmezse süreç kapanır (bellek boşalır).

Protokol (satır satır JSON): stdin {"wav": yol, "language": "tr" | null} → stdout {"text", "seconds", "device"} ya da
{"error"}. Başlarken bir kez {"ready": true, "device": …} yazar.
Kullanım: python dictation_server.py <model adı ya da klasörü>
"""

import json
import os
import select
import sys
import time

IDLE = 300


def say(obj):
    sys.stdout.write(json.dumps(obj, ensure_ascii=False) + "\n")
    sys.stdout.flush()


def load(name: str):
    from faster_whisper import WhisperModel

    # ekran kartı: hızlı ama Ollama ile belleği paylaşır; CUDA kütüphaneleri yoksa işlemci (int8, yeterince hızlı)
    if os.environ.get("DIKTE_CPU") != "1":
        try:
            model = WhisperModel(name, device="cuda", compute_type="int8_float16")
            # model kartta açılabiliyor ama libcublas eksikse hata ilk çeviride çıkıyor: bir saniyelik sessizlikle dene
            import numpy

            list(model.transcribe(numpy.zeros(16000, dtype=numpy.float32), language="tr")[0])
            return model, "gpu"
        except Exception:
            pass
    threads = max(1, (os.cpu_count() or 4) - 2)
    return WhisperModel(name, device="cpu", compute_type="int8", cpu_threads=threads), "cpu"


def main():
    try:
        model, device = load(sys.argv[1])
    except Exception as e:
        say({"error": f"model yüklenemedi: {type(e).__name__}: {e}"})
        return
    say({"ready": True, "device": device})
    while True:
        ready, _, _ = select.select([sys.stdin], [], [], IDLE) if os.name != "nt" else ([sys.stdin], [], [])
        if not ready:
            return  # uzun süre istek gelmedi: kapan, bellek boşalsın
        line = sys.stdin.readline()
        if not line:
            return
        try:
            req = json.loads(line)
            started = time.monotonic()
            segments, _info = model.transcribe(req["wav"], language=req.get("language") or None, beam_size=5,
                                               vad_filter=True, condition_on_previous_text=False)
            text = " ".join(s.text.strip() for s in segments).strip()
            say({"text": text, "seconds": round(time.monotonic() - started, 2), "device": device})
        except Exception as e:
            say({"error": f"{type(e).__name__}: {e}"})


if __name__ == "__main__":
    main()
