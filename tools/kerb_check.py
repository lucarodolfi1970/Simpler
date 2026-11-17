"""(1.78.4, Luca: «sul bordo del marciapiede ci sono tagli squadrati nella neve, il resto è ok») Along a kerb that
does not follow the grid of the mantle the snow came in square teeth: the height of each cell is the one at its
centre, so the rise of the kerb went in steps of a cell, and near 15 cm some squares across it joined the two sides
and others did not. Here: the test scene with snow, a sidewalk 15 cm high turned 7 degrees off the view; seen from
above (1 cm) along its edge the sheet must have no hole and no steep teeth.
Run inside Blender with SIMPLER_CHECK_SCENE=<a .simpler>:  blender -b --python tools/kerb_check.py
Prints KERB_OK or KERB_FAIL <why>."""
import math
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "engine"))
import bmesh                                            # noqa: E402
import bpy                                              # noqa: E402
import mathutils                                        # noqa: E402
from mathutils.bvhtree import BVHTree                   # noqa: E402

try:
    from simpler import server, ambience, snow
    server.project_open({"path": os.environ["SIMPLER_CHECK_SCENE"]})
    cam = bpy.context.scene.camera
    fwd = cam.matrix_world.to_quaternion() @ mathutils.Vector((0, 0, -1))
    fwd.z = 0
    fwd.normalize()
    side = mathutils.Vector((-fwd.y, fwd.x, 0))
    H = 0.15
    me = bpy.data.meshes.new("kerb check")
    bm = bmesh.new()
    bmesh.ops.create_cube(bm, size=1.0)
    bm.to_mesh(me)
    bm.free()
    ob = bpy.data.objects.new("Kerb check", me)
    bpy.context.scene.collection.objects.link(ob)
    ang = math.atan2(fwd.y, fwd.x) + math.radians(7.0)
    c = cam.location.copy()
    c.z = 0
    c += side * -3.5 + fwd * 15
    ob.location = (c.x, c.y, H / 2)
    ob.rotation_euler = (0, 0, ang)
    ob.scale = (30, 3, H)
    bpy.context.view_layer.update()
    ambience.api_set({"snow": {"amount": 0.7, "depth": 0.1}})
    snow.update(force=True)
    dg = bpy.context.evaluated_depsgraph_get()
    sheets = [o for o in bpy.data.objects if o.type == "MESH" and o.data.name.startswith(snow.MAT_NAME)
              and "·" not in o.data.name and "punti" not in o.name]
    bv = BVHTree.FromObject(sheets[0], dg)
    u = mathutils.Vector((math.cos(ang), math.sin(ang), 0))
    v = mathutils.Vector((-u.y, u.x, 0))
    e0 = mathutils.Vector((c.x, c.y, 0)) + v * 1.5
    miss = steep = n = 0
    down = mathutils.Vector((0, 0, -1))
    for i in range(-30, 30):
        for j in range(-600, 600, 2):
            p = e0 + u * (j * 0.01) + v * (i * 0.01)
            h = bv.ray_cast(mathutils.Vector((p.x, p.y, 50)), down)
            n += 1
            if h[0] is None:
                miss += 1
            elif h[1].z < 0.5:
                steep += 1
    bad = []
    if miss > 0.002 * n:
        bad.append(f"holes along the kerb: {100.0 * miss / n:.1f}%")
    if steep > 0.01 * n:
        bad.append(f"steep teeth along the kerb: {100.0 * steep / n:.1f}%")
    print("KERB_FAIL " + "; ".join(bad) if bad else "KERB_OK")
except Exception as e:                                  # noqa: BLE001
    print(f"KERB_FAIL {e!r}")
