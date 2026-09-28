"""Komut ve Python araçları: alt süreçte, çalışma klasöründe, zaman aşımıyla.

Hangi Python'un ve hangi ortamın kullanılacağı (programın gömülü Python'u, ajan kütüphaneleri, sudo parola penceresi)
çağırandan gelir (`tools.py`: `python_exe`, `agent_env`, `_askpass_launcher`); böylece o ayarlar tek yerde kalır.
Onay (çalıştırmadan önce) `permissions.py` + güvenlik ajanında; burası yalnızca çalıştırır.
"""

import os
import re
import signal
import subprocess
import sys
import tempfile
from collections.abc import Callable
from pathlib import Path

from .temel import PENCERESIZ, AracHatasi

ZAMAN_ASIMI = 120

# Alt sürece geçen ortam: yalnızca beyaz liste (MIMARI §10 "anahtarlar alt sürece geçirilmez"). Modelin yazdığı komut ya
# da Python kodu `env` deyip ANTHROPIC_API_KEY / CAFER_TOKEN gibi sırları okuyamaz; yetenek manifesti `anahtar:<AD>`
# ile açıkça istediği tek bir değişkeni `izinli` ile alır. CAFER_* ve ANTHROPIC_API_KEY istense de geçmez.
ORTAM_BEYAZ_LISTESI = frozenset({
    "PATH", "HOME", "LANG", "LANGUAGE", "TERM", "TMPDIR", "TEMP", "TMP", "USER", "LOGNAME", "SHELL", "TZ",
    "DISPLAY", "WAYLAND_DISPLAY", "XAUTHORITY", "DBUS_SESSION_BUS_ADDRESS", "SSL_CERT_FILE", "SSL_CERT_DIR",
    "REQUESTS_CA_BUNDLE", "MPLBACKEND", "VIRTUAL_ENV", "OLLAMA_HOST",
    # Windows
    "SYSTEMROOT", "SYSTEMDRIVE", "COMSPEC", "PATHEXT", "WINDIR", "APPDATA", "LOCALAPPDATA", "USERPROFILE",
    "PROGRAMFILES", "PROGRAMDATA", "USERNAME", "HOMEDRIVE", "HOMEPATH",
})
ORTAM_BEYAZ_ONEKLER = ("LC_", "XDG_", "PYTHON")  # yerel ayarlar, masaüstü klasörleri, PYTHONPATH/PYTHONUTF8…
ORTAM_ASLA = re.compile(r"^CAFER_|^ANTHROPIC_API_KEY$")  # açıkça istense de geçmez


def guvenli_ortam(kaynak: dict | None = None, ek: dict | None = None, izinli=()) -> dict:
    """Alt süreç ortamı: `kaynak`tan (varsayılan `os.environ`) yalnızca beyaz listedekiler + `izinli` adlar + `ek`."""
    kaynak = os.environ if kaynak is None else kaynak
    ortam = {ad: deger for ad, deger in kaynak.items()
             if (ad in ORTAM_BEYAZ_LISTESI or ad.startswith(ORTAM_BEYAZ_ONEKLER)) and not ORTAM_ASLA.search(ad)}
    for ad in izinli:
        if ad in kaynak and not ORTAM_ASLA.search(ad):
            ortam[ad] = kaynak[ad]
    ortam.update(ek or {})
    return ortam


def grubu_oldur(proc: subprocess.Popen) -> None:
    """Süreci ve (posix'te) bütün süreç grubunu öldürür, sonra toplar (K12-D10: `bash -c "x &"` torunları öksüz kalıyordu)."""
    try:
        if sys.platform == "win32":
            proc.kill()
        else:
            os.killpg(proc.pid, signal.SIGKILL)
    except (OSError, ProcessLookupError):
        pass
    try:
        proc.communicate(timeout=5)
    except (subprocess.TimeoutExpired, OSError, ValueError):
        pass


def surec(argv: list[str], kok: Path, ortam: dict | None = None, zaman_asimi: float = ZAMAN_ASIMI) -> str:
    """Alt süreci çalıştırır; çıkış kodu + stdout + stderr metni döner (modele gider). Zaman aşımında süreç GRUBU
    öldürülür (ayrı oturum: `start_new_session`)."""
    proc = subprocess.Popen(
        argv, cwd=kok, stdout=subprocess.PIPE, stderr=subprocess.PIPE, stdin=subprocess.DEVNULL, env=ortam,
        creationflags=PENCERESIZ, text=True, encoding="utf-8", errors="replace",
        start_new_session=sys.platform != "win32",
    )
    try:
        stdout, stderr = proc.communicate(timeout=zaman_asimi)
    except subprocess.TimeoutExpired:
        grubu_oldur(proc)
        raise AracHatasi(f"Timed out after {zaman_asimi} seconds") from None
    cikti = f"exit code: {proc.returncode}\n"
    if stdout:
        cikti += f"--- stdout ---\n{stdout}"
    if stderr:
        cikti += f"\n--- stderr ---\n{stderr}"
    return cikti


def komut_calistir(komut: str, kok: Path, *, python_yolu: Callable[[], str], ajan_ortami: Callable[[], dict],
                   askpass: Callable[[], str], zaman_asimi: float = ZAMAN_ASIMI) -> str:
    """Linux/macOS: bash; Windows: PowerShell. `sudo` parolayı grafik pencereyle ister (terminal yok)."""
    if sys.platform == "win32":  # Windows: PowerShell (sistem istemi modele Windows olduğunu söyler)
        # Windows'ta çoğu zaman Python yok: `python` komutu paketteki Python'u (ve hazır kütüphaneleri) bulsun
        ortam = guvenli_ortam(ajan_ortami())
        ortam["PATH"] = str(Path(python_yolu()).parent) + os.pathsep + ortam.get("PATH", "")
        return surec(["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", komut], kok, ortam,
                     zaman_asimi)
    if re.search(r"\bsudo\b", komut):
        # terminal yok: sudo parolayı grafik pencereyle istesin (komut güvenlik ajanından geçti)
        ortam = guvenli_ortam(ek={"SUDO_ASKPASS": askpass(), "YA_SUDO_COMMAND": komut})
        komut = re.sub(r"\bsudo\b(?!\s+-A)", "sudo -A", komut)
        return surec(["bash", "-c", komut], kok, ortam, zaman_asimi)
    return surec(["bash", "-c", komut], kok, guvenli_ortam(), zaman_asimi)


def kacislari_coz(kod: str) -> str:
    """Bazı yerel modeller (qwen2.5 14B) kodu gerçek satır sonu yerine düz metin "\\n" ile gönderir: kod tek satır
    olur ve her denemede SyntaxError verir (bir grup görevi bu yüzden hiçbir şey üretemedi, 2026-09-27). Kod
    tek satırsa, olduğu gibi derlenmiyorsa ve kaçışlar çözülünce derleniyorsa çözülmüş hali döner; yoksa aynen."""
    if "\n" in kod or "\\n" not in kod:
        return kod
    try:
        compile(kod, "<kod>", "exec")
        return kod  # zaten geçerli (ör. print("a\\nb"))
    except (SyntaxError, ValueError):
        pass
    try:  # Türkçe harfler latin-1'e sığmaz: önce \\uXXXX olur, çözümde geri gelir
        duzeltilmis = kod.encode("latin-1", "backslashreplace").decode("unicode_escape")
        compile(duzeltilmis, "<kod>", "exec")
    except (SyntaxError, ValueError, UnicodeError):
        return kod
    return duzeltilmis


def python_calistir(kod: str, kok: Path, *, python_yolu: str, ortam: dict, arac_adlari: set | dict = (),
                    zaman_asimi: float = ZAMAN_ASIMI) -> str:
    """Kodu geçici dosyaya yazıp ajan Python'unda çalıştırır. `arac_adlari`: kayıtlı araçlar (yanlış kullanım uyarısı).
    `ortam` (ajan kütüphaneleri, PYTHONPATH) beyaz listeden geçirilir: sırlar koda ulaşmaz."""
    with tempfile.NamedTemporaryFile("w", suffix=".py", delete=False, encoding="utf-8") as f:
        f.write(kacislari_coz(kod))
        betik = f.name
    try:
        sonuc = surec([python_yolu, betik], kok, guvenli_ortam(ortam), zaman_asimi)
    finally:
        Path(betik).unlink(missing_ok=True)
    # küçük modeller aracı Python işlevi gibi çağırıyor (make_decor_model(...) → NameError, 2026-09-27)
    yanlis = re.search(r"NameError: name '(\w+)' is not defined", sonuc)
    if yanlis and yanlis.group(1) in arac_adlari:
        sonuc += (f"\n\n{yanlis.group(1)} is a TOOL, not a Python function: do not call it inside run_python code; "
                  "call the tool itself with its arguments.")
    return sonuc
