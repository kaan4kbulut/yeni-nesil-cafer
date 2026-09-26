"""Grup alanı arayüzü: görev listesi (sol panel), iş odası (orta) ve görevi yürüten işçi."""

import threading
from datetime import datetime

from PySide6.QtCore import Qt, QThread, QUrl, Signal
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (
    QDialog, QFormLayout, QFrame, QHBoxLayout, QLabel, QLineEdit, QListWidget,
    QListWidgetItem, QMenu, QMessageBox, QPlainTextEdit, QPushButton, QSplitter, QStackedWidget,
    QVBoxLayout, QWidget,
)

from ..agent import Cancelled, describe_error
from ..work import STATUS_LABELS, STEP_ICONS, Task, TeamRunner
from .chat import ChatView
from .sidebar import _dialog_buttons
from .icons import icon
from .widgets import RowButton
from .theme import C


# ---------------------------------------------------------------- arka plan işçisi

class _Callbacks:
    """TeamRunner'ın olaylarını işçinin sinyallerine çevirir (işçi iş parçacığında çağrılır)."""

    def __init__(self, w: "TaskWorker"):
        self.w = w

    def speaker(self, who): self.w.speaker.emit(who)
    def on_text(self, delta): self.w.text.emit(delta)
    def on_thinking(self, delta): self.w.thinking.emit(delta)
    def on_model_start(self, step): pass
    def on_model_end(self, stats): pass
    def on_tool_start(self, call_id, name, args): self.w.tool_start.emit(call_id, name, args)
    def on_tool_end(self, call_id, result, is_error): self.w.tool_end.emit(call_id, result, is_error)
    def ask_approval(self, name, args): return self.w.ask_approval(name, args)
    def is_cancelled(self): return self.w.is_cancelled()
    def notice(self, text): self.w.note.emit(text)
    def changed(self): self.w.changed.emit()


class TaskWorker(QThread):
    speaker = Signal(str)
    text = Signal(str)
    thinking = Signal(str)
    tool_start = Signal(str, str, dict)
    tool_end = Signal(str, str, bool)
    note = Signal(str)
    changed = Signal()
    approval_needed = Signal(str, dict)
    failed = Signal(str)

    def __init__(self, task: Task, settings, profiles, connections):
        super().__init__()
        self.task = task
        self.runner = TeamRunner(task, settings, profiles, connections, _Callbacks(self))
        self._cancel = threading.Event()
        self._approval_event = threading.Event()
        self._approval_result = False

    def is_cancelled(self):
        return self._cancel.is_set()

    def ask_approval(self, name, args) -> bool:
        self._approval_event.clear()
        self.approval_needed.emit(name, args)
        self._approval_event.wait()
        return self._approval_result

    def answer_approval(self, allowed: bool):
        self._approval_result = allowed
        self._approval_event.set()

    def cancel(self):
        self._cancel.set()
        self.answer_approval(False)

    def run(self):
        try:
            self.runner.run()
        except Cancelled:
            pass
        except Exception as e:
            self.failed.emit(describe_error(e))


# ---------------------------------------------------------------- yeni görev

class NewTaskDialog(QDialog):
    """Gruba görev: yalnızca görev yazılır; ajanları ve modelleri program kendisi seçer."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Gruba görev ver")
        self.setMinimumWidth(620)
        form = QFormLayout(self)
        form.setContentsMargins(20, 20, 20, 20)
        form.setSpacing(10)
        intro = QLabel("Görevi anlat. Yönetici planlar; program gereken bütün ajanları ve modelleri (yerel, bulut, "
                       "kod, görme, düşünme uzmanları) kendisi seçip görevi grupça yapar, bitince sana rapor verir.",
                       objectName="hint")
        intro.setWordWrap(True)
        self.goal = QPlainTextEdit()
        self.goal.setMinimumHeight(130)
        self.goal.setPlaceholderText(
            "ör. Laptop için 30-40 bin TL arası en iyi 5 modeli araştır, özelliklerini karşılaştıran "
            "bir tablo hazırla ve önerini yaz.")
        self.title = QLineEdit()
        self.title.setPlaceholderText("Boş bırakırsan görevin ilk satırından alınır")
        form.addRow(intro)
        form.addRow("Görev:", self.goal)
        form.addRow("Başlık:", self.title)
        buttons = _dialog_buttons(self)
        buttons.button(buttons.StandardButton.Save).setText("Gruba ver")
        form.addRow(buttons)
        self.goal.setFocus()

    def accept(self):
        goal = self.goal.toPlainText().strip()
        if not goal:
            QMessageBox.warning(self, "Eksik bilgi", "Görevi yazmalısın.")
            return
        self.result_goal = goal
        self.result_title = self.title.text().strip() or goal.splitlines()[0][:60]
        super().accept()


# ---------------------------------------------------------------- sol panel: görev listesi

class WorkPanel(QWidget):
    new_task = Signal()
    task_chosen = Signal(str)
    task_action = Signal(str, str)  # görev id, eylem: "stop" | "resume" | "folder" | "delete"

    def __init__(self, parent=None):
        super().__init__(parent)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(8)
        add = RowButton("Yeni Görev", "", "+", "outlineRow")
        add.setCursor(Qt.PointingHandCursor)
        add.clicked.connect(self.new_task)
        lay.addWidget(add)
        self.list = QListWidget(objectName="agentList")
        self.list.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.list.setWordWrap(True)
        self.list.itemClicked.connect(lambda it: self.task_chosen.emit(it.data(Qt.UserRole)))
        self.list.setContextMenuPolicy(Qt.CustomContextMenu)
        self.list.customContextMenuRequested.connect(self._menu)
        lay.addWidget(self.list, 1)
        self.hint = QLabel("Görevleri gruba ver; yönetici planlar, program gereken ajanları ve modelleri seçer, sana rapor gelir.",
                           objectName="hint")
        self.hint.setWordWrap(True)
        lay.addWidget(self.hint)
        self.tasks: list[Task] = []

    def refresh(self, tasks: list[Task], current_id: str = ""):
        self.tasks = tasks
        self.list.clear()
        if not tasks:
            empty = QListWidgetItem("Henüz görev yok.\n＋ Yeni Görev ile başla ya da\nSohbet'te asistana "
                                    "“bunu gruba ver” de.")
            empty.setFlags(Qt.NoItemFlags)
            empty.setForeground(Qt.gray)
            self.list.addItem(empty)
            return
        for t in tasks:
            done = sum(1 for s in t.steps if s["status"] == "done")
            progress = f"  ·  {done}/{len(t.steps)} adım" if t.steps else ""
            when = datetime.fromtimestamp(t.updated).strftime("%d.%m %H:%M")
            item = QListWidgetItem(f"{t.title}\n{STATUS_LABELS.get(t.status, t.status)}{progress}  ·  {when}")
            item.setData(Qt.UserRole, t.id)
            item.setToolTip(t.goal[:400])
            self.list.addItem(item)
            if t.id == current_id:
                item.setSelected(True)

    def _menu(self, pos):
        item = self.list.itemAt(pos)
        task_id = item.data(Qt.UserRole) if item else None
        task = next((t for t in self.tasks if t.id == task_id), None)
        if not task:
            return
        menu = QMenu(self)
        actions = {}
        if task.running or task.status == "queued":
            actions[menu.addAction("⏹  Durdur")] = "stop"
        elif task.status != "done":
            actions[menu.addAction("▶  Devam et")] = "resume"
        actions[menu.addAction("📁  Klasörü aç")] = "folder"
        menu.addSeparator()
        actions[menu.addAction("Sil")] = "delete"
        chosen = menu.exec(self.list.mapToGlobal(pos))
        if chosen in actions:
            self.task_action.emit(task.id, actions[chosen])


# ---------------------------------------------------------------- orta: iş odası

class WorkRoom(QWidget):
    send_note = Signal(str)
    action = Signal(str)  # "stop" | "resume" | "folder"

    def __init__(self, label_for, parent=None):
        super().__init__(parent)
        self.setObjectName("center")
        self.label_for = label_for  # konuşmacı id -> "Araştırmacı"
        self.task: Task | None = None
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)

        header = QWidget(objectName="header")
        hl = QHBoxLayout(header)
        hl.setContentsMargins(18, 10, 12, 10)
        self.title = QLabel("Grup Çalışması", objectName="title")
        self.status_chip = QLabel(objectName="agentChip")
        self.model_chip = QLabel(objectName="chip")
        self.folder_btn = QPushButton(" Klasör", objectName="smallButton")
        self.folder_btn.setIcon(icon("folder", C["muted"], 14))
        self.folder_btn.clicked.connect(lambda: self.action.emit("folder"))
        self.run_btn = QPushButton(objectName="smallButton")
        self.run_btn.clicked.connect(lambda: self.action.emit(self.run_btn.property("act")))
        hl.addWidget(self.title)
        hl.addWidget(self.status_chip)
        hl.addWidget(self.model_chip)
        hl.addStretch()
        hl.addWidget(self.folder_btn)
        hl.addWidget(self.run_btn)
        lay.addWidget(header)

        self.stack = QStackedWidget()
        empty = QLabel("🏢\n\nGrup Çalışması\n\nSoldan bir görev seç ya da ＋ Yeni Görev ile gruba iş ver.\n"
                       "Sohbet'te asistana “bunu gruba ver” demen de yeterli.",
                       objectName="hint", alignment=Qt.AlignCenter)
        self.stack.addWidget(empty)

        body = QSplitter()
        body.setHandleWidth(1)
        self.feed = ChatView()
        body.addWidget(self.feed)
        plan = QWidget(objectName="planPane")
        pl = QVBoxLayout(plan)
        pl.setContentsMargins(14, 14, 14, 14)
        pl.setSpacing(8)
        pl.addWidget(QLabel("PLAN", objectName="panelTitle"))
        self.steps = QListWidget(objectName="stepList")
        self.steps.setWordWrap(True)
        self.steps.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        pl.addWidget(self.steps, 1)
        pl.addWidget(QLabel("HEDEF", objectName="panelTitle"))
        self.goal = QLabel(objectName="hint")
        self.goal.setWordWrap(True)
        self.goal.setTextInteractionFlags(Qt.TextSelectableByMouse)
        pl.addWidget(self.goal)
        plan.setMinimumWidth(220)
        body.addWidget(plan)
        body.setStretchFactor(0, 1)
        body.setSizes([700, 260])
        body_wrap = QWidget()
        bw = QVBoxLayout(body_wrap)
        bw.setContentsMargins(0, 0, 0, 0)
        bw.setSpacing(0)
        bw.addWidget(body, 1)

        composer_wrap = QWidget()
        cw = QHBoxLayout(composer_wrap)
        cw.setContentsMargins(18, 6, 18, 12)
        composer = QFrame(objectName="composer")
        cl = QHBoxLayout(composer)
        cl.setContentsMargins(14, 8, 8, 8)
        from .window import InputBox  # döngüsel içe aktarmayı önlemek için burada

        self.input = InputBox(objectName="inputBox")
        self.input.setFixedHeight(52)
        self.input.setPlaceholderText("Ekibe not yaz — yönetici kalan planı buna göre günceller…")
        self.input.submitted.connect(self._send)
        send = QPushButton(objectName="sendButton")
        send.setIcon(icon("arrow-up", "#ffffff", 18))
        send.setFixedSize(34, 34)
        send.setCursor(Qt.PointingHandCursor)
        send.clicked.connect(self._send)
        cl.addWidget(self.input, 1)
        cl.addWidget(send, 0, Qt.AlignBottom)
        cw.addWidget(composer)
        bw.addWidget(composer_wrap)
        self.stack.addWidget(body_wrap)
        lay.addWidget(self.stack, 1)
        self.show_task(None)

    def _send(self):
        text = self.input.toPlainText().strip()
        if text and self.task:
            self.input.clear()
            self.send_note.emit(text)

    # ---- görev gösterimi
    def show_task(self, task: Task | None, live_text: str = ""):
        self.task = task
        for w in (self.status_chip, self.model_chip, self.folder_btn, self.run_btn):
            w.setVisible(task is not None)
        if task is None:
            self.title.setText("Grup Çalışması")
            self.stack.setCurrentIndex(0)
            return
        self.stack.setCurrentIndex(1)
        self.goal.setText(task.goal)
        self.feed.clear()
        self.feed.root = task.folder  # ajanların göreli dosya yolları görev klasörüne göredir
        counter = 0
        for ev in list(task.feed):
            kind = ev.get("type")
            if kind == "speaker":
                self.start_speaker(ev.get("who", ""), show_time=False)
            elif kind == "text":
                self.feed.append_text(ev.get("text", ""))
                self.feed.end_segment()
            elif kind == "tool":
                counter += 1
                cid = f"f{counter}"
                self.feed.start_tool(cid, ev.get("name", "?"), ev.get("args") or {})
                self.feed.end_tool(cid, ev.get("result", ""), ev.get("error", False), live=False)
            elif kind == "notice":
                self.feed.add_notice(ev.get("text", ""), C["muted"])
            elif kind == "user":
                self.feed.add_user(ev.get("text", ""))
        if live_text:
            self.feed.append_text(live_text)
        elif not task.running:
            self.feed._close_bubble()
        self.feed.title_fn = lambda: task.title
        self.feed.flush()
        self.update_task()

    def start_speaker(self, who: str, show_time: bool = True):
        self.feed.start_turn("", show_time=show_time, who=self.label_for(who).lower())

    def update_task(self):
        task = self.task
        if task is None:
            return
        self.title.setText(task.title)
        self.status_chip.setText(STATUS_LABELS.get(task.status, task.status))
        self.model_chip.setText(f"yönetici · {task.model or task.provider}")
        if task.running or task.status == "queued":
            self.run_btn.setText("⏹ Durdur")
            self.run_btn.setProperty("act", "stop")
        else:
            self.run_btn.setText("▶ Devam et" if task.status != "done" else "↻ Yeniden planla")
            self.run_btn.setProperty("act", "resume")
        self.steps.clear()
        if not task.steps:
            self.steps.addItem("Yönetici planı hazırlıyor…" if task.running else "Plan yok")
        for i, st in enumerate(task.steps, 1):
            icon = STEP_ICONS.get(st["status"], "○")
            item = QListWidgetItem(f"{icon}  {i}. {st['title']}\n      {self.label_for(st['agent'])}")
            if st["status"] in ("running", "revising"):
                item.setForeground(Qt.white)
                f = item.font()
                f.setBold(True)
                item.setFont(f)
            elif st["status"] == "done":
                item.setForeground(Qt.gray)
            elif st["status"] == "failed":
                item.setForeground(Qt.red)
            self.steps.addItem(item)


def open_folder(path: str):
    QDesktopServices.openUrl(QUrl.fromLocalFile(path))
