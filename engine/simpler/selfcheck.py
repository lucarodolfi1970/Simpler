"""Self-check of the engine: the things that must always hold in a scene, one rule per bug found (GET selfcheck).

tools/regression.py asks it after opening a project, after the steps and after saving and opening it again: a rule
broken is a failure of the check, whatever the version. Every bug that reaches Luca adds its rule here (or a step in
the regression), so it cannot come back unseen.

Each rule: (name, function) -> list of problems (empty: holds). Kept cheap: a few loops over the data, no rays.
"""
import bpy


def _refcaustics_linked():
    # 1.73.8: the check of the missing textures at opening unplugged the pictures of the light reflected by the
    # water (they live in a temporary folder): computed again, it never reached the surfaces
    from . import refcaustics
    g = bpy.data.node_groups.get(refcaustics.GROUP)
    if g is None:
        return []
    out = []
    for k in range(refcaustics.SLOTS):
        n = g.nodes.get(f"img{k}")
        if n is None or not any(o.is_linked for o in n.outputs):
            out.append(f"refcaustics img{k} unplugged")
    return out


def _internal_not_missing():
    # 1.73.8: Simpler's own pictures (made again by the engine) never reported as missing textures of the project
    from . import textures
    return [f"internal picture reported missing: {im.name}" for im in bpy.data.images
            if im.get("simpler_refcaustics_img") and textures.is_missing(im) and im.users]


def _no_cut_internal():
    # 1.73.8: no node of Simpler's own groups cut off by the check of the missing textures
    from . import textures
    out = []
    for g in bpy.data.node_groups:
        if not g.name.startswith("Simpler"):
            continue
        for n in g.nodes:
            if n.get(textures.CUT_KEY):
                out.append(f"{g.name}/{n.name} cut off")
    return out


def _ocean_maps():
    # 1.73.8: the sea has its maps (far waves, short waves) packed in the project - the final render reads a copy
    from . import ocean
    ob = ocean._find()
    if ob is None:
        return []
    out = []
    mat = ob.data.materials[0] if ob.data.materials else None
    if mat is None or mat.name != ocean.MAT:
        out.append(f"sea material {mat.name if mat else None} instead of {ocean.MAT}")
        return out
    for node, name in [(b + x, im) for b, im in (("slopes_tex", ocean.SLOPE_IMG), ("detail_tex", ocean.DETAIL_IMG))
                       for x in ("", "_1", "_2")]:          # (1.76.21: three samples of each map, laid without repeating)
        n = mat.node_tree.nodes.get(node)
        im = n.image if n is not None else None
        if im is None:
            out.append(f"sea: {node} without picture")
        elif im.packed_file is None:
            out.append(f"sea: {name} not packed")
    # (1.76.21) the far map carries the foam of the tile (blue): the far sea foams as the near one, and the foam of
    # the wide rows of the grid is not drawn as streaks; the foam comes from the map there (_material)
    s = ocean.settings(ob)
    img = bpy.data.images.get(ocean.SLOPE_IMG)
    if img is not None and float(s.get("foam") or 0) > 0.05 and float(s.get("height") or 0) > 0:
        import numpy as np
        px = np.empty(img.size[0] * img.size[1] * 4, np.float32)
        img.pixels.foreach_get(px)
        if float(px[2::4].max()) <= 0.0:
            out.append("sea: the far map has no foam")
    nt = mat.node_tree
    if not any(nd.type == "MIX" and nd.data_type == "FLOAT" and nd.inputs[2].is_linked and nd.inputs[2].links[0].from_node.type == "ATTRIBUTE"
               and nd.inputs[2].links[0].from_node.attribute_name == "foam" for nd in nt.nodes):
        out.append("sea: the foam of the points drawn where the grid is wide (no blend with the far map)")
    # (1.76.22) the foam of the surf as a lace cut at a level (coast_noise, coast_cut), not a grey veil (Luca)
    # (1.76.23) the clear water its own shader: a single one went half white where the water stops being clear - a
    # grey band along the coast whatever the foam (Luca)
    if nt.nodes.get("bs_clear") is None or nt.nodes.get("sea_clear_mix") is None:
        out.append("sea: the clear water mixed in the base colour (grey band along the coast)")
    if nt.nodes.get("coast_noise") is None or nt.nodes.get("coast_cut") is None:
        out.append("sea: the foam of the surf drawn as a veil (no coast_noise / coast_cut)")
    if ob.data.get("simpler_grid", 1) != ocean.GRID_VERSION:
        out.append("sea: grid of an older version")
    # (1.76.33, Luca: «il bordo che tocca l'acqua è troppo netto») the shore's ripples in true shape for the path
    # tracing: the fade group cuts and raises the band along the shore
    fd = ob.modifiers.get(ocean.MOD_FADE)
    g = fd.node_group if fd is not None else None
    eo = bpy.data.objects.get(ocean.EDGE_OBJ)
    if g is not None and g.nodes.get("edge_obj") is not None and s.get("coast") and ocean._COAST.get("objects") \
            and (eo is None or g.nodes["edge_obj"].inputs["Object"].default_value is not eo):
        out.append("sea: the ripples of the shore without the shape of the water line (1.76.36: they did nothing)")
    if g is None or g.nodes.get("edge_sub") is None or g.nodes.get("edge_v3") is None:
        out.append("sea: no ripples of the shore (an older group: the water meets the rocks in a clean cut)")
    elif s.get("coast") and float(s.get("height") or 0) > 0.05 and float(s.get("edgeMove", 1)) > 0 \
            and g.nodes["edge_amp"].outputs[0].default_value <= 0.0:
        out.append("sea: the ripples of the shore off with the coast on")
    # (1.76.27, Luca: «la schiuma della costa è dritta invece di circondare il modello») with the coast on and
    # something at the water line, the material reads the coast from its map of square cells (ocean._raster_image)
    if s.get("coast") and ocean._COAST.get("objects") and ocean._RASTER["d"] is not None:
        t = nt.nodes.get("coast_tex")
        on = nt.nodes.get("coast_on")
        if t is None or t.image is None or on is None or on.outputs[0].default_value < 0.5:
            out.append("sea: the coast drawn from the points of the grid (no map: straight bands)")
        elif t.image.packed_file is None:
            out.append(f"sea: {ocean.COAST_IMG} not packed")
        elif not ocean._coast_info(s):
            out.append("sea: the coast's map not given to the view")
    return out


def _no_fake_texture_asked():
    # 1.74.0: a «texture» whose path is only the name of a map (FBX of 3ds Max: «M:/Map #5234338», no extension) was
    # asked for at every opening; it is an empty map of the original model: never in the list of the missing ones
    from . import textures
    return [f"asked for a path without a file: {n}" for n in textures.status()["missing"] if not textures._real_file(n)]


def _no_puddles_in_sea():
    # 1.75.0: the puddles of the rain showed on the sand under the sea. The rain's material group must take the sea's
    # line both for the snow and for the puddles (its "s_on" value feeds both), and know where the sea is now
    from . import rain, ocean
    g = bpy.data.node_groups.get(rain.GROUP)
    if g is None or not ocean.present():
        return []
    n = g.nodes.get("s_on")
    if n is None:
        return ["rain group without the sea's line"]
    out = []
    if len(n.outputs[0].links) < 2:
        out.append("rain: the sea's line does not reach the puddles")
    line = ocean.snow_line()
    if line is not None and n.outputs[0].default_value < 0.5:
        out.append("rain: the sea is there but the rain does not know it")
    return out


def _water_grids():
    # 1.75.0: the grid around the camera of a large water surface is rendered in its place. Without the surface's
    # materials it was a grey floor; read through the surface's modifier the final render raised the water to the
    # shoulders of a person. It must follow its surface, carry its materials and its own waves
    from . import water
    out = []
    for g in [o for o in bpy.context.scene.objects if o.get(water.GRID_KEY)]:
        src = next((o for o in bpy.context.scene.objects if (o.get("simpler_id", "") or o.name) == g[water.GRID_KEY]
                    and not o.get(water.GRID_KEY)), None)
        if src is None:
            out.append(f"{g.name}: no surface")
            continue
        c = next((c for c in g.constraints if c.type == "COPY_TRANSFORMS"), None)
        if c is None or c.target is not src:
            out.append(f"{g.name}: does not follow {src.name}")
        if [m.name if m else None for m in g.data.materials] != [s.material.name if s.material else None for s in src.material_slots]:
            out.append(f"{g.name}: materials differ from {src.name}")
        if g.modifiers.get(water.MOD) is None:
            out.append(f"{g.name}: no waves")
    return out


def _sea_caustics_clean():
    # 1.75.2: the sea's caustics are made in a scene of their own, removed at once; «Luce riflessa dall'acqua» off
    # leaves nothing of them (the scene as before)
    from . import seacaustics, refcaustics
    out = []
    if bpy.data.scenes.get(seacaustics.TMP_SCENE) is not None:
        out.append("scene of the sea's caustics left")
    left = [x.name for c in (bpy.data.objects, bpy.data.meshes, bpy.data.materials) for x in c
            if x.name.startswith(seacaustics.TMP_SCENE)]
    if left:
        out.append("left: " + ", ".join(left[:5]))
    if not refcaustics.enabled() and bpy.data.node_groups.get(refcaustics.GROUP) is not None:
        out.append("reflected light off but its images still in the materials")
    return out


def _coast_sign():
    # 1.75.2: no sea in the scene - the «busy» sign never says «coast» (a sea of a project opened before left its name)
    from . import ocean
    if ocean._find() is None and ocean.BAND["name"] and ocean._COAST["changes"] != -1:
        from . import rain
        if ocean._COAST["changes"] == rain._STATE["changes"]:
            return [f"coast still named: {ocean.BAND['name']}"]
    return []


def _snow_closed():
    # 1.75.16: the snow mantle has no open edge standing above the surface under it (dark slits along a sidewalk,
    # Luca: «servono bordi chiusi ovunque») - a ray down from a sample of its open edges finds the surface at once
    from . import snow
    import bmesh
    from mathutils import Vector
    ob = snow._object()
    if ob is None or ob.data is None or not len(ob.data.vertices):
        return []
    bm = bmesh.new()
    bm.from_mesh(ob.data)
    edges = [e for e in bm.edges if e.is_boundary]
    step = max(1, len(edges) // 1500)
    sc = bpy.context.scene
    dg = bpy.context.evaluated_depsgraph_get()
    mw = ob.matrix_world
    bad = []
    for e in edges[::step]:
        p = mw @ ((e.verts[0].co + e.verts[1].co) / 2)
        hit, loc, _n, _i, hob, _m = sc.ray_cast(dg, p - Vector((0, 0, 0.004)), Vector((0, 0, -1)), distance=5.0)
        if hit and hob is not None and not hob.get(snow.MANTLE_KEY) and (p.z - loc.z) > 0.04:
            bad.append(f"open edge {p.z - loc.z:.2f} m above {hob.name} at ({p.x:.2f}, {p.y:.2f})")
            if len(bad) >= 5:
                break
    bm.free()
    return bad


def _terrain_diagonals():
    # 1.76.12: a crest across the cells of the terrain grid stays one line of edges (Luca: «creste a dente di sega»):
    # the diagonal chosen follows a ridge in either direction; a plane keeps the alternating split
    import numpy as np
    from . import terrain
    n = 24
    i, j = np.meshgrid(np.arange(n, dtype=float), np.arange(n, dtype=float), indexing="ij")
    bad = []
    main = -np.abs(i - j)                  # a crest along (0,0)-(1,1)
    anti = -np.abs(i + j - (n - 1))        # a crest along (0,1)-(1,0)
    d1 = terrain._diagonals(main)[np.abs(i[:-1, :-1] - j[:-1, :-1]) < 0.5]
    d2 = terrain._diagonals(anti)[np.abs(i[:-1, :-1] + j[:-1, :-1] + 1 - (n - 1)) < 0.5]
    if d1.any():
        bad.append(f"crest along the main diagonal cut across in {int(d1.sum())} cells")
    if not d2.all():
        bad.append(f"crest along the other diagonal cut across in {int((~d2).sum())} cells")
    flat = terrain._diagonals(np.zeros((n, n)))
    if abs(float(flat.mean()) - 0.5) > 0.05:
        bad.append("a plane is not split alternately")
    return bad


def _snow_no_repeats():
    # 1.76.45 (Luca: «la neve con una quantità di 29,6 crea quegli strani disegni ripetuti»): the noise of the snow must
    # not repeat every 8 m (the tile of its map) - the same values one tile away are a wallpaper from far
    import numpy as np
    from . import snow
    x = np.arange(0.0, 400.0, 0.5)
    X, Y = np.meshgrid(x, x)
    a = snow._snow_ns(X, Y, 0.0, 0.0)
    bad = []
    for name, b in (("8 m east", snow._snow_ns(X + 8.0, Y, 0.0, 0.0)), ("8 m north", snow._snow_ns(X, Y + 8.0, 0.0, 0.0))):
        c = float(np.corrcoef(a.ravel(), b.ravel())[0, 1])
        if c > 0.4:          # (before 1.76.45: 0.62; now about 0.17)
            bad.append(f"the snow repeats {name}: correlation {c:.2f}")
    return bad


def _snow_slope_shaken():
    # 1.76.12: on a slope at the limit the snow is ragged (the slope shaken by the map), not a straight line along the
    # triangles - the same in the materials (rain group: «snowmask3») and in the mantle (snow._snow_at)
    import numpy as np
    from . import rain, snow
    bad = []
    g = bpy.data.node_groups.get(rain.GROUP)
    if g is not None and g.nodes.get("snowmask") is not None and g.nodes.get("snowmask3") is None:
        bad.append(f"{rain.GROUP}: the slope of the snow is not shaken (no snowmask3)")
    x = np.linspace(0.0, 60.0, 400)
    X, Y = np.meshgrid(x, x)
    walls = 0.3
    wlo = 0.75 - 0.95 * walls
    nz = np.full_like(X, wlo + 0.15)
    st = (1.0, walls, 0.3, 0.0, 0.0, 0.0, False, 0.5)
    _S, face = snow._snow_at(X, Y, np.zeros_like(X), nz, st, local=True)
    if float(face.std()) < 0.05:
        bad.append(f"the mantle's slope is not shaken (spread {float(face.std()):.3f})")
    return bad


def _snow_empty_part():
    # 1.76.25: a variant of the snow's shells that came out with no faces stopped the path tracing («foreach_set(..)
    # sequence length mismatch given 1, needed 0», Luca with a terrain and trees): an empty mesh must be made
    from . import snow
    try:
        me = snow._mesh([], [], [], None)
    except Exception as exc:  # noqa: BLE001
        return [f"an empty snow mesh fails: {exc}"[:200]]
    bpy.data.meshes.remove(me)
    return []


def _clouds_height():
    # 1.76.17: the clouds are where the user put them (their «height» over the ground of the scene) - never raised by
    # Simpler above the terrain (Luca: «Non alzare niente!»)
    from . import ambience, clouds
    st = ambience.state()
    if not clouds.active(st):
        return []
    obs = clouds._volume_objects(clouds._collection())
    if not obs:
        return []
    lo, _hi = ambience._scene_box()
    want = float(lo.z) + float(clouds.settings(st)["height"])
    base = min(float(o.location.z - o.scale.z) for o in obs)
    if abs(base - want) > 1.0:
        return [f"clouds from {base:.0f} m, their height says {want:.0f} m"]
    return []


def _camera_far():
    # 1.76.20: the camera sees the whole scene and the sea - before, its far clip was 100 x the orbit distance (at
    # least 1 km): close to its target, the path tracing lost a terrain of 3 km and the sea past 1 km (Luca)
    from mathutils import Vector
    from . import ambience, ocean, render
    cam = bpy.context.scene.camera
    if cam is None:
        return []
    far = float(cam.data.clip_end)
    bad = []
    lo, hi = ambience._scene_box()
    p = cam.matrix_world.translation
    reach = max((Vector((x, y, z)) - p).length for x in (lo.x, hi.x) for y in (lo.y, hi.y) for z in (lo.z, hi.z))
    if far < reach:
        bad.append(f"the camera stops at {far:.0f} m, the scene reaches {reach:.0f} m")
    if ocean.present() and far < ocean.EDGE_FAR:
        bad.append(f"the camera stops at {far:.0f} m, the sea goes to {ocean.EDGE_FAR:.0f} m")
    if far < render.CLIP_FAR:
        bad.append(f"far clip {far:.0f} m, less than {render.CLIP_FAR:.0f} m")
    return bad


def _stale_proxy_orig():
    # 1.75.38: an image node showing a new image (the rain's shelter map, made again) with the name of an old
    # «original» left on it: the final render put the old image back, its file gone - the wet road dry in the render.
    # Tested on a node made for the check: a stale name must be ignored and dropped.
    from . import proxies
    g = bpy.data.node_groups.new("simpler_selfcheck_tmp", "ShaderNodeTree")
    new = bpy.data.images.new("simpler_selfcheck_new", 4, 4)
    old = bpy.data.images.new("simpler_selfcheck_old", 4, 4)
    try:
        n = g.nodes.new("ShaderNodeTexImage")
        n.image = new
        n[proxies.NODE_ORIG] = old.name
        got = proxies._original(n)
        out = []
        if got is not new:
            out.append(f"stale original taken: {got.name if got else None}")
        if n.get(proxies.NODE_ORIG):
            out.append("stale original name left on the node")
        # and the shelter map of the rain is never offered for a reduced copy
        import os
        import tempfile
        f = os.path.join(tempfile.gettempdir(), "simpler_selfcheck_noproxy.png")
        new.filepath_raw = f
        new.file_format = "PNG"
        new.save()
        new.source = "FILE"
        new[proxies.NO_PROXY] = 1
        if any(im.name == new.name for im in proxies.originals_in_use()):
            out.append("image marked noproxy offered to the proxies")
        return out
    finally:
        bpy.data.node_groups.remove(g)
        bpy.data.images.remove(new)
        bpy.data.images.remove(old)


def _data_maps_not_proxied():
    # 1.75.51: the maps of data Simpler paints (painted dirt: amount and depth in bytes; painted puddles and snow,
    # the shelter of the rain) never offered for a reduced copy - a reduced copy of the dirt map hid the painted dirt
    # in the path tracing of a big project
    from . import proxies, dirtpaint
    names = {dirtpaint.IMG}
    try:
        from . import rain
        names |= {L["img"] for L in rain.LAYERS.values()}
    except Exception:  # noqa: BLE001
        pass
    out = [f"data map offered to the proxies: {im.name}" for im in proxies.originals_in_use() if im.name in names]
    for n in names:
        im = bpy.data.images.get(n)
        if im is not None and im.users and not im.get(proxies.NO_PROXY):
            out.append(f"data map without the no-proxy mark: {n}")
    return out


RULES = [
    ("refcaustics_linked", _refcaustics_linked),
    ("internal_not_missing", _internal_not_missing),
    ("no_cut_internal", _no_cut_internal),
    ("ocean_maps", _ocean_maps),
    ("no_fake_texture_asked", _no_fake_texture_asked),
    ("no_puddles_in_sea", _no_puddles_in_sea),
    ("water_grids", _water_grids),
    ("sea_caustics_clean", _sea_caustics_clean),
    ("coast_sign", _coast_sign),
    ("snow_closed", _snow_closed),
    ("terrain_diagonals", _terrain_diagonals),
    ("snow_slope_shaken", _snow_slope_shaken),
    ("snow_no_repeats", _snow_no_repeats),
    ("clouds_height", _clouds_height),
    ("snow_empty_part", _snow_empty_part),
    ("camera_far", _camera_far),
    ("stale_proxy_orig", _stale_proxy_orig),
    ("data_maps_not_proxied", _data_maps_not_proxied),
]


def run(_d=None):
    """GET selfcheck -> {holds, problems: {rule: [..]}}"""
    problems = {}
    for name, fn in RULES:
        try:
            p = fn()
        except Exception as exc:  # noqa: BLE001
            p = [f"rule failed: {exc!r}"[:200]]
        if p:
            problems[name] = p[:20]
    return {"holds": not problems, "problems": problems}     # (not "ok": the server sets that on every answer)
