"""Arayüz denetimi: programdaki her düğmeye, menü seçeneğine ve sağ tık menüsüne basar; hataları kaydeder.

2026-09-26'da kullanıcının "her buton ve işlevi kontrolden geçir" isteğiyle yazıldı (628 eylem). Kullanıcının
ayarlarının KOPYASIYLA ekransız çalışır: açılan pencereler, sorular (hep "Hayır"), tarayıcı/dosya açma, arka plan
işleri ve komutlar kaydedilir ama yapılmaz; gerçek ayarlara dokunulmaz. Unittest değildir (test_ ile başlamaz).

    ~/.local/share/yeni-nesil-cafer-app/python/bin/python3 testler/arayuz_denetimi.py
Çıktı: arayuz_denetimi.json (her eylem: yer, ad, olaylar, hatalar) ve tek satır özet.
Bilinen: PySide6'da QMenu.exec sınıftan değiştirilemez (aşırı yüklü) → modüllerdeki QMenu adı alt sınıfla değiştirilir.
"""
import faulthandler
import json
import os
import shutil
import sys
import tempfile
import time
import traceback
from pathlib import Path

KOK = Path(__file__).resolve().parent.parent
OUT = Path(tempfile.gettempdir()) / "arayuz_denetimi.json"
sys.path.insert(0, str(KOK))
GECICI = Path(tempfile.mkdtemp(prefix="ync-denetim-"))
os.environ["XDG_CONFIG_HOME"] = str(GECICI / "ayar")
os.environ["XDG_DATA_HOME"] = str(GECICI / "veri")
os.environ["QT_QPA_PLATFORM"] = "offscreen"
# gerçek ayarların ve küçük verilerin kopyası (büyük model/kütüphane klasörleri değil)
shutil.copytree(Path.home() / ".config/yeni-nesil-cafer", GECICI / "ayar/yeni-nesil-cafer")
veri = Path.home() / ".local/share/yeni-nesil-cafer"
(GECICI / "veri/yeni-nesil-cafer").mkdir(parents=True)
for ad in ("sohbetler", "hafiza.db", "gelisim.jsonl", "model-kartlari.json", "model_katalogu.json", "oneriler.json",
           "ogrenilen-beceriler"):
    src = veri / ad
    if src.is_dir():
        shutil.copytree(src, GECICI / "veri/yeni-nesil-cafer" / ad)
    elif src.exists():
        shutil.copy2(src, GECICI / "veri/yeni-nesil-cafer" / ad)

from PySide6.QtCore import QObject, Qt  # noqa: E402
from PySide6.QtGui import QDesktopServices  # noqa: E402
from PySide6.QtWidgets import (QAbstractButton, QApplication, QDialog, QFileDialog, QInputDialog,  # noqa: E402
                               QMenu, QMessageBox, QWidget)

APP = QApplication([])
faulthandler.dump_traceback_later(int(os.environ.get("DENETIM_DOKUM", "150")), repeat=True)
from asistan.gui.theme import apply_theme  # noqa: E402

apply_theme(APP)

olaylar: list = []  # o anki eylemde olanlar
hatalar: list = []


def kaydet(tur, ayrinti=""):
    olaylar.append(f"{tur}: {ayrinti}"[:300])


def excepthook(t, v, tb):
    metin = "".join(traceback.format_exception(t, v, tb))[-2500:]
    hatalar.append(metin)
    son = traceback.extract_tb(tb)
    if son and son[-1].filename.endswith("denetim.py"):
        print("DENETİM BETİĞİ HATASI:\n" + metin, flush=True)


sys.excepthook = excepthook

# ---- yan etkisiz sahteler
acilan_dialoglar: list = []


def sahte_exec(self, *a, **k):
    acilan_dialoglar.append(self)
    kaydet("pencere", f"{type(self).__name__} «{self.windowTitle()}»")
    return 0


QDialog.exec = sahte_exec
QDialog.exec_ = sahte_exec
for ad, donus in (("question", QMessageBox.No), ("warning", QMessageBox.Ok), ("information", QMessageBox.Ok),
                  ("critical", QMessageBox.Ok)):
    setattr(QMessageBox, ad, staticmethod(lambda *a, _ad=ad, _d=donus, **k: (kaydet("soru", f"{_ad}: " + " | ".join(
        str(x)[:120] for x in a[1:3])), _d)[1]))
QMessageBox.about = staticmethod(lambda *a, **k: kaydet("soru", "about"))
QMessageBox.exec = lambda self, *a, **k: (kaydet("soru", f"{self.windowTitle()} {self.text()[:120]}"), QMessageBox.No)[1]
QInputDialog.getText = staticmethod(lambda *a, **k: (kaydet("girdi", str(a[1:3])[:150]), ("", False))[1])
QInputDialog.getItem = staticmethod(lambda *a, **k: (kaydet("girdi", str(a[1:3])[:150]), ("", False))[1])
QInputDialog.getInt = staticmethod(lambda *a, **k: (kaydet("girdi", str(a[1:3])[:150]), (0, False))[1])
QInputDialog.getMultiLineText = staticmethod(lambda *a, **k: (kaydet("girdi", str(a[1:3])[:150]), ("", False))[1])
for ad in ("getOpenFileName", "getSaveFileName"):
    setattr(QFileDialog, ad, staticmethod(lambda *a, _ad=ad, **k: (kaydet("dosya", _ad), ("", ""))[1]))
QFileDialog.getOpenFileNames = staticmethod(lambda *a, **k: (kaydet("dosya", "getOpenFileNames"), ([], ""))[1])
QFileDialog.getExistingDirectory = staticmethod(lambda *a, **k: (kaydet("dosya", "getExistingDirectory"), "")[1])
QDesktopServices.openUrl = staticmethod(lambda url, *a: (kaydet("tarayıcı/dosya aç", url.toString()[:150]), True)[1])

import asistan.gui as gui_pkg  # noqa: E402
import pkgutil  # noqa: E402
import importlib  # noqa: E402

arka_plan: list = []


def sahte_arka_plan(fn, on_done, parent):
    ad = getattr(fn, "__qualname__", repr(fn))
    arka_plan.append((ad, fn, on_done))
    kaydet("arka plan işi", ad)


moduller = [importlib.import_module(f"asistan.gui.{m.name}") for m in pkgutil.iter_modules(gui_pkg.__path__)]
for m in moduller:
    if hasattr(m, "run_in_background"):
        m.run_in_background = sahte_arka_plan
    if hasattr(m, "open_folder"):
        m.open_folder = lambda p, *a, **k: kaydet("klasör aç", str(p))

import subprocess  # noqa: E402

_gercek_popen = subprocess.Popen


GUVENLI = {"nvidia-smi", "node", "lspci", "git", "which", "uname", "powershell"}


def _guvenli(cmd) -> bool:
    if not isinstance(cmd, (list, tuple)) or not cmd:
        return False
    ad, argv = Path(str(cmd[0])).name, [str(x) for x in cmd[1:]]
    if ad in GUVENLI:
        return True
    if ad == "ollama":
        return bool(argv) and argv[0] in ("list", "ps", "--version", "show")
    if ad in ("codex", "claude", "gemini") or ad.endswith("gemini.js"):
        return "--version" in argv or argv[:2] == ["login", "status"]
    return False


class SahtePopen:
    def __new__(cls, cmd, *a, **k):
        if _guvenli(cmd):
            return _gercek_popen(cmd, *a, **k)
        return super().__new__(cls)

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def __init__(self, cmd, *a, **k):
        kaydet("komut", " ".join(map(str, cmd))[:200] if isinstance(cmd, (list, tuple)) else str(cmd)[:200])
        self.returncode, self.pid, self.stdout, self.stderr, self.stdin = 0, 0, None, None, None
        self.args = cmd
        self._metin = bool(k.get("text") or k.get("universal_newlines") or k.get("encoding"))

    def poll(self):
        return 0

    def wait(self, *a, **k):
        return 0

    def communicate(self, *a, **k):
        return ("", "") if self._metin else (b"", b"")

    def kill(self):
        pass

    terminate = kill


from asistan.gui.window import MainWindow  # noqa: E402

t0 = time.time()
W = MainWindow()
W.resize(1500, 950)
W.show()
for _ in range(30):
    APP.processEvents()
    time.sleep(0.05)
_gercek_notify, _gercek_notice = W._notify, W.chat.add_notice
W._notify = lambda text, ms=8000: (kaydet("durum çubuğu", text), _gercek_notify(text, ms))[1]
W.chat.add_notice = lambda text, *a, **k: (kaydet("sohbet bildirimi", str(text)), _gercek_notice(text, *a, **k))[1]
acilis_hatalari = list(hatalar)
hatalar.clear()
subprocess.Popen = SahtePopen  # pencere açıldıktan sonra: düğmeler komut başlatmasın
W.close = lambda *a: kaydet("pencere kapat", "")  # "çık" düğmesi pencereyi kapatmasın
QApplication.quit = staticmethod(lambda: kaydet("programdan çık", ""))

sonuclar: list = []


def yer(w: QObject) -> str:
    zincir = []
    p = w.parent()
    while p is not None and len(zincir) < 5:
        ad = p.objectName() or type(p).__name__
        if ad not in ("QWidget", "QFrame", "QScrollArea", "QStackedWidget", "QSplitter"):
            zincir.append(ad)
        p = p.parent()
    return " < ".join(zincir)


def bagli_mi(obj, sinyaller=("clicked", "toggled", "pressed", "released", "triggered")) -> bool:
    mo = obj.metaObject()
    for i in range(mo.methodCount()):
        m = mo.method(i)
        if bytes(m.name()).decode() in sinyaller and obj.isSignalConnected(m):
            return True
    if isinstance(obj, QAbstractButton) and hasattr(obj, "menu") and obj.menu() is not None:
        return True
    return False


def dene(etiket: str, konum: str, eylem, bagli: bool):
    print(f"[{len(sonuclar)}] {konum} :: {etiket}", flush=True)
    olaylar.clear()
    hatalar.clear()
    once_pencereler = set(id(w) for w in APP.topLevelWidgets() if w.isVisible())
    t = time.time()
    try:
        eylem()
    except Exception:
        hatalar.append(traceback.format_exc()[-2500:])
    for _ in range(3):
        APP.processEvents()
    if not W.isVisible():
        kaydet("ANA PENCERE KAPANDI", "yeniden açıldı")
        W.show()
    yeni = [w for w in APP.topLevelWidgets() if w.isVisible() and id(w) not in once_pencereler and w is not W]
    for w in yeni:
        kaydet("açılan pencere", f"{type(w).__name__} «{w.windowTitle()}»")
        if isinstance(w, QMenu):
            w.hide()
        else:
            w.close()
    sonuclar.append({"etiket": etiket, "konum": konum, "bagli": bagli, "olaylar": list(olaylar),
                     "hatalar": list(hatalar), "sure": round(time.time() - t, 2)})


def ad_ver(b) -> str:
    t = (b.text() or "").replace("\n", " ").strip()
    return t or f"[{b.toolTip()[:60] or b.objectName() or type(b).__name__}]"


# ---- menüler: exec/popup engeller (ekransızda kilitlenir); yakalanan menü sonra gezilir
yakalanan_menuler: list = []


def menu_yakala(self, *a, **k):
    yakalanan_menuler.append(self)
    kaydet("menü", self.title() or f"{len(self.actions())} seçenek")
    return None


class SahteMenu(QMenu):  # PySide6'da QMenu.exec sınıf üzerinden değiştirilemiyor (aşırı yüklü): alt sınıf
    def exec(self, *a, **k):
        return menu_yakala(self)

    exec_ = exec

    def popup(self, *a, **k):
        return menu_yakala(self)


for _m in moduller:
    if getattr(_m, "QMenu", None) is QMenu:
        _m.QMenu = SahteMenu
denenen: set = set()
SINIR = int(os.environ.get("DENETIM_SINIR", "700"))


def menu_gez(m: QMenu, yol: str, derinlik=0):
    if derinlik > 4 or len(sonuclar) > SINIR:
        return
    try:
        m.aboutToShow.emit()
    except Exception:
        hatalar.append(traceback.format_exc()[-2500:])
    APP.processEvents()
    for a in list(m.actions())[:45]:
        try:
            metin = a.text().replace("&", "").replace("\n", " ").strip()
        except RuntimeError:
            continue
        if a.isSeparator() or not metin:
            continue
        alt = a.menu()
        if alt is not None:
            menu_gez(alt, f"{yol} › {metin}", derinlik + 1)
            continue
        anahtar = (yol, metin)
        if anahtar in denenen or not a.isEnabled():
            continue
        denenen.add(anahtar)
        if metin == "Çıkış":  # programı kapatır: denenmez
            continue
        if a.isCheckable():  # aç/kapa: iki kez (eski hâline döner)
            dene(metin, f"menü: {yol}", lambda a=a: (a.trigger(), APP.processEvents(), a.trigger()), bagli_mi(a))
        else:
            dene(metin, f"menü: {yol}", a.trigger, bagli_mi(a))


def menuleri_bosalt():
    while yakalanan_menuler:
        m = yakalanan_menuler.pop(0)
        try:
            menu_gez(m, m.title() or "menü")
        except RuntimeError:
            pass


def dugmeleri_gez(kok: QWidget, konum_on_ek=""):
    """Görünen, açık her düğmeye bir kez bas; arayüz değiştikçe yeni görünenleri de dene."""
    for tur in range(8):
        yeni = 0
        for b in kok.findChildren(QAbstractButton):
            try:
                if not b.isVisible() or not b.isEnabled():
                    continue
                anahtar = (ad_ver(b), yer(b))
            except RuntimeError:
                continue
            if anahtar in denenen:
                continue
            denenen.add(anahtar)
            yeni += 1
            try:
                menu = b.menu() if hasattr(b, "menu") else None
            except RuntimeError:
                continue
            if menu is not None:
                dene(anahtar[0], konum_on_ek + anahtar[1], lambda m=menu: menu_gez(m, ad_ver(b)), True)
            else:
                dene(anahtar[0], konum_on_ek + anahtar[1], b.click, bagli_mi(b))
            menuleri_bosalt()
            if len(sonuclar) > SINIR:
                return
        if not yeni:
            break


def pencereleri_gez():
    """Düğmelerin açtığı pencereler (exec engellendi): gösterip içindeki düğmelere bas."""
    gorulen = set()
    while acilan_dialoglar and len(sonuclar) <= SINIR:
        d = acilan_dialoglar.pop(0)
        try:
            ad = type(d).__name__ + "«" + d.windowTitle() + "»"
        except RuntimeError:
            continue
        if ad in gorulen:
            continue
        gorulen.add(ad)
        try:
            d.show()
            APP.processEvents()
            dugmeleri_gez(d, f"pencere {ad} < ")
            d.hide()
        except RuntimeError:
            pass


def menubar_gez():
    for a in W.menuBar().actions():
        if a.menu() is not None:
            menu_gez(a.menu(), "üst menü › " + a.text().replace("&", ""))


def sag_tik_menuleri():
    """Sağ tık menüsü olan listeler: ilk öğede sağ tık (customContextMenuRequested) → yakalanan menü gezilir."""
    from PySide6.QtWidgets import QAbstractItemView
    for v in W.findChildren(QAbstractItemView):
        if v.contextMenuPolicy() != Qt.CustomContextMenu:
            continue
        model = v.model()
        if model is None or model.rowCount() == 0:
            continue
        for r in range(min(model.rowCount(), 6)):
            idx = model.index(r, 0)
            rect = v.visualRect(idx)
            if rect.isValid() and idx.flags() & Qt.ItemIsEnabled:
                dene(f"sağ tık: {str(idx.data())[:40]}", yer(v) + " < " + (v.objectName() or type(v).__name__),
                     lambda p=rect.center(), vv=v: vv.customContextMenuRequested.emit(p), True)
                menuleri_bosalt()
                break


def sekmeleri_gez():
    """Kenar çubuğu ve sağ panel sekmeleri: her sekmeyi açıp içindeki düğmeleri dene."""
    from PySide6.QtWidgets import QTabWidget, QButtonGroup
    for grup in W.findChildren(QButtonGroup):
        for b in grup.buttons():
            try:
                b.click()
            except RuntimeError:
                continue
            APP.processEvents()
            dugmeleri_gez(W)
    for t in W.findChildren(QTabWidget):
        for i in range(t.count()):
            t.setCurrentIndex(i)
            APP.processEvents()
            dugmeleri_gez(W)


def ana():
    menubar_gez()
    dugmeleri_gez(W)
    sekmeleri_gez()
    sag_tik_menuleri()
    pencereleri_gez()
    dugmeleri_gez(W)  # pencerelerden sonra değişenler
    rapor = {"acilis_hatalari": acilis_hatalari, "sonuclar": sonuclar,
             "arka_plan": [a for a, _, _ in arka_plan], "sure": round(time.time() - t0)}
    OUT.write_text(json.dumps(rapor, ensure_ascii=False, indent=1), encoding="utf-8")
    hatali = [s for s in sonuclar if s["hatalar"]]
    bagsiz = [s for s in sonuclar if not s["bagli"] and not s["olaylar"]]
    print(f"açılış hatası: {len(acilis_hatalari)} · denenen: {len(sonuclar)} · hatalı: {len(hatali)} · "
          f"bağlantısız/etkisiz: {len(bagsiz)} · arka plan işi: {len(arka_plan)} · süre: {rapor['sure']} sn")


if __name__ == "__main__":
    try:
        ana()
    except Exception:
        print("DENETİM BETİĞİ HATASI:\n" + traceback.format_exc(), flush=True)
    sys.stdout.flush()  # os._exit tamponu boşaltmaz
    os._exit(0)
