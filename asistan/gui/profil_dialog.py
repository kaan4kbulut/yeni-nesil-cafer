"""Donanım profili penceresi: durum çubuğundaki kademe düğmesi açar. Özet, bu kademede kapalı özellikler, kilit.

Ölçüm ve kademe kararı çekirdekte (`cekirdek/profil.py`); pencere yalnızca gösterir ve kilidi yazar.
"""

from PySide6.QtWidgets import (QCheckBox, QComboBox, QDialog, QHBoxLayout, QLabel, QMessageBox, QPlainTextEdit,
                               QPushButton, QVBoxLayout)

from .. import sysinfo
from ..cekirdek import donanim, profil
from ..cekirdek.analiz import olcum
from .sidebar import run_in_background
from .theme import mono


class ProfileDialog(QDialog):
    def __init__(self, parent=None, on_change=None, ayarlar=None):
        self.ayarlar = ayarlar  # ana pencerenin Settings nesnesi (K12-C2)
        super().__init__(parent)
        self.on_change = on_change  # kademe değişince ana pencere durum çubuğunu yeniler
        self.setWindowTitle("Donanım profili ve kademe")
        self.setMinimumSize(640, 460)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(20, 16, 20, 14)
        intro = QLabel(
            "Program açılışta bu bilgisayarı ölçer ve bir <b>kademe</b> seçer: düşük · orta · yüksek · sunucu. "
            "Kademe, hangi modellerin önerileceğini ve ağır özelliklerin (anlamca arama, tarayıcı otomasyonu, "
            "uzun bağlam) açık olup olmadığını belirler. Ölçüm yanlışsa kademeyi elle kilitleyebilirsin; kilit "
            "ölçümü ezer.", objectName="hint")
        intro.setWordWrap(True)
        lay.addWidget(intro)
        self.text = QPlainTextEdit(readOnly=True)
        self.text.setFont(mono(10))
        lay.addWidget(self.text, 1)
        # K13: güç/donanım farkındalığı (Donanım bölümü)
        lay.addWidget(QLabel("<b>Donanım</b> — fiş/pil, ekran kartı, Ollama'nın cihazı", objectName="hint"))
        self.hw_text = QPlainTextEdit(readOnly=True)
        self.hw_text.setFont(mono(10))
        self.hw_text.setMaximumHeight(150)
        lay.addWidget(self.hw_text)
        hw_row = QHBoxLayout()
        self.auto_hw = QCheckBox("Otomatik uyarla (pilde kademe/bağlam/cihaz)")
        self.auto_hw.setChecked(olcum.otomatik_uyarla_acik(self.ayarlar))
        self.auto_hw.toggled.connect(self._auto_hw_changed)
        hw_row.addWidget(self.auto_hw, 1)
        self.hw_measure = QPushButton("Şimdi ölç", objectName="smallButton")
        self.hw_measure.clicked.connect(self._hw_measure)
        hw_row.addWidget(self.hw_measure)
        self.hw_restart = QPushButton("Ollama'yı yeniden başlat", objectName="smallButton")
        self.hw_restart.clicked.connect(self._hw_restart)
        self.hw_restart.hide()
        hw_row.addWidget(self.hw_restart)
        lay.addLayout(hw_row)
        row = QHBoxLayout()
        row.addWidget(QLabel("Kademe:"))
        self.combo = QComboBox()
        self.combo.addItem("otomatik (ölçülen)", None)
        for k in profil.KADEMELER:
            self.combo.addItem(f"{profil.ADLAR[k]} — kilitli", k)
        row.addWidget(self.combo, 1)
        self.remeasure = QPushButton("Yeniden ölç", objectName="smallButton")
        row.addWidget(self.remeasure)
        close = QPushButton("Kapat", objectName="smallButton")
        row.addWidget(close)
        lay.addLayout(row)
        self.lock_hint = QLabel(objectName="hint")
        self.lock_hint.setWordWrap(True)
        lay.addWidget(self.lock_hint)
        self.combo.activated.connect(self._lock_changed)
        self.remeasure.clicked.connect(self._measure)
        close.clicked.connect(self.accept)
        self._show(profil.yukle())
        if profil.yukle() is None:
            self._measure()
        self._hw_refresh()

    def _show(self, p: dict | None):
        self.text.setPlainText(profil.ozet(p) if p else "Ölçülüyor…")
        locked = profil.kilit()
        self.combo.setCurrentIndex(self.combo.findData(locked) if locked else 0)
        from_file = profil.kilit_kaynagi() == "dosya"
        self.combo.setEnabled(not from_file)
        self.lock_hint.setText("Kademe ayar.toml (genel.kademe_kilidi) ya da CAFER_GENEL_KADEME_KILIDI ile "
                               "kilitli; buradan değiştirilemez." if from_file else "")

    def _measure(self):
        self.remeasure.setEnabled(False)
        self.text.setPlainText("Ölçülüyor…")

        def done(p, error):
            self.remeasure.setEnabled(True)
            if error is not None:
                self.text.setPlainText(f"Ölçülemedi: {error}")
                return
            self._show(p)
            if self.on_change:
                self.on_change()

        run_in_background(lambda: profil.guncelle(sunucu=False), done, self)

    def _lock_changed(self, _index: int):
        profil.kilitle(self.combo.currentData(), ayarlar=self.ayarlar)
        self._show(profil.yukle())
        if self.on_change:
            self.on_change()

    # ---- K13: Donanım bölümü (tüm ölçümler arka planda)
    def _hw_refresh(self):
        self.hw_text.setPlainText("Okunuyor…")

        def done(metin, error):
            self.hw_text.setPlainText(metin if error is None else f"Okunamadı: {error}")
            self.hw_restart.setVisible(bool((donanim.karar() or {}).get("oneri") == "ollama_yeniden_baslat"))
            self.hw_measure.setEnabled(True)

        run_in_background(olcum.donanim_ozeti, done, self)

    def _hw_measure(self):
        """Seçili modelin gpu ve cpu hızını arka planda ölçer (en çok 2 sonda), sonra kararı yeniler."""
        self.hw_measure.setEnabled(False)
        self.hw_text.setPlainText("Ölçülüyor… (birkaç on saniye sürebilir)")
        ayarlar = self.ayarlar

        def is_():
            model = getattr(ayarlar, "ollama_model", "")
            if model:
                olcum.sonda_kos([(model, "gpu"), (model, "cpu")], lambda: True, ayarlar.ollama_url)
            olcum.uyarla(ayarlar)
            return olcum.donanim_ozeti()

        def done(metin, error):
            self.hw_text.setPlainText(metin if error is None else f"Ölçülemedi: {error}")
            self.hw_measure.setEnabled(True)
            if self.on_change:
                self.on_change()

        run_in_background(is_, done, self)

    def _auto_hw_changed(self, on: bool):
        if self.ayarlar is not None:
            self.ayarlar.extra = {**self.ayarlar.extra, "donanim_otomatik": bool(on)}
            self.ayarlar.save()
        run_in_background(lambda: (olcum.uyarla(self.ayarlar), olcum.donanim_ozeti())[1],
                          lambda m, e: (self.hw_text.setPlainText(m if e is None else str(e)),
                                        self.on_change() if self.on_change else None), self)

    def _hw_restart(self):
        """Onaylı yeniden başlatma; sonra ölçüm yinelenir (kart hâlâ görülmezse CPU)."""
        if QMessageBox.question(self, "Ollama'yı yeniden başlat",
                                "Ekran kartın sağlam görünüyor ama Ollama modeli işlemcide çalıştırıyor. "
                                "Ollama yeniden başlatılsın mı? (Yetki istenebilir; çalışan yanıtlar kesilir.)"
                                ) != QMessageBox.StandardButton.Yes:
            return
        self.hw_restart.setEnabled(False)
        self.hw_text.setPlainText("Ollama yeniden başlatılıyor…")

        def is_():
            ok, ileti = sysinfo.restart_ollama_service()
            if ok:
                olcum.ollama_yeniden_baslatildi()
                model = getattr(self.ayarlar, "ollama_model", "")
                if model:
                    olcum.hizli_sonda(model, "gpu", self.ayarlar.ollama_url)  # modeli kartla yükletir, ölçümü yineler
                donanim.gpu_envanteri(yenile=True)
                olcum.uyarla(self.ayarlar)
            return ileti + "\n" + olcum.donanim_ozeti()

        def done(metin, error):
            self.hw_restart.setEnabled(True)
            self.hw_text.setPlainText(metin if error is None else f"Yeniden başlatılamadı: {error}")
            self.hw_restart.setVisible(bool((donanim.karar() or {}).get("oneri") == "ollama_yeniden_baslat"))
            if self.on_change:
                self.on_change()

        run_in_background(is_, done, self)
