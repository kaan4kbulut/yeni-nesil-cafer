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


class YonlendiriciModeli:
    def __init__(self, ayarlar, baglantilar: list | None = None):
        self.ayarlar, self.baglantilar = ayarlar, list(baglantilar or [])
        self._kararlar: dict[str, yonlendirici.Secim] = {}

    def _karar(self, rol: str) -> yonlendirici.Secim:
        if rol not in self._kararlar:
            self._kararlar[rol] = yonlendirici.sec(self.ayarlar, rol)
        return self._kararlar[rol]

    def secim(self, rol: str) -> dict:
        return self._karar(rol).sozluk()

    def __call__(self, rol: str, mesajlar: list, sistem: str = "", sema: dict | None = None) -> Cevap:
        from .. import saglayici as sg

        karar = self._karar(rol)
        sira = ([karar.anahtar] if karar.anahtar else []) + [tuple(k) for k in karar.zincir]
        if not sira:
            raise ModelYok(karar.neden)
        son_hata: Exception | None = None
        for ad, model in dict.fromkeys(sira):
            try:
                saglayici = sg.bul(ad, self.ayarlar, self.baglantilar)
                if sema is not None:
                    s = yapisal.uret(saglayici, mesajlar, sema, sistem, model=model)
                    metin, veri, hatalar = s.ham, s.veri, s.hatalar
                else:
                    metin, veri, hatalar = saglayici.sohbet(mesajlar, sistem, model=model).metin, None, []
            except Exception as e:  # bu model olmadı: zincirde sıradaki
                son_hata = e
                if _ulasilamadi(e):
                    yonlendirici.SAGLIK.bildir(ad, False, str(e)[:200])
                _gunluk.warning("görev modeli %s/%s hata verdi: %s", ad, model, e)
                continue
            if not (ad == "ollama" or ad.startswith("cli:")):  # ücretli bulut: token yaklaşık (karakter/4)
                yonlendirici.harcama_ekle(ad, (len(sistem) + len(str(mesajlar)) + len(metin or "")) // 4)
            secim = {"saglayici": ad, "model": model, "neden": karar.neden if (ad, model) == karar.anahtar
                     else f"yedek: {karar.anahtar[1] if karar.anahtar else '?'} hata verdi"}
            return Cevap(metin or "", veri, secim, hatalar)
        raise ModelYok(f"{karar.neden}; son hata: {son_hata}" if son_hata else karar.neden)
