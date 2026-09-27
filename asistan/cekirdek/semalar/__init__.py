"""JSON şemaları (docs/SEMALAR.md) ve küçük bir doğrulayıcı.

`jsonschema` paketi kurulum paketinde yok; burada yalnızca şemalarımızın kullandığı alt küme denetlenir: `type` (tek ya
da liste), `required`, `properties`, `additionalProperties: false`, `items`, `enum`, `const`, `minimum`, `minLength`,
`minItems`, `maxItems`, yerel `$ref` (`#/$defs/<ad>`). Bilinmeyen anahtar sessizce geçilir (modelin Ollama `format`
alanına giden şemayla aynı dosya kullanılabilsin).
"""

import json
from functools import cache
from pathlib import Path

KLASOR = Path(__file__).resolve().parent

_TURLER = {"string": str, "integer": int, "number": (int, float), "boolean": bool, "object": dict, "array": list,
           "null": type(None)}


@cache
def _oku(ad: str) -> str:
    return (KLASOR / f"{ad}.json").read_text(encoding="utf-8")


def yukle(ad: str) -> dict:
    """`semalar/<ad>.json` (her çağrıda yeni kopya: çağıran değiştirebilir)."""
    return json.loads(_oku(ad))


def _tur_uyar(deger, tur: str) -> bool:
    beklenen = _TURLER.get(tur)
    if beklenen is None:
        return True
    if tur in ("integer", "number") and isinstance(deger, bool):
        return False
    if tur == "integer" and isinstance(deger, float):
        return deger.is_integer()
    return isinstance(deger, beklenen)


def _coz(sema: dict, kok: dict) -> dict:
    ref = sema.get("$ref")
    if isinstance(ref, str) and ref.startswith("#/"):
        hedef = kok
        for parca in ref[2:].split("/"):
            hedef = hedef[parca]
        return hedef
    return sema


def dogrula(veri, sema: dict, _kok: dict | None = None, _yol: str = "$") -> list[str]:
    """Şemaya uymayan her yer için bir Türkçe hata satırı; boş liste = uyuyor."""
    kok = _kok if _kok is not None else sema
    sema = _coz(sema, kok)
    hatalar: list[str] = []
    tur = sema.get("type")
    if tur is not None:
        turler = tur if isinstance(tur, list) else [tur]
        if not any(_tur_uyar(veri, t) for t in turler):
            return [f"{_yol}: tür {'/'.join(turler)} olmalı ({type(veri).__name__} geldi)"]
    if "const" in sema and veri != sema["const"]:
        hatalar.append(f"{_yol}: {sema['const']!r} olmalı")
    if "enum" in sema and veri not in sema["enum"]:
        hatalar.append(f"{_yol}: şunlardan biri olmalı: {', '.join(map(str, sema['enum']))} ({veri!r} geldi)")
    if isinstance(veri, (int, float)) and not isinstance(veri, bool) and "minimum" in sema and veri < sema["minimum"]:
        hatalar.append(f"{_yol}: en az {sema['minimum']} olmalı")
    if isinstance(veri, str) and len(veri) < sema.get("minLength", 0):
        hatalar.append(f"{_yol}: boş olmamalı")
    if isinstance(veri, dict):
        ozellikler = sema.get("properties") or {}
        for anahtar in sema.get("required") or []:
            if anahtar not in veri:
                hatalar.append(f"{_yol}: '{anahtar}' eksik")
        for anahtar, alt in veri.items():
            if anahtar in ozellikler:
                hatalar += dogrula(alt, ozellikler[anahtar], kok, f"{_yol}.{anahtar}")
            elif sema.get("additionalProperties") is False:
                hatalar.append(f"{_yol}: bilinmeyen alan '{anahtar}'")
    if isinstance(veri, list):
        if len(veri) < sema.get("minItems", 0):
            hatalar.append(f"{_yol}: en az {sema['minItems']} öğe olmalı")
        if "maxItems" in sema and len(veri) > sema["maxItems"]:
            hatalar.append(f"{_yol}: en çok {sema['maxItems']} öğe olmalı")
        if isinstance(sema.get("items"), dict):
            for i, alt in enumerate(veri):
                hatalar += dogrula(alt, sema["items"], kok, f"{_yol}[{i}]")
    return hatalar


def duzlestir(sema: dict) -> dict:
    """Yerel `$ref`'leri açar: Ollama `format` ve OpenAI `json_schema` `$defs` başvurularını her zaman çözmüyor."""
    kok = sema

    def ac(s):
        if isinstance(s, dict):
            s = _coz(s, kok)
            return {k: ac(v) for k, v in s.items() if k not in ("$defs", "$schema", "$id")}
        if isinstance(s, list):
            return [ac(x) for x in s]
        return s

    return ac(sema)
