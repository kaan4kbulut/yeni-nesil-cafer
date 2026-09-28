"""Agent'ın kullanabildiği araçlar: tanımlar (JSON şeması) ve çalıştırıcılar."""

import json
import re
import subprocess
import sys
from pathlib import Path

import httpx
from bs4 import BeautifulSoup

from .registry import APPROVAL_RISKS, REGISTRY

MAX_OUTPUT = 20_000  # modele geri gönderilen çıktı için karakter sınırı
COMMAND_TIMEOUT = 120

# Ajanın Python kodu programın gömülü Python'unda çalışır ama kütüphaneleri ayrı durur (programınkiler bozulmasın):
# pakete gömülü hazır set (ajan-kutuphaneleri) ve sonradan kurulanlar (veri klasöründe, yeniden kurulumda kalır).
from .config import DATA_DIR  # noqa: E402

from .cekirdek.araclar import dosya as a_dosya, komut as a_komut, web as a_web  # noqa: E402
from .cekirdek.araclar.temel import GIZLI_DOSYALAR, PENCERESIZ, AracHatasi  # noqa: E402

BUNDLED_LIBS = Path(__file__).resolve().parent.parent / "ajan-kutuphaneleri"
PROGRAM_DIR = Path(__file__).resolve().parent.parent  # programın kurulu olduğu klasör (kodu burada)
SECRET_FILES = GIZLI_DOSYALAR  # API anahtarları: asistan bunları okuyamaz (cekirdek/araclar/temel.py)
USER_LIBS = DATA_DIR / "python-kutuphaneleri"
DECOR_SCRIPT = Path(__file__).resolve().parent / "decor3d.py"  # süs modelleri: ajan Python'unda ayrı süreçte
AGENT_LIBRARIES = ("pandas, numpy, matplotlib (save charts to files), openpyxl (Excel), python-docx (Word), "
                   "python-pptx (PowerPoint), pypdf (PDF read), reportlab (PDF create), Pillow (images), "
                   "requests, httpx, beautifulsoup4, PyYAML, faster-whisper (speech to text), build123d (CAD: exact-size "
                   "3D parts, export STL/3MF/STEP), trimesh (3D meshes)")
NO_WINDOW = PENCERESIZ  # Windows: konsol penceresi açılmasın


def program_roots(extra: str = "") -> list[Path]:
    """Asistanın okuyabildiği program klasörleri: kod, ayarlar, veriler (+ ayarlarda verilmişse kaynak klasörü)."""
    from . import results
    from .config import CONFIG_DIR

    # programın masaüstündeki kendi klasörü (YENİ NESİL CAFER: Sonuçlar, Örnekler…): kullanıcı "bu dosyalara bak"
    # diyor, okuyamayınca iş 25 dk "yol çalışma klasörünün dışında" hatasıyla döndü (2026-09-27)
    roots = [PROGRAM_DIR, CONFIG_DIR, DATA_DIR, results.project_dir()] + ([Path(extra).expanduser()] if extra else [])
    return [r.resolve() for r in roots]


def _askpass_launcher() -> str:
    """SUDO_ASKPASS çalıştırılabilir bir dosya ister: programın Python'uyla askpass.py'yi açan küçük betik."""
    import stat

    script = DATA_DIR / "askpass.sh"
    body = f'#!/bin/sh\nexec "{python_exe()}" "{Path(__file__).resolve().parent / "askpass.py"}" "$@"\n'
    if not script.exists() or script.read_text(encoding="utf-8") != body:
        script.parent.mkdir(parents=True, exist_ok=True)
        script.write_text(body, encoding="utf-8")
        script.chmod(script.stat().st_mode | stat.S_IXUSR)
    return str(script)


def python_exe() -> str:
    """Ajan kodu için konsol Python'u (Windows'ta program pythonw.exe ile açılır; onun çıktısı güvenilmez)."""
    exe = Path(sys.executable)
    if exe.name.lower() == "pythonw.exe" and (exe.parent / "python.exe").exists():
        return str(exe.parent / "python.exe")
    return str(exe)


def agent_env() -> dict:
    import os

    paths = [str(p) for p in (USER_LIBS, BUNDLED_LIBS) if p.is_dir()]
    if os.environ.get("PYTHONPATH"):
        paths.append(os.environ["PYTHONPATH"])
    return {**os.environ, "PYTHONPATH": os.pathsep.join(paths), "PYTHONIOENCODING": "utf-8", "PYTHONUTF8": "1", "MPLBACKEND": "Agg"}

TOOL_SPECS = [
    {
        "name": "list_files",
        "description": "List files and folders in a directory inside the workspace. Paths are relative to the workspace root.",
        "input_schema": {
            "type": "object",
            "properties": {"path": {"type": "string", "description": "Directory path, default '.'"}},
            "required": [],
        },
    },
    {
        "name": "read_file",
        "description": "Read a UTF-8 text file inside the workspace. Returns numbered lines.",
        "input_schema": {
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "File path relative to the workspace"},
                "start_line": {"type": "integer", "description": "1-based line to start from (optional)"},
                "max_lines": {"type": "integer", "description": "Maximum number of lines to return (optional)"},
            },
            "required": ["path"],
        },
    },
    {
        "name": "search_files",
        "description": "Search text inside files in the workspace (like grep) and return matching lines with file "
                       "name and line number. Read-only, no approval needed. Use it for large files and logs instead "
                       "of reading everything, and to find where something is mentioned.",
        "input_schema": {
            "type": "object",
            "properties": {
                "pattern": {"type": "string", "description": "Text to find (case-insensitive), or a regular expression"},
                "path": {"type": "string", "description": "File or folder to search, default: the whole workspace"},
                "max_results": {"type": "integer", "description": "Default 200"},
            },
            "required": ["pattern"],
        },
    },
    {
        "name": "write_file",
        "description": "Create or overwrite a text file inside the workspace. Parent folders are created automatically.",
        "input_schema": {
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "File path relative to the workspace"},
                "content": {"type": "string", "description": "Full file content"},
            },
            "required": ["path", "content"],
        },
    },
    {
        "name": "edit_file",
        "description": "Replace an exact, unique snippet of text in an existing file inside the workspace.",
        "input_schema": {
            "type": "object",
            "properties": {
                "path": {"type": "string"},
                "old_text": {"type": "string", "description": "Exact text to replace; must occur exactly once"},
                "new_text": {"type": "string", "description": "Replacement text"},
            },
            "required": ["path", "old_text", "new_text"],
        },
    },
    {
        "name": "run_command",
        "description": "Run a shell command (bash) in the workspace directory and return stdout/stderr. The user must approve each command, so always explain it in `purpose`.",
        "input_schema": {
            "type": "object",
            "properties": {"command": {"type": "string"}, "purpose": {"type": "string", "description": "For the user's approval dialog: one or two plain sentences in the user's language (usually Turkish) saying what this does and why it is needed. Example: 'Klasördeki .txt dosyalarını sayıp toplam boyutlarını hesaplıyorum; hangi dosyaların yer kapladığını görmek için.'"}},
            "required": ["command", "purpose"],
        },
    },
    {
        "name": "run_python",
        "description": "Run a Python 3 script in the workspace directory and return its output. Use print() to show results. The user must approve each run, so always explain it in `purpose`. Already available, no install needed: " + AGENT_LIBRARIES + ".",
        "input_schema": {
            "type": "object",
            "properties": {"code": {"type": "string"}, "purpose": {"type": "string", "description": "For the user's approval dialog: one or two plain sentences in the user's language (usually Turkish) saying what this does and why it is needed. Example: 'Klasördeki .txt dosyalarını sayıp toplam boyutlarını hesaplıyorum; hangi dosyaların yer kapladığını görmek için.'"}},
            "required": ["code", "purpose"],
        },
    },
    {
        "name": "web_search",
        "description": "Search the web (DuckDuckGo). Returns titles, URLs and snippets.",
        "input_schema": {
            "type": "object",
            "properties": {
                "query": {"type": "string"},
                "max_results": {"type": "integer", "description": "1-10, default 5"},
            },
            "required": ["query"],
        },
    },
    {
        "name": "fetch_url",
        "description": "Download a web page and return its readable text content.",
        "input_schema": {
            "type": "object",
            "properties": {"url": {"type": "string"}},
            "required": ["url"],
        },
    },
]
# temel araçların risk sınıfı ve sohbetteki adı (ajan profilleri bu araçlardan seçer)
_BASE_TOOLS = {
    "list_files": ("okur", ("klasörü listele", "listelendi")),
    "read_file": ("okur", ("dosya oku", "okundu")),
    "search_files": ("okur", ("dosyalarda ara", "arandı")),
    "write_file": ("yazar", ("dosya yaz", "yazıldı")),
    "edit_file": ("yazar", ("dosya düzenle", "düzenlendi")),
    "run_command": ("calistirir", ("komut", "çalıştırıldı")),
    "run_python": ("calistirir", ("python", "çalıştırıldı")),
    "web_search": ("okur", ("web'de ara", "arandı")),
    "fetch_url": ("okur", ("sayfa oku", "okundu")),
}
for _spec in TOOL_SPECS:
    REGISTRY.add(_spec, *_BASE_TOOLS[_spec["name"]], group="temel")

# Kullanıcının eklediği araç API'lerini çağırır; açıklamaya API listesi ajan tarafından eklenir
CALL_API_SPEC = REGISTRY.add({
    "name": "call_api",
    "description": "Call one of the user's configured HTTP APIs. The API key is added automatically.",
    "input_schema": {
        "type": "object",
        "properties": {
            "api": {"type": "string", "description": "API name from the list below"},
            "method": {"type": "string", "description": "HTTP method: GET, POST, PUT, PATCH or DELETE (default GET)"},
            "path": {"type": "string", "description": "Path appended to the API base URL, e.g. /weather"},
            "query": {"type": "object", "description": "Query string parameters (optional)"},
            "body": {"type": "object", "description": "JSON body for POST/PUT/PATCH (optional)"},
            "purpose": {"type": "string", "description": "Needed for anything but GET; one or two plain sentences in the user's language (usually Turkish) saying what this does and why it is needed. Example: 'Klasördeki .txt dosyalarını sayıp toplam boyutlarını hesaplıyorum; hangi dosyaların yer kapladığını görmek için.'"},
        },
        "required": ["api"],
    },
}, "okur", ("api çağır", "çağrıldı"), group="ozel")

# Görevlerin ihtiyaç duyduğu ek Python kütüphaneleri: ajanın kütüphane klasörüne kurulur (run_python hemen kullanır)
PIP_SPEC = REGISTRY.add({
    "name": "install_python_package",
    "description": (
        "Install extra Python packages (needs internet) so run_python can import them (e.g. python-telegram-bot). "
        "These are already available and need no install: " + AGENT_LIBRARIES + ". Use this instead of 'pip "
        "install' in run_command: the system Python is often externally managed and refuses. Already installed "
        "packages are skipped."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "packages": {"type": "string", "description": "Space-separated pip package names, e.g. 'pandas openpyxl'"},
            "purpose": {"type": "string", "description": "One plain sentence in the user's language: why it is needed"},
        },
        "required": ["packages"],
    },
}, "kurar", ("kütüphane kur", "kuruldu"), group="ozel")

# 3D baskı: modelin yazıcıya uygun olup olmadığı (kapalı yüzey, tek parça, ölçüler, tabla) — salt okur
CHECK_3D_SPEC = REGISTRY.add({
    "name": "check_3d_model",
    "description": (
        "Check a 3D model file (STL, 3MF, OBJ, PLY, GLB) before 3D printing: is it watertight (closed, printable), "
        "how many separate bodies, its real size in millimetres, volume, and whether it fits the printer bed. Call it "
        "after exporting a model and fix every reported problem before telling the user it is ready."),
    "input_schema": {
        "type": "object",
        "properties": {
            "path": {"type": "string", "description": "Model file in the workspace, e.g. 3D/tutucu.stl"},
            "bed": {"type": "string", "description": "Printer build volume in mm as WxDxH (default 220x220x250)"},
        },
        "required": ["path"],
    },
}, "okur", ("3D modeli denetle", "denetlendi"))

# model dosyasını trimesh ile ajanların Python'unda denetleyen küçük program (programın kendi süreci yüklemez)
_CHECK_3D = r"""
import json, sys
import trimesh
path, bed = sys.argv[1], [float(x) for x in sys.argv[2].lower().split("x")]
mesh = trimesh.load(path, force="mesh")
size = [round(float(v), 2) for v in mesh.extents]
bodies = int(mesh.body_count)  # bağlı parça sayısı (scipy; split() networkx ister)
problems = []
if not mesh.is_watertight:
    problems.append("NOT watertight: the surface has holes or open edges; slicers may fail or print it wrong")
if not mesh.is_winding_consistent:
    problems.append("inconsistent face winding (flipped normals)")
if bodies > 1:
    problems.append(f"{bodies} separate bodies: check that parts that should touch are really joined")
if max(size) < 2:
    problems.append("very small (under 2 mm): the model was probably built in metres or centimetres, not mm")
fits = all(s <= b for s, b in zip(sorted(size), sorted(bed)))
if not fits:
    problems.append(f"does not fit the {sys.argv[2]} mm printer bed in any orientation")
print(json.dumps({"size_mm": size, "volume_cm3": round(float(mesh.volume) / 1000, 2) if mesh.is_watertight else None,
                  "triangles": len(mesh.faces), "bodies": bodies, "watertight": bool(mesh.is_watertight),
                  "fits_bed": fits, "problems": problems}))
"""

# 3D süs modeli (decor3d.py): vazo, lamba, süs, kabartma, litofan, siluet — geometri test edilmiş koddan gelir,
# model yalnızca şekli ve ölçüleri seçer. Yalnızca 3D / süs konuşulan sohbette ajana verilir (agent.run).
DECOR_SPEC = REGISTRY.add({
    "name": "make_decor_model",
    "description": (
        "Create a decorative 3D-printable model from tested geometry, without writing code. Use it for vases, lamps, "
        "lampshades, ornaments, figurines and decorations instead of build123d; use exact-size CAD (use_skill "
        "3d-baski) only for functional parts. Shapes: vazo (vase), abajur (lampshade with LED hole), girdap_lamba "
        "(sphere lamp of spiral petals, LED hole), sus_topu (ornament ball with hanging loop), burgulu_kule (twisted "
        "polygon tower), yildiz (star ornament), kafes_kure (lattice sphere), kabartma (relief plaque from an image), "
        "litofan (lithophane panel from an image; the picture shows when lit from behind), litofan_lamba (image "
        "wrapped around a cylinder lampshade), siluet (standing figure from a silhouette image; for an animal, person "
        "or character first make the image with generate_image, prompt like 'solid black silhouette of a sitting "
        "cat, side view, plain white background, simple shape'; if no image can be made, ask the user to attach a "
        "picture — never write geometry code for a figure). Saves 3D/<name>.stl and .3mf, watertight, scaled down if "
        "it does not fit the bed. To change the look, call again with other profile/pattern/sides/twist."),
    "input_schema": {
        "type": "object",
        "properties": {
            "shape": {"type": "string", "enum": ["vazo", "abajur", "girdap_lamba", "sus_topu", "burgulu_kule", "yildiz",
                                                 "kafes_kure", "kabartma", "litofan", "litofan_lamba", "siluet"]},
            "name": {"type": "string", "description": "File name without extension, e.g. mavi_vazo"},
            "height": {"type": "number", "description": "Height in mm (optional; good defaults per shape)"},
            "width": {"type": "number", "description": "Largest diameter or width in mm (optional)"},
            "profile": {"type": "string", "enum": ["klasik", "lale", "silindir", "koni", "kum_saati", "top", "sise"],
                        "description": "Side curve of vazo/abajur: classic, tulip, cylinder, cone, hourglass, globe, bottle"},
            "pattern": {"type": "string", "enum": ["yuvarlak", "yivli", "yildiz", "cokgen"],
                        "description": "Cross-section of vazo/abajur: round, fluted, star, polygon"},
            "sides": {"type": "integer", "description": "Number of flutes, star points, polygon corners or petals"},
            "twist": {"type": "number", "description": "Twist in degrees from bottom to top, e.g. 90 (0 = straight)"},
            "wall": {"type": "number", "description": "Wall thickness in mm (default 2, lamps 1.6); 0 = solid body "
                     "for the slicer's vase mode"},
            "hole": {"type": "number", "description": "LED / cable hole in the bottom in mm (lamps 40 by default; 0 = none)"},
            "thickness": {"type": "number", "description": "siluet: figure thickness; kabartma: relief depth; "
                          "litofan: maximum thickness; kafes_kure: strut size (mm)"},
            "image": {"type": "string", "description": "Image file in the workspace (kabartma, litofan, litofan_lamba, siluet)"},
            "invert": {"type": "boolean", "description": "Swap light and dark (kabartma: dark parts raised; siluet: "
                       "light figure on a dark background)"},
            "bed": {"type": "string", "description": "Printer build volume WxDxH in mm from memory, e.g. 260x260x260"},
        },
        "required": ["shape"],
    },
}, "yazar", ("süs modeli yap", "model hazır"), group="ozel")

# Resimden gerçek 3D figür (figure3d.py, TripoSR): yalnızca motor kuruluysa ve 3D / süs sohbetinde (agent._offer_decor)
FIGURE_SPEC = REGISTRY.add({
    "name": "make_3d_figure",
    "description": (
        "Turn ONE picture of a single object (animal, character, figurine, toy, bust) into a real 3D printable "
        "figure with the local 3D model (TripoSR). The picture must show one whole object in front of a plain "
        "background: make it first with generate_image, prompt like 'a cute cat figurine sitting, full body, "
        "centered, three-quarter front view, isolated on a plain uniform mid-gray background, no floor, no shadow, "
        "soft studio light, 3D render' and negative 'floor, ground, shadow, gradient background, text' (a background "
        "colour different from the object; or use the user's photo). If it says the figure could not be separated, "
        "make the picture again as told. The back side is guessed from one view and thin parts get simplified. Saves "
        "3D/<name>.stl and .3mf with a flat base, watertight, fitting the bed. Takes from 10 seconds to 3 minutes."),
    "input_schema": {
        "type": "object",
        "properties": {
            "image": {"type": "string", "description": "Picture in the workspace, e.g. Resimler/resim-….png"},
            "name": {"type": "string", "description": "File name without extension, e.g. kedi_figuru"},
            "height": {"type": "number", "description": "Figure height in mm (default 100)"},
            "base": {"type": "boolean", "description": "Add a 3 mm base plate so it stands well (default true)"},
            "bed": {"type": "string", "description": "Printer build volume WxDxH in mm from memory, e.g. 260x260x260"},
        },
        "required": ["image"],
    },
}, "yazar", ("3D figür yap", "figür hazır"), group="ozel")

# Kurulum / kaldırma öncesi: sistemde zaten var mı? (salt okunur, onay gerekmez)
CHECK_SPEC = REGISTRY.add({
    "name": "check_installed",
    "description": (
        "Check whether a program, package, app, Python package or Ollama model is already on this computer: "
        "executables on PATH, the system package manager (pacman/apt/dnf/rpm, winget on Windows), Flatpak, Snap, "
        "pip, desktop apps and Ollama models. Read-only. ALWAYS call this first when the user asks to install, "
        "uninstall, set up or start something, so you don't redo what exists or remove what isn't there. Use the "
        "plain product name (e.g. 'telegram', 'whatsapp'), not a library name."
    ),
    "input_schema": {
        "type": "object",
        "properties": {"name": {"type": "string", "description": "Program or package name, e.g. 'telegram'"}},
        "required": ["name"],
    },
}, "okur", ("kurulu mu", "kontrol edildi"))

# Kurulu bir masaüstü uygulamasını açar (uygulama menüsünden bulur; onay gerekmez, bir şey değiştirmez)
OPEN_APP_SPEC = REGISTRY.add({
    "name": "open_app",
    "description": (
        "Open (launch) a desktop application installed on this computer, e.g. 'telegram', 'firefox', 'spotify', "
        "'hesap makinesi'. Finds it in the application menu by its name, so you don't need to know the command. "
        "ALWAYS use this when the user asks to open, start or launch an app, instead of run_command. "
        "If it reports NOT FOUND, check with check_installed and offer to install it."
    ),
    "input_schema": {
        "type": "object",
        "properties": {"name": {"type": "string", "description": "App name as the user said it, e.g. 'telegram'"}},
        "required": ["name"],
    },
}, "danisir", ("uygulama aç", "açıldı"))

# Hazır API kataloğunda arama: elde olmayan bir konu için API bulur (api_catalog.py)
FIND_API_SPEC = REGISTRY.add({
    "name": "find_api",
    "description": (
        "Search the catalog of well-known public APIs for a topic (weather, currency, news, earthquakes, prayer "
        "times, holidays, books, movies, stocks, football…). Use it when you need live data and no configured API "
        "fits. Ready APIs can be called right away with call_api; for APIs that need a key, tell the user where "
        "to get it and that they can add it in one click under API'ler > hazır API'ler."
    ),
    "input_schema": {
        "type": "object",
        "properties": {"topic": {"type": "string", "description": "What data you need, e.g. 'döviz kuru'"}},
        "required": ["topic"],
    },
}, "okur", ("api bul", "bulundu"), group="ozel")

# Sohbetteki asistanın büyük işleri Çalışma alanındaki ekibe devretmesi (arayüz yürütür)
TEAM_TASK_SPEC = REGISTRY.add({
    "name": "start_team_task",
    "description": (
        "Hand a larger, multi-step job to the user's team of specialist agents in the Work area "
        "(Çalışma). The team plans, works through the steps on its own and reports back; the user "
        "follows progress there. Use this when the user asks you to delegate or give a job to the team, "
        "or when the job clearly needs several steps by different specialists (research, writing, code, "
        "file work). For quick questions, answer yourself instead."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "title": {"type": "string", "description": "Short task title (a few words, user's language)"},
            "goal": {"type": "string", "description": "Complete description of what the team should deliver, with all details the user gave"},
        },
        "required": ["title", "goal"],
    },
}, "ekip", ("gruba ver", "gruba verildi"), group="ozel")

# Ana asistanın tek bir uzman ajana iş vermesi (açıklamaya ekip listesi Agent içinde eklenir)
DELEGATE_SPEC = REGISTRY.add({
    "name": "delegate_to_agent",
    "description": (
        "Give one piece of work to a specialist agent on your team and get its result back. The agent works "
        "with its own tools and the model best suited to its job, then reports to you; you then answer the "
        "user using its result. Use this when a request falls in one specialist's area (research, code, "
        "files, images, summaries). For jobs needing several specialists in sequence use start_team_task; "
        "for quick questions answer yourself."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "agent": {"type": "string", "description": "Agent id from the team list"},
            "task": {"type": "string", "description": "Complete, self-contained instruction with all details, "
                                                      "files and the exact result you need back"},
        },
        "required": ["agent", "task"],
    },
}, "danisir", ("ajana görev ver", "ajan bitirdi"), group="ozel")

# Başka modellerin yeteneklerini kullanma (ajan yürütür; uzman modeller specialists.py'de)
LOOK_SPEC = REGISTRY.add({
    "name": "look_at_image",
    "description": (
        "See an image. A vision-capable specialist model looks at an image file in the workspace (png, jpg, "
        "webp, screenshot, photo, scanned document) and answers your question about it. You cannot see images "
        "yourself, so ALWAYS use this when the user shares or mentions an image; never say you can't see images."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "path": {"type": "string", "description": "Image path relative to the workspace, e.g. ekler/foto.png"},
            "question": {"type": "string", "description": "What to find out, e.g. 'Describe this image in detail and transcribe any text'"},
        },
        "required": ["path", "question"],
    },
}, "danisir", ("resme bak", "bakıldı"))
SPECIALIST_SPEC = REGISTRY.add({
    "name": "ask_specialist",
    "description": (
        "Consult another AI model with different strengths and get its answer: 'reasoning' for hard problems, "
        "math, planning and decisions; 'code' for programming; 'vision' for images (prefer look_at_image); "
        "'general' for a second opinion. Use it whenever you are unsure or a task is beyond you, then combine "
        "its answer into your own solution."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "role": {"type": "string", "description": "reasoning, code, vision or general"},
            "question": {"type": "string", "description": "A complete, self-contained question with all needed context"},
        },
        "required": ["role", "question"],
    },
}, "danisir", ("uzmana danış", "danışıldı"))

# Resim üretme: yerel SDXL modeli (imagegen.py); yalnızca kuruluysa ajana verilir
IMAGE_GEN_SPEC = REGISTRY.add({
    "name": "generate_image",
    "description": (
        "Create new images with the local image model (uncensored SDXL: photos, art, adult/erotic scenes of "
        "adults are allowed; anything involving minors is forbidden and blocked). Write the prompt in ENGLISH as "
        "comma-separated visual details: subject, clearly adult age (e.g. 'adult woman, 30 years old'), body, "
        "clothing, pose, setting, lighting, camera/style (e.g. 'photo, 85mm, soft light, detailed skin'). "
        "Images are saved in the workspace under Resimler/ and shown to the user automatically."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "prompt": {"type": "string", "description": "English visual description, comma separated"},
            "negative": {"type": "string", "description": "Optional: things to avoid"},
            "width": {"type": "integer", "description": "Default 1024 (832x1216 portrait, 1216x832 landscape)"},
            "height": {"type": "integer", "description": "Default 1024"},
            "count": {"type": "integer", "description": "How many images, 1-4 (default 1)"},
        },
        "required": ["prompt"],
    },
}, "yazar", ("resim üret", "resim üretildi"), group="ozel")

# Kalıcı hafıza: sohbetler arasında hatırlanacak tercihler, bilgiler ve dersler (programın kendi verisi)
REMEMBER_SPEC = REGISTRY.add({
    "name": "remember",
    "description": (
        "Save something to long-term memory so you know it in future conversations: the user's preferences (how "
        "they want answers, files, language, tone), facts about them or this computer, or a lesson learned (a method "
        "or command that worked or failed on this system). Use it when the user says to remember something, states a "
        "lasting preference, corrects you, or when you discover something that will matter next time. Not for "
        "one-off details of the current task. One short sentence per call."),
    "input_schema": {
        "type": "object",
        "properties": {
            "text": {"type": "string", "description": "One short, self-contained sentence in the user's language"},
            "kind": {"type": "string", "description": "tercih (preference) · bilgi (fact) · ders (lesson) · "
                     "ekipman (the user's devices and their settings: 3D printer model and bed size, camera, phone…)"},
        },
        "required": ["text"],
    },
}, "danisir", ("hafızaya kaydet", "kaydedildi"))

# Tarayıcı (BrowserAgent): gerçek Chromium, kalıcı profil. Tıklama ve yazma numarayla; satın alma, mesaj, hesap,
# giriş/indirme gruplarındaki eylemleri agent.py her zaman kullanıcıya sorar (browser.gate)
_REF = {"type": "integer", "description": "Element number from the last browser_read / browser_open result, e.g. 12"}
BROWSER_SPECS = [
    REGISTRY.add({"name": "browser_open", "description": (
        "Open a web page in the real browser window (the user sees it; logins stay in its profile). Returns the page's "
        "numbered interactive elements and visible text."),
        "input_schema": {"type": "object", "properties": {"url": {"type": "string", "description": "Address, e.g. "
                         "https://www.hepsiburada.com"}}, "required": ["url"]}},
        "danisir", ("sayfayı aç", "açıldı"), group="tarayici"),
    REGISTRY.add({"name": "browser_read", "description": (
        "Read the current page again: numbered elements (links, buttons, fields) and visible text. Use `find` to show "
        "only elements and lines containing some words (e.g. prices, a product name)."),
        "input_schema": {"type": "object", "properties": {"find": {"type": "string", "description": "Optional words "
                         "to filter by"}}}}, "danisir", ("sayfayı oku", "okundu"), group="tarayici"),
    REGISTRY.add({"name": "browser_click", "description": (
        "Click an element by its number. Buying, paying, sending/posting, deleting, account changes, logging in and "
        "downloads are always shown to the user for approval first."),
        "input_schema": {"type": "object", "properties": {"ref": _REF}, "required": ["ref"]}},
        "danisir", ("tıkla", "tıklandı"), group="tarayici"),
    REGISTRY.add({"name": "browser_type", "description": (
        "Type text into a field by its number (replaces its content); submit=true presses Enter (e.g. to search). "
        "Passwords and payment details are always shown to the user for approval first."),
        "input_schema": {"type": "object", "properties": {
            "ref": _REF, "text": {"type": "string", "description": "Text to type"},
            "submit": {"type": "boolean", "description": "Press Enter after typing"}}, "required": ["ref", "text"]}},
        "danisir", ("yaz", "yazıldı"), group="tarayici"),
    REGISTRY.add({"name": "browser_scroll", "description": "Scroll the page down (or up) and read it again.",
        "input_schema": {"type": "object", "properties": {"direction": {"type": "string", "description": "down or up"}}}},
        "danisir", ("kaydır", "kaydırıldı"), group="tarayici"),
    REGISTRY.add({"name": "browser_back", "description": "Go back to the previous page and read it.",
        "input_schema": {"type": "object", "properties": {}}}, "danisir", ("geri", "geri gidildi"), group="tarayici"),
    REGISTRY.add({"name": "browser_look", "description": (
        "Take a screenshot of the page and ask the vision model about it — for things the element list cannot show "
        "(images, charts, maps, canvas, layout, which of several similar buttons is highlighted)."),
        "input_schema": {"type": "object", "properties": {"question": {"type": "string", "description": "What to find "
                         "out from the screenshot"}}, "required": ["question"]}},
        "danisir", ("sayfaya bak", "bakıldı"), group="tarayici"),
    REGISTRY.add({"name": "browser_extract_items", "description": (
        "Read the product / listing list of the current page as structured rows (name, price, currency, link) — for "
        "prices and product lists use this instead of reading numbered elements. Reads the page again each time. "
        "If the page has no such list it says so: never invent rows."),
        "input_schema": {"type": "object", "properties": {
            "find": {"type": "string", "description": "Optional words every product name must contain"},
            "max_items": {"type": "integer", "description": "Default 30"}}}},
        "danisir", ("ürünleri oku", "okundu"), group="tarayici"),
]
BROWSER_TOOLS = {s["name"] for s in BROWSER_SPECS}

# Görev motorunun yetenekleri için (K5 `dosya_tasi`): sohbet ajanlarına verilmez (grup "gorev"), talimat uzamaz
MOVE_FILE_SPEC = REGISTRY.add({
    "name": "move_file",
    "description": "Move or rename a file or folder inside the workspace. Never overwrites an existing file.",
    "input_schema": {
        "type": "object",
        "properties": {
            "source": {"type": "string", "description": "Path relative to the workspace"},
            "target": {"type": "string", "description": "New path, or an existing folder to move into"},
        },
        "required": ["source", "target"],
    },
}, "yazar", ("taşı", "taşındı"), group="gorev")

# Araç fabrikası (Aşama 5): eksik yetenek için test edilmiş yeni araç; ekleme ayrıca kullanıcıya sorulur
# Kullanıcının beceri dosyaları (definitions.py): talimatta yalnızca adlar; tarifin tamamı bu araçla
USE_SKILL_SPEC = REGISTRY.add({
    "name": "use_skill",
    "description": "Get the full recipe of one of the user's skills listed under 'Skills' in your instructions. "
                   "Call it before doing a job that matches a skill, then follow the recipe.",
    "input_schema": {
        "type": "object",
        "properties": {"name": {"type": "string", "description": "Skill name from the list"}},
        "required": ["name"],
    },
}, "okur", ("beceriyi aç", "açıldı"), group="ozel")

# Masaüstü uygulaması kurma, yönetici izni olmadan (apps.py): Flatpak --user, AppImage, winget --scope user, brew
INSTALL_APP_SPEC = REGISTRY.add({
    "name": "install_app",
    "description": (
        "Install a desktop application for this user only, without administrator rights (Linux: Flatpak if "
        "available, otherwise the official AppImage; Windows: winget; macOS: Homebrew). Use it when a job needs a "
        "real program (3D slicer, CAD, image or video editor…) that Python libraries cannot replace. On Linux "
        "without Flatpak give source: the app's GitHub repo as owner/repo (latest release AppImage is picked) or the "
        "https address of its .AppImage from the official site; find it with web_search first. Always official "
        "sources only."),
    "input_schema": {
        "type": "object",
        "properties": {
            "name": {"type": "string", "description": "Application name, e.g. OrcaSlicer"},
            "source": {"type": "string", "description": "owner/repo, https .AppImage address, Flatpak id, winget id "
                       "or Homebrew cask (optional; empty: search the package manager by name)"},
            "purpose": {"type": "string", "description": "Why it is needed, in the user's language (shown when "
                        "asking for approval)"},
        },
        "required": ["name"],
    },
}, "kurar", ("uygulama kur", "kuruldu"))

# Sonucu gözle denetleme (inspect_output.py): çıktıyı resme çevirir, görme modeline istenen şey mi diye sorar
INSPECT_SPEC = REGISTRY.add({
    "name": "inspect_output",
    "description": (
        "Look at a result the way the user will see it and check it against the request: renders 3D models (3 "
        "views with size), PDFs (first pages), SVG, video (a frame) and images, and asks the vision model your "
        "question; for Word/PowerPoint/Excel it reports the structure (headings, tables, pictures, sheets, embedded "
        "charts). Use it before saying a visual result is done; if the answer shows a mismatch, fix and check again."),
    "input_schema": {
        "type": "object",
        "properties": {
            "path": {"type": "string", "description": "The output file in the workspace"},
            "question": {"type": "string", "description": "What it must show, as a yes/no check, e.g. 'Is this a "
                         "40x20x10 mm block with one round hole through the middle?'"},
        },
        "required": ["path", "question"],
    },
}, "danisir", ("sonucu denetle", "denetlendi"))

# Asistanın kendi bulduğu yolu tarif olarak kaydetmesi (definitions.learn): bir dahaki sefere araştırmasın
LEARN_SKILL_SPEC = REGISTRY.add({
    "name": "learn_skill",
    "description": (
        "Save a recipe you just worked out (after research or several attempts) so next time you can call use_skill "
        "instead of starting over. Only after it actually worked. Recipe: the tools/libraries, a short working code "
        "or command template, the steps, and the pitfalls you hit. Same name again updates your earlier recipe."),
    "input_schema": {
        "type": "object",
        "properties": {
            "name": {"type": "string", "description": "short-kebab-case name, e.g. video-kurgu"},
            "description": {"type": "string", "description": "One line in the user's language: when to use it"},
            "recipe": {"type": "string", "description": "The recipe in Markdown (under 4000 characters)"},
        },
        "required": ["name", "description", "recipe"],
    },
}, "danisir", ("beceri öğren", "beceri kaydedildi"))

REQUEST_TOOL_SPEC = REGISTRY.add({
    "name": "request_tool",
    "description": (
        "Get a new tool built when NONE of your tools can do a needed part of the job (for example: convert a file "
        "format, read a special file type, compute something domain-specific, talk to a local device or service). "
        "The tool factory looks for a ready solution, writes a tool, tests it in a sandbox and asks the user to "
        "approve it; then you can call the new tool. Do not use it for things run_python can do in a few lines "
        "once, or for things that are impossible or harmful."),
    "input_schema": {
        "type": "object",
        "properties": {
            "need": {"type": "string", "description": "The missing capability: what goes in, what should come out"},
            "example": {"type": "string", "description": "How you will call it for the current job (optional)"},
        },
        "required": ["need"],
    },
}, "danisir", ("araç iste", "araç fabrikası bitti"))

def needs_approval(name: str, args: dict) -> bool:
    """Bu çağrı her seferinde onay ister mi? (kayıttaki risk sınıfından; bilinmeyen araç: evet)"""
    # API'den yalnızca okuma serbest; veri değiştirebilecek istekler onaylanır
    if name == "call_api":
        return str((args or {}).get("method") or "GET").upper() != "GET"
    tool = REGISTRY.get(name)
    return tool is None or (tool.risk in APPROVAL_RISKS and not tool.trusted)


# Onay penceresi için: koddaki etkileri düz Türkçe ile işaretler (kaba bir tarama; güvence değildir)
_RISKS = [
    (r"\brm\s|\brmdir\b|shutil\.rmtree|os\.remove|os\.unlink|\.unlink\(|os\.rmdir|\bshred\b",
     "Dosya ya da klasör SİLİYOR."),
    (r"\bmv\s|shutil\.move|os\.rename|\.rename\(", "Dosyaları taşıyor ya da yeniden adlandırıyor."),
    (r"\bsudo\b|\bpkexec\b|\bdoas\b", "Yönetici (root) yetkisi istiyor."),
    (r"\b(pip3?|pipx|npm|pnpm|yarn|pacman|yay|paru|apt(-get)?|dnf|flatpak|cargo)\s+(install|add|-S)\b",
     "Program ya da paket KURUYOR."),
    (r"\bcurl\b|\bwget\b|requests\.|httpx\.|urllib|socket\.|aiohttp|\bssh\b|\bscp\b|\bgit\s+(clone|push|pull)",
     "İnternete bağlanıyor."),
    (r"\bsystemctl\b|\bchmod\b|\bchown\b|\bmount\b|\bdd\b|\bmkfs|/etc/|crontab",
     "Sistem ayarlarına ya da izinlere dokunuyor."),
    (r"\bkill(all)?\b|\bpkill\b|\breboot\b|\bshutdown\b|\bpoweroff\b", "Çalışan programları kapatıyor ya da bilgisayarı yeniden başlatıyor."),
    (r"subprocess|os\.system|os\.popen", "Python içinden başka komutlar çalıştırıyor."),
    (r">\s*[\w./~-]|open\([^)]*['\"][wa]b?['\"]|\.write_text|\.write_bytes|\btee\b|\bcp\s", "Dosyaya yazıyor."),
]


def describe_risks(name: str, args: dict, workspace: str) -> list[str]:
    """Onay penceresinde gösterilecek, koddan çıkarılmış etkiler."""
    import re

    if name == "call_api":
        method = str(args.get("method") or "GET").upper()
        return [f"“{args.get('api')}” servisine {method} isteği gönderiyor; oradaki verileri değiştirebilir."]
    if name == "install_app":  # program indirip kuruyor: nereden geldiği görünsün
        source = str(args.get("source") or "paket yöneticisi (Flatpak / winget / Homebrew)")
        from .apps import trusted

        return [f"“{args.get('name')}” uygulamasını yalnızca bu kullanıcıya kuruyor (yönetici izni gerekmez).",
                f"Kaynak: {source}",
                "Bilinen bir yayıncının resmi kaynağı." if trusted(str(args.get("source") or "")) else
                "⚠ BİLİNEN BİR YAYINCI DEĞİL: bu kaynağın gerçekten uygulamanın resmi yeri olduğundan emin değilsen onaylama."]
    if name.startswith("browser_"):  # tarayıcı: kapının nedeni ve sayfa
        return [str(args.get("purpose") or "Tarayıcıda bir işlem yapılacak."),
                "Onaylarsan bu tek işlem yapılır; sonraki benzer işlemler yine sorulur."]
    if name == "add_tool":  # araç fabrikası: yeni araç ekleniyor
        found = ["Programa kalıcı yeni bir araç ekleniyor (araç fabrikası yazdı, sandbox'ta internetsiz test edildi).",
                 "Araç her çalıştırılışında yine güvenlik ajanı ya da sen denetlersin; istediğinde Yardım → Araç "
                 "fabrikası'ndan silebilirsin."]
        if args.get("packages"):
            found.append(f"Şu kütüphaneleri kullanıyor: {args['packages']}")
        code = str(args.get("code") or "")
        return found + [msg for pattern, msg in _RISKS if re.search(pattern, code)]
    tool = REGISTRY.get(name)
    if tool is not None and tool.source == "fabrika":
        return ["Araç fabrikasının eklediği bir araç: kodu Yardım → Araç fabrikası'nda."]
    if tool is not None and tool.source != "yerlesik":
        where = tool.source.split(":", 1)[-1]
        found = [f"Dışarıdan takılan “{where}” MCP sunucusunda çalışıyor; ne yaptığını o sunucu belirler."]
        if tool.hints.get("destructiveHint", True) and not tool.hints.get("readOnlyHint"):
            found.append("Sunucu bu aracın geri alınamayan değişiklikler yapabileceğini belirtiyor (ya da belirtmiyor).")
        if tool.hints.get("openWorldHint", True):
            found.append("İnternetteki ya da başka sistemlerdeki verilere dokunabilir.")
        return found
    text = str(args.get("command") or args.get("code") or "")
    found = [msg for pattern, msg in _RISKS if re.search(pattern, text)]
    root = str(Path(workspace).expanduser().resolve())
    outside = [p for p in re.findall(r"(?<![\w.:/-])(/[\w.+-]+(?:/[\w.+-]+)*|~/[\w./+-]*)", text)
               if not str(Path(p).expanduser()).startswith((root, "/tmp", "/dev/null", "/usr/bin", "/bin"))]
    if outside or re.search(r"\.\./|\$HOME|Path\.home\(\)|expanduser", text):
        where = ", ".join(sorted(set(outside))[:3])
        found.append("Çalışma klasörünün DIŞINA erişiyor" + (f": {where}" if where else "."))
    return found


# JSON şema türleri (MCP araçları number, boolean, array da kullanır)
_JSON_TYPES = {"string": str, "integer": int, "object": dict, "number": (int, float), "boolean": bool, "array": list}


def validate_input(name: str, args) -> str | None:
    """Model çıktısını şemaya göre denetler; sorun varsa hata metni döndürür."""
    tool = REGISTRY.get(name)
    if tool is None:
        return f"Unknown tool: {name}"
    if not isinstance(args, dict):
        return "Tool input must be a JSON object"
    schema = tool.schema
    for key in schema.get("required") or []:
        if key not in args:
            if key == "purpose":  # yalnızca onay penceresindeki açıklama: yoksa program kendisi yazar, reddetme
                args[key] = ""
                continue
            return f"Missing required argument: {key}"
    for key, value in args.items():
        prop = (schema.get("properties") or {}).get(key)
        expected = _JSON_TYPES.get(prop.get("type")) if isinstance(prop, dict) and isinstance(prop.get("type"), str) else None
        if expected is None:  # şemada türü yok ya da birden çok tür: olduğu gibi geçer
            continue
        if expected is int and isinstance(value, str) and value.strip().lstrip("-").isdigit():
            args[key] = int(value)  # yerel modeller sayıları bazen metin olarak yollar
        elif expected is int and isinstance(value, float) and value.is_integer():
            args[key] = int(value)
        elif expected is str and isinstance(value, (dict, list)):
            args[key] = json.dumps(value, ensure_ascii=False, indent=2)  # dosya içeriği JSON nesnesi olarak geldi
        elif expected is str and isinstance(value, (int, float)) and not isinstance(value, bool):
            args[key] = str(value)
        elif not isinstance(value, expected) or (expected is int and isinstance(value, bool)):
            return f"Argument '{key}' must be of type {prop['type']}"
    return None


def _truncate(text: str) -> str:
    if len(text) <= MAX_OUTPUT:
        return text
    return text[:MAX_OUTPUT] + f"\n\n[... çıktı kısaltıldı, toplam {len(text)} karakter]"


ToolError = AracHatasi  # K1: çekirdekteki sınıfla aynı (araç uygulamaları cekirdek/araclar'da)


def file_stem(name: str, default: str) -> str:
    """Modelin verdiği addan güvenli dosya adı (Türkçe harfler sadeleşir)."""
    table = str.maketrans("çğıöşüÇĞİÖŞÜ", "cgiosuCGIOSU")
    return re.sub(r"[^a-z0-9_-]+", "_", (name or default).translate(table).lower()).strip("_-")[:50] or default


def missing_image(root: Path, image: str) -> ToolError:
    """Resim bulunamadı: modele klasördeki en yeni resimleri söyler. Küçük modeller üretilen resmin adını kısaltıyor
    ("Resimler/resim-0.png"; gerçek ad "Resimler/resim-20260927-180119-0.png"), liste görünce tek denemede düzeltir."""
    pics = [p for p in root.rglob("*") if p.suffix.lower() in (".png", ".jpg", ".jpeg", ".webp")
            and not any(x.startswith(".") for x in p.relative_to(root).parts) and not p.stem.endswith("-girdi")]
    newest = sorted(pics, key=lambda p: p.stat().st_mtime, reverse=True)[:5]
    listing = ", ".join(str(p.relative_to(root)) for p in newest)
    return ToolError(f"No such image: {image}." + (f" Newest images in the workspace: {listing}" if listing else ""))


def model_report(r: dict, root: Path) -> str:
    """decor3d.save sonucu → modele giden metin (süs modeli ve 3D figür aynı biçimde)."""
    files = ", ".join(str(Path(f).relative_to(root)) for f in r["files"])
    x, y, z = r["size_mm"]
    lines = [f"Created {files}: {x} × {y} × {z} mm, {r['bodies']} body, "
             + ("watertight (ready to slice)" if r["watertight"] else "NOT watertight")
             + (f", about {r['filament_g']} g PLA" if r.get("filament_g") else "")
             + (f" at {r['infill'] * 100:.0f}% infill" if r.get("infill") else "") + "."]
    lines += ["Print notes (tell the user):"] + [f"- {n}" for n in r["notes"]]
    lines.append("Next: check it with inspect_output (a yes/no question describing the request) before answering.")
    return "\n".join(lines)


unescape_code = a_komut.kacislari_coz  # tek satıra "\\n" ile sıkıştırılmış kodu çözer (cekirdek/araclar/komut.py)


def _fit_args(handler, args) -> dict:
    """Küçük modellerin hatalı çağrılarını düzeltir: bilinmeyen argümanları atar, "5" → 5 çevirir."""
    import inspect

    if not isinstance(args, dict):
        raise ToolError("Tool arguments must be a JSON object")
    params = inspect.signature(handler).parameters
    fitted = {}
    for key, value in args.items():
        param = params.get(key)
        if param is None:
            continue
        if param.annotation is int and not isinstance(value, int):
            try:
                value = int(float(str(value).strip()))
            except ValueError:
                raise ToolError(f"{key} must be a number, got {value!r}") from None
        elif param.annotation is str and value is not None and not isinstance(value, str):
            # dosya içeriği JSON nesnesi olarak geldiyse düzgün JSON yazılsın ("{'a': 1}" değil)
            value = json.dumps(value, ensure_ascii=False, indent=2) if isinstance(value, (dict, list)) else str(value)
        fitted[key] = value
    missing = [p.name for p in params.values() if p.default is inspect.Parameter.empty and p.name not in fitted]
    if missing:
        raise ToolError("Missing required argument(s): " + ", ".join(missing))
    return fitted


class Toolbox:
    def __init__(self, workspace: str, apis: list | None = None):
        self.root = Path(workspace).expanduser().resolve()
        self.read_roots = program_roots()  # asistan kendi programını okuyabilsin (yalnızca okuma)
        self.root.mkdir(parents=True, exist_ok=True)
        self.apis = apis or []  # connections.Connection (kind == "tool")

    def _resolve(self, path: str, read: bool = False) -> Path:
        # Model çıktısı güvenilmez: çalışma klasörünün dışına çıkan yolları reddet. Okuma araçları ayrıca
        # programın kendi klasörlerine (kod, ayarlar, veriler) erişebilir: asistan içinde çalıştığı programı tanısın.
        return a_dosya.yol_coz(self.root, self.read_roots, path, read)

    def _base(self, target: Path) -> Path:
        """Yolun bağlı olduğu izinli kök (çalışma klasörü ya da programın bir klasörü)."""
        return a_dosya.taban(target, self.root, self.read_roots)

    def _shown(self, path: Path) -> str:
        return a_dosya.gorunen(path, self.root)

    def run(self, name: str, args: dict) -> str:
        handler = getattr(self, f"_tool_{name}", None)
        if handler is None:
            tool = REGISTRY.get(name)
            if tool is not None and tool.runner is not None:  # dışarıdan takılan araç (MCP sunucusu)
                return _truncate(tool.runner(args))
            raise ToolError(f"Unknown tool: {name}")
        return _truncate(handler(**_fit_args(handler, args)))

    def _tool_install_python_package(self, packages: str, purpose: str = "") -> str:
        import importlib.metadata as md
        import re as _re

        names = [p for p in packages.replace(",", " ").split() if p]
        if not names or any(not _re.fullmatch(r"[A-Za-z0-9._\-\[\]=<>!~]+", p) for p in names):
            raise ToolError("packages must be plain pip package names")
        present = {(d.metadata["Name"] or "").lower().replace("_", "-")
                   for d in md.distributions(path=[str(USER_LIBS), str(BUNDLED_LIBS), *sys.path])}
        todo = [p for p in names if _re.split(r"[\[=<>!~]", p)[0].lower().replace("_", "-") not in present]
        if not todo:
            return "Already installed: " + ", ".join(names)
        USER_LIBS.mkdir(parents=True, exist_ok=True)
        # programın kendi kütüphanelerine dokunmadan ajanın klasörüne kurar
        return self._run_process([python_exe(), "-m", "pip", "install", "--disable-pip-version-check",
                                  "--target", str(USER_LIBS), "--upgrade", *todo], python=True)

    def _tool_install_app(self, name: str, source: str = "", purpose: str = "") -> str:
        from . import apps

        try:
            return apps.install(name, source)
        except apps.AppError as e:
            raise ToolError(str(e))

    def _tool_check_3d_model(self, path: str, bed: str = "220x220x250") -> str:
        target = self._resolve(path, read=True)
        if not target.is_file():
            raise ToolError(f"No such file: {path}")
        if not re.fullmatch(r"\s*\d+(\.\d+)?\s*x\s*\d+(\.\d+)?\s*x\s*\d+(\.\d+)?\s*", bed or ""):
            raise ToolError("bed must look like 220x220x250 (mm)")
        out = subprocess.run([python_exe(), "-c", _CHECK_3D, str(target), bed.replace(" ", "")], capture_output=True,
                             text=True, encoding="utf-8", errors="replace", timeout=120, env=agent_env(), creationflags=NO_WINDOW)
        if out.returncode != 0:
            if "No module named 'trimesh'" in out.stderr:
                raise ToolError("trimesh is not installed: install it with install_python_package (trimesh "
                                "manifold3d), then call check_3d_model again.")
            raise ToolError("Could not read the model: " + (out.stderr.strip().splitlines() or ["?"])[-1])
        r = json.loads(out.stdout)
        x, y, z = r["size_mm"]
        lines = [f"Size: {x} × {y} × {z} mm; triangles: {r['triangles']}; bodies: {r['bodies']}; "
                 f"volume: {r['volume_cm3']} cm³" if r["volume_cm3"] is not None else
                 f"Size: {x} × {y} × {z} mm; triangles: {r['triangles']}; bodies: {r['bodies']}"]
        lines += ["PROBLEMS:"] + [f"- {p}" for p in r["problems"]] if r["problems"] else \
            [f"OK: watertight, fits the {bed} mm bed; ready to slice."]
        return "\n".join(lines)

    def _tool_make_decor_model(self, shape: str, name: str = "", height=None, width=None, profile: str = "",
                               pattern: str = "", sides=None, twist=None, wall=None, hole=None, thickness=None,
                               image: str = "", invert=False, bed: str = "220x220x250") -> str:
        target = self._resolve(f"3D/{file_stem(name, shape)}")
        args = {"shape": shape, "height": height, "width": width, "profile": profile, "pattern": pattern,
                "sides": sides, "twist": twist, "wall": wall, "hole": hole, "thickness": thickness, "bed": bed,
                "invert": invert is True or str(invert).lower() in ("true", "1", "evet"), "out": str(target)}
        if image:
            picture = self._resolve(image, read=True)
            if not picture.is_file():
                raise missing_image(self.root, image)
            args["image"] = str(picture)
        out = subprocess.run([python_exe(), str(DECOR_SCRIPT), json.dumps(args)], capture_output=True, text=True,
                             encoding="utf-8", errors="replace", timeout=300, env=agent_env(), creationflags=NO_WINDOW)
        if out.returncode != 0:
            last = (out.stderr.strip().splitlines() or ["?"])[-1]
            if "No module named" in last:
                raise ToolError(f"A 3D library is missing ({last}); install it with install_python_package "
                                "(manifold3d trimesh), then try again.")
            raise ToolError("Model could not be built: " + last)
        r = json.loads(out.stdout.strip().splitlines()[-1])
        if r.get("error"):
            raise ToolError(r["error"])
        return model_report(r, self.root)

    def _tool_check_installed(self, name: str) -> str:
        """Programın izini birçok yerde arar; yalnızca okur."""
        import shutil

        name = name.strip()
        if not name:
            raise ToolError("name is empty")
        key = name.lower()
        found = []

        def probe(label: str, argv: list[str], keep=lambda line: any(k in line.lower() for k in keys)):
            if not shutil.which(argv[0]):
                return
            try:
                out = subprocess.run(argv, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=20, creationflags=NO_WINDOW).stdout
            except (OSError, subprocess.SubprocessError):
                return
            lines = [ln.strip() for ln in out.splitlines() if ln.strip() and keep(ln)][:8]
            if lines:
                found.append(f"{label}:\n  " + "\n  ".join(lines))

        # "python-telegram-bot" gibi adlarda asıl ürün kelimesiyle de ara ("telegram")
        generic = {"python", "py", "client", "bot", "app", "desktop", "linux", "windows", "api", "sdk", "lib"}
        words = [w for w in re.split(r"[-_ .]+", key) if len(w) >= 4 and w not in generic]
        keys = list(dict.fromkeys([key, *words]))

        for variant in {name, key, key.replace(" ", "-"), key.replace(" ", ""), *words}:
            path = shutil.which(variant)
            if path:
                found.append(f"PATH: {variant} → {path}")
        if sys.platform == "win32":
            probe("winget", ["winget", "list", "--name", name, "--accept-source-agreements"])
        else:
            probe("pacman", ["pacman", "-Q"])
            probe("dpkg", ["dpkg-query", "-W", "-f=${Package} ${Version}\n"])
            probe("rpm", ["rpm", "-qa"])
            probe("flatpak", ["flatpak", "list", "--app", "--columns=name,application,version"])
            probe("snap", ["snap", "list"])
            for folder in (Path.home() / ".local/share/applications", Path("/usr/share/applications"),
                           Path("/var/lib/flatpak/exports/share/applications")):
                if folder.is_dir():
                    apps = [p.name for p in folder.glob("*.desktop") if any(k.replace(" ", "") in p.name.lower() for k in keys)]
                    if apps:
                        found.append(f"uygulama menüsü ({folder}): " + ", ".join(apps[:5]))
        probe("pip", [python_exe(), "-m", "pip", "list", "--disable-pip-version-check",
                      *[a for p in (USER_LIBS, BUNDLED_LIBS, *map(Path, sys.path)) if p.is_dir()
                        for a in ("--path", str(p))]])
        try:
            models = httpx.get("http://localhost:11434/api/tags", timeout=2).json().get("models", [])
            names = [m["name"] for m in models if any(k in m["name"].lower() for k in keys)]
            if names:
                found.append("ollama modelleri: " + ", ".join(names))
        except Exception:
            pass
        if not found:
            return (f"'{name}' not found on this computer (PATH, package manager, flatpak/snap, pip, apps, "
                    "ollama). It is not installed — or it has a different name; try the exact package name.")
        return f"'{name}' FOUND — already present:\n" + "\n".join(found)

    def _tool_open_app(self, name: str) -> str:
        """Uygulamayı menüdeki kısayolundan bulup programdan bağımsız başlatır."""
        import os
        import shlex
        import shutil
        import time

        name = name.strip()
        if not name:
            raise ToolError("name is empty")
        detached = {"stdin": subprocess.DEVNULL, "stdout": subprocess.DEVNULL, "stderr": subprocess.DEVNULL,
                    "cwd": str(Path.home())}
        if sys.platform == "win32":
            ps = f"Start-Process -FilePath '{name}'"
            proc = subprocess.run(["powershell", "-NoProfile", "-Command", ps], capture_output=True, text=True, encoding="utf-8", errors="replace",
                                  timeout=30, creationflags=NO_WINDOW)
            if proc.returncode:
                return f"'{name}' NOT FOUND or could not start: {proc.stderr.strip()[:500]}"
            return f"Opened '{name}'."
        if sys.platform == "darwin":
            proc = subprocess.run(["open", "-a", name], capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=30)
            return f"Opened '{name}'." if proc.returncode == 0 else f"'{name}' NOT FOUND: {proc.stderr.strip()}"

        # Linux: uygulama menüsündeki .desktop dosyalarında ad, Türkçe ad, anahtar kelime ve dosya adına bak
        key = name.lower().replace(" ", "")
        data_dirs = [Path(os.environ.get("XDG_DATA_HOME", Path.home() / ".local/share"))]
        data_dirs += [Path(p) for p in os.environ.get("XDG_DATA_DIRS", "/usr/local/share:/usr/share").split(":") if p]
        data_dirs += [Path.home() / ".local/share/flatpak/exports/share", Path("/var/lib/flatpak/exports/share"),
                      Path("/var/lib/snapd/desktop")]
        best = None  # (puan, dosya, Exec)
        seen = set()
        for folder in dict.fromkeys(d / "applications" for d in data_dirs):
            if not folder.is_dir():
                continue
            for desktop in folder.rglob("*.desktop"):
                if desktop.name in seen:  # kullanıcının kısayolu sistemdekini gölgeler
                    continue
                seen.add(desktop.name)
                fields = {}
                try:
                    in_entry = False
                    for line in desktop.read_text(encoding="utf-8", errors="replace").splitlines():
                        if line.startswith("["):
                            in_entry = line.strip() == "[Desktop Entry]"
                        elif in_entry and "=" in line:
                            k, v = line.split("=", 1)
                            fields.setdefault(k.strip(), v.strip())
                except OSError:
                    continue
                if fields.get("Type", "Application") != "Application" or fields.get("NoDisplay") == "true" \
                        or fields.get("Hidden") == "true" or not fields.get("Exec"):
                    continue
                names = [fields.get(k, "") for k in ("Name", "Name[tr]", "GenericName", "GenericName[tr]")]
                names = [n.lower().replace(" ", "") for n in names if n]
                words = (fields.get("Keywords", "") + ";" + fields.get("Keywords[tr]", "")).lower().split(";")
                stem = desktop.stem.lower()
                if key in names:
                    score = 3
                elif any(n.startswith(key) for n in names) or key in stem.split("."):
                    score = 2
                elif key in stem or any(key in n for n in names) or key in [w.strip() for w in words]:
                    score = 1
                else:
                    continue
                if best is None or score > best[0]:
                    best = (score, desktop, fields["Exec"])
        if best:
            _, desktop, exec_line = best
            if shutil.which("gio"):
                argv = ["gio", "launch", str(desktop)]
            else:
                # %U, %f gibi alan kodlarını at; dosya/adres vermeden aç
                argv = [a for a in shlex.split(exec_line) if not re.fullmatch(r"%[a-zA-Z]", a)]
            label = f"{desktop.name} ({' '.join(argv)})"
        else:
            path = shutil.which(name) or shutil.which(key) or shutil.which(name.lower())
            if not path:
                return (f"'{name}' NOT FOUND in the application menu or PATH. It is probably not installed; "
                        "check with check_installed and offer to install it.")
            argv, label = [path], path
        try:
            # ayrı oturumda başlar: asistan kapansa ya da komut bitse de uygulama açık kalır
            proc = subprocess.Popen(argv, start_new_session=True, **detached)
        except OSError as e:
            raise ToolError(f"could not start {label}: {e}") from None
        time.sleep(1.5)
        code = proc.poll()
        if code not in (None, 0):
            return f"Started {label} but it exited right away with code {code}; the app may be broken."
        return f"Opened '{name}' → {label}. It is starting now; tell the user it is open."

    def _tool_list_files(self, path: str = ".") -> str:
        return a_dosya.listele(self.root, self.read_roots, path)

    def _tool_read_file(self, path: str, start_line: int = 1, max_lines: int = 2000) -> str:
        return a_dosya.oku(self.root, self.read_roots, path, start_line, max_lines)

    def _tool_search_files(self, pattern: str, path: str = ".", max_results: int = 200) -> str:
        return a_dosya.ara(self.root, self.read_roots, pattern, path, max_results)

    def _tool_write_file(self, path: str, content: str) -> str:
        return a_dosya.yaz(self.root, self.read_roots, path, content)

    def _tool_edit_file(self, path: str, old_text: str, new_text: str) -> str:
        return a_dosya.duzenle(self.root, self.read_roots, path, old_text, new_text)

    def _tool_move_file(self, source: str, target: str) -> str:
        return a_dosya.tasi(self.root, self.read_roots, source, target)

    def _run_process(self, argv: list[str], python: bool = False, env: dict | None = None) -> str:
        return a_komut.surec(argv, self.root, agent_env() if python else env, COMMAND_TIMEOUT)

    def _tool_run_command(self, command: str, purpose: str = "") -> str:
        return a_komut.komut_calistir(command, self.root, python_yolu=python_exe, ajan_ortami=agent_env,
                                      askpass=_askpass_launcher, zaman_asimi=COMMAND_TIMEOUT)

    def _tool_run_python(self, code: str, purpose: str = "") -> str:
        return a_komut.python_calistir(code, self.root, python_yolu=python_exe(), ortam=agent_env(),
                                       arac_adlari=REGISTRY.tools, zaman_asimi=COMMAND_TIMEOUT)

    # ---- tarayıcı (browser.py; tarayıcı kendi iş parçacığında, turlar arasında açık kalır)
    def _tool_browser_open(self, url: str) -> str:
        from . import browser
        return browser.get().open(url)

    def _tool_browser_read(self, find: str = "") -> str:
        from . import browser
        return browser.get().read(find)

    def _tool_browser_click(self, ref: int) -> str:
        from . import browser
        b = browser.get()
        allow, b.approved_download = b.approved_download, False  # agent.py kullanıcı onayladıysa açar
        return b.click(ref, allow_download=allow)

    def _tool_browser_type(self, ref: int, text: str, submit: bool = False) -> str:
        from . import browser
        return browser.get().type(ref, text, bool(submit))

    def _tool_browser_scroll(self, direction: str = "down") -> str:
        from . import browser
        return browser.get().scroll("up" if str(direction).lower().startswith("u") else "down")

    def _tool_browser_back(self) -> str:
        from . import browser
        return browser.get().back()

    def _tool_browser_extract_items(self, find: str = "", max_items: int = 30) -> str:
        from . import browser
        return browser.get().extract_items(find, max_items)

    def _tool_web_search(self, query: str, max_results: int = 5) -> str:
        return a_web.ara(query, max_results)

    def _tool_fetch_url(self, url: str) -> str:
        return a_web.oku(url)

    def _tool_call_api(self, api: str, method: str = "GET", path: str = "", query: dict | None = None,
                       body: dict | None = None, purpose: str = "") -> str:
        conn = next((c for c in self.apis if api in (c.slug, c.name)), None)
        if conn is None:
            names = ", ".join(c.slug for c in self.apis) or "(none)"
            raise ToolError(f"Unknown API '{api}'. Available: {names}")
        method = (method or "GET").upper()
        if method not in ("GET", "POST", "PUT", "PATCH", "DELETE"):
            raise ToolError(f"Unsupported method: {method}")
        url = conn.base_url.rstrip("/")
        if path:
            if path.startswith(("http://", "https://")):
                raise ToolError("path must be relative to the API base URL")
            url += "/" + path.lstrip("/")
        headers = {"User-Agent": "yeni-nesil-cafer", "Accept": "application/json"}
        params = dict(query or {})
        conn.auth_request(headers, params)
        try:
            resp = httpx.request(method, url, params=params, json=body, headers=headers, timeout=30,
                                 follow_redirects=True)
        except httpx.HTTPError as e:
            raise ToolError(f"Could not reach {url} ({type(e).__name__}). Check the path or the internet "
                            "connection.") from None
        text = resp.text
        ctype = resp.headers.get("content-type", "")
        if "json" in ctype:
            try:
                text = json.dumps(resp.json(), ensure_ascii=False, indent=1)
            except ValueError:
                pass
        elif "html" in ctype:
            # API verisi değil, bir web sayfası geldi (çoğunlukla yol eksik/yanlış): ham HTML bağlamı doldurmasın
            soup = BeautifulSoup(text, "html.parser")
            for tag in soup(["script", "style", "nav", "footer", "header", "noscript", "svg"]):
                tag.decompose()
            page = re.sub(r"\n{3,}", "\n\n", soup.get_text("\n", strip=True))[:3000]
            text = (f"NOTE: this is an HTML web page, not API data — the path is probably missing or wrong. "
                    f"How to use this API: {conn.description or '(no description)'}\n\nPage text:\n{page}")
        if 400 <= resp.status_code < 500 and conn.description and "html" not in ctype:
            # küçük modeller yolu tahmin ediyor ya da unutuyor (canlı deneme: open-meteo'ya /weather, yolsuz
            # geocoding → 404): doğru kullanım hatanın yanında dursun, ikinci deneme doğru olsun
            text += f"\n\nHow to use this API (use exactly these paths and parameters): {conn.description}"
        key = conn.key
        if key:
            text = text.replace(key, "***")  # anahtar yanıtta geri dönerse modele sızmasın
        # istenen adresi de göster: model yanlış yol kullandıysa hatasını görebilsin
        return f"HTTP {resp.status_code} ({method} {url})\n{text}"
