"""«Calcola solo l'area inquadrata»: what is made only (or finer) where the camera looks - one place for all of it.

Saved in the project (scene[KEY]): {"snow": bool, "eco": bool}
  snow   the mantle of snow (snow.py): the ground finer near the camera and coarser far away, only a light base out of
         the frame; the mantle of the distributions only for the models with copies in the frame, as fine as their
         distance needs. Made again by itself when the camera stops (in the engine's idle time).
  eco    the ecosystems (ecosystems.py): their pieces only where the camera sees the surface. Too heavy to be made at
         every stop of the camera: when the view changed, the app shows «Ricalcola» (refresh: all of them, one undo
         step), and before a final render they are made for its camera. An ecosystem «Sempre intero» (its «whole»)
         stays whole.
The flakes that fall (snowfall.py) are always only in front of the camera: nothing to choose.
A project made before this had no setting: the snow follows the camera, the ecosystems as they were (cut when one of
them was cut).
"""
import json

from .i18n import tr
import math

import bpy

KEY = "simpler_camview"
ITEMS = ("snow", "eco", "scree")       # (1.76.25: «Pietre e detriti» too, Luca)
FRAME = {"aspect": None}        # (a final render: the proportions of its image, while it is prepared)


def _stored():
    try:
        return json.loads(bpy.context.scene.get(KEY) or "{}")
    except (TypeError, ValueError):
        return {}


def settings():
    s = _stored()
    out = {"snow": bool(s.get("snow", True))}
    if "eco" in s:
        out["eco"] = bool(s["eco"])
    else:
        ecos = [json.loads(g.get(_eco_key()) or "{}") for g in _eco_groups()]
        out["eco"] = any(e.get("camOnly") for e in ecos) if ecos else True
    out["scree"] = bool(s.get("scree", out["eco"]))
    return out


def on(item):
    """Cheap (the snow asks every few ms in the engine's idle time)."""
    raw = bpy.context.scene.get(KEY)
    if raw != _ON["raw"]:
        try:
            _ON.update(raw=raw, val=json.loads(raw or "{}"))
        except (TypeError, ValueError):
            _ON.update(raw=raw, val={})
    v = _ON["val"]
    if item in v:
        return bool(v[item])
    if item == "snow":
        return True
    return bool(settings().get(item))


_ON = {"raw": object(), "val": {}}


def set_settings(d):
    """POST camview {snow?, eco?} (all: both)"""
    cur = settings()
    new = dict(cur)
    if "all" in d:
        new = {k: bool(d["all"]) for k in ITEMS}
    for k in ITEMS:
        if k in d:
            new[k] = bool(d[k])
    bpy.context.scene[KEY] = json.dumps(new)
    if new["snow"] != cur["snow"]:
        from . import snow, rain
        snow.touch()
        rain.refresh_info()
    return status()


# ---------------------------------------------------------------- the camera

def camera():
    """The camera of the view now: position, target (m), proportions of the frame, lens, width in pixels."""
    from . import render
    from .ecosystems import _cam_now
    c = _cam_now()
    if FRAME.get("aspect"):
        c["aspect"] = float(FRAME["aspect"])
    c["width"] = float(max(64, (render.STATE.vp_size or (1600, 900))[0]))
    return c


def moved(a, b):
    """Has the camera moved enough (from a to b) for what was made for a to show? About a twentieth of the distance to
    what it looks at, a tenth of the frame turned, the lens or the proportions changed by a tenth."""
    if not a or not b:
        return True
    pa, pb = [float(x) for x in a["pos"]], [float(x) for x in b["pos"]]
    ta, tb = [float(x) for x in a["target"]], [float(x) for x in b["target"]]
    da = math.dist(pa, ta)
    if math.dist(pa, pb) > max(0.25, 0.05 * da):
        return True
    fa = [(t - p) / max(da, 1e-6) for t, p in zip(ta, pa)]
    db = math.dist(pb, tb)
    fb = [(t - p) / max(db, 1e-6) for t, p in zip(tb, pb)]
    cos = max(-1.0, min(1.0, sum(x * y for x, y in zip(fa, fb))))
    half = math.atan(18.0 / max(1.0, float(a["lens"])))
    if math.acos(cos) > 0.1 * half:
        return True
    if abs(math.log(max(1e-3, float(b["lens"])) / max(1e-3, float(a["lens"])))) > 0.1:
        return True
    return abs(math.log(max(0.05, float(b["aspect"])) / max(0.05, float(a["aspect"])))) > 0.1


class Frustum:
    """The frame of a camera with a margin: what is in it, how far, how big a pixel is there."""

    def __init__(self, cam, margin=0.1):
        import numpy as np
        self.pos = np.array(cam["pos"], dtype=np.float64)
        f = np.array(cam["target"], dtype=np.float64) - self.pos
        f /= max(float(np.linalg.norm(f)), 1e-6)
        r = np.cross(f, [0.0, 0.0, 1.0])
        if np.linalg.norm(r) < 1e-6:
            r = np.array([1.0, 0.0, 0.0])
        r /= np.linalg.norm(r)
        self.f, self.r, self.u = f, r, np.cross(r, f)
        aspect, half = max(0.05, float(cam["aspect"])), math.atan(18.0 / max(1.0, float(cam["lens"])))
        if aspect >= 1:
            tx = math.tan(half); ty = tx / aspect
        else:
            ty = math.tan(half); tx = ty * aspect
        self.tx0, self.ty0 = tx, ty
        m = 1.0 + max(0.0, margin)
        self.tx, self.ty = tx * m, ty * m
        self.pixel = 2.0 * tx / max(64.0, float(cam.get("width") or 1600))     # (radians per pixel, about)

    def look(self, P, rad=None):
        """-> (distance from the camera (m), in the frame (bool)) for points P (n, 3); rad: their size (a sphere)."""
        import numpy as np
        v = P - self.pos
        z = v @ self.f
        x = np.abs(v @ self.r)
        y = np.abs(v @ self.u)
        d = np.linalg.norm(v, axis=1)
        rr = 0.0 if rad is None else rad
        sx = math.sqrt(1.0 + self.tx * self.tx)
        sy = math.sqrt(1.0 + self.ty * self.ty)
        zz = np.maximum(z, 0.0)
        inside = (z > -rr) & (x <= self.tx * zz + rr * sx) & (y <= self.ty * zz + rr * sy)
        return d, inside


# ---------------------------------------------------------------- the ecosystems

def _eco_key():
    from .ecosystems import ECO_KEY
    return ECO_KEY


def _eco_groups():
    k = _eco_key()
    return [g for g in bpy.context.scene.objects if g.get(k) and not g.get("simpler_trashed")]


def eco_wanted(st):
    """Should this ecosystem (its saved settings) be only where the camera looks?"""
    return on("eco") and not st.get("whole")


def _eco_stale(now=None):
    """The ecosystems not made as the setting and the camera of now want (and that can be made again)."""
    from .core import ApiError, ID_KEY
    now = now or camera()
    out = []
    for g in _eco_groups():
        try:
            st = json.loads(g.get(_eco_key()) or "{}")
        except (TypeError, ValueError):
            continue
        want = eco_wanted(st)
        if bool(st.get("camOnly")) != want or (want and moved(st.get("camView"), now)):
            try:
                from .ecosystems import _read_placed
                _read_placed(st.get("id"), st.get("name") or "")
            except ApiError:
                continue                    # (gone from the library: it cannot be made again - left as it is)
            out.append(g.get(ID_KEY))
    return out


def scree_wanted(st):
    """(1.76.25) Should these stones (their saved settings) be only where the camera looks?"""
    return on("scree") and not st.get("whole")


def _scree_stale(now=None):
    """The «Pietre e detriti» not made as the setting and the camera of now want."""
    from . import scree
    from .core import ID_KEY
    now = now or camera()
    out = []
    for g in bpy.context.scene.objects:
        if not g.get(scree.KEY) or g.get(scree.LAYER_KEY) or g.get("simpler_trashed"):
            continue
        st = scree._state(g)
        want = scree_wanted(st)
        if bool(st.get("camView")) != want or (want and moved(st.get("camView"), now)):
            out.append(g.get(ID_KEY))
    return out


def status(_d=None):
    s = settings()
    stale = _eco_stale()
    sc = _scree_stale()
    # (ecoStale: everything «Ricalcola» makes again - the app asks it before a final render too)
    from . import scree
    n_scree = sum(1 for g in bpy.context.scene.objects
                  if g.get(scree.KEY) and not g.get(scree.LAYER_KEY) and not g.get("simpler_trashed"))
    # (1.76.31: screeTotal - the app asks again after the camera stops also when there are only stones: before, with
    # no ecosystem, «Ricalcola» never showed bottom left for the stones, Luca)
    return dict(s, ecoStale=len(stale) + len(sc), screeStale=len(sc), ecoTotal=len(_eco_groups()), screeTotal=n_scree)


def refresh(d=None):
    """POST camview/refresh: the ecosystems made again as the setting and the camera of now want (one undo step)."""
    from . import ecosystems
    from .core import ApiError
    done, failed = 0, []
    from .core import find
    for gid in _eco_stale():
        st = None
        try:
            g = find(gid)
            st = json.loads(g.get(_eco_key()) or "{}")
            ecosystems.apply({"group": gid, "camOnly": eco_wanted(st), "camRefresh": True})
            done += 1
        except ApiError as exc:
            failed.append({"name": (st or {}).get("name", ""), "error": str(exc)})
    from . import scree
    for gid in _scree_stale():
        try:
            scree.apply({"group": gid, "camRefresh": True})
            done += 1
        except ApiError as exc:
            failed.append({"name": tr("Pietre e detriti"), "error": str(exc)})
    return dict(status(), done=done, failed=failed)
