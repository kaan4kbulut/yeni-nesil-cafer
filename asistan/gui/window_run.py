"""Ana pencere: mesaj gönderme, ajanın çalışması (işçi olayları, onaylar) ve bağlam ölçümü."""

import re
import threading
from dataclasses import replace
from pathlib import Path

from PySide6.QtCore import QTimer

from .. import ctxprobe, learning, power, roster, suggest
from ..agent import Agent, describe_error, describe_pending, is_advice_request, is_install_request, is_task_request
from ..work import chat_folder, guess_category

from .chat import format_stats, summarize_args, tool_label
from .dialogs import ApprovalDialog
from .sidebar import run_in_background
from .theme import C
from .worker import AgentWorker


CTX_CAP = 32768  # otomatik bağlamın üst sınırı (token)

# sansürsüz mod: kullanıcı filtresiz yerel modeli kendisi seçti; bilgisayardaki işlemlerin kuralları değişmez
WORK_DIR_NOTE = (
    "\n\n## This conversation's folder\nThe workspace `{work}` belongs only to this conversation; everything you "
    "create goes there. Other tasks live in sibling folders under `{root}`: never list, read or change them unless "
    "the user explicitly asks about them. Words like \"files\", \"steps\" or \"models\" in a request refer to "
    "the user's request itself (for example the app's own UI), not to whatever files happen to exist.")

UNCENSORED_NOTE = (
    "\n\n## Unfiltered mode\nThe user switched on unfiltered mode and chose an uncensored local model. Answer "
    "directly, frankly and completely: no moralizing, lectures, unnecessary disclaimers or refusals of ordinary "
    "requests. The app's rules for actions on the computer (approval of commands, file changes, installs) stay "
    "exactly the same.")


class RunMixin:
    """MainWindow'un parçası (window.py); konusu modülün açıklamasında."""

    # ---- gönderme / çalıştırma
    def _set_running(self, running: bool):
        self.send_btn.setVisible(not running)
        self.enter_hint.setVisible(not running)
        self.stop_btn.setVisible(running)
        self._set_mode("ÇALIŞIYOR" if running else "HAZIR")
        self.run_label.setVisible(True)
        self.input.setPlaceholderText("Devam et ya da yeni bir görev ver" if running or self.conv.messages
                                      else "Asistana bir şey sor ya da bir görev ver")
        for w in (self.model_pill, self.workspace_btn, self.api_panel, self.agent_panel):
            w.setEnabled(not running)

    def _submit(self):
        """Enter: iş sürerken durdurmaz; yazılan mesaj sıraya girer, iş bitince kendiliğinden gönderilir.
        Durdurmak yalnızca ■ durdur düğmesi ya da Esc ile."""
        if not self.worker:
            self._send_or_stop()
        elif self.input.toPlainText().strip() and not self.queued_send:
            self.queued_send = True
            self.chat.add_notice("⏳ Mesajın sırada: bu iş bitince gönderilecek (kutuda düzenleyebilirsin).", C["muted"])

    def _send_or_stop(self):
        if self.worker:
            self.worker.cancel()
            self._set_mode("DURDURULUYOR")
            return
        text = self.input.toPlainText().strip()
        if not text and not self.attachments:
            return
        self.continued_project = None
        if not self.conv.messages and not self.conv.work_dir:
            # "3D projeme devam et": hafızadaki projenin klasöründe sürer; yoksa yeni sohbet kendi iş klasöründe
            # çalışır: <çalışma klasörü>/<kategori>/<başlık>; kategori kenar çubuğundaki klasör, o "Genel" ise
            # isteğin konusu (3D Modeller, Kod, Belgeler…)
            project = learning.find_project(text) if text else None
            first = (text or "ekler").splitlines()[0][:60]
            if project:
                self.conv.work_dir = project["folder"]
                self.continued_project = project
            else:
                folder = self.conv.folder or self.current_folder
                category = folder if folder and folder != "Genel" else guess_category(text)
                self.conv.work_dir = chat_folder(self.settings.workspace, category, first, self.conv.id)
                Path(self.conv.work_dir).mkdir(parents=True, exist_ok=True)
                work_dir = self.conv.work_dir
                threading.Thread(target=learning.save_project, args=(work_dir, first, text), daemon=True).start()
            self._update_workspace_label()
        text = (text or "Ekteki dosyalara bak.") + self._take_attachments()
        self.input.clear()
        free = self.settings.extra.get("uncensored") and self.settings.extra.get("uncensored_model")
        if free:
            self.route = None  # otomatik seçim sansürsüz modu bozmasın
        else:
            self._auto_route()
        if not self.conv.messages:
            self.chat.clear()
            self.conv.folder = self.conv.folder or self.current_folder
            self.conv.provider = self.provider  # Claude Code'a gitse de geçmiş düz metin: sohbetin sağlayıcısı kalır
            self.conv.title = text.splitlines()[0][:60]
            if self.conv not in self.conversations:
                self.conversations.insert(0, self.conv)
            self._update_header()
        self.chat.add_user(text)
        if self.continued_project:
            self.chat.add_notice(f"📁 Kayıtlı projede devam ediliyor: «{self.continued_project.get('title', '')}» — "
                                 + self.conv.work_dir.replace(str(Path.home()), "~"), C["muted"])
        run_provider = self.route[0] if self.route else self.provider
        model = "claude code" if self.route else self.model_box.currentText()
        agent_settings = self.settings
        if free:
            run_provider, model = "ollama", free
            agent_settings = self._run_settings()
            if not self.conv.messages or self.conv.provider != "ollama":
                self.conv.provider = "ollama"
        if free and is_task_request(text) and roster.worker_for(self.settings, ("ollama", free)) is None:
            self.chat.add_notice(f"⚠ {free} araç kullanamıyor: dosyaları okuyamaz, yazamaz, komut çalıştıramaz. Bu işle "
                                 "ilgili söyledikleri uydurma olabilir; araç destekli bir sansürsüz model seç.",
                                 C["error"])
        self.chat.start_turn(f"🔓 {model}" if free else model)
        self.chat.show_waiting()

        work = self._work_dir()
        if work != self.settings.workspace:
            agent_settings = replace(agent_settings, workspace=work)
        agent = Agent(agent_settings, None, self.profile, self.connections, team_tool=self.profile is None,
                      team=self.profiles)
        if work != self.settings.workspace:
            # diğer işler salt okunur kalır: kullanıcı açıkça isterse eski bir işe bakılabilir
            root = Path(self.settings.workspace).expanduser().resolve()
            agent.toolbox.read_roots.append(root)
            agent.extra_system = (agent.extra_system or "") + WORK_DIR_NOTE.format(
                work=agent.toolbox.root, root=root)
            if self.continued_project:
                agent.extra_system += learning.project_note(self.continued_project)
        if free:
            agent.extra_system = (agent.extra_system or "") + UNCENSORED_NOTE
        agent.always_allowed = self.always_allowed
        if self.settings.approval_mode == "guvenlik":
            # güvenlik ajanı kipi: onay sorulmaz; asistan işe hemen başlar, her adımı güvenlik ajanı denetler
            agent.gate_actions = False
        elif free:
            # sansürsüz modda güvenlik ajanı çalışamıyor, ama "önce plan, sonra ▶" de yok: model plan yazıp
            # duruyordu. İşe hemen başlar; komut ve kurulum gibi riskli adımlar yine tek tek kullanıcıya sorulur.
            agent.gate_actions = False
            agent.must_act = text.startswith("▶ ")
        else:
            # varsayılan: hiçbir işlem kendiliğinden yapılmaz; değişiklikler bekler, yanıtın kenarına ✓ gelir
            agent.gate_actions = not text.startswith("▶ ")
            agent.must_act = text.startswith("▶ ")  # "uygula" düğmesi: yazıp geçmesin, gerçekten yapsın
        if self.settings.approval_mode == "guvenlik" and is_advice_request(text):  # yalnızca öneri istendi: hiçbir şey yapılmasın (kullanıcı isterse söyler)
            agent.extra_system = (agent.extra_system or "") + (
                "\n\n## The user only asked for suggestions\nGive the suggestions; do NOT run commands, code or change "
                "anything now. Read-only checks (reading files, searching, read-only commands) are fine. If they want "
                "one applied, they will ask.")
        agent.cli_model = self.route[1] if self.route else ""  # Claude Code: opus, sonnet…
        # beceri kütüphanesi: benzer bir iş daha önce başarıyla yapıldıysa yöntemini asistana ver
        self.used_skills = learning.find_skills(learning.original_request(text)) if not text.startswith("📈") else []
        if self.used_skills:
            agent.extra_system = (agent.extra_system or "") + learning.skills_prompt(self.used_skills)
            self.chat.add_notice("🧩 Daha önce işe yarayan yöntem kullanılıyor: "
                                 + " · ".join(f"«{x['title'][:60]}»" for x in self.used_skills), C["muted"])
        self.last_run_model = model if model != "otomatik" else self.model_box.currentText()
        self.run_failed = False
        self.worker = w = AgentWorker(agent, run_provider, self.conv.messages, text)
        w.text.connect(self.chat.append_text)
        w.text.connect(self.right.activity.text_started)
        w.thinking.connect(self.right.activity.append_thinking)  # düşünce sohbette değil, sağdaki adımlarda
        w.model_started.connect(self.right.activity.model_start)
        w.model_ended.connect(self._model_ended)
        w.tool_start.connect(self._tool_started)
        w.tool_end.connect(self._tool_ended)
        w.media.connect(self._media_event)
        w.approval_needed.connect(self._ask_approval)
        w.security_note.connect(lambda text, decision, why: self.chat.add_notice(text, C["muted"])
                                if decision == "approve" else
                                self.chat.add_security_block(text, decision, why, lambda: self._toggle_guard(False)))
        w.team_task.connect(lambda title, goal: self._create_task(title, goal, self.provider,
                                                                  self.model_box.currentText(), show=False))
        w.plan.connect(self.chat.show_plan)
        w.route_note.connect(lambda text: self.chat.add_notice(text, C["muted"]))
        w.plan_step.connect(self.chat.update_step)
        w.plan_step.connect(lambda i, status, note: self.right.activity.state.setText(
            f"Adım {i + 1}: " + {"running": "yapılıyor", "checking": "doğrulanıyor", "fixing": "düzeltiliyor",
                                 "done": "bitti", "failed": "başarısız"}.get(status, status)))
        w.failed.connect(self._failed)
        w.stopped.connect(lambda: self.chat.add_notice("⏹ Durduruldu.", C["muted"]))
        w.finished.connect(self._finished)
        self._set_running(True)
        self.right.activity.begin_run(model)
        self.run_clock.start()
        w.start()

    def _model_ended(self, stats: dict):
        self.right.activity.model_end(stats)
        self.last_context = stats.get("input_tokens", 0) + stats.get("output_tokens", 0)
        self._update_context_label()

    def _tool_started(self, call_id: str, name: str, args: dict):
        self.tool_args[call_id] = (name, args)
        self.chat.start_tool(call_id, name, args)
        self.right.activity.tool_start(call_id, name, summarize_args(name, args))

    def _tool_ended(self, call_id: str, result: str, is_error: bool):
        self.chat.end_tool(call_id, result, is_error)
        self.right.activity.tool_end(call_id, is_error)
        name, args = self.tool_args.pop(call_id, ("?", {}))
        self.right.log.add(f"{'✗' if is_error else '✓'} {tool_label(name)}  {summarize_args(name, args)}", result)
        if name in ("write_file", "edit_file") and not is_error:
            path = Path(self._work_dir(), args.get("path", "")).resolve()
            self.right.files.show_file(str(path))
            self.right.activity.add_file(str(path), name == "edit_file")

    def _media_event(self, path: str, pct: int, text: str):
        """Resim üretimi ilerliyor: sağ panel açılır, her adım canlı görüntü bölümünde görünür."""
        if pct >= 0 and not self.right.media.live_active:
            self._show_tab(self.right.media)
        self.right.media.live(path, pct, text)

    def _ask_approval(self, name: str, args: dict):
        self.right.activity.waiting_approval(name)
        dlg = ApprovalDialog(name, args, self._work_dir(), self.worker.turn_text, self)
        dlg.exec()
        if dlg.choice == "always":
            self.always_allowed = True
            self.worker.agent.always_allowed = True
        self.worker.answer_approval(dlg.choice in ("allow", "always"))
        if dlg.choice != "deny":
            self.right.activity.state.setText("Çalışıyor")

    def _failed(self, msg: str):
        self.run_failed = True  # hata mesajı gösterildi: "model yetersiz" açıklaması eklenmesin
        learning.log_issue("hata", self.chat.last_request, getattr(self, "last_run_model", ""), msg)
        self.chat.add_notice(f"⚠ {msg}", C["error"])
        self._offer_report("hata", msg)
        self.right.log.add(f"⚠ Hata: {msg}")

    def _finished(self):
        w = self.worker
        secs = self.run_clock.elapsed() / 1000
        summary = format_stats(secs, w.stats)
        bubble = self.chat.last_bubble
        if w.agent.pending_actions and bubble is not None and not bubble.text().strip():
            self.chat.append_text(describe_pending(w.agent.pending_actions))  # model planı yazmadan durdu
            self.chat.flush()
        elif w.agent.pending_actions and bubble is not None:
            # model bazen "kaydettim" der: yanılmasın (kullanıcı da, sonraki turda model de) — bu yalnızca bir plan
            note = ("\n\n⏸ *Henüz hiçbir şey yapılmadı: yukarıdakiler yalnızca plan. ▶ uygula'ya basınca "
                    "yapılacak.*")
            self.chat.append_text(note)
            self.chat.flush()
            last = next((m for m in reversed(self.conv.messages) if m.get("role") == "assistant"
                         and isinstance(m.get("content"), str)), None)
            if last is not None:  # model de sonraki turda "zaten yaptım" sanmasın
                last["content"] = (last["content"] or "") + note
        elif bubble is not None and not bubble.text().strip() and not w.is_cancelled() \
                and not getattr(self, "run_failed", False):
            # model uğraşıp hiçbir şey yazmadan bitirdi: kullanıcı sessiz kalmasın, ne yapabileceğini bilsin
            learning.log_issue("bos_cevap", self.chat.last_request, getattr(self, "last_run_model", ""),
                               ", ".join(n for n, _ in w.agent.done_steps) or "hiçbir işlem başarılı olmadı")
            self.chat.append_text(
                "Bu isteği tamamlayamadım: kullandığım model bu iş için yetersiz kaldı (yukarıdaki adımlarda ne "
                "denediğimi görebilirsin).\n\n**Ne yapabilirsin:**\n- İsteği daha küçük parçalara bölerek tekrar dene.\n"
                "- Yardım → **Model önerileri**'nden bilgisayarına uygun daha güçlü bir model indir.\n"
                "- Ya da ücretsiz bir bulut modeline bağlan (Online → Ücretsiz).")
            self.chat.flush()
            self._offer_report("bos_cevap", ", ".join(n for n, _ in w.agent.done_steps) or "hiçbir işlem başarılı olmadı")
        self._learn_from_run(w)
        if self.cloud_job is not None:
            self._cloud_job_finished(w)
        self.chat.end_turn(summary)
        request = self.chat.last_request or ""
        if (self.settings.approval_mode != "guvenlik" and not w.is_cancelled() and not request.startswith("📈")
                and not w.agent.no_tools):  # araçsız model: düğmeye basınca yapılabilecek bir şey yok
            nothing_to_do = w.agent.found_installed and is_install_request(request)  # "zaten kurulu"
            reply = bubble.text() if bubble is not None else ""
            # eylem kelimesi geçse de ("tarihini yaz") yalnızca soru cevaplandıysa düğme gelmez; asistan bir plan
            # yazdıysa (komut/kod bloğu ya da numaralı adımlar) ya da bekleyen işlem varsa gelir
            planned = "```" in reply or re.search(r"(?m)^\s*(1[.)]|adım 1)", reply, re.I) is not None
            if w.agent.pending_actions or (not nothing_to_do and (
                    is_advice_request(request) or (is_task_request(request) and planned and w.agent.gate_actions))):
                self.chat.offer_apply()  # ✓ ile başlatılır, sonra her adım için onay sorulur
        state = "Durduruldu" if w.is_cancelled() else "Tamamlandı"
        self.right.activity.end_run(state, summary)
        self.conv.save()
        # "finished" sinyali iş parçacığı tamamen kapanmadan gelebilir; son referans o an bırakılırsa Qt
        # programı durdurur ("QThread: Destroyed while thread is still running") — kapanmasını bekle
        w.wait()
        w.deleteLater()
        self.worker = None
        self._set_running(False)
        self.run_label.setText(f"{'durduruldu' if w.is_cancelled() else 'son yanıt'} {secs:.0f} sn")
        self.conversations.sort(key=lambda c: c.updated, reverse=True)
        self._refresh_sidebar()
        self._refresh_models_status()
        self.input.setFocus()
        QTimer.singleShot(500, self._check_context)
        self.suggest_timer.start()  # öneriler ancak kullanıcı bir süre yazmazsa: yeni komut beklemesin
        if self.queued_send:  # iş sürerken Enter'la sıraya alınan mesaj (durdurulduysa kutuda bekler)
            self.queued_send = False
            if not w.is_cancelled() and self.input.toPlainText().strip():
                QTimer.singleShot(0, self._send_or_stop)

    def _refresh_suggestions(self):
        """Kullanıcı bir dakika boş kalınca, son isteklere göre kişisel önerileri arka planda yerel modelle yeniler."""
        if power.saving(self.settings):
            return  # pilde arka planda model çalıştırma: pili yer, sohbet modelini bekletir
        if self.worker or self.input.toPlainText().strip() or (self.task_worker and self.task_worker.isRunning()):
            return
        if self.provider != "ollama" or not suggest.stale(self.conversations):
            return
        convs = [c for c in self.conversations if c.messages][:8]
        run_in_background(lambda: suggest.generate(self.settings, convs), lambda _res, _err: None, self)

    # ---- bağlam ölçümü
    def _check_context(self):
        """Seçili Ollama modeli için ekran kartına sığan en büyük bağlamı bulur ve uygular."""
        if not self.settings.auto_ctx or self.probing:
            return
        model = self.settings.ollama_model
        if self.worker or (self.task_worker and self.task_worker.isRunning()):
            return  # çalışan bir iş bitince yeniden denenir
        vram = ctxprobe.gpu_total_mib()
        key = ctxprobe.probe_key(model, vram)
        if key in self.settings.ctx_probe:
            self._apply_context(self.settings.ctx_probe[key], measured=False)
            return
        self.probing = True
        self.ctx_label.setText("bağlam ölçülüyor…")
        self.ctx_label.show()
        url = self.settings.ollama_url

        def progress(text):
            QTimer.singleShot(0, self, lambda: self.ctx_label.setText(f"bağlam ölçülüyor: {text}"))

        def done(result, error):
            self.probing = False
            if error:
                self.ctx_label.hide()
                self._notify(f"bağlam ölçülemedi: {describe_error(error)}")
                return
            self.settings.ctx_probe[key] = result
            self._apply_context(result, measured=True)

        run_in_background(lambda: ctxprobe.probe(url, model, progress), done, self)

    def _apply_context(self, result: dict, measured: bool):
        # en fazla 32K: daha büyüğü uzun sohbetlerde her adımı yavaşlatıyor ve ekran kartında uzman modellere
        # (görme, kod) yer bırakmıyordu; model geçişlerinde yeniden yükleme gerekiyordu
        old, new = self.settings.ollama_num_ctx, min(result["ctx"], CTX_CAP)
        self.settings.ollama_num_ctx = new
        self.settings.save()
        self._update_context_label()
        self.ctx_label.hide()
        self.context_label.setToolTip(
            f"Model sınırı {result.get('max', 0) // 1024}K. Ekran kartına sığan en büyük bağlam otomatik seçildi.\n"
            "Ayarlar'dan kapatılabilir ya da yeniden ölçülebilir.")
        if measured and new != old:
            self._notify(f"sistem kontrol edildi: bağlam {old // 1024}K → {new // 1024}K", 10000)
