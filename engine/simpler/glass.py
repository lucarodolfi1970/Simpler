"""Light through glass and water.

Cycles does not let the direct light of a lamp (above all the sun, a point of light) pass through a refracting
surface: a shadow ray that meets glass or water stops. The light can only arrive as a caustic, a path that has to
find the light by chance after the refraction: with the sun it practically never happens. So whatever is behind or
under a glass or a water surface stays dark - the bottom of a pond is black, a glass table casts a black shadow -
unless other lights reach it from elsewhere (that is why the same water can look right in an interior).

The usual fix of photorealistic renderers, and the one used here: for shadow rays only, glass and water are a
Transparent BSDF tinted with their colour (Light Path "Is Shadow Ray"). Camera, reflection and refraction rays still
see the real glass. The light then passes, without the focusing of real caustics, at almost no cost (a shadow ray
crosses the surface instead of stopping there). With the "Caustiche" switch on (MNEE, real shadow caustics) the
shortcut is turned off, so the light is not counted twice.

ensure() is called before every path-traced image: it wraps the materials that need it (once; a material rebuilt by
the editor is wrapped again) through one shared node group, whose switch follows the caustics setting. It also tells
whether the scene has glass or water at all (PRESENT): the render then never lets the "total bounces" limit stop the
rays that cross them (see render._apply_common).
"""
import bpy

PRESENT = {"glass": False}
GROUP = "Simpler Glass Shadow"
TAG = "simpler_glass_shadow"


CASTER_PROP = "simpler_caster"      # 1 on the pieces that draw sharp caustics (render.refresh_caustics)


def _group():
    g = bpy.data.node_groups.get(GROUP)
    if g is not None:
        if g.nodes.get("caster") is None:
            _add_caster(g)                         # (group of an older version: per-piece switch added)
        return g
    g = bpy.data.node_groups.new(GROUP, "ShaderNodeTree")
    g.interface.new_socket("Shader", in_out="INPUT", socket_type="NodeSocketShader")
    tint = g.interface.new_socket("Tint", in_out="INPUT", socket_type="NodeSocketColor")
    tint.default_value = (1.0, 1.0, 1.0, 1.0)
    w = g.interface.new_socket("Weight", in_out="INPUT", socket_type="NodeSocketFloat")
    w.default_value = 1.0
    g.interface.new_socket("Shader", in_out="OUTPUT", socket_type="NodeSocketShader")
    N, L = g.nodes, g.links
    gi = N.new("NodeGroupInput")
    go = N.new("NodeGroupOutput")
    lp = N.new("ShaderNodeLightPath")
    on = N.new("ShaderNodeValue"); on.name = "enabled"; on.outputs[0].default_value = 1.0
    m1 = N.new("ShaderNodeMath"); m1.operation = "MULTIPLY"
    L.new(lp.outputs["Is Shadow Ray"], m1.inputs[0]); L.new(on.outputs[0], m1.inputs[1])
    m2 = N.new("ShaderNodeMath"); m2.operation = "MULTIPLY"
    L.new(m1.outputs[0], m2.inputs[0]); L.new(gi.outputs["Weight"], m2.inputs[1])
    tr = N.new("ShaderNodeBsdfTransparent")
    L.new(gi.outputs["Tint"], tr.inputs["Color"])
    mix = N.new("ShaderNodeMixShader")
    L.new(m2.outputs[0], mix.inputs["Fac"]); L.new(gi.outputs[0], mix.inputs[1]); L.new(tr.outputs[0], mix.inputs[2])
    L.new(mix.outputs[0], go.inputs[0])
    m2.name = "weight"
    _add_caster(g)
    return g


def _add_caster(g):
    """The shortcut is off on the pieces that draw sharp caustics (their light arrives as a real caustic): an object
    property read by the shader, so a window and a gem with the same glass behave each as they should."""
    N, L = g.nodes, g.links
    m2 = g.nodes.get("weight") or next(n for n in g.nodes if n.type == "MATH" and n.outputs[0].is_linked
                                        and any(l.to_node.type == "MIX_SHADER" for l in n.outputs[0].links))
    at = N.new("ShaderNodeAttribute"); at.name = "caster"
    at.attribute_type = "OBJECT"; at.attribute_name = CASTER_PROP
    inv = N.new("ShaderNodeMath"); inv.operation = "SUBTRACT"; inv.inputs[0].default_value = 1.0; inv.use_clamp = True
    L.new(at.outputs["Fac"], inv.inputs[1])
    m3 = N.new("ShaderNodeMath"); m3.operation = "MULTIPLY"
    mix_links = [l for l in m2.outputs[0].links]
    L.new(m2.outputs[0], m3.inputs[0]); L.new(inv.outputs[0], m3.inputs[1])
    for l in mix_links:
        L.new(m3.outputs[0], l.to_socket)
    g.update_tag()


def set_enabled(enabled):
    g = _group()
    node = g.nodes.get("enabled")
    if node is not None and abs(node.outputs[0].default_value - (1.0 if enabled else 0.0)) > 1e-6:
        node.outputs[0].default_value = 1.0 if enabled else 0.0
        g.update_tag()


def _output(mat):
    outs = [n for n in mat.node_tree.nodes if n.type == "OUTPUT_MATERIAL"]
    for n in outs:
        if n.is_active_output:
            return n
    return outs[0] if outs else None


def _transmission(mat, shader_node):
    """(weight, tint socket or colour) of a glass-like surface, or None."""
    from . import matedit
    mp = matedit.params_of(mat)
    if mp is not None:
        w = float(mp["transmission"]["weight"])
        if w <= 0.05:
            return None
        # the colour the glass really has: the Base Color input of its BSDF, with the texture of the colour channel
        # (a stained glass window throws its colours on the floor, not white light); the plain tint only without one
        bsdf = next((x for x in mat.node_tree.nodes if x.type == "BSDF_PRINCIPLED"), None)
        bc = bsdf.inputs.get("Base Color") if bsdf is not None else None
        return (w, bc if bc is not None else tuple(mp["color"]["tint"][:3]))
    n = shader_node
    if n is None:
        return None
    if n.type == "BSDF_PRINCIPLED":
        tw = n.inputs.get("Transmission Weight") or n.inputs.get("Transmission")
        if tw is None or tw.is_linked or tw.default_value <= 0.05:
            return None
        bc = n.inputs.get("Base Color")
        return (float(tw.default_value), bc)
    if n.type in ("BSDF_GLASS", "BSDF_REFRACTION"):
        return (1.0, n.inputs.get("Color"))
    if n.type == "MIX_SHADER":                         # e.g. dispersive glass of the editor: look inside
        for s in (n.inputs[1], n.inputs[2]):
            if s.is_linked:
                r = _transmission(mat, s.links[0].from_node)
                if r is not None:
                    return r
    return None


def _wrap(mat):
    out = _output(mat)
    if out is None or not out.inputs["Surface"].is_linked:
        return False
    link = out.inputs["Surface"].links[0]
    src = link.from_node
    nt = mat.node_tree
    if src.type == "GROUP" and src.node_tree is not None and src.node_tree.name == GROUP:
        # already wrapped (glass): the colour of the shadow follows the glass as it is now (a texture added later)
        inner = src.inputs[0].links[0].from_node if src.inputs[0].is_linked else None
        info = _transmission(mat, inner) if inner is not None else None
        if info is not None:
            _set_tint(nt, src, info[1])
        return None
    info = _transmission(mat, src)
    if info is None:
        return False
    weight, tint = info
    g = nt.nodes.new("ShaderNodeGroup")
    g.node_tree = _group()
    g.name = TAG
    g.label = "Glass shadow"
    g.location = (out.location.x - 200, out.location.y - 180)
    nt.links.new(link.from_socket, g.inputs[0])
    _set_tint(nt, g, tint)
    g.inputs[2].default_value = max(0.0, min(1.0, weight))
    g["simpler_weight"] = float(max(0.0, min(1.0, weight)))
    nt.links.new(g.outputs[0], out.inputs["Surface"])
    return True


def _set_tint(nt, g, tint):
    """The colour of the light that passes (Tint of the group): the same socket as the glass colour - a texture
    linked there colours the light - or a plain colour."""
    sock = g.inputs[1]
    if hasattr(tint, "is_linked"):
        if tint.is_linked:
            src = tint.links[0].from_socket
            if not (sock.is_linked and sock.links[0].from_socket == src):
                nt.links.new(src, sock)
            return
        col = tuple(tint.default_value)
    else:
        col = (*tint[:3], 1.0)
    for l in list(sock.links):
        nt.links.remove(l)
    if any(abs(a - b) > 1e-6 for a, b in zip(sock.default_value, col)):
        sock.default_value = col


def ensure(caustic_mats=()):
    """Wraps the glass and water materials of the scene that are not wrapped yet. Cheap when nothing changed.
    The shortcut is off only on the pieces that draw sharp caustics now (object property simpler_caster, set by
    render.refresh_caustics): their light reaches through them as a real caustic, not twice; every other glass keeps
    it - a window lets the sun into a room even with the caustics of the pool on.
    Returns how many were wrapped now; PRESENT["glass"] says whether the scene has glass or water at all."""
    if caustic_mats is True or caustic_mats is False:     # (old calls: a switch for every glass)
        caustic_mats = ()
    caustic_mats = set(caustic_mats)
    set_enabled(True)
    seen, n, found = set(), 0, False
    for ob in bpy.context.scene.objects:
        if ob.type not in ("MESH", "CURVE", "FONT", "META", "SURFACE"):
            continue
        for sl in ob.material_slots:
            mat = sl.material
            if mat is None or mat in seen or not mat.use_nodes or mat.node_tree is None:
                continue
            seen.add(mat)
            try:
                r = _wrap(mat)
                if r is None:
                    found = True
                elif r:
                    n += 1
                    found = True
                if r is not False:
                    node = mat.node_tree.nodes.get(TAG)
                    if node is not None and "simpler_weight" in node and abs(node.inputs[2].default_value - node["simpler_weight"]) > 1e-6:
                        node.inputs[2].default_value = node["simpler_weight"]      # (1.13.0 set it per material)
            except Exception as exc:                   # an unusual node graph: left as it is
                print(f"SIMPLER_GLASS skip {mat.name}: {exc}", flush=True)
    PRESENT["glass"] = found
    return n


# ---------------------------------------------------------------- the colour of the light through a glass (1.75.0)

_FILTERS = {}
FILTER_PX = 256           # the picture of a stained glass, reduced to this for the light that crosses it


def light_filter(mat):
    """What a glass does to the light of the sun that crosses it, for refcaustics (the light reflected by the water:
    before 1.75.0 every glass stopped it, so through stained glass windows only white light reached the water):
    None (opaque) or (weight, colour (r, g, b), picture: numpy (h, w, 3) or None). Kept until the material changes."""
    if mat is None or not mat.use_nodes or mat.node_tree is None:
        return None
    key = (mat.name, mat.get("simpler_rev", 0), len(mat.node_tree.nodes), len(mat.node_tree.links))
    if key in _FILTERS:
        return _FILTERS[key]
    out = _output(mat)
    res = None
    if out is not None and out.inputs["Surface"].is_linked:
        src = out.inputs["Surface"].links[0].from_node
        if src.type == "GROUP" and src.node_tree is not None and src.node_tree.name == GROUP:
            src = src.inputs[0].links[0].from_node if src.inputs[0].is_linked else None
        info = _transmission(mat, src) if src is not None else None
        if info is not None:
            w, tint = info
            col, pic = (1.0, 1.0, 1.0), None
            if hasattr(tint, "is_linked"):
                if tint.is_linked:
                    n = _image_upstream(tint.links[0].from_node)
                    if n is not None:
                        pic = _small_pixels(n.image)
                else:
                    col = tuple(tint.default_value[:3])
            else:
                col = tuple(tint[:3])
            res = (float(w), col, pic)
    _FILTERS[key] = res
    return res


def _image_upstream(n, depth=0):
    """The picture that gives a colour (through a few nodes: a mix, a hue, a gamma...), or None."""
    if n is None or depth > 5:
        return None
    if n.type == "TEX_IMAGE":
        return n if n.image is not None else None
    for i in n.inputs:
        if i.is_linked and i.type in ("RGBA", "VALUE", "VECTOR") and i.name not in ("Vector", "Normal"):
            r = _image_upstream(i.links[0].from_node, depth + 1)
            if r is not None:
                return r
    return None


def _small_pixels(im):
    import numpy as np
    try:
        w, h = im.size
        if w <= 0 or h <= 0:
            return None
        px = np.empty(w * h * im.channels, np.float32)
        im.pixels.foreach_get(px)
    except Exception:          # (a picture that cannot be read: plain glass)
        return None
    px = px.reshape(h, w, im.channels)[:, :, :3]
    sy, sx = max(1, h // FILTER_PX), max(1, w // FILTER_PX)
    px = np.ascontiguousarray(px[::sy, ::sx])
    if im.colorspace_settings.name in ("sRGB", "") and not im.is_float:
        px = np.where(px <= 0.04045, px / 12.92, ((px + 0.055) / 1.055) ** 2.4)     # (the light: linear)
    return px
