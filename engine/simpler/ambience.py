"""Ambiente: physical sky, sun, clouds, haze, night sky and ground (the "Ambience" of Twinmotion, with Blender).

Everything is chosen for the path tracing time first:
- Sky: Blender's "Multiple scattering" sky (5.0+), the same atmosphere model for the colour of the sky and of the
  sun. The sun that lights the scene is a Sun light (sharp shadows, sampled directly by Cycles: no noise); its
  colour and strength come from the same atmosphere (fitted formula of the sky model, below), so sunset, haze or
  thin air change sun and sky together. The disc in the sky is only seen by the camera (Light Path), so it never
  lights the scene twice.
- Clouds: a layer painted in the sky (noise projected on a plane above), not a volume: ~10% more time instead of
  several times. They dim and soften the sun.
- Haze / fog: distance fog made by the compositor from the Mist pass (no volume in the scene: no extra time).
- Night: stars in the sky (only when the sun is down) and a moon (a second, weak Sun light).
- Ground: one very large plane (2 triangles) with a tiling texture made here (no download), so an empty scene
  already has a horizon. It is an ordinary object ("Suolo"): other materials can go on it.
- Exposure: automatic from the light of sun and sky (like a camera), plus the manual exposure of the render settings.
- Real-time view: a small 360° picture of the sky is path traced by the preview Blender (never in the engine: the
  scene stays on the GPU) and used by the view as background and light, so both views agree.

The settings live on the world (simpler_ambience, JSON) and travel with the project and the saved scenes.
"""
import copy
import json
import math
import os

import bpy
from mathutils import Vector, Matrix

from .core import ApiError, ID_KEY, ensure_id, find, refresh, log
from .i18n import tr
from . import clouds

KEY = "simpler_ambience"
SUN_KEY = "simpler_ambience_sun"       # on the Sun light driven by the Ambiente
MOON_KEY = "simpler_ambience_moon"
GROUND_KEY = "simpler_ground"
NIGHT_EV = 4.5                         # highest automatic exposure of a full night (see auto_ev)
K = 0.025                              # scene units per unit of the sky model (noon sun ~4 W/m²)
GROUND_SIZE = 4000.0                   # metres (horizon at ~2 km: beyond, the haze)
TEX_VERSION = 2

DEFAULTS = {
    "mode": "sky",                     # "sky" | "hdri" | "studio"
    "preset": "giorno",
    "sun": {"hour": 12.0, "day": 172, "lat": 45.5, "north": 0.0, "intensity": 1.0, "size": 0.545},
    "sky": {"air": 1.0, "aerosol": 1.0, "ozone": 1.0, "altitude": 100.0, "ambient": 1.0},
    "clouds": {"cover": 0.2, "scale": 0.5, "soft": 0.5, "seed": 7, "cirrus": 0.0,
               # volumetric clouds (clouds.py): off = painted on the sky
               "volumetric": False, "type": "cumuli_piccoli", "height": 1200.0, "thickness": 700.0, "flat": 0.75,
               "puff": 0.70, "density": 0.45, "shadows": True, "layer2": False, "layer2Cover": 0.5},
    # (1.75.49) low: the fog thins out upwards - dense up to «height» (m above the ground, z 0), then fading over
    # «falloff» metres; start: metres from the camera where it begins; tint: the colour chosen (sRGB) instead of the
    # automatic one (its brightness stays the automatic one: a tint, not a lamp)
    # (1.75.50) haze2: a thin haze everywhere above a low fog (the second layer); noise / noiseScale: patches and an
    # undulating top in the volumetric fog; glow: how much the fog lights up towards the lights (droplets: Mie)
    "fog": {"density": 0.15, "volumetric": False, "low": False, "height": 10.0, "falloff": 20.0, "start": 0.0,
            "tint": False, "color": [0.80, 0.84, 0.90], "haze2": 0.0, "noise": 0.0, "noiseScale": 25.0, "glow": 0.6},
    # night: stars and moon light (×); phase 0 new · 0.25 first quarter · 0.5 full · 0.75 last quarter; moonSize ×
    # the real size (0.52°); disc and halo: how bright the disc and its glow look; moonAuto: placed opposite the sun,
    # else at moonElev / moonAz (degrees, azimuth from north towards east)
    "night": {"stars": 0.1, "moon": 1.0, "phase": 0.5, "moonSize": 4.0, "disc": 0.6, "halo": 0.6,
              "moonAuto": True, "moonElev": 35.0, "moonAz": 135.0},
    "ground": {"type": "piastrelle"},
    "exposure": {"auto": True},
    "hdri": {"id": "", "rotation": 0.0, "strength": 1.0, "sun": True},
    # rain on the surfaces (rain.py): wetness, share of puddles, size of their pattern, mirror (0) .. clear water (1)
    "rain": {"wet": 0.0, "puddles": 0.0, "size": 0.5, "look": 0.3, "offX": 0.0, "offY": 0.0, "soft": 0.3, "outdoor": True,
             "paintSoft": 0.5},
    # snow on the surfaces (rain.py, same materials; while it snows the rain is suspended): amount, how far it goes
    # down the slopes, edge softness, shift of its pattern
    "snow": {"amount": 0.0, "walls": 0.3, "soft": 0.3, "offX": 0.0, "offY": 0.0, "outdoor": True, "depth": 0.1, "paintSoft": 0.5,
             "detail": 0.5, "age": 0.0},
}

# presets: changes to the defaults; "elev" = sun height in degrees (the hour is found for the date and place),
# "pm" = afternoon side
PRESETS = [
    ("alba", "Alba", {"elev": 1.5, "pm": False, "sky": {"aerosol": 1.4, "ozone": 1.2}, "clouds": {"cover": 0.3, "cirrus": 0.45}, "fog": {"density": 0.3}}),
    ("mattino", "Mattino limpido", {"elev": 18, "pm": False, "sky": {"aerosol": 0.8}, "clouds": {"cover": 0.1}, "fog": {"density": 0.25}}),
    ("giorno", "Pieno giorno", {"hour": 12.0, "clouds": {"cover": 0.2}, "fog": {"density": 0.15}}),
    ("pomeriggio", "Pomeriggio", {"elev": 32, "pm": True, "clouds": {"cover": 0.35}, "fog": {"density": 0.15}}),
    ("ora_doro", "Ora d'oro", {"elev": 7, "pm": True, "sky": {"aerosol": 1.6}, "clouds": {"cover": 0.25}, "fog": {"density": 0.2}}),
    ("tramonto", "Tramonto", {"elev": 1.0, "pm": True, "sky": {"aerosol": 2.2}, "clouds": {"cover": 0.35, "cirrus": 0.35}, "fog": {"density": 0.2}}),
    ("crepuscolo", "Crepuscolo", {"elev": -3.0, "pm": True, "sky": {"aerosol": 1.6, "ozone": 1.3}, "clouds": {"cover": 0.3, "cirrus": 0.5}, "fog": {"density": 0.15}, "night": {"stars": 0.06, "moon": 1.0}}),
    ("nuvoloso", "Nuvoloso", {"hour": 12.0, "sky": {"aerosol": 2.5}, "clouds": {"cover": 0.85, "soft": 0.8}, "fog": {"density": 0.35}}),
    ("nebbia", "Nebbia", {"hour": 11.5, "sky": {"aerosol": 5.0}, "clouds": {"cover": 0.7, "soft": 1.0}, "fog": {"density": 0.8}}),
    ("notte", "Notte", {"elev": -25, "pm": True, "clouds": {"cover": 0.05}, "fog": {"density": 0.1}, "night": {"stars": 0.1, "moon": 1.0}}),
    ("studio", "Studio", {"mode": "studio"}),
]
# the settings in the "Avanzate" boxes of the panel: once the user changes one, the presets leave it as it is
ADVANCED = {"sun": ("day", "lat", "north", "size"), "sky": ("air", "ozone", "altitude"),
            "clouds": ("height", "thickness", "flat", "puff", "density", "shadows"), "fog": ("volumetric", "start", "noise", "noiseScale", "glow"),
            "night": ("stars", "moon", "phase", "moonSize", "disc", "halo", "moonAuto", "moonElev", "moonAz"),
            "rain": ("offX", "offY", "soft", "outdoor", "paintSoft"), "snow": ("walls", "soft", "offX", "offY", "outdoor", "paintSoft", "detail", "age")}
CLOUD_SHAPE = ("height", "thickness", "flat", "puff", "density")
GROUNDS = [("piastrelle", "Piastrelle"), ("bianco", "Bianco"), ("prato", "Prato"), ("terra", "Terra"), ("cemento", "Cemento"), ("neutro", "Neutro"), ("nessuno", "Nessuno")]


# ---------------------------------------------------------------- the sun from the sky model
# Sun irradiance (normal incidence) of Blender's Multiple scattering sky, fitted on renders of the sky model
# (5% rms): E = E0 * exp(-m * (air*a*exp(-alt/hr) + aerosol*b*exp(-alt/hm) + ozone*o)), m = air mass (Kasten-Young)
_E0 = (181.144, 164.301, 156.919)
_A = (0.04948, 0.10251, 0.26193)
_B = (0.01407, 0.01717, 0.02510)
_O = (0.02761, 0.02469, 0.0)
_HR, _HM = 7208.2, 3044.3


def _air_mass(elev):
    e = max(0.0, elev)
    return 1.0 / (math.sin(math.radians(e)) + 0.50572 * (e + 6.07995) ** -1.6364)


def sun_rgb(elev, sky):
    """Irradiance of the sun disc (model units, RGB) at this height of the sun."""
    if elev < -0.6:
        return (0.0, 0.0, 0.0)
    m = _air_mass(elev)
    alt = max(0.0, float(sky.get("altitude", 100.0)) - 100.0)
    out = []
    for c in range(3):
        tau = (sky.get("air", 1.0) * _A[c] * math.exp(-alt / _HR) + sky.get("aerosol", 1.0) * _B[c] * math.exp(-alt / _HM)
               + sky.get("ozone", 1.0) * _O[c])
        out.append(_E0[c] * math.exp(-m * tau))
    if elev < 0.5:                                   # the disc going under the horizon
        f = max(0.0, (elev + 0.6) / 1.1)
        out = [x * f * f for x in out]
    return tuple(out)


def _dip(height):
    """Degrees the horizon dips for something at this height (m): the sun sets later up there."""
    return math.degrees(math.sqrt(2.0 * max(0.0, height) / 6371000.0))


def sun_disc_display(elev, sky):
    """Colour of the sun disc as a photo shows it (display level, after the exposure): its own colour - white-yellow
    high up, orange and then red at the horizon, from the same transmission of the air as the sunlight - and a
    brightness that falls with it but stays above everything else (a photo exposed for the sky keeps the low sun
    round and coloured; the real radiance would burn it white at any height). None when it is under the horizon."""
    half = max(0.05, 0.545) / 2.0
    if elev < -half:
        return None
    e = sun_rgb(max(elev, 0.0), sky)
    mx = max(e)
    if mx <= 0:
        return None
    ref = sun_rgb(55.0, DEFAULTS["sky"])
    lum = lambda c: 0.2126 * c[0] + 0.7152 * c[1] + 0.0722 * c[2]
    T = max(0.0, lum(e) / max(1e-9, lum(ref)))
    L = 2.0 + 28.0 * T ** 0.75
    return [x / mx * L for x in e]


def sky_irradiance(elev, sky):
    """Light from the sky (without sun) on a horizontal surface, model units (measured on the sky model)."""
    if elev > -1.0:
        e = 17.5 * (1.0 - math.exp(-(elev + 1.0) / 11.0)) + 0.35
    else:
        e = 0.35 * math.exp((elev + 1.0) / 2.6)      # twilight
    return e * (0.85 + 0.15 * min(3.0, sky.get("aerosol", 1.0)))


# ---------------------------------------------------------------- state

def state():
    w = bpy.context.scene.world
    raw = w.get(KEY) if w is not None else None
    if not raw:
        return None
    try:
        s = json.loads(raw)
    except ValueError:
        return None
    return _merge(copy.deepcopy(DEFAULTS), s)


def _merge(base, extra):
    for k, v in (extra or {}).items():
        if isinstance(v, dict) and isinstance(base.get(k), dict):
            _merge(base[k], v)
        else:
            base[k] = v
    return base


def active():
    s = state()
    return s is not None and s.get("mode") in ("sky", "hdri")


def outdoor(s):
    """Sky or HDRI: an Ambiente with its sun (not a studio background)."""
    return s is not None and s.get("mode") in ("sky", "hdri")


def _hour_for_elev(elev, pm, sun):
    """Hour of the day (local solar time) when the sun is at this height (closest one), for the date and place."""
    from .scene_ops import sun_vector
    best, best_d = 12.0, 1e9
    rng = [12.0 + i * 0.02 for i in range(0, 601)] if pm else [12.0 - i * 0.02 for i in range(0, 601)]
    for h in rng:
        z = sun_vector(h, 0.0, sun["day"], sun["lat"]).z
        d = abs(math.degrees(math.asin(max(-1.0, min(1.0, z)))) - elev)
        if d < best_d:
            best, best_d = h, d
    return round(best, 2)


def preset_state(pid, current=None):
    base = copy.deepcopy(DEFAULTS)
    if current:                                       # the place, the date and the ground stay the user's
        base["sun"].update({k: current["sun"][k] for k in ("day", "lat", "north") if k in current.get("sun", {})})
        base["ground"] = copy.deepcopy(current.get("ground", base["ground"]))
        base["exposure"] = copy.deepcopy(current.get("exposure", base["exposure"]))
        base["hdri"] = copy.deepcopy(current.get("hdri", base["hdri"]))       # (the HDRI chosen stays for later)
        base["rain"] = copy.deepcopy(current.get("rain", base["rain"]))       # (the rain is not part of a preset)
        base["snow"] = copy.deepcopy(current.get("snow", base["snow"]))       # (nor the snow)
        cf = current.get("fog", {})                   # (1.75.49) the shape and colour of the fog stay the user's
        base["fog"].update({k: copy.deepcopy(cf[k]) for k in ("low", "height", "falloff", "start", "tint", "color", "haze2", "noise", "noiseScale", "glow") if k in cf})
        cc = current.get("clouds", {})                # the volumetric clouds stay on, with their shape
        base["clouds"].update({k: cc[k] for k in ("volumetric", "type", "height", "thickness", "flat", "puff", "density",
                                                  "shadows", "layer2", "layer2Cover") if k in cc})
    p = next((x for x in PRESETS if x[0] == pid), None)
    if p is None:
        raise ApiError(tr("Ambiente sconosciuto: {0}", pid))
    ch = copy.deepcopy(p[2])
    user = list((current or {}).get("user", []))
    for gk in user:                                   # advanced settings changed by the user: they stay (sun first:
        g, _, k = gk.partition(".")                   # the hour of the preset is found for the date and place)
        if g == "sun" and k in current.get("sun", {}):
            base["sun"][k] = current["sun"][k]
    if "elev" in ch:
        base["sun"]["hour"] = _hour_for_elev(ch.pop("elev"), ch.pop("pm", True), base["sun"])
    if "hour" in ch:
        base["sun"]["hour"] = ch.pop("hour")
    _merge(base, ch)
    for gk in user:
        g, _, k = gk.partition(".")
        if g in base and isinstance(base[g], dict) and k in current.get(g, {}):
            base[g][k] = copy.deepcopy(current[g][k])
    base["user"] = user
    base["preset"] = pid
    return base


def _adv_reference(s):
    """What the advanced settings would be without the user's changes: the preset's values (or the defaults), the
    shape of the cloud type chosen."""
    pid = s.get("preset")
    try:
        ref = preset_state(pid) if pid not in (None, "custom", "studio") else copy.deepcopy(DEFAULTS)
    except ApiError:
        ref = copy.deepcopy(DEFAULTS)
    t = clouds.TYPES.get(s.get("clouds", {}).get("type") or "cumuli_piccoli", {})
    for k in CLOUD_SHAPE:
        if k in t:
            ref["clouds"][k] = t[k]
    ref["clouds"]["shadows"] = True
    return ref


def adv_changed(s):
    """Per group: is an advanced setting away from its reference (the orange dot of the panel)."""
    if not s:
        return {}
    ref = _adv_reference(s)
    out = {}
    for g, keys in ADVANCED.items():
        ch = False
        for k in keys:
            a, b = s.get(g, {}).get(k), ref.get(g, {}).get(k)
            if isinstance(a, (int, float)) and isinstance(b, (int, float)) and not isinstance(a, bool):
                ch = ch or abs(float(a) - float(b)) > 1e-6 * max(1.0, abs(float(b)))
            else:
                ch = ch or a != b
        out[g] = ch
    return out


# ---------------------------------------------------------------- apply

def apply(new=None, partial=None, from_studio=False):
    """Sets the whole ambience (new) or changes some of its settings (partial, merged into the current one)."""
    s = new if new is not None else (state() or copy.deepcopy(DEFAULTS))
    if partial:
        if partial.get("preset"):
            s = preset_state(partial["preset"], s)
        user = set(s.get("user", []))
        reset = partial.get("resetAdvanced")
        if reset in ADVANCED:                          # "Valori predefiniti" of an Avanzate box
            ref = _adv_reference(s)
            for k in ADVANCED[reset]:
                s[reset][k] = copy.deepcopy(ref[reset][k])
                user.discard(reset + "." + k)
        for g, keys in ADVANCED.items():
            part = partial.get(g)
            if isinstance(part, dict) and not partial.get("fromPhoto"):   # (a photo is not the user's own change)
                if g == "clouds" and part.get("type"):  # a new cloud type brings its own shape
                    user -= {"clouds." + k for k in CLOUD_SHAPE}
                user |= {g + "." + k for k in keys if k in part}
        s["user"] = sorted(user)
        rest = {k: v for k, v in partial.items() if k not in ("preset", "resetAdvanced", "fromPhoto")}
        cl = rest.get("clouds")
        if isinstance(cl, dict) and cl.get("type"):
            # a type of cloud: its shape (coverage, size, heights, puffs...) unless the same call sets them too
            from .clouds import TYPES
            preset = TYPES.get(cl["type"])
            if preset is None:
                raise ApiError(tr("Tipo di nuvole non valido"))
            rest["clouds"] = dict(preset, **cl)
        if rest:
            _merge(s, rest)
            if set(rest) - {"rain", "snow"}:              # (the rain is not part of a preset: the preset stays chosen)
                s["preset"] = partial.get("presetKeep") or "custom"
    s = _merge(copy.deepcopy(DEFAULTS), s)
    s["sun"]["hour"] = max(0.0, min(24.0, float(s["sun"]["hour"])))
    s["clouds"]["cover"] = max(0.0, min(1.0, float(s["clouds"]["cover"])))
    s["fog"]["density"] = max(0.0, min(1.0, float(s["fog"]["density"])))
    fg = s["fog"]
    fg["height"] = max(0.0, min(500.0, float(fg.get("height", 10.0))))
    fg["falloff"] = max(0.5, min(1000.0, float(fg.get("falloff", 20.0))))
    fg["start"] = max(0.0, min(2000.0, float(fg.get("start", 0.0))))
    col = fg.get("color") if isinstance(fg.get("color"), list) and len(fg.get("color")) == 3 else [0.80, 0.84, 0.90]
    fg["color"] = [max(0.0, min(1.0, float(c))) for c in col]
    fg["low"], fg["tint"] = bool(fg.get("low")), bool(fg.get("tint"))
    fg["haze2"] = max(0.0, min(1.0, float(fg.get("haze2", 0.0))))
    fg["noise"] = max(0.0, min(1.0, float(fg.get("noise", 0.0))))
    fg["noiseScale"] = max(1.0, min(500.0, float(fg.get("noiseScale", 25.0))))
    fg["glow"] = max(0.0, min(1.0, float(fg.get("glow", 0.6))))
    from . import rain
    rain.clamp_state(s)
    rain.update(s)          # wet surfaces and puddles (the materials follow before the next path-traced image)
    from . import snowfall, raindrops
    snowfall.touch()        # (the flakes that fall: looked at again in the engine's idle time)
    raindrops.touch()       # (the drops likewise)
    scene = bpy.context.scene
    from . import scene_ops, dusk
    dusk.update(s)          # lamps and emissions "from dusk to dawn" follow the hour (before the exposure)
    if s["mode"] == "studio":
        if not scene.world or scene.world.get("simpler_env") not in ("studio_morbido", "studio_contrasto", "notte"):
            scene_ops.set_environment("studio_morbido", 1.0)
        _remove(MOON_KEY)
        _ground(None)
        _fog(None)
        clouds.remove()
        scene.world[KEY] = json.dumps(s)
        _sun_object(create=False, release=True)
        _bump()
        return info()
    force_ground = bool(partial) and "ground" in partial      # the user chose a ground in the panel
    if partial is not None and "ground" not in partial and not from_studio:   # (a whole state - new scene, undo, view - is applied as it is)
        _ground_follows_user(s)
    if s["mode"] == "hdri":
        clouds.remove()
        _apply_hdri(s, force_ground)
        _bump()
        return info()
    w = scene_ops._world()
    v = _sun_dir(s)
    elev = math.degrees(math.asin(max(-1.0, min(1.0, v.z))))
    if elev < -4 and (float(s["night"].get("stars", 0.1)) > 0 or float(s["night"].get("moon", 1.0)) > 0):
        from . import night as nt
        if not nt.ready():
            nt.download()                  # the real stars and the moon (once): until they arrive, the drawn stars
    _world_nodes(w, s, v, elev)
    w["simpler_env"] = "ambience"
    w[KEY] = json.dumps(s)
    dk = w.node_tree.nodes.get("sun_disc_k")
    if dk is not None:
        dk.outputs[0].default_value = max(2.0 ** (-auto_ev()), float(dk.get("min_k", 0.0)))
    _sun(s, v, elev)
    _moon(s, v, elev)
    _ground(s["ground"]["type"], force_ground)
    _fog(s)
    clouds.update(s, v, elev)
    _bump()
    return info()


def _hdri_analysis(s):
    from . import hdri
    path = hdri.file_of(s["hdri"].get("id", ""))
    if not path:
        raise ApiError(tr("HDRI non disponibile: scaricalo dalla libreria"))
    return path, hdri.analyze(path)


def _apply_hdri(s, force_ground=False):
    """A photographed sky (hdri.py): the picture as background and light, its sun as the Sun light."""
    from . import hdri, scene_ops
    h = s["hdri"]
    h["rotation"] = float(h.get("rotation", 0.0)) % 360.0
    h["strength"] = max(0.0, min(20.0, float(h.get("strength", 1.0))))
    path, a = _hdri_analysis(s)
    use_sun = bool(h.get("sun", True)) and a.get("sun") is not None
    w = scene_ops._world()
    hdri.build_world(w, path, h["rotation"], h["strength"], a["threshold"] if use_sun else 0.0)
    w[KEY] = json.dumps(s)
    if use_sun:
        ob = _sun_object()
        sun = a["sun"]
        e = [max(0.0, x) * h["strength"] for x in sun["rgb"]]
        mx = max(e) if max(e) > 0 else 1.0
        d = ob.data
        if hasattr(d, "use_temperature"):
            d.use_temperature = False
        d.color = tuple(x / mx for x in e)
        d.energy = mx
        d.angle = math.radians(sun["size"])
        _aim_sun(ob, Vector(hdri.world_dir(sun["dir"], h["rotation"])).normalized())
        ob["simpler_sun"] = json.dumps({"power": d.energy, "hdri": True})
    else:
        _remove(SUN_KEY)
    _remove(MOON_KEY)
    _ground(s["ground"]["type"], force_ground)
    _fog(None)                                  # (the haze is in the photograph)


_REV = {"n": 0}


def _bump():
    _REV["n"] += 1
    from . import render
    render.invalidate()


def _sun_dir(s):
    from .scene_ops import sun_vector
    sun = s["sun"]
    return sun_vector(float(sun["hour"]), float(sun["north"]), float(sun["day"]), float(sun["lat"]))


def _volumetric(s):
    return clouds.active(s)


def _cloud_dim(s, lights=False):
    """How much the clouds dim the light. Painted clouds: an estimate on sun, moon and sky. Volumetric clouds cast
    their own shadows (lights=True: no dimming), and for exposure and haze only the average."""
    c = s["clouds"]["cover"]
    if _volumetric(s):
        return 1.0 if lights else 1.0 - 0.55 * c ** 1.3
    return 1.0 - 0.92 * c ** 1.3


def _drawn_stars(N, L, s, elev, tc, sep, col):
    """The stars drawn by noise (before the real sky map arrives, or without it)."""
    stars = float(s["night"].get("stars", 0.1))
    if elev < -6 and stars > 0:
        vor = N.new("ShaderNodeTexVoronoi")
        vor.feature = "F1"
        vor.inputs["Scale"].default_value = 260.0
        L.new(tc.outputs["Generated"], vor.inputs["Vector"])
        pt = N.new("ShaderNodeMapRange"); pt.interpolation_type = "SMOOTHSTEP"
        pt.inputs[1].default_value = 0.06; pt.inputs[2].default_value = 0.0
        L.new(vor.outputs["Distance"], pt.inputs[0])
        sel = N.new("ShaderNodeMapRange"); sel.inputs[1].default_value = 0.82; sel.inputs[2].default_value = 1.0
        sepc = N.new("ShaderNodeSeparateColor"); L.new(vor.outputs["Color"], sepc.inputs[0]); L.new(sepc.outputs[0], sel.inputs[0])
        st = N.new("ShaderNodeMath"); st.operation = "MULTIPLY"; L.new(pt.outputs[0], st.inputs[0]); L.new(sel.outputs[0], st.inputs[1])
        up = N.new("ShaderNodeMapRange"); up.inputs[1].default_value = 0.0; up.inputs[2].default_value = 0.08; L.new(sep.outputs[2], up.inputs[0])
        st2 = N.new("ShaderNodeMath"); st2.operation = "MULTIPLY"; L.new(st.outputs[0], st2.inputs[0]); L.new(up.outputs[0], st2.inputs[1])
        fade = max(0.0, min(1.0, (-6.0 - elev) / 10.0))
        st3 = N.new("ShaderNodeMath"); st3.operation = "MULTIPLY"; L.new(st2.outputs[0], st3.inputs[0])
        st3.inputs[1].default_value = K * 2.5 * stars * fade      # (stars 10% = the drawn stars of before at 100%)
        add = N.new("ShaderNodeMix"); add.data_type = "RGBA"; add.blend_type = "ADD"; add.inputs[0].default_value = 1.0
        L.new(col, add.inputs[6]); L.new(st3.outputs[0], add.inputs[7])
        col = add.outputs[2]
    return col


def moon_dir(s, v, elev):
    """Where the moon is: opposite the sun, fairly high (automatic), or at the height and direction chosen."""
    n = s["night"]
    if n.get("moonAuto", True):
        az = math.atan2(v.y, v.x) + math.pi
        el = math.radians(max(18.0, min(55.0, -elev * 1.2)))
        return Vector((math.cos(el) * math.cos(az), math.cos(el) * math.sin(az), math.sin(el)))
    t = math.radians(float(s["sun"]["north"]))
    n_dir = Vector((math.sin(t), math.cos(t), 0.0))
    e_dir = Vector((math.cos(t), -math.sin(t), 0.0))
    az = math.radians(float(n.get("moonAz", 135.0)))
    el = math.radians(max(-5.0, min(89.0, float(n.get("moonElev", 35.0)))))
    h = n_dir * math.cos(az) + e_dir * math.sin(az)
    return (h * math.cos(el) + Vector((0.0, 0.0, math.sin(el)))).normalized()


MOON_RADIUS = math.radians(0.26)        # half of the real size of the moon in the sky
STARS_K = 0.08                           # radiance of a very bright star (the 99.99th percentile of the map) at 100%
MOON_DISC_K = 0.05                       # radiance of the full moon's disc at 100% (seen well at the night exposure)
EARTHSHINE = 0.012


def moon_geometry(s, v, elev):
    """Everything the disc needs (also sent to the real-time view): direction m, frame r (right) / u (up), sin of the
    radius, lit direction (x, z), brightness of disc and halo."""
    from . import night as nt
    n = s["night"]
    m = moon_dir(s, v, elev)
    r = m.cross(Vector((0.0, 0.0, 1.0)))
    r = r.normalized() if r.length > 1e-6 else Vector((1.0, 0.0, 0.0))
    u = r.cross(m).normalized()
    radius = MOON_RADIUS * max(0.25, min(12.0, float(n.get("moonSize", 4.0))))
    lx, lz = nt.lit_dir(n.get("phase", 0.5))
    fade = max(0.0, min(1.0, (-4.0 - elev) / 6.0))       # (the moon shows once the sun is down)
    return {"m": m, "r": r, "u": u, "sinR": math.sin(radius), "radius": radius, "lx": lx, "lz": lz,
            "disc": MOON_DISC_K * max(0.0, float(n.get("disc", 0.6))) * fade * _cloud_dim(s, lights=True),
            "halo": 0.004 * max(0.0, float(n.get("halo", 0.6))) * nt.phase_light(n.get("phase", 0.5)) * fade,
            "visible": elev < -4 and m.z > -0.02 and float(n.get("moon", 1.0)) > 0}


def _night_sky(N, L, s, v, elev, d, sep, col, old_stars):
    """Stars (the real sky map, turned to the place and the hour) and the moon disc, added to the sky colour. The
    value node "night_k" multiplies both: 0 in the picture baked for the real-time view, which draws its own."""
    from . import night as nt
    stars = float(s["night"].get("stars", 0.1))
    info = nt.prepare() if elev < -4 else None
    if info is None:
        return old_stars(col) if elev < -6 and stars > 0 else col
    kn = N.new("ShaderNodeValue"); kn.name = "night_k"; kn.outputs[0].default_value = 1.0

    def dotc(vec):
        n_ = N.new("ShaderNodeVectorMath"); n_.operation = "DOT_PRODUCT"
        L.new(d, n_.inputs[0]); n_.inputs[1].default_value = tuple(vec)
        return n_.outputs["Value"]

    def math_(op, a, b=None, clamp=False):
        n_ = N.new("ShaderNodeMath"); n_.operation = op; n_.use_clamp = clamp
        for i, x in enumerate((a, b)):
            if x is None:
                continue
            if isinstance(x, (int, float)):
                n_.inputs[i].default_value = float(x)
            else:
                L.new(x, n_.inputs[i])
        return n_.outputs[0]

    def add_rgb(c, rgb_socket):
        mx = N.new("ShaderNodeMix"); mx.data_type = "RGBA"; mx.blend_type = "ADD"; mx.inputs[0].default_value = 1.0
        L.new(c, mx.inputs[6]); L.new(rgb_socket, mx.inputs[7])
        return mx.outputs[2]

    def scale_rgb(rgb_socket, k_socket):
        mx = N.new("ShaderNodeVectorMath"); mx.operation = "SCALE"
        L.new(rgb_socket, mx.inputs[0]); L.new(k_socket, mx.inputs["Scale"])
        return mx.outputs[0]

    # ---- stars: direction -> declination and hour angle -> right ascension -> the map
    fade = max(0.0, min(1.0, (-6.0 - elev) / 10.0))
    if stars > 0 and fade > 0:
        P, A, B, lst = nt.frames(s["sun"])
        dec = math_("ARCSINE", math_("MINIMUM", math_("MAXIMUM", dotc(P), -1.0), 1.0))
        ha = math_("ARCTAN2", dotc(B), dotc(A))
        # u = 0.5 - (lst - H) / 2pi (right ascension grows to the left), v = 0.5 + dec / pi
        uu = math_("MULTIPLY_ADD", ha, 1.0 / (2 * math.pi))
        uu.node.inputs[2].default_value = 0.5 - lst / (2 * math.pi)
        vv = math_("MULTIPLY_ADD", dec, 1.0 / math.pi)
        vv.node.inputs[2].default_value = 0.5
        cv = N.new("ShaderNodeCombineXYZ"); L.new(uu, cv.inputs[0]); L.new(vv, cv.inputs[1])
        img = N.new("ShaderNodeTexImage"); img.image = nt._image(nt.file_of("stars"), "Linear Rec.709")
        img.extension = "REPEAT"; img.interpolation = "Cubic"
        L.new(cv.outputs[0], img.inputs["Vector"])
        up = N.new("ShaderNodeMapRange"); up.inputs[1].default_value = -0.01; up.inputs[2].default_value = 0.06
        L.new(sep.outputs[2], up.inputs[0])
        k = math_("MULTIPLY", up.outputs[0], STARS_K * stars * fade / max(1e-9, info["norm"]))
        k = math_("MULTIPLY", k, kn.outputs[0])
        col = add_rgb(col, scale_rgb(img.outputs["Color"], k))

    # ---- the moon: its near side on a disc, lit by the phase
    g = moon_geometry(s, v, elev)
    if g["visible"]:
        sinR = g["sinR"]
        x = math_("DIVIDE", dotc(g["r"]), sinR)
        y = math_("DIVIDE", dotc(g["u"]), sinR)
        cm = dotc(g["m"])
        rho2 = math_("ADD", math_("MULTIPLY", x, x), math_("MULTIPLY", y, y))
        rho = math_("SQRT", rho2)
        # inside the disc, with an edge one pixel-ish soft (2% of the radius); only on the side of the sky it is in
        mask = math_("MULTIPLY", math_("DIVIDE", math_("SUBTRACT", 1.0, rho), 0.02, clamp=True), math_("GREATER_THAN", cm, 0.0))
        z = math_("SQRT", math_("MAXIMUM", math_("SUBTRACT", 1.0, rho2), 0.0))
        lon = math_("ARCTAN2", x, z)
        lat = math_("ARCSINE", math_("MINIMUM", math_("MAXIMUM", y, -1.0), 1.0))
        tu = math_("MULTIPLY_ADD", lon, 1.0 / (2 * math.pi)); tu.node.inputs[2].default_value = 0.5
        tv = math_("MULTIPLY_ADD", lat, 1.0 / math.pi); tv.node.inputs[2].default_value = 0.5
        ct = N.new("ShaderNodeCombineXYZ"); L.new(tu, ct.inputs[0]); L.new(tv, ct.inputs[1])
        mi = N.new("ShaderNodeTexImage"); mi.image = nt._image(nt.file_of("moon"), "sRGB")
        mi.extension = "EXTEND"; mi.interpolation = "Linear"
        L.new(ct.outputs[0], mi.inputs["Vector"])
        shade = math_("MAXIMUM", math_("ADD", math_("MULTIPLY", x, g["lx"]), math_("MULTIPLY", z, g["lz"])), 0.0)
        shade = math_("ADD", shade, EARTHSHINE)
        k = math_("MULTIPLY", math_("MULTIPLY", shade, mask), g["disc"] / max(1e-6, info["moonMean"]))
        k = math_("MULTIPLY", k, kn.outputs[0])
        col = add_rgb(col, scale_rgb(mi.outputs["Color"], k))
        # halo: a soft glow around the disc (the moon seen through the air), bluish white
        if g["halo"] > 0:
            ang = math_("ARCCOSINE", math_("MINIMUM", math_("MAXIMUM", cm, -1.0), 1.0))
            t = math_("DIVIDE", math_("MAXIMUM", math_("SUBTRACT", ang, g["radius"]), 0.0), math.radians(3.0))
            hk = math_("MULTIPLY", math_("EXPONENT", math_("MULTIPLY", t, -1.0)), g["halo"])
            hk = math_("MULTIPLY", math_("MULTIPLY", hk, math_("SUBTRACT", 1.0, mask, clamp=True)), kn.outputs[0])
            hc = N.new("ShaderNodeCombineColor"); hc.inputs[0].default_value = 0.8; hc.inputs[1].default_value = 0.86; hc.inputs[2].default_value = 1.0
            col = add_rgb(col, scale_rgb(hc.outputs[0], hk))
    return col


def _world_nodes(w, s, v, elev):
    nt = w.node_tree
    nt.nodes.clear()
    N, L = nt.nodes, nt.links
    out = N.new("ShaderNodeOutputWorld")
    bg = N.new("ShaderNodeBackground")
    bg.inputs[1].default_value = 1.0
    sky_s = s["sky"]
    rot = math.atan2(-v.x, v.y) % (2 * math.pi)
    ground_col = _ground_color(s["ground"]["type"])

    def sky_node(disc):
        n = N.new("ShaderNodeTexSky")
        try:
            n.sky_type = "MULTIPLE_SCATTERING"
        except TypeError:
            pass
        n.sun_disc = disc
        n.sun_elevation = math.radians(elev)
        n.sun_rotation = rot
        n.sun_size = math.radians(max(0.05, float(s["sun"]["size"])))
        n.altitude = max(0.0, float(sky_s["altitude"]))
        n.air_density = max(0.0, float(sky_s["air"]))
        n.aerosol_density = max(0.0, float(sky_s["aerosol"]))
        n.ozone_density = max(0.0, float(sky_s["ozone"]))
        try:
            n.ground_albedo = sum(ground_col) / 3.0
        except (AttributeError, TypeError):
            pass
        return n

    amb = K * max(0.0, float(sky_s.get("ambient", 1.0)))
    plain = sky_node(False)
    col = plain.outputs[0]
    scale = N.new("ShaderNodeMix"); scale.data_type = "RGBA"; scale.blend_type = "MULTIPLY"; scale.inputs[0].default_value = 1.0
    L.new(col, scale.inputs[6]); scale.inputs[7].default_value = (amb, amb, amb, 1.0)
    col = scale.outputs[2]

    tc = N.new("ShaderNodeTexCoord")
    sep = N.new("ShaderNodeSeparateXYZ")
    L.new(tc.outputs["Generated"], sep.inputs[0])

    # direction of each ray against the sun (for the disc and the glow of the haze around the sun)
    nrm = N.new("ShaderNodeVectorMath"); nrm.operation = "NORMALIZE"
    L.new(tc.outputs["Generated"], nrm.inputs[0])
    dot = N.new("ShaderNodeVectorMath"); dot.operation = "DOT_PRODUCT"
    L.new(nrm.outputs[0], dot.inputs[0]); dot.inputs[1].default_value = tuple(v)

    # night sky: stars (only once the sun is well under the horizon: they cost nothing by day) and the moon disc
    col = _night_sky(N, L, s, v, elev, nrm.outputs[0], sep, col, old_stars=lambda c: _drawn_stars(N, L, s, elev, tc, sep, c))

    # clouds: a layer painted on the sky (projected on a plane above), lit by sun and sky
    cover = s["clouds"]["cover"]
    if cover > 0.005:
        zc = N.new("ShaderNodeMath"); zc.operation = "MAXIMUM"; zc.inputs[1].default_value = 0.03; L.new(sep.outputs[2], zc.inputs[0])
        dx = N.new("ShaderNodeMath"); dx.operation = "DIVIDE"; L.new(sep.outputs[0], dx.inputs[0]); L.new(zc.outputs[0], dx.inputs[1])
        dy = N.new("ShaderNodeMath"); dy.operation = "DIVIDE"; L.new(sep.outputs[1], dy.inputs[0]); L.new(zc.outputs[0], dy.inputs[1])
        cb = N.new("ShaderNodeCombineXYZ"); L.new(dx.outputs[0], cb.inputs[0]); L.new(dy.outputs[0], cb.inputs[1])
        cb.inputs[2].default_value = float(s["clouds"].get("seed", 7)) * 3.17
        nz = N.new("ShaderNodeTexNoise")
        try:
            nz.noise_dimensions = "3D"
        except TypeError:
            pass
        sc = float(s["clouds"].get("scale", 0.5))
        nz.inputs["Scale"].default_value = 1.6 - 1.3 * sc          # larger = bigger cloud masses
        nz.inputs["Detail"].default_value = 4.0
        nz.inputs["Roughness"].default_value = 0.55
        L.new(cb.outputs[0], nz.inputs["Vector"])
        soft = float(s["clouds"].get("soft", 0.5))
        t = 0.68 - 0.36 * cover
        mr = N.new("ShaderNodeMapRange"); mr.interpolation_type = "SMOOTHSTEP"
        mr.inputs[1].default_value = t - 0.02 - 0.06 * soft; mr.inputs[2].default_value = t + 0.03 + 0.12 * soft
        L.new(nz.outputs["Fac"], mr.inputs[0])
        hz = N.new("ShaderNodeMapRange"); hz.interpolation_type = "SMOOTHSTEP"
        hz.inputs[1].default_value = 0.0; hz.inputs[2].default_value = 0.15
        L.new(sep.outputs[2], hz.inputs[0])
        mk = N.new("ShaderNodeMath"); mk.operation = "MULTIPLY"; L.new(mr.outputs[0], mk.inputs[0]); L.new(hz.outputs[0], mk.inputs[1])
        # with volumetric clouds the painted ones stay only beyond the volume (towards the horizon, where it fades
        # out: clouds down to the horizon); the 360-degree photo of the sky (bake) keeps them all ("painted_clouds")
        pc = N.new("ShaderNodeValue"); pc.name = "painted_clouds"
        pc.outputs[0].default_value = 0.0 if _volumetric(s) else 1.0
        if _volumetric(s):
            from . import clouds as _cl
            hcl = float(_cl.settings(s)["height"])
            far = N.new("ShaderNodeMapRange")
            far.inputs[1].default_value = math.sin(math.atan2(hcl, 0.97 * _cl.HALF_WIDTH))
            far.inputs[2].default_value = math.sin(math.atan2(hcl, 0.6 * _cl.HALF_WIDTH))
            far.inputs[3].default_value = 1.0; far.inputs[4].default_value = 0.0
            L.new(sep.outputs[2], far.inputs[0])
            pmx = N.new("ShaderNodeMath"); pmx.operation = "MAXIMUM"; L.new(far.outputs[0], pmx.inputs[0]); L.new(pc.outputs[0], pmx.inputs[1])
            pcv = pmx.outputs[0]
        else:
            pcv = pc.outputs[0]
        mk2 = N.new("ShaderNodeMath"); mk2.operation = "MULTIPLY"; L.new(mk.outputs[0], mk2.inputs[0]); L.new(pcv, mk2.inputs[1])
        mk = mk2
        th = N.new("ShaderNodeMapRange"); th.inputs[1].default_value = t; th.inputs[2].default_value = t + 0.3
        L.new(nz.outputs["Fac"], th.inputs[0])
        # lit by the sun as it is up there (the clouds see it a little longer than the ground: pink after sunset)
        from . import clouds as _cl
        e_up = elev + _dip(float(_cl.settings(s)["height"]))
        e_sun = sun_rgb(e_up, sky_s)
        e_sky = sky_irradiance(elev, sky_s)
        sin_e = max(0.0, math.sin(math.radians(e_up)))
        lit = [(e_sun[c] * (0.35 + 0.65 * sin_e) + e_sky) * K / math.pi * 0.9 for c in range(3)]
        if e_up < -6:                                # moonlit clouds
            lit = [K * 0.0008, K * 0.0009, K * 0.0011]
        dark = [x * (0.38 + 0.25 * (1 - cover)) for x in lit]
        cc = N.new("ShaderNodeMix"); cc.data_type = "RGBA"
        L.new(th.outputs[0], cc.inputs[0])
        cc.inputs[6].default_value = (*lit, 1.0); cc.inputs[7].default_value = (*dark, 1.0)
        fin = N.new("ShaderNodeMix"); fin.data_type = "RGBA"
        L.new(mk.outputs[0], fin.inputs[0]); L.new(col, fin.inputs[6]); L.new(cc.outputs[2], fin.inputs[7])
        col = fin.outputs[2]
    # cirrus: thin streaks high up (~9 km), painted on the sky: stretched by the wind, half see-through, lit by the
    # sun as it is up there - the last clouds to stay pink and orange after sunset. Also in the real-time view.
    cir = float(s["clouds"].get("cirrus", 0.0))
    if cir > 0.005:
        zc2 = N.new("ShaderNodeMath"); zc2.operation = "MAXIMUM"; zc2.inputs[1].default_value = 0.02; L.new(sep.outputs[2], zc2.inputs[0])
        cx = N.new("ShaderNodeMath"); cx.operation = "DIVIDE"; L.new(sep.outputs[0], cx.inputs[0]); L.new(zc2.outputs[0], cx.inputs[1])
        cy2 = N.new("ShaderNodeMath"); cy2.operation = "DIVIDE"; L.new(sep.outputs[1], cy2.inputs[0]); L.new(zc2.outputs[0], cy2.inputs[1])
        cv = N.new("ShaderNodeCombineXYZ"); L.new(cx.outputs[0], cv.inputs[0]); L.new(cy2.outputs[0], cv.inputs[1])
        cv.inputs[2].default_value = float(s["clouds"].get("seed", 7)) * 1.91
        mp = N.new("ShaderNodeMapping")
        wind = (float(s["clouds"].get("seed", 7)) * 47.0) % 180.0
        mp.inputs["Rotation"].default_value = (0.0, 0.0, math.radians(wind))
        mp.inputs["Scale"].default_value = (0.5, 3.0, 1.0)            # streaks: long across the wind direction
        # the streaks bend: their coordinates warped by a slow noise
        wn = N.new("ShaderNodeTexNoise"); wn.inputs["Scale"].default_value = 0.35; wn.inputs["Detail"].default_value = 1.0
        L.new(cv.outputs[0], wn.inputs["Vector"])
        wsub = N.new("ShaderNodeVectorMath"); wsub.operation = "SUBTRACT"; L.new(wn.outputs["Color"], wsub.inputs[0])
        wsub.inputs[1].default_value = (0.5, 0.5, 0.5)
        wsc = N.new("ShaderNodeVectorMath"); wsc.operation = "SCALE"; wsc.inputs["Scale"].default_value = 1.6
        L.new(wsub.outputs[0], wsc.inputs[0])
        wadd = N.new("ShaderNodeVectorMath"); wadd.operation = "ADD"; L.new(cv.outputs[0], wadd.inputs[0]); L.new(wsc.outputs[0], wadd.inputs[1])
        L.new(wadd.outputs[0], mp.inputs["Vector"])
        # in patches, not over the whole sky
        pn = N.new("ShaderNodeTexNoise"); pn.inputs["Scale"].default_value = 0.22; pn.inputs["Detail"].default_value = 2.0
        L.new(cv.outputs[0], pn.inputs["Vector"])
        pm = N.new("ShaderNodeMapRange"); pm.interpolation_type = "SMOOTHSTEP"
        pm.inputs[1].default_value = 0.44 - 0.14 * cir; pm.inputs[2].default_value = 0.62 - 0.10 * cir
        L.new(pn.outputs["Fac"], pm.inputs[0])
        cn = N.new("ShaderNodeTexNoise")
        cn.inputs["Scale"].default_value = 1.2
        cn.inputs["Detail"].default_value = 8.0
        cn.inputs["Roughness"].default_value = 0.62
        cn.inputs["Distortion"].default_value = 0.8
        L.new(mp.outputs["Vector"], cn.inputs["Vector"])
        ct = 0.56 - 0.16 * cir
        cm = N.new("ShaderNodeMapRange"); cm.interpolation_type = "SMOOTHSTEP"
        cm.inputs[1].default_value = ct; cm.inputs[2].default_value = ct + 0.16
        L.new(cn.outputs["Fac"], cm.inputs[0])
        chz = N.new("ShaderNodeMapRange"); chz.interpolation_type = "SMOOTHSTEP"
        chz.inputs[1].default_value = 0.0; chz.inputs[2].default_value = 0.06
        L.new(sep.outputs[2], chz.inputs[0])
        ca0 = N.new("ShaderNodeMath"); ca0.operation = "MULTIPLY"; L.new(cm.outputs[0], ca0.inputs[0]); L.new(pm.outputs[0], ca0.inputs[1])
        ca = N.new("ShaderNodeMath"); ca.operation = "MULTIPLY"; L.new(ca0.outputs[0], ca.inputs[0]); L.new(chz.outputs[0], ca.inputs[1])
        ca2 = N.new("ShaderNodeMath"); ca2.operation = "MULTIPLY"; L.new(ca.outputs[0], ca2.inputs[0])
        ca2.inputs[1].default_value = 0.35 + 0.35 * cir
        e_hi = elev + _dip(9000.0)
        es_hi = sun_rgb(e_hi, sky_s)
        sk = sky_irradiance(elev, sky_s)
        # thin ice: lit through, brighter than a thick cloud's side; at night barely there
        clit = [(es_hi[c] * 0.55 + sk * 0.9) * K / math.pi for c in range(3)]
        if e_hi < -6:
            clit = [K * 0.0006, K * 0.0007, K * 0.0009]
        cmix = N.new("ShaderNodeMix"); cmix.data_type = "RGBA"
        L.new(ca2.outputs[0], cmix.inputs[0]); L.new(col, cmix.inputs[6]); cmix.inputs[7].default_value = (*clit, 1.0)
        col = cmix.outputs[2]
    # night: the sky lit by the moon (deep blue, a little lighter towards the horizon)
    moon = float(s["night"].get("moon", 1.0))
    if elev < -6 and moon > 0:
        hz2 = N.new("ShaderNodeMapRange"); hz2.inputs[1].default_value = 0.0; hz2.inputs[2].default_value = 0.6
        hz2.inputs[3].default_value = 1.6; hz2.inputs[4].default_value = 0.7
        L.new(sep.outputs[2], hz2.inputs[0])
        night = N.new("ShaderNodeMix"); night.data_type = "RGBA"; night.blend_type = "MULTIPLY"; night.inputs[0].default_value = 1.0
        k = K * 0.0035 * moon * max(0.0, min(1.0, (-6.0 - elev) / 8.0))
        night.inputs[6].default_value = (0.45 * k, 0.56 * k, 1.0 * k, 1.0)
        cmb = N.new("ShaderNodeCombineColor")
        for i in range(3):
            L.new(hz2.outputs[0], cmb.inputs[i])
        L.new(cmb.outputs[0], night.inputs[7])
        add2 = N.new("ShaderNodeMix"); add2.data_type = "RGBA"; add2.blend_type = "ADD"; add2.inputs[0].default_value = 1.0
        L.new(col, add2.inputs[6]); L.new(night.outputs[2], add2.inputs[7])
        col = add2.outputs[2]
    # haze also on the sky: thick near the horizon (long path through the air), thin overhead; with a dense fog the
    # sky disappears in it, as it should. The same colour as the haze on the objects (compositor).
    glow_peak = 0.0
    dens = s["fog"]["density"]
    if dens >= 0.005:
        V = fog_visibility(dens)
        zf = N.new("ShaderNodeMath"); zf.operation = "MAXIMUM"; zf.inputs[1].default_value = 0.02; L.new(sep.outputs[2], zf.inputs[0])
        a1 = N.new("ShaderNodeMath"); a1.operation = "DIVIDE"; a1.name = "haze_k"; L.new(zf.outputs[0], a1.inputs[1])
        cz = bpy.context.scene.camera.matrix_world.translation.z if bpy.context.scene.camera else 1.6
        a1.inputs[0].default_value = -fog_column(s, cz) / V     # (1.75.49: low fog - the sky above stays clear)
        e1 = N.new("ShaderNodeMath"); e1.operation = "EXPONENT"; L.new(a1.outputs[0], e1.inputs[0])
        f1 = N.new("ShaderNodeMath"); f1.operation = "SUBTRACT"; f1.inputs[0].default_value = 1.0; L.new(e1.outputs[0], f1.inputs[1])
        # only what the camera sees: as light the sky stays the physical one (a glowing haze below the horizon lit
        # the volumetric clouds from underneath and turned a sunset pale)
        lpw = N.new("ShaderNodeLightPath")
        f2 = N.new("ShaderNodeMath"); f2.operation = "MULTIPLY"; L.new(f1.outputs[0], f2.inputs[0]); L.new(lpw.outputs["Is Camera Ray"], f2.inputs[1])
        hm = N.new("ShaderNodeMix"); hm.data_type = "RGBA"
        L.new(f2.outputs[0], hm.inputs[0]); L.new(col, hm.inputs[6])
        # the haze glows towards the sun: its droplets scatter forwards (Henyey-Greenstein, g 0.7), with the colour
        # of the sunlight - the bright orange around a low sun, where a uniform haze colour made a grey veil
        hcol = N.new("ShaderNodeMix"); hcol.data_type = "RGBA"; hcol.blend_type = "ADD"; hcol.inputs[0].default_value = 1.0
        hcol.inputs[6].default_value = (*_fog_color(s), 1.0)
        es = sun_rgb(elev, sky_s)
        if max(es) > 0:
            g = 0.75
            # P(cos) - 1/4pi = (1-g^2) / (4pi (1+g^2-2g cos)^1.5) - 1/4pi
            d1 = N.new("ShaderNodeMath"); d1.operation = "MULTIPLY_ADD"
            L.new(dot.outputs["Value"], d1.inputs[0]); d1.inputs[1].default_value = -2 * g; d1.inputs[2].default_value = 1 + g * g
            d2 = N.new("ShaderNodeMath"); d2.operation = "POWER"; L.new(d1.outputs[0], d2.inputs[0]); d2.inputs[1].default_value = 1.5
            d3 = N.new("ShaderNodeMath"); d3.operation = "DIVIDE"; d3.inputs[0].default_value = (1 - g * g) / (4 * math.pi)
            L.new(d2.outputs[0], d3.inputs[1])
            d4 = N.new("ShaderNodeMath"); d4.operation = "SUBTRACT"; d4.use_clamp = True; L.new(d3.outputs[0], d4.inputs[0])
            d4.inputs[1].default_value = 1 / (4 * math.pi)
            gc = N.new("ShaderNodeMix"); gc.data_type = "RGBA"; gc.blend_type = "MULTIPLY"; gc.inputs[0].default_value = 1.0
            amp = 0.4 * K * float(s["sky"].get("ambient", 1.0)) * (0.55 + 0.45 * _cloud_dim(s))
            glow_peak = amp * max(es) * ((1 - g * g) / (4 * math.pi * (1 - g) ** 3) - 1 / (4 * math.pi))
            gc.inputs[6].default_value = (*[x * amp for x in es], 1.0)
            gcmb = N.new("ShaderNodeCombineColor")
            for i in range(3):
                L.new(d4.outputs[0], gcmb.inputs[i])
            L.new(gcmb.outputs[0], gc.inputs[7])
            L.new(gc.outputs[2], hcol.inputs[7])
        else:
            hcol.inputs[7].default_value = (0, 0, 0, 1)
        L.new(hcol.outputs[2], hm.inputs[7])
        col = hm.outputs[2]
    # the disc of the sun (after the haze: its colour already has the air in front of it), only for camera rays (the Sun light does the lighting): our own, with the colour a photo
    # shows (sun_disc_display) instead of the real radiance, which burnt it to a white disc at any height. Darker
    # towards its edge (limb darkening), cut by the horizon. Its strength is set for the automatic exposure
    # ("sun_disc_k" = 1 / 2^EV, by apply): the Esposizione slider brightens or darkens it with the rest.
    dd = sun_disc_display(elev, sky_s)
    if dd is not None:
        half = math.radians(max(0.05, float(s["sun"]["size"]))) / 2.0
        ac = N.new("ShaderNodeMath"); ac.operation = "ARCCOSINE"; L.new(dot.outputs["Value"], ac.inputs[0])
        r = N.new("ShaderNodeMath"); r.operation = "DIVIDE"; r.inputs[1].default_value = half; L.new(ac.outputs[0], r.inputs[0])
        edge = N.new("ShaderNodeMapRange"); edge.interpolation_type = "SMOOTHSTEP"
        edge.inputs[1].default_value = 1.0; edge.inputs[2].default_value = 0.94
        L.new(r.outputs[0], edge.inputs[0])
        r2 = N.new("ShaderNodeMath"); r2.operation = "MULTIPLY"; L.new(r.outputs[0], r2.inputs[0]); L.new(r.outputs[0], r2.inputs[1])
        mu = N.new("ShaderNodeMath"); mu.operation = "SUBTRACT"; mu.use_clamp = True; mu.inputs[0].default_value = 1.0; L.new(r2.outputs[0], mu.inputs[1])
        sq = N.new("ShaderNodeMath"); sq.operation = "SQRT"; L.new(mu.outputs[0], sq.inputs[0])
        limb = N.new("ShaderNodeMapRange"); limb.inputs[3].default_value = 0.55; limb.inputs[4].default_value = 1.0
        L.new(sq.outputs[0], limb.inputs[0])
        hz = N.new("ShaderNodeMapRange"); hz.inputs[1].default_value = -0.0003; hz.inputs[2].default_value = 0.0003
        L.new(sep.outputs[2], hz.inputs[0])
        m1 = N.new("ShaderNodeMath"); m1.operation = "MULTIPLY"; L.new(edge.outputs[0], m1.inputs[0]); L.new(limb.outputs[0], m1.inputs[1])
        m2 = N.new("ShaderNodeMath"); m2.operation = "MULTIPLY"; L.new(m1.outputs[0], m2.inputs[0]); L.new(hz.outputs[0], m2.inputs[1])
        lpd = N.new("ShaderNodeLightPath")
        m3 = N.new("ShaderNodeMath"); m3.operation = "MULTIPLY"; L.new(m2.outputs[0], m3.inputs[0]); L.new(lpd.outputs["Is Camera Ray"], m3.inputs[1])
        kk = N.new("ShaderNodeValue"); kk.name = "sun_disc_k"; kk.outputs[0].default_value = 1.0
        kk["min_k"] = 2.0 * glow_peak / max(1e-6, max(dd))     # (never dimmer than 2x the glow around it)
        m4 = N.new("ShaderNodeMath"); m4.operation = "MULTIPLY"; L.new(m3.outputs[0], m4.inputs[0]); L.new(kk.outputs[0], m4.inputs[1])
        dcol = N.new("ShaderNodeMix"); dcol.data_type = "RGBA"; dcol.blend_type = "MULTIPLY"; dcol.inputs[0].default_value = 1.0
        dcol.inputs[6].default_value = (*dd, 1.0)
        cmb = N.new("ShaderNodeCombineColor")
        for i in range(3):
            L.new(m4.outputs[0], cmb.inputs[i])
        L.new(cmb.outputs[0], dcol.inputs[7])
        # added to the sky (the haze in front of it glows too): always brighter than the glow around it
        addd = N.new("ShaderNodeMix"); addd.data_type = "RGBA"; addd.blend_type = "ADD"; addd.inputs[0].default_value = 1.0
        L.new(col, addd.inputs[6]); L.new(dcol.outputs[2], addd.inputs[7])
        col = addd.outputs[2]
    # under the horizon the sky model is black. The camera never sees it (the ground, or the haze of the compositor),
    # but the other rays do: a ray refracted by glass or reflected by a chrome that slips past the edge of the ground
    # (2 km away: a sliver just under the horizon) or finds no ground at all came back black - black streaks and
    # lines inside a glass cube, black lower half of the reflections. There those rays see a far ground lit by the
    # same sun and sky (behind its haze), or with no ground the colour of the haze, as the camera does.
    far = _far_ground(s, elev)
    lpf = N.new("ShaderNodeLightPath")
    under = N.new("ShaderNodeMapRange"); under.interpolation_type = "SMOOTHSTEP"
    under.inputs[1].default_value = 0.0; under.inputs[2].default_value = -0.002
    L.new(sep.outputs[2], under.inputs[0])
    notcam = N.new("ShaderNodeMath"); notcam.operation = "SUBTRACT"; notcam.inputs[0].default_value = 1.0
    L.new(lpf.outputs["Is Camera Ray"], notcam.inputs[1])
    ff = N.new("ShaderNodeMath"); ff.operation = "MULTIPLY"
    L.new(under.outputs[0], ff.inputs[0]); L.new(notcam.outputs[0], ff.inputs[1])
    fm = N.new("ShaderNodeMix"); fm.data_type = "RGBA"; fm.name = "far_ground"
    L.new(ff.outputs[0], fm.inputs[0]); L.new(col, fm.inputs[6]); fm.inputs[7].default_value = (*far, 1.0)
    col = fm.outputs[2]
    L.new(col, bg.inputs[0])
    L.new(bg.outputs[0], out.inputs[0])
    try:
        w.cycles.sampling_method = "AUTOMATIC"
    except (AttributeError, TypeError):
        pass


def _find_flag(flag):
    for ob in bpy.context.scene.objects:
        if ob.get(flag) and not ob.get("simpler_trashed"):
            return ob
    return None


def _remove(flag):
    from . import scene_ops
    ob = _find_flag(flag)
    if ob is not None:
        data = ob.data
        bpy.data.objects.remove(ob, do_unlink=True)
        if data is not None and data.users == 0 and isinstance(data, bpy.types.Light):
            bpy.data.lights.remove(data)


def _sun_object(create=True, release=False):
    ob = _find_flag(SUN_KEY)
    if ob is None:
        # the sun of the scene (e.g. of an older project) becomes the sun of the Ambiente
        for o in bpy.context.scene.objects:
            if o.type == "LIGHT" and o.data.type == "SUN" and not o.get(MOON_KEY) and not o.get("simpler_trashed") \
                    and not o.get(clouds.CLOUD_SUN_KEY) and not o.get("simpler_fill"):
                ob = o
                break
    if release:
        if ob is not None and SUN_KEY in ob:
            del ob[SUN_KEY]
        return ob
    if ob is None and create:
        from .core import link
        data = bpy.data.lights.new(tr("Sole"), "SUN")
        ob = bpy.data.objects.new(tr("Sole"), data)
        link(ob)
        ensure_id(ob)
    if ob is not None:
        ob[SUN_KEY] = True
    return ob


def _put(owner, attr, value):
    """owner.attr = value only when it differs. Every write, even of the same value, makes Blender evaluate the scene
    again and the path tracing sync it: 0.1-0.8 s on a big model at each change of the Ambiente (1.70.3)."""
    cur = getattr(owner, attr)
    if isinstance(value, (int, float)) and not isinstance(value, bool) and isinstance(cur, (int, float)):
        if abs(cur - value) <= 1e-7 * max(1.0, abs(value)):
            return
    elif hasattr(cur, "__len__") and not isinstance(cur, str) and hasattr(value, "__len__") and len(cur) == len(value):
        try:
            if all(abs(a - b) <= 1e-7 * max(1.0, abs(b)) for a, b in zip(cur, value)):
                return
        except TypeError:
            if all(a == b for a, b in zip(cur, value)):
                return
    elif cur == value:
        return
    setattr(owner, attr, value)


def _aim_sun(ob, v):
    mw = ob.matrix_world.copy()
    loc, _r, scale = mw.decompose()
    q = Vector((0.0, 0.0, 1.0)).rotation_difference(v)      # the light shines along its -Z: +Z looks at the sun
    m = Matrix.LocRotScale(loc, q, scale)
    if any(abs(mw[r][c] - m[r][c]) > 1e-7 for r in range(4) for c in range(4)):
        ob.matrix_world = m


def _sun(s, v, elev):
    ob = _sun_object()
    e = sun_rgb(elev, s["sky"])
    mx = max(e) if max(e) > 0 else 1.0
    d = ob.data
    if hasattr(d, "use_temperature"):
        _put(d, "use_temperature", False)
    _put(d, "color", tuple(x / mx for x in e) if max(e) > 0 else (1.0, 1.0, 1.0))
    _put(d, "energy", max(e) * K * float(s["sun"]["intensity"]) * _cloud_dim(s, lights=True))
    spread = 0.0 if _volumetric(s) else 6.0 * s["clouds"]["cover"] ** 2      # (real clouds: sharp sun, real shade)
    _put(d, "angle", math.radians(max(0.05, float(s["sun"]["size"])) * (1.0 + spread)))
    _aim_sun(ob, v)
    sun = s["sun"]
    info = json.dumps({"hour": sun["hour"], "north": sun["north"], "day": sun["day"], "lat": sun["lat"], "power": d.energy})
    if ob.get("simpler_sun") != info:
        ob["simpler_sun"] = info
    return ob


def _moon(s, v, elev):
    strength = float(s["night"].get("moon", 1.0))
    if elev > -4 or strength <= 0:
        _remove(MOON_KEY)
        return
    ob = _find_flag(MOON_KEY)
    if ob is None:
        from .core import link
        data = bpy.data.lights.new(tr("Luna"), "SUN")
        ob = bpy.data.objects.new(tr("Luna"), data)
        ob[MOON_KEY] = True
        link(ob)
        ensure_id(ob)
    from . import night as nt
    mv = moon_dir(s, v, elev)
    _aim_sun(ob, mv)
    _put(ob.data, "color", (0.72, 0.8, 1.0))
    # (a moon under the horizon lights nothing; a quarter gives about a tenth of the full moon)
    up = max(0.0, min(1.0, (mv.z + 0.02) / 0.06))
    _put(ob.data, "energy", K * 165.0 * 0.0025 * strength * _cloud_dim(s, lights=True) * nt.phase_light(s["night"].get("phase", 0.5)) * up)
    _put(ob.data, "angle", math.radians(0.52))


# ---------------------------------------------------------------- ground

_GROUND = {
    # tile (m), roughness, specular, bump
    "prato": (2.5, 0.95, 0.25, 0.35),
    "terra": (3.0, 0.92, 0.3, 0.45),
    "cemento": (3.0, 0.78, 0.5, 0.15),
    "piastrelle": (1.8, 0.32, 0.5, 0.0),      # the texture of the app (assets): 3 x 3 tiles of 60 cm
}


def _ground_color(kind):
    return {"prato": (0.06, 0.1, 0.03), "terra": (0.13, 0.09, 0.06), "cemento": (0.3, 0.29, 0.27), "neutro": (0.4, 0.4, 0.4), "bianco": (0.75, 0.75, 0.74)}.get(kind, (0.2, 0.2, 0.2))


def _tex_dir():
    base = os.environ.get("LOCALAPPDATA") or os.path.expanduser("~")
    d = os.path.join(base, "Simpler", "ground")
    os.makedirs(d, exist_ok=True)
    return d


def _fbm(n, rng, beta, lo=1.0, hi=None):
    """Periodic (tiling) noise n×n with a 1/f^beta spectrum between frequencies lo and hi, normalised to 0..1."""
    import numpy as np
    fx = np.fft.fftfreq(n) * n
    fy = np.fft.rfftfreq(n) * n
    f = np.sqrt(fx[:, None] ** 2 + fy[None, :] ** 2)
    amp = np.where(f >= lo, 1.0 / np.maximum(f, 1e-6) ** beta, 0.0)
    if hi is not None:
        amp = amp * np.exp(-(f / hi) ** 2)
    ph = rng.standard_normal(f.shape) + 1j * rng.standard_normal(f.shape)
    img = np.fft.irfft2(amp * ph, s=(n, n))
    img -= img.min()
    return img / max(1e-9, img.max())


def _ground_texture(kind):
    """A tiling colour texture for the ground (made once, kept in %LOCALAPPDATA%\\Simpler\\ground)."""
    if kind == "piastrelle":
        # a photo texture that comes with the app: copied next to the others (the projects keep finding it there)
        dst = os.path.join(_tex_dir(), "piastrelle_v1.jpg")
        if not os.path.isfile(dst):
            import shutil
            src = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "assets", "ground_tiles.jpg")
            shutil.copy2(src, dst)
        return dst
    path = os.path.join(_tex_dir(), f"{kind}_v{TEX_VERSION}.png")
    if os.path.isfile(path):
        return path
    import numpy as np
    n = 1024
    rng = np.random.default_rng({"prato": 11, "terra": 23, "cemento": 37}[kind])
    big = _fbm(n, rng, 1.6, 1, 12)
    mid = _fbm(n, rng, 1.2, 8, 90)
    fine = _fbm(n, rng, 0.6, 120, None)
    if kind == "prato":
        dark, green, dry = np.array([0.035, 0.07, 0.018]), np.array([0.075, 0.14, 0.035]), np.array([0.15, 0.14, 0.055])
        a = np.clip((big - 0.45) * 1.2, 0, 0.5)[..., None]       # (large patches come from the material)
        base = green * (1 - a) + dry * a * 0.8 + green * a * 0.2
        blades = (0.55 + 0.9 * fine)[..., None]
        shade = (0.75 + 0.5 * mid)[..., None]
        col = base * blades * shade
        col = col * (1 - 0.5 * (fine < 0.18)[..., None]) + dark * 0.0
    elif kind == "terra":
        lo, hi = np.array([0.09, 0.062, 0.04]), np.array([0.2, 0.145, 0.095])
        a = (0.6 * big + 0.4 * mid)[..., None]
        col = lo * (1 - a) + hi * a
        pebbles = (fine > 0.8)[..., None]
        col = col * (0.8 + 0.4 * fine[..., None]) * (1 + 0.6 * pebbles)
    else:
        base = np.array([0.3, 0.29, 0.27])
        col = base * (0.85 + 0.25 * big[..., None]) * (0.92 + 0.16 * fine[..., None]) * (0.95 + 0.1 * mid[..., None])
    col = np.clip(col, 0, 1)
    srgb = np.where(col <= 0.0031308, col * 12.92, 1.055 * np.power(col, 1 / 2.4) - 0.055)
    rgba = np.concatenate([srgb, np.ones((n, n, 1))], axis=2).astype(np.float32)
    im = bpy.data.images.new("simpler_ground_tmp", n, n, alpha=False)
    try:
        im.pixels.foreach_set(rgba.ravel())
        im.filepath_raw = path
        im.file_format = "PNG"
        im.save()
    finally:
        bpy.data.images.remove(im)
    return path


GROUND_MAT_VERSION = 3


def _ground_material(kind):
    """The ground's material as a Simpler material (the editor reads and changes all of it: colour, roughness,
    mapping, «Rompi la ripetizione»...). The textured grounds break their repetition with the editor's own
    Randomize UV; the tiles do not (the grout lines must match)."""
    name = f"Simpler Suolo {kind} v{GROUND_MAT_VERSION}"
    mat = bpy.data.materials.get(name)
    if mat is not None:
        return mat
    import copy
    from . import matedit
    mat = bpy.data.materials.new(name)
    mat.use_nodes = True
    p = copy.deepcopy(matedit.DEFAULTS)
    if kind in ("neutro", "bianco"):
        p["color"]["tint"] = list(_ground_color(kind))
        p["roughness"]["value"] = 0.8 if kind == "neutro" else 0.9
        p["specular"] = 0.5 if kind == "neutro" else 0.3
    else:
        tile, rough, spec, _bump = _GROUND[kind]
        im = bpy.data.images.load(_ground_texture(kind), check_existing=True)
        p["color"]["tint"] = [1.0, 1.0, 1.0]
        p["color"]["map"]["image"] = im.name
        p["roughness"]["value"] = rough
        p["specular"] = spec
        # the mesh UVs already repeat the texture every "tile" metres (_ground): one repeat per UV unit
        p["uv"].update(mode="uv", scale=1.0)
        if kind != "piastrelle":
            p["uv"].update(antitile=True, cellRepeats=3.0, antitileBlend=0.3, antitileRotate=True)
        mat["simpler_ground_tile"] = tile
    matedit.apply(mat, p, keep_original=False)
    return mat


def _ground_follows_user(s):
    """The ground is the user's once made: deleted in the scene, it stays deleted (a change of sun, sky or preset
    does not bring it back; only choosing a ground in the panel does); put back with undo, it is kept."""
    active = _find_flag(GROUND_KEY)
    if s["ground"]["type"] not in (None, "nessuno"):
        if active is None:
            s["ground"]["type"] = "nessuno"
    elif active is not None:
        s["ground"]["type"] = active.get("simpler_ground_kind", "prato")


GROUND_SIDES = 96


def _ground_disc(me):
    """The ground as a round plate (one face of 96 sides, ~94 triangles): the horizon is as far in every direction.
    The square one ended 2 km away straight ahead and 2.8 km away towards its corners - with little haze its edge
    showed as a slanted line at a different distance."""
    h = GROUND_SIZE / 2.0
    me.clear_geometry()
    verts = [(h * math.cos(2 * math.pi * i / GROUND_SIDES), h * math.sin(2 * math.pi * i / GROUND_SIDES), 0.0)
             for i in range(GROUND_SIDES)]
    me.from_pydata(verts, [], [tuple(range(GROUND_SIDES))])
    if not me.uv_layers:
        me.uv_layers.new(name="UVMap")
    me.update()


GROUND_Z = -0.004                      # the ground of Simpler: just under z = 0
GROUND_GAP = 0.004                     # ... and this much under a floor of the scene that lies lower
GROUND_AUTO = "simpler_ground_z"       # the height Simpler gave it (another one: the user moved it, it stays)


def _ground_height(ob):
    """Where the ground goes: GROUND_Z, or GROUND_GAP under the lowest floor of the scene found within 10 cm under
    z = 0. (Luca, 18/11, the cathedral: its floor ends at -6.5 mm, the ground at -4 mm lay 2.5 mm ABOVE it - in the
    real-time view the floor appeared and disappeared as the camera moved, in the path tracing the ground covered it.)
    Rays straight down from just above z = 0 over the extent of the scene: only what lies between +3 mm and -10 cm
    is met (not the furniture standing on the floor)."""
    from .core import INTERNAL_KEY
    try:
        lo = [1e18, 1e18]; hi = [-1e18, -1e18]
        for o in bpy.context.scene.objects:
            if o.type != "MESH" or o is ob or o.get(INTERNAL_KEY) or o.get("simpler_trashed") or o.hide_render:
                continue
            for c in o.bound_box:
                p = o.matrix_world @ Vector(c)
                lo = [min(lo[0], p.x), min(lo[1], p.y)]; hi = [max(hi[0], p.x), max(hi[1], p.y)]
        if lo[0] > hi[0]:
            return GROUND_Z
        lo = [max(v, -150.0) for v in lo]; hi = [min(v, 150.0) for v in hi]
        dg = bpy.context.evaluated_depsgraph_get()
        scene = bpy.context.scene
        lowest = None
        n = 24
        for i in range(n):
            for j in range(n):
                x = lo[0] + (hi[0] - lo[0]) * (i + 0.5) / n
                y = lo[1] + (hi[1] - lo[1]) * (j + 0.5) / n
                z, left = 0.003, 0.103
                for _ in range(4):                 # (past the ground itself, a twin, a decal)
                    ok, loc, nrm, _i, hob, _m = scene.ray_cast(dg, Vector((x, y, z)), Vector((0.0, 0.0, -1.0)), distance=left)
                    if not ok or hob is None:
                        break
                    src = hob.original if hob.original is not None else hob
                    if src is ob or (src.get(INTERNAL_KEY) and not src.get("simpler_twin")) or src.get("simpler_decal") \
                            or src.get(KIND_KEY_DECAL) == "decal":
                        step = (z - loc.z) + 0.0005
                        z -= step; left -= step
                        if left <= 0:
                            break
                        continue
                    if nrm.z > 0.7 and (lowest is None or loc.z < lowest):
                        lowest = loc.z
                    break
        if lowest is None:
            return GROUND_Z
        return min(GROUND_Z, round(lowest - GROUND_GAP, 4))
    except Exception as exc:  # noqa: BLE001
        log("SIMPLER_GROUND", f"height not measured: {exc}")
        return GROUND_Z


KIND_KEY_DECAL = "simpler_kind"


def _ground(kind, force=False):
    """The ground object. Its material is Simpler's only until the user gives it another one: a change of sky, sun or
    preset keeps the user's material; choosing a ground in the panel (force) puts Simpler's back."""
    ob = _find_flag(GROUND_KEY)
    if kind in (None, "nessuno"):
        if ob is not None:
            me = ob.data
            bpy.data.objects.remove(ob, do_unlink=True)
            if me is not None and me.users == 0:
                bpy.data.meshes.remove(me)
        return
    tile = _GROUND.get(kind, (4.0,))[0]
    created = ob is None
    if ob is None:
        from .core import link
        me = bpy.data.meshes.new(tr("Suolo"))
        _ground_disc(me)
        ob = bpy.data.objects.new(tr("Suolo"), me)
        ob[GROUND_KEY] = True
        ob.location.z = GROUND_Z          # just under a floor already in the scene (no flicker)
        ob[GROUND_AUTO] = GROUND_Z
        link(ob)
        ensure_id(ob)
    # the height stays Simpler's while the user has not moved it: under the lowest floor of the scene (_ground_height)
    auto = ob.get(GROUND_AUTO)
    if abs(ob.location.z - (GROUND_Z if auto is None else float(auto))) < 1e-5:
        z = _ground_height(ob)
        if abs(z - ob.location.z) > 1e-5:
            log("SIMPLER_GROUND", f"ground from {ob.location.z * 1000:.1f} mm to {z * 1000:.1f} mm: a floor of the scene lies lower")
            ob.location.z = z
        ob[GROUND_AUTO] = z
    me = ob.data
    rebuilt = False
    if len(me.vertices) == 4 and len(me.polygons) == 1:
        _ground_disc(me)                  # (the square ground of projects before 1.37.6)
        rebuilt = True
    if created or rebuilt or me.get("simpler_tile") != tile:
        # (only when the tile changes: written at every change of the Ambiente, the ground was a new geometry for
        # Blender and the path tracing each time - 1.70.3)
        import numpy as np
        h = GROUND_SIZE / 2.0
        co = np.empty(len(me.vertices) * 3, np.float32)
        me.vertices.foreach_get("co", co)
        vi = np.empty(len(me.loops), np.int32)
        me.loops.foreach_get("vertex_index", vi)
        co = co.reshape(-1, 3)[vi]
        uv = np.stack([(co[:, 0] + h) / tile, (co[:, 1] + h) / tile], axis=1).astype(np.float32)
        me.uv_layers[0].data.foreach_set("uv", uv.ravel())
        me["simpler_tile"] = tile
        me.update()
    mat = _ground_material(kind)
    cur = ob.material_slots[0].material if ob.material_slots else None
    ours = cur is None or cur.name.startswith("Simpler Suolo")
    if (created or force or ours or ob.get("simpler_ground_kind") != kind) and cur is not mat:
        me.materials.clear()
        me.materials.append(mat)
        ob["simpler_ground_kind"] = kind


# ---------------------------------------------------------------- haze / fog (compositor, Mist pass)

FOG_TREE = "Simpler Foschia v17"
MIST_DEPTH = 50000.0


# the haze is a layer of air near the ground, thinning out upwards (scale height, metres): the sky and the clouds
# get the haze of the path through it, H / sin(elevation). It was 1200 m: with the aerosols that the sky model
# already has, sunsets turned into a white veil.
HAZE_H = 150.0


def fog_visibility(density):
    """Metres at which ~63% of the view is haze: 40 km (clear) ... 30 m (thick fog)."""
    return 40000.0 * (30.0 / 40000.0) ** density


def _fog(s):
    scene = bpy.context.scene
    vl = scene.view_layers[0]
    dens = s["fog"]["density"] if s else 0.0
    tree = bpy.data.node_groups.get(FOG_TREE)
    volumetric = bool(s and s["fog"].get("volumetric")) and dens >= 0.005
    _fog_domain(s if volumetric else None)
    if dens < 0.005 or volumetric:            # (volumetric: the haze is in the scene, the compositor does nothing)
        if getattr(scene, "compositing_node_group", None) is tree and tree is not None:
            scene.compositing_node_group = None
        _put(scene.render, "film_transparent", False)
        _put(vl, "use_pass_mist", False)
        _put(vl, "use_pass_environment", False)
        return
    V = fog_visibility(dens)
    _put(scene.render, "film_transparent", True)  # the sky comes back from the Environment pass, unfogged
    _put(vl, "use_pass_mist", True)
    _put(vl, "use_pass_z", True)                  # (the nearest surface: see _fog_tree)
    _put(vl, "use_pass_environment", True)
    _put(vl.cycles, "denoising_store_passes", True)     # (v15: the guides of the denoising of the haze, see _fog_tree)
    if vl.cycles.use_pass_volume_direct or vl.cycles.use_pass_volume_indirect:    # (passes of 1.14.0, unused)
        vl.cycles.use_pass_volume_direct = vl.cycles.use_pass_volume_indirect = False
    ms = scene.world.mist_settings
    # the Mist pass covers 6 visibility distances (beyond, the haze is complete): its precision then is a fixed
    # share of the visibility - over 50 km a thick fog turned the sampling noise of leaves into fog
    depth = max(50.0, min(MIST_DEPTH, 6.0 * V))
    _put(ms, "start", 0.0)
    _put(ms, "depth", depth)
    _put(ms, "falloff", "LINEAR")
    if tree is None:
        for old in [g for g in bpy.data.node_groups if g.name.startswith("Simpler Foschia") and g.name != FOG_TREE]:
            bpy.data.node_groups.remove(old)           # trees of older versions
        tree = _fog_tree()
    if scene.compositing_node_group is not tree:
        scene.compositing_node_group = tree
    _put(scene.render, "use_compositing", True)
    # (v12) the haze from the optical depth along each ray (_fog_tau): low fog (height, falloff), start distance
    _put(tree.nodes["fog_k"].inputs[1], "default_value", -1.0 / V)
    _put(tree.nodes["fog_k2"].inputs[1], "default_value", -1.0 / V)
    _put(tree.nodes["fog_k3"].inputs[1], "default_value", -1.0 / V)
    _put(tree.nodes["fog_k4"].inputs[1], "default_value", -1.0 / V)
    _put(tree.nodes["fog_k5"].inputs[1], "default_value", -1.0 / V)
    _put(tree.nodes["fog_k6"].inputs[1], "default_value", -1.0 / V)
    prof = fog_profile(s)
    h, H = prof if prof else (1e7, 1.0)
    V2 = fog_visibility2(s)
    _set_labels(tree, {"depth": depth, "s0": float(s["fog"].get("start", 0.0)), "h": h, "H": H, "nH": -H, "iH": -1.0 / H,
                       "r2": V / V2 if V2 else 0.0})
    fog_camera(scene)
    _put(tree.nodes["z_to_mist"].inputs[1], "default_value", 1.0 / depth)
    for n in tree.nodes:                                                 # (v17: the sky, in the Mist pass's units)
        if n.label == "sky_cut":
            _put(n.inputs[1], "default_value", 1e9 / depth)
    # (volumetric clouds: the far end is sky and clouds only if the ground is well inside the Mist pass)
    _put(tree.nodes["keep_far"].inputs[1], "default_value", 1.0 if clouds.active(s) and depth > 1.5 * GROUND_SIZE else 0.0)
    col = _fog_color(s)
    _put(tree.nodes["fog_color"].outputs[0], "default_value", (*col, 1.0))


# ---------------------------------------------------------------- volumetric fog (switch: real shafts of light)
# The haze of the compositor is cheap and right for the distance, but it does not know where the light is: no shafts
# of light between trees or through a window, no glow around a lamp in the fog. "Nebbia volumetrica" puts the fog in
# the scene instead: a box around the scene and the camera filled with a Principled Volume (density = 1/visibility,
# light scattered a little forwards), path traced by Cycles from the sun, the sky and the lamps. The sky beyond the
# box keeps the haze painted in the sky (world shader). Cost: much more than the compositor (every ray crosses the
# volume, more noise): a switch, off by default.
FOG_DOMAIN_KEY = "simpler_fog_domain"
FOG_DOMAIN_MAT = "Simpler Nebbia volumetrica"
_DOMAIN = {"box": None}


def _scene_box():
    from .core import managed_objects
    from . import twins
    lo, hi = Vector((1e9, 1e9, 1e9)), Vector((-1e9, -1e9, -1e9))
    n = 0
    for ob in managed_objects():
        if ob.type != "MESH" or ob.get(GROUND_KEY) or twins.is_twin(ob) or ob.get("simpler_trashed"):
            continue
        mw = ob.matrix_world
        for c in ob.bound_box:
            p = mw @ Vector(c)
            lo = Vector(map(min, lo, p)); hi = Vector(map(max, hi, p))
        n += 1
        if n > 20000:
            break
    if n == 0:
        return Vector((-10, -10, 0)), Vector((10, 10, 10))
    return lo, hi


def _fog_domain(s):
    ob = _find_flag(FOG_DOMAIN_KEY)
    if s is None:
        if ob is not None:
            me = ob.data
            bpy.data.objects.remove(ob, do_unlink=True)
            if me is not None and me.users == 0:
                bpy.data.meshes.remove(me)
        _DOMAIN["box"] = None
        return
    V = fog_visibility(s["fog"]["density"])
    if ob is None:
        from .core import INTERNAL_KEY
        me = bpy.data.meshes.new(FOG_DOMAIN_MAT)
        v = [(x, y, z) for x in (-1, 1) for y in (-1, 1) for z in (-1, 1)]
        f = [(0, 1, 3, 2), (4, 6, 7, 5), (0, 4, 5, 1), (2, 3, 7, 6), (0, 2, 6, 4), (1, 5, 7, 3)]
        me.from_pydata(v, [], f)
        me.update()
        ob = bpy.data.objects.new(FOG_DOMAIN_MAT, me)
        ob[FOG_DOMAIN_KEY] = True
        ob[INTERNAL_KEY] = 1
        bpy.context.scene.collection.objects.link(ob)
        ob.hide_select = True
    ob.hide_viewport = True                     # not clicked, not in the real-time view: only Cycles sees it
    ob.hide_render = False
    ob.cycles.is_caustics_caster = ob.cycles.is_caustics_receiver = False
    mat = bpy.data.materials.get(FOG_DOMAIN_MAT)
    if mat is None:
        mat = bpy.data.materials.new(FOG_DOMAIN_MAT)
        mat.use_nodes = True
    nt = mat.node_tree
    if nt.nodes.get("fog_scatter") is None or nt.nodes.get("fog_v2") is None:   # (1.75.50: Mie, noise; older: again)
        _fog_domain_nodes(nt)
    prof = fog_profile(s)
    h, H = prof if prof else (1e7, 1.0)
    f = s["fog"]
    noise = float(f.get("noise", 0.0))
    N = nt.nodes
    N["fog_h"].inputs[1].default_value = h
    N["fog_iH"].inputs[1].default_value = -1.0 / H
    N["fog_sigma"].inputs[1].default_value = 1.0 / V
    N["fog_sigma2"].inputs[1].default_value = 1.0 / fog_visibility2(s) if fog_visibility2(s) else 0.0
    N["fog_scale"].inputs["Scale"].default_value = 1.0 / max(1.0, float(f.get("noiseScale", 25.0)))
    N["fog_irr"].inputs[0].default_value = noise                    # how much the noise changes the density
    N["fog_wave"].inputs[1].default_value = noise * 1.6 * (H if prof else 0.0)   # the top of a low fog undulates
    alb = fog_tint_albedo(s)
    N["fog_scatter"].inputs["Color"].default_value = (*alb, 1.0)
    N["fog_absorb"].inputs["Color"].default_value = (*alb, 1.0)    # (absorbs 1 - albedo: extinction = density)
    # the glow towards the lights: small = light scattered evenly (dust, the shafts seen from the side), large =
    # water droplets (Mie phase of droplets 5-30 µm: the bright halo towards the sun and around the lamps)
    glow = max(0.0, min(1.0, float(f.get("glow", 0.6))))
    sc = N["fog_scatter"]
    if glow < 0.5:
        sc.phase = "HENYEY_GREENSTEIN"
        sc.inputs["Anisotropy"].default_value = glow * 1.4
    else:
        sc.phase = "MIE"
        sc.inputs["Diameter"].default_value = 5.0 + (glow - 0.5) * 2.0 * 25.0
    if not ob.data.materials:
        ob.data.materials.append(mat)
    lo, hi = _scene_box()
    reach = min(3.0 * V, 1500.0)                # beyond ~3 visibilities the fog is complete anyway
    c = (lo + hi) / 2
    half = Vector((max((hi.x - lo.x) / 2 + 10.0, reach), max((hi.y - lo.y) / 2 + 10.0, reach), 0.0))
    # a layer of fog on the ground, a little higher than the scene: the sun comes in from above through a few
    # metres of it (a layer hundreds of metres thick swallows the sun - right for a real fog bank, but then there are
    # no shafts, only grey: the haze of the compositor does that for far less)
    zlo = lo.z - 2.0
    zhi = hi.z + max(8.0, 0.1 * (hi.z - lo.z))
    if prof:                                    # (a low fog: the box up to where it has faded away)
        zhi = max(zhi, min(h + 5.0 * H, zlo + 3.0 * reach))
    _DOMAIN["box"] = [c.x - half.x, c.y - half.y, zlo, c.x + half.x, c.y + half.y, zhi]
    _place_domain(ob)


def _fog_domain_nodes(nt):
    """(1.75.50) The material of the volumetric fog: density = (dense fog by height × noise) + the haze above;
    Volume Scatter (Mie droplets or Henyey-Greenstein) + Volume Absorption of the same density, so that the colour is
    the albedo of the droplets and nothing else."""
    for n in list(nt.nodes):
        if n.type != "OUTPUT_MATERIAL":
            nt.nodes.remove(n)
    out = next(n for n in nt.nodes if n.type == "OUTPUT_MATERIAL")
    N, L = nt.nodes, nt.links

    def m(op, a=None, b=None, name=None):
        n = N.new("ShaderNodeMath"); n.operation = op
        for i, x in enumerate((a, b)):
            if x is None:
                continue
            if isinstance(x, (int, float)):
                n.inputs[i].default_value = float(x)
            else:
                L.new(x, n.inputs[i])
        if name:
            n.name = name
        return n
    geo = N.new("ShaderNodeNewGeometry")
    # 3D noise in metres of the world: fBm, a few octaves - banks and wisps, not a pattern
    N.new("NodeReroute").name = "fog_v2"           # (marks this version of the material)
    sca = N.new("ShaderNodeVectorMath"); sca.operation = "SCALE"; sca.name = "fog_scale"
    L.new(geo.outputs["Position"], sca.inputs[0])
    nz = N.new("ShaderNodeTexNoise"); nz.noise_dimensions = "3D"
    try:
        nz.noise_type = "FBM"
    except (AttributeError, TypeError):
        pass
    nz.inputs["Scale"].default_value = 1.0        # (the size comes from fog_scale: 1 / metres)
    nz.inputs["Detail"].default_value = 5.0
    nz.inputs["Roughness"].default_value = 0.55
    nz.inputs["Distortion"].default_value = 0.35
    L.new(sca.outputs["Vector"], nz.inputs["Vector"])
    # the height, moved up and down by the noise: the top of a fog bank is not flat
    sep = N.new("ShaderNodeSeparateXYZ")
    L.new(geo.outputs["Position"], sep.inputs[0])
    wv = m("SUBTRACT", nz.outputs["Fac"], 0.5)
    wv = m("MULTIPLY", wv.outputs[0], 0.0, "fog_wave")
    z = m("ADD", sep.outputs[2], wv.outputs[0])
    sub = m("SUBTRACT", z.outputs[0], 0.0, "fog_h")
    mx = m("MAXIMUM", sub.outputs[0], 0.0)
    mu = m("MULTIPLY", mx.outputs[0], 0.0, "fog_iH")
    ex = m("EXPONENT", mu.outputs[0])
    # patches: the noise from 0.36-0.64 to 0-2 (the same density on average), mixed in by «Irregolarità»
    rng = N.new("ShaderNodeMapRange"); rng.clamp = True
    rng.inputs["From Min"].default_value = 0.36; rng.inputs["From Max"].default_value = 0.64   # (clear gaps, thick banks)
    rng.inputs["To Min"].default_value = 0.0; rng.inputs["To Max"].default_value = 2.0
    L.new(nz.outputs["Fac"], rng.inputs["Value"])
    irr = N.new("ShaderNodeMix"); irr.data_type = "FLOAT"; irr.name = "fog_irr"; irr.clamp_factor = True
    irr.inputs[2].default_value = 1.0
    L.new(rng.outputs["Result"], irr.inputs[3])
    pat = m("MULTIPLY", ex.outputs[0], irr.outputs[0])
    d1 = m("MULTIPLY", pat.outputs[0], 0.0, "fog_sigma")
    d2 = m("MULTIPLY", irr.outputs[0], 0.0, "fog_sigma2")         # (the haze above: everywhere, with the same patches)
    dn = m("ADD", d1.outputs[0], d2.outputs[0])
    scat = N.new("ShaderNodeVolumeScatter"); scat.name = "fog_scatter"
    absn = N.new("ShaderNodeVolumeAbsorption"); absn.name = "fog_absorb"
    L.new(dn.outputs[0], scat.inputs["Density"]); L.new(dn.outputs[0], absn.inputs["Density"])
    add = N.new("ShaderNodeAddShader")
    L.new(scat.outputs[0], add.inputs[0]); L.new(absn.outputs[0], add.inputs[1])
    L.new(add.outputs[0], out.inputs["Volume"])


def fog_visibility2(s):
    """(1.75.50) Visibility of the haze above a low fog (the second layer), 0 when there is none."""
    f = s.get("fog", {}) if s else {}
    d2 = float(f.get("haze2", 0.0))
    return fog_visibility(d2) if f.get("low") and d2 >= 0.005 else 0.0


def _place_domain(ob):
    x0, y0, z0, x1, y1, z1 = _DOMAIN["box"]
    loc = Vector(((x0 + x1) / 2, (y0 + y1) / 2, (z0 + z1) / 2))
    sc = Vector(((x1 - x0) / 2, (y1 - y0) / 2, (z1 - z0) / 2))
    if (ob.location - loc).length > 1e-3 or (ob.scale - sc).length > 1e-3:
        ob.location = loc
        ob.scale = sc


_UW = {"epoch": None, "boxes": [], "off": False}


def _camera_underwater(pos):
    """Is the camera under the surface of a water (inside its outline, below its level)? Water outlines are read
    again only when the scene changes."""
    from . import render, water
    if _UW["epoch"] != render.STATE.epoch:
        boxes = []
        for ob in bpy.context.scene.objects:
            if ob.type == "MESH" and not ob.get(water.BODY_KEY) and not ob.get("simpler_trashed") \
                    and water.water_material(ob) is not None:
                pts = [ob.matrix_world @ Vector(c) for c in ob.bound_box]
                boxes.append((min(p.x for p in pts), min(p.y for p in pts), max(p.x for p in pts), max(p.y for p in pts),
                              max(p.z for p in pts)))
        _UW.update(epoch=render.STATE.epoch, boxes=boxes)
    return any(x0 <= pos.x <= x1 and y0 <= pos.y <= y1 and z - 60.0 < pos.z < z for x0, y0, x1, y1, z in _UW["boxes"])


def _underwater_haze(pos):
    """The haze of the air (compositor, from the distance) is not for a camera under water: there the water itself
    (its volume: colour, clarity) makes the distance fade. Seen from under the surface the air haze painted a grey
    veil over a clear pool, whatever its clarity. Off while the camera is under water, back when it comes out."""
    s = state()
    under = _camera_underwater(pos)
    if under:
        scene = bpy.context.scene
        if s is not None and s["fog"]["density"] >= 0.005 and not s["fog"].get("volumetric") \
                and (getattr(scene, "compositing_node_group", None) is not None or scene.render.film_transparent):
            if getattr(scene, "compositing_node_group", None) is not None:
                scene.compositing_node_group = None
            scene.render.film_transparent = False
            vl = scene.view_layers[0]
            vl.use_pass_mist = False
            vl.use_pass_environment = False
            _UW["off"] = True
    elif not under and _UW["off"]:
        _UW["off"] = False
        _fog(s)


def fog_follow_camera(pos):
    """Before every path-traced image: the box of the volumetric fog always holds the camera (Cycles must know the
    camera is inside the fog); it only grows. Under water: no air haze (see _underwater_haze)."""
    try:
        _underwater_haze(pos)
    except Exception as exc:
        print("SIMPLER_FOG underwater check:", exc, flush=True)
    box = _DOMAIN["box"]
    ob = _find_flag(FOG_DOMAIN_KEY)
    if ob is None:
        return
    if box is None:
        s = state()
        if s is None or not s["fog"].get("volumetric"):
            return
        _fog_domain(s)
        box = _DOMAIN["box"]
    m = 5.0
    nb = [min(box[0], pos.x - m), min(box[1], pos.y - m), min(box[2], pos.z - m),
          max(box[3], pos.x + m), max(box[4], pos.y + m), max(box[5], pos.z + m)]
    if nb != box:
        _DOMAIN["box"] = nb
        _place_domain(ob)


def upgrade_world():
    """Projects saved before 1.27: their sky had no far ground under the horizon (see _world_nodes)."""
    w = bpy.context.scene.world
    s = state()
    if s is None or s["mode"] != "sky" or w is None or w.get("simpler_env") != "ambience" or not w.use_nodes:
        return
    if w.node_tree.nodes.get("far_ground") is not None:
        return
    v = _sun_dir(s)
    elev = math.degrees(math.asin(max(-1.0, min(1.0, v.z))))
    k = w.node_tree.nodes.get("sun_disc_k")
    k = k.outputs[0].default_value if k is not None else None
    _world_nodes(w, s, v, elev)
    dk = w.node_tree.nodes.get("sun_disc_k")
    if dk is not None and k is not None:
        dk.outputs[0].default_value = k


def _far_ground(s, elev):
    """Radiance of the ground far away (scene units, RGB), for the rays that look under the horizon past the edge of
    the ground: albedo / pi x (sun on a horizontal surface + sky), behind the haze of ~2 km. No ground: the haze."""
    kind = s["ground"]["type"]
    fog = _fog_color(s)
    if kind in (None, "nessuno"):
        return fog
    albedo = (0.55, 0.54, 0.52) if kind == "piastrelle" else _ground_color(kind)
    e_sun = sun_rgb(elev, s["sky"])
    sin_e = max(0.0, math.sin(math.radians(elev)))
    sky = sky_irradiance(elev, s["sky"]) * float(s["sky"].get("ambient", 1.0)) * (0.6 + 0.4 * _cloud_dim(s))
    from . import night as nt
    moon = 165.0 * 0.0025 * float(s["night"].get("moon", 1.0)) * 0.6 * nt.phase_light(s["night"].get("phase", 0.5)) if elev < -4 else 0.0
    out = [albedo[c] / math.pi * K * (e_sun[c] * sin_e * float(s["sun"]["intensity"]) * _cloud_dim(s) + sky + moon)
           for c in range(3)]
    dens = s["fog"]["density"]
    if dens >= 0.005:
        f = 1.0 - math.exp(-2000.0 / fog_visibility(dens))
        out = [out[c] * (1 - f) + fog[c] * f for c in range(3)]
    return tuple(out)


def _fog_color(s):
    """Colour of the haze: the light of sun and sky scattered towards the eye (bluish-white by day, warm at sunset);
    (1.75.49) with «tint» the colour chosen, at the same brightness."""
    auto = _fog_color_auto(s)
    f = s.get("fog", {}) if s else {}
    if not f.get("tint"):
        return auto
    lin = [(c / 12.92) if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4 for c in f.get("color", [0.8, 0.84, 0.9])]
    lum = lambda c: 0.2126 * c[0] + 0.7152 * c[1] + 0.0722 * c[2]
    la, lt = lum(auto), max(1e-6, lum(lin))
    return tuple(c * la / lt for c in lin)


def fog_tint_albedo(s):
    """The chosen colour as the colour of the droplets of the volumetric fog (brightest channel 0.96)."""
    f = s.get("fog", {}) if s else {}
    if not f.get("tint"):
        return (0.96, 0.96, 0.96)
    lin = [(c / 12.92) if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4 for c in f.get("color", [0.8, 0.84, 0.9])]
    m = max(1e-6, max(lin))
    return tuple(0.96 * c / m for c in lin)


def fog_profile(s):
    """(1.75.49) (height, falloff) of a low fog, or None for a fog everywhere (the same at every height)."""
    f = s.get("fog", {}) if s else {}
    if not f.get("low"):
        return None
    return float(f.get("height", 10.0)), max(0.5, float(f.get("falloff", 20.0)))


def fog_column(s, zc):
    """Metres of dense fog straight above a point at height zc: the haze of the sky seen from the camera."""
    p = fog_profile(s)
    if p is None:
        return HAZE_H
    h, H = p
    F = (min(zc, h) + H * (1.0 - math.exp(-max(zc - h, 0.0) / H)))
    V2 = fog_visibility2(s)                   # (the haze above: the usual layer of air, at its own density)
    extra = HAZE_H * fog_visibility(s["fog"]["density"]) / V2 if V2 else 0.0
    return max(0.05, (h + H) - F) + extra


def _fog_color_auto(s):
    v = _sun_dir(s)
    elev = math.degrees(math.asin(max(-1.0, min(1.0, v.z))))
    e_sun = sun_rgb(elev, s["sky"])
    e_sky = sky_irradiance(elev, s["sky"])
    sky_tint = (0.85, 0.92, 1.05)
    out = [(e_sky * 1.6 * sky_tint[c] + e_sun[c] * 0.12) * K / math.pi * float(s["sky"].get("ambient", 1.0)) for c in range(3)]
    if elev < -6:
        out = [K * 0.0006, K * 0.0007, K * 0.001]
    dim = 0.55 + 0.45 * _cloud_dim(s)
    return tuple(x * dim for x in out)


def _set_labels(tree, values):
    """Constants of the fog tree: a node labelled «fog:key:i» gets values[key] on its input i."""
    for n in tree.nodes:
        lab = n.label or ""
        if lab.count(":") == 2 and lab.split(":")[0] in ("fog", "cam"):
            _, key, i = lab.split(":")
            if key in values:
                _put(n.inputs[int(i)], "default_value", float(values[key]))


def _math(N, L, op, a=None, b=None, c=None, label=None, clamp=False):
    """A math node of the compositor; a/b/c: a socket or a number; label «fog:key:i» marks a constant set later."""
    n = N.new("ShaderNodeMath"); n.operation = op; n.use_clamp = clamp
    for i, x in enumerate((a, b, c)):
        if x is None:
            continue
        if isinstance(x, (int, float)):
            n.inputs[i].default_value = float(x)
        else:
            L.new(x, n.inputs[i])
    if label:
        n.label = label
    return n.outputs[0]


def _fog_view_dz(N, L, image):
    """(v12) The vertical component of each pixel's ray, from the pixel position and the camera (fog_camera sets the
    frame of the camera and its rotation: «cam:» constants)."""
    ic = N.new("CompositorNodeImageCoordinates")
    L.new(image, ic.inputs[0])
    sep = N.new("ShaderNodeSeparateXYZ")
    L.new(ic.outputs["Normalized"], sep.inputs[0])
    xl = _math(N, L, "MULTIPLY_ADD", sep.outputs[0], 1.0, 0.0); xl.node.inputs[1].default_value = 1.0
    xl.node.label = "cam:ax:1"
    xl = _math(N, L, "ADD", xl, 0.0, label="cam:bx:1")
    yl = _math(N, L, "MULTIPLY", sep.outputs[1], 1.0, label="cam:ay:1")
    yl = _math(N, L, "ADD", yl, 0.0, label="cam:by:1")
    n1 = _math(N, L, "MULTIPLY", xl, 0.0, label="cam:r20:1")
    n1 = _math(N, L, "ADD", n1, -1.0, label="cam:c:1")
    num = _math(N, L, "MULTIPLY", yl, 0.0, label="cam:r21:1")
    num = _math(N, L, "ADD", num, n1)
    x2 = _math(N, L, "MULTIPLY", xl, xl)
    y2 = _math(N, L, "MULTIPLY", yl, yl)
    l2 = _math(N, L, "ADD", x2, y2)
    l2 = _math(N, L, "ADD", l2, 1.0, label="cam:z2:1")
    ln = _math(N, L, "SQRT", l2)
    return _math(N, L, "DIVIDE", num, ln)


def _fog_F(N, L, z):
    """Metres of dense fog from the ground up to height z (antiderivative of the density profile), and the density
    there: dense below h, exp(-(z-h)/H) above. Fog everywhere: h huge (F = z, density 1)."""
    a = _math(N, L, "MINIMUM", z, 0.0, label="fog:h:1")
    e = _math(N, L, "SUBTRACT", z, 0.0, label="fog:h:1")
    e = _math(N, L, "MAXIMUM", e, 0.0)
    g = _math(N, L, "EXPONENT", _math(N, L, "MULTIPLY", e, 0.0, label="fog:iH:1"))
    F = _math(N, L, "MULTIPLY_ADD", g, -1.0, a, label="fog:nH:1")
    F = _math(N, L, "ADD", F, 1.0, label="fog:H:1")
    return F, g


def _fog_tau(N, L, mnorm, dz):
    """(v12) Optical depth along the ray in metres of dense fog (× 1/visibility in fog_k): from the start distance to
    the surface, through the profile of the fog - exact, F(zp) - F(zs) over the height crossed; almost level rays
    take the density in the middle."""
    dist = _math(N, L, "MULTIPLY", mnorm, 1.0, label="fog:depth:1")
    d1 = _math(N, L, "MAXIMUM", _math(N, L, "SUBTRACT", dist, 0.0, label="fog:s0:1"), 0.0)
    zp = _math(N, L, "MULTIPLY_ADD", dist, dz, 0.0, label="cam:zc:2")
    zs = _math(N, L, "MULTIPLY_ADD", dz, 0.0, 0.0)
    zs.node.label = "fog:s0:1"
    zs = _math(N, L, "ADD", zs, 0.0, label="cam:zc:1")
    Fp, _gp = _fog_F(N, L, zp)
    Fs, _gs = _fog_F(N, L, zs)
    dZ = _math(N, L, "SUBTRACT", zp, zs)
    exact = _math(N, L, "DIVIDE", _math(N, L, "SUBTRACT", Fp, Fs), dZ)
    zm = _math(N, L, "MULTIPLY", _math(N, L, "ADD", zp, zs), 0.5)
    _Fm, gm = _fog_F(N, L, zm)
    small = _math(N, L, "LESS_THAN", _math(N, L, "ABSOLUTE", dZ), 0.05)
    mix = N.new("ShaderNodeMix"); mix.data_type = "FLOAT"; mix.clamp_factor = True
    L.new(small, mix.inputs[0]); L.new(exact, mix.inputs[2]); L.new(gm, mix.inputs[3])
    r = _math(N, L, "ADD", mix.outputs[0], 0.0, label="fog:r2:1")       # (v13) + the haze above (V / V2)
    return _math(N, L, "MULTIPLY", d1, r)


def fog_camera(scene=None):
    """(1.75.49) Before every path-traced image (after its size is set): the camera frame and rotation into the fog
    tree (the height of each pixel's ray) and the haze of the sky for the camera's height."""
    scene = scene or bpy.context.scene
    tree = bpy.data.node_groups.get(FOG_TREE)
    cam = scene.camera
    if cam is None:
        return
    zc = cam.matrix_world.translation.z
    if tree is not None and getattr(scene, "compositing_node_group", None) is tree:
        fr = cam.data.view_frame(scene=scene)
        xs, ys, z = [p.x for p in fr], [p.y for p in fr], fr[0].z
        R = cam.matrix_world.to_3x3().normalized()
        _set_labels(tree, {"ax": max(xs) - min(xs), "bx": min(xs), "ay": max(ys) - min(ys), "by": min(ys),
                           "r20": R[2][0], "r21": R[2][1], "c": R[2][2] * z, "z2": z * z, "zc": zc})
    s = state()
    w = scene.world
    if s and w is not None and w.node_tree is not None and s["fog"]["density"] >= 0.005:
        hk = w.node_tree.nodes.get("haze_k")
        if hk is not None:
            _put(hk.inputs[0], "default_value", -fog_column(s, zc) / fog_visibility(s["fog"]["density"]))


def _neighbour_min(N, L, value, others=False):
    """Smallest value among a pixel and its 8 neighbours (compositor: 8 one-pixel shifts). Outside the picture a
    shift gives 0: counted as very far. others: the 8 neighbours only, without the pixel itself."""
    best = value
    if others:
        inf = N.new("ShaderNodeMath"); inf.operation = "MAXIMUM"; inf.inputs[1].default_value = 1e10
        L.new(value, inf.inputs[0])
        best = inf.outputs[0]
    for dx, dy in ((-1, -1), (0, -1), (1, -1), (-1, 0), (1, 0), (-1, 1), (0, 1), (1, 1)):
        t = N.new("CompositorNodeTranslate")
        for name, v in (("X", float(dx)), ("Y", float(dy))):
            try:
                t.inputs[name].default_value = v
            except (KeyError, TypeError, AttributeError):
                pass
        try:
            t.use_relative = False
        except (AttributeError, TypeError):
            pass
        try:
            t.inputs["Interpolation"].default_value = "Nearest"     # (v17: whole pixels, never a blend with the sky)
        except (KeyError, TypeError, AttributeError):
            pass
        L.new(value, t.inputs[0])
        z0 = N.new("ShaderNodeMath"); z0.operation = "LESS_THAN"; z0.inputs[1].default_value = 1e-6
        L.new(t.outputs[0], z0.inputs[0])
        far = N.new("ShaderNodeMath"); far.operation = "MULTIPLY_ADD"; far.inputs[1].default_value = 1e10
        L.new(z0.outputs[0], far.inputs[0]); L.new(t.outputs[0], far.inputs[2])
        mn = N.new("ShaderNodeMath"); mn.operation = "MINIMUM"
        L.new(best, mn.inputs[0]); L.new(far.outputs[0], mn.inputs[1])
        best = mn.outputs[0]
    return best


def _neighbour_max(N, L, value):
    """Largest value among a pixel and its 8 neighbours (outside the picture a shift gives 0)."""
    best = value
    for dx, dy in ((-1, -1), (0, -1), (1, -1), (-1, 0), (1, 0), (-1, 1), (0, 1), (1, 1)):
        t = N.new("CompositorNodeTranslate")
        for name, v in (("X", float(dx)), ("Y", float(dy))):
            try:
                t.inputs[name].default_value = v
            except (KeyError, TypeError, AttributeError):
                pass
        try:
            t.use_relative = False
        except (AttributeError, TypeError):
            pass
        try:
            t.inputs["Interpolation"].default_value = "Nearest"     # (v17: whole pixels, never a blend with the sky)
        except (KeyError, TypeError, AttributeError):
            pass
        L.new(value, t.inputs[0])
        best = _math(N, L, "MAXIMUM", best, t.outputs[0])
    return best


def _neighbour_sum5(N, L, value):
    """(v16) Sum over a pixel and its 24 neighbours of the 5x5 around (outside the picture a shift gives 0)."""
    total = value
    for dx in (-2, -1, 0, 1, 2):
        for dy in (-2, -1, 0, 1, 2):
            if dx == 0 and dy == 0:
                continue
            t = N.new("CompositorNodeTranslate")
            for name, v in (("X", float(dx)), ("Y", float(dy))):
                try:
                    t.inputs[name].default_value = v
                except (KeyError, TypeError, AttributeError):
                    pass
            try:
                t.use_relative = False
            except (AttributeError, TypeError):
                pass
            try:
                t.inputs["Interpolation"].default_value = "Nearest"
            except (KeyError, TypeError, AttributeError):
                pass
            L.new(value, t.inputs[0])
            total = _math(N, L, "ADD", total, t.outputs[0])
    return total


def _fog_tree():
    tree = bpy.data.node_groups.new(FOG_TREE, "CompositorNodeTree")
    tree.interface.new_socket("Image", in_out="OUTPUT", socket_type="NodeSocketColor")
    N, L = tree.nodes, tree.links
    rl = N.new("CompositorNodeRLayers")
    out = N.new("NodeGroupOutput")
    # volumetric clouds: a volume is not in the Mist pass (mist 1, as the sky), so the haze turned the clouds into
    # flat grey patches. With "keep_far" on, what is at the far end of the Mist pass (only sky and clouds: the
    # ground is far closer than its 6 visibilities) is not fogged - the clouds fade into the haze by themselves
    # (clouds.py), the sky has its own haze. (Volume passes would split them better, but they are not denoised:
    # grain and dark rims on every cloud edge.)
    alpha_s = rl.outputs["Alpha"]
    # the Mist pass of a pixel only partly covered (leaves, hair, edges against the sky) includes the sky at the
    # far end (mist 1) for the uncovered part: mist = alpha·m + (1 − alpha). The distance of what covers the pixel
    # is m = (mist − 1 + alpha) / alpha; without this the leaves against the sky became ghosts of fog.
    m1 = N.new("ShaderNodeMath"); m1.operation = "ADD"
    L.new(rl.outputs["Mist"], m1.inputs[0]); L.new(alpha_s, m1.inputs[1])
    m2 = N.new("ShaderNodeMath"); m2.operation = "SUBTRACT"; m2.inputs[1].default_value = 1.0; m2.use_clamp = True
    L.new(m1.outputs[0], m2.inputs[0])
    am = N.new("ShaderNodeMath"); am.operation = "MAXIMUM"; am.inputs[1].default_value = 1e-4
    L.new(alpha_s, am.inputs[0])
    m3 = N.new("ShaderNodeMath"); m3.operation = "DIVIDE"
    L.new(m2.outputs[0], m3.inputs[0]); L.new(am.outputs[0], m3.inputs[1])
    m3a = m3.outputs[0]                     # (the covered mist, kept for the volumes: see v11 below)
    # never farther than the first surface (Depth pass, the nearest hit): the Mist pass is an average along the
    # rays, and through a see-through surface (a lamp shade, a salt shaker, a glass door made with an opacity map)
    # a few of them reach the sky or the far ground - 400 m for a lamp 2 m away. The haze of 400 m on some pixels
    # and not on their neighbours: the white dots on those pieces, with any number of samples.
    zd = N.new("ShaderNodeMath"); zd.name = "z_to_mist"; zd.operation = "MULTIPLY"; zd.inputs[1].default_value = 1.0
    L.new(rl.outputs["Depth"], zd.inputs[0])
    # but Cycles writes the Depth pass on the first sample only: on an edge pixel (a leaf, a ridge) whose first ray
    # went past it, Depth is the sky. Against the sky the alpha above already finds the leaf; against a volumetric
    # cloud it cannot (the cloud is in the alpha but not in the Mist pass), the leaf got the haze of the far end:
    # bright jagged rims on trees in front of the clouds, with any number of samples. There the nearest Depth of
    # the 3x3 pixels around is used (only when the pixel's own first ray missed: no halo around solid objects).
    nmin = _neighbour_min(N, L, zd.outputs[0])
    m3k = N.new("ShaderNodeMath"); m3k.operation = "MULTIPLY"; m3k.inputs[1].default_value = 1.02
    L.new(m3.outputs[0], m3k.inputs[0])
    miss = N.new("ShaderNodeMath"); miss.operation = "GREATER_THAN"
    L.new(zd.outputs[0], miss.inputs[0]); L.new(m3k.outputs[0], miss.inputs[1])
    dz = N.new("ShaderNodeMath"); dz.operation = "SUBTRACT"
    L.new(nmin, dz.inputs[0]); L.new(zd.outputs[0], dz.inputs[1])
    dzm = N.new("ShaderNodeMath"); dzm.operation = "MULTIPLY"
    L.new(dz.outputs[0], dzm.inputs[0]); L.new(miss.outputs[0], dzm.inputs[1])
    deff = N.new("ShaderNodeMath"); deff.operation = "ADD"
    L.new(zd.outputs[0], deff.inputs[0]); L.new(dzm.outputs[0], deff.inputs[1])
    mz = N.new("ShaderNodeMath"); mz.operation = "MINIMUM"
    L.new(m3.outputs[0], mz.inputs[0]); L.new(deff.outputs[0], mz.inputs[1])
    m3 = mz
    # what is left (1.17.4, measured on a sunset): sparse twigs at the edge of a crown in front of a cloud, where no
    # first ray of the 3x3 pixels hit a leaf. A leaf covering 1% of a pixel otherwise covered by the cloud took the
    # haze of the far end on the whole pixel: isolated bright dots. In those pixels (own first ray missed) the share
    # of surface is estimated from the Mist pass against the nearest Mist of the 5x5 pixels around (mref, the leaf):
    # a_s = (1 - mist) / (1 - mref); the haze is applied only for that share (a_s / alpha) and at the leaf's
    # distance. Against the clear sky a_s = alpha: nothing changes there.
    mref = _neighbour_min(N, L, _neighbour_min(N, L, rl.outputs["Mist"]))
    miss2 = N.new("ShaderNodeMath"); miss2.operation = "GREATER_THAN"; miss2.inputs[1].default_value = 1e9
    L.new(rl.outputs["Depth"], miss2.inputs[0])
    near = N.new("ShaderNodeMath"); near.operation = "LESS_THAN"; near.inputs[1].default_value = 0.9999
    L.new(rl.outputs["Mist"], near.inputs[0])                          # (pure sky and clouds: as before)
    miss3 = N.new("ShaderNodeMath"); miss3.operation = "MULTIPLY"
    L.new(miss2.outputs[0], miss3.inputs[0]); L.new(near.outputs[0], miss3.inputs[1])
    miss2 = miss3
    hit = N.new("ShaderNodeMath"); hit.operation = "SUBTRACT"; hit.inputs[0].default_value = 1.0
    L.new(miss2.outputs[0], hit.inputs[1])
    far_if_hit = N.new("ShaderNodeMath"); far_if_hit.operation = "MULTIPLY_ADD"; far_if_hit.inputs[1].default_value = 1e10
    L.new(hit.outputs[0], far_if_hit.inputs[0]); L.new(mref, far_if_hit.inputs[2])
    mz2 = N.new("ShaderNodeMath"); mz2.operation = "MINIMUM"
    L.new(m3.outputs[0], mz2.inputs[0]); L.new(far_if_hit.outputs[0], mz2.inputs[1])
    m3 = mz2
    one_m = N.new("ShaderNodeMath"); one_m.operation = "SUBTRACT"; one_m.inputs[0].default_value = 1.0
    L.new(rl.outputs["Mist"], one_m.inputs[1])
    one_r = N.new("ShaderNodeMath"); one_r.operation = "SUBTRACT"; one_r.inputs[0].default_value = 1.0
    L.new(mref, one_r.inputs[1])
    one_rc = N.new("ShaderNodeMath"); one_rc.operation = "MAXIMUM"; one_rc.inputs[1].default_value = 1e-4
    L.new(one_r.outputs[0], one_rc.inputs[0])
    a_s = N.new("ShaderNodeMath"); a_s.operation = "DIVIDE"
    L.new(one_m.outputs[0], a_s.inputs[0]); L.new(one_rc.outputs[0], a_s.inputs[1])
    w_raw = N.new("ShaderNodeMath"); w_raw.operation = "DIVIDE"; w_raw.use_clamp = True
    L.new(a_s.outputs[0], w_raw.inputs[0]); L.new(am.outputs[0], w_raw.inputs[1])
    w_m1 = N.new("ShaderNodeMath"); w_m1.operation = "SUBTRACT"; w_m1.inputs[1].default_value = 1.0
    L.new(w_raw.outputs[0], w_m1.inputs[0])
    w = N.new("ShaderNodeMath"); w.operation = "MULTIPLY_ADD"; w.inputs[2].default_value = 1.0
    L.new(w_m1.outputs[0], w.inputs[0]); L.new(miss2.outputs[0], w.inputs[1])
    k = N.new("ShaderNodeMath"); k.name = "fog_k"; k.operation = "MULTIPLY"
    ex = N.new("ShaderNodeMath"); ex.operation = "EXPONENT"
    f = N.new("ShaderNodeMath"); f.operation = "SUBTRACT"; f.inputs[0].default_value = 1.0
    dz = _fog_view_dz(N, L, rl.outputs["Image"])          # (v12) the height direction of each pixel's ray
    L.new(_fog_tau(N, L, m3.outputs[0], dz), k.inputs[0]); L.new(k.outputs[0], ex.inputs[0]); L.new(ex.outputs[0], f.inputs[1])
    # (v14, Luca: «con la nebbia la pioggia diventa macchioline nere»; a thick fog: bright and dark rims on every leaf in
    # front of something far) ONE distance per pixel is wrong whenever the pixel holds two things: a raindrop 3 m away
    # and the street 80 m behind it, the edge of a leaf and the hill behind, a lamp shade and the room seen through it.
    # With the distance of the first ray (the Depth pass: one ray) a pixel whose ray met the drop had the haze of 3 m
    # among pixels with the haze of 80 m - the dark dot; with the mean distance (the Mist pass) the leaf took the haze of
    # the hill. The haze is not proportional to the distance, so neither is right. Now two distances per pixel:
    #   near = the nearest first ray of the 3x3 pixels, far = the farthest first ray (that met a surface) of the 5x5,
    #   and the Mist pass (the mean over all the rays) says how much of the pixel is near: c = (far - mist) / (far - near).
    #   haze = c x haze(near) + (1 - c) x haze(far)
    # One thing in the pixel (near = far): as before. A drop: c is the little share the drop covers, whatever the first
    # ray met. A shade with opacity 0.7: 70% the haze of the shade, 30% that of what is seen through - the same on all
    # its pixels (no dots). Nothing far around that a first ray met (far = near): the haze of the near thing, as before.
    dn = _math(N, L, "MINIMUM", nmin, 1.0)
    fin = _math(N, L, "LESS_THAN", zd.outputs[0], 1e8)
    zfin = _math(N, L, "MULTIPLY", _math(N, L, "MINIMUM", zd.outputs[0], 1.0), fin)
    mfar = _math(N, L, "MAXIMUM", _neighbour_max(N, L, _neighbour_max(N, L, zfin)), dn)
    mm = _math(N, L, "MINIMUM", _math(N, L, "MAXIMUM", m3a, dn), mfar)
    span = _math(N, L, "SUBTRACT", mfar, dn)
    cnear = _math(N, L, "DIVIDE", _math(N, L, "SUBTRACT", mfar, mm), _math(N, L, "MAXIMUM", span, 1e-5), clamp=True)
    two = _math(N, L, "GREATER_THAN", span, 1e-4)
    cnear = _math(N, L, "MULTIPLY_ADD", _math(N, L, "SUBTRACT", cnear, 1.0), two, 1.0)
    k4 = N.new("ShaderNodeMath"); k4.name = "fog_k4"; k4.operation = "MULTIPLY"
    L.new(_fog_tau(N, L, dn, dz), k4.inputs[0])
    f_near = _math(N, L, "SUBTRACT", 1.0, _math(N, L, "EXPONENT", k4.outputs[0]))
    k5 = N.new("ShaderNodeMath"); k5.name = "fog_k5"; k5.operation = "MULTIPLY"
    L.new(_fog_tau(N, L, mfar, dz), k5.inputs[0])
    f_far = _math(N, L, "SUBTRACT", 1.0, _math(N, L, "EXPONENT", k5.outputs[0]))
    f = N.new("ShaderNodeMath"); f.operation = "MULTIPLY_ADD"
    L.new(_math(N, L, "SUBTRACT", f_near, f_far), f.inputs[0]); L.new(cnear, f.inputs[1]); L.new(f_far, f.inputs[2])
    far = N.new("ShaderNodeMath"); far.operation = "GREATER_THAN"; far.inputs[1].default_value = 0.9999
    L.new(rl.outputs["Mist"], far.inputs[0])
    # (v10) where no ray met a surface - nothing at the first ray (Depth: the sky) and nothing in the Mist pass -
    # what covers the pixel can only be a volume (a volumetric model: a cloud, smoke): it is not fogged as if it were
    # at the far end of the Mist pass (it became a flat grey patch); the sky there has its own haze. Volumetric
    # clouds (keep_far 1) as before.
    dinf = N.new("ShaderNodeMath"); dinf.operation = "GREATER_THAN"; dinf.inputs[1].default_value = 1e9
    L.new(rl.outputs["Depth"], dinf.inputs[0])
    keep = N.new("ShaderNodeMath"); keep.name = "keep_far"; keep.operation = "MAXIMUM"; keep.inputs[1].default_value = 0.0
    L.new(dinf.outputs[0], keep.inputs[0])
    kf = N.new("ShaderNodeMath"); kf.operation = "MULTIPLY"
    L.new(far.outputs[0], kf.inputs[0]); L.new(keep.outputs[0], kf.inputs[1])
    nf = N.new("ShaderNodeMath"); nf.operation = "SUBTRACT"; nf.inputs[0].default_value = 1.0
    L.new(kf.outputs[0], nf.inputs[1])
    fk = N.new("ShaderNodeMath"); fk.operation = "MULTIPLY"
    L.new(f.outputs[0], fk.inputs[0]); L.new(nf.outputs[0], fk.inputs[1])
    fw = N.new("ShaderNodeMath"); fw.operation = "MULTIPLY"          # (the share of surface, see above)
    L.new(fk.outputs[0], fw.inputs[0]); L.new(w.outputs[0], fw.inputs[1])
    f = fw
    # (v11) a volumetric model in front of walls and streets: its samples do not reach a surface, the Mist pass
    # counts them as the far end (1) and the Depth pass (first sample only) is the sky on some pixels and the wall
    # on their neighbours. v10 kept a pixel only when its Mist was exactly 1: inside a cloud most pixels are 0.98
    # (a few samples got through to the wall) and took the haze of the far end - a flat grey patch in the middle of
    # the cloud and grey specks along its edge, with any number of samples. Where the first ray met no surface the
    # pixel is now split: a share s of surface (what got through, at the distance m_s of the nearest surface
    # around) takes its haze, the rest (volume or sky) none - the sky has its own, a cloud of a few metres none:
    #   mist = s·m_s + (1 − s)  ->  s = (1 − mist) / (1 − m_s)
    # Against the open sky (leaves, distant clouds) m_s is the leaf's own Mist (mref) and s comes out as before.
    # m_s: the nearest surface of the 5x5 pixels around (Depth), or the nearest Mist there when it is a surface;
    # no surface at all around (inside a cloud, its samples scatter before the wall) -> 0: what got through is near
    # and takes no haze (the Mist there is the cloud's own 0.98, not a distance)
    nmin5 = _neighbour_min(N, L, nmin)
    has = N.new("ShaderNodeMath"); has.operation = "LESS_THAN"; has.inputs[1].default_value = 1.0
    L.new(nmin5, has.inputs[0])
    ms_ = N.new("ShaderNodeMath"); ms_.operation = "MINIMUM"
    L.new(nmin5, ms_.inputs[0]); L.new(mref, ms_.inputs[1])
    msh = N.new("ShaderNodeMath"); msh.operation = "MULTIPLY"
    L.new(ms_.outputs[0], msh.inputs[0]); L.new(has.outputs[0], msh.inputs[1])
    msc = N.new("ShaderNodeMath"); msc.operation = "MINIMUM"; msc.inputs[1].default_value = 0.999
    L.new(msh.outputs[0], msc.inputs[0])
    sn = N.new("ShaderNodeMath"); sn.operation = "SUBTRACT"; sn.inputs[0].default_value = 1.0
    L.new(m3a, sn.inputs[1])
    sd = N.new("ShaderNodeMath"); sd.operation = "SUBTRACT"; sd.inputs[0].default_value = 1.0
    L.new(msc.outputs[0], sd.inputs[1])
    sh = N.new("ShaderNodeMath"); sh.operation = "DIVIDE"; sh.use_clamp = True
    L.new(sn.outputs[0], sh.inputs[0]); L.new(sd.outputs[0], sh.inputs[1])
    k2 = N.new("ShaderNodeMath"); k2.name = "fog_k2"; k2.operation = "MULTIPLY"
    L.new(_fog_tau(N, L, msc.outputs[0], dz), k2.inputs[0])
    ex2 = N.new("ShaderNodeMath"); ex2.operation = "EXPONENT"
    L.new(k2.outputs[0], ex2.inputs[0])
    f2 = N.new("ShaderNodeMath"); f2.operation = "SUBTRACT"; f2.inputs[0].default_value = 1.0
    L.new(ex2.outputs[0], f2.inputs[1])
    fs = N.new("ShaderNodeMath"); fs.operation = "MULTIPLY"
    L.new(sh.outputs[0], fs.inputs[0]); L.new(f2.outputs[0], fs.inputs[1])
    # (v14, Luca: a thick fog, mountains and woods kilometres away: a grey picture with black dots along the ridges and in
    # front of the clouds) the surfaces around are BEYOND the far end of the Mist pass (6 visibilities): the Mist of
    # everything is 1 there, the share above comes out 0 and the pixel (an edge whose first ray went past, a tree seen
    # through a cloud) got no haze at all among pixels completely hazed. With a surface around at any distance (a Depth
    # that is not the sky) and none inside the Mist pass, the pixel takes the whole haze of the far end.
    # (v17, Luca 17/11: a light rim along every ridge of trees against a sunset sky) nmin5 is in units of the Mist pass
    # (Depth x 1/depth, z_to_mist), the sky there is 1e10/depth: 2e5 with a light haze (depth 50 km), under the 1e8 of
    # v14 - every pixel of open sky counted as «a surface beyond the far end» and took the whole haze of the far end,
    # except the two pixels next to a ridge, where a real surface is near: a band without haze along every crown.
    # Now the cut is the sky's, in the same units (sky_cut: 1e9 / depth, set with z_to_mist).
    hasfar = N.new("ShaderNodeMath"); hasfar.operation = "LESS_THAN"; hasfar.label = "sky_cut"
    hasfar.inputs[1].default_value = 1e8
    L.new(nmin5, hasfar.inputs[0])
    nohas = N.new("ShaderNodeMath"); nohas.operation = "SUBTRACT"; nohas.inputs[0].default_value = 1.0
    L.new(has.outputs[0], nohas.inputs[1])
    farcase = N.new("ShaderNodeMath"); farcase.operation = "MULTIPLY"
    L.new(hasfar.outputs[0], farcase.inputs[0]); L.new(nohas.outputs[0], farcase.inputs[1])
    one_far = N.new("ShaderNodeValue"); one_far.outputs[0].default_value = 1.0
    k3 = N.new("ShaderNodeMath"); k3.name = "fog_k3"; k3.operation = "MULTIPLY"
    L.new(_fog_tau(N, L, one_far.outputs[0], dz), k3.inputs[0])
    ex3 = N.new("ShaderNodeMath"); ex3.operation = "EXPONENT"
    L.new(k3.outputs[0], ex3.inputs[0])
    f3 = N.new("ShaderNodeMath"); f3.operation = "SUBTRACT"; f3.inputs[0].default_value = 1.0
    L.new(ex3.outputs[0], f3.inputs[1])
    fsf = N.new("ShaderNodeMix"); fsf.data_type = "FLOAT"; fsf.clamp_factor = True
    L.new(farcase.outputs[0], fsf.inputs[0]); L.new(fs.outputs[0], fsf.inputs[2]); L.new(f3.outputs[0], fsf.inputs[3])
    fs = fsf
    fsel = N.new("ShaderNodeMix"); fsel.data_type = "FLOAT"; fsel.clamp_factor = True
    L.new(dinf.outputs[0], fsel.inputs[0]); L.new(f.outputs[0], fsel.inputs[2]); L.new(fs.outputs[0], fsel.inputs[3])
    f = fsel
    # (v16, Luca 17/11, his own passes of the valley with the tower: thin volumetric clouds 1 km away in front of the wood)
    # in a volume the Mist pass is not a distance: the samples that scatter in the cloud count as the far end (there the
    # mean was 5 km for a cloud and a wood at 1.1 km). Every formula above that reads the Mist went wrong in a different
    # way on the two kinds of pixel of the cloud, at random: those whose first ray stopped in the cloud (Depth = sky,
    # 1 in 4: 0.049 of haze) and those whose first ray reached the wood (near/far of v14 with the farthest ridge seen in
    # the 5x5 through the gaps: 0.03 to 0.20) - the dark dots, kept (and turned the other way) by the denoising of v15,
    # whose guides change at random in the same way. In such pixels - a volume in front of surfaces: a pixel of the 5x5
    # around whose first ray met no surface while some of its rays reached one (Mist below the far end) -
    # the haze is now the mean of the haze of the first rays that met a surface in the 5x5 around, each at its own
    # distance: what is seen through the cloud, the same for all its pixels. Elsewhere (no volume, the sky, sky clouds,
    # a thick cloud with no surface seen around) as before.
    k6 = N.new("ShaderNodeMath"); k6.name = "fog_k6"; k6.operation = "MULTIPLY"
    L.new(_fog_tau(N, L, zfin, dz), k6.inputs[0])
    f_own = _math(N, L, "SUBTRACT", 1.0, _math(N, L, "EXPONENT", k6.outputs[0]))
    hitm = _math(N, L, "SUBTRACT", 1.0, dinf.outputs[0])
    num = _neighbour_sum5(N, L, _math(N, L, "MULTIPLY", f_own, hitm))
    cnt = _neighbour_sum5(N, L, hitm)
    avg = _math(N, L, "DIVIDE", num, _math(N, L, "MAXIMUM", cnt, 1e-6))
    inside = _math(N, L, "MULTIPLY", dinf.outputs[0], near.outputs[0])     # (first ray in a volume, surfaces behind)
    around = _math(N, L, "GREATER_THAN", _neighbour_sum5(N, L, inside), 0.5)
    vol = _math(N, L, "MULTIPLY", around, near.outputs[0])
    use = _math(N, L, "MULTIPLY", vol, _math(N, L, "GREATER_THAN", cnt, 1.5))
    fv = N.new("ShaderNodeMix"); fv.data_type = "FLOAT"; fv.clamp_factor = True; fv.name = "fog_volume"
    L.new(use, fv.inputs[0]); L.new(f.outputs[0], fv.inputs[2]); L.new(avg, fv.inputs[3])
    f = fv
    # (v15, Luca 16/11: «le nuvole sono granulose», volumetric clouds in front of a hillside in the haze) the haze of a pixel
    # comes from the Mist and Depth passes, which are NOT denoised (only the picture is): where a pixel is part cloud and part
    # hillside kilometres behind, each sample tells a different distance and the amount of haze jumps from pixel to pixel -
    # the grain on the clouds, the same with any number of samples worth waiting for. The amount of haze is now denoised like
    # the picture itself (Open Image Denoise, with the albedo and normal of the first thing each pixel shows as guides): the
    # grain goes, the edges of leaves, towers and walls stay where the picture has them (tried before: a blur guided by the
    # picture took the haze off a dark wall seen through dark leaves; guided by the distance it did nothing on the clouds).
    # Only in the final render (render._apply_common unmutes it): in the view it would cost a denoising at every pass.
    fb = N.new("CompositorNodeDenoise"); fb.name = "fog_smooth"
    fb.mute = True                                    # (on only in the final render: render.fog_denoise)
    _put(fb.inputs["HDR"], "default_value", False)
    L.new(f.outputs[0], fb.inputs["Image"])
    if "Denoising Albedo" in rl.outputs and "Denoising Normal" in rl.outputs:
        L.new(rl.outputs["Denoising Albedo"], fb.inputs["Albedo"]); L.new(rl.outputs["Denoising Normal"], fb.inputs["Normal"])
    f = fb
    col = N.new("CompositorNodeRGB"); col.name = "fog_color"
    alpha3 = N.new("CompositorNodeCombineColor")
    for i in range(3):
        L.new(alpha_s, alpha3.inputs[i])
    pre = N.new("ShaderNodeMix"); pre.data_type = "RGBA"; pre.blend_type = "MULTIPLY"; pre.inputs[0].default_value = 1.0
    L.new(col.outputs[0], pre.inputs[6]); L.new(alpha3.outputs[0], pre.inputs[7])
    fog = N.new("ShaderNodeMix"); fog.data_type = "RGBA"
    L.new(f.outputs[0], fog.inputs[0]); L.new(rl.outputs["Image"], fog.inputs[6]); L.new(pre.outputs[2], fog.inputs[7])
    # the sky back: the Environment pass is already weighted by what lets it through (1 - alpha of a leaf edge,
    # the transmittance of a cloud); multiplied once more by (1 - alpha) it darkened every edge against the sky
    add = N.new("ShaderNodeMix"); add.data_type = "RGBA"; add.blend_type = "ADD"; add.inputs[0].default_value = 1.0
    L.new(fog.outputs[2], add.inputs[6]); L.new(rl.outputs["Environment"], add.inputs[7])
    opaque = N.new("CompositorNodeSetAlpha")       # the picture stays opaque (the film is transparent for the sky)
    for sock, val in (("Type", "Replace Alpha"), ("Alpha", 1.0)):
        try:
            opaque.inputs[sock].default_value = val
        except (KeyError, TypeError, AttributeError):
            pass
    try:
        opaque.mode = "REPLACE_ALPHA"               # (older Blender: a property instead of a socket)
    except (AttributeError, TypeError):
        pass
    L.new(add.outputs[2], opaque.inputs[0])
    L.new(opaque.outputs[0], out.inputs[0])
    return tree


# ---------------------------------------------------------------- exposure

def _lamps_light():
    """Light of the scene's own lamps (point, spot, area) where the view looks, in units of the sky model: a camera
    measures them too. Without it the exposure of a night (raised to see by the moon) burnt every lamp to white -
    an old project with the three studio lights, under a night sky, was all white."""
    from . import render
    from .core import CM
    t = render.STATE.camera.get("target") or [0.0, 0.0, 0.0]
    p = Vector([float(x) * CM for x in t])
    total = 0.0
    for ob in bpy.context.scene.objects:
        if ob.type != "LIGHT" or ob.data.type == "SUN" or ob.hide_render or ob.get("simpler_trashed"):
            continue
        d = ob.data
        power = float(d.energy) * max(d.color) if hasattr(d, "color") else float(d.energy)
        if power <= 0:
            continue
        v = p - ob.matrix_world.translation
        dist2 = max(v.length_squared, 0.0025)
        if d.type == "AREA":
            fwd = (ob.matrix_world.to_quaternion() @ Vector((0.0, 0.0, -1.0))).normalized()
            cos = max(0.0, fwd.dot(v.normalized())) if v.length > 1e-6 else 1.0
            sx = float(d.size); sy = float(d.size_y) if d.shape in ("RECTANGLE", "ELLIPSE") else sx
            area = sx * sy * ob.matrix_world.to_scale().x * ob.matrix_world.to_scale().y
            total += power * cos / (math.pi * dist2 + area)
        else:
            total += power / (4.0 * math.pi * dist2)
    return total / K


def auto_exposure_on():
    """«Esposizione automatica» of the Ambiente (on without a sky: the framing can still open up, render.exposure_auto)."""
    s = state()
    return s is None or not outdoor(s) or bool(s.get("exposure", {}).get("auto", True))


def auto_ev():
    """Automatic exposure (EV) from the light of sun, sky and moon, like a camera: 0 at a clear noon."""
    s = state()
    if s is None or not outdoor(s) or not s.get("exposure", {}).get("auto", True):
        return 0.0
    ref = 0.2126 * sun_rgb(55, DEFAULTS["sky"])[0] + 0.7152 * sun_rgb(55, DEFAULTS["sky"])[1] + 0.0722 * sun_rgb(55, DEFAULTS["sky"])[2]
    ref = ref * math.sin(math.radians(55)) + sky_irradiance(55, DEFAULTS["sky"])
    if s.get("mode") == "hdri":
        # light of the photograph on the ground (scene units → model units: / K), sun included
        try:
            _p, a = _hdri_analysis(s)
        except ApiError:
            return 0.0
        from . import hdri
        st = float(s["hdri"].get("strength", 1.0))
        total = a.get("groundIrradiance", 0.0)
        if a.get("sun") and s["hdri"].get("sun", True):
            rgb = a["sun"]["rgb"]
            z = hdri.world_dir(a["sun"]["dir"], 0.0)[2]
            total += (0.2126 * rgb[0] + 0.7152 * rgb[1] + 0.0722 * rgb[2]) * max(0.0, z)
        total = total * st / K + _lamps_light()
        return max(-1.0, min(11.0, 0.85 * math.log2(ref / max(1e-6, total))))
    v = _sun_dir(s)
    elev = math.degrees(math.asin(max(-1.0, min(1.0, v.z))))
    e = sun_rgb(elev, s["sky"])
    lum = 0.2126 * e[0] + 0.7152 * e[1] + 0.0722 * e[2]
    total = (lum * max(0.0, math.sin(math.radians(elev))) * float(s["sun"]["intensity"]) * _cloud_dim(s)
             + sky_irradiance(elev, s["sky"]) * float(s["sky"].get("ambient", 1.0)) * (0.6 + 0.4 * _cloud_dim(s)))
    if elev < -4:
        from . import night as nt
        total += 165.0 * 0.0025 * float(s["night"].get("moon", 1.0)) * 0.6 * nt.phase_light(s["night"].get("phase", 0.5))
    ref = 0.2126 * sun_rgb(55, DEFAULTS["sky"])[0] + 0.7152 * sun_rgb(55, DEFAULTS["sky"])[1] + 0.0722 * sun_rgb(55, DEFAULTS["sky"])[2]
    ref = ref * math.sin(math.radians(55)) + sky_irradiance(55, DEFAULTS["sky"])
    total += _lamps_light()
    ev = 0.85 * math.log2(ref / max(1e-6, total))
    # a night has to look like a night: the camera does not make the moon a cloudy day (+7.7 EV did). From sunset
    # to full night the highest exposure goes down to +4.5 EV: moonlit, dark blue, the lamps stand out.
    top = 11.0 if elev >= 0 else max(NIGHT_EV, 11.0 + (NIGHT_EV - 11.0) * min(1.0, -elev / 8.0))
    return max(-1.0, min(top, ev))


# ---------------------------------------------------------------- info for the app and the view

def _auto_total():
    """(1.79.0) The automatic exposure as the render uses it: with «Esposizione sull'inquadratura» (render.exposure_auto)."""
    from . import render
    return render.exposure_auto()


def info():
    s = state()
    out = {"state": s, "presets": [{"id": p[0], "name": tr(p[1])} for p in PRESETS],
           "grounds": [{"id": g[0], "name": tr(g[1])} for g in GROUNDS], "rev": _REV["n"], "ev": _auto_total(),
           "advChanged": adv_changed(s)}
    from . import rain
    out["rainPainted"] = rain.painted()       # (puddles painted by hand: the rain is on even at 0 / 0)
    out["snowSculpted"] = __import__("simpler.snowsculpt", fromlist=["x"]).present()
    out["snowPainted"] = rain.painted("snow")  # (snow painted by hand: it snows even at 0, when the rain is off)
    from . import snow
    out["snowMantle"] = snow.M["meta"]         # (the last mantle: its cells and vertices, for «Dettaglio del mantello»)
    from . import snowfall
    out["snowFlakes"] = snowfall.F["meta"]      # (the flakes that fall: how many, how long - in the Avanzate)
    from . import raindrops
    out["rainDrops"] = raindrops.F["meta"] if raindrops.F.get("active") else None
    from . import ocean
    out["ocean"] = ocean.state()            # (Paesaggio > Oceano: panel and view, with no call of their own)
    if s is not None and s.get("mode") == "sky":
        # the highest and lowest the sun goes that day, there: the panel says when it never sets (midnight sun, the
        # Night preset then shows daylight) or never rises
        from .scene_ops import sun_vector
        sn = s.get("sun", {})
        zs = [sun_vector(h * 0.25, 0.0, sn.get("day", 172), sn.get("lat", 45.5)).z for h in range(97)]
        out["sunMin"] = round(math.degrees(math.asin(max(-1.0, min(1.0, min(zs))))), 1)
        out["sunMax"] = round(math.degrees(math.asin(max(-1.0, min(1.0, max(zs))))), 1)
    from . import render
    out["evTotal"] = float(render.STATE.config.get("exposure", 0.0)) + out["ev"]
    if s is not None and s.get("mode") == "hdri":
        out["fog"] = {"visibility": 0.0, "color": [0.0, 0.0, 0.0]}
        ob = _find_flag(SUN_KEY)
        out["sunId"] = ob.get(ID_KEY) if ob is not None else ""
        try:
            from . import hdri
            _p, a = _hdri_analysis(s)
            out["hdriFile"] = _p
            if a.get("sun") and s["hdri"].get("sun", True):
                d = hdri.world_dir(a["sun"]["dir"], float(s["hdri"].get("rotation", 0.0)))
                rgb = [max(0.0, x) * float(s["hdri"].get("strength", 1.0)) for x in a["sun"]["rgb"]]
                out["sun"] = {"dir": list(d), "elev": math.degrees(math.asin(max(-1.0, min(1.0, d[2])))), "rgb": rgb,
                              "size": a["sun"]["size"], "inPicture": True}
        except ApiError:
            pass
    elif s is not None and s.get("mode") == "sky":
        v = _sun_dir(s)
        elev = math.degrees(math.asin(max(-1.0, min(1.0, v.z))))
        e = sun_rgb(elev, s["sky"])
        out["sun"] = {"dir": list(v), "elev": elev, "rgb": [x * K for x in e], "size": float(s["sun"]["size"]),
                      "disc": sun_disc_display(elev, s["sky"])}
        dens = s["fog"]["density"]
        prof = fog_profile(s)
        V2 = fog_visibility2(s)
        out["fog"] = {"visibility": fog_visibility(dens) if dens >= 0.005 else 0.0, "color": list(_fog_color(s)),
                      "height": prof[0] if prof else None, "falloff": prof[1] if prof else None,
                      "start": float(s["fog"].get("start", 0.0)),
                      "haze2": fog_visibility(dens) / V2 if V2 and dens >= 0.005 else 0.0}
        ob = _find_flag(SUN_KEY)
        out["sunId"] = ob.get(ID_KEY) if ob is not None else ""
        out["night"] = _night_info(s, v, elev)
    return out


def _night_info(s, v, elev):
    """Stars and moon for the real-time view (it draws them itself, as _night_sky): the same vectors and values."""
    from . import night as nt
    st = nt.status()
    out = {"download": st["state"], "fraction": st.get("fraction"), "error": st.get("error", "")}
    if elev >= -4:
        return out
    info = nt.prepare() if st["state"] == "done" else None
    if info is None:
        return out
    P, A, B, lst = nt.frames(s["sun"])
    fade = max(0.0, min(1.0, (-6.0 - elev) / 10.0))
    out.update(ready=True, P=list(P), A=list(A), B=list(B), lst=lst,
               stars=STARS_K * float(s["night"].get("stars", 0.1)) * fade,
               cover=float(s["clouds"]["cover"]) if not _volumetric(s) else 0.0, rev=info["sig"][1:])
    g = moon_geometry(s, v, elev)
    if g["visible"]:
        out["moon"] = {"m": list(g["m"]), "r": list(g["r"]), "u": list(g["u"]), "sinR": g["sinR"], "radius": g["radius"],
                       "lx": g["lx"], "lz": g["lz"], "disc": g["disc"] / max(1e-6, info["moonMean"]),
                       "halo": g["halo"], "earthshine": EARTHSHINE}
    return out


def refresh_api(_d=None):
    """POST ambience/refresh: the ambience built again as it is (the night sky has just arrived). Not an undo step."""
    s = state()
    if s is None:
        return info()
    return apply(s)


def night_file(name):
    from . import night as nt
    p = nt.view_file(os.path.basename(name or ""))
    if not p:
        raise ApiError(tr("File non trovato"))
    return p


def api_get(_d=None):
    return info()


def api_set(d):
    """POST ambience {preset?, sun?, sky?, clouds?, fog?, night?, ground?, exposure?, mode?}"""
    s = state() or copy.deepcopy(DEFAULTS)
    studio = s.get("mode") == "studio"           # (the studio has no ground: leaving it, the ground comes back)
    if d.get("mode") == "studio" or d.get("preset") == "studio":
        s = _merge(s, {"mode": "studio", "preset": "studio"})
        return apply(s)
    if d.get("mode") == "hdri" or (isinstance(d.get("hdri"), dict) and d["hdri"].get("id")):
        s["mode"] = "hdri"                       # a photographed sky; the settings of the physical sky stay for later
        d = {k: v for k, v in d.items() if k != "mode"}
        return apply(s, d, studio)
    if s.get("mode") == "hdri" and not d.get("preset") and d.get("mode") != "sky" and set(d) <= {"hdri", "ground", "exposure", "presetKeep", "rain", "snow", "resetAdvanced"}:
        return apply(s, d)                       # rotation, strength, sun, ground, rain of the HDRI
    if s.get("mode") != "sky" and not d.get("preset"):
        d = dict(d, mode="sky")
    if s.get("mode") != "sky":
        s["mode"] = "sky"
    d = {k: v for k, v in d.items() if k != "mode"}
    return apply(s, d, studio)


def sun_changed(ob):
    """The sun of the Ambiente was moved from its own panel (hour, date, place, north): the sky follows."""
    s = state()
    if s is None or s.get("mode") != "sky" or not ob.get(SUN_KEY):
        return False
    try:
        p = json.loads(ob.get("simpler_sun") or "{}")
    except ValueError:
        p = {}
    apply(s, {"sun": {k: float(p[k]) for k in ("hour", "north", "day", "lat") if k in p}, "presetKeep": "custom"})
    return True


# ---------------------------------------------------------------- 360° sky for the real-time view

_BAKE = {"rid": 0, "rev": -1, "out": ""}


def bake(_d=None):
    """Asks the preview Blender for a 360° picture of the sky as it is now (does not touch the engine's render).
    Returns {id} (GET ambience/sky?id= tells when it is ready)."""
    from . import previews
    w = bpy.context.scene.world
    if w is None:
        raise ApiError(tr("Nessun ambiente"))
    if _BAKE["rev"] == _REV["n"] and _BAKE["rid"]:
        return {"id": _BAKE["rid"], "rev": _REV["n"]}
    blend = os.path.join(previews.work_dir(), f"sky{_REV['n']}.blend")
    tmp = w.copy()
    tmp.name = "Simpler Sky Bake"
    dk = tmp.node_tree.nodes.get("sun_disc_k") if tmp.node_tree else None
    if dk is not None:
        dk.outputs[0].default_value = 0.0         # (the real-time view draws its own disc, sharper)
    nk = tmp.node_tree.nodes.get("night_k") if tmp.node_tree else None
    if nk is not None:
        nk.outputs[0].default_value = 0.0         # (stars and moon: the real-time view draws them, sharp)
    pc = tmp.node_tree.nodes.get("painted_clouds") if tmp.node_tree else None
    if pc is not None:
        pc.outputs[0].default_value = 1.0          # (the real-time view: painted clouds)
    try:
        bpy.data.libraries.write(blend, {tmp}, fake_user=True, path_remap="ABSOLUTE", compress=False)
    finally:
        bpy.data.worlds.remove(tmp)
    out = os.path.join(previews.work_dir(), f"sky{_REV['n']}.bin")
    rid = previews.enqueue_sky(blend, out, 1024, 512)
    _BAKE.update(rid=rid, rev=_REV["n"], out=out)
    return {"id": rid, "rev": _REV["n"]}


def sky_status(d):
    from . import previews
    r = previews.status({"id": d.get("id")})
    if r.get("state") == "error" and _BAKE.get("logged") != d.get("id"):
        _BAKE["logged"] = d.get("id")
        log("SIMPLER_SKY", "bake failed:", r.get("error", ""))     # (the real-time view keeps the sky it had)
    if r.get("state") == "done":
        r["file"] = os.path.basename(r.get("path") or "")
        try:
            with open((r.get("path") or "") + ".json", encoding="utf-8") as f:
                r["stats"] = json.load(f)
        except (OSError, ValueError):
            r["stats"] = {}
        # the haze of the path tracing takes the colour of the horizon just measured (same as the view)
        hor = r["stats"].get("horizon")
        if hor and int(d.get("id") or 0) == _BAKE["rid"] and _BAKE.get("fogSet") != _BAKE["rid"]:
            _BAKE["fogSet"] = _BAKE["rid"]
            tree = bpy.data.node_groups.get(FOG_TREE)
            if tree is not None and bpy.context.scene.compositing_node_group is tree:
                node = tree.nodes.get("fog_color")
                old = tuple(node.outputs[0].default_value)[:3]
                if max(abs(old[i] - hor[i]) for i in range(3)) > 1e-3 * max(1e-6, max(hor)):
                    node.outputs[0].default_value = (*hor, 1.0)
                    from . import render
                    render.invalidate()
    return r


def sky_file(name):
    from . import previews
    name = os.path.basename(name or "")
    if not (name.startswith("sky") and name.endswith(".bin")):
        raise ApiError(tr("File non valido"))
    p = os.path.join(previews.work_dir(), name)
    if not os.path.isfile(p):
        raise ApiError(tr("File non trovato"))
    return p
