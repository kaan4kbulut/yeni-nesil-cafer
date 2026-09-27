"""Görevler penceresi (K4): görev motorunun görevleri — liste, adım durumu, yeni görev, Devam / Onayla / Reddet / İptal.

Sağ panele dördüncü sekme açılmaz (CLAUDE.md: sağ panel üç sekme; SORULAR K4/K5/K7): ayrı pencere, Yardım → Görevler.
Görev ayrı bir iş parçacığında koşar; pencere durumu görev deposundan (`gorevler.db`) saniyede bir okur. Motorun
kendi onay kuralı yok: onay bekleyen adımı buradaki "Onayla" düğmesi sürdürür, araç yine izin hattından geçer.
"""

import html
import threading

from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import (
    QCheckBox, QDialog, QHBoxLayout, QLabel, QLineEdit, QListWidget, QListWidgetItem, QPushButton, QSplitter,
    QTextBrowser, QVBoxLayout, QWidget,
)

from ..cekirdek.gorev import durum as gorev_durum
from ..cekirdek.gorev.komut import ISARET
from .theme import C

DURUM_ADI = {"planlandi": "planlandı", "calisiyor": "çalışıyor", "bekliyor_onay": "onay bekliyor",
             "bekliyor_kullanici": "cevabını bekliyor", "tamamlandi": "tamamlandı", "basarisiz": "yapılamadı",
             "iptal": "iptal"}


class GorevlerDialog(QDialog):
    def __init__(self, settings, connections=None, parent=None):
        super().__init__(parent)
        self.settings, self.connections = settings, connections
        self.setWindowTitle("Görevler")
        self.setMinimumSize(900, 520)
        self._thread: threading.Thread | None = None
        self._stop = threading.Event()
        self._error = ""
        self._last_state = None
        self._cancel_id = ""  # çalışırken iptal edilen görev: iş parçacığı bitince iptal yeniden yazılır

        lay = QVBoxLayout(self)
        lay.setContentsMargins(20, 16, 20, 14)
        intro = QLabel(
            "Çok adımlı işler burada plan olarak görünür ve adım adım koşar; her adımdan sonra kaydedilir, program "
            "kapanıp açılınca <b>Devam</b> ile kaldığı yerden sürer. Onay gereken adımda görev durur: "
            "<b>Onayla</b> dersen o adım (yine güvenlik kurallarından geçerek) yapılır.", objectName="hint")
        intro.setWordWrap(True)
        lay.addWidget(intro)

        new_row = QHBoxLayout()
        self.request = QLineEdit(placeholderText="Yeni görev: ör. Çalışma klasöründeki .txt dosyalarını say, "
                                                 "en büyüğünü özetle")
        self.request.returnPressed.connect(self._start_new)
        self.start_btn = QPushButton("Başlat", objectName="smallButton")
        self.start_btn.clicked.connect(self._start_new)
        new_row.addWidget(self.request, 1)
        new_row.addWidget(self.start_btn)
        lay.addLayout(new_row)

        split = QSplitter(Qt.Horizontal)
        left = QVBoxLayout()
        left_box = QWidget()
        left_box.setLayout(left)
        left.setContentsMargins(0, 0, 0, 0)
        self.only_open = QCheckBox("Yalnızca yarım görevler")
        self.only_open.toggled.connect(lambda _=False: self._refresh(True))
        left.addWidget(self.only_open)
        self.list = QListWidget()
        self.list.currentItemChanged.connect(lambda *_: self._show())
        left.addWidget(self.list, 1)
        split.addWidget(left_box)
        self.detail = QTextBrowser()
        self.detail.setOpenExternalLinks(False)
        split.addWidget(self.detail)
        split.setSizes([330, 570])
        lay.addWidget(split, 1)

        row = QHBoxLayout()
        self.status = QLabel(objectName="hint")
        row.addWidget(self.status, 1)
        self.continue_btn = QPushButton("Devam", objectName="smallButton", toolTip="Kaldığı adımdan sürdür")
        self.approve_btn = QPushButton("Onayla", objectName="smallButton", toolTip="Onay bekleyen adımı yap")
        self.reject_btn = QPushButton("Reddet", objectName="smallButton", toolTip="Adımı yapma, görevi durdur")
        self.cancel_btn = QPushButton("İptal", objectName="smallButton",
                                      toolTip="Görevi iptal et (kayıt silinmez); çalışıyorsa durdurur")
        self.continue_btn.clicked.connect(lambda: self._run_selected("devam"))
        self.approve_btn.clicked.connect(lambda: self._run_selected("onayla"))
        self.reject_btn.clicked.connect(lambda: self._run_selected("reddet"))
        self.cancel_btn.clicked.connect(self._cancel)
        for b in (self.continue_btn, self.approve_btn, self.reject_btn, self.cancel_btn):
            row.addWidget(b)
        lay.addLayout(row)

        self.timer = QTimer(self)
        self.timer.setInterval(1000)
        self.timer.timeout.connect(self._tick)
        self.timer.start()
        self._refresh(True)

    # ---- veri
    def _depo(self):
        return gorev_durum.depo()

    def _tasks(self) -> list[dict]:
        try:
            d = self._depo()
            return d.yarim() if self.only_open.isChecked() else d.listele(sinir=60)
        except Exception as e:  # depo açılamadı: pencere yine açılsın
            self.status.setText(f"Görev deposu okunamadı: {e}")
            return []

    def _selected(self) -> dict | None:
        item = self.list.currentItem()
        if item is None:
            return None
        return self._depo().getir(item.data(Qt.UserRole))

    @property
    def busy(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    # ---- görünüm
    def _refresh(self, force: bool = False) -> None:
        tasks = self._tasks()
        state = [(g["gorev_id"], g["durum"], g.get("checkpoint", {}).get("son_adim"),
                  tuple(a.get("durum") for a in g.get("adimlar") or [])) for g in tasks]
        if not force and state == self._last_state:
            return
        self._last_state = state
        current = self.list.currentItem().data(Qt.UserRole) if self.list.currentItem() else None
        self.list.blockSignals(True)
        self.list.clear()
        for g in tasks:
            item = QListWidgetItem(f"{ISARET.get(g['durum'], '?')}  {g['istek'][:60]}\n"
                                   f"    {DURUM_ADI.get(g['durum'], g['durum'])} · {g.get('olusturma', '')[:16]}")
            item.setData(Qt.UserRole, g["gorev_id"])
            self.list.addItem(item)
            if g["gorev_id"] == current:
                self.list.setCurrentItem(item)
        if self.list.currentItem() is None and self.list.count():
            self.list.setCurrentRow(0)
        self.list.blockSignals(False)
        self._show()

    def _show(self) -> None:
        g = self._selected()
        self._buttons(g)
        if g is None:
            self.detail.setHtml(f"<p style='color:{C['muted']}'>Görev yok. Üstteki kutuya bir iş yaz.</p>")
            return
        parts = [f"<h3>{html.escape(g['istek'])}</h3>",
                 f"<p><b>{DURUM_ADI.get(g['durum'], g['durum'])}</b> · {html.escape(g['gorev_id'])}</p>"]
        niyet = (g.get("anlayis") or {}).get("niyet")
        if niyet:
            parts.append(f"<p style='color:{C['muted']}'>Niyet: {html.escape(niyet)}</p>")
        if g["durum"] == "bekliyor_kullanici" and g.get("rapor"):
            parts.append(f"<p><b>Soru:</b> {html.escape(g['rapor'])}<br>Cevabını üstteki kutuya yazıp Başlat'a "
                         "bas: görev cevapla sürer.</p>")
        parts.append("<ol>")
        for a in g.get("adimlar") or []:
            renk = {"tamamlandi": C["success"], "basarisiz": C["error"]}.get(a["durum"], C["text"])
            model = (a.get("secim") or {}).get("model")
            ek = []
            if a.get("onay_gerekli"):
                ek.append("onay gerekli")
            if model:
                ek.append(html.escape(str(model)))
            parts.append(f"<li><span style='color:{renk}'>{ISARET.get(a['durum'], '?')} "
                         f"{html.escape(a['amac'])}</span> <small>· {html.escape(a['yetenek'])}"
                         f"{' · ' + ' · '.join(ek) if ek else ''}</small>")
            if a["durum"] == "bekliyor_onay":
                parts.append(f"<br><small>Yapılacak: <code>{html.escape(str(a.get('girdi'))[:400])}</code></small>")
            ozet = a.get("sonuc_ozeti") or a.get("not")
            if ozet:
                parts.append(f"<br><small style='color:{C['muted']}'>{html.escape(ozet[:300])}</small>")
            parts.append("</li>")
        parts.append("</ol>")
        if g["durum"] in ("tamamlandi", "basarisiz", "iptal") and g.get("rapor"):
            parts.append(f"<pre>{html.escape(g['rapor'])}</pre>")
        son = next((a for a in reversed(g.get("adimlar") or []) if a["durum"] == "tamamlandi"), None)
        if g["durum"] == "tamamlandi" and son and son.get("sonuc"):
            parts.append(f"<h4>Sonuç</h4><pre>{html.escape(son['sonuc'][:4000])}</pre>")
        self.detail.setHtml("".join(parts))

    def _buttons(self, g: dict | None) -> None:
        d = (g or {}).get("durum")
        busy = self.busy
        self.start_btn.setEnabled(not busy)
        self.continue_btn.setEnabled(not busy and d in ("planlandi", "calisiyor"))
        self.approve_btn.setEnabled(not busy and d == "bekliyor_onay")
        self.reject_btn.setEnabled(not busy and d == "bekliyor_onay")
        self.cancel_btn.setEnabled(g is not None and d not in gorev_durum.BITMIS)
        if busy:
            self.status.setText("Görev çalışıyor…")
        elif self._error:
            self.status.setText(self._error)

    def _tick(self) -> None:
        was = getattr(self, "_was_busy", False)
        now = self.busy
        self._was_busy = now
        if now or was:
            self._refresh(force=was and not now)

    # ---- işlemler
    def _motor(self, istek: str = "", gorev_id: str = ""):
        from ..cekirdek.gorev.komut import motor_kur

        return motor_kur(self.settings, self.connections, istek=istek, gorev_id=gorev_id,
                         iptal=self._stop.is_set, kaynak="komut")

    def _launch(self, work) -> None:
        self._stop.clear()
        self._error, self._cancel_id = "", ""

        def run():
            try:
                work()
            except Exception as e:  # noqa: BLE001 — iptal (Iptal) dahil: görev yarım kalır, kayıtta durur
                if type(e).__name__ != "Iptal":
                    self._error = f"Görev durdu: {type(e).__name__}: {e}"[:300]
            finally:
                if self._cancel_id:  # motor son adımı kaydederken iptali ezmiş olabilir
                    self._depo().iptal_et(self._cancel_id)

        self._thread = threading.Thread(target=run, daemon=True)
        self._thread.start()
        self._buttons(self._selected())

    def _start_new(self) -> None:
        text = self.request.text().strip()
        if not text or self.busy:
            return
        g = self._selected()
        self.request.clear()
        if g is not None and g["durum"] == "bekliyor_kullanici":  # motorun sorusuna cevap
            gid = g["gorev_id"]
            self._launch(lambda: self._motor(gorev_id=gid).yanitla(gid, text))
            return
        gid = gorev_durum.yeni_id()
        self._launch(lambda: self._motor(istek=text, gorev_id=gid).baslat(text, gorev_id=gid))
        QTimer.singleShot(1500, lambda: self._refresh(True))

    def _run_selected(self, action: str) -> None:
        g = self._selected()
        if g is None or self.busy:
            return
        gid = g["gorev_id"]
        if action == "devam":
            self._launch(lambda: self._motor(gorev_id=gid).devam(gid))
        else:
            self._launch(lambda: self._motor(gorev_id=gid).onayla(gid, action == "onayla"))

    def _cancel(self) -> None:
        g = self._selected()
        if g is None:
            return
        if self.busy:
            self._cancel_id = g["gorev_id"]
            self._stop.set()  # adım sınırında durur; iş parçacığı bitince iptal yeniden yazılır
        self._depo().iptal_et(g["gorev_id"])
        self._refresh(True)

    def closeEvent(self, event):
        self.timer.stop()
        self._stop.set()  # çalışan görev adım sınırında durur, yarım olarak kalır ("Devam" ile sürer)
        super().closeEvent(event)
