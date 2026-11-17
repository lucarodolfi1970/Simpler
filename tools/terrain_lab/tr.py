# render a heightfield with Cycles: python3 tr.py preset out.png
import sys, time, math
sys.path.insert(0, "/home/claude/simpler/engine/simpler")
import numpy as np, bpy, terrain_gen as T
preset, out = sys.argv[1], sys.argv[2]
mode = sys.argv[3] if len(sys.argv) > 3 else "fluvial"
P = T.PRESETS[preset]; size = P["size"]; height = P["height"]
M, n = 192, 512
t0 = time.time()
base = T.base_shape(preset, M, size, height, 3); bn = base / height; cell = size / (M - 1)
if mode.endswith(".npy"):
    h = np.load(mode); n = h.shape[0]
elif mode == "fluvial":
    rng = np.random.default_rng(5)
    def run(z0, U, m, steps, kf, D):
        c = size / (m - 1)
        k = kf * c / (size * size) ** 0.45
        z, _ = T.fluvial(z0, c, steps=steps, k=k, diffusion=D, uplift=U)
        return z
    m1 = 128
    b1 = T.resample(bn, m1)
    U1 = (0.15 + 0.85 * b1 ** 1.5) * height * 0.03
    z = run(b1 * height * 0.05 + rng.random(b1.shape) * 0.01 * height, U1, m1, 70, 30.0, 0.5)
    m2 = 256
    z2 = T.resample(z, m2)
    b2 = T.resample(bn, m2)
    U2 = (0.15 + 0.85 * b2 ** 1.5) * height * 0.03 * (np.ptp(z) / (height * 0.03 * 70) + 0.0)
    z2 = run(z2, U2 * 0.0, m2, 25, 30.0, 0.35)
    z2 = (z2 - z2.min()) / max(1e-6, np.ptp(z2)) * height
    import time as _t; _t0 = _t.time()
    z3 = T.resample(z2, n)
    z3 = run(z3, None, n, int(sys.argv[4]) if len(sys.argv) > 4 else 8, 30.0, 0.25)
    print("fine pass", round(_t.time() - _t0, 1))
    h = (z3 - z3.min()) / max(1e-6, np.ptp(z3)) * height
    h = T.thermal(h, size / (n - 1), P["talus"], 20)
    h = T.smooth(h, 1)
else:
    h = T.generate(preset, n=n, seed=3)["h"]
print("gen", round(time.time() - t0, 1))
bpy.ops.wm.read_factory_settings(use_empty=True)
sc = bpy.context.scene
c = size / (n - 1)
xs = (np.arange(n) - (n - 1) / 2) * c
X, Y = np.meshgrid(xs, xs)
verts = np.stack([X.ravel(), Y.ravel(), h.ravel()], 1)
idx = np.arange(n * n).reshape(n, n)
q = np.stack([idx[:-1, :-1].ravel(), idx[:-1, 1:].ravel(), idx[1:, 1:].ravel(), idx[1:, :-1].ravel()], 1)
me = bpy.data.meshes.new("t")
me.from_pydata(verts.tolist(), [], q.tolist())
me.shade_smooth() if hasattr(me, "shade_smooth") else None
ob = bpy.data.objects.new("t", me); sc.collection.objects.link(ob)
for p in me.polygons: p.use_smooth = True
mat = bpy.data.materials.new("m"); mat.use_nodes = True; nt = mat.node_tree
N = nt.nodes; L = nt.links.new
b = N["Principled BSDF"]; b.inputs["Roughness"].default_value = 0.92
geo = N.new("ShaderNodeNewGeometry")
sep = N.new("ShaderNodeSeparateXYZ"); L(geo.outputs["Normal"], sep.inputs[0])
pos = N.new("ShaderNodeSeparateXYZ"); L(geo.outputs["Position"], pos.inputs[0])
noi = N.new("ShaderNodeTexNoise"); noi.inputs["Scale"].default_value = 0.35; noi.inputs["Detail"].default_value = 8
L(geo.outputs["Position"], noi.inputs["Vector"])
g1 = N.new("ShaderNodeMix"); g1.data_type = "RGBA"; L(noi.outputs["Fac"], g1.inputs[0])
g1.inputs[6].default_value = (0.022, 0.05, 0.008, 1); g1.inputs[7].default_value = (0.06, 0.075, 0.018, 1)
img = bpy.data.images.load("/mnt/user-data/uploads/coastal_cliff_04/textures/coastal_cliff_04_diff_2k.jpg")
tex = N.new("ShaderNodeTexImage"); tex.image = img; tex.projection = "BOX"; tex.projection_blend = 0.3
mp = N.new("ShaderNodeMapping"); mp.inputs["Scale"].default_value = (0.08, 0.08, 0.08)
L(geo.outputs["Position"], mp.inputs[0]); L(mp.outputs[0], tex.inputs[0])
rk = N.new("ShaderNodeMix"); rk.data_type = "RGBA"; rk.inputs[0].default_value = 0.55
L(tex.outputs[0], rk.inputs[6]); rk.inputs[7].default_value = (0.09, 0.09, 0.09, 1)
bm = N.new("ShaderNodeBump"); bm.inputs["Strength"].default_value = 0.6; L(tex.outputs[0], bm.inputs["Height"]); L(bm.outputs[0], b.inputs["Normal"])
# slope mask: normal z 0.80 (37°) -> 0.88 (28°) with noise on the edge
sl = N.new("ShaderNodeMath"); sl.operation = "ADD"; L(sep.outputs[2], sl.inputs[0])
nb = N.new("ShaderNodeMath"); nb.operation = "MULTIPLY"; nb.inputs[1].default_value = 0.08; L(noi.outputs["Fac"], nb.inputs[0]); L(nb.outputs[0], sl.inputs[1])
mr = N.new("ShaderNodeMapRange"); mr.inputs[1].default_value = 0.76; mr.inputs[2].default_value = 0.84
L(sl.outputs[0], mr.inputs[0])
mix = N.new("ShaderNodeMix"); mix.data_type = "RGBA"; L(mr.outputs[0], mix.inputs[0])
L(rk.outputs[2], mix.inputs[6]); L(g1.outputs[2], mix.inputs[7])
# snow: high and not steep
hs = N.new("ShaderNodeMapRange"); hs.inputs[1].default_value = float(np.percentile(h, 88)) if preset == "montagne" else 1e9; hs.inputs[2].default_value = float(np.percentile(h, 94)) if preset == "montagne" else 2e9
L(pos.outputs[2], hs.inputs[0])
fl = N.new("ShaderNodeMath"); fl.operation = "MULTIPLY"; L(hs.outputs[0], fl.inputs[0]); L(mr.outputs[0], fl.inputs[1])
sn = N.new("ShaderNodeMix"); sn.data_type = "RGBA"; L(fl.outputs[0], sn.inputs[0]); L(mix.outputs[2], sn.inputs[6]); sn.inputs[7].default_value = (0.8, 0.82, 0.85, 1)
L(sn.outputs[2], b.inputs["Base Color"])
if preset == "canyon":
    g1.inputs[6].default_value = (0.09, 0.07, 0.035, 1); g1.inputs[7].default_value = (0.16, 0.1, 0.05, 1)
    rk.inputs[7].default_value = (0.32, 0.13, 0.06, 1); rk.inputs[0].default_value = 0.7
if preset == "dune":
    simg = bpy.data.images.load("/mnt/user-data/uploads/coast_sand_01/color.jpg")
    st = N.new("ShaderNodeTexImage"); st.image = simg; st.projection = "BOX"
    m2 = N.new("ShaderNodeMapping"); m2.inputs["Scale"].default_value = (0.3, 0.3, 0.3); L(geo.outputs["Position"], m2.inputs[0]); L(m2.outputs[0], st.inputs[0])
    tint = N.new("ShaderNodeMix"); tint.data_type = "RGBA"; tint.inputs[0].default_value = 0.6; L(st.outputs[0], tint.inputs[6]); tint.inputs[7].default_value = (0.55, 0.36, 0.18, 1)
    L(tint.outputs[2], b.inputs["Base Color"])
ob.data.materials.append(mat)
cam = bpy.data.objects.new("c", bpy.data.cameras.new("c")); sc.collection.objects.link(cam); sc.camera = cam
cam.data.lens = 35; cam.data.clip_end = size * 4
import os
v = os.environ.get("VIEW", "high")
from mathutils import Vector
if v == "valley":
    ci = int(n * 0.08)
    row = h[ci]; cj = int(np.argmin(row[n // 4: 3 * n // 4])) + n // 4
    cam.location = (xs[cj], xs[ci], float(h[ci, cj]) + 25)
    tj = int(np.argmin(h[int(n * 0.8)][n // 4: 3 * n // 4])) + n // 4
    d = Vector((xs[tj], xs[int(n * 0.8)], float(h[int(n * 0.8), tj]) + 40)) - cam.location
    cam.data.lens = 30
elif v == "high":
    cam.location = (-size * 0.48, -size * 0.48, float(np.percentile(h, 70)) + size * 0.12)
    d = Vector((size * 0.05, size * 0.05, float(np.median(h)))) - cam.location
else:
    eye = {"montagne": 40, "valle": 25, "canyon": 3, "colline": 4, "pianura": 2, "dune": 2}.get(preset, 5)
    # the highest of a few places near a corner: a viewpoint, looking towards the middle
    best = None
    for fi in (0.12, 0.18, 0.24):
        for fj in (0.12, 0.18, 0.24):
            ci, cj = int(n * fi), int(n * fj)
            if best is None or h[ci, cj] > h[best[0], best[1]]:
                best = (ci, cj)
    ci, cj = best
    cam.location = (xs[cj], xs[ci], float(h[ci, cj]) + eye)
    d = Vector((size * 0.1, size * 0.1, float(np.percentile(h, 50)))) - cam.location
    cam.data.lens = 30
cam.rotation_euler = d.to_track_quat("-Z", "Y").to_euler()
sun = bpy.data.objects.new("s", bpy.data.lights.new("s", "SUN")); sc.collection.objects.link(sun)
sun.data.energy = 2.6; sun.data.angle = math.radians(1); sun.rotation_euler = (math.radians(62), 0, math.radians(-120))
w = bpy.data.worlds.new("w"); w.use_nodes = True; sc.world = w
sky = w.node_tree.nodes.new("ShaderNodeTexSky")
try: sky.sky_type = "NISHITA"; sky.sun_elevation = math.radians(28); sky.sun_rotation = math.radians(-120 + 90)
except Exception: pass
w.node_tree.links.new(sky.outputs[0], w.node_tree.nodes["Background"].inputs[0]); w.node_tree.nodes["Background"].inputs[1].default_value = 0.12
fwd = d.normalized()
az = math.atan2(fwd.y, fwd.x) + math.radians(float(os.environ.get("SUNAZ", "110")))            # sun behind and to the side of the camera
el = math.radians(32)
sd = Vector((math.cos(az) * math.cos(el), math.sin(az) * math.cos(el), math.sin(el)))
sun.rotation_euler = (-sd).to_track_quat("-Z", "Y").to_euler()
try:
    sky.sun_elevation = el; sky.sun_rotation = math.atan2(sd.x, sd.y)
except Exception: pass
sc.render.engine = "CYCLES"; sc.cycles.samples = 16; sc.cycles.use_denoising = True
sc.render.resolution_x, sc.render.resolution_y = 900, 500
sc.view_settings.view_transform = "AgX"; sc.view_settings.look = "AgX - Medium High Contrast" if False else sc.view_settings.look
sc.render.filepath = out
bpy.ops.render.render(write_still=True)
print("total", round(time.time() - t0, 1))
