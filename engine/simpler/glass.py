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

(19/11) The light that passes loses at every surface of the glass the share the glass reflects (Fresnel, with the
index of the glass): about 4% where the light meets the surface square on, much more where it grazes it. So a glass
under a spot or the sun has a light shadow, darker along its outline and where it is thick - before it had none at all
(Luca, a cake stand and glasses under spots, caustics «Normali»). Water keeps the plain shortcut (IOR input 1: no
loss), its look was tuned with it.

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
        if g.nodes.get("fresnel") is None:
            _add_fresnel(g)                        # (group of before 19/11: no loss at the surfaces)
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
    _add_fresnel(g)
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


IOR_SOCKET = "IOR"
IOR_DEFAULT = 1.5


def _add_fresnel(g):
    """The light that goes through loses at each surface the share the glass reflects: Transparent colour = tint x
    (1 - Fresnel). An IOR of 1 (water) loses nothing. Materials wrapped before get the default index at once (glass)."""
    N, L = g.nodes, g.links
    if g.interface.items_tree.get(IOR_SOCKET) is None:
        s = g.interface.new_socket(IOR_SOCKET, in_out="INPUT", socket_type="NodeSocketFloat")
        s.default_value = IOR_DEFAULT
        s.min_value = 1.0
    gi = next(n for n in N if n.type == "GROUP_INPUT")
    tr = next(n for n in N if n.type == "BSDF_TRANSPARENT")
    fr = N.new("ShaderNodeFresnel"); fr.name = "fresnel"
    # the light is not bent here (it goes straight through): on the way out it meets the surface at the same angle
    # it came in, so the loss is the same as on the way in. The Fresnel node takes the index inverted on back faces
    # (light leaving the glass), and beyond 42 degrees it would see total reflection: a black shadow (tried). So on
    # back faces it gets 1/IOR, which it inverts again.
    geo = N.new("ShaderNodeNewGeometry")
    rec = N.new("ShaderNodeMath"); rec.operation = "DIVIDE"; rec.inputs[0].default_value = 1.0
    L.new(gi.outputs[IOR_SOCKET], rec.inputs[1])
    dif = N.new("ShaderNodeMath"); dif.operation = "SUBTRACT"
    L.new(rec.outputs[0], dif.inputs[0]); L.new(gi.outputs[IOR_SOCKET], dif.inputs[1])
    eta = N.new("ShaderNodeMath"); eta.operation = "MULTIPLY_ADD"
    L.new(geo.outputs["Backfacing"], eta.inputs[0]); L.new(dif.outputs[0], eta.inputs[1])
    L.new(gi.outputs[IOR_SOCKET], eta.inputs[2])
    L.new(eta.outputs[0], fr.inputs["IOR"])
    inv = N.new("ShaderNodeMath"); inv.operation = "SUBTRACT"; inv.inputs[0].default_value = 1.0; inv.use_clamp = True
    L.new(fr.outputs[0], inv.inputs[1])
    sc = N.new("ShaderNodeVectorMath"); sc.operation = "SCALE"; sc.name = "fresnel_scale"
    for l in list(tr.inputs["Color"].links):
        L.remove(l)
    L.new(gi.outputs["Tint"], sc.inputs[0])
    L.new(inv.outputs[0], sc.inputs["Scale"])
    L.new(sc.outputs["Vector"], tr.inputs["Color"])
    g.update_tag()


def _ior(mat, inner=None):
    """Index of refraction of a glass material (editor parameters, else the BSDF), 1.5 when unknown."""
    from . import matedit
    v = None
    mp = matedit.params_of(mat)
    if mp is not None:
        v = mp["transmission"].get("ior")
    if v is None:
        for n in ([inner] if inner is not None else []) + list(mat.node_tree.nodes):
            if n is not None and n.type in ("BSDF_PRINCIPLED", "BSDF_GLASS", "BSDF_REFRACTION"):
                s = n.inputs.get("IOR")
                if s is not None and not s.is_linked:
                    v = s.default_value
                    break
    try:
        return max(1.0, min(3.0, float(v)))
    except (TypeError, ValueError):
        return IOR_DEFAULT


def _set_ior(node, value):
    s = node.inputs.get(IOR_SOCKET)
    if s is not None and abs(s.default_value - value) > 1e-4:
        s.default_value = value


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
    from . import water
    waters = set()                              # (water keeps the plain shortcut: no Fresnel loss)
    for ob in bpy.context.scene.objects:
        if ob.get("simpler_ocean") or ob.get(water.BODY_KEY):
            waters.update(sl.material for sl in ob.material_slots if sl.material is not None)
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
                    if node is not None:
                        wet = mat in waters or water.is_water(mat)
                        inner = node.inputs[0].links[0].from_node if node.inputs[0].is_linked else None
                        _set_ior(node, 1.0 if wet else _ior(mat, inner))
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
