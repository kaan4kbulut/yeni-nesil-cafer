"""Ana pencere: grup çalışması (görevler)."""

from pathlib import Path

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QMessageBox

from .. import roster
from ..work import MANAGER_ID, Task, task_folder

from .dialogs import ApprovalDialog
from .theme import C
from .work import NewTaskDialog, open_folder, TaskWorker


class GroupMixin:
    """MainWindow'un parçası (window.py); konusu modülün açıklamasında."""

    # ---- grup alanı (görevler)
    def _member_label(self, who: str) -> str:
        if who == MANAGER_ID:
            return "Yönetici"
        p = next((p for p in self.profiles if p.id == who), None)
        return p.name if p else "Genel asistan"

    def _find_task(self, task_id: str) -> Task | None:
        return next((t for t in self.tasks if t.id == task_id), None)

    def _refresh_tasks(self):
        self.tasks.sort(key=lambda t: t.updated, reverse=True)
        current = self.work_room.task.id if self.work_room.task else ""
        self.work_panel.refresh(self.tasks, current)
        running = sum(1 for t in self.tasks if t.running or t.status == "queued")
        self.side_tabs.button(1).set_key(f"{running} ■" if running else "")  # yalnızca çalışan görev varsa

    def _new_task_dialog(self):
        dlg = NewTaskDialog(self)
        if dlg.exec():
            # model seçilmez: yönetici ve ajanların modelleri işe göre otomatik (roster); bu yalnızca yedek
            found = roster.pick_for(self.settings, None)
            provider, model = (found.provider, found.model) if found else (self.provider, self.model_box.currentText())
            self._create_task(dlg.result_title, dlg.result_goal, provider, model)

    def _create_task(self, title: str, goal: str, provider: str, model: str, show: bool = True):
        title = (title or goal.splitlines()[0] if goal else "Görev")[:60]
        free = self._free_model()
        if free:  # sansürsüz modda verilen görev: ekip de sansürsüz çalışır (başlıktaki 🔓 bunu işaretler)
            title, provider, model = "🔓 " + title.lstrip("🔓 "), "ollama", free
        task = Task(title=title, goal=goal, provider=provider, model=model, folder="")
        task.folder = task_folder(self.settings.workspace, title, task.id)
        task.feed.append({"type": "user", "text": goal})
        task.save()
        self.tasks.insert(0, task)
        self._start_task(task)
        if show:
            self.side_tabs.button(1).click()
            self._show_task(task.id)
        else:
            self._refresh_tasks()
            self._notify(f"“{title}” gruba verildi — Grup Çalışması sekmesinden izleyebilirsin", 10000)

    def _show_task(self, task_id: str):
        task = self._find_task(task_id)
        live = ""
        if task and self.task_worker and self.task_worker.task is task:
            live = self.task_worker.runner.buffer
        self.work_room.show_task(task, live)
        self.center_stack.setCurrentIndex(1)
        self._refresh_tasks()

    def _start_task(self, task: Task):
        if self.task_worker is not None:
            if task is not self.task_worker.task and task not in self.task_queue:
                task.status = "queued"
                task.save()
                self.task_queue.append(task)
            self._task_changed(task)
            return
        run_settings = self._run_settings() if task.title.startswith("🔓") else self.settings
        w = self.task_worker = TaskWorker(task, run_settings, self.profiles, self.connections)
        in_room = lambda: self.work_room.task is task
        w.speaker.connect(lambda who: in_room() and self.work_room.start_speaker(who))
        w.text.connect(lambda d: in_room() and self.work_room.feed.append_text(d))
        w.thinking.connect(lambda d: in_room() and self.work_room.feed.append_thinking(d))
        w.tool_start.connect(lambda i, n, a: in_room() and self.work_room.feed.start_tool(i, n, a))
        w.tool_end.connect(lambda i, r, e: in_room() and self.work_room.feed.end_tool(i, r, e))
        w.note.connect(lambda t: in_room() and self.work_room.feed.add_notice(t, C["muted"]))
        w.changed.connect(lambda: self._task_changed(task))
        w.approval_needed.connect(self._ask_task_approval)
        w.failed.connect(lambda msg: self._task_failed(task, msg))
        w.finished.connect(self._task_finished)
        task.status = "planning" if not task.steps else "running"
        w.start()
        self._task_changed(task)

    def _task_changed(self, task: Task):
        if self.work_room.task is task:
            self.work_room.update_task()
        self._refresh_tasks()

    def _task_failed(self, task: Task, msg: str):
        task.feed.append({"type": "notice", "text": f"⚠ {msg}"})
        task.save()
        if self.work_room.task is task:
            self.work_room.feed.add_notice(f"⚠ {msg}", C["error"])

    def _task_finished(self):
        task = self.task_worker.task
        self.task_worker.wait()  # tamamen kapanmadan bırakılırsa Qt programı durdurur
        self.task_worker.deleteLater()
        self.task_worker = None
        if self.work_room.task is task:
            self.work_room.feed.end_turn("")  # açık kalan adım grubunu kapat
        self._task_changed(task)
        if task.status == "done":
            self._notify(f"✓ “{task.title}” tamamlandı — rapor Grup Çalışması sekmesinde", 15000)
        if self.task_queue:
            self._start_task(self.task_queue.pop(0))
        else:
            QTimer.singleShot(500, self._check_context)

    def _ask_task_approval(self, name: str, args: dict):
        w = self.task_worker
        context = next((ev.get("text", "") for ev in reversed(w.task.feed) if ev.get("type") == "text"), "")
        dlg = ApprovalDialog(name, args, w.task.folder, context, self)
        dlg.setWindowTitle(f"Onay gerekiyor — {w.task.title}")
        dlg.exec()
        w.answer_approval(dlg.choice in ("allow", "always"))

    def _task_note(self, text: str):
        task = self.work_room.task
        if not task:
            return
        task.feed.append({"type": "user", "text": text})
        task.notes.append(text)
        task.save()
        self.work_room.feed.add_user(text)
        running = self.task_worker and self.task_worker.task is task
        if running:
            self.work_room.feed.add_notice("📝 Not yöneticiye iletildi; sıradaki adımdan önce plana eklenecek.",
                                           C["muted"])
        elif task.status != "queued":
            self._start_task(task)

    def _task_action(self, task_id: str, action: str):
        task = self._find_task(task_id)
        if not task:
            return
        if action == "folder":
            Path(task.folder).mkdir(parents=True, exist_ok=True)
            open_folder(task.folder)
        elif action == "stop":
            if self.task_worker and self.task_worker.task is task:
                self.task_worker.cancel()
            elif task in self.task_queue:
                self.task_queue.remove(task)
                task.status = "stopped"
                task.save()
                self._task_changed(task)
        elif action == "resume":
            if task.status == "done":
                task.notes.append("Sonucu gözden geçir; eksik ya da geliştirilecek bir şey varsa tamamla.")
            self._start_task(task)
        elif action == "delete":
            if self.task_worker and self.task_worker.task is task:
                QMessageBox.information(self, "Görev çalışıyor", "Silmeden önce görevi durdur.")
                return
            if QMessageBox.question(self, "Görevi sil",
                                    f"“{task.title}” silinsin mi?\nGörev klasöründeki dosyalar silinmez.") \
                    != QMessageBox.Yes:
                return
            if task in self.task_queue:
                self.task_queue.remove(task)
            task.delete()
            self.tasks.remove(task)
            if self.work_room.task is task:
                self.work_room.show_task(None)
            self._refresh_tasks()
