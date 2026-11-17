"""«Terreno» (1.76.0): a terrain in the scene, made of one mesh per zone (prato, terra, roccia, neve, spianata,
sabbia) under a group - so a zone can take its own material or ecosystem (Luca: «il materiale prato potrò sostituirlo
con un ecosistema perché sarà delimitato dalla sua propria mesh»).

- the shape: terrain_gen (numpy): relief grown by rivers, droplet erosion, natural angle; or a height map of the user
  (PNG 16 bit, TIFF, EXR, RAW), optionally eroded a little
- the zones: from slope, height, the flow of water and what it left (gravel and soil along the channels and at the
  foot of slopes), hollows for the snow; their borders broken by a noise (no straight lines)
- the zones share the very same vertices on their borders and get the normals of the whole terrain (custom normals):
  no seam is seen between them
- the «spianata»: a flat area around the model (at height 0, where the model stands), with a soft edge; the outer
  edge of the terrain goes down to 0 too (it meets the ground of the Ambiente without a step)
- the parameters live on the meshes (simpler_terrain on each zone mesh): Ctrl+Z (history kind «meshes», the swaps of
  decimate.SWAPS) brings back the shape and the parameters together
- materials: a plain colour at once, then the Poly Haven textures (downloaded in the background by library.py):
  POST terrain/materials applies them to the zones that still have the plain colour (a material the user chose stays)
"""
import json
import math
import os
import time

import bpy
import numpy as np

from . import progress, terrain_gen as T
from .core import ApiError, ID_KEY, KIND_KEY, find, link, new_id, refresh
from .i18n import tr

KEY = "simpler_terrain"            # on the group (kind «terrain») and on every zone mesh: the parameters (json)
ZONE_KEY = "simpler_terrain_zone"  # on the zone objects: their zone
PLACEHOLDER = "simpler_terrain_placeholder"   # on the plain materials made at first (replaced by the textures)

ZONES = ("prato", "terra", "roccia", "neve", "spianata", "sabbia")
ZONE_NAMES = {"prato": "Prato", "terra": "Terra e ghiaia", "roccia": "Roccia", "neve": "Neve", "spianata": "Spianata",
              "sabbia": "Sabbia"}
# the plain colours shown until the textures arrive (linear RGB), roughness
ZONE_COLORS = {"prato": ((0.05, 0.09, 0.02), 0.9), "terra": ((0.14, 0.11, 0.08), 0.95), "roccia": ((0.2, 0.19, 0.17), 0.85),
               "neve": ((0.85, 0.87, 0.9), 0.5), "spianata": ((0.07, 0.11, 0.03), 0.9), "sabbia": ((0.45, 0.32, 0.18), 0.9)}
# Poly Haven textures of every zone, by preset (ids checked in the Poly Haven list, 2026-11-01)
# ---- «Dividi zona» (1.76.8): a zone split in two by the ground itself - the wet hollows of a meadow, the side in
# the sun, the high pastures, the steep parts, the ridges, natural patches. A split is {id, zone (the zone it takes
# from, also a split), rule, amount (share of that zone's area), irregular, size (patches, m), name}; applied in
# order on the fields the zones are made of, so «Un'altra versione» or a new height range make them again.
MAX_ZONES = 16
SPLIT_RULES = {"umido": ("wet", 1), "secco": ("wet", -1), "sole": ("sun", 1), "ombra": ("sun", -1),
               "alto": ("alt", 1), "basso": ("alt", -1), "ripido": ("slope", 1), "piano": ("slope", -1),
               "dossi": ("shape", 1), "conche": ("shape", -1), "macchie": ("patch", 1)}
SPLIT_NAMES = {"umido": "umido", "secco": "secco", "sole": "al sole", "ombra": "in ombra", "alto": "in alto",
               "basso": "in basso", "ripido": "ripido", "piano": "in piano", "dossi": "sui dossi",
               "conche": "nelle conche", "macchie": "a macchie"}
# (the first look of a new part: its zone's material a little different - brightness, saturation - until another
# material is dropped on it)
SPLIT_TWEAK = {"umido": (0.85, 1.15), "secco": (1.12, 0.75), "sole": (1.08, 0.85), "ombra": (0.88, 1.05),
               "alto": (1.05, 0.85), "basso": (0.92, 1.1), "ripido": (0.95, 0.9), "piano": (1.0, 1.05),
               "dossi": (1.06, 0.85), "conche": (0.88, 1.12), "macchie": (0.9, 1.1)}


def splits_of(p):
    out, seen = [], set(ZONES)
    for sp in (p.get("splits") or []):
        if not isinstance(sp, dict) or not sp.get("id") or sp["id"] in seen or sp.get("rule") not in SPLIT_RULES:
            continue
        if sp.get("zone") not in seen or len(seen) >= MAX_ZONES:
            continue
        seen.add(sp["id"])
        out.append(sp)
    return out


def _assign_split_ids(p, taken=()):
    """New parts (from the app, without id): the next free «sN» (never one an object of the terrain still has)."""
    used = set(taken) | {sp.get("id") for sp in (p.get("splits") or []) if isinstance(sp, dict)}
    nums = [int(k[1:]) for k in used if isinstance(k, str) and k[:1] == "s" and k[1:].isdigit()]
    n = max(nums or [0])
    for sp in (p.get("splits") or []):
        if isinstance(sp, dict) and not sp.get("id"):
            n += 1
            sp["id"] = f"s{n}"
    return p


def zone_keys(p):
    """The zones of a terrain: the six of every terrain, then its splits."""
    return list(ZONES) + [sp["id"] for sp in splits_of(p)]


def _split(p, key):
    return next((sp for sp in splits_of(p) if sp["id"] == key), None)


def root_zone(p, key):
    """The zone of the six a split comes from (its textures, its large texture)."""
    seen = 0
    while key not in ZONES and seen < MAX_ZONES:
        sp = _split(p, key)
        if sp is None:
            return "prato"
        key, seen = sp["zone"], seen + 1
    return key


def zone_label(p, key):
    if key in ZONES:
        return tr(ZONE_NAMES[key])
    sp = _split(p, key) or {}
    if sp.get("name"):
        return sp["name"]
    return zone_label(p, sp.get("zone", "prato")) + " · " + tr(SPLIT_NAMES.get(sp.get("rule"), ""))


def _sun_xy():
    """Where the sun of the Ambiente is, seen from above (unit vector towards it); the south when there is none."""
    try:
        from . import ambience
        from mathutils import Vector
        sun = ambience._find_flag(ambience.SUN_KEY)
        if sun is not None:
            v = sun.matrix_world.to_3x3() @ Vector((0.0, 0.0, 1.0))
            l = math.hypot(v.x, v.y)
            if l > 1e-3:
                return v.x / l, v.y / l
    except Exception:
        pass
    return 0.0, -1.0


TEXTURES = {
    "default": {"prato": "leafy_grass", "terra": "gravel_ground_01", "roccia": "rock_face_03", "neve": "snow_02",
                "spianata": "grass_ground", "sabbia": "aerial_sand"},
    "colline": {"terra": "forest_ground_04", "roccia": "rocky_trail"},
    "pianura": {"terra": "forest_ground_04", "roccia": "rocky_trail"},
    "dune": {"sabbia": "aerial_sand"},
    "canyon": {"prato": "withered_grass", "terra": "red_sand", "roccia": "sandstone_cracks", "spianata": "dry_ground_01"},
}

# (1.76.6) «Variazione su grande scala» of the zones: a large aerial texture of Poly Haven (its real size from the
# library) over the detail one - (texture, strength, colour, tone); None: only the tone. Sizes in metres for when the
# list of the library is not loaded.
MACRO = {
    "default": {"prato": ("rocky_terrain_02", 0.55, 0.3, 0.25), "terra": ("aerial_rocks_01", 0.7, 0.5, 0.15),
                "roccia": ("marble_cliff_05", 0.8, 0.7, 0.1), "neve": ("snow_field_aerial", 0.6, 0.6, 0.05),
                "spianata": (None, 0.0, 0.0, 0.15), "sabbia": ("aerial_beach_01", 0.6, 0.5, 0.1)},
    "pianura": {"prato": (None, 0.0, 0.0, 0.25)},
    "canyon": {"roccia": ("marble_cliff_04", 0.8, 0.7, 0.1)},
}
MACRO_SIZE_M = {"rocky_terrain_02": 90, "aerial_rocks_01": 80, "marble_cliff_05": 20, "marble_cliff_04": 12,
                "snow_field_aerial": 80, "aerial_beach_01": 30}


def macro_for(p):
    t = dict(MACRO["default"])
    t.update(MACRO.get(p.get("preset"), {}))
    return t


DEFAULTS = {
    "preset": "colline", "size": None, "height": None, "seed": 1,
    "erosion": 1.0, "age": 1.0, "rough": 0.5, "direction": 0.0,
    "rockSlope": 35.0,          # degrees: steeper is rock
    "gravel": 0.5,              # 0..1 how much ground along channels and at the foot of slopes is gravel and soil
    "snow": False, "snowHeight": 0.75,     # 0..1 of the relief
    "irregular": 0.5,           # how broken the borders of the zones are
    "flat": {"on": True, "x": 0.0, "y": 0.0, "radius": 30.0, "soft": 40.0},   # metres
    "edge": True,               # the outer edge goes down to 0
    "splits": [],               # (1.76.8) «Dividi zona»: see SPLIT_RULES
    # (1.76.10) «Roccia scolpita» (rock_settings): None on terrains made before - unchanged; a new terrain takes
    # the one of its preset (ROCKY_DEF)
    "rocky": None, "sharp": 0.5, "strata": 0.6, "strataThick": 0.0, "strataDip": 8.0,
    "tone": None,               # (1.76.14) «Colori dal terreno» (tone_settings): new terrains TONE_DEF
    "sculpt": [],               # (1.76.44) «Scultura»: the strokes of the brush (_apply_sculpt), in metres of the terrain
    "rockKind": None, "rockSize": None, "rockOrient": None,   # (1.76.54) «Rilievo 3D» in the shape (rock_kind)
    "edgeNatural": None,        # (1.76.19) the edge with bays and headlands (new terrains); before: the straight ramp
    "detail": "normale",        # mesh: normale 512, alto 768, massimo 1024
    "heightmap": "", "hmHeight": 100.0, "hmErosion": 0.3,
    "hmCrop": [],               # (1.76.34) of an elevation file: the square used [x0, y0, side], fractions, from the north-west
}
MESH_N = {"normale": 512, "alto": 768, "massimo": 1024}     # (points per side at most: the same as the old even grid)
# (1.76.3) the grid is finer where it matters - around the model and where the camera is and looks - and wider
# towards the edges (Luca: a 3 km mountain had a point every 6 m next to the model). A tensor grid: the columns and the
# rows have their own spacing, finest inside the «focus» box, growing by GRID_GROW a cell outside it. No cracks,
# the zones and the cut stay the same code; the mesh has as many points as the even grid had, or fewer.
FINE = {"normale": 2.0, "alto": 1.5, "massimo": 1.0}      # metres between the points in the focus box (at best)
FOCUS_R = 60.0                       # metres of fine grid around the model, the camera and where it looks
FOCUS_MAX = 900.0                    # the focus box at most this wide (a camera far away: the model only)
GRID_GROW = 1.06
BLEND_REACH = 12.0                   # (1.76.4) metres of distance to the next zone kept in the mesh (the widest blend)
BLEND_FAR = 60.0                     # stored for «no zone near» (and for its own zone)
BLEND_UV = ("simpler_tb01", "simpler_tb23", "simpler_tb45")   # (UV maps: the view gets them as uv1..uv3 from the glTF)
ZONE_N = 512                         # the even grid the zones are decided on (in metres, whatever the mesh)
GEN_N = 384


PRESET_DEFAULTS = {"montagne": {"rockSlope": 45.0, "snow": True, "snowHeight": 0.65}}


def _params(data, base=None):
    p = json.loads(json.dumps(base or DEFAULTS))
    for k, v in (data or {}).items():
        if k in DEFAULTS:
            if isinstance(DEFAULTS[k], dict) and isinstance(v, dict):
                p[k] = dict(p[k], **v)
            else:
                p[k] = v
    if p["preset"] not in T.PRESETS and not p.get("heightmap"):
        raise ApiError(tr("Tipo di terreno sconosciuto"))
    if (base is None or ("preset" in (data or {}) and base.get("preset") != p["preset"])) and "rocky" not in (data or {}):
        p["rocky"] = ROCKY_DEF.get(p["preset"], 0.4) if not p.get("heightmap") else 0.0    # (a real place: as it is)
    if base is None and "tone" not in (data or {}):
        p["tone"] = dict(TONE_DEF)
    if base is None and "edgeNatural" not in (data or {}):
        p["edgeNatural"] = True
    if isinstance(p.get("tone"), dict) and isinstance((base or {}).get("tone"), dict) and isinstance((data or {}).get("tone"), dict):
        p["tone"] = dict(base["tone"], **data["tone"])
    # (1.76.25) a real elevation file (USGS .dem, SRTM .hgt, ESRI .asc): its true width and relief, and no erosion of
    # ours on top (a real place, as it is) - unless the call says otherwise; then they can be changed as usual
    hm = (data or {}).get("heightmap")
    if not hm and "hmCrop" in (data or {}):
        hm = p.get("heightmap")                       # (another square of the same file)
    if hm and (hm != (base or {}).get("heightmap") or "hmCrop" in (data or {})) \
            and os.path.splitext(hm)[1].lower() in _dem_exts():
        from . import dem
        if hm != (base or {}).get("heightmap") and "hmCrop" not in (data or {}):
            p["hmCrop"] = []
        try:
            inf = dem.info(hm, p.get("hmCrop") or None)
            # (1.76.34, Luca: «non ci serve portare 100 km di terreno») at most dem.MAX_SIDE: a file bigger than that
            # and no square chosen - its middle
            if not p.get("hmCrop") and inf["size"] > dem.MAX_SIDE + 1.0:
                side = dem.DEFAULT_SIDE / inf["full"]
                p["hmCrop"] = [0.5 - side / 2, 0.5 - side / 2, side]
                inf = dem.info(hm, p["hmCrop"])
        except Exception as exc:  # noqa: BLE001
            raise ApiError(tr("Questo file di quote non si legge: {0}", str(exc)[:120]))
        p["size"] = float(inf["size"])
        p["hmHeight"] = max(1.0, float(inf["height"]))
        if "hmErosion" not in (data or {}):
            p["hmErosion"] = 0.0
    # a new preset brings its own look (montagne: rock only on the real walls, snow up high), unless the call sets it
    if "preset" in (data or {}) and (base is None or base.get("preset") != p["preset"]):
        for k, v in PRESET_DEFAULTS.get(p["preset"], {}).items():
            if k not in data:
                p[k] = v
        for k in ("rockSlope", "snow", "snowHeight"):
            if k not in data and k not in PRESET_DEFAULTS.get(p["preset"], {}):
                p[k] = DEFAULTS[k]
    return p


# ---------------------------------------------------------------- the height field

def _dem_exts():
    from . import dem
    return dem.EXTS


def _load_heightmap(path, n, crop=None):
    """A grey image as heights 0..1 (16 bit and float kept: Blender reads them as float); (1.76.25) or a real
    elevation file (dem.py)."""
    if not path or not os.path.isfile(path):
        raise ApiError(tr("Mappa di altezze non trovata"))
    ext = os.path.splitext(path)[1].lower()
    if ext in _dem_exts():
        from . import dem
        try:
            a, _cell = dem.read_cached(path)
        except Exception as exc:  # noqa: BLE001
            raise ApiError(tr("Questo file di quote non si legge: {0}", str(exc)[:120]))
        a = dem.crop(a, crop or None)                # (1.76.34: the square chosen)
        a = a.astype(np.float32)[::-1]               # (rows from the south, as the images once read)
    elif ext in (".raw", ".r16"):
        raw = np.fromfile(path, dtype="<u2")
        side = int(round(math.sqrt(raw.size)))
        if side * side != raw.size:
            raise ApiError(tr("File RAW non quadrato: servono N × N valori a 16 bit"))
        a = raw.reshape(side, side).astype(np.float32) / 65535.0
        a = a[::-1]                                  # (the first row is the top of the picture)
    else:
        im = bpy.data.images.load(path, check_existing=False)
        try:
            im.colorspace_settings.name = "Non-Color"
            w, h = im.size
            px = np.empty(w * h * im.channels, dtype=np.float32)
            im.pixels.foreach_get(px)
            px = px.reshape(h, w, im.channels)
            a = px[..., :3].mean(axis=2) if im.channels >= 3 else px[..., 0]
        finally:
            bpy.data.images.remove(im)
    side = min(a.shape)
    a = a[:side, :side]
    a = (a - a.min()) / max(1e-9, float(np.ptp(a)))
    return T.resample(a.astype(np.float32), n)


_FIELD = {"key": None, "f": None}
FIELD_KEYS = ("preset", "size", "height", "seed", "rough", "direction", "erosion", "age", "heightmap", "hmHeight", "hmErosion",
              "hmCrop")


def _field(p, prog=None):
    """(1.76.8) The last field is kept: a change that does not touch the shape (a split, the snow, the spianata) does
    not run the erosion again (montagne: ~25 s)."""
    key = json.dumps({k: p.get(k) for k in FIELD_KEYS}, sort_keys=True, default=str)
    if _FIELD["key"] == key and _FIELD["f"] is not None:
        return _FIELD["f"]
    # (1.76.48, Luca: «ancora molto lento») also on disk: the first change after opening the scene again ran the
    # erosion again (15 s on a mountain of 3 km)
    f = _field_disk(key)
    if f is None:
        f = _field_make(p, prog)
        _field_disk(key, f)
    _FIELD.update(key=key, f=f)
    return f


def _field_disk(key, f=None):
    """The field of these parameters from the disk cache (f None) or into it. The key carries the code of the
    generation (terrain_gen.py, this file): a change of the formulas does not read an old field; a height map
    carries its file's date and size."""
    import hashlib
    try:
        from . import diskcache
        d = diskcache.folder("terrcache")
        src = _FIELD.get("src")
        if src is None:
            # (1.76.51, audit) the code that makes the field: the generator and the two functions of this file, not
            # the whole file - every new version touching the terrain lost the cache (15 s at the first edit, Luca)
            import inspect
            h_ = hashlib.sha1()
            with open(T.__file__, "rb") as fh:
                h_.update(fh.read())
            h_.update((inspect.getsource(_field_make) + inspect.getsource(_load_heightmap) + str(GEN_N)).encode("utf-8"))
            src = _FIELD["src"] = h_.hexdigest()
        kk = json.loads(key)
        hm = kk.get("heightmap") or ""
        if hm and os.path.isfile(hm):
            kk["_hm"] = [os.path.getmtime(hm), os.path.getsize(hm)]
        name = hashlib.sha1((json.dumps(kk, sort_keys=True, default=str) + src).encode("utf-8")).hexdigest()[:24] + ".npz"
        path = os.path.join(d, name)
        if f is None:
            if not os.path.isfile(path):
                return None
            with np.load(path, allow_pickle=False) as z:
                out = {k: (z[k].item() if z[k].ndim == 0 else z[k]) for k in z.files}
            os.utime(path)
            print(f"SIMPLER_TERRAIN field from the disk cache ({name})", flush=True)
            return out
        os.makedirs(d, exist_ok=True)
        arrs = {k: np.asarray(v) for k, v in f.items() if isinstance(v, (np.ndarray, float, int, str, np.floating, np.integer))}
        tmp = path + ".tmp.npz"
        np.savez(tmp, **arrs)
        os.replace(tmp, path)
        diskcache.prune("terrcache")
    except Exception as exc:  # noqa: BLE001  (the cache is only a help)
        print("SIMPLER_TERRAIN field cache:", exc, flush=True)
    return None


def _field_make(p, prog=None):
    """{"h", "flow", "deposit", "slope"...} on the generation grid, in metres."""
    if p.get("heightmap"):
        size = float(p.get("size") or 1000.0)
        height = float(p.get("hmHeight") or 100.0)
        h = _load_heightmap(p["heightmap"], GEN_N, p.get("hmCrop"))
        flow = np.zeros_like(h); dep = np.zeros_like(h)
        if float(p.get("hmErosion") or 0) > 0:
            h, flow, dep, _w = T.hydraulic(h, 1.0, drops=float(p["hmErosion"]), life=30, inertia=0.05, capacity=4.0,
                                           min_slope=0.01, erode=0.3, deposit=0.3, evaporate=0.01, gravity=4.0,
                                           progress=prog)
            h = (h - h.min()) / max(1e-6, float(np.ptp(h)))
        return {"h": h * height, "flow": flow, "deposit": dep * height, "size": size, "height": height}
    r = T.generate(p["preset"], n=GEN_N, size=p.get("size"), height=p.get("height"), seed=int(p.get("seed") or 1),
                   rough=float(p["rough"]), direction=float(p["direction"]), erosion=float(p["erosion"]),
                   age=float(p["age"]), progress=prog)
    return r


def _axis(L, a, b, s0, smax):
    """The coordinates along one side (-L/2 .. L/2): every s0 inside [a, b], then wider by GRID_GROW a cell up to
    smax towards the ends (the last cell made to end on the edge)."""
    a, b = max(-L / 2, min(a, b)), min(L / 2, max(a, b))
    n_in = max(1, int(math.ceil((b - a) / s0)))
    mid = list(np.linspace(a, b, n_in + 1))
    left, x, sp = [], a, s0
    while x > -L / 2 + 1e-6:
        sp = min(sp * GRID_GROW, smax)
        x -= sp
        left.append(max(x, -L / 2))
    right, x, sp = [], b, s0
    while x < L / 2 - 1e-6:
        sp = min(sp * GRID_GROW, smax)
        x += sp
        right.append(min(x, L / 2))
    xs = np.array(left[::-1] + mid + right, dtype=np.float64)
    xs = np.unique(np.round(xs, 6))
    # (a last cell much smaller than the one before: merged into it)
    if len(xs) > 3 and xs[1] - xs[0] < 0.35 * (xs[2] - xs[1]):
        xs = np.delete(xs, 1)
    if len(xs) > 3 and xs[-1] - xs[-2] < 0.35 * (xs[-2] - xs[-3]):
        xs = np.delete(xs, -2)
    return xs


def _focus(p, size):
    """The box of fine grid: around the model (the centre of the spianata, or the middle) and, when they are not too
    far, around the camera and the point it looks at. -> (x0, x1, y0, y1)"""
    fl = p.get("flat") or {}
    pts = [(float(fl.get("x", 0.0)), float(fl.get("y", 0.0)))]
    r0 = max(FOCUS_R, float(fl.get("radius", 30.0)) + float(fl.get("soft", 40.0)) * 0.5 if fl.get("on") else FOCUS_R)
    box = [pts[0][0] - r0, pts[0][0] + r0, pts[0][1] - r0, pts[0][1] + r0]
    try:
        from .ecosystems import _cam_now
        cam = _cam_now()
        for q in (cam["target"], cam["pos"]):
            if abs(q[0]) > size / 2 or abs(q[1]) > size / 2:
                continue
            nb = [min(box[0], q[0] - FOCUS_R), max(box[1], q[0] + FOCUS_R), min(box[2], q[1] - FOCUS_R), max(box[3], q[1] + FOCUS_R)]
            if nb[1] - nb[0] <= FOCUS_MAX and nb[3] - nb[2] <= FOCUS_MAX:
                box = nb
    except Exception:
        pass
    return box


def _grid(p, size):
    """The coordinates of the columns and of the rows of the mesh (1-D, metres): fine (FINE) in the focus box, and
    towards the edges the smallest spacing that keeps within the point budget (the even grid's)."""
    nmax = MESH_N.get(p.get("detail"), 512)
    s0 = FINE.get(p.get("detail"), 2.0)
    box = _focus(p, size)
    fits = lambda s0_, sm: max(len(_axis(size, box[0], box[1], s0_, sm)), len(_axis(size, box[2], box[3], s0_, sm))) <= nmax
    while not fits(s0, size):                     # (the focus box alone too many points: a little coarser there)
        s0 *= 1.15
    lo, hi = s0, size
    for _ in range(30):                           # (the finest spacing towards the edges that still fits)
        mid = math.sqrt(lo * hi)
        if fits(s0, mid):
            hi = mid
        else:
            lo = mid
    return _axis(size, box[0], box[1], s0, hi), _axis(size, box[2], box[3], s0, hi)


def _interp(src_n, size, dst, cubic=True):
    """Matrix (len(dst) × src_n) that samples a field given on an even grid of src_n points over -size/2..size/2
    at the coordinates dst: Catmull-Rom (smooth: no creases of the coarse grid on the fine mesh) or linear."""
    u = np.clip((np.asarray(dst, np.float64) / size + 0.5) * (src_n - 1), 0.0, src_n - 1.0)
    i = np.clip(np.floor(u).astype(np.int64), 0, src_n - 2)
    t = u - i
    W = np.zeros((len(u), src_n), np.float64)
    rows = np.arange(len(u))
    if not cubic:
        W[rows, i] += 1 - t
        W[rows, i + 1] += t
        return W
    w = [-0.5 * t ** 3 + t ** 2 - 0.5 * t, 1.5 * t ** 3 - 2.5 * t ** 2 + 1, -1.5 * t ** 3 + 2 * t ** 2 + 0.5 * t, 0.5 * t ** 3 - 0.5 * t ** 2]
    for k, wk in zip((-1, 0, 1, 2), w):
        np.add.at(W, (rows, np.clip(i + k, 0, src_n - 1)), wk)
    return W


def _sample(a, size, xs, ys, cubic=True):
    """A field on an even grid sampled on the tensor grid (ys × xs)."""
    n = a.shape[0]
    return (_interp(n, size, ys, cubic) @ a.astype(np.float64) @ _interp(n, size, xs, cubic).T).astype(np.float32)


def _fbm_band(X, Y, spacing, perm, base, octaves):
    """fBm with the octaves finer than twice the local spacing of the grid faded out (no shimmer of detail the
    mesh cannot hold where it is wide)."""
    out = np.zeros_like(X)
    amp, f, tot = 1.0, 1.0 / base, 0.0
    for _ in range(octaves):
        lam = 1.0 / f
        w = np.clip((lam / np.maximum(spacing, 1e-3) - 2.0) / 2.0, 0.0, 1.0)
        out += amp * w * T.noise(X * f, Y * f, perm)
        tot += amp
        amp *= 0.5
        f *= 2.0
    return out / max(tot, 1e-6) * 1.6


# (1.76.10) «Roccia scolpita»: the rock is cut into ledges and cliffs, crests and gullies are sharper (Luca: «tutto
# sembra troppo liscio e sinuoso ... non montagne rocciose»). On the mesh, as a function of the place (the same on
# every grid), where the field is steep: strata (benches and risers, thickness changing from layer to layer, tilted,
# their lines bent), a broken surface (ridged noise) and the crests and gullies of the field made sharper. Terrains
# made before have no «rocky»: unchanged.
ROCKY_DEF = {"pianura": 0.1, "colline": 0.35, "valle": 0.65, "montagne": 0.8, "dune": 0.0, "canyon": 0.8}


def _rock_masks(p, f):
    """slope (degrees, smoothed) and relative height on the field's grid, and the field's crests and gullies
    (height minus its blur) - kept with the field."""
    c = f.get("_rock")
    if c is not None:
        return c
    hf = np.asarray(f["h"], np.float32)
    n = hf.shape[0]
    cell = float(f["size"]) / (n - 1)
    hs = T.smooth(hf, 1)
    gy, gx = np.gradient(hs, cell)
    slope = np.degrees(np.arctan(np.hypot(gx, gy))).astype(np.float32)
    rel = (hf - hf.min()) / max(1e-6, float(np.ptp(hf)))
    # crests and gullies about 3-6 cells wide (montagne 25-45 m, colline 10-20 m)
    detail = hf - T.smooth(hf, 6)
    g2y, g2x = np.gradient(T.smooth(hf, 3), cell)
    c = {"slope": T.smooth(slope, 2), "rel": rel.astype(np.float32), "detail": detail.astype(np.float32),
         "gx": g2x.astype(np.float32), "gy": g2y.astype(np.float32)}
    f["_rock"] = c
    return c


def _fall_noise(X, Y, gx, gy, lam, stretch, perm, tile):
    """Noise stretched along the fall line (gx, gy: the slope), about -1..1: tiles of the size «tile», each with the
    direction of its centre (no twist of the pattern where the direction turns), blended bilinearly."""
    tx, ty = X / tile, Y / tile
    i0, j0 = np.floor(tx - 0.5), np.floor(ty - 0.5)
    fx, fy = tx - 0.5 - i0, ty - 0.5 - j0
    out = np.zeros_like(X)
    wsum = np.zeros_like(X)
    # the direction at the tile centres: the slope where the point is, averaged over the tile is too costly; the
    # direction of each tile is taken from the slope field sampled at its centre (nearest point of the grid)
    xs, ys = X[0], Y[:, 0]
    for di in (0, 1):
        for dj in (0, 1):
            ci, cj = i0 + di, j0 + dj
            cx, cy = (ci + 0.5) * tile, (cj + 0.5) * tile
            ix = np.clip(np.searchsorted(xs, cx), 0, len(xs) - 1)
            iy = np.clip(np.searchsorted(ys, cy), 0, len(ys) - 1)
            ax, ay = gx[iy, ix], gy[iy, ix]
            L = np.maximum(np.hypot(ax, ay), 1e-6)
            ax, ay = ax / L, ay / L
            u = ((X - cx) * -ay + (Y - cy) * ax) / lam                  # across the fall line
            v = ((X - cx) * ax + (Y - cy) * ay) / (lam * stretch)       # along it
            w = (fx if di else 1 - fx) * (fy if dj else 1 - fy)
            w = w * w * (3 - 2 * w)
            out += w * T.noise(u + ci * 7.31 + cj * 3.17, v + ci * 1.93 - cj * 5.71, perm)
            wsum += w
    return out / np.maximum(wsum, 1e-6)


def _smoothstep(a, b, x):
    t = np.clip((x - a) / (b - a), 0.0, 1.0)
    return t * t * (3 - 2 * t)


def rock_settings(p):
    """The «Roccia scolpita» parameters with their defaults (thickness 0: from the height of the terrain)."""
    rocky = p.get("rocky")
    rocky = 0.0 if rocky is None else max(0.0, min(1.0, float(rocky)))
    height = float(p.get("height") or T.PRESETS.get(p.get("preset"), {}).get("height") or p.get("hmHeight") or 100.0)
    thick = float(p.get("strataThick") or 0.0)
    if thick <= 0:
        thick = float(np.clip(height / 25.0, 4.0, 25.0))
    return {"rocky": rocky, "strata": max(0.0, min(1.0, float(p.get("strata", 0.6)))),
            "sharp": max(0.0, min(1.0, float(p.get("sharp", 0.5)))), "thick": thick,
            "dip": max(0.0, min(40.0, float(p.get("strataDip", 8.0))))}


def _strata_u(p, X, Y, h):
    """The layer coordinate of the rock (layers of rock_settings' thickness, tilted, their lines bent, thicker and
    thinner): the ledges of «Roccia scolpita» and the bands of «Colori dal terreno» follow the same layers."""
    rs = rock_settings(p)
    T0 = rs["thick"]
    seed = int(p.get("seed") or 1)
    perm = T._perm(np.random.default_rng(seed + 313))
    perm2 = T._perm(np.random.default_rng(seed + 314))
    a = math.radians(seed * 47.0 % 360.0)
    tilt = math.tan(math.radians(rs["dip"]))
    bend = 1.4 * T.fbm(X / (T0 * 10.0), Y / (T0 * 10.0), perm, 3, gain=0.5) + 0.45 * T.fbm(X / (T0 * 2.5) + 9.1, Y / (T0 * 2.5), perm2, 2)
    s_ = h + tilt * (X * math.cos(a) + Y * math.sin(a)) + T0 * bend
    u = s_ / T0
    return (u + 0.45 * T.noise(u * 0.37 + 3.1, np.full_like(u, 0.71), perm2)).astype(np.float32)   # (thickness from layer to layer)


ROCK_KINDS = ("attuale", "canaloni", "fratture", "cenge")
# (1.76.54) how much of each part of the rock's shape every kind of «Rilievo 3D» has: crests sharpened, ledges of the
# layers, gullies down the slope (strength, width × T0), broken surface, blocks of the joints
ROCK_MIX = {
    "attuale": {"crest": 1.0, "ledge": 1.0, "gully": 1.0, "gully_w": 1.0, "gully2": 0.0, "rough": 1.0, "blocks": 0.0, "massive": 1.0},
    "canaloni": {"crest": 1.4, "ledge": 0.25, "gully": 2.2, "gully_w": 1.6, "gully2": 0.9, "rough": 0.7, "blocks": 0.0, "massive": 1.0},
    "fratture": {"crest": 0.8, "ledge": 0.3, "gully": 0.35, "gully_w": 1.0, "gully2": 0.0, "rough": 0.5, "blocks": 1.0, "massive": 1.0},
    "cenge": {"crest": 0.7, "ledge": 2.6, "gully": 0.45, "gully_w": 1.0, "gully2": 0.0, "rough": 0.8, "blocks": 0.0, "massive": 0.0},
}


def rock_kind(p):
    """(1.76.54) The kind of «Rilievo 3D» of the rock's shape, its size (× the thickness of the layers) and its
    orientation (degrees): a terrain made before - «Attuale», 1, 0 (the shape as it was)."""
    k = p.get("rockKind")
    k = k if k in ROCK_KINDS else "attuale"
    return k, max(0.25, min(4.0, float(p.get("rockSize") or 1.0))), max(-90.0, min(90.0, float(p.get("rockOrient") or 0.0)))


def _hash2(i, j, seed):
    """A random number 0..1 per pair of integers (a block of the joints): the same everywhere for the same pair."""
    v = np.sin(i * 127.1 + j * 311.7 + seed * 74.7) * 43758.5453
    return v - np.floor(v)


def _rock_blocks(X, Y, h, T0, orient, perm, seed, spacing):
    """«Parete fratturata» in the shape: the wall cut by two sets of vertical joints across each other (turned by
    the orientation) and a dipping one into blocks; each block stands out or is set back by its own amount and is a
    little tilted - at each joint a step. The lines of the joints wander a little. Metres."""
    a = math.radians(orient)
    ca, sa = math.cos(a), math.sin(a)
    wx = T.noise(X / (T0 * 2.0) + 5.3, Y / (T0 * 2.0) - 1.7, perm)
    wy = T.noise(X / (T0 * 2.0) - 8.1, Y / (T0 * 2.0) + 3.9, perm)
    a1 = (X * ca + Y * sa) / (T0 * 0.9) + 0.35 * wx
    a2 = (-X * sa + Y * ca + 0.3 * h) / (T0 * 0.65) + 0.35 * wy
    a3 = h / (T0 * 0.8) + 0.25 * (X * ca + Y * sa) / T0 + 0.3 * wx
    i1, i2, i3 = np.floor(a1), np.floor(a2), np.floor(a3)
    f1, f2, f3 = a1 - i1 - 0.5, a2 - i2 - 0.5, a3 - i3 - 0.5
    r0 = _hash2(i1 + i3 * 57.0, i2, seed)
    r1 = _hash2(i1, i2 + i3 * 31.0, seed + 1)
    r2 = _hash2(i2, i1 - i3 * 13.0, seed + 2)
    out = (r0 - 0.5) * 0.7 * T0 + f1 * (r1 - 0.5) * 0.8 * T0 + f2 * (r2 - 0.5) * 0.6 * T0 + f3 * (r0 - 0.5) * 0.5 * T0
    # (blocks smaller than the grid holds: nothing - a step every point would be noise)
    return out * np.clip((0.65 * T0 / np.maximum(spacing, 1e-3) - 0.8) / 1.2, 0.0, 1.0)


def _rock_relief(p, f, X, Y, h, spacing, u=None):
    """The change of height (metres) on the mesh points (X, Y, h: the height sampled from the field). (1.76.54) In
    the parts and amounts of the kind of «Rilievo 3D» (ROCK_MIX; «Attuale»: as before), sized × its Dimensione."""
    rs = rock_settings(p)
    if rs["rocky"] <= 0:
        return np.zeros_like(h)
    kind, ksize, korient = rock_kind(p)
    mix = ROCK_MIX[kind]
    size = float(f["size"])
    m = _rock_masks(p, f)
    xs, ys = X[0], Y[:, 0]
    S = lambda a: _sample(a, size, xs, ys, cubic=False)
    slope = S(m["slope"])
    rel = S(m["rel"])
    rock_lim = float(p.get("rockSlope", 35.0))
    seed = int(p.get("seed") or 1)
    perm = T._perm(np.random.default_rng(seed + 313))
    perm2 = T._perm(np.random.default_rng(seed + 314))
    # where: the steep parts (from a bit below the rock's slope), more up high; a little everywhere steep enough
    R = _smoothstep(rock_lim - 24.0, rock_lim - 2.0, slope) * (0.7 + 0.3 * rel)
    steep = _smoothstep(12.0, 30.0, slope)
    out = np.zeros_like(h)
    # 1. crests and gullies of the field sharper (less «sinuous»)
    out += mix["crest"] * rs["rocky"] * rs["sharp"] * 1.3 * steep * S(m["detail"])
    # 2. strata: benches and risers - not a staircase: the lines bend, the layers change thickness and hardness,
    # some are strong and some hardly there, whole patches of the wall are massive (no ledges)
    T0 = rs["thick"] * ksize
    if u is None:
        u = _strata_u(p, X, Y, h)
    uu = u / ksize
    q = np.floor(uu)
    fr = uu - q
    r1 = 0.5 + 0.5 * T.noise(q * 0.61 + 1.3, np.full_like(q, 4.2), perm2)
    r2 = 0.5 + 0.5 * T.noise(q * 0.43 + 7.7, np.full_like(q, 2.9), perm)
    hard = 0.5 + 0.35 * r1                                                       # share of the bench
    bench = 0.1
    g = np.where(fr < hard, bench * fr / hard, bench + (1.0 - bench) * _smoothstep(0.0, 1.0, (fr - hard) / (1.0 - hard)))
    layer = 0.15 + 0.85 * _smoothstep(0.4, 0.75, r2)                             # strong and faint layers
    massive = _smoothstep(-0.35, 0.25, T.fbm(X / (T0 * 6.0) + 4.4, Y / (T0 * 6.0) - 2.2, perm2, 3))
    massive = mix["massive"] * massive + (1.0 - mix["massive"]) * 0.85             # («cenge»: ledges everywhere)
    band = np.clip((T0 / np.maximum(spacing, 1e-3) - 1.5) / 1.5, 0.0, 1.0)          # (not finer than the grid holds)
    ks = min(1.0, rs["rocky"] * rs["strata"] * 2.0) * mix["ledge"]
    Rs = _smoothstep(rock_lim - 18.0, rock_lim + 2.0, slope)                     # (ledges only on the real walls)
    out += ks * Rs * band * layer * (0.25 + 0.75 * massive) * (g - fr) * T0
    # 3. gullies down the slope: creases of a noise stretched along the fall line, cutting the ledges
    gxs, gys = S(m["gx"]), S(m["gy"])
    lam_a = T0 * 1.0 * mix["gully_w"]
    wa = np.clip((lam_a / np.maximum(spacing, 1e-3) - 2.0) / 2.0, 0.0, 1.0)
    gn = _fall_noise(X, Y, gxs, gys, lam_a, 4.0, perm, T0 * 6.0)
    gul = 1.0 - _smoothstep(0.0, 0.6, np.abs(gn))                               # 1 in the crease
    out -= mix["gully"] * rs["rocky"] * rs["sharp"] * (0.3 * steep + 0.7 * R) * wa * gul * 0.6 * T0
    if mix["gully2"] > 0:
        # («canaloni»: smaller gullies branching between the big ones)
        lam_b = T0 * 0.55
        wb = np.clip((lam_b / np.maximum(spacing, 1e-3) - 2.0) / 2.0, 0.0, 1.0)
        gn2 = _fall_noise(X + 37.0 * T0, Y - 21.0 * T0, gxs, gys, lam_b, 5.0, perm2, T0 * 4.0)
        gul2 = 1.0 - _smoothstep(0.0, 0.5, np.abs(gn2))
        out -= mix["gully2"] * rs["rocky"] * rs["sharp"] * (0.3 * steep + 0.7 * R) * wb * gul2 * 0.35 * T0
    if mix["blocks"] > 0:
        out += mix["blocks"] * rs["rocky"] * (0.25 * steep + 0.75 * R) * _rock_blocks(X, Y, h, T0, korient, perm2, seed, spacing)
    rough = np.zeros_like(h)
    amp, lam, tot = 1.0, T0 * 2.0, 0.0
    for o in range(5):
        w = np.clip((lam / np.maximum(spacing, 1e-3) - 2.0) / 2.0, 0.0, 1.0)
        if not w.any():
            break                                       # (finer octaves: the grid holds none of them)
        r = 1.0 - np.abs(T.noise(X / lam + o * 13.7, Y / lam - o * 7.3, perm2))
        rough += amp * w * (r * r - 0.45)
        tot += amp
        amp *= 0.6
        lam *= 0.5
    out += mix["rough"] * rs["rocky"] * rs["sharp"] * (0.35 + 0.65 * R) * steep * rough / max(tot, 1e-6) * T0 * 1.0
    return out.astype(np.float32)


TONE_UV = ("simpler_tc1", "simpler_tc2")
TONE_SHADER = 2         # (1.76.43) creases and streaks in groups, not a comb
TONE_DEF = {"on": True, "streaks": 0.5, "bands": 0.5, "ridges": 0.5, "wet": 0.5, "relief": 0.5}


def tone_of(g):
    """The «Colori dal terreno» of a terrain: what was set on it (POST terrain/tone: on the group), else what it was
    made with (its params; None on terrains made before 1.76.14)."""
    raw = g.get("simpler_terrain_tone") if g is not None else None
    if raw:
        try:
            return tone_settings({"tone": json.loads(raw)})
        except ValueError:
            pass
    return tone_settings(_current(g)) if g is not None else None


def set_tone(data):
    """POST terrain/tone {id, on, streaks, bands, ridges, wet, relief}: the colours guided by the land (materials only: the
    geometry stays - a terrain made before 1.76.14 has no data for them: made again first). Undo: «deep» on the
    zones and the group (their materials, its setting)."""
    g = _group(data.get("id"))
    # (1.76.41) a terrain made before 1.76.14, only its relief asked: the colours stay off
    t = tone_of(g) or dict(TONE_DEF, on=False)
    for k in TONE_DEF:
        if k in data:
            t[k] = bool(data[k]) if k == "on" else max(0.0, min(1.0, float(data[k])))
    # (1.76.53) «Rilievo 3D»: the kind and the numbers (a value at its default leaves the setting)
    from . import matedit
    # (1.76.58) the maps of «Rilievo 3D» given as files: images of the project (as the maps of the materials)
    for fk, k in (("rmapFile", "rmap"), ("rcolorFile", "rcolor")):
        path = data.get(fk)
        if isinstance(path, str) and path:
            if not os.path.isfile(path):
                raise ApiError(tr("File non trovato: {0}", path))
            data[k] = bpy.data.images.load(path, check_existing=True).name
    rd = {k: t.get(k, d) for k, d in matedit.RELIEF_DEF.items()}
    rd.update({k: data[k] for k in matedit.RELIEF_DEF if k in data})
    for k in matedit.RELIEF_DEF:
        t.pop(k, None)
    t.update(_relief3d(rd))
    g["simpler_terrain_tone"] = json.dumps(t)
    ids = sync_blend(g)
    return {"id": g[ID_KEY], "tone": t, "geometry": [], "terrainBlend": ids}


def tone_settings(p):
    """(1.76.14) «Colori dal terreno»: None on terrains made before (their colours as they were)."""
    t = p.get("tone")
    if not isinstance(t, dict):
        return None
    out = dict(TONE_DEF)
    out.update({k: v for k, v in t.items() if k in TONE_DEF})
    for k in ("streaks", "bands", "ridges", "wet", "relief"):
        out[k] = max(0.0, min(1.0, float(out[k])))
    out["on"] = bool(out["on"])
    out.update(_relief3d(t))
    return out


def _relief3d(t):
    """(1.76.53) «Rilievo 3D»: its kind and numbers - only those not at their default (a terrain with the relief as
    before keeps the same materials: nothing made again when it is opened)."""
    from . import matedit
    out = {}
    for k, d in matedit.RELIEF_DEF.items():
        v = t.get(k)
        if v is None:
            continue
        if k == "rtype":
            v = v if v in matedit.RELIEF_TYPES else d
        elif k in ("rdisp", "rmanti"):
            v = bool(v)
        elif k in ("rmap", "rcolor"):
            v = str(v or "")
        else:
            lo, hi = matedit.RELIEF_RANGE[k]
            v = round(max(lo, min(hi, float(v))), 4)
        if v != d:
            out[k] = v
    return out


def _tone_data(p, f, xs, ys, h, u):
    """Per point of the mesh: (crest 1 / gully 0, water + 1, layer of the rock). The crest from the field's crests
    and gullies (tens of metres) and from the mesh's own (a few metres); the water as «Dividi zona» reads it."""
    size, height = float(f["size"]), float(f["height"])
    m = _rock_masks(p, f)
    S = lambda a: _sample(a, size, xs, ys, cubic=False)
    T0 = rock_settings(p)["thick"]
    hh = np.asarray(h, np.float32)
    fine = hh - T.smooth(T.smooth(hh, 2), 2)
    conv = np.tanh(S(m["detail"]) / max(0.5, 0.012 * height) + fine / max(0.3, 0.25 * T0))
    n = int(f["h"].shape[0])
    flow = np.asarray(f["flow"], np.float32) if f.get("flow") is not None and np.ptp(f["flow"]) > 0 else np.zeros((n, n), np.float32)
    dep = np.asarray(f["deposit"], np.float32) if f.get("deposit") is not None and np.ptp(f["deposit"]) > 0 else np.zeros((n, n), np.float32)
    flow = flow / max(1e-9, float(np.percentile(flow, 99)))
    dep = dep / max(1e-9, float(np.percentile(dep, 99)))
    wet = np.clip(S(T.smooth(flow * 0.6 + dep * 0.8, 2)), 0.0, 1.0)
    return np.stack([0.5 + 0.5 * conv, 1.0 + wet, u], -1).astype(np.float32)


def _mesh_field(p, f, xs, ys, extra=None):
    """The height on the grid of the mesh (rows ys × columns xs, metres), with a fine detail the generation grid
    cannot hold, the «spianata» and the edge brought to 0. Returns (h, size, flat weight). extra (a dict): gets
    «u», the layer coordinate of the rock (1.76.14: the colours of the terrain)."""
    size, height = float(f["size"]), float(f["height"])
    h = _sample(f["h"], size, xs, ys)
    X, Y = np.meshgrid(xs.astype(np.float32), ys.astype(np.float32))
    perm = T._perm(np.random.default_rng(int(p.get("seed") or 1) + 77))
    gy, gx = np.gradient(h, ys, xs)
    steep = np.clip(np.degrees(np.arctan(np.hypot(gx, gy))) / 30.0, 0.15, 1.0)
    dx = np.gradient(xs)[None, :]
    dy = np.gradient(ys)[:, None]
    spacing = np.maximum(dx, dy).astype(np.float32)
    u = _strata_u(p, X, Y, h) if extra is not None else None
    if extra is not None:
        extra["u"] = u
    h = h + _rock_relief(p, f, X, Y, h, spacing, u)
    # (fine detail: a few decimetres on flat ground, more on slopes - where the eye expects broken ground; down to
    # about a metre where the grid is fine)
    h = h + steep * (0.004 * height + 0.15) * _fbm_band(X, Y, spacing, perm, 25.0, 6)
    w_flat = np.zeros_like(h)
    fl = p.get("flat") or {}
    if fl.get("on"):
        d = np.hypot(X - float(fl.get("x", 0.0)), Y - float(fl.get("y", 0.0)))
        r, sft = max(0.0, float(fl.get("radius", 30.0))), max(0.5, float(fl.get("soft", 40.0)))
        u = np.clip((d - r) / sft, 0.0, 1.0)
        w_flat = 1.0 - u * u * (3 - 2 * u)
    if p.get("edge", True):
        band = 0.08 * size
        de = np.minimum.reduce([X + size / 2, size / 2 - X, Y + size / 2, size / 2 - Y])
        if p.get("edgeNatural"):
            # (1.76.19) the edge not a straight ramp along the square: the low ground reaches in here and there by
            # up to 3.2 bands (bays, with headlands between them) - with the sea at the foot of the terrain the coast
            # is a natural line, not the square of the terrain (Luca's screenshot: a straight shore)
            pe = T._perm(np.random.default_rng(int(p.get("seed") or 1) + 991))
            nb = T.fbm(X / (0.22 * size) + 5.3, Y / (0.22 * size) - 2.7, pe, 5, gain=0.5)
            reach = np.clip(0.45 + 1.3 * nb, 0.0, 1.0) * 3.2 * band
            de = de - reach
        u = np.clip(de / band, 0.0, 1.0)
        w_edge = u * u * (3 - 2 * u)
    else:
        w_edge = np.ones_like(h)
    if extra is not None:
        extra["edge"] = w_edge          # (1.76.22: no stones on the ramp of the edge, scree.py)
    # the level 0: where the model stands (centre of the spianata), or the lowest edge
    if fl.get("on"):
        ix = int(np.argmin(np.abs(xs - float(fl.get("x", 0)))))
        iy = int(np.argmin(np.abs(ys - float(fl.get("y", 0)))))
        base = float(h[iy, ix])
    else:
        base = float(np.percentile(np.concatenate([h[0], h[-1], h[:, 0], h[:, -1]]), 20))
    h = (h - base) * (1.0 - w_flat)
    # the outer edge down to the lowest point of the terrain: the ground of the Ambiente is put there (_ground_level),
    # so no part of the terrain is hidden under it and there is no step where they meet
    low = float(h.min())
    # (1.76.44) «Scultura»: the strokes of the brush on the shape (before the edge: it still goes down to the same
    # level; the lowest point of before - a hole dug does not move the edge)
    if p.get("sculpt"):
        h = _apply_sculpt(p["sculpt"], xs, ys, h)
    h = low + (h - low) * w_edge
    return h.astype(np.float32), size, w_flat


# ---- (1.76.44, Luca: «il pennello per alzare e abbassare la geometria del terreno») «Scultura». A stroke: the
# tool, the radius (m), the intensity (0..1), the softness of the edge (0..1) and its dabs [x, y] in metres of the
# terrain (the zone meshes' own coordinates), as the view stamped them while the mouse moved - the view deforms
# its meshes with the same formulas (viewer.js terrainDab), the engine replays them on every grid the terrain is
# made on (the mesh, the even grid of the zones): so they stay when the terrain is made again (another version,
# size, detail).
SCULPT_TOOLS = ("raise", "lower", "smooth")
SCULPT_RATE = 0.03          # a dab of «Alza» at 100%: this part of the radius at the centre
SCULPT_SMOOTH = 0.5         # a dab of «Liscia» at 100%: this part of the way to the plane of the ground around
SCULPT_MAX_STROKES = 4000
SCULPT_MAX_DABS = 400000


def _sculpt_falloff(d, soft):
    """1 inside, 0 at the radius (d: distance / radius); soft 0 = a hard edge, 1 = soft from the centre."""
    inner = 1.0 - max(0.05, min(1.0, float(soft)))
    t = np.clip((d - inner) / max(1e-3, 1.0 - inner), 0.0, 1.0)
    return 1.0 - t * t * (3 - 2 * t)


def sculpt_clean(strokes):
    """The strokes as they are kept: known tools, numbers in range, dabs rounded to the centimetre."""
    out, dabs = [], 0
    for s in (strokes or [])[:SCULPT_MAX_STROKES]:
        if not isinstance(s, dict) or s.get("tool") not in SCULPT_TOOLS:
            continue
        pts = []
        for q in s.get("pts") or []:
            try:
                pts.append([round(float(q[0]), 2), round(float(q[1]), 2)])
            except (TypeError, ValueError, IndexError):
                continue
        if not pts or dabs + len(pts) > SCULPT_MAX_DABS:
            continue
        dabs += len(pts)
        out.append({"tool": s["tool"], "r": round(max(0.5, min(3000.0, float(s.get("r", 10.0)))), 3),
                    "k": round(max(0.0, min(1.0, float(s.get("k", 0.5)))), 3),
                    "soft": round(max(0.0, min(1.0, float(s.get("soft", 0.7)))), 3), "pts": pts})
    return out


def _apply_sculpt(strokes, xs, ys, h):
    """The strokes on the heights h (rows ys × columns xs, metres), in order. -> new array."""
    h = np.array(h, np.float64)
    xs = np.asarray(xs, np.float64)
    ys = np.asarray(ys, np.float64)
    for s in strokes:
        tool, r, k, soft = s.get("tool"), float(s.get("r", 10.0)), float(s.get("k", 0.5)), float(s.get("soft", 0.7))
        if tool not in SCULPT_TOOLS or r <= 0 or k <= 0:
            continue
        for q in s.get("pts") or []:
            x, y = float(q[0]), float(q[1])
            i0, i1 = np.searchsorted(xs, x - r), np.searchsorted(xs, x + r, side="right")
            j0, j1 = np.searchsorted(ys, y - r), np.searchsorted(ys, y + r, side="right")
            if i0 >= i1 or j0 >= j1:
                continue
            X, Y = np.meshgrid(xs[i0:i1], ys[j0:j1])
            f = _sculpt_falloff(np.hypot(X - x, Y - y) / r, soft)
            sub = h[j0:j1, i0:i1]
            if tool == "raise":
                sub += f * (SCULPT_RATE * r * k)
            elif tool == "lower":
                sub -= f * (SCULPT_RATE * r * k)
            else:
                # «Liscia»: towards the plane that fits the ground under the brush (weighted): the bumps go, the
                # slope stays
                w = f.ravel()
                if w.sum() < 1e-6 or len(w) < 3:
                    continue
                A = np.stack([np.ones_like(w), (X.ravel() - x) / r, (Y.ravel() - y) / r], 1)
                Aw = A * w[:, None]
                try:
                    c = np.linalg.solve(A.T @ Aw + np.eye(3) * 1e-9, Aw.T @ sub.ravel())
                except np.linalg.LinAlgError:
                    continue
                plane = (A @ c).reshape(sub.shape)
                sub += (plane - sub) * f * (SCULPT_SMOOTH * k)
            h[j0:j1, i0:i1] = sub
    return h


def _zones(p, f, xs, ys, w_flat):
    """The zone of every point of the mesh (rows ys × columns xs). The fields that decide it (slope, water, height,
    hollows, the noise of the borders) are made on an even grid of ZONE_N - the zones have the same shapes in metres
    whatever the spacing of the mesh - and then sampled on the mesh, where the thresholds are taken."""
    size = float(f["size"])
    n = ZONE_N
    xu = np.linspace(-size / 2, size / 2, n)
    h, _s, _w = _mesh_field(p, f, xu, xu)
    cell = size / (n - 1)
    gy, gx = np.gradient(h, cell)
    slope = np.degrees(np.arctan(np.hypot(gx, gy)))
    t = np.linspace(0.0, 1.0, n, dtype=np.float32)
    X, Y = np.meshgrid(t, t)
    perm = T._perm(np.random.default_rng(int(p.get("seed") or 1) + 101))
    irr = float(p.get("irregular", 0.5))
    nz = T.fbm(X * size / 40.0, Y * size / 40.0, perm, 4, gain=0.55)          # -1..1, borders broken
    flow = T.resample(f["flow"], n) if f.get("flow") is not None and np.ptp(f["flow"]) > 0 else np.zeros_like(h)
    dep = T.resample(f["deposit"], n) if f.get("deposit") is not None and np.ptp(f["deposit"]) > 0 else np.zeros_like(h)
    flow = flow / max(1e-9, float(np.percentile(flow, 99)))
    dep = dep / max(1e-9, float(np.percentile(dep, 99)))
    rel = (h - h.min()) / max(1e-6, float(np.ptp(h)))
    lap = (np.roll(h, 1, 0) + np.roll(h, -1, 0) + np.roll(h, 1, 1) + np.roll(h, -1, 1) - 4 * h) / (cell * cell)
    # smooth fields first (no speckles of one face), then sampled on the mesh, then the thresholds
    S = lambda a: _sample(a, size, xs, ys, cubic=False)
    slope_s = S(T.smooth(slope, 2))
    wet = S((T.smooth(flow, 2) * 0.6 + T.smooth(dep, 2) * 0.8) * float(p.get("gravel", 0.5)) + irr * 0.15 * nz)
    nzm = S(nz)
    relm = S(rel)
    hol = S(np.clip(T.smooth(lap, 2) * cell, -0.05, 0.05))
    z = np.zeros(slope_s.shape, np.int8)                         # prato
    # bare rock comes sooner up high and later down low (soil and plants hold on lower slopes): the walls of a valley
    # are green at the foot and rock towards the crests, not one grey wall
    rock_lim = float(p.get("rockSlope", 35.0)) + irr * 6.0 * nzm + 12.0 * (0.55 - relm)
    if p.get("preset") == "dune" and not p.get("heightmap"):
        z[:] = ZONES.index("sabbia")
    else:
        z[(wet > 0.35) & (slope_s < rock_lim)] = ZONES.index("terra")
        z[(slope_s > rock_lim - 6.0) & (slope_s <= rock_lim)] = ZONES.index("terra")     # scree at the foot of rock
        z[slope_s > rock_lim] = ZONES.index("roccia")
        if p.get("snow"):
            # (1.76.12, Luca: «non mi sembra nell'altezza giusta ... confini netti») the snow line is not a contour:
            # it goes up and down in patches (large and small), lower in hollows and gullies, higher on crests in the
            # wind; above it the snow holds on steeper ground the higher it is (ledges of the walls, not only the
            # gentle slopes down low) - the slope a little less smoothed, so the ledges keep it
            sh0 = float(p.get("snowHeight", 0.75))
            big = S(T.fbm(X * size / 160.0 + 3.7, Y * size / 160.0 - 1.9, perm, 3, gain=0.5))
            sh = sh0 + irr * 0.05 * nzm + 0.04 * big - hol
            slope_1 = S(T.smooth(slope, 1))
            above = np.clip((relm - sh) / 0.18, 0.0, 1.0)
            snow_lim = 36.0 + 16.0 * above + 5.0 * nzm
            z[(relm > sh) & (slope_1 < snow_lim)] = ZONES.index("neve")
    z[w_flat > 0.5] = ZONES.index("spianata")
    keys = zone_keys(p)
    sps = splits_of(p)
    if sps:
        # the fields a split can follow, on the mesh
        lap_s = T.smooth(lap, 3)
        wetf = S(T.smooth(flow * 0.6 + dep * 0.8, 3) + np.clip(lap_s * cell * 20.0, -1.0, 1.0) * 0.3)
        sx, sy = _sun_xy()
        nn = np.sqrt(1.0 + gx * gx + gy * gy)
        sunf = S(T.smooth((-gx * sx - gy * sy) / nn, 2))
        shapef = S(-lap_s)
        Xm, Ym = np.meshgrid(xs.astype(np.float32), ys.astype(np.float32))
        area = np.gradient(xs)[None, :] * np.gradient(ys)[:, None]
        fields = {"wet": lambda sp: wetf, "sun": lambda sp: sunf, "alt": lambda sp: relm, "slope": lambda sp: slope_s,
                  "shape": lambda sp: shapef}
        for sp in sps:
            par = keys.index(sp["zone"])
            mask = z == par
            if not mask.any():
                continue
            kind, sign = SPLIT_RULES[sp["rule"]]
            seed_ = int(p.get("seed") or 1) * 131 + keys.index(sp["id"])
            perm_s = T._perm(np.random.default_rng(seed_))
            if kind == "patch":
                sz = max(2.0, float(sp.get("size", 40.0)))
                sc = T.fbm(Xm / sz, Ym / sz, perm_s, 4, gain=0.5)
            else:
                sc = fields[kind](sp) * sign
            # the rank of every point inside its zone, by area (a fine grid near the model does not count more)
            v = sc[mask]
            w = area[mask]
            order = np.argsort(v, kind="stable")
            cum = np.empty(len(v))
            cum[order] = np.cumsum(w[order]) / max(1e-9, float(w.sum()))
            irr_s = max(0.0, min(1.0, float(sp.get("irregular", 0.5))))
            nzs = T.fbm(Xm[mask] / 30.0, Ym[mask] / 30.0, perm_s, 4, gain=0.55)
            take = (cum + irr_s * 0.25 * nzs) > 1.0 - max(0.0, min(1.0, float(sp.get("amount", 0.4))))
            idx = np.nonzero(mask)
            z[idx[0][take], idx[1][take]] = keys.index(sp["id"])
    return _majority(_majority(z, len(keys)), len(keys))           # (per vertex: triangles take their zone below)


def _majority(z, k):
    """Every face takes the zone most of its 3 × 3 neighbourhood has (ties: its own): no single faces, smoother
    borders."""
    counts = np.zeros((k,) + z.shape, np.int16)
    pad = np.pad(z, 1, mode="edge")
    n0, n1 = z.shape
    for dy in (0, 1, 2):
        for dx in (0, 1, 2):
            w = pad[dy:dy + n0, dx:dx + n1]
            for i in range(k):
                counts[i] += (w == i)
    best = counts.argmax(axis=0).astype(np.int8)
    own = np.take_along_axis(counts, z[None].astype(np.int64), 0)[0]
    return np.where(own >= counts.max(axis=0), z, best).astype(np.int8)


def _diagonals(h):
    """(1.76.12) Which diagonal splits every cell of the grid: the one whose middle is nearer the height the
    surface has in the middle of the cell (cubic estimate from the 4 × 4 points around). A crest or a gully across
    the cell stays one line of edges instead of a row of teeth (Luca: «creste a dente di sega», in the snow above
    all - its line follows the slope of the triangles). Where both are as good: alternating (no grain).
    -> (ny - 1, nx - 1) bool: True = the diagonal from (0, 1) to (1, 0)."""
    H = np.pad(np.asarray(h, np.float64), 1, mode="edge")
    mx = (-H[:, :-3] + 9 * H[:, 1:-2] + 9 * H[:, 2:-1] - H[:, 3:]) / 16.0            # (rows, nx - 1): middle in x
    hc = (-mx[:-3] + 9 * mx[1:-2] + 9 * mx[2:-1] - mx[3:]) / 16.0                     # (ny - 1, nx - 1)
    h = np.asarray(h, np.float64)
    d_main = np.abs((h[:-1, :-1] + h[1:, 1:]) * 0.5 - hc)        # diagonal (0,0)-(1,1)
    d_anti = np.abs((h[:-1, 1:] + h[1:, :-1]) * 0.5 - hc)        # diagonal (0,1)-(1,0)
    ny, nx = h.shape
    checker = (np.arange(ny - 1)[:, None] + np.arange(nx - 1)[None, :]) % 2 == 1
    tie = np.abs(d_main - d_anti) < 1e-4 + 1e-3 * np.abs(h[:-1, :-1] - h[1:, 1:])
    return np.where(tie, checker, d_anti < d_main)


def _cut(zv, h, xs, ys, normals, k=None, data=None):
    """The faces of every zone, with borders that are smooth curves: the zone map is turned into one soft field per
    zone (its share of the neighbourhood), and the triangles where two or three zones meet are cut where those fields
    are equal - not along the edges of the grid (no staircase, no teeth). The new points lie on the triangle they
    cut and are computed once per edge, so the meshes of two zones meet without a crack.
    Returns (co (m × 3), normals (m × 3), {zone index: triangles (t × 3)}) - and with data (values per point of the
    grid, n × c) those values on every point too (interpolated as the normals), last."""
    ny, nx = zv.shape
    k = k or len(ZONES)
    S = np.empty((k, ny, nx), np.float32)
    for i in range(k):
        S[i] = T.smooth((zv == i).astype(np.float32), 3)
    lab = S.argmax(0).astype(np.int8)
    S = S.reshape(k, -1)
    lv = lab.ravel()
    idx = np.arange(ny * nx).reshape(ny, nx)
    v00 = idx[:-1, :-1].ravel(); v10 = idx[:-1, 1:].ravel(); v01 = idx[1:, :-1].ravel(); v11 = idx[1:, 1:].ravel()
    flip = _diagonals(h).ravel()
    t1 = np.where(flip[:, None], np.stack([v00, v10, v01], 1), np.stack([v00, v10, v11], 1))
    t2 = np.where(flip[:, None], np.stack([v10, v11, v01], 1), np.stack([v00, v11, v01], 1))
    tris = np.concatenate([t1, t2], 0)
    L = lv[tris]
    X, Y = np.meshgrid(xs, ys)
    co = np.stack([X.ravel(), Y.ravel(), h.ravel()], 1).astype(np.float32)
    nm = normals.reshape(-1, 3)
    out = {i: [] for i in range(k)}
    same = (L[:, 0] == L[:, 1]) & (L[:, 1] == L[:, 2])
    for i in range(k):
        out[i].append(tris[same & (L[:, 0] == i)])
    mixed = tris[~same]
    dt = None if data is None else np.asarray(data, np.float32).reshape(ny * nx, -1)
    if mixed.shape[0] == 0:
        res = (co, nm, {i: np.concatenate(v) for i, v in out.items()})
        return res if dt is None else res + (dt,)
    Lm = L[~same]
    # the points on the edges between two zones (one per edge, shared by the two triangles on it)
    ea = np.concatenate([mixed[:, [0, 1]], mixed[:, [1, 2]], mixed[:, [2, 0]]])
    ea = ea[lv[ea[:, 0]] != lv[ea[:, 1]]]
    ea = np.unique(np.sort(ea, 1), axis=0)
    a0, a1 = ea[:, 0], ea[:, 1]
    la, lb = lv[a0], lv[a1]
    d0 = S[la, a0] - S[lb, a0]
    d1 = S[la, a1] - S[lb, a1]
    w = np.clip(d0 / np.maximum(1e-6, d0 - d1), 0.15, 0.85)[:, None]
    base = ny * nx
    co_e = co[a0] * (1 - w) + co[a1] * w
    nm_e = nm[a0] * (1 - w) + nm[a1] * w
    ekey = a0.astype(np.int64) * base + a1          # (sorted: np.unique sorts the rows)

    def edge(u, v):
        return base + np.searchsorted(ekey, np.minimum(u, v).astype(np.int64) * base + np.maximum(u, v))

    # two corners alike: turned so the odd one is the third
    two = ~((Lm[:, 0] != Lm[:, 1]) & (Lm[:, 1] != Lm[:, 2]) & (Lm[:, 0] != Lm[:, 2]))
    m2, l2 = mixed[two], Lm[two]
    odd = np.where(l2[:, 0] == l2[:, 1], 2, np.where(l2[:, 1] == l2[:, 2], 0, 1))
    rot = (odd[:, None] + 1 + np.arange(3)[None, :]) % 3
    m2 = np.take_along_axis(m2, rot, 1)
    l2 = np.take_along_axis(l2, rot, 1)
    p12 = edge(m2[:, 1], m2[:, 2]); p20 = edge(m2[:, 2], m2[:, 0])
    q_a = np.concatenate([np.stack([m2[:, 0], m2[:, 1], p12], 1), np.stack([m2[:, 0], p12, p20], 1)])
    z_a = np.concatenate([l2[:, 0], l2[:, 0]])
    q_b = np.stack([p20, p12, m2[:, 2]], 1)
    z_b = l2[:, 2]
    # three different zones: the centre of the triangle too
    m3, l3 = mixed[~two], Lm[~two]
    cid = base + ea.shape[0] + np.arange(m3.shape[0])
    co_c = co[m3].mean(1)
    nm_c = nm[m3].mean(1)
    p01 = edge(m3[:, 0], m3[:, 1]); p12 = edge(m3[:, 1], m3[:, 2]); p20 = edge(m3[:, 2], m3[:, 0])
    q_c, z_c = [], []
    for v, pin, pout in ((0, p01, p20), (1, p12, p01), (2, p20, p12)):
        q_c += [np.stack([m3[:, v], pin, cid], 1), np.stack([m3[:, v], cid, pout], 1)]
        z_c += [l3[:, v], l3[:, v]]
    q = np.concatenate([q_a, q_b] + q_c)
    z = np.concatenate([z_a, z_b] + z_c)
    for i in range(k):
        out[i].append(q[z == i])
    co = np.concatenate([co, co_e, co_c]).astype(np.float32)
    nm = np.concatenate([nm, nm_e, nm_c])
    nm = (nm / np.linalg.norm(nm, axis=1, keepdims=True)).astype(np.float32)
    res = (co, nm, {i: np.concatenate(v).astype(np.int64) for i, v in out.items()})
    if dt is None:
        return res
    return res + (np.concatenate([dt, dt[a0] * (1 - w) + dt[a1] * w, dt[m3].mean(1)]).astype(np.float32),)


def _border_dist(co, parts, size):
    """(1.76.4) For every point of the terrain: how far it is from the border with another zone (metres, up to
    BLEND_REACH) and which two zones meet there. A map from above (chamfer, 8 neighbours) started on the borders -
    the sides of the triangles that two zones share, sampled every half cell - read back bilinear for the distance.
    -> (dist (m,), za (m,), zb (m,)): the pair of the nearest border (za < zb), -1 where none is within reach."""
    tri_all = np.concatenate([parts[i] for i in range(len(parts))])
    zid = np.concatenate([np.full(len(parts[i]), i, np.int8) for i in range(len(parts))])
    nv = len(co)
    m = len(co)
    far = np.full(m, BLEND_FAR, np.float32)
    none = np.full(m, -1, np.int8)
    if not len(tri_all):
        return far, none, none.copy(), {}
    e = np.concatenate([tri_all[:, [0, 1]], tri_all[:, [1, 2]], tri_all[:, [2, 0]]])
    e = np.sort(e, axis=1).astype(np.int64)
    ez = np.concatenate([zid, zid, zid])
    key = e[:, 0] * nv + e[:, 1]
    order = np.argsort(key, kind="stable")
    key, ez, e = key[order], ez[order], e[order]
    same_next = key[1:] == key[:-1]
    diff = same_next & (ez[1:] != ez[:-1])
    idx = np.nonzero(diff)[0]
    if not len(idx):
        return far, none, none.copy(), {}
    be = e[idx]
    za = np.minimum(ez[idx], ez[idx + 1])
    zb = np.maximum(ez[idx], ez[idx + 1])
    pk, pc = np.unique(za.astype(np.int64) * 256 + zb, return_counts=True)
    pairs = {(int(k_ // 256), int(k_ % 256)): int(c_) for k_, c_ in zip(pk, pc)}      # (how long each border is)
    cell = max(0.5, size / 1024.0)
    n = int(size / cell) + 3
    lo = -size / 2 - cell
    P0, P1 = co[be[:, 0]].astype(np.float64), co[be[:, 1]].astype(np.float64)
    L = np.linalg.norm((P1 - P0)[:, :2], axis=1)
    k = np.maximum(1, np.ceil(L / (cell * 0.5)).astype(np.int64))
    seg = np.repeat(np.arange(len(be)), k)
    t = (np.arange(int(k.sum())) - np.repeat(np.cumsum(k) - k, k) + 0.5) / np.repeat(k, k)
    Q = P0[seg][:, :2] + (P1[seg] - P0[seg])[:, :2] * t[:, None]
    D = np.full((n, n), np.inf, np.float32)
    A = np.full((n, n), -1, np.int8)
    B = np.full((n, n), -1, np.int8)
    ix = np.clip(((Q[:, 0] - lo) / cell).round().astype(np.int64), 0, n - 1)
    iy = np.clip(((Q[:, 1] - lo) / cell).round().astype(np.int64), 0, n - 1)
    D[iy, ix] = 0.0
    A[iy, ix] = za[seg]
    B[iy, ix] = zb[seg]
    for _ in range(int(math.ceil(BLEND_REACH / cell)) + 1):
        changed = False
        for dy, dx, w in ((0, 1, 1.0), (0, -1, 1.0), (1, 0, 1.0), (-1, 0, 1.0),
                          (1, 1, 1.4142), (1, -1, 1.4142), (-1, 1, 1.4142), (-1, -1, 1.4142)):
            ys = slice(max(dy, 0), n + min(dy, 0)); yd = slice(max(-dy, 0), n + min(-dy, 0))
            xs = slice(max(dx, 0), n + min(dx, 0)); xd = slice(max(-dx, 0), n + min(-dx, 0))
            cand = D[yd, xd] + np.float32(w * cell)
            dst = D[ys, xs]
            better = cand < dst
            if better.any():
                dst[better] = cand[better]
                A[ys, xs][better] = A[yd, xd][better]
                B[ys, xs][better] = B[yd, xd][better]
                changed = True
        if not changed:
            break
    D = np.where(np.isfinite(D), D, BLEND_FAR).astype(np.float32)
    # bilinear distance, nearest pair
    fx = np.clip((co[:, 0] - lo) / cell, 0, n - 1.001)
    fy = np.clip((co[:, 1] - lo) / cell, 0, n - 1.001)
    x0, y0 = fx.astype(np.int64), fy.astype(np.int64)
    tx, ty = fx - x0, fy - y0
    dist = (D[y0, x0] * (1 - tx) * (1 - ty) + D[y0, x0 + 1] * tx * (1 - ty) + D[y0 + 1, x0] * (1 - tx) * ty
            + D[y0 + 1, x0 + 1] * tx * ty).astype(np.float32)
    rx, ry = np.round(fx).astype(np.int64), np.round(fy).astype(np.int64)
    pa, pb = A[ry, rx].copy(), B[ry, rx].copy()
    on = np.zeros(m, bool)                          # (the points on a border: exactly 0)
    on[be.ravel()] = True
    dist[on] = 0.0
    pa[be[:, 0]], pb[be[:, 0]] = za, zb
    pa[be[:, 1]], pb[be[:, 1]] = za, zb
    dist[dist > BLEND_REACH] = BLEND_FAR
    pa[dist >= BLEND_FAR], pb[dist >= BLEND_FAR] = -1, -1
    return dist, pa, pb, pairs


def _blend_uv(zone_i, dist, pa, pb, pairs, prev=None):
    """The three UV maps of a zone: in 6 slots, the distance to each of its neighbours (+1: 0 means «no data», a
    material shared with another object never blends there; BLEND_FAR + 1 where it is not the one across the nearest
    border). (1.76.8) The slots are the zone's own neighbours, the longest borders first - not the six zones of
    every terrain: with the parts of «Dividi zona» a terrain has up to 16. -> (uv maps, neighbour indices)."""
    m = len(dist)
    nb = sorted(((c, (b if a == zone_i else a)) for (a, b), c in pairs.items() if zone_i in (a, b)), reverse=True)
    nb = [j for _c, j in nb][:6]
    if prev:
        # (1.76.47) the neighbours of before keep their slots: the materials know the zone in each slot, and a new
        # order (the borders a little longer or shorter after a sculpting) made every material of the terrain again
        # - 18 s for nothing (Luca: «tutto super lento»)
        keep = [j if j in nb else None for j in prev[:6]]
        rest = [j for j in nb if j not in keep]
        nb = [j if j is not None else (rest.pop(0) if rest else None) for j in keep] + rest
        while nb and nb[-1] is None:
            nb.pop()
        nb = nb[:6]
    across = np.where(pa == zone_i, pb, np.where(pb == zone_i, pa, -1)).astype(np.int64)
    slot = np.full(max(256, len(nb) + 1), -1, np.int64)
    for k_, j in enumerate(nb):
        if j is not None:
            slot[j] = k_
    out = np.full((m, 6), BLEND_FAR + 1.0, np.float32)
    ok = across >= 0
    sl = np.where(ok, slot[np.clip(across, 0, len(slot) - 1)], -1)
    ok &= sl >= 0
    out[np.nonzero(ok)[0], sl[ok]] = dist[ok] + 1.0
    return [out[:, 2 * j:2 * j + 2] for j in range(3)], nb


def _zone_mesh(name, co, tris, normals, extra=None, tone=None):
    """A mesh with the triangles of one zone (its vertices copied from the whole terrain: the same positions on the
    border of the next zone), smooth, with the normals of the whole terrain."""
    me = bpy.data.meshes.new(name)
    if tris.shape[0] == 0:
        return me
    used = np.unique(tris)
    remap = np.full(co.shape[0], -1, np.int64)
    remap[used] = np.arange(used.size)
    q = remap[tris]
    me.vertices.add(used.size)
    me.vertices.foreach_set("co", co[used].ravel())
    me.loops.add(q.size)
    me.loops.foreach_set("vertex_index", q.ravel().astype(np.int32))
    me.polygons.add(q.shape[0])
    me.polygons.foreach_set("loop_start", (np.arange(q.shape[0]) * 3).astype(np.int32))
    me.update(calc_edges=True)
    me.validate(clean_customdata=False)
    try:
        me.shade_smooth()
    except AttributeError:
        for poly in me.polygons:
            poly.use_smooth = True
    try:
        me.normals_split_custom_set_from_vertices(normals[used].tolist())
    except (AttributeError, RuntimeError, TypeError):
        pass
    # a plain UV in metres first (a material projected by UV gets a sensible one), then the distances to the other
    # zones (the blend of the borders: matedit edge_blend, viewer useEdgeBlend)
    lv = q.ravel()
    uvs = [("UVMap", co[used][:, :2])] + ([(BLEND_UV[j], extra[j][used]) for j in range(3)] if extra is not None else [])
    for nm, vals in uvs:
        lay = me.uv_layers.new(name=nm)
        if lay is not None:
            lay.data.foreach_set("uv", np.ascontiguousarray(vals[lv], dtype=np.float32).ravel())
    if tone is not None and extra is not None:
        # (1.76.14) «Colori dal terreno»: crest/gully and water (+ 2: 0 = a mesh without the data), layer of the rock -
        # per point, two more UV maps after the three of the blend (the export keeps them as floats, colours not:
        # the view reads them as texcoord_4 and texcoord_5; matedit tone_color by name)
        tv = tone[used]
        for nm, vals in ((TONE_UV[0], np.stack([tv[:, 0], tv[:, 1] + 1.0], 1)), (TONE_UV[1], np.stack([tv[:, 2], np.zeros_like(tv[:, 2])], 1))):
            lay = me.uv_layers.new(name=nm)
            if lay is not None:
                lay.data.foreach_set("uv", np.ascontiguousarray(vals[lv], dtype=np.float32).ravel())
    if me.uv_layers.get("UVMap") is not None:
        me.uv_layers.active = me.uv_layers["UVMap"]
        try:
            me.uv_layers["UVMap"].active_render = True
        except AttributeError:
            pass
    return me


def _normals(h, xs, ys):
    gy, gx = np.gradient(h, ys, xs)
    nz = np.ones_like(h)
    v = np.stack([-gx, -gy, nz], -1)
    return (v / np.linalg.norm(v, axis=-1, keepdims=True)).astype(np.float32)


def _placeholder(zone):
    from . import matedit
    name = tr("Terreno") + " · " + tr(ZONE_NAMES[zone])
    mat = bpy.data.materials.get(name)
    if mat is not None and mat.get(PLACEHOLDER):
        return mat
    mat = bpy.data.materials.new(name)
    col, rough = ZONE_COLORS[zone]
    prm = json.loads(json.dumps(matedit.DEFAULTS))
    prm["color"]["tint"] = list(col)
    prm["roughness"]["value"] = rough
    matedit.apply(mat, prm)
    mat[PLACEHOLDER] = zone
    return mat


def _split_material(g, p, key):
    """The first material of a new part: a copy of its zone's material (its own, under the blend), a little lighter
    or darker as its rule suggests; a plain colour zone gives a plain colour."""
    from . import matedit
    sp = _split(p, key) or {}
    zs = zone_objects(g)
    par = zs.get(sp.get("zone", ""))
    src = source_of(par.material_slots[0].material) if par is not None and par.material_slots else None
    name = tr("Terreno") + " · " + zone_label(p, key)
    mat = src.copy() if src is not None else _placeholder(root_zone(p, key)).copy()
    mat.name = name
    prm = matedit.params_of(mat)
    if prm is not None:
        prm = json.loads(json.dumps(prm))
        prm.pop("blend", None)
        b, sat = SPLIT_TWEAK.get(sp.get("rule"), (1.0, 1.0))
        prm["color"]["brightness"] = float(prm["color"].get("brightness", 1.0)) * b
        prm["color"]["saturation"] = float(prm["color"].get("saturation", 1.0)) * sat
        matedit.apply(mat, prm)
    for k in (DERIVED, "simpler_blend_key", "simpler_blend_base"):
        if k in mat:
            del mat[k]
    if mat.get("simpler_terrain_material"):
        mat["simpler_terrain_material"] = root_zone(p, key)
    mat["simpler_split_rule"] = sp.get("rule", "")
    return mat


def _group(gid):
    g = find(gid)
    if not g.get(KEY):
        if g.parent is not None and g.parent.get(KEY):         # (a zone: its terrain)
            return g.parent
        raise ApiError(tr("Non è un terreno"))
    return g


def _current(g):
    zs = zone_objects(g)
    raw = zs["prato"].data.get(KEY) if zs.get("prato") is not None and zs["prato"].data is not None else None
    return json.loads(raw or g.get(KEY) or "{}")


def zone_objects(g, trashed=False):
    """zone -> object (not the ones in the trash: parts of «Dividi zona» an undo took away, unless trashed)."""
    return {o.get(ZONE_KEY): o for o in g.children if isinstance(o.get(ZONE_KEY), str) and o.get(ZONE_KEY)
            and (trashed or not o.get("simpler_trashed"))}


def _build(p, prog_from=0.0, prev_nb=None):
    progress.update(tr("Forma del terreno"), prog_from, "")
    f = _field(p, lambda x: progress.update(None, prog_from + 0.75 * x))
    progress.update(tr("Zone e geometrie"), 0.8, "")
    xs, ys = _grid(p, float(f["size"]))
    ex = {}
    h, size, w_flat = _mesh_field(p, f, xs, ys, ex)
    zv = _zones(p, f, xs, ys, w_flat)
    keys = zone_keys(p)
    co, nm, parts, tone = _cut(zv, h, xs, ys, _normals(h, xs, ys), k=len(keys), data=_tone_data(p, f, xs, ys, h, ex["u"]))
    t_b = time.time()
    bd = _border_dist(co, parts, size)
    print(f"SIMPLER_TERRAIN borders {time.time() - t_b:.2f} s", flush=True)
    print(f"SIMPLER_TERRAIN grid {len(xs)} × {len(ys)}, {np.diff(xs).min():.2f} - {np.diff(xs).max():.2f} m", flush=True)
    meshes = {}
    for i, zone in enumerate(keys):
        prev = [keys.index(z) if z in keys else -1 for z in (prev_nb or {}).get(zone, [])] if prev_nb else None
        uvs, nb = _blend_uv(i, *bd, prev=prev)
        meshes[zone] = _zone_mesh(tr("Terreno") + " · " + zone_label(p, zone), co, parts[i], nm, uvs, tone)
        meshes[zone][KEY] = json.dumps(p)
        meshes[zone]["simpler_tb_nb"] = json.dumps([keys[j] if j is not None else "" for j in nb])     # (the zone in each slot of the blend)
    return meshes, {"size": size, "height": float(np.ptp(h)), "min": float(h.min()), "max": float(h.max()),
                    "edge": float(h[0, 0]) if p.get("edge", True) else None,
                    "grid": {"n": [int(len(xs)), int(len(ys))], "fine": round(float(min(np.diff(xs).min(), np.diff(ys).min())), 2),
                             "coarse": round(float(max(np.diff(xs).max(), np.diff(ys).max())), 2),
                             "focus": [round(float(v), 1) for v in _focus(p, size)]}}


def _ground_level(info):
    """The ground of the Ambiente at the level of the terrain's edge (its lowest point): the parts of the terrain
    below 0 are not hidden under it. Back to its place when no terrain is left (ground_reset)."""
    from . import ambience
    ob = ambience._find_flag(ambience.GROUND_KEY)
    if ob is None or info.get("edge") is None:
        return
    if "simpler_ground_z0" not in ob:
        ob["simpler_ground_z0"] = float(ob.location.z)
    ob.location.z = min(float(ob["simpler_ground_z0"]), info["edge"] - 0.004)


# ---------------------------------------------------------------- API

def create(data):
    """POST terrain/create {params}: a new terrain (group «Terreno» with one mesh per zone). Undo: kind «objects»."""
    p = _assign_split_ids(_params(data))
    t0 = time.time()
    progress.begin("terrain", tr("Creazione del terreno"))
    try:
        meshes, info = _build(p)
        g = link(bpy.data.objects.new(tr("Terreno"), None))
        g[KIND_KEY] = "group"
        g[KEY] = json.dumps(p)
        g.empty_display_size = 1.0
        zones = {}
        for zone in zone_keys(p):
            ob = link(bpy.data.objects.new(meshes[zone].name, meshes[zone]))
            ob[ZONE_KEY] = zone
            ob.parent = g
            ob.data.materials.append(_placeholder(zone) if zone in ZONES else _split_material(g, p, zone))
            zones[zone] = ob[ID_KEY]
    finally:
        progress.end()
    _ground_level(info)
    refresh()
    _start_downloads(p, meshes)
    sync_blend(g)
    print(f"SIMPLER_TERRAIN create {p['preset']} {info} {time.time() - t0:.1f} s", flush=True)
    return {"id": g[ID_KEY], "zones": zones, "info": info, "params": p, "textures": textures_for(p)}


def update(data):
    """POST terrain/update {id, params}: the terrain made again with the new parameters (the zone objects stay: their
    names, materials, ecosystems on them). Undo: kind «meshes» (the old meshes come back, with their parameters)."""
    from . import decimate
    g = _group(data.get("id"))
    zs = zone_objects(g)
    prm = dict(data.get("params") or {})
    base = _params(_current(g))
    if "sculptAdd" in prm:
        # (1.76.44) the strokes of a session of «Scultura», added to those before (one undo step)
        prm["sculpt"] = list(base.get("sculpt") or []) + list(prm.pop("sculptAdd") or [])
    if "sculpt" in prm:
        prm["sculpt"] = sculpt_clean(prm["sculpt"])
    if any(k in prm for k in ("rockKind", "rockSize", "rockOrient")):
        # (1.76.54) a kind of «Rilievo 3D» chosen: no longer «Nessuno» in the shading
        t_ = tone_of(g)
        if t_ and t_.get("rtype") == "nessuno":
            t_.pop("rtype", None)
            g["simpler_terrain_tone"] = json.dumps(t_)
    p = _params(prm, base=base)
    _assign_split_ids(p, zone_objects(g, trashed=True).keys())
    t0 = time.time()
    progress.begin("terrain", tr("Terreno"))
    prev_nb = {}
    for z_, ob_ in zs.items():
        try:
            prev_nb[z_] = json.loads(ob_.data.get("simpler_tb_nb") or "[]") if ob_.data is not None else []
        except ValueError:
            pass
    try:
        meshes, info = _build(p, prev_nb=prev_nb)
    finally:
        progress.end()
    decimate.SWAPS.clear()
    decimate.ADDED.clear()
    keys = zone_keys(p)
    for zone in keys:
        ob = zs.get(zone)
        new = meshes[zone]
        if ob is None:
            # (a new part of «Dividi zona», or a zone added by a later version: its object, with an empty mesh that
            # the new one replaces - Ctrl+Z gives the empty one back, the zone it came from whole again)
            ob = link(bpy.data.objects.new(new.name, bpy.data.meshes.new(new.name)))
            decimate.ADDED.append(ob[ID_KEY])          # (history: Ctrl+Z puts it in the trash, Ctrl+Y back)
            ob[ZONE_KEY] = zone
            ob.parent = g
            ob.data.materials.append(_placeholder(zone) if zone in ZONES else _split_material(g, p, zone))
            zs[zone] = ob
        elif zone not in ZONES and (ob.data is None or not len(ob.data.polygons)):
            # (a part made again with the name of one taken away before: its material if the rule is the same)
            cur_m = ob.material_slots[0].material if ob.material_slots else None
            if cur_m is None or source_of(cur_m).get("simpler_split_rule") != (_split(p, zone) or {}).get("rule"):
                if ob.material_slots:
                    ob.material_slots[0].material = _split_material(g, p, zone)
                else:
                    ob.data.materials.append(_split_material(g, p, zone))
        old = ob.data
        for i, m in enumerate(old.materials):     # (the materials of the zone go with it)
            new.materials.append(m)
        ob.data = new
        new["simpler_decimated_from"] = old.name      # (decimate.after_open: the old one dropped when reopened)
        old.use_fake_user = True
        decimate.SWAPS.append((old.name, new.name))
    for zone, ob in zs.items():
        if zone in keys or ob.data is None or not len(ob.data.polygons):
            continue
        # (a part taken away: its object stays, with an empty mesh - Ctrl+Z gives it back)
        old = ob.data
        new = bpy.data.meshes.new(old.name)
        for m in old.materials:
            new.materials.append(m)
        new[KEY] = json.dumps(p)
        ob.data = new
        new["simpler_decimated_from"] = old.name
        old.use_fake_user = True
        decimate.SWAPS.append((old.name, new.name))
    g[KEY] = json.dumps(p)
    _ground_level(info)
    refresh()
    _start_downloads(p, meshes)
    blended = sync_blend(g)
    eco = _regrow_ecosystems(zone_objects(g))
    print(f"SIMPLER_TERRAIN update {p['preset']} {info} {time.time() - t0:.1f} s", flush=True)
    ids = [o[ID_KEY] for o in zone_objects(g).values()]
    return {"id": g[ID_KEY], "zones": {z: o[ID_KEY] for z, o in zone_objects(g).items()}, "info": info, "params": p,
            "geometry": ids, "textures": textures_for(p), "terrainBlend": blended, "ecosystems": eco}


def _regrow_ecosystems(zs):
    """(1.76.15, Luca: «se ho degli ecosistemi su un terreno e lo modifico ... si riposizionano?») The ecosystems on
    the zones of a terrain just made again: made again on the new shape, with their own settings and seed (the same
    composition) - before, their pieces stayed where they were (buried, in the air, past the new borders). In the
    same undo step as the terrain (decimate.ADDED / REMOVED: the new layers, the old ones in the trash).
    -> {"done": n, "failed": [{"name", "error"}]}"""
    from . import decimate, ecosystems, history
    zone_ids = {o.get(ID_KEY) for o in zs.values()}
    groups = []
    for o in bpy.context.scene.objects:
        if not o.get(ecosystems.ECO_KEY) or o.get("simpler_trashed"):
            continue
        try:
            st = json.loads(o.get(ecosystems.ECO_KEY) or "{}")
        except ValueError:
            continue
        host = o.parent.get(ID_KEY) if o.parent is not None else None
        if st.get("target") in zone_ids or host in zone_ids:
            groups.append((o.get(ID_KEY), st.get("name") or o.name))
    out = {"done": 0, "failed": [], "dropped": 0}
    # (1.76.18) the other distributions over the terrain (pennello, area, spaziatura): their pieces dropped on the
    # new surface (paint.drop_groups); the layers of an ecosystem are made again above instead
    from . import paint
    from mathutils import Vector as _V
    xs, ys = [], []
    for o in zs.values():
        if o.data is not None and len(o.data.polygons):
            for c in o.bound_box:
                w = o.matrix_world @ _V(c)
                xs.append(w.x); ys.append(w.y)
    dists = []
    if xs:
        x0, x1, y0, y1 = min(xs), max(xs), min(ys), max(ys)
        from . import scree
        for o in bpy.context.scene.objects:
            if not o.get(paint.PAINT_KEY) or o.get("simpler_trashed") or o.get(ecosystems.LAYER_KEY) or o.get(scree.LAYER_KEY):
                continue
            h = paint._holder(o)
            if h is None:
                continue
            hb = [h.matrix_world @ _V(c) for c in h.bound_box]
            if max(v.x for v in hb) < x0 or min(v.x for v in hb) > x1 or max(v.y for v in hb) < y0 or min(v.y for v in hb) > y1:
                continue
            dists.append(o)
    from . import scree
    g = next((o.parent for o in zs.values() if o.parent is not None), None)
    has_scree = g is not None and any(c.get(scree.KEY) and not c.get("simpler_trashed") for c in g.children)
    if not groups and not dists and not has_scree:
        return out
    progress.update(tr("Ecosistemi"), 0.95, "")
    before = history._scene_ids()
    if dists:
        try:
            out["dropped"] = paint.drop_groups(dists)
        except Exception as exc:  # noqa: BLE001
            print("SIMPLER_TERRAIN drop", exc, flush=True)
    for gid, name in groups:
        try:
            ecosystems.apply({"group": gid})
            out["done"] += 1
        except ApiError as exc:
            out["failed"].append({"name": name, "error": str(exc)})
        except Exception as exc:  # noqa: BLE001 - one ecosystem must not stop the terrain
            out["failed"].append({"name": name, "error": str(exc)})
            print("SIMPLER_TERRAIN ecosystem", name, exc, flush=True)
    if has_scree:
        # (1.76.22) the stones of the terrain laid again on its new shape
        done, failed = scree.regrow(g)
        out["done"] += done
        out["failed"].extend(failed)
    after = history._scene_ids()
    decimate.ADDED.extend(sorted(after - before))
    decimate.REMOVED.extend(sorted(before - after))
    return out


def textures_for(p):
    t = dict(TEXTURES["default"])
    t.update(TEXTURES.get(p.get("preset"), {}))
    return t


def _start_downloads(p, meshes=None):
    """Only the textures of the zones this terrain has (a plain without rock or snow downloads neither)."""
    from . import library
    tex = textures_for(p)
    mac = macro_for(p)
    need = [z for z in ZONES if meshes is None or (z in meshes and len(meshes[z].polygons))]
    for aid in {tex[z] for z in need if tex.get(z)} | {mac[z][0] for z in need if mac.get(z) and mac[z][0]}:
        try:
            library.download({"id": aid})
        except Exception as exc:
            print("SIMPLER_TERRAIN download", aid, exc, flush=True)


def state(data):
    """GET terrain/state?id=: parameters, zones (ids, faces) and the state of their textures."""
    from . import library, matedit
    g = _group(data.get("id"))
    zs = zone_objects(g)
    p = _current(g)
    tex = textures_for(p)
    out = {"id": g[ID_KEY], "params": p, "zones": {}, "presets": list(T.PRESETS.keys()), "blend": blend_settings(g),
           "blendReady": all(o.data is not None and o.data.uv_layers.get(BLEND_UV[0]) is not None
                             for o in zs.values() if o.data is not None and len(o.data.polygons))}
    for zone in zone_keys(p):
        ob = zs.get(zone)
        if ob is None:
            continue
        rz = root_zone(p, zone)
        mac = (macro_for(p).get(rz) or (None,))[0]
        slot_m = ob.material_slots[0].material if ob.material_slots else None
        mat = source_of(slot_m)
        st = library.status({"id": tex.get(rz, "")}) if tex.get(rz) else {"state": "none"}
        sp = _split(p, zone)
        out["zones"][zone] = {"id": ob[ID_KEY], "faces": len(ob.data.polygons) if ob.data is not None else 0,
                              "name": zone_label(p, zone),
                              "parent": sp["zone"] if sp else "", "split": sp or None,
                              "material": mat.name if mat else "", "placeholder": bool(mat and mat.get(PLACEHOLDER)),
                              "macroWaiting": macro_waiting(rz, p, mat), "macroTexture": mac or "",
                              "macroDownload": library.status({"id": mac}).get("state") if mac else "none",
                              "macroFraction": library.status({"id": mac}).get("fraction") if mac else None,
                              "blended": bool(slot_m is not None and slot_m.get(DERIVED)
                                              and ((matedit.params_of(slot_m) or {}).get("blend") or {}).get("partners")),
                              "slotMaterial": slot_m.name if slot_m else "",
                              "texture": tex.get(rz, ""), "download": st.get("state"), "fraction": st.get("fraction")}
    out["maxZones"] = MAX_ZONES
    out["rock"] = rock_settings(p)
    out["tone"] = tone_of(g)
    # (1.76.58) the maps of «Rilievo 3D»: their files, for the panel (name and picture)
    rm = {}
    for k in ("rmap", "rcolor"):
        im = bpy.data.images.get((out["tone"] or {}).get(k) or "")
        if im is not None:
            rm[k] = {"image": im.name, "file": bpy.path.abspath(im.filepath) if im.filepath else "", "missing": bool(im.filepath) and not os.path.isfile(bpy.path.abspath(im.filepath))}
    out["reliefMaps"] = rm
    out["toneReady"] = all(o.data is not None and o.data.uv_layers.get(TONE_UV[0]) is not None
                           for o in zs.values() if o.data is not None and len(o.data.polygons))
    out["rules"] = [{"id": k, "name": tr(SPLIT_NAMES[k])} for k in SPLIT_RULES]
    from . import scree
    out["scree"] = scree.of_terrain(g)          # (1.76.22) «Pietre e detriti» on this terrain
    return out


def _solid(prm):
    """No cut-out on a terrain: some Poly Haven ground textures come with an opacity map (leafy_grass: the leaves), and
    the ground became see-through (Luca, 1.76.0)."""
    op = prm.get("opacity")
    if isinstance(op, dict):
        op["useAlpha"] = False
        if isinstance(op.get("map"), dict):
            op["map"]["image"] = ""


def _see_through(mat):
    from . import matedit
    op = (matedit.params_of(mat) or {}).get("opacity") or {}
    return bool(op.get("useAlpha") or (op.get("map") or {}).get("image"))


def after_open():
    """Terrains made by 1.76.0 whose texture brought an opacity map: made solid when the project is opened."""
    from . import matedit
    for mat in bpy.data.materials:
        if mat.get("simpler_terrain_material") and _see_through(mat):
            prm = json.loads(json.dumps(matedit.params_of(mat)))
            _solid(prm)
            matedit.apply(mat, prm)
            print("SIMPLER_TERRAIN solid", mat.name, flush=True)


# ---------------------------------------------------------------- «Sfumatura dei bordi» (1.76.4)
# Every zone shows, near the border with another zone, that zone's material (matedit edge_blend, viewer useEdgeBlend).
# The material on a zone is kept as it is (the «source»: a texture of the terrain, a material of the library, one of
# the user's); the zone gets a copy of it with the blend («derived», DERIVED = the source's name). Editing the derived
# one in the panel edits the source (sync_blend copies it back); a material dropped on a zone becomes its source.
BLEND_DEF = {"width": 2.5, "irregular": 0.6}
DERIVED = "simpler_blend_of"


def _slot_mat(ob):
    return ob.material_slots[0].material if ob is not None and ob.material_slots else None


def source_of(mat):
    """The material a zone really has (the source of a derived one)."""
    if mat is not None and mat.get(DERIVED):
        return bpy.data.materials.get(mat[DERIVED]) or mat
    return mat


def _hash(d):
    import hashlib
    return hashlib.sha1(json.dumps(d, sort_keys=True, default=str).encode()).hexdigest()[:16]


def _base(prm):
    """The params of a material without the blend, with the per-object random shift off (it would shift the same
    texture differently on the two sides of a border)."""
    q = json.loads(json.dumps(prm))
    q.pop("blend", None)
    q.pop("tone", None)              # (1.76.14: the terrain's colours belong to the terrain, not to the material)
    q.pop("version", None)
    if isinstance(q.get("uv"), dict):
        q["uv"]["randomize"] = False
    return q


def blend_settings(g):
    for ob in zone_objects(g).values():
        m = _slot_mat(ob)
        if m is not None and m.get(DERIVED):
            from . import matedit
            b = (matedit.params_of(m) or {}).get("blend") or {}
            if b:
                return {"width": float(b.get("width", BLEND_DEF["width"])), "irregular": float(b.get("irregular", BLEND_DEF["irregular"]))}
    try:
        return dict(BLEND_DEF, **json.loads(g.get("simpler_terrain_blend") or "{}"))
    except ValueError:
        return dict(BLEND_DEF)


def snow_width(W):
    """(1.76.12) The blend between the snow and the zones next to it: wider than the others (Luca: the snow had
    sharp borders) - twice the width, at least 4 m, within what the distances stored in the mesh can hold."""
    return round(min(BLEND_REACH / 2.4, max(4.0, 2.0 * float(W))), 3)


def blendable(mat):
    """Whether a material can take part in the blend of the borders: a material of Simpler (its channels known),
    not water (waves, body of water: on the material and on the objects - a copy would lose them), not volumetric
    (a volume inside the faces), not glass (mixing a see-through surface into grass makes no sense). The others keep
    a sharp border, on both sides."""
    from . import matedit, volumetric
    if mat is None:
        return False
    p = matedit.params_of(mat)
    if p is None:
        return False
    try:
        from . import water
        if mat.get(water.MKEY) and water.mat_settings(mat).get("on"):
            return False
    except Exception:
        pass
    if volumetric.is_on(mat):
        return False
    if float(p["transmission"]["weight"]) > 0.3:
        return False
    return True


def sync_blend(g, settings=None, fresh=False):
    """Makes the derived materials of a terrain match their sources and the blend settings. Returns the ids of the
    zones whose material changed (for the view). fresh: new derived materials (a change of the settings: undo gives
    the old ones back - they are kept by name)."""
    from . import matedit
    zs = zone_objects(g)
    has_uv = all(ob.data is not None and ob.data.uv_layers.get(BLEND_UV[0]) is not None for ob in zs.values() if ob.data and len(ob.data.polygons))
    src = {}
    for zone, ob in zs.items():
        cur = _slot_mat(ob)
        if cur is None:
            continue
        if cur.get(DERIVED):
            s0 = bpy.data.materials.get(cur[DERIVED])
            base = _base(matedit.params_of(cur) or {})
            if s0 is None:                                   # (the source was deleted: the derived one becomes it)
                s0 = bpy.data.materials.new(cur.name.replace(" · " + tr("bordi"), ""))
                matedit.apply(s0, base, keep_original=False)
            elif _hash(base) != cur.get("simpler_blend_base"):
                # the zone's material was edited in the panel (the derived one): the edit goes to the source
                matedit.apply(s0, base, keep_original=False)
            src[zone] = s0
        else:
            src[zone] = cur
    st = dict(BLEND_DEF, **(settings or blend_settings(g)))
    if settings is not None:
        g["simpler_terrain_blend"] = json.dumps(st)
    W = float(st["width"])
    pcur = _current(g)
    tone = tone_of(g)
    # (1.76.54) the kind, size and orientation of «Rilievo 3D» are those of the rock's shape (the terrain's params:
    # an undo of the shape takes the shading back with it); «Nessuno» stays the tone's own
    if tone and tone.get("rtype") != "nessuno" and pcur.get("rockKind") is not None:
        kind, ksize, korient = rock_kind(pcur)
        tone = {k: v for k, v in tone.items() if k not in ("rtype", "rsize", "rorient")}
        tone.update(_relief3d({"rtype": kind, "rsize": ksize, "rorient": korient}))
    # (1.76.41) the relief of the rock also with the colours off (then only the relief is passed on)
    if tone and not tone["on"]:
        tone = dict(tone, **{k: 0.0 for k in ("streaks", "bands", "ridges", "wet")})
    tone = tone if (tone and (tone["on"] or tone["relief"] > 0) and any(o.data is not None and o.data.uv_layers.get(TONE_UV[0]) is not None
                                                for o in zs.values())) else None
    prms = {z: (matedit.params_of(m) if blendable(m) else None) for z, m in src.items()}
    faces = {z: (len(ob.data.polygons) if ob.data is not None else 0) for z, ob in zs.items()}
    if tone and tone.get("rdisp"):
        _real_weight(zs)
    changed = []
    inplace = []
    for zone, ob in zs.items():
        s0 = src.get(zone)
        if s0 is None or not ob.material_slots:
            continue
        partners = []
        if W > 0 and has_uv and prms.get(zone) is not None and faces.get(zone):
            # the zone in each slot of its distances (1.76.8: its own neighbours; meshes made before: the six zones)
            try:
                nbs = json.loads(ob.data.get("simpler_tb_nb") or "null")
            except ValueError:
                nbs = None
            if not isinstance(nbs, list):
                nbs = list(ZONES)
            order = zone_keys(pcur)
            for j, zb in enumerate(nbs[:6]):
                if zb == zone or prms.get(zb) is None or not faces.get(zb):
                    continue
                ia = order.index(zone) if zone in order else 99
                ib = order.index(zb) if zb in order else 99
                q = {"attr": BLEND_UV[j // 2], "comp": j % 2, "sign": 1 if ia < ib else -1,
                     "params": dict(_base(prms[zb]), **({"tone": (dict(tone, rcolor="") if tone.get("rcolor") and root_zone(pcur, zb) != "roccia" else tone)} if tone else {})), "zone": zb}
                if "neve" in (root_zone(pcur, zone), root_zone(pcur, zb)):
                    q["width"] = snow_width(W)          # (1.76.12) snow fades over a wider band, in patches
                partners.append(q)
        cur = _slot_mat(ob)
        tz = tone if (tone and prms.get(zone) is not None and faces.get(zone)) else None
        if not partners and tz is None:
            if cur is not s0:
                ob.material_slots[0].material = s0
                changed.append(ob[ID_KEY])
            continue
        desired = dict(_base(prms[zone]), blend={"width": W, "irregular": float(st["irregular"]), "partners": partners})
        # (1.76.56) a texture of tens of metres on this side or the other: its brightness leads the border less
        # (matedit.blend_lum_weight) - the marker makes those materials again once, the others stay as they are
        if partners and min([matedit.blend_lum_weight(prms[zone])] + [matedit.blend_lum_weight(q["params"]) for q in partners]) < 1.0:
            desired["blend"]["lumW"] = 1
        if tz is not None:
            # (1.76.14 «Colori dal terreno»: on every material of the terrain, its own too; 1.76.40: with the thickness
            # of the layers, for the relief of the rock in the shading)
            # (1.76.43: v = the version of the shading of the walls - the materials made again once when it changes)
            desired["tone"] = dict(tz, thick=round(float(rock_settings(pcur)["thick"]), 2), v=TONE_SHADER)
            if tz.get("rcolor") and root_zone(pcur, zone) != "roccia":
                desired["tone"]["rcolor"] = ""      # (1.76.58: the colour map on the rock only - see the partners)
        # (the key without the zone names: a material made before 1.76.8 is not made again for them)
        key = _hash(dict(desired, blend=dict(desired["blend"], partners=[{k: v for k, v in q.items() if k != "zone"}
                                                                          for q in partners])))
        if cur is not None and cur.get(DERIVED) == s0.name and cur.get("simpler_blend_key") == key:
            continue
        # (1.76.47) why a material is made again (a few seconds each: Luca, «tutto super lento»): in the log
        why = {"own": _hash(_base(prms[zone])), "tone": _hash(desired.get("tone") or {}), "W": W,
               "partners": [[q["zone"], q["attr"], q["comp"], q["sign"], _hash(q["params"])] for q in partners]}
        try:
            was = json.loads(cur.get("simpler_blend_why") or "{}") if cur is not None else {}
        except ValueError:
            was = {}
        diff = [k_ for k_ in why if was.get(k_) != why[k_]] if was else ["new"]
        # (1.76.50) only the numbers of the border blend changed (width, irregularity): set in place, not made again
        # (1.76.53) nor those of «Rilievo 3D» (depth, size, detail, where, orientation, the thickness of the layers)
        def tn(t_, view=False):
            if not isinstance(t_, dict):
                return t_
            o_ = dict(t_, **{k: None for k in matedit.RELIEF_NUMS}, reliefOn=float(t_.get("relief", 0) or 0) > 0)
            if not view:
                return o_
            # (the view: the relief is not in it - only the colour map of «Rilievo 3D», with its numbers, 1.76.58)
            o_ = dict(o_, rtype=None, reliefOn=None, rdisp=None, rmap=None, rmanti=None)
            if t_.get("rcolor"):
                o_.update({k: t_.get(k) for k in matedit.RELIEF_VIEW}, reliefOn=float(t_.get("relief", 0) or 0) > 0,
                          nessuno=t_.get("rtype") == "nessuno")
            return o_

        def parts_(view, drop):
            return [dict({k: v for k, v in q.items() if k not in drop},
                         params=dict(q["params"], tone=tn(q["params"].get("tone"), view)) if "tone" in q["params"] else q["params"])
                    for q in partners]
        sk = dict(desired, blend=dict(desired["blend"], width=None, irregular=None, partners=parts_(False, ("zone", "width"))))
        vk = dict(desired, blend=dict(desired["blend"], partners=parts_(True, ("zone",))))
        if isinstance(desired.get("tone"), dict):
            sk["tone"] = tn(desired["tone"])
            vk["tone"] = tn(desired["tone"], True)
        skey, vkey = _hash(sk), _hash(vk)
        # (a copy when the old one must stay for Ctrl+Z - «fresh»: Blender copies a whole tree at once, cheaply)
        if cur is not None and cur.get(DERIVED) == s0.name and cur.get("simpler_blend_skey") == skey:
            tgt = cur.copy() if fresh else cur
            relief = isinstance(desired.get("tone"), dict) and float(desired["tone"].get("relief", 0) or 0) > 0
            ok = matedit.update_blend_values(tgt, desired) if (partners and W > 0) else True
            if ok and relief:
                ok = matedit.update_relief_values(tgt, desired)
            if ok:
                matedit.store_params(tgt, desired)
                tgt["simpler_blend_key"] = key
                tgt["simpler_blend_why"] = json.dumps(why)
                only_relief = cur.get("simpler_blend_vkey") == vkey
                tgt["simpler_blend_vkey"] = vkey
                if tgt is not cur:
                    ob.material_slots[0].link = "OBJECT"
                    ob.material_slots[0].material = tgt
                print(f"SIMPLER_TERRAIN material {zone}: only its {'relief' if only_relief else 'border'} numbers changed, set {'on a copy' if fresh else 'in place'}", flush=True)
                if not only_relief or tgt is not cur:
                    changed.append(ob[ID_KEY])        # (the relief is not in the view: nothing to send it, unless a copy)
                inplace.append(ob)
                continue
            if tgt is not cur:
                bpy.data.materials.remove(tgt)
        print(f"SIMPLER_TERRAIN material {zone} made again: {', '.join(diff)}"
              + (f" (partners {[w_[0] for w_ in was.get('partners', [])]} -> {[w_[0] for w_ in why['partners']]})" if "partners" in diff else ""), flush=True)
        if fresh or cur is None or not cur.get(DERIVED):
            d = bpy.data.materials.new(tr("Terreno") + " · " + zone_label(pcur, zone) + " · " + tr("bordi"))
        else:
            d = cur
        # (1.76.53) only the kind of «Rilievo 3D» changed: the same material made again, nothing new for the view
        same_view = d is cur and cur is not None and cur.get("simpler_blend_vkey") == vkey
        # (1.76.56, Luca: «ogni azione … un'attesa infinita») params now, the tree when Cycles needs it
        matedit.apply_deferred(d, desired)
        d[DERIVED] = s0.name
        d["simpler_blend_key"] = key
        d["simpler_blend_why"] = json.dumps(why)
        d["simpler_blend_skey"] = skey
        d["simpler_blend_vkey"] = vkey
        d["simpler_blend_base"] = _hash(_base(matedit.params_of(d) or {}))
        if s0.get("simpler_terrain_material"):
            d["simpler_terrain_material"] = s0["simpler_terrain_material"]
        ob.material_slots[0].link = "OBJECT"
        ob.material_slots[0].material = d
        if not same_view:
            changed.append(ob[ID_KEY])
    if changed or inplace or (tone and tone.get("rdisp")):
        # (the subdivision for real displacement follows the zone's material and the ones it blends into; 1.76.55:
        # also a zone set in place - Finezza of «Rilievo 3D» is its subdivision; same_view zones of a new kind)
        matedit._sync_displacement([o for o in zs.values() if o[ID_KEY] in changed or o in inplace or (tone and tone.get("rdisp"))])
    return changed


REAL_BORDER = 6.0       # (1.76.55) metres from the border with another zone where the true relief is all there
RW_V = 1                # (the version of simpler_rw: made again once when it changes)
REAL_WALLS = 0.15       # (the part of a zone's points on walls steeper than 37° for its true relief)


def _real_weight(zs):
    """(1.76.55) «Rilievo 3D» Displacement vero: per point of every zone, the part of the relief made real
    (matedit RELIEF_RW, a float of the points): 0 on the points two zones share - exactly, each zone is a mesh of its
    own and moved there they would part - up to 1 REAL_BORDER metres in (the distance to the next zone: the blend
    maps the mesh has). Once per mesh (a new mesh after a sculpting: again); a few tenths of a second."""
    from . import matedit
    obs = [o for o in zs.values() if o.data is not None and len(o.data.vertices)]
    if not obs or all(o.data.get(matedit.RELIEF_RW + "_v") == RW_V and o.data.attributes.get(matedit.RELIEF_RW) is not None
                      for o in obs):
        return
    t0 = time.time()
    cos = []
    for o in obs:
        co = np.empty(len(o.data.vertices) * 3, np.float64)
        o.data.vertices.foreach_get("co", co)
        co = co.reshape(-1, 3)
        M = np.array(o.matrix_world, np.float64)
        cos.append(co @ M[:3, :3].T + M[:3, 3])
    # the points of more than one zone: the same place (to the millimetre) in two meshes
    keys = [np.round(c * 1000.0).astype(np.int64) for c in cos]
    allk = np.concatenate(keys)
    owner = np.concatenate([np.full(len(k_), i, np.int32) for i, k_ in enumerate(keys)])
    _u, inv = np.unique(allk, axis=0, return_inverse=True)
    inv = inv.ravel()
    shared = np.zeros(len(_u), bool)
    order = np.argsort(inv, kind="stable")
    si, so = inv[order], owner[order]
    same = si[1:] == si[:-1]
    shared[si[1:][same & (so[1:] != so[:-1])]] = True
    off = 0
    for o, c in zip(obs, cos):
        me = o.data
        n = len(c)
        border = shared[inv[off:off + n]]
        off += n
        # the distance to the next zone from the blend maps (per corner: + 1, 0 = no data)
        d = np.full(n, BLEND_FAR, np.float32)
        nl = len(me.loops)
        if nl:
            lv = np.empty(nl, np.int32)
            me.loops.foreach_get("vertex_index", lv)
            for nm in BLEND_UV:
                lay = me.uv_layers.get(nm)
                if lay is None:
                    continue
                uv = np.empty(nl * 2, np.float32)
                lay.data.foreach_get("uv", uv)
                uv = uv.reshape(-1, 2)
                for c_ in range(2):
                    v = np.where(uv[:, c_] > 0.5, uv[:, c_] - 1.0, BLEND_FAR).astype(np.float32)
                    np.minimum.at(d, lv, v)
        w = _smoothstep(0.0, REAL_BORDER, d).astype(np.float32)
        w[border] = 0.0
        a = me.attributes.get(matedit.RELIEF_RW)
        if a is not None and (a.domain != "POINT" or a.data_type != "FLOAT"):
            me.attributes.remove(a)
            a = None
        if a is None:
            a = me.attributes.new(matedit.RELIEF_RW, "FLOAT", "POINT")
        a.data.foreach_set("value", w)
        # (only a zone with walls gets the subdivision: on a meadow or the spianata it would cost memory and time -
        # each of its faces cut in micro-triangles - for a relief that only the walls have, tone_relief «Dove»)
        nz = np.empty(n * 3, np.float32)
        me.vertices.foreach_get("normal", nz)
        walls = float(((w > 0.05) & (nz.reshape(-1, 3)[:, 2] < 0.8)).mean())
        me[matedit.RELIEF_RW + "_v"] = RW_V
        me[matedit.RELIEF_RW + "_any"] = 1 if walls > REAL_WALLS else 0
        print(f"SIMPLER_TERRAIN true relief {o.name}: walls {walls:.1%}", flush=True)
    print(f"SIMPLER_TERRAIN true relief weights {time.time() - t0:.2f} s", flush=True)


def sync_all():
    """After a command that may have changed a material on a zone (dropped, edited): every terrain made to match.
    Nothing to do (no terrain, nothing changed) costs a few hashes. -> ids of the zones whose material changed."""
    out = []
    for o in bpy.context.scene.objects:
        if o.get(KEY) and o.get(KIND_KEY) == "group" and not o.get("simpler_trashed"):
            try:
                out += sync_blend(o)
            except Exception as exc:
                print("SIMPLER_TERRAIN blend", exc, flush=True)
    return out


def set_blend(data):
    """POST terrain/blend {id, width, irregular}: the blend of the borders (materials only: the geometry stays).
    Undo: «deep» on the zones (their materials by name)."""
    g = _group(data.get("id"))
    st = blend_settings(g)
    for k in ("width", "irregular"):
        if k in data:
            st[k] = max(0.0, min(5.0 if k == "width" else 1.0, float(data[k])))      # (5 m: the reach stored, 12 m, is 2.3 ×)
    ids = sync_blend(g, st, fresh=True)
    return {"id": g[ID_KEY], "blend": st, "geometry": [], "terrainBlend": ids}


def _maps_of(aid):
    """The maps of a downloaded texture of the library (channel -> image name, loaded), or None."""
    from . import library, paths
    mfile = os.path.join(library.root(), os.path.basename(aid or ""), "maps.json")
    if not aid or not os.path.isfile(mfile):
        return None
    try:
        with open(mfile, encoding="utf-8") as f:
            maps = json.load(f)
    except (OSError, ValueError):
        return None
    out = {}
    for ch in ("color", "normal"):
        path = paths.resolve(maps.get(ch)) if isinstance(maps.get(ch), str) else None
        if not path or not os.path.isfile(path):
            continue
        im = bpy.data.images.load(path, check_existing=True)
        im.name = f"{aid}_{ch}"
        out[ch] = im.name
    return out if out.get("color") else None


def _macro_size_m(aid):
    from . import library
    info = next((a for a in (library._list.get("assets") or []) if a.get("id") == aid), {})
    mm = float(info.get("sizeMm") or 0)
    return mm / 1000.0 if mm > 0 else float(MACRO_SIZE_M.get(aid, 30))


def _macro_params(zone, p, prm):
    """The «macro» of a terrain material for its zone: None while its texture is not downloaded."""
    from . import matedit
    aid, st, col, tone = macro_for(p).get(zone, (None, 0.0, 0.0, 0.0))
    mc = {"map": {"image": ""}, "normal": {"image": ""}, "sizeCm": 2000.0, "strength": 0.0, "colour": 0.0,
          "tone": tone, "toneSizeM": 30.0, "aid": aid or ""}
    if aid:
        maps = _maps_of(aid)
        if maps is None:
            return None
        mc.update(map={"image": maps["color"]}, normal={"image": maps.get("normal", "")}, sizeCm=_macro_size_m(aid) * 100.0,
                  strength=st, colour=col, mean=matedit.image_mean(maps["color"]),
                  detailMean=matedit.image_mean(((prm.get("color") or {}).get("map") or {}).get("image")) or matedit.image_mean(maps["color"]))
    return mc


def _add_macro(mat, zone, p):
    """Our terrain material without its large texture yet (just downloaded): added. True when it changed."""
    from . import matedit
    prm = matedit.params_of(mat)
    if prm is None or not mat.get("simpler_terrain_material"):
        return False
    have = prm.get("macro") or {}
    want_aid = (macro_for(p).get(zone) or (None,))[0] or ""
    if have and have.get("aid", "") == want_aid and (not want_aid or (have.get("map") or {}).get("image")):
        return False
    mc = _macro_params(zone, p, prm)
    if mc is None:
        return False
    prm = json.loads(json.dumps(prm))
    prm["macro"] = mc
    matedit.apply(mat, prm)
    return True


def macro_waiting(zone, p, mat):
    """Our terrain material whose large texture is still downloading (the panel keeps asking)."""
    from . import library, matedit
    if mat is None or not mat.get("simpler_terrain_material"):
        return False
    aid = (macro_for(p).get(zone) or (None,))[0]
    if not aid:
        return False
    have = (matedit.params_of(mat) or {}).get("macro") or {}
    if have.get("aid") == aid and (have.get("map") or {}).get("image"):
        return False
    return library.status({"id": aid}).get("state") in ("running", "done")


def apply_textures(data):
    """POST terrain/materials {id}: the Poly Haven textures (downloaded) on the zones that still have their plain
    colour - as a material of the terrain of their own (box projection, «Rompi la ripetizione» on: a large surface)."""
    from . import library, matedit
    g = _group(data.get("id"))
    zs = zone_objects(g)
    p = _current(g)
    tex = textures_for(p)
    done = []
    for zone, ob in zs.items():
        if ob.data is None or not len(ob.data.polygons):
            continue
        rz = root_zone(p, zone)
        mat = source_of(ob.material_slots[0].material if ob.material_slots else None)
        aid = tex.get(rz)
        if mat is not None and mat.get("simpler_terrain_material") and _see_through(mat):
            prm = json.loads(json.dumps(matedit.params_of(mat)))       # (made by 1.76.0: the cut-out off)
            _solid(prm)
            matedit.apply(mat, prm)
            done.append(zone)
        if mat is not None and not mat.get(PLACEHOLDER):
            if _add_macro(mat, rz, p):                   # (its large texture arrived after the detail one)
                done.append(zone)
            continue
        if not aid:
            continue
        if library.status({"id": aid}).get("state") != "done":
            continue
        name = tr("Terreno") + " · " + zone_label(p, zone) + " · " + aid
        tm = bpy.data.materials.get(name)
        if tm is None:
            library.apply({"id": aid, "ids": [ob[ID_KEY]]})            # (the material of the texture, then our copy)
            src = ob.material_slots[0].material
            tm = src.copy()
            tm.name = name
            prm = matedit.params_of(tm) or matedit.read_material(tm)[0]
            prm = json.loads(json.dumps(prm))
            prm["uv"]["mode"] = "box"
            prm["uv"]["antitile"] = True
            prm["uv"]["cellRepeats"] = 4.0
            _solid(prm)
            sp_ = _split(p, zone)
            if sp_ is not None:                          # (a part of «Dividi zona»: its zone's texture, a bit different)
                b_, s_ = SPLIT_TWEAK.get(sp_.get("rule"), (1.0, 1.0))
                prm["color"]["brightness"] = float(prm["color"].get("brightness", 1.0)) * b_
                prm["color"]["saturation"] = float(prm["color"].get("saturation", 1.0)) * s_
            mc = _macro_params(rz, p, prm)
            if mc is not None:
                prm["macro"] = mc
            matedit.apply(tm, prm)
            tm["simpler_terrain_material"] = rz
        if ob.material_slots:
            ob.material_slots[0].link = "OBJECT"
            ob.material_slots[0].material = tm
        done.append(zone)
    blended = sync_blend(g)
    return {"applied": done, "materials": [ob.material_slots[0].material.name for z, ob in zs.items() if ob.material_slots and ob.material_slots[0].material],
            "terrainBlend": blended}


def list_terrains(_data=None):
    """GET terrain/list: the terrains of the scene (the panel shows the first, or the one selected)."""
    out = []
    for o in bpy.context.scene.objects:
        if o.get(KEY) and o.type == "EMPTY" and not o.get("simpler_trashed"):
            out.append({"id": o[ID_KEY], "name": o.name, "zones": {z: ob[ID_KEY] for z, ob in zone_objects(o).items()}})
    return {"terrains": out}
