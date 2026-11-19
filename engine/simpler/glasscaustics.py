"""Caustiche del vetro (18/11, Luca: «non possiamo aspettare la versione 2»): the light of the sun and of the lamps
that goes THROUGH a glass - a tumbler, a bottle, a vase - followed from the light, as refcaustics does for the light
reflected by water. What it draws: the dark shadow of the glass with the bright patterns of light in it, sharp where
the glass focuses the light, and coloured when the glass has «Dispersione».

Why: the sharp caustics of Cycles (MNEE) find almost no path through a cut glass (tried on Luca's whisky glass: a
black shadow, nothing in it), and the path tracing alone finds the sun only by chance. So, for the thin-walled vessels
(render._vessel), with the caustics «Nitide»:

- a grid of rays leaves each light towards the glass. Each ray is refracted where it enters and leaves the glass
  (Snell, the index of the material; total reflection inside followed; the Fresnel share lost at each crossing), for
  as many crossings as it takes, and lands on what is around. The first reflection on the outside of the glass is
  followed too (the streaks of light a glass throws around itself);
- three neighbouring rays that went the same way carry the light of their cell of the grid onto the triangle they
  land on - small triangle: bright (the caustic), large: faint; rays that went different ways each leave their share
  as a soft patch;
- with «Dispersione» the same for red, green and blue, each with its own index (as matedit.dispersive_glass);
- the light is added to the images of refcaustics (same projection, same shader): the glass itself stops the direct
  light in Cycles (its shadow shortcut off, no MNEE on it: render.refresh_caustics), so nothing is counted twice.

(19/11, Luca: «un bicchiere d'oro colpito dalla luce genera riflessi dorati: dove sono le nostre caustiche
riflessive?») The same for the light a polished METAL piece throws around itself: Cycles finds it only by chance
(with the sun: never), and MNEE does not reflect. The small pieces of smooth metal (METAL_*) are casters too: their
rays are reflected (as many times as it takes - the inside of a cup), each time tinted by the colour of the metal,
and land like the others; the blur grows with the roughness. Nothing to take away in Cycles: a metal is opaque,
its shadow stays, this light is only added.

Imports of Simpler only inside the functions (refcaustics imports this module)."""
import math
import time

import bpy
import numpy as np
from mathutils import Vector
from mathutils.interpolate import poly_3d_calc

from .core import log
from .i18n import tr

RAYS_VIEW = 60_000         # rays per light, shared by the pieces (each at least RAYS_MIN_*) and by the colours of a dispersive glass
RAYS_FINAL = 320_000
RAYS_MIN_VIEW = 8_000
RAYS_MIN_FINAL = 40_000
AIM_CELLS = 128            # the rays are aimed: a first look on this many cells along the longer side finds where the piece is
MAX_EVENTS = 40            # crossings and inner reflections followed per ray (a diamond keeps the light in for long)
REACH_K = 4.0              # the light is followed up to this many times the size of the piece (at least REACH_MIN)
REACH_MIN = 0.25           # (19/11: 10 times and 0.6 m - the images covered 1.9 m around two rings, texels of 1 mm: the
                           # crescents and the sparkles were there, blurred; now 0.45 mm in the final render)
TEXEL = 0.0004             # metres: the finest texel of the images when only glass draws in them
SMOOTH_TRIS = 4_000_000    # a piece with more triangles: face normals (no interpolation)
METAL_MIN = 0.6            # «Metallo» from here up, «Rugosità» up to METAL_ROUGH, largest side up to METAL_SIZE (m)
METAL_ROUGH = 0.35
METAL_SIZE = 1.2
SOFT_K = 0.2               # the patch of a ray that went its own way: blurred by this share of how far its cell landed apart
SOFT_MAX = 0.03            # ... at most this share of the reach
SOFT_SIZE = 0.12           # ... and this share of the size of the piece (a gem: sparkles, not a glow)
STATE = {"failed": False}


def _is_vessel(ob):
    from . import render, materials, water
    from .core import INTERNAL_KEY
    if ob.type != "MESH" or ob.get("simpler_trashed") or ob.get(INTERNAL_KEY) or ob.get("simpler_twin") or ob.hide_render:
        return False
    if not any(materials.is_transmissive(s.material) for s in ob.material_slots):
        return False
    if water.water_material(ob) is not None:
        return False
    if render.no_caustics(ob):
        return False
    # (19/11, Luca's rings beside a render of D5: «i diamantini come generano quelle caustiche, e guarda il nostro») every
    # small round piece of glass, whatever its thickness: gems and solid glass too. Their meshes are often not closed
    # (the diamonds of his rings: thickness 0 even welded, never casters before) - following the rays needs no
    # closed mesh, and MNEE found little in a brilliant cut anyway
    return render._vessel(ob) and not render._holds_lamp(ob)


def _metal_of(mat):
    """(colour, roughness) of a polished metal material, or None."""
    from . import matedit
    if mat is None:
        return None
    mp = matedit.params_of(mat)
    try:
        if mp is not None:
            if float(mp["transmission"]["weight"]) > 0.5:
                return None
            met = float(mp["metallic"]["value"]); rough = float(mp["roughness"]["value"])
            col = tuple(float(c) for c in mp["color"]["tint"][:3])
            if mp["metallic"]["map"].get("image") or mp["roughness"]["map"].get("image"):
                return None                       # (painted metal, rust: not a mirror all over)
        else:
            b = next((n for n in mat.node_tree.nodes if n.type == "BSDF_PRINCIPLED"), None) if mat.node_tree else None
            if b is None or b.inputs["Metallic"].is_linked or b.inputs["Roughness"].is_linked:
                return None
            met = float(b.inputs["Metallic"].default_value); rough = float(b.inputs["Roughness"].default_value)
            col = tuple(b.inputs["Base Color"].default_value[:3])
    except (KeyError, TypeError, ValueError, AttributeError):
        return None
    if met < METAL_MIN or rough > METAL_ROUGH:
        return None
    return tuple(min(1.0, max(0.0, c)) for c in col), rough


def _is_metal(ob):
    from .core import INTERNAL_KEY
    if ob.type != "MESH" or ob.get("simpler_trashed") or ob.get(INTERNAL_KEY) or ob.get("simpler_twin") or ob.hide_render:
        return False
    if len(ob.data.polygons) < 8 or max(ob.dimensions) > METAL_SIZE or max(ob.dimensions) < 0.005:
        return False
    from . import render
    if render.no_caustics(ob):
        return False
    return any(_metal_of(s.material) is not None for s in ob.material_slots)


def _switch(key):
    """«Caustiche riflesse» / «Caustiche rifratte» of the Rendering panel: they turn this light off too (Luca, 19/11:
    «se metto reflective caustics off perché si vedono?» - they only spoke to the path tracing of Cycles)."""
    from .render import STATE as RS
    return bool(RS.config.get(key, True))


def handles(ob):
    """Is the light through this piece made here (and not by MNEE)? Asked by render.refresh_caustics."""
    return not STATE["failed"] and _switch("causticsRefractive") and _is_vessel(ob)


def casters():
    from .render import STATE as RS
    if not RS.caustics or STATE["failed"]:
        return []
    # (asked before every pass: the scene is walked only when something changed)
    epoch = getattr(RS, "epoch", None)
    if STATE.get("epoch") == epoch and epoch is not None:
        out = [bpy.data.objects.get(n) for n in STATE.get("names", ())]
        if all(o is not None for o in out):
            return out
    refr, refl = _switch("causticsRefractive"), _switch("causticsReflective")
    out = [ob for ob in bpy.context.scene.objects
           if ((refr and _is_vessel(ob)) or (refl and _is_metal(ob))) and ob.visible_get()]
    STATE.update(epoch=epoch, names=[o.name for o in out])
    return out


def _optics(ob):
    """Index, colour and bands of the glass of this piece: [(index, rgb weight)], tint. A metal: [(None, white)], its
    colour, and its roughness as third value (glass: 0)."""
    from . import materials, matedit
    if not _is_vessel(ob):
        m = next((_metal_of(s.material) for s in ob.material_slots if _metal_of(s.material) is not None), None)
        if m is not None:
            return [(None, (1.0, 1.0, 1.0))], m[0], m[1]
    mat = next((s.material for s in ob.material_slots if materials.is_transmissive(s.material)), None)
    ior, tint, bands = 1.5, (1.0, 1.0, 1.0), None
    mp = matedit.params_of(mat) if mat is not None else None
    if mp is not None:
        t = mp["transmission"]
        ior = max(1.01, float(t.get("ior", 1.5)))
        try:
            tint = tuple(float(c) for c in mp["color"]["tint"][:3])
        except (KeyError, TypeError, ValueError):
            pass
        if t.get("dispersion") and not t.get("thin"):
            abbe = max(5.0, float(t.get("abbe", 55.0)))
            boost = max(0.0, float(t.get("dispersionBoost", 1.0)))
            B = (ior - 1.0) / abbe / (1 / 0.4861 ** 2 - 1 / 0.6563 ** 2) * boost
            A = ior - B / 0.5893 ** 2
            bands = [(A + B / lam ** 2, tuple(w)) for lam, w in
                     ((0.610, (1.0, 0.0, 0.0)), (0.550, (0.0, 1.0, 0.0)), (0.465, (0.0, 0.0, 1.0)))]
    elif mat is not None and mat.node_tree is not None:
        b = next((n for n in mat.node_tree.nodes if n.type == "BSDF_PRINCIPLED"), None)
        if b is not None:
            ior = max(1.01, float(b.inputs["IOR"].default_value))
            tint = tuple(b.inputs["Base Color"].default_value[:3])
    if bands is None:
        bands = [(ior, (1.0, 1.0, 1.0))]
    # (a pale tint: the light crosses the walls twice or more - the colour of the glass, not its square)
    tint = tuple(min(1.0, max(0.0, c)) ** 0.5 for c in tint)
    return bands, tint, 0.0


def fingerprint(glasses, lights):
    """What the light through the glasses depends on (besides the lights, see refcaustics._fingerprint)."""
    from . import matedit, materials
    parts = [_switch("causticsRefractive"), _switch("causticsReflective")]
    lo = Vector((1e18,) * 3); hi = Vector((-1e18,) * 3)
    for ob in glasses:
        parts.append((ob.name, tuple(round(x, 5) for r in ob.matrix_world for x in r), len(ob.data.polygons),
                      tuple(str(s.material.get(matedit.PARAMS_KEY, "")) for s in ob.material_slots if s.material is not None),
                      str(_optics(ob))))
        for c in ob.bound_box:
            p = ob.matrix_world @ Vector(c)
            lo = Vector(map(min, lo, p)); hi = Vector(map(max, hi, p))
    if glasses:
        reach = max(REACH_MIN, REACH_K * max(hi - lo))
        for ob in bpy.context.scene.objects:
            if ob.type != "MESH" or ob in glasses:
                continue
            try:
                pts = [ob.matrix_world @ Vector(c) for c in ob.bound_box]
            except Exception:
                continue
            a = Vector(map(min, *pts)); b = Vector(map(max, *pts))
            if all(a[i] <= hi[i] + reach and b[i] >= lo[i] - reach for i in range(3)):
                parts.append((ob.name, tuple(round(x, 4) for r in ob.matrix_world for x in r), ob.hide_render,
                              len(ob.data.polygons)))
    return hash(tuple(parts))


def _glass_data(k, meta):
    """Per triangle of a glass in the BVH: its three corners and their shading normals in the world (lists of
    Vector), or None for a very heavy one (face normals then)."""
    orig, m, me = meta[k]
    nt = len(me.loop_triangles)
    if nt > SMOOTH_TRIS:
        return None
    co = np.empty(len(me.vertices) * 3, np.float32); me.vertices.foreach_get("co", co)
    co = co.reshape(-1, 3).astype(np.float64) @ m[:3, :3].T + m[:3, 3]
    tv = np.empty(nt * 3, np.int32); me.loop_triangles.foreach_get("vertices", tv)
    tl = np.empty(nt * 3, np.int32); me.loop_triangles.foreach_get("loops", tl)
    cn = np.empty(len(me.loops) * 3, np.float32); me.corner_normals.foreach_get("vector", cn)
    nm = np.linalg.inv(m[:3, :3]).T
    cn = cn.reshape(-1, 3).astype(np.float64) @ nm.T
    cn /= np.maximum(np.linalg.norm(cn, axis=1, keepdims=True), 1e-12)
    # (arrays: the Vectors of a triangle are made when a ray meets it - made for every triangle of two rings of
    # 900,000 triangles, they took longer than all the rays)
    return co[tv].reshape(nt, 3, 3), cn[tl].reshape(nt, 3, 3)


def _follow(ray_cast, origin, direction, first_limit, reach, owner_of, glass, target, ior, eps=2e-5):
    # (ior None: the target is a metal - every crossing of it is a reflection; events = how many)
    """One ray of light. Returns (kind, hit, normal, last distance, polygon, weight, events, reflection) - kind 0:
    nothing (it missed the glass, or was lost), 1: landed. reflection: (point, direction, share) of the light the
    outside of the glass sends back at the first crossing, or None."""
    pos = origin; d = direction
    weight = 1.0
    events = 0
    refl = None
    limit = first_limit
    for _ in range(MAX_EVENTS + 1):
        loc, ng, idx, dist = ray_cast(pos, d, limit)
        if loc is None:
            return 0, None, None, 0.0, -1, 0.0, events, refl
        k = owner_of(idx)
        data = glass.get(k, False)
        if data is False:                       # not glass
            if events == 0:
                return 0, None, None, 0.0, -1, 0.0, 0, None          # (the glass is not what this ray meets)
            if ng.dot(d) > 0.0:
                ng = -ng
            return 1, loc, ng, dist, idx, weight, events, refl
        if events == 0 and k != target:
            return 0, None, None, 0.0, -1, 0.0, 0, None              # (another glass first: its own grid has it)
        if events >= MAX_EVENTS:
            return 0, None, None, 0.0, -1, 0.0, events, refl
        entering = ng.dot(d) < 0.0
        n = ng
        mirror = data[3] if data is not None else glass.get(("metal", k), False)
        if data is not None:
            tri = idx - data[2]
            c = data[4].get(tri)
            if c is None:
                c = ([Vector(x) for x in data[0][tri]], [Vector(x) for x in data[1][tri]])
                data[4][tri] = c
            w = poly_3d_calc(c[0], loc)
            nn = c[1]
            ns = nn[0] * w[0] + nn[1] * w[1] + nn[2] * w[2]
            if ns.length_squared > 1e-12:
                ns.normalize()
                if (ns.dot(d) < 0.0) == entering:      # (a shading normal on the wrong side: the face's)
                    n = ns
        if n.dot(d) > 0.0:
            n = -n
        cosi = min(1.0, -d.dot(n))
        if mirror or ior is None:
            if not mirror:
                return 0, None, None, 0.0, -1, 0.0, events, refl     # (a glass on the way of the light of a metal)
            d = (d + n * (2.0 * cosi)).normalized()
            pos = loc + ng * (eps if ng.dot(d) > 0.0 else -eps)
            events += 1
            limit = reach
            continue
        eta = (1.0 / ior) if entering else ior
        s2 = eta * eta * (1.0 - cosi * cosi)
        if s2 >= 1.0:                           # total reflection inside
            d = (d + n * (2.0 * cosi)).normalized()
            pos = loc + ng * (eps if ng.dot(d) > 0.0 else -eps)
        else:
            cost = math.sqrt(1.0 - s2)
            rs = (eta * cosi - cost) / (eta * cosi + cost)
            rp = (eta * cost - cosi) / (eta * cost + cosi)
            R = 0.5 * (rs * rs + rp * rp)
            if events == 0:
                rd = (d + n * (2.0 * cosi)).normalized()
                refl = (loc + ng * (eps if ng.dot(rd) > 0.0 else -eps), rd, R)
            d = (d * eta + n * (eta * cosi - cost)).normalized()
            weight *= 1.0 - R
            pos = loc + ng * (eps if ng.dot(d) > 0.0 else -eps)
        events += 1
        limit = reach
    return 0, None, None, 0.0, -1, 0.0, events, refl


def _accumulate(acc, plane, tri, V, power, blur_k, spacing, offsets, reach, size=None):
    """The triangles of light of one bundle (see the module): V = per ray (landed, hit, normal, distance, polygon,
    weight, events); power: W per cell triangle (rgb), before the weight of the rays; blur_k: blur per metre."""
    P, N, F, B, O = acc
    ok, hit, hn, hd, hidx, wt, ev = V
    a, b, c = tri[:, 0], tri[:, 1], tri[:, 2]
    own = np.searchsorted(offsets, np.maximum(hidx, 0), "right") - 1
    wsum = (wt[a] + wt[b] + wt[c]) / 3.0          # (per colour)
    all3 = ok[a] & ok[b] & ok[c]
    dab = np.linalg.norm(np.where(all3[:, None], hit[a] - hit[b], 0.0), axis=1)
    dbc = np.linalg.norm(np.where(all3[:, None], hit[b] - hit[c], 0.0), axis=1)
    dca = np.linalg.norm(np.where(all3[:, None], hit[c] - hit[a], 0.0), axis=1)
    wide = np.maximum(np.maximum(dab, dbc), dca)
    far = (hd[a] + hd[b] + hd[c]) / 3.0
    same = all3 & (own[a] == own[b]) & (own[a] == own[c]) & (ev[a] == ev[b]) & (ev[a] == ev[c]) \
        & (np.einsum("ij,ij->i", hn[a], hn[b]) > 0.9) & (np.einsum("ij,ij->i", hn[a], hn[c]) > 0.9) \
        & (wide < 40.0 * spacing + 0.35 * far)
    if same.any():
        T = np.stack([hit[a[same]], hit[b[same]], hit[c[same]]], 1)
        ar = 0.5 * np.linalg.norm(np.cross(T[:, 1] - T[:, 0], T[:, 2] - T[:, 0]), axis=1)
        P.append(T)
        N.append(hn[a[same]])
        F.append(power[same] * wsum[same])
        B.append(np.maximum(far[same] * blur_k, 0.75 * np.sqrt(ar / 4096.0)))
        O.append(own[a[same]])
    # the rays that went different ways: a third of the light of the cell at each landing point, as a soft patch
    rest = ~same
    if rest.any():
        landed = ok[a].astype(np.int8) + ok[b] + ok[c]
        top = SOFT_MAX * reach if size is None else min(SOFT_MAX * reach, max(SOFT_SIZE * size, 4.0 * spacing))
        soft = np.clip(np.where(all3, SOFT_K * wide, 0.8 * top), 2.0 * spacing, top)
        for v in (a, b, c):
            k = rest & ok[v]
            if not k.any():
                continue
            pts = hit[v[k]]; nn = hn[v[k]]
            # a small triangle lying on the surface it landed on
            t1 = np.cross(nn, np.array((0.0, 0.0, 1.0)))
            flat = np.linalg.norm(t1, axis=1) < 1e-3
            t1[flat] = np.cross(nn[flat], np.array((1.0, 0.0, 0.0)))
            t1 /= np.maximum(np.linalg.norm(t1, axis=1, keepdims=True), 1e-12)
            t2 = np.cross(nn, t1)
            s = spacing
            P.append(np.stack([pts + t1 * s, pts - t1 * (0.5 * s) + t2 * (0.87 * s), pts - t1 * (0.5 * s) - t2 * (0.87 * s)], 1))
            N.append(nn)
            F.append(power[k] * (wt[v[k]] / 3.0))
            B.append(np.maximum(soft[k], hd[v[k]] * blur_k))
            O.append(own[v[k]])


def _aimed_grid(u0, u1, v0, v1, n_rays, on_target):
    """The grid of rays only where the piece is (19/11: the small diamonds set in a ring took 1% of the rays of a
    grid over their box, the central stone 7%). A first look on AIM_CELLS cells: the cells with a corner on the
    piece, and their neighbours, are filled with a fine grid - n_rays in all. Returns (U, V of the points, triangles,
    spacing) or None."""
    cs = max(u1 - u0, v1 - v0, 1e-9) / AIM_CELLS
    ncu = max(1, int(math.ceil((u1 - u0) / cs))); ncv = max(1, int(math.ceil((v1 - v0) / cs)))
    H = np.zeros((ncu + 1, ncv + 1), bool)
    for i in range(ncu + 1):
        for j in range(ncv + 1):
            H[i, j] = on_target(u0 + i * cs, v0 + j * cs)
    M = H[:-1, :-1] | H[1:, :-1] | H[:-1, 1:] | H[1:, 1:]
    D = M.copy()
    D[1:, :] |= M[:-1, :]; D[:-1, :] |= M[1:, :]; D[:, 1:] |= M[:, :-1]; D[:, :-1] |= M[:, 1:]
    if not D.any():
        return None
    # (cells too many for the rays - fewer than 3 x 3 each: twice as large, until they are enough)
    while D.sum() * 16 > n_rays and min(D.shape) > 1:
        a2, b2 = (D.shape[0] + 1) // 2, (D.shape[1] + 1) // 2
        P2 = np.zeros((a2 * 2, b2 * 2), bool); P2[:D.shape[0], :D.shape[1]] = D
        D = P2.reshape(a2, 2, b2, 2).any(axis=(1, 3))
        cs *= 2.0
    cells = np.argwhere(D)
    m = int(round(math.sqrt(max(1, n_rays) / len(cells)))) - 1
    m = min(max(m, 1), 64)
    spacing = cs / m
    a = np.arange(m + 1) / m
    A, B = np.meshgrid(a, a, indexing="ij")                  # (m+1, m+1) inside one cell
    U = (u0 + (cells[:, 0, None, None] + A[None]) * cs).reshape(-1)
    V = (v0 + (cells[:, 1, None, None] + B[None]) * cs).reshape(-1)
    idx = np.arange((m + 1) * (m + 1)).reshape(m + 1, m + 1)
    ta = idx[:-1, :-1].ravel(); tb = idx[1:, :-1].ravel(); tc = idx[1:, 1:].ravel(); td = idx[:-1, 1:].ravel()
    t1 = np.concatenate([np.stack([ta, tb, tc], 1), np.stack([ta, tc, td], 1)])
    base = (np.arange(len(cells)) * (m + 1) * (m + 1))[:, None, None]
    tri = (t1[None] + base).reshape(-1, 3)
    return U, V, tri, spacing


def trace(glasses, lights, final=False, progress=None):
    """Returns (dict of arrays as refcaustics._trace, rays, owners, offsets) or None."""
    from . import refcaustics as rc
    if not glasses or not lights:
        return None
    t0 = time.time()
    lo, hi = rc._bounds(glasses)
    bvh, owners, offsets = rc._blockers_box(lo, hi, 10_000_000 if final else 3_000_000)
    if bvh is None:
        return None
    meta = list(rc.META)
    names = {ob.name for ob in glasses}
    glass = {}                                  # owner index -> (corners, normals, first polygon) or None
    for k, ow in enumerate(owners):
        if ow.name in names:
            d = _glass_data(k, meta)
            metal = not _is_vessel(ow)
            glass[k] = None if d is None else (d[0], d[1], int(offsets[k]), metal, {})
            if metal:
                glass[("metal", k)] = True
    if not glass:
        return None
    off_list = [int(o) for o in offsets]
    import bisect

    def owner_of(idx):
        return bisect.bisect_right(off_list, idx) - 1

    ray_cast = bvh.ray_cast
    reflect_on = _switch("causticsReflective")      # (the streaks the outside of a glass throws around: reflected)
    acc = ([], [], [], [], [])
    rays = 0
    pieces = [kv for kv in glass.items() if not isinstance(kv[0], tuple)]
    budget = max(RAYS_MIN_FINAL if final else RAYS_MIN_VIEW, (RAYS_FINAL if final else RAYS_VIEW) // max(1, len(pieces)))
    for gi, (k, _d) in enumerate(pieces):
        ob = owners[k]
        bands, tint, rough = _optics(ob)
        is_metal = bands[0][0] is None
        pts = [ob.matrix_world @ Vector(c) for c in ob.bound_box]
        cen = sum(pts, Vector()) / 8.0
        size = max((Vector(map(max, *pts)) - Vector(map(min, *pts))))
        reach = max(REACH_MIN, REACH_K * size)
        for em in lights:
            sun = em.data.type == "SUN"
            col = np.array(em.data.color[:3], np.float64) * float(em.data.energy) * (1.0 if is_metal else np.array(tint))
            mcol = np.array(tint, np.float64)
            if sun:
                d0 = -(em.matrix_world.to_quaternion() @ Vector((0.0, 0.0, 1.0))).normalized()
                blur_k = math.tan(max(float(em.data.angle), 1e-4) / 2.0)
            else:
                L = em.matrix_world.translation.copy()
                if (cen - L).length < 1e-4:
                    continue
                d0 = (cen - L).normalized()
            up = Vector((0.0, 0.0, 1.0)) if abs(d0.z) < 0.9 else Vector((1.0, 0.0, 0.0))
            u = d0.cross(up).normalized(); v = d0.cross(u).normalized()
            pu = [(p - cen).dot(u) for p in pts]; pv = [(p - cen).dot(v) for p in pts]; pd = [(p - cen).dot(d0) for p in pts]
            u0, u1, v0, v1 = min(pu), max(pu), min(pv), max(pv)
            n_rays = max(2500, budget // len(bands))
            back = -min(pd) + 0.01                   # (the plane of the grid, moved before the glass)
            first0 = back + max(pd) + 0.02

            def on_target(a, b, _k=k):
                p = cen + u * a + v * b
                if sun:
                    loc, _n, ix, _ds = ray_cast(p - d0 * back, d0, first0)
                else:
                    dv = p - L
                    loc, _n, ix, _ds = ray_cast(L, dv.normalized(), dv.length + size)
                return loc is not None and owner_of(ix) == _k

            g = _aimed_grid(u0, u1, v0, v1, n_rays, on_target)
            if g is None:
                continue
            U, Vv, tri, spacing = g
            plane = np.array(cen)[None, :] + U.reshape(-1, 1) * np.array(u)[None, :] + Vv.reshape(-1, 1) * np.array(v)[None, :]
            nvt = len(plane)
            if sun:
                starts = plane - np.array(d0)[None, :] * back
                dirs = None
                irr = np.ones(nvt)
                first = back + max(pd) + 0.02
            else:
                dvec = plane - np.array(L)[None, :]
                dist = np.maximum(np.linalg.norm(dvec, axis=1), 1e-6)
                dirs = dvec / dist[:, None]
                _dd, irr, _ld, _L, radius = rc._lamp_terms(em, plane)
                blur_k = radius / max((cen - L).length, 1e-3)
                first = float(dist.max()) + size
            cell = 0.5 * spacing * spacing
            irr_t = (irr[tri[:, 0]] + irr[tri[:, 1]] + irr[tri[:, 2]]) / 3.0
            for bi, (ior, bw) in enumerate(bands):
                ok = np.zeros(nvt, bool); hit = np.zeros((nvt, 3)); hn = np.zeros((nvt, 3)); hd = np.zeros(nvt)
                hidx = np.full(nvt, -1, np.int64); wt = np.zeros((nvt, 3)); ev = np.zeros(nvt, np.int32)
                rok = np.zeros(nvt, bool); rhit = np.zeros((nvt, 3)); rhn = np.zeros((nvt, 3)); rhd = np.zeros(nvt)
                rhidx = np.full(nvt, -1, np.int64); rwt = np.zeros((nvt, 3))
                step = max(2000, nvt // 25)
                for i in range(nvt):
                    if progress is not None and i % step == 0:
                        progress(tr("Caustiche del vetro: raggi"), f"{i * 100 // nvt}%", i / nvt)
                    if sun:
                        o = Vector(starts[i]); d = d0
                        # in the shade of something (a wall, a roof)? Towards the sun from before the glass
                        sh, _n, six, _dist = ray_cast(o, -d0, 200.0)
                        if sh is not None and glass.get(owner_of(six), False) is False:
                            f = rc._glass_pass(six, sh, offsets)
                            if f is None or f.max() < 1e-3:
                                continue
                    else:
                        o = L; d = Vector(dirs[i])
                    rays += 1
                    kind, loc, nrm, dist_, ix, w, e, refl = _follow(ray_cast, o, d, first, reach, owner_of, glass, k, ior)
                    if kind == 1:
                        ok[i] = True; hit[i] = loc; hn[i] = nrm; hd[i] = dist_; hidx[i] = ix; ev[i] = e
                        wt[i] = (mcol ** e) if is_metal else w          # (a metal: its colour at every reflection)
                    if refl is not None and bi == 0 and not is_metal and reflect_on:
                        rl, rn, rix, rdist = ray_cast(refl[0], refl[1], reach)
                        if rl is not None and glass.get(owner_of(rix), False) is False:
                            if rn.dot(refl[1]) > 0.0:
                                rn = -rn
                            rok[i] = True; rhit[i] = rl; rhn[i] = rn; rhd[i] = rdist; rhidx[i] = rix; rwt[i] = refl[2]
                power = (cell * irr_t)[:, None] * (col * np.array(bw))[None, :]
                # (a metal that is not a mirror: its light spreads with the distance, as its roughness)
                bk = blur_k + (0.7 * rough * rough if is_metal else 0.0)
                _accumulate(acc, plane, tri, (ok, hit, hn, hd, hidx, wt, ev), power, bk, spacing, offsets, reach, size)
                if bi == 0 and not is_metal:
                    powr = (cell * irr_t)[:, None] * (np.array(em.data.color[:3], np.float64) * float(em.data.energy))[None, :]
                    _accumulate(acc, plane, tri, (rok, rhit, rhn, rhd, rhidx, rwt, np.zeros(nvt, np.int32)), powr, blur_k,
                                spacing, offsets, reach)
    P, N, F, B, O = acc
    if not P:
        return None
    out = {"P": np.concatenate(P), "N": np.concatenate(N), "F": np.concatenate(F), "B": np.concatenate(B),
           "O": np.concatenate(O)}
    log("SIMPLER_GLASSCAUSTICS", f"{time.time() - t0:.2f}s glasses={len(glass)} lights={len(lights)} rays={rays} "
        f"triangles of light={len(out['P'])}", "final" if final else "view")
    return out, rays, owners, offsets
