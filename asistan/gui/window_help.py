"""Ana pencere: Yardım menüsündeki pencereler, model sınavı, gelişim ve sorun raporu, bulut iş kuyruğu."""

import threading
import time
from pathlib import Path

from PySide6.QtCore import Qt, QTimer, QUrl
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (
    QApplication, QDialog, QFrame, QHBoxLayout, QInputDialog, QLabel, QMessageBox, QPlainTextEdit, QPushButton,
    QVBoxLayout,
)

from .. import cards, learning, power, roster
from ..agent import list_ollama_models
from ..profiles import load_profiles

from .theme import C


class ReportPreview(QDialog):
    """Sorun raporunun önizlemesi: kaydetmeden önce görülür, istenmeyen satırlar silinebilir."""

    def __init__(self, text: str, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Sorun raporu · önizleme")
        self.resize(820, 640)
        lay = QVBoxLayout(self)
        hint = QLabel("Rapor kaydedilmeden önce içeriğini gör. Paylaşmak istemediğin satırları (ör. sohbetteki kişisel "
                      "bir bilgi) silebilirsin. API anahtarları, ev klasörün ve kullanıcı adın zaten gizlendi.",
                      objectName="hint")
        hint.setWordWrap(True)
        lay.addWidget(hint)
        self.editor = QPlainTextEdit()
        self.editor.setPlainText(text)
        lay.addWidget(self.editor, 1)
        row = QHBoxLayout()
        row.addStretch()
        cancel = QPushButton("İptal", objectName="smallButton")
        cancel.clicked.connect(self.reject)
        save = QPushButton("Kaydet ve panoya kopyala", objectName="primary")
        save.clicked.connect(self.accept)
        row.addWidget(cancel)
        row.addWidget(save)
        lay.addLayout(row)

    def text(self) -> str:
        return self.editor.toPlainText()


class HelpMixin:
    """MainWindow'un parçası (window.py); konusu modülün açıklamasında."""

    # ---- bulut asistan (Aşama 6)
    def _cloud_tick(self):
        from .. import cloud_sync

        if not cloud_sync.enabled(self.settings) or getattr(self, "_cloud_busy", False):
            return
        self._cloud_busy = True

        def work():
            jobs, error = [], ""
            try:
                cloud_sync.sync(self.settings)
                jobs = cloud_sync.pending_jobs(self.settings)
            except Exception as e:
                error = str(e)
            QTimer.singleShot(0, self, lambda: self._cloud_done(jobs, error))

        threading.Thread(target=work, daemon=True).start()

    def _cloud_done(self, jobs: list, error: str):
        self._cloud_busy = False
        if error:
            self.cloud_btn.setText("☁ bağlantı yok")
            self.cloud_btn.setToolTip(f"Bulut asistana ulaşılamadı: {error}")
            self.cloud_btn.setVisible(True)
            return
        new = [j for j in jobs if j["id"] not in {x["id"] for x in self.cloud_jobs}]
        self.cloud_jobs = jobs
        self.cloud_btn.setToolTip("Bulut asistanın bilgisayarına bıraktığı işler")
        self.cloud_btn.setText(f"☁ {len(jobs)} iş")
        self.cloud_btn.setVisible(bool(jobs))
        if new:
            self._notify(f"☁ Bulut asistan bilgisayarına {len(new)} iş bıraktı — durum çubuğundaki ☁ düğmesi", 15000)

    def open_cloud_jobs(self):
        from .. import cloud_sync

        if not self.cloud_jobs:
            self._cloud_tick()
            return
        dlg = QDialog(self)
        dlg.setWindowTitle("Buluttan gelen işler")
        dlg.setMinimumWidth(620)
        lay = QVBoxLayout(dlg)
        lay.setContentsMargins(20, 16, 20, 14)
        hint = QLabel("Bulut asistan bu işleri senin bilgisayarında yapılsın diye bıraktı. Hiçbiri sen onaylamadan "
                      "çalışmaz; “yap” dersen yeni bir sohbette YENİ NESİL CAFER yapar ve sonucu buluta geri gönderir.",
                      objectName="hint")
        hint.setWordWrap(True)
        lay.addWidget(hint)
        for job in self.cloud_jobs:
            box = QFrame(objectName="jobCard")
            box.setStyleSheet(f"#jobCard {{ border: 1px solid {C['frame']}; border-radius: 8px; }}")
            bl = QVBoxLayout(box)
            text = QLabel(job["task"])
            text.setWordWrap(True)
            text.setTextInteractionFlags(Qt.TextSelectableByMouse)
            bl.addWidget(text)
            if job.get("reason"):
                bl.addWidget(QLabel(job["reason"], objectName="hint"))
            row = QHBoxLayout()
            do = QPushButton("yap", objectName="primary")
            no = QPushButton("reddet", objectName="smallButton")
            do.clicked.connect(lambda _=False, j=job: (dlg.accept(), self._run_cloud_job(j)))
            no.clicked.connect(lambda _=False, j=job, b=box: (threading.Thread(
                target=cloud_sync.finish_job, args=(self.settings, j["id"], "reddedildi"), daemon=True).start(),
                b.hide(), self.cloud_jobs.remove(j), self._cloud_done(list(self.cloud_jobs), "")))
            row.addStretch()
            row.addWidget(no)
            row.addWidget(do)
            bl.addLayout(row)
            lay.addWidget(box)
        dlg.exec()

    def _run_cloud_job(self, job: dict):
        from .. import cloud_sync

        if self.worker:
            self._notify("asistan şu an çalışıyor; bitince tekrar dene")
            return
        threading.Thread(target=cloud_sync.finish_job, args=(self.settings, job["id"], "alindi"), daemon=True).start()
        self.cloud_job = job
        self.cloud_jobs = [j for j in self.cloud_jobs if j["id"] != job["id"]]
        self._cloud_done(list(self.cloud_jobs), "")
        self.new_conversation()
        self.input.setPlainText(f"☁ Buluttan gelen iş: {job['task']}")
        self._send_or_stop()

    def _cloud_job_finished(self, w):
        """Bulut işi bitti: sonucu (son yanıt) buluta gönder; durdurulduysa iş yeniden beklemeye döner."""
        from .. import cloud_sync

        if w.agent.gate_actions and w.agent.pending_actions and not w.is_cancelled():
            return  # "Ben onaylarım" kipinde bu tur yalnızca plan: iş ▶ uygula'dan sonraki turda yapılır
        job, self.cloud_job = self.cloud_job, None
        if w.is_cancelled():
            status, result = "bekliyor", ""
        else:
            bubble = self.chat.last_bubble
            status, result = "bitti", (bubble.text() if bubble is not None else "").strip() or "(yanıt yok)"
        threading.Thread(target=cloud_sync.finish_job, args=(self.settings, job["id"], status, result),
                         daemon=True).start()

    def open_factory(self):
        from .factory_dialog import FactoryDialog

        FactoryDialog(self).exec()

    def open_categories(self):
        from .categories_dialog import CategoriesDialog

        CategoriesDialog(self.settings, lambda m, size: self._download_model(m, size, None), self).exec()
        self.profiles = load_profiles()  # kategori ajanları eklenmiş olabilir
        self._refresh_sidebar()

    def open_tasks(self):
        """Görev motorunun görevleri (K4): ayrı pencere; sağ panel üç sekme kalır."""
        from .gorevler_dialog import GorevlerDialog

        GorevlerDialog(self.settings, getattr(self, "connections", None), self).exec()

    def open_capabilities(self):
        """Görev motorunun yetenekleri (K5): aktif/pasif, izinler, kaynak, güvenilir; ayrı pencere."""
        from .yetenekler_dialog import YeteneklerDialog

        YeteneklerDialog(self).exec()

    def open_models(self):
        """K7: Modeller penceresi (kademe listeleri, ölçümler, varsayılan, listeyi yenile)."""
        from .modeller_dialog import ModellerDialog

        ModellerDialog(self.settings, self).exec()

    def open_cards(self):
        from .cards_dialog import CardsDialog

        CardsDialog(self.settings.ollama_url, self).exec()
        roster._cache = None  # yeni kartlarla seçilsin

    def _exam_models(self):
        """Kartı olmayan yerel modelleri arka planda sınar: yalnızca program boştayken ve fişe takılıyken.
        Kullanıcı mesaj gönderince sınav durur, bir sonraki boş anda kalan modellerle sürer."""
        busy = lambda: (self.worker is not None or power.saving(self.settings)  # noqa: E731
                        or (self.task_worker is not None and self.task_worker.isRunning()))
        if getattr(self, "_exam_running", False) or busy():
            return
        self._exam_running = True
        url = self.settings.ollama_url

        def work():
            done = None
            try:
                done = cards.measure_missing(url, cancelled=busy, on_progress=lambda i, n, m: QTimer.singleShot(
                    0, self, lambda: self._notify(f"🧪 model sınavı {i}/{n} · {m}", 120000)))
            except Exception:  # durduruldu ya da Ollama kapalı: sonra yeniden denenir
                pass
            QTimer.singleShot(0, self, lambda: self._exam_done(done))

        threading.Thread(target=work, daemon=True).start()

    def _exam_done(self, done):
        self._exam_running = False
        if done:
            self._notify(f"🧪 {len(done)} model sınandı — sonuçlar: Yardım → Model kartları", 15000)
        else:
            self.notice_label.clear()

    def open_learning(self):
        """Asistanın hafızası, beceri kütüphanesi ve gelişim raporu."""
        from .learning_dialog import LearningDialog

        LearningDialog(self.settings, self._growth_report, self).exec()

    def _growth_report(self):
        """Gelişim raporu: sorun kayıtlarını yeni bir sohbette asistana inceletir (yalnızca yazı)."""
        from .learning_dialog import program_dir

        try:
            installed = [m if isinstance(m, str) else m.get("name", "") for m in list_ollama_models(self.settings.ollama_url)]
        except Exception:
            installed = []
        self.new_conversation()
        self.input.setPlainText(learning.report_request(program_dir(self.settings), installed))
        self._send_or_stop()

    # ---- sorun raporu (problem_report.py): program kendini değiştirmez, geliştiriciye verilecek raporu hazırlar
    def _offer_report(self, kind: str, detail: str = ""):
        """Sohbette "🐞 Sorunu raporla" kartı (aynı sorun art arda gelirse bir kez)."""
        from ..problem_report import KINDS

        now = time.monotonic()
        if now - getattr(self, "_last_offer", -60) < 30:
            return
        self._last_offer = now
        self.chat.add_report_offer(
            f"🐞 **{KINDS.get(kind, 'Sorun')}.** İstersen geliştiriciye (Claude Code) verebileceğin bir rapor "
            "hazırlayayım: ne olduğu, sohbetin ilgili kısmı, hatalar ve sistem bilgisi tek dosyada; API anahtarları "
            "gizlenir.", lambda card: self._make_report(kind, detail, card=card))

    def _make_report(self, kind: str, detail: str = "", note: str = "", card=None):
        """Raporu arka planda hazırlar (ön teşhis yerel modelle ~10-60 sn); kaydetmeden önce önizleme açılır."""
        from .. import problem_report

        request = getattr(self.chat, "last_request", "") or ""
        model = getattr(self, "last_run_model", "") or self.settings.ollama_model
        messages = [dict(m) for m in (self.conv.messages if self.conv else [])]
        settings, work = self.settings, self._work_dir()
        if card is None:
            self._notify("🐞 sorun raporu hazırlanıyor…", 60000)

        def work_():
            try:
                result = (problem_report.build(kind, detail, request, model, settings, messages, work, note), "")
            except Exception as e:  # rapor hazırlanamasa da program çalışmaya devam eder
                result = ("", f"{type(e).__name__}: {e}")
            QTimer.singleShot(0, self, lambda: self._report_built(*result, card))

        threading.Thread(target=work_, daemon=True).start()

    def _report_built(self, text: str, error: str, card):
        """Önizleme: kullanıcı raporu görür, istemediğini siler; kaydedince masaüstüne yazılır ve cümle panoya."""
        from .. import problem_report

        if error:
            card.failed(error) if card is not None else QMessageBox.warning(self, "Sorun raporu",
                                                                             f"Rapor hazırlanamadı: {error}")
            return
        dlg = ReportPreview(text, self)
        if not dlg.exec():
            if card is not None:
                card.cancelled()
            return
        try:
            path = str(problem_report.write(problem_report.redact(dlg.text())))  # sonradan yapıştırılan anahtar da
        except OSError as e:
            QMessageBox.warning(self, "Sorun raporu", f"Rapor kaydedilemedi: {e}")
            return
        prompt = problem_report.claude_prompt(Path(path))
        if card is not None:
            card.done(path, prompt)
            return
        QApplication.clipboard().setText(prompt)
        self._notify("🐞 sorun raporu hazır; Claude Code'a verilecek cümle panoda", 15000)
        box = QMessageBox(self)
        box.setWindowTitle("Sorun raporu hazır")
        box.setText(f"Rapor masaüstüne kaydedildi:\n{path}\n\nClaude Code'a verilecek cümle panoya kopyalandı; "
                    "Claude Code'a yapıştırman yeterli.")
        box.addButton("Tamam", QMessageBox.AcceptRole)
        folder = box.addButton("Klasörü aç", QMessageBox.ActionRole)
        box.exec()
        if box.clickedButton() is folder:
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(Path(path).parent)))

    def _report_dialog(self):
        """Yardım → Sorun bildir: kullanıcı ne olduğunu anlatır, son sohbetle birlikte rapor hazırlanır."""
        text, ok = QInputDialog.getMultiLineText(
            self, "Sorun bildir", "Ne oldu, ne bekliyordun? (Son sohbet ve sistem bilgisi rapora kendiliğinden "
            "eklenir; API anahtarları gizlenir.)")
        if ok and text.strip():
            self._make_report("kullanici", "", note=text.strip())

    # ---- güncellemeler (updates.py): yalnızca yayımlanan resmi sürüm; program kendi kodunu yazmaz
    def schedule_update_check(self):
        """Açılıştan 30 sn sonra, günde en çok bir kez sessiz denetim (yeni sürüm varsa haber verir)."""
        from .. import updates

        last = float(self.settings.extra.get("guncelleme_denetimi", 0) or 0)
        if not self.settings.extra.get("guncelleme_otomatik", True):  # Ayarlar'dan kapatıldı (menüden elle denetlenir)
            return
        if updates.enabled()[0] and time.time() - last > updates.CHECK_EVERY:
            QTimer.singleShot(30000, lambda: self._check_updates(quiet=True))

    def _check_updates(self, quiet: bool = True):
        from .. import updates

        ok, why = updates.enabled()
        if not ok:
            if not quiet:
                QMessageBox.information(self, "Güncellemeler", why)
            return

        def work():
            try:
                info, error = updates.latest(), ""
            except Exception as e:
                info, error = None, f"{type(e).__name__}: {e}"
            QTimer.singleShot(0, self, lambda: self._update_checked(info, error, quiet))

        threading.Thread(target=work, daemon=True).start()

    def _update_checked(self, info, error: str, quiet: bool):
        from .. import __version__, updates

        if not error:
            self.settings.extra["guncelleme_denetimi"] = time.time()
            self.settings.save()
        if updates.newer(info):
            self.update_action.setText(f"⬆ Güncelleme var: {info['version']}…")
            if quiet:
                self._notify(f"⬆ YENİ NESİL CAFER {info['version']} hazır — Yardım → Güncelleme var", 30000)
                return
            self._update_dialog(info)
        elif not quiet:
            QMessageBox.information(self, "Güncellemeler", f"Denetlenemedi: {error}" if error else
                                    f"En güncel sürümü kullanıyorsun ({__version__}).")

    def _update_dialog(self, info: dict):
        from .. import __version__

        box = QMessageBox(self)
        box.setWindowTitle("Güncelleme var")
        box.setTextFormat(Qt.MarkdownText)
        box.setText(f"**YENİ NESİL CAFER {info['version']}** hazır (şu an {__version__}); indirilecek: "
                    f"{info['size'] / 1e6:.1f} MB.\n\nKurmadan önce şimdiki sürüm yedeklenir; yeni sürüm açılamazsa "
                    "kendiliğinden geri dönülür. Program yeniden başlar.\n\n" + (info["notes"][:1500] or ""))
        go = box.addButton("Güncelle ve yeniden başlat", QMessageBox.AcceptRole)
        box.addButton("Sonra", QMessageBox.RejectRole)
        box.exec()
        if box.clickedButton() is go:
            if self.worker is not None:
                QMessageBox.information(self, "Güncelleme", "Asistan şu an çalışıyor; iş bitince yeniden dene.")
                return
            self._install_update(info)

    def _install_update(self, info: dict):
        from .. import updates

        self._notify("⬆ güncelleme indiriliyor…", 120000)

        def work():
            try:
                package = updates.download(info, progress=lambda p: QTimer.singleShot(
                    0, self, lambda: self._notify(f"⬆ güncelleme indiriliyor… %{p}", 120000)))
                updates.apply(package, info["version"])
                error = ""
            except Exception as e:
                error = str(e)
            QTimer.singleShot(0, self, lambda: self._update_installed(error))

        threading.Thread(target=work, daemon=True).start()

    def _update_installed(self, error: str):
        if error:
            QMessageBox.warning(self, "Güncelleme kurulamadı", f"{error}\n\nŞimdiki sürüm olduğu gibi duruyor.")
            return
        import subprocess
        import sys

        from ..updates import PROGRAM_DIR

        flags = subprocess.CREATE_NEW_PROCESS_GROUP | subprocess.DETACHED_PROCESS if sys.platform == "win32" else 0
        subprocess.Popen([sys.executable, *(["-X", "utf8"] if sys.platform == "win32" else []), str(PROGRAM_DIR / "main.py")], cwd=str(PROGRAM_DIR), creationflags=flags,
                         start_new_session=sys.platform != "win32")
        QApplication.quit()

    # ---- tanıtım (tour.py): ilk kurulumda ve her yeni sürümde bir kez
    def show_tour_if_new(self):
        from . import tour

        items = tour.pending(self.settings)
        if not items:
            return
        tour.mark_seen(self.settings)  # kapatılsa da bir daha çıkmasın
        tour.TourDialog(items, lambda name: getattr(self, name)(), self).exec()

    def _open_results(self):
        """Masaüstündeki YENİ NESİL CAFER/Sonuçlar: işlerin görselleri, 3D modelleri, belgeleri (results.py)."""
        from .. import results

        folder = results.results_dir()
        folder.mkdir(parents=True, exist_ok=True)
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(folder)))

    def _tour_media(self):
        self._show_tab(self.right.media)

