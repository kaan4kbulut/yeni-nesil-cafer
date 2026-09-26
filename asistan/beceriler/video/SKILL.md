---
name: video
description: Kısa video oluşturma (MP4/GIF): animasyon, resimlerden slayt gösterisi, yazı, ses ekleme
---
# Video with imageio + imageio-ffmpeg (tested; ffmpeg comes inside the pip package, also on Windows)

If `import imageio_ffmpeg` fails: install_python_package "imageio imageio-ffmpeg". Put results in Video/.
Frame size must be a multiple of 16 (1280x720, 1920x1080). Real AI video generation is not available locally:
make videos from frames you draw (matplotlib, Pillow) or from images/photos.

Animation (matplotlib frames → MP4):
```python
from pathlib import Path
import numpy as np, imageio.v2 as imageio, matplotlib
matplotlib.use("Agg"); import matplotlib.pyplot as plt
out = Path("Video"); out.mkdir(exist_ok=True)
W, H, FPS = 1280, 720, 30
writer = imageio.get_writer(out / "animasyon.mp4", fps=FPS, codec="libx264", quality=8)
fig, ax = plt.subplots(figsize=(W / 100, H / 100), dpi=100)
x = np.linspace(0, 2 * np.pi, 200)
for i in range(FPS * 5):                                  # 5 seconds
    ax.clear(); ax.plot(x, np.sin(x + i / 10)); ax.set_ylim(-1.2, 1.2)
    fig.canvas.draw(); writer.append_data(np.asarray(fig.canvas.buffer_rgba())[:, :, :3])
writer.close(); plt.close(fig)
```

Slide show with Turkish text (Pillow; DejaVu font has ç ğ ı İ ö ş ü):
```python
from PIL import Image, ImageDraw, ImageFont
font = ImageFont.truetype(str(Path(matplotlib.get_data_path()) / "fonts/ttf/DejaVuSans-Bold.ttf"), 60)
w = imageio.get_writer(out / "slayt.mp4", fps=FPS, codec="libx264", quality=8)
for path_or_color, caption in slides:                    # a photo path or a colour like "#1e3a8a"
    img = Image.open(path_or_color).convert("RGB").resize((W, H)) if Path(str(path_or_color)).exists() \
        else Image.new("RGB", (W, H), path_or_color)
    ImageDraw.Draw(img).text((W / 2, H - 80), caption, font=font, fill="white", anchor="mm",
                             stroke_width=3, stroke_fill="black")
    for _ in range(FPS * 3): w.append_data(np.asarray(img))     # 3 s per slide
w.close()
```

GIF: `imageio.mimsave(out / "kisa.gif", frames, duration=0.5, loop=0)` (keep it small: ≤ 480 px, ≤ 60 frames).

Add sound or a voice-over (voice: see the "ses" skill, piper tr_TR-dfki-medium):
```python
import subprocess, imageio_ffmpeg
ff = imageio_ffmpeg.get_ffmpeg_exe()
subprocess.run([ff, "-y", "-loglevel", "error", "-i", "Video/slayt.mp4", "-i", "anlatim.wav",
                "-c:v", "copy", "-c:a", "aac", "-shortest", "Video/slayt-sesli.mp4"], check=True)
```
The same ffmpeg can cut (`-ss 5 -t 10`), join, resize (`-vf scale=1280:-2`) or convert existing videos.

Finish with inspect_output on the video (it looks at a middle frame) and give length, size and file name.
