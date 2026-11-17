"""Where Simpler keeps the files it downloads and the user's libraries - and how projects find them again.

Four places, each with a default and a folder the user can choose (Impostazioni > Cartelle):
    phTextures  Poly Haven materials (downloaded textures)   %LOCALAPPDATA%\\Simpler\\library\\polyhaven
    phModels    Poly Haven 3D models                          %LOCALAPPDATA%\\Simpler\\library\\polyhaven\\models
    models      the user's library of 3D models               %APPDATA%\\Simpler\\models
    materials   the user's library of materials               %APPDATA%\\Simpler\\materials
The choice is kept in %APPDATA%\\Simpler\\paths.json, with every folder used before ("history").

Projects do not depend on where a library is: when a project is saved, each texture coming from one of these
places is tagged with the place ("simpler_root") and its path inside it ("simpler_rel") - a variable, in effect.
When the project is opened the texture is looked for in the place as it is NOW. Older projects (without the tag)
and the library files themselves (which store full paths) are rebased the same way: a path under an old folder
of a place (or its default) is moved to the current folder.
"""
import json
import os
import shutil
import tempfile

# (1.78.2) «ecosystems» (before: always next to the models library - moving the models left them behind) and
# «decals» (the user's decals, before: always in %APPDATA%) can be moved like the others
KEYS = ("phTextures", "phModels", "models", "ecosystems", "materials", "decals")
ROOT_TAG, REL_TAG = "simpler_root", "simpler_rel"


def _appdata():
    return os.environ.get("APPDATA") or os.environ.get("LOCALAPPDATA") or tempfile.gettempdir()


def _localappdata():
    return os.environ.get("LOCALAPPDATA") or tempfile.gettempdir()


def defaults():
    ph = os.path.join(_localappdata(), "Simpler", "library", "polyhaven")
    return {"phTextures": ph, "phModels": os.path.join(ph, "models"),
            "models": os.path.join(_appdata(), "Simpler", "models"),
            "ecosystems": os.path.join(_appdata(), "Simpler", "ecosystems"),
            "materials": os.path.join(_appdata(), "Simpler", "materials"),
            "decals": os.path.join(_appdata(), "Simpler", "decals")}


_MADE = set()          # (1.76.50) folders already made in this session: not asked to the disk again
_CACHE = {"key": None, "data": None}


def _config_file():
    d = os.path.join(_appdata(), "Simpler")
    if d not in _MADE:
        os.makedirs(d, exist_ok=True)
        _MADE.add(d)
    return os.path.join(d, "paths.json")


def _load():
    """The settings of the folders. (1.76.50) read again only when the file changed: the library asked for them once
    per model - 400 reads and 800 «make this folder» at every listing (3 s at the start, Luca's log)."""
    p = _config_file()
    try:
        st = os.stat(p)
        key = (st.st_mtime_ns, st.st_size)
    except OSError:
        key = None
    if key is not None and _CACHE["key"] == key and _CACHE["data"] is not None:
        return json.loads(json.dumps(_CACHE["data"]))
    try:
        with open(p, encoding="utf-8") as f:
            d = json.load(f)
    except (OSError, ValueError):
        d = {}
    d.setdefault("current", {})
    d.setdefault("history", {})
    _CACHE.update(key=key, data=json.loads(json.dumps(d)))
    return d


def _save(d):
    p = _config_file()
    with open(p + ".part", "w", encoding="utf-8") as f:
        json.dump(d, f, indent=1)
    os.replace(p + ".part", p)


def get(key):
    """Current folder of a place (created if missing)."""
    d = _load()
    path = d["current"].get(key)
    if not path and key == "ecosystems":
        # (1.78.2) where they always were: next to the models library as it is now - kept from here on, so that
        # moving the models does not leave them behind any more
        path = os.path.join(os.path.dirname(os.path.normpath(d["current"].get("models") or defaults()["models"])), "ecosystems")
        d["current"]["ecosystems"] = path        # (kept even when it is the default: it must not follow the models)
        try:
            _save(d)
            _CACHE.update(key=None, data=None)
        except OSError:
            pass
    path = path or defaults()[key]
    if path not in _MADE or not os.path.isdir(path):
        try:
            os.makedirs(path, exist_ok=True)
            _MADE.add(path)
        except OSError:
            pass
    return path


def _norm(p):
    return os.path.normcase(os.path.normpath(os.path.abspath(p))) if p else ""


def _under(path, root):
    """Path of `path` inside `root` (with /), or None."""
    np, nr = _norm(path), _norm(root)
    if not nr or not np:
        return None
    if np == nr:
        return ""
    if np.startswith(nr.rstrip("\\/") + os.sep):
        return os.path.normpath(os.path.abspath(path))[len(os.path.normpath(os.path.abspath(root)).rstrip("\\/")) + 1:].replace("\\", "/")
    return None


def _all_roots(key, d=None):
    """Every folder this place has had: current first, then the older ones and the default."""
    d = d or _load()
    out = [get(key)] + list(d["history"].get(key, [])) + [defaults()[key]]
    seen, res = set(), []
    for r in out:
        if r and _norm(r) not in seen:
            seen.add(_norm(r))
            res.append(r)
    return res


def locate(path):
    """(key, rel) of a file that is (or was) inside one of the places, else (None, None). The most specific place
    wins (Poly Haven models live inside the Poly Haven folder by default)."""
    d = _load()
    best = (None, None, -1)
    for key in KEYS:
        for root in _all_roots(key, d):
            rel = _under(path, root)
            if rel is not None and len(_norm(root)) > best[2]:
                best = (key, rel, len(_norm(root)))
    return best[0], best[1]


def resolve(path):
    """A file stored with a full path (library json files): where it is now. Unchanged if it exists or is unknown."""
    if not path or os.path.isfile(path):
        return path
    key, rel = locate(path)
    if key is None:
        return path
    cand = os.path.join(get(key), *rel.split("/")) if rel else get(key)
    return cand if os.path.exists(cand) else path


# ---------------------------------------------------------------- projects

def tag_images():
    """Before saving a project: every texture from a library or a download remembers its place and its path in it."""
    import bpy
    for im in bpy.data.images:
        if im.source not in ("FILE", "TILED") or not im.filepath or im.get("simpler_proxy"):
            continue
        absf = bpy.path.abspath(im.filepath)
        key, rel = locate(absf)
        if key is not None and rel:
            im[ROOT_TAG], im[REL_TAG] = key, rel
        else:
            for tag in (ROOT_TAG, REL_TAG):
                if tag in im:
                    del im[tag]


def remap_images():
    """After opening a project: textures of a library or a download are taken from the place's current folder."""
    import bpy
    moved = 0
    for im in bpy.data.images:
        if im.source not in ("FILE", "TILED") or not im.filepath:
            continue
        cur = bpy.path.abspath(im.filepath)
        key, rel = im.get(ROOT_TAG), im.get(REL_TAG)
        if not (key in KEYS and rel):
            if os.path.isfile(cur):
                continue
            key, rel = locate(cur)                    # older project: rebase by the old folders
            if key is None or not rel:
                continue
        cand = os.path.join(get(key), *str(rel).split("/"))
        if _norm(cand) != _norm(cur) and os.path.isfile(cand):
            im.filepath = cand
            moved += 1
    return moved


# ---------------------------------------------------------------- API

LABELS = {"phTextures": "Download: texture di Poly Haven, HDRI, decal di ambientCG", "phModels": "Modelli 3D Poly Haven",
          "models": "Libreria Modelli 3D e vegetazione", "ecosystems": "Ecosistemi", "materials": "Libreria Materiali",
          "decals": "Le mie decal"}


def _size(path, limit=200000):
    total, n = 0, 0
    for base, _dirs, files in os.walk(path):
        for f in files:
            try:
                total += os.path.getsize(os.path.join(base, f))
            except OSError:
                pass
            n += 1
            if n > limit:
                return total
    return total


def api_list(_data=None):
    from .i18n import tr
    d = _load()
    df = defaults()
    return {"folders": [{"key": k, "label": tr(LABELS[k]), "path": get(k), "default": df[k],
                         "isDefault": _norm(get(k)) == _norm(df[k])} for k in KEYS]}


def api_size(data):
    return {"key": data.get("key"), "bytes": _size(get(data.get("key")))}


def _check_target(key, new):
    from .core import ApiError
    from .i18n import tr
    old = get(key)
    if _norm(new) == _norm(old):
        raise ApiError(tr("È già la cartella in uso"))
    if _under(new, old) is not None:
        raise ApiError(tr("La nuova cartella non può stare dentro quella attuale"))
    if _under(old, new) is not None:
        raise ApiError(tr("La nuova cartella non può contenere quella attuale"))
    try:
        os.makedirs(new, exist_ok=True)
        probe = os.path.join(new, ".simpler_write_test")
        with open(probe, "w") as f:
            f.write("ok")
        os.remove(probe)
    except OSError as exc:
        raise ApiError(tr("Non posso scrivere nella cartella {0}: {1}", new, exc.strerror or str(exc))) from exc
    return old


def api_check(data):
    """POST paths/check {key, path}: can the folder be used? Is it empty? How much is in the current one?"""
    key, new = data.get("key"), os.path.normpath(os.path.abspath((data.get("path") or "").strip() or defaults()[data.get("key")]))
    if key not in KEYS:
        from .core import ApiError
        from .i18n import tr
        raise ApiError(tr("Cartella sconosciuta"))
    old = _check_target(key, new)
    n, total = _count(old, [get(k) for k in KEYS if k != key])
    return {"path": new, "old": old, "empty": not any(os.scandir(new)), "files": n, "bytes": total}


def _count(path, skip=()):
    n, total = 0, 0
    skip = {_norm(x) for x in skip}
    for base, dirs, files in os.walk(path):
        dirs[:] = [x for x in dirs if _norm(os.path.join(base, x)) not in skip]
        for f in files:
            n += 1
            try:
                total += os.path.getsize(os.path.join(base, f))
            except OSError:
                pass
    return n, total


def api_set(data):
    """POST paths/set {key, path ("" = default)}: from now on the place is in this folder. Every place is
    independent: another place living inside the old folder (Poly Haven models inside Poly Haven materials, by
    default) stays where it is."""
    from .core import ApiError
    from .i18n import tr
    key = data.get("key")
    if key not in KEYS:
        raise ApiError(tr("Cartella sconosciuta"))
    new = os.path.normpath(os.path.abspath((data.get("path") or "").strip() or defaults()[key]))
    old = get(key)
    if _norm(new) == _norm(old):
        return api_list()
    d = _load()
    d["history"].setdefault(key, [])
    if _norm(old) not in {_norm(x) for x in d["history"][key]}:
        d["history"][key].insert(0, old)
    d["current"][key] = new
    _save(d)
    _reset_caches()
    return api_list()


# ---------------------------------------------------------------- copy to a new folder (background, with progress)

import threading
_job = {"state": "idle", "kind": "", "done": 0, "total": 0, "bytes": 0, "totalBytes": 0, "current": "", "error": "",
        "cancel": False, "failed": []}
_job_lock = threading.Lock()


def api_status(_data=None):
    with _job_lock:
        return {k: v for k, v in _job.items() if k != "cancel"}


def api_cancel(_data=None):
    with _job_lock:
        _job["cancel"] = True
    return api_status()


def _start_job(kind, target):
    from .core import ApiError
    from .i18n import tr
    with _job_lock:
        if _job["state"] == "running":
            raise ApiError(tr("Un'altra operazione sulle cartelle è in corso"))
        _job.update(state="running", kind=kind, done=0, total=0, bytes=0, totalBytes=0, current="", error="", cancel=False, failed=[])
    threading.Thread(target=target, daemon=True).start()
    return api_status()


def api_copy(data):
    """POST paths/copy {key, path}: copies everything of the place (all subfolders) into the new, empty folder, then
    checks every file (same size). The place is NOT switched here: the app does it (paths/set) when the
    copy reports "done", so a failed or cancelled copy changes nothing."""
    key = data.get("key")
    new = os.path.normpath(os.path.abspath((data.get("path") or "").strip()))
    old = _check_target(key, new)

    def run():
        from .i18n import tr
        try:
            # folders of other places inside this one (Poly Haven models in Poly Haven materials) are not copied
            others = [_norm(get(k)) for k in KEYS if k != key and _under(get(k), old) not in (None, "")]
            files = []
            for base, dirs, names in os.walk(old):
                dirs[:] = [x for x in dirs if _norm(os.path.join(base, x)) not in others]
                for n in names:
                    f = os.path.join(base, n)
                    try:
                        files.append((f, os.path.getsize(f)))
                    except OSError:
                        pass
            with _job_lock:
                _job["total"], _job["totalBytes"] = len(files), sum(sz for _f, sz in files)
            for f, sz in files:
                with _job_lock:
                    if _job["cancel"]:
                        _job["state"], _job["error"] = "cancelled", ""
                        return
                    _job["current"] = os.path.relpath(f, old)
                dst = os.path.join(new, os.path.relpath(f, old))
                os.makedirs(os.path.dirname(dst), exist_ok=True)
                if not (os.path.isfile(dst) and os.path.getsize(dst) == sz):
                    shutil.copy2(f, dst + ".part")
                    os.replace(dst + ".part", dst)
                with _job_lock:
                    _job["done"] += 1
                    _job["bytes"] += sz
            # empty subfolders too (a library folder without models yet)
            for base, dirs, _names in os.walk(old):
                dirs[:] = [x for x in dirs if _norm(os.path.join(base, x)) not in others]
                for dname in dirs:
                    os.makedirs(os.path.join(new, os.path.relpath(os.path.join(base, dname), old)), exist_ok=True)
            with _job_lock:
                _job["current"] = tr("Verifica della copia")
            failed = [os.path.relpath(f, old) for f, sz in files
                      if not os.path.isfile(os.path.join(new, os.path.relpath(f, old)))
                      or os.path.getsize(os.path.join(new, os.path.relpath(f, old))) != sz]
            with _job_lock:
                _job["failed"] = failed[:20]
                if failed:
                    _job["state"], _job["error"] = "error", tr("{0} file non sono stati copiati correttamente", len(failed))
                else:
                    _job["state"], _job["current"] = "done", ""
        except Exception as exc:
            with _job_lock:
                _job["state"], _job["error"] = "error", str(exc)

    return _start_job("copy", run)


def api_delete_old(data):
    """POST paths/deleteold {path}: removes a folder a place used before (after a verified copy). Only folders
    in the history of a place, never the current one of any place."""
    from .core import ApiError
    from .i18n import tr
    target = os.path.normpath(os.path.abspath(data.get("path") or ""))
    d = _load()
    known = {_norm(x) for k in KEYS for x in d["history"].get(k, [])}
    if _norm(target) not in known:
        raise ApiError(tr("Questa cartella non è una vecchia cartella di Simpler"))
    owners = {k for k in KEYS if _norm(target) in {_norm(x) for x in d["history"].get(k, [])}}
    for k in KEYS:
        rel = _under(target, get(k))
        # never a folder in use; inside a place in use only when it was the folder of ANOTHER place
        # (Poly Haven models that lived inside the Poly Haven materials folder)
        if rel == "" or (rel is not None and not (owners - {k})):
            raise ApiError(tr("La cartella {0} è ancora in uso", target))
    # places in use that live inside the old folder (e.g. Poly Haven models): kept, with everything in them
    keep = [_norm(get(k)) for k in KEYS if _under(get(k), target) not in (None, "")]

    def run():
        try:
            entries = []
            for base, dirs, names in os.walk(target):
                dirs[:] = [x for x in dirs if _norm(os.path.join(base, x)) not in keep]
                entries += [os.path.join(base, n) for n in names]
            with _job_lock:
                _job["total"] = len(entries)
            for f in entries:
                try:
                    os.remove(f)
                except OSError:
                    pass
                with _job_lock:
                    _job["done"] += 1
                    _job["current"] = os.path.relpath(f, target)
            # empty folders go away, deepest first (the kept places stay, and so the folders above them)
            for base, dirs, names in sorted(os.walk(target), key=lambda t: -len(t[0])):
                if any(_norm(base) == k or _norm(base).startswith(k + os.sep) for k in keep):
                    continue
                try:
                    os.rmdir(base)
                except OSError:
                    pass
            left = [f for f in entries if os.path.exists(f)]
            with _job_lock:
                _job["state"] = "done" if not left else "error"
                _job["error"] = "" if not left else tr("Alcuni file non si possono eliminare (in uso?)")
        except Exception as exc:
            with _job_lock:
                _job["state"], _job["error"] = "error", str(exc)

    return _start_job("delete", run)


def _reset_caches():
    from . import library, materials, phmodels
    materials._user_cache["stamp"] = None
    library._list["assets"] = None
    phmodels._list["assets"] = None
