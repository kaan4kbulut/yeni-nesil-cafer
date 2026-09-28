"""Dosya araçları: listele, oku, ara, yaz, düzenle. Yol denetimi burada (model çıktısı güvenilmez).

Yazma yalnızca çalışma klasöründe (`kok`); okuma ayrıca programın kendi klasörlerinde (`okuma_kokleri`: kod, ayarlar,
veriler) serbest, ama anahtar dosyaları hiçbir zaman okunmaz. Onay ve risk sınıfı burada değil: `permissions.py`.
"""

import re
from pathlib import Path

from .. import ayar
from .temel import GIZLI_DOSYALAR, AracHatasi


def yol_coz(kok: Path, okuma_kokleri: list[Path], yol: str, okuma: bool = False) -> Path:
    """Modelin verdiği yolu çözer; çalışma klasörü (okumada program klasörleri de) dışına çıkarsa `AracHatasi`."""
    hedef = (kok / yol).expanduser().resolve()
    if okuma and hedef.name in GIZLI_DOSYALAR:  # çalışma klasörü ev klasörü seçilse de (K5 denetimi)
        raise AracHatasi("This file holds the user's API keys and cannot be read.")
    if okuma and hedef.is_relative_to(ayar.CONFIG_DIR.resolve()):  # ayar klasörü okuma kökü olsa da (anahtarlar orada)
        raise AracHatasi("The program's settings folder cannot be read.")
    if hedef.is_relative_to(kok):
        return hedef
    if okuma and any(hedef.is_relative_to(r) for r in okuma_kokleri):
        return hedef
    raise AracHatasi(f"Path is outside the workspace: {yol}"
                     + (" (writing is only allowed inside the workspace)" if not okuma and any(
                         hedef.is_relative_to(r) for r in okuma_kokleri) else ""))


def taban(hedef: Path, kok: Path, okuma_kokleri: list[Path]) -> Path:
    """Yolun bağlı olduğu izinli kök (çalışma klasörü ya da programın bir klasörü)."""
    return next((r for r in (kok, *okuma_kokleri) if hedef.is_relative_to(r)), kok)


def gorunen(yol: Path, kok: Path) -> str:
    return str(yol.relative_to(kok)) if yol.is_relative_to(kok) else str(yol)


def listele(kok: Path, okuma_kokleri: list[Path], yol: str = ".") -> str:
    hedef = yol_coz(kok, okuma_kokleri, yol, okuma=True)
    if not hedef.is_dir():
        raise AracHatasi(f"Not a directory: {yol}")
    girdiler = sorted(hedef.iterdir(), key=lambda p: (not p.is_dir(), p.name.lower()))
    satirlar = []
    for p in girdiler[:500]:
        if p.is_dir():
            satirlar.append(f"{p.name}/")
        else:
            satirlar.append(f"{p.name}  ({p.stat().st_size} bytes)")
    return "\n".join(satirlar) or "(empty directory)"


def oku(kok: Path, okuma_kokleri: list[Path], yol: str, baslangic: int = 1, en_cok: int = 2000) -> str:
    hedef = yol_coz(kok, okuma_kokleri, yol, okuma=True)
    if not hedef.is_file():
        raise AracHatasi(f"File not found: {yol}")
    try:
        satirlar = hedef.read_text(encoding="utf-8").splitlines()
    except UnicodeDecodeError:
        raise AracHatasi("File is not UTF-8 text") from None
    bas = max(baslangic, 1)
    parca = satirlar[bas - 1 : bas - 1 + max(en_cok, 1)]
    govde = "\n".join(f"{i}\t{satir}" for i, satir in enumerate(parca, bas))
    son = bas + len(parca) - 1
    if parca and (bas > 1 or son < len(satirlar)):  # model dosyanın devamı olduğunu bilsin
        govde += (f"\n[satır {bas}-{son} / toplam {len(satirlar)}; devamı için start_line kullan, "
                  "belirli bir şeyi aramak için search_files]")
    return govde or "(empty file)"


def ara(kok: Path, okuma_kokleri: list[Path], desen: str, yol: str = ".", en_cok: int = 200) -> str:
    hedef = yol_coz(kok, okuma_kokleri, yol, okuma=True)
    izinli = taban(hedef, kok, okuma_kokleri)
    if not hedef.exists():
        raise AracHatasi(f"Not found: {yol}")
    try:
        rx = re.compile(desen, re.I)
    except re.error:
        rx = re.compile(re.escape(desen), re.I)
    dosyalar = [hedef] if hedef.is_file() else sorted(
        p for p in hedef.rglob("*") if p.is_file() and not any(x.startswith(".") for x in p.relative_to(hedef).parts))
    bulunan, taranan = [], 0
    for f in dosyalar:
        if f.stat().st_size > 50_000_000 or not f.resolve().is_relative_to(izinli) or f.name in GIZLI_DOSYALAR:
            continue  # çok büyük ya da klasör dışını gösteren sembolik bağ
        try:
            with f.open(encoding="utf-8") as fh:
                taranan += 1
                for n, satir in enumerate(fh, 1):
                    if rx.search(satir):
                        bulunan.append(f"{gorunen(f, kok)}:{n}: {satir.rstrip()[:300]}")
                        if len(bulunan) >= max(1, en_cok):
                            return "\n".join(bulunan) + f"\n[ilk {len(bulunan)} sonuç; daha fazlası olabilir]"
        except (UnicodeDecodeError, OSError):
            continue  # ikili dosya
    if not bulunan:
        return f"No matches for {desen!r} in {taranan} text file(s)."
    return f"{len(bulunan)} eşleşme:\n" + "\n".join(bulunan)


def yaz(kok: Path, okuma_kokleri: list[Path], yol: str, icerik: str) -> str:
    """`okuma_kokleri` yalnızca hata metni için: program klasörüne yazmaya kalkarsa model nedenini bilsin."""
    hedef = yol_coz(kok, okuma_kokleri, yol)
    hedef.parent.mkdir(parents=True, exist_ok=True)
    hedef.write_text(icerik, encoding="utf-8")
    return f"Wrote {len(icerik)} characters to {hedef.relative_to(kok)}"


def tasi(kok: Path, okuma_kokleri: list[Path], kaynak: str, hedef: str) -> str:
    """Dosya ya da klasörü çalışma klasörü içinde taşır / yeniden adlandırır. Hedef var olan bir klasörse içine taşır;
    var olan bir dosyanın üstüne yazmaz (veri kaybı olmasın)."""
    import shutil

    k = yol_coz(kok, okuma_kokleri, kaynak)
    if not k.exists():
        raise AracHatasi(f"Not found: {kaynak}")
    if k == kok:
        raise AracHatasi("The workspace folder itself cannot be moved")
    h = yol_coz(kok, okuma_kokleri, hedef)
    if hedef.endswith(("/", "\\")):  # "arsiv/": klasöre taşı (yoksa açılır)
        h.mkdir(parents=True, exist_ok=True)
    if h.is_dir():
        h = h / k.name
    if h.exists():
        raise AracHatasi(f"Target already exists: {gorunen(h, kok)} (nothing was overwritten)")
    if h.is_relative_to(k):
        raise AracHatasi("A folder cannot be moved into itself")
    h.parent.mkdir(parents=True, exist_ok=True)
    shutil.move(str(k), str(h))
    return f"Moved {gorunen(k, kok)} -> {gorunen(h, kok)}"


def duzenle(kok: Path, okuma_kokleri: list[Path], yol: str, eski: str, yeni: str) -> str:
    hedef = yol_coz(kok, okuma_kokleri, yol)
    if not hedef.is_file():
        raise AracHatasi(f"File not found: {yol}")
    metin = hedef.read_text(encoding="utf-8")
    sayi = metin.count(eski)
    if sayi != 1:
        raise AracHatasi(f"old_text must occur exactly once, found {sayi} occurrences")
    hedef.write_text(metin.replace(eski, yeni), encoding="utf-8")
    return f"Edited {hedef.relative_to(kok)}"
