"""Komut ve Python araçları: alt süreçte, çalışma klasöründe, zaman aşımıyla.

Hangi Python'un ve hangi ortamın kullanılacağı (programın gömülü Python'u, ajan kütüphaneleri, sudo parola penceresi)
çağırandan gelir (`tools.py`: `python_exe`, `agent_env`, `_askpass_launcher`); böylece o ayarlar tek yerde kalır.
Onay (çalıştırmadan önce) `permissions.py` + güvenlik ajanında; burası yalnızca çalıştırır.
"""

import os
import re
import subprocess
import sys
import tempfile
from collections.abc import Callable
from pathlib import Path

from .temel import PENCERESIZ, AracHatasi

ZAMAN_ASIMI = 120


def surec(argv: list[str], kok: Path, ortam: dict | None = None, zaman_asimi: float = ZAMAN_ASIMI) -> str:
    """Alt süreci çalıştırır; çıkış kodu + stdout + stderr metni döner (modele gider)."""
    try:
        proc = subprocess.run(
            argv, cwd=kok, capture_output=True, text=True, timeout=zaman_asimi,
            stdin=subprocess.DEVNULL, env=ortam, creationflags=PENCERESIZ,
            encoding="utf-8", errors="replace",
        )
    except subprocess.TimeoutExpired:
        raise AracHatasi(f"Timed out after {zaman_asimi} seconds") from None
    cikti = f"exit code: {proc.returncode}\n"
    if proc.stdout:
        cikti += f"--- stdout ---\n{proc.stdout}"
    if proc.stderr:
        cikti += f"\n--- stderr ---\n{proc.stderr}"
    return cikti


def komut_calistir(komut: str, kok: Path, *, python_yolu: Callable[[], str], ajan_ortami: Callable[[], dict],
                   askpass: Callable[[], str], zaman_asimi: float = ZAMAN_ASIMI) -> str:
    """Linux/macOS: bash; Windows: PowerShell. `sudo` parolayı grafik pencereyle ister (terminal yok)."""
    if sys.platform == "win32":  # Windows: PowerShell (sistem istemi modele Windows olduğunu söyler)
        # Windows'ta çoğu zaman Python yok: `python` komutu paketteki Python'u (ve hazır kütüphaneleri) bulsun
        ortam = ajan_ortami()
        ortam["PATH"] = str(Path(python_yolu()).parent) + os.pathsep + ortam.get("PATH", "")
        return surec(["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", komut], kok, ortam,
                     zaman_asimi)
    if re.search(r"\bsudo\b", komut):
        # terminal yok: sudo parolayı grafik pencereyle istesin (komut güvenlik ajanından geçti)
        ortam = {**os.environ, "SUDO_ASKPASS": askpass(), "YA_SUDO_COMMAND": komut}
        komut = re.sub(r"\bsudo\b(?!\s+-A)", "sudo -A", komut)
        return surec(["bash", "-c", komut], kok, ortam, zaman_asimi)
    return surec(["bash", "-c", komut], kok, None, zaman_asimi)


def kacislari_coz(kod: str) -> str:
    """Bazı yerel modeller (qwen2.5:14b) kodu gerçek satır sonu yerine düz metin "\\n" ile gönderir: kod tek satır
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
    """Kodu geçici dosyaya yazıp ajan Python'unda çalıştırır. `arac_adlari`: kayıtlı araçlar (yanlış kullanım uyarısı)."""
    with tempfile.NamedTemporaryFile("w", suffix=".py", delete=False, encoding="utf-8") as f:
        f.write(kacislari_coz(kod))
        betik = f.name
    try:
        sonuc = surec([python_yolu, betik], kok, ortam, zaman_asimi)
    finally:
        Path(betik).unlink(missing_ok=True)
    # küçük modeller aracı Python işlevi gibi çağırıyor (make_decor_model(...) → NameError, 2026-09-27)
    yanlis = re.search(r"NameError: name '(\w+)' is not defined", sonuc)
    if yanlis and yanlis.group(1) in arac_adlari:
        sonuc += (f"\n\n{yanlis.group(1)} is a TOOL, not a Python function: do not call it inside run_python code; "
                  "call the tool itself with its arguments.")
    return sonuc
