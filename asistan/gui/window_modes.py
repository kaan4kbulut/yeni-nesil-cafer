"""Ana pencere: sansürsüz kip, güvenlik ajanı, ayarlar, güç (pil) kipi ve resim üretimi kurulumu."""

from pathlib import Path

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QMessageBox

from .. import power, roster, specialists
from ..agent import describe_error, list_ollama_models, settings_for
from ..cekirdek import profil

from .dialogs import SettingsDialog
from .icons import pixmap
from .sidebar import run_in_background
from .theme import C
from .work import open_folder


class ModesMixin:
    """MainWindow'un parçası (window.py); konusu modülün açıklamasında."""

    # ---- sansürsüz mod: aynı asistan (araçlar, hafıza, onaylar), ama kullanıcının seçtiği filtresiz yerel model
    def _installed_uncensored(self) -> list[str]:
        from .. import model_updates

        try:
            return [m for m in list_ollama_models(self.settings.ollama_url) if model_updates.is_uncensored(m)]
        except Exception:
            return []

    def _run_settings(self):
        """Çalışacak asistanın ayarları: sansürsüz modda bütün ekip (ajanlar, kod, düşünme, görme) sansürsüz
        modellere yönlendirilmiş bir kopya; kayıtlı ayarlara dokunulmaz (kopya hiç kaydedilmez)."""
        free = self._free_model()
        if not free:
            return self.settings
        from .. import model_updates

        team = model_updates.uncensored_team(self._installed_uncensored(), free)
        s = settings_for(self.settings, "ollama", free)
        s.auto_model, s.active_kind = True, "offline"
        s.defaults = {"offline": f"ollama|{free}", "code": f"ollama|{team['code']}"}
        s.specialists = {"code": f"ollama|{team['code']}", "reasoning": f"ollama|{team['reasoning']}",
                         **({"vision": f"ollama|{team['vision']}"} if team["vision"] else {})}
        s.extra = {**s.extra, "uncensored_only": True}  # otomatik seçim yalnızca sansürsüz modellerden
        return s

    def _update_free_btn(self):
        on = bool(self.settings.extra.get("uncensored"))
        model = self._free_model() or self.settings.extra.get("uncensored_model", "")  # pilde küçük olan
        self._switch_style(self.free_btn, on, C["error"])
        self.free_btn.setText(f"🔓 sansürsüz: {model.split('/')[-1]}" if on and model else "🔓 sansürsüz: kapalı")
        self._center_model_tabs()  # dar pencerede kısa yazı
        self.free_btn.setToolTip("Açık: sohbetleri seçtiğin sansürsüz (filtresiz) model yürütür; araçlar ve "
                                 "hafıza aynı kalır; güvenlik ajanı kapanır, işlemleri sen onaylarsın.\nKapalı: normal modeller.")
        if self.free_btn.isChecked() != on:
            self.free_btn.blockSignals(True)
            self.free_btn.setChecked(on)
            self.free_btn.blockSignals(False)
        self._center_model_tabs()

    def _toggle_uncensored(self, on: bool, model: str = ""):
        from .. import model_updates

        if on:
            # araç kullanabilen (dosya, komut, ekip işleri yapabilen) sansürsüz modeller önce
            installed = sorted(self._installed_uncensored(), key=lambda m: "tools" not in
                               specialists._capabilities(self.settings.ollama_url, m))
            model = model or (self.settings.extra.get("uncensored_model") if
                              self.settings.extra.get("uncensored_model") in installed else "") or \
                (installed[0] if installed else "")
            if not model:  # kurulu sansürsüz model yok: bilgisayara sığan en büyüğünü indirmeyi öner
                info = self._system_info()
                budget = info.vram_gb * 0.92 if info.vram_gb else info.ram_gb * 0.5
                fits = [u for u in model_updates.UNCENSORED_MODELS if u["size"] <= budget] or \
                    sorted(model_updates.UNCENSORED_MODELS, key=lambda u: u["size"])[:1]
                best = max(fits, key=lambda u: u["size"])
                self._update_free_btn()  # kapalı kalsın
                self._download_model(best["model"], best["size"], "uncensored")
                return
        self.settings.extra = {**self.settings.extra, "uncensored": on,
                               **({"uncensored_model": model} if on else {})}
        # güvenlik ajanı sansürsüz modelle birlikte çalışamıyor: sansürsüz modda kapanır, çıkınca geri açılır
        guard_note = ""
        if on and self.settings.approval_mode == "guvenlik":
            self.settings.approval_mode = "kullanici"
            self.settings.extra["guvenlik_sansursuz"] = True
            guard_note = " · 🛡 güvenlik kapatıldı (işlemleri sen onaylarsın)"
        elif not on and self.settings.extra.get("guvenlik_sansursuz"):
            self.settings.approval_mode = "guvenlik"
            self.settings.extra["guvenlik_sansursuz"] = False
            guard_note = " · 🛡 güvenlik yeniden açık"
        self.settings.save()
        self._update_guard_btn()
        self._update_free_btn()
        if not self.worker:
            self.new_conversation()  # normal ve sansürsüz sohbetler karışmasın
        self._update_header()
        if on and "tools" not in specialists._capabilities(self.settings.ollama_url, model):
            self.chat.add_notice(
                f"🔓 {model} araç kullanamıyor: sansürsüz sohbet yapar ama dosya, komut ve ekip işlerini yapamaz. "
                "Bunlar için Offline → uzmanlığa göre → Sansürsüz listesinden “araç” etiketli bir model seç ya da indir.", C["text2"])
        self._notify((f"🔓 Sansürsüz mod açık: {model}" if on else "Sansürsüz mod kapalı: normal modellere dönüldü.")
                     + guard_note, 8000)

    def _toggle_guard(self, on: bool):
        self.settings.approval_mode = "guvenlik" if on else "kullanici"
        self.settings.extra = {**self.settings.extra, "guvenlik_sansursuz": False}  # kullanıcı kendisi seçti
        self.settings.save()
        if on and self.settings.extra.get("uncensored"):
            self.free_btn.setChecked(False)  # ikisi birlikte çalışamaz: güvenlik açılınca sansürsüz mod kapanır
        self._update_guard_btn()
        self._notify("🛡 Güvenlik ajanı açık: onayları o verecek, sana sorulmayacak." if on else
                     "Güvenlik ajanı kapalı: işlemler önce ▶ düğmesi, sonra her adımda senin onayınla.", 8000)

    def _open_settings(self):
        dlg = SettingsDialog(self.settings, self)
        if dlg.exec():
            dlg.apply_to(self.settings)
            self.settings.save()
            self._apply_power(announce=False)
            self._update_guard_btn()
            self._reload_models()
            self._refresh_models_status()
            self._check_context()
            self.agent_panel.refresh()

    def _fix_gpu(self):
        """Model en güçlü kartta değilse ve Ollama'yı program başlattıysa: bir kez o karta sabitleyip yeniden başlat.
        (Sistem servisine dokunulmaz; düzeltme model panelinde ve durum çubuğunda kullanıcıya gösterilir.)"""
        from .. import sysinfo

        report = self.right.models.gpu_report
        if report is None or report.ok or report.fix or getattr(self, "_gpu_fixed", False) or self.worker:
            return
        self._gpu_fixed = True
        self.right.log.add(f"⚠ Ekran kartı: {report.text} Ollama en güçlü kartla yeniden başlatılıyor.")
        url = self.settings.ollama_url
        run_in_background(lambda: sysinfo.restart_ollama(url), lambda ok, err: self._refresh_models_status(), self)

    def _set_conn(self, ok: bool | None, text: str):
        color = C["muted"] if ok is None else (C["success"] if ok else C["error"])
        self.conn_label.setText(f'<span style="color:{color}">●</span>&nbsp; {text}')

    def _refresh_models_status(self):
        share = self.right.models.refresh()
        self.gpu_share = share
        self._fix_gpu()
        self._update_context_label()
        if self.provider == "claude":
            self._set_conn(None, "claude")
            self.banner.hide()
            return
        conn = self._connection(self.provider)
        if conn:
            ok, _ = self.api_panel.status.get(conn.id, (None, ""))
            self._set_conn(ok, conn.name.lower())
            self.banner.hide()
            return
        if not self.right.models.list.count():
            self._set_conn(False, "ollama bağlı değil")
            return
        self._set_conn(True, "ollama bağlı")
        # ekran kartı sorunu: model paneliyle aynı teşhis (gpu.check) — sebep ve gerçekten işe yarayan çözüm
        report = self.right.models.gpu_report
        if report is not None and not report.ok and not self.banner_dismissed:
            command = report.fix if report.fix.startswith("sudo ") else ""
            self.banner_fix = command
            self.banner_copy.setVisible(bool(command))
            self.banner_text.setText(f"⚠  {report.text}" + (f"  Çözüm: {report.fix}" if report.fix else ""))
            self.banner.show()
        elif report is None or report.ok:
            self.banner.hide()

    # ---- güç: pildeyken hafif mod (power.py)
    def _update_power_label(self):
        text = power.label(self.settings)
        self.power_label.setText(text)
        self.power_label.setVisible(bool(text))
        self.power_label.setToolTip(
            "Hafif mod: küçük model, en çok 8K bağlam, düşünmesiz yanıt; modeller arasında gidip gelinmez.\n"
            "Fişe takılınca tam güce döner. Ayarlar → Güç'ten değiştirilebilir." if power.saving(self.settings)
            else "Pildesin ama Ayarlar → Güç 'her zaman tam güç': büyük modeller pilde yavaş çalışır.")

    # ---- donanım kademesi (cekirdek/profil.py): açılışta ölçülür, durum çubuğunda görünür, elle kilitlenebilir
    def _measure_profile(self):
        self._update_tier_btn()
        run_in_background(lambda: profil.guncelle(sunucu=False), lambda _p, _e: self._update_tier_btn(), self)

    def _update_tier_btn(self):
        p = profil.yukle() or {}
        tier = profil.kademe()
        locked = profil.kilit()
        self.tier_btn.setText(f"kademe: {profil.ADLAR[tier]}" + (" 🔒" if locked else ""))
        off = [profil.AGIR_OZELLIKLER[o] for o in profil.AGIR_OZELLIKLER if not profil.acik_mi(o)]
        why = (p.get("kademe") or {}).get("neden") or "ölçülüyor…"
        tip = (f"Elle kilitli. Ölçüm: {why}" if locked else why) + (
            "\nBu kademede kapalı: " + ", ".join(off) if off else "") + "\nTıkla: profil özeti ve kademe kilidi."
        self.tier_btn.setToolTip(tip)

    def _open_profile(self):
        from .profil_dialog import ProfileDialog

        ProfileDialog(self, on_change=self._profile_changed).exec()

    def _profile_changed(self):
        self._update_tier_btn()
        self._update_context_label()  # dusuk kademede bağlam tavanı değişir

    def _update_light_btn(self):
        btn = getattr(self, "light_btn", None)
        if btn is None:
            return
        on = power.saving(self.settings)
        self._switch_style(btn, on, C["warn"])
        pct = power.state().percent if power.state().on_battery else None
        where = "pilde" if power.state().on_battery else "fişte"
        btn.setText(f"🔋 hafif mod: {'açık' if on else 'kapalı'}" + (f" · %{pct}" if pct is not None else ""))
        self._center_model_tabs()  # dar pencerede kısa yazı
        mode = self.settings.power_mode
        how = {"otomatik": "otomatik (pilde açılır, fişte kapanır)", "performans": "her zaman kapalı",
               "tasarruf": "her zaman açık"}.get(mode, mode)
        if self.settings.extra.get("power_override"):
            how = "elle seçildi — fiş takılınca ya da çıkarılınca yeniden otomatik"
        btn.setToolTip(f"Hafif mod: küçük model, en çok 8K bağlam, düşünmesiz yanıt; pilde çok daha hızlı.\n"
                       f"Şu an {where} · {how}.\nKalıcı ayar: Ayarlar → Güç.")
        if btn.isChecked() != on:
            btn.blockSignals(True)
            btn.setChecked(on)
            btn.blockSignals(False)

    def _toggle_light(self, on: bool):
        """Sağ üstteki anahtar: seçim bir sonraki fiş takma/çıkarmaya kadar geçerli (sonra otomatiğe döner).
        Otomatiğin zaten yapacağı seçilirse doğrudan otomatik olur."""
        s = self.settings
        if on == power.state(refresh=True).on_battery:
            s.power_mode = "otomatik"
            s.extra = {**s.extra, "power_override": False}
        else:
            s.power_mode = "tasarruf" if on else "performans"
            s.extra = {**s.extra, "power_override": True}
        s.save()
        self._apply_power(announce=False)
        self._notify("🔋 hafif mod açık: küçük model, 8K bağlam, düşünmesiz" if on else
                     "hafif mod kapalı: tam güç" + (" — pilde büyük modeller yavaş çalışır" if
                                                    power.state().on_battery else ""), 10000)

    def _check_power(self):
        """Fişe takılınca/çıkarılınca modeli ve bağlamı yeniden seçer; çalışan iş bitince sıradaki mesajda uygulanır."""
        battery = power.state().on_battery
        if battery != self._on_battery and self.settings.extra.get("power_override"):
            # elle seçim yalnızca o güç durumu için: fiş takılınca/çıkarılınca otomatiğe dönülür
            self.settings.power_mode = "otomatik"
            self.settings.extra = {**self.settings.extra, "power_override": False}
            self.settings.save()
        self._on_battery = battery
        self._apply_power(announce=True)

    def _apply_power(self, announce: bool):
        """Hafif mod değiştiyse modeli ve bağlamı yeniden seçer; göstergeleri günceller."""
        now = power.saving(self.settings)
        self._update_power_label()
        self._update_light_btn()
        if now == self.saving:
            return
        self.saving = now
        roster.candidates(self.settings, refresh=True)  # puanlar güç durumuna göre değişti
        if announce and now:
            self._notify("🔋 pildesin: hafif moda geçildi (küçük model, 8K bağlam, düşünmesiz)", 12000)
        elif announce:
            self._notify("🔌 fişe takıldı: tam güce dönüldü", 10000)
        if not self.worker and not (self.task_worker and self.task_worker.isRunning()):
            free = self.settings.extra.get("uncensored") and self.settings.extra.get("uncensored_model")
            if not free:
                self._auto_route()
        self._update_context_label()
        self._update_header()

    def _image_setup(self):
        """Yerel resim üretimi: kurulu değilse motor + model (~7 GB) program içinden indirilir."""
        from .. import imagegen

        if imagegen.installed():
            folder = Path(self.settings.workspace) / "Resimler"
            folder.mkdir(parents=True, exist_ok=True)
            self._notify("resim üretimi kurulu — sohbette “… resmini oluştur” yazman yeterli", 10000)
            open_folder(str(folder))
            return
        if getattr(self, "_image_installing", False):
            self._notify("resim üretimi zaten kuruluyor…", 5000)
            return
        info = imagegen.MODELS[imagegen.DEFAULT_MODEL]
        answer = QMessageBox.question(
            self, "Resim üretimi",
            f"Yerel resim üretimi kurulsun mu?\n\nModel: {info['title']}\nİndirme: ~{info['size'] + 0.05:.1f} GB "
            "(motor + model). Kesilirse kaldığı yerden sürer.\n\nKurulunca asistan sohbette resim üretebilir; "
            "resimler çalışma klasöründe Resimler/ altına kaydedilir. Reşit olmayanları çağrıştıran istekler her "
            "zaman engellenir.")
        if answer != QMessageBox.Yes:
            return
        self._image_installing = True

        def progress(pct, text):
            QTimer.singleShot(0, self, lambda: self._notify(f"resim üretimi kuruluyor · {text}"
                                                            + (f" · %{pct}" if pct >= 0 else ""), 600000))

        def done(_res, error):
            self._image_installing = False
            if error:
                self._notify(f"resim üretimi kurulamadı: {describe_error(error)}", 20000)
                return
            self._notify("✓ resim üretimi hazır — sohbette “… resmini oluştur” yazabilirsin", 20000)

        run_in_background(lambda: imagegen.install(progress, lambda: False), done, self)

    def _figure_setup(self):
        """Resimden gerçek 3D figür (figure3d.py): kurulu değilse kütüphaneler + TripoSR modeli (~1,7 GB) indirilir."""
        from .. import figure3d

        if figure3d.installed():
            self._notify("3D figür motoru kurulu — sohbette “3D yazıcı için oturan bir kedi figürü yap” gibi yaz", 10000)
            return
        if getattr(self, "_figure_installing", False):
            self._notify("3D figür motoru zaten kuruluyor…", 5000)
            return
        size = figure3d.download_gb()
        answer = QMessageBox.question(
            self, "3D figür motoru",
            "Resimden gerçek 3D figür yapan yerel model (TripoSR, ücretsiz, MIT lisanslı) kurulsun mu?\n\n"
            f"İndirme: ~{size:.1f} GB. Kesilirse kaldığı yerden sürer.\n\nKurulunca asistan hayvan, karakter ya da "
            "biblo figürlerini önce resmini üretip sonra 3D yazıcıda basılacak hacimli bir modele çevirebilir. Arka "
            "taraf tek resimden tahmin edildiği için ince ayrıntılar sadeleşebilir.")
        if answer != QMessageBox.Yes:
            return
        self._figure_installing = True

        def progress(pct, text):
            QTimer.singleShot(0, self, lambda: self._notify(f"3D figür motoru kuruluyor · {text}"
                                                            + (f" · %{pct}" if pct >= 0 else ""), 600000))

        def done(_res, error):
            self._figure_installing = False
            if error:
                self._notify(f"3D figür motoru kurulamadı: {describe_error(error)}", 20000)
                return
            self._notify("✓ 3D figür motoru hazır — sohbette “oturan bir kedi figürü yap” yazabilirsin", 20000)

        run_in_background(lambda: figure3d.install(progress, lambda: False), done, self)

    def _free_model(self) -> str:
        """Sansürsüz modda çalışacak model: pildeyken kuruluysa küçük bir sansürsüz model (seçilen yerine)."""
        free = self.settings.extra.get("uncensored") and self.settings.extra.get("uncensored_model")
        if not free or not power.saving(self.settings):
            return free or ""
        installed = set(self._installed_uncensored())
        small = [c for c in roster.candidates(self.settings) if c.model in installed
                 and 0 < c.params <= power.BATTERY_MAX_PARAMS]
        if not small:
            return free
        return max(small, key=lambda c: ("tools" in c.caps, c.params)).model

    def _tick(self):
        if self.worker:
            self.run_label.setText(f"{self.run_clock.elapsed() / 1000:.0f} sn")

    def _notify(self, text: str, ms: int = 8000):
        """Durum çubuğunda geçici bilgi (showMessage diğer bölmeleri gizlediği için kullanılmaz)."""
        self.notice_label.setText(text)
        self.notice_timer.start(ms)

    def _set_mode(self, text: str):
        self.mode_label.setText(text)

    def _right_toggled(self, on: bool):
        self.right.setVisible(on)
        self.toggle_icon.setPixmap(pixmap("panel-right", C["accent"] if on else C["text2"], 14))
