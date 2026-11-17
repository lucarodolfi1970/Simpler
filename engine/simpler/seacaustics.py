"""Caustics of the sea (1.74.0): the net of light the waves draw on a shallow bottom, and the light they throw on
the rocks around - with «Luce riflessa dall'acqua» (the same switch as the pools, refcaustics).

Cycles cannot draw them on the sea: its sharp caustics (MNEE) need a plain glass surface, one bounce and smooth real
geometry (tried on the sea: no net, a darker bottom, black lines). So they are computed here from the light, as
refcaustics does for the light reflected by pools, and given to the same images and the same shading.

Where: the clear shallow water the camera sees (the bottom visible: depth up to the clarity of the water), up to a
distance (VIEW/FINAL_DIST) - a rectangle on the sea. In it a grid of points (spacing from the budget of points, never
finer than MIN_STEP): for each one
  - the surface: the slopes of the simulated waves (the tile of ocean._slopes, scaled down in the shallow water as
    the geometry is) + the short waves (ocean._detail): its normal;
  - the sun seen from there (a ray: the cliff's shadow on the water);
  - refraction into the water (Snell, 1.333; Fresnel transmission), a ray to the bottom: the light lost on the way
    in the water (its colour, the same absorption as the material's volume);
  - reflection (Fresnel reflectance) up to the rocks within reach.
Each lit triangle of the grid sends its power to the triangle its three rays draw on the bottom (refcaustics._land):
where neighbouring triangles fold onto a small area the light concentrates - the bright lines. The sun's size blurs
them with the depth, as in reality.

Inside the rectangle the sea stops the sun's own shadow rays (ocean.set_caustic_area): its light reaches the bottom
only as the caustics - no light counted twice. The sky's light passes as before.

Cost: ~3 rays per point, only when the sun, the sea or what is near it change, or the camera looks at another part
of the shore (the rectangle, rounded to whole metres). View: VIEW_POINTS, final render: FINAL_POINTS.
"""
import math
import os
import time

import bpy
import numpy as np
from mathutils import Vector

from .core import log
from .i18n import tr

VIEW_POINTS = 160_000
FINAL_POINTS = 1_000_000
MIN_STEP_VIEW = 0.03            # metres between the points of the grid at most (the view)
MIN_STEP_FINAL = 0.015
VIEW_DIST = 25.0                # how far from the camera the shore is lit by its caustics (farther: the net is finer than a pixel)
FINAL_DIST = 40.0
REACH = 40.0                    # the light reflected by the sea, followed up to here
BREAK = 0.78
STATE = {"rect": None, "points": 0, "step": 0.0, "feather": 0.5}


def feather_of(rect):
    """(1.75.12) Metres over which the caustics fade into the even light at the border of their area: the same in
    the bottom's image and in the sea's shader (ocean.set_caustic_area) - no line across the water."""
    x0, y0, x1, y1 = rect
    return float(min(6.0, max(1.5, 0.15 * min(x1 - x0, y1 - y0))))


def _ocean():
    from . import ocean
    ob = ocean._find()
    if ob is None or ob.hide_render or ob.get("simpler_trashed"):
        return None
    s = ocean.settings(ob)
    if not s["coast"] or not s["shallow"] or s["height"] <= 0:
        return None          # (no clear shallow water: the bottom is not seen, no caustics to show)
    return ob


ENABLED = True                  # (1.75.2: on - the bottom from a render of Cycles, see _cycles_bottom)
CYCLES_BOTTOM = True            # the bottom's caustics: a small render of Cycles of real water (False: the rays below)
PATCH_VIEW = 600_000            # points of the water surface of that render: view / final render
PATCH_FINAL = 2_500_000
PATCH_STEP_VIEW, PATCH_STEP_FINAL = 0.03, 0.02     # metres between them at most
BOTTOM_PX_VIEW, BOTTOM_PX_FINAL = 1024, 1536      # the image of the bottom's light (long side)
BOTTOM_SAMPLES_VIEW, BOTTOM_SAMPLES_FINAL = 16, 64
DEPTH_STEP = 0.15               # metres between the depths measured (water or land, the waves lower in shallow water)
TMP_SCENE = "Simpler Caustiche del mare"
CAUSTIC_MIN_WAVE = 0.25         # metres: the waves shorter than this are left out of the water that makes the net
                                # (1.75.8: they only cut it into a grain of cells of a few centimetres; the net of the
                                # sea seen from a few metres is made of cells of a palm or two)
CAUSTIC_GAIN = 3.0


def active():
    return ENABLED and _ocean() is not None


def _region(final):
    """The rectangle of shallow clear water the camera sees, rounded to whole metres; None: none."""
    from . import ocean
    ob = _ocean()
    cam = bpy.context.scene.camera
    if ob is None or cam is None or ocean._COAST["d"] is None:
        return None
    me = ob.data
    n = len(me.vertices)
    d = ocean._COAST["d"]
    if len(d) != n:
        return None
    s = ocean.settings(ob)
    dc = ocean.CLARITY[s["color"]][0] * s["clarity"]
    rest = np.empty(n * 3, np.float32)
    me.attributes["simpler_rest"].data.foreach_get("vector", rest)
    rest = rest.reshape(-1, 3).astype(np.float64)
    rest[:, 2] = s["level"]
    sel = (d > -0.3) & (d < dc)
    if not sel.any():
        return None
    P = rest[sel]
    from mathutils import Matrix
    # (1.75.3) from its location and rotation: matrix_world is only brought up to date by the next depsgraph update,
    # and the camera was just placed for this view (render.apply_camera) - the rectangle was the one of the view before
    mw = cam.matrix_world if cam.parent else Matrix.LocRotScale(cam.location, cam.rotation_euler, Vector((1, 1, 1)))
    m = np.array(mw.inverted(), np.float64)
    v = P @ m[:3, :3].T + m[:3, 3]
    z = -v[:, 2]
    half = math.tan(max(cam.data.angle, 0.1) / 2.0) * 1.25
    vis = (z > 0.1) & (np.abs(v[:, 0]) < z * half) & (np.abs(v[:, 1]) < z * half)
    vis &= np.linalg.norm(v, axis=1) < (FINAL_DIST if final else VIEW_DIST)
    if not vis.any():
        return None
    P = P[vis]
    pad = 1.0
    x0, y0 = math.floor(P[:, 0].min() - pad), math.floor(P[:, 1].min() - pad)
    x1, y1 = math.ceil(P[:, 0].max() + pad), math.ceil(P[:, 1].max() + pad)
    # (1.75.12) the fading border outside what is seen in full: the caustics whole up to the edge of the area seen
    f = feather_of((x0, y0, x1, y1))
    return (float(math.floor(x0 - f)), float(math.floor(y0 - f)), float(math.ceil(x1 + f)), float(math.ceil(y1 + f)))


def fingerprint(final):
    """For refcaustics._fingerprint: what makes the caustics of the sea change."""
    from . import ocean
    ob = _ocean()
    if ob is None:
        return None
    return (ob.get(ocean.REV_KEY, ""), _region(final), bool(final))


def _sample(field, S, x, y):
    """Bilinear sample of a periodic field (N, N, 2: [y, x]) of side S at the points (x, y)."""
    N = field.shape[0]
    u = np.mod(x / S, 1.0) * N - 0.5
    v = np.mod(y / S, 1.0) * N - 0.5
    i0 = np.floor(u).astype(np.int64); j0 = np.floor(v).astype(np.int64)
    fu = (u - i0)[:, None]; fv = (v - j0)[:, None]
    i0 %= N; j0 %= N
    i1 = (i0 + 1) % N; j1 = (j0 + 1) % N
    return ((field[j0, i0] * (1 - fu) + field[j0, i1] * fu) * (1 - fv)
            + (field[j1, i0] * (1 - fu) + field[j1, i1] * fu) * fv)


def trace(suns, final, progress, transmit=True):
    """The light of the sea: (traced dict as refcaustics._trace gives, ray count, owners, offsets) or None.
    transmit False: only the light reflected by the sea (the bottom comes from _cycles_bottom)."""
    from . import ocean, refcaustics as rc
    ob = _ocean()
    rect = _region(final)
    STATE.update(rect=rect, points=0)
    if ob is None or rect is None or not suns:
        return None
    x0, y0, x1, y1 = rect
    area = (x1 - x0) * (y1 - y0)
    budget = FINAL_POINTS if final else VIEW_POINTS
    step = max(MIN_STEP_FINAL if final else MIN_STEP_VIEW, math.sqrt(area / budget))
    # the waves the grid can follow (4 points a wave at least); the ripples shorter than that blur the net instead
    f = ocean.caustic_fields(4.0 * step)
    if f is None:
        return None
    rough = 0.5 * math.sqrt(f["left"])
    nx, ny = int(math.ceil((x1 - x0) / step)) + 1, int(math.ceil((y1 - y0) / step)) + 1
    xs = x0 + np.arange(nx) * step; ys = y0 + np.arange(ny) * step
    X, Y = np.meshgrid(xs, ys, indexing="xy")
    X = X.ravel(); Y = Y.ravel()
    level = f["level"]
    co = np.stack([X, Y, np.full(len(X), level)], axis=1)
    i = np.arange((ny - 1) * (nx - 1))
    r_, c_ = i // (nx - 1), i % (nx - 1)
    a = r_ * nx + c_
    tri = np.concatenate([np.stack([a, a + 1, a + nx + 1], 1), np.stack([a, a + nx + 1, a + nx], 1)])
    STATE.update(points=len(co), step=step)
    # what the light meets: the bottom and the rocks around (refcaustics' BVH, on this rectangle)
    lo = Vector((x0, y0, level - 60.0)); hi = Vector((x1, y1, level + 5.0))
    bvh, owners, offsets = rc._blockers_box(lo, hi, 10_000_000 if final else 3_000_000)
    if bvh is None:
        return None
    ray_cast = bvh.ray_cast
    n = len(co)
    progress(tr("Caustiche del mare: fondale"), "", 0.0)
    # the depth under every point (a ray down: the bottom, facing up; none - land or too deep - no light)
    depth = np.full(n, np.inf)
    down = Vector((0.0, 0.0, -1.0))
    dmax = f["dc"] * 1.5 + f["H"]
    for k in range(n):
        loc, nrm, _idx, dist = ray_cast(Vector((X[k], Y[k], level + 0.02)), down, dmax)
        if loc is not None and nrm.z > 0.0:
            depth[k] = dist - 0.02
    wet = np.isfinite(depth) & (depth > 0.0)
    # the surface's slopes: the simulated waves (fewer where the waves feel the bottom, as ocean._weights) + the
    # short waves
    H = max(f["H"], 1e-3)
    allow = np.clip(BREAK * np.where(wet, depth, 0.0) / H, 0.0, 1.0)
    allow = allow * allow * (3 - 2 * allow)
    allow = np.maximum(allow, 0.35)
    sl = _slopes(f, X, Y, allow)
    no = np.stack([-sl[:, 0], -sl[:, 1], np.ones(n)], axis=1)
    no /= np.linalg.norm(no, axis=1, keepdims=True)
    ext = f["ext"]
    acc = ([], [], [], [], [])
    rays = n
    for em in suns:
        col = np.array(em.data.color[:3], np.float64) * float(em.data.energy)
        sdir = np.array((em.matrix_world.to_quaternion() @ Vector((0.0, 0.0, 1.0))).normalized(), np.float64)
        if sdir[2] <= 0.02:
            continue
        spread = math.tan(max(float(em.data.angle), 1e-4) / 2.0) + rough
        cos_i = np.clip(no @ sdir, 0.0, 1.0)
        eta = 1.0 / rc.IOR
        cos_t = np.sqrt(np.maximum(0.0, 1.0 - eta * eta * (1.0 - cos_i * cos_i)))
        tdir = -eta * sdir[None, :] + (eta * cos_i - cos_t)[:, None] * no
        tdir /= np.linalg.norm(tdir, axis=1, keepdims=True)
        rdir = -sdir[None, :] + 2.0 * cos_i[:, None] * no
        rdir /= np.linalg.norm(rdir, axis=1, keepdims=True)
        lit = np.zeros(n, bool)
        thit = np.full((n, 3), np.nan); thn = np.zeros((n, 3)); thd = np.zeros(n); tidx = np.full(n, -1, np.int64)
        rhit = np.full((n, 3), np.nan); rhn = np.zeros((n, 3)); rhd = np.zeros(n); ridx = np.full(n, -1, np.int64)
        sv = Vector(sdir)
        stepn = max(2000, n // 40)
        for k in range(n):
            if k % stepn == 0:
                progress(tr("Caustiche del mare: raggi"), f"{k * 100 // n}%", k / n)
            if not wet[k] or cos_i[k] <= 0.0:
                continue
            p = Vector(co[k])
            rays += 1
            if ray_cast(p + Vector((0.0, 0.0, 0.01)), sv, 500.0)[0] is not None:
                continue                                   # (in the shadow of the cliff)
            lit[k] = True
            if transmit:
                rays += 1
                tv = Vector(tdir[k])
                loc, nrm, idx, dist = ray_cast(p - Vector((0.0, 0.0, 0.01)), tv, depth[k] * 4.0 + 1.0)
                if loc is not None:
                    if nrm.dot(tv) > 0.0:
                        nrm = -nrm
                    thit[k] = loc; thn[k] = nrm; thd[k] = dist; tidx[k] = idx
            if rdir[k][2] > 0.0:
                rays += 1
                rv = Vector(rdir[k])
                loc, nrm, idx, dist = ray_cast(p + Vector((0.0, 0.0, 0.01)), rv, REACH)
                if loc is not None:
                    if nrm.dot(rv) > 0.0:
                        nrm = -nrm
                    rhit[k] = loc; rhn[k] = nrm; rhd[k] = dist; ridx[k] = idx
        a0, b0, c0 = tri[:, 0], tri[:, 1], tri[:, 2]
        tarea = np.full(len(tri), 0.5 * step * step)
        nmean = no[a0] + no[b0] + no[c0]
        nmean /= np.linalg.norm(nmean, axis=1, keepdims=True)
        cmean = np.clip(nmean @ sdir, 0.0, 1.0)
        R = rc._fresnel(cmean, rc.IOR)
        litf = (lit[a0].astype(float) + lit[b0] + lit[c0]) / 3.0
        base = tarea * sdir[2] * litf                    # (the sun's light on the flat rectangle: area x cos)
        dist_t = (thd[a0] + thd[b0] + thd[c0]) / 3.0
        att = np.exp(-np.outer(dist_t, ext))
        rc._land(acc, co, tri, thit, thn, thd, tidx, (base * (1.0 - R))[:, None] * att * col[None, :], thd * spread,
                 col, offsets)
        rc._land(acc, co, tri, rhit, rhn, rhd, ridx, (base * R)[:, None] * col[None, :], rhd * spread, col, offsets)
    P, N, F, B, O = acc
    if not P:
        return None
    log("SIMPLER_SEACAUSTICS", f"{n} points, step {step * 100:.1f} cm, area {area:.0f} m2, rays {rays}")
    return ({"P": np.concatenate(P), "N": np.concatenate(N), "F": np.concatenate(F), "B": np.concatenate(B),
             "O": np.concatenate(O)}, rays, owners, offsets)


# ---------------------------------------------------------------- the waves (both the rays and the render of Cycles)

MIX = ((1.0, 0.0, 0.0, 0.0, 0.0), (0.66, 0.73, 0.83, 3.1, 7.7))
"""The short waves: their tile (a few metres) twice, the second smaller, turned and shifted - its repetition never
lines up on the shore (one tile alone drew the same net every few metres). (weight, scale, angle, dx, dy); weights
squared add up to ~1: the same slopes on average."""


def _short(f, X, Y, field):
    """The short waves at (X, Y) from a field of their tile (slopes or heights), mixed as MIX says."""
    out = 0.0
    for w, sc, ang, dx, dy in MIX:
        if sc == 0.0:
            out = out + w * _sample(field, f["L"], X, Y)
            continue
        c, sn = math.cos(ang), math.sin(ang)
        u = (c * X - sn * Y) * sc + dx
        v = (sn * X + c * Y) * sc + dy
        val = _sample(field, f["L"], u, v)
        if val.shape[1] == 2:            # slopes: the chain rule (scaled and turned back)
            gx, gy = val[:, 0] * sc, val[:, 1] * sc
            val = np.stack([c * gx + sn * gy, -sn * gx + c * gy], 1)
        out = out + w * val
    return out


def _slopes(f, X, Y, allow):
    return _sample(f["geo"], f["S"], X, Y) * allow[:, None] + _short(f, X, Y, f["det"])


def _heights_of(field, S):
    """Heights (N, N, 1) of a periodic field of slopes (N, N, 2: dz/dx, dz/dy, [y, x]) of side S: by its spectrum."""
    N = field.shape[0]
    k = 2.0 * math.pi * np.fft.fftfreq(N, d=S / N)
    KX, KY = np.meshgrid(k, k, indexing="xy")
    sx = np.fft.fft2(field[..., 0]); sy = np.fft.fft2(field[..., 1])
    k2 = KX * KX + KY * KY
    k2[0, 0] = 1.0
    h = np.real(np.fft.ifft2(-1j * (KX * sx + KY * sy) / k2))
    return (h - h.mean())[..., None]


_HEIGHTS = {"key": None}


def _heights(f):
    key = (id(f["geo"]), id(f["det"]), f["S"], f["L"])
    if _HEIGHTS["key"] != key:
        _HEIGHTS.update(key=key, geo=_heights_of(f["geo"], f["S"]), det=_heights_of(f["det"], f["L"]))
    return _HEIGHTS["geo"], _HEIGHTS["det"]


# ---------------------------------------------------------------- the bottom: a render of Cycles

def _depths(rect, level, bvh, step):
    """Depth of the bottom under a coarse grid of the rectangle (m; -1: land or nothing): (array [y, x], xs, ys)."""
    x0, y0, x1, y1 = rect
    xs = np.arange(x0, x1 + step, step); ys = np.arange(y0, y1 + step, step)
    D = np.full((len(ys), len(xs)), -1.0)
    down = Vector((0.0, 0.0, -1.0))
    for j, y in enumerate(ys):
        for i, x in enumerate(xs):
            loc, nrm, _idx, dist = bvh.ray_cast(Vector((x, y, level + 0.02)), down, 80.0)
            if loc is not None and nrm.z > 0.0:
                D[j, i] = dist - 0.02
    return D, xs, ys


def _bilinear(D, xs, ys, X, Y):
    fx = np.clip((X - xs[0]) / (xs[1] - xs[0]), 0, len(xs) - 1.001)
    fy = np.clip((Y - ys[0]) / (ys[1] - ys[0]), 0, len(ys) - 1.001)
    i0 = fx.astype(np.int64); j0 = fy.astype(np.int64)
    tx = fx - i0; ty = fy - j0
    return ((D[j0, i0] * (1 - tx) + D[j0, i0 + 1] * tx) * (1 - ty)
            + (D[j0 + 1, i0] * (1 - tx) + D[j0 + 1, i0 + 1] * tx) * ty)


def _water_patch(rect, f, D, xs, ys, final):
    """The surface of the sea in the rectangle as real geometry (the same waves the material draws): a mesh."""
    x0, y0, x1, y1 = rect
    area = (x1 - x0) * (y1 - y0)
    step = max(PATCH_STEP_FINAL if final else PATCH_STEP_VIEW, math.sqrt(area / (PATCH_FINAL if final else PATCH_VIEW)))
    if os.environ.get("SIMPLER_SEA_FAST"):
        step = max(step, float(os.environ["SIMPLER_SEA_FAST"].split(",")[2]))
    nx, ny = int(math.ceil((x1 - x0) / step)) + 1, int(math.ceil((y1 - y0) / step)) + 1
    X, Y = np.meshgrid(x0 + np.arange(nx) * step, y0 + np.arange(ny) * step, indexing="xy")
    X = X.ravel(); Y = Y.ravel()
    depth = _bilinear(D, xs, ys, X, Y)
    H = max(f["H"], 1e-3)
    allow = np.clip(BREAK * np.maximum(depth, 0.0) / H, 0.0, 1.0)
    allow = allow * allow * (3 - 2 * allow)
    allow = np.maximum(allow, 0.35)
    hg, hd = _heights(f)
    z = f["level"] + _sample(hg, f["S"], X, Y)[:, 0] * allow + _short(f, X, Y, hd)[:, 0]
    # in very shallow water the waves never go below the bottom (they would cut it and shade it)
    z = np.maximum(z, f["level"] - np.maximum(depth, 0.0) * 0.6)
    keep = depth > -0.05
    idx = -np.ones(nx * ny, np.int64)
    idx[keep] = np.arange(int(keep.sum()))
    g = idx.reshape(ny, nx)
    a, b, c, d = g[:-1, :-1], g[:-1, 1:], g[1:, 1:], g[1:, :-1]
    ok = (a >= 0) & (b >= 0) & (c >= 0) & (d >= 0)
    quads = np.stack([a[ok], b[ok], c[ok], d[ok]], 1)
    co = np.stack([X[keep], Y[keep], z[keep]], 1).astype(np.float32)
    me = bpy.data.meshes.new(TMP_SCENE + " · acqua")
    me.vertices.add(len(co)); me.vertices.foreach_set("co", co.ravel())
    me.loops.add(quads.size); me.loops.foreach_set("vertex_index", quads.ravel().astype(np.int32))
    me.polygons.add(len(quads)); me.polygons.foreach_set("loop_start", np.arange(0, quads.size, 4, dtype=np.int32))
    me.update(calc_edges=True)
    me.polygons.foreach_set("use_smooth", np.ones(len(quads), bool))
    return me, step, len(co)


def _receivers(rect, level):
    """The pieces of the scene in the rectangle that can be under the sea."""
    from .core import INTERNAL_KEY
    x0, y0, x1, y1 = rect
    out = []
    for ob in bpy.context.scene.objects:
        if ob.type != "MESH" or ob.hide_render or ob.get("simpler_trashed") or ob.get(INTERNAL_KEY) \
                or ob.get("simpler_twin") or ob.get("simpler_water_body") or ob.get("simpler_ocean"):
            continue
        pts = [ob.matrix_world @ Vector(c) for c in ob.bound_box]
        a = Vector(map(min, *pts)); b = Vector(map(max, *pts))
        if a.x <= x1 and b.x >= x0 and a.y <= y1 and b.y >= y0 and a.z <= level:
            out.append(ob)
    return out


def _cycles_bottom(sun, final, bvh, progress):
    """The light of the sun on the shallow bottom through the waves, drawn by Cycles: in a scene of its own the
    surface of the sea as real water (MNEE caustics, the same as a pool), the bottom white, seen from above.
    Returns the image for refcaustics ((H, W, 4) W/m2 + depth, u0, v0, texel, d0, d1), the receivers, or None."""
    import tempfile
    from . import ocean, render
    rect = _region(final)
    f = ocean.caustic_fields(CAUSTIC_MIN_WAVE)
    if rect is None or f is None or sun is None:
        return None
    sdir = (sun.matrix_world.to_quaternion() @ Vector((0.0, 0.0, 1.0))).normalized()
    if sdir.z <= 0.05:
        return None
    t0 = time.time()
    level = f["level"]
    progress(tr("Caustiche del mare: fondale"), "", 0.0)
    D, xs, ys = _depths(rect, level, bvh, DEPTH_STEP)
    if not (D > 0).any():
        return None
    obs = _receivers(rect, level)
    if not obs:
        return None
    main = bpy.context.scene
    old = bpy.data.scenes.get(TMP_SCENE)
    if old is not None:
        _cleanup(old)
    sc = bpy.data.scenes.new(TMP_SCENE)
    made = {"objects": [], "meshes": [], "materials": [], "lights": [], "cameras": [], "worlds": []}
    try:
        white = bpy.data.materials.new(TMP_SCENE + " · bianco"); made["materials"].append(white)
        white.use_nodes = True
        nt = white.node_tree; nt.nodes.clear()
        dif = nt.nodes.new("ShaderNodeBsdfDiffuse"); dif.inputs["Color"].default_value = (1, 1, 1, 1)
        out = nt.nodes.new("ShaderNodeOutputMaterial"); nt.links.new(dif.outputs[0], out.inputs["Surface"])
        wat = bpy.data.materials.new(TMP_SCENE + " · acqua"); made["materials"].append(wat)
        wat.use_nodes = True
        nt = wat.node_tree; nt.nodes.clear()
        gl = nt.nodes.new("ShaderNodeBsdfGlass"); gl.inputs["IOR"].default_value = 1.333
        gl.inputs["Roughness"].default_value = 0.0; gl.inputs["Color"].default_value = (1, 1, 1, 1)
        out = nt.nodes.new("ShaderNodeOutputMaterial"); nt.links.new(gl.outputs[0], out.inputs["Surface"])
        for ob in obs:
            c = ob.copy()
            c.parent = None
            c.matrix_world = ob.matrix_world.copy()
            for sl in c.material_slots:
                sl.link = "OBJECT"
                sl.material = white
            c.cycles.is_caustics_receiver = True
            c.cycles.is_caustics_caster = False
            sc.collection.objects.link(c); made["objects"].append(c)
        me, step, npts = _water_patch(rect, f, D, xs, ys, final); made["meshes"].append(me)
        me.materials.append(wat)
        pw = bpy.data.objects.new(TMP_SCENE + " · acqua", me); made["objects"].append(pw)
        pw.cycles.is_caustics_caster = True; pw.cycles.is_caustics_receiver = False
        pw.visible_camera = False      # (the bottom seen straight: the light where it lands)
        sc.collection.objects.link(pw)
        ld = bpy.data.lights.new(TMP_SCENE + " · sole", "SUN"); made["lights"].append(ld)
        ld.energy = 1.0; ld.color = (1, 1, 1); ld.angle = sun.data.angle
        ld.cycles.is_caustics_light = True
        lo_ = bpy.data.objects.new(TMP_SCENE + " · sole", ld); made["objects"].append(lo_)
        lo_.matrix_world = sun.matrix_world.copy()
        sc.collection.objects.link(lo_)
        x0, y0, x1, y1 = rect
        w, h = x1 - x0, y1 - y0
        cd = bpy.data.cameras.new(TMP_SCENE); made["cameras"].append(cd)
        cd.type = "ORTHO"; cd.ortho_scale = max(w, h); cd.clip_start = 0.1; cd.clip_end = 400.0
        co_ = bpy.data.objects.new(TMP_SCENE + " · camera", cd); made["objects"].append(co_)
        co_.location = ((x0 + x1) / 2, (y0 + y1) / 2, level + 100.0)
        sc.collection.objects.link(co_); sc.camera = co_
        wo = bpy.data.worlds.new(TMP_SCENE); made["worlds"].append(wo)
        wo.use_nodes = True
        bg = wo.node_tree.nodes.get("Background")
        if bg is not None:
            bg.inputs["Strength"].default_value = 0.0
        sc.world = wo
        px = BOTTOM_PX_FINAL if final else BOTTOM_PX_VIEW
        if os.environ.get("SIMPLER_SEA_FAST"):
            px = int(os.environ["SIMPLER_SEA_FAST"].split(",")[0])
        W = max(8, int(round(px * w / max(w, h)))); Hh = max(8, int(round(px * h / max(w, h))))
        r = sc.render
        r.engine = "CYCLES"; r.resolution_x, r.resolution_y, r.resolution_percentage = W, Hh, 100
        r.film_transparent = False
        r.use_persistent_data = False
        cy, mc = sc.cycles, main.cycles
        cy.device = mc.device
        cy.samples = BOTTOM_SAMPLES_FINAL if final else BOTTOM_SAMPLES_VIEW
        if os.environ.get("SIMPLER_SEA_FAST"):
            cy.samples = int(os.environ["SIMPLER_SEA_FAST"].split(",")[1])
        cy.use_adaptive_sampling = False
        cy.use_denoising = False
        cy.max_bounces = 4; cy.diffuse_bounces = 1; cy.glossy_bounces = 0   # (diffuse 0: Cycles gives no caustics)
        cy.transmission_bounces = 4; cy.transparent_max_bounces = 4; cy.volume_bounces = 0
        cy.caustics_refractive = True; cy.caustics_reflective = False
        cy.sample_clamp_direct = 0.0; cy.sample_clamp_indirect = 0.0
        cy.blur_glossy = 0.0
        cy.time_limit = 0.0
        sc.view_settings.view_transform = "Standard"; sc.view_settings.look = "None"
        sc.view_settings.exposure = 0.0; sc.view_settings.gamma = 1.0
        r.image_settings.file_format = "OPEN_EXR"; r.image_settings.color_depth = "32"
        r.image_settings.exr_codec = "ZIP"
        path = os.path.join(tempfile.gettempdir() if not getattr(render.STATE, "tmp", None) else render.STATE.tmp,
                            "seacaustics_bottom.exr")
        r.filepath = path
        progress(tr("Caustiche del mare: fondale"), "", 0.3)
        t1 = time.time()
        bpy.ops.render.render(write_still=True, scene=sc.name)
        t2 = time.time()
        im = bpy.data.images.load(path, check_existing=False)
        try:
            px_ = np.empty(im.size[0] * im.size[1] * 4, np.float32)
            im.pixels.foreach_get(px_)
        finally:
            bpy.data.images.remove(im)
        img = px_.reshape(Hh, W, 4)[:, :, :3].mean(2) * math.pi          # (white, seen from above: E = pi x L)
        # the same without the water: the sun straight on the bottom (only the shadows of the rocks). Cycles' caustics
        # keep the shape of the light but not all of it (measured: a seventh): on the lit bottom the light through
        # the waves must be on average what passes a flat surface - one factor for the whole image
        pw.hide_render = True
        r.resolution_percentage = 25
        cy.samples = 4
        path0 = path[:-4] + "_0.exr"
        r.filepath = path0
        bpy.ops.render.render(write_still=True, scene=sc.name)
        im = bpy.data.images.load(path0, check_existing=False)
        try:
            p0 = np.empty(im.size[0] * im.size[1] * 4, np.float32)
            im.pixels.foreach_get(p0)
            e0 = p0.reshape(im.size[1], im.size[0], 4)[:, :, :3].mean(2) * math.pi
        finally:
            bpy.data.images.remove(im)
        jj = np.minimum((np.arange(Hh) * e0.shape[0]) // Hh, e0.shape[0] - 1)
        ii = np.minimum((np.arange(W) * e0.shape[1]) // W, e0.shape[1] - 1)
        e0 = e0[jj][:, ii]
    finally:
        _cleanup(sc, made)
    texel = w / W
    U, V = np.meshgrid(x0 + (np.arange(W) + 0.5) * texel, y0 + (np.arange(Hh) + 0.5) * (h / Hh), indexing="xy")
    depth = _bilinear(D, xs, ys, U.ravel(), V.ravel()).reshape(Hh, W)
    # the light lost on its way down in the water (the same as the colour of the sea): along the refracted sun
    cos_t = math.sqrt(max(0.05, 1.0 - (1.0 - sdir.z * sdir.z) / (1.333 * 1.333)))
    att = np.exp(-np.maximum(depth, 0.0)[..., None] * (f["ext"][None, None, :] / cos_t))
    col = np.array(sun.data.color[:3], np.float64) * float(sun.data.energy)
    cos_i = max(0.05, sdir.z)
    lit = (depth > 0.05) & (e0 > 0.5 * cos_i)
    from .refcaustics import _fresnel
    T = 1.0 - float(_fresnel(np.array([cos_i]), 1.333)[0])
    k = float(np.clip(T * e0[lit].sum() / max(img[lit].sum(), 1e-6), 0.5, 20.0)) if lit.sum() > 100 else 1.0
    img = img * k
    if lit.any():
        # (1.75.8) the net as it is seen at sea: the light gathered into its lines CAUSTIC_GAIN times further from the
        # average (the average stays: the same light as without caustics). With the light of Cycles alone the net was
        # a faint grey grain seen through the waves (Luca, «Scene 7»: «only darker water»)
        m = float(img[lit].mean())
        img = np.maximum(0.0, m + (img - m) * CAUSTIC_GAIN)
    # (1.75.12) only the light the waves gather ABOVE the even sun: the sun is no longer held back under the sea
    # (refcaustics passes no area to ocean.set_caustic_area). Holding it back and putting it again as an image left
    # a seam at the border of the area and a dark band along the shore, where the bottom's image had nothing (Luca,
    # «Scena 1»: «un disastro»). Now the bright lines are added and the rest stays as without: nothing can get darker
    flat = T * e0
    img = np.maximum(0.0, img - flat)
    # the last centimetres at the shore: the lines fade out (the waves there cut into the sand in the patch)
    img *= np.clip((depth - 0.02) / 0.08, 0.0, 1.0)
    rgb = img[..., None] * att * col[None, None, :]
    rgb[depth <= 0.0] = 0.0
    # the border: the caustics fade out as the sea's shader lets the even sun in again (ocean.set_caustic_area)
    F = feather_of(rect)
    fx = np.clip((U - x0) / F, 0.0, 1.0) * np.clip((x1 - U) / F, 0.0, 1.0)
    fy = np.clip((V - y0) / F, 0.0, 1.0) * np.clip((y1 - V) / F, 0.0, 1.0)
    rgb *= (fx * fy)[..., None]
    zb = level - np.maximum(depth, 0.0)
    rgbd = np.concatenate([rgb, np.zeros((Hh, W, 1))], 2).astype(np.float32)
    d0 = float(level - max(0.5, float(D.max()) + 0.5))
    wet = depth > 0
    log("SIMPLER_SEACAUSTICS", f"bottom image: wet {wet.mean():.2f}, E wet mean {img[wet].mean() if wet.any() else 0:.3f} "
        f"p5 {np.percentile(img[wet], 5) if wet.any() else 0:.3f} p95 {np.percentile(img[wet], 95) if wet.any() else 0:.3f}, "
        f"sun z {sdir.z:.2f}, factor {k:.2f}")
    if os.environ.get("SIMPLER_SEA_FAST") or os.environ.get("SIMPLER_SEA_DUMP"):   # (development: kept for a look)
        np.save(os.path.join(os.path.dirname(path), "seacaustics_bottom.npy"), img)
    log("SIMPLER_SEACAUSTICS", f"bottom by Cycles: {W}x{Hh}, water {npts} points ({step * 100:.1f} cm), "
        f"{len(obs)} pieces, render {t2 - t1:.2f}s, all {time.time() - t0:.2f}s")
    STATE.update(rect=rect, feather=F)
    return (rgbd, x0, y0, texel, d0, float(level) - 0.005), {ob.name for ob in obs}


def _cleanup(sc, made=None):
    if made is None:
        made = {"objects": list(sc.collection.objects), "meshes": [], "materials": [], "lights": [], "cameras": [],
                "worlds": [sc.world] if sc.world else []}
        for ob in made["objects"]:
            if ob.type == "MESH" and ob.data.name.startswith(TMP_SCENE):
                made["meshes"].append(ob.data)
        made["materials"] = [m for m in bpy.data.materials if m.name.startswith(TMP_SCENE)]
    for ob in made["objects"]:
        try:
            bpy.data.objects.remove(ob, do_unlink=True)
        except ReferenceError:
            pass
    for coll, items in ((bpy.data.meshes, made["meshes"]), (bpy.data.materials, made["materials"]),
                        (bpy.data.lights, made["lights"]), (bpy.data.cameras, made["cameras"]),
                        (bpy.data.worlds, made["worlds"])):
        for it in items:
            try:
                coll.remove(it)
            except (ReferenceError, RuntimeError):
                pass
    try:
        bpy.data.scenes.remove(sc)
    except ReferenceError:
        pass
