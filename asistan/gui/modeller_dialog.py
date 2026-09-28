"""Modeller penceresi (K7): `ayar/modeller.json` kademe listeleri, bu bilgisayardaki ölçümler (tok/sn, ilk token,
doğrulayıcı başarı oranı), "Varsayılan yap" (kullanıcı katmanı `DATA_DIR/modeller.json`) ve "Listeyi yenile"
(günlük model listesi + önerilen 5 yerel + 5 bulut). Ölçüm ve karar çekirdekte (`cekirdek/analiz/olcum.py`,
`cekirdek/modeller.py`); pencere yalnızca gösterir ve kullanıcı katmanını yazar."""

from PySide6.QtCore import QObject, Signal
from PySide6.QtWidgets import (
    QDialog, QHBoxLayout, QHeaderView, QLabel, QPushButton, QTableWidget, QTableWidgetItem, QVBoxLayout,
)

from ..cekirdek import modeller, profil
from ..cekirdek.analiz import olcum
from .sidebar import run_in_background
from .theme import C

SUTUNLAR = ["Kademe", "Tür", "Sıra", "Model", "tok/sn", "İlk token", "Başarı", "Kurulu"]


class _Kopru(QObject):
    bitti = Signal(str)


def onerilen_liste(live: dict | None, kurulu: list[str]) -> dict:
    """Günlük listeden 5 yerel + 5 bulut öneri (CLAUDE.md haftalık liste): yerel = kütüphane puanı + kurulu olanlar
    önce; bulut = LMArena metin sıralaması. Kademe listelerini DEĞİŞTİRMEZ; `onerilen` olarak yazılır."""
    from .. import model_updates

    live = live or {}
    kutuphane = live.get("library") or {}
    yerel = sorted(kutuphane, key=lambda ad: (ad.split(":")[0] not in {k.split(":")[0] for k in kurulu},
                                              -float((kutuphane[ad][2] if len(kutuphane[ad]) > 2 else 0) or 0)))
    bulut = [r.get("model") or r.get("name") or "" for r in model_updates.arena_ranked(live, "text", 5)]
    return {"yerel": [y for y in yerel if y][:5], "bulut": [b for b in bulut if b][:5]}


class ModellerDialog(QDialog):
    def __init__(self, settings, parent=None):
        super().__init__(parent)
        self.settings = settings
        self.setWindowTitle("Modeller")
        self.setMinimumSize(900, 480)
        self.kopru = _Kopru()
        self.kopru.bitti.connect(self._yenilendi)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(20, 16, 20, 14)
        intro = QLabel("Kademe başına model listesi <code>ayar/modeller.json</code>'dan; ilk ad o kademenin varsayılanı. "
                       "Hız bu bilgisayarda ölçülmüştür (profil benchmark), başarı görev doğrulayıcısının saydığıdır. "
                       "<b>Varsayılan yap</b> seçimi kullanıcı katmanına yazar (güncellemeler ezmez).", objectName="hint")
        intro.setWordWrap(True)
        lay.addWidget(intro)
        self.table = QTableWidget(0, len(SUTUNLAR))
        self.table.setHorizontalHeaderLabels(SUTUNLAR)
        self.table.verticalHeader().setVisible(False)
        self.table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.table.setSelectionBehavior(QTableWidget.SelectRows)
        self.table.setSelectionMode(QTableWidget.SingleSelection)
        for i in range(len(SUTUNLAR) - 1):
            self.table.horizontalHeader().setSectionResizeMode(i, QHeaderView.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(len(SUTUNLAR) - 1, QHeaderView.Stretch)
        lay.addWidget(self.table, 1)
        self.oneri = QLabel(objectName="hint")
        self.oneri.setWordWrap(True)
        lay.addWidget(self.oneri)
        row = QHBoxLayout()
        self.status = QLabel(objectName="hint")
        row.addWidget(self.status, 1)
        self.default_btn = QPushButton("Varsayılan yap", objectName="smallButton",
                                       toolTip="Seçili modeli kademesinin listesinde başa alır")
        self.default_btn.clicked.connect(self._varsayilan_yap)
        self.refresh_btn = QPushButton("Listeyi yenile", objectName="smallButton",
                                       toolTip="Günlük model listesini indirir, 5 yerel + 5 bulut öneri çıkarır")
        self.refresh_btn.clicked.connect(self._yenile)
        row.addWidget(self.default_btn)
        row.addWidget(self.refresh_btn)
        lay.addLayout(row)
        self.satirlar: list[tuple[str, str, str]] = []  # (kademe, tür, model)
        self._doldur()

    def _kurulu(self) -> set[str]:
        return set(((profil.yukle() or {}).get("ollama") or {}).get("modeller") or [])

    def _doldur(self):
        self.table.setRowCount(0)
        self.satirlar = []
        kurulu = self._kurulu()
        etkin = profil.kademe()
        for kademe in modeller.KADEMELER:
            liste = modeller.kademe_modelleri(kademe)
            for tur in ("yerel", "bulut"):
                for sira, model in enumerate(liste[tur], 1):
                    oz = olcum.model_ozeti("ollama" if tur == "yerel" else "bulut", model)
                    r = self.table.rowCount()
                    self.table.insertRow(r)
                    degerler = [profil.ADLAR.get(kademe, kademe) + (" ◀" if kademe == etkin else ""), tur,
                                "varsayılan" if sira == 1 else str(sira), model,
                                f"{oz['tok_sn']:.0f}" if oz["tok_sn"] else "—",
                                f"{oz['ilk_token_ms']} ms" if oz["ilk_token_ms"] else "—",
                                f"%{100 * oz['basari']:.0f} ({oz['toplam']})" if oz["basari"] is not None else "—",
                                ("✓" if model in kurulu else "") if tur == "yerel" else "bulut"]
                    for c, v in enumerate(degerler):
                        item = QTableWidgetItem(v)
                        if sira == 1:
                            item.setForeground(_renk(C["accent"]))
                        self.table.setItem(r, c, item)
                    self.satirlar.append((kademe, tur, model))
        on = modeller.deger("onerilen") or {}
        self.oneri.setText("Önerilen (listeyi yenile): yerel " + (", ".join(on.get("yerel") or []) or "—")
                           + " · bulut " + (", ".join(on.get("bulut") or []) or "—")
                           + f" · liste tarihi {modeller.deger('guncelleme', '?')}")

    def _varsayilan_yap(self):
        r = self.table.currentRow()
        if r < 0 or r >= len(self.satirlar):
            self.status.setText("Önce bir satır seç.")
            return
        kademe, tur, model = self.satirlar[r]
        modeller.varsayilan_yap(kademe, model, yerel=tur == "yerel")
        self.status.setText(f"{model} → {profil.ADLAR.get(kademe, kademe)} kademesinin varsayılan {tur} modeli")
        self._doldur()

    def _yenile(self):
        self.refresh_btn.setEnabled(False)
        self.status.setText("Günlük model listesi indiriliyor…")

        def work():
            from .. import model_updates

            live = model_updates.refresh(force=True) or model_updates.load()
            on = onerilen_liste(live, sorted(self._kurulu()))
            modeller.ust_yaz({"onerilen": on, "guncelleme": __import__("datetime").date.today().isoformat()})
            return on

        def done(on, err):
            self.kopru.bitti.emit(f"hata: {err}" if err else "yenilendi")

        run_in_background(work, done, self)

    def _yenilendi(self, metin: str):
        self.refresh_btn.setEnabled(True)
        self.status.setText("Liste güncellenemedi: " + metin[6:] if metin.startswith("hata") else "Liste yenilendi.")
        self._doldur()


def _renk(hex_color: str):
    from PySide6.QtGui import QColor

    return QColor(hex_color)
