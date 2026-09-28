"""Claude API sağlayıcısı (`anthropic` SDK, akışlı Messages API).

İstemci dışarıdan verilir (`istemci_getir`): anahtar zinciri ve testlerdeki sahte istemci `Agent._claude_client`'tan gelir.
Hangi modelin düşünme / sunucu tarafı yedek desteklediği çağıranın kararıdır (model adları çekirdeğe gömülmez).
"""

import os
from collections.abc import Callable, Iterator

import anthropic

from .temel import DUSUNCE, METIN, NABIZ, SON, Parca, Saglayici, Saglik

EN_COK_TOKEN = 64000


def istemci(anahtar: str = "") -> anthropic.Anthropic:
    """Anahtar verilirse onunla; yoksa ANTHROPIC_API_KEY ya da `ant auth login` profiliyle."""
    return anthropic.Anthropic(api_key=anahtar) if anahtar else anthropic.Anthropic()


class ClaudeSaglayici(Saglayici):
    ad = "claude"

    def __init__(self, istemci_getir: Callable[[], anthropic.Anthropic] = istemci, model: str = "",
                 anahtar_getir: Callable[[], str] | None = None, anahtar_env: str = "ANTHROPIC_API_KEY"):
        self.istemci_getir, self.model = istemci_getir, model
        self.anahtar_getir, self.anahtar_env = anahtar_getir, anahtar_env
        self._istemci = None

    def parametreler(self, sistem: str, araclar: list | None = None, *, model: str = "", dusunme: bool = True,
                     sunucu_yedegi: bool = False) -> dict:
        """`messages.stream` parametreleri (mesajlar hariç). Büyük araç girdileri üretilirken akar."""
        params = dict(model=model or self.model, max_tokens=EN_COK_TOKEN, system=sistem,
                      cache_control={"type": "ephemeral"})
        if araclar:
            params["tools"] = [{**spec, "eager_input_streaming": True} for spec in araclar]
        if dusunme:
            params["thinking"] = {"type": "adaptive", "display": "summarized"}
        if sunucu_yedegi:
            # güvenlik sınıflandırıcısı reddederse sunucu önerilen modelle yeniden dener
            params["betas"] = ["server-side-fallback-2026-07-01"]
            params["fallbacks"] = "default"
        return params

    def akis(self, mesajlar: list, sistem: str = "", araclar: list | None = None, *,
             parametreler: dict | None = None, **secenek) -> Iterator[Parca]:
        """Parçalar: METIN, DUSUNCE, diğer her olayda NABIZ; SON'da `son["yanit"]` SDK'nin son mesajı (içerik
        blokları, kullanım, stop_reason).

        Araç çağrıları Claude biçiminde (`tool_use` blokları) yanıtın içindedir; OpenAI biçimine çevrilmez."""
        params = parametreler if parametreler is not None else self.parametreler(sistem, araclar, **secenek)
        if self._istemci is None:
            self._istemci = self.istemci_getir()
        with self._istemci.beta.messages.stream(messages=mesajlar, **params) as akim:
            for olay in akim:
                if olay.type == "text":
                    yield Parca(METIN, olay.text)
                elif olay.type == "thinking":
                    yield Parca(DUSUNCE, olay.thinking)
                else:
                    yield Parca(NABIZ)  # araç girdisi akarken (input_json) de iptal (■ / Esc) denetlensin
            yanit = akim.get_final_message()
        yield Parca(SON, son={"yanit": yanit})

    def saglik(self) -> Saglik:
        anahtar = self.anahtar_getir() if self.anahtar_getir else ""
        if anahtar or os.environ.get(self.anahtar_env):
            return Saglik(True)
        return Saglik(False, "Claude API anahtarı yok")

    def kullanim(self, yanit) -> tuple[int, int]:
        """SDK'nin son mesajındaki `usage`: girdi = düz + önbelleğe yazılan + önbellekten okunan; çıktı."""
        u = getattr(yanit.son.get("yanit"), "usage", None)
        if u is None:
            return 0, 0
        girdi = sum(int(getattr(u, ad, 0) or 0) for ad in
                    ("input_tokens", "cache_creation_input_tokens", "cache_read_input_tokens"))
        return girdi, int(getattr(u, "output_tokens", 0) or 0)
