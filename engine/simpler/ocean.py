"""Oceano (Paesaggio): a real sea to the horizon, from Blender's Ocean modifier.

THE WAVES. Blender's Ocean modifier simulates the spectrum of a real sea (FFT of thousands of waves with the
lengths and speeds a wind of that strength makes, as in Tessendorf's method): Turbulent (Phillips), Established
(Pierson-Moskowitz), Established with sharp peaks (JONSWAP) and Shallow water (TMA). Everything it offers is here:
wind, choppiness of the crests, alignment and direction, damping, depth, fetch and sharp peaks, smallest wave,
random seed, time, foam (the mask where the crests break). The spray map is not used: it is only the data to emit
drops, nothing that shows.

THE HEIGHT. The modifier normalises its waves (measured: about 1 m whatever the wind; the wind changes their length
and shape): the height of the panel is the real significant height (4 × the standard deviation of the surface,
what sailors call «altezza d'onda»). It is measured once for each shape (_EVAL) and the wave scale set from it.

THE SURFACE. One object, kept out of the tree (as the clouds): a grid of its own in «Displace» mode, fine around the
scene (or the camera) and wider and wider towards the horizon (20 km: the edge never shows, even from a drone). Far
from the fine part, where the points are too far apart for the shorter waves, the waves fade into the flat sea
(a small Geometry Nodes step after the modifier: the points go back towards where they were, weight simpler_w).
The real-time view gets the grid as it is (one point a metre near the scene); the path tracing gets it subdivided
(Subdivision Simple, render levels) and a finer simulation (resolution).

THE WATER. A deep sea is not clear water: the light that comes back from it is the sky reflected (Fresnel, index
1.333) and a little scattered light from below, darker blue-green, brighter in the crests (thinner, lit from
behind). So the material is an opaque dielectric (no transmission: no noise, no depth needed under it), the colour
of the crests mixed in with the height, the foam (the mask of the modifier broken up by a noise) white and rough,
small ripples as a bump. The real-time view draws the same (viewer.js, OCEAN).

Performance: the simulation runs only when a setting changes; the height is measured only when the shape of the
waves changes; the grid is rebuilt only when its centre or density changes. The view gets positions and foam only
(the triangles only when the grid changed): GET ocean/mesh, answered from the HTTP thread.
"""
import hashlib
import json
import math
import uuid

import bpy

from .i18n import tr

OCEAN_KEY = "simpler_ocean"         # on the object
CFG_KEY = "simpler_ocean_cfg"       # its settings (JSON)
REV_KEY = "simpler_ocean_rev"       # changes at every change (the view fetches the surface again)
TOPO_KEY = "simpler_ocean_topo"     # on the mesh: the grid it holds
NAME = "Simpler Oceano"
MAT = "Simpler Oceano v11"    # (v11, 1.76.31: the map only where finer than the grid; v7, 1.76.21: the maps laid without repeating; v8, 1.76.22: the surf in lace; v9, 1.76.23: the clear water its own shader; v10, 1.76.26: the coast from its map)
SLOPE_IMG = "Simpler Oceano pendenze"   # the slopes of one tile of the waves (_slopes)
SLOPE_N = 256
DETAIL_IMG = "Simpler Oceano increspature"  # the short waves the simulation leaves out (_detail)
FADE_GROUP = "Simpler Oceano lontano"
MOD_SUB, MOD_OCEAN, MOD_FADE = "Simpler Oceano dettaglio", "Simpler Oceano", "Simpler Oceano lontano"
RADIUS = 20000.0                    # metres: the sea goes this far from the centre
EDGE_FAR = 200000.0                 # (1.73.8) then one last flat ring to here: from 20 km the gap between its edge and
                                    # the horizon showed the sky under the horizon - a dark line (0.03 deg from 10 m up)
GRID_VERSION = 2
GROWTH = 1.06                       # beyond the fine part each row of the grid is 6% wider than the one before

SPECTRA = {"turbulent": "PHILLIPS", "established": "PIERSON_MOSKOWITZ", "sharp": "JONSWAP", "shallow": "TEXEL_MARSEN_ARSLOE"}
SPECTRUM_NAMES = [("turbulent", "Agitato"), ("established", "Formato"), ("sharp", "Formato, creste a punta"), ("shallow", "Acqua bassa")]
# the colour of the water (linear RGB): what comes back from deep down, and from the thin crests lit from behind
COLORS = {
    "profondo": ((0.003, 0.012, 0.030), (0.010, 0.075, 0.100)),
    "mediterraneo": ((0.004, 0.025, 0.045), (0.020, 0.140, 0.160)),
    "tropicale": ((0.010, 0.075, 0.085), (0.050, 0.300, 0.280)),
    "nordico": ((0.006, 0.016, 0.020), (0.020, 0.060, 0.060)),
    "lago": ((0.008, 0.020, 0.014), (0.030, 0.070, 0.040)),
    "torbido": ((0.014, 0.022, 0.020), (0.050, 0.080, 0.070)),
}
COLOR_NAMES = [("profondo", "Oceano"), ("mediterraneo", "Mediterraneo"), ("tropicale", "Tropicale"),
               ("nordico", "Nordico"), ("lago", "Lago"), ("torbido", "Torbido")]
# clear shallow water (Costa): the depth (m) where it stops showing the bottom, and what 1 m of it lets through
CLARITY = {
    "profondo": (5.0, (0.55, 0.86, 0.93)),
    "mediterraneo": (6.0, (0.62, 0.90, 0.95)),
    "tropicale": (8.0, (0.70, 0.95, 0.93)),
    "nordico": (3.0, (0.55, 0.80, 0.80)),
    "lago": (2.0, (0.62, 0.76, 0.58)),
    "torbido": (1.0, (0.55, 0.62, 0.52)),
}
COAST_DMAX = 30.0                   # depth measured down to (m): deeper is open sea
COAST_CMAX = 12.0                   # distance from the shore measured up to (m)
BREAK = 0.78                        # a wave breaks when it is 0.78 times the depth (McCowan)
LAND_MAX = 2.0                      # height of the land over the sea kept (m): the edge of the water fades into it
def _edge(H):
    """The water thinner than this (m) fades out: no sharp edge on the shore. Wide enough to hide where the surface
    meets a bumpy shore (a sand with displacement: the bottom is measured without it)."""
    return 0.25 + 0.5 * H
# view spacing (m), render subdivision levels, highest simulation resolution (Blender: resolution² cells a side)
DETAIL = {"bassa": (1.5, 1, 16), "media": (1.0, 1, 24), "alta": (0.75, 2, 32)}

DEFAULTS = {
    "preset": "mosso", "level": 0.0, "height": 1.2, "wind": 10.0, "chop": 1.2, "direction": 0.0, "foam": 0.35,
    "color": "mediterraneo", "seed": 0,
    # Avanzate
    "spectrum": "turbulent", "align": 0.0, "smallest": 0.01, "damping": 0.5, "depth": 200.0, "fetch": 100.0,
    "sharpen": 0.0, "time": 1.0, "ripples": 0.35, "detail": "media", "center": "camera",
    # Costa (the sea near what it touches: beaches, rocks, piers)
    "coast": True, "coastFoam": 1.0, "shallow": True, "clarity": 1.0, "wetBand": 1.0,
    # (1.76.33, Luca: «il bordo che tocca l'acqua è troppo netto») how much the water moves against what it touches
    "edgeMove": 1.0,
    # (1.76.16) with a terrain in the scene the sea is at its foot (follow_terrain) until «Livello del mare» is moved
    "levelAuto": True,
}
ALIGN_MIN = 0.25                    # (1.76.37) the waves always follow the wind a little: «Direzione» always counts
MAIN_KEYS = ("level", "height", "wind", "chop", "direction", "foam", "color", "seed")
ADV_KEYS = ("spectrum", "align", "smallest", "damping", "depth", "fetch", "sharpen", "time", "ripples", "detail", "center")
COAST_KEYS = ("coast", "coastFoam", "shallow", "clarity", "wetBand", "edgeMove")
COAST_ADV = ("clarity", "wetBand", "edgeMove")
PRESETS = [
    ("calmo", "Calmo", {"height": 0.15, "wind": 3.0, "chop": 0.5, "foam": 0.0, "spectrum": "established", "align": 0.3, "ripples": 0.25, "color": "mediterraneo"}),
    ("brezza", "Brezza", {"height": 0.45, "wind": 6.0, "chop": 0.9, "foam": 0.12, "spectrum": "turbulent", "align": 0.2, "ripples": 0.35, "color": "mediterraneo"}),
    ("mosso", "Mosso", {"height": 1.2, "wind": 10.0, "chop": 1.2, "foam": 0.35, "spectrum": "turbulent", "align": 0.0, "ripples": 0.35, "color": "mediterraneo"}),
    ("burrasca", "Burrasca", {"height": 3.5, "wind": 18.0, "chop": 1.6, "foam": 0.8, "spectrum": "turbulent", "align": 0.4, "ripples": 0.5, "color": "torbido"}),
    ("lunga", "Onda lunga", {"height": 1.6, "wind": 14.0, "chop": 0.8, "foam": 0.08, "spectrum": "sharp", "align": 0.85, "fetch": 300.0, "sharpen": 0.5, "ripples": 0.3, "color": "profondo"}),
    ("tropicale", "Tropicale", {"height": 0.35, "wind": 5.0, "chop": 0.8, "foam": 0.04, "spectrum": "established", "align": 0.3, "ripples": 0.3, "color": "tropicale"}),
    ("nordico", "Nordico", {"height": 2.0, "wind": 13.0, "chop": 1.3, "foam": 0.45, "spectrum": "turbulent", "align": 0.2, "ripples": 0.45, "color": "nordico"}),
    ("lago", "Lago", {"height": 0.12, "wind": 4.0, "chop": 0.6, "foam": 0.0, "spectrum": "shallow", "depth": 6.0, "fetch": 2.0, "align": 0.1, "ripples": 0.3, "color": "lago"}),
]

# the surface for the real-time view (built on Blender's thread, sent from the HTTP thread)
_BIN = {"rev": "", "topo": "", "pos": b"", "data": b"", "idx": b"", "n": 0}


# ---------------------------------------------------------------- settings

def _find():
    for ob in bpy.context.scene.objects:
        if ob.get(OCEAN_KEY) and not ob.get("simpler_trashed"):
            return ob
    return None


def present():
    return _find() is not None


def settings(ob=None):
    s = dict(DEFAULTS)
    ob = ob if ob is not None else _find()
    if ob is not None:
        try:
            raw = json.loads(ob.get(CFG_KEY, "{}"))
            s.update(raw)
            if "levelAuto" not in raw:
                s["levelAuto"] = False            # (a sea made before 1.76.16: its level as it was set)
        except (TypeError, ValueError):
            pass
    return _clean(s)


def _clean(s):
    def f(k, lo, hi):
        try:
            v = float(s.get(k, DEFAULTS[k]))
        except (TypeError, ValueError):
            v = DEFAULTS[k]
        s[k] = max(lo, min(hi, v if math.isfinite(v) else DEFAULTS[k]))
    f("level", -500.0, 500.0); f("height", 0.0, 15.0); f("wind", 0.5, 40.0); f("chop", 0.0, 2.0)
    f("direction", -360.0, 720.0); f("foam", 0.0, 1.0); f("align", 0.0, 1.0); f("smallest", 0.001, 2.0)
    f("damping", 0.0, 1.0); f("depth", 0.5, 250.0); f("fetch", 0.05, 1000.0); f("sharpen", 0.0, 1.0)
    f("time", 0.0, 10000.0); f("ripples", 0.0, 1.0)
    f("coastFoam", 0.0, 2.0); f("clarity", 0.1, 4.0); f("wetBand", 0.0, 3.0); f("edgeMove", 0.0, 3.0)
    s["coast"] = bool(s.get("coast", True)); s["shallow"] = bool(s.get("shallow", True))
    s["levelAuto"] = bool(s.get("levelAuto", True))
    s["direction"] %= 360.0
    s["seed"] = int(max(0, min(10000, int(s.get("seed", 0) or 0))))
    if s.get("spectrum") not in SPECTRA:
        s["spectrum"] = DEFAULTS["spectrum"]
    if s.get("color") not in COLORS:
        s["color"] = DEFAULTS["color"]
    if s.get("detail") not in DETAIL:
        s["detail"] = DEFAULTS["detail"]
    if s.get("center") not in ("scena", "camera"):
        s["center"] = "scena"
    return s


def _preset(pid):
    for p in PRESETS:
        if p[0] == pid:
            return p[2]
    return None


def adv_changed(s):
    """An Avanzate setting differs from what the preset (or, without one, the defaults) gives it."""
    base = dict(DEFAULTS)
    base.update(_preset(s.get("preset")) or {})
    for k in ADV_KEYS:
        a, b = s.get(k), base.get(k)
        if isinstance(b, float):
            if abs(float(a) - b) > 1e-6:
                return True
        elif a != b:
            return True
    return False


# ---------------------------------------------------------------- the grid

def _axis(d0, r0, R):
    import numpy as np
    xs = [0.0]
    while xs[-1] < r0 - 1e-9:
        xs.append(xs[-1] + d0)
    d = d0
    while xs[-1] < R:
        # (1.73.8) past 100 x d0 the waves are long gone from the geometry (they live in the map of the slopes): the
        # rows widen fast there - fewer points than the round grid of before, even with the ring to 200 km
        d *= GROWTH if d < 100.0 * d0 else 1.35
        xs.append(min(R, xs[-1] + d))
    xs = np.array(xs)
    return np.concatenate([-xs[:0:-1], xs])


def _scene_box():
    from .ambience import _scene_box as box
    lo, hi = box()
    return lo, hi


def _look(s):
    """(1.76.39) Where the fine part of the sea goes in «Segue l'inquadratura»: from the camera towards the point it
    looks at, as far as half the fine part (what is in front, near, has the true waves). (cx, cy, r0) or None."""
    try:
        from .render import camera_view, CM
        v = camera_view()
    except Exception:  # noqa: BLE001
        return None
    px, py, pz = (float(x) * CM for x in v["position"])
    tx, ty, _tz = (float(x) * CM for x in v["target"])
    r0 = max(60.0, min(500.0, 80.0 + 2.0 * abs(pz - s["level"])))        # (higher camera: the waves it sees are farther)
    dx, dy = tx - px, ty - py
    dl = math.hypot(dx, dy)
    k = min(dl, 0.5 * r0) / dl if dl > 1e-6 else 0.0
    return px + dx * k, py + dy * k, r0


def _layout(s):
    """Centre, half side of the fine part and spacing of its points."""
    lo, hi = _scene_box()
    look = _look(s) if s["center"] == "camera" else None
    if look is not None:
        cx, cy, r0 = look
    else:
        cx, cy = float(lo.x + hi.x) / 2.0, float(lo.y + hi.y) / 2.0
        r0 = 0.6 * math.hypot(float(hi.x - lo.x), float(hi.y - lo.y)) + 40.0
    r0 = max(60.0, min(500.0, r0))
    d0 = max(DETAIL[s["detail"]][0], r0 / 200.0)               # (the view keeps ~200 000-300 000 points)
    # (rounded: a small change of the scene does not make another grid)
    q = max(d0, 5.0)
    cx, cy = round(cx / q) * q, round(cy / q) * q
    r0 = math.ceil(r0 / 20.0) * 20.0
    d0 = round(d0, 2)
    return cx, cy, r0, d0


def _peak(s):
    """The length of the longest waves that count (m): the peak of the spectrum for that wind (and fetch)."""
    g, V = 9.81, s["wind"]
    if s["spectrum"] in ("sharp", "shallow"):
        F = s["fetch"] * 1000.0
        wp = 22.0 * (g * g / (V * F)) ** (1.0 / 3.0)
        lam = 2.0 * math.pi * g / (wp * wp)
    else:
        lam = 2.0 * math.pi * V * V / (0.877 ** 2 * g)
    return max(1.0, lam)


def _spatial(s):
    return int(max(80, min(512, round(2.5 * _peak(s)))))


def _build_grid(me, cx, cy, r0, d0):
    import numpy as np
    ax = _axis(d0, r0, RADIUS)
    ax = np.concatenate([[-EDGE_FAR], ax, [EDGE_FAR]])
    n = len(ax)
    X, Y = np.meshgrid(ax, ax, indexing="ij")
    co = np.stack([X.ravel() + cx, Y.ravel() + cy, np.zeros(n * n)], axis=1).astype(np.float32)
    i = np.arange((n - 1) * (n - 1))
    r, c = i // (n - 1), i % (n - 1)
    a = r * n + c
    quads = np.stack([a, a + n, a + n + 1, a + 1], axis=1)
    # (square: the ring to EDGE_FAR makes the horizon the same in every direction - before, a round grid did)
    used = np.zeros(n * n, bool)
    used[quads.ravel()] = True
    remap = np.cumsum(used) - 1
    co = co[used]
    quads = remap[quads].astype(np.int32)
    # the spacing at each point: the wider of the two rows that meet there
    dx = np.diff(ax)
    sp = np.maximum(np.concatenate([dx[:1], dx]), np.concatenate([dx, dx[-1:]]))
    spacing = np.maximum(sp[:, None], sp[None, :]).ravel()[used].astype(np.float32)
    me.clear_geometry()
    me.vertices.add(len(co))
    me.vertices.foreach_set("co", co.ravel())
    me.loops.add(quads.size)
    me.loops.foreach_set("vertex_index", quads.ravel())
    me.polygons.add(len(quads))
    me.polygons.foreach_set("loop_start", np.arange(0, quads.size, 4, dtype=np.int32))
    me.update(calc_edges=True)
    if "sharp_face" in me.attributes:
        me.attributes.remove(me.attributes["sharp_face"])
    rest = me.attributes.new("simpler_rest", "FLOAT_VECTOR", "POINT")
    rest.data.foreach_set("vector", co.ravel())
    sa = me.attributes.new("simpler_spacing", "FLOAT", "POINT")
    sa.data.foreach_set("value", spacing)
    for name in ("simpler_w", "simpler_cfoam", "simpler_depth", "simpler_shore"):
        me.attributes.new(name, "FLOAT", "POINT")


def _smooth(e0, e1, x):
    import numpy as np
    t = np.clip((x - e0) / max(1e-9, e1 - e0), 0.0, 1.0)
    return t * t * (3.0 - 2.0 * t)


def _write(me, name, v):
    """An attribute of the grid written only when it changes (a write is a new surface for Cycles). True if
    written."""
    import numpy as np
    a = me.attributes[name]
    cur = np.empty(len(a.data), np.float32)
    a.data.foreach_get("value", cur)
    if np.allclose(cur, v, atol=1e-4):
        return False
    a.data.foreach_set("value", v.astype(np.float32))
    return True


def _weights(me, s, d0):
    """Per point of the grid (numpy): the weight of the waves (far fade × what the depth allows), the foam of the
    coast, the depth and the distance from the shore. Pure arithmetic on the coast already measured (_COAST)."""
    import numpy as np
    n = len(me.vertices)
    sp = np.empty(n, np.float32)
    me.attributes["simpler_spacing"].data.foreach_get("value", sp)
    lo = max(2.0 * d0, _peak(s) / 8.0)
    fade = np.clip((2.0 * lo - sp) / lo, 0.0, 1.0)
    co = _COAST if (_COAST["d"] is not None and len(_COAST["d"]) == n and s["coast"]) else None
    if co is None:
        return (fade.astype(np.float32), np.zeros(n, np.float32), np.full(n, COAST_DMAX, np.float32),
                np.full(n, COAST_CMAX, np.float32))
    d, c, inside = co["d"], co["c"], co["inside"]
    allow, cfoam = _coast_fields(s, d, c, inside)
    depth = d                               # (negative on land: its height over the sea - the water thins out to it)
    return ((fade * allow).astype(np.float32), cfoam.astype(np.float32), depth.astype(np.float32), c.astype(np.float32))


def _coast_fields(s, d, c, inside):
    """(what the depth allows the waves, the foam of the coast) from the depth, the distance from the shore and the
    land - per point of the grid, and (1.76.26) per cell of the coast's map (_raster)."""
    import numpy as np
    H = s["height"]
    water = ~inside
    # the waves feel the bottom: never higher than BREAK × depth (there they break); on land (inside an object at
    # the water line) none - the sea stays flat under the rock or the sand
    # (the broken waves still run up the shore - the swash: a part of them goes on into the shallowest water and over
    # the land for a few metres, so the water line moves with the waves and is drawn by the sea, not by the straight
    # edge where the bottom crosses the level; under the land the surface is hidden anyway)
    swash = 0.35
    run = 1.5 + 6.0 * H
    allow = np.where(water, np.maximum(_smooth(0.0, 1.0, BREAK * d / max(H, 1e-3)), swash),
                     swash * (1.0 - _smooth(0.0, run, c))) if H > 1e-3 else water.astype(np.float32)
    # the white water of the surf: where the waves reach that limit, wider on gentle slopes and with bigger seas
    # (strongest along the line where they break, weaker in the white water between there and the shore)
    ratio = H / (BREAK * d + 1e-3)
    surf = np.where(water, _smooth(0.75, 1.15, ratio) * (0.4 + 0.6 * np.exp(-((ratio - 1.15) / 0.35) ** 2)), 0.0) \
        if H > 0.05 else np.zeros(np.shape(d))
    # a ring of foam where the water touches something, as wide as the waves are high
    # (1.76.33: a little wider and whiter with low seas too - the foam that clings to a rock or a hull, Luca)
    ring_w = max(0.6, 0.4 + 0.6 * H)
    ring = np.where(water & (c < COAST_CMAX), 1.0 - _smooth(0.0, ring_w, c), 0.0) * (0.55 + 0.45 * min(1.0, H / 0.6))
    # (and the foam of the swash where the waves run over the land)
    ring = np.maximum(ring, np.where(inside, 1.0 - _smooth(0.0, run, c), 0.0) * 0.6 * min(1.0, 2.0 * H))
    cfoam = np.clip(np.maximum(0.8 * surf, ring) * s["coastFoam"], 0.0, 1.0)
    return allow, cfoam


def _set_weights(me, s, d0):
    w, cf, dep, sh = _weights(me, s, d0)
    changed = _write(me, "simpler_w", w)
    for name, v in (("simpler_cfoam", cf), ("simpler_depth", dep), ("simpler_shore", sh)):
        changed = _write(me, name, v) or changed
    # (1.76.37) which points are on land, kept with the project: their depth is no longer always negative (_steep_edge)
    import numpy as np
    land = _COAST["inside"] if (_COAST["inside"] is not None and len(_COAST["inside"]) == len(me.vertices)) \
        else np.zeros(len(me.vertices), bool)
    if "simpler_land" not in me.attributes:
        me.attributes.new("simpler_land", "FLOAT", "POINT")
    changed = _write(me, "simpler_land", land.astype(np.float32)) or changed
    if changed:
        me.update()
    return changed


def _fade_group():
    g = bpy.data.node_groups.get(FADE_GROUP)
    if g is not None and g.nodes.get("edge_obj") is not None and g.nodes.get("edge_v3") is not None:
        return g
    if g is not None:                       # (a sea of before 1.76.33: the group made again, with the shore's ripples)
        g.name = FADE_GROUP + " (vecchio)"
        old = g
        g = _fade_group()
        for ob in bpy.data.objects:
            for m in ob.modifiers:
                if m.type == "NODES" and m.node_group is old:
                    m.node_group = g
        if old.users == 0:
            bpy.data.node_groups.remove(old)
        return g
    g = bpy.data.node_groups.new(FADE_GROUP, "GeometryNodeTree")
    g.interface.new_socket("Geometry", in_out="INPUT", socket_type="NodeSocketGeometry")
    g.interface.new_socket("Geometry", in_out="OUTPUT", socket_type="NodeSocketGeometry")
    n, L = g.nodes, g.links
    gi, go = n.new("NodeGroupInput"), n.new("NodeGroupOutput")
    rest = n.new("GeometryNodeInputNamedAttribute"); rest.data_type = "FLOAT_VECTOR"; rest.inputs["Name"].default_value = "simpler_rest"
    w = n.new("GeometryNodeInputNamedAttribute"); w.data_type = "FLOAT"; w.inputs["Name"].default_value = "simpler_w"
    pos = n.new("GeometryNodeInputPosition")
    mix = n.new("ShaderNodeMix"); mix.data_type = "VECTOR"; mix.clamp_factor = True
    a = next(s for s in mix.inputs if s.identifier == "A_Vector")
    b = next(s for s in mix.inputs if s.identifier == "B_Vector")
    fac = next(s for s in mix.inputs if s.identifier == "Factor_Float")
    out = next(s for s in mix.outputs if s.identifier == "Result_Vector")
    sp = n.new("GeometryNodeSetPosition")
    L.new(rest.outputs["Attribute"], a); L.new(pos.outputs["Position"], b); L.new(w.outputs["Attribute"], fac)
    L.new(gi.outputs[0], sp.inputs["Geometry"]); L.new(out, sp.inputs["Position"])
    # (1.76.33, Luca: «il bordo che tocca l'acqua è troppo netto, se la camera è vicina dovrebbero vedersi le onde»)
    # near what the sea touches the short waves become true shape: the faces of the band along the shore (where
    # the grid is fine) cut smaller (edge_sub: about 12 cm) and raised and lowered by a field of small waves, as
    # high as the sea allows (edge_amp), fading to nothing at the edge of the band (edge_band) - so the line where
    # the water meets a rock, a pier, a hull is no longer a clean cut. At the band's edge the field is zero: the
    # finer faces meet the others without gaps. Only for the path tracing (the view has its own light version)
    def value(name, v):
        x = n.new("ShaderNodeValue"); x.name = name; x.outputs[0].default_value = v
        return x.outputs[0]

    def math_(kind, a, b=None):
        m = n.new("ShaderNodeMath"); m.operation = kind
        for i, x in enumerate((a, b)):
            if x is None:
                continue
            if isinstance(x, (int, float)):
                m.inputs[i].default_value = x
            else:
                L.new(x, m.inputs[i])
        return m.outputs[0]

    def named(name):
        a = n.new("GeometryNodeInputNamedAttribute"); a.data_type = "FLOAT"; a.inputs["Name"].default_value = name
        return a.outputs["Attribute"]

    band = value("edge_band", 3.0)
    amp = value("edge_amp", 0.0)
    # (1.76.36, Luca: «0%, 300%, 1200% non cambia nulla») the distance from what the sea touches measured on its own
    # shape (EDGE_OBJ: the triangles of the coast's objects around the water line), not from the points of the grid:
    # 2.5 m apart near a big terrain, they knew the shore to a metre or two and the band fell between them
    oi = n.new("GeometryNodeObjectInfo"); oi.name = "edge_obj"; oi.transform_space = "RELATIVE"
    n.new("NodeFrame").name = "edge_v3"           # (the version of the group: 1.76.37)
    prox = n.new("GeometryNodeProximity"); prox.target_element = "FACES"
    L.new(oi.outputs["Geometry"], prox.inputs["Target"] if "Target" in prox.inputs else prox.inputs[0])
    spacing = named("simpler_spacing")
    near = math_("LESS_THAN", prox.outputs["Distance"], math_("ADD", band, math_("MULTIPLY", spacing, 1.5)))
    fine = math_("LESS_THAN", spacing, 3.0)
    # (1.76.37: no longer limited to near the camera - that tied the sea to the camera, made again at every move of
    # the view, and with a camera of none or a moved one (the engine's own) nothing was cut: «Acqua mossa sul bordo»
    # did nothing, found by tools/slider_audit.py. The water line alone, where the grid is fine: some 10^5 faces)
    on = math_("GREATER_THAN", amp, 0.001)
    sel = math_("MULTIPLY", math_("MULTIPLY", near, fine), on)
    sep = n.new("GeometryNodeSeparateGeometry"); sep.domain = "FACE"; sep.name = "edge_sep"
    L.new(sp.outputs[0], sep.inputs["Geometry"]); L.new(sel, sep.inputs["Selection"])
    sub = n.new("GeometryNodeSubdivideMesh"); sub.name = "edge_sub"
    sub.inputs["Level"].default_value = 2
    L.new(sep.outputs["Selection"], sub.inputs["Mesh"])
    pos2 = n.new("GeometryNodeInputPosition")
    nz1 = n.new("ShaderNodeTexNoise"); nz1.noise_dimensions = "3D"
    nz1.inputs["Scale"].default_value = 0.9; nz1.inputs["Detail"].default_value = 2.0; nz1.inputs["Roughness"].default_value = 0.5
    nz2 = n.new("ShaderNodeTexNoise"); nz2.noise_dimensions = "3D"
    nz2.inputs["Scale"].default_value = 0.45; nz2.inputs["Detail"].default_value = 1.0
    for nz in (nz1, nz2):
        L.new(pos2.outputs["Position"], nz.inputs["Vector"])
    # (centred on zero: noise 0.5 ± ~0.13 → ±1; the long one sets where the water rises more)
    r1 = math_("MULTIPLY", math_("SUBTRACT", nz1.outputs["Fac"], 0.5), 7.5)
    r2 = math_("MULTIPLY", math_("SUBTRACT", nz2.outputs["Fac"], 0.5), 4.0)
    ripple = math_("ADD", math_("MULTIPLY", r1, 0.7), math_("MULTIPLY", r2, 0.5))
    prox2 = n.new("GeometryNodeProximity"); prox2.target_element = "FACES"
    L.new(oi.outputs["Geometry"], prox2.inputs["Target"] if "Target" in prox2.inputs else prox2.inputs[0])
    fade = n.new("ShaderNodeMapRange"); fade.interpolation_type = "SMOOTHSTEP"; fade.clamp = True
    L.new(prox2.outputs["Distance"], fade.inputs["Value"]); L.new(band, fade.inputs["From Max"])
    fade.inputs["From Min"].default_value = 0.0
    fade.inputs["To Min"].default_value = 1.0; fade.inputs["To Max"].default_value = 0.0
    h = math_("MULTIPLY", math_("MULTIPLY", ripple, fade.outputs["Result"]), amp)
    off = n.new("ShaderNodeCombineXYZ")
    L.new(h, off.inputs["Z"])
    sp2 = n.new("GeometryNodeSetPosition")
    L.new(sub.outputs["Mesh"], sp2.inputs["Geometry"]); L.new(off.outputs[0], sp2.inputs["Offset"])
    join = n.new("GeometryNodeJoinGeometry")
    L.new(sp2.outputs[0], join.inputs[0]); L.new(sep.outputs["Inverted"], join.inputs[0])
    L.new(join.outputs[0], go.inputs[0])
    return g


EDGE_OBJ = "Simpler Oceano costa (forma)"
EDGE_FACES = 400000                 # (1.76.37) at most so many faces more for the ripples of the shore


def _edge_shape(level, V, T):
    """(1.76.36) The triangles of what the sea touches at the water line (those crossing it), as one
    hidden object the shore's ripples measure their distance from (_fade_group: edge_obj). None: empty."""
    import numpy as np
    from .core import INTERNAL_KEY
    ob = bpy.data.objects.get(EDGE_OBJ)
    if ob is None:
        me = bpy.data.meshes.new(EDGE_OBJ)
        ob = bpy.data.objects.new(EDGE_OBJ, me)
        ob[INTERNAL_KEY] = 1
        ob.hide_render = True
        ob.hide_select = True
        ob.display_type = "BOUNDS"
        bpy.context.scene.collection.objects.link(ob)
        ob.hide_viewport = True
    elif ob.name not in bpy.context.scene.objects:
        bpy.context.scene.collection.objects.link(ob)
    me = ob.data
    tris = np.zeros((0, 3), np.int64)
    if V is not None and T is not None and len(T):
        z = V[T][:, :, 2]
        keep = (z.max(axis=1) >= level - 0.3) & (z.min(axis=1) <= level + 0.3)     # (the water line itself)
        tris = T[keep]
    if not len(tris):
        me.clear_geometry()
        me.update()
        return ob
    # the length of the water line (for how fine the band may be cut: _set_edge)
    P = V[tris].astype(np.float64)
    z = P[:, :, 2] - level
    pts = []
    for a_, b_ in ((0, 1), (1, 2), (2, 0)):
        za, zb = z[:, a_], z[:, b_]
        cross = (za * zb) < 0
        t_ = np.where(cross, za / np.where(cross, za - zb, 1.0), 0.0)
        pts.append((P[:, a_, :2] + (P[:, b_, :2] - P[:, a_, :2]) * t_[:, None], cross))
    length = 0.0
    for (p1, c1), (p2, c2) in ((pts[0], pts[1]), (pts[1], pts[2]), (pts[2], pts[0])):
        both = c1 & c2
        length += float(np.linalg.norm(p1[both] - p2[both], axis=1).sum())
    ob["simpler_line"] = length / 2.0 if length > 0 else 0.0     # (each segment found from two pairs of edges)
    used, inv = np.unique(tris.ravel(), return_inverse=True)
    co = V[used].astype(np.float32)           # (world: Object Info RELATIVE brings it into the sea's own space -
                                              # 1.76.37: lowered by the level here too, it was off by it twice and
                                              # the sea at the foot of a terrain had no ripples at all)
    me.clear_geometry()
    me.vertices.add(len(co))
    me.vertices.foreach_set("co", co.ravel())
    t = inv.reshape(-1, 3).astype(np.int32)
    me.loops.add(t.size)
    me.loops.foreach_set("vertex_index", t.ravel())
    me.polygons.add(len(t))
    me.polygons.foreach_set("loop_start", np.arange(0, t.size, 3, dtype=np.int32))
    me.update(calc_edges=True)
    return ob


def _set_edge(ob, s, d0, levels):
    """The ripples of the shore for the path tracing (_fade_group): their height from the sea (none without the
    coast or with a flat sea), the band from the waves, the cut to about 12 cm from the grid near the scene."""
    m = ob.modifiers.get(MOD_FADE)
    g = m.node_group if m is not None else None
    if g is None or g.nodes.get("edge_sub") is None:
        return
    H = float(s["height"])
    amp = 0.0
    if s["coast"] and H > 0.0 and s["edgeMove"] > 0.0:
        # (1.76.38, Luca: «la linea mi sembra dritta» with a 2 m sea - the ripples were 22 cm at most: lost against a
        # sphere of 12 m. Now about a fifth of the waves' height, up to half a metre)
        amp = min(0.5, 0.03 + 0.18 * H) * min(1.0, H / 0.1) * float(s["edgeMove"])
    band = 1.2 + 1.2 * H
    fine = max(0.05, d0 / (2 ** levels))
    lev = int(max(1, min(3, math.ceil(math.log2(max(1.0, fine / 0.12))))))
    # (a long coast - the whole shore of a terrain - is cut less finely: at most EDGE_FACES faces more)
    eo_ = bpy.data.objects.get(EDGE_OBJ)
    line = float(eo_.get("simpler_line", 0.0)) if eo_ is not None else 0.0
    if line > 0:
        faces = line * 2.0 * (band + 1.5 * d0) / (d0 * d0) * (2 ** levels) ** 2
        while lev > 1 and faces * 4 ** lev > EDGE_FACES:
            lev -= 1
    for name, v in (("edge_amp", amp), ("edge_band", band)):
        nd = g.nodes[name]
        if abs(nd.outputs[0].default_value - v) > 1e-6:
            nd.outputs[0].default_value = v
    eo = bpy.data.objects.get(EDGE_OBJ)
    if eo is None or eo.data is None or not len(eo.data.polygons):
        amp = 0.0                            # (nothing to measure from: no ripples - never the whole grid cut finer)
        nd = g.nodes["edge_amp"]
        if nd.outputs[0].default_value != 0.0:
            nd.outputs[0].default_value = 0.0
    oi = g.nodes["edge_obj"]
    if oi.inputs["Object"].default_value is not eo:
        oi.inputs["Object"].default_value = eo
    sub = g.nodes["edge_sub"]
    if sub.inputs["Level"].default_value != lev:
        sub.inputs["Level"].default_value = lev


# ---------------------------------------------------------------- the material

def _material(s, hs):
    mat = bpy.data.materials.get(MAT)
    if mat is None:
        mat = bpy.data.materials.new(MAT)
        mat.use_nodes = True
        nt = mat.node_tree
        n, L = nt.nodes, nt.links
        bs = next(x for x in n if x.type == "BSDF_PRINCIPLED")
        out = next(x for x in n if x.type == "OUTPUT_MATERIAL")
        bs.location = (300, 0); out.location = (900, 0)

        def op(kind, a, b=None, c=None, clamp=False):
            m = n.new("ShaderNodeMath"); m.operation = kind; m.use_clamp = clamp
            for i, x in enumerate((a, b, c)):
                if x is None:
                    continue
                if isinstance(x, (int, float)):
                    m.inputs[i].default_value = x
                else:
                    L.new(x, m.inputs[i])
            return m.outputs[0]

        def rng(x, a, b, lo=0.0, hi=1.0, name=None):
            m = n.new("ShaderNodeMapRange"); m.interpolation_type = "SMOOTHSTEP"; m.clamp = True
            if name:
                m.name = name
            L.new(x, m.inputs["Value"])
            m.inputs["From Min"].default_value = a; m.inputs["From Max"].default_value = b
            m.inputs["To Min"].default_value = lo; m.inputs["To Max"].default_value = hi
            return m.outputs["Result"]

        def attr(name):
            a = n.new("ShaderNodeAttribute"); a.attribute_name = name; a.attribute_type = "GEOMETRY"
            return a.outputs["Fac"]

        def val(name, v):
            x = n.new("ShaderNodeValue"); x.name = x.label = name; x.outputs[0].default_value = v
            return x.outputs[0]

        def antitile(uv, name, third=False):
            """(1.76.21) A map of slopes laid without repeating (as oTile in viewer.js): a grid of triangles about half
            a tile wide, every corner with its own random shift of the map (a white noise of the corner), the three
            corners blended with sharpened weights and the sum scaled back to the spread of one map. -> the slope
            (x, y, 0), -1..1 - with third: z = the blend of the third channel (the foam of the far map, a plain
            weighted mean). The image nodes: name, name_1, name_2 (_set_far gives them the map). Before, the tile
            repeated in rows and diagonals to the horizon (Luca)."""
            su = n.new("ShaderNodeSeparateXYZ")
            L.new(uv, su.inputs[0])
            ux, uy = su.outputs["X"], su.outputs["Y"]
            sx = op("MULTIPLY", op("MULTIPLY_ADD", uy, -0.57735027, ux), 2.0)
            sy = op("MULTIPLY", uy, 2.30940108)
            bx, by = op("FLOOR", sx), op("FLOOR", sy)
            fx, fy = op("SUBTRACT", sx, bx), op("SUBTRACT", sy, by)
            up = op("GREATER_THAN", op("ADD", fx, fy), 1.0)
            dn = op("SUBTRACT", 1.0, up)
            corners = [(op("ADD", bx, up), op("ADD", by, up)), (op("ADD", bx, dn), op("ADD", by, up)),
                       (op("ADD", bx, up), op("ADD", by, dn))]
            ws = [op("ABSOLUTE", op("SUBTRACT", op("ADD", fx, fy), 1.0)),
                  op("MULTIPLY_ADD", up, op("MULTIPLY_ADD", fx, -2.0, 1.0), fx),
                  op("MULTIPLY_ADD", up, op("MULTIPLY_ADD", fy, -2.0, 1.0), fy)]
            ws = [op("POWER", w, 4.0) for w in ws]
            tot = op("ADD", op("ADD", ws[0], ws[1]), ws[2])
            ws = [op("DIVIDE", w, tot) for w in ws]
            norm = op("INVERSE_SQRT", op("ADD", op("ADD", op("MULTIPLY", ws[0], ws[0]), op("MULTIPLY", ws[1], ws[1])), op("MULTIPLY", ws[2], ws[2])))
            acc = None
            for i, ((cx, cy), w) in enumerate(zip(corners, ws)):
                cv = n.new("ShaderNodeCombineXYZ")
                L.new(cx, cv.inputs[0]); L.new(cy, cv.inputs[1])
                wn = n.new("ShaderNodeTexWhiteNoise"); wn.noise_dimensions = "2D"
                L.new(cv.outputs[0], wn.inputs["Vector"])
                sh = n.new("ShaderNodeVectorMath"); sh.operation = "ADD"
                L.new(uv, sh.inputs[0]); L.new(wn.outputs["Color"], sh.inputs[1])
                im = n.new("ShaderNodeTexImage"); im.name = name if i == 0 else f"{name}_{i}"
                im.interpolation = "Linear"; im.extension = "REPEAT"
                L.new(sh.outputs[0], im.inputs["Vector"])
                dec = n.new("ShaderNodeVectorMath"); dec.operation = "MULTIPLY_ADD"     # (colour -> slope: x 2 - 1)
                L.new(im.outputs["Color"], dec.inputs[0]); dec.inputs[1].default_value = (2.0, 2.0, 1.0 if third else 0.0); dec.inputs[2].default_value = (-1.0, -1.0, 0.0)
                sc_ = n.new("ShaderNodeVectorMath"); sc_.operation = "SCALE"
                L.new(dec.outputs[0], sc_.inputs[0]); L.new(op("MULTIPLY", w, norm), sc_.inputs["Scale"])
                if acc is None:
                    acc = sc_.outputs[0]
                else:
                    ad = n.new("ShaderNodeVectorMath"); ad.operation = "ADD"
                    L.new(acc, ad.inputs[0]); L.new(sc_.outputs[0], ad.inputs[1])
                    acc = ad.outputs[0]
            if third:
                # (the third channel scaled by the weights alone: back from the scale that keeps the contrast)
                fix = n.new("ShaderNodeVectorMath"); fix.operation = "MULTIPLY"
                inv = n.new("ShaderNodeCombineXYZ")
                inv.inputs[0].default_value = 1.0; inv.inputs[1].default_value = 1.0
                L.new(op("DIVIDE", 1.0, norm), inv.inputs[2])
                L.new(acc, fix.inputs[0]); L.new(inv.outputs[0], fix.inputs[1])
                acc = fix.outputs[0]
            return acc

        tc = n.new("ShaderNodeTexCoord")
        sep = n.new("ShaderNodeSeparateXYZ")
        L.new(tc.outputs["Object"], sep.inputs[0])
        # (1.76.26) the coast from its map where it reaches (_raster_image: foam, depth, distance from the shore),
        # from the points of the grid elsewhere
        cm = n.new("ShaderNodeVectorMath"); cm.operation = "MULTIPLY_ADD"; cm.name = "coast_map"
        L.new(tc.outputs["Object"], cm.inputs[0])
        ctx = n.new("ShaderNodeTexImage"); ctx.name = "coast_tex"; ctx.interpolation = "Linear"; ctx.extension = "CLIP"
        L.new(cm.outputs[0], ctx.inputs["Vector"])
        # (1.76.31) only where the map is finer than the grid: a coast as long as a whole terrain has cells of 3 m,
        # coarser than the grid near the scene (0.5-2 m) - there the points stay (the map from cell to 2 × cell)
        cin = op("MULTIPLY", op("MULTIPLY", ctx.outputs["Alpha"], val("coast_on", 0.0)),
                 rng(attr("simpler_spacing"), 0.0, 1.0, name="coast_fine"))
        csp = n.new("ShaderNodeSeparateColor")
        L.new(ctx.outputs["Color"], csp.inputs[0])

        def coast(name, ch):
            mx = n.new("ShaderNodeMix"); mx.data_type = "FLOAT"
            L.new(cin, mx.inputs["Factor"]); L.new(attr(name), mx.inputs[2]); L.new(csp.outputs[ch], mx.inputs[3])
            return mx.outputs[0]
        c_foam, c_depth, c_shore = coast("simpler_cfoam", 0), coast("simpler_depth", 1), coast("simpler_shore", 2)
        crest = rng(sep.outputs["Z"], -0.1, 0.6, 0.0, 0.75, name="crest")
        body = n.new("ShaderNodeMix"); body.name = "body"; body.data_type = "RGBA"
        L.new(crest, body.inputs["Factor"])
        nz = n.new("ShaderNodeTexNoise"); nz.name = "foam_noise"
        nz.inputs["Scale"].default_value = 5.0; nz.inputs["Detail"].default_value = 8.0
        nz.inputs["Roughness"].default_value = 0.7; nz.inputs["Distortion"].default_value = 0.6
        L.new(tc.outputs["Object"], nz.inputs["Vector"])
        noise = nz.outputs["Fac"]
        # the far waves (_slopes, _set_far): the slopes of one tile over the whole sea, as strong as the geometry has
        # faded; far beyond, where they are smaller than a pixel, the roughness of the open sea instead. (1.76.21)
        # with the foam of the tile in its third channel
        sc = n.new("ShaderNodeVectorMath"); sc.operation = "MULTIPLY_ADD"; sc.name = "slope_scale"
        L.new(tc.outputs["Object"], sc.inputs[0])
        sl = antitile(sc.outputs[0], "slopes_tex", third=True)
        sls = n.new("ShaderNodeSeparateXYZ"); L.new(sl, sls.inputs[0])
        farw = rng(attr("simpler_spacing"), 1.0, 2.0, 0.0, 1.0, name="far")
        # the foam of the open sea: the mask of the modifier broken up into lace - (1.76.21) where the grid has
        # grown wide the foam of the far map instead: the points of the grid there are far apart in one direction
        # (the rows in front of a camera: 1 m across, 30 m along), the foam drawn between them was long white streaks
        # pointing at the horizon (Luca: in the path tracing and in the view)
        fmix = n.new("ShaderNodeMix"); fmix.data_type = "FLOAT"
        L.new(farw, fmix.inputs["Factor"]); L.new(attr("foam"), fmix.inputs[2]); L.new(sls.outputs["Z"], fmix.inputs[3])
        sea = rng(op("MULTIPLY", fmix.outputs[0], op("MULTIPLY_ADD", noise, 3.8, -1.6, clamp=True)), 0.15, 0.9, 0.0, 0.8, name="foam")
        # the foam of the coast (surf and rings: ocean._weights), a denser lace
        # (more on the crests, where the waves break, less in the troughs; in patches of a few metres)
        gate = rng(sep.outputs["Z"], -0.1, 0.4, 0.35, 1.0, name="coast_gate")
        nz2 = n.new("ShaderNodeTexNoise"); nz2.inputs["Scale"].default_value = 0.18; nz2.inputs["Detail"].default_value = 2.0
        L.new(tc.outputs["Object"], nz2.inputs["Vector"])
        patch = rng(nz2.outputs["Fac"], 0.35, 0.65, 0.45, 1.0)
        # (1.76.22) the foam of the surf as foam is: white patches with sharp edges and holes, more and bigger where
        # the surf is strong, not a veil. Before, its amount was the opacity of a faint pattern (Blender's noise
        # spreads little: about 0.05 around 0.5) - a soft grey band a few metres off the shore (Luca: «così sfumata
        # ... e così opaca rovina il realismo quando si è vicini»). Now a field (patches of a metre or two, a fine
        # lace, more on the crests) cut at a level that the amount of surf lowers: the amount is how much of the
        # water is white, the edges stay sharp. The noises in units of their own spread (measured: 0.075 and 0.051).
        nzc = n.new("ShaderNodeTexNoise"); nzc.name = "coast_noise"
        nzc.inputs["Scale"].default_value = 0.7; nzc.inputs["Detail"].default_value = 3.0
        nzc.inputs["Roughness"].default_value = 0.55; nzc.inputs["Distortion"].default_value = 0.4
        L.new(tc.outputs["Object"], nzc.inputs["Vector"])
        za = op("MULTIPLY_ADD", nzc.outputs["Fac"], 1.0 / 0.075, -0.5 / 0.075)
        zb = op("MULTIPLY_ADD", noise, 1.0 / 0.051, -0.5 / 0.051)
        crest_b = op("MULTIPLY_ADD", gate, 1.2 / 0.325, -1.2 * 0.675 / 0.325)
        field = op("ADD", op("ADD", op("MULTIPLY", za, 0.55), op("MULTIPLY", zb, 0.85)), crest_b)
        cf = c_foam
        cov = op("MULTIPLY", cf, patch)
        thr = op("MULTIPLY_ADD", cov, -4.4, 2.2)
        cut = op("SUBTRACT", field, thr)
        # (thin at the edges of a patch, thick and white inside: a lace, not cut-outs of paper)
        thick = op("MULTIPLY_ADD", rng(cut, 0.3, 1.6), 0.45, 0.5)
        coast = op("MULTIPLY", op("MULTIPLY", rng(cut, -0.3, 0.3, 0.0, 1.0, name="coast_cut"), thick), rng(cf, 0.0, 0.08))
        # the lines the last waves leave along the shore
        # (thin, wavy and broken: the edges of the last waves, not contour lines)
        shore = c_shore
        band = rng(shore, 0.0, 1.0, 1.0, 0.0, name="shore_band")
        wave = op("MULTIPLY_ADD", op("SINE", op("MULTIPLY_ADD", noise, 40.0, op("MULTIPLY", shore, 7.0))), 0.5, 0.5)
        broken = rng(nz2.outputs["Fac"], 0.42, 0.58)
        lines = op("MULTIPLY", op("MULTIPLY", op("MULTIPLY", band, rng(wave, 0.75, 0.97)), broken), val("lines", 0.5))
        foam = op("MAXIMUM", op("MAXIMUM", sea, coast), lines)
        white = n.new("ShaderNodeMix"); white.name = "foam_color"; white.data_type = "RGBA"
        white.inputs[7].default_value = (0.82, 0.86, 0.88, 1.0)
        L.new(foam, white.inputs["Factor"]); L.new(body.outputs[2], white.inputs[6])
        # clear shallow water: the bottom shows through where it is shallow (transmission, the volume absorbs with
        # the depth); deep down the opaque sea of before. Off where it foams.
        shallow = rng(c_depth, 2.0, 6.0, 1.0, 0.0, name="shallow")
        T = op("MULTIPLY", op("MULTIPLY", shallow, op("SUBTRACT", 1.0, foam)), val("shallow_on", 1.0))
        # (1.76.23) the clear water a shader of its own (bs_clear, below), mixed with the opaque sea by T. Before, one
        # Principled took both: its base colour went from the sea's to white with T and only its transmission part
        # let the bottom through - half way (the depth where the water stops being clear) the other half was a
        # diffuse almost white: a grey band all along the coast, a few metres out, whatever the foam (Luca: «0% o
        # 200% non cambia nulla ... ancora molto opache»)
        L.new(white.outputs[2], bs.inputs["Base Color"])
        rough = n.new("ShaderNodeMix"); rough.name = "rough"; rough.data_type = "FLOAT"
        rough.inputs[3].default_value = 0.55
        # (the last centimetres of water on the shore: a film broken by bubbles and sand, not a mirror)
        thin = op("MULTIPLY", rng(c_depth, 0.0, 0.3, 0.6, 0.0), val("thin_on", 1.0))
        L.new(op("MAXIMUM", foam, thin), rough.inputs["Factor"]); L.new(rough.outputs[0], bs.inputs["Roughness"])
        rz = n.new("ShaderNodeTexNoise"); rz.name = "ripples_noise"
        rz.inputs["Scale"].default_value = 3.0; rz.inputs["Detail"].default_value = 5.0
        bump = n.new("ShaderNodeBump"); bump.name = "ripples"
        bump.inputs["Distance"].default_value = 0.03
        L.new(tc.outputs["Object"], rz.inputs["Vector"]); L.new(rz.outputs["Fac"], bump.inputs["Height"])
        L.new(bump.outputs["Normal"], bs.inputs["Normal"])
        # (the normal of the far waves again from the slope: z = sqrt(1 - x² - y²), then as a colour for the map)
        slz = op("SQRT", op("SUBTRACT", 1.0, op("ADD", op("MULTIPLY", sls.outputs["X"], sls.outputs["X"]), op("MULTIPLY", sls.outputs["Y"], sls.outputs["Y"])), clamp=True))
        slc = n.new("ShaderNodeCombineXYZ")
        L.new(op("MULTIPLY_ADD", sls.outputs["X"], 0.5, 0.5), slc.inputs[0]); L.new(op("MULTIPLY_ADD", sls.outputs["Y"], 0.5, 0.5), slc.inputs[1])
        L.new(op("MULTIPLY_ADD", slz, 0.5, 0.5), slc.inputs[2])
        far_on = val("far_on", 1.0)
        far = op("MULTIPLY", farw, far_on)
        cam = n.new("ShaderNodeCameraData")
        g = rng(cam.outputs["View Distance"], 2000.0, 8000.0, 0.0, 1.0, name="far_rough")
        nm = n.new("ShaderNodeNormalMap"); nm.space = "OBJECT"
        L.new(slc.outputs[0], nm.inputs["Color"])
        L.new(op("MULTIPLY", far, op("SUBTRACT", 1.0, g)), nm.inputs["Strength"])
        # the short waves (_detail): their slopes added to the normal near; far, where they are smaller than a
        # pixel, the roughness they make
        dsc = n.new("ShaderNodeVectorMath"); dsc.operation = "MULTIPLY_ADD"; dsc.name = "detail_scale"
        L.new(tc.outputs["Object"], dsc.inputs[0])
        dsl = antitile(dsc.outputs[0], "detail_tex")
        gd = rng(cam.outputs["View Distance"], 120.0, 480.0, 0.0, 1.0, name="detail_far")
        # (seen at a grazing angle a map of slopes shows the backs of the waves too - in a real sea hidden behind
        # the crests: the far sea went grey and a dark band lay under the horizon. There the short waves and the
        # roughness give way: what is seen of a sea at a grazing angle is the faces turned to the eye, a mirror)
        gin = n.new("ShaderNodeNewGeometry")
        dot = n.new("ShaderNodeVectorMath"); dot.operation = "DOT_PRODUCT"
        L.new(gin.outputs["Incoming"], dot.inputs[0]); L.new(gin.outputs["True Normal"], dot.inputs[1])
        gz = rng(op("ABSOLUTE", dot.outputs["Value"]), 0.03, 0.35, 0.0, 1.0, name="grazing")
        dw = n.new("ShaderNodeVectorMath"); dw.operation = "SCALE"
        L.new(dsl, dw.inputs[0]); L.new(op("MULTIPLY", op("MULTIPLY", far_on, op("SUBTRACT", 1.0, gd)), gz), dw.inputs["Scale"])
        da = n.new("ShaderNodeVectorMath"); da.operation = "ADD"
        L.new(nm.outputs["Normal"], da.inputs[0]); L.new(dw.outputs[0], da.inputs[1])
        dn = n.new("ShaderNodeVectorMath"); dn.operation = "NORMALIZE"
        L.new(da.outputs[0], dn.inputs[0])
        L.new(dn.outputs[0], bump.inputs["Normal"])
        r2 = n.new("ShaderNodeMix"); r2.data_type = "FLOAT"
        L.new(op("MULTIPLY", op("MULTIPLY", g, far_on), gz), r2.inputs["Factor"])
        L.new(rough.outputs[0], r2.inputs[2])
        L.new(op("MAXIMUM", rough.outputs[0], val("rough_far", 0.3)), r2.inputs[3])
        r3 = n.new("ShaderNodeMix"); r3.data_type = "FLOAT"
        L.new(op("MULTIPLY", op("MULTIPLY", gd, far_on), gz), r3.inputs["Factor"])
        L.new(r2.outputs[0], r3.inputs[2])
        L.new(op("MAXIMUM", r2.outputs[0], val("rough_detail", 0.0)), r3.inputs[3])
        L.new(r3.outputs[0], bs.inputs["Roughness"])
        bs.inputs["IOR"].default_value = 1.333
        bs.inputs["Metallic"].default_value = 0.0
        bsc = n.new("ShaderNodeBsdfPrincipled"); bsc.name = "bs_clear"
        bsc.inputs["Base Color"].default_value = (1.0, 1.0, 1.0, 1.0)
        bsc.inputs["Transmission Weight"].default_value = 1.0
        bsc.inputs["IOR"].default_value = 1.333
        bsc.inputs["Metallic"].default_value = 0.0
        L.new(r3.outputs[0], bsc.inputs["Roughness"])
        L.new(bump.outputs["Normal"], bsc.inputs["Normal"])
        sea_mix = n.new("ShaderNodeMixShader"); sea_mix.name = "sea_clear_mix"
        L.new(T, sea_mix.inputs[0]); L.new(bs.outputs[0], sea_mix.inputs[1]); L.new(bsc.outputs[0], sea_mix.inputs[2])
        # the sunlight reaches the bottom through the clear water (Cycles stops shadow rays at refractions): a shadow
        # ray passes where the water is clear, attenuated by the volume as the light is
        lp = n.new("ShaderNodeLightPath")
        tr_ = n.new("ShaderNodeBsdfTransparent")
        mix = n.new("ShaderNodeMixShader")
        # (the caustics of the sea, seacaustics: inside their area the sun's own shadow rays stop here - its light
        # reaches the bottom as the caustics; the sky's light still passes)
        gin2 = n.new("ShaderNodeNewGeometry")
        sunv = n.new("ShaderNodeCombineXYZ")
        L.new(val("caus_sx", 0.0), sunv.inputs[0]); L.new(val("caus_sy", 0.0), sunv.inputs[1]); L.new(val("caus_sz", -1.0), sunv.inputs[2])
        al = n.new("ShaderNodeVectorMath"); al.operation = "DOT_PRODUCT"
        L.new(gin2.outputs["Incoming"], al.inputs[0]); L.new(sunv.outputs[0], al.inputs[1])
        aligned = rng(al.outputs["Value"], 0.9970, 0.9995, 0.0, 1.0)
        px, py = sep.outputs["X"], sep.outputs["Y"]
        # (1.75.12) the border fades over 1/caus_k metres, the same as the bottom's image (seacaustics.FEATHER): with
        # half a metre the edge of the area was a straight line across the sea (Luca)
        ck = val("caus_k", 2.0)
        inx = op("MULTIPLY", op("MULTIPLY", op("SUBTRACT", px, val("caus_x0", 0.0)), ck, clamp=True),
                 op("MULTIPLY", op("SUBTRACT", val("caus_x1", 0.0), px), ck, clamp=True))
        iny = op("MULTIPLY", op("MULTIPLY", op("SUBTRACT", py, val("caus_y0", 0.0)), ck, clamp=True),
                 op("MULTIPLY", op("SUBTRACT", val("caus_y1", 0.0), py), ck, clamp=True))
        block = op("MULTIPLY", op("MULTIPLY", op("MULTIPLY", inx, iny), aligned), val("caus_on", 0.0))
        Tsh = op("MULTIPLY", T, op("SUBTRACT", 1.0, block))
        L.new(op("MULTIPLY", lp.outputs["Is Shadow Ray"], Tsh), mix.inputs[0])
        L.new(sea_mix.outputs[0], mix.inputs[1]); L.new(tr_.outputs[0], mix.inputs[2])
        # the edge of the water: the film thinner than _edge (depth of the bottom + the height of the wave here) fades
        # into the wet sand - no line where the surface meets the shore
        thick = op("ADD", c_depth, sep.outputs["Z"])
        edge = rng(thick, 0.0, 0.3, 0.0, 1.0, name="edge")
        edge_on = op("MAXIMUM", edge, op("SUBTRACT", 1.0, val("edge_on", 1.0)))
        tr2 = n.new("ShaderNodeBsdfTransparent")
        mix2 = n.new("ShaderNodeMixShader")
        L.new(edge_on, mix2.inputs[0]); L.new(tr2.outputs[0], mix2.inputs[1]); L.new(mix.outputs[0], mix2.inputs[2])
        L.new(mix2.outputs[0], out.inputs["Surface"])
        ab = n.new("ShaderNodeVolumeAbsorption"); ab.name = "absorb"
        mat["simpler_dry"] = 1
    nt = mat.node_tree
    deep_c, crest_c = COLORS[s["color"]]
    body = nt.nodes["body"]
    _put(body.inputs[6], (*deep_c, 1.0)); _put(body.inputs[7], (*crest_c, 1.0))
    cr = nt.nodes["crest"]
    _put(cr.inputs["From Min"], -0.1 * hs); _put(cr.inputs["From Max"], 0.6 * max(0.05, hs))
    cg = nt.nodes["coast_gate"]
    _put(cg.inputs["From Min"], -0.1 * hs); _put(cg.inputs["From Max"], 0.4 * max(0.05, hs))
    _put(nt.nodes["rough"].inputs[2], 0.015 + 0.06 * s["ripples"])
    _put(nt.nodes["ripples"].inputs["Strength"], 0.35 * s["ripples"])
    coast = s["coast"]
    _put(nt.nodes["lines"].outputs[0], 0.5 * s["coastFoam"] if coast else 0.0)
    _put(nt.nodes["shore_band"].inputs["From Max"], 1.5 * (0.4 + 0.6 * hs))
    dc = CLARITY[s["color"]][0] * s["clarity"]
    sh = nt.nodes["shallow"]
    _put(sh.inputs["From Min"], 0.35 * dc); _put(sh.inputs["From Max"], dc)
    clear_on = coast and s["shallow"]
    _put(nt.nodes["thin_on"].outputs[0], 1.0 if coast else 0.0)
    _put(nt.nodes["edge_on"].outputs[0], 1.0 if coast else 0.0)
    _put(nt.nodes["edge"].inputs["From Max"], _edge(hs))
    _put(nt.nodes["shallow_on"].outputs[0], 1.0 if clear_on else 0.0)
    # the volume: absorption per metre from the colour of the water, a little haze with the clarity
    t = CLARITY[s["color"]][1]
    absorb = [-math.log(max(1e-4, x)) + 0.3 / dc for x in t]
    dens = max(absorb)
    ab = nt.nodes["absorb"]
    _put(ab.inputs["Color"], (*(1.0 - a / dens for a in absorb), 1.0))
    _put(ab.inputs["Density"], dens)
    out = next(x for x in nt.nodes if x.type == "OUTPUT_MATERIAL")
    linked = out.inputs["Volume"].is_linked
    if clear_on and not linked:
        nt.links.new(ab.outputs[0], out.inputs["Volume"])
    elif not clear_on and linked:
        nt.links.remove(out.inputs["Volume"].links[0])      # (no clear water: no volume to cross)
    if hasattr(mat.cycles, "homogeneous_volume"):
        mat.cycles.homogeneous_volume = True
    return mat


def _put(sock, v):
    if sock is None:
        return
    try:
        cur = sock.default_value
        if hasattr(cur, "__len__"):
            if all(abs(a - b) < 1e-7 for a, b in zip(cur, v)):
                return
        elif abs(cur - v) < 1e-9:
            return
    except TypeError:
        pass
    sock.default_value = v


# ---------------------------------------------------------------- the object

def _object(create):
    ob = _find()
    if ob is not None or not create:
        return ob
    from .core import INTERNAL_KEY
    me = bpy.data.meshes.new(NAME)
    ob = bpy.data.objects.new(NAME, me)
    ob[OCEAN_KEY] = True
    ob[INTERNAL_KEY] = 1
    ob["simpler_dry"] = True                 # (no rain and no snow on it: the sea has its own surface)
    ob["simpler_nosnow"] = True
    bpy.context.scene.collection.objects.link(ob)
    ob.hide_select = True
    ob.cycles.is_caustics_caster = ob.cycles.is_caustics_receiver = False
    sub = ob.modifiers.new(MOD_SUB, "SUBSURF")
    sub.subdivision_type = "SIMPLE"; sub.levels = 0
    oc = ob.modifiers.new(MOD_OCEAN, "OCEAN")
    oc.geometry_mode = "DISPLACE"
    oc.foam_layer_name = "foam"
    oc.use_normals = False                   # (the normals come from the surface itself)
    fd = ob.modifiers.new(MOD_FADE, "NODES")
    fd.node_group = _fade_group()
    return ob


def _shape_sig(s):
    return json.dumps([s[k] for k in ("wind", "chop", "direction", "align", "smallest", "damping", "depth", "fetch",
                                      "sharpen", "time", "seed", "spectrum")] + [_spatial(s), ALIGN_MIN])


def _ocean_params(oc, s, scale, view_res, render_res):
    def put(attr, v):
        if getattr(oc, attr) != v:
            setattr(oc, attr, v)
    put("spectrum", SPECTRA[s["spectrum"]])
    put("spatial_size", _spatial(s))
    put("wind_velocity", float(s["wind"]))
    put("choppiness", float(s["chop"]))
    # (1.76.37, tools/slider_audit.py: «Direzione» and «Smorzamento» changed nothing with «Allineamento» at 0% - Blender's
    # waves have no direction there; a wind sea always has one: a little alignment at least)
    put("wave_alignment", max(ALIGN_MIN, float(s["align"])))
    put("wave_direction", math.radians(s["direction"]))
    put("wave_scale_min", float(s["smallest"]))
    put("damping", float(s["damping"]))
    put("depth", float(s["depth"]))
    put("fetch_jonswap", float(s["fetch"]) * 1000.0)
    put("sharpen_peak_jonswap", float(s["sharpen"]))
    put("time", float(s["time"]))
    put("random_seed", int(s["seed"]))
    put("wave_scale", float(scale))
    put("viewport_resolution", int(view_res))
    put("resolution", int(render_res))
    foam = s["foam"] > 0.0
    put("use_foam", foam)
    if foam:
        put("foam_coverage", -0.6 + 1.0 * float(s["foam"]) + 0.6 * float(s["foam"]) ** 3)
        # (1.76.37: the top of «Schiuma» reaches much more foam - tools/slider_audit.py found 0% and 100% nearly the
        # same at the shore; the presets, at 35% or less, are as before within a few hundredths)


def _resolutions(s, d0):
    sp = _spatial(s)
    _view_d, levels, rmax = DETAIL[s["detail"]]
    view = int(max(4, min(16, math.ceil(math.sqrt(sp / d0)))))
    render = int(max(view, min(rmax, math.ceil(math.sqrt(sp / (d0 / 2 ** levels))))))
    return view, render, levels


# the surface at wave scale 1, kept for the last shapes (key: _eval_key): the displacement of every point from its
# place on the grid (with no weights: the far fade and the coast are applied after, in numpy as in Geometry Nodes)
# and the foam. The displacement grows linearly with the wave scale and the foam does not depend on it (measured):
# a new height, level, colour, ripples or coast needs no simulation at all; an undo back to a recent shape neither
_EVAL = []                          # [(key, {"d1", "foam", "hs1", "rest"})], newest last
_EVAL_KEEP = 4


def _eval_key(s, view_res, topo):
    return _shape_sig(s) + f"|{view_res}|{topo}|{s['foam'] if s['foam'] > 0 else 0}"


def _evaluate(ob, s, view_res, render_res, d0):
    """Simulate once at wave scale 1 (viewport resolution), without the weights: displacement, foam and the height
    it gives in the open sea."""
    import numpy as np
    oc = ob.modifiers[MOD_OCEAN]
    fd = ob.modifiers[MOD_FADE]
    _ocean_params(oc, s, 1.0, view_res, render_res)
    fd.show_viewport = False
    try:
        dg = bpy.context.evaluated_depsgraph_get()
        dg.update()
        me = ob.evaluated_get(dg).data
        base = ob.data
        n = len(me.vertices)
        if n != len(base.vertices):
            raise RuntimeError("ocean: evaluated surface does not match the grid")
        co = np.empty(n * 3, np.float32)
        me.vertices.foreach_get("co", co)
        foam = np.zeros(n, np.uint8)
        fa = me.attributes.get("foam")
        if fa is not None and oc.use_foam:
            vals = np.empty(len(fa.data) * 4, np.float32)
            fa.data.foreach_get("color", vals)
            vals = vals[0::4]
            if fa.domain == "CORNER":
                vi = np.empty(len(me.loops), np.int32)
                me.loops.foreach_get("vertex_index", vi)
                pt = np.zeros(n, np.float32)
                pt[vi] = vals
                vals = pt
            foam = np.clip(vals * 255.0 + 0.5, 0, 255).astype(np.uint8)
    finally:
        fd.show_viewport = True
    rest = np.empty(n * 3, np.float32)
    base.attributes["simpler_rest"].data.foreach_get("vector", rest)
    sp = np.empty(n, np.float32)
    base.attributes["simpler_spacing"].data.foreach_get("value", sp)
    lo = max(2.0 * d0, _peak(s) / 8.0)
    d1 = co - rest
    z = d1[2::3][sp <= lo]                   # (the open sea where the grid is fine: the coast does not count)
    hs1 = max(1e-4, float(4.0 * z.std())) if len(z) > 16 else 1.0
    return {"d1": d1, "foam": foam, "hs1": hs1, "rest": rest}


# ---------------------------------------------------------------- the waves far away: their slopes as a map
# (1.73.8) Beyond the fine part of the grid the waves fade out of the geometry (its points too far apart for them):
# the sea there was a flat mirror - a ring where the waves stopped, the clouds reflected in long streaks. The waves
# of the modifier repeat every «spatial size» (a tile of the simulation): their slopes over one tile, at the same
# scale, go into an image (object-space normals) that the material lays over the whole sea, as strong as the
# geometry has faded (_far): near, the waves in 3D; far, the same waves as slopes only - no edge. Where they are
# smaller than a pixel, the roughness of the open sea measured by Cox and Munk for that wind takes over (no glitter
# to chase with samples). Made again only when the shape or the height of the waves change.
_SLOPES = {"key": None, "png": b"", "rev": "", "dkey": None, "dpng": b"", "drev": "", "sig2": 0.0, "dsig2": 0.0, "L": 2.0}


def _png(rgb):
    """A plain 8-bit RGB PNG of an (h, w, 3) uint8 array (rows top first) - no library in Blender's Python."""
    import struct
    import zlib
    h, w, _ = rgb.shape
    raw = b"".join(b"\0" + rgb[y].tobytes() for y in range(h))

    def chunk(t, d):
        return struct.pack(">I", len(d)) + t + d + struct.pack(">I", zlib.crc32(t + d) & 0xFFFFFFFF)
    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 2, 0, 0, 0))
            + chunk(b"IDAT", zlib.compress(raw, 6)) + chunk(b"IEND", b""))


def cox_munk(wind):
    """Roughness (Blender's, GGX) of the open sea for this wind (m/s): mean square slope 0.003 + 0.00512 U (Cox and
    Munk, 1954), alpha = sqrt(2) x rms slope, roughness = sqrt(alpha)."""
    s2 = 0.003 + 0.00512 * max(0.0, float(wind))
    return min(0.8, math.sqrt(math.sqrt(2.0 * s2)))


_TILE = []                          # [(key, displacement at wave scale 1)], newest last (the shape of the waves)


def _tile_disp(s, res, S, N):
    """The displacement (N, N, 3: [y, x]) of one tile of the waves of side S at wave scale 1: the modifier on a grid
    of N x N points of its own, in a scene of its own (in the project's scene a new object made Blender look at the
    whole scene again: 1 s on the cathedral). It grows linearly with the scale: simulated once per shape."""
    import numpy as np
    key = _shape_sig(s) + f"|{res}|{S}|{N}"
    for k_, D in _TILE:
        if k_ == key:
            return D
    h = S / N
    ii, jj = np.meshgrid(np.arange(N), np.arange(N), indexing="xy")      # (row j = y, column i = x)
    rest = np.stack([ii.ravel() * h, jj.ravel() * h, np.zeros(N * N)], axis=1).astype(np.float32)
    me = bpy.data.meshes.new("_simpler_slopes")
    me.vertices.add(N * N)
    me.vertices.foreach_set("co", rest.ravel())
    me.update()
    tmp = bpy.data.objects.new("_simpler_slopes", me)
    sc = bpy.data.scenes.new("_simpler_slopes")
    sc.collection.objects.link(tmp)
    try:
        oc = tmp.modifiers.new("o", "OCEAN")
        oc.geometry_mode = "DISPLACE"
        oc.use_normals = False
        _ocean_params(oc, dict(s, foam=0.0), 1.0, res, res)
        with bpy.context.temp_override(scene=sc, view_layer=sc.view_layers[0]):
            dg = bpy.context.evaluated_depsgraph_get()
            dg.update()
            ev = tmp.evaluated_get(dg).data
        co = np.empty(N * N * 3, np.float32)
        ev.vertices.foreach_get("co", co)
    finally:
        bpy.data.objects.remove(tmp, do_unlink=True)
        bpy.data.meshes.remove(me)
        bpy.data.scenes.remove(sc)
    D = (co.reshape(-1, 3) - rest).reshape(N, N, 3)
    _TILE[:] = [x for x in _TILE if x[0] != key][-3:] + [(key, D)]
    return D


def _tile_foam(s, res, S, N):
    """(1.76.21) The foam of the modifier (0..1, (N, N): [y, x]) over one tile of side S: for the far sea, where the
    points of the grid are too far apart to carry it (_material). The modifier's foam needs faces: a grid of quads."""
    import numpy as np
    if float(s["foam"]) <= 0.0:
        return np.zeros((N, N), np.float32)
    key = _shape_sig(s) + f"|foam{float(s['foam']):.4f}|{res}|{S}|{N}"
    for k_, F in _TILE:
        if k_ == key:
            return F
    h = S / N
    ii, jj = np.meshgrid(np.arange(N), np.arange(N), indexing="xy")
    rest = np.stack([ii.ravel() * h, jj.ravel() * h, np.zeros(N * N)], axis=1).astype(np.float32)
    i = np.arange((N - 1) * (N - 1))
    r, c = i // (N - 1), i % (N - 1)
    a = r * N + c
    quads = np.stack([a, a + 1, a + N + 1, a + N], axis=1).astype(np.int32)
    me = bpy.data.meshes.new("_simpler_foam")
    me.vertices.add(N * N)
    me.vertices.foreach_set("co", rest.ravel())
    me.loops.add(quads.size)
    me.loops.foreach_set("vertex_index", quads.ravel())
    me.polygons.add(len(quads))
    me.polygons.foreach_set("loop_start", np.arange(0, quads.size, 4, dtype=np.int32))
    me.update(calc_edges=True)
    tmp = bpy.data.objects.new("_simpler_foam", me)
    sc = bpy.data.scenes.new("_simpler_foam")
    sc.collection.objects.link(tmp)
    F = np.zeros(N * N, np.float32)
    try:
        oc = tmp.modifiers.new("o", "OCEAN")
        oc.geometry_mode = "DISPLACE"
        oc.use_normals = False
        oc.foam_layer_name = "foam"
        _ocean_params(oc, s, 1.0, res, res)
        with bpy.context.temp_override(scene=sc, view_layer=sc.view_layers[0]):
            dg = bpy.context.evaluated_depsgraph_get()
            dg.update()
            ev = tmp.evaluated_get(dg).data
        fa = ev.attributes.get("foam")
        if fa is not None:
            vals = np.empty(len(fa.data) * 4, np.float32)
            fa.data.foreach_get("color", vals)
            vals = vals[0::4]
            if fa.domain == "CORNER":
                vi = np.empty(len(ev.loops), np.int32)
                ev.loops.foreach_get("vertex_index", vi)
                F[vi] = vals
            else:
                F[:] = vals[:N * N]
    finally:
        bpy.data.objects.remove(tmp, do_unlink=True)
        bpy.data.meshes.remove(me)
        bpy.data.scenes.remove(sc)
    F = np.clip(F, 0.0, 1.0).reshape(N, N)
    # (the last row and column: the grid does not wrap - the first ones again, the tile repeats)
    F[-1, :] = F[0, :]
    F[:, -1] = F[:, 0]
    _TILE[:] = [x for x in _TILE if x[0] != key][-3:] + [(key, F)]
    return F


def _tile_normals(s, k, res, S, N):
    """The normals (N, N, 3: [y, x], z up) of one tile at wave scale k: the slopes with the neighbours (the tile
    repeats: no edge)."""
    import numpy as np
    h = S / N
    D = _tile_disp(s, res, S, N) * np.float32(k)
    tu = np.roll(D, -1, axis=1) - np.roll(D, 1, axis=1); tu[..., 0] += 2 * h
    tv = np.roll(D, -1, axis=0) - np.roll(D, 1, axis=0); tv[..., 1] += 2 * h
    n = np.cross(tu, tv)
    n /= np.maximum(np.linalg.norm(n, axis=2, keepdims=True), 1e-9)
    return n


def _slopes(ob, s, k, res):
    """The image of the slopes of one tile at wave scale k (made again only for a new shape or height)."""
    import numpy as np
    S = float(_spatial(s))
    _SLOPES.update(k=float(k), res=int(res))          # (for the caustics of the sea: the same waves)
    key = _shape_sig(s) + f"|{k:.5f}|{res}|{SLOPE_N}|foam{float(s['foam']):.4f}|v2"     # (v2: the foam in blue)
    img = bpy.data.images.get(SLOPE_IMG)
    if img is not None and img.get("simpler_key") == key and img.size[0] == SLOPE_N:
        _SLOPES["sig2"] = float(img.get("simpler_sig2", 0.0))
        if _SLOPES["key"] != key:            # (a project just opened: the image is in the file, the view needs its PNG)
            px = np.empty(SLOPE_N * SLOPE_N * 4, np.float32)
            img.pixels.foreach_get(px)
            _SLOPES.update(key=key, png=_png(np.clip(px.reshape(SLOPE_N, SLOPE_N, 4)[::-1, :, :3] * 255 + 0.5, 0, 255).astype(np.uint8)),
                           rev=hashlib.sha1(key.encode()).hexdigest()[:10])
        return img
    # (the simulation's grid is 16 x its resolution a side: 16 gives the 256 points of the map - more is not seen)
    n = _tile_normals(s, k, min(int(res), SLOPE_N // 16), S, SLOPE_N)
    sig2 = float((((n[..., 0] / n[..., 2]) ** 2) + ((n[..., 1] / n[..., 2]) ** 2)).mean())
    enc = n * 0.5 + 0.5
    # (1.76.21) the third channel: the foam of the tile, not the z of the normal - the material and the view make z
    # again from x and y (_material, viewer.js oTile)
    enc[..., 2] = _tile_foam(s, min(int(res), SLOPE_N // 16), S, SLOPE_N)
    N = SLOPE_N
    if img is None or img.size[0] != N:
        if img is not None:
            bpy.data.images.remove(img)
        img = bpy.data.images.new(SLOPE_IMG, N, N, float_buffer=True, alpha=False)
        img.colorspace_settings.name = "Non-Color"
        img.use_fake_user = True
    px = np.ones((N, N, 4), np.float32)
    px[..., :3] = enc
    img.pixels.foreach_set(px.ravel())
    img.pack()                               # (in the project: the final render reads a saved copy)
    img["simpler_key"] = key
    img["simpler_sig2"] = sig2
    _SLOPES["sig2"] = sig2
    _SLOPES.update(key=key, png=_png(np.clip(enc[::-1] * 255 + 0.5, 0, 255).astype(np.uint8)),
                   rev=hashlib.sha1(key.encode()).hexdigest()[:10])
    return img


def _far_info(s):
    """For the view: the map of the slopes (rev, tile), where the geometry fades (the grid: its centre, the fine
    part, its spacing - beyond r0 the spacing grows by GROWTH a row, about d0 + 0.06 x the distance past r0) and the
    roughness far away."""
    ob = _find()
    topo = (ob.data.get(TOPO_KEY) if ob is not None else "") or ""
    try:
        cx, cy, r0, d0 = (float(x) for x in topo.split(",")[:4])
    except ValueError:
        return None
    S = float(_spatial(s))
    return {"rev": _SLOPES["rev"], "S": S, "N": SLOPE_N, "lo": max(2.0 * d0, _peak(s) / 8.0), "cx": cx, "cy": cy,
            "r0": r0, "d0": d0, "grow": GROWTH - 1.0, "rough": cox_munk(s["wind"]) if s["height"] > 0 else 0.0,
            "g0": min(15000.0, max(500.0, 20.0 * S)), "g1": min(19000.0, max(2000.0, 80.0 * S)),
            "on": s["height"] > 0, "drev": _SLOPES["drev"], "L": _SLOPES["L"],
            "roughD": math.sqrt(math.sqrt(2.0 * _SLOPES["dsig2"])) if _SLOPES["dsig2"] > 0 else 0.0}


def _detail_size(s):
    """Side of the tile of the short waves (m): a little longer than the shortest waves the grid draws."""
    return round(min(8.0, max(1.0, float(_spatial(s)) / 32.0)), 2)


def _detail_normals(s, L, N, sig2, min_len=0.0):
    """The short waves (the ripples and wavelets the simulation leaves out: shorter than about L): a field of its
    own made here with the shape of the short end of a wind sea - height spectrum k^-4, so every octave adds the
    same slope; mostly along the wind, partly all round - random phases from the seed, periodic over L. Scaled to
    the slope variance sig2 (what the sea for this wind has and the simulated waves do not)."""
    import numpy as np
    rng = np.random.default_rng(int(s["seed"]) * 7919 + 17)
    kx = np.fft.fftfreq(N, d=L / N) * 2.0 * math.pi
    KX, KY = np.meshgrid(kx, kx, indexing="xy")
    K = np.hypot(KX, KY)
    K[0, 0] = 1.0
    th = np.arctan2(KY, KX) - math.radians(float(s["direction"]))
    P = K ** -4.0 * (0.4 + 1.2 * np.cos(th) ** 2)
    P[K < 2.0 * math.pi / L * 0.999] = 0.0
    P[0, 0] = 0.0
    amp = np.sqrt(P) * (rng.normal(size=K.shape) + 1j * rng.normal(size=K.shape))
    sx = np.real(np.fft.ifft2(1j * KX * amp))
    sy = np.real(np.fft.ifft2(1j * KY * amp))
    m = float((sx * sx + sy * sy).mean())
    f = math.sqrt(max(0.0, sig2) / m) if m > 0 else 0.0
    if min_len > 0.0:
        # (the caustics of the sea: only the waves longer than min_len - the same amplitudes, the shorter ones left
        # out; they only blur the net, seacaustics adds that blur)
        amp = np.where(K > 2.0 * math.pi / min_len, 0.0, amp)
        sx = np.real(np.fft.ifft2(1j * KX * amp))
        sy = np.real(np.fft.ifft2(1j * KY * amp))
    n = np.stack([-sx * f, -sy * f, np.ones_like(sx)], axis=2)
    return n / np.linalg.norm(n, axis=2, keepdims=True)


def _detail(s):
    """The image of the short waves: the slope the sea has for this wind (Cox and Munk) less the slope of the
    simulated waves (measured on their tile, _slopes)."""
    import numpy as np
    L = _detail_size(s)
    target = (0.003 + 0.00512 * float(s["wind"])) if s["height"] > 0 else 0.0
    f = float(s["ripples"]) / 0.35          # («Increspature»: at its default the sea of that wind; less, smoother)
    sig2 = max(0.0, target - _SLOPES["sig2"]) * f * f
    key = f"{L}|{sig2:.5f}|{s['seed']}|{s['direction']}|{SLOPE_N}"
    img = bpy.data.images.get(DETAIL_IMG)
    _SLOPES.update(dsig2=sig2, L=L)
    if img is not None and img.get("simpler_key") == key and img.size[0] == SLOPE_N:
        if _SLOPES["dkey"] != key:
            px = np.empty(SLOPE_N * SLOPE_N * 4, np.float32)
            img.pixels.foreach_get(px)
            _SLOPES.update(dkey=key, dpng=_png(np.clip(px.reshape(SLOPE_N, SLOPE_N, 4)[::-1, :, :3] * 255 + 0.5, 0, 255).astype(np.uint8)),
                           drev=hashlib.sha1(key.encode()).hexdigest()[:10])
        return img
    N = SLOPE_N
    enc = _detail_normals(s, L, N, sig2) * 0.5 + 0.5
    if img is None or img.size[0] != N:
        if img is not None:
            bpy.data.images.remove(img)
        img = bpy.data.images.new(DETAIL_IMG, N, N, float_buffer=True, alpha=False)
        img.colorspace_settings.name = "Non-Color"
        img.use_fake_user = True
    px = np.ones((N, N, 4), np.float32)
    px[..., :3] = enc
    img.pixels.foreach_set(px.ravel())
    img.pack()
    img["simpler_key"] = key
    _SLOPES.update(dkey=key, dpng=_png(np.clip(enc[::-1] * 255 + 0.5, 0, 255).astype(np.uint8)),
                   drev=hashlib.sha1(key.encode()).hexdigest()[:10])
    return img


def caustic_fields(min_len=0.0):
    """For seacaustics: the waves as the material draws them - the slopes of the simulation's tile at the scale of
    now (N, N, 2: dz/dx, dz/dy, [y, x]) and its side, the short waves (same) and theirs, the height of the waves, the
    level, the light lost per metre in the water (RGB) and the depth where the bottom stops showing. None: no sea."""
    import numpy as np
    ob = _find()
    if ob is None or "k" not in _SLOPES:
        return None
    s = settings(ob)
    S = float(_spatial(s))
    n = _tile_normals(s, _SLOPES["k"], min(int(_SLOPES["res"]), SLOPE_N // 16), S, SLOPE_N)
    geo = np.stack([-n[..., 0] / n[..., 2], -n[..., 1] / n[..., 2]], axis=2)
    L = _SLOPES.get("L", _detail_size(s))
    d = _detail_normals(s, L, SLOPE_N, _SLOPES.get("dsig2", 0.0), min_len)
    det = np.stack([-d[..., 0] / d[..., 2], -d[..., 1] / d[..., 2]], axis=2)
    left = max(0.0, _SLOPES.get("dsig2", 0.0) - float((det ** 2).sum(-1).mean()))     # (the slope left out)
    dc = CLARITY[s["color"]][0] * s["clarity"]
    t = CLARITY[s["color"]][1]
    absorb = np.array([-math.log(max(1e-4, x)) + 0.3 / dc for x in t])
    return {"geo": geo, "S": S, "det": det, "L": L, "H": float(s["height"]), "level": float(s["level"]),
            "ext": absorb, "dc": dc, "s": s, "left": left}


def _caus_k(nt):
    """The node of the width of the border (1.75.12); a sea of before gets it: the four ramps of the border, which
    had 2.0 (half a metre), take it."""
    k = nt.nodes.get("caus_k")
    if k is not None:
        return k
    k = nt.nodes.new("ShaderNodeValue"); k.name = k.label = "caus_k"; k.outputs[0].default_value = 2.0
    for name in ("caus_x0", "caus_x1", "caus_y0", "caus_y1"):
        v = nt.nodes.get(name)
        if v is None:
            continue
        for l1 in list(v.outputs[0].links):
            sub = l1.to_node
            if sub.type != "MATH" or sub.operation != "SUBTRACT":
                continue
            for l2 in list(sub.outputs[0].links):
                mul = l2.to_node
                if mul.type == "MATH" and mul.operation == "MULTIPLY" and mul.use_clamp and not mul.inputs[1].is_linked:
                    nt.links.new(k.outputs[0], mul.inputs[1])
    return k


def set_caustic_area(rect, sun, feather=0.5):
    """The sea draws its caustics (seacaustics) inside rect (x0, y0, x1, y1): there the sun no longer passes the
    surface evenly (its light comes as the caustics) - only along the sun's direction, the sky still does. None: off.
    feather: metres over which the border fades (the bottom's image fades the same way)."""
    ob = _find()
    mat = bpy.data.materials.get(MAT)
    if ob is None or mat is None:
        return
    nt = mat.node_tree
    if nt.nodes.get("caus_on") is None:
        return
    _put(_caus_k(nt).outputs[0], 1.0 / max(0.05, float(feather)))
    _put(nt.nodes["caus_on"].outputs[0], 1.0 if rect else 0.0)
    if rect:
        for name, v in zip(("caus_x0", "caus_y0", "caus_x1", "caus_y1"), rect):
            _put(nt.nodes[name].outputs[0], float(v))
        for name, v in zip(("caus_sx", "caus_sy", "caus_sz"), sun):
            _put(nt.nodes[name].outputs[0], -float(v))


def slopes_png(which=""):
    """GET ocean/slopes: the maps for the real-time view (from the HTTP thread): the far waves, or the short ones."""
    if which == "coast":
        return _RASTER["png"]                        # (1.76.27: the coast's map, _raster_image)
    return _SLOPES["dpng"] if which == "detail" else _SLOPES["png"]


def _set_far(mat, s, d0, img):
    """The far waves of the material: the map, the tile, where the geometry has faded, the roughness far away."""
    nt = mat.node_tree
    S = float(_spatial(s))
    lo = max(2.0 * d0, _peak(s) / 8.0)
    for k in ("slopes_tex", "slopes_tex_1", "slopes_tex_2"):
        t = nt.nodes[k]
        if t.image is not img:
            t.image = img
    _put(nt.nodes["slope_scale"].inputs[1], (1.0 / S, 1.0 / S, 1.0))
    _put(nt.nodes["slope_scale"].inputs[2], (0.5 / SLOPE_N, 0.5 / SLOPE_N, 0.0))
    g = nt.nodes["far_rough"]                # (the waves of the map smaller than a pixel: from about 20 tiles away)
    _put(g.inputs["From Min"], min(15000.0, max(500.0, 20.0 * S))); _put(g.inputs["From Max"], min(19000.0, max(2000.0, 80.0 * S)))
    fr = nt.nodes["far"]
    _put(fr.inputs["From Min"], lo); _put(fr.inputs["From Max"], 2.0 * lo)
    _put(nt.nodes["far_on"].outputs[0], 1.0 if s["height"] > 0 else 0.0)
    _put(nt.nodes["rough_far"].outputs[0], cox_munk(s["wind"]))
    # the short waves: their map, its tile; far away (smaller than a pixel) the roughness they make instead
    dimg = _detail(s)
    for k in ("detail_tex", "detail_tex_1", "detail_tex_2"):
        dt = nt.nodes[k]
        if dt.image is not dimg:
            dt.image = dimg
    L = _SLOPES["L"]
    _put(nt.nodes["detail_scale"].inputs[1], (1.0 / L, 1.0 / L, 1.0))
    _put(nt.nodes["detail_scale"].inputs[2], (0.5 / SLOPE_N, 0.5 / SLOPE_N, 0.0))
    dg = nt.nodes["detail_far"]
    _put(dg.inputs["From Min"], 60.0 * L); _put(dg.inputs["From Max"], 240.0 * L)
    sd2 = _SLOPES["dsig2"]
    _put(nt.nodes["rough_detail"].outputs[0], math.sqrt(math.sqrt(2.0 * sd2)) if sd2 > 0 else 0.0)


# ---------------------------------------------------------------- the coast: what the sea touches
# For every point of the grid, at the level of the sea: is it inside something (land, rock: a ray going up meets a
# surface facing up), how deep is the water under it (a ray going down, up to COAST_DMAX), how far is the shore
# (the nearest point of the water line on the grid, up to COAST_CMAX). Measured on the objects of the scene that
# reach the level of the sea (their box), not the ground of the Ambiente; only for the points over their boxes.
# Made again when the grid, the level or those objects change (moved, edited): at once when the sea changes, in the
# idle time after the other commands (rain.idle) and before a path-traced image (rain.ensure).
_COAST = {"key": None, "changes": -1, "d": None, "c": None, "inside": None, "objects": 0, "ground": False, "secs": 0.0, "points": 0}
_TRIS = {}                          # object name -> (its state, world points, triangles near the sea)
BAND = {"v": None, "name": "", "line": None}      # the wet band on the shore for the rain's materials: (level, top, soft)


def _coast_sources(level):
    from .core import managed_objects
    from .ambience import GROUND_KEY
    from mathutils import Vector
    # (what reaches down to the sea: a new height of the waves does not change the list - measured again for
    # nothing, it took 3 s on the cathedral)
    lo_z, hi_z = level - COAST_DMAX, level + 0.05
    out = []
    for o in managed_objects():
        if o.type != "MESH" or o.get(GROUND_KEY) or o.get("simpler_trashed") or o.hide_render or o.data is None:
            continue
        # (a model of the library carries simpler_paint_model too: it is a real object of the scene; only the points
        # of a distribution are left out)
        if o.get("simpler_paint_data") or o.modifiers.get("Simpler Decal") is not None:
            continue
        mw = o.matrix_world
        zs = [(mw @ Vector(c)).z for c in o.bound_box]
        if min(zs) > hi_z or max(zs) < lo_z:
            continue
        out.append(o)
    return out


def _coast_sig(srcs, s, topo):
    parts = [topo, round(s["level"], 4)]
    for o in srcs:
        mw = o.matrix_world
        parts.append((o.name, o.data.name, len(o.data.vertices), o.data.get("simpler_georev", 0),
                      tuple(round(mw[r][c], 4) for r in range(3) for c in range(4))))
    import hashlib
    return hashlib.sha1(repr(parts).encode()).hexdigest()      # (the same in every session: hash() is not)


def _ground_bed(level):
    """The ground of the Ambiente as the bed of the sea, when it is one: tilted (a beach going down into the water)
    or lowered under the sea. A flat ground just under the level (as the Ambiente makes it) is not: the whole sea would
    be a few millimetres deep - there the panel suggests removing it. (normal, point, radius) or None."""
    from .ambience import GROUND_KEY, _find_flag
    from mathutils import Vector
    g = _find_flag(GROUND_KEY)
    if g is None or g.hide_render or g.data is None:
        return None
    mw = g.matrix_world
    nrm = (mw.to_3x3() @ Vector((0.0, 0.0, 1.0))).normalized()
    p0 = mw.translation
    tilted = nrm.z < math.cos(math.radians(0.05))
    if not tilted and float(p0.z) > level - 0.3:
        return None
    if nrm.z < 0.2:
        return None                          # (a ground on its side: not a sea bed)
    r = max(max(abs(c[0]), abs(c[1])) for c in g.bound_box) * max(mw.to_scale())      # (the disc: its radius)
    return (tuple(nrm), tuple(p0), float(r))


def _coast_measure(ob, s, srcs, bed=None):
    import numpy as np
    from mathutils import Vector
    from mathutils.bvhtree import BVHTree
    from mathutils.kdtree import KDTree
    me = ob.data
    n = len(me.vertices)
    d = np.full(n, COAST_DMAX, np.float32)
    c = np.full(n, COAST_CMAX, np.float32)
    inside = np.zeros(n, bool)
    if not srcs and bed is None:
        return (d, c, inside), 0
    level = s["level"]
    rest = np.empty(n * 3, np.float32)
    me.attributes["simpler_rest"].data.foreach_get("vector", rest)
    rest = rest.reshape(-1, 3)
    pts = 0
    if bed is not None:
        # the ground of the Ambiente: a plane, in numpy for all the points at once
        (nx, ny, nz), (px, py, pz), rad = bed
        X, Y = rest[:, 0].astype(np.float64), rest[:, 1].astype(np.float64)
        zp = pz - (nx * (X - px) + ny * (Y - py)) / nz
        on = (X - px) ** 2 + (Y - py) ** 2 < rad * rad
        land = on & (zp > level)
        inside |= land
        dd = np.where(on & ~land, level - zp, COAST_DMAX)
        d = np.minimum(d, np.clip(dd, 0.0, COAST_DMAX)).astype(np.float32)
        d[land] = -np.minimum(zp[land] - level, LAND_MAX)      # (on land: minus its height over the sea)
        pts += int(on.sum())
    if not srcs:
        _raster_measure(level, None, None, bed)
        _edge_shape(level, None, None)
        return _shore(me, rest, d, c, inside), pts
    dg = bpy.context.evaluated_depsgraph_get()
    verts, tris, base = [], [], 0
    bx0, by0, bx1, by1 = 1e18, 1e18, -1e18, -1e18
    keep = {}
    for o in srcs:
        # (the triangles of each object in the world, kept while the object stays as it is: moving one rock does not
        # read again the 2,000 objects of a flooded cathedral)
        mw = o.matrix_world
        osig = (o.data.name, len(o.data.vertices), o.data.get("simpler_georev", 0), round(level, 4),
                tuple(round(mw[r][c], 5) for r in range(3) for c in range(4)), tuple(m.name for m in o.modifiers))
        hit = _TRIS.get(o.name)
        if hit is not None and hit[0] == osig:
            co, t = hit[1], hit[2]
        else:
            co, t = None, None
            e = o.evaluated_get(dg)
            try:
                m = e.to_mesh()
            except RuntimeError:
                m = None
            try:
                if m is not None:
                    m.calc_loop_triangles()
                    nv, nt = len(m.vertices), len(m.loop_triangles)
                    if nt:
                        co = np.empty(nv * 3, np.float32)
                        m.vertices.foreach_get("co", co)
                        M = np.array(mw, np.float64)
                        co = (co.reshape(-1, 3) @ M[:3, :3].T + M[:3, 3]).astype(np.float32)
                        t = np.empty(nt * 3, np.int32)
                        m.loop_triangles.foreach_get("vertices", t)
                        t = t.reshape(-1, 3)
                        t = t[co[t][:, :, 2].max(axis=1) >= level - COAST_DMAX]   # (deeper than that never counts)
                        if not len(t):
                            co, t = None, None
            finally:
                if m is not None:
                    e.to_mesh_clear()
        keep[o.name] = (osig, co, t)
        if co is None:
            continue
        verts.append(co)
        tris.append(t + base)
        base += len(co)
        bx0, by0 = min(bx0, float(co[:, 0].min())), min(by0, float(co[:, 1].min()))
        bx1, by1 = max(bx1, float(co[:, 0].max())), max(by1, float(co[:, 1].max()))
    _TRIS.clear()
    _TRIS.update(keep)
    if not tris:
        _raster_measure(level, None, None, bed)
        _edge_shape(level, None, None)
        return _shore(me, rest, d, c, inside), pts
    V = np.concatenate(verts)
    T = np.concatenate(tris)
    _raster_measure(level, V, T, bed)
    _edge_shape(level, V, T)
    bvh = BVHTree.FromPolygons(V.tolist(), T.tolist(), all_triangles=True)
    m_ = COAST_CMAX
    sel = np.nonzero((rest[:, 0] >= bx0 - m_) & (rest[:, 0] <= bx1 + m_) & (rest[:, 1] >= by0 - m_) & (rest[:, 1] <= by1 + m_))[0]
    up, down = Vector((0.0, 0.0, 1.0)), Vector((0.0, 0.0, -1.0))
    p = Vector((0.0, 0.0, 0.0))
    for i in sel:
        p.x, p.y, p.z = float(rest[i, 0]), float(rest[i, 1]), level - 0.002
        hit = bvh.ray_cast(p, up)
        if hit[0] is not None and hit[1].z > 0.0:
            inside[i] = True
            d[i] = -min(hit[3], LAND_MAX)
            continue
        p.z = level
        hit = bvh.ray_cast(p, down, COAST_DMAX)
        if hit[0] is not None and hit[3] < d[i]:
            d[i] = hit[3]
    return _shore(me, rest, d, c, inside), pts + len(sel)


# ---------------------------------------------------------------- (1.76.26) the coast as a map
# The coast was measured on the points of the sea's grid: fine near the centre of the scene, wider and wider away
# from it - and, as the grid is made of rows and columns, long and thin where one direction is fine and the other
# wide (1 m × 30 m). The foam of the coast, the clear water and the edge of the water drawn between those points
# came out as straight bands along the rows, not around the shore (Luca: «la schiuma della costa è dritta invece di
# circondare il modello»). Now the coast is also measured on a map of square cells over the part of the scene it is
# in (up to RASTER_N a side), read by the material and the view where it reaches; the grid's points stay for the
# waves (how much the depth lets them rise) and outside the map.
COAST_IMG = "Simpler Oceano costa"
RASTER_N = 1024
_RASTER = {"d": None, "c": None, "inside": None, "x0": 0.0, "y0": 0.0, "size": 0.0, "n": 0, "key": "", "png": b"",
           "rev": "", "vkey": None}


def _steep_edge(d, inside, pairs):
    """(1.76.37, Luca: «il terreno fantasma appare anche nella 1.76.35») a point on land next to deep water (a rock, a
    pier's pillar, a sphere, a cliff - not a beach) takes the depth of that water, less a little: between the two the
    depth stays that of the sea. Before, «land» (minus its height) against 1.2 m of water made a shallow slope across the
    whole cell between them - 2.5 m near a big terrain - and the clear water and the edge of the water faded the sea
    out there: the bottom showed dry around the object, a piece of «ground» that was not there. On a beach the water
    next to the land is shallow: little changes. pairs: (land, water) indices."""
    import numpy as np
    if not len(pairs):
        return d
    a, b = pairs[:, 0], pairs[:, 1]
    want = d[b] - 0.3
    np.maximum.at(d, a, want.astype(d.dtype))
    return d


def _raster_measure(level, V, T, bed):
    """Depth, land and distance from the shore on the map (numpy, rays only where something stands over the level)."""
    import numpy as np
    from mathutils import Vector
    from mathutils.bvhtree import BVHTree
    from .ecosystems import _Ground
    boxes = []
    if V is not None and len(T):
        tz = V[T][:, :, 2]
        near = T[tz.min(axis=1) <= level + LAND_MAX + 0.5]        # (what reaches down to the water line)
        if len(near):
            P = V[np.unique(near)]
            boxes.append((float(P[:, 0].min()), float(P[:, 1].min()), float(P[:, 0].max()), float(P[:, 1].max())))
    if bed is not None:
        (_nx, _ny, _nz), (px, py, _pz), rad = bed
        r = min(float(rad), RADIUS)
        boxes.append((px - r, py - r, px + r, py + r))
    if not boxes:
        _RASTER.update(d=None, c=None, inside=None, n=0, key="", png=b"", rev="", vkey=None)
        return
    m_ = COAST_CMAX + 2.0
    x0 = max(-RADIUS, min(b[0] for b in boxes) - m_)
    y0 = max(-RADIUS, min(b[1] for b in boxes) - m_)
    x1 = min(RADIUS, max(b[2] for b in boxes) + m_)
    y1 = min(RADIUS, max(b[3] for b in boxes) + m_)
    size = max(x1 - x0, y1 - y0, 1.0)
    cell = max(0.25, size / RASTER_N)
    n = int(math.ceil(size / cell)) + 1
    size = (n - 1) * cell
    xs = x0 + np.arange(n) * cell
    ys = y0 + np.arange(n) * cell
    X, Y = np.meshgrid(xs, ys)                    # (rows: y from the south)
    X, Y = X.ravel(), Y.ravel()
    d = np.full(X.size, COAST_DMAX, np.float32)
    inside = np.zeros(X.size, bool)
    if bed is not None:
        (nx, ny, nz), (px, py, pz), rad = bed
        zp = pz - (nx * (X - px) + ny * (Y - py)) / nz
        on = (X - px) ** 2 + (Y - py) ** 2 < rad * rad
        land = on & (zp > level)
        inside |= land
        d = np.where(on & ~land, np.clip(level - zp, 0.0, COAST_DMAX), d).astype(np.float32)
        d[land] = -np.minimum(zp[land] - level, LAND_MAX)
    if V is not None and len(T):
        # the highest surface over every cell (all at once); under the level: the depth. Over it: land - unless the
        # cell is under something that stands over the water (a pier, an arch): a ray from just under the level up,
        # that leaves a solid (it meets a face looking up), says land; else the water goes on under it
        hit, z, _n = _Ground(V.astype(np.float64), T.astype(np.int64)).drop(X, Y)
        wet = hit & (z <= level)
        d = np.where(wet, np.minimum(d, np.clip(level - z, 0.0, COAST_DMAX)), d).astype(np.float32)
        over = np.nonzero(hit & (z > level))[0]
        if len(over):
            bvh = BVHTree.FromPolygons(V.tolist(), T.tolist(), all_triangles=True)
            up, down = Vector((0.0, 0.0, 1.0)), Vector((0.0, 0.0, -1.0))
            p = Vector((0.0, 0.0, 0.0))
            for i in over:
                p.x, p.y, p.z = float(X[i]), float(Y[i]), level - 0.002
                h = bvh.ray_cast(p, up)
                if h[0] is not None and h[1].z > 0.0:
                    inside[i] = True
                    d[i] = -min(h[3], LAND_MAX)
                    continue
                p.z = level
                h = bvh.ray_cast(p, down, COAST_DMAX)
                if h[0] is not None and h[3] < d[i]:
                    d[i] = h[3]
    d = d.reshape(n, n)
    inside = inside.reshape(n, n)
    idx = np.arange(n * n).reshape(n, n)
    prs = []
    for a_, b_ in ((idx[:, 1:], idx[:, :-1]), (idx[:, :-1], idx[:, 1:]), (idx[1:, :], idx[:-1, :]), (idx[:-1, :], idx[1:, :])):
        a_, b_ = a_.ravel(), b_.ravel()
        m_ = inside.ravel()[a_] & ~inside.ravel()[b_]
        prs.append(np.stack([a_[m_], b_[m_]], 1))
    d = _steep_edge(d.ravel(), inside.ravel(), np.concatenate(prs)).reshape(n, n)
    # the distance from the shore, on both sides, up to COAST_CMAX: a few rounds of «the neighbour's + a step»
    big = np.float32(1e6)
    c = np.full((n, n), big, np.float32)
    edge = np.zeros((n, n), bool)
    edge[:, 1:] |= inside[:, 1:] != inside[:, :-1]
    edge[:, :-1] |= inside[:, 1:] != inside[:, :-1]
    edge[1:, :] |= inside[1:, :] != inside[:-1, :]
    edge[:-1, :] |= inside[1:, :] != inside[:-1, :]
    c[edge] = 0.5 * cell
    steps = int(math.ceil(COAST_CMAX / cell)) + 1
    diag = np.float32(cell * math.sqrt(2.0))
    for _ in range(steps):
        p_ = np.pad(c, 1, mode="constant", constant_values=big)
        c = np.minimum.reduce([c, p_[:-2, 1:-1] + cell, p_[2:, 1:-1] + cell, p_[1:-1, :-2] + cell, p_[1:-1, 2:] + cell,
                               p_[:-2, :-2] + diag, p_[:-2, 2:] + diag, p_[2:, :-2] + diag, p_[2:, 2:] + diag])
    c = np.minimum(c, COAST_CMAX).astype(np.float32)
    import hashlib
    key = hashlib.sha1(d.tobytes() + inside.tobytes() + repr((x0, y0, size)).encode()).hexdigest()[:12]
    # (the box of the map as an image: its pixels are centred on the samples, so half a cell more on every side)
    _RASTER.update(d=d, c=c, inside=inside, x0=float(x0 - cell / 2), y0=float(y0 - cell / 2), size=float(n * cell), n=n,
                   key=key, vkey=None)
    from .core import log
    log("SIMPLER_OCEAN", f"costa in mappa: {n} × {n}, celle {cell:.2f} m, {len(over) if V is not None and len(T) else 0} punti sopra il livello")


def _raster_image(s):
    """The coast's map for the material (float: foam of the coast, depth, distance from the shore) and its PNG for the
    view - made again when the coast or what the foam depends on changes. None when there is no map."""
    import numpy as np
    import hashlib
    if _RASTER["d"] is None or not s["coast"]:
        return None
    vkey = f"{_RASTER['key']}|{s['height']:.4f}|{s['coastFoam']:.4f}"
    img = bpy.data.images.get(COAST_IMG)
    n = _RASTER["n"]
    if img is not None and img.get("simpler_key") == vkey and img.size[0] == n and _RASTER["vkey"] == vkey:
        return img
    _allow, cf = _coast_fields(s, _RASTER["d"], _RASTER["c"], _RASTER["inside"])
    px = np.ones((n, n, 4), np.float32)
    px[..., 3] = np.where(_RASTER["inside"], 0.995, 1.0)      # (1.76.37: the land kept, read back by _raster_from_file)
    px[..., 0] = cf
    px[..., 1] = _RASTER["d"]
    px[..., 2] = _RASTER["c"]
    if img is None or img.size[0] != n or img.size[1] != n:
        if img is not None:
            bpy.data.images.remove(img)
        img = bpy.data.images.new(COAST_IMG, n, n, alpha=True, float_buffer=True)
        img.colorspace_settings.name = "Non-Color"
        img.alpha_mode = "CHANNEL_PACKED"
        img.use_fake_user = True
    img.pixels.foreach_set(px.ravel())
    img.pack()
    img["simpler_key"] = vkey
    img["simpler_box"] = [_RASTER["x0"], _RASTER["y0"], _RASTER["size"]]
    ob = _find()
    img["simpler_coast_key"] = ob.data.get("simpler_coast_key", "") if ob is not None else ""
    enc = np.stack([np.clip(cf, 0, 1), np.clip((_RASTER["d"] + 2.0) / 32.0, 0, 1), np.clip(_RASTER["c"] / COAST_CMAX, 0, 1)], -1)
    _RASTER.update(png=_png(np.clip(enc[::-1] * 255 + 0.5, 0, 255).astype(np.uint8)), vkey=vkey,
                   rev=hashlib.sha1(vkey.encode()).hexdigest()[:10])
    return img


def _raster_from_file(coast_key):
    """A project just opened (_coast_from_file): the coast's map from its packed picture, when it was made for the
    same coast - else the grid's points until the coast is measured again (and the straight bands with them)."""
    import numpy as np
    import hashlib
    img = bpy.data.images.get(COAST_IMG)
    box = img.get("simpler_box") if img is not None else None
    if img is None or not coast_key or img.get("simpler_coast_key") != coast_key or box is None \
            or img.size[0] != img.size[1] or img.size[0] < 2:
        _RASTER.update(d=None, c=None, inside=None, n=0, key="", png=b"", rev="", vkey=None)
        return False
    n = img.size[0]
    px = np.empty(n * n * 4, np.float32)
    img.pixels.foreach_get(px)
    px = px.reshape(n, n, 4)
    d = px[..., 1].copy()
    c = px[..., 2].copy()
    key = hashlib.sha1(d.tobytes() + c.tobytes()).hexdigest()[:12]
    _RASTER.update(d=d, c=c, inside=(px[..., 3] < 0.9975) | (d < 0.0), x0=float(box[0]), y0=float(box[1]), size=float(box[2]), n=n, key=key,
                   png=b"", rev="", vkey=None)
    return True


def _set_coast(mat, s):
    """The material reads the coast's map where it reaches (the points of the grid elsewhere)."""
    nt = mat.node_tree
    t = nt.nodes.get("coast_tex")
    if t is None:
        return
    img = _raster_image(s)
    if t.image is not img:
        t.image = img
    on = img is not None
    size = max(1e-3, _RASTER["size"]) if on else 1.0
    _put(nt.nodes["coast_map"].inputs[1], (1.0 / size, 1.0 / size, 0.0))
    _put(nt.nodes["coast_map"].inputs[2], (-_RASTER["x0"] / size, -_RASTER["y0"] / size, 0.0) if on else (-5.0, -5.0, 0.0))
    _put(nt.nodes["coast_on"].outputs[0], 1.0 if on else 0.0)
    cell = _RASTER["size"] / max(1, _RASTER["n"]) if on else 1.0
    fine = nt.nodes["coast_fine"]
    _put(fine.inputs["From Min"], cell)
    _put(fine.inputs["From Max"], 2.0 * cell)


def _coast_info(s):
    if _RASTER["d"] is None or not s["coast"] or not _RASTER["rev"]:
        return None
    return {"rev": _RASTER["rev"], "x0": _RASTER["x0"], "y0": _RASTER["y0"], "size": _RASTER["size"], "n": _RASTER["n"],
            "cell": _RASTER["size"] / max(1, _RASTER["n"])}


def _shore(me, rest, d, c, inside):
    """The distance from the shore (the water line: halfway along every edge of the grid between land and water).
    Returns (d, c, inside)."""
    import numpy as np
    from mathutils.kdtree import KDTree
    vi = np.empty(len(me.loops), np.int32)
    me.loops.foreach_get("vertex_index", vi)
    q = vi.reshape(-1, 4)
    e = np.concatenate([q[:, [0, 1]], q[:, [1, 2]], q[:, [2, 3]], q[:, [3, 0]]])
    e = e[inside[e[:, 0]] != inside[e[:, 1]]]
    if len(e):
        lw = np.where(inside[e[:, 0]][:, None], e, e[:, ::-1])          # (land, water)
        d = _steep_edge(d, inside, lw)
        mids = (rest[e[:, 0], :2] + rest[e[:, 1], :2]) / 2.0
        kd = KDTree(len(mids))
        for k, (x, y) in enumerate(mids):
            kd.insert((float(x), float(y), 0.0), k)
        kd.balance()
        mx0, my0 = mids.min(axis=0) - COAST_CMAX
        mx1, my1 = mids.max(axis=0) + COAST_CMAX
        # (on both sides: in the water the foam, on land how far the waves run up)
        # (only where the grid is fine enough to show it: a shore of kilometres - a tilted ground - asked the far rows
        # of the grid too, 1 s for nothing)
        sp = np.empty(len(rest), np.float32)
        me.attributes["simpler_spacing"].data.foreach_get("value", sp)
        near = np.nonzero((rest[:, 0] >= mx0) & (rest[:, 0] <= mx1) & (rest[:, 1] >= my0) & (rest[:, 1] <= my1) & (sp <= 4.0))[0]
        for i in near:
            _co, _k, dist = kd.find((float(rest[i, 0]), float(rest[i, 1]), 0.0))
            if dist is not None and dist < COAST_CMAX:
                c[i] = dist
    return d, c, inside


def _coast(ob, s, topo, force=False):
    """The coast measured again if the grid, the level or the objects that reach the sea changed. True if it
    changed."""
    import time
    from . import rain
    changes = rain._STATE["changes"]
    if not s["coast"]:
        return False
    # (1.76.37: the shape of the shore for its ripples must be there too - «Togli il mare» takes it away, and a Ctrl+Z
    # that gives the sea back with the same coast found nothing to measure)
    shape_ok = not _COAST.get("objects") or bpy.data.objects.get(EDGE_OBJ) is not None
    if not force and shape_ok and _COAST["changes"] == changes and _COAST["key"] is not None and _COAST["key"][0] == (topo, round(s["level"], 4)) \
            and _COAST["d"] is not None and len(_COAST["d"]) == len(ob.data.vertices):
        return False
    _COAST["changes"] = changes
    srcs = _coast_sources(s["level"])
    bed = _ground_bed(s["level"])
    key = ((topo, round(s["level"], 4)), _coast_sig(srcs, s, topo), bed)
    if shape_ok and key == _COAST["key"] and _COAST["d"] is not None and len(_COAST["d"]) == len(ob.data.vertices):
        return False
    t0 = time.time()
    (d, c, inside), pts = _coast_measure(ob, s, srcs, bed)
    _COAST.update(key=key, d=d, c=c, inside=inside, objects=len(srcs), ground=bed is not None, points=pts,
                  secs=round(time.time() - t0, 2))
    ob.data["simpler_coast_key"] = _key_text(key)
    from .core import log
    log("SIMPLER_OCEAN", f"costa: {len(srcs)} oggetti{' + suolo' if bed else ''}, {pts} punti misurati, "
        f"{int(inside.sum())} a terra, {_COAST['secs']} s")
    return True


def _coast_from_file(ob, s, topo):
    """A project just opened: the coast is already in the grid (depth and distance from the shore were saved with
    it). Taken from there when the objects that reach the sea are the same - measuring again took 3.6 s at every
    opening of a scene with a big cliff. True if taken."""
    import numpy as np
    from . import rain
    me = ob.data
    if "simpler_depth" not in me.attributes or "simpler_shore" not in me.attributes or not me.get("simpler_coast_key"):
        return False
    srcs = _coast_sources(s["level"])
    bed = _ground_bed(s["level"])
    key = ((topo, round(s["level"], 4)), _coast_sig(srcs, s, topo), bed)
    if me.get("simpler_coast_key") != _key_text(key):
        return False
    n = len(me.vertices)
    d = np.empty(n, np.float32)
    me.attributes["simpler_depth"].data.foreach_get("value", d)
    c = np.empty(n, np.float32)
    me.attributes["simpler_shore"].data.foreach_get("value", c)
    if "simpler_land" in me.attributes:
        land = np.empty(n, np.float32)
        me.attributes["simpler_land"].data.foreach_get("value", land)
        inside = land > 0.5
    else:
        inside = d < 0.0
    _COAST.update(key=key, changes=rain._STATE["changes"], d=d, c=c, inside=inside, objects=len(srcs),
                  ground=bed is not None, points=0, secs=0.0)
    # (1.76.27: a project saved before the coast's map, or without it: measured again once, the map comes with it)
    # (1.76.36: and the shape the shore's ripples measure from)
    if (not _raster_from_file(me.get("simpler_coast_key")) or (srcs and bpy.data.objects.get(EDGE_OBJ) is None)) \
            and (srcs or bed is not None):
        _COAST.update(key=None, d=None)
        return False
    return True


def _key_text(key):
    """The key of a coast as saved in the project (the hash of the objects is the same in every session: the
    names, matrices and sizes it is made of are)."""
    import hashlib
    return hashlib.sha1(repr(key).encode()).hexdigest()


def _band(s):
    """The wet band on what the sea touches: from under the water up to where the waves run up the shore."""
    if not s["coast"] or s["wetBand"] <= 0.0:
        return None
    H = s["height"]
    top = s["level"] + (0.15 + 0.7 * H) * s["wetBand"]
    return (s["level"], top, 0.1 + 0.3 * H * s["wetBand"])


def coast_band():
    """For rain.py: (level, top of the wet band, softness) or None. Cheap: one look-up by name."""
    v, name = BAND["v"], BAND["name"]
    if v is None:
        return None
    ob = bpy.data.objects.get(name)
    if ob is None or not ob.get(OCEAN_KEY) or ob.get("simpler_trashed") or ob.name not in bpy.context.scene.objects:
        BAND["v"] = None
        return None
    return v


def _set_band(ob, s):
    BAND["v"] = _band(s) if ob is not None else None
    BAND["name"] = ob.name if ob is not None else ""
    # (no snow where the sea is or where its waves run: it melts in the water - the snow starts over the wet band)
    old = BAND.get("line")
    if ob is None:
        BAND["line"] = None
    elif BAND["v"] is not None:
        BAND["line"] = (BAND["v"][1] - BAND["v"][2], BAND["v"][1])
    else:
        BAND["line"] = (s["level"], s["level"] + 0.05)
    if BAND["line"] != old:
        from . import snow
        snow.touch()                         # (the mantle of snow follows the sea)


def snow_line():
    """For snow.py and rain.py: the snow fades in between these heights (no snow under them: the sea), or None."""
    if coast_band() is None and (BAND.get("line") is None or bpy.data.objects.get(BAND["name"]) is None):
        return None
    return BAND.get("line")


def update(s, force_coast=False):
    """Make the sea as the settings say (created if missing)."""
    import time
    t0 = time.time()
    new = _find() is None
    ob = _object(True)
    me = ob.data
    if "simpler_depth" not in me.attributes:                  # (a sea of 1.72.0: a new grid with the coast)
        me[TOPO_KEY] = ""
    # the grid stays as it is until its centre or its detail are chosen again (or the sea is made): it is the
    # place of the fine waves, and finding the box of a big scene is not free (0.1 s on the cathedral)
    lay = json.dumps([s["center"], s["detail"]])
    if new or me.get("simpler_ocean_layout") != lay or "simpler_rest" not in me.attributes or not me.get(TOPO_KEY) \
            or me.get("simpler_grid", 1) != GRID_VERSION:
        cx, cy, r0, d0 = _layout(s)
        topo = f"{cx:.2f},{cy:.2f},{r0:.1f},{d0:.3f},g{GRID_VERSION}"     # (the grid's version too: the coast saved
                                                                           # with an older grid does not fit this one)
        if me.get(TOPO_KEY) != topo or "simpler_depth" not in me.attributes or me.get("simpler_grid", 1) != GRID_VERSION:
            _build_grid(me, cx, cy, r0, d0)
            me[TOPO_KEY] = topo
            me["simpler_grid"] = GRID_VERSION
        me["simpler_ocean_layout"] = lay
    topo = me[TOPO_KEY]
    d0 = float(topo.split(",")[3])
    view_res, render_res, levels = _resolutions(s, d0)
    key = _eval_key(s, view_res, topo)
    ent = next((e for k, e in _EVAL if k == key), None)
    if ent is None:
        ent = _evaluate(ob, s, view_res, render_res, d0)
        _EVAL[:] = [x for x in _EVAL if x[0] != key][-(_EVAL_KEEP - 1):] + [(key, ent)]
        sim = "simulato"
    else:
        sim = "dalla memoria"
    _coast(ob, s, topo, force_coast)
    _set_weights(me, s, d0)
    sub = ob.modifiers[MOD_SUB]
    if sub.render_levels != levels:
        sub.render_levels = levels
    k = s["height"] / ent["hs1"] if s["height"] > 0 else 0.0
    _ocean_params(ob.modifiers[MOD_OCEAN], s, k, view_res, render_res)
    if ob.modifiers.get(MOD_FADE) is not None and ob.modifiers[MOD_FADE].node_group is not _fade_group():
        ob.modifiers[MOD_FADE].node_group = _fade_group()      # (a sea of before 1.76.33: the shore's ripples)
    _set_edge(ob, s, d0, levels)
    if abs(ob.location.z - s["level"]) > 1e-6 or ob.location.x != 0.0 or ob.location.y != 0.0:
        ob.location = (0.0, 0.0, s["level"])
    mat = _material(s, s["height"])
    if not me.materials or me.materials[0] is not mat:
        me.materials.clear()
        me.materials.append(mat)
    _set_far(mat, s, d0, _slopes(ob, s, k, render_res))
    _set_coast(mat, s)
    ob[CFG_KEY] = json.dumps(s)
    ob[REV_KEY] = uuid.uuid4().hex[:10]
    _set_band(ob, s)
    _view_surface(ob, ent, k)
    from .core import log
    log("SIMPLER_OCEAN", f"{len(me.vertices)} punti, risoluzione {view_res}/{render_res}, livelli {levels}, "
        f"Hs1 {ent['hs1']:.3f}, {sim}, {(time.time() - t0) * 1000:.0f} ms")
    return ob


def remove():
    ob = _find()
    if ob is None:
        return
    me = ob.data
    bpy.data.objects.remove(ob, do_unlink=True)
    if me is not None and me.users == 0:
        bpy.data.meshes.remove(me)
    _BIN.update({"rev": "", "topo": "", "pos": b"", "data": b"", "idx": b"", "n": 0})
    eo = bpy.data.objects.get(EDGE_OBJ)
    if eo is not None:                       # (1.76.36: the shape of the shore goes with the sea)
        em = eo.data
        bpy.data.objects.remove(eo, do_unlink=True)
        if em is not None and em.users == 0:
            bpy.data.meshes.remove(em)
    for name in (SLOPE_IMG, DETAIL_IMG, COAST_IMG):
        img = bpy.data.images.get(name)
        if img is not None:
            bpy.data.images.remove(img)
    _RASTER.update(d=None, c=None, inside=None, n=0, key="", png=b"", rev="", vkey=None)
    _SLOPES.update(key=None, png=b"", rev="", dkey=None, dpng=b"", drev="")
    _set_band(None, None)


FOLLOW = {"due": False, "t": 0.0}
FOLLOW_WAIT = 1.0                   # (s: the camera still for so long before the sea follows it)


def camera_moved():
    """(1.76.39, Luca: «io non uso sempre e solo la fotocamera?») After every move of the camera: in «Segue
    l'inquadratura», if the point looked at has left the fine part of the sea (more than half of it away from its
    centre), the sea follows a moment after the camera stops (idle_follow). Only flags: nothing is computed here."""
    ob = _find()
    if ob is None:
        FOLLOW["due"] = False
        return
    s = settings(ob)
    if s["center"] != "camera":
        FOLLOW["due"] = False
        return
    look = _look(s)
    topo = ob.data.get(TOPO_KEY, "")
    try:
        cx, cy, r0 = (float(x) for x in topo.split(",")[:3])
    except (ValueError, AttributeError):
        return
    if look is None:
        return
    far = max(abs(look[0] - cx), abs(look[1] - cy)) > 0.5 * r0 or look[2] > 1.6 * r0 or look[2] < 0.6 * r0
    FOLLOW["due"] = bool(far)
    FOLLOW["t"] = __import__("time").time()


def idle_follow(now=False):
    """The fine part of the sea moved where the camera looks (a new grid: its waves, its coast). True if done."""
    import time
    if not FOLLOW["due"] or (not now and time.time() - FOLLOW["t"] < FOLLOW_WAIT):
        return False
    FOLLOW["due"] = False
    ob = _find()
    if ob is None:
        return False
    s = settings(ob)
    if s["center"] != "camera":
        return False
    ob.data["simpler_ocean_layout"] = ""          # (the layout asked again: the grid where the camera looks)
    update(s)
    from .core import log
    log("SIMPLER_OCEAN", f"the sea follows the view: {ob.data.get(TOPO_KEY)}")
    return True


def idle_due():
    """The coast should be measured again (only flags: for the «busy» sign)."""
    from . import rain
    return (BAND["name"] != "" and _COAST["changes"] != rain._STATE["changes"]) or FOLLOW["due"]


def idle_coast():
    """From rain.idle / rain.ensure: the coast follows the objects moved or edited. True if the sea changed."""
    from . import rain
    if _COAST["changes"] == rain._STATE["changes"]:
        return False
    ob = _find()
    if ob is None:
        _COAST["changes"] = rain._STATE["changes"]
        BAND["name"] = ""            # (no sea: the «busy» sign no longer says «coast» - a project with a sea opened
        BAND["v"] = None             # before left its name here, and every move of an object showed it)
        return False
    s = settings(ob)
    me = ob.data
    topo = me.get(TOPO_KEY, "")
    if not s["coast"] or not topo or "simpler_depth" not in me.attributes:
        _COAST["changes"] = rain._STATE["changes"]
        return False
    if _COAST["d"] is None and _coast_from_file(ob, s, topo):
        return False                         # (a project just opened: its coast as it was saved)
    if not _coast(ob, s, topo):
        return False
    _view_again(ob, new_rev=True)
    return True


# ---------------------------------------------------------------- the surface for the real-time view

def _view_surface(ob, ent, k):
    """The surface as the view shows it (viewport resolution, no subdivision): the grid moved by the displacement
    at this wave scale and its weights; per point foam, coast foam, depth and distance from the shore; the
    triangles when the grid changed."""
    import numpy as np
    me = ob.data
    n = len(me.vertices)
    w = np.empty(n, np.float32)
    me.attributes["simpler_w"].data.foreach_get("value", w)
    co = ent["rest"] + ent["d1"] * np.float32(k) * np.repeat(w, 3)
    data = np.zeros((n, 4), np.uint8)
    data[:, 0] = ent["foam"]
    for j, name, lo, top in ((1, "simpler_cfoam", 0.0, 1.0), (2, "simpler_depth", -LAND_MAX, COAST_DMAX), (3, "simpler_shore", 0.0, COAST_CMAX)):
        v = np.empty(n, np.float32)
        me.attributes[name].data.foreach_get("value", v)
        data[:, j] = np.clip((v - lo) / (top - lo) * 255.0 + 0.5, 0, 255).astype(np.uint8)
    topo = me.get(TOPO_KEY, "")
    if topo != _BIN["topo"] or len(_BIN["idx"]) == 0:
        vi = np.empty(len(me.loops), np.int32)
        me.loops.foreach_get("vertex_index", vi)
        q = vi.reshape(-1, 4)
        tri = np.concatenate([q[:, [0, 1, 2]], q[:, [0, 2, 3]]], axis=1).astype(np.uint32)
        _BIN["idx"] = tri.tobytes()
        _BIN["topo"] = topo
    _BIN["pos"] = co.astype(np.float32).tobytes()
    _BIN["data"] = data.tobytes()
    _BIN["n"] = n
    _BIN["rev"] = ob.get(REV_KEY, "")


def _view_again(ob, new_rev=False):
    """After a project is opened (or a whole copy of the scene comes back with undo, or the coast changed): the
    surface for the view, simulated once if needed."""
    s = settings(ob)
    me = ob.data
    if TOPO_KEY not in me or "simpler_rest" not in me.attributes or "simpler_depth" not in me.attributes \
            or me.get("simpler_grid", 1) != GRID_VERSION:        # (a sea of an older grid: made again once)
        update(s)
        return
    topo = me[TOPO_KEY]
    d0 = float(topo.split(",")[3])
    view_res, render_res, _levels = _resolutions(s, d0)
    key = _eval_key(s, view_res, topo)
    ent = next((e for k, e in _EVAL if k == key), None)
    if ent is None:
        ent = _evaluate(ob, s, view_res, render_res, d0)
        _EVAL[:] = [x for x in _EVAL if x[0] != key][-(_EVAL_KEEP - 1):] + [(key, ent)]
    if s["coast"] and _COAST["d"] is None and not _coast_from_file(ob, s, topo):
        _coast(ob, s, topo, force=True)        # (a project just opened: measured once)
    _set_weights(me, s, d0)
    k = s["height"] / ent["hs1"] if s["height"] > 0 else 0.0
    _ocean_params(ob.modifiers[MOD_OCEAN], s, k, view_res, render_res)
    if ob.modifiers.get(MOD_FADE) is not None:
        ob.modifiers[MOD_FADE].node_group = _fade_group()      # (a sea of before 1.76.33: the shore's ripples)
    _set_edge(ob, s, d0, _levels)
    mat = _material(s, s["height"])
    if not me.materials or me.materials[0] is not mat:
        me.materials.clear()                 # (a sea of an older version: its material made again as it is now)
        me.materials.append(mat)
    _set_far(mat, s, d0, _slopes(ob, s, k, render_res))
    _set_coast(mat, s)
    _set_band(ob, s)
    if new_rev:
        ob[REV_KEY] = uuid.uuid4().hex[:10]
        from . import render
        render.invalidate()
    _BIN["topo"] = ""                        # (the triangles of this grid)
    _view_surface(ob, ent, k)


def view_rev():
    """For rain/info (the real-time view asks while the coast is wet): the surface it should have."""
    return _BIN["rev"] if _BIN["n"] else ""


def view_info():
    """For rain/info: the surface the view should have and (1.76.30) the coast's map with it - before only the
    surface came here, and after moving an object in the water the view kept the old map: where the object had been
    the water stayed «land» (transparent: the bottom under it looked like ground that was not there, Luca)."""
    ob = _find()
    rev = view_rev()
    if ob is None or not rev:
        return {"rev": rev}
    return {"rev": rev, "coastMap": _coast_info(settings(ob))}


def mesh_bytes(have_topo=""):
    """GET ocean/mesh?topo=…: 'OCN2', n points, n indices (0: the view already has them), length of the rev; the rev
    (padded to 4), the grid (64 bytes), positions float32 ×3, per point 4 bytes (foam, coast foam, depth from -2 to
    30 m - negative on land -, distance from the shore / 12 m), indices uint32. From the HTTP thread (no Blender)."""
    import struct
    b = dict(_BIN)
    if not b["n"]:
        return b""
    idx = b"" if have_topo and have_topo == b["topo"] else b["idx"]
    rev = b["rev"].encode("ascii", "replace")
    head = b"OCN2" + struct.pack("<III", b["n"], len(idx) // 4, len(rev)) + rev + b"\0" * ((4 - len(rev) % 4) % 4)
    topo = b["topo"].encode("ascii", "replace")[:64]
    return head + topo + b"\0" * (64 - len(topo)) + b["pos"] + b["data"] + idx


# ---------------------------------------------------------------- API

def state():
    """For the panel and the view (in GET ambience: no call of its own)."""
    ob = _find()
    out = {"on": ob is not None, "presets": [{"id": p[0], "name": tr(p[1])} for p in PRESETS],
           "colors": [{"id": c[0], "name": tr(c[1]), "deep": list(COLORS[c[0]][0]), "crest": list(COLORS[c[0]][1])} for c in COLOR_NAMES],
           "spectra": [{"id": k, "name": tr(v)} for k, v in SPECTRUM_NAMES]}
    s = settings(ob)
    out["settings"] = s
    out["advChanged"] = adv_changed(s) if ob is not None else False
    out["coastAdvChanged"] = any(abs(float(s[k]) - DEFAULTS[k]) > 1e-6 for k in COAST_ADV)
    if ob is None:
        return out
    if _BIN["rev"] != ob.get(REV_KEY, "") or not _BIN["n"]:
        _view_again(ob)                      # (a project just opened, an undo of a whole copy of the scene)
    deep_c, crest_c = COLORS[s["color"]]
    dc = CLARITY[s["color"]][0] * s["clarity"]
    out.update({"rev": _BIN["rev"], "topo": _BIN["topo"], "points": _BIN["n"], "level": s["level"],
                "height": s["height"], "deep": list(deep_c), "crest": list(crest_c), "ripples": s["ripples"],
                "spatial": _spatial(s), "coast": s["coast"], "shallow": bool(s["coast"] and s["shallow"]), "clear": dc,
                "coastFoam": s["coastFoam"], "band": _band(s), "far": _far_info(s), "coastMap": _coast_info(s), "edge": _edge(s["height"]), "snowLine": BAND.get("line"),
                "coastInfo": {"objects": _COAST["objects"], "ground": _COAST["ground"], "points": _COAST["points"], "secs": _COAST["secs"],
                              "land": int(_COAST["inside"].sum()) if _COAST["inside"] is not None else 0}})
    from .ambience import GROUND_KEY, _find_flag
    g = _find_flag(GROUND_KEY)
    # (a ground tilted or lowered is the bed of the sea: no warning)
    out["groundCovers"] = g is not None and not g.hide_render and _ground_bed(s["level"]) is None
    return out


def snapshot():
    ob = _find()
    return settings(ob) if ob is not None else None


def restore(snap):
    if snap is None:
        remove()
    else:
        update(_clean(dict(snap)))


def terrain_level():
    """(1.76.16, Luca: the terrain was under the sea) The level of the sea at the foot of the terrains of the scene:
    their lowest point (the outer edge: it goes down to it) plus a little, so that the sea laps the edge band and the
    whole terrain rises out of it - wherever the terrain was moved. None without a terrain."""
    from mathutils import Vector
    from . import terrain
    lo, hi = None, None
    try:
        bpy.context.view_layer.update()       # (a group just moved: its zones' matrices)
    except RuntimeError:
        pass
    for o in bpy.context.scene.objects:
        if not isinstance(o.get(terrain.ZONE_KEY), str) or o.get("simpler_trashed") or o.hide_render or o.data is None:
            continue
        if not len(getattr(o.data, "polygons", ())):
            continue
        mw = o.matrix_world
        zs = [(mw @ Vector(c)).z for c in o.bound_box]
        lo = min(zs) if lo is None else min(lo, min(zs))
        hi = max(zs) if hi is None else max(hi, max(zs))
    if lo is None:
        return None
    return round(lo + max(1.0, 0.02 * (hi - lo)), 2)


def follow_terrain():
    """After a command: a sea at the foot of the terrain (levelAuto) follows it - made, changed, moved, removed (back
    to 0). -> the state of the sea when its level changed, else None."""
    ob = _find()
    if ob is None:
        return None
    s = settings(ob)
    if not s.get("levelAuto"):
        return None
    lv = terrain_level()
    lv = 0.0 if lv is None else lv
    if abs(lv - float(s["level"])) < 0.01:
        return None
    s["level"] = lv
    update(_clean(s))
    return state()


def api_set(d):
    """POST landscape/ocean {on?, preset?, settings?: {...}, resetAdvanced?, resetCoast?, randomSeed?}"""
    if d.get("on") is False:
        remove()
        return state()
    ob = _find()
    s = settings(ob)
    if d.get("preset"):
        p = _preset(d["preset"])
        if p is not None:
            keep = {k: s[k] for k in ("level", "direction", "seed", "detail", "center", "time") + COAST_KEYS}
            s = dict(DEFAULTS)
            s.update(p)
            s.update(keep)
            s["preset"] = d["preset"]
    if isinstance(d.get("settings"), dict):
        for k, v in d["settings"].items():
            if k in DEFAULTS and k != "preset":
                s[k] = v
        if "level" in d["settings"] and "levelAuto" not in d["settings"]:
            s["levelAuto"] = False                # (the level set by hand: it stays)
    if s.get("levelAuto"):
        lv = terrain_level()
        if lv is not None:
            s["level"] = lv
    if d.get("resetAdvanced"):
        base = dict(DEFAULTS)
        base.update(_preset(s.get("preset")) or {})
        for k in ADV_KEYS:
            s[k] = base[k]
    if d.get("resetCoast"):
        for k in COAST_ADV:
            s[k] = DEFAULTS[k]
    if d.get("randomSeed"):
        import random
        s["seed"] = random.randint(1, 10000)
    update(_clean(s), force_coast=bool(d.get("measureCoast")))
    return state()


SEA_NET = False         # (1.75.2: the drawn net of 1.75.1 off - too fake next to the real caustics of the pools)


def caustic_values():
    """For rain.py (1.75.1): the caustics of the sea on the bed - on with the sea, the sun up and «Luce riflessa
    dall'acqua» (the switch of the water's light, as for the pool). k_inv: 1 / size of the cells of the net (from the
    short waves of the wind); k_sx, k_sy: the shift of the net per metre of depth, along the sun refracted into the
    water; k_amt: weaker with a low sun."""
    off = {"k_on": 0.0}
    if not SEA_NET:
        return off
    ob = _find()
    if ob is None or ob.get("simpler_trashed"):
        return off
    from . import refcaustics
    if not refcaustics.enabled():
        return off
    sun = None
    for o in bpy.context.scene.objects:
        if o.type == "LIGHT" and o.data.type == "SUN" and not o.hide_render and o.data.energy > 0 \
                and not o.get("simpler_ambience_moon") and not o.get("simpler_cloud_sun") and not o.get("simpler_fill"):
            sun = o
            break
    if sun is None:
        return off
    from mathutils import Vector
    d = (sun.matrix_world.to_quaternion() @ Vector((0.0, 0.0, 1.0))).normalized()      # (towards the sun)
    if d.z <= 0.02:
        return off
    s = settings(ob)
    h = math.hypot(d.x, d.y)
    sin_t = min(0.999, h / 1.333)                    # (refracted into the water)
    tan_t = sin_t / math.sqrt(1.0 - sin_t * sin_t)
    ax, ay = (d.x / h, d.y / h) if h > 1e-6 else (0.0, 0.0)
    cell = max(0.25, min(1.6, 0.35 + 0.06 * float(s.get("wind", 5.0))))     # (m: calm sea ~0.5 m, windy ~1 m)
    elev = math.degrees(math.asin(max(-1.0, min(1.0, d.z))))
    return {"k_on": 1.0, "k_inv": 1.0 / cell, "k_lvl": float(s["level"]),
            "k_sx": ax * tan_t, "k_sy": ay * tan_t,
            "k_amt": max(0.0, min(1.0, (elev - 3.0) / 25.0)) * min(1.0, 0.4 + float(s.get("ripples", 0.35)) * 1.7)}
