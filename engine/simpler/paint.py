"""Distribuisci > Pennello: models of the library painted on the surfaces of the scene.

The real-time view computes where every piece goes (it knows the surfaces under the brush) and sends world matrices;
here they become objects. A painting lives in a group ("Distribuzione 1"...); for every library model the first piece
painted is inserted from the library (the original), all the next ones are instances of it (linked copies: the
geometry and the materials exist once, Cycles draws them as instances). Every piece remembers its library model
(simpler_paint_model), so the brush finds the original again in a later session.
"""
import json
import os
import subprocess
import tempfile
import threading
import time

import bpy
from mathutils import Matrix, Vector

from . import fullspeed
from . import models
from .core import ApiError, ID_KEY, INTERNAL_KEY, KIND_KEY, find, link, log, new_id, object_json, refresh
from .i18n import tr

PAINT_KEY = "simpler_paint"              # on the group
MODEL_KEY = "simpler_paint_model"        # on every painted piece: id of its library model
MAX_ITEMS = 5000                         # per request


def _matrix(values):
    if not isinstance(values, list) or len(values) != 16:
        raise ApiError(tr("Matrice non valida"))
    return Matrix([[float(values[c * 4 + r]) for c in range(4)] for r in range(4)])


_KIND_NAMES = {"brush": "Distribuzione Pennello", "area": "Distribuzione Area", "spacing": "Distribuzione Spaziatura"}


def _kind_of(d):
    """brush | area | spacing: how the distribution was made (its name says it in the tree)."""
    mode = ((d.get("settings") or {}).get("mode") or "") if isinstance(d.get("settings"), dict) else ""
    if mode in ("area", "spacing"):
        return mode
    if d.get("area"):
        return "area"
    return "brush"


def _new_group(name="", kind=""):
    n = 1
    existing = {o.name for o in bpy.data.objects}
    base = name.strip() or tr(_KIND_NAMES.get(kind, "Distribuzione"))
    label = base if name.strip() else f"{base} {n}"
    while label in existing:
        n += 1
        label = f"{base} {n}"
    g = link(bpy.data.objects.new(label, None))
    g.empty_display_size = 0.2
    g[KIND_KEY] = "group"
    g[PAINT_KEY] = 1
    new_id(g)
    return g


def _original(group, model_id):
    for o in group.children:
        if o.get(MODEL_KEY) == model_id and not o.get("simpler_trashed"):
            return o
    return None


def contact_point(root, obs=None):
    """Where a piece of the model touches the surface, in world space: the pivot placed by hand (violet gizmo, kept
    in the library: 1.78.4), else the centre of the bottom of the model."""
    pv = root.get("simpler_pivot")
    if pv is not None and len(pv) == 3:
        return root.matrix_world @ Vector([float(v) for v in pv])
    lo, hi = models._bbox(obs if obs is not None else [root] + list(root.children_recursive))
    return Vector(((lo.x + hi.x) / 2, (lo.y + hi.y) / 2, lo.z))


def repivot(model_id, pv):
    """(1.78.4) The point of the model that touches the surface changed (its pivot, kept in the library): the
    originals of the distributions of this model stand on the new point. The points do not change - only where the
    original sits in its collection (its contact point at the origin), so the change costs nothing however many
    pieces there are."""
    moved = 0
    for o in scatter_originals():
        if o.get(MODEL_KEY) != model_id or (o.parent is not None and o.parent.get(MODEL_KEY)):
            continue
        rest = o.get("simpler_paint_rest")
        if rest is None or len(rest) != 16:
            continue
        p0 = Matrix([[float(rest[r * 4 + c]) for c in range(4)] for r in range(4)])
        if pv is not None:
            o["simpler_pivot"] = [float(v) for v in pv]
            bl = Vector([float(v) for v in pv])
        else:
            if "simpler_pivot" in o:
                del o["simpler_pivot"]
            refresh()
            bl = o.matrix_world.inverted_safe() @ contact_point(o)
        if (Vector(o.get("simpler_paint_base") or (0.0, 0.0, 0.0)) - bl).length < 1e-7:
            continue
        o["simpler_paint_base"] = list(bl)
        o.matrix_world = Matrix.Translation(-(p0 @ bl)) @ p0
        moved += 1
    if moved:
        refresh()
        from . import render
        render.invalidate()
        log("SIMPLER_PIVOT", model_id, f"{moved} originals of distributions on the new point")
    return moved


def _base_offset(root):
    """Centre of the bottom of the model (or its pivot placed by hand), in world space: a painted piece stands on it."""
    refresh()
    return contact_point(root)


def _rest(orig):
    """Matrix of the model as it came from the library, and its base point in world space at that matrix."""
    v = orig.get("simpler_paint_rest")
    p0 = Matrix([[float(v[r * 4 + c]) for c in range(4)] for r in range(4)]) if v is not None and len(v) == 16 else Matrix.Identity(4)
    bl = Vector(orig.get("simpler_paint_base") or (0.0, 0.0, 0.0))
    return p0, p0 @ bl


def add(data):
    """POST paint/add {group, name, items: [{model, m: 16 numbers (column-major world matrix: point on the surface,
    rotation, scale)}]} -> {group, ids, copies (new id -> original id, for the real-time view), inserted}.
    Every piece: world = m x T(-base) x rest, so its base lands on the painted point with the painted rotation/scale."""
    from . import scene_ops
    items = data.get("items") or []
    if not items:
        raise ApiError(tr("Niente da distribuire"))
    items = items[:MAX_ITEMS]
    group = find(data.get("group"), required=False) if data.get("group") else None
    if group is None or not group.get(PAINT_KEY) or group.get("simpler_trashed"):
        group = _new_group(data.get("name") or "", "brush")
    refresh()
    entries = models._entries()
    created, copies, inserted = [], {}, []
    item_ids = [""] * len(items)            # root id of every piece, in the order of the items (the view's ghosts)
    by_model = {}
    for k, it in enumerate(items):
        by_model.setdefault(it.get("model") or "", []).append((k, _matrix(it.get("m"))))
    for model_id, mats in by_model.items():
        e = entries.get(model_id)
        if e is None:
            continue
        orig = _original(group, model_id)
        if orig is None:
            # first piece of this model in the painting: the original, from the library
            path = models.os.path.join(models.user_dir(), e["id"], "model.blend")
            r = models.insert_blend(path, e["name"], entry=e, location=None, parent=group.get("simpler_id"))
            orig = find(r["id"])
            refresh()
            p0 = orig.matrix_world.copy()
            base = _base_offset(orig)
            orig["simpler_paint_rest"] = [p0[r_][c] for r_ in range(4) for c in range(4)]
            orig["simpler_paint_base"] = list(p0.inverted() @ base)
            tag_pieces(orig, model_id)
            k0, m0 = mats[0]
            orig.matrix_world = m0 @ Matrix.Translation(-base) @ p0
            created.append(orig)
            inserted.append(orig)
            item_ids[k0] = orig.get("simpler_id")
            mats = mats[1:]
        p0, base = _rest(orig)
        # a piece is a copy of the original placed directly under the group: its local matrix is computed here, no
        # scene update per piece (thousands of pieces in a fraction of a second)
        g_inv = group.matrix_world.inverted()
        for k, m in mats:
            ob = scene_ops._duplicate_tree(orig, group, copies)
            scene_ops._tag_instance(ob, orig, False)
            ob.matrix_parent_inverse.identity()
            ob.matrix_basis = g_inv @ m @ Matrix.Translation(-base) @ p0
            created.append(ob)
            item_ids[k] = ob.get("simpler_id")
    refresh()
    for ob in created:
        ob.rotation_mode = "XYZ"
    return {"group": group.get("simpler_id"), "groupName": group.name, "ids": [o.get("simpler_id") for o in created],
            "copies": copies, "inserted": [o.get("simpler_id") for o in inserted], "itemIds": item_ids}



# ---------------------------------------------------------------- a distribution as a whole (editable afterwards)
# The view keeps the strokes of a distribution (where the brush passed, its size, the erased spots) and makes the
# pieces from them with the current settings: changing spacing, scale, rotation or presence later re-makes the
# whole distribution, not only the next stroke. POST paint/set receives every piece of the distribution and puts
# them in place of the previous ones (one undo step); the strokes and the settings live in a hidden "data" object of
# the group, replaced at every change: undo brings back the previous one together with the previous pieces.

DATA_KEY = "simpler_paint_data"
GEN_KEY = "simpler_paint_gen"          # a piece made from the strokes (pieces painted before 1.6.1 are kept as they are)
MAX_SET = 2000000


def _holder(group):
    for c in group.children:
        if c.get(DATA_KEY) and not c.get("simpler_trashed"):
            return c
    return None


def data(d):
    """GET paint/data?group= -> {group, strokes, seed, settings, palette} of a distribution (empty when it has none)."""
    g = find(d.get("group"), required=False) if d.get("group") else None
    h = _holder(g) if g is not None else None
    out = {"group": d.get("group") or "", "strokes": [], "seed": 0, "settings": None, "palette": None, "area": None}
    if h is None:
        return out
    for k in ("strokes", "settings", "palette", "area"):
        try:
            out[k] = json.loads(h.get("simpler_paint_" + k) or "null")
        except ValueError:
            pass
    out["strokes"] = out["strokes"] or []
    out["seed"] = int(h.get("simpler_paint_seed") or 0)
    out["base"] = int(h.get(BASE_KEY) or 0)
    _follow_group(g, h, out)
    return out


BASE_KEY = "simpler_paint_base"      # on the points: how many of the first pieces are fixed (not made by strokes)
SEASON_ATTR = "simpler_season"      # (1.79.0) on the points: the season of each piece (matedit.PIECE_SEASON)


def base(d):
    """GET paint/base?group= -> {models, idx, trs, count}: the fixed pieces of a distribution (the first BASE_KEY
    points), in world space as the view packs them (model index; position, quaternion x y z w, uniform scale)."""
    import base64
    import numpy as np
    g = find(d.get("group"))
    h = _holder(g)
    n = int(h.get(BASE_KEY) or 0) if h is not None and h.type == "MESH" else 0
    n = min(n, len(h.data.vertices)) if n else 0
    if not n:
        return {"models": [], "idx": "", "trs": "", "count": 0}
    me = h.data
    tot = len(me.vertices)
    xf = np.empty(tot * 16, dtype=np.float32)
    mi = np.empty(tot, dtype=np.int32)
    me.attributes["simpler_xform"].data.foreach_get("value", xf)
    me.attributes["simpler_model"].data.foreach_get("value", mi)
    xf = xf.reshape(tot, 4, 4).transpose(0, 2, 1)[:n].astype(np.float64)      # (stored transposed)
    G = np.array(models._world_now(g), dtype=np.float64)       # (as _layer_points: the space of the group)
    w = G[None] @ xf
    M = w[:, :3, :3]
    sc = np.linalg.norm(M, axis=1).mean(axis=1)
    R = M / np.maximum(sc, 1e-12)[:, None, None]
    # rotation matrices to quaternions (x y z w), vectorised
    tr_ = R[:, 0, 0] + R[:, 1, 1] + R[:, 2, 2]
    q = np.zeros((n, 4))
    c0 = tr_ > 0
    s0 = np.sqrt(np.maximum(tr_[c0] + 1.0, 1e-12)) * 2
    q[c0, 3] = 0.25 * s0
    q[c0, 0] = (R[c0, 2, 1] - R[c0, 1, 2]) / s0
    q[c0, 1] = (R[c0, 0, 2] - R[c0, 2, 0]) / s0
    q[c0, 2] = (R[c0, 1, 0] - R[c0, 0, 1]) / s0
    for a, b_, c in ((0, 1, 2), (1, 2, 0), (2, 0, 1)):
        k = ~c0 & (R[:, a, a] >= R[:, b_, b_]) & (R[:, a, a] >= R[:, c, c])
        c0 = c0 | k
        sk = np.sqrt(np.maximum(1.0 + R[k, a, a] - R[k, b_, b_] - R[k, c, c], 1e-12)) * 2
        q[k, 3] = (R[k, c, b_] - R[k, b_, c]) / sk
        q[k, a] = 0.25 * sk
        q[k, b_] = (R[k, b_, a] + R[k, a, b_]) / sk
        q[k, c] = (R[k, c, a] + R[k, a, c]) / sk
    trs = np.concatenate([w[:, :3, 3], q, sc[:, None]], axis=1).astype(np.float32)
    subs = list(_scatter_coll(g).children)
    names = [sub.get(MODEL_KEY) or "" for sub in subs]
    return {"models": names, "idx": base64.b64encode(mi[:n].astype(np.int32).tobytes()).decode("ascii"),
            "trs": base64.b64encode(trs.tobytes()).decode("ascii"), "count": n}


# The line (Area, Spaziatura) and the strokes (Pennello) are kept in world space, together with where the distribution
# was when they were saved: a distribution moved or turned afterwards (or a copy of it moved elsewhere) brings them
# along, so Aggiorna rebuilds the pieces where the distribution is now, not where it was drawn.
GM_KEY = "simpler_paint_gm"


def _gm_of(group):
    return [round(v, 6) for row in models._world_now(group) for v in row]


def _follow_group(group, holder, out):
    try:
        gm = holder.get(GM_KEY)
        gm = list(gm) if gm is not None else None
        old = Matrix([list(gm[i * 4:i * 4 + 4]) for i in range(4)]) if gm is not None and len(gm) == 16 else Matrix.Identity(4)
        delta = models._world_now(group) @ old.inverted()
    except (ValueError, TypeError):
        return
    if all(abs(delta[i][j] - (1.0 if i == j else 0.0)) < 1e-6 for i in range(4) for j in range(4)):
        return
    rot = delta.to_3x3()
    pt = lambda p: [round(v, 4) for v in delta @ Vector(p[:3])]
    a = out.get("area")
    if isinstance(a, dict) and isinstance(a.get("pts"), list):
        a["pts"] = [pt(p) for p in a["pts"] if isinstance(p, list) and len(p) >= 3]
    for st in out.get("strokes") or []:
        if isinstance(st, dict):
            if isinstance(st.get("p"), list) and len(st["p"]) >= 3:
                st["p"] = pt(st["p"])
            if isinstance(st.get("n"), list) and len(st["n"]) >= 3:
                n = (rot @ Vector(st["n"][:3])).normalized()
                st["n"] = [round(v, 5) for v in n]


def set_all(d):
    if os.environ.get("SIMPLER_PROFILE"):
        import cProfile, pstats, io
        pr = cProfile.Profile(); pr.enable()
        try:
            return _set_all(d)
        finally:
            pr.disable(); out = io.StringIO(); pstats.Stats(pr, stream=out).sort_stats("cumulative").print_stats(18); print(out.getvalue(), flush=True)
    return _set_all(d)


def _set_all(d):
    """POST paint/set {group, items: [{model, m}], strokes, seed, settings, palette} -> {group, rev, count, models}.

    A distribution is one object of points (Geometry Nodes "Instance on Points"): every point carries the library
    model it shows (simpler_model, the index of the model's collection) and where it stands (simpler_xform, 4x4 in
    the space of the points). The models themselves (one "original" each) live in a collection of the distribution
    that is not in the scene. Cycles draws the points as instances; writing hundreds of thousands of them is a few
    arrays. The points object is replaced at every change (undo brings back the previous one)."""
    import numpy as np
    from . import trash
    packed = d.get("packed")
    if packed:
        # from the view: model index (int32) and position, rotation (quaternion x y z w), scale (8 float32) per piece
        import base64
        idx = np.frombuffer(base64.b64decode(packed.get("idx") or ""), dtype=np.int32)
        trs = np.frombuffer(base64.b64decode(packed.get("trs") or ""), dtype=np.float32).reshape(-1, 8).astype(np.float64)
        names = list(packed.get("models") or [])
        if "base" in packed:
            d = dict(d, base=int(packed.get("base") or 0))
        return _set_points(d, names, idx[:MAX_SET], trs[:MAX_SET])
    items = (d.get("items") or [])[:MAX_SET]
    group = find(d.get("group"), required=False) if d.get("group") else None
    if group is None or not group.get(PAINT_KEY) or group.get("simpler_trashed"):
        if not items:
            raise ApiError(tr("Niente da distribuire"))
        group = _new_group(d.get("name") or "", _kind_of(d))
    ms = [it.get("m") for it in items if isinstance(it.get("m"), list) and len(it.get("m")) == 16]
    _attach_to_plot(group, [m[12] for m in ms], [m[13] for m in ms])         # (column-major: translation 12-14)
    refresh()
    entries = models._entries()
    _convert_legacy(group)
    coll = _scatter_coll(group)
    index = {}
    mids = list(dict.fromkeys(it.get("model") or "" for it in items))
    with _loading(len(mids)) as step:
        for k, mid in enumerate(mids):
            step(k, entries.get(mid))
            index[mid] = _ensure_original(coll, mid, entries.get(mid))
    keep = [k for k, it in enumerate(items) if index.get(it.get("model") or "") is not None]
    n = len(keep)
    g_inv = np.array(group.matrix_world.inverted(), dtype=np.float64)
    xf = np.empty((n, 4, 4), dtype=np.float64)
    mi = np.empty(n, dtype=np.int32)
    for j, k in enumerate(keep):
        v = items[k].get("m")
        if not isinstance(v, list) or len(v) != 16:
            raise ApiError(tr("Matrice non valida"))
        xf[j] = np.array(v, dtype=np.float64).reshape(4, 4).T        # column-major from the view
        mi[j] = index[items[k]["model"]][1]
    xf = g_inv[None] @ xf if n else xf
    old = [c for c in group.children if not c.get("simpler_trashed") and c.get(DATA_KEY)]
    trash.trash([o for o in old])
    pts = _points_object(group, coll, xf, mi)
    for k in ("strokes", "settings", "palette", "area"):
        pts["simpler_paint_" + k] = json.dumps(d.get(k), separators=(",", ":"))
    pts["simpler_paint_seed"] = int(d.get("seed") or 0)
    pts[GM_KEY] = _gm_of(group)
    refresh()
    return {"group": group.get("simpler_id"), "groupName": group.name, "rev": pts.get("simpler_id"), "count": n}


def _attach_to_plot(group, xs, ys):
    """A new distribution painted on the test plot of the ecosystems becomes its child (it keeps its place): moving
    the plot takes it along, deleting the plot deletes it. Only when most of its pieces stand on the plot."""
    import numpy as np
    if group.parent is not None or not len(xs) or group.get("simpler_eco_layer"):
        return
    from . import ecosystems
    for plot in bpy.context.scene.objects:
        if not plot.get(ecosystems.PLOT_KEY) or plot.get("simpler_trashed"):
            continue
        size = float(plot.get(ecosystems.PLOT_KEY) or 20.0)
        c = plot.matrix_world.translation
        on = (np.abs(np.asarray(xs) - c.x) <= size / 2) & (np.abs(np.asarray(ys) - c.y) <= size / 2)
        if on.mean() > 0.5:
            refresh()
            mw = group.matrix_world.copy()
            group.parent = plot
            group.matrix_parent_inverse = plot.matrix_world.inverted()
            group.matrix_world = mw
            refresh()
            return


def _season_hash(xs, ys):
    """(1.79.0) a random number 0..1 per piece from its place (x, y to the millimetre, float32 as the view sends them):
    viewer.js seasonHash does the same, so the view and the render give each piece the same season."""
    import numpy as np
    ix = np.floor(np.asarray(xs, dtype=np.float32).astype(np.float64) * 1000.0 + 0.5).astype(np.int64)
    iy = np.floor(np.asarray(ys, dtype=np.float32).astype(np.float64) * 1000.0 + 0.5).astype(np.int64)
    h = ((ix * 73856093) & 0xFFFFFFFF) ^ ((iy * 19349663) & 0xFFFFFFFF)
    for _ in range(2):
        h = h ^ (h >> 16)
        h = (h * 0x45D9F3B) & 0xFFFFFFFF
    h = h ^ (h >> 16)
    return h.astype(np.float64) / 4294967296.0


def _seasons(palette, names, idx, xs, ys):
    """(1.79.0, Luca: «se è una vegetazione puoi aggiungere season») the season of each piece from the settings of its
    model in the brush (season, seasonRand: 0..1): 1 + season, 0 = the material's own; None when no model has one."""
    import numpy as np
    over = {}
    for e in palette or []:
        if not isinstance(e, dict):
            continue
        sv, rv = float(e.get("season") or 0.0), float(e.get("seasonRand") or 0.0)
        if sv > 0 or rv > 0:
            over[e.get("model")] = (sv, rv)
    if not over or not len(idx):
        return None
    mids = np.asarray(list(names) + [""], dtype=object)[np.asarray(idx)]
    u = _season_hash(xs, ys)
    out = np.zeros(len(mids), dtype=np.float32)
    for mid, (sv, rv) in over.items():
        k = mids == mid
        if k.any():
            out[k] = 1.0 + np.clip(sv + (u[k] * 2.0 - 1.0) * rv, 0.0, 1.0)
    return out if out.any() else None


def _season_materials(coll, sea, mi):
    """The leaf materials of the models that have pieces with a season of their own read it from the piece."""
    import numpy as np
    from . import matedit
    if sea is None:
        return
    subs = list(coll.children)
    mats = []
    for k in np.unique(mi[sea > 0.5]):
        if 0 <= k < len(subs):
            for o in subs[k].all_objects:
                mats += [sl.material for sl in getattr(o, "material_slots", []) if sl.material is not None]
    matedit.season_per_piece(mats)


def _set_points(d, names, idx, trs):
    """paint/set with the pieces as arrays (any number of them)."""
    import numpy as np
    from . import trash
    n = len(idx)
    group = find(d.get("group"), required=False) if d.get("group") else None
    if group is None or not group.get(PAINT_KEY) or group.get("simpler_trashed"):
        if not n:
            raise ApiError(tr("Niente da distribuire"))
        group = _new_group(d.get("name") or "", _kind_of(d))
    if not d.get("noPlot"):
        # (at every change, not only the first: a brush that started just off the plot is adopted when most of its
        # pieces are on it)
        _attach_to_plot(group, trs[:, 0], trs[:, 1])
    refresh()
    entries = models._entries()
    _convert_legacy(group)
    coll = _scatter_coll(group)
    remap = np.full(max(1, len(names)), -1, dtype=np.int32)
    with _loading(len(names)) as step:
        for k, mid in enumerate(names):
            step(k, entries.get(mid))
            got = _ensure_original(coll, mid, entries.get(mid))
            if got is not None:
                remap[k] = got[1]
    mi = remap[idx] if n else np.empty(0, dtype=np.int32)
    ok = mi >= 0
    sea = _seasons(d.get("palette"), names, idx, trs[:, 0], trs[:, 1]) if n else None
    mi, trs = mi[ok], trs[ok]
    sea = sea[ok] if sea is not None else None
    n = len(mi)
    # the fixed pieces at the start (an ecosystem put back on the bench to be changed): the strokes of the brush add
    # to them and erase them; told by the view at every change, else kept from the points before
    prev = _holder(group)
    base = d.get("base")
    if base is None:
        base = int(prev.get(BASE_KEY) or 0) if prev is not None else 0
    base = int(ok[:max(0, int(base))].sum()) if len(ok) else 0
    # matrices from position, quaternion and uniform scale (vectorised), then into the space of the group
    x, y, z, w = trs[:, 3], trs[:, 4], trs[:, 5], trs[:, 6]
    s = trs[:, 7]
    xf = np.zeros((n, 4, 4))
    xf[:, 0, 0] = (1 - 2 * (y * y + z * z)) * s; xf[:, 0, 1] = 2 * (x * y - z * w) * s; xf[:, 0, 2] = 2 * (x * z + y * w) * s
    xf[:, 1, 0] = 2 * (x * y + z * w) * s; xf[:, 1, 1] = (1 - 2 * (x * x + z * z)) * s; xf[:, 1, 2] = 2 * (y * z - x * w) * s
    xf[:, 2, 0] = 2 * (x * z - y * w) * s; xf[:, 2, 1] = 2 * (y * z + x * w) * s; xf[:, 2, 2] = (1 - 2 * (x * x + y * y)) * s
    xf[:, 0, 3], xf[:, 1, 3], xf[:, 2, 3], xf[:, 3, 3] = trs[:, 0], trs[:, 1], trs[:, 2], 1.0
    g_inv = np.array(group.matrix_world.inverted(), dtype=np.float64)
    if n:
        xf = g_inv[None] @ xf
    old = [c for c in group.children if not c.get("simpler_trashed") and c.get(DATA_KEY)]
    trash.trash(old)
    pts = _points_object(group, coll, xf, mi, sea)
    _season_materials(coll, sea, mi)
    pts.hide_render = pts.hide_viewport = group.hide_render     # (a hidden distribution stays hidden)
    for k in ("strokes", "settings", "palette", "area"):
        pts["simpler_paint_" + k] = json.dumps(d.get(k), separators=(",", ":"))
    pts["simpler_paint_seed"] = int(d.get("seed") or 0)
    pts[BASE_KEY] = base
    pts[GM_KEY] = _gm_of(group)
    if not d.get("noRefresh"):                  # (an ecosystem makes several layers: it evaluates the scene once at the end)
        refresh()
    return {"group": group.get("simpler_id"), "groupName": group.name, "rev": pts.get("simpler_id"), "count": int(n)}


SCATTER_COLL = "simpler_scatter_coll"      # on a group: name of the collection with its models
SCATTER_TAG = "simpler_scatter"            # on that collection


def _scatter_coll(group):
    name = group.get(SCATTER_COLL) or ""
    c = bpy.data.collections.get(name) if name else None
    if c is None:
        c = bpy.data.collections.new(tr("Distribuzione") + " · " + tr("modelli"))
        c[SCATTER_TAG] = 1
        c.use_fake_user = True
        group[SCATTER_COLL] = c.name
    return c


def _scatter_refs(live=False):
    """Names of the model collections that distributions use (live: only distributions in the scene, not deleted)."""
    out = set()
    for g in bpy.data.objects:
        n = g.get(SCATTER_COLL)
        if n and g.get(PAINT_KEY) and (not live or (g.users_scene and not g.get("simpler_trashed"))):
            out.add(n)
    return out


def scatter_originals(live=False):
    """The models of every distribution (they are not in the scene: drawn only as instances of its points). The
    collections of distributions that are gone (orphans, purge_orphans) are not counted."""
    refs = _scatter_refs(live)
    out = []
    for c in bpy.data.collections:
        if c.get(SCATTER_TAG) and c.name in refs:
            out.extend(o for o in c.all_objects if not o.get("simpler_trashed"))
    return out


def purge_orphans():
    """The models of distributions that no longer exist (deleted and out of the undo history). Their collection
    stayed in the project forever (kept by a fake user): memory, file size, names taken (a car placed again came out
    «.002»), and their old models could still be picked as the model's reference (an old orientation in the view)."""
    refs = _scatter_refs()
    gone = [c for c in bpy.data.collections if c.get(SCATTER_TAG) and c.name not in refs]
    if not gone:
        return 0
    victims = {o for c in gone for o in c.all_objects if not o.users_scene}
    for c in gone:
        bpy.data.collections.remove(c)
    victims = [o for o in victims if o.name in bpy.data.objects and not o.users_collection]
    if victims:
        bpy.data.batch_remove(victims)
    for coll in (bpy.data.meshes, bpy.data.lights):
        for block in list(coll):
            if block.users == 0:
                coll.remove(block)
    return len(gone)


import contextlib


@contextlib.contextmanager
def _loading(total):
    """Progress of a distribution while its models come from the library (the app shows it in the view's pill)."""
    from . import progress
    progress.begin("paint", tr("Preparazione della distribuzione"))

    def step(k, entry):
        progress.update(tr("Modelli della distribuzione"), k / max(1, total),
                        tr("{0} di {1}", k + 1, total) + (" · " + entry["name"] if entry and entry.get("name") else ""))
    try:
        yield step
    finally:
        progress.end()


def _ensure_original(coll, model_id, entry):
    """(original, index) of a model in a distribution's collection: inserted from the library the first time."""
    for k, sub in enumerate(coll.children):
        if sub.get(MODEL_KEY) == model_id and len(sub.objects):
            return next(o for o in sub.objects if o.parent is None or o.parent.name not in sub.objects), k
    # the same model in another distribution: a copy of its original that shares meshes, materials and textures
    # (loading the library file again took longer at every new distribution - 9, 30, 60 s for 7 big buildings - and
    # doubled the textures in memory; the view also had to prepare the model again)
    for other in bpy.data.collections:
        if other is coll or not other.get(SCATTER_TAG):
            continue
        for sub in other.children:
            if sub.get(MODEL_KEY) != model_id or not len(sub.objects):
                continue
            root = next((o for o in sub.objects if (o.parent is None or o.parent.name not in sub.objects)
                         and not o.get("simpler_trashed")), None)
            if root is not None:
                o = _adopt(coll, model_id, root, copy=True)
                if sub.get("simpler_orient_serial"):
                    coll.children[-1]["simpler_orient_serial"] = sub["simpler_orient_serial"]
                if sub.get("simpler_lib_rev"):
                    coll.children[-1]["simpler_lib_rev"] = sub["simpler_lib_rev"]
                return o, len(coll.children) - 1
    if entry is None:
        return None
    path = models.os.path.join(models.user_dir(), entry["id"], "model.blend")
    r = models.insert_blend(path, entry["name"], entry=entry, location=None)
    orig = find(r["id"])
    o = _adopt(coll, model_id, orig)
    coll.children[-1]["simpler_lib_rev"] = str(entry.get("rev", ""))     # (libupdate.outdated)
    # (loaded as the library has it now: an orientation changed before is already in it - models.orient_scatters)
    try:
        with open(models.os.path.join(models.user_dir(), entry["id"], "info.json"), encoding="utf-8") as fh:
            serial = json.load(fh).get("orientSerial")
        if serial:
            coll.children[-1]["simpler_orient_serial"] = serial
    except (OSError, ValueError):
        pass
    return o, len(coll.children) - 1


def _adopt(coll, model_id, orig, copy=False, sub=None):
    """A model becomes the original of a distribution: in its own collection, its base at the origin."""
    refresh()
    tree = [orig] + list(orig.children_recursive)
    if copy:
        # (from a piece painted before: a copy of it, the pieces then go)
        mapping = {}
        for o in tree:
            mapping[o] = o.copy()
        for o, c in mapping.items():
            c.parent = mapping.get(o.parent)
            new_id(c)
        tree = [mapping[o] for o in tree]
        world = orig.matrix_world.copy()
        orig = tree[0]
    else:
        world = orig.matrix_world.copy()
    rest = orig.get("simpler_paint_rest")
    if rest is not None and len(rest) == 16:
        p0 = Matrix([[float(rest[r * 4 + c]) for c in range(4)] for r in range(4)])
        bl = Vector(orig.get("simpler_paint_base") or (0.0, 0.0, 0.0))
    else:
        p0 = world
        base = contact_point(orig, tree if not copy else [orig] + list(orig.children_recursive))
        bl = p0.inverted() @ base
        orig["simpler_paint_rest"] = [p0[r][c] for r in range(4) for c in range(4)]
        orig["simpler_paint_base"] = list(bl)
    if sub is None:
        sub = bpy.data.collections.new(f"{len(coll.children):03d} {orig.name}")
        sub[MODEL_KEY] = model_id
        coll.children.link(sub)
    # (sub given: the model again from the library into its old place - libupdate.py)
    for o in tree:
        for c in list(o.users_collection):
            c.objects.unlink(o)
        sub.objects.link(o)
        if o.type in PIECE_TYPES_SET:
            o[MODEL_KEY] = model_id
        for k in ("simpler_instance_of", GEN_KEY):
            if k in o:
                del o[k]
    orig.parent = None
    orig.matrix_world = Matrix.Translation(-(p0 @ bl)) @ p0
    from . import dusk
    for o in tree:
        if o.type == "LIGHT":
            dusk.apply_lamp(o)          # (its lamps on or off for the time of day now, as in the scene)
    return orig


PIECE_TYPES_SET = {"MESH", "EMPTY", "CURVE", "SURFACE", "META", "FONT"}


def _node_tree(group, coll):
    name = "Simpler Scatter · " + (group.get("simpler_id") or group.name)
    ng = bpy.data.node_groups.get(name)
    if ng is not None:
        for n in ng.nodes:
            if n.type == "COLLECTION_INFO":
                n.inputs["Collection"].default_value = coll
        return ng
    ng = bpy.data.node_groups.new(name, "GeometryNodeTree")
    ng.interface.new_socket("Geometry", in_out="INPUT", socket_type="NodeSocketGeometry")
    ng.interface.new_socket("Geometry", in_out="OUTPUT", socket_type="NodeSocketGeometry")
    N, L = ng.nodes, ng.links
    gi, go = N.new("NodeGroupInput"), N.new("NodeGroupOutput")
    ci = N.new("GeometryNodeCollectionInfo")
    ci.transform_space = "ORIGINAL"
    ci.inputs["Collection"].default_value = coll
    ci.inputs["Separate Children"].default_value = True
    ci.inputs["Reset Children"].default_value = True
    iop = N.new("GeometryNodeInstanceOnPoints")
    iop.inputs["Pick Instance"].default_value = True
    na_m = N.new("GeometryNodeInputNamedAttribute")
    na_m.data_type = "INT"
    na_m.inputs["Name"].default_value = "simpler_model"
    na_x = N.new("GeometryNodeInputNamedAttribute")
    na_x.data_type = "FLOAT4X4"
    na_x.inputs["Name"].default_value = "simpler_xform"
    sit = N.new("GeometryNodeSetInstanceTransform")
    # (1.79.0) the copies pressed into the snow (snow.press_update) are left out
    dl = N.new("GeometryNodeDeleteGeometry")
    dl.name = PRESS_NODE
    dl.domain = "POINT"
    na_p = N.new("GeometryNodeInputNamedAttribute")
    na_p.data_type = "BOOLEAN"
    na_p.inputs["Name"].default_value = "simpler_pressed"
    L.new(gi.outputs["Geometry"], dl.inputs["Geometry"])
    L.new(na_p.outputs["Attribute"], dl.inputs["Selection"])
    gi_out = dl.outputs["Geometry"]
    L.new(gi_out, iop.inputs["Points"])
    L.new(ci.outputs["Instances"], iop.inputs["Instance"])
    L.new(na_m.outputs["Attribute"], iop.inputs["Instance Index"])
    L.new(iop.outputs["Instances"], sit.inputs["Instances"])
    L.new(na_x.outputs["Attribute"], sit.inputs["Transform"])
    L.new(sit.outputs["Instances"], go.inputs["Geometry"])
    ng.use_fake_user = True
    return ng


PRESS_NODE = "simpler_press_del"


def press_node(po):
    """(1.79.0) The node trees made before: the Delete Geometry of the pressed copies put in front."""
    for mod in po.modifiers:
        ng = mod.node_group if mod.type == "NODES" else None
        if ng is None or ng.nodes.get(PRESS_NODE) is not None:
            continue
        iop = next((n for n in ng.nodes if n.bl_idname == "GeometryNodeInstanceOnPoints"), None)
        if iop is None or not iop.inputs["Points"].is_linked:
            continue
        src = iop.inputs["Points"].links[0].from_socket
        dl = ng.nodes.new("GeometryNodeDeleteGeometry")
        dl.name = PRESS_NODE
        dl.domain = "POINT"
        na_p = ng.nodes.new("GeometryNodeInputNamedAttribute")
        na_p.data_type = "BOOLEAN"
        na_p.inputs["Name"].default_value = "simpler_pressed"
        ng.links.new(src, dl.inputs["Geometry"])
        ng.links.new(na_p.outputs["Attribute"], dl.inputs["Selection"])
        ng.links.new(dl.outputs["Geometry"], iop.inputs["Points"])


def _points_object(group, coll, xf, mi, sea=None):
    import numpy as np
    n = len(mi)
    me = bpy.data.meshes.new(group.name + " · " + tr("punti"))
    me.vertices.add(n)
    if n:
        me.vertices.foreach_set("co", xf[:, :3, 3].astype(np.float32).ravel())
        a = me.attributes.new("simpler_xform", "FLOAT4X4", "POINT")
        a.data.foreach_set("value", np.ascontiguousarray(xf.transpose(0, 2, 1)).astype(np.float32).ravel())
        b = me.attributes.new("simpler_model", "INT", "POINT")
        b.data.foreach_set("value", mi)
        if sea is not None and len(sea) == n:
            # (1.79.0) the season of each piece (1 + season, 0 = the material's): the leaf materials read it
            c = me.attributes.new(SEASON_ATTR, "FLOAT", "POINT")
            c.data.foreach_set("value", np.asarray(sea, dtype=np.float32))
    ob = link(bpy.data.objects.new(tr("Dati distribuzione"), me))
    ob.parent = group
    ob.matrix_parent_inverse.identity()
    ob[DATA_KEY] = 1
    mod = ob.modifiers.new("Simpler Scatter", "NODES")
    mod.node_group = _node_tree(group, coll)
    new_id(ob)
    return ob


def _convert_legacy(group):
    """Pieces painted before 1.8 (one object each) become points of the distribution."""
    from . import trash
    pieces = [c for c in group.children if c.get(MODEL_KEY) and not c.get("simpler_trashed") and not c.get(DATA_KEY)]
    if not pieces:
        return False
    import numpy as np
    refresh()
    coll = _scatter_coll(group)
    origs = {}
    xf, mi = [], []
    for p in pieces:
        mid = p.get(MODEL_KEY)
        if mid not in origs:
            src = next((q for q in pieces if q.get(MODEL_KEY) == mid and not q.get("simpler_instance_of")), p)
            done = next(((o, k) for k, sub in enumerate(coll.children) if sub.get(MODEL_KEY) == mid
                         for o in sub.objects if o.parent is None), None)
            origs[mid] = done or (_adopt(coll, mid, src, copy=True), len(coll.children) - 1)
        orig, k = origs[mid]
        m = group.matrix_world.inverted() @ p.matrix_world @ orig.matrix_world.inverted()
        xf.append(np.array(m, dtype=np.float64))
        mi.append(k)
    victims = []
    for p in pieces:
        victims.extend([p] + list(p.children_recursive))
    holder = [c for c in group.children if c.get(DATA_KEY) and not c.get("simpler_trashed")]
    props = {}
    if holder:
        props = {k: holder[0].get(k) for k in ("simpler_paint_strokes", "simpler_paint_settings", "simpler_paint_palette", "simpler_paint_seed")}
        victims.extend(holder)
    trash.trash(victims)
    pts = _points_object(group, coll, np.array(xf).reshape(-1, 4, 4), np.array(mi, dtype=np.int32))
    for k, v in props.items():
        if v is not None:
            pts[k] = v
    return True


def convert_all(_d=None):
    """All the distributions of the project as points (after opening a project made with an older Simpler)."""
    n = 0
    for g in [o for o in bpy.context.scene.objects if o.get(PAINT_KEY)]:
        if _convert_legacy(g):
            n += 1
    return {"converted": n}


def sub_lamps(sub):
    """The lamps inside the model of a distribution, for the real-time view (it draws the pieces without them: the
    street lamps of a scatter did not light the street at night). m: the lamp in the space of a piece (column after
    column) - in the scene a copy of it is at group × piece matrix × m, as Cycles draws it."""
    from .core import LIGHT_KINDS, light_json
    out = []
    for o in sub.all_objects:
        if o.type != "LIGHT" or o.get("simpler_trashed") or o.hide_render or o.data.type == "SUN":
            continue
        m = o.matrix_world
        out.append({"kind": LIGHT_KINDS.get(o.data.type, "point"), "data": light_json(o),
                    "m": [round(m[r][c], 5) for c in range(4) for r in range(4)]})
    return out


def lamps_sig(coll):
    """What changes the lamps of a distribution's models (on/off at dusk, power, colour): part of its version."""
    parts = []
    for o in coll.all_objects:
        if o.type == "LIGHT" and not o.get("simpler_trashed"):
            d = o.data
            parts.append((o.name, "simpler_power" in o, round(d.energy, 3), tuple(round(x, 3) for x in d.color), d.type))
    return repr(sorted(parts)) if parts else ""


def points(d):
    """GET paint/points?group= -> {rev, file, models: [{model, key, count}]}: the points of a distribution for the
    real-time view, grouped by model (xform 4x4 column-major, float32, in the space of the group), in a file."""
    import numpy as np
    from .core import proto_key
    from . import render
    g = find(d.get("group"))
    pts = _holder(g)
    if pts is None or pts.type != "MESH":
        return {"rev": "", "file": "", "models": []}
    rev = pts.get("simpler_id")
    # (1.79.0) the copies pressed into the snow (snow.press_update) are left out: a file of their own
    ph = pts.get("simpler_pressed") or ""
    stem = rev + ("_p" + ph if ph else "")
    folder = os.path.join(render.view_cache_dir(), "points")      # (one file per points object: they never change)
    os.makedirs(folder, exist_ok=True)
    path = os.path.join(folder, stem + ".bin")
    me = pts.data
    n = len(me.vertices)
    coll = _scatter_coll(g)
    subs = list(coll.children)
    infos = []
    if n:
        xf = np.empty(n * 16, dtype=np.float32)
        mi = np.empty(n, dtype=np.int32)
        me.attributes["simpler_xform"].data.foreach_get("value", xf)
        me.attributes["simpler_model"].data.foreach_get("value", mi)
        xf = xf.reshape(n, 16)
        sa = me.attributes.get(SEASON_ATTR)
        sea = None
        if sa is not None and len(sa.data) == n:
            sea = np.empty(n, dtype=np.float32)
            sa.data.foreach_get("value", sea)
        from . import snow
        pr = snow.pressed_of(pts, n)
        if pr is not None:
            mi = np.where(pr, -1, mi)
        order = np.argsort(mi, kind="stable")
        blocks, seas = [], []
        for k in np.unique(mi):
            sel = order[mi[order] == k]
            sub = subs[k] if 0 <= k < len(subs) else None
            orig = next((o for o in sub.objects if o.parent is None), None) if sub is not None else None
            if orig is None:
                continue
            blocks.append(xf[sel])
            if sea is not None:
                seas.append(sea[sel])
            infos.append({"model": sub.get(MODEL_KEY), "key": proto_key(orig), "id": orig.get("simpler_id"), "count": int(len(sel)),
                          "lamps": sub_lamps(sub)})
        from . import diskcache
        if not os.path.isfile(path):
            np.concatenate(blocks).astype(np.float32).tofile(path) if blocks else open(path, "wb").close()
            diskcache.prune_soon("viewcache/points")    # (1.76.51: one file per distribution made: within limits)
        else:
            diskcache.touch(path)
        if seas:
            # (1.79.0) the season of each piece, in the same order (viewer.js: the leaves of each copy)
            spath = os.path.join(folder, stem + ".s.bin")
            if not os.path.isfile(spath):
                np.concatenate(seas).astype(np.float32).tofile(spath)
            return {"rev": rev, "file": stem + ".bin", "sea": stem + ".s.bin", "models": infos, "count": int((mi >= 0).sum())}
    else:
        open(path, "wb").close()
    return {"rev": rev, "file": stem + ".bin", "models": infos, "count": int((mi >= 0).sum()) if n else 0}


def points_file(name):
    from . import render
    p = os.path.join(render.view_cache_dir(), "points", os.path.basename(name or ""))
    if name and p.endswith(".bin") and os.path.isfile(p):
        from . import diskcache
        diskcache.touch(p)
        return p
    return ""


# ---------------------------------------------------------------- prototypes for the real-time view
# The view draws all the painted pieces of a library model from one copy of it (its "prototype", a small GLB made
# once per model version and kept in the view cache): GPU instancing and levels of detail there. The prototype is
# written by a second Blender (the engine stays free): the first time a model is painted it takes a few seconds,
# then never again (also in other projects).

PROTO = {}          # key -> {"state": running|error, "error", "t"}
_proto_lock = threading.Lock()


def _proto_dir():
    from . import render
    d = os.path.join(render.view_cache_dir(), "proto")
    os.makedirs(d, exist_ok=True)
    return d


def proto_file(name):
    """Path of a prototype file (GET paint/proto.glb?f=), or "" (only files of the prototype folder)."""
    p = os.path.join(_proto_dir(), os.path.basename(name or ""))
    return p if name and p.endswith(".glb") and os.path.isfile(p) else ""


def tag_pieces(root, model_id):
    """A library model placed in the scene: drawn by the real-time view from its prototype (instancing, levels of
    detail, no new preparation of the view). Lights and cameras inside it stay normal objects of the view; a model
    with bones (or other kinds of objects) is left as it is."""
    from .core import PIECE_TYPES
    obs = [root] + list(root.children_recursive)
    if any(o.type not in PIECE_TYPES and o.type not in ("LIGHT", "CAMERA") for o in obs):
        return False
    for o in obs:
        if o.type in PIECE_TYPES:
            o[MODEL_KEY] = model_id
        else:
            if MODEL_KEY in o:
                del o[MODEL_KEY]        # (lights and cameras: never parts of the prototype)
            o["simpler_lib_part"] = model_id     # (but of the model: «Aggiorna dalla libreria» replaces them too)
    return True


def _source(model_id, obj_id=""):
    if obj_id:
        ob = find(obj_id, required=False)
        if ob is not None and ob.get(MODEL_KEY) == model_id and not ob.get("simpler_trashed"):
            return ob
    best = None
    for ob in list(bpy.context.scene.objects) + scatter_originals(live=True):
        if ob.get(MODEL_KEY) != model_id or ob.get("simpler_trashed") or (ob.parent and ob.parent.get(MODEL_KEY)):
            continue
        if not ob.get("simpler_instance_of"):
            return ob
        best = best or ob
    return best


def _maps_are_own(mat, rp):
    """Every picture the view would load for the material is one its nodes really use: an image named as in the model
    file («Bitmaptexture.006» of every Maxtree tree) can be another model's picture in the project - the leaves came
    out fuchsia, painted with a normal map. In doubt the prototype keeps the material of its export."""
    from .matedit import used_images
    used = used_images(mat)
    for d in (rp.get("maps") or {}).values():
        if isinstance(d, dict) and d.get("image") and d["image"] not in used:
            return False
    return True


def _proto_mats(src):
    """(1.78.4, Luca: «in realtime non funziona ma il path tracer sì») the materials of Simpler of a library piece, as
    the view draws them (materials.realtime_params): the prototype's glTF has only what the export understands - an
    inverted opacity map (a «Transparency» of PlantFactory) came out solid - and the materials sent to the view
    reached the prototype only when it was already loaded."""
    from .materials import realtime_params
    out = {}
    for o in [src] + list(src.children_recursive):
        if o.get("simpler_trashed") or o.type != "MESH":
            continue
        for sl in o.material_slots:
            m = sl.material
            if m is not None and m.name not in out:
                rp = realtime_params(m)
                if rp.get("simpler") and _maps_are_own(m, rp):
                    out[m.name] = rp
    return out


def _rest_now(model_id, saved):
    """Where the pieces of a distribution stand in the model (rest matrix of its original and base point), from the
    original of this model in the project - not from the file of the prototype. The prototype is shared by content:
    one made first from a copy of the model placed in the scene has no rest (a placed copy carries its own matrix);
    a distribution then drew its pieces without the model's own turn and scale - a car of an FBX in inches came out
    38 times smaller in the view (the path tracer, using the original, was right)."""
    for ob in scatter_originals(live=True) + scatter_originals():
        if ob.get(MODEL_KEY) != model_id or ob.get("simpler_trashed") or (ob.parent and ob.parent.get(MODEL_KEY)):
            continue
        rest = ob.get("simpler_paint_rest")
        if rest is not None and len(rest) == 16:
            return {"rest": [float(v) for v in rest], "base": [float(v) for v in (ob.get("simpler_paint_base") or (0.0, 0.0, 0.0))]}
    return {}


def proto(data):
    """GET paint/proto?model= -> {state: done (file) | running | error}. Starts the prototype when missing."""
    from . import proxies, render
    from .core import proto_key
    model_id = data.get("model") or ""
    px = render.realtime_texture_px()
    e = models._entries().get(model_id) or {}
    safe = "".join(ch if ch.isalnum() or ch in "-_" else "_" for ch in model_id)
    prefix = f"{safe}_{e.get('rev', '0')}_{px}_"
    src = _source(model_id, data.get("id") or "")
    pk = data.get("key") or (proto_key(src) if src is not None else "")
    if not pk:
        # the model is not in the scene yet (the first stroke of a brush): the last prototype made of it, if any
        made = sorted((f for f in os.listdir(_proto_dir()) if f.startswith(prefix) and f.endswith(".glb")),
                      key=lambda f: os.path.getmtime(os.path.join(_proto_dir(), f)), reverse=True)
        pk = made[0][len(prefix):-4] if made else ""
    key = prefix + pk
    path = os.path.join(_proto_dir(), key + ".glb")
    if pk and os.path.isfile(path):
        from . import diskcache
        diskcache.touch(path); diskcache.touch(path[:-4] + ".json")     # (1.76.51: used - kept by the cache)
        out = {"state": "done", "file": key + ".glb", "key": pk}
        try:
            with open(path[:-4] + ".json", encoding="utf-8") as f:
                out.update(json.load(f))       # rest matrix and base point of the model (for the view's preview)
        except (OSError, ValueError):
            pass
        now = _rest_now(model_id, out)
        if not now and isinstance(e.get("pivot"), list) and len(e["pivot"]) == 3:
            now = {"base": [float(v) for v in e["pivot"]]}      # (1.78.4: no distribution yet - the pivot chosen by hand)
        out.update(now)
        if src is not None:
            out["mats"] = _proto_mats(src)
        return out
    with _proto_lock:
        st = PROTO.get(key)
        if st and (st["state"] == "running" or time.time() - st["t"] < 20):
            return {"state": st["state"], "error": st.get("error", ""), "key": pk}
    if src is None:
        # (1.75.62) no object of this model in the scene any more (changed meanwhile): the last prototype made of it
        # still shows it, instead of an error the view asked again and again
        made = sorted((f for f in os.listdir(_proto_dir()) if f.startswith(prefix) and f.endswith(".glb")),
                      key=lambda f: os.path.getmtime(os.path.join(_proto_dir(), f)), reverse=True)
        if made:
            log("SIMPLER_PROTO", model_id, "not in the scene: the last prototype made of it", made[0])
            from . import diskcache
            diskcache.touch(os.path.join(_proto_dir(), made[0]))
            return {"state": "done", "file": made[0], "key": made[0][len(prefix):-4]}
        ob = find(data.get("id") or "", required=False) if data.get("id") else None
        log("SIMPLER_PROTO", model_id, "not in the scene, no prototype made of it:", "id", data.get("id"),
            "object", ob.name if ob else None, "its model", ob.get(MODEL_KEY) if ob else None,
            "trashed", bool(ob.get("simpler_trashed")) if ob else None, "key", data.get("key"))
        raise ApiError(tr("Modello non presente nella scena"))
    if data.get("key") and proto_key(src) != data["key"]:
        src = next((o for o in list(bpy.context.scene.objects) + scatter_originals() if o.get(MODEL_KEY) == model_id and not o.get("simpler_trashed")
                    and not (o.parent and o.parent.get(MODEL_KEY)) and proto_key(o) == data["key"]), src)
    job_dir = tempfile.mkdtemp(prefix="simpler_proto_", dir=render.STATE.tmp)
    blend = os.path.join(job_dir, "part.blend")
    coll = bpy.data.collections.new("SimplerPart")
    try:
        from .core import PIECE_TYPES
        for o in [src] + list(src.children_recursive):
            if not o.get(INTERNAL_KEY) and not o.get("simpler_trashed") and o.type in PIECE_TYPES and not o.hide_render:
                coll.objects.link(o)
        bpy.data.libraries.write(blend, {coll}, path_remap="ABSOLUTE", compress=False)
    finally:
        bpy.data.collections.remove(coll)
    rest = src.get("simpler_paint_rest")
    info = {"rest": list(rest) if rest is not None and len(rest) == 16 else None,
            "base": list(src.get("simpler_paint_base") or (0.0, 0.0, 0.0))}
    with _proto_lock:
        PROTO[key] = {"state": "running", "t": time.time()}
    if px > 0:
        proxies.ensure_async(sizes=(px,))

    def run():
        t0 = time.time()
        tmp_out = os.path.join(job_dir, "proto.glb")
        err = ""
        try:
            while px > 0 and proxies.status()["running"]:
                time.sleep(0.25)
            map_file = ""
            if px > 0:
                map_file = os.path.join(job_dir, "proxies.json")
                with open(map_file, "w", encoding="utf-8") as f:
                    json.dump(proxies.proxy_map(px), f)
            exe = os.environ.get("SIMPLER_RENDER_EXE") or bpy.app.binary_path
            script = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "export_job.py")
            cmd = [exe, "--factory-startup", "-t", str(render.cpu_threads()), "-b", "--python", script, "--",
                   tmp_out, str(px), map_file, "--append", blend]
            flags = (0x08000000 | 0x00004000) if os.name == "nt" else 0
            r = fullspeed.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, encoding="utf-8",
                               errors="replace", creationflags=flags)
            if r.returncode == 0 and os.path.isfile(tmp_out):
                with open(path[:-4] + ".json", "w", encoding="utf-8") as f:
                    json.dump(info, f)
                os.replace(tmp_out, path)
                from . import diskcache
                diskcache.prune_soon("viewcache/proto")     # (1.76.51: within its limits)
            else:
                err = "\n".join(r.stdout.splitlines()[-6:])
        except Exception as exc:
            err = str(exc)
        finally:
            import shutil
            shutil.rmtree(job_dir, ignore_errors=True)
        with _proto_lock:
            if err:
                PROTO[key] = {"state": "error", "error": err, "t": time.time()}
            else:
                PROTO.pop(key, None)
        log("SIMPLER_PROTO", model_id, "error" if err else "done", f"{time.time() - t0:.1f}s", err[-300:])

    threading.Thread(target=run, daemon=True).start()
    return {"state": "running", "key": pk}


# ---------------------------------------------------------------- «Appoggia alla superficie» (1.76.18)
# The pieces of a distribution (pennello, area, spaziatura, the layers of an ecosystem) dropped again on the surface
# under or over them, along the vertical: the ground moved (a terrain made again or moved, a model moved away) and
# they stayed in the air or buried (Luca: «qualcosa che riposizioni gli item sulla superficie ... vale per tutto»).
# Each piece goes to the nearer of the surface below it and the one above it (buried: up), within DROP_REACH; one
# already on its surface (within DROP_KEEP: a piece sunk a little on purpose) stays. Rotation and scale stay. The
# points object is replaced (undo: objects).
DROP_REACH = 2000.0
DROP_KEEP = 0.3


def _surfaces(box):
    """The surfaces a piece can stand on, as one BVH in world space: the meshes of the scene whose box meets box
    (x0, y0, x1, y1) - not distributions, decals, the sea, the snow mantle, clouds, internal objects."""
    import numpy as np
    from mathutils.bvhtree import BVHTree
    from .core import managed_objects
    x0, y0, x1, y1 = box
    dg = bpy.context.evaluated_depsgraph_get()
    verts, tris, off = [], [], 0
    for o in managed_objects():
        if o.type != "MESH" or o.get("simpler_trashed") or o.hide_render or o.get(DATA_KEY):
            continue
        if o.modifiers.get("Simpler Decal") is not None or any(k in o for k in ("simpler_ocean", "simpler_snow_mantle", "simpler_clouds")):
            continue
        mw = o.matrix_world
        bb = np.array([list(mw @ Vector(c)) for c in o.bound_box])
        if bb[:, 0].max() < x0 or bb[:, 0].min() > x1 or bb[:, 1].max() < y0 or bb[:, 1].min() > y1:
            continue
        ev = o.evaluated_get(dg)
        try:
            me = ev.to_mesh()
        except RuntimeError:
            continue
        try:
            me.calc_loop_triangles()
            nv, nt = len(me.vertices), len(me.loop_triangles)
            if not nv or not nt:
                continue
            co = np.empty(nv * 3, np.float32)
            me.vertices.foreach_get("co", co)
            tv = np.empty(nt * 3, np.int32)
            me.loop_triangles.foreach_get("vertices", tv)
            M = np.array(mw, np.float64)
            w = co.reshape(-1, 3) @ M[:3, :3].T + M[:3, 3]
            verts.append(w)
            tris.append(tv.reshape(-1, 3) + off)
            off += nv
        finally:
            ev.to_mesh_clear()
    if not verts:
        return None
    V = np.concatenate(verts)
    F = np.concatenate(tris)
    return BVHTree.FromPolygons(V.tolist(), F.tolist(), all_triangles=True)


def drop_groups(groups):
    """The pieces of these distribution groups on the surface. -> pieces moved."""
    import numpy as np
    from . import trash
    moved = 0
    for g in groups:
        h = _holder(g)
        if h is None or h.data is None or not len(h.data.vertices):
            continue
        me = h.data
        n = len(me.vertices)
        xa, ma = me.attributes.get("simpler_xform"), me.attributes.get("simpler_model")
        if xa is None or ma is None:
            continue
        xf = np.empty(n * 16, np.float32)
        xa.data.foreach_get("value", xf)
        xf = xf.reshape(n, 4, 4).transpose(0, 2, 1).astype(np.float64)     # (stored column after column)
        mi = np.empty(n, np.int32)
        ma.data.foreach_get("value", mi)
        Hm = np.array(h.matrix_world, np.float64)
        P = xf[:, :3, 3] @ Hm[:3, :3].T + Hm[:3, 3]
        pad = 5.0
        bvh = _surfaces((P[:, 0].min() - pad, P[:, 1].min() - pad, P[:, 0].max() + pad, P[:, 1].max() + pad))
        if bvh is None:
            continue
        dz = np.zeros(n)
        down, up = Vector((0.0, 0.0, -1.0)), Vector((0.0, 0.0, 1.0))
        for i in range(n):
            p = Vector(P[i])
            a = bvh.ray_cast(p + Vector((0.0, 0.0, 0.01)), down, DROP_REACH)
            b = bvh.ray_cast(p - Vector((0.0, 0.0, 0.01)), up, DROP_REACH)
            da = (a[0].z - p.z) if a[0] is not None else None
            db = (b[0].z - p.z) if b[0] is not None else None
            cand = [v for v in (da, db) if v is not None]
            if not cand:
                continue
            d = min(cand, key=abs)
            if abs(d) > DROP_KEEP:
                dz[i] = d
        k = np.abs(dz) > 0
        if not k.any():
            continue
        # the vertical move, in the space of the points
        Hinv = np.linalg.inv(Hm)
        local = np.outer(dz, Hinv[:3, 2])                  # (0, 0, dz) through the inverse rotation/scale
        xf[:, :3, 3] += local
        coll = _scatter_coll(g)
        props = {k2: h[k2] for k2 in h.keys() if k2 not in (ID_KEY, DATA_KEY, "simpler_trashed", "_RNA_UI")}
        sa = h.data.attributes.get(SEASON_ATTR)           # (1.79.0: the seasons of the pieces stay theirs)
        sea = None
        if sa is not None and len(sa.data) == len(mi):
            sea = np.empty(len(mi), dtype=np.float32)
            sa.data.foreach_get("value", sea)
        trash.trash([h])
        pts = _points_object(g, coll, xf, mi, sea)
        pts.hide_render = pts.hide_viewport = h.hide_render
        for k2, v in props.items():
            try:
                pts[k2] = v
            except (TypeError, ValueError):
                pass
        moved += int(k.sum())
    refresh()
    return moved


def dist_groups_of(ids):
    """The distribution groups among these objects and under them (an ecosystem: its layers)."""
    out, seen = [], set()
    for i in ids or []:
        ob = find(i, required=False)
        if ob is None:
            continue
        for o in [ob] + list(ob.children_recursive):
            if o.get(PAINT_KEY) and not o.get("simpler_trashed") and o.name not in seen:
                seen.add(o.name)
                out.append(o)
    return out


def drop(d):
    """POST paint/drop {ids}: «Appoggia alla superficie» for the distributions among ids (and under them)."""
    groups = dist_groups_of(d.get("ids") or ([d["group"]] if d.get("group") else []))
    if not groups:
        raise ApiError(tr("Nessuna distribuzione da appoggiare"))
    from . import progress
    progress.begin("drop", tr("Appoggia alla superficie"))
    try:
        n = drop_groups(groups)
    finally:
        progress.end()
    return {"groups": len(groups), "moved": n}
