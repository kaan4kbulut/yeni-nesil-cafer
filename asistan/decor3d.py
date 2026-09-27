"""Süs modelleri: vazo, abajur, lamba, süs topu, geometrik süs, kabartma, litofan, siluet figür (STL + 3MF).

Yerel modeller süs geometrisini kendileri kodlayamıyor: "girdaplı lamba" isteğinde düz bir küre, "gerçekçi ateş"
isteğinde delikli, tablaya sığmayan yüzeyler çıktı (2026-09-27). Burada geometri test edilmiş koddan gelir; model
yalnızca şekli ve birkaç ölçüyü seçer (tools.make_decor_model). Her çıktı manifold3d ile kapalı yüzeylidir (baskıya
uygun) ve tablaya sığmazsa orantılı küçültülür.

Ajanların Python'unda ayrı süreçte çalışır (numpy, manifold3d, trimesh, pillow, contourpy pakette gelir; programın
kendi süreci bunları yüklemez). Kullanım: python decor3d.py '<json>'  →  stdout'a tek satır JSON sonuç.
Birimler milimetre; model tablaya oturur (en alt z = 0) ve x, y'de ortalanır.
"""

import json
import math
import sys
from pathlib import Path

import manifold3d as mf
import numpy as np

SHAPES = ("vazo", "abajur", "girdap_lamba", "sus_topu", "burgulu_kule", "yildiz", "kafes_kure", "kabartma",
          "litofan", "litofan_lamba", "siluet")
PROFILES = ("klasik", "lale", "silindir", "koni", "kum_saati", "top", "sise")
PATTERNS = ("yuvarlak", "yivli", "yildiz", "cokgen")
PLA = 1.24  # g/cm³

# vazo / abajur profilleri: (yükseklik oranı, en geniş yere göre yarıçap oranı); aralar yumuşak eğriyle doldurulur
_PROFILE_POINTS = {
    "klasik": [(0, 0.62), (0.3, 1.0), (0.68, 0.62), (0.88, 0.5), (1, 0.6)],
    "lale": [(0, 0.5), (0.35, 0.72), (0.75, 1.0), (1, 0.92)],
    "silindir": [(0, 1.0), (1, 1.0)],
    "koni": [(0, 0.6), (1, 1.0)],
    "kum_saati": [(0, 1.0), (0.5, 0.62), (1, 1.0)],
    "top": [(0, 0.55), (0.45, 1.0), (0.85, 0.6), (1, 0.5)],
    "sise": [(0, 0.88), (0.45, 1.0), (0.68, 0.55), (0.85, 0.3), (1, 0.33)],
}


class DecorError(Exception):
    pass


# ---------------------------------------------------------------- ağ yardımcıları

def _manifold(vertices, faces) -> mf.Manifold:
    """Köşe ve üçgenlerden Manifold; yüzler içe bakıyorsa çevrilir, kapalı değilse hata."""
    v = np.asarray(vertices, dtype=np.float64)
    f = np.asarray(faces, dtype=np.int64)
    a, b, c = v[f[:, 0]], v[f[:, 1]], v[f[:, 2]]
    if np.einsum("ij,ij->i", a, np.cross(b, c)).sum() < 0:  # işaretli hacim negatif: yüzler ters
        f = f[:, ::-1]
    m = mf.Manifold(mf.Mesh(vert_properties=v.astype(np.float32), tri_verts=f.astype(np.uint32)))
    if m.status() != mf.Error.NoError or m.is_empty():
        raise DecorError(f"geometri kapalı bir yüzey oluşturmadı ({m.status()})")
    return m


def _loft(rings: np.ndarray, bottom=None, top=None) -> mf.Manifold:
    """Halkaları (katman × nokta × 3, alttan üste, açı sırasıyla) yüzeyle birleştirir; uçlar bir merkez noktasına
    bağlanarak kapanır (verilmezse halkanın ağırlık merkezi). Halkalar eksene göre yıldız biçimli olmalı."""
    rings = np.asarray(rings, dtype=np.float64)
    nz, n = rings.shape[:2]
    verts = rings.reshape(-1, 3)
    i, j = np.meshgrid(np.arange(nz - 1), np.arange(n), indexing="ij")
    a = (i * n + j).ravel()
    b = (i * n + (j + 1) % n).ravel()
    c = ((i + 1) * n + (j + 1) % n).ravel()
    d = ((i + 1) * n + j).ravel()
    faces = [np.c_[a, b, c], np.c_[a, c, d]]
    cb = len(verts)
    cen_b = rings[0].mean(axis=0) if bottom is None else bottom
    cen_t = rings[-1].mean(axis=0) if top is None else top
    verts = np.vstack([verts, cen_b, cen_t])
    jj = np.arange(n)
    faces.append(np.c_[np.full(n, cb), (jj + 1) % n, jj])  # alt kapak
    last = (nz - 1) * n
    faces.append(np.c_[np.full(n, cb + 1), last + jj, last + (jj + 1) % n])  # üst kapak
    return _manifold(verts, np.vstack(faces))


def _profile(name: str):
    pts = np.array(_PROFILE_POINTS[name], dtype=float)
    try:
        from scipy.interpolate import PchipInterpolator
        return PchipInterpolator(pts[:, 0], pts[:, 1])
    except ImportError:  # scipy yoksa doğrusal (kavisler köşeli olur ama çalışır)
        return lambda t: np.interp(t, pts[:, 0], pts[:, 1])


def _section(phi: np.ndarray, pattern: str, sides: int) -> np.ndarray:
    """Yatay kesitin açıya göre göreli yarıçapı (en çok 1)."""
    n = max(3, int(sides))
    if pattern == "yivli":  # yumuşak dalgalar
        return 1 - 0.09 * (0.5 - 0.5 * np.cos(n * phi))
    if pattern == "yildiz":  # sivri uçlar, yuvarlak aralar
        return 0.72 + 0.28 * np.abs(np.cos(n * phi / 2)) ** 3
    if pattern == "cokgen":  # düzgün çokgen (köşeler 1)
        step = 2 * np.pi / n
        return np.cos(np.pi / n) / np.cos((phi % step) - np.pi / n)
    return np.ones_like(phi)


def _rotation_to(d: np.ndarray) -> np.ndarray:
    """z eksenini d yönüne çeviren 3×3 dönme."""
    z = np.array([0.0, 0.0, 1.0])
    d = d / np.linalg.norm(d)
    v, c = np.cross(z, d), float(z @ d)
    if np.linalg.norm(v) < 1e-9:
        return np.eye(3) if c > 0 else np.diag([1.0, -1.0, -1.0])
    k = np.array([[0, -v[2], v[1]], [v[2], 0, -v[0]], [-v[1], v[0], 0]])
    return np.eye(3) + k + k @ k * (1 / (1 + c))


def _cylinder(height: float, r_low: float, r_high: float, segments: int = 96) -> mf.Manifold:
    """Silindir; köşeleri gövdenin açı ızgarasıyla çakışmasın diye biraz döndürülmüş. Tam çakışan köşelerde birleşim
    aynı yerde iki ayrı nokta bırakıyor, STL'de açık kenar oluyordu (süs topu: 240 = 5 × 48 dilim, 2026-09-27)."""
    return mf.Manifold.cylinder(height, r_low, r_high, segments).rotate((0, 0, 3.7))


def _torus(ring_r: float, tube_r: float) -> mf.Manifold:
    """Dik duran askı halkası (x-z düzleminde, merkez başlangıçta)."""
    t = mf.CrossSection.circle(tube_r, 24).translate((ring_r, 0)).revolve(48)
    return t.rotate((90, 0, 3.7))


# ---------------------------------------------------------------- şekiller

def _vase_rings(height, radius, prof, pattern, sides, twist_deg, z_from, z_to, inset, nz, n=288):
    phi = np.linspace(0, 2 * np.pi, n, endpoint=False)
    sec = _section(phi, pattern, sides)
    rings = []
    for z in np.linspace(z_from, z_to, nz):
        t = min(max(z / height, 0.0), 1.0)
        rho = np.maximum(radius * float(prof(t)) * sec - inset, 1.0)
        ang = phi + math.radians(twist_deg) * t
        rings.append(np.c_[rho * np.cos(ang), rho * np.sin(ang), np.full(n, z)])
    return np.array(rings)


def vase(p: dict, lamp: bool) -> tuple[mf.Manifold, list[str]]:
    h = p["height"] or (160.0 if lamp else 150.0)
    w = p["width"] or (120.0 if lamp else 90.0)
    prof = _profile(p["profile"] or ("lale" if lamp else "klasik"))
    pattern = p["pattern"] or "yivli"
    sides = p["sides"] or (16 if lamp else 12)
    twist = p["twist"] if p["twist"] is not None else (60.0 if lamp else 0.0)
    wall = p["wall"] if p["wall"] is not None else (1.6 if lamp else 2.0)
    r = w / 2
    nz = max(60, int(h / 1.0))
    outer = _loft(_vase_rings(h, r, prof, pattern, sides, twist, 0, h, 0.0, nz))
    notes = []
    if wall <= 0:
        notes.append("Dolu gövde: dilimleyicide VAZO MODU (Creality Print: 'Spiral vazo' / 'Spiralize') açık basın; "
                     "yazıcı tek duvar ve taban basar. Duvar kalınlığı nozül çapı kadar olur (0.4 mm nozülde 0.4–0.8 mm "
                     "çizgi genişliği önerilir).")
        return outer, notes
    floor = max(1.2, wall)
    inner = _loft(_vase_rings(h, r, prof, pattern, sides, twist, floor, h + 2, wall, nz))
    body = outer - inner
    hole = p["hole"] if p["hole"] is not None else (40.0 if lamp else 0.0)
    if hole > 0:
        body -= _cylinder(floor + 2, hole / 2, hole / 2, 96).translate((0, 0, -1))
        notes.append(f"Tabanda {hole:g} mm delik: LED modülü / kablo buradan girer.")
    if lamp:
        notes.append("Işığın geçmesi için yarı saydam ya da beyaz PLA/PETG kullanın; 1.2–1.6 mm duvar iyi dağıtır.")
    notes.append("Destek gerekmez (duvar eğimi 45°'den dik).")
    return body, notes


def _swirl_sphere(radius, lobes, twist_deg, amp, inset, nth=180, nph=360, wave="girdap"):
    """Kutuptan kutba spiral dilimli küre yüzeyi (dilimler üstte merkezde birleşir)."""
    th = np.linspace(0, np.pi, nth + 2)[1:-1]  # kutuplar ayrı: kapak merkezleri
    ph = np.linspace(0, 2 * np.pi, nph, endpoint=False)
    T, P = np.meshgrid(th, ph, indexing="ij")
    psi = P + math.radians(twist_deg) * T / np.pi
    g = np.abs(np.sin(lobes * psi / 2)) ** 0.55  # yuvarlak dilimler, keskin oluklar
    r = radius * (1 + amp * g * np.sin(T) ** 0.7) - inset
    rings = np.stack([r * np.sin(T) * np.cos(P), r * np.sin(T) * np.sin(P), r * np.cos(T)], axis=-1)[::-1]
    top_r, bot_r = radius - inset, radius - inset
    return _loft(rings, bottom=np.array([0, 0, -bot_r]), top=np.array([0, 0, top_r]))


def swirl_lamp(p: dict) -> tuple[mf.Manifold, list[str]]:
    w = p["width"] or 140.0
    lobes = p["sides"] or 10
    twist = p["twist"] if p["twist"] is not None else 200.0
    wall = p["wall"] if p["wall"] is not None else 1.6
    amp = 0.08
    R = w / 2 / (1 + amp)
    cut = -0.68 * R  # buradan aşağısı kesilir: kalan yüzey 45°'den dik, destek gerekmez
    outer = _swirl_sphere(R, lobes, twist, amp, 0.0)
    notes = []
    if wall <= 0:
        body = outer.trim_by_plane((0, 0, 1), cut)
        notes.append("Dolu gövde: VAZO MODU (spiral vazo) açık basın; tek duvar ışığı çok iyi geçirir.")
    else:
        plate = 2.0
        inner = _swirl_sphere(R, lobes, twist, amp, wall).trim_by_plane((0, 0, 1), cut + plate)
        body = outer.trim_by_plane((0, 0, 1), cut) - inner
        hole = p["hole"] if p["hole"] is not None else 40.0
        if hole > 0:
            body -= _cylinder(plate + 4, hole / 2, hole / 2, 96).translate((0, 0, cut - 1))
            notes.append(f"Tabanda {hole:g} mm delik: pilli LED mum ya da küçük LED modülü içeri girer.")
    notes += ["Düz tabanı tablaya gelecek şekilde basın; alt kısım kesildiği için destek gerekmez.",
              "Yarı saydam ya da beyaz PLA/PETG ile ışık dilimlerden süzülür (fotoğraftaki etki)."]
    return body, notes


def ornament(p: dict) -> tuple[mf.Manifold, list[str]]:
    w = p["width"] or 60.0
    lobes = p["sides"] or 8
    twist = p["twist"] if p["twist"] is not None else 180.0
    amp = 0.07
    R = w / 2 / (1 + amp)
    body = _swirl_sphere(R, lobes, twist, amp, 0.0, nth=120, nph=240)
    if p["wall"]:
        body -= _swirl_sphere(R, lobes, twist, amp, p["wall"], nth=120, nph=240)
    tube = max(1.2, w * 0.03)
    ring = _torus(w * 0.09, tube).translate((0, 0, R + w * 0.09 * 0.6))
    body += ring + _cylinder(w * 0.08, w * 0.07, w * 0.05, 48).translate((0, 0, R - w * 0.04))
    body = body.trim_by_plane((0, 0, 1), -R * 0.92)  # küçük düz taban: tablaya otursun
    return body, ["Askı halkası üstte. Küre altı eğimli: dilimleyicide 'yalnızca tablaya dokunan destek' açın.",
                  "İpe asmak için halkaya ip ya da süs kancası takın."]


def twisted_tower(p: dict) -> tuple[mf.Manifold, list[str]]:
    h = p["height"] or 120.0
    w = p["width"] or 70.0
    n = max(3, int(p["sides"] or 6))
    twist = p["twist"] if p["twist"] is not None else 120.0
    ang = np.linspace(0, 2 * np.pi, n, endpoint=False)
    poly = np.c_[np.cos(ang), np.sin(ang)] * (w / 2)
    body = mf.CrossSection([poly]).extrude(h, n_divisions=max(20, int(h)), twist_degrees=twist,
                                           scale_top=(0.55, 0.55))
    return body, ["Dolu gövde: süs olarak dolgu %10–15 ile ya da vazo modunda basılabilir. Destek gerekmez."]


def star(p: dict) -> tuple[mf.Manifold, list[str]]:
    w = p["width"] or 90.0
    n = max(4, int(p["sides"] or 5))
    thick = p["thickness"] or max(2.0, w * 0.03)
    R, r = w / 2, w / 2 * 0.45
    ang = np.pi / 2 + np.arange(2 * n) * np.pi / n
    rad = np.where(np.arange(2 * n) % 2 == 0, R, r)
    outline = np.c_[rad * np.cos(ang), rad * np.sin(ang)]
    rings = np.array([np.c_[outline, np.zeros(2 * n)], np.c_[outline, np.full(2 * n, thick)]])
    body = _loft(rings, top=np.array([0.0, 0.0, thick + w * 0.14]))  # tepe noktasına yükselen yüzeyler
    hole = p["hole"] if p["hole"] is not None else 3.5
    notes = ["Düz yüzü tablaya gelecek şekilde basın; destek gerekmez."]
    if hole > 0:
        body -= _cylinder(thick * 3, hole / 2, hole / 2, 32).translate((0, R * 0.74, -1))
        notes.append(f"Üst uçta {hole:g} mm askı deliği.")
    return body, notes


def lattice_sphere(p: dict) -> tuple[mf.Manifold, list[str]]:
    import trimesh

    w = p["width"] or 80.0
    R = w / 2
    ico = trimesh.creation.icosphere(subdivisions=1 if w < 70 else 2, radius=R)
    strut = p["thickness"] or max(1.6, w * 0.028)
    parts = []
    for a, b in ico.vertices[ico.edges_unique]:
        d = b - a
        length = float(np.linalg.norm(d))
        m = np.c_[_rotation_to(d), a]
        parts.append(_cylinder(length, strut / 2, strut / 2, 12).transform(m.tolist()))
    parts += [mf.Manifold.sphere(strut * 0.75, 16).translate(tuple(v)) for v in ico.vertices]
    body = mf.Manifold.batch_boolean(parts, mf.OpType.Add).trim_by_plane((0, 0, 1), -R * 0.9)
    return body, ["Kafes yapı: dilimleyicide ağaç destek (tree support) önerilir; alt kısım düzleştirildi."]


def _gray(path: str, max_px: int) -> np.ndarray:
    from PIL import Image, ImageOps

    img = ImageOps.exif_transpose(Image.open(path)).convert("L")
    img.thumbnail((max_px, max_px))
    return np.asarray(img, dtype=np.float64) / 255.0  # 0 siyah … 1 beyaz; satır 0 resmin üstü


def _heightfield(hmap: np.ndarray, width: float, height: float) -> mf.Manifold:
    """Yükseklik haritası (satır × sütun, mm) → altı düz, kapalı blok. Satır 0 resmin üstü (y en büyük)."""
    rows, cols = hmap.shape
    xs = np.linspace(-width / 2, width / 2, cols)
    ys = np.linspace(height / 2, -height / 2, rows)
    X, Y = np.meshgrid(xs, ys)
    top = np.c_[X.ravel(), Y.ravel(), hmap.ravel()]
    bottom = np.c_[X.ravel(), Y.ravel(), np.zeros(X.size)]
    verts = np.vstack([top, bottom])
    k = rows * cols
    idx = np.arange(k).reshape(rows, cols)
    a, b, c, d = idx[:-1, :-1].ravel(), idx[:-1, 1:].ravel(), idx[1:, 1:].ravel(), idx[1:, :-1].ravel()
    faces = [np.c_[a, d, c], np.c_[a, c, b], np.c_[a + k, c + k, d + k], np.c_[a + k, b + k, c + k]]
    ring = np.r_[idx[0, :], idx[1:, -1], idx[-1, -2::-1], idx[-2:0:-1, 0]]  # kenar dolaşımı
    nxt = np.roll(ring, -1)
    faces += [np.c_[ring, nxt, nxt + k], np.c_[ring, nxt + k, ring + k]]  # kenar halkası saat yönünde
    return _manifold(verts, np.vstack(faces))


def relief(p: dict, litho: bool) -> tuple[mf.Manifold, list[str]]:
    if not p["image"]:
        raise DecorError("bu şekil için 'image' (resim dosyası) gerekli")
    w = p["width"] or (100.0 if litho else 120.0)
    g = _gray(p["image"], 260)
    rows, cols = g.shape
    h = w * rows / cols
    if litho:  # koyu yerler kalın (ışığı keser), açık yerler ince
        tmin, tmax = 0.8, max(2.0, p["thickness"] or 3.0)
        hmap = tmin + (tmax - tmin) * (1 - g)
        frame = 3.0
        hmap[:, :int(cols * frame / w) + 1] = hmap[:, -int(cols * frame / w) - 1:] = tmax + 0.5
        hmap[:int(rows * frame / h) + 1, :] = hmap[-int(rows * frame / h) - 1:, :] = tmax + 0.5
        notes = ["Litofan: beyaz PLA ile %100 dolgu, 0.12–0.16 mm katman; dik (kenarı tablada) basmak en net "
                 "sonucu verir. Arkasından ışık tutunca resim görünür."]
    else:  # açık yerler yüksek (invert: koyu yerler yüksek)
        base, depth = 2.5, p["thickness"] or 4.0
        v = (1 - g) if p["invert"] else g
        hmap = base + depth * v
        notes = ["Kabartma pano: düz yüzü tablada basın, 0.12–0.16 mm katman ayrıntıyı iyi çıkarır."]
    return _heightfield(hmap, w, h), notes


def litho_lamp(p: dict) -> tuple[mf.Manifold, list[str]]:
    """Resmi silindire saran litofan abajur: içi düz, dışı koyu yerlerde kalın; alt ve üstte sağlam bant."""
    if not p["image"]:
        raise DecorError("litofan_lamba için 'image' (resim dosyası) gerekli")
    d = p["width"] or 80.0
    circ = math.pi * d
    g = _gray(p["image"], 720)
    rows, cols = g.shape
    h = p["height"] or min(circ * rows / cols, 200.0)
    band, rin = 4.0, d / 2 - 3.0
    tmin, tmax = 0.8, 3.0
    n_a = min(cols, 500)  # ~0.5 mm: ayrıntı yeter, dosya 20 MB'ı geçmez
    n_z = max(40, int(h / 0.5))
    col = np.linspace(0, cols - 1, n_a).astype(int)
    zz = np.linspace(0, h, n_z)
    row = np.clip(((h - band - zz) / max(h - 2 * band, 1)) * (rows - 1), 0, rows - 1).astype(int)
    thick = tmin + (tmax - tmin) * (1 - g[np.ix_(row, col)])
    thick[(zz < band) | (zz > h - band), :] = tmax  # bantlar
    ang = 2 * np.pi * np.arange(n_a) / n_a
    ro = rin + thick
    outer = np.stack([ro * np.cos(ang), ro * np.sin(ang), np.repeat(zz[:, None], n_a, 1)], axis=-1).reshape(-1, 3)
    # iç yüzey düz silindir: yalnızca alt ve üst halka (uzun üçgenler; dosya yarıya iner)
    inner = np.vstack([np.c_[rin * np.cos(ang), rin * np.sin(ang), np.full(n_a, z)] for z in (0.0, h)])
    k = n_z * n_a
    idx = np.arange(k).reshape(n_z, n_a)
    nxt = lambda x: np.roll(x, -1, axis=-1)  # noqa: E731
    a, b, c, dd = idx[:-1].ravel(), nxt(idx[:-1]).ravel(), nxt(idx[1:]).ravel(), idx[1:].ravel()
    ib, it = k + np.arange(n_a), k + n_a + np.arange(n_a)  # iç alt / üst halka
    faces = [np.c_[a, b, c], np.c_[a, c, dd], np.c_[ib, nxt(it), nxt(ib)], np.c_[ib, it, nxt(it)]]
    top, bot = idx[-1], idx[0]
    faces += [np.c_[top, nxt(top), nxt(it)], np.c_[top, nxt(it), it],
              np.c_[bot, nxt(ib), nxt(bot)], np.c_[bot, ib, nxt(ib)]]
    body = _manifold(np.vstack([outer, inner]), np.vstack(faces))
    return body, ["Litofan lamba: beyaz PLA, %100 dolgu, 0.12–0.16 mm katman; içine pilli LED mum koyun.",
                  "Dik basılır, destek gerekmez; resim dıştan, ışık yanınca görünür."]


def _otsu(g: np.ndarray) -> float:
    hist, edges = np.histogram(g, bins=64, range=(0, 1))
    mids = (edges[:-1] + edges[1:]) / 2
    w0 = np.cumsum(hist)
    w1 = w0[-1] - w0
    m0 = np.cumsum(hist * mids) / np.maximum(w0, 1)
    m1 = (np.sum(hist * mids) - np.cumsum(hist * mids)) / np.maximum(w1, 1)
    return float(mids[np.argmax(w0 * w1 * (m0 - m1) ** 2)])


def silhouette(p: dict) -> tuple[mf.Manifold, list[str]]:
    """Resimdeki figürün dış hattı → kalınlık verilmiş, ayaklı, ayakta duran figür."""
    if not p["image"]:
        raise DecorError("siluet için 'image' (resim dosyası) gerekli; önce generate_image ile beyaz zemin üzerinde "
                         "siyah siluet resmi üretin")
    import contourpy
    from PIL import Image, ImageFilter

    g = _gray(p["image"], 480)
    mask = g < _otsu(g)
    border = np.r_[mask[0], mask[-1], mask[:, 0], mask[:, -1]]
    if border.mean() > 0.5:  # zemin koyuymuş: figür açık renkli
        mask = ~mask
    if p["invert"]:
        mask = ~mask
    if mask.mean() < 0.01:
        raise DecorError("resimde figür bulunamadı: beyaz zemin üzerinde tek, koyu bir siluet olmalı")
    soft = np.asarray(Image.fromarray((mask * 255).astype(np.uint8)).filter(ImageFilter.GaussianBlur(1.2)),
                      dtype=np.float64) / 255.0
    soft = np.pad(soft, 2)  # kenara değen figür de kapalı hat versin
    lines = contourpy.contour_generator(z=soft).lines(0.5)
    polys = [np.c_[ln[:, 0], -ln[:, 1]] for ln in lines if len(ln) >= 8]
    if not polys:
        raise DecorError("figürün dış hattı çıkarılamadı")
    shape2d = mf.CrossSection(polys, mf.FillRule.EvenOdd).simplify(0.4)
    pieces = sorted(shape2d.decompose(), key=lambda s: s.area(), reverse=True)
    pieces = [s for s in pieces if s.area() >= pieces[0].area() * 0.03]
    shape2d = mf.CrossSection.batch_boolean(pieces, mf.OpType.Add)
    (x0, y0), (x1, y1) = shape2d.bounds()[:2], shape2d.bounds()[2:]
    fig_h = p["height"] or 120.0
    s = fig_h / (y1 - y0)
    shape2d = shape2d.translate((-(x0 + x1) / 2, -y0)).scale((s, s))
    thick = p["thickness"] or max(4.0, fig_h * 0.05)
    base_t = 4.0
    fig = shape2d.extrude(thick).rotate((90, 0, 0)).translate((0, thick / 2, base_t - 0.6))
    fw = (x1 - x0) * s
    depth = max(30.0, fig_h * 0.3)
    base = mf.CrossSection.circle(1.0, 96).scale(((fw + 12) / 2, depth / 2)).extrude(base_t)
    body = fig + base
    notes = ["Ayakta duran figür: tabanı tablada, destek gerekmez. Kalınlık " + f"{thick:g} mm."]
    if len(pieces) > 1:
        notes.append(f"Siluette {len(pieces)} ayrı parça vardı; tabana değmeyenler havada kalabilir — tek parça bir "
                     "siluet resmiyle daha iyi olur.")
    return body, notes


def write_3mf(path: Path, vertices: np.ndarray, faces: np.ndarray) -> None:
    """En yalın 3MF (zip içinde model XML'i, birim mm): trimesh'in 3MF yazıcısı pakette olmayan networkx istiyor,
    dosya 0 bayt kalıyordu."""
    import zipfile

    verts = "".join(f'<vertex x="{x:.4f}" y="{y:.4f}" z="{z:.4f}"/>' for x, y, z in vertices)
    tris = "".join(f'<triangle v1="{a}" v2="{b}" v3="{c}"/>' for a, b, c in faces)
    model = ('<?xml version="1.0" encoding="UTF-8"?>\n<model unit="millimeter" xml:lang="tr-TR" '
             'xmlns="http://schemas.microsoft.com/3dmanufacturing/core/2015/02"><resources><object id="1" '
             f'type="model"><mesh><vertices>{verts}</vertices><triangles>{tris}</triangles></mesh></object>'
             '</resources><build><item objectid="1"/></build></model>')
    types = ('<?xml version="1.0" encoding="UTF-8"?>\n<Types xmlns="http://schemas.openxmlformats.org/package/2006/'
             'content-types"><Default Extension="rels" ContentType="application/vnd.openxmlformats-package.'
             'relationships+xml"/><Default Extension="model" ContentType="application/vnd.ms-package.3dmanufacturing'
             '-3dmodel+xml"/></Types>')
    rels = ('<?xml version="1.0" encoding="UTF-8"?>\n<Relationships xmlns="http://schemas.openxmlformats.org/package/'
            '2006/relationships"><Relationship Target="/3D/3dmodel.model" Id="rel0" Type="http://schemas.microsoft.'
            'com/3dmanufacturing/2013/01/3dmodel"/></Relationships>')
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("[Content_Types].xml", types)
        z.writestr("_rels/.rels", rels)
        z.writestr("3D/3dmodel.model", model)


# ---------------------------------------------------------------- ana akış

def _params(raw: dict) -> dict:
    def num(key, lo=None, hi=None):
        v = raw.get(key)
        if v in (None, ""):
            return None
        v = float(v)
        if lo is not None and v < lo or hi is not None and v > hi:
            raise DecorError(f"{key} {lo}–{hi} arasında olmalı")
        return v

    shape = str(raw.get("shape") or "").strip().lower()
    if shape not in SHAPES:
        raise DecorError(f"bilinmeyen şekil '{shape}'; seçenekler: {', '.join(SHAPES)}")
    profile = str(raw.get("profile") or "").strip().lower() or None
    if profile and profile not in PROFILES:
        raise DecorError(f"profil şunlardan biri olmalı: {', '.join(PROFILES)}")
    pattern = str(raw.get("pattern") or "").strip().lower() or None
    if pattern and pattern not in PATTERNS:
        raise DecorError(f"desen şunlardan biri olmalı: {', '.join(PATTERNS)}")
    bed = [float(x) for x in str(raw.get("bed") or "220x220x250").lower().replace(" ", "").split("x")]
    if len(bed) != 3:
        raise DecorError("bed 260x260x260 biçiminde olmalı (mm)")
    sides = num("sides", 3, 64)
    return {"shape": shape, "profile": profile, "pattern": pattern, "height": num("height", 5, 1000),
            "width": num("width", 5, 1000), "sides": int(sides) if sides else None, "twist": num("twist", -1080, 1080),
            "wall": num("wall", 0, 20), "hole": num("hole", 0, 300), "thickness": num("thickness", 0.4, 50),
            "image": raw.get("image") or None, "invert": bool(raw.get("invert")), "bed": bed}


BUILDERS = {
    "vazo": lambda p: vase(p, lamp=False),
    "abajur": lambda p: vase(p, lamp=True),
    "girdap_lamba": swirl_lamp,
    "sus_topu": ornament,
    "burgulu_kule": twisted_tower,
    "yildiz": star,
    "kafes_kure": lattice_sphere,
    "kabartma": lambda p: relief(p, litho=False),
    "litofan": lambda p: relief(p, litho=True),
    "litofan_lamba": litho_lamp,
    "siluet": silhouette,
}


def build(raw: dict, out: str) -> dict:
    """Süs modelini üretir ve kaydeder (save); sonuç bilgisi döner."""
    p = _params(raw)
    body, notes = BUILDERS[p["shape"]](p)
    vase_mode = p["wall"] is not None and p["wall"] <= 0 and p["shape"] in ("vazo", "abajur", "girdap_lamba")
    solid = p["shape"] in ("siluet", "yildiz", "burgulu_kule") or (p["shape"] == "sus_topu" and not p["wall"])
    return save(body, notes, p["bed"], out, vase_mode=vase_mode, infill=0.15 if solid else None)


def save(body: mf.Manifold, notes: list[str], bed, out: str, vase_mode: bool = False,
         infill: float | None = None) -> dict:
    """Modeli tablaya oturtur (gerekirse orantılı küçültür), STL ve 3MF yazar, yazılan dosyayı denetler.
    Süs modelleri ve resimden 3D figür (figure3d_worker.py) aynı yoldan kaydedilir. infill: dolu gövdenin
    dilimleyicideki dolgu oranı (filament tahmini: 1.2 mm kabuk + dolgu; verilmezse tam hacim, ör. ince duvarlı vazo)."""
    import trimesh

    notes = list(notes)
    lo, hi = np.array(body.bounding_box()[:3]), np.array(body.bounding_box()[3:])
    size = hi - lo
    fit = min(1.0, *(b / s for s, b in zip(sorted(size), sorted(bed)) if s > 0))
    if fit < 1.0:  # tablaya sığmıyor: orantılı küçült (%2 pay)
        body = body.scale((fit * 0.98,) * 3)
        notes.insert(0, f"Tablaya ({'x'.join(f'{b:g}' for b in bed)} mm) sığsın diye %{fit * 98:.0f} boyuta "
                        "küçültüldü.")
        lo, hi = np.array(body.bounding_box()[:3]), np.array(body.bounding_box()[3:])
    body = body.translate((-(lo[0] + hi[0]) / 2, -(lo[1] + hi[1]) / 2, -lo[2]))
    # birleşimden kalan mikron altı kenarlar birleştirilir, hacimsiz artıklar atılır (0.01 mm eşik küçük süs topunda
    # hacmi sıfır ayrı bir parça bırakıyordu)
    body = body.simplify(0.001)
    pieces = body.decompose()
    if len(pieces) > 1:
        body = mf.Manifold.compose([x for x in pieces if x.volume() >= 1.0] or pieces)
    mesh = body.to_mesh()
    tm = trimesh.Trimesh(np.asarray(mesh.vert_properties)[:, :3], np.asarray(mesh.tri_verts), process=False)
    out_path = Path(out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    stl = out_path.with_suffix(".stl")
    tm.export(stl)
    files = [str(stl)]
    written = trimesh.load(stl, force="mesh")  # kapalılık yazılan dosyada denetlenir: dilimleyicinin göreceği
    three = out_path.with_suffix(".3mf")
    try:
        write_3mf(three, np.asarray(written.vertices), np.asarray(written.faces))
        files.append(str(three))
    except OSError:  # STL her dilimleyicide açılır; yarım 3MF bırakılmaz
        three.unlink(missing_ok=True)
    vol = body.volume() / 1000
    info = {"files": files, "size_mm": [round(float(x), 1) for x in tm.extents], "triangles": int(body.num_tri()),
            "watertight": bool(written.is_watertight), "bodies": len(body.decompose()), "volume_cm3": round(vol, 1),
            "notes": notes}
    if vase_mode:  # vazo modunda tek duvar: yüzey alanı × ~0.5 mm
        info["filament_g"] = round(body.surface_area() * 0.5 / 1000 * PLA)
    elif infill is not None:  # dolu gövde: 3 duvar (~1.2 mm) + iç dolgu (tam hacim 3 kat fazla gösteriyordu)
        shell = min(vol, body.surface_area() * 1.2 / 1000)
        info["filament_g"] = round((shell + (vol - shell) * infill) * PLA)
        info["infill"] = infill
    else:
        info["filament_g"] = round(vol * PLA)
    return info


if __name__ == "__main__":
    args = json.loads(sys.argv[1])
    try:
        print(json.dumps(build(args, args["out"]), ensure_ascii=False))
    except DecorError as e:
        print(json.dumps({"error": str(e)}, ensure_ascii=False))
