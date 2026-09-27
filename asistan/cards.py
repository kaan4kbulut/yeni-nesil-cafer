"""Model kimlik kartları: her yerel modelin bu bilgisayarda gerçekten ne yapabildiği, programın kendi sınavıyla.

Ollama'nın "tools" beyanı modelin araç çağırdığını göstermez (Gemma 4 komutu metin olarak yazar). Bu yüzden
her model kısa bir sınava girer; sınavda programın gerçek sistem talimatı ve araç listesi kullanılır, araç
çağrıları ÇALIŞTIRILMAZ (yalnızca doğru araç, doğru argümanla çağrıldı mı diye bakılır):

- araç: 3 görev (dosya yazma, Python ile hesap, yaz-ve-kaydet) × 2 deneme, gerçek kullanımdaki gibi düşünme açık;
  seviye 0 (hiç), 1 (bazen), 2 (6 denemenin hepsi)
- plan: yöneticinin JSON planını çıkarabiliyor mu (manager.PLAN_SCHEMA)
- türkçe: Türkçe soruya Türkçe cevap veriyor mu
- hız: token/sn ve yüklenme süresi (bu donanımda ölçülmüş)

Kartlar `DATA_DIR/model-kartlari.json` dosyasında; model güncellenince (digest değişince) ya da sınav değişince
(EXAM_VERSION) yeniden sınanır. Hata veren sınav bir gün sonra tekrarlanır.
"""

import json
import re
import threading
import time

import httpx

from .cekirdek import modeller
from .config import DATA_DIR

CARDS_FILE = DATA_DIR / "model-kartlari.json"
EXAM_VERSION = 3
TOOL_REPEATS = 2  # her araç görevi iki kez: bazen çağırıp bazen yazıp geçen model "iyi" sayılmasın
RETRY_ERROR_SECONDS = 24 * 3600
CALL_TIMEOUT = 240  # soğuk yükleme dahil (12B diskten ~30 sn)

TOOL_TASKS = [
    # (istek, kabul edilen araçlar, argümanlarda geçmesi gereken metin)
    ("sinav.txt adında bir dosya oluştur ve içine yalnızca 'merhaba' yaz.",
     {"write_file", "run_python", "run_command"}, "sinav.txt"),
    ("Python ile 1234 * 5678 işlemini hesapla ve sonucu söyle.", {"run_python", "run_command"}, "1234"),
    # sık görülen hata: model masalı sohbete yazar, dosyaya kaydetmez ("yazdı ama yapmadı")
    ("Kısa bir masal yaz ve masal.txt dosyasına kaydet.", {"write_file", "run_python"}, "masal.txt"),
]
PLAN_REQUEST = ("satis.csv dosyasını oku, aylık toplamları hesapla, bunları grafik.png olarak çiz ve sonra "
                "hepsini rapor.docx dosyasına koy")
TURKISH_QUESTION = "Çay nasıl demlenir? İki cümleyle anlat."
_TR_WORDS = re.compile(r"\b(ve|bir|bu|için|ile|olarak|sonra|çay|su|demlik|dakika|kadar|daha)\b", re.I)
_EN_WORDS = re.compile(r"\b(the|and|is|of|to|with|water|tea|minutes)\b", re.I)
_CJK = re.compile(r"[぀-ヿ㐀-鿿가-힯]")

_lock = threading.Lock()


# ---------------------------------------------------------------- kayıt

def load_cards() -> dict:
    try:
        data = json.loads(CARDS_FILE.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def _save(model: str, card: dict) -> None:
    with _lock:
        cards = load_cards()
        cards[model] = card
        CARDS_FILE.parent.mkdir(parents=True, exist_ok=True)
        tmp = CARDS_FILE.with_suffix(".tmp")
        tmp.write_text(json.dumps(cards, ensure_ascii=False, indent=1), encoding="utf-8")
        tmp.replace(CARDS_FILE)


def installed(ollama_url: str) -> list[dict]:
    """Kurulu sohbet modelleri: {name, digest, params}."""
    from .roster import _params

    try:
        resp = httpx.get(ollama_url.rstrip("/") + "/api/tags", timeout=5)
        resp.raise_for_status()
        models = resp.json().get("models", [])
    except Exception:
        return []
    return [{"name": m.get("name", ""), "digest": m.get("digest", ""),
             "params": _params(m.get("details", {}).get("parameter_size", ""))}
            for m in models if m.get("name") and "embed" not in m.get("name", "")]


def valid(card: dict | None, digest: str = "") -> bool:
    """Kart hâlâ geçerli mi (aynı model sürümü, aynı sınav; hatalıysa bir gün geçmemiş)?"""
    if not card or card.get("version") != EXAM_VERSION or (digest and card.get("digest") != digest):
        return False
    return not card.get("error") or time.time() - card.get("measured", 0) < RETRY_ERROR_SECONDS


def card(model: str) -> dict | None:
    """Modelin geçerli kartı (hatalı sınav kart sayılmaz); yoksa None."""
    c = load_cards().get(model)
    return c if valid(c) and not c.get("error") else None


def missing(ollama_url: str, errors: bool = False) -> list[dict]:
    """Kartı olmayan / eskimiş kurulu modeller (küçükten büyüğe: hızlı olanlar önce hazır olsun).
    errors: sınavı hatayla yarıda kalanlar da (kendiliğinden bir gün sonra denenir; kullanıcı düğmeye basınca hemen)."""
    cards = load_cards()
    todo = [m for m in installed(ollama_url) if not valid(cards.get(m["name"]), m["digest"])
            or (errors and (cards.get(m["name"]) or {}).get("error"))]
    return sorted(todo, key=lambda m: m["params"] or 99)


# kart yokken (yeni kurulum, sınav henüz yapılmadı) başlangıç bilgisi: bu ailelerin modelleri Ollama'ya "araç
# desteği var" dese de sınavda hiç araç çağırmadı (2026-09-26, 12 model: Qwen2.5-Coder 14B, Gemma 3 12B,
# Dolphin 3 8B ve GLM-OCR 0/6). Kod ve veri ajanları ilk sınav bitene kadar dosya yazamayan bir modele düşmesin.
NO_TOOL_FAMILIES = tuple(modeller.deger("aileler.arac_cagiramaz"))  # ayar/modeller.json


def tools_level(model: str) -> int | None:
    """0: araç çağırmıyor · 1: bazen · 2: güvenilir · None: henüz sınanmadı (bilinen araçsız aile: 0)."""
    c = card(model)
    if c is None:
        return 0 if model.split(":")[0].split("/")[-1] in NO_TOOL_FAMILIES else None
    return int(c.get("tools", 0))


# ---------------------------------------------------------------- sınav

def _chat(url: str, model: str, messages: list, tools: list | None = None, schema: dict | None = None,
          think: bool = False) -> dict:
    payload = {"model": model, "messages": messages, "stream": False, "keep_alive": "2m",
               "options": {"num_ctx": 8192, "num_predict": 2500 if think else 700}}
    if not think:
        payload["think"] = False  # düşünme açıkken modelin kendi varsayılanı (agent.py gibi)
    if tools:
        payload["tools"] = tools
    if schema:
        payload["format"] = schema
    resp = httpx.post(url.rstrip("/") + "/api/chat", json=payload, timeout=httpx.Timeout(CALL_TIMEOUT, connect=10))
    if resp.status_code != 200:
        raise RuntimeError(f"{resp.status_code}: {resp.text[:200]}")
    return resp.json()


def _tool_ok(reply: dict, allowed: set, needle: str) -> bool:
    for call in (reply.get("message") or {}).get("tool_calls") or []:
        fn = call.get("function") or {}
        args = fn.get("arguments")
        text = args if isinstance(args, str) else json.dumps(args or {}, ensure_ascii=False)
        if fn.get("name") in allowed and needle in text:
            return True
    return False


def is_turkish(text: str) -> bool:
    if not text.strip() or _CJK.search(text):
        return False
    tr_chars = len(re.findall(r"[çğışöüÇĞİŞÖÜ]", text))
    return tr_chars >= 2 and len(_TR_WORDS.findall(text)) >= 2 and len(_EN_WORDS.findall(text)) <= 2


def measure(ollama_url: str, model: str, digest: str = "", params: float = 0.0, cancelled=None) -> dict:
    """Modeli sınar, kartı kaydeder ve döndürür. cancelled() True olursa InterruptedError."""
    from . import manager, model_updates, specialists, sysinfo
    from .agent import build_tool_specs, system_prompt

    def check():
        if cancelled and cancelled():
            raise InterruptedError("model sınavı durduruldu")

    caps = set(specialists._capabilities(ollama_url, model))
    c = {"model": model, "digest": digest, "params": params, "version": EXAM_VERSION, "measured": time.time(),
         "declared_tools": "tools" in caps, "vision": "vision" in caps,
         "uncensored": model_updates.is_uncensored(model), "tools": 0, "tools_passed": 0,
         "tools_total": len(TOOL_TASKS) * TOOL_REPEATS, "plan": False, "turkish": False,
         "tps": 0.0, "load_s": 0.0, "error": ""}
    before = {m.get("name") for m in _loaded(ollama_url)}
    try:
        check()
        sysinfo.make_room(ollama_url, model)
        # 1) Türkçe + hız (ilk çağrı yüklemeyi de ölçer)
        r = _chat(ollama_url, model, [{"role": "user", "content": TURKISH_QUESTION}])
        c["load_s"] = round(r.get("load_duration", 0) / 1e9, 1)
        if r.get("eval_duration"):
            c["tps"] = round(r.get("eval_count", 0) / (r["eval_duration"] / 1e9), 1)
        c["turkish"] = is_turkish((r.get("message") or {}).get("content", ""))
        # 2) araç: programın gerçek talimatı ve araç listesiyle (model yalnızca "yazıp geçiyor" mu?)
        if "tools" in caps:
            system = {"role": "system", "content": system_prompt("/tmp/yeni-nesil-cafer-sinav")}
            tools = [{"type": "function", "function": {"name": s["name"], "description": s["description"],
                                                       "parameters": s["input_schema"]}}
                     for s in build_tool_specs(None, [])]
            for request, allowed, needle in TOOL_TASKS * TOOL_REPEATS:
                check()
                r = _chat(ollama_url, model, [system, {"role": "user", "content": request}], tools, think=True)
                c["tools_passed"] += int(_tool_ok(r, allowed, needle))
            c["tools"] = 2 if c["tools_passed"] == c["tools_total"] else int(c["tools_passed"] > 0)
        # 3) plan: yöneticinin JSON planı
        check()
        prompt = (f"User's request:\n{PLAN_REQUEST}\n\nSplit the work into 1-{manager.MAX_PLAN_STEPS} ordered steps. "
                  'Respond as JSON: {"steps": [{"title": "...", "do": "...", "done_when": "..."}]}')
        r = _chat(ollama_url, model, [{"role": "system", "content": manager.PLANNER_SYSTEM},
                                      {"role": "user", "content": prompt}], schema=manager.PLAN_SCHEMA)
        c["plan"] = len(manager.clean_steps(manager.parse_json((r.get("message") or {}).get("content", "")))) >= 2
    except InterruptedError:
        raise
    except Exception as e:
        c["error"] = f"{type(e).__name__}: {e}"[:300]
    finally:
        if model not in before:  # sınav için yüklenen model ekran kartında kalmasın
            try:
                httpx.post(ollama_url.rstrip("/") + "/api/generate", json={"model": model, "keep_alive": 0}, timeout=10)
            except Exception:
                pass
    _save(model, c)
    return c


def _loaded(ollama_url: str) -> list[dict]:
    try:
        return httpx.get(ollama_url.rstrip("/") + "/api/ps", timeout=3).json().get("models", [])
    except Exception:
        return []


def measure_missing(ollama_url: str, on_progress=None, cancelled=None, force: bool = False,
                    errors: bool = False) -> list[dict]:
    """Kartı olmayan modelleri sırayla sınar. on_progress(sıra, toplam, model)."""
    todo = sorted(installed(ollama_url), key=lambda m: m["params"] or 99) if force else missing(ollama_url, errors)
    done = []
    for i, m in enumerate(todo, 1):
        if cancelled and cancelled():
            break
        if on_progress:
            on_progress(i, len(todo), m["name"])
        done.append(measure(ollama_url, m["name"], m["digest"], m["params"], cancelled))
    if done:
        from . import roster

        roster._cache = None  # seçim yeni kartlarla yapılsın
    return done


# ---------------------------------------------------------------- arayüz metinleri

TOOL_WORDS = {0: "yok", 1: "zayıf", 2: "iyi"}


def describe(c: dict) -> str:
    """Tek satırlık Türkçe özet: "araç: iyi · plan: ✓ · Türkçe: ✓ · 45 token/sn"."""
    if c.get("error"):
        return f"sınav başarısız: {c['error']}"
    parts = [f"araç: {TOOL_WORDS.get(c.get('tools', 0), '?')} ({c.get('tools_passed', 0)}/{c.get('tools_total', 0)})", f"plan: {'✓' if c.get('plan') else '✗'}",
             f"Türkçe: {'✓' if c.get('turkish') else '✗'}", f"{c.get('tps', 0):.0f} token/sn"]
    if c.get("declared_tools") and not c.get("tools"):
        parts[0] += " (araç desteği var diyor ama çağırmıyor)"
    return " · ".join(parts)
