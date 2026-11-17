"""Volumetric clouds: real clouds in 3D for the path tracing (the "Volumetric clouds" of Twinmotion, with Cycles).

A layer of the sky between the base and the top of the clouds (a box tens of km wide, centred on the scene) filled
with a cloud volume:
- shape: a large noise for the masses (coverage = how much of it becomes cloud, size = how big the masses are), a
  height profile (flat bottom, rounded top, thickness) and a small Worley noise that erodes the edges into puffs;
- light: Volume Scatter, forward (Henyey-Greenstein; see _material for why not the MIE phase): the glow against
  the sun, the white of the lit side, the grey of the thick bases, as real clouds. Self shadows and the shadows on
  the ground come from the path tracing itself (no trick). Far clouds fade into the haze (aerial perspective).
- two suns: the sun of the Ambiente lights the scene and NOT the clouds; a "sun of the clouds" (light linking)
  lights only the clouds, with the colour the sunlight has up there - redder after a longer path through the air,
  and still there for a few degrees after sunset (the clouds glow pink while the ground is already in the shade).
  With "Ombre delle nuvole" off the clouds do not block the sun of the scene (shadow linking): clear sunlight
  under a cloudy sky.

Cost: a volume over the whole sky, ray-marched (biased volumes, small steps). In the view: fewer volume bounces
and longer steps; in the final render: full bounces. One switch (clouds.volumetric), off by default: off, the clouds stay painted on the sky.
The real-time view keeps the painted clouds (a 360-degree photo of the real ones comes later).
"""
import json
import math

import bpy
from mathutils import Vector

CLOUD_KEY = "simpler_clouds"           # on the cloud volume object
CLOUD_SUN_KEY = "simpler_cloud_sun"    # on the sun that lights only the clouds
COLL = "Simpler Nuvole"
MAT = "Simpler Nuvole volumetriche"
MAT2 = "Simpler Nuvole volumetriche (strato alto)"
LAYER_KEY = "simpler_clouds_layer"       # 2 on the object of the second layer (it has CLOUD_KEY too: every
                                         # exclusion of the clouds - export, caustics, measures - applies to it)
HALF_WIDTH = 30000.0                   # metres: the layer reaches ~4-6 degrees above the horizon


def _tiles():
    """The boxes of the layer (x0, x1, y0, y1 around the centre). One: boxes side by side leave seams (the volume
    is entered and left on their shared faces, with different steps on the two sides)."""
    return [(-HALF_WIDTH, HALF_WIDTH, -HALF_WIDTH, HALF_WIDTH)]

# types of cloud (Twinmotion: Small cumulus, Large cumulus, Altocumulus, Cumulonimbus, Stratus, Nimbostratus)
TYPES = {
    "cumuli_piccoli": {"cover": 0.30, "scale": 0.30, "height": 1200.0, "thickness": 700.0, "flat": 0.75, "puff": 0.70, "density": 0.45},
    "cumuli_grandi": {"cover": 0.32, "scale": 0.65, "height": 1400.0, "thickness": 1800.0, "flat": 0.65, "puff": 0.60, "density": 0.55},
    "altocumuli": {"cover": 0.52, "scale": 0.02, "height": 3600.0, "thickness": 320.0, "flat": 0.30, "puff": 0.95, "density": 0.30},
    "cumulonembo": {"cover": 0.35, "scale": 0.95, "height": 1100.0, "thickness": 5000.0, "flat": 0.85, "puff": 0.50, "density": 0.80},
    "strati": {"cover": 0.92, "scale": 0.80, "height": 600.0, "thickness": 350.0, "flat": 0.25, "puff": 0.15, "density": 0.40},
    "nembostrati": {"cover": 0.98, "scale": 0.90, "height": 800.0, "thickness": 2500.0, "flat": 0.30, "puff": 0.20, "density": 0.90},
}
VDEFAULTS = {"volumetric": False, "type": "cumuli_piccoli", "height": 1200.0, "thickness": 700.0, "flat": 0.75,
             "puff": 0.70, "density": 0.45, "shadows": True, "layer2": False, "layer2Cover": 0.5}
SIGMA_MAX = 0.085                      # 1/m at density 100%: a thick cumulus (real ones 0.05-0.1; Cycles needs
                                       # (seen through the anisotropy of the scattering, see _material)


LIGHT_K = 0.3                          # density seen by the light inside the clouds (see _material)


def settings(s):
    c = dict(VDEFAULTS)
    c.update(s.get("clouds") or {})
    c["height"] = max(250.0, min(4000.0, float(c["height"])))
    c["thickness"] = max(100.0, min(6000.0, float(c["thickness"])))
    for k in ("flat", "puff", "density", "cover", "scale", "layer2Cover"):
        c[k] = max(0.0, min(1.0, float(c.get(k, 0.5))))
    c["layer2"] = bool(c.get("layer2"))
    return c


def layer2_settings(c):
    """The second layer (1.17.12, a switch): a thinner sheet higher up, as in a covered sky - dark masses below and a
    lighter, broken veil above, with gaps of light between them. Its base 700 m over the top of the first layer
    (at least 3 km), altocumulus-like: thin, flat-ish, puffy, lighter."""
    top1 = c["height"] + c["thickness"]
    return {"height": min(9000.0, max(3000.0, top1 + 700.0)), "thickness": 450.0, "flat": 0.35, "puff": 0.85,
            "density": 0.30, "cover": c["layer2Cover"], "scale": 0.35}


def active(s):
    return s is not None and s.get("mode") == "sky" and bool(settings(s)["volumetric"]) and settings(s)["cover"] > 0.005


# ---------------------------------------------------------------- scene objects

def _collection():
    from .core import INTERNAL_KEY
    coll = bpy.data.collections.get(COLL)
    if coll is None:
        coll = bpy.data.collections.new(COLL)
        coll[INTERNAL_KEY] = 1
    if coll.name not in bpy.context.scene.collection.children:
        bpy.context.scene.collection.children.link(coll)
    return coll


def _find(flag):
    for ob in bpy.data.objects:
        if ob.get(flag):
            return ob
    return None


def _find_all(flag):
    return sorted((ob for ob in bpy.data.objects if ob.get(flag)), key=lambda o: int(o.get(flag)))


def remove():
    for ob in _find_all(CLOUD_KEY) + _find_all(CLOUD_SUN_KEY):
        if ob is not None:
            data = ob.data
            bpy.data.objects.remove(ob, do_unlink=True)
            if data is not None and data.users == 0:
                if isinstance(data, bpy.types.Light):
                    bpy.data.lights.remove(data)
                elif isinstance(data, bpy.types.Mesh):
                    bpy.data.meshes.remove(data)
    for name in (COLL, COLL + " (solo volume)"):
        coll = bpy.data.collections.get(name)
        if coll is not None:
            bpy.data.collections.remove(coll)
    from .ambience import _find_flag, SUN_KEY
    sun = _find_flag(SUN_KEY)
    # (only when set: writing the light linking, even None over None, makes Blender evaluate the whole scene again -
    # 0.3-0.8 s on a big model at every change of the Ambiente without clouds, and the path tracing synced it all)
    if sun is not None:
        _link(sun, "receiver_collection", None)
        _link(sun, "blocker_collection", None)


def _link(ob, attr, coll):
    if getattr(ob.light_linking, attr) != coll:
        setattr(ob.light_linking, attr, coll)


def _volume_objects(coll):
    """The boxes of the layer (one mesh, one material)."""
    from .core import INTERNAL_KEY
    obs = [o for o in _find_all(CLOUD_KEY) if not o.get(LAYER_KEY)]
    n = len(_tiles())
    if len(obs) != n:
        for ob in obs:
            bpy.data.objects.remove(ob, do_unlink=True)
        me = bpy.data.meshes.get(MAT)
        if me is None:
            me = bpy.data.meshes.new(MAT)
            v = [(x, y, z) for x in (-1, 1) for y in (-1, 1) for z in (-1, 1)]
            f = [(0, 1, 3, 2), (4, 6, 7, 5), (0, 4, 5, 1), (2, 3, 7, 6), (0, 2, 6, 4), (1, 5, 7, 3)]
            me.from_pydata(v, [], f)
            me.update()
        obs = []
        for i in range(n):
            ob = bpy.data.objects.new(f"{MAT} {i + 1}", me)
            ob[CLOUD_KEY] = i + 1
            ob[INTERNAL_KEY] = 1
            ob.hide_select = True
            obs.append(ob)
    mat = _material()
    for ob in obs:
        if ob.name not in coll.objects:
            coll.objects.link(ob)
        ob.hide_viewport = True                 # not clicked, not in the real-time view: only Cycles sees it
        ob.hide_render = False
        ob.cycles.is_caustics_caster = ob.cycles.is_caustics_receiver = False
        if not ob.data.materials:
            ob.data.materials.append(mat)
        elif ob.data.materials[0] != mat:
            ob.data.materials[0] = mat
    return obs


def _material(name=MAT):
    """The cloud volume (one material per layer; its numbers are set by _set_shape)."""
    mat = bpy.data.materials.get(name)
    if mat is not None and mat.node_tree is not None and mat.node_tree.nodes.get("billow") is not None and mat.cycles.volume_step_rate == 0.25 and mat.node_tree.nodes.get("light_k").outputs[0].links[0].to_node.operation == "POWER":
        return mat
    if mat is None:
        mat = bpy.data.materials.new(name)
    mat.use_nodes = True
    nt = mat.node_tree
    N, L = nt.nodes, nt.links
    for n in list(N):
        N.remove(n)
    out = N.new("ShaderNodeOutputMaterial")
    geo = N.new("ShaderNodeNewGeometry")
    sep = N.new("ShaderNodeSeparateXYZ"); L.new(geo.outputs["Position"], sep.inputs[0])

    def node(t, name=None, **kw):
        n = N.new(t)
        if name:
            n.name = name
        for k, v in kw.items():
            setattr(n, k, v)
        return n

    def math_(op, a=None, b=None, name=None, clamp=False):
        n = node("ShaderNodeMath", name, operation=op)
        n.use_clamp = clamp
        for i, x in enumerate((a, b)):
            if x is None:
                continue
            if isinstance(x, (int, float)):
                n.inputs[i].default_value = x
            else:
                L.new(x, n.inputs[i])
        return n.outputs[0]

    # height within the layer: 0 at the base, 1 at the top
    h = node("ShaderNodeMapRange", "height")
    L.new(sep.outputs[2], h.inputs[0])
    # flat bottom: the density rises within a short band above the base; rounded top: it falls towards the top
    bot = node("ShaderNodeMapRange", "bottom", interpolation_type="SMOOTHSTEP")
    bot.inputs[1].default_value = 0.0
    L.new(h.outputs[0], bot.inputs[0])
    top = node("ShaderNodeMapRange", "top", interpolation_type="SMOOTHSTEP")
    top.inputs[1].default_value = 1.0
    L.new(h.outputs[0], top.inputs[0])
    prof = math_("MULTIPLY", bot.outputs[0], top.outputs[0])
    # the masses: a large noise, in km (world position: the clouds stay put whatever is moved in the scene)
    sc1 = node("ShaderNodeVectorMath", "mass_scale", operation="SCALE")
    L.new(geo.outputs["Position"], sc1.inputs[0])
    off = node("ShaderNodeVectorMath", "seed", operation="ADD")
    L.new(sc1.outputs[0], off.inputs[0])
    nz = node("ShaderNodeTexNoise")
    nz.inputs["Scale"].default_value = 1.0
    nz.inputs["Detail"].default_value = 5.0
    nz.inputs["Roughness"].default_value = 0.55
    L.new(off.outputs[0], nz.inputs["Vector"])
    cov = node("ShaderNodeMapRange", "cover_lo")
    L.new(nz.outputs["Fac"], cov.inputs[0])
    # domes: the denser the mass, the higher it rises (the top of the cloud where mass = height); with the flat
    # bottom and the rounded top this gives the cumulus towers, narrower than their base
    tower = math_("SUBTRACT", cov.outputs[0], math_("MULTIPLY", h.outputs[0], 0.7, name="tower_h"), name="tower", clamp=True)
    shape = math_("MULTIPLY", math_("MULTIPLY", tower, 1.6, name="tower_m", clamp=True), prof)
    # puffs (the cauliflower): a fractal Worley noise (Voronoi F1, three octaves: ~200, ~80, ~35 m for small
    # cumulus) eats the edges, leaving round billows around its cells; its lookup is warped by a smooth noise so the
    # cells do not line up. A finer noise adds the wisps.
    sc3 = node("ShaderNodeVectorMath", "detail_scale", operation="SCALE")
    L.new(geo.outputs["Position"], sc3.inputs[0])
    nz2 = node("ShaderNodeTexNoise")
    nz2.inputs["Scale"].default_value = 1.0
    nz2.inputs["Detail"].default_value = 3.0
    L.new(sc3.outputs[0], nz2.inputs["Vector"])
    wv = node("ShaderNodeVectorMath", operation="SUBTRACT")
    L.new(nz2.outputs["Color"], wv.inputs[0]); wv.inputs[1].default_value = (0.5, 0.5, 0.5)
    ww = node("ShaderNodeVectorMath", "warp", operation="SCALE")       # Scale: metres of warp
    L.new(wv.outputs[0], ww.inputs[0])
    wp = node("ShaderNodeVectorMath", operation="ADD")
    L.new(geo.outputs["Position"], wp.inputs[0]); L.new(ww.outputs[0], wp.inputs[1])
    sc2 = node("ShaderNodeVectorMath", "puff_scale", operation="SCALE")
    L.new(wp.outputs[0], sc2.inputs[0])
    vo = node("ShaderNodeTexVoronoi", feature="F1")
    vo.inputs["Scale"].default_value = 1.0
    for k, v in (("Detail", 2.0), ("Roughness", 0.5), ("Lacunarity", 2.4)):
        try:
            vo.inputs[k].default_value = v
        except KeyError:
            pass
    try:
        vo.normalize = True
    except AttributeError:
        pass
    L.new(sc2.outputs[0], vo.inputs["Vector"])
    bil = node("ShaderNodeMapRange", "billow", interpolation_type="SMOOTHSTEP")     # contrast: round billows
    bil.inputs[1].default_value = 0.12; bil.inputs[2].default_value = 0.55
    L.new(vo.outputs["Distance"], bil.inputs[0])
    ero = math_("ADD", math_("MULTIPLY", bil.outputs[0], 0.8), math_("MULTIPLY", nz2.outputs["Fac"], 0.2))
    ero = math_("MULTIPLY", ero, None, name="puff")
    # erosion strongest at the thin edges, little in the cores: (shape - e) / (1 - e)
    fin = math_("DIVIDE", math_("SUBTRACT", shape, ero), math_("SUBTRACT", 1.001, ero), clamp=True)
    edge = node("ShaderNodeMapRange", "soft_edge", interpolation_type="SMOOTHSTEP")
    edge.inputs[1].default_value = 0.0; edge.inputs[2].default_value = 0.08
    L.new(fin, edge.inputs[0])
    # towards the sides of the layer the clouds thin out (no straight cut along the horizon)
    rel = node("ShaderNodeVectorMath", "center", operation="SUBTRACT")    # inputs[1]: centre of the layer
    L.new(geo.outputs["Position"], rel.inputs[0])
    flat2 = node("ShaderNodeVectorMath", operation="MULTIPLY")
    flat2.inputs[1].default_value = (1.0, 1.0, 0.0)
    L.new(rel.outputs[0], flat2.inputs[0])
    rlen = node("ShaderNodeVectorMath", operation="LENGTH")
    L.new(flat2.outputs[0], rlen.inputs[0])
    side = node("ShaderNodeMapRange", "side_fade", interpolation_type="SMOOTHSTEP")
    side.inputs[1].default_value = 0.6 * HALF_WIDTH; side.inputs[2].default_value = 0.97 * HALF_WIDTH
    side.inputs[3].default_value = 1.0; side.inputs[4].default_value = 0.0
    L.new(rlen.outputs["Value"], side.inputs[0])
    dens = math_("MULTIPLY", math_("MULTIPLY", edge.outputs[0], side.outputs[0]), None, name="density")
    # light: Henyey-Greenstein, forward. Water droplets scatter much more forward (the MIE phase), but in Cycles a
    # path then needs hundreds of bounces to turn that into the white of a cloud (with 24: a grey veil). The same
    # look with a few bounces: a moderate forward lobe (still the glow against the sun) with the density of a real
    # cloud seen through it (similarity theory: what counts is density x (1 - anisotropy)). One lobe only: Cycles
    # has room for two volume closures, the other one is the haze below.
    vs = node("ShaderNodeVolumeScatter", "scatter")
    vs.inputs["Anisotropy"].default_value = 0.55
    try:
        vs.phase = "HENYEY_GREENSTEIN"
    except (TypeError, AttributeError):
        pass
    # haze between the eye and the cloud (aerial perspective): far clouds fade into the colour of the haze. The
    # compositor cannot do it (a volume has no depth in the Mist pass), so the cloud does it itself, only for the
    # rays of the camera: there the cloud scatters (1 - h) of the light and glows with the haze for h (absorption
    # keeps the same extinction). The light inside the clouds and their shadows stay the same.
    # The haze is a layer near the ground (ambience.HAZE_H): of the path to a cloud at height z only
    # H (1 - exp(-z / H)) / z is in it - the same haze as the sky behind the cloud, so no dark or light rims.
    eye = node("ShaderNodeVectorMath", "eye", operation="DISTANCE")        # inputs[1]: the camera (render_settings)
    L.new(geo.outputs["Position"], eye.inputs[0])
    ez = node("ShaderNodeValue", "eye_z")
    zr = math_("MAXIMUM", math_("SUBTRACT", sep.outputs[2], ez.outputs[0]), 1.0)
    from .ambience import HAZE_H
    frac = math_("DIVIDE", math_("MULTIPLY", math_("SUBTRACT", 1.0, math_("EXPONENT", math_("DIVIDE", zr, -HAZE_H))), HAZE_H), zr)
    hk = math_("MULTIPLY", math_("MULTIPLY", eye.outputs["Value"], frac), None, name="haze_k")      # -1 / visibility
    hz = math_("SUBTRACT", 1.0, math_("EXPONENT", hk))
    lp = node("ShaderNodeLightPath")
    hc = math_("MULTIPLY", hz, lp.outputs["Is Camera Ray"])
    # light inside the cloud (every ray but the camera's): a lighter cloud, light_k of the density. A thick cloud
    # needs hundreds of bounces to carry the light into its shadowed parts (with a few: black grain); the lighter
    # medium carries it in a few, as the multiple-scattering approximations of film and games do (Wrenninge). The
    # camera still sees the full density: sharp edges and the detail of the billows.
    # Lighter by order of scattering: the shadows of the light that scatters once (Ray Depth 0) see the full
    # cloud - the self shadows of the billows - each further bounce light_k^depth of it.
    lk = node("ShaderNodeValue", "light_k")
    kd = math_("POWER", lk.outputs[0], lp.outputs["Ray Depth"])
    notcam = math_("SUBTRACT", 1.0, lp.outputs["Is Camera Ray"])
    keep = math_("MULTIPLY", dens, math_("SUBTRACT", math_("SUBTRACT", 1.0, hc),
                                         math_("MULTIPLY", notcam, math_("SUBTRACT", 1.0, kd))))
    L.new(keep, vs.inputs["Density"])
    hd = math_("MULTIPLY", dens, hc)
    ab = node("ShaderNodeVolumeAbsorption")
    ab.inputs["Color"].default_value = (0.0, 0.0, 0.0, 1.0)
    L.new(hd, ab.inputs["Density"])
    em = node("ShaderNodeEmission", "haze_glow")
    L.new(hd, em.inputs["Strength"])
    add2 = node("ShaderNodeAddShader")
    L.new(vs.outputs[0], add2.inputs[0]); L.new(ab.outputs[0], add2.inputs[1])
    add3 = node("ShaderNodeAddShader")
    L.new(add2.outputs[0], add3.inputs[0]); L.new(em.outputs[0], add3.inputs[1])
    L.new(add3.outputs[0], out.inputs["Volume"])
    try:
        mat.cycles.volume_sampling = "MULTIPLE_IMPORTANCE"
        mat.cycles.volume_interpolation = "LINEAR"
        # Cycles marches a procedural volume in steps that grow with the size of its box (here 60 km): a quarter
        # of them, so the billows (down to ~35 m) are not smeared into soft grey blobs
        mat.cycles.volume_step_rate = 0.25
    except (AttributeError, TypeError):
        pass
    return mat


def _layer2_object(coll, on):
    """The box of the second layer (its own mesh and material), or none."""
    from .core import INTERNAL_KEY
    ob = next((o for o in _find_all(CLOUD_KEY) if o.get(LAYER_KEY)), None)
    if not on:
        if ob is not None:
            me = ob.data
            bpy.data.objects.remove(ob, do_unlink=True)
            if me is not None and me.users == 0:
                bpy.data.meshes.remove(me)
        return None
    if ob is None:
        me = bpy.data.meshes.new(MAT2)
        v = [(x, y, z) for x in (-1, 1) for y in (-1, 1) for z in (-1, 1)]
        f = [(0, 1, 3, 2), (4, 6, 7, 5), (0, 4, 5, 1), (2, 3, 7, 6), (0, 2, 6, 4), (1, 5, 7, 3)]
        me.from_pydata(v, [], f)
        me.update()
        ob = bpy.data.objects.new(MAT2, me)
        ob[CLOUD_KEY] = 99
        ob[LAYER_KEY] = 2
        ob[INTERNAL_KEY] = 1
        ob.hide_select = True
    if ob.name not in coll.objects:
        coll.objects.link(ob)
    ob.hide_viewport = True
    ob.hide_render = False
    ob.cycles.is_caustics_caster = ob.cycles.is_caustics_receiver = False
    mat = _material(MAT2)
    if not ob.data.materials:
        ob.data.materials.append(mat)
    elif ob.data.materials[0] != mat:
        ob.data.materials[0] = mat
    return ob


def _set_shape(obs, s, c, seed_add=0):
    """Numbers of the shape: coverage, size, seed, heights, flat bottom, puffs, density."""
    from .ambience import _scene_box
    mat = obs[0].data.materials[0]
    nt = mat.node_tree
    base, thick = c["height"], c["thickness"]
    lo, hi = _scene_box()
    cx, cy = (lo.x + hi.x) / 2, (lo.y + hi.y) / 2
    gz = lo.z
    # (1.76.17: the height is the user's - with the camera inside or above the clouds if he wants: never raised, Luca
    # «Non alzare niente!»)
    z0, z1 = gz + base, gz + base + thick
    for ob, (x0, x1, y0, y1) in zip(obs, _tiles()):
        ob.location = Vector((cx + (x0 + x1) / 2, cy + (y0 + y1) / 2, (z0 + z1) / 2))
        ob.scale = Vector(((x1 - x0) / 2, (y1 - y0) / 2, thick / 2))
        ob.visible_shadow = True
    nt.nodes["center"].inputs[1].default_value = (cx, cy, 0.0)
    nt.nodes["height"].inputs[1].default_value = z0
    nt.nodes["height"].inputs[2].default_value = z1
    flat = c["flat"]
    nt.nodes["bottom"].inputs[2].default_value = 0.03 + 0.35 * (1.0 - flat)      # flat: the base is sharp
    nt.nodes["top"].inputs[2].default_value = 0.90                              # (the domes make the tops)
    # masses: from 1 km (size 0) to 8 km (size 1)
    mass = 1000.0 * (1.0 + 7.0 * c["scale"] ** 1.3)
    nt.nodes["mass_scale"].inputs["Scale"].default_value = 1.0 / mass
    seed = float((int(s["clouds"].get("seed", 7)) + seed_add) % 997)      # (small offsets: big ones lose float precision)
    nt.nodes["seed"].inputs[1].default_value = (seed * 13.7, seed * 7.31, seed * 3.17)
    cover = c["cover"]
    t = 0.63 - 0.34 * cover                     # noise above t becomes cloud
    nt.nodes["cover_lo"].inputs[1].default_value = t
    nt.nodes["cover_lo"].inputs[2].default_value = t + 0.12
    puff = max(70.0, min(500.0, 0.08 * mass))
    nt.nodes["puff_scale"].inputs["Scale"].default_value = 1.0 / puff
    nt.nodes["detail_scale"].inputs["Scale"].default_value = 1.0 / (puff * 1.5)
    nt.nodes["warp"].inputs["Scale"].default_value = puff * 0.9
    nt.nodes["puff"].inputs[1].default_value = 0.15 + 0.6 * c["puff"]
    nt.nodes["density"].inputs[1].default_value = SIGMA_MAX * (0.15 + 0.85 * c["density"])
    nt.nodes["light_k"].outputs[0].default_value = LIGHT_K
    tint = s["clouds"].get("color")
    col = tuple(tint[:3]) + (1.0,) if isinstance(tint, (list, tuple)) and len(tint) >= 3 else (1.0, 1.0, 1.0, 1.0)
    nt.nodes["scatter"].inputs["Color"].default_value = col
    from .ambience import fog_visibility, _fog_color
    dens = float(s["fog"]["density"])
    nt.nodes["haze_k"].inputs[1].default_value = -1.0 / fog_visibility(dens) if dens >= 0.005 else 0.0
    nt.nodes["haze_glow"].inputs["Color"].default_value = (*_fog_color(s), 1.0)
    return z0, z1


def _cloud_sun(coll, s, v, elev, z_mid):
    """The sun of the clouds: only the clouds (light linking), with the colour of the sunlight at their height."""
    from .ambience import sun_rgb, K, _aim_sun
    from .core import INTERNAL_KEY
    # from up there the sun sets later: dip of the horizon = sqrt(2 h / R)
    dip = math.degrees(math.sqrt(2.0 * max(0.0, z_mid) / 6371000.0))
    sky = dict(s["sky"])
    sky["altitude"] = float(sky.get("altitude", 100.0)) + z_mid
    e = sun_rgb(elev + dip, sky)
    ob = _find(CLOUD_SUN_KEY)
    if max(e) <= 0:
        if ob is not None:
            ob.data.energy = 0.0
            ob.hide_render = True
        return ob
    if ob is None:
        data = bpy.data.lights.new("Simpler Sole delle nuvole", "SUN")
        ob = bpy.data.objects.new("Simpler Sole delle nuvole", data)
        ob[CLOUD_SUN_KEY] = True
        ob[INTERNAL_KEY] = 1
        ob.hide_select = True
    if ob.name not in coll.objects:
        coll.objects.link(ob)
    ob.hide_viewport = True
    ob.hide_render = False
    d = ob.data
    mx = max(e)
    d.color = tuple(x / mx for x in e)
    d.energy = mx * K * float(s["sun"]["intensity"])
    d.angle = math.radians(max(0.05, float(s["sun"]["size"])))
    if hasattr(d.cycles, "is_caustics_light"):
        d.cycles.is_caustics_light = False
    # the direction: the real one. With the sun under the horizon of the ground (but still above that of the
    # clouds, up to -dip) its rays rise from below: they light the bases of the clouds - the pink and orange
    # undersides of a sunset under a sky already blue
    vv = Vector(v)
    if elev < -0.95 * dip:
        flat = Vector((vv.x, vv.y, 0.0)).normalized()
        a = math.radians(-0.95 * dip)
        vv = Vector((flat.x * math.cos(a), flat.y * math.cos(a), math.sin(a)))
    _aim_sun(ob, vv)
    # only the clouds, and only the clouds block it (rays rising from under the horizon: the ground and the scene
    # are not in their way up there)
    _link(ob, "receiver_collection", coll)
    _link(ob, "blocker_collection", coll)
    for co in coll.collection_objects:
        if co.light_linking.link_state != "INCLUDE":
            co.light_linking.link_state = "INCLUDE"
    return ob


def update(s, v=None, elev=None):
    """Called by ambience.apply: the clouds follow the Ambiente (or go away)."""
    if not active(s):
        remove()
        return
    from .ambience import _find_flag, SUN_KEY, _sun_dir
    if v is None:
        v = _sun_dir(s)
        elev = math.degrees(math.asin(max(-1.0, min(1.0, v.z))))
    c = settings(s)
    coll = _collection()
    obs = _volume_objects(coll)
    z0, z1 = _set_shape(obs, s, c)
    up = _layer2_object(coll, c["layer2"] and c["layer2Cover"] > 0.005)
    if up is not None:
        _set_shape([up], s, layer2_settings(c), seed_add=101)
        obs = obs + [up]
    _cloud_sun(coll, s, v, elev, (z0 + z1) / 2)
    # the sun of the scene: does not light the clouds (theirs does), and with the shadows off it is not blocked
    sun = _find_flag(SUN_KEY)
    if sun is not None:
        excl = bpy.data.collections.get(COLL + " (solo volume)")
        if excl is None:
            from .core import INTERNAL_KEY
            excl = bpy.data.collections.new(COLL + " (solo volume)")
            excl[INTERNAL_KEY] = 1
        for ob in obs:
            if ob.name not in excl.objects:
                excl.objects.link(ob)
        for co in excl.collection_objects:
            if co.light_linking.link_state != "EXCLUDE":
                co.light_linking.link_state = "EXCLUDE"
        _link(sun, "receiver_collection", excl)
        _link(sun, "blocker_collection", None if c["shadows"] else excl)


def render_settings(scene, final):
    """Before an image with volumetric clouds: enough volume bounces for white clouds, guiding, far clip."""
    if _find(CLOUD_KEY) is None:
        return
    cy = scene.cycles
    want = 24 if final else 6
    cy.volume_bounces = max(cy.volume_bounces, want)
    cy.max_bounces = max(cy.max_bounces, want + 2)
    try:
        cy.use_volume_guiding = True
    except AttributeError:
        pass
    # ray marching (biased): tens of times faster than the null scattering of Cycles on a volume this large and
    # this dense (each ray crosses kilometres of it), and with small steps the clouds look the same.
    # 1.73.6: the final render with the steps of the view (0.5, was 0.25): measured on a sunset over the sea, sky
    # in the frame, 40 samples - 274 s -> 159 s (-42%), the picture the same but for the noise (mean 1.6/255); with
    # the clouds out of the frame (their shadows only) -39% per sample
    try:
        cy.volume_biased = True
        cy.volume_step_rate = 0.5
        cy.volume_max_steps = max(cy.volume_max_steps, 4096)
    except AttributeError:
        pass
    cam = scene.camera
    if cam is not None:
        if cam.data.clip_end < 2.5 * HALF_WIDTH:
            cam.data.clip_end = 2.5 * HALF_WIDTH
        for ob in _find_all(CLOUD_KEY):                  # (each layer has its material)
            eye = ob.data.materials[0].node_tree.nodes.get("eye") if ob.data.materials else None
            if eye is not None:
                pos = tuple(cam.matrix_world.translation)
                if tuple(eye.inputs[1].default_value) != pos:
                    eye.inputs[1].default_value = pos
                    ez = ob.data.materials[0].node_tree.nodes.get("eye_z")
                    if ez is not None:          # (a material of an older version has no eye_z: no error)
                        ez.outputs[0].default_value = pos[2]
