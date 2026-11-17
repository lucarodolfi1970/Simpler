"""«Libera memoria» (the red broom in the toolbar): what the scene no longer uses goes out of memory.

What a save already leaves out of the file, taken out now, without saving and opening again:
- the objects deleted and kept for undo (trash.py) - so the undo history is cleared;
- materials, textures, meshes, node groups... no object uses any more (Blender's purge of orphan data).
Kept: whatever has a fake user (the hidden originals for «Ripristina originale», the models of distributions, the
painted puddles...), the library material being edited on no object (a draft) and the previews of the editor.
The path tracing uses only what is in the scene: this frees the memory of the computer (RAM), not of the graphics
card."""
import bpy

from . import history, trash

_KINDS = ("objects", "meshes", "materials", "images", "node_groups", "textures", "curves", "lights", "cameras",
          "volumes", "collections")


def _protected():
    from .materials import DRAFT_KEY
    return [m for m in bpy.data.materials
            if not m.use_fake_user and (m.get(DRAFT_KEY) or m.name.startswith("Simpler Preview"))]


def _image_bytes(im):
    try:
        if not im.has_data:
            return 0
        w, h = im.size
        return int(w) * int(h) * max(1, im.channels) * (4 if im.is_float else 1)
    except Exception:
        return 0


def _dead():
    """The data that would go: trashed objects and, following the users, what only they (or nothing) use."""
    keep = set(_protected())
    umap = bpy.data.user_map()
    dead = {ob for ob in bpy.data.objects if trash.is_trashed(ob)}
    cands = []
    for k in _KINDS:
        for idb in getattr(bpy.data, k):
            if idb.use_fake_user or idb in keep or idb.library is not None:
                continue
            if isinstance(idb, bpy.types.Image) and idb.type != "IMAGE":
                continue                     # (Render Result, Viewer Node: Blender's own)
            cands.append(idb)
    changed = True
    while changed:
        changed = False
        for idb in cands:
            if idb in dead:
                continue
            users = umap.get(idb, set())
            if all(u in dead or u is idb for u in users):
                if isinstance(idb, bpy.types.Object) and idb.users_scene:
                    continue
                dead.add(idb)
                changed = True
    return dead


def preview(_data=None):
    """GET memory: what «Libera memoria» would take away (counts and an estimate of the textures in MB)."""
    dead = _dead()
    count = {k: 0 for k in ("objects", "materials", "images", "meshes", "other")}
    mb = 0
    for idb in dead:
        if isinstance(idb, bpy.types.Object):
            count["objects"] += 1
        elif isinstance(idb, bpy.types.Material):
            count["materials"] += 1
        elif isinstance(idb, bpy.types.Image):
            count["images"] += 1
            mb += _image_bytes(idb)
        elif isinstance(idb, bpy.types.Mesh):
            count["meshes"] += 1
            mb += len(idb.vertices) * 48 + len(idb.loops) * 24
        else:
            count["other"] += 1
    return {**count, "mb": round(mb / 1e6, 1), "undo": len(history.UNDO) + len(history.REDO)}


def purge(_data=None):
    """POST memory/purge: the undo history cleared, the trash emptied, orphan data removed. Returns what went."""
    before = {k: len(getattr(bpy.data, k)) for k in _KINDS}
    history.reset()
    trash.purge_all()
    keep = _protected()
    for m in keep:
        m.use_fake_user = True
    try:
        bpy.data.orphans_purge(do_local_ids=True, do_linked_ids=True, do_recursive=True)
    finally:
        for m in keep:
            try:
                m.use_fake_user = False
            except ReferenceError:
                pass
    gone = {k: before[k] - len(getattr(bpy.data, k)) for k in _KINDS}
    from .core import log
    log("SIMPLER_PURGE", gone)
    return {"gone": gone}
