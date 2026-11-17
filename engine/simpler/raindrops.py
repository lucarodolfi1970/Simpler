"""Pioggia, gocce che cadono: real raindrops in the scene, only where the camera looks (as the snowflakes, snowfall.py),
and the splashes where they hit the ground.

Settings in the ambience (rain.drop*, in the Avanzate of the rain; read and clamped here):
  drop        on / off («Gocce che cadono»)
  dropAmount  «Intensità»: drops per cubic metre (from a drizzle to a downpour)
  dropWind, dropDir, dropGust   «Vento», «Direzione del vento», «Irregolarità»: the slant of the drops and how much it
              changes from drop to drop
  dropSize    «Dimensione delle gocce»: 0.4 .. 2.2 mm of radius (mean); bigger drops fall faster (terminal speed)
  dropClear   «Trasparenza delle gocce»: 0 pale streaks (rain against a dark background), 1 clear water (they refract
              what is behind them: seen only where the light plays on them)
  dropBlur    «Mosso»: each drop carries its speed (velocity), Cycles smears it during the shutter (0 = still drops,
              100% = 1/30 s: a streak of about 25 cm)
  dropFar     «Fin dove arrivano»: the drops as they are up to where one is a third of a pixel thin, beyond fewer as (d0/d)²
              and bigger as d/d0 (their streak too): every metre of depth covers the same share of the picture, a
              veil that thickens with the distance as in real rain
  dropWet     «Bagna le superfici»: the wetness of the surfaces follows the intensity (rain.settings: at least
              0.3 + 0.55 * intensity); the parts under a shelter stay dry as always
  splash, splashAmount  «Schizzi»: small crowns of droplets where the drops hit what faces up, near the camera
How the splashes find the ground: the triangles of the scene (and of the ground) rastered from above around the camera
(the highest at every cell centre: where the rain lands - a roof, not the floor under it); a splash only on a cell
whose neighbours are at about the same height (flat: no splash on a wall, an edge or a steep slope), in the frame and
within SPLASH_FAR. Both in one point cloud with one material (water); the real-time view draws the same points from
GET rain/raindrops.bin. Not saved with the project (made again when needed, as the flakes).
"""
import math
import os
import time

import bpy

from mathutils import Vector

from .core import INTERNAL_KEY, log

DROP_KEY = "simpler_raindrops"
MAT_NAME = "Simpler Gocce v6"
FALL_NEAR = 0.3
WIND_MAX = 14.0             # m/s at «Vento» 100%
MAX_DROPS = 600_000
MAX_SPLASH_PTS = 300_000
PER_SPLASH = 13             # droplets in a splash (the last two: the jet in the middle)
SPLASH_FAR = 20.0           # metres: splashes farther than this are not seen (sub-pixel, faint)
SHUTTER = 1.0 / 30.0        # s at «Mosso» 100%
DROP_DEFAULTS = {"drop": False, "dropAmount": 0.5, "dropSize": 0.5, "dropWind": 0.15, "dropDir": 0.0, "dropGust": 0.3,
                 "dropClear": 0.5, "dropBlur": 0.6, "dropFar": 40.0, "dropSeed": 1, "dropWet": True,
                 "splash": True, "splashAmount": 0.5,
                 # «Gocce sulle superfici» (rain._drops_nodes): read by rain.settings
                 "beads": True, "beadAmount": 0.5, "beadSize": 0.5, "beadBig": 0.3, "beadRivul": 0.4, "beadFilm": 0.5,
                 "puddleRings": 0.5}
F = {"sig": None, "meta": None, "rev": 0, "secs": 0.0, "dirty": True, "active": False, "camkey": None, "geo": None}


def _raw():
    from . import ambience
    s = ambience.state()
    if not s or s.get("mode") not in ("sky", "hdri"):
        return None, None
    return s, dict(DROP_DEFAULTS, **(s.get("rain") or {}))


def settings():
    """The drops' settings while they fall, else None (off, studio, or while it snows: then the rain waits)."""
    s, r = _raw()
    if r is None:
        return None
    c = lambda k, lo, hi: max(lo, min(hi, float(r.get(k, DROP_DEFAULTS[k]))))
    if not r.get("drop") or c("dropAmount", 0, 1) <= 0:
        return None
    from . import rain
    rs = rain.settings(s)
    if rs is None or rs.get("snowing"):
        return None
    from . import snowfall
    if snowfall.settings() is not None:            # (flakes falling: it snows, not rains)
        return None
    return {"amount": c("dropAmount", 0, 1), "size": c("dropSize", 0, 1), "wind": c("dropWind", 0, 1),
            "dir": c("dropDir", -360, 720) % 360.0, "gust": c("dropGust", 0, 1), "clear": c("dropClear", 0, 1),
            "blur": c("dropBlur", 0, 1), "far": c("dropFar", 10, 300), "seed": int(r.get("dropSeed", 1) or 1),
            "splash": bool(r.get("splash", True)), "splashAmount": c("splashAmount", 0, 1),
            "outdoor": bool(rs.get("outdoor", True))}


def wet_from_drops(r):
    """The wetness the falling drops give (rain.settings: the surfaces follow the intensity), 0 when they do not."""
    if not r or not r.get("drop") or not r.get("dropWet", True):
        return 0.0
    a = max(0.0, min(1.0, float(r.get("dropAmount", 0.5))))
    return 0.3 + 0.55 * a if a > 0 else 0.0


def intensity():
    """How hard it rains with drops now (0: no drops) - the rings on the water follow it (ripples.py)."""
    st = settings()
    return st["amount"] if st else 0.0


def _outdoor_mask(P):
    """Which points are not under a shelter (as snowfall._outdoor)."""
    import numpy as np
    from . import rain
    from .snowfall import _filled
    meta = rain.SH["meta"]
    if meta is None:
        return np.ones(len(P), bool)
    sh = _filled(meta)
    sn = int(meta["n"])
    si = np.floor((P[:, 1] - meta["y0"]) / meta["cell"]).astype(np.int64)
    sj = np.floor((P[:, 0] - meta["x0"]) / meta["cell"]).astype(np.int64)
    inside = (si >= 0) & (si < sn) & (sj >= 0) & (sj < sn)
    v = np.zeros(len(P), dtype=np.float32)
    v[inside] = sh[si[inside], sj[inside]]
    hs = np.where(v > 1e-4, meta["zmin"] + v * meta["zr"], -1e9)
    return hs < P[:, 2] + 0.05


def _camera():
    from . import camview
    return camview.camera()


def _sig(st, cam):
    from . import rain
    sh = (rain.SH["meta"] or {}).get("file") if st["outdoor"] else None
    r = lambda v: tuple(round(float(x), 2) for x in v)
    return repr((sorted(st.items()), r(cam["pos"]), r(cam["target"]), round(cam["aspect"], 2), round(cam["lens"], 1),
                 round(cam.get("width", 0)), sh, _hit_sig()))      # (always: the drops are taken out of the objects too)


def _frame(cam):
    import numpy as np
    pos = np.array(cam["pos"], dtype=np.float64)
    f = np.array(cam["target"], dtype=np.float64) - pos
    f /= max(float(np.linalg.norm(f)), 1e-6)
    rgt = np.cross(f, [0.0, 0.0, 1.0])
    if np.linalg.norm(rgt) < 1e-6:
        rgt = np.array([1.0, 0.0, 0.0])
    rgt /= np.linalg.norm(rgt)
    up = np.cross(rgt, f)
    aspect, half = max(0.05, cam["aspect"]), math.atan(18.0 / max(1.0, cam["lens"]))
    if aspect >= 1:
        tx = math.tan(half); ty = tx / aspect
    else:
        ty = math.tan(half); tx = ty * aspect
    return pos, f, rgt, up, tx * 1.15, ty * 1.15      # (a margin: made again only when the camera moved enough)


def _terminal(diam_mm):
    """Fall speed of a raindrop (m/s) from its diameter (Atlas, Srivastava and Sekhon 1973)."""
    import numpy as np
    return np.maximum(0.8, 9.65 - 10.3 * np.exp(-0.6 * diam_mm))


def drops(st, cam):
    """-> positions (n, 3), radii (n,), speeds (n, 3) of the falling drops."""
    import numpy as np
    from .snowfall import _waves
    rng = np.random.default_rng(st["seed"] * 7919 + 29)
    pos, f, rgt, up, tx, ty = _frame(cam)
    far = st["far"]
    # Up to d0 the drops as they are; beyond, a drop would be thinner than a third of a pixel: fewer drops (as (d0/d)²),
    # each as much bigger (d / d0) - the same share of the picture covered by every metre of depth, as real rain,
    # which far away becomes a grey veil the farther it goes (with (d0/d)⁴ as the flakes, beyond 40 m nothing was
    # added: «Fin dove arrivano» at 150 m looked as 40)
    from . import camview
    r0 = 0.0004 + 0.0018 * st["size"] ** 1.2
    pixel = camview.Frustum(cam, 0.0).pixel
    d0 = max(FALL_NEAR + 0.5, min(far, r0 / (0.3 * pixel)))
    rho = 700.0 * st["amount"] ** 1.7                 # drops per m³ near the camera (1.66.1: 400 - a downpour too thin)
    a = (d0 ** 3 - FALL_NEAR ** 3) / 3.0
    b = d0 ** 2 * max(0.0, far - d0)
    # over the limit: the drops near the camera are kept (they make a downpour look dense), the veil far away gets
    # fewer and bigger ones (the same coverage); before, all were thinned alike - 2700 drops within 3 m at 100%
    nn, nf = rho * 4.0 * tx * ty * a, rho * 4.0 * tx * ty * b
    s_near = max(1.0, nn / (0.7 * MAX_DROPS))
    n_near = int(nn / s_near)
    s_far = max(1.0, nf / max(1.0, MAX_DROPS - n_near))
    n = n_near + int(nf / s_far)
    u = rng.random(n)
    d = np.empty(n)
    d[:n_near] = (FALL_NEAR ** 3 + u[:n_near] * (d0 ** 3 - FALL_NEAR ** 3)) ** (1.0 / 3.0)
    if n > n_near:
        d[n_near:] = d0 + u[n_near:] * (far - d0)              # (pdf constant in depth)
    scale = np.where(np.arange(n) < n_near, s_near, s_far)
    sx = rng.uniform(-1, 1, n) * tx * d
    sy = rng.uniform(-1, 1, n) * ty * d
    P = pos[None] + f[None] * d[:, None] + rgt[None] * sx[:, None] + up[None] * sy[:, None]
    if st["outdoor"]:
        from .snowfall import _outdoor
        keep = _outdoor_mask(P)
        P, d, scale = P[keep], d[keep], scale[keep]
    # near the camera: none inside or under what the rain hits (a car that does not shelter the road, a copy of a
    # distribution) - the same map as the splashes
    try:
        H, m = _surface(cam, min(SPLASH_FAR, st["far"]))
        j = np.floor((P[:, 0] - m["x0"]) / m["cell"]).astype(np.int64)
        i = np.floor((P[:, 1] - m["y0"]) / m["cell"]).astype(np.int64)
        inside = (i >= 0) & (i < m["n"]) & (j >= 0) & (j < m["n"])
        top = np.full(len(P), -np.inf)
        top[inside] = H[i[inside], j[inside]]
        keep = ~(P[:, 2] < top)
        P, d, scale = P[keep], d[keep], scale[keep]
    except Exception as exc:
        log(f"SIMPLER_RAIN drops under surfaces: {exc}")
    n = len(P)
    # sizes: mostly small, a few big ones; the speed from the real size (a big drop falls faster)
    rad = r0 * rng.lognormal(0.0, 0.3, n)
    vz = _terminal(rad * 2000.0)
    grow = np.maximum(1.0, d / d0)
    rad = rad * np.sqrt(scale) * grow          # (far: fewer and bigger - a veil)
    wdir = math.radians(st["dir"])
    wind = np.array([math.sin(wdir), math.cos(wdir), 0.0]) * WIND_MAX * st["wind"] ** 1.2
    V = np.tile(wind, (n, 1))
    V[:, 2] = -vz
    if st["gust"] > 0:
        # (rain is heavy: the eddies bend it less than the snow, the wind changes from place to place)
        g = 0.6 + 2.5 * st["gust"] + 0.35 * WIND_MAX * st["wind"] * st["gust"]
        for ax in range(2):
            V[:, ax] += g * _waves(rng, 5, 6.0 + 3.0 * ax)(P)
        V[:, :2] *= (1.0 + 0.25 * st["gust"] * rng.uniform(-1, 1, (n, 1)))
    V *= np.sqrt(grow)[:, None]                   # (and its streak longer: still a streak, not a dot)
    return P.astype(np.float32), rad.astype(np.float32), V.astype(np.float32)


# ---------------------------------------------------------------- the splashes

_SURF = {"key": None, "H": None, "meta": None}
_TRI_CACHE = {}
_GEO = {"sig": None}
SPLASH_TRIS = 30_000_000        # triangles of copies of distributions rastered at most for the splashes
SPLASH_MIN_H = 0.3              # metres: lower models of distributions (grass) carry no splashes


def _mkey(M):
    return tuple(round(M[r][c], 4) for r in range(3) for c in range(4))


def _hit_objects():
    """What the rain hits from above: every visible mesh of the scene and the ground - also those that do not shelter
    («Non fa riparo»: a car - the rain still bounces on it), not «Sempre asciutto», decals, fog and clouds."""
    from .core import INTERNAL_KEY
    from . import paint, rain, volumetric
    out = []
    for ob in bpy.context.scene.objects:
        if ob.type != "MESH" or ob.get(INTERNAL_KEY) or ob.get("simpler_trashed") or ob.hide_render:
            continue
        if ob.get(paint.DATA_KEY) or ob.get(rain.DRY_KEY) or ob.modifiers.get("Simpler Decal") is not None:
            continue
        if volumetric.is_volume_object(ob):
            continue
        out.append(ob)
    return out


def _hit_copies():
    from . import paint, rain

    def dry(o):
        while o is not None:
            if rain.rain_dry(o):
                return True
            o = o.parent
        return False
    # (a distribution with «Niente pioggia»: no splashes on it, as on a single object)
    return [ob for ob in bpy.context.scene.objects if ob.get(paint.DATA_KEY) and not ob.get("simpler_trashed")
            and not ob.hide_render and not dry(ob)]


def _hit_sig(obs=None, copies=None):
    obs = _hit_objects() if obs is None else obs
    copies = _hit_copies() if copies is None else copies
    return hash((tuple((o.name, o.data.name, len(o.data.vertices), _mkey(o.matrix_world)) for o in obs),
                 tuple((po.name, po.data.name, len(po.data.vertices), _mkey(po.matrix_world)) for po in copies)))


def _tris(ob, cut):
    """World triangles of a mesh (without cut-out materials) and their xy boxes; kept while it stays the same."""
    import numpy as np
    from . import snow
    for m in ob.data.materials:
        if m is not None and m.name not in cut:
            cut[m.name] = snow._cutout(m)
    key = (ob.name, ob.data.name, len(ob.data.vertices), _mkey(ob.matrix_world),
           _GEO["sig"] if ob.modifiers else None)       # (modifiers: again when the geometry of the scene changed)
    got = _TRI_CACHE.get(ob.name)
    if got is not None and got[0] == key:
        _TRI_CACHE[ob.name] = _TRI_CACHE.pop(ob.name)        # (the most recent at the end: the oldest go first)
        return got[1]
    dg = bpy.context.evaluated_depsgraph_get()
    me = ob.evaluated_get(dg).data
    nv, nt = len(me.vertices), len(me.loop_triangles)
    if not nv or not nt:
        out = (np.zeros((0, 3, 3), np.float32), np.zeros((0, 4), np.float32))
    else:
        co = np.empty(nv * 3, dtype=np.float32)
        me.vertices.foreach_get("co", co)
        Mw = np.array(ob.matrix_world, dtype=np.float32)
        V = co.reshape(-1, 3) @ Mw[:3, :3].T + Mw[:3, 3]
        tri = np.empty(nt * 3, dtype=np.int32)
        me.loop_triangles.foreach_get("vertices", tri)
        T = tri.reshape(-1, 3)
        bad = [i for i, sl in enumerate(ob.material_slots) if sl.material is not None and cut.get(sl.material.name)]
        if bad:
            mi = np.empty(nt, dtype=np.int32)
            me.loop_triangles.foreach_get("material_index", mi)
            T = T[~np.isin(mi, bad)]
        P = V[T]
        box = np.stack([P[:, :, 0].min(1), P[:, :, 0].max(1), P[:, :, 1].min(1), P[:, :, 1].max(1)], axis=1)
        out = (P.astype(np.float32), box.astype(np.float32))
    while len(_TRI_CACHE) >= 400:                         # (before 1.67.5 all of it was dropped: a city made it
        _TRI_CACHE.pop(next(iter(_TRI_CACHE)))              # again at every move of the camera)
    _TRI_CACHE[ob.name] = (key, out)
    return out


def _copies_tris(copies, cut):
    """[(triangles of a model in the space of its copies (m, 3, 3), copies (n, 4, 4), radius)] of the distributions
    (models lower than SPLASH_MIN_H left out: grass)."""
    import numpy as np
    from . import paint
    out = []
    for po in copies:
        me = po.data
        n = len(me.vertices)
        xa, ma = me.attributes.get("simpler_xform"), me.attributes.get("simpler_model")
        group = po.parent
        coll = bpy.data.collections.get(group.get(paint.SCATTER_COLL) or "") if group is not None else None
        if not n or xa is None or ma is None or coll is None:
            continue
        xf = np.empty(n * 16, dtype=np.float32)
        xa.data.foreach_get("value", xf)
        xf = xf.reshape(n, 4, 4).transpose(0, 2, 1)
        mi = np.empty(n, dtype=np.int32)
        ma.data.foreach_get("value", mi)
        pm = np.array(po.matrix_world, dtype=np.float32)
        subs = list(coll.children)
        for k in np.unique(mi):
            if k < 0 or k >= len(subs):
                continue
            parts = [_tris(o, cut)[0] for o in subs[k].all_objects if o.type == "MESH" and not o.hide_render]
            parts = [p for p in parts if len(p)]
            if not parts:
                continue
            P = np.concatenate(parts)
            W = pm[None] @ xf[mi == k]
            sc = np.linalg.norm(W[:, :3, 2], axis=1)
            h = float(P[:, :, 2].max() - P[:, :, 2].min())
            W = W[h * sc >= SPLASH_MIN_H]
            if not len(W):
                continue
            rad = float(np.abs(P[:, :, :2]).max()) * float(np.linalg.norm(W[:, :3, :3], axis=1).max())
            out.append((P, W, rad))
    return out


def _surface(cam, far_s):
    """The highest surface of the scene around the camera, seen from above: heights at cell centres (or -inf)."""
    import numpy as np
    from . import rain, snow
    # only the part of the ground the frame can see within far_s (seen from above: the camera and the corners of the
    # frame at far_s), on a grid of steps (kept while the camera moves a little)
    import numpy as np
    pos, f, rgt, up, tx, ty = _frame(cam)
    pts = [pos[:2]]
    for a in (-1, 1):
        for b in (-1, 1):
            d = f + rgt * tx * a + up * ty * b
            d = d / max(float(np.linalg.norm(d)), 1e-9)
            pts.append((pos + d * far_s)[:2])
    pts = np.array(pts)
    step = max(2.0, far_s / 4.0)
    lo = np.floor((pts.min(0) - 0.5 * step) / step) * step
    hi = np.ceil((pts.max(0) + 0.5 * step) / step) * step
    side = float(max(hi - lo))
    cell = max(0.06, side / 1000.0)
    n = int(math.ceil(side / cell))
    x0, y0 = float(lo[0]), float(lo[1])
    obs = _hit_objects()
    copies = _hit_copies()
    key = (_hit_sig(obs, copies), round(x0, 3), round(y0, 3), n, round(cell, 5))
    if _SURF["key"] == key:
        return _SURF["H"], _SURF["meta"]
    t0 = time.time()
    _GEO["sig"] = rain._geometry_sig()
    H = np.full(n * n, -np.inf, dtype=np.float32)
    cut = {}
    x1, y1 = x0 + n * cell, y0 + n * cell

    def put(P, box):
        if not len(P):
            return
        sel = (box[:, 1] >= x0) & (box[:, 0] <= x1) & (box[:, 3] >= y0) & (box[:, 2] <= y1)
        if sel.any():
            snow._raster(P[sel], box[sel], x0, y0, n, n, cell, H)
    for ob in obs:
        # (only the objects over the area: their box in the world first, without reading their triangles)
        if not ob.modifiers:
            c = [ob.matrix_world @ Vector(b) for b in ob.bound_box]
            if max(v.x for v in c) < x0 or min(v.x for v in c) > x1 or max(v.y for v in c) < y0 or min(v.y for v in c) > y1:
                continue
        P, box = _tris(ob, cut)
        put(P, box)
    # the copies of the distributions (cars, benches, trees: the rain bounces on them too), those in the area only
    ntri = 0
    for P0, W, rad in _copies_tris(copies, cut):
        t = W[:, :3, 3]
        near = (t[:, 0] >= x0 - rad) & (t[:, 0] <= x1 + rad) & (t[:, 1] >= y0 - rad) & (t[:, 1] <= y1 + rad)
        Wn = W[near].astype(np.float32)
        per = max(1, 3_000_000 // max(1, len(P0) * 3))        # (the copies in groups: one numpy step for many)
        for a in range(0, len(Wn), per):
            if ntri > SPLASH_TRIS:
                break
            Wb = Wn[a:a + per]
            P = (np.matmul(P0.reshape(1, -1, 3).astype(np.float32), Wb[:, :3, :3].transpose(0, 2, 1)) + Wb[:, None, :3, 3]).reshape(-1, 3, 3)
            ntri += len(P)
            box = np.stack([P[:, :, 0].min(1), P[:, :, 0].max(1), P[:, :, 1].min(1), P[:, :, 1].max(1)], axis=1)
            put(P, box.astype(np.float32))
    H = H.reshape(n, n)
    meta = {"x0": x0, "y0": y0, "n": n, "cell": cell}
    _SURF.update(key=key, H=H, meta=meta)
    log(f"SIMPLER_RAIN splash ground: {n}x{n} cells of {cell * 100:.1f} cm in {time.time() - t0:.2f} s")
    return H, meta


def splashes(st, cam):
    """-> positions, radii, speeds of the droplets of the splashes (crowns) on what faces up near the camera."""
    import numpy as np
    from . import camview
    z3 = (np.zeros((0, 3), np.float32), np.zeros(0, np.float32), np.zeros((0, 3), np.float32))
    if not st["splash"] or st["splashAmount"] <= 0:
        return z3
    far_s = min(SPLASH_FAR, st["far"])
    H, m = _surface(cam, far_s)
    n, cell = m["n"], m["cell"]
    rng = np.random.default_rng(st["seed"] * 104729 + 3)
    rho = 40.0 * st["splashAmount"] * st["amount"] ** 1.2              # splashes per m² seen in one picture
    k = int(min(2_000_000, rho * (n * cell) ** 2))
    if k <= 0:
        return z3
    # anywhere (not on the cells' lattice): the height between the four nearest cell centres, only where they are at
    # about the same height - flat (no splash on a wall top, an edge, a steep slope)
    u = rng.uniform(0.5, n - 1.5, k)
    v = rng.uniform(0.5, n - 1.5, k)
    j0 = np.floor(u - 0.5).astype(np.int64); i0 = np.floor(v - 0.5).astype(np.int64)
    fu = u - 0.5 - j0; fv = v - 0.5 - i0
    z00, z01, z10, z11 = H[i0, j0], H[i0, j0 + 1], H[i0 + 1, j0], H[i0 + 1, j0 + 1]
    tol = 0.45 * cell + 0.004
    with np.errstate(invalid="ignore"):
        zs = np.stack([z00, z01, z10, z11])
        ok = np.isfinite(zs).all(0) & ((zs.max(0) - zs.min(0)) < tol * 1.5)
    z = (z00 * (1 - fu) + z01 * fu) * (1 - fv) + (z10 * (1 - fu) + z11 * fu) * fv
    S = np.stack([m["x0"] + u * cell, m["y0"] + v * cell, z], axis=1)[ok]
    fr = camview.Frustum(cam, 0.05)
    dist, inside = fr.look(S, 0.05)
    keep = inside & (dist <= far_s) & (dist > 0.4)
    S, dist = S[keep], dist[keep]
    ns = len(S)
    if not ns:
        return z3
    per = PER_SPLASH
    if ns * per > MAX_SPLASH_PTS:
        pick = rng.choice(ns, MAX_SPLASH_PTS // per, replace=False)
        S, dist, ns = S[pick], dist[pick], MAX_SPLASH_PTS // per
    # a crown: droplets on a ring that rises from the impact, a couple higher in the middle; splashes of all ages
    sz = st["size"]
    age = rng.uniform(0.3, 1.3, (ns, 1))
    R0 = (0.014 + 0.016 * sz) * age
    th = (np.arange(per)[None] * (2 * math.pi / (per - 2)) + rng.uniform(0, 2 * math.pi, (ns, 1))
          + rng.uniform(-0.25, 0.25, (ns, per)))
    rr = R0 * rng.uniform(0.75, 1.25, (ns, per))
    hz = (0.003 + (0.016 + 0.016 * sz) * rng.random((ns, per)) ** 1.5) * age
    mid = np.zeros((ns, per), bool)
    mid[:, -2:] = True                                         # (two in the middle: the jet)
    rr = np.where(mid, rr * 0.15, rr)
    hz = np.where(mid, hz * 1.8 + 0.008 * age, hz)
    P = np.empty((ns, per, 3))
    P[..., 0] = S[:, 0:1] + rr * np.cos(th)
    P[..., 1] = S[:, 1:2] + rr * np.sin(th)
    P[..., 2] = S[:, 2:3] + hz
    sp = rng.uniform(0.6, 1.8, (ns, per))
    V = np.empty((ns, per, 3))
    V[..., 0] = np.cos(th) * sp * np.where(mid, 0.1, 1.0)
    V[..., 1] = np.sin(th) * sp * np.where(mid, 0.1, 1.0)
    V[..., 2] = rng.uniform(-0.3, 1.0, (ns, per)) + np.where(mid, 1.2, 0.0)
    rad = (0.0009 + 0.0011 * sz) * rng.lognormal(0.0, 0.3, (ns, per))
    # (far they become fainter, as in a photograph - not bigger: specks of white all over the ground looked like snow)
    return (P.reshape(-1, 3).astype(np.float32), rad.reshape(-1).astype(np.float32),
            V.reshape(-1, 3).astype(np.float32))


# ---------------------------------------------------------------- the objects

def _material(st):
    m = bpy.data.materials.get(MAT_NAME)
    if m is None:
        m = bpy.data.materials.new(MAT_NAME)
        m.use_nodes = True
        nt = m.node_tree
        nt.nodes.clear()
        out = nt.nodes.new("ShaderNodeOutputMaterial")
        # Water, both: «pale» is rough water (it scatters the light of the sky and of the lamps: a visible streak),
        # «clear» is smooth water (a small lens: what is behind it, upside down, and the glints). Not a white
        # material (1.65.0-1.65.1: at a low «Trasparenza» the drops near the camera looked like white balls).
        # A perfectly smooth sphere of water sends a lamp to the camera only by chance (a path tracer cannot aim at
        # a light through two refractions): the clear water keeps a little rough water in it, so at night the drops
        # still glow around a street lamp (roughness 0.5: tried 0.08, 0.22, 0.4, 0.5 on lamps at night)
        pale = nt.nodes.new("ShaderNodeBsdfPrincipled")
        pale.inputs["Base Color"].default_value = (1, 1, 1, 1)
        pale.inputs["Roughness"].default_value = 0.5
        pale.inputs["Transmission Weight"].default_value = 1.0
        pale.inputs["IOR"].default_value = 1.33
        smooth = nt.nodes.new("ShaderNodeBsdfPrincipled")
        smooth.inputs["Base Color"].default_value = (1, 1, 1, 1)
        smooth.inputs["Roughness"].default_value = 0.0
        smooth.inputs["Transmission Weight"].default_value = 1.0
        smooth.inputs["IOR"].default_value = 1.33
        glass = nt.nodes.new("ShaderNodeMixShader")
        glass.inputs["Fac"].default_value = 0.75          # (the clear water: three quarters smooth, a quarter rough)
        nt.links.new(pale.outputs[0], glass.inputs[1])
        nt.links.new(smooth.outputs[0], glass.inputs[2])
        mix = nt.nodes.new("ShaderNodeMixShader")
        nt.links.new(pale.outputs[0], mix.inputs[1])
        nt.links.new(glass.outputs[0], mix.inputs[2])
        nt.links.new(mix.outputs[0], out.inputs["Surface"])
        # (the droplets of a splash paler than the falling drops: a burst of spray catches the light)
        clear = nt.nodes.new("ShaderNodeValue"); clear.name = "clear"
        att = nt.nodes.new("ShaderNodeAttribute"); att.attribute_type = "GEOMETRY"; att.attribute_name = "simpler_splash"
        k = nt.nodes.new("ShaderNodeMath"); k.operation = "MULTIPLY_ADD"
        nt.links.new(att.outputs["Fac"], k.inputs[0]); k.inputs[1].default_value = -0.7; k.inputs[2].default_value = 1.0
        f = nt.nodes.new("ShaderNodeMath"); f.operation = "MULTIPLY"
        nt.links.new(clear.outputs[0], f.inputs[0]); nt.links.new(k.outputs[0], f.inputs[1])
        nt.links.new(f.outputs[0], mix.inputs["Fac"])
        # the spray of a splash: a cloud of tiny droplets scatters the light as a white mist, not as one lens (on the
        # dark asphalt at night the splashes of clear water were not seen)
        spray = nt.nodes.new("ShaderNodeBsdfPrincipled")
        spray.inputs["Base Color"].default_value = (0.9, 0.92, 0.95, 1)
        spray.inputs["Roughness"].default_value = 0.4
        spray.inputs["Transmission Weight"].default_value = 0.4
        spray.inputs["IOR"].default_value = 1.33
        sm = nt.nodes.new("ShaderNodeMixShader")
        sf = nt.nodes.new("ShaderNodeMath"); sf.operation = "MULTIPLY"; sf.inputs[1].default_value = 0.7
        nt.links.new(att.outputs["Fac"], sf.inputs[0]); nt.links.new(sf.outputs[0], sm.inputs["Fac"])
        nt.links.new(mix.outputs[0], sm.inputs[1]); nt.links.new(spray.outputs[0], sm.inputs[2])
        nt.links.new(sm.outputs[0], out.inputs["Surface"])
    clear = m.node_tree.nodes.get("clear")
    if clear is not None:
        clear.outputs[0].default_value = float(st["clear"])
    return m


def _object():
    for ob in bpy.context.scene.objects:
        if ob.get(DROP_KEY):
            return ob
    return None


def remove():
    ob = _object()
    from .snowfall import _motion_blur
    _motion_blur(False, "rain")
    if ob is None:
        return False
    pc = ob.data
    bpy.data.objects.remove(ob, do_unlink=True)
    if pc is not None and pc.users == 0:
        bpy.data.pointclouds.remove(pc)
    return True


def _build(P, R, V, st, n_drops=None):
    import numpy as np
    from .snowfall import _motion_blur
    ob = _object()
    pc = bpy.data.pointclouds.new(MAT_NAME)
    pc.resize(len(P))
    pc.attributes["position"].data.foreach_set("vector", P.ravel())
    ra = pc.attributes.get("radius") or pc.attributes.new("radius", "FLOAT", "POINT")
    ra.data.foreach_set("value", R)
    if n_drops is not None and n_drops < len(P):
        sa = pc.attributes.new("simpler_splash", "FLOAT", "POINT")
        flag = np.zeros(len(P), np.float32); flag[n_drops:] = 1.0
        sa.data.foreach_set("value", flag)
    blur = st["blur"] > 0.001
    if blur:
        fps = bpy.context.scene.render.fps / max(bpy.context.scene.render.fps_base, 1e-6)
        k = st["blur"] * SHUTTER * fps / 0.5
        va = pc.attributes.new("velocity", "FLOAT_VECTOR", "POINT")
        va.data.foreach_set("vector", (V * k).astype(np.float32).ravel())
    pc.materials.append(_material(st))
    if ob is None:
        ob = bpy.data.objects.new(MAT_NAME, pc)
        ob[DROP_KEY] = True
        ob[INTERNAL_KEY] = 1
        bpy.context.scene.collection.objects.link(ob)
        ob.hide_select = True
        ob.visible_shadow = False           # (tiny shadows: only noise, and time)
    # (the light bounced by walls and ground does not look for the drops - they matter seen directly, in
    # reflections and through glass; with hundreds of thousands of them that is time saved at every bounce)
    ob.visible_diffuse = False
    ob.visible_volume_scatter = False
    if ob.data is not pc:
        old = ob.data
        ob.data = pc
        if old is not None and old.users == 0:
            bpy.data.pointclouds.remove(old)
    _motion_blur(blur, "rain")


def _write_view(P, R, V, st):
    """rain/raindrops.bin: «RDP1», u32 count, float32 blur (s), float32 clear, then per point 7 float32: position,
    radius, speed."""
    import numpy as np
    from . import rain
    d = rain._shelter_dir()
    for f in os.listdir(d):
        if f.startswith("raindrops_"):
            try:
                os.remove(os.path.join(d, f))
            except OSError:
                pass
    stem = f"raindrops_{os.getpid()}_{F['rev']}"
    with open(os.path.join(d, stem + ".bin"), "wb") as fh:
        fh.write(np.array([0x31504452, len(P)], dtype=np.uint32).tobytes())
        fh.write(np.array([st["blur"] * SHUTTER, st["clear"]], dtype=np.float32).tobytes())
        fh.write(np.concatenate([P, R[:, None], V], axis=1).astype(np.float32).tobytes())
    return stem


def view_file(name):
    from . import rain
    name = os.path.basename(name or "")
    if not name.startswith("raindrops_") or not name.endswith(".bin"):
        return ""
    p = os.path.join(rain._shelter_dir(), name)
    return p if os.path.isfile(p) else ""


def _camkey():
    from . import render, camview
    c = render.STATE.camera
    return (tuple(c.get("target") or ()), c.get("yaw"), c.get("pitch"), c.get("distance"), c.get("lens"),
            tuple(render.STATE.vp_size or ()), camview.FRAME.get("aspect"))


def touch():
    """The ambience changed: looked at again in the engine's idle time."""
    F["dirty"] = True


CAM_STILL = 0.6                     # seconds the camera stays still before the drops follow it in the view


def due(wait=False):
    """Cheap (from the engine's loop): the settings were touched, or the camera moved while it rains, or the shelter
    or the geometry changed. wait: a camera that moved waits to stay still (the path tracing of the view: before
    1.67.5 the drops were made again at every step of an orbit, 0.5 s and more each; the last ones stay meanwhile)."""
    from . import rain
    if F.get("dirty"):
        return True
    if not F.get("active"):
        return False
    if (rain.SH["meta"] or {}).get("file") != F.get("shrev") or rain._STATE["changes"] != F.get("geo"):
        return True
    if _camkey() == F.get("camkey"):
        return False
    # the camera moved: made again only when enough for the margin around the frame to run out (camview.moved) -
    # at every small step of the wheel it was half a second of the engine and 10 MB for the view each time
    from . import camview
    if F.get("cam") is not None and not camview.moved(F["cam"], _camera()):
        F["camkey"] = _camkey()
        return False
    if wait:
        k = _camkey()
        if k != F.get("still"):
            F.update(still=k, still_t=time.time())
            return False
        return time.time() - F.get("still_t", 0.0) > CAM_STILL
    return True


def update(force=False):
    """The drops follow the camera and the settings. True when they changed."""
    import numpy as np
    from . import rain
    F["dirty"] = False
    F["camkey"] = _camkey()
    F["shrev"] = (rain.SH["meta"] or {}).get("file")
    F["geo"] = rain._STATE["changes"]
    st = settings()
    F["active"] = st is not None
    if st is None:
        had = F["meta"] is not None
        F.update(sig=None, meta=None)
        if had:
            _forget()
        return remove() or had
    cam = _camera()
    F["cam"] = cam
    sig = _sig(st, cam)
    if sig == F["sig"] and not force and _object() is not None:
        return False
    t0 = time.time()
    P, R, V = drops(st, cam)
    nd = len(P)
    try:
        Ps, Rs, Vs = splashes(st, cam)
    except Exception as exc:                        # (a splash less is not worth a failed picture)
        log(f"SIMPLER_RAIN splashes failed: {exc}")
        Ps = np.zeros((0, 3), np.float32); Rs = np.zeros(0, np.float32); Vs = np.zeros((0, 3), np.float32)
    P, R, V = np.concatenate([P, Ps]), np.concatenate([R, Rs]), np.concatenate([V, Vs])
    _build(P, R, V, st, nd)
    F["rev"] += 1
    stem = _write_view(P, R, V, st)
    F["sig"] = sig
    F["secs"] = round(time.time() - t0, 2)
    F["meta"] = {"rev": F["rev"], "file": stem + ".bin", "count": int(nd), "splashes": int(len(Ps)) // PER_SPLASH,
                 "secs": F["secs"]}
    log(f"SIMPLER_RAIN drops: {nd} + {len(Ps)} in splashes, {F['secs']} s")
    return True


def _forget():
    """Rain off: the triangles kept for the splashes and the file of the view go (hundreds of MB in a city)."""
    _SURF.update(key=None, H=None, meta=None)
    _TRI_CACHE.clear()
    try:
        from . import rain
        d = rain._shelter_dir()
        for f in os.listdir(d):
            if f.startswith("raindrops_"):
                os.remove(os.path.join(d, f))
    except OSError:
        pass


def after_open():
    remove()
    _forget()
    F.update(sig=None, meta=None, dirty=True, geo=None)
