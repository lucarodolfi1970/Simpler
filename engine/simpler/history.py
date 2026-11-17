"""Undo / redo.

Two kinds of steps:
- "state": cheap snapshots of the objects a command touches (name, parent, world matrix, visibility, light
  settings). Used for transforms, visibility, renames, re-parenting and light edits.
- "objects": objects created or deleted by the command (import, add, duplicate, delete). Deleted objects wait in
  the trash (trash.py), so undo and redo just move them in or out of the scene: instant even on huge scenes.
- "env": the environment (id and strength) before the command.
- "view": the scene settings (camera, render settings, lights, visibility) before applying a saved scene.
- "material": the channels of the edited materials (matedit.py): instant, no copy of the scene.
- "file": a full copy of the scene saved to a temporary .blend. Used for texture relinking.
  Restoring reloads that file.
"""
import os
import shutil
import tempfile

import bpy

from .i18n import tr
from mathutils import Matrix

from .core import ID_KEY, ApiError, find, descendants, descendants_many, refresh, managed_objects
from . import trash
from . import tempdirs

MAX_STEPS = 60
MAX_FILE_STEPS = 12
LIGHT_PROPS = ("type", "energy", "color", "use_temperature", "temperature", "shadow_soft_size", "use_shadow",
               "spot_size", "spot_blend", "size", "size_y", "shape", "angle", "use_soft_falloff")

_dir = tempdirs.make("simpler_undo_")
_counter = 0
UNDO: list = []
REDO: list = []
_after_restore = []   # callbacks run after a file step is restored (render settings, device...)


def on_restore(fn):
    _after_restore.append(fn)
    return fn


# ---------------------------------------------------------------- state snapshots

def _object_state(ob):
    st = {
        "name": ob.name,
        "parent": ob.parent.get(ID_KEY, "") if ob.parent else "",
        "matrix": [list(row) for row in ob.matrix_world],
        "hide_render": ob.hide_render,
        "hide_viewport": ob.hide_viewport,
        "visible_glossy": ob.visible_glossy,
        "visible_camera": ob.visible_camera,
        "order": ob.get("simpler_order"),
        "dryk": [ob.get(k) for k in ("simpler_dry", "simpler_dry_snowok", "simpler_nosnow")],
        "noshelter": bool(ob.get("simpler_noshelter")),
        "nomantle": bool(ob.get("simpler_nomantle")),
        "snowdetail": ob.get("simpler_snow_detail") or "",
        "tone": ob.get("simpler_terrain_tone") or "",          # (1.76.14: «Colori dal terreno» on a terrain's group)
    }
    if ob.type == "MESH":
        st["materials"] = [[sl.link, sl.material.name if sl.material else ""] for sl in ob.material_slots]
    if ob.get("simpler_decal") is not None:
        st["decal"] = ob["simpler_decal"]
    st["pivot"] = list(ob["simpler_pivot"]) if ob.get("simpler_pivot") is not None else None
    if ob.type == "LIGHT":
        d = ob.data
        light = {}
        for p in LIGHT_PROPS:
            if hasattr(d, p):
                v = getattr(d, p)
                light[p] = list(v) if hasattr(v, "__len__") and not isinstance(v, str) else v
        light["@range"] = float(ob.get("simpler_light_range", 0.0))
        light["@gobo"] = str(ob.get("simpler_light_gobo", ""))
        # the switches (dusk.py): on, dusk, and the power kept aside while off
        light["@on"] = int(ob.get("simpler_on", 1))
        light["@dusk"] = int(ob.get("simpler_dusk", 0))
        light["@power"] = float(ob["simpler_power"]) if "simpler_power" in ob else None
        st["light"] = light
    return st


def _apply_state(ob, st):
    """Puts the object back as in st; True when its place changed (parent or matrix: the scene must be evaluated
    before its children are placed). Only what differs is written (each write makes the path tracing sync again)."""
    moved = False
    if ob.name != st["name"]:
        ob.name = st["name"]
    parent = find(st["parent"], required=False) if st["parent"] else None
    if ob.parent != parent:
        ob.parent = parent
        ob.matrix_parent_inverse.identity()
        moved = True
    m = Matrix(st["matrix"])
    cur = ob.matrix_world
    if moved or any(abs(cur[r][c] - m[r][c]) > 1e-7 for r in range(4) for c in range(4)):
        ob.matrix_world = m
        moved = True
    for k in ("hide_render", "hide_viewport", "visible_glossy", "visible_camera"):
        if k in st and getattr(ob, k) != st[k]:
            setattr(ob, k, st[k])
    if "dryk" in st:                     # «Sempre asciutto»: no rain, no snow (rain.set_dry_state)
        keys = ("simpler_dry", "simpler_dry_snowok", "simpler_nosnow")
        before = [ob.get(k) for k in keys]
        for k, v in zip(keys, st["dryk"]):
            if v:
                ob[k] = v
            elif k in ob:
                del ob[k]
        if [ob.get(k) for k in keys] != before:
            ob.update_tag(refresh={"OBJECT"})   # (read by the materials: Cycles must sync the object again)
    elif "dry" in st:                    # (a step of undo from before 1.67.1)
        if st["dry"]:
            ob["simpler_dry"] = 1.0
        elif "simpler_dry" in ob:
            del ob["simpler_dry"]
    if "snowdetail" in st:               # «Dettaglio neve» (snow.py)
        if st["snowdetail"]:
            ob["simpler_snow_detail"] = st["snowdetail"]
        elif "simpler_snow_detail" in ob:
            del ob["simpler_snow_detail"]
    if "tone" in st:                     # «Colori dal terreno» (terrain.py)
        if st["tone"]:
            ob["simpler_terrain_tone"] = st["tone"]
        elif "simpler_terrain_tone" in ob:
            del ob["simpler_terrain_tone"]
    if "nomantle" in st:                 # «Senza mantello» (snow.py)
        if st["nomantle"]:
            ob["simpler_nomantle"] = 1
        elif "simpler_nomantle" in ob:
            del ob["simpler_nomantle"]
    if "noshelter" in st:                # «Non fa riparo» (rain.py)
        if st["noshelter"]:
            ob["simpler_noshelter"] = 1
        elif "simpler_noshelter" in ob:
            del ob["simpler_noshelter"]
    if st.get("order") is None:
        if "simpler_order" in ob:
            del ob["simpler_order"]
    else:
        ob["simpler_order"] = st["order"]
    if "materials" in st and ob.type == "MESH":
        for sl, (link, name) in zip(ob.material_slots, st["materials"]):
            if sl.link != link:
                sl.link = link
            if (sl.material.name if sl.material else "") != name:
                sl.material = bpy.data.materials.get(name) if name else None
        for sl in list(ob.material_slots)[len(st["materials"]):]:
            if sl.material is not None:
                sl.material = None
    if "decal" in st:
        # (also when only the place changed: the piece it is projected on is its parent)
        ob["simpler_decal"] = st["decal"]
        from . import decals
        decals.apply(ob)
    if "pivot" in st:
        if st["pivot"] is None:
            if "simpler_pivot" in ob:
                del ob["simpler_pivot"]
        else:
            ob["simpler_pivot"] = st["pivot"]
    if "light" in st and ob.type == "LIGHT":
        light = st["light"]
        if "type" in light and ob.data.type != light["type"]:
            ob.data.type = light["type"]
        d = ob.data
        for p, v in light.items():
            if p != "type" and hasattr(d, p):
                try:
                    setattr(d, p, v)
                except (TypeError, AttributeError, ValueError):
                    pass
        if "@range" in light:
            ob["simpler_light_range"] = light["@range"]
            ob["simpler_light_gobo"] = light["@gobo"]
            from .scene_ops import _light_nodes
            _light_nodes(ob)
        if "@on" in light:
            ob["simpler_on"] = light["@on"]
            ob["simpler_dusk"] = light["@dusk"]
            if light.get("@power") is not None:
                ob["simpler_power"] = light["@power"]
            elif "simpler_power" in ob:
                del ob["simpler_power"]
            from . import dusk
            dusk.apply_lamp(ob)          # (the time of day may have changed since)
    return moved


def _capture(ids):
    refresh()
    out = {}
    for i in ids:
        ob = find(i, required=False)
        if ob is not None:
            out[i] = _object_state(ob)
    return out


# ---------------------------------------------------------------- file snapshots

def _save_file():
    global _counter
    _counter += 1
    path = os.path.join(_dir, f"step_{_counter:05d}.blend")
    # snapshots live in a temp folder: relative texture paths would break when one is reloaded
    try:
        bpy.ops.file.make_paths_absolute()
    except RuntimeError:
        pass
    from . import snow
    with snow.aside():          # (the mantle of snow is made again after a restore: not in every snapshot)
        bpy.ops.wm.save_as_mainfile(filepath=path, copy=True, compress=False, relative_remap=False, check_existing=False)
    return path


def _load_file(path):
    bpy.ops.wm.open_mainfile(filepath=path, load_ui=False)
    for fn in _after_restore:
        fn()


def _trim():
    while len(UNDO) > MAX_STEPS:
        _drop(UNDO.pop(0))
    files = [s for s in UNDO if s["kind"] == "file"]
    while len(files) > MAX_FILE_STEPS:
        old = files.pop(0)
        UNDO.remove(old)
        _drop(old)


def _drop(step):
    if step["kind"] == "objects":
        # in the undo list its deleted objects wait in the trash; in the redo list, the objects it had created
        trash.purge_ids(step["added"] if step.get("undone") else step["removed"])
        return
    if step["kind"] == "meshes":
        from . import decimate
        decimate.drop_meshes(step["pairs"], step.get("undone", False))
        if step.get("undone"):
            trash.purge_ids(step.get("added") or [])
        else:
            trash.purge_ids(step.get("removed") or [])
        return
    if step["kind"] == "file":
        try:
            os.remove(step["path"])
        except OSError:
            pass


def _clear(stack):
    for s in stack:
        _drop(s)
    stack.clear()


# ---------------------------------------------------------------- public API

def begin(kind, label, ids=None):
    """Called before a command runs. Returns a token for commit()/cancel()."""
    if kind in ("state", "deep"):
        ids = _with_descendants(ids or [])
        if kind == "deep":
            ids = list(dict.fromkeys(ids + [d.get(ID_KEY) for d in descendants_many([find(i, required=False) for i in ids])
                                            if d.get(ID_KEY)]))
        return {"kind": "state", "label": label, "objects": _capture(ids)}
    _PARENTS.clear()
    _HIDDEN.clear()
    if kind == "objects":
        return {"kind": "objects", "label": label, "before": _scene_ids(), "added": [], "removed": []}
    if kind == "allobjects":
        # (like objects, also with the objects that are not in the scene: the models of the distributions)
        from .core import ensure_id
        from . import paint
        for o in paint.scatter_originals():
            ensure_id(o)
        return {"kind": "objects", "label": label, "before": _all_ids(), "added": [], "removed": [], "all": True}
    if kind == "env":
        return {"kind": "env", "label": label, "env": _env_state()}
    if kind == "ambience":
        from . import ambience
        return {"kind": "ambience", "label": label, "ambience": ambience.state(), "env": _env_state()}
    if kind == "ocean":
        from . import ocean
        return {"kind": "ocean", "label": label, "ocean": ocean.snapshot()}
    if kind == "view":
        from . import views
        return {"kind": "view", "label": label, "view": views.current_snapshot()}
    if kind == "material":
        from . import matedit
        return {"kind": "material", "label": label, "snap": matedit.snapshot(ids or [])}
    if kind == "normals":
        return {"kind": "normals", "label": label, "flipped": {}}
    if kind == "rainpaint":
        from . import rain
        return {"kind": "rainpaint", "label": label, "snap": rain.paint_snapshot()}
    if kind == "meshes":
        from . import decimate
        decimate.ADDED.clear()
        decimate.REMOVED.clear()
        return {"kind": "meshes", "label": label, "pairs": [], "added": [], "removed": []}
    if kind == "dirtpaint":
        from . import dirtpaint
        return {"kind": "dirtpaint", "label": label, "snap": dirtpaint.snapshot()}
    return {"kind": "file", "label": label, "path": _save_file()}


def _scene_ids():
    return {ob.get(ID_KEY) for ob in managed_objects() if ob.get(ID_KEY)}


_PARENTS = []          # objects that a command of kind objects moved under another object (note_parent)
_HIDDEN = []           # (1.76.31) objects that a command of kind objects hid (note_hidden: the bench of an ecosystem)


def note_hidden(ids):
    """An objects step that also hides objects (the bench of an ecosystem hides the rest): undo shows them again."""
    _HIDDEN.extend(ids)


def _hide(ids, hidden):
    from . import scene_ops
    for i in ids:
        if find(i, required=False) is not None:
            scene_ops.set_visible(i, not hidden)


def note_parent(child_id, before_id, after_id):
    """An objects step that also moves an object from one parent to another (an object the user put under a model
    that «Aggiorna dalla libreria» replaced): undo puts it back under the old one."""
    _PARENTS.append([child_id, before_id, after_id])


def _reparent(moves, undoing):
    refresh()
    for child_id, before_id, after_id in moves:
        ob = find(child_id, required=False)
        par = find(before_id if undoing else after_id, required=False)
        if ob is None or par is None:
            continue
        w = ob.matrix_world.copy()
        ob.parent = par
        ob.matrix_parent_inverse.identity()
        ob.matrix_world = w
    refresh()


def _all_ids():
    return {ob.get(ID_KEY) for ob in bpy.data.objects if ob.get(ID_KEY) and not ob.get("simpler_trashed")}


def _env_state():
    w = bpy.context.scene.world
    return {"id": w.get("simpler_env", "studio_morbido") if w else "studio_morbido",
            "strength": float(w.get("simpler_env_strength", 1.0)) if w else 1.0}


def commit(step):
    if step["kind"] == "objects":
        after = _all_ids() if step.get("all") else _scene_ids()
        if _PARENTS:
            step["parents"] = list(_PARENTS)
            _PARENTS.clear()
        if _HIDDEN:
            step["hidden"] = list(_HIDDEN)
            _HIDDEN.clear()
        step["added"] = sorted(after - step["before"])
        step["removed"] = sorted(step["before"] - after)
        del step["before"]
        if not step["added"] and not step["removed"] and not step.get("hidden"):
            return
    if step["kind"] == "normals" and not step["flipped"]:
        return
    if step["kind"] == "meshes":
        from . import decimate
        step["pairs"] = [list(p) for p in decimate.SWAPS]
        step["added"] = list(decimate.ADDED)
        step["removed"] = list(decimate.REMOVED)
        decimate.SWAPS.clear()
        decimate.ADDED.clear()
        decimate.REMOVED.clear()
        if not step["pairs"]:
            return
    UNDO.append(step)
    _clear(REDO)
    _trim()


def cancel(step):
    _drop(step)


def reset():
    _clear(UNDO)
    _clear(REDO)


def _with_descendants(ids):
    # only the objects themselves: children follow their parent's matrix automatically
    return list(dict.fromkeys(i for i in ids if i))


def _swap(src, dst):
    if not src:
        raise ApiError(tr("Niente da annullare") if src is UNDO else tr("Niente da ripetere"))
    step = src.pop()
    # (1.79.0, Luca: «i passi sono scomparsi») which step went back or forward: in engine.log, to find what undid what
    from .core import log
    log("SIMPLER_UNDO", "undo" if src is UNDO else "redo", step["kind"], step.get("label", ""))
    if step["kind"] == "state":
        back = {"kind": "state", "label": step["label"], "objects": _capture(step["objects"].keys())}
        levels = {}
        for i in step["objects"]:
            ob = find(i, required=False)
            if ob is None:
                continue
            n, p = 0, ob.parent
            while p is not None:
                n += 1
                p = p.parent
            levels.setdefault(n, []).append((ob, step["objects"][i]))
        refresh()
        # parents first, each level seeing the updated parents. The scene is evaluated again only after a level where
        # something moved (1.70.3: once per object before - the undo of «Sempre asciutto» on a model of 4,300 pieces
        # evaluated the whole scene 4,300 times and took minutes; only flags had changed)
        for n in sorted(levels):
            moved = False
            for ob, st in levels[n]:
                moved = _apply_state(ob, st) or moved
            if moved:
                refresh()
        dst.append(back)
    elif step["kind"] == "objects":
        undoing = src is UNDO
        if undoing:
            trash.trash_ids(step["added"])
            trash.restore_ids(step["removed"])
        else:
            trash.trash_ids(step["removed"])
            trash.restore_ids(step["added"])
        if step.get("parents"):
            _reparent(step["parents"], undoing)
        if step.get("hidden"):
            _hide(step["hidden"], not undoing)
        step["undone"] = undoing
        refresh()
        dst.append(step)
    elif step["kind"] == "env":
        from . import scene_ops
        back = {"kind": "env", "label": step["label"], "env": _env_state()}
        scene_ops.set_environment(step["env"]["id"], step["env"]["strength"])
        dst.append(back)
    elif step["kind"] == "ambience":
        from . import ambience, scene_ops
        back = {"kind": "ambience", "label": step["label"], "ambience": ambience.state(), "env": _env_state()}
        if step["ambience"]:
            ambience.apply(step["ambience"])
        else:
            scene_ops.set_environment(step["env"]["id"], step["env"]["strength"])
        dst.append(back)
    elif step["kind"] == "ocean":
        from . import ocean
        back = {"kind": "ocean", "label": step["label"], "ocean": ocean.snapshot()}
        ocean.restore(step["ocean"])
        dst.append(back)
    elif step["kind"] == "material":
        from . import matedit
        back = {"kind": "material", "label": step["label"], "snap": matedit.snapshot(list(step["snap"].keys()))}
        matedit.restore(step["snap"])
        dst.append(back)
    elif step["kind"] == "normals":
        from . import scene_ops
        scene_ops.flip_faces(step["flipped"])      # (turning the same faces again is its own undo)
        dst.append(step)
    elif step["kind"] == "meshes":
        from . import decimate
        undoing = src is UNDO
        step["geometry"] = decimate.swap_meshes(step["pairs"], undoing)
        if step.get("added") or step.get("removed"):
            # (1.76.8: objects the command made - the new parts of «Dividi zona» - out of the scene and back;
            # 1.76.15: the layers of the ecosystems made again on the new shape, and the old ones back)
            if undoing:
                trash.trash_ids(step.get("added") or [])
                trash.restore_ids(step.get("removed") or [])
            else:
                trash.trash_ids(step.get("removed") or [])
                trash.restore_ids(step.get("added") or [])
            refresh()
        step["undone"] = undoing
        dst.append(step)
    elif step["kind"] == "selection":
        dst.append(step)                           # (nothing to restore in the scene: the app selects)
    elif step["kind"] == "dirtpaint":
        from . import dirtpaint
        back = {"kind": "dirtpaint", "label": step["label"], "snap": dirtpaint.snapshot()}
        dirtpaint.restore(step["snap"])
        dst.append(back)
    elif step["kind"] == "rainpaint":
        from . import rain
        back = {"kind": "rainpaint", "label": step["label"], "snap": rain.paint_snapshot()}
        rain.paint_restore(step["snap"])
        dst.append(back)
    elif step["kind"] == "view":
        from . import views
        back = {"kind": "view", "label": step["label"], "view": views.current_snapshot()}
        views.apply_snapshot(step["view"])
        dst.append(back)
    else:
        back = {"kind": "file", "label": step["label"], "path": _save_file()}
        _load_file(step["path"])
        _drop(step)
        dst.append(back)
    out = {"label": step["label"], "structural": step["kind"] in ("file", "objects", "meshes"), "kind": step["kind"], **status()}
    if step["kind"] == "material":
        out["materials"] = list(step["snap"].keys())     # (the app draws them again in the real-time view)
    if step["kind"] == "meshes":
        out["geometry"] = step.pop("geometry", [])      # (the app gives the view these objects again)
    if step["kind"] == "selection":
        out["select"] = step["before"] if src is UNDO else step["after"]
    return out


def remember_selection(d):
    """POST selection/remember {before: {ids, primary}, after: {ids, primary}}: a selection of several objects lost
    (deselected, or replaced by another) becomes a step of the history, so Ctrl+Z brings it back. Nothing in the scene
    changes; the app selects again what the step returns."""
    def sel(x):
        x = x if isinstance(x, dict) else {}
        return {"ids": [str(i) for i in (x.get("ids") or [])], "primary": str(x.get("primary") or "")}
    step = {"kind": "selection", "label": tr("Selezione"), "before": sel(d.get("before")), "after": sel(d.get("after"))}
    UNDO.append(step)
    _clear(REDO)
    _trim()
    return status()


def undo(_data=None):
    return _swap(UNDO, REDO)


def redo(_data=None):
    return _swap(REDO, UNDO)


def status():
    return {
        "canUndo": bool(UNDO), "canRedo": bool(REDO),
        "undoLabel": UNDO[-1]["label"] if UNDO else "",
        "redoLabel": REDO[-1]["label"] if REDO else "",
    }


def cleanup():
    shutil.rmtree(_dir, ignore_errors=True)
