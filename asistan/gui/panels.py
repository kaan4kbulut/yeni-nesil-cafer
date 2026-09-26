"""Sağ panel: Etkinlik, Dosyalar, Görsel (media_panel.py), Kayıt, Modeller ve Önizle sekmeleri."""

import csv
from datetime import datetime
from pathlib import Path

from PySide6.QtCore import QDir, QElapsedTimer, Qt, QTimer, QUrl, Signal
from PySide6.QtGui import QBrush, QColor, QDesktopServices, QPixmap, QTextFrameFormat, QTextTable
from PySide6.QtWidgets import (
    QApplication, QFileSystemModel, QFrame, QHBoxLayout, QLabel, QListWidget, QListWidgetItem,
    QPlainTextEdit, QProgressBar, QPushButton, QScrollArea, QSplitter, QStackedWidget, QTableWidget,
    QTableWidgetItem, QTabWidget, QTextBrowser, QToolButton, QTreeView, QVBoxLayout, QWidget,
)

from ..agent import ollama_models, ollama_running
from ..connections import ANTHROPIC_KEY
from ..keystore import get_secret
from .chat import file_kind, tool_label
from .icons import icon, pixmap
from .media_panel import MediaPanel
from .theme import C

TEXT_SUFFIXES = {
    ".txt", ".md", ".py", ".json", ".yaml", ".yml", ".toml", ".ini", ".cfg", ".csv", ".log", ".sh",
    ".fish", ".js", ".ts", ".html", ".css", ".xml", ".rs", ".go", ".c", ".h", ".cpp", ".java", ".sql",
    ".conf", ".env", ".gitignore", "",
}
IMAGE_SUFFIXES = {".png", ".jpg", ".jpeg", ".gif", ".webp", ".bmp", ".svg"}
FIX_COMMAND = "sudo systemctl restart ollama"


def _title(text: str) -> QLabel:
    return QLabel(text.upper(), objectName="panelTitle")


def human_size(n: int) -> str:
    for unit in ("B", "KB", "MB", "GB"):
        if n < 1024:
            return f"{n:.0f} {unit}" if unit == "B" else f"{n:.1f} {unit}"
        n /= 1024
    return f"{n:.1f} TB"


# ---------------------------------------------------------------- Etkinlik

class StepRow(QWidget):
    """Baloncuk: 01 · başlık / alt satır · süre · durum. Altında, varsa, modelin o adımdaki düşüncesi paragraf olarak."""

    def __init__(self, no: int, title: str, sub: str = ""):
        super().__init__()
        self.setObjectName("stepRow")
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 5, 0, 5)
        outer.setSpacing(6)
        self.bubble = QFrame(objectName="stepBubble")
        self.bubble.setStyleSheet(f"#stepBubble {{ background: {C['surface2']}; border: 1px solid {C['border']}; "
                                  f"border-radius: 10px; }} #stepBubble QLabel {{ background: transparent; }}")
        row = QHBoxLayout(self.bubble)
        row.setContentsMargins(12, 9, 12, 9)
        row.setSpacing(12)
        self.no = QLabel(f"{no:02d}", objectName="stepNo")
        self.no.setFixedWidth(20)
        col = QVBoxLayout()
        col.setSpacing(3)
        self.title = QLabel(title, objectName="stepTitle")
        self.sub = QLabel(sub, objectName="stepSub")
        self.sub.setWordWrap(True)
        self.sub.setVisible(bool(sub))
        col.addWidget(self.title)
        col.addWidget(self.sub)
        self.time = QLabel("", objectName="stepTime")
        self.mark = QLabel()
        self.mark.setFixedWidth(12)
        row.addWidget(self.no, 0, Qt.AlignTop)
        row.addLayout(col, 1)
        row.addWidget(self.time, 0, Qt.AlignTop)
        row.addWidget(self.mark, 0, Qt.AlignTop)
        outer.addWidget(self.bubble)
        # düşünce: baloncuğun altında, her zaman açık düz paragraf
        self.thought_text = ""
        self.thought = QLabel(objectName="stepThought")
        self.thought.setWordWrap(True)
        self.thought.setTextInteractionFlags(Qt.TextSelectableByMouse)
        self.thought.setStyleSheet(f"background: transparent; color: {C['text2']}; font-style: italic; padding: 0 6px 0 14px; "
                                   f"border-left: 2px solid {C['frame']}; margin-left: 10px;")
        self.thought.setVisible(False)
        outer.addWidget(self.thought)
        self.clock = QElapsedTimer()
        self.clock.start()
        self.live = True
        self.set_live()

    def add_thought(self, delta: str):
        if not self.thought_text and self.live:
            self.title.setText("düşünüyor")
        self.thought_text += delta
        text = self.thought_text.strip()
        self.thought.setText(text)
        self.thought.setVisible(bool(text))

    def set_live(self):
        self.no.setStyleSheet(f"color: {C['accent']};")
        self.mark.setText("■")
        self.mark.setStyleSheet(f"color: {C['accent']}; font-size: 9px;")

    def tick(self):
        if self.live:
            self.time.setText(f"{self.clock.elapsed() / 1000:.1f} sn")

    def finish(self, ok: bool, seconds: float | None = None, title: str = "", sub: str | None = None):
        self.live = False
        if title:
            self.title.setText(title)
        if sub is not None:
            self.sub.setText(sub)
            self.sub.setVisible(bool(sub))
        secs = seconds if seconds is not None else self.clock.elapsed() / 1000
        self.time.setText(f"{secs:.1f} sn")
        self.no.setStyleSheet(f"color: {C['muted']};")
        self.mark.setText("✓" if ok else "✗")
        self.mark.setStyleSheet(f"color: {C['success'] if ok else C['error']};")


class _Rule(QFrame):
    def __init__(self):
        super().__init__()
        self.setFixedHeight(1)
        self.setStyleSheet(f"border-top: 1px dashed {C['border']};")


class ActivityPanel(QWidget):
    file_open = Signal(str)

    def __init__(self):
        super().__init__()
        lay = QVBoxLayout(self)
        lay.setContentsMargins(20, 18, 20, 14)
        lay.setSpacing(6)
        head = QHBoxLayout()
        head.addWidget(_title("Adımlar"), 1)
        self.meta = QLabel("", objectName="panelMeta")
        head.addWidget(self.meta)
        lay.addLayout(head)
        self.progress = QProgressBar()
        self.progress.setTextVisible(False)
        self.progress.setRange(0, 1)
        self.progress.setValue(0)
        self.progress.setVisible(False)
        lay.addWidget(self.progress)

        self.scroll = scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        inner = QWidget()
        self.col = QVBoxLayout(inner)
        self.col.setContentsMargins(0, 0, 0, 0)
        self.col.setSpacing(0)
        self.empty = QLabel("Bir mesaj gönderdiğinde attığım adımlar burada görünür.", objectName="stepSub")
        self.empty.setWordWrap(True)
        self.col.addWidget(_Rule())
        self.col.addWidget(self.empty)
        self.col.addStretch()
        scroll.setWidget(inner)
        lay.addWidget(scroll, 3)

        files_head = QHBoxLayout()
        files_head.addWidget(_title("Değişen dosyalar"), 1)
        self.files_meta = QLabel("0", objectName="panelMeta")
        files_head.addWidget(self.files_meta)
        lay.addSpacing(18)
        lay.addLayout(files_head)
        self.files_box = QVBoxLayout()
        self.files_box.setSpacing(0)
        self.files_box.addWidget(_Rule())
        lay.addLayout(self.files_box)
        lay.addStretch(1)

        # eski arayüzle uyum için (pencere bu alanlara yazıyor)
        self.state = QLabel("Hazır", objectName="stepSub")
        self.detail = QLabel(objectName="stepSub")
        self.stats = QLabel("", objectName="panelMeta")
        self.stats.setWordWrap(True)
        lay.addWidget(self.stats)

        self.clock = QElapsedTimer()
        self.running = False
        self.rows: list[StepRow] = []
        self.current_model: StepRow | None = None
        self.tool_rows: dict[str, StepRow] = {}
        self.files: dict[str, QWidget] = {}
        self.timer = QTimer(self)
        self.timer.timeout.connect(self._tick)
        self.timer.start(200)

    def _tick(self):
        for r in (self.current_model, *self.tool_rows.values()):
            if r is not None:
                r.tick()
        if self.running:
            self._update_meta()

    def _update_meta(self):
        secs = self.clock.elapsed() / 1000 if self.clock.isValid() else 0
        self.meta.setText(f"{len(self.rows)} adım · {secs:.1f} sn")

    def _add_row(self, title: str, sub: str = "") -> StepRow:
        self.empty.hide()
        row = StepRow(len(self.rows) + 1, title, sub)
        self.rows.append(row)
        self.col.insertWidget(self.col.count() - 1, row)
        self._update_meta()
        self._follow()
        return row

    def _follow(self):
        """Kullanıcı yukarı kaydırmadıysa en son adımı göster."""
        bar = self.scroll.verticalScrollBar()
        if bar.maximum() - bar.value() < 80:
            QTimer.singleShot(0, lambda: bar.setValue(bar.maximum()))

    def begin_run(self, model: str):
        for i in reversed(range(self.col.count())):
            w = self.col.itemAt(i).widget()
            if w is not None and w is not self.empty:
                w.deleteLater()
                self.col.takeAt(i)
        self.col.removeWidget(self.empty)
        self.col.insertWidget(0, _Rule())
        self.col.insertWidget(1, self.empty)
        self.empty.hide()
        self.rows.clear()
        self.tool_rows.clear()
        self.current_model = None
        self.model = model
        self.running = True
        self.clock.start()
        self.state.setText("Çalışıyor")
        self.progress.setRange(0, 0)
        self.progress.setVisible(True)
        for w in list(self.files.values()):
            w.deleteLater()
        self.files.clear()
        self.files_meta.setText("0")

    def model_start(self, step: int):
        self.current_model = self._add_row("yanıt yazılıyor" if step == 1 else "sonucu değerlendiriyor", self.model)

    def model_end(self, stats: dict):
        if self.current_model is not None:
            speed = stats.get("tokens_per_sec", 0)
            sub = f"{stats.get('output_tokens', 0)} token" + (f" · {speed:.0f} tok/sn" if speed else "")
            self.current_model.finish(True, stats.get("seconds"), "model yanıtı", sub)
            self.current_model = None
        parts = [f"girdi {stats.get('input_tokens', 0)}", f"çıktı {stats.get('output_tokens', 0)} token"]
        if stats.get("load_seconds", 0) > 0.5:
            parts.append(f"model yükleme {stats['load_seconds']:.1f} sn")
        self.stats.setText("son yanıt · " + " · ".join(parts))

    def append_thinking(self, delta: str):
        """Düşünce sohbette değil burada, o anki model adımının altında gösterilir."""
        if self.current_model is None:
            self.current_model = self._add_row("düşünüyor", self.model)
        self.current_model.add_thought(delta)
        self._follow()

    def text_started(self, _delta: str = ""):
        if self.current_model is not None and self.current_model.title.text() == "düşünüyor":
            self.current_model.title.setText("yanıt yazılıyor")

    def tool_start(self, call_id: str, name: str, summary: str):
        self.tool_rows[call_id] = self._add_row(tool_label(name), summary)
        self.state.setText("Araç çalışıyor")

    def tool_end(self, call_id: str, is_error: bool):
        row = self.tool_rows.pop(call_id, None)
        if row is not None:
            row.finish(not is_error)

    def waiting_approval(self, name: str):
        self.state.setText("Onayın bekleniyor")
        row = self._add_row("onay bekleniyor", tool_label(name))
        row.finish(True, 0)
        row.mark.setText("?")
        row.mark.setStyleSheet(f"color: {C['accent']};")

    def add_file(self, path: str, edited: bool):
        if path in self.files:
            return
        p = Path(path)
        w = QWidget()
        row = QHBoxLayout(w)
        row.setContentsMargins(0, 8, 0, 8)
        row.setSpacing(10)
        mark = QLabel("~" if edited else "+", objectName="stepTitle")
        mark.setStyleSheet(f"color: {C['accent'] if edited else C['success']};")
        mark.setFixedWidth(10)
        name = QLabel(p.name, objectName="stepTitle")
        try:
            meta = human_size(p.stat().st_size)
        except OSError:
            meta = ""
        size = QLabel(meta, objectName="stepSub")
        open_btn = QPushButton("aç", objectName="smallButton")
        open_btn.clicked.connect(lambda: self.file_open.emit(path))
        row.addWidget(mark)
        row.addWidget(name, 1)
        row.addWidget(size)
        row.addWidget(open_btn)
        self.files_box.addWidget(w)
        self.files_box.addWidget(_Rule())
        self.files[path] = w
        self.files_meta.setText(str(len(self.files)))

    def end_run(self, state: str, summary: str):
        self.running = False
        if self.current_model is not None:
            self.current_model.finish(False, title="yanıt kesildi")
            self.current_model = None
        self.progress.setRange(0, 1)
        self.progress.setVisible(False)
        self.state.setText(state)
        self._update_meta()


# ---------------------------------------------------------------- Dosyalar

class FilesPanel(QWidget):
    def __init__(self):
        super().__init__()
        lay = QVBoxLayout(self)
        lay.setContentsMargins(14, 14, 14, 14)
        lay.setSpacing(8)
        top = QHBoxLayout()
        self.root_label = QLabel(objectName="hint")
        open_btn = QPushButton("Klasörü aç", objectName="smallButton")
        open_btn.clicked.connect(lambda: QDesktopServices.openUrl(QUrl.fromLocalFile(self.root)))
        top.addWidget(self.root_label, 1)
        top.addWidget(open_btn)
        lay.addLayout(top)

        split = QSplitter(Qt.Vertical)
        self.model = QFileSystemModel()
        self.model.setFilter(QDir.AllEntries | QDir.NoDotAndDotDot | QDir.Hidden)
        self.tree = QTreeView()
        self.tree.setModel(self.model)
        for col in (1, 2, 3):
            self.tree.hideColumn(col)
        self.tree.setHeaderHidden(True)
        self.tree.clicked.connect(lambda idx: self.show_file(self.model.filePath(idx)))
        split.addWidget(self.tree)

        preview_box = QWidget()
        pv = QVBoxLayout(preview_box)
        pv.setContentsMargins(0, 6, 0, 0)
        head = QHBoxLayout()
        self.preview_name = QLabel("Önizleme", objectName="panelTitle")
        self.open_file_btn = QPushButton("Aç", objectName="smallButton")
        self.open_file_btn.setEnabled(False)
        self.open_file_btn.clicked.connect(
            lambda: QDesktopServices.openUrl(QUrl.fromLocalFile(self.current_file)))
        head.addWidget(self.preview_name, 1)
        head.addWidget(self.open_file_btn)
        pv.addLayout(head)
        self.stack = QStackedWidget()
        self.empty = QLabel("Önizlemek için bir dosya seç.\nAgent bir dosya yazdığında burada açılır.",
                            objectName="hint", alignment=Qt.AlignCenter)
        self.text = QPlainTextEdit(objectName="preview", readOnly=True)
        self.text.setLineWrapMode(QPlainTextEdit.NoWrap)
        self.md = QTextBrowser(objectName="mdPreview")
        self.md.setOpenExternalLinks(True)
        self.image = QLabel(alignment=Qt.AlignCenter)
        image_scroll = QScrollArea()
        image_scroll.setWidgetResizable(True)
        image_scroll.setWidget(self.image)
        for w in (self.empty, self.text, self.md, image_scroll):
            self.stack.addWidget(w)
        self.image_page = image_scroll
        pv.addWidget(self.stack, 1)
        split.addWidget(preview_box)
        split.setSizes([300, 200])  # sağ panelde üç bölümden biri: ağaç öne
        lay.addWidget(split, 1)
        self.root = ""
        self.current_file = ""

    def set_root(self, path: str):
        self.root = path
        self.root_label.setText(f"📁 {path}")
        self.root_label.setToolTip(path)
        self.model.setRootPath(path)
        self.tree.setRootIndex(self.model.index(path))

    def show_file(self, path: str):
        p = Path(path)
        if not p.is_file():
            return
        self.current_file = str(p)
        self.open_file_btn.setEnabled(True)
        self.preview_name.setText(f"{p.name}  ·  {human_size(p.stat().st_size)}".upper())
        self.tree.setCurrentIndex(self.model.index(str(p)))
        suffix = p.suffix.lower()
        if suffix in IMAGE_SUFFIXES:
            pix = QPixmap(str(p))
            self.image.setPixmap(pix.scaledToWidth(min(pix.width(), 340), Qt.SmoothTransformation))
            self.stack.setCurrentWidget(self.image_page)
            return
        if suffix not in TEXT_SUFFIXES or p.stat().st_size > 2_000_000:
            self.empty.setText("Bu dosya türü önizlenemiyor.\n'Aç' ile varsayılan programda açabilirsin.")
            self.stack.setCurrentWidget(self.empty)
            return
        try:
            content = p.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            self.empty.setText("Dosya metin olarak okunamadı.")
            self.stack.setCurrentWidget(self.empty)
            return
        if suffix == ".md":
            self.md.setMarkdown(content)
            self.stack.setCurrentWidget(self.md)
        else:
            self.text.setPlainText(content)
            self.stack.setCurrentWidget(self.text)


# ---------------------------------------------------------------- Kayıt

class LogPanel(QWidget):
    def __init__(self):
        super().__init__()
        lay = QVBoxLayout(self)
        lay.setContentsMargins(14, 14, 14, 14)
        top = QHBoxLayout()
        top.addWidget(_title("Araç çıktıları"), 1)
        clear = QPushButton("Temizle", objectName="smallButton")
        clear.clicked.connect(lambda: self.view.clear())
        top.addWidget(clear)
        lay.addLayout(top)
        self.view = QPlainTextEdit(objectName="logView", readOnly=True)
        self.view.setMaximumBlockCount(5000)
        lay.addWidget(self.view, 1)

    def add(self, header: str, body: str = ""):
        stamp = datetime.now().strftime("%H:%M:%S")
        text = f"[{stamp}] {header}"
        if body:
            shown = body if len(body) <= 8000 else body[:8000] + "\n…"
            text += "\n" + shown.rstrip()
        self.view.appendPlainText(text + "\n")
        self.view.verticalScrollBar().setValue(self.view.verticalScrollBar().maximum())


# ---------------------------------------------------------------- Modeller

class ModelsPanel(QWidget):
    model_chosen = Signal(str)

    def __init__(self, settings):
        super().__init__()
        self.settings = settings
        lay = QVBoxLayout(self)
        lay.setContentsMargins(14, 14, 14, 14)
        lay.setSpacing(10)

        card = QFrame(objectName="card")
        c = QVBoxLayout(card)
        c.setContentsMargins(14, 12, 14, 12)
        top = QHBoxLayout()
        self.ollama_state = QLabel("Ollama", objectName="statusBig")
        refresh = QPushButton("Yenile", objectName="smallButton")
        refresh.clicked.connect(self.refresh)
        top.addWidget(self.ollama_state, 1)
        top.addWidget(refresh)
        self.running_label = QLabel(objectName="hint")
        self.running_label.setWordWrap(True)
        c.addLayout(top)
        c.addWidget(self.running_label)
        lay.addWidget(card)

        self.warn = QFrame(objectName="banner")
        w = QVBoxLayout(self.warn)
        w.setContentsMargins(12, 10, 12, 10)
        self.warn_text = QLabel()
        self.warn_text.setWordWrap(True)
        copy = QPushButton("Komutu kopyala", objectName="smallButton")
        copy.clicked.connect(lambda: QApplication.clipboard().setText(FIX_COMMAND))
        w.addWidget(self.warn_text)
        w.addWidget(copy, alignment=Qt.AlignLeft)
        self.warn.setVisible(False)
        lay.addWidget(self.warn)

        lay.addWidget(_title("Kurulu yerel modeller"))
        lay.addWidget(QLabel("Kullanmak için çift tıkla", objectName="hint"))
        self.list = QListWidget(objectName="modelList")
        self.list.itemDoubleClicked.connect(lambda it: self.model_chosen.emit(it.data(Qt.UserRole)))
        lay.addWidget(self.list, 1)

        lay.addWidget(_title("Claude"))
        self.claude_label = QLabel(objectName="hint")
        self.claude_label.setWordWrap(True)
        lay.addWidget(self.claude_label)
        self.gpu_share: float | None = None

    def refresh(self) -> float | None:
        """Durumu yeniler; bellekteki modelin GPU payını (0-1) ya da None döndürür."""
        url = self.settings.ollama_url
        self.list.clear()
        try:
            models = ollama_models(url)
            running = ollama_running(url)
        except Exception:
            self.ollama_state.setText("● Ollama bağlı değil")
            self.ollama_state.setStyleSheet(f"color: {C['error']};")
            self.running_label.setText("`ollama serve` çalışıyor mu? Adres: " + url)
            self.warn.setVisible(False)
            self.gpu_share = None
            return None
        self.ollama_state.setText(f"● Ollama bağlı  ·  {len(models)} model")
        self.ollama_state.setStyleSheet(f"color: {C['success']};")
        for m in models:
            d = m.get("details", {})
            item = QListWidgetItem(
                f"{m['name']}\n{human_size(m.get('size', 0))}  ·  {d.get('parameter_size', '?')}  ·  "
                f"{d.get('quantization_level', '')}")
            item.setData(Qt.UserRole, m["name"])
            if m["name"] == self.settings.ollama_model:
                item.setText("★ " + item.text())
            self.list.addItem(item)

        self.gpu_share = None
        if running:
            lines = []
            for r in running:
                share = r.get("size_vram", 0) / r["size"] if r.get("size") else 0
                self.gpu_share = share if self.gpu_share is None else min(self.gpu_share, share)
                where = "GPU" if share > 0.99 else ("CPU" if share < 0.01 else f"%{share * 100:.0f} GPU")
                lines.append(f"Bellekte: {r['name']}  ·  {human_size(r.get('size', 0))}  ·  {where}  ·  "
                             f"bağlam {r.get('context_length', '?')}")
            self.running_label.setText("\n".join(lines))
        else:
            self.running_label.setText("Şu an bellekte model yok (ilk mesajda yüklenir).")
        slow = self.gpu_share is not None and self.gpu_share < 0.9
        self.warn.setVisible(slow)
        if slow:
            self.warn_text.setText(
                f"⚠ Model büyük ölçüde işlemcide çalışıyor (%{self.gpu_share * 100:.0f} GPU), bu yüzden "
                f"yanıtlar çok yavaş. Ekran kartını tekrar algılaması için terminalde çalıştır:\n\n"
                f"{FIX_COMMAND}")

        import os

        key = get_secret(ANTHROPIC_KEY) or os.environ.get("ANTHROPIC_API_KEY")
        self.claude_label.setText(
            "API anahtarı ayarlı ✓" if key else "API anahtarı yok — sol paneldeki API'ler sekmesinden ekleyebilirsin.")
        return self.gpu_share


# ---------------------------------------------------------------- Önizleme (belge görünümü)

class DocumentView(QWidget):
    """Dosyayı belge gibi gösterir: Markdown, tablo (CSV), kod, resim."""

    def __init__(self):
        super().__init__()
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)
        bar = QWidget(objectName="docToolbar")
        bl = QHBoxLayout(bar)
        bl.setContentsMargins(14, 8, 8, 8)
        self.file_icon = QLabel()
        self.name = QLabel("Önizleme", objectName="docName")
        self.meta = QLabel(objectName="hint")
        bl.addWidget(self.file_icon)
        bl.addWidget(self.name)
        bl.addWidget(self.meta)
        bl.addStretch()
        self.buttons = []
        for icon_name, tip, fn in [
            ("external", "Varsayılan programda aç", lambda: self._open(self.path)),
            ("folder", "Klasörde göster", lambda: self._open(str(Path(self.path).parent))),
        ]:
            b = QToolButton(objectName="iconButton", toolTip=tip)
            b.setIcon(icon(icon_name, active=C["text"]))
            b.clicked.connect(fn)
            bl.addWidget(b)
            self.buttons.append(b)
        lay.addWidget(bar)

        self.stack = QStackedWidget()
        self.empty = QLabel("Sohbetteki bir dosya kartına tıkla,\nburada belge gibi açılsın.",
                            objectName="hint", alignment=Qt.AlignCenter)
        self.doc = QTextBrowser(objectName="docView")
        self.doc.setOpenExternalLinks(True)
        self.doc.document().setDocumentMargin(22)
        self.code = QPlainTextEdit(objectName="docCode", readOnly=True)
        self.code.setLineWrapMode(QPlainTextEdit.NoWrap)
        self.table = QTableWidget(objectName="docTable")
        self.table.verticalHeader().setVisible(False)
        self.image = QLabel(alignment=Qt.AlignCenter)
        self.image_page = QScrollArea()
        self.image_page.setWidgetResizable(True)
        self.image_page.setWidget(self.image)
        for w in (self.empty, self.doc, self.code, self.table, self.image_page):
            self.stack.addWidget(w)
        lay.addWidget(self.stack, 1)
        self.path = ""
        self._set_enabled(False)

    @staticmethod
    def _open(path: str):
        if path:
            QDesktopServices.openUrl(QUrl.fromLocalFile(path))

    def _set_enabled(self, on: bool):
        for b in self.buttons:
            b.setEnabled(on)

    def _message(self, text: str):
        self.empty.setText(text)
        self.stack.setCurrentWidget(self.empty)

    def _style_tables(self):
        # Markdown tabloları çerçevesiz gelir; ince çizgi ve iç boşluk ekle
        root = self.doc.document().rootFrame()
        for frame in root.childFrames():
            if isinstance(frame, QTextTable):
                fmt = frame.format()
                fmt.setBorder(1)
                fmt.setBorderStyle(QTextFrameFormat.BorderStyle_Solid)
                fmt.setBorderBrush(QBrush(QColor(C["border"])))
                fmt.setBorderCollapse(True)
                fmt.setCellPadding(6)
                fmt.setCellSpacing(0)
                frame.setFormat(fmt)

    def show_file(self, path: str):
        p = Path(path)
        self.path = str(p)
        kind, icon_name = file_kind(p)
        self.file_icon.setPixmap(pixmap(icon_name, "#9fb6e8", 16))
        self.name.setText(p.name)
        if not p.is_file():
            self.meta.setText("")
            self._set_enabled(False)
            self._message("Dosya bulunamadı; taşınmış ya da silinmiş olabilir.")
            return
        self._set_enabled(True)
        self.meta.setText(f"·  {kind}  ·  {human_size(p.stat().st_size)}")
        suffix = p.suffix.lower()
        if suffix in IMAGE_SUFFIXES:
            pix = QPixmap(str(p))
            width = max(self.width() - 40, 200)
            self.image.setPixmap(pix.scaledToWidth(min(pix.width(), width), Qt.SmoothTransformation))
            self.stack.setCurrentWidget(self.image_page)
            return
        if suffix not in TEXT_SUFFIXES or p.stat().st_size > 2_000_000:
            self._message("Bu dosya türü burada önizlenemiyor.\nÜstteki düğmeyle varsayılan programda açabilirsin.")
            return
        try:
            content = p.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            self._message("Dosya metin olarak okunamadı.")
            return
        if suffix == ".md":
            self.doc.setMarkdown(content)
            self._style_tables()
            self.stack.setCurrentWidget(self.doc)
        elif suffix == ".csv":
            rows = list(csv.reader(content.splitlines()))[:2000]
            header, body = (rows[0], rows[1:]) if rows else ([], [])
            self.table.clear()
            self.table.setColumnCount(len(header))
            self.table.setHorizontalHeaderLabels(header)
            self.table.setRowCount(len(body))
            for r, row in enumerate(body):
                for c, value in enumerate(row[: len(header)]):
                    self.table.setItem(r, c, QTableWidgetItem(value))
            self.table.resizeColumnsToContents()
            self.stack.setCurrentWidget(self.table)
        elif suffix in (".txt", ".log", ""):
            self.doc.setPlainText(content)
            self.stack.setCurrentWidget(self.doc)
        else:
            self.code.setPlainText(content)
            self.stack.setCurrentWidget(self.code)


class RightPanel(QWidget):
    closed = Signal()

    def __init__(self, settings):
        super().__init__(objectName="rightPanel")
        """Üç bölüm alt alta, hepsi aynı anda görünür: adımlar (sekmelerle kayıt, modeller, önizle),
        dosyalar ve canlı görüntü (üretilen resim / video / 3D model). Bölümler aradaki çizgiyle büyütülür."""
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        self.tabs = QTabWidget()
        self.tabs.setDocumentMode(True)
        self.activity = ActivityPanel()
        self.files = FilesPanel()
        self.media = MediaPanel()
        self.log = LogPanel()
        self.models = ModelsPanel(settings)
        self.preview = DocumentView()
        self.tabs.addTab(self.activity, "adımlar")
        self.tabs.addTab(self.log, "kayıt")
        self.tabs.addTab(self.models, "modeller")
        self.tabs.addTab(self.preview, "önizle")
        self.tabs.tabBar().setExpanding(False)
        self.tabs.tabBar().setDrawBase(False)
        self.tabs.tabBar().setUsesScrollButtons(False)
        self.tabs.currentChanged.connect(self._tab_changed)
        close = QToolButton(objectName="iconButton", toolTip="Paneli kapat (Ctrl+J)")
        close.setText("✕")
        close.clicked.connect(self.closed)
        self.tabs.setCornerWidget(close, Qt.TopRightCorner)
        self.split = QSplitter(Qt.Vertical)
        self.split.setChildrenCollapsible(False)
        for w, stretch in ((self.tabs, 3), (self.files, 3), (self.media, 5)):  # canlı görüntüye en çok yer
            w.setMinimumHeight(140)
            self.split.addWidget(w)
            self.split.setStretchFactor(self.split.count() - 1, stretch)
        lay.addWidget(self.split)

    def show_part(self, widget):
        """Bölümü öne çıkarır: sekmeyse ona geçer (dosyalar ve canlı görüntü zaten hep görünür)."""
        if self.tabs.indexOf(widget) >= 0:
            self.tabs.setCurrentWidget(widget)

    def _tab_changed(self, i: int):
        if self.tabs.widget(i) is self.models:
            self.models.refresh()

    def set_root(self, path: str):
        """Sohbetin klasörü: dosya ağacı ve canlı görüntü bölümünin izlediği klasör."""
        self.files.set_root(path)
        self.media.set_root(path)
