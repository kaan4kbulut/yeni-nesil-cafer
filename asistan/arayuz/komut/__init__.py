"""Komut satırı yüzü (`cafer` / `python -m asistan`): çekirdeği çağırır, Qt yüklemez.

Komutlar: `profil` (donanım profili ve kademe), `gorev` (görev motoru). Sunucu (`sunucu`) K8'de eklenir.
"""

import sys

KOMUTLAR = {"profil": "donanım profili ve kademe (--json, --kilitle <kademe>, --kilidi-ac)",
            "gorev": "\"<istek>\" çok adımlı görev; --liste, --goster/--devam/--onayla/--reddet/--iptal <id>"}


def _yardim() -> str:
    satirlar = ["Kullanım: python -m asistan <komut> [seçenekler]", "", "Komutlar:"]
    satirlar += [f"  {ad:<8} {aciklama}" for ad, aciklama in KOMUTLAR.items()]
    return "\n".join(satirlar)


def ana(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    if not argv or argv[0] in ("-h", "--help", "yardim"):
        print(_yardim())
        return 0
    komut, kalan = argv[0], argv[1:]
    if komut == "profil":
        from ...cekirdek import profil

        return profil.komut(kalan)
    if komut == "gorev":
        from ...cekirdek.gorev import komut as gorev_komutu

        return gorev_komutu.komut(kalan)
    print(f"Bilinmeyen komut: {komut}\n\n{_yardim()}", file=sys.stderr)
    return 2
