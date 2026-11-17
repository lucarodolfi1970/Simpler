"""Neve, passo 2: the snow mantle - a layer of snow with a real thickness on what faces up.

The snow of the materials (rain.py, step 1) is only white paint. The mantle is a separate object made here: one sheet
over the top surface of the scene seen from above (where the snow falls), lifted by the thickness of the snow. The
models stay as they are; the mantle is internal (not in the tree, not saved with the project: made again when the
project is opened), drawn by the path tracing as an object and by the real-time view from a file (GET rain/mantle.bin).

How it is made (numpy, no render), on a grid over the scene (cells of MIN_CELL m or more, at most so many cells with (limits)
snow - a bigger scene gets bigger cells):
  top        the highest point of the geometry in every cell (points spread over the triangles, as the shelter of
             the rain), without the distributions (grass, trees: white paint only), without the cut-out parts of a
             material (leaves) and without the objects «Senza mantello»; where nothing is, the ground (Suolo)
  amount     the same snow as the materials, from the top surface: S = smoothstep(ts - es, ts + es, ns) *
             smoothstep(wlo, wlo + 0.3, nz) * (1 - cover) * keep * min(50 * amount, 1)   (rain.py, top of the file)
             nz from the slope of the top surface, cover from the shelter map (under a roof, a tree: none),
             keep 0 on «Sempre asciutto»
  thickness  t = depth * S, rounded at the edges where the surface drops (a roof, a car, a ledge: a quarter of a
             circle of radius ~ depth), and down to nothing at the border of the grid (the ground beyond keeps the
             white of step 1); not where it rises (snow against a wall goes up to the wall)
  sheet      one vertex per cell (top + t + 2 mm), quads between neighbours on the same surface (no jump in height),
             cut along the line where the thickness ends (no steps of a cell at the edge of a patch); its border
             against a wall is pushed a little into the wall (no gap of half a cell)
Made again only when the geometry, the snow settings, the shelter or the flags change (in the engine's idle time or
before a path-traced image).
"""
import math
import os
import time

import bpy

from .core import INTERNAL_KEY, log

MANTLE_KEY = "simpler_snow_mantle"
NO_MANTLE_KEY = "simpler_nomantle"          # on an object (or a group above it): «Senza mantello»
MAT_NAME = "Simpler Neve"
SNOW_COLOR = (0.88, 0.90, 0.93)
TRODDEN = (0.70, 0.73, 0.78)                # trodden snow (sculpted, compaction 1); the real-time view: the same
TRODDEN_MIX = 0.7
TRODDEN_ROUGH = 0.35
COMPACT = "simpler_compact"
THIN = "simpler_thin"                       # 1 where the mantle thins out (its edges): old snow is dirtier there
MIN_CELL = 0.06
NEAR_CELL = 0.025                           # following the camera: cells this small where it is close
# «Dettaglio del mantello» (Neve > Avanzate, 0..1, 0.5 by default): the size of the grid and the cells with snow at
# most (the sheet: as many vertices). At 1 the limits stop at what a scene can still carry: a grid of 3000 (about
# 1.5 GB of memory while it is made) and 4 million vertices (the real-time view slows down beyond that)
GRID_MIN, GRID_TOP = 800, 3000
SNOW_MIN, SNOW_TOP = 150000, 4000000
HEAVY = 1500000                             # vertices: above this the panel warns


def limits(detail):
    d = max(0.0, min(1.0, float(detail)))
    return int(GRID_MIN * (GRID_TOP / GRID_MIN) ** d), int(SNOW_MIN * (SNOW_TOP / SNOW_MIN) ** d)
LIFT = 0.002
EPS = 0.003                                 # thinner than this: no snow
KERB_MIN = 0.05                             # a step from this high ...
KERB_MAX = 0.30                             # ... to this: a kerb, the snow goes over it
GROUND_MARGIN = 8.0                         # metres of ground around the scene that get the mantle (fading out)

M = {"sig": None, "meta": None, "rev": 0, "dirty": True, "changes": -1, "cam": None}
# (1.78.4, Luca: «cosa ne dici se lo fa in automatico Simpler?») while the snow brush is on (POST snow/brushing) the
# mantle is made lighter - at most BRUSH_DETAIL, the slider of the user stays as it is - and only after a pause of
# BRUSH_WAIT without strokes: one stroke after another, one computation (about 20 s at full detail on a big street,
# each stroke). The brush off: made again once at the detail chosen. A final image is always at the detail chosen.
BRUSH = {"on": False, "last": 0.0, "full": False}
BRUSH_DETAIL = 0.4
BRUSH_WAIT = 1.5
HIDE = {"on": False}       # «Nascondi la neve»: the mantle away from the view and the images, not made again while
                           # models move; «Mostra la neve» makes it again once (not saved: shown at every opening)
_MASK = {"arr": None}
_LAST = {"cell": 0.0, "secs": 0.0, "shells": 0, "shell_verts": 0}


# ---------------------------------------------------------------- what to cover

def _no_mantle(ob):
    o = ob
    while o is not None:
        if o.get(NO_MANTLE_KEY):
            return True
        o = o.parent
    return _water_surface(ob)


def _water_surface(ob):
    """(16/11, Luca: «qualunque cosa faccia sull'acqua congelata resta sempre tutta bianca») an object made only of water (a
    material «Acqua»: a lake, a river, a plane of water on the ground): no mantle on it - snow does not lie on water, and on
    frozen water the ice shows its own dusting of snow (ice.py). Before, the mantle was laid over it like over any ground:
    a white slab over the whole lake, and the sliders of the ice changed nothing that could be seen. It shelters what is
    under it, as «Senza mantello» (_covers)."""
    if ob is None or ob.type != "MESH" or not ob.material_slots:
        return False
    from . import water
    mats = [sl.material for sl in ob.material_slots]
    return all(m is not None and water.is_water(m) for m in mats)


def _dry(ob):
    """No snow here («Sempre asciutto» → Neve, on it or on a group above it)."""
    from .rain import snow_dry
    while ob is not None:
        if snow_dry(ob):
            return True
        ob = ob.parent
    return False


def _ground():
    from .ambience import GROUND_KEY
    for ob in bpy.context.scene.objects:
        if ob.get(GROUND_KEY) and ob.type == "MESH" and not ob.hide_render and not ob.get("simpler_trashed"):
            return ob
    return None


def _cutout(mat):
    """A material with holes (leaves, fences): its triangles hold no mantle. And water (16/11): a river or a lake
    painted on the ground as a material of the ground (Luca: «On: Ground») - no mantle on its faces either."""
    from . import rain
    if mat is None or not mat.use_nodes or mat.node_tree is None:
        return False
    if _is_water_mat(mat):
        return True
    try:
        out = rain._source_output(mat.node_tree)
        lk = rain._linked(out.inputs["Surface"]) if out is not None else None
        p = rain._path(lk.from_node) if lk is not None else None
        a = rain._inp(p, "Alpha") if p is not None else None
        return a is not None and (rain._linked(a) is not None or float(a.default_value) < 0.99)
    except Exception:
        return False


def _objects():
    from . import rain
    return [ob for ob in rain._scene_meshes(shelter=False) if not _no_mantle(ob) and not ob.get(MANTLE_KEY)]


def settings():
    """(amount, walls, soft, offX, offY, depth, outdoor, paintSoft, painted map rev) while it snows with a thickness,
    else None."""
    from . import ambience, rain
    s = ambience.state()
    r = rain.settings(s)
    if r is None or not r["snowing"]:
        return None
    depth = float(((s or {}).get("snow") or {}).get("depth", 0.0))
    if depth <= 0.001:
        return None
    # (the last two: the softness of the painted snow and the version of its map)
    detail = r["sdetail"]
    if BRUSH["on"] and not BRUSH["full"]:
        detail = min(detail, BRUSH_DETAIL)          # (painting: a lighter mantle, see BRUSH)
    return (r["snow"], r["walls"], r["ssoft"], r["soffX"], r["soffY"], depth, r["outdoor"], r["spaintSoft"],
            (rain._paint_frame("snow") or {}).get("rev"), detail)


def set_brushing(d):
    """POST snow/brushing {on}: the snow brush is on (the mantle lighter, after a pause) or off (once at the detail
    chosen)."""
    on = bool((d or {}).get("on"))
    if on != BRUSH["on"]:
        BRUSH["on"] = on
        BRUSH["last"] = time.time()
        if not on:
            M["dirty"] = True       # (back to the detail chosen; on: nothing is made until the first stroke)
        log(f"SIMPLER_SNOW brush {'on: lighter mantle while painting' if on else 'off: mantle at the detail chosen'}")
    return {"on": BRUSH["on"]}


def stroked():
    """A stroke of the snow brush: the mantle waits for a pause (BRUSH_WAIT)."""
    BRUSH["last"] = time.time()


def _signature(st):
    from . import rain
    from .core import ID_KEY
    g = _ground()
    flags = tuple(sorted((str(ob.get(ID_KEY)), str(ob.get(DETAIL_KEY))) for ob in bpy.context.scene.objects
                         if ob.get(NO_MANTLE_KEY) or rain.snow_dry(ob) or ob.get(DETAIL_KEY) or _water_surface(ob)))
    sh = rain.SH["meta"]["rev"] if (st[6] and rain.SH["meta"]) else -1
    used = {m for ob in _objects() for m in ob.data.materials if m is not None}
    mats = tuple(sorted((m.name, _cutout(m)) for m in used))
    gz = round(g.matrix_world.translation.z, 4) if g is not None else None
    return hash((rain._geometry_sig(shelter=False), tuple(round(x, 5) if isinstance(x, float) else x for x in st), sh, flags, gz, mats))


def touch():
    """The snow settings or the flags changed: looked at again (cheap when nothing really changed)."""
    M["dirty"] = True


def due(wait=True):
    """Should the mantle be made again? wait: a camera that moved waits to stay still (the idle time); a path-traced
    image does not wait."""
    from . import rain
    if HIDE["on"]:
        return False
    if BRUSH["on"] and not BRUSH["full"] and time.time() - BRUSH["last"] < BRUSH_WAIT:
        return False            # (painting: the mantle waits for a pause in the strokes)
    if M["dirty"] or M["changes"] != rain._STATE["changes"]:
        return True
    # (as the camera sees it: made again when the camera has moved enough - the engine's idle time comes a moment
    # after it stops)
    if M["meta"] is not None or M.get("cam") is not None:
        from . import camview
        want = camview.on("snow")
        if want != (M.get("cam") is not None):
            return True
        if want:
            now = camview.camera()
            if camview.moved(M["cam"], now):
                # (only once the camera has stayed still a little: not between two drags of the view)
                key = repr((now["pos"], now["target"], now["lens"], now["aspect"]))
                if not wait:
                    return True
                if key != M.get("still"):
                    M.update(still=key, still_t=time.time())
                    return False
                return time.time() - M.get("still_t", 0.0) > CAM_STILL
    return False


CAM_STILL = 1.0                             # seconds the camera stays still before the mantle follows it


def _show_objects(on):
    for ob in bpy.context.scene.objects:
        if ob.get(MANTLE_KEY) or ob.get(PART_KEY):
            ob.hide_render = ob.hide_viewport = not on


def set_hidden(d):
    """POST rain/snowhide {hidden}: «Nascondi la neve» / «Mostra la neve». Hidden: the mantle (and the mantles of the
    distributions) out of the view and of the path tracing, nothing made again while it stays hidden; shown: made
    again once, for what changed meanwhile (in the engine's idle time, as after any change)."""
    from . import rain, render
    on = bool(d.get("hidden"))
    if on == HIDE["on"]:
        return {"hidden": on}
    HIDE["on"] = on
    _show_objects(not on)
    from . import snowfall
    snowfall.show(not on)
    if not on:
        snowfall.touch()
    if not on:
        M["dirty"] = True
    render.invalidate()
    rain.refresh_info()
    return {"hidden": on}


# ---------------------------------------------------------------- numpy helpers

def _np():
    import numpy as np
    return np


def _smooth(e0, e1, x):
    np = _np()
    t = np.clip((x - e0) / np.maximum(e1 - e0, 1e-9), 0.0, 1.0)
    return t * t * (3 - 2 * t)


def _shift(a, dy, dx, fill):
    """a moved by (dy, dx) cells: out[y, x] = a[y + dy, x + dx] (fill outside)."""
    np = _np()
    out = np.full_like(a, fill)
    h, w = a.shape
    ys, yd = (slice(dy, h), slice(0, h - dy)) if dy >= 0 else (slice(0, h + dy), slice(-dy, h))
    xs, xd = (slice(dx, w), slice(0, w - dx)) if dx >= 0 else (slice(0, w + dx), slice(-dx, w))
    out[yd, xd] = a[ys, xs]
    return out


def _mask():
    """The tiling map of the puddles (rain.mask_path) as Cycles reads it: rows from the bottom, 0..1."""
    np = _np()
    if _MASK["arr"] is not None:
        return _MASK["arr"]
    from . import rain
    im = rain._mask_image()
    w, h = im.size
    px = np.empty(w * h * 4, dtype=np.float32)
    im.pixels.foreach_get(px)
    _MASK["arr"] = px.reshape(h, w, 4)[..., 0].copy()
    return _MASK["arr"]


def _sample_mask(u, v):
    """Bilinear, repeating (as the Image Texture node, interpolation Linear, extension Repeat)."""
    np = _np()
    a = _mask()
    h, w = a.shape
    x = u * w - 0.5
    y = v * h - 0.5
    x0 = np.floor(x).astype(np.int64)
    y0 = np.floor(y).astype(np.int64)
    fx, fy = (x - x0).astype(np.float32), (y - y0).astype(np.float32)
    x0 %= w; y0 %= h
    x1, y1 = (x0 + 1) % w, (y0 + 1) % h
    return (a[y0, x0] * (1 - fx) + a[y0, x1] * fx) * (1 - fy) + (a[y1, x0] * (1 - fx) + a[y1, x1] * fx) * fy


_TRIS = {"sig": None, "obs": {}}


def _world_tris(ob, cut):
    """The triangles of a mesh in the world, without those of cut-out materials (leaves), kept while the geometry
    stays the same: (corners (n, 3, 3), xy boxes (n, 4): xmin xmax ymin ymax, vertices (m, 3))."""
    np = _np()
    from . import rain
    bad = tuple(i for i, sl in enumerate(ob.material_slots) if sl.material is not None and cut.get(sl.material.name))
    key = (ob.name, bad)
    got = _TRIS["obs"].get(key)
    if got is not None:
        return got
    dg = bpy.context.evaluated_depsgraph_get()
    me = ob.evaluated_get(dg).data
    nv, nt = len(me.vertices), len(me.loop_triangles)
    if not nv or not nt:
        out = (np.zeros((0, 3, 3), np.float32), np.zeros((0, 4), np.float32), np.zeros((0, 3), np.float32))
    else:
        co = np.empty(nv * 3, dtype=np.float32)
        me.vertices.foreach_get("co", co)
        Mw = np.array(ob.matrix_world, dtype=np.float32)
        V = co.reshape(-1, 3) @ Mw[:3, :3].T + Mw[:3, 3]
        tri = np.empty(nt * 3, dtype=np.int32)
        me.loop_triangles.foreach_get("vertices", tri)
        T = tri.reshape(-1, 3)
        if bad:
            mi = np.empty(nt, dtype=np.int32)
            me.loop_triangles.foreach_get("material_index", mi)
            T = T[~np.isin(mi, bad)]
        P = V[T]
        box = np.stack([P[:, :, 0].min(1), P[:, :, 0].max(1), P[:, :, 1].min(1), P[:, :, 1].max(1)], axis=1)
        out = (P.astype(np.float32), box.astype(np.float32), V[np.unique(T)].astype(np.float32))
    _TRIS["obs"][key] = out
    return out


def _tris_fresh():
    """At every mantle made: the triangles kept only while the geometry has not changed."""
    from . import rain
    sig = rain._geometry_sig(shelter=False)
    if _TRIS["sig"] != sig:
        _TRIS.update(sig=sig, obs={})


RASTER_CHUNK = 4000000                  # (cells x triangles looked at in one go)


def _raster(P, box, x0, y0, nx, ny, cell, out):
    """The height of the triangles at the centre of every cell they cover (the highest), into out (ny * nx); out a
    function: called with (cells, heights) of every triangle over every cell."""
    np = _np()
    j0 = np.ceil((box[:, 0] - x0) / cell - 0.5).astype(np.int64)
    j1 = np.floor((box[:, 1] - x0) / cell - 0.5).astype(np.int64)
    i0 = np.ceil((box[:, 2] - y0) / cell - 0.5).astype(np.int64)
    i1 = np.floor((box[:, 3] - y0) / cell - 0.5).astype(np.int64)
    j0, i0 = np.maximum(j0, 0), np.maximum(i0, 0)
    j1, i1 = np.minimum(j1, nx - 1), np.minimum(i1, ny - 1)
    w, h = j1 - j0 + 1, i1 - i0 + 1
    keep = (w > 0) & (h > 0)
    if not keep.any():
        return
    P, j0, i0, w, h = P[keep], j0[keep], i0[keep], w[keep], h[keep]
    # (a triangle over very many cells - a floor, a road: in strips of rows)
    big = w * h > RASTER_CHUNK // 4
    if big.any():
        for k in np.nonzero(big)[0]:
            rows = max(1, (RASTER_CHUNK // 4) // int(w[k]))
            for r0 in range(0, int(h[k]), rows):
                hh = min(rows, int(h[k]) - r0)
                _raster_run(P[k:k + 1], j0[k:k + 1], i0[k:k + 1] + r0, w[k:k + 1], np.array([hh]), x0, y0, nx, cell, out)
        small = ~big
        P, j0, i0, w, h = P[small], j0[small], i0[small], w[small], h[small]
    cnt = w * h
    cum = np.cumsum(cnt)
    s = 0
    while s < len(cnt):
        base = cum[s - 1] if s else 0
        e = int(np.searchsorted(cum, base + RASTER_CHUNK, side="right"))
        e = max(e, s + 1)
        _raster_run(P[s:e], j0[s:e], i0[s:e], w[s:e], h[s:e], x0, y0, nx, cell, out)
        s = e


def _raster_run(P, j0, i0, w, h, x0, y0, nx, cell, out):
    np = _np()
    cnt = w * h
    tot = int(cnt.sum())
    if not tot:
        return
    t = np.repeat(np.arange(len(cnt), dtype=np.int32), cnt)
    loc = np.arange(tot, dtype=np.int64) - np.repeat(np.cumsum(cnt) - cnt, cnt)
    wt = w[t]
    ci = i0[t] + loc // wt
    cj = j0[t] + loc % wt
    # (float32, measured from the corner of the grid: precise to a fraction of a millimetre)
    cx = ((cj + 0.5) * cell).astype(np.float32)
    cy = ((ci + 0.5) * cell).astype(np.float32)
    p = P[t]
    xa, ya, xb, yb, xc, yc = (p[:, 0, 0] - np.float32(x0), p[:, 0, 1] - np.float32(y0), p[:, 1, 0] - np.float32(x0),
                              p[:, 1, 1] - np.float32(y0), p[:, 2, 0] - np.float32(x0), p[:, 2, 1] - np.float32(y0))
    d = (yb - yc) * (xa - xc) + (xc - xb) * (ya - yc)
    ok = np.abs(d) > 1e-10
    d = np.where(ok, d, np.float32(1.0))
    a = ((yb - yc) * (cx - xc) + (xc - xb) * (cy - yc)) / d
    b = ((yc - ya) * (cx - xc) + (xa - xc) * (cy - yc)) / d
    c = 1.0 - a - b
    e = -1e-6
    ok &= (a >= e) & (b >= e) & (c >= e)
    if not ok.any():
        return
    z = a * p[:, 0, 2] + b * p[:, 1, 2] + c * p[:, 2, 2]
    if callable(out):
        out((ci * nx + cj)[ok], z[ok])          # (every height at every cell: ice.py)
    else:
        np.maximum.at(out, (ci * nx + cj)[ok], z[ok].astype(out.dtype))


def _edge_points(P, spacing):
    """Points along the sides of the triangles (their corners apart), about one per spacing."""
    np = _np()
    A = P
    B = np.roll(P, -1, axis=1)
    A, B = A.reshape(-1, 3), B.reshape(-1, 3)
    L = np.linalg.norm((B - A)[:, :2], axis=1)
    k = np.floor(L / spacing).astype(np.int64)
    sel = k > 0
    if not sel.any():
        return np.zeros((0, 3), np.float32)
    A, B, k = A[sel], B[sel], k[sel]
    t = np.repeat(np.arange(len(k)), k)
    loc = np.arange(int(k.sum())) - np.repeat(np.cumsum(k) - k, k)
    f = ((loc + 1) / (k[t] + 1))[:, None]
    return (A[t] + (B[t] - A[t]) * f).astype(np.float32)


def _snow_ns(X, Y, sox, soy):
    """The noise of the snow (rain.py SNOW_NS, v25): the same as the materials and the view."""
    from . import rain
    K = rain.SNOW_NS
    mid = _sample_mask(X * K["s_mid"] + 0.5 * sox + 0.71, Y * K["s_mid"] + 0.5 * soy + 0.13)
    a, b, c, d = K["r2"]
    big = _sample_mask((a * X + b * Y) * K["s_big"] + K["o_big"][0], (c * X + d * Y) * K["s_big"] + K["o_big"][1])
    a, b, c, d = K["r1"]
    fine = _sample_mask((a * X + b * Y) * 0.125 + sox + 0.37 + K["warp"] * (mid - 0.5),
                        (c * X + d * Y) * 0.125 + soy + 0.61 + K["warp"] * (big - 0.5))
    w0, w1, w2 = K["w"]
    return 0.5 + K["spread"] * (w0 * fine + w1 * mid + w2 * big - 0.5)


def _snow_at(X, Y, Z, nz, st, local=False):
    """The snow of the materials (rain.py, top of the file) at these points: S and the slope factor. The same for the
    grid of the ground and for the points on the models."""
    np = _np()
    from . import rain
    amount, walls, ssoft, sox, soy, depth, outdoor = st[:7]
    ns = _snow_ns(X, Y, sox, soy)
    ts, es, wlo = 1.0 - 1.15 * amount, 0.02 + 0.3 * ssoft, 0.75 - 0.95 * walls
    nzs = nz + rain.NZJ_AMP * (_sample_mask(X * rain.NZJ_SCALE + rain.NZJ_OFF[0], Y * rain.NZJ_SCALE + rain.NZJ_OFF[1]) - 0.5)
    face = _smooth(wlo, wlo + 0.3, nzs)          # (1.76.12: the slope shaken as in the materials, rain.py v23)
    S = _smooth(ts - es, ts + es, ns) * face * min(amount * 50.0, 1.0)
    meta = rain.SH["meta"] if (outdoor and not local) else None     # (local: a model of a distribution, in its own space)
    if meta is not None:
        try:
            sh = _shelter_array(meta)
            sn = int(meta["n"])
            si = np.clip(((Y - meta["y0"]) / meta["cell"]).astype(np.int64), 0, sn - 1)
            sj = np.clip(((X - meta["x0"]) / meta["cell"]).astype(np.int64), 0, sn - 1)
            inside = (X >= meta["x0"]) & (X < meta["x0"] + meta["size"]) & (Y >= meta["y0"]) & (Y < meta["y0"] + meta["size"])
            v = sh[si, sj]
            hs = np.where(inside & (v > 1e-4), meta["zmin"] + v * meta["zr"], -1e6)
            S = S * (1.0 - _smooth(meta["lo"], meta["lo"] + 0.3, hs - Z))
        except (OSError, ValueError, KeyError):
            pass
    # the snow painted by hand (rain.paint_stroke, layer snow), as in the materials
    pa, pf = (None, None) if local else (rain._paint_array("snow"), rain._paint_frame("snow"))
    if pa is not None and pf is not None:
        pn = int(pf["n"])
        pj = ((X - pf["x0"]) / pf["size"] * pn).astype(np.int64)
        pi = ((Y - pf["y0"]) / pf["size"] * pn).astype(np.int64)
        pin = (pj >= 0) & (pj < pn) & (pi >= 0) & (pi < pn)
        q = pa[np.clip(pi, 0, pn - 1), np.clip(pj, 0, pn - 1)] * pin[..., None]
        match = 1.0 - _smooth(0.4, 0.8, np.abs(Z - (pf.get("z0", 0.0) + q[..., 2] * pf.get("zr", 1.0))))
        eq = 0.02 + 0.43 * st[7]
        S = np.maximum(S * (1.0 - q[..., 1] * match), _smooth(0.5 - eq, 0.5 + eq, q[..., 0] * match) * face)
    # the sea (Paesaggio > Oceano): no snow on what is under it or where its waves run - it melts in the water;
    # without this the mantle went on over the shore into the sea as a slab with a dark edge
    if not local:
        from . import ocean
        line = ocean.snow_line()
        if line is not None:
            S = S * _smooth(line[0], line[1], Z)
    return S, face


_SH_ARR = {"file": None, "arr": None}


def _shelter_array(meta):
    np = _np()
    from . import rain
    if _SH_ARR["file"] != meta["file"]:
        sn = int(meta["n"])
        a = np.fromfile(os.path.join(rain._shelter_dir(), meta["file"] + ".bin"), dtype=np.float16)
        _SH_ARR.update(file=meta["file"], arr=a.reshape(sn, sn).astype(np.float32))
    return _SH_ARR["arr"]


# ---------------------------------------------------------------- the mantle on the shape of the models
# A model (everything under one root of the tree) up to SHELL_MAX metres wide gets a mantle made on its own shape:
# points spread over its faces that look up (their true normal; a face turned the wrong way counts when nothing is
# above it), each with the snow of the materials; a ball of snow on every point (radius = half the thickness, its
# centre lifted so it rests on the surface), all the balls made into one smooth surface by Blender (Points to
# Volume and Volume to Mesh, the voxels as fine as the detail). The edges come out rounded by themselves and the snow
# stops where the shape gets too steep: no sheet hanging from the sides. Bigger models (buildings, a street) and
# those set to «Basso» are in the grid from above, cheaper on wide flat surfaces.

DETAIL_KEY = "simpler_snow_detail"          # on an object (or a group above it): high | low (none: auto)
SHELL_MAX = 12.0
FLAT_MAX = 0.5               # metres: a model lower than this (and flat) goes in the grid - footprints on a pavement
VOL_GROUP = "Simpler Neve volume v3"
VOL_SMOOTH = 12              # passes of smoothing of the surface (the balls left rings and bumps on a curved roof)


def _root(ob):
    while ob.parent is not None and not ob.parent.get(INTERNAL_KEY):
        ob = ob.parent
    return ob


def _detail_of(ob):
    while ob is not None:
        v = ob.get(DETAIL_KEY)
        if v in ("high", "low"):
            return v
        ob = ob.parent
    return "auto"


def _vol_group():
    ng = bpy.data.node_groups.get(VOL_GROUP)
    if ng is not None:
        return ng
    ng = bpy.data.node_groups.new(VOL_GROUP, "GeometryNodeTree")
    ng.interface.new_socket("Geometry", in_out="INPUT", socket_type="NodeSocketGeometry")
    ng.interface.new_socket("Geometry", in_out="OUTPUT", socket_type="NodeSocketGeometry")
    N, L = ng.nodes, ng.links
    gi, go = N.new("NodeGroupInput"), N.new("NodeGroupOutput")
    m2p = N.new("GeometryNodeMeshToPoints")
    na = N.new("GeometryNodeInputNamedAttribute")
    na.data_type = "FLOAT"
    na.inputs["Name"].default_value = "radius"
    p2v = N.new("GeometryNodePointsToVolume")
    p2v.name = "volume"
    p2v.inputs["Resolution Mode"].default_value = "Size"
    v2m = N.new("GeometryNodeVolumeToMesh")
    v2m.inputs["Resolution Mode"].default_value = "Grid"
    v2m.inputs["Adaptivity"].default_value = 0.0
    L.new(gi.outputs[0], m2p.inputs["Mesh"])
    L.new(m2p.outputs[0], p2v.inputs["Points"])
    L.new(na.outputs[0], p2v.inputs["Radius"])
    L.new(p2v.outputs[0], v2m.inputs["Volume"])
    # the surface smoothed (each point to the mean of its neighbours, a few times): a union of balls on a gently
    # curved roof had rings and steps along its height, and a pebbly skin; snow is soft
    pos = N.new("GeometryNodeInputPosition")
    blur = N.new("GeometryNodeBlurAttribute")
    blur.name = "smooth"
    blur.data_type = "FLOAT_VECTOR"
    blur.inputs["Iterations"].default_value = VOL_SMOOTH
    blur.inputs["Weight"].default_value = 1.0
    setp = N.new("GeometryNodeSetPosition")
    L.new(pos.outputs[0], blur.inputs[0])
    L.new(v2m.outputs[0], setp.inputs["Geometry"])
    L.new(blur.outputs[0], setp.inputs["Position"])
    L.new(setp.outputs[0], go.inputs[0])
    return ng


def _model_tris(meshes, cut, up_min=None, top=None):
    """World triangles of the meshes of a model (without the triangles of cut-out materials).
    (1.75.6) up_min: only the triangles that can hold snow (facing up at least this much, either side - the same
    test _shell_points made later, now before the arrays are built). top (cell, tol, every mesh of the model): only
    those near the top of the model where they are - its roof and glass shelter its seats, also when the model is
    not in the shelter map («Non fa riparo»). A car of 24 M triangles: 11.7 M before, the memory ran out."""
    np = _np()
    dg = bpy.context.evaluated_depsgraph_get()
    out = []
    Htop = None
    if top is not None:
        cell, tol, every = top
        allv = []
        for ob in every:                 # (all the model: its glass «Niente neve» or «Senza mantello» still shelters)
            me = ob.evaluated_get(dg).data
            if not len(me.vertices):
                continue
            co = np.empty(len(me.vertices) * 3, dtype=np.float32)
            me.vertices.foreach_get("co", co)
            Mw = np.array(ob.matrix_world, dtype=np.float32)
            allv.append(co.reshape(-1, 3) @ Mw[:3, :3].T + Mw[:3, 3])
        if allv:
            A = np.concatenate(allv)
            x0, y0 = float(A[:, 0].min()), float(A[:, 1].min())
            nx = int((float(A[:, 0].max()) - x0) / cell) + 1
            ny = int((float(A[:, 1].max()) - y0) / cell) + 1
            if nx * ny <= 16_000_000:
                Htop = np.full(nx * ny, -np.inf, dtype=np.float32)
                ix = ((A[:, 0] - x0) / cell).astype(np.int64); iy = ((A[:, 1] - y0) / cell).astype(np.int64)
                np.maximum.at(Htop, iy * nx + ix, A[:, 2])
            del allv, A
    for ob in meshes:
        if _dry(ob):
            continue
        me = ob.evaluated_get(dg).data
        nv, nt = len(me.vertices), len(me.loop_triangles)
        if not nv or not nt:
            continue
        co = np.empty(nv * 3, dtype=np.float32)
        me.vertices.foreach_get("co", co)
        Mw = np.array(ob.matrix_world, dtype=np.float32)
        V = co.reshape(-1, 3) @ Mw[:3, :3].T + Mw[:3, 3]
        tri = np.empty(nt * 3, dtype=np.int32)
        me.loop_triangles.foreach_get("vertices", tri)
        T = tri.reshape(-1, 3)
        # the shading normals of the corners (smooth surfaces stay smooth: with the normal of each flat face the
        # snow changed by steps from one ring of faces to the next - terraces on a curved roof)
        lp = np.empty(nt * 3, dtype=np.int32)
        me.loop_triangles.foreach_get("loops", lp)
        cn = np.empty(len(me.loops) * 3, dtype=np.float32)
        try:
            me.corner_normals.foreach_get("vector", cn)
        except AttributeError:
            cn[:] = 0.0
        Nm = np.linalg.inv(Mw[:3, :3]).T
        CN = cn.reshape(-1, 3) @ Nm.T
        CN /= np.maximum(np.linalg.norm(CN, axis=1), 1e-12)[:, None]
        LT = lp.reshape(-1, 3)
        bad = [i for i, sl in enumerate(ob.material_slots) if sl.material is not None and cut.get(sl.material.name)]
        if bad:
            mi = np.empty(nt, dtype=np.int32)
            me.loop_triangles.foreach_get("material_index", mi)
            keep = ~np.isin(mi, bad)
            T, LT = T[keep], LT[keep]
        if len(T) and up_min is not None:
            p0, p1, p2 = V[T[:, 0]], V[T[:, 1]], V[T[:, 2]]
            cr = np.cross(p1 - p0, p2 - p0)
            nz = np.abs(cr[:, 2]) / np.maximum(np.linalg.norm(cr, axis=1), 1e-12)
            cz = np.abs(CN[LT][:, :, 2]).max(1)
            k = np.maximum(nz, cz) > up_min
            T, LT = T[k], LT[k]
        if len(T) and Htop is not None:
            P = V[T]
            c = P.mean(1)
            ix = np.clip(((c[:, 0] - x0) / cell).astype(np.int64), 0, nx - 1)
            iy = np.clip(((c[:, 1] - y0) / cell).astype(np.int64), 0, ny - 1)
            k = P[:, :, 2].max(1) >= Htop[iy * nx + ix] - tol
            T, LT = T[k], LT[k]
        if len(T):
            out.append(np.concatenate([V[T], CN[LT]], axis=1))     # (n, 6: 3 corners, 3 corner normals, xyz)
    return np.concatenate(out) if out else np.zeros((0, 6, 3), np.float32)


def _shell_points(tris, h, st, local=False, rmin=0.0):
    """Centres and radii of the balls of snow over the faces of a model (see above). rmin: no ball smaller than this
    where there is snow (a mantle coarser than its thickness: a little thicker, rather than none)."""
    np = _np()
    depth, outdoor = st[5], st[6]
    p0, p1, p2 = tris[:, 0], tris[:, 1], tris[:, 2]
    n0, n1, n2 = tris[:, 3], tris[:, 4], tris[:, 5]
    cr = np.cross(p1 - p0, p2 - p0)
    area = 0.5 * np.linalg.norm(cr, axis=1)
    nrm = cr / np.maximum(2.0 * area, 1e-12)[:, None]
    # (with the shelter: a face turned the wrong way counts by its side facing up - what is under something gets
    # nothing anyway; without it only the side the model says)
    flip = ((nrm[:, 2] < 0) & outdoor)[:, None]
    up = np.where(flip, -nrm, nrm)
    sgn = np.where(flip, -1.0, 1.0)
    from . import rain
    wlo = 0.75 - 0.95 * st[1] - 0.5 * rain.NZJ_AMP          # (1.76.12: the slope shaken lets a little steeper hold)
    keep = (np.maximum(up[:, 2], (sgn * np.stack([n0[:, 2], n1[:, 2], n2[:, 2]], 1)).max(1)) > wlo - 0.05) & (area > 0)
    p0, p1, p2, area, sgn = p0[keep], p1[keep], p2[keep], area[keep], sgn[keep]
    n0, n1, n2 = n0[keep] * sgn, n1[keep] * sgn, n2[keep] * sgn
    if not len(area):
        return None, None
    rng = np.random.default_rng(len(area))
    cnt = np.floor(area / (0.7 * h) ** 2 + rng.random(len(area))).astype(np.int64)
    idx = np.repeat(np.arange(len(area)), cnt)
    r1 = np.sqrt(rng.random(len(idx)))[:, None]
    r2 = rng.random(len(idx))[:, None]
    a, b, c = 1 - r1, r1 * (1 - r2), r1 * r2
    P = p0[idx] * a + p1[idx] * b + p2[idx] * c
    U = n0[idx] * a + n1[idx] * b + n2[idx] * c       # (the smooth normal at the point)
    P = np.concatenate([P, p0, p1, p2])            # (the corners too: small faces get their snow)
    U = np.concatenate([U, n0, n1, n2])
    U /= np.maximum(np.linalg.norm(U, axis=1), 1e-12)[:, None]
    S, _face = _snow_at(P[:, 0], P[:, 1], P[:, 2], U[:, 2], st, local)
    if not local:
        cv = _cover_at(P[:, 0], P[:, 1])
        if cv is not None:
            S = np.where(cv > P[:, 2] + 0.02, 0.0, S)
    r = 0.5 * depth * S
    if rmin > 0:
        r = np.where(S > 0.25, np.maximum(r, rmin), r)
    ok = r >= 0.5 * h
    if not ok.any():
        return None, None
    C = P[ok] + U[ok] * (r[ok] - 0.3 * h)[:, None]
    return C.astype(np.float32), r[ok].astype(np.float32)


def _volume_mesh(C, R, h):
    """One smooth surface around the balls (Blender: Points to Volume, Volume to Mesh)."""
    np = _np()
    me = bpy.data.meshes.new("Simpler Neve punti")
    me.vertices.add(len(C))
    me.vertices.foreach_set("co", C.ravel())
    a = me.attributes.new("radius", "FLOAT", "POINT")
    a.data.foreach_set("value", R)
    ob = bpy.data.objects.new("Simpler Neve punti", me)
    ob[INTERNAL_KEY] = 1
    bpy.context.scene.collection.objects.link(ob)
    try:
        mod = ob.modifiers.new("Neve", "NODES")
        ng = _vol_group()
        ng.nodes["volume"].inputs["Voxel Size"].default_value = float(h)      # (one call at a time: no input needed)
        mod.node_group = ng
        dg = bpy.context.evaluated_depsgraph_get()
        out = bpy.data.meshes.new_from_object(ob.evaluated_get(dg))
        nv = len(out.vertices)
        pos = np.empty(nv * 3, dtype=np.float32)
        out.vertices.foreach_get("co", pos)
        npoly = len(out.polygons)
        sizes = np.empty(npoly, dtype=np.int32)
        out.polygons.foreach_get("loop_total", sizes)
        loops = np.empty(len(out.loops), dtype=np.int32)
        out.loops.foreach_get("vertex_index", loops)
        bpy.data.meshes.remove(out)
        return pos.reshape(-1, 3), loops, sizes
    finally:
        bpy.data.objects.remove(ob, do_unlink=True)
        bpy.data.meshes.remove(me)


def _plan(obs, st, max_snow, view=None):
    """Which models get the mantle on their shape and how fine (h, metres): {root: (meshes, h)}; the others go in
    the grid. Over the limit the farthest models get coarser, then go to the grid. view (camview): only the models in
    the frame, none finer than about a pixel and a half where it stands (the others in the grid: out of the frame it
    is coarse)."""
    np = _np()
    depth, detail = st[5], st[9]
    roots = {}
    for ob in obs:
        roots.setdefault(_root(ob), []).append(ob)
    fr = None
    if view is not None:
        from . import camview
        fr = camview.Frustum(view, 0.1)
        cpos = fr.pos
    else:
        cam = bpy.context.scene.camera
        cpos = np.array(cam.matrix_world.translation) if cam is not None else None
    mult = 2.0 ** (1.0 - 2.0 * detail)              # (the «Dettaglio del mantello» of the panel: 50% = 1)
    cand = []
    for root, meshes in roots.items():
        mode = _detail_of(meshes[0]) if len(meshes) == 1 else _detail_of(root)
        if mode == "low":
            continue
        lo = np.full(3, np.inf); hi = np.full(3, -np.inf)
        for ob in meshes:
            c = np.array([ob.matrix_world @ __import__("mathutils").Vector(b) for b in ob.bound_box])
            lo = np.minimum(lo, c.min(0)); hi = np.maximum(hi, c.max(0))
        diag = float(np.linalg.norm((hi - lo)[:2]))
        if mode == "auto" and diag > SHELL_MAX:
            continue
        if mode == "auto" and (hi - lo)[2] < max(FLAT_MAX, 0.06 * diag):
            continue        # (flat and low - a pavement, a step, a kerb: in the grid, where it can be sculpted)
        h = min(max(diag / 120.0, 0.008) * mult * (0.5 if mode == "high" else 1.0), depth / 2.5)
        h = max(h, 0.005)
        dist = float(np.linalg.norm((lo + hi) / 2 - cpos)) if cpos is not None else 0.0
        if fr is not None:
            rad = float(np.linalg.norm(hi - lo)) / 2
            d_, seen = fr.look(((lo + hi) / 2)[None], rad)
            if not seen[0]:
                continue
            h = max(h, 1.5 * fr.pixel * max(float(d_[0]) - rad, 0.1))
            if h > depth / 2.0:
                continue                    # (so far that the snow is thinner than a pixel: the grid)
        top_area = float((hi - lo)[0] * (hi - lo)[1])
        cand.append((dist, root, meshes, h, top_area))
    cand.sort(key=lambda x: x[0])
    plan, used = {}, 0.0
    for dist, root, meshes, h, area in cand:
        est = 2.5 * area / (h * h)
        if used + est > max_snow:
            h = h * math.sqrt(est / max(max_snow - used, 1.0)) if used < max_snow else depth
            if h > depth / 2.0:
                continue                             # (too coarse for its thickness: in the grid)
            est = 2.5 * area / (h * h)
        used += est
        plan[root] = (meshes, h)
    _LAST["planned"] = used
    return plan


def _shells(plan, cut, st):
    """The mantles on the shape of the models: one surface per fineness (h rounded to steps of √2)."""
    np = _np()
    buckets = {}
    for root, (meshes, h) in plan.items():
        k = round(math.log(h, math.sqrt(2.0)))
        hq = math.sqrt(2.0) ** k
        every = [o for o in ([root] + list(root.children_recursive)) if o.type == "MESH" and not o.hide_render
                 and not o.get(INTERNAL_KEY)]
        tris = _model_tris(meshes, cut, up_min=0.75 - 0.95 * st[1] - 0.05,
                           top=(max(2.0 * hq, 0.02), max(3.0 * hq, 0.04), every or meshes))
        if not len(tris):
            continue
        C, R = _shell_points(tris, hq, st)
        if C is None:
            continue
        buckets.setdefault(hq, []).append((C, R))
    parts = []
    for hq, items in buckets.items():
        C = np.concatenate([c for c, _r in items])
        R = np.concatenate([r for _c, r in items])
        parts.append(_volume_mesh(C, R, hq))
    return parts


# ---------------------------------------------------------------- the mantle of the distributions
# The copies of a distribution are drawn from one model (instancing): their mantle too. Per model, VARIANTS mantles
# on its shape (each with its own patches), made once in the space of the model; every copy gets one of them (by
# its number), as an instance - 80 cars cost what 3 cost. Per copy: none when something is above it (the shelter at
# the top of the copy), none when the copy leans more than SCATTER_TILT degrees (its «up» is not the model's up).
# The distribution «Sempre asciutto», «Senza mantello» or «Basso» (Dettaglio neve): no mantle.

VARIANTS = 3
SCATTER_TILT = 10.0
PART_KEY = "simpler_snow_part"

# ---------------------------------------------------------------- copies pressed by the sculpted snow (1.79.0)
# (Luca: «sculpt neve footprint non va niente» - the steps were there, under the snow of 19,398 tufts of grass of an
# ecosystem: each tuft has its own mantle and they covered the ground) Where the snow is trodden or dug (footprints,
# tyres, digging: snowsculpt D below -1 cm or pressed), the copies of the distributions standing there are pressed
# into the snow: left out of the path tracing (Delete Geometry in their node tree, paint._press_node), of the real-time
# view (paint.points) and of the mantle of the distributions. Not destructive: an attribute of the points, made again
# from the sculpted snow - cleared, undone or without snow, the copies are all back.
PRESS = {"rev": 0}
PRESS_ATTR = "simpler_pressed"
PRESS_DEPTH = 0.01
PRESS_C = 0.4


def _press_points():
    from . import paint
    return [ob for ob in bpy.context.scene.objects if ob.get(paint.DATA_KEY) and not ob.get("simpler_trashed")
            and ob.type == "MESH"]


def _press_write(po, mask, h=""):
    me = po.data
    a = me.attributes.get(PRESS_ATTR)
    if mask is None:
        if a is not None:
            me.attributes.remove(a)
        if PRESS_ATTR in po:
            del po[PRESS_ATTR]
    else:
        if a is not None and (a.data_type != "BOOLEAN" or a.domain != "POINT"):
            me.attributes.remove(a)
            a = None
        if a is None:
            a = me.attributes.new(PRESS_ATTR, "BOOLEAN", "POINT")
        a.data.foreach_set("value", mask)
        po[PRESS_ATTR] = h
        from . import paint
        paint.press_node(po)
    me.update()


def press_update():
    """The pressed copies of every distribution from the sculpted snow. True when some changed."""
    np = _np()
    import hashlib
    from . import snowsculpt
    active = settings() is not None and snowsculpt.present()
    box = snowsculpt.extent() if active else None
    changed = False
    for po in _press_points():
        me = po.data
        n = len(me.vertices)
        old = po.get(PRESS_ATTR, "")
        mask = None
        if box is not None and n:
            co = np.empty(n * 3, dtype=np.float32)
            me.vertices.foreach_get("co", co)
            co = co.reshape(n, 3)
            pm = np.array(po.matrix_world, dtype=np.float32)
            W = co @ pm[:3, :3].T + pm[:3, 3]
            near = (W[:, 0] >= box[0]) & (W[:, 0] <= box[2]) & (W[:, 1] >= box[1]) & (W[:, 1] <= box[3])
            if near.any():
                D, C = snowsculpt.sample(W[near, 0], W[near, 1])
                hit = (D < -PRESS_DEPTH) | (C > PRESS_C)
                if hit.any():
                    mask = np.zeros(n, dtype=bool)
                    mask[np.nonzero(near)[0][hit]] = True
        h = hashlib.sha1(np.packbits(mask).tobytes()).hexdigest()[:10] if mask is not None else ""
        if h != old:
            _press_write(po, mask, h)
            changed = True
    if changed:
        PRESS["rev"] += 1
    return changed


def pressed_of(po, n):
    """The pressed copies of a points object (bool array), or None."""
    if not po.get(PRESS_ATTR):
        return None
    a = po.data.attributes.get(PRESS_ATTR)
    if a is None or len(a.data) != n:
        return None
    np = _np()
    m = np.zeros(n, dtype=bool)
    a.data.foreach_get("value", m)
    return m


def _scatter_models(st):
    """{collection name: (objects of the model, world matrices of its copies (n, 4, 4))} of the distributions."""
    np = _np()
    from . import paint, rain
    out = {}
    for po in rain._scatter_points():
        if _no_mantle(po) or _dry(po) or _detail_of(po) == "low":
            continue
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
        pr = pressed_of(po, n)
        if pr is not None:
            mi = np.where(pr, -1, mi)         # (pressed into the snow: no copy, no mantle)
        pm = np.array(po.matrix_world, dtype=np.float32)
        subs = list(coll.children)
        for k in np.unique(mi):
            if k < 0 or k >= len(subs):
                continue
            obs = [o for o in subs[k].all_objects if o.type == "MESH" and not o.hide_render and not _no_mantle(o)]
            if not obs:
                continue
            W = pm[None] @ xf[mi == k]
            prev = out.get(subs[k].name)
            out[subs[k].name] = (obs, W if prev is None else np.concatenate([prev[1], W]))
    return out


_SHELL_K = {"k": 6.0}                       # vertices of a mantle per (snow-carrying area / h²): learnt as they are made
_SHELL_CACHE = {"key": None, "items": {}}


def _scatter_shells(st, max_snow, view=None):
    """[(variant mesh (pos, faces), copies (n, 4, 4))] for the models of the distributions, within max_snow. Every model
    gets its share of the budget (a model made coarser to fit it, down to one variant, never left without when it can
    carry snow at all). view (camview): only the copies in the frame, as fine as the nearest of them needs (far away
    one variant: the patches do not show)."""
    np = _np()
    from . import rain
    depth, outdoor, detail = st[5], st[6], st[9]
    cut = {}
    out, used = [], 0
    mult = 2.0 ** (1.0 - 2.0 * detail)
    meta = rain.SH["meta"] if outdoor else None
    fr = None
    if view is not None:
        from . import camview
        fr = camview.Frustum(view, 0.15)
    ckey = (rain._geometry_sig(shelter=False), tuple(round(x, 5) if isinstance(x, float) else x for x in st),
            (meta or {}).get("file"))
    if _SHELL_CACHE["key"] != ckey or len(_SHELL_CACHE["items"]) > 40:
        _SHELL_CACHE.update(key=ckey, items={})
    todo = []
    for name, (obs, W) in _scatter_models(st).items():
        for ob in obs:
            for m in ob.data.materials:
                if m is not None and m.name not in cut:
                    cut[m.name] = _cutout(m)
        tk = ("tris", name)
        tris = _SHELL_CACHE["items"].get(tk)
        if tris is None:
            tris = _model_tris(obs, cut)
            if view is not None:
                _SHELL_CACHE["items"][tk] = tris        # (following the camera: asked again at every stop)
        if not len(tris):
            continue
        lo = tris[:, :3].reshape(-1, 3).min(0); hi = tris[:, :3].reshape(-1, 3).max(0)
        diag = float(np.linalg.norm((hi - lo)[:2]))
        # (upright copies only)
        z = W[:, :3, 2]
        sc = np.linalg.norm(z, axis=1)
        upright = z[:, 2] / np.maximum(sc, 1e-9) > math.cos(math.radians(SCATTER_TILT))
        # (nothing above the top of the copy)
        top = np.array([(lo[0] + hi[0]) / 2, (lo[1] + hi[1]) / 2, hi[2], 1.0], dtype=np.float32)
        tw = W @ top
        free = np.ones(len(W), dtype=bool)
        if meta is not None:
            sh = _shelter_array(meta)
            sn = int(meta["n"])
            si = np.clip(((tw[:, 1] - meta["y0"]) / meta["cell"]).astype(np.int64), 0, sn - 1)
            sj = np.clip(((tw[:, 0] - meta["x0"]) / meta["cell"]).astype(np.int64), 0, sn - 1)
            v = sh[si, sj]
            hs = np.where(v > 1e-4, meta["zmin"] + v * meta["zr"], -1e6)
            free = hs - tw[:, 2] < meta["lo"] + 0.15
        cv = _cover_at(tw[:, 0], tw[:, 1])
        if cv is not None:
            free &= ~(cv > tw[:, 2] + 0.02)              # (under the surface of a pool: none)
        keep = upright & free
        if not keep.any():
            continue
        W, sc = W[keep], sc[keep]
        s_med = float(np.median(sc))
        d_model = depth / max(s_med, 1e-6)                 # (the copies scale the snow with them)
        h = min(max(diag / 120.0, 0.008) * mult, d_model / 2.5)
        h = max(h, 0.005)
        hmax = d_model                                      # (coarser than this: no ball holds the snow)
        variants = VARIANTS
        near = 0.0
        if fr is not None:
            mid = np.array([(lo[0] + hi[0]) / 2, (lo[1] + hi[1]) / 2, (lo[2] + hi[2]) / 2, 1.0], dtype=np.float32)
            cw = (W @ mid)[:, :3]
            rad = 0.5 * float(np.linalg.norm(hi - lo)) * sc
            d, seen = fr.look(cw, rad)
            if not seen.any():
                continue
            W, sc, d, rad = W[seen], sc[seen], d[seen], rad[seen]
            near = float(np.maximum(d - rad, 0.1).min())
            h = max(h, 1.5 * fr.pixel * near / s_med)       # (about a pixel and a half at the nearest copy)
            if h > hmax:
                continue                                    # (thinner than a pixel there: the white of the materials)
            if float((rad * 2).max()) / max(near, 0.1) < 0.1 * fr.ty0:
                variants = 1                                # (small on the screen: one is enough)
        # the area that can carry snow (faces looking up): how many vertices a mantle of it will have
        p0, p1, p2 = tris[:, 0], tris[:, 1], tris[:, 2]
        cr = np.cross(p1 - p0, p2 - p0)
        ar = 0.5 * np.linalg.norm(cr, axis=1)
        nzv = np.abs(cr[:, 2]) / np.maximum(2.0 * ar, 1e-12)
        area = float(ar[nzv > (0.75 - 0.95 * st[1]) - 0.05].sum())
        todo.append({"name": name, "tris": tris, "W": W, "h": h, "hmax": hmax, "d_model": d_model,
                     "variants": variants, "area": max(area, 1e-6), "near": near, "copies": len(W)})
    # the nearest (or the most used) first; each its share of what is left
    todo.sort(key=lambda m: (m["near"], -m["copies"]) if fr is not None else (-m["copies"],))
    for k, m in enumerate(todo):
        share = (max_snow - used) / max(1, len(todo) - k)
        h, nv = m["h"], m["variants"]
        est = lambda hh, vv: vv * _SHELL_K["k"] * m["area"] / (hh * hh)
        if est(h, nv) > share and nv > 1:
            nv = 1
        if est(h, nv) > share:
            h = h * math.sqrt(est(h, nv) / max(share, 1.0))
        # (coarser than the snow is thick: the balls made as big as the voxels need - the snow of this model a little
        # thicker than set, never missing; at most 2.5 times as coarse)
        h = min(h, 2.5 * m["hmax"])
        hq = math.sqrt(2.0) ** math.ceil(math.log(h, math.sqrt(2.0)) - 1e-6)    # (steps of √2: kept between views)
        if hq > 2.5 * m["hmax"]:
            hq = 2.5 * m["hmax"]
        rmin = 0.55 * hq if hq > m["hmax"] else 0.0
        W = m["W"]
        pick = np.arange(len(W)) % nv
        for v in range(nv):
            sel = pick == v
            if not sel.any():
                continue
            key = (m["name"], round(hq, 6), v)
            mesh = _SHELL_CACHE["items"].get(key)
            if mesh is None:
                stv = (st[0], st[1], st[2], st[3] + 0.31 * v, st[4] + 0.57 * v, m["d_model"], False) + tuple(st[7:])
                C, R = _shell_points(m["tris"], hq, stv, local=True, rmin=rmin)
                if C is None:
                    continue
                mesh = _volume_mesh(C, R, hq)
                _SHELL_CACHE["items"][key] = mesh
                # (learnt: how many vertices for this area at this fineness)
                _SHELL_K["k"] = 0.5 * _SHELL_K["k"] + 0.5 * len(mesh[0]) * hq * hq / m["area"]
            used += len(mesh[0])
            out.append((mesh, W[sel]))
    _LAST["scatter"] = len(out)
    return out


def _part_objects(parts):
    """The variants in the path tracing: an object with the mesh (not rendered by itself) and one with a point per
    copy that puts an instance of it there (geometry nodes: the copies share the mesh on the graphics card)."""
    np = _np()
    mat = _material()
    made = []
    for i, ((pos, loops, sizes), W) in enumerate(parts):
        if not len(sizes) or not len(W):
            continue                          # (an empty variant: nothing to put in the picture)
        me = _mesh(pos, loops, sizes, mat)
        src = bpy.data.objects.new(f"{MAT_NAME} · forma {i}", me)
        src[PART_KEY] = 1
        src[INTERNAL_KEY] = 1
        bpy.context.scene.collection.objects.link(src)
        src.hide_render = True
        src.hide_viewport = True
        src.hide_select = True
        pts = bpy.data.meshes.new(f"{MAT_NAME} · copie {i}")
        pts.vertices.add(len(W))
        pts.vertices.foreach_set("co", W[:, :3, 3].ravel())
        a = pts.attributes.new("simpler_m", "FLOAT4X4", "POINT")
        a.data.foreach_set("value", W.transpose(0, 2, 1).ravel())        # (column after column)
        ins = bpy.data.objects.new(f"{MAT_NAME} · copie {i}", pts)
        ins[PART_KEY] = 1
        ins[INTERNAL_KEY] = 1
        bpy.context.scene.collection.objects.link(ins)
        ins.hide_select = True
        mod = ins.modifiers.new("Neve", "NODES")
        mod.node_group = _inst_group(src)
        nrm = np.empty(len(pos) * 3, dtype=np.float32)
        me.vertex_normals.foreach_get("vector", nrm)
        made.append((pos, loops, sizes, nrm.reshape(-1, 3), W))
    return made


def _inst_group(src):
    ng = bpy.data.node_groups.new(f"{MAT_NAME} · copie", "GeometryNodeTree")
    ng[PART_KEY] = 1
    ng.interface.new_socket("Geometry", in_out="INPUT", socket_type="NodeSocketGeometry")
    ng.interface.new_socket("Geometry", in_out="OUTPUT", socket_type="NodeSocketGeometry")
    N, L = ng.nodes, ng.links
    gi, go = N.new("NodeGroupInput"), N.new("NodeGroupOutput")
    oi = N.new("GeometryNodeObjectInfo")
    oi.inputs["Object"].default_value = src
    oi.inputs["As Instance"].default_value = True
    iop = N.new("GeometryNodeInstanceOnPoints")
    na = N.new("GeometryNodeInputNamedAttribute")
    na.data_type = "FLOAT4X4"
    na.inputs["Name"].default_value = "simpler_m"
    sit = N.new("GeometryNodeSetInstanceTransform")
    L.new(gi.outputs[0], iop.inputs["Points"])
    L.new(oi.outputs["Geometry"], iop.inputs["Instance"])
    L.new(iop.outputs[0], sit.inputs["Instances"])
    L.new(na.outputs[0], sit.inputs["Transform"])
    L.new(sit.outputs[0], go.inputs[0])
    return ng


def _mesh(pos, loops, sizes, mat, comp=None, thin=None):
    np = _np()
    me = bpy.data.meshes.new(MAT_NAME)
    me.vertices.add(len(pos))
    me.vertices.foreach_set("co", np.asarray(pos, dtype=np.float32).ravel())
    me.loops.add(len(loops))
    me.loops.foreach_set("vertex_index", np.asarray(loops, dtype=np.int32))
    me.polygons.add(len(sizes))
    # (1.76.25: no faces - a shell of a variant that came out empty - gave one start for none, and the path tracing
    # stopped with «sequence length mismatch given 1, needed 0», Luca)
    starts = np.concatenate([[0], np.cumsum(sizes)[:-1]]).astype(np.int32) if len(sizes) else np.zeros(0, np.int32)
    me.polygons.foreach_set("loop_start", starts)
    me.update()
    me.shade_smooth()
    if comp is not None and len(comp) == len(pos) and comp.max(initial=0) > 1e-3:
        at = me.attributes.new(COMPACT, "FLOAT", "POINT")
        at.data.foreach_set("value", np.asarray(comp, dtype=np.float32))
    if thin is not None and len(thin) == len(pos) and thin.max(initial=0) > 1e-3:
        at = me.attributes.new(THIN, "FLOAT", "POINT")
        at.data.foreach_set("value", np.asarray(thin, dtype=np.float32))
    me.materials.append(mat)
    return me


def _remove_parts():
    gone = False
    for ob in [o for o in bpy.data.objects if o.get(PART_KEY)]:
        me = ob.data
        bpy.data.objects.remove(ob, do_unlink=True)
        if me is not None and me.users == 0:
            bpy.data.meshes.remove(me)
        gone = True
    for ng in [g for g in bpy.data.node_groups if g.get(PART_KEY) and g.users == 0]:
        bpy.data.node_groups.remove(ng)
    return gone


# ---------------------------------------------------------------- the mantle

def _is_water_mat(m):
    from . import water
    try:
        return m is not None and bool(water.is_water(m))
    except Exception:
        return False


def _water_faces():
    """(16/11) Meshes with water on SOME of their faces (a river painted on the ground): (object, cut) where cut
    leaves out every material that is not water - those faces shelter what is under them like «Senza mantello»."""
    from . import rain
    out = []
    g = _ground()
    for ob in rain._scene_meshes() + ([g] if g is not None else []):
        if _no_mantle(ob) or not ob.material_slots:
            continue
        mats = [sl.material for sl in ob.material_slots]
        if any(_is_water_mat(m) for m in mats):
            out.append((ob, {m.name: True for m in mats if m is not None and not _is_water_mat(m)}))
    return out


def _covers():
    """What shelters without a mantle of its own («Senza mantello», not «Non fa riparo»): the surface of water, a
    sheet of glass. Under it no snow, however close (the shelter of the rain counts only what is well above)."""
    from . import rain
    return [ob for ob in rain._scene_meshes() if _no_mantle(ob)]


def _cover(x0, y0, nx, ny, cell):
    """The height of those over every cell (-inf: none), or None when there are none."""
    np = _np()
    obs = [(ob, {}) for ob in _covers()] + _water_faces()
    if not obs:
        return None
    out = np.full(nx * ny, -np.inf, dtype=np.float32)
    bx1, by1 = x0 + nx * cell, y0 + ny * cell
    for ob, cut in obs:
        P, box, _V = _world_tris(ob, cut)
        if not len(P):
            continue
        sel = (box[:, 1] >= x0) & (box[:, 0] <= bx1) & (box[:, 3] >= y0) & (box[:, 2] <= by1)
        if sel.any():
            _raster(P[sel], box[sel], x0, y0, nx, ny, cell, out)
    return out.reshape(ny, nx)


def _wet(x0, y0, nx, ny, cell):
    """(16/11) The height of the water over every cell (-inf: none), or None when there is no water: the objects made
    of water and the faces of water of any other mesh (a river painted on the ground: Luca, «On: Ground»)."""
    np = _np()
    from . import rain
    g = _ground()          # (Simpler's ground is not among the meshes of the scene: its own, the ground of the grid)
    obs = [(ob, {}) for ob in rain._scene_meshes() + ([g] if g is not None else []) if _water_surface(ob)] + _water_faces()
    if not obs:
        return None
    out = np.full(nx * ny, -np.inf, dtype=np.float32)
    bx1, by1 = x0 + nx * cell, y0 + ny * cell
    for ob, cut in obs:
        P, box, _V = _world_tris(ob, cut)
        if not len(P):
            continue
        sel = (box[:, 1] >= x0) & (box[:, 0] <= bx1) & (box[:, 3] >= y0) & (box[:, 2] <= by1)
        if sel.any():
            _raster(P[sel], box[sel], x0, y0, nx, ny, cell, out)
    return out.reshape(ny, nx)


def _cover_at(X, Y):
    """The height of those at these points (-inf: none; None: none at all) - a grid over their box, about 10 cm."""
    np = _np()
    if not len(X) or not (_covers() or _water_faces()):
        return None
    x0, y0 = float(X.min()) - 0.2, float(Y.min()) - 0.2
    size = max(float(X.max()) - x0, float(Y.max()) - y0) + 0.4
    cell = max(0.1, size / 2000.0)
    n = int(math.ceil(size / cell))
    g = _cover(x0, y0, n, n, cell)
    if g is None:
        return None
    i = np.clip(((Y - y0) / cell).astype(np.int64), 0, n - 1)
    j = np.clip(((X - x0) / cell).astype(np.int64), 0, n - 1)
    return g[i, j]


def _heights(obs, cut, x0, y0, nx, ny, cell):
    """Top of the geometry per cell (and of the «Sempre asciutto» objects), -inf where nothing is (ny x nx). The height
    of the surface at the centre of the cell (exact: a slope is not lifted by half a cell, as the highest point of a
    cell was); the highest corner or point of a side in the cell where that is higher than a cell above the centre - a
    post, the edge of a roof, a small object the centre misses."""
    np = _np()
    top = np.full(nx * ny, -np.inf, dtype=np.float32)
    dry = np.full(nx * ny, -np.inf, dtype=np.float32)
    pts = np.full(nx * ny, -np.inf, dtype=np.float32)
    dpts = np.full(nx * ny, -np.inf, dtype=np.float32)
    bx0, by0, bx1, by1 = x0, y0, x0 + nx * cell, y0 + ny * cell
    for ob in obs:
        P, box, V = _world_tris(ob, cut)
        if not len(P):
            continue
        sel = (box[:, 1] >= bx0) & (box[:, 0] <= bx1) & (box[:, 3] >= by0) & (box[:, 2] <= by1)
        if not sel.any():
            continue
        P, box = P[sel], box[sel]
        isdry = _dry(ob)
        _raster(P, box, x0, y0, nx, ny, cell, top)
        if isdry:
            _raster(P, box, x0, y0, nx, ny, cell, dry)
        Q = np.concatenate([V, _edge_points(P, cell * 0.9)])
        ix = np.floor((Q[:, 0] - x0) / cell).astype(np.int64)
        iy = np.floor((Q[:, 1] - y0) / cell).astype(np.int64)
        ok = (ix >= 0) & (ix < nx) & (iy >= 0) & (iy < ny)
        k = iy[ok] * nx + ix[ok]
        np.maximum.at(pts, k, Q[ok, 2])
        if isdry:
            np.maximum.at(dpts, k, Q[ok, 2])

    def merge(c, p):
        # the highest point counts where it is higher than the slope of the surface explains (the slope from the
        # neighbours, only where it goes the same way on both sides: a gap between the boards of a deck, a ridge, a
        # step - the highest; a hillside - the centre). No surface at the centre: -inf, any point counts
        c, p = c.reshape(ny, nx), p.reshape(ny, nx)
        f = np.where(np.isfinite(c), c, np.nan)
        allow = np.zeros_like(f)
        for dy, dx in ((0, 1), (1, 0)):
            fw = _shift(f, dy, dx, np.nan) - f
            bw = f - _shift(f, -dy, -dx, np.nan)
            same = np.sign(fw) == np.sign(bw)
            g = np.where(same, np.minimum(np.abs(fw), np.abs(bw)), 0.0)
            allow += np.nan_to_num(g, nan=0.0)
        allow = 0.5 * allow + 0.01
        with np.errstate(invalid="ignore"):
            hi = p > c + allow
        return np.where(hi, p, c)
    return merge(top, pts), merge(dry, dpts)


_CACHE = {"base": None, "field": None, "shells": None, "parts": None, "groups": None, "nparts": 0}


def _build(st, keep=False, cam=None, base=None):
    """The mantle: positions, faces (flat vertex indices, corners per face), compaction per vertex, or None when there
    is none. The models planned on their shape (_plan) apart, the rest in the grid from above. keep: only the
    sculpted snow changed - the heights and the models from the last time (_CACHE). cam: as the camera sees it
    (camview, _levels)."""
    np = _np()
    t0 = time.time()
    if keep:
        fields, shells = _CACHE["field"], _CACHE["shells"]
    else:
        _tris_fresh()
        obs = _objects()
        cut = {}
        for ob in obs:
            for m in ob.data.materials:
                if m is not None and m.name not in cut:
                    cut[m.name] = _cutout(m)
        _grid_max, max_snow = limits(st[9])
        plan = _plan(obs, st, max_snow, cam)
        grid_obs = [ob for ob in obs if _root(ob) not in plan]
        # (one limit for the whole mantle: the grid gets what the models left, at least 40% of it)
        budget = max(max_snow - _LAST.get("planned", 0.0), 0.4 * max_snow)
        if cam is not None:
            fields = _levels(st, obs, grid_obs, cut, budget, cam, base)
        else:
            F = _grid_field(st, obs, grid_obs, cut, budget)
            fields = [F] if F is not None else []
            _LAST.update(levels=1)
        t1 = time.time()
        shells = _shells(plan, cut, st)
        _LAST.update(shells=len(plan), shell_verts=int(sum(len(p) for p, _l, _s in shells)))
        log(f"SIMPLER_SNOW mantle: {len(plan)} models on their shape ({_LAST['shell_verts']} vertices, "
            f"{time.time() - t1:.2f} s)")
        _CACHE.update(field=fields, shells=shells)
    parts = []
    for F in fields or []:
        g = _grid_mesh(F)
        if g is not None:
            parts.append(g)
    parts += [(p, l, sz, np.zeros(len(p), dtype=np.float32), np.zeros(len(p), dtype=np.float32)) for p, l, sz in shells]
    if not parts:
        log(f"SIMPLER_SNOW mantle: no snow ({time.time() - t0:.2f} s)")
        return None
    pos = np.concatenate([p[0] for p in parts]).astype(np.float32)
    off = np.cumsum([0] + [len(p[0]) for p in parts[:-1]])
    loops = np.concatenate([p[1] + o for p, o in zip(parts, off)]).astype(np.int32)
    sizes = np.concatenate([p[2] for p in parts]).astype(np.int32)
    comp = np.concatenate([p[3] for p in parts]).astype(np.float32)
    thin = np.concatenate([p[4] for p in parts]).astype(np.float32)
    if not keep:
        _LAST.update(secs=round(time.time() - t0, 1))
    log(f"SIMPLER_SNOW mantle: {len(pos)} vertices in all, {time.time() - t0:.2f} s")
    return pos, loops, sizes, comp, thin


def _grid(st, obs, grid_obs, cut, budget):
    """The sheet of snow from above (ground, big models): positions, faces, compaction per vertex, or None."""
    F = _grid_field(st, obs, grid_obs, cut, budget)
    return None if F is None else _grid_mesh(F)


def _box_mean(v, w, r):
    """The mean of v (weights w) over a square of 2r+1 cells around every cell (sums of the rows and columns)."""
    np = _np()
    ny, nx = v.shape

    def box(a):
        c = np.zeros((ny + 1, nx + 1), dtype=np.float64)
        c[1:, 1:] = np.cumsum(np.cumsum(a, 0), 1)
        i0 = np.clip(np.arange(ny) - r, 0, ny); i1 = np.clip(np.arange(ny) + r + 1, 0, ny)
        j0 = np.clip(np.arange(nx) - r, 0, nx); j1 = np.clip(np.arange(nx) + r + 1, 0, nx)
        return c[i1][:, j1] - c[i0][:, j1] - c[i1][:, j0] + c[i0][:, j0]
    sw = box(w)
    with np.errstate(invalid="ignore", divide="ignore"):
        return (box(v) / sw).astype(np.float32)


def _scene_box(obs):
    """The ground the mantle covers: the box of the objects (and some ground around them) -> (x0, y0, x1, y1, margin)."""
    np = _np()
    lo, hi = [], []
    for ob in obs:
        c = np.array([ob.matrix_world @ __import__("mathutils").Vector(b) for b in ob.bound_box])
        lo.append(c[:, :2].min(0)); hi.append(c[:, :2].max(0))
    if not lo:
        return None
    margin = GROUND_MARGIN if _ground() is not None else 0.5
    x0, y0 = np.min(lo, axis=0) - margin
    x1, y1 = np.max(hi, axis=0) + margin
    return float(x0), float(y0), float(x1), float(y1), margin


def _grid_field(st, obs, grid_obs, cut, budget, frame=None, box=None):
    """The heavy part of the sheet (heights, thickness), kept while only the sculpted snow changes. frame: a given
    grid (x0, y0, nx, ny, cell - a part of the ground at its own fineness, _levels); else one grid over the whole
    ground, its cells as small as the budget allows."""
    np = _np()
    amount, walls, ssoft, sox, soy, depth, outdoor, _psoft, _prev, detail = st
    grid_max, _max = limits(detail)
    max_snow = int(budget)
    t0 = time.time()
    g = _ground()
    box = box or _scene_box(obs)
    if box is None:
        return None
    sx0, sy0, sx1, sy1, margin = box
    if frame is None:
        x0, y0 = sx0, sy0
        size = float(max(sx1 - sx0, sy1 - sy0, 1.0))
        # (a first guess of the cells with snow: most of the frame when it snows a lot - one grid instead of three)
        cell = max(MIN_CELL, size / grid_max, size * math.sqrt(min(1.0, 1.15 * amount) * 0.8 / max_snow))
        tries = 3
    else:
        x0, y0, cell = frame["x0"], frame["y0"], frame["cell"]
        tries = 1
    for attempt in range(tries):
        if frame is None:
            nx = ny = int(np.ceil(size / cell))
        else:
            nx, ny = frame["nx"], frame["ny"]
        top, dry = _heights(grid_obs, cut, x0, y0, nx, ny, cell)
        cover = _cover(x0, y0, nx, ny, cell)
        wet = _wet(x0, y0, nx, ny, cell)
        real = np.isfinite(top)
        if not real.any() and g is None:
            return None
        # a single empty cell inside a surface: the mean of its neighbours
        nb = [(dy, dx) for dy in (-1, 0, 1) for dx in (-1, 0, 1) if dy or dx]
        cnt = sum(_shift(real.astype(np.int32), dy, dx, 0) for dy, dx in nb)
        sm = sum(np.where(_shift(real, dy, dx, False), _shift(np.where(real, top, 0), dy, dx, 0), 0) for dy, dx in nb)
        hole = ~real & (cnt >= 5)
        top = np.where(hole, sm / np.maximum(cnt, 1), top)
        real = real | hole
        gz = float(g.matrix_world.translation.z) if g is not None else None
        if gz is not None:
            top = np.where(real, np.maximum(top, gz), gz)
            real = np.ones_like(real)
        # (two cells on the same surface: a slope that can still hold snow - «Sulle pareti» decides how steep; a
        # steeper step is an edge, where the snow ends rounded instead of hanging down the face in thin flaps)
        from . import rain
        wlo = 0.75 - 0.95 * walls - 0.5 * rain.NZJ_AMP     # (1.76.12: the slope shaken lets a little steeper hold)
        steep = min(math.acos(max(-1.0, min(1.0, wlo))) + math.radians(5.0), math.radians(80.0))
        disc = max(0.15, min(3.0, math.tan(steep)) * cell)
        # a cell at the edge of a roof or of a car can miss the points of its top: it looked lower, an edge inside the
        # roof - notches in the snow along every edge. Closed (the highest around, then the lowest around): a gap of
        # one cell is filled, a straight edge or a corner stays where it is
        tf = np.where(real, top, -1e6)
        dil = tf.copy()
        for dy, dx in nb:
            dil = np.maximum(dil, _shift(tf, dy, dx, -1e6))
        clo = dil.copy()
        for dy, dx in nb:
            clo = np.minimum(clo, _shift(dil, dy, dx, -1e6))
        top = np.where(clo > -1e5, np.maximum(tf, clo), top)
        real = real | (clo > -1e5)
        # smoothed on the same surface (a cell can hold the corner of something a little higher)
        tf = np.where(real, top, -1e6)
        acc, wsum = np.zeros_like(top), np.zeros_like(top)
        for dy in (-1, 0, 1):
            for dx in (-1, 0, 1):
                nbv = _shift(tf, dy, dx, -1e6)
                same = np.abs(nbv - tf) < 0.05
                acc += np.where(same, nbv, 0); wsum += same
        top = np.where(real, acc / np.maximum(wsum, 1), top)
        # (1.78.4, Luca: «sul bordo del marciapiede tagli squadrati») a kerb (a step of 5 to 30 cm, KERB_MIN,
        # KERB_MAX): the height of each cell is the one at its centre, so along a kerb that does not follow the grid the
        # rise came in steps of a cell - square teeth in the snow all along it. There the heights averaged (only the cells
        # beside such a step, only with cells on the same surface): the rise lies along the kerb
        tf = np.where(real, top, -1e6)
        kerb = np.zeros_like(real)
        for dy, dx in ((0, 1), (1, 0)):
            # (a jump between two cells with the surface level on both sides - a slope of a hill is not a kerb)
            f = np.abs(_shift(tf, dy, dx, -1e6) - tf)
            b = np.abs(tf - _shift(tf, -dy, -dx, -1e6))
            a = np.abs(_shift(tf, 2 * dy, 2 * dx, -1e6) - _shift(tf, dy, dx, -1e6))
            j = real & _shift(real, dy, dx, False) & (f >= KERB_MIN) & (f < KERB_MAX) & (b < 0.5 * f) & (a < 0.5 * f)
            kerb |= j | _shift(j, -dy, -dx, False)
        if kerb.any():
            # (two passes over the cells beside the kerb and one more around: the rise over about four cells, so that
            # no square across it is left steeper than the sheet joins - a higher kerb gave teeth again)
            grow = kerb.copy()
            for dy, dx in nb:
                grow |= _shift(kerb, dy, dx, False)
            kerb = grow & real
            for _ in range(2):
                tf = np.where(real, top, -1e6)
                acc, wsum = np.zeros_like(top), np.zeros_like(top)
                for dy in (-1, 0, 1):
                    for dx in (-1, 0, 1):
                        nbv = _shift(tf, dy, dx, -1e6)
                        same = np.abs(nbv - tf) < KERB_MAX
                        acc += np.where(same, nbv, 0); wsum += same
                top = np.where(kerb, acc / np.maximum(wsum, 1), top).astype(np.float32)
        # the snow lies softer than what is under it: the folds between the faces of a coarse terrain (or of a roof)
        # rounded over about twice its thickness or half the cell the whole ground would have - only with cells finer
        # than that (near the camera), never more than half the thickness away from the surface (no snow under the
        # ground at a ridge)
        ref = frame.get("ref", cell) if frame is not None else cell
        top_raw = top
        rt = int(round(max(2.0 * depth, 0.5 * ref) / cell))
        if rt >= 2 and cell < 0.75 * ref:
            tf = np.where(real, top, -1e6)
            edge = np.zeros_like(real)
            for dy, dx in nb:
                edge |= real & (np.abs(_shift(tf, dy, dx, -1e6) - tf) >= disc)
            w = (real & ~edge).astype(np.float64)
            ts = _box_mean(np.where(real, top, 0.0) * w, w, rt)
            ok = real & ~edge & np.isfinite(ts)
            top = np.where(ok, np.clip(ts, top - 0.5 * depth, top + 0.5 * depth), top).astype(np.float32)
        # slope of the top surface (only with neighbours on the same surface)
        tf = np.where(real, top, -1e6)

        def side(dy, dx):
            nbv = _shift(tf, dy, dx, -1e6)
            return nbv, np.abs(nbv - tf) < disc
        e, eo = side(0, 1); w_, wo = side(0, -1); nn, no = side(1, 0); s_, so = side(-1, 0)
        gx = np.where(eo & wo, (e - w_) / (2 * cell), np.where(eo, (e - tf) / cell, np.where(wo, (tf - w_) / cell, 0)))
        gy = np.where(no & so, (nn - s_) / (2 * cell), np.where(no, (nn - tf) / cell, np.where(so, (tf - s_) / cell, 0)))
        nz = 1.0 / np.sqrt(1.0 + gx * gx + gy * gy)
        # the same snow as the materials
        jx = (np.arange(nx) + 0.5) * cell + x0
        iy = (np.arange(ny) + 0.5) * cell + y0
        X, Y = np.meshgrid(jx, iy)
        S, face = _snow_at(X, Y, top, nz, st)
        S = np.where(real & ~(np.isfinite(dry) & (dry >= top - 0.03)), S, 0.0)
        # (under something that has no mantle but shelters - the surface of a pool, a pond: none, however close)
        if cover is not None:
            S = np.where(cover > top + 0.02, 0.0, S)
        if wet is not None:
            # (16/11) water at the height of the ground or above it (a river painted on the ground, a lake): no mantle
            S = np.where(wet >= top - 0.02, 0.0, S)
        t = depth * S
        # (a layer, not the grain of the pattern: the fine detail of the map stays in the white of the materials)
        rb = int(round(2.4 * ref / cell))      # (two passes of 3 x 3 reach about 2.4 cells: what this matches)
        if rb <= 3:
            for _ in range(2):
                acc, wsum = np.zeros_like(t), np.zeros_like(t)
                for dy in (-1, 0, 1):
                    for dx in (-1, 0, 1):
                        same = np.abs(_shift(tf, dy, dx, -1e6) - tf) < disc
                        acc += np.where(same, _shift(t, dy, dx, 0.0), 0); wsum += same
                t = acc / np.maximum(wsum, 1)
        else:
            # (finer cells than the whole ground would have - near the camera: the same smoothing in metres as there,
            # not in cells, or the snow would change from one fineness to the next; a box over the cells of a surface,
            # the edges by their neighbours)
            edge = np.zeros_like(real)
            acc, wsum = np.zeros_like(t), np.zeros_like(t)
            for dy in (-1, 0, 1):
                for dx in (-1, 0, 1):
                    same = np.abs(_shift(tf, dy, dx, -1e6) - tf) < disc
                    edge |= ~same & real
                    acc += np.where(same, _shift(t, dy, dx, 0.0), 0); wsum += same
            t1 = acc / np.maximum(wsum, 1)
            w = (real & ~edge).astype(np.float64)
            tb = _box_mean(t * w, w, rb)
            t = np.where(edge | ~np.isfinite(tb), t1, tb)
        # (the smoothing spreads the snow of a top onto the steep side next to it: there it hung as a curtain with a
        # ragged hem below the rim of a rock - the side keeps only what its own slope holds)
        t = t * _smooth(0.0, 0.5, face)
        # (seen from above a steep side is a staircase - a cell across, its whole height down: the edge of the snow on
        # it came out as teeth. The mantle ends on what is gentler than about 50 degrees, rounded; the white of the
        # materials goes on down the side. With snow «Sulle pareti» high, as it was)
        if walls < 0.5:
            t = t * _smooth(0.57, 0.77, nz)
        # rounded where the surface drops (edge of a roof, of a car), not where it rises (against a wall)
        drop = np.zeros_like(real)
        for dy, dx in ((0, 1), (0, -1), (1, 0), (-1, 0)):
            nbv = _shift(tf, dy, dx, -1e6)
            drop |= real & (nbv < tf - disc)
        # (and where the surface gets too steep to hold it - the side of a rock: the snow ends rounded on top)
        drop |= real & (face < 0.3)
        R = max(depth * 1.2, 1.5 * cell)
        D = np.where(drop, 0.0, np.inf).astype(np.float32)      # (the last cell: down to the surface)
        for _ in range(int(np.ceil(R / cell)) + 1):
            for dy, dx, c in ((0, 1, cell), (0, -1, cell), (1, 0, cell), (-1, 0, cell),
                              (1, 1, cell * 1.414), (1, -1, cell * 1.414), (-1, 1, cell * 1.414), (-1, -1, cell * 1.414)):
                D = np.minimum(D, _shift(D, dy, dx, np.inf) + c)
        f = np.sqrt(np.clip(1.0 - (1.0 - np.minimum(D / R, 1.0)) ** 2, 0.0, 1.0))
        # (the distance goes from cell to cell: along an edge that is not along the grid it climbs in steps, and the
        # edge of the snow came out as a row of teeth - smoothed on the same surface, the steps go)
        for _ in range(2):
            acc, wsum = np.zeros_like(f), np.zeros_like(f)
            for dy in (-1, 0, 1):
                for dx in (-1, 0, 1):
                    same = np.abs(_shift(tf, dy, dx, -1e6) - tf) < disc
                    acc += np.where(same, _shift(f, dy, dx, 0.0), 0); wsum += same
            f = np.where(drop, 0.0, acc / np.maximum(wsum, 1))
        t = t * f
        # to nothing at the border of the ground (beyond it the ground keeps the white of the materials)
        if g is not None:
            bd = np.minimum(np.minimum(X - sx0, sx1 - X), np.minimum(Y - sy0, sy1 - Y))
            t = t * _smooth(0.5, margin - 1.0, bd)
        # (a fold rounded down: never so low that the surface under it comes through where the snow is thin)
        top = np.where(real, np.maximum(top, top_raw - 0.6 * t), top)
        snow = t > 0.003
        # specks (a branch, the top of a post): away
        snow &= sum(_shift(snow.astype(np.int32), dy, dx, 0) for dy, dx in nb) >= 3
        count = int(snow.sum())
        if count <= max_snow or attempt == tries - 1:
            break
        cell *= math.sqrt(count / max_snow) * 1.05
    if not snow.any() and frame is None:
        log(f"SIMPLER_SNOW mantle: no snow ({time.time() - t0:.2f} s)")
        return None
    t = np.where(snow, t, 0.0)
    if frame is None:
        log(f"SIMPLER_SNOW grid {nx}x{ny} cell {cell * 100:.1f} cm, {int(snow.sum())} cells with snow, {time.time() - t0:.2f} s")
        _LAST.update(cell=float(cell))
    return {"nx": nx, "ny": ny, "cell": float(cell), "x0": float(x0), "y0": float(y0), "top": top.astype(np.float32),
            "real": real, "t": t.astype(np.float32), "snow": snow, "disc": disc, "secs": time.time() - t0}


# ---------------------------------------------------------------- the ground as the camera sees it
# «Calcola solo l'area inquadrata» (camview, snow): the same budget of vertices, spent where the camera looks. A base
# grid over the whole ground (a quarter of the budget: what is out of the frame, what is far); on it, every square
# between four of its cells gets a level L - 0 the base, each level half the cell of the one before (down to
# MIN_CELL) - from its distance to the camera (cell = lam x distance, lam as small as the budget allows) and only in
# the frame (with a margin); two squares side by side differ by one level at most. Every level is a grid of its own
# over the squares it holds (and some cells around them, for the smoothing and the rounded edges), whose cell centres
# fall on the centres of the coarser ones: where two levels meet, the vertices of the finer one along the side are
# put on the straight side of the coarser one (no crack, no step).

BASE_SHARE = 0.25
LEVEL_CELLS = 6000000                       # cells of the grid of one level, at most


def _levels(st, obs, grid_obs, cut, budget, cam, base=None):
    np = _np()
    from . import camview
    t0 = time.time()
    box = _scene_box(obs)
    if box is None:
        return []
    # (the cell the whole ground would have without the camera: the snow is smoothed as there, in metres)
    size = float(max(box[2] - box[0], box[3] - box[1], 1.0))
    ref = max(MIN_CELL, size / limits(st[9])[0], size * math.sqrt(min(1.0, 1.15 * st[0]) * 0.8 / max(budget, 1.0)))
    if ref < 2.0 * NEAR_CELL:
        # (a small scene: the whole ground is already as fine as the mantle goes)
        F = _grid_field(st, obs, grid_obs, cut, budget, box=box)
        _LAST.update(levels=1)
        return [F] if F is not None else []
    # (the base does not depend on the camera: kept while the scene and the snow stay the same)
    key = (base, round(budget), tuple(sorted(ob.name for ob in grid_obs)))
    if base is not None and _CACHE.get("f0key") == key:
        F0 = dict(_CACHE["f0"])
    else:
        F0 = _grid_field(st, obs, grid_obs, cut, max(1000.0, budget * BASE_SHARE), box=box)
        _CACHE.update(f0key=key, f0=dict(F0) if F0 is not None else None)
    if F0 is None:
        return []
    cb = F0["cell"]
    nx0, ny0 = F0["nx"], F0["ny"]
    if nx0 < 2 or ny0 < 2:
        return [F0]
    fr = camview.Frustum(cam, 0.1)
    top0 = np.where(F0["real"], F0["top"], np.nan)
    Xc = (np.arange(nx0) + 0.5) * cb + F0["x0"]
    Yc = (np.arange(ny0) + 0.5) * cb + F0["y0"]
    # the squares: their centre (the mean of their corners), whether snow can be there
    zq = np.nanmean(np.stack([top0[:-1, :-1], top0[:-1, 1:], top0[1:, 1:], top0[1:, :-1]]), axis=0)
    zq = np.where(np.isfinite(zq), zq, 0.0)
    QX, QY = np.meshgrid(Xc[:-1] + 0.5 * cb, Yc[:-1] + 0.5 * cb)
    P = np.stack([QX.ravel(), QY.ravel(), zq.ravel()], axis=1)
    rad = 0.75 * cb
    d, inside = fr.look(P, rad)
    d = np.maximum(d - rad, 0.5).reshape(QX.shape)
    inside = inside.reshape(QX.shape)
    sn = F0["snow"] | (F0["real"] & (F0["t"] > 0))
    snq = sn[:-1, :-1] | sn[:-1, 1:] | sn[1:, 1:] | sn[1:, :-1]
    grow = snq.copy()                                   # (a thin patch the base missed: one square around)
    grow[1:] |= snq[:-1]; grow[:-1] |= snq[1:]; grow[:, 1:] |= snq[:, :-1]; grow[:, :-1] |= snq[:, 1:]
    cand = grow & inside
    lmax = max(0, int(math.floor(math.log2(cb / NEAR_CELL))))
    if lmax == 0 or not cand.any():
        return [F0]
    dc = d[cand]
    fine_budget = max(0.0, budget - float(F0["snow"].sum()))

    def lev(lam):
        return np.clip(np.ceil(np.log2(cb / np.maximum(lam * dc, 1e-9))), 0, lmax).astype(np.int64)

    def cost(lam):
        L = lev(lam)
        return float((4.0 ** L).sum() - len(L))         # (the vertices a level adds over the base)
    lo, hi = math.log(1e-5), math.log(10.0)
    for _ in range(40):
        mid = 0.5 * (lo + hi)
        if cost(math.exp(mid)) > fine_budget:
            lo = mid
        else:
            hi = mid
    lam = math.exp(hi)
    for _ in range(12):
        L = np.zeros(d.shape, dtype=np.int64)
        L[cand] = lev(lam)
        # (two squares side by side: one level apart at most)
        for _k in range(lmax):
            m = L.copy()
            for dy, dx in ((0, 1), (0, -1), (1, 0), (-1, 0), (1, 1), (1, -1), (-1, 1), (-1, -1)):
                m = np.maximum(m, _shift(L, dy, dx, 0))
            L2 = np.maximum(L, m - 1)
            if (L2 == L).all():
                break
            L = L2
        frames = []
        big = False
        for lv in range(1, lmax + 1):
            sel = L == lv
            if not sel.any():
                continue
            rows, cols = np.nonzero(sel.any(1))[0], np.nonzero(sel.any(0))[0]
            k = 2 ** lv
            c = cb / k
            R = max(st[5] * 1.2, 1.5 * c)
            M = int(math.ceil(R / c)) + 6
            qi0, qi1, qj0, qj1 = int(rows[0]), int(rows[-1]), int(cols[0]), int(cols[-1])
            nx, ny = (qj1 + 1 - qj0) * k + 1 + 2 * M, (qi1 + 1 - qi0) * k + 1 + 2 * M
            if nx * ny > LEVEL_CELLS:
                big = True
                break
            frames.append({"L": lv, "k": k, "M": M, "qi0": qi0, "qj0": qj0, "rows": qi1 + 1 - qi0, "ref": ref,
                           "cols": qj1 + 1 - qj0, "nx": nx, "ny": ny, "cell": c,
                           "x0": float(Xc[qj0] - M * c - 0.5 * c), "y0": float(Yc[qi0] - M * c - 0.5 * c)})
        if not big:
            break
        lam *= 1.3
    F0["own"] = L == 0
    F0.update(L=0, k=1, M=0, qi0=0, qj0=0)
    fields = {0: F0}
    for fr_ in frames:
        F = _grid_field(st, obs, grid_obs, cut, 1e12, frame=fr_, box=box)
        if F is None:
            continue
        F.update({k: fr_[k] for k in ("L", "k", "M", "qi0", "qj0")})
        lv, k, M = fr_["L"], fr_["k"], fr_["M"]
        # the squares it holds
        a = np.arange(F["ny"] - 1) - M
        b = np.arange(F["nx"] - 1) - M
        qa = np.where((a >= 0) & (a < fr_["rows"] * k), fr_["qi0"] + np.floor_divide(a, k), -1)
        qb = np.where((b >= 0) & (b < fr_["cols"] * k), fr_["qj0"] + np.floor_divide(b, k), -1)
        A, B = np.meshgrid(qa, qb, indexing="ij")
        okq = (A >= 0) & (B >= 0)
        own = np.zeros(A.shape, dtype=bool)
        own[okq] = L[A[okq], B[okq]] == lv
        F["own"] = own
        _snap(F, fields, L)
        fields[lv] = F
    _LAST.update(cell=float(min(F["cell"] for F in fields.values())), levels=len(fields), lam=lam)
    log(f"SIMPLER_SNOW camera: base {nx0}x{ny0} cell {cb * 100:.1f} cm, levels " +
        ", ".join(f"{F['cell'] * 100:.1f} cm {F['nx']}x{F['ny']} ({F['secs']:.2f} s)" for lv, F in sorted(fields.items()) if lv) +
        f", {time.time() - t0:.2f} s")
    return [fields[k] for k in sorted(fields)]


def _snap(F, fields, L):
    """The vertices of a level on the side of a coarser one: put on the straight side of the coarser level (its
    height and thickness, linear between its vertices)."""
    np = _np()
    lv, k, M = F["L"], F["k"], F["M"]
    nqy, nqx = L.shape
    i = np.arange(F["ny"]) - M
    j = np.arange(F["nx"]) - M
    I, J = np.meshgrid(i, j, indexing="ij")
    on_r, on_c = (I % k) == 0, (J % k) == 0
    inside = (I >= 0) & (J >= 0) & (I <= (nqy - F["qi0"]) * k) & (J <= (nqx - F["qj0"]) * k)
    cand = inside & (on_r | on_c)
    if not cand.any():
        return
    ci, cj = np.nonzero(cand)
    bi = F["qi0"] + I[ci, cj] / k                   # (base rows/columns, fractional along a side)
    bj = F["qj0"] + J[ci, cj] / k
    r_on, c_on = on_r[ci, cj], on_c[ci, cj]
    big = 99
    lmin = np.full(len(ci), big)
    has_own = np.zeros(len(ci), dtype=bool)

    def look(qi, qj, use):
        ok = use & (qi >= 0) & (qi < nqy) & (qj >= 0) & (qj < nqx)
        v = np.full(len(qi), big)
        v[ok] = L[qi[ok], qj[ok]]
        return v
    fi, fj = np.floor(bi).astype(np.int64), np.floor(bj).astype(np.int64)
    ri, rj = np.round(bi).astype(np.int64), np.round(bj).astype(np.int64)
    quads = []
    # on a row of the base: the squares above and below; on a column: left and right; a corner: the four
    quads.append(look(ri - 1, np.where(c_on, rj - 1, fj), r_on))
    quads.append(look(ri, np.where(c_on, rj - 1, fj), r_on))
    quads.append(look(fi, rj - 1, c_on & ~r_on))
    quads.append(look(np.where(r_on, ri, fi), rj, c_on))
    quads.append(look(ri - 1, rj, r_on & c_on))
    for v in quads:
        lmin = np.minimum(lmin, v)
        has_own |= v == lv
    sel = has_own & (lmin < lv)
    if not sel.any():
        return
    ci, cj, bi, bj, lmin = ci[sel], cj[sel], bi[sel], bj[sel], lmin[sel]
    for lo in np.unique(lmin):
        G = fields.get(int(lo))
        if G is None:
            continue
        m = lmin == lo
        gi = G["M"] + (bi[m] - G["qi0"]) * G["k"]
        gj = G["M"] + (bj[m] - G["qj0"]) * G["k"]
        i0 = np.clip(np.floor(gi).astype(np.int64), 0, G["ny"] - 1)
        j0 = np.clip(np.floor(gj).astype(np.int64), 0, G["nx"] - 1)
        i1 = np.clip(i0 + 1, 0, G["ny"] - 1)
        j1 = np.clip(j0 + 1, 0, G["nx"] - 1)
        fy, fx = np.clip(gi - i0, 0, 1), np.clip(gj - j0, 0, 1)
        tg = np.where(G["real"], G["top"], np.nan)
        th = np.where(G["snow"], G["t"], 0.0)

        def bil(a):
            return (a[i0, j0] * (1 - fx) + a[i0, j1] * fx) * (1 - fy) + (a[i1, j0] * (1 - fx) + a[i1, j1] * fx) * fy
        tz, tt = bil(tg), bil(th)
        ok = np.isfinite(tz)
        a, b = ci[m][ok], cj[m][ok]
        F["top"][a, b] = tz[ok]
        F["t"][a, b] = tt[ok]
        F["snow"][a, b] = tt[ok] > 0
        F["real"][a, b] = True


FINE_MAX = 4000000                          # lattice points of the sculpted part of the sheet, at most


def _sculpted(T, D, C):
    """The thickness of the snow sculpted (snowsculpt): thickness T, D added, C how pressed. Heaped: T + D. Dug
    (C = 0): T + D, down to the ground. Pressed (a footprint, a tyre: C = 1): the snow under the foot squeezed, not
    taken away - T exp(D / T), about T + D in deep snow, a thin layer that keeps the shape of the sole and of the
    tread where the snow is thinner than the print."""
    np = _np()
    dug = np.maximum(T + D, 0.0)
    pressed = T * np.exp(np.minimum(D, 0.0) / np.maximum(T, 1e-3))
    return np.where(D >= 0, T + D, C * pressed + (1.0 - C) * dug)


def _grid_mesh(F):
    """The sheet from the field; the quads near the sculpted snow (snowsculpt) cut into small squares of about 1.5 cm,
    their height top + the thickness sculpted (_sculpted). F["own"]: only these quads (a part of the ground at its
    fineness, _levels)."""
    np = _np()
    from . import snowsculpt
    t0 = time.time()
    nx, ny, cell, x0, y0, top, real, t, snow, disc = (F[k] for k in ("nx", "ny", "cell", "x0", "y0", "top", "real", "t", "snow", "disc"))
    nb = [(dy, dx) for dy in (-1, 0, 1) for dx in (-1, 0, 1) if dy or dx]
    tf = np.where(real, top, -1e6)
    X, Y = np.meshgrid((np.arange(nx) + 0.5) * cell + x0, (np.arange(ny) + 0.5) * cell + y0)
    # the vertices: the cells with snow and their neighbours on the same surface (the sheet comes down to it)
    near = np.zeros_like(snow)
    for dy, dx in nb + [(0, 0)]:
        nbv = _shift(tf, dy, dx, -1e6)
        near |= _shift(snow, dy, dx, False) & (np.abs(nbv - tf) < disc)
    V = real & (snow | near)
    vid = np.full(V.shape, -1, dtype=np.int64)
    vid[V] = np.arange(int(V.sum()))
    # quads between four vertices on the same surface, with some snow
    a, b, c, d = vid[:-1, :-1], vid[:-1, 1:], vid[1:, 1:], vid[1:, :-1]
    ta, tb, tc, td = tf[:-1, :-1], tf[:-1, 1:], tf[1:, 1:], tf[1:, :-1]
    ok = (a >= 0) & (b >= 0) & (c >= 0) & (d >= 0)
    hs4 = np.stack([ta, tb, tc, td])
    ok &= (hs4.max(0) - hs4.min(0)) < disc
    ok &= snow[:-1, :-1] | snow[:-1, 1:] | snow[1:, 1:] | snow[1:, :-1]
    if F.get("own") is not None:
        ok &= F["own"]
    quads = np.stack([a[ok], b[ok], c[ok], d[ok]], axis=1)
    if not len(quads):
        return None
    qi, qj = np.nonzero(ok)
    yy, xx = np.nonzero(V)
    px = X[yy, xx].astype(np.float64)
    py = Y[yy, xx].astype(np.float64)
    # the border against a wall goes a little into it (no gap between the snow and the wall)
    for dy, dx in ((0, 1), (0, -1), (1, 0), (-1, 0)):
        nbv = _shift(tf, dy, dx, -1e6)[yy, xx]
        nbV = _shift(V, dy, dx, False)[yy, xx]
        wall = (~nbV) & (nbv > tf[yy, xx] + disc)
        px = px + np.where(wall, 0.6 * cell * dx, 0)
        py = py + np.where(wall, 0.6 * cell * dy, 0)
    tv = np.where(snow[yy, xx], t[yy, xx], 0.0).astype(np.float64)
    # (the vertices at a rim - the surface drops beside them: where the outline of the snow comes out in steps)
    rimg = np.zeros(tf.shape, dtype=bool)
    for dy, dx in nb:
        rimg |= real & (_shift(tf, dy, dx, -1e6) < tf - disc)
    for _ in range(2):                                          # (and two cells around it)
        g2 = rimg.copy()
        for dy, dx in nb:
            g2 |= _shift(rimg, dy, dx, False)
        rimg = g2
    rimv = rimg[yy, xx]
    base = np.stack([px, py, top[yy, xx].astype(np.float64)], axis=1)
    comp = np.zeros(len(base))
    fine = snowsculpt.touched_cells(x0, y0, nx, cell, ny) if snowsculpt.present() else None
    nfine = 0
    if fine is not None and fine.any():
        isf = (fine[:-1, :-1] | fine[:-1, 1:] | fine[1:, 1:] | fine[1:, :-1])[qi, qj]
        if isf.any():
            FQ, fi, fj = quads[isf], qi[isf], qj[isf]
            quads = quads[~isf]
            nf = len(FQ)
            m = int(min(64, max(1, round(cell / snowsculpt.PX))))
            while m > 1 and nf * (m + 1) ** 2 > FINE_MAX:
                m -= 1
            lv, lu = np.meshgrid(np.arange(m + 1), np.arange(m + 1), indexing="ij")
            lv, lu = lv.ravel(), lu.ravel()
            u, v = lu / m, lv / m
            w = np.stack([(1 - u) * (1 - v), u * (1 - v), u * v, (1 - u) * v])           # corners a, b, c, d
            P = np.einsum("fkc,kq->fqc", base[FQ], w)
            T = np.einsum("fk,kq->fq", tv[FQ], w)
            W = (nx - 1) * m + 1
            key = (fi[:, None] * m + lv[None]) * W + fj[:, None] * m + lu[None]
            uk, first, inv = np.unique(key.ravel(), return_index=True, return_inverse=True)
            nb0 = len(base)
            idx = (nb0 + inv).reshape(nf, -1)
            for k, q in enumerate((0, m, (m + 1) * (m + 1) - 1, m * (m + 1))):       # (the corners: the coarse vertices)
                idx[:, q] = FQ[:, k]
            NP = P.reshape(-1, 3)[first]
            Dv, Cv = snowsculpt.sample(NP[:, 0], NP[:, 1])
            # (the corners too: inside the sculpted part they are its points like the others - only at the border of
            # the fine part the snow is as it was, there the coarse quads meet it without a step)
            cor = np.unique(FQ)
            Dc, Cc = snowsculpt.sample(base[cor, 0], base[cor, 1])
            tv = tv.copy()
            tv[cor] = _sculpted(tv[cor], Dc, Cc)
            comp[cor] = Cc
            base = np.concatenate([base, NP])
            rimv = np.concatenate([rimv, np.zeros(len(NP), dtype=bool)])
            tv = np.concatenate([tv, _sculpted(T.ravel()[first], Dv, Cv)])
            comp = np.concatenate([comp, Cv])
            sv, su = np.meshgrid(np.arange(m), np.arange(m), indexing="ij")
            q00 = (sv * (m + 1) + su).ravel()
            sub = np.stack([idx[:, q00], idx[:, q00 + 1], idx[:, q00 + m + 2], idx[:, q00 + m + 1]], axis=2)
            quads = np.concatenate([quads, sub.reshape(-1, 4)])
            nfine = len(uk)
    pos = base.copy()
    pos[:, 2] += np.maximum(tv, 0.0) + LIFT
    thin = 1.0 - _smooth(EPS, 0.04, np.maximum(tv, 0.0))       # («Neve vecchia»: dirtier where it thins out)
    # the edge of the snow cut along the line where the thickness ends (inside the cells, not on their sides: the
    # patches had steps of a cell)
    inn = tv >= EPS
    qin = inn[quads]
    full = qin.all(1)
    mixed = qin.any(1) & ~full
    Q = quads[mixed]
    I, J = Q, np.roll(Q, -1, axis=1)
    inI = inn[I]
    cross = inI != inn[J]
    s_ = np.where(cross, (EPS - tv[I]) / np.where(cross, tv[J] - tv[I], 1.0), 0.0)[cross]
    ci, cj = I[cross], J[cross]
    pb = base[ci] + (base[cj] - base[ci]) * s_[:, None]
    pb[:, 2] += EPS + LIFT
    R = np.full((len(Q), 8), -1, dtype=np.int64)
    R[:, 0::2] = np.where(inI, I, -1)
    newid = np.full(Q.shape, -1, dtype=np.int64)
    newid[cross] = len(pos) + np.arange(int(cross.sum()))
    R[:, 1::2] = newid
    rs = (R >= 0).sum(1)
    keep = rs >= 3
    R, rs = R[keep], rs[keep]
    pos = np.concatenate([pos, pb])
    comp = np.concatenate([comp, comp[ci] + (comp[cj] - comp[ci]) * s_])
    thin = np.concatenate([thin, np.ones(len(ci))])
    rimv = np.concatenate([rimv, rimv[ci] | rimv[cj]])
    loops = np.concatenate([quads[full].ravel(), R[R >= 0]]).astype(np.int64)
    sizes = np.concatenate([np.full(int(full.sum()), 4, dtype=np.int64), rs]).astype(np.int64)
    pos = _smooth_edge(pos, loops, sizes, thin, rimv)
    # (1.75.16) closed borders: where the sheet ends still thick (against an object, a hole, a cut of the sculpted
    # snow) its open edge let one see under the snow - dark slits along the sidewalk (Luca). A skirt from the edge
    # down to the surface under it (1 cm into it)
    topz = np.concatenate([base[:, 2], pb[:, 2] - (EPS + LIFT)])
    pos, loops, sizes, comp, thin = _skirt(pos, loops, sizes, comp, thin, topz)
    # only the vertices used
    used = np.zeros(len(pos), dtype=bool)
    used[loops] = True
    remap = np.full(len(pos), -1, dtype=np.int64)
    remap[used] = np.arange(int(used.sum()))
    pos = pos[used].astype(np.float32)
    comp = comp[used].astype(np.float32)
    thin = thin[used].astype(np.float32)
    loops = remap[loops]
    log(f"SIMPLER_SNOW sheet: {len(pos)} vertices ({nfine} sculpted), {len(sizes)} faces, {time.time() - t0:.2f} s")
    return pos, loops.astype(np.int32), sizes.astype(np.int32), comp, thin


EDGE_PASSES = 40
SKIRT_MIN = 0.01          # an open edge higher than this over the surface under it gets a skirt


def _skirt(pos, loops, sizes, comp, thin, topz):
    """The open edges of the sheet that stand above the surface under them closed by a strip down to it."""
    np = _np()
    if not len(sizes):
        return pos, loops, sizes, comp, thin
    starts = np.concatenate([[0], np.cumsum(sizes)[:-1]])
    nxt = np.arange(len(loops)) + 1
    ends = starts + sizes
    last = np.zeros(len(loops), dtype=bool)
    last[ends - 1] = True
    nxt[last] = np.repeat(starts, sizes)[last]
    a, b = loops, loops[nxt]
    # an edge is open when its reverse is not in the mesh (and it appears once)
    n = int(len(pos))
    hi = (pos[a, 2] - topz[a] > SKIRT_MIN) & (pos[b, 2] - topz[b] > SKIRT_MIN)
    if not hi.any():
        return pos, loops, sizes, comp, thin
    fs = np.sort(a.astype(np.int64) * n + b)
    ca, cb = a[hi].astype(np.int64), b[hi].astype(np.int64)
    rev = cb * n + ca
    i = np.minimum(np.searchsorted(fs, rev), len(fs) - 1)
    has_rev = fs[i] == rev
    fw = ca * n + cb
    once = (np.searchsorted(fs, fw, side="right") - np.searchsorted(fs, fw, side="left")) == 1
    sel = once & ~has_rev
    if not sel.any():
        return pos, loops, sizes, comp, thin
    ea, eb = a[hi][sel], b[hi][sel]
    verts = np.unique(np.concatenate([ea, eb]))
    low = np.full(n, -1, dtype=np.int64)
    low[verts] = n + np.arange(len(verts))
    lp = pos[verts].copy()
    lp[:, 2] = topz[verts] - 0.01
    quads = np.stack([eb, ea, low[ea], low[eb]], axis=1).ravel()
    pos = np.concatenate([pos, lp.astype(pos.dtype)])
    comp = np.concatenate([comp, comp[verts]])
    thin = np.concatenate([thin, np.ones(len(verts), dtype=thin.dtype)])
    loops = np.concatenate([loops, quads]).astype(loops.dtype)
    sizes = np.concatenate([sizes, np.full(len(ea), 4, dtype=sizes.dtype)])
    return pos, loops, sizes, comp, thin


def _smooth_edge(pos, loops, sizes, thin, rim):
    """The outline of the snow straightened: where the snow ends (thin) along an edge that does not follow the grid, its
    vertices zig-zag from cell to cell - a row of teeth on the rim of a slab, near the camera. Every vertex of the
    outline at a rim goes half way to the middle of its two neighbours along it, a few times (the vertices inside, the
    outline of patches of snow on a flat ground - smooth already - and the sides between the parts of the ground made
    at different fineness, where the snow goes on, do not move)."""
    np = _np()
    if not len(loops):
        return pos
    nf = len(sizes)
    starts = np.concatenate([[0], np.cumsum(sizes)[:-1]])
    idx = np.arange(len(loops))
    st = np.repeat(starts, sizes)
    last = st + np.repeat(sizes, sizes) - 1
    nxt = np.where(idx == last, st, idx + 1)
    a, b = loops[idx], loops[nxt]
    lo, hi = np.minimum(a, b), np.maximum(a, b)
    key = lo * (len(pos) + 1) + hi
    uk, inv, cnt = np.unique(key, return_inverse=True, return_counts=True)
    bnd = cnt[inv] == 1
    ea, eb = a[bnd], b[bnd]
    if not len(ea):
        return pos
    deg = np.zeros(len(pos), dtype=np.int64)
    np.add.at(deg, ea, 1); np.add.at(deg, eb, 1)
    move = (deg == 2) & (thin > 0.3) & rim
    if not move.any():
        return pos
    p = pos.astype(np.float64).copy()
    for _ in range(EDGE_PASSES):
        acc = np.zeros_like(p)
        np.add.at(acc, ea, p[eb]); np.add.at(acc, eb, p[ea])
        p[move] = 0.5 * p[move] + 0.25 * acc[move]
    return p


def _material():
    """The snow of the mantle: the colour of rain.py's snow, a little greyer and smoother where it is trodden
    (sculpted: footprints, tyre tracks), and old (rain.aged_snow_nodes: «Neve vecchia», the same stains as on the
    materials; its edge here: where the mantle is thin)."""
    from . import rain
    mat = bpy.data.materials.get(MAT_NAME)
    if mat is not None and mat.get("simpler_snow_v") == 4:
        return mat
    if mat is None:
        mat = bpy.data.materials.new(MAT_NAME)
    mat["simpler_snow_v"] = 4
    mat.use_nodes = True
    nt = mat.node_tree
    N, L = nt.nodes, nt.links
    for nd in list(N):
        N.remove(nd)
    out = N.new("ShaderNodeOutputMaterial")
    p = N.new("ShaderNodeBsdfPrincipled")
    sock = lambda socks, ident: next(x for x in socks if x.identifier == ident)

    def m(op, a, b_=None, c=None):
        n = N.new("ShaderNodeMath")
        n.operation = op
        for i, x in enumerate((a, b_, c)):
            if x is None:
                continue
            if isinstance(x, (int, float)):
                n.inputs[i].default_value = x
            else:
                L.new(x, n.inputs[i])
        return n.outputs[0]

    def smooth(e0, e1, x):
        n = N.new("ShaderNodeMapRange")
        n.interpolation_type = "SMOOTHSTEP"
        n.clamp = True
        for name, v in (("Value", x), ("From Min", e0), ("From Max", e1)):
            if isinstance(v, (int, float)):
                n.inputs[name].default_value = v
            else:
                L.new(v, n.inputs[name])
        return n.outputs["Result"]

    def attr(name):
        at = N.new("ShaderNodeAttribute")
        at.attribute_type = "GEOMETRY"
        at.attribute_name = name
        return at.outputs["Fac"]
    C, thin = attr(COMPACT), attr(THIN)
    agev = N.new("ShaderNodeValue")
    agev.name = agev.label = "age"
    agev.outputs[0].default_value = float(M.get("age", 0.0))
    age = agev.outputs[0]
    mix = N.new("ShaderNodeMix")
    mix.data_type = "RGBA"
    sock(mix.inputs, "A_Color").default_value = SNOW_COLOR + (1.0,)
    sock(mix.inputs, "B_Color").default_value = TRODDEN + (1.0,)
    L.new(m("MULTIPLY", C, TRODDEN_MIX), sock(mix.inputs, "Factor_Float"))
    geo = N.new("ShaderNodeNewGeometry")
    sp = N.new("ShaderNodeSeparateXYZ")
    L.new(geo.outputs["Position"], sp.inputs[0])
    col = rain.aged_snow_nodes(N, L, m, smooth, sp.outputs["X"], sp.outputs["Y"], age, thin, C, rain._mask_image(),
                               sock(mix.outputs, "Result_Color"))
    L.new(col, p.inputs["Base Color"])
    r0 = m("MULTIPLY_ADD", C, TRODDEN_ROUGH - 0.55, 0.55)
    L.new(m("MULTIPLY_ADD", m("MULTIPLY", age, 0.6), m("SUBTRACT", TRODDEN_ROUGH, r0), r0), p.inputs["Roughness"])
    # small lumps on the surface (no geometry: a bump)
    tc = nt.nodes.new("ShaderNodeTexCoord")
    nz = nt.nodes.new("ShaderNodeTexNoise")
    nz.inputs["Scale"].default_value = 1.5
    nz.inputs["Detail"].default_value = 4.0
    bump = nt.nodes.new("ShaderNodeBump")
    bump.inputs["Strength"].default_value = 0.08
    bump.inputs["Distance"].default_value = 0.02
    nt.links.new(tc.outputs["Object"], nz.inputs["Vector"])
    nt.links.new(nz.outputs["Fac"], bump.inputs["Height"])
    nt.links.new(bump.outputs["Normal"], p.inputs["Normal"])
    nt.links.new(p.outputs[0], out.inputs["Surface"])
    return mat


def set_age(a):
    """«Neve vecchia» (rain.update): only the material of the mantle - nothing is made again."""
    M["age"] = float(a)
    mat = bpy.data.materials.get(MAT_NAME)
    n = mat.node_tree.nodes.get("age") if (mat is not None and mat.node_tree) else None
    if n is not None and abs(n.outputs[0].default_value - a) > 1e-6:
        n.outputs[0].default_value = float(a)


def _object():
    for ob in bpy.context.scene.objects:
        if ob.get(MANTLE_KEY):
            return ob
    return None


def remove():
    _CACHE.update(base=None, field=None, shells=None, parts=None, groups=None, nparts=0, f0key=None, f0=None)
    gone = _remove_parts()
    ob = _object()
    if ob is None:
        return gone
    me = ob.data
    bpy.data.objects.remove(ob, do_unlink=True)
    if me is not None and me.users == 0:
        bpy.data.meshes.remove(me)
    return True


def _write_view(groups):
    """The mantle for the real-time view: «MNT3», groups; each: u32 vertices, u32 indices, u32 copies, u32 flags (1: with
    compaction, 2: with thinness), float32 positions, float32 normals, u32 triangles, float32 4x4 matrices of the copies (column
    after column; none: drawn as it is), float32 compaction per vertex (sculpted snow), float32 thinness per vertex
    (where the sheet thins out: «Neve vecchia»)."""
    np = _np()
    from . import rain
    d = rain._shelter_dir()
    for f in os.listdir(d):
        if f.startswith("mantle_"):
            try:
                os.remove(os.path.join(d, f))
            except OSError:
                pass
    stem = f"mantle_{os.getpid()}_{M['rev']}"
    with open(os.path.join(d, stem + ".bin"), "wb") as f:
        f.write(np.array([0x33544E4D, len(groups)], dtype=np.uint32).tobytes())
        for g in groups:
            pos, loops, sizes, normals, W = g[:5]
            comp = g[5] if len(g) > 5 else None
            if comp is not None and comp.max(initial=0) <= 1e-3:
                comp = None
            thin = g[6] if len(g) > 6 else None
            if thin is not None and thin.max(initial=0) <= 1e-3:
                thin = None
            starts = np.concatenate([[0], np.cumsum(sizes)[:-1]]).astype(np.int64)
            # every face as a fan of triangles from its first corner
            parts = []
            for k in range(3, int(sizes.max()) + 1):
                sel = starts[sizes >= k]
                parts.append(np.stack([loops[sel], loops[sel + k - 2], loops[sel + k - 1]], axis=1))
            tris = np.concatenate(parts).astype(np.uint32)
            nm = 0 if W is None else len(W)
            f.write(np.array([len(pos), tris.size, nm, (0 if comp is None else 1) | (0 if thin is None else 2)],
                             dtype=np.uint32).tobytes())
            f.write(np.asarray(pos, dtype=np.float32).tobytes())
            f.write(np.asarray(normals, dtype=np.float32).tobytes())
            f.write(tris.tobytes())
            if nm:
                f.write(W.transpose(0, 2, 1).astype(np.float32).tobytes())
            if comp is not None:
                f.write(np.asarray(comp, dtype=np.float32).tobytes())
            if thin is not None:
                f.write(np.asarray(thin, dtype=np.float32).tobytes())
    return stem


def view_file(name):
    from . import rain
    name = os.path.basename(name or "")
    if not name.startswith("mantle_") or not name.endswith(".bin"):
        return ""
    p = os.path.join(rain._shelter_dir(), name)
    return p if os.path.isfile(p) else ""


def update(force=False, wait=True):
    """The mantle follows the scene and the settings. True when it changed. When only the sculpted snow changed
    (snowsculpt), the heights, the models and the distributions of the last time are kept: only the sheet is made
    again (a stroke costs a fraction of a second)."""
    from . import rain, snowsculpt
    st = settings()
    if st is None:
        HIDE["on"] = False      # (no snow any more: «Nascondi la neve» ends with it)
        press_update()          # (no snow: the pressed copies stand again)
        M["dirty"] = False
        M["changes"] = rain._STATE["changes"]
        changed = remove() or M["meta"] is not None
        M.update(meta=None, sig=None, cam=None)
        return changed
    if HIDE["on"]:
        return False            # (hidden: made again when shown - set_hidden)
    if not force and not due(wait):
        return False
    M["dirty"] = False
    M["changes"] = rain._STATE["changes"]
    from . import camview
    cam = None
    if camview.on("snow"):
        now = camview.camera()
        cam = M["cam"] if (M.get("cam") is not None and not camview.moved(M["cam"], now)) else now
    ckey = "-" if cam is None else repr(tuple(round(float(x), 2) for x in list(cam["pos"]) + list(cam["target"])
                                              + [cam["lens"], cam["aspect"]]))
    press_update()              # (1.79.0) the copies pressed by the sculpted snow: their mantles go with them
    base = str(_signature(st)) + f"/p{PRESS['rev']}"
    sig = f"{base}/{snowsculpt.rev()}/{ckey}"
    ob = _object()
    if M["sig"] == sig and M["meta"] is not None and (ob is None or ob.get("simpler_mantle_sig") == sig):
        M["cam"] = cam
        return False
    keep = (_CACHE["base"] == base and _CACHE.get("cam") == ckey and _CACHE["groups"] is not None
            and sum(1 for o in bpy.context.scene.objects if o.get(PART_KEY)) == _CACHE["nparts"])
    M["cam"] = cam
    try:
        made = _build(st, keep, cam, base)
    except Exception as exc:
        log(f"SIMPLER_SNOW mantle failed: {exc}")
        made = None
        keep = False
        _CACHE.update(field=None, shells=[])
    if keep:
        parts, pgroups = _CACHE["parts"], _CACHE["groups"]
    else:
        parts = []
        try:
            t0 = time.time()
            parts = _scatter_shells(st, limits(st[9])[1], cam)
            if parts:
                log(f"SIMPLER_SNOW distributions: {len(parts)} mantles for {sum(len(w) for _m, w in parts)} copies, "
                    f"{time.time() - t0:.2f} s")
        except Exception as exc:
            log(f"SIMPLER_SNOW distributions failed: {exc}")
        _remove_parts()
        pgroups = _part_objects(parts) if parts else []
        _CACHE.update(base=base, cam=ckey, parts=parts, groups=pgroups,
                      nparts=sum(1 for o in bpy.context.scene.objects if o.get(PART_KEY)))
    M["sig"] = sig
    if made is None and not parts:
        changed = remove() or M["meta"] is not None
        M["meta"] = None
        return changed
    np = _np()
    groups = []
    if made is not None:
        pos, loops, sizes, comp, thin = made
        me = _mesh(pos, loops, sizes, _material(), comp, thin)
        if ob is None:
            ob = bpy.data.objects.new(MAT_NAME, me)
            ob[MANTLE_KEY] = True
            ob[INTERNAL_KEY] = 1
            bpy.context.scene.collection.objects.link(ob)
            ob.hide_select = True
        else:
            old = ob.data
            ob.data = me
            if old is not None and old.users == 0:
                bpy.data.meshes.remove(old)
        nrm = np.empty(len(pos) * 3, dtype=np.float32)
        me.vertex_normals.foreach_get("vector", nrm)
        groups.append((pos, loops, sizes, nrm.reshape(-1, 3), None, comp, thin))
    else:
        ob = _object()
        if ob is not None:
            me = ob.data
            bpy.data.objects.remove(ob, do_unlink=True)
            if me is not None and me.users == 0:
                bpy.data.meshes.remove(me)
        ob = None
    groups += pgroups
    verts = sum(len(g[0]) for g in groups)
    if ob is not None:
        ob["simpler_mantle_sig"] = sig
    M["rev"] += 1
    stem = _write_view(groups)
    M["meta"] = {"rev": M["rev"], "file": stem + ".bin", "vertices": int(verts), "cell": _LAST["cell"],
                 "secs": _LAST["secs"], "heavy": verts > HEAVY, "shells": _LAST["shells"],
                 "shellVerts": _LAST["shell_verts"], "scatter": len(parts),
                 "copies": int(sum(len(w) for _m, w in parts)), "sculpt": snowsculpt.present()}
    return True


def set_detail(ids, value):
    """POST rain/snowdetail {ids, value: auto | high | low}: how the mantle of these models is made."""
    from .core import find
    from . import rain
    for i in ids:
        ob = find(i)
        if value in ("high", "low"):
            ob[DETAIL_KEY] = value
        elif DETAIL_KEY in ob:
            del ob[DETAIL_KEY]
        for o in ob.children_recursive:              # (the model decides as a whole)
            if DETAIL_KEY in o:
                del o[DETAIL_KEY]
    rain.touch()
    touch()
    return {}


def set_flag(ids, value):
    """POST rain/nomantle {ids, value}: «Senza mantello» on these objects and on the pieces inside them."""
    from .core import find
    from . import rain
    from .core import with_trees
    for o in with_trees([find(i) for i in ids]):     # (children_recursive per object: slow on big selections)
        if value:
            o[NO_MANTLE_KEY] = 1
        elif NO_MANTLE_KEY in o:
            del o[NO_MANTLE_KEY]
    if not value:
        for o in rain.ancestors([find(i) for i in ids]):
            if NO_MANTLE_KEY in o:
                del o[NO_MANTLE_KEY]     # (see rain.ancestors)
    rain.touch()
    touch()
    return {}


class aside:
    """Saving the project: the mantle is not written (it is made again when the project is opened); the sculpted
    snow is (snowsculpt.flush)."""

    def __enter__(self):
        from . import snowsculpt
        snowsculpt.flush()          # (the sculpted snow is kept in the project: written now)
        # (the objects out of the scene and their meshes off them: a data-block nobody uses is not written)
        self.items = []
        # (the flakes that fall: out of the scene while saving, back after - made again at every opening)
        from .snowfall import FALL_KEY
        from .raindrops import DROP_KEY
        self.flakes = []
        for o in [o for o in bpy.context.scene.objects if o.get(FALL_KEY) or o.get(DROP_KEY)]:
            empty = bpy.data.pointclouds.new("Simpler Fiocchi (vuoto)")
            self.flakes.append((o, o.data, empty))
            o.data = empty              # (the flakes themselves used by nothing: not written)
            for c in list(o.users_collection):
                c.objects.unlink(o)
        for ob in [o for o in bpy.context.scene.objects if o.get(MANTLE_KEY) or o.get(PART_KEY)]:
            empty = bpy.data.meshes.new(MAT_NAME + " (vuoto)")
            self.items.append((ob, ob.data, empty, list(ob.modifiers)))
            for md in list(ob.modifiers):
                md.show_viewport = md.show_render = False
            ob.data = empty
            for c in list(ob.users_collection):
                c.objects.unlink(ob)
        return self

    def __exit__(self, *exc):
        for o, pc, empty in getattr(self, "flakes", []):
            try:
                o.data = pc
                bpy.context.scene.collection.objects.link(o)
                bpy.data.pointclouds.remove(empty)
            except (ReferenceError, RuntimeError):
                pass
        for ob, me, empty, mods in self.items:
            try:
                ob.data = me
                for md in mods:
                    md.show_viewport = md.show_render = True
                bpy.context.scene.collection.objects.link(ob)
                bpy.data.meshes.remove(empty)
            except (ReferenceError, RuntimeError):
                pass
        return False


def after_open():
    """A project just opened: a mantle kept in the file (none should be) away, made again when needed."""
    remove()
    M.update(sig=None, meta=None, dirty=True, changes=-1, cam=None)
    _TRIS.update(sig=None, obs={})
    _SHELL_CACHE.update(key=None, items={})
    if HIDE["on"]:
        _show_objects(False)    # (an undo that loads a copy of the scene: the snow stays hidden)
    from . import snowsculpt
    snowsculpt.after_open()
    from . import snowfall, raindrops, ripples
    snowfall.after_open()
    raindrops.after_open()
    ripples.after_open()
