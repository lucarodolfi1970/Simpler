"""Ecosistemi: vegetation (or anything) arranged once and placed again on other surfaces.

An ecosystem is made by the user with his own library models (many are commercial: Simpler cannot ship ready ones),
usually on the "banco di prova", a square plot of 20 (or 50) metres where he paints and fills areas with the Scatter
tool until he likes it. Saving it keeps:
- the recipe of every layer (a distribution): its models with their weights and its settings;
- the sample: where every piece stands on the plot (position from the corner of the plot, height above it, rotation,
  scale), so the composition comes back as it was made.

Applied to an object (its faces, or only those with one material), the sample is repeated in tiles over it - each
tile turned by a quarter turn at random so the repetition does not show - and every piece is dropped on the surface
under it (a piece that falls outside the faces is left out: the shape of the object cuts the tiles). Every layer
becomes a distribution of its own (instances: one copy of each model, whatever the number of pieces), all under a
group "Ecosistema"; the group remembers what it was made from, so density, scale and arrangement can be changed and
it is made again.

The files live next to the library models: <models>/../ecosystems/<id>/eco.json + thumb.jpg.
"""
import base64
import json
import math
import os
import time
import uuid

import bpy
from mathutils import Matrix, Vector

from .core import ApiError, ID_KEY, KIND_KEY, find, link, log, new_id, refresh
from .i18n import tr

ECO_KEY = "simpler_eco"              # on the group of an ecosystem in the scene: JSON (id, target, settings)
LAYER_KEY = "simpler_eco_layer"      # on its distributions: the id of the group
PLOT_KEY = "simpler_eco_plot"        # on the plot of the "banco di prova"
WARN_PIECES = 400_000                # above: the app asks before placing
# Memory of one piece, measured (1.38.4): the project in the engine 600-720 B (bpy, 1 million pieces), the same again
# in the render process that loads it, the real-time view about 120 B (its arrays), and Cycles about 1.7-2.1 KB for
# every object of the model it puts in the picture (instances on points: the geometry is there only once, but every
# copy of every part is an object of its own for the path tracer).
BYTES_ENGINE = 650
BYTES_VIEW = 120
BYTES_CYCLES = 1800
MEM_SHARE = 0.6                      # of the memory free now: the rest for the scene, the textures and Windows
MAX_FALLBACK = 3_000_000             # the memory cannot be read: the old limit
DEFAULTS = {"density": 1.0, "scale": 1.0, "seed": 1, "turnTiles": True, "align": None, "onlyMaterial": True,
            "camOnly": False, "camMargin": 0.15, "camFalloff": 0.0, "whole": False, "camOcclude": True,
            "underSea": False, "spill": 0.0, "spillDensity": 0.5}
# (spill: «Oltre il bordo», metres the pieces may go past the edge of the surface they grow on, onto what is next to
# it - the other zones of a terrain, the ground, another lawn; spillDensity: how thick they are just outside, thinning
# to nothing at the end of the band. The band is wider here and narrower there (a noise) and every piece is kept by a
# chance, never by a line: tufts that thin out. Saved with the ecosystem in the library: «spill», «spillDensity».)
SPILL_GRID = 2048                    # cells per side at most of the map of the distance from the edge
# (underSea: with the sea of the Paesaggio on, nothing grows below its level - grass on the sea bed was counted and
# made, 90% of the pieces of a bay seen from above, all hidden under the water)
# (camOnly: made only where the camera looks - decided by «Calcola solo l'area inquadrata» (camview, eco) and the
# ecosystem's own «Sempre intero» (whole); a request may still give it, as camview.refresh does)
CAM_GRID = 400                       # «Solo dove guarda la camera»: rays across the frame for the depth of the terrain
# «Niente pezzi dietro i modelli» (camOcclude): whatever already stands in the scene and is opaque - a building, a
# wall, a car, the trunks of the trees of another distribution, a big rock - hides the
# surface behind it, and there no piece is made; where the surface shows (between two trees, through a gap) pieces
# are made. See-through materials never hide: glass, water, leaves and grass cut out by transparency (Alpha), fog.
# The triangles are drawn into a depth image of the view (OCC_SCALE x the grid of the rays), a pixel is hidden only
# where a triangle covers its centre; far copies are drawn simpler (their corners on a grid of 3/4 of a pixel).
# Only models at least OCC_MIN_H high count (grass, flowers and stones never hide anything).
OCC_MIN_H = 1.5
OCC_SCALE = 2
OCC_TRIS = 4_000_000                 # triangles drawn at most (the nearest first: the far ones matter less)
_OCC = {}


def root():
    from . import paths
    return paths.get("ecosystems")          # (1.78.2: its own folder, Impostazioni > Cartelle; before: next to the models)


def _dir(eid):
    eid = os.path.basename(str(eid or ""))
    if not eid.startswith("e_"):
        raise ApiError(tr("Ecosistema non trovato"))
    return os.path.join(root(), eid)


def _read(eid):
    try:
        with open(os.path.join(_dir(eid), "eco.json"), encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        raise ApiError(tr("Ecosistema non trovato"))


DEFS_KEY = "simpler_eco_defs"          # in the scene: {id: the ecosystem as it was placed} (the library may lose it)


def _defs():
    try:
        return json.loads(bpy.context.scene.get(DEFS_KEY) or "{}")
    except (TypeError, ValueError):
        return {}


def _keep_def(eid, e):
    d = _defs()
    if d.get(eid) != e:
        d[eid] = e
        bpy.context.scene[DEFS_KEY] = json.dumps(d)


OWN_KEY = "simpler_eco_own"            # on the group of an ecosystem in the scene: its layers changed only in this project


def _pal_of(layer):
    """The settings of each model of a layer {model: entry} (weight, scale, rot, season, seasonRand), as composed."""
    pal = {p.get("model"): p for p in layer.get("palette") or [] if isinstance(p, dict)}
    return {m: dict({"model": m, "weight": 100.0}, **pal.get(m, {})) for m in layer.get("models") or []}


def _effective(e, own):
    """(Luca: «A va bene ma solo se lo vincoliamo a quella particolare istanza di ecosistema nel progetto, senza toccare
    l'originale in libreria») the ecosystem of the library with the layers changed in this project (own: {layers:
    [{off, density, palette: [{model, name, weight, scale, rot, season, seasonRand}]}]}, by the index of the layer):
    a model taken away takes its pieces with it; with models added or other presences the pieces of the layer get
    their model again by the presences (always the same draw); scale and turn of a model change its pieces by how much
    they differ from the composed ones; the density of a layer leaves that part of its pieces; a layer off: no pieces."""
    import numpy as np
    if not own or not isinstance(own.get("layers"), list):
        return e
    out = dict(e, layers=[])
    for li, layer in enumerate(e.get("layers") or []):
        o = own["layers"][li] if li < len(own["layers"]) and isinstance(own["layers"][li], dict) else None
        if o is None:
            out["layers"].append(layer)
            continue
        old_m = list(layer.get("models") or [])
        old_p = _pal_of(layer)
        new_p = [dict(p) for p in o.get("palette") or [] if isinstance(p, dict) and p.get("model")]
        new_m = [p["model"] for p in new_p]
        idx = np.frombuffer(base64.b64decode(layer["idx"]), dtype=np.int32)
        trs = np.frombuffer(base64.b64decode(layer["trs"]), dtype=np.float32).reshape(-1, 8).astype(np.float64)
        rng = np.random.default_rng(104729 + li * 7919)
        old_id = np.asarray(old_m + [""], dtype=object)[np.clip(idx, 0, len(old_m))]
        keep = np.isin(old_id, new_m) & (rng.random(len(idx)) < max(0.0, min(1.0, float(o.get("density", 1.0)))))
        if o.get("off") or not new_m:
            keep[:] = False
        old_id, trs = old_id[keep], trs[keep]
        # the fewest pieces change model: a model now less present than composed gives that part of its pieces to the
        # ones now more present (an added model: none before), by how much more each is
        w_new = np.array([max(0.0, float(p.get("weight", 100.0))) for p in new_p])
        w_old = np.array([max(0.0, float(old_p[m].get("weight", 100.0))) if m in old_p else 0.0 for m in new_m])
        if not len(old_id) or w_new.sum() <= 0:
            nidx, old_id, trs = np.zeros(0, dtype=np.int32), old_id[:0], trs[:0]
        else:
            nidx = np.array([new_m.index(m) for m in old_id], dtype=np.int32)
            pn = w_new / w_new.sum()
            po = w_old / w_old.sum() if w_old.sum() > 0 else np.zeros_like(pn)
            give = np.where(po > 1e-9, np.clip((po - pn) / np.maximum(po, 1e-9), 0.0, 1.0), 0.0)
            need = np.clip(pn - po, 0.0, None)
            if need.sum() > 1e-9 and give.any():
                move = rng.random(len(nidx)) < give[nidx]
                nidx[move] = rng.choice(len(new_m), size=int(move.sum()), p=need / need.sum())
        if len(nidx):
            # scale and turn of each model: by how much they differ from those of the model the piece was composed with
            k_old = np.array([float(old_p.get(m, {}).get("scale", 1.0) or 1.0) for m in old_id])
            r_old = np.array([float(old_p.get(m, {}).get("rot", 0.0) or 0.0) for m in old_id])
            k_new = np.array([float(new_p[i].get("scale", 1.0) or 1.0) for i in nidx])
            r_new = np.array([float(new_p[i].get("rot", 0.0) or 0.0) for i in nidx])
            trs[:, 7] *= k_new / np.maximum(k_old, 1e-6)
            a = np.radians(r_new - r_old)
            if np.any(np.abs(a) > 1e-9):
                q = _qmul(np.stack([trs[:, 6], trs[:, 3], trs[:, 4], trs[:, 5]], axis=1),
                          np.stack([np.cos(a / 2), np.zeros_like(a), np.zeros_like(a), np.sin(a / 2)], axis=1))
                trs[:, 6], trs[:, 3], trs[:, 4], trs[:, 5] = q[:, 0], q[:, 1], q[:, 2], q[:, 3]
        out["layers"].append(dict(layer, models=new_m, palette=new_p, count=int(len(nidx)),
                                  idx=base64.b64encode(np.ascontiguousarray(nidx, dtype=np.int32).tobytes()).decode("ascii"),
                                  trs=base64.b64encode(trs.astype(np.float32).tobytes()).decode("ascii")))
    return out


def _own_of(g):
    try:
        return json.loads(g.get(OWN_KEY) or "null") if g is not None else None
    except (TypeError, ValueError):
        return None


def _read_placed(eid, name=""):
    """The ecosystem of one placed in the scene, to make it again -> (ecosystem, id). From the library; deleted from it
    (or saved again under a new id): the copy kept in the project when it was placed (since 1.63.5), else the one of
    the library with the same name, when only one has it."""
    try:
        return _read(eid), eid
    except ApiError:
        pass
    e = _defs().get(eid)
    if e:
        return e, eid
    found = []
    if name:
        for n in sorted(os.listdir(root())):
            p = os.path.join(root(), n, "eco.json")
            if not n.startswith("e_") or not os.path.isfile(p):
                continue
            try:
                with open(p, encoding="utf-8") as f:
                    x = json.load(f)
            except (OSError, ValueError):
                continue
            if (x.get("name") or "").strip().lower() == name.strip().lower():
                found.append((x, n))
    if len(found) == 1:
        print(f"SIMPLER_ECO {eid} not in the library: {found[0][1]} has its name «{name}»", flush=True)
        return found[0]
    raise ApiError(tr("«{0}» non c'è più nella libreria degli ecosistemi: non si può rifare. Rimettilo dalla libreria", name or eid))


def library(_d=None):
    """GET ecosystems -> {items: [{id, name, size, layers, pieces, thumb (base64 jpeg), created}]}"""
    out = []
    for name in sorted(os.listdir(root())):
        p = os.path.join(root(), name, "eco.json")
        if not name.startswith("e_") or not os.path.isfile(p):
            continue
        try:
            with open(p, encoding="utf-8") as f:
                e = json.load(f)
        except (OSError, ValueError):
            continue
        thumb = ""
        tp = os.path.join(root(), name, "thumb.png")            # path traced (the picture of the view until then)
        if not os.path.isfile(tp):
            tp = os.path.join(root(), name, "thumb.jpg")
        if os.path.isfile(tp):
            with open(tp, "rb") as f:
                thumb = base64.b64encode(f.read()).decode("ascii")
        out.append({"id": name, "name": e.get("name", name), "size": e.get("size", 20.0),
                    "layers": len(e.get("layers") or []), "pieces": sum(int(l.get("count") or 0) for l in e.get("layers") or []),
                    "models": sorted({m.get("name") or m.get("model") for l in e.get("layers") or [] for m in l.get("palette") or []}),
                    "thumb": thumb, "created": e.get("created", ""), "folder": _clean(e.get("folder"))})
    out.sort(key=lambda x: x.get("created", ""), reverse=True)
    folders = set()
    for f in list(_folders()) + [x["folder"] for x in out]:
        parts = f.split("/") if f else []
        for k in range(1, len(parts) + 1):
            folders.add("/".join(parts[:k]))
    return {"items": out, "folders": sorted(folders, key=str.lower)}


# ---------------------------------------------------------------- folders (as the 3D models: models.folder_op)

def _clean(path):
    return "/".join(p.strip() for p in str(path or "").replace("\\", "/").split("/") if p.strip())


def _folders():
    try:
        with open(os.path.join(root(), "folders.json"), encoding="utf-8") as f:
            return [_clean(x) for x in json.load(f).get("folders", []) if _clean(x)]
    except (OSError, ValueError):
        return []


def _save_folders(folders):
    with open(os.path.join(root(), "folders.json"), "w", encoding="utf-8") as f:
        json.dump({"folders": sorted(set(folders), key=str.lower)}, f, indent=1)


def _write(eid, e):
    with open(os.path.join(_dir(eid), "eco.json"), "w", encoding="utf-8") as f:
        json.dump(e, f)


def set_defaults(d):
    """POST ecosystems/defaults {id, spill, spillDensity}: the values the ecosystem brings when placed (saved in the
    library: «Salva nell'ecosistema»)."""
    eid = d.get("id")
    e = _read(eid)
    for k in ("spill", "spillDensity"):
        if k in d:
            e[k] = max(0.0, float(d[k]))
    _write(eid, e)
    return {"id": eid, "spill": e.get("spill", 0.0), "spillDensity": e.get("spillDensity", DEFAULTS["spillDensity"])}


def folder_op(data):
    """POST ecosystems/folder {action: create|rename|delete, path, newPath}. Deleting moves the contents up."""
    action = data.get("action")
    path = _clean(data.get("path"))
    folders = _folders()
    if action == "create":
        if not path:
            raise ApiError(tr("Nome vuoto"))
        _save_folders(folders + [path])
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
    folders = [moved(f) for f in folders if not (action == "delete" and (f == path or f.startswith(path + "/")))]
    if action == "rename":
        folders.append(target)
    for name in os.listdir(root()):
        if not name.startswith("e_"):
            continue
        try:
            e = _read(name)
        except ApiError:
            continue
        cur = _clean(e.get("folder"))
        if cur == path or cur.startswith(path + "/"):
            e["folder"] = moved(cur)
            _write(name, e)
    _save_folders([f for f in folders if f])
    return {"path": target}


def move(data):
    """POST ecosystems/move {id, folder}."""
    e = _read(data.get("id"))
    e["folder"] = _clean(data.get("folder"))
    if e["folder"]:
        _save_folders(_folders() + [e["folder"]])
    _write(data["id"], e)
    return {"id": data["id"], "folder": e["folder"]}


def rename(d):
    e = _read(d.get("id"))
    name = (d.get("name") or "").strip()
    if not name:
        raise ApiError(tr("Il nome non può essere vuoto"))
    e["name"] = name
    with open(os.path.join(_dir(d["id"]), "eco.json"), "w", encoding="utf-8") as f:
        json.dump(e, f)
    return {"id": d["id"], "name": name}


def copy(d):
    """POST ecosystems/copy {id, folder}: a copy of the ecosystem (recipe, sample, thumbnail) in that folder, named
    «<name> (copia)»: a base to change for a new one - many ecosystems share the same arrangement. Returns the new id."""
    import shutil
    e = _read(d.get("id"))
    eid = "e_" + uuid.uuid4().hex[:10]
    shutil.copytree(_dir(d.get("id")), os.path.join(root(), eid))
    e["name"] = tr("{0} (copia)", e.get("name") or "")
    e["folder"] = _clean(d.get("folder"))
    e["created"] = time.strftime("%Y-%m-%d %H:%M")
    if e["folder"]:
        _save_folders(_folders() + [e["folder"]])
    _write(eid, e)
    return {"id": eid, "name": e["name"]}


def delete(d):
    import shutil
    p = _dir(d.get("id"))
    if os.path.isdir(p):
        shutil.rmtree(p, ignore_errors=True)
    return {"id": d.get("id")}


EDIT_KEY = "simpler_eco_editing"     # on the plot: the id of the ecosystem of the library put back on it to be changed
SIG_KEY = "simpler_eco_saved"        # on the plot: what its scatters were when it was opened or saved (_bench_sig)
HIDDEN_KEY = "simpler_bench_hidden"  # on the plot: the objects of the scene it hid (json list of ids), shown again by close


def _bench_sig(plot):
    """(1.79.0, Luca: «se ne apro un altro devo poterlo vedere») what the scatters of the bench are now: each one with
    its points object (a new one at every change of its pieces, the old one back with Ctrl+Z) and its place."""
    from . import paint
    out = []
    for g in _groups_on(plot):
        h = paint._holder(g)
        t = g.matrix_world.translation
        out.append(f"{g.get(ID_KEY)}:{h.get(ID_KEY) if h is not None else ''}:{t.x:.3f},{t.y:.3f},{t.z:.3f}")
    return "|".join(sorted(out))


def detail(d):
    """GET ecosystems/detail?id= -> {id, name, folder, size, layers: [{name, count, models: [{model, name, weight}],
    settings}]}: what an ecosystem of the library is made of (the panel shows it before placing or changing it)."""
    from . import models
    eid = d.get("id")
    e = _read(eid)
    names = {k: (v.get("name") or k) for k, v in models._entries().items()}
    layers = []
    for l in e.get("layers") or []:
        pal = l.get("palette") or [{"model": m, "weight": 100} for m in l.get("models") or []]
        layers.append({"name": l.get("name") or "", "count": int(l.get("count") or 0), "settings": l.get("settings") or {},
                       "models": [{"model": p.get("model"), "name": names.get(p.get("model"), p.get("model") or ""),
                                   "weight": p.get("weight", 100), "missing": p.get("model") not in names} for p in pal]})
    return {"id": eid, "name": e.get("name", ""), "folder": _clean(e.get("folder")), "size": float(e.get("size") or 20.0),
            "layers": layers, "created": e.get("created", ""), "edited": e.get("edited", "")}


def editing(d=None):
    """GET ecosystems/editing[?changed=1] -> {id, name, plot}: the ecosystem of the library open on the bench ("" if
    none). With changed: also {bench, changed} - the bench of the scene and whether its scatters are different from
    when the ecosystem was opened or saved (a bench never saved: whether it has scatters)."""
    want = bool((d or {}).get("changed"))
    for ob in bpy.context.scene.objects:
        if not ob.get(PLOT_KEY) or ob.get("simpler_trashed"):
            continue
        eid = ob.get(EDIT_KEY) or ""
        if not eid and not want:
            continue
        out = {"id": "", "name": "", "plot": ob.get(ID_KEY)}
        if eid:
            try:
                out.update(id=eid, name=_read(eid).get("name", ""))
            except ApiError:
                pass
        if want:
            sig = _bench_sig(ob)
            out.update(bench=ob.get(ID_KEY), changed=bool(sig) and sig != (ob.get(SIG_KEY) or ""))
        return out
    return {"id": "", "name": "", "plot": "", "bench": "", "changed": False}


def edit(d):
    """POST ecosystems/edit {id, clear} -> the ecosystem of the library back on the bench to be changed: one scatter per
    layer with the pieces exactly where they were saved (fixed pieces: the brush adds to them and erases them, paint
    BASE_KEY). The bench is made (or resized) for it. Scatters already on the bench: {busy: n} unless clear (the app
    asks first); with clear they go (one undo step with the rest)."""
    import numpy as np
    from . import paint, trash
    eid = d.get("id")
    e = _read(eid)
    size = float(e.get("size") or 20.0)
    r = new_plot({"size": 50.0 if size > 20.0 + 1e-6 else 20.0})
    plot = find(r["id"])
    refresh()
    olds = _groups_on(plot)
    if olds and not d.get("clear"):
        return {"busy": len(olds), "plot": r["id"]}
    if olds:
        trash.trash([o for g in olds for o in [g] + list(g.children_recursive)])
        refresh()
    psize = float(plot.get(PLOT_KEY) or 20.0)
    c = plot.matrix_world.translation
    # (the sample in the middle of the bench: the same corner as when it was saved on a bench of its size)
    x0, y0, z0 = c.x - size / 2, c.y - size / 2, c.z
    made, pieces = [], 0
    for li, layer in enumerate(e.get("layers") or []):
        names = list(layer.get("models") or [])
        idx = np.frombuffer(base64.b64decode(layer.get("idx") or ""), dtype=np.int32)
        trs = np.frombuffer(base64.b64decode(layer.get("trs") or ""), dtype=np.float32).reshape(-1, 8).astype(np.float64).copy()
        if not len(idx) or not names:
            continue
        trs[:, 0] += x0
        trs[:, 1] += y0
        trs[:, 2] += z0
        settings = dict(layer.get("settings") or {})
        settings["mode"] = "brush"                  # (changed with the brush: Shift erases)
        dd = {"group": "", "name": layer.get("name") or tr("Strato {0}", li + 1), "strokes": [], "seed": 1 + li,
              "settings": settings, "area": None, "noRefresh": True, "base": len(idx),
              "palette": layer.get("palette") or [{"model": m, "weight": 100} for m in names]}
        out = paint._set_points(dd, names, idx.astype(np.int32), trs)
        g = find(out["group"])
        g.name = layer.get("name") or g.name
        made.append(out["group"])
        pieces += out["count"]
    plot[EDIT_KEY] = eid
    refresh()
    plot[SIG_KEY] = _bench_sig(plot)
    if psize < size - 1e-6:
        log("SIMPLER_ECO", f"edit: sample of {size} m on a bench of {psize} m")
    return {"plot": r["id"], "groups": made, "pieces": pieces, "name": e.get("name", ""), "hidden": r.get("hidden") or [],
            "size": psize}


# ---------------------------------------------------------------- the plot ("banco di prova")

def new_plot(d):
    """POST ecosystems/plot {size: 20 | 50, clear}: a square of ground where an ecosystem is made, away from the scene (so
    nothing of the scene is painted on). Returns {id, center (cm), size}."""
    from . import ambience
    size = 50.0 if float(d.get("size") or 20) >= 35 else 20.0
    refresh()
    # one plot per scene: the plot is where an ecosystem is being made; asking again gives back the one there (with
    # the other size if asked: same place, same scatters)
    for ob in bpy.context.scene.objects:
        if ob.get(PLOT_KEY) and not ob.get("simpler_trashed") and ob.type == "MESH":
            resized = float(ob.get(PLOT_KEY) or 20.0) != size
            if resized:
                h = size / 2
                for v in ob.data.vertices:
                    v.co = (h if v.co.x > 0 else -h, h if v.co.y > 0 else -h, 0.0)
                if ob.data.uv_layers:
                    for li, loop in enumerate(ob.data.loops):
                        co = ob.data.vertices[loop.vertex_index].co
                        ob.data.uv_layers[0].data[li].uv = ((co.x + h) / 2.0, (co.y + h) / 2.0)
                ob.data.update()
                ob[PLOT_KEY] = size
                ob.name = tr("Banco ecosistema") + f" {int(size)} m"
                refresh()
            if d.get("clear"):
                # (1.79.0, «Nuovo ecosistema»: the bench empty, for a new one - the app asked first about what was on it)
                from . import trash
                olds = _groups_on(ob)
                if olds:
                    trash.trash([o for g in olds for o in [g] + list(g.children_recursive)])
                for k in (EDIT_KEY, SIG_KEY):
                    if k in ob:
                        del ob[k]
                refresh()
            c = ob.matrix_world.translation
            return {"id": ob.get(ID_KEY), "center": [c.x * 100.0, c.y * 100.0, c.z * 100.0], "size": size,
                    "existing": True, "resized": resized, "hidden": _hide_for_plot(ob)}
    # beyond what the scene has (its models, not the big ground of the Ambiente)
    hi_x, lo_y, hi_y, n = 0.0, 0.0, 0.0, 0
    for o in bpy.context.scene.objects:
        if o.type != "MESH" or o.get(ambience.GROUND_KEY) or o.get(PLOT_KEY) or o.hide_render or o.get("simpler_ocean"):
            continue
        for c in o.bound_box:
            w = o.matrix_world @ Vector(c)
            hi_x = max(hi_x, w.x) if n else w.x
            lo_y = min(lo_y, w.y) if n else w.y
            hi_y = max(hi_y, w.y) if n else w.y
            n += 1
    cx = (hi_x + 20.0 + size / 2) if n else 0.0
    cy = ((lo_y + hi_y) / 2) if n else 0.0
    h = size / 2
    me = bpy.data.meshes.new(tr("Banco ecosistema"))
    me.from_pydata([(-h, -h, 0), (h, -h, 0), (h, h, 0), (-h, h, 0)], [], [(0, 1, 2, 3)])
    me.uv_layers.new(name="UVMap")
    for li, uv in zip(range(4), ((0, 0), (1, 0), (1, 1), (0, 1))):
        me.uv_layers[0].data[li].uv = (uv[0] * size / 2.0, uv[1] * size / 2.0)
    ob = bpy.data.objects.new(tr("Banco ecosistema") + f" {int(size)} m", me)
    ob[PLOT_KEY] = size
    ob[KIND_KEY] = "mesh"
    ob.location = (cx, cy, 0.0)
    link(ob)
    new_id(ob)
    try:
        me.materials.append(ambience._ground_material("prato"))
    except Exception:
        pass
    refresh()
    return {"id": ob.get(ID_KEY), "center": [cx * 100.0, cy * 100.0, 0.0], "size": size, "hidden": _hide_for_plot(ob)}


def _hide_for_plot(plot):
    """(1.76.31, Luca) the plot alone in the view while an ecosystem is made: the rest of the scene hidden (as the
    eye of the scene panel does: there it is shown again), in the same undo step. The lights stay (the plot lit as
    the scene) and so do the ground of the Ambiente and the sea (not in the scene panel). The ids hidden."""
    from .core import managed_objects
    from . import scene_ops
    out = []
    for o in managed_objects():
        if o.parent is not None or o is plot or o.type == "LIGHT" or o.get(ambience_ground_key()) \
                or o.get("simpler_ocean") or o.get("simpler_trashed") or o.hide_render:
            continue
        oid = o.get(ID_KEY)
        if not oid:
            continue
        scene_ops.set_visible(oid, False)
        out.append(oid)
    if out:
        from . import history
        history.note_hidden(out)              # (Ctrl+Z shows them again)
        try:
            plot[HIDDEN_KEY] = json.dumps(list(dict.fromkeys(json.loads(plot.get(HIDDEN_KEY) or "[]") + out)))
        except ValueError:
            plot[HIDDEN_KEY] = json.dumps(out)
        refresh()
    return out


def close(_d=None):
    """POST ecosystems/close -> {closed, shown}: (1.79.0, Luca: «come esco da qui!!») the bench goes - with its scatters
    (the app asked first about unsaved changes) - and the objects of the scene it hid are shown again. One undo step."""
    from . import scene_ops, trash
    refresh()
    for ob in bpy.context.scene.objects:
        if not ob.get(PLOT_KEY) or ob.get("simpler_trashed"):
            continue
        try:
            hidden = [str(x) for x in json.loads(ob.get(HIDDEN_KEY) or "[]")]
        except ValueError:
            hidden = []
        victims = scene_ops.descendants_many(list(dict.fromkeys(_groups_on(ob) + [ob])))
        trash.trash(victims)
        shown = []
        for oid in hidden:
            try:
                scene_ops.set_visible(oid, True)
                shown.append(oid)
            except Exception:
                pass                          # (deleted meanwhile)
        refresh()
        return {"closed": True, "shown": shown}
    return {"closed": False, "shown": []}


def ambience_ground_key():
    from .ambience import GROUND_KEY
    return GROUND_KEY


# ---------------------------------------------------------------- save

def _layer_points(group):
    """World pieces of a distribution: (model ids per piece, 4x4 world matrices)."""
    import numpy as np
    from . import paint
    h = paint._holder(group)
    if h is None or h.type != "MESH" or h.data is None or not len(h.data.vertices):
        return [], np.zeros((0, 4, 4))
    me = h.data
    n = len(me.vertices)
    a, b = me.attributes.get("simpler_xform"), me.attributes.get("simpler_model")
    if a is None or b is None:
        return [], np.zeros((0, 4, 4))
    xf = np.empty(n * 16, dtype=np.float32)
    a.data.foreach_get("value", xf)
    xf = xf.reshape(n, 4, 4).transpose(0, 2, 1).astype(np.float64)       # (stored transposed, paint._points_object)
    mi = np.empty(n, dtype=np.int64)
    b.data.foreach_get("value", mi)
    coll = paint._scatter_coll(group)
    ids = [sub.get(paint.MODEL_KEY) or "" for sub in coll.children]
    g = np.array(paint.models._world_now(group), dtype=np.float64)
    world = g[None] @ xf
    return [ids[k] if 0 <= k < len(ids) else "" for k in mi], world


def save(d):
    """POST ecosystems/save {name, plot (id) | ids (distributions), thumb (base64 jpeg)} -> {id}. With a plot: the
    distributions whose pieces stand on it; else the distributions given (the sample = the square around them)."""
    import numpy as np
    from . import paint
    name = (d.get("name") or "").strip() or tr("Ecosistema")
    plot = find(d["plot"], required=False) if d.get("plot") else None
    groups = []
    if d.get("ids"):
        for i in d["ids"]:
            g = find(i, required=False)
            while g is not None and not g.get(paint.PAINT_KEY) and g.parent is not None:
                g = g.parent
            if g is not None and g.get(paint.PAINT_KEY) and g not in groups:
                groups.append(g)
            elif g is not None and g.get(ECO_KEY):
                groups += [c for c in g.children if c.get(paint.PAINT_KEY) and c not in groups]
    refresh()
    if plot is not None:
        size = float(plot.get(PLOT_KEY) or 20.0)
        c = plot.matrix_world.translation
        x0, y0, z0 = c.x - size / 2, c.y - size / 2, c.z
        if not groups:
            groups = _groups_on(plot)
    if not groups:
        raise ApiError(tr("Niente da salvare: dipingi o riempi un'area di modelli sul banco di prova (strumento Scatter)"))
    layers, allpts = [], []
    for g in groups:
        ids, w = _layer_points(g)
        if len(w):
            allpts.append(w[:, :3, 3])
        layers.append((g, ids, w))
    if plot is None:
        pts = np.concatenate(allpts) if allpts else np.zeros((1, 3))
        lo, hi = pts.min(axis=0), pts.max(axis=0)
        size = float(max(hi[0] - lo[0], hi[1] - lo[1], 1.0))
        x0, y0, z0 = float(lo[0]), float(lo[1]), float(lo[2])
    out_layers = []
    for g, ids, w in layers:
        if plot is not None and len(w):
            keep = (w[:, 0, 3] >= x0) & (w[:, 0, 3] <= x0 + size) & (w[:, 1, 3] >= y0) & (w[:, 1, 3] <= y0 + size)
            w = w[keep]
            ids = [m for m, k in zip(ids, keep) if k]
        if not len(w):
            continue
        h = paint._holder(g)
        settings = json.loads(h.get("simpler_paint_settings") or "null") if h is not None else None
        palette = json.loads(h.get("simpler_paint_palette") or "null") if h is not None else None
        names = list(dict.fromkeys(ids))
        idx = np.array([names.index(m) for m in ids], dtype=np.int32)
        trs = np.zeros((len(w), 8), dtype=np.float32)
        for k in range(len(w)):
            m = Matrix(w[k].tolist())
            loc, rot, sc = m.decompose()
            trs[k] = (loc.x - x0, loc.y - y0, loc.z - z0, rot.x, rot.y, rot.z, rot.w, (sc.x + sc.y + sc.z) / 3.0)
        out_layers.append({"name": g.name, "models": names, "palette": palette or [{"model": m, "weight": 100} for m in names],
                           "settings": settings or {}, "count": int(len(w)),
                           "idx": base64.b64encode(idx.tobytes()).decode("ascii"),
                           "trs": base64.b64encode(trs.tobytes()).decode("ascii")})
    if not out_layers:
        raise ApiError(tr("Niente da salvare: dipingi o riempi un'area di modelli sul banco di prova (strumento Scatter)"))
    if d.get("replace"):
        # «Salva modifiche»: the same ecosystem (its id, folder, date and the values saved with it), new layers
        eid = os.path.basename(str(d["replace"]))
        old = _read(eid)
        p = _dir(eid)
        new = dict(old, layers=out_layers, size=size, edited=time.strftime("%Y-%m-%d %H:%M"))
        if (d.get("name") or "").strip():
            new["name"] = name
        name = new.get("name", name)
        for t in ("thumb.png", "thumb.jpg"):             # (the old pictures go: the new ones follow)
            try:
                os.remove(os.path.join(p, t))
            except OSError:
                pass
        _write(eid, new)
    else:
        eid = "e_" + uuid.uuid4().hex[:10]
        p = os.path.join(root(), eid)
        os.makedirs(p, exist_ok=True)
        with open(os.path.join(p, "eco.json"), "w", encoding="utf-8") as f:
            json.dump({"version": 1, "name": name, "size": size, "layers": out_layers,
                       "created": time.strftime("%Y-%m-%d %H:%M"), "folder": _clean(d.get("folder"))}, f)
        if plot is not None:
            plot[EDIT_KEY] = eid                        # («Salva come nuovo»: the new one is the one open on the bench)
    if plot is not None:
        plot[SIG_KEY] = _bench_sig(plot)                # (saved: nothing to ask before opening another one)
    if d.get("thumb"):
        try:
            with open(os.path.join(p, "thumb.jpg"), "wb") as f:
                f.write(base64.b64decode(d["thumb"]))
        except (ValueError, OSError):
            pass
    job = 0
    if plot is not None:
        # the real thumbnail: path traced on the plot (a few seconds, in the preview process); until it is ready the
        # library shows the picture of the view
        try:
            job = _thumb_job(plot, groups, os.path.join(p, "thumb.png"))
        except Exception as exc:
            print("SIMPLER_ECO_THUMB", exc, flush=True)
    return {"id": eid, "name": name, "layers": len(out_layers), "pieces": sum(l["count"] for l in out_layers),
            "thumbJob": job}


def _groups_on(plot):
    """The distributions with pieces on the test plot - painted ones and the layers of an ecosystem placed on it
    (a saved ecosystem put back on the plot to look at it, or to save a variant of it)."""
    import numpy as np
    from . import paint
    size = float(plot.get(PLOT_KEY) or 20.0)
    c = plot.matrix_world.translation
    x0, y0 = c.x - size / 2, c.y - size / 2
    out = []
    for g in bpy.context.scene.objects:
        if not g.get(paint.PAINT_KEY) or any(o.get("simpler_trashed") for o in [g] + _ancestors(g)):
            continue
        _ids, w = _layer_points(g)
        if len(w) and np.any((w[:, 0, 3] >= x0) & (w[:, 0, 3] <= x0 + size) & (w[:, 1, 3] >= y0) & (w[:, 1, 3] <= y0 + size)):
            out.append(g)
    return out


def _ancestors(o):
    out = []
    while o.parent is not None:
        o = o.parent
        out.append(o)
    return out


def thumb(d):
    """POST ecosystems/thumb {id, plot} -> {thumbJob}: the path traced thumbnail made again on the test plot in the
    scene, with the distributions that stand on it (an ecosystem saved before 1.38.5, or after a change of light)."""
    import numpy as np
    from . import paint
    _read(d.get("id"))
    plot = find(d.get("plot"))
    refresh()
    groups = _groups_on(plot)
    if not groups:
        raise ApiError(tr("Niente da salvare: dipingi o riempi un'area di modelli sul banco di prova (strumento Scatter)"))
    return {"thumbJob": _thumb_job(plot, groups, os.path.join(_dir(d["id"]), "thumb.png"))}


def _thumb_job(plot, groups, out):
    """Writes the plot and its distributions (with the models they show) to a small .blend and queues the path traced
    thumbnail. The light: the sun and sky of the project when the sun is up; else a plain daylight of the preview."""
    from . import ambience, paint, previews
    ids, show = {plot}, [plot.name]
    for g in groups:
        for o in _ancestors(g):                    # (an ecosystem's layer sits under its group, under the plot)
            if o not in ids:
                ids.add(o)
                show.append(o.name)
        for o in [g] + list(g.children_recursive):
            if not o.get("simpler_trashed"):
                ids.add(o)
                show.append(o.name)
        coll = paint._scatter_coll(g)
        if coll is not None:
            ids.add(coll)
    sc = bpy.context.scene
    light = None
    sun = ambience._find_flag(ambience.SUN_KEY)
    if sun is not None and sc.world is not None and not sun.hide_render:
        up = (sun.matrix_world.to_3x3() @ Vector((0.0, 0.0, 1.0))).normalized()
        if up.z > math.sin(math.radians(8.0)):
            ids.update({sc.world, sun})
            show.append(sun.name)
            from . import render
            cfg = render.STATE.config
            light = {"world": sc.world.name,
                     "exposure": float(cfg.get("exposure", 0.0)) + float(render.exposure_auto()),     # (as the render)
                     "view": "Khronos PBR Neutral" if cfg.get("colorRender") == "vivid" else "AgX",
                     "look": "None" if cfg.get("colorRender") == "vivid" else (cfg.get("look") or "AgX - Base Contrast")}
    blend = os.path.join(previews.work_dir(), "eco_" + uuid.uuid4().hex[:10] + ".blend")
    bpy.data.libraries.write(blend, ids, fake_user=True, path_remap="ABSOLUTE", compress=False)
    c = plot.matrix_world.translation
    return previews.enqueue_eco(blend, out, show, (c.x, c.y, c.z), float(plot.get(PLOT_KEY) or 20.0), light)


# ---------------------------------------------------------------- apply

def _sea_cut(opts=None):
    """The height below which nothing grows: the level of the sea when there is one (None: no sea, or the ecosystem
    grows under the water too)."""
    if opts and opts.get("underSea"):
        return None
    from . import ocean
    try:
        return float(ocean.settings()["level"]) if ocean.present() else None
    except Exception:
        return None


def _area_above(a, b, c, cut):
    """Fraction of each triangle (a, b, c: n x 3) above the height cut - exact, the height being linear on it."""
    import numpy as np
    h = np.sort(np.stack([a[:, 2], b[:, 2], c[:, 2]], axis=1), axis=1)
    h0, h1, h2 = h[:, 0], h[:, 1], h[:, 2]
    f = np.where(cut <= h0, 1.0, 0.0)
    m1 = (cut > h0) & (cut <= h1)
    m2 = (cut > h1) & (cut < h2)
    with np.errstate(divide="ignore", invalid="ignore"):
        f = np.where(m1, 1.0 - (cut - h0) ** 2 / np.maximum((h1 - h0) * (h2 - h0), 1e-12), f)
        f = np.where(m2, (h2 - cut) ** 2 / np.maximum((h2 - h0) * (h2 - h1), 1e-12), f)
    return np.clip(f, 0.0, 1.0)


_SPILL = {"key": None, "obj": None}


class _Spill:
    """The band past the edge of the surface an ecosystem grows on. The edge: the sides of its faces that border no
    other face of it (and the faces of another material, when only one grows). A map from above of the distance to
    that edge and of its height there (chamfer, 8 neighbours); the surfaces under the band: the faces looking up of
    the other objects around it (and the rest of the same object), the ground of the Ambiente - never a roof: a
    piece is kept only near the height of the edge (at most as steep as 45 degrees from it)."""

    def __init__(self, ob, co, tv, slot, spill, seed):
        import numpy as np
        from . import terrain_gen as TG
        from .core import INTERNAL_KEY
        self.spill = float(spill)
        self.ok = False
        if not len(tv) or self.spill <= 0:
            return
        e = np.sort(np.concatenate([tv[:, [0, 1]], tv[:, [1, 2]], tv[:, [2, 0]]]), axis=1).astype(np.int64)
        nv_ = int(e.max()) + 1
        u, cnt = np.unique(e[:, 0] * nv_ + e[:, 1], return_counts=True)      # (1-D keys: 10× faster than rows)
        u = u[cnt == 1]
        b = np.stack([u // nv_, u % nv_], axis=1)
        if not len(b):
            return
        reach = self.spill * 1.7                          # (the widest the band gets with its noise)
        P0, P1 = co[b[:, 0]], co[b[:, 1]]
        lo = np.minimum(P0, P1).min(axis=0)[:2] - reach - 1.0
        hi = np.maximum(P0, P1).max(axis=0)[:2] + reach + 1.0
        cell = max(self.spill / 8.0, 0.05, float((hi - lo).max()) / SPILL_GRID)
        nx, ny = int((hi[0] - lo[0]) / cell) + 1, int((hi[1] - lo[1]) / cell) + 1
        # the edge sampled every half cell
        L = np.linalg.norm((P1 - P0)[:, :2], axis=1)
        k = np.maximum(1, np.ceil(L / (cell * 0.5)).astype(np.int64))
        seg = np.repeat(np.arange(len(b)), k)
        t = (np.arange(int(k.sum())) - np.repeat(np.cumsum(k) - k, k) + 0.5) / np.repeat(k, k)
        Q = P0[seg] + (P1[seg] - P0[seg]) * t[:, None]
        D = np.full((ny, nx), np.inf, np.float32)
        Z = np.zeros((ny, nx), np.float32)
        ix = np.clip(((Q[:, 0] - lo[0]) / cell).astype(np.int64), 0, nx - 1)
        iy = np.clip(((Q[:, 1] - lo[1]) / cell).astype(np.int64), 0, ny - 1)
        D[iy, ix] = 0.0
        Z[iy, ix] = Q[:, 2]
        steps = int(math.ceil(reach / cell)) + 1
        for _ in range(steps):
            changed = False
            for dy, dx, w in ((0, 1, 1.0), (0, -1, 1.0), (1, 0, 1.0), (-1, 0, 1.0),
                              (1, 1, 1.4142), (1, -1, 1.4142), (-1, 1, 1.4142), (-1, -1, 1.4142)):
                ys = slice(max(dy, 0), ny + min(dy, 0)); yd = slice(max(-dy, 0), ny + min(-dy, 0))
                xs = slice(max(dx, 0), nx + min(dx, 0)); xd = slice(max(-dx, 0), nx + min(-dx, 0))
                cand = D[yd, xd] + np.float32(w * cell)
                dst = D[ys, xs]
                better = cand < dst
                if better.any():
                    dst[better] = cand[better]
                    Z[ys, xs][better] = Z[yd, xd][better]
                    changed = True
            if not changed:
                break
        self.D, self.Z, self.lo, self.cell, self.nx, self.ny = D, Z, lo, cell, nx, ny
        self.perm = TG._perm(np.random.default_rng(int(seed) * 31 + 7))
        # the surfaces under the band
        parts = []
        wlo, whi = lo, hi
        for o in bpy.context.scene.objects:
            if o.type != "MESH" or o.hide_render or o.get(INTERNAL_KEY) or o.get("simpler_trashed") or o.data is None:
                continue
            if o == ob and slot is None:
                continue
            if o.get("simpler_paint_data") or o.get("simpler_ocean") or o.get("simpler_snow_mantle") or o.get("simpler_snow_part"):
                continue
            if o.modifiers.get("Simpler Decal") is not None:
                continue
            M = np.array(o.matrix_world)
            bb = np.array([tuple(c) for c in o.bound_box]) @ M[:3, :3].T + M[:3, 3]
            if (bb[:, 0].max() < wlo[0] or bb[:, 0].min() > whi[0] or bb[:, 1].max() < wlo[1] or bb[:, 1].min() > whi[1]):
                continue
            aco, atv, grow, _n = _all_triangles(o)
            if o == ob:                      # (the same object, the other materials)
                g2 = _all_triangles(o, slot)[2]
                grow = grow & ~g2
            if grow.any():
                # only the triangles in the band (a corner or the centre within reach of the edge): a big model or
                # a big ground next to a small lawn costs only the part near it
                tt = atv[grow]
                near = np.zeros(len(tt), bool)
                for pts in (aco[tt[:, 0]], aco[tt[:, 1]], aco[tt[:, 2]], aco[tt].mean(axis=1)):
                    near |= np.isfinite(self._d_at(pts[:, 0], pts[:, 1]))
                big = np.ptp(aco[tt][:, :, :2], axis=1).max(axis=1) > reach      # (triangles bigger than the band)
                tt = tt[near | big]
                if len(tt):
                    parts.append((aco, tt))
        if not parts:
            return
        offs, cos, tvs = 0, [], []
        for aco, atv in parts:
            cos.append(aco); tvs.append(atv + offs); offs += len(aco)
        self.ground = _Ground(np.concatenate(cos), np.concatenate(tvs))
        self.ok = True

    def _d_at(self, x, y):
        import numpy as np
        ix = np.floor((x - self.lo[0]) / self.cell).astype(np.int64)
        iy = np.floor((y - self.lo[1]) / self.cell).astype(np.int64)
        inside = (ix >= 0) & (ix < self.nx) & (iy >= 0) & (iy < self.ny)
        d = np.full(len(x), np.inf)
        d[inside] = self.D[iy[inside], ix[inside]]
        return d

    def pick(self, x, y):
        """In parts of a million points (the memory of the noises)."""
        import numpy as np
        n = len(x)
        keep = np.zeros(n, bool)
        z, nrm = np.zeros(n), np.zeros((n, 3))
        for a in range(0, n, 1_000_000):
            k_, z_, n_ = self._pick(x[a:a + 1_000_000], y[a:a + 1_000_000])
            keep[a:a + len(k_)], z[a:a + len(k_)], nrm[a:a + len(k_)] = k_, z_, n_
        return keep, z, nrm

    def _pick(self, x, y):
        """For points that fell off the surface: which of them stay (the band, its noise, a chance by the distance,
        stable for a point), and where they land -> (keep, z, normal)."""
        import numpy as np
        from . import terrain_gen as TG
        n = len(x)
        keep = np.zeros(n, bool)
        z, nrm = np.zeros(n), np.zeros((n, 3))
        if not self.ok or not n:
            return keep, z, nrm
        ix = np.floor((x - self.lo[0]) / self.cell).astype(np.int64)
        iy = np.floor((y - self.lo[1]) / self.cell).astype(np.int64)
        inside = (ix >= 0) & (ix < self.nx) & (iy >= 0) & (iy < self.ny)
        d = np.full(n, np.inf)
        zb = np.zeros(n)
        d[inside] = self.D[iy[inside], ix[inside]]
        zb[inside] = self.Z[iy[inside], ix[inside]]
        cand = np.isfinite(d)
        if not cand.any():
            return keep, z, nrm
        c = np.nonzero(cand)[0]
        f = 1.0 / max(0.5, self.spill * 4.0)
        nz = TG.fbm(x[c] * f, y[c] * f, self.perm, 3)            # (the band wider or narrower along the edge)
        width = self.spill * np.clip(0.9 + 2.2 * nz, 0.12, 1.7)
        r = np.clip(d[c] / width, 0.0, None)
        # tufts: a finer noise gathers the pieces in patches with gaps between them
        f2 = 1.0 / max(0.2, self.spill * 0.6)
        tuft = np.clip(0.95 + 2.5 * TG.fbm(x[c] * f2 + 37.1, y[c] * f2 - 11.3, self.perm, 2), 0.0, 2.0)
        prob = float(self.spillDensity) * np.clip(1.0 - r, 0.0, 1.0) ** 1.4 * tuft
        h = np.sin(x[c] * 12.9898 + y[c] * 78.233) * 43758.5453
        uq = h - np.floor(h)                                       # (a chance stable for the point)
        sel = uq < prob
        c = c[sel]
        if not len(c):
            return keep, z, nrm
        hit, zz, nn = self.ground.drop(x[c], y[c])
        hit &= np.abs(zz - zb[c]) <= 0.5 + d[c]                    # (not on a roof, not down a cliff)
        keep[c[hit]] = True
        z[c[hit]] = zz[hit]
        nrm[c[hit]] = nn[hit]
        return keep, z, nrm


def _spill_for(ob, co, tv, slot, spill, dens, seed):
    import numpy as np
    key = (ob.name, ob.data.name if ob.data else "", len(co), float(np.asarray(co).sum()), len(tv), slot, round(float(spill), 3),
           int(seed), tuple(round(v, 3) for v in np.array(ob.matrix_world).ravel()))
    if _SPILL["key"] != key:
        t0 = time.time()
        _SPILL.update(key=key, obj=_Spill(ob, co, tv, slot, spill, seed))
        log("SIMPLER_ECO", f"band past the edge {spill:.2f} m: {time.time() - t0:.2f} s")
    sp = _SPILL["obj"]
    sp.spillDensity = max(0.0, min(1.0, float(dens)))
    return sp


def _target_faces(ob, slot, cut=None):
    """World triangles of the object's faces that look up (vegetation grows on what can be walked on), only those
    of the material slot when given; and their area seen from above (above the sea, cut, when given: triangles all
    under it are left out)."""
    import numpy as np
    dg = bpy.context.evaluated_depsgraph_get()
    ev = ob.evaluated_get(dg)
    me = ev.to_mesh()
    try:
        me.calc_loop_triangles()
        m = np.array(ob.matrix_world)
        nv = len(me.vertices)
        co = np.empty(nv * 3); me.vertices.foreach_get("co", co)
        co = co.reshape(-1, 3) @ m[:3, :3].T + m[:3, 3]
        nt = len(me.loop_triangles)
        tv = np.empty(nt * 3, dtype=np.int64); me.loop_triangles.foreach_get("vertices", tv)
        tv = tv.reshape(-1, 3)
        pi = np.empty(nt, dtype=np.int64); me.loop_triangles.foreach_get("polygon_index", pi)
        if slot is not None and len(me.polygons):
            mi = np.empty(len(me.polygons), dtype=np.int64); me.polygons.foreach_get("material_index", mi)
            tv = tv[mi[pi] == int(slot)]
        a, b, c = co[tv[:, 0]], co[tv[:, 1]], co[tv[:, 2]]
        n = np.cross(b - a, c - a)
        ln = np.linalg.norm(n, axis=1)
        ok = ln > 1e-12
        up = np.zeros(len(n))
        up[ok] = np.abs(n[ok, 2]) / ln[ok]
        keep = up > 0.25                                     # (walls and undersides: nothing grows there)
        frac = np.ones(len(n))
        if cut is not None and len(n):
            frac = _area_above(a, b, c, cut)
            keep &= frac > 0
        tv = tv[keep]
        area_xy = float((np.abs(n[keep, 2]) * frac[keep]).sum() / 2.0)
        return co, tv, area_xy
    finally:
        ev.to_mesh_clear()


def _eco_of(d):
    if d.get("group"):
        g = find(d["group"])
        st = json.loads(g.get(ECO_KEY) or "{}")
        return g, st
    return None, {}


def free_memory():
    """Bytes of physical memory free now (Windows: GlobalMemoryStatusEx; Linux: MemAvailable), or 0."""
    try:
        if os.name == "nt":
            import ctypes

            class MS(ctypes.Structure):
                _fields_ = [("dwLength", ctypes.c_ulong), ("dwMemoryLoad", ctypes.c_ulong),
                            ("ullTotalPhys", ctypes.c_ulonglong), ("ullAvailPhys", ctypes.c_ulonglong),
                            ("ullTotalPageFile", ctypes.c_ulonglong), ("ullAvailPageFile", ctypes.c_ulonglong),
                            ("ullTotalVirtual", ctypes.c_ulonglong), ("ullAvailVirtual", ctypes.c_ulonglong),
                            ("ullAvailExtendedVirtual", ctypes.c_ulonglong)]
            m = MS()
            m.dwLength = ctypes.sizeof(MS)
            if ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(m)):
                return int(m.ullAvailPhys)
            return 0
        with open("/proc/meminfo") as f:
            for line in f:
                if line.startswith("MemAvailable:"):
                    return int(line.split()[1]) * 1024
    except Exception:
        pass
    return 0


_parts_cache = {}


def _parts(model):
    """Objects of a library model (each copy of each one is an object for Cycles)."""
    if model not in _parts_cache:
        n = 1
        try:
            from . import paths
            with open(os.path.join(paths.get("models"), model + ".json"), encoding="utf-8") as f:
                obs = json.load(f).get("objects")
            if isinstance(obs, str):
                import ast
                obs = ast.literal_eval(obs)
            n = max(1, len(obs or []))
        except Exception:
            pass
        _parts_cache[model] = n
    return _parts_cache[model]


def bytes_per_piece(e):
    """Memory of one piece of this ecosystem, on average over its pieces (models with more parts cost more)."""
    import numpy as np
    pieces = parts = 0
    for layer in e.get("layers") or []:
        try:
            idx = np.frombuffer(base64.b64decode(layer["idx"]), dtype=np.int32)
            models = list(layer.get("models") or [])
            cnt = np.bincount(idx, minlength=len(models)) if len(idx) else np.zeros(len(models))
            for k, m in enumerate(models):
                parts += int(cnt[k]) * _parts(m)
                pieces += int(cnt[k])
        except Exception:
            continue
    avg = parts / pieces if pieces else 1.0
    return 2 * BYTES_ENGINE + BYTES_VIEW + BYTES_CYCLES * avg


def limits(e):
    """-> (max pieces for the memory free now, bytes per piece, free bytes)."""
    bpp = bytes_per_piece(e)
    free = free_memory()
    if not free:
        return MAX_FALLBACK, bpp, 0
    return max(1000, int(free * MEM_SHARE / bpp)), bpp, free


def _gb(b):
    return f"{b / 1e9:.1f}".replace(".", ",")


def _mesh_target(ob):
    """The surface an ecosystem grows on: the object, or - a group, a model of the library picked as a whole - its
    biggest piece (of levels of detail LOD0..3 one over the other: the finest)."""
    if ob is not None and ob.type == "MESH" and ob.data is not None:
        return ob
    from .core import descendants
    kids = [o for o in descendants(ob) if o.type == "MESH" and o.data is not None and not o.hide_render
            and not o.get("simpler_trashed") and not o.get("simpler_paint_data")] if ob is not None else []
    if not kids:
        raise ApiError(tr("Lascia l'ecosistema sopra un oggetto"))
    return max(kids, key=lambda o: len(o.data.polygons))


def estimate(d):
    """GET/POST ecosystems/estimate {id, target, slot, density} -> {pieces, warn, max}"""
    e = _read(d.get("id"))
    ob = _mesh_target(find(d.get("target")))
    _co, tv, area = _target_faces(ob, d.get("slot"), _sea_cut(dict(_eco_of(d)[1], **d)))
    size = float(e.get("size") or 20.0)
    dens = max(0.0, min(1.0, float(d.get("density", 1.0))))
    n = int(sum(int(l.get("count") or 0) for l in e["layers"]) * area / (size * size) * dens)
    from . import camview
    cam_only = d["camOnly"] if "camOnly" in d else camview.eco_wanted(dict(_eco_of(d)[1], **d))
    if cam_only and len(tv):
        # (only where the camera looks: the pieces counted as apply makes them, without making them)
        try:
            n = int(apply(dict(d, camOnly=True, camRefresh=True, dry=True))["pieces"])
        except ApiError:
            n = 0
    mx, bpp, free = limits(e)
    mem = n * bpp
    return {"pieces": n, "warn": n > WARN_PIECES or (free and mem > free * 0.3), "max": mx, "area": area,
            "memGB": round(mem / 1e9, 1), "freeGB": round(free / 1e9, 1), "tooMany": n > mx, "camOnly": bool(cam_only)}


def _qmul(a, b):
    """Quaternions (w, x, y, z) in rows: a x b."""
    import numpy as np
    aw, ax, ay, az = a[:, 0], a[:, 1], a[:, 2], a[:, 3]
    bw, bx, by, bz = b[:, 0], b[:, 1], b[:, 2], b[:, 3]
    return np.stack([aw * bw - ax * bx - ay * by - az * bz, aw * bx + ax * bw + ay * bz - az * by,
                     aw * by - ax * bz + ay * bw + az * bx, aw * bz + ax * by - ay * bx + az * bw], axis=1)


class _Ground:
    """The surface seen from above, for pieces that fall straight down: the triangles in a grid of cells (about one
    triangle per cell), so every point only tests the few triangles of its cell. All in numpy: a million pieces in
    about a second, where one ray per piece in Python took about a minute."""
    PAIRS_MAX = 30_000_000
    CHUNK = 4_000_000

    def __init__(self, co, tv):
        import numpy as np
        a, b, c = co[tv[:, 0]], co[tv[:, 1]], co[tv[:, 2]]
        e0, e1 = (b - a), (c - a)
        d = e0[:, 0] * e1[:, 1] - e1[:, 0] * e0[:, 1]
        ok = np.abs(d) > 1e-12                       # (a wall seen from above: no area, nothing falls on it)
        inv = np.where(ok, 1.0 / np.where(ok, d, 1.0), 0.0)
        # (one flat array per number: the lookups of the candidates are the slow part)
        self.ax, self.ay, self.az = (np.ascontiguousarray(a[:, i]) for i in range(3))
        self.p0x, self.p0y, self.p0z = (np.ascontiguousarray(e0[:, i] * (inv if i < 2 else 1.0)) for i in range(3))
        self.p1x, self.p1y, self.p1z = (np.ascontiguousarray(e1[:, i] * (inv if i < 2 else 1.0)) for i in range(3))
        n = np.cross(e0, e1)
        n /= np.maximum(np.linalg.norm(n, axis=1), 1e-20)[:, None]
        n[n[:, 2] < 0] *= -1.0
        self.n = n
        tmin = np.minimum(np.minimum(a[:, :2], b[:, :2]), c[:, :2])
        tmax = np.maximum(np.maximum(a[:, :2], b[:, :2]), c[:, :2])
        tmin, tmax = tmin[ok], tmax[ok]
        tri = np.nonzero(ok)[0]
        self.lo = tmin.min(axis=0) if len(tri) else np.zeros(2)
        ext = np.maximum((tmax.max(axis=0) - self.lo) if len(tri) else np.ones(2), 1e-6)
        cell = max(math.sqrt(ext[0] * ext[1] / max(1, len(tri))) * 0.7, float(ext.max()) / 4096.0, 1e-4)
        while True:
            self.cell = cell
            self.nx, self.ny = int(ext[0] // cell) + 1, int(ext[1] // cell) + 1
            i0 = ((tmin - self.lo) // cell).astype(np.int64)
            i1 = ((tmax - self.lo) // cell).astype(np.int64)
            sx, sy = i1[:, 0] - i0[:, 0] + 1, i1[:, 1] - i0[:, 1] + 1
            cnt = sx * sy
            if int(cnt.sum()) <= self.PAIRS_MAX:
                break
            cell *= 2.0
        t = np.repeat(np.arange(len(tri)), cnt)
        loc = np.arange(int(cnt.sum())) - np.repeat(np.cumsum(cnt) - cnt, cnt)
        key = (i0[t, 1] + loc // sx[t]) * self.nx + (i0[t, 0] + loc % sx[t])
        order = np.argsort(key, kind="stable")
        self.keys, self.tris = key[order], tri[t[order]]

    def drop(self, x, y):
        """-> (hit, z, normal) of the highest triangle under every point (x, y)."""
        import numpy as np
        n = len(x)
        hit, z, nrm = np.zeros(n, dtype=bool), np.zeros(n), np.zeros((n, 3))
        if not n or not len(self.keys):
            return hit, z, nrm
        cx = np.floor((x - self.lo[0]) / self.cell).astype(np.int64)
        cy = np.floor((y - self.lo[1]) / self.cell).astype(np.int64)
        inside = (cx >= 0) & (cx < self.nx) & (cy >= 0) & (cy < self.ny)
        k = np.where(inside, cy * self.nx + cx, -1)
        s0 = np.searchsorted(self.keys, k, "left")
        cnt = np.where(inside, np.searchsorted(self.keys, k, "right") - s0, 0)
        best = np.full(n, -np.inf)
        bt = np.full(n, -1, dtype=np.int64)
        p0 = 0
        cum = np.cumsum(cnt)
        while p0 < n:
            # (in pieces: the candidate pairs of a chunk stay within a few hundred MB)
            base = cum[p0 - 1] if p0 else 0
            p1 = max(p0 + 1, int(np.searchsorted(cum, base + self.CHUNK, "right")))
            p1 = min(p1, n)
            c = cnt[p0:p1]
            pi = np.repeat(np.arange(p0, p1), c)
            if len(pi):
                off = np.arange(len(pi)) - np.repeat(np.cumsum(c) - c, c)
                ti = self.tris[s0[pi] + off]
                vx, vy = x[pi] - self.ax[ti], y[pi] - self.ay[ti]
                u = vx * self.p1y[ti] - self.p1x[ti] * vy
                v = self.p0x[ti] * vy - vx * self.p0y[ti]
                eps = 1e-9
                ok = (u >= -eps) & (v >= -eps) & (u + v <= 1.0 + eps)
                pi, ti, u, v = pi[ok], ti[ok], u[ok], v[ok]
                if len(pi):
                    zc = self.az[ti] + u * self.p0z[ti] + v * self.p1z[ti]
                    # the highest under every point (pi comes sorted: one group per point)
                    st = np.r_[0, np.nonzero(pi[1:] != pi[:-1])[0] + 1]
                    top = np.maximum.reduceat(zc, st)
                    win = zc >= np.repeat(top, np.diff(np.r_[st, len(pi)]))
                    pi, ti, zc = pi[win], ti[win], zc[win]
                    better = zc > best[pi]
                    best[pi[better]] = zc[better]
                    bt[pi[better]] = ti[better]
            p0 = p1
        hit = bt >= 0
        z[hit] = best[hit]
        nrm[hit] = self.n[bt[hit]]
        return hit, z, nrm


# ---------------------------------------------------------------- «Solo dove guarda la camera»
# (as the old Vue did: the pieces only where the camera sees the surface - in the frame, with a margin for the
# shadows and reflections of what is just outside, and not hidden behind a ridge or a hill. A whole mountain range
# of forest becomes the part the picture shows. Moving the camera: «Ricalcola dalla vista»; the same seed gives the
# same pieces where the two views overlap.)

def _cam_now():
    """The camera of the view now (render.STATE): position, target (m), proportions of the frame, lens."""
    from . import render
    c = render.STATE.camera
    t = Vector([float(v) for v in c["target"]]) * 0.01
    yaw, pitch = math.radians(c["yaw"]), math.radians(c["pitch"])
    pos = t + Vector((math.cos(pitch) * math.cos(yaw), math.cos(pitch) * math.sin(yaw), math.sin(pitch))) * c["distance"] * 0.01
    w, h = render.STATE.vp_size
    return {"pos": list(pos), "target": list(t), "aspect": float(w) / max(1.0, float(h)), "lens": float(c["lens"])}


def _all_triangles(ob, slot=None):
    """World triangles of the whole object (what hides what: walls and undersides too), and which of them can carry
    pieces (as _target_faces: looking up, of the material slot when given)."""
    import numpy as np
    dg = bpy.context.evaluated_depsgraph_get()
    ev = ob.evaluated_get(dg)
    me = ev.to_mesh()
    try:
        me.calc_loop_triangles()
        m = np.array(ob.matrix_world)
        co = np.empty(len(me.vertices) * 3); me.vertices.foreach_get("co", co)
        co = co.reshape(-1, 3) @ m[:3, :3].T + m[:3, 3]
        tv = np.empty(len(me.loop_triangles) * 3, dtype=np.int64); me.loop_triangles.foreach_get("vertices", tv)
        tv = tv.reshape(-1, 3)
        a, b, c = co[tv[:, 0]], co[tv[:, 1]], co[tv[:, 2]]
        n = np.cross(b - a, c - a)
        ln = np.maximum(np.linalg.norm(n, axis=1), 1e-20)
        grow = np.abs(n[:, 2]) / ln > 0.25
        if slot is not None and len(me.polygons):
            pi = np.empty(len(me.loop_triangles), dtype=np.int64); me.loop_triangles.foreach_get("polygon_index", pi)
            mi = np.empty(len(me.polygons), dtype=np.int64); me.polygons.foreach_get("material_index", mi)
            grow &= mi[pi] == int(slot)
        return co, tv, grow, n / ln[:, None]
    finally:
        ev.to_mesh_clear()


class _View:
    """The frame of the camera with a margin, and the depth of the surface in it (rays on a grid, dilated by one cell:
    near the edge of a ridge a piece counts as seen). visible(points) -> bool for every point."""

    def __init__(self, cam, margin, co, tv):
        import numpy as np
        from mathutils.bvhtree import BVHTree
        self.pos = np.array(cam["pos"], dtype=np.float64)
        t = np.array(cam["target"], dtype=np.float64)
        f = t - self.pos
        self.dist0 = max(float(np.linalg.norm(f)), 1e-3)
        # (1.76.37, Luca: «più rado in lontananza a 0% e 100% praticamente uguali») the thinning starts at FALL0 (or at
        # the point the camera looks at, when nearer): before, only beyond that point - with it on a far mountain,
        # nearly everything seen was nearer and nothing thinned
        # (1.76.42, Luca: the grass gone after «Ricalcola dalla vista» with the camera far away) not nearer than a
        # quarter of the distance to that point: from 25 m with a camera 900 m away almost nothing was left
        self.fall0 = min(self.dist0, max(FALL0, FALL_FRAC * self.dist0))
        f /= self.dist0
        r = np.cross(f, [0.0, 0.0, 1.0])
        if np.linalg.norm(r) < 1e-6:
            r = np.array([1.0, 0.0, 0.0])
        r /= np.linalg.norm(r)
        self.f, self.r, self.u = f, r, np.cross(r, f)
        aspect, half = max(0.05, cam["aspect"]), math.atan(18.0 / max(1.0, cam["lens"]))
        if aspect >= 1:
            tx = math.tan(half); ty = tx / aspect
        else:
            ty = math.tan(half); tx = ty * aspect
        m = 1.0 + max(0.0, float(margin))
        self.tx, self.ty = tx * m, ty * m
        self.W = CAM_GRID
        self.H = max(48, int(round(CAM_GRID * self.ty / self.tx)))
        # (1.76.52: plain lists, not a tuple per point - 0.4 s less on a terrain of a million triangles)
        bvh = BVHTree.FromPolygons(np.asarray(co).tolist(), np.asarray(tv).tolist(), all_triangles=True)
        depth = np.full((self.H, self.W), np.inf)
        pv = Vector(self.pos)
        F, R, U = Vector(self.f), Vector(self.r), Vector(self.u)
        hp, hd, ht, hw = [], [], [], []
        cell = (2.0 * self.tx / self.W) * (2.0 * self.ty / self.H)
        for j in range(self.H):
            y = (-1.0 + (j + 0.5) * 2.0 / self.H) * self.ty
            for i in range(self.W):
                x = (-1.0 + (i + 0.5) * 2.0 / self.W) * self.tx
                dvec = (F + R * x + U * y).normalized()
                hit = bvh.ray_cast(pv, dvec)
                if hit[0] is not None:
                    depth[j, i] = hit[3]
                    hp.append(hit[0]); hd.append(dvec); ht.append(hit[2])
                    hw.append(cell / (1.0 + x * x + y * y) ** 1.5)       # (the solid angle of the cell)
        # what the rays hit: points of the surface seen, with the area of ground each one stands for (for the count of
        # pieces: a big flat ground of two triangles seen up close is a few square metres, not the whole triangle)
        self.hits = np.array([tuple(p) for p in hp]) if hp else np.zeros((0, 3))
        self.hit_dir = np.array([tuple(d) for d in hd]) if hd else np.zeros((0, 3))
        self.hit_tri = np.array(ht, dtype=np.int64)
        self.hit_w = np.array(hw)
        pad = np.pad(depth, 1, mode="edge")
        self.depth = np.max(np.stack([pad[1 + dj:self.H + 1 + dj, 1 + di:self.W + 1 + di]
                                      for dj in (-1, 0, 1) for di in (-1, 0, 1)]), axis=0)
        fin = self.depth[np.isfinite(self.depth)]
        # (beyond this distance nothing can hide the surface: its farthest point seen, with room for what grows on it)
        self.dmax = float(fin.max()) * 1.05 + 30.0 if fin.size else None

    def might_hide(self, ob):
        """False when the object surely hides nothing of the surface: behind the camera, out of the frame, or farther
        than the surface (its box). Its triangles are then not read at all (1.70.3: all 3,800 pieces of the cathedral
        were read and placed to draw 25,000 triangles - 5 s at the first count)."""
        import numpy as np
        M = np.array(ob.matrix_world, dtype=np.float64)
        Wc = np.array([tuple(c) for c in ob.bound_box], dtype=np.float64) @ M[:3, :3].T + M[:3, 3]
        if self.dmax is not None:
            lo, hi = Wc.min(axis=0), Wc.max(axis=0)
            if float(np.linalg.norm(np.clip(self.pos, lo, hi) - self.pos)) > self.dmax:
                return False
        v = Wc - self.pos
        z = v @ self.f
        if (z <= 0.05).all():
            return False
        if (z > 0.05).all():
            x, y = (v @ self.r) / z, (v @ self.u) / z
            if (x > self.tx).all() or (x < -self.tx).all() or (y > self.ty).all() or (y < -self.ty).all():
                return False
        return True

    occ = None

    def occlude(self, scene, scatter):
        """The depth (along the view) of what hides the surface: scene = [(triangles (n, 3, 3) world)], scatter =
        [(triangles (n, 3, 3) of a model, sorted by area, their areas, instance matrices (k, 4, 4))]. Then visible()
        also wants nothing in front."""
        import numpy as np
        t0 = time.time()
        OW, OH = self.W * OCC_SCALE, self.H * OCC_SCALE
        self.OW, self.OH = OW, OH
        occ = np.full(OH * OW, np.inf, dtype=np.float32)
        pos = self.pos.astype(np.float32)
        f, r, u = (self.f.astype(np.float32), self.r.astype(np.float32), self.u.astype(np.float32))
        sx, sy = 0.5 * OW / self.tx, 0.5 * OH / self.ty          # (tangent -> pixels)
        drawn = [0]

        def put(idx, val):
            """occ[idx] = min(occ[idx], val), the nearest per pixel (np.minimum.at is many times slower)."""
            o = np.lexsort((val, idx))
            idx, val = idx[o], val[o]
            first = np.ones(len(idx), dtype=bool)
            first[1:] = idx[1:] != idx[:-1]
            idx, val = idx[first], val[first]
            occ[idx] = np.minimum(occ[idx], val)

        def raster(T):
            """Triangles (n, 3, 3) in the world into the depth image (pixel centres, perspective-correct depth)."""
            with np.errstate(divide="ignore", invalid="ignore", over="ignore"):
                raster_(T)

        def raster_(T):
            if not len(T):
                return
            v = T - pos
            z = v @ f                                              # (n, 3)
            near = 0.05
            behind = z <= near
            nb = behind.sum(axis=1)
            cross = (nb == 1) | (nb == 2)
            if cross.any():
                # triangles through the plane near the eye: cut there (the wall right beside the camera hides the most;
                # before 1.67.5 such a triangle was left out whole)
                vc, zc, bc = v[cross], z[cross], behind[cross]
                extra = []
                for k_ in (1, 2):
                    sel = bc.sum(axis=1) == k_
                    if not sel.any():
                        continue
                    vv, zz_, bb = vc[sel], zc[sel], bc[sel]
                    # the odd vertex first (the one behind when one is behind, the one in front when two are)
                    odd = np.argmax(bb if k_ == 1 else ~bb, axis=1)
                    rows = np.arange(len(vv))
                    ia, ib, ic = odd, (odd + 1) % 3, (odd + 2) % 3
                    A, B, C = vv[rows, ia], vv[rows, ib], vv[rows, ic]
                    za, zb, zc_ = zz_[rows, ia], zz_[rows, ib], zz_[rows, ic]
                    tab = ((near - za) / (zb - za))[:, None]
                    tac = ((near - za) / (zc_ - za))[:, None]
                    Pab, Pac = A + (B - A) * tab, A + (C - A) * tac
                    if k_ == 1:     # A behind: the quad Pab B C Pac in two triangles
                        extra += [np.stack([Pab, B, C], 1), np.stack([Pab, C, Pac], 1)]
                    else:           # A in front: the triangle A Pab Pac
                        extra.append(np.stack([A, Pab, Pac], 1))
                keep = nb == 0
                v = np.concatenate([v[keep]] + [e.astype(v.dtype) for e in extra])
                z = v @ f
                z = np.maximum(z, near)
            ok = (z >= near - 1e-6).all(axis=1)
            if not ok.any():
                return
            v, z = v[ok], z[ok]
            px = (v @ r) / z * sx + 0.5 * OW - 0.5
            py = (v @ u) / z * sy + 0.5 * OH - 0.5
            x0 = np.maximum(np.ceil(px.min(axis=1)), 0).astype(np.int64)
            x1 = np.minimum(np.floor(px.max(axis=1)), OW - 1).astype(np.int64)
            y0 = np.maximum(np.ceil(py.min(axis=1)), 0).astype(np.int64)
            y1 = np.minimum(np.floor(py.max(axis=1)), OH - 1).astype(np.int64)
            ok = (x0 <= x1) & (y0 <= y1)
            if not ok.any():
                return
            px, py, z, x0, x1, y0, y1 = px[ok], py[ok], z[ok], x0[ok], x1[ok], y0[ok], y1[ok]
            ar = (px[:, 1] - px[:, 0]) * (py[:, 2] - py[:, 0]) - (px[:, 2] - px[:, 0]) * (py[:, 1] - py[:, 0])
            ok = np.abs(ar) > 1e-9
            px, py, z, x0, x1, y0, y1, ar = px[ok], py[ok], z[ok], x0[ok], x1[ok], y0[ok], y1[ok], ar[ok]
            iz = 1.0 / z
            size = np.maximum(x1 - x0, y1 - y0) + 1
            drawn[0] += len(z)
            big = size > SPAN_PX
            if big.any():
                spans(np.nonzero(big)[0], px, py, iz, ar, x0, x1, y0, y1)
            b = 1
            while True:
                sel = (size <= b) & (size > b // 2) & ~big if b > 1 else size <= 1
                if sel.any():
                    idx = np.nonzero(sel)[0]
                    oy, ox = np.mgrid[0:b, 0:b]
                    ox, oy = ox.ravel(), oy.ravel()
                    per = max(1, 6_000_000 // (b * b))
                    for c in range(0, len(idx), per):
                        k = idx[c:c + per]
                        X = x0[k, None] + ox[None]
                        Y = y0[k, None] + oy[None]
                        inb = (X <= x1[k, None]) & (Y <= y1[k, None])
                        Xf, Yf = X.astype(np.float32), Y.astype(np.float32)
                        qx, qy, a_ = px[k], py[k], ar[k][:, None]
                        w0 = ((qx[:, 1, None] - Xf) * (qy[:, 2, None] - Yf) - (qx[:, 2, None] - Xf) * (qy[:, 1, None] - Yf)) / a_
                        w1 = ((qx[:, 2, None] - Xf) * (qy[:, 0, None] - Yf) - (qx[:, 0, None] - Xf) * (qy[:, 2, None] - Yf)) / a_
                        w2 = 1.0 - w0 - w1
                        inside = inb & (w0 >= -1e-5) & (w1 >= -1e-5) & (w2 >= -1e-5)
                        if not inside.any():
                            continue
                        zz = 1.0 / (w0 * iz[k, 0, None] + w1 * iz[k, 1, None] + w2 * iz[k, 2, None])
                        put((Y * OW + X)[inside], zz[inside].astype(np.float32))
                if b >= size.max():
                    break
                b *= 2

        def spans(idx, px, py, iz, ar, x0, x1, y0, y1):
            """Big triangles row by row (1.70.2): on each row of pixels only the stretch inside the triangle, so the
            work is the triangle's area - testing every pixel of its square cost 280 million tests in the cathedral,
            most of them for the long thin triangles of the columns."""
            R = (y1[idx] - y0[idx] + 1)
            tri = np.repeat(idx, R)
            start = np.cumsum(R) - R
            Y = (y0[tri] + np.arange(len(tri)) - np.repeat(start, R)).astype(np.float64)
            xmin = np.full(len(tri), np.inf)
            xmax = np.full(len(tri), -np.inf)
            for a_, b_ in ((0, 1), (1, 2), (2, 0)):
                xa, ya, xb, yb = px[tri, a_], py[tri, a_], px[tri, b_], py[tri, b_]
                dy = yb - ya
                ok_ = ((Y - ya) * (Y - yb) <= 0) & (np.abs(dy) > 1e-12)
                x_ = xa + (Y - ya) * (xb - xa) / np.where(ok_, dy, 1.0)
                xmin = np.where(ok_, np.minimum(xmin, x_), xmin)
                xmax = np.where(ok_, np.maximum(xmax, x_), xmax)
            xl = np.maximum(np.ceil(xmin - 1e-5), x0[tri]).astype(np.int64)
            xr = np.minimum(np.floor(xmax + 1e-5), x1[tri]).astype(np.int64)
            cnt = np.maximum(xr - xl + 1, 0)
            # (in chunks of about 4 million pixels)
            ends = np.cumsum(cnt)
            c0 = 0
            while c0 < len(cnt):
                lim = (ends[c0 - 1] if c0 else 0) + 4_000_000
                c1 = max(c0 + 1, int(np.searchsorted(ends, lim, side="right")))
                cc = cnt[c0:c1]
                n_ = int(cc.sum())
                if n_:
                    t_ = np.repeat(tri[c0:c1], cc)
                    st = np.cumsum(cc) - cc
                    X = (np.repeat(xl[c0:c1], cc) + np.arange(n_) - np.repeat(st, cc))
                    Yp = np.repeat(Y[c0:c1], cc)
                    Xf = X.astype(np.float64)
                    qx, qy = px[t_], py[t_]
                    a_ = ar[t_]
                    w0 = ((qx[:, 1] - Xf) * (qy[:, 2] - Yp) - (qx[:, 2] - Xf) * (qy[:, 1] - Yp)) / a_
                    w1 = ((qx[:, 2] - Xf) * (qy[:, 0] - Yp) - (qx[:, 0] - Xf) * (qy[:, 2] - Yp)) / a_
                    w2 = 1.0 - w0 - w1
                    zz = 1.0 / (w0 * iz[t_, 0] + w1 * iz[t_, 1] + w2 * iz[t_, 2])
                    put(Yp.astype(np.int64) * OW + X, zz.astype(np.float32))
                c0 = c1

        # every object of the scene, then the copies of the distributions - the nearest first, up to OCC_TRIS
        def nearest(T):
            P = T.reshape(-1, 3)
            return float(np.min(np.linalg.norm(P[::max(1, len(P) // 256)] - pos, axis=1))) if len(P) else 1e9
        # (1.70.2: in batches of about 200,000 triangles - one call per object cost 4 ms each, 15 s for the
        # cathedral's 3,800 objects; the nearest first still, the cap OCC_TRIS still per batch)
        batch, nb = [], 0
        for T in sorted(scene, key=nearest):
            if drawn[0] >= OCC_TRIS:
                break
            batch.append(T)
            nb += len(T)
            if nb >= 200_000:
                raster(np.concatenate(batch))
                batch, nb = [], 0
        if batch and drawn[0] < OCC_TRIS:
            raster(np.concatenate(batch))
        # the copies of the distributions: all of them in one list from the nearest, drawn in growing waves; before each
        # wave the copies already hidden whole behind what is drawn are left out (a forest behind the first rows of
        # trees costs nothing more)
        items = []                                           # (nearest depth, job, level, matrix, x, y, radius/z)
        for jid, (lods, Ws) in enumerate(scatter):
            if not len(Ws) or not len(lods[0][1]):
                continue
            T0 = lods[0][1]
            sc = np.linalg.norm(Ws[:, :3, 2], axis=1)
            R_ = float(np.linalg.norm(T0.reshape(-1, 3), axis=1).max())
            v = Ws[:, :3, 3] - self.pos
            z = v @ self.f
            rad = R_ * sc
            zz = np.maximum(z, 1e-3)
            x, y = (v @ self.r) / zz, (v @ self.u) / zz
            inside = (z + rad > 0.05) & (np.abs(x) <= self.tx + rad / zz) & (np.abs(y) <= self.ty + rad / zz)
            inside |= (z > -rad) & (z < rad)
            if not inside.any():
                continue
            Ws, sc, z, rad, x, y = Ws[inside], sc[inside], z[inside], rad[inside], x[inside], y[inside]
            # the level of detail: the coarsest whose cells stay within 3/4 of a pixel at the nearest point of the copy
            pix = 0.75 * np.maximum(z - rad, 0.3) / (sx * sc)
            cs = np.array([c for c, _T in lods])
            lv = np.maximum(np.searchsorted(cs, pix, side="right") - 1, 0)
            for i in range(len(Ws)):
                items.append((float(z[i] - rad[i]), jid, int(lv[i]), Ws[i], float(x[i]), float(y[i]), float(rad[i] / max(z[i], 1e-3)), float(z[i])))
        items.sort(key=lambda it: it[0])
        BLK = 8
        hb, wb = -(-OH // BLK), -(-OW // BLK)

        def coarse():
            o = np.full((hb * BLK, wb * BLK), np.inf, dtype=np.float32)
            o[:OH, :OW] = occ.reshape(OH, OW)
            return o.reshape(hb, BLK, wb, BLK).max(axis=(1, 3))

        culled = 0
        pos_i, wave = 0, 256
        while pos_i < len(items) and drawn[0] < OCC_TRIS:
            batch = items[pos_i:pos_i + wave]
            pos_i += wave
            wave *= 2
            if drawn[0] > 0:
                cm = coarse()
                keep = []
                for it in batch:
                    near, _j, _l, _W, x, y, rz, zc = it
                    if zc - near >= zc or near <= 0.3:           # (the camera inside or very near: always drawn)
                        keep.append(it); continue
                    i0 = int(((x - rz) / self.tx + 1.0) * 0.5 * OW) // BLK
                    i1 = int(((x + rz) / self.tx + 1.0) * 0.5 * OW) // BLK
                    j0 = int(((y - rz) / self.ty + 1.0) * 0.5 * OH) // BLK
                    j1 = int(((y + rz) / self.ty + 1.0) * 0.5 * OH) // BLK
                    if i0 < 0 or j0 < 0 or i1 >= wb or j1 >= hb:   # (partly out of the frame: drawn)
                        keep.append(it); continue
                    if float(cm[j0:j1 + 1, i0:i1 + 1].max()) < near - 0.3:
                        culled += 1                              # (hidden whole: nothing to draw)
                        continue
                    keep.append(it)
                batch = keep
            groups = {}
            for it in batch:
                groups.setdefault((it[1], it[2]), []).append(it[3])
            for (jid, l), Wl in groups.items():
                if drawn[0] >= OCC_TRIS:
                    break
                Q = scatter[jid][0][l][1]
                if not len(Q):
                    continue
                Wk = np.array(Wl, dtype=np.float32)
                per = max(1, 3_000_000 // (len(Q) * 3))
                for a_ in range(0, len(Wk), per):
                    if drawn[0] >= OCC_TRIS:
                        break
                    Wb = Wk[a_:a_ + per]
                    Tw = np.matmul(Q.reshape(1, -1, 3), Wb[:, :3, :3].transpose(0, 2, 1)) + Wb[:, None, :3, 3]
                    raster(Tw.reshape(-1, 3, 3))
        self.occ = occ.reshape(OH, OW)
        log("SIMPLER_ECO", f"hidden by the models: {drawn[0]:,} triangles drawn, {culled:,} copies already hidden, {int(np.isfinite(occ).sum()):,} of {OH * OW:,} pixels, {time.time() - t0:.2f} s")

    def seen_area(self, grow, normals, falloff=0.0, cut=None):
        """Ground area (seen from above, m²) the camera sees on the triangles that carry pieces, weighted by the
        thinning with distance: what the count of pieces is made on."""
        import numpy as np
        if not len(self.hits):
            return 0.0
        ok = grow[self.hit_tri]
        n = normals[self.hit_tri]
        d = np.linalg.norm(self.hits - self.pos, axis=1)
        cos = np.maximum(np.abs(np.sum(self.hit_dir * n, axis=1)), 0.1)
        a = self.hit_w * d * d / cos * np.abs(n[:, 2])
        if falloff > 0:
            a = a * self.fall_total(1.0, np.minimum(1.0, (self.fall0 / np.maximum(d, 1e-3)) ** (2.0 * float(falloff))))
        if cut is not None:
            ok = ok & (self.hits[:, 2] >= cut)            # (under the sea: nothing grows)
        return float(a[ok].sum())

    def visible(self, P):
        import numpy as np
        v = P - self.pos
        z = v @ self.f
        zs = np.maximum(z, 1e-6)
        x, y = (v @ self.r) / zs, (v @ self.u) / zs
        ok = (z > 0.05) & (np.abs(x) <= self.tx) & (np.abs(y) <= self.ty)
        i = np.clip(((x / self.tx + 1.0) * 0.5 * self.W).astype(np.int64), 0, self.W - 1)
        j = np.clip(((y / self.ty + 1.0) * 0.5 * self.H).astype(np.int64), 0, self.H - 1)
        dist = np.linalg.norm(v, axis=1)
        ok &= dist <= self.depth[j, i] + 0.5 + 0.02 * dist
        if self.occ is not None:
            # (nothing opaque standing in front of it; the depth along the view, as drawn by occlude)
            io = np.clip(np.floor((x / self.tx + 1.0) * 0.5 * self.OW).astype(np.int64), 0, self.OW - 1)
            jo = np.clip(np.floor((y / self.ty + 1.0) * 0.5 * self.OH).astype(np.int64), 0, self.OH - 1)
            ok &= z <= self.occ[jo, io] + 0.3
        return ok

    @staticmethod
    def fall_total(p_far, p_fall):
        """(1.76.42, Luca: the grass gone after «Ricalcola dalla vista» with the camera far away - far away 1 in 12
        pieces for the memory times 1 in 400 for «Più rado in lontananza») the part of the pieces kept with both:
        «Più rado» thins on top of the other down to 1/FAR_GROW² (as far as the bigger pieces still cover the ground),
        past that at most FALL_COVER less than the other alone keeps: sparser, never bare."""
        import numpy as np
        return np.maximum(p_far * p_fall, np.minimum(p_far, 1.0 / (FAR_GROW * FAR_GROW)) * FALL_COVER)

    def fall_p(self, P, falloff):
        """«Più rado in lontananza»: the part of the pieces kept at each point (1 nearer than fall0)."""
        import numpy as np
        if falloff <= 0 or not len(P):
            return np.ones(len(P))
        dist = np.linalg.norm(P - self.pos, axis=1)
        return np.minimum(1.0, (self.fall0 / np.maximum(dist, 1e-3)) ** (2.0 * float(falloff)))

    def keep(self, P, falloff, before=None, want=None):
        """«Più rado in lontananza»: farther than fall0, fewer pieces (a stable choice: by position, so the same piece
        stays or goes at every recalculation). (1.76.42) <want>: the part to keep in all (see fall_total), <before>:
        the part already kept by the thinning for the memory (FAR)."""
        import numpy as np
        if falloff <= 0 or not len(P):
            return np.ones(len(P), dtype=bool)
        p = self.fall_p(P, falloff) if want is None else want
        if before is not None:
            p = np.minimum(1.0, p / np.maximum(before, 1e-9))
        h = np.sin(P[:, 0] * 12.9898 + P[:, 1] * 78.233) * 43758.5453
        return (h - np.floor(h)) < p


FALL0 = 25.0            # (1.76.37) metres from the camera where «Più rado in lontananza» starts
FALL_FRAC = 0.25        # (1.76.42) ... but not nearer than this part of the distance to the point looked at
FALL_COVER = 0.6        # (1.76.42) the ground «Più rado in lontananza» leaves covered at least (see _View.fall_total)
OCC_CACHE_BYTES = 1_500_000_000
SPAN_PX = 48            # triangles wider or taller than this (pixels): drawn row by row (spans), not pixel by pixel
_VIEW_CACHE = {"key": None, "view": None}


_OCC_BYTES = [0]           # what the cache of shapes holds now (kept as it changes)


def _occ_size(v):
    if isinstance(v, tuple) and len(v) == 2 and hasattr(v[0], "nbytes"):
        return v[0].nbytes + v[1].nbytes
    if isinstance(v, list):
        return sum(T.nbytes for _c, T in v)
    return 0


def _occ_put(k, v):
    """Into the cache of shapes, within OCC_CACHE_BYTES (the oldest out first). 1.70.2: the total is kept as entries
    come and go - before, every new shape summed the whole cache again (O(n²): 7 million sums and 16 s of the
    cathedral's 4,000 objects at every ecosystem)."""
    old = _OCC.pop(k, None)
    if old is not None:
        _OCC_BYTES[0] -= _occ_size(old)
    _OCC[k] = v
    _OCC_BYTES[0] += _occ_size(v)
    while len(_OCC) > 1 and _OCC_BYTES[0] > OCC_CACHE_BYTES:
        k0 = next(iter(_OCC))
        _OCC_BYTES[0] -= _occ_size(_OCC.pop(k0))
    return v


def _see_through(mat):
    """A material that does not hide what is behind it (in doubt: it does not): glass, water, transparent plastic,
    leaves and grass cut out by the Alpha, fog and smoke."""
    if mat is None:
        return False
    from . import materials, volumetric
    try:
        if volumetric.is_on(mat) or materials.is_transmissive(mat):
            return True
    except Exception:
        return True
    if not mat.use_nodes or mat.node_tree is None:
        return float(getattr(mat, "diffuse_color", (1, 1, 1, 1))[3]) < 0.999

    def opaque_alpha(sock):
        """The Alpha fed straight by a picture without transparency (many imported models link it anyway)."""
        lk = sock.links[0] if sock.links else None
        if lk is None or lk.from_node.type != "TEX_IMAGE" or lk.from_socket.name != "Alpha":
            return False
        img = lk.from_node.image
        if img is None:
            return False
        try:
            return img.alpha_mode == "NONE" or int(img.channels) < 4 or int(img.depth) in (8, 24, 48, 96)
        except Exception:
            return False

    def scan(tree, depth=0):
        for n in tree.nodes:
            if n.type in ("BSDF_TRANSPARENT", "BSDF_GLASS", "BSDF_REFRACTION", "PRINCIPLED_VOLUME", "VOLUME_ABSORPTION",
                          "VOLUME_SCATTER", "HOLDOUT"):
                return True
            if n.type == "BSDF_PRINCIPLED":
                al, tw = n.inputs.get("Alpha"), n.inputs.get("Transmission Weight")
                if al is not None and al.is_linked and not opaque_alpha(al):
                    return True
                if al is not None and not al.is_linked and al.default_value < 0.999:
                    return True
                if tw is not None and (tw.is_linked or tw.default_value > 0.01):
                    return True
            if n.type == "OUTPUT_MATERIAL" and n.inputs.get("Volume") is not None and n.inputs["Volume"].is_linked:
                return True
            if n.type == "GROUP" and n.node_tree is not None and depth < 3 and scan(n.node_tree, depth + 1):
                return True
        return False
    try:
        return scan(mat.node_tree)
    except Exception:
        return True


def _occ_tris(ob):
    """The opaque triangles of an object (its own space, from the biggest), and their areas."""
    import numpy as np
    dg = bpy.context.evaluated_depsgraph_get()
    me = ob.evaluated_get(dg).data
    slots = [sl.material for sl in ob.material_slots]
    clear_ = tuple(_see_through(m) for m in slots)
    nv, nt = len(me.vertices), len(me.loop_triangles)
    co = np.empty(nv * 3, dtype=np.float32)
    if nv:
        me.vertices.foreach_get("co", co)
    # (the key: the mesh, its size, a checksum of its points and which slots are see-through - a mesh deformed or a
    # material turned to glass is read again; before 1.67.5 the name and the counts only)
    k = (ob.data.name if not ob.modifiers else "o:" + ob.name, ob.data.as_pointer(), nv, nt, clear_,
         float(co.sum()), float(np.abs(co).sum()) if nv else 0.0)
    got = _OCC.get(k)
    if got is not None:
        _OCC[k] = _OCC.pop(k)
        return got
    if not nv or not nt:
        return _occ_put(k, (np.zeros((0, 3, 3), np.float32), np.zeros(0, np.float32)))
    V = co.reshape(-1, 3)
    tri = np.empty(nt * 3, dtype=np.int32)
    me.loop_triangles.foreach_get("vertices", tri)
    T = V[tri.reshape(-1, 3)]
    mi = np.empty(nt, dtype=np.int32)
    me.loop_triangles.foreach_get("material_index", mi)
    clear = np.array(list(clear_) or [False], dtype=bool)
    keep = ~clear[np.clip(mi, 0, len(clear) - 1)]
    T = T[keep]
    areas = 0.5 * np.linalg.norm(np.cross(T[:, 1] - T[:, 0], T[:, 2] - T[:, 0]), axis=1)
    order = np.argsort(-areas)
    return _occ_put(k, (np.ascontiguousarray(T[order]), areas[order].astype(np.float32)))


LODS_DISK_MIN = 50_000        # (1.76.48) models with at least these triangles: their levels kept on disk too


def _lods_cached(T):
    """_lods, for a big model also from/into a cache on disk (by the bytes of its triangles): after opening the scene
    again the trees of an ecosystem are not simplified again (seconds each, Luca: «ancora molto lento»)."""
    import hashlib
    import os
    import numpy as np
    if len(T) < LODS_DISK_MIN:
        return _lods(T)
    try:
        from . import diskcache
        d = diskcache.folder("occcache")
        name = "v1_" + hashlib.sha1(T.tobytes()).hexdigest()[:24] + ".npz"
        path = os.path.join(d, name)
        if os.path.isfile(path):
            with np.load(path, allow_pickle=False) as z:
                cells = z["cells"]
                out = [(0.0, T)] + [(float(cells[i]), z[f"l{i}"]) for i in range(1, len(cells))]
            os.utime(path)
            return out
        out = _lods(T)
        os.makedirs(d, exist_ok=True)
        arrs = {f"l{i}": a for i, (_c, a) in enumerate(out) if i > 0}
        tmp = path + ".tmp.npz"
        np.savez(tmp, cells=np.array([c for c, _a in out], np.float64), **arrs)
        os.replace(tmp, path)
        diskcache.prune("occcache")
        return out
    except Exception as exc:  # noqa: BLE001  (the cache is only a help)
        print("SIMPLER_ECO lods cache:", exc, flush=True)
        return _lods(T)


def _lods(T):
    """Levels of detail of opaque triangles (n, 3, 3): [(cell size, triangles)], the first the triangles as they are;
    then the corners snapped on coarser and coarser grids (vertex clustering): the shape stays within a cell, the
    small triangles merge. Chosen per copy by the size of a pixel there.
    (1.76.47, Luca: «tutto super super lento») the cells and the triangles as single numbers (np.unique on rows of
    three sorted their bytes: about 0.5 s per call on a tree of a million triangles, 16 calls per model, all again
    at every ecosystem made again - 109 s of a terrain update); the same triangles as before."""
    import numpy as np
    out = [(0.0, T)]
    if len(T) < 64:
        return out
    P = T.reshape(-1, 3)
    pmin = P.min(axis=0)
    ext = float((P.max(axis=0) - pmin).max())
    c = ext / 512.0
    cur = T
    M1 = np.uint64(0x9E3779B97F4A7C15)
    M2 = np.uint64(0xBF58476D1CE4E5B9)
    while len(cur) > 24 and c < ext / 3.0:
        q = np.floor((P - pmin) / c).astype(np.int64)
        R = int(q.max()) + 2
        cell = (q[:, 0] * R + q[:, 1]) * R + q[:, 2]                 # (R <= 515: always fits)
        _u, inv = np.unique(cell, return_inverse=True)
        inv = inv.reshape(-1, 3).astype(np.int64)
        ok = (inv[:, 0] != inv[:, 1]) & (inv[:, 1] != inv[:, 2]) & (inv[:, 0] != inv[:, 2])
        key = np.sort(inv[ok], axis=1)
        N = int(len(_u)) + 1
        if N ** 3 < 2 ** 62:
            k1 = (key[:, 0] * N + key[:, 1]) * N + key[:, 2]
        else:                        # (a hash of the three: a clash only merges two triangles of a coarse level)
            ku = key.astype(np.uint64)
            with np.errstate(over="ignore"):
                k1 = ((ku[:, 0] * M1) ^ (ku[:, 1] * M2) ^ (ku[:, 2] * M1 * M2)).view(np.int64)
        _k, first = np.unique(k1, return_index=True)
        cen = ((q.astype(np.float32) + 0.5) * c + pmin).astype(np.float32)   # (the corners on the centres of their cells)
        nxt = cen.reshape(-1, 3, 3)[np.nonzero(ok)[0][first]]
        if len(nxt) < len(cur) * 0.8:
            out.append((c, nxt.astype(np.float32)))
            cur = nxt
        c *= 2.0
    return out


def _occluders(target, skip_group, view=None):
    """What can hide the surface (see camOcclude): every object of the scene and the copies of the distributions,
    not the surface itself, the ground, the snow mantles, the decals, fog and clouds, nor the ecosystem being made
    again (skip_group); only their opaque triangles."""
    import numpy as np
    from . import paint, rain, volumetric
    from .ambience import GROUND_KEY
    from .core import INTERNAL_KEY

    def under(o, g):
        while o is not None:
            if o == g:
                return True
            o = o.parent
        return False

    # the height of the whole model a piece belongs to (a car is made of many parts, each lower than the car)
    heights = {}

    def height_of(o):
        root = o
        while root.parent is not None and root.parent != target:
            root = root.parent
        h = heights.get(root.name)
        if h is None:
            zs = []
            for c in [root] + list(root.children_recursive):
                if c.type == "MESH" and not c.hide_render:
                    zs += [(c.matrix_world @ Vector(b)).z for b in c.bound_box]
            h = heights[root.name] = (max(zs) - min(zs)) if zs else 0.0
        return h

    scene = []
    for o in bpy.context.scene.objects:
        if o.type != "MESH" or o == target or o.hide_render or o.get(INTERNAL_KEY) or o.get("simpler_trashed"):
            continue
        if not getattr(o, "visible_camera", True):
            continue
        if o.get(GROUND_KEY) or o.get(paint.DATA_KEY) or o.get("simpler_snow_mantle") or o.get("simpler_snow_part"):
            continue
        if o.modifiers.get("Simpler Decal") is not None or volumetric.is_volume_object(o):
            continue
        if skip_group is not None and under(o, skip_group):
            continue
        if view is not None and not view.might_hide(o):
            continue
        if height_of(o) < OCC_MIN_H:
            continue
        T, _a = _occ_tris(o)
        if len(T):
            M = np.array(o.matrix_world, dtype=np.float32)
            scene.append(T @ M[:3, :3].T + M[:3, 3])
    scatter = []
    for po in [o for o in bpy.context.scene.objects if o.get(paint.DATA_KEY) and not o.hide_render and not o.get("simpler_trashed")]:
        if skip_group is not None and under(po, skip_group):
            continue
        me = po.data
        n = len(me.vertices)
        xa, ma = me.attributes.get("simpler_xform"), me.attributes.get("simpler_model")
        group = po.parent
        coll = bpy.data.collections.get(group.get(paint.SCATTER_COLL) or "") if group is not None else None
        if not n or xa is None or ma is None or coll is None:
            continue
        xf = np.empty(n * 16, dtype=np.float32)
        xa.data.foreach_get("value", xf)
        xf = xf.reshape(n, 4, 4).transpose(0, 2, 1)
        mi = np.empty(n, dtype=np.int32)
        ma.data.foreach_get("value", mi)
        pm = np.array(po.matrix_world, dtype=np.float32)
        subs = list(coll.children)
        for k in np.unique(mi):
            if k < 0 or k >= len(subs):
                continue
            parts = []
            for o in subs[k].all_objects:
                if o.type != "MESH" or o.hide_render or not getattr(o, "visible_camera", True):
                    continue
                T, _a = _occ_tris(o)
                if len(T):
                    Mo = np.array(o.matrix_world, dtype=np.float32)
                    parts.append(T @ Mo[:3, :3].T + Mo[:3, 3])
            if not parts:
                continue
            T = np.concatenate(parts)
            W = pm[None] @ xf[mi == k]
            zs = T[:, :, 2]
            W = W[(zs.max() - zs.min()) * np.linalg.norm(W[:, :3, 2], axis=1) >= OCC_MIN_H]
            if not len(W):
                continue
            # (1.76.47: by what the model is, not by the collection it sits in - an ecosystem made again has new
            # collections, and every model was simplified again)
            key = ("lod", len(T), float(T.sum()), float(np.abs(T).sum()), float((T * T).sum()))
            lods = _OCC.get(key)
            if lods is None:
                lods = _occ_put(key, _lods_cached(np.ascontiguousarray(T, dtype=np.float32)))
            scatter.append((lods, W))
    return scene, scatter


def _tri_visible(view, co, tv, hmax=0.0):
    """Triangles of the surface the camera sees (a corner, the centre, or the same raised by hmax: the crown of a tree
    behind a ridge)."""
    import numpy as np
    a, b, c = co[tv[:, 0]], co[tv[:, 1]], co[tv[:, 2]]
    vis = np.zeros(len(tv), dtype=bool)
    for P in (a, b, c, (a + b + c) / 3.0):
        vis |= view.visible(P)
        if hmax > 0:
            vis |= view.visible(P + np.array([0.0, 0.0, hmax]))
    return vis


def _height(orig):
    """Height of a model as it stands (its pieces), for what shows above a ridge."""
    zs = []
    for o in [orig] + list(orig.children_recursive):
        if o.type == "MESH":
            zs.extend((o.matrix_world @ Vector(cr)).z for cr in o.bound_box)
    return (max(zs) - min(zs)) if zs else 1.0


def _known_heights(e, sc):
    """Heights of the models of an ecosystem as they already are in the scene (no loading: the count must not
    change anything) -> (heights by layer, the highest) or (None, 0) when one is missing."""
    import numpy as np
    from . import paint
    roots = {}
    for c in bpy.data.collections:
        if not c.get(paint.SCATTER_TAG):
            continue
        for sub in c.children:
            mid = sub.get(paint.MODEL_KEY)
            if mid and mid not in roots:
                r = next((o for o in sub.objects if (o.parent is None or o.parent.name not in sub.objects)
                          and not o.get("simpler_trashed")), None)
                if r is not None:
                    roots[mid] = r
    heights, hmax = {}, 0.0
    for li, layer in enumerate(e["layers"]):
        mids = list(layer.get("models") or [])
        if any(m not in roots for m in mids):
            return None, 0.0
        hs = [_height(roots[m]) for m in mids] or [1.0]
        trs_ = np.frombuffer(base64.b64decode(layer["trs"]), dtype=np.float32).reshape(-1, 8)
        smax = float(trs_[:, 7].max()) * sc if len(trs_) else sc
        hmax = max(hmax, max(hs) * smax)
        heights[li] = np.array(hs)
    return heights, hmax


CAND_MAX = 4_000_000                 # pieces tried at most before the cut to what the camera sees (peak ~2 GB, measured)
CUT = {"far": 0.0}
FAR = {"d0": 0.0}                    # (1.76.2) past d0 from the camera the pieces thin out and grow (see apply)
FAR_GROW = 2.5                   # how far the pieces go when the far tiles were left out (0: none)


def apply(d):
    """POST ecosystems/apply {id, target, slot, density, scale, seed, turnTiles, align, group (to make again)}
    -> {group, pieces, layers}"""
    import numpy as np
    from . import paint, trash
    old, prev = _eco_of(d)
    opts = dict(DEFAULTS)
    opts.update({k: v for k, v in prev.items() if k in DEFAULTS})
    opts.update({k: d[k] for k in DEFAULTS if k in d})
    eid = d.get("id") or prev.get("id")
    # (made again: the object it is the child of - a copy of the object carries a copy of the ecosystem, which
    # grows on the copy)
    host = old.parent if old is not None and old.parent is not None and old.parent.type == "MESH" else None
    tid = d.get("target") or (host.get(ID_KEY) if host is not None else None) or prev.get("target")
    slot = d["slot"] if "slot" in d else prev.get("slot")
    e, eid = _read_placed(eid, prev.get("name") or "")
    # (the layers changed only in this project: «own» given - None goes back to the library - or the ones it had)
    own = d["own"] if "own" in d else _own_of(old)
    lib_e = e
    e = _effective(e, own)
    for k in ("spill", "spillDensity"):                 # (first placed: the values saved with the ecosystem)
        if k not in prev and k not in d and k in e:
            opts[k] = e[k]
    ob = _mesh_target(find(tid))
    use_slot = slot if (opts.get("onlyMaterial") and slot is not None) else None
    refresh()
    cut = _sea_cut(opts)
    co, tv, area = _target_faces(ob, use_slot, cut)
    if not len(tv):
        if cut is not None and len(_target_faces(ob, use_slot)[1]):
            raise ApiError(tr("Questa superficie è tutta sotto il livello del mare: qui non cresce nulla"))
        raise ApiError(tr("Su questo oggetto non c'è una superficie su cui far crescere qualcosa (solo pareti o facce rivolte in basso)"))
    size = float(e.get("size") or 20.0)
    dens = max(0.0, min(1.0, float(opts["density"])))
    total = sum(int(l.get("count") or 0) for l in e["layers"])
    from . import camview
    if "camOnly" not in d:
        opts["camOnly"] = camview.eco_wanted(opts)
    cam_only = bool(opts.get("camOnly"))
    view, cam = None, None
    if cam_only:
        # (the view it was cut for stays: changing the density later does not cut it again for wherever the camera
        # is now; «Ricalcola dalla vista» - camRefresh - takes the camera of now)
        cam = prev.get("camView") if (prev.get("camView") and not d.get("camRefresh")) else _cam_now()
        aco, atv, grow, nrm = _all_triangles(ob, use_slot)
        # (the same view for the count and the making that follows it - estimate, count, apply: before 1.67.5 the rays
        # and the hidden parts were made again for each, 2-4 times per click)
        from . import rain
        ckey = (json.dumps(cam, sort_keys=True, default=float), float(opts["camMargin"]), ob.name, use_slot,
                bool(opts.get("camOcclude", True)), old.name if old is not None else "", rain._STATE["changes"],
                len(aco), float(np.asarray(aco).sum()))
        if _VIEW_CACHE["key"] == ckey:
            view = _VIEW_CACHE["view"]
        else:
            view = _View(cam, opts["camMargin"], aco, atv)
            if opts.get("camOcclude", True):
                view.occlude(*_occluders(ob, old, view))
            _VIEW_CACHE.update(key=ckey, view=view)
        area = view.seen_area(grow, nrm, float(opts["camFalloff"]), cut)
        if area <= 0:
            raise ApiError(tr("La camera non vede questa superficie: inquadrala e riprova, o metti l'ecosistema «Sempre intero» (nelle sue Avanzate)"))
    est = int(total * area / (size * size) * dens)
    mx, bpp, free = limits(e)
    num = lambda v: f"{v:,}".replace(",", ".")
    if d.get("dry") and view is None:
        # (the count only, without the camera: the estimate on the area - nothing in the scene changes)
        return {"pieces": est, "max": mx, "memGB": round(est * bpp / 1e9, 1), "freeGB": round(free / 1e9, 1),
                "warn": est > WARN_PIECES or bool(free and est * bpp > free * 0.3), "tooMany": est > mx}
    if view is None and est > mx:
        if free:
            raise ApiError(tr("Troppi pezzi per la memoria di questo PC: circa {0}, che chiederebbero circa {1} GB (liberi ora: {2} GB, quindi al massimo circa {3} pezzi). Abbassa la densità o usa una superficie più piccola",
                              num(est), _gb(est * bpp), _gb(free), num(mx)))
        raise ApiError(tr("Troppi pezzi: circa {0} (il massimo è {1}). Abbassa la densità o usa una superficie più piccola", num(est), num(mx)))
    used = np.unique(tv)
    lo, hi = co[used].min(axis=0), co[used].max(axis=0)
    spill_m = max(0.0, float(opts.get("spill") or 0.0))
    spl = _spill_for(ob, co, tv, use_slot, spill_m, opts.get("spillDensity", 0.5), opts["seed"]) if spill_m > 0 and float(opts.get("spillDensity") or 0) > 0 else None
    if spl is not None and spl.ok:
        lo, hi = lo - spill_m * 1.7, hi + spill_m * 1.7            # (the tiles cover the band too)
        lo[2], hi[2] = co[used][:, 2].min(), co[used][:, 2].max()
    else:
        spl = None
    rng = np.random.default_rng(int(opts["seed"]) & 0x7FFFFFFF)
    nx, ny = max(1, int(math.ceil((hi[0] - lo[0]) / size))), max(1, int(math.ceil((hi[1] - lo[1]) / size)))
    turns = rng.integers(0, 4, size=(nx, ny)) if opts.get("turnTiles", True) else np.zeros((nx, ny), dtype=np.int64)
    sc = max(0.05, min(10.0, float(opts["scale"])))
    def generate(heights, hmax):
        """The pieces of every layer: [(layer index, model indices, transforms)], cut to the view when there is one."""
        tile_ok = None
        FAR.update(d0=0.0)
        if view is None:
            ground = _Ground(co, tv)
        else:
            # the triangles that carry pieces and the camera sees: a corner or the centre in sight (raised by the
            # tallest model too), or hit by a ray of the view (a big triangle seen only in its middle)
            hit_ = np.zeros(len(atv), dtype=bool)
            hit_[view.hit_tri] = True
            vis = grow & (_tri_visible(view, aco, atv, hmax) | hit_)
            ground = _Ground(aco, atv[vis])
            x0 = (lo[0] + hi[0]) / 2 - nx * size / 2
            y0 = (lo[1] + hi[1]) / 2 - ny * size / 2
            # the tiles to make: those with a point the camera sees - the centre and the corners of every tile
            # dropped on the surface (far away, where a ray of the view covers several tiles), and the tiles where
            # the rays hit (up close, where a tile is bigger than what the camera sees); one tile more all around
            tile_ok = np.zeros((nx + 2, ny + 2), dtype=bool)
            gi, gj = np.meshgrid(np.arange(nx), np.arange(ny), indexing="ij")
            gi, gj = gi.ravel(), gj.ravel()
            for fx, fy in ((0.5, 0.5), (0.02, 0.02), (0.98, 0.02), (0.02, 0.98), (0.98, 0.98)):
                px, py = x0 + (gi + fx) * size, y0 + (gj + fy) * size
                h_, z_, _n = ground.drop(px, py)
                if not h_.any():
                    continue
                P = np.stack([px[h_], py[h_], z_[h_]], axis=1)
                seen = view.visible(P) | view.visible(P + np.array([0.0, 0.0, hmax]))
                if cut is not None:
                    seen &= P[:, 2] >= cut
                tile_ok[gi[h_][seen] + 1, gj[h_][seen] + 1] = True
            hits = view.hits if cut is None or not len(view.hits) else view.hits[view.hits[:, 2] >= cut]
            if len(hits):
                ti = np.clip(((hits[:, 0] - x0) // size).astype(np.int64), 0, nx - 1)
                tj = np.clip(((hits[:, 1] - y0) // size).astype(np.int64), 0, ny - 1)
                tile_ok[ti + 1, tj + 1] = True
            k = tile_ok.copy()
            for di in (-1, 0, 1):
                for dj in (-1, 0, 1):
                    k[1:nx + 1, 1:ny + 1] |= tile_ok[1 + di:nx + 1 + di, 1 + dj:ny + 1 + dj]
            tile_ok = k[1:nx + 1, 1:ny + 1]
            # a view over a big surface to the horizon (a ground of 4 km, a camera low over it): the tiles it sees
            # would make hundreds of millions of candidates before the cut to what is visible - out of memory (950 MB
            # for one array, then the engine killed). Only the nearest tiles, up to CAND_MAX candidates: far away the
            # pieces are smaller than a pixel anyway
            per_tile = max(1.0, total * dens)
            n_ok = int(tile_ok.sum())
            FAR.update(d0=0.0)
            if n_ok * per_tile > CAND_MAX:
                # (1.76.2) before, the far tiles were left out: no grass at all past 300-500 m (Luca: a hill with
                # trees and bare ground behind). Now every tile seen stays; past a distance d0 the pieces thin out as
                # (d0/d)^2 - about as fast as their size on screen shrinks - and grow by 1/sqrt of that (at most
                # FAR_GROW times), so the ground stays as covered: far away a blade is less than a pixel anyway
                ti_, tj_ = np.nonzero(tile_ok)
                tcx = (lo[0] + hi[0]) / 2 + (ti_ - (nx - 1) / 2) * size
                tcy = (lo[1] + hi[1]) / 2 + (tj_ - (ny - 1) / 2) * size
                dist = np.maximum(np.hypot(tcx - view.pos[0], tcy - view.pos[1]), size * 0.5)
                a, b = 1.0, float(dist.max()) + size
                for _ in range(40):                                 # (d0: the candidates fit CAND_MAX)
                    m_ = 0.5 * (a + b)
                    if float((np.minimum(1.0, (m_ / dist) ** 2) * per_tile).sum()) > CAND_MAX:
                        b = m_
                    else:
                        a = m_
                FAR.update(d0=a)
                CUT["far"] = 0.0
                log("SIMPLER_ECO", f"thinner past {a:.0f} m from the camera (tiles seen: {n_ok}, farthest {float(dist.max()):.0f} m)")
        out = []
        for li, layer in enumerate(e["layers"]):
            idx = np.frombuffer(base64.b64decode(layer["idx"]), dtype=np.int32)
            if not len(idx):
                continue                                 # (a layer switched off in this project)
            trs = np.frombuffer(base64.b64decode(layer["trs"]), dtype=np.float32).reshape(-1, 8).astype(np.float64)
            align = opts["align"] if opts["align"] is not None else bool((layer.get("settings") or {}).get("align", False))
            lrng = np.random.default_rng((int(opts["seed"]) * 7919 + li * 104729) & 0x7FFFFFFF)
            half = size / 2.0
            js, wxs, wys, angs = [], [], [], []
            for ix in range(nx):
                for iy in range(ny):
                    # (the tiles centred on the surface: a small one gets the middle of the sample)
                    cx = (lo[0] + hi[0]) / 2 + (ix - (nx - 1) / 2) * size
                    cy = (lo[1] + hi[1]) / 2 + (iy - (ny - 1) / 2) * size
                    ang = int(turns[ix, iy]) * math.pi / 2
                    ca, sa = math.cos(ang), math.sin(ang)
                    if tile_ok is not None:
                        # (only where the camera looks: one sequence of random numbers per tile, so a tile has the
                        # same pieces whatever the others - and the tiles out of sight cost nothing)
                        if not tile_ok[ix, iy]:
                            continue
                        trng = np.random.default_rng([int(opts["seed"]) & 0x7FFFFFFF, li, ix, iy])
                        keep = trng.random(len(idx)) < dens if dens < 1.0 else np.ones(len(idx), dtype=bool)
                        if FAR["d0"] > 0:
                            ux = cx + ca * (trs[:, 0] - half) - sa * (trs[:, 1] - half)
                            uy = cy + sa * (trs[:, 0] - half) + ca * (trs[:, 1] - half)
                            dd = np.maximum(np.hypot(ux - view.pos[0], uy - view.pos[1]), 1e-3)
                            keep &= trng.random(len(idx)) < np.minimum(1.0, (FAR["d0"] / dd) ** 2)
                    else:
                        keep = lrng.random(len(idx)) < dens if dens < 1.0 else np.ones(len(idx), dtype=bool)
                    j = np.nonzero(keep)[0]
                    px, py = trs[j, 0] - half, trs[j, 1] - half
                    js.append(j); wxs.append(cx + ca * px - sa * py); wys.append(cy + sa * px + ca * py)
                    angs.append(np.full(len(j), ang))
            if not js:
                continue
            j = np.concatenate(js)
            # every piece falls straight down on the surface, all at once (vectorised: about a second per million)
            wxa, wya = np.concatenate(wxs), np.concatenate(wys)
            del wxs, wys
            hit, z, nrm = ground.drop(wxa, wya)
            if spl is not None:
                # (past the edge: on what is next to the surface, thinner and thinner)
                miss = np.nonzero(~hit)[0]
                if len(miss):
                    k_, z_, n_ = spl.pick(wxa[miss], wya[miss])
                    m_ = miss[k_]
                    hit[m_] = True
                    z[m_] = z_[k_]
                    nrm[m_] = n_[k_]
            if cut is not None:
                hit &= z >= cut                                  # (under the sea: nothing grows)
            j, z, nrm = j[hit], z[hit], nrm[hit]
            wx, wy, ang = wxa[hit], wya[hit], np.concatenate(angs)[hit]
            del wxa, wya
            # turn of the tile (about Z) x turn of the piece; then up -> the normal of the surface (Follow the slope)
            q = _qmul(np.stack([np.cos(ang / 2), np.zeros_like(ang), np.zeros_like(ang), np.sin(ang / 2)], axis=1),
                      np.stack([trs[j, 6], trs[j, 3], trs[j, 4], trs[j, 5]], axis=1))
            if align and len(j):
                qa = np.stack([1.0 + nrm[:, 2], -nrm[:, 1], nrm[:, 0], np.zeros(len(j))], axis=1)
                qa /= np.linalg.norm(qa, axis=1)[:, None]
                q = _qmul(qa, q)
            out_i = idx[j]
            grow_ = np.ones(len(j))
            p_far = np.ones(len(j))
            p_all = np.ones(len(j))
            if view is not None and len(j):
                if FAR["d0"] > 0:
                    dd = np.maximum(np.hypot(wx - view.pos[0], wy - view.pos[1]), 1e-3)
                    p_far = np.minimum(1.0, (FAR["d0"] / dd) ** 2)
                # (1.76.42) the part kept with both thinnings (fall_total); the pieces kept bigger by as much (at most
                # FAR_GROW times), so the ground stays as covered - «Più rado in lontananza» lightens, it does not bare
                p_all = view.fall_total(p_far, view.fall_p(np.stack([wx, wy, z], axis=1), float(opts["camFalloff"])))
                grow_ = np.clip(1.0 / np.sqrt(np.maximum(p_all, 1e-9)), 1.0, FAR_GROW)
            out_t = np.stack([wx, wy, z + trs[j, 2] * grow_, q[:, 1], q[:, 2], q[:, 3], q[:, 0], trs[j, 7] * sc * grow_], axis=1)
            if view is not None and len(out_i):
                # the pieces the camera sees: at the foot, half way up or at the top (a crown behind a ridge)
                base = out_t[:, :3]
                hl = heights.get(li) if heights else None
                hh = hl[np.clip(out_i, 0, len(hl) - 1)] * out_t[:, 7] if hl is not None else np.zeros(len(out_i))
                up = np.zeros_like(base)
                up[:, 2] = hh
                seen = view.visible(base) | view.visible(base + up * 0.5) | view.visible(base + up)
                seen &= view.keep(base, float(opts["camFalloff"]), p_far, p_all)
                out_i, out_t = out_i[seen], out_t[seen]
            if len(out_i):
                out.append((li, out_i, out_t))
        return out

    heights, hmax, pre = {}, 0.0, {}
    CUT["far"] = 0.0
    dry, kh, khmax, far0 = None, None, 0.0, None
    if view is not None:
        # first without the models (no side effect: the count, for the memory and for the question of the app)
        # (with the heights when the models are already in the scene - making again: then the count is the one
        # that will be made; else at the ground, a little lower)
        kh, khmax = _known_heights(e, sc)
        dry = generate(kh, khmax) if kh is not None else generate(None, 0.0)
        far0 = (dict(FAR), dict(CUT))
        count = sum(len(o[1]) for o in dry)
        if d.get("dry"):
            # (the count only - for «Ricalcola dalla vista» and the estimate: nothing in the scene changes)
            mem = count * bpp
            return {"pieces": count, "max": mx, "memGB": round(mem / 1e9, 1), "freeGB": round(free / 1e9, 1),
                    "warn": count > WARN_PIECES or bool(free and mem > free * 0.3), "tooMany": count > mx,
                    "farCut": round(CUT["far"], 0), "thinPast": round(FAR["d0"], 0),
                    # (1.76.42) how much ground the pieces cover (the sum of their scale squared): for the tests
                    "cover": round(float(sum(float(np.sum(o[2][:, 7] ** 2)) for o in dry)), 1)}
        if not count:
            raise ApiError(tr("La camera non vede questa superficie: inquadrala e riprova, o metti l'ecosistema «Sempre intero» (nelle sue Avanzate)"))
        if count > mx:
            raise ApiError(tr("Troppi pezzi anche solo nell'inquadratura: circa {0} (il massimo è {1}). Abbassa la densità o avvicina la camera", num(count), num(mx)))
    # the old layers go (making again after a change: one undo step, the history of the app)
    group = old
    if group is not None:
        olds = [c for c in group.children if c.get(paint.PAINT_KEY) and not c.get("simpler_trashed")]
        trash.trash([o for c in olds for o in [c] + list(c.children_recursive)])
    else:
        group = link(bpy.data.objects.new(tr("Ecosistema") + " · " + e.get("name", ""), None))
        group.empty_display_size = 0.2
        group[KIND_KEY] = "group"
        new_id(group)
        _attach(group, ob)
    if view is not None:
        # the models (their height: a crown shows above a ridge that hides its trunk), then the pieces again
        from . import models as _models
        entries = _models._entries()
        for li, layer in enumerate(e["layers"]):
            lg = paint._new_group(layer.get("name") or "", "area")
            coll = paint._scatter_coll(lg)
            hs = []
            for mid in list(layer.get("models") or []):
                got = paint._ensure_original(coll, mid, entries.get(mid))
                hs.append(_height(got[0]) if got is not None else 1.0)
            trs_ = np.frombuffer(base64.b64decode(layer["trs"]), dtype=np.float32).reshape(-1, 8)
            smax = float(trs_[:, 7].max()) * sc if len(trs_) else sc
            hmax = max(hmax, max(hs or [1.0]) * smax)
            pre[li], heights[li] = lg, np.array(hs or [1.0])
    # (1.76.52, audit: 5 s of each ecosystem made again after a sculpting, Luca) the count above was already made
    # with the heights of the models in the scene: when the models loaded now have the same heights, the pieces are
    # those - not made a second time (the same tiles, the same random numbers: the same pieces)
    if dry is not None and kh is not None and khmax == hmax and set(kh) == set(heights) \
            and all(np.array_equal(kh[k], heights[k]) for k in heights):
        layers_out = dry
        FAR.update(far0[0]); CUT.update(far0[1])
        log("SIMPLER_ECO", "pieces as counted (the same heights): not made again")
    else:
        layers_out = generate(heights, hmax)
    for li in [k for k in pre if k not in {o[0] for o in layers_out}]:
        bpy.data.objects.remove(pre[li], do_unlink=True)
    made, pieces = [], 0
    for li, out_i, out_t in layers_out:
        layer = e["layers"][li]
        names = list(layer["models"])
        dd = {"group": "", "noPlot": True, "noRefresh": True, "name": tr("Ecosistema") + " · " + layer.get("name", ""), "strokes": [], "seed": int(opts["seed"]),
              "settings": dict(layer.get("settings") or {}, mode="area"), "area": None,
              "palette": layer.get("palette") or [{"model": m, "weight": 100} for m in names]}
        if li in pre:
            dd["group"] = pre[li].get(ID_KEY)
        r = paint._set_points(dd, names, out_i.astype(np.int32), out_t.astype(np.float64))
        lg = find(r["group"])
        lg[LAYER_KEY] = group.get(ID_KEY)
        lg.name = layer.get("name") or lg.name
        mw = _world_now(lg)
        lg.parent = group
        lg.matrix_parent_inverse = group.matrix_world.inverted()
        lg.matrix_world = mw
        made.append(lg)
        pieces += r["count"]
    refresh()                                   # (once for all the layers)
    if not pieces:
        if old is None:
            bpy.data.objects.remove(group, do_unlink=True)
        if view is not None:
            raise ApiError(tr("La camera non vede questa superficie: inquadrala e riprova, o metti l'ecosistema «Sempre intero» (nelle sue Avanzate)"))
        raise ApiError(tr("Sulla superficie non è caduto nessun pezzo: è più piccola del campione o la densità è troppo bassa"))
    st = {"id": eid, "name": e.get("name", ""), "target": tid, "slot": slot, "pieces": pieces,
          **{k: opts[k] for k in DEFAULTS}}
    if cam is not None:
        st["camView"] = cam
    group[ECO_KEY] = json.dumps(st)
    if own:
        group[OWN_KEY] = json.dumps(own)
    elif OWN_KEY in group:
        del group[OWN_KEY]
    _keep_def(eid, lib_e)
    refresh()
    return {"group": group.get(ID_KEY), "pieces": pieces, "layers": len(made), "eco": st}


def _world_now(o):
    """The place of o in the world without evaluating the whole scene when it can be read directly (an object without
    parent nor constraints: its own matrix) - each evaluation of the cathedral takes 0.5-1 s after objects are added."""
    if o.parent is None and not o.constraints:
        return o.matrix_basis.copy()
    refresh()
    return o.matrix_world.copy()


def _attach(group, ob):
    """The ecosystem becomes a child of the object it grows on (it keeps its place in the world): moving, turning or
    scaling the object takes the vegetation along, and copying or deleting it too (as the decals)."""
    mw = _world_now(group)
    group.parent = ob
    group.matrix_parent_inverse = ob.matrix_world.inverted()
    group.matrix_world = mw


def upgrade():
    """Projects of 1.38.0: the ecosystems were beside their object, not its children."""
    for g in [o for o in bpy.context.scene.objects if o.get(ECO_KEY) and o.parent is None]:
        try:
            ob = find(json.loads(g.get(ECO_KEY) or "{}").get("target"), required=False)
            if ob is not None and ob.type == "MESH" and not ob.get("simpler_trashed"):
                _attach(g, ob)
        except Exception as e:
            print("SIMPLER_ECO_UPGRADE", g.name, e, flush=True)


def info(d):
    """GET ecosystems/info?group= -> the settings of an ecosystem placed in the scene (for the panel)."""
    g = find(d.get("group"))
    while g is not None and not g.get(ECO_KEY):
        g = g.parent
    if g is None:
        raise ApiError(tr("Non è un ecosistema"))
    st = json.loads(g.get(ECO_KEY) or "{}")
    t = find(st.get("target"), required=False) if st.get("target") else None
    slot = st.get("slot")
    mat = ""
    if t is not None and slot is not None and 0 <= int(slot) < len(t.material_slots) and t.material_slots[int(slot)].material:
        mat = t.material_slots[int(slot)].material.name
    out = dict(DEFAULTS, **st)
    out.update(group=g.get(ID_KEY), targetName=t.name if t is not None else "", material=mat)
    try:
        lib = _read(st.get("id"))
        out["libSpill"], out["libSpillDensity"] = float(lib.get("spill", 0.0)), float(lib.get("spillDensity", DEFAULTS["spillDensity"]))
    except ApiError:
        out["libSpill"] = None
    # (its layers, for «Strati di questo ecosistema - solo in questo progetto»: as changed here, else as in the library)
    own = _own_of(g)
    out["own"] = bool(own)
    out["layers"] = []
    try:
        e, _eid = _read_placed(st.get("id"), st.get("name") or "")
    except ApiError:
        return out
    eff = _effective(e, own)
    for li, layer in enumerate(e.get("layers") or []):
        o = own["layers"][li] if own and li < len(own.get("layers") or []) and isinstance(own["layers"][li], dict) else {}
        pal = o.get("palette") if o.get("palette") is not None else list(_pal_of(layer).values())
        out["layers"].append({"name": layer.get("name") or "", "off": bool(o.get("off")), "density": float(o.get("density", 1.0)),
                              "pieces": int(eff["layers"][li].get("count") or 0) if li < len(eff["layers"]) else 0,
                              "palette": [dict(p) for p in pal]})
    return out


def save_own(d):
    """POST ecosystems/saveown {group, name, folder}: «Salva in libreria come nuovo» - the ecosystem placed here, with
    the layers changed in this project, becomes a new one of the library (its thumbnail: the one it came from)."""
    import shutil
    g = find(d.get("group"))
    while g is not None and not g.get(ECO_KEY):
        g = g.parent
    if g is None:
        raise ApiError(tr("Non è un ecosistema"))
    st = json.loads(g.get(ECO_KEY) or "{}")
    e, src = _read_placed(st.get("id"), st.get("name") or "")
    eff = _effective(e, _own_of(g))
    layers = [l for l in eff["layers"] if int(l.get("count") or 0) > 0]
    if not layers:
        raise ApiError(tr("Niente da salvare: tutti gli strati sono spenti o senza modelli"))
    name = (d.get("name") or "").strip() or tr("Ecosistema")
    eid = "e_" + uuid.uuid4().hex[:10]
    p = os.path.join(root(), eid)
    os.makedirs(p, exist_ok=True)
    new = {k: v for k, v in eff.items() if k not in ("layers", "edited")}
    new.update(version=1, name=name, layers=layers, created=time.strftime("%Y-%m-%d %H:%M"), folder=_clean(d.get("folder")))
    _write(eid, new)
    for t in ("thumb.png", "thumb.jpg"):
        try:
            shutil.copyfile(os.path.join(_dir(src), t), os.path.join(p, t))
        except (OSError, ApiError):
            pass
    if new["folder"]:
        _save_folders(_folders() + [new["folder"]])
    return {"id": eid, "name": name, "layers": len(layers), "pieces": sum(int(l["count"]) for l in layers)}
