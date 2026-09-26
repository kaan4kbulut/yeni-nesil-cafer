"""Uzman modeller: asistanın kendi yapamadığı işleri (resim görme, derin düşünme, kod) başka modellere sordurur.

Her rol için ayarlardan seçilen model kullanılır; seçilmemişse kurulu modellerin yeteneklerine
(Ollama /api/show "capabilities") bakılarak en uygunu otomatik bulunur.
"""

import base64
import re
import mimetypes
from functools import lru_cache
from pathlib import Path

import httpx

from .config import Settings
from .connections import ANTHROPIC_KEY, Connection
from .keystore import get_secret

ROLES = {
    "vision": "görsel — resim, fotoğraf, ekran görüntüsü, taranmış belge",
    "reasoning": "derin düşünme — zor problem, matematik, plan, karar",
    "code": "kod — yazılım, hata ayıklama, betik",
    "general": "genel — ikinci görüş",
}
IMAGE_SUFFIXES = {".png", ".jpg", ".jpeg", ".webp", ".gif", ".bmp"}
# ad parçasına göre tahmin (yetenek bilgisi vermeyen sağlayıcılar için)
_NAME_HINTS = {
    "reasoning": ("deepseek-r1", "qwq", "phi4-reasoning", "magistral", "gpt-oss"),
    "code": ("coder", "codestral", "codellama", "devstral", "starcoder"),
}


@lru_cache(maxsize=64)
def _capabilities(base_url: str, model: str) -> tuple:
    try:
        resp = httpx.post(base_url.rstrip("/") + "/api/show", json={"model": model}, timeout=10)
        resp.raise_for_status()
        return tuple(resp.json().get("capabilities") or ())
    except Exception:
        return ()


def ollama_models(settings: Settings) -> list[str]:
    try:
        resp = httpx.get(settings.ollama_url.rstrip("/") + "/api/tags", timeout=5)
        resp.raise_for_status()
        return [m["name"] for m in resp.json().get("models", [])]
    except Exception:
        return []


def vision_models(settings: Settings) -> list[str]:
    return [m for m in ollama_models(settings) if "vision" in _capabilities(settings.ollama_url, m)]


CLAUDE_CODE = ("cli:claude", "claude-code")  # (sağlayıcı, model): kullanıcının Claude aboneliğiyle Claude Code
# Claude Code'un çalışabildiği modeller (--model takma adları); "claude-code": Claude Code'un kendi varsayılanı
CLAUDE_CODE_MODELS = [("claude-code", "varsayılan"), ("opus", "en yetenekli"), ("fable", "en güçlü"),
                      ("sonnet", "dengeli, hızlı"), ("haiku", "en hızlı, en az kullanım")]


def claude_code_available() -> bool:
    import shutil

    return shutil.which("claude") is not None


def claude_code(prompt: str, cwd: str, system: str = "", edits: bool = False, cancelled=None,
                timeout: int = 1800, model: str = "") -> str:
    """Claude Code'u komut satırından çalıştırır (`claude -p`); yanıt metnini döndürür.

    edits=True: çalışma klasöründeki dosyaları düzenleyebilir (komut çalıştırmak yine kapalı).
    cancelled: çağrılabilir; True dönerse süreç durdurulur ve Cancelled benzeri bir hata atılır.
    """
    import os
    import shutil
    import subprocess
    import time

    exe = shutil.which("claude")
    if exe is None:
        raise RuntimeError("Claude Code bulunamadı. Kurmak için: https://claude.com/claude-code")
    cmd = [exe, "-p", prompt, "--output-format", "text"]
    if model and model != CLAUDE_CODE[1]:
        cmd += ["--model", model]
    if edits:
        cmd += ["--permission-mode", "acceptEdits"]
    if system:
        cmd += ["--append-system-prompt", system]
    # başka bir Claude Code oturumundan başlatıldıysa iç içe oturum sayılmasın
    env = {k: v for k, v in os.environ.items() if not k.startswith("CLAUDECODE") and k != "CLAUDE_CODE_ENTRYPOINT"}
    proc = subprocess.Popen(cmd, cwd=cwd, env=env, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                            stderr=subprocess.PIPE, text=True)
    start = time.time()
    while True:
        try:
            out, err = proc.communicate(timeout=0.5)
            break
        except subprocess.TimeoutExpired:
            if (cancelled and cancelled()) or time.time() - start > timeout:
                proc.kill()
                proc.communicate()
                raise InterruptedError("Claude Code durduruldu")
    if proc.returncode != 0:
        raise RuntimeError(f"Claude Code hatası: {(err or out).strip()[:400]}")
    return out.strip()


def _claude_available() -> bool:
    import os

    return bool(get_secret(ANTHROPIC_KEY) or os.environ.get("ANTHROPIC_API_KEY"))


def _cloud_fallback(role: str) -> tuple[str, str] | None:
    """Bağlı bulut sağlayıcılarından role uygun bir model (Gemini > OpenAI > diğer)."""
    from .connections import load_connections

    from . import catalog

    for c in load_connections():
        if c.kind != "llm" or not c.enabled:
            continue
        provider = catalog.by_host(c.base_url)
        if provider is None:
            continue
        # katalogdaki öne çıkan model (kod rolünde kod listesi), hesapta varsa
        featured = [m for m, _ in (provider.code if role == "code" else provider.chat)]
        m = next((m for m in featured if not c.models or m in c.models), None)
        if m:
            return f"api:{c.id}", m
    return None


def resolve(settings: Settings, role: str) -> tuple[str, str] | None:
    """Rol için (sağlayıcı, model) — ayar > kurulu yerel model > Claude > bağlı bulut (Gemini, OpenAI)."""
    if role == "general" and settings.extra.get("writer_model"):
        return "ollama", settings.extra["writer_model"]  # işçi model çalışırken: metni kullanıcının modeli yazar
    chosen = settings.specialists.get(role) or (settings.defaults.get("code") if role == "code" else "")
    if chosen and "|" in chosen:
        provider, model = chosen.split("|", 1)
        return provider, model
    local = ollama_models(settings)
    if role == "vision":
        found = [m for m in local if "vision" in _capabilities(settings.ollama_url, m)]
        # genel görme modelleri önce (OCR modelleri yazı okur, sayfa düzenini / resmi anlatamaz); sonra araç
        # sınavını geçen (model kartı) ve adındaki boyutu büyük olan
        from . import cards

        from .model_updates import is_uncensored

        def rank(m):  # sansürsüz modeller sona: kart yokken (yeni kurulum) adı önce gelen seçilmesin
            size = re.search(r":(\d+(?:\.\d+)?)b", m)
            return ("ocr" in m, is_uncensored(m), -(cards.tools_level(m) or 0), -(float(size.group(1)) if size else 0))
        found.sort(key=rank)
        if found:
            return "ollama", found[0]
    elif role in _NAME_HINTS:
        found = [m for m in local if any(h in m for h in _NAME_HINTS[role])]
        if found:
            return "ollama", found[0]
    if _claude_available():
        return "claude", settings.claude_model
    cloud = _cloud_fallback(role)
    if cloud:
        return cloud
    if role in ("general", "reasoning", "code") and local:
        return "ollama", settings.ollama_model
    return None


def _ctx_for(settings: Settings, model: str) -> int:
    from . import power

    return power.num_ctx(settings) if model == settings.ollama_model else 8192


def _image_parts(paths: list[Path]) -> list[tuple[str, str]]:
    """[(mime, base64)]"""
    out = []
    for p in paths:
        mime = mimetypes.guess_type(p.name)[0] or "image/png"
        out.append((mime, base64.b64encode(p.read_bytes()).decode()))
    return out


def ask(settings: Settings, connections: list[Connection], provider: str, model: str, prompt: str,
        images: list[Path] | None = None, system: str = "", schema: dict | None = None) -> str:
    """Tek seferlik soru; yanıt metnini döndürür. schema verilirse yanıt JSON istenir (yerelde düşünmeden)."""
    images = images or []
    parts = _image_parts(images)
    system = system or ("You are a specialist helping another AI assistant. Answer precisely and completely in the "
                        "language of the question. Describe everything relevant; if text is visible in an image, "
                        "transcribe it.")
    if provider == "ollama":
        msg = {"role": "user", "content": prompt}
        if parts:
            msg["images"] = [b64 for _, b64 in parts]
        resp = httpx.post(settings.ollama_url.rstrip("/") + "/api/chat", json={
            "model": model, "stream": False, "keep_alive": "10m",
            "messages": [{"role": "system", "content": system}, msg],
            # ana modelle aynıysa onun bağlamı: farklı bağlam modeli yeniden yükletir
            "options": {"num_ctx": _ctx_for(settings, model)},
            **({"format": schema, "think": False} if schema else {}),
        }, timeout=httpx.Timeout(600, connect=10))
        if resp.status_code != 200:
            raise RuntimeError(f"{model} hatası ({resp.status_code}): {resp.text[:300]}")
        return resp.json().get("message", {}).get("content", "").strip()
    if provider == "claude":
        import anthropic

        key = get_secret(ANTHROPIC_KEY)
        client = anthropic.Anthropic(api_key=key) if key else anthropic.Anthropic()
        content = [{"type": "image", "source": {"type": "base64", "media_type": mime, "data": b64}}
                   for mime, b64 in parts] + [{"type": "text", "text": prompt}]
        resp = client.messages.create(model=model, max_tokens=4000, system=system,
                                      messages=[{"role": "user", "content": content}])
        return "".join(b.text for b in resp.content if b.type == "text").strip()
    if provider == CLAUDE_CODE[0]:
        return claude_code(prompt, settings.workspace, system, model=model)
    if provider.startswith("api:"):
        conn = next((c for c in connections if c.id == provider[4:]), None)
        if conn is None:
            raise RuntimeError("Uzman modelin API bağlantısı silinmiş.")
        content = [{"type": "text", "text": prompt}] + [
            {"type": "image_url", "image_url": {"url": f"data:{mime};base64,{b64}"}} for mime, b64 in parts]
        headers = {"Authorization": f"Bearer {conn.key}"} if conn.key else {}
        resp = httpx.post(conn.base_url.rstrip("/") + "/chat/completions", headers=headers, json={
            "model": model, "messages": [{"role": "system", "content": system},
                                         {"role": "user", "content": content}],
            **({"response_format": {"type": "json_object"}} if schema else {}),
        }, timeout=httpx.Timeout(600, connect=15))
        if resp.status_code != 200:
            raise RuntimeError(f"{conn.name} hatası ({resp.status_code}): {resp.text[:300]}")
        return resp.json()["choices"][0]["message"]["content"].strip()
    raise RuntimeError(f"Bilinmeyen sağlayıcı: {provider}")


def describe(settings: Settings, role: str) -> str:
    found = resolve(settings, role)
    if not found:
        return "yok"
    provider = found[0]
    if provider.startswith("api:"):
        from .connections import load_connections

        conn = next((c for c in load_connections() if c.id == provider[4:]), None)
        provider = conn.name if conn else "api"
    return f"{found[1]} ({provider})"
