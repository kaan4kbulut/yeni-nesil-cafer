"""Ollama bağlam sınırı, model başına (K12-C3).

Bağlam ölçümü (`ctxprobe.probe`, modeli yükleyip ikili arama) yalnızca sohbet modeli için yapılır ve tek bir genel ayar
(`ollama_num_ctx`) çıkarır. Yönlendiricinin seçtiği başka bir model (14B yönetici) o bağlamla karta sığmayınca işlemciye
taşıyor ve her görev zaman aşımına düşüyordu (sınav 2026-09-28: 2/15). Burası ölçülmemiş model için VRAM'e göre TAHMİN
yapar: ağırlık boyutu (`/api/tags`) + KV önbelleği (`/api/show`: katman, KV baş sayısı, gömme; f16). Sonuç
`ayarlar.ctx_probe`'a yazılır (bir sonraki `save` ile kalıcı) ve genel ayarı yalnızca AŞAĞI çeker.
"""

import subprocess
import time

import httpx

STEP = 1024  # bağlam hassasiyeti (token)
MIN_CTX = 2048
# Hiçbir zaman bunun altına inilmez: sistem talimatı + araç tanımları ~4.1–5.6K token (agent.lean). Karta tam sığmayan
# model bir kısmıyla işlemciye taşar: yavaşlar ama doğru çalışır.
FLOOR_CTX = 8192
_vram_onbellek: list = []  # toplam VRAM değişmez: nvidia-smi bir kez (num_ctx sık çağrılır)
_tahmin_hatalari: dict = {}  # "model|vram" → zaman: Ollama kapalıyken her etiket güncellemesinde yeniden denenmez


def gpu_total_mib(yenile: bool = False) -> int | None:
    if _vram_onbellek and not yenile:
        return _vram_onbellek[0]
    try:
        out = subprocess.run(
            ["nvidia-smi", "--query-gpu=memory.total", "--format=csv,noheader,nounits"],
            capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=5,
        ).stdout.split()
        deger = int(out[0]) if out else None
    except (OSError, ValueError, subprocess.SubprocessError):
        deger = None
    _vram_onbellek[:] = [deger]
    return deger


def probe_key(model: str, vram: int | None) -> str:
    return f"{model}|{vram or 0}"


def tahmin(base_url: str, model: str, vram_mib: int | None) -> dict:
    """Modeli yüklemeden VRAM'e göre bağlam tahmini: {"ctx", "max", "gpu", "vram", "tahmin": True}."""
    url = base_url.rstrip("/")
    resp = httpx.post(url + "/api/show", json={"model": model}, timeout=15)
    resp.raise_for_status()
    info = resp.json().get("model_info", {}) or {}

    def al(sonek: str, varsayilan: int) -> int:
        return next((int(v) for k, v in info.items() if k.endswith(sonek)), varsayilan)

    limit = al(".context_length", 8192)
    if not vram_mib:
        return {"ctx": min(FLOOR_CTX, limit), "max": limit, "gpu": False, "vram": vram_mib, "tahmin": True}
    tags = httpx.get(url + "/api/tags", timeout=10)
    tags.raise_for_status()
    boyut = next((int(m.get("size") or 0) for m in tags.json().get("models", [])
                  if m.get("name") == model or m.get("model") == model), 0)
    katman, bas = al(".block_count", 32), al(".attention.head_count", 32)
    kv, gomme = al(".attention.head_count_kv", bas), al(".embedding_length", 4096)
    token_basi = 2 * katman * kv * (gomme // max(bas, 1)) * 2  # K + V, f16
    if boyut <= 0 or token_basi <= 0:
        ctx, gpu = limit, True
    else:
        kullanilabilir = vram_mib * 1024 * 1024 * 0.9 - boyut - 512 * 1024 * 1024  # %10 pay + sürücü/tampon
        ctx = int(max(0, kullanilabilir) // token_basi) // STEP * STEP
        gpu = ctx >= MIN_CTX
    ctx = max(min(ctx, limit), min(FLOOR_CTX, limit))
    return {"ctx": ctx, "max": limit, "gpu": gpu, "vram": vram_mib, "tahmin": True}


def model_ctx(ayarlar, tahmin_fn=None, vram_fn=None) -> int:
    """`ayarlar.ollama_model` için bağlam: ölçüm (`ctx_probe`) varsa o; yoksa tahmin bir kez (önbelleğe); Ollama'ya
    ulaşılamazsa 10 dk denenmez ve genel ayar (`ollama_num_ctx`) kullanılır. Sınır genel ayarı yalnızca aşağı çeker."""
    tahmin_fn, vram_fn = tahmin_fn or tahmin, vram_fn or gpu_total_mib
    genel = int(getattr(ayarlar, "ollama_num_ctx", 0) or 0)
    model = getattr(ayarlar, "ollama_model", "") or ""
    probe = getattr(ayarlar, "ctx_probe", None)
    if not genel or not model or not isinstance(probe, dict):
        return genel
    vram = vram_fn()
    if not vram:  # ekran kartı yok: ölçüm/tahmin anlamsız, kullanıcının ayarı
        return genel
    key = probe_key(model, vram)
    kayit = probe.get(key)
    if not isinstance(kayit, dict):
        if time.time() - _tahmin_hatalari.get(key, 0) < 600:
            return genel
        try:
            kayit = tahmin_fn(getattr(ayarlar, "ollama_url", "http://127.0.0.1:11434"), model, vram)
        except Exception:
            _tahmin_hatalari[key] = time.time()
            return genel
        probe[key] = kayit
    ctx = int(kayit.get("ctx") or 0)
    return min(genel, max(ctx, FLOOR_CTX)) if ctx else genel
