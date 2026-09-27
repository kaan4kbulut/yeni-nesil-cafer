"""OpenAI uyumlu sağlayıcılar tek dosyada (OpenAI, Gemini, Groq, OpenRouter, DeepSeek, LM Studio…): farklı base_url.

Bağlantı bilgisi `connections.Connection`'dan gelir (ad, base_url, anahtar, modeller). Bağlam aşımında bütçeyi küçültüp
özetleme `Agent`'ta; burada yalnızca istek, akış ayrıştırma ve araç çağrısı parçalarının birleştirilmesi var.
"""

import json
import uuid
from collections.abc import Iterator

import httpx

from .temel import ARAC, DUSUNCE, METIN, NABIZ, SON, Parca, Saglayici, SaglayiciHatasi, Saglik


class OpenAIUyumluSaglayici(Saglayici):
    def __init__(self, baglanti, model: str = ""):
        """`baglanti`: `connections.Connection` (name, base_url, key, models, usable, id)."""
        self.baglanti = baglanti
        self.ad = f"api:{baglanti.id}"
        self.model = model or (baglanti.models[0] if baglanti.models else "")

    @property
    def sohbet_adresi(self) -> str:
        return self.baglanti.base_url.rstrip("/") + "/chat/completions"

    def basliklar(self) -> dict:
        anahtar = self.baglanti.key
        return {"Authorization": f"Bearer {anahtar}"} if anahtar else {}

    def istek(self, mesajlar: list, sistem: str = "", araclar: list | None = None, *, model: str = "",
              json_bicimi: bool = False) -> dict:
        payload = {"model": model or self.model,
                   "messages": [{"role": "system", "content": sistem}, *mesajlar] if sistem else list(mesajlar),
                   "stream": True}
        if json_bicimi:
            payload["response_format"] = {"type": "json_object"}
        if araclar:
            payload["tools"] = araclar
        return payload

    def akis(self, mesajlar: list, sistem: str = "", araclar: list | None = None, *, govde: dict | None = None,
             **secenek) -> Iterator[Parca]:
        """Parçalar: METIN, DUSUNCE, ARAC; SON'da birleşmiş araç çağrıları, `son["usage"]`, `son["parca"]` (sayı).

        HTTP hatası `SaglayiciHatasi` (durum + gövde): çağıran bağlam aşımını ya da 401'i ayırt eder."""
        payload = govde if govde is not None else self.istek(mesajlar, sistem, araclar, **secenek)
        ad = self.baglanti.name
        calls, usage, parca = {}, {}, 0
        with httpx.stream("POST", self.sohbet_adresi, json=payload, headers=self.basliklar(),
                          timeout=httpx.Timeout(600, connect=15)) as resp:
            if resp.status_code != 200:
                resp.read()
                raise SaglayiciHatasi(resp.status_code, resp.text, ad)
            for line in resp.iter_lines():
                if not line.startswith("data:"):
                    yield Parca(NABIZ)  # boş satır ya da ": PROCESSING" yorumu: iptal denetlensin
                    continue
                data = line[5:].strip()
                if data == "[DONE]":
                    break
                chunk = json.loads(data)
                if chunk.get("error"):
                    raise RuntimeError(f"{ad} hatası: {chunk['error']}")
                usage = chunk.get("usage") or (chunk.get("x_groq") or {}).get("usage") or usage
                yield Parca(NABIZ)
                for choice in chunk.get("choices") or []:
                    delta = choice.get("delta") or {}
                    dusunce = delta.get("reasoning_content") or delta.get("reasoning")
                    if dusunce:
                        yield Parca(DUSUNCE, dusunce)
                    if delta.get("content"):
                        parca += 1
                        yield Parca(METIN, delta["content"])
                    # araç çağrıları parça parça gelir; index ile birleştirilir
                    for tc in delta.get("tool_calls") or []:
                        parca += 1
                        slot = calls.setdefault(tc.get("index", len(calls)), {
                            "id": "", "type": "function", "function": {"name": "", "arguments": ""}})
                        if tc.get("id"):
                            slot["id"] = tc["id"]
                        fn = tc.get("function") or {}
                        slot["function"]["name"] += fn.get("name") or ""
                        slot["function"]["arguments"] += fn.get("arguments") or ""
                        yield Parca(ARAC)
        tool_calls = [calls[i] for i in sorted(calls)]
        for tc in tool_calls:
            tc["id"] = tc["id"] or uuid.uuid4().hex
        yield Parca(SON, araclar=tool_calls, son={"usage": usage, "parca": parca})

    def saglik(self) -> Saglik:
        if not self.baglanti.usable:
            return Saglik(False, f"{self.baglanti.name}: anahtar yok ya da reddedildi")
        if not self.model:
            return Saglik(False, f"{self.baglanti.name} için model seçilmemiş")
        return Saglik(True)

    def maliyet(self, girdi_token: int, cikti_token: int, model: str = "") -> float | None:
        return None  # fiyat listesi K3'te (ayar/modeller.json); bilinmiyor
