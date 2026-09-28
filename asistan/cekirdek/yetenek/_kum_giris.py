"""Sandbox alt sürecinin girişi (`calistirici` başlatır; kendi başına çalıştırılmaz). Yalnızca standart kütüphane.

stdin'den iş (JSON) alır, izin dışı erişimi engelleyen denetim kancasını (`sys.addaudithook`) kurar, yeteneğin
`calistir.py`'sini yükleyip çalıştırır, sonucu stdout'a TEK satır JSON olarak yazar. Yeteneğin kendi `print`leri
stderr'e gider (sonuç satırı bozulmasın).

Kanca manifestteki `izinler`i uygular:
- dosya okuma: Python'un kendi dosyaları, yeteneğin klasörü, geçici klasör; `dosya_oku` ile çalışma klasörü ve okuma
  kökleri; `ag` ile ağ ayar dosyaları (`/etc`)
- dosya yazma / klasör açma / yeniden adlandırma: `dosya_yaz` ile yalnızca çalışma klasörü (+ geçici klasör hep)
- silme: `dosya_sil` ile yalnızca çalışma klasörü (+ geçici klasör hep)
- ağ: `ag` yoksa soket bağlantısı ve ad çözümleme engelli (Linux'ta ayrıca ağsız ad alanı: `unshare -rn`)
- alt süreç / ctypes: `komut` yoksa engelli
Denetim kancası tek başına kesin bir sınır değildir (`gc.get_referrers` gibi yollarla yamalanan işlev bulunabilir);
asıl sınırlar ayrı süreç, zaman aşımı, anahtarsız ortam ve ağsız ad alanıdır. Kanca, iyi niyetli ama yanlış kodu ve
bilinen yolları durdurur; işletim sistemi düzeyinde yalıtım (bubblewrap/seccomp) SORULAR K12'de ertelendi.
"""

import json
import os
import sys
import traceback


_KOMUT_MODULLERI = {"_posixsubprocess", "_winapi", "_multiprocessing", "multiprocessing", "pty"}


def _kokler(liste) -> list[str]:
    return [os.path.realpath(k) for k in liste if k]


def _icinde(yol: str, kokler: list[str]) -> bool:
    return any(yol == k or yol.startswith(k.rstrip(os.sep) + os.sep) for k in kokler)


def kanca_kur(is_: dict) -> None:
    izin = set(is_.get("izinler") or [])
    gecici = os.path.realpath(is_["gecici"])
    calisma = os.path.realpath(is_["calisma_klasoru"])
    program = os.path.realpath(is_["program_koku"])  # PYTHONPATH'te; ondan yalnızca asistan/ okunur
    yollar = [p for p in sys.path if p and os.path.isdir(p) and os.path.realpath(p) != program]
    okunur = _kokler([sys.prefix, sys.base_prefix, sys.exec_prefix, os.path.dirname(os.__file__), *yollar,
                      os.path.join(program, "asistan"), is_["yetenek_klasoru"], gecici,
                      *is_.get("kutuphane_yollari", []), "/dev/null", "/dev/urandom", "/dev/random",
                      "/usr/share/zoneinfo", "/usr/lib/locale", "/proc/self"])
    if "dosya_oku" in izin:
        okunur += _kokler([calisma, *is_.get("okuma_kokleri", [])])
    if "dosya_yaz" in izin:
        okunur.append(calisma)
    if "ag" in izin:
        okunur += ["/etc"]
    yazilir = [gecici] + ([calisma] if "dosya_yaz" in izin else [])
    silinir = [gecici] + ([calisma] if "dosya_sil" in izin else [])
    # hiçbir izinle açılmayanlar: programın ayar klasörü (anahtar dosyası orada) ve adıyla anahtar dosyaları — çalışma
    # klasörü ev klasörü seçilse bile
    yasak_kok = _kokler(is_.get("yasak_kokler") or [])
    yasak_ad = set(is_.get("yasak_adlar") or [])

    def red(neden: str):
        raise PermissionError(f"İzin dışı erişim engellendi: {neden}")

    def yol_(deger) -> str | None:
        if isinstance(deger, int):
            return None  # açık dosya tanıtıcısı: zaten izinle açılmış
        try:
            return os.path.realpath(os.fsdecode(deger))
        except (TypeError, ValueError):
            return None

    def kanca(olay: str, args):
        if olay in ("open", "os.listdir", "os.scandir", "os.rename", "os.replace", "os.remove", "os.unlink",
                    "shutil.rmtree", "os.link", "os.symlink") and args and args[0] is not None:
            yol = yol_(args[0])
            if yol is not None and (_icinde(yol, yasak_kok) or os.path.basename(yol) in yasak_ad):
                red(f"programın gizli dosyası: {yol}")
        if olay == "open":
            yol = yol_(args[0])
            if yol is None:
                return
            kip = args[1] if len(args) > 1 and isinstance(args[1], str) else ""
            bayrak = args[2] if len(args) > 2 and isinstance(args[2], int) else 0
            yazma = any(c in kip for c in "wax+") or bool(bayrak & (os.O_WRONLY | os.O_RDWR | os.O_CREAT | os.O_TRUNC
                                                                      | getattr(os, "O_APPEND", 0)))
            if yazma:
                if not _icinde(yol, yazilir):
                    red(f"yazma: {yol} (izin: {'dosya_yaz, yalnızca çalışma klasörü' if 'dosya_yaz' in izin else 'yok'})")
            elif not _icinde(yol, okunur):
                red(f"okuma: {yol} (izin: {'dosya_oku' if 'dosya_oku' in izin else 'yok'})")
        elif olay in ("os.listdir", "os.scandir"):
            yol = yol_(args[0] if args and args[0] is not None else ".")
            if yol is not None and not _icinde(yol, okunur) and yol != program:  # içe aktarma kökü tarar
                red(f"klasör listeleme: {yol}")
        elif olay in ("os.remove", "os.unlink", "os.rmdir", "shutil.rmtree"):
            yol = yol_(args[0])
            if yol is not None and not _icinde(yol, silinir):
                red(f"silme: {yol}")
        elif olay in ("os.rename", "os.replace", "os.link", "os.symlink"):
            for d in args[:2]:
                yol = yol_(d)
                if yol is not None and not _icinde(yol, yazilir):
                    red(f"taşıma/bağlantı: {yol}")
        elif olay in ("os.mkdir", "os.chmod", "os.chown", "os.utime", "os.truncate", "os.chflags"):
            yol = yol_(args[0])
            if yol is not None and not _icinde(yol, yazilir):
                red(f"{olay}: {yol}")
        elif olay in ("socket.connect", "socket.getaddrinfo", "socket.gethostbyname", "socket.gethostbyaddr",
                      "socket.sendto", "socket.sendmsg", "socket.bind"):
            if "ag" not in izin:
                red("ağ (izin: ag yok)")
        elif olay in ("subprocess.Popen", "os.system", "os.exec", "os.posix_spawn", "os.spawn", "os.fork",
                      "os.forkpty", "pty.spawn", "os.startfile", "ctypes.dlopen", "ctypes.dlsym"):
            if "komut" not in izin:
                red(f"{olay} (izin: komut yok)")
        elif olay == "import" and "komut" not in izin and args and args[0] in _KOMUT_MODULLERI:
            # K12-B1: fork_exec yaması sys.modules'tan silinip modül yeniden içe aktarılarak atlatılıyordu (inceleme b);
            # taze `_posixsubprocess`/`_winapi` yüklenemez (import olayı yalnızca sys.modules'ta olmayan modülde gelir)
            red(f"{args[0]} içe aktarma (izin: komut yok)")

    if "komut" not in izin:  # subprocess'in fork_exec'i denetim olayı üretmez: yol kapatılır (kancadan ÖNCE yüklenir)
        def kapali(*_a, **_k):
            red("alt süreç (izin: komut yok)")
        try:
            import _posixsubprocess
            import subprocess

            _posixsubprocess.fork_exec = kapali
            if hasattr(subprocess, "_fork_exec"):
                subprocess._fork_exec = kapali
        except ImportError:  # Windows: CreateProcess yolu "subprocess.Popen" olayıyla kapalı
            pass
    sys.addaudithook(kanca)


def main() -> int:
    is_ = json.loads(sys.stdin.read())
    cikis = sys.stdout
    sys.stdout = sys.stderr  # yeteneğin print'leri sonuç satırını bozmasın
    sys.dont_write_bytecode = True
    import importlib.util
    import logging

    logging.basicConfig(level=logging.INFO, stream=sys.stderr, format="%(message)s")
    try:
        from asistan.cekirdek.yetenek import Baglam, YetenekHatasi
    except Exception as e:  # program kodu okunamadı: ortam bozuk
        cikis.write(json.dumps({"tamam": False, "sinif": "kaynak", "mesaj": f"sandbox kurulamadı: {e}"}) + "\n")
        return 0
    os.chdir(is_["calisma_klasoru"])
    kanca_kur(is_)
    try:
        spec = importlib.util.spec_from_file_location("yetenek_" + is_["ad"],
                                                      os.path.join(is_["yetenek_klasoru"], "calistir.py"))
        modul = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(modul)
        baglam = Baglam(calisma_klasoru=is_["calisma_klasoru"], kademe=is_.get("kademe", "orta"),
                        gunluk=logging.getLogger("yetenek." + is_["ad"]), ayar=is_.get("ayar") or {},
                        okuma_kokleri=tuple(is_.get("okuma_kokleri") or ()))
        sonuc = modul.calistir(is_["girdi"], baglam)
        cevap = {"tamam": True, "cikti": sonuc}
    except YetenekHatasi as e:
        cevap = {"tamam": False, "sinif": e.sinif, "mesaj": e.mesaj}
    except PermissionError as e:
        cevap = {"tamam": False, "sinif": "izin", "mesaj": str(e)}
    except ModuleNotFoundError as e:
        cevap = {"tamam": False, "sinif": "eksik_bagimlilik", "mesaj": f"{e}"}
    except MemoryError:
        cevap = {"tamam": False, "sinif": "kaynak", "mesaj": "bellek yetmedi"}
    except Exception as e:
        iz = "".join(traceback.format_exception(e)).strip().splitlines()[-5:]
        cevap = {"tamam": False, "sinif": "mantik", "mesaj": f"{type(e).__name__}: {e}", "iz": "\n".join(iz)}
    try:
        satir = json.dumps(cevap, ensure_ascii=False, default=str)
    except (TypeError, ValueError) as e:
        satir = json.dumps({"tamam": False, "sinif": "mantik", "mesaj": f"çıktı JSON'a çevrilemedi: {e}"})
    cikis.write(satir + "\n")
    cikis.flush()
    return 0


if __name__ == "__main__":
    sys.exit(main())
