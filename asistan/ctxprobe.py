"""Bağlam ölçümü: seçili modelin ekran kartına tamamen sığdığı en büyük bağlamı bulur.

Ollama'nın bellek hesabı formülle birebir tahmin edilemediği için model farklı bağlamlarla
kısaca yüklenir ve /api/ps'deki `size_vram == size` (tamamen GPU'da) koşulu ikili aramayla denenir.
Sonuç model + ekran kartı belleği için saklanır; ikisi değişmedikçe ölçüm tekrarlanmaz.
"""

import subprocess

import httpx

STEP = 1024  # bağlam ölçüm hassasiyeti (token)
MIN_CTX = 2048


def gpu_total_mib() -> int | None:
    try:
        out = subprocess.run(
            ["nvidia-smi", "--query-gpu=memory.total", "--format=csv,noheader,nounits"],
            capture_output=True, text=True, timeout=5,
        ).stdout.split()
        return int(out[0]) if out else None
    except (OSError, ValueError, subprocess.SubprocessError):
        return None


def model_max_context(base_url: str, model: str) -> int:
    resp = httpx.post(base_url.rstrip("/") + "/api/show", json={"model": model}, timeout=15)
    resp.raise_for_status()
    info = resp.json().get("model_info", {})
    return next((int(v) for k, v in info.items() if k.endswith(".context_length")), 8192)


def probe_key(model: str, vram: int | None) -> str:
    return f"{model}|{vram or 0}"


def _fits(base_url: str, model: str, ctx: int, keep_alive: str = "2m") -> bool:
    """Modeli `ctx` bağlamıyla yükler; tamamen ekran kartında mı döndürür."""
    url = base_url.rstrip("/")
    for _ in range(2):  # arada başka bir istek modeli farklı bağlamla yüklediyse bir kez daha dene
        httpx.post(url + "/api/generate", json={
            "model": model, "prompt": "", "keep_alive": keep_alive, "options": {"num_ctx": ctx},
        }, timeout=300).raise_for_status()
        loaded = httpx.get(url + "/api/ps", timeout=10).json().get("models", [])
        m = next((m for m in loaded if m.get("name") == model or m.get("model") == model), None)
        if m and m.get("context_length", ctx) == ctx:
            return m.get("size_vram", 0) >= m.get("size", 1)
    return False


def probe(base_url: str, model: str, progress=None) -> dict:
    """{"ctx": önerilen bağlam, "max": modelin sınırı, "gpu": tamamen GPU'ya sığıyor mu, "vram": MiB}."""
    vram = gpu_total_mib()
    limit = model_max_context(base_url, model)
    if vram is None:  # ekran kartı yok: ölçülecek bir şey yok
        return {"ctx": min(8192, limit), "max": limit, "gpu": False, "vram": None}

    def say(text):
        if progress:
            progress(text)

    say(f"{MIN_CTX // 1024}K deneniyor")
    if not _fits(base_url, model, MIN_CTX):
        return {"ctx": MIN_CTX, "max": limit, "gpu": False, "vram": vram}
    lo, hi = MIN_CTX // STEP, limit // STEP  # lo sığıyor; hi'nin sığıp sığmadığı bilinmiyor
    if _fits(base_url, model, hi * STEP):
        lo = hi
    else:
        while hi - lo > 1:
            mid = (lo + hi) // 2
            say(f"{mid * STEP // 1024}K deneniyor")
            if _fits(base_url, model, mid * STEP):
                lo = mid
            else:
                hi = mid
    ctx = lo * STEP
    _fits(base_url, model, ctx, keep_alive="30m")  # sohbet bu bağlamla başlasın, yeniden yükleme olmasın
    return {"ctx": ctx, "max": limit, "gpu": True, "vram": vram}
