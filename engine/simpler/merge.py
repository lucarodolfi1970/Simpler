"""«Unisci in un solo oggetto»: the pieces of an imported model joined into one mesh (importing into the scene,
importer.py, and into the library, preview_job.py). The materials stay on their faces."""
import bpy

REPEAT_KEEP = 4                  # a mesh used by this many pieces or more...
REPEAT_VERTS = 200_000           # ...whose copies would add more vertices than this stays as copies (not merged)


def merge_objects(objs, name=None):
    """«Unisci in un solo oggetto»: the pieces of the model joined into one mesh, every material on its faces
    (Blender's join: the slots, also those linked to the objects, follow the faces). Empties go; lamps and cameras
    stay, under the joined mesh. Pieces repeated many times (bolts, chairs) stay copies when merging them would
    add too much geometry (each copy would become vertices of its own)."""
    meshes = [o for o in objs if o.type == "MESH" and o.data is not None and len(o.data.polygons)]
    if len(meshes) <= 1:
        return objs
    users = {}
    for o in meshes:
        users.setdefault(o.data, []).append(o)
    keep_apart = set()
    for me, obs in users.items():
        if len(obs) >= REPEAT_KEEP and len(me.vertices) * (len(obs) - 1) > REPEAT_VERTS:
            keep_apart.update(obs)
    join = [o for o in meshes if o not in keep_apart]
    if len(join) <= 1:
        return objs
    bpy.context.view_layer.update()
    target = join[0]
    join_ptr = {o.as_pointer() for o in join}
    others = [o for o in objs if o.as_pointer() not in join_ptr]     # (the joined pieces cease to exist)
    for o in join:
        mw = o.matrix_world.copy()
        o.parent = None
        o.matrix_world = mw
        if o.data.users > 1:
            o.data = o.data.copy()                       # (join needs its own data for each piece)
    with bpy.context.temp_override(active_object=target, selected_editable_objects=join, selected_objects=join,
                                   object=target):
        bpy.ops.object.join()
    if name:
        target.name = name                               # (the model's name, not the one of its first piece)
    out = [target]
    for o in others:
        if o.type == "EMPTY" and not o.instance_collection:
            for c in list(o.children):                  # (what hangs under it keeps its place)
                mw = c.matrix_world.copy()
                c.parent = None
                c.matrix_world = mw
            bpy.data.objects.remove(o, do_unlink=True)
            continue
        mw = o.matrix_world.copy()
        o.parent = target
        o.matrix_world = mw
        out.append(o)
    print(f"SIMPLER_MERGE {len(join)} pieces -> 1, {len(out) - 1} kept apart", flush=True)
    return out


STRIP_KEYS = ("simpler_paint_model", "simpler_paint_gen", "simpler_paint_rest", "simpler_paint_base",
              "simpler_instance_of", "simpler_trashed", "simpler_twin")


def merge_selection(ids):
    """POST merge {ids}: «Unisci in un solo oggetto» from the tree: the selected objects (a group, a model, several
    pieces), with what is inside them, become one object with all their materials on their faces. The originals go
    to the trash (one undo step: Ctrl+Z puts them back as they were); the joined object is made of copies of their
    geometry, in the place of the first one. Lights and cameras inside stay, under the joined object."""
    from .core import find, descendants, descendants_many, refresh, new_id, claim_name, ApiError, KIND_KEY, INTERNAL_KEY
    from .i18n import tr
    from . import trash
    srcs = [find(i) for i in ids if i]
    sel = set(srcs)
    tops = []
    for ob in srcs:
        p = ob.parent
        while p is not None and p not in sel:
            p = p.parent
        if p is None and ob not in tops:
            tops.append(ob)
    tree = descendants_many(tops)
    if any(o.get("simpler_paint") or o.get(KIND_KEY) == "decal" for o in tree):
        raise ApiError(tr("Distribuzioni e decal non si possono unire: toglili dalla selezione"))
    odd = [o for o in tree if o.type not in ("MESH", "EMPTY", "LIGHT", "CAMERA")]
    if odd:
        raise ApiError(tr("{0} non è fatto di superfici e non si può unire", odd[0].name))
    pieces = [o for o in tree if o.type == "MESH" and o.data is not None and len(o.data.polygons)]
    if len(pieces) < 2:
        raise ApiError(tr("Servono almeno due pezzi con una superficie per unire"))
    refresh()
    world = {o: o.matrix_world.copy() for o in tree}
    parent = tops[0].parent
    name = tops[0].name if len(tops) == 1 else tr("Unione")
    coll = bpy.context.scene.collection
    datamap, copies = {}, []
    for o in tree:
        if o.type == "EMPTY" or (o.type == "MESH" and o not in pieces):
            continue
        c = o.copy()
        if o.data is not None:
            if o.data not in datamap:          # (pieces sharing a mesh keep sharing its copy: repeated pieces)
                datamap[o.data] = o.data.copy()
            c.data = datamap[o.data]
        for k in STRIP_KEYS:
            if k in c:
                del c[k]
        coll.objects.link(c)
        c.parent = None
        c.matrix_world = world[o]
        new_id(c)
        c["simpler_merge_name"] = o.name
        copies.append(c)
    out = merge_objects(copies, None)
    target = out[0]
    for m in [s.material for s in target.material_slots if s.material is not None]:
        m.use_fake_user = False
    trash.trash(tree)
    for c in out:
        n = c.get("simpler_merge_name")
        if n is not None:
            del c["simpler_merge_name"]
            if c is not target:
                claim_name(c, n)               # (a lamp inside keeps its name, not «Luce.001»)
    claim_name(target, name)
    if parent is not None and not parent.get("simpler_trashed"):
        refresh()
        mw = target.matrix_world.copy()
        target.parent = parent
        target.matrix_parent_inverse.identity()
        target.matrix_world = mw
    refresh()
    return {"id": target["simpler_id"], "name": target.name, "pieces": len(pieces), "kept": len(out) - 1}
