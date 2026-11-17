"""Cerchi della pioggia: while the drops fall (raindrops.py), the water of a material «Acqua» gets the rings of the rain
- circles that open from where a drop hit and fade as they grow («Cerchi della pioggia», Avanzate of the water).

Settings in the water of the material (water.py, MKEY, part "rings"):
  on        rings while it rains with drops (default on)
  amount    0..1 «Quantità»: how many rings at once (x the intensity of the rain)
  size      0..1 «Dimensione»: cells of 15..75 cm, rings up to 0.3 of a cell
  strength  0..2 «Forza»: how marked they are (the slope of their crests)

How (no geometry, only the shading normal): three layers of cells (Voronoi F1, randomness 0.5, scales 1, 0.73, 1.37
of the size, shifted); in every cell a ring of age t = fract(random + 0.37 layer), radius R = 0.04 + 0.26 t (cells),
present when another random < amount * (0.25 + 0.75 rain) * 0.9; its height cos(2π x / 0.09) exp(-(x / w)²) (1 - t)²,
x = distance - R, w = 0.035 + 0.03 t; the sum over the layers is a bump of 2 mm x strength x (cell / 0.45 m) - on
what faces up only (smooth 0.8..0.95 of the normal), not under a shelter (the shelter map of the rain, 0.45 m more:
the water is lifted there). The real-time
view (viewer.js, ringsPatch) uses the same formula.
"""
import json

import bpy

from .core import log

GROUP = "Simpler Cerchi pioggia v1"
NODE = "simpler_rings"
DEFAULTS = {"on": True, "amount": 0.5, "size": 0.5, "strength": 1.0}
LAYERS = ((1.0, (0.0, 0.0)), (0.73, (17.31, 5.17)), (1.37, (-9.43, 23.71)))
_SIG = {}


def settings(mat):
    from . import water
    s = dict(DEFAULTS)
    s.update(water.mat_settings(mat).get("rings") or {})
    return s


def cell_size(size):
    return 0.15 + 0.6 * float(size)


def _group():
    g = bpy.data.node_groups.get(GROUP)
    if g is not None:
        return g
    g = bpy.data.node_groups.new(GROUP, "ShaderNodeTree")
    try:
        _fill(g)
    except Exception:
        bpy.data.node_groups.remove(g)          # (never a half group left: made again next time)
        raise
    return g


def _fill(g):
    I = g.interface
    for name, dv in (("Rain", 0.0), ("Amount", 0.5), ("Size", 0.5), ("Strength", 1.0)):
        I.new_socket(name, in_out="INPUT", socket_type="NodeSocketFloat").default_value = dv
    I.new_socket("NormalIn", in_out="INPUT", socket_type="NodeSocketVector").default_value = (0.0, 0.0, 1.0)
    I.new_socket("Normal", in_out="OUTPUT", socket_type="NodeSocketVector")
    N, L = g.nodes, g.links
    gi, go = N.new("NodeGroupInput"), N.new("NodeGroupOutput")

    def put(sock, x):
        if isinstance(x, (int, float)):
            sock.default_value = x
        else:
            L.new(x, sock)

    def m(op, a, b=None, c=None):
        n = N.new("ShaderNodeMath"); n.operation = op
        for i, x in enumerate((a, b, c)):
            if x is not None:
                put(n.inputs[i], x)
        return n.outputs[0]

    def smooth(e0, e1, x):
        n = N.new("ShaderNodeMapRange"); n.interpolation_type = "SMOOTHSTEP"; n.clamp = True
        put(n.inputs["Value"], x); put(n.inputs["From Min"], e0); put(n.inputs["From Max"], e1)
        return n.outputs["Result"]

    def val(name, v):
        n = N.new("ShaderNodeValue"); n.name = n.label = name; n.outputs[0].default_value = v
        return n.outputs[0]

    geo = N.new("ShaderNodeNewGeometry")
    sp = N.new("ShaderNodeSeparateXYZ"); L.new(geo.outputs["Position"], sp.inputs[0])
    sn = N.new("ShaderNodeSeparateXYZ"); L.new(geo.outputs["Normal"], sn.inputs[0])
    cell = m("MULTIPLY_ADD", gi.outputs["Size"], 0.6, 0.15)
    dens = m("MULTIPLY", m("MULTIPLY", gi.outputs["Amount"], m("MULTIPLY_ADD", gi.outputs["Rain"], 0.75, 0.25)), 0.9)
    total = None
    for k, (sc, (ox, oy)) in enumerate(LAYERS):
        s = m("MULTIPLY", cell, sc)
        q = N.new("ShaderNodeCombineXYZ")
        L.new(m("ADD", m("DIVIDE", sp.outputs["X"], s), ox), q.inputs["X"])
        L.new(m("ADD", m("DIVIDE", sp.outputs["Y"], s), oy), q.inputs["Y"])
        vor = N.new("ShaderNodeTexVoronoi"); vor.voronoi_dimensions = "2D"; vor.feature = "F1"
        vor.inputs["Scale"].default_value = 1.0; vor.inputs["Randomness"].default_value = 0.5
        L.new(q.outputs[0], vor.inputs["Vector"])
        rgb = N.new("ShaderNodeSeparateColor"); L.new(vor.outputs["Color"], rgb.inputs[0])
        t = m("FRACT", m("ADD", rgb.outputs[0], 0.37 * k))
        act = m("LESS_THAN", rgb.outputs[1], dens)
        x = m("SUBTRACT", vor.outputs["Distance"], m("MULTIPLY_ADD", t, 0.26, 0.04))
        w = m("MULTIPLY_ADD", t, 0.03, 0.035)
        env = m("EXPONENT", m("MULTIPLY", m("POWER", m("DIVIDE", x, w), 2.0), -1.0))
        h = m("MULTIPLY", m("COSINE", m("MULTIPLY", x, 6.283185 / 0.09)), env)
        fade = m("POWER", m("SUBTRACT", 1.0, t), 2.0)
        h = m("MULTIPLY", h, m("MULTIPLY", fade, act))
        total = h if total is None else m("ADD", total, h)
    # on what faces up, not under a shelter (the same lookup as the rain's group: rain._shelter_to_group fills it)
    sh_on, x0, y0, sinv = val("sh_on", 0.0), val("sh_x0", 0.0), val("sh_y0", 0.0), val("sh_inv", 1.0)
    zmin, zr, lo = val("sh_zmin", 0.0), val("sh_zr", 1.0), val("sh_lo", 0.5)
    uvs = N.new("ShaderNodeCombineXYZ")
    L.new(m("MULTIPLY", m("SUBTRACT", sp.outputs["X"], x0), sinv), uvs.inputs["X"])
    L.new(m("MULTIPLY", m("SUBTRACT", sp.outputs["Y"], y0), sinv), uvs.inputs["Y"])
    stex = N.new("ShaderNodeTexImage"); stex.name = "shelter"; stex.interpolation = "Linear"; stex.extension = "CLIP"
    L.new(uvs.outputs[0], stex.inputs["Vector"])
    ssep = N.new("ShaderNodeSeparateColor"); L.new(stex.outputs["Color"], ssep.inputs[0])
    v = ssep.outputs[0]
    height = m("SUBTRACT", m("MULTIPLY_ADD", v, zr, zmin), m("MULTIPLY", m("LESS_THAN", v, 1e-4), 1e6))
    # (the surface of water is itself a cover in the map, lifted 0.35 m + a little over it - rain.shelter_map: so only
    # what is more than that above the water shelters it, a bridge, a roof)
    lo2 = m("ADD", lo, 0.45)
    cover = m("MULTIPLY", smooth(lo2, m("ADD", lo2, 0.3), m("SUBTRACT", height, sp.outputs["Z"])), sh_on)
    gate = m("MULTIPLY", m("MULTIPLY", smooth(0.8, 0.95, sn.outputs["Z"]), m("SUBTRACT", 1.0, cover)),
             m("GREATER_THAN", gi.outputs["Rain"], 0.0))
    bump = N.new("ShaderNodeBump"); bump.inputs["Strength"].default_value = 1.0
    L.new(m("MULTIPLY", total, gate), bump.inputs["Height"])
    L.new(m("MULTIPLY", m("MULTIPLY", gi.outputs["Strength"], 0.002), m("DIVIDE", cell, 0.45)), bump.inputs["Distance"])
    L.new(gi.outputs["NormalIn"], bump.inputs["Normal"])
    L.new(bump.outputs[0], go.inputs["Normal"])


def _principled(mat):
    if mat is None or not mat.use_nodes or mat.node_tree is None:
        return None
    return next((n for n in mat.node_tree.nodes if n.type == "BSDF_PRINCIPLED"), None)


def _remove_nodes(mat):
    """The rings out: whatever their normal fed gets back what fed them."""
    nt = mat.node_tree
    grp = nt.nodes.get(NODE)
    src = grp.inputs.get("NormalIn") if grp is not None else None
    out = grp.outputs.get("Normal") if grp is not None else None
    if src is not None and out is not None:
        frm = src.links[0].from_socket if (src.is_linked and src.links[0].from_node.name != NODE + "_geo") else None
        geo = None
        for lk in list(out.links):
            to = lk.to_socket
            nt.links.remove(lk)
            if frm is not None:
                nt.links.new(frm, to)
            elif to.node.type != "BSDF_PRINCIPLED":
                # (fed by the surface's own normal: a node that came after the rings - the ice, when it started to snow
                # during the rain - gets that normal again, not a flat constant: the water lost its waves, 1.65-1.67.4)
                if geo is None:
                    geo = nt.nodes.new("ShaderNodeNewGeometry")
                    geo.name = geo.label = "Normale della superficie"
                    geo.location = (grp.location.x, grp.location.y - 160)
                nt.links.new(geo.outputs["Normal"], to)
    for n in [n for n in nt.nodes if n.name.startswith(NODE)]:
        nt.nodes.remove(n)
    _SIG.pop(mat.name, None)


def strip(mat):
    """The rings out of a material (the editor reads and changes it as it is)."""
    if mat is not None and mat.node_tree is not None and mat.node_tree.nodes.get(NODE) is not None:
        _remove_nodes(mat)


def _apply(mat, s, rain_k):
    nt = mat.node_tree
    p = _principled(mat)
    if p is None:
        return False
    grp = nt.nodes.get(NODE)
    if grp is not None and (grp.node_tree is None or grp.node_tree.name != GROUP or not grp.outputs["Normal"].is_linked):
        _remove_nodes(mat)
        grp = None
    changed = False
    if grp is None:
        g = _group()
        grp = nt.nodes.new("ShaderNodeGroup"); grp.name = NODE; grp.label = "Cerchi pioggia"
        grp.node_tree = g
        grp.location = (p.location.x - 520, p.location.y - 420)
        sock = p.inputs["Normal"]
        if sock.is_linked:
            nt.links.new(sock.links[0].from_socket, grp.inputs["NormalIn"])
        else:
            g = nt.nodes.new("ShaderNodeNewGeometry"); g.name = NODE + "_geo"
            g.location = (grp.location.x - 220, grp.location.y)
            nt.links.new(g.outputs["Normal"], grp.inputs["NormalIn"])
        nt.links.new(grp.outputs["Normal"], sock)
        changed = True
    for name, v in (("Rain", rain_k), ("Amount", s["amount"]), ("Size", s["size"]), ("Strength", s["strength"])):
        if abs(grp.inputs[name].default_value - float(v)) > 1e-6:
            grp.inputs[name].default_value = float(v)
            changed = True
    return changed


def update():
    """Every water material follows the rings (before a path-traced image and in the idle time). True when a
    material changed. Cheap when nothing changed."""
    from . import water, raindrops, rain, ambience
    k = raindrops.intensity()
    changed = False
    any_on = False
    for mat in bpy.data.materials:
        if mat.node_tree is None:
            continue
        grp = mat.node_tree.nodes.get(NODE)
        has = grp is not None
        linked = has and grp.outputs.get("Normal") is not None and grp.outputs["Normal"].is_linked
        on = k > 0 and water.is_water(mat) and not mat.name.startswith("·orig·")   # (not the hidden originals)
        s = settings(mat) if on else None
        on = on and bool(s["on"]) and s["amount"] > 0 and s["strength"] > 0
        if not on:
            if has:
                _remove_nodes(mat)
                changed = True
            continue
        any_on = True
        sig = (round(k, 4), json.dumps(s, sort_keys=True), True)
        if _SIG.get(mat.name) == sig and linked:
            continue
        try:
            changed = _apply(mat, s, k) or changed
            _SIG[mat.name] = (round(k, 4), json.dumps(s, sort_keys=True), True)
        except Exception as exc:
            log(f"SIMPLER_RAIN rings {mat.name}: {exc}")
    g = bpy.data.node_groups.get(GROUP)
    if any_on and g is not None:
        changed = rain._shelter_to_group(g, rain.settings(ambience.state())) or changed
        if changed:
            g.update_tag()
    return changed


def view_info():
    """For the real-time view (rain/info): the waters with rings, by material name."""
    from . import water, raindrops
    k = raindrops.intensity()
    if k <= 0:
        return []
    out = []
    for mat in bpy.data.materials:
        if not water.is_water(mat) or mat.name.startswith("·orig·"):
            continue
        s = settings(mat)
        if s["on"] and s["amount"] > 0 and s["strength"] > 0:
            out.append({"name": mat.name, "rain": k, "amount": s["amount"], "size": s["size"], "strength": s["strength"]})
    return out


def after_open():
    _SIG.clear()
