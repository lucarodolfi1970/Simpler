"""HDRI environments: a real photographed sky (360° HDR) as background and light, with its sun made a real Sun light.

Sources: the HDRIs that come with Blender (offline, always there) and Poly Haven (https://polyhaven.com/hdris, CC0,
downloaded the first time they are used, 4K HDR, then kept on disk like the Poly Haven textures).

WHY THE SUN IS EXTRACTED. In an HDRI of a clear day the sun is a few pixels a hundred thousand times brighter than
the sky. Lighting the scene with the picture alone, Cycles finds that tiny spot only by chance: noisy, soft shadows
that take many samples. So, as in the professional tools ("sun from HDRI"), the picture is measured once:
direction, colour and strength of the sun (the light above a threshold around the brightest point), the light of the
sky on the ground (for the automatic exposure) and the colour of the horizon. Then:
  · for the light of the scene the HDRI is clamped at the threshold (no sun in it),
  · the sun becomes a Sun light with that direction, colour, power and size: sharp, clean shadows at once,
  · the camera still sees the original picture (the sun disc as photographed).
Rotating the HDRI turns the sun with it. A cloudy HDRI without a clear sun is used as it is (no Sun light).

Performance: the measurement reads the picture once (numpy, ~1-2 s for 4K) and is cached next to the file; the
world shader adds one clamp (cost ~0). Downloads run in the background (GET hdri/status).
"""
import json
import math
import os
import threading
import time

API = "https://api.polyhaven.com"
REFRESH_DAYS = 7
RES = "4k"
_lock = threading.RLock()
_jobs = {}
_list = {"assets": None, "loading": False, "error": ""}
_thumbs = {"running": False}

BLENDER_HDRIS = [("forest", "Bosco"), ("city", "Città"), ("courtyard", "Cortile"), ("sunrise", "Alba"),
                 ("sunset", "Tramonto"), ("interior", "Interno"), ("night", "Notte"), ("studio", "Studio")]


def root():
    from . import paths
    d = os.path.join(paths.get("phTextures"), "hdri")
    os.makedirs(d, exist_ok=True)
    return d


_BDIR = {"path": None}


def _blender_dir():
    """Folder of the HDRIs that come with Blender (asked once, on the main thread: then also usable elsewhere)."""
    if _BDIR["path"] is None:
        import bpy
        _BDIR["path"] = bpy.utils.system_resource("DATAFILES", path=os.path.join("studiolights", "world")) or ""
    return _BDIR["path"]


def file_of(hid):
    """Local file of an HDRI id ("blender:forest", "polyhaven:<id>"), or "" when not on disk."""
    src, _, name = (hid or "").partition(":")
    name = os.path.basename(name)
    if src == "blender":
        p = os.path.join(_blender_dir(), name + ".exr")
        return p if os.path.isfile(p) else ""
    if src == "polyhaven":
        for ext in (".hdr", ".exr"):
            p = os.path.join(root(), name + "_" + RES + ext)
            if os.path.isfile(p):
                return p
    return ""


# ---------------------------------------------------------------- catalogue

def _list_file():
    return os.path.join(root(), "assets.json")


def _load_list():
    path = _list_file()
    fresh = os.path.isfile(path) and time.time() - os.path.getmtime(path) < REFRESH_DAYS * 86400
    if _list["assets"] is None and os.path.isfile(path):
        try:
            with open(path, encoding="utf-8") as f:
                _list["assets"] = json.load(f)
        except (OSError, ValueError):
            _list["assets"] = None
    if not fresh and not _list["loading"]:
        _list["loading"] = True
        threading.Thread(target=_refresh_list, daemon=True).start()


def _refresh_list():
    from . import library
    try:
        data = json.loads(library._get(API + "/assets?type=hdris", timeout=60))
        out = []
        for aid, a in data.items():
            out.append({"id": aid, "name": a.get("name", aid), "categories": list(a.get("categories") or []),
                        "thumb": a.get("thumbnail_url", ""), "downloads": a.get("download_count", 0)})
        out.sort(key=lambda a: -a["downloads"])
        with open(_list_file() + ".part", "w", encoding="utf-8") as f:
            json.dump(out, f)
        os.replace(_list_file() + ".part", _list_file())
        _list["assets"] = out
        _list["error"] = ""
    except Exception as exc:
        _list["error"] = library.explain(exc)
    finally:
        _list["loading"] = False
    _start_thumbs()


def _thumb_path(aid):
    d = os.path.join(root(), "thumbs")
    os.makedirs(d, exist_ok=True)
    return os.path.join(d, aid.replace(":", "_") + ".png")


def _start_thumbs():
    from . import library
    with _lock:
        if _thumbs["running"] or not _list["assets"]:
            return
        _thumbs["running"] = True

    def run():
        try:
            for a in list(_list["assets"] or []):
                path = _thumb_path("polyhaven:" + a["id"])
                if os.path.isfile(path) or not a.get("thumb"):
                    continue
                small = a["thumb"].replace("width=256", "width=192").replace("height=256", "height=96")
                for url in (small.replace("format=webp", "format=png"), small):
                    try:
                        library._download(url, path, tries=1)
                        break
                    except Exception:
                        continue
        finally:
            _thumbs["running"] = False
    threading.Thread(target=run, daemon=True).start()


# the polyhaven categories shown as folders (first match)
FOLDERS = [("outdoor", "Esterni"), ("skies", "Cieli"), ("indoor", "Interni"), ("studio", "Studio"),
           ("urban", "Città"), ("nature", "Natura"), ("night", "Notte"), ("sunrise-sunset", "Alba e tramonto")]


def list_items(_data=None):
    """Blender HDRIs (offline) first, then Poly Haven."""
    from .i18n import tr
    _load_list()
    _start_thumbs()
    items = []
    for k, v in BLENDER_HDRIS:
        hid = "blender:" + k
        if not os.path.isfile(os.path.join(_blender_dir(), k + ".exr")):
            continue
        make_thumb(hid)                       # (main thread: made once, then a file)
        items.append({"id": hid, "name": tr(v), "folder": "Blender", "source": "blender", "downloaded": True,
                      "hasThumb": os.path.isfile(_thumb_path(hid))})
    for a in _list["assets"] or []:
        cats = set(a.get("categories") or [])
        folder = next((tr(v) for k, v in FOLDERS if k in cats), tr("Altro"))
        hid = "polyhaven:" + a["id"]
        items.append({"id": hid, "name": a["name"], "folder": folder, "source": "polyhaven",
                      "downloaded": bool(file_of(hid)), "hasThumb": os.path.isfile(_thumb_path(hid))})
    return {"items": items, "loading": _list["loading"], "error": _list["error"],
            "credit": "Poly Haven (polyhaven.com) · CC0 — Blender studio lights"}


def thumb_file(hid):
    """Thumbnail PNG of an HDRI, if there is one (any thread)."""
    path = _thumb_path(hid or "")
    return path if os.path.isfile(path) else None


def make_thumb(hid):
    """Thumbnail of a Blender HDRI, made once from the picture (main thread)."""
    path = _thumb_path(hid or "")
    if os.path.isfile(path):
        return path
    if (hid or "").startswith("blender:") and file_of(hid):
        try:
            _make_thumb(file_of(hid), path)
            return path
        except Exception as exc:          # unreadable: no thumbnail
            print("SIMPLER_HDRI thumb", hid, exc, flush=True)
    return None


def _make_thumb(src, dst, w=192, h=96):
    import bpy
    import numpy as np
    im = bpy.data.images.load(src, check_existing=False)
    try:
        W, H = im.size
        px = np.empty(W * H * 4, dtype=np.float32)
        im.pixels.foreach_get(px)
    finally:
        bpy.data.images.remove(im)
    a = px.reshape(H, W, 4)[:, :, :3]
    ys = (np.arange(h) * H // h); xs = (np.arange(w) * W // w)
    small = a[ys][:, xs]
    small = small / (1.0 + small)                      # simple tone map
    small = np.clip(small ** (1 / 2.2), 0, 1)
    out = bpy.data.images.new("simpler_hdri_thumb", w, h, alpha=True)
    try:
        rgba = np.concatenate([small, np.ones((h, w, 1), dtype=np.float32)], axis=2)
        out.pixels.foreach_set(rgba.astype(np.float32).ravel())
        out.filepath_raw = dst
        out.file_format = "PNG"
        out.save()
    finally:
        bpy.data.images.remove(out)


# ---------------------------------------------------------------- download

def download(data):
    from . import library
    hid = data.get("id") or ""
    if file_of(hid):
        return {"id": hid, "state": "done", "fraction": 1.0}
    src, _, aid = hid.partition(":")
    aid = os.path.basename(aid)
    if src != "polyhaven" or not aid:
        return {"id": hid, "state": "error", "error": "id"}
    with _lock:
        job = _jobs.get(hid)
        library._watchdog(job)
        if job and job["state"] == "running":
            return status({"id": hid})
        _jobs[hid] = {"state": "running", "done": 0, "total": 0, "error": "", "started": time.time(), "seen": time.time()}

    def advance(n):
        with _lock:
            _jobs[hid]["done"] += n
            _jobs[hid]["seen"] = time.time()

    def run():
        try:
            files = json.loads(library._get(f"{API}/files/{aid}"))
            by_res = (files.get("hdri") or {})
            pick = None
            for res in (RES, "2k", "8k", "1k"):
                fmts = by_res.get(res) or {}
                for fmt in ("hdr", "exr"):
                    if isinstance(fmts.get(fmt), dict) and fmts[fmt].get("url"):
                        pick = (fmts[fmt]["url"], fmt, fmts[fmt].get("size", 0))
                        break
                if pick:
                    break
            if not pick:
                raise RuntimeError("no hdri file")
            with _lock:
                _jobs[hid]["total"] = max(1, pick[2])
            path = os.path.join(root(), f"{aid}_{RES}.{pick[1]}")
            library._download(pick[0], path, advance, timeout=60)
            with _lock:
                _jobs[hid]["state"] = "done"
        except Exception as exc:
            with _lock:
                _jobs[hid].update(state="error", error=str(exc) if isinstance(exc, RuntimeError) else library.explain(exc))
    threading.Thread(target=run, daemon=True).start()
    return status({"id": hid})


def status(data):
    from . import library
    hid = data.get("id") or ""
    if file_of(hid):
        return {"id": hid, "state": "done", "fraction": 1.0}
    with _lock:
        job = _jobs.get(hid)
        library._watchdog(job)
        job = dict(job or {"state": "none", "done": 0, "total": 0, "error": ""})
    job["id"] = hid
    job["fraction"] = job["done"] / job["total"] if job.get("total") else None
    return job


# ---------------------------------------------------------------- measurement of the picture

ANALYSIS_REV = 2


def tex_dir(u, v):
    """Direction (texture space, Z up) of a point of the equirectangular picture (u right, v up, 0..1), as the
    Environment Texture of Cycles maps it."""
    phi = (0.5 - u) * 2.0 * math.pi
    theta = (v - 0.5) * math.pi
    return (math.cos(theta) * math.cos(phi), math.cos(theta) * math.sin(phi), math.sin(theta))


def analyze(path):
    """Sun (direction in texture space, RGB irradiance, size), threshold, sky light on the ground, horizon colour.
    Cached in <file>.simpler.json."""
    cache = path + ".simpler.json"
    try:
        if os.path.getmtime(cache) >= os.path.getmtime(path):
            with open(cache, encoding="utf-8") as f:
                a = json.load(f)
            if a.get("rev") == ANALYSIS_REV:
                return a
    except (OSError, ValueError):
        pass
    import bpy
    import numpy as np
    im = bpy.data.images.load(path, check_existing=False)
    try:
        W, H = im.size
        px = np.empty(W * H * 4, dtype=np.float32)
        im.pixels.foreach_get(px)
    finally:
        bpy.data.images.remove(im)
    img = px.reshape(H, W, 4)[:, :, :3].astype(np.float64)    # row 0 = bottom (v = 0)
    img = np.nan_to_num(img, nan=0.0, posinf=0.0, neginf=0.0)
    # a working copy at most 2048 wide: sums of energy are kept (block means x block solid angles)
    f = max(1, W // 2048)
    if f > 1:
        Hs, Ws = H // f, W // f
        img = img[:Hs * f, :Ws * f].reshape(Hs, f, Ws, f, 3).mean(axis=(1, 3))
        H, W = Hs, Ws
    Y = 0.2126 * img[:, :, 0] + 0.7152 * img[:, :, 1] + 0.0722 * img[:, :, 2]
    v = (np.arange(H) + 0.5) / H
    u = (np.arange(W) + 0.5) / W
    theta = (v - 0.5) * np.pi                     # elevation
    domega = (2 * np.pi / W) * (np.pi / H) * np.cos(theta)          # solid angle of a pixel, per row
    up = theta > 0
    # sky light on a horizontal ground (upper half, cosine-weighted)
    e_ground = float((Y[up] * (domega[up] * np.sin(theta[up]))[:, None]).sum())
    # threshold: what is far brighter than the sky
    sky = Y[up].ravel() if up.any() else Y.ravel()
    p99 = float(np.percentile(sky, 99.0))
    ymax = float(Y.max())
    out = {"rev": ANALYSIS_REV, "w": W * f, "h": H * f, "groundIrradiance": e_ground, "sun": None,
           "threshold": 0.0, "p99": p99, "ymax": ymax}
    # colour of the horizon (a band just above it), for the haze and the real-time view
    band = (theta > math.radians(1)) & (theta < math.radians(8))
    if band.any():
        out["horizon"] = [float(x) for x in img[band].reshape(-1, 3).mean(axis=0)]
    if ymax > 60.0 * max(p99, 1e-6):              # a real sun: a spot much brighter than 99% of the sky
        T = math.sqrt(ymax * max(p99, 1e-6)) * 0.5
        T = max(T, 8.0 * p99)
        j, i = np.unravel_index(int(np.argmax(Y)), Y.shape)
        c = np.array(tex_dir(u[i], v[j]))
        # pixels above the threshold within 12° of the brightest point
        cosr = math.cos(math.radians(12))
        ph = (0.5 - u) * 2 * np.pi
        dx = np.cos(theta)[:, None] * np.cos(ph)[None, :]
        dy = np.cos(theta)[:, None] * np.sin(ph)[None, :]
        dz = np.repeat(np.sin(theta)[:, None], W, axis=1)
        near = (dx * c[0] + dy * c[1] + dz * c[2]) > cosr
        mask = near & (Y > T)
        if mask.any():
            k = np.where(mask, 1.0 - T / np.maximum(Y, 1e-9), 0.0)      # the share above the threshold goes to the Sun
            w_ = k * domega[:, None]
            e_rgb = [float((img[:, :, ch] * w_).sum()) for ch in range(3)]
            wy = Y * w_
            d = np.array([float((dx * wy).sum()), float((dy * wy).sum()), float((dz * wy).sum())])
            d /= max(1e-9, float(np.linalg.norm(d)))
            area = float((mask * domega[:, None]).sum())
            size = 2.0 * math.degrees(math.sqrt(max(area, 1e-8) / math.pi))  # angular diameter of the spot
            out["sun"] = {"dir": [float(x) for x in d], "rgb": e_rgb, "size": max(0.3, min(6.0, size))}
            out["threshold"] = T
    try:
        with open(cache, "w", encoding="utf-8") as f:
            json.dump(out, f)
    except OSError:
        pass
    return out


def world_dir(tex_d, rotation_deg):
    """Texture-space direction → scene direction: the Mapping node turns the lookup vector by +rotation about Z,
    so what the picture has at tex_d is seen at Rz(-rotation)·tex_d."""
    r = -math.radians(rotation_deg)
    x, y, z = tex_d
    return (x * math.cos(r) - y * math.sin(r), x * math.sin(r) + y * math.cos(r), z)


# ---------------------------------------------------------------- the world

def build_world(w, path, rotation_deg, strength, threshold):
    """World nodes: picture (rotated); for every ray but the camera's, clamped at the threshold (its sun is the Sun
    light). The camera sees the picture as photographed."""
    import bpy
    nt = w.node_tree
    nt.nodes.clear()
    N, L = nt.nodes, nt.links
    out = N.new("ShaderNodeOutputWorld")
    bg = N.new("ShaderNodeBackground")
    bg.inputs[1].default_value = float(strength)
    tc = N.new("ShaderNodeTexCoord")
    mp = N.new("ShaderNodeMapping")
    mp.inputs["Rotation"].default_value = (0.0, 0.0, math.radians(rotation_deg))
    L.new(tc.outputs["Generated"], mp.inputs["Vector"])
    env = N.new("ShaderNodeTexEnvironment")
    env.name = "hdri"
    img = bpy.data.images.load(path, check_existing=True)
    env.image = img
    L.new(mp.outputs[0], env.inputs["Vector"])
    color = env.outputs["Color"]
    if threshold > 0:
        bw = N.new("ShaderNodeRGBToBW")
        L.new(color, bw.inputs[0])
        mx = N.new("ShaderNodeMath"); mx.operation = "MAXIMUM"; mx.inputs[1].default_value = threshold
        L.new(bw.outputs[0], mx.inputs[0])
        k = N.new("ShaderNodeMath"); k.operation = "DIVIDE"; k.inputs[0].default_value = threshold
        L.new(mx.outputs[0], k.inputs[1])
        cl = N.new("ShaderNodeVectorMath"); cl.operation = "SCALE"
        L.new(color, cl.inputs[0]); L.new(k.outputs[0], cl.inputs["Scale"])
        lp = N.new("ShaderNodeLightPath")
        mix = N.new("ShaderNodeMix"); mix.data_type = "RGBA"; mix.name = "simpler_camera_mix"
        L.new(lp.outputs["Is Camera Ray"], mix.inputs[0])
        L.new(cl.outputs[0], mix.inputs[6]); L.new(color, mix.inputs[7])
        color = mix.outputs[2]
    L.new(color, bg.inputs[0])
    L.new(bg.outputs[0], out.inputs[0])
    w["simpler_env"] = "hdri"
