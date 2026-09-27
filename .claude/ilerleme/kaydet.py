#!/usr/bin/env python3
"""Claude Code hook: görev listesindeki değişiklikleri .cafer/ilerleme.json'a yazar.

Bağlandığı olaylar (settings.json):
  - PostToolUse  (matcher: TaskCreate|TaskUpdate)  → görev ekle / durum güncelle
  - SessionStart (source: startup | clear)          → sayaç sıfırla (yeni oturum = yeni aşama)

Claude Code her görev aracını çağırdığında bu betik stdin'den JSON alır; hiçbir şey
yazdırmaz, hata verse de Claude Code'u durdurmaz (her şey try/except içinde).
"""
import json
import os
import re
import sys
import time


def oku_stdin():
    try:
        return json.load(sys.stdin)
    except Exception:
        return {}


def yol_bul(veri):
    kok = (
        veri.get("cwd")
        or os.environ.get("CLAUDE_PROJECT_DIR")
        or os.getcwd()
    )
    klasor = os.path.join(kok, ".cafer")
    os.makedirs(klasor, exist_ok=True)
    return os.path.join(klasor, "ilerleme.json")


def yukle(yol):
    try:
        with open(yol, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def kaydet(yol, il):
    gorevler = {k: v for k, v in (il.get("gorevler") or {}).items() if v.get("durum") != "deleted"}
    il["gorevler"] = gorevler
    il["toplam"] = len(gorevler)
    il["biten"] = sum(1 for g in gorevler.values() if g.get("durum") == "completed")
    suanki = [g for g in gorevler.values() if g.get("durum") == "in_progress"]
    il["su_an"] = suanki[-1]["baslik"] if suanki else None
    if not il.get("asama"):
        for g in gorevler.values():
            m = re.search(r"\bK\d{1,2}\b", g.get("baslik", ""))
            if m:
                il["asama"] = m.group(0)
                break
    il["guncelleme"] = time.time()
    try:
        with open(yol, "w", encoding="utf-8") as f:
            json.dump(il, f, ensure_ascii=False, indent=1)
    except Exception:
        pass


def main():
    veri = oku_stdin()
    if not veri:
        return
    yol = yol_bul(veri)
    il = yukle(yol)
    olay = veri.get("hook_event_name")

    if olay == "SessionStart":
        if veri.get("source") in (None, "startup", "clear"):
            il = {"asama": None, "gorevler": {}, "baslangic": time.time()}
            kaydet(yol, il)
        return

    if olay != "PostToolUse":
        return

    arac = veri.get("tool_name", "")
    girdi = veri.get("tool_input") or {}
    cikti = veri.get("tool_output") or veri.get("tool_response") or ""
    if not isinstance(cikti, str):
        cikti = json.dumps(cikti, ensure_ascii=False)

    gorevler = il.setdefault("gorevler", {})
    if not il.get("baslangic"):
        il["baslangic"] = time.time()

    if arac == "TaskCreate":
        m = re.search(r"#(\d+)", cikti)
        gid = m.group(1) if m else str(len(gorevler) + 1)
        gorevler[gid] = {"baslik": girdi.get("subject", "")[:80], "durum": "pending"}

    elif arac == "TaskUpdate":
        gid = str(girdi.get("taskId", ""))
        if gid:
            g = gorevler.setdefault(gid, {"baslik": girdi.get("subject", "")[:80] or f"görev {gid}", "durum": "pending"})
            if girdi.get("subject"):
                g["baslik"] = girdi["subject"][:80]
            if girdi.get("status"):
                g["durum"] = girdi["status"]
                if girdi["status"] == "completed":
                    g["bitis"] = time.time()

    kaydet(yol, il)


if __name__ == "__main__":
    try:
        main()
    except Exception:
        pass
