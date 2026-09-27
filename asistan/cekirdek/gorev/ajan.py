"""Görev motorunun yetenekleri K4'te programın temel araçlarıdır (dosya, komut, Python, web). Bu uyarlayıcı onları
`Agent._execute_tool` üzerinden çalıştırır: girdi doğrulama → izin hattı (`permissions.decide`) → araca özgü kapı →
hook'lar. Toolbox doğrudan çağrılmaz (izin hattı atlanırdı). K5'te manifestli yetenekler aynı arayüzle gelir.

Onay: izin hattı "kullanıcıya sor" derse soru `ask_approval` geri çağrısına gelir. Kullanıcı bu adımı onayladıysa
(`onayli`) cevap "evet"; onaylamadıysa "hayır" ve sonuç `onay_bekliyor` olur — yürütücü adımı bekletir, kullanıcı
Görevler penceresinden ya da `gorev --onayla` ile onaylayınca aynı çağrı hattan yeniden geçer.
"""

import uuid
from dataclasses import replace
from pathlib import Path

from . import Cikti

GRUP = "temel"  # registry grubu: planlayıcıya açılan araçlar (K5'te manifestler)


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

    def __getattr__(self, name):  # on_tool_end, on_text, on_security…: motor kullanmıyor
        return lambda *a, **k: None


class AjanYetenekleri:
    def __init__(self, ayarlar, baglantilar: list | None = None, klasor: str = "", okunur: list[str] | None = None,
                 olay=None, iptal=None):
        from ...agent import Agent
        from ...registry import REGISTRY

        if klasor:
            Path(klasor).mkdir(parents=True, exist_ok=True)
            ayarlar = replace(ayarlar, workspace=klasor)
        self._onayli = self._bekleyen = False
        self.olay, self.iptal = olay, iptal
        self.ajan = Agent(ayarlar, _GeriCagri(self), None, baglantilar or [])
        self.ajan.gate_actions = False  # ✓ beklemesi yok: onay adım adım (yürütücü)
        self.ajan.must_act = False
        for yol in okunur or []:
            self.ajan.toolbox.read_roots.append(Path(yol).expanduser().resolve())
        adlar = {n for n, t in REGISTRY.tools.items() if t.group == GRUP}
        self._specs = [s for s in self.ajan.tool_specs if s["name"] in adlar]

    def listele(self) -> list[dict]:
        from ...registry import REGISTRY

        return [{"ad": s["name"], "aciklama": s["description"].split("\n")[0][:300], "girdi_semasi": s["input_schema"],
                 "salt_okur": getattr(REGISTRY.get(s["name"]), "risk", "") == "okur"} for s in self._specs]

    def onay_gerekir(self, ad: str, girdi: dict) -> bool:
        from ... import permissions

        return permissions.decide(ad, dict(girdi or {}), self.ajan.permission_context()).kind == permissions.ASK

    def calistir(self, ad: str, girdi: dict, onayli: bool = False) -> Cikti:
        self._onayli, self._bekleyen = onayli, False
        try:
            metin, hata = self.ajan._execute_tool(uuid.uuid4().hex[:12], ad, dict(girdi or {}))
        finally:
            self._onayli = False
        return Cikti(str(metin), bool(hata), onay_bekliyor=self._bekleyen)
