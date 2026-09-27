"""Ana pencerenin diyalogları ve mesaj kutusu: ayarlar, onay penceresi, giriş kutusu."""

import json
import threading

from PySide6.QtCore import Qt, QTimer, QUrl, Signal
from PySide6.QtGui import QDesktopServices, QKeyEvent
from PySide6.QtWidgets import (
    QCheckBox, QComboBox, QDialog, QDialogButtonBox, QFormLayout, QHBoxLayout, QLabel, QLineEdit,
    QPlainTextEdit, QPushButton, QSpinBox, QVBoxLayout,
)
from pathlib import Path

from .. import mcp, power
from ..config import Settings
from ..connections import load_connections
from ..tools import describe_risks

from .chat import tool_label, TOOL_LABELS
from .theme import ACCENTS, C, MONO


class InputBox(QPlainTextEdit):
    submitted = Signal()
    files_dropped = Signal(list)  # sürükle-bırak ile gelen yerel dosyalar

    def canInsertFromMimeData(self, source):  # noqa: N802
        return source.hasUrls() or super().canInsertFromMimeData(source)

    def insertFromMimeData(self, source):  # noqa: N802
        files = [u.toLocalFile() for u in source.urls() if u.isLocalFile()] if source.hasUrls() else []
        if files:
            self.files_dropped.emit(files)
        else:
            super().insertFromMimeData(source)

    def keyPressEvent(self, event: QKeyEvent):
        if event.key() in (Qt.Key_Return, Qt.Key_Enter) and not event.modifiers() & Qt.ShiftModifier:
            self.submitted.emit()
            return
        super().keyPressEvent(event)


class SettingsDialog(QDialog):
    def __init__(self, settings: Settings, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Ayarlar")
        self.setMinimumWidth(600)
        form = QFormLayout(self)
        form.setContentsMargins(20, 20, 20, 20)
        form.setSpacing(12)
        self.ollama_url = QLineEdit(settings.ollama_url)
        self.num_ctx = QSpinBox()
        from ..ctxprobe import FLOOR_CTX

        self.num_ctx.setRange(FLOOR_CTX, 131072)  # daha azına talimat sığmaz (ctxprobe.FLOOR_CTX)
        self.num_ctx.setSingleStep(2048)
        self.num_ctx.setValue(settings.ollama_num_ctx)
        self.num_ctx.setToolTip("Büyük bağlam daha çok ekran kartı belleği ister.")
        self.auto_ctx = QCheckBox("Bağlamı sisteme göre otomatik ayarla (önerilen)")
        self.auto_ctx.setToolTip("Açılışta model farklı bağlamlarla denenir; tamamen ekran kartına "
                                 "sığan en büyük değer kullanılır.")
        self.auto_ctx.setChecked(settings.auto_ctx)
        self.num_ctx.setEnabled(not settings.auto_ctx)
        self.auto_ctx.toggled.connect(lambda on: self.num_ctx.setEnabled(not on))
        self.remeasure = QPushButton("Yeniden ölç", objectName="smallButton")
        self.remeasure.setToolTip("Kayıtlı ölçümleri siler; bağlam bir sonraki kontrolde yeniden ölçülür.")
        self.remeasure.clicked.connect(lambda: (settings.ctx_probe.clear(), self.remeasure.setText("Ölçüm sıfırlandı ✓")))
        self.accent = QComboBox()
        for name, color in ACCENTS.items():
            self.accent.addItem(name, color)
        self.accent.setCurrentIndex(max(self.accent.findData(settings.accent), 0))
        self.accent.setToolTip("Değişiklik program yeniden açılınca uygulanır.")
        self.confirm = QCheckBox("Komut ve Python çalıştırmadan önce onay iste")
        self.confirm.setChecked(settings.confirm_commands)
        moved = QLabel("API anahtarları artık sol paneldeki 🔑 API'ler sekmesinde.", objectName="hint")
        form.addRow(moved)
        form.addRow("Ollama adresi:", self.ollama_url)
        ctx_row = QHBoxLayout()
        ctx_row.addWidget(self.num_ctx)
        ctx_row.addWidget(self.remeasure)
        form.addRow("Ollama bağlam (token):", ctx_row)
        form.addRow("", self.auto_ctx)
        form.addRow("Vurgu rengi:", self.accent)
        from .. import specialists

        form.addRow(QLabel("MODEL SEÇİMİ — işleri kim, hangi modelle yapsın", objectName="label"))
        self.auto_model = QCheckBox("Modelleri program seçsin (önerilen)")
        self.auto_model.setToolTip("Ana asistan, ajanlar ve yönetici her iş için uygun modeli kendileri seçer.")
        self.auto_model.setChecked(settings.auto_model)
        form.addRow("", self.auto_model)
        self.policy = QComboBox()
        self.policy.addItem("Önce yerel modeller (ücretsiz, bilgisayarında)", "yerel")
        self.policy.addItem("En güçlü model (bulut dahil, ücretli olabilir)", "guclu")
        self.policy.setCurrentIndex(max(self.policy.findData(settings.model_policy), 0))
        form.addRow("Öncelik:", self.policy)
        self.power = QComboBox()
        for value, text in power.MODES.items():
            self.power.addItem(text, value)
        self.power.setCurrentIndex(max(self.power.findData(settings.power_mode), 0))
        self.power.setToolTip("Pildeyken ekran kartı güç sınırına takılır; hafif modda küçük model, 8K bağlam ve "
                              "düşünmesiz yanıt kullanılır. Fişe takılınca program kendiliğinden tam güce döner.")
        form.addRow("Güç:", self.power)

        experts = QLabel("UZMAN MODELLER — asistanın danıştığı modeller", objectName="label")
        form.addRow(experts)
        local = specialists.ollama_models(settings)
        vision = specialists.vision_models(settings)
        self.expert_boxes = {}
        for role, title in [("vision", "Görsel (resim):"), ("reasoning", "Derin düşünme:"), ("code", "Kod:")]:
            box = QComboBox()
            saved = settings.specialists.get(role, "")
            box.addItem(f"otomatik ({specialists.describe(Settings(**{**settings.__dict__, 'specialists': {}}), role)})", "")
            for m in (vision if role == "vision" else local):
                box.addItem(m, f"ollama|{m}")
            box.addItem(f"Claude · {settings.claude_model}", f"claude|{settings.claude_model}")
            for conn in load_connections():  # Gemini, OpenAI vb. bağlı bulut sağlayıcıları
                if conn.kind == "llm":
                    for m in conn.models:
                        box.addItem(f"{conn.name} · {m}", f"api:{conn.id}|{m}")
            box.setCurrentIndex(max(box.findData(saved), 0))
            self.expert_boxes[role] = box
            form.addRow(title, box)
        if not vision:
            tip = QLabel("Resim görebilen yerel model yok. Yardım → Model önerileri'nden tek tıkla kurabilirsin.",
                         objectName="hint")
            form.addRow("", tip)
        form.addRow(QLabel("ARAÇLAR — takılan MCP sunucuları", objectName="label"))
        self.mcp_status = QLabel(objectName="hint")
        self.mcp_status.setWordWrap(True)
        self.mcp_status.setTextInteractionFlags(Qt.TextSelectableByMouse)
        form.addRow("MCP:", self.mcp_status)
        mcp_row = QHBoxLayout()
        edit_mcp = QPushButton("mcp.json'u aç")
        edit_mcp.setToolTip("Sunucuları Claude Desktop ile aynı biçimde ekle; kaydettikten sonra “yeniden yükle”.")
        edit_mcp.clicked.connect(self._open_mcp_config)
        reload_mcp = QPushButton("yeniden yükle")
        reload_mcp.clicked.connect(lambda: threading.Thread(
            target=mcp.reload, args=(settings.workspace,), daemon=True).start())
        mcp_row.addWidget(edit_mcp)
        mcp_row.addWidget(reload_mcp)
        mcp_row.addStretch()
        form.addRow("", mcp_row)
        self._show_mcp()
        self.mcp_timer = QTimer(self)  # sunucular arka planda başlar: durum her saniye yenilenir
        self.mcp_timer.timeout.connect(self._show_mcp)
        self.mcp_timer.start(1000)
        form.addRow(QLabel("BULUT ASİSTAN — bilgisayar kapalıyken Telegram / web'den", objectName="label"))
        cloud = settings.extra.get("cloud") or {}
        self.cloud_url = QLineEdit(cloud.get("url", ""), placeholderText="ör. http://100.64.0.5:8765 (Tailscale adresi)")
        self.cloud_token = QLineEdit(cloud.get("token", ""), placeholderText="sunucu kurulurken verilen erişim anahtarı")
        self.cloud_token.setEchoMode(QLineEdit.Password)
        self.cloud_on = QCheckBox("Hafızayı eşitle ve buluttan gelen işleri göster")
        self.cloud_on.setChecked(cloud.get("enabled", True))
        cloud_row = QHBoxLayout()
        test_btn = QPushButton("Bağlantıyı dene", objectName="smallButton")
        self.cloud_status = QLabel(objectName="hint")
        test_btn.clicked.connect(self._test_cloud)
        cloud_row.addWidget(test_btn)
        cloud_row.addWidget(self.cloud_status, 1)
        form.addRow("Adres:", self.cloud_url)
        form.addRow("Anahtar:", self.cloud_token)
        form.addRow("", self.cloud_on)
        form.addRow("", cloud_row)
        cloud_hint = QLabel("Bulut asistan bilgisayarına erişemez; yerel dosya gereken işleri kuyruğa bırakır, "
                            "burada listelenir ve sen onaylarsan yapılır. Kurulum: programın klasöründeki "
                            "sunucu/BENIOKU.md.", objectName="hint")
        cloud_hint.setWordWrap(True)
        form.addRow("", cloud_hint)
        form.addRow(QLabel("DİKTE VE GÜNCELLEMELER", objectName="label"))
        extra = settings.extra or {}
        self.dictation_lang = QComboBox()
        for text, code in (("Türkçe", "tr"), ("Kendisi bulsun (karışık dillerde)", ""), ("İngilizce", "en")):
            self.dictation_lang.addItem(text, code)
        self.dictation_lang.setCurrentIndex(max(0, self.dictation_lang.findData(extra.get("dikte_dil", "tr"))))
        form.addRow("Dikte dili:", self.dictation_lang)
        self.dictation_clean = QCheckBox("Dikte metnini düzenle (ııı, tekrarlar, noktalama; küçük yerel modelle)")
        self.dictation_clean.setChecked(extra.get("dikte_temizle", True))
        form.addRow("", self.dictation_clean)
        self.auto_update = QCheckBox("Güncellemeleri kendiliğinden denetle (günde bir kez; kurmadan önce sorar)")
        self.auto_update.setChecked(extra.get("guncelleme_otomatik", True))
        form.addRow("", self.auto_update)
        self.collect_results = QCheckBox("İşlerin sonuçlarını (görsel, 3D model, belge) masaüstünde "
                                         "YENİ NESİL CAFER/Sonuçlar klasöründe topla")
        self.collect_results.setChecked(extra.get("sonuclari_topla", True))
        form.addRow("", self.collect_results)
        form.addRow(QLabel("ONAYLAR — işlemlere kim izin versin", objectName="label"))
        self.approval = QComboBox()
        self.approval.addItem("🛡 Güvenlik ajanı onaylasın (varsayılan): engellediğinde nedenini gösterir", "guvenlik")
        self.approval.addItem("Ben onaylarım: önce ▶ uygula düğmesi, sonra her adımda bana sorulsun", "kullanici")
        self.approval.setCurrentIndex(max(0, self.approval.findData(settings.approval_mode)))
        form.addRow("Onay:", self.approval)
        guard = QLabel("Güvenlik ajanı her komut, kod ve dosya işlemini risk düzeyine göre denetler: güvenli olanları "
                       "onaylar, hatalıları geri çevirip başka yol denetir, zararlıları reddeder; kararlar sohbette "
                       "notla görünür.", objectName="hint")
        guard.setWordWrap(True)
        form.addRow("", guard)
        self.approval.currentIndexChanged.connect(
            lambda: self.confirm.setVisible(self.approval.currentData() == "kullanici"))
        form.addRow(self.confirm)
        self.confirm.setVisible(settings.approval_mode == "kullanici")
        buttons = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Cancel)
        buttons.button(QDialogButtonBox.Save).setText("Kaydet")
        buttons.button(QDialogButtonBox.Save).setObjectName("primary")
        buttons.button(QDialogButtonBox.Cancel).setText("Vazgeç")
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        form.addRow(buttons)

    def _show_mcp(self):
        self.mcp_status.setText(_mcp_summary())

    def _test_cloud(self):
        from .. import cloud_sync

        probe = type("S", (), {"extra": {"cloud": {"url": self.cloud_url.text().strip(),
                                                   "token": self.cloud_token.text().strip()}}})()
        try:
            self.cloud_status.setText("✓ " + cloud_sync.check(probe))
        except Exception as e:
            self.cloud_status.setText(f"✗ {e}")

    def _open_mcp_config(self):
        try:
            mcp.load_config()  # yoksa boş örnek dosyayı oluşturur
        except mcp.McpError:
            pass  # bozuk dosya da açılsın ki düzeltilebilsin
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(mcp.CONFIG_FILE)))

    def apply_to(self, settings: Settings):
        settings.ollama_url = self.ollama_url.text().strip() or "http://localhost:11434"
        settings.ollama_num_ctx = self.num_ctx.value()
        settings.confirm_commands = self.confirm.isChecked()
        settings.approval_mode = self.approval.currentData()
        settings.auto_ctx = self.auto_ctx.isChecked()
        settings.accent = self.accent.currentData()
        settings.auto_model = self.auto_model.isChecked()
        settings.model_policy = self.policy.currentData()
        if self.power.currentData() != settings.power_mode:
            settings.extra = {**settings.extra, "power_override": False}  # Ayarlar'dan seçilen kalıcı
        settings.power_mode = self.power.currentData()
        url, token = self.cloud_url.text().strip(), self.cloud_token.text().strip()
        extra = dict(settings.extra)
        extra["dikte_dil"] = self.dictation_lang.currentData()
        extra["dikte_temizle"] = self.dictation_clean.isChecked()
        extra["guncelleme_otomatik"] = self.auto_update.isChecked()
        extra["sonuclari_topla"] = self.collect_results.isChecked()
        if url and token:
            extra["cloud"] = {"url": url, "token": token, "enabled": self.cloud_on.isChecked()}
        else:
            extra.pop("cloud", None)
        settings.extra = extra
        for role, box in self.expert_boxes.items():
            if box.currentData():
                settings.specialists[role] = box.currentData()
            else:
                settings.specialists.pop(role, None)


def _mcp_summary() -> str:
    rows = mcp.status()
    if not rows:
        return ("Henüz sunucu yok. Hazır MCP sunucuları (dosya, tarayıcı, veritabanı, GitHub…) mcp.json'a eklenince "
                "araçları asistana kendiliğinden verilir. Salt okuyan araçlar onaysız, diğerleri onayla çalışır.")
    marks = {"çalışıyor": "✓", "başlıyor": "…", "hata": "✗", "kapalı": "○", "devre dışı": "–"}
    return "\n".join(f"{marks.get(r['state'], '?')} {r['name']}: {r['state']}"
                     + (f" · {r['tools']} araç" if r["tools"] else "")
                     + (f" — {r['error'][:160]}" if r["error"] else "") for r in rows)


class ApprovalDialog(QDialog):
    """Onay penceresi: ne yapacak ve neden, dikkat edilecekler, sonra kod."""

    def __init__(self, name: str, args: dict, workspace: str, context: str = "", parent=None):
        super().__init__(parent)
        self.setWindowTitle("Onay gerekiyor")
        self.setMinimumWidth(680)
        self.choice = "deny"
        lay = QVBoxLayout(self)
        lay.setContentsMargins(24, 20, 24, 18)
        lay.setSpacing(6)
        title = QLabel("Bu işlemi onaylıyor musun?")
        title.setStyleSheet(f"font-size: 18px; font-weight: 500; color: {C['text']};")
        lay.addWidget(title)
        where = workspace.replace(str(Path.home()), "~")
        lay.addWidget(QLabel(f"{tool_label(name)} · klasör: {where}", objectName="stamp"))

        lay.addSpacing(14)
        lay.addWidget(QLabel("NE YAPACAK VE NEDEN", objectName="label"))
        purpose = str(args.get("purpose") or "").strip()
        if not purpose and context.strip():
            purpose = "Asistanın bu adımdan hemen önce yazdığı:\n“" + context.strip()[-500:] + "”"
        why = QLabel(purpose or "Asistan bu adım için bir açıklama yazmadı. Aşağıdaki koda ve uyarılara bakarak karar ver; "
                                "emin değilsen reddet ve asistana ne yapmak istediğini sor.")
        why.setWordWrap(True)
        why.setTextInteractionFlags(Qt.TextSelectableByMouse)
        why.setStyleSheet(f"font-size: 15px; color: {C['text'] if purpose else C['text2']};")
        lay.addWidget(why)

        lay.addSpacing(14)
        lay.addWidget(QLabel("DİKKAT", objectName="label"))
        risks = describe_risks(name, args, workspace)
        if risks:
            for r in risks:
                line = QLabel(f"!  {r}")
                line.setWordWrap(True)
                line.setStyleSheet(f"color: {C['warn']}; font-family: '{MONO}'; font-size: 12.5px;")
                lay.addWidget(line)
        else:
            ok = QLabel("✓  Belirgin bir risk görünmüyor: dosya silmiyor, bir şey kurmuyor, klasör dışına çıkmıyor.")
            ok.setWordWrap(True)
            ok.setStyleSheet(f"color: {C['success']}; font-family: '{MONO}'; font-size: 12.5px;")
            lay.addWidget(ok)
        lay.addWidget(QLabel("Bu uyarılar kodun otomatik taranmasıyla çıkarılır; her şeyi yakalayamaz.",
                             objectName="stamp"))

        lay.addSpacing(14)
        heading = {"run_command": "KOMUT", "run_python": "PYTHON KODU", "call_api": "İSTEK",
                   "install_python_package": "KURULACAK KÜTÜPHANELER", "write_file": "YAZILACAK DOSYA",
                   "edit_file": "DÜZENLENECEK DOSYA", "add_tool": "EKLENECEK ARACIN KODU",
                   "browser_click": "TIKLANACAK ÖĞE", "browser_type": "YAZILACAK ALAN"}.get(name, "AYRINTI")
        lay.addWidget(QLabel(heading, objectName="label"))
        if name in ("browser_click", "browser_type"):
            detail = f"Sayfa: {args.get('page', '')}\nÖğe: {args.get('element', '')}"
            if name == "browser_type":
                detail += f"\nYazılacak: {args.get('text', '')}" + ("\n(ardından Enter)" if args.get("submit") else "")
        elif name == "add_tool":
            detail = f"{args.get('name', '')} — {args.get('description', '')}\n\n{args.get('code', '')}"
        elif name == "call_api" or name not in TOOL_LABELS:  # API isteği ve MCP araçları: gönderilecek girdiler
            detail = json.dumps({k: v for k, v in args.items() if k != "purpose"}, ensure_ascii=False, indent=1)
        elif name == "write_file":
            detail = f"{args.get('path', '')}\n\n{args.get('content', '')}"
        elif name == "edit_file":
            detail = f"{args.get('path', '')}\n\n— eski —\n{args.get('old_text', '')}\n\n— yeni —\n{args.get('new_text', '')}"
        elif name == "install_python_package":
            detail = args.get("packages", "")
        else:
            detail = args.get("command") if name == "run_command" else args.get("code", "")
        code = QPlainTextEdit(str(detail or ""), readOnly=True, objectName="preview")
        code.setMinimumHeight(150)
        code.setMaximumHeight(260)
        lay.addWidget(code)

        lay.addSpacing(10)
        row = QHBoxLayout()
        allow = QPushButton({"add_tool": "aracı ekle", "browser_click": "tıkla", "browser_type": "yaz"}.get(name, "çalıştır"),
                            objectName="primary")
        always = QPushButton("bu oturumda hep izin ver")
        always.setVisible(not name.startswith("browser_"))  # tarayıcı kapısı her seferinde sorar
        deny = QPushButton("reddet")
        allow.clicked.connect(lambda: self._done("allow"))
        always.clicked.connect(lambda: self._done("always"))
        deny.clicked.connect(lambda: self._done("deny"))
        row.addWidget(allow)
        row.addWidget(always)
        row.addStretch()
        row.addWidget(deny)
        lay.addLayout(row)
        deny.setFocus()

    def _done(self, choice: str):
        self.choice = choice
        self.accept()
