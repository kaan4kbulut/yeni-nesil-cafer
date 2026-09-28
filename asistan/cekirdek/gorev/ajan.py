"""Görev motorunun yetenekleri (K5): planlayıcıya giden liste yalnızca manifestlerden (`yetenek/kayit.py`), elle liste
yok. Her yetenek programın tek araç yolundan geçer: girdi doğrulama → izin hattı (`permissions.decide`) → araca özgü
kapı → hook'lar. Toolbox doğrudan çağrılmaz (izin hattı atlanırdı).

- Yerleşik yetenek (`sandbox: false`): `calistir.py` süreç içinde; her aracı `baglam.arac` → `Agent._execute_tool` ile
  çağırır. Onay tahmini `arac_cagrisi(girdi)` ile (hangi araç, hangi girdi).
- Sandbox yeteneği (`sandbox: true`): izin hattına `y_<ad>` adıyla, manifestten çıkan risk sınıfıyla (`Yetenek.risk`)
  kayıtlı bir araç olarak girer; çalıştırıcısı bu motor ajanının `_tool_y_<ad>` yöntemidir (sohbet ajanlarına verilmez).
- Eski yol: K4'te kaydedilmiş yarım görevlerin adımları araç adıyla (`read_file`, `run_python`…) sürer.

Onay: izin hattı "kullanıcıya sor" derse soru `ask_approval` geri çağrısına gelir. Kullanıcı bu adımı onayladıysa
(`onayli`) cevap "evet"; onaylamadıysa "hayır" ve sonuç `onay_bekliyor` olur — yürütücü adımı bekletir, kullanıcı
Görevler penceresinden ya da `gorev --onayla` ile onaylayınca aynı çağrı hattan yeniden geçer.

Sohbetten çalışırken (`sohbet.py`) araç olayları sohbetin geri çağrısına da gider (`ust_cb`: araç kartları, güvenlik
notları) ve sohbet ajanının izin bağlamı (`izin_kaynagi`: ▶ uygula turu, "hep izin ver", otomatik onay listesi) aynen
kopyalanır; yoksa ▶ turunda yazma onaysız geçerdi (`permissions.decide`: `must_act and action`).
"""

import logging
import uuid
from dataclasses import replace
from pathlib import Path
from types import MappingProxyType

from ..yetenek import Baglam, YetenekHatasi, cikti_metni
from . import Cikti

GRUP = "temel"  # K4'ün araç grubu: yalnızca eski görevlerin adımları için (eski yol)
ONEK = "y_"  # sandbox yeteneklerinin izin hattındaki araç adı


class _GeriCagri:
    """Agent.Callbacks: araç olaylarını motora iletir, onayı adımın onayından cevaplar."""

    def __init__(self, sahip: "AjanYetenekleri"):
        self.sahip = sahip

    def ask_approval(self, name, args):
        if self.sahip._onayli:
            return True
        self.sahip._bekleyen = True
        return False

    def is_cancelled(self):
        return bool(self.sahip.iptal and self.sahip.iptal())

    def on_tool_start(self, call_id, name, args):
        if self.sahip.olay:
            self.sahip.olay("arac", {"ad": name, "girdi": args})
        self._ilet("on_tool_start", call_id, name, args)

    def on_tool_end(self, call_id, result, is_error):
        self._ilet("on_tool_end", call_id, result, is_error)

    def on_security(self, *a, **k):
        self._ilet("on_security", *a, **k)

    def _ilet(self, ad: str, *a, **k):
        fn = getattr(self.sahip.ust_cb, ad, None) if self.sahip.ust_cb is not None else None
        if fn:
            fn(*a, **k)

    def __getattr__(self, name):  # on_text, on_thinking…: motor kullanmıyor
        return lambda *a, **k: None


class AjanYetenekleri:
    def __init__(self, ayarlar, baglantilar: list | None = None, klasor: str = "", okunur: list[str] | None = None,
                 olay=None, iptal=None, ust_cb=None, izin_kaynagi=None, kayit=None):
        from ... import tools
        from ...agent import Agent
        from ...registry import REGISTRY
        from .. import profil
        from ..yetenek.kayit import Kayit

        if klasor:
            Path(klasor).mkdir(parents=True, exist_ok=True)
            ayarlar = replace(ayarlar, workspace=klasor)
        self._onayli = self._bekleyen = False
        self._son_hata = ""
        self.olay, self.iptal, self.ust_cb = olay, iptal, ust_cb
        self.ajan = Agent(ayarlar, _GeriCagri(self), None, baglantilar or [])
        self.ajan.gate_actions = False  # ✓ beklemesi yok: onay adım adım (yürütücü)
        self.ajan.must_act = False
        if izin_kaynagi is not None:  # sohbet ajanının izin bağlamı (▶ turu, hep izin ver, otomatik onay)
            if getattr(izin_kaynagi, "confirm_commands", False):  # ✓ turu: "komutları onayla" kapalı olsa da sorulur
                self.ajan.settings = replace(self.ajan.settings, confirm_commands=True)
            self.ajan.must_act = bool(getattr(izin_kaynagi, "must_act", False))
            self.ajan.always_allowed = bool(getattr(izin_kaynagi, "always_allowed", False))
            self.ajan.auto_approve = getattr(izin_kaynagi, "auto_approve", self.ajan.auto_approve)
        # kullanıcının klasörleri: sandbox yeteneğine yalnızca bunlar okuma kökü olarak gider (programın kendi
        # klasörleri değil: ayar klasöründe anahtar dosyası var)
        self._okunur = [Path(yol).expanduser().resolve() for yol in okunur or []]
        self.ajan.toolbox.read_roots.extend(self._okunur)
        self.klasor = str(self.ajan.toolbox.root)
        self._eski = {n for n, t in REGISTRY.tools.items() if t.group == GRUP}
        self.kademe = profil.kademe()
        self._kutuphaneler = [str(p) for p in (tools.USER_LIBS, tools.BUNDLED_LIBS) if p.is_dir()]
        self._python = tools.python_exe()
        self.kayit = kayit if kayit is not None else Kayit(kademe=self.kademe, kutuphane_yollari=self._kutuphaneler)
        self._arac_ekle()

    # ---- kurulum
    def _arac_ekle(self) -> None:
        """Motor ajanının araçları: temel araçlar (eski yol ve yerleşik yetenekler) + yeteneklerin kullandığı ek araçlar
        (`move_file`, tarayıcı) + sandbox yetenekleri (`y_<ad>`). Sohbet ajanlarının listesi değişmez."""
        from ... import browser
        from ...registry import REGISTRY, Tool

        ek = [REGISTRY.get("move_file").spec]
        if browser.available():
            ek += REGISTRY.specs("tarayici")
        for y in self.kayit.aktifler():
            if not y.sandbox:
                continue
            ad = ONEK + y.ad
            REGISTRY.put(Tool(ad, f"Capability '{y.ad}': {y.aciklama}", y.girdi_semasi(), y.risk(),
                              (f"yetenek: {y.ad}", "bitti"), source="yetenek", group="yetenek",
                              hints={"izinler": y.izinler, "kaynak": y.kaynak,
                                     "guvenilir": y.guvenilir and y.kaynak == "yerlesik"}))
            ek.append(REGISTRY.get(ad).spec)
            setattr(self.ajan, f"_tool_{ad}", lambda args, _y=y: self._sandboxta(_y, args))
        var = {s["name"] for s in self.ajan.tool_specs}
        self.ajan.tool_specs += [s for s in ek if s["name"] not in var]

    def _baglam(self, arac=None) -> Baglam:
        return Baglam(calisma_klasoru=self.klasor, kademe=self.kademe, okuma_kokleri=tuple(map(str, self._okunur)),
                      ayar=MappingProxyType({"calisma_klasoru": self.klasor, "kademe": self.kademe}), arac=arac)

    def _arac(self, ad: str, args: dict) -> str:
        """Yerleşik yeteneğin `baglam.arac`'ı: programın tek araç yolu. Hata metni aynen saklanır (doğrulayıcı onu
        okur: "The user declined…", "BLOCKED…")."""
        metin, hata = self.ajan._execute_tool(uuid.uuid4().hex[:12], ad, dict(args or {}))
        if hata:
            self._son_hata = str(metin)
            raise YetenekHatasi("izin" if self._bekleyen else "mantik", str(metin)[:500])
        return str(metin)

    def _sandboxta(self, yetenek, args: dict) -> str:
        """`y_<ad>` aracının çalıştırıcısı (izin hattından geçtikten sonra çağrılır)."""
        from ... import tools
        from ..yetenek import calistirici

        try:
            return cikti_metni(calistirici.calistir(yetenek, dict(args or {}), self._baglam(), python=self._python,
                                                    kutuphane_yollari=self._kutuphaneler))
        except YetenekHatasi as e:
            raise tools.ToolError(f"({e.sinif}) {e.mesaj}") from None

    # ---- Yetenekler arayüzü (gorev/__init__.py)
    def listele(self) -> list[dict]:
        return self.kayit.planlayici_listesi()

    def pasifler(self) -> list[dict]:
        """Var ama kullanılamayan yetenekler (anlayıcı "şu kurulursa yapılabilir" diyebilsin)."""
        return [{"ad": y.ad, "aciklama": y.aciklama, "neden": y.neden} for y in self.kayit.pasifler()]

    def _cagri(self, ad: str, girdi: dict) -> tuple[str, dict] | None:
        """Bu yetenek çağrısı izin hattına hangi araç adıyla gider? Bilinmeyen: None."""
        from ..yetenek.kayit import modul_yukle

        y = self.kayit.getir(ad)
        if y is None or not y.aktif:
            return (ad, dict(girdi or {})) if y is None and ad in self._eski else None
        if y.sandbox:
            return ONEK + ad, dict(girdi or {})
        cagri = getattr(modul_yukle(y), "arac_cagrisi", None)
        return cagri(dict(girdi or {})) if cagri else None

    def onay_gerekir(self, ad: str, girdi: dict) -> bool:
        from ... import permissions

        try:
            cagri = self._cagri(ad, girdi)
        except Exception as e:  # girdi henüz tam değil (yer tutucu): çalışma anında hat yine sorar
            logging.getLogger("asistan.yetenek").info("onay tahmini yapılamadı (%s): %s", ad, e)
            return False
        if cagri is None:
            return False
        return permissions.decide(cagri[0], cagri[1], self.ajan.permission_context()).kind == permissions.ASK

    def calistir(self, ad: str, girdi: dict, onayli: bool = False) -> Cikti:
        from ..yetenek import calistirici

        self._onayli, self._bekleyen, self._son_hata = onayli, False, ""
        try:
            y = self.kayit.getir(ad)
            if y is None and ad in self._eski:  # eski görev (K4): araç adıyla
                metin, hata = self.ajan._execute_tool(uuid.uuid4().hex[:12], ad, dict(girdi or {}))
            elif y is None:
                adlar = ", ".join(x["ad"] for x in self.listele())
                metin, hata = f"Error: '{ad}' adlı yetenek yok (kayıtlı yetenekler: {adlar})", True
            elif not y.aktif:
                metin, hata = f"Error: '{ad}' yeteneği kullanılamıyor: {y.neden}", True
            elif y.sandbox:
                metin, hata = self.ajan._execute_tool(uuid.uuid4().hex[:12], ONEK + ad, dict(girdi or {}))
            else:
                try:
                    cikti = calistirici.calistir(y, dict(girdi or {}), self._baglam(self._arac))
                    metin, hata = cikti_metni(cikti), False
                except YetenekHatasi as e:
                    metin, hata = self._son_hata or f"Error ({e.sinif}): {e.mesaj}", True
        finally:
            self._onayli = False
        return Cikti(str(metin), bool(hata), onay_bekliyor=self._bekleyen)
