"""Arka plan işçisi: ajanı arayüzü dondurmadan ayrı iş parçacığında çalıştırır."""

import threading

from PySide6.QtCore import QThread, Signal

from ..agent import Agent, Cancelled, describe_error
from ..manager import Manager

from .chat import tool_label, TOOL_LABELS


class AgentWorker(QThread):
    text = Signal(str)
    thinking = Signal(str)
    model_started = Signal(int)
    model_ended = Signal(dict)
    tool_start = Signal(str, str, dict)
    tool_end = Signal(str, str, bool)
    approval_needed = Signal(str, dict)
    security_note = Signal(str, str, str)  # (not metni, karar, "neden?" açıklaması)
    team_task = Signal(str, str)
    plan = Signal(object)  # yöneticinin planı: None (çıkarılıyor), [] (gerek yok) ya da adım listesi
    plan_step = Signal(int, str, str)  # (adım sırası, durum, not)
    route_note = Signal(str)  # yöneticinin model notu ("işi X yapıyor")
    media = Signal(str, int, str)  # Görsel sekmesi: (dosya, yüzde; <0 bitti, not)
    failed = Signal(str)
    stopped = Signal()

    def __init__(self, agent: Agent, provider: str, messages: list, user_text: str):
        super().__init__()
        self.agent, self.provider, self.messages, self.user_text = agent, provider, messages, user_text
        self._cancel = threading.Event()
        self._approval_event = threading.Event()
        self._approval_result = False
        self.stats: list[dict] = []
        self.turn_text = ""
        agent.cb = self

    # Callbacks protokolü (işçi iş parçacığında çağrılır)
    def on_text(self, delta):
        self.turn_text += delta
        self.text.emit(delta)

    def on_thinking(self, delta): self.thinking.emit(delta)

    def on_model_start(self, step):
        self.turn_text = ""  # onay penceresi için: modelin bu adımda yazdığı açıklama
        self.model_started.emit(step)

    def on_tool_start(self, call_id, name, args): self.tool_start.emit(call_id, name, args)
    def on_tool_end(self, call_id, result, is_error): self.tool_end.emit(call_id, result, is_error)
    def is_cancelled(self): return self._cancel.is_set()
    def on_plan(self, steps): self.plan.emit(None if steps is None else [dict(s) for s in steps])
    def on_step(self, i, status, note): self.plan_step.emit(i, status, note)
    def on_route(self, text): self.route_note.emit(text)
    def on_media(self, path, pct, text): self.media.emit(path, pct, text)

    def on_model_end(self, stats):
        self.stats.append(stats)
        self.model_ended.emit(stats)

    def on_security(self, name, decision, tier, reason, args=None, verdict=None):
        from .. import security

        label = tool_label(name) if name in TOOL_LABELS else name
        why = security.explain(label, args or {}, verdict) if verdict is not None else ""
        self.security_note.emit(security.note(label, decision, tier, reason), decision, why)

    def ask_approval(self, name, args) -> bool:
        self._approval_event.clear()
        self.approval_needed.emit(name, args)
        self._approval_event.wait()
        return self._approval_result

    def answer_approval(self, allowed: bool):
        self._approval_result = allowed
        self._approval_event.set()

    def start_team_task(self, title: str, goal: str) -> str:
        self.team_task.emit(title, goal)
        return (f"The task '{title}' was handed to the team in the Grup Çalışması (group work) area. The manager "
                "will plan it and the agents will work on it there; the final report will appear in "
                "that task. Tell the user this in one or two sentences; do not do the work yourself.")

    def cancel(self):
        self._cancel.set()
        self.answer_approval(False)

    def run(self):
        try:
            Manager(self.agent).run(self.provider, self.messages, self.user_text)
        except Cancelled:
            self.stopped.emit()
        except Exception as e:
            self.failed.emit(describe_error(e))
