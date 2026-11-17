"""Materials, images and node groups brought by a model that the scene already has, identical: the copies go and
the model uses what is there.

Every insertion of a library model loads its materials again (body.001, glass.001...): more memory, the same
textures twice, and the real-time view had to prepare each copy of the model from scratch (its prototype depends on
the names of its materials). Only what is really identical is shared - same node graph with all its values and
links, same node groups, same settings of the material, same images (the same file with the same colour space, or the
same embedded bytes) - never two materials that only have the same name. A material changed in the scene ("only for
this object") stays a material of its own, and so does the one coming in.
"""
import hashlib
import json
import os

import bpy

# node properties that do not change the look
_SKIP = {"rna_type", "name", "label", "location", "location_absolute", "width", "height", "dimensions", "select",
         "show_options", "show_preview", "hide", "mute", "show_texture", "color", "use_custom_color", "parent",
         "bl_idname", "bl_label", "bl_description", "bl_icon", "bl_static_type", "bl_width_default",
         "bl_width_min", "bl_width_max", "bl_height_default", "bl_height_min", "bl_height_max", "type",
         "inputs", "outputs", "internal_links", "is_active_output", "warning_propagation", "color_tag"}
# custom properties of a material that are bookkeeping, not look
_SKIP_PROPS = {"simpler_lib_rev", "simpler_lib_dirty", "simpler_graded_ok", "simpler_lib_draft"}


def _num(v):
    if isinstance(v, float):
        return round(v, 6)
    if isinstance(v, (str, bytes, int, bool)) or v is None:
        return v
    try:
        return [_num(x) for x in v]
    except TypeError:
        return v


def image_key(im):
    """What makes two images the same picture."""
    if im is None:
        return None
    base = (im.source, im.colorspace_settings.name, im.alpha_mode, bool(getattr(im, "use_half_precision", False)))
    if im.packed_file is not None:
        data = im.packed_file.data
        return base + ("packed", len(data), hashlib.sha1(bytes(data)).hexdigest())
    if im.source in ("FILE", "TILED", "SEQUENCE", "MOVIE"):
        path = bpy.path.abspath(im.filepath, library=im.library)
        return base + ("file", os.path.normcase(os.path.normpath(path)))
    return base + ("other", im.name, tuple(im.size))         # generated pictures: only themselves


def _value(v, ctx):
    if isinstance(v, bpy.types.Image):
        return ("IMAGE", image_key(v))
    if isinstance(v, bpy.types.NodeTree):
        return ("TREE", tree_key(v, ctx))
    if isinstance(v, bpy.types.ID):
        return ("ID", type(v).__name__, ctx["names"].get(v.name, v.name))
    if isinstance(v, (int, float, str, bool)) or v is None:
        return _num(v)
    try:
        return _num(tuple(v))
    except TypeError:
        return repr(v)


def _struct(s, ctx, depth=0):
    """The settings of a node (or of a struct inside it: colour ramp, curves...)."""
    out = []
    for p in s.bl_rna.properties:
        k = p.identifier
        if k in _SKIP:
            continue
        try:
            v = getattr(s, k)
        except AttributeError:
            continue
        if p.type == "POINTER":
            if isinstance(v, bpy.types.ID) or v is None:
                out.append((k, _value(v, ctx)))
            elif depth < 3:
                out.append((k, _struct(v, ctx, depth + 1)))
        elif p.type == "COLLECTION":
            if depth < 3 and k in ("elements", "curves", "points", "mapping_items", "enum_items", "format_items"):
                out.append((k, [_struct(e, ctx, depth + 1) for e in v]))
        else:
            out.append((k, _value(v, ctx)))
    return out


def tree_key(nt, ctx):
    """A node graph with every value and link (groups by their own content)."""
    if nt is None:
        return None
    memo = ctx["trees"]
    if nt.as_pointer() in memo:
        return memo[nt.as_pointer()]
    memo[nt.as_pointer()] = ("CYCLE", nt.name)
    nodes = []
    for n in sorted(nt.nodes, key=lambda n: n.name):
        ins = []
        for s in n.inputs:
            dv = getattr(s, "default_value", None)
            ins.append((s.identifier, s.enabled, _value(dv, ctx) if dv is not None else None))
        nodes.append((n.name, n.bl_idname, _struct(n, ctx), ins))
    links = sorted((l.from_node.name, l.from_socket.identifier, l.to_node.name, l.to_socket.identifier, l.is_muted)
                   for l in nt.links)
    iface = []
    for it in getattr(nt, "interface", None).items_tree if getattr(nt, "interface", None) else []:
        iface.append((getattr(it, "item_type", ""), getattr(it, "in_out", ""), getattr(it, "socket_type", ""),
                      getattr(it, "name", ""), _value(getattr(it, "default_value", None), ctx)))
    key = hashlib.sha1(repr((nt.bl_idname, nodes, links, iface)).encode("utf-8", "replace")).hexdigest()
    memo[nt.as_pointer()] = key
    return key


def material_key(m, ctx):
    props = []
    for k in sorted(m.keys()):
        if k in _SKIP_PROPS:
            continue
        v = m[k]
        if k == "simpler_mat_backup":          # the hidden original: compared by what it is, not by its name
            b = bpy.data.materials.get(ctx.get("renamed", {}).get(str(v), str(v)))
            v = ("BACKUP", material_key(b, ctx) if b is not None and b is not m else None)
        elif hasattr(v, "to_dict"):
            v = json.dumps(v.to_dict(), sort_keys=True, default=str)
        elif hasattr(v, "to_list"):
            v = repr(v.to_list())
        props.append((k, _num(v) if not isinstance(v, str) else v))
    settings = []
    for k in ("blend_method", "surface_render_method", "use_backface_culling", "use_backface_culling_shadow",
              "displacement_method", "use_transparency_overlap", "use_screen_refraction", "use_nodes",
              "diffuse_color", "metallic", "roughness", "specular_intensity", "pass_index", "line_priority"):
        if hasattr(m, k):
            settings.append((k, _value(getattr(m, k), ctx)))
    tree = tree_key(m.node_tree, ctx) if m.use_nodes and m.node_tree is not None else None
    return hashlib.sha1(repr((props, settings, tree)).encode("utf-8", "replace")).hexdigest()


def _image_cheap(im):
    """What two equal images surely have in common, without reading them (see image_key)."""
    base = (im.source, im.colorspace_settings.name, im.alpha_mode)
    if im.packed_file is not None:
        return base + ("packed", im.packed_file.size)
    if im.source in ("FILE", "TILED", "SEQUENCE", "MOVIE"):
        return base + ("file", os.path.normcase(os.path.normpath(bpy.path.abspath(im.filepath, library=im.library))))
    return base + ("other",)


def _tree_cheap(nt):
    return (nt.bl_idname, len(nt.nodes), len(nt.links)) if nt is not None else None


def _mat_cheap(m):
    # (1.75.28) and the pictures it uses: the materials of Simpler all have the same nodes, only their images differ
    # (after the images were shared above, an equal material uses the very same images, with the same names)
    nt = m.node_tree if m.use_nodes else None
    ims = tuple(sorted(n.image.name for n in nt.nodes if n.type == "TEX_IMAGE" and n.image is not None)) if nt is not None else ()
    return (bool(m.use_nodes), _tree_cheap(nt), "simpler_mat_backup" in m, ims)


def share_identical(new_materials, new_images, new_groups):
    """After loading a model: its images, node groups and materials that equal ones already in the scene are
    replaced by those. Returns how many of each were shared."""
    done = {"images": 0, "groups": 0, "materials": 0}
    new_images = [i for i in new_images if i is not None and i.name in bpy.data.images]
    new_groups = [g for g in new_groups if g is not None and g.name in bpy.data.node_groups]
    new_materials = [m for m in new_materials if m is not None and m.name in bpy.data.materials]
    # images first: then the materials that use them compare equal
    # (1.75.27) only the old ones that could be equal get their full key (a packed picture is read whole to be
    # compared): a big scene compared hundreds of images, materials and node graphs at every model put in it
    olds = {}
    newset = {i.as_pointer() for i in new_images}
    cheap_new = {_image_cheap(i) for i in new_images}
    for im in bpy.data.images:
        if im.as_pointer() not in newset and im.users and _image_cheap(im) in cheap_new:
            olds.setdefault(image_key(im), im)
    for im in new_images:
        old = olds.get(image_key(im))
        if old is not None and old != im:
            im.user_remap(old)
            bpy.data.images.remove(im)
            done["images"] += 1
    ctx = {"trees": {}, "names": {}}
    # node groups (Simpler Glass Shadow, decal trees...)
    newg = {g.as_pointer() for g in new_groups}
    oldg = {}
    cheap_g = {_tree_cheap(g) for g in new_groups}
    for g in bpy.data.node_groups:
        if g.as_pointer() not in newg and g.users and _tree_cheap(g) in cheap_g:
            oldg.setdefault(tree_key(g, ctx), g)
    for g in new_groups:
        old = oldg.get(tree_key(g, ctx))
        if old is not None and old != g:
            g.user_remap(old)
            bpy.data.node_groups.remove(g)
            done["groups"] += 1
    # the image names inside the channels of Simpler materials follow the images really used (matedit._heal_images):
    # after the images above were shared, or renamed by Blender on loading
    # (only the materials just loaded: the others did not lose or change images here)
    from . import matedit
    for m in new_materials:
        if m.name in bpy.data.materials and m.get(matedit.PARAMS_KEY):
            matedit.params_of(m)
    # materials: the hidden originals (·orig·) before the materials that point to them
    ctx = {"trees": {}, "names": {}, "renamed": {}}
    newm = {m.as_pointer() for m in new_materials}
    oldm = {}
    cheap_m = {_mat_cheap(m) for m in new_materials if m.name in bpy.data.materials}
    for m in bpy.data.materials:
        if m.as_pointer() not in newm and (m.users or m.use_fake_user) and _mat_cheap(m) in cheap_m:
            oldm.setdefault(material_key(m, ctx), m)
    for m in sorted(new_materials, key=lambda m: 0 if m.name.startswith("·orig·") else 1):
        key = material_key(m, ctx)
        old = oldm.get(key)
        if old is not None and old != m:
            ctx["renamed"][m.name] = old.name
            m.user_remap(old)
            bpy.data.materials.remove(m)
            done["materials"] += 1
            ctx["trees"].clear()
    # the materials that stay point to the shared hidden original, if theirs went
    for m in new_materials:
        try:
            v = m.get("simpler_mat_backup")
        except ReferenceError:
            continue
        if v is not None and str(v) in ctx["renamed"]:
            m["simpler_mat_backup"] = ctx["renamed"][str(v)]
    return done
