"""Agent döngüsü: modele istek gönderir, araç çağrılarını çalıştırır, sonuçları geri yollar.

Arayüzden bağımsızdır; olaylar `Callbacks` üzerinden bildirilir. Sohbet geçmişi her
sağlayıcının kendi (native) mesaj biçiminde tutulur ve JSON olarak kaydedilebilir.
"""

import json
import platform
import re
import subprocess
import time
import uuid
from contextlib import closing
from pathlib import Path
from dataclasses import replace
from datetime import date
from typing import Protocol

import httpx

from .cekirdek import modeller, saglayici as sg, yonlendirici
from .cekirdek.saglayici import claude as sg_claude, cli_ajan as sg_cli, ollama as sg_ollama
from .cekirdek.saglayici.openai_uyumlu import OpenAIUyumluSaglayici
from .config import Settings
from .connections import ANTHROPIC_KEY, Connection, key_error
from .keystore import get_secret
from .profiles import AgentProfile
from . import api_catalog, cli_agents, hooks, learning, power, security, specialists, sysinfo
from .tools import (
    program_roots,
    CALL_API_SPEC, DECOR_SPEC, DELEGATE_SPEC, FIGURE_SPEC, PIP_SPEC, FIND_API_SPEC, IMAGE_GEN_SPEC, USE_SKILL_SPEC,
    TEAM_TASK_SPEC, Toolbox, ToolError, file_stem, missing_image, model_report,
    validate_input,
)
from .registry import REGISTRY
from . import permissions
from .permissions import is_action  # manager ve testler buradan da alır


class _TembelAnthropic:
    """`anthropic` SDK'sı açılışta ~1 sn: ilk Claude çağrısında yüklenir (K10 açılış süresi; düşük kademede < 3 sn)."""

    def __getattr__(self, ad):
        import anthropic as sdk

        return getattr(sdk, ad)


anthropic = _TembelAnthropic()

MAX_STEPS = 40  # tek bir kullanıcı mesajında en fazla model çağrısı
SELECTOR_STEPS = 12  # araç seçici kipinde bir turda en çok araç kararı
SELECTOR_PREDICT = 1500  # karar JSON'u kısa: uzun kod argümanı da sığsın
SELECTOR_NOTE = (
    "\n\n## How to use tools in this conversation\nYou do not call tools yourself. At each step answer with ONE JSON "
    'decision: {{"eylem": "arac", "arac": <tool name>, "argumanlar": {{...}}, "gerekce": <why, short>}} to run a '
    'tool, or {{"eylem": "cevap", "gerekce": ...}} when the work is done or no tool is needed. The program runs '
    "the tool and shows you the result; then decide again. Tools:\n{tools}")
SELECTOR_ANSWER = ("\n\nThe tools already ran; their results are in the conversation. Now write your answer to the "
                   "user. You cannot run tools in this answer.")
THINK_LIMIT = 6000  # yerel modelin gizli düşünmesi için karakter sınırı (~30 sn); aşılırsa düşünmeden cevaplar
THINK_SECONDS = 240  # pilde yavaş modelde karakter sınırına varmadan dakikalarca düşünebilir: süre sınırı da var
STALL_SECONDS = 150  # Ollama'dan bu kadar süre tek parça gelmezse çağrı takılmış sayılır (model yükleme dahil sığar)
NUM_PREDICT = 8192  # tek çağrıda en çok bu kadar token: uzun hikâyeye yeter, kısır döngü dakikalarca sürmez
# kendini tekrar eden model: metnin son REPEAT_TAIL karakteri metinde REPEAT_COUNT kez geçiyorsa döngüdedir.
# qwen2.5 14B grup görevinde aynı kod bloğunu ~20 kez yazdı (8192 token, 3 dk 47 sn; 2026-09-27): o sürede
# Ollama tek isteği işlediği için sohbet de bekledi.
REPEAT_TAIL = 300
REPEAT_COUNT = 3
QUICK_REQUEST = 60  # bu kadar kısa, tek satırlık istekler ("telegram aç") düşünmeden yapılır

# Sunucu tarafı yedek model (refusal fallback) desteklenen modeller
CLAUDE_FALLBACK_MODELS = set(modeller.deger("claude.yedekli"))
# Adaptive thinking desteklemeyen modeller
CLAUDE_NO_THINKING = set(modeller.deger("claude.dusunmesiz"))


Cancelled = sg.Iptal  # kullanıcı durdurdu (çekirdekteki sınıfla aynı: arayüz ikisini de yakalar)


class _SubRelay:
    """Alt ajanın olayları: araç kartları ve onaylar ana sohbete gider, metni toplanıp sonuç olur."""

    def __init__(self, parent):
        self.parent, self.text = parent, ""

    def on_text(self, delta): self.text += delta
    def on_thinking(self, delta): pass
    def on_model_start(self, step): pass
    def on_model_end(self, stats): self.parent.on_model_end(stats)
    def on_tool_start(self, call_id, name, args): self.parent.on_tool_start(call_id, name, args)
    def on_tool_end(self, call_id, result, is_error): self.parent.on_tool_end(call_id, result, is_error)
    def ask_approval(self, name, args): return self.parent.ask_approval(name, args)
    def on_media(self, *a):  # alt ajanın ürettiği görseller de canlı görünsün
        fn = getattr(self.parent, "on_media", None)
        if fn:
            fn(*a)
    def on_security(self, *a):  # alt ajanın güvenlik kararları da görünsün
        fn = getattr(self.parent, "on_security", None)
        if fn:
            fn(*a)
    def is_cancelled(self): return self.parent.is_cancelled()
    def start_team_task(self, title, goal): return "Not available to a delegated agent."


HEAD_PROMPT = (
    "\n\n## Your position\nYou are the head of the user's personal company of AI specialists. The user just "
    "says what they want; you decide who does it and never ask the user to pick a model. For each request: "
    "answer yourself when it is quick; give work in one specialist's area to that agent with delegate_to_agent "
    "(the agent gets the model best suited to its job); hand larger jobs needing several specialists to the team "
    "with start_team_task; consult a stronger model with ask_specialist when a problem is hard. After a "
    "delegated agent reports, check its result and give the user the final answer in your own words."
)


class Callbacks(Protocol):
    def on_text(self, delta: str) -> None: ...
    def on_thinking(self, delta: str) -> None: ...
    def on_model_start(self, step: int) -> None: ...
    def on_model_end(self, stats: dict) -> None: ...
    def on_tool_start(self, call_id: str, name: str, args: dict) -> None: ...
    def on_tool_end(self, call_id: str, result: str, is_error: bool) -> None: ...
    def ask_approval(self, name: str, args: dict) -> bool: ...
    def is_cancelled(self) -> bool: ...


def _os_name() -> str:
    """Ör. "Linux · CachyOS (çekirdek 7.2.6)" — dağıtıma uygun komut önerilsin diye."""
    name = platform.system()
    try:
        distro = platform.freedesktop_os_release()
        name += f" · {distro.get('PRETTY_NAME') or distro.get('NAME')}"
        if distro.get("ID_LIKE") or distro.get("ID"):
            name += f", {distro.get('ID_LIKE') or distro.get('ID')} family"
    except OSError:
        pass
    name = f"{name}, kernel {platform.release()}"
    try:
        family = f"{distro.get('ID', '')} {distro.get('ID_LIKE', '')}"
        pm = next((pm for key, pm in _PACKAGE_MANAGERS if key in family), "")
        if pm:
            name += f"; package manager: {pm} — never suggest commands of other distributions (e.g. apt)"
    except NameError:
        pass
    return name


_PACKAGE_MANAGERS = [("arch", "pacman (AUR: paru/yay)"), ("debian", "apt"), ("ubuntu", "apt"), ("fedora", "dnf"),
                     ("rhel", "dnf"), ("suse", "zypper"), ("gentoo", "emerge"), ("alpine", "apk")]


GATE_NOTE = (
    "\n\n## Nothing changes without the user's approval\nYou may read, search and research freely. Anything that "
    "changes something (writing or editing files, running commands or code, API calls that modify data, handing "
    "work to the team) is NOT executed now: the app collects it and shows a ✓ (apply) button next to your answer. "
    "So when a request needs changes, first describe concisely exactly what you will do (which files, which "
    "commands, in order) and stop; when the user presses the button you will be asked to do it step by step. "
    "Never claim you already did something that was not executed.")
# "işe koyuluyorum", "görselleri üretiyorum": model yapıyormuş gibi anlatıyor (araç çağırmadıysa uydurma)
_CLAIMS_WORK = re.compile(r"\w+(?:ıyor|iyor|uyor|üyor)(?:um|uz)\b|\bhazırla(?:dım|nıyor)|\bbaşladım", re.I)
_ADVICE = re.compile(r"öner|tavsiye|fikir|fikr|ipuc|ipuç|ne yapmalı|ne yapabilir|nasıl yapabilir|yolları|"
                     r"seçenekler|alternatif", re.I)
_ACTION = re.compile(r"uygula|çalıştır|kur\b|kurul|başlat|oluştur|yaz\b|sil\b|düzenle|değiştir", re.I)
# görev istekleri: yanıtın kenarına ✓ ✗ ↻ gelir (asistan kendiliğinden yapmaz)
_TASK = re.compile(r"\b(kur(\b|ar m|abilir|ul|mak|ar\b)|yükle|indir|kaldır|sil(\b|er m|ebilir|mek)|başlat|durdur|"
                   r"çalıştır|oluştur|yaz(\b|ar m|abilir|mak)|düzenle|değiştir|taşı|kopyala|yedekle|gönder|ayarla|"
                   r"güncelle|temizle|düzelt|ekle|kapat|uygula|dönüştür|üret|hazırla|çiz|analiz et)", re.I)

# araç gerektiren ama iş (değişiklik) sayılmayan istekler: okumak, aramak, saymak (araç seçici kipi bunlarda da açılır)
_NEEDS_TOOL = re.compile(r"\b(oku|bul|ara|araştır|listele|say\b|saydır|hesapla|incele|kontrol et|bak)|dosya|klasör|"
                         r"internet|web|\b\w+\.(txt|md|csv|json|py|pdf|xlsx|docx|png|jpg)\b", re.I)


PROGRAM = "_program"  # programın modele gönderdiği uyarı mesajlarının işareti (kullanıcının isteği değil)
COMPACTED = "_ozetlendi"  # özetlenmiş eski mesaj: sohbette görünür, modele gitmez (yerine özet mesajı gider)
SUMMARY = "_ozet"  # eski konuşmanın özeti (program mesajı)
SUMMARY_HEAD = "[Summary of the earlier part of this conversation"  # fit_context özeti atmasın diye tanır
COMPACT_MIN = 6  # özetlemek için en az bu kadar eski mesaj (daha azında kırpma yeter, özetleme bekletir)
API_CTX = 32768  # bağlamı bilinmeyen OpenAI uyumlu model için temkinli varsayılan (aşılınca yarıya iner)
MIN_API_CTX = 4096  # LM Studio'nun varsayılanı: bundan aşağı inilmez
CLAUDE_CTX = 150_000  # Claude "prompt is too long" derse özetleme bütçesi
_API_CTX: dict[str, int] = {}  # model → bağlam aşım hatasından öğrenilen sınır (oturum boyunca)
_OVERFLOW = re.compile(r"context|too long|too many tokens|maximum.{0,40}tokens|token limit|n_ctx|reduce the length",
                       re.I)


def api_context(model: str) -> int:
    """OpenAI uyumlu modelin bağlamı: aşım hatasından öğrenilen, yoksa model kataloğundan, yoksa API_CTX."""
    if model in _API_CTX:
        return _API_CTX[model]
    from . import model_updates

    cloud = (model_updates.load() or {}).get("cloud") or {}
    rows = list((cloud.get("index") or {}).values()) + list(cloud.get("free") or [])
    for row in rows:  # OpenRouter adı "firma/model"; doğrudan firmaya bağlanınca yalnızca "model"
        rid = str(row.get("id", "")) if isinstance(row, dict) else ""
        if row.get("ctx") and model in (rid, rid.split("/")[-1]):
            return int(row["ctx"])
    return API_CTX
CHARS_PER_TOKEN = 2.6  # Türkçe metin, kod ve JSON için temkinli ortalama (fazla tahmin, taşmaktan iyidir)
REPLY_RESERVE = 1500  # modelin cevabı ve düşünmesi için ayrılan token
# modele göre tahmin düzeltmesi: gerçek token sayısı / tahmin (bağlam taşınca ölçülür, oturum boyunca kalır)
_CTX_SCALE: dict[str, float] = {}


def _strip(m: dict) -> dict:
    """Programın iç alanları (`_program`, `_plan`…) "_" ile başlar; sağlayıcıya gitmez."""
    return {k: v for k, v in m.items() if not k.startswith("_")} if any(k.startswith("_") for k in m) else m


def _clean(messages: list) -> list:
    """Sağlayıcıya gönderilmeden önce programın iç işaretlerini kaldırır (bilinmeyen alan API hatası verir).
    Özetlenmiş eski mesajlar gönderilmez (yerlerine özet mesajı gider)."""
    return [_strip(m) for m in messages if not m.get(COMPACTED)]


def last_request(messages: list) -> int:
    """Kullanıcının GERÇEK son isteğinin sırası: program uyarıları ve ▶ / ↻ onayları istek değildir."""
    return max((i for i, m in enumerate(messages) if m.get("role") == "user" and not m.get(PROGRAM)
                and not (isinstance(m.get("content"), str) and m["content"].startswith(("▶ ", "↻ ")))), default=0)


def transcript(messages: list, limit: int) -> str:
    """Özetlenecek konuşmanın düz metni. Önceki özet başta kalır; sığmazsa önce asistan ve araç metinleri kısalır
    ve en eskiden başlayarak atılır, kullanıcının kendi yazdıkları ("3D yazıcı aldım") en son kısalır."""
    head, items = "", []  # items: [kullanıcı mı, etiket, metin]
    for m in messages:
        c = m.get("content")
        text = " ".join((c if isinstance(c, str) else json.dumps(c, ensure_ascii=False)).split())
        if m.get(SUMMARY):
            head = "Earlier summary:\n" + text[:3000]
            continue
        calls = [f"{(t.get('function') or {}).get('name', '')}"
                 f"({json.dumps((t.get('function') or {}).get('arguments'), ensure_ascii=False)[:200]})"
                 for t in m.get("tool_calls") or []]
        if calls:
            text += " → calls: " + ", ".join(calls)
        user = m.get("role") == "user" and not m.get(PROGRAM)
        items.append([user, "program" if m.get(PROGRAM) else m.get("role", "?"), text])

    def render(user_cap: int, other_cap: int) -> list[str]:
        return [f"[{who}] {text[:user_cap if user else other_cap]}" for user, who, text in items]

    lines = []
    for user_cap, other_cap in ((1200, 600), (600, 200), (400, 80)):
        lines = render(user_cap, other_cap)
        if len(head) + sum(len(x) + 1 for x in lines) <= limit:
            return "\n".join(([head] if head else []) + lines)
    for drop_user in (False, True):  # hâlâ sığmıyor: en eski asistan/araç satırları, sonra en eski istekler
        for i, (user, _, _) in enumerate(items):
            if len(head) + sum(len(x) + 1 for x in lines if x) <= limit:
                break
            if user == drop_user:
                lines[i] = ""
    return "\n".join(([head] if head else []) + [x for x in lines if x])


# 3D baskı istekleri: ölçülü CAD modeli, dışa aktarma ve denetim (yalnızca istek 3D'yle ilgiliyse talimata girer)
_PRINT3D = re.compile(r"\b3\s?d\b|\bstl\b|\b3mf\b|\bstep\b dosya|yazıcı|baskı|bastır|printer|print", re.I)
PRINT3D_NOTE = (
    "\n\n## 3D printable models\nBuild real geometry in millimetres, never a picture. Decorative objects (vase, "
    "lamp, lampshade, ornament, star, figurine, animal or character figure, relief, lithophane): call "
    "make_decor_model directly and pick shape and sizes; do not write geometry code for these. A figure (animal, "
    "character, statuette): if make_3d_figure is among your tools, make a picture with generate_image and turn it "
    "into a real 3D figure with make_3d_figure (but a flat, 2.5D or silhouette figure the user asks for is always "
    "make_decor_model shape 'siluet'); otherwise use make_decor_model shape 'siluet' and tell the user that "
    "real 3D figures need the 3D figure engine (Yardım → 3D figür motoru). If generate_image fails, ask the user for "
    "a picture. Functional parts "
    "with exact sizes (box, holder, bracket, lid): FIRST call use_skill with name '3d-baski' (tested build123d "
    "template; guessing the API wastes many attempts), export to the 3D/ folder and call check_3d_model. Use the "
    "printer's bed size from memory. If build123d is missing, install it with install_python_package.")
# süs isteği: 3D kelimesi geçmese de (ör. "vazo tasarla") süs aracı verilir; takip mesajları için geçmişe de bakılır
_DECOR = re.compile(r"vazo|abajur|lamba|süs|heykel|figür|biblo|litofan|kabartma|siluet|silüet", re.I)

# programın modele hatırlatmaları: model bunları kullanıcıya anlatmasın (canlı denemede "ben bir modelim, bu
# mesajdaki talimata göre…" diye cevaba sızdı)
APP_NOTE = " (This reminder comes from the app, not from the user: do not mention it in your answer.)"

VISUAL_OUTPUTS = {".png", ".jpg", ".jpeg", ".webp", ".gif", ".svg", ".pdf", ".stl", ".obj", ".glb", ".gltf", ".3mf",
                  ".ply", ".mp4", ".webm", ".mov", ".docx", ".pptx", ".xlsx"}


def new_outputs(root: str, since: float, limit: int = 5) -> list[str]:
    """Bu turda çalışma klasöründe oluşan / değişen, kullanıcının bakacağı dosyalar (gizliler hariç, 3 düzey)."""
    import os

    found, seen = [], 0
    for folder, dirs, files in os.walk(root):
        depth = Path(folder).relative_to(root).parts
        dirs[:] = [d for d in dirs if not d.startswith(".")] if len(depth) < 2 else []  # en çok 3 düzey
        for name in files:
            seen += 1
            path = Path(folder) / name
            try:
                if not name.startswith(".") and path.suffix.lower() in VISUAL_OUTPUTS and path.stat().st_mtime >= since:
                    found.append(str(path.relative_to(root)))
            except OSError:
                continue
        if len(found) >= limit or seen > 3000:
            break
    return found[:limit]


def method_prompt(tools: set[str]) -> str:
    """Her işte izlenen çözüm yöntemi: anla → sor → tarif → araştır → edin → yap → gözle denetle → öğren.
    Yalnızca bu ajanda gerçekten olan araçları anar (küçük modeller olmayan aracı çağırmaya kalkmasın)."""
    get = [x for x, name in (("a Python library (install_python_package)", "install_python_package"),
                             ("a desktop application (install_app)", "install_app"),
                             ("a new tool built for you (request_tool)", "request_tool")) if name in tools]
    steps = ["If a detail that decides the result is missing and cannot be looked up (a size, which device, which "
             "file, which account), ask one short question before starting; for everything else assume sensibly "
             "and say what you assumed. When you ask, end your message with the question on its own line and, "
             "under it, 2-5 short answers as a bulleted list (- E27 standart duy), no text after the list: the "
             "user clicks one instead of typing."
             + (" Save lasting answers with remember (kind ekipman for the user's devices, tercih for preferences) "
                "so you never ask again." if "remember" in tools else "")]
    if "use_skill" in tools:
        steps.append("Check the Skills list and your memory for a known recipe first (use_skill).")
    if "web_search" in tools:
        steps.append("No recipe and the job is not trivial: research how it is done well (web_search, fetch_url) "
                     "and choose proven tools" + (": " + ", ".join(get) if get else "") + ".")
    steps.append("Do the work with tools, step by step.")
    if "inspect_output" in tools:
        steps.append("Verify the real result, not your intention: for anything the user will look at (3D model, "
                     "chart, PDF, image, document) call inspect_output with what it must show, and fix and repeat "
                     "until it matches.")
    if "learn_skill" in tools:
        steps.append("When a new approach worked, save it with learn_skill (short recipe: tools, steps, pitfalls) "
                     "so next time you already know it.")
    return "\n\n## How you solve things on your own\n" + "\n".join(f"{i}. {s}" for i, s in enumerate(steps, 1))


INSTRUCTIONS_FILE = "ASISTAN.md"  # kullanıcının talimat dosyası (Claude Code'daki CLAUDE.md gibi)
INSTRUCTIONS_LIMIT = 4000  # dosya başına karakter: küçük modelin bağlamını talimat doldurmasın


def instruction_files(folder: str, top: str = "") -> str:
    """İş klasöründen çalışma klasörüne (top) kadar ASISTAN.md dosyaları, genelden özele; yoksa boş."""
    here = Path(folder).expanduser().resolve()
    root = Path(top).expanduser().resolve() if top else here
    dirs = [here] + [d for d in here.parents if d.is_relative_to(root)]
    parts = []
    kalan = INSTRUCTIONS_LIMIT  # K12-F8: sınır dosya başına değil TOPLAM (3 düzey × 4000 = 12K bağlamı dolduruyordu)
    for d in reversed(dirs[:3]):  # iş → kategori → çalışma klasörü
        try:
            text = (d / INSTRUCTIONS_FILE).read_text(encoding="utf-8").strip()
        except (OSError, UnicodeDecodeError):
            continue
        if text and kalan > 0:
            parts.append(f"### {d / INSTRUCTIONS_FILE}\n{text[:kalan]}")
            kalan -= len(text)
    if not parts:
        return ""
    return ("\n\n## User instructions (ASISTAN.md files the user keeps in the workspace; follow them, the more "
            "specific folder wins)\n" + "\n\n".join(parts))


def estimate_tokens(messages: list, fixed_chars: int) -> float:
    """fit_context'in kullandığı kaba token tahmini (talimat + araçlar + mesajlar)."""
    return fixed_chars / 3.8 + sum(_size(m) for m in messages) / CHARS_PER_TOKEN


def _size(m: dict) -> int:
    c = m.get("content")
    return len(c if isinstance(c, str) else json.dumps(c, ensure_ascii=False)) + \
        len(json.dumps(m.get("tool_calls") or "", ensure_ascii=False)) + 20


def fit_context(messages: list, num_ctx: int, fixed_chars: int, scale: float = 1.0) -> list:
    """Mesajları modelin bağlamına sığdırır; geçmişin kendisine dokunmaz (kısaltılmış kopya döner).

    Ollama bağlamı aşınca en baştaki mesajları sessizce atar: kullanıcının sorusu kaybolur ve model alakasız
    cevap verir. Bunu önlemek için sırayla: eski araç çıktıları → son araç çıktısı kısaltılır, en son çare
    olarak eski sohbet turları atılır. Kullanıcının son isteği ve sonrası her zaman kalır."""
    # talimat ve araç tanımları İngilizce: token başına ~4 karakter (ölçüldü: 9972 karakter = 2446 token)
    # scale > 1: tahmin daha önce gerçeğin altında kaldı (ölçüldü), bütçe o oranda daralır
    budget = int(((num_ctx - REPLY_RESERVE) / scale - fixed_chars / 3.8) * CHARS_PER_TOKEN)
    size = _size

    def shorten(m, keep: int) -> dict:
        c = m.get("content") or ""
        if not isinstance(c, str) or len(c) <= keep:
            return m
        return {**m, "content": c[:keep] + f"\n[... kısaltıldı: {len(c)} karakterin ilk {keep}'i; gerekirse daha "
                                           "dar bir istekle (satır aralığı, belirli bir sayfa/yol) tekrar al]"}

    messages = [m for m in messages if not m.get(COMPACTED)]  # sıralar msgs ile aynı kalsın
    msgs = _clean(messages)
    total = lambda: sum(size(m) for m in msgs)  # noqa: E731
    if total() <= budget:
        return msgs
    tool_idx = [i for i, m in enumerate(msgs) if m.get("role") == "tool"]
    for i in tool_idx[:-1]:  # 1) eski araç çıktıları: kısa bir özet kalsın
        msgs[i] = shorten(msgs[i], 600)
        if total() <= budget:
            return msgs
    if tool_idx:  # 2) son araç çıktısı: sığacak kadarı
        i = tool_idx[-1]
        room = budget - (total() - size(msgs[i]))
        msgs[i] = shorten(msgs[i], max(1200, room))
        if total() <= budget:
            return msgs
    # 3) kullanıcının GERÇEK son isteğinden (program uyarıları değil) sonraki uzun metinler: baş ve son kalsın
    # ▶ / ↻ düğmelerinin mesajları yeni istek değil, önceki isteğin onayı: gerçek istek onlardan öncedir
    last_user = last_request(messages)
    for i in range(last_user + 1, len(msgs) - 1):
        c = msgs[i].get("content")
        if isinstance(c, str) and len(c) > 1600 and total() > budget:
            msgs[i] = {**msgs[i], "content": c[:600] + "\n[…]\n" + c[-900:]}  # yarım cevabın sonu: devam için
    # 4) eski turlar: önce araç çıktıları ve asistan cevapları kısalır/atılır; kullanıcının kendi yazdıkları
    # (kısa ama işin ne olduğunu söyleyen tek yer: "3D yazıcı aldım", "sağ panele ekle") en sona kalır
    for i in range(len(msgs) - 2):  # son iki mesaj (son araç çıktısı / yarım cevap) olduğu gibi kalsın
        if total() <= budget:
            break
        if msgs[i].get("role") in ("tool", "assistant"):
            msgs[i] = shorten(msgs[i], 300)
    while total() > budget:  # en eski asistan adımı, araç sonuçlarıyla birlikte (son dört mesaj kalır)
        i = next((i for i, m in enumerate(msgs[:-4]) if m.get("role") != "user"), None)
        if i is None:
            break
        j = i + 1
        while j < len(msgs) - 4 and msgs[j].get("role") == "tool":
            j += 1
        del msgs[i:j]
        if i < last_user:
            last_user -= j - i
    while last_user > 0 and total() > budget:  # en eski turlar; eski konuşmanın özeti (kısa, en değerli) kalır
        i = next((i for i in range(last_user) if not str(msgs[i].get("content") or "").startswith(SUMMARY_HEAD)),
                 None)
        if i is None:
            break
        msgs.pop(i)
        last_user -= 1
    while msgs and msgs[0].get("role") == "tool":  # araç cevabı çağrısız kalmasın
        msgs.pop(0)
    return msgs


def read_paths(messages: list) -> set[str]:
    """Bu sohbette read_file ile okunmuş yollar (Ollama/OpenAI tool_calls ve Claude tool_use biçimleri)."""
    seen = set()
    for m in messages:
        if m.get("role") != "assistant":
            continue
        calls = [c.get("function") or {} for c in m.get("tool_calls") or []]
        if isinstance(m.get("content"), list):
            calls += [{"name": b.get("name"), "arguments": b.get("input")} for b in m["content"]
                      if isinstance(b, dict) and b.get("type") == "tool_use"]
        for c in calls:
            a = c.get("arguments")
            if isinstance(a, str):
                try:
                    a = json.loads(a)
                except ValueError:
                    a = {}
            if c.get("name") == "read_file" and isinstance(a, dict) and a.get("path"):
                seen.add(str(a["path"]))
    return seen


def describe_pending(actions: list[tuple[str, dict]]) -> str:
    """Onay bekleyen işlemlerin kullanıcıya okunur listesi (model planı yazmadan durduysa program yazar)."""
    labels = {
        "run_command": lambda a: f"komut çalıştır: `{a.get('command', '')}`",
        "run_python": lambda a: "Python kodu çalıştır" + (f" — {a['purpose']}" if a.get("purpose") else ""),
        "write_file": lambda a: f"dosya yaz: `{a.get('path', '')}`",
        "edit_file": lambda a: f"dosya düzenle: `{a.get('path', '')}`",
        "install_python_package": lambda a: f"Python kütüphanesi kur: `{a.get('packages', '')}`",
        "start_team_task": lambda a: f"gruba ver: {a.get('title', '')}",
        "call_api": lambda a: f"API isteği: {a.get('api', '')} {a.get('method', '')} {a.get('path', '')}",
        "claude_code": lambda a: f"{cli_agents.label(a.get('provider') or 'cli:claude')} ile değişiklik yap",
    }
    lines = [f"{n}. {labels.get(name, lambda a: name)(args if isinstance(args, dict) else {})}"
             for n, (name, args) in enumerate(actions, 1)]
    return "Onayını bekleyen işlemler:\n\n" + "\n".join(lines) + "\n\n✓ ile başlatabilir, ✗ ile iptal edebilirsin."


def is_task_request(text: str) -> bool:
    """Kullanıcı bir şey yapılmasını mı istiyor (kurulum, dosya, komut…)? "uygula" mesajları hariç."""
    text = (text or "").strip()
    return not text.startswith(("▶ ", "↻ ")) and bool(_TASK.search(text.split("\n\n[Ek")[0]))


def is_install_request(text: str) -> bool:
    return bool(re.search(r"\b(kur(\b|ar m|abilir|mak)|yükle|indir)", (text or "").split("\n\n[Ek")[0], re.I))


def is_advice_request(text: str) -> bool:
    """Kullanıcı yalnızca öneri / tavsiye mi istiyor (uygulamasını değil)?"""
    text = (text or "").strip()
    if text.startswith("▶ "):  # "uygula" düğmesinden gelen mesaj
        return False
    request = text.split("\n\n[Ek")[0]
    return bool(_ADVICE.search(request)) and not _ACTION.search(request)


def program_prompt(settings: Settings, request: str = "", lean: bool = False) -> str:
    """Asistan içinde çalıştığı programı hep tanısın: kullanıcı "bu program", "sol panel", "grup çalışması"
    dediğinde neyi kastettiğini anlasın ve programın dosyalarını okuyabilsin.
    lean (küçük bağlam): istek programla ilgili değilse iki satırlık kısa tanıtım."""
    from . import __version__
    from .config import CONFIG_DIR, DATA_DIR
    from .tools import PROGRAM_DIR

    if lean and not _PROGRAM_REQUEST.search(request or ""):
        return (f"\n\n## The program you are running in\nYou are the assistant inside **YENİ NESİL CAFER** (version "
                f"{__version__}), a desktop app. Its code is at `{PROGRAM_DIR}` (read-only for you); when the user asks "
                "about the program, read its files there instead of guessing.")
    dev = settings.extra.get("dev_dir", "")
    return (
        f"\n\n## The program you are running in\nYou are the assistant inside **YENİ NESİL CAFER** (version {__version__}), "
        "a desktop app (Python + PySide6) that runs local Ollama models and can use cloud models. When the user says "
        "\"bu program\", \"uygulama\", \"asistan\" or talks about its menus, panels or settings, they mean this app.\n"
        f"- Program code (read-only for you): `{PROGRAM_DIR}` (the `asistan/` package: agent.py, tools.py, work.py, "
        "roster.py (automatic model choice), learning.py (memory, skills), gui/ (window, panels, menus))"
        + (f"\n- Source code under development: `{dev}`" if dev else "") + "\n"
        f"- Settings: `{CONFIG_DIR}` (ayarlar.json, ajanlar.json). Data: `{DATA_DIR}` (sohbetler/ chats, gorevler/ group "
        "tasks, python-kutuphaneleri/ extra Python libraries, hafıza and skills files). API keys are never readable.\n"
        "- You can read, list and search these folders with read_file, list_files and search_files using absolute "
        "paths; writing and editing stay inside the workspace (the user decides changes to the program).\n"
        "- Layout: left panel tabs Sohbet (chats), Grup Çalışması (a manager plans a task and the program picks "
        "the agents and models to do it), Ajanlar (agent profiles), API'ler (model providers and tool APIs), "
        "Kütüphaneler (Python libraries: program, preinstalled for agents, added later). Top bar: Online (cloud) "
        "and Offline (local) model menus with today's best and per-specialty lists, 🛡 güvenlik (security agent "
        "approves instead of the user; off by default) and 🔓 sansürsüz (uncensored local model). Under the chat "
        "box: model picker (otomatik = the program chooses), workspace folder. Right panel tabs: adımlar (each step and "
        "the model's thinking, auto-scrolls), kayıt, klasörler; below them a live preview opens only while visual "
        "work runs (image generation, 3D model, video) and shows each new STL/OBJ/GLB/image as soon as it is saved. Help menu: Hafıza ve öğrenme.\n"
        "- By default a security agent reviews every action with side effects by risk tier and may approve, send "
        "back or refuse it; the user can switch it off (🛡) to approve each step themselves (▶ uygula, then each step).\n"
        "When the user asks about the program, how something works in it, or wants to change it, look at its files "
        "first instead of guessing."
    )


# küçük bağlamda (LEAN_CTX altı) yalnızca istek gerektirince talimata giren bölümler
LEAN_CTX = 12000
_APP_REQUEST = re.compile(r"\b(aç|açar m|başlat|çalıştır|kur|kurar|kaldır|yükle|indir|sil|güncelle|install|open|launch)",
                          re.I)
_PROGRAM_REQUEST = re.compile(r"program|uygulama|asistan|panel|menü|ayar|sekme|düğme|buton|sohbet|ajan|güvenlik|"
                              r"sansürsüz|hafıza|kütüphane|yerel asistan|yeni nesil cafer|cafer", re.I)

_OPEN_APP_NOTE = (
    "Open / start / launch an app (\"telegram aç\", \"spotify'ı başlat\"): call open_app with the app name right "
    "away — no check_installed, no guessing commands with run_command. Only if it says NOT FOUND, check and offer "
    "to install.")
_INSTALL_NOTE = (
    "Install / uninstall / set up requests: when the user names an app (telegram, whatsapp, spotify, "
    "discord…) they mean the desktop application, not a programming library — unless they mention code, a bot or "
    "a library. Install apps the way this system does it (Linux: its package manager, AUR, or Flatpak/Snap; "
    "Windows: winget; macOS: brew); if there is no native app, offer the official web version. "
    "FIRST check the current state with check_installed (and "
    "read-only commands if needed). If it is already installed, tell the user that clearly and don't redo it; "
    "if they want it removed but it isn't there, say so. If it is missing and you don't know how to do it on "
    "this system, research it (web_search, fetch_url, find_api), learn the right method for this OS, and try "
    "alternatives instead of giving up after the first failure.")


def system_prompt(workspace: str, profile: AgentProfile | None = None, request: str = "", lean: bool = False) -> str:
    """Asistanın ana talimatı. lean (küçük bağlam): uygulama açma / kurma kuralları yalnızca istek gerektirince."""
    base = (
        "You are YENİ NESİL CAFER, a capable personal assistant and agent running on the user's "
        f"own computer ({_os_name()}). Today is {date.today().isoformat()}. Give commands and steps that fit "
        "this system (e.g. its own package manager).\n\n"
        "Always reply in the same language the user writes in (usually Turkish).\n\n"
        f"You have tools to work with files in the workspace folder `{workspace}`, run shell commands "
        "and Python code there, search the web and read web pages. Use them whenever they help you give "
        "a correct, grounded answer - for example search the web for current information instead of "
        "guessing. Relative paths are resolved against the workspace.\n\n"
        "Act directly: when the user asks for something, call the tools right away instead of describing "
        "a plan or asking whether you should. The app itself asks the user to approve commands and "
        "Python code, so never ask for permission in text; if a tool call is declined, respect it and "
        "continue without it.\n\n"
        "When a task needs several steps, work through them with tools until it is done, then give a "
        "short summary of what you did. Format answers with Markdown.\n\n"
        "To run Python (scripts, calculations, files, charts) use the run_python tool: it has the preinstalled "
        "libraries and works on every computer; don't rely on a system `python3` command.\n\n"
        "Cleanup / deletion: prefer safe, targeted steps (package manager cache tools, old logs, one app's cache) "
        "and show how much space each frees; never wipe whole folders like ~/.cache/*, /tmp/* or Downloads, and "
        "say what could be lost.\n\n"
        "Long-term memory: when the user asks you to remember something (\"unutma\", \"hatırla\", \"aklında tut\") "
        "or states a lasting preference or fact (\"bundan sonra\", \"her zaman\", \"asla\", their name, how they want "
        "answers or files), you MUST call the remember tool — one call per item — before answering. Never just say "
        "it is saved.\n\n"
        "Base plans on real data: look at the user's files with read_file / list_files first (they need no "
        "approval) so names, columns and formats in your plan are correct, not guessed.\n\n"
        "Before your final answer, check the request part by part: every requested file exists with the requested "
        "name and content (a chart asked to be in an Excel or Word file must be embedded in that file, e.g. "
        "openpyxl.drawing.image.Image or python-docx add_picture), numbers come from code you actually ran, and "
        "nothing asked for is missing. Fix gaps before answering; if something could not be done, say so plainly "
        "instead of implying it is done.\n\n"
        "Be solution-oriented. Never tell the user that you cannot do something because of your own limits. "
        "If a task needs an ability you lack, get it from other models: look_at_image to see images (you cannot "
        "see them yourself), ask_specialist for hard reasoning, code or a second opinion. When the user attaches "
        "images, look at every one with look_at_image before answering. If the job is large or needs several "
        "specialists working together, hand it to the team with start_team_task (when available). If information "
        "is missing, make a sensible assumption, say it, and still deliver a concrete result with next steps — "
        "unless the missing detail decides the result (see 'How you solve things on your own').\n"
        "But never pretend: only the tools in your tool list exist. Do not announce agents, specialists or work "
        "that you are not actually calling (\"the X agent will analyse…\", \"I am generating the videos…\"). If "
        "no tool can do a needed part and it is a clear, safe capability (a converter, a reader for a file type, a "
        "calculation), call request_tool to get one built and approved. If that fails or the part is impossible "
        "(for example making videos), say so in one sentence, then do everything that is possible now."
    )
    if not lean or _APP_REQUEST.search(request or ""):
        base += "\n\n" + _OPEN_APP_NOTE + "\n\n" + _INSTALL_NOTE
    if profile and profile.prompt:
        base += f"\n\n## Your role: {profile.name}\n{profile.prompt}"
    return base


def settings_for(settings: Settings, provider: str, model: str, workspace: str | None = None) -> Settings:
    """Belirli bir sağlayıcı/model (ve klasör) için ayarların kopyası."""
    s = replace(settings, api_models=dict(settings.api_models))
    if workspace:
        s.workspace = workspace
    if model:
        if provider == "claude":
            s.claude_model = model
        elif provider == "ollama":
            s.ollama_model = model
        elif provider.startswith("api:"):
            s.api_models[provider[4:]] = model
        elif cli_agents.is_cli(provider):
            s.extra = {**s.extra, "cli_model": model}
    return s


def build_tool_specs(profile: AgentProfile | None, apis: list[Connection]) -> list[dict]:
    """Ajanın izinli araçları; araç API'si varsa `call_api` açıklamasına listesi eklenir."""
    allowed = None if profile is None or profile.tools is None else set(profile.tools)
    specs = [s for s in REGISTRY.specs("temel") if allowed is None or s["name"] in allowed]
    if allowed is None or "run_python" in allowed:  # Python çalıştırabilen, kütüphanesini de kurabilsin
        specs.append(PIP_SPEC)
    # herkese açık araçlar: başka modellere danışma (yetenek eksikliğini kapatır), kurulu mu kontrolü, uygulama
    # açma, kalıcı hafıza
    specs += REGISTRY.specs("herkes", source="yerlesik")
    from . import imagegen

    if imagegen.installed() and (allowed is None or "write_file" in allowed or "look_at_image" in allowed):
        specs.append(IMAGE_GEN_SPEC)  # resim üretme: yerel model kuruluysa
    if apis and (allowed is None or "call_api" in allowed):
        listing = "\n".join(f"- {c.slug}: {c.description or c.name} (base URL: {c.base_url})" for c in apis)
        specs.append({**CALL_API_SPEC, "description": CALL_API_SPEC["description"] + "\nAvailable APIs:\n" + listing})
        specs.append(FIND_API_SPEC)
    from .definitions import load_skills

    if load_skills():  # kullanıcının beceri dosyaları: herkes okuyabilir (yalnızca tarif metni)
        specs.append(USE_SKILL_SPEC)
    # takılan MCP sunucularının araçları: ana asistanda ve "mcp" izni verilen ajanlarda
    if allowed is None or "mcp" in allowed:
        specs += REGISTRY.specs(source="mcp:")
    # tarayıcı araçları: yalnızca izin listesinde olan ajanlarda (BrowserAgent); ana asistan işi ona devreder
    if allowed is not None:
        from . import browser

        if browser.available():
            specs += [s for s in REGISTRY.specs("tarayici") if s["name"] in allowed]
    # araç fabrikasının eklediği araçlar: Python çalıştırabilen (ya da "fabrika" izni verilen) ajanlarda
    if allowed is None or "run_python" in allowed or "fabrika" in allowed:
        specs += REGISTRY.specs(source="fabrika")
    return specs


def to_jsonable(block):
    """SDK içerik bloklarını (Pydantic) geçmişte saklanabilir sözlüklere çevirir."""
    if isinstance(block, dict):
        return block
    return block.model_dump(mode="json", by_alias=True, exclude_none=True)


class Agent:
    def __init__(self, settings: Settings, callbacks: Callbacks, profile: AgentProfile | None = None,
                 connections: list[Connection] | None = None, team_tool: bool = False,
                 team: list[AgentProfile] | None = None):
        self.settings = settings
        self.cb = callbacks
        self.profile = profile
        self.connections = connections or []
        apis = [c for c in self.connections if c.kind == "tool" and c.enabled]
        # hazır anahtarsız API'ler (hava, döviz, deprem…): kullanıcı bir şey kurmadan açık
        own = {c.base_url.rstrip("/") for c in apis}
        apis += [c for c in api_catalog.builtin_connections(settings.extra.get("api_off"))
                 if c.base_url.rstrip("/") not in own]
        self.toolbox = Toolbox(settings.workspace, apis)
        self.toolbox.read_roots = program_roots(settings.extra.get("dev_dir", ""))
        self.tool_specs = build_tool_specs(profile, apis)
        self.team = list(team or [])  # ana asistanın görev verebileceği uzman ajanlar
        if team_tool:
            self.tool_specs.append(TEAM_TASK_SPEC)
            if self.team:
                listing = "\n".join(f"- {p.id}: {p.name} — {p.description}" for p in self.team)
                self.tool_specs.append({**DELEGATE_SPEC,
                                        "description": DELEGATE_SPEC["description"] + "\nTeam:\n" + listing})
        self.always_allowed = False  # "bu oturumda hep izin ver"
        self.auto_approve = None  # (ad, argümanlar) -> bool; True ise onay sorulmaz
        self.json_format: dict | None = None  # verilirse model yalnızca bu şemaya uygun JSON döndürür
        self.extra_system = ""
        self._provider = settings.provider  # run() çalışan sağlayıcıyla günceller
        self.gate_actions = False  # değişiklik yapan araçlar çalışmaz, bekleyen işlem olur (✓ düğmesi)
        self.pending_actions: list[tuple[str, dict]] = []  # bu turda kullanıcı onayını bekleyen işlemler
        self.read_paths: set[str] = set()  # bu sohbette read_file ile okunmuş yollar (tekrar okuma uyarısı)
        self.blocked_calls = 0  # onay beklerken engellenen çağrılar (döngü freni)
        self.actions_done = 0  # ✓ sonrası gerçekten çalışan işlemler
        self.check_nudges = 0  # "bitti" denince yapılan denetimlerin sayısı
        self.failed_calls: set = set()  # hata veren çağrılar (aynısı tekrarlanınca uyarı)
        self.verified = False  # istenen dosyaların içeriği bir kez denetletildi mi
        self.done_steps: list[tuple[str, dict]] = []  # ✓ sonrası başarıyla çalışan işlemler (beceri için)
        self.succeeded = False  # ✓ ile başlatılan iş denetimden geçerek bitti
        self.gave_up = False  # denemeler bitti, iş tamamlanamadı
        self.remembered: list[str] = []  # bu turda hafızaya kaydedilenler
        self.no_think = False  # düşünme bağlamı doldurduysa bu turun kalanı düşünmesiz
        self.no_tools = False  # model araç desteklemiyor (yalnızca sohbet)
        self.actions_tried = 0  # denenen yan etkili işlemler (güvenlik ajanına giden)
        self.security_blocks = 0  # güvenlik ajanının geri çevirdikleri/reddettikleri
        self.security_rejects = 0
        self.blocked_keys: set = set()
        self.security_stop = False  # zararlı işlemde ısrar: tur durdurulur
        self.memory_nudged = False
        self.user_text = ""
        self.found_installed = False  # check_installed "zaten var" dedi (kurulum isteğinde ✓ gereksiz)
        self.cli_model = ""  # Claude Code ile çalışırken model (opus, sonnet…; boş: Claude Code'un varsayılanı)
        self.must_act = False  # "uygula" istendi: komutları yazıp geçmesin, araçlarla gerçekten yapsın
        # "iş bitmedi" dürtmeleri; grup yöneticisinde kapalı: plan, kontrol ve raporda işi kendisi yapmaz, dürtülünce
        # sahip olmadığı run_python'u tekrar tekrar çağırıp görevi bitirmiyordu (2026-09-27)
        self.nudges = True
        self.bekleyen_soru = ""  # kullaniciya_sor çağrıldı: tur biter, arayüz "cevap bekliyor"
        self.cevaplanan_soru = ""  # arayüz: bir önceki turda sorulan soru; bu turun mesajı onun cevabı
        self.focus = ""  # yönetici adımı: "iş bitti mi" denetimi tüm isteğe değil bu adıma bakar
        self.base_system = ""  # verilirse system_prompt + program_prompt yerine kullanılır (bulut kopyası)
        self.lean = False  # küçük bağlamlı yerel model: talimat ve araç tanımları kısaltılır (run() belirler)
        self.run_started = time.time()  # tur başında yenilenir (run): bu turda üretilen dosyalar
        self.tools_used: set[str] = set()
        self.tool_errors = 0

    def _collect_results(self) -> None:
        """Bu turda üretilen görsel, 3D model, belge… masaüstündeki YENİ NESİL CAFER/Sonuçlar'a kopyalanır
        (results.py; Ayarlar'dan kapatılabilir). Bulut kopyasında yok."""
        if self.base_system or not (self.settings.extra or {}).get("sonuclari_topla", True):
            return
        from . import results

        try:
            results.collect(self.toolbox.root, self.settings.workspace, getattr(self, "run_started", time.time()))
        except OSError:
            pass  # masaüstü yazılamıyor: iş klasöründeki asıl dosyalar yerinde

    def _offer_decor(self, messages: list) -> None:
        """Sohbet 3D baskı ya da süs üzerineyse süs modeli aracını ekler (her sohbette talimatı büyütmesin diye
        yalnızca o zaman). Son birkaç kullanıcı mesajına bakılır: "daha burgulu yap" gibi takipte araç kaybolmasın."""
        if self.base_system or any(s["name"] == DECOR_SPEC["name"] for s in self.tool_specs):
            return  # bulut kopyasının dosya yazan aracı yok (cloud_server.CLOUD_TOOLS)
        allowed = None if self.profile is None or self.profile.tools is None else set(self.profile.tools)
        if allowed is not None and not allowed & {"write_file", "run_python"}:
            return  # dosya yazamayan ajan (ör. yönetici, araştırmacı)
        recent = [m.get("content") for m in messages[-12:] if m.get("role") == "user"]
        if any(isinstance(c, str) and (_PRINT3D.search(c) or _DECOR.search(c)) for c in recent):
            self.tool_specs.append(DECOR_SPEC)
            from . import figure3d

            if figure3d.installed():
                self.tool_specs.append(FIGURE_SPEC)

    def _system(self) -> str:
        # base_system: yerel programı anlatan uzun talimatın yerine (bulut kopyası kısa, kendine özgü talimat kullanır)
        request = learning.original_request(self.user_text)
        text = self.base_system or (system_prompt(str(self.toolbox.root), self.profile, request, self.lean)
                                    + program_prompt(self.settings, request, self.lean))
        if any(s["name"] == "delegate_to_agent" for s in self.tool_specs):
            text += HEAD_PROMPT
        if not self.base_system:
            text += method_prompt({s["name"] for s in self.tool_specs})
        # önceki sohbetlerden öğrenilenler: tercihler her zaman, bilgiler bu isteğe göre en ilgili olanlar
        text += learning.memory_prompt(self.focus or learning.original_request(self.user_text))
        if not self.base_system:  # bulut kopyasının çalışma klasörü yok
            text += instruction_files(str(self.toolbox.root), Settings.load().workspace)
            if _PRINT3D.search(request):
                text += PRINT3D_NOTE
        if any(s["name"] == "use_skill" for s in self.tool_specs):
            from .definitions import load_skills, skills_prompt

            text += skills_prompt(load_skills())
        return text + ("\n\n" + self.extra_system if self.extra_system else "")

    # ---- ortak araç çalıştırma ----

    def _execute_tool(self, call_id: str, name: str, args) -> tuple[str, bool]:
        self._check_cancel()  # K12-F10: ■ basıldıysa sıradaki araç için onay penceresi açılmasın
        error = validate_input(name, args)
        self.cb.on_tool_start(call_id, name, args if isinstance(args, dict) else {"raw": args})
        if error is None and not any(s["name"] == name for s in self.tool_specs):
            # yalnızca "yok" demek yetmiyor: küçük model aynı aracı tekrar tekrar deniyordu; elindekileri söyle
            error = (f"Tool '{name}' is not available to this agent. Do not call it again. Your tools: "
                     + (", ".join(s["name"] for s in self.tool_specs) or "none") + ".")
        if error:
            self.cb.on_tool_end(call_id, error, True)
            return error, True
        refused = self._permit(call_id, name, args)  # her araç (programın kendi araçları dahil) izin hattından geçer
        if refused is not None:
            return refused
        check = getattr(self, f"_gate_{name}", None)  # araca özgü ek kapı (ör. tarayıcıda ödeme / giriş)
        refused = check(name, args) if check else None
        if refused:
            self.cb.on_tool_end(call_id, refused, True)
            return refused, True
        hook = self._hook("PreToolUse", name, tool_name=name, tool_input=args)
        if hook.blocked:  # kullanıcının hook'u: yalnızca engelleyebilir, onay kurallarını aşamaz
            msg = f"BLOCKED by the user's hook: {hook.message} Do not try it again; tell the user briefly."
            self.cb.on_tool_end(call_id, msg, True)
            return msg, True
        # ajanın durumuna ihtiyaç duyan araçlar Agent._tool_<ad>, diğerleri Toolbox._tool_<ad> (ya da MCP/fabrika)
        own = getattr(self, f"_tool_{name}", None)
        try:
            if own is not None:
                result, is_error = own(args), False
            else:
                result, is_error = self._run_toolbox(name, args), False
        except Cancelled:
            raise
        except ToolError as e:
            result, is_error = f"Error: {e}", True
        except Exception as e:  # araç hatası modele iletilir, döngü devam eder
            result, is_error = f"Error: {type(e).__name__}: {e}", True
        self.tools_used.add(name)
        if is_error or re.match(r"exit code: [1-9]", result) or "Traceback (most recent call last)" in result:
            self.tool_errors += 1
        hook = self._hook("PostToolUse", name, tool_name=name, tool_input=args, tool_result=result[:20000])
        if hook.blocked:  # kullanıcının denetimi bir sorun buldu: model düzeltsin
            result += f"\n\n[The user's hook reported a problem: {hook.message}]"
        self.cb.on_tool_end(call_id, result, is_error)
        return result, is_error

    def _hook(self, event: str, tool: str = "", **payload) -> "hooks.Outcome":
        """Kullanıcının hook'larını çalıştırır (hooks.json yoksa hiçbir şey yapmaz)."""
        if not hooks.active(event):
            return hooks.Outcome()
        return hooks.run(event, {"cwd": str(self.toolbox.root), "request": learning.original_request(self.user_text),
                                 **payload}, tool)

    def _run_toolbox(self, name: str, args: dict) -> str:
        """Çalışma klasöründeki araçlar (dosya, komut, web, MCP, fabrika); başarılı değişiklikler beceri adımı olur."""
        if REGISTRY.get(name) is not None and REGISTRY.get(name).source == "fabrika":
            from . import factory

            factory.set_workspace(str(self.toolbox.root))  # fabrika aracı çalışma klasöründe çalışır
        result = self.toolbox.run(name, args)
        if name == "read_file":
            key = str(args.get("path") or "")
            if key in self.read_paths:
                # küçük modeller aynı dosyayı turlar boyunca yeniden okuyup bağlamı dolduruyor
                result = ("[Note: you already read this file earlier in this conversation. Do not read it "
                          "again; go on with the user's request.]\n" + result)
            self.read_paths.add(key)
        if name == "check_installed" and "FOUND" in result:
            self.found_installed = True
        if is_action(name, args) and not result.startswith("exit code: 1"):
            self.actions_done += 1
            self.done_steps.append((name, args))  # başarılı olursa beceri olarak kaydedilir
        return result

    # ---- programın kendi araçları (ajanın durumuna ihtiyaç duyanlar) ----

    def _tool_kullaniciya_sor(self, args: dict) -> str:
        """Kullanıcıya tek soru: soru (+ seçenekler madde olarak) baloncuğa yazılır, tur biter (`_soru_ile_bitti`)."""
        soru = " ".join(str(args.get("soru") or "").split())
        if not soru:
            raise ToolError("soru is empty")
        secenekler = [" ".join(str(s).split()) for s in (args.get("secenekler") or []) if str(s).strip()][:6]
        metin = soru + ("".join(f"\n- {s}" for s in secenekler) if secenekler else "")
        self.bekleyen_soru = metin
        self.cb.on_text(("\n\n" if getattr(self.cb, "text", "") else "") + metin)
        return ("The question is shown to the user; this turn ends now. Their answer will arrive as the next "
                "message. Do not write anything further.")

    def _soru_ile_bitti(self, messages: list) -> bool:
        """Bu turda `kullaniciya_sor` çağrıldıysa: soru son asistan mesajı olarak geçmişe girer, döngü biter."""
        if not self.bekleyen_soru:
            return False
        messages.append({"role": "assistant", "content": self.bekleyen_soru})
        return True

    def _tool_remember(self, args: dict) -> str:
        """Programın kendi hafızası: kullanıcının sistemine dokunmaz, sohbette görünür."""
        result = learning.remember(str(args.get("text", "")), str(args.get("kind") or "bilgi"))
        self.remembered.append(str(args.get("text", "")))
        return result

    def _tool_look_at_image(self, args: dict) -> str:
        return self._consult("look_at_image", args)

    def _tool_ask_specialist(self, args: dict) -> str:
        return self._consult("ask_specialist", args)

    def _tool_make_3d_figure(self, args: dict) -> str:
        """Resimden 3D figür (figure3d.py); Ollama modelleri ekran kartından boşaltılır."""
        from . import figure3d

        image = str(args.get("image") or "").strip()
        if not image:
            raise ToolError("image is required: make a picture with generate_image first, then pass its path")
        picture = self.toolbox._resolve(image, read=True)
        if not picture.is_file():
            raise missing_image(Path(self.toolbox.root), image)
        target = self.toolbox._resolve(f"3D/{file_stem(str(args.get('name') or ''), picture.stem)}")
        try:
            height = float(args.get("height") or 100)
        except (TypeError, ValueError):
            raise ToolError("height must be a number in mm") from None
        base = str(args.get("base", True)).lower() not in ("false", "0", "hayır", "no")
        try:
            r = figure3d.run(str(picture), str(target), height=height, base=base, bed=str(args.get("bed") or
                             "220x220x250"), ollama_url=self.settings.ollama_url)
        except (RuntimeError, subprocess.TimeoutExpired) as e:
            raise ToolError(str(e)) from None
        where = "graphics card" if r.get("device") == "cuda" else "processor (slower)"
        return (model_report(r, Path(self.toolbox.root)) + f"\nMade on the {where} in {r.get('seconds')} s. The picture "
                f"as the model saw it: {Path(r['input']).relative_to(self.toolbox.root)}")

    def _tool_generate_image(self, args: dict) -> str:
        return self._generate_image(args)

    def _tool_browser_look(self, args: dict) -> str:
        """Sayfanın ekran görüntüsü → görme modeli (model yalnızca yorumlar)."""
        from . import browser

        shot = browser.get().screenshot(Path(self.toolbox.root) / "tarayici-goruntu")
        return self._consult("look_at_image", {"path": str(shot), "question": str(args.get("question", ""))})

    def _tool_request_tool(self, args: dict) -> str:
        return self._request_tool(args)

    def _tool_find_api(self, args: dict) -> str:
        return self._find_api(str(args.get("topic", "")))

    def _tool_delegate_to_agent(self, args: dict) -> str:
        return self._delegate(args)

    def _tool_inspect_output(self, args: dict) -> str:
        """Çıktıyı resme çevirip görme modeline sorar; resme çevrilemeyen belgede yapı raporu."""
        from . import inspect_output

        path = self.toolbox._resolve(str(args.get("path", "")), read=True)
        if not path.is_file():
            raise ToolError(f"No such file: {args.get('path')}")
        try:
            image, facts = inspect_output.render(path, Path(self.toolbox.root) / ".denetim")
        except (ValueError, ImportError) as e:
            raise ToolError(str(e))
        if image is None:
            return facts
        question = str(args.get("question") or "Describe what this shows.")
        seen = self._consult("look_at_image", {"path": str(image), "question": (
            f"{question}\nAnswer yes or no first, then list anything that does not match. {facts}").strip()})
        return (f"[{facts}]\n" if facts else "") + f"Vision check: {seen}"

    def _tool_learn_skill(self, args: dict) -> str:
        from .definitions import learn

        try:
            return learn(str(args.get("name", "")), str(args.get("description", "")), str(args.get("recipe", "")))
        except ValueError as e:
            raise ToolError(str(e))

    def _tool_use_skill(self, args: dict) -> str:
        from .definitions import skill_text

        return skill_text(str(args.get("name", "")))

    def _tool_start_team_task(self, args: dict) -> str:
        return self.cb.start_team_task(args.get("title", ""), args.get("goal", ""))

    def _gate_browser_click(self, name: str, args: dict) -> str | None:
        return self._browser_gate(name, args)

    _gate_browser_type = _gate_browser_click

    def permission_context(self) -> "permissions.Context":
        """İzin hattının bu ajan için bağlamı (görev motoru da planda `onay_gerekli` tahmini için kullanır)."""
        from .model_updates import is_uncensored

        return permissions.Context(
            approval_mode=self.settings.approval_mode,
            # sansürsüz modelle güvenlik ajanı çalışamıyor (ikisi belleğe sığmıyor): o zaman kullanıcı onaylar
            uncensored=self._provider == "ollama" and is_uncensored(self.settings.ollama_model),
            confirm_commands=self.settings.confirm_commands, gate_actions=self.gate_actions,
            must_act=self.must_act, always_allowed=self.always_allowed, auto_approve=self.auto_approve)

    def _permit(self, call_id: str, name: str, args: dict) -> tuple[str, bool] | None:
        """İzin hattının (`permissions.decide`) kararını uygular; çağrı çalışmayacaksa modele gidecek sonucu döndürür."""
        decision = permissions.decide(name, args, self.permission_context())
        if decision.kind == permissions.DENY:  # yasak listesi: her kipte, güvenlik ajanının reddi gibi
            verdict = security.Verdict("reject", security.FORBIDDEN, f"Zararlı işlem: {decision.reason}.",
                                       [decision.reason])
            on_security = getattr(self.cb, "on_security", None)
            if on_security:
                on_security(name, verdict.decision, verdict.tier, verdict.reason, args, verdict)
            msg = self._security_message(name, args, verdict)
            self.cb.on_tool_end(call_id, msg, True)
            return msg, True
        if decision.kind == permissions.PENDING:
            # kullanıcı ✓ düğmesine basana kadar değişiklik yok: işlemi kaydet, modele planı anlatmasını söyle
            if (name, args) not in self.pending_actions:  # aynı işlem tekrar tekrar listelenmesin
                self.pending_actions.append((name, args))
            self.blocked_calls += 1
            self.cb.on_tool_end(call_id, "onay bekliyor — ✓ düğmesine basınca yapılacak", False)
            if name == "run_command" and re.match(r"\s*(cat|head|tail|less|more|nl)\b", str(args.get("command") or "")):
                # dosya okumak onay gerektirmez: model plan yazıp durmasın, doğru araca geçsin
                return ("NOT EXECUTED: shell commands need the user's approval. To read a file use the read_file "
                        "tool instead — it needs no approval. Continue with read_file."), False
            return ("NOT EXECUTED: the user has not approved changes yet. Do not call more tools that change "
                    "things. Finish by listing exactly what you will do (files, commands, in order); the user "
                    "will press the ✓ button to let you do it."), False
        if is_action(name, args):
            self.actions_tried += 1
        if decision.kind == permissions.REVIEW:
            # güvenlik ajanı kipi: kullanıcıya sorulmaz; risk katmanına göre onay, geri çevirme ya da ret
            verdict = self._security_review(name, args)
            if verdict.decision == "ask":  # K12-A3: güvenlik modeli yok — orta riskli adımı kullanıcı onaylar
                if not self.cb.ask_approval(name, args):
                    msg = "The user declined to run this."
                    self.cb.on_tool_end(call_id, msg, True)
                    return msg, True
                return None
            if not verdict.approved:
                msg = self._security_message(name, args, verdict)
                self.cb.on_tool_end(call_id, msg, True)
                return msg, True
        elif decision.kind == permissions.ASK and not self.cb.ask_approval(name, args):
            msg = "The user declined to run this."
            self.cb.on_tool_end(call_id, msg, True)
            return msg, True
        return None

    def _security_review(self, name: str, args: dict) -> "security.Verdict":
        """Güvenlik ajanına sorar; kararı sohbette kısa bir notla gösterir."""
        chat_model = self.settings.ollama_model if self._provider == "ollama" else ""
        reviewer = ""
        # düşük riskte kurallar karar verir: denetçi model seçilmez, sohbet modeli ekran kartından boşaltılmaz
        if security.needs_model(name, args, str(self.toolbox.root)):
            reviewer = security.pick_reviewer(self.settings.ollama_url, chat_model, power.saving(self.settings))
            if reviewer and reviewer != chat_model:
                sysinfo.make_room(self.settings.ollama_url, reviewer)  # güvenlik modeli ekran kartına tam sığsın
        verdict = security.review(name, args, learning.original_request(self.user_text), str(self.toolbox.root),
                                  self.settings.ollama_url, reviewer, _os_name(),
                                  power.num_ctx(self.settings) if reviewer == chat_model else None)
        on_security = getattr(self.cb, "on_security", None)
        if on_security:
            on_security(name, verdict.decision, verdict.tier, verdict.reason, args, verdict)
        return verdict

    def _security_message(self, name: str, args: dict, verdict) -> str:
        """Geri çevrilen/reddedilen işlem için modele giden sonuç; ısrar ederse tur durdurulur."""
        key = json.dumps([name, args], sort_keys=True, ensure_ascii=False, default=str)
        self.security_blocks += 1
        repeated = key in self.blocked_keys
        self.blocked_keys.add(key)
        if verdict.decision == "reject":
            self.security_rejects += 1
        if self.security_rejects >= 2 or self.security_blocks >= 5 or (repeated and verdict.decision == "reject"):
            self.security_stop = True
        if verdict.decision == "reject":
            return (f"REFUSED by the security agent (risk: {verdict.tier}): {verdict.reason} This will not be done — "
                    "do not try it again or in another form. Tell the user briefly that it was refused and why.")
        return (f"NOT RUN — the security agent sent this back (risk: {verdict.tier}): {verdict.reason} Find a "
                "different, safer way to reach the user's goal (targeted, reversible, inside the workspace when "
                "possible) and try that instead." + (" You already proposed exactly this; do NOT repeat it."
                                                     if repeated else ""))

    _MEMORY_RX = re.compile(r"unutma|hatırla|hatirla|aklında tut|aklinda tut|bundan sonra|her zaman|hep böyle|asla |"
                            r"benim ad[ıi]m|remember", re.I)
    _NAME_RX = re.compile(r"(?<![\wçğıöşü])[Aa]d[ıi]m\s+(?!adım)[A-ZÇĞİÖŞÜ][a-zçğıöşü]+")  # "Adım Deniz" (adım adım değil)

    def _memory_check(self) -> str | None:
        """Kullanıcı bir şeyi hatırlamasını istedi ama model remember'ı çağırmadan bitirdi: bir kez uyar."""
        request = learning.original_request(self.user_text)
        if (self.memory_nudged or self.user_text.startswith("📈")  # rapor isteği: içinde hafıza metinleri geçer
                or not any(s["name"] == "remember" for s in self.tool_specs)):
            return None
        name = self._NAME_RX.search(request)
        name_missing = bool(name) and not any(name.group(0).split()[-1].casefold() in t.casefold()
                                              for t in self.remembered)
        if not name_missing and (self.remembered or not self._MEMORY_RX.search(request)):
            return None
        self.memory_nudged = True
        if name_missing and self.remembered:
            return (f"You saved some items but not the user's name ({name.group(0).split()[-1]}). Call remember for "
                    "it now (kind: bilgi), then answer briefly.")
        return ("You said it is noted, but nothing was saved: memory is only kept if you call the remember tool. "
                "If my last message contains something lasting to remember (a preference, a fact about me, my name), "
                "call remember now, once per item; then answer briefly. If there is nothing lasting, just answer.")

    def _repeat_note(self, name: str, args, result: str) -> str:
        """Aynı araç çağrısı aynı hatayı ikinci kez verdiyse sonuca açık bir uyarı ekler."""
        failed = result.startswith(("Error:", "exit code: 1")) or "Traceback" in result
        key = (name, json.dumps(args, sort_keys=True, ensure_ascii=False, default=str), result[-400:])
        seen = self.failed_calls
        if failed and key in seen:
            hint = next((ln.strip() for ln in reversed(result.splitlines()) if ln.strip()), "")
            return (result + "\n\nNOTE: you already ran exactly this and got exactly this error. Running it again "
                    f"will fail the same way. Change the code to fix the error: {hint[:300]}")
        if failed:
            seen.add(key)
        return result

    _FILE_RX = re.compile(r"[\w\-.]+\.(?:xlsx|xls|docx|pptx|pdf|csv|md|txt|png|jpg|json|py|html|zip)\b", re.I)

    def _completion_check(self, messages: list) -> str | None:
        """Bir iş isteğinde model "bitti" dediğinde: gerçekten yapıldı mı? (küçük modeller uydurabiliyor)

        Hiçbir işlem çalışmadıysa ya da istenen dosyalar çalışma klasöründe yoksa modele bir kez daha iş verilir.
        Yalnızca asistan bir işlem denediyse ya da istek açıkça bir iş (dosya, kurulum…) ise devreye girer."""
        original = learning.original_request(self.user_text)
        request = self.focus or original  # yönetici adımında: yalnızca o adım
        # adımdaki dosya adlarından yalnızca kullanıcının kendi isteğinde geçenler istenir: planlayıcının uydurduğu
        # "olasiliklar.txt / model_duzenleme.py" için model 20 dk "dosya yok, oluştur" döngüsüne girdi (2026-09-27)
        wanted = dict.fromkeys(f for f in self._FILE_RX.findall(request) if not self.focus or f in original)
        acting = self.actions_tried > 0 or (is_task_request(request) and bool(wanted))
        if (not acting or self.gate_actions or self.no_tools or self.check_nudges > 2
                or self.user_text.startswith("📈")):
            return None  # plan turunda (✓ bekleniyor) iş zaten yapılmaz
        root = Path(self.settings.workspace).expanduser()
        missing = [f for f in wanted if not any(root.rglob(f))] if root.is_dir() else []
        if self.check_nudges == 2:  # denemeler bitti: kullanıcıya dürüstçe söyle, "yapıldı" sanmasın
            self.check_nudges += 1
            if self.actions_done == 0 or missing:
                self.gave_up = True
                what = (f"şu dosyalar oluşturulamadı: {', '.join(missing)}" if missing
                        else "hiçbir işlem gerçekten çalıştırılamadı")
                self.cb.on_text(f"\n\n⚠ **İş tamamlanamadı** — {what}. Yukarıdaki adımlarda ne denendiğini "
                                "görebilirsin. Daha güçlü bir model (Yardım → Model önerileri) ya da ücretsiz bir "
                                "bulut modeliyle tekrar dene.")
            else:
                self.succeeded = True
            return None
        if self.actions_done == 0:
            self.check_nudges += 1
            return ("The task is NOT done: no step has succeeded yet (nothing ran, or every run ended with an "
                    "error). Do it now with the tools (run_python / write_file …): read each error message and fix "
                    "exactly that, check the real output, then report only real results. Never write placeholders "
                    "like '(hesaplama sonucu)'.")
        if missing:
            self.check_nudges += 1
            return (f"These requested files do not exist in the workspace yet: {', '.join(missing)}. Create them now "
                    "with the tools and verify they exist before you report. Do not claim they exist.")
        if wanted and not self.verified:
            # dosya var ama içi istenen gibi mi? (ör. grafik Excel'e gömülememiş ama "gömüldü" denmiş)
            self.verified = True
            self.check_nudges += 1
            return (f"Before reporting, verify with run_python that {', '.join(wanted)} really contain what was "
                    "asked (open them: sheets/rows, embedded images or charts, text…). If something is missing, fix "
                    "it; then report only what the check confirmed, and clearly say if anything could not be done.")
        if self.actions_done:
            self.succeeded = True  # denetimlerden geçti: yöntem beceri olarak kaydedilebilir
        return None

    def _consult(self, name: str, args: dict) -> str:
        """Uzman modele sorar: resim görme ya da başka bir yetenek."""
        if name == "look_at_image":
            path = self.toolbox._resolve(args["path"], read=True)
            if not path.is_file():
                raise ToolError(f"Image not found: {args['path']}")
            if path.suffix.lower() not in specialists.IMAGE_SUFFIXES:
                raise ToolError("Not an image file; use read_file for text files")
            role, images, question = "vision", [path], args["question"]
        else:
            role = str(args.get("role", "general")).strip().lower()
            if role not in specialists.ROLES:
                role = "general"
            images, question = [], args["question"]
        found = specialists.resolve(self.settings, role)
        if found is None:
            raise ToolError(
                f"No specialist model for '{role}' is installed. Tell the user which model would add this "
                f"ability (for images: {modeller.deger('gorme_uzmani')}; they can download it from the Models menu, "
                "never give them a terminal command) and meanwhile do the best you can.")
        provider, model = found
        try:
            answer = specialists.ask(self.settings, self.connections, provider, model, question, images,
                                     cancelled=getattr(self.cb, "is_cancelled", None))
        except InterruptedError:  # K12-D8
            raise Cancelled() from None
        return f"[{model} yanıtı]\n{answer}"

    def _generate_image(self, args: dict) -> str:
        """Yerel resim modeliyle üretir; dosyalar çalışma klasöründe Resimler/ altında."""
        from . import imagegen

        out = Path(self.toolbox.root) / "Resimler"
        live = out / ".canli-onizleme.png"  # gizli: canlı görüntü bölümünin klasör taraması galeriye almaz
        prompt, negative = str(args.get("prompt", "")), str(args.get("negative") or "")
        try:
            imagegen.check_prompt(prompt)  # çeviriden önce de: çeviri bir şeyi yumuşatmasın
            imagegen.check_prompt(negative)
            prompt, negative = self._english(prompt), self._english(negative)
            files = imagegen.generate(
                prompt, out, negative,
                int(args.get("width") or 1024), int(args.get("height") or 1024), int(args.get("count") or 1),
                saving=power.saving(self.settings), ollama_url=self.settings.ollama_url,
                cancelled=self.cb.is_cancelled, preview=live,
                progress=lambda pct, text: self._media(str(live), min(pct, 99), text))
        except imagegen.Blocked as e:
            return f"BLOCKED: {e} Do not retry with minors; tell the user this cannot be made."
        except InterruptedError:
            raise Cancelled()
        finally:
            live.unlink(missing_ok=True)
            self._media("", -1, "")  # canlı görünüm kapansın (sonuç dosyası aşağıda)
        for f in files:
            self._media(str(f), -1, "bitti")
        root = Path(self.toolbox.root)
        rel = [str(f.relative_to(root)) for f in files]
        from . import gpu

        card = gpu.image_report(self.settings)
        slow = f"\nWARNING (tell the user): {card.text} {card.fix}" if card and not card.ok else ""
        return "SAVED: " + ", ".join(rel) + ("\nThe images are already shown to the user. Describe briefly "
                                              "what was made; offer variations.") + slow

    def _media(self, path: str, pct: int, text: str) -> None:
        """canlı görüntü bölümüne üretim ilerlemesi: pct 0-99 ara görüntü, pct < 0 bitti (path: sonuç ya da boş)."""
        on_media = getattr(self.cb, "on_media", None)
        if on_media:
            on_media(path, pct, text)

    def _english(self, text: str) -> str:
        """Resim modeli İngilizce ister: Türkçe istemi sohbet modeline çevirtir (küçük modeller Türkçe yazabiliyor)."""
        if not text.strip() or not re.search(r"[çğıöşüÇĞİÖŞÜ]|\b(ve|bir|ile|resmi|kadın|adam|gün|ışık)\b", text):
            return text
        model = self.settings.ollama_model if self._provider == "ollama" else ""
        if not model:
            return text
        try:
            answer = specialists.ask(
                self.settings, self.connections, "ollama", model, text,
                system="Translate this image description into an English Stable Diffusion prompt: comma-separated "
                       "visual details, keep every detail and every age exactly as written, add nothing. "
                       "Output only the prompt.")
        except Exception:
            return text
        return answer.strip().strip('"').splitlines()[0][:1500] if answer.strip() else text

    def _browser_gate(self, name: str, args: dict) -> str | None:
        """Satın alma / ödeme, mesaj / paylaşım, hesap / silme, giriş / indirme: güvenlik ajanı açık olsa ve "hep izin
        ver" seçilmiş olsa bile kullanıcıya sorulur. Onaylanmadıysa modele gidecek metni döndürür."""
        from . import browser

        b = browser.get()
        element = b.element(args.get("ref", 0)) or {}
        url = b.url()
        reason = browser.gate("click" if name == "browser_click" else "type", element, url,
                              str(args.get("text") or ""), bool(args.get("submit")))
        if not reason:
            return None
        shown = "••••••" if element.get("type") == "password" else str(args.get("text") or "")
        info = {"ref": args.get("ref"), "page": url, "element": browser._describe(element) if element else
                f"[{args.get('ref')}]", "text": shown, "submit": bool(args.get("submit")),
                "purpose": f"Tarayıcı — {reason}. Sayfa: {url[:120]}"}
        if not self.cb.ask_approval(name, info):
            return ("NOT DONE: the user did not approve this browser action (" + reason + "). Do not try it again or "
                    "another way; tell the user what you were about to do and ask how to continue.")
        if name == "browser_click" and "indir" in reason:
            b.approved_download = True
        return None

    def _request_tool(self, args: dict) -> str:
        """Araç fabrikası: eksik yetenek için araç yazdırır, test ettirir; kullanıcı onaylarsa hemen kullanılır."""
        from . import factory

        def progress(text):
            self.cb.on_text(f"\n*({text})*\n")

        def cancelled():
            return self.cb.is_cancelled()

        before = set(REGISTRY.tools)
        try:
            result = factory.build(str(args.get("need", "")), str(args.get("example") or ""), self.settings,
                                   self.connections, (self._provider, self._model()), self.cb.ask_approval,
                                   progress, cancelled)
        except InterruptedError:
            raise Cancelled()
        for name in set(REGISTRY.tools) - before:  # yeni araç bu turda hemen kullanılabilsin
            if REGISTRY.get(name).source == "fabrika":  # aynı anda kaydedilen görev motoru yetenekleri (y_) değil
                self.tool_specs.append(REGISTRY.get(name).spec)
        return result

    def _find_api(self, topic: str) -> str:
        found = api_catalog.search(topic)
        if not found:
            return "No catalog API matches this topic. Use web_search / fetch_url instead."
        ready = {c.base_url.rstrip("/"): c for c in self.toolbox.apis}
        lines = []
        for e in found:
            conn = ready.get(e.base_url.rstrip("/"))
            if conn:
                lines.append(f"READY — call_api api='{conn.slug}': {e.summary}. {e.usage}")
            else:
                lines.append(f"NEEDS A KEY — {e.name}: {e.summary}. Get a key: {e.key_url} ; the user adds it in "
                             "one click under API'ler > hazır API'ler.")
        return "\n".join(lines)

    def _delegate(self, args: dict) -> str:
        """Uzman ajana iş verir: ajan kendi araçları ve kendisine atanan modelle çalışır, sonucu döner."""
        from . import roster

        key = str(args.get("agent", "")).strip().lower()
        p = next((p for p in self.team if key in (p.id.lower(), p.name.lower())), None)
        if p is None:
            raise ToolError("Unknown agent. Team: " + ", ".join(f"{p.id} ({p.name})" for p in self.team))
        current = (self._provider, self._model())
        provider, model = roster.assign(self.settings, p, current)
        sub = Agent(settings_for(self.settings, provider, model), _SubRelay(self.cb), p, self.connections)
        sub.always_allowed, sub.auto_approve = self.always_allowed, self.auto_approve
        sub.gate_actions, sub.must_act = self.gate_actions, self.must_act  # ✓ kuralı alt ajanda da geçerli
        sub.extra_system = ("You were given this work by the head assistant, who will present your result to "
                            "the user. Do the work fully with your tools, then reply with the complete result.")
        try:
            sub.run(provider, [], str(args["task"]))
        finally:
            self.pending_actions += sub.pending_actions
        text = sub.cb.text.strip() or "(ajan metin döndürmedi)"
        return f"[{p.name} · {model}]\n{text}"

    def _model(self) -> str:
        if self._provider == "claude":
            return self.settings.claude_model
        if self._provider == "ollama":
            return self.settings.ollama_model
        return self.settings.api_models.get(self._provider[4:], "")

    def _check_cancel(self):
        if self.cb.is_cancelled():
            raise Cancelled()

    def run(self, provider: str, messages: list, user_text: str, step: str = "") -> None:
        """Kullanıcı mesajını geçmişe ekler ve agent döngüsünü tamamlanana kadar çalıştırır.

        step verilirse bu bir yönetici adımıdır: kullanıcının isteği zaten geçmiştedir, adım talimatı
        program mesajı olarak eklenir (sohbette kullanıcı mesajı gibi görünmez)."""
        if step:
            messages.append({"role": "user", PROGRAM: True, "content": step})
        else:
            if self.cevaplanan_soru:  # kullaniciya_sor'un cevabı: aynı bağlam, aynı iş sürer
                messages.append({"role": "user", PROGRAM: True, "content": (
                    f"The user is now answering your question «{self.cevaplanan_soru[:300]}». Treat the next message "
                    "as the answer and continue the same work; do not repeat the question.")})
                self.cevaplanan_soru = ""
            messages.append({"role": "user", "content": user_text})
        self.bekleyen_soru = ""
        self.user_text = user_text
        self._provider = provider
        self._offer_decor(messages)
        self.run_started = time.time()  # bu turda üretilen dosyalar (görsel denetim hatırlatması)
        self.tools_used: set[str] = set()
        self.tool_errors = 0  # başarısız araç denemeleri (çok denemeden sonra başarı → öğrenme hatırlatması)
        # 8K bağlamda talimat + araçlar ~5.6K token tutuyordu, geçmişe ~1.1K kalıyordu (2026-09-26 ölçümü)
        self.lean = provider == "ollama" and power.num_ctx(self.settings) < LEAN_CTX
        self.read_paths = read_paths([m for m in messages if not m.get(COMPACTED)])  # özetlenenin içeriği artık görünmüyor
        if self.gate_actions and GATE_NOTE not in (self.extra_system or ""):  # yönetici adımlarında bir kez
            self.extra_system = (self.extra_system or "") + GATE_NOTE
        if not step:
            hook = self._hook("UserPromptSubmit", prompt=user_text)
            if hook.blocked:
                note = f"*Bu istek hook tarafından durduruldu:* {hook.message}"
                self.cb.on_text(note)
                messages.append({"role": "assistant", "content": note})
                return
            if hook.message:  # hook'un eklediği bilgi (ör. proje durumu): modele program mesajı olarak
                messages.append({"role": "user", PROGRAM: True, "content": "Context from the user's hook:\n"
                                 + hook.message})
        try:
            if provider == "claude":
                self._run_claude(messages)
            elif cli_agents.is_cli(provider):
                self._run_cli(messages, provider)
            elif provider.startswith("api:"):
                conn = next((c for c in self.connections if c.id == provider[4:]), None)
                if conn is None:
                    raise RuntimeError("Bu sohbetin API bağlantısı silinmiş. API'ler sekmesinden yeniden ekle.")
                self._run_openai(messages, conn)
            else:
                self._run_ollama(messages)
        except Cancelled:
            messages.append({"role": "assistant", "content": "[Kullanıcı tarafından durduruldu]"})
            raise
        finally:
            self._collect_results()
        if not step:
            last = messages[-1].get("content") if messages and messages[-1].get("role") == "assistant" else ""
            self._hook("Stop", answer=last if isinstance(last, str) else "")

    # ---- Aboneliğinle çalışan resmi programlar (Claude Code, Codex, Gemini CLI; cli_agents.py) ----

    def _run_cli(self, messages: list, provider: str) -> None:
        # önceki konuşma (varsa) kısaca bağlam olarak verilir; program her çağrıda yeni oturum açar (sg_cli.istem)
        saglayici = sg_cli.CliAjanSaglayici(provider, self.cli_model or self.settings.extra.get("cli_model", ""))
        agent = saglayici.ajan
        system = "\n\n".join(x for x in ((self.profile.prompt if self.profile else ""), self.extra_system,
                                          "Reply in the user's language (usually Turkish).") if x)
        if self.gate_actions:  # onay yok: program yalnızca okur ve plan çıkarır; ✓ ile düzenleyebilir
            system += ("\n\nDo not modify any files now. Read what you need, then describe exactly which "
                       "changes you will make; the user approves with a button before you edit.")
            self.pending_actions.append(("claude_code", {"task": messages[-1]["content"], "provider": provider}))
        call_id = uuid.uuid4().hex
        self.cb.on_model_start(1)
        self.cb.on_tool_start(call_id, agent.tool, {"task": messages[-1]["content"]})
        started = time.time()

        def step(title: str, result: str, error: bool):  # programın kendi adımları sağ panelde görünsün
            sid = uuid.uuid4().hex
            self.cb.on_tool_start(sid, "cli_step", {"task": title})
            self.cb.on_tool_end(sid, result or "bitti", error)

        try:
            text = saglayici.sohbet(messages, system, klasor=str(self.toolbox.root),
                                    duzenleyebilir=not self.gate_actions, iptal=self.cb.is_cancelled, adim=step).metin
        except InterruptedError:
            self.cb.on_tool_end(call_id, "durduruldu", True)
            raise Cancelled()
        except Exception as e:
            self.cb.on_tool_end(call_id, str(e), True)
            raise
        self.cb.on_tool_end(call_id, text[:3000], False)
        self.cb.on_text(text)
        self.cb.on_model_end({"model": agent.title.lower(), "input_tokens": 0, "output_tokens": 0,
                              "seconds": time.time() - started, "load_seconds": 0, "tokens_per_sec": 0})
        messages.append({"role": "assistant", "content": text})

    # ---- Claude ----

    def _claude_client(self) -> "anthropic.Anthropic":
        return sg_claude.istemci(get_secret(ANTHROPIC_KEY))  # anahtar yoksa ANTHROPIC_API_KEY / `ant auth login`

    # ---- döngülerin ortak parçaları (Claude / Ollama / OpenAI uyumlu) ----

    def _stopped_by_security(self) -> bool:
        """Güvenlik ajanı turu durdurduysa kullanıcıya söyler."""
        if not self.security_stop:
            return False
        self.cb.on_text("\n\n🛡 **Güvenlik ajanı işlemi durdurdu:** asistan reddedilen ya da tekrar tekrar geri "
                        "çevrilen işlemlerde ısrar etti. Hiçbir zararlı adım çalıştırılmadı.")
        return True

    def _unfinished_nudge(self, messages: list, content: str, has_tools: bool, step: int, state: dict) -> str | None:
        """Model araç çağırmadan durdu: iş gerçekten bitti mi? Bitmediyse modele gidecek uyarı (döngü sürer).

        Küçük modellerin sık hataları: planı / komutları yazıp hiçbir şey çalıştırmamak ("oluşturuyorum…"),
        araçtan sonra hiçbir şey yazmadan durmak, "not aldım" deyip remember'ı çağırmamak, işi yarım bırakmak.
        Cevap bir soruyla bitiyorsa model kullanıcıya sonucu belirleyen bir şey soruyor: dürtülmez (▶ turu hariç).
        Ondan önce, yöntemin küçük modellerin atladığı iki adımı program takip eder: görsel çıktıyı gözle denetleme
        ve çok denemeden sonra bulunan yolu beceri olarak kaydetme (her biri turda bir kez)."""
        if not self.nudges or self.bekleyen_soru:  # soru soruldu: "yapmadı" sayılmaz
            return None
        names = {s["name"] for s in self.tool_specs}
        if not self.gate_actions and "inspect_output" in names and "inspect_output" not in self.tools_used \
                and not state.get("inspect"):
            made = new_outputs(str(self.toolbox.root), getattr(self, "run_started", time.time()))
            if made:
                state["inspect"] = True
                self.cb.on_text("\n\n*Sonucu gözle kontrol ediyorum.*\n\n")
                return (f"You created {', '.join(made)}. Before finishing, check the main result with inspect_output "
                        "(question: does it show exactly what I asked for?) and fix anything that does not match; "
                        "then give your final answer." + APP_NOTE)
        if not self.gate_actions and "learn_skill" in names and "learn_skill" not in self.tools_used \
                and getattr(self, "tool_errors", 0) >= 2 and self.actions_done and not state.get("learn"):
            state["learn"] = True
            return ("That took several attempts before it worked. Save what finally worked with learn_skill (the "
                    "library or tool, a short working code template, the pitfalls you hit) so next time is quick, "
                    "then give your final answer." + APP_NOTE)
        if content.rstrip().endswith("?") and not self.must_act:
            return None
        if (has_tools and step == 1 and not self.actions_tried
                and (self.must_act or (
                    not self.gate_actions and is_task_request(self.user_text)
                    and ("```" in content or re.search(r"(?m)^\s*(1[.)]|adım 1)", content, re.I)
                         or _CLAIMS_WORK.search(content))))):
            self.cb.on_text("\n\n*Şimdi gerçekten yapıyorum.*\n\n")
            return ("Nothing was executed yet: you only wrote text. Now actually do the work by calling the tools "
                    "(run_python, write_file, run_command…) step by step, then summarize the real results.")
        if not content.strip() and has_tools and not state.get("empty_act") and not self.gate_actions \
                and is_task_request(self.user_text) and not self.actions_done:
            # iş istendi ama hiçbir şey üretilmeden sessizce durdu (sık: tarif / resim okunduktan sonra): açıklama
            # isteme — küçük model o zaman konuşup bırakıyor; bir sonraki adımı gerçekten yaptır
            state["empty_act"] = True
            self.cb.on_text("\n\n*Devam ediyorum.*\n\n")
            last = next((m.get("tool_name") or m.get("name") for m in reversed(messages) if m.get("role") == "tool"), "")
            how = ("Apply the recipe you just read: write the complete script and run it with run_python now."
                   if last == "use_skill" else "Call the next tool now (e.g. run_python with the complete script).")
            return ("You stopped without writing anything, but the task is not done and nothing has been produced "
                    f"yet. {how} Do not explain or apologize first; act. If a size that decides the result is "
                    "really missing, ask exactly one short question instead.")
        if not content.strip() and not state.get("empty"):
            state["empty"] = True
            return ("You stopped without writing anything. Tell me briefly in my language what happened, what you "
                    "found, and what you propose next (if something failed, give a working alternative).")
        nudge = self._memory_check() or self._completion_check(messages)
        if nudge:
            self.cb.on_text("\n\n*Henüz bitmedi, eksikleri tamamlıyorum.*\n\n")
        return nudge

    def _run_calls(self, tool_calls: list, messages: list, ollama: bool) -> None:
        """OpenAI biçimindeki araç çağrılarını (Ollama ve OpenAI uyumlu) çalıştırır, sonuçları geçmişe ekler."""
        for call in tool_calls:
            fn = call.get("function") or {}
            name = fn.get("name", "")
            args = fn.get("arguments", {})
            if isinstance(args, str):
                try:
                    args = json.loads(args or "{}")
                except ValueError:
                    pass  # validate_input hatayı modele bildirir
            call_id = call.get("id") or uuid.uuid4().hex
            result, _ = self._execute_tool(call_id, name, args)
            result = self._repeat_note(name, args, result)  # aynı çağrı aynı hatayı yine verdiyse açıkça söyle
            messages.append({"role": "tool", "tool_name": name, "content": result} if ollama
                            else {"role": "tool", "tool_call_id": call_id, "content": result})

    # ---- Claude API ----

    def _run_claude(self, messages: list) -> None:
        model = self.settings.claude_model
        saglayici = sg_claude.ClaudeSaglayici(self._claude_client, model)
        # eager_input_streaming (büyük araç girdileri üretilirken akar), düşünme ve sunucu yedeği: sağlayıcıda
        params = saglayici.parametreler(self._system(), self.tool_specs, dusunme=model not in CLAUDE_NO_THINKING,
                                        sunucu_yedegi=model in CLAUDE_FALLBACK_MODELS)
        tools = params.get("tools", [])

        json_retries = 0
        compacted = False  # "prompt is too long" sonrası bir kez özetlendi
        for step in range(1, MAX_STEPS + 1):
            self._check_cancel()
            self.cb.on_model_start(step)
            started = time.monotonic()
            try:
                with closing(saglayici.akis(_clean(messages), parametreler=params)) as akis:
                    for parca in akis:
                        self._check_cancel()
                        if parca.tur == sg.METIN:
                            self.cb.on_text(parca.metin)
                        elif parca.tur == sg.DUSUNCE:
                            self.cb.on_thinking(parca.metin)
                        elif parca.tur == sg.SON:
                            response = parca.son["yanit"]
                json_retries = 0
                elapsed = time.monotonic() - started
                usage = response.usage
                stats = {
                    "model": response.model,
                    "input_tokens": usage.input_tokens + (usage.cache_read_input_tokens or 0)
                    + (usage.cache_creation_input_tokens or 0),
                    "output_tokens": usage.output_tokens,
                    "seconds": elapsed,
                    "tokens_per_sec": usage.output_tokens / elapsed if elapsed else 0,
                }
                yonlendirici.harcama_ekle("claude", stats["input_tokens"] + stats["output_tokens"])  # bulut tavanı
                self.cb.on_model_end(stats)
            except ValueError:
                # SDK'nin hiç ayrıştıramadığı araç girdisi JSON'u: turu yeniden iste
                json_retries += 1
                if json_retries > 2:
                    raise
                continue
            except anthropic.BadRequestError as e:
                # çok uzun sohbet: eski turlar özetlenir (yerel modelle), bir kez yeniden denenir
                if compacted or "too long" not in str(e).lower():
                    raise
                compacted = True
                self._compact(messages, {"content": params["system"]}, tools, CLAUDE_CTX, force=True)
                continue

            if response.stop_reason == "pause_turn":
                messages.append({"role": "assistant", "content": [to_jsonable(b) for b in response.content]})
                continue

            if response.stop_reason == "refusal":
                messages.append({"role": "assistant", "content": "[Model bu isteği reddetti]"})
                self.cb.on_text("\n\n*Model bu isteği güvenlik nedeniyle yanıtlamadı.*")
                return

            tool_uses = [b for b in response.content if b.type == "tool_use"]
            messages.append({"role": "assistant", "content": [to_jsonable(b) for b in response.content]})
            if not tool_uses:
                if response.stop_reason == "max_tokens":
                    self.cb.on_text("\n\n*Yanıt uzunluk sınırına ulaştı.*")
                return

            results = []
            for block in tool_uses:
                if response.stop_reason == "max_tokens":
                    # Kesilen araç girdisi geçerli ama eksik bir nesne olarak ayrışır; çalıştırma
                    result, is_error = "Tool input was truncated (max_tokens). Try smaller steps.", True
                else:
                    result, is_error = self._execute_tool(block.id, block.name, block.input)
                results.append({"type": "tool_result", "tool_use_id": block.id, "content": result, "is_error": is_error})
            messages.append({"role": "user", "content": results})
            if self._stopped_by_security() or self._soru_ile_bitti(messages):
                return
            self.cb.on_text("\n\n")
        self.cb.on_text("\n\n*Adım sınırına ulaşıldı.*")

    # ---- Ollama ----

    def _run_ollama(self, messages: list) -> None:
        url = self.settings.ollama_url.rstrip("/") + "/api/chat"
        tools = [
            {"type": "function", "function": {"name": s["name"], "description": self._describe(s), "parameters": s["input_schema"]}}
            for s in self.tool_specs
        ]
        system = {"role": "system", "content": self._system()}
        caps = specialists._capabilities(self.settings.ollama_url, self.settings.ollama_model)
        if tools and self._selector_turn():
            # araç sınavını tam geçemeyen model, iş isteğinde: karar şema-kısıtlı, aracı program çalıştırır
            self._compact(messages, system, [])
            self._run_selector(url, system, messages, tools)
            return
        if tools and caps and "tools" not in caps:
            tools = self._drop_tools(system)
        self._compact(messages, system, tools)

        state = {}  # bu turda yapılan uyarılar (_unfinished_nudge)
        continued = 0  # kesilen cevabın kaç kez sürdürüldüğü
        repeated = 0  # tekrar döngüsü yüzünden kaç kez durduruldu
        request = (self.user_text or "").strip()
        if len(request) <= QUICK_REQUEST and "\n" not in request:
            self.no_think = True  # kısa, basit istek: uzun düşünme yalnızca bekletir
        if power.saving(self.settings):
            self.no_think = True  # pilde her token pahalı (4B: ~10 token/sn): düşünme metni dakikalarca bekletir
        for step in range(1, MAX_STEPS + 1):
            self._check_cancel()
            self.cb.on_model_start(step)
            try:
                content, tool_calls, final = self._ollama_step(url, system, messages, tools)
            except _ThinkTooLong:
                # model düşünmede döngüye girdi: bu turun kalanı düşünmeden, doğrudan
                self.no_think = True
                self.cb.on_text("*(Düşünme çok uzadı; doğrudan yapıyorum.)*\n\n")
                content, tool_calls, final = self._ollama_step(url, system, messages, tools)
            except _NoToolSupport:
                # yetenek bilgisi alınamadıysa hata buradan anlaşılır: araçsız bir kez daha dene
                tools = self._drop_tools(system)
                content, tool_calls, final = self._ollama_step(url, system, messages, tools)

            ns = 1e9
            eval_s = final.get("eval_duration", 0) / ns
            self.cb.on_model_end({
                "model": self.settings.ollama_model,
                "input_tokens": final.get("prompt_eval_count", 0),
                "output_tokens": final.get("eval_count", 0),
                "seconds": final.get("total_duration", 0) / ns,
                "load_seconds": final.get("load_duration", 0) / ns,
                "tokens_per_sec": final.get("eval_count", 0) / eval_s if eval_s else 0,
            })
            assistant = {"role": "assistant", "content": content}
            if tool_calls:
                assistant["tool_calls"] = tool_calls
            messages.append(assistant)
            if not tool_calls and final.get("done_reason") == "length" and not content.strip() and not self.no_think:
                # bağlamın tamamı gizli düşünmeye gitti, cevap hiç yazılamadı: bu adımı düşünmeden tekrarla
                messages.pop()
                self.no_think = True
                self.cb.on_text("*(Uzun düşünme bağlamı doldurdu; doğrudan cevaplıyorum.)*\n\n")
                continue
            if not tool_calls and final.get("done_reason") == "repeat" and repeated < 1:
                # tekrar kesildi (metin ilk tekrarın sonunda): aynı şeyi yeniden yazmasın, işi araçla yapsın
                repeated += 1
                messages.append({"role": "user", PROGRAM: True, "content": (
                    "You started writing the same text over and over, so you were stopped. Do not write it again. "
                    "If code or a command has to run, call the tool now; otherwise finish with a short answer.")})
                continue
            if not tool_calls and final.get("done_reason") == "length" and content.strip() and continued < 2:
                # bağlam doldu (uzun düşünme + uzun cevap): cevap yarıda kesildi, kaldığı yerden sürdürsün
                continued += 1
                messages.append({"role": "user", PROGRAM: True, "content": (
                    "Your answer was cut off because of the length limit. Continue exactly where you stopped — do "
                    "not repeat what you already wrote, do not add an introduction.")})
                continue
            if not tool_calls and final.get("done_reason") == "length" and content.strip():
                # sürdürme hakkı bitti: kullanıcı yarım cevabın önünde sessizce beklemesin
                self.cb.on_text("\n\n*(Cevap bağlam sınırı yüzünden yarıda kaldı. Yeni bir sohbet açmak ya da "
                                "Ayarlar'dan bağlamı büyütmek sorunu çözer.)*")
            if not tool_calls:
                nudge = self._unfinished_nudge(messages, content, bool(tools), step, state)
                if nudge:
                    messages.append({"role": "user", PROGRAM: True, "content": nudge})
                    continue
                return
            self._run_calls(tool_calls, messages, ollama=True)
            if self._stopped_by_security() or self._soru_ile_bitti(messages):
                return
            if self.gate_actions and self.blocked_calls >= 2 and tools:
                # küçük modeller engellenen işlemi inatla tekrar dener: araçları kapat, planı yazsın
                tools = []
            self.cb.on_text("\n\n")
        self.cb.on_text("\n\n*Adım sınırına ulaşıldı.*")

    def _compact(self, messages: list, system: dict, tools: list, num_ctx: int | None = None,
                 force: bool = False) -> None:
        """Geçmiş bağlamın çoğunu dolduruyorsa son istekten önceki turları sohbet modeline özetletir.

        Kırpmada (fit_context) eski turlar sessizce atılıyor, model "3D yazıcı aldım" gibi bilgileri unutuyordu.
        Eski mesajlar silinmez (sohbette görünür), yalnızca COMPACTED işaretlenir; modele yerlerine özet gider.
        Özet alınamazsa hiçbir şey değişmez, kırpma yine devrededir.
        num_ctx: bulut modelinin bağlamı (verilmezse Ollama'nınki); force: sağlayıcı "fazla uzun" dedi, tahmine bakma."""
        local = num_ctx is None
        num_ctx = num_ctx or power.num_ctx(self.settings)
        fixed = len(system.get("content") or "") + len(json.dumps(tools or []))
        live = [m for m in messages if not m.get(COMPACTED)]
        scale = _CTX_SCALE.get(self.settings.ollama_model, 1.0) if local else 1.0
        if not force and estimate_tokens(live, fixed) * scale <= num_ctx - REPLY_RESERVE:
            return  # sığıyor: özetlemek yalnızca bekletir
        last = last_request(messages)
        old = [m for m in messages[:last] if not m.get(COMPACTED)]
        if sum(1 for m in old if not m.get(SUMMARY)) < COMPACT_MIN:
            return  # özetlenecek kadar eski konuşma yok: kırpma yeter
        # özet, geçmişe kalan bütçenin ~%30'unu geçmesin (8K bağlamda talimat + araçlar ~5.5K token tutuyor)
        history = max(0.0, (num_ctx - REPLY_RESERVE) / scale - fixed / 3.8)
        words = int(min(250, max(80, history * 0.3 / 2.5)))
        self.cb.on_text("*(Konuşma uzadı; eski kısmı özetliyorum.)*\n\n")
        # özeti yerel model yazar: onun bağlamı (bulut modelinin 128K'sı Ollama'da dev bellek ayırırdı)
        own_ctx = min(num_ctx, power.num_ctx(self.settings))
        summary = self._summarize(transcript(old, int((own_ctx - 1500) * CHARS_PER_TOKEN * 0.7)), own_ctx, words)
        if not summary:
            return
        for m in old:
            m[COMPACTED] = True
        messages.insert(last, {"role": "user", PROGRAM: True, SUMMARY: True, "content": (
            SUMMARY_HEAD + " — the full messages are no longer shown to you]\n"
            + summary)})

    def _summarize(self, text: str, num_ctx: int, words: int = 250) -> str:
        """Eski konuşmanın özeti (sohbet modeliyle, düşünmeden); olmazsa boş."""
        self._check_cancel()
        prompt = ("Summarize this conversation between a user and their desktop assistant so the assistant can "
                  "continue it without the original messages. Keep: what the user asked for and why, their "
                  "preferences and facts about them, files and folders created or changed (exact paths), commands "
                  "that worked or failed, decisions taken, and what is still open. Write in the user's language, "
                  f"as a compact list, at most {words} words. No introduction.\n\n" + text)
        saglayici = sg_ollama.OllamaSaglayici(self.settings.ollama_url, self.settings.ollama_model)
        try:
            return saglayici.sohbet([{"role": "user", "content": prompt}], num_ctx=num_ctx, num_predict=words * 3,
                                    dusunme=False, okuma_zaman_asimi=300).metin.strip()
        except (httpx.HTTPError, ValueError, sg.SaglayiciHatasi, RuntimeError):
            return ""

    def _describe(self, spec: dict) -> str:
        """Modele giden araç açıklaması; küçük bağlamda call_api'nin API listesi yalnızca adlar (kullanımı find_api verir)."""
        text = spec["description"]
        if not self.lean or spec["name"] != "call_api" or "\nAvailable APIs:\n" not in text:
            return text
        head, listing = text.split("\nAvailable APIs:\n", 1)
        names = [line.split(":", 1)[0].lstrip("- ").strip() for line in listing.splitlines() if line.startswith("- ")]
        return (head + " Before the first call to an API, call find_api with the topic to get its exact paths and "
                "parameters.\nAvailable APIs: " + ", ".join(names))

    # ---- şema-kısıtlı üretim ve araç seçici kipi (K4, eski Aşama 3) ----

    def structured(self, messages: list, schema: dict, model: str | None = None, system: str = "") -> dict | None:
        """Şema-kısıtlı tek cevap (`cekirdek/yapisal.py`): Ollama `format`, OpenAI uyumlu json_schema, Claude
        zorunlu araç, CLI talimat. Program şemayı denetler; uymazsa bir düzeltme turu. Şemaya uyan nesne ya da None."""
        from .cekirdek import yapisal

        if self._provider == "ollama":
            model = model or self.settings.ollama_model
            sysinfo.make_room(self.settings.ollama_url, model)
            num_ctx = power.num_ctx(self.settings)
            sent = fit_context(messages, num_ctx, len(system) + len(json.dumps(schema)), _CTX_SCALE.get(model, 1.0))
            saglayici = sg_ollama.OllamaSaglayici(self.settings.ollama_url, model)
            return yapisal.uret(saglayici, sent, schema, system,
                                ollama_ek={"num_ctx": num_ctx, "num_predict": SELECTOR_PREDICT}).veri
        saglayici = sg.bul(self._provider, self.settings, self.connections)
        return yapisal.uret(saglayici, _clean(messages), schema, system, model=model or self._model()).veri

    def _selector_turn(self) -> bool:
        """Bu turda araç seçici kipi mi? Yalnızca araç sınavını tam geçemeyen yerel model iş yaparken; sohbet
        mesajında (selam, soru) model eskisi gibi doğrudan cevaplar. Kip seçimi roster'da, kullanıcıya görünmez."""
        from . import roster

        if self.json_format is not None or self.profile is not None and self.profile.tools == []:
            return False
        request = learning.original_request(self.user_text)
        if not (self.must_act or self.focus or is_task_request(request) or _NEEDS_TOOL.search(request)):
            return False
        try:
            return roster.arac_kipi(self.settings, self.settings.ollama_model) == "secici"
        except Exception:
            return False  # kart/Ollama okunamadı: eski yol

    @staticmethod
    def _selector_view(messages: list) -> list:
        """Araç şablonu olmayan modele giden geçmiş: araç çağrıları ve sonuçları düz metin (kayıtlı geçmiş aynı)."""
        out = []
        for m in messages:
            if m.get("role") == "assistant" and m.get("tool_calls"):
                calls = "; ".join(f"{(c.get('function') or {}).get('name')} "
                                  f"{json.dumps((c.get('function') or {}).get('arguments'), ensure_ascii=False)[:400]}"
                                  for c in m["tool_calls"])
                out.append({"role": "assistant", "content": ((m.get("content") or "") + f"\n[tool call: {calls}]")
                            .strip()})
            elif m.get("role") == "tool":
                out.append({"role": "user", PROGRAM: True,
                            "content": f"[result of {m.get('tool_name') or 'the tool'}]\n{m.get('content') or ''}"})
            else:
                out.append(m)
        return out

    def _run_selector(self, url: str, system: dict, messages: list, tools: list) -> None:
        """Araç seçici kipi: her adımda model yalnızca şema-kısıtlı bir KARAR verir ({eylem: arac|cevap, arac: kayıtlı
        araç adlarından biri, argumanlar, gerekce}); argümanlar aracın şemasına uymazsa ikinci çağrı o aracın kendi
        şemasıyla. Aracı program `_execute_tool` ile çalıştırır (izin hattı aynı). "cevap" gelince cevap her zamanki
        gibi akarak yazılır. Araç tanımları talimata yalnızca ad + ilk cümle olarak girer (lean bütçesi)."""
        specs = {t["function"]["name"]: t["function"] for t in tools}
        names = list(specs)
        listing = "\n".join(f"- {n}: {self._first_sentence(specs[n].get('description') or '')}" for n in names)
        decide = system["content"] + SELECTOR_NOTE.format(tools=listing)
        def schema(first: bool) -> dict:
            # bu turda henüz hiçbir araç çalışmadıysa "cevap" seçilemez: gemma3 / dolphin3 ilk kararda araçsız
            # "cevap" deyip "dosya oluşturuldu" yazıyordu (2026-09-28 ölçümü, 0/6). Program kanıtla bilir: iş yapılmadı.
            return {"type": "object", "properties": {
                "eylem": {"type": "string", "enum": ["arac"] if first else ["arac", "cevap"]},
                "arac": {"type": "string", "enum": names},
                "argumanlar": {"type": "object"},
                "gerekce": {"type": "string"}},
                "required": ["eylem", "arac", "gerekce"] if first else ["eylem", "gerekce"]}

        model = self.settings.ollama_model
        ran = 0  # bu turda program tarafından çalıştırılan araçlar
        for step in range(1, SELECTOR_STEPS + 1):
            self._check_cancel()
            self.cb.on_model_start(step)
            started = time.monotonic()
            decision = self.structured(self._selector_view(messages), schema(ran == 0), model, decide)
            self.cb.on_model_end({"model": model, "input_tokens": 0, "output_tokens": 0, "load_seconds": 0,
                                  "seconds": time.monotonic() - started, "tokens_per_sec": 0})
            if not decision or decision.get("eylem") != "arac" or decision.get("arac") not in specs:
                break
            name = decision["arac"]
            args = decision.get("argumanlar") if isinstance(decision.get("argumanlar"), dict) else {}
            problem = validate_input(name, dict(args))
            if problem:  # argümanlar aracın şemasına uymuyor: o aracın kendi şemasıyla ikinci karar
                ask = self._selector_view(messages) + [{"role": "user", PROGRAM: True, "content": (
                    f"Give the arguments for the tool {name} ({problem}). Tool: "
                    f"{specs[name].get('description', '')[:600]}")}]
                args = self.structured(ask, specs[name]["parameters"], model, decide) or args
            call = {"id": uuid.uuid4().hex, "function": {"name": name, "arguments": args}}
            messages.append({"role": "assistant", "content": "", "tool_calls": [call]})
            self._run_calls([call], messages, ollama=True)
            ran += 1
            if self._stopped_by_security() or self._soru_ile_bitti(messages):
                return
            if self.gate_actions and self.blocked_calls >= 2:
                break  # onay bekleyen işlemde ısrar etmesin: planı yazsın
            self.cb.on_text("\n\n")
        self._check_cancel()
        self.cb.on_model_start(SELECTOR_STEPS + 1)
        answer = {"role": "system", "content": system["content"] + SELECTOR_ANSWER}
        content, _, final = self._ollama_step(url, answer, self._selector_view(messages), [])
        messages.append({"role": "assistant", "content": content})

    @staticmethod
    def _first_sentence(text: str) -> str:
        first = text.strip().split("\n")[0]
        return (first.split(". ")[0] + ".")[:200] if ". " in first else first[:200]

    def _drop_tools(self, system: dict) -> list:
        """Araç desteklemeyen model (ör. gemma3): araç listesi gönderilmez, yalnızca sohbet edilir."""
        system["content"] += ("\n\nIMPORTANT: In this conversation you have NO tools. Answer directly from your own "
                              "knowledge. Do not claim to search the web, read or write files, or run commands. If "
                              "the user asks for such work, say plainly that this model cannot do it.")
        self.no_tools = True  # "iş bitmedi" denetimleri anlamsız: model yapamaz, uydurmaya zorlanmasın
        return []  # kullanıcıya model seçilirken bildirilir (pencere: "sadece sohbet")

    def _ollama_step(self, url: str, system: dict, messages: list, tools: list) -> tuple[str, list, dict]:
        """Tek model çağrısı (akışlı): (metin, araç çağrıları, son parça)."""
        try:
            return self._ollama_call(url, system, messages, tools)
        except httpx.ConnectError:
            # Ollama henüz açılmadı (program yeni başladı) ya da kapandı: başlatıp bir kez daha dene
            if not sysinfo.ensure_ollama(self.settings.ollama_url):
                raise
            return self._ollama_call(url, system, messages, tools)
        except httpx.ReadTimeout:
            # model üretiyor ama hiçbir şey akmıyor (gemma4 bozuk araç çağrısını tamponda tutup dakikalarca
            # sürdürebiliyor): bekletmeden bir kez düşünmesiz dene, yine olmazsa kullanıcıya açıkça söyle
            self.stalls = getattr(self, "stalls", 0) + 1
            if self.stalls > 2:
                raise RuntimeError(f"Model {STALL_SECONDS} sn boyunca hiçbir çıktı vermedi ve durduruldu. "
                                   "İsteği tekrar gönder ya da daha kısa parçalara böl.")
            self.no_think = True
            self.cb.on_text("*(Model takıldı; yeniden deniyorum.)*\n\n")
            return self._ollama_call(url, system, messages, tools)

    def _ollama_call(self, url: str, system: dict, messages: list, tools: list) -> tuple[str, list, dict]:
        sysinfo.make_room(self.settings.ollama_url, self.settings.ollama_model)
        num_ctx = power.num_ctx(self.settings)  # pilde en çok 8K: kısa geçmiş, hızlı okuma
        fixed = len(system.get("content") or "") + len(json.dumps(tools or []))
        scale = _CTX_SCALE.get(self.settings.ollama_model, 1.0)
        sent = fit_context(messages, num_ctx, fixed, scale)
        # cevap bağlamın kalanına sığsın: taşarsa Ollama istemin başını silip üretmeyi sürdürür (context shift),
        # model kendi talimatını kaybeder ve anlamsız, dakikalarca süren bir cevap yazar
        room = num_ctx - estimate_tokens(sent, fixed) * scale
        saglayici = sg_ollama.OllamaSaglayici(url, self.settings.ollama_model)
        payload = saglayici.istek([system, *sent], "", tools, num_ctx=num_ctx,
                                  num_predict=int(min(NUM_PREDICT, max(REPLY_RESERVE, room))),
                                  dusunme=not self.no_think, bicim=self.json_format)
        content, tool_calls, final = "", [], {}
        thought = 0  # bu çağrıda üretilen düşünme metninin uzunluğu
        checked = 0  # tekrar denetiminin en son baktığı metin uzunluğu
        started = time.monotonic()
        # boş akış (takılma) sağlayıcıda httpx.ReadTimeout olur; "araç yok" hatası AracDesteklenmiyor; içi boş
        # satırlar NABIZ olarak gelir: iptal (■ / Esc) her satırda denetlenir
        with closing(_eski_hata_metni(saglayici.akis([], govde=payload, okuma_zaman_asimi=STALL_SECONDS))) as akis:
            for parca in akis:
                self._check_cancel()
                if parca.tur == sg.DUSUNCE:
                    self.cb.on_thinking(parca.metin)
                    thought += len(parca.metin)
                    if (thought > THINK_LIMIT or time.monotonic() - started > THINK_SECONDS) \
                            and not content and not tool_calls:
                        raise _ThinkTooLong()
                elif parca.tur == sg.METIN:
                    content += parca.metin
                    self.cb.on_text(parca.metin)
                    if len(content) - checked >= 200:
                        checked = len(content)
                        cut = repeat_cut(content)
                        if cut:  # akışı kapatmak (closing) Ollama'da üretimi de durdurur
                            content = content[:cut]
                            self.cb.on_text("\n\n*(Model aynı metni tekrar tekrar yazmaya başladı; durdurdum.)*\n\n")
                            final = {"done_reason": "repeat"}
                            break
                elif parca.tur == sg.ARAC:
                    tool_calls.extend(parca.araclar)
                elif parca.tur == sg.SON:
                    final = parca.son
        if final.get("done_reason") == "length":
            self._learn_ctx(num_ctx, final.get("eval_count", 0), estimate_tokens(payload["messages"][1:], fixed))
        return content, tool_calls, final

    def _learn_ctx(self, num_ctx: int, produced: int, estimated: float) -> None:
        """Bağlam doldu: istemin gerçek boyu ≈ bağlam − üretilen token. Tahmin bunun altında kaldıysa
        (uzun araç çıktıları, Türkçe metin) sonraki çağrılarda geçmiş o oranda daha sıkı kırpılır; yoksa
        model cevaba birkaç token yazıp kesilir ve "devam et" döngüsü de hiçbir şey kazandırmaz."""
        actual = num_ctx - produced
        if produced >= REPLY_RESERVE or estimated <= 0 or actual <= 0:
            return  # cevap için ayrılan yer yetti; cevap gerçekten uzundu
        model = self.settings.ollama_model
        _CTX_SCALE[model] = min(3.0, max(_CTX_SCALE.get(model, 1.0), actual / estimated * 1.1))

    # ---- OpenAI uyumlu sağlayıcılar (OpenAI, Gemini, Groq, OpenRouter, LM Studio...) ----

    def _run_openai(self, messages: list, conn: Connection) -> None:
        model = self.settings.api_models.get(conn.id) or (conn.models[0] if conn.models else "")
        if not model:
            raise RuntimeError(f"{conn.name} için model seçilmemiş. API'ler sekmesinden bağlantıyı test et.")
        saglayici = OpenAIUyumluSaglayici(conn, model)
        tools = [
            {"type": "function", "function": {"name": s["name"], "description": s["description"], "parameters": s["input_schema"]}}
            for s in self.tool_specs
        ]
        system = {"role": "system", "content": self._system()}
        state = {}  # bu turda yapılan uyarılar (_unfinished_nudge)
        fixed = len(system["content"]) + len(json.dumps(tools))
        self._compact(messages, system, tools, api_context(model))
        for step in range(1, MAX_STEPS + 1):
            self._check_cancel()
            self.cb.on_model_start(step)
            ctx = api_context(model)
            payload = saglayici.istek([system, *fit_context(messages, ctx, fixed)], "", tools,
                                      json_bicimi=bool(self.json_format))
            started = time.monotonic()
            content, tool_calls, son = "", [], {}
            try:
                with closing(saglayici.akis([], govde=payload)) as akis:
                    for parca in akis:
                        self._check_cancel()
                        if parca.tur == sg.DUSUNCE:
                            self.cb.on_thinking(parca.metin)
                        elif parca.tur == sg.METIN:
                            content += parca.metin
                            self.cb.on_text(parca.metin)
                        elif parca.tur == sg.SON:
                            tool_calls, son = parca.araclar, parca.son
            except sg.SaglayiciHatasi as e:
                if e.durum in (400, 413) and _OVERFLOW.search(e.govde) and ctx > MIN_API_CTX:
                    # bağlam aşıldı (LM Studio 4K, küçük Groq modelleri…): bütçe yarıya, özetle, yeniden dene
                    _API_CTX[model] = max(MIN_API_CTX, ctx // 2)
                    self._compact(messages, system, tools, _API_CTX[model], force=True)
                    continue
                if e.durum == 401:
                    raise key_error(conn, 401) from None
                raise RuntimeError(f"{conn.name} hatası ({e.durum}): {e.govde[:500]}") from None

            elapsed = time.monotonic() - started
            usage = son.get("usage") or {}
            out_tokens = usage.get("completion_tokens") or son.get("parca", 0)
            yonlendirici.harcama_ekle(f"api:{conn.id}", (usage.get("prompt_tokens") or 0) + (out_tokens or 0))
            self.cb.on_model_end({
                "model": model,
                "input_tokens": usage.get("prompt_tokens", 0),
                "output_tokens": out_tokens,
                "seconds": elapsed,
                "tokens_per_sec": out_tokens / elapsed if elapsed else 0,
            })
            assistant = {"role": "assistant", "content": content}
            if tool_calls:
                assistant["tool_calls"] = tool_calls
            messages.append(assistant)
            if not tool_calls:
                # OpenAI uyumlu bağlantılar da küçük modellere gidebilir (LM Studio, Groq…): aynı uyarılar
                nudge = self._unfinished_nudge(messages, content, bool(tools), step, state)
                if nudge:
                    messages.append({"role": "user", PROGRAM: True, "content": nudge})
                    continue
                return
            self._run_calls(tool_calls, messages, ollama=False)
            if self._stopped_by_security() or self._soru_ile_bitti(messages):
                return
            if self.gate_actions and self.blocked_calls >= 2 and tools:
                tools = []  # engellenen işlemde ısrar: araçları kapat, planı yazsın
            self.cb.on_text("\n\n")
        self.cb.on_text("\n\n*Adım sınırına ulaşıldı.*")


def repeat_cut(text: str) -> int:
    """Model kendini tekrar ediyor mu? Son REPEAT_TAIL karakter metinde REPEAT_COUNT kez geçiyorsa döngüdedir;
    metnin kesileceği yer (ilk geçişin sonu: bir kopya kalır) döner, döngü yoksa 0."""
    if len(text) < REPEAT_TAIL * REPEAT_COUNT:
        return 0
    tail = text[-REPEAT_TAIL:]
    if not tail.strip() or text.count(tail) < REPEAT_COUNT:
        return 0
    return text.find(tail) + REPEAT_TAIL


def _eski_hata_metni(akis):
    """Sağlayıcının HTTP hatası kullanıcıya eskisi gibi görünsün ("RuntimeError: Ollama hatası (500): …")."""
    try:
        yield from akis
    except sg.SaglayiciHatasi as e:
        raise RuntimeError(str(e)) from None


class _ThinkTooLong(Exception):
    """Ollama: model cevaba geçmeden çok uzun düşündü (döngüye girmiş olabilir)."""


_NoToolSupport = sg_ollama.AracDesteklenmiyor  # Ollama: seçili model araç çağrısını desteklemiyor

# K1: sağlayıcıya özgü yardımcılar çekirdekte (cekirdek/saglayici); eski adlar aynı işlevler
ollama_models = sg_ollama.modeller  # kurulu modeller (/api/tags)
ollama_running = sg_ollama.bellekteki_modeller  # bellekteki modeller (/api/ps)
list_ollama_models = sg_ollama.model_adlari
describe_error = sg.hata_metni  # hataları kullanıcıya gösterilecek Türkçe metne çevirir
