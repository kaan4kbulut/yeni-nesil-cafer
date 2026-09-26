"""MainWindow: bulut modellerini hesabınla kullanma (anahtar kopyalamadan).

İki yol (kullanıcının kararı, 2026-09-26): tarayıcıda giriş (OpenRouter, Hugging Face; accounts.py) ve aboneliğinle
resmi program (ChatGPT → Codex, Google → Gemini CLI, Claude → Claude Code; cli_agents.py). Model menüsünde firmanın
alt menüsünün başında "🔑 …" seçenekleri olarak görünür.
"""

from PySide6.QtCore import QTimer, QUrl
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import QMenu, QMessageBox

from .. import accounts, cli_agents
from ..agent import describe_error
from ..connections import LLM_PRESETS, Connection
from .sidebar import login_account, run_in_background

CLI_SIZES = {"cli:codex": "~110 MB indirme, kurulunca ~270 MB", "cli:gemini": "~21 MB indirme; Node.js yoksa +30 MB"}


class AccountsMixin:
    def _account_requested(self, what: str):
        """API'ler sekmesindeki "hesabınla" satırı: resmi programı kur / giriş yap ya da OpenRouter'a giriş."""
        from .. import catalog

        if cli_agents.is_cli(what):
            self._cli_connect(what)
        else:
            self._account_login(catalog.BY_ID[what], "online", "")

    def _account_actions(self, menu: QMenu, prov, kind: str, model: str = "") -> bool:
        """Firmanın hesapla kullanma seçenekleri; bir şey eklendiyse True."""
        added = False
        if prov.login in ("openrouter", "huggingface") and accounts.available(prov.login) \
                and not self._provider_conn(prov)[0]:
            menu.addAction(f"🔑  hesabınla giriş yap — {prov.name} (tarayıcıda, anahtar kopyalamadan)",
                           lambda: self._account_login(prov, kind, model))
            added = True
        agent = cli_agents.AGENTS.get(prov.login)
        if agent is not None:
            if cli_agents.available(agent.provider):
                text = f"✓  {agent.via} kullanılıyor — {agent.title} (kod menüsünde)"
            elif cli_agents.installed(agent.provider):
                text = f"🔑  {agent.via} giriş yap — {agent.title}"
            else:
                text = f"🔑  {agent.via} kullan — önce {agent.title} kurulur"
            menu.addAction(text, lambda p=agent.provider: self._cli_connect(p))
            added = True
        return added

    # ---- tarayıcıda giriş: OpenRouter, Hugging Face
    def _account_login(self, prov, kind: str, model: str = ""):
        if getattr(self, "_login_running", False):
            self._notify("bir giriş zaten sürüyor — tarayıcıya bak", 6000)
            return
        self._login_running = True
        self._notify(f"{prov.name}: tarayıcıda giriş yapıp onayla…", 300000)

        def done(result, error):
            self._login_running = False
            if error:
                self._notify(f"{prov.name} girişi yapılamadı: {describe_error(error)}", 15000)
                return
            key, session = result
            conn = Connection(kind="llm", name=prov.preset, base_url=LLM_PRESETS[prov.preset][0], preset=prov.preset)
            self.side_tabs.button(3).click()  # API'ler sekmesi: eklenen bağlantı orada görünsün
            self.api_panel.add_ready(conn, key, session)
            self._notify(f"✓ {prov.name} hesabınla bağlandı", 10000)
            if model:
                self._set_default_model(kind, f"api:{conn.id}|{model}")

        run_in_background(lambda: login_account(prov.login, self), done, self)

    # ---- aboneliğinle resmi program: Codex, Gemini CLI, Claude Code
    def _cli_connect(self, provider: str):
        agent = cli_agents.AGENTS[provider]
        if cli_agents.available(provider):
            self._set_default_model("code", f"{provider}|{agent.default}")
            return
        if getattr(self, "_cli_busy", False):
            self._notify("kurulum ya da giriş zaten sürüyor…", 6000)
            return
        if provider == cli_agents.CLAUDE.provider:  # Claude Code'u Anthropic kendi kurar
            QDesktopServices.openUrl(QUrl("https://claude.com/claude-code"))
            self._notify("Claude Code'u kurup terminalde bir kez `claude` yazarak giriş yap; sonra burada görünür",
                         20000)
            return
        installed = cli_agents.installed(provider)
        text = (f"{agent.title}, {agent.via} çalışan resmi programdır: API anahtarı gerekmez, "
                f"aboneliğinin kullanım hakkını kullanır.\n\n")
        if not installed:
            text += (f"Önce {agent.title} programın klasörüne kurulacak ({CLI_SIZES.get(provider, '')}, "
                     f"firmanın resmi GitHub sayfasından, SHA-256 doğrulamalı). Sistemine başka bir şey kurulmaz.\n\n")
        text += ("Sonra tarayıcıda hesabınla giriş yapıp onaylarsın. Giriş bilgisini program görmez; "
                 f"{agent.title} kendisi saklar.\n\n{agent.title} yalnızca senin sohbette gönderdiğin isteklerde, "
                 "iş klasöründe çalışır. Devam edilsin mi?")
        if QMessageBox.question(self, f"{agent.via} kullan", text) != QMessageBox.Yes:
            return
        self._cli_busy = True

        def progress(pct, msg):
            QTimer.singleShot(0, self, lambda: self._notify(f"{agent.title} kuruluyor · {msg}"
                                                            + (f" · %{pct}" if pct >= 0 else ""), 600000))

        def work():
            if not cli_agents.installed(provider):
                cli_agents.install(provider, progress)
            QTimer.singleShot(0, self, lambda: self._notify(
                f"{agent.title}: tarayıcıda {agent.via} giriş yapıp onayla…", 600000))
            cli_agents.login(provider)

        def done(_res, error):
            self._cli_busy = False
            if error:
                self._notify(f"{agent.title} hazırlanamadı: {describe_error(error)}", 20000)
                return
            self._notify(f"✓ {agent.title} hazır — {agent.via} kod ve genel işlerde kullanılıyor", 15000)
            self.api_panel.refresh()
            self._set_default_model("code", f"{provider}|{agent.default}")

        run_in_background(work, done, self)
