"""Yetenek kayıt defteri: `*/manifest.json` tarama, doğrulama, aktif/pasif listeleme (MIMARI §6).

Pasif yetenek planlayıcıya çağrılabilir olarak gitmez; "var ama kullanılamıyor" diye nedeniyle listelenir (anlayıcı
onu eksik yetenek olarak söyleyebilir). Pasif nedenleri: manifest şemaya ya da ek kurallara uymuyor (ad = klasör adı,
`calistir.py` içinde `calistir` işlevi, örnek girdiler şemaya uyar), gereksinim karşılanmıyor (pip paketi / ikili /
kademe / işletim sistemi / Python sürümü), yerleşik yeteneğin kendi hazırlık denetimi (`hazir_mi()`), güven kuralı:
programla gelmeyen yetenek "yerleşik" olamaz ve sandbox dışında çalışamaz.

Kök sırası önemlidir: aynı ad ikinci kez görülürse sonraki pasif olur (üretilen yetenek yerleşiği ezemez).
"""

import ast
import importlib.util
import json
import re
import shutil
import sys
from dataclasses import dataclass, field
from pathlib import Path

from .. import semalar
from . import nesne_semasi

YERLESIK_KOK = Path(__file__).resolve().parents[2] / "yetenekler"  # asistan/yetenekler (programla gelir)
KADEME_SIRASI = {"dusuk": 0, "orta": 1, "sunucu": 1, "yuksek": 2}
_ISLETIM = {"linux": "linux", "win32": "windows", "darwin": "macos"}


def uretilen_kok() -> Path:
    """Üretilen / katalogdan gelen yetenekler (K6): `DATA_DIR/yetenekler`."""
    from ..ayar import DATA_DIR

    return DATA_DIR / "yetenekler"


@dataclass
class Yetenek:
    ad: str
    klasor: Path
    manifest: dict = field(default_factory=dict)
    aktif: bool = False
    neden: str = ""  # pasifse neden (Türkçe, tek satır)
    hatalar: list = field(default_factory=list)  # manifest hataları
    yerlesik_kokte: bool = False

    @property
    def izinler(self) -> list[str]:
        return list(self.manifest.get("izinler") or [])

    @property
    def sandbox(self) -> bool:
        return bool(self.manifest.get("sandbox", True))

    @property
    def kaynak(self) -> str:
        return str(self.manifest.get("kaynak") or "")

    @property
    def guvenilir(self) -> bool:
        return bool(self.manifest.get("guvenilir"))

    @property
    def aciklama(self) -> str:
        return str(self.manifest.get("aciklama") or "")

    @property
    def zaman_asimi(self) -> int:
        return int(self.manifest.get("zaman_asimi_sn") or 30)

    @property
    def salt_okur(self) -> bool:
        """Yalnızca bilgi okur (doğrulayıcı dosya kanıtı aramaz)."""
        return not {"dosya_yaz", "dosya_sil", "komut"} & set(self.izinler)

    def girdi_semasi(self) -> dict:
        return nesne_semasi(self.manifest.get("girdi") or {})

    def cikti_semasi(self) -> dict:
        return nesne_semasi(self.manifest.get("cikti") or {})

    def risk(self) -> str:
        """İzin hattının risk sınıfı (`registry.RISKS`): programla gelmeyen ya da güvenilmeyen kod her seferinde
        onaylanır; komut / silme / ağ (okuduğunu dışarı gönderebilir; MIMARI §10 `ag = "sor"`) / anahtar da öyle;
        dosya yazma değişiklik; gerisi okuma."""
        izin = set(self.izinler)
        if self.kaynak != "yerlesik" or not self.guvenilir or izin & {"komut", "dosya_sil", "ag"} \
                or any(i.startswith("anahtar:") for i in izin):
            return "calistirir"
        return "yazar" if "dosya_yaz" in izin else "okur"

    def ozet(self) -> dict:
        """Arayüz ve komut satırı için düz sözlük."""
        m = self.manifest
        return {"ad": self.ad, "surum": m.get("surum", ""), "aciklama": self.aciklama, "aktif": self.aktif,
                "neden": self.neden, "izinler": self.izinler, "kaynak": self.kaynak, "guvenilir": self.guvenilir,
                "sandbox": self.sandbox, "etiketler": list(m.get("etiketler") or []), "klasor": str(self.klasor),
                "hatalar": list(self.hatalar), "girdi": dict(m.get("girdi") or {}),
                "ornekler": list(m.get("ornekler") or []), "min_kademe": (m.get("gereksinimler") or {}).get(
                    "min_kademe", "dusuk")}


# ---------------------------------------------------------------- doğrulama

def manifest_hatalari(manifest, klasor: Path) -> list[str]:
    """Şema + şemanın anlatamadığı kurallar. Boş liste = geçerli."""
    if not isinstance(manifest, dict):
        return ["manifest bir JSON nesnesi değil"]
    hatalar = semalar.dogrula(manifest, semalar.yukle("manifest"))
    if hatalar:
        return hatalar
    if manifest["ad"] != klasor.name:
        hatalar.append(f"ad ({manifest['ad']}) klasör adıyla ({klasor.name}) aynı olmalı")
    kod = klasor / "calistir.py"
    if not kod.is_file():
        hatalar.append("calistir.py yok")
    else:
        try:
            agac = ast.parse(kod.read_text(encoding="utf-8"))
        except (SyntaxError, UnicodeDecodeError, ValueError) as e:
            hatalar.append(f"calistir.py derlenmiyor: {e}")
        else:
            if not any(isinstance(d, ast.FunctionDef) and d.name == "calistir" for d in agac.body):
                hatalar.append("calistir.py içinde `calistir(girdi, baglam)` işlevi yok")
    sema = nesne_semasi(manifest.get("girdi") or {})
    for i, ornek in enumerate(manifest.get("ornekler") or []):
        hatalar += [f"ornekler[{i}]: {h}" for h in semalar.dogrula(ornek["girdi"], sema, _yol="girdi")]
    return hatalar


def _surum(metin: str) -> tuple:
    return tuple(int(x) for x in re.findall(r"\d+", metin)[:4])


def surum_uyar(var: str, kosul: str) -> bool:
    """`kosul` ">=0.27,<1" gibi; boşsa her sürüm uyar."""
    for parca in [p.strip() for p in kosul.split(",") if p.strip()]:
        m = re.match(r"(==|>=|<=|!=|~=|>|<)\s*(.+)", parca)
        if not m:
            continue
        op, hedef = m.group(1), _surum(m.group(2))
        v = _surum(var)
        n = max(len(v), len(hedef))
        v, hedef = v + (0,) * (n - len(v)), hedef + (0,) * (n - len(hedef))
        tamam = {"==": v == hedef, ">=": v >= hedef, "<=": v <= hedef, "!=": v != hedef, ">": v > hedef,
                 "<": v < hedef, "~=": v >= hedef}[op]
        if not tamam:
            return False
    return True


def paket_surumu(ad: str, yollar: list[str]) -> str | None:
    """Kurulu dağıtımın sürümü (programın Python'u + ajan kütüphane klasörleri); yoksa None."""
    import importlib.metadata as md

    ad_n = re.sub(r"[-_.]+", "-", ad).lower()
    for d in md.distributions(path=[*sys.path, *[str(y) for y in yollar]]):
        isim = re.sub(r"[-_.]+", "-", (d.metadata["Name"] or "")).lower()
        if isim == ad_n:
            return d.version
    return None


def gereksinim_eksigi(manifest: dict, kademe: str, yollar: list[str]) -> str:
    """Karşılanmayan ilk gereksinim (Türkçe); hepsi tamamsa boş."""
    g = manifest.get("gereksinimler") or {}
    isletim = _ISLETIM.get(sys.platform, sys.platform)
    if g.get("isletim") and isletim not in g["isletim"]:
        return f"bu işletim sisteminde çalışmaz ({isletim})"
    if g.get("python") and not surum_uyar(".".join(map(str, sys.version_info[:3])), g["python"]):
        return f"Python {g['python']} gerekiyor"
    en_az = g.get("min_kademe") or "dusuk"
    if KADEME_SIRASI.get(kademe, 1) < KADEME_SIRASI.get(en_az, 0):
        return f"en az '{en_az}' kademe gerekiyor (bu bilgisayar: {kademe})"
    for ikili in g.get("ikili") or []:
        if not shutil.which(ikili):
            return f"'{ikili}' programı kurulu değil"
    for paket in g.get("pip") or []:
        m = re.match(r"([A-Za-z0-9][A-Za-z0-9._\-]*)(\[[^\]]*\])?\s*(.*)", paket)
        ad, kosul = m.group(1), m.group(3)
        surum = paket_surumu(ad, yollar)
        if surum is None:
            return f"Python paketi kurulu değil: {ad}"
        if not surum_uyar(surum, kosul):
            return f"{ad} {surum} kurulu, {kosul} gerekiyor"
    return ""


_MODULLER: dict[str, tuple[float, object]] = {}


def modul_yukle(yetenek: Yetenek):
    """Yerleşik yeteneğin `calistir.py`'si (süreç içi). Sandbox yeteneğinin kodu ana süreçte ASLA yüklenmez."""
    if not (yetenek.yerlesik_kokte and not yetenek.sandbox):
        raise PermissionError(f"{yetenek.ad}: yalnızca yerleşik, sandbox dışı yetenek süreç içinde yüklenir")
    yol = yetenek.klasor / "calistir.py"
    anahtar, zaman = str(yol), yol.stat().st_mtime
    onbellek = _MODULLER.get(anahtar)
    if onbellek and onbellek[0] == zaman:
        return onbellek[1]
    spec = importlib.util.spec_from_file_location(f"asistan_yetenek_{yetenek.ad}", yol)
    modul = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(modul)
    _MODULLER[anahtar] = (zaman, modul)
    return modul


# ---------------------------------------------------------------- kayıt

class Kayit:
    """`kokler`: taranacak klasörler (varsayılan: yerleşik + üretilen). `kademe`: gereksinim denetimi için (varsayılan
    `profil.kademe()`). `kutuphane_yollari`: pip gereksinimi aranırken programın ek kütüphane klasörleri."""

    def __init__(self, kokler: list[Path] | None = None, kademe: str | None = None,
                 kutuphane_yollari: list | tuple = ()):
        self.kokler = [Path(k) for k in kokler] if kokler is not None else [YERLESIK_KOK, uretilen_kok()]
        self._kademe = kademe
        self.kutuphane_yollari = [str(y) for y in kutuphane_yollari]
        self._liste: list[Yetenek] | None = None

    @property
    def kademe(self) -> str:
        if self._kademe is None:
            from .. import profil

            self._kademe = profil.kademe()
        return self._kademe

    def yenile(self) -> list[Yetenek]:
        self._liste = None
        return self.tara()

    def tara(self) -> list[Yetenek]:
        if self._liste is not None:
            return self._liste
        liste: list[Yetenek] = []
        gorulen: set[str] = set()
        for kok in self.kokler:
            if not kok.is_dir():
                continue
            yerlesik = kok.resolve() == YERLESIK_KOK.resolve()
            for klasor in sorted(p for p in kok.iterdir() if p.is_dir() and (p / "manifest.json").exists()):
                y = self._oku(klasor, yerlesik)
                if y.ad in gorulen and y.aktif:
                    y.aktif, y.neden = False, "aynı adla başka bir yetenek önce kayıtlı"
                gorulen.add(y.ad)
                liste.append(y)
        self._liste = liste
        return liste

    def _oku(self, klasor: Path, yerlesik: bool) -> Yetenek:
        y = Yetenek(klasor.name, klasor, yerlesik_kokte=yerlesik)
        try:
            y.manifest = json.loads((klasor / "manifest.json").read_text(encoding="utf-8"))
        except (OSError, ValueError) as e:
            y.hatalar, y.neden = [f"manifest okunamadı: {e}"], "manifest bozuk"
            return y
        y.hatalar = manifest_hatalari(y.manifest, klasor)
        if y.hatalar:
            y.neden = "manifest geçersiz: " + y.hatalar[0]
            return y
        y.ad = y.manifest["ad"]
        if not yerlesik and y.kaynak == "yerlesik":
            y.neden = "programla gelmeyen yetenek 'yerlesik' olamaz"
            return y
        if not y.sandbox and not (yerlesik and y.kaynak == "yerlesik"):
            y.neden = "yalnızca yerleşik yetenek sandbox dışında çalışabilir"
            return y
        y.neden = gereksinim_eksigi(y.manifest, self.kademe, self.kutuphane_yollari)
        if not y.neden and not y.sandbox:  # yerleşik: kendi hazırlık denetimi (ör. tarayıcı motoru kurulu mu)
            try:
                hazir = getattr(modul_yukle(y), "hazir_mi", None)
                y.neden = str(hazir() or "") if hazir else ""
            except Exception as e:  # yüklenemeyen yerleşik yetenek pasif kalır, program açılır
                y.neden = f"calistir.py yüklenemedi: {type(e).__name__}: {e}"
        y.aktif = not y.neden
        return y

    # ---- sorgular
    def getir(self, ad: str) -> Yetenek | None:
        return next((y for y in self.tara() if y.ad == ad and y.aktif), None) or \
            next((y for y in self.tara() if y.ad == ad), None)

    def aktifler(self) -> list[Yetenek]:
        return [y for y in self.tara() if y.aktif]

    def pasifler(self) -> list[Yetenek]:
        return [y for y in self.tara() if not y.aktif]

    def listele(self) -> list[dict]:
        return [y.ozet() for y in self.tara()]

    def planlayici_listesi(self) -> list[dict]:
        """Görev motorunun `Yetenekler.listele()` biçimi — yalnızca manifestlerden, elle liste yok."""
        return [{"ad": y.ad, "aciklama": y.aciklama, "girdi_semasi": y.girdi_semasi(), "salt_okur": y.salt_okur}
                for y in self.aktifler()]
