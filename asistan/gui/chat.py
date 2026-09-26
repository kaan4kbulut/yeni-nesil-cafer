"""Orta alan: sohbet akışı (mesajlar, kod blokları, araç kartları)."""

import json
from datetime import datetime
from pathlib import Path

from PySide6.QtCore import QElapsedTimer, Qt, QTimer, QUrl, Signal
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (
    QApplication, QFrame, QHBoxLayout, QLabel, QMenu, QPushButton, QScrollArea, QSizePolicy,
    QToolButton, QVBoxLayout, QWidget,
)

from .. import tools as _tools  # noqa: F401  (araçlar kayda burada yüklenir)
from ..registry import REGISTRY
from .icons import icon
from .theme import C

# araç adı -> (kısa ad, bittiğinde yazan açıklama): yerleşik araçlar kayıttan (registry.py), sıralı
TOOL_LABELS = {n: t.label for n, t in REGISTRY.tools.items() if t.source == "yerlesik"}
TOOL_LABELS["claude_code"] = ("claude code", "bitti")  # araç değil: Claude Code'a giden turun kartı
TOOL_LABELS["codex"] = ("codex", "bitti")  # aynı şekilde: ChatGPT hesabıyla Codex (cli_agents.py)
TOOL_LABELS["gemini_cli"] = ("gemini cli", "bitti")  # Google hesabıyla Gemini CLI
TOOL_LABELS["cli_step"] = ("adım", "bitti")  # bu programların kendi adımları (komut, dosya…)
TOOL_LABELS["mcp"] = ("MCP araçları", "")
TOOL_LABELS["add_tool"] = ("araç ekle", "eklendi")  # araç değil: araç fabrikasının onay adımı
TOOL_LABELS["fabrika"] = ("fabrika araçları", "")  # ajan izni: araç fabrikasının eklediği araçlar  # ajan izni: takılan MCP sunucularının bütün araçları


def tool_label(name: str) -> str:
    """Sohbetteki araç kartının adı; MCP araçlarında "sunucu: araç"."""
    return TOOL_LABELS[name][0] if name in TOOL_LABELS else REGISTRY.label(name)[0]


def _passive(*widgets):
    """Düğmenin içindeki etiketler tıklamayı düğmeye bıraksın."""
    for w in widgets:
        w.setAttribute(Qt.WA_TransparentForMouseEvents)


def _colored(text: str, color: str, object_name: str = "stamp") -> QLabel:
    label = QLabel(text, objectName=object_name)
    label.setStyleSheet(f"color: {color};")
    return label


def summarize_args(name: str, args: dict) -> str:
    if name in ("run_python", "run_command") and args.get("purpose"):
        text = str(args["purpose"]).strip().splitlines()[0]
    elif name == "run_python":
        lines = (args.get("code") or "").strip().splitlines()
        text = lines[0] if lines else ""
    elif name == "ask_specialist":
        text = f"{args.get('role', '')}: {args.get('question', '')}"
    elif name == "start_team_task":
        text = str(args.get("title", ""))
    elif name == "install_python_package":
        text = str(args.get("purpose") or args.get("packages", ""))
    elif name in ("check_installed", "open_app"):
        text = str(args.get("name", ""))
    elif name == "find_api":
        text = str(args.get("topic", ""))
    elif name in ("claude_code", "codex", "gemini_cli", "cli_step"):
        text = str(args.get("task", "")).strip().splitlines()[0] if str(args.get("task", "")).strip() else ""
    elif name == "delegate_to_agent":
        text = f"{args.get('agent', '')}: {args.get('task', '')}"
    elif name == "call_api":
        text = f"{args.get('api', '')} {str(args.get('method') or 'GET').upper()} {args.get('path') or ''}".strip()
    else:
        key = {"run_command": "command", "web_search": "query", "fetch_url": "url"}.get(name, "path")
        value = args.get(key)
        text = str(value) if value is not None else ""
    return text if len(text) <= 80 else text[:77] + "…"


def split_markdown(text: str) -> list[tuple[str, str, str]]:
    """Metni ("md", metin, "") ve ("code", kod, dil) parçalarına ayırır. Kapanmamış blok da koddur."""
    parts, buf, in_code, lang = [], [], False, ""
    for line in text.split("\n"):
        stripped = line.strip()
        if stripped.startswith("```"):
            if in_code:
                parts.append(("code", "\n".join(buf), lang))
                buf, in_code, lang = [], False, ""
            else:
                if "".join(buf).strip():
                    parts.append(("md", "\n".join(buf), ""))
                buf, in_code, lang = [], True, stripped[3:].strip()
            continue
        buf.append(line)
    if in_code:
        parts.append(("code", "\n".join(buf), lang))
    elif "".join(buf).strip():
        parts.append(("md", "\n".join(buf), ""))
    return parts


def _selectable(label: QLabel, links=True):
    flags = Qt.TextSelectableByMouse
    if links:
        flags |= Qt.LinksAccessibleByMouse
        label.setOpenExternalLinks(True)
    label.setTextInteractionFlags(flags)
    label.setWordWrap(True)
    label.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)


def _flash_copied(button: QToolButton):
    """Kopyala simgesi 1,5 sn boyunca yeşil onay işaretine döner."""
    button.setIcon(icon("check", C["success"], 15))
    QTimer.singleShot(1500, lambda: button.setIcon(icon("copy", C["muted"], 15, active=C["text"])))


class CodeBlock(QFrame):
    kind = "code"

    def __init__(self):
        super().__init__()
        self.setObjectName("codeBlock")
        lay = QVBoxLayout(self)
        lay.setContentsMargins(12, 6, 12, 10)
        top = QHBoxLayout()
        self.lang = QLabel(objectName="codeLang")
        copy = QToolButton(objectName="iconButton", toolTip="kodu kopyala")
        copy.setIcon(icon("copy", C["muted"], 15, active=C["text"]))
        copy.setCursor(Qt.PointingHandCursor)
        copy.clicked.connect(self._copy)
        self.copy_btn = copy
        top.addWidget(self.lang)
        top.addStretch()
        top.addWidget(copy)
        self.code = QLabel(objectName="codeText")
        self.code.setTextFormat(Qt.PlainText)
        _selectable(self.code, links=False)
        lay.addLayout(top)
        lay.addWidget(self.code)

    def update_part(self, content: str, lang: str):
        self.lang.setText(lang or "kod")
        if self.code.text() != content:
            self.code.setText(content)

    def _copy(self):
        QApplication.clipboard().setText(self.code.text())
        _flash_copied(self.copy_btn)


class MarkdownPart(QLabel):
    kind = "md"

    def __init__(self):
        super().__init__(objectName="assistantText")
        self.setTextFormat(Qt.MarkdownText)
        _selectable(self)

    def update_part(self, content: str, _lang: str):
        self.setText(content)


class RichText(QWidget):
    """Akan Markdown metni; kod blokları ayrı kutularda gösterilir."""

    def __init__(self, object_name="assistantText"):
        super().__init__()
        self.lay = QVBoxLayout(self)
        self.lay.setContentsMargins(0, 0, 0, 0)
        self.lay.setSpacing(8)
        self.parts: list[QWidget] = []
        self.buffer = ""
        self.dirty = False
        self.object_name = object_name

    def append(self, delta: str):
        self.buffer += delta
        self.dirty = True

    def flush(self):
        if not self.dirty:
            return
        self.dirty = False
        segments = split_markdown(self.buffer)
        for i, (kind, content, lang) in enumerate(segments):
            if i < len(self.parts) and self.parts[i].kind != kind:
                for w in self.parts[i:]:
                    w.deleteLater()
                self.parts = self.parts[:i]
            if i >= len(self.parts):
                w = CodeBlock() if kind == "code" else MarkdownPart()
                if kind == "md" and self.object_name != "assistantText":
                    w.setObjectName(self.object_name)
                self.parts.append(w)
                self.lay.addWidget(w)
            self.parts[i].update_part(content, lang)


ATTACH_RE = __import__("re").compile(r"\n\n\[Ek(?:ler|li dosyalar): ([^\]]+?)(?: — [^\]]*)?\](?:\n\(.*\))?\s*$", 2 | 16)
IMAGE_EXT = (".png", ".jpg", ".jpeg", ".webp", ".gif", ".bmp")


def split_attachments(text: str) -> tuple[str, list[str]]:
    """Mesajın sonundaki ek notunu ayırır: (metin, [göreli yollar])."""
    m = ATTACH_RE.search(text)
    if not m:
        return text, []
    return text[: m.start()].strip(), [p.strip() for p in m.group(1).split(",") if p.strip()]


class UserBubble(QWidget):
    """Kullanıcı mesajı: › işaretli, çerçeveli kutu; sağda saat; ekler küçük resim/etiket olarak."""

    def __init__(self, text: str, stamp: str = "", root: str = "", on_open=None, on_retry=None,
                 title_fn=None):
        super().__init__()
        full_text = text
        text, attachments = split_attachments(text)
        row = QVBoxLayout(self)
        row.setContentsMargins(0, 4, 0, 2)
        row.setSpacing(4)
        box = QFrame(objectName="userBox")
        hl = QHBoxLayout(box)
        hl.setContentsMargins(16, 12, 16, 12)
        hl.setSpacing(12)
        label = QLabel(text, objectName="userText")
        label.setTextFormat(Qt.PlainText)
        _selectable(label, links=False)
        hl.addWidget(QLabel("›", objectName="prompt"), 0, Qt.AlignTop)
        col = QVBoxLayout()
        col.setSpacing(8)
        col.addWidget(label)
        if attachments:
            row_att = QHBoxLayout()
            row_att.setSpacing(8)
            for rel in attachments:
                path = Path(root or ".", rel)
                if path.suffix.lower() in IMAGE_EXT and path.is_file():
                    thumb = QPushButton()
                    thumb.setObjectName("thumb")
                    thumb.setCursor(Qt.PointingHandCursor)
                    thumb.setToolTip(path.name)
                    from PySide6.QtGui import QIcon, QPixmap

                    pix = QPixmap(str(path))
                    if not pix.isNull():
                        pix = pix.scaled(160, 110, Qt.KeepAspectRatio, Qt.SmoothTransformation)
                        thumb.setIcon(QIcon(pix))
                        thumb.setIconSize(pix.size())
                        thumb.setFixedSize(pix.width() + 6, pix.height() + 6)
                    else:
                        thumb.setText(path.name)
                else:
                    thumb = QPushButton(f"▤ {path.name}", objectName="smallButton")
                    thumb.setCursor(Qt.PointingHandCursor)
                if on_open:
                    thumb.clicked.connect(lambda _=False, p=str(path): on_open(p))
                row_att.addWidget(thumb)
            row_att.addStretch()
            col.addLayout(row_att)
        hl.addLayout(col, 1)
        if stamp:
            hl.addWidget(QLabel(stamp, objectName="stamp"), 0, Qt.AlignTop)
        row.addWidget(box)
        # altta, sağda simgeler: tekrar et · kopyala · paylaş
        actions = QHBoxLayout()
        actions.setSpacing(2)
        actions.addStretch()

        def icon_button(name: str, tip: str) -> QToolButton:
            b = QToolButton(objectName="iconButton", toolTip=tip)
            b.setIcon(icon(name, C["muted"], 15, active=C["text"]))
            b.setCursor(Qt.PointingHandCursor)
            actions.addWidget(b)
            return b

        if on_retry:
            retry = icon_button("retry", "tekrar et — bu mesajı (ekleriyle) yeniden gönder")
            retry.clicked.connect(lambda: on_retry(full_text))
        copy = icon_button("copy", "kopyala")

        def do_copy():
            QApplication.clipboard().setText(text)
            _flash_copied(copy)

        copy.clicked.connect(do_copy)
        share = icon_button("share", "paylaş")
        share.setPopupMode(QToolButton.InstantPopup)
        from .share import share_menu  # döngüsel içe aktarmayı önlemek için

        share.setMenu(share_menu(share, lambda: text, title_fn or (lambda: "")))
        row.addLayout(actions)


class BlinkCursor(QLabel):
    """Retro blok imleç."""

    def __init__(self, w: int, h: int):
        super().__init__()
        self.setFixedSize(w, h)
        self.setStyleSheet(f"background: {C['accent']};")
        self.timer = QTimer(self)
        self.timer.timeout.connect(lambda: self.setStyleSheet(
            f"background: {C['accent'] if self.styleSheet().endswith('transparent;') else 'transparent'};"))
        self.timer.start(530)


class Welcome(QWidget):
    """Boş sohbet: karşılama, örnek görevler."""

    def __init__(self, title: str, text: str, suggestions: list[tuple[str, str]], hint: str, on_pick):
        super().__init__()
        col = QVBoxLayout(self)
        col.setContentsMargins(0, 0, 0, 8)
        col.setSpacing(0)
        top = QHBoxLayout()
        top.setSpacing(6)
        top.addWidget(QLabel(title, objectName="welcomeTitle"))
        top.addWidget(BlinkCursor(13, 28), 0, Qt.AlignVCenter)
        top.addStretch()
        col.addLayout(top)
        body = QLabel(text, objectName="welcomeText")
        body.setWordWrap(True)
        body.setMaximumWidth(600)
        col.addSpacing(12)
        col.addWidget(body)
        if suggestions:
            # suggestions liste ya da her çağrıda yeni öneri veren fonksiyon (↻ ile yenilenir)
            self.suggest_fn = suggestions if callable(suggestions) else (lambda: suggestions)
            self.on_pick = on_pick
            col.addSpacing(32)
            head = QHBoxLayout()
            head.addWidget(QLabel("BİRİNİ DENE", objectName="label"))
            head.addStretch()
            if callable(suggestions):
                shuffle = QToolButton(objectName="iconButton", toolTip="başka öneriler")
                shuffle.setIcon(icon("retry", C["muted"], 14, active=C["text"]))
                shuffle.setCursor(Qt.PointingHandCursor)
                shuffle.clicked.connect(self._fill)
                head.addWidget(shuffle)
            col.addLayout(head)
            col.addSpacing(8)
            self.rows = QVBoxLayout()
            self.rows.setSpacing(0)
            col.addLayout(self.rows)
            self._fill()
            line = QFrame(objectName="rule")
            col.addWidget(line)
        if hint:
            col.addSpacing(14)
            h = QLabel(hint, objectName="stamp")
            h.setStyleSheet("font-size: 11.5px;")
            col.addWidget(h)

    def _fill(self):
        while self.rows.count():
            w = self.rows.takeAt(0).widget()
            if w:
                w.hide()  # deleteLater bir sonraki döngüye kalır; yenilerin altında görünmesin
                w.deleteLater()
        for prompt, tag in self.suggest_fn():
            b = QPushButton(objectName="suggestion")
            b.setCursor(Qt.PointingHandCursor)
            hl = QHBoxLayout(b)
            hl.setContentsMargins(4, 0, 4, 0)
            hl.setSpacing(12)
            arrow = QLabel("›", objectName="prompt")
            label = QLabel(prompt)
            label.setStyleSheet(f"color: {C['text']}; font-size: 14.5px;")
            tag_label = QLabel(tag, objectName="suggestionTag")
            _passive(arrow, label, tag_label)
            hl.addWidget(arrow)
            hl.addWidget(label, 1)
            hl.addWidget(tag_label)
            b.clicked.connect(lambda _=False, t=prompt: self.on_pick(t))
            self.rows.addWidget(b)


class ThinkingView(QWidget):
    def __init__(self):
        super().__init__()
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        self.toggle = QPushButton("💭 Düşünce sürecini göster", objectName="toolHeader")
        self.toggle.setCheckable(True)
        self.toggle.setCursor(Qt.PointingHandCursor)
        self.text = RichText("thinking")
        self.text.setVisible(False)
        self.toggle.toggled.connect(self.text.setVisible)
        lay.addWidget(self.toggle)
        lay.addWidget(self.text)


class SecurityNotice(QFrame):
    """Engellenen işlem kartı: kısa not, [🛡 Güvenliği Kapat] [Neden?]; neden açıklaması düğmeyle açılır."""

    def __init__(self, text: str, decision: str, explanation: str, on_disable):
        super().__init__(objectName="securityNotice")
        color = C["error"] if decision == "reject" else C["warn"]
        self.setStyleSheet(f"#securityNotice {{ border: 1px solid {color}; border-radius: 8px; background: {C['surface']}; }}"
                           f" #securityNotice QLabel {{ background: transparent; }}")
        lay = QVBoxLayout(self)
        lay.setContentsMargins(12, 10, 12, 10)
        lay.setSpacing(8)
        head = QLabel(text)
        head.setWordWrap(True)
        head.setStyleSheet(f"color: {color};")
        _selectable(head)
        lay.addWidget(head)
        row = QHBoxLayout()
        row.setSpacing(6)
        self.off = QPushButton("🛡 Güvenliği Kapat", objectName="smallButton",
                               toolTip="Güvenlik ajanı kapanır; bundan sonra her adım sana sorulur")
        self.why = QPushButton("Neden?", objectName="smallButton", toolTip="Bu işlemin neden yapılmadığını göster")
        self.why.setCheckable(True)
        for b in (self.off, self.why):
            b.setCursor(Qt.PointingHandCursor)
            row.addWidget(b)
        row.addStretch()
        lay.addLayout(row)
        self.detail = QLabel(objectName="notice")
        self.detail.setTextFormat(Qt.MarkdownText)
        self.detail.setWordWrap(True)
        _selectable(self.detail)
        self.detail.setText(explanation or "Ayrıntı yok.")
        self.detail.setVisible(False)
        lay.addWidget(self.detail)
        self.why.toggled.connect(self.detail.setVisible)
        self.why.toggled.connect(lambda on: self.why.setText("Gizle" if on else "Neden?"))

        def disable():
            on_disable()
            self.off.setText("🛡 Güvenlik kapatıldı — isteğini yeniden gönderebilirsin")
            self.off.setEnabled(False)

        self.off.clicked.connect(disable)


class ReportOffer(QFrame):
    """Sorun oldu: [🐞 Sorunu raporla] → rapor dosyası (problem_report.py) + Claude Code'a verilecek cümle panoda."""

    def __init__(self, text: str, on_report):
        super().__init__(objectName="reportOffer")
        self.setStyleSheet(f"#reportOffer {{ border: 1px dashed {C['warn']}; border-radius: 8px; "
                           f"background: {C['surface']}; }} #reportOffer QLabel {{ background: transparent; }}")
        lay = QVBoxLayout(self)
        lay.setContentsMargins(12, 10, 12, 10)
        lay.setSpacing(8)
        self.label = QLabel(text)
        self.label.setWordWrap(True)
        self.label.setTextFormat(Qt.MarkdownText)
        _selectable(self.label)
        lay.addWidget(self.label)
        row = QHBoxLayout()
        row.setSpacing(6)
        self.button = QPushButton("🐞 Sorunu raporla", objectName="smallButton",
                                  toolTip="Geliştiriciye (Claude Code) verilecek raporu hazırla; anahtarlar gizlenir")
        self.button.setCursor(Qt.PointingHandCursor)
        self.button.clicked.connect(lambda: (self.button.setEnabled(False),
                                             self.button.setText("rapor hazırlanıyor…"), on_report(self)))
        row.addWidget(self.button)
        self.extra = QHBoxLayout()
        row.addLayout(self.extra)
        row.addStretch()
        lay.addLayout(row)

    def done(self, path: str, prompt: str):
        from PySide6.QtGui import QDesktopServices, QGuiApplication

        QGuiApplication.clipboard().setText(prompt)
        self.button.setText("✓ rapor hazır")
        self.label.setText(f"Rapor: `{path}`\n\nClaude Code'a verilecek cümle panoya kopyalandı; yapıştırman yeterli.")
        for text, action in (("Klasörü aç", lambda: QDesktopServices.openUrl(QUrl.fromLocalFile(str(Path(path).parent)))),
                             ("Tekrar kopyala", lambda: QGuiApplication.clipboard().setText(prompt))):
            b = QPushButton(text, objectName="smallButton")
            b.setCursor(Qt.PointingHandCursor)
            b.clicked.connect(action)
            self.extra.addWidget(b)

    def failed(self, error: str):
        self.button.setText("rapor hazırlanamadı")
        self.label.setText(f"Rapor hazırlanamadı: {error}")

    def cancelled(self):  # önizlemede vazgeçildi: yeniden denenebilir
        self.button.setEnabled(True)
        self.button.setText("🐞 Sorunu raporla")


class PlanCard(QFrame):
    """Yöneticinin planı: adımlar ○ ▶ … ↻ ✓ ✗ işaretleriyle canlı güncellenir; notlar adımın altında."""

    COLORS = {"done": "success", "failed": "error", "fixing": "warn", "running": "accent", "checking": "accent"}
    WORDS = {"running": "yapılıyor", "checking": "doğrulanıyor", "fixing": "düzeltiliyor"}

    def __init__(self, steps: list | None):
        super().__init__(objectName="planCard")
        self.setStyleSheet(f"#planCard {{ border: 1px solid {C['frame']}; border-radius: 8px; background: {C['surface']}; }}"
                           f" #planCard QLabel {{ background: transparent; }}")
        self.lay = QVBoxLayout(self)
        self.lay.setContentsMargins(12, 10, 12, 10)
        self.lay.setSpacing(4)
        self.head = QLabel(objectName="stamp")
        self.lay.addWidget(self.head)
        self.rows: list[QLabel] = []
        self.steps: list[dict] = []
        self.set_steps(steps)

    def set_steps(self, steps: list | None):
        """None: plan çıkarılıyor · []: plana gerek yok (kart gizlenir) · liste: adımlar."""
        for row in self.rows:
            row.hide()
            row.deleteLater()
        self.rows = []
        if steps is None:
            self.head.setText("■ yönetici plan çıkarıyor…")
            return
        if not steps:
            self.hide()
            return
        self.steps = [dict(s) for s in steps]
        for _ in self.steps:
            row = QLabel()
            row.setWordWrap(True)
            row.setTextFormat(Qt.RichText)
            _selectable(row, links=False)
            self.lay.addWidget(row)
            self.rows.append(row)
        for i in range(len(self.steps)):
            self._paint(i)

    def update_step(self, i: int, status: str, note: str):
        if 0 <= i < len(self.steps):
            self.steps[i].update(status=status, note=note)
            self._paint(i)

    def _paint(self, i: int):
        from html import escape

        from ..manager import STEP_ICONS

        st = self.steps[i]
        status = st.get("status", "pending")
        color = C[self.COLORS.get(status, "muted")]
        word = self.WORDS.get(status, "")
        text = (f'<span style="color:{color};">{STEP_ICONS.get(status, "○")}</span>&nbsp; {i + 1}. '
                f'{escape(st.get("title", ""))}' + (f' <span style="color:{C["muted"]};">· {word}</span>' if word else ""))
        if st.get("note") and status in ("failed", "fixing", "skipped"):
            text += f'<br><span style="color:{C["muted"]};">&nbsp;&nbsp;&nbsp;&nbsp;{escape(st["note"])}</span>'
        self.rows[i].setText(text)
        done = sum(s.get("status") == "done" for s in self.steps)
        failed = sum(s.get("status") == "failed" for s in self.steps)
        self.head.setText(f"PLAN  ·  {done}/{len(self.steps)} adım bitti" + (f"  ·  {failed} başarısız" if failed else ""))


class ToolCard(QFrame):
    """Tek satırlık araç kaydı: durum · ad · açıklama · süre; tıklayınca kod ve çıktı açılır."""

    def __init__(self, name: str, args: dict):
        super().__init__(objectName="toolCard")
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)
        self.name, self.summary = name, summarize_args(name, args)
        self.header = QPushButton(objectName="toolHeader")
        self.header.setCheckable(True)
        self.header.setCursor(Qt.PointingHandCursor)
        hl = QHBoxLayout(self.header)
        hl.setContentsMargins(12, 0, 12, 0)
        hl.setSpacing(10)
        self.status = _colored("…", C["accent"], "stepTitle")
        self.status.setFixedWidth(12)
        title = _colored(tool_label(name), C["text"], "stepTitle")
        self.desc = QLabel(self.summary, objectName="stepSub")
        self.desc.setMinimumWidth(0)
        self.desc.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
        self.time = QLabel("", objectName="stepTime")
        self.chevron = QLabel("›", objectName="stepTime")
        _passive(self.status, title, self.desc, self.time, self.chevron)
        for w in (self.status, title):
            hl.addWidget(w)
        hl.addWidget(self.desc, 1)
        hl.addWidget(self.time)
        hl.addWidget(self.chevron)
        self.details = QLabel(objectName="toolDetails")
        self.details.setTextFormat(Qt.PlainText)
        _selectable(self.details, links=False)
        self.details.setVisible(False)
        self.body = self._body(name, args)
        self.details.setText(self.body)
        self.header.toggled.connect(self._toggle)
        lay.addWidget(self.header)
        lay.addWidget(self.details)
        self.clock = QElapsedTimer()
        self.clock.start()

    @staticmethod
    def _body(name: str, args: dict) -> str:
        if name == "run_python":
            return args.get("code", "")
        if name == "run_command":
            return "$ " + str(args.get("command", ""))
        if name == "write_file":
            content = str(args.get("content", ""))
            return f"{args.get('path', '')}\n\n{content[:3000]}" + ("\n…" if len(content) > 3000 else "")
        return json.dumps(args, ensure_ascii=False, indent=2)

    def _toggle(self, open_: bool):
        self.details.setVisible(open_)
        self.chevron.setText("⌄" if open_ else "›")

    def set_status(self, icon_text: str):  # eski arayüzle uyum
        self.status.setText(icon_text)

    def finish(self, result: str, is_error: bool, live: bool = True):
        self.status.setText("✗" if is_error else "✓")
        self.status.setStyleSheet(f"color: {C['error'] if is_error else C['success']};")
        done = TOOL_LABELS[self.name][1] if self.name in TOOL_LABELS else REGISTRY.label(self.name)[1]
        if done and not is_error and self.name in ("run_python", "run_command"):
            self.desc.setText(done)
        if live:
            self.time.setText(f"{self.clock.elapsed() / 1000:.1f} sn")
        shown = result if len(result) <= 6000 else result[:6000] + "\n…"
        self.details.setText(f"{self.body}\n\n── çıktı ──\n{shown}")
        if self.name == "generate_image" and not is_error and result.startswith("SAVED: "):
            self._add_thumbs(result)

    def _add_thumbs(self, result: str):
        """Üretilen resimler kartın altında görünür; tıklayınca varsayılan resim görüntüleyicide açılır."""
        from PySide6.QtCore import QUrl
        from PySide6.QtGui import QDesktopServices, QIcon, QPixmap

        root = Path(getattr(self, "root", "") or ".")
        rels = result.splitlines()[0][len("SAVED: "):].split(", ")
        row = QHBoxLayout()
        row.setContentsMargins(12, 6, 12, 8)
        row.setSpacing(8)
        for rel in rels:
            path = (root / rel.strip())
            pix = QPixmap(str(path))
            if pix.isNull():
                continue
            pix = pix.scaled(240, 240, Qt.KeepAspectRatio, Qt.SmoothTransformation)
            thumb = QPushButton(objectName="thumb")
            thumb.setCursor(Qt.PointingHandCursor)
            thumb.setToolTip(str(path))
            thumb.setIcon(QIcon(pix))
            thumb.setIconSize(pix.size())
            thumb.setFixedSize(pix.width() + 6, pix.height() + 6)
            thumb.clicked.connect(lambda _=False, p=str(path): QDesktopServices.openUrl(QUrl.fromLocalFile(p)))
            row.addWidget(thumb)
        row.addStretch(1)
        self.layout().addLayout(row)


def _duration(seconds: float) -> str:
    seconds = int(seconds)
    if seconds < 60:
        return f"{seconds} sn"
    return f"{seconds // 60} dk {seconds % 60} sn"


class WorkGroup(QFrame):
    """Bir yanıttaki ara adımlar (araç çağrıları, ara metinler) tek, açılır kapanır satırda toplanır."""

    def __init__(self, live: bool):
        super().__init__(objectName="workGroup")
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(4)
        self.header = QPushButton(objectName="workHeader")
        self.header.setCheckable(True)
        self.header.setCursor(Qt.PointingHandCursor)
        self.body = QFrame()
        self.body_lay = QVBoxLayout(self.body)
        self.body_lay.setContentsMargins(0, 0, 0, 0)
        self.body_lay.setSpacing(8)
        # az adım varken satırlar doğrudan görünür; COLLAPSE_AFTER'ı aşınca tek satırda toplanır
        self.header.setVisible(False)
        self.collapsed_mode = False
        self.header.toggled.connect(self._toggle)
        lay.addWidget(self.header)
        lay.addWidget(self.body)
        self.live = live
        self.steps = 0
        self.errors = 0
        self.current = ""  # canlıyken şu an çalışan adım
        self.seconds: float | None = None
        self.update_header(0)

    def _toggle(self, open_: bool):
        if self.collapsed_mode:
            self.body.setVisible(open_)
        self.update_header()

    def add(self, widget):
        self.body_lay.addWidget(widget)

    COLLAPSE_AFTER = 3

    def add_step(self, label: str):
        self.steps += 1
        self.current = label
        if not self.collapsed_mode and self.steps > self.COLLAPSE_AFTER:
            self.collapsed_mode = True
            self.header.setVisible(True)
            self.body.setObjectName("workBody")
            self.body_lay.setContentsMargins(14, 6, 0, 2)
            self.body.style().unpolish(self.body)
            self.body.style().polish(self.body)
            self.body.setVisible(self.header.isChecked())

    def step_done(self, is_error: bool):
        self.errors += int(is_error)
        self.current = ""

    def finish(self, seconds: float | None):
        self.live = False
        self.seconds = seconds
        self.current = ""
        self.update_header()

    def update_header(self, elapsed: float | None = None):
        arrow = "⌄" if self.header.isChecked() else "›"
        parts = []
        if self.live:
            parts.append(f"Çalışıyor · {_duration(elapsed)}" if elapsed is not None else "Çalışıyor")
        elif self.seconds is not None:
            parts.append(f"{_duration(self.seconds)} çalıştı")
        parts.append(f"{self.steps} adım")
        if self.errors:
            parts.append(f"{self.errors} hata")
        text = f"{arrow}  " + "  ·  ".join(parts)
        if self.live and self.current and not self.header.isChecked():
            text += f"    {self.current}"
        if self.header.text() != text:
            self.header.setText(text)


FILE_KINDS = {
    ".md": ("Markdown", "file"), ".txt": ("Metin", "file"), ".pdf": ("PDF", "file"),
    ".csv": ("Tablo (CSV)", "table"), ".xlsx": ("Excel", "table"), ".json": ("JSON", "code"),
    ".py": ("Python", "code"), ".js": ("JavaScript", "code"), ".ts": ("TypeScript", "code"),
    ".html": ("HTML", "code"), ".css": ("CSS", "code"), ".sh": ("Betik", "code"), ".sql": ("SQL", "code"),
    ".png": ("Resim", "image"), ".jpg": ("Resim", "image"), ".jpeg": ("Resim", "image"),
    ".gif": ("Resim", "image"), ".webp": ("Resim", "image"), ".svg": ("SVG", "image"),
}


def file_kind(path: Path) -> tuple[str, str]:
    return FILE_KINDS.get(path.suffix.lower(), (path.suffix.lstrip(".").upper() or "Dosya", "file"))


def _size(n: int) -> str:
    for unit in ("B", "KB", "MB", "GB"):
        if n < 1024:
            return f"{n:.0f} {unit}" if unit == "B" else f"{n:.1f} {unit}"
        n /= 1024
    return f"{n:.1f} TB"


class FileCard(QFrame):
    """Oluşan/değişen dosya satırı: + ad · tür · boyut · aç; tıklayınca sağ panelde önizlenir."""

    def __init__(self, path: Path, edited: bool, on_open):
        super().__init__(objectName="fileCard")
        self.path, self.on_open = path, on_open
        self.setCursor(Qt.PointingHandCursor)
        row = QHBoxLayout(self)
        row.setContentsMargins(12, 6, 6, 6)
        row.setSpacing(10)
        kind, _ = file_kind(path)
        marker = _colored("~" if edited else "+", C["accent"] if edited else C["success"], "fileTile")
        marker.setFixedWidth(10)
        name = QLabel(path.name, objectName="fileName")
        name.setTextFormat(Qt.PlainText)
        try:
            size = _size(path.stat().st_size)
        except OSError:
            size = "silinmiş"
        meta = QLabel(f"{kind} · {size}", objectName="fileMeta")
        open_btn = QPushButton("aç", objectName="smallButton")
        open_btn.clicked.connect(lambda: on_open(str(path)))
        more = QToolButton(objectName="iconButton")
        more.setText("⋯")
        more.setPopupMode(QToolButton.InstantPopup)
        menu = QMenu(more)
        menu.addAction("önizle", lambda: on_open(str(path)))
        menu.addAction("varsayılan programda aç", lambda: QDesktopServices.openUrl(QUrl.fromLocalFile(str(path))))
        menu.addAction("klasörde göster", lambda: QDesktopServices.openUrl(QUrl.fromLocalFile(str(path.parent))))
        more.setMenu(menu)
        row.addWidget(marker)
        row.addWidget(name)
        row.addWidget(meta, 1)
        row.addWidget(open_btn)
        row.addWidget(more)

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.LeftButton:
            self.on_open(str(self.path))
        super().mouseReleaseEvent(event)


def format_stats(seconds: float, stats: list[dict]) -> str:
    out_tokens = sum(s.get("output_tokens", 0) for s in stats)
    speeds = [s["tokens_per_sec"] for s in stats if s.get("tokens_per_sec")]
    text = f"⏱ {seconds:.1f} sn"
    if out_tokens:
        text += f"  ·  {out_tokens} token"
    if speeds:
        text += f"  ·  {sum(speeds) / len(speeds):.1f} token/sn"
    return text


class AssistantBubble(QFrame):
    """Asistanın (ya da bir ajanın) bir yanıtı: başlık, içerik, altta süre · yeniden dene · kopyala · paylaş."""

    def __init__(self, header: str, title_fn, on_regenerate=None, on_problem=None):
        super().__init__(objectName="assistantBox")
        self.title_fn = title_fn
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)
        inner = QWidget()
        self.body = QVBoxLayout(inner)
        self.body.setContentsMargins(16, 10, 16, 12)
        self.body.setSpacing(10)
        self.body.addWidget(QLabel(header, objectName="turnHeader"))
        lay.addWidget(inner)
        self.footer = QWidget(objectName="bubbleFooter")
        fl = QHBoxLayout(self.footer)
        fl.setContentsMargins(16, 6, 8, 6)
        fl.setSpacing(2)
        self.stats = QLabel("", objectName="turnFooter")
        regen = None
        if on_regenerate:
            regen = QToolButton(objectName="iconButton", toolTip="yeniden dene — farklı bir çözüm bulsun")
            regen.setIcon(icon("retry", C["muted"], 15, active=C["text"]))
            regen.setCursor(Qt.PointingHandCursor)
            regen.clicked.connect(on_regenerate)
        problem = None
        if on_problem:
            problem = QToolButton(objectName="iconButton",
                                  toolTip="hata var — yarım kaldı, yapmadı ya da yanlış: kendini kontrol edip tamamlasın")
            problem.setIcon(icon("alert", C["muted"], 15, active=C["error"]))
            problem.setCursor(Qt.PointingHandCursor)
            problem.clicked.connect(on_problem)
        copy = QToolButton(objectName="iconButton", toolTip="kopyala")
        copy.setIcon(icon("copy", C["muted"], 15, active=C["text"]))
        copy.setCursor(Qt.PointingHandCursor)
        copy.clicked.connect(lambda: self._copy(copy))
        share = QToolButton(objectName="iconButton", toolTip="paylaş")
        share.setIcon(icon("share", C["muted"], 15, active=C["text"]))
        share.setCursor(Qt.PointingHandCursor)
        share.setPopupMode(QToolButton.InstantPopup)
        from .share import share_menu  # döngüsel içe aktarmayı önlemek için

        share.setMenu(share_menu(share, self.text, title_fn))
        fl.addWidget(self.stats, 1)
        if regen:
            fl.addWidget(regen)
        if problem:
            fl.addWidget(problem)
        fl.addWidget(copy)
        fl.addWidget(share)
        self.footer_actions = [x for x in (regen, problem, copy, share) if x]  # karar düğmeleri çıkınca gizlenir
        self.footer.setVisible(False)
        lay.addWidget(self.footer)

    def text(self) -> str:
        """Yanıtın asıl metni (ara adımlar hariç), Markdown olarak."""
        parts = []
        for i in range(self.body.count()):
            w = self.body.itemAt(i).widget()
            if isinstance(w, RichText) and w.buffer.strip():
                parts.append(w.buffer.strip())
        return "\n\n".join(parts)

    def _copy(self, button: QToolButton):
        QApplication.clipboard().setText(self.text())
        _flash_copied(button)

    def finish(self, summary: str = ""):
        self.stats.setText(summary)
        self.footer.setVisible(bool(self.text()))

    # ---- karar düğmeleri (✓ ✗ ↻): alt köşede, kenara taşan küçük bir baloncuk; asistan bir işlem planladığında
    def offer_apply(self, on_apply, on_cancel, on_retry=None):
        if getattr(self, "apply_btn", None) is not None or self.parentWidget() is None:
            return
        pill = QFrame(self.parentWidget(), objectName="decisionPill")
        row = QHBoxLayout(pill)
        row.setContentsMargins(4, 4, 4, 4)
        row.setSpacing(4)

        def button(name: str, tip: str, color: str, obj: str, fn) -> QToolButton:
            b = QToolButton(objectName=obj, toolTip=tip)
            b.setIcon(icon(name, color, 16))
            b.setFixedSize(30, 30)
            b.setCursor(Qt.PointingHandCursor)
            b.clicked.connect(lambda: (self._close_decision(), fn()))
            row.addWidget(b)
            return b

        button("check", "Onayla — göreve başlasın (her adımda ayrıca sorulur)", C["on_accent"], "decisionYes", on_apply)
        button("x", "İptal — hiçbir şey yapılmasın", C["text2"], "decisionNo", on_cancel)
        if on_retry:
            button("retry", "Beğenmedim — başka bir çözüm bulsun", C["text2"], "decisionNo", on_retry)
        self.destroyed.connect(pill.deleteLater)
        self.apply_btn = pill
        for x in self.footer_actions:  # köşedeki simgelerle üst üste binmesin
            x.hide()
        pill.adjustSize()
        self._place_apply()
        pill.show()

    def offer_choices(self, options: list[str], on_pick, on_other):
        """Asistanın sorusunun cevapları: tıklanabilir baloncuklar (biri seçilince hepsi kapanır)."""
        box = QWidget(objectName="choiceBox")
        col = QVBoxLayout(box)
        col.setContentsMargins(0, 2, 0, 0)
        col.setSpacing(6)
        buttons = []

        def pick(fn):
            for b in buttons:
                b.setEnabled(False)
            fn()

        for option in options:
            b = QPushButton(option, objectName="choiceButton")
            b.setCursor(Qt.PointingHandCursor)
            b.clicked.connect(lambda _=False, o=option: pick(lambda: on_pick(o)))
            buttons.append(b)
            col.addWidget(b, 0, Qt.AlignLeft)
        other = QPushButton("✎ başka bir şey yazayım", objectName="choiceOther")
        other.setCursor(Qt.PointingHandCursor)
        other.clicked.connect(on_other)
        col.addWidget(other, 0, Qt.AlignLeft)
        self.body.addWidget(box)
        self.choice_buttons = buttons

    def _close_decision(self):
        pill = getattr(self, "apply_btn", None)
        if pill is not None:
            pill.hide()
            pill.setEnabled(False)
            for x in self.footer_actions:
                x.show()

    def _place_apply(self):
        btn = getattr(self, "apply_btn", None)
        if btn is not None and btn.isEnabled():
            # alt sağ köşe: baloncuğun kenarına oturur, biraz dışına taşar
            btn.move(self.x() + self.width() - btn.width() + 14, self.y() + self.height() - btn.height() // 2)
            btn.raise_()

    def moveEvent(self, event):  # noqa: N802
        super().moveEvent(event)
        self._place_apply()

    def resizeEvent(self, event):  # noqa: N802
        super().resizeEvent(event)
        self._place_apply()

    def hideEvent(self, event):  # noqa: N802
        super().hideEvent(event)
        if getattr(self, "apply_btn", None) is not None:
            self.apply_btn.hide()


class ChatView(QScrollArea):
    file_opened = Signal(str)  # dosya kartına tıklandı
    retry_requested = Signal(str)  # kullanıcı mesajında "tekrar et"
    regenerate_requested = Signal(str)  # yanıtta "yeniden dene": yanıtlanan istek metni
    choice_picked = Signal(str)  # asistanın sorusuna baloncukla verilen cevap
    problem_requested = Signal(str)  # yanıtta "hata var": yanıtlanan istek metni (kendini kontrol etsin)
    apply_requested = Signal(str)  # yanıt kenarındaki ✓: onaylanan isteğin metni

    def __init__(self):
        super().__init__(objectName="chatArea")
        self.setWidgetResizable(True)
        self.setFrameShape(QFrame.NoFrame)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.container = QWidget(objectName="chatContainer")
        outer = QHBoxLayout(self.container)
        outer.setContentsMargins(0, 0, 0, 0)
        # içerik geniş ekranlarda da okunaklı kalsın diye ortalanmış bir sütun
        column = QWidget()
        column.setMaximumWidth(776)
        self.layout_ = QVBoxLayout(column)
        self.layout_.setContentsMargins(28, 20, 28, 20)
        self.layout_.setSpacing(10)
        self.layout_.addStretch()
        outer.addStretch()
        outer.addWidget(column, 100)
        outer.addStretch()
        self.setWidget(self.container)
        self.streams: list[RichText] = []
        self.current_text: RichText | None = None
        self.current_thinking: ThinkingView | None = None
        self.tools: dict[str, ToolCard] = {}
        self.plan_card: PlanCard | None = None  # bu yanıttaki yönetici planı
        self.group: WorkGroup | None = None  # bu yanıtın adım grubu
        self.bubble: AssistantBubble | None = None  # açık yanıt baloncuğu
        self.title_fn = lambda: ""  # paylaşırken kullanılacak başlık (sohbet adı)
        self.can_regenerate = False  # yanıtlarda "yeniden dene" gösterilsin mi
        self.last_bubble: AssistantBubble | None = None  # son yanıt (✓ onay düğmesi buna eklenir)
        self.last_request = ""  # son kullanıcı mesajı (ekler hariç); yeni yanıt buna bağlanır
        self.turn_pending: list[QWidget] = []  # son araçtan sonra eklenen metin/düşünce parçaları
        self.turn_clock = QElapsedTimer()
        self.turn_live = False
        self.root = ""  # araçların göreli yollarının çözüldüğü klasör
        self.tool_files: dict[str, tuple[str, bool]] = {}  # call_id -> (yol, düzenleme mi)
        self.turn_files: dict[str, bool] = {}  # bu yanıtta yazılan dosyalar
        self.waiting: QLabel | None = None
        self.waiting_since = QElapsedTimer()
        self._follow = True
        self.verticalScrollBar().rangeChanged.connect(self._on_range)
        self.verticalScrollBar().valueChanged.connect(self._on_scroll)
        self.timer = QTimer(self)
        self.timer.timeout.connect(self.flush)
        self.timer.start(60)

    # ---- kaydırma
    def _on_scroll(self, value):
        self._follow = value >= self.verticalScrollBar().maximum() - 40

    def _on_range(self, _min, maximum):
        if self._follow:
            self.verticalScrollBar().setValue(maximum)

    @property
    def cur(self) -> QVBoxLayout:
        """Yeni içeriğin eklendiği yer: açık bir yanıt varsa onun baloncuğu."""
        return self.bubble.body if self.bubble is not None else self.layout_

    def _add(self, widget):
        self.cur.addWidget(widget)
        if self.waiting is not None and widget is not self.waiting:
            # bekleme göstergesi hep en altta kalsın
            self.cur.removeWidget(self.waiting)
            self.cur.addWidget(self.waiting)

    def clear(self):
        self.hide_waiting()
        while self.layout_.count() > 1:
            item = self.layout_.takeAt(1)
            if item.widget():
                item.widget().hide()  # deleteLater bir sonraki döngüye kalır; o ana kadar görünmesin
                item.widget().deleteLater()
        self.streams.clear()
        self.tools.clear()
        self.group = None
        self.bubble = None
        self.last_request = ""
        self.turn_pending = []
        self.turn_live = False
        self.tool_files.clear()
        self.turn_files = {}
        self.current_text = self.current_thinking = None
        self.plan_card = None
        self._follow = True

    def flush(self):
        for s in self.streams:
            s.flush()
        if self.group is not None and self.group.live:
            self.group.update_header(self.turn_clock.elapsed() / 1000)
        if self.waiting:
            secs = self.waiting_since.elapsed() // 1000
            block = C["accent"] if (self.waiting_since.elapsed() // 530) % 2 == 0 else "transparent"
            self.waiting.setText(f'<span style="background:{block}; color:{block};">▌</span>&nbsp; '
                                 f'yanıt hazırlanıyor · {secs} sn')

    # ---- bekleme göstergesi
    def show_waiting(self):
        if self.waiting is None:
            self.waiting = QLabel(objectName="stamp")
            self.waiting.setTextFormat(Qt.RichText)
            self.cur.addWidget(self.waiting)
            self.waiting_since.start()
            self.flush()

    def hide_waiting(self):
        if self.waiting is not None:
            self.waiting.hide()
            self.waiting.setParent(None)
            self.waiting.deleteLater()
            self.waiting = None

    # ---- içerik
    def add_user(self, text: str, stamp: str | None = None):
        self._close_bubble()
        self._follow = True
        if not text.startswith("↻ "):  # "yeniden dene" mesajı asıl isteğin yerini almasın
            self.last_request = split_attachments(text)[0]
        self._add(UserBubble(text, datetime.now().strftime("%H:%M") if stamp is None else stamp,
                             self.root, self.file_opened.emit, self.retry_requested.emit, self.title_fn))
        self.end_segment()

    def add_notice(self, text: str, color: str | None = None):
        label = QLabel(objectName="notice")
        label.setTextFormat(Qt.MarkdownText)
        _selectable(label)
        if color:
            label.setStyleSheet(f"color: {color};")
        label.setText(text)
        self._add(label)
        self.end_segment()

    def show_plan(self, steps: list | None):
        """Yöneticinin planı (None: çıkarılıyor, []: gerek yok). Kart yanıtın en üstünde durur."""
        if self.plan_card is None:
            if steps == []:
                return
            self.plan_card = PlanCard(steps)
            self._add(self.plan_card)
            self.end_segment()
        else:
            self.plan_card.set_steps(steps)
        if steps == []:
            self.plan_card = None

    def update_step(self, i: int, status: str, note: str):
        if self.plan_card is not None:
            self.plan_card.update_step(i, status, note)

    def add_report_offer(self, text: str, on_report) -> "ReportOffer":
        """Sorun oldu: raporlama önerisi (düğmeye basılınca on_report(kart) çağrılır)."""
        card = ReportOffer(text, on_report)
        self._add(card)
        self.end_segment()
        return card

    def add_security_block(self, text: str, decision: str, explanation: str, on_disable):
        """Güvenlik ajanı bir işlemi engelledi / geri çevirdi: not + "güvenliği kapat" + "neden?" düğmeleri."""
        self._add(SecurityNotice(text, decision, explanation, on_disable))
        self.end_segment()

    def add_welcome(self, title: str, text: str, suggestions: list[tuple[str, str]], hint: str, on_pick):
        self._close_bubble()
        self._add(Welcome(title, text, suggestions, hint, on_pick))
        self.end_segment()

    def start_turn(self, model: str, show_time: bool = True, who: str = "asistan"):
        text = f"{who}  ·  {model}" if model else who
        self._close_bubble()
        regen = problem = None
        if self.can_regenerate and self.last_request:
            regen = lambda _=False, q=self.last_request: self.regenerate_requested.emit(q)
            problem = lambda _=False, q=self.last_request: self.problem_requested.emit(q)
        self.bubble = self.last_bubble = AssistantBubble(text, self.title_fn, regen, problem)
        self.plan_card = None
        self.layout_.addWidget(self.bubble)
        self.end_segment()
        self.turn_live = show_time  # geçmişten çizilen yanıtlar canlı değil
        self.turn_clock.start()

    def offer_choices(self, options: list[str], on_other):
        """Son yanıt bir soruyla bittiyse cevap seçenekleri baloncuk olarak sunulur."""
        if self.last_bubble is not None and options:
            self.last_bubble.offer_choices(options, self.choice_picked.emit, on_other)

    def offer_apply(self):
        """Son yanıtın alt köşesine ✓ ✗ ↻ koyar: onayla (adım adım sorarak yapar) · iptal · başka çözüm."""
        bubble, request = self.last_bubble, self.last_request
        if bubble is not None and request:
            bubble.offer_apply(lambda: self.apply_requested.emit(request),
                               lambda: self.add_notice("✗ İptal edildi — hiçbir işlem yapılmadı.", C["muted"]),
                               (lambda: self.regenerate_requested.emit(request)) if self.can_regenerate else None)

    def _close_group(self):
        if self.group is not None and self.group.live:
            self.group.finish(self.turn_clock.elapsed() / 1000 if self.turn_live else None)
        self.group = None
        self.turn_pending = []
        # yanıtta oluşan dosyalar cevabın altında kart olarak
        for path, edited in self.turn_files.items():
            self._add(FileCard(Path(path), edited, self.file_opened.emit))
        self.turn_files = {}

    def _close_bubble(self, summary: str = ""):
        self._close_group()
        if self.bubble is not None:
            self.flush()
            self.bubble.finish(summary)
            self.bubble = None

    def end_turn(self, summary: str):
        self.hide_waiting()
        self.flush()
        self._close_bubble(summary)
        self.end_segment()

    def end_segment(self):
        self.current_text = self.current_thinking = None

    def append_text(self, delta: str):
        if self.current_text is None:
            if not delta.strip():
                return
            self.hide_waiting()
            self.current_text = RichText()
            self.streams.append(self.current_text)
            self._add(self.current_text)
            self.turn_pending.append(self.current_text)
            self.current_thinking = None
        self.current_text.append(delta)

    def append_thinking(self, delta: str):
        if self.current_thinking is None:
            self.hide_waiting()
            self.current_thinking = ThinkingView()
            self.streams.append(self.current_thinking.text)
            self._add(self.current_thinking)
            self.turn_pending.append(self.current_thinking)
            self.current_text = None
        self.current_thinking.text.append(delta)

    def start_tool(self, call_id: str, name: str, args: dict):
        self.hide_waiting()
        if self.group is None:
            # grup, bu yanıtta araçtan önce yazılan ilk ara metnin yerine yerleşir
            self.group = WorkGroup(live=self.turn_live)
            first = self.turn_pending[0] if self.turn_pending else None
            index = self.cur.indexOf(first) if first is not None else -1
            if index >= 0:
                self.cur.insertWidget(index, self.group)
            else:
                self._add(self.group)
        # araçtan önceki ara metinler ("şimdi arıyorum…") de gruba taşınır; son yanıt dışarıda kalır
        for w in self.turn_pending:
            self.cur.removeWidget(w)
            self.group.add(w)
        self.turn_pending = []
        card = ToolCard(name, args)
        card.root = self.root  # üretilen resimlerin göreli yolları buna göre
        self.tools[call_id] = card
        if name in ("write_file", "edit_file") and args.get("path"):
            self.tool_files[call_id] = (str(Path(self.root or ".", args["path"]).resolve()), name == "edit_file")
        self.group.add(card)
        self.group.add_step(f"{tool_label(name)}  {summarize_args(name, args)}")
        self.group.update_header(self.turn_clock.elapsed() / 1000 if self.group.live else None)
        self.end_segment()

    def end_tool(self, call_id: str, result: str, is_error: bool, live: bool = True):
        if card := self.tools.get(call_id):
            card.finish(result, is_error)
            if self.group is not None and card.parent() is self.group.body:
                self.group.step_done(is_error)
                self.group.update_header()
        if call_id in self.tool_files:
            path, edited = self.tool_files.pop(call_id)
            if not is_error:
                # aynı dosya hem yazılıp hem düzenlendiyse "yeni" sayılır
                self.turn_files[path] = self.turn_files.get(path, edited) and edited
        if live:
            self.show_waiting()  # model sonucu okuyup yeniden yanıt hazırlıyor

    def render_history(self, messages: list, model_label: str):
        """Kaydedilmiş bir sohbeti (Claude ya da Ollama biçimi) yeniden çizer."""
        self.clear()
        pending: list[str] = []  # sonucu beklenen araç kartları (Ollama sırası)
        counter = 0
        in_turn = False
        for msg in messages:
            role, content = msg.get("role"), msg.get("content")
            if role == "user":
                if msg.get("_program"):
                    continue  # programın modele verdiği adım/uyarı mesajı: kullanıcının yazdığı değil
                if isinstance(content, str):
                    self.add_user(content, stamp="")
                    in_turn = False
                    if isinstance(msg.get("_plan"), list) and msg["_plan"]:
                        self.start_turn(model_label, show_time=False)
                        in_turn = True
                        self.show_plan(msg["_plan"])
                else:
                    for block in content:
                        if block.get("type") == "tool_result":
                            self.end_tool(block["tool_use_id"], str(block.get("content", "")),
                                          block.get("is_error", False), live=False)
            elif role == "assistant":
                if not in_turn:
                    self.start_turn(model_label, show_time=False)
                    in_turn = True
                if isinstance(content, str):
                    self.append_text(content)
                else:
                    for block in content:
                        if block.get("type") == "text":
                            self.append_text(block["text"] + "\n\n")
                        elif block.get("type") == "tool_use":
                            self.start_tool(block["id"], block["name"], block.get("input") or {})
                for call in msg.get("tool_calls") or []:
                    counter += 1
                    call_id = f"h{counter}"
                    fn = call.get("function", {})
                    args = fn.get("arguments")
                    if isinstance(args, str):  # OpenAI biçimi: argümanlar JSON metni
                        try:
                            args = json.loads(args)
                        except ValueError:
                            args = {}
                    self.start_tool(call_id, fn.get("name", "?"), args if isinstance(args, dict) else {})
                    pending.append(call_id)
            elif role == "tool" and pending:
                self.end_tool(pending.pop(0), str(content), str(content).startswith("Error"), live=False)
        self._close_bubble()
        self.flush()
