"""Deleted objects stay in memory, out of the scene, until their undo step is gone.

Deleting and restoring is then instant even on huge scenes (no copy of the whole scene to disk for undo), and the
real-time view can show them again without a new export.
"""
import contextlib

import bpy

from .core import ID_KEY

TRASH_KEY = "simpler_trashed"
COLLS_KEY = "simpler_trash_colls"
MASTER = "\x00scene"


def is_trashed(ob):
    return bool(ob.get(TRASH_KEY))


def _by_ids(ids):
    want = set(i for i in ids if i)
    return [ob for ob in bpy.data.objects if ob.get(ID_KEY) in want]


def _collections_of(objects):
    """object -> collections it is in, for many objects at once (users_collection scans all of them every time)."""
    want = set(objects)
    out = {}
    scene = bpy.context.scene
    for c in [scene.collection] + list(bpy.data.collections):
        for o in c.objects:
            if o in want:
                out.setdefault(o, []).append(c)
    return out


def trash(objects):
    from . import twins
    twins.drop_for(objects)
    scene = bpy.context.scene
    colls = _collections_of(objects) if len(objects) > 20 else None
    for ob in objects:
        if is_trashed(ob):
            continue
        names = []
        for c in list(colls.get(ob, []) if colls is not None else ob.users_collection):
            names.append(MASTER if c == scene.collection else c.name)
            c.objects.unlink(ob)
        ob[COLLS_KEY] = names
        ob[TRASH_KEY] = 1
        ob.use_fake_user = True


def restore(objects):
    scene = bpy.context.scene
    inside = {}          # collection -> names of its objects, read once (a name lookup in c.objects is slow)
    for ob in objects:
        if not is_trashed(ob):
            continue
        names = list(ob.get(COLLS_KEY) or []) or [MASTER]
        linked = False
        for n in names:
            c = scene.collection if n == MASTER else bpy.data.collections.get(n)
            if c is None:
                continue
            have = inside.get(c)
            if have is None:
                have = inside[c] = {o.name for o in c.objects}
            if ob.name not in have:
                c.objects.link(ob)
                have.add(ob.name)
                linked = True
        if not linked and not ob.users_collection:
            scene.collection.objects.link(ob)
        ob.use_fake_user = False
        for k in (TRASH_KEY, COLLS_KEY):
            if k in ob:
                del ob[k]
        before = ob.get("simpler_name_before")
        if before:
            # (stepped aside while it was in the trash, core.claim_name: its name back if nobody visible took it)
            del ob["simpler_name_before"]
            other = bpy.data.objects.get(before)
            if other is None or not other.users_scene:
                from .core import claim_name
                claim_name(ob, before)


def trash_ids(ids):
    trash(_by_ids(ids))


def restore_ids(ids):
    # parents first, so children find them back in the scene
    obs = _by_ids(ids)
    obs.sort(key=lambda o: _depth(o))
    restore(obs)


def _depth(ob):
    n = 0
    while ob.parent is not None:
        n += 1
        ob = ob.parent
    return n


def purge_ids(ids):
    """Really delete trashed objects (their undo step is gone)."""
    victims = [ob for ob in _by_ids(ids) if is_trashed(ob)]
    _remove(victims)


def purge_all():
    _remove([ob for ob in bpy.data.objects if is_trashed(ob)])


def _remove(victims):
    if not victims:
        return
    for ob in victims:
        ob.use_fake_user = False
    bpy.data.batch_remove(victims)
    for coll in (bpy.data.meshes, bpy.data.lights):
        for block in list(coll):
            if block.users == 0:
                coll.remove(block)


@contextlib.contextmanager
def excluded():
    """Saving a file: trashed objects are not written (no fake user while saving)."""
    obs = [ob for ob in bpy.data.objects if is_trashed(ob)]
    for ob in obs:
        ob.use_fake_user = False
    try:
        yield
    finally:
        for ob in obs:
            try:
                ob.use_fake_user = True
            except ReferenceError:
                pass
