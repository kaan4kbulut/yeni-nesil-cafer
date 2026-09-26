"""Araç fabrikası penceresi: asistanın kullanıcı onayıyla eklediği araçlar, kodları ve silme."""

import time

from PySide6.QtCore import Qt, QUrl
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (
    QDialog, QHBoxLayout, QLabel, QListWidget, QListWidgetItem, QMessageBox, QPlainTextEdit, QPushButton,
    QVBoxLayout,
)

from .. import factory


class FactoryDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Araç fabrikası")
        self.setMinimumSize(820, 600)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(20, 16, 20, 14)
        intro = QLabel(
            "Asistanın elinde olmayan bir yetenek gerektiğinde (ör. bir dosya biçimini dönüştürmek) araç fabrikası "
            "önce hazır bir çözüm arar, yoksa aracı yazar, internetsiz bir sandbox'ta test eder ve eklemeden önce sana "
            "sorar. Eklenen araçlar burada; her çalıştırılışları yine güvenlik ajanı ya da sen denetlersin. Her ekleme "
            "ve silme git ile kaydedilir.", objectName="hint")
        intro.setWordWrap(True)
        lay.addWidget(intro)
        self.list = QListWidget()
        self.list.currentItemChanged.connect(self._show)
        lay.addWidget(self.list, 1)
        self.code = QPlainTextEdit(readOnly=True, objectName="preview")
        self.code.setMinimumHeight(220)
        lay.addWidget(self.code, 1)
        row = QHBoxLayout()
        folder = QPushButton("Klasörü aç", objectName="smallButton")
        folder.clicked.connect(lambda: QDesktopServices.openUrl(QUrl.fromLocalFile(str(factory.TOOLS_DIR))))
        delete = QPushButton("Seçili aracı sil", objectName="smallButton")
        delete.clicked.connect(self._delete)
        row.addWidget(folder)
        row.addStretch()
        row.addWidget(delete)
        lay.addLayout(row)
        self._fill()

    def _fill(self):
        self.list.clear()
        self.code.clear()
        items = factory.tools()
        for t in items:
            when = time.strftime("%d.%m.%Y", time.localtime(t.get("created", 0)))
            item = QListWidgetItem(f"{t['name']}  —  {t['description'][:90]}   · {when}")
            item.setData(Qt.UserRole, t)
            self.list.addItem(item)
        if not items:
            self.list.addItem("Henüz eklenmiş araç yok. Asistan bir işi mevcut araçlarla yapamadığında burada görünür.")

    def _show(self, item):
        t = item.data(Qt.UserRole) if item else None
        if not t:
            self.code.clear()
            return
        head = (f"# {t['name']}\n# ihtiyaç: {t.get('need', '')}\n# yazan model: {t.get('model', '?')}\n"
                f"# kütüphaneler: {', '.join(t.get('packages') or []) or '-'}\n\n")
        self.code.setPlainText(head + t.get("code", ""))

    def _delete(self):
        item = self.list.currentItem()
        t = item.data(Qt.UserRole) if item else None
        if t and QMessageBox.question(self, "Aracı sil", f"{t['name']} silinsin mi?") == QMessageBox.Yes:
            factory.remove(t["name"])
            self._fill()
