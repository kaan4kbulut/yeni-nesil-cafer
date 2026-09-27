#!/usr/bin/env python3
"""Claude Code hook: masaüstü bildirimi.

Bağlandığı olaylar (settings.json):
  - Notification → izin/onay bekliyor, boşta bekliyor
  - Stop         → cevabını bitirdi

Bildirimde ilerleme de gösterilir (K3 6/9 %66). Windows: balon bildirim (PowerShell),
macOS: osascript, Linux: notify-send. Hiçbiri çalışmazsa terminal zili.
"""
import json
import os
import platform
import subprocess
import sys


def stdin_oku():
    try:
        return json.load(sys.stdin)
    except Exception:
        return {}


def ilerleme_metni(veri):
    kok = veri.get("cwd") or os.environ.get("CLAUDE_PROJECT_DIR") or os.getcwd()
    try:
        with open(os.path.join(kok, ".cafer", "ilerleme.json"), encoding="utf-8") as f:
            il = json.load(f)
        if il.get("toplam"):
            b, t = int(il.get("biten", 0)), int(il["toplam"])
            return f"{il.get('asama') or 'Görev'} {b}/{t} %{int(b / t * 100)}"
    except Exception:
        pass
    return ""


def bildir(baslik, metin):
    sistem = platform.system()
    try:
        if sistem == "Windows":
            b = baslik.replace("'", "''")
            m = metin.replace("'", "''")
            ps = (
                "Add-Type -AssemblyName System.Windows.Forms; Add-Type -AssemblyName System.Drawing; "
                "$n = New-Object System.Windows.Forms.NotifyIcon; "
                "$n.Icon = [System.Drawing.SystemIcons]::Information; $n.Visible = $true; "
                f"$n.ShowBalloonTip(6000, '{b}', '{m}', [System.Windows.Forms.ToolTipIcon]::Info); "
                "Start-Sleep -Seconds 7; $n.Dispose()"
            )
            subprocess.Popen(
                ["powershell", "-NoProfile", "-WindowStyle", "Hidden", "-Command", ps],
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
        elif sistem == "Darwin":
            b = baslik.replace('"', '\\"')
            m = metin.replace('"', '\\"')
            subprocess.Popen(
                ["osascript", "-e", f'display notification "{m}" with title "{b}" sound name "Glass"'],
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            )
        else:
            subprocess.Popen(
                ["notify-send", baslik, metin],
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            )
    except Exception:
        pass
    try:
        sys.stderr.write("\a")
        sys.stderr.flush()
    except Exception:
        pass


def main():
    veri = stdin_oku()
    if not veri:
        return
    olay = veri.get("hook_event_name")
    ilerleme = ilerleme_metni(veri)

    if olay == "Notification":
        tip = veri.get("notification_type", "")
        if tip in ("permission_prompt", "elicitation_dialog"):
            bildir("Claude Code onayını bekliyor", f"{ilerleme} — terminale dön".strip(" —"))
        elif tip == "idle_prompt":
            bildir("Claude Code boşta, seni bekliyor", ilerleme or "Sıradaki adımı yaz")
        elif tip == "agent_completed":
            bildir("Alt ajan bitti", ilerleme or "")
        return

    if olay == "Stop":
        son = (veri.get("last_assistant_message") or "").strip().replace("\n", " ")
        bildir("Claude Code bitirdi", f"{ilerleme} · {son[:110]}".strip(" ·"))


if __name__ == "__main__":
    try:
        main()
    except Exception:
        pass
