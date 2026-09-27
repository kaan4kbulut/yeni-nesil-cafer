"""İnternet kurulumu: GitHub'daki küçük kurulum dosyasında olmayan parçaları resmi kaynaklarından indirip kurar.

Kullanıcı programın GitHub'dan tek, küçük bir dosyayla indirilebilmesini istedi; gerekenler ilk kurulumda internetten
gelsin (2026-09-27). Tam paket (~8 GB, her şey içinde) arkadaşlara elden verilir; internet paketi (birkaç MB) yalnızca
programın kodunu ve sürüm listelerini taşır. kur.sh / kur.ps1 önce taşınabilir Python'u indirir, sonra bu betiği o
Python'la çalıştırır: programın ve ajanların kütüphaneleri (tam paketle birebir aynı sürümler, `kurulum/*.txt`),
Ollama (sabit sürüm, SHA-256 doğrulamalı) ve tarayıcı (Chromium). Modelleri ilk açılıştaki kurulum sihirbazı indirir,
dikte modeli ilk kullanımda iner. Kurulu parça yeniden indirilmez; kesilen indirme kaldığı yerden sürer.

YALNIZCA standart kütüphane: çalıştığında henüz hiçbir kütüphane kurulu değildir.
Kullanım (program klasöründe): python -m asistan.bootstrap <program klasörü>
"""

import hashlib
import os
import platform
import shutil
import subprocess
import sys
import tarfile
import tempfile
import time
import urllib.error
import urllib.request
import zipfile
from pathlib import Path

OLLAMA_SURUM = "v0.34.4"  # paketleme/paketle.py ile aynı
OLLAMA_URL = f"https://github.com/ollama/ollama/releases/download/{OLLAMA_SURUM}/{{}}"
OLLAMA_DOSYALARI = {  # sistem → [(dosya, sha256)]; ROCm yalnızca AMD kartta
    "windows": [("ollama-windows-amd64.zip", "535193f38f3344e5b08f5d1c171c31ce11aa17f0124ff69ae26d8ec7fe06fa62")],
    "linux": [("ollama-linux-amd64.tar.zst", "c238986e61d40c0cc5f4a9b9e40b9eea104350b77efa34741fc134e105cb9533")],
}
OLLAMA_ROCM = {
    "windows": ("ollama-windows-amd64-rocm.zip", "73b02b93f4d9335e29c467e54004fcd340db6efc0fb7f50dfef17597327c616b"),
    "linux": ("ollama-linux-amd64-rocm.tar.zst", "dbfcbdff6c36f69bfed177d1807aa2a23ad04ad9208f9a3f648d2fd36136ff3d"),
}


def yaz(metin: str) -> None:
    print(f"  {metin}", flush=True)


def _sure(saniye: float) -> str:
    return f"{saniye / 60:.0f} dk" if saniye >= 90 else f"{saniye:.0f} sn"


def indir(url: str, hedef: Path, sha256: str, etiket: str, ilerleme=None) -> None:
    """Kaldığı yerden süren indirme (bağlantı koparsa yeniden dener), canlı ilerleme, SHA-256 doğrulaması.
    ilerleme(yüzde, metin) verilirse (kurulum sihirbazı) ekrana değil ona bildirilir."""
    hedef.parent.mkdir(parents=True, exist_ok=True)
    if hedef.is_file() and _sha(hedef) == sha256:
        return
    parca = hedef.with_suffix(hedef.suffix + ".part")
    for deneme in range(30):
        var = parca.stat().st_size if parca.exists() else 0
        istek = urllib.request.Request(url, headers={"Range": f"bytes={var}-"} if var else {})
        try:
            with urllib.request.urlopen(istek, timeout=60) as cevap:
                if var and cevap.status != 206:  # sunucu devam etmeyi desteklemiyor: baştan
                    var = 0
                    parca.unlink(missing_ok=True)
                toplam = var + int(cevap.headers.get("Content-Length") or 0)
                bas, son, ilk = time.time(), 0.0, var
                with open(parca, "ab") as f:
                    while True:
                        blok = cevap.read(1 << 20)
                        if not blok:
                            break
                        f.write(blok)
                        var += len(blok)
                        if time.time() - son > 1:
                            son = time.time()
                            hiz = (var - ilk) / max(son - bas, 0.001)
                            kalan = f" · ~{_sure((toplam - var) / hiz)} kaldı" if toplam and hiz > 0 else ""
                            yuzde = f"%{var * 100 // toplam:>3} · " if toplam else ""
                            metin = (f"{etiket}: {yuzde}{var / 1e6:,.0f} / {toplam / 1e6:,.0f} MB · "
                                     f"{hiz / 1e6:.1f} MB/sn{kalan}")
                            if ilerleme:
                                ilerleme(var * 100 // toplam if toplam else -1, metin)
                            else:
                                print(f"\r  {metin}      ", end="", flush=True)
            if not ilerleme:
                print()
            break
        except urllib.error.HTTPError as e:
            if e.code == 416:  # tamamı zaten inmiş
                break
            if e.code in (403, 404):
                raise SystemExit(f"  {etiket} indirilemedi ({e.code}): {url}") from None
            yaz(f"{etiket}: bağlantı hatası ({e.code}), yeniden deneniyor ({deneme + 1})")
        except (OSError, urllib.error.URLError) as e:
            print()
            yaz(f"{etiket}: bağlantı koptu ({e}), yeniden deneniyor ({deneme + 1})")
        time.sleep(3)
    else:
        raise SystemExit(f"  {etiket} indirilemedi: bağlantı sürekli kesildi. İnterneti denetleyip kurulumu yeniden "
                         "başlat; indirilen kısım korunur.")
    if _sha(parca) != sha256:
        parca.unlink(missing_ok=True)
        raise SystemExit(f"  {etiket} doğrulanamadı (SHA-256 tutmuyor); dosya silindi. Kurulumu yeniden başlat.")
    parca.replace(hedef)


def _sha(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for blok in iter(lambda: f.read(1 << 20), b""):
            h.update(blok)
    return h.hexdigest()


def _sistem() -> str:
    return "windows" if os.name == "nt" else "linux"


def _amd_kart() -> bool:
    """AMD ekran kartı var mı (Ollama'nın ROCm eki gerekir)?"""
    if os.name == "nt":
        try:
            out = subprocess.run(["powershell", "-NoProfile", "-Command",
                                  "(Get-CimInstance Win32_VideoController).Name"], capture_output=True, text=True,
                                 timeout=30).stdout
            return any(k in out.upper() for k in ("AMD", "RADEON"))
        except (OSError, subprocess.TimeoutExpired):
            return False
    return any(p.read_text().strip() == "0x1002" for p in Path("/sys/class/drm").glob("card*/device/vendor")
               if p.is_file())


def _pip(python: str, argv: list[str], etiket: str) -> None:
    yaz(etiket)
    sonuc = subprocess.run([python, "-m", "pip", "install", "--disable-pip-version-check", "--no-warn-script-location",
                            "--only-binary=:all:", "--progress-bar", "on", *argv])
    if sonuc.returncode != 0:
        raise SystemExit(f"  {etiket.rstrip('…')} kurulamadı (pip hatası). İnterneti denetleyip kurulumu yeniden "
                         "başlat.")


def kutuphaneler(uyg: Path) -> None:
    """Programın kendi kütüphaneleri (taşınabilir Python'a) ve ajanların kütüphaneleri (ajan-kutuphaneleri/)."""
    liste = uyg / "kurulum"
    isaret = uyg / "python" / ".kutuphaneler"
    imza = hashlib.sha256((liste / "program-kutuphaneleri.txt").read_bytes()).hexdigest()
    if not (isaret.is_file() and isaret.read_text() == imza):
        _pip(sys.executable, ["-r", str(liste / "program-kutuphaneleri.txt")],
             "Programın kütüphaneleri kuruluyor (~250 MB)…")
        isaret.write_text(imza)
    ajan = uyg / "ajan-kutuphaneleri"
    isaret = ajan / ".kuruldu"
    imza = hashlib.sha256((liste / "ajan-kutuphaneleri.txt").read_bytes()).hexdigest()
    if not (isaret.is_file() and isaret.read_text() == imza):
        shutil.rmtree(ajan, ignore_errors=True)
        _pip(sys.executable, ["--target", str(ajan), "--no-compile", "-r", str(liste / "ajan-kutuphaneleri.txt")],
             "Asistanın kütüphaneleri kuruluyor (Excel, Word, PDF, 3D, ses… ~700 MB)…")
        isaret.write_text(imza)


def _ac_zst(arsiv: Path, hedef: Path) -> None:
    """.tar.zst: sistemin tar'ı (zstd ile), yoksa pip'ten zstandard ile Python'da açılır."""
    if shutil.which("tar") and shutil.which("zstd"):
        if subprocess.run(["tar", "--zstd", "-xf", str(arsiv), "-C", str(hedef)]).returncode == 0:
            return
    gecici = Path(tempfile.mkdtemp(prefix="ync-zstd-"))
    subprocess.run([sys.executable, "-m", "pip", "install", "--quiet", "--disable-pip-version-check", "--target",
                    str(gecici), "zstandard"], check=True)
    sys.path.insert(0, str(gecici))
    import zstandard

    with open(arsiv, "rb") as f, zstandard.ZstdDecompressor().stream_reader(f) as akis, \
            tarfile.open(fileobj=akis, mode="r|") as t:
        t.extractall(hedef, filter="tar")


def ollama(uyg: Path, onbellek: Path | None = None, ilerleme=None) -> None:
    """Ollama'yı program klasörüne kurar (sistemde kurulu olsa da: program kendi Ollama'sını en güçlü karta sabitler).
    Kurucu ve kurulum sihirbazı (Ollama eksik kaldıysa "indir ve kur" düğmesi) aynı yolu kullanır."""
    sistem = _sistem()
    hedef = uyg / "ollama"
    if (hedef / ".surum").is_file() and (hedef / ".surum").read_text() == OLLAMA_SURUM:
        return
    dosyalar = list(OLLAMA_DOSYALARI[sistem]) + ([OLLAMA_ROCM[sistem]] if _amd_kart() else [])
    onbellek = onbellek or uyg / "kurulum" / "indirilen"
    for dosya, sha in dosyalar:
        indir(OLLAMA_URL.format(dosya), onbellek / dosya, sha, f"Ollama ({dosya})", ilerleme)
    (ilerleme or (lambda _p, m: yaz(m)))(-1, "Ollama açılıyor…")
    shutil.rmtree(hedef, ignore_errors=True)
    hedef.mkdir(parents=True)
    for dosya, _ in dosyalar:
        if dosya.endswith(".zip"):
            with zipfile.ZipFile(onbellek / dosya) as z:
                z.extractall(hedef)
        else:
            _ac_zst(onbellek / dosya, hedef)
    for dosya, _ in dosyalar:  # açıldı: indirilen arşiv yer kaplamasın
        (onbellek / dosya).unlink(missing_ok=True)
    (hedef / ".surum").write_text(OLLAMA_SURUM)


def tarayici(uyg: Path) -> None:
    """Asistanın web'de gezdiği Chromium (Playwright'ın resmi indirmesi; görünmez kip tarayıcısı alınmaz)."""
    hedef = uyg / "tarayici"
    if hedef.is_dir() and any(hedef.glob("chromium-*")):
        return
    yaz("Tarayıcı (Chromium, ~170 MB) indiriliyor…")
    env = {**os.environ, "PLAYWRIGHT_BROWSERS_PATH": str(hedef)}
    if subprocess.run([sys.executable, "-m", "playwright", "install", "--no-shell", "chromium"], env=env).returncode:
        yaz("Tarayıcı şimdi kurulamadı; asistan web'de gezinmek gerektiğinde yeniden dener.")


def main(uyg: Path) -> None:
    adimlar = [("Kütüphaneler", kutuphaneler), ("Ollama (yerel yapay zekâ motoru, ~1,4 GB)", ollama),
               ("Tarayıcı", tarayici)]
    for i, (ad, adim) in enumerate(adimlar, 1):
        bas = time.time()
        yaz(f"[{i}/{len(adimlar)}] {ad}")
        adim(uyg)
        yaz(f"      tamam ({_sure(time.time() - bas)})")
    shutil.rmtree(uyg / "kurulum" / "indirilen", ignore_errors=True)


if __name__ == "__main__":
    if len(sys.argv) != 2:
        raise SystemExit("kullanım: python -m asistan.bootstrap <program klasörü>")
    print(f"  ({platform.system()} · Python {platform.python_version()})", flush=True)
    main(Path(sys.argv[1]).resolve())
