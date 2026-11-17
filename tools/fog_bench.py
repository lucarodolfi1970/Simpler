import sys, os, math, json, random
ENG = os.environ.get("ENG", os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "engine")); sys.path.insert(0, ENG)
import bpy
from mathutils import Vector
from simpler import server, render, ambience, i18n
i18n.set_lang("en"); server.project_new({})
out, fogmode, rain = sys.argv[-3], sys.argv[-2], sys.argv[-1] == "rain"
W, H, S = 640, 360, int(os.environ.get("S", "24"))
cam = render.camera_view(); pos = Vector(cam["position"]) * 0.01; tgt = Vector(cam["target"]) * 0.01
fwd = (tgt - pos); fwd.z = 0; fwd.normalize(); right = Vector((fwd.y, -fwd.x, 0))
def mat(name, col, alpha=1.0, checker=False):
    m = bpy.data.materials.new(name); m.use_nodes = True; b = m.node_tree.nodes["Principled BSDF"]
    b.inputs["Base Color"].default_value = (*col, 1); b.inputs["Roughness"].default_value = 0.6
    if checker:
        c = m.node_tree.nodes.new("ShaderNodeTexChecker"); c.inputs["Scale"].default_value = 40
        m.node_tree.links.new(c.outputs["Fac"], b.inputs["Alpha"])
    else: b.inputs["Alpha"].default_value = alpha
    return m
def box(name, where, size, m):
    bpy.ops.mesh.primitive_cube_add(size=1, location=where); o = bpy.context.object; o.name = name; o.scale = size; o.data.materials.append(m); return o
def plane(name, where, size, m):
    bpy.ops.mesh.primitive_plane_add(size=1, location=where); o = bpy.context.object; o.name = name; o.scale = (size, size, size)
    o.rotation_euler = (math.radians(90), 0, math.atan2(-fwd.x, fwd.y)); o.data.materials.append(m); return o
dark, white = mat("dark", (0.03, 0.05, 0.03)), mat("white", (0.8, 0.8, 0.8))
random.seed(4)
# far things (0.6 - 1.5 km): dark as a wood, and white
for i in range(10):
    d = random.uniform(600, 1500); s = random.uniform(60, 220)
    p = pos + fwd * d + right * random.uniform(-0.5, 0.5) * d; p.z = s * 0.4
    box(f"far{i}", p, (s, s, s), dark if i % 3 else white)
# a wall 60 m away on the left (so that drops and the shade have something not too far behind)
box("wall", pos + fwd * 60 - right * 14 + Vector((0, 0, 6)), (14, 2, 12), dark)
# a see-through shade 4 m away (opacity 0.7), leaves (holes) 25 m away against the sky and the far things
plane("shade", pos + fwd * 4 + right * 1.2 + Vector((0, 0, 0.2)), 1.0, mat("shade", (0.7, 0.6, 0.4), alpha=0.7))
plane("leaves", pos + fwd * 25 - right * 2 + Vector((0, 0, 4)), 9.0, mat("leaves", (0.05, 0.2, 0.05), checker=True))
fog = {"low": {"density": 0.7, "low": True, "height": 3, "falloff": 6}, "thick": {"density": 0.929, "low": False},
       "mid": {"density": 0.6, "low": False}, "none": {"density": 0.0, "low": False}, "light": {"density": 0.2, "low": False}}[fogmode]
part = {"preset": "nuvoloso"}; ambience.apply(partial=part)
if os.environ.get("VOL"): ambience.apply(partial={"clouds": {"volumetric": True, "cover": 0.6}}); ambience.apply(partial={"fog": fog})
if rain:
    ambience.apply(partial={"rain": {"wet": 0.6, "drop": True, "splash": False, "dropAmount": 0.5, "dropSize": 0.45, "dropClear": 0.5, "dropBlur": 0.6}})
    from simpler import raindrops
    try: print("drops:", raindrops.update(force=True))
    except Exception as e: print("drops failed", repr(e))
r = render.final_render({"path": out, "width": W, "height": H, "quality": "bozza", "inProcess": True, "samples": S})
print("RENDERED", r.get("path"), r.get("seconds"))
