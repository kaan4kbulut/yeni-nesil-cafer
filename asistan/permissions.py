"""İzin hattı: bir araç çağrısı çalışsın mı, sorulsun mu, güvenlik ajanına mı gitsin, bekletilsin mi — tek yerde.

Sıra (ilk eşleşen karar verir):
1. Yasak listesi (`security.forbidden`): hangi kipte ve hangi onayla olursa olsun reddedilir.
2. ✓ düğmesi beklenirken (gate_actions) değişiklik yapan çağrı: bekleyen işlem olur, çalışmaz.
3. Güvenlik ajanı kipi: onay gerektiren ya da değişiklik yapan çağrı güvenlik ajanına gider.
4. Sansürsüz model (güvenlik ajanı çalışamaz): riskli adımlar kullanıcıya sorulur — "komutları onayla" kapalı olsa
   bile (o kutu yalnızca kullanıcı kipinde görünür; kapalı kalmışsa güvenlik tamamen kalkmasın).
5. Kullanıcı kipi: onay gerektiren (ya da ▶ turunda değişiklik yapan) çağrı kullanıcıya sorulur; "komutları onayla"
   kapalıysa, "bu oturumda hep izin ver" ya da otomatik onay listesindeyse sorulmaz.
Yeni bir onay kuralı yalnızca buraya eklenir; `agent._execute_tool` kararı uygular, kendisi karar vermez.
Araç dışı tek kural: bulut maliyet tavanı (`bulut_tavani`) aşılınca ücretli bulut çağrısı hep kullanıcıya sorulur.
"""

import re
import sys
from dataclasses import dataclass
from typing import Callable

from .registry import ACTION_RISKS, REGISTRY
from .tools import needs_approval

ALLOW, ASK, REVIEW, PENDING, DENY = "izin", "sor", "denetle", "bekle", "yasak"

# yalnızca bilgi okuyan komutlar (plan yapmak için disk, paket, donanım durumu): onaysız çalışabilir
_READONLY_CMDS = {"df", "du", "ls", "free", "uname", "whoami", "hostname", "lsblk", "lscpu", "lspci", "lsusb", "nproc",
                  "uptime", "which", "whereis", "type", "stat", "file", "echo", "date", "pwd", "nvidia-smi",
                  "sensors", "id", "locale", "tree"}
# dosya İÇERİĞİ okuyanlar: yalnızca boru hattında önceki komutun çıktısını işlerken (du … | sort -h); doğrudan
# dosya okumak onaysız olmasın (read_file çalışma klasörüyle sınırlı; ~/.ssh gibi özel dosyalar dışarı sızmasın)
_PIPE_FILTERS = {"sort", "uniq", "head", "tail", "wc", "grep", "cut", "column"}  # awk yok: system() çalıştırır
_READONLY_SUB = {"pacman": ("-Q",), "dpkg": ("-l", "-L", "-s"), "rpm": ("-q",), "flatpak": ("list", "info"),
                 "snap": ("list", "info"), "systemctl": ("status", "is-active", "is-enabled", "list-units"),
                 "journalctl": ("--disk-usage",), "ip": ("addr", "a", "route", "link"), "ollama": ("list", "ps", "show"),
                 "pip": ("list", "show"), "python3": ("--version",), "git": ("status", "branch")}


def is_readonly_command(command: str) -> bool:
    """Bu kabuk komutu kesinlikle hiçbir şeyi değiştirmiyor mu? Şüphede hayır (onay gerekir)."""
    if sys.platform == "win32" or not command.strip():
        return False
    if re.search(r"[;`<>\n]|\$\(|&(?!&)|\bsudo\b|\bxargs\b", command.replace("2>/dev/null", "")
                 .replace("2>&1", "").replace("&&", "")):
        return False
    for part in re.split(r"&&|\|\|", command):
        for n, piece in enumerate(part.split("|")):
            words = piece.split()
            if not words:
                return False
            if n > 0 and words[0] in _PIPE_FILTERS and not any("/" in w or w.startswith(("~", ".")) for w in words[1:]):
                continue  # boru süzgeci: dosya adı almıyor
            if not _readonly_program(words):
                return False
    return True


def _readonly_program(words: list[str]) -> bool:
    prog = words[0]
    if prog in _READONLY_CMDS:
        return True
    if prog == "find" and not any(w in ("-delete", "-exec", "-execdir", "-ok", "-fprint", "-fls") for w in words):
        return True
    subs = _READONLY_SUB.get(prog)
    return bool(subs and len(words) > 1 and any(words[1] == x or (x.startswith("-Q") and words[1].startswith("-Q"))
                                                 for x in subs))


def is_readonly(name: str, args) -> bool:
    """Salt okuyan kabuk komutu mu? (run_command dışındaki araçlar için hep hayır)"""
    return name == "run_command" and isinstance(args, dict) and is_readonly_command(str(args.get("command") or ""))


def is_action(name: str, args) -> bool:
    """Bu araç çağrısı sistemde / dosyalarda / dış serviste değişiklik yapar mı?"""
    # değiştiren araçlar (kayıtta yazar / ekip / calistirir / kurar): ✓ basılmadan çalışmaz, basınca her adım onaylanır
    if is_readonly(name, args):
        return False
    if name == "call_api":
        return isinstance(args, dict) and str(args.get("method") or "GET").upper() != "GET"
    tool = REGISTRY.get(name)
    return tool is not None and tool.risk in ACTION_RISKS


@dataclass
class Context:
    """Kararı etkileyen oturum durumu (ajan her çağrıda kendi durumundan kurar)."""
    approval_mode: str = "kullanici"  # "guvenlik" | "kullanici"
    uncensored: bool = False  # sohbet modeli sansürsüz: güvenlik ajanı yanında çalışamaz
    confirm_commands: bool = True
    gate_actions: bool = False  # ✓ düğmesi bekleniyor: değişiklik yapan araçlar çalışmaz
    must_act: bool = False  # ▶ turu: değişiklik yapan her adım (dosya yazma dahil) sorulur
    always_allowed: bool = False  # "bu oturumda hep izin ver"
    auto_approve: Callable[[str, dict], bool] | None = None  # kullanıcının otomatik onay listesi


@dataclass
class Decision:
    kind: str  # ALLOW | ASK | REVIEW | PENDING | DENY
    reason: str = ""


def decide(name: str, args, ctx: Context) -> Decision:
    """Bir araç çağrısı için izin kararı (sıra modül açıklamasında)."""
    from . import security

    args = args if isinstance(args, dict) else {}
    why = security.forbidden(name, args)
    if why:
        return Decision(DENY, why)
    action = is_action(name, args)
    if ctx.gate_actions and action:
        return Decision(PENDING)
    risky = needs_approval(name, args) and not is_readonly(name, args)
    if ctx.approval_mode == "guvenlik" and not ctx.uncensored:
        return Decision(REVIEW if risky or action else ALLOW)
    user_allowed = ctx.always_allowed or bool(ctx.auto_approve and ctx.auto_approve(name, args))
    asks = risky or (ctx.must_act and action)
    # sansürsüz modelle güvenlik kipi: kullanıcı güvenlik ajanının yerine geçer, "komutları onayla" kutusu yok sayılır
    confirm = ctx.confirm_commands or ctx.approval_mode == "guvenlik"
    return Decision(ASK if asks and confirm and not user_allowed else ALLOW)


BULUT_TAVANI = "bulut_tavani"  # onay penceresine giden ad (araç değil: ücretli bulut çağrısı izni)


def bulut_tavani(asim: str, onaylandi: bool = False) -> Decision:
    """Bulut maliyet tavanı (`ayar.toml → [bulut]`) aşıldıysa ücretli bulut çağrısı kullanıcıya sorulur.

    Güvenlik ajanı, "hep izin ver" ya da otomatik onay listesi bunu geçemez: para harcatan karar hep kullanıcının.
    Aynı istekte bir kez onaylandıysa (`onaylandi`) yeniden sorulmaz."""
    if not asim or onaylandi:
        return Decision(ALLOW)
    return Decision(ASK, asim)
