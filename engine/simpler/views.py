"""Saved scenes ("Scene" tab): framing + every render setting + environment + lights + visibility, with a
thumbnail (captured from the real-time view). Stored inside the project (.simpler) so they travel with it."""
import base64
import copy
import json
import os
import time
import uuid

import bpy

from . import render
from .core import ID_KEY, ApiError, managed_objects, refresh
from .i18n import tr

KEY = "simpler_views"
THUMB_W, THUMB_H = 320, 200
LIGHT_PROPS = ("energy", "color", "use_temperature", "temperature", "shadow_soft_size", "use_shadow",
               "spot_size", "spot_blend", "size", "size_y", "angle")


def _load():
    raw = bpy.context.scene.get(KEY)
    try:
        return json.loads(raw) if raw else []
    except ValueError:
        return []


def _store(views):
    bpy.context.scene[KEY] = json.dumps(views)


def _find(views, view_id):
    for v in views:
        if v["id"] == view_id:
            return v
    raise ApiError(tr("Vista non trovata"))


def _snapshot():
    world = bpy.context.scene.world
    lights, visible = {}, {}
    for ob in managed_objects():
        oid = ob.get(ID_KEY)
        if not oid:
            continue
        visible[oid] = not ob.hide_render
        if ob.type == "LIGHT":
            d = ob.data
            st = {"type": d.type}
            for p in LIGHT_PROPS:
                if hasattr(d, p):
                    val = getattr(d, p)
                    st[p] = list(val) if hasattr(val, "__len__") and not isinstance(val, str) else val
            lights[oid] = st
    return {
        "camera": copy.deepcopy(render.STATE.camera),
        "config": copy.deepcopy(render.STATE.config),
        "quality": render.STATE.quality,
        "caustics": render.STATE.caustics,
        "environment": (world.get("simpler_env", "studio_morbido") if world else "studio_morbido"),
        "envStrength": float(world.get("simpler_env_strength", 1.0)) if world else 1.0,
        "lights": lights,
        "visible": visible,
        "ambience": _ambience_state(),
    }


def _ambience_state():
    from . import ambience
    return ambience.state()


def _given_thumb(data):
    """JPEG (base64) captured by the app from the real-time view: instant even on huge scenes."""
    t = data.get("thumb") if isinstance(data, dict) else None
    if not isinstance(t, str) or len(t) < 100 or len(t) > 2_000_000:
        return None
    try:
        raw = base64.b64decode(t, validate=True)
    except ValueError:
        return None
    return t if raw[:2] == b"\xff\xd8" else None


def _thumbnail():
    """Fallback: small, fast path-traced image of the current framing (JPEG, base64)."""
    scene = bpy.context.scene
    render.apply_camera()
    render._apply_common(scene)
    aspect = render.FORMATS.get(render.cam_get("format")) or (render.STATE.vp_size[0] / render.STATE.vp_size[1])
    tw, th = (THUMB_W, max(60, round(THUMB_W / aspect))) if aspect >= 1 else (max(60, round(THUMB_H * aspect)), THUMB_H)
    render.fit_camera_to_render(tw, th)
    r = scene.render
    saved = (r.resolution_x, r.resolution_y, r.resolution_percentage, scene.cycles.samples, scene.cycles.time_limit,
             r.image_settings.file_format, r.filepath)
    path = os.path.join(render.STATE.tmp, "view_thumb.jpg")
    try:
        r.resolution_x, r.resolution_y, r.resolution_percentage = tw, th, 100
        scene.cycles.samples = 8
        scene.cycles.time_limit = 2.0
        scene.cycles.use_denoising = True
        r.image_settings.file_format = "JPEG"
        r.image_settings.quality = 85
        r.filepath = path
        from . import matedit
        matedit.flush_pending()          # (1.76.56) the material trees left for later
        bpy.ops.render.render(write_still=True)
        with open(path, "rb") as f:
            return base64.b64encode(f.read()).decode("ascii")
    finally:
        (r.resolution_x, r.resolution_y, r.resolution_percentage, scene.cycles.samples, scene.cycles.time_limit,
         r.image_settings.file_format, r.filepath) = saved
        render.apply_camera()
        render.invalidate()


# (1.75.57) the scene opened last from its thumbnail, and the count of the changes to the project right after: the
# path tracing of that scene, finished with nothing changed since, becomes its thumbnail (pt_thumb - Luca's idea)
APPLIED = {"id": None, "n": -1}


def _near(a, b):
    """Two framings the same (the view may send the camera back with its own rounding)."""
    if isinstance(a, dict) and isinstance(b, dict):
        return set(a) == set(b) and all(_near(a[k], b[k]) for k in a)
    if isinstance(a, (list, tuple)) and isinstance(b, (list, tuple)):
        return len(a) == len(b) and all(_near(x, y) for x, y in zip(a, b))
    if isinstance(a, (int, float)) and isinstance(b, (int, float)) and not isinstance(a, bool) and not isinstance(b, bool):
        return abs(a - b) <= 1e-3 * max(1.0, abs(a), abs(b))
    return a == b


def pt_thumb(data, changes):
    """POST views/ptthumb {id, thumb}: the finished path tracing (JPEG from the view, cut like the thumbnails) becomes
    the thumbnail of the scene - only if it is the scene opened last and nothing changed since (the count of the
    changes and the framing). The date of the scene is not touched: a better thumbnail is not a change (the keyframes
    of the AI video look at it). «Aggiorna» on the scene gives the thumbnail of the real-time view back."""
    from .core import log
    vid = data.get("id")
    why = ""
    if APPLIED["id"] != vid:
        why = "not the scene opened last"
    elif changes != APPLIED["n"]:
        why = f"project changed since the scene was opened ({changes - APPLIED['n']} changes)"
    views = _load()
    v = next((x for x in views if x["id"] == vid), None)
    if not why and v is None:
        why = "scene gone"
    if not why and not _near(render.STATE.camera, v.get("camera")):
        why = "framing moved"
    thumb = _given_thumb(data)
    if not why and not thumb:
        why = "no picture"
    if why:
        log("SIMPLER_PTTHUMB", vid, "kept:", why)
        return {"replaced": False, "why": why}
    v["thumb"] = thumb
    v["thumbPT"] = True
    _store(views)
    log("SIMPLER_PTTHUMB", vid, "thumbnail from the path tracing", f"{len(thumb) * 3 // 4 // 1024} KB")
    return {"replaced": True, "view": {k: v[k] for k in ("id", "name", "thumb", "updated")}}


def list_views(_data=None):
    return {"views": [{k: v[k] for k in ("id", "name", "thumb", "updated")} for v in _load()]}


def save_view(data):
    views = _load()
    name = (data.get("name") or "").strip() or tr("Scena {0}", len(views) + 1)
    view = {"id": uuid.uuid4().hex[:10], "name": name, "updated": time.strftime("%Y-%m-%d %H:%M"), "stamp": time.time(), **_snapshot()}
    view["thumb"] = _given_thumb(data) or _thumbnail()
    views.append(view)
    _store(views)
    return {"view": {k: view[k] for k in ("id", "name", "thumb", "updated")}}


def update_view(data):
    views = _load()
    v = _find(views, data.get("id"))
    v.update(_snapshot())
    v["updated"] = time.strftime("%Y-%m-%d %H:%M")
    v["stamp"] = time.time()          # (1.75.42) to the second: the video keyframes made from it know it changed
    v["thumb"] = _given_thumb(data) or _thumbnail()
    v.pop("thumbPT", None)            # (1.75.57) back to the thumbnail of the real-time view
    _store(views)
    return {"view": {k: v[k] for k in ("id", "name", "thumb", "updated")}}


def rename_view(data):
    views = _load()
    v = _find(views, data.get("id"))
    name = (data.get("name") or "").strip()
    if not name:
        raise ApiError(tr("Il nome non può essere vuoto"))
    v["name"] = name
    _store(views)
    return {}


def duplicate_view(data):
    views = _load()
    v = copy.deepcopy(_find(views, data.get("id")))
    v["id"] = uuid.uuid4().hex[:10]
    v["name"] = v["name"] + tr(" copia")
    views.insert(views.index(_find(views, data.get("id"))) + 1, v)
    _store(views)
    return {"id": v["id"]}


def delete_view(data):
    views = _load()
    v = _find(views, data.get("id"))
    views.remove(v)
    _store(views)
    return {}


def current_snapshot():
    return copy.deepcopy(_snapshot())


def apply_view(data):
    """Back to a saved scene: framing, render settings, caustics, environment, lights, visibility."""
    return apply_snapshot(_find(_load(), data.get("id")))


def apply_snapshot(v):
    from . import scene_ops
    render.STATE.camera = copy.deepcopy(v["camera"])
    # texture sizes are a performance choice of this computer, not part of the look of a scene: kept as they are
    keep = {k: render.STATE.config.get(k) for k in ("textureLimit", "realtimeTextures") if k in render.STATE.config}
    render.STATE.config = render.default_config("alta")
    render.STATE.config.update({k: x for k, x in v.get("config", {}).items() if k not in keep})
    if "meterExposure" not in v.get("config", {}):
        render.STATE.config["meterExposure"] = False     # (1.79.0) scenes saved before: their exposure as it was
    render.STATE.config.update(keep)
    render.STATE.quality = v.get("quality", "alta")
    render.apply_caustics(bool(v.get("caustics", False)))
    # (1.79, Luca: «è sparito il materiale asfalto del pavimento ... mi ha tolto anche la pioggia») a scene with a sky or
    # a photographed sky is set by its ambience below: going through set_environment first took the scene to a studio
    # background for a moment - and that deletes the ground (with the material the user gave it and the decals
    # projected on it), made again as Simpler's by the ambience. Only a scene without a sky sets its background here.
    if (v.get("ambience") or {}).get("mode") not in ("sky", "hdri"):
        try:
            scene_ops.set_environment(v.get("environment", "studio_morbido"), float(v.get("envStrength", 1.0)))
        except ApiError:
            pass
    by_id = {ob.get(ID_KEY): ob for ob in managed_objects() if ob.get(ID_KEY)}
    for oid, vis in v.get("visible", {}).items():
        ob = by_id.get(oid)
        # only what differs (1.70.3): writing all 4,300 pieces of a big model took 2 s and made the path tracing
        # sync every object again
        if ob is not None and (ob.hide_render != (not vis) or ob.hide_viewport != (not vis)):
            ob.hide_render = not vis
            ob.hide_viewport = not vis
    for oid, st in v.get("lights", {}).items():
        ob = by_id.get(oid)
        if ob is None or ob.type != "LIGHT":
            continue
        if ob.data.type != st.get("type", ob.data.type):
            ob.data.type = st["type"]
        for p, val in st.items():
            if p != "type" and hasattr(ob.data, p):
                try:
                    setattr(ob.data, p, val)
                except (TypeError, ValueError, AttributeError):
                    pass
        ob.data.update_tag()
    if v.get("ambience") and v["ambience"].get("mode") in ("sky", "hdri", "studio"):   # (1.75.6: studio too - its rain and snow)
        from . import ambience
        ambience.apply(copy.deepcopy(v["ambience"]))      # after the lights: the sky sets its sun again
    render.apply_camera()
    refresh()
    return {"view": render.camera_view(), "settings": render.settings_json()}
