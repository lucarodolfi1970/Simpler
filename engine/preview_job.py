"""Material previews: a sphere on a studio backdrop, path traced, in a separate Blender process that stays open.

Started once by the engine as:
    blender.exe --factory-startup -b --python preview_job.py -- <device>
Then reads one request per line on stdin (JSON):
    {"blend": "<file with the material>", "material": "<name>", "out": "<png>", "size": 256, "samples": 64}
and answers "SIMPLER_PREVIEW_DONE <out>" or "SIMPLER_PREVIEW_ERROR <message>".

Rendering here, not in the engine, keeps the engine's path tracing view intact: Cycles keeps the data of one scene
only, so a preview rendered in the engine would make the next view pass rebuild the whole scene.
"""
import json
import time
import math
import os
import shutil
import sys
import traceback

import bpy
from mathutils import Matrix, Vector

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))     # the simpler package (texture search, text FBX)
argv = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
device = argv[0] if argv else "CPU"



def _world_now(o):
    """(1.75.6) World matrix from the parents: Blender does not update the matrix of a piece hidden in the render."""
    m = o.matrix_basis.copy()
    if o.parent is not None:
        m = _world_now(o.parent) @ o.matrix_parent_inverse @ m
    return m

def setup():
    bpy.ops.wm.read_factory_settings(use_empty=True)
    scene = bpy.context.scene
    scene.render.engine = "CYCLES"
    scene.render.resolution_percentage = 100
    scene.render.film_transparent = False
    scene.render.image_settings.file_format = "PNG"
    cy = scene.cycles
    cy.use_adaptive_sampling = True
    cy.adaptive_threshold = 0.02
    cy.use_denoising = True
    cy.max_bounces = 16
    cy.transmission_bounces = 16
    cy.glossy_bounces = 8
    cy.caustics_refractive = True
    cy.caustics_reflective = True
    scene.view_settings.view_transform = "AgX"
    try:
        scene.view_settings.look = "AgX - Medium High Contrast"
    except TypeError:
        pass
    if device != "CPU":
        try:
            prefs = bpy.context.preferences.addons["cycles"].preferences
            prefs.compute_device_type = device
            (prefs.refresh_devices if hasattr(prefs, "refresh_devices") else prefs.get_devices)()
            for d in prefs.devices:
                d.use = d.type == device
            cy.device = "GPU" if any(d.use for d in prefs.devices) else "CPU"
            if cy.device == "GPU":
                cy.denoiser = "OPTIX" if device == "OPTIX" else "OPENIMAGEDENOISE"
        except Exception:
            cy.device = "CPU"
    # video memory: nothing kept on the card between two pictures (persistent data would keep every texture and
    # mesh of every model rendered so far), and textures read at most 1024 px - the pictures are 256-512 px
    scene.render.use_persistent_data = False
    scene.render.use_simplify = True
    cy.texture_limit_render = "1024"
    cy.texture_limit = "1024"
    scene.render.simplify_subdivision_render = 6
    scene.render.simplify_child_particles_render = 1.0

    world = bpy.data.worlds.new("Preview World")
    world.use_nodes = True
    bg = world.node_tree.nodes["Background"]
    bg.inputs[0].default_value = (0.30, 0.32, 0.36, 1)
    bg.inputs[1].default_value = 0.5
    scene.world = world

    # sphere, smooth
    import bmesh
    me = bpy.data.meshes.new("Preview Sphere")
    bm = bmesh.new()
    bm.loops.layers.uv.new("UVMap")       # calc_uvs fills a UV layer only if there is one
    bmesh.ops.create_uvsphere(bm, u_segments=96, v_segments=48, radius=0.5, calc_uvs=True)
    bm.to_mesh(me)
    bm.free()
    for p in me.polygons:
        p.use_smooth = True
    sphere = bpy.data.objects.new("Preview Sphere", me)
    sphere.location = (0, 0, 0.5)
    scene.collection.objects.link(sphere)

    # backdrop with a checker pattern: transparency, refraction and reflections are readable
    floor_me = bpy.data.meshes.new("Preview Floor")
    floor_me.from_pydata([(-6, -6, 0), (6, -6, 0), (6, 6, 0), (-6, 6, 0)], [], [(0, 1, 2, 3)])
    floor_me.uv_layers.new()
    floor = bpy.data.objects.new("Preview Floor", floor_me)
    fm = bpy.data.materials.new("Preview Floor")
    fm.use_nodes = True
    nt = fm.node_tree
    chk = nt.nodes.new("ShaderNodeTexChecker")
    chk.inputs["Scale"].default_value = 24
    chk.inputs["Color1"].default_value = (0.32, 0.33, 0.36, 1)
    chk.inputs["Color2"].default_value = (0.14, 0.15, 0.17, 1)
    bsdf = nt.nodes.get("Principled BSDF")
    nt.links.new(chk.outputs["Color"], bsdf.inputs["Base Color"])
    bsdf.inputs["Roughness"].default_value = 0.6
    floor_me.materials.append(fm)
    scene.collection.objects.link(floor)

    for name, loc, energy, size in (("Key", (-1.6, -1.4, 2.4), 300, 1.2), ("Rim", (1.8, 1.6, 1.8), 200, 1.0)):
        ld = bpy.data.lights.new("Preview " + name, "AREA")
        ld.energy, ld.size = energy, size
        lo = bpy.data.objects.new("Preview " + name, ld)
        lo.location = loc
        lo.rotation_euler = (Vector((0, 0, 0.5)) - Vector(loc)).to_track_quat("-Z", "Y").to_euler()
        scene.collection.objects.link(lo)
    # a small, strong spot: caustics and dispersion show on the floor
    sd = bpy.data.lights.new("Preview Spot", "SPOT")
    sd.energy, sd.spot_size, sd.shadow_soft_size = 120, math.radians(35), 0.02
    so = bpy.data.objects.new("Preview Spot", sd)
    so.location = (1.2, -0.8, 2.6)
    so.rotation_euler = (Vector((0, 0, 0.5)) - so.location).to_track_quat("-Z", "Y").to_euler()
    scene.collection.objects.link(so)

    cd = bpy.data.cameras.new("Preview Camera")
    cd.lens = 70
    cam = bpy.data.objects.new("Preview Camera", cd)
    cam.location = (0, -3.0, 1.35)
    cam.rotation_euler = (Vector((0, 0, 0.48)) - cam.location).to_track_quat("-Z", "Y").to_euler()
    scene.collection.objects.link(cam)
    scene.camera = cam
    return scene, sphere


# ---------------------------------------------------------------- models of the library
# {"kind": "model", "blend": objects written by the engine, "save": model.blend, "textures": folder, "out": png}

def _world(o):
    """World matrix of an object just read from a file (not in a scene yet: matrix_world is not computed)."""
    m = o.matrix_basis.copy()
    while o.parent is not None:
        m = o.parent.matrix_basis @ o.matrix_parent_inverse @ m
        o = o.parent
    return m


def _new(before):
    return {k: [x for x in getattr(bpy.data, k) if x not in v] for k, v in before.items()}


def render_model(scene, sphere, req):
    kinds = ("objects", "meshes", "materials", "images", "node_groups", "lights", "cameras", "curves", "libraries")
    before = {k: set(getattr(bpy.data, k)) for k in kinds}
    with bpy.data.libraries.load(req["blend"], link=False) as (src, dst):
        file_names = list(src.objects)
        dst.objects = list(src.objects)
        dst.images = list(src.images)          # (the originals of textures shown as reduced copies)
        dst.materials = [n for n in src.materials if n.startswith("·orig·")]   # hidden originals of the materials
    origs = [m for m in dst.materials if m is not None]
    loaded = [(n, o) for n, o in zip(file_names, dst.objects) if o is not None]
    obs = [o for _, o in loaded]
    norm = cam = None
    try:
        # only what was saved: a parent of the saved pieces (e.g. the floor they were placed in) comes along with
        # them in the file - it goes away, the pieces keep their place
        name_of = {o: n for n, o in loaded}
        keep = set(req.get("keep") or [])
        tops = set(req.get("keepTops") or [])
        if not keep and tops:
            for n, o in loaded:
                p = o
                while p is not None:
                    if name_of.get(p) in tops:
                        keep.add(n)
                        break
                    p = p.parent
        if keep:
            for n, o in loaded:
                if n in keep and o.parent is not None and name_of.get(o.parent) not in keep:
                    world = _world(o)
                    o.parent = None
                    o.matrix_basis = world
            for n, o in loaded:
                if n not in keep:
                    bpy.data.objects.remove(o, do_unlink=True)
            obs = [o for n, o in loaded if n in keep]
        # the scale chosen in the import wizard (a model saved in the wrong units: a person 7 cm tall)
        _scale_tops(obs, req.get("scale"), basis=True)
        turned = _orient_tops(obs, req.get("orient"))
        added = _new(before)
        # 1. image nodes back to the original textures (the engine's views may show reduced copies)
        for m in added["materials"] + added["node_groups"]:
            tree = m.node_tree if hasattr(m, "node_tree") else m
            if tree is None:
                continue
            for node in tree.nodes:
                orig = node.get("simpler_orig")
                if orig and bpy.data.images.get(orig) is not None:
                    node.image = bpy.data.images[orig]
                    del node["simpler_orig"]
        # 1b. (1.75.8) the rain and snow of the scene (their nodes in the materials, rain.py PREFIX "simpler_wet") stay
        # in the scene: the model in the library and its thumbnail are dry - the Qashqai's thumbnail came out snowy
        for m in added["materials"]:
            tree = m.node_tree
            if tree is None:
                continue
            wet = [n for n in tree.nodes if n.name.startswith("simpler_wet")]
            for n in wet:
                tree.nodes.remove(n)
            if wet and "simpler_wet_sig" in m:
                del m["simpler_wet_sig"]
        # 2. texture files copied next to the model (the model keeps working when the originals move)
        os.makedirs(req["textures"], exist_ok=True)
        used = set()
        for im in added["images"]:
            if im.users and im.packed_file is None and im.source == "MOVIE" and im.filepath.lower().endswith(".gif"):
                # (1.78.4) a GIF (a cut-out mask of some plant exports): Blender opens it as a movie, it was not copied
                # and the real-time view had no picture (solid leaf cards). A PNG of it next to the model instead.
                gif = bpy.path.abspath(im.filepath)
                if os.path.isfile(gif):
                    from simpler import stillgif
                    png = os.path.join(req["textures"], os.path.splitext(os.path.basename(gif))[0] + ".png")
                    if os.path.isfile(png) or stillgif.to_png(gif, png):
                        im.source = "FILE"
                        im.filepath = png
                        im.reload()
                        used.add(os.path.normcase(png))
                        continue
            if im.users == 0 or im.packed_file is not None or im.source not in ("FILE", "TILED"):
                continue
            path = bpy.path.abspath(im.filepath)
            if not os.path.isfile(path):
                continue
            base, ext = os.path.splitext(os.path.basename(path))
            dest, n = os.path.join(req["textures"], base + ext), 1
            while os.path.normcase(dest) in used or (os.path.isfile(dest) and os.path.getsize(dest) != os.path.getsize(path)):
                n += 1
                dest = os.path.join(req["textures"], f"{base}_{n}{ext}")
            used.add(os.path.normcase(dest))
            if not os.path.isfile(dest):
                shutil.copy2(path, dest)
            im.filepath = dest
        tmp = req["save"] + ".part"
        bpy.data.libraries.write(tmp, set(obs) | set(origs), fake_user=True, path_remap="RELATIVE", compress=True)
        os.replace(tmp, req["save"])

        # 3. thumbnail: axonometric view of the model scaled to 1 m, filling the square, studio lights, on the
        #    checker backdrop of the material previews
        for o in obs:
            scene.collection.objects.link(o)
        bpy.context.view_layer.update()
        lo, hi = Vector((1e30,) * 3), Vector((-1e30,) * 3)
        # the box of what is drawn: empties (helpers, lights of other renderers) count only when there is nothing else
        geo = [o for o in obs if o.type in ("MESH", "CURVE", "SURFACE", "FONT", "META", "CURVES")]
        geo = [o for o in geo if not o.hide_render] or geo      # (1.75.6: hidden pieces are not in the picture)
        for o in geo or obs:
            pts = [_world_now(o) @ Vector(c) for c in o.bound_box] if o in geo else [_world_now(o).translation]
            for w in pts:
                lo = Vector(map(min, lo, w)); hi = Vector(map(max, hi, w))
        if hi.x < lo.x:
            lo, hi = Vector((-0.5, -0.5, 0)), Vector((0.5, 0.5, 1))
        if req.get("orient") and req.get("info"):
            # the new size and the rotation applied (the engine turns the models of the distributions the same way)
            import json as _json
            inf = {}
            try:
                with open(req["info"], encoding="utf-8") as fh:
                    inf = _json.load(fh)
            except (OSError, ValueError):
                pass
            inf["sizeCm"] = [round((h - l) * 100, 2) for l, h in zip(lo, hi)]
            inf["orientRot"] = [list(r) for r in (turned or Matrix.Identity(3))]
            inf["orientSerial"] = str(time.time())
            with open(req["info"], "w", encoding="utf-8") as fh:
                _json.dump(inf, fh)
        size = max(hi - lo)
        k = 1.0 / max(size, 1e-6)
        norm = bpy.data.objects.new("Preview Model", None)
        scene.collection.objects.link(norm)
        for o in obs:
            if o.parent is None:
                o.parent = norm
        norm.scale = (k, k, k)
        norm.location = (-(lo.x + hi.x) / 2 * k, -(lo.y + hi.y) / 2 * k, -lo.z * k)
        bpy.context.view_layer.update()
        ext = (hi - lo) * k
        target = Vector((0, 0, ext.z / 2))
        az, el = math.radians(-35), math.radians(28)       # from the front right, a little above
        d = Vector((math.sin(-az) * math.cos(el), -math.cos(az) * math.cos(el), math.sin(el)))
        cd = bpy.data.cameras.new("Preview Model Camera")
        cd.type = "ORTHO"
        cam = bpy.data.objects.new("Preview Model Camera", cd)
        cam.location = target + d * 10
        cam.rotation_euler = (-d).to_track_quat("-Z", "Y").to_euler()
        scene.collection.objects.link(cam)
        bpy.context.view_layer.update()
        right = cam.matrix_world.to_3x3() @ Vector((1, 0, 0))
        up = cam.matrix_world.to_3x3() @ Vector((0, 1, 0))
        corners = [Vector((x, y, z)) for x in (-ext.x / 2, ext.x / 2) for y in (-ext.y / 2, ext.y / 2) for z in (0, ext.z)]
        w = max(c.dot(right) for c in corners) - min(c.dot(right) for c in corners)
        h = max(c.dot(up) for c in corners) - min(c.dot(up) for c in corners)
        cx = (max(c.dot(right) for c in corners) + min(c.dot(right) for c in corners)) / 2
        cy = (max(c.dot(up) for c in corners) + min(c.dot(up) for c in corners)) / 2
        cam.location = target + d * 10 + right * (cx - target.dot(right)) + up * (cy - target.dot(up))
        cd.ortho_scale = max(w, h) * 1.06          # the object fills the square
        cd.clip_end = 100
        old_cam, scene.camera = scene.camera, cam
        floor = bpy.data.objects["Preview Floor"]
        spot = bpy.data.objects["Preview Spot"]
        sphere.hide_render = True
        spot.hide_render = True
        size_px = int(req.get("size", 256))
        scene.render.resolution_x = scene.render.resolution_y = size_px
        scene.cycles.samples = int(req.get("samples", 64))
        scene.render.filepath = req["out"]
        try:
            bpy.ops.render.render(write_still=True)
        finally:
            scene.camera = old_cam
            sphere.hide_render = False
            spot.hide_render = False
            scene.render.image_settings.color_mode = "RGB"
    finally:
        # everything that came with the model goes away
        for o in obs + [x for x in (norm, cam) if x is not None]:
            if o.name in bpy.data.objects:
                bpy.data.objects.remove(o, do_unlink=True)
        added = _new(before)
        for k in ("objects", "meshes", "materials", "node_groups", "lights", "cameras", "curves", "images"):
            for x in added[k]:
                try:
                    getattr(bpy.data, k).remove(x)
                except (ReferenceError, RuntimeError):
                    pass
        for lib in list(bpy.data.libraries):
            bpy.data.libraries.remove(lib)


def _volume_preview(sphere, mat):
    """A volumetric material (simpler/volumetric.py): the sphere filled as the engine fills a model (Mesh to Volume,
    the band of «Morbidezza»), with light scattered a few times. None for any other material."""
    try:
        s = json.loads(mat.get("simpler_volumetric") or "{}")
    except ValueError:
        s = {}
    scene = bpy.context.scene
    scene.cycles.volume_bounces = 4 if s.get("on") else 0
    scene.cycles.max_bounces = max(scene.cycles.max_bounces, 4)
    if not s.get("on"):
        return None
    g = bpy.data.node_groups.new("Simpler Volume preview", "GeometryNodeTree")
    g.interface.new_socket("Geometry", in_out="INPUT", socket_type="NodeSocketGeometry")
    g.interface.new_socket("Geometry", in_out="OUTPUT", socket_type="NodeSocketGeometry")
    gi, go = g.nodes.new("NodeGroupInput"), g.nodes.new("NodeGroupOutput")
    mv = g.nodes.new("GeometryNodeMeshToVolume")
    mv.inputs["Resolution Mode"].default_value = "Size"
    mv.inputs["Voxel Size"].default_value = 1.0 / (48 + 112 * float(s.get("detail", 0.5)))
    mv.inputs["Interior Band Width"].default_value = max(2.0 * mv.inputs["Voxel Size"].default_value, float(s.get("soft", 0.6)) * 0.5)
    sm = g.nodes.new("GeometryNodeSetMaterial")
    sm.inputs["Material"].default_value = mat
    g.links.new(gi.outputs[0], mv.inputs["Mesh"])
    g.links.new(mv.outputs["Volume"], sm.inputs["Geometry"])
    g.links.new(sm.outputs["Geometry"], go.inputs[0])
    mod = sphere.modifiers.new("Simpler Volume", "NODES")
    mod.node_group = g
    sphere["simpler_vol_size"] = 1.0                   # (the puffs are a share of the model: here 1 m)
    return mod


def _interior_preview(scene, sphere, mat):
    """(1.79.0, Luca: «se il materiale è di tipo Interni possiamo mettere come miniatura l'anteprima della stanza? la
    sfera non fa capire nulla») an «Interni» material: one window of the size of its rooms, seen a little from the side
    (the depth of the room shows), instead of the sphere. Returns the function that puts the studio back, or None."""
    try:
        it = (json.loads(mat.get("simpler_mat") or "{}").get("interior") or {})
    except (TypeError, ValueError):
        it = {}
    if not it.get("enabled"):
        return None
    W = max(0.2, float(it.get("roomW", 4.0)))
    H = max(0.2, float(it.get("roomH", 3.0)))
    me = bpy.data.meshes.new("Preview Window")
    me.from_pydata([(-W / 2, 0, 0), (W / 2, 0, 0), (W / 2, 0, H), (-W / 2, 0, H)], [], [(0, 1, 2, 3)])
    me.uv_layers.new()
    ob = bpy.data.objects.new("Preview Window", me)
    # (what matedit.interior_pass writes on the objects: the corner the rooms start from, the scale, the axis up)
    for k, v in (("simpler_bb_x", -W / 2), ("simpler_bb_y", 0.0), ("simpler_bb_z", 0.0), ("simpler_sc_x", 1.0),
                 ("simpler_sc_y", 1.0), ("simpler_sc_z", 1.0), ("simpler_up", 3.0), ("simpler_up_s", 1.0)):
        ob[k] = v
    me.materials.append(mat)
    scene.collection.objects.link(ob)
    # (the studio's floor and sphere, and its lamps: on the glass they were a white square)
    hidden = [o for o in scene.objects if o is not ob and o.type in ("MESH", "LIGHT") and not o.hide_render]
    for o in hidden:
        o.hide_render = True
    cam = scene.camera
    keep = (cam.matrix_world.copy(), cam.data.lens)
    cam.data.lens = 50
    d = (H / 2) / math.tan(math.atan(18.0 / 50.0)) * 1.02          # (the window fills the picture up and down)
    cam.location = (W * 0.16, -d, H * 0.56)
    cam.rotation_euler = (Vector((0, 0, H / 2)) - cam.location).to_track_quat("-Z", "Y").to_euler()

    def restore():
        for o in hidden:
            o.hide_render = False
        cam.matrix_world = keep[0]
        cam.data.lens = keep[1]
        me.materials.clear()
        bpy.data.objects.remove(ob)
        bpy.data.meshes.remove(me)
    return restore


def render(scene, sphere, req):
    before_mats = set(bpy.data.materials)
    before_imgs = set(bpy.data.images)
    before_groups = set(bpy.data.node_groups)
    with bpy.data.libraries.load(req["blend"], link=False) as (src, dst):
        dst.materials = [n for n in src.materials if n == req["material"]] or src.materials[:1]
    mat = dst.materials[0] if dst.materials else None
    if mat is None:
        raise RuntimeError("material not found in " + req["blend"])
    sphere.data.materials.clear()
    sphere.data.materials.append(mat)
    vol = _volume_preview(sphere, mat)
    back = _interior_preview(scene, sphere, mat)
    size = int(req.get("size", 256))
    scene.render.resolution_x = scene.render.resolution_y = size
    scene.cycles.samples = int(req.get("samples", 64))
    scene.render.filepath = req["out"]
    try:
        bpy.ops.render.render(write_still=True)
    finally:
        if back is not None:
            back()
        if vol is not None:
            sphere.modifiers.remove(vol)
        sphere.data.materials.clear()
        # what came with this material goes away (the next request brings its own)
        for m in set(bpy.data.materials) - before_mats:
            bpy.data.materials.remove(m)
        for g in set(bpy.data.node_groups) - before_groups:
            if g.users == 0:
                bpy.data.node_groups.remove(g)
        for im in set(bpy.data.images) - before_imgs:
            if im.users == 0:
                bpy.data.images.remove(im)
        for lib in list(bpy.data.libraries):
            bpy.data.libraries.remove(lib)


# ---------------------------------------------------------------- a model file straight into the library
# {"kind": "import", "path": model file, "save", "textures", "out", "info"}: imported here (never in the scene the user
# is working on: no flicker, no wait), cleaned (no cameras, lights or rigs of the file), textures looked for next to
# the file, then the same steps as a model saved from the scene (render_model).

IMPORTERS = {
    ".fbx": lambda p: bpy.ops.import_scene.fbx(filepath=p, use_custom_normals=True, use_image_search=True),
    ".glb": lambda p: bpy.ops.import_scene.gltf(filepath=p),
    ".gltf": lambda p: bpy.ops.import_scene.gltf(filepath=p),
    ".obj": lambda p: bpy.ops.wm.obj_import(filepath=p),
    ".usd": lambda p: bpy.ops.wm.usd_import(filepath=p),
    ".usda": lambda p: bpy.ops.wm.usd_import(filepath=p),
    ".usdc": lambda p: bpy.ops.wm.usd_import(filepath=p),
    ".usdz": lambda p: bpy.ops.wm.usd_import(filepath=p),
}


def _read_model(path, ext, before):
    """The objects of a model file, without cameras, lights, rigs and empty helpers (in the current scene)."""
    from simpler import fbx_legacy
    if ext == ".fbx":
        fbx_legacy.import_fbx(path)
    else:
        try:
            result = IMPORTERS[ext](path)
        except Exception as exc:
            raise RuntimeError("import non riuscito: " + fbx_legacy._short(exc)) from exc
        if "FINISHED" not in result:
            raise RuntimeError("import non riuscito")
    new = [o for o in bpy.data.objects if o not in before["objects"]]
    # cameras, lights and rigs of the file are not part of the model (the pieces keep their place)
    bpy.context.view_layer.update()
    drop = [o for o in new if o.type in ("CAMERA", "LIGHT", "ARMATURE")]
    shapes = set()
    for o in new:
        if o.type == "ARMATURE" and o.pose is not None:
            shapes.update(pb.custom_shape for pb in o.pose.bones if pb.custom_shape is not None)
    for o in new:
        if o.parent in drop or o.parent in shapes:
            w = o.matrix_world.copy()
            o.parent = None
            o.matrix_world = w
    keep = [o for o in new if o not in drop and o not in shapes]
    # empties with nothing under them are what is left of lights the importer does not know (V-Ray, Corona
    # lights in an FBX become empties) or of helpers: nothing to see, and far from the model they made it look
    # tiny in its thumbnail
    while True:
        ks = set(keep)
        leaf = [o for o in keep if o.type == "EMPTY" and o.instance_type == "NONE" and not any(c in ks for c in o.children)]
        if not leaf or len(leaf) == len(keep):
            break
        keep = [o for o in keep if o not in leaf]
    return keep


def probe_model(scene, sphere, req):
    """{"kind": "probe", "path", "out"}: the size of a model file before importing it (the import wizard shows it
    on its row: a person 7 cm tall, a house 30 km wide - the scale is chosen before, not after)."""
    path = req["path"]
    ext = os.path.splitext(path)[1].lower()
    if ext not in IMPORTERS:
        raise RuntimeError("formato non supportato: " + ext)
    kinds = ("objects", "meshes", "materials", "images", "node_groups", "lights", "cameras", "curves", "armatures", "actions", "collections")
    before = {k: set(getattr(bpy.data, k)) for k in kinds}
    try:
        keep = _read_model(path, ext, before)
        bpy.context.view_layer.update()
        lo, hi = Vector((1e30,) * 3), Vector((-1e30,) * 3)
        meshes = 0
        for o in keep:
            if o.type == "MESH":
                meshes += 1
                for c in o.bound_box:
                    w = _world_now(o) @ Vector(c)
                    lo = Vector(map(min, lo, w)); hi = Vector(map(max, hi, w))
        size = [round((h - l) * 100, 3) for l, h in zip(lo, hi)] if hi.x >= lo.x else [0, 0, 0]
        with open(req["out"], "w", encoding="utf-8") as f:
            json.dump({"sizeCm": size, "objects": len(keep), "meshes": meshes}, f)
    finally:
        for k in kinds:
            for x in [x for x in getattr(bpy.data, k) if x not in before[k]]:
                try:
                    getattr(bpy.data, k).remove(x)
                except (ReferenceError, RuntimeError):
                    pass


def import_model(scene, sphere, req):
    import tempfile
    from simpler import fbx_legacy, textures
    path = req["path"]
    ext = os.path.splitext(path)[1].lower()
    if ext not in IMPORTERS:
        raise RuntimeError("formato non supportato: " + ext)
    kinds = ("objects", "meshes", "materials", "images", "node_groups", "lights", "cameras", "curves", "armatures", "actions", "collections")
    before = {k: set(getattr(bpy.data, k)) for k in kinds}
    tmp = req["save"] + ".src.blend"
    try:
        keep = _read_model(path, ext, before)
        if not keep:
            raise RuntimeError("il file non contiene oggetti")
        imgs = [i for i in bpy.data.images if i not in before["images"]]
        textures.resolve(imgs, textures.search_folders_for(path))
        bpy.context.view_layer.update()
        keep_set = set(keep)
        if req.get("split"):
            # a collection: every top object of the file (with its children) is a model of its own
            tops = [o for o in keep if o.parent not in keep_set]
            groups = []
            for t in sorted(tops, key=lambda o: o.name):
                objs = [t] + [c for c in t.children_recursive if c in keep_set]
                if any(o.type in ("MESH", "CURVE", "SURFACE", "FONT", "META", "CURVES") for o in objs):
                    groups.append((t.name, objs))
            if not groups:
                raise RuntimeError("il file non contiene oggetti")
        else:
            groups = [(None, keep)]
        print(f"SIMPLER_PREVIEW_PROGRESS 0\t{len(groups)}\t", flush=True)
        jobs = []
        for k, (gname, objs) in enumerate(groups):
            if req.get("merge"):
                from simpler import merge
                objs = merge.merge_objects(objs, gname or (req.get("entry") or {}).get("name"))
            _bake_rotation(objs)            # (the file's own turn into the meshes: the model's up is Z)
            _set_pivot(objs, req.get("pivot") or "keep")
            _scale_tops(objs, req.get("scale"))
            bpy.context.view_layer.update()
            lo, hi = Vector((1e30,) * 3), Vector((-1e30,) * 3)
            for o in objs:
                if o.type == "MESH":
                    for c in o.bound_box:
                        w = o.matrix_world @ Vector(c)
                        lo = Vector(map(min, lo, w)); hi = Vector(map(max, hi, w))
            size = [round((h - l) * 100, 2) for l, h in zip(lo, hi)] if hi.x >= lo.x else [0, 0, 0]
            if req.get("split"):
                pid = f"{req['baseId']}_{k + 1:03d}"
                pdir = os.path.join(req["partsDir"], pid)
                os.makedirs(pdir, exist_ok=True)
                part = dict(req, save=os.path.join(pdir, "model.blend"), textures=os.path.join(pdir, "textures"),
                            out=os.path.join(pdir, "thumb.png"), info=os.path.join(pdir, "info.json"))
            else:
                pid, part = None, dict(req)
            if part.get("info"):
                with open(part["info"], "w", encoding="utf-8") as f:
                    json.dump({"sizeCm": size, "objects": [o.name for o in objs], "source": path}, f)
            ptmp = part["save"] + ".src.blend"
            bpy.data.libraries.write(ptmp, set(objs), fake_user=True, path_remap="ABSOLUTE", compress=False)
            jobs.append((pid, gname, size, part, ptmp, [o.name for o in objs]))
    finally:
        # everything the import brought goes away: this process stays clean for the next request
        for k in kinds:
            for x in [x for x in getattr(bpy.data, k) if x not in before[k]]:
                try:
                    getattr(bpy.data, k).remove(x)
                except (ReferenceError, RuntimeError):
                    pass
    done = 0
    for pid, gname, size, part, ptmp, names in jobs:
        print(f"SIMPLER_PREVIEW_PROGRESS {done}\t{len(jobs)}\t{gname or ''}", flush=True)
        try:
            render_model(scene, sphere, dict(part, blend=ptmp, keep=names, scale=1.0))   # (already scaled above)
            if pid:
                entry = dict(req.get("entry") or {}, id=pid, name=_part_name(gname, req), sizeCm=size, rev=str(int(time.time())))
                epath = os.path.join(req["partsDir"], pid + ".json")
                with open(epath + ".part", "w", encoding="utf-8") as f:
                    json.dump(entry, f, indent=1)
                os.replace(epath + ".part", epath)
        finally:
            try:
                os.remove(ptmp)
            except OSError:
                pass
        done += 1
    print(f"SIMPLER_PREVIEW_PROGRESS {done}\t{len(jobs)}\t", flush=True)
    if req.get("split"):
        # the placeholder of the whole file leaves the library: the parts are there instead
        import shutil
        shutil.rmtree(os.path.join(req["partsDir"], req["baseId"]), ignore_errors=True)
        try:
            os.remove(os.path.join(req["partsDir"], req["baseId"] + ".json"))
        except OSError:
            pass


def _part_name(gname, req):
    """Name of a model taken out of a collection: the object's name, without Blender's .001 suffixes."""
    import re
    n = re.sub(r"\.\d{3}$", "", gname or "").strip()
    return n or (req.get("entry") or {}).get("name") or "Modello"


def _footprint(objs):
    """World points of the model's meshes (at most ~20 000 per mesh): numpy array (n, 3), or None."""
    import numpy as np
    pts = []
    for o in objs:
        if o.type != "MESH" or o.data is None or not len(o.data.vertices):
            continue
        n = len(o.data.vertices)
        co = np.empty(n * 3, dtype=np.float64)
        o.data.vertices.foreach_get("co", co)
        co = co.reshape(n, 3)
        if n > 20000:
            co = co[:: n // 20000]
        w = np.array(_world(o))
        pts.append(co @ w[:3, :3].T + w[:3, 3])
    return np.concatenate(pts) if pts else None


def _hull2d(p):
    """Convex hull of 2D points (monotone chain)."""
    import numpy as np
    p = np.unique(np.round(p, 6), axis=0)
    if len(p) < 3:
        return p
    p = p[np.lexsort((p[:, 1], p[:, 0]))]

    def half(pts):
        out = []
        for q in pts:
            while len(out) >= 2 and (out[-1][0] - out[-2][0]) * (q[1] - out[-2][1]) - (out[-1][1] - out[-2][1]) * (q[0] - out[-2][0]) <= 0:
                out.pop()
            out.append(q)
        return out
    lower, upper = half(p), half(p[::-1])
    return np.array(lower[:-1] + upper[:-1])


def _bake_rotation(objs):
    """(Luca: «se prendo il gizmo per appoggiare la pianta al pavimento ruota di 90 gradi») the turn a file gives to
    its top objects (an OBJ written with Y up: 90° on X, kept on the object) goes into the meshes, the objects keep
    no rotation: the model stands as before and its own up is the vertical (Z) again - the view straightens a model
    by its up when it rests on a surface, and a lying «up» laid it on its side. Meshes shared by several objects are
    left as they are. Returns how many objects were changed."""
    from mathutils import Matrix
    objset = set(objs)
    done = 0
    for o in [o for o in objs if o.parent not in objset]:
        if o.type != "MESH" or o.data is None or o.data.users > 1 or o.data.library is not None:
            continue
        loc, rot, sca = o.matrix_basis.decompose()
        if rot.angle < 1e-6:
            continue
        S = Matrix.Diagonal((sca.x, sca.y, sca.z, 1.0))
        if min(abs(sca.x), abs(sca.y), abs(sca.z)) < 1e-12:
            continue
        M = S.inverted() @ rot.to_matrix().to_4x4() @ S          # (T R S v = T S (S⁻¹ R S) v)
        o.data.transform(M)
        o.data.update()
        o.matrix_basis = Matrix.Translation(loc) @ S
        for c in o.children:                                    # (the children stay where they were)
            c.matrix_parent_inverse = M @ c.matrix_parent_inverse
        done += 1
    return done


def _orient_tops(objs, orient):
    """The model turned (Libreria ▸ Raddrizza / Gira di 90° / 180°, or as it was turned in the scene), around the
    centre of its base, which stays where it was. Its front goes along the red X axis. Returns the 3x3 rotation."""
    if not orient:
        return None
    import math
    import numpy as np
    from mathutils import Matrix, Quaternion, Vector
    if orient.get("mode") == "bake":
        # Libreria ▸ Orientamento ▸ «Correggi gli assi»: the model does not move, only its axes are straightened
        print(f"SIMPLER_AXES {_bake_rotation(objs)}", flush=True)
        return Matrix.Identity(3)
    objset = set(objs)
    tops = [o for o in objs if o.parent not in objset]
    pts = _footprint(objs)
    if pts is None or not tops:
        return None
    mode = orient.get("mode")
    if mode == "yaw":
        r = Matrix.Rotation(math.radians(float(orient.get("deg") or 0)), 3, "Z")
    elif mode == "auto":
        # the smallest rectangle around the model seen from above; its long side on X
        hull = _hull2d(pts[:, :2])
        best = (float("inf"), 0.0, 0.0, 0.0)
        for i in range(len(hull)):
            e = hull[(i + 1) % len(hull)] - hull[i]
            if not e.any():
                continue
            t = math.atan2(e[1], e[0])
            c, s = math.cos(-t), math.sin(-t)
            rx = hull[:, 0] * c - hull[:, 1] * s
            ry = hull[:, 0] * s + hull[:, 1] * c
            w, l = rx.max() - rx.min(), ry.max() - ry.min()
            if w * l < best[0]:
                best = (w * l, t, w, l)
        _a, t, w, l = best
        if l > w:
            t += math.pi / 2
        yaw = -t
        while yaw <= -math.pi / 2:
            yaw += math.pi
        while yaw > math.pi / 2:
            yaw -= math.pi
        r = Matrix.Rotation(yaw, 3, "Z")
    elif mode == "abs":
        # the rotation the single top object has in the scene
        cur = _world(tops[0]).to_quaternion()
        r = Quaternion(orient.get("q")).to_matrix() @ cur.to_matrix().inverted()
    elif mode == "delta":
        r = Quaternion(orient.get("q")).to_matrix()
    else:
        return None
    c0 = Vector(((pts[:, 0].min() + pts[:, 0].max()) / 2, (pts[:, 1].min() + pts[:, 1].max()) / 2, pts[:, 2].min()))
    m = Matrix.Translation(c0) @ r.to_4x4() @ Matrix.Translation(-c0)
    for t_ in tops:
        t_.matrix_basis = m @ t_.matrix_basis
    p2 = _footprint(objs)
    c1 = Vector(((p2[:, 0].min() + p2[:, 0].max()) / 2, (p2[:, 1].min() + p2[:, 1].max()) / 2, p2[:, 2].min()))
    shift = Matrix.Translation(c0 - c1)
    for t_ in tops:
        t_.matrix_basis = shift @ t_.matrix_basis
    return r


def _scale_tops(objs, factor, basis=False):
    """Scales the model around the world origin (its pivot after _set_pivot: the base stays on the ground)."""
    from mathutils import Matrix
    try:
        f = float(factor or 1.0)
    except (TypeError, ValueError):
        return
    if f <= 0 or abs(f - 1.0) < 1e-9:
        return
    objset = set(objs)
    for t in [o for o in objs if o.parent not in objset]:
        if basis:
            t.matrix_basis = Matrix.Scale(f, 4) @ t.matrix_basis        # (just read from a file: no scene yet)
        else:
            t.matrix_world = Matrix.Scale(f, 4) @ t.matrix_world


def _set_pivot(objs, mode):
    """The model's origin where the user wants it, and there at the world origin (so the gizmo "Origine" and the
    rotations of the inserted model use it). base: centre of the bottom of the model; center: centre of the box;
    keep: as in the file."""
    from mathutils import Matrix
    if mode not in ("base", "center"):
        return
    bpy.context.view_layer.update()
    lo, hi = Vector((1e30,) * 3), Vector((-1e30,) * 3)
    for o in [o for o in objs if o.type == "MESH" and not o.hide_render] or objs:
        if o.type == "MESH":
            for c in o.bound_box:
                w = _world_now(o) @ Vector(c)
                lo = Vector(map(min, lo, w)); hi = Vector(map(max, hi, w))
    if hi.x < lo.x:
        return
    p = Vector(((lo.x + hi.x) / 2, (lo.y + hi.y) / 2, lo.z if mode == "base" else (lo.z + hi.z) / 2))
    objset = set(objs)
    tops = [o for o in objs if o.parent not in objset]
    if len(tops) == 1:
        t = tops[0]
        d = t.matrix_world.inverted() @ p                      # the pivot in the object's own space
        if t.data is not None and hasattr(t.data, "transform"):
            if t.data.users > 1:
                t.data = t.data.copy()
            t.data.transform(Matrix.Translation(-d))
        for c in t.children:
            c.matrix_parent_inverse = Matrix.Translation(-d) @ c.matrix_parent_inverse
        mw = t.matrix_world @ Matrix.Translation(d)          # origin on the pivot...
        mw.translation = Vector((0.0, 0.0, 0.0))              # ...and the pivot at the world origin
        t.matrix_world = mw
    else:
        for t in tops:                                        # several pieces: the group made at insertion is the pivot
            mw = t.matrix_world.copy()
            mw.translation -= p
            t.matrix_world = mw


# {"kind": "sky", "blend": file with the world, "out": .bin, "final": .bin, "w": 1024, "h": 512}: a 360° picture of the
# sky (equirectangular, half floats RGBA, laid out for three.js) for the real-time view, and a few numbers (.json)
_sky = {"scene": None}


def bake_sky(_scene, _sphere, req):
    import numpy as np
    with bpy.data.libraries.load(req["blend"]) as (src, dst):
        dst.worlds = list(src.worlds)
    world = dst.worlds[0]
    for n in (world.node_tree.nodes if world.node_tree else []):
        if n.type == "TEX_SKY":
            n.sun_disc = False                        # the view draws the sun itself; the light comes from the Sun lamp
        if n.name == "simpler_camera_mix":           # HDRI (hdri.py): the picture without its sun, as the light sees it
            for l in list(n.inputs[0].links):
                world.node_tree.links.remove(l)
            n.inputs[0].default_value = 0.0
    sc = _sky["scene"]
    if sc is None or sc.name not in bpy.data.scenes:
        sc = bpy.data.scenes.new("Simpler Sky Bake")
        sc.render.engine = "CYCLES"
        cd = bpy.data.cameras.new("Simpler Sky Bake")
        cd.type = "PANO"
        try:
            cd.panorama_type = "EQUIRECTANGULAR"
        except (AttributeError, TypeError):
            cd.cycles.panorama_type = "EQUIRECTANGULAR"
        cam = bpy.data.objects.new("Simpler Sky Bake", cd)
        sc.collection.objects.link(cam)
        sc.camera = cam
        cam.rotation_euler = (math.pi / 2, 0.0, -math.pi / 2)      # looking along +X, Z up
        cy = sc.cycles
        cy.use_adaptive_sampling = False
        cy.use_denoising = False
        cy.max_bounces = 0
        sc.render.use_persistent_data = False
        sc.view_settings.view_transform = "Standard"
        sc.render.image_settings.file_format = "OPEN_EXR"
        sc.render.image_settings.color_depth = "16"
        sc.render.film_transparent = False
        try:
            cy.device = bpy.context.scene.cycles.device
        except Exception:
            pass
        _sky["scene"] = sc
    old = sc.world
    sc.world = world
    if old is not None and old != world and old.users == 0:
        bpy.data.worlds.remove(old)
    W, H = int(req.get("w", 1024)), int(req.get("h", 512))
    sc.render.resolution_x, sc.render.resolution_y, sc.render.resolution_percentage = W, H, 100
    sc.cycles.samples = int(req.get("samples", 4))
    exr = req["out"] + ".exr"
    sc.render.filepath = exr
    bpy.ops.render.render(write_still=True, scene=sc.name)
    im = bpy.data.images.load(exr)
    try:
        px = np.empty(W * H * 4, dtype=np.float32)
        im.pixels.foreach_get(px)
    finally:
        bpy.data.images.remove(im)
        try:
            os.remove(exr)
        except OSError:
            pass
    # three.js layout (the view uses environmentRotation = 90° about X for its Z up): first row = straight down,
    # u = 0.5 - azimuth/360 (Blender: first row at the bottom, u = azimuth/360 from +X)
    a = px.reshape(H, W, 4)
    cols = (W // 2 - 1 - np.arange(W)) % W
    a = a[:, cols]
    a[..., 3] = 1.0
    with open(req["out"], "wb") as f:
        f.write(a.astype(np.float16).tobytes())
    lat = ((np.arange(H) + 0.5) / H - 0.5) * math.pi  # -90° at the first row
    dw = (2 * math.pi / W) * (math.pi / H) * np.cos(lat)
    up = lat > 0
    e_h = float((a[up, :, :3].mean(axis=2) * (dw[up] * np.sin(lat[up]))[:, None]).sum())
    band = (lat > math.radians(1)) & (lat < math.radians(6))
    hor = a[band, :, :3].reshape(-1, 3).mean(axis=0).tolist()
    stats = {"w": W, "h": H, "skyIrradiance": e_h, "horizon": hor}
    with open(req["final"] + ".json", "w", encoding="utf-8") as f:
        json.dump(stats, f)
    for w2 in list(bpy.data.worlds):
        if w2 != world and w2.users == 0:
            bpy.data.worlds.remove(w2)


# {"kind": "eco", "blend": plot + distributions (+ world and sun), "show": objects to put in the picture,
#  "center": [x, y, z] of the plot, "plot": its side (m), "light": {world, exposure, view, look} or None}
def render_eco(scene, _sphere, req):
    kinds = ("objects", "meshes", "materials", "images", "node_groups", "lights", "cameras", "collections", "worlds",
             "curves", "scenes")
    before = {k: set(getattr(bpy.data, k)) for k in kinds}
    sc = None
    try:
        with bpy.data.libraries.load(req["blend"], link=False) as (src, dst):
            dst.objects = list(src.objects)
            dst.collections = list(src.collections)
            dst.worlds = list(src.worlds)
        sc = bpy.data.scenes.new("Simpler Eco Thumb")
        sc.render.engine = "CYCLES"
        for a in ("device", "use_adaptive_sampling", "adaptive_threshold", "use_denoising", "denoiser", "max_bounces",
                  "texture_limit_render", "texture_limit"):
            try:
                setattr(sc.cycles, a, getattr(scene.cycles, a))
            except (AttributeError, TypeError):
                pass
        sc.render.use_persistent_data = False
        sc.render.use_simplify = True
        sc.render.film_transparent = False
        sc.render.image_settings.file_format = "PNG"
        show = set(req.get("show") or [])
        for o in dst.objects:
            if o is not None and o.name in show:
                sc.collection.objects.link(o)
        light = req.get("light")
        if light and light.get("world") in bpy.data.worlds:
            sc.world = bpy.data.worlds[light["world"]]
            sc.view_settings.view_transform = light.get("view") or "AgX"
            try:
                sc.view_settings.look = light.get("look") or "None"
            except TypeError:
                pass
            sc.view_settings.exposure = float(light.get("exposure") or 0.0)
        else:
            # plain daylight: a soft blue-grey sky and a sun from the left, high
            w = bpy.data.worlds.new("Simpler Eco Thumb")
            w.use_nodes = True
            w.node_tree.nodes["Background"].inputs[0].default_value = (0.42, 0.52, 0.68, 1)
            w.node_tree.nodes["Background"].inputs[1].default_value = 1.0
            sc.world = w
            ld = bpy.data.lights.new("Simpler Eco Thumb Sun", "SUN")
            ld.energy, ld.angle = 3.5, math.radians(1.5)
            lo = bpy.data.objects.new("Simpler Eco Thumb Sun", ld)
            lo.rotation_euler = (math.radians(40), 0.0, math.radians(-60))
            sc.collection.objects.link(lo)
            sc.view_settings.view_transform = "AgX"
            try:
                sc.view_settings.look = "AgX - Medium High Contrast"
            except TypeError:
                pass
        # the camera: from the front left, 50° above, aimed at the middle of the plot; as far as it can be while all
        # four corners of the picture still fall on the plot (no edge, no background: a close look at the ground)
        cx, cy, cz = req["center"]
        half = float(req.get("plot", 20.0)) / 2.0 * 0.94
        target = Vector((cx, cy, cz))
        el, az = math.radians(50), math.radians(-30)
        dvec = Vector((math.sin(az) * math.cos(el), -math.cos(az) * math.cos(el), math.sin(el)))
        cd = bpy.data.cameras.new("Simpler Eco Thumb")
        cd.lens, cd.sensor_width, cd.sensor_fit = 50.0, 36.0, "HORIZONTAL"
        cd.clip_start, cd.clip_end = 0.05, 1000.0
        cam = bpy.data.objects.new("Simpler Eco Thumb", cd)
        sc.collection.objects.link(cam)
        sc.camera = cam
        rot = (-dvec).to_track_quat("-Z", "Y")
        t = math.tan(math.atan(18.0 / 50.0))         # half of the view, both ways (square picture)

        def inside(dist):
            pos = target + dvec * dist
            for sx in (-1, 1):
                for sy in (-1, 1):
                    ray = rot @ Vector((sx * t, sy * t, -1.0))
                    if ray.z >= -1e-6:
                        return False
                    k = (cz - pos.z) / ray.z
                    hit = pos + ray * k
                    if abs(hit.x - cx) > half or abs(hit.y - cy) > half:
                        return False
            return True
        lo_d, hi_d = 0.3, 0.3
        while inside(hi_d * 1.5) and hi_d < 500:
            hi_d *= 1.5
        lo_d = hi_d
        hi_d = hi_d * 1.5
        for _ in range(30):
            mid = (lo_d + hi_d) / 2
            lo_d, hi_d = (mid, hi_d) if inside(mid) else (lo_d, mid)
        cam.location = target + dvec * lo_d
        cam.rotation_euler = rot.to_euler()
        px = int(req.get("size", 384))
        sc.render.resolution_x = sc.render.resolution_y = px
        sc.render.resolution_percentage = 100
        sc.cycles.samples = int(req.get("samples", 96))
        sc.render.filepath = req["out"]
        bpy.ops.render.render(write_still=True, scene=sc.name)
    finally:
        if sc is not None:
            bpy.data.scenes.remove(sc)
        added = _new(before)
        for k in ("objects", "collections", "meshes", "materials", "node_groups", "lights", "cameras", "worlds", "curves", "images"):
            for x in added[k]:
                try:
                    getattr(bpy.data, k).remove(x)
                except (ReferenceError, RuntimeError):
                    pass
        for lib in list(bpy.data.libraries):
            bpy.data.libraries.remove(lib)


def main():
    scene, sphere = setup()
    print("SIMPLER_PREVIEW_READY", flush=True)
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        if line == "quit":
            break
        try:
            req = json.loads(line)
            final = req["out"]
            tmp = final + (".part" if req.get("kind") in ("sky", "probe") else ".part.png")
            req["out"] = tmp
            req["final"] = final
            {"model": render_model, "import": import_model, "sky": bake_sky, "probe": probe_model, "eco": render_eco}.get(req.get("kind"), render)(scene, sphere, req)
            if not (req.get("kind") == "import" and req.get("split")):
                os.replace(tmp, final)
            print("SIMPLER_PREVIEW_DONE " + final, flush=True)
        except Exception as exc:
            traceback.print_exc()
            print("SIMPLER_PREVIEW_ERROR " + str(exc).replace("\n", " "), flush=True)


main()
