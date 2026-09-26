"""Model önerileri penceresi: sisteme ve yeteneklere göre yerel modeller (indir), bulutta ücretsiz kotalar ve
ücretli en iyi modeller (bağlan). Liste günde bir güncellenir (model_updates); "şimdi güncelle" ile hemen.
"""

import threading

from PySide6.QtCore import QObject, Qt, QUrl, Signal
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (
    QApplication, QDialog, QFrame, QHBoxLayout, QLabel, QProgressBar, QPushButton, QScrollArea, QVBoxLayout,
    QWidget,
)

from .. import catalog, model_updates, sysinfo
from .theme import C

# model_updates.CLOUD_VENDORS etiketi → catalog sağlayıcısı (bağlanmak için); Qwen bulutu OpenRouter üzerinden
VENDOR_PROVIDER = {"Anthropic · Claude": "anthropic", "OpenAI · GPT": "openai", "Google · Gemini": "google",
                   "xAI · Grok": "xai", "DeepSeek": "deepseek", "Mistral": "mistral", "Alibaba · Qwen": "openrouter"}


class _Bridge(QObject):
    progress = Signal(str, int, str)
    done = Signal(str, str)
    refreshed = Signal()


class ModelAdvisor(QDialog):
    def __init__(self, settings, connect_fn, parent=None):
        """connect_fn(sağlayıcı id): o firmaya bağlanma penceresini açar (pencere sağlar)."""
        super().__init__(parent)
        self.settings, self.connect_fn = settings, connect_fn
        self.setWindowTitle("Model önerileri")
        self.setMinimumSize(760, 640)
        self.bridge = _Bridge()
        self.bridge.progress.connect(self._on_progress)
        self.bridge.done.connect(self._on_done)
        self.bridge.refreshed.connect(self._refreshed)
        self.bars: dict[str, QProgressBar] = {}
        self.buttons: dict[str, QPushButton] = {}

        outer = QVBoxLayout(self)
        outer.setContentsMargins(22, 18, 22, 14)
        head = QHBoxLayout()
        self.summary = QLabel(objectName="hint")
        self.summary.setWordWrap(True)
        head.addWidget(self.summary, 1)
        self.refresh_btn = QPushButton("şimdi güncelle", objectName="smallButton")
        self.refresh_btn.clicked.connect(self._refresh)
        head.addWidget(self.refresh_btn, 0, Qt.AlignTop)
        outer.addLayout(head)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)  # uzun satırlar kayar, düğmeler görünür kalır
        inner = QWidget()
        self.rows = QVBoxLayout(inner)
        self.rows.setSpacing(4)
        scroll.setWidget(inner)
        outer.addWidget(scroll, 1)
        close = QPushButton("Kapat", objectName="primary")
        close.clicked.connect(self.accept)
        outer.addWidget(close, 0, Qt.AlignRight)
        self.info = sysinfo.scan(settings.ollama_url)
        self._fill()
        if model_updates.stale():
            self._refresh()

    # ---- yardımcılar
    def _section(self, title: str, hint: str = ""):
        label = QLabel(title, objectName="label")
        label.setContentsMargins(0, 14, 0, 2)
        self.rows.addWidget(label)
        if hint:
            h = QLabel(hint, objectName="keyHint")
            h.setWordWrap(True)
            self.rows.addWidget(h)

    def _row(self, text: str, sub: str = "", buttons: list[tuple[str, object]] = (), key: str = "") -> QFrame:
        row = QFrame(objectName="agentRow")
        col = QVBoxLayout(row)
        col.setContentsMargins(10, 6, 8, 6)
        col.setSpacing(2)
        line = QHBoxLayout()
        label = QLabel(text)
        label.setTextFormat(Qt.RichText)
        label.setWordWrap(True)
        label.setMinimumWidth(1)
        line.addWidget(label, 1)
        for caption, fn in buttons:
            if fn is None:
                line.addWidget(QLabel(caption, objectName="keyHint"))
                continue
            b = QPushButton(caption, objectName="smallButton")
            b.clicked.connect(fn)
            line.addWidget(b)
            if key:
                self.buttons[key] = b
        col.addLayout(line)
        if sub:
            s = QLabel(sub, objectName="keyHint")
            s.setWordWrap(True)
            col.addWidget(s)
        if key:
            bar = QProgressBar()
            bar.setFixedHeight(3)
            bar.setTextVisible(False)
            bar.hide()
            col.addWidget(bar)
            self.bars[key] = bar
        self.rows.addWidget(row)
        return row

    def _note(self, text: str):
        label = QLabel(text, objectName="keyHint")
        label.setWordWrap(True)
        label.setMinimumWidth(1)
        self.rows.addWidget(label)

    def _clear(self):
        while self.rows.count():
            item = self.rows.takeAt(0)
            if item.widget():
                item.widget().hide()
                item.widget().deleteLater()
        self.bars.clear()
        self.buttons.clear()

    # ---- içerik
    def _fill(self):
        self._clear()
        live = model_updates.load()
        info = self.info
        age = model_updates.age_hours()
        when = "hiç güncellenmedi — programla gelen liste" if age is None else (
            "az önce güncellendi" if age < 1 else f"{age:.0f} saat önce güncellendi")
        gpu = f"{info.gpu} {info.vram_gb:.0f} GB" if info.gpu else "ayrı ekran kartı yok"
        self.summary.setText(f"Sistemin: {gpu} · {info.ram_gb:.0f} GB RAM · {info.disk_free_gb:.0f} GB boş disk.  "
                             f"Liste her gün internetten güncellenir ({when}).")

        text, suggestions = sysinfo.recommend(info, live)
        self._section("YEREL — ÜCRETSİZ, BİLGİSAYARINDA", text)
        for sug in suggestions:
            have = sug.model in info.ollama_models
            alt = "↳ seçenek · " if sug.alternative else ""
            buttons = [("kurulu ✓", None)] if have else (
                [("Ollama çalışmıyor", None)] if not info.ollama_running else [("indir", lambda _=False, m=sug.model: self._pull(m))])
            self._row(f"{alt}<b>{sug.model}</b>&nbsp;&nbsp;<span style='color:{C['text2']}'>{sug.title} · "
                      f"{sug.size:.1f} GB</span>", sug.note, buttons, key=sug.model)
        # sisteme uygun ama önerilenlerin dışında kalan daha büyük modeller: bilgi
        heavy = []
        for kind, ladder in ((live or {}).get("local") or {}).items():
            heavy += [m for m, size, _ in ladder if not sysinfo.fits(info, size) and size <= info.ram_gb]
        if heavy:
            names = ", ".join(dict.fromkeys(heavy[:6]))
            self._note(f"Sistemine ağır gelir (yavaş çalışır): {names}")

        self._section("BULUT — ÜCRETSİZ KOTA", "Kart gerekmez; günlük/aylık istek sınırı vardır. Anahtarı alıp "
                                              "“bağlan” ile yapıştırman yeterli.")
        for name, note, pid in model_updates.FREE_TIERS:
            prov = catalog.BY_ID.get(pid)
            self._row(f"<b>{name}</b>", note, [
                ("anahtar al", lambda _=False, u=prov.key_url: QDesktopServices.openUrl(QUrl(u))),
                ("bağlan", lambda _=False, p=pid: self._connect(p))])
        free = ((live or {}).get("cloud") or {}).get("free") or []
        if free:
            names = ", ".join(r["id"].split("/")[-1].replace(":free", "") for r in free[:8])
            self._note(f"OpenRouter'da bugün ücretsiz olanlar: {names}")

        self._section("BULUT — ÜCRETLİ, EN İYİLER", "Fiyatlar 1 milyon token (yaklaşık 750 bin kelime) başına, "
                                                   "giriş / çıkış, ABD doları.")
        vendors = ((live or {}).get("cloud") or {}).get("vendors") or {}
        if not vendors:
            for prov in catalog.PROVIDERS:
                if prov.id not in ("groq", "openrouter"):
                    best = ", ".join(m for m, _ in prov.chat[:2])
                    self._row(f"<b>{prov.name}</b>", best, [("bağlan", lambda _=False, p=prov.id: self._connect(p))])
        def describe(r: dict) -> str:
            price = "ücretsiz" if not (r["in"] or r["out"]) else f"${r['in']:g} / ${r['out']:g}"
            return f"{r['id'].split('/')[-1]} ({price}{', resim görür' if r['vision'] else ''})"

        for label, picks in vendors.items():
            if not isinstance(picks, dict):  # eski biçimdeki liste: yenilenince düzelir
                continue
            parts, seen = [], set()
            for key, name in (("top", "en üst seviye"), ("newest", "en yeni"), ("cheap", "en ucuz")):
                r = picks.get(key)
                if r and r["id"] not in seen:
                    seen.add(r["id"])
                    parts.append(f"{name}: {describe(r)}")
            self._row(f"<b>{label}</b>", "  ·  ".join(parts),
                      [("bağlan", lambda _=False, p=VENDOR_PROVIDER.get(label, "openrouter"): self._connect(p))])
        self.rows.addStretch()

    # ---- eylemler
    def _connect(self, provider_id: str):
        self.connect_fn(provider_id)
        self._fill()

    def _refresh(self):
        self.refresh_btn.setEnabled(False)
        self.refresh_btn.setText("güncelleniyor…")

        def work():
            model_updates.refresh(force=True)
            self.bridge.refreshed.emit()

        threading.Thread(target=work, daemon=True).start()

    def _refreshed(self):
        self.refresh_btn.setEnabled(True)
        self.refresh_btn.setText("şimdi güncelle")
        self._fill()

    def _pull(self, model: str):
        btn, bar = self.buttons.get(model), self.bars.get(model)
        if btn:
            btn.setEnabled(False)
            btn.setText("iniyor…")
        if bar:
            bar.show()
        url = self.settings.ollama_url

        def work():
            try:
                sysinfo.pull(model, url, lambda pct, status: self.bridge.progress.emit(model, pct, status),
                             lambda: False)
                self.bridge.done.emit(model, "")
            except Exception as e:  # noqa: BLE001 — kullanıcıya gösterilir
                self.bridge.done.emit(model, str(e))

        threading.Thread(target=work, daemon=True).start()

    def _on_progress(self, model: str, pct: int, status: str):
        if pct >= 0 and model in self.bars:
            self.bars[model].setValue(pct)
        if model in self.buttons:
            self.buttons[model].setText(f"{pct}%" if pct >= 0 else "…")

    def _on_done(self, model: str, error: str):
        btn = self.buttons.get(model)
        if btn:
            btn.setText("hata" if error else "kuruldu ✓")
            btn.setToolTip(error)
        if not error:
            self.info.ollama_models.append(model)
        QApplication.processEvents()
