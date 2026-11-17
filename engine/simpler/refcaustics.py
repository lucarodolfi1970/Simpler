"""Reflected caustics of water: the moving net of light that a pool, a canal or a fountain throws on the walls, the
underside of a bridge or a boat - sunlight reflected by the waves.

Cycles cannot draw it. Its sharp caustics (MNEE) handle only refraction: the net on the BOTTOM of a pool (shadow
caustics through the surface). Light reflected by a mirror-like surface onto a diffuse one can only be found by
chance by the path tracer (a ray from the wall must hit the tiny disc of the sun after the reflection): fireflies,
clamped away, nothing visible. So it is computed here, from the light (photon tracing), as a physical property of
the water: no setting per scene.

How: the surface of every water with real waves (water.py: the geometry the path tracer sees) is a mesh of small
triangles. For each vertex a ray goes to the sun (is it lit?) and, reflected with the smooth normal of the waves,
on into the scene (BVH of the objects near the water). Each lit triangle of water sends to where its three rays
land the power it receives from the sun (irradiance x area x cos) times the Fresnel reflectance of water (n = 1.333,
exact for that angle): the light of the triangle spreads over the triangle it draws on the wall. Where neighbouring
triangles fold onto a small area the light concentrates: those are the bright lines of the caustic, with no noise,
since the triangles are filled densely (many samples per triangle, numpy) rather than shot as random photons. The
size of the sun blurs them as in reality (farther walls: softer net).

The light collected (irradiance, W/m2) is stored in six projection images, one for each facing (+X -X +Y -Y +Z -Z,
EXR files, half float), over the area where the light arrived. The receiving materials get a small wrapper
(node group): Emission = base colour x irradiance / pi - what a matte surface under that light gives back. It also
lights the rest of the scene (it is light like any other for the path tracer).

Cost: two ray casts per vertex of water and the filling of the images, only when the sun, the water or the
objects near it change (cached). Real-time view: not shown (the light plane of the water has no waves). One
switch in the render settings (config "causticsReflected"), off by default.
"""
import math
import os
import shutil
import tempfile
import time

import bpy
import numpy as np
from mathutils import Vector

from .core import log
from .i18n import tr


def _progress(phase, detail="", fraction=None):
    try:
        from . import progress
        progress.viewport_phase(phase, detail, fraction)
    except Exception:
        pass

GROUP = "Simpler Reflected Caustics"
TAG = "simpler_refcaustics"
IMG_TAG = "simpler_refcaustics_img"
IOR = 1.333
REACH = 40.0            # metres: how far the reflected light is followed (and objects near the water considered)
MAX_PX = 2048           # final render (the view: VIEW_PX, a quarter of the texels and of the time)
VIEW_PX = 1024
MIN_TEXEL = 0.005       # metres
MAX_WATER_VERTS = 600_000  # final render: vertices x lights (about 2 rays each); the view: VIEW_WATER_VERTS
VIEW_WATER_VERTS = 80_000   # (~1 s of rays: the engine waits for it)
VIEW_LAMP_VERTS = 120_000   # vertices traced per lamp in the view (where its light is)
LAMP_SR_VIEW = 4e-4          # largest solid angle of a water triangle seen from a lamp (view / final render)
LAMP_SR_FINAL = 1e-4
MAX_SAMPLES = 12_000_000  # all the images of a final render (the view: a third)
AXES = [(0, 1.0), (0, -1.0), (1, 1.0), (1, -1.0), (2, 1.0), (2, -1.0)]
GLASS_LAYERS = 4          # (1.75.0) glass crossed by the sun on its way to the water (both faces of a pane count)
LAYERS = 4                # depth layers per facing: a wall, the columns in front of it, a step... each its own image
SLOTS = 6 * LAYERS
LAYER_GAP = 0.15          # metres along the facing between two layers
LAST = {"state": "off", "seconds": 0.0, "rays": 0, "receivers": 0, "when": 0.0}
_CACHE = {"key": None, "epoch": None, "receivers": set(), "dir": None, "kind": None}


def enabled():
    from .render import STATE
    return bool(STATE.config.get("causticsReflected", False))


def info():
    return dict(LAST)


# ---------------------------------------------------------------- scene reading

def _water_objects():
    from . import water
    out = []
    for ob in bpy.context.scene.objects:
        if ob.type != "MESH" or ob.get("simpler_trashed") or ob.hide_render or not ob.visible_get():
            continue
        wm = water.water_material(ob)
        if wm is not None and water.mat_settings(wm)["waves"]["on"] and ob.modifiers.get(water.MOD) is not None:
            out.append(water.grid_of(ob) or ob)        # (a large surface: its grid around the camera is the water)
    return out


def ocean_level():
    from . import ocean
    ob = ocean._find()
    return float(ocean.settings(ob)["level"]) if ob is not None else 0.0


def _suns():
    out = []
    for ob in bpy.context.scene.objects:
        if ob.type == "LIGHT" and ob.data.type == "SUN" and not ob.hide_render and not ob.get("simpler_trashed") \
                and ob.data.energy > 0:
            s = (ob.matrix_world.to_quaternion() @ Vector((0.0, 0.0, 1.0))).normalized()
            if s.z > 0.0 and not ob.get("simpler_ambience_moon") and not ob.get("simpler_cloud_sun") and not ob.get("simpler_fill"):      # (moonlight reflected: nothing to see)
                out.append(ob)
    return out


def _fingerprint(waters, suns, final):
    from . import water
    parts = [bool(final)]
    for ob in suns:
        d = ob.data
        parts.append((ob.name, d.type, tuple(round(x, 5) for r in ob.matrix_world for x in r), round(d.energy, 4),
                      tuple(round(c, 4) for c in d.color), round(getattr(d, "angle", 0.0), 5),
                      round(getattr(d, "shadow_soft_size", 0.0), 4), round(getattr(d, "size", 0.0), 4),
                      round(getattr(d, "spot_size", 0.0), 4), round(getattr(d, "spot_blend", 0.0), 4)))
    for ob in waters:
        parts.append((ob.name, tuple(round(x, 5) for r in ob.matrix_world for x in r), ob.get(water.KEY, ""),
                      water.water_material(ob).get(water.MKEY, ""), float(ob.get("simpler_caster", 0.0))))
    from . import seacaustics
    parts.append(seacaustics.fingerprint(final))
    lo, hi = _bounds(waters) if waters else (Vector((0, 0, 0)), Vector((0, 0, 0)))
    for ob in bpy.context.scene.objects:
        if waters and ob.type in ("MESH", "EMPTY", "CURVE") and _near(ob, lo, hi):
            parts.append((ob.name, tuple(round(x, 4) for r in ob.matrix_world for x in r), ob.hide_render,
                          len(ob.data.polygons) if ob.type == "MESH" else 0))
    return hash(tuple(parts))


def _bounds(obs):
    lo = Vector((1e18, 1e18, 1e18)); hi = Vector((-1e18, -1e18, -1e18))
    for ob in obs:
        for c in ob.bound_box:
            p = ob.matrix_world @ Vector(c)
            lo = Vector(map(min, lo, p)); hi = Vector(map(max, hi, p))
    return lo, hi


def _near(ob, lo, hi, reach=REACH):
    try:
        pts = [ob.matrix_world @ Vector(c) for c in ob.bound_box]
    except Exception:
        return False
    a = Vector(map(min, *pts)) if len(pts) > 1 else pts[0]
    b = Vector(map(max, *pts)) if len(pts) > 1 else pts[0]
    if ob.type == "EMPTY" and ob.instance_type == "COLLECTION":
        return True                                     # (bound box of an empty: unknown - checked per instance)
    return all(a[i] <= hi[i] + reach and b[i] >= lo[i] - reach for i in range(3))


def _mesh_arrays(me, mw):
    """World vertices (n,3), vertex normals (n,3), triangles (m,3) of an evaluated mesh."""
    me.calc_loop_triangles()
    nv, nt = len(me.vertices), len(me.loop_triangles)
    co = np.empty(nv * 3, np.float32); me.vertices.foreach_get("co", co)
    no = np.empty(nv * 3, np.float32); me.vertices.foreach_get("normal", no)
    tri = np.empty(nt * 3, np.int32); me.loop_triangles.foreach_get("vertices", tri)
    m = np.array(mw, np.float64)
    co = co.reshape(-1, 3) @ m[:3, :3].T + m[:3, 3]
    nm = np.linalg.inv(m[:3, :3]).T
    no = no.reshape(-1, 3) @ nm.T
    no /= np.maximum(np.linalg.norm(no, axis=1, keepdims=True), 1e-12)
    return co, no, tri.reshape(-1, 3)


def _water_surfaces(waters, levels=1, max_verts=MAX_WATER_VERTS):
    """The surfaces of the water as the path tracer sees them (waves modifier evaluated), top faces only."""
    from . import water
    out = []
    mods = [ob.modifiers.get(water.MOD) for ob in waters]
    for m in mods:
        m.show_viewport = True
    hidden = [ob for ob in waters if ob.hide_viewport]          # (the grid of a large surface: hidden in the view)
    for ob in hidden:
        ob.hide_viewport = False
    try:
        dg = bpy.context.evaluated_depsgraph_get()
        dg.update()
        for ob, mod in zip(waters, mods):
            ev = ob.evaluated_get(dg)
            co, no, tri = _mesh_arrays(ev.data, ev.matrix_world)
            if len(co) > max(max_verts * 2, 2_000_000):
                # only for a huge water: the same waves with a coarser subdivision. Not for ordinary ones any more:
                # coarser waves are other waves (the noise sampled more loosely) - in the view the net of light of
                # the pool disappeared. Lamps trace only the part of the water that carries their light (_trace).
                ident = water._socket_ids(mod).get("Level")
                lev = _get_input(mod, ident) if ident else None
                if lev:
                    drop = min(int(lev), int(math.ceil(math.log(len(co) / max_verts, 4))))
                    water._set_input(mod, ident, int(lev) - drop)
                    try:
                        ob.update_tag()
                        dg.update()
                        ev = ob.evaluated_get(dg)
                        co, no, tri = _mesh_arrays(ev.data, ev.matrix_world)
                    finally:
                        water._set_input(mod, ident, int(lev))
                        ob.update_tag()
            e1 = co[tri[:, 1]] - co[tri[:, 0]]; e2 = co[tri[:, 2]] - co[tri[:, 0]]
            fn = np.cross(e1, e2)
            area2 = np.linalg.norm(fn, axis=1)
            keep = (area2 > 1e-14) & (fn[:, 2] > 0.3 * area2)
            tri = tri[keep]
            used = np.unique(tri)
            remap = np.full(len(co), -1, np.int64); remap[used] = np.arange(len(used))
            co, no, tri = co[used], no[used], remap[tri]
            for _ in range(levels):
                if len(co) * 4 > max_verts:
                    break
                co, no, tri = _subdivide(co, no, tri)
            out.append((ob, co, no, tri))
    finally:
        for m in mods:
            m.show_viewport = False
        for ob in hidden:
            ob.hide_viewport = True
        bpy.context.evaluated_depsgraph_get().update()
    return out


def _get_input(mod, ident):
    props = getattr(mod, "properties", None)
    if props is not None and hasattr(props.inputs, ident):
        return getattr(props.inputs, ident).value
    try:
        return mod[ident]
    except KeyError:
        return None


def _subdivide(co, no, tri):
    """Each triangle into four: the new vertices in the middle of the edges, on the flat triangle, with the normal
    interpolated as Cycles does for smooth shading - the reflection the path tracer sees, at a finer step (sharper
    lines where the light folds)."""
    e = np.sort(np.concatenate([tri[:, [0, 1]], tri[:, [1, 2]], tri[:, [2, 0]]]), axis=1)
    uniq, inv = np.unique(e, axis=0, return_inverse=True)
    inv = inv.ravel()
    mid = len(co) + inv.reshape(3, -1).T                       # (m,3): middle of edges 01, 12, 20
    mco = 0.5 * (co[uniq[:, 0]] + co[uniq[:, 1]])
    mno = no[uniq[:, 0]] + no[uniq[:, 1]]
    mno /= np.maximum(np.linalg.norm(mno, axis=1, keepdims=True), 1e-12)
    a, b, c = tri[:, 0], tri[:, 1], tri[:, 2]
    m01, m12, m20 = mid[:, 0], mid[:, 1], mid[:, 2]
    nt = np.concatenate([np.stack([a, m01, m20], 1), np.stack([m01, b, m12], 1), np.stack([m20, m12, c], 1),
                         np.stack([m01, m12, m20], 1)])
    return np.concatenate([co, mco]), np.concatenate([no, mno]), nt


META = []          # (owner, world matrix as numpy, evaluated mesh) of the last BVH, in the order of its offsets


def _glass_pass(idx, loc, offsets):
    """The sun's ray met triangle idx of the BVH at loc: (r, g, b) of the light that goes on through it, or None when
    it stops there (1.75.0: glass and stained glass windows colour the light instead of stopping it)."""
    from . import glass
    k = int(np.searchsorted(offsets, idx, side="right")) - 1
    if k < 0 or k >= len(META):
        return None
    orig, m, me = META[k]
    lt = me.loop_triangles[idx - int(offsets[k])]
    mi = lt.material_index
    mat = orig.material_slots[mi].material if mi < len(orig.material_slots) else None
    f = glass.light_filter(mat)
    if f is None:
        return None
    w, col, pic = f
    c = np.array(col, np.float64)
    if pic is not None and me.uv_layers.active is not None:
        uvl = me.uv_layers.active.data
        P = [m[:3, :3] @ np.array(me.vertices[v].co) + m[:3, 3] for v in lt.vertices]
        # barycentric of the hit in the triangle
        v0, v1, v2 = P[1] - P[0], P[2] - P[0], np.array(loc) - P[0]
        d00, d01, d11 = v0 @ v0, v0 @ v1, v1 @ v1
        d20, d21 = v2 @ v0, v2 @ v1
        den = d00 * d11 - d01 * d01
        if abs(den) > 1e-18:
            b1 = (d11 * d20 - d01 * d21) / den; b2 = (d00 * d21 - d01 * d20) / den
            uv = sum(np.array(uvl[li].uv) * bw for li, bw in zip(lt.loops, (1.0 - b1 - b2, b1, b2)))
            h, wd = pic.shape[:2]
            x = int(uv[0] % 1.0 * wd) % wd; y = int(uv[1] % 1.0 * h) % h
            c = pic[y, x].astype(np.float64)
    return np.clip(c, 0.0, 1.0) * w


def _blockers(waters, max_tris=4_000_000):
    """BVH of the objects near the water (instances of library models too), without the water itself.
    Returns (bvh, polygon -> object owner list, offsets)."""
    lo, hi = _bounds(waters)
    return _blockers_box(lo, hi, max_tris, {ob.name for ob in waters})


def _blockers_box(lo, hi, max_tris=4_000_000, skip=()):
    """BVH of the objects within REACH of the box lo..hi (the sea's caustics: their rectangle)."""
    from mathutils.bvhtree import BVHTree
    from .core import INTERNAL_KEY
    skip = set(skip)
    dg = bpy.context.evaluated_depsgraph_get()
    # first what is near and how heavy it is, then the nearest pieces up to a budget of triangles: a scene of 87 M
    # triangles (a terrain with scattered plants around a lake) made a BVH of all of it and the view waited minutes
    cand = []
    for inst in dg.object_instances:
        ob = inst.object
        orig = ob.original
        if ob.type != "MESH" or orig.name in skip or orig.hide_render or orig.get("simpler_twin") \
                or orig.get("simpler_water_body") or orig.get("simpler_fog_domain") or orig.get(INTERNAL_KEY):
            continue
        mw = inst.matrix_world.copy()
        pts = [mw @ Vector(c) for c in ob.bound_box]
        a = Vector(map(min, *pts)); b = Vector(map(max, *pts))
        if not all(a[i] <= hi[i] + REACH and b[i] >= lo[i] - REACH for i in range(3)):
            continue
        me = ob.data
        if not me.polygons:
            continue
        gap = math.sqrt(sum(max(0.0, a[i] - hi[i], lo[i] - b[i]) ** 2 for i in range(3)))
        cand.append((gap, len(me.polygons) * 2, orig, mw, me))
    cand.sort(key=lambda c: c[0])
    budget = max_tris
    verts, polys, owners, offsets = [], [], [], []
    META.clear()
    nv, npoly, left_out = 0, 0, 0
    for gap, est, orig, mw, me in cand:
        if est > budget:
            left_out += 1
            continue
        me.calc_loop_triangles()
        co = np.empty(len(me.vertices) * 3, np.float32); me.vertices.foreach_get("co", co)
        m = np.array(mw, np.float64)
        co = co.reshape(-1, 3) @ m[:3, :3].T + m[:3, 3]
        tri = np.empty(len(me.loop_triangles) * 3, np.int32); me.loop_triangles.foreach_get("vertices", tri)
        verts.append(co); polys.append(tri.reshape(-1, 3) + nv)
        offsets.append(npoly); owners.append(orig)
        META.append((orig, m, me))
        nv += len(co); npoly += len(me.loop_triangles)
        budget -= len(me.loop_triangles)
    if left_out:
        log("SIMPLER_REFCAUSTICS", f"{left_out} far or heavy pieces left out ({max_tris / 1e6:.0f} M triangles used)")
    if not verts:
        return None, [], np.zeros(0, np.int64)
    V = np.concatenate(verts); P = np.concatenate(polys)
    bvh = BVHTree.FromPolygons(V.tolist(), P.tolist(), all_triangles=True, epsilon=0.0)
    return bvh, owners, np.array(offsets, np.int64)


def _fresnel(cos_i, n=IOR):
    """Unpolarised Fresnel reflectance; n = index on the far side / index on the near side (from inside the water:
    1/1.333, with total internal reflection beyond 48.6 degrees)."""
    cos_i = np.clip(cos_i, 0.0, 1.0)
    n = np.asarray(n, np.float64)
    sin_t2 = (1.0 - cos_i ** 2) / (n * n)
    cos_t = np.sqrt(np.maximum(0.0, 1.0 - sin_t2))
    rs = ((cos_i - n * cos_t) / np.maximum(cos_i + n * cos_t, 1e-12)) ** 2
    rp = ((cos_t - n * cos_i) / np.maximum(cos_t + n * cos_i, 1e-12)) ** 2
    return np.where(sin_t2 >= 1.0, 1.0, 0.5 * (rs + rp))


# ---------------------------------------------------------------- the light

def _emitters(waters):
    """The lights whose reflection on the water is followed: every sun, and the lamps (point, spot, area) within
    reach of the water - above it (a lamp by the pool) or under it (the light of a pool at night: the surface seen
    from below reflects a good part of it back, all of it beyond 48.6 degrees, onto the floor and the walls)."""
    out = list(_suns())
    lo, hi = _bounds(waters)
    for ob in bpy.context.scene.objects:
        if ob.type != "LIGHT" or ob.data.type not in ("POINT", "SPOT", "AREA") or ob.hide_render \
                or ob.get("simpler_trashed") or ob.data.energy <= 0:
            continue
        p = ob.matrix_world.translation
        if all(lo[i] - REACH <= p[i] <= hi[i] + REACH for i in range(3)):
            out.append(ob)
    return out


def _lamp_terms(ob, co):
    """For a lamp: direction from the lamp to each vertex, irradiance per unit of power on a surface facing it
    (W/m2 per W, as Cycles: point and spot P/4pi per steradian, area P/pi x cos), distance and light radius."""
    d = ob.data
    L = np.array(ob.matrix_world.translation, np.float64)
    v = co - L
    dist = np.maximum(np.linalg.norm(v, axis=1), 1e-4)
    dirs = v / dist[:, None]
    fwd = np.array((ob.matrix_world.to_quaternion() @ Vector((0.0, 0.0, -1.0))).normalized(), np.float64)
    if d.type == "AREA":
        inten = np.maximum(0.0, dirs @ fwd) / math.pi
        sc = ob.matrix_world.to_scale()
        sx = float(d.size) * sc.x
        sy = (float(d.size_y) if d.shape in ("RECTANGLE", "ELLIPSE") else float(d.size)) * sc.y
        radius = 0.5 * math.sqrt(max(1e-8, sx * sy))
    else:
        inten = np.full(len(co), 1.0 / (4.0 * math.pi))
        if d.type == "SPOT":
            ch = math.cos(float(d.spot_size) / 2.0)
            t = dirs @ fwd
            smooth = max(1e-6, (1.0 - ch) * float(d.spot_blend))
            x = np.clip((t - ch) / smooth, 0.0, 1.0)
            inten = inten * np.where(t > ch, x * x * (3 - 2 * x), 0.0)
        radius = float(getattr(d, "shadow_soft_size", 0.0))
    return dirs, inten / (dist * dist), dist, L, radius


def _extinction(ob):
    """Light lost per metre inside this water (RGB): colour and clarity of its body (water.py), murk included."""
    from . import water
    wm = water.water_material(ob)
    body = water.mat_settings(wm)["body"] if wm is not None else None
    if not body or not body.get("on"):
        return np.zeros(3)
    absorb, scatter = water.coefficients(body)
    return np.array(absorb, np.float64) + scatter


def _land(acc, co, tri, hit, hn, hd, hidx, power, blur_v, col, offsets):
    """Adds the triangles of light of one bundle of rays (reflected or refracted) to acc. power: (m, 3) W per triangle
    (colour included), hit...: per vertex."""
    P, N, F, B, O = acc
    a, b, c = tri[:, 0], tri[:, 1], tri[:, 2]
    pw = power.sum(1)
    ok = (hidx[a] >= 0) & (hidx[b] >= 0) & (hidx[c] >= 0) & (pw > 0)
    # the three rays must land on the same surface (else the triangle straddles an edge: patches below)
    oa = np.searchsorted(offsets, hidx[a], "right") - 1
    ob_ = np.searchsorted(offsets, hidx[b], "right") - 1
    oc = np.searchsorted(offsets, hidx[c], "right") - 1
    same = ok & (oa == ob_) & (oa == oc) & (np.einsum("ij,ij->i", hn[a], hn[b]) > 0.9) \
        & (np.einsum("ij,ij->i", hn[a], hn[c]) > 0.9)
    if same.any():
        P.append(np.stack([hit[a[same]], hit[b[same]], hit[c[same]]], 1))
        N.append(hn[a[same]])
        F.append(power[same])
        B.append((blur_v[a[same]] + blur_v[b[same]] + blur_v[c[same]]) / 3.0)
        O.append(oa[same])
    # straddling triangles (their rays land on different surfaces): a third of the power at each vertex that
    # landed, spread over a patch the size and shape of the water triangle (as a flat mirror would throw it). As
    # single points they made a salt-and-pepper noise instead of light.
    rest = (pw > 0) & ~same
    cen = (co[a] + co[b] + co[c]) / 3.0
    for v in (a, b, c):
        k = rest & (hidx[v] >= 0)
        if k.any():
            pts = hit[v[k]]
            P.append(np.stack([pts + (co[a[k]] - cen[k]), pts + (co[b[k]] - cen[k]), pts + (co[c[k]] - cen[k])], 1))
            N.append(hn[v[k]])
            F.append(power[k] / 3.0)
            B.append(blur_v[v[k]])
            O.append(np.searchsorted(offsets, hidx[v[k]], "right") - 1)


def _refine_near(co, no, tri, L, max_sr, max_verts):
    """Water triangles seen from a lamp under too large an angle split into four, again and again (up to the vertex
    budget): close to a lamp - above all one just under the surface - a few big triangles carried all its light and
    each drew a big round blob. New vertices in the middle of the edges, on the flat triangle, normal interpolated
    as Cycles does (the shape of the waves does not change); they are not shared (each triangle on its own)."""
    for _ in range(8):
        a, b, c = tri[:, 0], tri[:, 1], tri[:, 2]
        cen = (co[a] + co[b] + co[c]) / 3.0
        area = 0.5 * np.linalg.norm(np.cross(co[b] - co[a], co[c] - co[a]), axis=1)
        d2 = np.maximum(np.einsum("ij,ij->i", cen - L, cen - L), 1e-6)
        big = area / d2 > max_sr
        nb = int(big.sum())
        if nb == 0 or len(co) + nb * 3 > max_verts:
            if nb and len(co) < max_verts:              # (budget almost reached: the largest ones first)
                k = (max_verts - len(co)) // 3
                order = np.argsort(-(area / d2))
                big = np.zeros(len(tri), bool); big[order[:k]] = True
                nb = int(big.sum())
            if nb == 0 or len(co) + nb * 3 > max_verts:
                break
        sel = tri[big]
        a, b, c = sel[:, 0], sel[:, 1], sel[:, 2]
        mids = []
        for i, j in ((a, b), (b, c), (c, a)):
            m = 0.5 * (co[i] + co[j])
            n = no[i] + no[j]
            n /= np.maximum(np.linalg.norm(n, axis=1, keepdims=True), 1e-12)
            mids.append((m, n))
        base = len(co)
        co = np.concatenate([co] + [m for m, _ in mids])
        no = np.concatenate([no] + [n for _, n in mids])
        m01 = base + np.arange(nb); m12 = m01 + nb; m20 = m12 + nb
        new = np.concatenate([np.stack([a, m01, m20], 1), np.stack([m01, b, m12], 1), np.stack([m20, m12, c], 1),
                              np.stack([m01, m12, m20], 1)])
        tri = np.concatenate([tri[~big], new])
    return co, no, tri


def _trace(surfaces, emitters, bvh, owners, offsets, final=False):
    """Hits of the light the water sends on: per lit water triangle, its 3 landing points, the receiving normal, the
    power (W, per colour channel), the blur radius of the light at the landing point and the owner object.
    Reflected light for every light (above or under the water). Refracted light for lamps UNDER the water (the light
    of a pool lamp leaving the water onto walls and ceiling) - only where the water draws sharp caustics (its glass
    shadow shortcut is off there: otherwise that light already passes, evenly, and would count twice). Returns a dict
    of arrays + ray count."""
    rays = 0
    acc = ([], [], [], [], [])
    ray_cast = bvh.ray_cast
    eps = 1e-3
    for em in emitters:
        sun = em.data.type == "SUN"
        col = np.array(em.data.color[:3], np.float64) * float(em.data.energy)
        vert_budget = MAX_WATER_VERTS if final else VIEW_LAMP_VERTS
        for ob, co, no, tri in surfaces:
            if not sun:
                L0 = np.array(em.matrix_world.translation, np.float64)
                co, no, tri = _refine_near(co, no, tri, L0, LAMP_SR_FINAL if final else LAMP_SR_VIEW,
                                           (MAX_WATER_VERTS if final else VIEW_WATER_VERTS // 2) + len(co))
            nv = len(co)
            refract = (not sun) and float(ob.get("simpler_caster", 0.0)) > 0.5
            ext = _extinction(ob)
            if sun:
                s = np.array((em.matrix_world.to_quaternion() @ Vector((0.0, 0.0, 1.0))).normalized(), np.float64)
                dirs = np.tile(-s, (nv, 1)); irr = np.ones(nv); ldist = np.full(nv, REACH * 4)
                spread = math.tan(max(float(em.data.angle), 1e-4) / 2.0)       # blur = distance x this
            else:
                dirs, irr, ldist, _L, radius = _lamp_terms(em, co)
            dn = np.einsum("ij,ij->i", no, dirs)            # < 0: lit from above, > 0: from under the water
            r = dirs - 2.0 * dn[:, None] * no
            r /= np.maximum(np.linalg.norm(r, axis=1, keepdims=True), 1e-12)
            # refraction out of the water (Snell, water -> air): t = eta d - (eta cos_i - cos_t) n
            eta = IOR
            cos_i = np.clip(dn, 0.0, 1.0)
            sin_t2 = eta * eta * (1.0 - cos_i * cos_i)
            cos_t = np.sqrt(np.maximum(0.0, 1.0 - sin_t2))
            tdir = eta * dirs - (eta * cos_i - cos_t)[:, None] * no
            tdir /= np.maximum(np.linalg.norm(tdir, axis=1, keepdims=True), 1e-12)
            lit = np.zeros(nv, bool)
            tint = np.ones((nv, 3))
            hit = np.full((nv, 3), np.nan); hn = np.zeros((nv, 3)); hd = np.zeros(nv); hidx = np.full(nv, -1, np.int64)
            thit = np.full((nv, 3), np.nan); thn = np.zeros((nv, 3)); thd = np.zeros(nv); thidx = np.full(nv, -1, np.int64)
            # a lamp lights the water unevenly (inverse square): only the triangles that carry 99.5% of its light
            # on the water are traced, at most the budget of vertices - the full waves where the light is
            active = np.ones(nv, bool)
            if not sun:
                a0, b0, c0 = tri[:, 0], tri[:, 1], tri[:, 2]
                ar = 0.5 * np.linalg.norm(np.cross(co[b0] - co[a0], co[c0] - co[a0]), axis=1)
                wt = ar * (np.abs(dn[a0]) + np.abs(dn[b0]) + np.abs(dn[c0])) * (irr[a0] + irr[b0] + irr[c0])
                order = np.argsort(-wt)
                cum = np.cumsum(wt[order])
                keep = int(np.searchsorted(cum, 0.995 * cum[-1])) + 1 if len(cum) and cum[-1] > 0 else 0
                keep = min(keep, max(1, vert_budget // 2))       # (about 2 triangles per vertex)
                active = np.zeros(nv, bool)
                active[tri[order[:keep]].ravel()] = True
            idxs = np.nonzero(active)[0]
            step = max(2000, len(idxs) // 50)
            for n_i, i in enumerate(idxs):
                if n_i % step == 0:
                    _progress(tr("Luce riflessa dall'acqua: raggi"), f"{n_i * 100 // max(1, len(idxs))}%", n_i / max(1, len(idxs)))
                if irr[i] <= 0.0 or dn[i] == 0.0:
                    continue
                above = dn[i] < 0.0
                p = Vector(co[i]) + Vector(no[i]) * (eps if above else -eps)
                rays += 1
                sv = Vector(-dirs[i]); q = p; left = max(0.0, ldist[i] - 2 * eps); shadow = False
                for _layer in range(GLASS_LAYERS + 1):
                    hloc, _hn, hix, hdist = ray_cast(q, sv, left)
                    if hloc is None:
                        break
                    f = _glass_pass(hix, hloc, offsets) if _layer < GLASS_LAYERS else None
                    if f is None or f.max() < 1e-3:
                        shadow = True                          # in shadow (a bridge, a wall, a tree over the water)
                        break
                    tint[i] *= f                               # (through a glass: its colour, at that point)
                    q = hloc + sv * eps; left -= hdist + eps; rays += 1
                if shadow:
                    continue
                lit[i] = True
                ri = r[i]
                if not ((ri[2] <= 0.0) if above else (ri[2] >= 0.0)):     # (into the water again / out: not followed)
                    rays += 1
                    rv = Vector(ri)
                    loc, nrm, idx, dist = ray_cast(p, rv, REACH)
                    if loc is not None:
                        if nrm.dot(rv) > 0.0:
                            nrm = -nrm                         # (the side the light arrives on, as Cycles shades it)
                        hit[i] = loc; hn[i] = nrm; hd[i] = dist; hidx[i] = idx
                if refract and not above and sin_t2[i] < 1.0 and tdir[i][2] > 0.0:
                    rays += 1
                    tv = Vector(tdir[i])
                    loc, nrm, idx, dist = ray_cast(Vector(co[i]) + Vector(no[i]) * eps, tv, REACH)
                    if loc is not None:
                        if nrm.dot(tv) > 0.0:
                            nrm = -nrm
                        thit[i] = loc; thn[i] = nrm; thd[i] = dist; thidx[i] = idx
            a, b, c = tri[:, 0], tri[:, 1], tri[:, 2]
            fn = np.cross(co[b] - co[a], co[c] - co[a])
            area = 0.5 * np.linalg.norm(fn, axis=1)
            fnn = fn / np.maximum(2.0 * area[:, None], 1e-12)
            dm = dirs[a] + dirs[b] + dirs[c]
            dm /= np.maximum(np.linalg.norm(dm, axis=1, keepdims=True), 1e-12)
            cos_s = np.abs(np.einsum("ij,ij->i", fnn, dm))
            nmean = no[a] + no[b] + no[c]
            nmean /= np.maximum(np.linalg.norm(nmean, axis=1, keepdims=True), 1e-12)
            cdn = np.einsum("ij,ij->i", nmean, dm)
            below = cdn > 0.0
            R = _fresnel(np.abs(cdn), np.where(below, 1.0 / IOR, IOR))    # (from under: total reflection possible)
            same_side = (np.sign(dn[a]) == np.sign(dn[b])) & (np.sign(dn[a]) == np.sign(dn[c]))
            litf = (lit[a] * irr[a] + lit[b] * irr[b] + lit[c] * irr[c]) / 3.0
            base = area * cos_s * litf * same_side              # W per unit of light energy, at the surface
            # under the water the light is dimmed on its way (lamp -> surface, and back down for the reflection)
            dl = (ldist[a] + ldist[b] + ldist[c]) / 3.0
            dr = (hd[a] + hd[b] + hd[c]) / 3.0
            att_in = np.where(below[:, None], np.exp(-np.outer(dl, ext)), 1.0)
            att_ref = att_in * np.where(below[:, None], np.exp(-np.outer(dr, ext)), 1.0)
            if sun:
                blur_r = hd * spread
                blur_t = thd * spread
            else:
                blur_r = hd * radius / np.maximum(ldist, 1e-3)
                blur_t = thd * IOR * radius / np.maximum(ldist, 1e-3)   # (out of the water the lamp looks n x wider)
            tm = (tint[a] + tint[b] + tint[c]) / 3.0               # (the colour of the glass the light came through)
            _land(acc, co, tri, hit, hn, hd, hidx, (base * R)[:, None] * att_ref * col[None, :] * tm, blur_r, col, offsets)
            if refract and below.any():
                T = np.where(below, 1.0 - R, 0.0)
                _land(acc, co, tri, thit, thn, thd, thidx, (base * T)[:, None] * att_in * col[None, :] * tm, blur_t, col,
                      offsets)
    P, N, F, B, O = acc
    if not P:
        return None, rays
    return {"P": np.concatenate(P), "N": np.concatenate(N), "F": np.concatenate(F), "B": np.concatenate(B),
            "O": np.concatenate(O)}, rays


def _splat(t, final):
    """Fills the triangles of light into the six projection images. Returns {axis: (rgb image, u0, v0, texel,
    d0, d1)}."""
    rng = np.random.default_rng(7)
    P, N, F, Bl = t["P"], t["N"], t["F"], t["B"]
    # weights per facing (normalised squares of the positive components): see the shader (any normal is exact)
    w = np.zeros((len(N), 6))
    for k, (ax, sg) in enumerate(AXES):
        c = N[:, ax] * sg
        w[:, k] = np.where(c > 0.01, c * c, 0.0)
    w /= np.maximum(w.sum(1, keepdims=True), 1e-12)
    out = {}
    # first the extent and the coverage of each facing at the finest texel; then ONE scale for all the texels so
    # that the samples fit the budget (when it is not enough the TEXELS get bigger - a softer image - never the
    # samples fewer: one sample for a large triangle of light made a speckled noise)
    # each facing in depth layers: surfaces facing the same way at different depths (a wall and the columns in
    # front of it) never share an image - before one depth per texel mixed them and cut the light into holes
    layers = []
    for k, (ax, sg) in enumerate(AXES):
        selk = w[:, k] > 1e-4
        if not selk.any():
            continue
        ids = np.nonzero(selk)[0]
        dt = P[ids, :, ax].mean(1) * sg
        order = np.argsort(dt)
        ds = dt[order]
        cuts = np.nonzero(np.diff(ds) > LAYER_GAP)[0]
        groups = np.split(order, cuts + 1)
        # at most LAYERS: the closest neighbours merge first
        while len(groups) > LAYERS:
            gaps = [dt[groups[i + 1]].min() - dt[groups[i]].max() for i in range(len(groups) - 1)]
            i = int(np.argmin(gaps))
            groups[i] = np.concatenate([groups[i], groups[i + 1]])
            del groups[i + 1]
        for l, gidx in enumerate(groups):
            sel = np.zeros(len(N), bool); sel[ids[gidx]] = True
            layers.append((k * LAYERS + l, k, sel))
    prep = {}
    for slot, k, sel in layers:
        ax, sg = AXES[k]
        u_ax, v_ax = [i for i in range(3) if i != ax]
        tp = P[sel]
        pu, pv = tp[:, :, u_ax], tp[:, :, v_ax]
        blur = Bl[sel]
        u0, u1 = pu.min() - 0.05, pu.max() + 0.05
        v0, v1 = pv.min() - 0.05, pv.max() + 0.05
        px = MAX_PX if final else VIEW_PX
        texel = max(MIN_TEXEL, (u1 - u0) / px, (v1 - v0) / px)
        tarea = 0.5 * np.abs((pu[:, 1] - pu[:, 0]) * (pv[:, 2] - pv[:, 0]) - (pu[:, 2] - pu[:, 0]) * (pv[:, 1] - pv[:, 0]))
        cover = tarea
        need = float(np.sum(np.clip(cover / (texel * texel) * 0.75, 1.0, 4096.0)))
        prep[slot] = (k, sel, tp, pu, pv, blur, u0, u1, v0, v1, texel, cover, need)
    budget = MAX_SAMPLES if final else MAX_SAMPLES // 3
    total = sum(x[-1] for x in prep.values())
    grow = math.sqrt(total / budget) if total > budget else 1.0
    for slot, (k, sel, tp, pu, pv, blur, u0, u1, v0, v1, texel, cover, _need) in prep.items():
        ax, sg = AXES[k]
        texel *= grow
        cosn = np.abs(N[sel, ax])
        flux = F[sel] * (w[sel, k] * cosn)[:, None]
        W, H = int(math.ceil((u1 - u0) / texel)) + 1, int(math.ceil((v1 - v0) / texel)) + 1
        want = np.clip(np.ceil(cover / (texel * texel) * 0.75), 1, 4096)
        n = want.astype(np.int64)
        idx = np.repeat(np.arange(len(n)), n)
        # stratified points (a Fibonacci lattice in each triangle, shifted per triangle): far less grain than random
        start = np.repeat(np.cumsum(n) - n, n)
        j = (np.arange(len(idx)) - start).astype(np.float32)
        nn = n.astype(np.float32)[idx]
        shift = rng.random(len(n), np.float32)[idx]
        r1 = (j + 0.5) / nn
        r2 = np.mod(j * np.float32(0.6180339887) + shift, np.float32(1.0))
        sq = np.sqrt(r1)
        b0, b1, b2 = 1 - sq, sq * (1 - r2), sq * r2
        pu32, pv32 = (pu - u0).astype(np.float32), (pv - v0).astype(np.float32)   # (float32 near 0: exact)
        b0, b1, b2 = b0.astype(np.float32), b1.astype(np.float32), b2.astype(np.float32)
        su = b0 * pu32[idx, 0] + b1 * pu32[idx, 1] + b2 * pu32[idx, 2]
        sv = b0 * pv32[idx, 0] + b1 * pv32[idx, 1] + b2 * pv32[idx, 2]
        x = np.clip((su / np.float32(texel)).astype(np.int64), 0, W - 1)
        y = np.clip((sv / np.float32(texel)).astype(np.int64), 0, H - 1)
        # where along the axis the light landed, per texel (4th channel of the image): the shader lights a surface
        # only at that depth. With a depth RANGE for the whole image, another wall facing the same way inside the
        # range (behind a door, the bottom of a wall beyond the deck) got a copy of the light.
        dd = tp[:, :, ax].ravel() * sg
        d0 = float(dd.min()) - 0.03
        dtri = (tp[:, :, ax].mean(1) * sg - d0).astype(np.float64)
        # the size of the light blurs what it draws (sun: distance x tan(angle/2); lamp: distance x radius / its
        # distance). Done on the image, not by moving each sample at random: the triangles are grouped by blur
        # radius (in texels, steps of x2) and each group is blurred once - smooth, no "bokeh" of dots.
        rt = blur / texel
        cls = np.where(rt < 0.75, -1, np.round(np.log(np.maximum(rt, 1e-6)) / math.log(2.0))).astype(np.int64)
        per = np.repeat(1.0 / n, n)
        # a pyramid: a group with a wide blur is counted straight into an image 2^j times smaller, blurred there
        # by a couple of texels, and the levels are added back from the coarsest (each step: x2 and a soft pass)
        pend = {}
        for cl in np.unique(cls):
            m = (cls == cl)[idx]
            if not m.any():
                continue
            rad = min(2.0 ** cl, 0.25 * max(W, H)) if cl >= 0 else 0.0
            j = int(math.floor(math.log2(rad / 1.5))) if rad >= 3 else 0
            f = 2 ** j
            Hj, Wj = -(-H // f), -(-W // f)
            cm = (y[m] // f) * Wj + (x[m] // f)
            im_ = idx[m]
            layer = np.zeros((Hj * Wj, 5), np.float32)
            for ch in range(3):
                layer[:, ch] = np.bincount(cm, weights=flux[im_, ch] * per[m], minlength=Hj * Wj)
            # depth weighted by the light: where a wall and a column in front of it share texels, the depth is the
            # one of the surface that gets the light (counted per sample it was halfway between, matched neither,
            # and the light was cut into black holes with sharp edges)
            wl = flux[im_].sum(1) * per[m]
            layer[:, 3] = np.bincount(cm, weights=dtri[im_] * wl, minlength=Hj * Wj)
            layer[:, 4] = np.bincount(cm, weights=wl, minlength=Hj * Wj)
            layer = layer.reshape(Hj, Wj, 5)
            r = rad / f
            npass = max(1, int(round((r * r / 4.0) / 0.5))) if r > 0 else 0
            pend.setdefault(j, {}).setdefault(npass, []).append(layer)
        # per level: the groups that need more passes are blurred first and the others join on the way (one pass
        # blurs all the groups already in): as many passes as the widest group, not their sum
        levels = {}
        for j, groups in pend.items():
            acc = None
            for npass in range(max(groups), -1, -1):
                for layer in groups.get(npass, []):
                    acc = layer if acc is None else acc + layer
                if npass > 0 and acc is not None:
                    acc = _blur(acc)
            levels[j] = acc
        top = max(levels) if levels else 0
        for j in range(top, 0, -1):
            if j not in levels:
                continue
            f = 2 ** (j - 1)
            Hn, Wn = -(-H // f), -(-W // f)
            up = np.repeat(np.repeat(levels[j], 2, 0), 2, 1)[:Hn, :Wn] / 4.0
            up = _blur(up)
            levels[j - 1] = up if (j - 1) not in levels else levels[j - 1] + up
        img = levels.get(0, np.zeros((H, W, 5), np.float32))
        img[:, :, :3] /= (texel * texel)                     # W/m2 of the surface (see the weights above)
        img = _blur(img)                                     # (half a texel: no square texels in close-ups)
        wsum = img[:, :, 4]
        valid = wsum > 1e-30
        depth = np.where(valid, img[:, :, 3] / np.maximum(wsum, 1e-30), 0.0)
        # texels without light take the depth of the nearest lit ones: the image is read with linear filtering,
        # and a "no depth" value next to a lit texel gave a nonsense depth there - the light was cut into black
        # holes with sharp edges along the borders of every lit patch
        depth = _fill_depth(depth, valid)
        rgbd = np.concatenate([img[:, :, :3], depth[:, :, None]], 2)
        out[slot] = (rgbd.astype(np.float32), u0, v0, texel, d0, float(dd.max()) + 0.03)
    return out


def _box(img, r, axis):
    """Moving average of width 2r+1 along an axis (cumulative sums: cost independent of r), edges padded."""
    if r <= 0:
        return img
    pad = [(0, 0)] * img.ndim
    pad[axis] = (r + 1, r)
    c = np.cumsum(np.pad(img, pad, mode="edge"), axis=axis)
    n = c.shape[axis]
    sl_hi = [slice(None)] * img.ndim; sl_hi[axis] = slice(2 * r + 1, n)
    sl_lo = [slice(None)] * img.ndim; sl_lo[axis] = slice(0, n - 2 * r - 1)
    return (c[tuple(sl_hi)] - c[tuple(sl_lo)]) / (2 * r + 1)


def _disc_blur(img, radius):
    """About the blur of a round light of this radius (texels): three box passes per direction give a smooth bell
    with the same spread (variance of a disc: R^2/4). Wide blurs are made on a reduced copy (sum of f x f blocks,
    blurred, spread back): same light, a fraction of the time."""
    if radius >= 3:
        f = int(2 ** math.floor(math.log2(radius / 1.5)))
        H, W = img.shape[:2]
        Hp, Wp = -(-H // f) * f, -(-W // f) * f
        p = np.pad(img, ((0, Hp - H), (0, Wp - W), (0, 0)))
        small = p.reshape(Hp // f, f, Wp // f, f, -1).sum((1, 3))
        small = _disc_blur(small, radius / f)
        big = np.repeat(np.repeat(small, f, 0), f, 1)[:H, :W] / (f * f)
        return _blur(_blur(big))
    sigma2 = radius * radius / 4.0
    if radius < 3:                                   # (small: a few 1-2-1 passes, variance 1/2 each)
        for _ in range(max(1, int(round(sigma2 / 0.5)))):
            img = _blur(img)
        return img
    r = int(round((math.sqrt(12.0 * sigma2 / 3.0 + 1.0) - 1.0) / 2.0))
    for _ in range(3):
        img = _box(img, r, 0)
        img = _box(img, r, 1)
    return img


def _fill_depth(depth, valid):
    """Push-pull fill: empty texels get the average depth of the lit texels around them (coarser and coarser)."""
    if valid.all() or not valid.any():
        return depth
    levels = [(depth * valid, valid.astype(np.float64))]
    while min(levels[-1][0].shape) > 1:
        d, w = levels[-1]
        H, W = d.shape
        Hp, Wp = H + (H & 1), W + (W & 1)
        d = np.pad(d, ((0, Hp - H), (0, Wp - W))); w = np.pad(w, ((0, Hp - H), (0, Wp - W)))
        levels.append((d.reshape(Hp // 2, 2, Wp // 2, 2).sum((1, 3)), w.reshape(Hp // 2, 2, Wp // 2, 2).sum((1, 3))))
    d, w = levels[-1]
    est = np.where(w > 0, d / np.maximum(w, 1e-12), 0.0)
    for d, w in reversed(levels[:-1]):
        H, W = d.shape
        up = np.repeat(np.repeat(est, 2, 0), 2, 1)[:H, :W]
        est = np.where(w > 0, d / np.maximum(w, 1e-12), up)
    return np.where(valid, depth, est)


def _blur(img):
    """1-2-1 filter in both directions (edges repeated)."""
    H, W = img.shape[:2]
    if H < 2 or W < 2:
        return img
    a = np.empty_like(img)
    a[1:-1] = img[:-2] + img[2:] + 2 * img[1:-1]
    a[0] = 3 * img[0] + img[1]
    a[-1] = 3 * img[-1] + img[-2]
    b = np.empty_like(img)
    b[:, 1:-1] = a[:, :-2] + a[:, 2:] + 2 * a[:, 1:-1]
    b[:, 0] = 3 * a[:, 0] + a[:, 1]
    b[:, -1] = 3 * a[:, -1] + a[:, -2]
    b *= 1.0 / 16.0
    return b


# ---------------------------------------------------------------- images and shading

def _dir():
    d = _CACHE.get("dir")
    if not d or not os.path.isdir(d):
        from .render import STATE
        d = tempfile.mkdtemp(prefix="refcaustics_", dir=getattr(STATE, "tmp", None))
        _CACHE["dir"] = d
    return d


def _write_images(maps):
    """EXR files (half float) + their images in Blender; returns {axis: image}."""
    stamp = int(time.time() * 1000)
    folder = _dir()
    for f in os.listdir(folder):
        try:
            os.remove(os.path.join(folder, f))
        except OSError:
            pass
    imgs = {}
    for k, (arr, *_rest) in maps.items():
        H, W, _ = arr.shape
        name = f"Simpler RefCaustics {k}"
        im = bpy.data.images.get(name)
        if im is not None:
            bpy.data.images.remove(im)
        im = bpy.data.images.new(name, W, H, alpha=True, float_buffer=True)
        im.alpha_mode = "CHANNEL_PACKED"              # (alpha = depth, never multiplied into the colour)
        # data, not a colour: BEFORE the pixels are written. Set only after the save, the light went through a
        # colour transform on the way to the file - dim light came back up to 10 times brighter (burnt pools)
        im.colorspace_settings.is_data = True
        px = np.asarray(arr, np.float32)
        im.pixels.foreach_set(px.ravel())
        path = os.path.join(folder, f"axis{k}_{stamp}.exr")
        im.filepath_raw = path
        im.file_format = "OPEN_EXR"
        if hasattr(im, "use_half_precision"):
            im.use_half_precision = True
        im.save()                       # (pixels kept in the file: the final render runs from a saved copy)
        im.source = "FILE"
        im.filepath = path
        im.colorspace_settings.is_data = True
        im.alpha_mode = "CHANNEL_PACKED"
        im[IMG_TAG] = 1
        im.reload()
        imgs[k] = im
    return imgs


def _group():
    g = bpy.data.node_groups.get(GROUP)
    if g is not None:
        imgs = [g.nodes.get(f"img{k}") for k in range(SLOTS)]
        # (1.73.8) every picture still plugged in: the check of the missing textures at opening took these pictures
        # (in a temporary folder, gone) for missing ones of the project and unplugged them - the light was made
        # again but never reached the surfaces, until the switch was turned off and on. A group left so is rebuilt
        if all(n is not None and any(o.is_linked for o in n.outputs) for n in imgs):
            return g
        # group of 1.13.50-53: its nodes built again in the same datablock. The sockets stay as they are - clearing
        # them cut the links of every wrapped material and left those materials black
        g.nodes.clear()
    else:
        g = bpy.data.node_groups.new(GROUP, "ShaderNodeTree")
        g.interface.new_socket("Shader", in_out="INPUT", socket_type="NodeSocketShader")
        c = g.interface.new_socket("Color", in_out="INPUT", socket_type="NodeSocketColor")
        c.default_value = (0.8, 0.8, 0.8, 1.0)
        g.interface.new_socket("Shader", in_out="OUTPUT", socket_type="NodeSocketShader")
    Nn, L = g.nodes, g.links
    gi = Nn.new("NodeGroupInput"); go = Nn.new("NodeGroupOutput")
    geo = Nn.new("ShaderNodeNewGeometry")
    sp = Nn.new("ShaderNodeSeparateXYZ"); L.new(geo.outputs["Position"], sp.inputs[0])
    sn = Nn.new("ShaderNodeSeparateXYZ"); L.new(geo.outputs["True Normal"], sn.inputs[0])
    total = None
    for k in range(SLOTS):
        ax, sg = AXES[k // LAYERS]
        u_ax, v_ax = [i for i in range(3) if i != ax]
        cmb = Nn.new("ShaderNodeCombineXYZ")
        L.new(sp.outputs[u_ax], cmb.inputs[0]); L.new(sp.outputs[v_ax], cmb.inputs[1])
        mp = Nn.new("ShaderNodeVectorMath"); mp.operation = "MULTIPLY_ADD"; mp.name = f"map{k}"
        L.new(cmb.outputs[0], mp.inputs[0])
        tex = Nn.new("ShaderNodeTexImage"); tex.name = f"img{k}"; tex.extension = "CLIP"; tex.interpolation = "Linear"
        L.new(mp.outputs[0], tex.inputs[0])
        # facing: normal component on this axis > 0.01; depth: within the range where the light arrived
        fc = Nn.new("ShaderNodeMath"); fc.operation = "MULTIPLY"; fc.inputs[1].default_value = sg
        L.new(sn.outputs[ax], fc.inputs[0])
        gt = Nn.new("ShaderNodeMath"); gt.operation = "GREATER_THAN"; gt.inputs[1].default_value = 0.01
        L.new(fc.outputs[0], gt.inputs[0])
        dp = Nn.new("ShaderNodeMath"); dp.operation = "MULTIPLY"; dp.inputs[1].default_value = sg
        L.new(sp.outputs[ax], dp.inputs[0])
        lo = Nn.new("ShaderNodeMath"); lo.operation = "GREATER_THAN"; lo.name = f"lo{k}"
        L.new(dp.outputs[0], lo.inputs[0])
        hi = Nn.new("ShaderNodeMath"); hi.operation = "LESS_THAN"; hi.name = f"hi{k}"
        L.new(dp.outputs[0], hi.inputs[0])
        m1 = Nn.new("ShaderNodeMath"); m1.operation = "MULTIPLY"; L.new(gt.outputs[0], m1.inputs[0]); L.new(lo.outputs[0], m1.inputs[1])
        m2a = Nn.new("ShaderNodeMath"); m2a.operation = "MULTIPLY"; L.new(m1.outputs[0], m2a.inputs[0]); L.new(hi.outputs[0], m2a.inputs[1])
        # the depth where the light landed (alpha of the image, from the start of the range): only that surface
        rel = Nn.new("ShaderNodeMath"); rel.operation = "SUBTRACT"; rel.name = f"rel{k}"
        L.new(dp.outputs[0], rel.inputs[0])
        dif = Nn.new("ShaderNodeMath"); dif.operation = "SUBTRACT"
        L.new(rel.outputs[0], dif.inputs[0]); L.new(tex.outputs["Alpha"], dif.inputs[1])
        ab = Nn.new("ShaderNodeMath"); ab.operation = "ABSOLUTE"; L.new(dif.outputs[0], ab.inputs[0])
        near = Nn.new("ShaderNodeMath"); near.operation = "LESS_THAN"; near.name = f"tol{k}"; near.inputs[1].default_value = 0.05
        L.new(ab.outputs[0], near.inputs[0])
        m2 = Nn.new("ShaderNodeMath"); m2.operation = "MULTIPLY"; L.new(m2a.outputs[0], m2.inputs[0]); L.new(near.outputs[0], m2.inputs[1])
        on = Nn.new("ShaderNodeMath"); on.operation = "MULTIPLY"; on.name = f"on{k}"; on.inputs[1].default_value = 0.0
        L.new(m2.outputs[0], on.inputs[0])
        sc = Nn.new("ShaderNodeVectorMath"); sc.operation = "SCALE"
        L.new(tex.outputs["Color"], sc.inputs[0]); L.new(on.outputs[0], sc.inputs["Scale"])
        if total is None:
            total = sc
        else:
            add = Nn.new("ShaderNodeVectorMath"); add.operation = "ADD"
            L.new(total.outputs[0], add.inputs[0]); L.new(sc.outputs[0], add.inputs[1])
            total = add
    mul = Nn.new("ShaderNodeVectorMath"); mul.operation = "MULTIPLY"
    L.new(total.outputs[0], mul.inputs[0]); L.new(gi.outputs["Color"], mul.inputs[1])
    em = Nn.new("ShaderNodeEmission"); em.name = "emission"
    em.inputs["Strength"].default_value = 1.0 / math.pi
    L.new(mul.outputs[0], em.inputs["Color"])
    addsh = Nn.new("ShaderNodeAddShader")
    L.new(gi.outputs[0], addsh.inputs[0]); L.new(em.outputs[0], addsh.inputs[1])
    L.new(addsh.outputs[0], go.inputs[0])
    return g


def _set_group(maps, imgs):
    g = _group()
    for k in range(SLOTS):
        on = g.nodes[f"on{k}"]; tex = g.nodes[f"img{k}"]
        if k not in maps:
            on.inputs[1].default_value = 0.0
            tex.image = None
            continue
        _arr, u0, v0, texel, d0, d1 = maps[k]
        H, W = _arr.shape[:2]
        mp = g.nodes[f"map{k}"]
        mp.inputs[1].default_value = (1.0 / (W * texel), 1.0 / (H * texel), 0.0)
        mp.inputs[2].default_value = (-u0 / (W * texel), -v0 / (H * texel), 0.0)
        g.nodes[f"lo{k}"].inputs[1].default_value = d0
        g.nodes[f"hi{k}"].inputs[1].default_value = d1
        g.nodes[f"rel{k}"].inputs[1].default_value = d0
        g.nodes[f"tol{k}"].inputs[1].default_value = 1e6     # (per-texel depth not used: each layer has its range)
        on.inputs[1].default_value = 1.0
        tex.image = imgs[k]
    g.update_tag()


def _output(mat):
    outs = [n for n in mat.node_tree.nodes if n.type == "OUTPUT_MATERIAL"]
    for n in outs:
        if n.is_active_output:
            return n
    return outs[0] if outs else None


def _wrap(mat):
    """The emission of the reflected light added to a receiving material (once; again after an editor rebuild)."""
    from . import materials, glass
    if mat is None or not mat.use_nodes or mat.node_tree is None or materials.is_transmissive(mat):
        return False
    out = _output(mat)
    if out is None or not out.inputs["Surface"].is_linked:
        return False
    nt = mat.node_tree
    link = out.inputs["Surface"].links[0]
    src = link.from_node
    bsdf = next((x for x in nt.nodes if x.type == "BSDF_PRINCIPLED"), None)
    tint = bsdf.inputs.get("Base Color") if bsdf is not None else (0.8, 0.8, 0.8)
    if src.type == "GROUP" and src.node_tree is not None and src.node_tree.name == GROUP:
        glass._set_tint(nt, src, tint)
        return None
    g = nt.nodes.new("ShaderNodeGroup")
    g.node_tree = _group()
    g.name = TAG
    g.label = "Reflected caustics"
    g.location = (out.location.x - 200, out.location.y + 160)
    nt.links.new(link.from_socket, g.inputs[0])
    glass._set_tint(nt, g, tint)
    nt.links.new(g.outputs[0], out.inputs["Surface"])
    return True


def strip(mat):
    """The wrapper out of one material (saving to the library, real-time export)."""
    if mat is None or mat.node_tree is None:
        return False
    nt = mat.node_tree
    done = False
    for n in [n for n in nt.nodes if n.type == "GROUP" and n.node_tree is not None and n.node_tree.name == GROUP]:
        if n.inputs[0].is_linked:
            src = n.inputs[0].links[0].from_socket
            for l in list(n.outputs[0].links):
                nt.links.new(src, l.to_socket)
        nt.nodes.remove(n)
        done = True
    return done


def strip_materials(mats):
    """Before a material leaves the scene (library save): without the wrapper. The next image puts it back."""
    n = sum(1 for m in mats if strip(m))
    if n:
        _CACHE["epoch"] = None
        _rain_again()
    return n


def remove_all():
    n = 0
    for mat in bpy.data.materials:
        if strip(mat):
            n += 1
    for im in [im for im in bpy.data.images if im.get(IMG_TAG)]:
        bpy.data.images.remove(im)
    g = bpy.data.node_groups.get(GROUP)
    if g is not None:
        bpy.data.node_groups.remove(g)
    d = _CACHE.get("dir")
    if d:
        shutil.rmtree(d, ignore_errors=True)
    _CACHE.update(key=None, epoch=None, receivers=set(), dir=None)
    if n:
        _rain_again()
    try:
        from . import ocean
        ocean.set_caustic_area(None, (0.0, 0.0, 1.0))      # (the sun passes the sea evenly again)
    except Exception:
        pass
    return n


# ---------------------------------------------------------------- entry point

_UNDER = {"epoch": None, "boxes": []}


def lamp_under_water(ob):
    """Is this lamp under the surface of a water with real waves that draws sharp caustics? Its light leaving the
    water is then made here (refraction, with the net of light): Cycles must not add its own too (MNEE gave it
    without the net, and the two together doubled it)."""
    if not enabled() or ob.type != "LIGHT" or ob.data.type == "SUN":
        return False
    from .render import STATE
    if _UNDER["epoch"] != STATE.epoch:
        boxes = []
        from .render import is_caustic_caster
        for w in _water_objects():
            if STATE.caustics and is_caustic_caster(w):
                pts = [w.matrix_world @ Vector(c) for c in w.bound_box]
                boxes.append((min(p.x for p in pts), min(p.y for p in pts), max(p.x for p in pts), max(p.y for p in pts),
                              max(p.z for p in pts)))
        _UNDER.update(epoch=STATE.epoch, boxes=boxes)
    p = ob.matrix_world.translation
    return any(x0 <= p.x <= x1 and y0 <= p.y <= y1 and p.z < z for x0, y0, x1, y1, z in _UNDER["boxes"])


def safe_ensure(final=False):
    """ensure(), but whatever goes wrong (memory, an odd mesh) the path tracing goes on without this light: an
    error here stopped every pass and the view stayed on "computing" for good."""
    try:
        ensure(final)
    except Exception as exc:
        import traceback
        log("SIMPLER_REFCAUSTICS", "failed:", repr(exc)[:300])
        traceback.print_exc()
        try:
            remove_all()
        except Exception:
            pass
        from .render import STATE
        LAST.update(state="error", error=repr(exc)[:200], when=time.time())
        _CACHE["epoch"] = STATE.epoch
        _CACHE["key"] = ("failed", _CACHE.get("key"))     # (not tried again at every pass: only after a change)


def ensure(final=False):
    """Before every path-traced image. Off: nothing left in the scene. On: computed again only when the sun, the
    water or what is near it changed; otherwise only the wrappers are checked (a material rebuilt by the editor)."""
    from .render import STATE
    if not enabled():
        if _CACHE["key"] is not None or bpy.data.node_groups.get(GROUP) is not None:
            remove_all()
        LAST.update(state="off")
        return
    if not final and _CACHE["epoch"] == STATE.epoch and _CACHE["key"] is not None:
        return
    waters = _water_objects()
    from . import seacaustics
    sea = seacaustics.active()
    suns = _emitters(waters) if waters else (_suns() if sea else [])
    if (not waters and not sea) or not suns:
        if _CACHE["key"] is not None:
            remove_all()
        LAST.update(state="nothing", seconds=0.0, rays=0, receivers=0)
        _CACHE["epoch"] = STATE.epoch
        return
    key = _fingerprint(waters, suns, final)
    if key != _CACHE["key"]:
        t0 = time.time()
        nl = max(1, len(suns))
        traced, rays, owners = None, 0, []
        bvh = None
        if waters:
            _progress(tr("Luce riflessa dall'acqua: superficie"))
            surfaces = _water_surfaces(waters, 2 if final else 1, (MAX_WATER_VERTS if final else VIEW_WATER_VERTS) // nl)
            _progress(tr("Luce riflessa dall'acqua: oggetti vicini"))
            bvh, owners, offsets = _blockers(waters, 10_000_000 if final else 3_000_000)
        t1 = time.time()
        if bvh is not None:
            traced, rays = _trace(surfaces, suns, bvh, owners, offsets, final)
        # the sea (seacaustics): its caustics on the shallow bottom and its light on the rocks, into the same images
        sea_rect = None
        sea_bottom = None
        if sea:
            sea_suns = [e for e in suns if e.type == "LIGHT" and e.data.type == "SUN"]
            prog = lambda ph, det="", fr=None: _progress(ph, det, fr)
            if seacaustics.CYCLES_BOTTOM and sea_suns:
                # the bottom: a small render of Cycles with the surface of the sea as real water (1.75.2)
                x0, y0, x1, y1 = seacaustics._region(final) or (0.0, 0.0, 0.0, 0.0)
                lv = ocean_level()
                bb, _o, _f = _blockers_box(Vector((x0, y0, lv - 60.0)), Vector((x1, y1, lv + 5.0)),
                                           10_000_000 if final else 3_000_000)
                if bb is not None:
                    sea_bottom = seacaustics._cycles_bottom(sea_suns[0], final, bb, prog)
                if sea_bottom is not None:
                    sea_rect = seacaustics.STATE["rect"]
            st = seacaustics.trace(sea_suns, final, prog, transmit=not seacaustics.CYCLES_BOTTOM)
            if st is not None:
                t2_, r2, own2, _off2 = st
                t2_ = dict(t2_)
                t2_["O"] = t2_["O"] + len(owners)
                owners = list(owners) + list(own2)
                rays += r2
                traced = t2_ if traced is None else {k: np.concatenate([traced[k], t2_[k]]) for k in traced}
                sea_rect = seacaustics.STATE["rect"] if (sea_bottom is not None or not seacaustics.CYCLES_BOTTOM) \
                    else sea_rect
        from . import ocean
        sun0 = next((e for e in suns if e.type == "LIGHT" and e.data.type == "SUN"), None)
        sea_rect = None      # (1.75.12) the sun passes the sea evenly: the image of the bottom only adds its lines
        ocean.set_caustic_area(sea_rect, tuple((sun0.matrix_world.to_quaternion() @ Vector((0.0, 0.0, 1.0))).normalized())
                               if sun0 is not None else (0.0, 0.0, 1.0), seacaustics.STATE.get("feather", 0.5))
        t2 = time.time()
        receivers = set()
        if traced is None:
            maps = {}
        else:
            _progress(tr("Luce riflessa dall'acqua: immagini"))
            maps = _splat(traced, final)
            receivers = {owners[i].name for i in np.unique(traced["O"])}
        if sea_bottom is not None:
            # the bottom's image in the last layer facing up (the reflected light rarely lands facing up)
            maps[4 * LAYERS + LAYERS - 1] = sea_bottom[0]
            receivers |= sea_bottom[1]
        imgs = _write_images(maps)
        _set_group(maps, imgs)
        t3 = time.time()
        _CACHE.update(key=key, receivers=receivers)
        LAST.update(state="on", seconds=round(t3 - t0, 2), rays=int(rays), receivers=len(receivers), when=time.time())
        log("SIMPLER_REFCAUSTICS", f"{t3 - t0:.2f}s", f"(mesh+bvh {t1 - t0:.2f}s, rays {t2 - t1:.2f}s, images {t3 - t2:.2f}s)",
            f"rays={rays}", f"receivers={len(receivers)}", "final" if final else "view",
            " ".join(f"{k}:{m[0].shape[1]}x{m[0].shape[0]}" for k, m in maps.items()))
    _CACHE["epoch"] = STATE.epoch
    wrapped = False
    for name in _CACHE["receivers"]:
        ob = bpy.data.objects.get(name)
        if ob is None:
            continue
        for sl in ob.material_slots:
            try:
                wrapped = _wrap(sl.material) is True or wrapped
            except Exception as exc:
                print(f"SIMPLER_REFCAUSTICS skip {sl.material and sl.material.name}: {exc}", flush=True)
    if wrapped:
        _rain_again()


def _rain_again():
    """(1.75.9) The wrappers changed: the rain (rain.ensure, right after this) must go through the materials again.
    It kept its cache: turned off and on, the light was wrapped around the rain's wet surface instead of inside it -
    the bottom of the sea darker than without (Luca, «test oceano»: caustics at opening, gone after off/on)."""
    try:
        from . import rain
        rain.touch(geometry=False)
    except Exception:
        pass
