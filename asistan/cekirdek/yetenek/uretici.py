"""Yetenek üretme döngüsü (MIMARI §7): eksik yetenek → manifest → kod ajanı `calistir.py` + `test_<ad>.py` → sandbox
test → onay → kayıt (`kaynak: "uretildi"`, `guvenilir: false`, `sandbox: true`). En çok `TUR` (3) düzeltme turu.

Kod ajanı yönlendiricinin `kod` rolüdür (`model("kod", …)`: CLI ajanı > bulut > yerel). Üretilen dosyalar önce
`<kök>/.taslak/<ad>/`'a yazılır; testler ayrı venv'de, beyaz listeli ortamda, ağsız (izin yoksa) ve zaman aşımıyla
koşar; geçerse (ve `sor` onaylarsa) `<kök>/<ad>/`'a taşınır ve kayıt defteri onu görür. Üretilen yetenek ana süreçte
ASLA yüklenmez. `guncelle` çalışan üretilmiş yeteneği aynı döngüyle yeniler.
"""

import json
import logging
import os
import re
import shutil
import subprocess
import sys
import tempfile
from dataclasses import dataclass, field
from pathlib import Path

from .. import guvenlik
from ..araclar import komut
from . import Baglam, YetenekHatasi
from .kayit import Kayit, Yetenek, uretilen_kok

_gunluk = logging.getLogger(__name__)
TUR = 3
IZINLER = ("ag", "dosya_oku", "dosya_yaz", "dosya_sil", "komut")
TIPLER = ("string", "int", "float", "bool", "list", "dict")

MANIFEST_SEMASI = {
    "type": "object",
    "properties": {
        "aciklama": {"type": "string"},
        "girdi": {"type": "array", "items": {"type": "object", "properties": {
            "ad": {"type": "string"}, "tip": {"type": "string", "enum": list(TIPLER)}, "zorunlu": {"type": "boolean"},
            "aciklama": {"type": "string"}}, "required": ["ad", "tip", "zorunlu", "aciklama"]}},
        "cikti": {"type": "array", "items": {"type": "object", "properties": {
            "ad": {"type": "string"}, "tip": {"type": "string", "enum": list(TIPLER)}, "aciklama": {"type": "string"}},
            "required": ["ad", "tip", "aciklama"]}},
        "izinler": {"type": "array", "items": {"type": "string", "enum": list(IZINLER)}},
        "pip": {"type": "array", "items": {"type": "string"}},
        "ornekler": {"type": "array", "items": {"type": "object", "properties": {
            "girdi": {"type": "object"}, "beklenen": {"type": "string"}}, "required": ["girdi", "beklenen"]}},
    },
    "required": ["aciklama", "girdi", "cikti", "izinler", "pip", "ornekler"],
}
KOD_SEMASI = {"type": "object", "properties": {"calistir_py": {"type": "string"}, "test_py": {"type": "string"}},
              "required": ["calistir_py", "test_py"]}

MANIFEST_SISTEMI = (
    "You design a small, self-contained capability ('yetenek') for a desktop assistant. Return ONLY a JSON object: "
    "aciklama (Turkish, one sentence), girdi (input fields), cikti (output fields), izinler (least privilege: only from "
    "ag, dosya_oku, dosya_yaz, dosya_sil, komut), pip (third-party packages, prefer none), ornekler (2 examples with "
    "concrete girdi and a short 'beklenen' description). Names are snake_case ASCII.")
KOD_SISTEMI = (
    "You write Python for a sandboxed capability. Return ONLY a JSON object with calistir_py and test_py.\n"
    "calistir_py contract:\n"
    "  from asistan.cekirdek.yetenek import YetenekHatasi, gerekli\n"
    "  def calistir(girdi: dict, baglam) -> dict   # returns exactly the manifest's cikti fields\n"
    "Rules: validate inputs first (gerekli(girdi, 'alan'); raise YetenekHatasi('veri', msg)); relative file paths are "
    "under baglam.calisma_klasoru; raise YetenekHatasi('ag'|'izin'|'eksik_bagimlilik'|'veri', msg) for errors; import "
    "heavy/third-party modules inside the function; no network unless 'ag' permission; no subprocess unless 'komut'; "
    "Turkish docstring.\n"
    "test_py: unittest module named test_<ad>.py in the same folder. It must load calistir.py from its own folder "
    "(importlib.util.spec_from_file_location with os.path.dirname(__file__)), build baglam = types.SimpleNamespace("
    "calisma_klasoru=<temp dir>, kademe='orta', gunluk=logging.getLogger('t'), okuma_kokleri=(), ayar={}), create any "
    "input files in that temp dir, run every manifest example, and include at least one error-path test (missing "
    "input → YetenekHatasi). No network in tests.")


@dataclass
class Sonuc:
    yetenek: Yetenek | None
    rapor: str
    tur: int = 0
    klasor: Path | None = None  # taslak (onay bekliyorsa) ya da kalıcı klasör
    onay_bekliyor: bool = False
    dosyalar: dict = field(default_factory=dict)  # ad → içerik (arayüzde göstermek için)


def manifest_kur(ad: str, taslak: dict, zaman_asimi: int) -> dict:
    """Modelin (dizi biçimli) tasarımı → SEMALAR §1 manifesti."""
    girdi = {a["ad"]: {"tip": a["tip"], "zorunlu": bool(a.get("zorunlu")), "aciklama": a.get("aciklama", "")}
             for a in taslak.get("girdi") or [] if re.fullmatch(r"[a-z][a-z0-9_]*", str(a.get("ad", "")))}
    cikti = {a["ad"]: {"tip": a["tip"], "aciklama": a.get("aciklama", "")}
             for a in taslak.get("cikti") or [] if re.fullmatch(r"[a-z][a-z0-9_]*", str(a.get("ad", "")))}
    izinler = [i for i in dict.fromkeys(taslak.get("izinler") or []) if i in IZINLER]
    pip = [p for p in taslak.get("pip") or [] if re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._\-\[\]<>=!~,]*", str(p))]
    zorunlu = {a for a, t in girdi.items() if t["zorunlu"]}
    # örnekler manifest şemasına uymalı (kayıt defteri girdisi eksik örneği reddeder): modelin "hata örneği" atılır
    ornekler = [o for o in taslak.get("ornekler") or []
                if isinstance(o.get("girdi"), dict) and zorunlu <= set(o["girdi"]) and set(o["girdi"]) <= set(girdi)][:5]
    return {"ad": ad, "surum": "0.1.0", "aciklama": str(taslak.get("aciklama") or ad), "etiketler": ["uretildi"],
            "girdi": girdi, "cikti": cikti,
            "gereksinimler": {"pip": pip, "ikili": [], "min_kademe": "dusuk", "isletim": ["windows", "linux", "macos"],
                              "python": ">=3.12"},
            "izinler": izinler, "zaman_asimi_sn": zaman_asimi, "sandbox": True, "kaynak": "uretildi",
            "guvenilir": False, "ornekler": ornekler}


def _yaz(klasor: Path, ad: str, manifest: dict, kod: dict) -> dict:
    klasor.mkdir(parents=True, exist_ok=True)
    dosyalar = {"manifest.json": json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
                "calistir.py": str(kod.get("calistir_py") or ""), f"test_{ad}.py": str(kod.get("test_py") or "")}
    for isim, icerik in dosyalar.items():
        (klasor / isim).write_text(icerik, encoding="utf-8")
    return dosyalar


def testi_kos(yetenek: Yetenek, python: str | None = None, kutuphane_yollari=(), ortamlar: Path | None = None) -> tuple[bool, str]:
    """`test_<ad>.py` yeteneğin ayrı venv'inde, beyaz listeli ortamda, ağ izni yoksa ağsız, zaman aşımıyla.
    (geçti mi, çıktı son satırları)."""
    from .calistirici import _agsiz_onek, ortam_koku, venv_python

    python = python or sys.executable
    exe = venv_python(yetenek.ad, python, ortamlar or ortam_koku())
    test = yetenek.klasor / f"test_{yetenek.ad}.py"
    if not test.is_file():
        return False, "test dosyası yok"
    gecici = tempfile.mkdtemp(prefix=f"yetenek-test-{yetenek.ad}-")
    koku = Path(__file__).resolve().parents[3]
    ortam = komut.guvenli_ortam(os.environ, ek={"HOME": gecici, "TMPDIR": gecici, "PYTHONDONTWRITEBYTECODE": "1",
                                                "PYTHONNOUSERSITE": "1", "PYTHONIOENCODING": "utf-8",
                                                "PYTHONPATH": os.pathsep.join([str(koku), *map(str, kutuphane_yollari)])})
    onek = () if "ag" in yetenek.izinler else _agsiz_onek()
    sure = max(10, guvenlik.sandbox_zaman_asimi() * 2)
    try:
        p = subprocess.run([*onek, exe, "-B", "-m", "unittest", "-v", str(test)], cwd=str(yetenek.klasor), env=ortam,
                           capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=sure,
                           stdin=subprocess.DEVNULL)
    except subprocess.TimeoutExpired:
        return False, f"test zaman aşımı ({sure} sn)"
    finally:
        shutil.rmtree(gecici, ignore_errors=True)
    cikti = (p.stdout + "\n" + p.stderr).strip()
    return p.returncode == 0, "\n".join(cikti.splitlines()[-25:])


def ornekleri_kos(yetenek: Yetenek, baglam: Baglam, python: str | None = None, kutuphane_yollari=()) -> tuple[bool, str]:
    """Manifest örnekleri gerçek sandbox'ta (`calistirici.calistir`): çıktı şemaya uymalı."""
    from . import calistirici

    for i, ornek in enumerate(yetenek.manifest.get("ornekler") or [], 1):
        try:
            calistirici.calistir(yetenek, dict(ornek.get("girdi") or {}), baglam, python=python,
                                 kutuphane_yollari=kutuphane_yollari)
        except YetenekHatasi as e:
            if e.sinif == "veri" and "beklenen" in ornek and re.search(r"hata|error|veri", str(ornek["beklenen"]), re.I):
                continue  # örnek zaten hata bekliyor
            return False, f"örnek {i} ({ornek.get('girdi')}): ({e.sinif}) {e.mesaj}"
    return True, ""


def uret(ad: str, aciklama: str, model, *, kok: Path | None = None, python: str | None = None, sor=None, arac=None,
         kutuphane_yollari=(), kademe: str = "orta", tur: int = TUR, mevcut: dict | None = None,
         calisma_klasoru: str = "") -> Sonuc:
    """Yeteneği üretir. `model(rol, mesajlar, sistem, sema)` → Cevap; `sor(ozet) -> bool` kayıt onayı (None: taslak
    kalır, `onay_bekliyor`); `arac(ad, args)` eksik pip paketini izin hattından kurmak için (None: kurulmaz);
    `mevcut`: güncellenecek yeteneğin dosyaları (guncelle)."""
    if not re.fullmatch(r"[a-z][a-z0-9_]{1,40}", ad or ""):
        return Sonuc(None, f"geçersiz yetenek adı: {ad!r}")
    kok = Path(kok) if kok else uretilen_kok()
    taslak = kok / ".taslak" / ad
    shutil.rmtree(taslak, ignore_errors=True)
    zaman = min(30, guvenlik.sandbox_zaman_asimi())
    istem = f"Capability name: {ad}\nWhat it must do: {aciklama}"
    if mevcut:
        istem += "\n\nExisting version (update it, keep the contract):\n" + "\n".join(
            f"--- {k} ---\n{v[:6000]}" for k, v in mevcut.items())
    c = model("planlama", [{"role": "user", "content": istem}], MANIFEST_SISTEMI, MANIFEST_SEMASI)
    if not c.veri:
        return Sonuc(None, "manifest tasarlanamadı: " + "; ".join(c.hatalar[:3]))
    manifest = manifest_kur(ad, c.veri, zaman)
    if not manifest["cikti"]:
        return Sonuc(None, "manifest tasarlanamadı: çıktı alanı yok")
    mesajlar = [{"role": "user", "content": f"Manifest:\n{json.dumps(manifest, ensure_ascii=False, indent=1)}\n\n"
                                            f"Task description: {aciklama}"}]
    if mevcut:
        mesajlar[0]["content"] += "\n\nExisting files:\n" + "\n".join(f"--- {k} ---\n{v[:6000]}" for k, v in mevcut.items())
    rapor, dosyalar, yetenek = "", {}, None
    for deneme in range(1, max(1, tur) + 1):
        c = model("kod", mesajlar, KOD_SISTEMI, KOD_SEMASI)
        if not c.veri:
            rapor = f"tur {deneme}: kod üretilemedi: " + "; ".join(c.hatalar[:3])
            mesajlar += [{"role": "assistant", "content": c.metin or "(boş)"},
                         {"role": "user", "content": "Return the JSON object with calistir_py and test_py only."}]
            continue
        dosyalar = _yaz(taslak, ad, manifest, c.veri)
        kayit = Kayit([taslak.parent], kademe=kademe, kutuphane_yollari=kutuphane_yollari)
        yetenek = kayit.getir(ad)
        if yetenek is not None and not yetenek.aktif and "Python paketi kurulu değil" in yetenek.neden and arac:
            from . import yukleyici

            try:
                yukleyici.kur("pip:" + yetenek.neden.split(":")[-1].strip(), arac, f"{ad} yeteneği için")
                yetenek = kayit.yenile() and kayit.getir(ad)
            except YetenekHatasi as e:
                rapor = f"bağımlılık kurulamadı: {e.mesaj}"
                break
        if yetenek is None or not yetenek.aktif:
            hata = (yetenek.neden if yetenek else "manifest okunamadı") + ("; " + "; ".join(yetenek.hatalar[:3]) if yetenek and yetenek.hatalar else "")
            rapor = f"tur {deneme}: yetenek kayda giremedi: {hata}"
        else:
            gecti, cikti = testi_kos(yetenek, python, kutuphane_yollari)
            if gecti:
                baglam = Baglam(calisma_klasoru=calisma_klasoru or tempfile.mkdtemp(prefix="yetenek-ornek-"),
                                kademe=kademe)
                gecti, cikti = ornekleri_kos(yetenek, baglam, python, kutuphane_yollari)
            if gecti:
                rapor = f"tur {deneme}: testler ve örnekler geçti"
                break
            rapor = f"tur {deneme}: test geçmedi:\n{cikti}"
        _gunluk.info("yetenek üretimi %s: %s", ad, rapor.splitlines()[0])
        mesajlar += [{"role": "assistant", "content": c.metin or ""},
                     {"role": "user", "content": f"The sandbox test failed. Fix the code and tests:\n{rapor[-3000:]}\n"
                                                 "Return the full JSON object again."}]
        yetenek = None
    if yetenek is None:
        _taslak_sil(taslak)
        return Sonuc(None, f"yapamadım: {rapor}", tur)
    ozet = (f"Yeni yetenek: {ad} — {manifest['aciklama']}\nizinler: {', '.join(manifest['izinler']) or 'yok'} · "
            f"pip: {', '.join(manifest['gereksinimler']['pip']) or 'yok'} · sandbox, güvenilmez (ilk "
            f"{guvenlik.politika()['uretilen_sandbox_calistirma']} çalıştırma sandbox'ta)\n\n--- calistir.py ---\n"
            f"{dosyalar['calistir.py'][:4000]}")
    if sor is None:
        return Sonuc(yetenek, rapor, tur, taslak, onay_bekliyor=True, dosyalar=dosyalar)
    if not sor(ozet):
        _taslak_sil(taslak)
        return Sonuc(None, "kullanıcı yeni yeteneği onaylamadı", tur)
    return Sonuc(kaydet(taslak, kok, kademe, kutuphane_yollari), rapor, tur, kok / ad, dosyalar=dosyalar)


def _taslak_sil(taslak: Path) -> None:
    shutil.rmtree(taslak, ignore_errors=True)
    try:
        taslak.parent.rmdir()  # `.taslak` boş kaldıysa
    except OSError:
        pass


def kaydet(taslak: Path, kok: Path, kademe: str = "orta", kutuphane_yollari=()) -> Yetenek | None:
    """Onaylanan taslağı kalıcı klasöre taşır (varsa eski sürüm `<ad>.eski` olarak yedeklenir)."""
    hedef = kok / taslak.name
    if hedef.exists():
        yedek = kok / f"{taslak.name}.eski"
        shutil.rmtree(yedek, ignore_errors=True)
        hedef.rename(yedek)
    shutil.move(str(taslak), str(hedef))
    try:
        (kok / ".taslak").rmdir()
    except OSError:
        pass
    return Kayit([kok], kademe=kademe, kutuphane_yollari=kutuphane_yollari).getir(taslak.name)


def guncelle(ad: str, istek: str, model, *, kok: Path | None = None, **k) -> Sonuc:
    """Çalışan üretilmiş yeteneği yeniler: mevcut dosyalar bağlam olur, aynı döngü (test → onay → kayıt)."""
    kok = Path(kok) if kok else uretilen_kok()
    klasor = kok / ad
    if not (klasor / "manifest.json").is_file():
        return Sonuc(None, f"güncellenecek üretilmiş yetenek yok: {ad}")
    try:
        if json.loads((klasor / "manifest.json").read_text(encoding="utf-8")).get("kaynak") != "uretildi":
            return Sonuc(None, f"{ad} üretilmiş bir yetenek değil; yalnızca üretilmişler güncellenir")
    except ValueError:
        pass
    mevcut = {p.name: p.read_text(encoding="utf-8", errors="replace") for p in klasor.iterdir()
              if p.suffix in (".py", ".json") and p.is_file()}
    return uret(ad, istek, model, kok=kok, mevcut=mevcut, **k)
