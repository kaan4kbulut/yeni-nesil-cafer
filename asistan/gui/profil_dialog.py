"""Donanım profili penceresi: durum çubuğundaki kademe düğmesi açar. Özet, bu kademede kapalı özellikler, kilit.

Ölçüm ve kademe kararı çekirdekte (`cekirdek/profil.py`); pencere yalnızca gösterir ve kilidi yazar.
"""

from PySide6.QtWidgets import QComboBox, QDialog, QHBoxLayout, QLabel, QPlainTextEdit, QPushButton, QVBoxLayout

from ..cekirdek import profil
from .sidebar import run_in_background
from .theme import mono


class ProfileDialog(QDialog):
    def __init__(self, parent=None, on_change=None):
        super().__init__(parent)
        self.on_change = on_change  # kademe değişince ana pencere durum çubuğunu yeniler
        self.setWindowTitle("Donanım profili ve kademe")
        self.setMinimumSize(640, 460)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(20, 16, 20, 14)
        intro = QLabel(
            "Program açılışta bu bilgisayarı ölçer ve bir <b>kademe</b> seçer: düşük · orta · yüksek · sunucu. "
            "Kademe, hangi modellerin önerileceğini ve ağır özelliklerin (anlamca arama, tarayıcı otomasyonu, "
            "uzun bağlam) açık olup olmadığını belirler. Ölçüm yanlışsa kademeyi elle kilitleyebilirsin; kilit "
            "ölçümü ezer.", objectName="hint")
        intro.setWordWrap(True)
        lay.addWidget(intro)
        self.text = QPlainTextEdit(readOnly=True)
        self.text.setFont(mono(10))
        lay.addWidget(self.text, 1)
        row = QHBoxLayout()
        row.addWidget(QLabel("Kademe:"))
        self.combo = QComboBox()
        self.combo.addItem("otomatik (ölçülen)", None)
        for k in profil.KADEMELER:
            self.combo.addItem(f"{profil.ADLAR[k]} — kilitli", k)
        row.addWidget(self.combo, 1)
        self.remeasure = QPushButton("Yeniden ölç", objectName="smallButton")
        row.addWidget(self.remeasure)
        close = QPushButton("Kapat", objectName="smallButton")
        row.addWidget(close)
        lay.addLayout(row)
        self.lock_hint = QLabel(objectName="hint")
        self.lock_hint.setWordWrap(True)
        lay.addWidget(self.lock_hint)
        self.combo.activated.connect(self._lock_changed)
        self.remeasure.clicked.connect(self._measure)
        close.clicked.connect(self.accept)
        self._show(profil.yukle())
        if profil.yukle() is None:
            self._measure()

    def _show(self, p: dict | None):
        self.text.setPlainText(profil.ozet(p) if p else "Ölçülüyor…")
        locked = profil.kilit()
        self.combo.setCurrentIndex(self.combo.findData(locked) if locked else 0)
        from_file = profil.kilit_kaynagi() == "dosya"
        self.combo.setEnabled(not from_file)
        self.lock_hint.setText("Kademe ayar.toml (genel.kademe_kilidi) ya da CAFER_GENEL_KADEME_KILIDI ile "
                               "kilitli; buradan değiştirilemez." if from_file else "")

    def _measure(self):
        self.remeasure.setEnabled(False)
        self.text.setPlainText("Ölçülüyor…")

        def done(p, error):
            self.remeasure.setEnabled(True)
            if error is not None:
                self.text.setPlainText(f"Ölçülemedi: {error}")
                return
            self._show(p)
            if self.on_change:
                self.on_change()

        run_in_background(lambda: profil.guncelle(sunucu=False), done, self)

    def _lock_changed(self, _index: int):
        profil.kilitle(self.combo.currentData())
        self._show(profil.yukle())
        if self.on_change:
            self.on_change()
