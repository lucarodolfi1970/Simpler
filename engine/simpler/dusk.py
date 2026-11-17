"""Lights and emissive materials that switch on by themselves at dusk ("Dal tramonto all'alba").

Every lamp and every emissive material has two switches:
  · on    (Accesa): off = always off - it wins over everything (to switch one off by hand);
  · dusk  (Dal tramonto all'alba): on only when the Ambiente says it is evening or night - the lights in the houses,
          the neon signs of a street, the street lamps.
Lit = on and (not dusk or dark).

Dark: with the sky of the Ambiente, the sun lower than DARK_ELEV degrees (a little before sunset until a little after
dawn); with a photographed sky (HDRI), its sun under that height, or without a sun its light on the ground below that
of a sun at that height; with a studio background (no time of day) it is always "dark": the lamps of a studio stay on.

A lamp that is off keeps its power aside (simpler_power) and has energy 0: the path tracing, the automatic exposure
and the real-time view (light_json "lit") all see it off, the panel still shows its power. A material keeps its
luminance in its channels; only the strength of its BSDF follows (no rebuild of the material).
"""
import math

import bpy

DARK_ELEV = 2.0
ON_KEY = "simpler_on"          # lamps: 0 = switched off by hand (absent = on)
DUSK_KEY = "simpler_dusk"      # lamps: 1 = on only from dusk to dawn
POWER_KEY = "simpler_power"    # lamps: the power while they are off


def is_dark(s=None):
    from . import ambience
    s = s if s is not None else ambience.state()
    if s is None or s.get("mode") == "studio":
        return True
    try:
        if s.get("mode") == "hdri":
            from . import hdri
            _p, a = ambience._hdri_analysis(s)
            if a.get("sun") and s["hdri"].get("sun", True):
                z = hdri.world_dir(a["sun"]["dir"], 0.0)[2]
                return z < math.sin(math.radians(DARK_ELEV))
            total = a.get("groundIrradiance", 0.0) * float(s["hdri"].get("strength", 1.0)) / ambience.K
            return total < ambience.sky_irradiance(DARK_ELEV, ambience.DEFAULTS["sky"])
        v = ambience._sun_dir(s)
        return math.degrees(math.asin(max(-1.0, min(1.0, v.z)))) < DARK_ELEV
    except Exception:
        return False


# ---------------------------------------------------------------- lamps

def lamp_lit(ob, dark=None):
    if not ob.get(ON_KEY, 1):
        return False
    if ob.get(DUSK_KEY):
        return is_dark() if dark is None else dark
    return True


def user_power(ob):
    return float(ob[POWER_KEY]) if POWER_KEY in ob else float(ob.data.energy)


def set_user_power(ob, power):
    if POWER_KEY in ob:
        ob[POWER_KEY] = float(power)
    else:
        ob.data.energy = float(power)


def apply_lamp(ob, dark=None):
    """Energy as the switches say. True when it changed."""
    if ob.type != "LIGHT" or ob.data.type == "SUN" or ob.get("simpler_ambience_moon"):
        return False
    lit = lamp_lit(ob, dark)
    if lit and POWER_KEY in ob:
        ob.data.energy = float(ob[POWER_KEY])
        del ob[POWER_KEY]
        return True
    if not lit and POWER_KEY not in ob:
        ob[POWER_KEY] = float(ob.data.energy)
        ob.data.energy = 0.0
        return True
    return False


# ---------------------------------------------------------------- emissive materials

def mat_lit(p, dark=None):
    e = p.get("emission") or {}
    if not e.get("on", True):
        return False
    if e.get("dusk", False):
        return is_dark() if dark is None else dark
    return True


def apply_material(mat, dark=None):
    """Emission strength of a Simpler material as its switches say. True when it changed."""
    from . import matedit
    p = matedit.params_of(mat)
    if p is None or float(p["emission"].get("nits", 0)) <= 0:
        return False
    lit = mat_lit(p, dark)
    if int(mat.get("simpler_lit", 1)) == int(lit):
        return False
    mat["simpler_lit"] = int(lit)
    strength = float(p["emission"]["nits"]) / matedit.NITS_PER_UNIT if lit else 0.0
    if mat.node_tree is not None:
        for n in mat.node_tree.nodes:
            if n.type == "BSDF_PRINCIPLED":
                n.inputs["Emission Strength"].default_value = strength
    return True


def update(s=None):
    """After a change of the time of day (or of the sky): every switch that follows the dusk. Returns what changed."""
    dark = is_dark(s)
    lamps, mats = [], []
    from . import paint
    # the lamps of the models of distributions too: those models are not in the scene (drawn only as copies), so a
    # lamp that follows the dusk stayed as it was saved - a car saved by day kept its cabin light off in every copy
    for ob in list(bpy.context.scene.objects) + paint.scatter_originals():
        if ob.type == "LIGHT" and (ob.get(DUSK_KEY) or POWER_KEY in ob) and apply_lamp(ob, dark):
            lamps.append(ob.get("simpler_id", ""))
    from . import matedit
    for mat in bpy.data.materials:
        p = matedit.params_of(mat) if mat.get(matedit.PARAMS_KEY) else None
        if p is not None and (p["emission"].get("dusk") or not p["emission"].get("on", True) or not mat.get("simpler_lit", 1)) \
                and apply_material(mat, dark):
            mats.append(mat.name)
        it = (p.get("interior") or {}) if p is not None else {}
        if it.get("enabled") and mat.node_tree is not None and mat.node_tree.nodes.get(matedit.INTERIOR_BRIGHT_NODE) is None:
            # (a room material made before its light followed the dark: made again once, with the same values)
            try:
                matedit.apply(mat, p)
                mats.append(mat.name)
            except Exception:
                pass
        if it.get("enabled") and mat.node_tree is not None:
            # (1.79.0) the night lights of the rooms of «Interni»: on at evening and at night; and the light of the
            # rooms themselves faint when it is dark (matedit.interior_bright), lights on or off
            ch = False
            for nn, v in ((matedit.INTERIOR_NIGHT_NODE, matedit.interior_night(it, dark)),
                          (matedit.INTERIOR_BRIGHT_NODE, matedit.interior_bright(it, dark))):
                n = mat.node_tree.nodes.get(nn)
                if n is not None and abs(n.outputs[0].default_value - v) > 1e-6:
                    n.outputs[0].default_value = v
                    ch = True
            if ch and mat.name not in mats:
                mats.append(mat.name)
    return {"dark": dark, "lamps": lamps, "materials": mats}
