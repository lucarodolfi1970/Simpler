"""Water: real waves for real caustics, and the body of the water (its colour and clarity).

WAVES. A caustic is light focused by a curved surface: the bright net on the bottom of a pool exists because the
surface of the water is made of waves that act as small lenses. A flat surface (a plane, as water usually is in a
scene) lets the light through evenly: no pattern, whatever the renderer. A bump or normal map is not enough either
for the shadow caustics of Cycles (MNEE): it follows the real geometry and its smooth normals. So "Onde" adds a
Geometry Nodes modifier to the water object: the surface is subdivided (density from the size of the waves) and
moved up and down by a noise in metres, the same whatever the scale of the object; then it is shaded smooth.

BODY OF THE WATER. Real water is not a glass surface: it swallows the red first (blue-green with depth) and gets
hazy with distance, more if murky. In Cycles that is a volume (Volume Absorption, + Volume Scatter when murky) in
the material of the water, between its surface and the bottom. Seen from above an open plane is enough (the ray
enters the surface and meets the bottom); seen from under the water Cycles must know that the camera is inside
the volume, and for that the volume must be closed: the same modifier closes the surface downwards (a slab as deep
as the deepest point under it, hidden in the ground).

The modifier exists only for the path tracing (show_viewport off): the real-time view and its export keep the
light plane. Volume settings live on the material (all the water of that material is alike), waves on the object.
ensure() puts the volume nodes back into the materials before every path-traced image (the material editor may
rebuild a material from scratch).

Performance: subdivision capped (MAX_QUADS) and computed only when the settings change; the waves cost a little
BVH time, MNEE ~2-2.5x, the clear volume ~+10-20%, a murky one (scattering) more: all switches for the user.
"""
import json
import math

import bpy
from mathutils import Vector

GROUP = "Simpler Onde v4"           # (v4, 1.75.0: the grid around the camera for large surfaces)
MOD = "Simpler Onde"
KEY = "simpler_waves"           # JSON settings on the object
VKEY = "simpler_water_volume"   # JSON settings on the material
MAX_QUADS = 400_000
DEFAULTS = {"on": False, "height": 0.08, "size": 0.6}
# colour of a 1 m layer of water (transmittance per metre: the red goes first)
COLORS = {
    "piscina": (0.70, 0.93, 0.97),
    "lago": (0.74, 0.90, 0.76),
    "mare": (0.58, 0.87, 0.95),
    "palude": (0.70, 0.74, 0.50),
}
VDEFAULTS = {"on": False, "color": "piscina", "clarity": 25.0, "murk": 0.0}   # (murk: scattering - more noise, off by default)


# ---------------------------------------------------------------- the modifier (waves + closed body)

def _group():
    g = bpy.data.node_groups.get(GROUP)
    if g is not None:
        return g
    g = bpy.data.node_groups.new(GROUP, "GeometryNodeTree")
    g.interface.new_socket("Geometry", in_out="INPUT", socket_type="NodeSocketGeometry")
    lv = g.interface.new_socket("Level", in_out="INPUT", socket_type="NodeSocketInt")
    lv.default_value = 6; lv.min_value = 0; lv.max_value = 11
    h = g.interface.new_socket("Height", in_out="INPUT", socket_type="NodeSocketFloat")
    h.default_value = DEFAULTS["height"]
    s = g.interface.new_socket("Size", in_out="INPUT", socket_type="NodeSocketFloat")
    s.default_value = DEFAULTS["size"]
    d = g.interface.new_socket("Depth", in_out="INPUT", socket_type="NodeSocketFloat")
    d.default_value = 0.0
    lo = g.interface.new_socket("Lower", in_out="INPUT", socket_type="NodeSocketFloat")
    lo.default_value = 0.0
    ins = g.interface.new_socket("Inset", in_out="INPUT", socket_type="NodeSocketFloat")
    ins.default_value = 0.0
    up = g.interface.new_socket("UpOnly", in_out="INPUT", socket_type="NodeSocketFloat")
    up.default_value = -2.0
    g.interface.new_socket("Grid", in_out="INPUT", socket_type="NodeSocketObject")
    ug = g.interface.new_socket("UseGrid", in_out="INPUT", socket_type="NodeSocketBool")
    ug.default_value = False
    g.interface.new_socket("Geometry", in_out="OUTPUT", socket_type="NodeSocketGeometry")
    N, L = g.nodes, g.links
    gi = N.new("NodeGroupInput"); go = N.new("NodeGroupOutput")
    sub0 = N.new("GeometryNodeSubdivideMesh")
    L.new(gi.outputs["Geometry"], sub0.inputs["Mesh"]); L.new(gi.outputs["Level"], sub0.inputs["Level"])
    # (1.75.0) a large surface: instead of the same subdivision everywhere, the grid around the camera (an internal
    # object made by _view_grid, in the local space of this one): fine near the camera, wider far away
    ginfo = N.new("GeometryNodeObjectInfo"); ginfo.transform_space = "ORIGINAL"
    L.new(gi.outputs["Grid"], ginfo.inputs["Object"])
    gsw = N.new("GeometryNodeSwitch"); gsw.input_type = "GEOMETRY"
    L.new(gi.outputs["UseGrid"], gsw.inputs["Switch"])
    L.new(sub0.outputs["Mesh"], gsw.inputs["False"]); L.new(ginfo.outputs["Geometry"], gsw.inputs["True"])
    # position in metres: object space × scale of the object (the noise does not stretch with a scaled plane)
    selfo = N.new("GeometryNodeSelfObject")
    info = N.new("GeometryNodeObjectInfo"); info.transform_space = "ORIGINAL"
    L.new(selfo.outputs[0], info.inputs["Object"])
    pos = N.new("GeometryNodeInputPosition")
    wpos = N.new("ShaderNodeVectorMath"); wpos.operation = "MULTIPLY"
    L.new(pos.outputs[0], wpos.inputs[0]); L.new(info.outputs["Scale"], wpos.inputs[1])
    inv = N.new("ShaderNodeMath"); inv.operation = "DIVIDE"; inv.inputs[0].default_value = 1.0
    L.new(gi.outputs["Size"], inv.inputs[1])
    nz = N.new("ShaderNodeTexNoise"); nz.noise_dimensions = "3D"
    nz.inputs["Detail"].default_value = 3.0
    nz.inputs["Roughness"].default_value = 0.45
    L.new(wpos.outputs[0], nz.inputs["Vector"]); L.new(inv.outputs[0], nz.inputs["Scale"])
    c = N.new("ShaderNodeMath"); c.operation = "SUBTRACT"; c.inputs[1].default_value = 0.5
    L.new(nz.outputs["Fac"], c.inputs[0])
    amp0 = N.new("ShaderNodeMath"); amp0.operation = "MULTIPLY"
    L.new(c.outputs[0], amp0.inputs[0]); L.new(gi.outputs["Height"], amp0.inputs[1])
    # waves fade where the cells of the grid are too wide for them (simpler_cell, metres; 0 without the grid): no
    # noise of waves drawn with too few points far from the camera
    cell = N.new("GeometryNodeInputNamedAttribute"); cell.data_type = "FLOAT"; cell.inputs["Name"].default_value = "simpler_cell"
    rel = N.new("ShaderNodeMath"); rel.operation = "DIVIDE"
    L.new(cell.outputs["Attribute"], rel.inputs[0]); L.new(gi.outputs["Size"], rel.inputs[1])
    fade = N.new("ShaderNodeMapRange"); fade.interpolation_type = "SMOOTHSTEP"; fade.clamp = True
    fade.inputs["From Min"].default_value = 0.2; fade.inputs["From Max"].default_value = 0.4
    fade.inputs["To Min"].default_value = 1.0; fade.inputs["To Max"].default_value = 0.0
    L.new(rel.outputs[0], fade.inputs["Value"])
    amp = N.new("ShaderNodeMath"); amp.operation = "MULTIPLY"
    L.new(amp0.outputs[0], amp.inputs[0]); L.new(fade.outputs["Result"], amp.inputs[1])
    # metres → object space along the local Z
    sep = N.new("ShaderNodeSeparateXYZ"); L.new(info.outputs["Scale"], sep.inputs[0])
    sz = N.new("ShaderNodeMath"); sz.operation = "MAXIMUM"; sz.inputs[1].default_value = 1e-6
    L.new(sep.outputs["Z"], sz.inputs[0])
    amp2 = N.new("ShaderNodeMath"); amp2.operation = "SUBTRACT"
    L.new(amp.outputs[0], amp2.inputs[0]); L.new(gi.outputs["Lower"], amp2.inputs[1])
    dz = N.new("ShaderNodeMath"); dz.operation = "DIVIDE"
    L.new(amp2.outputs[0], dz.inputs[0]); L.new(sz.outputs[0], dz.inputs[1])
    off = N.new("ShaderNodeCombineXYZ"); L.new(dz.outputs[0], off.inputs["Z"])
    sp = N.new("GeometryNodeSetPosition")
    L.new(gsw.outputs[0], sp.inputs["Geometry"]); L.new(off.outputs[0], sp.inputs["Offset"])
    # a closed piece of water (a sphere, a glass, an aquarium): waves only where the surface faces up (UpOnly = the
    # lowest Z of the normal that still gets waves; -2 = everywhere, for an open surface)
    nrm = N.new("GeometryNodeInputNormal")
    nsep = N.new("ShaderNodeSeparateXYZ"); L.new(nrm.outputs[0], nsep.inputs[0])
    cmp_ = N.new("ShaderNodeMath"); cmp_.operation = "GREATER_THAN"
    L.new(nsep.outputs["Z"], cmp_.inputs[0]); L.new(gi.outputs["UpOnly"], cmp_.inputs[1])
    L.new(cmp_.outputs[0], sp.inputs["Selection"])
    # closed body for the volume: the surface extruded downwards by Depth (0: just the surface). The extruded faces
    # become the bottom (flipped to face outwards), the original surface is joined back on top and welded.
    ddz = N.new("ShaderNodeMath"); ddz.operation = "DIVIDE"
    L.new(gi.outputs["Depth"], ddz.inputs[0]); L.new(sz.outputs[0], ddz.inputs[1])
    neg = N.new("ShaderNodeMath"); neg.operation = "MULTIPLY"; neg.inputs[1].default_value = -1.0
    L.new(ddz.outputs[0], neg.inputs[0])
    ext = N.new("GeometryNodeExtrudeMesh"); ext.mode = "FACES"
    L.new(sp.outputs["Geometry"], ext.inputs["Mesh"])
    ext.inputs["Offset Scale"].default_value = 0.0
    L.new(neg.outputs[0], ext.inputs["Offset Scale"])
    ext.inputs["Individual"].default_value = False
    flip = N.new("GeometryNodeFlipFaces")
    L.new(ext.outputs["Mesh"], flip.inputs["Mesh"])          # bottom and sides (extruded downwards) face outwards
    join = N.new("GeometryNodeJoinGeometry")
    L.new(sp.outputs["Geometry"], join.inputs[0]); L.new(flip.outputs[0], join.inputs[0])
    weld = N.new("GeometryNodeMergeByDistance"); weld.inputs["Distance"].default_value = 1e-5
    L.new(join.outputs[0], weld.inputs["Geometry"])
    has = N.new("ShaderNodeMath"); has.operation = "GREATER_THAN"; has.inputs[1].default_value = 1e-4
    L.new(gi.outputs["Depth"], has.inputs[0])
    sw = N.new("GeometryNodeSwitch"); sw.input_type = "GEOMETRY"
    L.new(has.outputs[0], sw.inputs["Switch"])
    L.new(sp.outputs["Geometry"], sw.inputs["False"]); L.new(weld.outputs[0], sw.inputs["True"])
    # Inset: the surface moved inwards along its normals (the body of a closed piece of water sits just inside it)
    nrm2 = N.new("GeometryNodeInputNormal")
    ninv = N.new("ShaderNodeMath"); ninv.operation = "DIVIDE"
    L.new(gi.outputs["Inset"], ninv.inputs[0]); L.new(sz.outputs[0], ninv.inputs[1])
    nneg = N.new("ShaderNodeMath"); nneg.operation = "MULTIPLY"; nneg.inputs[1].default_value = -1.0
    L.new(ninv.outputs[0], nneg.inputs[0])
    nsc = N.new("ShaderNodeVectorMath"); nsc.operation = "SCALE"
    L.new(nrm2.outputs[0], nsc.inputs[0]); L.new(nneg.outputs[0], nsc.inputs["Scale"])
    isp = N.new("GeometryNodeSetPosition")
    L.new(sw.outputs[0], isp.inputs["Geometry"]); L.new(nsc.outputs[0], isp.inputs["Offset"])
    sm = N.new("GeometryNodeSetShadeSmooth")
    L.new(isp.outputs[0], sm.inputs[0])
    L.new(sm.outputs[0], go.inputs[0])
    return g


def settings(ob):
    s = dict(DEFAULTS)
    try:
        s.update(json.loads(ob.get(KEY, "{}")))
    except (TypeError, ValueError):
        pass
    return s


def _level(ob, size):
    """Subdivision level: about 8 quads per wave, at most MAX_QUADS in all."""
    me = ob.data
    if not me.vertices:
        return 0
    sc = ob.matrix_world.to_scale()
    xs = [v.co.x for v in me.vertices]; ys = [v.co.y for v in me.vertices]
    span = max((max(xs) - min(xs)) * abs(sc.x), (max(ys) - min(ys)) * abs(sc.y), 1e-3)
    faces = max(1, len(ob.data.polygons))
    # the existing faces already split the span: estimate their size
    per_face = span / max(1.0, math.sqrt(faces))
    want = max(0, math.ceil(math.log2(max(1.0, per_face / max(0.01, size / 8.0)))))
    cap = max(0, int(math.floor(math.log(max(1.0, MAX_QUADS / faces), 4))))
    return min(want, cap, 11)


def _socket_ids(mod):
    ids = {}
    for item in mod.node_group.interface.items_tree:
        if item.item_type == "SOCKET" and item.in_out == "INPUT":
            ids[item.name] = item.identifier
    return ids


def _set_input(mod, ident, value):
    props = getattr(mod, "properties", None)          # Blender 5: modifier.properties.inputs.<id>.value
    if props is not None and hasattr(props.inputs, ident):
        getattr(props.inputs, ident).value = value
    else:
        mod[ident] = value                             # (older Blender: id properties on the modifier)


def _depth(ob):
    """How deep the water goes under this surface (deepest bottom found + margin), for the closed body."""
    scene = bpy.context.scene
    dg = bpy.context.evaluated_depsgraph_get()
    mw = ob.matrix_world
    me = ob.data
    pts = []
    for poly in me.polygons[:2000]:
        pts.append(mw @ poly.center)
        for vi in poly.vertices:
            pts.append((mw @ me.vertices[vi].co) * 0.8 + (mw @ poly.center) * 0.2)
    if not me.polygons:
        return 0.0
    # a grid over the surface too (a single big quad would give only its centre)
    lo = Vector([min(p[i] for p in pts) for i in range(3)]); hi = Vector([max(p[i] for p in pts) for i in range(3)])
    for i in range(1, 12):
        for j in range(1, 12):
            pts.append(Vector((lo.x + (hi.x - lo.x) * i / 12, lo.y + (hi.y - lo.y) * j / 12, (lo.z + hi.z) / 2)))
    deepest = 0.0
    hide = ob.hide_viewport
    for p in pts[:600]:
        o = p + Vector((0, 0, -0.002))
        for _k in range(4):
            hit, loc, _n, _i, hob, _m = scene.ray_cast(dg, o, Vector((0, 0, -1)), distance=200.0)
            if not hit:
                break
            if hob is not None and (hob.original is ob or hob.name.startswith("twin·")) and (hob.original is ob or hob.data is ob.data):
                o = loc + Vector((0, 0, -0.002))
                continue
            deepest = max(deepest, p.z - loc.z)
            break
    _ = hide
    return min(200.0, deepest + 0.5) if deepest > 0 else 3.0


def _modifier(ob, level, height, size, depth, lower, inset=0.0, up_only=-2.0):
    mod = ob.modifiers.get(MOD)
    if mod is None:
        mod = ob.modifiers.new(MOD, "NODES")
    if mod.node_group is None or mod.node_group.name != GROUP:
        mod.node_group = _group()
    mod.show_viewport = False            # only the path tracing sees it (real-time view: light plane)
    mod.show_render = True
    ids = _socket_ids(mod)
    _set_input(mod, ids["Level"], level)
    _set_input(mod, ids["Height"], height)
    _set_input(mod, ids["Size"], size)
    _set_input(mod, ids["Depth"], depth)
    _set_input(mod, ids["Lower"], lower)
    _set_input(mod, ids["Inset"], inset)
    _set_input(mod, ids["UpOnly"], up_only)
    return mod


_CLOSED = {}


def is_closed(ob):
    """A closed piece (every edge between two faces: a sphere, a box, a glass of water) or an open surface (a plane)."""
    me = ob.data
    key = (me.name, len(me.polygons), len(me.edges))
    if key not in _CLOSED:
        import bmesh
        bm = bmesh.new()
        try:
            bm.from_mesh(me)
            _CLOSED[key] = len(bm.edges) > 0 and all(e.is_manifold for e in bm.edges)
        finally:
            bm.free()
    return _CLOSED[key]


_SHEET = {}


def is_sheet(ob):
    """An open surface lying flat (most of its area facing up or down: a plane, a pond, a terrain of water) - what the
    waves and the body under it are made for. An open SHELL (a glass without top, a vase, a bowl with walls) is
    neither: a slab of water under every face of it made a volume that never closed, and Cycles saw the whole
    scene from inside the water (all black at night, all grey by day)."""
    me = ob.data
    key = (me.name, len(me.polygons))
    if key not in _SHEET:
        import numpy as np
        n = len(me.polygons)
        if n == 0:
            _SHEET[key] = False
        else:
            no = np.empty(n * 3, np.float32); me.polygons.foreach_get("normal", no)
            ar = np.empty(n, np.float32); me.polygons.foreach_get("area", ar)
            no = no.reshape(-1, 3)
            flat = float(ar[np.abs(no[:, 2]) > 0.7].sum()) / max(float(ar.sum()), 1e-12)
            _SHEET[key] = flat > 0.8
    return _SHEET[key]


def shape_of(ob):
    """"closed" (a piece with an inside), "sheet" (a surface of water) or "shell" (open with walls: plain water
    surface, no waves and no body)."""
    return "closed" if is_closed(ob) else ("sheet" if is_sheet(ob) else "shell")


def _remove_waves(ob):
    mod = ob.modifiers.get(MOD)
    if mod is not None:
        ob.modifiers.remove(mod)
        ob.update_tag()


MAX_STEEPNESS = 0.2             # height / size: real waves break at about 1/7; above, the surface is a field of spikes


def _quad_size(ob, level):
    me = ob.data
    if not me.vertices:
        return 0.0
    sc = ob.matrix_world.to_scale()
    xs = [v.co.x for v in me.vertices]; ys = [v.co.y for v in me.vertices]
    span = max((max(xs) - min(xs)) * abs(sc.x), (max(ys) - min(ys)) * abs(sc.y), 1e-3)
    return span / max(1.0, math.sqrt(max(1, len(me.polygons)))) / (2 ** level)


def effective_height(ob, height, size, level):
    if _wants_grid(ob, size):
        return min(float(height), MAX_STEEPNESS * float(size))      # (1.75.0: the grid around the camera draws them)
    return _effective_height(ob, height, size, level)


def _effective_height(ob, height, size, level):
    """The height the waves really get: at most MAX_STEEPNESS × size (higher, they are spikes, and the water turns
    into a grey-white mirror of the sky), and lower when the surface is too large for the subdivision to draw waves
    that small (a 4 km ground: a few metres per quad; 60 cm waves there would only be noise)."""
    h = min(float(height), MAX_STEEPNESS * float(size))
    q = _quad_size(ob, level)
    need = float(size) / 4.0                       # at least 4 quads per wave
    if q > need > 0:
        h *= need / q
    return h


# ---------------------------------------------------------------- the grid around the camera (1.75.0)
#
# A large flat surface of water (the cathedral's Plane: 139 m) could not be subdivided finely enough: at most
# MAX_QUADS for all of it, 27 cm squares - waves of 16 cm were cut to 0.5 cm (the sliders «did nothing») and each
# flat square reflected the sun as a small mirror (squares of light on the columns). Now such a surface gets a grid
# made around the camera, in polar rows: columns dense inside the view (a few pixels apart), sparse behind it; rows
# that follow the size of a pixel on the water, never wider than ~1.4% of their distance. Crack-free (one mesh),
# clipped to the rectangle of the surface. Made again when the camera moves enough (GRID_STEP, GRID_TURN).
# The grid is its own internal object, rendered in place of the surface (it follows it with Copy Transforms and
# carries the same waves): read through Object Info by the surface's modifier, the final render evaluated it
# differently from the view - the water rose to the shoulders of a person (found on Luca's cathedral)

GRID_KEY = "simpler_water_grid"
GRID_PX = 4.0                   # pixels between two columns inside the view
GRID_ISO = 0.014                # rows never wider than this x their distance
GRID_STEP = 0.25                # m: the camera moved this much -> another grid
GRID_TURN = 6.0                 # degrees of turn -> another grid
GRID_MARGIN = 25.0              # degrees each side of the view still dense (a turn of the camera, reflections at the edge)
GRID_MAX_COLS = 1200


def _rect(ob):
    """The surface as a flat rectangle in its local space: (x0, y0, x1, y1, z), or None (another shape)."""
    me = ob.data
    if not me.vertices or not me.polygons:
        return None
    import numpy as np
    co = np.empty(len(me.vertices) * 3, np.float32); me.vertices.foreach_get("co", co)
    co = co.reshape(-1, 3)
    lo, hi = co.min(0), co.max(0)
    if hi[2] - lo[2] > 1e-4 * max(1e-6, float(max(hi[0] - lo[0], hi[1] - lo[1]))):
        return None
    ar = np.empty(len(me.polygons), np.float32); me.polygons.foreach_get("area", ar)
    box = float((hi[0] - lo[0]) * (hi[1] - lo[1]))
    if box <= 0 or abs(float(ar.sum()) - box) > 0.01 * box:
        return None                             # (not a full rectangle: a pond, a river - the subdivision as before)
    return float(lo[0]), float(lo[1]), float(hi[0]), float(hi[1]), float(lo[2])


def _wants_grid(ob, size):
    """The grid around the camera for this surface: a flat rectangle the subdivision cannot draw these waves on."""
    if is_closed(ob) or not is_sheet(ob) or bpy.context.scene.camera is None:
        return False
    return _quad_size(ob, _level(ob, size)) > size / 4.0 and _rect(ob) is not None


def _cam_key(ob):
    cam = bpy.context.scene.camera
    m = ob.matrix_world.inverted() @ cam.matrix_world
    p = m.translation
    fwd = cam.matrix_world.to_3x3() @ Vector((0.0, 0.0, -1.0))
    yaw = math.degrees(math.atan2(fwd.y, fwd.x))
    pitch = math.degrees(math.asin(max(-1.0, min(1.0, fwd.z))))
    sc = ob.matrix_world.to_scale()
    q = lambda v, st: round(v / st)
    return [q(p.x * abs(sc.x), GRID_STEP), q(p.y * abs(sc.y), GRID_STEP), q(p.z * abs(sc.z), GRID_STEP),
            q(yaw, GRID_TURN), q(pitch, GRID_TURN), round(math.degrees(cam.data.angle), 1),
            bpy.context.scene.render.resolution_x]


def _grid_object(ob):
    from .core import INTERNAL_KEY, ID_KEY
    oid = ob.get(ID_KEY, "") or ob.name
    for o in bpy.data.objects:
        if o.get(GRID_KEY) == oid:
            return o
    me = bpy.data.meshes.new(f"{ob.name} · griglia")
    g = bpy.data.objects.new(me.name, me)
    g[INTERNAL_KEY] = 1
    g[GRID_KEY] = oid
    bpy.context.scene.collection.objects.link(g)
    c = g.constraints.new("COPY_TRANSFORMS")
    c.target = ob
    g.hide_viewport = True               # (the real-time view shows the surface itself, flat)
    g.hide_select = True
    return g


def grid_of(ob):
    """The grid that draws this surface around the camera (rendered in its place), or None."""
    from .core import ID_KEY
    oid = ob.get(ID_KEY, "") or ob.name
    for o in bpy.data.objects:
        if o.get(GRID_KEY) == oid and o.name in bpy.context.scene.objects:
            return o
    return None


def _remove_grid(ob):
    from .core import ID_KEY
    oid = ob.get(ID_KEY, "") or ob.name
    for o in [o for o in bpy.data.objects if o.get(GRID_KEY) == oid]:
        me = o.data
        bpy.data.objects.remove(o, do_unlink=True)
        if me.users == 0:
            bpy.data.meshes.remove(me)


def _axis_rows(h, size, rmax):
    """Distances of the rows from the point under the camera (metres)."""
    import numpy as np
    sc = bpy.context.scene.render
    px = float(bpy.context.scene.camera.data.angle) / max(64, sc.resolution_x * sc.resolution_percentage / 100.0)
    da = GRID_PX * px
    h = max(0.05, h)
    rs = [0.0]
    r = 0.0
    while r < rmax:
        dr = da * (h * h + r * r) / h                  # (one step of the view's angle, on the water)
        dr = min(dr, max(size / 10.0, GRID_ISO * r))   # (never too wide for its distance)
        dr = max(dr, size / 10.0)                      # (never finer than the waves need)
        r += dr
        rs.append(min(r, rmax))
    return np.array(rs), da


def _view_grid(ob, size):
    """Builds the grid of this surface around the camera (in its local space) and returns its object."""
    import numpy as np
    x0, y0, x1, y1, z = _rect(ob)
    sc = ob.matrix_world.to_scale()
    sx, sy = max(1e-9, abs(sc.x)), max(1e-9, abs(sc.y))
    cam = bpy.context.scene.camera
    m = ob.matrix_world.inverted() @ cam.matrix_world
    cx, cy = m.translation.x * sx, m.translation.y * sy           # metres in the plane of the surface
    h = abs(m.translation.z - z) * abs(sc.z)
    fwd = m.to_3x3() @ Vector((0.0, 0.0, -1.0))
    yaw = math.atan2(fwd.y * sy, fwd.x * sx)
    X0, Y0, X1, Y1 = x0 * sx, y0 * sy, x1 * sx, y1 * sy
    rmax = max(math.hypot(px - cx, py - cy) for px in (X0, X1) for py in (Y0, Y1)) + 0.5
    rows, da = _axis_rows(h, size, rmax)
    # columns: dense within the view (and a margin), sparse behind
    r_ = bpy.context.scene.render
    aspect = max(1.0, (r_.resolution_x * r_.pixel_aspect_x) / max(1, r_.resolution_y * r_.pixel_aspect_y))
    half = float(cam.data.angle) / 2.0 if aspect >= 1.0 else float(cam.data.angle) / 2.0 * aspect
    half = min(math.pi, half + math.radians(GRID_MARGIN))
    dense = max(8, min(GRID_MAX_COLS, int(math.ceil(2 * half / da))))
    a_in = np.linspace(-half, half, dense + 1)
    back = 2 * math.pi - 2 * half
    nb = max(2, int(math.ceil(back / math.radians(3.0))))
    a_back = half + np.arange(1, nb) * back / nb
    ang = np.concatenate([a_in, a_back]) + yaw                  # (closed around: the last column meets the first)
    nc, nr = len(ang), len(rows)
    R, A = np.meshgrid(rows[1:], ang, indexing="ij")           # (row 0 is the centre: one vertex)
    X = cx + R * np.cos(A); Y = cy + R * np.sin(A)
    # columns' spacing at each point (for the fade of the waves)
    dA = np.diff(np.concatenate([ang, [ang[0] + 2 * math.pi]]))
    dAm = np.maximum(dA, np.roll(dA, 1))
    dR = np.diff(rows)
    cell = np.maximum(dR[:, None], R * dAm[None, :])
    inside = (X >= X0) & (X <= X1) & (Y >= Y0) & (Y <= Y1)
    Xc, Yc = np.clip(X, X0, X1), np.clip(Y, Y0, Y1)
    # vertices: centre + rings
    cX, cY = min(max(cx, X0), X1), min(max(cy, Y0), Y1)
    VX = np.concatenate([[cX], Xc.ravel()]); VY = np.concatenate([[cY], Yc.ravel()])
    VC = np.concatenate([[size / 10.0], cell.ravel()])
    VI = np.concatenate([[cx >= X0 and cx <= X1 and cy >= Y0 and cy <= Y1], inside.ravel()])
    idx = lambda r, c: 1 + r * nc + (c % nc)
    faces = []
    c = np.arange(nc)
    # the fan around the centre
    fan = np.stack([np.zeros(nc, np.int64), idx(0, c), idx(0, c + 1)], axis=1)
    rr, cc = np.meshgrid(np.arange(nr - 2), c, indexing="ij")
    rr, cc = rr.ravel(), cc.ravel()
    quads = np.stack([idx(rr, cc), idx(rr + 1, cc), idx(rr + 1, cc + 1), idx(rr, cc + 1)], axis=1)
    # only what touches the rectangle (the rest of the disc is cut away)
    keep_f = VI[fan].any(1)
    keep_q = VI[quads].any(1)
    fan, quads = fan[keep_f], quads[keep_q]
    used = np.zeros(len(VX), bool); used[fan.ravel()] = True; used[quads.ravel()] = True
    remap = np.cumsum(used) - 1
    co = np.stack([VX[used] / sx, VY[used] / sy, np.full(int(used.sum()), z)], axis=1).astype(np.float32)
    fan, quads = remap[fan], remap[quads]
    g = _grid_object(ob)
    me = g.data
    me.clear_geometry()
    me.vertices.add(len(co))
    me.vertices.foreach_set("co", co.ravel())
    loops = np.concatenate([fan.ravel(), quads.ravel()]).astype(np.int32)
    me.loops.add(len(loops))
    me.loops.foreach_set("vertex_index", loops)
    nf, nq = len(fan), len(quads)
    me.polygons.add(nf + nq)
    starts = np.concatenate([np.arange(0, 3 * nf, 3), 3 * nf + np.arange(0, 4 * nq, 4)]).astype(np.int32)
    me.polygons.foreach_set("loop_start", starts)
    me.update(calc_edges=True)
    me.validate(clean_customdata=False)            # (corners clipped onto one point: degenerate faces removed)
    # the materials of the surface (Object Info brings the grid's own: without them the water was a grey floor)
    me.materials.clear()
    for sl in ob.material_slots:
        me.materials.append(sl.material)
    a = me.attributes.get("simpler_cell") or me.attributes.new("simpler_cell", "FLOAT", "POINT")
    if len(a.data) == int(used.sum()):
        a.data.foreach_set("value", VC[used].astype(np.float32))
    from .core import log
    log("SIMPLER_WATER", f"grid around the camera for {ob.name}: {len(me.polygons)} faces, {nc} columns x {nr} rows")
    return g


def _sync(ob, force=False):
    try:
        if ob.get(GRID_KEY):
            return None                 # (the grid of a surface: made by its surface, see _view_grid)
    except ReferenceError:              # (removed meanwhile: e.g. a grid rebuilt by its surface in the same loop)
        return None
    """The object follows the water of its material: waves (its own modifier) and the closed body of the water (a
    hidden object, see _body). Cheap when nothing changed (a signature of what they were made from)."""
    mat = water_material(ob)
    if mat is None:
        _remove_waves(ob)
        _remove_grid(ob)
        _remove_body(ob)
        if SIG_KEY in ob:
            del ob[SIG_KEY]
        return None
    ws = mat_settings(mat)
    w = ws["waves"]
    sc = ob.matrix_world.to_scale()
    from . import ice
    wf = ice.wave_factor(mat)
    grid = bool(w["on"]) and _wants_grid(ob, w["size"])
    sig = json.dumps([w["on"], round(w["height"], 5), round(w["size"], 5), ws["body"]["on"], len(ob.data.polygons),
                      [round(x, 4) for x in sc], mat.name, round(wf, 4), _cam_key(ob) if grid else None])
    has_mod = ob.modifiers.get(MOD) is not None
    has_body = _find_body(ob) is not None
    shell = shape_of(ob) == "shell"
    if not force and ob.get(SIG_KEY) == sig and has_mod == (w["on"] and not shell) \
            and has_body == (ws["body"]["on"] and not shell):
        return ws
    ob[SIG_KEY] = sig
    if shell:
        # an open object with walls: the water is only its surface material (clear, index 1.333), like a glass
        _remove_waves(ob)
        _remove_body(ob)
        ob.update_tag()
        return ws
    level = _level(ob, w["size"]) if w["on"] else 0
    if grid:
        h = min(float(w["height"]), MAX_STEEPNESS * float(w["size"])) * wf
    else:
        h = effective_height(ob, w["height"], w["size"], level) * wf if w["on"] else 0.0       # (frozen: calmer)
    s = {"on": w["on"], "height": h, "size": w["size"]}
    if w["on"]:
        mod = _modifier(ob, level, h, w["size"], 0.0, 0.0, 0.0, 0.7 if is_closed(ob) else -2.0)
        ids = _socket_ids(mod)
        _set_input(mod, ids["UseGrid"], grid)          # (with the grid: nothing here, the grid is rendered instead)
        if grid:
            g = _view_grid(ob, w["size"])
            gm = _modifier(g, 0, h, w["size"], 0.0, 0.0, 0.0, -2.0)
            _set_input(gm, _socket_ids(gm)["UseGrid"], False)
            g.hide_render = ob.hide_render
            for a in ("visible_camera", "visible_diffuse", "visible_glossy", "visible_transmission", "visible_shadow"):
                setattr(g, a, getattr(ob, a))
            g.cycles.is_caustics_caster = ob.cycles.is_caustics_caster
            g.cycles.is_caustics_receiver = ob.cycles.is_caustics_receiver
            g.update_tag()
    else:
        _remove_waves(ob)
    if not grid:
        _remove_grid(ob)
    ob.update_tag()
    if ws["body"]["on"]:
        if force:
            ob["simpler_water_depth"] = 0.0         # measured again
        _body(ob, mat, s)
    else:
        _remove_body(ob)
    return ws


# The body of the water is its own object: Cycles MNEE (sharp caustics) finds no caustic through a surface that
# carries a volume, so the surface of the water stays a plain glass (caster of the caustics) and the volume lives in
# a closed, invisible box around it (Transparent surface + volume): from a few millimetres above the crests down to
# the deepest bottom under the surface. It shares the mesh of the surface and follows it (Copy Transforms); hidden in the viewport (no
# clicks, no real-time export), rendered only by Cycles.
BODY_KEY = "simpler_water_body"


_BODIES = None


def _find_body(ob):
    """The body of this water. One look at every object per request (1.70.3): looked for object by object, a material
    given to a model of 3,800 pieces looked through all the scene 3,800 times - 48 s on the cathedral."""
    global _BODIES
    from .core import ID_KEY, per_request
    if _BODIES is None:
        _BODIES = per_request({})
    if not _BODIES:
        _BODIES[None] = None                        # (looked: the file has these bodies - also set aside ones)
        for o in bpy.data.objects:
            k = o.get(BODY_KEY)
            if k:
                _BODIES.setdefault(k, []).append(o)
    oid = ob.get(ID_KEY, "") or ob.name
    if oid not in _BODIES:
        return None
    scene = bpy.context.scene.objects
    for body in _BODIES[oid]:
        try:
            if body.get(BODY_KEY) == oid and scene.get(body.name) == body:
                return body
        except ReferenceError:
            pass
    for o in scene:                                 # (moved meanwhile: looked for as before)
        if o.get(BODY_KEY) == oid:
            _BODIES[oid] = [o]
            return o
    return None


def _body_material(mat):
    name = f"{mat.name} · corpo"
    bm = bpy.data.materials.get(name)
    if bm is None:
        bm = bpy.data.materials.new(name)
        bm.use_nodes = True
        nt = bm.node_tree
        for n in list(nt.nodes):
            if n.type != "OUTPUT_MATERIAL":
                nt.nodes.remove(n)
        out = next(n for n in nt.nodes if n.type == "OUTPUT_MATERIAL")
        tr_ = nt.nodes.new("ShaderNodeBsdfTransparent")
        tr_.location = (out.location.x - 260, out.location.y)
        nt.links.new(tr_.outputs[0], out.inputs["Surface"])
        bm["simpler_body_of"] = mat.name
        bm.use_fake_user = False
    _volume_nodes(bm, dict(mat_settings(mat)["body"]))
    return bm


def _body(ob, mat, s):
    from .core import ID_KEY, INTERNAL_KEY
    body = _find_body(ob)
    if body is None:
        body = bpy.data.objects.new(f"{ob.name} · corpo", ob.data)
        body[INTERNAL_KEY] = 1
        body[BODY_KEY] = ob.get(ID_KEY, "") or ob.name
        bpy.context.scene.collection.objects.link(body)
        if _BODIES:
            _BODIES.setdefault(body[BODY_KEY], []).insert(0, body)
        c = body.constraints.new("COPY_TRANSFORMS")
        c.target = ob
        body.hide_select = True
    if body.data is not ob.data:
        body.data = ob.data
    body.hide_viewport = True             # not in clicks nor in the real-time view; rendered by Cycles
    body.hide_render = False
    for sl in body.material_slots:
        sl.link = "OBJECT"
    bm = _body_material(mat)
    for sl in body.material_slots:
        if sl.material is not bm:
            sl.material = bm
    body.cycles.is_caustics_caster = False
    body.cycles.is_caustics_receiver = False
    body.visible_diffuse = body.visible_glossy = body.visible_camera = body.visible_transmission = True
    body.visible_shadow = True
    if is_closed(ob):
        # a closed piece of water is its own container: the body is the same shape, 2 mm inside (no box under it)
        _modifier(body, 0, 0.0, 1.0, 0.0, 0.0, (s["height"] / 2.0 if s["on"] else 0.0) + 0.002, -2.0)
        body.update_tag()
        return 0.0
    depth = float(ob.get("simpler_water_depth", 0.0))
    if depth <= 0:
        depth = _depth(ob)
        ob["simpler_water_depth"] = depth
    # the top of the body just ABOVE the crests of the waves: MNEE finds no caustic when a ray from the bottom meets
    # another surface (even a transparent one) before the surface of the water; above it, it does not matter
    lower = -((s["height"] / 2.0 if s["on"] else 0.0) + 0.003)
    _modifier(body, 0, 0.0, 1.0, depth, lower)
    body.update_tag()
    return depth


def _remove_body(ob):
    body = _find_body(ob)
    if body is not None:
        bpy.data.objects.remove(body, do_unlink=True)


# ---------------------------------------------------------------- water as a property of the material

MKEY = "simpler_water"          # JSON on the material: {on, waves: {on, height, size}, body: {on, color, clarity, murk}}
SIG_KEY = "simpler_water_sig"
MDEFAULTS = {"on": False, "waves": {"on": True, "height": 0.08, "size": 0.6},
             "body": {"on": True, "color": "piscina", "clarity": 25.0, "murk": 0.0},
             "ice": {"on": False, "amount": 0.5, "clear": 0.6, "bubbles": 0.3, "cracks": 1.0, "cracksFine": 1.0},      # (ice: ice.py)
             "rings": {"on": True, "amount": 0.5, "size": 0.5, "strength": 1.0}}         # (rings of the rain: ripples.py)


def mat_settings(mat):
    """Water settings of a material (defaults filled in; projects of 1.13: the body settings found there)."""
    s = json.loads(json.dumps(MDEFAULTS))
    if mat is None:
        return s
    raw = mat.get(MKEY)
    if raw:
        try:
            d = json.loads(raw)
            s["on"] = bool(d.get("on", False))
            s["waves"].update(d.get("waves") or {})
            s["body"].update(d.get("body") or {})
            s["ice"].update(d.get("ice") or {})
            s["rings"].update(d.get("rings") or {})
        except (TypeError, ValueError):
            pass
    elif VKEY in mat:
        v = volume_settings(mat)
        s["on"] = True
        s["body"].update({k: v[k] for k in ("on", "color", "clarity", "murk")})
        s["waves"]["on"] = False
    return s


def is_water(mat):
    return mat is not None and mat_settings(mat)["on"]


def water_material(ob):
    if ob is None or ob.type != "MESH" or ob.get(BODY_KEY):
        return None
    for sl in ob.material_slots:
        if sl.material is not None and is_water(sl.material):
            return sl.material
    return None


def _users(mat):
    return [o for o in bpy.context.scene.objects if o.type == "MESH" and not o.get(BODY_KEY)
            and not o.get(GRID_KEY) and any(sl.material is mat for sl in o.material_slots)]


def set_material(data):
    """POST /api/material/water {name, on?, waves?: {on, height, size}, body?: {on, color, clarity, murk}}.
    Turning the water on makes the material a clear water (transparency 100%, index 1.333, smooth): then it can be
    changed as any other material."""
    from .core import ApiError
    from .i18n import tr
    mat = bpy.data.materials.get(data.get("name") or "")
    if mat is None:
        raise ApiError(tr("Materiale non trovato"))
    from . import terrain
    mat = terrain.source_of(mat)       # (1.76.4) a zone of a terrain: its own material, not the blended copy
    s = mat_settings(mat)
    was_on = s["on"] and bool(mat.get(MKEY))
    if "on" in data:
        s["on"] = bool(data["on"])
    for part in ("waves", "body", "ice", "rings"):
        if isinstance(data.get(part), dict):
            s[part].update(data[part])
    ic = s["ice"]
    ic["on"] = bool(ic["on"])
    for k in ("amount", "clear", "bubbles"):
        ic[k] = max(0.0, min(1.0, float(ic[k])))
    for k in ("cracks", "cracksFine"):
        ic[k] = max(0.0, min(2.0, float(ic[k])))
    rg = s["rings"]
    rg["on"] = bool(rg["on"])
    for k in ("amount", "size"):
        rg[k] = max(0.0, min(1.0, float(rg[k])))
    rg["strength"] = max(0.0, min(2.0, float(rg["strength"])))
    w, b = s["waves"], s["body"]
    w["on"] = bool(w["on"]); b["on"] = bool(b["on"])
    w["height"] = max(0.0, min(2.0, float(w["height"])))
    w["size"] = max(0.05, min(20.0, float(w["size"])))
    if b["color"] not in COLORS:
        b["color"] = "piscina"
    b["clarity"] = max(0.5, min(500.0, float(b["clarity"])))
    b["murk"] = max(0.0, min(1.0, float(b["murk"])))
    mat[MKEY] = json.dumps(s)
    if VKEY in mat:
        del mat[VKEY]
    if s["on"] and not was_on:
        _remember_standard(mat)
        make_clear_water(mat)
    elif was_on and not s["on"]:
        _restore_standard(mat)
    bm = bpy.data.materials.get(f"{mat.name} · corpo")
    if bm is not None:
        _volume_nodes(bm, dict(b))
    for ob in _users(mat):
        _sync(ob, force=True)
    from . import ice, ripples
    ice.update()
    ripples.update()            # (after the ice: the ice taken away first, then the rings in its place)
    ice.touch()
    return {"name": mat.name, "water": editor_info(mat)}


PREV_KEY = "simpler_water_prev"   # the channels water changes, as they were before (back to Standard: restored)


def _remember_standard(mat):
    from . import matedit
    try:
        p, _adv = matedit.read_material(mat)
        mat[PREV_KEY] = json.dumps({"transmission": {k: p["transmission"].get(k) for k in ("weight", "ior", "thin") if k in p["transmission"]},
                                    "roughness": {"value": p["roughness"].get("value")},
                                    "metallic": {"value": p["metallic"].get("value")}})
    except Exception as exc:
        print("SIMPLER_WATER remember", mat.name, exc, flush=True)


def _restore_standard(mat):
    """Type back to Standard: transparency, index, roughness and metal as they were before the water (the other
    channels keep what was changed meanwhile). Without a record: an opaque material."""
    from . import matedit
    raw = mat.get(PREV_KEY)
    try:
        prev = json.loads(raw) if raw else {"transmission": {"weight": 0.0, "ior": 1.5}}
        prev = {k: {kk: vv for kk, vv in v.items() if vv is not None} for k, v in prev.items()}
        matedit.edit({"name": mat.name, "convert": True, "params": prev})
    except Exception as exc:
        print("SIMPLER_WATER restore", mat.name, exc, flush=True)
    if PREV_KEY in mat:
        del mat[PREV_KEY]


def make_clear_water(mat):
    from . import matedit
    try:
        matedit.edit({"name": mat.name, "convert": True, "params": {
            "transmission": {"weight": 1.0, "ior": 1.333, "thin": False}, "roughness": {"value": 0.0},
            "metallic": {"value": 0.0, "map": matedit._map()}}})
    except Exception as exc:                     # an unusual material: the water settings stay anyway
        print("SIMPLER_WATER material", mat.name, exc, flush=True)


def editor_info(mat):
    s = mat_settings(mat)
    quads = 0
    if s["on"] and s["waves"]["on"]:
        for ob in _users(mat):
            quads += len(ob.data.polygons) * 4 ** _level(ob, s["waves"]["size"])
    s["quads"] = quads
    eff, limit, span = None, None, 0.0
    if s["on"] and s["waves"]["on"]:
        for ob in _users(mat):
            e = effective_height(ob, s["waves"]["height"], s["waves"]["size"], _level(ob, s["waves"]["size"]))
            if eff is None or e < eff:
                eff = e
                # why (1.74.0, the app says what to do): too steep for their size, or a surface too large to draw them
                steep = min(float(s["waves"]["height"]), MAX_STEEPNESS * float(s["waves"]["size"]))
                limit = "size" if e < steep * 0.95 else "steep"
                span = max(ob.dimensions.x, ob.dimensions.y)
    s["effectiveHeight"] = eff
    s["waveLimit"] = limit
    s["span"] = round(span, 1)
    s["colors"] = list(COLORS.keys())
    from . import ice
    s["snowing"] = ice.snow_amount() > 0.0
    from . import raindrops
    s["raining"] = raindrops.intensity() > 0.0
    s["shells"] = sum(1 for ob in _users(mat) if shape_of(ob) == "shell")
    return s


def migrate(ob):
    """Projects of 1.12-1.13: the waves were on the object; they go to its water material (once)."""
    if KEY not in ob:
        return
    try:
        old = json.loads(ob[KEY])
    except (TypeError, ValueError):
        old = {}
    mats = [sl.material for sl in ob.material_slots if sl.material is not None and _transmissive(sl.material)]
    if old.get("on") and mats and MKEY not in mats[0]:
        s = mat_settings(mats[0])
        s["on"] = True
        s["waves"] = {"on": True, "height": float(old.get("height", 0.08)), "size": float(old.get("size", 0.6))}
        mats[0][MKEY] = json.dumps(s)
    del ob[KEY]


def _transmissive(mat):
    from . import materials
    return materials.is_transmissive(mat)


# ---------------------------------------------------------------- the body of the water (volume in the material)

def volume_settings(mat):
    s = dict(VDEFAULTS)
    if mat is None:
        return s
    try:
        s.update(json.loads(mat.get(VKEY, "{}")))
    except (TypeError, ValueError):
        pass
    return s


def set_volume(mat, data):
    s = volume_settings(mat)
    for k in ("on", "color", "clarity", "murk"):
        if k in data:
            s[k] = data[k]
    s["on"] = bool(s["on"])
    if s["color"] not in COLORS:
        s["color"] = VDEFAULTS["color"]
    s["clarity"] = max(0.5, min(500.0, float(s["clarity"])))
    s["murk"] = max(0.0, min(1.0, float(s["murk"])))
    mat[VKEY] = json.dumps(s)
    bm = bpy.data.materials.get(f"{mat.name} · corpo")
    if bm is not None:
        _volume_nodes(bm, s)
    return s


def coefficients(s):
    """(absorption RGB, scattering) per metre. The colour of 1 m of water plus the clarity: the haze at "clarity"
    metres swallows ~63% of the light; "murk" is the share of it that is scattered (milky) instead of absorbed."""
    t = COLORS.get(s["color"], COLORS["piscina"])
    k = 1.0 / max(0.5, float(s["clarity"]))
    murk = float(s["murk"])
    absorb = [-math.log(max(1e-4, c)) + k * (1.0 - murk) for c in t]
    return absorb, k * murk


def _volume_nodes(mat, s=None):
    """Volume Absorption (+ Volume Scatter when murky) into the Volume of the material output; removed when off."""
    if mat is None or not mat.use_nodes or mat.node_tree is None:
        return
    s = s or volume_settings(mat)
    nt = mat.node_tree
    old = [n for n in nt.nodes if n.name.startswith("simpler_vol")]
    outs = [n for n in nt.nodes if n.type == "OUTPUT_MATERIAL"]
    out = next((n for n in outs if n.is_active_output), outs[0] if outs else None)
    if not s["on"]:
        for n in old:
            nt.nodes.remove(n)
        return
    if out is None:
        return
    absorb, scatter = coefficients(s)
    dens = max(absorb)
    col = tuple(1.0 - a / dens for a in absorb)
    ab = nt.nodes.get("simpler_vol_abs") or nt.nodes.new("ShaderNodeVolumeAbsorption")
    ab.name = "simpler_vol_abs"; ab.label = "Acqua: assorbimento"
    ab.location = (out.location.x - 260, out.location.y - 260)
    ab.inputs["Color"].default_value = (*col, 1.0)
    ab.inputs["Density"].default_value = dens
    final = ab.outputs[0]
    sc = nt.nodes.get("simpler_vol_sca")
    if scatter > 1e-5:
        sc = sc or nt.nodes.new("ShaderNodeVolumeScatter")
        sc.name = "simpler_vol_sca"; sc.label = "Acqua: torbidità"
        sc.location = (out.location.x - 260, out.location.y - 420)
        t = COLORS.get(s["color"], COLORS["piscina"])
        sc.inputs["Color"].default_value = (*t, 1.0)
        sc.inputs["Density"].default_value = scatter
        sc.inputs["Anisotropy"].default_value = 0.6       # water scatters forwards
        add = nt.nodes.get("simpler_vol_add") or nt.nodes.new("ShaderNodeAddShader")
        add.name = "simpler_vol_add"
        add.location = (out.location.x - 120, out.location.y - 300)
        nt.links.new(ab.outputs[0], add.inputs[0]); nt.links.new(sc.outputs[0], add.inputs[1])
        final = add.outputs[0]
    else:
        for name in ("simpler_vol_sca", "simpler_vol_add"):
            n = nt.nodes.get(name)
            if n is not None:
                nt.nodes.remove(n)
    if not out.inputs["Volume"].is_linked or out.inputs["Volume"].links[0].from_socket != final:
        nt.links.new(final, out.inputs["Volume"])
    if hasattr(mat.cycles, "homogeneous_volume"):
        mat.cycles.homogeneous_volume = True             # a constant density: no ray marching (fast; Blender 5 sees it)


def ensure():
    """Before every path-traced image: every object follows the water of its material (waves, body); bodies of
    removed or deleted water go away. Cheap when nothing changed."""
    from .core import ID_KEY
    owners = {}
    for ob in bpy.context.scene.objects:
        if ob.type == "MESH" and not ob.get(BODY_KEY) and not ob.get(GRID_KEY):
            owners[ob.get(ID_KEY, "") or ob.name] = ob
    for body in [o for o in bpy.context.scene.objects if o.get(BODY_KEY)]:
        src = owners.get(body[BODY_KEY])
        if src is None or src.get("simpler_trashed") or water_material(src) is None:
            bpy.data.objects.remove(body, do_unlink=True)
    for g in [o for o in bpy.context.scene.objects if o.get(GRID_KEY)]:
        src = owners.get(g[GRID_KEY])
        if src is None or src.get("simpler_trashed") or water_material(src) is None:
            gname = g.name
            _remove_grid(src if src is not None else g)
            gg = bpy.data.objects.get(gname)
            if gg is not None:
                bpy.data.objects.remove(gg, do_unlink=True)
    for ob in owners.values():
        if ob.get("simpler_trashed"):
            continue
        migrate(ob)
        if water_material(ob) is not None or ob.modifiers.get(MOD) is not None:
            _sync(ob)
    from . import ice, ripples
    ice.update()                # (the frozen water: ice.py)
    ripples.update()            # (the rings of the rain: ripples.py - after the ice, which may just have gone)
