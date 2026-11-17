"""Path-traced material previews (a sphere on a studio backdrop), rendered by a second Blender that stays open
(preview_job.py), so the engine's path tracing view is never disturbed.

- Library thumbnails: cached on disk by material id and revision (a saved material gets a new picture).
- Live preview of the material editor: re-rendered after every change; only the latest request is kept, so dragging
  a slider never queues a long line of renders.
The engine only writes the material into a small .blend (bpy.data.libraries.write, a fraction of a second) and goes
back to work; the preview process loads it, renders and answers.
"""
import itertools
import json
import os
import subprocess
import tempfile
import threading
import time

import bpy

from . import fullspeed
from . import materials, render
from . import tempdirs

PREVIEW_VERSION = 2          # bump when the preview set-up changes: old cached images are ignored
THUMB_SIZE = 160
LIVE_SIZE = 256
SCENE_NAME = "Simpler Preview"     # (older versions rendered previews in a scene inside the project)

_lock = threading.Lock()
_cond = threading.Condition(_lock)
_state = {"proc": None, "thread": None, "pending": {}, "results": {}, "stop": False}
_ids = itertools.count(1)
_dir = tempdirs.make("simpler_preview_")


def _exe():
    exe = os.environ.get("SIMPLER_RENDER_EXE") or bpy.app.binary_path
    return exe if exe and os.path.isfile(exe) else None


def _start():
    """The preview Blender, started on first use (CPU threads and priority kept low)."""
    proc = _state["proc"]
    if proc is not None and proc.poll() is None:
        return proc
    exe = _exe()
    if exe is None:
        return None
    script = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "preview_job.py")
    flags = (0x08000000 | 0x00004000) if os.name == "nt" else 0   # no window, below normal priority
    proc = fullspeed.popen([exe, "--factory-startup", "-t", str(max(1, render.cpu_threads() // 2)), "-b", "--python", script,
                             "--", render.STATE.device], stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                            text=True, encoding="utf-8", errors="replace", creationflags=flags, bufsize=1)
    for line in proc.stdout:              # wait until its scene is ready
        if line.startswith("SIMPLER_PREVIEW_READY"):
            break
    _state["proc"] = proc
    return proc


IDLE_QUIT_S = 45        # the preview Blender closes after this long without work: its video memory goes back to zero


def _quit_idle():
    """Closes the preview process (called with no work pending). Started again, in ~2 s, by the next request."""
    proc = _state["proc"]
    _state["proc"] = None
    if proc is None or proc.poll() is not None:
        return
    try:
        proc.stdin.write("quit\n")
        proc.stdin.flush()
        proc.wait(timeout=10)
    except Exception:
        try:
            proc.kill()
        except OSError:
            pass


def _worker():
    while True:
        with _cond:
            while not _state["pending"] and not _state["stop"]:
                proc = _state["proc"]
                if proc is not None and proc.poll() is None:
                    if not _cond.wait(timeout=IDLE_QUIT_S) and not _state["pending"] and not _state["stop"]:
                        _quit_idle()
                else:
                    _cond.wait()
            if _state["stop"]:
                return
            # the oldest request of each kind goes first; "live" keeps only its latest
            key = next(iter(_state["pending"]))
            job = _state["pending"].pop(key)
        result = {"state": "error", "path": "", "error": ""}
        try:
            proc = _start()
            if proc is None:
                raise RuntimeError("no Blender for previews")
            proc.stdin.write(json.dumps({k: v for k, v in job.items() if k != "id"}) + "\n")
            proc.stdin.flush()
            for line in proc.stdout:
                if line.startswith("SIMPLER_PREVIEW_PROGRESS"):
                    parts = line[len("SIMPLER_PREVIEW_PROGRESS"):].strip("\n").lstrip().split("\t")
                    try:
                        with _cond:
                            _state["results"][job["id"]] = dict(_state["results"].get(job["id"]) or {}, state="running",
                                                                done=int(parts[0]), total=int(parts[1]),
                                                                current=parts[2] if len(parts) > 2 else "")
                    except (ValueError, IndexError):
                        pass
                    continue
                if line.startswith("SIMPLER_PREVIEW_DONE"):
                    result = {"state": "done", "path": job["out"], "error": ""}
                    break
                if line.startswith("SIMPLER_PREVIEW_ERROR"):
                    result = {"state": "error", "path": "", "error": line[22:].strip()}
                    break
            else:
                _state["proc"] = None          # the process ended: started again next time
                result["error"] = "preview process ended"
        except Exception as exc:
            result["error"] = str(exc)
            _state["proc"] = None
        finally:
            if not job.get("keepSource"):
                try:
                    os.remove(job["blend"])
                except OSError:
                    pass
        if result.get("state") == "error":
            try:
                from .core import log
                log("SIMPLER_PREVIEW", job.get("kind", "material"), "failed:", (result.get("error") or "")[-400:])
            except Exception:
                pass
        with _cond:
            _state["results"][job["id"]] = result
            _cond.notify_all()


PREVIEW_MAX_CM = 200.0      # (1.76.56) a projected texture larger than this is shown whole on the sphere (1 m)


def _preview_size(tmp):
    """(1.76.56, Luca: «la scala ho dovuto metterla a 12000 … così l'anteprima diventa irriconoscibile») a texture
    projected at tens of metres (an aerial or cliff photo: 50-120 m) showed a blurred patch of a few pixels of it on the
    1 m sphere: the copy for the preview gets it at 1 m - the whole picture, as a library thumbnail - and the other
    sizes of the material with it (large texture, grunge, displacement height). The material itself does not change."""
    import copy
    from . import matedit
    p = matedit.params_of(tmp)
    uv = (p or {}).get("uv") or {}
    size = float(uv.get("sizeCm") or 100.0)
    if not p or uv.get("mode", "uv") == "uv" or size <= PREVIEW_MAX_CM:
        return
    f = 100.0 / size
    q = copy.deepcopy(p)
    q["uv"]["sizeCm"] = 100.0
    for k in ("macro", "grunge"):
        if isinstance(q.get(k), dict) and q[k].get("sizeCm"):
            q[k]["sizeCm"] = max(1.0, float(q[k]["sizeCm"]) * f)
    if isinstance(q.get("displacement"), dict) and q["displacement"].get("heightCm"):
        q["displacement"]["heightCm"] = float(q["displacement"]["heightCm"]) * f
    q.pop("blend", None)
    matedit._Builder(tmp, matedit._merge(matedit.DEFAULTS, q)).build()


def _write_light(mat, blend):
    """A copy of the material whose textures are the reduced copies (1024 px) instead of big or packed originals:
    the file is small, written in a moment, and the preview process loads it fast."""
    from . import proxies
    from . import matedit
    matedit.flush_pending([mat])            # (1.76.56: its tree, if it was left for later)
    tmp = mat.copy()                        # (the preview process takes the only material of the file)
    before = set(bpy.data.images)
    try:
        _preview_size(tmp)
        if tmp.node_tree is not None:
            for node in tmp.node_tree.nodes:
                im = getattr(node, "image", None)
                if im is None or node.type not in ("TEX_IMAGE", "TEX_ENVIRONMENT"):
                    continue
                orig = bpy.data.images.get(node.get("simpler_orig") or "") or im
                if orig.source not in ("FILE", "TILED"):
                    continue
                path = proxies.file_for(orig, 1024)
                if path and (orig.packed_file is not None or os.path.normcase(path) != os.path.normcase(bpy.path.abspath(orig.filepath))):
                    small = bpy.data.images.load(path, check_existing=True)
                    try:
                        small.colorspace_settings.name = orig.colorspace_settings.name
                    except TypeError:
                        pass
                    small.alpha_mode = orig.alpha_mode
                    node.image = small
        bpy.data.libraries.write(blend, {tmp}, fake_user=True, path_remap="ABSOLUTE", compress=False)
    finally:
        bpy.data.materials.remove(tmp)
        for im in set(bpy.data.images) - before:
            if im.users == 0:
                bpy.data.images.remove(im)


def _enqueue(mat, out, key, size, samples):
    """Writes the material to a small .blend (main thread) and queues the render. Returns the request id."""
    rid = next(_ids)
    blend = os.path.join(_dir, f"m{rid}.blend")
    _write_light(mat, blend)
    with _cond:
        old = _state["pending"].pop(key, None)
        if old is not None:                    # superseded: its file is not needed any more
            _state["results"][old["id"]] = {"state": "superseded", "path": "", "error": ""}
            try:
                os.remove(old["blend"])
            except OSError:
                pass
        _state["pending"][key] = {"id": rid, "blend": blend, "material": mat.name, "out": out, "size": size, "samples": samples}
        _state["results"][rid] = {"state": "running", "path": "", "error": ""}
        if _state["thread"] is None or not _state["thread"].is_alive():
            _state["thread"] = threading.Thread(target=_worker, daemon=True)
            _state["thread"].start()
        _cond.notify_all()
    return rid


def work_dir():
    return _dir


def enqueue_model(blend, save, textures, out, key, keep=None, keep_source=False, keep_tops=None, scale=1.0, orient=None, info=None):
    """A model saved to the library: the preview process copies its textures next to it, writes save (relative
    paths) and renders the thumbnail (out). blend: the objects as written by the engine (removed when done)."""
    rid = next(_ids)
    with _cond:
        _state["pending"][key] = {"id": rid, "kind": "model", "blend": blend, "save": save, "textures": textures,
                                  "out": out, "size": 256, "samples": 64, "keep": list(keep or []), "keepSource": keep_source,
                                  "keepTops": list(keep_tops or []), "scale": float(scale or 1.0),
                                  "orient": orient, "info": info}
        _state["results"][rid] = {"state": "running", "path": "", "error": ""}
        if _state["thread"] is None or not _state["thread"].is_alive():
            _state["thread"] = threading.Thread(target=_worker, daemon=True)
            _state["thread"].start()
        _cond.notify_all()
    return rid


def enqueue_probe(path, out, key):
    """The size of a model file, measured by the preview process before the import (models.probe)."""
    rid = next(_ids)
    with _cond:
        _state["pending"][key] = {"id": rid, "kind": "probe", "path": path, "out": out, "keepSource": True, "blend": ""}
        _state["results"][rid] = {"state": "running", "path": "", "error": ""}
        if _state["thread"] is None or not _state["thread"].is_alive():
            _state["thread"] = threading.Thread(target=_worker, daemon=True)
            _state["thread"].start()
        _cond.notify_all()
    return rid


def enqueue_import(path, save, textures, out, info, key, split=False, pivot="keep", parts_dir="", base_id="", entry=None, scale=1.0, merge=False):
    """A model file imported into the library by the preview process (the user's scene is not touched).
    split: every top object of the file becomes a library model of its own (collections); pivot: base|center|keep."""
    rid = next(_ids)
    with _cond:
        _state["pending"][key] = {"id": rid, "kind": "import", "path": path, "save": save, "textures": textures,
                                  "out": out, "info": info, "size": 256, "samples": 64, "keepSource": True, "blend": "",
                                  "split": bool(split), "pivot": pivot or "keep", "partsDir": parts_dir, "baseId": base_id,
                                  "entry": entry or {}, "scale": float(scale or 1.0), "merge": bool(merge)}
        _state["results"][rid] = {"state": "running", "path": "", "error": ""}
        if _state["thread"] is None or not _state["thread"].is_alive():
            _state["thread"] = threading.Thread(target=_worker, daemon=True)
            _state["thread"].start()
        _cond.notify_all()
    return rid


def enqueue_sky(blend, out, w, h, samples=4):
    """A 360° picture of the sky for the real-time view (the latest request only: older ones are dropped)."""
    rid = next(_ids)
    with _cond:
        old = _state["pending"].pop("sky", None)
        if old is not None:
            _state["results"][old["id"]] = {"state": "superseded", "path": "", "error": ""}
            try:
                os.remove(old["blend"])
            except OSError:
                pass
        _state["pending"]["sky"] = {"id": rid, "kind": "sky", "blend": blend, "out": out, "w": w, "h": h, "samples": samples,
                                    "size": w}
        _state["results"][rid] = {"state": "running", "path": "", "error": ""}
        if _state["thread"] is None or not _state["thread"].is_alive():
            _state["thread"] = threading.Thread(target=_worker, daemon=True)
            _state["thread"].start()
        _cond.notify_all()
    return rid


def enqueue_eco(blend, out, show, center, size, light, px=384, samples=96):
    """The thumbnail of an ecosystem, path traced on its test plot (ecosystems.save): the camera sees only the plot,
    from a little above, as close as it can without showing its edges."""
    rid = next(_ids)
    with _cond:
        _state["pending"]["eco:" + out] = {"id": rid, "kind": "eco", "blend": blend, "out": out, "show": list(show),
                                           "center": list(center), "plot": float(size), "light": light,
                                           "size": int(px), "samples": int(samples)}
        _state["results"][rid] = {"state": "running", "path": "", "error": ""}
        if _state["thread"] is None or not _state["thread"].is_alive():
            _state["thread"] = threading.Thread(target=_worker, daemon=True)
            _state["thread"].start()
        _cond.notify_all()
    return rid


def status(data):
    """GET material/preview/status?id= (answered at once, no Blender data)."""
    rid = int(data.get("id") or 0)
    with _lock:
        r = dict(_state["results"].get(rid) or {"state": "unknown", "path": "", "error": ""})
    r["id"] = rid
    return r


def wait(rid, timeout=600):
    t0 = time.time()
    with _cond:
        while _state["results"].get(rid, {}).get("state") == "running" and time.time() - t0 < timeout:
            _cond.wait(0.5)
        return dict(_state["results"].get(rid) or {})


def material_preview(data):
    """Thumbnail of a library material (cached by id and revision). data: {id, folder, wait}.
    Returns {path, cached} when ready, or {pending: request id} (GET material/preview/status tells when)."""
    from .core import ApiError
    from .i18n import tr
    mid = data.get("id", "")
    folder = data.get("folder", "")
    entry = materials.library_entry(mid)
    if entry is None:
        raise ApiError(tr("Materiale sconosciuto: {0}", mid))
    os.makedirs(folder, exist_ok=True)
    # (1.76.56: a texture of tens of metres shown whole - a new name for those thumbnails only, the others stay)
    prm = ((materials._user_entries().get(mid) or {}).get("params") or {}) if entry.get("user") else {}
    uv = prm.get("uv") or {}
    big = uv.get("mode", "uv") != "uv" and float(uv.get("sizeCm") or 100.0) > PREVIEW_MAX_CM
    # (1.79.0, Luca: «la sfera non fa capire nulla») an «Interni» material: its room through a window (preview_job), a
    # name of its own so the sphere made before is not kept
    room = bool((prm.get("interior") or {}).get("enabled"))
    path = os.path.join(folder, f"{mid}_{entry['rev']}_v{PREVIEW_VERSION}{'w' if big else ''}{'i' if room else ''}.png")
    if os.path.isfile(path) and os.path.getsize(path) > 0:
        return {"path": path, "cached": True}
    if big:
        try:
            os.remove(os.path.join(folder, f"{mid}_{entry['rev']}_v{PREVIEW_VERSION}.png"))    # (the thumbnail of before)
        except OSError:
            pass
    existed = {m.name for m in bpy.data.materials}
    mat = materials.get_or_create(mid, fresh=True)   # (the library's version, not the project's copy with its edits)
    try:
        rid = _enqueue(mat, path, "thumb:" + mid, THUMB_SIZE, 96)
    finally:
        if mat.name not in existed and mat.users == 0:
            bpy.data.materials.remove(mat)   # don't leave unused library materials in the project
    if data.get("wait"):
        r = wait(rid)
        if r.get("state") != "done":
            raise ApiError(r.get("error") or tr("Anteprima non riuscita"))
        return {"path": path, "cached": False}
    return {"pending": rid}


def live_preview(data):
    """POST material/livepreview {name}: the material as it is now, on the preview sphere."""
    from .core import ApiError
    from .i18n import tr
    mat = bpy.data.materials.get(data.get("name") or "")
    if mat is None:
        raise ApiError(tr("Materiale non trovato"))
    out = os.path.join(_dir, f"live_{next(_ids)}.png")
    rid = _enqueue(mat, out, "live", int(data.get("size") or LIVE_SIZE), int(data.get("samples") or 48))
    return {"id": rid}


def stop():
    with _cond:
        _state["stop"] = True
        _cond.notify_all()
    proc = _state["proc"]
    if proc is not None and proc.poll() is None:
        try:
            proc.stdin.write("quit\n")
            proc.stdin.flush()
        except OSError:
            pass
        try:
            proc.kill()
        except OSError:
            pass


def remove_preview_scene():
    """Projects saved by older versions may contain the preview scene: it never goes into the user's file."""
    scene = bpy.data.scenes.get(SCENE_NAME)
    if scene is None:
        return
    for ob in list(scene.objects):
        data = ob.data
        bpy.data.objects.remove(ob, do_unlink=True)
        if data is not None and data.users == 0:
            if isinstance(data, bpy.types.Mesh):
                bpy.data.meshes.remove(data)
            elif isinstance(data, bpy.types.Light):
                bpy.data.lights.remove(data)
            elif isinstance(data, bpy.types.Camera):
                bpy.data.cameras.remove(data)
    if scene.world and scene.world.name.startswith("Simpler Preview"):
        w = scene.world
        scene.world = None
        bpy.data.worlds.remove(w)
    m = bpy.data.materials.get("Simpler Preview Floor")
    if m is not None and m.users == 0:
        bpy.data.materials.remove(m)
    bpy.data.scenes.remove(scene)
