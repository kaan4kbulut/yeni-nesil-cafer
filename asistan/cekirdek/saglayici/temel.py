"""Model sağlayıcılarının ortak arayüzü: `sohbet`, `akis`, `saglik`, `maliyet` (docs/MIMARI.md §2).

Sağlayıcı yalnızca TEK model çağrısını yapar (istek → akış parçaları). Araç döngüsü, bağlam kırpma, özetleme, iptal ve
"iş bitmedi" uyarıları `Agent`'ta kalır; böylece dört yol (Ollama, Claude, OpenAI uyumlu, CLI ajanı) aynı biçimde çağrılır.
"""

import time
from abc import ABC, abstractmethod
from collections.abc import Iterator
from dataclasses import dataclass, field

# akış parçası türleri
METIN = "metin"  # cevabın bir parçası
DUSUNCE = "dusunce"  # modelin gizli düşünmesi (arayüzde ayrı gösterilir)
ARAC = "arac"  # araç çağrıları geldi (bilgi için; hepsi SON'da da toplu verilir)
NABIZ = "nabiz"  # içi boş satır geldi: çağıran her satırda iptali (■ / Esc) denetleyebilsin
SON = "son"  # çağrı bitti: istatistik, araç çağrıları, sağlayıcıya özgü son bilgi


@dataclass
class Parca:
    tur: str
    metin: str = ""
    araclar: list = field(default_factory=list)  # SON: OpenAI biçiminde araç çağrıları ({"id", "function": {…}})
    son: dict = field(default_factory=dict)  # SON: sağlayıcının ham son bilgisi (Ollama son parçası, kullanım…)


@dataclass
class Yanit:
    metin: str
    araclar: list
    son: dict
    dusunce: str = ""


@dataclass
class Saglik:
    iyi: bool
    neden: str = ""
    zaman: float = field(default_factory=time.time)


class Iptal(Exception):
    """Kullanıcı işi durdurdu (■ / Esc). Eski adı `agent.Cancelled` (aynı sınıf)."""


class SaglayiciHatasi(RuntimeError):
    """Sağlayıcı HTTP hatası: durum kodu ve gövde (çağıran bağlam aşımı / 401 gibi durumları ayırt eder)."""

    def __init__(self, durum: int, govde: str, ad: str = ""):
        super().__init__(f"{ad or 'Sağlayıcı'} hatası ({durum}): {govde}")
        self.durum, self.govde, self.ad = durum, govde, ad


class Saglayici(ABC):
    """Bir model sağlayıcısı. `ad` sohbetin sağlayıcı kimliğidir: "ollama", "claude", "api:<id>", "cli:<ad>"."""

    ad: str = ""

    @abstractmethod
    def akis(self, mesajlar: list, sistem: str = "", araclar: list | None = None, **secenek) -> Iterator[Parca]:
        """Tek model çağrısı, akışlı. Son parça her zaman `SON` türündedir; içi boş her satır için `NABIZ` gelir.

        Çağıran akışı yarıda bırakacaksa üreteci kapatmalı (`contextlib.closing`): bağlantı kapanır, üretim durur."""

    def sohbet(self, mesajlar: list, sistem: str = "", araclar: list | None = None, **secenek) -> Yanit:
        """Tek model çağrısı, akışsız: bütün parçalar birleştirilir."""
        metin, dusunce, son = [], [], Parca(SON)
        for parca in self.akis(mesajlar, sistem, araclar, **secenek):
            if parca.tur == METIN:
                metin.append(parca.metin)
            elif parca.tur == DUSUNCE:
                dusunce.append(parca.metin)
            elif parca.tur == SON:
                son = parca
        return Yanit("".join(metin), son.araclar, son.son, "".join(dusunce))

    @abstractmethod
    def saglik(self) -> Saglik:
        """Sağlayıcı şu an kullanılabilir mi? Ücretli çağrı yapmaz (anahtar var mı, sunucu açık mı)."""

    def maliyet(self, girdi_token: int, cikti_token: int, model: str = "") -> float | None:
        """Bu çağrının tahmini maliyeti (USD). Yerel ve abonelikli sağlayıcılarda 0; fiyatı bilinmiyorsa None."""
        return 0.0
