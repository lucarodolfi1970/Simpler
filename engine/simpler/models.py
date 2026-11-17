"""The user's model library: pieces of a scene saved to be reused in any project.

%APPDATA%\\Simpler\\models\\
    folders.json                 {"folders": [paths]} - the folder tree (empty folders too)
    <id>.json                    {id, name, folder, rev, sizeCm, created}
    <id>\\model.blend             the objects (with materials); textures copied into <id>\\textures, relative paths
    <id>\\thumb.png               path-traced thumbnail (axonometric view, studio lights, transparent background)

Saving is quick for the engine: it writes the objects to a temporary .blend and goes back to work; the preview process
(previews.py / preview_job.py) copies the textures next to the model, writes model.blend and renders the thumbnail.
"""
import json
import math
import os
import shutil
import time
import uuid

import bpy
from mathutils import Vector

from .core import claim_name, ID_KEY, INTERNAL_KEY, KIND_KEY, ApiError, find, link, log, new_id, refresh, tree_kids

MODEL_KEY = "simpler_paint_model"     # (as paint.MODEL_KEY: a piece of a library model placed in the scene)
from .i18n import tr

CM = 0.01

# a first set of folders (the user adds, renames and removes them like the material folders)
DEFAULT_FOLDERS = [
    "Alberi", "Piante e fiori", "Natura", "Natura/Rocce e pietre", "Natura/Tronchi e rami",
    "Edifici", "Elementi architettonici", "Elementi architettonici/Porte", "Elementi architettonici/Finestre",
    "Elementi architettonici/Scale", "Oggetti città", "Oggetti città/Panchine", "Oggetti città/Lampioni",
    "Oggetti città/Recinzioni", "Veicoli", "Persone", "Arredamento", "Arredamento/Sedute", "Arredamento/Tavoli",
    "Arredamento/Letti", "Arredamento/Contenitori", "Cucina", "Bagno", "Illuminazione", "Decorazioni", "Elettronica",
    "Giardino ed esterni", "Gioielli", "Altro",
]


def user_dir():
    from . import paths
    return paths.get("models")


# (15/11, Luca, first PC with Simpler in Italian: «in Modelli 3D ▸ I miei c'è Vegetation con 13 oggetti») the root of the
# plants has the name of the language («Vegetazione» / «Vegetation»), but the folders of the models are written in the
# files with the name of the language they were made in - the plants of the cloud and of the packs (made in English), the
# library of who changes the language. Read in the other language they were an ordinary folder of «I miei». The two
# names are the same root, shown in the language in use: every folder of a model passes here.
VEG_ROOT_NAMES = ("Vegetazione", "Vegetation")


def _clean(path):
    parts = [p.strip() for p in str(path or "").replace("\\", "/").split("/") if p.strip()]
    if parts and parts[0] in VEG_ROOT_NAMES:
        parts[0] = tr("Vegetazione")
    return "/".join(parts)


def _write_json(path, data):
    with open(path + ".part", "w", encoding="utf-8") as f:
        json.dump(data, f, indent=1)
    os.replace(path + ".part", path)


def _folders():
    path = os.path.join(user_dir(), "folders.json")
    if not os.path.isfile(path):
        # (15/11, Luca: «non possiamo sapere come l'utente vorrà organizzare i suoi modelli, non lo facciamo per materiali e
        # decal») a new library starts EMPTY: no folders made by Simpler (DEFAULT_FOLDERS stays only for the names
        # other parts know). The libraries that already have their folders.json are not touched
        d = {"folders": []}
        _write_json(path, d)
        return d
    try:
        with open(path, encoding="utf-8") as f:
            d = json.load(f)
    except (OSError, ValueError):
        d = {}
    d.setdefault("folders", [])
    return d


def _save_folders(d):
    d["folders"] = sorted(set(_clean(f) for f in d["folders"] if _clean(f)), key=str.lower)
    _write_json(os.path.join(user_dir(), "folders.json"), d)


def _entries():
    d = user_dir()
    out = {}
    for f in sorted(os.listdir(d)):
        if not f.endswith(".json") or f == "folders.json":
            continue
        try:
            with open(os.path.join(d, f), encoding="utf-8") as fh:
                e = json.load(fh)
            out[e["id"]] = e
        except (OSError, ValueError, KeyError):
            continue
    return out


_SIZES = {}          # id -> (rev, bytes): the size on disk of a model's folder, counted again when it changes


def _folder_bytes(e, d):
    key = (e.get("rev", ""), os.path.getmtime(d) if os.path.isdir(d) else 0)
    hit = _SIZES.get(e["id"])
    if hit and hit[0] == key:
        return hit[1]
    total = 0
    for root_, _dirs, files in os.walk(d):
        for f in files:
            try:
                total += os.path.getsize(os.path.join(root_, f))
            except OSError:
                pass
    _SIZES[e["id"]] = (key, total)
    return total


def _entry_json(e):
    d = os.path.join(user_dir(), e["id"])
    thumb = os.path.join(d, "thumb.png")
    if not any(e.get("sizeCm") or []) and os.path.isfile(os.path.join(d, "info.json")):
        try:
            with open(os.path.join(d, "info.json"), encoding="utf-8") as f:
                e = dict(e, sizeCm=json.load(f).get("sizeCm", [0, 0, 0]))
        except (OSError, ValueError):
            pass
    return {"id": e["id"], "name": e.get("name", e["id"]), "folder": _clean(e.get("folder")), "rev": e.get("rev", ""),
            "sizeCm": e.get("sizeCm", [0, 0, 0]), "thumb": thumb if os.path.isfile(thumb) else "", "source": e.get("source", ""),
            "ready": os.path.isfile(os.path.join(d, "model.blend")), "bytes": _folder_bytes(e, d),
            "veg": e.get("veg") or None}


def library_json(_data=None):
    entries = [_entry_json(e) for e in _entries().values()]
    entries.sort(key=lambda e: e["name"].lower())
    folders = set()
    for f in [_clean(x) for x in _folders()["folders"]] + [e["folder"] for e in entries]:
        parts = f.split("/") if f else []
        for k in range(1, len(parts) + 1):
            folders.add("/".join(parts[:k]))
    from .matbulk import veg_root
    return {"models": entries, "folders": sorted(folders, key=str.lower), "vegRoot": veg_root()}


# ---------------------------------------------------------------- folders, names

def folder_op(data):
    """POST models/folder {action: create|rename|delete, path, newPath, items}. Deleting moves the contents up; with
    «items» (1.78.4, Luca: «ho eliminato la cartella con i modelli dentro: è sparita ma i modelli ci sono tutti») the
    models inside it and in its subfolders are deleted too (as «Elimina» on each: models/delete), and its subfolders."""
    action = data.get("action")
    path = _clean(data.get("path"))
    if action == "delete" and data.get("items") and path:
        gone = 0
        for mid, e in list(_entries().items()):
            cur = _clean(e.get("folder"))
            if cur == path or cur.startswith(path + "/"):
                delete({"id": mid})
                gone += 1
        d = _folders()
        d["folders"] = [f for f in d["folders"] if not (f == path or f.startswith(path + "/"))]
        _save_folders(d)
        return {"path": "/".join(path.split("/")[:-1]), "deleted": gone}
    d = _folders()
    if action == "create":
        if not path:
            raise ApiError(tr("Nome vuoto"))
        d["folders"].append(path)
        _save_folders(d)
        return {"path": path}
    if not path:
        raise ApiError(tr("Cartella non valida"))
    parent = "/".join(path.split("/")[:-1])
    target = _clean(data.get("newPath")) if action == "rename" else parent
    if action == "rename" and not target:
        raise ApiError(tr("Nome vuoto"))
    if action == "rename" and (target + "/").startswith(path + "/"):
        raise ApiError(tr("Una cartella non può andare dentro sé stessa"))

    def moved(f):
        # (1.78.5, Luca: «se elimino un folder padre i figli devono essere eliminati») deleting takes the subfolders
        # with it: what they contain goes to the folder above the deleted one
        if action == "delete" and (f == path or f.startswith(path + "/")):
            return target
        if f == path:
            return target
        if f.startswith(path + "/"):
            return (target + "/" if target else "") + f[len(path) + 1:]
        return f
    d["folders"] = [moved(f) for f in d["folders"] if not (action == "delete" and (f == path or f.startswith(path + "/")))]
    if action == "rename":
        d["folders"].append(target)
    for mid, e in _entries().items():
        cur = _clean(e.get("folder"))
        if cur == path or cur.startswith(path + "/"):
            e["folder"] = moved(cur)
            _write_json(os.path.join(user_dir(), mid + ".json"), e)
    _save_folders(d)
    return {"path": target}


# (1.78.4) the «Simpler» parts of the library (Modelli 3D ▸ Simpler, Vegetazione ▸ Simpler): with the setting of the
# app «SimplerLocked» = 1 they are read only - nothing is imported, saved, moved, renamed, converted or deleted there,
# and nothing is moved out. The app sends the setting at the start (POST models/lock); 0 while the parts are being filled.
LOCK = {"on": False}


def lock_set(data):
    LOCK["on"] = bool(data.get("on"))
    return {"on": LOCK["on"]}


def _locked_folder(f):
    from .matbulk import veg_root
    f = (f or "").strip("/")
    roots = ("Simpler", veg_root() + "/Simpler", "Packages", veg_root() + "/Packages")     # (the packs: blue, as read only)
    return any(f == r or f.startswith(r + "/") for r in roots)


def _pack_folder(f):
    from .matbulk import veg_root
    f = (f or "").strip("/")
    return any(f == r or f.startswith(r + "/") for r in ("Packages", veg_root() + "/Packages"))


def is_locked(f):
    """(Luca: «c'è ancora delete folder») a folder that cannot be changed now: the packs always (only their installer
    writes there), the Simpler parts with the lock on."""
    return _pack_folder(f) or (LOCK["on"] and _locked_folder(f))


def _folder_of(mid):
    e = _entries().get(mid or "")
    return e.get("folder", "") if e else ""


# what each request changes: the folders it writes into and the models it changes
_LOCK_TARGETS = {
    "POST /api/models/save": lambda d: ([d.get("folder")], [d.get("replace")]),
    "POST /api/models/import": lambda d: ([d.get("folder")], [d.get("replace")]),
    "POST /api/models/rescale": lambda d: ([], [d.get("id")]),
    "POST /api/models/orient": lambda d: ([], [d.get("id")]),
    "POST /api/models/folder": lambda d: ([d.get("path"), d.get("newPath")], []),
    "POST /api/models/move": lambda d: ([d.get("folder")], [d.get("id")]),
    "POST /api/models/copy": lambda d: ([d.get("folder")], []),
    "POST /api/models/rename": lambda d: ([], [d.get("id")]),
    "POST /api/models/delete": lambda d: ([], [d.get("id")]),
    "POST /api/models/thumb": lambda d: ([], [d.get("id")]),
    "POST /api/models/vegetation": lambda d: ([], list(d.get("ids") or [])),
    "POST /api/matbulk/apply": lambda d: ([], [it.get("id") for it in d.get("items") or []]),
}


def _eco_locked(f):
    f = _clean(f)
    return f == "Simpler" or f.startswith("Simpler/")


def _eco_lock_check(key, d):
    """(Luca: «le cartelle rosse non consentono modifiche») the ecosystems of the folder «Simpler»: only used and copied."""
    if not LOCK["on"]:
        return
    name = key.rsplit("/", 1)[1]
    ro = tr("Le cartelle Simpler sono di sola lettura")
    if name in ("rename", "delete", "move", "thumb", "defaults"):
        from . import ecosystems
        try:
            cur = ecosystems._read(d.get("id")).get("folder")
        except ApiError:
            cur = ""
        if _eco_locked(cur):
            raise ApiError(ro)
    if name in ("move", "copy", "save", "saveown") and _eco_locked(d.get("folder")):
        raise ApiError(ro)
    if name == "folder":
        path = _clean(d.get("path"))
        act = d.get("action")
        if act == "create" and path == "Simpler":
            return                      # (the part always has its folder)
        if _eco_locked(path) or _eco_locked(d.get("newPath")) or (act in ("rename", "delete") and path == ""):
            raise ApiError(ro)


def lock_check(key, data):
    """Refuses a change of the locked Simpler parts (before the request runs)."""
    d = data or {}
    if key.startswith("POST /api/material/"):
        if not LOCK["on"]:
            return
        from . import materials
        if materials.locked_change(key, d):
            raise ApiError(tr("Le cartelle Simpler sono di sola lettura"))
        return
    if key.startswith("POST /api/ecosystems/"):
        _eco_lock_check(key, d)
        return
    if key not in _LOCK_TARGETS:
        return
    if key == "POST /api/models/folder":
        from .matbulk import veg_root
        path = _clean(d.get("path"))
        packs = tuple(r for r in ("Packages", veg_root() + "/Packages")          # (the packs: only when some are there)
                      if any(_clean(e.get("folder")).startswith(r + "/") or _clean(e.get("folder")) == r for e in _entries().values()))
        roots = (("Simpler", veg_root() + "/Simpler") if LOCK["on"] else ()) + packs
        if d.get("action") == "create" and (path in roots or path in ("Packages", veg_root() + "/Packages") or path == "Simpler/Primitives"):
            return                      # (the parts always have their folder)
        if d.get("action") in ("rename", "delete") and path and any(r.startswith(path + "/") for r in roots):
            raise ApiError(tr("Le cartelle Simpler sono di sola lettura"))      # (a folder that holds them)
    folders, ids = _LOCK_TARGETS[key](d)
    if any(f and is_locked(_clean(f)) for f in folders) or any(m and is_locked(_folder_of(m)) for m in ids):
        raise ApiError(tr("Le cartelle Simpler sono di sola lettura"))


def _entry(mid):
    e = _entries().get(mid or "")
    if e is None:
        raise ApiError(tr("Modello non trovato nella libreria"))
    return e


def move(data):
    """POST models/move {id, folder}."""
    e = _entry(data.get("id"))
    e["folder"] = _clean(data.get("folder"))
    if e["folder"]:
        d = _folders()
        d["folders"].append(e["folder"])
        _save_folders(d)
    _write_json(os.path.join(user_dir(), e["id"] + ".json"), e)
    return {"id": e["id"], "folder": e["folder"]}


def copy(data):
    """POST models/copy {id, folder}: a copy of the model in the library (its folder copied whole: model, textures,
    thumbnail), in that folder, with the same name. Returns the new id."""
    e = _entry(data.get("id"))
    src = os.path.join(user_dir(), e["id"])
    if not os.path.isdir(src):
        raise ApiError(tr("Modello non trovato"))
    if not os.path.isfile(os.path.join(src, "model.blend")):
        raise ApiError(tr("Il modello è ancora in preparazione: riprova tra poco"))
    mid = "m_" + uuid.uuid4().hex[:10]
    dst = os.path.join(user_dir(), mid)
    shutil.copytree(src, dst)
    new = dict(e, id=mid, folder=_clean(data.get("folder")), rev=str(int(time.time())), created=time.strftime("%Y-%m-%d %H:%M"))
    _write_json(os.path.join(user_dir(), mid + ".json"), new)
    if new["folder"]:
        d = _folders()
        d["folders"].append(new["folder"])
        _save_folders(d)
    return {"id": mid}


def rename(data):
    """POST models/rename {id, name}."""
    e = _entry(data.get("id"))
    name = (data.get("name") or "").strip()
    if not name:
        raise ApiError(tr("Nome vuoto"))
    e["name"] = name
    _write_json(os.path.join(user_dir(), e["id"] + ".json"), e)
    return {"id": e["id"], "name": name}


def delete(data):
    """POST models/delete {id}: the model leaves the library. Its textures stay where they are: the copies of the model
    already in a scene (this one, and saved projects) show them from this folder - deleting them turned those copies
    pink. The folder is no longer listed (no .json, no model.blend)."""
    e = _entry(data.get("id"))
    mdir = os.path.join(user_dir(), e["id"])
    if os.path.isdir(os.path.join(mdir, "textures")) and os.listdir(os.path.join(mdir, "textures")):
        for f in os.listdir(mdir):
            if f == "textures":
                continue
            p = os.path.join(mdir, f)
            try:
                shutil.rmtree(p) if os.path.isdir(p) else os.remove(p)
            except OSError:
                pass
    else:
        shutil.rmtree(mdir, ignore_errors=True)
    try:
        os.remove(os.path.join(user_dir(), e["id"] + ".json"))
    except OSError:
        pass
    return {"id": e["id"]}


# ---------------------------------------------------------------- saving

def _pieces(ids):
    """The objects to save: the given ones and everything under them (helpers, twins and deleted objects excluded),
    and the top ones (those whose parent is not saved)."""
    from . import twins
    obs = []
    roots = [find(i) for i in ids]
    kids = tree_kids(roots)                    # (Object.children per piece: seconds on big models)
    seen = set()
    for r in roots:
        stack = [r]
        while stack:
            ob = stack.pop()
            if ob in seen or ob.get(INTERNAL_KEY) or ob.get("simpler_trashed") or twins.is_twin(ob):
                continue
            seen.add(ob)
            obs.append(ob)
            stack.extend(kids.get(ob, ()))
    if not obs:
        raise ApiError(tr("Niente da salvare"))
    tops = [o for o in obs if o.parent not in seen]
    return obs, tops


def _bbox(obs):
    """(1.75.6) The box of what is drawn, with world matrices from the parents: a piece hidden in the render (the
    Qashqai's «Glass_Clear», in millimetres under a group scaled 0.001) is not updated by Blender's depsgraph - its
    stale matrix made it 4 km wide, and the car went in the scene a kilometre up."""
    lo, hi = Vector((1e30,) * 3), Vector((-1e30,) * 3)
    shown = [o for o in obs if o.type == "MESH" and not o.hide_render]
    for o in shown or [o for o in obs if o.type == "MESH"]:
        mw = _world_now(o)
        for corner in o.bound_box:
            w = mw @ Vector(corner)
            lo = Vector(map(min, lo, w))
            hi = Vector(map(max, hi, w))
    if hi.x < lo.x:
        for o in obs:
            p = o.matrix_world.translation
            lo = Vector(map(min, lo, p))
            hi = Vector(map(max, hi, p))
    return lo, hi


def save(data):
    """POST models/save {ids, name, folder, replace}: the objects (with their children, materials and textures) into the
    library. Returns {id, pending: preview request id} - the thumbnail and the copy of the textures follow."""
    from . import previews, proxies
    ids = data.get("ids") or ([data["id"]] if data.get("id") else [])
    if not ids:
        raise ApiError(tr("Seleziona un oggetto"))
    obs, tops = _pieces(ids)
    name = (data.get("name") or "").strip() or (tops[0].name if len(tops) == 1 else tr("Modello"))
    folder = _clean(data.get("folder"))
    refresh()
    lo, hi = _bbox(obs)
    old = _entries().get(data.get("replace") or "")
    mid = old["id"] if old else "m_" + uuid.uuid4().hex[:10]       # replace: the same library model, new content
    mdir = os.path.join(user_dir(), mid)
    if old:
        # the new content replaces the old one, but its textures stay: the model in the scene (and in other projects)
        # shows them from this very folder - deleting it first left the saved model without textures (all white)
        for f in ("model.blend", "thumb.png"):
            try:
                os.remove(os.path.join(mdir, f))
            except OSError:
                pass
    os.makedirs(mdir, exist_ok=True)
    # image nodes may show reduced copies (the views): the originals go with the model, put back by the preview process
    extra = set()
    mats = {s.material for o in obs for s in o.material_slots if s.material is not None}
    from . import refcaustics
    refcaustics.strip_materials(mats)          # (the light of the water in this scene does not go with the model)
    for m in mats:
        if m.node_tree is None:
            continue
        for node in m.node_tree.nodes:
            orig = node.get(proxies.NODE_ORIG)
            if orig and bpy.data.images.get(orig) is not None:
                extra.add(bpy.data.images[orig])
    # the hidden originals («Ripristina originale») go with the model: without them a model taken from the library
    # could not go back to its imported materials - or found the original of another model with the same name
    origs = {bpy.data.materials.get(str(m.get("simpler_mat_backup") or "")) for m in mats} - {None}
    missing = _rescue_textures(mats | origs, extra, os.path.join(mdir, "textures"))
    tmp = os.path.join(previews.work_dir(), mid + "_src.blend")
    bpy.data.libraries.write(tmp, set(obs) | extra | origs, fake_user=True, path_remap="ABSOLUTE", compress=False)
    entry = {"id": mid, "name": name, "folder": folder, "rev": str(int(time.time())), "version": 1,
             "sizeCm": [round((h - l) / CM, 2) for l, h in zip(lo, hi)], "created": time.strftime("%Y-%m-%d %H:%M"),
             "tops": [o.name for o in tops], "objects": [o.name for o in obs]}
    _write_json(os.path.join(user_dir(), mid + ".json"), entry)
    if folder:
        d = _folders()
        d["folders"].append(folder)
        _save_folders(d)
    rid = previews.enqueue_model(tmp, os.path.join(mdir, "model.blend"), os.path.join(mdir, "textures"),
                                 os.path.join(mdir, "thumb.png"), "model:" + mid, keep=[o.name for o in obs])
    return {"id": mid, "name": name, "pending": rid, "missing": missing}


def _rescue_textures(mats, extra, tex_dir):
    """Textures whose file is gone (e.g. a library model deleted before 1.13.35 while a copy was in the scene): the
    pixels still in memory, or the reduced copy of the views, are written next to the model being saved, and the
    image shows that file from now on. Returns the names of the ones that could not be saved (shown to the user)."""
    from . import proxies
    imgs = set(extra)
    for m in mats:
        if m.node_tree is None:
            continue
        for n in m.node_tree.nodes:
            if n.type in ("TEX_IMAGE", "TEX_ENVIRONMENT") and n.image is not None:
                if not any(o.is_linked for o in n.outputs):
                    continue                     # a texture node connected to nothing: not part of the look
                imgs.add(n.image)
                orig = n.get(proxies.NODE_ORIG)
                if orig and bpy.data.images.get(orig) is not None:
                    imgs.add(bpy.data.images[orig])
    missing = []
    for im in imgs:
        if im.packed_file is not None or im.source not in ("FILE", "TILED"):
            continue
        path = bpy.path.abspath(im.filepath)
        if os.path.isfile(path):
            continue
        if not os.path.basename(path.rstrip()) and not im.has_data:
            # an empty slot from the original file (3ds Max "Map #0": a map with no picture, the path is only a
            # folder): there was never a texture to save
            continue
        os.makedirs(tex_dir, exist_ok=True)
        dest = os.path.join(tex_dir, os.path.basename(path) or (im.name + ".png"))
        ok = False
        try:
            if im.has_data:
                base, ext = os.path.splitext(dest)
                if ext.lower() not in (".png", ".jpg", ".jpeg"):
                    dest = base + ".png"
                im.filepath_raw = dest
                im.file_format = "JPEG" if dest.lower().endswith((".jpg", ".jpeg")) else "PNG"
                im.save()
                ok = os.path.isfile(dest)
        except Exception as exc:
            print("SIMPLER_WARN rescue", im.name, exc, flush=True)
        if not ok:
            # the reduced copy of the views, still in the cache of this session
            with proxies._lock:
                ready = [v for (src, px), v in proxies.READY.items() if os.path.normcase(src) == os.path.normcase(path) and os.path.isfile(v)]
            if ready:
                import shutil as _sh
                best = max(ready, key=os.path.getsize)
                dest = os.path.splitext(dest)[0] + os.path.splitext(best)[1]
                _sh.copy2(best, dest)
                im.filepath = dest
                ok = True
        if not ok:
            missing.append(os.path.basename(path) or im.name)
    return missing


def _world(o):
    """World matrix of an object just read from a file (not in a scene yet: matrix_world is not computed)."""
    m = o.matrix_basis.copy()
    while o.parent is not None:
        m = o.parent.matrix_basis @ o.matrix_parent_inverse @ m
        o = o.parent
    return m


def _keep_names(e, names_in_file, parent_of):
    """Names of the saved objects (a parent of the saved pieces may have come along in the file)."""
    if e.get("objects"):
        return set(e["objects"])
    tops = set(e.get("tops") or [])
    if not tops:
        return set(names_in_file)
    keep = set()
    for n in names_in_file:
        p = n
        while p is not None:
            if p in tops:
                keep.add(n)
                break
            p = parent_of.get(p)
    return keep


def rethumb(data):
    """POST models/thumb {id}: the thumbnail again (and model.blend cleaned of anything that was not saved)."""
    from . import previews
    e = _entry(data.get("id"))
    mdir = os.path.join(user_dir(), e["id"])
    path = os.path.join(mdir, "model.blend")
    if not os.path.isfile(path):
        raise ApiError(tr("Il modello è ancora in preparazione: riprova tra qualche secondo"))
    rid = previews.enqueue_model(path, path, os.path.join(mdir, "textures"), os.path.join(mdir, "thumb.png"),
                                 "model:" + e["id"], keep=e.get("objects"), keep_source=True, keep_tops=e.get("tops"))
    e["rev"] = str(int(time.time()))
    _write_json(os.path.join(user_dir(), e["id"] + ".json"), e)
    return {"id": e["id"], "pending": rid}


IMPORT_FORMATS = (".fbx", ".glb", ".gltf", ".obj", ".usd", ".usda", ".usdc", ".usdz")


def import_file(data):
    """POST models/import {path, name, folder, replace, split, pivot, merge}: a model file straight into the library, imported by the
    preview process (textures found and copied, thumbnail). replace: id of a library model to overwrite.
    Returns {id, pending}."""
    from . import previews
    path = data.get("path") or ""
    if not os.path.isfile(path):
        raise ApiError(tr("File non trovato: {0}", path))
    if os.path.splitext(path)[1].lower() not in IMPORT_FORMATS:
        raise ApiError(tr("Formato non supportato: {0} (supportati: {1})", os.path.splitext(path)[1], ", ".join(IMPORT_FORMATS)))
    name = (data.get("name") or "").strip() or os.path.splitext(os.path.basename(path))[0]
    folder = _clean(data.get("folder"))
    old = _entries().get(data.get("replace") or "")
    mid = old["id"] if old else "m_" + uuid.uuid4().hex[:10]
    mdir = os.path.join(user_dir(), mid)
    if old:
        for f in ("model.blend", "thumb.png"):     # (the textures stay: copies in the scenes may show them)
            try:
                os.remove(os.path.join(mdir, f))
            except OSError:
                pass
    os.makedirs(mdir, exist_ok=True)
    entry = {"id": mid, "name": name, "folder": folder, "rev": str(int(time.time())), "version": 1, "sizeCm": [0, 0, 0],
             "created": time.strftime("%Y-%m-%d %H:%M"), "source": path}
    _write_json(os.path.join(user_dir(), mid + ".json"), entry)
    if folder:
        d = _folders()
        d["folders"].append(folder)
        _save_folders(d)
    split = bool(data.get("split"))
    pivot = data.get("pivot") if data.get("pivot") in ("base", "center") else "keep"
    rid = previews.enqueue_import(path, os.path.join(mdir, "model.blend"), os.path.join(mdir, "textures"),
                                  os.path.join(mdir, "thumb.png"), os.path.join(mdir, "info.json"), "import:" + mid,
                                  split=split, pivot=pivot, parts_dir=user_dir(), base_id=mid,
                                  entry={k: v for k, v in entry.items() if k not in ("id", "sizeCm", "rev")},
                                  scale=_factor(data.get("scale")), merge=bool(data.get("merge")))
    return {"id": mid, "name": name, "pending": rid, "split": split}


def probe(data):
    """POST models/probe {path}: the size of a model file before importing it (import wizard). Returns {sizeCm,
    objects} when known (measured once: kept until the file changes), else {pending: preview request id} -
    ask again when it is done."""
    from . import previews
    import hashlib
    path = data.get("path") or ""
    if not os.path.isfile(path):
        raise ApiError(tr("File non trovato: {0}", path))
    st = os.stat(path)
    h = hashlib.sha1(f"{os.path.abspath(path)}|{st.st_size}|{int(st.st_mtime)}".encode("utf-8", "replace")).hexdigest()[:16]
    out = os.path.join(previews.work_dir(), f"probe_{h}.json")
    if os.path.isfile(out):
        try:
            with open(out, encoding="utf-8") as f:
                return json.load(f)
        except (OSError, ValueError):
            pass
    return {"pending": previews.enqueue_probe(path, out, "probe:" + h)}


def _factor(v):
    try:
        f = float(v if v is not None else 1.0)
    except (TypeError, ValueError):
        raise ApiError(tr("Fattore di scala non valido"))
    if not (1e-4 <= f <= 1e4):
        raise ApiError(tr("Fattore di scala non valido"))
    return f


def rescale(data):
    """POST models/rescale {id, source, factor}: library models made bigger or smaller (the import wizard, after each
    model: wrong units in the file). id: one model; source: every model imported from that file (a collection).
    Returns {ids, pending: [preview request ids], sizes: {id: sizeCm}}."""
    from . import previews
    f = _factor(data.get("factor"))
    src = data.get("source") or ""
    entries = _entries()
    targets = [e for e in entries.values() if e["id"] == data.get("id") or (src and e.get("source") == src)]
    if not targets:
        raise ApiError(tr("Modello non trovato nella libreria"))
    pending, sizes = [], {}
    for e in targets:
        mdir = os.path.join(user_dir(), e["id"])
        path = os.path.join(mdir, "model.blend")
        if not os.path.isfile(path):
            continue
        size = _entry_json(e)["sizeCm"]
        e["sizeCm"] = [round(x * f, 2) for x in size]
        e["rev"] = str(int(time.time()))
        _write_json(os.path.join(user_dir(), e["id"] + ".json"), e)
        info = os.path.join(mdir, "info.json")
        if os.path.isfile(info):
            try:
                with open(info, encoding="utf-8") as fh:
                    inf = json.load(fh)
                inf["sizeCm"] = e["sizeCm"]
                _write_json(info, inf)
            except (OSError, ValueError):
                pass
        sizes[e["id"]] = e["sizeCm"]
        if abs(f - 1.0) > 1e-9:
            pending.append(previews.enqueue_model(path, path, os.path.join(mdir, "textures"), os.path.join(mdir, "thumb.png"),
                                                  "model:" + e["id"], keep=e.get("objects"), keep_source=True,
                                                  keep_tops=e.get("tops"), scale=f))
    return {"ids": [e["id"] for e in targets], "pending": pending, "sizes": sizes}


def orient(data):
    """POST models/orient {id, mode: auto | rot90 | rot180 | bake | abs | delta, q}: the library model turned so its front
    goes along the red X axis (auto: its long side on X), around the centre of its base. Every new insertion and
    every scatter then use it; copies already in scenes stay as they are. Returns {id, pending}."""
    from . import previews
    e = _entry(data.get("id"))
    mdir = os.path.join(user_dir(), e["id"])
    path = os.path.join(mdir, "model.blend")
    if not os.path.isfile(path):
        raise ApiError(tr("Il modello è ancora in preparazione: riprova tra qualche secondo"))
    mode = data.get("mode") or "auto"
    req = {"rot90": {"mode": "yaw", "deg": 90}, "rot180": {"mode": "yaw", "deg": 180}, "auto": {"mode": "auto"},
           "bake": {"mode": "bake"}}.get(mode)
    if req is None and mode in ("abs", "delta") and isinstance(data.get("q"), list) and len(data["q"]) == 4:
        req = {"mode": mode, "q": [float(v) for v in data["q"]]}
    if req is None:
        raise ApiError(tr("Orientamento non valido"))
    e["rev"] = str(int(time.time()))
    e["sizeCm"] = [0, 0, 0]                 # (written by the preview process with the new orientation: info.json)
    _write_json(os.path.join(user_dir(), e["id"] + ".json"), e)
    rid = previews.enqueue_model(path, path, os.path.join(mdir, "textures"), os.path.join(mdir, "thumb.png"),
                                 "model:" + e["id"], keep=e.get("objects"), keep_source=True, keep_tops=e.get("tops"),
                                 orient=req, info=os.path.join(mdir, "info.json"))
    return {"id": e["id"], "pending": rid}


def orient_from_scene(data):
    """POST models/orientfromscene {object}: the library model gets the rotation its copy has in the scene (turned
    with the gizmo: any angle, on any axis)."""
    ob = find(data.get("object"))
    while ob.parent is not None and ob.parent.get(MODEL_KEY) == ob.get(MODEL_KEY):
        ob = ob.parent
    mid = ob.get(MODEL_KEY)
    if not mid:
        raise ApiError(tr("Non è un modello della libreria"))
    e = _entry(mid)
    q = ob.matrix_world.to_quaternion()
    one = len(e.get("tops") or []) == 1
    return orient({"id": mid, "mode": "abs" if one else "delta", "q": [q.w, q.x, q.y, q.z]})


def _world_now(o):
    """World matrix from the parents (objects outside the scene - the models of distributions - are not updated by
    Blender: their matrix_world is the one of when they were last in the scene)."""
    m = o.matrix_basis.copy()
    if o.parent is not None:
        m = _world_now(o.parent) @ o.matrix_parent_inverse @ m
    return m


def _bbox_now(obs):
    lo, hi = Vector((1e30,) * 3), Vector((-1e30,) * 3)
    for o in obs:
        if o.type not in ("MESH", "CURVE", "SURFACE", "META", "FONT") or o.data is None:
            continue
        w = _world_now(o)
        for c in o.bound_box:
            p = w @ Vector(c)
            lo = Vector(map(min, lo, p)); hi = Vector(map(max, hi, p))
    return lo, hi


def _library_rots(mid):
    """{top name: rotation (w, x, y, z)} of the model as the library has it now (its file, read once per revision:
    kept in info.json)."""
    import json as _json
    e = _entries().get(mid)
    if e is None:
        return {}
    mdir = os.path.join(user_dir(), mid)
    info_path = os.path.join(mdir, "info.json")
    inf = {}
    try:
        with open(info_path, encoding="utf-8") as fh:
            inf = _json.load(fh)
    except (OSError, ValueError):
        pass
    cached = inf.get("rootRot")
    if isinstance(cached, dict) and cached.get("rev") == e.get("rev") and isinstance(cached.get("rots"), dict):
        return cached["rots"]
    path = os.path.join(mdir, "model.blend")
    if not os.path.isfile(path):
        return {}
    rots = {}
    before = set(bpy.data.libraries)
    # (read from a copy with a name of its own: Blender keeps a file it has read in memory, so the same path read
    # again after the model was turned gave the old turn)
    import tempfile
    tmp = os.path.join(tempfile.gettempdir(), f"simpler_rot_{uuid.uuid4().hex[:10]}.blend")
    shutil.copyfile(path, tmp)
    try:
        with bpy.data.libraries.load(tmp, link=True) as (src, dst):
            names = list(src.objects)
            dst.objects = names
        for o in dst.objects:
            if o is not None and o.parent is None:
                q = o.matrix_basis.to_quaternion().normalized()
                rots[o.name] = [q.w, q.x, q.y, q.z]
    finally:
        for lib in set(bpy.data.libraries) - before:
            bpy.data.libraries.remove(lib)
        try:
            os.remove(tmp)
        except OSError:
            pass
    tops = e.get("tops") or []
    if tops:
        rots = {k: v for k, v in rots.items() if k in tops} or rots
    inf["rootRot"] = {"rev": e.get("rev"), "rots": rots}
    try:
        _write_json(info_path, inf)
    except OSError:
        pass
    return rots


def _stem(name):
    import re
    return re.sub(r"\.\d{3}$", "", name)


def sync_orientation(mid=None):
    """The models of the distributions of this project turned exactly as the library has them now (absolute, not by
    adding turns): a model turned in the library while another project was open, or turned twice, left the
    distributions of this project with an old orientation - after opening it a car faced backwards again, and
    turning it once more only moved the error. Their pieces follow. Returns [(model, collection, degrees)]."""
    from mathutils import Matrix, Quaternion, Vector
    from . import paint
    fixed = []
    lib = {}
    for c in bpy.data.collections:
        if not c.get(paint.SCATTER_TAG):
            continue
        for sub in c.children:
            m = sub.get(MODEL_KEY)
            if not m or (mid and m != mid) or not len(sub.objects):
                continue
            if m not in lib:
                lib[m] = _library_rots(m)
            rots = lib[m]
            if not rots:
                continue
            roots = [o for o in sub.objects if o.parent is None or o.parent.name not in sub.objects]
            if not roots:
                continue
            # the top of the model that the library file has: the root itself (one object, renamed after the model)
            # or one of the objects under the group made for a model of several objects
            cands = roots + [c for o in roots for c in o.children]
            ref = next((o for o in cands if _stem(o.name) in rots), None)
            want = rots.get(_stem(ref.name)) if ref is not None else None
            if ref is None and len(rots) == 1 and len(roots) == 1:
                ref, want = roots[0], next(iter(rots.values()))
            if want is None:
                continue
            cur = _world_now(ref).to_quaternion().normalized()
            r = (Quaternion(want).normalized() @ cur.inverted()).normalized()
            deg = math.degrees(r.angle) if r.angle <= math.pi else 360.0 - math.degrees(r.angle)
            if abs(deg) < 1.0:
                continue
            R = r.to_matrix().to_4x4()
            for o in roots:
                o.matrix_basis = R @ _world_now(o)
                o.parent = None
            lo, hi = _bbox_now(list(sub.objects))
            base = Vector(((lo.x + hi.x) / 2, (lo.y + hi.y) / 2, lo.z))
            pv = roots[0].get("simpler_pivot") if len(roots) == 1 else None
            if pv is not None and len(pv) == 3:
                base = roots[0].matrix_basis @ Vector([float(v) for v in pv])    # (1.78.4: the pivot chosen by hand)
            for o in roots:
                o.matrix_basis = Matrix.Translation(-base) @ o.matrix_basis
                o["simpler_paint_rest"] = [o.matrix_basis[i][j] for i in range(4) for j in range(4)]
                o["simpler_paint_base"] = list(o.matrix_basis.inverted() @ Vector((0.0, 0.0, 0.0)))
            fixed.append((m, sub.name, round(deg, 1)))
    if fixed:
        refresh()
    return fixed


def orient_scatters(data):
    """POST models/orient/apply {id}: after models/orient, the models of the distributions of this project turn as
    the library has them now (sync_orientation)."""
    return {"turned": len(sync_orientation(data.get("id") or ""))}


def import_failed(data):
    """POST models/importfailed {id}: a model whose import failed leaves the library (no empty tile)."""
    e = _entries().get(data.get("id") or "")
    if e is not None and not os.path.isfile(os.path.join(user_dir(), e["id"], "model.blend")):
        delete({"id": e["id"]})
    return {}


# ---------------------------------------------------------------- inserting

def keep_pivot(ob):
    """(1.78.4) The pivot placed by hand on a model of the library (its root: the top object with the model's id) is
    written in its entry ("pivot", in the root's own space - the same space at every insert: the object itself, or
    the group made at the file's origin). None: back to the lowest point. Not in the locked Simpler parts."""
    mid = ob.get(MODEL_KEY)
    if not mid or (ob.parent is not None and ob.parent.get(MODEL_KEY) == mid):
        return
    e = _entries().get(mid)
    if e is None or is_locked(e.get("folder", "")):
        return
    pv = ob.get("simpler_pivot")
    new = [round(float(v), 6) for v in pv] if pv is not None else None
    if e.get("pivot") == new:
        return
    if new is None:
        e.pop("pivot", None)
    else:
        e["pivot"] = new
    _write_json(os.path.join(user_dir(), mid + ".json"), e)
    from . import paint
    paint.repivot(mid, new)


def insert(data):
    """POST models/insert {id, location (cm, the point where the model's base goes), parent}: the model in the scene
    (one object: as it is, at the root; several: in a group named after the model). Returns {id}."""
    e = _entry(data.get("id"))
    path = os.path.join(user_dir(), e["id"], "model.blend")
    if not os.path.isfile(path):
        raise ApiError(tr("Il modello è ancora in preparazione: riprova tra qualche secondo"))
    r = insert_blend(path, e.get("name") or tr("Modello"), entry=e, location=data.get("location"), parent=data.get("parent"))
    from . import paint
    root = find(r["id"])
    for o in [root] + list(root.children_recursive):
        # (a model saved from painted pieces: it is a new model of its own here)
        for k in ("simpler_paint_gen", "simpler_paint_rest", "simpler_paint_base", "simpler_instance_of"):
            if k in o:
                del o[k]
    paint.tag_pieces(root, e["id"])     # drawn by the real-time view from its prototype: no new preparation
    root["simpler_lib_rev"] = str(e.get("rev", ""))       # (the version of the library: libupdate.outdated)
    return r


def apply_pivot(root, e):
    """(1.78.4) The pivot kept in the library entry, on a copy of the model just inserted (its root)."""
    pv = e.get("pivot") if e else None
    if isinstance(pv, list) and len(pv) == 3 and root.get("simpler_pivot") is None:
        root["simpler_pivot"] = [float(v) for v in pv]


def insert_blend(path, name, entry=None, location=None, parent=None, types=None):
    """The objects of a .blend file in the scene. entry: a library entry (only the objects it saved);
    types: object types to take (e.g. no cameras or lights from a downloaded model)."""
    # (1.75.26) the time of every phase in the log: an insert took 17 s in a big scene with SmartView on (Luca)
    import time as _time
    _tm = {"t": _time.perf_counter(), "parts": []}

    def _lap(what):
        now = _time.perf_counter()
        _tm["parts"].append(f"{what} {now - _tm['t']:.2f}")
        _tm["t"] = now
    before = ({m.as_pointer() for m in bpy.data.materials}, {i.as_pointer() for i in bpy.data.images},
              {g.as_pointer() for g in bpy.data.node_groups})
    with bpy.data.libraries.load(path, link=False) as (src, dst):
        file_names = list(src.objects)
        orig_names = [n for n in src.materials if n.startswith("·orig·")]
        dst.objects = list(src.objects)
        dst.materials = list(orig_names)
    # names as they are in the file (loaded objects may be renamed when the scene has the same names)
    loaded = [(n, o) for n, o in zip(file_names, dst.objects) if o is not None]
    name_of = {o: n for n, o in loaded}
    if entry is not None:
        keep = _keep_names(entry, [n for n, _ in loaded], {n: (name_of.get(o.parent) if o.parent else None) for n, o in loaded})
    else:
        # shapes drawn for the bones of a rig (wdg_* in Poly Haven files) are not part of the model
        shapes = set()
        for _, o in loaded:
            if o.type == "ARMATURE" and o.pose is not None:
                shapes.update(pb.custom_shape for pb in o.pose.bones if pb.custom_shape is not None)
        keep = {n for n, o in loaded if (types is None or o.type in types) and o not in shapes}
    for n, o in loaded:
        if n in keep and o.parent is not None and name_of.get(o.parent) not in keep:
            world = _world(o)
            o.parent = None
            o.matrix_basis = world
    _lap("load")
    bpy.data.batch_remove([o for n, o in loaded if n not in keep])   # (in one call: one by one is quadratic)
    obs = [o for n, o in loaded if n in keep]
    if not obs:
        raise ApiError(tr("Il file del modello è vuoto"))
    coll = bpy.context.scene.collection
    for o in obs:
        coll.objects.link(o)
        new_id(o)
        o.use_fake_user = False
        o.rotation_mode = "XYZ"           # (like every object of the app; Blender converts the rotation)
    tops = [o for o in obs if o.parent is None]
    if len(tops) == 1:
        # one object (with what it contains): it goes straight into the scene, under the name of the model
        root = tops[0]
        if name:
            claim_name(root, name)
    else:
        root = link(bpy.data.objects.new(name or tr("Modello"), None))
        claim_name(root, name or tr("Modello"))
        root.empty_display_size = 0.2
        refresh()
        for t in tops:
            world = t.matrix_world.copy()
            t.parent = root
            t.matrix_parent_inverse.identity()
            t.matrix_world = world
    _lap("link")
    apply_pivot(root, entry)            # (every copy from the library: scene, brush, update from the library)
    if root.type == "EMPTY":
        root[KIND_KEY] = root.get(KIND_KEY) or "group"
    if parent:
        par = find(parent)
        refresh()
        world = root.matrix_world.copy()
        root.parent = par
        root.matrix_parent_inverse.identity()
        root.matrix_world = world
    for m in {s.material for o in obs for s in o.material_slots if s.material is not None}:
        m.use_fake_user = False
    # the hidden originals (·orig·, for «Ripristina originale») loaded with the model: renamed by Blender when the
    # scene has one with that name (·orig·Vetro.001) - the materials follow; a material whose original is not in the
    # file (models saved before 1.35.2) loses the link rather than pointing to the original of another model
    origmap = {n: m.name for n, m in zip(orig_names, dst.materials) if m is not None}
    for m in dst.materials:
        if m is not None:
            m.use_fake_user = True
    for m in [m for m in bpy.data.materials if m.as_pointer() not in before[0]]:
        b = m.get("simpler_mat_backup")
        if b is None:
            continue
        if str(b) in origmap:
            m["simpler_mat_backup"] = origmap[str(b)]
        else:
            del m["simpler_mat_backup"]
    _lap("parent+materials")
    # what the scene already has, identical (not only by name), is shared instead of loaded twice (dedupe.py)
    from . import dedupe
    try:
        shared = dedupe.share_identical([m for m in bpy.data.materials if m.as_pointer() not in before[0]],
                                        [i for i in bpy.data.images if i.as_pointer() not in before[1]],
                                        [g for g in bpy.data.node_groups if g.as_pointer() not in before[2]])
        if any(shared.values()):
            log("SIMPLER_SHARED", name, shared)
    except Exception as exc:
        log("SIMPLER_WARN", "share", exc)
    _lap("share")
    refresh()
    _lap("refresh")
    if location is not None:
        lo, hi = _bbox(obs)
        base = Vector(((lo.x + hi.x) / 2, (lo.y + hi.y) / 2, lo.z))
        pv = entry.get("pivot") if entry else None
        if isinstance(pv, list) and len(pv) == 3:
            base = root.matrix_world @ Vector([float(v) for v in pv])     # (1.78.4: the pivot chosen by hand stands on the point)
        target = Vector([float(v) for v in location]) * CM
        mw = root.matrix_world.copy()
        mw.translation += target - base
        root.matrix_world = mw
        refresh()
    _lap("place")
    log("SIMPLER_INSERT", name, f"{len(obs)} objects", " · ".join(_tm["parts"]))
    return {"id": root[ID_KEY], "name": root.name, "objects": len(obs)}
