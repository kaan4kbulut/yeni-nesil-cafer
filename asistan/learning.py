"""Öğrenme: kalıcı hafıza, beceri kütüphanesi ve gelişim kayıtları (hepsi kullanıcının veri klasöründe).

- Hafıza: kullanıcının tercihleri, onun ve bu bilgisayar hakkında bilgiler, öğrenilen dersler. Her sohbette
  bütün ajanlara verilir; asistan `remember` aracıyla ekler, kullanıcı görüp siler.
- Beceriler: ✓ ile başlatılıp doğrulanarak biten işlerin işe yarayan yöntemi (çalışan kod ve adımlar). Benzer bir
  istek gelince asistana "bu daha önce işe yaradı" diye verilir; küçük modellerin başarısını artırır.
- Başarısızlıklar: yönetici bir adımı tamamlatamazsa neyin neden olmadığı kaydedilir; benzer iş planlanırken
  işe yarayan tariflerle birlikte yöneticiye verilir (planning_prompt).
- Hafıza, beceri ve başarısızlıklar SQLite'ta anlamsal aramayla durur (memory_db.py); eski JSON dosyaları bir kez
  içe aktarılır.
- Gelişim: tamamlanamayan işler, hatalar ve "beğenmedim"ler. Birikince kullanıcı uyarılır; rapor için modele
  verilir. Program kendi kodunu kendiliğinden değiştirmez: öneriler kullanıcıya gösterilir.
"""

import hashlib
import json
import re
import threading
import time
import uuid
from pathlib import Path

from . import memory_db
from .config import DATA_DIR

MEMORY_FILE = DATA_DIR / "hafiza.json"
SKILLS_FILE = DATA_DIR / "beceriler.json"
GROWTH_FILE = DATA_DIR / "gelisim.jsonl"
GROWTH_STATE = DATA_DIR / "gelisim-durum.json"

MEMORY_KINDS = {"tercih": "Tercih", "bilgi": "Bilgi", "ders": "Ders", "ekipman": "Ekipman"}
ALWAYS_KINDS = ("tercih", "ekipman")  # her istekte talimata girer (yazıcı bilgisi "telefon tutucu yap"da da gerekir)
MAX_MEMORIES = 150
MAX_SKILLS = 120
_lock = threading.Lock()  # aynı anda birden çok ajan yazabilir (ekip görevleri)


def _read(path: Path, default):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return default


def _write(path: Path, data) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
    tmp.replace(path)  # yarım yazılmış dosya kalmasın


def _norm(text: str) -> str:
    return " ".join(re.sub(r"[^\w\s]", " ", (text or "").casefold()).split())


def _stems(text: str) -> set[str]:
    """Türkçe ekler için kaba kök: kelimenin ilk 5 harfi ("ciroyu", "cirolar" → "ciroy"/"ciro")."""
    return {w[:5] for w in _norm(text).split() if len(w) >= 3 and not w.isdigit()} - _STOP


_STOP = {"bir", "bu", "ve", "ile", "için", "icin", "gibi", "daha", "sonr", "sonra", "kadar", "şimdi", "şimd",
         "bana", "benim", "dosya", "yap", "yapa", "hesap", "olan", "olar", "her", "tüm", "tum", "istiy", "lütfe",
         "the", "and", "with", "from", "that", "this"}


# ---------------------------------------------------------------- hafıza (SQLite + anlamsal arama: memory_db.py)

# eşikler nomic-embed-text ile Türkçe örneklerde ölçüldü (2026-09-25). Sorgu→belge: benzer iş 0.67-0.74, ilgili
# bilgi ~0.65, ilgisiz 0.46-0.55. Belge→belge: aynı bilgi 0.92-0.97, benzer ama farklı iş 0.76-0.81.
SEM_DUPLICATE = 0.88  # belge-belge: yeni kayıt eskisinin güncellenmiş hali sayılır
SEM_SAME_JOB = 0.85  # belge-belge: beceri aynı türden iş (son çalışan yöntem eskisinin yerine geçer)
SEM_RELEVANT = 0.60  # sorgu-belge: hafıza talimata girer
SEM_SKILL = 0.62  # sorgu-belge: beceri "benzer iş" sayılır
SEM_FAILURE = 0.62
MAX_FAILURES = 200


def _migrate() -> None:
    """Eski JSON dosyalarını (hafiza.json, beceriler.json) bir kez veritabanına aktarır; dosyalar silinmez."""
    if memory_db.meta("json_import"):
        return
    with _lock:
        if memory_db.meta("json_import"):
            return
        for m in _read(MEMORY_FILE, []):
            if m.get("text"):
                memory_db.put(m.get("kind") if m.get("kind") in MEMORY_KINDS else "bilgi", m["text"], {},
                              m.get("id"), m.get("created"))
        for sk in _read(SKILLS_FILE, []):
            if sk.get("request"):
                data = {k: v for k, v in sk.items() if k not in ("id", "request", "created", "updated")}
                memory_db.put("beceri", sk["request"], data, sk.get("id"), sk.get("created"))
        memory_db.meta("json_import", str(time.time()))


def _keyword(query: str, item: dict) -> float:
    """Embedding yokken: kelime kökü örtüşmesi (eski arama). 3'ten az ortak kök 0 sayılır."""
    want, have = _stems(query), _stems(item.get("text", ""))
    common = want & have
    return len(common) / max(len(want), 1) if len(common) >= 3 or (common and len(want) <= 2) else 0.0


def _similar(kinds: tuple, text: str) -> dict | None:
    """Aynı ya da çok benzer kayıt (güncellemek için)."""
    if memory_db.semantic():
        hit = memory_db.search(text, kinds, k=1, min_score=SEM_DUPLICATE, task="document")
        if hit:
            return hit[0][1]
    new = _stems(text)
    for item in memory_db.items(kinds):
        old = _stems(item["text"])
        if _norm(item["text"]) == _norm(text) or (new and old and len(new & old) / len(new | old) >= 0.8):
            return item
    return None


def memories() -> list[dict]:
    _migrate()
    return memory_db.items(tuple(MEMORY_KINDS))


def remember(text: str, kind: str = "bilgi") -> str:
    """Hafızaya ekler; aynısı ya da çok benzeri varsa günceller. Kullanıcıya gösterilecek kısa sonuç döner."""
    _migrate()
    text = " ".join(str(text or "").split())[:300]
    if len(text) < 4:
        return "Boş bilgi kaydedilmedi."
    kind = kind if kind in MEMORY_KINDS else "bilgi"
    with _lock:
        old = _similar(tuple(MEMORY_KINDS), text)
        if old:
            memory_db.put(kind, text, {}, old["id"], old["created"])
            return f"Hafızadaki bilgi güncellendi: {text}"
        memory_db.put(kind, text)
        memory_db.trim(kind, MAX_MEMORIES)
    return f"Hafızaya eklendi ({MEMORY_KINDS[kind].lower()}): {text}"


def forget(memory_id: str) -> None:
    memory_db.delete(memory_id)


def memory_prompt(query: str = "", limit_chars: int = 2500) -> str:
    """Talimata eklenecek hafıza: tercihler her zaman (en yeniler önce), bilgiler ve dersler isteğe göre en ilgili
    olanlar (anlamsal arama); istek yoksa ya da ilgili bulunamazsa en yeniler. Bağlamı doldurmasın diye sınırlı."""
    items = memories()
    if not items:
        return ""
    prefs = [m for m in reversed(items) if m["kind"] in ALWAYS_KINDS]
    others = [m for m in items if m["kind"] not in ALWAYS_KINDS]
    relevant = []
    if query.strip() and others:
        found = memory_db.search(query, ("bilgi", "ders"), k=10,
                                 min_score=SEM_RELEVANT if memory_db.semantic() else 0.2, keyword_score=_keyword)
        relevant = [m for _, m in found]
    chosen = prefs + relevant + [m for m in reversed(others) if m not in relevant]
    lines, size = [], 0
    for item in chosen:
        line = f"- [{MEMORY_KINDS.get(item['kind'], 'Bilgi')}] {item['text']}"
        if size + len(line) > limit_chars:
            break
        lines.append(line)
        size += len(line)
    return ("\n\n## Long-term memory (what you learned about the user and this computer)\nFollow these preferences "
            "and use these facts; they come from earlier conversations.\n" + "\n".join(lines))


# ---------------------------------------------------------------- beceriler

def _skill(item: dict) -> dict:
    """Veritabanı kaydı → eski beceri sözlüğü (pencereler ve istemler bu biçimi kullanır)."""
    return {"uses": 0, "successes": 1, "failures": 0, "code": "", "steps": [], "model": "",
            **item, "request": item["text"], "title": item.get("title") or item["text"][:90]}


def skills() -> list[dict]:
    _migrate()
    return [_skill(i) for i in memory_db.items(("beceri",))]


def save_skill(request: str, steps: list[tuple[str, dict]], model: str = "") -> dict | None:
    """Başarıyla biten bir işin yöntemini kaydeder (benzer beceri varsa onu günceller)."""
    _migrate()
    request = " ".join(str(request or "").split())
    useful = [(n, a) for n, a in steps if n in ("run_python", "write_file", "edit_file", "run_command", "call_api")]
    if not request or not useful:
        return None
    code = "\n\n".join(a.get("code", "") for n, a in useful if n == "run_python" and a.get("code"))[-6000:]
    other = [{"tool": n, "args": {k: (v if len(str(v)) < 400 else str(v)[:400] + "…") for k, v in a.items()
                                  if k != "purpose"}} for n, a in useful if n != "run_python"][-8:]
    title = re.split(r"(?<=[.!?])\s", request)[0][:90]
    with _lock:
        old = None
        if memory_db.semantic():
            hit = memory_db.search(request, ("beceri",), k=1, min_score=SEM_SAME_JOB, task="document")
            old = hit[0][1] if hit else None
        else:
            new = _stems(request)
            old = next((i for i in memory_db.items(("beceri",)) if new and _stems(i["text"]) and
                        len(new & _stems(i["text"])) / len(new | _stems(i["text"])) >= 0.7), None)
        data = {"title": title, "code": code, "steps": other, "model": model}
        if old:  # aynı türden iş: son çalışan yöntem kalsın
            data.update(uses=old.get("uses", 0), successes=old.get("successes", 0) + 1,
                        failures=old.get("failures", 0))
            return _skill(memory_db.put("beceri", request, data, old["id"], old["created"]))
        item = memory_db.put("beceri", request, {**data, "uses": 0, "successes": 1, "failures": 0})
        memory_db.trim("beceri", MAX_SKILLS)
    return _skill(item)


def delete_skill(skill_id: str) -> None:
    memory_db.delete(skill_id)


def find_skills(request: str, k: int = 2) -> list[dict]:
    """İsteğe en çok benzeyen, iyi sonuç vermiş beceriler; zayıf eşleşmeler verilmez."""
    _migrate()
    if len(_stems(request)) < 2:
        return []
    semantic = memory_db.semantic()
    found = memory_db.search(request, ("beceri",), k=k + 3, min_score=SEM_SKILL if semantic else 0.35,
                             keyword_score=_keyword)
    out = [_skill(i) for _, i in found if i.get("failures", 0) <= i.get("successes", 1) + 1]
    return out[:k]


def skills_prompt(found: list[dict]) -> str:
    if not found:
        return ""
    parts = []
    for item in found:
        body = f"### {item['title']}\nEarlier request: {item['request'][:400]}\n"
        if item.get("code"):
            body += f"Working code (ran successfully):\n```python\n{item['code'][:2500]}\n```\n"
        if item.get("steps"):
            body += "Other steps: " + json.dumps(item["steps"], ensure_ascii=False)[:800] + "\n"
        parts.append(body)
    return ("\n\n## Methods that worked before for similar requests\nAdapt them to the current request (file names, "
            "columns and details may differ — check the real data first); don't copy blindly.\n\n" + "\n".join(parts))


def record_skill_result(skill_ids: list[str], success: bool) -> None:
    for sid in skill_ids or []:
        item = memory_db.get(sid)
        if item:
            key = "successes" if success else "failures"
            memory_db.update_data(sid, uses=item.get("uses", 0) + 1, **{key: item.get(key, 0) + 1})


# ---------------------------------------------------------------- başarısızlıklar (hangi yol neden işe yaramadı)

def record_failure(request: str, step: str, reason: str, tools: list[str] | None = None, model: str = "") -> None:
    """Başarısız bir adımı ders olarak kaydeder; benzer iş planlanırken yöneticiye gösterilir."""
    _migrate()
    step, reason = " ".join(str(step or "").split())[:300], " ".join(str(reason or "").split())[:300]
    if not step:
        return
    text = f"{step} — {reason}" if reason else step
    data = {"request": original_request(request)[:400], "step": step, "reason": reason, "tools": tools or [],
            "model": model}
    with _lock:
        old = _similar(("hata",), text)
        if old:
            data["count"] = old.get("count", 1) + 1
            memory_db.put("hata", text, data, old["id"], old["created"])
        else:
            memory_db.put("hata", text, {**data, "count": 1})
            memory_db.trim("hata", MAX_FAILURES)


def failures() -> list[dict]:
    _migrate()
    return memory_db.items(("hata",))


def find_failures(request: str, k: int = 3) -> list[dict]:
    _migrate()
    found = memory_db.search(request, ("hata",), k=k, min_score=SEM_FAILURE if memory_db.semantic() else 0.35,
                             keyword_score=_keyword)
    return [i for _, i in found]


def planning_prompt(request: str) -> str:
    """Yöneticinin planına girecek dersler: işe yarayan tarifler ve daha önce başarısız olan yollar."""
    parts = []
    for sk in find_skills(request, 2):
        steps = ", ".join(s.get("tool", "") for s in sk.get("steps", [])) or ("run_python" if sk.get("code") else "")
        parts.append(f"- WORKED before ({sk.get('successes', 1)}x) for \"{sk['request'][:160]}\"" +
                     (f" using {steps}" if steps else ""))
    for f in find_failures(request, 3):
        parts.append(f"- FAILED before ({f.get('count', 1)}x): {f['text'][:260]}" +
                     (f" [model: {f['model']}]" if f.get("model") else ""))
    if not parts:
        return ""
    return ("Lessons from earlier similar jobs (reuse what worked, plan around what failed):\n" + "\n".join(parts)
            + "\n\n")


def original_request(text: str) -> str:
    """"▶ Onaylıyorum…: «istek»…" / "↻ … «istek»" mesajlarından asıl isteği çıkarır."""
    text = (text or "").split("\n\n[Ek")[0]
    m = re.search(r"«(.*)»", text, re.S)
    return (m.group(1) if m and text.startswith(("▶", "↻")) else text).strip()


# ---------------------------------------------------------------- gelişim

def log_issue(kind: str, request: str, model: str, detail: str = "") -> None:
    """kind: tamamlanamadi · hata · begenilmedi · bos_cevap"""
    if str(request or "").startswith("📈"):  # gelişim raporu isteğinin kendisi sorun kaydı sayılmaz
        return
    entry = {"time": time.time(), "kind": kind, "request": " ".join(str(request or "").split())[:600],
             "model": model, "detail": str(detail or "")[-1500:]}
    with _lock:
        GROWTH_FILE.parent.mkdir(parents=True, exist_ok=True)
        with GROWTH_FILE.open("a", encoding="utf-8") as f:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")


def issues(since: float = 0) -> list[dict]:
    try:
        lines = GROWTH_FILE.read_text(encoding="utf-8").splitlines()
    except OSError:
        return []
    out = []
    for line in lines:
        try:
            item = json.loads(line)
        except ValueError:
            continue
        if item.get("time", 0) > since:
            out.append(item)
    return out


REPORT_FILE = DATA_DIR / "gelisim-raporu.md"


def save_report(text: str) -> None:
    text = re.sub(r"(?m)^\*\(.*?\)\*\s*$\n?", "", text).strip()  # program notları ("…doğrudan cevaplıyorum") rapora girmesin
    REPORT_FILE.parent.mkdir(parents=True, exist_ok=True)
    REPORT_FILE.write_text(text, encoding="utf-8")
    mark_reported()


def last_report() -> str:
    try:
        return REPORT_FILE.read_text(encoding="utf-8")
    except OSError:
        return ""


def last_report_time() -> float:
    return _read(GROWTH_STATE, {}).get("last_report", 0)


def mark_reported() -> None:
    _write(GROWTH_STATE, {**_read(GROWTH_STATE, {}), "last_report": time.time()})


def new_issue_count() -> int:
    return len(issues(last_report_time()))


ISSUE_NAMES = {"tamamlanamadi": "tamamlanamadı", "hata": "hata verdi", "begenilmedi": "beğenilmedi",
               "bos_cevap": "cevap üretilemedi"}


def report_request(program_dir: str, installed_models: list[str]) -> str:
    """Gelişim raporu için asistana verilecek istek (yalnızca yazı; hiçbir şey değiştirmez)."""
    items = issues(last_report_time()) or issues()[-30:]
    lines = []
    for n, item in enumerate(items[-30:], 1):
        when = time.strftime("%d.%m %H:%M", time.localtime(item["time"]))
        lines.append(f"{n}. [{when}] {ISSUE_NAMES.get(item['kind'], item['kind'])} · model: {item['model'] or '?'}\n"
                     f"   istek: {item['request'][:300]}\n   ayrıntı: {item['detail'][-500:] or '-'}")
    memo = "\n".join(f"- {m['text']}" for m in memories()[-15:]) or "-"
    return (
        "📈 GELİŞİM RAPORU İSTEĞİ — hiçbir aracı çalıştırma, hiçbir şeyi değiştirme; yalnızca raporu yaz.\n\n"
        "Aşağıda bu programda (YENİ NESİL CAFER) son zamanlarda tamamlanamayan, hata veren ya da kullanıcının "
        "beğenmediği işler var. İnceleyip Türkçe, kısa ve somut bir gelişim raporu yaz. TAM OLARAK şu dört başlığı, "
        "bu sırayla kullan; her bölüm en fazla 5 madde olsun:\n\n"
        "## 1. Özet\n(kaç sorun, ortak desenler)\n\n"
        "## 2. Nedenler\n(her sorun için: modelin gücü mü yetmedi, bir yetenek/araç mı eksik, programda bir hata mı?)\n\n"
        "## 3. Senin hemen yapabileceklerin\n(ör. daha güçlü bir model indirmek — kurulu modeller: "
        f"{', '.join(installed_models) or 'bilinmiyor'} —, ücretsiz bir bulut modeline bağlanmak, isteği bölmek)\n\n"
        "## 4. Programa önerilen geliştirmeler\n(öncelik sırasıyla; her biri için: ne eklenmeli/düzeltilmeli, "
        "neden, nasıl — bir geliştirici (Claude Code) doğrudan uygulayabilecek kadar açık)\n\n"
        f"Programın klasörü: {program_dir}\n\nBilinen tercihler ve dersler:\n{memo}\n\nSorunlar:\n"
        + "\n".join(lines)
    )


def developer_request(report: str, program_dir: str) -> str:
    """Kullanıcı onaylarsa Claude Code'a verilecek geliştirme talebi."""
    return (
        f"YENİ NESİL CAFER projesi ({program_dir}) için aşağıdaki gelişim raporundaki 'Programa eklenmesi önerilen "
        "geliştirmeler' bölümünü uygula. Önce kodu incele ve bana bir plan sun; her değişiklik için onayımı iste. "
        "Kodun mevcut üslubuna (Türkçe yorumlar) uy, programın 'önce ▶ uygula düğmesi, sonra adım adım onay' "
        "kuralını bozma ve değişikliklerden sonra programın açıldığını doğrula.\n\n--- RAPOR ---\n" + report
    )


# ---------------------------------------------------------------- projeler
# Her sohbetin iş klasörü hafızada "proje" kaydıdır: yeni bir sohbette "3D projeme devam et" denince doğru klasör
# bulunur; devam isteği yoksa yeni iş kendi klasörünü açar, eski projelere dokunulmaz.
SEM_PROJECT = 0.62  # sorgu-belge: istek bu projenin devamı sayılır
SEM_PROJECT_LOW = 0.52  # bu puanla ancak ortak bir konu kelimesi varsa (nomic-embed-text, 2026-09-26 ölçümü)
_CONTINUE_STEMS = {"devam", "kaldı", "yerde", "sürdü", "proje", "önce", "geçen", "edeli", "çalış"}
_CONTINUE = re.compile(r"devam|kaldığı|sürdür|önceki|geçen (gün|sefer|hafta)|projem|projesin|üzerinde çalıştığı",
                       re.I)


def _project_id(folder: str) -> str:
    return "p-" + hashlib.md5(folder.encode()).hexdigest()[:10]


def save_project(folder: str, title: str, request: str, last: str = "") -> None:
    """İş klasörünü proje olarak kaydeder ya da son durumunu günceller (anahtar: klasör)."""
    if not folder:
        return
    item_id = _project_id(folder)
    old = memory_db.get(item_id)
    last = " ".join(str(last or "").split())[:300]
    if old:  # aranan metin (başlık + ilk istek) sabit kalır: vektör yeniden çıkarılmaz
        memory_db.update_data(item_id, **({"last": last} if last else {}))
        return
    text = " ".join(f"{title} — {original_request(request)}".split())[:300]
    memory_db.put("proje", text, {"folder": folder, "title": title, "last": last}, item_id)


def find_project(request: str) -> dict | None:
    """Devam isteği → hafızadaki en uygun proje (klasörü hâlâ duruyorsa); yoksa None."""
    if not _CONTINUE.search(request or ""):
        return None
    semantic = memory_db.semantic()
    found = memory_db.search(request, ("proje",), k=3, min_score=SEM_PROJECT_LOW if semantic else 0.2,
                             keyword_score=_keyword)
    # kısa devam istekleri ("hikayeye devam et") anlamca düşük puan alır (~0.58; ilgisiz ~0.57): orta puanda
    # ortak bir konu kelimesi de aranır ("devam", "proje" gibi kelimeler sayılmaz)
    topic = _stems(_CONTINUE.sub(" ", request)) - _CONTINUE_STEMS
    for score, p in found:
        if not Path(p.get("folder", "")).is_dir():
            continue
        if not semantic or score >= SEM_PROJECT or topic & _stems(p.get("text", "")):
            return p
    return None


def project_note(project: dict) -> str:
    """Devam edilen projeyi modele anlatan talimat eki."""
    last = f" Last time: {project['last']}" if project.get("last") else ""
    return (f"\n\n## Continuing a saved project\nThis conversation continues the project «{project.get('title', '')}» "
            f"(first request: {project.get('text', '')}). Its files are in the workspace folder; look at them "
            f"before changing anything.{last}")
