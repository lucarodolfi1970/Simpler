"""Poly Haven texture library (https://polyhaven.com, CC0 assets, public API at api.polyhaven.com).

The list of textures and their thumbnails are downloaded once and kept in %LOCALAPPDATA%\\Simpler\\library\\polyhaven
(refreshed every week); the maps of a texture are downloaded the first time it is used (2K JPG/PNG, a few tens of MB)
and stay on disk for every project. Applying a texture creates a Simpler material (matedit.py) with colour, roughness,
metallic, normal and height maps, box projection at the real size of the scanned surface.

API terms (https://github.com/Poly-Haven/Public-API/blob/master/ToS.md): free, also commercially; every call carries a
user agent naming the app; the app shows that the content comes from Poly Haven (the library tab is called
"Texture Poly Haven"). Everything here except apply() runs on background threads and never touches bpy.
"""
import json
import os
import tempfile
import threading
import time
import urllib.request

API = "https://api.polyhaven.com"
USER_AGENT = "Simpler/{0} (photorealistic still renderer; contact via polyhaven attribution in app)"
RES_ORDER = ("2k", "1k", "4k")
REFRESH_DAYS = 7

_lock = threading.RLock()        # (re-entrant: download() answers with status() while holding it)
_jobs = {}            # id -> {"state": "running|done|error", "done": n, "total": n, "error": ""}
_list = {"assets": None, "loading": False, "error": ""}
_thumbs = {"running": False}


def _ua():
    from . import VERSION
    return USER_AGENT.format(VERSION)


def root():
    from . import paths
    return paths.get("phTextures")       # chosen by the user in Impostazioni > Cartelle (default: LOCALAPPDATA)


def _get(url, timeout=30):
    req = urllib.request.Request(url, headers={"User-Agent": _ua()})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read()


def _download(url, path, progress=None, tries=3, timeout=45):
    """Downloads url to path (through path.part). progress(bytes) is called as data arrives. A connection that
    stops sending for `timeout` seconds, or an error, is retried `tries` times (after 2, 5 s); then it raises."""
    last = None
    for attempt in range(tries):
        if attempt:
            time.sleep((2, 5, 10)[min(attempt - 1, 2)])
        tmp = path + ".part"
        got = 0
        try:
            req = urllib.request.Request(url, headers={"User-Agent": _ua()})
            with urllib.request.urlopen(req, timeout=timeout) as r, open(tmp, "wb") as f:
                while True:
                    chunk = r.read(1 << 18)
                    if not chunk:
                        break
                    f.write(chunk)
                    got += len(chunk)
                    if progress:
                        progress(len(chunk))
            os.replace(tmp, path)
            return
        except Exception as exc:            # network error, timeout, disk: try again from the start of the file
            last = exc
            if progress and got:
                progress(-got)
            try:
                os.remove(tmp)
            except OSError:
                pass
    raise RuntimeError(explain(last) + f" ({os.path.basename(path)})")


def explain(exc):
    """The reason of a failed download in words the user understands (what to do about it is in the app)."""
    from .i18n import tr
    import socket
    import urllib.error
    text = str(exc)
    if isinstance(exc, urllib.error.HTTPError):
        if exc.code == 404:
            return tr("il file non è più disponibile su Poly Haven")
        if exc.code in (429, 503):
            return tr("Poly Haven è sovraccarico in questo momento (errore {0})", exc.code)
        return tr("Poly Haven ha risposto con un errore ({0})", exc.code)
    if isinstance(exc, (socket.timeout, TimeoutError)) or "timed out" in text:
        return tr("Poly Haven non risponde: connessione lenta o interrotta")
    if isinstance(exc, urllib.error.URLError):
        reason = str(getattr(exc, "reason", ""))
        if "getaddrinfo" in reason or "Name or service" in reason or "11001" in reason:
            return tr("nessuna connessione a Internet (polyhaven.com non raggiungibile)")
        if "CERTIFICATE" in reason.upper() or "SSL" in reason.upper():
            return tr("connessione sicura rifiutata (proxy o antivirus che filtra HTTPS?)")
        return tr("connessione non riuscita: {0}", reason)
    if isinstance(exc, OSError) and getattr(exc, "errno", None) in (28, 13):
        return tr("impossibile scrivere sul disco (spazio esaurito o permessi)")
    return text


# ---------------------------------------------------------------- list of textures

def _list_file():
    return os.path.join(root(), "assets.json")


def _load_list():
    """Assets from the cache, refreshed in the background when older than a week."""
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
        data = json.loads(_get(API + "/assets?type=textures", timeout=60))
        out = []
        for aid, a in data.items():
            dims = a.get("dimensions") or []
            out.append({"id": aid, "name": a.get("name", aid), "category": a.get("category") or ", ".join(a.get("categories", [])[:2]),
                        "categories": list(a.get("categories") or []),
                        "thumb": a.get("thumbnail_url", ""), "sizeMm": dims[0] if dims else 0,
                        "downloads": a.get("download_count", 0)})
        out.sort(key=lambda a: -a["downloads"])
        with open(_list_file() + ".part", "w", encoding="utf-8") as f:
            json.dump(out, f)
        os.replace(_list_file() + ".part", _list_file())
        _list["assets"] = out
        _list["error"] = ""
    except Exception as exc:          # offline: the cached list (if any) stays
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
                small = a["thumb"].replace("width=256", "width=128").replace("height=256", "height=128")
                for url in (small.replace("format=webp", "format=png"), small):   # PNG for every Windows; WebP as a fallback
                    try:
                        _download(url, path, tries=1)
                        break
                    except Exception:
                        continue
        finally:
            _thumbs["running"] = False
    threading.Thread(target=run, daemon=True).start()


# Poly Haven gives each texture a category path ("Wood/Boards & Planks/Parquet"): the library shows it as nested folders,
# two levels deep (the first one translated). Older lists without a path: grouped by their tags.
TOP_FOLDERS = {
    "Brick & Block": "Mattoni e blocchi", "Concrete": "Cemento e intonaco", "Wood": "Legno", "Stone": "Pietra",
    "Ceramic": "Ceramica", "Ground & Terrain": "Terreno", "Asphalt & Bitumen": "Asfalto", "Metal": "Metallo",
    "Textiles & Leather": "Tessuti e pelle", "Organic": "Organici", "Plastic & Rubber": "Plastica e gomma", "Paper & Card": "Carta",
}
TAG_FOLDERS = [
    ("wood", "Wood"), ("brick", "Brick & Block"), ("tiles", "Ceramic"), ("marble", "Stone"), ("cobblestone", "Stone"),
    ("concrete", "Concrete"), ("plaster-concrete", "Concrete"), ("plaster", "Concrete"), ("asphalt", "Asphalt & Bitumen"),
    ("road", "Asphalt & Bitumen"), ("metal", "Metal"), ("fabric", "Textiles & Leather"), ("leather", "Textiles & Leather"),
    ("rock", "Stone"), ("stone", "Stone"), ("sand", "Ground & Terrain"), ("snow", "Ground & Terrain"), ("terrain", "Ground & Terrain"),
]


def folder_for(category, tags=()):
    from .i18n import tr
    parts = [p.strip() for p in str(category or "").split("/") if p.strip()]
    if len(parts) > 1 or (parts and parts[0] in TOP_FOLDERS):
        parts = parts[:2]
        parts[0] = tr(TOP_FOLDERS.get(parts[0], parts[0]))
        return "/".join(p.replace("/", "-") for p in parts)
    cats = [str(c).strip().lower() for c in list(tags or []) + str(category or "").split(", ") if str(c).strip()]
    for key, top in TAG_FOLDERS:
        if key in cats:
            return tr(TOP_FOLDERS[top])
    return tr("Altro")


def list_assets(_data=None):
    _load_list()
    _start_thumbs()
    assets = _list["assets"] or []
    return {"assets": [dict(a, folder=folder_for(a.get("category"), a.get("categories")), hasThumb=os.path.isfile(_thumb_path(a["id"])),
                            downloaded=os.path.isfile(os.path.join(root(), a["id"], "maps.json"))) for a in assets],
            "loading": _list["loading"], "error": _list["error"], "credit": "Poly Haven (polyhaven.com) · CC0"}


def thumb_file(aid):
    path = _thumb_path(os.path.basename(aid or ""))
    return path if os.path.isfile(path) else None


# ---------------------------------------------------------------- maps of a texture

# Poly Haven map names -> Simpler channel; first match wins
MAP_KEYS = [
    ("color", ("Diffuse", "diff", "Color", "col", "albedo")),
    ("normal", ("nor_gl", "Normal", "nor")),
    ("roughness", ("Rough", "rough", "roughness")),
    ("metallic", ("Metal", "metal", "metallic")),
    ("height", ("Displacement", "disp", "height", "Bump")),
    ("alpha", ("alpha", "Alpha", "opacity", "mask")),
    ("arm", ("arm", "ARM")),
]


def _pick_files(files):
    """Chosen file (url, extension) for each channel, from the /files answer."""
    chosen = {}
    lower = {k.lower(): k for k in files}
    for channel, names in MAP_KEYS:
        for n in names:
            key = lower.get(n.lower())
            if key is None or not isinstance(files.get(key), dict):
                continue
            by_res = files[key]
            for res in RES_ORDER:
                fmts = by_res.get(res)
                if not isinstance(fmts, dict):
                    continue
                order = ("png", "jpg") if channel in ("height", "alpha") else ("jpg", "png")
                for fmt in order:
                    if isinstance(fmts.get(fmt), dict) and fmts[fmt].get("url"):
                        chosen[channel] = (fmts[fmt]["url"], fmt, fmts[fmt].get("size", 0))
                        break
                if channel in chosen:
                    break
            if channel in chosen:
                break
    if "color" not in chosen:
        # (22/11) textures sold in colour variants have no single colour map: col_1, col_2... (fabric_pattern_05, _07 -
        # «no colour map» before); the first variant is the colour
        for key in sorted(k for k in files if k.lower().startswith(("col_", "diff_", "diffuse_")) and isinstance(files.get(k), dict)):
            by_res = files[key]
            for res in RES_ORDER:
                fmts = by_res.get(res)
                if not isinstance(fmts, dict):
                    continue
                for fmt in ("jpg", "png"):
                    if isinstance(fmts.get(fmt), dict) and fmts[fmt].get("url"):
                        chosen["color"] = (fmts[fmt]["url"], fmt, fmts[fmt].get("size", 0))
                        break
                if "color" in chosen:
                    break
            if "color" in chosen:
                break
    return chosen


def download(data):
    """Starts downloading the maps of a texture (background). GET library/status tells when it is ready."""
    aid = os.path.basename(data.get("id") or "")
    if not aid:
        return {"state": "error", "error": "id"}
    folder = os.path.join(root(), aid)
    if os.path.isfile(os.path.join(folder, "maps.json")):
        return {"id": aid, "state": "done", "fraction": 1.0}
    with _lock:
        job = _jobs.get(aid)
        _watchdog(job)
        if job and job["state"] == "running":
            return status({"id": aid})
        _jobs[aid] = {"state": "running", "done": 0, "total": 0, "error": "", "started": time.time(), "seen": time.time()}

    def advance(n):
        with _lock:
            _jobs[aid]["done"] += n
            _jobs[aid]["seen"] = time.time()

    def run():
        try:
            os.makedirs(folder, exist_ok=True)
            files = json.loads(_get(f"{API}/files/{aid}"))
            chosen = _pick_files(files)
            if "color" not in chosen:
                raise RuntimeError("no colour map")
            with _lock:
                _jobs[aid]["total"] = sum(max(1, c[2]) for c in chosen.values())
            maps = {}
            for channel, (url, fmt, size) in chosen.items():
                path = os.path.join(folder, f"{channel}.{fmt}")
                if not os.path.isfile(path):
                    _download(url, path, advance)
                else:
                    advance(max(1, size))
                maps[channel] = path
            with open(os.path.join(folder, "maps.json"), "w", encoding="utf-8") as f:
                json.dump(maps, f)
            with _lock:
                _jobs[aid]["state"] = "done"
        except Exception as exc:
            with _lock:
                _jobs[aid].update(state="error", error=str(exc) if isinstance(exc, RuntimeError) else explain(exc))
    threading.Thread(target=run, daemon=True).start()
    return status({"id": aid})


STALL_S = 150          # no data for this long: the download is given up (a new click starts it again)


def _watchdog(job):
    """A job that stopped moving is marked as failed: it does not hold the slot forever."""
    if job and job.get("state") == "running" and time.time() - job.get("seen", time.time()) > STALL_S:
        from .i18n import tr
        job.update(state="error", error=tr("nessun dato da Poly Haven da oltre due minuti"))


def status(data):
    aid = os.path.basename(data.get("id") or "")
    if os.path.isfile(os.path.join(root(), aid, "maps.json")):
        return {"id": aid, "state": "done", "fraction": 1.0}
    with _lock:
        job = _jobs.get(aid)
        _watchdog(job)
        job = dict(job or {"state": "none", "done": 0, "total": 0, "error": ""})
    job["id"] = aid
    job["fraction"] = job["done"] / job["total"] if job.get("total") else None
    return job


def apply(data):
    """Material from a downloaded texture, assigned to objects (ids; slot optional). Runs on the main thread."""
    import bpy
    from . import matedit
    from .core import ApiError, find, tree_kids
    from .i18n import tr
    aid = os.path.basename(data.get("id") or "")
    mfile = os.path.join(root(), aid, "maps.json")
    if not os.path.isfile(mfile):
        raise ApiError(tr("Texture non ancora scaricata"))
    with open(mfile, encoding="utf-8") as f:
        maps = json.load(f)
    from . import paths
    maps = {k: paths.resolve(v) if isinstance(v, str) else v for k, v in maps.items()}   # the folder may have moved
    info = next((a for a in (_list["assets"] or []) if a["id"] == aid), {})
    name = "PH · " + (info.get("name") or aid)
    mat = bpy.data.materials.get(name)
    if mat is None or not matedit.params_of(mat):
        mat = mat or bpy.data.materials.new(name)

        def img(channel):
            path = maps.get(channel)
            if not path or not os.path.isfile(path):
                return {"image": ""}
            im = bpy.data.images.load(path, check_existing=True)
            im.name = f"{aid}_{channel}"           # every texture has color.jpg, normal.jpg...: readable names
            return {"image": im.name}
        size_cm = (info.get("sizeMm") or 0) / 10.0 or 100.0
        params = {
            "color": {"tint": [1.0, 1.0, 1.0], "map": img("color")},
            "roughness": {"value": 0.7, "map": dict(img("roughness"), strength=1.0)},
            "metallic": {"value": 0.0, "map": dict(img("metallic"), strength=1.0)},
            "normal": {"map": img("normal"), "strength": 1.0, "directx": False},
            "displacement": {"enabled": False, "map": img("height"), "heightCm": max(0.2, min(5.0, size_cm / 100.0)), "midlevel": 0.5},
            "uv": {"mode": "box", "space": "object", "sizeCm": size_cm, "blend": 0.15},
        }
        if not params["roughness"]["map"]["image"] and maps.get("arm"):
            arm_im = bpy.data.images.load(maps["arm"], check_existing=True)
            arm_im.name = f"{aid}_arm"
            arm = arm_im.name
            params["roughness"]["map"] = {"image": arm, "channel": "G", "strength": 1.0}
            params["metallic"]["map"] = {"image": arm, "channel": "B", "strength": 1.0}
        if maps.get("alpha"):
            params["opacity"] = {"map": img("alpha")}
        mat["simpler_source"] = "polyhaven:" + aid
        matedit.apply(mat, params)
    count = 0
    stack = [find(i) for i in data.get("ids") or []]
    kids = tree_kids(stack)                    # (Object.children per piece: seconds on big models)
    slot = data.get("slot")
    while stack:
        ob = stack.pop()
        stack.extend(kids.get(ob, ()))
        if ob.type != "MESH":
            continue
        if not ob.material_slots:
            ob.data.materials.append(None)
        slots = range(len(ob.material_slots)) if slot is None else [int(slot)]
        for i in slots:
            if 0 <= i < len(ob.material_slots):
                ob.material_slots[i].link = "OBJECT"
                ob.material_slots[i].material = mat
                count += 1
    return {"material": mat.name, "assigned": count}
