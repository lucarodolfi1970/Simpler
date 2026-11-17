"""(1.78.4, Luca: «cambio lo slider stagione e boom foglie bianche») An imported material with a black emission (the
default strength 1 of every FBX/glTF) is read as no emission, and a change of anything else (the season of a leaf)
never turns a black emission into a white glow; switching the light on still makes a black filter white.
Run inside Blender:
    blender -b --factory-startup --python tools/emission_check.py
Prints EMISSION_OK or EMISSION_FAIL <why>."""
import json
import os
import sys

import bpy

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "engine"))
from simpler import matedit                     # noqa: E402

bad = []
try:
    mat = bpy.data.materials.new("Leaf imported")
    mat.use_nodes = True
    bsdf = next(n for n in mat.node_tree.nodes if n.type == "BSDF_PRINCIPLED")
    bsdf.inputs["Emission Color"].default_value = (0, 0, 0, 1)
    bsdf.inputs["Emission Strength"].default_value = 1.0
    p, adv = matedit.read_material(mat)
    if p["emission"]["nits"] != 0:
        bad.append(f"a black emission read as {p['emission']['nits']} nits")
    # a leaf converted before (683 nits of black light stored): the season changes, the emission does not
    p = matedit._merge(matedit.DEFAULTS, p)
    p["emission"]["nits"], p["emission"]["color"] = 683.0, [0.0, 0.0, 0.0]
    p["foliage"]["enabled"], p["foliage"]["part"] = True, "foglie"
    matedit._Builder(mat, p).build()
    mat[matedit.PARAMS_KEY] = json.dumps(p)
    r = matedit.edit({"name": mat.name, "params": {"foliage": {"season": 0.44}}})
    q = matedit.params_of(mat)
    if sum(q["emission"]["color"]) > 0.003:
        bad.append(f"the season made the emission {q['emission']['color']}")
    # switching the light on with the black filter: white, as before
    matedit.edit({"name": mat.name, "params": {"emission": {"nits": 500.0}}})
    q = matedit.params_of(mat)
    if sum(q["emission"]["color"]) < 2.9:
        bad.append(f"switching the light on kept a black filter: {q['emission']['color']}")
except Exception as exc:
    import traceback
    traceback.print_exc()
    bad.append(f"error: {exc}")
print("EMISSION_FAIL " + "; ".join(bad) if bad else "EMISSION_OK", flush=True)
