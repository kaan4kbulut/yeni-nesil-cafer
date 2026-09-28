"""Yetenekler penceresi (K5): görev motorunun planlayıcısının çağırabildiği yetenekler — aktif mi (değilse neden),
izinleri, kaynağı, güvenilir mi, sandbox'ta mı çalışır.

Sağ panele sekme açılmaz (CLAUDE.md: sağ panel üç sekme; SORULAR K4/K5/K7): ayrı pencere, Yardım → Yetenekler. Liste
yalnızca manifestlerden (`cekirdek/yetenek/kayit.py`) okunur; pencere hiçbir şey kurmaz, çalıştırmaz, değiştirmez.
"""

import html

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QDialog, QHBoxLayout, QHeaderView, QLabel, QPushButton, QSplitter, QTableWidget, QTableWidgetItem, QTextBrowser,
    QVBoxLayout,
)

from ..cekirdek.yetenek.kayit import Kayit

COLUMNS = ["Yetenek", "Durum", "İzinler", "Kaynak", "Güvenilir", "Çalışma"]
IZIN_ADI = {"ag": "internet", "dosya_oku": "dosya okur", "dosya_yaz": "dosya yazar", "dosya_sil": "dosya siler",
            "komut": "komut / kod çalıştırır"}
KAYNAK_ADI = {"yerlesik": "yerleşik", "katalog": "katalog", "uretildi": "üretildi"}


def izin_metni(izinler: list[str]) -> str:
    adlar = [IZIN_ADI.get(i, i.replace("anahtar:", "anahtar: ")) for i in izinler]
    return ", ".join(adlar) or "yok"


class YeteneklerDialog(QDialog):
    def __init__(self, parent=None, kayit: Kayit | None = None):
        super().__init__(parent)
        self.setWindowTitle("Yetenekler")
        self.setMinimumSize(900, 520)
        self.kayit = kayit or Kayit()
        self.items: list[dict] = []

        lay = QVBoxLayout(self)
        lay.setContentsMargins(20, 16, 20, 14)
        intro = QLabel(
            "Görev motoru bir işi planlarken <b>yalnızca buradaki aktif yetenekleri</b> kullanabilir. Pasif bir "
            "yetenek kayıtlıdır ama şu an çalışamaz (nedeni yanında). Programla gelmeyen ya da güvenilir olmayan "
            "yetenekler kapalı bir alanda (sandbox) çalışır ve her seferinde onay ister.", objectName="hint")
        intro.setWordWrap(True)
        lay.addWidget(intro)

        split = QSplitter(Qt.Vertical)
        self.table = QTableWidget(0, len(COLUMNS))
        self.table.setHorizontalHeaderLabels(COLUMNS)
        self.table.verticalHeader().setVisible(False)
        self.table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.table.setSelectionBehavior(QTableWidget.SelectRows)
        self.table.setSelectionMode(QTableWidget.SingleSelection)
        head = self.table.horizontalHeader()
        head.setSectionResizeMode(QHeaderView.ResizeToContents)
        head.setSectionResizeMode(2, QHeaderView.Stretch)
        self.table.itemSelectionChanged.connect(self._show)
        split.addWidget(self.table)
        self.detail = QTextBrowser()
        self.detail.setOpenExternalLinks(False)
        split.addWidget(self.detail)
        split.setSizes([300, 220])
        lay.addWidget(split, 1)

        row = QHBoxLayout()
        self.status = QLabel(objectName="hint")
        row.addWidget(self.status, 1)
        refresh = QPushButton("Yenile", objectName="smallButton", toolTip="Yetenek klasörlerini yeniden tara")
        refresh.clicked.connect(self._refresh)
        close = QPushButton("Kapat", objectName="smallButton")
        close.clicked.connect(self.accept)
        row.addWidget(refresh)
        row.addWidget(close)
        lay.addLayout(row)
        self._refresh()

    def _refresh(self) -> None:
        try:
            self.kayit.yenile()
            self.items = self.kayit.listele()
        except Exception as e:  # tarama bozulsa da pencere açılsın
            self.items = []
            self.status.setText(f"Yetenekler okunamadı: {e}")
            return
        self.table.setRowCount(len(self.items))
        for r, y in enumerate(self.items):
            cells = [y["ad"], "✓ aktif" if y["aktif"] else "○ pasif", izin_metni(y["izinler"]),
                     KAYNAK_ADI.get(y["kaynak"], y["kaynak"] or "?"), "evet" if y["guvenilir"] else "hayır",
                     "sandbox" if y["sandbox"] else "program içinde"]
            for c, text in enumerate(cells):
                item = QTableWidgetItem(text)
                if c == 1 and not y["aktif"]:
                    item.setToolTip(y["neden"])
                self.table.setItem(r, c, item)
        aktif = sum(y["aktif"] for y in self.items)
        self.status.setText(f"{aktif} aktif · {len(self.items) - aktif} pasif")
        if self.items:
            self.table.selectRow(0)
        self._show()

    def _show(self) -> None:
        rows = self.table.selectionModel().selectedRows() if self.table.selectionModel() else []
        if not rows or rows[0].row() >= len(self.items):
            self.detail.setHtml("")
            return
        y = self.items[rows[0].row()]
        e = html.escape
        parts = [f"<h3>{e(y['ad'])} <small>{e(y['surum'])}</small></h3>", f"<p>{e(y['aciklama'])}</p>"]
        if not y["aktif"]:
            parts.append(f"<p><b>Pasif:</b> {e(y['neden'])}</p>")
        if y["girdi"]:
            parts.append("<p><b>Girdi:</b></p><ul>" + "".join(
                f"<li><code>{e(ad)}</code> ({e(a.get('tip', '?'))}{', zorunlu' if a.get('zorunlu') else ''})"
                f" — {e(a.get('aciklama', ''))}</li>" for ad, a in y["girdi"].items()) + "</ul>")
        parts.append(f"<p><b>İzinler:</b> {e(izin_metni(y['izinler']))} · <b>En az kademe:</b> "
                     f"{e(y['min_kademe'])}</p>")
        if y["ornekler"]:
            parts.append("<p><b>Örnekler:</b></p><ul>" + "".join(
                f"<li><code>{e(str(o['girdi']))}</code> → {e(o['beklenen'])}</li>" for o in y["ornekler"]) + "</ul>")
        if y["hatalar"]:
            parts.append("<p><b>Manifest hataları:</b></p><ul>" + "".join(
                f"<li>{e(h)}</li>" for h in y["hatalar"][:8]) + "</ul>")
        parts.append(f"<p style='color:gray'>{e(y['klasor'])}</p>")
        self.detail.setHtml("".join(parts))
