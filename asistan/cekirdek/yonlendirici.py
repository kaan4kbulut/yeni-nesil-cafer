"""Model yönlendirici: her iş için "hangi sağlayıcı, hangi model, neden" kararı (docs/MIMARI.md §4).

Kural sırası: çevrimdışı → gizlilik → görev türü (rol) → kademe → yedekleme zinciri. Sağlık sonuçları 5 dk
önbellekte; sağlıksız sağlayıcı havuzdan düşer. Bulut için görev başına ve günlük token tavanı (`ayar.toml → [bulut]`);
aşılınca karar `onay_gerekli` taşır, soruyu çağıran `permissions.bulut_tavani` ile sorar.

Karar saf işlevlerdedir (`karar`, `yonetici_karari`, `Zincir`): aday listesi ve `Durum` alır, sahte sağlayıcılarla
sınanır. Adayları `adaylar()` programın kadrosundan (roster, kartlar, bağlantılar, Claude Code) toplar. Yönetici seçimi
bu dosyadadır; `roster.manager_for` ve `roster.stronger` buraya devreder (ikinci bir seçim kodu yok).
"""

import contextlib
import json
import logging
import os
import threading
import time
from dataclasses import dataclass, field, replace
from datetime import date

from . import ayar
from .saglayici.temel import Saglik

_gunluk = logging.getLogger(__name__)

GIZLILIK_MODLARI = ("yerel", "karma", "bulut")
POLITIKALAR = ("otomatik", "yerel", "bulut")  # yönetici modeli politikası (eski Aşama 2)
ROLLER = ("hizli", "yonetici", "kod")
GOREV_ROLU = {  # MIMARI §4 madde 3
    "sohbet": "hizli", "ozet": "hizli", "siniflandirma": "hizli",
    "planlama": "yonetici", "analiz": "yonetici", "cok_adimli": "yonetici",
    "kod_uretimi": "kod", "yetenek_uretimi": "kod",
}
ROL_ADI = {"hizli": "hızlı", "yonetici": "yönetici", "kod": "kod"}
GIZLILIK_ADI = {"yerel": "yalnızca yerel", "karma": "karma", "bulut": "bulut öncelikli"}
POLITIKA_ADI = {"otomatik": "otomatik (en güçlü erişilebilir)", "yerel": "yalnızca yerel", "bulut": "bulut öncelikli"}

SAGLIK_SN = 300  # MIMARI §4 madde 6
SAGLIKSIZ_SN = 60  # sağlıksız sonuç daha kısa: Ollama yeniden açılınca 5 dk buluta gidilmesin (NOTLAR K3)
BASARISIZ_ESIGI = 2  # aynı modelde bu kadar başarısızlık → zincirde bir üst basamak
EXTRA_GIZLILIK = "gizlilik"  # Settings.extra anahtarları (arayüzün yazdığı; ayar.toml önce gelir)
EXTRA_POLITIKA = "yonetici_politikasi"
EXTRA_KAYNAK = "istek_kaynagi"  # "kuyruk" | "zamanli" | "komut": CLI ajanları seçilmez (CLAUDE.md)


# ---------------------------------------------------------------- ayarlar

def _extra(ayarlar) -> dict:
    extra = getattr(ayarlar, "extra", None)
    return extra if isinstance(extra, dict) else {}


def gizlilik(ayarlar=None) -> str:
    """`yerel | karma | bulut`: ayar.toml / CAFER_GIZLILIK_MOD → arayüz (`extra["gizlilik"]`) → varsayılan."""
    acik = ayar.acik_degerler().get("gizlilik.mod")
    if acik in GIZLILIK_MODLARI:
        return acik
    secili = _extra(ayarlar).get(EXTRA_GIZLILIK)
    return secili if secili in GIZLILIK_MODLARI else ayar.VARSAYILAN["gizlilik.mod"]


def gizlilik_kilitli() -> bool:
    """Gizlilik ayar.toml ya da ortamla verildiyse arayüzdeki kutu kapalıdır."""
    return ayar.acik_degerler().get("gizlilik.mod") in GIZLILIK_MODLARI


def politika(ayarlar=None) -> str:
    """Yönetici politikası; gizlilik `yerel` iken her zaman `yerel`."""
    if gizlilik(ayarlar) == "yerel":
        return "yerel"
    secili = _extra(ayarlar).get(EXTRA_POLITIKA)
    return secili if secili in POLITIKALAR else "otomatik"


def kullanici_istegi(ayarlar=None) -> bool:
    """İstek kullanıcının sohbetinden mi geliyor? Kuyruk, zamanlanmış iş ve görev motoru (komut satırı, Görevler
    penceresi) sohbet değil: CLI ajanı seçilmez."""
    return _extra(ayarlar).get(EXTRA_KAYNAK) not in ("kuyruk", "zamanli", "komut")


# ---------------------------------------------------------------- veri

@dataclass
class Aday:
    """Seçilebilir bir model. `puan` roster'ın güç puanı; `arac` programın araç sınavı (0/1/2, bulutta 2)."""

    saglayici: str  # "ollama", "claude", "api:<id>", "cli:<ad>"
    model: str
    yerel: bool = False
    puan: float = 0.0
    arac: int | None = None
    plan: bool | None = None  # kartın plan sınavı (None: bilinmiyor)
    sansursuz: bool = False
    boyut_gb: float = 0.0  # yerelde bellek ihtiyacı (bilinmiyorsa 0)
    yetenekler: set = field(default_factory=set)

    @property
    def anahtar(self) -> tuple[str, str]:
        return self.saglayici, self.model

    @property
    def cli(self) -> bool:
        return self.saglayici.startswith("cli:")

    @property
    def ucretli(self) -> bool:
        """Token başına ücretli bulut (CLI ajanı kullanıcının aboneliğiyle çalışır, sayılmaz)."""
        return not self.yerel and not self.cli

    def sigar(self, vram_gb: float) -> bool:
        return not self.yerel or not vram_gb or not self.boyut_gb or self.boyut_gb <= vram_gb


@dataclass
class Durum:
    """Kararı etkileyen ortam: ağ, gizlilik, kademe, sansürsüz mod, isteğin kaynağı, kart belleği, bulut tavanı."""

    cevrimici: bool = True
    gizlilik: str = "karma"
    kademe: str = "orta"
    politika: str = "otomatik"
    sansursuz: bool = False
    kullanici_istegi: bool = True
    vram_gb: float = 0.0
    tavan: str = ""  # boş değilse bulut tavanı aşıldı (kullanıcıya gösterilecek neden)
    hiz: dict = field(default_factory=dict)  # model → tok/sn (profil.json → benchmark, K7); rol hızlı buna bakar


@dataclass
class Secim:
    """Yönlendiricinin kararı. `sozluk()` görev planına (`adimlar[i].secim`), `etiket()` arayüze gider."""

    saglayici: str | None
    model: str | None
    neden: str
    rol: str = ""
    zincir: list = field(default_factory=list)  # [(sağlayıcı, model)]: başarısızlıkta sırayla denenecekler
    bekleyen: bool = False  # çevrimdışı ve yerel model yok: istek bekler
    parcala: bool = False  # düşük kademe, bulut yok: görev küçük parçalara bölünüp hızlı modelle denenir
    onay_gerekli: str = ""  # bulut tavanı aşıldı: çağıran kullanıcıya sorar
    uyari: str = ""

    @property
    def anahtar(self) -> tuple[str, str] | None:
        return (self.saglayici, self.model) if self.saglayici else None

    def sozluk(self) -> dict:
        return {"saglayici": self.saglayici, "model": self.model, "neden": self.neden}

    def etiket(self) -> str:
        if not self.saglayici:
            return f"model yok — neden: {self.neden}"
        return f"{self.saglayici}/{self.model} — neden: {self.neden}"


# ---------------------------------------------------------------- sağlık (5 dk önbellek)

def _saglik_sorgu(ad: str, ayarlar=None) -> Saglik:
    """Sağlayıcı düzeyinde sağlık (model sorulmaz). Ücretli çağrı yapmaz. `ayarlar` yoksa kayıtlı ayarlar."""
    from ..connections import load_connections
    from .saglayici import bul
    from .saglayici.cli_ajan import CliAjanSaglayici
    from .saglayici.ollama import OllamaSaglayici

    ayarlar = ayarlar if hasattr(ayarlar, "ollama_url") else ayar.Settings.load()
    if ad == "ollama":
        return OllamaSaglayici(ayarlar.ollama_url.rstrip("/"), "").saglik()
    if ad.startswith("cli:"):
        return CliAjanSaglayici(ad, "").saglik()
    if ad.startswith("api:"):
        conn = next((c for c in load_connections() if c.id == ad[4:]), None)
        if conn is None:
            return Saglik(False, "bağlantı silinmiş")
        return Saglik(True) if conn.usable else Saglik(False, f"{conn.name}: anahtar yok ya da reddedildi")
    return bul(ad, ayarlar).saglik()


class SaglikOnbellegi:
    """`saglik()` sonuçları: iyi sonuç 5 dk, sağlıksız sonuç 1 dk saklanır. Çağrı hatası `bildir` ile işlenir."""

    def __init__(self, sorgu=_saglik_sorgu, sure: float = SAGLIK_SN, sagliksiz_sure: float = SAGLIKSIZ_SN,
                 saat=time.monotonic):
        self.sorgu, self.sure, self.sagliksiz_sure, self.saat = sorgu, sure, sagliksiz_sure, saat
        self._kayit: dict[str, tuple[float, Saglik]] = {}
        self._kilit = threading.Lock()

    def _gecerli(self, ad: str) -> Saglik | None:
        kayit = self._kayit.get(ad)
        if kayit is None:
            return None
        zaman, sonuc = kayit
        return sonuc if self.saat() - zaman < (self.sure if sonuc.iyi else self.sagliksiz_sure) else None

    def sor(self, ad: str, ayarlar=None) -> Saglik:
        """Önbellekte geçerli sonuç varsa o; yoksa sağlayıcıya sorulur (`ayarlar`: Ollama adresi buradan)."""
        with self._kilit:
            sonuc = self._gecerli(ad)
        if sonuc is not None:
            return sonuc
        try:
            sonuc = self.sorgu(ad, ayarlar)
        except Exception as e:  # sağlık sorusu programı durdurmaz
            sonuc = Saglik(False, f"{type(e).__name__}: {e}"[:200])
        with self._kilit:
            self._kayit[ad] = (self.saat(), sonuc)
        return sonuc

    def iyi(self, ad: str) -> bool:
        return self.sor(ad).iyi

    def bilinen_sagliksiz(self, ad: str) -> Saglik | None:
        """Sormadan: önbellekte sağlıksız görünüyorsa sonucu (aday listesi zaten canlı olanlardan kurulur)."""
        with self._kilit:
            sonuc = self._gecerli(ad)
        return sonuc if sonuc is not None and not sonuc.iyi else None

    def bildir(self, ad: str, iyi: bool, neden: str = "") -> None:
        """Gerçek çağrıda görülen durum (401, bağlantı hatası, zaman aşımı) önbelleğe yazılır."""
        with self._kilit:
            self._kayit[ad] = (self.saat(), Saglik(iyi, neden))

    def temizle(self) -> None:
        with self._kilit:
            self._kayit.clear()


SAGLIK = SaglikOnbellegi()


# ---------------------------------------------------------------- bulut harcaması ve tavan

_gorev = threading.local()  # bu iş parçacığındaki İSTEĞİN görev kimliği (Manager: gorev_basla() her istekte)
_sayaclar: dict[str, dict] = {}  # görev kimliği → {"token": int, "onay": bool}; iş parçacığından bağımsız
_sayac_kilidi = threading.Lock()
_defter_kilidi = threading.Lock()


def _defter_yolu():
    return ayar.DATA_DIR / "bulut_harcama.json"


@contextlib.contextmanager
def _dosya_kilidi(yol):
    """Süreçler arası kilit (CLI + masaüstü aynı anda yazabilir): POSIX `flock`, Windows `msvcrt.locking`."""
    yol.parent.mkdir(parents=True, exist_ok=True)
    with open(yol, "a+b") as f:
        try:
            if os.name == "nt":
                import msvcrt

                f.seek(0)
                msvcrt.locking(f.fileno(), msvcrt.LK_LOCK, 1)
            else:
                import fcntl

                fcntl.flock(f.fileno(), fcntl.LOCK_EX)
        except OSError:
            pass  # kilitlenemeyen dosya sistemi: süreç içi kilit yine var
        try:
            yield
        finally:
            try:
                if os.name == "nt":
                    f.seek(0)
                    msvcrt.locking(f.fileno(), msvcrt.LK_UNLCK, 1)
                else:
                    fcntl.flock(f.fileno(), fcntl.LOCK_UN)
            except OSError:
                pass


def _defter() -> dict:
    try:
        veri = json.loads(_defter_yolu().read_text(encoding="utf-8"))
        return veri if isinstance(veri, dict) else {}
    except (OSError, ValueError):
        return {}


def _kimlik(gorev_id: str | None) -> str:
    """Sayaç anahtarı: verilen görev kimliği; yoksa bu iş parçacığındaki isteğin kimliği; o da yoksa ortak kova."""
    return gorev_id if gorev_id is not None else getattr(_gorev, "kimlik", "")


def gorev_basla(gorev_id: str | None = None) -> str:
    """Yeni istek/görev: sayaç sıfırlanır, tavan onayı yeniden sorulur. Kimlik verilmezse bu iş parçacığı için
    üretilir (Manager yolu); görev motoru kendi görev kimliğini verir. Kimliği döndürür."""
    kimlik = gorev_id or f"istek-{threading.get_ident()}-{time.monotonic_ns()}"
    _gorev.kimlik = kimlik
    with _sayac_kilidi:
        _sayaclar[kimlik] = {"token": 0, "onay": False}
        if len(_sayaclar) > 500:  # eski istekler birikmesin
            for eski in list(_sayaclar)[:-200]:
                _sayaclar.pop(eski, None)
    return kimlik


def gorev_token(gorev_id: str | None = None) -> int:
    with _sayac_kilidi:
        return int((_sayaclar.get(_kimlik(gorev_id)) or {}).get("token", 0))


def gunluk_token(gun: str | None = None) -> int:
    return int(_defter().get(gun or date.today().isoformat(), 0))


def harcama_ekle(saglayici: str, token: int, gorev_id: str | None = None) -> None:
    """Ücretli bulut çağrısının token'ı günlük deftere ve görevin sayacına eklenir (yerel ve CLI sayılmaz)."""
    if not token or saglayici == "ollama" or str(saglayici).startswith("cli:"):
        return
    kimlik = _kimlik(gorev_id)
    with _sayac_kilidi:
        kayit = _sayaclar.setdefault(kimlik, {"token": 0, "onay": False})
        kayit["token"] += int(token)
    with _defter_kilidi, _dosya_kilidi(_defter_yolu().with_suffix(".lock")):
        defter = _defter()
        gun = date.today().isoformat()
        defter = {g: t for g, t in defter.items() if g >= _gun_once(30)}  # 30 günden eskisi silinir
        defter[gun] = int(defter.get(gun, 0)) + int(token)
        try:
            _defter_yolu().parent.mkdir(parents=True, exist_ok=True)
            _defter_yolu().write_text(json.dumps(defter), encoding="utf-8")
        except OSError as e:
            _gunluk.warning("bulut harcama defteri yazılamadı: %s", e)


def _gun_once(n: int) -> str:
    from datetime import timedelta

    return (date.today() - timedelta(days=n)).isoformat()


def tavan_durumu(gorev_id: str | None = None) -> str:
    """Tavan aşıldıysa kullanıcıya gösterilecek neden; aşılmadıysa boş. 0 ya da negatif tavan = sınırsız."""
    gunluk = int(ayar.deger("bulut.gunluk_tavan_token") or 0)
    gorev = int(ayar.deger("bulut.gorev_tavan_token") or 0)
    if gunluk > 0 and gunluk_token() >= gunluk:
        return f"bugünkü bulut kullanımı {gunluk_token():,} token (günlük tavan {gunluk:,})".replace(",", ".")
    harcanan = gorev_token(gorev_id)
    if gorev > 0 and harcanan >= gorev:
        return f"bu iş {harcanan:,} token harcadı (görev tavanı {gorev:,})".replace(",", ".")
    return ""


def tavan_onaylandi(gorev_id: str | None = None) -> bool:
    with _sayac_kilidi:
        return bool((_sayaclar.get(_kimlik(gorev_id)) or {}).get("onay", False))


def tavan_onayla(gorev_id: str | None = None) -> None:
    """Kullanıcı bu istek/görev için tavanı aşmayı onayladı: aynı istekte bir daha sorulmaz."""
    with _sayac_kilidi:
        _sayaclar.setdefault(_kimlik(gorev_id), {"token": 0, "onay": False})["onay"] = True


# ---------------------------------------------------------------- saf karar

def _guc_sirasi(a: Aday, vram_gb: float) -> tuple:
    """Yedekleme zincirinin sırası: yerel (karta sığan, küçükten büyüğe) → karta sığmayan yerel → bulut → CLI."""
    return (a.cli, not a.yerel, not a.sigar(vram_gb), a.puan)


def havuz(adaylar: list[Aday], durum: Durum, saglik=None) -> tuple[list[Aday], list[str]]:
    """Kural 1, 2 ve 6: çevrimdışı / gizlilik / sansürsüz / sağlık süzgeci. (kalanlar, düşenlerin nedenleri)."""
    notlar, kalan = [], []
    for a in adaylar:
        if saglik is not None:
            s = saglik(a.saglayici)
            if s is not None and not s.iyi:
                notlar.append(f"{a.saglayici} sağlıksız ({s.neden or 'yanıt yok'})")
                continue
        if not a.yerel and not durum.cevrimici:
            continue
        if not a.yerel and durum.gizlilik == "yerel":
            continue
        if a.cli and not durum.kullanici_istegi:
            continue  # CLI ajanları yalnızca kullanıcının sohbetteki isteğinde
        if durum.sansursuz and (not a.yerel or not a.sansursuz):
            continue  # sansürsüz modda yalnızca sansürsüz yerel modeller (sansürsüz ↔ normal geçişi yok)
        if not durum.sansursuz and a.sansursuz:
            continue  # sansürsüz modeller otomatik seçilmez
        kalan.append(a)
    return kalan, list(dict.fromkeys(notlar))


def _on_ek(durum: Durum) -> str:
    if not durum.cevrimici:
        return "çevrimdışı, yalnızca yerel; "
    if durum.gizlilik == "yerel":
        return "gizlilik yerel, bulut kapalı; "
    return ""


def _zincir(havuz_: list[Aday], secilen: Aday, durum: Durum) -> list[tuple[str, str]]:
    """Seçilenden sonra denenecekler: araç kullanan, güç sırasında seçilenden yukarıdakiler."""
    sira = sorted((a for a in havuz_ if a.arac == 2 and not a.cli), key=lambda a: _guc_sirasi(a, durum.vram_gb))
    anahtarlar = [a.anahtar for a in sira]
    if secilen.anahtar in anahtarlar:
        return anahtarlar[anahtarlar.index(secilen.anahtar) + 1:]
    return [k for k in anahtarlar if k != secilen.anahtar]


def _bitir(secilen: Aday, neden: str, rol: str, havuz_: list[Aday], durum: Durum, **ek) -> Secim:
    s = Secim(secilen.saglayici, secilen.model, neden, rol, _zincir(havuz_, secilen, durum), **ek)
    if secilen.ucretli and durum.tavan:
        s.onay_gerekli = durum.tavan
    return s


def _yok(rol: str, durum: Durum, notlar: list[str]) -> Secim:
    ek = f" ({'; '.join(notlar)})" if notlar else ""
    if not durum.cevrimici:
        return Secim(None, None, "çevrimdışı ve çalışan yerel model yok: istek bekletiliyor" + ek, rol, bekleyen=True)
    if durum.gizlilik == "yerel":
        return Secim(None, None, "gizlilik yerel ama çalışan yerel model yok" + ek, rol)
    return Secim(None, None, "kullanılabilir model yok" + ek, rol)


def karar(adaylar: list[Aday], rol: str, durum: Durum, saglik=None, sohbet: tuple[str, str] | None = None) -> Secim:
    """MIMARI §4 kural sırası. `rol` ya da görev türü ("ozet", "planlama", "kod_uretimi"…) verilebilir."""
    rol = GOREV_ROLU.get(rol, rol)
    if rol not in ROLLER:
        raise ValueError(f"bilinmeyen rol: {rol}")
    kalan, notlar = havuz(adaylar, durum, saglik)
    if rol == "yonetici":
        return yonetici_karari(kalan, durum, sohbet, notlar)
    if not kalan:
        return _yok(rol, durum, notlar)
    on = _on_ek(durum)
    yereller = sorted((a for a in kalan if a.yerel and a.arac == 2), key=lambda a: (a.sigar(durum.vram_gb), a.puan))
    bulutlar = [a for a in kalan if a.ucretli]
    if rol == "kod":
        cli = [a for a in kalan if a.cli]
        if cli:
            return _bitir(max(cli, key=lambda a: a.puan), on + "rol kod: CLI ajanı var", rol, kalan, durum)
        if bulutlar:
            return _bitir(max(bulutlar, key=lambda a: a.puan), on + "rol kod: en güçlü bulut", rol, kalan, durum)
        kodcu = [a for a in yereller if "code" in a.yetenekler] or yereller
        if kodcu:
            return _bitir(max(kodcu, key=lambda a: (a.sigar(durum.vram_gb), a.puan)),
                          on + "rol kod: bulut yok, yerel model", rol, kalan, durum)
    else:  # hizli
        if durum.gizlilik == "bulut" and bulutlar:
            return _bitir(min(bulutlar, key=lambda a: a.puan), "gizlilik bulut: en ucuz bulut modeli", rol, kalan, durum)
        if yereller:
            # MIMARI §3 / modeller.json roller.hizli "en ucuz/hızlı": karta sığan + araç sınavını geçenlerden ölçülmüş
            # tok/sn en yüksek olan; ölçüm yoksa en küçük puanlı (en küçük model). Büyük modeller zincirde üst basamak.
            sigan = [a for a in yereller if a.sigar(durum.vram_gb)] or yereller
            olculen = [a for a in sigan if durum.hiz.get(a.model)]
            if olculen:
                en_iyi = max(olculen, key=lambda a: (float(durum.hiz[a.model]), -a.puan))
                neden = f"rol hızlı: araç sınavını geçen, karta sığan en hızlı yerel ({float(durum.hiz[en_iyi.model]):.0f} tok/sn)"
            else:
                en_iyi = min(sigan, key=lambda a: (a.puan, a.boyut_gb))
                neden = "rol hızlı: araç sınavını geçen, karta sığan en küçük yerel (hız ölçümü yok)"
            return _bitir(en_iyi, on + neden, rol, kalan, durum)
        if bulutlar:
            return _bitir(min(bulutlar, key=lambda a: a.puan), "yerelde araç kullanan model yok → en ucuz bulut",
                          rol, kalan, durum)
    yarim = [a for a in kalan if a.yerel]
    if yarim:  # araç sınavını tam geçen yok: en güçlü yerel model, uyarıyla
        a = max(yarim, key=lambda a: (a.arac or 0, a.puan))
        return _bitir(a, on + f"rol {ROL_ADI[rol]}: araç sınavını tam geçen model yok", rol, kalan, durum,
                      uyari="Bu model araçları güvenilir kullanamıyor.")
    return _yok(rol, durum, notlar)


def yonetici_karari(havuz_: list[Aday], durum: Durum, sohbet: tuple[str, str] | None = None,
                    notlar: list[str] | None = None) -> Secim:
    """Yönetici (plan, doğrulama, devretme kararı) — eski Aşama 2 politika sırası, `havuz` süzgecinden geçmiş adaylarla.

    otomatik: 1) Claude Code (kullanıcının sohbetinden gelen istekte) 2) en güçlü bulut 3) araç sınavını tam geçen en
    güçlü yerel 4) sohbet modeli + uyarı. yerel: 3–4. bulut: 1–2, yoksa 3–4. Düşük kademede yerel yönetici yetmezse
    bulut; o da yoksa görev parçalanır (hızlı modelle)."""
    notlar = notlar or []
    pol = "yerel" if durum.sansursuz or durum.gizlilik == "yerel" or not durum.cevrimici else durum.politika
    on = _on_ek(durum) + ("sansürsüz mod, yalnızca yerel; " if durum.sansursuz else "")
    cli = [a for a in havuz_ if a.saglayici == "cli:claude"]
    bulutlar = [a for a in havuz_ if a.ucretli]
    yereller = [a for a in havuz_ if a.yerel and a.arac == 2 and a.plan is not False]
    sigan = [a for a in yereller if a.sigar(durum.vram_gb)] or yereller
    # yönetici çağrısı hata verirse sıradaki aday politika sırasıyla: Claude Code → bulut → en güçlü yerel
    sira = ((cli + sorted(bulutlar, key=lambda a: -a.puan)) if pol != "yerel" else []) \
        + sorted(sigan, key=lambda a: -a.puan)

    def bitir(secilen: Aday, neden: str, **ek) -> Secim:
        s = _bitir(secilen, neden, "yonetici", havuz_, durum, **ek)
        s.zincir = [a.anahtar for a in sira if a.anahtar != secilen.anahtar]
        return s

    if pol in ("otomatik", "bulut"):
        if cli:
            return bitir(cli[0], on + f"yönetici ({POLITIKA_ADI[pol]}): Claude Code girişli")
        if bulutlar:
            return bitir(max(bulutlar, key=lambda a: a.puan), on + f"yönetici ({POLITIKA_ADI[pol]}): en güçlü bulut")
    if durum.kademe == "dusuk":
        planci = [a for a in sigan if a.plan is True]
        if not planci:
            if bulutlar and pol != "yerel":
                return bitir(max(bulutlar, key=lambda a: a.puan), on + "düşük kademe: yönetici yerelde karşılanamıyor → bulut")
            araci = sigan or [a for a in havuz_ if a.yerel and a.arac == 2]  # plan sınavı şart değil: iş küçük parça
            kucuk = min(araci, key=lambda a: a.boyut_gb or a.puan) if araci else None
            hedef = kucuk or _sohbet_adayi(havuz_, sohbet)
            if hedef is None:
                return _yok("yonetici", durum, notlar)
            return bitir(hedef, on + "düşük kademe, bulut yok: görev parçalanıp hızlı modelle denenecek", parcala=True)
    if sigan:
        en_iyi = max(sigan, key=lambda a: a.puan)
        kendisi = next((a for a in sigan if sohbet and a.anahtar == tuple(sohbet)), None)
        if (kendisi and kendisi is not en_iyi and durum.vram_gb and kendisi.boyut_gb and en_iyi.boyut_gb
                and kendisi.boyut_gb + en_iyi.boyut_gb > durum.vram_gb):
            # sohbet modeli de sınavı tam geçti; ikisi birlikte karta sığmaz: her plan/denetimde modeller karttan
            # inip çıkmasın (2026-09-28 sınavı: 14B sohbet + 12B yönetici 12 GB kartta zaman aşımı)
            return bitir(kendisi, on + f"yönetici: sohbet modeli de araç sınavını tam geçti, {en_iyi.model} ile "
                                       "birlikte karta sığmaz")
        return bitir(en_iyi, on + "yönetici: araç sınavını tam geçen en güçlü yerel model")
    hedef = _sohbet_adayi(havuz_, sohbet)
    if hedef is None:
        return _yok("yonetici", durum, notlar)
    return bitir(hedef, on + "yönetici için uygun model yok, sohbet modeli planlıyor",
                 uyari="Planı ve denetimi sohbet modeli yapıyor: daha güçlü bir model bağlanırsa sonuç iyileşir.")


def _sohbet_adayi(havuz_: list[Aday], sohbet: tuple[str, str] | None) -> Aday | None:
    if not sohbet or not sohbet[0]:
        return None
    return next((a for a in havuz_ if a.anahtar == tuple(sohbet)), None) or Aday(sohbet[0], sohbet[1],
                                                                                  sohbet[0] == "ollama")


# ---------------------------------------------------------------- yedekleme zinciri

class Zincir:
    """Zaman aşımı ya da `esik` başarısızlık → bir üst basamak (yerel küçük → yerel büyük → bulut).

    Zincirin sonunda `bitti` olur; `hata_kaydi()` SEMALAR §3 biçiminde kaydı verir, `devret()` hata analizine yollar."""

    def __init__(self, sira: list[tuple[str, str]], esik: int = BASARISIZ_ESIGI):
        self.sira = [tuple(k) for k in dict.fromkeys(tuple(k) for k in sira)]
        self.esik, self.konum, self.sayac = esik, 0, 0
        self.gecmis: list[str] = []
        self.nedenler: list[str] = []

    @classmethod
    def secimden(cls, secim: Secim, esik: int = BASARISIZ_ESIGI) -> "Zincir":
        return cls(([secim.anahtar] if secim.anahtar else []) + list(secim.zincir), esik)

    @property
    def su_an(self) -> tuple[str, str] | None:
        return self.sira[self.konum] if self.konum < len(self.sira) else None

    @property
    def bitti(self) -> bool:
        return self.su_an is None

    def basarili(self) -> None:
        self.sayac = 0

    def basarisiz(self, neden: str = "", zaman_asimi: bool = False) -> tuple[str, str] | None:
        """Başarısızlığı kaydeder; eşik dolduysa (ya da zaman aşımıysa) bir üst basamağa geçer. Şimdiki modeli döndürür."""
        if self.bitti:
            return None
        self.sayac += 1
        if neden:
            self.nedenler.append(f"{self.su_an[1]}: {neden}"[:300])
        if zaman_asimi or self.sayac >= self.esik:
            eski = self.su_an
            self.konum += 1
            self.sayac = 0
            yeni = self.su_an
            sebep = "zaman aşımı" if zaman_asimi else f"{self.esik} başarısız deneme"
            self.gecmis.append(f"{eski[1]} → {yeni[1] if yeni else 'zincir bitti'} ({sebep})")
        return self.su_an

    def atla(self, neden: str = "") -> tuple[str, str] | None:
        """Bu basamak kullanılamıyor (bulut tavanı, bilinen sağlıksız sağlayıcı): başarısızlık SAYILMAZ, sıradakine geç."""
        if self.bitti:
            return None
        eski = self.su_an
        self.konum += 1
        self.sayac = 0
        yeni = self.su_an
        self.gecmis.append(f"{eski[1]} → {yeni[1] if yeni else 'zincir bitti'} ({neden or 'atlandı'})")
        return self.su_an

    def ekle(self, anahtarlar) -> None:
        """Zincirin sonuna yeni basamaklar (ör. tavan reddedilince yerel modeller); olanlar bir daha eklenmez."""
        for k in anahtarlar:
            k = tuple(k)
            if k not in self.sira:
                self.sira.append(k)

    def hata_kaydi(self, adim=None, belirti: str = "") -> dict:
        """docs/SEMALAR.md §3: zincirin sonu `model_yetersiz`."""
        return {
            "adim": adim,
            "zaman": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
            "sinif": "model_yetersiz",
            "belirti": belirti or (self.nedenler[-1] if self.nedenler else "yedekleme zinciri bitti"),
            "kanit": " | ".join(self.gecmis + self.nedenler[-3:])[:1000],
            "eylem": {"tip": "devret", "hedef": "analiz/hata", "onay": "yok"},
            "sonuc": "vazgecildi",
        }


def devret(kayit: dict) -> str:
    """Zincir sonu: kayıt hata analizine gider (`cekirdek/analiz/hata.py`: sınıf + eylem + kütük).

    Döner: "analiz" (sınıflandırıcı aldı) ya da "sira" (analiz çöktü: DATA_DIR/hata_sirasi.jsonl'e yazıldı)."""
    try:
        from .analiz import hata  # K6: sınıf + eylem, DATA_DIR/hatalar.jsonl

        hata.isle(kayit)
        return "analiz"
    except Exception as e:  # hata analizi de çökerse kayıt kaybolmasın
        _gunluk.warning("hata analizine devredilemedi: %s", e)
    try:
        yol = ayar.DATA_DIR / "hata_sirasi.jsonl"
        yol.parent.mkdir(parents=True, exist_ok=True)
        with yol.open("a", encoding="utf-8") as f:
            f.write(json.dumps(kayit, ensure_ascii=False) + "\n")
    except OSError as e:
        _gunluk.warning("hata sırası yazılamadı: %s", e)
    return "sira"


# ---------------------------------------------------------------- programın kadrosundan adaylar

def _boyut_gb(model: str, params: float) -> float:
    from . import modeller

    bilinen = (modeller.deger("kategoriler.boyutlar") or {}).get(model)
    if bilinen:
        return float(bilinen)
    return round(params * 0.65, 1) if params else 0.0  # 4 bit nicemleme ≈ 0,6 GB / milyar parametre


def aday_cevir(c) -> Aday:
    """`roster.Candidate` → `Aday` (kart bilgisiyle)."""
    from .. import cards, model_updates

    if c.local:
        arac = cards.tools_level(c.model)
        kart = cards.card(c.model)
        plan = None if not isinstance(kart, dict) else bool(kart.get("plan"))
    else:
        arac, plan = (2 if "tools" in c.caps else 0), None
    return Aday(c.provider, c.model, bool(c.local), float(c.score), arac, plan,
                bool(model_updates.is_uncensored(c.model)), _boyut_gb(c.model, c.params) if c.local else 0.0,
                set(c.caps))


def adaylar(ayarlar, kullanici_istegi_: bool = True) -> list[Aday]:
    """Kurulu yerel modeller + kullanılabilir bulut bağlantıları (+ girişli Claude Code, sohbet isteğinde)."""
    from .. import cli_agents, roster

    sonuc = [aday_cevir(c) for c in roster.candidates(ayarlar)]
    if kullanici_istegi_ and cli_agents.available("cli:claude"):
        sonuc.append(_cli_adayi("cli:claude", cli_agents.CLAUDE.default))
    return sonuc


def _cli_adayi(ad: str, model: str) -> Aday:
    """CLI ajanının adayı: sınav sonucu kartından (`cards.card(ad)`), kart yoksa "sınanmadı" (arac/plan None; puan
    yalnızca sıralama için). Sabit "araç 2, plan var" beyanı uydurulmaz: CLAUDE.md "programın kendi sınavı"."""
    from .. import cards

    kart = cards.card(ad) or {}
    arac = kart.get("tools")
    plan = kart.get("plan")
    return Aday(ad, model, False, float(kart.get("score", 95) or 95), None if arac is None else int(arac),
                None if plan is None else bool(plan), False, 0.0, {"tools", "code", "thinking"})


def cevrimici() -> bool:
    from . import profil

    return profil.ag_var()


def durum(ayarlar, sansursuz: bool | None = None) -> Durum:
    """Programın şu anki durumu: ağ, gizlilik, kademe, politika, sansürsüz mod, kart belleği, tavan."""
    from . import profil

    kayit = profil.yukle() or {}
    vram = float(((kayit.get("gpu") or {}).get("vram_gb")) or 0.0)
    extra = _extra(ayarlar)
    if sansursuz is None:
        sansursuz = bool(extra.get("uncensored_only") or extra.get("uncensored"))
    tavan = "" if tavan_onaylandi() else tavan_durumu()
    hiz = {model: float(s["tok_sn"]) for model, s in (kayit.get("benchmark") or {}).items()
           if isinstance(s, dict) and s.get("tok_sn")}
    return Durum(cevrimici(), gizlilik(ayarlar), profil.kademe(), politika(ayarlar), sansursuz,
                 kullanici_istegi(ayarlar), vram, tavan, hiz)


def _bilinen_saglik(ad: str) -> Saglik | None:
    return SAGLIK.bilinen_sagliksiz(ad)


def sec(ayarlar, rol: str, sohbet: tuple[str, str] | None = None, durum_: Durum | None = None,
        cli_yalnizca_kod: bool = False) -> Secim:
    """Programın kadrosuyla karar. Sağlık: aday listesi canlı sağlayıcılardan kurulur; önbellekte sağlıksız
    görünen (401, bağlantı hatası) sağlayıcı ayrıca düşer.

    `cli_yalnizca_kod` (görev motoru): CLI ajanı yalnızca `kod` rolünde aday olur; planlayıcı, analist ve denetçi
    olamaz (her anla/planla/doğrula ayrı bir `claude -p` oturumu açıyordu, CLAUDE.md kuralı)."""
    d = durum_ or durum(ayarlar)
    if cli_yalnizca_kod and GOREV_ROLU.get(rol, rol) != "kod":
        d = replace(d, kullanici_istegi=False)  # havuz CLI adaylarını düşürür
    return karar(adaylar(ayarlar, d.kullanici_istegi), rol, d, _bilinen_saglik, sohbet)


def yonetici_sec(ayarlar, sohbet: tuple[str, str], sansursuz: bool | None = None, politika_: str | None = None) -> Secim:
    """Plan / doğrulama / devretme kararını verecek model (roster.manager_for buraya devreder).

    `politika_` ayardaki politikayı bu çağrı için ezer (ör. araç fabrikası yerel yönetici ister)."""
    if sansursuz is None:
        sansursuz = _sansursuz_mu(sohbet)
    d = durum(ayarlar, sansursuz)
    if politika_ in POLITIKALAR and d.politika != "yerel":
        d.politika = politika_
    return sec(ayarlar, "yonetici", sohbet, d)


def yerel_sec(ayarlar, rol: str = "hizli") -> Secim:
    """Bulut kullanılamadığında (tavan onaylanmadı) yalnızca yerel modellerle karar."""
    d = durum(ayarlar)
    d.gizlilik = "yerel"
    secim = sec(ayarlar, rol, durum_=d)
    secim.neden = "bulut tavanı aşıldı, yerel model; " + secim.neden
    return secim


def _sansursuz_mu(sohbet) -> bool:
    from .. import model_updates

    return bool(sohbet and sohbet[1] and model_updates.is_uncensored(sohbet[1]))


def daha_guclu(ayarlar, su_an: tuple[str, str]):
    """Başarısız adımı devralacak model (zincirde bir üst basamak): `roster.Candidate` ya da None.

    Yerelde yalnızca araç sınavını tam geçenler; sansürsüz ↔ normal geçişi yok. Bulut yalnızca "güçlü" model
    politikasında (kullanıcı "yerel" seçtiyse ücretli bir servise kendiliğinden gidilmez), gizlilik ve ağ izin verirse."""
    from .. import roster

    havuz_c = roster.candidates(ayarlar)
    anahtar = tuple(su_an)
    taban = next((c.score for c in havuz_c if c.key == anahtar), 0.0)
    bulut_olur = getattr(ayarlar, "model_policy", "") == "guclu" and gizlilik(ayarlar) != "yerel"
    d = Durum(cevrimici=cevrimici() if bulut_olur else True, gizlilik=gizlilik(ayarlar),
              sansursuz=_sansursuz_mu(su_an))
    uygun = []
    for c in havuz_c:
        if c.key == anahtar or "tools" not in c.caps or c.score <= taban:
            continue
        a = aday_cevir(c)
        if a.yerel and a.arac != 2:
            continue
        if not a.yerel and (not bulut_olur or not d.cevrimici):
            continue
        if a.sansursuz != d.sansursuz or SAGLIK.bilinen_sagliksiz(a.saglayici):
            continue
        uygun.append(c)
    return max(uygun, key=lambda c: c.score, default=None)


def sohbet_secimi(ayarlar, saglayici: str, model: str, otomatik: bool) -> Secim:
    """Bu turun sohbet modeli için görünür karar (neden). Sağlayıcı sağlıksızsa yedek önerilir (`zincir`)."""
    s = SAGLIK.sor(saglayici, ayarlar)
    if s.iyi:
        neden = ("otomatik seçim: " if otomatik else "senin seçtiğin model; ") + {
            "ollama": "yerel, ücretsiz", "claude": "Claude API", }.get(saglayici, "bulut" if saglayici.startswith("api:")
                                                                         else "aboneliğinle çalışan program")
        return Secim(saglayici, model, neden, "hizli")
    yedek = sec(ayarlar, "hizli")
    kendisi = f"{saglayici} çalışmıyor ({s.neden or 'yanıt yok'})"
    if yedek.saglayici and yedek.saglayici != saglayici:
        return Secim(yedek.saglayici, yedek.model, f"{kendisi} → {yedek.neden}", "hizli", yedek.zincir,
                     onay_gerekli=yedek.onay_gerekli)
    if yedek.bekleyen or not cevrimici():
        return Secim(None, None, f"çevrimdışı: {kendisi} ve bulut kullanılamıyor", "hizli", bekleyen=True)
    return Secim(None, None, f"{kendisi}; {yedek.neden}", "hizli")
