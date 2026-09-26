"""Yanıt paylaşma — telefondaki paylaş ekranı gibi: kurulu uygulamalar doğrudan açılır
(Telegram, WhatsApp); e-posta Gmail'de, uygulaması olmayanlar web'de açılır.
"""

import subprocess
from datetime import datetime
from pathlib import Path
from urllib.parse import quote

from PySide6.QtCore import QUrl
from PySide6.QtGui import QDesktopServices, QIcon
from PySide6.QtWidgets import QApplication, QFileDialog, QMenu

# ad -> (uygulama bağlantısı, web yedeği, metin sınırı, tema simgeleri)
APPS = {
    "Telegram": ("tg://msg?text={text}", "https://t.me/share/url?url=%20&text={text}", 3500,
                 ["org.telegram.desktop", "telegram"]),
    "WhatsApp": ("whatsapp://send?text={text}", "https://web.whatsapp.com/send?text={text}", 3500,
                 ["whatsapp", "com.github.eneshecan.WhatsAppForLinux", "com.rtosta.zapzap", "zapzap"]),
}
WEB = {
    "X (Twitter)": ("https://x.com/intent/post?text={text}", 280),
    "LinkedIn": ("https://www.linkedin.com/feed/?shareActive=true&text={text}", 2900),
    "Reddit": ("https://www.reddit.com/submit?type=TEXT&title={title}&text={text}", 6000),
    "Bluesky": ("https://bsky.app/intent/compose?text={text}", 300),
    "Mastodon": ("https://mastodon.social/share?text={text}", 500),
}


def _clip(text: str, limit: int) -> str:
    text = text.strip()
    return text if len(text) <= limit else text[: limit - 1].rstrip() + "…"


def _plain(markdown: str) -> str:
    """Mesajlaşma uygulamaları Markdown göstermez; en belirgin işaretleri temizle."""
    lines = []
    for line in markdown.splitlines():
        s = line.lstrip("#").strip() if line.lstrip().startswith("#") else line
        lines.append(s.replace("**", "").replace("__", "").replace("`", ""))
    return "\n".join(lines).strip()


def _handler(scheme: str) -> str:
    """Bu bağlantı türünü açan uygulama (.desktop adı) ya da boş."""
    try:
        out = subprocess.run(["xdg-mime", "query", "default", f"x-scheme-handler/{scheme}"],
                             capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=3).stdout.strip()
    except (OSError, subprocess.SubprocessError):
        return ""
    # tarayıcılar her şeyi "açar"; onları uygulama saymayalım
    return "" if any(b in out.lower() for b in ("firefox", "chrom", "brave", "vivaldi", "opera", "zen")) else out


def _icon(names: list[str], fallback: str = "") -> QIcon:
    for n in names + ([fallback] if fallback else []):
        ic = QIcon.fromTheme(n)
        if not ic.isNull():
            return ic
    return QIcon()


def _open(url: str):
    QDesktopServices.openUrl(QUrl(url))


def fill_share_menu(menu: QMenu, get_text, get_title):
    """Menüyü her açılışta yeniden kurar: kurulu uygulamalar o an denetlenir."""
    menu.clear()
    parent = menu.parentWidget()
    text = lambda: _plain(get_text())  # noqa: E731

    menu.addSection("uygulamalar")
    for name, (app_url, web_url, limit, icons) in APPS.items():
        scheme = app_url.split(":", 1)[0]
        has_app = bool(_handler(scheme))
        url = app_url if has_app else web_url
        label = name if has_app else f"{name}  (web)"
        a = menu.addAction(_icon(icons, "internet-web-browser"), label,
                           lambda u=url, lim=limit: _open(u.format(text=quote(_clip(text(), lim)))))
        a.setToolTip("Uygulamada açılır, kime göndereceğini seçersin" if has_app
                     else "Bu bilgisayarda uygulaması yok; tarayıcıda açılır")
    menu.addAction(_icon(["mail-message-new", "internet-mail", "gmail"]), "Gmail",
                   lambda: _open("https://mail.google.com/mail/?view=cm&fs=1"
                                 f"&su={quote(get_title() or 'YENİ NESİL CAFER yanıtı')}"
                                 f"&body={quote(_clip(text(), 6000))}"))

    menu.addSection("web")
    for name, (pattern, limit) in WEB.items():
        menu.addAction(name, lambda p=pattern, lim=limit: _open(p.format(
            text=quote(_clip(text(), lim)), title=quote(_clip(get_title() or text().splitlines()[0], 250)))))

    menu.addSection("diğer")
    menu.addAction(_icon(["edit-copy"]), "metni kopyala", lambda: QApplication.clipboard().setText(get_text()))
    menu.addAction("düz metin olarak kopyala", lambda: QApplication.clipboard().setText(text()))
    menu.addAction(_icon(["document-save"]), "dosyaya kaydet (.md)…", lambda: _save(parent, get_text(), get_title()))


def share_menu(parent, get_text, title_fn) -> QMenu:
    menu = QMenu(parent)
    menu.aboutToShow.connect(lambda: fill_share_menu(menu, get_text, title_fn))
    return menu


def _save(parent, text: str, title: str):
    name = (title or "yanit")[:40].strip().replace("/", "-") or "yanit"
    default = str(Path.home() / f"{name} {datetime.now():%Y-%m-%d %H%M}.md")
    path, _ = QFileDialog.getSaveFileName(parent, "Yanıtı kaydet", default, "Markdown (*.md);;Metin (*.txt)")
    if path:
        Path(path).write_text(text, encoding="utf-8")
