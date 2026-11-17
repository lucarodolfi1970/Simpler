"""FBX 6.x (2005-2010 era) reader.

Blender's FBX importer reads only FBX 7.1 and later. Many tools still write the old 6.1 layout (Tree It,
old 3ds Max/Maya presets, many free model sites): meshes, UVs, normals, colours, materials, textures and the
model hierarchy are read here and built straight into Blender data. Animation, skinning, lights and cameras
of these files are ignored (Simpler makes still images).

`import_fbx(path)` is the single entry point used by the scene importer and by the library importer: it picks
the right road (binary 7.x -> Blender, text 7.x -> convert + Blender, 6.x -> this reader) and turns errors into
sentences a person can act on.
"""
import math
import os
import re
import struct
import tempfile

import bpy
from mathutils import Euler, Matrix, Vector

from . import fbx_ascii
from .core import ApiError
from .i18n import tr
from . import tempdirs


# ---------------------------------------------------------------- version and the common entry point

def version(path):
    """FBX version number (6100, 7400, ...) or 0 when unknown."""
    with open(path, "rb") as f:
        head = f.read(4096)
    if head.startswith(b"Kaydara FBX Binary"):
        return struct.unpack("<I", head[23:27])[0] if len(head) >= 27 else 0
    m = re.search(rb"FBXVersion:\s*(\d+)", head) or re.search(rb";\s*FBX\s+(\d+)\.(\d+)", head)
    if not m:
        return 0
    if len(m.groups()) == 2:
        return int(m.group(1)) * 1000 + int(m.group(2)) * 100
    return int(m.group(1))


def import_fbx(path, progress_update=None):
    """Import an FBX file of any version into the current scene. Raises ApiError with a readable message."""
    ver = version(path)
    if 0 < ver < 7000:
        if progress_update:
            progress_update(tr("Lettura FBX {0} (formato precedente al 2011)", "%d.%d" % (ver // 1000, ver % 1000 // 100)))
        try:
            load(path)
        except ApiError:
            raise
        except Exception as exc:
            raise ApiError(tr("Il file FBX {0} (versione {1}) non è leggibile: {2}", os.path.basename(path),
                              "%d.%d" % (ver // 1000, ver % 1000 // 100), _short(exc))) from exc
        return
    read = path
    if fbx_ascii.is_ascii_fbx(path):
        if progress_update:
            progress_update(tr("Conversione FBX di testo in binario"))
        read = os.path.join(tempdirs.make("simpler_fbx_"), os.path.basename(path))
        fbx_ascii.convert(path, read)
        if progress_update:
            progress_update(tr("Lettura del file {0}", os.path.basename(path)))
    try:
        result = bpy.ops.import_scene.fbx(filepath=read, use_custom_normals=True, use_image_search=True)
    except Exception as exc:
        raise ApiError(tr("Blender non riesce a leggere {0}: {1}. Prova a riesportarlo come FBX binario 2014 o successivo, "
                          "oppure come glTF/OBJ.", os.path.basename(path), _short(exc))) from exc
    if "FINISHED" not in result:
        raise ApiError(tr("Import non riuscito"))


def _short(exc):
    """Last meaningful line of an exception (Blender wraps Python tracebacks into RuntimeError text)."""
    lines = [l.strip() for l in str(exc).replace("Error: ", "").splitlines() if l.strip()]
    lines = [l for l in lines if not l.startswith(("Traceback", "File ", "^"))]
    return lines[-1] if lines else exc.__class__.__name__


# ---------------------------------------------------------------- a version-neutral node tree

class N:
    __slots__ = ("name", "vals", "kids")

    def __init__(self, name, vals, kids):
        self.name, self.vals, self.kids = name, vals, kids

    def first(self, name):
        for k in self.kids:
            if k.name == name:
                return k
        return None

    def all(self, name):
        return [k for k in self.kids if k.name == name]

    def value(self, name, default=None):
        k = self.first(name)
        return k.vals[0] if k is not None and k.vals else default

    def numbers(self, name):
        k = self.first(name)
        if k is None:
            return []
        if len(k.vals) == 1 and isinstance(k.vals[0], (list, tuple)):
            return list(k.vals[0])
        return [v for v in k.vals if isinstance(v, (int, float))]


def _from_ascii(node):
    vals = []
    if node.array is not None:
        vals = [float(v) for v in node.values]
    else:
        for kind, raw in node.values:
            if kind == "string":
                vals.append(raw[1:-1].replace("&quot;", '"'))
            elif kind == "number":
                vals.append(int(raw) if re.fullmatch(r"[-+]?\d+", raw) else float(raw))
            else:
                vals.append(raw)
    return N(node.name, vals, [_from_ascii(c) for c in node.children])


def _from_bin(elem):
    vals = []
    for v in elem.props:
        if isinstance(v, bytes):
            if b"\x00\x01" in v:          # binary "Name\x00\x01Class" -> "Class::Name" as in text files
                name, cls = v.split(b"\x00\x01", 1)
                v = cls + b"::" + name
            vals.append(v.decode("utf-8", "replace"))
        elif hasattr(v, "tolist"):
            vals.append(v.tolist())
        elif isinstance(v, (list, tuple)) or type(v).__name__ == "array":
            vals.append(list(v))
        else:
            vals.append(v)
    return N(elem.id.decode("utf-8", "replace"), vals, [_from_bin(e) for e in elem.elems])


def read_tree(path):
    if fbx_ascii.is_ascii_fbx(path):
        with open(path, "r", encoding="utf-8", errors="replace") as f:
            root = fbx_ascii.parse(f.read())
        return N("", [], [_from_ascii(c) for c in root.children])
    from io_scene_fbx import parse_fbx
    root, _ver = parse_fbx.parse(path)
    return N("", [], [_from_bin(e) for e in root.elems])


# ---------------------------------------------------------------- building Blender data

def _props(node):
    """Properties60 { Property: "Name", "Type", "Flags", values... } -> {name: values}"""
    out = {}
    p = node.first("Properties60") or node.first("Properties70")
    if p is None:
        return out
    for prop in p.kids:
        if len(prop.vals) >= 3:
            vals = prop.vals[3:] if prop.name == "Property" else prop.vals[4:]
            out[prop.vals[0]] = vals
    return out


def _axis_matrix(settings):
    """FBX space -> Blender space (Z up, metres)."""
    up = int(settings.get("UpAxis", [1])[0]) if settings.get("UpAxis") else 1
    sign = int(settings.get("UpAxisSign", [1])[0]) if settings.get("UpAxisSign") else 1
    unit = float(settings.get("UnitScaleFactor", [1.0])[0]) if settings.get("UnitScaleFactor") else 1.0
    if up == 2:
        rot = Matrix.Identity(4)
    elif up == 0:
        rot = Matrix.Rotation(math.radians(90), 4, "Y")
    else:
        rot = Matrix.Rotation(math.radians(90), 4, "X")      # Y up -> Z up: (x, y, z) -> (x, -z, y)
    if sign < 0:
        rot = Matrix.Rotation(math.pi, 4, "X") @ rot
    return Matrix.Scale(unit * 0.01, 4) @ rot


def _local_matrix(props):
    def vec(name, default):
        v = props.get(name)
        return [float(x) for x in v[:3]] if v and len(v) >= 3 else default
    t = vec("Lcl Translation", [0, 0, 0])
    r = vec("Lcl Rotation", [0, 0, 0])
    s = vec("Lcl Scaling", [1, 1, 1])
    pre = vec("PreRotation", [0, 0, 0])
    post = vec("PostRotation", [0, 0, 0])
    rad = lambda v: Euler([math.radians(a) for a in v], "XYZ").to_matrix().to_4x4()
    sm = Matrix.Diagonal((s[0], s[1], s[2], 1.0))
    return Matrix.Translation(t) @ rad(pre) @ rad(r) @ rad(post).inverted() @ sm


def _per_loop(layer, data_key, index_key, width, loop_verts, poly_of_loop):
    """Expand an FBX layer element to one value (tuple of `width`) per loop. None if not usable."""
    data = layer.numbers(data_key)
    if not data:
        return None
    mapping = str(layer.value("MappingInformationType", "ByPolygonVertex"))
    ref = str(layer.value("ReferenceInformationType", "Direct"))
    items = [tuple(data[i:i + width]) for i in range(0, len(data) - width + 1, width)]
    if ref in ("IndexToDirect", "Index"):
        idx = [int(i) for i in layer.numbers(index_key)]
        if idx:
            items = [items[i] if 0 <= i < len(items) else items[0] for i in idx]
    if mapping in ("ByVertice", "ByVertex"):
        src = loop_verts
    elif mapping == "ByPolygonVertex":
        src = range(len(loop_verts))
    elif mapping == "ByPolygon":
        src = poly_of_loop
    else:   # AllSame
        return [items[0]] * len(loop_verts) if items else None
    n = len(items)
    if n == 0:
        return None
    return [items[i] if i < n else items[-1] for i in src]


def _mesh(name, model, conv):
    verts = model.numbers("Vertices")
    pvi = [int(i) for i in model.numbers("PolygonVertexIndex")]
    if not verts or not pvi:
        return None
    rot = conv.to_3x3().normalized()
    co = []
    for i in range(0, len(verts) - 2, 3):
        v = conv @ Vector((verts[i], verts[i + 1], verts[i + 2]))
        co.extend(v)
    nverts = len(co) // 3
    loop_verts, starts, poly_of_loop = [], [], []
    start = 0
    for i, v in enumerate(pvi):
        end = v < 0
        vi = ~v if end else v
        loop_verts.append(vi if vi < nverts else 0)
        poly_of_loop.append(len(starts))
        if end:
            starts.append(start)
            start = i + 1
    # trailing polygon without the closing negative index
    if start < len(pvi):
        starts.append(start)
    keep = len(loop_verts)
    me = bpy.data.meshes.new(name)
    me.vertices.add(nverts)
    me.vertices.foreach_set("co", co)
    me.loops.add(keep)
    me.loops.foreach_set("vertex_index", loop_verts)
    me.polygons.add(len(starts))
    me.polygons.foreach_set("loop_start", starts)

    uv_layers = model.all("LayerElementUV")
    for k, layer in enumerate(uv_layers):
        uvs = _per_loop(layer, "UV", "UVIndex", 2, loop_verts, poly_of_loop)
        if uvs:
            uvl = me.uv_layers.new(name=str(layer.value("Name", "")) or ("UVMap" if k == 0 else "UVMap.%d" % k))
            uvl.data.foreach_set("uv", [c for uv in uvs for c in uv])
    for layer in model.all("LayerElementColor")[:1]:
        cols = _per_loop(layer, "Colors", "ColorIndex", 4, loop_verts, poly_of_loop)
        if cols:
            attr = me.color_attributes.new("Col", "FLOAT_COLOR", "CORNER")
            attr.data.foreach_set("color", [c for col in cols for c in col])
    mats = None
    for layer in model.all("LayerElementMaterial")[:1]:
        idx = [int(i) for i in layer.numbers("Materials")]
        mapping = str(layer.value("MappingInformationType", "AllSame"))
        if idx and mapping == "ByPolygon":
            mats = (idx + [idx[-1]] * len(starts))[:len(starts)]
    tex_ids = None
    for layer in model.all("LayerElementTexture")[:1]:
        idx = [int(i) for i in layer.numbers("TextureId")]
        mapping = str(layer.value("MappingInformationType", "AllSame"))
        if idx and mapping == "ByPolygon":
            tex_ids = (idx + [idx[-1]] * len(starts))[:len(starts)]
    me.update(calc_edges=True)
    me.validate(clean_customdata=False)
    normals = None
    for layer in model.all("LayerElementNormal")[:1]:
        normals = _per_loop(layer, "Normals", "NormalsIndex", 3, loop_verts, poly_of_loop)
    if normals and len(normals) == len(me.loops):
        me.shade_smooth()
        out = []
        for n in normals:
            v = rot @ Vector(n)
            out.append(v.normalized() if v.length > 1e-9 else Vector((0, 0, 1)))
        try:
            me.normals_split_custom_set(out)
        except (RuntimeError, ValueError):
            pass
    return me, mats, tex_ids


def _image(tex, base_dir):
    from bpy_extras.image_utils import load_image
    rel = str(tex.value("RelativeFilename", "") or "")
    absf = str(tex.value("FileName", "") or tex.value("Filename", "") or "")
    for cand in (os.path.join(base_dir, rel) if rel else "", absf, os.path.join(base_dir, os.path.basename(absf.replace("\\", "/")))):
        if cand and os.path.isfile(cand):
            return load_image(cand, check_existing=True)
    name = os.path.basename((rel or absf).replace("\\", "/"))
    if not name:
        return None
    # placeholder with the original path: textures.resolve() looks for it next to the model, or unplugs it
    return load_image(name, base_dir, place_holder=True, recursive=False, check_existing=True)


def _material(name, props, image):
    mat = bpy.data.materials.new(name or "Material")
    mat.use_nodes = True
    nt = mat.node_tree
    bsdf = next((n for n in nt.nodes if n.type == "BSDF_PRINCIPLED"), None)
    if bsdf is None:
        return mat
    col = props.get("DiffuseColor") or props.get("Diffuse")
    if col and len(col) >= 3:
        bsdf.inputs["Base Color"].default_value = (float(col[0]), float(col[1]), float(col[2]), 1.0)
    op = props.get("Opacity")
    if op and float(op[0]) < 0.999:
        bsdf.inputs["Alpha"].default_value = float(op[0])
    if image is not None:
        tn = nt.nodes.new("ShaderNodeTexImage")
        tn.image = image
        tn.location = (bsdf.location.x - 320, bsdf.location.y)
        nt.links.new(tn.outputs["Color"], bsdf.inputs["Base Color"])
        if os.path.splitext(image.filepath)[1].lower() in (".png", ".tga", ".dds", ".tif", ".tiff", ".exr"):
            nt.links.new(tn.outputs["Alpha"], bsdf.inputs["Alpha"])
    return mat


def load(path):
    tree = read_tree(path)
    objects = tree.first("Objects")
    if objects is None:
        raise ApiError(tr("Il file FBX non contiene oggetti"))
    base_dir = os.path.dirname(os.path.abspath(path))

    settings = {}
    gs = objects.first("GlobalSettings") or tree.first("GlobalSettings")
    if gs is not None:
        settings = _props(gs)
    conv = _axis_matrix(settings)

    models, materials, textures = {}, {}, {}
    for node in objects.kids:
        key = str(node.vals[0]) if node.vals else ""
        if node.name == "Model":
            models[key] = node
        elif node.name == "Material":
            materials[key] = node
        elif node.name == "Texture":
            textures[key] = node

    parent_of, mats_of, texs_of, tex_of_mat = {}, {}, {}, {}
    conns = tree.first("Connections")
    for c in (conns.kids if conns is not None else []):
        if c.name not in ("Connect", "C") or len(c.vals) < 3:
            continue
        child, par = str(c.vals[1]), str(c.vals[2])
        if child in models and par in models:
            parent_of[child] = par
        elif child in materials and par in models:
            mats_of.setdefault(par, []).append(child)
        elif child in textures and par in models:
            texs_of.setdefault(par, []).append(child)
        elif child in textures and par in materials:
            tex_of_mat.setdefault(par, child)

    images = {}

    def image_for(tex_key):
        if tex_key not in images:
            images[tex_key] = _image(textures[tex_key], base_dir)
        return images[tex_key]

    made_mats = {}

    def material_for(mat_key=None, tex_key=None):
        k = (mat_key, tex_key)
        if k in made_mats:
            return made_mats[k]
        if mat_key:
            node = materials[mat_key]
            tk = tex_key or tex_of_mat.get(mat_key)
            m = _material(mat_key.split("::", 1)[-1], _props(node), image_for(tk) if tk else None)
        else:
            tname = os.path.splitext(os.path.basename(str(textures[tex_key].value("RelativeFilename", "") or tex_key.split("::", 1)[-1])))[0]
            m = _material(tname, {}, image_for(tex_key))
        made_mats[k] = m
        return m

    coll = bpy.context.collection
    obs = {}
    for key, node in models.items():
        kind = str(node.vals[1]) if len(node.vals) > 1 else ""
        name = key.split("::", 1)[-1] or "Oggetto"
        data = None
        if kind == "Mesh" or node.first("Vertices") is not None:
            built = _mesh(name, node, Matrix.Identity(4))
            if built:
                me, mat_idx, tex_idx = built
                slots = []
                if mats_of.get(key):
                    texs = texs_of.get(key, [])
                    for i, mk in enumerate(mats_of[key]):
                        slots.append(material_for(mk, texs[i] if i < len(texs) and len(texs) > 1 else None))
                    if mat_idx:
                        me.polygons.foreach_set("material_index", [max(0, min(i, len(slots) - 1)) for i in mat_idx])
                elif texs_of.get(key):
                    for tk in texs_of[key]:
                        slots.append(material_for(None, tk))
                    if tex_idx:
                        me.polygons.foreach_set("material_index", [max(0, min(i, len(slots) - 1)) for i in tex_idx])
                for m in slots:
                    me.materials.append(m)
                data = me
        elif kind in ("Camera", "Light", "CameraSwitcher"):
            continue
        ob = bpy.data.objects.new(name, data)
        coll.objects.link(ob)
        obs[key] = (ob, _local_matrix(_props(node)))

    # hierarchy and transforms, in FBX space, then into Blender space (Z up, metres)
    world = {}

    def world_of(key):
        if key not in world:
            ob, local = obs[key]
            par = parent_of.get(key)
            world[key] = (world_of(par) if par in obs else Matrix.Identity(4)) @ local
        return world[key]

    for key, (ob, _local) in obs.items():
        w = world_of(key)
        # geometry is baked in Blender space; the object keeps only its position (pivot where the file had it)
        loc = (conv @ w).to_translation()
        if ob.type == "MESH":
            ob.data.transform(Matrix.Translation(-loc) @ conv @ w)
        ob.matrix_world = Matrix.Translation(loc)
    bpy.context.view_layer.update()
    for key, (ob, _local) in obs.items():
        par = parent_of.get(key)
        if par in obs:
            ob.parent = obs[par][0]
            ob.matrix_parent_inverse = obs[par][0].matrix_world.inverted()
    if not obs:
        raise ApiError(tr("Il file FBX non contiene oggetti"))
    return [o for o, _ in obs.values()]
