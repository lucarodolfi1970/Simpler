"""Poly Haven 3D models (https://polyhaven.com/models, CC0), through the same public API as the textures (library.py).

The list and the thumbnails are kept in %LOCALAPPDATA%\\Simpler\\library\\polyhaven\\models (list refreshed every week);
a model is downloaded the first time it is used: its .blend (Poly Haven's own Blender file, materials made for Cycles)
with the textures it includes, at 2K when available, and stays on disk for every project.
/files/{id} for a model: {"blend": {"2k": {"blend": {url, size, include: {"textures/x.jpg": {url, size}}}}}, "gltf": ...}

Everything except insert() runs on background threads and never touches bpy (API terms: user agent naming the app,
"Poly Haven" shown in the app - the tab is called "Modelli 3D Poly Haven").
"""
import json
import os
import threading
import time

from . import library

RES_ORDER = ("2k", "1k", "4k")
REFRESH_DAYS = 7

_lock = threading.RLock()        # (re-entrant: download() answers with status() while holding it)
_jobs = {}
_list = {"assets": None, "loading": False, "error": ""}
_thumbs = {"running": False}

# Poly Haven model categories -> library folders (unknown ones keep their name)
TOP_FOLDERS = {
    "furniture": "Arredamento", "seating": "Sedute", "table": "Tavoli", "tables": "Tavoli", "storage": "Contenitori",
    "shelves": "Contenitori", "decorative": "Decorazioni", "decoration": "Decorazioni", "lighting": "Illuminazione",
    "lights": "Illuminazione", "plants": "Piante e fiori", "plant": "Piante e fiori", "nature": "Natura",
    "rocks": "Rocce e pietre", "rock": "Rocce e pietre", "props": "Oggetti vari", "prop": "Oggetti vari", "food": "Cibo",
    "kitchen": "Cucina", "bathroom": "Bagno", "electronics": "Elettronica", "tools": "Attrezzi", "industrial": "Industria",
    "buildings": "Edifici", "building": "Edifici", "architecture": "Elementi architettonici", "vehicles": "Veicoli",
    "vehicle": "Veicoli", "outdoor": "Giardino ed esterni", "containers": "Contenitori", "toys": "Giocattoli",
    "books": "Libri", "clothing": "Abbigliamento", "sports": "Sport", "weapons": "Armi", "office": "Ufficio",
    "trees": "Alberi", "tree": "Alberi", "street": "Oggetti città", "urban": "Oggetti città",
}
GENERIC = {"man made", "natural", "indoor", "outdoor", "clean", "dirty", "low poly", "high poly"}


def root():
    from . import paths
    return paths.get("phModels")


def folder_for(category, tags=()):
    """A folder for a model: its category path from Poly Haven (two levels), else the first specific tag."""
    from .i18n import tr

    def name(c):
        c = c.strip()
        it = TOP_FOLDERS.get(c.lower())
        return tr(it) if it else c[:1].upper() + c[1:]
    parts = [p.strip() for p in str(category or "").split("/") if p.strip()]
    if len(parts) > 1:
        return "/".join(name(p).replace("/", "-") for p in parts[:2])
    cats = [c for c in list(tags or []) + parts if str(c).strip()]
    for c in cats:
        if str(c).lower() in TOP_FOLDERS:
            return name(str(c))
    for c in cats:
        if str(c).lower() not in GENERIC:
            return name(str(c))
    return tr("Altro")


# ---------------------------------------------------------------- list and thumbnails

def _list_file():
    return os.path.join(root(), "models.json")


def _load_list():
    path = _list_file()
    fresh = os.path.isfile(path) and time.time() - os.path.getmtime(path) < REFRESH_DAYS * 86400
    if _list["assets"] is None and os.path.isfile(path):
        try:
            with open(path, encoding="utf-8") as f:
                _list["assets"] = json.load(f)
        except (OSError, ValueError):
            _list["assets"] = None
    if not fresh and not _list["loading"]:
        _list["loading"] = True
        threading.Thread(target=_refresh_list, daemon=True).start()


def _refresh_list():
    try:
        data = json.loads(library._get(library.API + "/assets?type=models", timeout=60))
        out = []
        for aid, a in data.items():
            cats = a.get("categories") or []
            out.append({"id": aid, "name": a.get("name", aid), "category": a.get("category") or ", ".join(cats[:2]),
                        "categories": list(cats), "thumb": a.get("thumbnail_url", ""),
                        "downloads": a.get("download_count", 0), "polycount": a.get("polycount", 0)})
        out.sort(key=lambda a: -a["downloads"])
        with open(_list_file() + ".part", "w", encoding="utf-8") as f:
            json.dump(out, f)
        os.replace(_list_file() + ".part", _list_file())
        _list["assets"] = out
        _list["error"] = ""
    except Exception as exc:
        _list["error"] = str(exc)
    finally:
        _list["loading"] = False
    _start_thumbs()


def _thumb_path(aid):
    d = os.path.join(root(), "thumbs")
    os.makedirs(d, exist_ok=True)
    return os.path.join(d, aid + ".png")


def _start_thumbs():
    with _lock:
        if _thumbs["running"] or not _list["assets"]:
            return
        _thumbs["running"] = True

    def run():
        try:
            for a in list(_list["assets"] or []):
                path = _thumb_path(a["id"])
                if os.path.isfile(path) or not a.get("thumb"):
                    continue
                small = a["thumb"].replace("width=256", "width=160").replace("height=256", "height=160")
                for url in (small.replace("format=webp", "format=png"), small):
                    try:
                        library._download(url, path, tries=1)
                        break
                    except Exception:
                        continue
        finally:
            _thumbs["running"] = False
    threading.Thread(target=run, daemon=True).start()


def _ready(aid):
    folder = os.path.join(root(), aid)
    try:
        with open(os.path.join(folder, "model.json"), encoding="utf-8") as f:
            info = json.load(f)
    except (OSError, ValueError):
        return False
    # downloads of 1.2.7-1.2.10 took the .blend even when it had no textures: those are fetched again
    return info.get("v", 1) >= MODEL_VERSION or os.path.isdir(os.path.join(folder, "textures"))


def list_assets(_data=None):
    _load_list()
    _start_thumbs()
    assets = _list["assets"] or []
    return {"assets": [dict(a, folder=folder_for(a.get("category"), a.get("categories")), hasThumb=os.path.isfile(_thumb_path(a["id"])),
                            downloaded=_ready(a["id"])) for a in assets],
            "loading": _list["loading"], "error": _list["error"], "credit": "Poly Haven (polyhaven.com) · CC0"}


def thumb_file(aid):
    path = _thumb_path(os.path.basename(aid or ""))
    return path if os.path.isfile(path) else None


# ---------------------------------------------------------------- download

def _pick(files):
    """(main file info, extension). The .blend at 2K when it comes with its textures; some Poly Haven .blend files
    (rigged models such as cannon_01) have materials without any image: then the glTF, which always carries them."""
    found = []
    for fmt in ("blend", "gltf", "fbx"):
        by_res = files.get(fmt)
        if not isinstance(by_res, dict):
            continue
        for res in RES_ORDER + tuple(sorted(by_res)):
            info = (by_res.get(res) or {}).get(fmt) if isinstance(by_res.get(res), dict) else None
            if isinstance(info, dict) and info.get("url"):
                found.append((info, fmt))
                break
    for info, fmt in found:
        if fmt != "blend" or any(k.lower().startswith("textures") for k in (info.get("include") or {})):
            return info, fmt
    return found[0] if found else (None, None)


MODEL_VERSION = 2      # model.json of older downloads: a .blend without textures is downloaded again


def download(data):
    aid = os.path.basename(data.get("id") or "")
    if not aid:
        return {"state": "error", "error": "id"}
    if _ready(aid):
        return {"id": aid, "state": "done", "fraction": 1.0}
    with _lock:
        job = _jobs.get(aid)
        library._watchdog(job)
        if job and job["state"] == "running":
            return status({"id": aid})
        _jobs[aid] = {"state": "running", "done": 0, "total": 0, "error": "", "started": time.time(), "seen": time.time()}

    def advance(n):
        with _lock:
            _jobs[aid]["done"] += n
            _jobs[aid]["seen"] = time.time()

    def run():
        folder = os.path.join(root(), aid)
        try:
            os.makedirs(folder, exist_ok=True)
            # an old model.json must not say "ready" while the new files are still arriving
            try:
                os.remove(os.path.join(folder, "model.json"))
            except OSError:
                pass
            files = json.loads(library._get(f"{library.API}/files/{aid}"))
            info, fmt = _pick(files)
            if info is None:
                raise RuntimeError("no model file")
            todo = [(info["url"], os.path.basename(info["url"].split("?")[0]), info.get("size", 0))]
            for rel, inc in (info.get("include") or {}).items():
                if isinstance(inc, dict) and inc.get("url"):
                    todo.append((inc["url"], rel, inc.get("size", 0)))
            with _lock:
                _jobs[aid]["total"] = sum(max(1, t[2]) for t in todo)
            for url, rel, size in todo:
                rel = os.path.normpath(rel).lstrip("\\/")
                if rel.startswith(".."):
                    raise RuntimeError("bad path " + rel)
                path = os.path.join(folder, rel)
                os.makedirs(os.path.dirname(path), exist_ok=True)
                if not os.path.isfile(path):
                    library._download(url, path, advance)
                else:
                    advance(max(1, size))
            with open(os.path.join(folder, "model.json"), "w", encoding="utf-8") as f:
                json.dump({"file": todo[0][1], "format": fmt, "v": MODEL_VERSION}, f)
            with _lock:
                _jobs[aid]["state"] = "done"
        except Exception as exc:
            with _lock:
                _jobs[aid].update(state="error", error=str(exc) if isinstance(exc, RuntimeError) else library.explain(exc))
    threading.Thread(target=run, daemon=True).start()
    return status({"id": aid})


def status(data):
    aid = os.path.basename(data.get("id") or "")
    if _ready(aid):
        return {"id": aid, "state": "done", "fraction": 1.0}
    with _lock:
        job = _jobs.get(aid)
        library._watchdog(job)
        job = dict(job or {"state": "none", "done": 0, "total": 0, "error": ""})
    job["id"] = aid
    job["fraction"] = job["done"] / job["total"] if job.get("total") else None
    return job


# ---------------------------------------------------------------- levels of detail (1.76.23)
# Poly Haven models often come with the same shape at several levels of detail: rock_LOD0 (the most triangles) to
# rock_LOD3, all in the file. Inserted whole, all of them were in the scene, one inside the other (Luca: «si
# importano mesh in più per niente»): the app asks which one, the others stay out.
import re as _re
LOD_RE = _re.compile(r"_LOD(\d+)(\.\d+)?$", _re.IGNORECASE)


def lod_of(name):
    m = LOD_RE.search(name or "")
    return int(m.group(1)) if m else None


def lods(data):
    """POST library/models/lods {id} -> {lods: [{level, triangles}]} (empty: one level only). Read from the file
    once (its objects loaded and dropped), then kept next to it."""
    import bpy
    from .core import ApiError
    from .i18n import tr
    aid = os.path.basename(data.get("id") or "")
    if not _ready(aid):
        raise ApiError(tr("Modello non ancora scaricato"))
    folder = os.path.join(root(), aid)
    cache = os.path.join(folder, "lods.json")
    try:
        with open(cache, encoding="utf-8") as f:
            return {"lods": json.load(f)}
    except (OSError, ValueError):
        pass
    with open(os.path.join(folder, "model.json"), encoding="utf-8") as f:
        info = json.load(f)
    out = []
    if info.get("format") == "blend":
        path = os.path.join(folder, info["file"])
        with bpy.data.libraries.load(path, link=False) as (src, dst):
            names = [n for n in src.objects if lod_of(n) is not None]
            dst.objects = names
        tris = {}
        meshes = set()
        for o in dst.objects:
            if o is None:
                continue
            lv = lod_of(o.name)
            if o.type == "MESH" and o.data is not None:
                meshes.add(o.data)
                tris[lv] = tris.get(lv, 0) + sum(len(p.vertices) - 2 for p in o.data.polygons)
            bpy.data.objects.remove(o, do_unlink=True)
        for m in meshes:
            if m.users == 0:
                bpy.data.meshes.remove(m)
        if len(tris) > 1:
            out = [{"level": k, "triangles": int(tris[k])} for k in sorted(tris)]
    try:
        with open(cache, "w", encoding="utf-8") as f:
            json.dump(out, f)
    except OSError:
        pass
    return {"lods": out}


def _keep_lod(root_ob, lod):
    """Only the chosen level of detail of a model just placed: the pieces of the other levels go."""
    import bpy
    if lod is None:
        return
    gone = [o for o in root_ob.children_recursive if lod_of(o.name) is not None and lod_of(o.name) != int(lod)]
    for o in gone:
        for c in list(o.children):              # (what hangs on a level going away: kept, where it is)
            if c not in gone:
                w = c.matrix_world.copy()
                c.parent = root_ob
                c.matrix_world = w
    for o in gone:
        try:
            bpy.data.objects.remove(o, do_unlink=True)
        except ReferenceError:
            pass


# ---------------------------------------------------------------- into the scene (main thread)

def insert(data):
    """POST library/models/insert {id, location}: the downloaded model in the scene (base on location, cm)."""
    from . import models
    from .core import ApiError
    from .i18n import tr
    aid = os.path.basename(data.get("id") or "")
    if not _ready(aid):
        raise ApiError(tr("Modello non ancora scaricato"))
    folder = os.path.join(root(), aid)
    with open(os.path.join(folder, "model.json"), encoding="utf-8") as f:
        info = json.load(f)
    path = os.path.join(folder, info["file"])
    name = next((a.get("name") for a in (_list["assets"] or []) if a["id"] == aid), None) or aid
    if info.get("format") == "blend":
        out = models.insert_blend(path, name, location=data.get("location"), parent=data.get("parent"),
                                  types={"MESH", "EMPTY", "CURVE", "CURVES", "SURFACE", "META", "FONT"})
    else:
        import bpy
        from . import importer
        from .core import find, refresh
        r = importer.import_model(path, data.get("parent", ""))
        root_ob = find(r["id"])
        root_ob.name = name
        # only the visible pieces (a rig's bones and helpers stay out of the picture) and the base where it was dropped
        for o in [o for o in root_ob.children_recursive if o.type in ("ARMATURE", "CAMERA", "LIGHT")]:
            for c in o.children:
                w = c.matrix_world.copy()
                c.parent = root_ob
                c.matrix_world = w
            bpy.data.objects.remove(o, do_unlink=True)
        refresh()
        if data.get("location") is not None:
            from mathutils import Vector
            obs = [o for o in root_ob.children_recursive if o.type == "MESH"]
            lo, hi = models._bbox(obs or [root_ob])
            base = Vector(((lo.x + hi.x) / 2, (lo.y + hi.y) / 2, lo.z))
            mw = root_ob.matrix_world.copy()
            mw.translation += Vector([float(v) for v in data["location"]]) * models.CM - base
            root_ob.matrix_world = mw
            refresh()
        out = {"id": r["id"], "name": name}
    out["source"] = "Poly Haven · CC0"
    from . import paint
    from .core import find as _find, refresh as _refresh
    if data.get("lod") is not None:
        _keep_lod(_find(out["id"]), data.get("lod"))
        _refresh()
        r_ = _find(out["id"])
        out["objects"] = 1 + len(r_.children_recursive)
    # (one prototype per level of detail: the view draws the level placed, not the whole file)
    paint.tag_pieces(_find(out["id"]), "ph_" + aid + (f"_lod{int(data['lod'])}" if data.get("lod") is not None else ""))     # drawn by the real-time view from its prototype
    return out


def to_library(data):
    """POST library/models/tolibrary {id}: a downloaded Poly Haven model as a model of the user's library (folder
    «Poly Haven»), for what works only with library models - the brush and area of Distribuisci (1.75.0: a click on
    a Poly Haven model with the brush on put it in the scene instead). Made once: the same entry after that.
    Returns {id, name, pending (preview request id, or None when already there)}."""
    from . import models
    from .core import ApiError, find
    from .i18n import tr
    aid = os.path.basename(data.get("id") or "")
    if not _ready(aid):
        raise ApiError(tr("Modello non ancora scaricato"))
    lod = data.get("lod")
    lod = int(lod) if lod is not None else None
    for e in models._entries().values():
        if e.get("polyhaven") != aid or e.get("lod") != lod:       # (1.76.23: one entry per level of detail)
            continue
        mdir = os.path.join(models.user_dir(), e["id"])
        meta = os.path.join(models.user_dir(), e["id"] + ".json")
        if os.path.isfile(os.path.join(mdir, "model.blend")) or time.time() - os.path.getmtime(meta) < 600:
            # (its file may still be on its way: the app waits for the preview job of the first time)
            return {"id": e["id"], "name": e["name"], "pending": None}
        models.delete({"id": e["id"]})          # (a first time that never finished: made again)
    placed = insert({"id": aid, "lod": lod})
    root_ob = find(placed["id"])
    base_name = _re.sub(r"\.\d{3}$", "", placed["name"])         # (not «.001» when the model is also in the scene)
    name = base_name + (f" · LOD{lod}" if lod is not None else "")
    try:
        r = models.save({"ids": [placed["id"]], "name": name, "folder": "Poly Haven"})
    finally:
        # (only what the library needs: the copy placed for it goes away)
        import bpy
        for o in [root_ob] + list(root_ob.children_recursive):
            try:
                bpy.data.objects.remove(o, do_unlink=True)
            except ReferenceError:
                pass
        from .core import refresh
        refresh()
    p = os.path.join(models.user_dir(), r["id"] + ".json")
    with open(p, encoding="utf-8") as f:
        e = json.load(f)
    e["polyhaven"] = aid
    if lod is not None:
        e["lod"] = lod
    e["source"] = "Poly Haven · CC0"
    models._write_json(p, e)
    return {"id": r["id"], "name": r["name"], "pending": r.get("pending")}
