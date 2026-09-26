"""Tanıtım: ilk kurulumda ve her yeni sürümde o sürümün öne çıkan özellikleri bir kez gösterilir.

Görüldüğü `Settings.extra["tanitim_surumu"]` ile hatırlanır. Her madde, özelliğe götüren bir düğmeyle gelir
(ör. canlı görüntü bölümünü gösterir); kullanıcı hiçbirini denemek zorunda değildir.
"""

import re

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QDialog, QFrame, QHBoxLayout, QLabel, QPushButton, QVBoxLayout

from .. import __version__
from .theme import C

# sürüm → (başlık, açıklama, düğme yazısı, pencerede yapılacak iş: MainWindow metodu adı ya da "")
NEWS = {
    "2.3": [
        ("Sağ panel üç bölüm", "Adımlar, dosyalar ve canlı görüntü artık alt alta, hepsi aynı anda görünür: resim, "
         "video ya da 3D model hazırlanırken sonucu sekme değiştirmeden izlersin. Bölümleri aradaki çizgiyle "
         "büyütebilirsin.", "göster", "_tour_media"),
    ],
    "2.2": [
        ("İşleri kendi başına çözer", "Bilmediği bir işi araştırır, gereken kütüphaneyi ya da uygulamayı kurar "
         "(onayınla), yapar ve sonucu gözle kontrol eder. Bulduğu yolu tarif olarak kaydeder; bir dahaki sefere "
         "doğrudan bilir. Sonucu belirleyen bir bilgi eksikse önce sorar.", "", ""),
        ("Canlı görüntü", "Sağ panelde: resim üretilirken her adımı canlı izle; resim, video ve 3D modelleri "
         "(döndürerek, ölçüleriyle) önizle.", "göster", "_tour_media"),
        ("Konuşarak yaz", "Mesaj kutusundaki 🎤 ya da Ctrl+Shift+Space: konuş, tekrar bas; yazıya çevrilip kutuya "
         "eklenir. Tamamen bilgisayarında çalışır.", "dene", "_toggle_dictation"),
        ("3D yazıcı için parça", "\"40x20x10 mm, ortasında 5 mm delik olan bir blok yap\" gibi iste: ölçülü STL/3MF "
         "hazırlanır, baskıya uygunluğu denetlenir.", "", ""),
        ("Tarifler", "Asistanın öğrendiği ve programla gelen iş tarifleri: Yardım → Hafıza ve öğrenme → Tarifler. "
         "Görebilir, düzeltebilir, silebilirsin.", "aç", "open_learning"),
        ("Sorun bildir", "Bir şey ters giderse sohbette \"🐞 Sorunu raporla\" çıkar ya da Yardım → Sorun bildir. "
         "Geliştiriciye verilecek rapor hazırlanır; kaydetmeden önce içeriğini görürsün.", "", ""),
    ],
}


def pending(settings) -> list[tuple[str, str, str, str]]:
    """Gösterilecek maddeler: son görülen sürümden sonraki bütün sürümlerin yenilikleri (yenisi önce)."""
    seen = _key((settings.extra or {}).get("tanitim_surumu") or "0")
    return [item for v in sorted(NEWS, key=_key, reverse=True) if seen < _key(v) <= _key(__version__)
            for item in NEWS[v]]


def _key(version: str) -> tuple:
    return tuple(int(x) for x in re.findall(r"\d+", str(version)))


def mark_seen(settings) -> None:
    settings.extra = {**(settings.extra or {}), "tanitim_surumu": __version__}
    settings.save()


class TourDialog(QDialog):
    def __init__(self, items: list, run, parent=None):
        """run(metod_adı): düğmeye basılınca pencere kapanır ve ilgili özellik açılır."""
        super().__init__(parent)
        self.setWindowTitle(f"YENİ NESİL CAFER {__version__} — neler yeni")
        self.setMinimumWidth(680)
        lay = QVBoxLayout(self)
        lay.setSpacing(10)
        title = QLabel(f"<b>YENİ NESİL CAFER {__version__}</b>")
        title.setStyleSheet("font-size: 17px;")
        lay.addWidget(title)
        for head, text, button, action in items:
            box = QFrame(objectName="tourItem")
            box.setStyleSheet(f"#tourItem {{ border: 1px solid {C['frame']}; border-radius: 8px; }}"
                              " #tourItem QLabel { background: transparent; }")
            row = QHBoxLayout(box)
            row.setContentsMargins(12, 8, 12, 8)
            label = QLabel(f"<b>{head}</b><br>{text}")
            label.setWordWrap(True)
            label.setTextFormat(Qt.RichText)
            label.setMinimumWidth(500)
            label.setMinimumHeight(label.heightForWidth(500) + 4)  # boy, satırlar sarılmadan hesaplanıyor: kesilmesin
            row.addWidget(label, 1)
            if button and action:
                b = QPushButton(button, objectName="smallButton")
                b.setCursor(Qt.PointingHandCursor)
                b.clicked.connect(lambda _=False, a=action: (self.accept(), run(a)))
                row.addWidget(b, 0, Qt.AlignVCenter)
            lay.addWidget(box)
        ok = QPushButton("Başlayalım", objectName="primary")
        ok.clicked.connect(self.accept)
        lay.addWidget(ok, 0, Qt.AlignRight)
