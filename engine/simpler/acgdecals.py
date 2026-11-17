"""ambientCG decals (https://ambientcg.com, CC0): the "Decal" menu of the library.

ambientCG has no menu of its own for decals on its site (they are among the "Surfaces"), but its API lists them as
asset type "Decal": road lines, leaks, manhole covers, paving edges, doors, tyre tracks... (127 in October 2026).
Each one is a full PBR set: colour, opacity (a separate map, not the alpha of the colour), normal, roughness,
metalness, plus displacement and AO (not used), and its real size in centimetres (dimensionX, dimensionY).

The list is cached for a week in <Poly Haven folder>/ambientcg/decals.json, the thumbnails next to it. A decal is
downloaded once (the 1K JPG zip), unpacked into its own folder, and then placed like a personal decal (decals.add with
its maps and its real size). Network and files only: answered by the server thread at once, like library.py.
"""
import io
import json
import os
import threading
import time
import zipfile

from . import library

API = "https://ambientcg.com/api/v2/full_json?type=Decal&limit=500&include=downloadData,displayData,dimensionsData,tagData,mapData"
RES = "1K-JPG"
REFRESH_DAYS = 7
MAPS = {          # ambientCG map name in the file -> channel of the decal
    "Color": "color", "Opacity": "opacity", "NormalGL": "normal", "Roughness": "roughness", "Metalness": "metalness",
}

_lock = threading.RLock()
_list = {"assets": None, "loading": False, "error": ""}
_thumbs = {"running": False}
_jobs = {}


def root():
    d = os.path.join(library.root(), "ambientcg")
    os.makedirs(d, exist_ok=True)
    return d


def _family(aid):
    """ManholeCover011 -> ManholeCover (the folder of the library)."""
    base = aid.rstrip("ABCDEFGHIJKLMNOPQRSTUVWXYZ") if aid[-1:].isalpha() and aid[-2:-1].isdigit() else aid
    return base.rstrip("0123456789") or aid


FAMILIES = {      # folder names in Italian (translated where shown)
    "RoadLines": "Segnaletica stradale", "Leaking": "Colature", "ManholeCover": "Tombini", "PavingEdge": "Cordoli",
    "Door": "Porte", "ChewingGum": "Gomme da masticare", "AsphaltDamage": "Asfalto rovinato", "TireTracks": "Tracce di pneumatici",
}


def _list_file():
    return os.path.join(root(), "decals.json")


def _refresh():
    try:
        data = json.loads(library._get(API, timeout=60))
        out = []
        for a in data.get("foundAssets") or []:
            aid = a.get("assetId") or ""
            if not aid:
                continue
            zips = (((a.get("downloadFolders") or {}).get("default") or {}).get("downloadFiletypeCategories") or {}).get("zip") or {}
            dl = next((d for d in zips.get("downloads") or [] if d.get("attribute") == RES), None)
            prev = a.get("previewImage") or {}
            out.append({"id": aid, "name": a.get("displayName") or aid, "family": _family(aid),
                        "w": float(a.get("dimensionX") or 0), "l": float(a.get("dimensionY") or 0),
                        "thumb": prev.get("256-PNG") or prev.get("128-PNG") or "",
                        "zip": (dl or {}).get("downloadLink") or (dl or {}).get("fullDownloadPath") or "",
                        "size": (dl or {}).get("size") or 0, "maps": a.get("maps") or [],
                        "tags": a.get("tags") or [], "popularity": a.get("popularityScore") or 0})
        out.sort(key=lambda x: (x["family"], x["id"]))
        with open(_list_file() + ".part", "w", encoding="utf-8") as f:
            json.dump(out, f)
        os.replace(_list_file() + ".part", _list_file())
        _list["assets"] = out
        _list["error"] = ""
    except Exception as exc:
        _list["error"] = library.explain(exc).replace("Poly Haven", "ambientCG").replace("polyhaven.com", "ambientcg.com")
    finally:
        _list["loading"] = False
    _start_thumbs()


def _thumb_path(aid):
    d = os.path.join(root(), "thumbs")
    os.makedirs(d, exist_ok=True)
    return os.path.join(d, os.path.basename(aid) + ".png")


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
                try:
                    library._download(a["thumb"], path, tries=1)
                except Exception:
                    continue
        finally:
            _thumbs["running"] = False
    threading.Thread(target=run, daemon=True).start()


def list_assets(_data=None):
    """GET acg/decals/list: the decals (cached list; refreshed in the background when older than a week)."""
    path = _list_file()
    if _list["assets"] is None and os.path.isfile(path):
        try:
            with open(path, encoding="utf-8") as f:
                _list["assets"] = json.load(f)
        except (OSError, ValueError):
            _list["assets"] = None
    fresh = os.path.isfile(path) and time.time() - os.path.getmtime(path) < REFRESH_DAYS * 86400
    if not fresh and not _list["loading"]:
        _list["loading"] = True
        threading.Thread(target=_refresh, daemon=True).start()
    _start_thumbs()
    from .i18n import tr
    assets = _list["assets"] or []
    return {"assets": [dict(a, folder=tr(FAMILIES.get(a["family"], a["family"])), hasThumb=os.path.isfile(_thumb_path(a["id"])),
                            downloaded=os.path.isfile(os.path.join(root(), a["id"], "maps.json"))) for a in assets],
            "loading": _list["loading"], "error": _list["error"], "credit": "ambientCG (ambientcg.com) · CC0"}


def thumb_file(aid):
    path = _thumb_path(aid or "")
    return path if os.path.isfile(path) else None


def maps_of(aid):
    """{channel: file} of a downloaded decal, or None."""
    path = os.path.join(root(), os.path.basename(aid or ""), "maps.json")
    try:
        with open(path, encoding="utf-8") as f:
            maps = json.load(f)
        return {k: v for k, v in maps.items() if os.path.isfile(v)} or None
    except (OSError, ValueError):
        return None


def asset(aid):
    if _list["assets"] is None:
        list_assets()
    for a in _list["assets"] or []:
        if a["id"] == aid:
            return a
    return None


def download(data):
    """POST acg/decals/download {id}: the 1K maps, unpacked in the background (GET acg/decals/status follows)."""
    aid = os.path.basename(data.get("id") or "")
    if maps_of(aid):
        return {"id": aid, "state": "done", "fraction": 1.0}
    a = asset(aid)
    if a is None or not a.get("zip"):
        return {"id": aid, "state": "error", "error": "id"}
    with _lock:
        job = _jobs.get(aid)
        if job and job["state"] == "running":
            return status({"id": aid})
        _jobs[aid] = {"state": "running", "done": 0, "total": int(a.get("size") or 0), "error": ""}

    def advance(n):
        with _lock:
            _jobs[aid]["done"] += n

    def run():
        folder = os.path.join(root(), aid)
        try:
            os.makedirs(folder, exist_ok=True)
            zpath = os.path.join(folder, aid + "_" + RES + ".zip")
            library._download(a["zip"], zpath, advance, timeout=60)
            maps = {}
            with zipfile.ZipFile(zpath) as z:
                for name in z.namelist():
                    stem = os.path.splitext(os.path.basename(name))[0]
                    for key, channel in MAPS.items():
                        if stem.endswith("_" + key) and channel not in maps:
                            target = os.path.join(folder, channel + os.path.splitext(name)[1].lower())
                            with z.open(name) as src, open(target, "wb") as dst:
                                dst.write(src.read())
                            maps[channel] = target
            try:
                os.remove(zpath)
            except OSError:
                pass
            if "color" not in maps:
                raise RuntimeError("no colour map in " + aid)
            with open(os.path.join(folder, "maps.json"), "w", encoding="utf-8") as f:
                json.dump(maps, f)
            with _lock:
                _jobs[aid]["state"] = "done"
        except Exception as exc:
            with _lock:
                _jobs[aid].update(state="error", error=str(exc) if isinstance(exc, RuntimeError) else library.explain(exc))
    threading.Thread(target=run, daemon=True).start()
    return status({"id": aid})


def status(data):
    aid = os.path.basename(data.get("id") or "")
    if maps_of(aid):
        return {"id": aid, "state": "done", "fraction": 1.0}
    with _lock:
        job = dict(_jobs.get(aid) or {"state": "none", "done": 0, "total": 0, "error": ""})
    job["id"] = aid
    job["fraction"] = job["done"] / job["total"] if job.get("total") else None
    return job
