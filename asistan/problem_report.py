"""Sorun raporu: program kendi kodunu değiştirmez; sorunu algılar, anlar ve kullanıcının Claude Code'a (geliştiriciye)
doğrudan verebileceği tek bir Markdown dosyası hazırlar.

İçerik: ne oldu + programın ön teşhisi (yerel model, kısa) · sürüm, sistem, ekran kartı, ayarların özeti (anahtarsız)
· istek, sohbetin son bölümü (araç çağrıları ve hatalarıyla) · kullanılan modelin kartı · program günlüğünün sonu
(yakalanmamış hatalar, crash_log) · son sorun kayıtları. API anahtarları ve parolalar dosyaya yazılmadan önce
gizlenir (`redact`). Dosya masaüstüne (yoksa DATA_DIR/sorun-raporlari) yazılır, bir kopyası DATA_DIR'de kalır.
"""

import json
import platform
import re
import subprocess
import sys
import threading
import time
import traceback
from pathlib import Path

from .config import DATA_DIR

REPORTS_DIR = DATA_DIR / "sorun-raporlari"
LOG_FILE = DATA_DIR / "program-gunlugu.log"  # yakalanmamış hatalar (install_crash_log)
LOG_LIMIT = 300_000  # günlük bu boyutu aşınca eski yarısı atılır

KINDS = {"hata": "Hata verdi", "tamamlanamadi": "İş tamamlanamadı", "begenilmedi": "Kullanıcı beğenmedi",
         "bos_cevap": "Boş cevap", "cokme": "Program hatası (yakalanmamış)", "kullanici": "Kullanıcının bildirdiği"}

# bilinen anahtar biçimleri (sağlayıcılar): gerçek değerler de ayrıca aranır (secrets)
_KEY_PATTERNS = [r"sk-ant-[A-Za-z0-9_\-]{10,}", r"sk-[A-Za-z0-9_\-]{16,}", r"AIza[0-9A-Za-z_\-]{30,}",
                 r"gsk_[A-Za-z0-9]{20,}", r"hf_[A-Za-z0-9]{20,}", r"gh[pousr]_[A-Za-z0-9]{20,}",
                 r"xox[abpr]-[A-Za-z0-9\-]{10,}", r"(?i)(bearer\s+)[A-Za-z0-9._\-]{16,}",
                 r"(?i)((?:api[_-]?key|token|password|parola|şifre)[\"']?\s*[:=]\s*[\"']?)[^\s\"',}]{6,}"]


def secrets() -> list[str]:
    """Bu bilgisayarda kayıtlı gerçek anahtarlar (rapora asla girmesin diye aranır)."""
    found = []
    try:
        from .connections import ANTHROPIC_KEY, load_connections
        from .keystore import get_secret

        found.append(get_secret(ANTHROPIC_KEY) or "")
        found += [c.key or "" for c in load_connections()]
    except Exception:
        pass
    return [s for s in found if len(s) >= 8]


def redact(text: str, known: list[str] | None = None) -> str:
    """Anahtarlar, parolalar ve kişiyi belli eden yol / kullanıcı adı rapora girmez."""
    for s in known if known is not None else secrets():
        text = text.replace(s, "«gizlendi»")
    home = str(Path.home())
    text = text.replace(home, "~")  # /home/<kullanıcı>/… → ~/…
    user = Path(home).name
    if len(user) >= 4:
        text = re.sub(re.escape(user), "«kullanıcı»", text, flags=re.I)
    for pattern in _KEY_PATTERNS:
        text = re.sub(pattern, lambda m: (m.group(1) if m.lastindex else "") + "«gizlendi»", text)
    return text


# ---------------------------------------------------------------- program günlüğü (çökmeler)

def log_line(text: str) -> None:
    try:
        LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
        if LOG_FILE.exists() and LOG_FILE.stat().st_size > LOG_LIMIT:
            LOG_FILE.write_text(LOG_FILE.read_text(encoding="utf-8", errors="replace")[-LOG_LIMIT // 2:],
                                encoding="utf-8")
        with LOG_FILE.open("a", encoding="utf-8") as f:
            f.write(f"{time.strftime('%Y-%m-%d %H:%M:%S')} {text}\n")
    except OSError:
        pass


def install_crash_log(on_crash=None) -> None:
    """Yakalanmamış hatalar (arayüz ve iş parçacıkları) günlüğe ve sorun kayıtlarına yazılır; program kapanmaz.
    on_crash(özet): arayüz kullanıcıya "raporla" önerir (arayüz iş parçacığında çağrılmayabilir)."""
    def handle(kind, value, tb):
        text = "".join(traceback.format_exception(kind, value, tb))
        log_line("YAKALANMAMIŞ HATA\n" + text)
        try:
            from . import learning

            learning.log_issue("cokme", "", "", text[-1500:])
        except Exception:
            pass
        if on_crash:
            try:
                on_crash(f"{kind.__name__}: {value}")
            except Exception:
                pass

    sys.excepthook = handle
    threading.excepthook = lambda args: handle(args.exc_type, args.exc_value, args.exc_traceback)


def log_tail(lines: int = 80) -> str:
    try:
        return "\n".join(LOG_FILE.read_text(encoding="utf-8", errors="replace").splitlines()[-lines:])
    except OSError:
        return ""


# ---------------------------------------------------------------- rapor

def _system(settings) -> str:
    from . import __version__

    gpu = ""
    try:
        out = subprocess.run(["nvidia-smi", "--query-gpu=name,memory.total,driver_version", "--format=csv,noheader"],
                             capture_output=True, text=True, timeout=5)
        gpu = out.stdout.strip()
    except (OSError, subprocess.TimeoutExpired):
        pass
    try:
        from PySide6 import __version__ as qt
    except ImportError:
        qt = "?"
    ollama = ""
    try:
        import httpx

        ollama = httpx.get(settings.ollama_url.rstrip("/") + "/api/version", timeout=3).json().get("version", "")
    except Exception:
        pass
    return (f"- YENİ NESİL CAFER {__version__} · {platform.platform()} · Python {platform.python_version()} · PySide6 {qt}\n"
            f"- Ekran kartı: {gpu or 'bilinmiyor / yok'} · Ollama {ollama or 'çalışmıyor'}\n"
            f"- Ayarlar: sağlayıcı {settings.provider}, yerel model {settings.ollama_model}, bağlam "
            f"{settings.ollama_num_ctx} (otomatik {settings.auto_ctx}), onay kipi {settings.approval_mode}, model "
            f"politikası {settings.model_policy}, güç {settings.power_mode}")


def _content(c) -> str:
    if isinstance(c, str):
        return c
    parts = []
    for block in c or []:
        if not isinstance(block, dict):
            continue
        if block.get("type") == "text":
            parts.append(block.get("text", ""))
        elif block.get("type") == "tool_use":
            parts.append(f"→ araç {block.get('name')}({json.dumps(block.get('input'), ensure_ascii=False)[:600]})")
        elif block.get("type") == "tool_result":
            parts.append(f"← sonuç{' (HATA)' if block.get('is_error') else ''}: {str(block.get('content'))[:1200]}")
    return "\n".join(parts)


def conversation(messages: list, last: int = 16) -> str:
    """Sohbetin son bölümü: istekler, cevaplar, araç çağrıları ve sonuçları (uzunlar kısaltılır)."""
    out = []
    for m in (messages or [])[-last:]:
        role = "program" if m.get("_program") else m.get("role", "?")
        text = _content(m.get("content"))
        for call in m.get("tool_calls") or []:
            fn = call.get("function") or {}
            text += f"\n→ araç {fn.get('name')}({str(fn.get('arguments'))[:600]})"
        if role == "tool":
            role = f"araç sonucu{(' ' + m['tool_name']) if m.get('tool_name') else ''}"
        text = text.strip()
        if len(text) > 2500:
            text = text[:1200] + "\n[…]\n" + text[-1000:]
        if text:
            out.append(f"**[{role}]**\n```\n{text}\n```")
    return "\n\n".join(out) or "(sohbet yok)"


def diagnose(summary: str, settings, timeout: float = 60) -> str:
    """Yerel modelin kısa ön teşhisi (olası neden, nereye bakılmalı). Ollama yoksa boş: rapor yine yazılır."""
    try:
        import httpx

        r = httpx.post(settings.ollama_url.rstrip("/") + "/api/chat", json={
            "model": settings.ollama_model, "stream": False, "think": False, "keep_alive": "10m",
            "options": {"num_ctx": 8192, "num_predict": 400, "temperature": 0.2},
            "messages": [{"role": "user", "content": (
                "Bir masaüstü yapay zekâ asistanında (YENİ NESİL CAFER) aşağıdaki sorun oldu. Türkçe, en fazla 5 madde: "
                "en olası neden(ler), bunun model yetersizliği mi, eksik araç/kütüphane mi, programda hata mı olduğu, "
                "ve geliştiricinin nereye bakması gerektiği. Emin olmadığın yerde 'olabilir' de.\n\n"
                + summary[-6000:])}]}, timeout=timeout)
        r.raise_for_status()
        return ((r.json().get("message") or {}).get("content") or "").strip()
    except Exception:
        return ""


def build(kind: str, detail: str, request: str, model: str, settings, messages: list | None = None,
          work_dir: str = "", note: str = "", with_diagnosis: bool = True) -> str:
    """Raporun Markdown metni (anahtarlar gizlenmiş)."""
    from . import cards, learning

    when = time.strftime("%Y-%m-%d %H:%M")
    card = cards.card(model) if model else None
    recent = learning.issues()[-8:]
    issues = "\n".join(f"- {time.strftime('%d.%m %H:%M', time.localtime(i['time']))} · "
                       f"{KINDS.get(i['kind'], i['kind'])} · {i['model'] or '?'} · {i['request'][:120]}"
                       for i in recent) or "-"
    convo = conversation(messages or [])
    summary = (f"Tür: {KINDS.get(kind, kind)}\nKullanıcının notu: {note or '-'}\nİstek: {request or '-'}\n"
               f"Model: {model or '?'}\nAyrıntı: {detail or '-'}\n\nSohbetin sonu:\n{convo[-4000:]}")
    diagnosis = diagnose(summary, settings) if with_diagnosis else ""
    from . import GITHUB_REPO

    source = (f"https://github.com/{GITHUB_REPO} (ya da bilgisayardaki yerel kopyası)" if GITHUB_REPO
              else "bu projenin deposu ya da bilgisayardaki yerel kopyası")
    text = f"""# YENİ NESİL CAFER sorun raporu · {when}

> **Claude Code için:** Bu dosyayı YENİ NESİL CAFER programı kendisi hazırladı. Kaynak kod: {source};
> önce oradaki `CLAUDE.md`'yi oku (mimari, kurallar, bilinen tuzaklar). Aşağıdaki kanıtlardan sorunu bul, düzelt,
> testleri çalıştır (`testler/`), değişikliği kurulu programa aktar ve kurulum paketlerini güncelle. Program kendi
> kodunu değiştirmez; düzeltmeyi sen yaparsın.

## Ne oldu
- **Tür:** {KINDS.get(kind, kind)}
- **Kullanıcının notu:** {note or '-'}
- **İstek:** {request or '-'}
- **Model:** {model or '?'}
- **Ayrıntı:**
```
{(detail or '-')[-3000:]}
```

## Programın ön teşhisi (yerel model; yanılabilir)
{diagnosis or '(ön teşhis yapılamadı: yerel model yanıt vermedi)'}

## Sistem
{_system(settings)}
- Çalışma klasörü: `{work_dir or settings.workspace}`
- Modelin kartı (programın kendi sınavı): {cards.describe(card) if card else 'yok'}

## Sohbetin son bölümü
{convo}

## Program günlüğünün sonu (yakalanmamış hatalar)
```
{log_tail() or '(boş)'}
```

## Son sorun kayıtları
{issues}
"""
    return redact(text)


def desktop() -> Path:
    try:
        out = subprocess.run(["xdg-user-dir", "DESKTOP"], capture_output=True, text=True, timeout=5).stdout.strip()
        if out and Path(out).is_dir() and Path(out) != Path.home():
            return Path(out)
    except (OSError, subprocess.TimeoutExpired):
        pass
    for name in ("Desktop", "Masaüstü"):
        if (Path.home() / name).is_dir():
            return Path.home() / name
    return REPORTS_DIR


def write(text: str) -> Path:
    """Raporu masaüstüne yazar (kopyası DATA_DIR/sorun-raporlari'nda); masaüstündeki dosyanın yolu döner."""
    name = f"yeni-nesil-cafer-sorun-{time.strftime('%Y%m%d-%H%M%S')}.md"
    REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    (REPORTS_DIR / name).write_text(text, encoding="utf-8")
    target = desktop() / name
    if target.parent != REPORTS_DIR:
        try:
            target.write_text(text, encoding="utf-8")
        except OSError:
            target = REPORTS_DIR / name
    return target


def claude_prompt(path: Path) -> str:
    """Panoya kopyalanan, Claude Code'a yapıştırılacak cümle."""
    return (f"{path} dosyasındaki YENİ NESİL CAFER sorun raporunu oku; sorunu bul, düzelt, test et ve kurulum "
            "paketlerini güncelle.")

