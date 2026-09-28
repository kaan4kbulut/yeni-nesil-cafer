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
                 "journalctl": ("--disk-usage",), "ip": ("addr", "a", "route", "r", "link", "l"), "ollama": ("list", "ps", "show"),
                 "pip": ("list", "show"), "python3": ("--version",), "git": ("status", "branch", "log", "show", "diff")}
# K12-A1: salt okunur sayılan programların YAZAN seçenekleri (önek eşleşmesi: -fprintf, -fprint0, -okdir, -execdir…)
_FIND_YAZAN = ("-delete", "-exec", "-ok", "-fprint", "-fls")
_IP_OKUYAN = ("show", "list", "ls", "sh", "s", "get")  # `ip link set`, `ip addr add`, `ip route del` değiştirir
_NVIDIA_OKUYAN = ("-q", "-L", "-l", "-i", "-d", "-x", "-u", "-h", "--query", "--format", "--list", "--loop", "--id",
                  "--display", "--xml", "--unit", "--help")  # -r/--gpu-reset, -pl, -pm, -c, -e, -f değiştirir/yazar
_GREP_YASAK_HARF = set("rRfd")  # özyineleme (cwd taraması), -f DOSYA (dosya okur), -d recurse
_GREP_YASAK_UZUN = ("--recursive", "--dereference-recursive", "--include", "--exclude", "--file", "--directories")


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
            if n > 0 and words[0] in _PIPE_FILTERS and _pipe_filter_ok(words):
                continue  # boru süzgeci: dosya adı ve yazma/okuma seçeneği almıyor
            if not _readonly_program(words):
                return False
    return True


def _pipe_filter_ok(words: list[str]) -> bool:
    """Boru süzgeci (sort, head, grep…) yalnızca önceki komutun çıktısını işliyor mu? Dosya adı (`head -c 100 x.json`,
    `uniq - out.txt`), yazma seçeneği (`sort -o x`), `grep -r/-f/--include` (cwd'yi ya da dosyayı okur) → hayır."""
    prog, rest = words[0], words[1:]
    if any("/" in w or w.startswith(("~", ".")) for w in rest):
        return False
    konumsal = [w for w in rest if not w.startswith("-") and not w.isdigit()]
    if prog == "grep":
        for w in rest:
            if (re.fullmatch(r"-[A-Za-z]+", w) and set(w[1:]) & _GREP_YASAK_HARF) or w.startswith(_GREP_YASAK_UZUN):
                return False
        return len(konumsal) <= 1  # yalnızca desen
    if prog == "sort" and any((re.fullmatch(r"-[A-Za-z]+", w) and "o" in w[1:]) or w.startswith("--output") for w in rest):
        return False
    return not konumsal  # sort/uniq/head/tail/wc/cut/column: konumsal argüman = dosya adı


def _readonly_program(words: list[str]) -> bool:
    prog = words[0]
    if prog == "tree":
        return not any(w.startswith("-o") or w == "--output" for w in words[1:])  # -o DOSYA: dosyaya yazar
    if prog == "nvidia-smi":
        return all(w.startswith(_NVIDIA_OKUYAN) or w in ("dmon", "pmon", "topo") for w in words[1:])
    if prog in _READONLY_CMDS:
        return True
    if prog == "find":
        return not any(w.startswith(_FIND_YAZAN) for w in words)
    if prog == "ip":  # `ip addr` / `ip route show` okur; `ip link set`, `ip addr add` değiştirir
        return len(words) > 1 and words[1] in _READONLY_SUB["ip"] and (len(words) == 2 or words[2] in _IP_OKUYAN)
    if prog == "git" and len(words) > 1:
        if words[1] == "branch":  # `git branch -D x` siler, `git branch yeni` / `-m` yazar: yalnızca listeleme
            return all(w in ("-a", "-r", "-v", "-vv", "--all", "--remotes", "--list") for w in words[2:])
        if any(w.startswith("--output") for w in words):  # `git diff --output=DOSYA`
            return False
    subs = _READONLY_SUB.get(prog)
    return bool(subs and len(words) > 1 and any(words[1] == x or (x.startswith("-Q") and words[1].startswith("-Q"))
                                                 for x in subs))


def _politika_gecersiz(name: str, args: dict) -> bool:
    """K12-A5: politikanın "izin"i yine de hattı atlayamaz — güvenilmeyen kaynaktan program kurma (`apps.trusted`
    dışı https adresi / bilinmeyen GitHub deposu) `security.classify`'da yüksek risktir; kurulum politikası "otomatik"
    olsa da kullanıcıya / güvenlik ajanına gider."""
    if name == "install_app":
        from .apps import trusted

        return not trusted(str(args.get("source") or ""))
    return False


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
    # güvenlik politikası (cekirdek/guvenlik.py, MIMARI §10): yasak → ret; "otomatik" kurulum → izin; "sor" → hat
    # kendi kuralıyla sürer; ağ "sor" → riskli sayılır. Politika ikinci bir onay yolu değildir, karar yine burada.
    from .cekirdek import guvenlik

    tool = REGISTRY.get(name)
    soz, neden = guvenlik.karar(name, args, (tool.hints or {}).get("izinler", ()) if tool else ())
    if soz == "yasak":
        return Decision(DENY, neden)
    if soz == "izin" and not ctx.gate_actions and not _politika_gecersiz(name, args):
        return Decision(ALLOW, neden)
    action = is_action(name, args)
    if ctx.gate_actions and action:
        return Decision(PENDING)
    risky = (needs_approval(name, args) or soz == "sor") and not is_readonly(name, args)
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
