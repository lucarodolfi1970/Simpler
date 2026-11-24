"""Model import (FBX, glTF/GLB, OBJ, USD) preserving the file's hierarchy."""
import os

import bpy

import tempfile

from . import fbx_legacy, progress, textures
from .core import CM, KIND_KEY, SOURCE_KEY, ApiError, ensure_id, find, link, log, refresh
from .i18n import tr

IMPORTERS = {
    ".fbx": lambda p: bpy.ops.import_scene.fbx(filepath=p, use_custom_normals=True, use_image_search=True),
    ".glb": lambda p: bpy.ops.import_scene.gltf(filepath=p),
    ".gltf": lambda p: bpy.ops.import_scene.gltf(filepath=p),
    ".obj": lambda p: bpy.ops.wm.obj_import(filepath=p),
    ".usd": lambda p: bpy.ops.wm.usd_import(filepath=p),
    ".usda": lambda p: bpy.ops.wm.usd_import(filepath=p),
    ".usdc": lambda p: bpy.ops.wm.usd_import(filepath=p),
    ".usdz": lambda p: bpy.ops.wm.usd_import(filepath=p),
}


def supported_formats():
    return sorted(IMPORTERS)


def import_model(path, parent_id="", texture_folders=None, merge=False, location=None, offset=None, scale=1.0):
    progress.begin("import", tr("Lettura del file {0}", os.path.basename(path or "")))
    try:
        return _import_model(path, parent_id, texture_folders or [], merge, location, offset, scale)
    finally:
        progress.end()


def _freeze_pose(obs):
    """(1.80.38) An animated model (a skeleton with its clips, keyframes on its pieces): Cycles drew the pose of the clip
    at the scene's frame, the real-time view the rest pose of the skeleton - a diver swimming in the path tracing and
    standing in the view (Luca, 24/11). Simpler makes still images: the pose of the first frame is made the shape of
    the pieces (as both views then draw it) and the clips are taken away (no motion blur from them either).
    -> how many pieces had their pose fixed (0: nothing animated)."""
    skinned = [o for o in obs if o.type == "MESH" and any(m.type == "ARMATURE" for m in o.modifiers)]
    animated = [o for o in obs if o.animation_data and (o.animation_data.action or o.animation_data.nla_tracks)]
    keyed = [o for o in obs if o.type == "MESH" and o.data and o.data.shape_keys and o.data.shape_keys.animation_data]
    if not (skinned or animated or keyed):
        return 0
    view_layer = bpy.context.view_layer
    view_layer.update()
    dg = bpy.context.evaluated_depsgraph_get()
    world = {o: o.matrix_world.copy() for o in obs}
    done = 0
    for o in skinned + [k for k in keyed if k not in skinned]:
        try:
            e = o.evaluated_get(dg)
            me = bpy.data.meshes.new_from_object(e, preserve_all_data_layers=True, depsgraph=dg)
            old = o.data
            me.name = old.name
            o.modifiers.clear()
            o.data = me
            if old.users == 0:
                bpy.data.meshes.remove(old)
            done += 1
        except Exception as exc:  # noqa: BLE001
            log("SIMPLER_IMPORT", "pose not fixed on", o.name, exc)
    clips = set()
    for o in obs:
        if o.animation_data:
            if o.animation_data.action:
                clips.add(o.animation_data.action)
            for t in o.animation_data.nla_tracks:
                clips.update(st.action for st in t.strips if st.action)
    for o in obs:
        if o.animation_data:
            o.animation_data.action = None
            for t in list(o.animation_data.nla_tracks):
                o.animation_data.nla_tracks.remove(t)
        if o.type == "MESH" and o.data and o.data.shape_keys and o.data.shape_keys.animation_data:
            o.data.shape_keys.animation_data.action = None
    # (keyframes on the pieces themselves: each stays where the first frame had it)
    def depth(o):
        d = 0
        while o.parent is not None:
            o, d = o.parent, d + 1
        return d
    for o in sorted(obs, key=depth):
        o.matrix_world = world[o]
    view_layer.update()
    # (the clips of the file, no longer used by anything: not kept in the project nor sent to the view)
    for act in clips:
        act.use_fake_user = False
        if act.users == 0:
            bpy.data.actions.remove(act)
    log("SIMPLER_IMPORT", f"animated model: pose of the first frame kept on {done} pieces, {len(animated)} clips removed")
    return max(done, len(animated))


def _import_model(path, parent_id, texture_folders, merge=False, location=None, offset=None, scale=1.0):
    if not path or not os.path.isfile(path):
        raise ApiError(tr("File non trovato: {0}", path))
    try:
        f = float(scale if scale is not None else 1.0)
    except (TypeError, ValueError):
        f = float("nan")
    if not (1e-4 <= f <= 1e4):
        raise ApiError(tr("Fattore di scala non valido"))
    ext = os.path.splitext(path)[1].lower()
    if ext not in IMPORTERS:
        raise ApiError(tr("Formato non supportato: {0} (supportati: {1})", ext, ', '.join(supported_formats())))
    parent = find(parent_id) if parent_id else None

    before_obs = set(bpy.data.objects)
    before_mats = set(bpy.data.materials)
    before_imgs = set(bpy.data.images)

    if ext == ".fbx":
        # every FBX road (binary, text, pre-2011 6.x) lives in fbx_legacy.import_fbx, with readable errors
        fbx_legacy.import_fbx(path, progress.update)
    else:
        try:
            result = IMPORTERS[ext](path)
        except Exception as exc:
            raise ApiError(tr("Import non riuscito: {0}", fbx_legacy._short(exc))) from exc
        if "FINISHED" not in result:
            raise ApiError(tr("Import non riuscito"))

    progress.update(tr("Organizzazione della gerarchia"), 0.05)
    new_obs = [o for o in bpy.data.objects if o not in before_obs]
    posed = _freeze_pose(new_obs)
    if merge:
        # «Unisci in un solo oggetto»: one mesh with all the materials instead of the tree of pieces (merge.py)
        from . import merge as _merge
        progress.update(tr("Unione dei pezzi"), 0.04)
        new_obs = _merge.merge_objects(new_obs, os.path.splitext(os.path.basename(path))[0])
    new_set = set(new_obs)

    # Root group named after the file, at the origin.
    root = link(bpy.data.objects.new(os.path.basename(path), None))
    root[KIND_KEY] = "file"
    root[SOURCE_KEY] = path
    root.empty_display_size = 0.2
    if parent:
        root.parent = parent

    counts = {"nodes": 0, "meshes": 0, "lights": 0, "cameras": 0}
    for ob in new_obs:
        ensure_id(ob)
        ob.rotation_mode = "XYZ"
        ob[SOURCE_KEY] = path
        counts["nodes"] += 1
        if ob.type == "MESH":
            counts["meshes"] += 1
        elif ob.type == "LIGHT":
            counts["lights"] += 1
            ob.data.cycles.is_caustics_light = False
        elif ob.type == "CAMERA":
            counts["cameras"] += 1
        if ob.parent is None or ob.parent not in new_set:
            world = ob.matrix_world.copy()
            ob.parent = root
            ob.matrix_parent_inverse.identity()
            ob.matrix_world = world
    # (1.80.39, Luca: «già in importazione si può importare corretto») the size chosen in the import dialog: the
    # whole model scaled from the origin of the file (several files with the same factor stay aligned)
    if abs(f - 1.0) > 1e-9:
        root.scale = (f, f, f)
        refresh()

    new_mats = [m for m in bpy.data.materials if m not in before_mats]
    new_imgs = [i for i in bpy.data.images if i not in before_imgs]
    # textures: look for the missing ones next to the model; unplug those still missing (no magenta)
    folders = [(f, 6) for f in texture_folders if f] + textures.search_folders_for(path)
    found, missing = textures.resolve(new_imgs, folders, report_task=True)
    warnings = [tr("Texture non trovata: {0}", m) for m in missing]
    if posed:
        warnings.append(tr("Modello animato: tenuta la posa del primo fotogramma (le immagini sono ferme)"))

    # overall size (cm): files with wrong units show up immediately (a 1 cm glass, a 300 m chair)
    from mathutils import Vector
    lo, hi = Vector((1e30,) * 3), Vector((-1e30,) * 3)
    for o in new_obs:
        if o.type == "MESH":
            for corner in o.bound_box:
                w = o.matrix_world @ Vector(corner)
                lo = Vector(map(min, lo, w)); hi = Vector(map(max, hi, w))
    size_cm = [round((h - l) * 100, 2) for l, h in zip(lo, hi)] if hi.x >= lo.x else [0, 0, 0]

    # (1.75.48) where it goes: location (cm) = the point at the centre of the view, where the middle of the model's
    # base is put (as the models of the library); offset (cm) = the same shift as the file imported before it (several
    # files of one project stay aligned to each other). Neither: the coordinates of the file, as before.
    moved = None
    if location is not None and hi.x >= lo.x:
        base = Vector(((lo.x + hi.x) / 2, (lo.y + hi.y) / 2, lo.z))
        moved = Vector([float(v) for v in location]) * CM - base
    elif offset is not None:
        moved = Vector([float(v) for v in offset]) * CM
    if moved is not None and moved.length > 1e-6:
        mw = root.matrix_world.copy()
        mw.translation += moved
        root.matrix_world = mw
        refresh()

    # Shared meshes (instances) are kept shared: same memory for every copy.
    unique_meshes = {o.data for o in new_obs if o.type == "MESH"}
    return {
        "id": ensure_id(root),
        "nodes": counts["nodes"],
        "meshes": counts["meshes"],
        "uniqueMeshes": len(unique_meshes),
        "lights": counts["lights"],
        "cameras": counts["cameras"],
        "materials": len(new_mats),
        "textures": len(new_imgs),
        "warnings": warnings,
        "texturesFound": len(found),
        "sizeCm": size_cm,
        "offset": [round(v / CM, 4) for v in moved] if moved is not None else None,
        "missingTextures": missing,
        "emptyTextures": list(textures.LAST_EMPTY),
    }
