"""Decals: a picture (PNG with transparency) projected onto a model, like a sticker, a stain or a sign.

A decal is an object of its own (kind "decal"), child of the piece it was dropped on. Its box of projection is
its local space: X width, Y length, Z depth (Z = the normal of the surface, pointing out of it). A geometry-nodes
modifier takes the surface of the piece inside the box (faces entirely beyond one side of the box or turned away are
dropped), lifts it a hair towards the front of the box, maps the picture by the box (UVMap: X and Y of the box, 0-1) and marks
how far from the middle of the box each point is (decal_fade: 0 in the middle, 1 at the front and back faces).
The material reads the picture with "clip" extension (transparent outside the box), multiplies it by the tint and
fades it at the depth limits. The models are never touched: no UV, no material of theirs changes.

The real-time view builds the same geometry from GET /api/decal/mesh (the evaluated mesh of the modifier) and the
picture from GET /api/decal/png; the "rev" of the object changes when anything that shapes it changes.
"""
import hashlib
import json
import math
import os

import bpy
from mathutils import Matrix, Vector

from .core import ID_KEY, INTERNAL_KEY, KIND_KEY, ApiError, CM, ensure_id, find, refresh
from .i18n import tr

DECAL_KEY = "simpler_decal"
GROUP_NAME = "Simpler Decal"
GROUP_VERSION = 5
DEFAULTS = {"w": 50.0, "l": 50.0, "d": 20.0, "opacity": 1.0, "tint": [1.0, 1.0, 1.0], "rough": 0.6,
            "metal": 0.0, "emit": 0.0, "order": 0, "image": "", "file": "", "maps": {}, "mode": "alpha", "source": "",
            "nstr": 1.0, "ndx": False, "angle": 90.0}
# angle (Luca: «una decal con un motivo di sporcizia su un sacco tondeggiante … con un buon risultato»): the decal fades
# where the surface turns more than this away from the direction it projects (degrees; 90 = everywhere, as before).
# New decals start at NEW_ANGLE (no smear on tyres, steps, posts in the box); saved ones stay at 90.
NEW_ANGLE = 70.0
ANGLE_SOFT = 8.0         # degrees: the fade goes from angle - this to angle + this


def angle_fade(p, facing):
    """How much a surface |cos| = facing away from the projection keeps of the decal (0..1)."""
    a = float(p.get("angle", 90.0))
    if a >= 90.0:
        return 1.0
    lo = math.cos(math.radians(min(90.0, a + ANGLE_SOFT)))
    hi = math.cos(math.radians(max(0.0, a - ANGLE_SOFT)))
    t = max(0.0, min(1.0, (facing - lo) / max(1e-6, hi - lo)))
    return t * t * (3 - 2 * t)
# mode: "alpha" = the picture's own transparency (your PNGs); "opacity" = a separate opacity map (ambientCG road lines,
# manholes...); "multiply" = no opacity at all: the picture darkens what is under it like a stain (ambientCG leaks)
DATA_MAPS = ("opacity", "normal", "roughness", "metalness")
USER_MAPS = DATA_MAPS + ("emission",)     # what the panel can set (emission: a colour picture, sRGB - neon, signs)
# nstr: strength of the normal map; ndx: the normal map is DirectX style (green upside down)
LIFT = 0.0008            # m: how far the decal stands off the surface (plus a little more for each step of "order")


def params(ob):
    try:
        p = json.loads(ob.get(DECAL_KEY) or "{}")
    except ValueError:
        p = {}
    out = dict(DEFAULTS)
    out.update({k: v for k, v in p.items() if k in DEFAULTS})
    return out


def is_decal(ob):
    return ob is not None and ob.get(KIND_KEY) == "decal"


def info(ob):
    """For object_json: the values of the panel and a revision of the shape (the view fetches the mesh again when
    it changes)."""
    p = params(ob)
    ml = ob.matrix_local
    key = json.dumps(p, sort_keys=True) + "|" + ",".join(f"{v:.5f}" for row in ml for v in row) + "|" + (ob.parent.name if ob.parent else "") \
        + "|" + str(ob.get("simpler_decal_targets") or "")
    im = bpy.data.images.get(p["image"]) if p["image"] else None
    size = list(im.size) if im is not None else [0, 0]
    return {**p, "rev": hashlib.sha1(key.encode()).hexdigest()[:12], "size": size,
            "has": sorted((p["maps"] or {}).keys()) if isinstance(p["maps"], dict) else []}


# ---------------------------------------------------------------- geometry nodes

def _new_group(name):
    """The node tree of one decal. Its values (target, sizes, lift, material) are set on its nodes by apply(): each
    decal has its own small tree (an input of type Object on a shared group made Blender's evaluation hang)."""
    ng = bpy.data.node_groups.new(name, "GeometryNodeTree")
    ng["simpler_version"] = GROUP_VERSION
    it = ng.interface
    it.new_socket("Geometry", in_out="INPUT", socket_type="NodeSocketGeometry")
    it.new_socket("Geometry", in_out="OUTPUT", socket_type="NodeSocketGeometry")
    N, L = ng.nodes, ng.links

    def node(kind, x, y, **props):
        n = N.new(kind)
        n.location = (x, y)
        for k, v in props.items():
            setattr(n, k, v)
        return n

    gout = node("NodeGroupOutput", 1400, 0)
    oinfo = node("GeometryNodeObjectInfo", -1350, 200, transform_space="RELATIVE")
    oinfo.name = "Target"
    vals = node("ShaderNodeCombineXYZ", -1600, -200)
    vals.name = "Size"
    liftv = node("ShaderNodeValue", 650, -250)
    liftv.name = "Lift"
    real = node("GeometryNodeRealizeInstances", -1150, 200)
    L.new(oinfo.outputs["Geometry"], real.inputs["Geometry"])

    # q = position / half size: the box is -1..1 on every axis
    size = vals
    half = node("ShaderNodeVectorMath", -1150, -200, operation="SCALE")
    L.new(size.outputs[0], half.inputs[0])
    half.inputs["Scale"].default_value = 0.5
    pos = node("GeometryNodeInputPosition", -1150, -400)
    q = node("ShaderNodeVectorMath", -950, -300, operation="DIVIDE")
    L.new(pos.outputs[0], q.inputs[0])
    L.new(half.outputs[0], q.inputs[1])
    sep = node("ShaderNodeSeparateXYZ", -750, -300)
    L.new(q.outputs[0], sep.inputs[0])

    # a face goes when all its corners are beyond the same side of the box (a big wall that crosses the box stays)
    beyond = None
    y = -100
    for axis in range(3):
        for op, lim in (("GREATER_THAN", 1.0), ("LESS_THAN", -1.0)):
            cmp = node("FunctionNodeCompare", -550, y, data_type="FLOAT", operation=op)
            L.new(sep.outputs[axis], cmp.inputs[0])
            cmp.inputs[1].default_value = lim
            dom = node("GeometryNodeFieldOnDomain", -350, y, domain="POINT", data_type="FLOAT")
            L.new(cmp.outputs[0], dom.inputs[0])
            alls = node("FunctionNodeCompare", -150, y, data_type="FLOAT", operation="GREATER_THAN")
            L.new(dom.outputs[0], alls.inputs[0])
            alls.inputs[1].default_value = 0.999
            if beyond is None:
                beyond = alls.outputs[0]
            else:
                orn = node("FunctionNodeBooleanMath", 50, y, operation="OR")
                L.new(beyond, orn.inputs[0])
                L.new(alls.outputs[0], orn.inputs[1])
                beyond = orn.outputs[0]
            y -= 160
    # faces turned away from the projection (or seen edge-on) would smear the picture
    nrm = node("GeometryNodeInputNormal", -550, 400)
    nsep = node("ShaderNodeSeparateXYZ", -350, 400)
    L.new(nrm.outputs[0], nsep.inputs[0])
    # (both sides count: the faces of imported models are often turned the wrong way, and the view shows both)
    nabs = node("ShaderNodeMath", -250, 400, operation="ABSOLUTE")
    L.new(nsep.outputs[2], nabs.inputs[0])
    away = node("FunctionNodeCompare", -150, 400, data_type="FLOAT", operation="LESS_THAN")
    L.new(nabs.outputs[0], away.inputs[0])
    away.inputs[1].default_value = 0.15
    drop = node("FunctionNodeBooleanMath", 250, 300, operation="OR")
    L.new(beyond, drop.inputs[0])
    L.new(away.outputs[0], drop.inputs[1])
    delete = node("GeometryNodeDeleteGeometry", 450, 200, domain="FACE", mode="ALL")
    L.new(real.outputs[0], delete.inputs["Geometry"])
    L.new(drop.outputs[0], delete.inputs["Selection"])

    # cut to the box: a face crossing it (the big face of a road, a floor, a wall) was kept whole - invisible
    # beyond the box, but still a transparent surface there for the path tracer. Copies of a decal side by side then
    # lay on top of each other all along the road, at the same height: the rays went through one and missed the
    # other (it came out faded, patchy). Only the faces crossing a side of the box go through the cut (Boolean,
    # float solver: fast); the ones inside it stay as they are. The view already cut them the same way (mesh()).
    qa = node("ShaderNodeVectorMath", -550, -700, operation="ABSOLUTE")
    L.new(q.outputs[0], qa.inputs[0])
    qs = node("ShaderNodeSeparateXYZ", -350, -700)
    L.new(qa.outputs[0], qs.inputs[0])
    mx1 = node("ShaderNodeMath", -150, -700, operation="MAXIMUM")
    L.new(qs.outputs[0], mx1.inputs[0]); L.new(qs.outputs[1], mx1.inputs[1])
    mx2 = node("ShaderNodeMath", 50, -700, operation="MAXIMUM")
    L.new(mx1.outputs[0], mx2.inputs[0]); L.new(qs.outputs[2], mx2.inputs[1])
    inpt = node("FunctionNodeCompare", 250, -700, data_type="FLOAT", operation="LESS_EQUAL")
    L.new(mx2.outputs[0], inpt.inputs[0]); inpt.inputs[1].default_value = 1.0
    ind = node("GeometryNodeFieldOnDomain", 450, -700, domain="POINT", data_type="FLOAT")
    L.new(inpt.outputs[0], ind.inputs[0])
    inside = node("FunctionNodeCompare", 650, -700, data_type="FLOAT", operation="GREATER_THAN")
    L.new(ind.outputs[0], inside.inputs[0]); inside.inputs[1].default_value = 0.999
    split = node("GeometryNodeSeparateGeometry", 650, 0, domain="FACE")
    L.new(delete.outputs[0], split.inputs["Geometry"])
    L.new(inside.outputs[0], split.inputs["Selection"])
    tag = node("GeometryNodeStoreNamedAttribute", 850, -100, data_type="BOOLEAN", domain="FACE")
    tag.inputs["Name"].default_value = "decal_src"
    tag.inputs["Value"].default_value = True
    L.new(split.outputs["Inverted"], tag.inputs["Geometry"])
    box = node("GeometryNodeMeshCube", 850, -300)
    L.new(size.outputs[0], box.inputs["Size"])
    cut = node("GeometryNodeMeshBoolean", 1050, -100, operation="INTERSECT", solver="FLOAT")
    cut.name = "Cut"
    L.new(tag.outputs[0], cut.inputs["Mesh 2"])
    L.new(box.outputs[0], cut.inputs["Mesh 2"])
    src = node("GeometryNodeInputNamedAttribute", 1050, -300, data_type="BOOLEAN")
    src.inputs["Name"].default_value = "decal_src"
    notsrc = node("FunctionNodeBooleanMath", 1250, -300, operation="NOT")
    L.new(src.outputs[0], notsrc.inputs[0])
    nobox = node("GeometryNodeDeleteGeometry", 1250, -100, domain="FACE", mode="ALL")
    L.new(cut.outputs[0], nobox.inputs["Geometry"])
    L.new(notsrc.outputs[0], nobox.inputs["Selection"])
    joined = node("GeometryNodeJoinGeometry", 1450, 0)
    L.new(split.outputs["Selection"], joined.inputs[0])
    L.new(nobox.outputs[0], joined.inputs[0])
    clean = node("GeometryNodeRemoveAttribute", 1650, 0)
    clean.inputs["Name"].default_value = "decal_src"
    L.new(joined.outputs[0], clean.inputs["Geometry"])

    # UV from the box (corners), fade from the depth (points)
    uvv = node("ShaderNodeVectorMath", -550, -1100, operation="MULTIPLY_ADD")
    L.new(q.outputs[0], uvv.inputs[0])
    uvv.inputs[1].default_value = (0.5, 0.5, 0.0)
    uvv.inputs[2].default_value = (0.5, 0.5, 0.0)
    st_uv = node("GeometryNodeStoreNamedAttribute", 650, 200, data_type="FLOAT2", domain="CORNER")
    st_uv.inputs["Name"].default_value = "UVMap"
    L.new(clean.outputs[0], st_uv.inputs["Geometry"])
    L.new(uvv.outputs[0], st_uv.inputs["Value"])
    fade = node("ShaderNodeMath", -350, -1250, operation="ABSOLUTE")
    L.new(sep.outputs[2], fade.inputs[0])
    st_f = node("GeometryNodeStoreNamedAttribute", 850, 200, data_type="FLOAT", domain="POINT")
    st_f.inputs["Name"].default_value = "decal_fade"
    L.new(st_uv.outputs[0], st_f.inputs["Geometry"])
    L.new(fade.outputs[0], st_f.inputs["Value"])

    # how much each point faces the projection (|z| of its normal, both sides): the material fades it by «angle»
    fnrm = node("GeometryNodeInputNormal", 650, 500)
    fsep = node("ShaderNodeSeparateXYZ", 800, 500)
    L.new(fnrm.outputs[0], fsep.inputs[0])
    fabs = node("ShaderNodeMath", 950, 500, operation="ABSOLUTE")
    L.new(fsep.outputs[2], fabs.inputs[0])
    st_n = node("GeometryNodeStoreNamedAttribute", 950, 300, data_type="FLOAT", domain="POINT")
    st_n.inputs["Name"].default_value = "decal_facing"
    L.new(st_f.outputs[0], st_n.inputs["Geometry"])
    L.new(fabs.outputs[0], st_n.inputs["Value"])

    # a hair off the surface, towards the front of the box (where it is looked at from), whatever way the face points
    lift = node("ShaderNodeCombineXYZ", 850, -100)
    L.new(liftv.outputs[0], lift.inputs[2])
    setp = node("GeometryNodeSetPosition", 1050, 200)
    L.new(st_n.outputs[0], setp.inputs["Geometry"])
    L.new(lift.outputs[0], setp.inputs["Offset"])
    setm = node("GeometryNodeSetMaterial", 1250, 200)
    setm.name = "Material"
    L.new(setp.outputs[0], setm.inputs["Geometry"])
    L.new(setm.outputs[0], gout.inputs[0])
    return ng


# ---------------------------------------------------------------- material

def _material(ob, p):
    mat = None
    mod = ob.modifiers.get("Simpler Decal")
    if mod is not None and mod.node_group is not None and mod.node_group.nodes.get("Material") is not None:
        mat = mod.node_group.nodes["Material"].inputs["Material"].default_value
    if mat is None or mat.users > 1:            # (a duplicate shares it: its own copy)
        mat = bpy.data.materials.new(tr("Decal") + " · " + ob.name) if mat is None else mat.copy()
    mat.use_nodes = True
    nt = mat.node_tree
    nt.nodes.clear()
    N, L = nt.nodes, nt.links
    out = N.new("ShaderNodeOutputMaterial"); out.location = (700, 0)
    bsdf = N.new("ShaderNodeBsdfPrincipled"); bsdf.location = (400, 0)
    L.new(bsdf.outputs[0], out.inputs["Surface"])
    uv = N.new("ShaderNodeUVMap"); uv.location = (-700, 0); uv.uv_map = "UVMap"
    tex = N.new("ShaderNodeTexImage"); tex.location = (-450, 0)
    tex.extension = "CLIP"
    tex.interpolation = "Linear"
    im = bpy.data.images.get(p["image"]) if p["image"] else None
    tex.image = im
    L.new(uv.outputs[0], tex.inputs["Vector"])
    tint = N.new("ShaderNodeMix"); tint.location = (-150, 150)
    tint.data_type = "RGBA"; tint.blend_type = "MULTIPLY"
    tint.inputs["Factor"].default_value = 1.0
    L.new(tex.outputs["Color"], tint.inputs[6])
    t = p["tint"] if isinstance(p["tint"], list) and len(p["tint"]) == 3 else [1, 1, 1]
    tint.inputs[7].default_value = (float(t[0]), float(t[1]), float(t[2]), 1.0)
    maps = p["maps"] if isinstance(p["maps"], dict) else {}

    def data_tex(channel, y):
        im2 = bpy.data.images.get(maps.get(channel) or "")
        if im2 is None:
            return None
        try:
            im2.colorspace_settings.name = "Non-Color"
        except TypeError:
            pass
        n = N.new("ShaderNodeTexImage"); n.location = (-450, y)
        n.image = im2; n.extension = "CLIP"; n.interpolation = "Linear"
        L.new(uv.outputs[0], n.inputs["Vector"])
        return n
    # alpha = picture (or opacity map) * opacity * (1 - fade^4): gone at the front and back of the box
    attr = N.new("ShaderNodeAttribute"); attr.location = (-450, -300); attr.attribute_name = "decal_fade"
    pw = N.new("ShaderNodeMath"); pw.location = (-250, -300); pw.operation = "POWER"
    L.new(attr.outputs["Fac"], pw.inputs[0]); pw.inputs[1].default_value = 4.0
    inv = N.new("ShaderNodeMath"); inv.location = (-80, -300); inv.operation = "SUBTRACT"; inv.use_clamp = True
    inv.inputs[0].default_value = 1.0
    L.new(pw.outputs[0], inv.inputs[1])
    a1 = N.new("ShaderNodeMath"); a1.location = (80, -200); a1.operation = "MULTIPLY"
    op_tex = data_tex("opacity", -600) if p["mode"] == "opacity" else None
    if op_tex is not None:
        L.new(op_tex.outputs["Color"], a1.inputs[0])
    else:
        L.new(tex.outputs["Alpha"], a1.inputs[0])
    keep = inv.outputs[0]
    ang = float(p.get("angle", 90.0))
    if ang < 90.0:
        # (angle) faded where the surface turns away from the projection: smoothstep on |cos| as angle_fade()
        fa = N.new("ShaderNodeAttribute"); fa.location = (-450, -450); fa.attribute_name = "decal_facing"
        mr = N.new("ShaderNodeMapRange"); mr.location = (-250, -450); mr.interpolation_type = "SMOOTHSTEP"; mr.clamp = True
        L.new(fa.outputs["Fac"], mr.inputs["Value"])
        mr.inputs["From Min"].default_value = math.cos(math.radians(min(90.0, ang + ANGLE_SOFT)))
        mr.inputs["From Max"].default_value = math.cos(math.radians(max(0.0, ang - ANGLE_SOFT)))
        km = N.new("ShaderNodeMath"); km.location = (-80, -450); km.operation = "MULTIPLY"
        L.new(inv.outputs[0], km.inputs[0]); L.new(mr.outputs["Result"], km.inputs[1])
        keep = km.outputs[0]
    L.new(keep, a1.inputs[1])
    a2 = N.new("ShaderNodeMath"); a2.location = (240, -200); a2.operation = "MULTIPLY"; a2.use_clamp = True
    L.new(a1.outputs[0], a2.inputs[0]); a2.inputs[1].default_value = max(0.0, min(1.0, float(p["opacity"])))
    if p["mode"] == "multiply":
        # a stain: what is under it seen through a layer tinted with the picture (white = nothing, dark = darker)
        tr_ = N.new("ShaderNodeBsdfTransparent"); tr_.location = (150, 300)
        L.new(tint.outputs[2], tr_.inputs["Color"])
        clear = N.new("ShaderNodeBsdfTransparent"); clear.location = (150, 450)
        mix = N.new("ShaderNodeMixShader"); mix.location = (450, 300)
        L.new(a2.outputs[0], mix.inputs["Fac"])
        L.new(clear.outputs[0], mix.inputs[1]); L.new(tr_.outputs[0], mix.inputs[2])
        L.new(mix.outputs[0], out.inputs["Surface"])
        # (the factor keeps the picture's alpha: 0 outside the box, where "clip" gives black, which would darken
        # the whole face of the piece the decal lies on)
    else:
        L.new(tint.outputs[2], bsdf.inputs["Base Color"])
        L.new(a2.outputs[0], bsdf.inputs["Alpha"])
    rt = data_tex("roughness", -850)
    if rt is not None:
        L.new(rt.outputs["Color"], bsdf.inputs["Roughness"])
    else:
        bsdf.inputs["Roughness"].default_value = max(0.0, min(1.0, float(p["rough"])))
    mt = data_tex("metalness", -1100)
    if mt is not None:
        L.new(mt.outputs["Color"], bsdf.inputs["Metallic"])
    else:
        bsdf.inputs["Metallic"].default_value = max(0.0, min(1.0, float(p["metal"])))
    nt_ = data_tex("normal", -1350)
    if nt_ is not None:
        nm = N.new("ShaderNodeNormalMap"); nm.location = (150, -1350); nm.uv_map = "UVMap"
        nm.inputs["Strength"].default_value = max(0.0, min(10.0, float(p["nstr"])))
        col = nt_.outputs["Color"]
        if p["ndx"]:
            # DirectX normal map: the green channel is turned over (1 - G)
            sc = N.new("ShaderNodeSeparateColor"); sc.location = (-200, -1500)
            L.new(col, sc.inputs["Color"])
            ig = N.new("ShaderNodeMath"); ig.location = (-40, -1500); ig.operation = "SUBTRACT"
            ig.inputs[0].default_value = 1.0
            L.new(sc.outputs["Green"], ig.inputs[1])
            cc = N.new("ShaderNodeCombineColor"); cc.location = (100, -1500)
            L.new(sc.outputs["Red"], cc.inputs["Red"]); L.new(ig.outputs[0], cc.inputs["Green"]); L.new(sc.outputs["Blue"], cc.inputs["Blue"])
            col = cc.outputs["Color"]
        L.new(col, nm.inputs["Color"])
        L.new(nm.outputs["Normal"], bsdf.inputs["Normal"])
    emit = max(0.0, float(p["emit"]))
    if emit > 0:
        em = bpy.data.images.get(maps.get("emission") or "")
        if em is not None:
            # emission map: only what is light in it glows (the writing of a neon sign), times the colour
            try:
                em.colorspace_settings.name = "sRGB"
            except TypeError:
                pass
            et = N.new("ShaderNodeTexImage"); et.location = (-450, -1650)
            et.image = em; et.extension = "CLIP"; et.interpolation = "Linear"
            L.new(uv.outputs[0], et.inputs["Vector"])
            emix = N.new("ShaderNodeMix"); emix.location = (-150, -1650)
            emix.data_type = "RGBA"; emix.blend_type = "MULTIPLY"
            emix.inputs["Factor"].default_value = 1.0
            L.new(et.outputs["Color"], emix.inputs[6])
            emix.inputs[7].default_value = (float(t[0]), float(t[1]), float(t[2]), 1.0)
            L.new(emix.outputs[2], bsdf.inputs["Emission Color"])
        else:
            L.new(tint.outputs[2], bsdf.inputs["Emission Color"])
        bsdf.inputs["Emission Strength"].default_value = emit
    mat["simpler_decal_material"] = True
    return mat


# ---------------------------------------------------------------- objects

def apply(ob):
    """Modifier and material from the values stored on the object."""
    p = params(ob)
    mod = ob.modifiers.get("Simpler Decal")
    if mod is None:
        mod = ob.modifiers.new("Simpler Decal", "NODES")
    ng = mod.node_group
    if ng is None or ng.get("simpler_version") != GROUP_VERSION or ng.users > 1:
        # (a duplicate shares the tree of its original: its own one)
        ng = _new_group(GROUP_NAME + " · " + ob.name)
        mod.node_group = ng
    mat = _material(ob, p)
    target = ob.parent if ob.parent is not None and ob.parent.type == "MESH" else bpy.data.objects.get(ob.get("simpler_decal_target") or "")
    targets = _targets(ob, p, target)
    ob["simpler_decal_targets"] = "|".join(t.name for t in targets)
    N = ng.nodes
    _set_targets(ng, targets)
    sz = N["Size"].inputs
    sz[0].default_value = max(0.001, float(p["w"]) * CM)
    sz[1].default_value = max(0.001, float(p["l"]) * CM)
    sz[2].default_value = max(0.001, float(p["d"]) * CM)
    # (plus a hair of its own: two decals of the same order that overlap are not at exactly the same height)
    own = int(hashlib.md5(str(ob.get(ID_KEY) or ob.name).encode()).hexdigest()[:4], 16) % 8
    N["Lift"].outputs[0].default_value = LIFT * (1 + max(0, int(p["order"]))) + 0.00004 * own
    N["Material"].inputs["Material"].default_value = mat
    ob.data.update()
    # it lies on the surface: it casts no shadow and is not seen by the shadow rays
    try:
        ob.visible_shadow = False
    except AttributeError:
        pass


MAX_TARGETS = 12


def _targets(ob, p, first):
    """The pieces the decal is projected on: the one it was dropped on and every other piece its box reaches (a
    manhole on the edge of a road reaches the sidewalk too; before, it was cut at the edge of its own model)."""
    inv = ob.matrix_world.inverted_safe()
    hw, hl, hd = p["w"] * CM / 2, p["l"] * CM / 2, p["d"] * CM / 2
    found = []
    for o in bpy.context.scene.objects:
        if o.type != "MESH" or o is ob or is_decal(o) or o.get(INTERNAL_KEY) or o.get("simpler_trashed") \
                or o.get("simpler_twin") or o.get("simpler_paint_data") or o.hide_render or o.data is None:
            continue
        m = inv @ o.matrix_world
        cs = [m @ Vector(c) for c in o.bound_box]
        lo = [min(c[i] for c in cs) for i in range(3)]
        hi = [max(c[i] for c in cs) for i in range(3)]
        if hi[0] < -hw or lo[0] > hw or hi[1] < -hl or lo[1] > hl or hi[2] < -hd or lo[2] > hd:
            continue
        # nearest to the middle of the box first (the limit keeps a decal in a crowded corner light)
        cx, cy, cz = (max(lo[0], min(0.0, hi[0])), max(lo[1], min(0.0, hi[1])), max(lo[2], min(0.0, hi[2])))
        found.append((cx * cx + cy * cy + cz * cz, o))
    found.sort(key=lambda t: t[0])
    out = [first] if first is not None else []
    for _d, o in found:
        if o not in out:
            out.append(o)
    return out[:MAX_TARGETS]


def _set_targets(ng, targets):
    """One Object Info per piece, joined before the cut (trees made before 1.28.6 had one, straight in)."""
    N, L = ng.nodes, ng.links
    join = N.get("Join")
    if join is None:
        join = N.new("GeometryNodeJoinGeometry")
        join.name = "Join"
        join.location = (-1250, 400)
        real = next(n for n in N if n.type == "REALIZE_INSTANCES")
        L.new(join.outputs[0], real.inputs["Geometry"])
        L.new(N["Target"].outputs["Geometry"], join.inputs[0])
    infos = [n for n in N if n.type == "OBJECT_INFO"]
    while len(infos) < max(1, len(targets)):
        n = N.new("GeometryNodeObjectInfo")
        n.transform_space = "RELATIVE"
        n.location = (-1450, 200 - 160 * len(infos))
        L.new(n.outputs["Geometry"], join.inputs[0])
        infos.append(n)
    for i, n in enumerate(infos):
        n.inputs["Object"].default_value = targets[i] if i < len(targets) else None


def _hit(location, normal):
    """The piece of the scene right under the point, along the normal (the real mesh: not a twin, not a decal)."""
    dg = bpy.context.evaluated_depsgraph_get()
    n = Vector(normal).normalized() if Vector(normal).length > 1e-6 else Vector((0, 0, 1))
    origin = Vector(location) + n * 0.05
    left = 0.25
    for _ in range(6):
        ok, loc, _nrm, _i, ob, _m = bpy.context.scene.ray_cast(dg, origin, -n, distance=left)
        if not ok or ob is None:
            return None
        ob = bpy.data.objects.get(ob.name) or ob
        if ob.get("simpler_twin"):
            con = next((c for c in ob.constraints if c.type == "COPY_TRANSFORMS"), None)
            ob = con.target if con is not None and con.target is not None else ob
        if ob.type == "MESH" and not ob.get(INTERNAL_KEY) and not is_decal(ob):
            return ob
        step = (loc - origin).length + 0.0005           # a decal (or something internal) first: look past it
        origin = origin - n * step
        left -= step
        if left <= 0:
            break
    return None


def _load(path):
    """The picture of a file for a decal: the one already in the project when it is the same file, otherwise a new one.
    (Luca: «sul pavimento bagnato non si vedono») check_existing alone gave back the copy packed in the project even
    after the file had changed on disk: a decal of the library made again (lighter mud) was dropped with the old
    picture, every time, in a project that had used it once."""
    im = bpy.data.images.load(path, check_existing=True)
    try:
        pf = im.packed_file
        if pf is not None and os.path.isfile(path) and pf.size != os.path.getsize(path):
            im = bpy.data.images.load(path, check_existing=False)
    except (OSError, RuntimeError):
        pass
    return im


def add(data):
    """POST /api/decal/add {file, location (cm), normal, camera (cm), width (cm)}: a new decal on the surface."""
    files = data.get("maps") if isinstance(data.get("maps"), dict) else {}
    if data.get("acg"):
        # an ambientCG decal already downloaded: its maps, its real size, its name; no opacity map = a stain
        from . import acgdecals
        aid = str(data["acg"])
        files = acgdecals.maps_of(aid) or {}
        if not files:
            raise ApiError(tr("Decal non ancora scaricata"))
        a = acgdecals.asset(aid) or {}
        if float(a.get("w") or 0) > 0 and float(a.get("l") or 0) > 0:
            data = dict(data, width=float(a["w"]), length=float(a["l"]))
        data = dict(data, name=a.get("name") or aid, source="ambientCG " + aid, multiply="opacity" not in files)
    path = str(files.get("color") or data.get("file") or "")
    if not os.path.isfile(path):
        raise ApiError(tr("File non trovato: {0}", path))
    loc = Vector([float(v) for v in data.get("location") or (0, 0, 0)]) * CM
    n = Vector([float(v) for v in data.get("normal") or (0, 0, 1)])
    n = n.normalized() if n.length > 1e-6 else Vector((0, 0, 1))
    cam = Vector([float(v) for v in data.get("camera") or (0, -5, 2)]) * CM
    target = _hit(loc, n)
    if target is None:
        # (Luca: «non capisco il messaggio rosso, la decal sembra funzionare bene») the short ray along the normal can
        # miss the piece the view itself hit (log: view hit a shop display, ray found nothing, the decal was projected
        # anyway on the 4 pieces its box reaches): that piece is the one under the point, as the view saw it
        try:
            hit = find(str(data.get("hitObject") or "").split("/")[0])
        except Exception:
            hit = None
        if hit is not None and hit.type == "MESH" and not hit.get(INTERNAL_KEY) and not is_decal(hit) \
                and not hit.get("simpler_trashed"):
            target = hit
    # the picture, embedded in the project (the decal travels with it)
    im = _load(path)
    if not im.packed_file:
        im.pack()
    im.colorspace_settings.name = "sRGB"
    w, h = im.size[:] if im.size[0] > 0 else (1, 1)
    width = max(1.0, float(data.get("width") or 50.0))
    length = width * h / max(1, w)
    if float(data.get("length") or 0) > 0:                 # real size known (ambientCG): as it is
        length = float(data["length"])
    maps = {}
    for channel in DATA_MAPS:
        f = files.get(channel)
        if f and os.path.isfile(f):
            im2 = _load(f)
            if not im2.packed_file:
                im2.pack()
            maps[channel] = im2.name
    mode = "opacity" if "opacity" in maps else ("multiply" if files and data.get("multiply") else "alpha")
    # orientation: Z = the normal; Y = "up" as the user sees it (world up on walls, away from the camera on floors)
    up = Vector((0, 0, 1))
    if abs(n.dot(up)) > 0.9:
        up = loc - cam
        up -= n * up.dot(n)
        if up.length < 1e-6:
            up = Vector((0, 1, 0))
    yv = (up - n * up.dot(n)).normalized()
    xv = yv.cross(n).normalized()
    rot = Matrix((xv, yv, n)).transposed().to_4x4()
    rot.translation = loc
    me = bpy.data.meshes.new(tr("Decal"))
    name = str(data.get("name") or "") or os.path.splitext(os.path.basename(path))[0]
    ob = bpy.data.objects.new(name, me)
    coll = target.users_collection[0] if target is not None and target.users_collection else bpy.context.scene.collection
    coll.objects.link(ob)
    ob[KIND_KEY] = "decal"
    p = dict(DEFAULTS)
    p.update({"w": round(width, 2), "l": round(length, 2), "d": round(max(5.0, min(width, length) * 0.4), 2),
              "image": im.name, "file": os.path.basename(path), "maps": maps, "mode": mode,
              "source": str(data.get("source") or ""), "angle": NEW_ANGLE})
    ob[DECAL_KEY] = json.dumps(p)
    ob.matrix_world = rot
    if target is not None:
        ob["simpler_decal_target"] = target.name
        if not target.get("simpler_paint_model"):
            ob.parent = target
            ob.matrix_parent_inverse = target.matrix_world.inverted()
    apply(ob)
    if target is None:
        # (Luca: «leggi il messaggio sotto, non capisco») a decal with nothing under it: where it was dropped and what
        # is below that point, in the engine log, to find what the view hit there
        try:
            from .core import log
            dg = bpy.context.evaluated_depsgraph_get()
            ok, hloc, _hn, _i, hob, _m = bpy.context.scene.ray_cast(dg, loc + Vector((0, 0, 0.01)), Vector((0, 0, -1)), distance=50.0)
            log("SIMPLER_DECAL", f"no piece under the drop: point={tuple(round(v, 3) for v in loc)} m normal={tuple(round(v, 3) for v in n)}"
                f" view hit={data.get('hitObject') or '-'} size={round(width)}x{round(length)} cm targets={ob.get('simpler_decal_targets') or '-'}"
                f" below={(hob.name + ' at %.2f m' % (loc.z - hloc.z)) if ok and hob is not None else 'nothing'}")
        except Exception:
            pass
    refresh()
    from .core import object_json
    return {"id": ensure_id(ob), "object": object_json(ob), "target": target.get(ID_KEY, "") if target is not None else ""}


def edit(data):
    """POST /api/decal/edit {id, w, l, d, opacity, tint, rough, metal, emit, order, nstr, ndx,
    maps: {channel: file path to set, "" to take away}}."""
    ob = find(data.get("id"))
    if not is_decal(ob):
        raise ApiError(tr("Non è una decal"))
    p = params(ob)
    for k in ("w", "l", "d", "opacity", "rough", "metal", "emit", "nstr"):
        if k in data:
            p[k] = float(data[k])
    if "angle" in data:
        p["angle"] = max(0.0, min(90.0, float(data["angle"])))
    if "ndx" in data:
        p["ndx"] = bool(data["ndx"])
    if isinstance(data.get("maps"), dict):
        maps = dict(p["maps"]) if isinstance(p["maps"], dict) else {}
        for channel, f in data["maps"].items():
            if channel not in USER_MAPS and channel != "color":
                continue
            f = str(f or "")
            if not f:
                if channel != "color":           # (the picture itself cannot be taken away, only changed)
                    maps.pop(channel, None)
                continue
            if os.path.isfile(f):
                im2 = _load(f)
            elif f in bpy.data.images:
                im2 = bpy.data.images[f]         # an image of the project (a map copied from a material or a decal)
            else:
                raise ApiError(tr("File non trovato: {0}", f))
            if not im2.packed_file and im2.source == "FILE":
                try:
                    im2.pack()                   # the decal travels with its maps, like its picture
                except RuntimeError:
                    pass
            if channel == "color":
                # the picture of the decal: changed, the size stays (Larghezza/Altezza in Forma to change the shape)
                im2.colorspace_settings.name = "sRGB"
                p["image"] = im2.name
                p["file"] = os.path.basename(f) if os.path.isfile(f) else (os.path.basename(im2.filepath) or im2.name)
                continue
            maps[channel] = im2.name
            if channel == "emission" and float(p["emit"]) <= 0:
                p["emit"] = 1.0                  # a glow map with the glow off would show nothing
        p["maps"] = maps
        if p["mode"] != "multiply":
            p["mode"] = "opacity" if "opacity" in maps else "alpha"
    if "order" in data:
        p["order"] = max(0, min(20, int(data["order"])))
    if "tint" in data and isinstance(data["tint"], list) and len(data["tint"]) == 3:
        p["tint"] = [max(0.0, min(1.0, float(v))) for v in data["tint"]]
    ob[DECAL_KEY] = json.dumps(p)
    apply(ob)
    refresh()
    from .core import object_json
    return {"object": object_json(ob)}


def _clip(poly, axis, lim, keep_below):
    """Sutherland-Hodgman: the part of a polygon on one side of the plane coordinate[axis] = lim."""
    out = []
    n = len(poly)
    for i in range(n):
        a, b = poly[i], poly[(i + 1) % n]
        ina = a[axis] <= lim if keep_below else a[axis] >= lim
        inb = b[axis] <= lim if keep_below else b[axis] >= lim
        if ina:
            out.append(a)
        if ina != inb:
            t = (lim - a[axis]) / (b[axis] - a[axis])
            out.append((a[0] + (b[0] - a[0]) * t, a[1] + (b[1] - a[1]) * t, a[2] + (b[2] - a[2]) * t))
    return out


def mesh(data):
    """GET /api/decal/mesh?id=: the geometry for the real-time view, in the decal's own space (metres): the faces of
    the modifier cut exactly to the box (so the view, its gizmo and its outline see only the decal, not the whole
    wall it lies on), as flat triangle lists: p xyz, uv (from the box), f (fade from the depth)."""
    ob = find(data.get("id"))
    if not is_decal(ob):
        raise ApiError(tr("Non è una decal"))
    p = params(ob)
    hw, hl, hd = max(1e-5, p["w"] * CM / 2), max(1e-5, p["l"] * CM / 2), max(1e-5, p["d"] * CM / 2)
    dg = bpy.context.evaluated_depsgraph_get()
    ev = ob.evaluated_get(dg)
    me = ev.to_mesh()
    try:
        me.calc_loop_triangles()
        verts = me.vertices
        P, U, F = [], [], []
        for tri in me.loop_triangles:
            poly = [tuple(verts[v].co) for v in tri.vertices]
            # cut to the box on all three axes: a big face crossing the box (the floor of a car under its dashboard)
            # is kept whole by the modifier; beyond the depth it is fully faded (invisible), but the view drew its
            # outline, its selection box and took clicks there - a ghost of the decal down on the floor
            for axis, lim in ((0, hw), (1, hl), (2, hd)):
                poly = _clip(poly, axis, lim, True)
                if poly:
                    poly = _clip(poly, axis, -lim, False)
                if len(poly) < 3:
                    break
            if len(poly) < 3:
                continue
            for k in range(1, len(poly) - 1):
                tri3 = (poly[0], poly[k], poly[k + 1])
                keep = 1.0
                if float(p.get("angle", 90.0)) < 90.0:
                    nv = (Vector(tri3[1]) - Vector(tri3[0])).cross(Vector(tri3[2]) - Vector(tri3[0]))
                    keep = angle_fade(p, abs(nv.normalized().z)) if nv.length > 1e-12 else 0.0
                for c in tri3:
                    P += (round(c[0], 5), round(c[1], 5), round(c[2], 5))
                    U += (round(c[0] / (2 * hw) + 0.5, 5), round(c[1] / (2 * hl) + 0.5, 5))
                    f = min(1.0, abs(c[2]) / hd)
                    if keep < 1.0:
                        # 1 - f'^4 = (1 - f^4) * keep: the same fade the render gives (angle_fade)
                        f = max(0.0, 1.0 - (1.0 - f ** 4) * keep) ** 0.25
                    F.append(round(f, 4))
        return {"p": P, "uv": U, "f": F, "decal": info(ob)}
    finally:
        ev.to_mesh_clear()


def upgrade():
    """Projects saved before 1.36.3: decals with the tree that kept whole the faces crossing the box."""
    for ob in [o for o in bpy.context.scene.objects if is_decal(o)]:
        mod = ob.modifiers.get("Simpler Decal")
        ng = mod.node_group if mod is not None else None
        if ng is None or ng.get("simpler_version") != GROUP_VERSION:
            try:
                apply(ob)
            except Exception as e:          # (one decal that fails does not stop the opening)
                print("SIMPLER_DECAL_UPGRADE", ob.name, e, flush=True)


def report():
    """At opening, in the engine log (SIMPLER_DECAL): every decal with what decides how the views see it."""
    from .core import log
    obs = [o for o in bpy.data.objects if is_decal(o)]
    log("SIMPLER_DECAL", f"{len(obs)} decals in the project")
    for ob in obs[:60]:
        try:
            m = mesh({"id": ob.get("simpler_id")}) if ob.get("simpler_id") else {"p": []}
            tris = len(m.get("p") or []) // 9
        except Exception as exc:
            tris = f"error {exc}"
        top = ob
        while top.parent is not None:
            top = top.parent
        log("SIMPLER_DECAL", f"{ob.name!r} id={ob.get('simpler_id')} in_scene={bool(ob.users_scene)} trashed={bool(ob.get('simpler_trashed'))}"
            f" hidden={ob.hide_render} parent={ob.parent.name if ob.parent else '-'} top={top.name!r}"
            f" paint_model={ob.get('simpler_paint_model') or '-'} parent_paint_model={(ob.parent.get('simpler_paint_model') if ob.parent else None) or '-'}"
            f" target={ob.get('simpler_decal_targets') or ob.get('simpler_decal_target') or '-'} tris={tris}")


def retarget(ob):
    """After the decal is moved, turned or scaled: the piece under its middle (along its own -Z) becomes the piece it
    is projected on, and its child (it keeps its place in the world). Nothing under it: it stays where it was."""
    if not is_decal(ob):
        return
    refresh()
    mw = ob.matrix_world.copy()
    n = (mw.to_3x3() @ Vector((0, 0, 1))).normalized()
    hit = _hit(mw.translation, n)
    if hit is not None and hit != ob.parent and not hit.get("simpler_paint_model"):
        ob.parent = hit
        ob.matrix_parent_inverse = hit.matrix_world.inverted()
        ob.matrix_world = mw
        ob["simpler_decal_target"] = hit.name
    apply(ob)


def retarget_ids(ids):
    for i in ids or []:
        ob = find(i, required=False)
        if ob is not None and is_decal(ob):
            retarget(ob)


def png_bytes(decal_id, channel=""):
    """A picture of a decal as it is (the colour, or one of its maps), for the real-time view."""
    ob = find(decal_id, required=False)
    if not is_decal(ob):
        return None
    p = params(ob)
    name = (p["maps"] or {}).get(channel) if channel else p["image"]
    im = bpy.data.images.get(name or "")
    if im is None:
        return None
    if im.packed_file:
        return bytes(im.packed_file.data)
    path = bpy.path.abspath(im.filepath)
    if os.path.isfile(path):
        with open(path, "rb") as f:
            return f.read()
    return None
