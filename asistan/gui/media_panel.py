"""Sağ panel · Görsel sekmesi: üretilen resim, video ve 3D modelleri canlı izleme ve önizleme.

- Canlı: resim üretilirken (imagegen, `--preview proj`) her adımın ara görüntüsü ve ilerleme çubuğu (`live`).
- İzleme: sohbetin iş klasöründe yeni oluşan ya da değişen her medya dosyası (model run_python ile video kareleri,
  animasyon, STL yazarken de) birkaç saniye içinde gelir; "yenileri göster" açıksa hemen açılır.
- Önizleme: resim (hareketli GIF dahil), video (oynat / duraklat, döngü), 3D model (döndür / yakınlaştır, ölçüler).
- Galeri: klasördeki medya dosyaları, en yenisi başta; tıklayınca yukarıda açılır.
Video ve 3D görüntüleyici ilk gerektiğinde kurulur (açılışı yavaşlatmasın).
"""

import os
from pathlib import Path

from PySide6.QtCore import QSize, Qt, QTimer, QUrl, Signal
from PySide6.QtGui import QColor, QDesktopServices, QFont, QIcon, QMovie, QPainter, QPixmap
from PySide6.QtWidgets import (
    QCheckBox, QHBoxLayout, QLabel, QListWidget, QListWidgetItem, QProgressBar, QPushButton, QSlider,
    QStackedWidget, QVBoxLayout, QWidget,
)

from .theme import C

IMAGE = {".png", ".jpg", ".jpeg", ".webp", ".bmp", ".gif", ".svg"}
VIDEO = {".mp4", ".webm", ".mkv", ".mov", ".avi", ".m4v"}
MODEL = {".glb", ".gltf", ".obj", ".stl", ".ply"}
SCAN_MS = 1000  # klasör taraması aralığı
MAX_FILES = 300  # galerideki en çok dosya (en yeniler)
MAX_ENTRIES = 5000  # bir taramada bakılan en çok dosya/klasör (çalışma klasörünün kökü çok büyük olabilir)
MAX_DEPTH = 4
SKIP_DIRS = {".git", "__pycache__", ".venv", "venv", "node_modules"}
THUMB = 72


def media_kind(path: str | Path) -> str:
    suffix = Path(path).suffix.lower()
    return "image" if suffix in IMAGE else "video" if suffix in VIDEO else "model" if suffix in MODEL else ""


def scan(root: str) -> dict[str, tuple[float, int]]:
    """Klasördeki medya dosyaları: yol → (değişme zamanı, boyut). Gizli dosya ve klasörler atlanır
    (canlı önizleme dosyası `.canli-onizleme.png` gibi)."""
    found, seen = {}, 0
    base = Path(root)
    if not root or not base.is_dir():
        return found
    stack = [(base, 0)]
    while stack and seen < MAX_ENTRIES:
        folder, depth = stack.pop()
        try:
            entries = list(os.scandir(folder))
        except OSError:
            continue
        for e in entries:
            seen += 1
            if e.name.startswith("."):
                continue
            try:
                if e.is_dir(follow_symlinks=False):
                    if depth < MAX_DEPTH and e.name not in SKIP_DIRS:
                        stack.append((Path(e.path), depth + 1))
                elif media_kind(e.name):
                    st = e.stat()
                    found[e.path] = (st.st_mtime, st.st_size)
            except OSError:
                continue
    return found


def tile(kind: str, suffix: str) -> QPixmap:
    """Video ve 3D için galeri karesi: tür ve uzantı yazan küçük kare."""
    pix = QPixmap(THUMB, THUMB)
    pix.fill(QColor(C["surface2"]) if "surface2" in C else QColor("#2a2a30"))
    p = QPainter(pix)
    p.setRenderHint(QPainter.Antialiasing)
    p.setPen(QColor(C.get("accent", "#F2A93B")))
    font = QFont()
    font.setPixelSize(22)
    font.setBold(True)
    p.setFont(font)
    p.drawText(pix.rect().adjusted(0, -10, 0, 0), Qt.AlignCenter, "▶" if kind == "video" else "3D")
    font.setPixelSize(11)
    p.setFont(font)
    p.setPen(QColor(C.get("text2", "#aaa")))
    p.drawText(pix.rect().adjusted(0, 30, 0, 0), Qt.AlignCenter, suffix.upper().lstrip("."))
    p.end()
    return pix


class ImageView(QLabel):
    """Resmi alana sığdırır (büyütmez; canlı önizleme hariç); hareketli GIF oynar."""

    def __init__(self):
        super().__init__(alignment=Qt.AlignCenter)
        self.setMinimumSize(80, 80)
        self.pix = QPixmap()
        self.movie: QMovie | None = None
        self.upscale = False

    def show_path(self, path: str, upscale: bool = False) -> bool:
        """upscale: küçük resmi de alana büyüt (canlı önizleme 64×64 piksel gelir)."""
        if self.movie:
            self.movie.stop()
            self.movie = None
        if path.lower().endswith(".gif"):
            movie = QMovie(path)
            if movie.isValid() and movie.frameCount() != 1:
                self.movie = movie
                self.setMovie(movie)
                movie.frameChanged.connect(lambda _: self._fit_movie())
                movie.start()
                return True
        pix = QPixmap(path)
        if pix.isNull():  # yazılırken okundu (yarım dosya): eskisi kalsın
            return False
        self.pix = pix
        self.upscale = upscale
        self._fit()
        return True

    def _fit(self):
        if self.movie or self.pix.isNull():
            return
        w, h = max(1, self.width()), max(1, self.height())
        if self.upscale or self.pix.width() > w or self.pix.height() > h:
            self.setPixmap(self.pix.scaled(w, h, Qt.KeepAspectRatio, Qt.SmoothTransformation))
        else:
            self.setPixmap(self.pix)

    def _fit_movie(self):
        size = self.movie.currentPixmap().size()
        if size.isValid() and (size.width() > self.width() or size.height() > self.height()):
            self.movie.setScaledSize(size.scaled(self.size(), Qt.KeepAspectRatio))

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._fit()


class VideoView(QWidget):
    """Video: oynat / duraklat, konum çubuğu, döngü."""

    def __init__(self):
        super().__init__()
        from PySide6.QtMultimedia import QAudioOutput, QMediaPlayer
        from PySide6.QtMultimediaWidgets import QVideoWidget

        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        self.video = QVideoWidget()
        self.player = QMediaPlayer(self)
        self.audio = QAudioOutput(self)
        self.player.setAudioOutput(self.audio)
        self.player.setVideoOutput(self.video)
        self.player.setLoops(QMediaPlayer.Loops.Infinite)
        lay.addWidget(self.video, 1)
        row = QHBoxLayout()
        self.play = QPushButton("⏸", objectName="smallButton")
        self.play.setFixedWidth(34)
        self.play.clicked.connect(self._toggle)
        self.slider = QSlider(Qt.Horizontal)
        self.slider.sliderMoved.connect(self.player.setPosition)
        self.time = QLabel("0:00", objectName="keyHint")
        row.addWidget(self.play)
        row.addWidget(self.slider, 1)
        row.addWidget(self.time)
        lay.addLayout(row)
        self.player.durationChanged.connect(lambda d: self.slider.setRange(0, d))
        self.player.positionChanged.connect(self._moved)
        self.player.playbackStateChanged.connect(
            lambda s: self.play.setText("⏸" if s == QMediaPlayer.PlaybackState.PlayingState else "▶"))
        self.error = ""
        self.player.errorOccurred.connect(lambda _e, text: setattr(self, "error", text))

    def show_path(self, path: str) -> bool:
        self.error = ""
        self.player.setSource(QUrl.fromLocalFile(path))
        self.audio.setMuted(True)  # kendiliğinden açılan video ses çıkarmasın
        self.player.play()
        return True

    def stop(self):
        self.player.stop()

    def _toggle(self):
        from PySide6.QtMultimedia import QMediaPlayer

        if self.player.playbackState() == QMediaPlayer.PlaybackState.PlayingState:
            self.player.pause()
        else:
            self.audio.setMuted(False)
            self.player.play()

    def _moved(self, pos: int):
        if not self.slider.isSliderDown():
            self.slider.setValue(pos)
        self.time.setText(f"{pos // 60000}:{pos // 1000 % 60:02d}")


class ModelView(QWidget):
    """3D model: Qt Quick 3D (RuntimeLoader: glTF/GLB, OBJ, STL, PLY). Fareyle döndür, tekerlekle yakınlaştır."""

    def __init__(self):
        super().__init__()
        from PySide6.QtQuickWidgets import QQuickWidget

        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        self.quick = QQuickWidget()
        self.quick.setResizeMode(QQuickWidget.SizeRootObjectToView)
        self.quick.setSource(QUrl.fromLocalFile(str(Path(__file__).parent / "assets" / "model3d.qml")))
        lay.addWidget(self.quick, 1)
        row = QHBoxLayout()
        self.info = QLabel("", objectName="keyHint")
        reset = QPushButton("görünümü sıfırla", objectName="smallButton")
        reset.clicked.connect(self._reset)
        row.addWidget(self.info, 1)
        row.addWidget(reset)
        lay.addLayout(row)
        self.timer = QTimer(self)
        self.timer.setInterval(300)
        self.timer.timeout.connect(self._poll)

    def root(self):
        return self.quick.rootObject()

    def show_path(self, path: str) -> bool:
        root = self.root()
        if root is None:  # QML yüklenemedi (ör. Qt Quick 3D yok)
            self.info.setText("3D görüntüleyici açılamadı.")
            return False
        root.setProperty("dims", "")
        root.setProperty("source", QUrl())  # aynı dosya değişince yeniden yüklensin
        root.setProperty("source", QUrl.fromLocalFile(path))
        self._reset()  # yeni model: kamera baştan
        self.info.setText("yükleniyor…")
        self.timer.start()
        return True

    def _reset(self):
        root = self.root()
        if root is not None:
            from PySide6.QtCore import QMetaObject

            QMetaObject.invokeMethod(root, "reset")

    def _poll(self):
        root = self.root()
        status = str(root.property("status") or "") if root is not None else ""
        if not status:
            return
        self.timer.stop()
        if status == "ok":
            dims = str(root.property("dims") or "")
            self.info.setText(f"ölçüler: {dims} (STL/OBJ'de birim genelde mm) · sürükle: döndür · tekerlek: "
                              "yakınlaştır" if dims else "sürükle: döndür · tekerlek: yakınlaştır")
        else:
            self.info.setText(status)


class MediaPanel(QWidget):
    """Görsel sekmesi (ayrıntı modül açıklamasında)."""

    new_media = Signal()  # sekme görünmüyorken yeni medya geldi (sekme başlığında işaret)

    def __init__(self):
        super().__init__()
        lay = QVBoxLayout(self)
        lay.setContentsMargins(14, 14, 14, 14)
        lay.setSpacing(8)
        head = QHBoxLayout()
        self.title = QLabel("GÖRSEL", objectName="panelTitle")
        self.title.setToolTip("")
        self.open_btn = QPushButton("Aç", objectName="smallButton")
        self.open_btn.setEnabled(False)
        self.open_btn.clicked.connect(lambda: QDesktopServices.openUrl(QUrl.fromLocalFile(self.current)))
        folder_btn = QPushButton("Klasörü aç", objectName="smallButton")
        folder_btn.clicked.connect(lambda: QDesktopServices.openUrl(QUrl.fromLocalFile(self.root)))
        head.addWidget(self.title, 1)
        head.addWidget(self.open_btn)
        head.addWidget(folder_btn)
        lay.addLayout(head)

        self.live_row = QWidget()
        lr = QHBoxLayout(self.live_row)
        lr.setContentsMargins(0, 0, 0, 0)
        self.live_label = QLabel("", objectName="keyHint")
        self.live_bar = QProgressBar()
        self.live_bar.setFixedHeight(6)
        self.live_bar.setTextVisible(False)
        lr.addWidget(self.live_label)
        lr.addWidget(self.live_bar, 1)
        self.live_row.hide()
        lay.addWidget(self.live_row)

        self.stack = QStackedWidget()
        self.empty = QLabel("Burada üretilen resimler, videolar ve 3D modeller görünür.\nResim üretilirken her "
                            "adım canlı izlenir; iş klasörüne yeni bir görsel, video ya da model (STL, OBJ, GLB) "
                            "yazılınca kendiliğinden açılır.", objectName="hint", alignment=Qt.AlignCenter)
        self.empty.setWordWrap(True)
        self.image = ImageView()
        self.stack.addWidget(self.empty)
        self.stack.addWidget(self.image)
        self._video: VideoView | None = None
        self._model: ModelView | None = None
        lay.addWidget(self.stack, 1)

        bottom = QHBoxLayout()
        self.count = QLabel("", objectName="keyHint")
        self.follow = QCheckBox("yenileri göster")
        self.follow.setChecked(True)
        self.follow.setToolTip("Klasöre yeni bir görsel, video ya da model gelince hemen aç")
        bottom.addWidget(self.count, 1)
        bottom.addWidget(self.follow)
        lay.addLayout(bottom)
        self.gallery = QListWidget()
        self.gallery.setViewMode(QListWidget.IconMode)
        self.gallery.setFlow(QListWidget.LeftToRight)
        self.gallery.setWrapping(False)
        self.gallery.setMovement(QListWidget.Static)
        self.gallery.setIconSize(QSize(THUMB, THUMB))
        self.gallery.setFixedHeight(THUMB + 34)
        self.gallery.setHorizontalScrollMode(QListWidget.ScrollPerPixel)
        self.gallery.itemClicked.connect(lambda item: self.show_file(item.data(Qt.UserRole)))
        lay.addWidget(self.gallery)

        self.root = ""
        self.current = ""
        self.known: dict[str, tuple[float, int]] = {}  # galerideki dosyalar
        self.pending: dict[str, tuple[float, int]] = {}  # yazılıyor olabilir: bir tarama daha aynı kalmalı
        self.live_active = False
        self.timer = QTimer(self)
        self.timer.setInterval(SCAN_MS)
        self.timer.timeout.connect(self._scan)
        self.timer.start()

    # ---- klasör
    def set_root(self, path: str):
        if path == self.root:
            return
        self.root = path
        self.known = scan(path)
        self.pending = {}
        self._fill_gallery()
        newest = self._sorted()[:1]
        if newest and not self.live_active:
            self.show_file(newest[0])
        elif not self.live_active:
            self._stop_video()
            self.current = ""
            self.open_btn.setEnabled(False)
            self.title.setText("GÖRSEL")
            self.stack.setCurrentWidget(self.empty)

    def _sorted(self) -> list[str]:
        return sorted(self.known, key=lambda p: self.known[p][0], reverse=True)

    def _fill_gallery(self):
        self.gallery.clear()
        for path in self._sorted()[:MAX_FILES]:
            self.gallery.addItem(self._item(path))
        self._update_count()

    def _item(self, path: str) -> QListWidgetItem:
        kind = media_kind(path)
        if kind == "image":
            pix = QPixmap(path)
            icon = pix.scaled(THUMB, THUMB, Qt.KeepAspectRatio, Qt.SmoothTransformation) if not pix.isNull() else \
                tile("image", Path(path).suffix)
        else:
            icon = tile(kind, Path(path).suffix)
        item = QListWidgetItem(QIcon(icon), "")
        item.setData(Qt.UserRole, path)
        item.setToolTip(Path(path).name)
        item.setSizeHint(QSize(THUMB + 8, THUMB + 8))
        return item

    def _update_count(self):
        n = len(self.known)
        self.count.setText(f"{n} dosya" if n else "")

    def _scan(self):
        if not self.root or (not self.isVisible() and not self.follow.isChecked()):
            return
        now = scan(self.root)
        fresh = []
        for path, stamp in now.items():
            if self.known.get(path) == stamp:
                continue
            if self.pending.get(path) == stamp and stamp[1] > 0:  # iki taramadır aynı: yazılması bitti
                fresh.append(path)
                self.known[path] = stamp
                self.pending.pop(path, None)
            else:
                self.pending[path] = stamp
        gone = [p for p in self.known if p not in now]
        for p in gone:
            self.known.pop(p)
        if not fresh and not gone:
            return
        self._fill_gallery()
        if fresh:
            newest = max(fresh, key=lambda p: self.known[p][0])
            if self.follow.isChecked() and not self.live_active:
                self.show_file(newest)
            self.new_media.emit()

    # ---- gösterme
    def show_file(self, path: str):
        kind = media_kind(path)
        if not kind or not Path(path).is_file():
            return
        if kind != "video":
            self._stop_video()
        view = {"image": self.image, "video": self._video_view, "model": self._model_view}[kind]
        if callable(view) and not isinstance(view, QWidget):
            view = view()
        if not view.show_path(path) and path == self.current:
            return
        self.stack.setCurrentWidget(view)
        self.current = path
        self.open_btn.setEnabled(True)
        size = Path(path).stat().st_size
        shown = f"{size / 1024 / 1024:.1f} MB" if size >= 1024 * 1024 else (
            f"{size / 1024:.0f} KB" if size >= 1024 else f"{size} B")
        self.title.setText(f"{Path(path).name}  ·  {shown}".upper())
        self.title.setToolTip(path)
        for i in range(self.gallery.count()):
            if self.gallery.item(i).data(Qt.UserRole) == path:
                self.gallery.setCurrentRow(i)
                break

    def _video_view(self) -> VideoView:
        if self._video is None:
            self._video = VideoView()
            self.stack.addWidget(self._video)
        return self._video

    def _model_view(self) -> ModelView:
        if self._model is None:
            self._model = ModelView()
            self.stack.addWidget(self._model)
        return self._model

    def _stop_video(self):
        if self._video is not None:
            self._video.stop()

    # ---- canlı üretim (imagegen)
    def live(self, path: str, pct: int, text: str):
        """Üretim ilerlemesi: pct 0-99 → ara görüntü (path) ve çubuk; pct < 0 → bitti (path: sonuç dosyası)."""
        if pct < 0:
            self.live_active = False
            self.live_row.hide()
            if path and Path(path).is_file():
                self.known[path] = (Path(path).stat().st_mtime, Path(path).stat().st_size)
                self._fill_gallery()
                self.show_file(path)
            return
        if not self.live_active:
            self.live_active = True
            self._stop_video()
            self.live_row.show()
            self.title.setText("CANLI · ÜRETİLİYOR")
            self.open_btn.setEnabled(False)
        self.live_bar.setValue(pct)
        self.live_label.setText(f"● canlı · {text}")
        if path and Path(path).is_file() and self.image.show_path(path, upscale=True):
            self.stack.setCurrentWidget(self.image)

    def shutdown(self):
        self.timer.stop()
        self._stop_video()
