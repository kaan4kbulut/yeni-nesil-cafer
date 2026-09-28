"""Görev motorunun model çağrısı: yönlendirici (`yonlendirici.sec`) karar verir, sağlayıcı katmanı çağırır.

Seçilen model hata verirse (bağlantı, 401, zaman aşımı) yedekleme zincirinde sıradakine geçilir; ulaşılamayan sağlayıcı
sağlık önbelleğine yazılır. Şema istenirse `yapisal.uret` (şema-kısıtlı üretim + bir düzeltme turu) kullanılır.
"""

import logging

from .. import yapisal, yonlendirici
from . import Cevap, ModelYok

_gunluk = logging.getLogger(__name__)


def _ulasilamadi(hata: Exception) -> bool:
    import httpx

    return isinstance(hata, (httpx.ConnectError, httpx.TimeoutException, ConnectionError, TimeoutError)) or type(
        hata).__name__ in ("AuthenticationError", "APIConnectionError", "APITimeoutError") or "(401)" in str(hata)


def _ucretli(ad: str) -> bool:
    return not (ad == "ollama" or ad.startswith("cli:"))


class YonlendiriciModeli:
    """`sor`: onay penceresi (`ask_approval(ad, girdi) -> bool`). Bulut tavanı aşılınca ücretli çağrı ona sorulur
    (kural `permissions.bulut_tavani`; Manager'ın `_budget_ok`'u gibi). Yoksa ya da "hayır" denirse iş yerel
    modelle sürer: para harcatan karar hep kullanıcının, sessiz harcama yok."""

    def __init__(self, ayarlar, baglantilar: list | None = None, sor=None):
        self.ayarlar, self.baglantilar, self.sor = ayarlar, list(baglantilar or []), sor
        self._kararlar: dict[str, yonlendirici.Secim] = {}
        self._tavan_red = False  # bu motorda tavan bir kez reddedildi: yeniden sorulmaz
        self.gorev_id: str | None = None  # yürütücü görev kimliğini verir: bulut sayacı görev başına, iş parçacığından bağımsız

    def _karar(self, rol: str) -> yonlendirici.Secim:
        if rol not in self._kararlar:
            self._kararlar[rol] = yonlendirici.sec(self.ayarlar, rol)
        return self._kararlar[rol]

    def secim(self, rol: str) -> dict:
        return self._karar(rol).sozluk()

    def __call__(self, rol: str, mesajlar: list, sistem: str = "", sema: dict | None = None) -> Cevap:
        """Yedekleme zinciri `yonlendirici.Zincir` ile (MIMARI §4.5): aynı modelde `BASARISIZ_ESIGI` (2) hata → sıradaki;
        ulaşılamayan sağlayıcı (bağlantı, zaman aşımı, 401) → hemen sıradaki; `Iptal` yeniden fırlatılır; şemaya uymayan
        cevap zincir başarısızlığı değildir (çağıran `model_yetersiz` sayar)."""
        from .. import saglayici as sg

        karar = self._karar(rol)
        zincir = yonlendirici.Zincir.secimden(karar)
        if zincir.bitti:
            raise ModelYok(karar.neden)
        son_hata: Exception | None = None
        tavan_notu = ""
        while not zincir.bitti:
            ad, model = zincir.su_an
            if _ucretli(ad) and not self._tavan_izni(ad, model):
                if not tavan_notu:  # tavan onaylanmadı: yerel modeller sıranın sonuna
                    tavan_notu = "bulut tavanı aşıldı, yerel model"
                    yerel = yonlendirici.yerel_sec(self.ayarlar, rol)
                    zincir.ekle(k for k in ([yerel.anahtar] if yerel.anahtar else []) + [tuple(x) for x in yerel.zincir]
                                if not _ucretli(k[0]))
                zincir.atla("bulut tavanı")
                continue
            try:
                saglayici = sg.bul(ad, self.ayarlar, self.baglantilar)
                if sema is not None:  # yapisal.uret her çağrıyı (düzeltme turu dahil) deftere kendisi yazar
                    s = yapisal.uret(saglayici, mesajlar, sema, sistem, model=model, gorev_id=self.gorev_id)
                    metin, veri, hatalar = s.ham, s.veri, s.hatalar
                else:
                    yanit = saglayici.sohbet(mesajlar, sistem, model=model)
                    metin, veri, hatalar = yanit.metin, None, []
                    yapisal.harcama_yaz(saglayici, yanit, sistem, mesajlar, metin, self.gorev_id)
            except sg.Iptal:
                raise  # kullanıcı durdurdu: başka model denenmez
            except Exception as e:
                son_hata = e
                ulasilamadi = _ulasilamadi(e)
                if ulasilamadi:
                    yonlendirici.SAGLIK.bildir(ad, False, str(e)[:200])
                _gunluk.warning("görev modeli %s/%s hata verdi: %s", ad, model, e)
                zincir.basarisiz(str(e)[:200], zaman_asimi=ulasilamadi)  # ulaşılamıyorsa hemen sıradaki
                continue
            zincir.basarili()
            neden = (karar.neden if (ad, model) == karar.anahtar else tavan_notu
                     or f"yedek: {karar.anahtar[1] if karar.anahtar else '?'} hata verdi")
            return Cevap(metin or "", veri, {"saglayici": ad, "model": model, "neden": neden}, hatalar)
        neden = "; ".join(n for n in (karar.neden, tavan_notu, *zincir.gecmis[-3:]) if n)
        raise ModelYok(f"{neden}; son hata: {son_hata}" if son_hata else neden)

    def _tavan_izni(self, ad: str, model: str) -> bool:
        """Ücretli bulut çağrısı yapılabilir mi? Tavan aşıldıysa kullanıcıya bir kez sorulur."""
        from ... import permissions

        karar = permissions.bulut_tavani(yonlendirici.tavan_durumu(self.gorev_id),
                                         yonlendirici.tavan_onaylandi(self.gorev_id))
        if karar.kind == permissions.ALLOW:
            return True
        if self._tavan_red:
            return False
        evet = self.sor is not None and bool(self.sor(permissions.BULUT_TAVANI, {
            "purpose": f"Bulut maliyet tavanı aşıldı: {karar.reason}. {model} ile devam edilsin mi? "
                       "(Hayır dersen bu iş yerel modelle sürer.)", "model": f"{ad}/{model}"}))
        if evet:
            yonlendirici.tavan_onayla(self.gorev_id)
        else:
            self._tavan_red = True
            _gunluk.warning("bulut tavanı aşıldı (%s): %s/%s kullanılmıyor", karar.reason, ad, model)
        return evet
