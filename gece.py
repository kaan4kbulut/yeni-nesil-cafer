#!/usr/bin/env python3
"""
GECE SÜRÜCÜSÜ — kalan işleri sırayla Claude Code'a yaptırır, limit gelince sıfırlanmayı bekler, devam eder.

    python gece.py                # DEVAM → K13 → YAYIN (varsayılan sıra)
    python gece.py K13 YAYIN      # yalnızca bu aşamalar
    python gece.py --tam-yetki    # Claude Code izin sormasın (--dangerously-skip-permissions; yedeği olan repoda)
    python gece.py --model opus   # varsayılan sonnet
    python gece.py --hemen        # çalışan claude oturumunun bitmesini bekleme

Nasıl çalışır:
  - Önce çalışan bir `claude` süreci varsa (senin açık oturumun) bitmesini bekler.
  - Her aşama için NOTLAR/PROMPT-<AD>.md istemini taze `claude -p` oturumuna verir; çıktı NOTLAR/otomatik/gece-<AD>-<n>.log.
  - Çıktıda "SONUÇ:" varsa aşama bitti. Limit görülürse ("hit your … limit", "usage limit"…): sıfırlanma saatini okur
    (okuyamazsa 30 dk), uyur, aynı aşamayı "kaldığın yerden devam et" önsözüyle yeniden başlatır. Aşama başına en fazla 8 deneme.
  - Bitişte ve durunca notify-send ile masaüstü bildirimi; özet NOTLAR/otomatik/gece-ozet.log.
"""
from __future__ import annotations

import argparse
import re
import shutil
import subprocess
import sys
import time
from datetime import datetime, timedelta
from pathlib import Path

KOK = Path(__file__).resolve().parent
NOTLAR = KOK / "NOTLAR"
LOGLAR = NOTLAR / "otomatik"
SIRA = ["DEVAM", "K13", "YAYIN"]

LIMIT_KESIN = re.compile(r"hit your (?:[\w-]+ ){0,3}limit|usage limit", re.I)
LIMIT_GENEL = re.compile(r"rate limit|limit reached|out of (usage|credits|quota)|resets? (at|in)|overloaded|too many requests|"
                         r"not logged in|please (log|sign) in", re.I)

DEVAM_ONSOZ = ("ÖNEMLİ: Bu aşama daha önce kullanım limiti yüzünden yarım kaldı. Önce `git status`, `git stash list` "
               "(varsa `git stash pop`), `git log --oneline -5` ve `.cafer/ilerleme.json` ile nerede kaldığını bul; "
               "bitenleri yeniden yapma, kaldığın yerden sür.\n\n")


def yaz(m: str) -> None:
    s = f"{time.strftime('%H:%M:%S')} {m}"
    print(s, flush=True)
    LOGLAR.mkdir(parents=True, exist_ok=True)
    with open(LOGLAR / "gece-ozet.log", "a", encoding="utf-8") as f:
        f.write(s + "\n")


def bildir(baslik: str, metin: str) -> None:
    if shutil.which("notify-send"):
        subprocess.run(["notify-send", baslik, metin], check=False)


def claude_yolu() -> str:
    y = shutil.which("claude")
    if not y:
        sys.exit("claude bulunamadı (PATH)")
    return y


def claude_calisiyor() -> bool:
    r = subprocess.run(["pgrep", "-x", "claude"], capture_output=True, text=True)
    return r.returncode == 0


def sifirlanma(cikti: str) -> float:
    """Limit metninden bekleme süresi (saniye). Bulunamazsa 30 dk."""
    m = re.search(r"reset\w*\s+in\s+(\d+)\s*(h|hour|m|min)", cikti, re.I)
    if m:
        n = int(m.group(1))
        return (n * 3600 if m.group(2).startswith("h") else n * 60) + 120
    m = re.search(r"reset\w*\s*(?:at\s*)?(\d{1,2})(?::(\d{2}))?\s*(am|pm)?\b", cikti, re.I)
    if m:
        saat, dk, ap = int(m.group(1)), int(m.group(2) or 0), (m.group(3) or "").lower()
        if ap == "pm" and saat < 12:
            saat += 12
        if ap == "am" and saat == 12:
            saat = 0
        simdi = datetime.now()
        hedef = simdi.replace(hour=saat, minute=dk, second=0, microsecond=0)
        if hedef <= simdi:
            hedef += timedelta(days=1)
        return (hedef - simdi).total_seconds() + 120
    return 1800


def limit_mi(cikti: str) -> bool:
    if LIMIT_KESIN.search(cikti):
        return True
    kisa = cikti.strip()
    return len(kisa) < 2500 and bool(LIMIT_GENEL.search(kisa[:1500]) or LIMIT_GENEL.search(kisa[-1500:]))


def oturum(ad: str, prompt: str, n: int, model: str, tam_yetki: bool) -> str:
    cmd = [claude_yolu(), "-p", "--output-format", "text", "--model", model]
    if tam_yetki:
        cmd.append("--dangerously-skip-permissions")
    log = LOGLAR / f"gece-{ad}-{n}.log"
    yaz(f"▶ {ad} deneme {n} (model {model}) → {log.name}")
    with open(log, "w", encoding="utf-8") as f:
        p = subprocess.Popen(cmd, cwd=KOK, stdin=subprocess.PIPE, stdout=f, stderr=subprocess.STDOUT, text=True)
        p.communicate(prompt)
    return log.read_text(encoding="utf-8", errors="replace")


def asama(ad: str, model: str, tam_yetki: bool) -> bool:
    dosya = NOTLAR / f"PROMPT-{ad}.md"
    if not dosya.exists():
        yaz(f"✖ {dosya} yok, atlandı")
        return False
    prompt = dosya.read_text(encoding="utf-8")
    for n in range(1, 9):
        cikti = oturum(ad, (DEVAM_ONSOZ if n > 1 else "") + prompt, n, model, tam_yetki)
        son = [s for s in cikti.splitlines() if s.strip().startswith("SONUÇ")]
        if son:
            yaz(f"✔ {ad}: {son[-1].strip()[:160]}")
            bildir(f"CAFER {ad} bitti", son[-1].strip()[:200])
            return "TAM" in son[-1]
        if limit_mi(cikti):
            bekle = sifirlanma(cikti)
            uyan = (datetime.now() + timedelta(seconds=bekle)).strftime("%H:%M")
            yaz(f"⏳ {ad}: kullanım limiti; {uyan}'e kadar uyuyorum ({int(bekle // 60)} dk)")
            bildir("CAFER limit", f"{ad} durdu; {uyan}'de devam")
            time.sleep(bekle)
            continue
        yaz(f"⚠ {ad}: SONUÇ satırı yok, limit de değil (çıktı {len(cikti)} karakter); 2 dk sonra devam denemesi")
        time.sleep(120)
    yaz(f"✖ {ad}: 8 denemede bitmedi")
    bildir("CAFER durdu", f"{ad} 8 denemede bitmedi")
    return False


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("asamalar", nargs="*", default=SIRA)
    ap.add_argument("--model", default="sonnet")
    ap.add_argument("--tam-yetki", action="store_true")
    ap.add_argument("--hemen", action="store_true")
    a = ap.parse_args()

    if not a.hemen:
        while claude_calisiyor():
            yaz("… açık claude oturumu sürüyor, bitmesini bekliyorum (60 sn)")
            time.sleep(60)
        time.sleep(30)

    yaz(f"=== GECE başladı: {' → '.join(a.asamalar)}")
    for ad in a.asamalar:
        tam = asama(ad, a.model, a.tam_yetki)
        if not tam and ad != "DEVAM":
            yaz(f"■ {ad} TAM değil; sonraki aşamaya geçmiyorum (elle bak: NOTLAR/otomatik/gece-{ad}-*.log)")
            break
    yaz("=== GECE bitti")
    bildir("CAFER gece sürücüsü bitti", "NOTLAR/otomatik/gece-ozet.log")


if __name__ == "__main__":
    main()
