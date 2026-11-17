"""Texture proxies for the previews (see proxy_job.py).

Textures can be files or packed inside the project (FBX files with embedded textures). Packed ones are written once
to the cache as files (their original bytes, nothing decoded) so they can be reduced like the others. The previews
use the reduced copies by pointing the material image nodes to small "proxy" images; the original images stay
untouched and are put back for saving and for the final render.

Big textures get reduced copies in a local cache (2048 px for the path tracing view, 1024 or 2048 for the real-time
view, each size made once and kept for the next sessions), built in the background by
several Blender processes at once. The path tracing view and the real-time view use the copies: Cycles loads
them many times faster (the slow part of the first path tracing pass on big models is reading and decoding
hundreds of 4K/8K textures, often from a network drive). Saving a project and the final render always use the
original files.
"""
import contextlib
import hashlib
import json
import os
import struct
import subprocess
import tempfile
import threading
import time

import bpy

from . import fullspeed

PROXY_PX = 2048                  # path tracing view
SRC_KEY = "simpler_src"          # on a proxied image: the original file
PACK_KEY = "simpler_pack"        # on a packed image: "<size hex>|<file name in the cache>"
FLOAT_EXT = (".exr", ".hdr", ".tif", ".tiff")   # may hold float data: keep the originals

_lock = threading.Lock()
_state = {"running": False, "done": 0, "total": 0, "procs": [], "started": 0.0}
READY = {}                        # (original abs path, px) -> file in the cache; px 0 = exact local copy
_SEEN = set()                     # (original, px) already looked at (ready, not needed, queued or failed)
_QUEUE = []                       # (original, px) waiting for the background job
_DIMS = {}                        # original -> (w, h) read from the file header, or None


def cache_dir():
    base = os.environ.get("LOCALAPPDATA") or tempfile.gettempdir()
    d = os.path.join(base, "Simpler", "texcache")
    os.makedirs(d, exist_ok=True)
    return d


def _key(path, px):
    st = os.stat(path)
    h = hashlib.sha1(f"{os.path.normcase(path)}|{st.st_size}|{int(st.st_mtime)}".encode("utf-8")).hexdigest()[:20]
    return os.path.join(cache_dir(), f"{h}_{px}" if px else f"{h}")


def _cached(path, px):
    try:
        base = _key(path, px)
    except OSError:
        return None
    from . import diskcache
    if px:
        for ext in (".jpg", ".png"):
            if os.path.isfile(base + ext):
                diskcache.touch(base + ext)          # (1.76.51: used - the cache keeps the files used last)
                return base + ext
        return None
    copy = base + "_copy" + os.path.splitext(path)[1].lower()
    if os.path.isfile(copy):
        diskcache.touch(copy)
        return copy
    return None


def is_remote(path):
    """Network drive or share (and removable drives): textures read from there are slow."""
    if os.name != "nt":
        return False
    p = os.path.abspath(path)
    if p.startswith("\\\\"):
        return True
    try:
        import ctypes
        kind = ctypes.windll.kernel32.GetDriveTypeW(ctypes.c_wchar_p(p[:3]))
        return kind in (2, 4)        # DRIVE_REMOVABLE, DRIVE_REMOTE
    except Exception:
        return False


def _dimensions(path):
    """Width and height from the file header (PNG, JPEG, GIF, BMP) without decoding; None if unknown."""
    try:
        with open(path, "rb") as f:
            head = f.read(26)
            if head[:8] == b"\x89PNG\r\n\x1a\n":
                return struct.unpack(">II", head[16:24])
            if head[:6] in (b"GIF87a", b"GIF89a"):
                return struct.unpack("<HH", head[6:10])
            if head[:2] == b"BM" and len(head) >= 26:
                # (Luca: «ficus tree senza materiale») BMP: size unknown = never a copy the view can show
                w, h = struct.unpack("<ii", head[18:26])
                return (abs(w), abs(h)) if w and h else None
            if head[:2] == b"\xff\xd8":
                f.seek(2)
                while True:
                    b = f.read(1)
                    while b and b != b"\xff":
                        b = f.read(1)
                    while b == b"\xff":
                        b = f.read(1)
                    if not b:
                        return None
                    marker = b[0]
                    if marker in (0xC0, 0xC1, 0xC2, 0xC3, 0xC5, 0xC6, 0xC7, 0xC9, 0xCA, 0xCB, 0xCD, 0xCE, 0xCF):
                        f.read(3)
                        h, w = struct.unpack(">HH", f.read(4))
                        return w, h
                    seg = struct.unpack(">H", f.read(2))[0]
                    f.seek(seg - 2, 1)
    except (OSError, struct.error):
        return None
    return None


NODE_ORIG = "simpler_orig"        # on an image node showing a proxy: name of the original image
PROXY_TAG = "simpler_proxy"       # on a proxy image datablock
NO_PROXY = "simpler_noproxy"      # (1.75.38) on an image of Simpler's own (a data map: the shelter of the rain): never swapped
_SRC_OF = {}                      # original image name -> source file (packed images: extracted to the cache)
_SRC_ID = {}                      # (1.78.4) original image name -> what that image was (file, packed size) when looked up
_NAME_SRC = {}                    # same, filled for the export thread (no bpy access there)


def source_path(im):
    return im.get(SRC_KEY) or bpy.path.abspath(im.filepath)


def dims(path):
    """Width and height of a texture file from its header (cached); None if unknown."""
    if path not in _DIMS:
        _DIMS[path] = _dimensions(path)
    return _DIMS[path]


def _image_trees():
    for m in bpy.data.materials:
        if m.node_tree is not None:
            yield m.node_tree
    for g in bpy.data.node_groups:
        yield g
    for w in bpy.data.worlds:
        if w.node_tree is not None:
            yield w.node_tree


def _image_nodes(trees=None):
    for tree in (trees if trees is not None else _image_trees()):
        for node in tree.nodes:
            if node.type in ("TEX_IMAGE", "TEX_ENVIRONMENT"):
                yield node


def _original(node):
    name = node.get(NODE_ORIG)
    im = node.image
    # (1.75.38) the node shows an image that is not a proxy: someone put a new image there after the swap (the rain,
    # every new shelter map). The name of the "original" kept on the node is stale: the final render put back the
    # old image, its file already deleted - no shelter map, the road dry (Luca, archmodel palazzi, scene 8)
    if name and im is not None and not im.get(PROXY_TAG):
        del node[NODE_ORIG]
        name = ""
    if name:
        return bpy.data.images.get(name)
    return None if im is None or im.get(PROXY_TAG) else im


def originals_in_use():
    """The original images the materials use (also while they show a proxy)."""
    out = {}
    for node in _image_nodes():
        im = _original(node)
        if im is not None and im.source in ("FILE", "TILED") and not im.get(NO_PROXY):
            out[im.name] = im
    return list(out.values())


def _magic_ext(data):
    if data[:8] == b"\x89PNG\r\n\x1a\n":
        return ".png"
    if data[:2] == b"\xff\xd8":
        return ".jpg"
    if data[:4] in (b"II*\x00", b"MM\x00*"):
        return ".tif"
    if data[:4] == b"\x76\x2f\x31\x01":
        return ".exr"
    return ""


_PACK_INDEX = {"data": None, "dirty": False}


def _pack_index():
    """Packed textures already extracted to the cache, by image name, path and size (kept between sessions)."""
    if _PACK_INDEX["data"] is None:
        try:
            with open(os.path.join(cache_dir(), "packed_index.json"), encoding="utf-8") as f:
                _PACK_INDEX["data"] = json.load(f)
        except (OSError, ValueError):
            _PACK_INDEX["data"] = {}
    return _PACK_INDEX["data"]


def _pack_index_put(key, value):
    _pack_index()[key] = value
    _PACK_INDEX["dirty"] = True


def save_pack_index():
    if not _PACK_INDEX["dirty"]:
        return
    try:
        path = os.path.join(cache_dir(), "packed_index.json")
        with open(path + ".part", "w", encoding="utf-8") as f:
            json.dump(_PACK_INDEX["data"], f)
        os.replace(path + ".part", path)
        _PACK_INDEX["dirty"] = False
    except OSError:
        pass


def _ident(im):
    try:
        size = im.packed_file.size if im.packed_file is not None else -1
    except Exception:
        size = -1
    return (im.filepath, str(im.get(SRC_KEY, "")), size)


def _still(path):
    """(1.78.4) a GIF (Blender opens it as a movie; reduced copies and the real-time view take still pictures): the
    same picture as a PNG in the cache, made once. Other files as they are."""
    if os.path.splitext(path)[1].lower() != ".gif":
        return path
    try:
        st = os.stat(path)
        h = hashlib.sha1(f"{os.path.normcase(path)}|{st.st_size}|{int(st.st_mtime)}".encode("utf-8")).hexdigest()[:16]
        png = os.path.join(cache_dir(), f"gif_{h}.png")
        if os.path.isfile(png):
            return png
        from . import stillgif
        return png if stillgif.to_png(path, png) else path
    except OSError:
        return path


def source_of(im):
    """File with the original pixels of an image: its file, or the packed bytes written once to the cache."""
    # (1.78.4, Luca: flowers yellow in path tracing, violet in the real-time view) the names of the pictures of
    # imported plants are generic («color map.015») and come back for another picture when models are loaded and
    # removed: the file remembered for the name was another plant's. The name counts only for the same picture.
    ident = _ident(im)
    if im.name in _SRC_OF and _SRC_ID.get(im.name) == ident:
        return _SRC_OF[im.name]
    _SRC_ID[im.name] = ident
    src = None
    if im.packed_file is not None:
        try:
            # the name of the extracted file is remembered in the image (and saved with the project): reading
            # hundreds of packed textures into memory just to find their names took seconds at every opening
            size = im.packed_file.size
            known = str(im.get(PACK_KEY, "")) or _pack_index().get(f"{im.name}|{im.filepath}|{size}", "")
            if known.startswith(f"{size:x}|") and os.path.isfile(os.path.join(cache_dir(), known.split("|", 1)[1])):
                src = os.path.join(cache_dir(), known.split("|", 1)[1])
                _SRC_OF[im.name] = src
                with _lock:
                    _NAME_SRC[im.name] = src
                return src
            data = im.packed_file.data
            ext = _magic_ext(data[:16]) or os.path.splitext(im.filepath)[1].lower() or ".png"
            h = hashlib.sha1(data[:1 << 20]).hexdigest()[:16] + f"{len(data):x}"
            path = os.path.join(cache_dir(), f"packed_{h}{ext}")
            im[PACK_KEY] = f"{size:x}|packed_{h}{ext}"
            _pack_index_put(f"{im.name}|{im.filepath}|{size}", im[PACK_KEY])
            if not os.path.isfile(path):
                with open(path + ".part", "wb") as f:
                    f.write(data)
                os.replace(path + ".part", path)
            src = path
        except Exception as exc:   # unreadable packed data: the preview keeps the original
            print("SIMPLER_WARN packed", im.name, exc, flush=True)
    else:
        path = os.path.normpath(source_path(im))
        src = _still(path) if os.path.isfile(path) else None
    _SRC_OF[im.name] = src
    with _lock:
        _NAME_SRC[im.name] = src
    return src


def _candidates(sizes):
    """(source, px) pairs that deserve a file in the cache. Each pair is looked at once per session."""
    out = []
    for im in originals_in_use():
        path = source_of(im)
        if not path:
            continue
        remote = im.packed_file is None and is_remote(path)
        float_data = os.path.splitext(path)[1].lower() in FLOAT_EXT
        dim = None if float_data else dims(path)
        for px in sizes:
            if float_data:
                want = 0 if remote else None                 # float data: never reduced, copied if remote
            else:
                big = (max(dim) > px) if dim else os.path.getsize(path) > 3 * 1024 * 1024
                want = px if big else (0 if remote else None)  # reduced, or exact local copy, or nothing
            if want is None or (path, want) in _SEEN:
                continue
            _SEEN.add((path, want))
            out.append((path, want))
    save_pack_index()
    return out


def texture_bytes(px):
    """Rough GPU memory of the textures in use if reduced to px (4 bytes per pixel)."""
    total = 0
    for im in originals_in_use():
        path = source_of(im)
        d = dims(path) if path else None
        w, h = d if d else (2048, 2048)
        k = min(1.0, px / max(w, h)) if px > 0 else 1.0
        total += w * k * h * k * 4
    return total


def status():
    with _lock:
        return {"running": _state["running"], "done": _state["done"], "total": _state["total"],
                "elapsed": round(time.time() - _state["started"], 1) if _state["running"] else 0}


def ensure_async(sizes=(PROXY_PX,), workers=None):
    """Queues the missing reduced copies (for each size in sizes) and builds them in the background.
    Returns True while a job is running (the caller can wait for it)."""
    todo = []
    for path, px in _candidates(sizes):
        ready = _cached(path, px)
        if ready:
            with _lock:
                READY[(path, px)] = ready
        else:
            todo.append((path, px))
    exe = os.environ.get("SIMPLER_RENDER_EXE") or bpy.app.binary_path
    if not exe or not os.path.isfile(exe):
        return False
    with _lock:
        _QUEUE.extend(todo)
        if _state["running"]:
            _state["total"] += len(todo)
            return True
        if not _QUEUE:
            return False
        _state.update(running=True, done=0, total=len(_QUEUE), procs=[], started=time.time())
    n = workers or max(1, min(6, (os.cpu_count() or 4) - 2))
    script = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "proxy_job.py")
    threading.Thread(target=_runner, args=(exe, script, n), daemon=True).start()
    return True


def _runner(exe, script, n):
    """Works through the queue (new requests can arrive while it runs)."""
    t0 = time.time()
    count = 0
    while True:
        with _lock:
            batch = list(_QUEUE)
            _QUEUE.clear()
            if not batch:
                _state.update(running=False, procs=[])
                break
        count += len(batch)
        _run(exe, script, batch, min(n, len(batch)))
    print(f"SIMPLER_PROXIES {count} in {time.time() - t0:.1f}s", flush=True)



def _run(exe, script, todo, n):
    flags = (0x08000000 | 0x00004000) if os.name == "nt" else 0   # no window, below normal priority
    chunks = [todo[i::n] for i in range(n)]
    procs, files, wanted = [], [], {}
    for chunk in chunks:
        jf = tempfile.NamedTemporaryFile("w", suffix=".json", delete=False, encoding="utf-8")
        jobs = []
        for p, px in chunk:
            try:
                jobs.append([p, _key(p, px), px])
            except OSError:
                continue
        json.dump(jobs, jf)
        jf.close()
        files.append(jf.name)
        procs.append(fullspeed.popen([exe, "--factory-startup", "-b", "--python", script, "--", jf.name],
                                      stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, encoding="utf-8",
                                      errors="replace", creationflags=flags, bufsize=1))
    with _lock:
        _state["procs"] = procs

    def read(proc):
        for line in proc.stdout:
            if line.startswith("SIMPLER_PROXY "):
                rest = line[14:].rstrip("\n").split("\t")
                src, px, out = rest[0], int(rest[1]) if len(rest) > 2 else 0, rest[-1] if len(rest) > 1 else ""
                with _lock:
                    _state["done"] += 1
                    if out:
                        READY[(os.path.normpath(src), px)] = out
        proc.wait()

    readers = [threading.Thread(target=read, args=(p,), daemon=True) for p in procs]
    for r in readers:
        r.start()
    for r in readers:
        r.join()
    for f in files:
        try:
            os.remove(f)
        except OSError:
            pass


def wait(timeout=None):
    t0 = time.time()
    while status()["running"]:
        if timeout is not None and time.time() - t0 > timeout:
            return False
        time.sleep(0.2)
    return True


def stop():
    with _lock:
        procs = list(_state["procs"])
    for p in procs:
        try:
            p.kill()
        except OSError:
            pass


def forget(name):
    """An image found again in another file (missing textures linked again, copies next to the project): its source
    is looked up again. Before 1.68.3 a texture missing at the opening stayed «without file» for the session - linked
    again, the path tracing had it but the real-time view (which asks for its file here) did not."""
    _SRC_OF.pop(name, None)
    _SRC_ID.pop(name, None)
    with _lock:
        _NAME_SRC.pop(name, None)


def file_for(im, px, view=False):
    """A file showing this image at most px wide (for the app and the real-time view): the reduced copy when it is
    ready (it is made in the background otherwise), else the original. None if the image has no file.
    view: for the real-time view (a browser) - every picture that is not JPEG/PNG comes as a PNG copy of its own; the
    material previews (Cycles) keep the originals of the other formats (float data of EXR/HDR/TIFF not clamped)."""
    src = source_of(im)
    if not src:
        return None
    ext = os.path.splitext(src)[1].lower()
    srgb = view and bool(im.get(VIEW_SRGB)) and ext not in DIRECT_EXT
    if view and ext not in DIRECT_EXT:
        # (Luca: «perché questi materiali, eppure erano a posto» - «verifica che sia gestito per tutti i tipi di file»)
        # a picture other than JPEG/PNG (TIFF, TGA, EXR, HDR, BMP, WebP, DDS, JPEG 2000...) had no copy when it was
        # small, of a size not read from its header, or kept as it is (TIFF and EXR: never reduced for the render), so
        # the real-time view got nothing and the leaves of a plant drawn with its Simpler material came white and
        # solid. Now a PNG copy (alpha kept) at most px wide, made at once, kept in the cache under a name of its own
        # (the reduced copies of the render never get it).
        key = (src + "|srgb" if srgb else src, -px)
        with _lock:
            ready = READY.get(key)
        if ready and os.path.isfile(ready):
            return ready
        made = _view_copy(src, px, srgb)
        if made:
            with _lock:
                READY[key] = made
            return made
        return src if ext in (".gif", ".webp", ".bmp", ".avif") else None    # (Blender cannot read it, a browser can)
    d = dims(src)
    if d and max(d) <= px:
        return src
    with _lock:
        ready = READY.get((src, px))
    if ready and os.path.isfile(ready):
        return ready
    cached = _cached(src, px)
    if cached:
        with _lock:
            READY[(src, px)] = cached
        return cached
    _SEEN.discard((src, px))
    ensure_async(sizes=(px,))
    return src if ext in (".jpg", ".jpeg", ".png") else None


# (1.79.0) a float picture (EXR, HDR) shown in the view as colour - the room picture of «Interni»: its copy written as
# sRGB (the view reads it as colour), not its linear values in 8 bits (twelve times darker than in the render)
VIEW_SRGB = "simpler_view_srgb"

DIRECT_EXT = (".jpg", ".jpeg", ".png")      # served to the view as they are (a smaller copy made in the background when big)


def _view_copy(src, px, srgb=False):
    """A PNG of a picture the browser cannot read, at most px wide, in the cache (the name of the reduced copies, so
    _cached finds it next time). None if Blender cannot read it either."""
    try:
        out = _key(src, px) + ("_view_srgb.png" if srgb else "_view.png")
    except OSError:
        return None
    if os.path.isfile(out):
        return out
    im = None
    try:
        im = bpy.data.images.load(src, check_existing=False)
        im[NO_PROXY] = 1
        w, h = im.size
        if not w or not h:
            return None
        k = min(1.0, px / max(w, h))
        if k < 1.0:
            im.scale(max(1, int(w * k)), max(1, int(h * k)))
        if srgb and im.is_float:
            import numpy as np
            w, h = im.size
            a = np.empty(w * h * 4, dtype=np.float32)
            im.pixels.foreach_get(a)
            a = a.reshape(-1, 4)
            al = a[:, 3:4]
            rgb = np.where(al > 1e-6, a[:, :3] / np.maximum(al, 1e-6), a[:, :3])      # (float pictures: premultiplied)
            rgb = np.clip(rgb, 0.0, 1.0)
            a[:, :3] = np.where(rgb <= 0.0031308, rgb * 12.92, 1.055 * np.power(rgb, 1.0 / 2.4) - 0.055)
            b = bpy.data.images.new("simpler view srgb", w, h, alpha=True, float_buffer=False)
            b[NO_PROXY] = 1
            b.pixels.foreach_set(a.ravel())
            bpy.data.images.remove(im)
            im = b
        tmp = out + ".part.png"
        im.filepath_raw = tmp
        im.file_format = "PNG"
        im.save()
        os.replace(tmp, out)
        return out
    except Exception as exc:                       # (not readable: the view keeps asking a few times, then stops)
        print("SIMPLER_PROXY view copy failed", os.path.basename(src), exc, flush=True)
        return None
    finally:
        if im is not None:
            try:
                bpy.data.images.remove(im)
            except Exception:
                pass


def proxy_map(px=PROXY_PX):
    """Original image name -> file to use at that size (reduced copy, or exact local copy). Thread safe."""
    with _lock:
        by_src = {src: f for (src, p), f in READY.items() if p == 0}
        by_src.update({src: f for (src, p), f in READY.items() if p == px})
        return {name: by_src[src] for name, src in _NAME_SRC.items() if src in by_src}


def is_copy(path):
    return "_copy." in os.path.basename(path or "")


_PROXY_BY_PATH = {}                # normalised proxy file -> name of its image datablock (avoids scanning all images)


def _proxy_image(path, orig):
    key = os.path.normcase(os.path.normpath(path))
    name = _PROXY_BY_PATH.get(key)
    im = bpy.data.images.get(name) if name else None
    if im is not None and im.get(PROXY_TAG) and os.path.normcase(os.path.normpath(bpy.path.abspath(im.filepath))) == key:
        return im
    if not _PROXY_BY_PATH:                  # first use in this session (or after opening a project): index once
        for other in bpy.data.images:
            if other.get(PROXY_TAG):
                _PROXY_BY_PATH[os.path.normcase(os.path.normpath(bpy.path.abspath(other.filepath)))] = other.name
        name = _PROXY_BY_PATH.get(key)
        im = bpy.data.images.get(name) if name else None
        if im is not None:
            return im
    im = bpy.data.images.load(path, check_existing=False)
    im[PROXY_TAG] = 1
    im.name = "proxy·" + orig.name
    try:
        im.colorspace_settings.name = orig.colorspace_settings.name
    except TypeError:
        pass
    im.alpha_mode = orig.alpha_mode
    _PROXY_BY_PATH[key] = im.name
    return im


@bpy.app.handlers.persistent
def _on_load(*_args):
    _PROXY_BY_PATH.clear()          # another file: other datablocks (an image with the same name may be another one)
    _SRC_OF.clear()
    _SRC_ID.clear()
    with _lock:
        _NAME_SRC.clear()


if _on_load not in bpy.app.handlers.load_post:
    bpy.app.handlers.load_post.append(_on_load)


def drop_unused():
    """Proxy images no material shows any more (another size, used once for a final render or a save): removed,
    so they do not pile up during a session. They come back from the cache in a moment if needed again."""
    n = 0
    for im in list(bpy.data.images):
        if im.get(PROXY_TAG) and im.users == 0:
            bpy.data.images.remove(im)
            n += 1
    if n:
        _PROXY_BY_PATH.clear()
    return n


def apply(px, trees=None):
    """Image nodes show the files for this size: reduced copies (px > 0), exact local copies (always, when they
    exist), or the originals. px=None: originals everywhere. Returns how many nodes changed. (1.76.50) trees: only
    these node trees (a material just made: before, every material of the scene was walked for each one)."""
    files = proxy_map(px) if px is not None else {}
    n = 0
    for node in _image_nodes(trees):
        orig = _original(node)
        if orig is None:
            continue
        want_file = None if orig.get(NO_PROXY) else files.get(orig.name)     # (1.75.38: Simpler's data maps never)
        if want_file:
            pim = _proxy_image(want_file, orig)
            if node.image != pim:
                node[NODE_ORIG] = orig.name
                orig.use_fake_user = True         # no node uses it now: keep it (it comes back for saving and rendering)
                node.image = pim
                n += 1
        elif node.get(NODE_ORIG):
            node.image = orig
            del node[NODE_ORIG]
            orig.use_fake_user = False
            n += 1
    return n


def restore():
    return apply(None)


CURRENT = {"px": None}               # what the image nodes show now (None = originals)


def use(px):
    """apply() and remember it as the current state."""
    CURRENT["px"] = px
    return apply(px)


@contextlib.contextmanager
def originals(for_render=False):
    """Saving a project, or the scene for the final render: the original images in the nodes, then back.
    for_render: exact local copies of network textures stay (same pixels, read much faster)."""
    prev = CURRENT["px"]
    apply(-1 if for_render else None)
    for im in bpy.data.images:
        if im.get(PROXY_TAG) and im.users == 0:
            im.use_fake_user = False
    try:
        yield
    finally:
        apply(prev)
        drop_unused()


@contextlib.contextmanager
def for_render(px):
    """The final render: originals (px 0, exact local copies of network files allowed) or reduced copies."""
    if not px:
        with originals(for_render=True):
            yield
        return
    prev = CURRENT["px"]
    apply(px)
    try:
        yield
    finally:
        apply(prev)
        drop_unused()
