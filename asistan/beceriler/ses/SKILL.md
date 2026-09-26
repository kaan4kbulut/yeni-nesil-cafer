---
name: ses
description: Ses kaydını / videonun sesini yazıya çevirme (zaman damgalı) ve metni Türkçe seslendirme (wav)
---
# Speech to text and text to speech (local, tested)

Speech to text — faster-whisper with the program's own downloaded model (do not download another copy):
```python
from pathlib import Path
from faster_whisper import WhisperModel
dirs = [Path.home() / ".local/share/yeni-nesil-cafer/dikte-modeli"]   # also the program's "modeller/dikte" folder
model = next((str(d) for d in dirs if (d / "model.bin").exists()), "large-v3-turbo")
m = WhisperModel(model, device="cpu", compute_type="int8")
segments, info = m.transcribe("kayit.m4a", language="tr", vad_filter=True)   # mp3, m4a, wav, mp4 all work
with open("kayit.txt", "w", encoding="utf-8") as f:
    for s in segments:
        f.write(f"[{s.start:6.1f} – {s.end:6.1f}] {s.text.strip()}\n")
```
On the CPU the model needs ~5 s per 30 s of audio: tell the user roughly how long a long recording will take.
Language unknown: `language=None` (then `info.language`). Subtitles: write the same segments as .srt
(`00:00:01,000 --> 00:00:03,000`).

Text to speech — piper; the ONLY Turkish voice is tr_TR-dfki-medium (there is no "fahrettin"):
```python
import subprocess, sys, urllib.request
from pathlib import Path
ses = Path("sesler"); ses.mkdir(exist_ok=True)
base = "https://huggingface.co/rhasspy/piper-voices/resolve/main/tr/tr_TR/dfki/medium/"
for name in ("tr_TR-dfki-medium.onnx", "tr_TR-dfki-medium.onnx.json"):
    if not (ses / name).exists():
        urllib.request.urlretrieve(base + name, ses / name)
subprocess.run([sys.executable, "-m", "piper", "-m", str(ses / "tr_TR-dfki-medium.onnx"), "-f", "okuma.wav"],
               input="Okunacak metin.", text=True, check=True)
```
English voices: en_US-lessac-medium (same URL pattern under en/en_US/lessac/medium/). Long texts: one wav per
paragraph, then join. Never clone or imitate a real person's voice.
