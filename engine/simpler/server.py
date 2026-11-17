"""Local JSON API (127.0.0.1) + main loop.

Blender's API is not thread-safe: HTTP requests are parsed on a worker thread and
queued; the main thread executes them between progressive viewport passes.
"""
import json
import os
import queue
import threading
import time
import traceback
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

import bpy

from . import fullspeed
from . import VERSION, camview, decimate, memory, terrain, merge, libupdate, rain, acgdecals, decals, ecosystems, night, libstats, matbulk, ambience, breaker, core, hdri, history, importer, library, matedit, materials, models, paint, paths, phmodels, previews, progress, proxies, render, scene_ops, skyphoto, snow, textures, trash, videoframes, views
from .core import ApiError
from .i18n import tr


# ---------------------------------------------------------------- project files

PROJECT_KEY = "simpler_project"        # options saved in the project: {"backup": bool}


def project_options(data=None):
    """GET/POST /api/project/options {backup}: options of this project (saved with it)."""
    scene = bpy.context.scene
    try:
        opts = json.loads(scene.get(PROJECT_KEY, "{}"))
    except (TypeError, ValueError):
        opts = {}
    opts.setdefault("backup", True)            # (Blender always kept one copy, .simpler1: the default stays so)
    opts.setdefault("copyTextures", True)      # (1.68.2: the textures from outside travel with the project)
    changed = False
    for k in ("backup", "copyTextures"):
        if data and k in data:
            opts[k] = bool(data[k])
            changed = True
    if changed:
        scene[PROJECT_KEY] = json.dumps(opts)
    return opts


def _write_project(path, copy=False, keep_backup=False, collect=False):
    scene = bpy.context.scene
    scene["simpler_settings"] = json.dumps({"camera": render.STATE.camera, "quality": render.STATE.quality,
                                            "config": render.STATE.config,
                                            "caustics": render.STATE.caustics, "settingsVersion": 2})
    previews.remove_preview_scene()
    fp = bpy.context.preferences.filepaths
    old_versions = fp.save_version
    # one backup at most: Blender keeps the previous file as "<name>.simpler1" before writing (save_version = 1)
    fp.save_version = 1 if keep_backup else 0
    try:
        # A .simpler project is a Blender file; textures stay where they are (relative paths).
        # deleted objects kept only for undo are not saved; textures saved with their original files
        with trash.excluded(), proxies.originals(), snow.aside():
            if collect:
                from . import projtex
                try:
                    projtex.collect(path)   # pictures from Downloads & co. copied next to the project (1.68.2)
                except OSError as exc:      # (a full disk: the project is saved anyway, pointing where it did)
                    core.log("SIMPLER_PROJTEX", "copy failed:", exc)
            paths.tag_images()          # library / download textures remember their place, not the folder
            bpy.ops.wm.save_as_mainfile(filepath=path, check_existing=False, relative_remap=True, compress=True, copy=copy)
    finally:
        fp.save_version = old_versions


def project_save(data):
    path = data.get("path", "")
    if not path:
        raise ApiError(tr("Percorso mancante"))
    if not path.lower().endswith(".simpler"):
        path += ".simpler"
    opts = project_options()
    _write_project(path, keep_backup=bool(opts.get("backup", True)), collect=bool(opts.get("copyTextures", True)))
    auto = autosave_path(path)
    if os.path.isfile(auto):
        try:
            os.remove(auto)                   # (saved for real: the automatic copy is not needed any more)
        except OSError:
            pass
    from . import projfiles
    try:
        trash_list = projfiles.after_save(path)  # (1.76.7) the files of its folders it no longer uses: to the Recycle Bin
    except Exception as exc:
        core.log("SIMPLER_PROJFILES", "check failed:", exc)
        trash_list = []
    return {"path": path, "trash": trash_list}


def autosave_path(project_path):
    """<folder>/<name>.autosave.simpler next to the project; a scene never saved: in the app data folder."""
    if project_path:
        base = project_path[:-8] if project_path.lower().endswith(".simpler") else project_path
        return base + ".autosave.simpler"
    from .models import user_dir
    d = os.path.join(os.path.dirname(user_dir()), "autosave")
    os.makedirs(d, exist_ok=True)
    return os.path.join(d, "Nuova scena.autosave.simpler")


def project_autosave(data):
    """POST /api/autosave {project}: a copy of the scene next to the project (the project file is not touched),
    only when something changed since the last copy."""
    if CHANGES["n"] == CHANGES["saved"] or CHANGES.get("autosaved") == CHANGES["n"]:
        return {"saved": False}
    path = autosave_path(data.get("project") or "")
    t0 = time.time()
    _write_project(path, copy=True, keep_backup=False)
    CHANGES["autosaved"] = CHANGES["n"]
    core.log("SIMPLER_AUTOSAVE", path, f"{time.time() - t0:.1f}s")
    return {"saved": True, "path": path}


def autosave_info(data):
    """GET /api/autosave/info?project=: is there an automatic copy newer than the project?"""
    path = autosave_path((data or {}).get("project") or "")
    if not os.path.isfile(path):
        return {"exists": False}
    proj = (data or {}).get("project") or ""
    newer = not proj or not os.path.isfile(proj) or os.path.getmtime(path) > os.path.getmtime(proj)
    return {"exists": True, "newer": newer, "path": path, "when": time.strftime("%d/%m %H:%M", time.localtime(os.path.getmtime(path)))}


def autosave_discard(data):
    path = autosave_path((data or {}).get("project") or "")
    if os.path.isfile(path):
        os.remove(path)
    return {}


def project_open(data):
    path = data.get("path", "")
    if not os.path.isfile(path):
        raise ApiError(tr("Progetto non trovato"))
    history.reset()
    t0 = time.time()
    size = os.path.getsize(path)
    bpy.ops.wm.open_mainfile(filepath=path, load_ui=False)
    matedit.sanitize_displacement()   # (a project saved with a too heavy remesh must not fill the memory again)
    t1 = time.time()
    moved = paths.remap_images()      # libraries moved since the project was saved: textures from their new folder
    if moved:
        core.log("SIMPLER_PATHS", f"{moved} textures taken from the current library folders")
    render.setup_device()
    render.STATE.meter_ev, render.STATE.meter_epoch = None, -1     # (the measurement of the framing: of this scene)
    saved = bpy.context.scene.get("simpler_settings")
    has_view = False
    if saved:
        s = json.loads(saved)
        has_view = bool(s.get("camera"))
        render.STATE.camera.update(s.get("camera", {}))
        render.STATE.quality = s.get("quality", "alta")
        render.STATE.config = render.default_config("alta")
        cfg = {k: v for k, v in s.get("config", {}).items() if k in render.CONFIG_KEYS}
        if s.get("settingsVersion", 1) < 2:
            cfg.pop("textureLimit", None)     # before 1.1.3 "full textures" was only the default: now automatic
        cfg.setdefault("meterExposure", False)   # (1.79.0) projects made before: their exposure as it was
        render.STATE.config.update(cfg)
        render.apply_caustics(bool(s.get("caustics", False)))
    render.far_clip()             # (1.76.20) a project saved with the old far clip of the camera (1 km)
    scene_ops.close_models()      # (a model left open for its parts is drawn from its prototype again)
    scene_ops.repair_decals()     # (decals hidden inside a library model by 1.28.0-1.28.6)
    matedit.upgrade_alpha()       # projects before 1.3.3: see-through textures get the clean cut-out
    matedit.upgrade_graded()      # before 1.14.4: graded opacity maps (frosted glass, lamp shades) cut into speckles
    matedit.upgrade_uv_offset()   # before 1.32.1: UV offset different between the view and the path tracing
    decals.upgrade()              # before 1.36.3: decals not cut to their box (copies faded in path tracing)
    try:
        decals.report()               # (diagnosis: decals not seen in the real-time view)
    except Exception as exc:
        core.log("SIMPLER_DECAL", "report failed:", exc)
    ecosystems.upgrade()          # 1.38.0: ecosystems beside their object, not its children
    snow.HIDE["on"] = False       # («Nascondi la neve» is not kept: a project opens with its snow)
    rain.PAUSE["on"] = False      # (nor «Ferma i ricalcoli»)
    rain.after_open()             # the rain made fresh for this session (see rain.after_open)
    gone = paint.purge_orphans()  # models of distributions deleted long ago, still in the project (before 1.37.1)
    try:
        for m, sub, deg in models.sync_orientation():   # turned in the library while another project was open
            core.log("SIMPLER_ORIENT", f"distribution model {m} ({sub}) turned {deg} degrees to match the library")
    except Exception as exc:
        core.log("SIMPLER_ORIENT", "failed:", exc)
    if gone:
        core.log("SIMPLER_PAINT", f"{gone} collections of deleted distributions removed")
    conv = paint.convert_all().get("converted", 0)   # distributions painted before 1.8: as points
    if conv:
        core.log("SIMPLER_PAINT", f"{conv} distributions converted to points")
        trash.purge_all()
    history.reset()
    decimate.after_open()         # (the meshes kept for Ctrl+Z of «Ottimizza poligoni» when the project was saved)
    terrain.after_open()          # (1.76.1: no cut-out on the materials of a terrain)
    # what the file brought and nothing uses (the objects of a distribution deleted long ago, the textures of a
    # model deleted while it waited for undo when the project was saved): out of memory at once - before, «Libera
    # memoria» right after opening found 6 objects, 23 materials and 57 textures (70 MB) in a project of Luca
    try:
        memory.purge()
    except Exception as exc:
        core.log("SIMPLER_PURGE", "after open failed:", exc)
    t2 = time.time()
    # textures not where they were (a picture from Downloads deleted, a folder moved): looked for, the others unplugged
    # (the material keeps its name and settings) and listed for the app (1.68.2)
    missing_tex, empty_tex = [], []
    try:
        from . import projtex, textures
        textures.LAST_EMPTY.clear()
        _found, missing_tex = projtex.check_missing(path, data.get("textureFolders") or [])
        empty_tex = list(textures.LAST_EMPTY)
    except Exception as exc:
        core.log("SIMPLER_PROJTEX", "check at opening failed:", exc)
    render.warm_texture_cache()   # reduced textures for the previews, in the background (cached: instant next time)
    try:
        from . import diskcache
        from . import libstats
        # (1.76.49: the caches of terrains and models within their limits, old ones away; 1.76.51: the view's too -
        # never a reduced texture the open scene shows)
        diskcache.prune_all(libstats._images_in_use())
    except Exception as exc:  # noqa: BLE001
        core.log("SIMPLER_CACHE", "prune failed:", exc)
    t3 = time.time()
    core.log("SIMPLER_OPEN", f"{size / 1e6:.0f} MB", f"read {t1 - t0:.1f}s ({size / 1e6 / max(0.001, t1 - t0):.0f} MB/s)",
             f"settings {t2 - t1:.1f}s", f"textures {t3 - t2:.1f}s")
    try:
        # the sea of a project saved by an older version: its grid, material and maps renewed at once (before, only
        # when the app asked for the Ambiente - a render started first used the old material; found by selfcheck)
        from . import ocean
        if ocean.present():
            ocean.state()
    except Exception as exc:
        core.log("SIMPLER_OCEAN", "renew after open failed:", exc)
    if ambience.active():
        ambience._fog(ambience.state())   # (the haze of projects saved by an older version is renewed)
        try:
            # (and the clouds: a project made with an old version kept clouds of then - one box with an old material,
            # whose missing node broke the path tracing: «key "eye_z" not found»)
            from . import clouds
            if clouds.active(ambience.state()):
                clouds.update(ambience.state())
        except Exception as exc:
            core.log("SIMPLER_CLOUDS", "renew after open failed:", exc)
        ambience.upgrade_world()          # (before 1.27: black under the horizon for glass and reflections)
    ambience._bump()                  # another sky: the real-time view asks for its picture again
    from . import water
    water.ensure()                    # (projects of 1.12-1.13: the waves move from the object to its water material)
    _ecosystems_after_open()
    return {"path": path, "hasView": has_view, "missingTextures": missing_tex, "emptyTextures": empty_tex}     # saved framing: the app shows it instead of framing everything


def _ecosystems_after_open():
    """(1.79.0, Luca: «un progetto che HA SEMPRE FUNZIONATO mostra questo nel path tracer» - the trees and the grass of the
    ecosystems pink in the path tracing after opening «terrain test»; «Ricalcola dalla vista» put everything right;
    «all'apertura forziamo un ricalcolo della vista e degli ecosistemi … aprire un progetto grande ci sta che serva un
    po' di pazienza») every ecosystem of the project made again from its own settings when the project is opened, as
    «Ricalcola» does - before the first picture of the path tracing and of the view. Not an undo step."""
    from . import ecosystems
    groups = [o for o in bpy.context.scene.objects if o.get(ecosystems.ECO_KEY) and not o.get("simpler_trashed")]
    if not groups:
        return
    t0 = time.time()
    done = 0
    for g in groups:
        try:
            ecosystems.apply({"group": g.get("simpler_id")})
            done += 1
        except Exception as exc:  # noqa: BLE001 - that ecosystem stays as it was saved
            core.log("SIMPLER_ECO", f"after open: {g.name} not made again: {exc}")
    history.reset()
    core.log("SIMPLER_ECO", f"after open: {done} of {len(groups)} ecosystems made again in {time.time() - t0:.1f} s")


def project_new(_data):
    history.reset()
    scene_ops.new_scene()
    render.setup_device()
    # a new scene starts from the defaults: framing, render settings, exposure, caustics
    render.STATE.camera = {"target": [0.0, 0.0, 160.0], "distance": 600.0, "yaw": -60.0, "pitch": 1.5, "lens": 50.0}
    render.STATE.config = render.default_config("alta")
    render.STATE.quality = "alta"
    render.apply_caustics(False)
    render.STATE.meter_ev, render.STATE.meter_epoch = None, -1
    history.reset()
    snow.HIDE["on"] = False
    rain.PAUSE["on"] = False
    return {}


@history.on_restore
def _after_undo_load():
    snow.after_open()           # (the snapshots are written without the mantle: made again)
    render.setup_device()
    render.apply_caustics(render.STATE.caustics)


def _profiled(fn, d):
    if not os.environ.get("SIMPLER_PROFILE") or _PROFILE:      # (every request is profiled already: _run_job)
        return fn(d)
    import cProfile, pstats, io
    pr = cProfile.Profile(); pr.enable()
    try:
        return fn(d)
    finally:
        pr.disable(); out = io.StringIO(); pstats.Stats(pr, stream=out).sort_stats("tottime").print_stats(12); print(out.getvalue(), flush=True)


def _after_textures(result):
    render.warm_texture_cache()
    return result


# ---------------------------------------------------------------- routes
# name -> (handler(data) -> dict, changes_image, timeout_s)

def _texture_file(d):
    """File to show an image of the project at most px wide (GET /api/texture?image=&px= serves it)."""
    im = bpy.data.images.get(d.get("image") or "")
    if im is None:
        raise ApiError(tr("Immagine non trovata"))
    px = max(64, min(4096, int(d.get("px") or 1024)))
    return {"path": proxies.file_for(im, px, view=True) or ""}


def _decals_follow(ids, result):
    """A decal moved, turned or scaled: projected again on the piece now under it (see decals.retarget)."""
    decals.retarget_ids(ids)
    return result


def _ids(d):
    return d.get("ids") or ([d["id"]] if d.get("id") else [])


def _ambience_set(d):
    """POST ambience: and the copies pressed by the sculpted snow follow the snow at once (snow.press_update: without
    snow they stand again - the scene list the app asks right after already says so to the view)."""
    out = ambience.api_set(d)
    try:
        snow.press_update()
    except Exception as exc:  # noqa: BLE001
        core.log("SIMPLER_SNOW", f"pressed copies failed: {exc}")
    return out


ROUTES = {
    "GET /api/ping":         (lambda d: {"app": "Simpler", "version": VERSION, "blender": bpy.app.version_string, "device": render.STATE.device}, False, 300),
    "GET /api/scene":        (lambda d: core.scene_json(), False, 300),
    "GET /api/object":       (lambda d: (core.refresh(), core.object_json(core.find(d.get("id"))))[1], False, 300),
    "GET /api/materials":    (lambda d: materials.library_json(), False, 300),
    "GET /api/models":       (models.library_json, False, 300),
    "POST /api/models/save": (models.save, False, 600),
    "POST /api/models/rescale": (models.rescale, False, 60),
    "POST /api/models/orient": (models.orient, False, 60),
    "POST /api/models/orientfromscene": (models.orient_from_scene, False, 60),
    "POST /api/models/orient/apply": (models.orient_scatters, True, 300),
    "POST /api/models/probe": (models.probe, False, 60),
    "POST /api/matbulk/scan": (matbulk.scan, False, 60),
    "POST /api/matbulk/apply": (matbulk.apply, False, 60),
    "GET /api/matbulk/status": (matbulk.status, False, 30),
    "POST /api/matbulk/cancel": (matbulk.cancel, False, 30),
    "POST /api/matbulk/restore": (matbulk.restore, False, 300),
    "POST /api/models/vegetation": (matbulk.vegetation, False, 60),
    "POST /api/scene/vegetation": (matedit.scene_vegetation, True, 300),
    "POST /api/libstats/run": (libstats.run, False, 60),
    "GET /api/libstats/status": (libstats.status, False, 30),
    "POST /api/libstats/clean": (libstats.clean, False, 600),
    "POST /api/models/insert": (lambda d: _after_textures(models.insert(d)), True, 600),
    "POST /api/models/folder": (models.folder_op, False, 300),
    "POST /api/models/lock": (models.lock_set, False, 30),
    "POST /api/models/move": (models.move, False, 300),
    "POST /api/models/copy": (models.copy, False, 600),
    "POST /api/models/rename": (models.rename, False, 300),
    "POST /api/models/delete": (models.delete, False, 300),
    "POST /api/models/thumb": (models.rethumb, False, 300),
    "POST /api/models/import": (models.import_file, False, 300),
    "POST /api/models/importfailed": (models.import_failed, False, 300),
    "GET /api/environments": (lambda d: scene_ops.environments_json(), False, 300),
    "GET /api/settings":     (lambda d: render.settings_json(), False, 300),
    "GET /api/formats":      (lambda d: {"formats": importer.supported_formats()}, False, 300),
    "GET /api/gizmo":        (lambda d: render.gizmo(d.get("id")), False, 300),
    "GET /api/size":         (scene_ops.size_of, False, 300),
    "POST /api/pivot":       (scene_ops.set_pivot, False, 300),
    "POST /api/translate":   (lambda d: scene_ops.translate_world(d.get("id"), d.get("delta")), True, 300),
    "POST /api/rotate":      (lambda d: _decals_follow([d.get("id")], scene_ops.rotate_world(d.get("id"), d.get("axis", "z"), d.get("degrees", 0))), True, 300),
    "POST /api/scale":       (lambda d: _decals_follow([d.get("id")], scene_ops.scale_local(d.get("id"), d.get("factor"))), True, 300),
    "POST /api/preview":     (render.export_preview, False, 1800),
    "POST /api/preview/part": (render.export_part, False, 300),
    "POST /api/model/open":  (scene_ops.open_model, False, 300),
    "POST /api/model/close": (scene_ops.close_models, False, 300),
    "POST /api/matrix":      (lambda d: _decals_follow([d.get("id")], scene_ops.set_matrix_world(d.get("id"), d.get("matrix"))), True, 300),
    "POST /api/matrices":    (lambda d: _decals_follow(_item_ids(d), scene_ops.set_matrices(d.get("items") or [])), True, 300),
    "POST /api/undo":        (history.undo, True, 600),
    "POST /api/redo":        (history.redo, True, 600),
    "GET /api/history":      (lambda d: history.status(), False, 300),
    "POST /api/selection/remember": (history.remember_selection, False, 30),
    "POST /api/pick":        (lambda d: render.pick(float(d["u"]), float(d["v"])), False, 300),

    "POST /api/new":         (project_new, True, 60),
    "POST /api/open":        (project_open, True, 600),
    "POST /api/save":        (project_save, False, 600),
    "POST /api/project/overwrite": (lambda d: __import__("simpler.projfiles", fromlist=["x"]).overwrite_plan(d), False, 60),
    "POST /api/autosave":    (project_autosave, False, 600),
    "GET /api/autosave/info": (autosave_info, False, 30),
    "POST /api/autosave/discard": (autosave_discard, False, 30),
    "GET /api/project/options": (lambda d: project_options(), False, 30),
    "POST /api/project/options": (project_options, False, 30),
    "GET /api/dirty":        (lambda d: dirty_status(), False, 30),
    "GET /api/paths":        (paths.api_list, False, 60),
    "POST /api/paths/set":   (paths.api_set, False, 60),
    "POST /api/paths/check": (paths.api_check, False, 600),
    "POST /api/paths/copy":  (paths.api_copy, False, 600),
    "GET /api/paths/status": (paths.api_status, False, 30),
    "POST /api/paths/cancel": (paths.api_cancel, False, 30),
    "POST /api/paths/deleteold": (paths.api_delete_old, False, 60),
    "POST /api/import":      (lambda d: _after_textures(importer.import_model(d.get("path", ""), d.get("parent", ""), d.get("textureFolders"), bool(d.get("merge")), d.get("location"), d.get("offset"))), True, 3600),
    "POST /api/textures/relink": (lambda d: _after_textures(textures.relink(d)), True, 1800),
    "GET /api/views":        (views.list_views, False, 300),
    "POST /api/views/save":  (views.save_view, True, 600),
    "POST /api/views/update": (views.update_view, True, 600),
    "POST /api/views/apply": (views.apply_view, True, 300),
    "POST /api/views/ptthumb": (lambda d: views.pt_thumb(d, CHANGES["n"]), False, 60),
    "POST /api/views/rename": (views.rename_view, False, 300),
    "POST /api/views/duplicate": (views.duplicate_view, False, 300),
    "POST /api/views/delete": (views.delete_view, False, 300),
    "GET /api/video/frames":  (videoframes.list_frames, False, 60),
    "POST /api/video/frame/save": (videoframes.save_frame, False, 60),
    "POST /api/video/frame/image": (videoframes.set_image, False, 60),
    "POST /api/video/frame/clear": (videoframes.clear_frame, False, 60),
    "POST /api/video/frame/apply": (videoframes.apply_frame, True, 300),
    "GET /api/video/frames/raw": (videoframes.raw_frames, False, 60),
    "POST /api/video/frames/restore": (videoframes.restore_frames, False, 60),
    "POST /api/video/prompt": (videoframes.set_prompt, False, 60),
    "POST /api/materials/preview": (previews.material_preview, False, 600),
    "POST /api/material/livepreview": (previews.live_preview, False, 300),
    "POST /api/material/open":   (lambda d: {"name": materials.get_or_create(d.get("id", "")).name}, False, 300),
    "POST /api/material/save":   (materials.save_to_library, True, 600),
    "POST /api/material/library/reset": (materials.reset_library, True, 300),
    "POST /api/material/library/restore": (materials.restore_presets, False, 600),
    "POST /api/material/library/delete": (materials.delete_library, False, 300),
    "POST /api/material/library/folder": (materials.folder_op, False, 300),
    "POST /api/material/library/move": (materials.move_to_folder, False, 300),
    "GET /api/textures/missing": (textures.status, False, 300),
    "GET /api/selfcheck": (lambda d: __import__("simpler.selfcheck", fromlist=["run"]).run(d), False, 120),
    "POST /api/decal/add":   (decals.add, True, 300),
    "POST /api/decal/edit":  (decals.edit, True, 300),
    "GET /api/decal/mesh":   (decals.mesh, False, 300),
    "GET /api/decal/pngjob": (lambda d: {"data": decals.png_bytes(d.get("id"), d.get("map") or "")}, False, 300),
    "POST /api/add":         (lambda d: scene_ops.add(d.get("kind", ""), d.get("name", ""), d.get("parent", ""), d.get("location"), d.get("aim"), d.get("size")), True, 300),
    "POST /api/delete":      (lambda d: scene_ops.delete_many(_ids(d)), True, 60),
    "POST /api/paint/add":   (lambda d: _after_textures(paint.add(d)), True, 600),
    "GET /api/paint/proto":  (paint.proto, False, 120),
    "POST /api/paint/set":   (lambda d: _after_textures(paint.set_all(d)), True, 600),
    "GET /api/paint/data":   (paint.data, False, 30),
    "GET /api/paint/base":   (paint.base, False, 120),
    "GET /api/paint/points": (paint.points, False, 120),
    "GET /api/material/users": (lambda d: {"ids": matedit.users_of(d.get("name"))}, False, 30),
    "POST /api/duplicate":   (lambda d: scene_ops.duplicate(d.get("id")), True, 60),
    "POST /api/merge":       (lambda d: merge.merge_selection(_ids(d)), True, 600),
    "GET /api/decimate/info": (decimate.info, False, 60),
    "POST /api/decimate/preview": (decimate.preview, False, 3600),
    "POST /api/decimate/apply": (decimate.apply, True, 3600),
    "POST /api/decimate/discard": (decimate.discard, False, 60),
    "POST /api/decimate/view": (decimate.view, False, 3600),
    "POST /api/terrain/dem/preview": (lambda d: __import__("simpler.dem", fromlist=["x"]).preview(d), False, 300),
    "POST /api/terrain/create": (terrain.create, True, 1800),
    "POST /api/terrain/update": (terrain.update, True, 1800),
    "GET /api/terrain/state": (terrain.state, False, 60),
    "GET /api/terrain/list": (terrain.list_terrains, False, 60),
    "POST /api/terrain/materials": (terrain.apply_textures, True, 600),
    "POST /api/terrain/blend": (terrain.set_blend, True, 300),
    "POST /api/paint/drop": (lambda d: __import__("simpler.paint", fromlist=["x"]).drop(d), True, 600),
    "POST /api/scree/apply": (lambda d: __import__("simpler.scree", fromlist=["x"]).apply(d), True, 1800),
    "POST /api/terrain/tone": (terrain.set_tone, True, 300),
    "GET /api/memory":       (memory.preview, False, 60),
    "POST /api/memory/purge": (memory.purge, True, 600),
    "POST /api/duplicate/many": (lambda d: _profiled(scene_ops.duplicate_many, d), True, 1800),
    "POST /api/rename":      (lambda d: scene_ops.rename(d.get("id"), d.get("name")), False, 300),
    "POST /api/parent":      (lambda d: scene_ops.set_parent_many(_ids(d), d.get("parent", "")), True, 300),
    "POST /api/order":       (scene_ops.set_order, False, 300),
    "POST /api/transform":   (lambda d: _decals_follow([d.get("id")], scene_ops.transform(d.get("id"), d)), True, 300),
    "POST /api/noscatter":   (lambda d: scene_ops.set_noscatter(_ids(d), bool(d.get("value", True))), False, 300),
    "POST /api/rain/dry":    (lambda d: rain.set_dry(_ids(d), bool(d.get("value", True)), d.get("kind")), True, 300),
    "POST /api/rain/noshelter": (lambda d: rain.set_open(_ids(d), bool(d.get("value", True))), True, 300),
    "POST /api/rain/nomantle": (lambda d: snow.set_flag(_ids(d), bool(d.get("value", True))), True, 300),
    "POST /api/rain/snowhide": (snow.set_hidden, False, 60),
    "POST /api/rain/pause": (rain.set_pause, False, 30),
    "POST /api/smartview": (rain.set_smart, False, 30),
    "POST /api/rain/snowdetail": (lambda d: snow.set_detail(_ids(d), str(d.get("value") or "auto")), True, 300),
    "POST /api/rain/paint":  (rain.paint_stroke, True, 300),
    "POST /api/snow/brushing": (lambda d: __import__("simpler.snow", fromlist=["x"]).set_brushing(d), False, 30),
    "POST /api/rain/paint/clear": (rain.paint_clear, True, 300),
    "POST /api/dirt/paint":  (lambda d: __import__("simpler.dirtpaint", fromlist=["x"]).stroke(d), True, 300),
    "POST /api/dirt/paint/clear": (lambda d: __import__("simpler.dirtpaint", fromlist=["x"]).clear(d), True, 300),
    "GET /api/dirt/info":    (lambda d: {"info": __import__("simpler.dirtpaint", fromlist=["x"]).info()}, False, 60),
    "POST /api/rain/sculpt": (lambda d: __import__("simpler.snowsculpt", fromlist=["x"]).stroke(d), True, 300),
    "POST /api/rain/sculpt/clear": (lambda d: __import__("simpler.snowsculpt", fromlist=["x"]).clear(d), True, 300),
    "POST /api/material/water": (lambda d: __import__("simpler.water", fromlist=["x"]).set_material(d), True, 300),
    "POST /api/material/volumetric": (lambda d: __import__("simpler.volumetric", fromlist=["x"]).set_material(d), True, 300),
    "POST /api/material/raindrops": (lambda d: __import__("simpler.rain", fromlist=["x"]).set_material_drops(d), True, 300),
    "POST /api/normals":     (lambda d: scene_ops.fix_normals(_ids(d)), True, 600),
    "POST /api/visible":     (lambda d: scene_ops.set_visible(d.get("id"), bool(d.get("visible", True))), True, 300),
    "POST /api/light":       (lambda d: scene_ops.set_light(d.get("id"), d), True, 300),
    "POST /api/material/assign": (lambda d: materials.assign(_ids(d), d.get("material", ""), d.get("slot"), d.get("name"), d.get("replace")), True, 30),
    "POST /api/realtime/materials": (materials.realtime_json, False, 300),
    "GET /api/textures/estimate": (render.texture_estimate, False, 300),
    "POST /api/material/set":    (lambda d: materials.set_params(d.get("name", ""), d), True, 300),
    "GET /api/material/edit":    (matedit.editor_json, False, 300),
    "POST /api/material/edit":   (matedit.edit, True, 300),
    "POST /api/material/dispcheck": (matedit.displacement_check, False, 60),
    "POST /api/material/reset":  (matedit.reset, True, 300),
    "POST /api/material/center": (matedit.center, True, 300),
    "POST /api/material/fit": (matedit.fit, True, 300),
    "POST /api/material/duplicate": (matedit.duplicate, True, 300),
    "POST /api/material/rename": (matedit.rename, False, 300),
    "POST /api/material/replace": (matedit.replace, True, 300),
    "GET /api/scene/materials":  (matedit.scene_materials, False, 300),
    "GET /api/texture/file":     (_texture_file, False, 300),
    "POST /api/library/apply":   (library.apply, True, 600),
    "POST /api/library/models/insert": (lambda d: _after_textures(phmodels.insert(d)), True, 600),
    "POST /api/library/models/tolibrary": (lambda d: phmodels.to_library(d), True, 600),
    "POST /api/library/models/lods": (lambda d: phmodels.lods(d), False, 300),
    "GET /api/ambience":     (ambience.api_get, False, 60),
    "GET /api/luts":         (lambda d: __import__("simpler.luts", fromlist=["x"]).library(d), False, 60),
    "POST /api/luts/favorite": (lambda d: __import__("simpler.luts", fromlist=["x"]).set_favorite(d), False, 30),
    "POST /api/luts/import": (lambda d: __import__("simpler.luts", fromlist=["x"]).import_files(d), False, 600),
    "POST /api/luts/delete": (lambda d: __import__("simpler.luts", fromlist=["x"]).delete(d), False, 60),
    "POST /api/lut/source":  (lambda d: __import__("simpler.luts", fromlist=["x"]).set_source(d), False, 30),
    "GET /api/hdri/list":    (hdri.list_items, False, 120),
    "POST /api/ambience":    (_ambience_set, True, 300),
    "POST /api/ambience/refresh": (ambience.refresh_api, False, 300),
    "POST /api/landscape/ocean": (lambda d: __import__("simpler.ocean", fromlist=["x"]).api_set(d), True, 300),
    "GET /api/ecosystems":   (ecosystems.library, False, 60),
    "POST /api/ecosystems/save": (ecosystems.save, False, 300),
    "POST /api/ecosystems/saveown": (ecosystems.save_own, False, 120),
    "POST /api/ecosystems/rename": (ecosystems.rename, False, 30),
    "POST /api/ecosystems/defaults": (ecosystems.set_defaults, False, 30),
    "POST /api/ecosystems/delete": (ecosystems.delete, False, 30),
    "POST /api/ecosystems/copy": (ecosystems.copy, False, 120),
    "GET /api/ecosystems/detail": (ecosystems.detail, False, 30),
    "GET /api/ecosystems/editing": (ecosystems.editing, False, 30),
    "POST /api/ecosystems/edit": (ecosystems.edit, True, 1800),
    "POST /api/ecosystems/folder": (ecosystems.folder_op, False, 30),
    "POST /api/ecosystems/move": (ecosystems.move, False, 30),
    "POST /api/ecosystems/thumb": (ecosystems.thumb, False, 120),
    "POST /api/ecosystems/plot": (ecosystems.new_plot, True, 60),
    "POST /api/ecosystems/close": (ecosystems.close, True, 120),
    "POST /api/ecosystems/estimate": (ecosystems.estimate, False, 120),
    "POST /api/ecosystems/apply": (ecosystems.apply, True, 1800),
    "GET /api/models/usage": (libupdate.usage, False, 30),
    "GET /api/models/outdated": (libupdate.outdated, False, 30),
    "POST /api/models/refresh": (libupdate.update, True, 1800),
    "POST /api/ecosystems/count": (lambda d: ecosystems.apply(dict(d, dry=True)), False, 300),
    "GET /api/camview":      (camview.status, False, 30),
    "POST /api/camview":     (camview.set_settings, False, 30),
    "POST /api/camview/refresh": (camview.refresh, True, 1800),
    "GET /api/ecosystems/info": (ecosystems.info, False, 30),
    "GET /api/ambience/night/status": (night.status, False, 30),
    "POST /api/ambience/bake": (ambience.bake, False, 60),
    "GET /api/ambience/bake": (ambience.bake, False, 60),
    "GET /api/ambience/sky": (ambience.sky_status, False, 30),
    "GET /api/ambience/skyrefs": (skyphoto.refs, False, 30),
    "GET /api/skytable":     (lambda d: skytable_status(d), False, 10),
    "POST /api/ambience/fromphoto": (skyphoto.from_photo, True, 120),
    "POST /api/ambience/skyrefs/save": (skyphoto.save_ref, False, 60),
    "POST /api/ambience/skyrefs/delete": (skyphoto.delete_ref, False, 30),
    "POST /api/environment": (lambda d: scene_ops.set_environment(d.get("id", ""), float(d.get("strength", 1.0))), True, 300),
    "POST /api/settings":    (lambda d: render.set_settings(d), True, 300),
    "POST /api/camera":      (lambda d: _camera(d), True, 300),
    "POST /api/render":      (lambda d: render.final_render(d), False, 24 * 3600),
}


# Undo: which commands can be undone and how (see history.py)
def _item_ids(d):
    return [it.get("id") for it in d.get("items") or []]


UNDOABLE = {
    "POST /api/translate": ("state", "Sposta", _ids),
    "POST /api/rotate": ("state", "Ruota", _ids),
    "POST /api/scale": ("state", "Scala", _ids),
    "POST /api/matrix": ("state", "Trasforma", _ids),
    "POST /api/matrices": ("state", "Trasforma", _item_ids),
    "POST /api/transform": ("state", "Trasforma", _ids),
    "POST /api/pivot": ("state", "Sposta il pivot", _ids),
    "POST /api/visible": ("state", "Visibilità", _ids),
    "POST /api/rename": ("state", "Rinomina", _ids),
    "POST /api/parent": ("state", "Sposta nel gruppo", _ids),
    "POST /api/order": ("state", "Sposta nell'albero", scene_ops.order_undo_ids),
    "POST /api/light": ("state", "Modifica luce", _ids),
    "POST /api/rain/dry": ("state", "Sempre asciutto", lambda d: rain.dry_undo_ids(_ids(d))),
    "POST /api/rain/noshelter": ("state", "Non fa riparo", lambda d: rain.dry_undo_ids(_ids(d))),
    "POST /api/rain/nomantle": ("state", "Senza mantello", lambda d: rain.dry_undo_ids(_ids(d))),
    "POST /api/rain/snowdetail": ("state", "Dettaglio della neve", lambda d: rain.dry_undo_ids(_ids(d))),
    "POST /api/rain/paint": ("rainpaint", "Pozzanghere dipinte", None),
    "POST /api/rain/paint/clear": ("rainpaint", "Cancella pozzanghere dipinte", None),
    "POST /api/dirt/paint": ("dirtpaint", "Sporco dipinto", None),
    "POST /api/dirt/paint/clear": ("dirtpaint", "Cancella lo sporco dipinto", None),
    "POST /api/rain/sculpt": ("rainpaint", "Neve scolpita", None),
    "POST /api/rain/sculpt/clear": ("rainpaint", "Cancella la neve scolpita", None),
    "POST /api/import": ("objects", "Importa", None),
    "POST /api/add": ("objects", "Aggiungi", None),
    "POST /api/decal/add": ("objects", "Decal", None),
    "POST /api/decal/edit": ("state", "Modifica decal", _ids),
    "POST /api/models/insert": ("objects", "Inserisci modello", None),
    "POST /api/library/models/insert": ("objects", "Modello Poly Haven", None),
    "POST /api/delete": ("objects", "Elimina", None),
    "POST /api/paint/add": ("objects", "Pennello", None),
    "POST /api/paint/set": ("objects", "Distribuzione", None),
    "POST /api/ecosystems/apply": ("objects", "Ecosistema", None),
    "POST /api/camview/refresh": ("objects", "Ricalcola dalla vista", None),
    "POST /api/models/refresh": ("allobjects", "Aggiorna dalla libreria", None),
    "POST /api/ecosystems/plot": ("objects", "Banco ecosistema", None),
    "POST /api/ecosystems/close": ("objects", "Chiudi il banco di prova", None),
    "POST /api/ecosystems/edit": ("objects", "Modifica ecosistema", None),
    "POST /api/duplicate": ("objects", "Duplica", None),
    "POST /api/merge": ("objects", "Unisci in un solo oggetto", None),
    "POST /api/decimate/apply": ("meshes", "Ottimizza poligoni", None),
    "POST /api/terrain/create": ("objects", "Terreno", None),
    "POST /api/terrain/update": ("meshes", "Modifica terreno", None),
    "POST /api/terrain/blend": ("deep", "Sfumatura dei bordi", lambda d: [o["simpler_id"] for o in terrain.zone_objects(terrain._group(d.get("id"))).values()] if d.get("id") else []),
    "POST /api/paint/drop": ("objects", "Appoggia alla superficie", None),
    "POST /api/scree/apply": ("objects", "Pietre e detriti", None),
    "POST /api/terrain/tone": ("deep", "Colori dal terreno", lambda d: [d["id"]] + [o["simpler_id"] for o in terrain.zone_objects(terrain._group(d.get("id"))).values()] if d.get("id") else []),
    "POST /api/terrain/materials": ("deep", "Materiali del terreno", lambda d: [o["simpler_id"] for o in terrain.zone_objects(terrain._group(d.get("id"))).values()] if d.get("id") else []),
    "POST /api/duplicate/many": ("objects", "Duplica", None),
    "POST /api/material/assign": ("deep", "Materiale", lambda d: materials.assign_undo_ids(_ids(d))),
    "POST /api/material/set": ("material", "Modifica materiale", lambda d: [d.get("name", "")]),
    "POST /api/material/edit": ("material", "Modifica materiale", lambda d: [d.get("name", "")]),
    "POST /api/scene/vegetation": ("material", "Converti in vegetazione", matedit.scene_vegetation_materials),
    "POST /api/material/reset": ("material", "Ripristina materiale", lambda d: [d.get("name", "")]),
    "POST /api/material/center": ("material", "Centra la mappa", lambda d: [d.get("name", "")]),
    "POST /api/material/fit": ("file", "Adatta la texture all'oggetto", None),
    "POST /api/material/duplicate": ("deep", "Duplica materiale", lambda d: list(d.get("ids") or []) or ([d.get("id")] if d.get("id") else [])),
    "POST /api/material/replace": ("deep", "Sostituisci materiale", lambda d: matedit.users_of(d.get("name"))),
    "POST /api/library/apply": ("deep", "Materiale Poly Haven", _ids),
    "POST /api/environment": ("env", "Ambiente", None),
    "POST /api/ambience": ("ambience", "Ambiente", None),
    "POST /api/landscape/ocean": ("ocean", "Oceano", None),
    "POST /api/ambience/fromphoto": ("ambience", "Colori da una foto", None),
    "POST /api/material/water": ("material", "Acqua", lambda d: [d.get("name", "")]),
    "POST /api/material/volumetric": ("material", "Volumetrico", lambda d: [d.get("name", "")]),
    "POST /api/material/raindrops": ("material", "Con la pioggia", lambda d: [d.get("name", "")]),
    "POST /api/normals": ("normals", "Correggi normali", None),
    "POST /api/views/apply": ("view", "Scena", None),
    "POST /api/video/frame/apply": ("view", "Fotogramma del video", None),
    "POST /api/textures/relink": ("file", "Collega texture", None),
}


class _Job:
    def __init__(self, key, data):
        self.key, self.data = key, data
        self.t_put = time.time()          # (1.79.0) when it arrived: the log says how long it waited for the engine
        self.done = threading.Event()
        self.result, self.error = None, None


JOBS = queue.Queue()
STOP = threading.Event()


class Handler(BaseHTTPRequestHandler):
    server_version = "Simpler/" + VERSION

    def log_message(self, fmt, *args):  # quiet
        pass

    def _send(self, code, body, ctype="application/json; charset=utf-8", headers=None):
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Expose-Headers", "X-Simpler-Frame")
        for k, v in (headers or {}).items():
            self.send_header(k, str(v))
        self.end_headers()
        self.wfile.write(body)

    def _json(self, code, obj):
        self._send(code, json.dumps(obj, ensure_ascii=False).encode("utf-8"))

    def _handle(self, method):
        url = urlparse(self.path)
        if method == "GET" and url.path == "/api/frame":
            data, info = render.get_frame()
            if not data:
                self._send(204, b"")
            else:
                self._send(200, data, "image/jpeg", {"X-Simpler-Frame": json.dumps(info)})
            return
        if method == "GET" and url.path == "/api/decal/png":
            # the picture of a decal as it is (PNG with transparency), for the real-time view
            q = {k: v[0] for k, v in parse_qs(url.query).items()}
            job = _Job("GET /api/decal/pngjob", q)
            JOBS.put(job)
            render.interrupt_pass()
            job.done.wait()
            data = (job.result or {}).get("data") if not job.error else None
            if not data:
                self._send(404, b"")
            else:
                self._send(200, data, "image/png")
            return
        if method == "GET" and url.path == "/api/paint/points.bin":
            # the points of a distribution (paint.points): float32 matrices, served as they are
            path = paint.points_file({k: v[0] for k, v in parse_qs(url.query).items()}.get("f"))
            if not path:
                self._send(404, b"")
            else:
                with open(path, "rb") as f:
                    self._send(200, f.read(), "application/octet-stream")
            return
        if method == "GET" and url.path == "/api/ambience/night/file":
            # stars and moon for the real-time view (night.py): files of the library, served as they are
            try:
                path = ambience.night_file({k: v[0] for k, v in parse_qs(url.query).items()}.get("f"))
            except ApiError:
                path = ""
            if not path:
                self._send(404, b"")
            else:
                with open(path, "rb") as f:
                    self._send(200, f.read(), "image/png" if path.endswith(".png") else "image/jpeg")
            return
        if method == "GET" and url.path == "/api/busy":
            self._json(200, busy_status())          # (straight from here: never waits for Blender's thread)
            return
        if method == "GET" and url.path == "/api/rain/info":
            # (straight from here: through the queue it would interrupt the path tracing pass, see rain.refresh_info)
            from . import rain
            self._json(200, rain.info())
            return
        if method == "GET" and url.path == "/api/ocean/mesh":
            # (straight from here: the surface of the sea for the real-time view, made on Blender's thread at
            # every change - ocean.mesh_bytes)
            from . import ocean
            data = ocean.mesh_bytes({k: v[0] for k, v in parse_qs(url.query).items()}.get("topo") or "")
            self._send(200 if data else 404, data, "application/octet-stream")
            return
        if method == "GET" and url.path == "/api/ocean/slopes":
            # (straight from here: the slopes of the far waves for the real-time view, ocean.slopes_png)
            from . import ocean
            data = ocean.slopes_png({k: v[0] for k, v in parse_qs(url.query).items()}.get("which") or "")
            self._send(200 if data else 404, data, "image/png")
            return
        if method == "GET" and url.path == "/api/lut/thumb":
            from . import luts
            q = {k: v[0] for k, v in parse_qs(url.query).items()}
            data = luts.thumb_png(q.get("id") or "", q.get("k") or "")
            self._send(200 if data else 404, data, "image/png")
            return
        if method == "GET" and url.path == "/api/lut/table":
            # (straight from here: no Blender - the colour table of a look for the real-time view, luts.table_bytes)
            from . import luts
            data = luts.table_bytes({k: v[0] for k, v in parse_qs(url.query).items()}.get("id") or "")
            self._send(200 if data else 404, data, "application/octet-stream")
            return
        if method == "GET" and url.path == "/api/dirt/paint.bin":
            from . import dirtpaint
            path = dirtpaint.bin_file({k: v[0] for k, v in parse_qs(url.query).items()}.get("f"))
            if not path:
                self._send(404, b"")
            else:
                with open(path, "rb") as f:
                    self._send(200, f.read(), "application/octet-stream")
            return
        if method == "GET" and url.path == "/api/rain/paint.bin":
            from . import rain
            path = rain.paint_file({k: v[0] for k, v in parse_qs(url.query).items()}.get("f"))
            if not path:
                self._send(404, b"")
            else:
                with open(path, "rb") as f:
                    self._send(200, f.read(), "application/octet-stream")
            return
        if method == "GET" and url.path == "/api/rain/snowfall.bin":
            # the flakes that fall, for the real-time view (snowfall.py)
            from . import snowfall
            path = snowfall.view_file({k: v[0] for k, v in parse_qs(url.query).items()}.get("f"))
            if not path:
                self._send(404, b"")
            else:
                with open(path, "rb") as f:
                    self._send(200, f.read(), "application/octet-stream")
            return
        if method == "GET" and url.path == "/api/rain/raindrops.bin":
            # the drops that fall and their splashes, for the real-time view (raindrops.py)
            from . import raindrops
            path = raindrops.view_file({k: v[0] for k, v in parse_qs(url.query).items()}.get("f"))
            if not path:
                self._send(404, b"")
            else:
                with open(path, "rb") as f:
                    self._send(200, f.read(), "application/octet-stream")
            return
        if method == "GET" and url.path == "/api/rain/mantle.bin":
            # the snow mantle for the real-time view (snow.py)
            path = snow.view_file({k: v[0] for k, v in parse_qs(url.query).items()}.get("f"))
            if not path:
                self._send(404, b"")
            else:
                with open(path, "rb") as f:
                    self._send(200, f.read(), "application/octet-stream")
            return
        if method == "GET" and url.path == "/api/rain/ice.bin":
            # the map of the frozen water for the real-time view (ice.py): half floats, rows from the bottom
            from . import ice
            path = ice.view_file({k: v[0] for k, v in parse_qs(url.query).items()}.get("f"))
            if not path:
                self._send(404, b"")
            else:
                with open(path, "rb") as f:
                    self._send(200, f.read(), "application/octet-stream")
            return
        if method == "GET" and url.path == "/api/rain/shelter.bin":
            # the shelter map of the rain for the real-time view (rain.py): half floats, rows from the bottom
            from . import rain
            path = rain.shelter_file({k: v[0] for k, v in parse_qs(url.query).items()}.get("f"))
            if not path:
                self._send(404, b"")
            else:
                with open(path, "rb") as f:
                    self._send(200, f.read(), "application/octet-stream")
            return
        if method == "GET" and url.path == "/api/rain/mask.png":
            # the puddle map of the rain (rain.py), the same picture the path tracing uses
            from . import rain
            try:
                with open(rain.mask_path(), "rb") as f:
                    self._send(200, f.read(), "image/png")
            except OSError:
                self._send(404, b"")
            return
        if method == "GET" and url.path == "/api/ambience/sky.bin":
            # the 360° sky of the real-time view (ambience.py): half floats RGBA, laid out for three.js
            try:
                path = ambience.sky_file({k: v[0] for k, v in parse_qs(url.query).items()}.get("f"))
            except ApiError:
                path = ""
            if not path:
                self._send(404, b"")
            else:
                with open(path, "rb") as f:
                    self._send(200, f.read(), "application/octet-stream")
            return
        if method == "GET" and url.path == "/api/paint/proto.glb":
            # prototype of a painted model for the real-time view (paint.py): a file of the view cache
            path = paint.proto_file({k: v[0] for k, v in parse_qs(url.query).items()}.get("f"))
            if not path:
                self._send(404, b"")
            else:
                with open(path, "rb") as f:
                    self._send(200, f.read(), "model/gltf-binary")
            return
        if method == "GET" and url.path in ("/api/preview/part/status", "/api/preview/part.glb"):
            # new objects only, for the real-time view (render.export_part)
            k = {k: v[0] for k, v in parse_qs(url.query).items()}.get("k")
            if url.path.endswith("status"):
                self._json(200, render.part_status(k))
                return
            path = render.part_file(k)
            if not path:
                self._send(404, b"")
            else:
                with open(path, "rb") as f:
                    self._send(200, f.read(), "model/gltf-binary")
            return
        if method == "GET" and url.path == "/api/preview.glb":
            path = render.PREVIEW["path"]
            if not path or not os.path.isfile(path):
                self._send(404, b"")
            else:
                with open(path, "rb") as f:
                    self._send(200, f.read(), "model/gltf-binary")
            return
        if method == "POST" and url.path == "/api/live/off":
            # back to the real-time view: answered at once, even while a path tracing pass is running
            render.STATE.live = False
            render.interrupt_pass("live/off")
            self._json(200, {"ok": True})
            return
        if url.path in ("/api/hdri/thumb", "/api/hdri/download", "/api/hdri/status"):
            # HDRI library: network and files only, answered here at once
            q = {k: v[0] for k, v in parse_qs(url.query).items()}
            if method == "POST":
                length = int(self.headers.get("Content-Length") or 0)
                try:
                    q.update(json.loads((self.rfile.read(length) if length else b"{}").decode("utf-8") or "{}"))
                except ValueError:
                    pass
            if url.path == "/api/hdri/thumb":
                path = hdri.thumb_file(q.get("id"))
                if not path:
                    self._send(404, b"")
                else:
                    with open(path, "rb") as f:
                        self._send(200, f.read(), "image/png")
                return
            try:
                out = dict((hdri.download if url.path.endswith("download") else hdri.status)(q) or {})
                out["ok"] = True
                self._json(200, out)
            except Exception as exc:
                self._json(500, {"ok": False, "error": str(exc)})
            return
        if url.path.startswith("/api/library/") and url.path not in ("/api/library/apply", "/api/library/models/insert",
                                                                     "/api/library/models/tolibrary", "/api/library/models/lods"):
            # Poly Haven library: network and files only (no Blender data), answered here at once
            q = {k: v[0] for k, v in parse_qs(url.query).items()}
            if method == "POST":
                length = int(self.headers.get("Content-Length") or 0)
                try:
                    q.update(json.loads((self.rfile.read(length) if length else b"{}").decode("utf-8") or "{}"))
                except ValueError:
                    pass
            if url.path == "/api/library/decals/thumb":
                path = acgdecals.thumb_file(q.get("id"))
                if not path:
                    self._send(404, b"")
                else:
                    with open(path, "rb") as f:
                        self._send(200, f.read(), "image/png")
                return
            if url.path in ("/api/library/thumb", "/api/library/models/thumb"):
                path = (phmodels if "/models/" in url.path else library).thumb_file(q.get("id"))
                if not path:
                    self._send(404, b"")
                else:
                    with open(path, "rb") as f:
                        self._send(200, f.read(), "image/png")
                return
            fn = {"/api/library/list": library.list_assets, "/api/library/download": library.download,
                  "/api/library/status": library.status, "/api/library/models/list": phmodels.list_assets,
                  "/api/library/models/download": phmodels.download, "/api/library/models/status": phmodels.status,
                  "/api/library/decals/list": acgdecals.list_assets, "/api/library/decals/download": acgdecals.download,
                  "/api/library/decals/status": acgdecals.status}.get(url.path)
            if fn is not None:
                try:
                    out = dict(fn(q) or {})
                    out["ok"] = True
                    self._json(200, out)
                except Exception as exc:
                    self._json(400, {"ok": False, "error": str(exc)})
                return
        if method == "GET" and url.path in ("/api/material/preview/status", "/api/material/preview/file"):
            q = {k: v[0] for k, v in parse_qs(url.query).items()}
            st = previews.status(q)
            if url.path.endswith("status"):
                st["ok"] = True
                self._json(200, st)
            elif st.get("state") == "done" and os.path.isfile(st.get("path", "")):
                with open(st["path"], "rb") as f:
                    self._send(200, f.read(), "image/png")
            else:
                self._send(404, b"")
            return
        if method == "GET" and url.path == "/api/texture":
            q = {k: v[0] for k, v in parse_qs(url.query).items()}
            job = _Job("GET /api/texture/file", q)
            JOBS.put(job)
            render.interrupt_pass()
            job.done.wait()
            path = (job.result or {}).get("path") if not job.error else ""
            if not path or not os.path.isfile(path):
                self._send(404, b"")
                return
            ext = os.path.splitext(path)[1].lower()
            ctype = {".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".png": "image/png", ".bmp": "image/bmp"}.get(ext, "application/octet-stream")
            with open(path, "rb") as f:
                self._send(200, f.read(), ctype)
            return
        if method == "GET" and url.path == "/api/gpu":
            from . import gpu
            self._json(200, {"gpu": gpu.info(), "device": render.STATE.device})
            return
        if method == "GET" and url.path == "/api/proxies":
            self._json(200, proxies.status())
            return
        if method == "GET" and url.path == "/api/preview/status":
            self._json(200, render.preview_status())
            return
        if method == "POST" and url.path == "/api/preview/cancel":
            self._json(200, render.cancel_preview())
            return
        if method == "POST" and url.path == "/api/render/cancel":
            self._json(200, render.cancel_render())
            return
        if method == "POST" and url.path == "/api/decimate/cancel":
            self._json(200, decimate.cancel())            # (from here: the computation checks it between pieces)
            return
        if method == "GET" and url.path == "/api/progress":
            snap = progress.snapshot()
            if snap.get("active") and snap.get("task") == "render":
                snap["hardware"] = render.render_hardware()      # (straight from here: NVML and the system, no Blender)
            if snap.get("active") and snap.get("task") == "decimate":
                live = decimate.live_fraction()                  # (1.75.55) the piece on, estimated from the speed
                if live is not None:
                    snap["fraction"] = live[0]
                    if live[1] is not None:
                        snap["pieceLeft"] = round(live[1])
            self._json(200, snap)
            return
        if method == "GET" and url.path == "/api/frame/info":
            self._json(200, render.get_frame()[1])
            return
        if method == "POST" and url.path == "/api/shutdown":
            STOP.set()
            self._json(200, {"ok": True})
            return

        key = f"{method} {url.path}"
        if key not in ROUTES:
            self._json(404, {"ok": False, "error": tr("Endpoint sconosciuto")})
            return
        if method == "POST":
            length = int(self.headers.get("Content-Length") or 0)
            raw = self.rfile.read(length) if length else b"{}"
            try:
                data = json.loads(raw.decode("utf-8") or "{}")
            except ValueError:
                self._json(400, {"ok": False, "error": tr("JSON non valido")})
                return
        else:
            data = {k: v[0] for k, v in parse_qs(url.query).items()}

        job = _Job(key, data)
        JOBS.put(job)
        render.interrupt_pass(key)   # commands never wait for a path tracing pass
        # no time limit: a queued command always runs (giving up here would leave it running later,
        # unseen); long waits are shown and can be cancelled in the app
        job.done.wait()
        if job.error:
            self._json(400, {"ok": False, "error": job.error})
        else:
            out = dict(job.result or {})
            out["ok"] = True
            self._json(200, out)

    def do_OPTIONS(self):
        self.send_response(204)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.end_headers()

    def do_GET(self):
        self._handle("GET")

    def do_POST(self):
        self._handle("POST")


# ---------------------------------------------------------------- unsaved changes (asked when closing Simpler)
CHANGES = {"n": 0, "saved": 0}

# What Blender's thread is doing now (GET /api/busy, answered straight from the HTTP thread): a command, or a
# computation of its own (the shelter of the rain). The real-time view shows «Occupato · attendi» while it lasts.
BUSY = {"job": None, "t0": 0.0}
_BUSY_LABELS = {
    "POST /api/autosave": "Salvataggio automatico", "POST /api/save": "Salvataggio del progetto",
    "POST /api/open": "Apertura del progetto", "POST /api/new": "Nuova scena", "POST /api/import": "Importazione del modello",
    "POST /api/preview": "Preparazione della vista", "POST /api/undo": "Annulla", "POST /api/redo": "Ripeti",
    "POST /api/models/insert": "Inserimento del modello", "POST /api/paint/set": "Distribuzione",
    "POST /api/ecosystems/apply": "Ecosistema", "POST /api/library/apply": "Materiale dalla libreria", "POST /api/ecosystems/edit": "Modifica ecosistema",
    "POST /api/render": "Render", "rain": "Calcolo del riparo dalla pioggia", "POST /api/landscape/ocean": "Oceano",
    "POST /api/scree/apply": "Pietre e detriti",
}


def busy_status():
    job, t0 = BUSY["job"], BUSY["t0"]
    queued = JOBS.qsize()
    if job is None and not queued:
        # Cycles preparing the scene for the view (geometry, the grids of volumes, textures): Blender's thread is
        # held and a command would wait - said like any other work (the passes that follow can be interrupted)
        try:
            from . import progress
            prep = progress.viewport_snapshot()
        except Exception:
            prep = {"active": False}
        sampling = prep.get("phase") in (tr("Calcolo dell'immagine"), tr("Riduzione del rumore"))   # (interruptible)
        since = time.time() - (prep.get("phaseStarted") or time.time())
        if prep.get("active") and not sampling and since >= 0.8 and render.STATE.live:
            return {"busy": True, "what": tr("Path tracing") + ": " + str(prep.get("phase") or ""), "secs": round(since, 1),
                    "queued": 0, "ok": True}
        return {"busy": False, "ok": True}
    key = job or ""
    label = _BUSY_LABELS.get(key) or (UNDOABLE[key][1] if key in UNDOABLE else "Il motore sta lavorando")
    if key == "rain":
        label = rain.IDLE["what"]               # (the shelter or the mantle of snow)
    return {"busy": True, "what": tr(label), "secs": round(time.time() - t0, 1) if job else 0.0, "queued": queued, "ok": True}
_COUNTED = {"POST /api/views/ptthumb", "POST /api/views/save", "POST /api/views/update", "POST /api/views/rename", "POST /api/views/duplicate",
            "POST /api/views/delete", "POST /api/undo", "POST /api/redo", "POST /api/noscatter", "POST /api/project/options",
            "POST /api/camview",
            "POST /api/video/frame/save", "POST /api/video/frame/image", "POST /api/video/frame/clear",
            "POST /api/video/frames/restore", "POST /api/video/prompt"}


def _camera(d):
    r = render.camera_command(d)
    try:
        from . import ocean
        ocean.camera_moved()          # (1.76.39: «Segue l'inquadratura» - only a flag, the sea follows when idle)
    except Exception as exc:  # noqa: BLE001
        print("SIMPLER_OCEAN follow camera", exc, flush=True)
    return r


def _changes_scene(key, data):
    """Does this request change what the project file keeps? (navigation and the live preview do not)"""
    if key in UNDOABLE or key in _COUNTED:
        return True
    if key == "POST /api/settings":
        return bool(set(data) - {"live", "viewport", "view", "lang"})
    if key == "POST /api/camera":
        return data.get("action") not in ("lookat", "orbit", "zoom", "pan", "set", None)
    return False


# commands that change materials only, never a shape: no shelter, mantle or coast computed again after them
GEOMETRY_SAME = ("POST /api/dirt/paint", "POST /api/dirt/paint/clear",
                 # (1.78.4, Luca: every stroke of the snow brush started «Calcolo del riparo dalla pioggia») painted
                 # puddles and snow, sculpted snow: the shelter, the coast and the drops follow shapes, not these
                 "POST /api/rain/paint", "POST /api/rain/paint/clear", "POST /api/rain/sculpt", "POST /api/rain/sculpt/clear",
                 # (audit 1.78.5: 0.24 s of checks after each on a scene of 3,000 objects) a light, a name, a scene saved
                 "POST /api/light", "POST /api/rename", "POST /api/views/save", "POST /api/views/update")
# (audit 1.78.5) the sky alone (sun, clouds, fog, exposure, night): no shape changes - the mode or the ground may add or
# take away the ground, so they still count
AMBIENCE_LOOK = frozenset(("sun", "sky", "clouds", "fog", "exposure", "night"))
# (1.78.3) an edit of a material that only changes its look (colour, roughness, leaves, cloth…): no shape changed, so
# the coast, the shelter and the mantle are not looked for again - on a scene with a sea every slider moved made the
# engine busy 1 s after it measuring the coast. Opacity, transmission and displacement still count: glass and holes
# change the shelter, the displacement the shape.
LOOK_ONLY = frozenset(("color", "roughness", "metallic", "specular", "normal", "coat", "sheen", "subsurface", "emission",
                       "fabric", "foliage", "uv", "grunge", "gold", "red"))


def _changes_geometry(job):
    if job.key in GEOMETRY_SAME:
        return False
    if job.key == "POST /api/ambience":
        d = job.data or {}
        return not d or not set(d) <= AMBIENCE_LOOK
    if job.key == "POST /api/material/edit":
        d = job.data or {}
        params = d.get("params") or {}
        new_map = ((params.get("color") or {}).get("map") or {}).get("image")      # (a see-through texture sets the opacity)
        return bool(d.get("convert") or d.get("type") or not params or new_map or any(k not in LOOK_ONLY for k in params))
    return True


def dirty_status(_data=None):
    return {"dirty": CHANGES["n"] != CHANGES["saved"], "changes": CHANGES["n"] - CHANGES["saved"]}


def _mark_saved():
    CHANGES["saved"] = CHANGES["n"]


_PROFILE = os.environ.get("SIMPLER_PROFILE")      # (diagnosis: every request over 0.3 s profiled into the log)
# (1.75.27) or a file «profile.on» in the app's local folder: switched on from outside, without starting the engine
# differently - to find what is slow on the user's own scene
if not _PROFILE and os.path.isfile(os.path.join(os.environ.get("LOCALAPPDATA") or "", "Simpler", "profile.on")):
    _PROFILE = "file"


def _run_job(job):
    core.find_reset()               # (ids found during a request: core.find - objects come and go between requests)
    try:
        return _run_job_p(job)
    finally:
        core.find_reset()


def _run_job_p(job):
    if _PROFILE:
        import cProfile
        import io
        import pstats
        pr = cProfile.Profile()
        t0 = time.time()
        pr.enable()
        try:
            return _run_job_(job)
        finally:
            pr.disable()
            if time.time() - t0 >= (2.0 if _PROFILE == "file" else 0.3):
                out = io.StringIO()
                st_ = pstats.Stats(pr, stream=out)
                st_.sort_stats("cumulative").print_stats(18)
                # (1.76.46) and who calls the heaviest functions of their own: «argsort 95 s» alone said nothing of
                # where (Luca: «tutto super lento»)
                st_.sort_stats("tottime").print_callers(4)
                core.log("SIMPLER_PROFILE", job.key, f"{(time.time() - t0) * 1000:.0f} ms\n" + out.getvalue()[-12000:])
                if os.path.isdir(_PROFILE):                 # (a folder: the whole profile kept for a closer look)
                    pr.dump_stats(os.path.join(_PROFILE, f"{int(t0 * 1000)}_{job.key.replace('/', '_').replace(' ', '_')}.prof"))
    return _run_job_(job)


def _same_matrices(d):
    """True when every matrix sent is the one the object already has (within a hair)."""
    try:
        d = d or {}
        items = d.get("items") if isinstance(d.get("items"), list) else [{"id": d.get("id"), "matrix": d.get("matrix")}]
        if not items:
            return False
        for it in items:
            ob = core.find(it.get("id"))
            v = it.get("matrix")
            if ob is None or not isinstance(v, list) or len(v) != 16:
                return False
            mw = ob.matrix_world
            if any(abs(float(v[c * 4 + r]) - mw[r][c]) > 1e-6 for c in range(4) for r in range(4)):
                return False
        return True
    except Exception:  # noqa: BLE001 - anything unusual: let the command run as always
        return False


def _run_job_(job):
    handler, changes_image, _timeout = ROUTES[job.key]
    step = None
    t0 = time.time()
    try:
        models.lock_check(job.key, job.data)
        if job.key in UNDOABLE and not job.data.get("noUndo"):
            kind, label, ids_fn = UNDOABLE[job.key]
            if kind == "rainpaint" and (job.data or {}).get("layer") == "snow":   # (the same brush paints the snow)
                label = {"Pozzanghere dipinte": "Neve dipinta", "Cancella pozzanghere dipinte": "Cancella la neve dipinta"}.get(label, label)
            step = history.begin(kind, label, ids_fn(job.data) if ids_fn else None)
        if job.key in ("POST /api/matrices", "POST /api/matrix") and _same_matrices(job.data):
            # (Luca: «quando clicco su un oggetto parte il box rosso … non puoi fare una verifica preventiva») the
            # objects are already there: nothing to do, no undo step, no update of the scene (rain, materials, path
            # tracing) - whoever sends it (a gizmo released without moving, a panel, an older view)
            if step is not None:
                history.cancel(step)
                step = None
            job.result = {"unchanged": True}
            return
        _tc = time.time()
        job.result = handler(job.data)
        job._cmd_s = time.time() - _tc
        if changes_image and not job.key.startswith(("POST /api/terrain/", "POST /api/camera", "POST /api/settings")):
            # (1.76.4) a material dropped on a zone of a terrain, or edited there: its border blend follows
            tb = terrain.sync_all()
            if tb and isinstance(job.result, dict):
                job.result = dict(job.result)
                job.result["terrainBlend"] = tb
        if changes_image and job.key.startswith(("POST /api/terrain/", "POST /api/transform", "POST /api/matrices",
                                                  "POST /api/undo", "POST /api/redo", "POST /api/delete")):
            # (1.76.16) the sea at the foot of a terrain follows it (made, changed, moved, removed, undone)
            try:
                from . import ocean as _ocean
                of = _ocean.follow_terrain()
            except Exception as exc:  # noqa: BLE001
                of = None
                print("SIMPLER_OCEAN follow", exc, flush=True)
            if of is not None and isinstance(job.result, dict):
                job.result = dict(job.result)
                job.result["oceanFollow"] = of
        if job.key in ("POST /api/save", "POST /api/open", "POST /api/new"):
            _mark_saved()                         # the scene now matches a file (or is a fresh scene)
            if job.key == "POST /api/open" and job.data.get("recovered"):
                CHANGES["n"] += 1                 # (an automatic copy opened: not saved in the project yet)
        elif _changes_scene(job.key, job.data or {}) and not (isinstance(job.result, dict) and job.result.get("kind") == "selection") \
                and not (job.key == "POST /api/views/ptthumb" and not (job.result or {}).get("replaced")):
            CHANGES["n"] += 1                     # (undoing a lost selection changes nothing to save)
            if job.key == "POST /api/camview/refresh" and views.APPLIED["n"] == CHANGES["n"] - 1:
                # (1.78.4, Luca: «ha finito ma la miniatura non si è aggiornata») «Ricalcola dalla vista» before a path
                # tracing follows the framing of the scene itself: not a change of the scene for its thumbnail
                views.APPLIED["n"] = CHANGES["n"]
        if job.key == "POST /api/views/apply" or (job.key == "POST /api/views/ptthumb" and (job.result or {}).get("replaced")):
            # (1.75.57) the scene just opened (or its new thumbnail, a change of ours): the count from here
            views.APPLIED.update(id=(job.data or {}).get("id"), n=CHANGES["n"])
        elif job.key in ("POST /api/views/save", "POST /api/views/update") and isinstance(job.result, dict) \
                and (job.result.get("view") or {}).get("id"):
            # (1.76.37, Luca: «scena finita ma la miniatura non si aggiorna con il path tracer») a scene just saved or
            # updated from the view is the one shown too: its finished path tracing becomes its thumbnail (before, only
            # a scene opened from its thumbnail)
            views.APPLIED.update(id=job.result["view"]["id"], n=CHANGES["n"])
        if step is not None:
            if step["kind"] == "normals":
                job.result = dict(job.result or {})
                step["flipped"] = job.result.pop("undo", {})
            history.commit(step)
            step = None
            job.result = dict(job.result or {})
            job.result["history"] = history.status()
        if changes_image:
            if job.key not in ("POST /api/camera", "POST /api/settings"):
                # (moving the camera does not make the rain look at the materials again; painting dirt changes no
                # shape: only the materials)
                rain.touch(geometry=_changes_geometry(job))
            if render.STATE.caustics:
                render.apply_caustics(True)  # new glass/lights follow the switch
            render.invalidate()
    except ApiError as exc:
        job.error = str(exc)
    except Exception as exc:  # unexpected: report, keep the engine alive
        traceback.print_exc()
        job.error = tr("Errore interno: {0}", exc)
    finally:
        if step is not None:
            history.cancel(step)
        ms = int((time.time() - t0) * 1000)
        waited = int((t0 - job.__dict__.get("t_put", t0)) * 1000)
        if ms >= 300 or waited >= 300:
            # (1.75.26) and how much of it was the command itself, the undo step and what follows it; (1.79.0, Luca:
            # «ho portato lo slider ... non è successo nulla ... solo dopo aver mosso la viewport è partito») and how
            # long it waited before the engine took it
            core.log("SIMPLER_SLOW", job.key, f"{ms} ms", f"(command {int(job.__dict__.get('_cmd_s', 0) * 1000)} ms, waited {waited} ms)")
        job.done.set()


def _watch_parent(pid):
    """Exit when Simpler.exe goes away (also after a crash): no orphan Blender processes."""
    import ctypes
    if os.name != "nt" or not pid:
        return
    kernel32 = ctypes.windll.kernel32
    handle = kernel32.OpenProcess(0x00100000, False, int(pid))  # SYNCHRONIZE
    if not handle:
        STOP.set()
        return
    kernel32.WaitForSingleObject(handle, 0xFFFFFFFF)
    STOP.set()


def _maybe_sky_table():
    """Development: with test_out/tabella_cielo.on in the Simpler folder, the table of sky colours of "Colori da una
    foto" (sky_table_job.py) is made in a second Blender in the background, progress in test_out/tabella_cielo.txt."""
    import subprocess
    root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    flag = os.path.join(root, "test_out", "tabella_cielo.on")
    log = os.path.join(root, "test_out", "tabella_cielo.txt")
    SKYTABLE["log"] = log
    if not os.path.isfile(flag):
        return
    # the flag stays until the table is complete (the job removes it): closed half way, it goes on next time.
    # A job still running from a session before (a second Blender lives on its own): not started twice
    if os.path.isfile(log) and time.time() - os.path.getmtime(log) < 180:
        core.log("SIMPLER_SKYTABLE", "still running from before")
        return
    script = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "sky_table_job.py")
    cmd = [bpy.app.binary_path, "--factory-startup", "-b", "--python", script, "--", render.STATE.device, log]
    flags = (0x08000000 | 0x00004000) if os.name == "nt" else 0       # no window, below normal priority
    out = open(os.path.join(root, "test_out", "tabella_cielo.log"), "w", encoding="utf-8", errors="replace")
    try:
        os.remove(log)                     # (the progress of this run only)
    except OSError:
        pass
    SKYTABLE.update(proc=fullspeed.popen(cmd, stdout=out, stderr=subprocess.STDOUT, creationflags=flags), log=log)
    core.log("SIMPLER_SKYTABLE", "started in the background")


SKYTABLE = {"proc": None, "log": ""}


def skytable_status(_d=None):
    """GET skytable: the table of sky colours being made in the background (for the status bar of the app)."""
    import re
    proc = SKYTABLE["proc"]
    log = SKYTABLE["log"]
    fresh = bool(log) and os.path.isfile(log) and time.time() - os.path.getmtime(log) < 180
    if proc is None and not fresh:
        return {"active": False}
    running = proc.poll() is None if proc is not None else fresh
    last = ""
    try:
        with open(SKYTABLE["log"], encoding="utf-8") as f:
            lines = [ln.strip() for ln in f if ln.strip()]
        last = lines[-1] if lines else ""
    except OSError:
        pass
    m = re.search(r"(\d+)/(\d+) .*about (\d+) min left", last)
    out = {"active": True, "running": running, "finished": "done:" in last, "failed": (not running and "done:" not in last)}
    if m:
        out.update(done=int(m.group(1)), total=int(m.group(2)), minutes=int(m.group(3)))
    elif "start:" in last:
        out.update(done=0, total=int(re.search(r"start: (\d+)", last).group(1)), minutes=-1)
    return out


def serve(port=8787, new_scene=True, parent_pid=0):
    progress.install()
    breaker.install()
    from . import tempdirs
    threading.Thread(target=lambda: core.log("SIMPLER_TEMP", "old temporary folders removed:", tempdirs.sweep()),
                     daemon=True).start()       # (left by the engines before: closed by the app, never cleaned - 1.74.0)
    print("SIMPLER_BREAK", breaker.info(), flush=True)
    if new_scene:
        project_new({})
    else:
        render.setup_device()
    ThreadingHTTPServer.request_queue_size = 128   # the UI polls often: don't refuse connections under load
    httpd = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    httpd.daemon_threads = True
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    if parent_pid:
        threading.Thread(target=_watch_parent, args=(parent_pid,), daemon=True).start()
    core.log("SIMPLER_CLOCK", "engine ready")
    print(f"SIMPLER_READY port={port} device={render.STATE.device} blender={bpy.app.version_string}", flush=True)
    _maybe_sky_table()

    last_job = 0.0
    while not STOP.is_set():
        ran = False
        while True:
            try:
                job = JOBS.get_nowait()
            except queue.Empty:
                break
            BUSY["job"], BUSY["t0"] = job.key, time.time()
            try:
                _run_job(job)
            finally:
                BUSY["job"] = None
            ran = True
            last_job = time.time()
        # a short pause after commands: the app usually sends a few in a row (command, then scene and history);
        # (1.76.50) longer in a scene whose path tracing takes seconds to prepare (that part cannot be interrupted): a
        # few changes in a row (strokes, sliders, a camera moved and moved again) then wait for one preparation, not
        # one each - 2,300 s of «Path tracing: Preparazione della scena» in Luca's logs
        pause = 0.25 if render.STATE.last_prep < render.PREP_SLOW else min(2.0, 0.5 * render.STATE.last_prep)
        if render.viewport_needs_pass() and time.time() - last_job > pause:
            try:
                render.render_viewport_pass()
            except Exception as ex:
                traceback.print_exc()
                render.STATE.vp_error = str(ex) or ex.__class__.__name__
                render.STATE.dirty = False
        elif not ran:
            try:
                if rain.idle_due(last_job):
                    BUSY["job"], BUSY["t0"] = "rain", time.time()
                busy = rain.idle(last_job)        # the shelter of the rain follows the geometry (rain.py)
            except Exception:
                traceback.print_exc()
                busy = False
            finally:
                if BUSY["job"] == "rain":
                    BUSY["job"] = None
            if not busy:
                time.sleep(0.01)
    httpd.shutdown()
    proxies.stop()
    previews.stop()
    print("SIMPLER_STOPPED", flush=True)
