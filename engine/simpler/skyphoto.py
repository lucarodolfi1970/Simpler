"""Sky colours from a photo ("Colori da una foto", Cielo > Avanzate).

Simpler does not understand the photo: it compares colours. A table made once with Simpler itself (sky_table_job.py:
small renders of the sky only, for many heights of the sun, haze, ozone and clouds, through the same pipeline as the
final render) keeps the main colours of every combination. A photo is reduced the same way and the combination with
the closest colours wins: the sky stays physical, the photo only chooses among the skies Simpler can make. A photo
that is not a sky (a dog) simply gives the closest sky, with a low similarity.

Pure numpy: used by the table job (in Blender) and by the engine.
"""
import json
import math
import os

import numpy as np

TABLE = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "assets", "sky_table.json")
K = 6                                   # colours of a palette


def _lin(c):
    return np.where(c <= 0.04045, c / 12.92, ((c + 0.055) / 1.055) ** 2.4)


def lab(rgb):
    """sRGB display values 0..1 (..., 3) -> CIE Lab (D65)."""
    m = np.array([[0.4124, 0.3576, 0.1805], [0.2126, 0.7152, 0.0722], [0.0193, 0.1192, 0.9505]])
    xyz = _lin(np.clip(rgb, 0, 1)) @ m.T / np.array([0.9505, 1.0, 1.089])
    f = np.where(xyz > 0.008856, np.cbrt(xyz), 7.787 * xyz + 16.0 / 116.0)
    return np.stack([116 * f[..., 1] - 16, 500 * (f[..., 0] - f[..., 1]), 200 * (f[..., 1] - f[..., 2])], -1)


def describe(rgb):
    """rgb: (h, w, 3) display values 0..1, top row first. Returns the palette (K colours in Lab with their share,
    lightest first) and the mean colour of the top, middle and bottom thirds (the gradient of a sky)."""
    h, w = rgb.shape[:2]
    step = max(1, int(math.sqrt(h * w / 6000.0)))           # ~6000 pixels are enough for the colours
    small = rgb[::step, ::step, :3]
    px = lab(small.reshape(-1, 3))
    rng = np.random.default_rng(7)
    # k-means++ start, then 20 rounds
    c = [px[rng.integers(len(px))]]
    for _ in range(K - 1):
        d = np.min(((px[:, None] - np.array(c)[None]) ** 2).sum(-1), 1)
        c.append(px[rng.choice(len(px), p=d / max(d.sum(), 1e-9))])
    c = np.array(c)
    for _ in range(20):
        a = ((px[:, None] - c[None]) ** 2).sum(-1).argmin(1)
        c = np.array([px[a == i].mean(0) if np.any(a == i) else c[i] for i in range(K)])
    share = np.bincount(a, minlength=K) / len(a)
    order = np.argsort(-c[:, 0])
    thirds = [lab(small[i * small.shape[0] // 3:(i + 1) * small.shape[0] // 3].reshape(-1, 3)).mean(0) for i in range(3)]
    return {"palette": [[round(float(v), 2) for v in c[i]] for i in order], "share": [round(float(share[i]), 4) for i in order],
            "thirds": [[round(float(v), 2) for v in t] for t in thirds], "lightness": round(float(px[:, 0].mean()), 2)}


def _chamfer(pa, wa, pb, wb):
    """Distance between two palettes: every colour of one to the nearest of the other, weighted by its share, both
    ways. Lightness counts half (an exposure apart is less of a difference than another hue)."""
    s = np.array([0.5, 1.0, 1.0])
    d = np.sqrt((((pa[:, None] - pb[None]) * s) ** 2).sum(-1))
    return float((d.min(1) * wa).sum() + (d.min(0) * wb).sum()) / 2.0


def distance(a, b):
    pa, pb = np.array(a["palette"]), np.array(b["palette"])
    wa, wb = np.array(a["share"]), np.array(b["share"])
    g = np.mean([np.sqrt((((np.array(x) - np.array(y)) * [0.5, 1, 1]) ** 2).sum()) for x, y in zip(a["thirds"], b["thirds"])])
    return 0.75 * _chamfer(pa, wa, pb, wb) + 0.25 * g


def similarity(d):
    """A distance as a percentage for the panel: 0 = same colours; 40 (Lab) = nothing in common."""
    return max(0, min(100, round(100 * (1 - d / 40.0))))


def load_table():
    with open(TABLE, encoding="utf-8") as f:
        return json.load(f)


def best(desc, table=None, top=1, min_cover=0.0, only=None):
    """The combinations of the table closest to a photo described with describe() (only those with at least
    `min_cover` of clouds, or only the (type, cover) pairs in `only`, for the presets of a covered sky)."""
    table = table or load_table()
    entries = [e for e in table["entries"] if e["params"]["cover"] >= min_cover
               and (e["params"]["type"], e["params"]["cover"]) not in EXCLUDED]
    if only:
        sel = [e for e in entries if (e["params"]["type"], e["params"]["cover"]) in only]
        entries = sel or entries                # (a table made before those clouds: the rule above)
    scored = sorted(((distance(desc, e["desc"]), e) for e in entries), key=lambda x: x[0])
    return [(d, e["params"]) for d, e in scored[:top]]


# ---------------------------------------------------------------- the engine side (Blender)

BUILTIN = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "assets", "sky_refs")
GROUPS = {"alba": "Alba", "tramonto": "Tramonto", "nuvoloso": "Nuvoloso"}     # (in this order in the list)
# what we know of the built-in photos, that their colours alone cannot say: a covered sky (dark grey is also the shadow
# of a few big cumuli under a low exposure) and the morning side of the day
# never chosen from a photo (1.18.2): the stratus at 90% is one flat, uniform sheet - right as a sky, but a photo
# picking it for its colours gave a sky far too thick and even (the table keeps it, for other uses)
EXCLUDED = {("strati", 0.9)}
# Nuvoloso: big dark masses with gaps of light (1.17.12): the uniform stratus at 90% came out too flat and covered
GROUP_RULES = {"nuvoloso": {"min_cover": 0.6, "only": [("cumuli_grandi", 0.7)]}, "alba": {"am": True}, "tramonto": {"pm": True}}


def _user_dir():
    import tempfile
    base = os.environ.get("LOCALAPPDATA") or tempfile.gettempdir()
    d = os.path.join(base, "Simpler", "sky_refs")
    os.makedirs(d, exist_ok=True)
    return d


def _read(path, side=256):
    """A picture as display values (h, w, 3), top row first, reduced to about `side` pixels (any size, any format
    Blender reads)."""
    import bpy
    from .core import ApiError
    from .i18n import tr
    try:
        im = bpy.data.images.load(path, check_existing=False)
    except RuntimeError:
        raise ApiError(tr("Non riesco a leggere l'immagine: {0}", os.path.basename(path)))
    try:
        im.colorspace_settings.name = "Non-Color"          # the values of the file, as a photo shows them
        w, h = im.size[:]
        if w <= 0 or h <= 0:
            raise ApiError(tr("Non riesco a leggere l'immagine: {0}", os.path.basename(path)))
        k = side / max(w, h)
        if k < 1:
            im.scale(max(1, int(w * k)), max(1, int(h * k)))
            w, h = im.size[:]
        px = np.empty(w * h * 4, dtype=np.float32)
        im.pixels.foreach_get(px)
        return px.reshape(h, w, 4)[::-1, :, :3].copy()
    finally:
        bpy.data.images.remove(im)


def refs(_d=None):
    """The photos of the list: built-in presets (groups) and the user's own."""
    out = []
    if os.path.isdir(BUILTIN):
        order = list(GROUPS)
        files = [f for f in os.listdir(BUILTIN) if f.lower().endswith((".jpg", ".png"))]
        files.sort(key=lambda f: (order.index(f.rsplit("_", 1)[0]) if f.rsplit("_", 1)[0] in order else 99, f))
        for f in files:
            if f.lower().endswith((".jpg", ".png")):
                stem = os.path.splitext(f)[0]
                group = stem.rsplit("_", 1)[0]
                from .i18n import tr
                out.append({"id": "builtin:" + stem, "name": tr(GROUPS.get(group, group.capitalize())) + " " + stem.rsplit("_", 1)[-1],
                            "group": group, "path": os.path.join(BUILTIN, f), "user": False})
    d = _user_dir()
    for f in sorted(os.listdir(d), key=lambda x: os.path.getmtime(os.path.join(d, x))):
        if f.lower().endswith(".jpg"):
            stem = os.path.splitext(f)[0]
            out.append({"id": "user:" + stem, "name": stem, "group": "mie", "path": os.path.join(d, f), "user": True})
    ok = False
    try:
        ok = load_table().get("version") == 2
    except (OSError, ValueError):
        pass
    return {"refs": out, "table": ok}


def _ref_path(ref_id):
    from .core import ApiError
    from .i18n import tr
    for r in refs()["refs"]:
        if r["id"] == ref_id:
            return r["path"]
    raise ApiError(tr("Foto non trovata"))


def fit(desc, table=None, min_cover=0.0, only=None):
    """The settings closest to a photo: the clouds and the colour rendering of the nearest combination; height of the
    sun, haze, ozone and exposure averaged over the 4 nearest with the same clouds and rendering, by closeness."""
    found = best(desc, table, top=24, min_cover=min_cover, only=only)
    d0, p0 = found[0]
    same = [(d, p) for d, p in found if p["type"] == p0["type"] and p.get("render") == p0.get("render")][:4]
    ws = [1.0 / max(d, 0.5) ** 2 for d, _p in same]
    tot = sum(ws)
    out = {k: float(sum(w * p.get(k, 0.0) for w, (_d, p) in zip(ws, same)) / tot) for k in ("elev", "aerosol", "ozone", "ev")}
    out.update(type=p0["type"], cover=p0["cover"], render=p0.get("render", "natural"))
    return d0, out


def from_photo(d):
    """POST ambience/fromphoto {ref | path}: analyses the photo, sets time, haze, ozone and clouds of the sky."""
    from . import ambience
    from .core import ApiError
    from .i18n import tr
    if not os.path.isfile(TABLE) or load_table().get("version") != 2:
        raise ApiError(tr("La tabella dei colori del cielo non c'è ancora: serve per confrontare la foto"))
    path = _ref_path(d["ref"]) if d.get("ref") else d.get("path", "")
    group = ""
    if d.get("ref", "").startswith("builtin:"):
        group = d["ref"][8:].rsplit("_", 1)[0]
    rules = GROUP_RULES.get(group, {})
    if not path or not os.path.isfile(path):
        raise ApiError(tr("Foto non trovata"))
    desc = describe(_read(path))
    dist, p = fit(desc, min_cover=rules.get("min_cover", 0.0), only=rules.get("only"))
    s = ambience.state() or ambience.DEFAULTS
    sun = dict(s["sun"])
    pm = float(sun.get("hour", 12.0)) >= 12.0               # morning or evening: the side the user chose
    if rules.get("am"):
        pm = False                                           # (a sunrise: in the morning)
    elif rules.get("pm"):
        pm = True
    hour = ambience._hour_for_elev(p["elev"], pm, sun)
    change = {"sun": {"hour": hour}, "sky": {"aerosol": round(p["aerosol"], 2), "ozone": round(p["ozone"], 2)},
              "clouds": {"volumetric": True, "type": p["type"], "cover": round(p["cover"], 2)},
              "photoRef": d.get("ref") or path, "fromPhoto": True}
    from . import render
    render.set_settings({"config": {"exposure": round(p["ev"], 2), "colorRender": p["render"]}})
    out = ambience.api_set(change)
    if isinstance(out, dict):
        out = dict(out)
    else:
        out = ambience.info()
    out["photo"] = {"similarity": similarity(dist), "elev": round(p["elev"], 1), "hour": hour,
                    "aerosol": round(p["aerosol"], 2), "ozone": round(p["ozone"], 2), "type": p["type"],
                    "cover": round(p["cover"], 2), "ev": round(p["ev"], 1), "render": p["render"],
                    "palette": [_hex(c) for c in desc["palette"]], "share": desc["share"]}
    return out


def _hex(c):
    """A Lab colour back to #rrggbb (for the chips of the panel)."""
    L, a, b = c
    fy = (L + 16) / 116.0
    fx, fz = fy + a / 500.0, fy - b / 200.0
    f = np.array([fx, fy, fz])
    xyz = np.where(f ** 3 > 0.008856, f ** 3, (f - 16 / 116.0) / 7.787) * np.array([0.9505, 1.0, 1.089])
    m = np.array([[3.2406, -1.5372, -0.4986], [-0.9689, 1.8758, 0.0415], [0.0557, -0.2040, 1.0570]])
    lin = np.clip(m @ xyz, 0, 1)
    srgb = np.where(lin <= 0.0031308, 12.92 * lin, 1.055 * lin ** (1 / 2.4) - 0.055)
    return "#" + "".join(f"{int(round(v * 255)):02X}" for v in np.clip(srgb, 0, 1))


def save_ref(d):
    """POST ambience/skyrefs/save {path, name}: the photo as a preset of the user, square (centre) 256 px."""
    import bpy
    from .core import ApiError
    from .i18n import tr
    path, name = d.get("path", ""), "".join(ch for ch in (d.get("name") or "").strip() if ch not in '\\/:*?"<>|').strip()
    if not path or not os.path.isfile(path):
        raise ApiError(tr("Foto non trovata"))
    if not name:
        raise ApiError(tr("Scrivi un nome per il preset"))
    rgb = _read(path, 1024)
    h, w = rgb.shape[:2]
    s = min(h, w)
    sq = rgb[(h - s) // 2:(h - s) // 2 + s, (w - s) // 2:(w - s) // 2 + s]
    im = bpy.data.images.new("simpler_skyref", s, s, alpha=False)
    try:
        im.colorspace_settings.name = "Non-Color"
        px = np.ones((s, s, 4), dtype=np.float32)
        px[..., :3] = sq[::-1]
        im.pixels.foreach_set(px.ravel())
        im.scale(256, 256)
        out = os.path.join(_user_dir(), name + ".jpg")
        im.filepath_raw = out
        im.file_format = "JPEG"
        im.save()
    finally:
        bpy.data.images.remove(im)
    r = refs()
    r["saved"] = "user:" + name
    return r


def delete_ref(d):
    """POST ambience/skyrefs/delete {ref}: removes a preset of the user (the built-in ones stay)."""
    from .core import ApiError
    from .i18n import tr
    ref = d.get("ref", "")
    if not ref.startswith("user:"):
        raise ApiError(tr("Si possono togliere solo i preset salvati da te"))
    try:
        os.remove(_ref_path(ref))
    except OSError:
        pass
    return refs()
