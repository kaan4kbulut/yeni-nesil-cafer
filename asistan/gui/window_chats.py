"""Ana pencere: sohbet listesi ve klasörleri, toplu seçim, yeni sohbet, sohbet menüleri."""

import threading
from datetime import date, datetime
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor
from PySide6.QtWidgets import QInputDialog, QMenu, QMessageBox, QTreeWidgetItem

from .. import learning, roster, specialists, suggest
from ..storage import Conversation

from .chat import tool_label
from .icons import agent_icon, icon
from .theme import C


class ChatsMixin:
    """MainWindow'un parçası (window.py); konusu modülün açıklamasında."""

    # ---- sohbet listesi (klasörler)
    def _refresh_sidebar(self):
        self.chat_tree.blockSignals(True)  # kutucuk kurulurken itemChanged tetiklenmesin
        self._fill_chat_tree()
        self.chat_tree.blockSignals(False)
        self._update_select_bar()

    # ---- sohbet seçimi (toplu silme / taşıma)
    def _set_select_mode(self, on: bool):
        self.select_mode = on
        if not on:
            self.selected_ids.clear()
        if self.select_btn.isChecked() != on:
            self.select_btn.setChecked(on)
        self.select_bar.setVisible(on)
        self.select_all_btn.setVisible(on)
        self._refresh_sidebar()

    def _chat_checked(self, item: QTreeWidgetItem, column: int):
        data = item.data(0, Qt.UserRole)
        if not self.select_mode or not data or data[0] != "chat":
            return
        if item.checkState(0) == Qt.Checked:
            self.selected_ids.add(data[1])
        else:
            self.selected_ids.discard(data[1])
        self.checked_by_indicator = item  # kutucuğa tıklandı: ardından gelen tıklama işareti geri çevirmesin
        self._update_select_bar()

    def _update_select_bar(self):
        self.select_count.setText(f"{len(self.selected_ids)} Seçili")
        if hasattr(self, "select_all_btn"):
            self.select_all_btn.setText("Seçimi Kaldır" if self._all_selected() else "Tümünü Seç")

    def _all_selected(self) -> bool:
        ids = self._visible_conv_ids()
        return bool(ids) and set(ids) <= self.selected_ids

    def _toggle_select_all(self):
        if self._all_selected():
            self._clear_selection()
        else:
            self._select_all()

    def _visible_conv_ids(self, folder: str | None = None) -> list[str]:
        ids = []
        for i in range(self.chat_tree.topLevelItemCount()):
            top = self.chat_tree.topLevelItem(i)
            if folder is not None and top.data(0, Qt.UserRole)[1] != folder:
                continue
            ids += [top.child(j).data(0, Qt.UserRole)[1] for j in range(top.childCount())]
        return ids

    def _select_all(self, folder: str | None = None):
        if not self.select_mode:
            self._set_select_mode(True)
        self.collapsed_folders.clear()  # kapalı klasördekiler de görünsün
        self._refresh_sidebar()
        self.selected_ids.update(self._visible_conv_ids(folder))
        self._refresh_sidebar()

    def _select_one(self, conv_id: str):
        self._set_select_mode(True)
        if conv_id:
            self.selected_ids.add(conv_id)
        self._refresh_sidebar()

    def _clear_selection(self):
        self.selected_ids.clear()
        self._refresh_sidebar()

    def _selected_convs(self) -> list[Conversation]:
        return [c for c in self.conversations if c.id in self.selected_ids]

    def _delete_selected(self):
        convs = self._selected_convs()
        if not convs:
            self._notify("Önce silinecek sohbetleri işaretle.")
            return
        if self.worker:
            self._notify("Asistan çalışırken sohbet silinemez; bitmesini bekle ya da durdur.")
            return
        if QMessageBox.question(self, "Sohbetleri sil", f"{len(convs)} sohbet silinsin mi? Bu geri alınamaz.") \
                != QMessageBox.Yes:
            return
        for conv in convs:
            conv.delete()
            self.conversations.remove(conv)
        self.selected_ids.clear()
        if self.conv in convs:
            self.new_conversation()
        self._refresh_sidebar()
        self._notify(f"{len(convs)} sohbet silindi")

    def _move_selected_menu(self):
        menu = QMenu(self)
        self._fill_move_menu(menu)
        menu.exec(self.cursor().pos())

    def _fill_move_menu(self, menu: QMenu):
        for name in self.settings.chat_folders:
            menu.addAction(name, lambda n=name: self._move_selected(n))
        menu.addSeparator()
        menu.addAction(icon("folder-plus"), "Yeni klasör…", self._move_selected_new)

    def _move_selected(self, folder: str):
        convs = self._selected_convs()
        for conv in convs:
            self._move_conv(conv, folder)
        self._notify(f"{len(convs)} sohbet “{folder}” klasörüne taşındı")

    def _move_selected_new(self):
        name, ok = QInputDialog.getText(self, "Yeni klasör", "Klasör adı:")
        name = name.strip()
        if ok and name:
            if name not in self.settings.chat_folders:
                self.settings.chat_folders.append(name)
                self.settings.save()
            self._move_selected(name)

    def _fill_chat_tree(self):
        self.chat_tree.clear()
        query = self.search.text().strip().lower()
        folders = list(self.settings.chat_folders)
        for conv in self.conversations:
            if conv.folder not in folders:
                folders.append(conv.folder)
        for name in folders:
            convs = [c for c in self.conversations if c.folder == name and c.messages
                     and (not query or query in c.title.lower())]
            if query and not convs:
                continue
            collapsed = not query and name in self.collapsed_folders
            folder_item = QTreeWidgetItem([name.upper() + (f"  ›  {len(convs)}" if collapsed else "")])
            folder_item.setData(0, Qt.UserRole, ("folder", name))
            folder_item.setFlags(Qt.ItemIsEnabled)
            folder_item.setFont(0, self._label_font)
            folder_item.setForeground(0, QColor(C["muted"]))
            self.chat_tree.addTopLevelItem(folder_item)
            folder_item.setFirstColumnSpanned(True)
            today = date.today()
            for conv in convs:
                profile = next((p for p in self.profiles if p.id == conv.agent_id), None) if conv.agent_id else None
                when = datetime.fromtimestamp(conv.updated)
                stamp = when.strftime("%H:%M") if when.date() == today else when.strftime("%d.%m")
                running = self.worker is not None and self.conv is conv
                item = QTreeWidgetItem([conv.title, "■" if running else stamp])
                if profile:
                    item.setIcon(0, icon(agent_icon(profile.icon), C["muted"], 14))
                item.setData(0, Qt.UserRole, ("chat", conv.id))
                item.setToolTip(0, conv.title)
                if self.select_mode:
                    item.setFlags(item.flags() | Qt.ItemIsUserCheckable)
                    item.setCheckState(0, Qt.Checked if conv.id in self.selected_ids else Qt.Unchecked)
                item.setFont(1, self._stamp_font)
                item.setForeground(1, QColor(C["accent"] if running else C["muted"]))
                item.setTextAlignment(1, Qt.AlignRight | Qt.AlignVCenter)
                folder_item.addChild(item)
                if self.conv and conv.id == self.conv.id:
                    item.setSelected(True)
            folder_item.setExpanded(not collapsed)

    def _tree_clicked(self, item: QTreeWidgetItem):
        kind, value = item.data(0, Qt.UserRole)
        by_indicator, self.checked_by_indicator = self.checked_by_indicator is item, None
        if self.select_mode and kind == "chat":  # seçim modunda tıklamak sohbeti açmaz, işaretler
            if not by_indicator:  # kutucuğun kendisine tıklandıysa Qt zaten işaretledi
                item.setCheckState(0, Qt.Unchecked if item.checkState(0) == Qt.Checked else Qt.Checked)
                self.checked_by_indicator = None
            return
        if kind == "folder":
            self.current_folder = value
            if value in self.collapsed_folders:
                self.collapsed_folders.discard(value)
            else:
                self.collapsed_folders.add(value)
            self._refresh_sidebar()
            if self.conv and not self.conv.messages:  # boş yeni sohbet bu klasöre açılsın
                self.conv.folder = value
                self._update_header()
        else:
            self._open_item(value)

    def _new_folder(self):
        name, ok = QInputDialog.getText(self, "Yeni klasör", "Klasör adı:")
        name = name.strip()
        if ok and name and name not in self.settings.chat_folders:
            self.settings.chat_folders.append(name)
            self.settings.save()
            self.current_folder = name
            self._refresh_sidebar()

    def new_conversation(self, agent_id: str = ""):
        if self.worker:
            return
        self.conv = Conversation(provider=self.provider, agent_id=agent_id, folder=self.current_folder)
        self.last_context = 0
        if hasattr(self, "workspace_btn"):
            self._update_workspace_label()
        self.chat.clear()
        profile = self.profile
        if profile:
            if profile.provider and not self._set_provider_model(profile.provider, profile.model):
                self.chat.add_notice(
                    f"⚠ {profile.name} ajanının modeli bulunamadı; seçili model kullanılacak.", C["warn"])
            self.conv.provider = self.provider
            tools = "tüm araçlar" if profile.tools is None else (
                " · ".join(tool_label(t) for t in profile.tools) or "araç yok")
            self.chat.add_welcome(
                f"{profile.name}.", profile.description or "Bu sohbet bu ajanla yapılır.",
                lambda: suggest.pick(profile.id), f"kullanabildiği araçlar: {tools}", self._pick_suggestion)
        else:
            folder = Path(self.settings.workspace).name
            self.chat.add_welcome(
                "Merhaba.",
                "Sohbet edebilir, çalışma klasöründeki dosyalarla çalışabilir, komut ve Python "
                "çalıştırabilir, web'de araştırma yapabilirim.",
                lambda: suggest.pick("", folder=folder),  # her açılışta farklı; son sohbetlerine göre kişisel
                "Attığım her adımı sağ paneldeki adımlarda görebilirsin · Ctrl+J", self._pick_suggestion)
        self.agent_panel.select(agent_id)
        self.chat_tree.clearSelection()
        self._auto_route()  # üst menüdeki seçim (Online · Offline) açılışta da etikete yansısın
        self._update_header()
        self._update_context_label()
        self.input.setFocus()

    def _retry_message(self, text: str):
        """Kullanıcının önceki mesajını aynen yeniden gönderir."""
        if self.worker:
            self._notify("asistan hâlâ çalışıyor — bitince tekrar dene")
            return
        self.input.setPlainText(text)
        self._send_or_stop()

    def _learn_from_run(self, w):
        """Tur bitti: başarılı yöntemi beceri olarak kaydet, başarısızlığı gelişim kaydına yaz."""
        if w.is_cancelled():
            return
        if self.conv and self.conv.work_dir:  # proje hafızası: bu işte en son ne yapıldı
            bubble = self.chat.last_bubble
            last = bubble.text()[:300] if bubble is not None else ""
            args = (self.conv.work_dir, self.conv.title, self.conv.title, last)
            threading.Thread(target=learning.save_project, args=args, daemon=True).start()
        request = self.chat.last_request or ""
        model = getattr(self, "last_run_model", "")
        used = [x["id"] for x in getattr(self, "used_skills", [])]
        if request.startswith("📈"):  # gelişim raporu: son rapor olarak sakla (öğrenme penceresinde görünür)
            bubble = self.chat.last_bubble
            if bubble is not None and bubble.text().strip():
                learning.save_report(bubble.text())
            return
        if w.agent.succeeded and w.agent.done_steps:
            skill = learning.save_skill(learning.original_request(request), w.agent.done_steps, model)
            learning.record_skill_result(used, True)
            if skill:
                self.chat.add_notice(f"🧩 Bu yöntem beceri olarak kaydedildi: «{skill['title'][:70]}» — benzer "
                                     "işlerde tekrar kullanılacak.", C["muted"])
        elif w.agent.gave_up:
            learning.record_skill_result(used, False)
            errors = sorted({k[2][-200:] for k in w.agent.failed_calls})  # tekrarlanan hataların son satırları
            learning.log_issue("tamamlanamadi", learning.original_request(request), model,
                               "; ".join(errors) or "model istenen işi/dosyaları tamamlayamadı")
            self._offer_report("tamamlanamadi", "; ".join(errors) or "model istenen işi/dosyaları tamamlayamadı")
        n = learning.new_issue_count()
        if n >= 3 and not getattr(self, "growth_hint_shown", False):
            self.growth_hint_shown = True
            self._notify(f"🌱 {n} iş tamamlanamadı ya da beğenilmedi — Yardım → Hafıza ve öğrenme'den "
                         "gelişim raporu hazırlayabilirsin.", 20000)

    def _regenerate(self, request: str):
        """Beğenilmeyen yanıt için: aynı isteğe öncekinden farklı bir çözüm ister."""
        bubble = self.chat.last_bubble
        learning.log_issue("begenilmedi", learning.original_request(request), getattr(self, "last_run_model", ""),
                           "önceki cevap: " + (bubble.text()[:600] if bubble is not None else ""))
        first = request.strip().splitlines()[0] if request.strip() else ""
        quote = first[:200] + ("…" if len(first) > 200 or len(request.strip().splitlines()) > 1 else "")
        self._retry_message(
            f"↻ Önceki cevabını beğenmedim. Şu isteğim için öncekinden belirgin şekilde farklı bir yaklaşımla "
            f"yeni bir çözüm bul; aynı fikri tekrarlama: «{quote}»")

    def _self_check(self, request: str):
        """Yanıttaki "hata var": yarım kalan, hiçbir şey yapmayan ya da yanlış cevap. Asistan isteği, gerçekten
        yaptıklarını ve ürettiği dosyaları karşılaştırıp eksik kalanı şimdi yapar (açıklamayla oyalanmadan)."""
        bubble = self.chat.last_bubble
        learning.log_issue("hata_bildirildi", learning.original_request(request), getattr(self, "last_run_model", ""),
                           "önceki cevap: " + (bubble.text()[:600] if bubble is not None else ""))
        full = " ".join(learning.original_request(request).split())
        quote = full[:1500] + ("…" if len(full) > 1500 else "")
        self._retry_message(
            f"⚠ Önceki cevabında sorun var: yarım kaldı, istediğimi yapmadın ya da hatalı. Kendini kontrol et:\n"
            f"1. İsteğimi yeniden oku: «{quote}»\n"
            "2. Bu sohbette gerçekten çalıştırdığın adımlara ve iş klasöründeki dosyalara bak (list_files); yalnızca "
            "yazdığın ama yapmadığın şeyleri yapılmış sayma.\n"
            "3. İsteğin hangi kısmı eksik ya da yanlış, bul.\n"
            "4. Eksik kısmı şimdi araçlarla gerçekten yap, hatayı düzelt ve sonucu kontrol et (görsel/3D ise "
            "inspect_output ile).\n"
            "Özür dileyip açıklamayla vakit kaybetme. Sonucu belirleyen bir bilgi gerçekten eksikse tek bir kısa soru "
            "sor. Bitince neyi düzelttiğini kısaca yaz.")

    def _apply_suggestions(self, request: str):
        """Öneri cevabındaki "uygula": asistan önerdiklerini şimdi yapar (onay pencereleri yine sorar)."""
        # isteğin tamamı: kesilirse model görevin bir kısmını hiç görmez (ör. "sonunda en yüksek ayı söyle")
        full = " ".join(request.split("\n\n[Ek")[0].split())
        quote = full[:2000] + ("…" if len(full) > 2000 else "")
        self._retry_message(f"▶ Onaylıyorum, planladığın işlemleri şimdi yap: «{quote}». Önceki turda hiçbir şey "
                            "çalıştırılmadı, dosya yazılmadı — yalnızca planlandı. Şimdi araçları gerçekten çağır: bu "
                            "sisteme uygun komutlar kullan, isteğin her parçasını sırayla yap ve sonunda neyi yaptığını "
                            "kısaca özetle.")

    def _focus_search(self):
        self.side_tabs.button(0).click()
        self.search.setFocus()

    def _pick_suggestion(self, text: str):
        """Öneri ya da soru baloncuğu: mesaj olarak gönderilir (iş sürüyorsa durdurmaz, sıraya girer)."""
        self.input.setPlainText(text)
        self._submit()

    def _start_agent_chat(self, agent_id: str):
        if self.worker:
            return
        self.new_conversation(agent_id)
        self.center_stack.setCurrentIndex(0)

    def _agent_model(self, p) -> tuple[str, bool]:
        """Ajanın kullandığı model: (metin, kendi modeli mi)."""
        def label(provider: str, model: str) -> str:
            if provider == "ollama":  # yerel modelde adı yeterli
                return model or "ollama"
            conn = self._connection(provider)
            source = conn.name.lower() if conn else provider
            return f"{source} · {model}" if model else source

        if not hasattr(self, "model_box"):  # pencere kurulurken: ayarlardaki seçim
            provider, model = self.settings.provider, None
        else:
            provider, model = self.provider, self.model_box.currentText()
        if p.provider and (not hasattr(self, "provider_box") or self.provider_box.findData(p.provider) >= 0):
            return label(p.provider, p.model), True
        if self.settings.auto_model:
            # işi yapan kodla aynı karar (kategorili ajanda kategorinin modeli): panel başka model göstermesin
            provider_, model_ = roster.assign(self.settings, p, ("", ""))
            if provider_:
                if provider_ == specialists.CLAUDE_CODE[0]:
                    return "otomatik · Claude Code" + ("" if model_ == specialists.CLAUDE_CODE[1] else f" · {model_}"), False
                return "otomatik · " + label(provider_, model_), False
        if model is None:
            model = {"claude": self.settings.claude_model, "ollama": self.settings.ollama_model}.get(
                provider, self.settings.api_models.get(provider[4:], ""))
        return label(provider, model), False

    def _expert_models(self) -> list[tuple[str, str]]:
        from .. import specialists

        titles = {"vision": "görsel&nbsp;&nbsp;&nbsp;", "reasoning": "düşünme&nbsp;", "code": "kod&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;"}
        return [(t, specialists.describe(self.settings, role)) for role, t in titles.items()]

    def _side_tab_changed(self, index: int):
        self.side_stack.setCurrentIndex(index)
        if index == 2:
            self.agent_panel.refresh()
        if index == 4:
            self.library_panel.refresh()  # ajanlar iş sırasında kütüphane kurmuş olabilir
        if index == 0:
            self.center_stack.setCurrentIndex(0)
        elif index == 1:
            self.center_stack.setCurrentIndex(1)
            self._refresh_tasks()

    def _open_item(self, conv_id: str):
        if self.worker or not conv_id:
            return
        conv = next((c for c in self.conversations if c.id == conv_id), None)
        if not conv:
            return
        self.conv = conv
        self.current_folder = conv.folder
        self._update_workspace_label()  # sohbetin kendi iş klasörü (bağlantılar ve Dosyalar sekmesi)
        self.last_context = 0
        self.center_stack.setCurrentIndex(0)
        if conv.provider != self.provider and not self._set_provider_model(conv.provider):
            self._reload_models()
        self.chat.render_history(conv.messages, self.model_box.currentText())
        if conv.provider != self.provider:
            self.chat.add_notice(
                "⚠ Bu sohbetin API bağlantısı silinmiş. Devam etmek için API'ler sekmesinden yeniden ekle.",
                C["warn"])
        self.agent_panel.select(conv.agent_id)
        self._auto_route()
        self._update_header()
        self._update_context_label()

    def _chat_menu(self, pos):
        item = self.chat_tree.itemAt(pos)
        if self.worker:
            self._notify("Asistan çalışırken sohbet listesi düzenlenemez; bitmesini bekle ya da durdur.")
            return
        if self.select_mode or not item:
            self._selection_menu(pos, item)
            return
        kind, value = item.data(0, Qt.UserRole)
        menu = QMenu(self)
        select = menu.addAction(icon("square-check"), "Seç")
        select_all = menu.addAction("Hepsini seç")
        menu.addSeparator()
        select.triggered.connect(lambda: self._select_one(value if kind == "chat" else ""))
        select_all.triggered.connect(lambda: self._select_all())
        if kind == "folder":
            new = menu.addAction(icon("plus"), "Bu klasörde yeni sohbet")
            rename = menu.addAction("Yeniden adlandır")
            delete = menu.addAction("Klasörü sil") if value != "Genel" else None
            chosen = menu.exec(self.chat_tree.mapToGlobal(pos))
            if chosen is new:
                self.current_folder = value
                self.new_conversation()
            elif chosen is rename:
                name, ok = QInputDialog.getText(self, "Yeniden adlandır", "Klasör adı:", text=value)
                name = name.strip()
                if ok and name and name != value and name not in self.settings.chat_folders:
                    self._rename_folder(value, name)
            elif delete is not None and chosen is delete:
                if QMessageBox.question(self, "Klasörü sil",
                                        f"“{value}” silinsin mi? İçindeki sohbetler Genel'e taşınır.") == QMessageBox.Yes:
                    self._rename_folder(value, "Genel", remove=True)
            return
        conv = next(c for c in self.conversations if c.id == value)
        move = menu.addMenu(icon("folder"), "Klasöre taşı")
        for name in self.settings.chat_folders:
            a = move.addAction(name)
            a.setEnabled(name != conv.folder)
            a.setData(name)
        move.addSeparator()
        new_folder = move.addAction(icon("folder-plus"), "Yeni klasör…")
        menu.addSeparator()
        delete = menu.addAction("Sohbeti sil")
        chosen = menu.exec(self.chat_tree.mapToGlobal(pos))
        if chosen is delete:
            self._delete(conv)
        elif chosen is new_folder:
            name, ok = QInputDialog.getText(self, "Yeni klasör", "Klasör adı:")
            name = name.strip()
            if ok and name:
                if name not in self.settings.chat_folders:
                    self.settings.chat_folders.append(name)
                    self.settings.save()
                self._move_conv(conv, name)
        elif chosen is not None and chosen.data():
            self._move_conv(conv, chosen.data())

    def _move_conv(self, conv: Conversation, folder: str):
        conv.folder = folder
        conv.save()
        self._refresh_sidebar()
        self._update_header()

    def _rename_folder(self, old: str, new: str, remove: bool = False):
        folders = self.settings.chat_folders
        if remove:
            folders.remove(old)
        else:
            folders[folders.index(old)] = new
        for conv in self.conversations:
            if conv.folder == old:
                conv.folder = new
                conv.save()
        if self.current_folder == old:
            self.current_folder = new
        self.settings.save()
        self._refresh_sidebar()
        self._update_header()

    def _delete_current(self):
        if self.conv and self.conv in self.conversations and not self.worker:
            self._delete(self.conv)

    def _selection_menu(self, pos, item):
        """Seçim modunda sağ tık: hepsini seç, temizle, seçilenleri sil / taşı."""
        menu = QMenu(self)
        menu.addAction("Hepsini seç", lambda: self._select_all())
        data = item.data(0, Qt.UserRole) if item else None
        if data and data[0] == "folder":
            menu.addAction(f"“{data[1]}” klasöründekilerin hepsini seç", lambda: self._select_all(data[1]))
        menu.addAction("Seçimi temizle", self._clear_selection)
        menu.addSeparator()
        n = len(self.selected_ids)
        delete = menu.addAction(icon("trash"), f"Seçilenleri sil ({n})", self._delete_selected)
        move = menu.addMenu(icon("folder"), f"Seçilenleri klasöre taşı ({n})")
        self._fill_move_menu(move)
        delete.setEnabled(n > 0)
        move.setEnabled(n > 0)
        menu.addSeparator()
        menu.addAction("Seçim modundan çık", lambda: self._set_select_mode(False))
        menu.exec(self.chat_tree.mapToGlobal(pos))

    def _delete(self, conv: Conversation):
        conv.delete()
        self.conversations.remove(conv)
        if self.conv is conv:
            self.new_conversation()
        self._refresh_sidebar()
