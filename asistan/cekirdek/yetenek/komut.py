"""`python -m asistan yetenek …`: yetenek kayıt defteri komut satırından (MIMARI §6; `/kontrol` 8–9, `/yetenek-ekle`).

  yetenek                  liste: ✓ aktif / ○ pasif (nedeni), izinler, kaynak
  yetenek --json           liste JSON
  yetenek --dogrula        manifest doğrulama; geçersiz manifest varsa çıkış kodu 1
  yetenek --duman [ad …]   manifestteki örnekleri gerçekten çalıştırır (her örnek ayrı geçici çalışma klasöründe;
                           yeteneğin `ornek_dosyalar/` klasörü oraya kopyalanır); başarısız varsa çıkış kodu 1

Duman testinde her çağrı yine izin hattından geçer (kullanıcı kipi). Yerleşik ve güvenilir yeteneklerin örneklerini
program yazdığı için onları onaylı sayar; programla gelmeyen ya da güvenilmeyen yeteneğin örneği onaysız çalışmaz,
"onay bekliyor" diye raporlanır (sessizce geçilmez).
"""

import json
import shutil
import sys
import tempfile
import time
from dataclasses import replace

from .kayit import Kayit

IZIN_KISA = {"ag": "ağ", "dosya_oku": "oku", "dosya_yaz": "yaz", "dosya_sil": "sil", "komut": "komut"}


def liste_metni(kayit: Kayit) -> str:
    satirlar = []
    for y in kayit.tara():
        izin = ",".join(IZIN_KISA.get(i, i) for i in y.izinler) or "-"
        ek = "" if y.aktif else f"  — {y.neden}"
        uretilen = " [üretildi, güvenilmez]" if y.kaynak == "uretildi" and not y.guvenilir else ""
        satirlar.append(f"{'✓' if y.aktif else '○'} {y.ad:<18} {izin:<24} {y.kaynak:<9}"
                        f"{' sandbox' if y.sandbox else ''}{uretilen}{ek}")
    aktif = len(kayit.aktifler())
    satirlar.append(f"\n{aktif} aktif · {len(kayit.tara()) - aktif} pasif")
    return "\n".join(satirlar)


def dogrula(kayit: Kayit) -> int:
    bozuk = [y for y in kayit.tara() if y.hatalar]
    for y in kayit.tara():
        print(f"{'✗' if y.hatalar else '✓'} {y.ad}" + (": " + "; ".join(y.hatalar[:3]) if y.hatalar else ""))
    print(f"\n{len(kayit.tara()) - len(bozuk)} geçerli · {len(bozuk)} geçersiz manifest")
    return 1 if bozuk else 0


def duman(kayit: Kayit, adlar: list[str] | None = None, ayarlar=None) -> int:
    """Örnekleri koşar; (başarısız + geçersiz manifest) sayısı > 0 ise 1."""
    from ...config import Settings
    from ..gorev.ajan import AjanYetenekleri
    from ..gorev.dogrulayici import _BASARISIZ

    temel = replace(ayarlar or Settings.load(), approval_mode="kullanici", confirm_commands=True)
    kalan = 0
    for y in kayit.tara():
        if adlar and y.ad not in adlar:
            continue
        if not y.aktif:
            print(f"○ {y.ad}: pasif — {y.neden}")
            kalan += bool(y.hatalar)
            continue
        onayli = y.kaynak == "yerlesik" and y.guvenilir
        for i, ornek in enumerate(y.manifest.get("ornekler") or [], 1):
            klasor = tempfile.mkdtemp(prefix=f"yetenek-duman-{y.ad}-")
            try:
                if (y.klasor / "ornek_dosyalar").is_dir():
                    shutil.copytree(y.klasor / "ornek_dosyalar", klasor, dirs_exist_ok=True)
                yet = AjanYetenekleri(replace(temel, workspace=klasor), [], klasor, [klasor], kayit=kayit)
                basla = time.monotonic()
                c = yet.calistir(y.ad, ornek["girdi"], onayli=onayli)
                sure = time.monotonic() - basla
            finally:
                shutil.rmtree(klasor, ignore_errors=True)
            metin = (c.metin or "").strip()
            tamam = not c.hata and not c.onay_bekliyor and bool(metin) and not _BASARISIZ.match(metin)
            durum = "✅" if tamam else ("⏸ onay bekliyor" if c.onay_bekliyor else "❌")
            kalan += not tamam
            print(f"{durum} {y.ad} örnek {i} ({sure:.1f} sn) — beklenen: {ornek['beklenen']}")
            if not tamam or "-v" in (adlar or []):
                print("   " + " ".join(metin.split())[:300])
    print(f"\n{'Hepsi geçti.' if not kalan else f'{kalan} sorun var.'}")
    return 1 if kalan else 0


def komut(argv: list[str]) -> int:
    if argv and argv[0] in ("-h", "--help"):
        print(__doc__)
        return 0
    kayit = Kayit()
    secenek = argv[0] if argv else ""
    if secenek == "--json":
        print(json.dumps(kayit.listele(), ensure_ascii=False, indent=1))
        return 0
    if secenek == "--dogrula":
        return dogrula(kayit)
    if secenek == "--duman":
        return duman(kayit, argv[1:] or None)
    if secenek:
        print(f"Bilinmeyen seçenek: {secenek}\n{__doc__}", file=sys.stderr)
        return 2
    print(liste_metni(kayit))
    return 0
