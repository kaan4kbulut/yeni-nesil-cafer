"""Hafıza ve öğrenme penceresi: asistanın hafızası, beceri kütüphanesi ve gelişim raporu.

Kullanıcı her şeyi görür ve silebilir. Program kendi kodunu kendiliğinden değiştirmez: gelişim raporundaki
öneriler ancak kullanıcı isterse Claude Code'a verilir (Claude Code da her değişiklik için onay ister).
"""

import os
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QApplication, QComboBox, QDialog, QHBoxLayout, QLabel, QLineEdit, QListWidget, QListWidgetItem, QMessageBox,
    QPlainTextEdit, QPushButton, QTabWidget, QTextBrowser, QVBoxLayout, QWidget,
)

from .. import learning, memory_db, sysinfo


def program_dir(settings) -> str:
    """Geliştirilecek kod: ayarlarda kaynak klasörü verildiyse o, yoksa kurulu programın klasörü."""
    return str(Path(settings.extra.get("dev_dir") or sysinfo.APP_DIR).expanduser())


def claude_cli() -> str:
    return shutil.which("claude") or ""


def open_in_claude_code(prompt: str, cwd: str) -> str:
    """Claude Code'u yeni bir terminal penceresinde, isteği verilmiş olarak açar (etkileşimli: her adımı sorar).

    Başarılıysa boş, değilse kullanıcıya gösterilecek hata metni döner."""
    exe = claude_cli()
    if not exe:
        return "Claude Code bulunamadı. Kurmak için: https://claude.com/claude-code"
    fd, path = tempfile.mkstemp(prefix="gelistirme-", suffix=".md")
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        f.write(prompt)
    if sys.platform == "win32":
        cmd = (f"Set-Location -LiteralPath '{cwd}'; & '{exe}' (Get-Content -Raw -LiteralPath '{path}')")
        subprocess.Popen(["powershell", "-NoExit", "-NoProfile", "-Command", cmd],
                         creationflags=subprocess.CREATE_NEW_CONSOLE)
        return ""
    script = Path(tempfile.mkstemp(prefix="gelistirme-", suffix=".sh")[1])
    script.write_text(f'cd "{cwd}" && "{exe}" "$(cat "{path}")"; exec bash\n', encoding="utf-8")
    for term, args in (("konsole", ["-e"]), ("gnome-terminal", ["--"]), ("kitty", []), ("alacritty", ["-e"]),
                       ("xfce4-terminal", ["-x"]), ("x-terminal-emulator", ["-e"]), ("xterm", ["-e"])):
        if shutil.which(term):
            subprocess.Popen([term, *args, "bash", str(script)], start_new_session=True)
            return ""
    return "Terminal bulunamadı. Geliştirme talebini kopyalayıp Claude Code'a kendin yapıştırabilirsin."


def _when(ts: float) -> str:
    return time.strftime("%d.%m.%Y", time.localtime(ts or 0))


class LearningDialog(QDialog):
    def __init__(self, settings, make_report, parent=None):
        """make_report(): pencere kapanınca yeni sohbette gelişim raporu isteğini başlatır (pencere sağlar)."""
        super().__init__(parent)
        self.settings, self.make_report = settings, make_report
        self.setWindowTitle("Hafıza ve öğrenme")
        self.setMinimumSize(780, 600)
        outer = QVBoxLayout(self)
        outer.setContentsMargins(22, 18, 22, 14)
        intro = QLabel("Asistan sohbetlerden öğrendiklerini burada tutar. Hepsi yalnızca bu bilgisayarda saklanır; "
                       "istediğini silebilirsin. "
                       + (f"Arama anlam üzerinden yapılır ({memory_db.EMBED_MODEL})." if memory_db.semantic() else
                          memory_db.semantic_note()),
                       objectName="hint")
        intro.setWordWrap(True)
        outer.addWidget(intro)
        self.tabs = QTabWidget()
        self.tabs.addTab(self._memory_tab(), "Hafıza")
        self.tabs.addTab(self._skills_tab(), "Beceriler")
        self.tabs.addTab(self._recipes_tab(), "Tarifler")
        self.tabs.addTab(self._failures_tab(), "Başarısızlıklar")
        self.tabs.addTab(self._growth_tab(), "Gelişim")
        outer.addWidget(self.tabs, 1)
        close = QPushButton("Kapat", objectName="primary")
        close.clicked.connect(self.accept)
        outer.addWidget(close, 0, Qt.AlignRight)
        self._fill_memory()
        self._fill_skills()
        self._fill_failures()
        self._fill_growth()

    # ---- hafıza
    def _memory_tab(self) -> QWidget:
        w = QWidget()
        lay = QVBoxLayout(w)
        hint = QLabel("Tercihlerin, senin ve bu bilgisayar hakkındaki bilgiler, öğrenilen dersler. Her sohbette "
                      "asistana ve ekibine verilir. Asistana “bunu hatırla” diyerek de ekleyebilirsin.",
                      objectName="hint")
        hint.setWordWrap(True)
        lay.addWidget(hint)
        self.memory_list = QListWidget()
        self.memory_list.setWordWrap(True)
        lay.addWidget(self.memory_list, 1)
        row = QHBoxLayout()
        self.memory_kind = QComboBox()
        for key, name in learning.MEMORY_KINDS.items():
            self.memory_kind.addItem(name, key)
        self.memory_input = QLineEdit(placeholderText="ör. Raporları her zaman Excel olarak hazırla")
        self.memory_input.returnPressed.connect(self._add_memory)
        add = QPushButton("Ekle", objectName="smallButton")
        add.clicked.connect(self._add_memory)
        delete = QPushButton("Seçileni sil", objectName="smallButton")
        delete.clicked.connect(self._delete_memory)
        row.addWidget(self.memory_kind)
        row.addWidget(self.memory_input, 1)
        row.addWidget(add)
        row.addWidget(delete)
        lay.addLayout(row)
        return w

    def _fill_memory(self):
        self.memory_list.clear()
        items = learning.memories()
        for m in reversed(items):
            item = QListWidgetItem(f"[{learning.MEMORY_KINDS.get(m['kind'], 'Bilgi')}]  {m['text']}   · {_when(m['created'])}")
            item.setData(Qt.UserRole, m["id"])
            self.memory_list.addItem(item)
        if not items:
            self.memory_list.addItem("Henüz bir şey öğrenilmedi.")

    def _add_memory(self):
        text = self.memory_input.text().strip()
        if text:
            learning.remember(text, self.memory_kind.currentData())
            self.memory_input.clear()
            self._fill_memory()

    def _delete_memory(self):
        for item in self.memory_list.selectedItems():
            if item.data(Qt.UserRole):
                learning.forget(item.data(Qt.UserRole))
        self._fill_memory()

    # ---- beceriler
    def _skills_tab(self) -> QWidget:
        w = QWidget()
        lay = QVBoxLayout(w)
        hint = QLabel("✓ ile başlatılıp doğrulanarak biten işlerin çalışan yöntemi. Benzer bir istekte asistana "
                      "verilir, böylece sıfırdan denemek yerine işe yaradığı bilinen yolu kullanır.", objectName="hint")
        hint.setWordWrap(True)
        lay.addWidget(hint)
        self.skill_list = QListWidget()
        self.skill_list.currentItemChanged.connect(self._show_skill)
        lay.addWidget(self.skill_list, 1)
        self.skill_detail = QPlainTextEdit(readOnly=True)
        self.skill_detail.setMaximumHeight(200)
        lay.addWidget(self.skill_detail)
        delete = QPushButton("Seçileni sil", objectName="smallButton")
        delete.clicked.connect(self._delete_skill)
        lay.addWidget(delete, 0, Qt.AlignRight)
        return w

    def _fill_skills(self):
        self.skill_list.clear()
        self.skill_detail.clear()
        items = learning.skills()
        for s in sorted(items, key=lambda x: -x.get("updated", 0)):
            item = QListWidgetItem(f"{s['title']}   · {s.get('successes', 0)} başarılı"
                                   + (f", {s['failures']} başarısız" if s.get("failures") else "")
                                   + f" · {_when(s.get('updated'))}")
            item.setData(Qt.UserRole, s)
            self.skill_list.addItem(item)
        if not items:
            self.skill_list.addItem("Henüz beceri yok: ✓ ile başlattığın bir iş başarıyla bitince burada görünür.")

    def _show_skill(self, item):
        s = item.data(Qt.UserRole) if item else None
        if not s:
            self.skill_detail.clear()
            return
        text = f"İstek: {s['request']}\nModel: {s.get('model') or '?'}\n"
        if s.get("code"):
            text += f"\n--- çalışan kod ---\n{s['code']}\n"
        if s.get("steps"):
            text += "\n--- diğer adımlar ---\n" + "\n".join(f"{x['tool']}: {x['args']}" for x in s["steps"])
        self.skill_detail.setPlainText(text)

    def _delete_skill(self):
        item = self.skill_list.currentItem()
        if item and item.data(Qt.UserRole):
            learning.delete_skill(item.data(Qt.UserRole)["id"])
            self._fill_skills()

    # ---- tarifler (definitions.py: SKILL.md dosyaları; hazır · öğrenilen · kullanıcının)
    def _recipes_tab(self) -> QWidget:
        w = QWidget()
        lay = QVBoxLayout(w)
        hint = QLabel("Asistanın iş tarifleri. <b>hazır</b>: programla gelir (salt okunur) · <b>öğrenilen</b>: asistan "
                      "bir işi araştırıp başarınca kendisi kaydetti · <b>senin</b>: ~/.config/yeni-nesil-cafer/beceriler. "
                      "Asistan bir işe başlarken uygun tarifi okur; burada düzeltebilir ya da silebilirsin.",
                      objectName="hint")
        hint.setWordWrap(True)
        lay.addWidget(hint)
        self.recipe_list = QListWidget()
        self.recipe_list.currentItemChanged.connect(self._show_recipe)
        lay.addWidget(self.recipe_list, 1)
        self.recipe_text = QPlainTextEdit()
        self.recipe_text.setMinimumHeight(220)
        lay.addWidget(self.recipe_text, 2)
        row = QHBoxLayout()
        self.recipe_note = QLabel("", objectName="keyHint")
        self.recipe_save = QPushButton("Kaydet", objectName="smallButton")
        self.recipe_save.clicked.connect(self._save_recipe)
        self.recipe_delete = QPushButton("Sil", objectName="smallButton")
        self.recipe_delete.clicked.connect(self._delete_recipe)
        row.addWidget(self.recipe_note, 1)
        row.addWidget(self.recipe_save)
        row.addWidget(self.recipe_delete)
        lay.addLayout(row)
        self._fill_recipes()
        return w

    def _fill_recipes(self):
        from ..definitions import load_skills

        self.recipe_list.clear()
        self.recipe_text.clear()
        names = {"hazır": "hazır", "öğrenilen": "öğrenilen", "kullanıcı": "senin"}
        for s in sorted(load_skills(), key=lambda s: ({"öğrenilen": 0, "kullanıcı": 1}.get(s.source, 2), s.name)):
            item = QListWidgetItem(f"[{names.get(s.source, s.source)}]  {s.name} — {s.description}")
            item.setData(Qt.UserRole, s)
            self.recipe_list.addItem(item)
        self._show_recipe(None)

    def _show_recipe(self, item):
        s = item.data(Qt.UserRole) if item else None
        editable = bool(s) and s.source != "hazır"
        self.recipe_text.setPlainText(s.path.read_text(encoding="utf-8") if s else "")
        self.recipe_text.setReadOnly(not editable)
        self.recipe_save.setEnabled(editable)
        self.recipe_delete.setEnabled(editable)
        self.recipe_note.setText("" if not s else ("programla gelir; aynı adla kendi tarifini yazarak yerine "
                                                  "geçebilirsin" if s.source == "hazır" else str(s.path)))

    def _save_recipe(self):
        from ..definitions import save_skill_text

        item = self.recipe_list.currentItem()
        if not item:
            return
        try:
            save_skill_text(item.data(Qt.UserRole), self.recipe_text.toPlainText())
            self.recipe_note.setText("✓ kaydedildi")
        except ValueError as e:
            QMessageBox.warning(self, "Tarif", str(e))

    def _delete_recipe(self):
        from ..definitions import delete_skill_dir

        item = self.recipe_list.currentItem()
        if not item:
            return
        s = item.data(Qt.UserRole)
        if QMessageBox.question(self, "Tarifi sil", f"“{s.name}” silinsin mi?") != QMessageBox.Yes:
            return
        try:
            delete_skill_dir(s)
        except ValueError as e:
            QMessageBox.warning(self, "Tarif", str(e))
        self._fill_recipes()

    # ---- başarısızlıklar
    def _failures_tab(self) -> QWidget:
        w = QWidget()
        lay = QVBoxLayout(w)
        hint = QLabel("Yöneticinin tamamlatamadığı adımlar ve nedenleri. Benzer bir iş planlanırken yöneticiye "
                      "verilir, böylece aynı yolu tekrar denemek yerine başka bir yol seçer.", objectName="hint")
        hint.setWordWrap(True)
        lay.addWidget(hint)
        self.failure_list = QListWidget()
        self.failure_list.setWordWrap(True)
        lay.addWidget(self.failure_list, 1)
        delete = QPushButton("Seçileni sil", objectName="smallButton")
        delete.clicked.connect(self._delete_failure)
        lay.addWidget(delete, 0, Qt.AlignRight)
        return w

    def _fill_failures(self):
        self.failure_list.clear()
        items = learning.failures()
        for f in sorted(items, key=lambda x: -x.get("updated", 0)):
            item = QListWidgetItem(f"{f['text']}\n   {f.get('count', 1)} kez · model: {f.get('model') or '?'}"
                                   f" · istek: {f.get('request', '')[:80]} · {_when(f.get('updated'))}")
            item.setData(Qt.UserRole, f["id"])
            self.failure_list.addItem(item)
        if not items:
            self.failure_list.addItem("Henüz başarısız adım yok.")

    def _delete_failure(self):
        for item in self.failure_list.selectedItems():
            if item.data(Qt.UserRole):
                memory_db.delete(item.data(Qt.UserRole))
        self._fill_failures()

    # ---- gelişim
    def _growth_tab(self) -> QWidget:
        w = QWidget()
        lay = QVBoxLayout(w)
        self.growth_summary = QLabel(objectName="hint")
        self.growth_summary.setWordWrap(True)
        lay.addWidget(self.growth_summary)
        self.issue_list = QListWidget()
        self.issue_list.setWordWrap(True)
        self.issue_list.setMaximumHeight(170)
        lay.addWidget(self.issue_list)
        report_btn = QPushButton("Gelişim raporu hazırla", objectName="primary")
        report_btn.setToolTip("Sorunları asistana inceletir: neden oldu, sen ne yapabilirsin, programa ne eklenmeli. "
                              "Hiçbir şey değiştirilmez.")
        report_btn.clicked.connect(self._make_report)
        lay.addWidget(report_btn, 0, Qt.AlignLeft)
        lay.addWidget(QLabel("SON RAPOR", objectName="label"))
        self.report_view = QTextBrowser()
        lay.addWidget(self.report_view, 1)
        row = QHBoxLayout()
        copy = QPushButton("Geliştirme talebini kopyala", objectName="smallButton")
        copy.setToolTip("Rapordaki geliştirmeleri Claude Code'a (ya da bir geliştiriciye) vermek için hazır metin")
        copy.clicked.connect(self._copy_request)
        self.claude_btn = QPushButton("Claude Code ile geliştir…", objectName="smallButton")
        self.claude_btn.setToolTip("Claude Code yeni bir terminalde açılır; önce plan sunar, her değişiklik için "
                                   "senin onayını ister.")
        self.claude_btn.clicked.connect(self._open_claude)
        row.addWidget(copy)
        row.addWidget(self.claude_btn)
        row.addStretch(1)
        lay.addLayout(row)
        return w

    def _fill_growth(self):
        since = learning.last_report_time()
        new = learning.issues(since)
        recent = learning.issues()[-40:]
        self.growth_summary.setText(
            f"Tamamlanamayan, hata veren ya da beğenmediğin işler kaydedilir. Son rapordan bu yana: {len(new)} "
            f"sorun (toplam {len(learning.issues())}).")
        self.issue_list.clear()
        for item in reversed(recent):
            mark = "● " if item["time"] > since else "  "
            self.issue_list.addItem(f"{mark}{time.strftime('%d.%m %H:%M', time.localtime(item['time']))} · "
                                    f"{learning.ISSUE_NAMES.get(item['kind'], item['kind'])} · {item['request'][:110]}")
        if not recent:
            self.issue_list.addItem("Henüz bir sorun kaydı yok.")
        report = learning.last_report()
        self.report_view.setMarkdown(report or "_Henüz rapor hazırlanmadı._")
        has_report = bool(report.strip())
        self.claude_btn.setEnabled(has_report and bool(claude_cli()))
        if has_report and not claude_cli():
            self.claude_btn.setToolTip("Claude Code bu bilgisayarda kurulu değil. Talebi kopyalayıp bir "
                                       "geliştiriciye verebilirsin.")

    def _make_report(self):
        if not learning.issues():
            QMessageBox.information(self, "Gelişim raporu", "Henüz incelenecek bir sorun kaydı yok.")
            return
        self.accept()
        self.make_report()

    def _request_text(self) -> str:
        return learning.developer_request(learning.last_report(), program_dir(self.settings))

    def _copy_request(self):
        if not learning.last_report().strip():
            QMessageBox.information(self, "Gelişim raporu", "Önce bir gelişim raporu hazırla.")
            return
        QApplication.clipboard().setText(self._request_text())
        self.growth_summary.setText("Geliştirme talebi panoya kopyalandı.")

    def _open_claude(self):
        answer = QMessageBox.question(
            self, "Claude Code ile geliştir",
            f"Claude Code şu klasörde açılacak:\n{program_dir(self.settings)}\n\nÖnce bir plan sunacak ve her "
            "değişiklik için senin onayını isteyecek. Başlatılsın mı?")
        if answer != QMessageBox.Yes:
            return
        error = open_in_claude_code(self._request_text(), program_dir(self.settings))
        if error:
            QMessageBox.warning(self, "Claude Code", error)
