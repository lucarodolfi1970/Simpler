"""Editing the scene: add, delete, duplicate, rename, parent, transform, lights."""
import json
import math
import os

import bpy
from mathutils import Vector

from .core import (refresh, tree_kids, CM, INTERNAL_KEY, KIND_KEY, ApiError, apply_transform, descendants, descendants_many,
                   ensure_id, find, kind_of, link, new_id, object_json, vec3)
from . import materials
from .i18n import tr

PRIMITIVES = {
    "cube": "Cubo", "sphere": "Sfera", "plane": "Piano", "cylinder": "Cilindro",
    "cone": "Cono", "torus": "Toro",
}
LIGHTS = {"sun": ("SUN", "Sole"), "area": ("AREA", "Luce area"), "spot": ("SPOT", "Spot"), "point": ("POINT", "Luce punto")}


def _mesh_primitive(kind):
    import bmesh
    me = bpy.data.meshes.new(PRIMITIVES[kind])
    bm = bmesh.new()
    if kind != "torus":
        bm.loops.layers.uv.new("UVMap")       # (calc_uvs fills a UV layer only when it already exists)
    if kind == "cube":
        bmesh.ops.create_cube(bm, size=1.0, calc_uvs=True)
        # every face gets the whole picture, upright as seen from outside (the cross of calc_uvs gave each face a
        # small piece of it: a plate or a poster on a box needed scale and offsets worked out to the millimetre)
        uvl = bm.loops.layers.uv.active
        for f in bm.faces:
            n = f.normal
            v = Vector((0.0, 1.0, 0.0)) if abs(n.z) > 0.9 else Vector((0.0, 0.0, 1.0))
            u = v.cross(n)
            us = [l.vert.co.dot(u) for l in f.loops]
            vs = [l.vert.co.dot(v) for l in f.loops]
            u0, u1, v0, v1 = min(us), max(us), min(vs), max(vs)
            for l, a, b in zip(f.loops, us, vs):
                l[uvl].uv = ((a - u0) / max(1e-9, u1 - u0), (b - v0) / max(1e-9, v1 - v0))
    elif kind == "sphere":
        bmesh.ops.create_uvsphere(bm, u_segments=64, v_segments=32, radius=0.5, calc_uvs=True)
    elif kind == "plane":
        bmesh.ops.create_grid(bm, x_segments=1, y_segments=1, size=0.5, calc_uvs=True)
    elif kind == "cylinder":
        bmesh.ops.create_cone(bm, cap_ends=True, segments=64, radius1=0.5, radius2=0.5, depth=1.0, calc_uvs=True)
    elif kind == "cone":
        bmesh.ops.create_cone(bm, cap_ends=True, segments=64, radius1=0.5, radius2=0.0, depth=1.0, calc_uvs=True)
    elif kind == "torus":
        # simple torus: major 0.4, minor 0.1
        import math as m
        segs, rings, R, r = 64, 24, 0.4, 0.1
        verts = []
        for i in range(segs):
            a = 2 * m.pi * i / segs
            for j in range(rings):
                b = 2 * m.pi * j / rings
                verts.append(bm.verts.new(((R + r * m.cos(b)) * m.cos(a), (R + r * m.cos(b)) * m.sin(a), r * m.sin(b))))
        for i in range(segs):
            for j in range(rings):
                a = verts[i * rings + j]
                b = verts[((i + 1) % segs) * rings + j]
                c = verts[((i + 1) % segs) * rings + (j + 1) % rings]
                d = verts[i * rings + (j + 1) % rings]
                bm.faces.new((a, b, c, d))
        uv = bm.loops.layers.uv.new("UVMap")
        bm.verts.index_update()
        for f in bm.faces:
            ii = {v.index // rings for v in f.verts}
            jj = {v.index % rings for v in f.verts}
            for loop in f.loops:
                i, j = divmod(loop.vert.index, rings)
                # seams: faces across the last segment/ring continue past 1.0 instead of wrapping back to 0
                u = segs if (i == 0 and segs - 1 in ii) else i
                w = rings if (j == 0 and rings - 1 in jj) else j
                loop[uv].uv = (u / segs, w / rings)
    if not bm.loops.layers.uv:
        bm.loops.layers.uv.new("UVMap")       # every primitive has texture coordinates
    bm.to_mesh(me)
    bm.free()
    if kind in ("sphere", "cylinder", "cone", "torus"):
        for p in me.polygons:
            # (the flat caps of cylinder and cone stay flat: smoothed, their edge looked like a soft blob)
            p.use_smooth = not (kind in ("cylinder", "cone") and abs(p.normal.z) > 0.99)
    return me


def add(kind, name="", parent_id="", location=None, aim=None, size=None):
    parent = find(parent_id) if parent_id else None
    if kind in PRIMITIVES:
        ob = bpy.data.objects.new(name or tr(PRIMITIVES[kind]), _mesh_primitive(kind))
        link(ob)
        if ob.type == "MESH" and ob.data is not None:
            # a plain white material of its own library entry: a click on the piece opens it in the editor
            ob.data.materials.append(materials.default_white())   # (Simpler's white, not the library's, 1.68.1)
        z = 0.0 if kind == "plane" else (0.1 if kind == "torus" else 0.5)
        ob.location = (0.0, 0.0, z)
    elif kind in LIGHTS:
        ltype, default_name = LIGHTS[kind]
        default_name = tr(default_name)
        data = bpy.data.lights.new(name or default_name, ltype)
        if ltype == "AREA":
            data.shape = "RECTANGLE"
            data.size = data.size_y = 0.5
            data.energy = 300
        elif ltype == "SUN":
            data.energy = 4.0
            data.angle = math.radians(0.53)
        elif ltype == "SPOT":
            data.energy = 500
            data.shadow_soft_size = 0.05
        else:
            data.energy = 300
            data.shadow_soft_size = 0.05
        ob = link(bpy.data.objects.new(name or default_name, data))
        if ltype == "SUN":
            ob.rotation_euler = (math.radians(45), 0, math.radians(30))
        else:
            ob.location = (0.0, -1.5, 2.0)
            _aim(ob, Vector((0, 0, 0.3)))
    elif kind == "group":
        ob = link(bpy.data.objects.new(name or tr("Gruppo"), None))
        ob.empty_display_size = 0.2
    else:
        raise ApiError(tr("Tipo non supportato: {0}", kind))

    if parent:
        _set_parent(ob, parent)
    if location is not None:
        # world position (also inside a group)
        refresh()
        mw = ob.matrix_world.copy()
        mw.translation = Vector(vec3(location, "location")) * CM
        ob.matrix_world = mw
        refresh()
        if ob.type == "LIGHT" and ob.data.type != "SUN":
            target = Vector(vec3(aim, "aim")) * CM if aim is not None else Vector((0, 0, 0))
            _aim_world(ob, target)
            # light sized for the distance it is placed at: default power is meant for about 2 m
            d = max(1e-4, (ob.matrix_world.translation - target).length)
            ob.data.energy *= max(1e-4, min(100.0, (d / 2.0) ** 2))
            if ob.data.type == "AREA":
                ob.data.size = ob.data.size_y = max(0.005, min(5.0, d * 0.25))
            else:
                ob.data.shadow_soft_size = max(0.001, min(0.5, d * 0.025))
    if size is not None and ob.type == "MESH":
        k = max(0.0005, float(size) * CM)           # primitives are 1 m: size in cm
        ob.scale = (k, k, k)
    return {"id": ensure_id(ob), "object": object_json(ob)}


def _aim_world(ob, target):
    refresh()
    pos = ob.matrix_world.translation.copy()
    rot = (target - pos).to_track_quat("-Z", "Y").to_matrix().to_4x4()
    rot.translation = pos
    ob.matrix_world = rot


def _aim(ob, target):
    ob.rotation_mode = "XYZ"
    ob.rotation_euler = (target - ob.location).to_track_quat("-Z", "Y").to_euler("XYZ")


def _set_parent(ob, parent):
    refresh()
    world = ob.matrix_world.copy()
    ob.parent = parent
    ob.matrix_parent_inverse.identity()
    ob.matrix_world = world


def delete(obj_id):
    ob = find(obj_id)
    victims = descendants(ob) + [ob]
    # kept in memory out of the scene: undo puts them back at once (purged when the undo step goes away)
    from . import trash
    trash.trash(victims)
    return {"deleted": len(victims), "ids": [v.get(ID) for v in victims if v.get(ID)]}


def delete_many(ids):
    if not ids:
        raise ApiError(tr("Niente da eliminare"))
    victims = descendants_many([find(i) for i in ids])      # (each once; one look at the file for all)
    # kept in memory out of the scene: undo puts them back at once (purged when the undo step goes away)
    from . import trash
    trash.trash(victims)
    return {"deleted": len(victims), "ids": [v.get(ID) for v in victims if v.get(ID)]}


def _purge_orphans():
    for coll in (bpy.data.meshes, bpy.data.lights):
        for block in list(coll):
            if block.users == 0:
                coll.remove(block)


def duplicate(obj_id):
    src = find(obj_id)
    copies = {}
    copy = _duplicate_tree(src, src.parent, copies)
    _tag_instance(copy, src, False)
    copy.name = src.name + tr(" copia")
    _decals_of_copies([copy])
    # new id -> original id, for the whole tree: the real-time view clones the originals instead of a new export
    return {"id": ensure_id(copy), "object": object_json(copy), "copies": copies}


ID = "simpler_id"
MAX_COPIES = 2000


def duplicate_many(data):
    """POST duplicate/many {ids, mode: "instance"|"copy", count, delta (4x4 column-major, world) | row: true}
    count copies of every object (with its children). Copy k is placed at delta^k x original: the offset of a
    Shift-drag repeated (also a rotation around the pivot: copies in a circle). row=true (paste): side by side along X.
    instance: the copies share geometry and materials with the original (Cycles draws them as instances: almost no
    memory, even thousands). copy: every copy gets its own geometry (independent materials, same memory as the original)."""
    from mathutils import Matrix, Vector
    ids = [i for i in (data.get("ids") or []) if i]
    if not ids:
        raise ApiError(tr("Niente da duplicare"))
    srcs = [find(i) for i in ids]
    sel = set(srcs)
    # only the top of each selected tree (a selected child goes with its parent)
    tops = []
    for ob in srcs:
        p, covered = ob.parent, False
        while p is not None:
            if p in sel:
                covered = True
                break
            p = p.parent
        if not covered:
            tops.append(ob)
    count = max(1, min(MAX_COPIES, int(data.get("count") or 1)))
    deep = data.get("mode") == "copy"
    refresh()
    if isinstance(data.get("delta"), list) and len(data["delta"]) == 16:
        v = data["delta"]
        delta = Matrix([[float(v[c * 4 + r]) for c in range(4)] for r in range(4)])
    else:
        lo, hi = Vector((1e30,) * 3), Vector((-1e30,) * 3)
        for top in tops:
            for o in [top] + list(top.children_recursive):
                if o.type == "MESH":
                    for c in o.bound_box:
                        w = o.matrix_world @ Vector(c)
                        lo = Vector(map(min, lo, w)); hi = Vector(map(max, hi, w))
        width = (hi.x - lo.x) if hi.x >= lo.x else 1.0
        delta = Matrix.Translation((width * 1.1, 0.0, 0.0))
    copies, created = {}, []
    step = Matrix.Identity(4)
    # parts of the trees, once (Object.children scans the whole file at every call: per piece, a copy of a model of
    # 4,000 pieces spent seconds only finding the parts - core.tree_kids, 1.70.3)
    kids = tree_kids(tops)
    # the collections of every part, at once (users_collection looks through every collection at each call: 4.7 s
    # for a copy of the cathedral)
    from .trash import _collections_of
    colls = _collections_of(list(kids))
    for o in list(kids):
        kids[("colls", o)] = colls.get(o, [])
    m0s = {top: top.matrix_world.copy() for top in tops}
    # a decal pasted side by side goes along its own width, on the surface it lies on (not along the world X, off it)
    from . import decals
    row_decal = {}
    if not (isinstance(data.get("delta"), list) and len(data["delta"]) == 16):
        for top in tops:
            if decals.is_decal(top):
                xw = (m0s[top].to_3x3() @ Vector((1, 0, 0))).normalized()
                row_decal[top] = Matrix.Translation(xw * (decals.params(top)["w"] * 0.01 * 1.1))
    steps = {top: Matrix.Identity(4) for top in tops}
    for k in range(1, count + 1):
        step = delta @ step
        for top in tops:
            steps[top] = row_decal.get(top, delta) @ steps[top]
            ob = _duplicate_tree(top, top.parent, copies, deep=deep, kids=kids)
            _tag_instance(ob, top, deep)
            ob.matrix_world = steps[top] @ m0s[top]       # (the parent's matrix is up to date: no scene update per copy)
            created.append(ob)
    refresh()
    for ob in created:
        ob.rotation_mode = "XYZ"
    _decals_of_copies(created)
    return {"ids": [ensure_id(o) for o in created], "copies": copies, "count": count, "mode": "copy" if deep else "instance"}


def _decals_of_copies(created):
    """Decals among the copies (or inside copied models): each gets its own node tree and material and is projected
    on its own piece (a copied decal pointed at the original's piece; one moved off a surface finds the new one)."""
    from . import decals
    # (from the decals up to the copies: children_recursive per copy looked through every object of the file for
    # each one - hundreds of copies of a big scene, seconds)
    tops = set(created)
    for o in [o for o in bpy.data.objects if decals.is_decal(o)]:
        p = o
        while p is not None and p not in tops:
            p = p.parent
        if p is not None:
            if INSTANCE_KEY in o:
                del o[INSTANCE_KEY]          # (a decal has nothing to share: never an "instance")
            decals.retarget(o)


INSTANCE_KEY = "simpler_instance_of"


def _tag_instance(copy, src, deep):
    """An instance remembers its original model (the original of the original, for copies of copies); an
    independent copy is a model of its own."""
    if deep:
        if INSTANCE_KEY in copy:
            del copy[INSTANCE_KEY]
        return
    copy[INSTANCE_KEY] = src.get(INSTANCE_KEY) or ensure_id(src)


def _duplicate_tree(src, parent, copies=None, deep=False, datamap=None, kids=None):
    # default: meshes shared (instances: no extra memory). deep: every copy gets its own geometry - pieces that share
    # a mesh inside the original (e.g. the four prongs of a ring) keep sharing one new mesh inside the copy.
    src_id = src.get(ID)
    ob = src.copy()
    if deep and datamap is None:
        datamap = {}
    if src.type == "LIGHT":
        ob.data = src.data.copy()
    elif deep and src.data is not None and src.type in ("MESH", "CURVE", "SURFACE", "FONT", "META"):
        if src.data not in datamap:
            datamap[src.data] = src.data.copy()
        ob.data = datamap[src.data]
    # (users_collection scans every collection: asked once per source when the caller copies many times)
    if kids is None:
        colls = src.users_collection
    else:
        colls = kids.get(("colls", src))
        if colls is None:
            colls = kids[("colls", src)] = list(src.users_collection)
    for coll in colls:
        coll.objects.link(ob)
    nid = new_id(ob)
    if copies is not None and src_id:
        copies[nid] = src_id
    ob.parent = parent
    ob.matrix_parent_inverse = src.matrix_parent_inverse.copy()
    ob.matrix_basis = src.matrix_basis.copy()
    # (kids: parent -> children computed once by the caller; Object.children scans every object of the file)
    for child in (kids.get(src, ()) if kids is not None else src.children):
        if not child.get(INTERNAL_KEY) and not child.get("simpler_trashed"):
            _duplicate_tree(child, ob, copies, deep, datamap, kids)
    return ob


def rename(obj_id, name):
    name = (name or "").strip()
    if not name:
        raise ApiError(tr("Il nome non può essere vuoto"))
    ob = find(obj_id)
    from .core import claim_name
    claim_name(ob, name)
    return {"name": ob.name}


def set_parent(obj_id, parent_id):
    ob = find(obj_id)
    refresh()
    if not parent_id:
        world = ob.matrix_world.copy()
        ob.parent = None
        ob.matrix_world = world
        return {}
    parent = find(parent_id)
    p = parent
    while p is not None:
        if p == ob:
            raise ApiError(tr("Non puoi spostare un oggetto dentro sé stesso o un suo figlio"))
        p = p.parent
    _set_parent(ob, parent)
    return {}


ORDER_KEY = "simpler_order"


def _siblings(parent):
    from .core import managed_objects
    return [o for o in managed_objects() if o.parent == parent and not o.get("simpler_trashed")]


def tree_sort_key(o):
    """Same order as the app's tree: the place set by dragging, then imported files first, then the name."""
    return (o.get(ORDER_KEY, 10 ** 9), 0 if kind_of(o) == "file" else 1, o.name.lower())


def set_order(data):
    """POST order {ids, parent, target, where: before|after}: the objects (an original with its instances) go into
    the group `parent` (or the root) right before or after `target` in the tree. The siblings are numbered again."""
    ids = [i for i in (data.get("ids") or []) if i]
    if not ids:
        return {}
    parent = find(data["parent"]) if data.get("parent") else None
    moving = [find(i) for i in ids]
    for ob in moving:
        if ob.parent != parent:
            set_parent(ob.get(ID), data.get("parent") or "")
    rest = sorted([o for o in _siblings(parent) if o not in moving], key=tree_sort_key)
    target = find(data["target"], required=False) if data.get("target") else None
    if target in rest:
        k = rest.index(target) + (1 if data.get("where") == "after" else 0)
    else:
        k = len(rest)
    ordered = rest[:k] + moving + rest[k:]
    for n, o in enumerate(ordered):
        o[ORDER_KEY] = n * 10
    return {}


def order_undo_ids(data):
    """For the undo step: the moving objects and every sibling that gets a new number."""
    out = set(i for i in (data.get("ids") or []) if i)
    parent = find(data["parent"], required=False) if data.get("parent") else None
    out.update(o.get(ID) for o in _siblings(parent) if o.get(ID))
    return list(out)


def set_parent_many(ids, parent_id):
    """Several objects into the same group (an original and its instances move together)."""
    for i in ids:
        set_parent(i, parent_id)
    return {}


def transform(obj_id, data):
    ob = find(obj_id)
    apply_transform(ob, data)
    return {"object": object_json(ob)}


def set_noscatter(ids, value):
    """POST noscatter {ids, value}: the Area tool of Distribuisci passes through these objects (Escludi da Area)."""
    for i in ids:
        ob = find(i)
        if value:
            ob["simpler_noscatter"] = True
        elif "simpler_noscatter" in ob:
            del ob["simpler_noscatter"]
    return {}


def set_visible(obj_id, visible):
    ob = find(obj_id)
    for o in [ob] + descendants(ob):
        o.hide_render = not visible
        o.hide_viewport = not visible
    return {}


# ---------------------------------------------------------------- sun position (time of day, north)

SUN_DEFAULTS = {"hour": 10.5, "north": 0.0, "day": 172, "lat": 45.5}   # 10:30, 21 June, Milan


def sun_params(ob):
    import json
    p = dict(SUN_DEFAULTS)
    try:
        p.update(json.loads(ob.get("simpler_sun") or "{}"))
    except ValueError:
        pass
    return p


def sun_vector(hour, north, day, lat):
    """Direction towards the sun in the scene (Z up). Local solar time; north = where north points, degrees
    clockwise from +Y seen from above. Declination from the day of the year (good to a fraction of a degree)."""
    phi = math.radians(lat)
    dec = math.radians(23.44) * math.sin(math.radians(360.0 / 365.0 * (day - 81)))
    h = math.radians(15.0 * (hour - 12.0))
    east = -math.cos(dec) * math.sin(h)
    nrt = math.sin(dec) * math.cos(phi) - math.cos(dec) * math.cos(h) * math.sin(phi)
    up = math.sin(dec) * math.sin(phi) + math.cos(dec) * math.cos(h) * math.cos(phi)
    t = math.radians(north)
    n_dir = Vector((math.sin(t), math.cos(t), 0.0))
    e_dir = Vector((math.cos(t), -math.sin(t), 0.0))
    return (e_dir * east + n_dir * nrt + Vector((0.0, 0.0, up))).normalized()


def _sun_fade(z):
    """Light of the sun near and below the horizon: full above 3°, nothing below -1° (night)."""
    el = math.degrees(math.asin(max(-1.0, min(1.0, z))))
    x = max(0.0, min(1.0, (el + 1.0) / 4.0))
    return x * x * (3 - 2 * x)


def apply_sun(ob):
    """Points the sun light (and the sky of "Esterno giorno") as its time of day and north say."""
    import json
    from . import ambience
    if ambience.sun_changed(ob):                 # the sun of the Ambiente: sky, colour and strength follow
        refresh()
        return ambience._sun_dir(ambience.state())
    p = sun_params(ob)
    v = sun_vector(float(p["hour"]), float(p["north"]), float(p["day"]), float(p["lat"]))
    refresh()
    mw = ob.matrix_world.copy()
    loc, _rot, scale = mw.decompose()
    q = Vector((0.0, 0.0, 1.0)).rotation_difference(v)      # the sun shines along its -Z: +Z looks at the sun
    from mathutils import Matrix
    ob.matrix_world = Matrix.LocRotScale(loc, q, scale)
    power = float(p.get("power", ob.data.energy))
    p["power"] = power
    ob.data.energy = power * _sun_fade(v.z)
    ob["simpler_sun"] = json.dumps(p)
    w = bpy.context.scene.world
    if w is not None and w.get("simpler_env") == "esterno_giorno" and w.node_tree is not None:
        for n in w.node_tree.nodes:
            if n.type == "TEX_SKY":
                n.sun_elevation = math.asin(max(-1.0, min(1.0, v.z)))
                n.sun_rotation = math.atan2(-v.x, v.y) % (2 * math.pi)
    return v


def set_light(obj_id, data):
    ob = find(obj_id)
    if ob.type != "LIGHT":
        raise ApiError(tr("L'oggetto non è una luce"))
    if "type" in data:
        new_type = {"point": "POINT", "spot": "SPOT", "area": "AREA", "sun": "SUN"}.get(str(data["type"]).lower())
        if not new_type:
            raise ApiError(tr("Tipo di luce non valido"))
        if ob.data.type != new_type:
            old = ob.data.type
            if ob.data.users > 1:
                ob.data = ob.data.copy()
            ob.data.type = new_type
            d = ob.data
            # sensible defaults when switching: keep the look roughly comparable
            if new_type == "SUN":
                d.energy = 4.0
                d.angle = math.radians(0.53)
            elif old == "SUN":
                d.energy = 500.0
            if new_type == "SPOT" and old != "SPOT":
                d.spot_size = math.radians(45)
                d.spot_blend = 0.25
            if new_type == "AREA" and old != "AREA":
                d.shape = "RECTANGLE"
                d.size = d.size_y = 0.5
            if ob.get(KIND_KEY):
                del ob[KIND_KEY]
            if "simpler_sun" in ob:
                del ob["simpler_sun"]
    d = ob.data
    if "kelvin" in data:
        k = float(data["kelvin"] or 0)
        d.use_temperature = k > 0
        if k > 0:
            d.temperature = min(40000.0, max(800.0, k))     # (the colour, if any, tints it: they multiply)
    if "shadow" in data:
        d.use_shadow = bool(data["shadow"])
    if "reflections" in data:
        ob.visible_glossy = bool(data["reflections"])
    if "visibleCamera" in data:
        ob.visible_camera = bool(data["visibleCamera"])    # the emitting surface seen in the image (LED strips)
    if "power" in data:
        from . import dusk
        if d.type == "SUN":
            d.energy = max(0.0, float(data["power"]))
        else:
            dusk.set_user_power(ob, max(0.0, float(data["power"])))     # (switched off: kept for when it lights)
        if d.type == "SUN" and ob.get("simpler_sun"):
            import json
            p = sun_params(ob)
            p["power"] = d.energy
            ob["simpler_sun"] = json.dumps(p)
            apply_sun(ob)                      # the user's intensity, dimmed at dawn and dusk
    if "color" in data:
        d.color = vec3(data["color"], "color")
    if d.type == "AREA":
        if "width" in data:
            d.size = max(0.001, float(data["width"]) * CM)
        if "height" in data:
            d.size_y = max(0.001, float(data["height"]) * CM)
        if "shape" in data and data["shape"] in ("RECTANGLE", "SQUARE", "DISK", "ELLIPSE"):
            d.shape = data["shape"]
    if d.type in ("POINT", "SPOT") and "radius" in data:
        d.shadow_soft_size = max(0.0, float(data["radius"]) * CM)
    if d.type == "SPOT":
        if "coneAngle" in data:
            d.spot_size = math.radians(min(180.0, max(1.0, float(data["coneAngle"]))))
        if "blend" in data:
            d.spot_blend = min(1.0, max(0.0, float(data["blend"])))
    if "range" in data:
        ob["simpler_light_range"] = max(0.0, float(data["range"] or 0))       # metres, 0 = physical (no limit)
    if "gobo" in data:
        path = str(data["gobo"] or "")
        if path and not os.path.isfile(path):
            raise ApiError(tr("Immagine non trovata"))
        ob["simpler_light_gobo"] = path
    _light_nodes(ob)
    if d.type == "SUN" and "angle" in data:
        d.angle = math.radians(max(0.0, float(data["angle"])))
    if d.type == "SUN" and isinstance(data.get("sun"), dict):
        import json
        p = sun_params(ob)
        if not ob.get("simpler_sun"):
            p["power"] = d.energy
        for k in ("hour", "north", "day", "lat"):
            if k in data["sun"]:
                p[k] = float(data["sun"][k])
        p["hour"] = max(0.0, min(24.0, p["hour"]))
        p["north"] = p["north"] % 360.0
        p["day"] = max(1.0, min(365.0, p["day"]))
        p["lat"] = max(-89.0, min(89.0, p["lat"]))
        ob["simpler_sun"] = json.dumps(p)
        apply_sun(ob)
    if "aimAt" in data:
        target = find(data["aimAt"]).matrix_world.translation
        _aim(ob, target)
    if "on" in data or "dusk" in data or "type" in data:
        # Accesa / Dal tramonto all'alba (dusk.py)
        from . import dusk
        if "on" in data:
            ob[dusk.ON_KEY] = int(bool(data["on"]))
        if "dusk" in data:
            ob[dusk.DUSK_KEY] = int(bool(data["dusk"]))
        if ob.data.type == "SUN" and dusk.POWER_KEY in ob:
            ob.data.energy = float(ob[dusk.POWER_KEY])
            del ob[dusk.POWER_KEY]
        dusk.apply_lamp(ob)
    return {"object": object_json(ob)}


# ---------------------------------------------------------------- environments

ENVIRONMENTS = {
    "studio_morbido": "Studio morbido",
    "studio_contrasto": "Studio contrastato",
    "esterno_giorno": "Esterno giorno",
    "notte": "Fondo scuro",
}


def environments_json():
    # the presets of the Ambiente (physical sky) first, then the studio backgrounds
    from . import ambience
    amb = [{"id": "amb_" + p[0], "name": tr(p[1])} for p in ambience.PRESETS if p[0] != "studio"]
    return {"environments": amb + [{"id": k, "name": tr(v)} for k, v in ENVIRONMENTS.items() if k != "esterno_giorno"]}


def _world():
    w = bpy.context.scene.world
    if w is None:
        w = bpy.data.worlds.new("Simpler World")
        bpy.context.scene.world = w
    if w.node_tree is None:
        w.use_nodes = True
    return w


def set_environment(env_id, strength=1.0):
    from . import ambience
    if env_id.startswith("amb_") or env_id in ("esterno_giorno", "ambience"):
        pid = env_id[4:] if env_id.startswith("amb_") else ((ambience.state() or {}).get("preset") or "giorno")
        ambience.api_set({"preset": pid if pid != "custom" else "giorno"})
        return {"environment": env_id}
    # (checked before the sky goes away: an unknown id - "hdri" from a scene or an undo step saved with a
    # photo background - took away the ground with its material and its decals, then failed)
    if env_id not in ENVIRONMENTS:
        raise ApiError(tr("Ambiente sconosciuto: {0}", env_id))
    if ambience.state() is not None and ambience.state().get("mode") in ("sky", "hdri"):
        # a studio background: the sky, its haze and its ground go away (the settings stay for later)
        st = ambience.state()
        st["mode"] = "studio"
        w0 = bpy.context.scene.world
        ambience._fog(None)
        ambience._ground(None)
        ambience._remove(ambience.MOON_KEY)
        ambience._sun_object(create=False, release=True)
        if w0 is not None:
            w0[ambience.KEY] = json.dumps(st)
    w = _world()
    nt = w.node_tree
    nt.nodes.clear()
    out = nt.nodes.new("ShaderNodeOutputWorld")
    bg = nt.nodes.new("ShaderNodeBackground")
    nt.links.new(bg.outputs[0], out.inputs[0])
    if env_id == "esterno_giorno":
        sky = nt.nodes.new("ShaderNodeTexSky")
        try:
            sky.sky_type = "MULTIPLE_SCATTERING"
        except TypeError:
            pass
        sky.sun_elevation = math.radians(35)
        sky.sun_rotation = math.radians(120)
        nt.links.new(sky.outputs[0], bg.inputs[0])
        bg.inputs[1].default_value = 0.35 * strength
    else:
        color = {"studio_morbido": (0.06, 0.062, 0.068), "studio_contrasto": (0.04, 0.045, 0.05), "notte": (0.004, 0.005, 0.008)}[env_id]
        bg.inputs[0].default_value = (*color, 1.0)
        bg.inputs[1].default_value = strength
    w["simpler_env"] = env_id
    w["simpler_env_strength"] = float(strength)
    return {"environment": env_id}


def new_scene():
    """Empty scene in the open air: physical sky with sun, light haze and a ground to the horizon (Ambiente)."""
    from . import ambience
    bpy.ops.wm.read_factory_settings(use_empty=True)
    _world()
    ambience.apply(ambience.preset_state("giorno"))
    return {}


def new_studio_scene():
    """Empty scene with a neutral cyclorama floor, soft studio world and a 3-point light rig."""
    bpy.ops.wm.read_factory_settings(use_empty=True)
    set_environment("studio_morbido", 1.0)

    floor = add("plane", tr("Pavimento"))["id"]
    fl = find(floor)
    fl.scale = (20, 20, 1)
    materials.assign([floor], "pavimento_studio")

    # one sun, soft enough for product shots; other lights are added by the user (+ button)
    sun = find(add("sun")["id"])
    sun.data.energy = 3.0
    sun.data.angle = math.radians(3.0)
    sun.rotation_euler = (math.radians(40), 0, math.radians(35))
    return {}


# ---------------------------------------------------------------- gizmo edits (world space)

def translate_world(obj_id, delta_cm):
    ob = find(obj_id)
    d = Vector(vec3(delta_cm, "delta")) * CM
    mw = ob.matrix_world.copy()
    mw.translation = mw.translation + d
    ob.matrix_world = mw
    return {"object": object_json(ob)}


def rotate_world(obj_id, axis, degrees):
    from mathutils import Matrix
    ob = find(obj_id)
    if axis not in ("x", "y", "z"):
        raise ApiError(tr("Asse non valido"))
    pivot = ob.matrix_world.translation.copy()
    rot = Matrix.Rotation(math.radians(float(degrees)), 4, axis.upper())
    ob.matrix_world = Matrix.Translation(pivot) @ rot @ Matrix.Translation(-pivot) @ ob.matrix_world
    ob.rotation_mode = "XYZ"
    return {"object": object_json(ob)}


def scale_local(obj_id, factor):
    ob = find(obj_id)
    f = vec3(factor, "factor")
    ob.scale = (ob.scale[0] * f[0], ob.scale[1] * f[1], ob.scale[2] * f[2])
    return {"object": object_json(ob)}


def set_matrices(items):
    """Several world matrices at once (multi-selection gizmo). Parents first, so children stay consistent."""
    from mathutils import Matrix
    obs = []
    for it in items:
        ob = find(it.get("id"))
        values = it.get("matrix")
        if not isinstance(values, list) or len(values) != 16:
            raise ApiError(tr("Matrice non valida"))
        obs.append((ob, Matrix([[float(values[c * 4 + r]) for c in range(4)] for r in range(4)])))

    def depth(o):
        n = 0
        while o.parent is not None:
            n += 1
            o = o.parent
        return n

    obs.sort(key=lambda t: depth(t[0]))
    refresh()
    for ob, m in obs:
        ob.matrix_world = m
        ob.rotation_mode = "XYZ"
        refresh()          # the next (deeper) object must see its parent's new matrix
    return {"objects": [object_json(ob) for ob, _ in obs]}


def set_matrix_world(obj_id, values):
    """Matrix from the real-time viewport gizmo (column-major, metres)."""
    from mathutils import Matrix
    ob = find(obj_id)
    if not isinstance(values, list) or len(values) != 16:
        raise ApiError(tr("Matrice non valida"))
    m = Matrix([[float(values[c * 4 + r]) for c in range(4)] for r in range(4)])
    refresh()
    ob.matrix_world = m
    refresh()
    ob.rotation_mode = "XYZ"
    return {"object": object_json(ob)}


# ---------------------------------------------------------------- faces turned the wrong way

def fix_normals(ids):
    """Turns outwards the faces of the chosen pieces (and of the pieces inside a group): a face turned inwards is
    black or wrong in the path tracing behind glass, with translucency, normal maps, two-sided lighting. Returns the
    faces flipped per mesh, for undo."""
    import bmesh
    obs = [o for o in descendants_many([find(i, required=False) for i in ids]) if o.type == "MESH" and o.data is not None]
    flipped, total = {}, 0
    for me in {o.data for o in obs}:
        bm = bmesh.new()
        bm.from_mesh(me)
        before = [f.normal.copy() for f in bm.faces]
        bmesh.ops.recalc_face_normals(bm, faces=bm.faces)
        bm.faces.ensure_lookup_table()
        idx = [k for k, f in enumerate(bm.faces) if f.normal.dot(before[k]) < 0]
        if idx:
            bm.to_mesh(me)
            me.update()
            from .matedit import bump_geometry
            bump_geometry(me)
            flipped[me.name] = idx
            total += len(idx)
        bm.free()
    return {"flipped": total, "meshes": len(flipped), "undo": flipped}


def flip_faces(flipped):
    """Undo / redo of fix_normals: the same faces turned again."""
    import bmesh
    for name, idx in flipped.items():
        me = bpy.data.meshes.get(name)
        if me is None:
            continue
        bm = bmesh.new()
        bm.from_mesh(me)
        bm.faces.ensure_lookup_table()
        faces = [bm.faces[k] for k in idx if k < len(bm.faces)]
        bmesh.ops.reverse_faces(bm, faces=faces)
        bm.to_mesh(me)
        me.update()
        from .matedit import bump_geometry
        bump_geometry(me)
        bm.free()



# ---------------------------------------------------------------- light: reach and projected picture

def _light_nodes(ob):
    """Node tree of a lamp for what Cycles lights cannot do by themselves:
      · reach ("range", metres): the light fades to nothing at that distance - strength × (1 − (d/R)⁴)², the same
        window as real-time engines (three.js, Unreal); not physical, but it keeps a lamp local without changing its
        power near it. 0 = physical light (inverse square, no limit).
      · projection (spot only): a picture shone through the cone like a projector or a gobo: the direction of each
        ray (Texture Coordinate > Normal, the light's own space) is turned into a point of the picture, the cone
        fitting the picture's height.
    Without either, no node tree (the plain, fastest light)."""
    d = ob.data
    reach = float(ob.get("simpler_light_range", 0.0)) if d.type in ("POINT", "SPOT", "AREA") else 0.0
    gobo = str(ob.get("simpler_light_gobo", "")) if d.type == "SPOT" else ""
    if reach <= 0 and not gobo:
        # back to the plain light: the tree emptied to Emission -> Output (turning use_nodes off is not enough
        # since Blender 5 - the lamp's nodes are always used: a projection taken away stayed in the picture)
        nt = d.node_tree
        # (only a tree Simpler made - range or projection: the nodes of an imported lamp, an IES, stay as they are)
        ours = bool(d.get("simpler_lamp_nodes"))
        if nt is not None and not ours:
            # (lamps of projects before 1.67.5: no mark - a tree made only of the nodes Simpler uses is Simpler's)
            kinds = {n.type for n in nt.nodes}
            ours = kinds <= {"OUTPUT_LIGHT", "EMISSION", "LIGHT_PATH", "MATH", "TEX_COORD", "SEPXYZ", "COMBXYZ",
                             "SEPARATE_XYZ", "COMBINE_XYZ", "TEX_IMAGE"} and bool(kinds & {"LIGHT_PATH", "TEX_COORD"})
        if nt is not None and ours and any(n.type not in ("OUTPUT_LIGHT", "EMISSION") for n in nt.nodes):
            nt.nodes.clear()
            out = nt.nodes.new("ShaderNodeOutputLight")
            em = nt.nodes.new("ShaderNodeEmission")
            nt.links.new(em.outputs[0], out.inputs["Surface"])
        if ours:
            if "simpler_lamp_nodes" in d:
                del d["simpler_lamp_nodes"]
            if getattr(d, "use_nodes", False):
                try:
                    d.use_nodes = False
                except (AttributeError, TypeError):
                    pass
        return
    d.use_nodes = True
    d["simpler_lamp_nodes"] = 1
    nt = d.node_tree
    nt.nodes.clear()
    N, L = nt.nodes, nt.links
    out = N.new("ShaderNodeOutputLight")
    em = N.new("ShaderNodeEmission")
    L.new(em.outputs[0], out.inputs["Surface"])
    if reach > 0:
        lp = N.new("ShaderNodeLightPath")
        a = N.new("ShaderNodeMath"); a.operation = "DIVIDE"; a.inputs[1].default_value = reach
        L.new(lp.outputs["Ray Length"], a.inputs[0])
        p4 = N.new("ShaderNodeMath"); p4.operation = "POWER"; p4.inputs[1].default_value = 4.0
        L.new(a.outputs[0], p4.inputs[0])
        om = N.new("ShaderNodeMath"); om.operation = "SUBTRACT"; om.inputs[0].default_value = 1.0; om.use_clamp = True
        L.new(p4.outputs[0], om.inputs[1])
        sq = N.new("ShaderNodeMath"); sq.operation = "POWER"; sq.inputs[1].default_value = 2.0
        L.new(om.outputs[0], sq.inputs[0])
        L.new(sq.outputs[0], em.inputs["Strength"])
    if gobo:
        tc = N.new("ShaderNodeTexCoord")
        sep = N.new("ShaderNodeSeparateXYZ"); L.new(tc.outputs["Normal"], sep.inputs[0])
        negz = N.new("ShaderNodeMath"); negz.operation = "MULTIPLY"; negz.inputs[1].default_value = -1.0
        L.new(sep.outputs["Z"], negz.inputs[0])
        k = 1.0 / (2.0 * math.tan(min(math.radians(179.0), d.spot_size) / 2.0))
        cx = N.new("ShaderNodeCombineXYZ")
        for i, comp in enumerate(("X", "Y")):
            dv = N.new("ShaderNodeMath"); dv.operation = "DIVIDE"
            L.new(sep.outputs[comp], dv.inputs[0]); L.new(negz.outputs[0], dv.inputs[1])
            ma = N.new("ShaderNodeMath"); ma.operation = "MULTIPLY_ADD"
            ma.inputs[1].default_value = k; ma.inputs[2].default_value = 0.5
            L.new(dv.outputs[0], ma.inputs[0])
            L.new(ma.outputs[0], cx.inputs[i])
        tex = N.new("ShaderNodeTexImage")
        tex.image = bpy.data.images.load(gobo, check_existing=True)
        tex.extension = "CLIP"
        L.new(cx.outputs[0], tex.inputs["Vector"])
        L.new(tex.outputs["Color"], em.inputs["Color"])


# ---------------------------------------------------------------- pieces of a library model (opened for editing)
# A library model in the scene is drawn by the real-time view from its prototype (all its parts merged by material,
# shared by its copies): fast, but a part has no node of its own there, so it cannot be picked, outlined alone or
# moved. "Opening" the model takes the mark of the library off it and its parts (kept aside): for the view they are
# ordinary objects again, exported one by one; closing puts the mark back (the view draws it from a prototype again,
# a new one if a part was moved or given a material of its own). Only one model is open at a time.
MODEL_KEY = "simpler_paint_model"
OPEN_KEY = "simpler_open_model"        # the model id, kept aside on the root of an opened model


def _model_root(ob):
    root = None
    o = ob
    while o is not None:
        if o.get(MODEL_KEY) or o.get(OPEN_KEY):
            root = o
        o = o.parent
    return root


def open_model(data):
    """POST model/open {id}: opens the library model the piece belongs to (the others are closed). {root} or {}."""
    ob = find(data.get("id") or "")
    root = _model_root(ob)
    if root is None:
        return {"root": "", "changed": close_models({})["changed"]}
    # (pieces of a distribution are made from its strokes: they stay as they are)
    if root.get("simpler_paint_gen") or (root.parent is not None and root.parent.get("simpler_paint")):
        return {"root": "", "changed": False}
    changed = close_models({"keep": root.get("simpler_id", "")})["changed"]
    if root.get(OPEN_KEY):
        return {"root": root.get("simpler_id", ""), "changed": changed}
    model = root[MODEL_KEY]
    for o in [root] + list(root.children_recursive):      # (deleted ones too: undo brings them back)
        if MODEL_KEY in o:
            del o[MODEL_KEY]
    root[OPEN_KEY] = model
    return {"root": root.get("simpler_id", ""), "changed": True}


def close_models(data=None):
    """POST model/close {keep}: closes every opened model but the one with that root id."""
    keep = (data or {}).get("keep") or ""
    changed = False
    for root in [o for o in bpy.context.scene.objects if o.get(OPEN_KEY)]:
        if keep and root.get("simpler_id") == keep:
            continue
        model = root[OPEN_KEY]
        del root[OPEN_KEY]
        _free_decals(root)
        for o in [root] + [c for c in root.children_recursive if not c.get(INTERNAL_KEY)]:
            o[MODEL_KEY] = model           # (pieces added inside meanwhile, a copy of a part, belong to it too)
        changed = True
    return {"changed": changed}


def _free_decals(root):
    """Decals put on a part while the model was open: out of the model before it is closed (they are not part of
    it: with its mark they disappeared from the view and the tree - after saving and opening the project too); in the
    world where they are, still projected on the part."""
    from . import decals
    for d in [c for c in root.children_recursive if decals.is_decal(c)]:
        mw = d.matrix_world.copy()
        if d.parent is not None:
            d["simpler_decal_target"] = d.parent.name
        d.parent = None
        d.matrix_world = mw
        if MODEL_KEY in d:
            del d[MODEL_KEY]
        decals.apply(d)


def repair_decals():
    """Projects saved by 1.28.0-1.28.6: decals that got the mark of a library model when it was closed."""
    from . import decals
    for d in [o for o in bpy.context.scene.objects if decals.is_decal(o) and o.get(MODEL_KEY)]:
        mw = d.matrix_world.copy()
        if d.parent is not None and (d.parent.get(MODEL_KEY) or d.parent.get(OPEN_KEY)):
            d["simpler_decal_target"] = d.parent.name
            d.parent = None
            d.matrix_world = mw
        del d[MODEL_KEY]
        decals.apply(d)


# ---------------------------------------------------------------- size of a piece (Proprietà ▸ Trasformazione)

def size_of(data):
    """GET size?id=: how big the piece is with what it contains, in metres - along its own axes (a car turned by
    105° is still 4.5 × 1.8 × 1.4 m) and in the world. Shows at a glance a model imported with the wrong units."""
    refresh()                      # (matrices of the children after a move or a turn)
    ob = find(data.get("id") or "")
    inv = ob.matrix_world.inverted_safe()
    sc = ob.matrix_world.to_scale()
    lo, hi = [1e30] * 3, [-1e30] * 3
    wlo, whi = [1e30] * 3, [-1e30] * 3
    tris = 0
    for o in [ob] + descendants(ob):
        # (1.75.56) the triangles of the model as drawn (copies counted), shown under the size: a polygon of n corners
        # is n-2 triangles, so loops - 2 × polygons, with no triangulation (instant on millions)
        if o.type == "EMPTY" and o.instance_type == "COLLECTION" and o.instance_collection is not None:
            tris += sum(len(x.data.loops) - 2 * len(x.data.polygons) for x in o.instance_collection.all_objects
                        if x.type == "MESH" and x.data is not None)
        if o.type not in ("MESH", "CURVE", "SURFACE", "META", "FONT") or o.hide_render or o.get(INTERNAL_KEY):
            continue
        if o.type == "MESH" and o.data is not None:
            tris += len(o.data.loops) - 2 * len(o.data.polygons)
        for c in o.bound_box:
            w = o.matrix_world @ Vector(c)
            l = inv @ w
            for i in range(3):
                lo[i] = min(lo[i], l[i]); hi[i] = max(hi[i], l[i])
                wlo[i] = min(wlo[i], w[i]); whi[i] = max(whi[i], w[i])
    if hi[0] < lo[0]:
        return {"size": None}
    return {"size": [round((hi[i] - lo[i]) * abs(sc[i]), 5) for i in range(3)],
            "world": [round(whi[i] - wlo[i], 5) for i in range(3)], "triangles": tris}


# ---------------------------------------------------------------- pivot of a model placed by hand (the violet gizmo)

def set_pivot(data):
    """POST pivot {id, pivot: [x, y, z] in the object's own space (metres) | null}: where the gizmo stands when the
    model is selected - its "handle" for moving, turning and scaling, chosen by the user. null: back to automatic."""
    ob = find(data.get("id") or "")
    p = data.get("pivot")
    if p is None:
        if "simpler_pivot" in ob:
            del ob["simpler_pivot"]
    else:
        ob["simpler_pivot"] = [float(v) for v in vec3(p, "pivot")]
    # (1.78.4, Luca) the pivot of a model of the library is kept in the library too: the next copies and the brush
    # Distribuisci stand the model on it (paint.contact_point)
    try:
        from . import models
        models.keep_pivot(ob)
    except Exception as exc:
        from .core import log
        log("SIMPLER_WARN", "pivot to the library", exc)
    return {"object": object_json(ob)}
