"""Ollama sağlayıcısı: `/api/chat` akışı, kurulu ve bellekteki modeller, sağlık denetimi.

Bağlam kırpma, düşünme sınırı, tekrar kesme ve takılma yeniden denemesi `Agent`'ta kalır (akış parçalarına bakar).
"""

import json
import time
from collections.abc import Iterator

import httpx

from .temel import ARAC, DUSUNCE, METIN, NABIZ, SON, Parca, Saglayici, SaglayiciHatasi, Saglik

VARSAYILAN_URL = "http://localhost:11434"
OKUMA_ZAMAN_ASIMI = 150  # tek parça gelmeden geçebilecek en uzun süre (agent.STALL_SECONDS ile aynı)
BELLEKTE_TUT = "30m"  # modeli bellekte tut; her mesajda yeniden yüklenmesin


class AracDesteklenmiyor(Exception):
    """Seçili model araç çağrısını desteklemiyor (Ollama 400: "does not support tools")."""


def _kok(url: str) -> str:
    url = (url or VARSAYILAN_URL).rstrip("/")
    return url.removesuffix("/api/chat")


def modeller(url: str) -> list[dict]:
    """Kurulu modeller (/api/tags): name, size, details{parameter_size, quantization_level}."""
    resp = httpx.get(_kok(url) + "/api/tags", timeout=5)
    resp.raise_for_status()
    return resp.json().get("models", [])


def model_adlari(url: str) -> list[str]:
    return [m["name"] for m in modeller(url)]


def bellekteki_modeller(url: str) -> list[dict]:
    """Bellekteki modeller (/api/ps): size ve size_vram ile GPU/CPU payı hesaplanır."""
    resp = httpx.get(_kok(url) + "/api/ps", timeout=2)
    resp.raise_for_status()
    return resp.json().get("models", [])


class OllamaSaglayici(Saglayici):
    ad = "ollama"

    def __init__(self, url: str = VARSAYILAN_URL, model: str = ""):
        self.url, self.model = _kok(url), model

    @property
    def sohbet_adresi(self) -> str:
        return self.url + "/api/chat"

    def istek(self, mesajlar: list, sistem: str = "", araclar: list | None = None, *, model: str = "",
              num_ctx: int | None = None, num_predict: int | None = None, dusunme: bool = True,
              bicim: dict | str | None = None) -> dict:
        """`/api/chat` gövdesi (araçlar Ollama/OpenAI biçiminde)."""
        from .. import donanim

        secenek = {k: v for k, v in (("num_ctx", num_ctx), ("num_predict", num_predict),
                                     ("num_gpu", donanim.num_gpu_icin(model or self.model))) if v is not None}  # K13
        return {
            "model": model or self.model,
            "messages": [{"role": "system", "content": sistem}, *mesajlar] if sistem else list(mesajlar),
            **({"tools": araclar} if araclar else {}),
            "stream": True,
            **({"format": bicim} if bicim else {}),
            **({"options": secenek} if secenek else {}),
            **({"think": False} if not dusunme else {}),
            "keep_alive": BELLEKTE_TUT,
        }

    def akis(self, mesajlar: list, sistem: str = "", araclar: list | None = None, *,
             okuma_zaman_asimi: float = OKUMA_ZAMAN_ASIMI, govde: dict | None = None, **secenek) -> Iterator[Parca]:
        """Parçalar: METIN, DUSUNCE, ARAC, içi boş satırda NABIZ; en sonda SON (araclar = araç çağrıları, son = Ollama'nın
        son parçası).

        `govde` verilirse istek olduğu gibi gönderilir (çağıran bağlamı kendisi kırptıysa)."""
        payload = govde if govde is not None else self.istek(mesajlar, sistem, araclar, **secenek)
        tool_calls, son, bos = [], {}, True
        basladi = time.monotonic()
        with httpx.stream("POST", self.sohbet_adresi, json=payload,
                          timeout=httpx.Timeout(600, connect=10, read=okuma_zaman_asimi)) as resp:
            if resp.status_code != 200:
                resp.read()
                if payload.get("tools") and "does not support tools" in resp.text:
                    raise AracDesteklenmiyor()
                raise SaglayiciHatasi(resp.status_code, resp.text, "Ollama")
            for line in resp.iter_lines():
                if not line:
                    yield Parca(NABIZ)
                    continue
                chunk = json.loads(line)
                if "error" in chunk:
                    raise RuntimeError(f"Ollama hatası: {chunk['error']}")
                msg = chunk.get("message", {})
                verdi = False  # bu satırdan parça çıktı mı (çıkmadıysa nabız: iptal denetlensin)
                if msg.get("thinking"):
                    bos, verdi = False, True
                    yield Parca(DUSUNCE, msg["thinking"])
                if msg.get("content"):
                    bos, verdi = False, True
                    yield Parca(METIN, msg["content"])
                if msg.get("tool_calls"):
                    bos, verdi = False, True
                    tool_calls.extend(msg["tool_calls"])
                    yield Parca(ARAC, araclar=list(msg["tool_calls"]))
                if bos and time.monotonic() - basladi > okuma_zaman_asimi:
                    raise httpx.ReadTimeout("boş parçalar geliyor")  # akış sürüyor ama içi boş: takılma sayılır
                if chunk.get("done"):
                    son = chunk
                elif not verdi:
                    yield Parca(NABIZ)
        yield Parca(SON, araclar=tool_calls, son=son)

    def saglik(self) -> Saglik:
        try:
            resp = httpx.get(self.url + "/api/tags", timeout=3)
        except httpx.HTTPError as e:
            return Saglik(False, f"Ollama'ya bağlanılamadı ({type(e).__name__})")
        if resp.status_code != 200:
            return Saglik(False, f"Ollama {resp.status_code} döndü")
        if self.model and self.model not in {m.get("name") for m in resp.json().get("models", [])}:
            return Saglik(False, f"{self.model} kurulu değil")
        return Saglik(True)
