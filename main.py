import json
import os
import shutil
import sys
import threading
from pathlib import Path

APP_DIR = Path(__file__).resolve().parent
CONFIRM_MS = 15000  # yeni sürüm bu kadar süre açık kalırsa güncelleme onaylanır (geri dönüş kaydı silinir)


def update_state_file() -> Path:
    """asistan.updates.STATE_FILE ile aynı yer; asistan paketini içe aktarmadan (yeni kod bozuksa da çalışsın)."""
    if os.name == "nt":
        base = Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData/Local"))
    else:
        base = Path(os.environ.get("XDG_DATA_HOME", Path.home() / ".local/share"))
    new, old = base / "yeni-nesil-cafer" / "guncelleme-durum.json", base / "yerel-asistan" / "guncelleme-durum.json"
    return old if old.is_file() and not new.is_file() else new  # 2.2'den güncellenirken klasör henüz taşınmadı


def rollback_if_needed(state_file: Path, app_dir: Path = APP_DIR) -> str:
    """Güncellemeden sonra yeni sürüm bir önceki açılışı onaylayamadıysa (çöktüyse) yedekteki sürüme döner.
    İlk açılışta yalnızca deneme sayısını artırır. Kullanıcıya gösterilecek not ya da boş metin döner."""
    try:
        state = json.loads(state_file.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return ""
    backup = Path(state.get("backup", ""))
    # geri dönüş yalnızca önceki açılış onaylanmadan VE düzgün kapanmadan bittiyse (çökme). Onay süresi dolmadan
    # pencereyi kapatmak (mark_clean_exit) çökme değildir; eski hâli 15 sn'den kısa her kullanımı geri alıyordu.
    if state.get("tries", 0) >= 1 and not state.get("clean_exit") and (backup / "asistan").is_dir():
        shutil.rmtree(app_dir / "asistan", ignore_errors=True)
        shutil.copytree(backup / "asistan", app_dir / "asistan")
        if (backup / "main.py").is_file():
            shutil.copy2(backup / "main.py", app_dir / "main.py")
        state_file.unlink(missing_ok=True)
        return (f"Güncelleme {state.get('to')} açılamadı; {state.get('from')} sürümüne geri dönüldü. Sorunu "
                "Yardım → Sorun bildir ile raporlayabilirsin.")
    state["tries"] = state.get("tries", 0) + 1
    state["clean_exit"] = False
    _atomik_yaz(state_file, json.dumps(state))
    return ""


def _atomik_yaz(yol: Path, metin: str) -> None:
    """Geçici dosya + os.replace (K12-C1); program paketi içe aktarılmadan önce çalıştığı için burada ayrı."""
    import os

    gecici = yol.with_name(yol.name + ".tmp")
    try:
        gecici.write_text(metin, encoding="utf-8")
        os.replace(gecici, yol)
    finally:
        gecici.unlink(missing_ok=True)


def mark_clean_exit(state_file: Path) -> None:
    """Pencere düzgün kapandı (aboutToQuit): onay süresi dolmamış olsa da bu açılış çökme sayılmaz."""
    try:
        state = json.loads(state_file.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return
    state["clean_exit"] = True
    try:
        _atomik_yaz(state_file, json.dumps(state))
    except OSError:
        pass


def main():
    # güncelleme geri dönüşü, programın geri kalanı içe aktarılmadan önce: yeni kod içe aktarmada çökse de çalışır
    rollback_note = rollback_if_needed(update_state_file())

    from PySide6.QtCore import QTimer
    from PySide6.QtGui import QIcon
    from PySide6.QtWidgets import QApplication, QMessageBox

    from asistan.config import Settings
    from asistan.gui.theme import apply_theme
    from asistan.gui.window import MainWindow

    if sys.platform == "win32":  # görev çubuğunda Python'un değil programın simgesi görünsün
        import ctypes

        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("YeniNesilCafer")
    app = QApplication(sys.argv)
    app.setWindowIcon(QIcon(str(APP_DIR / "asistan" / "gui" / "assets" / "icon.png")))
    app.setApplicationName("YENİ NESİL CAFER")
    app.setDesktopFileName("yeni-nesil-cafer")
    from asistan import sysinfo  # Ollama kapalıysa arka planda başlat (pencere beklemesin)

    threading.Thread(target=sysinfo.ensure_ollama, args=(Settings.load().ollama_url,), daemon=True).start()
    first_run = not Settings.exists()  # ayar dosyası yoksa ilk açılış: kurulum sihirbazı
    apply_theme(app, Settings.load().accent)
    window = MainWindow()
    from asistan import problem_report, updates  # yakalanmamış hatalar günlüğe ve "🐞 Sorunu raporla" önerisine

    problem_report.install_crash_log(lambda summary: window.problem.emit("cokme", summary))
    window.show()
    if rollback_note:
        QMessageBox.warning(window, "Güncelleme geri alındı", rollback_note)

    def confirm_update():  # pencere açık kaldı: yeni sürüm sağlam, geri dönüş kaydı silinir
        note = updates.confirm()
        if note:
            window._notify("⬆ " + note, 15000)

    QTimer.singleShot(CONFIRM_MS, confirm_update)
    app.aboutToQuit.connect(lambda: mark_clean_exit(update_state_file()))  # kısa açılıp kapanma çökme değil
    window.schedule_update_check()
    if first_run:
        window.run_setup()
    QTimer.singleShot(1500, window.show_tour_if_new)  # ilk kurulumda (sihirbazdan sonra) ve her yeni sürümde bir kez
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
