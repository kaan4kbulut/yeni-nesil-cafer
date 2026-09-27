"""Ajan kategorileri: uzman ajanlar yedi alanda toplanır, her alana bu bilgisayara uygun modeller atanır.

Model listeleri 2026-09 araştırmasına göre 12 GB ekran kartı belleği ve 32 GB RAM'li bir bilgisayar için
sıralıdır: 12 GB'a tamamen sığan en iyi modeller önce, daha küçük/hızlı olanlar yedek.
Ajan, listedeki ilk KURULU ve araç sınavını geçen (cards.py) modeli alır; hiçbiri yoksa genel otomatik seçim
(roster.pick_for) devreye girer. Kurulu olmayan önerilen modeller ve model dışı araçlar (ses tanıma, nesne
tespiti…) "Ajan kategorileri" penceresinde kullanıcının tek tıkla kurması için listelenir; program kendiliğinden
bir şey indirmez.

Kaynaklar (2026-09): localaimaster.com (12 GB için en iyi kod modeli: Qwen 2.5 Coder 14B), sitepoint / morphllm
(12-16 GB için genel en iyi: Gemma 4 12B; Qwen 3.6 27B 24 GB ister), roboflow (YOLO26, Florence-2, RF-DETR),
localclaw / bentoml (faster-whisper, Piper — Kokoro Türkçe desteklemez), localaimaster (12 GB'ta resim: SDXL).
"""

import re
from pathlib import Path
from dataclasses import dataclass, field

from .config import DATA_DIR
from .profiles import AgentProfile

# dikte'nin ses modeli (dictation.py): pakete gömülü ya da indirilmiş; ses ajanı aynısını kullanır, yeniden indirmez
_WHISPER_DIRS = [Path(__file__).resolve().parent.parent / "modeller" / "dikte", DATA_DIR / "dikte-modeli"]


@dataclass
class Extra:
    """Model olmayan bileşen: Python kütüphanesi (ajan run_python ile kullanır)."""
    package: str  # pip adı
    note: str  # ne işe yarar (Türkçe)


@dataclass
class Category:
    id: str
    name: str
    icon: str
    covers: str  # kullanıcıya görünen kapsam
    models: list[str]  # bu donanım için sıralı Ollama modelleri
    agents: list[str]  # bu kategorideki ajanların id'leri (ilki kategorinin kendi ajanı)
    extras: list[Extra] = field(default_factory=list)
    limits: str = ""  # dürüst sınırlar


SIZES = {"gemma4:12b": 7.6, "qwen3.5:9b": 6.6, "qwen3.5:4b": 3.4, "qwen2.5-coder:14b": 9.0, "glm-ocr:latest": 2.2,
         "deepseek-ocr:3b": 6.7, "qwen2.5-coder:7b": 4.7, "qwen3.5:2b": 2.7}
SMALL = ["qwen3.5:4b", "qwen3.5:2b"]  # listedekilerin hiçbiri sığmayan bilgisayarlar için

CATEGORIES = [
    Category(
        "dil", "Dil ve Metin (NLP / LLM)", "pen",
        "metin anlamlandırma, çeviri, metin yazarlığı, özetleme, sohbet",
        ["gemma4:12b", "qwen3.5:9b", "qwen3.5:4b"],
        ["dil", "arastirmaci", "ozet"],
        limits="Uzun ve özenli metinlerde bulut modelleri (Online) belirgin biçimde daha iyi yazar."),
    Category(
        "goru", "Bilgisayarlı Görü", "eye",
        "görsel ve video analizi, nesne tespiti, yüz algılama, taranmış belge (OCR), tıbbi görüntü yorumu, "
        "deepfake tespiti",
        ["gemma4:12b", "qwen3.5:9b", "qwen3.5:4b", "glm-ocr:latest"],
        ["gorsel"],
        [Extra("ultralytics", "YOLO ile nesne tespiti ve sayma"), Extra("opencv-python", "yüz algılama, video karelerine ayırma")],
        "Deepfake yalnızca tespit edilir, üretilmez. Tıbbi görüntü yorumu bilgi amaçlıdır, teşhis değildir. "
        "Videolar kare kare incelenir."),
    Category(
        "veri", "Veri Analizi ve Tahminleme", "table",
        "büyük veri setlerinde anormallik bulma, trend analizi, finansal öngörü, istatistiksel modelleme",
        ["qwen2.5-coder:14b", "qwen3.5:9b", "gemma4:12b"],
        ["veri"],
        [Extra("scikit-learn", "anormallik tespiti, sınıflandırma, kümeleme"),
         Extra("statsmodels", "zaman serisi tahmini (ARIMA, mevsimsellik), istatistik testleri")],
        "Tahminler geçmiş veriye dayanır; finansal öngörüler yatırım tavsiyesi değildir."),
    Category(
        "ses", "Ses ve Konuşma", "languages",
        "konuşmayı yazıya çevirme, metni seslendirme, konuşmacı doğrulama, müzik üretimi",
        ["qwen3.5:4b", "gemma4:12b"],
        ["ses"],
        [Extra("faster-whisper", "konuşmayı yazıya çevirme (Türkçe dahil, large-v3-turbo)"),
         Extra("piper-tts", "metni seslendirme (Türkçe ses: tr_TR-dfki-medium)")],
        "Konuşmacı doğrulama ve müzik üretimi için henüz araç yok (Araç fabrikası aşamasında). Birinin sesini "
        "taklit eden ses klonlama yapılmaz."),
    Category(
        "problem", "Problem Çözme ve Kod", "code",
        "karmaşık matematik, lojistik rotalama, oyun stratejisi (satranç…), kod yazma ve hata ayıklama",
        ["qwen2.5-coder:14b", "qwen3.5:9b", "gemma4:12b"],
        ["kod"],
        [Extra("ortools", "rota ve çizelge optimizasyonu"), Extra("sympy", "sembolik matematik"),
         Extra("python-chess", "satranç konumları ve hamle analizi")],
        "Büyük kod tabanlarında Claude Code (Online) çok daha güçlüdür; bağlıysa kod işleri ona gider."),
    Category(
        "otonom", "Otonom Sistemler ve Robotik", "cpu",
        "otonom sürüş, robot kolu, insansız hava aracı: planlama, simülasyon ve kontrol kodu",
        ["qwen3.5:9b", "qwen2.5-coder:14b", "gemma4:12b"],
        ["otonom"],
        [Extra("scipy", "kontrol, optimizasyon ve sinyal işleme")],
        "Bu bilgisayara bağlı fiziksel robot ya da araç yok: iş simülasyon, rota planlama ve kontrol kodu "
        "yazma olarak yapılır."),
    Category(
        "uretken", "Üretken Yaratıcılık", "image",
        "metinden görsel oluşturma, dijital sanat; video ve 3D için hazırlık (senaryo, sahne, istem)",
        ["gemma4:12b", "qwen3.5:9b"],
        ["uretken"],
        extras=[Extra("build123d", "3D baskı için ölçülü parça (STL, 3MF, STEP)"),
                Extra("trimesh", "3D modelin baskıya uygunluğunu denetleme")],
        limits="Görseller yerel SDXL modeliyle üretilir (Yardım → Resim üretimi). 12 GB'ta video üretimi çok "
               "yavaş ve düşük kaliteli. 3D baskı parçaları ölçülü CAD (build123d) ile yapılır; karmaşık "
               "parçalarda bulut modelleri daha iyidir. Süsler (vazo, lamba, süs topu, kabartma, litofan, siluet "
               "figür) hazır süs modeli aracıyla yapılır; gerçek 3D heykelcik henüz yok. Gerçek kişilerin sahte "
               "görüntüleri ve reşit olmayanları çağrıştıran içerik üretilmez."),
]
BY_ID = {c.id: c for c in CATEGORIES}

# yeni kategori ajanları (kod, gorsel, arastirmaci, ozet zaten var: kategorileri eklenir)
_WORK = ["list_files", "read_file", "search_files", "write_file", "run_python"]
NEW_AGENTS = [
    AgentProfile(
        id="dil", name="Dil ve Metin", icon="pen", category="dil",
        description="Çeviri, metin yazarlığı, düzeltme, özet ve anlamlandırma",
        prompt=("You are an expert writer, editor and translator. Translate faithfully and naturally, keeping tone "
                "and terminology; write copy that fits the audience and purpose; when editing, keep the author's "
                "voice. Read source files fully before working on them and save longer results as files."),
        tools=["list_files", "read_file", "search_files", "write_file", "web_search", "fetch_url"]),
    AgentProfile(
        id="veri", name="Veri Analizi", icon="table", category="veri",
        description="Veri setlerinde anormallik, trend, tahmin ve istatistik",
        prompt=("You are a data scientist. Load data with pandas in run_python, look at its shape, types and "
                "missing values first, then analyse: trends, seasonality, anomalies (e.g. IsolationForest or "
                "z-scores), forecasts (statsmodels) and clear charts with matplotlib. Every number you report "
                "must come from code you actually ran. Save results (tables, charts, a short report) as files and "
                "state assumptions and uncertainty plainly."),
        tools=_WORK + ["web_search", "fetch_url"]),
    AgentProfile(
        id="ses", name="Ses ve Konuşma", icon="languages", category="ses",
        description="Konuşmayı yazıya çevirir, metni seslendirir",
        prompt=("You work with audio in run_python. Speech-to-text: faster_whisper.WhisperModel(model, device='cpu', "
                "compute_type='int8') with language='tr' for Turkish, where model is the program's already downloaded "
                "copy: the first existing folder of " + " , ".join(f"'{d}'" for d in _WHISPER_DIRS) + " (use "
                "'large-v3-turbo' only if none exists); save the transcript as a text "
                "file with timestamps when useful. Text-to-speech: the piper library (`python -m piper -m <voice.onnx> "
                "-f out.wav`, text on stdin) with the Turkish voice tr_TR-dfki-medium (the only Turkish piper voice); "
                "if missing, download tr_TR-dfki-medium.onnx and tr_TR-dfki-medium.onnx.json into the workspace from "
                "https://huggingface.co/rhasspy/piper-voices/resolve/main/tr/tr_TR/dfki/medium/<file name>. "
                "Save .wav files. "
                "If a library is missing, install it with install_python_package. Never clone or imitate a real "
                "person's voice."),
        tools=_WORK + ["web_search", "fetch_url"]),
    AgentProfile(
        id="otonom", name="Otonom Sistemler", icon="cpu", category="otonom",
        description="Robot, drone ve otonom araç için planlama, simülasyon, kontrol kodu",
        prompt=("You are a robotics and autonomous-systems engineer. There is no physical robot attached: work in "
                "simulation. Model the problem (kinematics, dynamics, sensors), plan paths (A*, RRT, trajectory "
                "optimisation), write and test control code (PID, MPC) with numpy/scipy in run_python, and show "
                "results with plots or animations saved as files. Explain safety limits of the design."),
        tools=_WORK + ["edit_file", "web_search", "fetch_url"]),
    AgentProfile(
        id="uretken", name="Üretken Yaratıcılık", icon="image", category="uretken",
        description="Metinden görsel, dijital sanat; 3D yazıcı için süs modelleri; video için senaryo ve istem",
        prompt=("You are a digital artist and creative director. Turn the user's idea into strong visual prompts "
                "(subject, composition, lighting, style, lens, colour) and create images with generate_image; offer "
                "variations. For 3D-printable decorations (vase, lamp, ornament, figurine, relief, lithophane) use "
                "make_decor_model; for a figure, first generate a black silhouette image, then shape 'siluet'. For "
                "video requests, write the storyboard, shot list and prompts, and say plainly that local video "
                "generation is not available yet. Never depict real people in fake situations."),
        tools=["list_files", "read_file", "write_file", "look_at_image", "web_search"]),
]
# BrowserAgent: gerçek tarayıcıda çalışan ajan (kategorisiz; yönetici tarayıcı işlerini ona verir)
BROWSER_AGENT = AgentProfile(
    id="tarayici", name="Tarayıcı ajanı", icon="globe", category="",
    description="Gerçek tarayıcıda siteleri açar, arar, tıklar, form doldurur; satın alma ve gönderme öncesi sorar",
    prompt=(
        "You are the browser agent. You work in a real browser window that the user can see; its profile keeps the "
        "user's logins. Work in a loop: observe (the numbered elements and text that browser_open / browser_read "
        "return) → decide → act (browser_click / browser_type with an element NUMBER from the latest result) → observe "
        "the new page → check you are where you wanted to be. Use browser_read with `find` to locate prices, names or "
        "a button; scroll for more; use browser_look only for things the element list cannot show (images, charts, "
        "maps, which option is selected). Never guess facts such as prices: read them from the page. When collecting "
        "information (for example comparing prices), open several relevant pages, extract the data, and finish with "
        "a clear comparison that lists the source URLs. The app asks the user before buying or paying, sending or "
        "posting, deleting or changing an account, logging in and downloading; if the user declines, stop and report. "
        "If the user said not to buy something, never click buying buttons at all. If a CAPTCHA or a login appears, "
        "ask the user to complete it in the browser window, then continue. Reply in the user's language."),
    tools=["browser_open", "browser_read", "browser_click", "browser_type", "browser_scroll", "browser_back",
           "browser_look", "web_search", "fetch_url", "write_file", "remember"])

# mevcut ajanların kategorileri
EXISTING = {"kod": "problem", "gorsel": "goru", "arastirmaci": "dil", "ozet": "dil"}


def upgrade(profiles: list[AgentProfile]) -> bool:
    """Eski ajan listesini kategorili hale getirir (bir kez): kategori alanı + eksik kategori ajanları.
    Değişiklik olduysa True (çağıran kaydeder)."""
    changed = False
    for p in profiles:
        if not p.category and p.id in EXISTING:
            p.category = EXISTING[p.id]
            changed = True
    have = {p.id for p in profiles}
    for new in NEW_AGENTS:
        if new.id not in have:
            profiles.append(AgentProfile(**{k: getattr(new, k) for k in AgentProfile.__dataclass_fields__}))
            changed = True
    return changed


def category_of(profile: AgentProfile | None) -> Category | None:
    return BY_ID.get(getattr(profile, "category", "") or "") if profile else None


def model_for(settings, category: Category, installed: set[str] | None = None) -> tuple[str, str] | None:
    """Kategorinin listesinden: kurulu, araç sınavını geçen (kartı yoksa Ollama'nın "tools" beyanı) ilk model.
    Pilde büyük modeller atlanır (hepsi büyükse yine ilki)."""
    from . import cards, power, specialists

    if installed is None:
        installed = set(specialists.ollama_models(settings))
    usable = []
    for m in category.models:
        if m not in installed:
            continue
        level = cards.tools_level(m)
        if level == 0 or (level is None and "tools" not in specialists._capabilities(settings.ollama_url, m)):
            continue  # ajanlar araç kullanır: kullanamayan model bu işe verilmez
        usable.append(m)
    if not usable:
        return None
    # sınavı tam geçenler (6/6) önce; "zayıf"lar (bazen yazıp geçen) yalnızca başka seçenek yoksa
    usable.sort(key=lambda m: cards.tools_level(m) == 1)
    if power.saving(settings):  # pilde büyük model çok yavaş: adındaki boyut (ör. "12b") sınırı aşmasın
        light = [m for m in usable if _params(m) <= power.BATTERY_MAX_PARAMS]
        usable = light or usable
    return "ollama", usable[0]


def _params(model: str) -> float:
    """Model adındaki boyut, milyar parametre ("qwen3.5:9b" → 9); bilinmiyorsa 0."""
    m = re.search(r"[:\-](\d+(?:\.\d+)?)b\b", model)
    return float(m.group(1)) if m else 0.0


def models_for(category: Category, info=None) -> list[str]:
    """Bu bilgisayar için önerilen modeller: listeler 12 GB ekran kartı için yazıldı, sığmayanlar çıkarılır
    (info: sysinfo.SystemInfo; yoksa liste olduğu gibi). Hiçbiri sığmazsa sığan en büyük küçük model."""
    if info is None:
        return list(category.models)
    from .sysinfo import fits

    fitting = [m for m in category.models if fits(info, SIZES.get(m, 0.0))]
    if fitting:
        return fitting
    return [next((m for m in SMALL if fits(info, SIZES[m])), SMALL[-1])]


def missing_models(category: Category, installed: set[str], info=None) -> list[tuple[str, float]]:
    """Önerilen ama kurulu olmayan modeller (model, GB)."""
    return [(m, SIZES.get(m, 0.0)) for m in models_for(category, info) if m not in installed]


def extras_state(category: Category, have: set[str]) -> list[tuple[Extra, bool]]:
    """Ek kütüphaneler ve kurulu olup olmadıkları (have: kurulu paket adları, küçük harf)."""
    return [(e, e.package.lower() in have) for e in category.extras]
