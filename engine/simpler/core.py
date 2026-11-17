"""Object identity, units and JSON serialisation of the scene."""
import math
import uuid

import bpy
from .i18n import tr
from mathutils import Euler, Vector

ID_KEY = "simpler_id"
KIND_KEY = "simpler_kind"
INTERNAL_KEY = "simpler_internal"
SOURCE_KEY = "simpler_source"

CM = 0.01  # API lengths are centimetres, Blender works in metres


def log(tag, *parts):
    """A line in engine.log with the clock time (to measure where the seconds go)."""
    import time as _t
    now = _t.time()
    stamp = _t.strftime("%H:%M:%S", _t.localtime(now)) + f".{int(now * 1000) % 1000:03d}"
    print(f"{tag} {stamp} " + " ".join(str(p) for p in parts), flush=True)


class ApiError(Exception):
    """An error message meant for the user (Italian)."""


# ---------------------------------------------------------------- identity

def ensure_id(ob):
    if ID_KEY not in ob:
        ob[ID_KEY] = uuid.uuid4().hex[:12]
    return ob[ID_KEY]


def new_id(ob):
    ob[ID_KEY] = uuid.uuid4().hex[:12]
    return ob[ID_KEY]


_FOUND = {}       # id -> object, while one request runs (server: find_reset after each, and at every file load)


def find(obj_id, required=True):
    """The object with this id. Looking through every object took 4-11 ms on a scene of 8,000 objects (and
    bpy.data.objects.get(name) 0.3 ms), and many actions look for one id after another (a selection of hundreds,
    the undo step of a whole model: seconds); an id found once in a request is found again at once (checked: the id
    may have moved, the object may be gone - then searched again)."""
    if obj_id:
        ob = _FOUND.get(obj_id)
        if ob is not None:
            try:
                if ob.get(ID_KEY) == obj_id:
                    return ob
            except ReferenceError:              # (removed meanwhile)
                pass
        if not _FOUND:
            first = None
            for ob in bpy.data.objects:            # (one pass: every id of the file, the first one as before)
                i = ob.get(ID_KEY)
                if i and i not in _FOUND:
                    _FOUND[i] = ob
                    if i == obj_id:
                        first = ob
            if first is not None:
                return first
        else:
            for ob in bpy.data.objects:
                if ob.get(ID_KEY) == obj_id:
                    _FOUND[obj_id] = ob
                    return ob
    if required:
        raise ApiError(tr("Oggetto non trovato"))
    return None


_RESET = []       # other lookups kept for one request (water bodies...): emptied with _FOUND


def per_request(cache):
    """A dict that lives for one request (and is emptied at every file load), like the ids of find."""
    _RESET.append(cache)
    return cache


def find_reset(*_args):
    _FOUND.clear()
    for c in _RESET:
        c.clear()


@bpy.app.handlers.persistent
def _find_reset_on_load(*_args):
    find_reset()                                # (another file: the objects found before are gone)


for _h in (bpy.app.handlers.load_pre, bpy.app.handlers.load_post):
    if _find_reset_on_load not in _h:
        _h.append(_find_reset_on_load)


def is_managed(ob):
    return not ob.get(INTERNAL_KEY) and ob.name in bpy.context.scene.objects


def managed_objects():
    return [ob for ob in bpy.context.scene.objects if not ob.get(INTERNAL_KEY)]


def tree_kids(roots):
    """parent -> children for the trees under roots. Object.children (and children_recursive) look through every
    object of the file at each call: 1-3 ms on a scene of 8,000 objects, so walking a model of 4,300 pieces child
    by child took 3-13 s (the size of the cathedral, a copy, a material on the whole model). One children_recursive
    per root instead - or, for many roots, one look at every object."""
    roots = [r for r in roots if r is not None]
    if len(roots) > 3:
        every = {}
        for o in bpy.data.objects:
            p = o.parent
            if p is not None:
                every.setdefault(p, []).append(o)
        kids, stack = {}, list(roots)
        while stack:
            o = stack.pop()
            if o in kids:
                continue
            kids[o] = every.get(o, [])
            stack.extend(kids[o])
        return kids
    seen = {}
    for r in roots:
        if r is None or r in seen:
            continue
        seen[r] = None
        for o in r.children_recursive:
            seen[o] = None
    kids = {o: [] for o in seen}
    for o in seen:
        p = o.parent
        if p is not None and p in kids:
            kids[p].append(o)
    return kids


def with_trees(roots):
    """The roots and everything under them (each once; see tree_kids)."""
    roots = [r for r in roots if r is not None]
    kids = tree_kids(roots)
    out, seen = [], set()
    for r in roots:
        stack = [r]
        while stack:
            o = stack.pop()
            if o in seen:
                continue
            seen.add(o)
            out.append(o)
            stack.extend(reversed(kids.get(o, ())))
    return out


def descendants_many(obs, include_self=True):
    """The objects and what is under each of them (as descendants), each once, with one look at the file for all of
    them (descendants object by object looked through the whole file each time: the undo step of a material on the
    cathedral, 4,300 times - 39 s)."""
    obs = [o for o in obs if o is not None]
    kids = tree_kids(obs)
    out, seen = [], set()

    def walk(o):
        for c in kids.get(o, ()):
            if c not in seen and not c.get(INTERNAL_KEY) and not c.get("simpler_trashed"):
                seen.add(c)
                out.append(c)
                walk(c)
    for ob in obs:
        if include_self and ob not in seen:
            seen.add(ob)
            out.append(ob)
        walk(ob)
    return out


def descendants(ob):
    kids = tree_kids([ob])
    out = []

    def walk(o):
        for child in kids.get(o, ()):
            if not child.get(INTERNAL_KEY) and not child.get("simpler_trashed"):
                out.append(child)
                walk(child)
    walk(ob)
    return out


def claim_name(ob, wanted):
    """The name the user wants (or the name of a library model just placed), as it is: when it is taken only by
    something the user does not see - an object deleted and kept for undo, the model of a distribution (not in the
    scene), an internal helper - that one steps aside (its old name is kept to come back on undo). Before, Blender
    added .001, .002... and a rename "did nothing" (the same name with the same number came back)."""
    wanted = (wanted or "").strip()[:63]
    if not wanted or ob.name == wanted:
        return ob.name
    other = bpy.data.objects.get(wanted)
    if other is not None and other != ob and (other.get("simpler_trashed") or other.get(INTERNAL_KEY)
                                             or other.get("simpler_twin") or not other.users_scene):
        if not other.get("simpler_name_before"):
            other["simpler_name_before"] = other.name
        other.name = wanted[:52] + " ·hidden"
    ob.name = wanted
    return ob.name


def link(ob, collection=None):
    (collection or bpy.context.scene.collection).objects.link(ob)
    ensure_id(ob)
    ob.rotation_mode = "XYZ"
    return ob


# ---------------------------------------------------------------- kinds

LIGHT_KINDS = {"SUN": "sun", "AREA": "area", "SPOT": "spot", "POINT": "point"}


def kind_of(ob):
    if ob.get(KIND_KEY):
        return ob[KIND_KEY]
    if ob.type == "MESH":
        return "mesh"
    if ob.type == "LIGHT":
        return LIGHT_KINDS.get(ob.data.type, "light")
    if ob.type == "EMPTY":
        return "group"
    if ob.type == "CAMERA":
        return "camera"
    return ob.type.lower()


# ---------------------------------------------------------------- vectors

def vec3(value, name):
    if not isinstance(value, (list, tuple)) or len(value) != 3:
        raise ApiError(tr("'{0}' deve essere una lista di 3 numeri", name))
    return [float(v) for v in value]


def r3(v, nd=4):
    return [round(float(x), nd) for x in v]


# ---------------------------------------------------------------- json

def light_json(ob):
    d = ob.data
    out = {
        "power": round(float(ob["simpler_power"]) if "simpler_power" in ob else d.energy, 3),   # (off: its own power)
        "color": r3(d.color),
        "on": bool(ob.get("simpler_on", 1)),          # Accesa (dusk.py)
        "dusk": bool(ob.get("simpler_dusk", 0)),      # Dal tramonto all'alba
        "lit": "simpler_power" not in ob,             # lit now (the real-time view switches it off otherwise)
    }
    if d.type == "AREA":
        out["shape"] = d.shape
        out["width"] = round(d.size / CM, 2)
        out["height"] = round((d.size_y if d.shape in ("RECTANGLE", "ELLIPSE") else d.size) / CM, 2)
    elif d.type in ("POINT", "SPOT"):
        out["radius"] = round(d.shadow_soft_size / CM, 2)
        if d.type == "SPOT":
            out["coneAngle"] = round(math.degrees(d.spot_size), 2)
            out["blend"] = round(d.spot_blend, 3)
    elif d.type == "SUN":
        out["angle"] = round(math.degrees(d.angle), 3)
        import json
        try:
            sun = json.loads(ob.get("simpler_sun") or "{}")
        except ValueError:
            sun = {}
        if sun:
            out["power"] = round(float(sun.get("power", d.energy)), 3)     # the user's intensity (not dimmed at dusk)
        out["sun"] = {k: sun.get(k, v) for k, v in {"hour": 10.5, "north": 0.0, "day": 172, "lat": 45.5}.items()}
        out["sunSet"] = bool(sun)
    out["caustics"] = bool(d.cycles.is_caustics_light)
    out["type"] = d.type
    out["kelvin"] = round(d.temperature, 1) if d.use_temperature else 0
    out["shadow"] = bool(d.use_shadow)
    out["reflections"] = bool(ob.visible_glossy)
    out["visibleCamera"] = bool(ob.visible_camera)
    if d.type in ("POINT", "SPOT", "AREA"):
        out["range"] = round(float(ob.get("simpler_light_range", 0.0)), 3)
    if d.type == "SPOT" and ob.get("simpler_light_gobo"):
        out["gobo"] = ob["simpler_light_gobo"]
        if d.use_nodes and d.node_tree is not None:
            im = next((n.image for n in d.node_tree.nodes if n.type == "TEX_IMAGE" and n.image is not None), None)
            if im is not None:
                out["goboImage"] = im.name          # (the real-time view loads it through GET /api/texture)
    if ob.get("simpler_ambience_sun") or ob.get("simpler_ambience_moon"):
        out["ambience"] = True            # driven by the Ambiente panel (sky, time of day)
    if d.type == "SPOT":
        out["coneAngle"] = round(math.degrees(d.spot_size), 2)
        out["blend"] = round(d.spot_blend, 3)
    if d.type in ("POINT", "SPOT"):
        out["radius"] = round(d.shadow_soft_size / CM, 2)
    return out


def object_json(ob):
    parent = ob.parent if ob.parent and not ob.parent.get(INTERNAL_KEY) else None
    loc, rot, scale = ob.matrix_basis.decompose()
    eul = ob.rotation_euler if ob.rotation_mode == "XYZ" else rot.to_euler("XYZ")
    out = {
        "id": ensure_id(ob),
        "name": ob.name,
        "kind": kind_of(ob),
        "parent": parent.get(ID_KEY) if parent else "",
        "visible": not ob.hide_render,
        "location": r3(Vector(loc) / CM, 3),
        "rotation": r3([math.degrees(a) for a in eul], 3),
        "scale": r3(scale, 4),
    }
    mw = ob.matrix_world
    out["matrixWorld"] = [round(mw[r][c], 6) for c in range(4) for r in range(4)]  # column-major, metres
    if ob.get(SOURCE_KEY):
        out["source"] = ob[SOURCE_KEY]
    if ob.get("simpler_noscatter"):
        out["noScatter"] = True           # the Area tool of Distribuisci puts nothing on it
    from .rain import rain_dry, snow_dry
    if rain_dry(ob):
        out["dry"] = True                 # «Sempre asciutto» → Pioggia: the rain does not wet it (rain.py)
    if snow_dry(ob):
        out["noSnow"] = True              # «Sempre asciutto» → Neve: no snow on it
    if ob.get("simpler_noshelter"):
        out["noShelter"] = True           # «Non fa riparo»: the rain reaches what is under it (rain.py)
    if ob.get("simpler_nomantle"):
        out["noMantle"] = True            # «Senza mantello»: no layer of snow on it (snow.py)
    if ob.get("simpler_snow_detail") in ("high", "low"):
        out["snowDetail"] = ob["simpler_snow_detail"]   # «Dettaglio neve» of the model (snow.py)
    # (lights and cameras inside a library model stay objects of the view of their own - a stale mark on them, copied
    # from another model, kept them out of the view: not drawn, not selectable there)
    if ob.get("simpler_paint_model") and ob.type in PIECE_TYPES:
        out["paintModel"] = ob["simpler_paint_model"]
        if parent is None or not parent.get("simpler_paint_model"):
            out["paintRoot"] = True       # a painted piece: drawn by the real-time view from its library model
            out["protoKey"] = proto_key(ob)
            if ob.get("simpler_paint_gen"):
                out["paintGen"] = True    # made from the strokes of its distribution (re-made when they change)
    if ob.get("simpler_pivot") is not None:
        out["pivot"] = [round(float(v), 6) for v in ob["simpler_pivot"]]   # gizmo placed by hand (own space, metres)
    if ob.get("simpler_open_model"):
        out["openModel"] = True           # a library model opened to change its parts (scene_ops.open_model)
    if ob.get("simpler_eco"):
        out["eco"] = "group"              # an ecosystem placed in the scene (ecosystems.py): its layers inside
    elif ob.get("simpler_eco_layer"):
        out["eco"] = "layer"
    elif ob.get("simpler_eco_plot"):
        out["eco"] = "plot"
    if ob.get("simpler_paint"):
        out["paint"] = True
        kids = _KIDS.get(ob, ()) if _KIDS is not None else ob.children
        pts = next((c for c in kids if c.get("simpler_paint_data") and not c.get("simpler_trashed")), None)
        if pts is not None and pts.type == "MESH":
            # changes at every change of the distribution: its points, or how its models look (a material...)
            rev = pts.get(ID_KEY, "")
            if pts.get("simpler_pressed"):
                rev += ":p" + pts["simpler_pressed"]     # (1.79.0: copies pressed into the sculpted snow)
            coll = bpy.data.collections.get(ob.get("simpler_scatter_coll") or "")
            if coll is not None:
                import hashlib
                keys = [proto_key(o) for sub in coll.children for o in sub.objects if o.parent is None]
                from .paint import lamps_sig
                keys.append(lamps_sig(coll))        # (its lamps on or off: the view lights them as they are)
                rev += ":" + hashlib.sha1("|".join(keys).encode()).hexdigest()[:8]
            out["paintRev"] = rev
            out["paintCount"] = len(pts.data.vertices)
    # (Luca: «il menu di destra deve tenere conto del tipo oggetto») what Simpler made it as: the menus of the app
    # leave out what does not apply to it (a zone of a terrain is not a model to optimize or turn into vegetation)
    role = ("ground" if ob.get("simpler_ground") else "zone" if ob.get("simpler_terrain_zone")
            else "terrain" if ob.get("simpler_terrain") and ob.type == "EMPTY" else "scree" if ob.get("simpler_scree")
            else "screeLayer" if ob.get("simpler_scree_layer") else "")
    if role:
        out["role"] = role
    if ob.get("simpler_order") is not None:
        out["order"] = int(ob["simpler_order"])          # place among its siblings in the tree (set by dragging)
    if ob.get(KIND_KEY) == "decal":
        from . import decals
        out["decal"] = decals.info(ob)
    if ob.type == "LIGHT":
        out["light"] = light_json(ob)
    if ob.type == "MESH":
        out["materials"] = [s.material.name if s.material else "" for s in ob.material_slots]
    return out


def refresh():
    """Re-evaluate the scene: children's matrix_world is only updated by the depsgraph. Without this,
    after moving a parent its children would still report (and the UI would snap them back to) the old place."""
    bpy.context.view_layer.update()


PIECE_TYPES = {"MESH", "EMPTY", "CURVE", "SURFACE", "META", "FONT"}


_KIDS = None      # parent -> children, while scene_json runs (children_recursive scans every object: slow with thousands)


def _below(o):
    if _KIDS is None:
        return list(o.children_recursive)
    out, todo = [], list(_KIDS.get(o, ()))
    while todo:
        c = todo.pop()
        out.append(c)
        todo.extend(_KIDS.get(c, ()))
    return out


def proto_key(root):
    """What the real-time view draws for a library piece (paint.py, prototypes): its parts, where they are inside it,
    their geometry and materials, hidden parts. Two pieces with the same key look the same; a piece changed in the
    scene (a part moved, a material "only for this object", a part hidden) gets a key and a prototype of its own."""
    import hashlib
    h = hashlib.sha1()
    inv = root.matrix_world.inverted_safe()
    rows = []
    for o in [root] + list(_below(root)):
        if o.get("simpler_trashed") or o.get(INTERNAL_KEY) or o.type not in PIECE_TYPES:
            continue
        parts = [o.type, int(o.hide_render)]
        if o is not root:
            m = inv @ o.matrix_world
            parts += [round(m[r][c], 4) for r in range(3) for c in range(4)]
        if o.type == "MESH" and o.data is not None:
            parts += [len(o.data.vertices), len(o.data.polygons)]
        parts += [s.material.name if s.material else "" for s in o.material_slots]
        parts += [md.type for md in o.modifiers]
        dc = _dry_code(o)
        if dc:
            parts.append("dry" if dc == 1 else f"dry{dc}")   # («Sempre asciutto» on a part: in the prototype, see export_job.py)
        rows.append(repr(parts))
    # in an order that does not depend on the names: two copies of a model get their parts renamed in a different
    # order (Sphere / Sphere.006...) and had different keys, so the view prepared every copy again
    for r in [rows[0]] + sorted(rows[1:]) if rows else []:
        h.update(r.encode("utf-8", "replace"))
    return h.hexdigest()[:12]


def _empty_split(o):
    """(1.76.31, Luca: «Elimina la suddivisione» took it from the panel but not from the scene tree) a part of «Dividi
    zona» taken away keeps its object with an empty mesh (Ctrl+Z gives it back): not listed while empty."""
    z = o.get("simpler_terrain_zone")
    if not isinstance(z, str) or not z or o.type != "MESH":
        return False
    from .terrain import ZONES
    return z not in ZONES and (o.data is None or not len(o.data.polygons))


def scene_json():
    refresh()
    obs = [o for o in managed_objects() if not o.get("simpler_paint_data")   # (paint.py: strokes of a distribution)
           and not _empty_split(o)]
    # parents before children, stable by name
    order = {}

    def depth(o):
        d = 0
        p = o.parent
        while p is not None:
            d += 1
            p = p.parent
        return d

    obs.sort(key=lambda o: (depth(o), o.name))
    global _KIDS
    _KIDS = {}
    for o in bpy.context.scene.objects:
        if o.parent is not None:
            _KIDS.setdefault(o.parent, []).append(o)
    try:
        out = _scene_json(obs)
        # emissive materials and their switch (dusk.py): the app redraws in the real-time view the ones that changed
        # (time of day, undo, a saved view...)
        out["emitLit"] = {m.name: int(m["simpler_lit"]) for m in bpy.data.materials if "simpler_lit" in m and m.users}
        return out
    finally:
        _KIDS = None


def _scene_json(obs):
    # instances. A copy made as "Istanza" carries simpler_instance_of = the id of the original model; the original
    # carries nothing. Scenes made before (no tag): models sharing geometry form a group, the first by name is the
    # original. Parts repeated inside one model (the prongs of a ring) never count.
    def top(o):
        while o.parent is not None and not o.parent.get(INTERNAL_KEY):
            o = o.parent
        return o
    by_id = {o.get(ID_KEY): o for o in obs if o.get(ID_KEY)}

    def meshes_of(o):
        return {c.data.name for c in [o] + _below(o) if c.type == "MESH" and c.data is not None}
    instance_of = {}
    for o in obs:
        src = by_id.get(o.get("simpler_instance_of") or "")
        if src is not None and src is not o and meshes_of(o) & meshes_of(src):
            instance_of[o] = src
    tops_of = {}
    for o in obs:
        if o.type == "MESH" and o.data is not None:
            tops_of.setdefault(o.data.name, set()).add(top(o))
    parent_of = {}

    def find(t):
        while parent_of.get(t, t) is not t:
            t = parent_of[t]
        return t
    for tops in tops_of.values():
        tops = sorted(tops, key=lambda t: t.name)
        for t in tops[1:]:
            a, b = find(tops[0]), find(t)
            if a is not b:
                parent_of[b] = a
    clusters = {}
    for t in {top(o) for o in obs}:
        clusters.setdefault(find(t), []).append(t)
    targets = set(instance_of.values())
    for members in clusters.values():
        if len(members) < 2:
            continue
        tagged = [m for m in members if m in targets]
        original = tagged[0] if tagged else min(members, key=lambda m: m.name)
        for m in members:
            if m is not original and m not in instance_of and not any(a in instance_of for a in [m] + _below(m)):
                instance_of[m] = original
    counts = {}
    for src in instance_of.values():
        counts[src] = counts.get(src, 0) + 1
    out = []
    for o in obs:
        j = object_json(o)
        if o in instance_of:
            j["instanceOf"] = instance_of[o].get(ID_KEY)
        if counts.get(o):
            j["instanceCount"] = counts[o]
        out.append(j)
    return {"objects": out}


def apply_transform(ob, data):
    """location (cm), rotation (deg XYZ), scale - relative to the parent."""
    if "location" in data:
        ob.location = Vector(vec3(data["location"], "location")) * CM
    if "rotation" in data:
        ob.rotation_mode = "XYZ"
        ob.rotation_euler = Euler([math.radians(a) for a in vec3(data["rotation"], "rotation")], "XYZ")
    if "scale" in data:
        ob.scale = vec3(data["scale"], "scale")


def materials_is_transmissive(mat):
    from . import materials
    return materials.is_transmissive(mat)


def _dry_code(o):
    from .rain import dry_code
    return dry_code(o)
