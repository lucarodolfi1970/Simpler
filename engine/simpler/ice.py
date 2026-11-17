"""Acqua ghiacciata: the water of a material «Acqua» freezes while it snows («Ghiaccia quando nevica», Avanzate of the
water).

Settings in the water of the material (water.py, MKEY, part "ice"):
  on       freezes while it snows (no snow: the water as it is)
  amount   0..1 «Ghiaccio»: from the shore towards the middle - 0 open water, a thin frame, ... 1 all frozen
  clear    0..1 «Trasparenza del ghiaccio»: 1 black ice (clear, smooth, the bottom shows), 0 milky ice (rough, pale)
  bubbles  0..1 «Bolle d'aria»: air caught in the ice, white specks under the surface
  cracks, cracksFine  0..2 «Crepe grandi», «Crepe sottili»: how marked the two nets of cracks are (0 none)

How (geometry only):
  shore    a map over the water (cells of 5 cm or more, 512 at most per side): the surface of the water where it is
           (its triangles at the centre of every cell) and where the ground crosses it (any triangle of the scene within
           3 cm under to 50 cm over the surface - an arch high above does not count); the distance of every cell of open
           water from the nearest shore (jump flooding), divided by the middle of its own water (17/11): 0 at the
           shore, 1 in the middle, of a river as of a lake
  front    ice where  amount * 1.4 - distance + jag * min(4 amount, 1) - 0.04 (1 - amount)  > 0  (jag: noise at three
           scales, ±0.39: tongues and loose plates; at 0 nothing, at 1 everything), soft over ±0.01, a whiter rim at
           the front; blurred as far as the width of the water allows (round fronts on a lake, none on a narrow river)
  ice      Principled inputs of the water mixed by the ice: colour pale blue (clear) to white (milky), roughness
           0.03..0.4, transparency 1..0.45; cracks (Voronoi distance to edge, two scales) and bubbles (Voronoi, a
           share of the cells by «Bolle d'aria») whiter and rougher; a gentle undulation and the cracks in the bump;
           a dusting of snow (noise, more near the shore, as much as it snows) white and rough, not transparent
  waves    the real waves of the water lower as it freezes (water.py: height x (1 - amount))
The real-time view (viewer.js, icePatch) uses the same map and front (noise from the map of the rain), colour,
roughness and transparency; no cracks nor bubbles there.
"""
import json
import math
import os

import bpy

from .core import log

GROUP = "Simpler Ghiaccio v2"
NODE = "simpler_ice"                 # prefix of the nodes added to a water material
IMG = "Simpler Ghiaccio · "
DEFAULTS = {"on": False, "amount": 0.5, "clear": 0.6, "bubbles": 0.3, "cracks": 1.0, "cracksFine": 1.0}
MAP_MAX = 512
MAP_CELL = 0.05
_MAPS = {}                           # material name -> {"sig", "meta", "img"}
_REV = {"n": 0}


def _np():
    import numpy as np
    return np


def settings(mat):
    from . import water
    s = dict(DEFAULTS)
    s.update(water.mat_settings(mat).get("ice") or {})
    return s


def snow_amount():
    """How much it snows now (0: not snowing)."""
    from . import ambience, rain
    r = rain.settings(ambience.state())
    return float(r["snow"]) if (r is not None and r.get("snowing")) else 0.0


def active(mat):
    from . import water
    return water.is_water(mat) and settings(mat)["on"] and snow_amount() > 0.0


def wave_factor(mat):
    """The real waves lower as the water freezes."""
    return 1.0 - settings(mat)["amount"] if active(mat) else 1.0


# ---------------------------------------------------------------- the map of the shore

def _edt(seed):
    """Distance (cells) of every cell from the nearest seed (jump flooding: log2(n) passes of 9 shifts)."""
    np = _np()
    from .snow import _shift
    ny, nx = seed.shape
    I, J = np.meshgrid(np.arange(ny), np.arange(nx), indexing="ij")
    sy = np.where(seed, I, -1).astype(np.int32)
    sx = np.where(seed, J, -1).astype(np.int32)
    big = np.int64(1) << 40

    def dist(cy, cx):
        return np.where(cy >= 0, (I - cy).astype(np.int64) ** 2 + (J - cx).astype(np.int64) ** 2, big)
    step = 1 << max(0, int(math.ceil(math.log2(max(nx, ny)))) - 1)
    steps = []
    while step >= 1:
        steps.append(step)
        step //= 2
    steps += [1]
    for st in steps:
        best = dist(sy, sx)
        for dy in (-st, 0, st):
            for dx in (-st, 0, st):
                if not dy and not dx:
                    continue
                cy = _shift(sy, dy, dx, -1)
                cx = _shift(sx, dy, dx, -1)
                d = dist(cy, cx)
                b = d < best
                sy = np.where(b, cy, sy); sx = np.where(b, cx, sx); best = np.where(b, d, best)
    return np.sqrt(np.where(sy >= 0, dist(sy, sx), big).astype(np.float64))


def _land_objects(users):
    from . import rain, water
    names = {o.name for o in users}
    return [ob for ob in rain._scene_meshes() if ob.name not in names and not ob.get(water.BODY_KEY)]


def _build_map(mat, users):
    np = _np()
    from . import rain, snow
    lo, hi = [], []
    for ob in users:
        c = np.array([ob.matrix_world @ __import__("mathutils").Vector(b) for b in ob.bound_box])
        lo.append(c[:, :2].min(0)); hi.append(c[:, :2].max(0))
    x0, y0 = np.min(lo, axis=0) - 0.5
    x1, y1 = np.max(hi, axis=0) + 0.5
    size = float(max(x1 - x0, y1 - y0, 0.5))
    n = int(min(MAP_MAX, max(16, math.ceil(size / MAP_CELL))))
    cell = size / n
    x0, y0 = float(x0), float(y0)
    Wz = np.full(n * n, -np.inf, dtype=np.float32)
    for ob in users:
        P, box, _V = snow._world_tris(ob, {})
        if len(P):
            snow._raster(P, box, x0, y0, n, n, cell, Wz)
    water = np.isfinite(Wz)
    land = np.zeros(n * n, dtype=bool)

    def band(idx, z):
        w = Wz[idx]
        hit = np.isfinite(w) & (z >= w - 0.03) & (z <= w + 0.5)
        land[idx[hit]] = True
    x1b, y1b = x0 + n * cell, y0 + n * cell
    for ob in _land_objects(users):
        P, box, _V = snow._world_tris(ob, {})
        if not len(P):
            continue
        sel = (box[:, 1] >= x0) & (box[:, 0] <= x1b) & (box[:, 3] >= y0) & (box[:, 2] <= y1b)
        if sel.any():
            snow._raster(P[sel], box[sel], x0, y0, n, n, cell, band)
    seed = (~water | land).reshape(n, n)
    open_ = ~seed
    d = _edt(seed) * cell
    dmax = float(d[open_].max()) if open_.any() else 1.0
    # (17/11, Luca: «già oltre il 10% è tutto bianco: a cosa serve il valore tra 10 e 100?») the distance was blurred over
    # 25 cells and divided by the largest of the whole map. On his valley the water is the material of the ground: under
    # the mountains (well above the water, no shore there) the «open water» reached 844 m from any shore, and the blur
    # crossed the banks of the river (7 cells wide) and gave it about 45 m everywhere - 0.05 of the largest, the same
    # from bank to bank: all of it frozen past 4% of «Ghiaccio». Now each cell is divided by the middle of ITS water (the
    # distance where the way straight up from the shore stops: _local_middle) - 0 at the shore, 1 in the middle, of a
    # river as of a lake - and the blur (round fronts) is as wide as that water allows: none on a river of a few cells.
    rmid = _local_middle(d, open_, cell)
    h = 0.5 * cell                                  # (the first cell of water is half a cell from the shore)
    dn = np.where(open_, np.clip((d - h) / np.maximum(rmid - h, 1e-6), 0.0, 1.0), 0.0)
    from .snow import _box_mean
    r = max(1, n // 40)
    wgt = open_.astype(np.float64)
    rc = rmid / cell
    out = dn.copy()
    for R in (1, 2, 4, 8, r):
        if R > r:
            break
        sel = open_ & (rc >= 4 * R)
        if sel.any():
            b = np.nan_to_num(_box_mean(dn * wgt, wgt, R), nan=0.0)
            out[sel] = b[sel]
    dn = np.where(open_, np.clip(out, 0.0, 1.0), 0.0).astype(np.float32)
    meta = {"x0": x0, "y0": y0, "size": size, "n": n, "cell": cell, "dmax": dmax,
            "water": int(water.sum()), "open": int(open_.sum())}
    return dn, meta


def _local_middle(d, open_, step):
    """(17/11) For every cell of open water the distance from the shore at the middle of its water: the way up from the
    cell, always to the highest of its 4 neighbours (open water only: never across a shore) while a step gains at least
    half a cell - straight across the water, it stops at the middle instead of running along it to a wider place."""
    np = _np()
    ny, nx = d.shape
    idx = np.arange(ny * nx).reshape(ny, nx)
    big = np.where(open_, d, -1e9)
    best, par = big + 0.5 * step, idx.copy()
    for dy, dx in ((-1, 0), (1, 0), (0, -1), (0, 1)):
        sh = np.full_like(big, -1e9)
        si = idx.copy()
        ys, yd = (slice(max(dy, 0), ny + min(dy, 0)), slice(max(-dy, 0), ny + min(-dy, 0)))
        xs, xd = (slice(max(dx, 0), nx + min(dx, 0)), slice(max(-dx, 0), nx + min(-dx, 0)))
        sh[yd, xd] = big[ys, xs]
        si[yd, xd] = idx[ys, xs]
        up = sh > best
        best = np.where(up, sh, best)
        par = np.where(up, si, par)
    par = par.ravel()
    for _ in range(int(math.ceil(math.log2(max(2, ny * nx)))) + 1):     # (pointer jumping: the top of every way)
        nxt = par[par]
        if np.array_equal(nxt, par):
            break
        par = nxt
    return d.ravel()[par].reshape(ny, nx)


def _image(name, dn):
    np = _np()
    n = dn.shape[0]
    img = bpy.data.images.get(name)
    if img is not None and (img.size[0] != n or img.size[1] != n):
        bpy.data.images.remove(img)
        img = None
    if img is None:
        img = bpy.data.images.new(name, n, n, alpha=False, float_buffer=True)
    img.colorspace_settings.name = "Non-Color"
    px = np.zeros((n, n, 4), dtype=np.float32)
    px[..., 0] = px[..., 1] = px[..., 2] = dn
    px[..., 3] = 1.0
    img.pixels.foreach_set(px.ravel())
    img.update()
    img.update_tag()          # (the path tracing keeps its images between passes: without the tag, the old pixels; 1.70.1)
    return img


def _view_file(dn, k):
    np = _np()
    from . import rain
    d = rain._shelter_dir()
    _REV["n"] += 1
    stem = f"ice_{os.getpid()}_{_REV['n']}_{k}"
    with open(os.path.join(d, stem + ".bin"), "wb") as f:
        f.write(dn.astype(np.float16).tobytes())                     # (rows from y0: as three.js reads them)
    return stem + ".bin"


def view_file(name):
    from . import rain
    name = os.path.basename(name or "")
    if not name.startswith("ice_") or not name.endswith(".bin"):
        return ""
    p = os.path.join(rain._shelter_dir(), name)
    return p if os.path.isfile(p) else ""


def _map(mat):
    """The map of this water (made again when the geometry changed)."""
    from . import rain, water
    users = [o for o in water._users(mat) if water.shape_of(o) != "shell"]
    if not users:
        return None
    sig = (rain._geometry_sig(), tuple(sorted(o.name for o in users)))
    got = _MAPS.get(mat.name)
    if got is not None and got["sig"] == sig and bpy.data.images.get(IMG + mat.name) is not None:
        return got
    import time
    t0 = time.time()
    dn, meta = _build_map(mat, users)
    img = _image(IMG + mat.name, dn)
    old = (got or {}).get("meta", {}).get("file")
    if old:
        try:
            os.remove(os.path.join(rain._shelter_dir(), old))
        except OSError:
            pass
    meta["file"] = _view_file(dn, len(_MAPS))
    _MAPS[mat.name] = {"sig": sig, "meta": meta, "img": img.name}
    log(f"SIMPLER_ICE {mat.name}: map {meta['n']}x{meta['n']} cell {meta['cell'] * 100:.1f} cm, "
        f"{meta['open']} cells of open water, farthest from the shore {meta['dmax']:.1f} m, {time.time() - t0:.2f} s")
    return _MAPS[mat.name]


# ---------------------------------------------------------------- the shader (Cycles)

def _group():
    g = bpy.data.node_groups.get(GROUP)
    if g is not None:
        return g
    g = bpy.data.node_groups.new(GROUP, "ShaderNodeTree")
    I = g.interface
    for name, typ, dv in (("Dist", "NodeSocketFloat", 1.0), ("Amount", "NodeSocketFloat", 0.5),
                          ("Clear", "NodeSocketFloat", 0.6), ("Bubbles", "NodeSocketFloat", 0.3),
                          ("Snow", "NodeSocketFloat", 0.0), ("Cracks", "NodeSocketFloat", 1.0),
                          ("CracksFine", "NodeSocketFloat", 1.0), ("BaseIn", "NodeSocketColor", (0.8, 0.8, 0.8, 1.0)),
                          ("RoughIn", "NodeSocketFloat", 0.0), ("TransIn", "NodeSocketFloat", 1.0),
                          ("NormalIn", "NodeSocketVector", (0.0, 0.0, 1.0))):
        s = I.new_socket(name, in_out="INPUT", socket_type=typ)
        s.default_value = dv
    for name, typ in (("Base", "NodeSocketColor"), ("Rough", "NodeSocketFloat"), ("Trans", "NodeSocketFloat"),
                      ("Normal", "NodeSocketVector"), ("Ice", "NodeSocketFloat")):
        I.new_socket(name, in_out="OUTPUT", socket_type=typ)
    N, L = g.nodes, g.links
    gi, go = N.new("NodeGroupInput"), N.new("NodeGroupOutput")

    def math_(op, a, b=None, c=None, clamp=False):
        n = N.new("ShaderNodeMath"); n.operation = op; n.use_clamp = clamp
        for i, x in enumerate((a, b, c)):
            if x is None:
                continue
            if isinstance(x, (int, float)):
                n.inputs[i].default_value = x
            else:
                L.new(x, n.inputs[i])
        return n.outputs[0]

    def smooth(e0, e1, x):
        n = N.new("ShaderNodeMapRange"); n.interpolation_type = "SMOOTHSTEP"; n.clamp = True
        n.inputs["From Min"].default_value = e0; n.inputs["From Max"].default_value = e1
        L.new(x, n.inputs["Value"])
        return n.outputs["Result"]

    def noise(vec, scale, detail=3.0):
        n = N.new("ShaderNodeTexNoise"); n.inputs["Scale"].default_value = scale; n.inputs["Detail"].default_value = detail
        L.new(vec, n.inputs["Vector"])
        return n.outputs["Fac"]

    def voronoi(vec, scale, feature):
        n = N.new("ShaderNodeTexVoronoi"); n.feature = feature; n.inputs["Scale"].default_value = scale
        L.new(vec, n.inputs["Vector"])
        return n

    def mixc(f, a, b):
        n = N.new("ShaderNodeMix"); n.data_type = "RGBA"
        L.new(f, n.inputs["Factor"])
        for sock, v in ((n.inputs[6], a), (n.inputs[7], b)):
            if isinstance(v, tuple):
                sock.default_value = v
            else:
                L.new(v, sock)
        return n.outputs[2]

    def mixf(f, a, b):
        n = N.new("ShaderNodeMix"); n.data_type = "FLOAT"
        L.new(f, n.inputs["Factor"])
        for sock, v in ((n.inputs[2], a), (n.inputs[3], b)):
            if isinstance(v, (int, float)):
                sock.default_value = v
            else:
                L.new(v, sock)
        return n.outputs[0]

    geo = N.new("ShaderNodeNewGeometry")
    P = geo.outputs["Position"]
    a = gi.outputs["Amount"]
    # the front: from the shore inwards, ragged
    jag = math_("ADD", math_("MULTIPLY", math_("SUBTRACT", noise(P, 0.15), 0.5), 0.5),
                math_("MULTIPLY", math_("SUBTRACT", noise(P, 0.6), 0.5), 0.2))
    jag = math_("ADD", jag, math_("MULTIPLY", math_("SUBTRACT", noise(P, 2.5), 0.5), 0.08))
    f = math_("SUBTRACT", math_("MULTIPLY", a, 1.4), gi.outputs["Dist"])
    f = math_("ADD", f, math_("MULTIPLY", jag, math_("MINIMUM", math_("MULTIPLY", a, 4.0), 1.0)))
    f = math_("SUBTRACT", f, math_("MULTIPLY", math_("SUBTRACT", 1.0, a), 0.04))
    ice = smooth(-0.01, 0.01, f)
    rim = math_("MULTIPLY", ice, math_("SUBTRACT", 1.0, smooth(0.0, 0.05, f)))
    # cracks: the edges of cells at two scales
    v1 = voronoi(P, 0.35, "DISTANCE_TO_EDGE")
    v2 = voronoi(P, 1.3, "DISTANCE_TO_EDGE")
    # («Crepe grandi» and «Crepe sottili»: 0 none, 1 as made, 2 twice as marked)
    crack = math_("MAXIMUM", math_("MULTIPLY", math_("SUBTRACT", 1.0, smooth(0.0, 0.006, v1.outputs["Distance"])), gi.outputs["Cracks"]),
                  math_("MULTIPLY", math_("SUBTRACT", 1.0, smooth(0.0, 0.01, v2.outputs["Distance"])),
                        math_("MULTIPLY", gi.outputs["CracksFine"], 0.35)))
    crack = math_("MINIMUM", crack, 1.0)
    # bubbles: a share of small cells, a white speck at their centre
    vb = voronoi(P, 30.0, "F1")
    sep = N.new("ShaderNodeSeparateColor")
    L.new(vb.outputs["Color"], sep.inputs[0])
    pick = math_("LESS_THAN", sep.outputs[0], math_("MULTIPLY", gi.outputs["Bubbles"], 0.8))
    pick = math_("MULTIPLY", pick, smooth(0.42, 0.6, noise(P, 0.5)))             # (in clusters, not everywhere)
    spot = math_("MULTIPLY", math_("SUBTRACT", 1.0, smooth(0.05, 0.18, vb.outputs["Distance"])), pick)
    spot = math_("MULTIPLY", spot, math_("ADD", 0.3, math_("MULTIPLY", sep.outputs[1], 0.4)))
    white = math_("MINIMUM", math_("ADD", math_("ADD", math_("MULTIPLY", crack, 0.4), math_("MULTIPLY", spot, 0.8)),
                                   math_("MULTIPLY", rim, 0.6)), 1.0)
    # a dusting of snow: more near the shore, as much as it snows
    shore = math_("SUBTRACT", 1.0, gi.outputs["Dist"])
    dn_ = math_("ADD", noise(P, 3.0, 4.0), math_("MULTIPLY", smooth(0.8, 1.0, shore), 0.45))
    dust = math_("MULTIPLY", smooth(0.58, 0.72, dn_), math_("MINIMUM", math_("MULTIPLY", gi.outputs["Snow"], 1.5), 1.0))
    dust = math_("MULTIPLY", dust, 0.9)
    milky = math_("SUBTRACT", 1.0, gi.outputs["Clear"])
    col = mixc(milky, (0.78, 0.89, 0.95, 1.0), (0.90, 0.94, 0.97, 1.0))
    col = mixc(white, col, (0.95, 0.97, 0.98, 1.0))
    col = mixc(dust, col, (0.88, 0.90, 0.93, 1.0))
    rough = math_("ADD", mixf(milky, 0.03, 0.4), math_("MULTIPLY", white, 0.3))
    rough = mixf(dust, rough, 0.62)
    trans = math_("MULTIPLY", mixf(milky, 1.0, 0.45), math_("SUBTRACT", 1.0, math_("MULTIPLY", white, 0.6)))
    trans = math_("MULTIPLY", trans, math_("SUBTRACT", 1.0, dust))
    # the surface: a gentle undulation and the cracks
    hgt = math_("ADD", math_("MULTIPLY", noise(P, 0.8), 0.6), math_("MULTIPLY", crack, -0.5))
    hgt = math_("ADD", hgt, math_("MULTIPLY", noise(P, 30.0), 0.08))
    bump = N.new("ShaderNodeBump"); bump.inputs["Strength"].default_value = 0.12; bump.inputs["Distance"].default_value = 0.01
    L.new(hgt, bump.inputs["Height"]); L.new(gi.outputs["NormalIn"], bump.inputs["Normal"])
    nm = N.new("ShaderNodeMix"); nm.data_type = "VECTOR"
    L.new(ice, nm.inputs["Factor"]); L.new(gi.outputs["NormalIn"], nm.inputs[4]); L.new(bump.outputs[0], nm.inputs[5])
    nrm = N.new("ShaderNodeVectorMath"); nrm.operation = "NORMALIZE"
    L.new(nm.outputs[1], nrm.inputs[0])
    L.new(mixc(ice, gi.outputs["BaseIn"], col), go.inputs["Base"])
    L.new(mixf(ice, gi.outputs["RoughIn"], rough), go.inputs["Rough"])
    L.new(mixf(ice, gi.outputs["TransIn"], trans), go.inputs["Trans"])
    L.new(nrm.outputs[0], go.inputs["Normal"])
    L.new(ice, go.inputs["Ice"])
    return g


TARGETS = (("Base Color", "BaseIn", "Base"), ("Roughness", "RoughIn", "Rough"),
           ("Transmission Weight", "TransIn", "Trans"), ("Normal", "NormalIn", "Normal"))


def _principled(mat):
    if mat is None or not mat.use_nodes or mat.node_tree is None:
        return None
    return next((n for n in mat.node_tree.nodes if n.type == "BSDF_PRINCIPLED"), None)


def _remove_nodes(mat):
    """The ice out of the material: every input of the Principled back to what fed it before."""
    nt = mat.node_tree
    grp = nt.nodes.get(NODE)
    if grp is not None:
        p = _principled(mat)
        for inp, gin, gout in TARGETS:
            if p is None:
                break
            src = grp.inputs.get(gin)
            if src is not None and src.is_linked and src.links[0].from_node.name != NODE + "_geo":
                nt.links.new(src.links[0].from_socket, p.inputs[inp])
            else:
                for lk in list(p.inputs[inp].links):
                    nt.links.remove(lk)
                if src is not None and inp != "Normal":
                    try:
                        p.inputs[inp].default_value = src.default_value
                    except (TypeError, AttributeError):
                        pass
    for n in [n for n in nt.nodes if n.name.startswith(NODE)]:
        nt.nodes.remove(n)


def _apply_nodes(mat, entry, s, snow):
    nt = mat.node_tree
    p = _principled(mat)
    if p is None:
        return
    grp = nt.nodes.get(NODE)
    if grp is not None and grp.node_tree is not None and grp.node_tree.name != GROUP:
        _remove_nodes(mat)                      # (made by an earlier version of the group: made again)
        grp = None
    if grp is not None and not all(p.inputs[inp].is_linked and p.inputs[inp].links[0].from_node == grp
                                   for inp, _gin, _gout in TARGETS):
        # (the material was changed meanwhile - the editor set its inputs again: those are the ones that count)
        for n in [n for n in nt.nodes if n.name.startswith(NODE)]:
            nt.nodes.remove(n)
        grp = None
    if grp is None:
        # the inputs as they are, into the group; the group into the inputs
        grp = nt.nodes.new("ShaderNodeGroup"); grp.name = NODE; grp.label = "Ghiaccio"
        grp.node_tree = _group()
        grp.location = (p.location.x - 260, p.location.y + 300)
        for inp, gin, gout in TARGETS:
            sock = p.inputs[inp]
            if sock.is_linked:
                nt.links.new(sock.links[0].from_socket, grp.inputs[gin])
            elif inp == "Normal":
                g = nt.nodes.new("ShaderNodeNewGeometry"); g.name = NODE + "_geo"
                g.location = (grp.location.x - 220, grp.location.y - 200)
                nt.links.new(g.outputs["Normal"], grp.inputs[gin])
            else:
                grp.inputs[gin].default_value = sock.default_value
            nt.links.new(grp.outputs[gout], sock)
        tex = nt.nodes.new("ShaderNodeTexImage"); tex.name = NODE + "_map"
        tex.interpolation = "Linear"; tex.extension = "EXTEND"
        geo = nt.nodes.new("ShaderNodeNewGeometry"); geo.name = NODE + "_pos"
        sub = nt.nodes.new("ShaderNodeVectorMath"); sub.name = NODE + "_sub"; sub.operation = "SUBTRACT"
        mul = nt.nodes.new("ShaderNodeVectorMath"); mul.name = NODE + "_mul"; mul.operation = "MULTIPLY"
        for k, n in enumerate((geo, sub, mul, tex)):
            n.location = (grp.location.x - 900 + 200 * k, grp.location.y + 200)
        nt.links.new(geo.outputs["Position"], sub.inputs[0])
        nt.links.new(sub.outputs[0], mul.inputs[0])
        nt.links.new(mul.outputs[0], tex.inputs["Vector"])
        nt.links.new(tex.outputs["Color"], grp.inputs["Dist"])
    m = entry["meta"]
    tex = nt.nodes.get(NODE + "_map")
    tex.image = bpy.data.images.get(entry["img"])
    nt.nodes[NODE + "_sub"].inputs[1].default_value = (m["x0"], m["y0"], 0.0)
    k = 1.0 / m["size"]
    nt.nodes[NODE + "_mul"].inputs[1].default_value = (k, k, 1.0)
    for name, v in (("Amount", s["amount"]), ("Clear", s["clear"]), ("Bubbles", s["bubbles"]), ("Snow", snow),
                    ("Cracks", s["cracks"]), ("CracksFine", s["cracksFine"])):
        if abs(grp.inputs[name].default_value - v) > 1e-6:
            grp.inputs[name].default_value = float(v)


def strip(mat):
    """The ice out of a material (the editor reads and changes it as it is)."""
    if mat is not None and mat.node_tree is not None and mat.node_tree.nodes.get(NODE) is not None:
        _remove_nodes(mat)


def update():
    """Every water material follows its ice (before a path-traced image, and in the idle time for the real-time
    view). Cheap when nothing changed."""
    from . import water
    snow = snow_amount()
    seen = set()
    for mat in bpy.data.materials:
        if not water.is_water(mat):
            if mat.node_tree is not None and mat.node_tree.nodes.get(NODE) is not None:
                _remove_nodes(mat)
            continue
        s = settings(mat)
        on = s["on"] and snow > 0.0
        if not on:
            if mat.node_tree is not None and mat.node_tree.nodes.get(NODE) is not None:
                _remove_nodes(mat)
            continue
        try:
            entry = _map(mat)
        except Exception as exc:
            log(f"SIMPLER_ICE {mat.name}: map failed: {exc}")
            entry = None
        if entry is None:
            continue
        seen.add(mat.name)
        _apply_nodes(mat, entry, s, snow)
    for name in [k for k in _MAPS if k not in seen]:
        _MAPS.pop(name, None)


def view_info():
    """For the real-time view (rain/info): the frozen waters, by material name."""
    from . import water
    snow = snow_amount()
    if snow <= 0.0:
        return []
    out = []
    for mat in bpy.data.materials:
        if not water.is_water(mat):
            continue
        s = settings(mat)
        e = _MAPS.get(mat.name)
        if not s["on"] or e is None:
            continue
        m = e["meta"]
        out.append({"name": mat.name, "file": m["file"], "x0": m["x0"], "y0": m["y0"], "size": m["size"], "n": m["n"],
                    "amount": s["amount"], "clear": s["clear"], "bubbles": s["bubbles"], "snow": snow})
    return out


def after_open():
    _MAPS.clear()


def touch():
    """The ice of a material changed (water.set_material): the view asks again."""
    from . import rain
    rain.refresh_info()
