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

Imports of Simpler only inside the functions (refcaustics imports this module)."""
import math
import time

import bpy
import numpy as np
from mathutils import Vector
from mathutils.interpolate import poly_3d_calc

from .core import log
from .i18n import tr

RAYS_VIEW = 60_000         # rays per light and glass (shared by the colours of a dispersive glass)
RAYS_FINAL = 320_000
MAX_EVENTS = 16            # crossings and inner reflections followed per ray
REACH_K = 10.0             # the light is followed up to this many times the size of the glass (at least REACH_MIN)
REACH_MIN = 0.6
TEXEL = 0.0004             # metres: the finest texel of the images when only glass draws in them
SMOOTH_TRIS = 800_000      # a glass with more triangles: face normals (no interpolation)
SOFT_K = 0.2               # the patch of a ray that went its own way: blurred by this share of how far its cell landed apart
SOFT_MAX = 0.03            # ... at most this share of the reach
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
    t = render._thickness(ob)
    return 0.0005 < t < 0.02 and render._vessel(ob) and not render._holds_lamp(ob)


def handles(ob):
    """Is the light through this piece made here (and not by MNEE)? Asked by render.refresh_caustics."""
    return not STATE["failed"] and _is_vessel(ob)


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
    out = [ob for ob in bpy.context.scene.objects if _is_vessel(ob) and ob.visible_get()]
    STATE.update(epoch=epoch, names=[o.name for o in out])
    return out


def _optics(ob):
    """Index, colour and bands of the glass of this piece: [(index, rgb weight)], tint."""
    from . import materials, matedit
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
    return bands, tint


def fingerprint(glasses, lights):
    """What the light through the glasses depends on (besides the lights, see refcaustics._fingerprint)."""
    from . import matedit, materials
    parts = []
    lo = Vector((1e18,) * 3); hi = Vector((-1e18,) * 3)
    for ob in glasses:
        mat = next((s.material for s in ob.material_slots if materials.is_transmissive(s.material)), None)
        parts.append((ob.name, tuple(round(x, 5) for r in ob.matrix_world for x in r), len(ob.data.polygons),
                      str(mat.get(matedit.PARAMS_KEY, "")) if mat is not None else ""))
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
    P = co[tv].reshape(nt, 3, 3); Nn = cn[tl].reshape(nt, 3, 3)
    return ([[Vector(P[i, j]) for j in range(3)] for i in range(nt)],
            [[Vector(Nn[i, j]) for j in range(3)] for i in range(nt)])


def _follow(ray_cast, origin, direction, first_limit, reach, owner_of, glass, target, ior, eps=2e-5):
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
        if data is not None:
            tri = idx - data[2]
            w = poly_3d_calc(data[0][tri], loc)
            nn = data[1][tri]
            ns = nn[0] * w[0] + nn[1] * w[1] + nn[2] * w[2]
            if ns.length_squared > 1e-12:
                ns.normalize()
                if (ns.dot(d) < 0.0) == entering:      # (a shading normal on the wrong side: the face's)
                    n = ns
        if n.dot(d) > 0.0:
            n = -n
        eta = (1.0 / ior) if entering else ior
        cosi = min(1.0, -d.dot(n))
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


def _accumulate(acc, plane, tri, V, power, blur_k, spacing, offsets, reach):
    """The triangles of light of one bundle (see the module): V = per ray (landed, hit, normal, distance, polygon,
    weight, events); power: W per cell triangle (rgb), before the weight of the rays; blur_k: blur per metre."""
    P, N, F, B, O = acc
    ok, hit, hn, hd, hidx, wt, ev = V
    a, b, c = tri[:, 0], tri[:, 1], tri[:, 2]
    own = np.searchsorted(offsets, np.maximum(hidx, 0), "right") - 1
    wsum = (wt[a] + wt[b] + wt[c]) / 3.0
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
        F.append(power[same] * wsum[same][:, None])
        B.append(np.maximum(far[same] * blur_k, 0.75 * np.sqrt(ar / 4096.0)))
        O.append(own[a[same]])
    # the rays that went different ways: a third of the light of the cell at each landing point, as a soft patch
    rest = ~same
    if rest.any():
        landed = ok[a].astype(np.int8) + ok[b] + ok[c]
        soft = np.clip(np.where(all3, SOFT_K * wide, 0.8 * SOFT_MAX * reach), 2.0 * spacing, SOFT_MAX * reach)
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
            F.append(power[k] * (wt[v[k]] / 3.0)[:, None])
            B.append(np.maximum(soft[k], hd[v[k]] * blur_k))
            O.append(own[v[k]])


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
            glass[k] = None if d is None else (d[0], d[1], int(offsets[k]))
    if not glass:
        return None
    off_list = [int(o) for o in offsets]
    import bisect

    def owner_of(idx):
        return bisect.bisect_right(off_list, idx) - 1

    ray_cast = bvh.ray_cast
    acc = ([], [], [], [], [])
    rays = 0
    budget = RAYS_FINAL if final else RAYS_VIEW
    for gi, (k, _d) in enumerate(glass.items()):
        ob = owners[k]
        bands, tint = _optics(ob)
        pts = [ob.matrix_world @ Vector(c) for c in ob.bound_box]
        cen = sum(pts, Vector()) / 8.0
        size = max((Vector(map(max, *pts)) - Vector(map(min, *pts))))
        reach = max(REACH_MIN, REACH_K * size)
        for em in lights:
            sun = em.data.type == "SUN"
            col = np.array(em.data.color[:3], np.float64) * float(em.data.energy) * np.array(tint)
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
            spacing = math.sqrt(max(1e-12, (u1 - u0) * (v1 - v0)) / n_rays)
            nu = max(2, int(math.ceil((u1 - u0) / spacing)) + 1); nv = max(2, int(math.ceil((v1 - v0) / spacing)) + 1)
            gu = u0 + np.arange(nu) * spacing; gv = v0 + np.arange(nv) * spacing
            U, Vv = np.meshgrid(gu, gv, indexing="ij")
            plane = np.array(cen)[None, :] + U.reshape(-1, 1) * np.array(u)[None, :] + Vv.reshape(-1, 1) * np.array(v)[None, :]
            nvt = len(plane)
            back = -min(pd) + 0.01                   # (the plane of the grid, moved before the glass)
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
            idx = np.arange(nu * nv).reshape(nu, nv)
            ta = idx[:-1, :-1].ravel(); tb = idx[1:, :-1].ravel(); tc = idx[1:, 1:].ravel(); td = idx[:-1, 1:].ravel()
            tri = np.concatenate([np.stack([ta, tb, tc], 1), np.stack([ta, tc, td], 1)])
            cell = 0.5 * spacing * spacing
            irr_t = (irr[tri[:, 0]] + irr[tri[:, 1]] + irr[tri[:, 2]]) / 3.0
            for bi, (ior, bw) in enumerate(bands):
                ok = np.zeros(nvt, bool); hit = np.zeros((nvt, 3)); hn = np.zeros((nvt, 3)); hd = np.zeros(nvt)
                hidx = np.full(nvt, -1, np.int64); wt = np.zeros(nvt); ev = np.zeros(nvt, np.int32)
                rok = np.zeros(nvt, bool); rhit = np.zeros((nvt, 3)); rhn = np.zeros((nvt, 3)); rhd = np.zeros(nvt)
                rhidx = np.full(nvt, -1, np.int64); rwt = np.zeros(nvt)
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
                        ok[i] = True; hit[i] = loc; hn[i] = nrm; hd[i] = dist_; hidx[i] = ix; wt[i] = w; ev[i] = e
                    if refl is not None and bi == 0:
                        rl, rn, rix, rdist = ray_cast(refl[0], refl[1], reach)
                        if rl is not None and glass.get(owner_of(rix), False) is False:
                            if rn.dot(refl[1]) > 0.0:
                                rn = -rn
                            rok[i] = True; rhit[i] = rl; rhn[i] = rn; rhd[i] = rdist; rhidx[i] = rix; rwt[i] = refl[2]
                power = (cell * irr_t)[:, None] * (col * np.array(bw))[None, :]
                _accumulate(acc, plane, tri, (ok, hit, hn, hd, hidx, wt, ev), power, blur_k, spacing, offsets, reach)
                if bi == 0:
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
