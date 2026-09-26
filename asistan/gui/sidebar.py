"""Sol panelin API'ler ve Ajanlar sekmeleri."""

import threading

from PySide6.QtCore import QObject, QSize, Qt, QTimer, QUrl, Signal
from PySide6.QtGui import QAction, QColor, QDesktopServices, QIcon, QPainter, QPixmap
from PySide6.QtWidgets import (
    QApplication, QCheckBox, QComboBox, QDialog, QDialogButtonBox, QFormLayout, QGridLayout, QHBoxLayout, QLabel,
    QFrame, QLineEdit, QListWidget, QListWidgetItem, QMenu, QMessageBox, QPlainTextEdit, QPushButton,
    QScrollArea, QSizePolicy, QToolButton, QVBoxLayout, QWidget,
)

from ..connections import (
    ANTHROPIC_KEY, AUTH_MODES, LLM_PRESETS, Connection, describe_http_error, fetch_llm_models,
    remove_connection, save_connections, test_anthropic, test_tool_api,
)
from ..keystore import backend_name, delete_secret, get_secret, set_secret
from .. import api_catalog
from ..profiles import AgentProfile, save_profiles
from .chat import TOOL_LABELS
from .icons import AGENT_ICONS, agent_icon, icon, pixmap
from .widgets import RowButton
from .theme import C

# "ekibe ver" ve "ajana görev ver" yalnızca ana asistanda; resme bakma ve uzmana danışma her ajanda hep açık
AGENT_TOOLS = [t for t in TOOL_LABELS
               if t not in ("start_team_task", "delegate_to_agent", "look_at_image", "ask_specialist", "find_api", "check_installed", "open_app",
                             "install_python_package", "claude_code", "codex", "gemini_cli", "cli_step")]


# ---------------------------------------------------------------- yardımcılar

class _Job(QObject):
    done = Signal(object, object)  # sonuç, hata


def run_in_background(fn, on_done, parent: QObject):
    """`fn`'i ayrı iş parçacığında çalıştırır; `on_done(sonuç, hata)` GUI iş parçacığında çağrılır."""
    job = _Job(parent)
    job.done.connect(on_done)
    job.done.connect(job.deleteLater)

    def work():
        try:
            result, error = fn(), None
        except Exception as e:
            result, error = None, e
        try:
            job.done.emit(result, error)
        except RuntimeError:  # sonucu bekleyen pencere bu arada kapandı
            pass

    threading.Thread(target=work, daemon=True).start()


def _dot(color: str) -> QIcon:
    pix = QPixmap(12, 12)
    pix.fill(Qt.transparent)
    p = QPainter(pix)
    p.setRenderHint(QPainter.Antialiasing)
    p.setBrush(QColor(color))
    p.setPen(Qt.NoPen)
    p.drawEllipse(2, 2, 8, 8)
    p.end()
    return QIcon(pix)


def _header_item(text: str) -> QListWidgetItem:
    item = QListWidgetItem(text)
    item.setFlags(Qt.NoItemFlags)
    item.setForeground(Qt.gray)
    f = item.font()
    f.setPixelSize(11)
    f.setBold(True)
    item.setFont(f)
    return item


def _dialog_buttons(dialog: QDialog) -> QDialogButtonBox:
    buttons = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Cancel)
    buttons.button(QDialogButtonBox.Save).setText("Kaydet")
    buttons.button(QDialogButtonBox.Save).setObjectName("primary")
    buttons.button(QDialogButtonBox.Cancel).setText("Vazgeç")
    buttons.accepted.connect(dialog.accept)
    buttons.rejected.connect(dialog.reject)
    return buttons


def _key_field(value: str) -> QLineEdit:
    edit = QLineEdit(value)
    edit.setEchoMode(QLineEdit.Password)
    eye = QAction("👁", edit)
    eye.setToolTip("Anahtarı göster / gizle")
    eye.triggered.connect(lambda: edit.setEchoMode(
        QLineEdit.Normal if edit.echoMode() == QLineEdit.Password else QLineEdit.Password))
    edit.addAction(eye, QLineEdit.TrailingPosition)
    return edit


# ---------------------------------------------------------------- API ekleme / düzenleme

class ApiDialog(QDialog):
    """Yeni bağlantı, mevcut bağlantı ya da Anthropic anahtarı (conn=None, anthropic=True)."""

    def __init__(self, conn: Connection | None = None, anthropic: bool = False, parent=None, preset: str = "",
                 template: Connection | None = None):
        super().__init__(parent)
        self.conn, self.anthropic = conn, anthropic
        self.setWindowTitle("Anthropic (Claude)" if anthropic else ("API'yi düzenle" if conn else "API ekle"))
        self.setMinimumWidth(560)
        form = QFormLayout(self)
        form.setContentsMargins(20, 20, 20, 20)
        form.setSpacing(10)
        self.form = form

        self.kind = QComboBox()
        self.kind.addItem("🧠  Model sağlayıcı — sohbette model olarak kullan", "llm")
        self.kind.addItem("🔌  Araç API'si — asistan gerektiğinde çağırsın", "tool")
        self.preset = QComboBox()
        self.preset.addItems(LLM_PRESETS)
        self.name = QLineEdit()
        self.url = QLineEdit()
        self.url.setPlaceholderText("https://…")
        self.key = _key_field(get_secret(ANTHROPIC_KEY) if anthropic else (conn.key if conn else ""))
        self.models = QLineEdit()
        self.models.setPlaceholderText("Test edince otomatik dolar (virgülle ayır)")
        self.description = QPlainTextEdit()
        self.description.setFixedHeight(84)
        self.description.setPlaceholderText(
            "Asistan bu açıklamaya bakarak ne zaman çağıracağına karar verir.\n"
            "Ör: Hava durumu. GET /weather?q=<şehir>&units=metric")
        self.auth = QComboBox()
        for mode, label in AUTH_MODES.items():
            self.auth.addItem(label, mode)
        self.auth_param = QLineEdit()
        self.auth_param.setPlaceholderText("ör. X-Api-Key ya da appid")

        self.login_session = None  # hesapla girişte (yöntem, süreli anahtar bilgisi): kaydederken saklanır
        self.login_btn = QPushButton("🔑  Hesabınla giriş yap — anahtar kopyalamadan", objectName="smallButton")
        self.login_btn.clicked.connect(self._login)

        test_row = QHBoxLayout()
        self.test_btn = QPushButton("Test et")
        self.test_btn.clicked.connect(self._test)
        self.test_result = QLabel(objectName="hint")
        self.test_result.setWordWrap(True)
        test_row.addWidget(self.test_btn)
        test_row.addWidget(self.test_result, 1)

        if anthropic:
            info = QLabel("Claude modelleri için anahtar. Boş bırakırsan ANTHROPIC_API_KEY ortam "
                          "değişkeni ya da `ant auth login` profili kullanılır.", objectName="hint")
            info.setWordWrap(True)
            form.addRow(info)
            form.addRow("API anahtarı:", self.key)
        else:
            form.addRow("Tür:", self.kind)
            form.addRow("Hazır ayar:", self.preset)
            form.addRow("Ad:", self.name)
            form.addRow("Adres:", self.url)
            form.addRow("API anahtarı:", self.key)
            form.addRow("", self.login_btn)
            form.addRow("Modeller:", self.models)
            form.addRow("Ne işe yarar:", self.description)
            form.addRow("Anahtar gönderimi:", self.auth)
            form.addRow("Parametre adı:", self.auth_param)
        form.addRow(test_row)
        form.addRow(_dialog_buttons(self))

        self.kind.currentIndexChanged.connect(self._kind_changed)
        self.preset.currentTextChanged.connect(self._apply_preset)
        self.preset.currentTextChanged.connect(self._update_fields)
        self.auth.currentIndexChanged.connect(self._update_fields)
        if conn:
            self.kind.setCurrentIndex(0 if conn.kind == "llm" else 1)
            self.kind.setEnabled(False)
            self.preset.blockSignals(True)
            self.preset.setCurrentText(conn.preset or "Özel (OpenAI uyumlu)")
            self.preset.blockSignals(False)
            self.name.setText(conn.name)
            self.url.setText(conn.base_url)
            self.models.setText(", ".join(conn.models))
            self.description.setPlainText(conn.description)
            self.auth.setCurrentIndex(max(self.auth.findData(conn.auth), 0))
            self.auth_param.setText(conn.auth_param)
        elif template is not None:  # hazır API'ler listesinden: alanlar dolu gelir, yalnızca anahtar girilir
            self.kind.setCurrentIndex(1)
            self.name.setText(template.name)
            self.url.setText(template.base_url)
            self.description.setPlainText(template.description)
            self.auth.setCurrentIndex(max(self.auth.findData(template.auth), 0))
            self.auth_param.setText(template.auth_param)
        elif not anthropic:
            if preset in LLM_PRESETS:  # menüden "OpenAI bağla…" gibi: sağlayıcı hazır seçili gelsin
                self.preset.blockSignals(True)
                self.preset.setCurrentText(preset)
                self.preset.blockSignals(False)
            self._apply_preset(self.preset.currentText())
        self._update_fields()

    def _set_row_visible(self, widget, visible: bool):
        self.form.setRowVisible(widget, visible)

    def _update_fields(self):
        if self.anthropic:
            return
        from .. import accounts

        llm = self.kind.currentData() == "llm"
        method = accounts.LOGINS.get(self.preset.currentText(), "")
        self._set_row_visible(self.login_btn, llm and accounts.available(method))
        self._set_row_visible(self.preset, llm and not self.conn)
        self._set_row_visible(self.models, llm)
        self._set_row_visible(self.description, not llm)
        self._set_row_visible(self.auth, not llm)
        self._set_row_visible(self.auth_param, not llm and self.auth.currentData() in ("header", "query"))

    def _kind_changed(self):
        if self.conn:
            return
        if self.kind.currentData() == "llm":
            self._apply_preset(self.preset.currentText())
        else:  # model sağlayıcı hazır ayarından kalan değerleri temizle
            self.name.clear()
            self.url.clear()
        self._update_fields()

    def _login(self):
        """Tarayıcıda hesapla giriş; alınan anahtar alana yazılır ve bağlantı denenir (accounts.py)."""
        from .. import accounts

        method = accounts.LOGINS.get(self.preset.currentText(), "")
        self.login_btn.setEnabled(False)
        self.test_result.setStyleSheet(f"color: {C['muted']}")
        self.test_result.setText("Tarayıcıda giriş yapıp onayla…")
        run_in_background(lambda: login_account(method, self), self._login_done, self)

    def _login_done(self, result, error):
        self.login_btn.setEnabled(True)
        if error:
            self.test_result.setStyleSheet(f"color: {C['error']}")
            self.test_result.setText("✗ Giriş yapılamadı: " + str(error)[:200])
            return
        key, session = result
        self.key.setText(key)
        self.login_session = session
        self._test()

    def _apply_preset(self, preset: str):
        url, _needs_key = LLM_PRESETS.get(preset, ("", True))
        self.url.setText(url)
        if not self.conn:
            self.name.setText("" if preset.startswith("Özel") else preset)
        self.models.clear()

    def _draft(self) -> Connection:
        """Formdaki değerlerle (kaydetmeden) bir bağlantı nesnesi."""
        c = self.conn or Connection(kind=self.kind.currentData(), name="", base_url="")
        draft = Connection(**{**c.__dict__})
        draft.name = self.name.text().strip()
        draft.base_url = self.url.text().strip()
        draft.preset = self.preset.currentText() if draft.kind == "llm" else ""
        draft.models = [m.strip() for m in self.models.text().split(",") if m.strip()]
        draft.description = self.description.toPlainText().strip()
        draft.auth = self.auth.currentData()
        draft.auth_param = self.auth_param.text().strip()
        return draft

    def _test(self):
        key = self.key.text().strip()
        self.test_btn.setEnabled(False)
        self.test_result.setStyleSheet(f"color: {C['muted']}")
        self.test_result.setText("Deneniyor…")
        if self.anthropic:
            fn = lambda: test_anthropic(key)
        else:
            draft = self._draft()
            if not draft.base_url:
                self._show_test(None, RuntimeError("Adres boş"))
                return
            if draft.kind == "llm":
                fn = lambda: fetch_llm_models(draft.base_url, key)
            else:
                fn = lambda: test_tool_api(draft, key)
        run_in_background(fn, self._show_test, self)

    def _show_test(self, result, error):
        self.test_btn.setEnabled(True)
        if error:
            self.test_result.setStyleSheet(f"color: {C['error']}")
            self.test_result.setText("✗ " + describe_http_error(error))
            return
        if isinstance(result, list):
            self.models.setText(", ".join(result))
            result = f"Bağlantı başarılı · {len(result)} model bulundu"
        self.test_result.setStyleSheet(f"color: {C['success']}")
        self.test_result.setText("✓ " + result)

    def accept(self):
        if self.anthropic:
            set_secret(ANTHROPIC_KEY, self.key.text().strip())
            super().accept()
            return
        draft = self._draft()
        if not draft.name or not draft.base_url:
            QMessageBox.warning(self, "Eksik bilgi", "Ad ve adres boş olamaz.")
            return
        if draft.needs_key and not self.key.text().strip():  # anahtarsız bağlantı her mesajda 401 verir
            from ..connections import account_hint

            QMessageBox.warning(self, "API anahtarı gerekli",
                                f"{draft.name or 'Bu sağlayıcı'} API anahtarı olmadan çalışmaz. Anahtarı yapıştır"
                                + (account_hint(draft.base_url) or "") + ".")
            return
        if draft.kind == "tool" and not draft.description:
            QMessageBox.warning(self, "Eksik bilgi",
                                "Asistanın bu API'yi ne zaman kullanacağını bilmesi için bir açıklama yaz.")
            return
        self.result_conn = draft
        self.result_key = self.key.text().strip()
        super().accept()


def login_account(method: str, parent) -> tuple[str, tuple | None]:
    """Hesapla giriş (arka plan iş parçacığında): (anahtar, oturum). Tarayıcı ve cihaz kodu GUI'de gösterilir."""
    from .. import accounts

    def open_url(url: str):
        QTimer.singleShot(0, parent, lambda: QDesktopServices.openUrl(QUrl(url)))

    if method == "openrouter":
        return accounts.openrouter(open_url), None
    if method == "huggingface":
        def show_code(code: str, url: str):
            def show():
                QApplication.clipboard().setText(code)
                QDesktopServices.openUrl(QUrl(url))
                QMessageBox.information(parent, "Hugging Face girişi",
                                        f"Tarayıcıda açılan sayfada bu kodu gir (panoya kopyalandı):\n\n{code}\n\n"
                                        "Onayladıktan sonra bu pencereyi kapatabilirsin; program girişi kendisi alır.")
            QTimer.singleShot(0, parent, show)

        tokens = accounts.huggingface(show_code)
        return tokens["access_token"], ("huggingface", tokens)
    raise RuntimeError("Bu sağlayıcıda hesapla giriş yok.")


# ---------------------------------------------------------------- API'ler sekmesi

class ApiPanel(QWidget):
    changed = Signal()  # bağlantılar eklendi / değişti / silindi
    account_requested = Signal(str)  # "cli:codex" / "openrouter": pencere kurulum ve giriş akışını başlatır

    def __init__(self, connections: list[Connection], parent=None, settings=None):
        super().__init__(parent)
        self.connections = connections
        self.settings = settings  # hazır API'lerden kapatılanlar: settings.extra["api_off"]
        self.status: dict[str, tuple[bool, str]] = {}  # id -> (başarılı mı, mesaj)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(8)
        add = RowButton("API Ekle", "", "+", "outlineRow")
        add.setCursor(Qt.PointingHandCursor)
        add.clicked.connect(self._add)
        lay.addWidget(add)
        catalog_btn = RowButton("Hazır API'ler", "", "≡", "outlineRow")
        catalog_btn.setCursor(Qt.PointingHandCursor)
        catalog_btn.setToolTip("Hava durumu, döviz, haberler, deprem… tek tıkla ekle")
        catalog_btn.clicked.connect(self.open_catalog)
        lay.addWidget(catalog_btn)
        self.list = QListWidget(objectName="chatList")
        self.list.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.list.setTextElideMode(Qt.ElideRight)
        self.list.itemClicked.connect(self._edit_item)
        self.list.setContextMenuPolicy(Qt.CustomContextMenu)
        self.list.customContextMenuRequested.connect(self._menu)
        lay.addWidget(self.list, 1)
        test_all = QPushButton("Tümünü test et", objectName="smallButton")
        test_all.clicked.connect(self.test_all)
        lay.addWidget(test_all)
        where = "KDE Cüzdanı'nda" if backend_name() != "dosya" else "yalnızca sana açık bir dosyada"
        hint = QLabel(f"🔒 Anahtarlar {where} saklanır.", objectName="hint")
        hint.setWordWrap(True)
        lay.addWidget(hint)
        self.refresh()

    def refresh(self):
        """Her satırın altında durumu: ne işe yaradığı belli olsun (2026-09-26: kullanıcı "hiçbiri işe yaramıyor gibi"
        dedi — üç sağlayıcının üçü de anahtarsızdı ve yalnızca gri nokta görünüyordu)."""
        import os

        from .. import accounts, cli_agents
        from ..connections import _REJECTED

        self.list.clear()
        self.list.addItem(_header_item("HESABINLA — API ANAHTARI GEREKMEZ"))
        for a in cli_agents.AGENTS.values():
            if cli_agents.available(a.provider):
                self._status_row(f"__account__:{a.provider}", a.title, f"✓ {a.via} hazır", True)
            else:
                how = "giriş yap" if cli_agents.installed(a.provider) else "kur"
                self._status_row(f"__account__:{a.provider}", a.title, f"{a.via} · tıkla, {how}", None,
                                 tip=f"{a.title}: {a.via} çalışan resmi program. Tıklayınca "
                                     + ("tarayıcıda giriş yaparsın." if how == "giriş yap"
                                        else "program kurulur, sonra tarayıcıda giriş yaparsın."))
        router = any("openrouter.ai" in c.base_url and c.usable for c in self.connections)
        if not router and accounts.available("openrouter"):
            self._status_row("__account__:openrouter", "OpenRouter", "tıkla, tarayıcıda giriş yap", None,
                             tip="Tek hesapla yüzlerce model, ücretsizler dahil. Anahtar kendiliğinden alınır.")
        self.list.addItem(_header_item("API ANAHTARIYLA"))
        claude_key = bool(get_secret(ANTHROPIC_KEY) or os.environ.get("ANTHROPIC_API_KEY"))
        self._add_row("anthropic", "Anthropic (Claude)", "☁", claude_key)
        for c in self.connections:
            if c.kind == "llm":
                self._add_row(c.id, c.name, "🧠", not c.needs_key or bool(get_secret(f"conn:{c.id}")),
                              c.id in _REJECTED)
        tools = [c for c in self.connections if c.kind == "tool"]
        self.list.addItem(_header_item("ARAÇ API'LERİ"))
        off = set(self.settings.extra.get("api_off", [])) if self.settings else set()
        free = [e for e in api_catalog.CATALOG if e.free]
        ready = QListWidgetItem(f"≡  anahtarsız hazır araçlar (hava, döviz, deprem…)\n"
                                f"    {len([e for e in free if e.id not in off])}/{len(free)} açık · asistan gerekince kullanır")
        ready.setData(Qt.UserRole, "__catalog__")
        ready.setToolTip("Asistan bunları kurulum gerektirmeden kullanır. Açıp kapatmak için tıkla.")
        self.list.addItem(ready)
        for c in tools:
            self._add_row(c.id, c.name + ("" if c.enabled else "  (kapalı)"), "🔌",
                          not c.needs_key or bool(get_secret(f"conn:{c.id}")))

    def _status_row(self, data: str, name: str, status: str, ok: bool | None, icon: str = "🔑", tip: str = ""):
        color = C["muted"] if ok is None else (C["success"] if ok else C["error"])
        item = QListWidgetItem(_dot(color), f"{icon}  {name}\n    {status}")
        item.setData(Qt.UserRole, data)
        item.setToolTip(tip or status)
        self.list.addItem(item)

    def _add_row(self, conn_id: str, name: str, icon: str, has_key: bool = True, rejected: bool = False):
        ok, msg = self.status.get(conn_id, (None, "henüz denenmedi"))
        tip = msg
        if not has_key:
            ok, msg, tip = False, "anahtar yok · tıkla, gir", "Anahtarı girmek için tıkla; kullanmayacaksan sağ tık → Sil."
        elif rejected and ok is not True:
            ok, msg = False, "anahtar reddedildi · tıkla, düzelt"
        self._status_row(conn_id, name, msg.replace("Bağlantı başarılı", "bağlı"), ok, icon, tip)

    def _find(self, conn_id: str) -> Connection | None:
        return next((c for c in self.connections if c.id == conn_id), None)

    # ---- ekle / düzenle / sil
    def open_catalog(self):
        ApiCatalogDialog(self).exec()
        self.refresh()
        self.changed.emit()

    def add_from_catalog(self, entry) -> bool:
        """Anahtar isteyen hazır API'yi ekler: alanlar dolu gelir, kullanıcı yalnızca anahtarı yapıştırır."""
        dlg = ApiDialog(parent=self, template=entry.connection())
        if not dlg.exec():
            return False
        conn = dlg.result_conn
        self.connections.append(conn)
        conn.key = dlg.result_key
        save_connections(self.connections)
        self.refresh()
        self.changed.emit()
        return True

    def add_claude(self):
        """Claude (Anthropic) API anahtarı penceresi."""
        self.edit("anthropic")

    def _add(self, preset: str = ""):
        dlg = ApiDialog(parent=self, preset=preset if isinstance(preset, str) else "")
        if dlg.exec():
            self.add_ready(dlg.result_conn, dlg.result_key, dlg.login_session)

    def add_ready(self, conn: Connection, key: str, session: tuple | None = None) -> Connection:
        """Hazır bağlantıyı ekler (pencereden ya da hesapla girişten); session: (yöntem, süreli anahtar bilgisi)."""
        from .. import accounts

        self.connections.append(conn)
        conn.key = key
        if session:
            accounts.save_session(conn.id, *session)
        save_connections(self.connections)
        self.refresh()
        self.changed.emit()
        self.test(conn.id)
        return conn

    def _edit_item(self, item: QListWidgetItem):
        conn_id = item.data(Qt.UserRole)
        if conn_id == "__catalog__":
            self.open_catalog()
        elif conn_id and conn_id.startswith("__account__:"):
            self.account_requested.emit(conn_id.split(":", 1)[1])
        elif conn_id:
            self.edit(conn_id)

    def edit(self, conn_id: str):
        if conn_id == "anthropic":
            if ApiDialog(anthropic=True, parent=self).exec():
                self.changed.emit()
                self.test("anthropic")
            return
        conn = self._find(conn_id)
        dlg = ApiDialog(conn, parent=self)
        if dlg.exec():
            new = dlg.result_conn
            for attr in ("name", "base_url", "preset", "models", "description", "auth", "auth_param"):
                setattr(conn, attr, getattr(new, attr))
            old = get_secret(f"conn:{conn.id}")
            conn.key = dlg.result_key
            if dlg.login_session:
                from .. import accounts

                accounts.save_session(conn.id, *dlg.login_session)
            elif dlg.result_key != old:  # anahtar elle değişti: eski girişin yenilemesi onu ezmesin
                delete_secret(f"oturum:{conn.id}")
            save_connections(self.connections)
            self.refresh()
            self.changed.emit()
            self.test(conn.id)

    def _menu(self, pos):
        item = self.list.itemAt(pos)
        conn_id = item.data(Qt.UserRole) if item else None
        if not conn_id:
            return
        conn = self._find(conn_id)
        menu = QMenu(self)
        edit = menu.addAction("Düzenle")
        test = menu.addAction("Test et")
        toggle = delete = None
        if conn:
            if conn.kind == "tool":
                toggle = menu.addAction("Kapat" if conn.enabled else "Aç")
            menu.addSeparator()
            delete = menu.addAction("Sil")
        chosen = menu.exec(self.list.mapToGlobal(pos))
        if chosen is edit:
            self.edit(conn_id)
        elif chosen is test:
            self.test(conn_id)
        elif toggle is not None and chosen is toggle:
            conn.enabled = not conn.enabled
            save_connections(self.connections)
            self.refresh()
            self.changed.emit()
        elif delete is not None and chosen is delete:
            if QMessageBox.question(self, "API'yi sil", f"“{conn.name}” ve anahtarı silinsin mi?") \
                    == QMessageBox.Yes:
                remove_connection(self.connections, conn)
                self.status.pop(conn_id, None)
                self.refresh()
                self.changed.emit()

    # ---- test
    def test_all(self):
        import os

        if get_secret(ANTHROPIC_KEY) or os.environ.get("ANTHROPIC_API_KEY"):
            self.test("anthropic")
        for c in self.connections:
            if not c.needs_key or get_secret(f"conn:{c.id}"):  # anahtarsızı denemenin anlamı yok (satırda yazıyor)
                self.test(c.id)

    def showEvent(self, event):
        super().showEvent(event)
        if not getattr(self, "_tested_once", False):  # sekme ilk açılınca durumlar kendiliğinden denensin
            self._tested_once = True
            self.test_all()

    def test(self, conn_id: str):
        conn = self._find(conn_id)
        if conn_id == "anthropic":
            fn = lambda: test_anthropic(get_secret(ANTHROPIC_KEY))
        elif conn is None:
            return
        elif conn.kind == "llm":
            fn = lambda: fetch_llm_models(conn.base_url, conn.key)
        else:
            fn = lambda: test_tool_api(conn, conn.key)
        self.status[conn_id] = (None, "Deneniyor…")
        self.refresh()
        run_in_background(fn, lambda result, error: self._tested(conn_id, result, error), self)

    def _tested(self, conn_id: str, result, error):
        if error:
            self.status[conn_id] = (False, "✗ " + describe_http_error(error))
        else:
            if isinstance(result, list):
                conn = self._find(conn_id)
                if conn and result and result != conn.models:
                    conn.models = result
                    save_connections(self.connections)
                    self.changed.emit()
                result = f"Bağlantı başarılı · {len(result)} model"
            self.status[conn_id] = (True, "✓ " + result)
        self.refresh()


# ---------------------------------------------------------------- ajan düzenleme

class AgentDialog(QDialog):
    def __init__(self, profile: AgentProfile | None, providers: list[tuple[str, str]], models_for,
                 parent=None):
        super().__init__(parent)
        self.setWindowTitle("Ajanı düzenle" if profile else "Yeni ajan")
        self.setMinimumWidth(600)
        self.models_for = models_for
        p = profile or AgentProfile(name="")
        form = QFormLayout(self)
        form.setContentsMargins(20, 20, 20, 20)
        form.setSpacing(10)

        top = QHBoxLayout()
        self.icon = QComboBox(toolTip="Ajanın simgesi")
        self.icon.setIconSize(QSize(16, 16))
        for name in AGENT_ICONS:
            self.icon.addItem(icon(name, C["text2"], 16), "", name)
        self.icon.setCurrentIndex(max(0, self.icon.findData(agent_icon(p.icon))))
        self.icon.setFixedWidth(64)
        self.name = QLineEdit(p.name)
        self.name.setPlaceholderText("ör. Çevirmen")
        top.addWidget(self.icon)
        top.addWidget(self.name, 1)
        self.description = QLineEdit(p.description)
        self.description.setPlaceholderText("Listede görünen kısa açıklama")
        self.prompt = QPlainTextEdit(p.prompt)
        self.prompt.setMinimumHeight(150)
        self.prompt.setPlaceholderText(
            "Bu ajanın rolünü ve nasıl çalışacağını anlat.\n"
            "ör. Sen deneyimli bir çevirmensin. Metinleri Türkçe ile İngilizce arasında, anlamı ve "
            "üslubu koruyarak çevirirsin…")

        model_row = QHBoxLayout()
        self.provider = QComboBox()
        self.provider.addItem("Sohbette seçili model", "")
        for label, data in providers:
            self.provider.addItem(label, data)
        self.model = QComboBox()
        self.model.setEditable(True)
        self.model.setMinimumWidth(220)
        model_row.addWidget(self.provider)
        model_row.addWidget(self.model, 1)
        self.provider.currentIndexChanged.connect(self._fill_models)
        self.provider.setCurrentIndex(max(self.provider.findData(p.provider), 0))
        self._fill_models()
        if p.model:
            self.model.setCurrentText(p.model)

        tools_box = QWidget()
        grid = QGridLayout(tools_box)
        grid.setContentsMargins(0, 0, 0, 0)
        self.tool_checks: dict[str, QCheckBox] = {}
        for i, name in enumerate(AGENT_TOOLS):
            cb = QCheckBox(TOOL_LABELS.get(name, (name,))[0])
            cb.setChecked(p.tools is None or name in p.tools)
            self.tool_checks[name] = cb
            grid.addWidget(cb, i // 3, i % 3)

        form.addRow("Ad:", top)
        form.addRow("Açıklama:", self.description)
        form.addRow("Rol tarifi:", self.prompt)
        form.addRow("Model:", model_row)
        form.addRow("Araçlar:", tools_box)
        form.addRow(_dialog_buttons(self))
        self.profile = p

    def _fill_models(self):
        current = self.model.currentText()
        self.model.clear()
        provider = self.provider.currentData()
        self.model.setEnabled(bool(provider))
        if provider:
            self.model.addItems(self.models_for(provider))
            if current and self.model.findText(current) >= 0:
                self.model.setCurrentText(current)

    def accept(self):
        if not self.name.text().strip():
            QMessageBox.warning(self, "Eksik bilgi", "Ajanın bir adı olmalı.")
            return
        p = self.profile
        p.name = self.name.text().strip()
        p.icon = self.icon.currentData() or "bot"
        p.description = self.description.text().strip()
        p.prompt = self.prompt.toPlainText().strip()
        p.provider = self.provider.currentData()
        p.model = self.model.currentText().strip() if p.provider else ""
        chosen = [n for n, cb in self.tool_checks.items() if cb.isChecked()]
        p.tools = None if len(chosen) == len(AGENT_TOOLS) else chosen
        super().accept()


# ---------------------------------------------------------------- Ajanlar sekmesi

class AgentRow(QFrame):
    """Ajan kartı (baloncuk): simge · ad · açıklama · model. Araçlar ipucunda."""

    clicked = Signal(str)
    menu_requested = Signal(str, object)  # profil id, global konum

    def __init__(self, p: AgentProfile, model_text: str, own_model: bool):
        super().__init__(objectName="agentRow")
        self.profile_id = p.id
        self.icon_name = agent_icon(p.icon)
        self.setCursor(Qt.PointingHandCursor)
        row = QHBoxLayout(self)
        row.setContentsMargins(10, 10, 4, 10)
        row.setSpacing(10)
        self.badge = QLabel(objectName="agentBadge")
        self.badge.setFixedSize(30, 30)
        self.badge.setAlignment(Qt.AlignCenter)
        row.addWidget(self.badge, 0, Qt.AlignTop)
        col = QVBoxLayout()
        col.setSpacing(2)
        col.addWidget(QLabel(p.name, objectName="agentName"))
        if p.description:
            col.addWidget(QLabel(p.description, objectName="agentDesc"))
        col.addSpacing(2)
        col.addWidget(QLabel(model_text + ("  · kendi" if own_model else ""), objectName="agentMeta"))
        row.addLayout(col, 1)
        more = QToolButton(objectName="iconButton", toolTip="Düzenle, kopyala, sil")
        more.setIcon(icon("more", C["muted"], 15, active=C["text"]))
        more.setCursor(Qt.PointingHandCursor)
        more.clicked.connect(lambda: self.menu_requested.emit(p.id, more.mapToGlobal(more.rect().bottomLeft())))
        row.addWidget(more, 0, Qt.AlignTop)
        # ⋯ yalnızca üzerine gelince ya da seçiliyken görünür; yer kaplamaya devam eder, kart kaymaz
        self.more = more
        keep = more.sizePolicy()
        keep.setRetainSizeWhenHidden(True)
        more.setSizePolicy(keep)
        if p.tools is None:
            tools_text = "tüm araçlar"
        else:
            names = [TOOL_LABELS.get(t, (t,))[0] for t in p.tools if t not in ("look_at_image", "ask_specialist")]
            tools_text = " · ".join(names) or "araç yok"
        how = "kendi modeli" if own_model else ("işine göre program seçiyor" if model_text.startswith("otomatik")
                                                 else "sohbette seçili model")
        self.setToolTip(f"model: {model_text} ({how})\naraçlar: {tools_text}")
        for w in self.findChildren(QLabel):
            w.setAttribute(Qt.WA_TransparentForMouseEvents)
            if w is not self.badge:
                # dar kenar çubuğunda taşmasın: genişliği panel belirlesin, metin alt satıra geçsin
                w.setWordWrap(True)
                w.setMinimumWidth(1)
                w.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
        self.set_selected(False)

    def set_selected(self, on: bool):
        self.badge.setPixmap(pixmap(self.icon_name, C["accent"] if on else C["text2"], 16))
        self.more.setVisible(on or self.underMouse())
        self.setProperty("selected", on)
        self.style().unpolish(self)
        self.style().polish(self)

    def enterEvent(self, event):
        self.more.show()
        super().enterEvent(event)

    def leaveEvent(self, event):
        self.more.setVisible(bool(self.property("selected")))
        super().leaveEvent(event)

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.LeftButton:
            self.clicked.emit(self.profile_id)
        elif event.button() == Qt.RightButton:
            self.menu_requested.emit(self.profile_id, event.globalPosition().toPoint())
        super().mouseReleaseEvent(event)


class AgentPanel(QWidget):
    agent_chosen = Signal(str)  # profil id -> bu ajanla yeni sohbet
    changed = Signal()

    def __init__(self, profiles: list[AgentProfile], providers_fn, models_for, model_fn=None,
                 experts_fn=None, parent=None):
        super().__init__(parent)
        self.profiles = profiles
        self.providers_fn, self.models_for = providers_fn, models_for
        self.model_fn = model_fn or (lambda p: (p.model or "sohbetteki model", bool(p.provider)))
        self.experts_fn = experts_fn or (lambda: [])
        self.selected = ""
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(8)
        add = RowButton("Yeni Ajan", "", "+", "outlineRow")
        add.clicked.connect(self._add)
        lay.addWidget(add)
        lay.addSpacing(4)
        lay.addWidget(QLabel("EKİP", objectName="label"))
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        scroll.setStyleSheet("background: transparent;")
        inner = QWidget()
        inner.setStyleSheet("background: transparent;")
        self.rows = QVBoxLayout(inner)
        self.rows.setContentsMargins(0, 0, 0, 0)
        self.rows.setSpacing(6)
        scroll.setWidget(inner)
        lay.addWidget(scroll, 1)
        lay.addWidget(QFrame(objectName="rule"))
        lay.addSpacing(4)
        lay.addWidget(QLabel("UZMAN MODELLER", objectName="label"))
        self.experts = QLabel(objectName="agentMeta")
        self.experts.setTextFormat(Qt.RichText)
        self.experts.setWordWrap(True)
        self.experts.setToolTip("Ajanlar kendi yapamadıkları işlerde bu modellere danışır. Ayarlar'dan değiştirilir.")
        lay.addWidget(self.experts)
        hint = QLabel("tıkla: sohbet · sağ tık: düzenle", objectName="keyHint")
        lay.addSpacing(4)
        lay.addWidget(hint)
        self.refresh()

    def refresh(self):
        while self.rows.count():
            w = self.rows.takeAt(0).widget()
            if w:
                w.hide()
                w.deleteLater()
        for p in self.profiles:
            text, own = self.model_fn(p)
            row = AgentRow(p, text, own)
            row.clicked.connect(self.agent_chosen)
            row.menu_requested.connect(self._menu)
            row.set_selected(p.id == self.selected)
            self.rows.addWidget(row)
        self.rows.addStretch()
        self.refresh_experts()

    def refresh_experts(self):
        # iki sütun: başlıklar solda, modeller aynı hizadan başlar
        rows = "".join(f'<tr><td style="padding-right:10px">{title}</td>'
                       f'<td style="color:{C["text2"]}">{model}</td></tr>' for title, model in self.experts_fn())
        self.experts.setText(f"<table cellspacing=0 cellpadding=1>{rows}</table>" if rows else "—")

    def select(self, profile_id: str):
        self.selected = profile_id
        for i in range(self.rows.count()):
            w = self.rows.itemAt(i).widget()
            if isinstance(w, AgentRow):
                w.set_selected(w.profile_id == profile_id)

    def _save(self):
        save_profiles(self.profiles)
        self.refresh()
        self.changed.emit()

    def _add(self):
        dlg = AgentDialog(None, self.providers_fn(), self.models_for, self)
        if dlg.exec():
            self.profiles.append(dlg.profile)
            self._save()

    def _menu(self, profile_id: str, pos):
        p = next((x for x in self.profiles if x.id == profile_id), None)
        if p is None:
            return
        menu = QMenu(self)
        chat = menu.addAction("yeni sohbet başlat")
        # dosyadan gelen ajan (ajanlar/*.md): kaynağı dosyası, düzenlemek dosyayı açar
        edit = menu.addAction("dosyayı aç" if p.source else "düzenle")
        copy = menu.addAction("kopyasını oluştur")
        menu.addSeparator()
        delete = menu.addAction("sil")
        chosen = menu.exec(pos)
        if chosen is chat:
            self.agent_chosen.emit(p.id)
        elif chosen is edit and p.source:
            QDesktopServices.openUrl(QUrl.fromLocalFile(p.source))
        elif chosen is edit:
            if AgentDialog(p, self.providers_fn(), self.models_for, self).exec():
                self._save()
        elif chosen is copy:
            clone = AgentProfile(**{**p.__dict__, "name": p.name + " (kopya)", "source": ""})
            clone.id = AgentProfile(name="").id
            self.profiles.insert(self.profiles.index(p) + 1, clone)
            self._save()
        elif chosen is delete and p.source:
            QMessageBox.information(self, "Ajanı sil", f"“{p.name}” bir dosyadan geliyor. Silmek için bu dosyayı "
                                    f"silin, program yeniden açılınca listeden kalkar:\n\n{p.source}")
        elif chosen is delete:
            if QMessageBox.question(self, "Ajanı sil", f"“{p.name}” silinsin mi?") == QMessageBox.Yes:
                self.profiles.remove(p)
                self._save()


class ApiCatalogDialog(QDialog):
    """Hazır API'ler: anahtarsızlar açılıp kapatılır, anahtar isteyenler tek tıkla eklenir."""

    def __init__(self, panel: "ApiPanel"):
        super().__init__(panel)
        self.panel = panel
        self.setWindowTitle("Hazır API'ler")
        self.setMinimumSize(660, 580)
        outer = QVBoxLayout(self)
        outer.setContentsMargins(20, 18, 20, 16)
        intro = QLabel("Asistan anahtarsız API'leri kurulum gerektirmeden kullanır. Anahtar isteyenleri "
                       "“ekle” ile bağlayabilirsin: alanlar dolu gelir, yalnızca anahtarı yapıştırırsın.",
                       objectName="hint")
        intro.setWordWrap(True)
        outer.addWidget(intro)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        inner = QWidget()
        self.rows = QVBoxLayout(inner)
        self.rows.setSpacing(4)
        scroll.setWidget(inner)
        outer.addWidget(scroll, 1)
        close = QPushButton("Kapat", objectName="primary")
        close.clicked.connect(self.accept)
        outer.addWidget(close, 0, Qt.AlignRight)
        self._fill()

    def _fill(self):
        while self.rows.count():
            item = self.rows.takeAt(0)
            if item.widget():
                item.widget().hide()
                item.widget().deleteLater()
        settings = self.panel.settings
        off = set(settings.extra.get("api_off", [])) if settings else set()
        added = {c.base_url.rstrip("/") for c in self.panel.connections if c.kind == "tool"}
        for category in api_catalog.CATEGORIES:
            label = QLabel(category.replace("i", "İ").upper(), objectName="label")
            label.setContentsMargins(0, 12, 0, 2)
            self.rows.addWidget(label)
            for e in (x for x in api_catalog.CATALOG if x.category == category):
                row = QFrame(objectName="agentRow")
                hl = QHBoxLayout(row)
                hl.setContentsMargins(10, 6, 8, 6)
                text = QLabel(f"<b>{e.name}</b>&nbsp;&nbsp;<span style='color:{C['text2']}'>{e.summary}</span>")
                text.setWordWrap(True)
                hl.addWidget(text, 1)
                if e.free:
                    box = QCheckBox("açık")
                    box.setChecked(e.id not in off)
                    box.setToolTip("anahtarsız — asistan hemen kullanabilir")
                    box.toggled.connect(lambda on, i=e.id: self._toggle(i, on))
                    hl.addWidget(box)
                elif e.base_url.rstrip("/") in added:
                    hl.addWidget(QLabel("eklendi ✓", objectName="keyHint"))
                else:
                    get = QPushButton("anahtar al", objectName="smallButton", toolTip=e.key_url)
                    get.clicked.connect(lambda _=False, u=e.key_url: QDesktopServices.openUrl(QUrl(u)))
                    add = QPushButton("ekle", objectName="smallButton")
                    add.clicked.connect(lambda _=False, x=e: self.panel.add_from_catalog(x) and self._fill())
                    hl.addWidget(get)
                    hl.addWidget(add)
                self.rows.addWidget(row)
        self.rows.addStretch()

    def _toggle(self, api_id: str, on: bool):
        settings = self.panel.settings
        if settings is None:
            return
        off = set(settings.extra.get("api_off", []))
        if on:
            off.discard(api_id)
        else:
            off.add(api_id)
        settings.extra["api_off"] = sorted(off)
        settings.save()


# ---------------------------------------------------------------- Kütüphaneler

class LibraryPanel(QWidget):
    """Kod kütüphaneleri: programın kullandıkları, ajanlara hazır gelenler ve sonradan kurulanlar.
    API'ler gibi: listelenir, eklenir (pip, internet gerekir), sonradan kurulanlar kaldırılabilir."""

    def __init__(self, parent=None):
        super().__init__(parent)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(8)
        self.add_btn = RowButton("Kütüphane Ekle", "", "+", "outlineRow")
        self.add_btn.setCursor(Qt.PointingHandCursor)
        self.add_btn.clicked.connect(self._add)
        lay.addWidget(self.add_btn)
        self.list = QListWidget(objectName="chatList")
        self.list.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.list.setTextElideMode(Qt.ElideRight)
        self.list.setContextMenuPolicy(Qt.CustomContextMenu)
        self.list.customContextMenuRequested.connect(self._menu)
        lay.addWidget(self.list, 1)
        self.state = QLabel("", objectName="hint")
        self.state.setWordWrap(True)
        lay.addWidget(self.state)
        hint = QLabel("Ajanlar Python kodu yazarken bunları kullanır; eksik olanı iş sırasında kendileri de kurabilir. "
                      "Sonradan kurulanları sağ tıkla kaldırabilirsin.", objectName="hint")
        hint.setWordWrap(True)
        lay.addWidget(hint)
        self.busy = False
        self.refresh()

    def refresh(self):
        from .. import libraries

        self.list.clear()
        try:
            libs = libraries.list_libraries()
        except Exception as e:  # noqa: BLE001 — liste okunamazsa panel boş kalmasın
            self.list.addItem(f"liste okunamadı: {e}")
            return
        titles = {"hazir": "AJANLARA HAZIR GELENLER", "kurulan": "SONRADAN KURULANLAR",
                  "program": "PROGRAMIN KULLANDIKLARI"}
        for group in ("hazir", "kurulan", "program"):
            rows = [x for x in libs if x.group == group]
            self.list.addItem(_header_item(titles[group]))
            if not rows:
                empty = QListWidgetItem("henüz yok — ＋ ile ekleyebilirsin" if group == "kurulan" else "—")
                empty.setFlags(Qt.NoItemFlags)
                empty.setForeground(QColor(C["muted"]))
                self.list.addItem(empty)
            for x in rows:
                missing = x.version == "kurulu değil"
                item = QListWidgetItem(_dot(C["error"] if missing else C["success"]), f"{x.name}  ·  {x.version}")
                item.setData(Qt.UserRole, x.name if x.removable else "")
                item.setToolTip((x.note + "\n" if x.note else "") + (
                    "Sonradan kuruldu — sağ tıkla kaldırabilirsin." if x.removable else
                    "Programla birlikte gelir; kaldırılamaz."))
                self.list.addItem(item)

    def _add(self):
        from PySide6.QtWidgets import QInputDialog

        if self.busy:
            return
        text, ok = QInputDialog.getText(self, "Kütüphane ekle",
                                        "Python kütüphanesinin adı (birden fazlaysa boşlukla ayır):\n"
                                        "ör. python-telegram-bot  ya da  seaborn scikit-learn")
        if not ok or not text.strip():
            return
        self._run(lambda: __import__("asistan.libraries", fromlist=["x"]).install(text),
                  f"{text.strip()} kuruluyor… (internet gerekir, birkaç dakika sürebilir)", "kuruldu ✓")

    def _menu(self, pos):
        item = self.list.itemAt(pos)
        name = item.data(Qt.UserRole) if item else ""
        if not name or self.busy:
            return
        menu = QMenu(self)
        delete = menu.addAction("Kaldır")
        if menu.exec(self.list.mapToGlobal(pos)) is delete and QMessageBox.question(
                self, "Kütüphaneyi kaldır", f"“{name}” kaldırılsın mı?") == QMessageBox.Yes:
            self._run(lambda: (__import__("asistan.libraries", fromlist=["x"]).remove(name), name)[1],
                      f"{name} kaldırılıyor…", "kaldırıldı")

    def _run(self, fn, busy_text: str, done_text: str):
        self.busy = True
        self.add_btn.setEnabled(False)
        self.state.setText(busy_text)

        def done(result, err):
            self.busy = False
            self.add_btn.setEnabled(True)
            self.state.setText(f"✗ {err}" if err else f"{result} {done_text}")
            self.refresh()

        run_in_background(fn, done, self)
