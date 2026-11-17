"""(1.78.4, Luca: «in realtime ci sono foglie fucsia, path tracer ok») Two trees whose pictures have the same names
(Maxtree: «Bitmaptexture.0NN»): Blender renumbers the second tree's pictures and the channels of its materials must
follow them (matedit._heal_images) - the leaf's colour went to another tree's normal map in the real-time view.
Run inside Blender: blender -b --factory-startup --python tools/heal_check.py   Prints HEAL_OK or HEAL_FAIL <why>."""
import json
import os
import sys

import bpy

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "engine"))
from simpler import materials, matedit          # noqa: E402

bad = []


def leaf(tagged):
    m = bpy.data.materials.new("Leaf")
    m.use_nodes = True
    a = bpy.data.images.new("Bitmaptexture.006", 8, 8)
    a.filepath = "//t/leaf_albedo.jpg"
    n = bpy.data.images.new("Bitmaptexture.007", 8, 8)
    n.filepath = "//t/leaf_normal.jpg"
    n.colorspace_settings.name = "Non-Color"
    p = matedit._merge(matedit.DEFAULTS, {"color": {"map": {"image": a.name}}, "normal": {"map": {"image": n.name}}})
    matedit._Builder(m, p).build()
    m[matedit.PARAMS_KEY] = json.dumps(p)
    if not tagged:
        for x in m.node_tree.nodes:
            if x.type == "TEX_IMAGE" and "simpler_map" in x:
                del x["simpler_map"]
    return m, a, n


try:
    for tagged in (False, True):
        bpy.ops.wm.read_factory_settings(use_empty=True)
        m, a, n = leaf(tagged)
        a.name, n.name = "Bitmaptexture.011", "Bitmaptexture.012"      # (renumbered: another tree came first)
        other = bpy.data.images.new("Bitmaptexture.006", 8, 8)          # (that tree's normal map, same name)
        other.colorspace_settings.name = "Non-Color"
        rp = materials.realtime_params(m)
        got = (rp["maps"]["color"]["image"], rp["maps"]["normal"]["image"])
        if got != ("Bitmaptexture.011", "Bitmaptexture.012"):
            bad.append(f"{'tagged' if tagged else 'old'} material: the view would load {got}")
except Exception as exc:
    bad.append(f"error: {exc}")
print("HEAL_FAIL " + "; ".join(bad) if bad else "HEAL_OK", flush=True)
