"""Ajan kategorileri penceresi: yedi alan, her birinin ajanları, atanan modeli, önerilen modeller ve ek araçlar.

Program kendiliğinden bir şey indirmez: önerilen model "indir", eksik kütüphane "kur" düğmesiyle kullanıcı
onayıyla kurulur."""

import threading

from PySide6.QtCore import QObject, Qt, Signal
from PySide6.QtWidgets import (
    QDialog, QFrame, QHBoxLayout, QLabel, QPushButton, QScrollArea, QVBoxLayout, QWidget,
)

from .. import categories, cli_agents, libraries, roster, specialists
from ..profiles import load_profiles
from .theme import C


class _Bridge(QObject):
    installed = Signal(str, str)  # (paket, hata metni ya da "")


class CategoriesDialog(QDialog):
    def __init__(self, settings, download_fn, parent=None):
        """download_fn(model, GB): pencerenin model indirme akışı (onay sorar, arka planda indirir)."""
        super().__init__(parent)
        self.settings, self.download_fn = settings, download_fn
        self.setWindowTitle("Ajan kategorileri")
        self.setMinimumSize(820, 680)
        self.bridge = _Bridge()
        self.bridge.installed.connect(self._installed)
        outer = QVBoxLayout(self)
        outer.setContentsMargins(20, 16, 20, 14)
        intro = QLabel(
            "Uzman ajanlar yedi alanda çalışır. Her alanın modelleri bu bilgisayara göre seçildi (12 GB ekran kartı "
            "belleği, 31 GB RAM): listedeki ilk kurulu ve araç sınavını geçen model o alanın ajanlarına verilir. "
            "Önerilen bir model kurulunca ajan kendiliğinden ona geçer.", objectName="hint")
        intro.setWordWrap(True)
        outer.addWidget(intro)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.inner = QWidget()
        self.rows = QVBoxLayout(self.inner)
        self.rows.setSpacing(10)
        scroll.setWidget(self.inner)
        outer.addWidget(scroll, 1)
        self.status = QLabel(objectName="hint")
        outer.addWidget(self.status)
        self._fill()

    def _fill(self):
        while self.rows.count():
            item = self.rows.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        installed = set(specialists.ollama_models(self.settings))
        have = {lib.name.lower() for lib in libraries.list_libraries()}
        from .. import sysinfo

        self.info = sysinfo.scan(self.settings.ollama_url)  # öneriler bu bilgisayara sığanlar
        profiles = {p.id: p for p in load_profiles()}
        for cat in categories.CATEGORIES:
            self.rows.addWidget(self._card(cat, installed, have, profiles))
        self.rows.addStretch()

    def _card(self, cat, installed: set, have: set, profiles: dict) -> QFrame:
        box = QFrame(objectName="catCard")
        box.setStyleSheet(f"#catCard {{ border: 1px solid {C['frame']}; border-radius: 8px; background: {C['surface']}; }}"
                          f" #catCard QLabel {{ background: transparent; }}")
        lay = QVBoxLayout(box)
        lay.setContentsMargins(14, 10, 14, 10)
        lay.setSpacing(5)
        title = QLabel(f"<b>{cat.name}</b>")
        lay.addWidget(title)
        covers = QLabel(cat.covers, objectName="hint")
        covers.setWordWrap(True)
        lay.addWidget(covers)
        agents = [profiles[a] for a in cat.agents if a in profiles]
        if agents:
            p = agents[0]
            provider, model = roster.assign(self.settings, p, ("", "—"))
            if cli_agents.is_cli(provider):
                model = cli_agents.label(provider, model)
            elif provider and provider != "ollama":
                model += " (bulut)"
            names = ", ".join(a.name for a in agents)
            lay.addWidget(QLabel(f"Ajanlar: {names}  ·  şu an çalışan model: <b>{model or '—'}</b>"))
        else:
            lay.addWidget(QLabel("Bu alanın ajanı silinmiş.", objectName="hint"))
        # önerilen modeller: kurulu ✓ / indir
        row = QHBoxLayout()
        row.setSpacing(6)
        row.addWidget(QLabel("Modeller:"))
        shown = categories.models_for(cat, self.info)
        shown += [m for m in cat.models if m in installed and m not in shown]  # kurulu olan hep görünür
        for m in shown:
            if m in installed:
                chip = QLabel(f"{m} ✓")
                chip.setStyleSheet(f"border: 1px solid {C['success']}; border-radius: 10px; padding: 2px 8px;")
                row.addWidget(chip)
            else:
                size = categories.SIZES.get(m, 0.0)
                btn = QPushButton(f"{m} · indir {size:.1f} GB", objectName="smallButton")
                btn.setCursor(Qt.PointingHandCursor)
                btn.clicked.connect(lambda _=False, m=m, size=size: self._download(m, size))
                row.addWidget(btn)
        row.addStretch()
        lay.addLayout(row)
        # ek araçlar (Python kütüphaneleri)
        if cat.extras:
            row = QHBoxLayout()
            row.setSpacing(6)
            row.addWidget(QLabel("Araçlar:"))
            for extra, ok in categories.extras_state(cat, have):
                if ok:
                    chip = QLabel(f"{extra.package} ✓")
                    chip.setToolTip(extra.note)
                    chip.setStyleSheet(f"border: 1px solid {C['success']}; border-radius: 10px; padding: 2px 8px;")
                    row.addWidget(chip)
                else:
                    btn = QPushButton(f"{extra.package} · kur", objectName="smallButton", toolTip=extra.note)
                    btn.setCursor(Qt.PointingHandCursor)
                    btn.clicked.connect(lambda _=False, pkg=extra.package, b=btn: self._install(pkg, b))
                    row.addWidget(btn)
            row.addStretch()
            lay.addLayout(row)
        if cat.limits:
            limits = QLabel(cat.limits, objectName="hint")
            limits.setWordWrap(True)
            limits.setStyleSheet(f"color: {C['muted']};")
            lay.addWidget(limits)
        return box

    def _download(self, model: str, size: float):
        self.download_fn(model, size)
        self.status.setText(f"{model} indiriliyor — durum alttaki çubukta; bitince ajan kendiliğinden ona geçer.")

    def _install(self, package: str, button: QPushButton):
        button.setEnabled(False)
        button.setText(f"{package} · kuruluyor…")
        self.status.setText(f"{package} kuruluyor (internet gerekir, bir-iki dakika sürebilir)…")

        def work():
            try:
                libraries.install(package)
                self.bridge.installed.emit(package, "")
            except Exception as e:
                self.bridge.installed.emit(package, str(e))

        threading.Thread(target=work, daemon=True).start()

    def _installed(self, package: str, error: str):
        self.status.setText(f"{package} kurulamadı: {error[:200]}" if error else f"{package} kuruldu ✓")
        self._fill()
