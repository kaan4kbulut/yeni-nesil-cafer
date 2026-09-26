"""Model kartları penceresi: her yerel modelin programın kendi sınavındaki sonucu ve "yeniden sına" düğmesi."""

import threading
import time

from PySide6.QtCore import QObject, Qt, Signal
from PySide6.QtWidgets import (
    QDialog, QHBoxLayout, QHeaderView, QLabel, QPushButton, QTableWidget, QTableWidgetItem, QVBoxLayout,
)

from .. import cards
from .theme import C

COLUMNS = ["Model", "Araç", "Plan", "Türkçe", "Hız", "Boyut", "Görme", "Sansürsüz", "Sınandı"]


class _Bridge(QObject):
    progress = Signal(str)
    done = Signal(str)


class CardsDialog(QDialog):
    def __init__(self, ollama_url: str, parent=None):
        super().__init__(parent)
        self.url = ollama_url
        self.setWindowTitle("Model kartları")
        self.setMinimumSize(900, 460)
        self.bridge = _Bridge()
        self.bridge.progress.connect(lambda text: self.status.setText(text))
        self.bridge.done.connect(self._done)
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

        lay = QVBoxLayout(self)
        lay.setContentsMargins(20, 16, 20, 14)
        intro = QLabel(
            "Program her yerel modeli kendi kısa sınavından geçirir; model seçimi üreticinin beyanına değil bu "
            "sonuçlara dayanır. <b>Araç</b>: dosya yazma, Python ile hesap, yaz-ve-kaydet görevlerinde gerçekten araç "
            "çağırdı mı. <b>Plan</b>: yöneticinin iş planını çıkarabiliyor mu. Hız bu bilgisayarda ölçülmüştür. "
            "Araç sınavını geçemeyen modelle sohbet ederken işi, geçen bir model yapar.", objectName="hint")
        intro.setWordWrap(True)
        lay.addWidget(intro)
        self.table = QTableWidget(0, len(COLUMNS))
        self.table.setHorizontalHeaderLabels(COLUMNS)
        self.table.verticalHeader().setVisible(False)
        self.table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.table.setSelectionMode(QTableWidget.NoSelection)
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.Stretch)
        for i in range(1, len(COLUMNS)):
            self.table.horizontalHeader().setSectionResizeMode(i, QHeaderView.ResizeToContents)
        lay.addWidget(self.table, 1)
        row = QHBoxLayout()
        self.status = QLabel(objectName="hint")
        row.addWidget(self.status, 1)
        self.missing_btn = QPushButton("Eksikleri sına", objectName="smallButton",
                                       toolTip="Kartı olmayan ya da güncellenmiş modelleri sınar")
        self.all_btn = QPushButton("Hepsini yeniden sına", objectName="smallButton",
                                   toolTip="Her model birkaç saniye ile yarım dakika sürer")
        self.missing_btn.clicked.connect(lambda: self._start(False))
        self.all_btn.clicked.connect(lambda: self._start(True))
        row.addWidget(self.missing_btn)
        row.addWidget(self.all_btn)
        lay.addLayout(row)
        self._fill()

    def _fill(self):
        all_cards = cards.load_cards()
        models = cards.installed(self.url)
        self.table.setRowCount(len(models))
        good, bad = C["success"], C["error"]
        for r, m in enumerate(sorted(models, key=lambda m: m["params"] or 99)):
            c = all_cards.get(m["name"])
            fresh = cards.valid(c, m["digest"])
            if not c or not fresh:
                cells = [(m["name"], None), ("sınanmadı" if not c else "yeniden sınanacak", C["muted"])] + \
                        [("", None)] * (len(COLUMNS) - 2)
            elif c.get("error"):
                cells = [(m["name"], None), ("hata", bad)] + [("", None)] * (len(COLUMNS) - 3) + \
                        [(c["error"][:60], C["muted"])]
            else:
                tools = c.get("tools", 0)
                cells = [
                    (m["name"], None),
                    (f"{cards.TOOL_WORDS[tools]} ({c.get('tools_passed', 0)}/{c.get('tools_total', 0)})",
                     good if tools == 2 else C["warn"] if tools == 1 else bad),
                    ("✓" if c.get("plan") else "✗", good if c.get("plan") else bad),
                    ("✓" if c.get("turkish") else "✗", good if c.get("turkish") else bad),
                    (f"{c.get('tps', 0):.0f} token/sn", None),
                    (f"{m['params']:g}B" if m["params"] else "?", None),
                    ("✓" if c.get("vision") else "", None),
                    ("🔓" if c.get("uncensored") else "", None),
                    (time.strftime("%d.%m %H:%M", time.localtime(c.get("measured", 0))), C["muted"]),
                ]
            for col, (text, color) in enumerate(cells):
                item = QTableWidgetItem(text)
                if color:
                    item.setForeground(_qcolor(color))
                if col == 1 and c and not c.get("error") and c.get("declared_tools") and not c.get("tools"):
                    item.setToolTip("Ollama bu modelin araç desteği olduğunu söylüyor, ama sınavda hiç araç çağırmadı "
                                    "(işi yapmak yerine anlatıyor).")
                self.table.setItem(r, col, item)
        todo = len(cards.missing(self.url))
        self.status.setText(f"{todo} model sınav bekliyor." if todo else "Bütün modellerin kartı güncel.")

    def _start(self, force: bool):
        if self._thread and self._thread.is_alive():
            return
        self.missing_btn.setEnabled(False)
        self.all_btn.setEnabled(False)
        self._stop.clear()

        def work():
            try:
                done = cards.measure_missing(
                    self.url, force=force, cancelled=self._stop.is_set,
                    on_progress=lambda i, n, m: self.bridge.progress.emit(f"🧪 sınanıyor {i}/{n} · {m}…"))
                self.bridge.done.emit(f"{len(done)} model sınandı." if done else "Sınanacak model yok.")
            except InterruptedError:
                self.bridge.done.emit("Durduruldu.")
            except Exception as e:  # Ollama kapalı vb.
                self.bridge.done.emit(f"Sınav yapılamadı: {e}")

        self._thread = threading.Thread(target=work, daemon=True)
        self._thread.start()

    def _done(self, text: str):
        self._fill()
        self.status.setText(text)
        self.missing_btn.setEnabled(True)
        self.all_btn.setEnabled(True)

    def done(self, result):  # pencere kapanınca süren sınav durur (bir sonraki boş anda kaldığı yerden sürer)
        self._stop.set()
        super().done(result)


def _qcolor(hex_color: str):
    from PySide6.QtGui import QColor

    return QColor(hex_color)
