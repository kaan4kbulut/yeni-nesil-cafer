"""Renkler ve Qt stil sayfası: sıcak siyah, tek vurgu, ince çizgiler (retro terminal görünümü).

Kurallar: köşe 2–3 px, gölge ve degrade yok; yüzeyler 1 px çizgiyle ayrılır; vurgu yalnızca imleç,
seçim ve ana eylemde; arayüz metni IBM Plex Mono, içerik IBM Plex Sans.
"""

from pathlib import Path

from PySide6.QtGui import QColor, QFont, QFontDatabase, QPalette
from PySide6.QtWidgets import QApplication

ACCENTS = {
    "Kehribar": "#F2A93B",
    "Yeşil": "#8FCB7A",
    "Camgöbeği": "#7CC4D6",
    "Mercan": "#E07A5F",
}

C = {
    "top": "#0F0D0B",  # başlık ve durum çubuğu
    "bg": "#14120F",  # sohbet alanı
    "sidebar": "#181511",  # kenar panelleri
    "panel": "#181511",
    "code_bg": "#181511",
    "field": "#1B1814",  # giriş kutusu, mesaj
    "surface": "#1B1814",
    "select": "#221E19",  # seçili satır, satır içi kod
    "surface2": "#221E19",
    "hover": "#1E1B16",
    "selection": "#6B4A17",  # seçili metin (vurgunun koyu tonu; zeminde açıkça görünür)
    "border": "#2E2923",  # ayırıcı
    "border_soft": "#2E2923",
    "frame": "#3D362E",  # çerçeve
    "text": "#E8E1D5",
    "text2": "#A89F91",
    "code_text": "#D8CFC1",
    "muted": "#8A8174",
    "accent": ACCENTS["Kehribar"],
    "accent_hover": "#F5BA5E",
    "on_accent": "#14120F",
    "success": "#8FB573",
    "warn": "#E5A54B",
    "error": "#D9695F",
}

SANS = "IBM Plex Sans"
MONO = "IBM Plex Mono"
FONTS_DIR = Path(__file__).parent / "fonts"


def set_accent(color: str) -> None:
    """Vurgu rengini ayarlar; pencereler oluşturulmadan önce çağrılmalı."""
    c = QColor(color)
    C["accent"] = c.name()
    C["accent_hover"] = c.lighter(115).name()
    sel = QColor(c)
    sel.setHsv(c.hsvHue(), min(255, int(c.hsvSaturation() * 0.8)), 110)
    C["selection"] = sel.name()


def load_fonts() -> None:
    for f in FONTS_DIR.glob("*.ttf"):
        QFontDatabase.addApplicationFont(str(f))


def mono(size: float = 12.5, weight: int = 400) -> QFont:
    f = QFont(MONO)
    f.setPixelSize(round(size))
    f.setWeight(QFont.Weight(weight))
    return f


def build_style() -> str:
    return f"""
* {{ font-family: "{SANS}"; font-size: 14px; }}
QMainWindow, #center {{ background: {C['bg']}; }}
QMenuBar {{ background: {C['top']}; color: {C['text2']}; border-bottom: 1px solid {C['border']}; padding: 0; min-height: 34px; }}
QMenuBar::item {{ padding: 5px 10px; border-radius: 3px; margin: 4px 1px; font-size: 13px; }}
QMenuBar::item:selected {{ background: {C['select']}; color: {C['text']}; }}
#appMark {{ color: {C['text2']}; font-family: "{MONO}"; font-size: 12px; padding: 0 12px 0 14px; }}
QMenu {{ background: {C['field']}; color: {C['text']}; border: 1px solid {C['frame']}; border-radius: 3px; padding: 4px; }}
QMenu::item {{ padding: 6px 24px 6px 12px; border-radius: 2px; font-family: "{MONO}"; font-size: 12.5px; }}
QMenu::item:selected {{ background: {C['select']}; color: {C['text']}; }}
QMenu::item:disabled {{ color: {C['muted']}; }}
QMenu::item:checked {{ color: {C['accent']}; }}
QMenu::indicator {{ width: 0; }}
QMenu::separator {{ height: 1px; background: {C['border']}; margin: 4px 6px; }}
QMenu::section {{ color: {C['muted']}; font-family: "{MONO}"; font-size: 10.5px; letter-spacing: 1px; padding: 8px 12px 4px; }}
QToolTip {{ background: {C['field']}; color: {C['text']}; border: 1px solid {C['frame']}; border-radius: 2px; padding: 4px 8px; font-family: "{MONO}"; font-size: 12px; }}
QSplitter::handle {{ background: {C['border']}; }}
QScrollBar:vertical {{ background: transparent; width: 8px; margin: 2px; }}
QScrollBar::handle:vertical {{ background: {C['frame']}; border-radius: 2px; min-height: 30px; }}
QScrollBar::handle:vertical:hover {{ background: #54493d; }}
QScrollBar::add-line, QScrollBar::sub-line {{ height: 0; width: 0; }}
QScrollBar::add-page, QScrollBar::sub-page {{ background: transparent; }}
QScrollBar:horizontal {{ background: transparent; height: 8px; margin: 2px; }}
QScrollBar::handle:horizontal {{ background: {C['frame']}; border-radius: 2px; }}

/* kenar çubuğu */
#sidebar {{ background: {C['sidebar']}; border-right: 1px solid {C['border']}; }}
#navRow, #sideRow {{ background: transparent; border: none; border-radius: 3px; color: {C['text2']};
                    font-family: "{MONO}"; font-size: 12.5px; text-align: left; padding: 0 10px; min-height: 32px; }}
#navRow:hover, #sideRow:hover {{ background: {C['hover']}; color: {C['text']}; }}
#navRow:checked {{ background: {C['select']}; color: {C['text']}; }}
#rule {{ background: {C['border']}; max-height: 1px; min-height: 1px; }}
#outlineRow {{ background: transparent; border: 1px solid {C['frame']}; border-radius: 3px; color: {C['text']};
              font-family: "{MONO}"; font-size: 12.5px; text-align: left; padding: 0 10px; min-height: 32px; }}
#outlineRow:hover {{ background: {C['hover']}; }}
#search {{ background: {C['bg']}; border: 1px solid {C['border']}; border-radius: 3px; padding: 0 8px; min-height: 32px;
          color: {C['text']}; font-family: "{MONO}"; font-size: 12.5px; }}
#search:focus {{ border-color: {C['frame']}; }}
#label {{ color: {C['muted']}; font-family: "{MONO}"; font-size: 10.5px; letter-spacing: 1.5px; }}
#chatTree, #chatList, #agentList {{ background: transparent; border: none; color: {C['text2']}; outline: none; font-size: 13.5px; }}
#chatTree::item {{ padding: 0 4px; min-height: 32px; border: none; }}
#chatTree::item:hover, #chatList::item:hover, #agentList::item:hover {{ background: {C['hover']}; color: {C['text']}; }}
#chatTree::item:selected, #chatList::item:selected, #agentList::item:selected {{ background: {C['select']}; color: {C['text']}; }}
#chatTree {{ show-decoration-selected: 1; }}
#chatTree::indicator {{ width: 13px; height: 13px; border: 1px solid {C['frame']}; border-radius: 3px; background: {C['field']}; }}
#chatTree::indicator:checked {{ background: {C['accent']}; border-color: {C['accent']}; }}
#selectBar {{ border-top: 1px solid {C['border']}; }}
#chatTree::branch, #chatTree::branch:selected, #chatTree::branch:hover {{ background: transparent; image: none; border: none; }}
#chatList::item {{ padding: 7px 10px; border-radius: 3px; }}
#agentList::item {{ padding: 8px 10px; border-radius: 3px; margin-bottom: 1px; }}
#agentRow {{ background: {C['field']}; border: 1px solid {C['border']}; border-radius: 3px; }}
#agentRow:hover {{ border-color: {C['frame']}; }}
#agentRow[selected="true"] {{ background: {C['select']}; border-color: {C['accent']}; }}
#agentBadge {{ background: {C['bg']}; border: 1px solid {C['border']}; border-radius: 3px; }}
#agentName {{ color: {C['text']}; font-size: 13.5px; font-weight: 500; background: transparent; }}
#agentDesc {{ color: {C['text2']}; font-size: 12.5px; background: transparent; }}
#agentMeta {{ color: {C['muted']}; font-family: "{MONO}"; font-size: 11px; background: transparent; }}
#agentChip {{ color: {C['accent']}; background: transparent; border: 1px solid {C['frame']}; border-radius: 2px; padding: 2px 8px;
             font-family: "{MONO}"; font-size: 11.5px; }}
#planPane {{ background: {C['panel']}; border-left: 1px solid {C['border']}; }}

/* başlık satırı */
#header {{ background: {C['bg']}; border-bottom: 1px solid {C['border']}; }}
#title {{ color: {C['text']}; font-size: 14.5px; font-weight: 500; }}
#chip {{ color: {C['muted']}; background: transparent; font-family: "{MONO}"; font-size: 11.5px; }}
#toggleButton {{ background: transparent; border: 1px solid {C['border']}; border-radius: 3px; color: {C['text2']};
                font-family: "{MONO}"; font-size: 12px; padding: 0 10px; min-height: 28px; }}
#toggleButton:hover {{ color: {C['text']}; }}
#toggleButton:checked {{ background: {C['select']}; border-color: {C['frame']}; color: {C['text']}; }}
#iconButton {{ background: transparent; border: none; color: {C['muted']}; padding: 5px; border-radius: 3px; font-family: "{MONO}"; }}
#iconButton:hover {{ background: {C['select']}; color: {C['text']}; }}
QToolButton#iconButton::menu-indicator, QToolButton#smallButton::menu-indicator {{ image: none; width: 0; }}
#banner {{ background: #2a2113; border: 1px solid #5a4420; border-radius: 3px; }}
#banner QLabel {{ color: #f0cf94; }}

/* karşılama */
#welcomeTitle {{ color: {C['text']}; font-size: 30px; font-weight: 500; }}
#welcomeText {{ color: {C['text2']}; font-size: 15px; }}
#suggestion {{ background: transparent; border: none; border-top: 1px solid {C['border']}; color: {C['text']};
              font-size: 14.5px; text-align: left; padding: 0 4px; min-height: 44px; }}
#suggestion:hover {{ background: {C['hover']}; }}
#suggestionTag {{ color: {C['muted']}; font-family: "{MONO}"; font-size: 11px; background: transparent; }}

/* sohbet */
#chatArea, #chatContainer {{ background: {C['bg']}; }}
#userBox {{ background: {C['field']}; border: 1px solid {C['border']}; border-radius: 3px; }}
#thumb {{ background: {C['bg']}; border: 1px solid {C['frame']}; border-radius: 2px; padding: 2px; }}
#thumb:hover {{ border-color: {C['accent']}; }}
#assistantBox {{ background: {C['panel']}; border: 1px solid {C['border']}; border-radius: 3px; }}
#bubbleFooter {{ border-top: 1px dashed {C['border']}; }}
QLabel {{ selection-background-color: {C['selection']}; selection-color: #FFFFFF; }}
#userText {{ color: {C['text']}; font-size: 15px; }}
#prompt {{ color: {C['accent']}; font-family: "{MONO}"; font-size: 15px; }}
#stamp {{ color: {C['muted']}; font-family: "{MONO}"; font-size: 11px; }}
#turnHeader {{ color: {C['muted']}; font-family: "{MONO}"; font-size: 11px; letter-spacing: 0.5px; padding-top: 4px; }}
#turnFooter {{ color: {C['muted']}; font-family: "{MONO}"; font-size: 11px; }}
#assistantText {{ color: {C['text']}; font-size: 15px; }}
#thinking {{ color: {C['muted']}; font-style: italic; }}
#codeBlock {{ background: {C['code_bg']}; border: 1px solid {C['border']}; border-radius: 3px; }}
#codeLang {{ color: {C['muted']}; font-family: "{MONO}"; font-size: 11px; }}
#codeText {{ color: {C['code_text']}; font-family: "{MONO}"; font-size: 13px; }}
#smallButton {{ background: transparent; border: 1px solid {C['frame']}; color: {C['text']}; border-radius: 2px; padding: 3px 8px;
               font-family: "{MONO}"; font-size: 11.5px; }}
#smallButton:hover {{ border-color: {C['accent']}; color: {C['accent']}; }}
#workHeader {{ border: 1px solid {C['border']}; border-radius: 3px; background: transparent; color: {C['text2']}; text-align: left;
              padding: 0 12px; min-height: 34px; font-family: "{MONO}"; font-size: 12.5px; }}
#workHeader:hover {{ color: {C['text']}; }}
#workBody {{ border-left: 1px solid {C['border']}; }}
#toolCard {{ background: transparent; border: 1px solid {C['border']}; border-radius: 3px; }}
#toolHeader {{ border: none; color: {C['text2']}; text-align: left; padding: 0 12px; min-height: 34px; background: transparent;
              font-family: "{MONO}"; font-size: 12.5px; }}
#toolHeader:hover {{ color: {C['text']}; }}
#toolDetails {{ background: {C['code_bg']}; color: {C['code_text']}; font-family: "{MONO}"; font-size: 12.5px; padding: 12px 14px;
               border-top: 1px solid {C['border']}; }}
#notice {{ color: {C['muted']}; }}
#fileCard {{ background: transparent; border: 1px solid {C['border']}; border-radius: 3px; }}
#fileCard:hover {{ border-color: {C['frame']}; background: {C['hover']}; }}
#fileTile {{ color: {C['success']}; font-family: "{MONO}"; font-size: 13px; }}
#fileName {{ color: {C['text']}; font-family: "{MONO}"; font-size: 12.5px; }}
#fileMeta {{ color: {C['muted']}; font-family: "{MONO}"; font-size: 11.5px; }}

/* mesaj kutusu */
#composer {{ background: {C['field']}; border: 1px solid {C['frame']}; border-radius: 3px; }}
#inputBox {{ background: transparent; border: none; color: {C['text']}; padding: 0; font-size: 15px; }}
#monoButton {{ background: transparent; border: none; border-radius: 3px; color: {C['text2']}; font-family: "{MONO}"; font-size: 12px;
              padding: 0 8px; min-height: 28px; }}
#monoButton:hover {{ background: {C['select']}; color: {C['text']}; }}
#monoButton::menu-indicator {{ image: none; width: 0; }}
#attachButton {{ background: {C['accent']}; border: none; border-radius: 2px; color: {C['on_accent']};
                font-family: "{MONO}"; font-size: 12px; font-weight: 600; padding: 0 10px; min-height: 28px; }}
#attachButton:hover {{ background: {C['accent_hover']}; }}
#vsep {{ background: {C['frame']}; min-width: 1px; max-width: 1px; min-height: 14px; max-height: 14px; }}
#keyHint {{ color: {C['muted']}; font-family: "{MONO}"; font-size: 11px; background: transparent; }}
#decisionPill {{ background: {C['field']}; border: 1px solid {C['frame']}; border-radius: 19px; }}
#decisionYes {{ background: {C['accent']}; border: none; border-radius: 15px; }}
#decisionYes:hover {{ background: {C['accent_hover']}; }}
#decisionNo {{ background: transparent; border: none; border-radius: 15px; }}
#decisionNo:hover {{ background: {C['select']}; }}
#modelTab {{ background: {C['accent']}; color: {C['on_accent']}; border: none; border-radius: 12px; padding: 3px 14px;
             font-family: "{MONO}"; font-size: 12px; font-weight: 600; min-height: 18px; }}
#modelTab:hover, #modelTab:pressed {{ background: {C['accent_hover']}; }}
QToolButton#modelTab::menu-indicator {{ image: none; width: 0; }}
QToolButton#modelTab[inactive="true"] {{ background: transparent; color: {C['text2']}; border: 1px solid {C['frame']}; }}
QToolButton#modelTab[inactive="true"]:hover {{ color: {C['accent']}; border-color: {C['accent']}; }}
#sendButton {{ background: {C['accent']}; color: {C['on_accent']}; border: none; border-radius: 2px; }}
#sendButton:hover {{ background: {C['accent_hover']}; }}
#stopButton {{ background: transparent; border: 1px solid {C['accent']}; border-radius: 2px; color: {C['accent']};
              font-family: "{MONO}"; font-size: 12px; padding: 0 10px; min-height: 26px; }}
#hint {{ color: {C['muted']}; font-size: 12px; }}
QComboBox {{ background: {C['field']}; border: 1px solid {C['border']}; border-radius: 3px; padding: 4px 10px; color: {C['text']}; }}
QComboBox::drop-down {{ border: none; width: 16px; }}
QComboBox QAbstractItemView {{ background: {C['field']}; color: {C['text']}; border: 1px solid {C['frame']}; selection-background-color: {C['select']}; }}

/* sağ panel */
#rightPanel {{ background: {C['panel']}; border-left: 1px solid {C['border']}; }}
QTabWidget::pane {{ border: none; border-top: 1px solid {C['border']}; }}
QTabBar::tab {{ background: transparent; color: {C['muted']}; padding: 0 6px; min-height: 50px; border: none;
               border-bottom: 2px solid transparent; font-family: "{MONO}"; font-size: 12px; }}
QTabBar::tab:selected {{ color: {C['text']}; border-bottom: 2px solid {C['accent']}; }}
QTabBar::tab:hover {{ color: {C['text']}; }}
#panelTitle {{ color: {C['muted']}; font-family: "{MONO}"; font-size: 10.5px; letter-spacing: 1.5px; }}
#panelMeta {{ color: {C['muted']}; font-family: "{MONO}"; font-size: 11px; }}
#statusBig {{ color: {C['text']}; font-family: "{MONO}"; font-size: 13px; font-weight: 500; }}
#card {{ background: transparent; border: 1px solid {C['border']}; border-radius: 3px; }}
#stepList, #modelList {{ background: transparent; border: none; color: {C['text2']}; outline: none; font-family: "{MONO}"; font-size: 12.5px; }}
#stepList::item {{ padding: 10px 0; border-top: 1px dashed {C['border']}; }}
#stepList::item:selected {{ background: transparent; color: {C['text']}; }}
#modelList::item {{ padding: 8px 6px; border-radius: 3px; }}
#modelList::item:selected {{ background: {C['select']}; }}
#stepNo {{ color: {C['muted']}; font-family: "{MONO}"; font-size: 12.5px; }}
#stepTitle {{ color: {C['text']}; font-family: "{MONO}"; font-size: 12.5px; }}
#stepSub {{ color: {C['muted']}; font-family: "{MONO}"; font-size: 11.5px; }}
#stepTime {{ color: {C['muted']}; font-family: "{MONO}"; font-size: 12px; }}
#logView, #preview {{ background: {C['code_bg']}; color: {C['code_text']}; border: 1px solid {C['border']}; border-radius: 3px;
                     font-family: "{MONO}"; font-size: 12px; }}
#mdPreview {{ background: {C['code_bg']}; color: {C['text']}; border: 1px solid {C['border']}; border-radius: 3px; }}
#docToolbar {{ border-bottom: 1px solid {C['border']}; }}
#docName {{ color: {C['text']}; font-family: "{MONO}"; font-size: 12.5px; }}
#docView {{ background: {C['panel']}; color: {C['text']}; border: none; }}
#docCode {{ background: {C['panel']}; color: {C['code_text']}; border: none; font-family: "{MONO}"; font-size: 13px; }}
#docTable {{ background: {C['panel']}; color: {C['text2']}; border: none; gridline-color: {C['border']}; }}
QTreeView {{ background: transparent; border: none; color: {C['text2']}; outline: none; }}
QTreeView::item {{ padding: 3px; }}
QTreeView::item:selected {{ background: {C['select']}; color: {C['text']}; }}
QHeaderView::section {{ background: {C['panel']}; color: {C['muted']}; border: none; border-bottom: 1px solid {C['border']}; padding: 5px;
                       font-family: "{MONO}"; font-size: 11.5px; }}
QProgressBar {{ background: {C['select']}; border: none; border-radius: 0; max-height: 3px; }}
QProgressBar::chunk {{ background: {C['accent']}; }}

/* durum çubuğu */
QStatusBar {{ background: {C['top']}; border-top: 1px solid {C['border']}; color: {C['text2']}; min-height: 28px; }}
QStatusBar::item {{ border: none; }}
QStatusBar QLabel {{ color: {C['text2']}; font-family: "{MONO}"; font-size: 11.5px; padding: 0 12px; min-height: 27px; }}
#statusMode {{ background: {C['accent']}; color: {C['on_accent']}; font-weight: 600; letter-spacing: 1.2px; }}
#statusSeg {{ border-right: 1px solid {C['border']}; }}
#statusSegR {{ border-left: 1px solid {C['border']}; }}

QDialog {{ background: {C['bg']}; }}
QLineEdit, QSpinBox, QPlainTextEdit {{ background: {C['field']}; border: 1px solid {C['border']}; border-radius: 3px; padding: 6px;
                                       color: {C['text']}; selection-background-color: {C['selection']}; selection-color: #FFFFFF; }}
QLineEdit:focus, QPlainTextEdit:focus, QSpinBox:focus {{ border-color: {C['frame']}; }}
QPushButton {{ background: transparent; color: {C['text']}; border: 1px solid {C['frame']}; border-radius: 3px; padding: 6px 14px;
              font-family: "{MONO}"; font-size: 12.5px; }}
QPushButton:hover {{ background: {C['select']}; }}
QPushButton#primary {{ background: {C['accent']}; border: none; color: {C['on_accent']}; font-weight: 600; }}
QPushButton#primary:hover {{ background: {C['accent_hover']}; }}
QPushButton#danger {{ background: {C['error']}; border: none; color: {C['on_accent']}; }}
QCheckBox {{ color: {C['text']}; }}
QCheckBox::indicator {{ width: 14px; height: 14px; border: 1px solid {C['frame']}; border-radius: 2px; background: {C['field']}; }}
QCheckBox::indicator:checked {{ background: {C['accent']}; border-color: {C['accent']}; }}
"""


def apply_theme(app: QApplication, accent: str | None = None) -> None:
    if accent:
        set_accent(accent)
    load_fonts()
    app.setStyle("Fusion")
    font = QFont(SANS)
    font.setPixelSize(14)
    app.setFont(font)
    p = QPalette()
    for role, color in {
        QPalette.Window: C["bg"], QPalette.WindowText: C["text"], QPalette.Base: C["field"],
        QPalette.AlternateBase: C["select"], QPalette.Text: C["text"], QPalette.Button: C["select"],
        QPalette.ButtonText: C["text"], QPalette.Highlight: C["selection"], QPalette.HighlightedText: "#FFFFFF",
        QPalette.ToolTipBase: C["field"], QPalette.ToolTipText: C["text"], QPalette.Link: C["accent"],
        QPalette.PlaceholderText: C["muted"],
    }.items():
        p.setColor(role, QColor(color))
    app.setPalette(p)
    app.setStyleSheet(build_style())
