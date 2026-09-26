"""Araç fabrikası: asistanın elinde olmayan bir yeteneği, test edilmiş ve kullanıcının onayladığı bir araç olarak ekler.

Çekirdektir: asistan bu dosyayı değiştiremez; yalnızca bu dosyanın ürettiği araçları (kullanıcı onayıyla) ekler.

Akış (asistan `request_tool` çağırınca):
1. Hazır çözüm aranır: kategorilerdeki bilinen kütüphaneler (categories.py), kurulabilir Ollama modelleri, hazır MCP
   sunucuları. Uyan kütüphane varsa araç onun üzerine kurulur; model / MCP önerisi asistana söylenir.
2. Araç yazılır: model ad, açıklama, JSON şeması, `run(**args) -> str` fonksiyonu, test ve gereken paketleri
   üretir. Önce yönetici modeli (yerel öncelik), testleri geçemezse bağlıysa Claude (API ya da Claude Code).
3. Paket gerekiyorsa kullanıcıya sorulur ve fabrikanın AYRI paket klasörüne kurulur (programın ve ajanların
   kütüphanelerine dokunulmaz).
4. Sandbox: geçici klasörde, internet bağlantısı kesik (Linux: `unshare -rn`), zaman sınırlı test. Başarısızsa
   hata modele verilir, en çok MAX_ATTEMPTS kez düzelttirilir.
5. Testler geçerse kullanıcıya aracın kodu gösterilip sorulur; onaylanırsa `araclar/<ad>/` altına kaydedilir,
   bu klasör git ile sürümlenir ve araç kayda "calistirir" risk sınıfıyla girer (her çalıştırma denetlenir).
"""

import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

from .config import DATA_DIR
from .registry import REGISTRY, Tool, safe_name

FACTORY_DIR = DATA_DIR / "arac-fabrikasi"
TOOLS_DIR = FACTORY_DIR / "araclar"  # onaylanan araçlar (git deposu)
PACKAGES_DIR = FACTORY_DIR / "paketler"  # fabrika araçlarının kütüphaneleri (ayrı ortam)
SOURCE = "fabrika"
MAX_ATTEMPTS = 3  # ilk yazım + 2 düzeltme
TEST_TIMEOUT = 60
RUN_TIMEOUT = 180
NAME_PREFIX = "f_"  # fabrika araçları yerleşik araçlarla karışmasın, adları çakışmasın

GEN_SCHEMA = {
    "type": "object",
    "properties": {
        "name": {"type": "string"}, "description": {"type": "string"},
        "input_schema": {"type": "object"}, "packages": {"type": "array", "items": {"type": "string"}},
        "code": {"type": "string"}, "test": {"type": "string"},
    },
    "required": ["name", "description", "input_schema", "packages", "code", "test"],
}

GEN_SYSTEM = (
    "You write small, reliable Python tools for a desktop AI assistant. Answer with a single JSON object only.")

RULES = (
    "Rules for the tool:\n"
    "- `code` is a complete Python module defining `def run(**kwargs) -> str` (keyword arguments exactly as in "
    "input_schema). It returns a short plain-text result for the assistant (or a file path it created). It must "
    "not ask for input, must not print progress, and must raise an Exception with a clear message on bad input.\n"
    "- Work only inside the current working directory (the user's workspace) for files; never delete or overwrite "
    "files it did not create; never use sudo, never change system settings, never read ~/.ssh or credentials.\n"
    "- Use the standard library, these preinstalled libraries (pandas, numpy, matplotlib, openpyxl, python-docx, "
    "python-pptx, pypdf, reportlab, pillow, requests, pyyaml) and at most a few extra pip packages listed in "
    "`packages` (plain pip names). Prefer no extra packages.\n"
    "- `input_schema` is a JSON Schema object: {\"type\": \"object\", \"properties\": {...}, \"required\": [...]} with a "
    "description for every property.\n"
    "- `name`: short snake_case English name of the capability (e.g. `docx_to_pdf`).\n"
    "- `description`: one or two sentences saying when to use it (English, for the assistant).\n"
    "- `test` is a Python script that imports the tool with `import arac` and checks `arac.run(...)` with asserts. "
    "It runs WITHOUT internet in an empty temporary folder: create any input files it needs itself, and if the "
    "tool needs the internet, test only the offline parts (argument checks, parsing of a sample response).\n")

# hazır MCP sunucuları (öneri olarak; kurulum kullanıcıya bırakılır — Node/uv gerektirir)
MCP_CATALOG = {
    ("veritabanı", "database", "sqlite", "sql"): "SQLite MCP sunucusu (mcp-server-sqlite, uvx ile)",
    ("git", "commit", "depo", "repository"): "Git MCP sunucusu (mcp-server-git, uvx ile)",
    ("github", "pull request", "issue"): "GitHub MCP sunucusu (github/github-mcp-server)",
    ("tarayıcı", "browser", "tıkla", "web sayfasında", "form doldur"): "Playwright MCP sunucusu (@playwright/mcp, npx ile)",
    ("saat dilimi", "timezone", "time zone"): "Time MCP sunucusu (mcp-server-time, uvx ile)",
}


class FactoryError(Exception):
    pass


# ---------------------------------------------------------------- hazır çözüm

def find_ready(need: str) -> dict:
    """{"packages": [(paket, not)], "models": [(model, not)], "mcp": [öneri]} — ihtiyaca uyan hazır çözümler."""
    from . import categories

    text = need.casefold()
    words = set(re.findall(r"\w{4,}", text))
    packages = []
    for cat in categories.CATEGORIES:
        for e in cat.extras:
            note = e.note.casefold()
            if e.package.split("-")[0] in text or len(words & set(re.findall(r"\w{4,}", note))) >= 2:
                packages.append((e.package, e.note))
    models = []
    if re.search(r"\bocr\b|taranmış|belge oku|yazıyı oku", text):
        models.append(("glm-ocr:latest", "taranmış belge ve resimdeki yazıyı okuma"))
    if re.search(r"resim|görsel|fotoğraf|image|photo", text) and re.search(r"gör|anla|tanı|analiz|describe", text):
        models.append(("gemma4:12b", "resim görme (look_at_image aracı bunu kullanır)"))
    mcp = [label for keys, label in MCP_CATALOG.items() if any(k in text for k in keys)]
    return {"packages": packages, "models": models, "mcp": mcp}


# ---------------------------------------------------------------- araç yazma

def _generate(settings, connections, provider: str, model: str, need: str, example: str, ready: dict,
              feedback: str = "", previous: dict | None = None) -> dict:
    from . import specialists
    from .manager import parse_json

    lines = [f"Missing capability the assistant needs:\n{need}"]
    if example:
        lines.append(f"Example of how it will be used:\n{example}")
    if ready["packages"]:
        lines.append("Known libraries that fit (prefer them): " +
                     ", ".join(f"{p} ({n})" for p, n in ready["packages"]))
    taken = ", ".join(sorted(REGISTRY.tools))
    lines.append(f"Existing tool names (do not reuse): {taken}")
    lines.append(RULES)
    if previous:
        lines.append("Your previous attempt:\n```json\n" + json.dumps(previous, ensure_ascii=False)[:6000] + "\n```")
    if feedback:
        lines.append(f"It failed. Fix exactly this and return the whole corrected JSON:\n{feedback[-2500:]}")
    lines.append('Respond as JSON: {"name": "...", "description": "...", "input_schema": {...}, "packages": [...], '
                 '"code": "...", "test": "..."}')
    answer = specialists.ask(settings, connections, provider, model, "\n\n".join(lines), system=GEN_SYSTEM,
                             schema=GEN_SCHEMA if provider == "ollama" else None)
    data = parse_json(answer)
    if not data:
        raise FactoryError("model geçerli bir araç tanımı döndürmedi")
    return data


def validate(data: dict) -> dict:
    """Modelin ürettiği tanımı güvenli biçime getirir; sorun varsa FactoryError (metni modele geri verilir)."""
    name = safe_name(str(data.get("name") or "")).lower()
    if not name or name == "arac":
        raise FactoryError("name is missing")
    if not name.startswith(NAME_PREFIX):
        name = NAME_PREFIX + name
    name = name[:48]
    if REGISTRY.get(name) is not None and REGISTRY.get(name).source != SOURCE:
        raise FactoryError(f"the name {name} is already used by a built-in tool; choose another name")
    schema = data.get("input_schema")
    if not isinstance(schema, dict) or schema.get("type") != "object" or not isinstance(schema.get("properties"), dict):
        raise FactoryError("input_schema must be {\"type\": \"object\", \"properties\": {...}}")
    code, test = str(data.get("code") or ""), str(data.get("test") or "")
    if "def run(" not in code:
        raise FactoryError("code must define def run(**kwargs) -> str")
    if "arac" not in test or "assert" not in test:
        raise FactoryError("test must `import arac` and check arac.run(...) with assert")
    try:
        compile(code, "arac.py", "exec")
        compile(test, "test_arac.py", "exec")
    except SyntaxError as e:
        raise FactoryError(f"syntax error: {e}") from e
    if re.search(r"\bsudo\b|rm\s+-rf\s+[/~]|shutil\.rmtree\(\s*['\"]?[/~]|\.ssh\b|/etc/shadow", code):
        raise FactoryError("the code does something forbidden (sudo, deleting outside the workspace, credentials)")
    packages = [p for p in (data.get("packages") or []) if isinstance(p, str) and p.strip()]
    if any(not re.fullmatch(r"[A-Za-z0-9._\-\[\]=<>!~]+", p) for p in packages):
        raise FactoryError("packages must be plain pip names")
    return {"name": name, "description": str(data.get("description") or name)[:600], "input_schema": schema,
            "packages": packages[:5], "code": code, "test": test}


# ---------------------------------------------------------------- sandbox

def _env(extra: Path | None = None) -> dict:
    from .tools import BUNDLED_LIBS, USER_LIBS

    paths = [str(p) for p in (extra, PACKAGES_DIR, BUNDLED_LIBS, USER_LIBS) if p]
    env = {k: v for k, v in os.environ.items() if k in ("PATH", "LANG", "LC_ALL", "SYSTEMROOT", "TEMP", "TMP")}
    env.update(PYTHONPATH=os.pathsep.join(paths), PYTHONNOUSERSITE="1", PYTHONIOENCODING="utf-8",
               MPLBACKEND="Agg")
    return env


def _offline_prefix() -> list[str]:
    """Linux'ta ağı kesik bir ad alanında çalıştırır (unshare -rn); desteklenmiyorsa boş (yine zaman sınırlı)."""
    if sys.platform != "linux" or not shutil.which("unshare"):
        return []
    try:
        ok = subprocess.run(["unshare", "-rn", "true"], capture_output=True, timeout=5).returncode == 0
    except Exception:
        ok = False
    return ["unshare", "-rn"] if ok else []


def install_packages(packages: list[str]) -> str:
    from .tools import python_exe

    PACKAGES_DIR.mkdir(parents=True, exist_ok=True)
    out = subprocess.run([python_exe(), "-m", "pip", "install", "--disable-pip-version-check", "--target",
                          str(PACKAGES_DIR), "--upgrade", *packages], capture_output=True, text=True, timeout=900)
    if out.returncode != 0:
        lines = [ln for ln in (out.stderr or out.stdout).splitlines() if ln.strip()]
        raise FactoryError("paket kurulamadı: " + " | ".join(lines[-4:]))
    return ", ".join(packages)


def sandbox_test(tool: dict) -> tuple[bool, str]:
    """(geçti mi, çıktı). Geçici klasörde, internetsiz, zaman sınırlı."""
    from .tools import python_exe

    with tempfile.TemporaryDirectory(prefix="arac-sinav-") as tmp:
        d = Path(tmp)
        (d / "arac.py").write_text(tool["code"], encoding="utf-8")
        (d / "test_arac.py").write_text(tool["test"], encoding="utf-8")
        env = {**_env(d), "HOME": tmp}
        try:
            out = subprocess.run(_offline_prefix() + [python_exe(), "test_arac.py"], cwd=tmp, env=env,
                                 capture_output=True, text=True, timeout=TEST_TIMEOUT)
        except subprocess.TimeoutExpired:
            return False, f"test {TEST_TIMEOUT} saniyede bitmedi (sonsuz döngü ya da internet bekliyor olabilir)"
        text = (out.stdout + "\n" + out.stderr).strip()
        return out.returncode == 0, text[-3000:]


# ---------------------------------------------------------------- kayıt ve çalıştırma

_RUNNER = (
    "import json, sys\n"
    "sys.path.insert(0, sys.argv[1])\n"
    "import arac\n"
    "args = json.loads(sys.stdin.read() or '{}')\n"
    "result = arac.run(**args)\n"
    "sys.stdout.write(str(result))\n"
)


def _runner(tool_dir: Path, workspace_fn):
    def run(args: dict) -> str:
        from .tools import python_exe

        cwd = Path(workspace_fn()).expanduser()
        cwd.mkdir(parents=True, exist_ok=True)
        try:
            out = subprocess.run([python_exe(), "-c", _RUNNER, str(tool_dir)], input=json.dumps(args), cwd=cwd,
                                 env=_env(tool_dir), capture_output=True, text=True, timeout=RUN_TIMEOUT)
        except subprocess.TimeoutExpired:
            return f"Error: the tool did not finish in {RUN_TIMEOUT} s"
        if out.returncode != 0:
            last = [ln for ln in out.stderr.splitlines() if ln.strip()][-3:]
            return "Error: " + " | ".join(last)
        return out.stdout.strip() or "(done, no output)"
    return run


_workspace = {"path": str(Path.home())}


def set_workspace(path: str) -> None:
    """Fabrika araçları çalışma klasöründe çalışır (Toolbox her ajanda bunu günceller)."""
    _workspace["path"] = path


def register(tool_dir: Path) -> str | None:
    try:
        meta = json.loads((tool_dir / "arac.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    if meta.get("disabled"):
        return None
    name = meta["name"]
    REGISTRY.put(Tool(
        name=name, description=f"[Araç fabrikası] {meta['description']}", schema=meta["input_schema"],
        risk="calistirir", label=(name.removeprefix(NAME_PREFIX).replace("_", " "), "bitti"), source=SOURCE,
        group="fabrika", runner=_runner(tool_dir, lambda: _workspace["path"])))
    return name


def load_all() -> list[str]:
    """Onaylanmış bütün fabrika araçlarını kayda ekler (program açılırken)."""
    REGISTRY.remove_source(SOURCE)
    if not TOOLS_DIR.is_dir():
        return []
    return [n for d in sorted(TOOLS_DIR.iterdir()) if d.is_dir() and (n := register(d))]


def tools() -> list[dict]:
    """Kayıtlı fabrika araçları (pencere için): arac.json + kod."""
    out = []
    if TOOLS_DIR.is_dir():
        for d in sorted(TOOLS_DIR.iterdir()):
            try:
                meta = json.loads((d / "arac.json").read_text(encoding="utf-8"))
                meta["code"] = (d / "arac.py").read_text(encoding="utf-8")
                meta["dir"] = str(d)
                out.append(meta)
            except (OSError, ValueError):
                continue
    return out


def _git(*args: str) -> None:
    """Araç klasörü git ile sürümlenir (asistanın yaptığı her ekleme/silme geri alınabilsin)."""
    if not shutil.which("git"):
        return
    TOOLS_DIR.mkdir(parents=True, exist_ok=True)
    env = {**os.environ, "GIT_AUTHOR_NAME": "YENİ NESİL CAFER", "GIT_AUTHOR_EMAIL": "asistan@localhost",
           "GIT_COMMITTER_NAME": "YENİ NESİL CAFER", "GIT_COMMITTER_EMAIL": "asistan@localhost"}
    if not (TOOLS_DIR / ".git").exists():
        subprocess.run(["git", "init", "-q"], cwd=TOOLS_DIR, env=env, capture_output=True)
    subprocess.run(["git", "add", "-A"], cwd=TOOLS_DIR, env=env, capture_output=True)
    subprocess.run(["git", "commit", "-q", "-m", *args], cwd=TOOLS_DIR, env=env, capture_output=True)


def save(tool: dict, need: str, model: str) -> Path:
    d = TOOLS_DIR / tool["name"]
    d.mkdir(parents=True, exist_ok=True)
    (d / "arac.py").write_text(tool["code"], encoding="utf-8")
    (d / "test_arac.py").write_text(tool["test"], encoding="utf-8")
    meta = {k: tool[k] for k in ("name", "description", "input_schema", "packages")}
    meta.update(need=need, model=model, created=time.time())
    (d / "arac.json").write_text(json.dumps(meta, ensure_ascii=False, indent=1), encoding="utf-8")
    _git(f"Araç eklendi: {tool['name']} — {need[:80]}")
    return d


def remove(name: str) -> None:
    d = TOOLS_DIR / name
    if d.is_dir() and d.parent == TOOLS_DIR:
        shutil.rmtree(d)
        _git(f"Araç silindi: {name}")
    REGISTRY.tools.pop(name, None)


# ---------------------------------------------------------------- ana akış

def _writers(settings, chat: tuple[str, str]) -> list[tuple[str, str]]:
    """Aracı yazacak modeller, sırayla: bulut önceliğinde bulut önce; yoksa yönetici modeli, sonra bağlı Claude."""
    from . import roster, specialists

    local = roster.manager_for(settings, chat) if chat[0] else chat
    cloud = []
    if specialists._claude_available():
        cloud.append(("claude", settings.claude_model))
    elif specialists.claude_code_available():
        cloud.append((specialists.CLAUDE_CODE[0], settings.extra.get("cli_model") or specialists.CLAUDE_CODE[1]))
    order = (cloud + [local]) if settings.model_policy == "guclu" else ([local] + cloud)
    return [m for m in dict.fromkeys(order) if m and m[1]]


def build(need: str, example: str, settings, connections, chat: tuple[str, str], ask_approval,
          progress=lambda text: None, cancelled=lambda: False) -> str:
    """request_tool: hazır çözüm → yaz → (paket onayı) → sandbox testi → kullanıcı onayı → kayıt.
    Asistana gidecek sonuç metnini döndürür."""
    need = " ".join(str(need or "").split())[:800]
    if len(need) < 8:
        return "Describe the missing capability in a sentence (what input, what output)."
    ready = find_ready(need)
    notes = []
    if ready["models"]:
        notes.append("A model fits this: " + "; ".join(f"{m} ({n})" for m, n in ready["models"]) +
                     ". If it is not installed, tell the user it can be downloaded in Yardım → Ajan kategorileri.")
    if ready["mcp"]:
        notes.append("A ready MCP server exists: " + "; ".join(ready["mcp"]) +
                     ". The user can add it in Ayarlar → MCP (mcp.json).")
    progress("araç fabrikası: " + ("hazır kütüphane bulundu, araç onun üzerine yazılıyor"
                                   if ready["packages"] else "hazır çözüm yok, araç yazılıyor"))
    installed: set[str] = set()
    last_error, data, tool = "", None, None
    for provider, model in _writers(settings, chat):
        for attempt in range(MAX_ATTEMPTS):
            if cancelled():
                raise InterruptedError("durduruldu")
            reason = next((ln.strip() for ln in reversed(last_error.splitlines()) if ln.strip()), "")[:120]
            progress(f"araç fabrikası: {model} aracı " + (f"yazıyor (deneme 1/{MAX_ATTEMPTS})" if attempt == 0 else
                     f"düzeltiyor (deneme {attempt + 1}/{MAX_ATTEMPTS}; sorun: {reason})"))
            try:
                data = _generate(settings, connections, provider, model, need, example, ready, last_error, data)
                tool = validate(data)
            except FactoryError as e:
                last_error, tool = str(e), None
                continue
            except Exception as e:  # model / bağlantı hatası: sıradaki yazara geç
                last_error, tool = f"{type(e).__name__}: {e}", None
                break
            todo = [p for p in tool["packages"] if p not in installed]
            if todo:
                if not ask_approval("install_python_package", {
                        "packages": " ".join(todo),
                        "purpose": f"Araç fabrikası “{tool['name']}” aracını test etmek için bu kütüphaneleri "
                                   "programdan ayrı bir klasöre (sandbox) kuracak."}):
                    return "The user declined installing the packages the new tool needs. " + " ".join(notes)
                progress("araç fabrikası: kütüphaneler kuruluyor " + ", ".join(todo))
                try:
                    install_packages(todo)
                    installed.update(todo)
                except FactoryError as e:
                    last_error = str(e) + " — use other packages or none"
                    continue
            progress(f"araç fabrikası: “{tool['name']}” sandbox'ta test ediliyor (internetsiz)")
            ok, output = sandbox_test(tool)
            if ok:
                break
            last_error, tool = f"The test failed:\n{output}", None
        if tool is not None:
            break
    if tool is None:
        return ("The tool factory could not build a working tool: " + last_error[-600:] + "\n" + " ".join(notes) +
                "\nTell the user plainly what is missing and continue with what is possible.")
    approved = ask_approval("add_tool", {
        "name": tool["name"], "description": tool["description"], "packages": " ".join(tool["packages"]),
        "code": tool["code"],
        "purpose": f"Asistanın bu yeteneği yoktu: “{need}”. Araç fabrikası yeni bir araç yazdı ve sandbox'ta "
                   f"(internetsiz) testleri geçti ({model}). Onaylarsan araç kalıcı olarak eklenir; her "
                   "çalıştırılışı yine güvenlik ajanı ya da sen denetlersin."})
    if not approved:
        return "The user did not approve adding the new tool. Continue without it. " + " ".join(notes)
    d = save(tool, need, model)
    register(d)
    return (f"NEW TOOL READY: {tool['name']} — {tool['description']}\nInput schema: "
            f"{json.dumps(tool['input_schema'], ensure_ascii=False)}\nCall it now to continue the job. "
            + " ".join(notes))
