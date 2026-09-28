"""İlk kurulum sihirbazı: çalışma klasörü → sistem taraması ve Ollama → önerilen yerel modelleri indirme → bitiş.

Program ilk kez açıldığında (ayar dosyası yokken) kendiliğinden, sonra Yardım menüsünden açılır.
"""

import threading
from pathlib import Path

from PySide6.QtCore import QObject, Qt, QUrl, Signal
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (
    QApplication, QCheckBox, QDialog, QFileDialog, QHBoxLayout, QLabel, QLineEdit, QProgressBar, QPushButton,
    QScrollArea, QStackedWidget, QVBoxLayout, QWidget,
)

from .. import sysinfo
from ..config import Settings
from .theme import C


class _Bridge(QObject):
    """İndirme iş parçacığından arayüze ilerleme bildirir."""

    progress = Signal(str, int, str)  # model, yüzde (-1: bilinmiyor), durum
    done = Signal(str, str)  # model, hata metni ("" başarılı)
    ollama = Signal(str, bool)  # Ollama kurulumu: durum metni, bitti mi


class SetupWizard(QDialog):
    def __init__(self, settings: Settings, parent=None):
        super().__init__(parent)
        self.settings = settings
        self.setWindowTitle("YENİ NESİL CAFER — kurulum")
        self.setMinimumSize(700, 540)
        self.info: sysinfo.SystemInfo | None = None
        self.pulling = False
        self._cancel = threading.Event()
        self.bridge = _Bridge()
        self.bridge.progress.connect(self._on_progress)
        self.bridge.done.connect(self._on_done)
        self.bridge.ollama.connect(self._on_ollama)
        self._ollama_busy = False

        outer = QVBoxLayout(self)
        outer.setContentsMargins(28, 24, 28, 20)
        self.step_label = QLabel(objectName="label")
        outer.addWidget(self.step_label)
        self.pages = QStackedWidget()
        outer.addWidget(self.pages, 1)
        nav = QHBoxLayout()
        self.skip_btn = QPushButton("Kurulumu atla", objectName="smallButton")
        self.skip_btn.clicked.connect(self.reject)
        self.back_btn = QPushButton("Geri")
        self.back_btn.clicked.connect(lambda: self._go(self.pages.currentIndex() - 1))
        self.next_btn = QPushButton("İleri", objectName="primary")
        self.next_btn.clicked.connect(self._next)
        nav.addWidget(self.skip_btn)
        nav.addStretch()
        nav.addWidget(self.back_btn)
        nav.addWidget(self.next_btn)
        outer.addLayout(nav)

        self.pages.addWidget(self._page_welcome())
        self.pages.addWidget(self._page_system())
        self.pages.addWidget(self._page_kaynak())  # K10: kademe → yerel / bulut / ikisi → gizlilik
        self.pages.addWidget(self._page_models())
        self.pages.addWidget(self._page_done())
        self._go(0)

    # ---- yardımcılar
    @staticmethod
    def _title(text: str) -> QLabel:
        label = QLabel(text, objectName="welcomeTitle")
        label.setStyleSheet("font-size: 24px;")
        return label

    @staticmethod
    def _text(text: str) -> QLabel:
        label = QLabel(text, objectName="welcomeText")
        label.setWordWrap(True)
        label.setTextFormat(Qt.RichText)
        label.setOpenExternalLinks(True)
        return label

    def _go(self, index: int):
        index = max(0, min(index, self.pages.count() - 1))
        self.pages.setCurrentIndex(index)
        names = ["hoş geldin", "sistem", "modeller nereden", "yerel modeller", "hazır"]
        self.step_label.setText(f"ADIM {index + 1} / {len(names)}  ·  {names[index].upper()}")
        self.back_btn.setVisible(0 < index < 4)
        self.skip_btn.setVisible(index < 4)
        self.next_btn.setText("Başla" if index == 4 else "İleri")
        if index == 1 and self.info is None:
            self._scan()
        if index == 2:
            self._kaynak_doldur()
        if index == 3:
            self._fill_models()

    def _next(self):
        index = self.pages.currentIndex()
        if index == 0:
            path = self.workspace.text().strip()
            if path:
                self.settings.workspace = str(Path(path).expanduser())
        if index == 2:  # model kaynağı + gizlilik kaydedilir; yalnızca bulut seçildiyse yerel model sayfası atlanır
            self._kaynak_kaydet()
            self._go(4 if self.src_bulut.isChecked() else 3)
            return
        if index == 3 and self.pulling:
            return
        if index == 4:
            self._finish()
            return
        self._go(index + 1)

    # ---- 1: hoş geldin + çalışma klasörü
    def _page_welcome(self) -> QWidget:
        page = QWidget()
        col = QVBoxLayout(page)
        col.addWidget(self._title("Merhaba, hoş geldin."))
        col.addSpacing(8)
        col.addWidget(self._text(
            "YENİ NESİL CAFER bilgisayarında çalışan kişisel bir yapay zekâ asistanı ve ekibidir. Sohbet eder, "
            "dosyalarınla çalışır, web'de araştırır, işleri uzman ajanlara dağıtır. Birkaç adımda bilgisayarını "
            "tarayıp sana uygun yerel modelleri kuracağız."))
        col.addSpacing(18)
        col.addWidget(QLabel("ÇALIŞMA KLASÖRÜ", objectName="label"))
        col.addWidget(self._text("Asistanın dosya okuyup yazacağı klasör. Dışına çıkamaz."))
        row = QHBoxLayout()
        self.workspace = QLineEdit(self.settings.workspace)
        pick = QPushButton("Seç…")
        pick.clicked.connect(self._pick_folder)
        row.addWidget(self.workspace, 1)
        row.addWidget(pick)
        col.addLayout(row)
        col.addStretch()
        return page

    def _pick_folder(self):
        path = QFileDialog.getExistingDirectory(self, "Çalışma klasörü", self.workspace.text())
        if path:
            self.workspace.setText(path)

    # ---- 3: kademe → modeller nereden (yerel / bulut / ikisi) → gizlilik (K10)
    def _page_kaynak(self) -> QWidget:
        from PySide6.QtWidgets import QComboBox, QRadioButton

        page = QWidget()
        col = QVBoxLayout(page)
        col.addWidget(self._title("Modeller nereden çalışsın?"))
        self.kademe_text = self._text("")
        col.addWidget(self.kademe_text)
        col.addSpacing(10)
        self.src_yerel = QRadioButton("Yerel modeller — ücretsiz, çevrimdışı, bilgisayarında (Ollama)")
        self.src_bulut = QRadioButton("Bulut anahtarı — Claude API (ücretli, hızlı; zayıf bilgisayarda önerilir)")
        self.src_ikisi = QRadioButton("İkisi — basit işler yerelde, karmaşık işler bulutta")
        for r in (self.src_yerel, self.src_bulut, self.src_ikisi):
            col.addWidget(r)
        col.addSpacing(8)
        col.addWidget(QLabel("CLAUDE API ANAHTARI (isteğe bağlı; anahtar zincirinde saklanır)", objectName="label"))
        self.api_key = QLineEdit(placeholderText="sk-ant-… (boş bırakılabilir; sonra Ayarlar → API'ler)")
        self.api_key.setEchoMode(QLineEdit.Password)
        col.addWidget(self.api_key)
        col.addSpacing(8)
        col.addWidget(QLabel("GİZLİLİK", objectName="label"))
        self.gizlilik = QComboBox()
        self.gizlilik.addItem("Karma: basit işler yerelde, gerekirse bulut", "karma")
        self.gizlilik.addItem("Yalnızca yerel: hiçbir şey buluta gitmez", "yerel")
        self.gizlilik.addItem("Bulut öncelikli: bağlı bulut modelleri önce", "bulut")
        col.addWidget(self.gizlilik)
        col.addWidget(self._text("Bunların hepsi sonradan Ayarlar'dan değiştirilebilir. Model seçmek zorunda "
                                 "değilsin; program işe ve bilgisayarına göre seçer."))
        col.addStretch()
        return page

    def _kaynak_doldur(self):
        """Ölçülen kademeye göre varsayılan seçim: yüksek → yerel, orta → ikisi, düşük → bulut (MIMARI §3)."""
        from ..cekirdek import profil

        kademe = profil.kademe()
        neden = ((profil.yukle() or {}).get("kademe") or {}).get("neden", "")
        self.kademe_text.setText(f"Bilgisayarının kademesi: <b>{profil.ADLAR.get(kademe, kademe)}</b>"
                                 + (f" — {neden}" if neden else "") + "<br>"
                                 + {"dusuk": "Bu kademede yerel modeller yavaş kalır; bulut anahtarı önerilir.",
                                    "orta": "Küçük ve orta modeller yerelde rahat çalışır; ağır işler için bulut iyi olur.",
                                    "yuksek": "Yerel modeller rahat çalışır; bulut isteğe bağlı."}.get(kademe, ""))
        if not any(r.isChecked() for r in (self.src_yerel, self.src_bulut, self.src_ikisi)):
            {"dusuk": self.src_bulut, "orta": self.src_ikisi}.get(kademe, self.src_yerel).setChecked(True)
        if kademe == "dusuk":
            self.gizlilik.setCurrentIndex(max(0, self.gizlilik.findData("bulut")))

    def _kaynak_kaydet(self):
        s = self.settings
        s.extra["gizlilik"] = self.gizlilik.currentData()  # cekirdek/yonlendirici EXTRA_GIZLILIK
        s.extra["model_kaynagi"] = "bulut" if self.src_bulut.isChecked() else "yerel" if self.src_yerel.isChecked() else "ikisi"
        if self.src_bulut.isChecked():
            s.model_policy = "guclu"
        anahtar = self.api_key.text().strip()
        if anahtar:
            try:
                from ..connections import ANTHROPIC_KEY
                from ..keystore import set_secret

                set_secret(ANTHROPIC_KEY, anahtar)
            except Exception as e:  # anahtar zinciri yok: kullanıcı Ayarlar → API'ler'den girer
                self.kademe_text.setText(self.kademe_text.text() + f"<br>Anahtar saklanamadı: {e}")
        s.save()

    # ---- 2: sistem taraması + Ollama
    def _page_system(self) -> QWidget:
        page = QWidget()
        col = QVBoxLayout(page)
        col.addWidget(self._title("Sistemin"))
        self.scan_text = self._text("taranıyor…")
        col.addWidget(self.scan_text)
        col.addSpacing(12)
        self.ollama_box = QWidget()
        box = QVBoxLayout(self.ollama_box)
        box.setContentsMargins(0, 0, 0, 0)
        box.addWidget(QLabel("OLLAMA — YEREL MODELLERİ ÇALIŞTIRAN PROGRAM", objectName="label"))
        self.ollama_text = self._text("")
        box.addWidget(self.ollama_text)
        row = QHBoxLayout()
        self.ollama_cmd = QLineEdit()
        self.ollama_cmd.setReadOnly(True)
        self.copy_btn = QPushButton("kopyala / aç", objectName="smallButton")
        self.copy_btn.clicked.connect(self._ollama_action)
        again = QPushButton("tekrar kontrol et", objectName="smallButton")
        again.clicked.connect(self._scan)
        row.addWidget(self.ollama_cmd, 1)
        row.addWidget(self.copy_btn)
        row.addStretch(0)
        row.addWidget(again, 0, Qt.AlignRight)
        box.addLayout(row)
        col.addWidget(self.ollama_box)
        col.addStretch()
        return page

    def _scan(self):
        self.scan_text.setText("taranıyor…")
        QApplication.processEvents()
        info = self.info = sysinfo.scan(self.settings.ollama_url)
        gpu = f"{info.gpu} · {info.vram_gb:.0f} GB" if info.gpu else "ayrı ekran kartı bulunamadı"
        self.scan_text.setText(
            f"<table cellpadding=3>"
            f"<tr><td style='color:{C['muted']}'>sistem</td><td>{info.os_name}</td></tr>"
            f"<tr><td style='color:{C['muted']}'>işlemci</td><td>{info.cpu} · {info.cores} çekirdek</td></tr>"
            f"<tr><td style='color:{C['muted']}'>bellek</td><td>{info.ram_gb:.0f} GB</td></tr>"
            f"<tr><td style='color:{C['muted']}'>ekran kartı</td><td>{gpu}</td></tr>"
            f"<tr><td style='color:{C['muted']}'>boş disk</td><td>{info.disk_free_gb:.0f} GB</td></tr>"
            f"<tr><td style='color:{C['muted']}'>ollama</td><td>"
            + ("çalışıyor ✓" if info.ollama_running else ("kurulu, çalışmıyor" if info.ollama_installed else "kurulu değil"))
            + "</td></tr></table>")
        if not info.ollama_running and info.ollama_installed and not getattr(self, "_started", False):
            # kurulu ama çalışmıyor: kullanıcıya komut yazdırmadan program başlatır (bir kez)
            self._started = True
            self.ollama_text.setText("Ollama başlatılıyor…")
            QApplication.processEvents()
            if sysinfo.ensure_ollama(self.settings.ollama_url):
                return self._scan()
        if info.ollama_running:
            self.ollama_text.setText(f"Hazır. Kurulu modeller: {', '.join(info.ollama_models) or 'henüz yok'}.")
            self.ollama_cmd.hide()
            self.copy_btn.hide()
        elif not info.ollama_installed:
            # kurulum yarım kaldıysa ya da internet paketinden: program kendisi indirip kurar (asistan/bootstrap.py)
            self.ollama_text.setText("Ollama kurulu değil. Program resmi sürümü indirip kendisi kurabilir (~1,4 GB, "
                                     "SHA-256 doğrulamalı). Ollama olmadan da bulut modelleriyle (Claude, Gemini, GPT) "
                                     "kullanabilirsin; bu adımı geçebilirsin.")
            self.ollama_cmd.hide()
            self.copy_btn.show()
            self.copy_btn.setText("Ollama'yı indir ve kur")
        else:
            hint, target = sysinfo.install_hint(info)
            if info.ollama_installed:
                hint = "Ollama kurulu ama çalışmıyor. Başlatıp “tekrar kontrol et”e bas:"
                target = "ollama serve" if not target.startswith("http") else "Başlat menüsünden Ollama'yı aç"
            self.ollama_text.setText(hint + " Ollama olmadan da bulut modelleriyle (Claude, Gemini, GPT) "
                                     "kullanabilirsin; bu adımı geçebilirsin.")
            self.ollama_cmd.setText(target)
            self.ollama_cmd.show()
            self.copy_btn.show()
            self.copy_btn.setText("indirme sayfasını aç" if target.startswith("http") else "komutu kopyala")

    def _ollama_action(self):
        if self.info and not self.info.ollama_installed:
            return self._install_ollama()
        target = self.ollama_cmd.text()
        if target.startswith("http"):
            QDesktopServices.openUrl(QUrl(target))
        else:
            QApplication.clipboard().setText(target)
            self.copy_btn.setText("kopyalandı ✓")

    def _install_ollama(self):
        if self._ollama_busy:
            return
        from .. import bootstrap

        self._ollama_busy = True
        self.copy_btn.setEnabled(False)
        self.next_btn.setEnabled(False)

        def work():
            try:
                bootstrap.ollama(sysinfo.APP_DIR, ilerleme=lambda _pct, text: self.bridge.ollama.emit(text, False))
                sysinfo.ensure_ollama(self.settings.ollama_url)
                self.bridge.ollama.emit("", True)
            except (Exception, SystemExit) as e:  # noqa: BLE001 — metin kullanıcıya gösterilir
                self.bridge.ollama.emit(f"Ollama kurulamadı: {str(e).strip()[:160]}", True)

        threading.Thread(target=work, daemon=True).start()

    def _on_ollama(self, text: str, finished: bool):
        if text:
            self.ollama_text.setText(text)
        if finished:
            self._ollama_busy = False
            self.copy_btn.setEnabled(True)
            self.next_btn.setEnabled(True)
            if not text:
                self._scan()

    # ---- 3: önerilen modeller
    def _page_models(self) -> QWidget:
        page = QWidget()
        col = QVBoxLayout(page)
        col.addWidget(self._title("Yerel modeller"))
        self.reco_text = self._text("")
        col.addWidget(self.reco_text)
        col.addSpacing(10)
        scroll = QScrollArea()  # öneriler çoğalınca pencere taşmasın
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QScrollArea.NoFrame)
        inner = QWidget()
        self.model_rows = QVBoxLayout(inner)
        self.model_rows.setContentsMargins(0, 0, 8, 0)
        scroll.setWidget(inner)
        col.addWidget(scroll, 1)
        col.addSpacing(10)
        row = QHBoxLayout()
        self.pull_btn = QPushButton("Seçilenleri indir", objectName="primary")
        self.pull_btn.clicked.connect(self._start_pull)
        self.pull_status = QLabel("", objectName="keyHint")
        row.addWidget(self.pull_btn)
        row.addWidget(self.pull_status, 1)
        col.addLayout(row)
        col.addStretch()
        self.checks: dict[str, QCheckBox] = {}
        self.sizes: dict[str, float] = {}
        self.bars: dict[str, QProgressBar] = {}
        return page

    def _fill_models(self):
        if self.checks or self.info is None:
            return
        from .. import model_updates

        self.reco_text.setText("güncel model listesi alınıyor…")
        QApplication.processEvents()
        live = model_updates.refresh()  # internet varsa günlük liste; yoksa eldeki / programla gelen liste
        text, suggestions = sysinfo.recommend(self.info, live)
        self.bundled = sysinfo.bundled_modelfile() is not None
        extra = "" if self.info.ollama_running else " <b>Ollama çalışmadığı için şimdi indirilemez</b>; " \
                                                    "sonra Offline menüsünden kurabilirsin."
        self.reco_text.setText(f"{text} Temel asistan her bilgisayarda çalışır; diğerleri her yetenek için "
                               f"sistemine sığan en güçlü modeller. Kod ve derin düşünme isteğe bağlı.{extra}")
        for sug in suggestions:
            have = sug.model in self.info.ollama_models
            from_bundle = sug.kind == "base" and self.bundled and not have
            where = "   ·   kurulu ✓" if have else ("   ·   paketten kurulur, indirme yok" if from_bundle else "")
            prefix = "   ↳ seçenek: " if sug.alternative else ""
            check = QCheckBox(f"{prefix}{sug.title}  ·  {sug.model}  ·  {sug.size:.1f} GB{where}")
            check.setToolTip(sug.note)
            check.setChecked(sug.checked and not have)
            check.setEnabled(not have and self.info.ollama_running)
            check.toggled.connect(self._update_total)
            note = QLabel(sug.note, objectName="keyHint")
            note.setContentsMargins(26, 0, 0, 0)
            bar = QProgressBar()
            bar.setFixedHeight(4)
            bar.setTextVisible(False)
            bar.setValue(100 if have else 0)
            self.model_rows.addWidget(check)
            self.model_rows.addWidget(note)
            self.model_rows.addWidget(bar)
            self.checks[sug.model], self.bars[sug.model] = check, bar
            self.sizes[sug.model] = sug.size
        # sohbet modeli: sisteme uygun sohbet modeli, yoksa temel model (kurulunca kullanılır)
        chat = next((x.model for x in suggestions if x.kind == "chat" and not x.alternative), sysinfo.BASE_MODEL[0])
        self.chat_models = [chat, sysinfo.BASE_MODEL[0]]
        self._update_total()

    def _update_total(self):
        todo = [m for m, c in self.checks.items() if c.isChecked() and c.isEnabled()]
        # indirilecek boyut (paketten kurulan temel model hariç)
        size = sum(self.sizes.get(m, 0) for m in todo
                   if not (m == sysinfo.BASE_MODEL[0] and getattr(self, "bundled", False)))
        self.pull_btn.setEnabled(bool(todo) and bool(self.info and self.info.ollama_running))
        free = self.info.disk_free_gb if self.info else 0
        self.pull_btn.setText((f"Seçilenleri kur · {size:.1f} GB indirilecek" if size else "Seçilenleri kur")
                              if todo else "Kurulacak model yok")
        self.pull_status.setText("" if size < free else f"⚠ diskte yeterli yer yok ({free:.0f} GB boş)")

    def _start_pull(self):
        queue = [m for m, c in self.checks.items() if c.isChecked() and c.isEnabled()]
        if not queue:
            return
        self.pulling = True
        self.pull_btn.setEnabled(False)
        self.next_btn.setEnabled(False)
        url = self.settings.ollama_url

        def work():
            for m in queue:
                try:
                    if m == sysinfo.BASE_MODEL[0] and sysinfo.bundled_modelfile():  # gömülü: internetsiz
                        self.bridge.progress.emit(m, -1, "paketten kuruluyor…")
                        sysinfo.import_bundled(m)
                    else:
                        sysinfo.pull(m, url, lambda pct, status, m=m: self.bridge.progress.emit(m, pct, status),
                                     self._cancel.is_set)
                    self.bridge.done.emit(m, "")
                except Exception as e:  # noqa: BLE001 — hata metni kullanıcıya gösterilir
                    self.bridge.done.emit(m, str(e))
                    if self._cancel.is_set():
                        return
            self.bridge.done.emit("", "")

        threading.Thread(target=work, daemon=True).start()

    def _on_progress(self, model: str, pct: int, status: str):
        if pct >= 0:
            self.bars[model].setValue(pct)
        self.pull_status.setText(f"{model}: {status} {pct}%" if pct >= 0 else f"{model}: {status}")

    def _on_done(self, model: str, error: str):
        if model:
            if error:
                self.pull_status.setText(f"{model} indirilemedi: {error[:120]}")
            else:
                self.bars[model].setValue(100)
                self.checks[model].setEnabled(False)
                self.checks[model].setText(self.checks[model].text() + "   ·   kuruldu ✓")
            return
        self.pulling = False
        self.next_btn.setEnabled(True)
        if not self.pull_status.text().count("indirilemedi"):
            self.pull_status.setText("indirme bitti ✓")

    # ---- 4: bitiş
    def _page_done(self) -> QWidget:
        page = QWidget()
        col = QVBoxLayout(page)
        col.addWidget(self._title("Hazırsın."))
        col.addSpacing(8)
        col.addWidget(self._text(
            "Modelleri program kendisi seçer; sen yalnızca ne istediğini yaz. İstersen üstteki menülerden "
            "varsayılanları değiştirebilirsin:<br><br>"
            f"<b style='color:{C['accent']}'>Online</b> &nbsp;bulut modelleri — bugünün en iyi 10'u ve uzmanlığa göre "
            "(ajan, kod, görme, belge, arama, ücretsiz)<br>"
            f"<b style='color:{C['accent']}'>Offline</b> &nbsp;yerel modeller — sistemine göre en iyi 10 ve uzmanlığa göre "
            "(sohbet, kod, düşünme, görme, belge okuma)<br>Listeler her gün internetten güncellenir.<br><br>"
            "API'ler sekmesindeki <b>hazır API'ler</b> ile hava durumu, döviz, haberler gibi servisleri "
            "tek tıkla ekleyebilirsin. Bu sihirbaza Yardım menüsünden yeniden ulaşabilirsin."))
        col.addStretch()
        return page

    def _finish(self):
        s = self.settings
        s.auto_model = True
        installed = set(self.info.ollama_models) if self.info else set()
        installed |= {m for m, c in getattr(self, "checks", {}).items() if not c.isEnabled() or c.text().endswith("✓")}
        for chat in getattr(self, "chat_models", []):  # sisteme uygun sohbet modeli, yoksa temel model
            if chat in installed:
                s.ollama_model = chat
                break
        s.extra["kurulum"] = True
        s.save()
        Path(s.workspace).mkdir(parents=True, exist_ok=True)
        self.accept()

    def reject(self):
        if self.pulling:
            self._cancel.set()
        self.settings.extra["kurulum"] = True  # atlandı: bir daha kendiliğinden açılmasın
        self.settings.save()
        super().reject()
