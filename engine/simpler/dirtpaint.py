"""«Dipingi lo sporco» (Materiale > Sporco > Avanzate, 1.70.0): dirt painted by hand on any surface, walls too.

The puddles are painted on one map seen from above; dirt goes on walls and columns as well, so here there are three
maps over a cube around what was painted, one for each direction a surface can face (seen along X, along Y, along Z),
cells of CELL m (larger when the painted area is over 40 m wide). Each cell keeps the amount of dirt (0..255) and how
deep the painted surface was along that direction (16 bits): a surface takes the dirt of its own map only where its depth matches (within TOL m), so painting the front
of a column does not dirty its back. (Two surfaces facing the same way at the same place of a map - the two faces of a
thin wall - share their cell: the last one painted keeps it.)

The three maps live in the project as one packed image, n wide and 3 n high (map a in the rows a n .. a n + n - 1):
R = amount, G and B = depth (high and low byte); the frame (origin, size, n) is a property of the world. A node group
reads them (DirtGroup) for the materials with «Sporco» on and painted dirt (grunge.paint); the real-time view gets the
same bytes (GET dirt/paint.bin) and draws the strokes itself while the mouse moves (viewer.js dirtStamp), with the same
three brushes, made from Simpler's dirt picture equalised (so the same on both sides):
  uniforme       fine even dirt: f × (0.45 + 0.55 E(0.6 m))
  frastagliato   a solid patch with a ragged outline: smoothstep(0.45, 0.6, f + 0.7 (E(2 m) - 0.5))
  macchie        separate stains: f × smoothstep(0.62, 0.78, E(3 m))
with f the soft round brush (1 - smoothstep(0.5, 1, d / r)) and E the picture averaged 4 × 4 (512²) and equalised. Every stroke is one step of undo (history «dirtpaint»).
"""
import json
import math
import os
import zlib

import bpy
import numpy as np

KEY = "simpler_dirt_paint"
IMG = "Simpler Sporco dipinto"
GROUP = "Simpler Sporco dipinto"
CELL = 0.02
N_MAX = 2048
TOL = 0.15
PRESETS = ("uniforme", "frastagliato", "macchie")
_C = {"A": None, "D": None, "frame": None, "rev": 0, "file": "", "E": None}


@bpy.app.handlers.persistent
def _on_load(*_a):
    _C.update(A=None, D=None, frame=None, file="")


if _on_load not in bpy.app.handlers.load_post:
    bpy.app.handlers.load_post.append(_on_load)


# ---------------------------------------------------------------- the maps

def frame():
    w = bpy.context.scene.world
    try:
        return json.loads(w[KEY]) if w is not None and w.get(KEY) else None
    except ValueError:
        return None


def painted():
    return frame() is not None


def _arrays():
    """(A, D): amount uint8 (3, n, n), depth uint16 (3, n, n), read once from the image of the project."""
    fr = frame()
    if fr is None:
        _C.update(A=None, D=None, frame=None)
        return None, None
    if _C["A"] is not None and _C["frame"] == fr:
        return _C["A"], _C["D"]
    n = int(fr["n"])
    A = np.zeros((3, n, n), np.uint8)
    D = np.zeros((3, n, n), np.uint16)
    im = bpy.data.images.get(IMG)
    if im is not None and im.size[0] == n and im.size[1] == 3 * n:
        px = np.empty(n * 3 * n * 4, np.float32)
        im.pixels.foreach_get(px)
        px = np.round(px.reshape(3, n, n, 4) * 255).astype(np.uint16)
        A[:] = px[..., 0]
        D[:] = (px[..., 1] << 8) | px[..., 2]
    _C.update(A=A, D=D, frame=fr)
    return A, D


def _store(A, D, fr):
    """Maps and frame into the project (packed image + world property), the node group and the view's file."""
    n = int(fr["n"])
    im = bpy.data.images.get(IMG)
    if im is None or im.size[0] != n or im.size[1] != 3 * n:
        if im is not None:
            bpy.data.images.remove(im)
        im = bpy.data.images.new(IMG, n, 3 * n, alpha=True)
        try:
            im.colorspace_settings.name = "Non-Color"
        except TypeError:
            pass
    px = np.empty((3, n, n, 4), np.float32)
    px[..., 0] = A / 255.0
    px[..., 1] = (D >> 8) / 255.0
    px[..., 2] = (D & 255) / 255.0
    px[..., 3] = 1.0
    im.pixels.foreach_set(px.ravel())
    im.pack()
    im.use_fake_user = True
    im["simpler_noproxy"] = 1      # (1.75.51) a map of data, never a reduced copy (see _update_group)
    # (the path tracing keeps its images between passes - persistent data: without this tag it went on with the
    # old pixels, the strokes did not show until the project was opened again; 1.70.1)
    im.update_tag()
    _C["rev"] += 1
    fr = {k: fr[k] for k in ("x0", "y0", "z0", "size", "n")} | {"rev": _C["rev"]}
    bpy.context.scene.world[KEY] = json.dumps(fr)
    _C.update(A=A, D=D, frame=fr)
    _write_bin(A, D, fr)
    _update_group()


def _dir():
    from .rain import _shelter_dir
    return _shelter_dir()


def _write_bin(A, D, fr):
    d = _dir()
    for f in os.listdir(d):
        if f.startswith("dirt_"):
            try:
                os.remove(os.path.join(d, f))
            except OSError:
                pass
    stem = f"dirt_{os.getpid()}_{fr['rev']}"
    n = int(fr["n"])
    out = np.empty((3, n, n, 3), np.uint8)               # (rows of map 0 first, each map from its v = 0: as the image)
    out[..., 0] = A
    out[..., 1] = D >> 8
    out[..., 2] = D & 255
    with open(os.path.join(d, stem + ".bin"), "wb") as f:
        f.write(out.tobytes())
    _C["file"] = stem


def bin_file(name):
    name = os.path.basename(name or "")
    if not name.startswith("dirt_") or not name.endswith(".bin"):
        return ""
    p = os.path.join(_dir(), name)
    return p if os.path.isfile(p) else ""


def info():
    """For the view: the frame and the file of its bytes (made again after opening a project); None when nothing."""
    fr = frame()
    if fr is None:
        return None
    if not _C["file"] or not os.path.isfile(os.path.join(_dir(), _C["file"] + ".bin")) or _C["frame"] != fr:
        A, D = _arrays()
        if A is None:
            return None
        _write_bin(A, D, fr)
    return {"file": _C["file"], "rev": fr.get("rev", 0), "x0": fr["x0"], "y0": fr["y0"], "z0": fr["z0"],
            "size": fr["size"], "n": int(fr["n"]), "tol": TOL, "pattern": _pattern_name()}


def _pattern_name():
    from .matedit import grunge_image
    return grunge_image().name


# ---------------------------------------------------------------- brushes

def _pattern():
    """Simpler's dirt picture equalised (each grey level replaced by its share of darker pixels): values spread
    evenly 0..1. Rows from the top of the file, as the view reads it from its canvas."""
    if _C["E"] is not None:
        return _C["E"]
    from .matedit import grunge_image
    im = grunge_image()
    w, h = im.size
    px = np.empty(w * h * 4, np.float32)
    im.pixels.foreach_get(px)
    v = np.round(px.reshape(h, w, 4)[::-1, :, 0] * 255).astype(np.int64)    # (Blender: rows from the bottom)
    # 4 × 4 averaged (512²): no detail finer than the cells of the maps (it made square specks); rounded as the view
    v = np.floor(v.reshape(h // 4, 4, w // 4, 4).mean(axis=(1, 3)) + 0.5).astype(np.int64)
    hist = np.bincount(v.ravel(), minlength=256).astype(np.float64)
    cdf = (np.cumsum(hist) - hist / 2) / v.size
    _C["E"] = cdf[v].astype(np.float32)
    return _C["E"]


def _sample(E, u, v, scale):
    h, w = E.shape
    i = (np.floor(np.mod(u / scale, 1.0) * w).astype(np.int64)) % w
    j = (np.floor(np.mod(v / scale, 1.0) * h).astype(np.int64)) % h
    return E[j, i]


def _smooth(e0, e1, x):
    t = np.clip((x - e0) / (e1 - e0), 0.0, 1.0)
    return t * t * (3 - 2 * t)


def brush(f, u, v, preset):
    """The brush's dirt from the round soft brush f at plane points (u, v) (metres)."""
    E = _pattern()
    if preset == "frastagliato":
        return _smooth(0.45, 0.6, f + 0.7 * (_sample(E, u, v, 2.0) - 0.5)) * (f > 0)
    if preset == "macchie":
        return f * _smooth(0.62, 0.78, _sample(E, u, v, 3.0))
    return f * (0.45 + 0.55 * _sample(E, u, v, 0.6))


AXES = ((1, 2, 0), (0, 2, 1), (0, 1, 2))      # map a: (u, v, depth) coordinates


def _new_frame(lo, hi):
    size = max(hi[0] - lo[0], hi[1] - lo[1], hi[2] - lo[2], 2.0)
    n = int(min(N_MAX, max(64, math.ceil(size / CELL))))
    return {"x0": lo[0], "y0": lo[1], "z0": lo[2], "size": size, "n": n}


def _regrid(A, D, fr, nf):
    """The old maps into a new frame (nearest cell; depths measured again)."""
    n, m = int(fr["n"]), int(nf["n"])
    o, no = (fr["x0"], fr["y0"], fr["z0"]), (nf["x0"], nf["y0"], nf["z0"])
    A2 = np.zeros((3, m, m), np.uint8)
    D2 = np.zeros((3, m, m), np.uint16)
    c = (np.arange(m) + 0.5) * nf["size"] / m
    for a, (iu, iv, idp) in enumerate(AXES):
        ou = ((no[iu] + c - o[iu]) / fr["size"] * n).astype(np.int64)
        ov = ((no[iv] + c - o[iv]) / fr["size"] * n).astype(np.int64)
        oku, okv = (ou >= 0) & (ou < n), (ov >= 0) & (ov < n)
        subA = A[a][np.clip(ov, 0, n - 1)][:, np.clip(ou, 0, n - 1)]
        subD = D[a][np.clip(ov, 0, n - 1)][:, np.clip(ou, 0, n - 1)].astype(np.float64)
        depth = o[idp] + subD / 65535.0 * fr["size"]
        subD2 = np.clip(np.round((depth - no[idp]) / nf["size"] * 65535), 0, 65535).astype(np.uint16)
        A2[a][np.ix_(okv, oku)] = subA[np.ix_(okv, oku)]
        D2[a][np.ix_(okv, oku)] = subD2[np.ix_(okv, oku)]
    return A2, D2


def stroke(d):
    """POST dirt/paint {points: [[x, y, z, nx, ny, nz], ...] (metres, world), radius (m), mode: add | remove,
    preset, strength 0..1, materials: [names]} - the materials painted on get the painted dirt on."""
    pts = [tuple(float(x) for x in p[:6]) for p in (d.get("points") or []) if isinstance(p, (list, tuple)) and len(p) >= 6]
    if not pts:
        return {"info": info(), "materials": []}
    r = max(0.02, min(20.0, float(d.get("radius", 0.5))))
    add = (d.get("mode") or "add") != "remove"
    k = max(0.02, min(1.0, float(d.get("strength", 1.0))))
    preset = d.get("preset") if d.get("preset") in PRESETS else "uniforme"
    A, D = _arrays()
    fr = frame()
    need_lo = [min(p[i] for p in pts) - r - 1.0 for i in range(3)]
    need_hi = [max(p[i] for p in pts) + r + 1.0 for i in range(3)]
    if fr is None or any(need_lo[i] < (fr["x0"], fr["y0"], fr["z0"])[i] or
                         need_hi[i] > (fr["x0"], fr["y0"], fr["z0"])[i] + fr["size"] for i in range(3)):
        # the maps cover where it was painted (with room around), not the whole scene: cells of 2 cm up to 40 m,
        # larger beyond (a stroke far away makes the frame grow)
        lo, hi = need_lo, need_hi
        if fr is not None:
            lo = [min(lo[i], (fr["x0"], fr["y0"], fr["z0"])[i]) for i in range(3)]
            hi = [max(hi[i], (fr["x0"], fr["y0"], fr["z0"])[i] + fr["size"]) for i in range(3)]
        nf = _new_frame([v - 3.0 for v in lo], [v + 3.0 for v in hi])
        if A is not None:
            A, D = _regrid(A, D, fr, nf)
        else:
            A = np.zeros((3, nf["n"], nf["n"]), np.uint8)
            D = np.zeros((3, nf["n"], nf["n"]), np.uint16)
        fr = nf
    else:
        A, D = A.copy(), D.copy()
    n, size = int(fr["n"]), fr["size"]
    cell = size / n
    o = (fr["x0"], fr["y0"], fr["z0"])
    for p in pts:
        nrm = p[3:6]
        a = max(range(3), key=lambda i: abs(nrm[i]))
        iu, iv, idp = AXES[a]
        pu, pv, pd = p[iu], p[iv], p[idp]
        rr = r * 1.3                           # (the depth goes a bit beyond the dirt: soft edges, not cut on the cells)
        i0 = max(0, int((pu - rr - o[iu]) / cell)); i1 = min(n, int((pu + rr - o[iu]) / cell) + 2)
        j0 = max(0, int((pv - rr - o[iv]) / cell)); j1 = min(n, int((pv + rr - o[iv]) / cell) + 2)
        if i0 >= i1 or j0 >= j1:
            continue
        cu = o[iu] + (np.arange(i0, i1) + 0.5) * cell
        cv = o[iv] + (np.arange(j0, j1) + 0.5) * cell
        U, V = np.meshgrid(cu, cv)
        dist = np.sqrt((U - pu) ** 2 + (V - pv) ** 2) / r
        f = 1.0 - _smooth(0.5, 1.0, dist)
        b = brush(f, U, V, preset) * k
        blkA = A[a, j0:j1, i0:i1].astype(np.float32) / 255.0
        if add:
            # the depth of this surface only where its dirt now wins (or the cell was clean): before, the whole
            # 1.3 r around took it - a stroke near the foot of a column took the wall's dirt away (its depth
            # changed, the wall did not match any more), 1.73.9
            dep = np.uint16(np.clip(round((pd - o[idp]) / size * 65535), 0, 65535))
            take = (dist < 1.3) & ((blkA <= 0.0) | (b >= blkA))
            D[a, j0:j1, i0:i1] = np.where(take, dep, D[a, j0:j1, i0:i1])
            blkA = np.maximum(blkA, b)
        else:
            blkA = blkA * (1.0 - k * f)
        A[a, j0:j1, i0:i1] = np.round(np.clip(blkA, 0, 1) * 255).astype(np.uint8)
    _store(A, D, fr)
    names = []
    for name in d.get("materials") or []:
        if _enable(name):
            names.append(name)
    out = {"info": info(), "materials": names, "amount": int(A.sum(dtype=np.int64))}
    if d.get("probe"):
        out["probe"] = _probe(A, D, fr, [float(x) for x in d["probe"][:6]])
    return out


def _probe(A, D, fr, p):
    """The painted dirt (0..1) a surface at p with normal p[3:6] takes: 0 where the depth does not match (test hook
    of tools/regression.py: a stroke must not take the dirt away from another surface)."""
    a = max(range(3), key=lambda i: abs(p[3 + i]))
    iu, iv, idp = AXES[a]
    o = (fr["x0"], fr["y0"], fr["z0"])
    n, size = int(fr["n"]), fr["size"]
    i, j = int((p[iu] - o[iu]) / size * n), int((p[iv] - o[iv]) / size * n)
    if not (0 <= i < n and 0 <= j < n):
        return 0.0
    dep = float(D[a, j, i]) / 65535 * size + o[idp]
    return round(float(A[a, j, i]) / 255.0, 3) if abs(dep - p[idp]) <= TOL else 0.0


def _enable(name):
    """A material painted on: its painted dirt on (the «Sporco» of the material); False when it cannot (advanced)."""
    from . import matedit
    mat = bpy.data.materials.get(name or "")
    if mat is None:
        return False
    p, advanced = matedit.read_material(mat)
    if advanced:
        return False
    if p["grunge"].get("paint") and mat.get(matedit.PARAMS_KEY):
        return False                            # (already on: nothing to rebuild)
    p["grunge"]["paint"] = True
    matedit.apply(mat, p)
    return True


def clear(_d=None):
    """POST dirt/paint/clear: all the painted dirt taken away."""
    w = bpy.context.scene.world
    if w is not None and KEY in w:
        del w[KEY]
    im = bpy.data.images.get(IMG)
    if im is not None:
        bpy.data.images.remove(im)
    _C.update(A=None, D=None, frame=None, file="")
    _C["rev"] += 1
    _update_group()
    return {"info": None, "materials": []}


def snapshot():
    fr = frame()
    A, D = _arrays()
    if fr is None or A is None:
        return None
    return {"frame": fr, "A": zlib.compress(A.tobytes(), 6), "D": zlib.compress(D.tobytes(), 6)}


def restore(snap):
    if snapshot() == snap:
        return
    if not snap:
        clear()
        return
    fr = snap["frame"]
    n = int(fr["n"])
    A = np.frombuffer(zlib.decompress(snap["A"]), np.uint8).reshape(3, n, n).copy()
    D = np.frombuffer(zlib.decompress(snap["D"]), np.uint16).reshape(3, n, n).copy()
    _store(A, D, fr)


# ---------------------------------------------------------------- the node group for the path tracing

def group():
    """The node group: (Position, Weights) -> Dirt, reading the three maps (made once, its frame kept up to date)."""
    g = bpy.data.node_groups.get(GROUP)
    if g is None:
        g = _make_group()
    _update_group()
    return g


def _make_group():
    g = bpy.data.node_groups.new(GROUP, "ShaderNodeTree")
    g["simpler_internal"] = 1
    g.interface.new_socket("Position", in_out="INPUT", socket_type="NodeSocketVector")
    g.interface.new_socket("Weights", in_out="INPUT", socket_type="NodeSocketVector")
    g.interface.new_socket("Dirt", in_out="OUTPUT", socket_type="NodeSocketFloat")
    nd, lk = g.nodes, g.links
    gi, go = nd.new("NodeGroupInput"), nd.new("NodeGroupOutput")

    def val(name, v=0.0):
        x = nd.new("ShaderNodeValue")
        x.name = x.label = name
        x.outputs[0].default_value = v
        return x.outputs[0]

    def math(op, a, b, clamp=False):
        m = nd.new("ShaderNodeMath")
        m.operation = op
        m.use_clamp = clamp
        for i, s in enumerate((a, b)):
            if isinstance(s, float):
                m.inputs[i].default_value = s
            else:
                lk.new(s, m.inputs[i])
        return m.outputs[0]

    x0, y0, z0, inv, on = val("x0"), val("y0"), val("z0"), val("inv", 1.0), val("on")
    tol = val("tol", 0.0)
    sp = nd.new("ShaderNodeSeparateXYZ"); lk.new(gi.outputs["Position"], sp.inputs[0])
    sw = nd.new("ShaderNodeSeparateXYZ"); lk.new(gi.outputs["Weights"], sw.inputs[0])
    coords = [math("MULTIPLY", math("SUBTRACT", sp.outputs[i], o), inv) for i, o in enumerate((x0, y0, z0))]
    total = None
    for a, (iu, iv, idp) in enumerate(AXES):
        u, v, dep = coords[iu], coords[iv], coords[idp]
        vv = math("DIVIDE", math("ADD", v, float(a)), 3.0)
        cb = nd.new("ShaderNodeCombineXYZ")
        lk.new(u, cb.inputs[0]); lk.new(vv, cb.inputs[1])
        texs = []
        for interp in ("Linear", "Closest"):
            t = nd.new("ShaderNodeTexImage")
            t.name = f"map{a}{interp[0]}"
            t.interpolation = interp
            t.extension = "CLIP"
            lk.new(cb.outputs[0], t.inputs["Vector"])
            texs.append(t)
        amt = nd.new("ShaderNodeSeparateColor"); lk.new(texs[0].outputs["Color"], amt.inputs[0])
        dc = nd.new("ShaderNodeSeparateColor"); lk.new(texs[1].outputs["Color"], dc.inputs[0])
        stored = math("ADD", math("MULTIPLY", dc.outputs[1], 255.0 * 256.0 / 65535.0), math("MULTIPLY", dc.outputs[2], 255.0 / 65535.0))
        near = math("LESS_THAN", math("ABSOLUTE", math("SUBTRACT", dep, stored), 0.0), tol)
        inside = math("MULTIPLY", math("MULTIPLY", math("GREATER_THAN", u, 0.0), math("LESS_THAN", u, 1.0)),
                      math("MULTIPLY", math("GREATER_THAN", v, 0.0), math("LESS_THAN", v, 1.0)))
        c = math("MULTIPLY", math("MULTIPLY", amt.outputs[0], near), math("MULTIPLY", inside, sw.outputs[a]))
        total = c if total is None else math("ADD", total, c)
    out = math("MULTIPLY", total, on, clamp=True)
    lk.new(out, go.inputs["Dirt"])
    return g


def _update_group():
    g = bpy.data.node_groups.get(GROUP)
    if g is None:
        return
    fr = frame()
    im = bpy.data.images.get(IMG) if fr else None
    # (1.75.51) never swapped for a reduced copy (proxies.py): the three maps are n × 3n pixels, often more than the
    # 1024 / 2048 of the path tracing view of a big project, and their G and B channels are the depth of the painted
    # surface in two bytes - a reduced copy mixed them, no surface matched its depth any more and the dirt painted
    # in the real-time view was missing or faint in the path tracing (Luca, the cathedral). Older projects too.
    if im is not None and not im.get("simpler_noproxy"):
        im["simpler_noproxy"] = 1
    vals = {"on": 1.0 if (fr and im is not None) else 0.0}
    if fr and im is not None:
        vals.update(x0=fr["x0"], y0=fr["y0"], z0=fr["z0"], inv=1.0 / fr["size"], tol=TOL / fr["size"])
    for k, v in vals.items():
        n = g.nodes.get(k)
        if n is not None:
            n.outputs[0].default_value = v
    for n in g.nodes:
        if n.type == "TEX_IMAGE" and n.image != im:
            n.image = im
    g.update_tag()
