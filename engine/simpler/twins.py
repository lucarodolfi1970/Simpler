"""Path tracing view: an invisible "twin" for every mesh, so a change to the scene does not rebuild everything.

Blender renders with Cycles in "final render" mode here (background process), and in that mode Cycles bakes the
position of every object used only once into its vertices (static BVH). It is the fastest layout for a single
render, but after any change - an object moved, a light dimmed, a material edited - Cycles bakes and uploads the
whole geometry again: about 2.4 s on a 1 GB scene with an RTX 4080, longer on slower cards.

A geometry used by two objects is never baked: it stays on the graphics card once and the objects only carry their
own position (instancing). So every single-user mesh gets a twin object that shares its mesh, follows it with a
Copy Transforms constraint and is invisible to every kind of ray that matters (only "volume scatter" visibility
is left on, otherwise Cycles would drop the object). Measured with Blender 5.2.2: a change to the scene goes from
1.8 s to 0.2 s on a test scene, and the samples cost 2-4% more. The twins are internal: never shown in the app,
removed from the copies used for the final render (full speed there) and for the real-time view export.
"""
import bpy

from .core import INTERNAL_KEY

TWIN_KEY = "simpler_twin"
COLL_NAME = "Simpler Twins"
RAY_FLAGS = ("visible_camera", "visible_diffuse", "visible_glossy", "visible_transmission", "visible_shadow")


def _collection(create=True):
    scene = bpy.context.scene
    coll = bpy.data.collections.get(COLL_NAME)
    if coll is None:
        if not create:
            return None
        coll = bpy.data.collections.new(COLL_NAME)
        coll[INTERNAL_KEY] = 1
    if create and coll.name not in scene.collection.children:
        scene.collection.children.link(coll)
    return coll


def is_twin(ob):
    return bool(ob.get(TWIN_KEY))


def original_of(ob):
    """The object a twin follows (or the object itself)."""
    if ob is not None and is_twin(ob) and ob.constraints:
        return ob.constraints[0].target or ob
    return ob


def _target(twin):
    return twin.constraints[0].target if twin.constraints else None


def _eligible(ob):
    # meshes with modifiers are not shared by Cycles (their geometry belongs to the object): a twin would not help
    return (ob.type == "MESH" and ob.data is not None and not is_twin(ob) and not ob.get(INTERNAL_KEY)
            and len(ob.modifiers) == 0 and not ob.get("simpler_trashed"))


def ensure():
    """Twins for the meshes that need one, stale twins removed. Cheap when nothing changed. Returns changes made."""
    scene = bpy.context.scene
    coll = _collection(create=True)
    in_scene = set(scene.objects)
    users = {}
    for ob in in_scene:
        if ob.type == "MESH" and not is_twin(ob):
            users[ob.data] = users.get(ob.data, 0) + 1
    have, stale = {}, []
    for tw in list(coll.objects):
        tgt = _target(tw)
        if (tgt is None or tgt not in in_scene or tgt.data is not tw.data or not _eligible(tgt)
                or users.get(tgt.data, 0) != 1 or tgt in have):
            stale.append(tw)
        else:
            have[tgt] = tw
    if stale:
        bpy.data.batch_remove(stale)       # (in one call: one by one costs a look through all the objects each)
    made = 0
    for ob in list(scene.objects):          # again: the stale twins removed above were in the first list
        if ob in have or not _eligible(ob) or users.get(ob.data, 0) != 1:
            continue
        tw = bpy.data.objects.new("twin·" + ob.name, ob.data)
        tw[INTERNAL_KEY] = 1
        tw[TWIN_KEY] = 1
        coll.objects.link(tw)
        con = tw.constraints.new("COPY_TRANSFORMS")
        con.target = ob
        for flag in RAY_FLAGS:
            setattr(tw, flag, False)
        tw.visible_volume_scatter = True
        tw.hide_select = True
        made += 1
    return made + len(stale)


def drop_for(objects):
    """Twins of objects that leave the scene (deleted): removed at once so their meshes can be freed."""
    coll = _collection(create=False)
    if coll is None:
        return
    gone = set(objects)
    drop = [tw for tw in coll.objects if _target(tw) in gone]
    if drop:
        bpy.data.batch_remove(drop)


def remove_all():
    """No twins (the copy of the scene for the final render: static layout is the fastest for one image)."""
    bpy.data.batch_remove([o for o in bpy.data.objects if o.get(TWIN_KEY)])
    coll = bpy.data.collections.get(COLL_NAME)
    if coll is not None:
        bpy.data.collections.remove(coll)
