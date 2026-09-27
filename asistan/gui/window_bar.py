"""Ana pencere: ekler, üst çubuk, sağlayıcı / model seçicisi, çalışma klasörü ve güvenlik düğmesi."""

from pathlib import Path

from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import QFileDialog, QPushButton

from .. import cli_agents, power, roster, specialists
from ..agent import list_ollama_models
from ..cekirdek import modeller
from ..config import CLAUDE_MODELS

from .icons import icon
from .theme import C


class BarMixin:
    """MainWindow'un parçası (window.py); konusu modülün açıklamasında."""

    def _attach_files(self):
        paths, _ = QFileDialog.getOpenFileNames(self, "Dosya ekle")
        self._add_attachments(paths)

    def _add_attachments(self, paths: list):
        for p in paths:
            if Path(p).is_file() and p not in self.attachments:
                self.attachments.append(p)
        self._render_attachments()
        self.input.setFocus()

    def _render_attachments(self):
        while self.attach_row.count() > 1:  # sondaki boşluk kalır
            w = self.attach_row.takeAt(0).widget()
            if w:
                w.hide()
                w.deleteLater()
        for p in self.attachments:
            chip = QPushButton(f"{Path(p).name}  ✕", objectName="smallButton")
            chip.setToolTip(f"{p}\nKaldırmak için tıkla")
            chip.setCursor(Qt.PointingHandCursor)
            chip.clicked.connect(lambda _=False, p=p: (self.attachments.remove(p), self._render_attachments()))
            self.attach_row.insertWidget(self.attach_row.count() - 1, chip)

    def _take_attachments(self) -> str:
        """Ekleri çalışma klasörüne kopyalar; mesaja eklenecek notu döndürür."""
        if not self.attachments:
            return ""
        import shutil

        target = Path(self._work_dir(), "ekler")
        target.mkdir(parents=True, exist_ok=True)
        names = []
        for p in self.attachments:
            dest = target / Path(p).name
            if Path(p).resolve() != dest.resolve():
                shutil.copy2(p, dest)
            names.append(f"ekler/{dest.name}")
        self.attachments.clear()
        self._render_attachments()
        return ("\n\n[Ekler: " + ", ".join(names) + "]\n"
                "(Resimleri görmek için look_at_image, metin dosyalarını okumak için read_file kullan.)")

    def _show_tab(self, tab):
        """Sağ paneli açıp bölümü gösterir (bölümün kendisiyle: yeni sekme eklenince sıralar kaymasın)."""
        self.toggle_right.setChecked(True)
        self.right.show_part(tab)

    # ---- dikte: konuşarak yaz (asistan/dictation.py)
    def _toggle_dictation(self):
        from .dikte_kaydi import Dictation

        if self.dictation is None:
            self.dictation = Dictation(lambda: self.settings, self._installed_models, self)
            self.dictation.level.connect(self._dictation_level)
            self.dictation.busy.connect(self._dictation_busy)
            self.dictation.text_ready.connect(self._dictation_text)
            self.dictation.failed.connect(lambda msg: self.chat.add_notice(f"🎤 {msg}", C["muted"]))
        if self.dictation.recording:
            self.dictation.stop()
        elif not self.dictation.working:
            self.dictation.start()

    def _installed_models(self) -> list[str]:
        try:
            return list_ollama_models(self.settings.ollama_url)
        except Exception:
            return []

    def _escape(self):
        """Esc: önce dikte kaydını iptal eder, kayıt yoksa çalışan işi durdurur."""
        if self.dictation is not None and self.dictation.recording:
            self.dictation.cancel()
        elif self.worker:
            self._send_or_stop()

    def _dictation_level(self, level: float, seconds: float):
        bars = "▮" * max(1, round(level * 8))
        self.enter_hint.setText(f"● kayıt {int(seconds) // 60}:{int(seconds) % 60:02d}  {bars:<8}  tekrar bas: bitir · Esc: iptal")

    def _dictation_busy(self, state: str):
        on = state == "kayıt"
        self.mic_btn.setIcon(icon("mic", C["accent"] if state else C["muted"], 16))
        self.mic_btn.setStyleSheet(f"background: {C['select']};" if on else "")
        self.mic_btn.setEnabled(state in ("", "kayıt"))
        texts = {"kayıt": "● kayıt 0:00", "çeviriliyor": "yazıya çevriliyor…", "temizleniyor": "düzenleniyor…"}
        self.enter_hint.setText(texts.get(state, "Shift+Enter yeni satır"))

    def _dictation_text(self, text: str):
        cursor = self.input.textCursor()
        before = self.input.toPlainText()[:cursor.position()]
        cursor.insertText((" " if before and not before[-1].isspace() else "") + text)
        self.input.setFocus()

    def _work_dir(self) -> str:
        """Bu sohbetin iş klasörü; eski sohbetlerde (iş klasörü yok) çalışma klasörünün kendisi."""
        return (self.conv.work_dir if self.conv and self.conv.work_dir else "") or self.settings.workspace

    def _update_workspace_label(self):
        work = self._work_dir()
        self.workspace_btn.setText(work.replace(str(Path.home()), "~") + "  ⌄")
        self.chat.root = work
        if hasattr(self, "right"):
            self.right.set_root(work if Path(work).is_dir() else self.settings.workspace)

    def _update_context_label(self):
        used = f"{self.last_context / 1000:.1f}K" if self.last_context else "0"
        if self.provider == "ollama":
            report = getattr(getattr(self, "right", None), "models", None) and self.right.models.gpu_report
            where = "" if report is None else f" · {'' if report.ok or report.card.startswith('⚠') else '⚠ '}" \
                                              f"{report.card or report.text}"
            self.context_label.setToolTip("" if report is None or report.ok else f"{report.text}\n{report.fix}")
            self.context_label.setText(f"bağlam {used} / {power.num_ctx(self.settings) // 1024}K{where}")
        else:
            self.context_label.setText(f"bağlam {used}")

    @property
    def profile(self):
        agent_id = self.conv.agent_id if self.conv else ""
        return next((p for p in self.profiles if p.id == agent_id), None) if agent_id else None

    def _connection(self, provider: str):
        if not provider.startswith("api:"):
            return None
        return next((c for c in self.connections if c.id == provider[4:]), None)

    def _provider_choices(self) -> list[tuple[str, str]]:
        choices = [("💻  Ollama", "ollama"), ("☁  Claude", "claude")]
        choices += [(f"🧠  {c.name}", f"api:{c.id}") for c in self.connections if c.kind == "llm"]
        return choices

    @staticmethod
    def _provider_icon(provider: str) -> str:
        return {"ollama": "💻", "claude": "☁"}.get(provider, "🧠")

    def _fill_providers(self):
        self.provider_box.blockSignals(True)
        self.provider_box.clear()
        for label, data in self._provider_choices():
            self.provider_box.addItem(label, data)
        self.provider_box.setCurrentIndex(max(self.provider_box.findData(self.settings.provider), 0))
        self.provider_box.blockSignals(False)

    def _models_for(self, provider: str) -> list[str]:
        if provider == "claude":
            return list(CLAUDE_MODELS)
        if provider == "ollama":
            try:
                return list_ollama_models(self.settings.ollama_url) or [self.settings.ollama_model]
            except Exception:
                return [self.settings.ollama_model]
        conn = self._connection(provider)
        return list(conn.models) if conn else []

    def _current_model_setting(self, provider: str) -> str:
        if provider == "claude":
            return self.settings.claude_model
        if provider == "ollama":
            return self.settings.ollama_model
        return self.settings.api_models.get(provider[4:], "")

    def _set_provider_model(self, provider: str, model: str = ""):
        """Sağlayıcıyı (ve verilirse modeli) sinyal zinciri tetiklemeden seçer."""
        index = self.provider_box.findData(provider)
        if index < 0:
            return False
        self.provider_box.blockSignals(True)
        self.provider_box.setCurrentIndex(index)
        self.provider_box.blockSignals(False)
        self.settings.provider = provider
        if model:
            if provider == "claude":
                self.settings.claude_model = model
            elif provider == "ollama":
                self.settings.ollama_model = model
            else:
                self.settings.api_models[provider[4:]] = model
        self._reload_models()
        return True

    def _chat_only(self) -> bool:
        """Seçili Ollama modeli araç kullanamıyor mu (ör. gemma3)? Sonuç önbellekte tutulur."""
        if self.provider != "ollama" or not self.settings.ollama_model:
            return False
        caps = specialists._capabilities(self.settings.ollama_url, self.settings.ollama_model)
        return bool(caps) and "tools" not in caps

    def _update_header(self):
        self.title.setText(self.conv.title if self.conv else "Yeni sohbet")
        model = self.model_box.currentText()
        self.provider_chip.setText(model)
        conn = self._connection(self.provider)
        source = conn.name.lower() if conn else self.provider
        chat_only = "  · sadece sohbet" if self._chat_only() else ""
        free = self._free_model()
        if free:  # sansürsüz mod: çalışan model bu; normal model göstergesi yanıltmasın
            tools = "tools" in specialists._capabilities(self.settings.ollama_url, free)
            self.model_pill.setText(f"🔓 sansürsüz · {free.split('/')[-1]}{'' if tools else '  · sadece sohbet'}  ⌄")
        elif getattr(self, "route", None):
            auto = "" if self.settings.active_kind else "otomatik · "
            self.model_pill.setText(f"{auto}{cli_agents.label(*self.route).lower()}  ⌄")
        elif self.settings.auto_model and self.settings.active_kind:  # üstten seçilen: firma · model
            self.model_pill.setText(f"{self._company(self.provider)} · {model or '—'}{chat_only}  ⌄")
        elif self.settings.auto_model:  # yerel modelde sağlayıcı adı gereksiz; etiket kısa kalsın
            where = "" if self.provider == "ollama" else f"{source} · "
            self.model_pill.setText(f"otomatik · {where}{model or '—'}{chat_only}  ⌄")
        else:
            self.model_pill.setText(f"{source} · {model or 'model seç'}{chat_only}  ⌄")
        self._update_kind_tabs(model)
        if hasattr(self, "free_btn"):
            self._update_free_btn()  # alttaki değişince üstteki 🔓 de aynı modeli göstersin
        profile = self.profile
        self.agent_chip.setVisible(profile is not None)
        if profile:
            self.agent_chip.setText(profile.name)

    def _tab_model(self, kind: str) -> str:
        """Sönük üst düğmede görünen: o menüye geçilirse kullanılacak model (seçilen varsayılan ya da otomatik seçim)."""
        from .. import model_updates

        s = self.settings
        free = self._free_model()
        if kind == "offline" and free:
            return f"🔓 {free.split('/')[-1]}"
        chosen = roster.default(s, kind)  # anahtarsız bağlantı ya da hafif modda büyük model: geçersiz, otomatiğe düşer
        if chosen is not None:
            return chosen.model.split("/")[-1]
        pool = [c for c in roster.candidates(s) if c.local == (kind == "offline") and "tools" in c.caps
                and not model_updates.is_uncensored(c.model)]
        if pool:
            best = max(pool, key=lambda c: c.score).model.split("/")[-1]
            return f"otomatik · {best}"
        agents = cli_agents.available_agents() if kind == "online" else []
        if agents:
            return agents[0].title.lower()
        return "bağlı değil" if kind == "online" else "model yok"

    def _update_kind_tabs(self, model: str):
        """Üstteki Online · Offline: ikisi de her zaman kendi modelini gösterir; alttaki modelin kategorisi yanar
        (otomatikte "otomatik · model"). Sansürsüz modelde ikisi de sönük, yalnızca 🔓 sansürsüz düğmesi yanar."""
        tabs = getattr(self, "kind_tabs", None)
        if not tabs:
            return
        s = self.settings
        provider = self.route[0] if getattr(self, "route", None) else self.provider
        if s.extra.get("uncensored"):  # sansürsüzde yalnızca 🔓 düğmesi yanar
            active = ""
        elif s.active_kind == "online":
            active = "online"
        elif s.active_kind == "offline":
            active = "offline"
        else:  # otomatik ya da kod: şu an kullanılan modelin çalıştığı yer
            active = "offline" if provider == "ollama" else "online"
        route = getattr(self, "route", None)
        if route:  # alttaki gibi: "claude code · fable"
            shown = cli_agents.label(*route).lower()
        else:
            shown = (model or "").split("/")[-1]
        if not s.active_kind and not getattr(self, "route", None):
            shown = f"otomatik · {shown}" if shown else "otomatik"
        if len(shown) > 30:
            shown = shown[:29] + "…"
        for kind, btn in tabs.items():
            title = "Online" if kind == "online" else "Offline"
            on = kind == active
            label = shown if on and shown else self._tab_model(kind)
            if len(label) > 30:
                label = label[:29] + "…"
            btn.setText(f"{title} · {label}  ⌄")
            btn.setProperty("inactive", not on)
            btn.style().unpolish(btn)
            btn.style().polish(btn)
        if hasattr(self, "_center_model_tabs"):
            self._center_model_tabs()

    def _reload_models(self):
        self.model_box.blockSignals(True)
        self.model_box.clear()
        models = self._models_for(self.provider)
        self.model_box.addItems(models)
        current = self._current_model_setting(self.provider)
        if current and self.model_box.findText(current) >= 0:
            self.model_box.setCurrentText(current)
        self.model_box.blockSignals(False)
        self._model_changed(self.model_box.currentText())

    def _model_changed(self, name: str):
        if name:
            if self.provider == "claude":
                self.settings.claude_model = name
            elif self.provider == "ollama":
                changed = name != self.settings.ollama_model
                if changed:
                    QTimer.singleShot(300, self._check_context)  # yeni modelin bağlamını ölç
                self.settings.ollama_model = name
                if changed and self._chat_only():
                    self._notify(f"{name} araç kullanamıyor: sohbet eder, ama web'de arama, dosya ve komut "
                                 f"işlerini yapamaz. Bunlar için {modeller.deger('arac_ustasi')} seç.", 12000)
            else:
                self.settings.api_models[self.provider[4:]] = name
            self.settings.save()
            if self.side_stack.currentIndex() == 2:  # ajan kartları "sohbetteki model"i gösteriyor
                self.agent_panel.refresh()
        self._update_header()
        self._update_context_label()

    def _connections_changed(self):
        if self.worker:
            return
        self._fill_providers()
        if self.provider != self.settings.provider:  # seçili bağlantı silindi
            self._provider_changed()
        else:
            self._reload_models()
        self._refresh_models_status()

    def _choose_ollama_model(self, name: str):
        if self.provider != "ollama":
            self.provider_box.setCurrentIndex(self.provider_box.findData("ollama"))
        self.model_box.setCurrentText(name)
        self.right.models.refresh()

    def _provider_changed(self):
        self.settings.provider = self.provider
        self.settings.save()
        self._reload_models()
        # Mesaj biçimleri farklı olduğu için sağlayıcı değişince yeni sohbet açılır
        if self.conv and self.conv.messages and self.conv.provider != self.provider:
            # ajan kendi modeline bağlı değilse yeni sohbette de aynı ajanla devam et
            profile = self.profile
            self.new_conversation(profile.id if profile and not profile.provider else "")
        self._refresh_models_status()

    def _pick_workspace(self):
        path = QFileDialog.getExistingDirectory(self, "Çalışma klasörünü seç", self.settings.workspace)
        if path:
            self.settings.workspace = path
            self.settings.save()
            self._update_workspace_label()
            self.right.set_root(path)

    @staticmethod
    def _switch_style(btn, on: bool, color: str):
        """Açılıp kapanan anahtar: açıkken dolu renk, kapalıyken soluk çerçeve (bir bakışta durumu belli olsun)."""
        btn.setStyleSheet(
            f"QToolButton {{ background: {color}; color: {C['on_accent']}; border: 1px solid {color}; }}" if on else
            f"QToolButton {{ background: transparent; color: {C['text2']}; border: 1px solid {C['border']}; }}")

    def _update_guard_btn(self):
        on = self.settings.approval_mode == "guvenlik"
        self._switch_style(self.guard_btn, on, C["success"])
        self.guard_btn.setText("🛡 güvenlik: açık" if on else "🛡 güvenlik: kapalı")
        self._center_model_tabs()  # dar pencerede kısa yazı
        self.guard_btn.setToolTip(
            "Açık (varsayılan): işlemlere güvenlik ajanı karar verir; engellediğinde sohbette nedenini ve kapatma "
            "düğmesini görürsün.\n"
            "Kapalı: önce ▶ uygula düğmesi gelir, sonra her adımda sana sorulur." )
        if self.guard_btn.isChecked() != on:
            self.guard_btn.blockSignals(True)
            self.guard_btn.setChecked(on)
            self.guard_btn.blockSignals(False)
        self._center_model_tabs()
