"""(1.75.32) The two keyframes of the AI video (Video AI panel): «Inizio» and «Fine». Each is a full snapshot of the
scene (framing, render settings, environment, lights, visibility, ambience - the same as a saved Scene) plus the
picture rendered for it. Stored inside the project (.simpler) so they travel with it."""
import copy
import json
import math
import os
import time

import bpy

from . import render, views
from .core import ApiError, refresh
from .i18n import tr

KEY = "simpler_video_frames"
SLOTS = ("start", "end")
PROMPT_KEY = "simpler_video_prompt"


def _load():
    raw = bpy.context.scene.get(KEY)
    try:
        d = json.loads(raw) if raw else {}
        return d if isinstance(d, dict) else {}
    except ValueError:
        return {}


def _store(frames):
    bpy.context.scene[KEY] = json.dumps(frames)


def _slot(data):
    s = (data or {}).get("slot")
    if s not in SLOTS:
        raise ApiError(tr("Fotogramma non valido"))
    return s


def _eye(cam):
    yaw, pitch = math.radians(cam["yaw"]), math.radians(cam["pitch"])
    t = cam["target"]
    d = cam["distance"]
    return [t[0] + math.cos(pitch) * math.cos(yaw) * d, t[1] + math.cos(pitch) * math.sin(yaw) * d, t[2] + math.sin(pitch) * d]


def _gap(a, b):
    """How far the two cameras are: metres between the eyes, degrees between the view directions, lens ratio."""
    ea, eb = _eye(a), _eye(b)
    metres = math.dist(ea, eb) / 100.0

    def direction(cam, eye):
        v = [cam["target"][i] - eye[i] for i in range(3)]
        n = math.sqrt(sum(x * x for x in v)) or 1.0
        return [x / n for x in v]
    da, db = direction(a, ea), direction(b, eb)
    dot = max(-1.0, min(1.0, sum(da[i] * db[i] for i in range(3))))
    degrees = math.degrees(math.acos(dot))
    lens = max(a.get("lens", 50.0), b.get("lens", 50.0)) / max(1.0, min(a.get("lens", 50.0), b.get("lens", 50.0)))
    return {"metres": round(metres, 2), "degrees": round(degrees, 1), "lens": round(lens, 2)}


def _version(v):
    return str(v.get("stamp") or v.get("updated", ""))


def _public(f, saved):
    if not f:
        return None
    img = f.get("image") or ""
    out = {"image": img if img and os.path.isfile(img) else "", "updated": f.get("updated", ""),
           "width": f.get("width", 0), "height": f.get("height", 0)}
    # (1.75.42) the saved scene it came from, by its id (never by name): its name as it is now (renamed: the new
    # name), gone when deleted (another scene with the same name is not it), changed when updated after the keyframe.
    # The keyframe is a copy of the scene in any case: renaming, updating or deleting the scene never changes it.
    vid = f.get("view") or ""
    if vid:
        v = saved.get(vid)
        out["viewId"] = vid
        out["viewName"] = v["name"] if v else f.get("viewName", "")
        out["viewGone"] = v is None
        out["viewChanged"] = bool(v) and _version(v) != f.get("viewUpdated", "")
    return out


def list_frames(_data=None):
    fr = _load()
    saved = {v["id"]: v for v in views._load()}
    renamed = False
    for s in SLOTS:          # (the last name of the scene kept: shown with «eliminata» if it is deleted later)
        f, v = fr.get(s), saved.get((fr.get(s) or {}).get("view") or "")
        if f and v and f.get("viewName") != v["name"]:
            f["viewName"] = v["name"]
            renamed = True
    if renamed:
        _store(fr)
    out = {s: _public(fr.get(s), saved) for s in SLOTS}
    out["prompt"] = bpy.context.scene.get(PROMPT_KEY, "")     # (1.75.44) the motion text belongs to the project
    if fr.get("start") and fr.get("end"):
        out["gap"] = _gap(fr["start"]["snapshot"]["camera"], fr["end"]["snapshot"]["camera"])
    return out


def save_frame(data):
    """The current view becomes the keyframe (before its picture is rendered: «image» comes with frame/image)."""
    s = _slot(data)
    fr = _load()
    fr[s] = {"snapshot": views.current_snapshot(), "updated": time.strftime("%Y-%m-%d %H:%M"), "image": "",
             "width": 0, "height": 0}
    vid = (data or {}).get("view") or ""
    if vid:              # (1.75.42) made from a saved scene («Da una vista salvata…»): which one, and as it was then
        v = next((x for x in views._load() if x["id"] == vid), None)
        if v is not None:
            fr[s].update({"view": vid, "viewName": v["name"], "viewUpdated": _version(v)})
    _store(fr)
    return list_frames()


def set_image(data):
    s = _slot(data)
    fr = _load()
    if not fr.get(s):
        raise ApiError(tr("Fotogramma non valido"))
    fr[s]["image"] = data.get("image") or ""
    fr[s]["width"] = int(data.get("width") or 0)
    fr[s]["height"] = int(data.get("height") or 0)
    _store(fr)
    return list_frames()


def clear_frame(data):
    s = _slot(data)
    fr = _load()
    fr.pop(s, None)
    _store(fr)
    return list_frames()


def apply_frame(data):
    """Back to a keyframe: the whole scene, or only its framing (cameraOnly: «Stessa inquadratura dell'inizio»)."""
    s = _slot(data)
    f = _load().get(s)
    if not f:
        raise ApiError(tr("Fotogramma non valido"))
    snap = f["snapshot"]
    if data.get("cameraOnly"):
        render.STATE.camera = copy.deepcopy(snap["camera"])
        render.apply_camera()
        refresh()
        return {"view": render.camera_view(), "settings": render.settings_json()}
    return views.apply_snapshot(snap)


def raw_frames(_data=None):
    """(1.75.39) The two keyframes whole (snapshots included): kept with each AI video, to make it again."""
    return {"frames": _load()}


def restore_frames(data):
    """(1.75.39) The keyframes of an AI video back in the panel (its pictures where the library keeps them)."""
    fr = data.get("frames") or {}
    if not isinstance(fr, dict):
        raise ApiError(tr("Fotogramma non valido"))
    _store({s: fr[s] for s in SLOTS if isinstance(fr.get(s), dict) and fr[s].get("snapshot")})
    return list_frames()


def set_prompt(data):
    """(1.75.44) The motion text of the AI video, kept in the project (a new project starts empty)."""
    bpy.context.scene[PROMPT_KEY] = str((data or {}).get("text") or "")[:4000]
    return list_frames()
