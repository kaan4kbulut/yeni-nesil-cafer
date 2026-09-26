"""Ana pencere: kenar çubuğu, sohbet, mesaj kutusu, sağ panel."""

import threading

from PySide6.QtCore import QElapsedTimer, Qt, QTimer, Signal
from PySide6.QtGui import QAction, QKeySequence, QShortcut
from PySide6.QtWidgets import (
    QApplication, QButtonGroup, QComboBox, QFrame, QHBoxLayout, QLabel, QMainWindow, QMenu, QMessageBox,
    QPushButton, QSplitter, QStackedWidget, QToolButton, QTreeWidget, QTreeWidgetItem, QVBoxLayout, QWidget,
)

from .. import __version__, catalog, factory, mcp, power, roster, specialists
from ..config import CONFIG_DIR, DATA_DIR, Settings
from ..connections import ANTHROPIC_KEY, load_connections
from ..keystore import set_secret
from ..profiles import load_profiles
from ..storage import Conversation, load_all
from ..work import load_tasks, Task

from .chat import ChatView
from .dialogs import InputBox
from .icons import icon, pixmap
from .panels import FIX_COMMAND, RightPanel
from .sidebar import AgentPanel, ApiPanel, LibraryPanel
from .sysmon import SystemMonitorLabel
from .theme import C, mono
from .widgets import RowButton, SearchBox
from .window_bar import BarMixin
from .window_chats import ChatsMixin
from .window_group import GroupMixin
from .window_help import HelpMixin
from .window_models import _models_for_menu, ModelsMixin
from .window_modes import ModesMixin
from .window_run import RunMixin
from .work import open_folder, TaskWorker, WorkPanel, WorkRoom
from .worker import AgentWorker


# ---------------------------------------------------------------- arka plan işçisi


# ---------------------------------------------------------------- küçük parçalar


# ---------------------------------------------------------------- ana pencere

class MainWindow(HelpMixin, ModelsMixin, BarMixin, ModesMixin, ChatsMixin, RunMixin, GroupMixin, QMainWindow):
    """Ana pencere. Konular karışım sınıflarında (window_*.py); burada kurulum, menü ve ortak yardımcılar."""
    pull_progress = Signal(str)  # menüden model indirirken alt çubuğa ilerleme
    problem = Signal(str, str)  # (tür, ayrıntı): yakalanmamış hata vb. başka iş parçacığından → rapor önerisi

    def __init__(self):
        super().__init__()
        self.settings = Settings.load()
        if self.settings.anthropic_api_key:  # eski sürümden: anahtarı anahtar zincirine taşı
            set_secret(ANTHROPIC_KEY, self.settings.anthropic_api_key)
            self.settings.anthropic_api_key = ""
            self.settings.save()
        self.connections = load_connections()
        self.profiles = load_profiles()
        if not self.settings.extra.get("gorsel_added"):
            from ..profiles import default_profiles, save_profiles

            if not any(p.id == "gorsel" for p in self.profiles):
                gorsel = next(p for p in default_profiles() if p.id == "gorsel")
                self.profiles.insert(min(3, len(self.profiles)), gorsel)
                save_profiles(self.profiles)
            self.settings.extra["gorsel_added"] = True
            self.settings.save()
        self.conversations = load_all()
        self.tasks = load_tasks()
        self.task_worker: TaskWorker | None = None
        self.task_queue: list[Task] = []
        self.probing = False
        self.conv: Conversation | None = None
        self.worker: AgentWorker | None = None
        self.dictation = None  # dikte (asistan/dictation.py): ilk kullanımda kurulur
        self.always_allowed = False
        self.tool_args: dict[str, tuple[str, dict]] = {}
        self.run_clock = QElapsedTimer()
        self.last_context = 0
        self.route = None  # otomatik modda bu mesajın gideceği (sağlayıcı, model) — ör. Claude Code
        self._label_font = mono(10.5)
        self._label_font.setLetterSpacing(self._label_font.SpacingType.AbsoluteSpacing, 1.5)
        self._stamp_font = mono(11)
        self.setWindowTitle(f"YENİ NESİL CAFER {__version__}")
        self.resize(1480, 900)
        self._build()
        self._build_menu()
        self._reload_models()
        self._refresh_sidebar()
        self.new_conversation()
        self.right.set_root(self.settings.workspace)
        QTimer.singleShot(200, self._refresh_models_status)
        QTimer.singleShot(1500, self._check_context)
        # en iyi modellerin listesi: açılışta ve 6 saatte bir kontrol; 20 saatten eskiyse internetten yenilenir
        QTimer.singleShot(3000, self._daily_model_update)
        self.pull_progress.connect(lambda text: self._notify(text, 600000))
        self.problem.connect(self._offer_report)
        self.model_timer = QTimer(self)
        self.model_timer.timeout.connect(self._daily_model_update)
        self.model_timer.start(6 * 3600 * 1000)
        # model kartları: açılıştan 1,5 dk sonra ve yarım saatte bir, kartsız model varsa (boşken) sınanır
        QTimer.singleShot(90_000, self._exam_models)
        self.cloud_timer = QTimer(self)  # bulut: dakikada bir hafıza eşitleme ve bekleyen işler
        self.cloud_timer.timeout.connect(self._cloud_tick)
        self.cloud_timer.start(60_000)
        QTimer.singleShot(8000, self._cloud_tick)
        self.exam_timer = QTimer(self)
        self.exam_timer.timeout.connect(self._exam_models)
        self.exam_timer.start(30 * 60 * 1000)

    # ---- kurulum
    def _build(self):
        self.splitter = QSplitter()
        self.splitter.setHandleWidth(1)
        self.setCentralWidget(self.splitter)

        # sol: kenar çubuğu
        self.sidebar = QWidget(objectName="sidebar")
        self.sidebar.setMinimumWidth(236)
        side = QVBoxLayout(self.sidebar)
        side.setContentsMargins(0, 0, 0, 0)
        side.setSpacing(0)
        nav = QVBoxLayout()
        nav.setContentsMargins(10, 14, 10, 14)
        nav.setSpacing(2)
        self.side_tabs = QButtonGroup(self)
        for i, text in enumerate(["Sohbet", "Grup Çalışması", "Ajanlar", "API'ler", "Kütüphaneler"]):
            b = RowButton(text, "", "›", "navRow", checkable=True)  # kısayol rakamı yazılmaz: sayı sanılıyordu
            b.setToolTip(f"Ctrl+{i + 1}")
            self.side_tabs.addButton(b, i)
            nav.addWidget(b)
        side.addLayout(nav)
        side.addWidget(QFrame(objectName="rule"))
        self.side_stack = QStackedWidget()
        self.side_tabs.idClicked.connect(self._side_tab_changed)
        side.addWidget(self.side_stack, 1)

        chats_page = QWidget()
        chats = QVBoxLayout(chats_page)
        chats.setContentsMargins(10, 14, 10, 6)
        chats.setSpacing(8)
        new_btn = RowButton("Yeni Sohbet", "Ctrl+N", "+", "outlineRow")
        new_btn.clicked.connect(lambda: self.new_conversation())
        chats.addWidget(new_btn)
        self.search = SearchBox("Ara", "Ctrl+K")
        self.search.textChanged.connect(self._refresh_sidebar)
        chats.addWidget(self.search)
        chats.addSpacing(6)
        # sağda seçim kutucuğu: sohbetleri tek tek seçip toplu silme / taşıma
        head = QHBoxLayout()
        head.setContentsMargins(6, 0, 0, 0)
        head.addWidget(QLabel("SOHBETLER", objectName="label"))
        head.addStretch()
        self.select_btn = QToolButton(objectName="iconButton", toolTip="sohbetleri seç — tek tek ya da hepsini")
        self.select_btn.setCheckable(True)
        self.select_btn.setIcon(icon("square-check", C["muted"], 15, active=C["accent"]))
        self.select_btn.setCursor(Qt.PointingHandCursor)
        self.select_btn.toggled.connect(self._set_select_mode)
        # seçim modunda kutucuğun solunda: tümünü seç / seçimi kaldır
        self.select_all_btn = QPushButton("Tümünü Seç", objectName="smallButton", toolTip="görünen bütün sohbetleri seç")
        self.select_all_btn.setCursor(Qt.PointingHandCursor)
        self.select_all_btn.ensurePolished()  # temanın yazı tipiyle ölç
        self.select_all_btn.setMinimumWidth(  # yazı "seçimi kaldır"a dönünce kesilmesin
            self.select_all_btn.fontMetrics().horizontalAdvance("Seçimi Kaldır") + 24)
        self.select_all_btn.clicked.connect(self._toggle_select_all)
        self.select_all_btn.hide()
        head.addWidget(self.select_all_btn)
        head.addWidget(self.select_btn)
        chats.addLayout(head)
        self.select_mode = False
        self.selected_ids: set[str] = set()
        self.checked_by_indicator: QTreeWidgetItem | None = None
        self.chat_tree = QTreeWidget(objectName="chatTree")
        self.chat_tree.setHeaderHidden(True)
        self.chat_tree.setColumnCount(2)
        self.chat_tree.header().setStretchLastSection(False)
        self.chat_tree.header().setSectionResizeMode(0, self.chat_tree.header().ResizeMode.Stretch)
        self.chat_tree.header().setSectionResizeMode(1, self.chat_tree.header().ResizeMode.ResizeToContents)
        self.chat_tree.setIndentation(0)
        self.chat_tree.setRootIsDecorated(False)
        self.chat_tree.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.chat_tree.setTextElideMode(Qt.ElideRight)
        self.chat_tree.setExpandsOnDoubleClick(False)
        self.chat_tree.itemClicked.connect(self._tree_clicked)
        self.chat_tree.setContextMenuPolicy(Qt.CustomContextMenu)
        self.chat_tree.customContextMenuRequested.connect(self._chat_menu)
        self.collapsed_folders: set[str] = set()
        self.current_folder = "Genel"
        chats.addWidget(self.chat_tree, 1)
        self.chat_tree.itemChanged.connect(self._chat_checked)
        # seçim modunda altta: "N seçili · sil · taşı · bitti"
        self.select_bar = QFrame(objectName="selectBar")
        bar = QHBoxLayout(self.select_bar)
        bar.setContentsMargins(4, 6, 0, 0)
        bar.setSpacing(4)
        self.select_count = QLabel("0 Seçili", objectName="keyHint")
        bar.addWidget(self.select_count, 1)
        for text, tip, fn in [("Sil", "seçilen sohbetleri sil", self._delete_selected),
                              ("Taşı", "seçilenleri klasöre taşı", self._move_selected_menu),
                              ("Bitti", "seçim modundan çık", lambda: self.select_btn.setChecked(False))]:
            b = QPushButton(text, objectName="smallButton", toolTip=tip)
            b.setCursor(Qt.PointingHandCursor)
            b.clicked.connect(fn)
            bar.addWidget(b)
        self.select_bar.hide()
        chats.addWidget(self.select_bar)
        self.side_stack.addWidget(chats_page)

        self.work_panel = WorkPanel()
        self.work_panel.new_task.connect(self._new_task_dialog)
        self.work_panel.task_chosen.connect(self._show_task)
        self.work_panel.task_action.connect(self._task_action)
        self.agent_panel = AgentPanel(self.profiles, self._provider_choices, self._models_for,
                                      self._agent_model, self._expert_models)
        self.agent_panel.agent_chosen.connect(self._start_agent_chat)
        self.agent_panel.changed.connect(self._update_header)
        self.api_panel = ApiPanel(self.connections, settings=self.settings)
        self.api_panel.changed.connect(self._connections_changed)
        self.library_panel = LibraryPanel()
        for page in (self.work_panel, self.agent_panel, self.api_panel, self.library_panel):
            wrap = QWidget()
            wl = QVBoxLayout(wrap)
            wl.setContentsMargins(10, 14, 10, 6)
            wl.addWidget(page)
            self.side_stack.addWidget(wrap)
        self.side_tabs.button(0).setChecked(True)
        side.addWidget(QFrame(objectName="rule"))
        foot = QVBoxLayout()
        foot.setContentsMargins(10, 8, 10, 10)
        settings_btn = RowButton("Ayarlar", "Ctrl+,", "", "sideRow")
        settings_btn.clicked.connect(self._open_settings)
        foot.addWidget(settings_btn)
        side.addLayout(foot)
        self.splitter.addWidget(self.sidebar)

        # orta
        center = QWidget(objectName="center")
        col = QVBoxLayout(center)
        col.setContentsMargins(0, 0, 0, 0)
        col.setSpacing(0)

        header = QWidget(objectName="header")
        header.setFixedHeight(52)
        hl = QHBoxLayout(header)
        hl.setContentsMargins(28, 0, 16, 0)
        hl.setSpacing(12)
        self.title = QLabel("Yeni sohbet", objectName="title")
        self.agent_chip = QLabel(objectName="agentChip")
        self.agent_chip.hide()
        self.provider_chip = QLabel(objectName="chip")
        self.provider_chip.hide()
        self.toggle_right = QPushButton(objectName="toggleButton")
        self.toggle_right.setCheckable(True)
        self.toggle_right.setCursor(Qt.PointingHandCursor)
        tr = QHBoxLayout(self.toggle_right)
        tr.setContentsMargins(10, 0, 10, 0)
        tr.setSpacing(8)
        self.toggle_icon = QLabel()
        self.toggle_icon.setPixmap(pixmap("panel-right", C["text2"], 14))
        toggle_text = QLabel("panel")
        toggle_text.setStyleSheet("background: transparent; font-family: 'IBM Plex Mono'; font-size: 12px;")
        toggle_key = QLabel("Ctrl+J", objectName="keyHint")
        for w in (self.toggle_icon, toggle_text, toggle_key):
            w.setAttribute(Qt.WA_TransparentForMouseEvents)
            tr.addWidget(w)
        self.toggle_right.setMinimumWidth(150)
        self.toggle_right.toggled.connect(self._right_toggled)
        hl.addWidget(self.title, 1)
        hl.addWidget(self.agent_chip, 0, Qt.AlignVCenter)
        hl.addWidget(self.toggle_right)
        col.addWidget(header)

        # yavaşlık uyarısı
        self.banner = QFrame(objectName="banner")
        bl = QHBoxLayout(self.banner)
        bl.setContentsMargins(14, 8, 8, 8)
        self.banner_text = QLabel()
        self.banner_text.setWordWrap(True)
        copy = QPushButton("komutu kopyala", objectName="smallButton")
        copy.clicked.connect(lambda: QApplication.clipboard().setText(FIX_COMMAND))
        close = QPushButton("✕", objectName="iconButton")
        close.clicked.connect(lambda: (self.banner.hide(), setattr(self, "banner_dismissed", True)))
        bl.addWidget(self.banner_text, 1)
        bl.addWidget(copy)
        bl.addWidget(close)
        self.banner.hide()
        self.banner_dismissed = False
        banner_wrap = QWidget()
        bw = QVBoxLayout(banner_wrap)
        bw.setContentsMargins(28, 10, 28, 0)
        bw.addWidget(self.banner)
        col.addWidget(banner_wrap)

        self.chat = ChatView()
        col.addWidget(self.chat, 1)

        # mesaj kutusu
        composer_wrap = QWidget()
        cw = QHBoxLayout(composer_wrap)
        cw.setContentsMargins(28, 0, 28, 22)
        composer = QFrame(objectName="composer")
        composer.setMaximumWidth(720)
        cl = QVBoxLayout(composer)
        cl.setContentsMargins(16, 14, 8, 8)
        cl.setSpacing(4)
        input_row = QHBoxLayout()
        input_row.setSpacing(10)
        input_row.addWidget(QLabel("›", objectName="prompt"), 0, Qt.AlignTop)
        self.input = InputBox(objectName="inputBox")
        self.input.setPlaceholderText("Asistana bir şey sor ya da bir görev ver")
        self.input.setFixedHeight(52)
        self.queued_send = False  # iş sürerken Enter: mesaj iş bitince gönderilir
        self.input.submitted.connect(self._submit)
        input_row.addWidget(self.input, 1)
        cl.addLayout(input_row)
        self.attachments: list[str] = []
        self.attach_row = QHBoxLayout()
        self.attach_row.setContentsMargins(20, 2, 0, 2)
        self.attach_row.setSpacing(6)
        self.attach_row.addStretch()
        cl.addLayout(self.attach_row)
        self.input.files_dropped.connect(self._add_attachments)
        tools_row = QHBoxLayout()
        tools_row.setSpacing(4)
        # sağlayıcı ve model kutuları mantığı taşır; görünen yüz tek bir düğme
        self.provider_box = QComboBox()
        self._fill_providers()
        self.provider_box.currentIndexChanged.connect(self._provider_changed)
        self.model_box = QComboBox()
        self.model_box.currentTextChanged.connect(self._model_changed)
        self.provider_box.hide()
        self.model_box.hide()
        self.model_pill = QToolButton(objectName="monoButton", toolTip="Model seç")
        self.model_pill.setPopupMode(QToolButton.InstantPopup)
        self.model_pill.setCursor(Qt.PointingHandCursor)
        self.model_menu = QMenu(self.model_pill)
        self.model_menu.aboutToShow.connect(self._build_model_menu)
        self.model_pill.setMenu(self.model_menu)
        self.workspace_btn = QToolButton(objectName="monoButton")
        self.workspace_btn.setToolTip("Asistanın dosya işlemleri yaptığı çalışma klasörü")
        self.workspace_btn.setCursor(Qt.PointingHandCursor)
        self.workspace_btn.setPopupMode(QToolButton.InstantPopup)
        ws_menu = QMenu(self.workspace_btn)
        ws_menu.addAction("klasörü değiştir…", self._pick_workspace)
        ws_menu.addAction("klasörü aç", lambda: open_folder(self._work_dir()))
        self.workspace_btn.setMenu(ws_menu)
        self.attach_btn = QToolButton(objectName="attachButton", toolTip="Dosya ekle (ya da dosyayı buraya sürükle)")
        self.attach_btn.setText("+ dosya")
        self.attach_btn.setCursor(Qt.PointingHandCursor)
        self.attach_btn.clicked.connect(self._attach_files)
        sep0 = QFrame(objectName="vsep")
        sep = QFrame(objectName="vsep")
        self.enter_hint = QLabel("Shift+Enter yeni satır", objectName="keyHint")
        # dikte: konuş → yazıya çevrilip kutuya eklenir (window_bar._toggle_dictation)
        self.mic_btn = QToolButton(objectName="iconButton", toolTip="Konuşarak yaz (Ctrl+Shift+Space) · Esc: iptal")
        self.mic_btn.setIcon(icon("mic", C["muted"], 16))
        self.mic_btn.setCursor(Qt.PointingHandCursor)
        self.mic_btn.clicked.connect(self._toggle_dictation)
        self.enter_hint.setContentsMargins(0, 0, 10, 0)
        self.send_btn = QPushButton(objectName="sendButton")
        self.send_btn.setIcon(icon("arrow-up", C["on_accent"], 15))
        self.send_btn.setFixedSize(34, 28)
        self.send_btn.setCursor(Qt.PointingHandCursor)
        self.send_btn.setToolTip("Gönder (Enter)")
        self.send_btn.clicked.connect(self._send_or_stop)
        self.stop_btn = QPushButton(objectName="stopButton")
        sl = QHBoxLayout(self.stop_btn)
        sl.setContentsMargins(10, 0, 10, 0)
        sl.setSpacing(8)
        for w in (QLabel("■"), QLabel("durdur"), QLabel("Esc", objectName="keyHint")):
            w.setAttribute(Qt.WA_TransparentForMouseEvents)
            if not w.objectName():
                w.setStyleSheet(f"color: {C['accent']}; background: transparent; font-family: 'IBM Plex Mono'; font-size: 12px;")
            sl.addWidget(w)
        self.stop_btn.setMinimumWidth(118)
        self.stop_btn.setCursor(Qt.PointingHandCursor)
        self.stop_btn.clicked.connect(self._send_or_stop)
        self.stop_btn.hide()
        tools_row.addWidget(self.attach_btn)
        tools_row.addWidget(sep0)
        tools_row.addWidget(self.model_pill)
        tools_row.addWidget(sep)
        tools_row.addWidget(self.workspace_btn)
        tools_row.addStretch()
        tools_row.addWidget(self.enter_hint)
        tools_row.addWidget(self.mic_btn)
        tools_row.addWidget(self.send_btn)
        tools_row.addWidget(self.stop_btn)
        cl.addLayout(tools_row)
        cw.addStretch()
        cw.addWidget(composer, 100)
        cw.addStretch()
        col.addWidget(composer_wrap)
        self.center_stack = QStackedWidget()
        self.center_stack.addWidget(center)
        self.work_room = WorkRoom(self._member_label)
        self.work_room.send_note.connect(self._task_note)
        self.work_room.action.connect(lambda act: self.work_room.task and self._task_action(self.work_room.task.id, act))
        self.center_stack.addWidget(self.work_room)
        self.splitter.addWidget(self.center_stack)

        # sağ panel
        self.right = RightPanel(self.settings)
        self.right.setMinimumWidth(372)
        self.right.setMaximumWidth(760)  # canlı görüntü büyütülebilsin
        self.right.models.model_chosen.connect(self._choose_ollama_model)
        self.right.media.new_media.connect(self._new_media)
        self.right.activity.file_open.connect(self._preview_file)
        self.right.closed.connect(lambda: self.toggle_right.setChecked(False))
        self.right.hide()
        self.chat.file_opened.connect(self._preview_file)
        self.chat.retry_requested.connect(self._retry_message)
        self.chat.can_regenerate = True
        self.chat.regenerate_requested.connect(self._regenerate)
        self.chat.apply_requested.connect(self._apply_suggestions)
        self.work_room.feed.retry_requested.connect(self._task_note)
        self.chat.title_fn = lambda: self.conv.title if self.conv else ""
        self.work_room.feed.file_opened.connect(self._preview_file)
        self.splitter.addWidget(self.right)
        self.splitter.setSizes([248, 820, 372])
        self.splitter.setStretchFactor(1, 1)
        self.splitter.setCollapsible(1, False)
        self.toggle_right.setChecked(True)  # sağ panel varsayılan olarak açık

        # durum çubuğu: [HAZIR] ● ollama bağlı | bağlam … ····· CPU | GPU | VRAM | RAM
        bar = self.statusBar()
        bar.setSizeGripEnabled(False)
        self.mode_label = QLabel("HAZIR", objectName="statusMode")
        self.conn_label = QLabel(objectName="statusSeg")
        self.conn_label.setTextFormat(Qt.RichText)
        self.context_label = QLabel(objectName="statusSeg")
        self.ctx_label = QLabel(objectName="statusSeg")  # bağlam ölçümü sürerken görünür
        self.ctx_label.hide()
        self.run_label = QLabel(objectName="statusSeg")
        self.run_label.hide()
        self.notice_label = QLabel()
        self.notice_label.setStyleSheet(f"color: {C['text']};")
        self.power_label = QLabel(objectName="statusSeg")  # pildeyken görünür
        self.power_label.hide()
        for w in (self.mode_label, self.conn_label, self.context_label, self.power_label, self.ctx_label,
                  self.run_label):
            bar.addWidget(w)
        for w in (self.ctx_label, self.run_label, self.notice_label):  # dar pencerede bunlar kısalsın, taşmasın
            w.setMinimumWidth(1)
        bar.addWidget(self.notice_label, 1)
        self.cloud_btn = QPushButton(objectName="smallButton", toolTip="Bulut asistanın bilgisayarına bıraktığı işler")
        self.cloud_btn.clicked.connect(self.open_cloud_jobs)
        self.cloud_btn.hide()
        bar.addPermanentWidget(self.cloud_btn)
        self.cloud_jobs: list[dict] = []
        self.cloud_job: dict | None = None  # şu an yapılan bulut işi (bitince sonucu gönderilir)
        self.sysmon = SystemMonitorLabel()
        # takılan MCP sunucuları arka planda başlar; araçları hazır olunca asistana kendiliğinden verilir
        threading.Thread(target=mcp.start_all, args=(self.settings.workspace,), daemon=True).start()
        try:
            factory.load_all()  # araç fabrikasının onaylanmış araçları
        except Exception:
            pass
        bar.addPermanentWidget(self.sysmon)
        self.suggest_timer = QTimer(self, singleShot=True)  # öneriler: 1 dk boşta kalınca
        self.suggest_timer.setInterval(60_000)
        self.suggest_timer.timeout.connect(self._refresh_suggestions)
        self.notice_timer = QTimer(self, singleShot=True)
        self.notice_timer.timeout.connect(lambda: self.notice_label.setText(""))
        self._update_workspace_label()
        self._update_context_label()
        self.tick = QTimer(self)
        self.tick.timeout.connect(self._tick)
        self.tick.start(500)
        self.status_poll = QTimer(self)
        self.status_poll.timeout.connect(self._refresh_models_status)
        self.status_poll.start(20000)
        if self.settings.extra.get("power_override"):  # önceki oturumun elle seçimi: açılışta yeniden otomatik
            self.settings.power_mode = "otomatik"
            self.settings.extra = {**self.settings.extra, "power_override": False}
            self.settings.save()
        self.saving = power.saving(self.settings)  # fişe takılma/çıkarılma burada yakalanır
        self._on_battery = power.state().on_battery
        self.power_timer = QTimer(self)
        self.power_timer.timeout.connect(self._check_power)
        self.power_timer.start(15000)
        self._update_power_label()

    def _build_menu(self):
        bar = self.menuBar()
        mark = self.app_mark = QLabel(objectName="appMark")  # referans tutulmazsa Python siler
        mark.setTextFormat(Qt.RichText)
        mark.setText(f'<span style="background:{C["accent"]}; color:{C["accent"]};">▌</span>&nbsp;&nbsp;YENİ NESİL CAFER')
        bar.setCornerWidget(mark, Qt.TopLeftCorner)
        # hafif mod anahtarı (küçük model, 8K bağlam, düşünmesiz) — power.py; güvenlik ve sansürsüz ile aynı sırada
        self.light_btn = QToolButton(objectName="modelTab", checkable=True)
        self.light_btn.setCursor(Qt.PointingHandCursor)
        self.light_btn.setChecked(power.saving(self.settings))
        self.light_btn.toggled.connect(self._toggle_light)
        for i in range(5):
            QShortcut(QKeySequence(f"Ctrl+{i + 1}"), self, activated=lambda i=i: self.side_tabs.button(i).click())
        QShortcut(QKeySequence("Ctrl+K"), self, activated=self._focus_search)
        QShortcut(QKeySequence("Esc"), self, activated=self._escape)
        QShortcut(QKeySequence("Ctrl+Shift+Space"), self, activated=self._toggle_dictation)
        m = bar.addMenu("Sohbet")
        for text, key, fn in [
            ("Yeni sohbet", "Ctrl+N", lambda: self.new_conversation()),
            ("Sohbeti sil", None, self._delete_current),
            (None, None, None),
            ("Ayarlar", "Ctrl+,", self._open_settings),
            ("Çıkış", "Ctrl+Q", self.close),
        ]:
            if text is None:
                m.addSeparator()
                continue
            a = QAction(text, self)
            if key:
                a.setShortcut(QKeySequence(key))
            a.triggered.connect(fn)
            m.addAction(a)
        # modeller: bulut · kod · yerel — üst çubuğun ortasında baloncuk düğmeler; her birinden varsayılan seçilir
        self.model_tabs = QWidget(bar)
        row = QHBoxLayout(self.model_tabs)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(8)
        self.kind_tabs: dict[str, QToolButton] = {}
        for kind, title in [("online", "Online"), ("offline", "Offline")]:
            btn = QToolButton(objectName="modelTab", text=f"{title}  ⌄")
            self.kind_tabs[kind] = btn
            btn.setCursor(Qt.PointingHandCursor)
            btn.setPopupMode(QToolButton.InstantPopup)
            menu = QMenu(btn)
            menu.aboutToShow.connect(lambda m=menu, k=kind: self._fill_model_menu(m, k))
            btn.setMenu(menu)
            row.addWidget(btn)
        # açılıp kapanan anahtarlar: güvenlik ajanı (onayları o verir) · sansürsüz mod (filtresiz model)
        self.guard_btn = QToolButton(objectName="modelTab", checkable=True)
        self.guard_btn.setCursor(Qt.PointingHandCursor)
        self.guard_btn.setChecked(self.settings.approval_mode == "guvenlik")
        self.guard_btn.toggled.connect(self._toggle_guard)
        row.addWidget(self.guard_btn)
        self.free_btn = QToolButton(objectName="modelTab", checkable=True)
        self.free_btn.setCursor(Qt.PointingHandCursor)
        from .. import model_updates

        # açılışta varsayılan asistan yerel modelle başlar: bulut / Claude Code / sansürsüz seçimi o oturumda kalır;
        # kullanıcının seçtiği normal bir yerel model korunur
        s = self.settings
        chosen = s.defaults.get("offline", "")
        if s.extra.get("guvenlik_sansursuz"):  # güvenliği sansürsüz mod kapatmıştı: normal modda geri gelsin
            s.approval_mode = "guvenlik"
            s.extra = {**s.extra, "guvenlik_sansursuz": False}
        if s.extra.get("uncensored") or model_updates.is_uncensored(chosen.split("|", 1)[-1]):
            s.extra = {**s.extra, "uncensored": False}
            s.defaults.pop("offline", None)
            if s.active_kind == "offline":
                s.active_kind = ""
        if s.active_kind not in ("", "offline"):
            s.active_kind = ""
        s.model_policy, s.auto_model = "yerel", True
        if not s.extra.get("guvenlik_varsayilan"):  # bir kereliğine: güvenlik ajanı artık varsayılan (kapatılırsa kapalı kalır)
            s.approval_mode = "guvenlik"
            s.extra = {**s.extra, "guvenlik_varsayilan": True}
        s.save()
        self.free_btn.setChecked(bool(self.settings.extra.get("uncensored")))
        self.free_btn.toggled.connect(self._toggle_uncensored)
        row.addWidget(self.free_btn)
        row.addWidget(self.light_btn)
        self._update_guard_btn()
        self._update_free_btn()
        self._update_light_btn()
        bar.installEventFilter(self)
        self._center_model_tabs()
        v = bar.addMenu("Görünüm")
        side = QAction("Kenar çubuğu", self, shortcut=QKeySequence("Ctrl+B"))
        side.triggered.connect(lambda: self.sidebar.setVisible(not self.sidebar.isVisible()))
        right = QAction("Sağ panel", self, shortcut=QKeySequence("Ctrl+J"))
        right.triggered.connect(lambda: self.toggle_right.setChecked(not self.toggle_right.isChecked()))
        v.addAction(side)
        v.addAction(right)
        v.addSeparator()
        r = self.right
        for name, tab in (("Adımlar", r.activity), ("Kayıt", r.log), ("Klasörler", r.files),
                          ("Canlı önizleme", r.media), ("Modeller", r.models),
                          ("Önizleme", r.preview)):
            a = QAction(name, self)
            a.triggered.connect(lambda _=False, tab=tab: self._show_tab(tab))
            v.addAction(a)
        h = bar.addMenu("Yardım")
        advisor = QAction("Model önerileri…", self)
        advisor.triggered.connect(self.open_advisor)
        h.addAction(advisor)
        setup = QAction("Kurulum sihirbazı…", self)
        setup.triggered.connect(self.run_setup)
        h.addAction(setup)
        self.image_action = QAction("Resim üretimi…", self)
        self.image_action.triggered.connect(self._image_setup)
        h.addAction(self.image_action)
        factory_action = QAction("Araç fabrikası…", self)
        factory_action.triggered.connect(self.open_factory)
        h.addAction(factory_action)
        cats_action = QAction("Ajan kategorileri…", self)
        cats_action.triggered.connect(self.open_categories)
        h.addAction(cats_action)
        cards_action = QAction("Model kartları…", self)
        cards_action.triggered.connect(self.open_cards)
        h.addAction(cards_action)
        learn = QAction("Hafıza ve öğrenme…", self)
        learn.triggered.connect(self.open_learning)
        h.addAction(learn)
        self.update_action = QAction("Güncellemeleri denetle…", self)
        self.update_action.triggered.connect(lambda: self._check_updates(quiet=False))
        h.addAction(self.update_action)
        report = QAction("Sorun bildir…", self)  # geliştiriciye (Claude Code) verilecek rapor
        report.triggered.connect(self._report_dialog)
        h.addAction(report)
        about = QAction("Hakkında", self)
        about.triggered.connect(lambda: QMessageBox.about(
            self, "YENİ NESİL CAFER",
            f"YENİ NESİL CAFER · sürüm {__version__}\n\n"
            "Yerel modellerle (Ollama) ve bulut modelleriyle çalışan kişisel yapay zekâ asistanı ve ekibi.\n\n"
            f"Sohbetler: {DATA_DIR}\nAyarlar: {CONFIG_DIR}"))
        h.addAction(about)

    # ---- yardımcılar
    @property
    def provider(self) -> str:
        return self.provider_box.currentData()

    def _preview_file(self, path: str):
        """Resim, video ve 3D model sağ paneldeki canlı görüntüde; diğer dosyalar önizleme penceresinde açılır."""
        from .media_panel import media_kind

        self.toggle_right.setChecked(True)
        self.right.show()
        if media_kind(path):
            self.right.media.show_file(path)
            return
        self.right.show_part(self.right.preview)
        self.right.preview.show_file(path)

    def _build_model_menu(self):
        """Alttaki model menüsü: kullanılabilecek bütün modeller — Offline (yerel), Sansürsüz, Online (bulut).
        Seçim üstteki menülerle aynı ayarı değiştirir; üstte o modelin kategorisi yanar."""
        from .. import model_updates

        menu = self.model_menu
        menu.clear()
        s = self.settings
        auto = menu.addAction("otomatik — işe göre program seçer")
        auto.setCheckable(True)
        auto.setChecked(s.auto_model and not s.active_kind and not s.extra.get("uncensored"))
        auto.triggered.connect(lambda: self._set_default_model("offline", ""))
        live = model_updates.load()
        candidates = roster.candidates(s)
        caps = {c.key: c.caps for c in candidates}

        def add(target: QMenu, text: str, kind: str, value: str):
            # üstteki menülerdeki gibi etiketler: #araç #görme #düşünme #kod…
            prov, _, name = value.partition("|")
            known = caps.get((prov, name))
            tags = model_updates.local_tags(name, 0, live if prov == "ollama" else None, known) \
                if known is not None or prov == "ollama" else []
            if known is not None and "tools" not in known:
                tags.append("sadece sohbet")
            a = target.addAction(f"{text}    {model_updates.hashtags(tags)}" if tags else text)
            a.setCheckable(True)
            a.setChecked(self._in_use(kind, value))
            a.triggered.connect(lambda _=False: self._set_default_model(kind, value))

        local = sorted((c for c in candidates if c.local), key=lambda c: -c.score)
        normal = [c for c in local if not model_updates.is_uncensored(c.model)]
        free = [c for c in local if model_updates.is_uncensored(c.model)]
        self._menu_title(menu, "OFFLINE · YEREL")  # hazır büyük harf: Türkçe dönüşüm İ yapmasın
        for c in normal:
            add(menu, c.model, "offline", f"ollama|{c.model}")
        if not local:
            menu.addAction("yerel model yok — Ollama çalışıyor mu?").setEnabled(False)
        if free:
            self._menu_title(menu, "sansürsüz — seçince 🔓 mod açılır")
            for c in free:
                add(menu, c.model, "offline", f"ollama|{c.model}")

        self._menu_title(menu, "ONLINE · BULUT")
        linked_any = False
        if specialists.claude_code_available():
            linked_any = True
            for m, note in specialists.CLAUDE_CODE_MODELS:
                label = "Claude Code" if m == specialists.CLAUDE_CODE[1] else f"Claude Code · {m}"
                add(menu, f"{label}    {note}", "code", f"{specialists.CLAUDE_CODE[0]}|{m}")
        known_hosts = []
        for prov in catalog.PROVIDERS:
            known_hosts.append(prov.host)
            if self._provider_conn(prov)[0]:
                linked_any = True
                sub = menu.addMenu(f"{prov.name}  ·  bağlı")
                self._provider_submenu(sub, prov, "online", "", inline=True)
        for conn in self.connections:  # katalogda olmayan, elle eklenmiş sağlayıcılar
            if conn.kind == "llm" and conn.enabled and not any(h in conn.base_url for h in known_hosts):
                linked_any = True
                sub = menu.addMenu(f"{conn.name}  ·  bağlı")
                for m in _models_for_menu(conn.models, False)[:25]:
                    add(sub, m, "online", f"api:{conn.id}|{m}")
        if not linked_any:
            menu.addAction("bulut bağlantısı yok — aşağıdan bir firmaya bağlan").setEnabled(False)
        connect = menu.addMenu("Bağlan — ücretsiz ve ücretli firmalar")
        for prov in catalog.PROVIDERS:
            if not self._provider_conn(prov)[0]:
                self._provider_submenu(connect, prov, "online", "")
        connect.addSeparator()
        connect.addAction("Başka sağlayıcı ekle…", lambda: self._add_connection(""))

    def _company(self, provider: str) -> str:
        if provider == "ollama":
            return "yerel"
        if provider == "claude":
            return "claude"
        if provider == specialists.CLAUDE_CODE[0]:
            return "claude code"
        conn = self._connection(provider)
        return conn.name.lower() if conn else provider

    def open_advisor(self):
        """Model önerileri: sisteme göre yerel modeller, bulutta ücretsiz kotalar ve ücretli en iyiler."""
        from .model_advisor import ModelAdvisor

        ModelAdvisor(self.settings, lambda pid: self._connect_provider(catalog.BY_ID[pid], "online", ""), self).exec()
        self._reload_models()
        self.right.models.refresh()

    def _daily_model_update(self):
        """Model listesini arka planda günceller (internet varsa; 20 saatten eskiyse)."""
        from .. import model_updates

        threading.Thread(target=model_updates.refresh, daemon=True).start()

    def closeEvent(self, event):
        try:
            from .. import browser

            browser.shutdown()  # tarayıcı penceresi programla birlikte kapansın (oturumlar profilde kalır)
        except Exception:
            pass
        self.sysmon.shutdown()
        if self.dictation is not None:
            self.dictation.shutdown()
        self.right.media.shutdown()
        mcp.stop_all()
        if self.task_worker:
            self.task_worker.cancel()
            self.task_worker.wait(3000)
        if self.worker:
            self.worker.cancel()
            self.worker.wait(3000)
        super().closeEvent(event)
