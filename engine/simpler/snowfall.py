"""Neve, passo 3: the flakes that fall - real flakes in the scene, only where the camera looks.

One point cloud (Cycles draws every point as a small sphere: hundreds of thousands cost little) filled in the frame
of the camera, from FALL_NEAR to «Distanza» (fallFar). A constant number of flakes per cubic metre up to D0; beyond
it fewer (as (D0/d)⁴) and bigger (as (d/D0)^1.5): far away the snow becomes a thin speckled veil, as in a photograph,
without millions of points too small to see - and without hiding the scene in a grey fog.

The movement (only for the look of a still picture: the flakes do not move between two images):
  fall       about 1 m/s down
  wind       «Vento» pushes them sideways (up to WIND_MAX m/s) towards «Direzione del vento»
  gusts      «Irregolarità»: a smooth field of eddies (a few waves in space) adds speed in every direction - flakes in
             swirls, some flying fast, some almost still, never all parallel
  zones      «Zone»: the density changes from place to place (a slow field of patches): thick curtains and clearer
             holes instead of the same snow everywhere
  blur       «Mosso»: each flake carries its speed (velocity), and Cycles draws it smeared along its way during the
             shutter (motion blur, only these points move); 0 = sharp dots
Not under roofs, porches and trees when the snow is «Solo all'aperto» (the shelter map of the rain). Not saved with
the project (made again when needed), hidden with «Nascondi la neve». The real-time view draws the same flakes from a
file (GET rain/snowfall.bin): position, radius, speed.
"""
import math
import os
import time

import bpy

from .core import INTERNAL_KEY, log

FALL_KEY = "simpler_snowfall"
MAT_NAME = "Simpler Fiocchi"
FALL_NEAR = 0.25
D0 = 8.0                    # metres: beyond, fewer and bigger flakes
WIND_MAX = 14.0             # m/s at «Vento» 100%
MAX_FLAKES = 450_000
SHUTTER = 1.0 / 30.0        # s: the time the flakes are smeared over at «Mosso» 100% (x the speed)
FALL_DEFAULTS = {"fall": False, "fallAmount": 0.5, "fallSize": 0.5, "fallWind": 0.2, "fallDir": 0.0, "fallGust": 0.4,
                 "fallZones": 0.4, "fallBlur": 0.4, "fallFar": 60.0, "fallSeed": 1}
F = {"sig": None, "meta": None, "rev": 0, "secs": 0.0, "count": 0, "blur_was": None, "dirty": True, "active": False,
     "camkey": None, "shrev": None}


def settings():
    """The flakes' settings while they fall (ambience snow.fall*), else None."""
    from . import ambience
    s = ambience.state()
    if not s or s.get("mode") not in ("sky", "hdri"):
        return None
    sn = dict(FALL_DEFAULTS, **(s.get("snow") or {}))
    c = lambda k, lo, hi: max(lo, min(hi, float(sn.get(k, FALL_DEFAULTS[k]))))
    if not sn.get("fall") or c("fallAmount", 0, 1) <= 0:
        return None
    return {"amount": c("fallAmount", 0, 1), "size": c("fallSize", 0, 1), "wind": c("fallWind", 0, 1),
            "dir": c("fallDir", -360, 720) % 360.0, "gust": c("fallGust", 0, 1), "zones": c("fallZones", 0, 1),
            "blur": c("fallBlur", 0, 1), "far": c("fallFar", 10, 300), "seed": int(sn.get("fallSeed", 1) or 1),
            "outdoor": bool(sn.get("outdoor", True))}


def _camera():
    from .ecosystems import _cam_now
    return _cam_now()


def _sig(st, cam):
    from . import rain, snow
    sh = (rain.SH["meta"] or {}).get("file") if st["outdoor"] else None
    r = lambda v: tuple(round(float(x), 2) for x in v)
    return repr((sorted(st.items()), r(cam["pos"]), r(cam["target"]), round(cam["aspect"], 2), round(cam["lens"], 1), sh))


def _waves(rng, n, scale):
    """A smooth random field in space: n plane waves with wavelength around «scale» m (vectorised, no grid)."""
    import numpy as np
    k = rng.normal(size=(n, 3))
    k /= np.linalg.norm(k, axis=1, keepdims=True)
    k *= (2 * math.pi / scale) * rng.uniform(0.6, 1.6, size=(n, 1))
    ph = rng.uniform(0, 2 * math.pi, size=n)
    amp = rng.uniform(0.5, 1.0, size=n)
    amp /= math.sqrt(float((amp ** 2).sum()) / 2.0)          # (about unit spread)

    def at(p):
        return (np.sin(p @ k.T + ph) * amp).sum(axis=1)
    return at


def generate(st, cam):
    """-> positions (n, 3), radii (n,), speeds (n, 3), all in metres (and m/s)."""
    import numpy as np
    rng = np.random.default_rng(st["seed"] * 7919 + 17)
    pos = np.array(cam["pos"], dtype=np.float64)
    f = np.array(cam["target"], dtype=np.float64) - pos
    f /= max(float(np.linalg.norm(f)), 1e-6)
    rgt = np.cross(f, [0.0, 0.0, 1.0])
    if np.linalg.norm(rgt) < 1e-6:
        rgt = np.array([1.0, 0.0, 0.0])
    rgt /= np.linalg.norm(rgt)
    up = np.cross(rgt, f)
    aspect, half = max(0.05, cam["aspect"]), math.atan(18.0 / max(1.0, cam["lens"]))
    if aspect >= 1:
        tx = math.tan(half); ty = tx / aspect
    else:
        ty = math.tan(half); tx = ty * aspect
    tx, ty = tx * 1.08, ty * 1.08                            # (a little beyond the frame: no empty border)
    far = st["far"]
    d0 = min(D0, far)
    # flakes per m³ near the camera; the zones remove some, so more are drawn first
    rho = 260.0 * st["amount"] ** 1.6
    keep_mean = 1.0 - 0.6 * st["zones"]
    a = (d0 ** 3 - FALL_NEAR ** 3) / 3.0                     # near: uniform in volume
    b = d0 ** 3 * max(0.0, 1.0 - d0 / far)                   # far: density as (d0/d)⁴ - fewer, bigger
    n = int(rho * 4.0 * tx * ty * (a + b) / keep_mean)
    scale = 1.0
    if n > MAX_FLAKES / keep_mean:
        scale = n / (MAX_FLAKES / keep_mean)                 # (too many: fewer, a little bigger, same look)
        n = int(MAX_FLAKES / keep_mean)
    n_near = int(n * a / (a + b)) if (a + b) > 0 else n
    u = rng.random(n)
    d = np.empty(n)
    d[:n_near] = (FALL_NEAR ** 3 + u[:n_near] * (d0 ** 3 - FALL_NEAR ** 3)) ** (1.0 / 3.0)
    if n > n_near:
        d[n_near:] = 1.0 / (1.0 / d0 - u[n_near:] * (1.0 / d0 - 1.0 / far))     # (pdf as 1/d²)
    sx = rng.uniform(-1, 1, n) * tx * d
    sy = rng.uniform(-1, 1, n) * ty * d
    P = pos[None] + f[None] * d[:, None] + rgt[None] * sx[:, None] + up[None] * sy[:, None]
    # patches of thicker and thinner snow
    if st["zones"] > 0:
        zone = _waves(rng, 6, 9.0)(P)
        m = 1.0 / (1.0 + np.exp(-1.6 * zone))                # 0..1, smooth patches
        keep = rng.random(n) < (1.0 - st["zones"]) + st["zones"] * (m ** 1.5) * 1.6
        P, d = P[keep], d[keep]
    # flakes under roofs, porches, trees: none (the shelter map of the rain)
    if st["outdoor"]:
        P, d = _outdoor(P, d)
    n = len(P)
    # sizes: 1-12 mm across, mostly small; farther ones bigger (their share of the picture stays)
    r0 = (0.0006 + 0.0045 * st["size"] ** 1.3) * math.sqrt(scale)
    rad = r0 * rng.lognormal(0.0, 0.35, n)
    far_k = np.maximum(1.0, (d / d0) ** 1.5)
    rad *= far_k
    # speed: falling, the wind, the eddies
    wdir = math.radians(st["dir"])
    wind = np.array([math.sin(wdir), math.cos(wdir), 0.0]) * WIND_MAX * st["wind"] ** 1.2
    V = np.tile(np.array([0.0, 0.0, -1.0]) + wind, (n, 1))
    V[:, 2] *= rng.uniform(0.7, 1.3, n)
    if st["gust"] > 0:
        g = 1.0 + 9.0 * st["gust"] + 0.4 * WIND_MAX * st["wind"] * st["gust"]
        for ax in range(3):
            V[:, ax] += g * (0.45 if ax == 2 else 1.0) * _waves(rng, 5, 4.0 + 2.0 * ax)(P)
        V *= (1.0 + 0.6 * st["gust"] * rng.uniform(-1, 1, (n, 1)))   # (single flakes faster or slower)
    return P.astype(np.float32), rad.astype(np.float32), V.astype(np.float32)


_FILLED = {"file": None, "arr": None}


def _filled(meta):
    """The shelter map with its gaps closed: it is made of points spread over the surfaces (a roof is a scatter of
    heights with empty cells between them); the highest within about half a metre counts."""
    import numpy as np
    from . import snow
    if _FILLED["file"] != meta["file"]:
        a = snow._shelter_array(meta)
        k = max(1, int(round(0.25 / max(float(meta["cell"]), 1e-3))))
        out = a.copy()
        for axis in (0, 1):
            src = out.copy()
            for s in range(1, k + 1):
                np.maximum(out, np.roll(src, s, axis=axis), out=out)
                np.maximum(out, np.roll(src, -s, axis=axis), out=out)
        _FILLED.update(file=meta["file"], arr=out)
    return _FILLED["arr"]


def _outdoor(P, d):
    import numpy as np
    from . import rain, snow
    meta = rain.SH["meta"]
    if meta is None:
        return P, d
    sh = _filled(meta)
    sn = int(meta["n"])
    si = np.floor((P[:, 1] - meta["y0"]) / meta["cell"]).astype(np.int64)
    sj = np.floor((P[:, 0] - meta["x0"]) / meta["cell"]).astype(np.int64)
    inside = (si >= 0) & (si < sn) & (sj >= 0) & (sj < sn)
    v = np.zeros(len(P), dtype=np.float32)
    v[inside] = sh[si[inside], sj[inside]]
    hs = np.where(v > 1e-4, meta["zmin"] + v * meta["zr"], -1e9)
    ok = hs < P[:, 2] + 0.05
    return P[ok], d[ok]


def _material():
    m = bpy.data.materials.get(MAT_NAME)
    if m is not None:
        return m
    m = bpy.data.materials.new(MAT_NAME)
    m.use_nodes = True
    nt = m.node_tree
    nt.nodes.clear()
    out = nt.nodes.new("ShaderNodeOutputMaterial")
    dif = nt.nodes.new("ShaderNodeBsdfDiffuse")
    dif.inputs["Color"].default_value = (0.85, 0.87, 0.9, 1)
    tr_ = nt.nodes.new("ShaderNodeBsdfTranslucent")
    tr_.inputs["Color"].default_value = (0.8, 0.82, 0.86, 1)
    mix = nt.nodes.new("ShaderNodeMixShader")
    mix.inputs["Fac"].default_value = 0.4              # (light from behind shines through: flakes against a lamp)
    nt.links.new(dif.outputs[0], mix.inputs[1])
    nt.links.new(tr_.outputs[0], mix.inputs[2])
    nt.links.new(mix.outputs[0], out.inputs["Surface"])
    return m


def _object():
    for ob in bpy.context.scene.objects:
        if ob.get(FALL_KEY):
            return ob
    return None


def remove():
    ob = _object()
    if ob is None:
        return False
    pc = ob.data
    bpy.data.objects.remove(ob, do_unlink=True)
    if pc is not None and pc.users == 0:
        bpy.data.pointclouds.remove(pc)
    _motion_blur(False)
    return True


BLUR_USERS = set()          # who wants the motion blur of the render now: "snow" (these flakes), "rain" (raindrops.py)


def _motion_blur(on, who="snow"):
    """Motion blur of the render on while flakes (or raindrops) are smeared (only they move: everything else is as
    before); back as it was when nobody wants it any more."""
    r = bpy.context.scene.render
    if on:
        if F["blur_was"] is None:
            F["blur_was"] = bool(r.use_motion_blur)
            # (also in the scene: a project saved - or an undo step taken - while the drops fall gets its own
            # setting back when it opens, after_open)
            bpy.context.scene["simpler_blur_was"] = 1 if F["blur_was"] else 0
        BLUR_USERS.add(who)
        r.use_motion_blur = True
        r.motion_blur_shutter = 0.5
    else:
        BLUR_USERS.discard(who)
        if not BLUR_USERS and F["blur_was"] is not None:
            r.use_motion_blur = F["blur_was"]
            F["blur_was"] = None
            if "simpler_blur_was" in bpy.context.scene:
                del bpy.context.scene["simpler_blur_was"]


def _build(P, R, V, st):
    import numpy as np
    ob = _object()
    pc = bpy.data.pointclouds.new(MAT_NAME)
    n = len(P)
    pc.resize(n)
    pc.attributes["position"].data.foreach_set("vector", P.ravel())
    ra = pc.attributes.get("radius") or pc.attributes.new("radius", "FLOAT", "POINT")
    ra.data.foreach_set("value", R)
    blur = st["blur"] > 0.001
    if blur:
        # (Cycles: metres per second, smeared over shutter / fps - the speed is scaled so that «Mosso» 100% is
        # SHUTTER seconds of the real movement)
        fps = bpy.context.scene.render.fps / max(bpy.context.scene.render.fps_base, 1e-6)
        k = st["blur"] * SHUTTER * fps / 0.5
        va = pc.attributes.new("velocity", "FLOAT_VECTOR", "POINT")
        va.data.foreach_set("vector", (V * k).astype(np.float32).ravel())
    pc.materials.append(_material())
    if ob is None:
        ob = bpy.data.objects.new(MAT_NAME, pc)
        ob[FALL_KEY] = True
        ob[INTERNAL_KEY] = 1
        bpy.context.scene.collection.objects.link(ob)
        ob.hide_select = True
        ob.visible_shadow = False           # (tiny shadows: only noise, and time)
    else:
        old = ob.data
        ob.data = pc
        if old is not None and old.users == 0:
            bpy.data.pointclouds.remove(old)
    from . import snow
    ob.hide_render = ob.hide_viewport = bool(snow.HIDE["on"])
    _motion_blur(blur)


def _write_view(P, R, V, st):
    """rain/snowfall.bin: «SFL1», u32 count, float32 blur (s), then per flake 7 float32: position, radius, speed."""
    import numpy as np
    from . import rain
    d = rain._shelter_dir()
    from . import tempdirs
    for f in os.listdir(d):
        if f.startswith("snowfall_") and tempdirs.removable(f, "snowfall_"):
            try:
                os.remove(os.path.join(d, f))
            except OSError:
                pass
    stem = f"snowfall_{os.getpid()}_{F['rev']}"
    with open(os.path.join(d, stem + ".bin"), "wb") as fh:
        fh.write(np.array([0x314C4653, len(P)], dtype=np.uint32).tobytes())
        fh.write(np.array([st["blur"] * SHUTTER], dtype=np.float32).tobytes())
        fh.write(np.concatenate([P, R[:, None], V], axis=1).astype(np.float32).tobytes())
    return stem


def view_file(name):
    from . import rain
    name = os.path.basename(name or "")
    if not name.startswith("snowfall_") or not name.endswith(".bin"):
        return ""
    p = os.path.join(rain._shelter_dir(), name)
    return p if os.path.isfile(p) else ""


def _camkey():
    from . import render
    c = render.STATE.camera
    return (tuple(c.get("target") or ()), c.get("yaw"), c.get("pitch"), c.get("distance"), c.get("lens"),
            tuple(render.STATE.vp_size or ()))


def touch():
    """The ambience changed (the flakes' settings may have): looked at again in the engine's idle time."""
    F["dirty"] = True


def due():
    """Cheap (from the engine's loop, every few ms): the settings were touched, or the camera moved while flakes
    fall, or the shelter map changed."""
    from . import rain, snow
    if snow.HIDE["on"]:
        return False
    if F.get("dirty"):
        return True
    if not F.get("active"):
        return False
    return _camkey() != F.get("camkey") or (rain.SH["meta"] or {}).get("file") != F.get("shrev")


def update(force=False):
    """The flakes follow the camera and the settings. True when they changed."""
    from . import rain, snow
    if snow.HIDE["on"]:
        return False
    F["dirty"] = False
    F["camkey"] = _camkey()
    F["shrev"] = (rain.SH["meta"] or {}).get("file")
    st = settings()
    F["active"] = st is not None
    if st is None:
        had = F["meta"] is not None
        F.update(sig=None, meta=None)
        return remove() or had
    cam = _camera()
    sig = _sig(st, cam)
    if sig == F["sig"] and not force and _object() is not None:
        return False
    t0 = time.time()
    P, R, V = generate(st, cam)
    _build(P, R, V, st)
    F["rev"] += 1
    stem = _write_view(P, R, V, st)
    F["sig"] = sig
    F["secs"] = round(time.time() - t0, 2)
    F["meta"] = {"rev": F["rev"], "file": stem + ".bin", "count": int(len(P)), "secs": F["secs"]}
    log(f"SIMPLER_SNOW flakes: {len(P)} in {F['secs']} s")
    return True


def show(on):
    ob = _object()
    if ob is not None:
        ob.hide_render = ob.hide_viewport = not on


def after_open():
    remove()
    BLUR_USERS.clear()
    F.update(sig=None, meta=None, blur_was=None, dirty=True)
    sc = bpy.context.scene
    if "simpler_blur_was" in sc:            # (saved while flakes or drops were smeared: the project's own setting)
        sc.render.use_motion_blur = bool(sc["simpler_blur_was"])
        del sc["simpler_blur_was"]
