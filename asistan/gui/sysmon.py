"""Durum çubuğu için küçük sistem izleyici: CPU, RAM, GPU kullanımı ve sıcaklıkları."""

import shutil
import subprocess
import threading
from pathlib import Path

from PySide6.QtCore import QObject, Qt, Signal
from PySide6.QtWidgets import QHBoxLayout, QLabel, QWidget

from .theme import C

INTERVAL = 2.0  # saniye


def _cpu_times():
    if not Path("/proc/stat").exists():  # Windows / macOS
        import psutil

        t = psutil.cpu_times()
        return sum(t), t.idle + getattr(t, "iowait", 0)
    with open("/proc/stat") as f:
        vals = [int(v) for v in f.readline().split()[1:]]
    idle = vals[3] + vals[4]  # idle + iowait
    return sum(vals), idle


def _ram():
    if not Path("/proc/meminfo").exists():  # Windows / macOS
        import psutil

        mem = psutil.virtual_memory()
        return (mem.total - mem.available) / 1024 ** 3, mem.total / 1024 ** 3
    info = {}
    with open("/proc/meminfo") as f:
        for line in f:
            key, val = line.split(":", 1)
            info[key] = int(val.split()[0])
    total = info["MemTotal"]
    used = total - info["MemAvailable"]
    return used / 1024 / 1024, total / 1024 / 1024


def _find_cpu_temp_file():
    if not Path("/sys/class/hwmon").exists():
        return None
    for hw in Path("/sys/class/hwmon").glob("hwmon*"):
        try:
            name = (hw / "name").read_text().strip()
        except OSError:
            continue
        if name in ("coretemp", "k10temp", "zenpower"):
            f = hw / "temp1_input"
            if f.exists():
                return f
    return None


def _gpu():
    try:
        out = subprocess.run(
            ["nvidia-smi", "--query-gpu=utilization.gpu,temperature.gpu,memory.used,memory.total",
             "--format=csv,noheader,nounits"],
            capture_output=True, text=True, timeout=3,
        ).stdout.strip().splitlines()[0]
        util, temp, used, total = (float(v) for v in out.split(","))
        return util, temp, used / 1024, total / 1024
    except Exception:
        return None


class SystemMonitor(QObject):
    """Arka planda ölçüm yapar, sonucu `updated` sinyaliyle GUI iş parçacığına gönderir."""

    updated = Signal(dict)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._stop = threading.Event()
        self._cpu_temp_file = _find_cpu_temp_file()
        self._has_gpu = shutil.which("nvidia-smi") is not None
        self._thread = threading.Thread(target=self._loop, daemon=True)

    def start(self):
        self._thread.start()

    def stop(self):
        self._stop.set()

    def _loop(self):
        prev = _cpu_times()
        while not self._stop.wait(INTERVAL):
            data = {}
            try:
                cur = _cpu_times()
                total, idle = cur[0] - prev[0], cur[1] - prev[1]
                prev = cur
                data["cpu"] = 100 * (1 - idle / total) if total else 0
            except OSError:
                pass
            if self._cpu_temp_file:
                try:
                    data["cpu_temp"] = int(self._cpu_temp_file.read_text()) / 1000
                except (OSError, ValueError):
                    pass
            try:
                data["ram"] = _ram()
            except (OSError, KeyError):
                pass
            if self._has_gpu:
                gpu = _gpu()
                if gpu:
                    data["gpu"] = gpu
            self.updated.emit(data)


def _level(v, warn, error):
    return C["error"] if v >= error else (C["warn"] if v >= warn else None)


def _c(text, color):
    return f'<span style="color:{color}">{text}</span>' if color else text


class SystemMonitorLabel(QWidget):
    """Durum çubuğunun sağındaki bölmeler: CPU · GPU · VRAM · RAM; yalnızca yüksek değerlerde renklenir."""

    def __init__(self, parent=None):
        super().__init__(parent)
        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)
        self.labels = {}
        for key in ("cpu", "gpu", "vram", "ram"):
            label = QLabel(objectName="statusSegR")
            label.setTextFormat(Qt.RichText)
            label.hide()
            lay.addWidget(label)
            self.labels[key] = label
        self.setToolTip("Sistem kaynak kullanımı (2 sn'de bir güncellenir)")
        self.monitor = SystemMonitor(self)
        self.monitor.updated.connect(self._show)
        self.monitor.start()

    def _set(self, key: str, html: str):
        label = self.labels[key]
        label.setText(html)
        label.setMinimumWidth(label.sizeHint().width())  # dar pencerede sayılar kesilmesin; soldakiler daralır
        label.show()

    def _show(self, d: dict):
        if "cpu" in d:
            text = "CPU " + _c(f"{d['cpu']:.0f}%", _level(d["cpu"], 75, 90))
            if "cpu_temp" in d:
                text += " " + _c(f"{d['cpu_temp']:.0f}°C", _level(d["cpu_temp"], 80, 90))
            self._set("cpu", text)
        if "gpu" in d:
            util, temp, used, total = d["gpu"]
            self._set("gpu", "GPU " + _c(f"{util:.0f}%", _level(util, 101, 101)) + " "
                      + _c(f"{temp:.0f}°C", _level(temp, 80, 90)))
            # model yüklüyken VRAM hep dolu görünür; bu normal, renklendirilmez
            self._set("vram", f"VRAM {used:.1f}/{total:.0f}G")
        if "ram" in d:
            used, total = d["ram"]
            self._set("ram", "RAM " + _c(f"{used:.1f}/{total:.0f}G", _level(100 * used / total, 85, 95)))

    def shutdown(self):
        self.monitor.stop()
