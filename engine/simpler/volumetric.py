"""Volumetrico: a type of material that fills a model with fog, smoke, cloud, steam, dust or fire.

The model is the container: its surface disappears (no surface shader) and its inside becomes a volume. A box of
uniform density would look like a box: so in the path tracing a Geometry Nodes modifier turns the closed shape
into a volume grid whose density goes from 0 at the surface to 1 at «Morbidezza» inside it (Mesh to Volume: the
fog of a signed distance, a linear ramp in its interior band), and the material eats its edge with a 3D noise
(«Sbuffi»): the edge becomes puffs, a sphere a cloud, three spheres a column of smoke, a low box a bank of fog.

Formulas (the same in viewer.js, volGLSL):
  d        the grid: clamp(-sdf / band, 0, 1), band = max(2 voxels, soft * 0.5 * smallest side of the model)
  n        fbm noise of the position (object space turned to world, so it follows the model) / (puffRel * the longest
           side of the model in metres) + seed,
           stretched: smoothstep(0.3, 0.7, n)
  f        clamp((d - puffs * (1 - n)) / (1 - 0.5 * puffs), 0, 1)
  sigma    4 / «Visibilità» (metres: through that much of it you no longer see)
  colour   albedo = colour * (1 - 0.85 * absorb): the light not scattered is absorbed (dark smoke)
  emission strength * f^2 in its colour (fire: brighter in the core)
Cycles: Principled Volume (Color = albedo, Absorption Color white, Density = sigma f, Anisotropy, Emission).

Settings live on the material (MKEY, JSON): all the objects with it are alike. The modifier exists only for the
path tracing (show_viewport off): the real-time view gets the mesh and draws the volume by itself (ray marching
inside its faces). Rain and snow leave volumetric models alone (no shelter, no mantle, no wetness).
"""
import json
import math

import bpy

MKEY = "simpler_volumetric"
GROUP = "Simpler Volume v4"
MOD = "Simpler Volume"
PREV_KEY = "simpler_volumetric_prev"      # where the surface of the material came from (back to Standard)
SIG_KEY = "simpler_volumetric_sig"

DEFAULTS = {"on": False, "preset": "nuvola", "visibility": 0.8, "color": [1.0, 1.0, 1.0], "absorb": 0.0, "soft": 0.6,
            "puffs": 0.6, "puffRel": 0.12, "detail": 0.5, "aniso": 0.4, "seed": 0, "emission": 0.0,
            "emitColor": [1.0, 0.42, 0.08], "bounces": 4}
PRESETS = {
    # (measured on a sphere of 6 m against a photo of a cumulus: dense - visibility about 1/25 of the size - with
    # sharp edges, no absorption: the grey of a cloud is its own shadow)
    "nuvola":  {"visibility": 0.25, "color": [1.0, 1.0, 1.0], "absorb": 0.0, "soft": 0.3, "puffs": 0.6, "puffRel": 0.12,
                "aniso": 0.6, "detail": 0.7, "emission": 0.0},
    "fumo":    {"visibility": 0.6, "color": [0.55, 0.55, 0.56], "absorb": 0.6, "soft": 0.8, "puffs": 0.7, "puffRel": 0.15,
                "aniso": 0.2, "emission": 0.0},
    "nebbia":  {"visibility": 12.0, "color": [0.95, 0.96, 0.98], "absorb": 0.0, "soft": 0.9, "puffs": 0.35, "puffRel": 0.4,
                "aniso": 0.6, "emission": 0.0},
    "vapore":  {"visibility": 1.2, "color": [1.0, 1.0, 1.0], "absorb": 0.0, "soft": 1.0, "puffs": 0.8, "puffRel": 0.12,
                "aniso": 0.6, "emission": 0.0},
    "polvere": {"visibility": 5.0, "color": [0.80, 0.70, 0.55], "absorb": 0.25, "soft": 0.8, "puffs": 0.5, "puffRel": 0.25,
                "aniso": 0.5, "emission": 0.0},
    "fuoco":   {"visibility": 0.8, "color": [0.35, 0.30, 0.28], "absorb": 0.5, "soft": 0.9, "puffs": 0.75, "puffRel": 0.2,
                "aniso": 0.0, "emission": 30.0, "emitColor": [1.0, 0.38, 0.06]},
}
MAX_VOXELS = 192
SIZE_KEY = "simpler_vol_size"        # on a volumetric object: its longest side in metres (the material reads it)
STEP_RATE = 3.0                      # ray marching steps of 3 voxels: the noise is smooth at that scale (measured:
                                     # 4 looks the same as 1, 2x faster)                     # along the longest side, at most


def mat_settings(mat):
    s = json.loads(json.dumps(DEFAULTS))
    if mat is None:
        return s
    try:
        s.update(json.loads(mat.get(MKEY) or "{}"))
    except (TypeError, ValueError):
        pass
    return s


def is_on(mat):
    return mat is not None and bool(mat.get(MKEY)) and mat_settings(mat)["on"]


def volume_material(ob):
    """The volumetric material of an object (the first), or None."""
    if ob is None or ob.type != "MESH":
        return None
    for sl in ob.material_slots:
        if is_on(sl.material):
            return sl.material
    return None


def is_volume_object(ob):
    return volume_material(ob) is not None


def _users(mat):
    return [o for o in bpy.context.scene.objects if o.type == "MESH" and any(sl.material is mat for sl in o.material_slots)]


def _clamp(s):
    c = lambda v, lo, hi: max(lo, min(hi, float(v)))
    s["on"] = bool(s["on"])
    if s.get("preset") not in PRESETS and s.get("preset") != "custom":
        s["preset"] = "custom"
    s["visibility"] = c(s["visibility"], 0.05, 1000.0)
    s["absorb"] = c(s["absorb"], 0, 1)
    s["soft"] = c(s["soft"], 0, 1)
    s["puffs"] = c(s["puffs"], 0, 1)
    s["puffRel"] = c(s["puffRel"], 0.01, 1.0)
    s.pop("puffSize", None)                        # (1.54.0: in metres - now a share of the model)
    s["detail"] = c(s["detail"], 0, 1)
    s["aniso"] = c(s["aniso"], -0.9, 0.9)
    s["seed"] = int(c(s["seed"], 0, 999))
    s["emission"] = c(s["emission"], 0, 1000.0)
    s["bounces"] = int(round(c(s.get("bounces", 4), 1, 32)))
    for k in ("color", "emitColor"):
        v = s.get(k) or DEFAULTS[k]
        s[k] = [c(x, 0, 1) for x in list(v)[:3]]
    return s


# ---------------------------------------------------------------- the material

def _outputs(mat):
    return [n for n in mat.node_tree.nodes if n.type == "OUTPUT_MATERIAL"]


def _remember_surface(mat):
    """Where the Surface of every output came from (node, socket): back there when the type goes back."""
    prev = {}
    for out in _outputs(mat):
        sock = out.inputs.get("Surface")
        if sock is not None and sock.is_linked:
            lk = sock.links[0]
            prev[out.name] = [lk.from_node.name, lk.from_socket.identifier]
    mat[PREV_KEY] = json.dumps(prev)


def _restore_surface(mat):
    nt = mat.node_tree
    for n in [n for n in nt.nodes if n.name.startswith("simpler_vm")]:
        nt.nodes.remove(n)
    try:
        prev = json.loads(mat.get(PREV_KEY) or "{}")
    except (TypeError, ValueError):
        prev = {}
    for out in _outputs(mat):
        vol = out.inputs.get("Volume")
        if vol is not None:
            for lk in list(vol.links):
                nt.links.remove(lk)
        src = prev.get(out.name)
        if src:
            node = nt.nodes.get(src[0])
            sock = next((o for o in node.outputs if o.identifier == src[1]), None) if node is not None else None
            if sock is not None:
                nt.links.new(sock, out.inputs["Surface"])
    if PREV_KEY in mat:
        del mat[PREV_KEY]
    if SIG_KEY in mat:
        del mat[SIG_KEY]


def _apply_nodes(mat, force=False):
    """The volume into the material (idempotent: nothing done when it is already there as the settings say)."""
    if mat is None:
        return False
    if not mat.use_nodes or mat.node_tree is None:
        mat.use_nodes = True
    s = mat_settings(mat)
    nt = mat.node_tree
    outs = _outputs(mat)
    if not outs:
        outs = [nt.nodes.new("ShaderNodeOutputMaterial")]
    sig = json.dumps({k: v for k, v in s.items() if k != "bounces"}, sort_keys=True) + "|1"   # (bounces: render settings)
    pv = nt.nodes.get("simpler_vm_pv")
    wired = pv is not None and all(o.inputs["Volume"].is_linked and o.inputs["Volume"].links[0].from_node is pv
                                   and not o.inputs["Surface"].is_linked for o in outs)
    if not force and wired and mat.get(SIG_KEY) == sig:
        return False
    if PREV_KEY not in mat or any(o.inputs["Surface"].is_linked for o in outs):
        _remember_surface(mat)          # (again after the editor rebuilt the material: its surface is linked again)
    for n in [n for n in nt.nodes if n.name.startswith("simpler_vm")]:
        nt.nodes.remove(n)
    N, L = nt.nodes, nt.links
    x0, y0 = outs[0].location.x - 1500, outs[0].location.y - 500

    def node(t, name, dx, dy=0):
        n = N.new(t)
        n.name = "simpler_vm_" + name
        n.label = "Volume: " + name
        n.location = (x0 + dx, y0 + dy)
        return n

    def math_(op, a, b=None, name="", dx=0, dy=0, clamp=False):
        n = node("ShaderNodeMath", name or op.lower() + str(len(N)), dx, dy)
        n.operation = op
        n.use_clamp = clamp
        for i, v in enumerate((a, b)):
            if v is None:
                continue
            if isinstance(v, (int, float)):
                n.inputs[i].default_value = v
            else:
                L.new(v, n.inputs[i])
        return n.outputs[0]

    at = node("ShaderNodeAttribute", "density", 0, 200)
    at.attribute_type = "GEOMETRY"
    at.attribute_name = "density"
    d = at.outputs["Fac"]
    f = d
    if s["puffs"] > 1e-3:
        tc = node("ShaderNodeTexCoord", "coords", 0, -100)
        vt = node("ShaderNodeVectorTransform", "world", 200, -100)
        vt.vector_type = "VECTOR"
        vt.convert_from = "OBJECT"
        vt.convert_to = "WORLD"
        L.new(tc.outputs["Object"], vt.inputs[0])
        # (the size of the puffs: a share of the model - its longest side in metres is on the object, SIZE_KEY)
        osz = node("ShaderNodeAttribute", "size", 0, -300)
        osz.attribute_type = "OBJECT"
        osz.attribute_name = SIZE_KEY
        k_ = math_("DIVIDE", 1.0 / s["puffRel"], math_("MAXIMUM", osz.outputs["Fac"], 1e-3, "sizemin", 200, -300), "pscale", 300, -300)
        sc = node("ShaderNodeVectorMath", "scale", 400, -100)
        sc.operation = "SCALE"
        L.new(k_, sc.inputs["Scale"])
        L.new(vt.outputs[0], sc.inputs[0])
        off = node("ShaderNodeVectorMath", "seed", 600, -100)
        off.operation = "ADD"
        k = float(s["seed"])
        off.inputs[1].default_value = (k * 17.31 + 0.5, k * 9.13 + 0.25, k * 3.77 + 0.75)
        L.new(sc.outputs[0], off.inputs[0])
        nz = node("ShaderNodeTexNoise", "noise", 800, -100)
        nz.noise_dimensions = "3D"
        nz.inputs["Scale"].default_value = 1.0
        nz.inputs["Detail"].default_value = 1.0 + 5.0 * s["detail"]
        nz.inputs["Roughness"].default_value = 0.55
        L.new(off.outputs[0], nz.inputs["Vector"])
        # (the fbm of the noise stays near 0.5: stretched to 0..1, or the puffs would only shrink the shape)
        mr = node("ShaderNodeMapRange", "contrast", 950, -100)
        mr.interpolation_type = "SMOOTHSTEP"
        mr.clamp = True
        mr.inputs["From Min"].default_value = 0.3
        mr.inputs["From Max"].default_value = 0.7
        L.new(nz.outputs["Fac"], mr.inputs["Value"])
        er = math_("MULTIPLY", math_("SUBTRACT", 1.0, mr.outputs["Result"], "inv", 1000, -100), s["puffs"], "erode", 1150, -100)
        f = math_("DIVIDE", math_("SUBTRACT", d, er, "eaten", 1300, 100), 1.0 - 0.5 * s["puffs"], "shape", 1450, 100, clamp=True)
    sigma = 4.0 / s["visibility"]
    dens = math_("MULTIPLY", f, sigma, "dens", 1600, 100)
    pv = node("ShaderNodeVolumePrincipled", "pv", 1800, 0)
    pv.name = "simpler_vm_pv"
    alb = [c * (1.0 - 0.85 * s["absorb"]) for c in s["color"]]
    pv.inputs["Color"].default_value = (*alb, 1.0)
    pv.inputs["Absorption Color"].default_value = (1.0, 1.0, 1.0, 1.0)
    pv.inputs["Anisotropy"].default_value = s["aniso"]
    L.new(dens, pv.inputs["Density"])
    if "Density Attribute" in pv.inputs:
        pv.inputs["Density Attribute"].default_value = ""
    if s["emission"] > 0:
        f2 = math_("MULTIPLY", f, f, "core", 1600, -150)
        L.new(math_("MULTIPLY", f2, s["emission"], "glow", 1700, -150), pv.inputs["Emission Strength"])
        pv.inputs["Emission Color"].default_value = (*s["emitColor"], 1.0)
    else:
        pv.inputs["Emission Strength"].default_value = 0.0
    for o in outs:
        for lk in list(o.inputs["Surface"].links):
            L.remove(lk)
        L.new(pv.outputs[0], o.inputs["Volume"])
    cy = getattr(mat, "cycles", None)
    if cy is not None:
        if hasattr(cy, "homogeneous_volume"):
            cy.homogeneous_volume = False
        if hasattr(cy, "volume_interpolation"):
            cy.volume_interpolation = "LINEAR"
        if hasattr(cy, "volume_step_rate"):
            cy.volume_step_rate = STEP_RATE
    mat[SIG_KEY] = sig
    return True


# ---------------------------------------------------------------- the modifier (shape -> volume grid)

def _group():
    g = bpy.data.node_groups.get(GROUP)
    if g is not None:
        return g
    g = bpy.data.node_groups.new(GROUP, "GeometryNodeTree")
    I = g.interface
    I.new_socket("Geometry", in_out="INPUT", socket_type="NodeSocketGeometry")
    I.new_socket("Material", in_out="INPUT", socket_type="NodeSocketMaterial")
    I.new_socket("Slot", in_out="INPUT", socket_type="NodeSocketInt")
    vs = I.new_socket("Voxel", in_out="INPUT", socket_type="NodeSocketFloat")
    vs.default_value = 0.05
    bw = I.new_socket("Band", in_out="INPUT", socket_type="NodeSocketFloat")
    bw.default_value = 0.2
    I.new_socket("Open", in_out="INPUT", socket_type="NodeSocketBool")
    rs = I.new_socket("Radius", in_out="INPUT", socket_type="NodeSocketFloat")
    rs.default_value = 0.5
    I.new_socket("Geometry", in_out="OUTPUT", socket_type="NodeSocketGeometry")
    N, L = g.nodes, g.links
    gi, go = N.new("NodeGroupInput"), N.new("NodeGroupOutput")
    # the faces of the volumetric slot (by index: a material linked to the object is not in the geometry)
    mi = N.new("GeometryNodeInputMaterialIndex")
    cmp = N.new("FunctionNodeCompare")
    cmp.data_type = "INT"
    cmp.operation = "EQUAL"
    L.new(mi.outputs[0], cmp.inputs["A"])
    L.new(gi.outputs["Slot"], cmp.inputs["B"])
    sep = N.new("GeometryNodeSeparateGeometry")
    sep.domain = "FACE"
    L.new(gi.outputs["Geometry"], sep.inputs["Geometry"])
    L.new(cmp.outputs["Result"], sep.inputs["Selection"])
    # a model that is not closed (open pieces, a cloud made of small discs): its pieces are wrapped in spheres of
    # «Radius» and the union becomes the closed shape to fill (points -> volume -> mesh)
    mp = N.new("GeometryNodeMeshToPoints")
    mp.mode = "VERTICES"
    L.new(sep.outputs["Selection"], mp.inputs["Mesh"])
    pv = N.new("GeometryNodePointsToVolume")
    pv.inputs["Resolution Mode"].default_value = "Size"
    pv.inputs["Density"].default_value = 1.0
    L.new(mp.outputs["Points"], pv.inputs["Points"])
    L.new(gi.outputs["Voxel"], pv.inputs["Voxel Size"])
    L.new(gi.outputs["Radius"], pv.inputs["Radius"])
    vm = N.new("GeometryNodeVolumeToMesh")
    vm.inputs["Resolution Mode"].default_value = "Grid"
    vm.inputs["Threshold"].default_value = 0.5
    L.new(pv.outputs["Volume"], vm.inputs["Volume"])
    # the wrap of many small pieces encloses pockets: shells facing inwards (negative volume, by the divergence
    # theorem: the sum of area * (centre . normal) / 3 over the faces of the shell). Filled as holes they left
    # pockets of empty air inside the cloud (the downloaded cloud of 1.55.0: 20 m³ of it): they go.
    isl = N.new("GeometryNodeInputMeshIsland")
    pos = N.new("GeometryNodeInputPosition")
    nrm = N.new("GeometryNodeInputNormal")
    area = N.new("GeometryNodeInputMeshFaceArea")
    dot = N.new("ShaderNodeVectorMath")
    dot.operation = "DOT_PRODUCT"
    L.new(pos.outputs[0], dot.inputs[0])
    L.new(nrm.outputs[0], dot.inputs[1])
    mul = N.new("ShaderNodeMath")
    mul.operation = "MULTIPLY"
    L.new(dot.outputs["Value"], mul.inputs[0])
    L.new(area.outputs[0], mul.inputs[1])
    acc = N.new("GeometryNodeAccumulateField")
    acc.data_type = "FLOAT"
    acc.domain = "FACE"
    L.new(mul.outputs[0], acc.inputs[0])
    L.new(isl.outputs["Island Index"], acc.inputs["Group ID"] if "Group ID" in acc.inputs else acc.inputs["Group Index"])
    neg = N.new("FunctionNodeCompare")
    neg.data_type = "FLOAT"
    neg.operation = "LESS_THAN"
    L.new(acc.outputs["Total"], neg.inputs["A"])
    neg.inputs["B"].default_value = 0.0
    dg = N.new("GeometryNodeDeleteGeometry")
    dg.domain = "FACE"
    L.new(vm.outputs["Mesh"], dg.inputs["Geometry"])
    L.new(neg.outputs["Result"], dg.inputs["Selection"])
    sw = N.new("GeometryNodeSwitch")
    sw.input_type = "GEOMETRY"
    L.new(gi.outputs["Open"], sw.inputs["Switch"])
    L.new(sep.outputs["Selection"], sw.inputs["False"])
    L.new(dg.outputs["Geometry"], sw.inputs["True"])
    mv = N.new("GeometryNodeMeshToVolume")
    mv.inputs["Resolution Mode"].default_value = "Size"
    mv.inputs["Density"].default_value = 1.0
    L.new(sw.outputs["Output"], mv.inputs["Mesh"])
    L.new(gi.outputs["Voxel"], mv.inputs["Voxel Size"])
    L.new(gi.outputs["Band"], mv.inputs["Interior Band Width"])
    sm = N.new("GeometryNodeSetMaterial")
    L.new(mv.outputs["Volume"], sm.inputs["Geometry"])
    L.new(gi.outputs["Material"], sm.inputs["Material"])
    j = N.new("GeometryNodeJoinGeometry")
    L.new(sm.outputs["Geometry"], j.inputs["Geometry"])
    L.new(sep.outputs["Inverted"], j.inputs["Geometry"])
    L.new(j.outputs["Geometry"], go.inputs["Geometry"])
    return g


def local_box(ob):
    import numpy as np
    me = ob.data
    n = len(me.vertices)
    if not n:
        return None
    co = np.empty(n * 3, dtype=np.float32)
    me.vertices.foreach_get("co", co)
    co = co.reshape(-1, 3)
    return co.min(0), co.max(0)


_SHAPE = {}


def shape_info(ob):
    """Is the model closed? Its pieces (islands) and the radius that wraps open ones into a closed shape - the same
    in viewer.js volShape. Vertices welded by position (1e-4 of the longest side: an imported mesh is often split at
    its seams); open = more than 1% of its edges have one face only. Radius = 0.8 (box volume / islands)^(1/3),
    between 2 voxels and 0.35 of the smallest side. Kept per mesh until it changes."""
    import numpy as np
    me = ob.data
    key = (me.name, len(me.vertices), len(me.polygons), me.vertices[0].co.to_tuple(4) if len(me.vertices) else None)
    if key in _SHAPE:
        return _SHAPE[key]
    n = len(me.vertices)
    out = {"open": False, "islands": 1, "radius": 0.0}
    if n and len(me.polygons):
        co = np.empty(n * 3, dtype=np.float64)
        me.vertices.foreach_get("co", co)
        co = co.reshape(-1, 3)
        lo, hi = co.min(0), co.max(0)
        longest = max(float((hi - lo).max()), 1e-6)
        q = np.round((co - lo) / (longest * 1e-4)).astype(np.int64)
        _u, weld = np.unique(q, axis=0, return_inverse=True)
        weld = weld.ravel()
        lv = np.empty(len(me.loops), dtype=np.int64)
        me.loops.foreach_get("vertex_index", lv)
        ls = np.empty(len(me.polygons), dtype=np.int64)
        me.polygons.foreach_get("loop_start", ls)
        lt = np.empty(len(me.polygons), dtype=np.int64)
        me.polygons.foreach_get("loop_total", lt)
        a = weld[lv]
        nxt = np.arange(len(lv)) + 1
        ends = ls + lt - 1
        nxt[ends] = ls                                   # (the last corner of a face goes back to the first)
        b = a[nxt]
        e = np.sort(np.stack([a, b], 1), 1)
        e = e[e[:, 0] != e[:, 1]]
        _ue, cnt = np.unique(e, axis=0, return_counts=True)
        out["open"] = bool((cnt == 1).sum() > 0.01 * max(1, len(cnt)))
        if out["open"]:
            lab = np.arange(len(_u))
            for _i in range(200):                        # (connected pieces: labels spread along the edges)
                old = lab.copy()
                m = np.minimum(lab[_ue[:, 0]], lab[_ue[:, 1]])
                np.minimum.at(lab, _ue[:, 0], m)
                np.minimum.at(lab, _ue[:, 1], m)
                lab = lab[lab]
                if (lab == old).all():
                    break
            out["islands"] = int(len(np.unique(lab)))
            dims = [max(float(x), 1e-6) for x in (hi - lo)]
            smallest = min([x for x in dims if x > 1e-5] or [longest])
            vol = float(np.prod([max(x, 0.05 * smallest) for x in dims]))
            out["radius"] = 0.8 * (vol / out["islands"]) ** (1.0 / 3.0)
            out["smallest"] = smallest
    if len(_SHAPE) > 200:
        _SHAPE.clear()
    _SHAPE[key] = out
    return out


def sizes(ob, s):
    """(voxel, band) in the object's own units: the voxel from the longest side (48..160 per side with
    «Dettaglio», MAX_VOXELS at most), the band from «Morbidezza» on the smallest side (2 voxels at least)."""
    box = local_box(ob)
    if box is None:
        return 0.1, 0.2
    dims = [float(b - a) for a, b in zip(*box)]
    longest = max(max(dims), 1e-4)
    per = min(MAX_VOXELS, 48 + 112 * s["detail"])
    voxel = longest / per
    smallest = min([x for x in dims if x > 1e-5] or [longest])
    band = max(2.0 * voxel, s["soft"] * 0.5 * smallest)
    return voxel, band


def _sync(ob):
    """The modifier on (or off) the object, after its material."""
    from . import water
    mat = volume_material(ob)
    mod = ob.modifiers.get(MOD)
    if mat is None:
        if mod is not None:
            ob.modifiers.remove(mod)
            return True
        return False
    s = mat_settings(mat)
    voxel, band = sizes(ob, s)
    changed = False
    if mod is None:
        mod = ob.modifiers.new(MOD, "NODES")
        changed = True
    if mod.node_group is None or mod.node_group.name != GROUP:
        mod.node_group = _group()
        changed = True
    mod.show_viewport = False                # only the path tracing: the real-time view draws its own volume
    mod.show_render = True
    ids = water._socket_ids(mod)
    slot = next(i for i, sl in enumerate(ob.material_slots) if sl.material is mat)
    sh = shape_info(ob)
    radius = max(2.0 * voxel, min(sh["radius"], 0.35 * sh.get("smallest", 1e9))) if sh["open"] else voxel
    # (the size of the model in metres, for «Grandezza sbuffi» as a share of it: read by the material)
    box = local_box(ob)
    if box is not None:
        sc = max(abs(x) for x in ob.matrix_world.to_scale())
        size = float(max(b - a for a, b in zip(*box))) * sc
        if abs(float(ob.get(SIZE_KEY, 0.0)) - size) > 1e-4:
            ob[SIZE_KEY] = size
            changed = True
    for name, v in (("Material", mat), ("Slot", slot), ("Voxel", voxel), ("Band", band), ("Open", sh["open"]), ("Radius", radius)):
        props = getattr(mod, "properties", None)
        cur = getattr(getattr(props.inputs, ids[name]), "value", None) if props is not None and hasattr(props.inputs, ids[name]) else mod.get(ids[name])
        if cur != v and not (isinstance(v, float) and cur is not None and abs(cur - v) < 1e-7):
            water._set_input(mod, ids[name], v)
            changed = True
    return changed


def sync_objects(obs):
    changed = False
    for ob in obs:
        try:
            if ob.type == "MESH":
                changed = _sync(ob) or changed
        except ReferenceError:
            pass
    return changed


def ensure():
    """Before every path-traced image: materials and modifiers as the settings say (the material editor may rebuild a
    material from scratch). Cheap when nothing changed."""
    changed = False
    mats = {m for m in bpy.data.materials if m.get(MKEY)}
    for m in mats:
        if is_on(m):
            changed = _apply_nodes(m) or changed
    for ob in bpy.context.scene.objects:
        if ob.type == "MESH" and (ob.modifiers.get(MOD) is not None or any(sl.material in mats for sl in ob.material_slots)):
            changed = _sync(ob) or changed
    return changed


# ---------------------------------------------------------------- editor

def set_material(data):
    """POST /api/material/volumetric {name, on?, preset?, visibility?, color?, absorb?, soft?, puffs?, puffRel?,
    detail?, aniso?, seed?, emission?, emitColor?}. A preset sets its values (then they can be changed)."""
    from .core import ApiError
    from .i18n import tr
    mat = bpy.data.materials.get(data.get("name") or "")
    if mat is None:
        raise ApiError(tr("Materiale non trovato"))
    from . import terrain
    mat = terrain.source_of(mat)       # (1.76.4) a zone of a terrain: its own material, not the blended copy
    from . import matedit
    matedit.mark_draft(mat)
    s = mat_settings(mat)
    was_on = is_on(mat)
    if "on" in data:
        s["on"] = bool(data["on"])
    if data.get("preset") in PRESETS:
        s.update(json.loads(json.dumps(PRESETS[data["preset"]])))
        s["preset"] = data["preset"]
        if "emitColor" not in PRESETS[data["preset"]]:
            s["emitColor"] = list(DEFAULTS["emitColor"])
    changed_values = False
    if "bounces" in data:                     # (how the render treats the light: not a change of the look's kind)
        s["bounces"] = data["bounces"]
    for k in ("visibility", "color", "absorb", "soft", "puffs", "puffRel", "detail", "aniso", "seed", "emission", "emitColor"):
        if k in data:
            s[k] = data[k]
            changed_values = True
    if changed_values and "preset" not in data:
        s["preset"] = "custom"
    s = _clamp(s)
    mat[MKEY] = json.dumps(s)
    if s["on"]:
        _apply_nodes(mat, force=True)
    elif was_on:
        _restore_surface(mat)
    sync_objects(_users(mat))
    _touch()
    return {"name": mat.name, "volumetric": editor_info(mat)}


FINAL_BOUNCES = 12                   # the final render: at least this (inside a cloud the light needs them; ~+30% time)


def bounces_wanted(scene):
    """The light bounces the volumetric models of the scene ask for (their «Rimbalzi della luce», the highest), 0
    when there are none."""
    want = 0
    for ob in scene.objects:
        mod = ob.modifiers.get(MOD) if ob.type == "MESH" else None
        if mod is None or not mod.show_render:
            continue
        mat = volume_material(ob)
        if mat is not None:
            want = max(want, int(mat_settings(mat).get("bounces", 4)))
    return want


def preset_to(mat, preset):
    """A material of the library (materials.VOLUME_PRESETS) made volumetric with a preset."""
    s = mat_settings(mat)
    s.update(json.loads(json.dumps(PRESETS[preset])))
    s.update(on=True, preset=preset)
    mat[MKEY] = json.dumps(_clamp(s))
    _apply_nodes(mat, force=True)


def _touch():
    from . import rain, render
    rain.touch()                                  # (the shelter and the mantle: volumes are not in them)
    try:
        render.invalidate()
    except Exception:
        pass


def editor_info(mat):
    s = mat_settings(mat)
    s["presets"] = list(PRESETS)
    users = _users(mat) if s["on"] else []
    s["users"] = len(users)
    s["voxels"] = 0
    for ob in users[:50]:
        box = local_box(ob)
        if box is None:
            continue
        voxel, _band = sizes(ob, s)
        dims = [float(b - a) for a, b in zip(*box)]
        s["voxels"] += int(math.prod(max(1.0, x / voxel) for x in dims))
    s["heavy"] = s["voxels"] > 6_000_000
    # models that are not closed (open pieces, a cloud made of small discs): filled by wrapping their pieces
    s["open"] = [ob.name for ob in users[:50] if ob.type == "MESH" and shape_info(ob)["open"]]
    return s


def realtime(mat):
    """For the real-time view (materials.realtime_params): what its shader needs."""
    s = mat_settings(mat)
    return {k: s[k] for k in ("visibility", "color", "absorb", "soft", "puffs", "puffRel", "detail", "aniso", "seed",
                              "emission", "emitColor")}


def library_settings(mat):
    """For the material library: the settings (None when the material is not volumetric)."""
    return mat.get(MKEY) if is_on(mat) else None


def from_library(mat, raw):
    if raw:
        mat[MKEY] = raw
        _apply_nodes(mat, force=True)


def snapshot(mat):
    return mat.get(MKEY)


def restore(mat, raw):
    """Undo of a material (matedit.restore): the volumetric settings as they were."""
    was = is_on(mat)
    if raw:
        mat[MKEY] = raw
    elif MKEY in mat:
        del mat[MKEY]
    if is_on(mat):
        _apply_nodes(mat, force=True)
    elif was or PREV_KEY in mat:
        _restore_surface(mat)
    sync_objects(_users(mat))
