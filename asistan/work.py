"""Çalışma alanı: yönetici bir görevi planlar, ajanlar adımları sırayla yapar, yönetici kontrol edip raporlar.

Arayüzden bağımsızdır; olaylar `TeamCallbacks` üzerinden bildirilir. Görevler JSON dosyaları olarak
saklanır; yarıda kalan bir görev kaldığı adımdan devam ettirilebilir.
"""

import json
import re
import time
import uuid
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Protocol

from . import roster, specialists
from .agent import Agent, Cancelled, settings_for
from .config import DATA_DIR, Settings
from .connections import Connection
from .profiles import AgentProfile

TASKS_DIR = DATA_DIR / "gorevler"
GENERAL_ID = "genel"  # profili olmayan, tüm araçlara sahip genel asistan
MANAGER_ID = "yonetici"
MAX_STEPS = 6
MAX_REVISIONS = 1  # yöneticinin bir adımı en fazla kaç kez geri göndereceği
OUTPUT_IN_CONTEXT = 1500  # sonraki adımlara aktarılan çıktı uzunluğu (küçük bağlam penceresi için)

STATUS_LABELS = {
    "queued": "… sırada",
    "planning": "■ planlanıyor",
    "running": "■ çalışılıyor",
    "waiting": "? onay bekliyor",
    "done": "✓ bitti",
    "stopped": "■ durduruldu",
    "failed": "✗ hata",
}
STEP_ICONS = {"pending": "○", "running": "▶", "done": "✓", "failed": "✗", "revising": "↻"}

PLAN_SCHEMA = {
    "type": "object",
    "properties": {
        "steps": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "agent": {"type": "string"},
                    "title": {"type": "string"},
                    "instruction": {"type": "string"},
                },
                "required": ["agent", "title", "instruction"],
            },
        },
    },
    "required": ["steps"],
}

REVIEW_SCHEMA = {
    "type": "object",
    "properties": {"approved": {"type": "boolean"}, "feedback": {"type": "string"}},
    "required": ["approved", "feedback"],
}

MANAGER_PROMPT = (
    "You are the manager of a team of AI agents and specialist models working for the user, like a "
    "decisive, solution-oriented project lead. The user wants results, not excuses: never answer that "
    "something is impossible or outside the team's abilities. When a job needs an ability a member lacks, "
    "route it: images go to members who use look_at_image (the vision model), hard reasoning to "
    "ask_specialist, web facts to the researcher, code to the coder. When information is missing, choose a "
    "sensible assumption, state it, and keep going. Give members precise, actionable instructions with the "
    "exact deliverable (file name and format). Judge their work strictly but fairly and push for a usable "
    "result. You do not do the work yourself. Write all titles, instructions, feedback and reports in the "
    "user's language (usually Turkish)."
)


@dataclass
class Task:
    title: str
    goal: str
    provider: str  # yöneticinin (ve kendi modeli olmayan ajanların) sağlayıcısı
    model: str
    folder: str
    id: str = field(default_factory=lambda: uuid.uuid4().hex[:12])
    created: float = field(default_factory=time.time)
    updated: float = field(default_factory=time.time)
    status: str = "planning"
    steps: list = field(default_factory=list)  # {id, agent, title, instruction, status, output, attempts}
    feed: list = field(default_factory=list)  # iş odasında görünen olaylar
    notes: list = field(default_factory=list)  # kullanıcının henüz işlenmemiş notları
    report: str = ""

    @property
    def path(self) -> Path:
        return TASKS_DIR / f"{self.id}.json"

    def save(self) -> None:
        TASKS_DIR.mkdir(parents=True, exist_ok=True)
        self.updated = time.time()
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(json.dumps(asdict(self), ensure_ascii=False, indent=1), encoding="utf-8")
        tmp.replace(self.path)

    def delete(self) -> None:
        self.path.unlink(missing_ok=True)

    @property
    def running(self) -> bool:
        return self.status in ("planning", "running", "waiting")


def load_tasks() -> list[Task]:
    tasks = []
    for path in TASKS_DIR.glob("*.json"):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            known = {k: v for k, v in data.items() if k in Task.__dataclass_fields__}
            task = Task(**known)
        except (OSError, ValueError, TypeError):
            continue
        if task.running or task.status == "queued":  # program kapanırken çalışıyordu
            task.status = "stopped"
        tasks.append(task)
    return sorted(tasks, key=lambda t: t.updated, reverse=True)


def _slug(title: str, empty: str) -> str:
    table = str.maketrans("çğıöşüÇĞİÖŞÜ", "cgiosuCGIOSU")
    return re.sub(r"[^a-z0-9]+", "-", title.translate(table).lower()).strip("-")[:40] or empty


def task_folder(workspace: str, title: str, task_id: str) -> str:
    return str(Path(workspace, "gorevler", f"{_slug(title, 'gorev')}-{task_id[:4]}"))


# sohbetin iş klasörü için kategori: ilk eşleşen kazanır (3D, "model" kelimesi dil modelleriyle karışmasın diye önde)
CATEGORIES = [
    ("3D Modeller", r"\b3\s?d\b|\bstl\b|yazıcı|printer|openscad|freecad|blender|dilimle|slicer"),
    ("Görseller", r"resim|görsel|fotoğraf|foto\b|logo|çizim|illüstrasyon|afiş"),
    ("Hikâyeler", r"hik[aâ]ye|öykü|roman|şiir|masal|senaryo"),
    ("Belgeler", r"rapor|belge|dilekçe|mektup|sunum|\bpdf\b|\bword\b|docx|özgeçmiş|\bcv\b"),
    ("Veri", r"excel|xlsx|\bcsv\b|tablo|veri|analiz|grafik"),
    ("Ses", r"\bses\b|müzik|\bmp3\b|\bwav\b|seslendir|podcast"),
    ("Kod", r"\bkod|python|betik|script|program|uygulama|arayüz|\bsite\b|web|\bapi\b|hata ayıkla"),
]


def guess_category(text: str) -> str:
    """İsteğin konusu → çalışma klasöründeki kategori klasörü (bulunamazsa "Genel")."""
    low = (text or "").lower()
    return next((name for name, rx in CATEGORIES if re.search(rx, low)), "Genel")


def chat_folder(workspace: str, category: str, title: str, conv_id: str) -> str:
    """Her sohbetin kendi iş klasörü: <çalışma klasörü>/<kategori>/<başlık>-<id>. Asistan yalnızca burada
    çalışır; çalışma klasöründe eski işlerin dosyalarını görüp yeni isteği onlarla karıştırmaz."""
    category = re.sub(r"[\\/:*?\"<>|]+", "-", category).strip(" .-") or "Genel"
    return str(Path(workspace, category, f"{_slug(title, 'is')}-{conv_id[:4]}"))


def safe_in_folder(folder: str, name: str, args: dict) -> bool:
    """Görev klasöründe kalan komut ve kodlar onaysız çalışır; dışına çıkabilecekler sorulur.

    Kaba bir denetimdir: şüpheli görünen her şey kullanıcıya sorulur.
    """
    if name not in ("run_command", "run_python"):
        return False
    text = str(args.get("command") or args.get("code") or "")
    if re.search(r"\bsudo\b|\.\.|~|\$HOME|\bsystemctl\b|\bpkexec\b|\bchmod\b|\bchown\b|\bdd\b", text):
        return False
    # K12-A8: internete gönderme, paket kurma ve silme klasör içinde de kullanıcı onayı ister (CLAUDE.md); otomatik
    # onay yalnızca klasörde okuyan/hesaplayan/yazan komut ve kodlar için
    if re.search(r"\b(curl|wget|nc|ncat|ssh|scp|rsync|ftp|telnet|sftp)\b|\bgit\s+(push|pull|fetch|clone)\b|"
                 r"\b(pip3?|pipx|npm|pnpm|yarn|pacman|yay|paru|apt(-get)?|dnf|yum|flatpak|snap|brew|cargo|winget)\s+"
                 r"(install|add|-S\w*|-i)\b|-m\s+pip\b|\brm\b|\brmdir\b|\bshred\b|\bunlink\b|"
                 r"\b(subprocess|socket|requests|httpx|urllib|aiohttp|ftplib|smtplib|shutil\.rmtree|os\.remove|"
                 r"os\.unlink|os\.rmdir|os\.system|os\.popen|\.unlink\(|rmtree\()", text):
        return False
    allowed = (folder, "/tmp", "/dev/null", "/usr/bin/", "/bin/")
    for path in re.findall(r"(?<![\w.:/-])/[\w./+-]+", text):
        if not path.startswith(allowed):
            return False
    return True


def parse_json(text: str) -> dict | None:
    text = text.strip()
    fence = re.search(r"```(?:json)?\s*(.*?)```", text, re.S)
    if fence:
        text = fence.group(1)
    start, end = text.find("{"), text.rfind("}")
    if start < 0 or end <= start:
        return None
    try:
        data = json.loads(text[start : end + 1])
    except ValueError:
        return None
    return data if isinstance(data, dict) else None


class TeamCallbacks(Protocol):
    def speaker(self, who: str) -> None: ...  # yeni konuşmacı (yönetici ya da ajan id)
    def on_text(self, delta: str) -> None: ...
    def on_thinking(self, delta: str) -> None: ...
    def on_model_start(self, step: int) -> None: ...
    def on_model_end(self, stats: dict) -> None: ...
    def on_tool_start(self, call_id: str, name: str, args: dict) -> None: ...
    def on_tool_end(self, call_id: str, result: str, is_error: bool) -> None: ...
    def ask_approval(self, name: str, args: dict) -> bool: ...
    def is_cancelled(self) -> bool: ...
    def notice(self, text: str) -> None: ...  # kısa sistem bilgisi
    def changed(self) -> None: ...  # durum / plan değişti


class _Relay:
    """Ajanın olaylarını ekip arayüzüne iletir ve görevin akışına (feed) kaydeder."""

    def __init__(self, runner: "TeamRunner", quiet: bool = False):
        self.r, self.quiet = runner, quiet
        self.text = ""  # bu çağrıda üretilen tüm metin
        self.tools: dict[str, tuple[str, dict]] = {}

    def on_text(self, delta):
        self.text += delta
        if not self.quiet:
            self.r.buffer += delta
            self.r.cb.on_text(delta)

    def on_thinking(self, delta):
        if not self.quiet:
            self.r.cb.on_thinking(delta)

    def on_model_start(self, step):
        self.r.cb.on_model_start(step)

    def on_model_end(self, stats):
        self.r.cb.on_model_end(stats)

    def on_tool_start(self, call_id, name, args):
        self.r.flush_text()
        self.tools[call_id] = (name, args)
        self.r.cb.on_tool_start(call_id, name, args)

    def on_tool_end(self, call_id, result, is_error):
        name, args = self.tools.pop(call_id, ("?", {}))
        self.r.add_event({"type": "tool", "name": name, "args": args, "result": result[:3000], "error": is_error})
        self.r.cb.on_tool_end(call_id, result, is_error)

    def on_security(self, name, decision, tier, reason, *_):
        from . import security

        self.r.notice(security.note(name, decision, tier, reason))

    def ask_approval(self, name, args):
        self.r.set_status("waiting")
        try:
            return self.r.cb.ask_approval(name, args)
        finally:
            self.r.set_status("running")

    def is_cancelled(self):
        return self.r.cb.is_cancelled()

    def start_team_task(self, title, goal):
        return "Not available inside a team task."


class TeamRunner:
    def __init__(self, task: Task, settings: Settings, profiles: list[AgentProfile],
                 connections: list[Connection], callbacks: TeamCallbacks):
        self.task, self.settings = task, settings
        self.profiles = {p.id: p for p in profiles}
        self.connections, self.cb = connections, callbacks
        self.buffer = ""  # henüz akışa yazılmamış canlı metin

    # ---- akış (feed) kaydı
    def add_event(self, event: dict):
        event.setdefault("time", time.time())
        self.task.feed.append(event)
        self.task.save()

    def flush_text(self):
        if self.buffer.strip():
            self.add_event({"type": "text", "text": self.buffer})
        self.buffer = ""

    def say(self, who: str, text: str = ""):
        """Yeni konuşmacı başlatır; metin verilirse hemen yazar."""
        self.flush_text()
        self.add_event({"type": "speaker", "who": who})
        self.cb.speaker(who)
        if text:
            self.buffer = text
            self.cb.on_text(text)
            self.flush_text()

    def notice(self, text: str):
        self.flush_text()
        self.add_event({"type": "notice", "text": text})
        self.cb.notice(text)

    def set_status(self, status: str):
        self.task.status = status
        self.task.save()
        self.cb.changed()

    # ---- model çağrıları
    def _agent(self, profile: AgentProfile | None, relay: _Relay) -> tuple[Agent, str]:
        # model: ajanın kendi modeli > işine göre otomatik seçim (roster) > görevin modeli
        provider, model = roster.assign(self.settings, profile, (self.task.provider, self.task.model))
        if provider.startswith("api:") and not any(c.id == provider[4:] for c in self.connections):
            provider, model = self.task.provider, self.task.model  # ajanın bağlantısı silinmiş
        s = settings_for(self.settings, provider, model, self.task.folder)
        agent = Agent(s, relay, profile, self.connections)
        folder = self.task.folder
        agent.auto_approve = lambda name, args: safe_in_folder(folder, name, args)
        return agent, provider

    def _manager(self, relay: _Relay) -> tuple[Agent, str]:
        profile = AgentProfile(id=MANAGER_ID, name="Yönetici", icon="briefcase", prompt=MANAGER_PROMPT, tools=[])
        agent, provider = self._agent(profile, relay)
        agent.nudges = False  # plan, kontrol ve rapor yazar; "iş bitmedi, araçla yap" dürtmesi onu döngüye sokar
        return agent, provider

    def ask_json(self, prompt: str, schema: dict) -> dict | None:
        for attempt in range(2):
            relay = _Relay(self, quiet=True)
            agent, provider = self._manager(relay)
            agent.json_format = schema
            agent.extra_system = "Answer with a single JSON object only, no other text."
            messages = []
            agent.run(provider, messages, prompt if attempt == 0 else prompt + "\n\nReturn ONLY valid JSON.")
            data = parse_json(relay.text)
            if data is not None:
                return data
        return None

    # ---- ekip bilgisi
    def _member(self, agent_id: str) -> AgentProfile | None:
        return self.profiles.get(agent_id)

    def member_label(self, agent_id: str) -> str:
        if agent_id == MANAGER_ID:
            return "Yönetici"
        p = self._member(agent_id)
        return p.name if p else "Genel asistan"

    def _team_listing(self) -> str:
        lines = [f"- {GENERAL_ID}: Genel asistan — her türlü iş; dosya, komut, Python, web araçlarının hepsi"]
        for p in self.profiles.values():
            tools = "all tools" if p.tools is None else (", ".join(p.tools) or "no tools")
            lines.append(f"- {p.id}: {p.name} — {p.description} (tools: {tools})")
        # her üye look_at_image ve ask_specialist ile uzman modellere danışabilir
        experts = ", ".join(f"{role}: {specialists.describe(self.settings, role)}" for role in specialists.ROLES)
        lines.append(f"Every member can also use look_at_image and ask_specialist. Specialist models: {experts}.")
        return "\n".join(lines)

    def _plan_text(self, current: str | None = None) -> str:
        lines = []
        for i, st in enumerate(self.task.steps, 1):
            mark = "→ SEN" if st["id"] == current else {"done": "✓", "failed": "✗"}.get(st["status"], " ")
            lines.append(f"{i}. [{mark}] {self.member_label(st['agent'])} — {st['title']}")
        return "\n".join(lines)

    def _outputs_text(self) -> str:
        parts = []
        for i, st in enumerate(self.task.steps, 1):
            if st["status"] == "done" and st.get("output"):
                out = st["output"].strip()
                if len(out) > OUTPUT_IN_CONTEXT:
                    out = out[:OUTPUT_IN_CONTEXT] + "\n[… kısaltıldı; ayrıntılar görev klasöründeki dosyalarda]"
                parts.append(f"### {i}. {st['title']} ({self.member_label(st['agent'])})\n{out}")
        return "\n\n".join(parts) or "(henüz yok)"

    def _files_text(self) -> str:
        root = Path(self.task.folder)
        files = [str(p.relative_to(root)) for p in sorted(root.rglob("*")) if p.is_file()][:50]
        return "\n".join(f"- {f}" for f in files) or "(dosya yok)"

    def _take_notes(self) -> str:
        notes, self.task.notes = self.task.notes, []
        return "\n".join(f"- {n}" for n in notes)

    # ---- planlama
    def plan(self, notes: str = ""):
        self.set_status("planning")
        done = [st for st in self.task.steps if st["status"] == "done"]
        prompt = (
            f"Job from the user:\n{self.task.goal}\n\n"
            f"Team members (use the id in the 'agent' field):\n{self._team_listing()}\n\n"
        )
        if done:
            prompt += f"Steps already completed:\n{self._plan_text()}\n\nTheir results:\n{self._outputs_text()}\n\n"
        if notes:
            prompt += f"New notes from the user (take them into account):\n{notes}\n\n"
        prompt += (
            f"Plan the {'remaining ' if done else ''}work as 1-{MAX_STEPS} steps. Each step goes to exactly one "
            "team member and must have a short title and a clear, self-contained instruction saying what "
            "to produce (files are saved in the shared task folder). Use as few steps as the job really "
            "needs; a simple job can be a single step. If the job involves images, the first step must have a "
            "member look at them with look_at_image. Never plan a step that only concludes something can't be "
            "done — plan how to get it done. "
            + ("If nothing more is needed, return an empty steps list. " if done else "")
            + 'Respond as JSON: {"steps": [{"agent": "...", "title": "...", "instruction": "..."}]}'
        )
        data = self.ask_json(prompt, PLAN_SCHEMA)
        raw = (data or {}).get("steps")
        if not isinstance(raw, list) or (not raw and not done):
            # model plan çıkaramadıysa işi tek adımda genel asistana ver
            raw = [] if done else [{"agent": GENERAL_ID, "title": self.task.title, "instruction": self.task.goal}]
        new_steps = []
        for item in raw[:MAX_STEPS]:
            if not isinstance(item, dict):
                continue
            agent_id = str(item.get("agent", "")).strip()
            if agent_id not in self.profiles:
                # yerel modeller bazen id yerine adı yazar
                agent_id = next((p.id for p in self.profiles.values() if p.name.lower() == agent_id.lower()),
                                GENERAL_ID)
            new_steps.append({
                "id": uuid.uuid4().hex[:8], "agent": agent_id,
                "title": str(item.get("title") or "Adım").strip(),
                "instruction": str(item.get("instruction") or self.task.goal).strip(),
                "status": "pending", "output": "", "attempts": 0,
            })
        self.task.steps = done + new_steps
        self.task.save()
        self.cb.changed()
        if new_steps:
            lines = [f"{i}. **{self.member_label(st['agent'])}** — {st['title']}"
                     for i, st in enumerate(new_steps, len(done) + 1)]
            intro = "Planı güncelledim:" if done else "Görevi şu adımlara böldüm:"
            self.say(MANAGER_ID, intro + "\n\n" + "\n".join(lines))
        elif done:
            self.say(MANAGER_ID, "Notunu değerlendirdim; ek bir adıma gerek görmedim.")

    # ---- adım çalıştırma
    def run_step(self, st: dict, feedback: str = "", notes: str = "") -> str:
        st["status"] = "revising" if feedback else "running"
        self.set_status("running")
        profile = self._member(st["agent"])
        relay = _Relay(self)
        agent, provider = self._agent(profile, relay)
        agent.extra_system = (
            "You are one member of a team working on a shared job. Do only your own step, save any "
            "substantial result as a file in the current folder (the shared task folder), and finish "
            "with a short summary of what you did and which files you created."
        )
        prompt = (
            f"# Takım görevi\n{self.task.goal}\n\n"
            f"## Plan\n{self._plan_text(st['id'])}\n\n"
            f"## Önceki adımların çıktıları\n{self._outputs_text()}\n\n"
            f"## Görev klasöründeki dosyalar\n{self._files_text()}\n\n"
        )
        if notes:
            prompt += f"## Kullanıcının notları\n{notes}\n\n"
        prompt += f"## Senin adımın: {st['title']}\n{st['instruction']}\n"
        if feedback:
            prompt += f"\n## Yöneticinin geri bildirimi (düzelt)\n{feedback}\n"
        self.say(st["agent"])
        agent.run(provider, [], prompt)
        self.flush_text()
        return relay.text.strip()

    def review(self, st: dict, output: str) -> tuple[bool, str]:
        prompt = (
            f"Job: {self.task.goal}\n\nStep assigned to {self.member_label(st['agent'])}: {st['title']}\n"
            f"Instruction: {st['instruction']}\n\nTheir result:\n{output[:4000]}\n\n"
            f"Files in the task folder:\n{self._files_text()}\n\n"
            "Does this result complete the step well enough to continue? Approve unless something "
            "important is missing or wrong, or the member gave up / said it can't be done. If not approved, "
            "give concrete, directive feedback: exactly what to do next and which tool or specialist to use. "
            'Respond as JSON: {"approved": true/false, "feedback": "..."}'
        )
        data = self.ask_json(prompt, REVIEW_SCHEMA)
        if data is None:
            return True, ""
        return bool(data.get("approved", True)), str(data.get("feedback") or "")

    def final_report(self):
        relay = _Relay(self)
        agent, provider = self._manager(relay)
        prompt = (
            f"Job from the user:\n{self.task.goal}\n\nPlan and status:\n{self._plan_text()}\n\n"
            f"Results:\n{self._outputs_text()}\n\nFiles in the task folder ({self.task.folder}):\n"
            f"{self._files_text()}\n\n"
            "Write the final report to the user in Markdown with exactly these sections: "
            "'## Sonuç' (the answer or deliverable itself, concrete and complete), "
            "'## Önerim' (your clear recommendation / decision, not a list of options), "
            "'## Sonraki adımlar' (2-4 concrete actions, each doable right away), "
            "and a short 'Dosyalar' line listing the files to open. State any assumptions you made. "
            "Be direct and confident; do not apologise or list what the team couldn't do — say how to get it done."
        )
        self.say(MANAGER_ID)
        agent.run(provider, [], prompt)
        self.flush_text()
        self.task.report = relay.text.strip()

    # ---- ana döngü
    def run(self):
        task = self.task
        Path(task.folder).mkdir(parents=True, exist_ok=True)
        for st in task.steps:
            if st["status"] in ("running", "revising", "failed"):  # yarıda kalanı yeniden dene
                st["status"] = "pending"
        try:
            notes = self._take_notes()
            if not task.steps or notes:
                self.plan(notes)
                notes = ""
            report_needed = not task.report or any(st["status"] == "pending" for st in task.steps)
            while True:
                st = next((s for s in task.steps if s["status"] == "pending"), None)
                if st is None:
                    break
                new_notes = self._take_notes()
                if new_notes:  # kullanıcı araya girdi: kalan adımları yeniden planla
                    task.steps = [s for s in task.steps if s["status"] != "pending"]
                    self.plan(new_notes)
                    continue
                output = self.run_step(st)
                while True:
                    ok, feedback = self.review(st, output)
                    if ok or st["attempts"] >= MAX_REVISIONS:
                        break
                    st["attempts"] += 1
                    self.say(MANAGER_ID, f"🔁 **{self.member_label(st['agent'])}** adımı tekrar yapsın:\n\n{feedback}")
                    output = self.run_step(st, feedback)
                st["output"] = output
                st["status"] = "done"
                task.save()
                self.cb.changed()
                self.notice(f"✓ {st['title']} tamamlandı")
            if report_needed:
                self.final_report()
            self.set_status("done")
        except Cancelled:
            self.flush_text()
            self.set_status("stopped")
            self.notice("⏹ Görev durduruldu. Kaldığı yerden devam ettirebilirsin.")
            raise
        except Exception:
            self.flush_text()
            for st in task.steps:
                if st["status"] in ("running", "revising"):
                    st["status"] = "failed"
            self.set_status("failed")
            raise
