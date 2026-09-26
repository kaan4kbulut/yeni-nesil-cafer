"""Hook'lar: kullanıcının belirli olaylarda kendiliğinden çalışan komutları (Claude Code'daki hooks ile aynı biçim).

Ayar: `~/.config/yeni-nesil-cafer/hooks.json`
    {"hooks": {"PreToolUse": [{"matcher": "run_command|write_file",
                               "hooks": [{"type": "command", "command": "~/bin/denetle.sh", "timeout": 30}]}]}}

Olaylar:
- UserPromptSubmit: kullanıcı mesajı gönderdi. Çıkış 2 → istek işlenmez; çıktı (stdout) modele ek bilgi olur.
- PreToolUse: araç çalışmadan hemen önce (onay verildikten sonra). Çıkış 2 → araç çalışmaz, stderr modele gider.
  Hook yalnızca engelleyebilir; onay kurallarını (permissions.py) aşamaz.
- PostToolUse: araç çalıştıktan sonra. Çıkış 2 → stderr araç sonucuna eklenir (model düzeltsin diye).
- Stop: tur bitti (bildirim, yedek vb.). Engelleyemez.
Komut olayı JSON olarak standart girdiden alır: event, cwd, request, tool_name, tool_input, tool_result.
Diğer çıkış kodları ve zaman aşımı işi durdurmaz; `DATA_DIR/hook-kayitlari.log` dosyasına yazılır.
Asistan bu dosyayı değiştiremez (security._FORBIDDEN): kendiliğinden çalışan komut kurmak kullanıcının işi.
"""

import json
import re
import subprocess
import sys
import time
from dataclasses import dataclass

from .config import CONFIG_DIR, DATA_DIR

CONFIG_FILE = CONFIG_DIR / "hooks.json"
LOG_FILE = DATA_DIR / "hook-kayitlari.log"
EVENTS = ("UserPromptSubmit", "PreToolUse", "PostToolUse", "Stop")
TIMEOUT = 30  # saniye (hook başına "timeout" ile değişir)
BLOCK = 2  # bu çıkış kodu: engelle
NO_WINDOW = subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0

_cache: tuple[float, dict] = (-1.0, {})


@dataclass
class Outcome:
    blocked: bool = False
    message: str = ""  # engellendiyse nedeni (stderr), değilse komutların çıktısı (stdout)


def load() -> dict:
    """hooks.json'daki olay → gruplar; dosya yoksa ya da bozuksa boş (değişince yeniden okunur)."""
    global _cache
    try:
        mtime = CONFIG_FILE.stat().st_mtime
    except OSError:
        return {}
    if mtime != _cache[0]:
        try:
            data = json.loads(CONFIG_FILE.read_text(encoding="utf-8")).get("hooks") or {}
        except (OSError, ValueError, AttributeError) as e:
            _log(f"hooks.json okunamadı: {e}")
            data = {}
        _cache = (mtime, data if isinstance(data, dict) else {})
    return _cache[1]


def active(event: str) -> bool:
    return bool(load().get(event))


def run(event: str, payload: dict, tool: str = "") -> Outcome:
    """Olayın hook'larını sırayla çalıştırır; biri engellerse durur."""
    outputs = []
    for group in load().get(event) or []:
        matcher = str(group.get("matcher") or "") if isinstance(group, dict) else ""
        if tool and matcher and matcher != "*" and not re.fullmatch(matcher, tool):
            continue
        for hook in (group.get("hooks") or []) if isinstance(group, dict) else []:
            if not isinstance(hook, dict) or hook.get("type", "command") != "command" or not hook.get("command"):
                continue
            command = str(hook["command"])
            try:
                proc = subprocess.run(command, shell=True, input=json.dumps({"event": event, **payload},
                                                                            ensure_ascii=False, default=str),
                                      capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=float(hook.get("timeout") or TIMEOUT),
                                      cwd=payload.get("cwd") or None, creationflags=NO_WINDOW)
            except subprocess.TimeoutExpired:
                _log(f"{event} {command}: zaman aşımı")
                continue
            except OSError as e:
                _log(f"{event} {command}: {e}")
                continue
            if proc.returncode == BLOCK:
                return Outcome(True, proc.stderr.strip()[:2000] or f"“{command}” hook'u engelledi.")
            if proc.returncode != 0:
                _log(f"{event} {command}: çıkış {proc.returncode}: {proc.stderr.strip()[:500]}")
            elif proc.stdout.strip():
                outputs.append(proc.stdout.strip()[:2000])
    return Outcome(False, "\n".join(outputs))


def _log(text: str) -> None:
    try:
        LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
        with LOG_FILE.open("a", encoding="utf-8") as f:
            f.write(f"{time.strftime('%Y-%m-%d %H:%M:%S')} {text}\n")
    except OSError:
        pass
