"""«Ottimizza poligoni» (1.75.52): fewer triangles for a model far away in the scene.

Blender's Decimate (Collapse: edge collapse driven by the error of the shape) on every distinct mesh of the model:
the materials stay on their faces (each face keeps its material index), the UV coordinates follow, closed surfaces
stay closed. Measured on a sphere of 262,000 triangles with two materials, at 15%: no hole, both materials in place,
their border a clean line, 2.5 s.

- the budget: the triangles asked (ratio × the distinct triangles of the model); pieces under MIN_TRIS are left as
  they are (little to gain, easily spoilt), the rest share what is left with the same ratio
- repeated pieces (copies sharing one mesh) are reduced once, and every copy in the project follows: the new mesh
  takes the place of the old one in every object that used it (also outside the model)
- smooth surfaces stay smooth and sharp edges sharp: sharp edges again from the angle (30°) after the collapse
- undo: the old meshes are kept (history kind «meshes»: their names before and after); Ctrl+Z puts them back
- the preview (POST decimate/preview) computes the same meshes it shows; «Applica» with the same ratio uses them
  at once. The picture: a quick Cycles image of the model alone, clay with the triangles drawn if asked, from the
  direction the camera is looking
"""
import math
import os
import time

import bpy
from mathutils import Vector

from . import progress
from .core import ApiError, find, descendants, refresh
from .i18n import tr

MIN_TRIS = 300
MIN_RATIO = 0.15
SHARP_ANGLE = 30.0
_CACHE = {"root": None, "ratio": None, "meshes": {}}     # mesh name -> reduced mesh (not yet applied)
_CANCEL = {"on": False}
SWAPS = []                                               # (old, new) of the command running, for history
ADDED = []                                               # ids of objects the command made for its new meshes (1.76.8)
REMOVED = []                                             # ids of objects it put in the trash (1.76.15: ecosystems made again)
# (1.75.55) the progress inside a piece: Blender's Decimate says nothing while it works (a piece of 5 million
# triangles: 30 s with the bar still - Luca). The speed measured on the pieces done (triangles a second, kept for the
# next time) gives an estimate of how far the piece on is; GET progress reads it from the HTTP thread (live_fraction).
LIVE = {"on": False, "done": 0, "total": 1, "piece": 0, "t0": 0.0, "rate": 150000.0}


def _tris(me):
    me.calc_loop_triangles()
    return len(me.loop_triangles)


def _pieces(root):
    out = []
    for o in [root] + list(descendants(root)):
        if o.type != "MESH" or o.data is None or not len(o.data.polygons):
            continue
        if o.get("simpler_trashed") or o.get("simpler_paint") or o.get("simpler_kind") == "decal":
            continue
        out.append(o)
    return out


def _meshes(root):
    """The distinct meshes of the model and how many objects of the model use each one."""
    users = {}
    for o in _pieces(root):
        users.setdefault(o.data, []).append(o)
    return users


def info(d):
    """GET decimate/info?id=: triangles (as drawn: copies counted), distinct triangles, pieces, materials, copies
    outside the model that share its meshes."""
    root = find(d.get("id"))
    users = _meshes(root)
    if not users:
        raise ApiError(tr("Questo oggetto non ha superfici da ottimizzare"))
    distinct = {me: _tris(me) for me in users}
    drawn = sum(distinct[me] * len(obs) for me, obs in users.items())
    mats = {s.material.name for obs in users.values() for o in obs for s in o.material_slots if s.material}
    inside = {o for obs in users.values() for o in obs}
    # other models of the scene with the same pieces (copies of the model): their top object, counted once
    scene_obs = set(bpy.context.scene.objects)
    tops = set()
    for o in bpy.data.objects:
        if o.type == "MESH" and o.data in users and o not in inside and o in scene_obs and not o.get("simpler_trashed") \
                and not o.get("simpler_internal"):
            while o.parent is not None:
                o = o.parent
            tops.add(o.name)
    outside = len(tops)
    return {"triangles": drawn, "distinct": sum(distinct.values()), "pieces": len(inside), "meshes": len(users),
            "materials": len(mats), "copiesOutside": outside, "minRatio": MIN_RATIO}


def _ratio_per_mesh(distinct, ratio):
    small = sum(t for t in distinct.values() if t < MIN_TRIS)
    big = sum(t for t in distinct.values() if t >= MIN_TRIS)
    if big == 0:
        return 1.0
    target = ratio * (small + big)
    return max(0.02, min(1.0, (target - small) / big))


def _reduce(me, r):
    """One mesh at ratio r: a new mesh (the old one untouched), materials and UVs kept, sharp edges from the angle."""
    tmp = bpy.data.objects.new("simpler_decimate_tmp", me)
    bpy.context.scene.collection.objects.link(tmp)
    try:
        md = tmp.modifiers.new("Simpler Decimate", "DECIMATE")
        md.decimate_type = "COLLAPSE"
        md.ratio = r
        md.use_collapse_triangulate = False
        dg = bpy.context.evaluated_depsgraph_get()
        new = bpy.data.meshes.new_from_object(tmp.evaluated_get(dg), preserve_all_data_layers=True, depsgraph=dg)
    finally:
        bpy.data.objects.remove(tmp, do_unlink=True)
    new.name = me.name + " (ottimizzata)"
    if any(p.use_smooth for p in me.polygons):
        try:
            new.set_sharp_from_angle(angle=math.radians(SHARP_ANGLE))
        except (AttributeError, TypeError, RuntimeError):
            pass
    for k in me.keys():                                    # (Simpler's marks on the mesh: kept)
        try:
            new[k] = me[k]
        except (TypeError, ValueError):
            pass
    new["simpler_georev"] = int(me.get("simpler_georev", 0)) + 1
    new["simpler_decimated_from"] = me.name
    return new


def _drop_cache(keep=()):
    for name, new in list(_CACHE["meshes"].items()):
        if new.name in keep:
            continue
        if new.users == 0:
            bpy.data.meshes.remove(new)
    _CACHE.update(root=None, ratio=None, meshes={})


def live_fraction():
    """(HTTP thread) The fraction done, the piece on estimated from the speed (never more than 95% of it), and the
    seconds left for that piece - or None when no decimation is running."""
    L = dict(LIVE)
    if not L["on"]:
        return None
    est = L["piece"] / max(1.0, L["rate"])
    part = min(0.95, (time.time() - L["t0"]) / max(0.05, est))
    left = max(0.0, est - (time.time() - L["t0"])) if est > 3 else None     # (said only for long pieces)
    return (L["done"] + part * L["piece"]) / max(1, L["total"]), left


def cancel(_d=None):
    """POST decimate/cancel (answered at once, from the HTTP thread): the computation stops after the piece it is on."""
    _CANCEL["on"] = True
    return {}


def _compute(root, ratio):
    """The reduced meshes for this model and ratio (reused when asked again)."""
    ratio = max(MIN_RATIO, min(1.0, float(ratio)))
    key = root.get("simpler_id")
    if _CACHE["root"] == key and _CACHE["ratio"] is not None and abs(_CACHE["ratio"] - ratio) < 1e-4 and \
            all(bpy.data.meshes.get(n) is not None for n in _CACHE["meshes"]):
        return _CACHE["meshes"], ratio
    _drop_cache()
    users = _meshes(root)
    distinct = {me: _tris(me) for me in users}
    r = _ratio_per_mesh(distinct, ratio)
    todo = sorted([me for me, t in distinct.items() if t >= MIN_TRIS], key=lambda m: -distinct[m])
    total = sum(distinct[m] for m in todo) or 1
    done = 0
    out = {}
    _CANCEL["on"] = False
    t0 = time.time()
    progress.begin("decimate", tr("Ottimizzazione dei poligoni"))
    try:
        if r < 0.999:
            for i, me in enumerate(todo):
                if _CANCEL["on"]:
                    for new in out.values():
                        bpy.data.meshes.remove(new)
                    raise ApiError(tr("Ottimizzazione interrotta"))
                progress.update(tr("Ottimizzazione dei poligoni"), done / total, tr("Pezzo {0} di {1}", i + 1, len(todo)))
                LIVE.update(on=True, done=done, total=total, piece=distinct[me], t0=time.time())
                out[me.name] = _reduce(me, r)
                took = time.time() - LIVE["t0"]
                if distinct[me] >= 20000 and took > 0.05:          # (big pieces only: small ones are mostly overhead)
                    LIVE["rate"] = 0.5 * LIVE["rate"] + 0.5 * distinct[me] / took
                done += distinct[me]
    finally:
        LIVE["on"] = False
        progress.end()
    print(f"SIMPLER_DECIMATE {len(todo)} meshes, ratio {ratio:.2f} (big pieces {r:.3f}), {time.time() - t0:.1f} s", flush=True)
    _CACHE.update(root=key, ratio=ratio, meshes=out)
    return out, ratio


def _result_tris(root, reduced):
    users = _meshes(root)
    t = 0
    for me, obs in users.items():
        new = reduced.get(me.name)
        t += _tris(new if new is not None else me) * len(obs)
    return t


# ---------------------------------------------------------------- the preview picture

def _preview_image(root, reduced, wire, path):
    """A quick Cycles image of the model alone (clay; with wire the triangles drawn), from the camera's direction."""
    pieces = _pieces(root)
    sc = bpy.data.scenes.new("Simpler Decimate Preview")
    made = []
    mat = None
    try:
        lo, hi = Vector((1e30,) * 3), Vector((-1e30,) * 3)
        for o in pieces:
            me = reduced.get(o.data.name, o.data)
            c = bpy.data.objects.new("p", me)
            c.matrix_world = o.matrix_world.copy()
            sc.collection.objects.link(c)
            made.append(c)
            for corner in o.bound_box:
                w = o.matrix_world @ Vector(corner)
                lo = Vector(map(min, lo, w)); hi = Vector(map(max, hi, w))
        centre, radius = (lo + hi) / 2, max(0.01, (hi - lo).length / 2)
        cam_main = bpy.context.scene.camera
        fwd = (cam_main.matrix_world.to_3x3() @ Vector((0, 0, -1))).normalized() if cam_main else Vector((0.6, 0.6, -0.4)).normalized()
        cd = bpy.data.cameras.new("p"); cd.lens = 50
        cam = bpy.data.objects.new("p", cd)
        dist = radius / math.sin(math.atan(18.0 / 50.0)) * 1.1
        cam.location = centre - fwd * dist
        cam.rotation_euler = fwd.to_track_quat("-Z", "Y").to_euler()
        cd.clip_start, cd.clip_end = max(0.001, dist * 0.001), dist * 10
        sc.collection.objects.link(cam); made.append(cam)
        sc.camera = cam
        ld = bpy.data.lights.new("p", "SUN"); ld.energy = 3.0; ld.angle = math.radians(8)
        sun = bpy.data.objects.new("p", ld)
        sun.rotation_euler = (fwd + Vector((0.3, -0.4, -0.8))).normalized().to_track_quat("-Z", "Y").to_euler()
        sc.collection.objects.link(sun); made.append(sun)
        w = bpy.data.worlds.new("p"); w.use_nodes = True
        w.node_tree.nodes["Background"].inputs[0].default_value = (0.42, 0.42, 0.42, 1)      # (neutral: the colours of the model as they are)
        sc.world = w
        if wire:
            # (1.75.52) the triangles: clay with thin dark lines. Without: the model with its own materials and textures
            # (the first version showed clay always, and blue lines so close on a heavy model it looked all blue)
            mat = bpy.data.materials.new("p"); mat.use_nodes = True
            nt = mat.node_tree
            bsdf = nt.nodes["Principled BSDF"]
            bsdf.inputs["Roughness"].default_value = 0.6
            wf = nt.nodes.new("ShaderNodeWireframe"); wf.use_pixel_size = True; wf.inputs[0].default_value = 0.6
            mix = nt.nodes.new("ShaderNodeMix"); mix.data_type = "RGBA"
            mix.inputs[6].default_value = (0.78, 0.78, 0.76, 1); mix.inputs[7].default_value = (0.08, 0.12, 0.2, 1)
            nt.links.new(wf.outputs[0], mix.inputs[0]); nt.links.new(mix.outputs[2], bsdf.inputs["Base Color"])
            sc.view_layers[0].material_override = mat
        r = sc.render
        sc.render.engine = "CYCLES"
        sc.cycles.samples = 12 if wire else 24
        sc.cycles.use_denoising = not wire
        sc.cycles.max_bounces = 2 if wire else 6
        try:
            sc.cycles.device = bpy.context.scene.cycles.device
        except (AttributeError, TypeError):
            pass
        r.resolution_x, r.resolution_y, r.resolution_percentage = 560, 380, 100
        r.film_transparent = False
        sc.view_settings.view_transform = bpy.context.scene.view_settings.view_transform
        r.image_settings.file_format = "PNG"
        r.filepath = path
        bpy.ops.render.render(write_still=True, scene=sc.name)
    finally:
        for o in made:
            data = o.data
            bpy.data.objects.remove(o, do_unlink=True)
            if data is not None and isinstance(data, (bpy.types.Camera, bpy.types.Light)) and data.users == 0:
                (bpy.data.cameras if isinstance(data, bpy.types.Camera) else bpy.data.lights).remove(data)
        if sc.world is not None and sc.world.users <= 1:
            bpy.data.worlds.remove(sc.world)
        bpy.data.scenes.remove(sc)
        if mat is not None and mat.users == 0:
            bpy.data.materials.remove(mat)
    return path


def preview(d):
    """POST decimate/preview {id, ratio, wire, before}: the reduced meshes for this ratio and pictures of the model
    before (when asked) and after. Returns the triangles after."""
    from . import render
    root = find(d.get("id"))
    wire = bool(d.get("wire"))
    folder = os.path.join(render.STATE.tmp, "decimate")
    os.makedirs(folder, exist_ok=True)
    stamp = str(int(time.time() * 1000))
    out = {}
    if d.get("before"):
        out["before"] = _preview_image(root, {}, wire, os.path.join(folder, f"before_{stamp}.png"))
    reduced, ratio = _compute(root, d.get("ratio", 0.5))
    out["after"] = _preview_image(root, reduced, wire, os.path.join(folder, f"after_{stamp}.png"))
    out["triangles"] = _result_tris(root, reduced)
    out["ratio"] = ratio
    return out


def apply(d):
    """POST decimate/apply {id, ratio}: the reduced meshes take the place of the old ones in every object using them
    (the copies in the whole project too). One undo step (kind «meshes»)."""
    root = find(d.get("id"))
    reduced, ratio = _compute(root, d.get("ratio", 0.5))
    if not reduced:
        return {"changed": 0, "triangles": _result_tris(root, {})}
    SWAPS.clear()
    for name, new in reduced.items():
        old = bpy.data.meshes.get(name)
        if old is None:
            continue
        for o in bpy.data.objects:
            if o.type == "MESH" and o.data is old:
                o.data = new
        old.use_fake_user = True                           # (kept for Ctrl+Z)
        SWAPS.append((old.name, new.name))
    _CACHE.update(root=None, ratio=None, meshes={})        # (now in the scene: not the cache's any more)
    refresh()
    tris = _result_tris(root, {})
    print(f"SIMPLER_DECIMATE applied: {len(SWAPS)} meshes, {tris} triangles", flush=True)
    return {"changed": len(SWAPS), "triangles": tris, "ratio": ratio, "geometry": geometry_ids([n for _o, n in SWAPS])}


def geometry_ids(mesh_names):
    """The objects of the scene drawing these meshes (their ids): the real-time view takes them again (before 1.75.52
    fix the view kept the old model after «Applica» - Luca: «sembra rimasto uguale»)."""
    names = set(mesh_names)
    return sorted({o.get("simpler_id") for o in bpy.data.objects
                   if o.type == "MESH" and o.data is not None and o.data.name in names and o.get("simpler_id")
                   and not o.get("simpler_trashed") and not o.get("simpler_internal")})


def discard(_d=None):
    """POST decimate/discard: the window closed without applying - the reduced meshes of the preview go."""
    _drop_cache()
    return {}


def swap_meshes(pairs, undoing):
    """History: the meshes of a decimation back (undoing) or again."""
    for old_name, new_name in pairs:
        old, new = bpy.data.meshes.get(old_name), bpy.data.meshes.get(new_name)
        if old is None or new is None:
            continue
        a, b = (new, old) if undoing else (old, new)
        for o in bpy.data.objects:
            if o.type == "MESH" and o.data is a:
                o.data = b
        b.use_fake_user = False
        a.use_fake_user = True
    refresh()
    return geometry_ids([o if undoing else n for o, n in pairs])


def drop_meshes(pairs, undone):
    """History step dropped: the meshes no longer reachable go (the old ones when the step was not undone)."""
    for old_name, new_name in pairs:
        me = bpy.data.meshes.get(new_name if undone else old_name)
        if me is not None:
            me.use_fake_user = False
            if me.users == 0:
                bpy.data.meshes.remove(me)


def after_open():
    """A project saved while a decimation could still be undone kept its other meshes (fake user): the history starts
    empty after opening, so they go."""
    named = {me.get("simpler_decimated_from") for me in bpy.data.meshes if me.get("simpler_decimated_from")}
    gone = 0
    for me in list(bpy.data.meshes):
        if me.use_fake_user and (me.get("simpler_decimated_from") or me.name in named):
            me.use_fake_user = False
            if me.users == 0:
                bpy.data.meshes.remove(me)
                gone += 1
    if gone:
        print(f"SIMPLER_DECIMATE {gone} meshes kept for undo removed after opening", flush=True)


# ---------------------------------------------------------------- the 3D preview (1.75.54)

_TMP_N = {"n": 0}


def view(d):
    """POST decimate/view {id, which: before|after, ratio}: the model as a GLB for the 3D preview of the window (two views
    side by side that turn together, Luca: «sulle anteprime non si può agire con il mouse»). Copies of its pieces
    (temporary objects, the reduced meshes for «after») go through the same export as the parts of the real-time view
    (textures reduced as there); the scene is not touched. Returns {state, key, triangles} - preview/part/status
    and preview/part.glb follow."""
    from . import render
    from .core import ID_KEY
    root = find(d.get("id"))
    after = d.get("which") == "after"
    reduced = {}
    ratio = None
    if after:
        reduced, ratio = _compute(root, d.get("ratio", 0.5))
    pieces = _pieces(root)
    if not pieces:
        raise ApiError(tr("Questo oggetto non ha superfici da ottimizzare"))
    made, ids, tris = [], [], 0
    try:
        for o in pieces:
            me = reduced.get(o.data.name, o.data)
            _TMP_N["n"] += 1
            c = bpy.data.objects.new("simpler_decimate_view", me)
            c.matrix_world = o.matrix_world.copy()
            for i, s in enumerate(o.material_slots):          # (materials on the object, not on the mesh)
                if s.link == "OBJECT" and i < len(c.material_slots):
                    c.material_slots[i].link = "OBJECT"
                    c.material_slots[i].material = s.material
            bpy.context.scene.collection.objects.link(c)
            c[ID_KEY] = f"decview{_TMP_N['n']}"
            made.append(c)
            ids.append(c[ID_KEY])
            tris += _tris(me)
        out = render.export_part({"ids": ids})
    finally:
        for c in made:
            bpy.data.objects.remove(c, do_unlink=True)
    out["triangles"] = tris
    if ratio is not None:
        out["ratio"] = ratio
    print(f"SIMPLER_DECIMATE view {'after' if after else 'before'}: {len(made)} pieces, {tris} triangles, {out.get('state')}", flush=True)
    return out
