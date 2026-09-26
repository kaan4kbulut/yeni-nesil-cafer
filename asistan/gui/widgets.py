"""Tasarımın ortak parçaları: işaretli satır düğmesi (› sohbet  1), arama kutusu."""

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QLineEdit, QPushButton

from .theme import C


class RowButton(QPushButton):
    """[işaret] metin ............ [kısayol] — işaret vurgu renginde; `checkable` ise yalnızca seçiliyken görünür."""

    def __init__(self, text: str, key: str = "", marker: str = "", object_name: str = "navRow",
                 checkable: bool = False, marker_always: bool = False):
        super().__init__(objectName=object_name)
        self.setCheckable(checkable)
        self.setCursor(Qt.PointingHandCursor)
        self.marker_char, self.marker_always = marker, marker_always
        row = QHBoxLayout(self)
        row.setContentsMargins(10, 0, 10, 0)
        row.setSpacing(10)
        self.marker = QLabel(marker)
        self.marker.setFixedWidth(8)
        self.marker.setStyleSheet(f"color: {C['accent']}; background: transparent;")
        self.label = QLabel(text)
        self.label.setStyleSheet("background: transparent; color: inherit;")
        self.key = QLabel(key, objectName="keyHint")
        for w in (self.marker, self.label, self.key):
            w.setAttribute(Qt.WA_TransparentForMouseEvents)
        row.addWidget(self.marker)
        row.addWidget(self.label, 1)
        row.addWidget(self.key)
        self.toggled.connect(self._sync)
        self._sync(self.isChecked())

    def _sync(self, checked: bool):
        show = self.marker_always or not self.isCheckable() or checked
        self.marker.setText(self.marker_char if show else "")
        self.label.setStyleSheet(f"background: transparent; color: {C['text'] if checked or not self.isCheckable() and self.objectName() == 'outlineRow' else C['text2']};")

    def setText(self, text: str):  # noqa: N802 — Qt adı
        if hasattr(self, "label"):
            self.label.setText(text)
        else:
            super().setText(text)

    def text(self) -> str:
        return self.label.text() if hasattr(self, "label") else super().text()

    def set_key(self, key: str):
        self.key.setText(key)


class SearchBox(QFrame):
    """/ ara ............ Ctrl+K"""

    textChanged = Signal(str)

    def __init__(self, placeholder: str = "ara", key: str = "Ctrl+K"):
        super().__init__(objectName="searchBox")
        self.setStyleSheet(f"#searchBox {{ background: {C['bg']}; border: 1px solid {C['border']}; border-radius: 3px; }}")
        row = QHBoxLayout(self)
        row.setContentsMargins(10, 0, 10, 0)
        row.setSpacing(10)
        slash = QLabel("/", objectName="keyHint")
        slash.setFixedWidth(8)
        self.edit = QLineEdit(placeholderText=placeholder)
        self.edit.setStyleSheet("background: transparent; border: none; padding: 0; font-family: 'IBM Plex Mono'; font-size: 12.5px;")
        self.edit.setMinimumHeight(32)
        self.edit.textChanged.connect(self.textChanged)
        row.addWidget(slash)
        row.addWidget(self.edit, 1)
        row.addWidget(QLabel(key, objectName="keyHint"))

    def text(self) -> str:
        return self.edit.text()

    def setFocus(self):  # noqa: N802
        self.edit.setFocus()
        self.edit.selectAll()
