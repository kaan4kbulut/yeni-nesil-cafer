"""Testler için ajan kütüphanesi klasörleri: kurulu programın `ajan-kutuphaneleri` ve kullanıcının `python-kutuphaneleri`,
YALNIZCA bu Python'la uyumluysa (derlenmiş uzantıların cpython etiketi). Uyumsuz klasör (ör. kurulu programın 3.12
tekerlekleri, testler 3.14 ile koşarken) PYTHONPATH'e girerse numpy içe aktarılamıyor ve 21 test "kütüphane yok" diye
sessizce atlanıyordu (2026-09-28). Uyumlu klasör yoksa `.venv`'in kendi kütüphaneleri kullanılır."""

import os
import sys
from pathlib import Path

ETIKET = f"cpython-{sys.version_info.major}{sys.version_info.minor}"
ADAYLAR = (Path.home() / ".local/share/yeni-nesil-cafer-app/ajan-kutuphaneleri",
           Path.home() / ".local/share/yerel-asistan-app/ajan-kutuphaneleri",
           Path.home() / ".local/share/yeni-nesil-cafer/python-kutuphaneleri",
           Path.home() / ".local/share/yerel-asistan/python-kutuphaneleri")


def uyumlu(yol: Path) -> bool:
    """Klasördeki derlenmiş uzantılar bu yorumlayıcı için mi? (İlk iki düzeyde `.cpython-3XY-*.so/.pyd`; hiç yoksa saf
    Python sayılır ve uyumludur.)"""
    if not yol.is_dir():
        return False
    etiketler = set()
    for alt in yol.iterdir():
        for p in (list(alt.glob("*.so")) + list(alt.glob("*.pyd")) + list(alt.glob("*/*.so")) + list(alt.glob("*/*.pyd"))
                  if alt.is_dir() else [alt]):
            ad = p.name
            if ".cpython-" in ad:
                etiketler.add(ad.split(".cpython-", 1)[1].split("-", 1)[0].split(".", 1)[0])
    return not etiketler or ETIKET.removeprefix("cpython-") in etiketler


def yollar(*adaylar) -> list[str]:
    return [str(p) for p in (adaylar or ADAYLAR) if uyumlu(Path(p))]


def pythonpath_ekle(*adaylar) -> list[str]:
    """Uyumlu klasörleri PYTHONPATH'in başına ekler (alt süreçler — ajanın Python'u — da görsün); eklenenleri döner."""
    ek = yollar(*adaylar)
    os.environ["PYTHONPATH"] = os.pathsep.join([*ek, os.environ.get("PYTHONPATH", "")]).strip(os.pathsep)
    return ek
