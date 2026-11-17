"""(1.78.4, Luca: «problema di opacità con plantfactory») A picture called «…_Transparency» plugged into the Alpha
(as the FBX import does with PlantFactory plants: white = no surface) is read as an inverted opacity map, so the card
is cut out around the leaf - not solid with a hole in the shape of the leaf; one with a black border (an opacity map
under the same name) stays as it is. Run inside Blender:
    blender -b --factory-startup --python tools/transparency_check.py
Prints TRANSP_OK or TRANSP_FAIL <why>."""
import os
import sys
import tempfile

import bpy
import numpy as np

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "engine"))
from simpler import matedit                     # noqa: E402

bad = []
tmp = tempfile.mkdtemp(prefix="simpler_transp_")
try:
    # a «Transparency» picture: white everywhere, a black (= solid) bar in the middle, 20% of it
    w, h = 64, 64
    px = np.ones((h, w, 4), np.float32)
    px[:, 26:39, :3] = 0.0
    img = bpy.data.images.new("leaf_Transparency", w, h)
    img.pixels = px.ravel().tolist()
    img.filepath_raw = os.path.join(tmp, "leaf_Transparency.png")
    img.file_format = "PNG"
    img.save()
    mat = bpy.data.materials.new("Leaf imported")
    mat.use_nodes = True
    nt = mat.node_tree
    bsdf = next(n for n in nt.nodes if n.type == "BSDF_PRINCIPLED")
    tex = nt.nodes.new("ShaderNodeTexImage")
    tex.image = img
    nt.links.new(tex.outputs["Color"], bsdf.inputs["Alpha"])
    p, adv = matedit.read_material(mat)
    if adv or not (p["opacity"]["map"].get("image") and p["opacity"]["map"].get("invert")):
        bad.append(f"not read as an inverted opacity map: {p['opacity']}")
    # (Luca: «se faccio inverti diventa tutto bianco») the same name on an opacity map (black border, white leaf - other
    # plants of the same program): read as it is, at the import and at «Converti in vegetazione», also when an older
    # conversion had inverted it, and with the user's «Inverti» kept
    px2 = np.zeros((h, w, 4), np.float32)
    px2[:, 26:39, :3] = 1.0
    px2[..., 3] = 1.0
    imo = bpy.data.images.new("flower_M_Transparency", w, h)
    imo.pixels = px2.ravel().tolist()
    imo.filepath_raw = os.path.join(tmp, "flower_M_Transparency.png")
    imo.file_format = "PNG"
    imo.save()
    m2 = bpy.data.materials.new("Flower imported")
    m2.use_nodes = True
    b2 = next(n for n in m2.node_tree.nodes if n.type == "BSDF_PRINCIPLED")
    t2 = m2.node_tree.nodes.new("ShaderNodeTexImage")
    t2.image = imo
    m2.node_tree.links.new(t2.outputs["Color"], b2.inputs["Alpha"])
    q, _ = matedit.read_material(m2)
    if not q["opacity"]["map"].get("image") or q["opacity"]["map"].get("invert"):
        bad.append(f"an opacity map named «Transparency» read inverted: {q['opacity']}")
    q["opacity"]["map"]["invert"] = True                     # (as an older conversion left it)
    if not matedit.fix_transparency_map(q, card=True) or q["opacity"]["map"].get("invert"):
        bad.append("an older wrong inversion not undone at the conversion")
    q["opacity"]["invert"] = True                            # (the user's «Inverti»: kept, the map turns)
    matedit.fix_transparency_map(q, card=True)
    if not q["opacity"]["invert"] or not q["opacity"]["map"].get("invert"):
        bad.append(f"the user's «Inverti» changed or not balanced: {q['opacity']}")
    q2 = {"opacity": {"invert": False, "useAlpha": False, "map": {"image": img.name, "invert": False}}}
    if not matedit.fix_transparency_map(q2, card=True) or not q2["opacity"]["map"]["invert"]:
        bad.append("a white-border map not inverted at the conversion")
    # the same picture named as an opacity map stays as it is
    img2 = bpy.data.images.new("leaf_Opacity", 4, 4)
    img2.filepath_raw = os.path.join(tmp, "leaf_Opacity.png")
    if matedit.transparency_named(img2.name):
        bad.append("an «Opacity» picture taken for a transparency")
    # rendered: the card is solid only on the bar
    matedit._Builder(mat, matedit._merge(matedit.DEFAULTS, p)).build()
    sc = bpy.context.scene
    for o in list(bpy.data.objects):            # (the start-up cube and lamp)
        bpy.data.objects.remove(o)
    bpy.ops.mesh.primitive_plane_add(size=2)
    pl = bpy.context.active_object
    pl.rotation_euler = (1.5708, 0, 0)
    pl.data.materials.append(mat)
    cam = bpy.data.objects.new("cam", bpy.data.cameras.new("cam"))
    sc.collection.objects.link(cam)
    sc.camera = cam
    cam.data.type = "ORTHO"
    cam.data.ortho_scale = 2.0
    cam.location = (0, -5, 0)
    cam.rotation_euler = (1.5708, 0, 0)
    sc.render.engine = "CYCLES"
    sc.cycles.samples = 4
    sc.render.resolution_x = sc.render.resolution_y = 64
    sc.render.film_transparent = True
    sc.render.filepath = os.path.join(tmp, "r.png")
    bpy.ops.render.render(write_still=True)
    r = np.array(bpy.data.images.load(sc.render.filepath).pixels[:]).reshape(-1, 4)
    cover = float((r[:, 3] > 0.5).mean())
    if not 0.1 < cover < 0.3:
        bad.append(f"the card covers {cover:.2f} of the picture (expected about 0.2)")
except Exception as exc:
    bad.append(f"error: {exc}")
finally:
    import shutil
    shutil.rmtree(tmp, ignore_errors=True)
print("TRANSP_FAIL " + "; ".join(bad) if bad else "TRANSP_OK", flush=True)
