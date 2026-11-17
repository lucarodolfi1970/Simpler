"""Finding the textures of imported models and keeping missing ones from turning the render magenta.

FBX files often point to texture paths of the machine they were exported on. We search by file name in the
model's folder, its parent folders and any folder the user indicates. Textures still missing are disconnected
from their material (the material keeps its base colour) instead of rendering magenta in Cycles; they are
reconnected automatically as soon as they are found.
"""
import json
import ntpath
import os

import bpy

from . import progress
from .i18n import tr

IMAGE_EXT = (".png", ".jpg", ".jpeg", ".tga", ".tif", ".tiff", ".bmp", ".exr", ".hdr", ".webp", ".psd", ".dds", ".jp2")
CUT_KEY = "simpler_cut_links"
MAX_FILES = 300000


def _file_name(path):
    # paths written on Windows may use either separator, whatever system we run on. Blender's relative paths start
    # with "//": read as a network path ("\\\\folder\\file") they had no file name - a texture saved next to the
    # project (relative) was never found again by name (1.68.2)
    if path and path.startswith("//"):
        path = path[2:]
    return ntpath.basename(path.replace("/", "\\")) if path else ""


def _real_file(path):
    """The file name of a picture, or "" when the path names no file: empty, or a name without extension - an FBX
    from 3ds Max can carry «M:/Map #5234338», the name of the map put where its file should be. Nothing to look for
    there: before 1.74.0 it was asked for at every opening of the project («Non ho trovato 1 texture»)."""
    name = _file_name(path)
    return name if os.path.splitext(name)[1] else ""


def is_missing(img):
    if img.source not in ("FILE", "TILED") or img.packed_file:
        return False
    if img.get("simpler_refcaustics_img"):
        # (1.73.8) the light reflected by the water (refcaustics): Simpler's own pictures in a temporary folder,
        # made again before the next path-traced image - never «missing textures» of the project
        return False
    path = bpy.path.abspath(img.filepath)
    return not path or not os.path.isfile(path)


def missing_images():
    return [img for img in bpy.data.images if img.users and is_missing(img)]


class Index:
    """File name -> path for every image under some folders (case-insensitive, also by name without extension)."""

    def __init__(self):
        self.by_name, self.by_stem, self.files = {}, {}, 0

    def add_folder(self, folder, max_depth=6):
        if not folder or not os.path.isdir(folder):
            return
        base_depth = folder.rstrip("\\/").count(os.sep)
        for root, dirs, files in os.walk(folder):
            if root.count(os.sep) - base_depth >= max_depth:
                dirs[:] = []
            dirs[:] = [d for d in dirs if not d.startswith(".") and d.lower() not in ("$recycle.bin", "windows", "node_modules")]
            for f in files:
                stem, ext = os.path.splitext(f)
                if ext.lower() not in IMAGE_EXT:
                    continue
                p = os.path.join(root, f)
                self.by_name.setdefault(f.lower(), p)
                self.by_stem.setdefault(stem.lower(), []).append(p)
                self.files += 1
                if self.files >= MAX_FILES:
                    return

    def find(self, wanted):
        name = _file_name(wanted)
        if not name:
            return None
        hit = self.by_name.get(name.lower())
        if hit:
            return hit
        # same name, different format (e.g. .tga exported as .png)
        stem = os.path.splitext(name)[0].lower()
        cands = self.by_stem.get(stem)
        return cands[0] if cands else None


def _material_trees():
    for mat in bpy.data.materials:
        if mat.node_tree:
            yield mat.node_tree
    for ng in bpy.data.node_groups:
        yield ng


def _image_nodes(img):
    for tree in _material_trees():
        for node in tree.nodes:
            if node.type == "TEX_IMAGE" and node.image == img:
                yield tree, node


def disconnect(img):
    """Unplug a missing texture: its material falls back to the plain values instead of magenta."""
    for tree, node in _image_nodes(img):
        cut = json.loads(node.get(CUT_KEY, "[]"))
        for out in node.outputs:
            for lk in list(out.links):
                cut.append([out.identifier, lk.to_node.name, lk.to_socket.identifier])
                tree.links.remove(lk)
        if cut:
            node[CUT_KEY] = json.dumps(cut)


def reconnect(img):
    for tree, node in _image_nodes(img):
        cut = json.loads(node.get(CUT_KEY, "[]"))
        for out_id, to_name, to_id in cut:
            out = next((s for s in node.outputs if s.identifier == out_id), None)
            to_node = tree.nodes.get(to_name)
            to_sock = next((s for s in to_node.inputs if s.identifier == to_id), None) if to_node else None
            if out and to_sock:
                tree.links.new(out, to_sock)
        if CUT_KEY in node:
            del node[CUT_KEY]


LAST_EMPTY = []      # the last resolve: pictures without any file (described), see resolve


def _users_by_image():
    """Image name -> names of the materials that show it (their trees and the groups inside them)."""
    out = {}

    def scan(tree, mat, seen):
        if tree is None or tree.as_pointer() in seen:
            return
        seen.add(tree.as_pointer())
        for n in tree.nodes:
            im = getattr(n, "image", None)
            if im is not None:
                out.setdefault(im.name, [])
                if mat not in out[im.name]:
                    out[im.name].append(mat)
            if n.type == "GROUP":
                scan(n.node_tree, mat, seen)
    for m in bpy.data.materials:
        if m.users and m.node_tree is not None:
            scan(m.node_tree, m.name, set())
    return out


def describe(img, users=None):
    """What the user can recognise of a missing picture: its file and the materials it belongs to (the name of the
    image datablock - «Map #0» of a 3ds Max model - says nothing)."""
    mats = (users if users is not None else _users_by_image()).get(img.name, [])
    what = _file_name(img.filepath) or img.name
    if not mats:
        return what
    more = f" +{len(mats) - 2}" if len(mats) > 2 else ""
    return what + "  —  " + tr("materiale") + " " + ", ".join(f"«{m}»" for m in mats[:2]) + more


def resolve(images, folders, report_task=None):
    """Try to find every image in `images`; reconnect the found ones, disconnect the others.
    Returns (found_names, missing: what the user can recognise, see describe). Pictures without any file at all (a
    map left empty in the program the model comes from: «Map #0») cannot be looked for: unplugged, kept apart in
    LAST_EMPTY (the app only mentions them; asking for their folder made no sense)."""
    images = [i for i in images if is_missing(i)]
    LAST_EMPTY.clear()
    if not images:
        return [], []
    users = _users_by_image()
    for img in [i for i in images if not _real_file(i.filepath)]:
        disconnect(img)
        LAST_EMPTY.append(describe(img, users))
    images = [i for i in images if _real_file(i.filepath)]
    if not images:
        return [], []
    index = Index()
    for i, entry in enumerate(folders):
        folder, depth = entry if isinstance(entry, tuple) else (entry, 6)
        if report_task:
            progress.update(tr("Ricerca delle texture"), 0.1 + 0.6 * i / max(1, len(folders)), folder)
        index.add_folder(folder, depth)
    found, missing = [], []
    for n, img in enumerate(images):
        if report_task and n % 20 == 0:
            progress.update(tr("Collegamento delle texture"), 0.7 + 0.3 * n / len(images), img.name)
        path = index.find(img.filepath) or index.find(img.name)
        if path:
            img.filepath = path
            try:
                img.reload()
            except RuntimeError:
                pass
            from . import proxies
            proxies.forget(img.name)       # (its file for the real-time view: looked up again)
            reconnect(img)
            found.append(img.name)
        else:
            disconnect(img)
            missing.append(describe(img, users))
    return found, missing


def search_folders_for(model_path):
    """Model folder (deep), plus its parent and grandparent: texture folders usually sit next to the model."""
    folder = os.path.dirname(os.path.abspath(model_path))
    out = [(folder, 6)]
    parent = os.path.dirname(folder)
    if parent and parent != folder and len(parent) > 3:      # never walk a whole drive
        out.append((parent, 3))
        grand = os.path.dirname(parent)
        if grand and grand != parent and len(grand) > 3:
            out.append((grand, 2))
    return out


def relink(data):
    folder = data.get("folder", "")
    if not os.path.isdir(folder):
        from .core import ApiError
        raise ApiError(tr("Cartella non trovata"))
    progress.begin("textures", tr("Ricerca delle texture"))
    try:
        found, missing = resolve(missing_images(), [folder], report_task=True)
    finally:
        progress.end()
    return {"found": len(found), "missing": missing}


def status(_data=None):
    return {"missing": sorted({_real_file(i.filepath) for i in missing_images() if _real_file(i.filepath)})}
