"""Güvenlik ajanı: kullanıcı yerine işlemleri denetler ve onaylar.

Her yan etkili araç çağrısı (komut, Python, dosya yazma, API isteği…) çalışmadan önce buradan geçer:
1. Kurallar (anında): işlem dört risk katmanından birine konur.
   düşük  → onaylanır (ör. çalışma klasörüne yazmak, salt okunur komut)
   orta   → güvenlik modeli inceler (ör. paket kurmak, klasörde silmek)
   yüksek → güvenlik modeli ancak istek gerçekten gerektiriyorsa onaylar (ör. sudo, klasör dışına yazmak)
   yasak  → her durumda reddedilir (ör. rm -rf ~, disk biçimlendirmek, gizli anahtarı dışarı göndermek)
2. Güvenlik modeli (orta/yüksek): isteğe uygun mu, zararlı mı, daha güvenli bir yol var mı? Kararı:
   onay · "farklı yol dene" (asistan başka bir çözüm arar) · ret (zararlı; yapılmaz).
Model yanıt veremezse temkinli davranılır: orta risk KULLANICIYA sorulur ("ask"; K12-A3 — paket kurma, silme, ağ
gönderme kural tarafından onaylanmaz), yüksek geri çevrilir.
"""

import json
import re
from dataclasses import dataclass, field
from pathlib import Path

import httpx

from .registry import REGISTRY

LOW, MEDIUM, HIGH, FORBIDDEN = "düşük", "orta", "yüksek", "yasak"

# her durumda reddedilen: geri dönüşü olmayan yıkım, sisteme sızma, gizli bilgiyi dışarı çıkarma
_FORBIDDEN = [
    (r"\brm\s+(-[a-zA-Z]*\s+)*(-[a-zA-Z]*[rR][a-zA-Z]*\s+)(-[a-zA-Z]*\s+)*(/|/\*|~|~/|~/\*|\$HOME/?|\$HOME/\*|/home/?\w*/?|/(etc|usr|boot|bin|lib|lib64|var|opt|root|srv|sys|proc)(/\S*)?)(\s|$|;|&)",
     "kök, ev klasörü ya da sistem klasörlerini topluca siliyor"),
    (r"\bmkfs(\.\w+)?\b|\bwipefs\b|\bfdisk\b|\bparted\b|\bsgdisk\b", "diski biçimlendiriyor ya da bölümlüyor"),
    (r"\bdd\b[^\n]*\bof=/dev/(sd|nvme|hd|vd|mmcblk)", "diske doğrudan yazıyor"),
    (r">\s*/dev/(sd|nvme|hd|vd|mmcblk)", "diske doğrudan yazıyor"),
    (r":\(\)\s*\{\s*:\|:&\s*\};:", "sistemi kilitleyen çatal bombası"),
    (r"\bchmod\s+(-R\s+)?[0-7]*777\s+/(\s|$)|\bchown\s+-R\s+\S+\s+/(\s|$)", "bütün sistemin izinlerini bozuyor"),
    (r"\bkill\s+-9\s+-1\b|\bkillall5\b", "bütün süreçleri öldürüyor"),
    (r"(curl|wget)\b[^|\n]*\|\s*(sudo\s+)?(ba|z|)sh\b", "internetten inen betiği incelemeden çalıştırıyor"),
    (r"/etc/(sudoers|shadow|passwd)\b[^\n]*(>|tee|sed\s+-i|echo)|\bvisudo\b|\bpasswd\b", "yetki/parola dosyalarını değiştiriyor"),
    (r"(\.ssh/id_|\.gnupg|keyring|anahtarlar\.json|\.aws/credentials|wallet)[^\n]*(curl|wget|requests\.|httpx\.|nc\s|scp|rsync)|"
     r"(curl|wget|requests\.|httpx\.|nc\s|scp|rsync)[^\n]*(\.ssh/id_|\.gnupg|anahtarlar\.json|\.aws/credentials)",
     "gizli anahtarları dışarı gönderiyor"),
    (r"history\s+-c|>\s*~/\.(bash|zsh)_history|\bshred\b[^\n]*(/var/log|~)", "izleri siliyor"),
    (r"(?:yeni-nesil-cafer|yerel-asistan)[/\\]+hooks\.json|\bhooks\.json\b", "programın kendiliğinden çalışan komutlarına (hooks.json) dokunuyor"),
    (r"\b(xmrig|minerd|cpuminer)\b", "kripto para madenciliği"),
    (r"\bsetenforce\s+0|ufw\s+disable|iptables\s+-F|systemctl\s+(stop|disable)\s+(firewalld|ufw|apparmor)",
     "güvenlik korumalarını kapatıyor"),
    (r"shutil\.rmtree\(\s*(['\"]/['\"]|Path\.home\(\)|os\.path\.expanduser\(['\"]~['\"]\))", "ev klasörünü ya da kökü siliyor"),
    (r"\bfind\s+(/|~|\$HOME|/home(/\w+)?|/(etc|usr|boot|var|opt|root))/?\s[^\n]*(-delete|-exec\s+rm)",
     "kök, ev klasörü ya da sistem klasörlerinde toplu silme yapıyor"),
]

# yüksek: yetki yükseltme, klasör dışına dokunma, sistem ayarı, dışarıya veri gönderme, kaldırma
_HIGH = [
    (r"\bsudo\b|\bpkexec\b|\bdoas\b|\bsu\s", "yönetici (root) yetkisi istiyor"),
    (r"\bsystemctl\s+(start|stop|restart|enable|disable|mask)|\bcrontab\b|/etc/", "sistem ayarını değiştiriyor"),
    (r"\b(pacman|yay|paru)\s+-R|\bapt(-get)?\s+(remove|purge|autoremove)|\bdnf\s+remove|\bflatpak\s+uninstall|"
     r"\bpip3?\s+uninstall|\bsnap\s+remove|winget\s+uninstall", "program kaldırıyor"),
    (r"\breboot\b|\bshutdown\b|\bpoweroff\b|\bkillall\b|\bpkill\b|\bkill\s", "süreçleri kapatıyor ya da bilgisayarı yeniden başlatıyor"),
    (r"\bgit\s+push\b|\bscp\b|\brsync\b[^\n]*:|\bnc\s|\bcurl\b[^\n]*(-X\s*(POST|PUT|DELETE)|--data|-d\s|-F\s|-T\s)",
     "dışarıya veri gönderiyor"),
    (r"\bchmod\b|\bchown\b|\bmount\b|\bumount\b", "izinleri ya da diskleri değiştiriyor"),
    (r"Remove-Item[^\n]*-Recurse|Format-Volume|Set-ExecutionPolicy|reg\s+(add|delete)|bcdedit", "Windows sistemine dokunuyor"),
]

# orta: kurulum, silme, taşıma, internet, Python'dan komut
_MEDIUM = [
    (r"\b(pip3?|pipx|npm|pnpm|yarn|pacman|yay|paru|apt(-get)?|dnf|flatpak|cargo|winget|brew|snap)\s+(install|add|-S)",
     "program ya da paket kuruyor"),
    (r"\brm\s|\brmdir\b|shutil\.rmtree|os\.remove|os\.unlink|\.unlink\(|os\.rmdir|Remove-Item|\bdel\s|"
     r"-delete\b|\btruncate\b|\bshred\b", "dosya siliyor"),
    (r"\bmv\s|shutil\.move|os\.rename|\.rename\(|Move-Item", "dosya taşıyor"),
    (r"subprocess|os\.system|os\.popen", "Python içinden komut çalıştırıyor"),
    (r"\bcurl\b|\bwget\b|requests\.(post|put|delete|patch)|httpx\.(post|put|delete|patch)|\bgit\s+clone",
     "internetten indiriyor ya da internete bağlanıyor"),
]


def _mass_delete_outside(text: str, workspace: str) -> str:
    """Çalışma klasörü dışında toplu silme (ör. ~/.cache/*, ~/Belgeler): hangi model onaylarsa onaylasın geri çevrilir."""
    if not re.search(r"\brm\s+(-\w*\s+)*-\w*[rR]|shutil\.rmtree|Remove-Item[^\n]*-Recurse", text):
        return ""
    home = str(Path.home())
    paths = re.findall(r"(?:~|\$HOME)/[\w./+-]*\*?|(?<![\w.:/-])/[\w./+-]+\*?", text)  # tam yol (sonundaki * dahil)
    for p in [x for x in paths if x in " ".join(_outside_paths(text, workspace)) or x.startswith(("~", "$HOME"))
              or x.rstrip("*") in " ".join(_outside_paths(text, workspace))]:
        full = p.replace("$HOME", home)
        rel = full[2:] if full.startswith("~/") else (full[len(home) + 1:] if full.startswith(home + "/") else "")
        depth = len([x for x in rel.rstrip("*").strip("/").split("/") if x])
        if full.endswith("*") or (rel and depth <= 1) or full.rstrip("/") in (home, "~"):
            return p
    return ""


DECISION_NAMES = {"approve": "onaylandı", "revise": "geri çevrildi — başka yol denenecek", "reject": "reddedildi",
                  "ask": "güvenlik modeli yok — kullanıcıya soruldu"}


TIER_MEANING = {
    LOW: "düşük risk: çalışma klasöründe kalan ya da yalnızca okuyan işler",
    MEDIUM: "orta risk: kurulum, silme, taşıma gibi işler; güvenlik modeli isteğine uygun mu diye bakar",
    HIGH: "yüksek risk: yönetici yetkisi, sistem ayarı, program kaldırma, klasör dışına yazma, dışarıya veri "
          "gönderme; ancak isteğin gerçekten gerektiriyorsa onaylanır",
    FORBIDDEN: "yasak: geri dönüşü olmayan yıkım ya da gizli bilgiyi dışarı çıkarma; her durumda reddedilir",
}


def explain(label: str, args: dict, verdict: "Verdict") -> str:
    """"Neden?" düğmesinin açtığı açıklama (Markdown): ne istendi, hangi katman, neden, ne yapılabilir."""
    args = args if isinstance(args, dict) else {}
    what = str(args.get("command") or args.get("code") or args.get("path") or args.get("packages")
               or args.get("url") or args.get("api") or "").strip()
    if len(what) > 600:
        what = what[:600] + "\n…(kısaltıldı)"
    purpose = str(args.get("purpose") or "").strip()
    lines = [f"**Yapılmak istenen:** {label}"]
    if purpose:
        lines.append(f"**Asistanın gerekçesi:** {purpose}")
    if what:
        lines.append(f"```\n{what}\n```")
    lines.append(f"**Risk katmanı:** {TIER_MEANING.get(verdict.tier, verdict.tier)}")
    if verdict.findings:
        lines.append("**Kuralların bulduğu:** " + "; ".join(verdict.findings))
    lines.append(f"**Güvenlik ajanının kararı:** {DECISION_NAMES.get(verdict.decision, verdict.decision)} — {verdict.reason}")
    if verdict.decision == "revise":
        lines.append("Asistan aynı sonuca daha güvenli bir yoldan ulaşmayı dener. Bu adımın aynen yapılmasını istiyorsan "
                     "güvenliği kapatıp isteğini yeniden gönder; o zaman her adım sana sorulur.")
    else:
        lines.append("Bu işlem zararlı sayıldığı için yapılmadı. Yine de yapılmasını istiyorsan güvenliği kapatıp "
                     "isteğini yeniden gönder; o zaman karar tamamen sende olur ve her adım sana sorulur.")
    return "\n\n".join(lines)


def note(label: str, decision: str, tier: str, reason: str) -> str:
    """Sohbette gösterilecek kısa karar notu."""
    return f"🛡 {DECISION_NAMES.get(decision, decision)} · {tier} risk · {label} — {reason}"


@dataclass
class Verdict:
    decision: str  # "approve" · "revise" · "reject" · "ask" (model yok: karar kullanıcının; agent._permit sorar)
    tier: str
    reason: str
    findings: list = field(default_factory=list)

    @property
    def approved(self) -> bool:
        return self.decision == "approve"


def _text(name: str, args: dict) -> str:
    if name == "call_api":
        return f"{args.get('method', 'GET')} {args.get('api', '')} {args.get('path', '')} {json.dumps(args.get('body') or {})}"
    return str(args.get("command") or args.get("code") or args.get("packages") or "")


def _outside_paths(text: str, workspace: str) -> list[str]:
    root = str(Path(workspace).expanduser().resolve())
    # "*/raporlar/*" gibi joker kalıpları ve URL parçaları yol sayılmaz
    found = re.findall(r"(?<![\w.:/*?-])(/[\w.+-]+(?:/[\w.+-]+)*|~/[\w./+-]*|[A-Za-z]:\\[\w\\. -]+)", text)
    found += re.findall(r"(?<![\w/.~-])(~|\$HOME)(?=[\s\"';]|$)", text)  # yalın ~ ya da $HOME: bütün ev klasörü
    safe = (root, "/tmp", "/dev/null", "/usr/bin", "/bin", "/usr/share", "/proc/", "/sys/class")
    return [p for p in found if not str(Path(p.replace("$HOME", "~")).expanduser()).startswith(safe)]


def forbidden(name: str, args: dict) -> str:
    """Yasak listesindeyse nedeni (her kipte reddedilir, kullanıcı onayı da açmaz); değilse boş."""
    tool = REGISTRY.get(name)
    text = _text(name, args if isinstance(args, dict) else {})
    if tool is not None and tool.source != "yerlesik" and isinstance(args, dict):
        # yetenek (alan adları Türkçe) ve MCP (K12-A7: sunucunun şeması ne olursa olsun) argümanlarının hepsi taranır
        text = " ".join(str(v) for v in args.values())
    return next((why for pattern, why in _FORBIDDEN if re.search(pattern, text, re.I)), "")


def needs_model(name: str, args: dict, workspace: str) -> bool:
    """Kurallar tek başına karar veremiyor mu (orta / yüksek risk)? Değilse güvenlik modeli hiç yüklenmez."""
    return classify(name, args, workspace)[0] in (MEDIUM, HIGH)


def classify(name: str, args: dict, workspace: str) -> tuple[str, list[str]]:
    """Kurallarla risk katmanı ve gerekçeler (Türkçe)."""
    args = args if isinstance(args, dict) else {}
    root = Path(workspace).expanduser().resolve()
    tool = REGISTRY.get(name)
    if tool is not None and tool.source == "yetenek":  # görev motorunun sandbox yeteneği (K5): manifestin izinleri
        izin, ad = set(tool.hints.get("izinler") or []), name.removeprefix("y_")
        if not tool.hints.get("guvenilir") or izin & {"komut", "dosya_sil"}:
            return HIGH, [f"“{ad}” yeteneği (programla gelmeyen ya da komut/silme izinli kod) sandbox'ta çalışıyor"]
        if izin & {"ag", "dosya_yaz"} or any(i.startswith("anahtar:") for i in izin):
            return MEDIUM, [f"“{ad}” yeteneği sandbox'ta çalışıyor (izinler: {', '.join(sorted(izin))})"]
        return LOW, [f"“{ad}” yeteneği sandbox'ta yalnızca okuyor"]
    if tool is not None and tool.source != "yerlesik":  # takılan MCP sunucusunun aracı: sunucunun işaretlerine göre
        where = tool.source.split(":", 1)[-1]
        if tool.hints.get("readOnlyHint"):
            if tool.trusted:
                return LOW, [f"“{where}” MCP sunucusundan yalnızca bilgi okuyor"]
            # K12-A7: sunucunun beyanı kanıt değil; güvenilenler listesinde (mcp.json "trusted") değilse model bakar
            return MEDIUM, [f"“{where}” MCP sunucusu aracı 'yalnızca okur' diyor ama sunucu güvenilenler listesinde değil"]
        if tool.hints.get("destructiveHint", True):  # MCP kuralı: işaret yoksa yıkıcı olabilir sayılır
            return HIGH, [f"“{where}” MCP sunucusunda geri alınamayabilecek bir değişiklik yapıyor"]
        return MEDIUM, [f"“{where}” MCP sunucusunda bir işlem çalıştırıyor"]
    if name in ("write_file", "edit_file"):
        target = (root / str(args.get("path", ""))).resolve()
        if not target.is_relative_to(root):
            return HIGH, ["çalışma klasörünün dışına yazıyor"]
        if target.exists() and name == "write_file":
            return LOW, ["çalışma klasöründeki bir dosyanın üzerine yazıyor"]
        return LOW, ["çalışma klasörüne yazıyor"]
    if name == "generate_image":
        return LOW, ["çalışma klasörüne resim üretiyor"]
    if name in ("start_team_task", "remember"):
        return LOW, ["ekibe iş veriyor" if name == "start_team_task" else "hafızaya kaydediyor"]
    if name == "install_python_package":
        return MEDIUM, [f"Python kütüphanesi kuruyor: {args.get('packages', '')}"]
    if name == "install_app":  # internetten program indirip kuruyor: kaynak denetlenir
        from .apps import trusted

        source = str(args.get("source") or "")
        where = f"{args.get('name', '')} ({source or 'paket yöneticisinden'})"
        if not trusted(source):
            return HIGH, [f"bilinen bir yayıncı olmayan kaynaktan program indiriyor: {where}"]
        return MEDIUM, [f"bilinen bir kaynaktan uygulama kuruyor: {where}"]
    if name == "call_api":
        method = str(args.get("method") or "GET").upper()
        return (LOW, ["servisten veri okuyor"]) if method == "GET" else (HIGH, [f"servise {method} isteği gönderiyor"])
    text = _text(name, args)
    for pattern, why in _FORBIDDEN:
        if re.search(pattern, text, re.I):
            return FORBIDDEN, [why]
    findings = [why for pattern, why in _HIGH if re.search(pattern, text)]
    if re.search(r"\.ssh/|\.gnupg|\.aws/|\.netrc|keyring|secretstorage|SecretService|kwallet|anahtarlar\.json|bulut\.json|"
                 r"/etc/shadow|\.password-store|"
                 r"\.mozilla/[^\n]*(logins|key4)|Login Data", text):
        findings.append("gizli anahtar ya da parola dosyalarına erişiyor")  # okumak bile yüksek risk
    outside = _outside_paths(text, workspace)
    writes_outside = bool(outside) and re.search(r"\brm\s|\bmv\s|\bcp\s|>\s*\S|\btee\b|write|remove|unlink|rmtree|-delete\b|"
                                                 r"rename|mkdir|touch|chmod|sed\s+-i|Set-Content|Out-File", text)
    if writes_outside:
        findings.append("çalışma klasörünün dışındaki dosyalara dokunuyor: " + ", ".join(outside[:3]))
    if findings:
        return HIGH, findings
    findings = [why for pattern, why in _MEDIUM if re.search(pattern, text)]
    if outside:
        findings.append("çalışma klasörü dışındaki yolları okuyor: " + ", ".join(outside[:3]))
    return (MEDIUM, findings) if findings else (LOW, ["yalnızca çalışma klasöründe çalışıyor"])


_PROMPT = """You are the SECURITY AGENT of a desktop AI assistant. The user has delegated all approvals to you: you \
decide whether the assistant may run the action below on the user's real computer ({os}).

User's request (what the user actually asked for):
<<<{request}>>>

Proposed action: {tool}
{details}

Rule-based risk tier: {tier} — {findings}
Workspace folder (the assistant's sandbox): {workspace}

Decide:
- "approve": the action serves the user's request, and its effects are proportionate and reversible enough. For \
tier "yüksek" approve ONLY if the request clearly needs exactly this and there is no safer way. If the user \
explicitly asked for exactly this (e.g. "delete the .log files"), approve it — don't second-guess their wishes. An \
action may be just ONE step of a longer plan: never send it back only because it doesn't do the whole task.
- "revise": ONLY for safety or correctness problems — the action is a wrong or overly risky way to do a legitimate task (e.g. deletes more than needed, wrong \
package name, touches files outside the task, uses sudo where not needed, a destructive command where a targeted \
one exists). The assistant will try another way; say concretely what to do instead.
- "reject": the action is harmful, not requested by the user (e.g. deleting/sending the user's data, disabling \
protections, installing something unrelated), or the user's request itself is harmful.

Answer with JSON only: {{"decision": "approve|revise|reject", "reason": "one short sentence in Turkish"}}"""


def _details(name: str, args: dict) -> str:
    shown = {k: v for k, v in args.items() if k != "purpose"}
    body = json.dumps(shown, ensure_ascii=False, indent=1)
    if len(body) > 3500:
        body = body[:3500] + "\n…(kısaltıldı)"
    purpose = str(args.get("purpose") or "").strip()
    return (f"Assistant's stated purpose: {purpose}\n" if purpose else "") + f"Arguments:\n{body}"


def _ask_model(prompt: str, ollama_url: str, model: str, num_ctx: int | None = None) -> dict | None:
    schema = {"type": "object", "properties": {"decision": {"type": "string", "enum": ["approve", "revise", "reject"]},
                                               "reason": {"type": "string"}}, "required": ["decision", "reason"]}
    try:
        resp = httpx.post(ollama_url.rstrip("/") + "/api/chat", timeout=120, json={
            "model": model, "stream": False, "think": False, "format": schema, "keep_alive": "30m",
            # sohbet modeliyle aynıysa aynı bağlam: yoksa Ollama modeli her denetimde yeniden yükler (ölçüldü: 5–6 sn)
            "options": {"temperature": 0, "num_predict": 200, **({"num_ctx": num_ctx} if num_ctx else {})},
            "messages": [{"role": "user", "content": prompt}]})
        resp.raise_for_status()
        data = json.loads(resp.json()["message"]["content"])
        if data.get("decision") in ("approve", "revise", "reject"):
            return data
    except Exception:
        return None
    return None


_reviewer_cache: dict = {}
# reddetme davranışı kaldırılmış (sansürsüz) modeller denetçi olamaz: neredeyse her şeyi onaylarlar
from .model_updates import UNCENSORED  # noqa: E402  (tek liste)


def pick_reviewer(ollama_url: str, chat_model: str, saving: bool = False) -> str:
    """Güvenlik modeli: sohbet modeli yeterince güçlüyse o (model değiştirme gecikmesi olmaz), değilse kurulu ve
    belleğe sığan en büyük model. Küçük modeller (4B gibi) zararlı komutları onaylayabiliyor (ölçüldü).

    saving (pilde): bütçe en çok 8B'lik model; büyük denetçi pilde her işlemi yarım dakika bekletir."""
    key = (ollama_url, chat_model, saving)
    if key in _reviewer_cache:
        return _reviewer_cache[key]
    try:
        models = httpx.get(ollama_url.rstrip("/") + "/api/tags", timeout=5).json().get("models", [])
    except Exception:
        return chat_model
    sizes = {m["name"]: m.get("size", 0) / 1e9 for m in models
             if not re.search(r"embed|ocr|whisper|bge|minilm", m["name"], re.I) and not UNCENSORED.search(m["name"])}
    if sizes.get(chat_model, 0) >= 6:
        pick = chat_model
    else:
        from . import sysinfo

        info = sysinfo.scan(ollama_url)
        budget = info.vram_gb * 0.92 if info.vram_gb else info.ram_gb * 0.4
        if saving:
            budget = min(budget, 6.0)  # ~8B (Q4): yavaş ama 4B'den güvenilir; kurallar yine önce çalışır
        fits = [n for n, gb in sizes.items() if gb <= budget]
        pick = max(fits, key=lambda n: sizes[n]) if fits else (max(sizes, key=sizes.get) if sizes else "")
    _reviewer_cache[key] = pick
    return pick


def review(name: str, args: dict, request: str, workspace: str, ollama_url: str, model: str,
           os_name: str = "", num_ctx: int | None = None) -> Verdict:
    """İşlemi denetler: kurallar, gerekirse güvenlik modeli."""
    args = args if isinstance(args, dict) else {}
    tier, findings = classify(name, args, workspace)
    if tier == FORBIDDEN:
        return Verdict("reject", tier, f"Zararlı işlem: {findings[0]}.", findings)
    if tier == LOW:
        return Verdict("approve", tier, findings[0] if findings else "düşük risk", findings)
    mass = _mass_delete_outside(_text(name, args), workspace)
    if mass:
        return Verdict("revise", tier, f"{mass} altındaki her şeyi topluca silmek çok riskli. Yalnızca gereksiz olduğu "
                                       "bilinen belirli alt klasörleri ya da sistemin kendi temizlik araçlarını kullan "
                                       "(ör. paccache, journalctl --vacuum-time).", findings)
    answer = _ask_model(_PROMPT.format(os=os_name or "?", request=(request or "?")[:1500], tool=name,
                                       details=_details(name, args), tier=tier, findings="; ".join(findings),
                                       workspace=workspace), ollama_url, model, num_ctx) if model else None
    if answer is None:  # güvenlik modeli yok/yanıt vermedi: temkinli
        if tier == MEDIUM:  # K12-A3: kural tek başına kurulum/silme/ağ onaylamaz; kullanıcıya sorulur
            return Verdict("ask", tier, "Güvenlik modeline ulaşılamadı; orta riskli adım kullanıcıya soruluyor.", findings)
        return Verdict("revise", tier, "Güvenlik modeline ulaşılamadı; yüksek riskli adım onaylanmadı. Daha güvenli "
                                       "bir yol dene.", findings)
    reason = " ".join(str(answer.get("reason") or "").split())[:300] or "; ".join(findings)
    return Verdict(answer["decision"], tier, reason, findings)
