#!/usr/bin/env python3
"""Claude Code durum çubuğu (statusLine).

Terminalin altında tek satır:
  K3 ████████░░░░ 6/9 %66 │ ▶ yönlendirici testleri │ 23dk · ~11dk kaldı │ bağlam %31 │ Opus

Kaynak: .cafer/ilerleme.json (kaydet.py yazar) + Claude Code'un stdin'e verdiği JSON.
"Kalan süre" kaba tahmindir: biten maddelerin ortalama süresi × kalan madde.
"""
import json
import os
import re
import sys
import time

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass


def stdin_oku():
    try:
        return json.load(sys.stdin)
    except Exception:
        return {}


def proje_koku(veri):
    ws = veri.get("workspace") or {}
    return (
        ws.get("project_dir")
        or ws.get("current_dir")
        or os.environ.get("CLAUDE_PROJECT_DIR")
        or os.getcwd()
    )


def cubuk(oran, genislik=12):
    dolu = int(round(max(0.0, min(1.0, oran)) * genislik))
    return "█" * dolu + "░" * (genislik - dolu)


def sure(sn):
    sn = int(max(0, sn))
    if sn < 60:
        return f"{sn}sn"
    dk = sn // 60
    if dk < 60:
        return f"{dk}dk"
    return f"{dk // 60}sa{dk % 60:02d}dk"


def main():
    veri = stdin_oku()
    kok = proje_koku(veri)
    yol = os.path.join(kok, ".cafer", "ilerleme.json")
    parcalar = []

    il = None
    try:
        with open(yol, encoding="utf-8") as f:
            il = json.load(f)
    except Exception:
        pass

    if il and il.get("toplam"):
        toplam = int(il["toplam"])
        biten = int(il.get("biten", 0))
        oran = biten / toplam if toplam else 0.0
        asama = il.get("asama") or "Görev"
        parcalar.append(f"{asama} {cubuk(oran)} {biten}/{toplam} %{int(oran * 100)}")

        su_an = il.get("su_an")
        if su_an and biten < toplam:
            su_an = re.sub(r"^\s*K\d{1,2}\s*[:\-–]\s*", "", su_an)
            parcalar.append(f"▶ {su_an[:42]}")

        bas = il.get("baslangic")
        if bas:
            try:
                gecen = time.time() - float(bas)
                p = [sure(gecen)]
                if 0 < biten < toplam and gecen >= 60:
                    kalan = gecen / biten * (toplam - biten)
                    p.append(f"~{sure(kalan)} kaldı")
                elif biten >= toplam:
                    p.append("bitti ✔")
                parcalar.append(" · ".join(p))
            except Exception:
                pass
    else:
        parcalar.append("aşama yok · /asama K<n> ile başla")

    ctx = (veri.get("context_window") or {}).get("used_percentage")
    if ctx is not None:
        try:
            parcalar.append(f"bağlam %{int(float(ctx))}")
        except Exception:
            pass

    model = (veri.get("model") or {}).get("display_name")
    if model:
        parcalar.append(str(model))

    sys.stdout.write(" │ ".join(parcalar))


if __name__ == "__main__":
    main()
