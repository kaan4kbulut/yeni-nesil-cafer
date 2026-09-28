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
    "3.1": [
        ("Yazdı ama yapmadı, bitti", "Model bir işi araç çalıştırmadan yalnızca anlatırsa bir kez uyarılır; yine "
         "yapmazsa iş görev motoruna ya da daha güçlü bir modele devredilir, o da yoksa tek satırla dürüstçe söylenir. "
         "Uyarı metinleri sohbette değil sağ paneldeki durum satırında görünür.", "", ""),
        ("Sorular ve 🐞 sorun düğmesi", "Model sonucu belirleyen bir şeyi soracaksa tek soru sorar, sohbet «cevap "
         "bekliyor» olur. Mesaj kutusunun yanındaki 🐞 sorun düğmesi tek tıkla rapor hazırlar; geliştiriciye verilecek "
         "cümle panoya kopyalanır.", "raporla", "_quick_report"),
        ("50'den fazla düzeltme", "Güvenlik, onay, sandbox, ayar ve donma sorunları giderildi; bağlam boyutu ekran "
         "kartının boş belleğine göre seçilir (14B model 12 GB kartta işlemciye taşmaz).", "", ""),
    ],
    "3.0": [
        ("Görev motoru", "Çok adımlı işleri anla → planla → uygula → doğrula adımlarıyla yapar; program kapansa "
         "da «devam et» ile kaldığı yerden sürer. Değişiklik yapan her adım onay bekler; yapamadığı işi sınıflandırır, "
         "eksik paketi (onayınla) kurar ya da yeni bir yetenek üretir.", "aç", "open_tasks"),
        ("Yetenekler ve Modeller", "Yardım → Yetenekler: motorun kullandığı her yetenek, izinleri ve durumu. "
         "Yardım → Gelişmiş → Modeller: kademe başına model listesi, bu bilgisayardaki hız ve başarı ölçümleri. "
         "Kademe (düşük/orta/yüksek) hıza göre kendini ayarlar; düşük kademede arayüz sadedir.", "aç", "open_capabilities"),
        ("Telefondan ve sunucudan", "Aynı program bir sunucuda çalışır (docs/SUNUCU_KURULUM.md): telefonda PWA ile "
         "sohbet, görevler, onaylar; bilgisayar kapalıyken görevler sunucuda sürer, açılınca burada görünür. "
         "Onay bekleyen görevler için ntfy/Telegram bildirimi.", "", ""),
    ],
    "2.6": [
        ("Sonuçlar tek yerde", "Asistanın ürettiği resimler, 3D modeller, belgeler ve kodlar masaüstündeki "
         "YENİ NESİL CAFER/Sonuçlar klasöründe konu konu toplanır (Sohbet → Sonuçlar klasörü). Asıl dosyalar çalışma "
         "klasöründe kalır; Ayarlar'dan kapatabilirsin.", "aç", "_open_results"),
    ],
    "2.5": [
        ("Resimden gerçek 3D figür", "Hayvan, karakter ya da biblo figürü iste: asistan önce resmini üretir (ya da "
         "senin fotoğrafını kullanır), sonra 3D yazıcıda basılacak hacimli, ayaklı bir figüre çevirir. Motoru bir kez "
         "kurman gerekir (~1,7 GB).", "kur", "_figure_setup"),
    ],
    "2.4": [
        ("3D yazıcı için süsler", "\"3D yazıcım için burgulu bir vazo yap\", \"girdaplı gece lambası\", \"yılbaşı süs "
         "topu\", \"oturan kedi figürü\" gibi iste: vazo, abajur, lamba, süs topu, yıldız, kafes küre, resimden "
         "kabartma ve litofan, siluet figür baskıya hazır STL/3MF olarak hazırlanır ve burada döndürüp incelenir.",
         "göster", "_tour_media"),
    ],
    "2.3": [
        ("Canlı önizleme", "Resim, video ya da 3D model hazırlanırken sağ panelde adımların altında canlı "
         "önizleme açılır; görsel iş yokken yer kaplamaz. Adımlar iş sürerken kendiliğinden aşağı kayar.", "göster", "_tour_media"),
    ],
    "2.2": [
        ("İşleri kendi başına çözer", "Bilmediği bir işi araştırır, gereken kütüphaneyi ya da uygulamayı kurar "
         "(onayınla), yapar ve sonucu gözle kontrol eder. Bulduğu yolu tarif olarak kaydeder; bir dahaki sefere "
         "doğrudan bilir. Sonucu belirleyen bir bilgi eksikse önce sorar.", "", ""),
        ("Görsel önizleme", "Sağ panelde: resim üretilirken her adımı canlı izle; resim, video ve 3D modelleri "
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
