"""Real-time view export (GLB) in a separate Blender process: the engine stays free and the export can be cancelled.

Started by the engine as:
    blender.exe --factory-startup -b scene.blend --python export_job.py -- <output.glb> <max texture px>
Prints SIMPLER_PHASE lines for the progress and SIMPLER_DONE at the end.

Textures are reduced to <max texture px> before the export (only in this copy of the scene): the real-time view
does not need 4K/8K maps and they are what makes big GLB files slow to write and heavy to load.
"""
import sys

import bpy

argv = sys.argv[sys.argv.index("--") + 1:]
out = argv[0]
part = argv[argv.index("--append") + 1] if "--append" in argv else ""
keep = "--keep" in argv          # new objects added to the view (render.export_part): placed by the view, no reset
if "--append" in argv:
    argv = argv[:argv.index("--append")]
if part:
    # one painted model alone (paint.py: its "prototype" for the real-time view): the default scene emptied, the
    # model appended from the file written by the engine, its root at the origin (the view places every piece)
    bpy.data.batch_remove(list(bpy.data.objects))
    with bpy.data.libraries.load(part, link=False) as (_src, _dst):
        _dst.collections = [c for c in _src.collections if c == "SimplerPart"]
    _coll = _dst.collections[0]
    bpy.context.scene.collection.children.link(_coll)
    _inside = set(_coll.objects)
    bpy.data.batch_remove([_ob for _ob in bpy.data.objects if _ob not in _inside])   # (the group it was painted in, came along)
    for _ob in ([] if keep else _coll.objects):
        if _ob.parent is None:
            _ob.matrix_parent_inverse.identity()
            _ob.matrix_basis.identity()
else:
    # painted pieces (Distribuisci) are not in the view file: the view draws them from their model, with levels of
    # detail and GPU instancing (one copy of each model, whatever the number of pieces)
    bpy.data.batch_remove([o for o in bpy.data.objects if o.get("simpler_paint_model") or o.get("simpler_paint_data")])
# path tracing view helpers (simpler/twins.py) are not part of the scene. In one call (1.70.3): removed one by one,
# each removal looks through all the objects - the 3,800 twins of the cathedral took 42 s of every export of the view
bpy.data.batch_remove([o for o in bpy.data.objects if o.get("simpler_twin") or o.get("simpler_water_body") or o.get("simpler_fog_domain")
                       or o.get("simpler_clouds") or o.get("simpler_cloud_sun") or o.get("simpler_fill") or o.get("simpler_snow_mantle")
                       or o.get("simpler_snow_part") or o.get("simpler_ocean")   # (the sea: the view draws it itself, ocean.py)
                       or o.get("simpler_water_grid")])   # (1.75.0: the water around the camera, path tracing only - the export crashed on it)
max_px = int(argv[1]) if len(argv) > 1 else 1024
proxies = {}
if len(argv) > 2 and argv[2]:
    import json
    import os
    with open(argv[2], encoding="utf-8") as f:
        proxies = json.load(f)
    # textures already reduced in the cache (proxy_job.py): the image nodes show those instead of the big
    # originals (map: original image name -> file). Packed textures are covered too.
    trees = [m.node_tree for m in bpy.data.materials if m.node_tree] + list(bpy.data.node_groups) + \
            [w.node_tree for w in bpy.data.worlds if w.node_tree]
    loaded = {}
    for tree in trees:
        for node in tree.nodes:
            if node.type not in ("TEX_IMAGE", "TEX_ENVIRONMENT") or node.image is None:
                continue
            name = node.get("simpler_orig") or node.image.name
            orig = bpy.data.images.get(name) or node.image
            path = proxies.get(name)
            if not path or not os.path.isfile(path):
                if node.get("simpler_orig") and orig is not None:
                    node.image = orig            # no copy at this size: back to the original
                continue
            if path not in loaded:
                im = bpy.data.images.load(path, check_existing=True)
                try:
                    im.colorspace_settings.name = orig.colorspace_settings.name
                except TypeError:
                    pass
                im.alpha_mode = orig.alpha_mode
                loaded[path] = im
            node.image = loaded[path]

# only the images the materials show: originals kept aside with a fake user (while the engine shows reduced copies)
# must not be read - decoding hundreds of 4K/8K textures for nothing took minutes (or ran out of memory)
used = {}
for tree in [m.node_tree for m in bpy.data.materials if m.node_tree] + list(bpy.data.node_groups) + \
        [w.node_tree for w in bpy.data.worlds if w.node_tree]:
    for node in tree.nodes:
        if node.type in ("TEX_IMAGE", "TEX_ENVIRONMENT") and node.image is not None:
            used[node.image.name] = node.image
images = [im for im in used.values() if im.source in ("FILE", "TILED") and im.size[0] * im.size[1] > 0]
if max_px > 0:
    big = [im for im in images if max(im.size[0], im.size[1]) > max_px]
    for i, im in enumerate(big):
        print(f"SIMPLER_PHASE textures {i + 1} {len(big)} {im.name}", flush=True)
        try:
            w, h = im.size
            k = max_px / max(w, h)
            im.scale(max(1, int(w * k)), max(1, int(h * k)))
        except Exception as exc:  # unreadable image: exported as it is
            print("SIMPLER_WARN", im.name, exc, flush=True)

# glass and water: the shadow shortcut of the path tracing (simpler/glass.py) is not for the real-time view
for _m in bpy.data.materials:
    if _m.node_tree is None:
        continue
    for _n in [n for n in _m.node_tree.nodes if n.type == "GROUP" and n.node_tree is not None and n.node_tree.name in ("Simpler Glass Shadow", "Simpler Reflected Caustics")]:
        if _n.inputs[0].is_linked:
            _src = _n.inputs[0].links[0].from_socket
            for _l in list(_n.outputs[0].links):
                _m.node_tree.links.new(_src, _l.to_socket)
        _m.node_tree.nodes.remove(_n)

# frozen water (simpler/ice.py): its nodes are for the path tracing; the view draws the ice itself (viewer.js,
# icePatch) - the inputs of the water back as they were
for _m in bpy.data.materials:
    if _m.node_tree is None:
        continue
    _g = _m.node_tree.nodes.get("simpler_ice")
    _bs = next((n for n in _m.node_tree.nodes if n.type == "BSDF_PRINCIPLED"), None)
    if _g is not None and _bs is not None:
        for _inp, _gin in (("Base Color", "BaseIn"), ("Roughness", "RoughIn"), ("Transmission Weight", "TransIn"), ("Normal", "NormalIn")):
            _gs = _g.inputs.get(_gin)
            for _l in list(_bs.inputs[_inp].links):
                _m.node_tree.links.remove(_l)
            if _gs is not None and _gs.is_linked and not _gs.links[0].from_node.name.startswith("simpler_ice"):
                _m.node_tree.links.new(_gs.links[0].from_socket, _bs.inputs[_inp])
            elif _gs is not None and _inp != "Normal":
                try:
                    _bs.inputs[_inp].default_value = _gs.default_value
                except (TypeError, AttributeError):
                    pass
    for _n in [n for n in _m.node_tree.nodes if n.name.startswith("simpler_ice")]:
        _m.node_tree.nodes.remove(_n)

# the rings of the rain on the water (simpler/ripples.py): path tracing only; the view draws them itself (viewer.js,
# ringsPatch) - whatever their normal fed gets back what fed them
for _m in bpy.data.materials:
    if _m.node_tree is None:
        continue
    _g = _m.node_tree.nodes.get("simpler_rings")
    if _g is not None:
        _src = _g.inputs.get("NormalIn")
        _frm = _src.links[0].from_socket if (_src is not None and _src.is_linked and not _src.links[0].from_node.name.startswith("simpler_rings")) else None
        for _l in list(_g.outputs["Normal"].links):
            _to = _l.to_socket
            _m.node_tree.links.remove(_l)
            if _frm is not None:
                _m.node_tree.links.new(_frm, _to)
    for _n in [n for n in _m.node_tree.nodes if n.name.startswith("simpler_rings")]:
        _m.node_tree.nodes.remove(_n)

# volumetric materials (simpler/volumetric.py): their surface is unlinked for the path tracing; the view draws the
# volume itself from the settings, which reach it as the extras of the material - so the material must be exported:
# its surface linked back for the export
for _m in bpy.data.materials:
    if _m.node_tree is None or not _m.get("simpler_volumetric"):
        continue
    _bs = next((n for n in _m.node_tree.nodes if n.type == "BSDF_PRINCIPLED"), None)
    for _o in [n for n in _m.node_tree.nodes if n.type == "OUTPUT_MATERIAL"]:
        if _bs is not None and not _o.inputs["Surface"].is_linked:
            _m.node_tree.links.new(_bs.outputs[0], _o.inputs["Surface"])

# «Sempre asciutto» on parts of a model (rain.DRY_KEY): an attribute of their points that the real-time view reads
# (viewer.js, wet shader) - the prototype merges the parts by material, the flag of the object would be lost
if part:
    for _ob in bpy.data.objects:
        # (the code of rain.dry_code: 1 no rain and no snow, 2 no rain, 3 no snow)
        _r = bool(_ob.get("simpler_dry"))
        _s = bool((_r and not _ob.get("simpler_dry_snowok")) or _ob.get("simpler_nosnow"))
        _code = 1.0 if _r and _s else 2.0 if _r else 3.0 if _s else 0.0
        if _ob.type != "MESH" or _ob.data is None or not _code:
            continue
        if _ob.data.users > 1:
            _ob.data = _ob.data.copy()
        _a = _ob.data.attributes.get("_wetdry") or _ob.data.attributes.new("_wetdry", "FLOAT", "POINT")
        _a.data.foreach_set("value", [_code] * len(_ob.data.vertices))

print("SIMPLER_PHASE export", flush=True)
bpy.ops.export_scene.gltf(
    filepath=out, export_format="GLB", use_selection=False, use_visible=False, use_active_scene=True,
    export_extras=True, export_yup=False, export_apply=False, export_cameras=False,
    export_lights=not part, export_materials="EXPORT", export_image_format="JPEG" if max_px > 0 else "AUTO",
    export_jpeg_quality=85, export_gpu_instances=True, export_attributes=bool(part),
)
print("SIMPLER_DONE", flush=True)
