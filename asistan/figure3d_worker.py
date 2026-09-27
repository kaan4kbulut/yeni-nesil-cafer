"""Resimden 3D figür (TripoSR): ajanların Python'unda ayrı süreçte çalışır (figure3d.run başlatır).

Akış: resmin arka planı silinir (kenardan dolan zemin rengi; saydam PNG'de saydamlık) → figür kare bir tuvale ortalanır
→ TripoSR üç düzlemli temsili çıkarır → yoğunluk ızgarası (ekran kartında 256³, işlemcide 160³) → marching cubes
(PyMCubes) → en büyük parça, ölçek, düz taban ve ayak → decor3d.save (tablaya sığdırma, STL + 3MF, kapalılık denetimi).
Kullanım: python figure3d_worker.py '<json>'  →  stdout'a tek satır JSON.
"""

import json
import sys
import time
import types
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))  # decor3d aynı klasörde
import decor3d  # noqa: E402

THRESHOLD = 25.0  # TripoSR'ın yüzey eşiği (yoğunluk)
# transformers 5, ViT katmanlarını yeniden adlandırdı (hesap aynı); TripoSR ağırlıkları eski adlarla kayıtlı.
# Yeni sürüm kuruluysa yüklerken çevrilir (transformers 5.17 ile denendi, 2026-09-27)
_VIT_RENAMES = [
    (r"\.encoder\.layer\.(\d+)\.attention\.attention\.query\.", r".layers.\1.attention.q_proj."),
    (r"\.encoder\.layer\.(\d+)\.attention\.attention\.key\.", r".layers.\1.attention.k_proj."),
    (r"\.encoder\.layer\.(\d+)\.attention\.attention\.value\.", r".layers.\1.attention.v_proj."),
    (r"\.encoder\.layer\.(\d+)\.attention\.output\.dense\.", r".layers.\1.attention.o_proj."),
    (r"\.encoder\.layer\.(\d+)\.intermediate\.dense\.", r".layers.\1.mlp.fc1."),
    (r"\.encoder\.layer\.(\d+)\.output\.dense\.", r".layers.\1.mlp.fc2."),
    (r"\.encoder\.layer\.(\d+)\.", r".layers.\1."),  # layernorm_before / layernorm_after
]


class FigureError(Exception):
    pass


def cut_out(path: str, max_px: int = 1024):
    """Resmi yükler, figürü zeminden ayırır: RGBA (zemin saydam). Saydam PNG'de saydamlık kullanılır; değilse kenardan
    başlayıp keskin bir sınıra (nesnenin dış hattına) çarpana kadar yayılan yumuşak geçişli bölge zemin sayılır: renk
    geçişli fon, aydınlık yer düzlemi ve gölge de zemindir. İlk yöntem (kenar rengine benzeyen bölge) beyaz fonda beyaz
    kediyi yer düzlemiyle birleştirip modelden kama biçimli bir blok çıkarmıştı (2026-09-27)."""
    from PIL import Image, ImageOps
    from scipy import ndimage

    img = ImageOps.exif_transpose(Image.open(path))
    img.thumbnail((max_px, max_px))
    rgba = np.asarray(img.convert("RGBA"), dtype=np.float64) / 255.0
    alpha = rgba[..., 3]
    if alpha.min() < 0.5 and alpha.mean() < 0.97:  # zaten saydam zeminli
        mask = alpha > 0.5
    else:
        rgb = rgba[..., :3]
        smooth = ndimage.gaussian_filter(rgb, sigma=(1.5, 1.5, 0))
        grad = np.sqrt(sum(ndimage.sobel(smooth[..., c], axis=a) ** 2 for c in range(3) for a in (0, 1)))
        thr = max(0.04, float(np.percentile(grad, 75)))  # nesnenin dış hattı: resmin en keskin %25'i
        labels, _ = ndimage.label(grad < thr)
        edge = np.unique(np.concatenate([labels[0], labels[-1], labels[:, 0], labels[:, -1]]))
        background = np.isin(labels, edge[edge > 0])
        opening = max(2, round(max(rgb.shape[:2]) / 250))  # zemin çizgisi gibi ince uzantılar kopsun
        mask = ndimage.binary_fill_holes(ndimage.binary_opening(~background, iterations=opening))
        # nesnenin arkasından geçen ufuk / masa kenarı: kenardan gelip gövdeye ulaşan İNCE yapı nesneden ayrılır
        thin = mask & (ndimage.distance_transform_edt(mask) < max(rgb.shape[:2]) * 0.015)
        parts, _ = ndimage.label(thin)
        rim = np.unique(np.concatenate([parts[0], parts[-1], parts[:, 0], parts[:, -1]]))
        mask &= ~np.isin(parts, rim[rim > 0])
    labels, n = ndimage.label(mask)
    if n == 0 or mask.mean() < 0.01:
        raise FigureError("resimde figür bulunamadı: düz zemin önünde tek bir nesne olmalı")
    sizes = ndimage.sum(mask, labels, range(1, n + 1))
    mask = labels == (int(np.argmax(sizes)) + 1)  # en büyük nesne
    top, bottom, left, right = (bool(line.any()) for line in (mask[0], mask[-1], mask[:, 0], mask[:, -1]))
    # gerçek nesneler kenara değmez (alta dayanan büst yalnızca alta); karşılıklı iki kenara birden değen şey ufuk,
    # masa kenarı ya da yer düzlemidir: uydurma blok üretme, resmi yeniletsin
    if mask.mean() > 0.8 or (left and right) or (top and bottom):
        raise FigureError("figür zeminden ayrılamadı: resmi, figürden farklı renkte düz bir zemin önünde (yer düzlemi ve "
                          "gölge olmadan, ör. 'plain uniform mid-gray background, no floor, no shadow') yeniden üretin")
    out = np.dstack([rgba[..., :3], mask.astype(np.float64)])
    return Image.fromarray((out * 255).astype(np.uint8), "RGBA")


def prepare(rgba, ratio: float = 0.85, size: int = 512):
    """TripoSR'ın beklediği girdi: figür kare tuvalin %85'ini kaplar, zemin gri (0.5)."""
    from PIL import Image

    a = np.asarray(rgba)
    ys, xs = np.nonzero(a[..., 3] > 0)
    crop = a[ys.min():ys.max() + 1, xs.min():xs.max() + 1]
    side = int(max(crop.shape[:2]) / ratio)
    canvas = np.zeros((side, side, 4), dtype=np.uint8)
    y0, x0 = (side - crop.shape[0]) // 2, (side - crop.shape[1]) // 2
    canvas[y0:y0 + crop.shape[0], x0:x0 + crop.shape[1]] = crop
    img = np.asarray(Image.fromarray(canvas, "RGBA").resize((size, size), Image.LANCZOS), dtype=np.float32) / 255.0
    rgb = img[..., :3] * img[..., 3:4] + (1 - img[..., 3:4]) * 0.5
    return Image.fromarray((rgb * 255).astype(np.uint8), "RGB")


def load_model(code_dir: str, model_dir: str, device: str):
    # TripoSR'ın içe aktardığı ama kullanmadığımız paketler: torchmcubes (derleme ister; marching cubes'u PyMCubes
    # yapar) ve rembg (arka planı cut_out siler). Kurulu değillerse sahte modül yeter.
    for name in ("torchmcubes", "rembg"):
        try:
            __import__(name)
        except ImportError:
            fake = types.ModuleType(name)
            fake.marching_cubes = fake.new_session = fake.remove = None
            sys.modules[name] = fake
    sys.path.insert(0, code_dir)
    import tsr.models.tokenizers.image as tokenizer_image
    from tsr.system import TSR

    import re

    import torch
    from omegaconf import OmegaConf

    dino = str(Path(model_dir) / "dino-config.json")  # internete gitmesin: yapı dosyası kurulumda indi
    tokenizer_image.hf_hub_download = lambda repo_id, filename, **kw: dino
    cfg = OmegaConf.load(Path(model_dir) / "config.yaml")  # TSR.from_pretrained'in yaptığı, ad çevirisiyle
    OmegaConf.resolve(cfg)
    model = TSR(cfg)
    ckpt = torch.load(Path(model_dir) / "model.ckpt", map_location="cpu", weights_only=True)
    expected = set(model.state_dict())
    if any(k not in expected for k in ckpt):
        for old, new in _VIT_RENAMES:
            ckpt = {(re.sub(old, new, k) if k not in expected else k): v for k, v in ckpt.items()}
    model.load_state_dict(ckpt)  # tam eşleşme: bir ad tutmazsa açık hata
    model.renderer.set_chunk_size(8192)
    return model.to(device)


def density_mesh(model, scene_code, resolution: int) -> tuple[np.ndarray, np.ndarray]:
    """Yoğunluk ızgarası → marching cubes; köşeler TripoSR'ın dünya koordinatlarında (z yukarı)."""
    import mcubes
    import torch

    r = float(model.renderer.cfg.radius)
    axis = torch.linspace(-r, r, resolution)
    grid = torch.stack(torch.meshgrid(axis, axis, axis, indexing="ij"), dim=-1).reshape(-1, 3)
    with torch.no_grad():
        density = model.renderer.query_triplane(model.decoder, grid.to(scene_code.device), scene_code)["density_act"]
    vol = density.reshape(resolution, resolution, resolution).float().cpu().numpy()
    vol = np.pad(vol, 1, constant_values=0.0)  # kenara değen yüzey de kapansın
    verts, faces = mcubes.marching_cubes(vol, THRESHOLD)
    if len(faces) == 0:
        raise FigureError("model bu resimden bir şekil çıkaramadı; figürü net, tek ve ortada olan bir resim deneyin")
    verts = (verts - 1) / (resolution - 1) * 2 * r - r
    return verts, faces.astype(np.int64)


def printable(verts: np.ndarray, faces: np.ndarray, height: float, base: bool):
    """Ağı baskıya hazırlar: kapalı en büyük parça, ölçek (yükseklik mm), düz taban, isteğe bağlı ayak."""
    import manifold3d as mf
    import trimesh

    tm = trimesh.Trimesh(verts, faces)  # yinelenen köşeler birleşir
    trimesh.repair.fix_normals(tm)
    # ızgaradan gelen basamaklı doku (işlemcide 160³) hacmi koruyan Taubin yumuşatmasıyla giderilir; bağlantı değişmez
    trimesh.smoothing.filter_taubin(tm, lamb=0.5, nu=-0.53, iterations=12)
    try:
        body = decor3d._manifold(tm.vertices, tm.faces)
    except decor3d.DecorError:
        # marching cubes'un belirsiz hücreleri kenarı ikiden çok yüze bağlayabiliyor: dışbükey olmayan onarım
        tm.merge_vertices()
        trimesh.repair.fill_holes(tm)
        body = decor3d._manifold(tm.vertices, tm.faces)
    pieces = sorted(body.decompose(), key=lambda m: m.volume(), reverse=True)
    body = pieces[0]
    lo, hi = np.array(body.bounding_box()[:3]), np.array(body.bounding_box()[3:])
    s = height / (hi[2] - lo[2])
    body = body.translate(tuple(-(lo + hi) / 2 * [1, 1, 0] - [0, 0, lo[2]])).scale((s, s, s))
    notes = []
    cut = height * 0.03  # yuvarlak alt kısım kesilir: figür tablaya düz otursun
    body = body.trim_by_plane((0, 0, 1), cut).translate((0, 0, -cut))
    if base:
        foot = body.slice(0.3)
        if foot.is_empty():
            foot = body.project()
        pad = max(3.0, height * 0.04)
        plate = foot.hull().offset(pad, mf.JoinType.Round, circular_segments=64).extrude(3.0)
        body = body.translate((0, 0, 2.6)) + plate  # 0.4 mm iç içe: tek parça
        notes.append("Figürün altına 3 mm'lik ayak eklendi (devrilmesin, tablaya iyi yapışsın).")
    if len(pieces) > 1:
        notes.append(f"Modelden {len(pieces) - 1} küçük kopuk parça atıldı.")
    notes += ["Figür organik biçimli: dilimleyicide ağaç destek (tree support) açın; 0.12–0.16 mm katman ayrıntıyı "
              "iyi çıkarır.", "Ayrıntı resimden tahmin edilir: arka taraf ve ince parçalar (kuyruk, bıyık) sadeleşebilir."]
    return body, notes


def main(args: dict) -> dict:
    import torch

    t0 = time.time()
    device = "cuda" if args.get("gpu") and torch.cuda.is_available() else "cpu"
    image = prepare(cut_out(args["image"]))

    def shape(dev: str):
        model = load_model(args["code"], args["model"], dev)
        with torch.no_grad():
            scene_codes = model([image], device=dev)
        return density_mesh(model, scene_codes[0], 256 if dev == "cuda" else 160)

    extra = []
    try:
        verts, faces = shape(device)
    except torch.OutOfMemoryError:
        # kartı başka bir program tutuyor (Ollama modeli, oyun…): hata verme, işlemcide yap (~25 sn)
        torch.cuda.empty_cache()
        device = "cpu"
        verts, faces = shape(device)
        extra.append("Ekran kartında yer yoktu (başka bir program kullanıyordu); figür işlemcide yapıldı.")
    body, notes = printable(verts, faces, float(args.get("height") or 100.0), bool(args.get("base", True)))
    notes = extra + notes
    bed = [float(x) for x in str(args.get("bed") or "220x220x250").lower().split("x")]
    info = decor3d.save(body, notes, bed, args["out"], infill=0.15)
    prepared = Path(args["out"]).with_name(Path(args["out"]).name + "-girdi.png")
    image.save(prepared)  # modelin gördüğü resim: sonuç beklenmedikse neden anlaşılsın
    info.update({"device": device, "seconds": round(time.time() - t0, 1), "input": str(prepared)})
    return info


if __name__ == "__main__":
    try:
        print(json.dumps(main(json.loads(sys.argv[1])), ensure_ascii=False))
    except (FigureError, decor3d.DecorError) as e:
        print(json.dumps({"error": str(e)}, ensure_ascii=False))
