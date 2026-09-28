"""Yönetici döngüsü: sohbet isteğini planlar, adımları ajana yaptırır, her adımı doğrular, gerekirse düzelttirir.

Çekirdektir: asistan bu dosyayı kendisi değiştiremez (yalnızca araç ve beceri ekleyebilir).

Akış: basit istek → doğrudan ajan (bugünkü gibi). Çok parçalı iş isteği → plan (1-5 adım, her adımın
"bitti sayılma ölçütü" var) → her adım aynı ajanla, aynı sohbet geçmişinde → adım sonrası doğrulama
(önce programın kendi kanıtı: hangi araç çalıştı, hangisi hata verdi; sonra modelin kısa JSON kararı) →
eksikse bir kez düzeltme → son özet. Adımlar `on_plan` / `on_step` ile arayüzde görünür ve plan,
kullanıcının mesajına `_plan` alanı olarak kaydedilir (sağlayıcıya gitmez; sohbet yeniden açılınca çizilir).
"""

import json
import re
import time
from contextlib import contextmanager
from dataclasses import replace
from pathlib import Path

from . import cli_agents, learning, permissions, roster, specialists
from .cekirdek import modeller, yonlendirici
from .agent import Agent, is_action, is_task_request, _TASK

MAX_PLAN_STEPS = 5
MAX_FIXES = 1  # bir adım en fazla kaç kez düzelttirilir
LONG_REQUEST = 240  # bu kadar uzun iş istekleri de planlanır
PREVIEW_SUFFIXES = {".txt", ".md", ".csv", ".json", ".py", ".html", ".log", ".yaml", ".yml", ".ini", ".sh"}

# adım durumları → arayüz işaretleri
STEP_ICONS = {"pending": "○", "running": "▶", "checking": "…", "fixing": "↻", "done": "✓", "failed": "✗",
              "skipped": "–"}

PLAN_SCHEMA = {
    "type": "object",
    "properties": {
        "steps": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {"title": {"type": "string"}, "do": {"type": "string"},
                               "done_when": {"type": "string"}},
                "required": ["title", "do", "done_when"],
            },
        },
    },
    "required": ["steps"],
}
CHECK_SCHEMA = {
    "type": "object",
    "properties": {"done": {"type": "boolean"}, "missing": {"type": "string"}},
    "required": ["done", "missing"],
}

PLANNER_SYSTEM = (
    "You are the manager of a personal assistant running on the user's computer. You do not do the work "
    "yourself: you split the user's request into a short ordered plan that the assistant will carry out with its "
    "tools, one step at a time. Answer with a single JSON object only.")
CHECKER_SYSTEM = (
    "You are the manager of a personal assistant. You check whether one step of a plan was really done, using "
    "the evidence the program collected (which tools ran and what they returned). Words alone are not evidence: "
    "if the assistant only claims it did something but no tool shows it, the step is not done. Answer with a "
    "single JSON object only.")

# işçi model çalışırken: metinleri kullanıcının seçtiği model yazar (ask_specialist → writer_model)
WORKER_NOTE = (
    "\n\n## You are the hands, not the writer\nThe user chose the model {writer} for writing; you were brought in "
    "because it cannot use tools. For longer creative or personal writing (a story, poem, letter, message, "
    "article) call ask_specialist with role 'general' and a complete brief (topic, length, tone, language) — it "
    "goes to {writer} — then use or save its answer word for word with your tools. Do everything else yourself.")

# gerçek tarayıcı gerektiren istekler (site açmak, sitede aramak, tıklamak, form, sepet…); düz bilgi soruları değil
_BROWSER = re.compile(
    r"https?://|www\.|\b\w+\.(com|com\.tr|net|org|io)\b|tarayıcı|chrome|firefox|siteye|sitesine|sitesinde|"
    r"siteler(e|de|i)|mağazalar(a|da|ı)|hepsiburada|trendyol|amazon|n11|sahibinden|youtube|instagram|twitter|"
    r"linkedin|e-?devlet|sepete|sepet|satın al|giriş yap|oturum aç|formu? doldur|tıkla|internet(ten|te) (bak|gir|"
    r"karşılaştır)|fiyatlar(ı|ına) (bak|karşılaştır)", re.I)


# modelin gerçek veri yerine bıraktığı boş kalıplar: [Ürün Adı], [Fiyat], [Price], (fiyat) …
_PLACEHOLDER = re.compile(r"\[(ürün|urun|fiyat|price|name|ad[ıi]|model|başlık|title|url|adres|link)[^\]\n]{0,25}\]", re.I)


def is_browser_task(text: str) -> bool:
    return bool(_BROWSER.search(learning.original_request(text or "")))


_LIST_ITEM = re.compile(r"(?m)^\s*(?:\d+[.)]|[-*•])\s+\S")
# iş sayılmayan ama bir iş adımı olabilen fiiller ("oku ve grafiğini çiz" iki adımdır)
_STEP_VERBS = re.compile(r"\b(oku|bul|ara|araştır|incele|karşılaştır|özetle|hesapla|çıkar|listele|kontrol et|"
                         r"topla|filtrele|sırala|çevir|ölç|test et|say)", re.I)
_THEN = re.compile(r"\b(sonra|ardından|daha sonra|ayrıca|en son|son olarak|önce)\b", re.I)  # sıra bildiren bağlaçlar


def needs_plan(text: str) -> bool:
    """Bu istek birden fazla parçalı bir iş mi? (tek parçalı istekler plansız, bugünkü gibi yapılır)"""
    if (text or "").startswith(("📈", "↻ ")):
        return False
    request = learning.original_request(text)
    if not request or not is_task_request(request):
        return False
    verbs = sum(1 for rx in (_TASK, _STEP_VERBS) for _ in rx.finditer(request))  # "yaz …, sonra … yaz" iki iş
    return (len(_LIST_ITEM.findall(request)) >= 2 or verbs >= 2 or bool(_THEN.search(request))
            or len(request) > LONG_REQUEST)


def _unreachable(exc: Exception) -> bool:
    """Sağlayıcıya ulaşılamadı ya da anahtar reddedildi: yönlendiricinin sağlık önbelleğine yazılır."""
    import httpx

    if isinstance(exc, (httpx.ConnectError, httpx.TimeoutException, ConnectionError, TimeoutError)):
        return True
    return type(exc).__name__ in ("AuthenticationError", "APIConnectionError", "APITimeoutError",
                                  "PermissionDeniedError") or "(401)" in str(exc)


def parse_json(text: str) -> dict | None:
    """Model cevabından ilk JSON nesnesi (``` içinde ya da metnin arasında olabilir)."""
    text = (text or "").strip()
    fence = re.search(r"```(?:json)?\s*(.*?)```", text, re.S)
    if fence:
        text = fence.group(1)
    start, end = text.find("{"), text.rfind("}")
    if start < 0 or end <= start:
        return None
    try:
        data = json.loads(text[start:end + 1])
    except ValueError:
        return None
    return data if isinstance(data, dict) else None


def clean_steps(data: dict | None) -> list[dict]:
    """Modelin planını güvenli biçime getirir: en çok MAX_PLAN_STEPS adım, boş alan yok."""
    raw = (data or {}).get("steps")
    steps = []
    for item in raw if isinstance(raw, list) else []:
        if not isinstance(item, dict):
            continue
        do = str(item.get("do") or "").strip()
        if not do:
            continue
        steps.append({"title": (str(item.get("title") or "").strip() or do)[:80], "do": do,
                      "done_when": str(item.get("done_when") or "").strip(), "status": "pending", "note": ""})
    return steps[:MAX_PLAN_STEPS]


class _Recorder:
    """Ajanın olaylarını arayüze aynen iletir; bu adımda çalışan araçları doğrulama için kaydeder."""

    def __init__(self, parent):
        self.parent = parent
        self.calls: dict[str, tuple[str, dict]] = {}
        self.events: list[dict] = []  # {name, args, result, error, action}
        self.text = ""

    def on_text(self, delta):
        self.text += delta
        self.parent.on_text(delta)

    def on_tool_start(self, call_id, name, args):
        self.calls[call_id] = (name, args)
        self.parent.on_tool_start(call_id, name, args)

    def on_tool_end(self, call_id, result, is_error):
        name, args = self.calls.pop(call_id, ("?", {}))
        failed = is_error or str(result).startswith(("Error", "exit code: 1", "NOT RUN", "REFUSED", "NOT EXECUTED"))
        self.events.append({"name": name, "args": args, "result": str(result), "error": failed,
                            "action": is_action(name, args)})
        self.parent.on_tool_end(call_id, result, is_error)

    def __getattr__(self, name):  # on_thinking, ask_approval, on_security, is_cancelled…
        return getattr(self.parent, name)


class Manager:
    """Sohbet turunu yöneten döngü. `agent.run` yerine `Manager(agent).run(...)` çağrılır."""

    def __init__(self, agent: Agent):
        self.agent = agent
        self.cb = agent.cb
        self.plan: list[dict] = []
        self.chat = self.worker = self.boss = None  # (sağlayıcı, model): sohbet · işi yapan · planlayan/denetleyen
        self.boss_choice: yonlendirici.Secim | None = None  # yöneticinin kararı (neden, yedekleri)
        self.boss_chain: yonlendirici.Zincir | None = None  # yönetici çağrısı hata verirse sıradaki aday
        self.boss_label = ""  # yönetici değiştiyse "X → Y" (plan kartı)
        self.lessons = ""  # planlamaya giren dersler (Aşama 4)
        self.started = time.time()  # bu turda değişen dosyaların içeriği denetçiye gösterilir
        self._hinted = False  # "daha güçlü model bağla" önerisi bu turda bir kez
        # K4 görev motoru (bayrakla, `cekirdek/istek.py`): plan çıkarılacak işi motora verir; None: eski yol.
        # `motor_karari`: motorun "çok adımlı iş" ölçütü (salt okuyan analiz de); motor ✓ beklemez, her değişikliği
        # kendi adımında sorar
        self.motor = None
        self.motor_karari = None

    # ---- arayüz bildirimleri (callback yoksa sessiz)
    def _emit(self, name: str, *args):
        fn = getattr(self.cb, name, None)
        if fn:
            fn(*args)

    def _set(self, i: int, status: str, note: str = ""):
        self.plan[i]["status"] = status
        if note or status in ("done", "running"):
            self.plan[i]["note"] = note[:300]
        self._emit("on_step", i, status, self.plan[i]["note"])

    # ---- karar
    def should_plan(self, provider: str, text: str) -> bool:
        a = self.agent
        gated = a.gate_actions and self.motor is None
        if a.profile is not None or gated or a.no_tools or not a.tool_specs:
            return False  # uzman ajan sohbeti · onay bekleyen plan turu (✓) · araçsız model: planın anlamı yok
        if cli_agents.is_cli(provider):
            return False  # Claude Code / Codex / Gemini CLI kendi planını yapar
        if provider == "ollama" and self.worker is None:
            return False  # hiçbir kurulu model araç kullanamıyor
        return (self.motor_karari or needs_plan)(text)

    # ---- modeller (Aşama 3: kartlarla; K3: yönlendirici)
    def _pick_models(self, provider: str) -> None:
        a = self.agent
        a._provider = provider
        self.chat = self.worker = self.boss = (provider, a._model())
        if cli_agents.is_cli(provider):
            return
        try:
            self.worker = roster.worker_for(a.settings, self.chat)
        except Exception:
            pass  # seçim yapılamazsa her şey sohbet modeliyle, eskisi gibi
        try:  # yönetici: yönlendiricinin "yonetici" rolü (politika otomatik | yerel | bulut)
            self.boss_choice = yonlendirici.yonetici_sec(a.settings, self.chat)
            self.boss = self.boss_choice.anahtar or self.chat
            self.boss_chain = yonlendirici.Zincir([self.boss] + list(self.boss_choice.zincir) + [self.chat], esik=1)
        except Exception:
            self.boss_choice, self.boss_chain = None, None

    def _route_chat(self, provider: str) -> yonlendirici.Secim | None:
        """Bu turun sohbet modeli: görünür karar ("ollama/x — neden: …"); sağlayıcı çalışmıyorsa yedeği."""
        a = self.agent
        try:
            return yonlendirici.sohbet_secimi(a.settings, provider, a._model(), bool(getattr(a.settings, "auto_model",
                                                                                          False)))
        except Exception:
            return None  # yönlendirici karar veremezse tur eskisi gibi sürer

    def _budget_ok(self, target: tuple[str, str] | None) -> bool:
        """Ücretli bulut modeline gitmeden önce maliyet tavanı (onay kuralı permissions.bulut_tavani'de)."""
        if not target or target[0] == "ollama" or cli_agents.is_cli(target[0]):
            return True
        decision = permissions.bulut_tavani(yonlendirici.tavan_durumu(), yonlendirici.tavan_onaylandi())
        if decision.kind == permissions.ALLOW:
            return True
        ask = getattr(self.cb, "ask_approval", None)
        ok = bool(ask and ask(permissions.BULUT_TAVANI, {
            "purpose": f"Bulut maliyet tavanı aşıldı: {decision.reason}. {target[1]} ile devam edilsin mi? "
                       "(Hayır dersen bu iş yerel modelle sürer.)", "model": f"{target[0]}/{target[1]}"}))
        if ok:
            yonlendirici.tavan_onayla()
        else:
            self._emit("on_route", f"💰 Bulut tavanı aşıldı ({decision.reason}); {target[1]} kullanılmıyor.")
        return ok

    @contextmanager
    def _hands(self):
        """Bu blokta işi işçi model yapar (sohbet modeli araç kullanamıyorsa); sonra sohbet modeline dönülür."""
        a = self.agent
        if self.worker is None or self.worker == self.chat or self.worker[0] != "ollama":
            yield
            return
        old_settings, old_extra = a.settings, a.extra_system
        a.settings = replace(old_settings, ollama_model=self.worker[1],
                             extra={**old_settings.extra, "writer_model": self.chat[1]})
        a.extra_system = (old_extra or "") + WORKER_NOTE.format(writer=self.chat[1])
        try:
            yield
        finally:
            a.settings, a.extra_system = old_settings, old_extra

    def _announce(self, text: str) -> None:
        """Kimin ne yaptığını sohbette kısa bir notla söyler (işçi model, eksik model)."""
        request = learning.original_request(text)
        if self.worker is None and is_task_request(request):
            self._emit("on_route", f"⚠ Kurulu modellerin hiçbiri araç sınavını geçemedi: {self.chat[1]} dosya yazamaz, "
                                   "komut çalıştıramaz. Modeller menüsünden araç kullanabilen küçük bir model indir "
                                   f"(önerilen: {modeller.deger('temel.model')}).")
        elif self.worker and self.worker != self.chat and is_task_request(request):
            self._emit("on_route", f"🔧 İşi **{self.worker[1]}** yapıyor: {self.chat[1]} araç kullanamıyor (model "
                                   f"kartı). Uzun metinleri yine {self.chat[1]} yazar.")

    # ---- model çağrıları (tek seferlik, JSON)
    def _next_boss(self, reason: str) -> bool:
        """Yönetici çağrısı olmadı (401, zaman aşımı, bağlam, tavan): zincirde sıradaki aday; "Yönetici: X → Y"."""
        chain, old = self.boss_chain, self.boss
        if chain is None or old is None:
            return False
        new = chain.basarisiz(reason, zaman_asimi=True)
        while new is not None and tuple(new) == tuple(old):
            new = chain.basarisiz(reason, zaman_asimi=True)
        if new is None:
            return False
        self.boss = tuple(new)
        self.boss_label = f"{(self.boss_label or old[1]).split(' → ')[0]} → {new[1]}"
        self._emit("on_route", f"🧭 Yönetici: {old[1]} → {new[1]} ({reason[:120]})")
        if self.plan:  # plan kartında da görünsün
            for step in self.plan:
                step["yonetici"] = self.boss_label
            self._emit("on_plan", self.plan)
        return True

    def _ask_json(self, provider: str, system: str, prompt: str, schema: dict) -> dict | None:
        a = self.agent
        for _ in range(6):  # yönetici adayları: hata verirse zincirde sıradaki
            provider_, model = self.boss or (provider, a._model())  # yönetici modeli
            if not self._budget_ok((provider_, model)):
                if self._next_boss("bulut tavanı aşıldı"):
                    continue
                return None
            for attempt in range(2):
                a._check_cancel()
                ask = prompt if attempt == 0 else prompt + "\n\nReturn ONLY valid JSON."
                try:
                    answer = specialists.ask(a.settings, a.connections, provider_, model, ask, system=system,
                                             schema=schema)
                except Exception as e:
                    if _unreachable(e):
                        yonlendirici.SAGLIK.bildir(provider_, False, str(e)[:200])
                    break  # bu yönetici olmadı: sıradakine geç
                yonlendirici.harcama_ekle(provider_, (len(system) + len(ask) + len(answer or "")) // 4)
                data = parse_json(answer)
                if data is not None:
                    return data
            else:
                return None  # yönetici cevap verdi ama JSON değil: iş yine yapılır, yalnızca adımlara bölünmez
            if not self._next_boss(f"{model} yanıt vermedi"):
                return None  # plan/denetim çıkmazsa iş yine yapılır, yalnızca adımlara bölünmez
        return None

    def make_plan(self, provider: str, messages: list, text: str) -> list[dict]:
        a = self.agent
        tools = ", ".join(s["name"] for s in a.tool_specs)
        last = next((m.get("content") for m in reversed(messages) if m.get("role") == "assistant"
                     and isinstance(m.get("content"), str) and m["content"].strip()), "")
        request = learning.original_request(text)
        try:
            lessons = learning.planning_prompt(request)  # Aşama 4: işe yarayan tarifler, başarısız yollar
        except Exception:
            lessons = ""
        self.lessons = lessons
        prompt = (
            f"User's request:\n{request}\n\n" + lessons
            + (f"Assistant's previous answer in this chat (for context):\n{last[:1200]}\n\n" if last else "")
            + f"Workspace folder: {a.toolbox.root}\nTools the assistant can use: {tools}\n\n"
            f"Split the work into 1-{MAX_PLAN_STEPS} ordered steps. Each step is one concrete piece of work the "
            "assistant can finish with its tools; later steps may use earlier results. Use as few steps as the job "
            "really needs; a simple request is one step. Do not add steps for asking the user, for approval (the "
            "app handles it) or only for summarising (the app adds a summary). For each step give:\n"
            "- title: very short, in the user's language (usually Turkish)\n"
            "- do: a clear, self-contained instruction (exact file names and formats when files are wanted; plain "
            "names relative to the workspace such as 'rapor.xlsx', never the full folder path). Never invent helper "
            "files, scripts or notes (e.g. 'plan.txt', 'duzenle.py') the user did not ask for: code runs with "
            "run_python without saving a file, and results are the files the user wants\n"
            "- done_when: how to tell from tool results that the step is really done (e.g. 'rapor.xlsx exists and "
            "has a chart sheet')\n"
            'Respond as JSON: {"steps": [{"title": "...", "do": "...", "done_when": "..."}]}')
        return clean_steps(self._ask_json(provider, PLANNER_SYSTEM, prompt, PLAN_SCHEMA))

    # ---- doğrulama
    @property
    def local_boss(self) -> bool:
        """Denetçi yerel mi? Dosya içerikleri buluta gönderilmez (hassas dosyalar yerelde kalır)."""
        return self.boss is None or self.boss[0] == "ollama"

    def _files(self) -> str:
        """Çalışma klasörü (en yeni önce); bu turda değişen küçük metin dosyalarının içeriğiyle birlikte."""
        root = Path(self.agent.toolbox.root)
        try:
            files = sorted((p for p in root.rglob("*") if p.is_file()), key=lambda p: p.stat().st_mtime,
                           reverse=True)[:30]
            lines, shown = [], 0
            for p in files:
                st = p.stat()
                lines.append(f"- {p.relative_to(root)} ({st.st_size} B)")
                if (self.local_boss and shown < 5 and st.st_mtime >= self.started and st.st_size <= 4000
                        and p.suffix.lower() in PREVIEW_SUFFIXES):
                    shown += 1
                    body = p.read_text(encoding="utf-8", errors="replace")
                    lines.append("  content: " + json.dumps(body[:400], ensure_ascii=False))
        except OSError:
            return "(okunamadı)"
        return "\n".join(lines) or "(dosya yok)"

    def check(self, provider: str, step: dict, rec: _Recorder) -> tuple[bool, str]:
        """(bitti mi, eksik ne). Önce programın kanıtı, sonra modelin kararı."""
        actions = [e for e in rec.events if e["action"]]
        if actions and all(e["error"] for e in actions):
            last = next((ln.strip() for ln in reversed(actions[-1]["result"].splitlines()) if ln.strip()), "")
            return False, f"denenen işlemlerin hepsi başarısız oldu ({last[:200]})"
        if self.agent.security_stop:
            return False, "güvenlik ajanı durdurdu"
        if not rec.events and not rec.text.strip():
            return False, "hiçbir şey yapılmadı"
        evidence = "\n".join(
            f"- {e['name']} {json.dumps(e['args'], ensure_ascii=False, default=str)[:200]} → "
            f"{'ERROR ' if e['error'] else ''}{e['result'][:300]}" for e in rec.events[-12:]) or "(no tools ran)"
        later = [s["do"] for s in self.plan[self.plan.index(step) + 1:]] if step in self.plan else []
        prompt = (
            f"Step: {step['do']}\nDone when: {step['done_when'] or '(not given)'}\n"
            + (f"Later steps (NOT part of this step; do not ask for them now): {' | '.join(later)}\n" if later else "")
            + "\n"
            f"Tools that ran in this step and their results:\n{evidence}\n\n"
            f"Files in the workspace (newest first):\n{self._files()}\n\n"
            f"The assistant's own words (not evidence by themselves):\n{rec.text.strip()[-1200:] or '(none)'}\n\n"
            "Check the file contents against the step (right values, counts, format). "
            "Was the step really done? If not, say briefly in the user's language (usually Turkish) exactly what is "
            'missing or wrong. Respond as JSON: {"done": true/false, "missing": "..."}')
        data = self._ask_json(provider, CHECKER_SYSTEM, prompt, CHECK_SCHEMA)
        if data is None:
            return True, ""  # denetçi cevap veremediyse adımı durdurma
        return bool(data.get("done", True)), str(data.get("missing") or "").strip()

    # ---- ana döngü
    def run(self, provider: str, messages: list, text: str) -> None:
        a = self.agent
        self.started = time.time()
        yonlendirici.gorev_basla()  # görev başına bulut token sayacı ve tavan onayı
        route = self._route_chat(provider)
        if route is not None and route.anahtar != (provider, a._model()):
            self._run_elsewhere(route, messages, text)  # sohbet sağlayıcısı çalışmıyor: yedeği ya da "çevrimdışı"
            return
        if route is not None and not self._budget_ok(route.anahtar):
            self._run_elsewhere(yonlendirici.yerel_sec(a.settings), messages, text)
            return
        if route is not None:
            self._emit("on_route", "🧭 " + route.etiket())
        self._pick_models(provider)
        if is_browser_task(text) and self._browser_agent():  # tarayıcı işi bölünmeden tarayıcı ajanına (tek döngü)
            self._via_browser(messages, text, learning.original_request(text))
            return
        self._announce(text)
        if not self.should_plan(provider, text):
            self._direct(provider, messages, text)
            return
        if self.motor is not None:  # görev motoru: planı kaydeder, adım adım koşar, kapanınca kaldığı yerden sürer
            self.motor(messages, text)
            return
        self._emit("on_plan", None)  # "plan çıkarılıyor…"
        self.plan = self.make_plan(provider, messages, text)
        if len(self.plan) < 2:  # tek adımlık iş: plansız, bugünkü gibi
            self._emit("on_plan", [])
            self._direct(provider, messages, text)
            return
        worker = self.worker or self.chat
        for step in self.plan:  # docs/SEMALAR.md §2: adımın model kararı planda görünür; kartta yönetici · işçi
            step["secim"] = {"saglayici": worker[0], "model": worker[1],
                             "neden": "işçi: sohbet modeli" if worker == self.chat else "işçi: araç sınavını geçen model"}
            step["yonetici"] = self.boss_label or self.boss[1]
        user = {"role": "user", "content": text, "_plan": self.plan}
        messages.append(user)
        a.user_text = text
        self._emit("on_plan", self.plan)
        self._emit("on_route", f"🧭 Yönetici: {self.boss[1]} · İşçi: {worker[1]}"
                   + (f" — neden: {self.boss_choice.neden}" if self.boss_choice else ""))
        if self.boss_choice and self.boss_choice.uyari:
            self._emit("on_route", "⚠ " + self.boss_choice.uyari)
        parent = a.cb
        try:
            failed = 0
            for i, step in enumerate(self.plan):
                if a.security_stop:
                    self._set(i, "skipped", "güvenlik ajanı işi durdurdu")
                    continue
                if failed >= 2:
                    # ilk adımlar yapılamadıysa sonrakiler onların üstüne kurulu: boşa uğraşma, dürüstçe bitir (canlı
                    # kayıt: 1–2. adım başarısızken 3–5. adımlar 15 dk uydurma dosyalarla döndü, 2026-09-27)
                    self._set(i, "skipped", "önceki iki adım yapılamadığı için atlandı")
                    continue
                with self._hands():
                    self._run_step(provider, messages, text, i, step, parent)
                failed += step.get("status") == "failed"
            self._summary(provider, messages, text, parent)
        finally:
            a.cb = parent
            a.focus = ""

    def _browser_agent(self):
        a = self.agent
        if a.profile is not None:
            return None  # zaten bir uzman ajanla sohbet ediliyor
        return next((p for p in a.team if p.id == "tarayici"), None)

    def _via_browser(self, messages: list, text: str, task: str, add_user: bool = True) -> None:
        """İşi tarayıcı ajanına verir (kendi modeli, kendi araçları); araç kartları sohbette görünür, sonucu yazar."""
        a = self.agent
        last = next((m.get("content") for m in reversed(messages) if m.get("role") == "assistant"
                     and isinstance(m.get("content"), str) and m["content"].strip()), "")
        brief = task + (f"\n\nContext (previous answer in this chat):\n{last[:1500]}" if last else "")
        self._emit("on_route", "🌐 Bu iş gerçek tarayıcı gerektiriyor: **Tarayıcı ajanı** yapıyor (pencerede izleyebilirsin; "
                               "satın alma, gönderme, giriş ve indirme öncesi sana sorar).")
        if add_user:
            messages.append({"role": "user", "content": text})
            a.user_text = text
        parent = a.cb
        step = {"do": task, "done_when": "the requested information was really read from the web pages (real names, "
                                        "numbers, addresses — no placeholders like [Fiyat]) or the requested action was done"}
        body = ""
        try:
            for attempt in range(MAX_FIXES + 1):
                a.cb = rec = _Recorder(parent)  # tarayıcı ajanının araçları doğrulama için kaydedilir
                result = a._delegate({"agent": "tarayici", "task": brief})
                body = result.split("\n", 1)[1] if result.startswith("[") and "\n" in result else result
                rec.text = body
                ok, missing = (False, "the answer contains placeholders instead of real data") \
                    if _PLACEHOLDER.search(body) else self.check(self.chat[0] if self.chat else "ollama", step, rec)
                if ok:
                    break
                if attempt < MAX_FIXES:
                    self._emit("on_route", f"↻ Tarayıcı ajanının sonucu doğrulanamadı ({missing[:120]}); tekrar deniyor.")
                    brief = (f"{task}\n\nYour previous attempt was NOT accepted: {missing}\nDo it again in the browser: "
                             "find the real data on the pages (read them, use `find`, scroll, open results). If you cannot, "
                             "say plainly what blocked you (e.g. a CAPTCHA, login, a page that did not load) — never "
                             "invent data or use placeholders.")
                else:
                    self._learn_failure(text, {"do": task}, missing, rec)
                    body = ("⚠ **Tarayıcıda bu iş tamamlanamadı:** " + (missing or "sonuç doğrulanamadı") +
                            "\n\nAjanın son yazdığı (doğrulanmadı):\n\n" + re.sub(_PLACEHOLDER, "…", body)[:1500])
        finally:
            a.cb = parent
        parent.on_text(body)
        messages.append({"role": "assistant", "content": body})

    def _direct(self, provider: str, messages: list, text: str) -> None:
        """Plansız tur: tarayıcı işi → tarayıcı ajanı; iş isteğiyse ve sohbet modeli araç kullanamıyorsa işçi model;
        değilse sohbet modeli."""
        if is_browser_task(text) and self._browser_agent():
            self._via_browser(messages, text, learning.original_request(text))
            return
        if is_task_request(learning.original_request(text)):
            with self._hands():
                self.agent.run(provider, messages, text)
        else:
            self.agent.run(provider, messages, text)

    def _run_elsewhere(self, route: yonlendirici.Secim, messages: list, text: str) -> None:
        """Sohbetin sağlayıcısı kullanılamıyor (kapalı, anahtar reddedildi, tavan onaylanmadı): tur yönlendiricinin
        seçtiği yedek modelle temiz bir alt ajanda yapılır; yedek yoksa dürüstçe "çevrimdışı" denir.

        Sohbet geçmişi aktarılmaz (Ollama ve bulutun mesaj biçimleri karışmasın); son birkaç düz mesaj bağlam olur."""
        from .agent import settings_for

        a = self.agent
        messages.append({"role": "user", "content": text})
        a.user_text = text
        if not route.saglayici:
            note = ("⚠ **Şu an cevap verecek model yok.** " + route.neden[:1].upper() + route.neden[1:] + ".\n\n"
                    + ("Ollama çalışınca ya da internet gelince isteği tekrar gönder."
                       if route.bekleyen else "Modeller menüsünden bir model seç ya da bir bulut bağlantısı ekle."))
            self._emit("on_route", "🧭 " + route.etiket())
            a.cb.on_text(note)
            messages.append({"role": "assistant", "content": note})
            return
        self._emit("on_route", "🧭 " + route.etiket())
        history = [m for m in messages[:-1] if m.get("role") in ("user", "assistant")
                   and isinstance(m.get("content"), str) and m["content"].strip() and not m.get("_program")]
        context = "\n".join(f"{m['role']}: {m['content'][:500]}" for m in history[-6:])
        rec = _Recorder(a.cb)
        sub = Agent(settings_for(a.settings, route.saglayici, route.model), rec, a.profile, a.connections)
        sub.always_allowed, sub.auto_approve = a.always_allowed, a.auto_approve
        sub.gate_actions, sub.must_act = a.gate_actions, a.must_act
        sub.extra_system = a.extra_system
        sub.toolbox.read_roots = list(getattr(a.toolbox, "read_roots", []))
        try:
            sub.run(route.saglayici, [], (f"Earlier in this chat:\n{context}\n\n" if context else "")
                    + learning.original_request(text))
        finally:
            a.pending_actions += sub.pending_actions
        messages.append({"role": "assistant", "content": rec.text.strip()})

    def _run_step(self, provider: str, messages: list, text: str, i: int, step: dict, parent) -> None:
        a = self.agent
        total = len(self.plan)
        a.cb = rec = _Recorder(parent)
        self._set(i, "running")
        a.focus = step["do"]
        a.check_nudges, a.verified, a.gave_up = 0, False, False  # "bitti mi" denetimleri her adımda baştan
        done_list = "\n".join(f"{n}. {s['title']} — {STEP_ICONS[s['status']]}" for n, s in enumerate(self.plan, 1))
        if is_browser_task(step["do"]) and self._browser_agent():  # bu adım tarayıcı ajanında
            self._via_browser(messages, text, f"Step {i + 1}/{total} of a larger job ({learning.original_request(text)}):"
                                              f" {step['do']}\nIt is done when: {step['done_when']}", add_user=False)
        else:
            a.run(provider, messages, text, step=(
            f"Plan ({total} steps):\n{done_list}\n\nNow do ONLY step {i + 1}/{total}: {step['do']}\n"
            f"It is done when: {step['done_when'] or 'the result is really there'}.\n"
            "Use the tools to actually do it, then say in one or two sentences (in my language) what you did. "
            "Do not start the next step."))
        for attempt in range(MAX_FIXES + 1):
            self._set(i, "checking")
            ok, missing = self.check(provider, step, rec)
            if ok:
                self._set(i, "done", missing)
                return
            if attempt == MAX_FIXES or a.security_stop:
                if not a.security_stop and self._escalate(text, i, step, missing, parent):
                    return
                self._set(i, "failed", missing)
                self._learn_failure(text, step, missing, rec)
                return
            self._set(i, "fixing", missing)
            parent.on_text("\n\n")
            a.check_nudges, a.verified, a.gave_up = 0, False, False
            a.cb = rec = _Recorder(parent)
            a.run(provider, messages, text, step=(
                f"Step {i + 1}/{total} is NOT done yet. The check found: {missing or 'no proof in the tool results'}\n"
                f"Fix exactly that now with the tools: {step['do']}\nThen say briefly what you did."))

    def _escalate(self, text: str, i: int, step: dict, missing: str, parent) -> bool:
        """Adım düzeltmeye rağmen olmadı: daha güçlü bir model (roster.stronger) temiz bir alt ajanla dener.

        Sohbet geçmişi aktarılmaz (Ollama ve bulutun mesaj biçimleri karışmasın, güçlü model dolu bağlamla
        uğraşmasın): istek, adım ve neyin eksik kaldığı anlatılır; dosyalar zaten çalışma klasöründe."""
        from .agent import _SubRelay, settings_for

        a = self.agent
        current = (a._provider, a._model())  # _hands içinde: işçi model
        try:
            alt = roster.stronger(a.settings, current)  # yedekleme zincirinde bir üst basamak
        except Exception:
            alt = None
        if alt is not None and not self._budget_ok(alt.key):
            alt = None
        if alt is None:
            self._chain_end(i, step, missing, [current])
            if a.settings.model_policy != "guclu" and not self._hinted:
                self._hinted = True
                parent.on_text("\n\n*(Bu adım bu bilgisayardaki modellerle olmadı. Daha güçlü bir model bağlarsan "
                               "(Online menüsü; ücretsiz seçenekler de var) ve Ayarlar'da model politikasını "
                               "\"güçlü\" yaparsan böyle adımlar ona devredilir.)*")
            return False
        self._set(i, "fixing", f"{alt.model} deniyor")
        parent.on_text(f"\n\n*({current[1]} bu adımı bitiremedi; {alt.model} devralıyor.)*\n\n")
        rec = _Recorder(parent)
        sub = Agent(settings_for(a.settings, alt.provider, alt.model), _SubRelay(rec), a.profile, a.connections)
        sub.always_allowed, sub.auto_approve = a.always_allowed, a.auto_approve
        sub.gate_actions, sub.must_act = a.gate_actions, a.must_act
        sub.extra_system = ("Another assistant could not finish this step; you take over. Files it made may already "
                            "be in the workspace: look at them first, keep what is right, fix the rest.")
        try:
            sub.run(alt.provider, [], (
                f"The user's request: {learning.original_request(text)}\n\nYour step: {step['do']}\n"
                f"It is done when: {step['done_when'] or 'the result is really there'}\n"
                f"Why the previous attempt failed: {missing or 'no proof that it was done'}\n\n"
                "Do this step fully with the tools, then say in one or two sentences (in the user's language) what "
                "you did."))
        finally:
            a.pending_actions += sub.pending_actions
        rec.text = sub.cb.text  # alt ajanın sözleri: denetçi görsün
        parent.on_text(sub.cb.text.strip())
        ok, missing = self.check(a._provider, step, rec)
        self._set(i, "done" if ok else "failed", missing if not ok else f"{alt.model} bitirdi")
        if not ok:
            self._learn_failure(text, step, missing, rec)
            self._chain_end(i, step, missing, [current, alt.key])
        return True

    def _chain_end(self, i: int, step: dict, missing: str, tried: list) -> None:
        """Yedekleme zincirinin sonu: kayıt hata analizine devredilir (docs/SEMALAR.md §3, `model_yetersiz`)."""
        chain = yonlendirici.Zincir(tried, esik=1)
        for model in tried:
            chain.basarisiz(missing or "adım doğrulanamadı")
        try:
            yonlendirici.devret(chain.hata_kaydi(i + 1, f"{step.get('do', '')[:200]} — {missing or 'doğrulanamadı'}"))
        except Exception:
            pass  # kayıt yazılamasa da iş sürer

    def _learn_failure(self, text: str, step: dict, reason: str, rec: "_Recorder") -> None:
        """Başarısız adım hafızaya ders olarak girer: benzer iş planlanırken yönetici bu yolu bilir."""
        tools = sorted({e["name"] for e in rec.events})
        errors = [e["result"] for e in rec.events if e["error"]]
        if errors:
            last = next((ln.strip() for ln in reversed(errors[-1].splitlines()) if ln.strip()), "")
            reason = f"{reason} ({last[:150]})" if reason else last[:200]
        model = (self.worker or self.chat or ("", ""))[1]
        try:
            learning.record_failure(text, step["do"], reason, tools, model)
        except Exception:
            pass  # hafıza yazılamasa da iş sürer

    def _summary(self, provider: str, messages: list, text: str, parent) -> None:
        a = self.agent
        a.cb, a.focus = parent, ""
        a.check_nudges, a.verified, a.gave_up = 0, False, False
        lines = "\n".join(f"{n}. {s['title']} — {STEP_ICONS[s['status']]}" + (f" ({s['note']})" if s["note"] else "")
                          for n, s in enumerate(self.plan, 1))
        parent.on_text("\n\n")
        a.run(provider, messages, text, step=(
            f"All plan steps were attempted:\n{lines}\n\nNow give me the final answer in my language: what was done "
            "and the concrete results (files, numbers, findings). If a step failed (✗), say so plainly and how to "
            "get it done. "
            + ("If something I asked for is still missing and you can do it now, do it first. "
               if self.worker == self.chat else "Do not call tools now; just answer. ")
            + "Do not repeat the step-by-step messages."))


def plan_of(message: dict) -> list[dict] | None:
    """Kaydedilmiş bir kullanıcı mesajının planı (sohbet yeniden çizilirken)."""
    plan = message.get("_plan")
    return plan if isinstance(plan, list) and plan else None

