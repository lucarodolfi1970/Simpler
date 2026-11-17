"""(1.76.22) «Pietre e detriti» of a terrain: the stone models the user picks, laid where a mountain sheds them.

Luca (with photos of talus slopes and boulder fields): not a fixed ecosystem, but «indicando i modelli di pietra li
posizioni direttamente secondo pendii canaloni». The terrain says where its walls, gullies and fans are; this puts
the stones there:
- talus cones at the foot of the walls: the debris runs down the fall line from every wall, as far as the wall is
  high; small stones near the wall, the big ones rolled farther (sorted by size); in cones, not an even apron;
- gullies: stones along the floor of the gullies on the slopes, and spread where they open out (fans).
Every stone at random orientation, partly buried, dropped on the real surface of the terrain (with its relief).

The colour: the stones take the tone of the rock of the terrain («Accordo al terreno», on a copy of their materials -
the library model does not change), then the user's base colour, saturation, brightness and contrast on top.

Scene: a group «Pietre e detriti» (KEY: its settings) child of the terrain's group, with one distribution (paint) in
it (LAYER_KEY). Made again with the terrain (terrain._regrow_ecosystems), in the same undo step.
"""
import json
import math

import bpy
import numpy as np

from . import terrain_gen as T
from .core import ApiError, ID_KEY, KIND_KEY, find, link, log, new_id, refresh
from .i18n import tr

KEY = "simpler_scree"                   # on the group: JSON (terrain, models, settings)
LAYER_KEY = "simpler_scree_layer"       # on its distribution: the id of the group
SRC_KEY = "simpler_scree_src"           # on a material copied for the stones: the material it comes from
MAX_PIECES = 300_000
GRID_MAX = 640                           # cells a side of the grid the places are worked out on
DEFAULTS = {
    "models": [], "amount": 0.5, "seed": 1, "size": 1.0,     # (1.76.31, Luca: «grandezza» of all the stones at once)
    # Avanzate
    "talus": 1.0, "gully": 0.6, "sizeMin": 0.5, "sizeMax": 2.0, "sort": 0.7, "bury": 0.35, "reach": 1.0,
    # colour
    "match": 1.0, "color": [0.5, 0.45, 0.4], "colorAmount": 0.0, "saturation": 1.0, "brightness": 1.0, "contrast": 0.0,
    # (1.76.24) per stone: its size and how many of it (as the brush), and the whole terrain or only what the camera sees
    "modelScale": {}, "modelWeight": {}, "whole": False,
}


def _clean(d, prev=None):
    s = dict(DEFAULTS)
    s.update({k: v for k, v in (prev or {}).items() if k in DEFAULTS})
    s.update({k: v for k, v in (d or {}).items() if k in DEFAULTS})

    def f(k, lo, hi):
        try:
            s[k] = max(lo, min(hi, float(s[k])))
        except (TypeError, ValueError):
            s[k] = DEFAULTS[k]
    f("amount", 0.0, 2.0); f("talus", 0.0, 2.0); f("gully", 0.0, 2.0); f("sizeMin", 0.05, 20.0); f("sizeMax", 0.05, 20.0)
    f("size", 0.05, 20.0)
    f("sort", 0.0, 1.0); f("bury", 0.0, 0.9); f("reach", 0.2, 3.0); f("match", 0.0, 1.0); f("colorAmount", 0.0, 1.0)
    f("saturation", 0.0, 2.0); f("brightness", 0.2, 3.0); f("contrast", -1.0, 1.0)
    if s["sizeMax"] < s["sizeMin"]:
        s["sizeMin"], s["sizeMax"] = s["sizeMax"], s["sizeMin"]
    s["seed"] = int(s.get("seed") or 1)
    c = s.get("color")
    s["color"] = [max(0.0, min(1.0, float(x))) for x in c][:3] if isinstance(c, list) and len(c) >= 3 else list(DEFAULTS["color"])
    s["models"] = [str(m) for m in (s.get("models") or []) if m]
    for k, lo, hi in (("modelScale", 0.05, 20.0), ("modelWeight", 0.0, 10.0)):
        v = s.get(k) if isinstance(s.get(k), dict) else {}
        s[k] = {str(m): max(lo, min(hi, float(x))) for m, x in v.items() if m in s["models"] and isinstance(x, (int, float))}
    s["whole"] = bool(s.get("whole"))
    return s


def _smoothstep(a, b, x):
    t = np.clip((x - a) / (b - a), 0.0, 1.0)
    return t * t * (3.0 - 2.0 * t)


def _bilinear(a, fi, fj):
    """a sampled at fractional (row fi, column fj), clamped to the grid."""
    n0, n1 = a.shape
    fi = np.clip(fi, 0.0, n0 - 1.001)
    fj = np.clip(fj, 0.0, n1 - 1.001)
    i0, j0 = fi.astype(np.int64), fj.astype(np.int64)
    ti, tj = fi - i0, fj - j0
    return ((a[i0, j0] * (1 - tj) + a[i0, j0 + 1] * tj) * (1 - ti)
            + (a[i0 + 1, j0] * (1 - tj) + a[i0 + 1, j0 + 1] * tj) * ti)


# ---------------------------------------------------------------- where the stones lie

def _talus_spread(D, top, src, h, is_wall, up_i, up_j, cell, steps):
    """From every wall down the fall line, one cell a step: the distance from the wall (D), the top of the wall above
    (top), the debris it sheds (src). Each cell reads its uphill point (bilinear in the four cells around it).
    (1.76.52, audit: 3.6 s of the 10 s of «Pietre e detriti» after a sculpting, Luca) the same steps as before, but
    each step looks only at the cells whose uphill cells changed in the step before (the front going down the
    slopes), and the four cells and weights of every uphill point are found once - the same numbers as before."""
    n0, n1 = D.shape
    fi = np.clip(up_i, 0.0, n0 - 1.001)
    fj = np.clip(up_j, 0.0, n1 - 1.001)
    i0, j0 = fi.astype(np.int64), fj.astype(np.int64)
    ti, tj = (fi - i0).ravel(), (fj - j0).ravel()
    k00 = (i0 * n1 + j0).ravel()
    k01, k10, k11 = k00 + 1, k00 + n1, k00 + n1 + 1
    w00, w01, w10, w11 = (1 - tj) * (1 - ti), tj * (1 - ti), (1 - tj) * ti, tj * ti
    D, top, src, hf = D.ravel().copy(), top.ravel().copy(), src.ravel().copy(), h.ravel()
    wall = is_wall.ravel()
    walls = np.nonzero(wall)[0]

    def at(a, c):
        """a at the uphill points of the cells c (as _bilinear)."""
        return ((a[k00[c]] * (1 - tj[c]) + a[k01[c]] * tj[c]) * (1 - ti[c])
                + (a[k10[c]] * (1 - tj[c]) + a[k11[c]] * tj[c]) * ti[c])

    cand = np.nonzero(~wall)[0]                     # (the first step: every cell)
    for _ in range(steps):
        Du = at(D, cand) + cell
        Tu = at(top, cand)
        Su = at(src, cand)
        better = (Du < D[cand]) & (Tu > -1e8)
        if not better.any():
            break
        c = cand[better]
        D[c] = Du[better]
        top[c] = Tu[better]
        src[c] = np.maximum(src[c], Su[better])
        # (on the wall itself the top keeps rising: the foot knows the whole height above it)
        tw = at(top, walls)
        nt = np.maximum(top[walls], np.where(tw > hf[walls], tw, hf[walls]))
        cw = walls[nt != top[walls]]
        top[walls] = nt
        # the cells that read a cell changed now: the next step looks at them only
        ch = np.zeros(D.size, bool)
        ch[c] = True
        ch[cw] = True
        nxt = ch[k00] | ch[k01] | ch[k10] | ch[k11]
        nxt &= ~wall
        cand = np.nonzero(nxt)[0]
        if not len(cand):
            break
    return D.reshape(n0, n1), top.reshape(n0, n1), src.reshape(n0, n1)


def density(p, f, xs, h, s):
    """Per cell of the grid (rows y, columns x): (density of stones 0..1, size 0..1 - 0 small near the wall, 1 the
    biggest, -1 random). Pure numpy on the terrain's height (with its relief)."""
    size_m = float(f["size"])
    cell = float(xs[1] - xs[0])
    relief = max(1.0, float(np.ptp(h)))
    hs = T.smooth(h, 1)
    gy, gx = np.gradient(hs, cell)
    grad = np.hypot(gx, gy)
    slope = np.degrees(np.arctan(grad))
    rs = float(p.get("rockSlope") or 40.0)
    # the walls as a whole (the height blurred over ~25 m): a wall cut into ledges and steps is one wall, the debris
    # gathers at its foot - with the slope of every step, every ledge had its own thin strip of stones
    big = h
    for _ in range(max(2, int(round(12.0 / cell)))):
        big = T.smooth(big, 1)
    by, bx = np.gradient(big, cell)
    bslope = np.degrees(np.arctan(np.hypot(bx, by)))
    wall = np.maximum(_smoothstep(rs - 6.0, rs + 6.0, bslope), _smoothstep(rs + 6.0, rs + 18.0, slope))
    # the gullies: hollows (the height under its blur over ~20 m) where water runs
    blur = h
    for _ in range(max(2, int(round(10.0 / cell)))):
        blur = T.smooth(blur, 1)
    hollow = np.clip(-(h - blur) / (0.004 * relief + 0.4), 0.0, 1.0)
    n = int(f["h"].shape[0])
    from . import terrain as TR
    flow = np.asarray(f["flow"], np.float32) if f.get("flow") is not None and np.ptp(f["flow"]) > 0 else np.zeros((n, n), np.float32)
    flow = flow / max(1e-9, float(np.percentile(flow, 99)))
    flow = np.clip(TR._sample(T.smooth(flow, 1), size_m, xs, xs, cubic=False), 0.0, 1.0)
    # ---- talus: from every wall down the fall line; how far: as the wall is high (the drop from its top)
    bg = np.hypot(bx, by)
    ux, uy = np.where(bg > 1e-6, bx / np.maximum(bg, 1e-6), 0.0), np.where(bg > 1e-6, by / np.maximum(bg, 1e-6), 0.0)
    rows, cols = np.mgrid[0:h.shape[0], 0:h.shape[1]].astype(np.float64)
    up_i, up_j = rows + uy, cols + ux                              # one cell uphill (the gradient points up)
    is_wall = wall > 0.5
    D = np.where(is_wall, 0.0, 1e9)
    top = np.where(is_wall, h, -1e9)
    # (the source: more debris below the gullies of the wall - they gather what falls)
    src = np.where(is_wall, 0.5 + 0.5 * hollow, 0.0)
    reach = float(s["reach"])
    steps = int(min(400.0, 220.0 * reach / cell)) + 2
    D, top, src = _talus_spread(D, top, src, h, is_wall, up_i, up_j, cell, steps)
    drop = np.maximum(0.0, top - h)
    L = np.clip(0.8 * drop * reach, 6.0, 260.0)                   # the cone reaches about as far as the wall is high
    t = np.clip(D / L, 0.0, 1.0)
    on = (D < 1e8) & (D > 0)
    talus = np.where(on, (1.0 - t) ** 0.7, 0.0) * np.clip(src, 0.0, 1.0)
    talus *= 1.0 - wall                                            # (nothing stays on the wall)
    # in cones and tongues, not an even apron: patches of a few tens of metres along the foot
    perm = T._perm(np.random.default_rng(int(s["seed"]) + 4242))
    X, Y = np.meshgrid(xs, xs)
    lam = max(15.0, 0.06 * relief)
    nb = T.fbm(X / lam + 3.1, Y / lam - 7.7, perm, 4, gain=0.55)
    talus *= _smoothstep(0.25, 0.75, 0.5 + nb + 0.35 * (1.0 - t))
    # ---- gullies: on the floor of the hollows of the slopes, and where they open out (fans)
    gully = hollow * _smoothstep(0.04, 0.3, flow) * _smoothstep(12.0, 24.0, slope) * (1.0 - wall)
    fan = _smoothstep(0.08, 0.35, flow) * (1.0 - _smoothstep(6.0, 16.0, slope)) * _smoothstep(0.0, 0.5, hollow + 0.3)
    # (only fans below the slopes, not every river bed: near the steep ground)
    near = T.smooth(_smoothstep(18.0, 30.0, slope), 4)
    for _ in range(int(round(30.0 / cell))):
        near = T.smooth(near, 1)
    fan *= np.clip(near * 3.0, 0.0, 1.0)
    gully = np.maximum(gully, 0.5 * fan)
    nb2 = T.fbm(X / (0.6 * lam) - 11.0, Y / (0.6 * lam) + 5.0, perm, 3, gain=0.5)
    gully *= _smoothstep(0.2, 0.7, 0.5 + nb2)
    dens = np.clip(float(s["talus"]) * talus + float(s["gully"]) * gully, 0.0, 1.5)
    size = np.where(talus * float(s["talus"]) >= gully * float(s["gully"]), t, -1.0)
    # (not where the terrain is lowered to its edge, nor on the «spianata»: kept by the mesh's own shape)
    return dens.astype(np.float32), size.astype(np.float32)


def _tris(zones):
    """The triangles of the zones in the world, together: (points, triangles) or None."""
    from . import ecosystems
    cos, tvs, off = [], [], 0
    for ob in zones:
        if ob.data is None or not len(ob.data.polygons):
            continue
        co, tv, _grow, _n = ecosystems._all_triangles(ob)
        cos.append(co); tvs.append(tv + off); off += len(co)
    return (np.concatenate(cos), np.concatenate(tvs)) if cos else None


def _ground(zones, tris=None):
    from . import ecosystems
    t = tris if tris is not None else _tris(zones)
    return ecosystems._Ground(t[0], t[1]) if t is not None else None


def _rand_quat(rng, n):
    """Uniform random rotations (Shoemake): (w, x, y, z)."""
    u1, u2, u3 = rng.random(n), rng.random(n), rng.random(n)
    a, b = np.sqrt(1 - u1), np.sqrt(u1)
    return np.stack([b * np.cos(2 * np.pi * u3), a * np.sin(2 * np.pi * u2), a * np.cos(2 * np.pi * u2), b * np.sin(2 * np.pi * u3)], 1)


# ---------------------------------------------------------------- the colour

def _lum(c):
    return 0.2126 * c[0] + 0.7152 * c[1] + 0.0722 * c[2]


def _mean_color(mat):
    """The average colour of a material as the eye sees it (linear), from its parameters."""
    from . import matedit
    if mat is None:
        return None
    p, _adv = matedit.read_material(mat)
    c = p["color"]
    tint = np.array([float(x) for x in c["tint"]][:3])
    img = (c.get("map") or {}).get("image")
    m = matedit.image_mean(img) if img else None
    col = tint * (np.array(m[:3]) if m else 1.0)
    # (brightness and saturation of the material: as the HSV node)
    import colorsys
    hh, ss, vv = colorsys.rgb_to_hsv(*[max(0.0, float(x)) for x in col])
    col = np.array(colorsys.hsv_to_rgb(hh, min(1.0, ss * float(c.get("saturation", 1.0))), vv * float(c.get("brightness", 1.0))))
    return col


def _rock_color(g):
    """The colour of the rock of the terrain (its «roccia» zone, else the gravel), linear."""
    from . import terrain as TR
    zs = TR.zone_objects(g)
    for z in ("roccia", "terra"):
        ob = zs.get(z)
        if ob is not None and ob.material_slots and ob.material_slots[0].material is not None:
            c = _mean_color(TR.source_of(ob.material_slots[0].material))
            if c is not None and c.max() > 1e-4:
                return c
    return None


def _recolour(coll, gid, s, target):
    """The materials of the stones of this group: copies (the library model keeps its own), their colour moved
    towards the rock's (match), then the user's colour, saturation, brightness and contrast. -> (materials changed,
    materials left as they are: made in a way Simpler cannot rebuild)"""
    from . import matedit
    copies, done, kept = {}, 0, 0
    for o in list(coll.all_objects):
        if o is None or o.type != "MESH" or o.data is None:      # (1.76.24: an empty slot of the collection - Luca)
            continue
        for slot in o.material_slots:
            m = slot.material
            if m is None:
                continue
            src = bpy.data.materials.get(m.get(SRC_KEY) or "") or m       # (from the original, never a copy again)
            if src.name in copies:
                slot.link = "OBJECT" if slot.link == "OBJECT" else slot.link
                slot.material = copies[src.name]
                continue
            p, advanced = matedit.read_material(src)
            if advanced:
                copies[src.name] = src                  # (a material Simpler cannot rebuild: left as it is)
                kept += 1
                continue
            stone = _mean_color(src)
            if stone is None:
                copies[src.name] = src
                continue
            stone = np.maximum(stone, 1e-4)
            want = stone.copy()
            if target is not None and s["match"] > 0:
                want = stone ** (1.0 - s["match"]) * np.maximum(target, 1e-4) ** s["match"]
            if s["colorAmount"] > 0:
                uc = np.array(s["color"], dtype=float)
                uc = uc * (_lum(want) / max(1e-4, _lum(uc)))           # (the user's hue, the brightness it has)
                want = want * (1.0 - s["colorAmount"]) + uc * s["colorAmount"]
            r = want / stone
            c = p["color"]
            tint = np.array([float(x) for x in c["tint"]][:3]) * r
            k = float(tint.max())
            extra = 1.0
            if k > 1.0:
                tint /= k
                extra = k
            cp = src.copy()
            cp.name = src.name + " · " + tr("pietre")
            cp[SRC_KEY] = src.name
            cp["simpler_scree_group"] = gid
            c["tint"] = [float(x) for x in tint]
            c["brightness"] = float(c.get("brightness", 1.0)) * extra * s["brightness"]
            c["saturation"] = float(c.get("saturation", 1.0)) * s["saturation"]
            c["contrast"] = float(c.get("contrast", 0.0)) + s["contrast"]
            matedit.apply(cp, p, keep_original=False)
            copies[src.name] = cp
            slot.material = cp
            done += 1
    return done, kept


# ---------------------------------------------------------------- API

def _state(group):
    """The settings of a group: those of its distribution in the scene (an undo puts the old distribution back, with
    its own settings), else the group's."""
    for c in group.children:
        if c.get(KEY) and c.get(LAYER_KEY) and not c.get("simpler_trashed"):
            try:
                return json.loads(c[KEY])
            except ValueError:
                break
    try:
        return json.loads(group.get(KEY) or "{}")
    except ValueError:
        return {}


def _of(d):
    """(old group or None, its settings) from {group}."""
    gid = d.get("group")
    if gid:
        ob = find(gid, required=False)
        if ob is not None and ob.get(KEY):
            return ob, _state(ob)
    return None, {}


def apply(d):
    """POST scree/apply {terrain (its group or a zone), group (to make again), models, settings...}
    -> {group, pieces, reduced, recoloured}"""
    from . import paint, models, terrain as TR, trash, ecosystems, progress
    old, prev = _of(d)
    s = _clean(d, prev)
    tid = d.get("terrain") or prev.get("terrain")
    if old is not None and old.parent is not None and old.parent.get(TR.KEY):
        tid = old.parent.get(ID_KEY)
    g = TR._group(tid)
    if not s["models"]:
        raise ApiError(tr("Scegli almeno un modello di pietra (clic su un modello della libreria mentre «Pietre e detriti» è in scelta)"))
    entries = models._entries()
    names = [m for m in s["models"] if entries.get(m) is not None]
    if not names:
        raise ApiError(tr("I modelli di pietra scelti non sono più nella libreria"))
    p = TR._params(TR._current(g))
    zs = [o for o in TR.zone_objects(g).values()]
    progress.begin("scree", tr("Pietre e detriti"))
    try:
        progress.update(tr("Pareti e canaloni"), 0.1, "")
        f = TR._field(p)
        size_m = float(f["size"])
        M = int(min(GRID_MAX, max(256, size_m / 3.0)))
        xs = np.linspace(-size_m / 2, size_m / 2, M)
        ex = {}
        h, _sz, w_flat = TR._mesh_field(p, f, xs, xs, ex)
        dens, srt = density(p, f, xs, h, s)
        # (not on the «spianata» around the model, nor on the ramp of the edge down to the ground: made, not shed)
        dens *= (1.0 - np.clip(np.asarray(w_flat, np.float32), 0.0, 1.0)) * np.clip(np.asarray(ex["edge"], np.float32), 0.0, 1.0) ** 2
        # ---- the models: in the group's collection, their size
        progress.update(tr("Modelli delle pietre"), 0.4, "")
        made = []                                   # (what this call adds: away again if it fails)
        group = old
        gone = []
        if group is not None:
            olds = [c for c in group.children if c.get(paint.PAINT_KEY) and not c.get("simpler_trashed")]
            gone = [o for c in olds for o in [c] + list(c.children_recursive)]
            trash.trash(gone)
        else:
            group = link(bpy.data.objects.new(tr("Pietre e detriti"), None))
            group.empty_display_size = 0.5
            group[KIND_KEY] = "group"
            new_id(group)
            ecosystems._attach(group, g)
            made.append(group)
        lg = paint._new_group(tr("Pietre e detriti"), "area")
        made.append(lg)
        try:
            r, cam, n_all, reduced, recol, kept = _lay(d, s, prev, g, p, f, xs, M, h, dens, srt, zs, names, entries, lg, group)
        except Exception:
            for o in made:
                try:
                    bpy.data.objects.remove(o, do_unlink=True)
                except ReferenceError:
                    pass
            if gone:
                trash.restore(gone)                  # (the stones of before stay)
            raise
    finally:
        progress.end()
    lg = find(r["group"])
    lg[LAYER_KEY] = group.get(ID_KEY)
    mwl = lg.matrix_world.copy()
    lg.parent = group
    lg.matrix_parent_inverse = group.matrix_world.inverted()
    lg.matrix_world = mwl
    st = dict(s, terrain=g.get(ID_KEY), pieces=int(r["count"]))
    if cam is not None:
        st["camView"] = cam
    group[KEY] = json.dumps(st)
    lg[KEY] = group[KEY]
    refresh()
    log("SIMPLER_SCREE", f"{r['count']} pietre (di {n_all} sul terreno), griglia {M}, {recol} materiali ricolorati, ridotte {reduced}")
    return {"group": group.get(ID_KEY), "pieces": int(r["count"]), "reduced": reduced, "recoloured": recol, "kept": kept,
            "camOnly": cam is not None, "scree": st}


def _lay(d, s, prev, g, p, f, xs, M, h, dens, srt, zs, names, entries, lg, group):
    """The stones of apply: their models in lg's collection, recoloured, laid. -> (paint result, camera or None,
    stones on the whole terrain, reduced, recoloured, kept)"""
    from . import paint, ecosystems, progress, camview
    if True:
        coll = paint._scatter_coll(lg)
        dims = []
        for mid in names:
            got = paint._ensure_original(coll, mid, entries.get(mid))
            if got is None:
                dims.append((1.0, 1.0, 1.0))
                continue
            orig = got[0]
            from .models import _bbox
            lo, hi = _bbox([orig] + list(orig.children_recursive))
            dims.append((max(0.01, hi.x - lo.x), max(0.01, hi.y - lo.y), max(0.01, hi.z - lo.z)))
        dims = np.array(dims)
        target = _rock_color(g) if s["match"] > 0 else None
        recol, kept = _recolour(coll, group.get(ID_KEY), s, target)
        # ---- how many, where
        progress.update(tr("Posa delle pietre"), 0.6, "")
        cell = float(xs[1] - xs[0])
        mscale = np.array([s["modelScale"].get(m, 1.0) for m in names])
        mweight = np.array([s["modelWeight"].get(m, 1.0) for m in names])
        if mweight.sum() <= 0:
            mweight = np.ones(len(names))
        mweight = mweight / mweight.sum()
        foot = float((np.maximum(dims[:, 0], dims[:, 1]) * mscale * mweight).sum())
        smean = math.sqrt(s["sizeMin"] * s["sizeMax"]) * s["size"]     # (bigger: as covered, fewer - as per stone)
        area1 = (foot * smean) ** 2
        # (amount 50%: the core of a cone covered - a carpet of stones, as a real talus; 100%: piled up)
        expect = s["amount"] * 2.0 * dens * cell * cell / max(1e-4, area1)
        grow_c = np.ones_like(expect)
        reduced = False
        mw = np.array(zs[0].matrix_world) if zs else np.eye(4)
        # (only what the camera sees, as the ecosystems: «Calcola solo l'area inquadrata» · Pietre e detriti, unless
        # «Sempre intero»; the view of when it was made, until «Ricalcola dalla vista». 1.76.25: decided per cell
        # BEFORE the stones are made - before, the whole terrain was made first (3 million stones, Luca) and cut
        # evenly to the limit, so the frame got the same few as everywhere; and farther than d0 from the camera
        # fewer stones, bigger as they thin out - the ground as covered, the near ones all there)
        cam = None
        tris = None
        n_all = int(expect.sum())
        if camview.scree_wanted(s):
            cam = prev.get("camView") if (prev.get("camView") and not d.get("camRefresh")) else ecosystems._cam_now()
            if cam:
                # (1.76.52: the triangles of the zones read once, for the view and for laying the stones)
                tris = _tris(zs)
                view = ecosystems._View(cam, 0.15, tris[0], tris[1])
                on = np.nonzero(expect.ravel() > 0)[0]
                ri0, ci0 = on // M, on % M
                C = np.stack([xs[ci0], xs[ri0], h[ri0, ci0], np.ones(len(on))], 1) @ mw.T
                C = C[:, :3]
                lift = np.zeros_like(C); lift[:, 2] = 2.0 * float(dims[:, 2].max()) * s["sizeMax"] * s["size"]
                seen = np.zeros(len(on), bool)
                for dx, dy in ((0, 0), (-0.5, -0.5), (0.5, -0.5), (-0.5, 0.5), (0.5, 0.5)):
                    Q = C + np.array([dx * cell, dy * cell, 0.0])
                    seen |= view.visible(Q) | view.visible(Q + lift)
                e = expect.ravel()
                e[on[~seen]] = 0.0
                expect = e.reshape(expect.shape)
                if not expect.any():
                    raise ApiError(tr("La camera non vede le pareti e i canaloni dove cadono le pietre: inquadrali, o accendi «Sempre intero» (nelle Avanzate)"))
                total = float(expect.sum())
                if total > MAX_PIECES:
                    vis = np.nonzero(expect.ravel() > 0)[0]
                    dist = np.full(expect.size, 1.0)
                    Pc = np.stack([xs[vis % M], xs[vis // M], h[vis // M, vis % M], np.ones(len(vis))], 1) @ mw.T
                    dist[vis] = np.maximum(np.linalg.norm(Pc[:, :3] - np.array(view.pos), axis=1), 1.0)
                    ev = expect.ravel()
                    a_, b_ = 1.0, float(dist.max()) + 1.0
                    for _ in range(40):
                        m_ = 0.5 * (a_ + b_)
                        if float((ev * np.minimum(1.0, (m_ / dist) ** 2)).sum()) > MAX_PIECES:
                            b_ = m_
                        else:
                            a_ = m_
                    keep_p = np.minimum(1.0, (a_ / dist) ** 2)
                    expect = (ev * keep_p).reshape(expect.shape)
                    grow_c = np.clip(np.sqrt(1.0 / np.maximum(keep_p, 1e-6)), 1.0, 2.5).reshape(expect.shape)
                    log("SIMPLER_SCREE", f"più rade oltre {a_:.0f} m dalla camera ({int(total)} nell'inquadratura)")
                    reduced = True
            else:
                cam = None
        total = float(expect.sum())
        if total > MAX_PIECES:                     # (the whole terrain: evenly to the limit)
            expect *= MAX_PIECES / total
            reduced = True
        rng = np.random.default_rng(int(s["seed"]) & 0x7FFFFFFF)
        cnt = rng.poisson(expect)
        idx = np.nonzero(cnt.ravel())[0]
        reps = cnt.ravel()[idx]
        cells = np.repeat(idx, reps)
        n = len(cells)
        if not n:
            raise ApiError(tr("Su questo terreno non c'è posto per le pietre: niente pareti né canaloni (alza «Roccia scolpita» o la quantità)"))
        ri, ci = cells // M, cells % M
        lx = xs[ci] + (rng.random(n) - 0.5) * cell
        ly = xs[ri] + (rng.random(n) - 0.5) * cell
        sort_ = srt[ri, ci]
        grow = grow_c[ri, ci]
        P = np.stack([lx, ly, np.zeros(n), np.ones(n)], 1) @ mw.T
        ground = _ground(zs, tris)
        if ground is None:
            raise ApiError(tr("Il terreno è vuoto"))
        hit, z, _nrm = ground.drop(P[:, 0], P[:, 1])
        cut = ecosystems._sea_cut()
        if cut is not None:
            hit &= z > cut + 0.1
        wx, wy, z, sort_, grow = P[hit, 0], P[hit, 1], z[hit], sort_[hit], grow[hit]
        n = len(wx)
        if not n:
            raise ApiError(tr("Le pietre cadrebbero tutte sott'acqua"))
        mi = rng.choice(len(names), n, p=mweight)
        # size: sorted along the cone (small near the wall, big far) as much as «sort» says, else random
        u = rng.random(n)
        k = np.where(sort_ >= 0, s["sort"] * sort_ + (1 - s["sort"]) * u, u)
        sc = s["sizeMin"] * (s["sizeMax"] / s["sizeMin"]) ** np.clip(k + 0.15 * rng.normal(size=n), 0.0, 1.0)
        sc = sc * mscale[mi] * grow * s["size"]                           # (the size of each stone, as chosen for it; far: bigger)
        q = _rand_quat(rng, n)
        # the centre of the stone above the ground by (1 - 2 × bury) of its half size; the model turns about its base
        half = 0.5 * dims[mi].mean(axis=1) * sc
        bury = np.clip(s["bury"] * (0.6 + 0.8 * rng.random(n)), 0.0, 0.95)
        cz = z + half * (1.0 - 2.0 * bury)
        w, x, y, zq = q[:, 0], q[:, 1], q[:, 2], q[:, 3]
        # the model's centre is (0, 0, height/2) from its base: rotated, scaled
        hz = 0.5 * dims[mi, 2] * sc
        ox = 2 * (x * zq + y * w) * hz
        oy = 2 * (y * zq - x * w) * hz
        oz = (1 - 2 * (x * x + y * y)) * hz
        trs = np.stack([wx - ox, wy - oy, cz - oz, x, y, zq, w, sc], 1)
        dd = {"group": lg.get(ID_KEY), "noPlot": True, "noRefresh": True, "name": tr("Pietre e detriti"), "strokes": [],
              "seed": int(s["seed"]), "settings": {"mode": "area"}, "area": None,
              "palette": [{"model": m, "weight": 100} for m in names]}
        progress.update(tr("Posa delle pietre"), 0.85, "")
        r = paint._set_points(dd, names, mi.astype(np.int32), trs.astype(np.float64))
    return r, cam, n_all, reduced, recol, kept


def of_terrain(g):
    """The «Pietre e detriti» on a terrain: [{id, name, settings, models: [{id, name}]}] (not the ones in the trash)."""
    from . import models
    out = []
    entries = None
    for o in g.children:
        if not o.get(KEY) or o.get("simpler_trashed"):
            continue
        st = _state(o)
        if entries is None:
            entries = models._entries()
        out.append({"id": o.get(ID_KEY), "name": o.name, "settings": _clean(st), "pieces": int(st.get("pieces") or 0),
                    "camOnly": bool(st.get("camView")),
                    "models": [{"id": m, "name": (entries.get(m) or {}).get("name", m)} for m in st.get("models") or []]})
    return out


def regrow(g):
    """Made again on the terrain just changed (terrain._regrow_ecosystems). -> (done, failed [{name, error}])"""
    done, failed = 0, []
    for o in list(g.children):
        if not o.get(KEY) or o.get("simpler_trashed"):
            continue
        try:
            apply({"group": o.get(ID_KEY)})
            done += 1
        except ApiError as exc:
            failed.append({"name": o.name, "error": str(exc)})
        except Exception as exc:  # noqa: BLE001 - the terrain must not fail for its stones
            failed.append({"name": o.name, "error": str(exc)})
            log("SIMPLER_SCREE", "regrow failed", exc)
    return done, failed
