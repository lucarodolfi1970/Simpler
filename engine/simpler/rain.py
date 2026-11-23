"""Pioggia (Ambiente): wet surfaces and puddles - in the path tracing and in the real-time view with the same formulas.

Nothing of the models changes. Every material whose surface is a Principled BSDF (directly or through Add / Mix
shaders: the reflected light of refcaustics) gets a second material output for Cycles only (OUT, target CYCLES):
the same chain with the Principled replaced by a group holding a Principled with the same inputs (links shared,
values copied) and the rain on its colour, roughness and coat. The output that the rest of Simpler reads (the
active one, for every renderer: matedit, the glTF export of the real-time view, glass, water, refcaustics) stays
the user's: nothing that reads materials sees the rain. Off (no wetness, no puddles, studio): taken away again.

The rain (the same lines are in viewer.js, wetGLSL):
  nz         the shading normal (world) facing up
  wetness    w = (1 - (1 - wet)^2) * (0.25 + 0.75 * smoothstep(-0.3, 0.7, nz))   seen early; walls less, undersides little
  puddles    only on flat surfaces facing up: smoothstep(0.9, 0.98, nz); a tiling map seen from above (equalised:
             the share of the ground over a threshold is the share asked), SIZE metres a tile, moved by offX/offY
             tiles: t = 1 - 0.55 * amount, edge e = 0.01 + 0.3 * soft; puddle = smoothstep(t - e, t + e, n); around
             each puddle the ground is fully wet: smoothstep(t - e - 0.12, t, n)
  film       heavy rain: a sheet of water on all the flat ground, 0.85 * smoothstep(0.5, 1, wet) (as a puddle,
             without its depth); the water is max(puddle, film)
  porosity   p = smoothstep(0.2, 0.9, roughness) * (1 - metallic)       asphalt, stone, wood darken; metal, paint not
  colour     *= (1 - 0.6 * w * p) * mix(1, mix(0.15, 0.75, look), puddle)       look 0 = mirror, 1 = clear water
  roughness  mix(r, min(r, mix(0.05, 0.25, p)), w)       (w here also max(halo, film))
  coat       the water: weight max(coat, water), roughness -> 0.02, IOR -> 1.33
  painted    puddles painted by hand (paint map: add a, remove r): puddle = max(auto * (1 - r), smoothstep(0.5 - ep,
             0.5 + ep, a) * flat), ep = 0.02 + 0.43 * paintSoft, halo likewise with smoothstep(0.05, 0.5, a), film * (1 - r); also under a shelter
No puddles on cut-out materials (leaves: Alpha linked; decals excepted) and on the pieces of distributions (grass,
trees: drawn as copies). Glass and water stay as they are.

Neve (the same group; snow and rain never together: while it snows the rain is suspended, its settings kept):
  noise      (v25) mid = map(xy * 0.027 + 0.5 * soff + (0.71, 0.13)), big = map(R2 xy * 0.0061 + (0.29, 0.83)),
             fine = map(R1 xy / 8 m + soff + (0.37, 0.61) + 1.6 * (mid - 0.5, big - 0.5)), R1/R2 turned +37°/-53°;
             ns = 0.5 + 1.17 * (0.5 fine + 0.3 mid + 0.2 big - 0.5)  (SNOW_NS: before, 0.6 * map(xy / 8 m) + 0.4 * mid -
             the 8 m tiles repeated over a mountain as a wallpaper)
  cover      S = smoothstep(ts - es, ts + es, ns) * smoothstep(wlo, wlo + 0.3, nzs) * open_up * min(50 * amount, 1)
             nzs = nz + 0.35 * (map(xy * 0.06 + (0.23, 0.47)) - 0.5): the slope shaken (v23: no straight-sided patches
             on a coarse mesh)
             ts = 1 - 1.15 * amount, es = 0.02 + 0.3 * ssoft, wlo = 0.75 - 0.95 * walls («Sulle pareti»: at 1 down to the walls)
             open_up: not under a shelter, not on «Sempre asciutto»
  surface    colour -> mix(c, (0.88, 0.90, 0.93), S); roughness -> mix(r, 0.55, S); metallic *= 1 - S;
             coat weight *= 1 - S; normal -> normalize(mix(N, geometry normal, S))  (the snow hides the bumps)
  painted    snow painted by hand (paint map, layer snow: add a, remove r, height h): S = max(S * (1 - r),
             smoothstep(0.5 - eq, 0.5 + eq, a) * smoothstep(wlo, wlo + 0.3, nz) * keep), eq = 0.02 + 0.43 * paintSoft;
             only where the height painted matches (as the puddles), also under a shelter
  old snow   «Neve vecchia» a (the same in snow.py for the mantle and in viewer.js snowAged): stains from the same map
             at two other scales, n2 = 0.45 * map(xy * 0.31 + (0.23, 0.87)) + 0.55 * map(xy * 0.071 + (0.55, 0.29)),
             blot = smoothstep(1 - 0.55 a, 1.25 - 0.55 a, n2); dirt d = a * clamp(0.75 blot + 0.5 edge + 0.6 pressed)
             (edge: where the snow thins - here 1 - smoothstep(0.35, 0.95, S), on the mantle its thickness; pressed:
             footprints and tyres of the mantle); colour = mix(mix(snow, (0.80, 0.79, 0.76), 0.6 a), (0.42, 0.38,
             0.33), 0.55 d); roughness of the snow -> mix(it, 0.35, 0.6 a) (a crust that melted and froze)
"""
import json
import math
import os
import struct
import time
import zlib

import bpy
from mathutils import Vector

from .core import log
from . import volumetric

VERSION = 26          # (24, 1.76.33: the top of the shore's wet band ragged, as the spray reaches; 25, 1.76.45: the
                      # snow's pattern no longer repeats - SNOW_NS; 26, 17/11: the drops on the sides over the world planes)
MASK_VERSION = 1
GROUP = f"Simpler Pioggia v{VERSION}"
NZJ_SCALE, NZJ_OFF, NZJ_AMP = 0.06, (0.23, 0.47), 0.35     # (v23) the slope of the snow shaken (see the snow below)
# (v25, 1.76.45, Luca: «la neve con una quantità di 29,6 crea quegli strani disegni ripetuti») the noise of the snow: the
# map of 8 m alone decided where a little snow lies, and it repeats every 8 m - from far a mountain was a wallpaper of
# the same white marks. Now the 8 m map is turned (37°) and pushed around by two big ones (37 m and 164 m, turned the
# other way), so its repeats never line up, and the big ones weigh in too: patches of every size. Spread as before
# (the same width of values: the same amount covers as much). The same in snow.py (_snow_ns) and viewer.js.
SNOW_NS = {"r1": (0.799, -0.602, 0.602, 0.799), "r2": (0.602, 0.799, -0.799, 0.602), "s_mid": 0.027, "s_big": 0.0061,
           "o_big": (0.29, 0.83), "warp": 1.6, "w": (0.3, 0.35, 0.35), "spread": 1.27}
BSDF_GROUP = f"Simpler Pioggia BSDF v{VERSION}"
PREFIX = "simpler_wet"
OUT = PREFIX + "_out"
SIG = "simpler_wet_sig"
MASK = f"puddles_v{MASK_VERSION}.png"
MASK_N = 1024

SH_TAPS = ((0.0, 0.0), (0.3333, 0.0), (0.0, 0.3333), (-0.3333, 0.0), (-0.0, -0.3333), (0.5774, 0.3333), (-0.3333, 0.5774), (-0.5774, -0.3333), (0.3333, -0.5774), (0.5, 0.866), (-0.866, 0.5), (-0.5, -0.866), (0.866, -0.5))     # (unit circle: × the radius)
SH_SOFT_R = 0.12          # metres: the edge of a dry patch fades over about twice this (plus half of «Morbidezza»)
DEFAULTS = {"wet": 0.0, "puddles": 0.0, "size": 0.5, "look": 0.3, "offX": 0.0, "offY": 0.0, "soft": 0.3, "outdoor": True,
            "paintSoft": 0.5}
SNOW_DEFAULTS = {"amount": 0.0, "walls": 0.3, "soft": 0.3, "offX": 0.0, "offY": 0.0, "outdoor": True, "depth": 0.1,
                 "paintSoft": 0.5, "detail": 0.5, "age": 0.0}
# the flakes that fall (snowfall.py): not clamped with the rest, read there
SNOW_DEFAULTS.update({"fall": False, "fallAmount": 0.5, "fallSize": 0.5, "fallWind": 0.2, "fallDir": 0.0, "fallGust": 0.4,
                      "fallZones": 0.4, "fallBlur": 0.4, "fallFar": 60.0, "fallSeed": 1})
# the drops that fall (raindrops.py): in the rain's settings, not clamped with the rest, read there
from .raindrops import DROP_DEFAULTS as _DROP_DEFAULTS
DEFAULTS.update(_DROP_DEFAULTS)
SNOW_COLOR = (0.88, 0.90, 0.93)
DRY_KEY = "simpler_dry"                  # on an object (and the pieces in it): «Sempre asciutto» - no rain
# «Sempre asciutto» is two switches: no rain, no snow. DRY_KEY alone (as before 1.67.1) = neither; with SNOWOK_KEY the
# snow comes (a car: drops on it when it rains, but no mantle swallowing it when it snows... or the other way);
# NOSNOW_KEY = no snow only. Read by the materials (shader attributes), the mantle and the real-time view.
SNOWOK_KEY = "simpler_dry_snowok"
NOSNOW_KEY = "simpler_nosnow"
DRY_KEYS = (DRY_KEY, SNOWOK_KEY, NOSNOW_KEY)


def rain_dry(ob):
    """No rain on this object (it alone, not the groups above it)."""
    return bool(ob.get(DRY_KEY))


def snow_dry(ob):
    """No snow on this object (it alone)."""
    return bool((ob.get(DRY_KEY) and not ob.get(SNOWOK_KEY)) or ob.get(NOSNOW_KEY))


def set_dry_state(ob, rain_off, snow_off):
    """Writes the two switches on one object. The materials read them as attributes of the object: with the
    persistent data of the path tracing Cycles syncs the object again only when it is tagged (before 1.67.4 the
    switches took effect only at the next opening of the project)."""
    before = tuple(ob.get(k) for k in DRY_KEYS)
    _write_dry(ob, rain_off, snow_off)
    if tuple(ob.get(k) for k in DRY_KEYS) != before:
        ob.update_tag(refresh={"OBJECT"})


def _write_dry(ob, rain_off, snow_off):
    for k in DRY_KEYS:
        if k in ob:
            del ob[k]
    if rain_off:
        ob[DRY_KEY] = 1.0
        if not snow_off:
            ob[SNOWOK_KEY] = 1.0
    elif snow_off:
        ob[NOSNOW_KEY] = 1.0


def dry_code(ob):
    """0 none, 1 no rain and no snow, 2 no rain, 3 no snow (export_job: _wetdry, the real-time view)."""
    r, sn = rain_dry(ob), snow_dry(ob)
    return 1 if r and sn else 2 if r else 3 if sn else 0
OPEN_KEY = "simpler_noshelter"           # on an object (or a group above it): «Non fa riparo» - a car driving by

_STATE = {"key": None, "changes": 0, "mats": 0}


def touch(geometry=True):
    """Something of the scene changed (not only the camera): the materials are looked at again. geometry=False: only
    materials (a stroke of painted dirt): the shelter, the mantle and the coast, which follow the shapes, stay - each
    stroke started them again (3 to 16 s on the cathedral) and the engine was busy all the time one painted (1.73.9)."""
    if geometry:
        _STATE["changes"] += 1
    else:
        _STATE["mats"] += 1


# ---------------------------------------------------------------- settings

def settings(s):
    """The rain (or the snow) of an ambience state, clamped; None when there is none (studio, or nothing on).
    While it snows the rain is suspended: wet and puddles 0, painted puddles off, the snow's «Solo all'aperto».
    It snows when the amount is above 0, or when snow was painted by hand and the rain has nothing on."""
    if not s or s.get("mode") not in ("sky", "hdri"):
        return None
    c = lambda v, lo, hi: max(lo, min(hi, float(v)))
    sn = dict(SNOW_DEFAULTS, **(s.get("snow") or {}))
    amount = c(sn["amount"], 0, 1)
    r = dict(DEFAULTS, **(s.get("rain") or {}))
    r = {"wet": c(r["wet"], 0, 1), "puddles": c(r["puddles"], 0, 1), "size": c(r["size"], 0, 1),
         "look": c(r["look"], 0, 1), "offX": c(r["offX"], -1, 1), "offY": c(r["offY"], -1, 1), "soft": c(r["soft"], 0, 1),
         "paintSoft": c(r.get("paintSoft", 0.5), 0, 1),
         "outdoor": bool(r.get("outdoor", True)), "snowing": False, "snow": 0.0, "walls": 0.3, "ssoft": 0.3,
         "soffX": 0.0, "soffY": 0.0, "spaintSoft": 0.5, "sdetail": 0.5, "sage": 0.0}
    # (the drops that fall: it rains with them, and the surfaces follow their intensity - «Bagna le superfici»)
    from .raindrops import wet_from_drops
    rr = dict(DEFAULTS, **(s.get("rain") or {}))
    dw = wet_from_drops(rr)
    drops = bool(rr.get("drop")) and c(rr.get("dropAmount", 0.5), 0, 1) > 0
    if sn.get("fall") and c(sn.get("fallAmount", 0.5), 0, 1) > 0:
        drops, dw = False, 0.0                       # (flakes falling: it snows - raindrops.settings)
    r["wet"] = max(r["wet"], c(dw, 0, 1))
    # «Gocce sulle superfici» (_drops_nodes): beads = their amount, 0 when off
    rb = dict(DEFAULTS, **(s.get("rain") or {}))
    r.update(beads=c(rb.get("beadAmount", 0.5), 0, 1) if rb.get("beads", True) else 0.0,
             bsize=c(rb.get("beadSize", 0.5), 0, 1), bbig=c(rb.get("beadBig", 0.3), 0, 1),
             briv=c(rb.get("beadRivul", 0.4), 0, 1), bfilm=c(rb.get("beadFilm", 0.5), 0, 1),
             rk=c(rb.get("dropAmount", 0.5), 0, 1) if drops else 0.0, ramount=c(rb.get("puddleRings", 0.5), 0, 1))
    raining = r["wet"] > 0 or r["puddles"] > 0 or painted() or drops
    if amount > 0 or (painted("snow") and not raining):
        return {"wet": 0.0, "puddles": 0.0, "size": 0.5, "look": 0.3, "offX": 0.0, "offY": 0.0, "soft": 0.3, "paintSoft": 0.5,
                "outdoor": bool(sn.get("outdoor", True)), "snowing": True, "snow": amount, "walls": c(sn["walls"], 0, 1),
                "ssoft": c(sn["soft"], 0, 1), "soffX": c(sn["offX"], -1, 1), "soffY": c(sn["offY"], -1, 1),
                "spaintSoft": c(sn.get("paintSoft", 0.5), 0, 1), "sdetail": c(sn.get("detail", 0.5), 0, 1),
                "sage": c(sn.get("age", 0.0), 0, 1)}
    if not raining:
        return None
    return r


def tile_size(size):
    """Metres of one tile of the puddle map (slider 0..1: 2.5 m .. 60 m, 12 m in the middle)."""
    return 2.5 * 24.0 ** float(size)


def clamp_state(s):
    r = s.setdefault("rain", dict(DEFAULTS))
    for k, v in DEFAULTS.items():
        r.setdefault(k, v)
    for k in ("wet", "puddles", "size", "look", "soft", "paintSoft"):
        r[k] = max(0.0, min(1.0, float(r[k])))
    for k in ("offX", "offY"):
        r[k] = max(-1.0, min(1.0, float(r[k])))
    r["outdoor"] = bool(r["outdoor"])
    sn = s.setdefault("snow", dict(SNOW_DEFAULTS))
    for k, v in SNOW_DEFAULTS.items():
        sn.setdefault(k, v)
    for k in ("amount", "walls", "soft", "paintSoft", "detail", "age"):
        sn[k] = max(0.0, min(1.0, float(sn[k])))
    sn["depth"] = max(0.0, min(0.5, float(sn["depth"])))       # the mantle (snow.py): metres
    for k in ("offX", "offY"):
        sn[k] = max(-1.0, min(1.0, float(sn[k])))
    sn["outdoor"] = bool(sn["outdoor"])


# ---------------------------------------------------------------- the puddle map

def _png_gray(path, img):
    """An 8-bit grey PNG (rows from the top, as every viewer reads it)."""
    h, w = img.shape
    raw = b"".join(b"\x00" + img[y].tobytes() for y in range(h))

    def chunk(t, d):
        return struct.pack(">I", len(d)) + t + d + struct.pack(">I", zlib.crc32(t + d) & 0xFFFFFFFF)
    data = b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 0, 0, 0, 0)) + \
        chunk(b"IDAT", zlib.compress(raw, 6)) + chunk(b"IEND", b"")
    tmp = path + ".tmp"
    with open(tmp, "wb") as f:
        f.write(data)
    os.replace(tmp, path)


def mask_path():
    """The tiling puddle map (made once, next to the textures of the ground): blotches of every size with ragged
    edges, equalised so that a value is also the share of the surface under it."""
    from .ambience import _tex_dir, _fbm
    path = os.path.join(_tex_dir(), MASK)
    if os.path.isfile(path):
        return path
    import numpy as np
    rng = np.random.default_rng(5)
    v = _fbm(MASK_N, rng, 1.9, 2, 24) + 0.12 * _fbm(MASK_N, rng, 1.0, 20, 160)
    rank = np.empty(v.size)
    rank[np.argsort(v.ravel(), kind="stable")] = np.arange(v.size)
    eq = (rank / (v.size - 1)).reshape(v.shape)
    _png_gray(path, np.round(eq * 255).astype(np.uint8))
    return path


def mask_file(_name=None):
    return mask_path()


def _mask_image():
    im = bpy.data.images.load(mask_path(), check_existing=True)
    try:
        im.colorspace_settings.name = "Non-Color"
    except TypeError:
        pass
    return im


# ---------------------------------------------------------------- node groups

def _math_group():
    """The rain on colour, roughness and coat (formulas at the top). Its Value nodes hold the settings: one change
    of the rain changes every material at once."""
    g = bpy.data.node_groups.get(GROUP)
    if g is not None:
        return g
    g = bpy.data.node_groups.new(GROUP, "ShaderNodeTree")
    I = g.interface
    for name, t in (("Base Color", "NodeSocketColor"), ("Roughness", "NodeSocketFloat"), ("Metallic", "NodeSocketFloat"),
                    ("Coat Weight", "NodeSocketFloat"), ("Coat Roughness", "NodeSocketFloat"), ("Coat IOR", "NodeSocketFloat"),
                    ("Normal", "NodeSocketVector"), ("Puddles", "NodeSocketFloat"), ("Coat Normal", "NodeSocketVector"),
                    ("Drops", "NodeSocketFloat"), ("Glass", "NodeSocketFloat"), ("Alpha", "NodeSocketFloat"),
                    ("AlphaDrops", "NodeSocketFloat")):
        I.new_socket(name, in_out="INPUT", socket_type=t)
    for name, t in (("Base Color", "NodeSocketColor"), ("Roughness", "NodeSocketFloat"), ("Metallic", "NodeSocketFloat"),
                    ("Coat Weight", "NodeSocketFloat"), ("Coat Roughness", "NodeSocketFloat"), ("Coat IOR", "NodeSocketFloat"),
                    ("Normal", "NodeSocketVector"), ("Coat Normal", "NodeSocketVector"), ("Alpha", "NodeSocketFloat")):
        I.new_socket(name, in_out="OUTPUT", socket_type=t)
    N, L = g.nodes, g.links
    gi, go = N.new("NodeGroupInput"), N.new("NodeGroupOutput")

    def val(name, v):
        n = N.new("ShaderNodeValue")
        n.name = n.label = name
        n.outputs[0].default_value = v
        return n.outputs[0]

    def put(sock, x):
        if isinstance(x, (int, float)):
            sock.default_value = x
        else:
            L.new(x, sock)

    def m(op, a, b=None, c=None):
        n = N.new("ShaderNodeMath")
        n.operation = op
        for i, x in enumerate((a, b, c)):
            if x is not None:
                put(n.inputs[i], x)
        return n.outputs[0]

    def smooth(e0, e1, x):
        n = N.new("ShaderNodeMapRange")
        n.interpolation_type = "SMOOTHSTEP"
        n.clamp = True
        put(n.inputs["Value"], x)
        put(n.inputs["From Min"], e0)
        put(n.inputs["From Max"], e1)
        n.inputs["To Min"].default_value = 0.0
        n.inputs["To Max"].default_value = 1.0
        return n.outputs["Result"]

    def mix(a, b, f):                                # a + f * (b - a)
        return m("MULTIPLY_ADD", f, m("SUBTRACT", b, a), a)

    wet, amount, inv = val("wet", 0.0), val("puddles", 0.0), val("invsize", 1.0 / tile_size(0.5))
    look, ox, oy = val("look", 0.3), val("offx", 0.0), val("offy", 0.0)
    edge = m("MULTIPLY_ADD", val("soft", 0.3), 0.3, 0.01)
    geo = N.new("ShaderNodeNewGeometry")
    sn = N.new("ShaderNodeSeparateXYZ")
    L.new(geo.outputs["Normal"], sn.inputs[0])
    sp = N.new("ShaderNodeSeparateXYZ")
    L.new(geo.outputs["Position"], sp.inputs[0])
    nz = sn.outputs["Z"]
    # the shelter: the scene seen from above (shelter_map); under something higher it stays dry - fully on what
    # faces up, half on walls (rain comes slanted); «Sempre asciutto» objects (DRY_KEY) never get wet
    sh_on, x0, y0, sinv = val("sh_on", 0.0), val("sh_x0", 0.0), val("sh_y0", 0.0), val("sh_inv", 1.0)
    zmin, zr, lo = val("sh_zmin", 0.0), val("sh_zr", 1.0), val("sh_lo", 0.5)
    # (1.75.17) the edge of the dry patch softened: the cover averaged over SH_TAPS points (the point and three rings
    # around it, out to SH_SOFT_R metres, more with «Morbidezza»), as the rain comes a little slanted - a single sample
    # drew the outline of the map in steps of its cells, a hard line on the wet road (Luca)
    rad = m("MULTIPLY", m("MULTIPLY_ADD", N["soft"].outputs[0], 0.5, SH_SOFT_R), sinv)
    img = None
    covers = []
    for k, (dx, dy) in enumerate(SH_TAPS):
        uvs = N.new("ShaderNodeCombineXYZ")
        ux = m("MULTIPLY", m("SUBTRACT", sp.outputs["X"], x0), sinv)
        uy = m("MULTIPLY", m("SUBTRACT", sp.outputs["Y"], y0), sinv)
        if dx:
            ux = m("MULTIPLY_ADD", rad, dx, ux)
        if dy:
            uy = m("MULTIPLY_ADD", rad, dy, uy)
        L.new(ux, uvs.inputs["X"])
        L.new(uy, uvs.inputs["Y"])
        stex = N.new("ShaderNodeTexImage")
        stex.name = "shelter" if k == 0 else f"shelter{k}"
        stex.interpolation = "Linear"
        stex.extension = "CLIP"
        L.new(uvs.outputs[0], stex.inputs["Vector"])
        ssep = N.new("ShaderNodeSeparateColor")
        L.new(stex.outputs["Color"], ssep.inputs[0])
        v = ssep.outputs[0]
        height = m("SUBTRACT", m("MULTIPLY_ADD", v, zr, zmin), m("MULTIPLY", m("LESS_THAN", v, 1e-4), 1e6))
        covers.append(smooth(lo, m("ADD", lo, 0.3), m("SUBTRACT", height, sp.outputs["Z"])))
    tot = covers[0]
    for c_ in covers[1:]:
        tot = m("ADD", tot, c_)
    cover = m("MULTIPLY", m("MULTIPLY", tot, 1.0 / len(SH_TAPS)), sh_on)
    # «Sempre asciutto» (set_dry_state): the object (for a piece of a distribution, the part of its model) and the
    # instancer (the points of a distribution: set_dry marks those when the whole distribution is dry)
    def dryness(kind):
        out = None
        for at in ("OBJECT", "INSTANCER"):
            a = {}
            for k in DRY_KEYS:
                n = N.new("ShaderNodeAttribute")
                n.attribute_type = at
                n.attribute_name = k
                a[k] = n.outputs["Fac"]
            if kind == "rain":
                v = a[DRY_KEY]
            else:   # DRY_KEY without SNOWOK_KEY, or NOSNOW_KEY
                v = m("ADD", m("MULTIPLY", a[DRY_KEY], m("SUBTRACT", 1.0, a[SNOWOK_KEY])), a[NOSNOW_KEY])
            out = v if out is None else m("MAXIMUM", out, v)
        return m("SUBTRACT", 1.0, m("MINIMUM", m("MAXIMUM", out, 0.0), 1.0))
    keep = dryness("rain")
    keep_s = dryness("snow")
    open_up_s = m("MULTIPLY", m("SUBTRACT", 1.0, cover), keep_s)
    open_up = m("MULTIPLY", m("SUBTRACT", 1.0, cover), keep)
    open_wall = m("MULTIPLY", m("SUBTRACT", 1.0, m("MULTIPLY", cover, m("MULTIPLY_ADD", smooth(0.3, 0.9, nz), 0.5, 0.5))), keep)
    wc = m("SUBTRACT", 1.0, m("POWER", m("SUBTRACT", 1.0, wet), 2.0))
    w = m("MULTIPLY", m("MULTIPLY", wc, m("MULTIPLY_ADD", smooth(-0.3, 0.7, nz), 0.75, 0.25)), open_wall)
    # the shore (Paesaggio > Oceano > Costa, ocean.coast_band): wet from under the sea up to where the waves run,
    # whatever the rain - also under a shelter (the waves come from the side), never on «Sempre asciutto»
    c_on, c_top, c_soft = val("c_on", 0.0), val("c_top", 0.0), val("c_soft", 0.3)
    # (1.76.33, Luca: «il bordo che tocca l'acqua è troppo netto») the top of the band ragged: where the spray and the
    # run of the waves reach, higher in places and lower in others (a noise of ~40 cm and one of ~2 m), not a level line
    cz_n = N.new("ShaderNodeTexNoise"); cz_n.inputs["Scale"].default_value = 2.5; cz_n.inputs["Detail"].default_value = 3.0
    cz_n2 = N.new("ShaderNodeTexNoise"); cz_n2.inputs["Scale"].default_value = 0.5; cz_n2.inputs["Detail"].default_value = 1.0
    L.new(geo.outputs["Position"], cz_n.inputs["Vector"]); L.new(geo.outputs["Position"], cz_n2.inputs["Vector"])
    rag = m("ADD", m("MULTIPLY", m("SUBTRACT", cz_n.outputs["Fac"], 0.5), 3.0), m("MULTIPLY", m("SUBTRACT", cz_n2.outputs["Fac"], 0.5), 4.0))
    cz = m("SUBTRACT", sp.outputs["Z"], m("MULTIPLY", rag, c_soft))
    shore = m("MULTIPLY", m("MULTIPLY", m("SUBTRACT", 1.0, smooth(m("SUBTRACT", c_top, c_soft), c_top, cz)), c_on), keep)
    # (1.73.7) under the sea the bed is wet and dark but not a mirror: water over sand reflects almost nothing (the
    # two bend the light alike). A glossy bed under shallow water reflected the low sun, and the water, taking the
    # red away, made it a bright green patch in the glint (Luca's beach at sunset). Glossy only above the level
    c_lo = val("c_lo", 0.0)
    # (1.75.0) glossy only ABOVE the level: from 15 cm under it the bed under the first centimetres of water was still a
    # mirror - the green patch in the glint at sunset came back (Luca's test oceano, 1.74.0)
    # (the waves run up over the lower half of the wet band: glossy from there up, where the water has gone back)
    run = m("SUBTRACT", c_top, c_lo)
    shore_gloss = m("MULTIPLY", shore, smooth(m("MULTIPLY_ADD", run, 0.35, c_lo), m("MULTIPLY_ADD", run, 0.65, c_lo), sp.outputs["Z"]))
    # ... and never seen through the water: the waves run up the beach over the wet band, and the sand under that thin
    # water was still a mirror (a ray that crossed a refracting surface - Light Path: Transmission Depth > 0)
    lpath = N.new("ShaderNodeLightPath")
    dry_path = m("LESS_THAN", lpath.outputs["Transmission Depth"], 0.5)
    shore_gloss = m("MULTIPLY", shore_gloss, dry_path)
    # the rain's own gloss too, where the sea can be over it (under the top of its wet band) and seen through water
    by_sea = m("MULTIPLY", c_on, m("SUBTRACT", 1.0, smooth(m("SUBTRACT", c_top, c_soft), c_top, cz)))
    w_g = m("MULTIPLY", w, m("SUBTRACT", 1.0, m("MULTIPLY", by_sea, m("SUBTRACT", 1.0, dry_path))))
    wg = m("MAXIMUM", w_g, shore_gloss)
    w = m("MAXIMUM", w, shore)
    # the map, seen from above
    uvn = N.new("ShaderNodeCombineXYZ")
    L.new(m("MULTIPLY_ADD", sp.outputs["X"], inv, ox), uvn.inputs["X"])
    L.new(m("MULTIPLY_ADD", sp.outputs["Y"], inv, oy), uvn.inputs["Y"])
    tex = N.new("ShaderNodeTexImage")
    tex.name = "mask"
    tex.image = _mask_image()
    tex.interpolation = "Linear"
    tex.extension = "REPEAT"
    L.new(uvn.outputs[0], tex.inputs["Vector"])
    sepc = N.new("ShaderNodeSeparateColor")
    L.new(tex.outputs["Color"], sepc.inputs[0])
    n = sepc.outputs[0]
    t = m("MULTIPLY_ADD", amount, -0.55, 1.0)
    # the sea (ocean.snow_line): no puddles nor film of rain under it or where its waves run (1.75.0: the puddles of the
    # rain showed through the sea, on the sand under it); snow does the same below
    s_on, s_lo, s_hi = val("s_on", 0.0), val("s_lo", 0.0), val("s_hi", 0.05)
    above_sea = m("SUBTRACT", 1.0, m("MULTIPLY", s_on, m("SUBTRACT", 1.0, smooth(s_lo, s_hi, sp.outputs["Z"]))))
    flat_up = m("MULTIPLY", m("MULTIPLY", m("MULTIPLY", smooth(0.9, 0.98, nz), gi.outputs["Puddles"]), open_up), above_sea)
    flat = m("MULTIPLY", flat_up, m("MINIMUM", m("MULTIPLY", amount, 50.0), 1.0))
    # the puddles painted by hand (paint_stroke): R = added, G = taken away; a painted puddle goes where it was
    # painted, also under a shelter (not on a «Sempre asciutto» object, nor on what does not face up)
    p_on, px0, py0, pinv = val("p_on", 0.0), val("p_x0", 0.0), val("p_y0", 0.0), val("p_inv", 1.0)
    uvp = N.new("ShaderNodeCombineXYZ")
    L.new(m("MULTIPLY", m("SUBTRACT", sp.outputs["X"], px0), pinv), uvp.inputs["X"])
    L.new(m("MULTIPLY", m("SUBTRACT", sp.outputs["Y"], py0), pinv), uvp.inputs["Y"])
    ptex = N.new("ShaderNodeTexImage")
    ptex.name = "paint"
    ptex.interpolation = "Linear"
    ptex.extension = "CLIP"
    L.new(uvp.outputs[0], ptex.inputs["Vector"])
    psep = N.new("ShaderNodeSeparateColor")
    L.new(ptex.outputs["Color"], psep.inputs[0])
    # B: the height of the surface that was painted (a puddle painted on the street does not go on the roof above)
    pz0, pzr = val("p_z0", 0.0), val("p_zr", 1.0)
    p_match = m("SUBTRACT", 1.0, smooth(0.4, 0.8, m("ABSOLUTE", m("SUBTRACT", sp.outputs["Z"], m("MULTIPLY_ADD", psep.outputs[2], pzr, pz0)))))
    p_on2 = m("MULTIPLY", p_on, p_match)
    p_add = m("MULTIPLY", psep.outputs[0], p_on2)
    p_rem = m("MULTIPLY", psep.outputs[1], p_on2)
    p_keep = m("SUBTRACT", 1.0, p_rem)
    flat_p = m("MULTIPLY", m("MULTIPLY", m("MULTIPLY", smooth(0.9, 0.98, nz), gi.outputs["Puddles"]), keep), above_sea)
    edge_p = m("MULTIPLY_ADD", val("psoft", 0.5), 0.43, 0.02)      # «Sfumatura pennello»: 0.02 .. 0.45
    pud = m("MAXIMUM", m("MULTIPLY", m("MULTIPLY", smooth(m("SUBTRACT", t, edge), m("ADD", t, edge), n), flat), p_keep),
            m("MULTIPLY", smooth(m("SUBTRACT", 0.5, edge_p), m("ADD", 0.5, edge_p), p_add), flat_p))
    halo = m("MAXIMUM", m("MULTIPLY", m("MULTIPLY", smooth(m("SUBTRACT", m("SUBTRACT", t, edge), 0.12), t, n), flat), p_keep),
             m("MULTIPLY", smooth(0.05, 0.5, p_add), flat_p))
    film = m("MULTIPLY", m("MULTIPLY", m("MULTIPLY", smooth(0.5, 1.0, wet), flat_up), 0.85), p_keep)
    unglass = m("SUBTRACT", 1.0, gi.outputs["Glass"])          # (glass, transparent plastic: only the drops)
    water = m("MULTIPLY", m("MAXIMUM", pud, film), unglass)
    w2 = m("MULTIPLY", m("MAXIMUM", m("MAXIMUM", w, halo), film), unglass)
    w2 = m("MINIMUM", m("MAXIMUM", w2, 0.0), 1.0)
    w2g = m("MULTIPLY", m("MAXIMUM", m("MAXIMUM", wg, halo), film), unglass)       # (the gloss: not under the sea)
    w2g = m("MINIMUM", m("MAXIMUM", w2g, 0.0), 1.0)
    por = m("MULTIPLY", smooth(0.2, 0.9, gi.outputs["Roughness"]), m("SUBTRACT", 1.0, gi.outputs["Metallic"]))
    dark = m("SUBTRACT", 1.0, m("MULTIPLY", m("MULTIPLY", w2, por), 0.6))
    deep = mix(1.0, m("MULTIPLY_ADD", look, 0.6, 0.15), pud)
    k = m("MULTIPLY", dark, deep)
    # (1.75.1) the caustics of the sea on what lies under it (Paesaggio > Oceano, with «Luce riflessa dall'acqua»): the
    # net of light the waves focus on the bed. Two layers of wavy cell edges (Voronoi, different sizes and angles: no
    # tile repeats), projected along the sun refracted into the water (the net moves with the depth, as the real one),
    # strongest in the first metre and gone by ~6 m (it blurs and the water takes the light). The bed gets darker
    # between the lines and brighter on them: about the same light on average
    k_on, k_inv, k_lvl = val("k_on", 0.0), val("k_inv", 2.0), val("k_lvl", 0.0)
    k_sx, k_sy, k_amt = val("k_sx", 0.0), val("k_sy", 0.0), val("k_amt", 1.0)
    dep = m("SUBTRACT", k_lvl, sp.outputs["Z"])
    kx = m("MULTIPLY", m("MULTIPLY_ADD", dep, k_sx, sp.outputs["X"]), k_inv)
    ky = m("MULTIPLY", m("MULTIPLY_ADD", dep, k_sy, sp.outputs["Y"]), k_inv)

    def caustic_layer(sc, ang, warp):
        ca, sa = __import__("math").cos(ang), __import__("math").sin(ang)
        u = m("MULTIPLY", m("SUBTRACT", m("MULTIPLY", kx, ca), m("MULTIPLY", ky, sa)), sc)
        v = m("MULTIPLY", m("ADD", m("MULTIPLY", kx, sa), m("MULTIPLY", ky, ca)), sc)
        cv = N.new("ShaderNodeCombineXYZ"); L.new(u, cv.inputs["X"]); L.new(v, cv.inputs["Y"])
        nz_ = N.new("ShaderNodeTexNoise"); nz_.noise_dimensions = "2D"
        nz_.inputs["Scale"].default_value = 0.6; nz_.inputs["Detail"].default_value = 1.0
        L.new(cv.outputs[0], nz_.inputs["Vector"])
        wv = N.new("ShaderNodeVectorMath"); wv.operation = "MULTIPLY_ADD"
        L.new(nz_.outputs["Color"], wv.inputs[0]); wv.inputs[1].default_value = (warp, warp, 0.0)
        L.new(cv.outputs[0], wv.inputs[2])
        vo = N.new("ShaderNodeTexVoronoi"); vo.voronoi_dimensions = "2D"; vo.feature = "DISTANCE_TO_EDGE"
        vo.inputs["Randomness"].default_value = 0.9
        L.new(wv.outputs[0], vo.inputs["Vector"])
        return m("SUBTRACT", 1.0, smooth(0.0, 0.09, vo.outputs["Distance"]))

    net = m("MAXIMUM", caustic_layer(1.0, 0.3, 0.45), m("MULTIPLY", caustic_layer(1.63, 1.9, 0.55), 0.8))
    k_depth = m("MULTIPLY", smooth(0.0, 0.08, dep), m("SUBTRACT", 1.0, smooth(0.8, 6.0, dep)))
    k_str = m("MULTIPLY", m("MULTIPLY", m("MULTIPLY", k_on, k_depth), k_amt), m("SUBTRACT", 1.0, gi.outputs["Glass"]))
    k = m("MULTIPLY", k, mix(1.0, m("MULTIPLY_ADD", net, 2.6, 0.55), k_str))
    col = N.new("ShaderNodeVectorMath")
    col.operation = "SCALE"
    L.new(gi.outputs["Base Color"], col.inputs[0])
    L.new(k, col.inputs["Scale"])
    # the snow (formulas at the top): on what faces up, patchy at its edges, never under a shelter
    snow, walls, ssoft = val("snow", 0.0), val("walls", 0.3), val("ssoft", 0.3)
    sox, soy = val("soffx", 0.0), val("soffy", 0.0)
    K = SNOW_NS

    def maptex(name, u, v):
        c = N.new("ShaderNodeCombineXYZ")
        L.new(u, c.inputs["X"]); L.new(v, c.inputs["Y"])
        t = N.new("ShaderNodeTexImage")
        t.name = name
        t.image = tex.image
        t.interpolation = "Linear"
        t.extension = "REPEAT"
        L.new(c.outputs[0], t.inputs["Vector"])
        sp_ = N.new("ShaderNodeSeparateColor")
        L.new(t.outputs["Color"], sp_.inputs[0])
        return sp_.outputs[0]
    X_, Y_ = sp.outputs["X"], sp.outputs["Y"]
    mid = maptex("snowmask2", m("MULTIPLY_ADD", X_, K["s_mid"], m("MULTIPLY_ADD", sox, 0.5, 0.71)),
                 m("MULTIPLY_ADD", Y_, K["s_mid"], m("MULTIPLY_ADD", soy, 0.5, 0.13)))
    a, b, c_, d = K["r2"]
    big = maptex("snowmask4", m("ADD", m("MULTIPLY", m("MULTIPLY_ADD", X_, a, m("MULTIPLY", Y_, b)), K["s_big"]), K["o_big"][0]),
                 m("ADD", m("MULTIPLY", m("MULTIPLY_ADD", X_, c_, m("MULTIPLY", Y_, d)), K["s_big"]), K["o_big"][1]))
    a, b, c_, d = K["r1"]
    wp = K["warp"]
    fu = m("ADD", m("MULTIPLY_ADD", m("MULTIPLY_ADD", X_, a, m("MULTIPLY", Y_, b)), 0.125, m("ADD", sox, 0.37)),
           m("MULTIPLY_ADD", mid, wp, -0.5 * wp))
    fv = m("ADD", m("MULTIPLY_ADD", m("MULTIPLY_ADD", X_, c_, m("MULTIPLY", Y_, d)), 0.125, m("ADD", soy, 0.61)),
           m("MULTIPLY_ADD", big, wp, -0.5 * wp))
    fine = maptex("snowmask", fu, fv)
    w0, w1, w2 = K["w"]
    nsum = m("MULTIPLY_ADD", fine, w0, m("MULTIPLY_ADD", mid, w1, m("MULTIPLY", big, w2)))
    nsv = m("MULTIPLY_ADD", m("SUBTRACT", nsum, 0.5), K["spread"], 0.5)
    # (v23, 1.76.12) the slope of the snow shaken by the same map at a third scale: on a coarse mesh (a terrain far
    # away, a point every 7 m) the line where the slope lets it hold followed the triangles - patches with straight
    # sides, crests «a dente di sega» (Luca); now ragged, inside the triangles too (snow.py, viewer.js: the same)
    uvs4 = N.new("ShaderNodeCombineXYZ")
    L.new(m("MULTIPLY_ADD", sp.outputs["X"], NZJ_SCALE, NZJ_OFF[0]), uvs4.inputs["X"])
    L.new(m("MULTIPLY_ADD", sp.outputs["Y"], NZJ_SCALE, NZJ_OFF[1]), uvs4.inputs["Y"])
    stx3 = N.new("ShaderNodeTexImage")
    stx3.name = "snowmask3"
    stx3.image = tex.image
    stx3.interpolation = "Linear"
    stx3.extension = "REPEAT"
    L.new(uvs4.outputs[0], stx3.inputs["Vector"])
    ssp3 = N.new("ShaderNodeSeparateColor")
    L.new(stx3.outputs["Color"], ssp3.inputs[0])
    nzs = m("ADD", nz, m("MULTIPLY_ADD", ssp3.outputs[0], NZJ_AMP, -0.5 * NZJ_AMP))
    ts = m("MULTIPLY_ADD", snow, -1.15, 1.0)
    es = m("MULTIPLY_ADD", ssoft, 0.3, 0.02)
    wlo = m("MULTIPLY_ADD", walls, -0.95, 0.75)
    S = m("MULTIPLY", smooth(m("SUBTRACT", ts, es), m("ADD", ts, es), nsv), smooth(wlo, m("ADD", wlo, 0.3), nzs))
    S = m("MULTIPLY", m("MULTIPLY", S, open_up_s), m("MINIMUM", m("MULTIPLY", snow, 50.0), 1.0))
    # the snow painted by hand (paint_stroke, layer snow): R = added, G = taken away, B = height of the surface; as
    # the painted puddles it goes where it was painted, also under a shelter (not on «Sempre asciutto»)
    q_on, qx0, qy0, qinv = val("q_on", 0.0), val("q_x0", 0.0), val("q_y0", 0.0), val("q_inv", 1.0)
    qz0, qzr = val("q_z0", 0.0), val("q_zr", 1.0)
    uvq = N.new("ShaderNodeCombineXYZ")
    L.new(m("MULTIPLY", m("SUBTRACT", sp.outputs["X"], qx0), qinv), uvq.inputs["X"])
    L.new(m("MULTIPLY", m("SUBTRACT", sp.outputs["Y"], qy0), qinv), uvq.inputs["Y"])
    qtex = N.new("ShaderNodeTexImage")
    qtex.name = "spaint"
    qtex.interpolation = "Linear"
    qtex.extension = "CLIP"
    L.new(uvq.outputs[0], qtex.inputs["Vector"])
    qsep = N.new("ShaderNodeSeparateColor")
    L.new(qtex.outputs["Color"], qsep.inputs[0])
    q_match = m("SUBTRACT", 1.0, smooth(0.4, 0.8, m("ABSOLUTE", m("SUBTRACT", sp.outputs["Z"], m("MULTIPLY_ADD", qsep.outputs[2], qzr, qz0)))))
    q_on2 = m("MULTIPLY", q_on, q_match)
    eq = m("MULTIPLY_ADD", val("qsoft", 0.5), 0.43, 0.02)
    q_add = smooth(m("SUBTRACT", 0.5, eq), m("ADD", 0.5, eq), m("MULTIPLY", qsep.outputs[0], q_on2))
    S = m("MAXIMUM", m("MULTIPLY", S, m("SUBTRACT", 1.0, m("MULTIPLY", qsep.outputs[1], q_on2))),
          m("MULTIPLY", m("MULTIPLY", q_add, smooth(wlo, m("ADD", wlo, 0.3), nzs)), keep_s))
    S = m("MULTIPLY", S, unglass)
    # the sea (ocean.snow_line): no snow under it nor where its waves run (snow.py does the same for the mantle)
    S = m("MULTIPLY", S, m("SUBTRACT", 1.0, m("MULTIPLY", s_on, m("SUBTRACT", 1.0, smooth(s_lo, s_hi, sp.outputs["Z"])))))
    # «Gocce sulle superfici» (formulas: _drops_nodes): the height of the drops lying on the surface, in metres
    drops_args = (N, L, m, smooth, val, gi, geo, sp, nz, open_wall, wet, unglass)
    ident = lambda socks, i: next(x for x in socks if x.identifier == i)      # (Mix: one socket per type, same names)
    # «Neve vecchia» (formulas at the top): stains and a duller white
    age = val("sage", 0.0)
    aged = aged_snow_nodes(N, L, m, smooth, sp.outputs["X"], sp.outputs["Y"], age,
                           m("SUBTRACT", 1.0, smooth(0.35, 0.95, S)), None, _mask_image())
    white = N.new("ShaderNodeMix")
    white.data_type = "RGBA"
    L.new(S, ident(white.inputs, "Factor_Float"))
    L.new(col.outputs["Vector"], ident(white.inputs, "A_Color"))
    L.new(aged, ident(white.inputs, "B_Color"))
    L.new(ident(white.outputs, "Result_Color"), go.inputs["Base Color"])
    nmix = N.new("ShaderNodeMix")
    nmix.data_type = "VECTOR"
    L.new(S, ident(nmix.inputs, "Factor_Float"))
    L.new(gi.outputs["Normal"], ident(nmix.inputs, "A_Vector"))
    L.new(geo.outputs["Normal"], ident(nmix.inputs, "B_Vector"))
    nrm = N.new("ShaderNodeVectorMath")
    nrm.operation = "NORMALIZE"
    L.new(ident(nmix.outputs, "Result_Vector"), nrm.inputs[0])
    # the drops: lenses of water over the surface - what is under a drop is seen through its dome (the surface's own
    # reflection bent by it), its coat of water takes the same shape; elsewhere nothing changes
    H, M, Nd = _drops_nodes(*drops_args, nrm.outputs["Vector"])
    L.new(Nd, go.inputs["Normal"])
    # the rings of the falling rain on the water of the puddles and of the sheet on the ground (the same as on the
    # water materials: ripples.py; «Cerchi nelle pozzanghere», 0 = none - and no cost)
    from . import ripples
    rg = N.new("ShaderNodeGroup"); rg.node_tree = ripples._group(); rg.name = "puddle_rings"
    L.new(val("rk", 0.0), rg.inputs["Rain"]); L.new(val("ramount", 0.0), rg.inputs["Amount"])
    rg.inputs["Size"].default_value = 0.35; rg.inputs["Strength"].default_value = 1.2
    L.new(gi.outputs["Coat Normal"], rg.inputs["NormalIn"])
    pn = N.new("ShaderNodeMix"); pn.data_type = "VECTOR"
    L.new(m("MULTIPLY", water, m("GREATER_THAN", m("MULTIPLY", val("rk2", 0.0), 1.0), 0.0)), ident(pn.inputs, "Factor_Float"))
    L.new(gi.outputs["Coat Normal"], ident(pn.inputs, "A_Vector"))
    L.new(rg.outputs["Normal"], ident(pn.inputs, "B_Vector"))
    cn = N.new("ShaderNodeMix"); cn.data_type = "VECTOR"
    L.new(M, ident(cn.inputs, "Factor_Float"))
    L.new(ident(pn.outputs, "Result_Vector"), ident(cn.inputs, "A_Vector"))
    L.new(Nd, ident(cn.inputs, "B_Vector"))
    L.new(ident(cn.outputs, "Result_Vector"), go.inputs["Coat Normal"])
    # a window made by transparency (Alpha 0.06: the usual glass of car models): the drops on it are water, not
    # transparent as the glass - there the surface is solid (only with a constant Alpha: never on cut-out leaves)
    L.new(m("MAXIMUM", gi.outputs["Alpha"], m("MULTIPLY", m("MULTIPLY", M, 0.9), gi.outputs["AlphaDrops"])), go.inputs["Alpha"])
    unS = m("SUBTRACT", 1.0, S)
    L.new(m("MULTIPLY", gi.outputs["Metallic"], unS), go.inputs["Metallic"])
    r = gi.outputs["Roughness"]
    L.new(mix(mix(r, m("MINIMUM", r, m("MULTIPLY_ADD", por, 0.2, 0.05)), w2g), m("MULTIPLY_ADD", age, -0.12, 0.55), S),
          go.inputs["Roughness"])
    # «Velo d'acqua»: on what is smooth and does not soak (paint, metal, plastic) a thin layer of water, as wet as it is
    film2 = m("MULTIPLY", m("MULTIPLY", m("MULTIPLY", val("bfilm", 0.0), w2g), m("SUBTRACT", 1.0, por)),
              m("SUBTRACT", 1.0, smooth(0.3, 0.6, gi.outputs["Roughness"])))
    wat = m("MAXIMUM", m("MAXIMUM", water, M), film2)
    L.new(m("MULTIPLY", m("MAXIMUM", gi.outputs["Coat Weight"], wat), unS), go.inputs["Coat Weight"])
    L.new(mix(gi.outputs["Coat Roughness"], 0.02, m("MINIMUM", m("MULTIPLY", wat, 20.0), 1.0)), go.inputs["Coat Roughness"])
    L.new(mix(gi.outputs["Coat IOR"], 1.33, m("MINIMUM", m("MULTIPLY", wat, 20.0), 1.0)), go.inputs["Coat IOR"])
    return g


def _drops_nodes(N, L, m, smooth, val, gi, geo, sp, nz, open_wall, wet, unglass, base_n):
    """«Gocce sulle superfici»: drops of water lying on the surfaces (no geometry). -> (height in metres, the normal
    bent by the drops). The normal is worked out from the shape of each drop (its slope), not by a Bump node: a bump
    computes the whole pattern three times (the render took twice as long; this way about a third more).
      cell      c = 6 mm + 24 mm x «Dimensione» (the biggest drops); sizes c and c/2 on what faces up, 0.6 c on the
                sides (the biggest as many as q x («Gocce grandi» + 0.3))
      up        cells over the world xy (Voronoi F1, randomness 1): in each a drop of radius (0.25 + 0.2 r) cells x
                (0.6 + 0.4 q), present when another random < its share; a dome h = 0.55 R sqrt(1 - e²), e = d / R;
                its slope -0.55 e / sqrt(1 - e²) (at most 2.7 at the rim), away from the centre
      sides     the same over (u, z / 1.5), u = the horizontal across the face: drops longer downwards; and the runs:
                strips along z, 4 c apart, wavy, in pieces, as many as «Rivoli»; the two blended by the slope of the
                face (smooth 0.55..0.85 of nz), none on what faces down
      where     not under a shelter, not on «Sempre asciutto», only while it is wet; per material «Con la pioggia»
                (Drops: 0 never, 1 auto = only on what is smooth (roughness under 0.35..0.65), 2 always); glass always
    q = «Quantità» (0: no drops, and no cost: their nodes are folded away by Cycles)."""
    q, bsize, bbig, briv = val("beads", 0.0), val("bsize", 0.5), val("bbig", 0.3), val("briv", 0.4)
    c = m("MULTIPLY_ADD", bsize, 0.024, 0.006)
    rad_k = m("MULTIPLY_ADD", q, 0.4, 0.6)

    def vec(x, y, z=None):
        v = N.new("ShaderNodeCombineXYZ")
        for k, a in zip("XYZ", (x, y, z)):
            if a is not None:
                if isinstance(a, (int, float)):
                    v.inputs[k].default_value = a
                else:
                    L.new(a, v.inputs[k])
        return v.outputs[0]

    def vm(op, a, b=None, scale=None):
        n = N.new("ShaderNodeVectorMath"); n.operation = op
        L.new(a, n.inputs[0])
        if b is not None:
            L.new(b, n.inputs[1])
        if scale is not None:
            if isinstance(scale, (int, float)):
                n.inputs["Scale"].default_value = scale
            else:
                L.new(scale, n.inputs["Scale"])
        return n.outputs["Value" if op in ("DOT_PRODUCT", "LENGTH") else "Vector"]

    def pick(h1, g1, h2, g2):
        """The higher of two drops, with its slope."""
        sel = m("GREATER_THAN", h1, h2)
        mx = N.new("ShaderNodeMix"); mx.data_type = "VECTOR"
        ident = lambda socks, i: next(x for x in socks if x.identifier == i)
        L.new(sel, ident(mx.inputs, "Factor_Float")); L.new(g2, ident(mx.inputs, "A_Vector")); L.new(g1, ident(mx.inputs, "B_Vector"))
        return m("MAXIMUM", h1, h2), ident(mx.outputs, "Result_Vector")

    def layer(X, Y, size, prob, sx=1.0, sy=1.0, off=(0.0, 0.0)):
        """A size of drops over (X, Y): (height, slope (d/dX, d/dY, 0))."""
        qx = m("ADD", m("DIVIDE", X, m("MULTIPLY", size, sx)), off[0])
        qy = m("ADD", m("DIVIDE", Y, m("MULTIPLY", size, sy)), off[1])
        vor = N.new("ShaderNodeTexVoronoi"); vor.voronoi_dimensions = "2D"; vor.feature = "F1"
        vor.inputs["Scale"].default_value = 1.0; vor.inputs["Randomness"].default_value = 1.0
        L.new(vec(qx, qy), vor.inputs["Vector"])
        rgb = N.new("ShaderNodeSeparateColor"); L.new(vor.outputs["Color"], rgb.inputs[0])
        fp = N.new("ShaderNodeSeparateXYZ"); L.new(vor.outputs["Position"], fp.inputs[0])
        d = vor.outputs["Distance"]
        on = m("LESS_THAN", rgb.outputs[2], prob)
        R = m("MULTIPLY", m("MULTIPLY_ADD", rgb.outputs[0], 0.2, 0.25), rad_k)
        e = m("DIVIDE", d, R)
        inside = m("LESS_THAN", e, 1.0)
        root = m("SQRT", m("MAXIMUM", m("SUBTRACT", 1.0, m("MULTIPLY", e, e)), 0.0))
        h = m("MULTIPLY", m("MULTIPLY", m("MULTIPLY", root, m("MULTIPLY", R, size)), 0.55), on)
        # slope along X, Y: -0.55 e / sqrt(1 - e²) x (q - feature) / d, per unit of X (q = X / (size sx))
        k = m("MULTIPLY", m("DIVIDE", m("MULTIPLY", e, -0.55), m("MAXIMUM", root, 0.2)), m("MULTIPLY", on, inside))
        k = m("DIVIDE", k, m("MAXIMUM", d, 1e-4))
        gx = m("DIVIDE", m("MULTIPLY", k, m("SUBTRACT", qx, fp.outputs["X"])), sx)
        gy = m("DIVIDE", m("MULTIPLY", k, m("SUBTRACT", qy, fp.outputs["Y"])), sy)
        return h, (gx, gy)
    X, Y, Z = sp.outputs["X"], sp.outputs["Y"], sp.outputs["Z"]
    # what faces up: over x, y
    h1, (gx1, gy1) = layer(X, Y, c, m("MULTIPLY", q, m("ADD", bbig, 0.3)))
    h2, (gx2, gy2) = layer(X, Y, m("MULTIPLY", c, 0.5), q, off=(13.1, 7.7))
    up, gup = pick(h1, vec(gx1, gy1, 0.0), h2, vec(gx2, gy2, 0.0))
    # the sides: u across the face (horizontal), z down it.
    # (v26, 17/11, Luca: the drops on the side of his cars «piuttosto irrealistiche», thin streaks and swirls) u was the
    # world position projected on the horizontal across the face, u = (nx y - ny x) / |n|: on a curved body the normal
    # turns, and with it the projection of the whole distance from the origin of the world - a car 40 m away, its side
    # curving over 2 m, had u running 20 times faster than the surface: drops squeezed into lines, swirling where the
    # normal wavers (the same body at the origin: round drops). Now u is the world x on what faces y and the world y on
    # what faces x (two layers of drops, each over its plane), blended over a narrow band at 45 degrees: u runs as the
    # surface does, wherever the model stands.
    sn = N.new("ShaderNodeSeparateXYZ"); L.new(geo.outputs["Normal"], sn.inputs[0])
    ax, ay = m("ABSOLUTE", sn.outputs["X"]), m("ABSOLUTE", sn.outputs["Y"])
    wy = smooth(0.42, 0.58, m("DIVIDE", ax, m("MAXIMUM", m("ADD", ax, ay), 1e-4)))    # (1: faces x, the drops over y, z)
    wx = m("SUBTRACT", 1.0, wy)
    hsx, (gux, gzx) = layer(X, Z, m("MULTIPLY", c, 0.6), q, 1.0, 1.5, (3.7, 11.3))
    hsy, (guy, gzy) = layer(Y, Z, m("MULTIPLY", c, 0.6), q, 1.0, 1.5, (9.2, 5.9))
    hs, gs_xy = pick(m("MULTIPLY", hsx, wx), vec(m("MULTIPLY", gux, wx), 0.0, m("MULTIPLY", gzx, wx)),
                     m("MULTIPLY", hsy, wy), vec(0.0, m("MULTIPLY", guy, wy), m("MULTIPLY", gzy, wy)))
    face_x = m("GREATER_THAN", wy, 0.5)
    U = m("ADD", m("MULTIPLY", X, m("SUBTRACT", 1.0, face_x)), m("MULTIPLY", Y, face_x))     # (the runs: one plane or the other)
    ux, uy = m("SUBTRACT", 1.0, face_x), face_x                                            # (dU/dx, dU/dy)
    # the runs: strips along z
    sr = m("MULTIPLY", c, 4.0)
    wv = N.new("ShaderNodeTexNoise"); wv.noise_dimensions = "2D"; wv.inputs["Scale"].default_value = 1.0
    L.new(vec(m("DIVIDE", U, m("MULTIPLY", sr, 6.0)), m("MULTIPLY", Z, 1.5)), wv.inputs["Vector"])
    xs = m("ADD", m("DIVIDE", U, sr), m("MULTIPLY", m("SUBTRACT", wv.outputs["Fac"], 0.5), 0.8))
    idx = m("FLOOR", xs)
    fr = m("SUBTRACT", m("FRACT", xs), 0.5)
    wn = N.new("ShaderNodeTexWhiteNoise"); wn.noise_dimensions = "1D"
    L.new(idx, wn.inputs["W"])
    seg = N.new("ShaderNodeTexNoise"); seg.noise_dimensions = "2D"; seg.inputs["Scale"].default_value = 1.0
    L.new(vec(m("MULTIPLY", idx, 3.1), m("MULTIPLY", Z, 4.0)), seg.inputs["Vector"])
    run_on = m("MULTIPLY", m("LESS_THAN", wn.outputs["Value"], m("MULTIPLY", briv, m("MULTIPLY", q, 0.7))),
               smooth(0.48, 0.56, seg.outputs["Fac"]))
    wr = 0.06
    ef = m("DIVIDE", fr, wr)
    rroot = m("SQRT", m("MAXIMUM", m("SUBTRACT", 1.0, m("MULTIPLY", ef, ef)), 0.0))
    run = m("MULTIPLY", m("MULTIPLY", rroot, m("MULTIPLY", sr, wr * 0.5)), run_on)
    grun = m("MULTIPLY", m("MULTIPLY", m("DIVIDE", m("MULTIPLY", ef, -0.5), m("MAXIMUM", rroot, 0.2)),
                         m("LESS_THAN", m("ABSOLUTE", ef), 1.0)), run_on)
    gside_s = gs_xy
    gside_r = vec(m("MULTIPLY", grun, ux), m("MULTIPLY", grun, uy), 0.0)
    side, gside = pick(hs, gside_s, run, gside_r)
    wall = m("SUBTRACT", 1.0, smooth(0.55, 0.85, sn.outputs["Z"]))
    H = m("ADD", m("MULTIPLY", up, m("SUBTRACT", 1.0, wall)), m("MULTIPLY", side, wall))
    G = vm("ADD", vm("SCALE", gup, scale=m("SUBTRACT", 1.0, wall)), vm("SCALE", gside, scale=wall))
    # where: open (half on walls under a shelter, as the wetness), not facing down, wet, and as the material says
    r = gi.outputs["Roughness"]
    mode = gi.outputs["Drops"]
    auto = m("MAXIMUM", m("SUBTRACT", 1.0, smooth(0.35, 0.65, r)), m("SUBTRACT", 1.0, unglass))
    f = m("ADD", m("GREATER_THAN", mode, 1.5),
          m("MULTIPLY", m("MULTIPLY", m("GREATER_THAN", mode, 0.5), m("LESS_THAN", mode, 1.5)), auto))
    where = m("MULTIPLY", m("MULTIPLY", f, smooth(0.3, 0.6, open_wall)), smooth(-0.35, -0.05, nz))
    where = m("MULTIPLY", m("MULTIPLY", where, m("GREATER_THAN", wet, 0.0)), m("GREATER_THAN", q, 0.0))
    H = m("MULTIPLY", H, where)                 # (off: 0, folded away by Cycles with all the drops' nodes)
    # (on glass the drops are steeper lenses: against a dark inside only their bent edges, catching the sky and the
    # lamps, show them - with the slope of a drop on paint the windows looked dry)
    clear_k = m("ADD", 1.0, m("MULTIPLY", m("MAXIMUM", gi.outputs["Glass"], m("SUBTRACT", 1.0, gi.outputs["Alpha"])), 1.5))
    G = vm("SCALE", G, scale=m("MULTIPLY", where, clear_k))
    # the normal: the slope taken off along the surface (the part of G across the face)
    Gt = vm("SUBTRACT", G, vm("SCALE", base_n, scale=vm("DOT_PRODUCT", G, base_n)))
    Nd = vm("NORMALIZE", vm("SUBTRACT", base_n, Gt))
    M = smooth(0.0, 0.0002, H)
    return H, M, Nd


AGED_COLOR = (0.80, 0.79, 0.76)              # «Neve vecchia»: the white gone dull
DIRT_COLOR = (0.42, 0.38, 0.33)              # and the stains


def aged_snow_nodes(N, L, m, smooth, X, Y, age, edge, pressed, image, base=None):
    """The colour of the snow with its age (formulas at the top): shader nodes in N, the colour socket. X, Y: world
    position; edge, pressed: sockets (pressed may be None); base: the colour of the fresh snow (a socket; None:
    SNOW_COLOR). Shared by the materials (here) and by the mantle (snow.py)."""
    ident = lambda socks, i: next(x for x in socks if x.identifier == i)
    stains = []
    for k, (sc, ox, oy) in enumerate(((0.31, 0.23, 0.87), (0.071, 0.55, 0.29))):
        uv = N.new("ShaderNodeCombineXYZ")
        L.new(m("MULTIPLY_ADD", X, sc, ox), uv.inputs["X"])
        L.new(m("MULTIPLY_ADD", Y, sc, oy), uv.inputs["Y"])
        tx = N.new("ShaderNodeTexImage")
        tx.name = f"agemask{k}"
        tx.image = image
        tx.interpolation = "Linear"
        tx.extension = "REPEAT"
        L.new(uv.outputs[0], tx.inputs["Vector"])
        sep = N.new("ShaderNodeSeparateColor")
        L.new(tx.outputs["Color"], sep.inputs[0])
        stains.append(sep.outputs[0])
    n2 = m("MULTIPLY_ADD", stains[0], 0.45, m("MULTIPLY", stains[1], 0.55))
    t0 = m("MULTIPLY_ADD", age, -0.55, 1.0)
    blot = smooth(t0, m("ADD", t0, 0.25), n2)
    d = m("MULTIPLY_ADD", blot, 0.75, m("MULTIPLY", edge, 0.5))
    if pressed is not None:
        d = m("MULTIPLY_ADD", pressed, 0.6, d)
    d = m("MULTIPLY", m("MINIMUM", d, 1.0), age)
    dull = N.new("ShaderNodeMix")
    dull.data_type = "RGBA"
    L.new(m("MULTIPLY", age, 0.6), ident(dull.inputs, "Factor_Float"))
    if base is None:
        ident(dull.inputs, "A_Color").default_value = SNOW_COLOR + (1.0,)
    else:
        L.new(base, ident(dull.inputs, "A_Color"))
    ident(dull.inputs, "B_Color").default_value = AGED_COLOR + (1.0,)
    dirt = N.new("ShaderNodeMix")
    dirt.data_type = "RGBA"
    L.new(m("MULTIPLY", d, 0.55), ident(dirt.inputs, "Factor_Float"))
    L.new(ident(dull.outputs, "Result_Color"), ident(dirt.inputs, "A_Color"))
    ident(dirt.inputs, "B_Color").default_value = DIRT_COLOR + (1.0,)
    return ident(dirt.outputs, "Result_Color")


def _inp(node, name):
    return next((s for s in node.inputs if s.name == name), None)


def _out(node, name):
    return next((s for s in node.outputs if s.name == name), None)


_SOCK = {"RGBA": "NodeSocketColor", "VALUE": "NodeSocketFloat", "VECTOR": "NodeSocketVector",
         "BOOLEAN": "NodeSocketBool", "INT": "NodeSocketInt"}
_RAIN = ("Base Color", "Roughness", "Metallic", "Coat Weight", "Coat Roughness", "Coat IOR", "Normal", "Coat Normal", "Alpha")
DROPS_KEY = "simpler_rain_drops"         # on a material: «Con la pioggia» auto | on | off (the drops lying on it)
DROPS_MODE = {"off": 0.0, "auto": 1.0, "on": 2.0}


def _bsdf_group(p):
    """A Principled with the same inputs as p, the rain between them (one group per kind of Principled)."""
    name = f"{BSDF_GROUP} {p.distribution} {p.subsurface_method}"
    g = bpy.data.node_groups.get(name)
    if g is not None:
        _color_output(g)
        return g
    g = bpy.data.node_groups.new(name, "ShaderNodeTree")
    for s in p.inputs:
        if s.type in _SOCK:
            g.interface.new_socket(s.name, in_out="INPUT", socket_type=_SOCK[s.type])
    g.interface.new_socket("simpler_puddles", in_out="INPUT", socket_type="NodeSocketFloat")
    g.interface.new_socket("simpler_drops", in_out="INPUT", socket_type="NodeSocketFloat")
    g.interface.new_socket("simpler_glass", in_out="INPUT", socket_type="NodeSocketFloat")
    g.interface.new_socket("simpler_alpha_drops", in_out="INPUT", socket_type="NodeSocketFloat")
    g.interface.new_socket("BSDF", in_out="OUTPUT", socket_type="NodeSocketShader")
    N, L = g.nodes, g.links
    gi, go = N.new("NodeGroupInput"), N.new("NodeGroupOutput")
    b = N.new("ShaderNodeBsdfPrincipled")
    b.distribution, b.subsurface_method = p.distribution, p.subsurface_method
    rain = N.new("ShaderNodeGroup")
    rain.node_tree = _math_group()
    # (by position: the inputs of the same kind of Principled come in the same order; some names, as "Weight",
    # cannot be looked up by key)
    ins = [i for i, s in enumerate(p.inputs) if s.type in _SOCK]
    for k, i in enumerate(ins):
        nm = p.inputs[i].name
        src = gi.outputs[k]
        if nm in _RAIN:
            L.new(src, _inp(rain, nm))
            src = _out(rain, nm)
        L.new(src, b.inputs[i])
    L.new(gi.outputs[len(ins)], _inp(rain, "Puddles"))
    L.new(gi.outputs[len(ins) + 1], _inp(rain, "Drops"))
    L.new(gi.outputs[len(ins) + 2], _inp(rain, "Glass"))
    L.new(gi.outputs[len(ins) + 3], _inp(rain, "AlphaDrops"))
    L.new(b.outputs[0], go.inputs["BSDF"])
    _color_output(g)
    return g


def _color_output(g):
    """(1.75.2) The colour after the rain as a second output: the light that refcaustics adds as an emission is
    seen with it (with the colour before the rain, the wet bottom under the sea got twice the light)."""
    if any(it.item_type == "SOCKET" and it.in_out == "OUTPUT" and it.name == "Color" for it in g.interface.items_tree):
        return
    g.interface.new_socket("Color", in_out="OUTPUT", socket_type="NodeSocketColor")
    b = next(n for n in g.nodes if n.type == "BSDF_PRINCIPLED")
    go = next(n for n in g.nodes if n.type == "GROUP_OUTPUT")
    bc = b.inputs["Base Color"]
    if bc.is_linked:
        g.links.new(bc.links[0].from_socket, go.inputs["Color"])
    else:
        go.inputs["Color"].default_value = bc.default_value


# ---------------------------------------------------------------- materials

def _source_output(nt):
    """The output the material has for every renderer (None: no output, or one of its own for Cycles only)."""
    outs = [n for n in nt.nodes if n.type == "OUTPUT_MATERIAL" and not n.name.startswith(PREFIX)]
    if any(n.target == "CYCLES" for n in outs):
        return None
    act = [n for n in outs if n.is_active_output]
    return act[0] if act else (outs[0] if outs else None)


def _linked(sock):
    if not sock.is_linked:
        return None
    lk = sock.links[0]
    return lk if (lk.is_valid and not lk.is_muted) else None


# Simpler's own wrappers around a Principled (glass shadows: refcaustics / glass.py): the rain goes through them - the
# glass of car models is wrapped so, and its drops were missing (1.66.0)
PASS_GROUPS = ("Simpler Glass Shadow", "Simpler Reflected Caustics")


def _path(node, depth=0):
    """The Principled at the end of a chain of Add / Mix shaders (or the node itself), else None."""
    if node is None or depth > 6:
        return None
    if node.type == "BSDF_PRINCIPLED":
        return node
    passing = node.type in ("ADD_SHADER", "MIX_SHADER", "REROUTE") or (
        node.type == "GROUP" and node.node_tree is not None and node.node_tree.name.startswith(PASS_GROUPS))
    if passing:
        for s in node.inputs:
            lk = _linked(s)
            if lk is not None:
                hit = _path(lk.from_node, depth + 1)
                if hit is not None:
                    return hit
    return None


def _val(v):
    try:
        return tuple(round(float(x), 6) for x in v)
    except TypeError:
        return round(float(v), 6) if not isinstance(v, bool) else bool(v)


def _sock_sig(s):
    lk = _linked(s)
    if lk is not None:
        return ("L", lk.from_node.name, lk.from_socket.identifier)
    return ("V", _val(s.default_value)) if hasattr(s, "default_value") else ("-",)


def _signature(out, bsdf, puddles):
    parts = [VERSION, out.name, puddles, bsdf.name, bsdf.distribution, bsdf.subsurface_method]
    seen = set()

    def walk(node):
        if node.name in seen:
            return
        seen.add(node.name)
        parts.append((node.name, node.type, tuple(_sock_sig(s) for s in node.inputs)))
        if node == bsdf:
            return
        for s in node.inputs:
            lk = _linked(s)
            if lk is not None and _path(lk.from_node) == bsdf:
                walk(lk.from_node)
    parts.append(tuple(_sock_sig(s) for s in out.inputs))
    lk = _linked(out.inputs["Surface"])
    walk(lk.from_node)
    return repr(parts)


def strip(mat):
    """The rain nodes taken out of a material."""
    nt = mat.node_tree if mat is not None else None
    if nt is None:
        return False
    ours = [n for n in nt.nodes if n.name.startswith(PREFIX)]
    for n in ours:
        nt.nodes.remove(n)
    if SIG in mat:
        del mat[SIG]
    return bool(ours)


def _copy_value(src, dst):
    try:
        dst.default_value = src.default_value
    except (AttributeError, TypeError, ValueError):
        pass


def _build(mat, out, bsdf, puddles, glass=False):
    nt = mat.node_tree
    strip(mat)
    N, L = nt.nodes, nt.links
    geo = None

    def geometry():
        nonlocal geo
        if geo is None:
            geo = N.new("ShaderNodeNewGeometry")
            geo.name = PREFIX + "_geo"
            geo.location = (bsdf.location.x - 300, bsdf.location.y - 900)
        return geo

    count = [0]

    def dup(node):
        """The output socket that stands for node in the Cycles chain."""
        if node == bsdf:
            gn = N.new("ShaderNodeGroup")
            gn.name = PREFIX + "_bsdf"
            gn.label = "Pioggia"
            gn.node_tree = _bsdf_group(bsdf)
            gn.location = (bsdf.location.x, bsdf.location.y - 700)
            ins = [s for s in bsdf.inputs if s.type in _SOCK]
            aniso = _inp(bsdf, "Anisotropic")
            for k, s in enumerate(ins):
                d = gn.inputs[k]
                lk = _linked(s)
                if lk is not None:
                    L.new(lk.from_socket, d)
                elif s.name in ("Normal", "Coat Normal"):
                    L.new(geometry().outputs["Normal"], d)
                elif s.name == "Tangent":
                    if aniso is not None and (aniso.is_linked or float(aniso.default_value) > 0):
                        L.new(geometry().outputs["Tangent"], d)
                else:
                    _copy_value(s, d)
            gn.inputs[len(ins)].default_value = 1.0 if puddles else 0.0
            gn.inputs[len(ins) + 1].default_value = DROPS_MODE.get(mat.get(DROPS_KEY) or "auto", 1.0)
            gn.inputs[len(ins) + 2].default_value = 1.0 if glass else 0.0
            al = _inp(bsdf, "Alpha")
            gn.inputs[len(ins) + 3].default_value = 1.0 if (al is not None and _linked(al) is None) else 0.0
            return gn.outputs[0]
        if node.type == "REROUTE":
            lk = _linked(node.inputs[0])
            return dup(lk.from_node)
        count[0] += 1
        c = N.new(node.bl_idname)
        if node.type == "GROUP":
            c.node_tree = node.node_tree
        c.name = f"{PREFIX}_mix{count[0]}"
        c.location = (node.location.x, node.location.y - 700)
        for i, s in enumerate(node.inputs):
            lk = _linked(s)
            if lk is None:
                _copy_value(s, c.inputs[i])
            elif _path(lk.from_node) == bsdf:
                L.new(dup(lk.from_node), c.inputs[i])
            else:
                L.new(lk.from_socket, c.inputs[i])
        if node.type == "GROUP" and node.node_tree is not None and node.node_tree.name.startswith(PASS_GROUPS[1]) \
                and c.inputs[0].is_linked:
            src = c.inputs[0].links[0].from_node
            col = _out(src, "Color") if src.type == "GROUP" else None
            if col is not None:
                L.new(col, c.inputs[1])          # (the reflected light seen with the wet colour)
        return c.outputs[0]

    o = N.new("ShaderNodeOutputMaterial")
    o.name = OUT
    o.label = "Pioggia (Cycles)"
    o.target = "CYCLES"
    o.location = (out.location.x, out.location.y - 700)
    for s in out.inputs:
        d = o.inputs.get(s.name)
        if d is None:
            continue
        if s.name == "Surface":
            L.new(dup(_linked(s).from_node), d)
            continue
        lk = _linked(s)
        if lk is not None:
            L.new(lk.from_socket, d)
        else:
            _copy_value(s, d)


def set_material_drops(d):
    """POST material/raindrops {name, mode: auto | on | off}: «Con la pioggia» - the drops lying on this material."""
    from .core import ApiError
    from .i18n import tr
    mat = bpy.data.materials.get(d.get("name") or "")
    if mat is None:
        raise ApiError(tr("Materiale non trovato"))
    mode = str(d.get("mode") or "auto")
    if mode not in DROPS_MODE:
        mode = "auto"
    if mode == "auto":
        if DROPS_KEY in mat:
            del mat[DROPS_KEY]
    else:
        mat[DROPS_KEY] = mode
    touch()
    return {"name": mat.name, "rainDrops": mode}


def _materials(glass_ok=False):
    """The materials to wet: those of the scene and of the models of distributions (drawn only as copies). Value:
    puddles allowed. glass_ok: also the transparent ones (glass, clear plastic: only the drops lying on them, «Gocce
    sulle superfici») - never the water (it has the rings of the rain, ripples.py), returned apart."""
    from . import paint, materials
    scene_mats, scatter_mats, decal_mats = set(), set(), set()
    kinds = ("MESH", "CURVE", "FONT", "META", "SURFACE")
    for ob in bpy.context.scene.objects:
        if ob.type not in kinds or ob.get("simpler_snow_mantle") or ob.get("simpler_snow_part") or ob.get("simpler_ocean"):
            continue                     # (the sea: its own surface, never wet - ocean.py)
        mod = ob.modifiers.get("Simpler Decal")
        decal = mod is not None
        for sl in ob.material_slots:
            if sl.material is not None:
                scene_mats.add(sl.material)
                if decal:
                    decal_mats.add(sl.material)
        # (a decal gets its material from its node tree, not from a slot: before, the rain and the snow never
        # reached the decals in the path tracing - road lines stayed dry and yellow over the snow)
        nd = mod.node_group.nodes.get("Material") if decal and mod.node_group is not None else None
        dm = nd.inputs["Material"].default_value if nd is not None and "Material" in nd.inputs else None
        if dm is not None:
            scene_mats.add(dm)
            decal_mats.add(dm)
    try:
        originals = paint.scatter_originals()
    except Exception:
        originals = []
    for ob in originals:
        for o in [ob] + list(getattr(ob, "children_recursive", [])):
            if o.type in kinds:
                for sl in o.material_slots:
                    if sl.material is not None:
                        scatter_mats.add(sl.material)
    out, glass = {}, set()
    for mat in scene_mats | scatter_mats:
        if not mat.use_nodes or mat.node_tree is None:
            continue
        if volumetric.is_on(mat):                   # (a volume has no surface to wet)
            continue
        try:
            if materials.is_transmissive(mat):
                from . import water
                if not glass_ok or water.is_water(mat) or mat.get(DROPS_KEY) == "off":
                    continue
                glass.add(mat)
        except Exception:
            pass
        out[mat] = mat in scene_mats
    return out, decal_mats, glass


DRY = {"wet": 0.0, "puddles": 0.0, "size": 0.5, "look": 0.3, "offX": 0.0, "offY": 0.0, "soft": 0.3, "paintSoft": 0.5,
       "outdoor": True, "snowing": False, "snow": 0.0, "walls": 0.3, "ssoft": 0.3, "soffX": 0.0, "soffY": 0.0,
       "spaintSoft": 0.5, "sdetail": 0.5, "sage": 0.0, "beads": 0.0, "bsize": 0.5, "bbig": 0.3, "briv": 0.4,
       "bfilm": 0.0, "rk": 0.0, "ramount": 0.5}       # (no rain: only the shore of the sea wet)


def _coast():
    from . import ocean
    return ocean.coast_band()


def update(s):
    """The settings of the rain into its group (called by ambience.apply); the materials follow before the next
    path-traced image (ensure)."""
    r = settings(s)
    band = _coast()
    from . import ocean
    line = ocean.snow_line()
    if r is None and band is None:
        return
    if r is None:
        r = dict(DRY)
    g = _math_group()
    vals = {"wet": r["wet"], "puddles": r["puddles"], "invsize": 1.0 / tile_size(r["size"]), "look": r["look"],
            "offx": r["offX"], "offy": r["offY"], "soft": r["soft"], "psoft": r["paintSoft"],
            "snow": r["snow"], "walls": r["walls"], "ssoft": r["ssoft"], "soffx": r["soffX"], "soffy": r["soffY"],
            "qsoft": r["spaintSoft"], "sage": r["sage"],
            "beads": 0.0 if r["snowing"] else r.get("beads", 0.0), "bsize": r.get("bsize", 0.5),
            "bbig": r.get("bbig", 0.3), "briv": r.get("briv", 0.4), "bfilm": 0.0 if r["snowing"] else r.get("bfilm", 0.5),
            "rk": 0.0 if r["snowing"] else r.get("rk", 0.0), "rk2": 0.0 if r["snowing"] else r.get("rk", 0.0) * (r.get("ramount", 0.0) > 0),
            "ramount": r.get("ramount", 0.5),
            "c_on": 1.0 if band else 0.0, "c_lo": band[0] if band else 0.0, "c_top": band[1] if band else 0.0, "c_soft": band[2] if band else 0.3,
            "s_on": 1.0 if line else 0.0, "s_lo": line[0] if line else 0.0, "s_hi": line[1] if line else 0.05}
    vals.update(ocean.caustic_values())      # (1.75.1: the caustics of the sea on the bed)
    changed = False
    for k, v in vals.items():
        n = g.nodes.get(k)
        if n is not None and abs(n.outputs[0].default_value - v) > 1e-7:
            n.outputs[0].default_value = v
            changed = True
    tex = g.nodes.get("mask")
    if tex is not None and tex.image is None:
        tex.image = _mask_image()
        changed = True
    from . import snow
    snow.set_age(r["sage"])                   # (the mantle's material: the same old snow)
    for nm in ("snowmask", "snowmask2", "snowmask3", "snowmask4", "agemask0", "agemask1"):
        st = g.nodes.get(nm)
        if st is not None and st.image is None:
            st.image = _mask_image()
            changed = True
    changed = _shelter_to_group(g, r if settings(s) is not None else None) or changed
    changed = _paint_to_group(g, r["snowing"]) or changed
    if changed:
        g.update_tag()
    from . import snow
    snow.touch()            # (the mantle follows the snow settings: made again in idle or before the next pass)


def ensure():
    """Before every path-traced image: the materials follow the rain (cheap when nothing changed)."""
    from . import ambience
    s = ambience.state()
    r = settings(s)
    from . import ocean
    try:
        ocean.idle_coast()        # (the coast of the sea as the objects are now)
    except Exception as exc:
        log(f"SIMPLER_OCEAN coast failed: {exc}")
    band = _coast()
    on = r is not None or band is not None
    if r is not None:
        shelter_update()          # (a path-traced image needs the shelter as the geometry is now)
    from . import snow
    from . import camview
    # the mantle of snow (snow.py), after the shelter it depends on (a final image: for its camera at once; the view
    # path tracing waits as the idle time does for the camera to stay still)
    final = camview.FRAME.get("aspect") is not None
    snow.BRUSH["full"] = final          # (1.78.4: a final image at the detail chosen, also with the snow brush on)
    try:
        if snow.update(wait=not final):
            refresh_info()
    finally:
        snow.BRUSH["full"] = False
    from . import snowfall
    if snowfall.due() and snowfall.update():     # the flakes that fall, for the camera of this image
        refresh_info()
    from . import raindrops
    try:
        # (the view's path tracing: the drops wait for the camera to stay still - the last ones stay meanwhile - and
        # for «Pausa ricalcoli»; a final image makes them for its camera at once)
        view = camview.FRAME.get("aspect") is None
        paused = view and is_paused() and not raindrops.F.get("dirty")      # (a change of the settings still shows)
        if not paused and raindrops.due(wait=view) and raindrops.update():
            refresh_info()
    except Exception as exc:                     # (drops that fail: the picture is made without them)
        log(f"SIMPLER_RAIN drops failed: {exc}")
    if INFO_STATE["changes"] != _STATE["changes"] or (on and INFO.get("shelter") is not SH["meta"]):
        refresh_info()
    beads_on = bool(r is not None and not r["snowing"] and r.get("beads", 0.0) > 0)
    key = (_STATE["changes"], _STATE["mats"], on, beads_on, len(bpy.data.materials), len(bpy.context.scene.objects), band, ocean.snow_line(),
           tuple(sorted((k, round(v, 4)) for k, v in ocean.caustic_values().items())))   # (sun, switch: the sea's caustics)
    if _STATE["key"] == key:
        return
    _STATE["key"] = key
    if not on:
        n = 0
        for mat in bpy.data.materials:
            if mat.node_tree is not None and mat.node_tree.nodes.get(OUT) is not None:
                n += strip(mat)
        if n:
            log(f"SIMPLER_RAIN off: {n} materials dry")
        return
    update(s)
    beads = r is not None and not r["snowing"] and r.get("beads", 0.0) > 0
    mats, decal_mats, glass_mats = _materials(beads)
    built = 0
    for mat, in_scene in mats.items():
        try:
            nt = mat.node_tree
            out = _source_output(nt)
            lk = _linked(out.inputs["Surface"]) if out is not None else None
            bsdf = _path(lk.from_node) if lk is not None else None
            if bsdf is None:
                if strip(mat):
                    built += 1
                continue
            puddles = in_scene and (mat in decal_mats or _linked(_inp(bsdf, "Alpha")) is None)
            glass = mat in glass_mats
            sig = _signature(out, bsdf, puddles) + repr((mat.get(DROPS_KEY) or "auto", glass))
            if mat.get(SIG) == sig and nt.nodes.get(OUT) is not None:
                continue
            _build(mat, out, bsdf, puddles, glass)
            mat[SIG] = sig
            built += 1
        except Exception as exc:                      # an unusual node graph: left dry
            strip(mat)
            log(f"SIMPLER_RAIN skip {mat.name}: {exc}")
    # materials no longer in the scene keep nothing of the rain
    for mat in bpy.data.materials:
        if mat not in mats and mat.node_tree is not None and mat.node_tree.nodes.get(OUT) is not None:
            strip(mat)
    if built:
        log(f"SIMPLER_RAIN {built} materials wet")


# ---------------------------------------------------------------- shelter: the scene seen from above
# For every cell of a grid over the scene (up to SHELTER_N x SHELTER_N, cells of at least SHELTER_CELL m), the
# highest point of the geometry: a point lower than that by more than SHELTER_LO (+ two cells, for slopes) is under
# something - a roof, a portico, a car, a tree - and the rain does not reach it. Made from points spread over the
# triangles (numpy, no render): the objects of the scene and, of the distributions, only the models taller than
# SHELTER_MIN_H (trees, cars: not grass). The ground (Suolo), decals, clouds and hidden objects do not count.
# Computed again only when the geometry changes (not for a material, a light or the camera), a moment after the
# last command (idle) or before a path-traced image. Saved as a 16-bit PNG (Cycles) and as half floats (real-time
# view), with the same numbers for both.

SHELTER_N = 2048
SHELTER_CELL = 0.05
SHELTER_LO = 0.1
SHELTER_MIN_H = 0.4
SHELTER_PTS_OBJ = 250000          # points at most per object / model
SHELTER_PTS_ALL = 20000000

SH = {"meta": None, "sig": None, "changes": -1, "dirty": True, "rev": 0}
_SAMPLES = {}


from . import tempdirs          # (23/11: files of another engine that is running are not removed, see tempdirs.removable)


def _shelter_dir():
    base = os.environ.get("LOCALAPPDATA") or os.path.expanduser("~")
    d = os.path.join(base, "Simpler", "rain")
    os.makedirs(d, exist_ok=True)
    return d


def _wanted(s=None):
    from . import ambience
    r = settings(s if s is not None else ambience.state())
    return r is not None and r["outdoor"]


def _no_shelter(ob):
    """«Non fa riparo» on the object or on a group above it (a moving car: the road under it stays wet)."""
    while ob is not None:
        if ob.get(OPEN_KEY):
            return True
        ob = ob.parent
    return False


def _scene_meshes(shelter=True):
    """The objects whose shape shelters (not the distributions: those come by their points). shelter False: also
    those with «Non fa riparo» (1.75.6: the snow mantle - a car that lets the rain reach the road still gets snow on
    its roof; before, «Non fa riparo» took the mantle away too)."""
    from .core import INTERNAL_KEY
    from .ambience import GROUND_KEY
    from . import paint
    out = []
    for ob in bpy.context.scene.objects:
        if ob.type != "MESH" or ob.get(INTERNAL_KEY) or ob.get("simpler_trashed") or ob.get(GROUND_KEY):
            continue
        if ob.hide_render or ob.get(paint.DATA_KEY) or ob.modifiers.get("Simpler Decal") is not None:
            continue
        if shelter and _no_shelter(ob):
            continue
        if volumetric.is_volume_object(ob):         # (fog, smoke, a cloud: no roof, no mantle)
            continue
        out.append(ob)
    return out


def _scatter_points():
    from . import paint
    return [ob for ob in bpy.context.scene.objects if ob.get(paint.DATA_KEY) and not ob.get("simpler_trashed")
            and not ob.hide_render and not _no_shelter(ob)]


def _geometry_sig(shelter=True):
    """shelter False: also the objects with «Non fa riparo» - they carry snow (the mantle): moving such a car must make
    the mantle again (1.75.12, Luca: the Qashqai moved, the final render had its snow where it was before)."""
    parts = []
    for ob in _scene_meshes(shelter) + _scatter_points():
        mw = ob.matrix_world
        parts.append((ob.name, ob.data.name if ob.data else "", len(ob.data.vertices) if ob.type == "MESH" else 0,
                      tuple(round(mw[r][c], 4) for r in range(3) for c in range(4))))
    return hash(tuple(parts))


def _up_dir(M):
    """The direction of the object's own space that ends up pointing up in the world (for the normals)."""
    import numpy as np
    try:
        q = np.linalg.inv(np.array(M, dtype=np.float64)[:3, :3])[:, 2]
    except np.linalg.LinAlgError:
        q = np.array([0.0, 0.0, 1.0])
    q = q / max(np.linalg.norm(q), 1e-12)
    return tuple(round(float(x), 3) for x in q)


def _samples(me, key, spacing, up=(0.0, 0.0, 1.0)):
    """Points spread over the triangles of a mesh (its own space), about one and a half per spacing² of surface seen
    from above (up: the world's up in the mesh's space) - walls get only their corners: they cover nothing but their
    own line, and the façades of a city were most of the points (the limit cut whole objects out: no shelter
    under the cars)."""
    import numpy as np
    k = (key, len(me.vertices), len(me.polygons), round(spacing, 4), up)
    got = _SAMPLES.get(k)
    if got is not None:
        return got
    if len(_SAMPLES) > 600:
        _SAMPLES.clear()
    nv = len(me.vertices)
    co = np.empty(nv * 3, dtype=np.float32)
    me.vertices.foreach_get("co", co)
    V = co.reshape(-1, 3)
    lt = me.loop_triangles
    nt = len(lt)
    if nt == 0:
        pts = V
    else:
        tri = np.empty(nt * 3, dtype=np.int32)
        lt.foreach_get("vertices", tri)
        T = tri.reshape(-1, 3)
        p0, p1, p2 = V[T[:, 0]], V[T[:, 1]], V[T[:, 2]]
        area = 0.5 * np.abs(np.cross(p1 - p0, p2 - p0) @ np.array(up, dtype=np.float32))
        cnt = area / max(spacing * spacing, 1e-8) * 1.5
        tot = float(cnt.sum())
        if tot > SHELTER_PTS_OBJ:
            cnt *= SHELTER_PTS_OBJ / tot
        rng = np.random.default_rng(nt)
        cnt = np.floor(cnt + rng.random(nt)).astype(np.int64)
        idx = np.repeat(np.arange(nt), cnt)
        r1 = np.sqrt(rng.random(len(idx), dtype=np.float32))[:, None]
        r2 = rng.random(len(idx), dtype=np.float32)[:, None]
        inner = p0[idx] * (1 - r1) + p1[idx] * (r1 * (1 - r2)) + p2[idx] * (r1 * r2)
        if nv > 60000:
            V = V[rng.choice(nv, 60000, replace=False)]
        pts = np.concatenate([V, inner.astype(np.float32)])
    _SAMPLES[k] = pts
    return pts


def _to_world(pts, M):
    import numpy as np
    return pts @ M[:3, :3].T.astype(np.float32) + M[:3, 3].astype(np.float32)


def shelter_map():
    """The map of the shelter (see above); None when the scene has nothing that shelters."""
    import numpy as np
    from . import paint
    t0 = time.time()
    dg = bpy.context.evaluated_depsgraph_get()
    obs = _scene_meshes()
    # the extent of the scene (without the ground: it is 4 km wide)
    lo_xy, hi_xy, zs = [], [], []
    for ob in obs:
        c = np.array([ob.matrix_world @ Vector(b) for b in ob.bound_box])
        lo_xy.append(c[:, :2].min(0)); hi_xy.append(c[:, :2].max(0)); zs += [c[:, 2].min(), c[:, 2].max()]
    scatter = []
    for po in _scatter_points():
        me = po.data
        n = len(me.vertices)
        if not n:
            continue
        xa, ma = me.attributes.get("simpler_xform"), me.attributes.get("simpler_model")
        group = po.parent
        coll = bpy.data.collections.get(group.get(paint.SCATTER_COLL) or "") if group is not None else None
        if xa is None or ma is None or coll is None:
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
                if o.type != "MESH" or o.hide_render:
                    continue
                oe = o.evaluated_get(dg)
                sc = max(o.matrix_world.to_scale())
                Mo = np.array(o.matrix_world, dtype=np.float32)
                parts.append(_to_world(_samples(oe.data, ("o", o.name) if o.modifiers else ("m", o.data.name), 0.15 / max(sc, 1e-6),
                                                _up_dir(Mo)), Mo))
            if not parts:
                continue
            P = np.concatenate(parts)
            sel = mi == k
            W = pm[None] @ xf[sel]                                       # instance -> world
            sz = np.linalg.norm(W[:, :3, 2], axis=1)
            h = (P[:, 2].max() - P[:, 2].min()) * sz
            W = W[h >= SHELTER_MIN_H]
            if not len(W):
                continue
            scatter.append((P, W))
            t = W[:, :3, 3]
            lo_xy.append(t[:, :2].min(0) - 3); hi_xy.append(t[:, :2].max(0) + 3); zs += [t[:, 2].min(), t[:, 2].max() + 30]
    if not lo_xy:
        return None
    x0, y0 = np.min(lo_xy, axis=0) - 1.0
    x1, y1 = np.max(hi_xy, axis=0) + 1.0
    size = float(max(x1 - x0, y1 - y0, 1.0))
    n = int(min(SHELTER_N, max(16, np.ceil(size / SHELTER_CELL))))
    cell = size / n
    H = np.full(n * n, -np.inf, dtype=np.float32)
    total = [0]

    def splat(P):
        if not len(P):
            return
        total[0] += len(P)
        ix = ((P[:, 0] - x0) / cell).astype(np.int64)
        iy = ((P[:, 1] - y0) / cell).astype(np.int64)
        ok = (ix >= 0) & (ix < n) & (iy >= 0) & (iy < n)
        np.maximum.at(H, iy[ok] * n + ix[ok], P[ok, 2])

    items = []
    from . import snow
    covers = {ob.name for ob in snow._covers()}
    for ob in obs:
        if ob.name in covers:
            continue                    # (below: by their exact surface)
        oe = ob.evaluated_get(dg)
        sc = max(ob.matrix_world.to_scale())
        key = ("o", ob.name) if ob.modifiers else ("m", ob.data.name)
        M = np.array(ob.matrix_world, dtype=np.float32)
        items.append((_samples(oe.data, key, cell / max(sc, 1e-6), _up_dir(M)), M))
    # over the limit every object gives fewer points, none is left out
    want = sum(len(P) for P, _M in items) + sum(len(P) * len(W) for P, W in scatter)
    keep = min(1.0, SHELTER_PTS_ALL / max(1, want))
    rng = np.random.default_rng(1)
    for P, M in items:
        if keep < 1.0 and len(P) > 64:
            P = P[rng.choice(len(P), max(64, int(len(P) * keep)), replace=False)]
        splat(_to_world(P, M))
    for P, W in scatter:
        budget = max(16, int(len(P) * keep))
        if len(P) > budget:
            P = P[rng.choice(len(P), budget, replace=False)]
        Ph = np.concatenate([P, np.ones((len(P), 1), np.float32)], axis=1)
        step = max(1, 4000000 // len(P))
        for a in range(0, len(W), step):
            splat((W[a:a + step] @ Ph.T).transpose(0, 2, 1)[..., :3].reshape(-1, 3))
    # what shelters without a mantle (the surface of water, a sheet of glass: snow.covers): a cell all under it is
    # sheltered however close the surface is (the map counts only what is well above: the rocks a few centimetres
    # under the water of a pool got the white of the snow); a cell where something comes out of it stays as it is
    if covers:
        Hc = snow._cover(float(x0), float(y0), n, n, cell)
        if Hc is not None:
            Hc = Hc.ravel()
            has = np.isfinite(Hc)
            under = has & ~(H > Hc + 0.02)
            H = np.where(under, Hc + (SHELTER_LO + 2.0 * cell) + 0.35, np.where(has, np.maximum(H, Hc), H)).astype(np.float32)
    real = np.isfinite(H)
    if not real.any():
        return None
    zmin, zmax = float(H[real].min()), float(H[real].max())
    zr = max(zmax - zmin, 0.01)
    v = np.zeros(n * n, dtype=np.float64)
    v[real] = np.clip((H[real] - zmin) / zr, 1.0 / 65535, 1.0)
    img = v.reshape(n, n)
    SH["rev"] += 1
    d = _shelter_dir()
    for f in os.listdir(d):
        if f.startswith("shelter_") and tempdirs.removable(f, "shelter_"):
            try:
                os.remove(os.path.join(d, f))
            except OSError:
                pass
    stem = f"shelter_{os.getpid()}_{SH['rev']}"
    png = os.path.join(d, stem + ".png")
    _png16(png, np.round(img[::-1] * 65535).astype(">u2"))         # (PNG rows from the top: max y first)
    with open(os.path.join(d, stem + ".bin"), "wb") as f:
        f.write(img.astype(np.float16).tobytes())                     # (rows from y0: as three.js reads them)
    meta = {"rev": SH["rev"], "file": stem, "x0": float(x0), "y0": float(y0), "size": size, "n": n, "cell": cell,
            "zmin": zmin, "zr": zr, "lo": SHELTER_LO + 2.0 * cell}
    log(f"SIMPLER_RAIN shelter {n}x{n} cell {cell * 100:.1f} cm, {total[0]} points, {time.time() - t0:.2f} s")
    return meta


def _png16(path, img):
    h, w = img.shape
    raw = b"".join(b"\x00" + img[y].tobytes() for y in range(h))

    def chunk(t, dd):
        return struct.pack(">I", len(dd)) + t + dd + struct.pack(">I", zlib.crc32(t + dd) & 0xFFFFFFFF)
    data = b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 16, 0, 0, 0, 0)) + \
        chunk(b"IDAT", zlib.compress(raw, 6)) + chunk(b"IEND", b"")
    with open(path, "wb") as f:
        f.write(data)


def _shelter_to_group(g, r):
    """The map (or none) into the rain group. True when something changed."""
    meta = SH["meta"] if (r is not None and r["outdoor"]) else None
    tex = g.nodes.get("shelter")
    if tex is None:
        return False
    extra = [g.nodes.get(f"shelter{k}") for k in range(1, len(SH_TAPS))]
    path = os.path.join(_shelter_dir(), meta["file"] + ".png") if meta else ""
    if meta and not os.path.isfile(path):
        meta, path = None, ""
    changed = False
    if meta:
        cur = tex.image
        if cur is None or bpy.path.abspath(cur.filepath) != path:
            im = bpy.data.images.load(path, check_existing=True)
            try:
                im.colorspace_settings.name = "Non-Color"
            except TypeError:
                pass
            im["simpler_noproxy"] = 1      # (1.75.38) a 16-bit map of heights: never a reduced copy
            tex.image = im
            for t_ in extra:
                if t_ is not None:
                    t_.image = im
            for t_ in [tex] + extra:       # (1.75.38) no stale «original» of a proxy left on the node
                if t_ is not None and t_.get("simpler_orig"):
                    del t_["simpler_orig"]
            if cur is not None and cur.users == 0:
                bpy.data.images.remove(cur)
            changed = True
        for t_ in extra:
            if t_ is not None and t_.image is not tex.image:
                t_.image = tex.image
                changed = True
        vals = {"sh_on": 1.0, "sh_x0": meta["x0"], "sh_y0": meta["y0"], "sh_inv": 1.0 / meta["size"],
                "sh_zmin": meta["zmin"], "sh_zr": meta["zr"], "sh_lo": meta["lo"]}
    else:
        vals = {"sh_on": 0.0}
    for k, v in vals.items():
        nd = g.nodes.get(k)
        if nd is not None and abs(nd.outputs[0].default_value - v) > 1e-9:
            nd.outputs[0].default_value = v
            changed = True
    return changed


def shelter_update(force=False):
    """The map made again if the geometry changed (force: now; else only when asked by idle). True if it changed."""
    from . import ambience
    s = ambience.state()
    if not _wanted(s):
        return False
    # (only when the geometry changed: a scene with nothing that shelters has no map, and asking again for it at
    # every pass started the path tracing again and again - stuck on «computing», 1.43.0-1.45.0)
    if SH["changes"] != _STATE["changes"] or SH["sig"] is None:
        SH["changes"] = _STATE["changes"]
        sig = _geometry_sig()
        if sig != SH["sig"]:
            SH["sig"], SH["dirty"] = sig, True
    if not SH["dirty"]:
        return False
    SH["dirty"] = False
    old = SH["meta"]
    try:
        SH["meta"] = shelter_map()
    except Exception as exc:
        log(f"SIMPLER_RAIN shelter failed: {exc}")
        SH["meta"] = None
    g = bpy.data.node_groups.get(GROUP)
    if g is not None and _shelter_to_group(g, settings(s)):
        g.update_tag()
    if old is not None or SH["meta"] is not None:     # (no map before and none now: nothing to draw again)
        from . import render
        render.invalidate()
    return True


IDLE = {"what": "Calcolo del riparo dalla pioggia"}


PAUSE = {"on": False}     # «Ferma i ricalcoli» (Alleggerisci): shelter, mantle and flakes not made again in the idle time
SMART = {"on": False}     # (1.75.9) «SmartView» (the orange button by the toolbar): the same wait, kept apart from PAUSE


def is_paused():
    """True while «Ferma i ricalcoli» or «SmartView» keeps the automatic computations waiting."""
    return PAUSE["on"] or SMART["on"]


def set_smart(d):
    """POST smartview {on}: SmartView - nothing of the view is computed again by itself (coast of the sea, shelter,
    mantle, flakes, drops; the app keeps the path tracing off). Inserting models, moving them and editing materials
    still work. Off: what changed meanwhile is made once."""
    from . import snow, snowfall
    on = bool(d.get("on"))
    if on != SMART["on"]:
        SMART["on"] = on
        if not on:
            SH["dirty"] = True
            snow.touch()
            snowfall.touch()
            __import__("simpler.raindrops", fromlist=["x"]).touch()
    log(f"SIMPLER_SMART {'on' if on else 'off'}")
    return {"on": SMART["on"]}


def set_pause(d):
    """POST rain/pause {on}: the rain's shelter, the snow mantle and the flakes wait (an image in path tracing still
    gets them right: ensure() before every pass); off, they are made again once for what changed meanwhile."""
    from . import snow, snowfall
    on = bool(d.get("on"))
    if on != PAUSE["on"]:
        PAUSE["on"] = on
        if not on:
            SH["dirty"] = True
            snow.touch()
            snowfall.touch()
            __import__("simpler.raindrops", fromlist=["x"]).touch()
    return {"on": PAUSE["on"]}


def idle_due(last_job):
    """True when idle() is about to compute the shelter or the mantle (for the «busy» sign; only flags, never reads
    Blender)."""
    from . import snow
    if time.time() - last_job < 0.6 or snow.HIDE["on"] or is_paused():
        return False            # (snow hidden, or «Ferma i ricalcoli»: the shelter waits too)
    from . import ocean
    if ocean.idle_due():
        IDLE["what"] = "Il mare segue l'inquadratura" if ocean.FOLLOW["due"] else "Calcolo della costa"
        return True
    if SH["dirty"] or SH["changes"] != _STATE["changes"]:
        IDLE["what"] = "Calcolo del riparo dalla pioggia"
        return True
    if snow.due():
        IDLE["what"] = "Calcolo del mantello di neve"
        return True
    from . import snowfall
    if snowfall.due():
        IDLE["what"] = "Calcolo dei fiocchi di neve"
        return True
    from . import raindrops
    if raindrops.due():
        IDLE["what"] = "Calcolo delle gocce di pioggia"
        return True
    return False


def idle(last_job):
    """From the engine's loop when there is nothing to do: the shelter follows the geometry, a moment after the last
    command (moving an object does not compute it at every step). Cheap when nothing changed: the ambience is not
    even read (this runs every 10 ms)."""
    if INFO_STATE["changes"] != _STATE["changes"]:
        refresh_info()
    if time.time() - last_job < 0.6:
        return False
    from . import snow
    if snow.HIDE["on"] or is_paused():
        return False
    from . import snowfall, raindrops, ocean
    try:
        if ocean.idle_follow():                 # (1.76.39: the fine part of the sea where the camera looks)
            refresh_info()
            return True
        if ocean.idle_coast():                  # (the coast of the sea follows the objects moved or edited)
            refresh_info()
            return True
    except Exception as exc:
        log(f"SIMPLER_OCEAN coast failed: {exc}")
    if SH["changes"] == _STATE["changes"] and not SH["dirty"] and not snow.due() and not snowfall.due() \
            and not raindrops.due():
        return False
    busy = False
    if not _wanted():
        # (1.73.9) and nothing left to do: «dirty» stayed set with the rain off, idle_due said «Calcolo del riparo»
        # for ever - the engine busy all the time, the sign on, a useless round every 10 ms
        SH["changes"] = _STATE["changes"]
        SH["dirty"] = False
    else:
        busy = shelter_update()
    if snow.update():
        busy = True
        from . import render
        render.invalidate()
    if snowfall.due() and snowfall.update():     # (the flakes: after the shelter they depend on)
        busy = True
        from . import render
        render.invalidate()
    try:
        if raindrops.due() and raindrops.update():   # (the drops and their splashes: after the shelter too)
            busy = True
            from . import render
            render.invalidate()
    except Exception as exc:
        log(f"SIMPLER_RAIN drops failed: {exc}")
    try:
        from . import ice
        ice.update()                            # (the frozen water: cheap when its map is made)
    except Exception as exc:
        log(f"SIMPLER_ICE failed: {exc}")
    try:
        from . import ripples
        if ripples.update():                    # (the rings of the rain: after the ice, cheap when nothing changed)
            from . import render
            render.invalidate()
    except Exception as exc:
        log(f"SIMPLER_RAIN rings failed: {exc}")
    refresh_info()
    return busy


def dry_ids():
    """The objects without rain."""
    from .core import ID_KEY
    return [ob.get(ID_KEY) for ob in bpy.context.scene.objects if rain_dry(ob) and ob.get(ID_KEY)]


def nosnow_ids():
    """The objects without snow."""
    from .core import ID_KEY
    return [ob.get(ID_KEY) for ob in bpy.context.scene.objects if snow_dry(ob) and ob.get(ID_KEY)]


INFO = {"shelter": None, "pending": False, "dry": [], "nosnow": []}
INFO_STATE = {"changes": -1}


def refresh_info():
    """What GET rain/info answers, made here on Blender's thread. The real-time view asks every 1.5 s while it rains:
    the answer comes from this copy straight from the HTTP thread, without going through the queue of commands -
    a command interrupts the path tracing pass, and those questions stopped every pass at 3/5 (1.43.0-1.43.3)."""
    global INFO
    from . import ambience, snow
    r = settings(ambience.state())
    meta = SH["meta"] if (r is not None and r["outdoor"]) else None
    INFO = {"shelter": meta, "pending": bool(r is not None and r["outdoor"] and (SH["dirty"] or SH["changes"] != _STATE["changes"])),
            "dry": dry_ids(), "nosnow": nosnow_ids(), "paint": _paint_info(), "snowPaint": _paint_info("snow"), "mantle": None if snow.HIDE["on"] else snow.M["meta"], "pressRev": snow.PRESS["rev"],
            "snowHidden": snow.HIDE["on"],
            "snowfall": None if snow.HIDE["on"] else __import__("simpler.snowfall", fromlist=["x"]).F["meta"], "snowMantle": bool((r is not None and snow.settings() is not None)
                                or __import__("simpler.snowfall", fromlist=["x"]).F.get("active")),
            "snowSculpt": __import__("simpler.snowsculpt", fromlist=["x"]).present(),
            "ice": __import__("simpler.ice", fromlist=["x"]).view_info(),
            "raindrops": __import__("simpler.raindrops", fromlist=["x"]).F["meta"],
            "rings": __import__("simpler.ripples", fromlist=["x"]).view_info(),
            "ocean": __import__("simpler.ocean", fromlist=["x"]).view_info()}
    INFO_STATE["changes"] = _STATE["changes"]


def info(_d=None):
    """GET rain/info (answered by the HTTP thread: only reads the copy)."""
    return dict(INFO, ok=True)


def shelter_file(name):
    name = os.path.basename(name or "")
    if not name.startswith("shelter_") or not name.endswith(".bin"):
        return ""
    p = os.path.join(_shelter_dir(), name)
    return p if os.path.isfile(p) else ""


def set_open(ids, value):
    """POST rain/noshelter {ids, value}: «Non fa riparo» on these objects and on the pieces inside them."""
    from .core import find, with_trees
    for o in with_trees([find(i) for i in ids]):     # (children_recursive per object: slow on big selections)
        if value:
            o[OPEN_KEY] = 1
        elif OPEN_KEY in o:
            del o[OPEN_KEY]
    if not value:
        for o in ancestors([find(i) for i in ids]):
            if OPEN_KEY in o:
                del o[OPEN_KEY]         # (its pieces keep their own: only the chosen one changes)
    touch()
    return {}


def ancestors(obs):
    """(1.75.4) The groups above these objects. A switch set on a whole model is written on the model AND on every
    piece; turned off on one piece, it stayed on the groups above, which still decided for that piece: «Senza
    mantello» off on the car paint, and still no snow on it. Turning off clears them too."""
    seen, out = set(), []
    for o in obs:
        p = o.parent if o is not None else None
        while p is not None:
            if p.name not in seen:
                seen.add(p.name); out.append(p)
            p = p.parent
    return out


def after_open():
    """A project just opened: the rain of its materials is taken away and made again before the first path-traced
    image, the shelter map computed again. The materials kept wet in the file showed some walls pink in the path
    tracing (an image Cycles could not read: magenta) until the rain was made again - always fine when made fresh
    in the session. Cheap: about a second for 200 materials."""
    n = 0
    for mat in bpy.data.materials:
        if mat.node_tree is not None and mat.node_tree.nodes.get(OUT) is not None:
            n += strip(mat)
    from . import ice
    ice.after_open()            # (the maps of the frozen water: made again - their images are not kept in the file)
    g = bpy.data.node_groups.get(GROUP)
    tex = g.nodes.get("shelter") if g is not None else None
    if tex is not None and tex.image is not None:
        old = tex.image
        tex.image = None
        for k_ in range(1, len(SH_TAPS)):
            t_ = g.nodes.get(f"shelter{k_}")
            if t_ is not None:
                t_.image = None
        if old.users == 0:
            bpy.data.images.remove(old)
    for k in ("sh_on",):
        nd = g.nodes.get(k) if g is not None else None
        if nd is not None:
            nd.outputs[0].default_value = 0.0
    SH.update(meta=None, sig=None, changes=-1, dirty=True)
    for P in PAINTS.values():
        P.update(arr=None, frame=None, filefor=None, file="")
    from . import snow
    snow.after_open()
    _STATE["key"] = None
    if n:
        log(f"SIMPLER_RAIN open: {n} materials made again")


def dry_undo_ids(ids):
    from .core import find, ID_KEY, with_trees
    obs = [find(i, required=False) for i in ids]
    # (the groups above too: turning a switch off clears it there - see ancestors - and undo must bring it back)
    return [o.get(ID_KEY) for o in list(with_trees(obs)) + ancestors([o for o in obs if o is not None]) if o.get(ID_KEY)]


def set_dry(ids, value, kind=None):
    """POST rain/dry {ids, value, kind}: «Sempre asciutto» on these objects and on the pieces inside them - kind
    "rain" (no rain), "snow" (no snow), none: both."""
    from .core import find, with_trees
    for o in with_trees([find(i) for i in ids]):     # (children_recursive per object: slow on big selections)
        r, sn = rain_dry(o), snow_dry(o)
        if kind in (None, "rain"):
            r = bool(value)
        if kind in (None, "snow"):
            sn = bool(value)
        set_dry_state(o, r, sn)
    if not value:
        for o in ancestors([find(i) for i in ids]):
            set_dry_state(o, False if kind in (None, "rain") else rain_dry(o),
                          False if kind in (None, "snow") else snow_dry(o))
    return {"dry": dry_ids(), "nosnow": nosnow_ids()}


# ---------------------------------------------------------------- puddles painted by hand
# A map seen from above, like the shelter: R = puddle added, G = puddle taken away (0..1), over a square of the
# scene (frame: x0, y0, size, n cells of at least PAINT_CELL m), made at the first stroke over the scene and grown
# when a stroke goes past it. It lives in the project: an image packed in the file and its frame on the world.
# Every stroke is one step of undo. The real-time view gets it as bytes (GET rain/paint.bin) and draws the strokes
# itself while the mouse moves, with the same brush (viewer.js puddleStamp).

PAINT_N = 2048
PAINT_CELL = 0.05
# two maps of the same kind: the puddles (rain) and the snow painted by hand (snow, Neve > Avanzate > Pennello neve)
LAYERS = {"rain": {"key": "simpler_rain_paint", "img": "Simpler Pioggia dipinto", "prefix": "paint_"},
          "snow": {"key": "simpler_snow_paint", "img": "Simpler Neve dipinta", "prefix": "spaint_"}}
PAINT_KEY, PAINT_IMG = LAYERS["rain"]["key"], LAYERS["rain"]["img"]
PAINTS = {k: {"arr": None, "frame": None, "rev": 0, "file": ""} for k in LAYERS}
PAINT = PAINTS["rain"]


def _layer(layer):
    return layer if layer in LAYERS else "rain"


def painted(layer="rain"):
    w = bpy.context.scene.world
    return bool(w is not None and w.get(LAYERS[_layer(layer)]["key"]))


def _paint_frame(layer="rain"):
    w = bpy.context.scene.world
    key = LAYERS[_layer(layer)]["key"]
    try:
        return json.loads(w[key]) if w is not None and w.get(key) else None
    except ValueError:
        return None


def _paint_array(layer="rain"):
    """The map as a float array (n, n, 3), read once from the image of the project."""
    import numpy as np
    layer = _layer(layer)
    P = PAINTS[layer]
    fr = _paint_frame(layer)
    if fr is None:
        P.update(arr=None, frame=None)
        return None
    if P["arr"] is not None and P["frame"] == fr:
        return P["arr"]
    im = bpy.data.images.get(LAYERS[layer]["img"])
    n = int(fr["n"])
    arr = np.zeros((n, n, 3), dtype=np.float32)
    if im is not None and im.size[0] == n and im.size[1] == n:
        px = np.empty(n * n * 4, dtype=np.float32)
        im.pixels.foreach_get(px)
        arr[:] = px.reshape(n, n, 4)[..., :3]
    P.update(arr=arr, frame=fr)
    return arr


def _paint_store(arr, fr, layer="rain"):
    """Array and frame into the project (packed image + world property), and to the shaders and the view."""
    import numpy as np
    layer = _layer(layer)
    P, L = PAINTS[layer], LAYERS[layer]
    n = int(fr["n"])
    im = bpy.data.images.get(L["img"])
    if im is None or im.size[0] != n or im.size[1] != n:
        if im is not None:
            bpy.data.images.remove(im)
        im = bpy.data.images.new(L["img"], n, n, alpha=False)
        try:
            im.colorspace_settings.name = "Non-Color"
        except TypeError:
            pass
    px = np.zeros((n, n, 4), dtype=np.float32)
    px[..., :3], px[..., 3] = arr, 1.0
    im.pixels.foreach_set(px.ravel())
    im.pack()
    im.use_fake_user = True
    im["simpler_noproxy"] = 1      # (1.75.51) painted puddles / snow: a map of data, never a reduced copy
    # (the path tracing keeps its images between passes - persistent data: without this tag it went on with the
    # old pixels, the strokes did not show until the project was opened again; 1.70.1)
    im.update_tag()
    P["rev"] += 1
    fr = dict(fr, rev=P["rev"])
    bpy.context.scene.world[L["key"]] = json.dumps(fr)
    P.update(arr=arr, frame=fr)
    _paint_bin(arr, fr, layer)
    P["filefor"] = json.dumps({k: fr.get(k) for k in ("x0", "y0", "size", "n", "z0", "zr")} | {"r": fr.get("rev")})
    g = bpy.data.node_groups.get(GROUP)
    if g is not None and _paint_to_group(g, _snowing()):
        g.update_tag()
    # (1.78.4, Luca: «snow brush… parte subito un'elaborazione con questo shelter rain») painted puddles or snow change
    # no shape: the shelter, the coast and the drops stay; the snow mantle follows its own painted map (snow.touch)
    touch(geometry=False)
    if layer == "snow":
        from . import snow
        snow.stroked()
        snow.touch()
    refresh_info()


def _paint_info(layer="rain"):
    """The painted map for the view: frame and the file of its bytes (made again after opening a project)."""
    layer = _layer(layer)
    P = PAINTS[layer]
    fr = _paint_frame(layer)
    if fr is None:
        return None
    key = json.dumps({k: fr.get(k) for k in ("x0", "y0", "size", "n", "z0", "zr")} | {"r": fr.get("rev")})
    if P.get("filefor") != key or not P.get("file"):
        arr = _paint_array(layer)
        if arr is None:
            return None
        P["rev"] += 1
        _paint_bin(arr, dict(fr, rev=P["rev"]), layer)
        P["filefor"] = key
    return {"rev": P["rev"], "file": P["file"], "x0": fr["x0"], "y0": fr["y0"], "size": fr["size"], "n": int(fr["n"]),
            "z0": fr.get("z0", 0.0), "zr": fr.get("zr", 1.0)}


def _paint_bin(arr, fr, layer="rain"):
    import numpy as np
    layer = _layer(layer)
    prefix = LAYERS[layer]["prefix"]
    d = _shelter_dir()
    for f in os.listdir(d):
        if f.startswith(prefix) and tempdirs.removable(f, prefix):
            try:
                os.remove(os.path.join(d, f))
            except OSError:
                pass
    stem = f"{prefix}{os.getpid()}_{fr['rev']}"
    with open(os.path.join(d, stem + ".bin"), "wb") as f:
        f.write(np.round(np.clip(arr, 0, 1) * 255).astype(np.uint8).tobytes())   # (rows from y0, RGB bytes)
    PAINTS[layer]["file"] = stem


def paint_file(name):
    name = os.path.basename(name or "")
    if not (name.startswith("paint_") or name.startswith("spaint_")) or not name.endswith(".bin"):
        return ""
    p = os.path.join(_shelter_dir(), name)
    return p if os.path.isfile(p) else ""


def _snowing():
    from . import ambience
    r = settings(ambience.state())
    return bool(r and r["snowing"])


def _paint_to_group(g, snowing=False):
    """The painted maps into the group: the puddles while it rains, the snow while it snows. True when changed."""
    changed = False
    for layer, tex_name, pre, on in (("rain", "paint", "p_", not snowing), ("snow", "spaint", "q_", snowing)):
        fr = _paint_frame(layer) if on else None
        tex = g.nodes.get(tex_name)
        if tex is None:
            continue
        im = bpy.data.images.get(LAYERS[layer]["img"]) if fr else None
        if im is not None and not im.get("simpler_noproxy"):
            im["simpler_noproxy"] = 1        # (1.75.51: older projects too - never a reduced copy)
        vals = {pre + "on": 1.0 if (fr and im is not None) else 0.0}
        if fr and im is not None:
            vals.update({pre + "x0": fr["x0"], pre + "y0": fr["y0"], pre + "inv": 1.0 / fr["size"],
                         pre + "z0": fr.get("z0", 0.0), pre + "zr": fr.get("zr", 1.0)})
        if tex.image != im:
            tex.image = im
            changed = True
        for k, v in vals.items():
            nd = g.nodes.get(k)
            if nd is not None and abs(nd.outputs[0].default_value - v) > 1e-9:
                nd.outputs[0].default_value = v
                changed = True
    return changed


def _scene_xyz():
    """The extent of the scene (without the ground): ([x, y, z] low, [x, y, z] high) or (None, None)."""
    from mathutils import Vector as V
    lo, hi = None, None
    for ob in _scene_meshes():
        for b in ob.bound_box:
            p = ob.matrix_world @ V(b)
            lo = [p.x, p.y, p.z] if lo is None else [min(lo[0], p.x), min(lo[1], p.y), min(lo[2], p.z)]
            hi = [p.x, p.y, p.z] if hi is None else [max(hi[0], p.x), max(hi[1], p.y), max(hi[2], p.z)]
    return lo, hi


def _frame_around(lo, hi):
    size = max(hi[0] - lo[0], hi[1] - lo[1], 2.0)
    n = int(min(PAINT_N, max(64, math.ceil(size / PAINT_CELL))))
    return {"x0": lo[0], "y0": lo[1], "size": size, "n": n, "z0": lo[2], "zr": max(hi[2] - lo[2], 1.0)}


def _smooth(e0, e1, x):
    import numpy as np
    t = np.clip((x - e0) / (e1 - e0), 0.0, 1.0)
    return t * t * (3 - 2 * t)


def paint_stroke(d):
    """POST rain/paint {points: [[x, y, z], ...] (metres, world: z = the surface painted), radius (m),
    mode: add | remove, strength 0..1, layer: rain | snow}."""
    import numpy as np
    layer = _layer(d.get("layer"))
    pts = [(float(p[0]), float(p[1]), float(p[2]) if len(p) > 2 else 0.0) for p in (d.get("points") or [])
           if isinstance(p, (list, tuple)) and len(p) >= 2]
    if not pts:
        return info()
    r = max(0.05, min(50.0, float(d.get("radius", 1.0))))
    add = (d.get("mode") or "add") != "remove"
    k = max(0.05, min(1.0, float(d.get("strength", 1.0))))
    arr, fr = _paint_array(layer), _paint_frame(layer)
    xs, ys, zs = [p[0] for p in pts], [p[1] for p in pts], [p[2] for p in pts]
    need_lo = [min(xs) - r - 1.0, min(ys) - r - 1.0, min(zs) - 1.0]
    need_hi = [max(xs) + r + 1.0, max(ys) + r + 1.0, max(zs) + 1.0]
    if fr is None or "z0" not in fr or need_lo[0] < fr["x0"] or need_lo[1] < fr["y0"] or need_hi[0] > fr["x0"] + fr["size"] \
            or need_hi[1] > fr["y0"] + fr["size"] or need_lo[2] < fr["z0"] or need_hi[2] > fr["z0"] + fr["zr"]:
        lo, hi = _scene_xyz()
        if fr is not None and "z0" in fr:
            flo, fhi = [fr["x0"], fr["y0"], fr["z0"]], [fr["x0"] + fr["size"], fr["y0"] + fr["size"], fr["z0"] + fr["zr"]]
            lo = [min(a, b) for a, b in zip(lo, flo)] if lo else flo
            hi = [max(a, b) for a, b in zip(hi, fhi)] if hi else fhi
        lo = [min(a, b) for a, b in zip(lo, need_lo)] if lo else need_lo
        hi = [max(a, b) for a, b in zip(hi, need_hi)] if hi else need_hi
        nf = _frame_around([lo[0] - 5.0, lo[1] - 5.0, lo[2] - 2.0], [hi[0] + 5.0, hi[1] + 5.0, hi[2] + 2.0])
        new = np.zeros((nf["n"], nf["n"], 3), dtype=np.float32)
        if arr is not None:                    # the old strokes into the new frame (nearest cell)
            c = (np.arange(nf["n"]) + 0.5) * nf["size"] / nf["n"]
            ox = ((nf["x0"] + c - fr["x0"]) / fr["size"] * fr["n"]).astype(np.int64)
            oy = ((nf["y0"] + c - fr["y0"]) / fr["size"] * fr["n"]).astype(np.int64)
            okx = (ox >= 0) & (ox < fr["n"])
            oky = (oy >= 0) & (oy < fr["n"])
            sub = arr[np.clip(oy, 0, fr["n"] - 1)][:, np.clip(ox, 0, fr["n"] - 1)].copy()
            if "z0" in fr:                     # (heights into the new range)
                sub[..., 2] = np.clip((fr["z0"] + sub[..., 2] * fr["zr"] - nf["z0"]) / nf["zr"], 0, 1)
            new[np.ix_(oky, okx)] = sub[np.ix_(oky, okx)]
        arr, fr = new, nf
    else:
        arr = arr.copy()
    n, cell = int(fr["n"]), fr["size"] / fr["n"]
    for (x, y, z) in pts:
        i0 = max(0, int((x - r - fr["x0"]) / cell)); i1 = min(n, int((x + r - fr["x0"]) / cell) + 2)
        j0 = max(0, int((y - r - fr["y0"]) / cell)); j1 = min(n, int((y + r - fr["y0"]) / cell) + 2)
        if i0 >= i1 or j0 >= j1:
            continue
        cx = fr["x0"] + (np.arange(i0, i1) + 0.5) * cell
        cy = fr["y0"] + (np.arange(j0, j1) + 0.5) * cell
        dist = np.sqrt((cx[None, :] - x) ** 2 + (cy[:, None] - y) ** 2) / r
        f = (k * (1.0 - _smooth(0.5, 1.0, dist))).astype(np.float32)
        a, g = arr[j0:j1, i0:i1, 0], arr[j0:j1, i0:i1, 1]
        hz = np.float32((z - fr["z0"]) / fr["zr"])
        arr[j0:j1, i0:i1, 2] = np.where(f > 0.02, hz, arr[j0:j1, i0:i1, 2])
        if add:
            arr[j0:j1, i0:i1, 0] = np.maximum(a, f)
            arr[j0:j1, i0:i1, 1] = g * (1.0 - f)
        else:
            arr[j0:j1, i0:i1, 1] = np.maximum(g, f)
            arr[j0:j1, i0:i1, 0] = a * (1.0 - f)
    _paint_store(arr, fr, layer)
    return info()


def paint_clear(d=None):
    """POST rain/paint/clear {layer}: the painted puddles (or the painted snow) all taken away."""
    layer = _layer((d or {}).get("layer"))
    L, P = LAYERS[layer], PAINTS[layer]
    w = bpy.context.scene.world
    if w is not None and L["key"] in w:
        del w[L["key"]]
    im = bpy.data.images.get(L["img"])
    if im is not None:
        bpy.data.images.remove(im)
    P.update(arr=None, frame=None)
    P["rev"] += 1
    P["file"] = ""
    g = bpy.data.node_groups.get(GROUP)
    if g is not None and _paint_to_group(g, _snowing()):
        g.update_tag()
    # (1.78.4, Luca: «snow brush… parte subito un'elaborazione con questo shelter rain») painted puddles or snow change
    # no shape: the shelter, the coast and the drops stay; the snow mantle follows its own painted map (snow.touch)
    touch(geometry=False)
    if layer == "snow":
        from . import snow
        snow.stroked()
        snow.touch()
    refresh_info()
    return info()


def paint_snapshot():
    """For undo: the frame and the map (compressed) of both layers."""
    import numpy as np
    out = {}
    for layer in LAYERS:
        fr = _paint_frame(layer)
        arr = _paint_array(layer)
        out[layer] = None if fr is None or arr is None else \
            {"frame": fr, "data": zlib.compress(np.round(np.clip(arr, 0, 1) * 255).astype(np.uint8).tobytes(), 6)}
    from . import snowsculpt
    out["sculpt"] = snowsculpt.snapshot()           # (the sculpted snow: the same step of undo)
    return out


def paint_restore(snap):
    import numpy as np
    if snap and "frame" in snap:                 # (a step made before the snow layer: the puddles only)
        snap = {"rain": snap, "snow": paint_snapshot()["snow"]}
    snap = snap or {}
    cur = paint_snapshot()                       # (a layer as it is stays: its map is not made again for nothing)
    for layer in LAYERS:
        one = snap.get(layer)
        if one == cur.get(layer):
            continue
        if not one:
            if painted(layer):
                paint_clear({"layer": layer})
            continue
        fr = one["frame"]
        n = int(fr["n"])
        arr = np.frombuffer(zlib.decompress(one["data"]), dtype=np.uint8).reshape(n, n, 3).astype(np.float32) / 255.0
        _paint_store(arr, {k: fr[k] for k in ("x0", "y0", "size", "n", "z0", "zr") if k in fr}, layer)
    if "sculpt" in snap and snap["sculpt"] != cur["sculpt"]:
        from . import snowsculpt
        snowsculpt.restore(snap["sculpt"])


def diag():
    """(1.75.18) One line for the log before a final render: the rain as the copy for the render will carry it (Luca: the
    final render without the wet road that the path tracing of the view had)."""
    g = bpy.data.node_groups.get(GROUP)
    if g is None:
        return "rain group: none"
    vals = {k: round(g.nodes[k].outputs[0].default_value, 3) for k in ("wet", "puddles", "sh_on") if g.nodes.get(k)}
    tex = g.nodes.get("shelter")
    im = tex.image if tex is not None else None
    path = bpy.path.abspath(im.filepath) if im is not None else ""
    wrapped = sum(1 for m in bpy.data.materials if m.node_tree is not None and m.node_tree.nodes.get(OUT) is not None)
    return (f"rain {vals}, shelter {im.name if im else None} {path} exists={os.path.isfile(path) if path else False} "
            f"size={tuple(im.size) if im else None}, wet materials {wrapped}")

