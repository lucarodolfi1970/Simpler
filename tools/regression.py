"""Regression and performance suite of the engine, run before every release.

Starts the engine on a scene, runs the same scenarios every time (the features that combine: Ambiente, rain, snow
and its mantle, sea and coast, ecosystems, undo/redo, the export of the view), waits for the idle work after each
step (shelter, mantle, coast) and records for every step: time, idle time after it, memory of the engine, errors.
Then compares with a baseline (another version of Simpler, or the last release) and says what got slower.

    python3 tools/regression.py --scene S.simpler [--scene ...] --out report.json [--base old.json]
                                [--engine engine_dir] [--eco eco_lib_dir] [--port 8811]

A step fails when it answers with an error, when the engine writes a traceback, or (with --base) when it is slower
than the baseline by more than 50% and 0.5 s. Steps that a version does not have (a route missing) are «skip».
"""
import argparse
import json
import re
import os
import shutil
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _test_model(eng, args):
    """(1.76.18) A small library model (--eco/../models) copied into the test engine's library: its id, or None."""
    src_models = os.path.join(os.path.dirname(os.path.normpath(args.eco)), "models")
    if not os.path.isdir(src_models):
        return None
    cands = sorted((os.path.getsize(os.path.join(src_models, m, "model.blend")), m) for m in os.listdir(src_models)
                   if os.path.isfile(os.path.join(src_models, m, "model.blend")) and os.path.isfile(os.path.join(src_models, m + ".json")))
    if not cands:
        return None
    mid = cands[0][1]
    lib = os.path.join(eng.tmp, "rad", "Simpler", "models")
    os.makedirs(lib, exist_ok=True)
    if not os.path.isdir(os.path.join(lib, mid)):
        shutil.copytree(os.path.join(src_models, mid), os.path.join(lib, mid))
        shutil.copy(os.path.join(src_models, mid + ".json"), os.path.join(lib, mid + ".json"))
    return mid


PERF_LIMITS = {"update": 30.0, "refresh": 20.0}      # (1.76.47) seconds, see PERFTERR


def _test_eco(eng, args):
    """(1.76.15) An ecosystem the test engine can place: the first one of --eco with its models replaced by a small
    library model shipped next to it (--eco/../models), copied into the engine's library. None when there is none."""
    src_models = os.path.join(os.path.dirname(os.path.normpath(args.eco)), "models")
    ids = sorted(n for n in os.listdir(args.eco) if n.startswith("e_"))
    if not ids or not os.path.isdir(src_models):
        return None
    cands = sorted((os.path.getsize(os.path.join(src_models, m, "model.blend")), m) for m in os.listdir(src_models)
                   if os.path.isfile(os.path.join(src_models, m, "model.blend")) and os.path.isfile(os.path.join(src_models, m + ".json")))
    if not cands:
        return None
    mid = cands[0][1]
    lib = os.path.join(eng.tmp, "rad", "Simpler", "models")
    os.makedirs(lib, exist_ok=True)
    if not os.path.isdir(os.path.join(lib, mid)):
        shutil.copytree(os.path.join(src_models, mid), os.path.join(lib, mid))
        shutil.copy(os.path.join(src_models, mid + ".json"), os.path.join(lib, mid + ".json"))
    with open(os.path.join(args.eco, ids[0], "eco.json"), encoding="utf-8") as fh:
        e = json.load(fh)
    for layer in e.get("layers") or []:
        layer["models"] = [mid for _m in layer.get("models") or []]
        if layer.get("palette"):
            layer["palette"] = [dict(p, model=mid) for p in layer["palette"]]
    eid = "e_regtest00"
    d = os.path.join(eng.tmp, "rad", "Simpler", "ecosystems", eid)
    os.makedirs(d, exist_ok=True)
    with open(os.path.join(d, "eco.json"), "w", encoding="utf-8") as fh:
        json.dump(e, fh)
    return eid


class Engine:
    def __init__(self, engine_dir, scene, port, eco):
        self.base = f"http://127.0.0.1:{port}/api/"
        self.tmp = tempfile.mkdtemp(prefix="simpler_reg_")
        lad, rad = os.path.join(self.tmp, "lad"), os.path.join(self.tmp, "rad")
        os.makedirs(os.path.join(rad, "Simpler", "models"), exist_ok=True)
        if eco:
            shutil.copytree(eco, os.path.join(rad, "Simpler", "ecosystems"))
        env = dict(os.environ, LOCALAPPDATA=lad, APPDATA=rad)
        self.log = os.path.join(self.tmp, "engine.out")
        self.proc = subprocess.Popen([sys.executable, "start_engine.py", "--port", str(port), "--open", scene],
                                     cwd=engine_dir, env=env, stdout=open(self.log, "w"), stderr=subprocess.STDOUT)
        self.peak = 0

    def rss(self):
        try:
            with open(f"/proc/{self.proc.pid}/status") as f:
                for line in f:
                    if line.startswith("VmRSS"):
                        v = int(line.split()[1]) / 1e6
                        self.peak = max(self.peak, v)
                        return v
        except OSError:
            pass
        return 0.0

    def call(self, method, path, body=None, timeout=1800):
        req = urllib.request.Request(self.base + path, method=method,
                                     data=None if body is None else json.dumps(body).encode(),
                                     headers={"Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=timeout) as r:
                raw = r.read()
                try:
                    return json.loads(raw or b"{}"), None
                except ValueError:
                    return {"bytes": len(raw)}, None
        except urllib.error.HTTPError as e:
            txt = e.read()[:400].decode("utf8", "replace")
            if e.code == 404:
                return None, "404"
            return None, txt
        except Exception as e:  # noqa: BLE001
            return None, str(e)

    def idle(self, limit=600):
        """Waits until the engine has nothing to do (also its idle work); seconds waited."""
        t0 = time.time()
        quiet = 0
        while time.time() - t0 < limit:
            r, _ = self.call("GET", "busy", timeout=10)
            if r is not None and not r.get("busy"):
                quiet += 1
                if quiet >= 3:                  # (the idle work starts 0.6 s after the last command)
                    return time.time() - t0 - 0.9
            else:
                quiet = 0
            time.sleep(0.3)
            self.rss()
        return time.time() - t0

    def tracebacks(self):
        try:
            with open(self.log, encoding="utf8", errors="replace") as f:
                return f.read().count("Traceback")
        except OSError:
            return 0

    def stop(self, keep=False):
        self.proc.terminate()
        try:
            self.proc.wait(20)
        except subprocess.TimeoutExpired:
            self.proc.kill()
        if not keep:
            # (1.74.0) the folders of the check went never away: 2415 of them with the engine's, 12 GB
            shutil.rmtree(self.tmp, ignore_errors=True)


# answers that are right for some scenes (the sea added to the cathedral covers its ground: nothing grows there)
EXPECTED = ("sotto il livello del mare", "below sea level")


DIRT = {"points": [[0.0, 0.0, 0.0, 0, 0, 1]], "radius": 0.4, "mode": "add", "preset": "uniforme", "strength": 1.0,
        "materials": [], "probe": [0.1, 0.0, 0.0, 0, 0, 1]}
# a stroke 30 cm higher (a step) whose edge reaches the first: the floor keeps its dirt
DIRT_STEP = dict(DIRT, points=[[0.55, 0.0, 0.3, 0, 0, 1]])


# (1.74.0) a change of the app only (interface, texts): the engine is the same - open, check, save and reopen
QUICK = ("scene", "selfcheck_open", "quiet_open", "temp_sweep", "save", "reopen", "selfcheck_reopen", "ph_to_brush")


def scenarios(st):
    """The steps: (name, method, path, body or a function of the state). Kept in this order across versions."""
    ground = lambda s: s.get("ground")
    return [
        ("scene", "GET", "scene", None),
        ("selfcheck_open", "GET", "selfcheck", None),
        ("quiet_open", "QUIET", "", None),
        ("temp_sweep", "TEMP", "", None),
        ("ambience", "GET", "ambience", None),
        ("rain_on", "POST", "ambience", {"rain": {"wet": 0.6, "puddles": 0.3}}),
        ("rain_off", "POST", "ambience", {"rain": {"wet": 0.0, "puddles": 0.0}}),
        ("snow_on", "POST", "ambience", {"snow": {"amount": 0.7, "depth": 0.1}}),
        ("snow_off", "POST", "ambience", {"snow": {"amount": 0.0}}),
        ("ocean_add", "POST", "landscape/ocean", {"preset": "mosso"}),
        ("ocean_height", "POST", "landscape/ocean", {"settings": {"height": 2.0}}),
        ("ocean_wind", "POST", "landscape/ocean", {"settings": {"wind": 16}}),
        ("ocean_calm", "POST", "landscape/ocean", {"preset": "calmo"}),
        ("ocean_mesh", "GET", "ocean/mesh", None),
        ("undo", "POST", "undo", {}),
        ("redo", "POST", "redo", {}),
        ("snow_with_sea", "POST", "ambience", {"snow": {"amount": 0.7, "depth": 0.1}}),
        ("snow_off2", "POST", "ambience", {"snow": {"amount": 0.0}}),
        ("eco_count", "POST", "ecosystems/count", lambda s: {"id": s["eco"], "target": ground(s), "camOnly": True} if s.get("eco") and ground(s) else None),
        ("eco_count_far", "POST", "ecosystems/count", lambda s: {"id": s["eco"], "target": ground(s), "camOnly": True, "camFalloff": 0.7} if s.get("eco") and ground(s) else None),
        ("eco_falloff", "ECOFALL", "", None),
        ("eco_on_model", "POST", "ecosystems/count", lambda s: {"id": s["eco"], "target": s["model"], "camOnly": True} if s.get("eco") and s.get("model") else None),
        ("coast_off", "POST", "landscape/ocean", {"settings": {"coast": False}}),
        ("coast_on", "POST", "landscape/ocean", {"settings": {"coast": True}}),
        ("render_small", "POST", "render", lambda s: {"path": os.path.join(s["tmp"], "r.png"), "width": 160, "height": 90,
                                                      "samples": 8, "denoise": False, "inProcess": True}),
        ("export_view", "POST", "preview", {"noCache": True}),
        ("selfcheck_steps", "GET", "selfcheck", None),
        ("quiet_steps", "QUIET", "", None),
        # saved and opened again (what lives in temporary folders, what the check of the textures at opening does)
        ("save", "POST", "save", lambda s: {"path": os.path.join(s["tmp"], "again.simpler")}),
        ("reopen", "POST", "open", lambda s: {"path": os.path.join(s["tmp"], "again.simpler")}),
        ("selfcheck_reopen", "GET", "selfcheck", None),
        ("render_reopen", "POST", "render", lambda s: {"path": os.path.join(s["tmp"], "r2.png"), "width": 160, "height": 90,
                                                       "samples": 8, "denoise": False, "inProcess": True}),
        ("selfcheck_render", "GET", "selfcheck", None),
        # (1.73.9) painted dirt: going over a painted part again erased it, and every stroke made the shelter of the
        # rain (and mantle, coast) again - with the rain on, a stroke must leave the engine with nothing to do
        ("rain_on2", "POST", "ambience", {"rain": {"wet": 0.6, "puddles": 0.3}}),
        ("dirt_paint", "POST", "dirt/paint", DIRT),
        ("dirt_repaint", "POST", "dirt/paint", DIRT),
        ("dirt_step", "POST", "dirt/paint", DIRT_STEP),
        ("dirt_clear", "POST", "dirt/paint/clear", {}),
        ("rain_off2", "POST", "ambience", {"rain": {"wet": 0.0, "puddles": 0.0}}),
        ("ph_to_brush", "PHLIB", "", None),
        # (1.75.10) «Luce riflessa dall'acqua» off and on again with the rain on: the same image as the first time
        # (the rain kept its cache and the bottom of the sea came back darker, without caustics - Luca, «test oceano»)
        ("sea_glow_offon", "SEAGLOW", "", None),
        # (1.75.23) the samples of a final render with tiles: Cycles writes the next tile with the samples of the last
        # one still at the end, and the chart of the samples jumped a tile ahead and stayed there (Luca, 4K, 4 tiles)
        ("tile_samples", "TILEPROG", "", None),
        # (1.75.23) a final render whose file cannot be written (open in another program): Blender went on as if
        # nothing were wrong and Simpler showed the old file with that name - now saved next to it with a number
        ("render_locked", "RENDERLOCK", "", None),
        # (1.75.42) the keyframes of the AI video and the saved scenes they come from: always copies (renaming, updating
        # or deleting the scene never changes them), the scene told by its id - a deleted one is not replaced by
        # another with the same name
        ("video_frame_views", "VIDFRAMES", "", None),
        # (1.75.52) «Ottimizza poligoni»: fewer triangles, the same pieces and materials; Ctrl+Z gives the model back
        ("decimate", "DECIMATE", "", None),
        # (1.75.57) the finished path tracing of a scene just opened becomes its thumbnail - not when something changed,
        # and the date of the scene stays (the keyframes of the AI video look at it)
        ("pt_thumb", "PTTHUMB", "", None),
        # (1.75.60) the scale of a single map (glossiness over many tiles): kept in the material, sent to the view
        ("map_scale", "MAPSCALE", "", None),
        # (1.76.0) the terrain: one mesh per zone, made again by a change, Ctrl+Z gives the one before and then removes it
        ("terrain", "TERRAIN", "", None),
        # (1.76.8) «Dividi zona»: a part of the meadow by the ground (wet hollows), changed, taken away, Ctrl+Z
        ("terrain_split", "TERRSPLIT", "", None),
        # (1.76.2) an ecosystem past the edge of its surface (a lawn into the gravel next to it), and the far pieces
        # thinned instead of left out (a hill behind with no grass at all - Luca)
        ("eco_spill", "ECOSPILL", "", None),
        # (1.76.15) an ecosystem on a zone of a terrain: made again when the terrain changes (new layers), the old ones
        # back with Ctrl+Z (Luca: the pieces stayed where they were - buried, in the air)
        ("terrain_eco", "TERRECO", "", None),
        # (1.76.16) the sea at the foot of a terrain: added there, follows it when moved, Ctrl+Z; set by hand: stays
        ("terrain_ocean", "TERROCEAN", "", None),
        ("eco_bench", "ECOBENCH", "", None),
        ("ocean_follow", "OCEANFOLLOW", "", None),
        ("rock_relief", "ROCKRELIEF", "", None),
        ("rock_kinds", "ROCKKINDS", "", None),
        ("rock_disp", "ROCKDISP", "", None),
        ("mat_edit_fast", "MATEDITFAST", "", None),
        ("rock_map", "ROCKMAP", "", None),
        # (1.77.0) type «Fogliame»: the season moves the leaves step by step (autumn colours, then fewer leaves), winter
        # leaves nothing; the wood is not touched by the season; the view gets it too; an edit answers at once
        ("foliage", "FOLIAGE", "", None),
        # (1.77.1) type «Tessuto»: the fuzz shows, a thin cloth lets one see through, the view gets it; edits at once
        ("fabric", "FABRIC", "", None),
        # (1.78.0) «Importa vegetazione»: a plant imported into the library, its leaves and wood recognised (by name and
        # by colour), Fogliame on them, the plant in Vegetazione/<kind>; «Foglie e legno…» changes one by hand
        ("vegetation", "VEGETATION", "", None),
        # (1.78.1, Luca: «convert to vegetation serve anche nella viewport») an object of the scene made a plant; Ctrl+Z
        ("scene_veg", "SCENEVEG", "", None),
        # (1.78.2) Impostazioni > Cartelle: ecosystems and the user's decals have their own folder; moving the models
        # does not take the ecosystems away any more
        ("paths_folders", "PATHSFOLDERS", "", None),
        # (1.78.4, Luca) settings «SimplerLocked» = 1: the Simpler parts of the library are read only (the engine refuses
        # every change there); 0: normal folders
        ("simpler_lock", "SIMPLERLOCK", "", None),
        # (1.76.18) «Appoggia alla superficie»: pieces of a distribution in the air dropped on the terrain; when the
        # terrain changes they follow by themselves; Ctrl+Z
        ("paint_drop", "PAINTDROP", "", None),
        # (1.78.4, Luca: «il senso del gizmo viola è poter spostare dove voglio il gizmo») the pivot placed by hand on a
        # library model is kept in the library: a new copy and the distributions (also one made before) stand on it
        ("pivot_paint", "PIVOTPAINT", "", None),
        # (1.78.4, Luca: «problema di opacità con plantfactory») a «…_Transparency» picture on the Alpha: an inverted
        # opacity map (tools/transparency_check.py, in Blender)
        ("transp_map", "TRANSPMAP", "", None),
        # (1.78.4, Luca: «foglie fucsia in realtime») pictures renumbered by Blender: the channels follow them
        ("heal_names", "TRANSPMAP", "heal_check.py", None),
        # (1.78.4, Luca: «cambio lo slider stagione e boom foglie bianche») a black imported emission stays off
        ("emission_black", "TRANSPMAP", "emission_check.py", None),
        # (1.78.4, Luca: flowers yellow in path tracing and violet in the real-time view; Rumex solid cards) pictures of
        # the view by what they are, not by their name; GIF masks as still pictures
        ("texture_names", "TRANSPMAP", "texname_check.py", None),
        # (1.78.4, Luca: a folder deleted with its models inside, the models stayed) folder delete with its models
        ("folder_delete", "TRANSPMAP", "folderdelete_check.py", None),
        # (1.78.4, Luca: actions allowed in the red Simpler folders) every change refused by the engine when locked
        ("simpler_lock", "TRANSPMAP", "lock_check.py", None),
        # (1.78.4) packs of models: install, uninstall, reinstall, over, update, shared, refused (tools/packtest)
        ("packs", "PACKS", "", None),
        # (1.78.4, Luca: square cuts in the snow along the kerb) the sheet over a kerb off the grid
        ("snow_kerb", "TRANSPMAP", "kerb_check.py", None),
        # (1.78.4, Luca: «snow brush… parte subito un'elaborazione con questo shelter rain») a stroke of painted snow
        # makes the mantle again but never the shelter of the rain (nor the coast): no shape changed
        ("snow_paint", "SNOWPAINT", "", None),
        # (1.76.22) «Pietre e detriti»: stones of the test library at the foot of the walls and in the gullies of a
        # terrain, their colour moved to the rock's; made again with the terrain; Ctrl+Z
        ("scree", "SCREE", "", None),
        # (1.76.23) a Poly Haven model with levels of detail: their list, only the chosen one placed, one library
        # entry per level (Luca: all the LODs came in the scene, one inside the other)
        ("ph_lod", "PHLOD", "", None),
        # (1.76.25) real elevation files as terrains (Luca: «i file .dem ... possiamo sfruttarli?»): an ESRI grid and an
        # SRTM tile made here - the true width and relief, no erosion added
        ("terrain_dem", "TERRDEM", "", None),
        # (1.76.44, Luca: «il pennello per alzare e abbassare la geometria del terreno») «Scultura»: raise, lower and
        # smooth with the same numbers as the view (SCULPT_RATE: 100 dabs of 10 m at 100% = 30 m), Ctrl+Z, the strokes
        # kept by «Un'altra versione», «Togli tutte le modifiche»
        ("terrain_sculpt", "TERRSCULPT", "", None),
        # (1.76.47, Luca: «tutto super super lento ... simpler lento equivale a nessuno lo userà») the times of the
        # terrain with an ecosystem: made again after a sculpting (its materials must not be made again for nothing,
        # its ecosystem made again in seconds) and «Ricalcola dalla vista»; over the limits = a regression
        ("perf_terrain", "PERFTERR", "", None),
        # (1.76.50) «Sfumatura dei bordi» changed: the numbers set on a copy of each material (not the trees made
        # again: 28 s in Luca's logs), the same picture as made again, Ctrl+Z
        ("blend_inplace", "BLENDINPLACE", "", None),
        ("terrain_reopen", "TERRREOPEN", "", None),
        # (1.76.7) the folders next to a project: the textures it no longer uses (after the save before) to the
        # Recycle Bin, and a save over another project takes the old one away first
        ("project_files", "PROJFILES", "", None),
        ("ocean_remove", "POST", "landscape/ocean", {"on": False}),
    ]


def _fake_textures(root, zones):
    """Tiny textures for the zones of a terrain (with an opacity map, as leafy_grass has) in the test library."""
    import struct, zlib

    def png(path, rgb):
        raw = b"".join(b"\0" + bytes(rgb) * 8 for _ in range(8))
        ch = lambda t, d: struct.pack(">I", len(d)) + t + d + struct.pack(">I", zlib.crc32(t + d) & 0xffffffff)
        with open(path, "wb") as f:
            f.write(b"\x89PNG\r\n\x1a\n" + ch(b"IHDR", struct.pack(">IIBBBBB", 8, 8, 8, 2, 0, 0, 0))
                    + ch(b"IDAT", zlib.compress(raw)) + ch(b"IEND", b""))
    aids = [z.get("texture") for z in zones.values()] + [z.get("macroTexture") for z in zones.values()]
    for aid in dict.fromkeys(a for a in aids if a):
        d = os.path.join(root, aid)
        os.makedirs(d, exist_ok=True)
        maps = {}
        for ch_, rgb in (("color", (90, 120, 60)), ("normal", (128, 128, 255)), ("alpha", (40, 40, 40))):
            maps[ch_] = os.path.join(d, ch_ + ".png")
            png(maps[ch_], rgb)
        with open(os.path.join(d, "maps.json"), "w") as f:
            json.dump(maps, f)


def run_scene(args, scene):
    eng = Engine(args.engine, scene, args.port, args.eco)
    out = {"scene": os.path.basename(scene), "steps": [], "errors": 0}
    try:
        t0 = time.time()
        while time.time() - t0 < 900:
            r, err = eng.call("GET", "ping", timeout=5)
            if r is not None:
                break
            time.sleep(1)
        out["open"] = round(time.time() - t0, 2)
        out["open_idle"] = round(eng.idle(), 2)
        state = {"tmp": eng.tmp}
        sc, _ = eng.call("GET", "scene")
        for o in (sc or {}).get("objects", []) if isinstance(sc, dict) else []:
            if str(o.get("name", "")).startswith(("Suolo", "Ground")):
                state["ground"] = o.get("id")
            elif not o.get("parent") and o.get("kind") in ("group", "model") and "model" not in state:
                state["model"] = o.get("id")        # (a model of the library: picked as a whole, a group)
        if args.eco:
            ids = sorted(n for n in os.listdir(args.eco) if n.startswith("e_"))
            state["eco"] = ids[0] if ids else None
        steps = scenarios(state)
        if args.quick:
            steps = [st for st in steps if st[0] in QUICK]
        skip = {x.split(":", 1)[1] for x in args.skip if x.split(":", 1)[0] == os.path.basename(scene)}
        steps = [st for st in steps if st[0] not in skip]
        if getattr(args, "only", None):
            steps = [st for st in steps if st[0] in args.only]
        for name, method, path, body in steps:
            if callable(body):
                body = body(state)
                if body is None:
                    out["steps"].append({"step": name, "status": "skip"})
                    continue
            if method == "TEMP":
                # (1.74.0) the temporary folders of the engines before (killed, never cleaned) removed at the start
                sys.path.insert(0, os.path.join(args.engine, "simpler"))
                import tempdirs
                left = []
                for _ in range(60):
                    left = tempdirs.stale()
                    if not left:
                        break
                    time.sleep(1)
                rec = {"step": name, "secs": 0.0, "idle": 0.0, "rssGB": round(eng.rss(), 2), "status": "ok" if not left else "FAIL"}
                if left:
                    rec["error"] = f"{len(left)} temporary folders of engines gone still there: {left[0]}"
                    out["errors"] += 1
                out["steps"].append(rec)
                print(f"  {name:16s} {rec['status']:5s}  {rec.get('error', '')}", flush=True)
                continue
            if method == "PHLIB":
                # (1.75.0) a Poly Haven model clicked with the brush of Distribuisci on went into the scene: it must
                # become a library model (once) and leave the scene as it was
                rec = {"step": name, "secs": 0.0, "idle": 0.0, "rssGB": round(eng.rss(), 2), "status": "ok"}
                d = os.path.join(eng.tmp, "lad", "Simpler", "library", "polyhaven", "models", "reg_shell")
                os.makedirs(d, exist_ok=True)
                subprocess.run([sys.executable, "-c", "import bpy,sys; bpy.ops.wm.read_factory_settings(use_empty=True); "
                                "bpy.ops.mesh.primitive_uv_sphere_add(radius=0.3); bpy.ops.wm.save_as_mainfile(filepath=sys.argv[1])",
                                os.path.join(d, "shell.blend")], capture_output=True)
                with open(os.path.join(d, "model.json"), "w") as f:
                    json.dump({"file": "shell.blend", "format": "blend", "v": 2}, f)
                n0 = len((eng.call("GET", "scene")[0] or {}).get("objects", []))
                t = time.time()
                r1, e1 = eng.call("POST", "library/models/tolibrary", {"id": "reg_shell"})
                r2, e2 = eng.call("POST", "library/models/tolibrary", {"id": "reg_shell"})
                rec["secs"] = round(time.time() - t, 3)
                n1 = len((eng.call("GET", "scene")[0] or {}).get("objects", []))
                if e1 == "404":
                    rec["status"] = "skip"
                elif e1 or e2 or not r1 or not r2 or r1.get("id") != r2.get("id") or n1 != n0:
                    rec["status"], rec["error"] = "FAIL", f"{e1 or e2 or ''} ids {r1 and r1.get('id')} / {r2 and r2.get('id')}, objects {n0} -> {n1}"[:300]
                    out["errors"] += 1
                out["steps"].append(rec)
                print(f"  {name:16s} {rec['status']:5s}  {rec.get('error', '')}", flush=True)
                continue
            if method == "VIDFRAMES":
                rec = {"step": name, "secs": 0.0, "idle": 0.0, "rssGB": round(eng.rss(), 2), "status": "ok"}
                t = time.time()

                def fr():
                    r, _e = eng.call("GET", "video/frames")
                    return (r or {}).get("start") or {}
                bad = []
                a = ((eng.call("POST", "views/save", {"name": "reg A"})[0] or {}).get("view") or {}).get("id")
                eng.call("POST", "views/apply", {"id": a})
                eng.call("POST", "video/frame/save", {"slot": "start", "view": a})
                raw = (eng.call("GET", "video/frames/raw")[0] or {}).get("frames", {})
                cam0 = (raw.get("start") or {}).get("snapshot", {}).get("camera")
                eng.call("POST", "views/rename", {"id": a, "name": "reg A2"})
                if fr().get("viewName") != "reg A2":
                    bad.append(f"rename not shown: {fr()}")
                eng.call("POST", "views/update", {"id": a})
                if not fr().get("viewChanged"):
                    bad.append("update not seen")
                eng.call("POST", "views/delete", {"id": a})
                b = ((eng.call("POST", "views/save", {"name": "reg A2"})[0] or {}).get("view") or {}).get("id")
                f = fr()
                if not f.get("viewGone") or f.get("viewId") == b:
                    bad.append(f"deleted scene taken for another with its name: {f}")
                _r, e1 = eng.call("POST", "video/frame/apply", {"slot": "start"})
                raw = (eng.call("GET", "video/frames/raw")[0] or {}).get("frames", {})
                if e1 or (raw.get("start") or {}).get("snapshot", {}).get("camera") != cam0:
                    bad.append(f"keyframe changed or not applied: {e1}")
                eng.call("POST", "views/delete", {"id": b})
                eng.call("POST", "video/frame/clear", {"slot": "start"})
                if bad:
                    rec["status"], rec["error"] = "FAIL", "; ".join(bad)[:300]
                    out["errors"] += 1
                rec["secs"] = round(time.time() - t, 2)
                out["steps"].append(rec)
                print(f"  {name:16s} {rec['status']:5s} {rec['secs']:8.2f} s  {rec.get('error', '')}", flush=True)
                continue
            if method == "MAPSCALE":
                rec = {"step": name, "secs": 0.0, "idle": 0.0, "rssGB": round(eng.rss(), 2), "status": "skip"}
                t = time.time()
                objs = (eng.call("GET", "scene")[0] or {}).get("objects", [])
                found = None
                for o in objs:
                    for mn in (o.get("materials") or [])[:4]:
                        ed = eng.call("GET", "material/edit?name=" + urllib.parse.quote(mn))[0] or {}
                        img = (((ed.get("params") or {}).get("color") or {}).get("map") or {}).get("image")
                        if img and not ed.get("advanced"):
                            found = (o["id"], mn, img)
                            break
                    if found:
                        break
                if found:
                    oid, mn, img = found
                    bad = []
                    _r, e1 = eng.call("POST", "material/edit", {"name": mn, "params": {"roughness": {"map": {"image": img, "scale": 3.0}}}})
                    ed = eng.call("GET", "material/edit?name=" + urllib.parse.quote(mn))[0] or {}
                    if e1 or ((ed.get("params") or {}).get("roughness") or {}).get("map", {}).get("scale") != 3.0:
                        bad.append(f"scale not kept: {e1}")
                    rt = ((eng.call("POST", "realtime/materials", {"ids": [oid]})[0] or {}).get("objects") or {}).get(oid) or []
                    sent = [((m or {}).get("maps") or {}).get("roughness") for m in rt if (m or {}).get("name", mn) == mn]
                    if not any(x and x.get("scale") == 3.0 for x in sent):
                        bad.append("scale not sent to the real-time view")
                    eng.call("POST", "undo", {})
                    rec["status"] = "ok"
                    if bad:
                        rec["status"], rec["error"] = "FAIL", "; ".join(bad)[:300]
                        out["errors"] += 1
                rec["secs"] = round(time.time() - t, 2)
                out["steps"].append(rec)
                print(f"  {name:16s} {rec['status']:5s} {rec['secs']:8.2f} s  {rec.get('error', '')}", flush=True)
                continue
            if method == "PTTHUMB":
                rec = {"step": name, "secs": 0.0, "idle": 0.0, "rssGB": round(eng.rss(), 2), "status": "ok"}
                t = time.time()
                import base64, io
                try:
                    from PIL import Image
                    buf = io.BytesIO(); Image.new("RGB", (64, 40), (200, 30, 30)).save(buf, "JPEG")
                    jpg = base64.b64encode(buf.getvalue()).decode()
                except ImportError:
                    jpg = ""
                bad = []
                vid = ((eng.call("POST", "views/save", {"name": "reg PT", "thumb": jpg})[0] or {}).get("view") or {}).get("id")
                # (1.76.37, Luca: «scena finita ma la miniatura non si aggiorna») a scene just saved, not opened: its
                # path tracing becomes its thumbnail too
                r0 = eng.call("POST", "views/ptthumb", {"id": vid, "thumb": jpg})[0] or {}
                if jpg and not r0.get("replaced"):
                    bad.append(f"a scene just saved: thumbnail not replaced ({r0.get('why')})")
                eng.call("POST", "views/apply", {"id": vid})
                before = next((v for v in (eng.call("GET", "views")[0] or {}).get("views", []) if v["id"] == vid), {})
                r1 = eng.call("POST", "views/ptthumb", {"id": vid, "thumb": jpg})[0] or {}
                after = next((v for v in (eng.call("GET", "views")[0] or {}).get("views", []) if v["id"] == vid), {})
                if jpg and not r1.get("replaced"):
                    bad.append(f"not replaced with nothing changed: {r1.get('why')}")
                if jpg and after.get("thumb") != jpg:
                    bad.append("thumbnail not the path-traced one")
                if after.get("updated") != before.get("updated"):
                    bad.append("the date of the scene changed")
                eng.call("POST", "ambience", {"rain": {"wet": 0.3}})
                r2 = eng.call("POST", "views/ptthumb", {"id": vid, "thumb": jpg})[0] or {}
                if r2.get("replaced"):
                    bad.append("replaced after the scene changed")
                eng.call("POST", "ambience", {"rain": {"wet": 0.0}})
                eng.call("POST", "views/delete", {"id": vid})
                if not jpg:
                    rec["status"] = "skip"
                elif bad:
                    rec["status"], rec["error"] = "FAIL", "; ".join(bad)[:300]
                    out["errors"] += 1
                rec["secs"] = round(time.time() - t, 2)
                out["steps"].append(rec)
                print(f"  {name:16s} {rec['status']:5s} {rec['secs']:8.2f} s  {rec.get('error', '')}", flush=True)
                continue
            if method == "DECIMATE":
                rec = {"step": name, "secs": 0.0, "idle": 0.0, "rssGB": round(eng.rss(), 2), "status": "ok"}
                t = time.time()
                mid = state.get("model")
                if not mid:          # (no library model: an imported one, or a piece, not the ground)
                    objs = (eng.call("GET", "scene")[0] or {}).get("objects", [])
                    mid = next((o.get("id") for o in objs if not o.get("parent") and o.get("kind") in ("file", "group", "mesh")
                                and o.get("id") != state.get("ground")), None)
                inf = lambda: (eng.call("GET", f"decimate/info?id={mid}")[0] or {})
                a = inf() if mid else {}
                if not a.get("distinct"):
                    rec["status"] = "skip"
                else:
                    bad = []
                    # (1.75.54) the 3D preview of the window: the reduced model exported without touching the scene
                    n0 = len((eng.call("GET", "scene")[0] or {}).get("objects", []))
                    v, ev = eng.call("POST", "decimate/view", {"id": mid, "which": "after", "ratio": 0.5})
                    if ev or not v or v.get("state") not in ("running", "done") or not v.get("triangles"):
                        bad.append(f"3D preview not made: {ev} {v}")
                    if len((eng.call("GET", "scene")[0] or {}).get("objects", [])) != n0:
                        bad.append("the 3D preview left objects in the scene")
                    _r, e1 = eng.call("POST", "decimate/apply", {"id": mid, "ratio": 0.5})
                    b = inf()
                    # (1.75.52) the view must be told which objects changed: without, it kept the old model
                    if not e1 and _r and _r.get("changed") and not _r.get("geometry"):
                        bad.append("apply did not say which objects changed (the view keeps the old model)")
                    if e1 or b.get("triangles", 0) >= a["triangles"] and a["distinct"] > 3000:
                        bad.append(f"not reduced: {e1} {a.get('triangles')} -> {b.get('triangles')}")
                    if b.get("materials") != a.get("materials") or b.get("pieces") != a.get("pieces"):
                        bad.append(f"materials/pieces changed: {a} -> {b}")
                    u = eng.call("POST", "undo", {})[0] or {}
                    if _r and _r.get("changed") and not u.get("geometry"):
                        bad.append("undo did not say which objects changed")
                    if inf().get("triangles") != a["triangles"]:
                        bad.append("undo did not give the model back")
                    if bad:
                        rec["status"], rec["error"] = "FAIL", "; ".join(bad)[:300]
                        out["errors"] += 1
                rec["secs"] = round(time.time() - t, 2)
                out["steps"].append(rec)
                print(f"  {name:16s} {rec['status']:5s} {rec['secs']:8.2f} s  {rec.get('error', '')}", flush=True)
                continue
            if method == "TERRAIN":
                rec = {"step": name, "secs": 0.0, "idle": 0.0, "rssGB": round(eng.rss(), 2), "status": "ok"}
                t = time.time()
                bad = []
                n0 = len((eng.call("GET", "scene")[0] or {}).get("objects", []))
                r, e = eng.call("POST", "terrain/create", {"preset": "pianura", "seed": 2}, timeout=900)
                eng.idle()
                if e or not r or not r.get("id"):
                    bad.append(f"not made: {e}")
                else:
                    # (1.76.3) the grid finer near the model (2 m with «Normale»), within the budget of points
                    gr = (r.get("info") or {}).get("grid") or {}
                    if not gr or gr.get("fine", 99) > 2.05 or max(gr.get("n") or [9999]) > 512:
                        bad.append(f"grid: {gr}")
                    st = eng.call("GET", f"terrain/state?id={r['id']}")[0] or {}
                    faces = {z: v.get("faces", 0) for z, v in (st.get("zones") or {}).items()}
                    if not faces.get("prato") or not faces.get("spianata") or len(faces) != 6:
                        bad.append(f"zones: {faces}")
                    u, e2 = eng.call("POST", "terrain/update", {"id": r["id"], "params": {"flat": {"radius": 60}}}, timeout=900)
                    eng.idle()
                    if e2 or not (u or {}).get("geometry"):
                        bad.append(f"update did not say which meshes changed: {e2}")
                    st2 = eng.call("GET", f"terrain/state?id={r['id']}")[0] or {}
                    if ((st2.get("params") or {}).get("flat") or {}).get("radius") != 60:
                        bad.append("update not kept in the terrain")
                    # (1.76.10) «Roccia scolpita»: a new terrain takes its preset's; it changes the shape; Ctrl+Z gives
                    # it back; a terrain made before (no «rocky») stays as it was (None = 0)
                    rk0 = (st2.get("rock") or {}).get("rocky")
                    if rk0 is None or abs(rk0 - 0.1) > 1e-6:
                        bad.append(f"new pianura without its sculpted rock: {st2.get('rock')}")
                    ra, ea = eng.call("POST", "terrain/update", {"id": r["id"], "params": {"rocky": 0.0}}, timeout=900)
                    rb, eb = eng.call("POST", "terrain/update", {"id": r["id"], "params": {"rocky": None}}, timeout=900)
                    rc, ec = eng.call("POST", "terrain/update", {"id": r["id"], "params": {"rocky": 1.0, "sharp": 1.0, "rockSlope": 15}}, timeout=900)
                    eng.idle()
                    ia, ib, ic = [((x or {}).get("info") or {}) for x in (ra, rb, rc)]
                    if ea or eb or ec or not ia or not ic:
                        bad.append(f"rock updates: {ea} {eb} {ec}")
                    else:
                        if (ia.get("min"), ia.get("max")) != (ib.get("min"), ib.get("max")):
                            bad.append(f"a terrain without «rocky» is not the one with 0: {ia} {ib}")
                        if abs(ic.get("max", 0) - ia.get("max", 0)) < 1e-3 and abs(ic.get("min", 0) - ia.get("min", 0)) < 1e-3:
                            bad.append("sculpted rock changed nothing")
                    for _i in range(3):
                        eng.call("POST", "undo", {}, timeout=900)
                    eng.idle()
                    st3 = eng.call("GET", f"terrain/state?id={r['id']}")[0] or {}
                    if abs(((st3.get("rock") or {}).get("rocky") or 0) - 0.1) > 1e-6:
                        bad.append(f"Ctrl+Z did not give the sculpted rock back: {st3.get('rock')}")
                    # (1.76.1) a Poly Haven texture with an opacity map (leafy_grass) made the ground see-through:
                    # fake textures in the library of this test engine only (its own temporary folder)
                    root = next((x.get("path") for x in ((eng.call("GET", "paths")[0] or {}).get("folders") or [])
                                 if x.get("key") == "phTextures"), "") or ""
                    # (1.76.9) what the app shows in «Occupato · attendi · Materiali del terreno» while they download
                    for z, v in (st2.get("zones") or {}).items():
                        if v.get("faces") and not all(k in v for k in ("placeholder", "download", "fraction", "macroWaiting", "macroDownload", "macroFraction")):
                            bad.append(f"terrain state of {z} without the download progress: {sorted(v)}")
                    if "simpler_reg_" in root:
                        _fake_textures(root, st2.get("zones") or {})
                        m, em = eng.call("POST", "terrain/materials", {"id": r["id"]})
                        st4 = eng.call("GET", f"terrain/state?id={r['id']}")[0] or {}
                        # (1.76.6) the large textures (Poly Haven aerial) on the zones that have one, as «macro»
                        for z, v in (st4.get("zones") or {}).items():
                            if not v.get("faces") or not v.get("macroTexture"):
                                continue
                            edm = eng.call("GET", "material/edit?name=" + urllib.parse.quote(v.get("material", "")))[0] or {}
                            mcp = ((edm.get("params") or {}).get("macro") or {})
                            if not (mcp.get("map") or {}).get("image") or not mcp.get("mean"):
                                bad.append(f"no large texture on {z}: {mcp}")
                            if v.get("macroWaiting"):
                                bad.append(f"{z} still waiting for its large texture")
                        plain = [z for z, v in (st4.get("zones") or {}).items() if v.get("faces") and v.get("placeholder")]
                        if em or plain:
                            bad.append(f"textures not put on the zones: {em} {plain}")
                        # (1.76.14) «Colori dal terreno»: on for a new terrain (its data in the meshes), off and back
                        # with Ctrl+Z, only in the materials
                        def tone_of_slot():
                            sx = eng.call("GET", f"terrain/state?id={r['id']}")[0] or {}
                            pz = (sx.get("zones") or {}).get("prato") or {}
                            ed = eng.call("GET", "material/edit?name=" + urllib.parse.quote(pz.get("slotMaterial", "")))[0] or {}
                            return sx, (ed.get("params") or {}).get("tone")
                        sx, tn = tone_of_slot()
                        if not sx.get("toneReady") or not (sx.get("tone") or {}).get("on") or not tn:
                            bad.append(f"new terrain without its colours: ready {sx.get('toneReady')} {sx.get('tone')} {tn}")
                        _t, et = eng.call("POST", "terrain/tone", {"id": r["id"], "on": False})
                        sx, tn = tone_of_slot()
                        # (1.76.42: the relief of the rock stays with the colours off - only the colours at 0)
                        if et or (sx.get("tone") or {}).get("on") or (tn and any(float(tn.get(k) or 0) > 0 for k in ("streaks", "bands", "ridges", "wet"))):
                            bad.append(f"colours not switched off: {et} {sx.get('tone')} {tn}")
                        eng.call("POST", "undo", {})
                        sx, tn = tone_of_slot()
                        if not (sx.get("tone") or {}).get("on") or not tn:
                            bad.append(f"Ctrl+Z did not give the colours back: {sx.get('tone')} {tn}")

                        for z, v in (st4.get("zones") or {}).items():
                            if not v.get("material"):
                                continue
                            ed = eng.call("GET", "material/edit?name=" + urllib.parse.quote(v["material"]))[0] or {}
                            op = (ed.get("params") or {}).get("opacity") or {}
                            if op.get("useAlpha") or (op.get("map") or {}).get("image"):
                                bad.append(f"see-through terrain material: {v['material']}")
                        # (1.76.4) «Sfumatura dei bordi»: the zones get a blended copy of their material; editing that copy
                        # edits the zone's own material; width 0 gives the plain ones back, Ctrl+Z the blended ones
                        zs4 = {z: v for z, v in (st4.get("zones") or {}).items() if v.get("faces")}
                        if not all(v.get("blended") for v in zs4.values()):
                            bad.append(f"zones not blended: {[z for z, v in zs4.items() if not v.get('blended')]}")
                        pr = zs4.get("prato") or {}
                        if pr.get("blended"):
                            _e, ee = eng.call("POST", "material/edit", {"name": pr["slotMaterial"], "params": {"roughness": {"value": 0.33}}})
                            src_ed = eng.call("GET", "material/edit?name=" + urllib.parse.quote(pr["material"]))[0] or {}
                            if ee or abs(((src_ed.get("params") or {}).get("roughness") or {}).get("value", 0) - 0.33) > 1e-6:
                                bad.append(f"edit of the blended material not passed to the zone's material: {ee}")
                            der = eng.call("GET", "material/edit?name=" + urllib.parse.quote(pr["slotMaterial"]))[0] or {}
                            if not ((der.get("params") or {}).get("blend") or {}).get("partners"):
                                bad.append("the blended material lost its partners after an edit")
                            _b, eb = eng.call("POST", "terrain/blend", {"id": r["id"], "width": 0})
                            st5 = eng.call("GET", f"terrain/state?id={r['id']}")[0] or {}
                            if eb or any(v.get("blended") for v in (st5.get("zones") or {}).values()):
                                bad.append(f"width 0 did not give the plain materials back: {eb}")
                            eng.call("POST", "undo", {})
                            st6 = eng.call("GET", f"terrain/state?id={r['id']}")[0] or {}
                            if not (((st6.get("zones") or {}).get("prato") or {}).get("blended")):
                                bad.append("undo of the blend width did not give the blended materials back")
                            # water on a zone (asked on its blended copy): the zone's own material becomes water, with a sharp
                            # border on both sides - the neighbours no longer blend into it
                            te = zs4.get("terra") or {}
                            if te.get("blended"):
                                _w, ew = eng.call("POST", "material/water", {"name": te["slotMaterial"], "on": True})
                                st7 = eng.call("GET", f"terrain/state?id={r['id']}")[0] or {}
                                t7 = (st7.get("zones") or {}).get("terra") or {}
                                p7 = (st7.get("zones") or {}).get("prato") or {}
                                der7 = eng.call("GET", "material/edit?name=" + urllib.parse.quote(p7.get("slotMaterial", "")))[0] or {}
                                parts7 = ((der7.get("params") or {}).get("blend") or {}).get("partners") or []
                                if ew or t7.get("blended") or t7.get("slotMaterial") != t7.get("material"):
                                    bad.append(f"water on a zone still blended: {ew} {t7}")
                                if any(q.get("zone") == "terra" for q in parts7):
                                    bad.append("the lawn still blends into the water")
                                eng.call("POST", "undo", {})
                            eng.call("POST", "undo", {})        # (the edit)
                        eng.call("POST", "undo", {})            # (the materials)
                    h1 = eng.call("POST", "undo", {})[0] or {}
                    if not h1.get("geometry"):
                        bad.append("undo of the change did not say which meshes changed")
                    st3 = eng.call("GET", f"terrain/state?id={r['id']}")[0] or {}
                    if ((st3.get("params") or {}).get("flat") or {}).get("radius") != 30:
                        bad.append("undo did not give the terrain before back")
                    eng.call("POST", "undo", {})
                    if len((eng.call("GET", "scene")[0] or {}).get("objects", [])) != n0:
                        bad.append("undo did not remove the terrain")
                if bad:
                    rec["status"], rec["error"] = "FAIL", "; ".join(bad)[:300]
                    out["errors"] += 1
                rec["secs"] = round(time.time() - t, 2)
                out["steps"].append(rec)
                print(f"  {name:16s} {rec['status']:5s} {rec['secs']:8.2f} s  {rec.get('error', '')}", flush=True)
                continue
            if method == "ECOSPILL":
                rec = {"step": name, "secs": 0.0, "idle": 0.0, "rssGB": round(eng.rss(), 2), "status": "ok"}
                t = time.time()
                eid = state.get("eco")
                if not eid:
                    rec["status"] = "skip"
                else:
                    bad = []
                    r, e = eng.call("POST", "terrain/create", {"preset": "colline", "seed": 1}, timeout=900)
                    eng.idle()
                    lawn = ((r or {}).get("zones") or {}).get("prato")
                    if e or not lawn:
                        bad.append(f"terrain not made: {e}")
                    else:
                        eng.call("POST", "camera", {"action": "lookat", "position": [0, 0, 1500], "target": [0, 30000, -1500],
                                                    "vfov": 40, "aspect": 1.7})
                        q = lambda extra: eng.call("POST", "ecosystems/count", dict({"id": eid, "target": lawn, "camOnly": True}, **extra))
                        a, e1 = q({})
                        b, e2 = q({"spill": 3.0, "spillDensity": 0.8})
                        if e1 or e2 or not a or not b:
                            bad.append(f"count: {e1} {e2}")
                        else:
                            if b["pieces"] <= a["pieces"]:
                                bad.append(f"nothing past the edge: {a['pieces']} -> {b['pieces']}")
                            if a.get("thinPast") is None:
                                bad.append("no thinning reported")
                        eng.call("POST", "undo", {})
                    if bad:
                        rec["status"], rec["error"] = "FAIL", "; ".join(bad)[:300]
                        out["errors"] += 1
                rec["secs"] = round(time.time() - t, 2)
                out["steps"].append(rec)
                print(f"  {name:16s} {rec['status']:5s} {rec['secs']:8.2f} s  {rec.get('error', '')}", flush=True)
                continue
            if method == "TERRECO":
                rec = {"step": name, "secs": 0.0, "idle": 0.0, "rssGB": round(eng.rss(), 2), "status": "ok"}
                t = time.time()
                eid = _test_eco(eng, args) if state.get("eco") else None
                if not eid:
                    rec["status"] = "skip"
                else:
                    bad = []
                    r, e = eng.call("POST", "terrain/create", {"preset": "pianura", "seed": 4}, timeout=900)
                    eng.idle()
                    lawn = ((r or {}).get("zones") or {}).get("prato")
                    if e or not lawn:
                        bad.append(f"terrain not made: {e}")
                    else:
                        a, ea = eng.call("POST", "ecosystems/apply", {"id": eid, "target": lawn, "whole": True, "density": 0.02}, timeout=1800)
                        eng.idle()
                        gid = (a or {}).get("group")
                        def layers():
                            objs = (eng.call("GET", "scene")[0] or {}).get("objects", [])
                            return sorted(o["id"] for o in objs if o.get("parent") == gid)
                        if ea or not gid:
                            bad.append(f"ecosystem not placed: {ea}")
                        else:
                            l0 = layers()
                            u, eu = eng.call("POST", "terrain/update", {"id": r["id"], "params": {"height": 30}}, timeout=900)
                            eng.idle()
                            l1 = layers()
                            if eu or ((u or {}).get("ecosystems") or {}).get("done") != 1 or not l1 or set(l1) & set(l0):
                                bad.append(f"ecosystem not made again with the terrain: {eu} {(u or {}).get('ecosystems')} {l0} -> {l1}")
                            eng.call("POST", "undo", {}, timeout=900)
                            eng.idle()
                            l2 = layers()
                            if l2 != l0:
                                bad.append(f"Ctrl+Z did not give the old layers back: {l0} -> {l2}")
                            eng.call("POST", "redo", {}, timeout=900)
                            eng.idle()
                            if layers() != l1:
                                bad.append(f"Ctrl+Y did not give the new layers back: {l1} -> {layers()}")
                            eng.call("POST", "undo", {}, timeout=900)
                        eng.call("POST", "undo", {}, timeout=900)
                        eng.call("POST", "undo", {}, timeout=900)
                        eng.idle()
                    if bad:
                        rec["status"], rec["error"] = "FAIL", "; ".join(bad)[:300]
                        out["errors"] += 1
                rec["secs"] = round(time.time() - t, 2)
                out["steps"].append(rec)
                print(f"  {name:16s} {rec['status']:5s} {rec['secs']:8.2f} s  {rec.get('error', '')}", flush=True)
                continue
            if method == "ECOFALL":
                # (1.76.37, Luca: «più rado in lontananza a 0% e 100% praticamente uguali») the slider must change the
                # count: 100% clearly fewer pieces than 0% (the thinning starts at 25 m, not at the far point looked at)
                rec = {"step": name, "secs": 0.0, "idle": 0.0, "rssGB": round(eng.rss(), 2), "status": "ok"}
                t = time.time()
                if not (state.get("eco") and state.get("ground")):
                    rec["status"] = "skip"
                else:
                    errs = []
                    covers = []
                    def cnt(f):
                        r_, e_ = eng.call("POST", "ecosystems/count", {"id": state["eco"], "target": state["ground"], "camOnly": True,
                                                                      "camRefresh": True, "camFalloff": f}, timeout=600)
                        if e_:
                            errs.append(str(e_)[:120])
                        covers.append(float((r_ or {}).get("cover") or 0))
                        return (r_ or {}).get("pieces") or 0
                    eng.idle()
                    # (the camera looking at a point far away, as Luca's mountain: before, nothing thinned nearer than it)
                    # (a low camera looking at a point 600 m away over the ground, as Luca's mountain; the sea of the
                    # steps before taken away meanwhile - the ground of this scene is at its level: nothing grows)
                    cam0 = ((eng.call("GET", "settings")[0] or {}).get("view") or {})
                    pos, tgt = cam0.get("position"), cam0.get("target")
                    sea = bool(((eng.call("GET", "ambience")[0] or {}).get("ocean") or {}).get("on"))
                    if sea:
                        eng.call("POST", "landscape/ocean", {"on": False}, timeout=600); eng.idle()
                    eng.call("POST", "camera", {"action": "lookat", "position": [0, -1500, 300], "target": [0, 60000, -400], "vfov": 50, "aspect": 1.78})
                    c0, c1 = cnt(0.0), cnt(1.0)
                    if sea:
                        eng.call("POST", "undo", {}, timeout=600); eng.idle()
                    if pos and tgt:
                        eng.call("POST", "camera", {"action": "lookat", "position": pos, "target": tgt, "vfov": cam0.get("vfov", 50), "aspect": 1.78})
                    # (1.76.42: at most 40% fewer where the thinning for the memory already did its part - before
                    # 96% fewer, and the ground bare)
                    if not c0 or c1 > 0.75 * c0:
                        rec["status"], rec["error"] = "FAIL", f"«Più rado in lontananza» 0% {c0} pieces, 100% {c1} {errs}"
                        out["errors"] += 1
                    # (1.76.42, Luca: after «Ricalcola dalla vista» the grass was gone) fewer pieces, but the ground
                    # still covered: the pieces kept far away are bigger
                    elif covers[0] > 0 and covers[1] < 0.55 * covers[0]:
                        rec["status"], rec["error"] = "FAIL", f"«Più rado in lontananza» 100% bares the ground: cover {covers[1]:.0f} of {covers[0]:.0f}"
                        out["errors"] += 1
                    rec["counts"] = [c0, c1, round(covers[1] / max(covers[0], 1e-9), 2) if covers else None]
                rec["secs"] = round(time.time() - t, 2)
                out["steps"].append(rec)
                print(f"  {name:16s} {rec['status']:5s} {rec['secs']:8.2f} s  {rec.get('error', '')} {rec.get('counts', '')}", flush=True)
                continue
            if method == "ROCKRELIEF":
                # (1.76.40, Luca: «tranne la parte dietro dei monti») «Rilievo della roccia» must change the picture of
                # distant walls (the shading of the rock where the mesh is coarse)
                rec = {"step": name, "secs": 0.0, "idle": 0.0, "rssGB": round(eng.rss(), 2), "status": "ok"}
                t = time.time()
                bad = []
                # (the sea of the steps before away meanwhile: at its level it would cover the walls)
                sea = bool(((eng.call("GET", "ambience")[0] or {}).get("ocean") or {}).get("on"))
                if sea:
                    eng.call("POST", "landscape/ocean", {"on": False}, timeout=600); eng.idle()
                r, e = eng.call("POST", "terrain/create", {"preset": "montagne", "seed": 4}, timeout=900)
                eng.idle()
                if e or not r:
                    bad.append(f"terrain not made: {e}")
                else:
                    try:
                        from PIL import Image
                        import numpy as _np
                        eng.call("POST", "camera", {"action": "lookat", "position": [-180000, -160000, 60000], "target": [0, 0, 20000], "vfov": 35, "aspect": 1.78})
                        pics = []
                        # (1.76.42, Luca: «dovrebbe essere in Forma e roccia») with «Colori dal terreno» off too
                        eng.call("POST", "terrain/tone", {"id": r["id"], "on": False}); eng.idle()
                        for rv in (0.0, 1.0):
                            eng.call("POST", "terrain/tone", {"id": r["id"], "relief": rv}); eng.idle()
                            pth = os.path.join(eng.tmp, f"relief_{rv}.png")
                            eng.call("POST", "render", {"path": pth, "width": 192, "height": 108, "samples": 8, "denoise": False, "inProcess": True}, timeout=900)
                            pics.append(_np.asarray(Image.open(pth).convert("RGB"), dtype=_np.float32))
                        dif = float(_np.abs(pics[0] - pics[1]).mean())
                        rec["diff"] = round(dif, 2)
                        if dif < 1.5:
                            bad.append(f"«Rilievo della roccia» 0% and 100% the same ({dif:.2f})")
                        # (1.76.53, Luca: «Rilievo 3D») each kind its own picture; its numbers set in place, nothing
                        # sent again to the view
                        kinds = {}
                        for kd in ("canaloni", "fratture", "cenge"):
                            tr_, et_ = eng.call("POST", "terrain/tone", {"id": r["id"], "rtype": kd}); eng.idle()
                            if et_:
                                bad.append(f"{kd}: {et_}")
                            pth = os.path.join(eng.tmp, f"relief_{kd}.png")
                            eng.call("POST", "render", {"path": pth, "width": 192, "height": 108, "samples": 8, "denoise": False, "inProcess": True}, timeout=900)
                            kinds[kd] = _np.asarray(Image.open(pth).convert("RGB"), dtype=_np.float32)
                            dk = float(_np.abs(kinds[kd] - pics[1]).mean())
                            if dk < 0.8:
                                bad.append(f"«Rilievo 3D» {kd} the same as «Attuale» ({dk:.2f})")
                        n0 = open(eng.log).read().count("only its relief numbers changed")
                        tr_, et_ = eng.call("POST", "terrain/tone", {"id": r["id"], "rsize": 2.0, "rdetail": 0.9, "rorient": 30}); eng.idle()
                        if et_ or (tr_ or {}).get("terrainBlend") or open(eng.log).read().count("only its relief numbers changed") <= n0:
                            bad.append(f"«Rilievo 3D» numbers not set in place: {et_} {(tr_ or {}).get('terrainBlend')}")
                        pth = os.path.join(eng.tmp, "relief_bigger.png")
                        eng.call("POST", "render", {"path": pth, "width": 192, "height": 108, "samples": 8, "denoise": False, "inProcess": True}, timeout=900)
                        if float(_np.abs(_np.asarray(Image.open(pth).convert("RGB"), dtype=_np.float32) - kinds["cenge"]).mean()) < 0.5:
                            bad.append("«Rilievo 3D» Dimensione and Dettaglio change nothing")
                    except ImportError:
                        rec["status"] = "skip"
                    for _i in range(8):
                        eng.call("POST", "undo", {}, timeout=600)
                    eng.idle()
                if sea:
                    eng.call("POST", "undo", {}, timeout=600); eng.idle()
                if bad:
                    rec["status"], rec["error"] = "FAIL", "; ".join(bad)[:300]
                    out["errors"] += 1
                rec["secs"] = round(time.time() - t, 2)
                out["steps"].append(rec)
                print(f"  {name:16s} {rec['status']:5s} {rec['secs']:8.2f} s  {rec.get('error', '')} {rec.get('diff', '')}", flush=True)
                continue
            if method == "ROCKMAP":
                # (1.76.58, Luca: «true displacement deve avere anche l'opzione per caricare una displacement») a relief
                # map of one's own replaces the kind; its size set in place; the colour map on the rock zone only (also
                # in the view); without the maps the picture of the kind comes back exactly
                rec = {"step": name, "secs": 0.0, "idle": 0.0, "rssGB": round(eng.rss(), 2), "status": "ok"}
                t = time.time()
                bad = []
                steps = 0
                sea = bool(((eng.call("GET", "ambience")[0] or {}).get("ocean") or {}).get("on"))
                if sea:
                    eng.call("POST", "landscape/ocean", {"on": False}, timeout=600); eng.idle()
                r, e = eng.call("POST", "terrain/create", {"preset": "montagne", "seed": 4, "rocky": 0.8}, timeout=900)
                eng.idle()
                if e or not r:
                    bad.append(f"terrain not made: {e}")
                else:
                    steps = 1
                    try:
                        from PIL import Image
                        import numpy as _np
                        rng = _np.random.default_rng(3)
                        hm = _np.kron(rng.random((16, 16)), _np.ones((32, 32)))       # (blocks: a relief one sees)
                        hpath = os.path.join(eng.tmp, "rmap_h.png")
                        Image.fromarray((hm * 255).astype(_np.uint8)).save(hpath)
                        cpath = os.path.join(eng.tmp, "rmap_c.png")
                        Image.fromarray((_np.stack([hm * 0.2, hm * 0.4, hm * 0.9], -1) * 255).astype(_np.uint8)).save(cpath)
                        eng.call("POST", "camera", {"action": "lookat", "position": [-20000, -16000, 15000], "target": [0, 0, 9000], "vfov": 25, "aspect": 1.78})
                        eng.call("POST", "terrain/update", {"id": r["id"], "params": {}}, timeout=900); eng.idle(); steps += 1
                        eng.call("POST", "terrain/tone", {"id": r["id"], "on": False, "relief": 0.9}); eng.idle(); steps += 1

                        def pic(tag):
                            pth = os.path.join(eng.tmp, f"rmap_{tag}.png")
                            eng.call("POST", "render", {"path": pth, "width": 192, "height": 108, "samples": 8, "denoise": False, "inProcess": True}, timeout=1200)
                            eng.idle()
                            return _np.asarray(Image.open(pth).convert("RGB"), dtype=_np.float32) if os.path.isfile(pth) else None
                        dif = lambda a, b: float(_np.abs(a - b).mean()) if a is not None and b is not None else -1.0
                        a = pic("preset")
                        tr_, et_ = eng.call("POST", "terrain/tone", {"id": r["id"], "rmapFile": hpath}); eng.idle(); steps += 1
                        if et_ or not ((tr_ or {}).get("tone") or {}).get("rmap"):
                            bad.append(f"relief map not set: {et_}")
                        b = pic("map")
                        if 0 <= dif(a, b) < 0.5:
                            bad.append(f"the relief map changes nothing ({dif(a, b):.2f})")
                        n1 = open(eng.log).read().count("only its relief numbers changed")
                        eng.call("POST", "terrain/tone", {"id": r["id"], "rmsize": 25.0, "rmrot": 40}); eng.idle(); steps += 1
                        if open(eng.log).read().count("only its relief numbers changed") <= n1:
                            bad.append("Grandezza/Rotazione of the map not set in place")
                        c = pic("size")
                        if 0 <= dif(b, c) < 0.3:
                            bad.append(f"Grandezza/Rotazione change nothing ({dif(b, c):.2f})")
                        eng.call("POST", "terrain/tone", {"id": r["id"], "rcolorFile": cpath}); eng.idle(); steps += 1
                        st, _e = eng.call("GET", "terrain/state?id=" + r["id"])
                        zs = (st or {}).get("zones") or {}
                        ids = {z: v.get("id") for z, v in zs.items()}
                        rt, _e = eng.call("POST", "realtime/materials", {"ids": [ids.get("roccia"), ids.get("prato")]})
                        objs = (rt or {}).get("objects") or {}
                        rc_rock = any(m_ and m_.get("reliefColor") for m_ in objs.get(ids.get("roccia")) or [])
                        rc_meadow = any(m_ and m_.get("reliefColor") for m_ in objs.get(ids.get("prato")) or [])
                        if not rc_rock or rc_meadow:
                            bad.append(f"colour map in the view: rock {rc_rock}, meadow {rc_meadow}")
                        d = pic("color")
                        if 0 <= dif(c, d) < 0.3:
                            bad.append(f"the colour map changes nothing ({dif(c, d):.2f})")
                        eng.call("POST", "terrain/tone", {"id": r["id"], "rmap": "", "rcolor": "", "rmsize": 10.0, "rmrot": 0}); eng.idle(); steps += 1
                        e_ = pic("nomap")
                        rec["diff"] = [round(dif(a, b), 2), round(dif(b, c), 2), round(dif(c, d), 2), round(dif(a, e_), 2)]
                        if dif(a, e_) > 0.3:
                            bad.append(f"without the maps not the picture of the kind ({dif(a, e_):.2f})")
                    except ImportError:
                        rec["status"] = "skip"
                    for _i in range(steps):
                        eng.call("POST", "undo", {}, timeout=600)
                    eng.idle()
                if sea:
                    eng.call("POST", "undo", {}, timeout=600); eng.idle()
                if bad:
                    rec["status"], rec["error"] = "FAIL", "; ".join(bad)[:300]
                    out["errors"] += 1
                rec["secs"] = round(time.time() - t, 2)
                out["steps"].append(rec)
                print(f"  {name:16s} {rec['status']:5s} {rec['secs']:8.2f} s  {rec.get('error', '')} {rec.get('diff', '')}", flush=True)
                continue
            if method == "FOLIAGE":
                rec = {"step": name, "secs": 0.0, "idle": 0.0, "rssGB": round(eng.rss(), 2), "status": "ok"}
                t = time.time()
                bad = []
                steps = 0
                exe = os.environ.get("SIMPLER_RENDER_EXE") or ""
                d = os.path.join(eng.tmp, "lad", "Simpler", "library", "polyhaven", "models", "reg_leaves")
                os.makedirs(d, exist_ok=True)
                script = os.path.join(eng.tmp, "mkleaves.py")
                with open(script, "w") as f:
                    # a ball of separate little faces: each face a leaf (an island), as in a real crown
                    f.write("import bpy, os, sys\nout = sys.argv[-1]\nfor o in list(bpy.data.objects): bpy.data.objects.remove(o)\n"
                            "bpy.ops.mesh.primitive_ico_sphere_add(subdivisions=3, radius=1.0)\no = bpy.context.object; o.name = 'reg_leaves'\n"
                            "bpy.ops.object.mode_set(mode='EDIT'); bpy.ops.mesh.select_all(action='SELECT'); bpy.ops.mesh.edge_split(type='EDGE')\n"
                            "bpy.ops.object.mode_set(mode='OBJECT')\nm = bpy.data.materials.new('reg_leaves_mat'); o.data.materials.append(m)\n"
                            "bpy.data.libraries.write(os.path.join(out, 'm.blend'), {o}, fake_user=True)\n")
                if not exe or subprocess.run([exe, "-b", "--python", script, "--", d], capture_output=True).returncode != 0:
                    rec["status"] = "skip"
                else:
                    with open(os.path.join(d, "model.json"), "w") as f:
                        json.dump({"format": "blend", "file": "m.blend", "v": 2}, f)
                    r, e = eng.call("POST", "library/models/insert", {"id": "reg_leaves"}, timeout=900)
                    eng.idle()
                    obj = next((o for o in (eng.call("GET", "scene")[0] or {}).get("objects", []) if "reg_leaves" in (o.get("name") or "")
                                and o.get("materials")), None)
                    if e or obj is None:
                        bad.append(f"test leaves not in the scene: {e}")
                    else:
                        steps = 1
                        mn = obj["materials"][0]
                        loc = list(obj.get("location") or [0, 0, 0])
                        loc[2] += 3000.0          # (cm: 30 m up, away from the scene's own models)
                        eng.call("POST", "transform", {"id": obj["id"], "location": loc}); eng.idle(); steps += 1
                        try:
                            from PIL import Image
                            import numpy as _np
                            eng.call("POST", "camera", {"action": "lookat", "position": [loc[0], loc[1] - 600, loc[2] + 150],
                                                        "target": loc, "vfov": 30, "aspect": 1.78})
                            eng.idle()            # (the sea follows the new view first: not a wait of the edits)

                            def pic(tag):
                                pth = os.path.join(eng.tmp, f"fol_{tag}.png")
                                eng.call("POST", "render", {"path": pth, "width": 192, "height": 108, "samples": 8, "denoise": False, "inProcess": True}, timeout=1200)
                                eng.idle()
                                return _np.asarray(Image.open(pth).convert("RGB"), dtype=_np.float32) if os.path.isfile(pth) else None
                            dif = lambda a, b: float(_np.abs(a - b).mean()) if a is not None and b is not None else -1.0
                            times = []

                            parts_t = []

                            def edit(params):
                                t1 = time.time()
                                # (converted once: then edits as the panel sends them, without «convert» - a look-only edit
                                # must not make the engine measure the coast again, 1 s on the auto scene, 1.78.3)
                                _r, ee = eng.call("POST", "material/edit", {"name": mn, "params": params, "convert": not times}, timeout=900)
                                tc = time.time()
                                whats = set()
                                tq, quiet = time.time(), 0
                                while time.time() - tq < 600:
                                    rb, _e = eng.call("GET", "busy", timeout=10)
                                    if rb is not None and not rb.get("busy"):
                                        quiet += 1
                                        if quiet >= 3:
                                            break
                                    else:
                                        quiet = 0
                                        if rb and rb.get("what"):
                                            whats.add(str(rb.get("what"))[:60])
                                    time.sleep(0.3)
                                times.append(round(time.time() - t1 - 0.6, 2))
                                parts_t.append((round(tc - t1, 2), round(time.time() - tc - 0.6, 2), sorted(whats)))
                                if ee:
                                    bad.append(f"edit: {ee}")
                                return ee is None
                            n0 = len(open(eng.log).read())
                            edit({"color": {"tint": [0.08, 0.3, 0.04]}, "foliage": {"enabled": True}}); steps += 1
                            pics = {}
                            for sv in (0.0, 0.5, 0.8, 1.0):
                                edit({"foliage": {"season": sv}}); steps += 1
                                pics[sv] = pic(f"s{sv}")
                            d1, d2, d3 = dif(pics[0.0], pics[0.5]), dif(pics[0.5], pics[0.8]), dif(pics[0.0], pics[1.0])
                            rec["diff"] = [round(d1, 2), round(d2, 2), round(d3, 2), times, parts_t,
                                           re.findall(r"SIMPLER_SLOWEDIT[^\n]*", open(eng.log).read()[n0:])[:3]]
                            if 0 <= d1 < 0.3:
                                bad.append(f"the season changes nothing at 50% ({d1:.2f})")
                            if 0 <= d2 < 0.3:
                                bad.append(f"the season changes nothing from 50% to 80% ({d2:.2f})")
                            if 0 <= d3 < max(d1, 0.5):
                                bad.append(f"winter does not take the leaves away ({d3:.2f})")
                            edit({"foliage": {"enabled": True, "part": "legno", "season": 1.0}}); steps += 1
                            w = pic("wood")
                            if 0 <= dif(w, pics[1.0]) < 0.5:
                                bad.append("the wood lost its surface in winter")
                            rt, _e = eng.call("POST", "realtime/materials", {"ids": [obj["id"]]})
                            fm = [m_ for m_ in ((rt or {}).get("objects") or {}).get(obj["id"]) or [] if m_ and m_.get("foliage")]
                            if not fm or fm[0]["foliage"].get("leaves") or not fm[0]["foliage"].get("ramps"):
                                bad.append(f"the view does not get the foliage: {fm[:1]}")
                            coast = [p_[2] for p_ in parts_t[1:] if any("costa" in w_ or "coast" in w_ for w_ in p_[2])]
                            if coast:
                                bad.append(f"a look-only edit makes the engine measure the coast again: {coast[:2]}")
                            if max(times) > 4.0:
                                slow = re.findall(r"SIMPLER_SLOWEDIT[^\n]*", open(eng.log).read()[n0:])
                                bad.append(f"an edit of a foliage material waits {max(times)} s ({times}; call/idle {parts_t}; {slow[:2]})")
                        except ImportError:
                            rec["status"] = "skip"
                    for _i in range(steps):
                        eng.call("POST", "undo", {}, timeout=600)
                    eng.idle()
                if bad:
                    rec["status"], rec["error"] = "FAIL", "; ".join(bad)[:300]
                    out["errors"] += 1
                rec["secs"] = round(time.time() - t, 2)
                out["steps"].append(rec)
                print(f"  {name:16s} {rec['status']:5s} {rec['secs']:8.2f} s  {rec.get('error', '')} {rec.get('diff', '')}", flush=True)
                continue
            if method == "FABRIC":
                rec = {"step": name, "secs": 0.0, "idle": 0.0, "rssGB": round(eng.rss(), 2), "status": "ok"}
                t = time.time()
                bad = []
                steps = 0
                exe = os.environ.get("SIMPLER_RENDER_EXE") or ""
                d = os.path.join(eng.tmp, "lad", "Simpler", "library", "polyhaven", "models", "reg_cloth")
                os.makedirs(d, exist_ok=True)
                script = os.path.join(eng.tmp, "mkcloth.py")
                with open(script, "w") as f:
                    f.write("import bpy, os, sys\nout = sys.argv[-1]\nfor o in list(bpy.data.objects): bpy.data.objects.remove(o)\n"
                            "bpy.ops.mesh.primitive_uv_sphere_add(radius=1.0)\no = bpy.context.object; o.name = 'reg_cloth'\n"
                            "m = bpy.data.materials.new('reg_cloth_mat'); o.data.materials.append(m)\n"
                            "bpy.data.libraries.write(os.path.join(out, 'm.blend'), {o}, fake_user=True)\n")
                if not exe or subprocess.run([exe, "-b", "--python", script, "--", d], capture_output=True).returncode != 0:
                    rec["status"] = "skip"
                else:
                    with open(os.path.join(d, "model.json"), "w") as f:
                        json.dump({"format": "blend", "file": "m.blend", "v": 2}, f)
                    r, e = eng.call("POST", "library/models/insert", {"id": "reg_cloth"}, timeout=900)
                    eng.idle()
                    obj = next((o for o in (eng.call("GET", "scene")[0] or {}).get("objects", []) if "reg_cloth" in (o.get("name") or "")
                                and o.get("materials")), None)
                    if e or obj is None:
                        bad.append(f"test cloth not in the scene: {e}")
                    else:
                        steps = 1
                        mn = obj["materials"][0]
                        loc = list(obj.get("location") or [0, 0, 0])
                        loc[2] += 3000.0
                        eng.call("POST", "transform", {"id": obj["id"], "location": loc}); eng.idle(); steps += 1
                        try:
                            from PIL import Image
                            import numpy as _np
                            eng.call("POST", "camera", {"action": "lookat", "position": [loc[0], loc[1] - 600, loc[2] + 150],
                                                        "target": loc, "vfov": 30, "aspect": 1.78})

                            def pic(tag):
                                pth = os.path.join(eng.tmp, f"fab_{tag}.png")
                                eng.call("POST", "render", {"path": pth, "width": 192, "height": 108, "samples": 8, "denoise": False, "inProcess": True}, timeout=1200)
                                eng.idle()
                                return _np.asarray(Image.open(pth).convert("RGB"), dtype=_np.float32) if os.path.isfile(pth) else None
                            dif = lambda a, b: float(_np.abs(a - b).mean()) if a is not None and b is not None else -1.0
                            times = []

                            def edit(params):
                                t1 = time.time()
                                _r, ee = eng.call("POST", "material/edit", {"name": mn, "params": params, "convert": True}, timeout=900)
                                eng.idle()
                                times.append(round(time.time() - t1, 2))
                                if ee:
                                    bad.append(f"edit: {ee}")
                            edit({"color": {"tint": [0.3, 0.05, 0.08]}, "roughness": {"value": 0.8}}); steps += 1
                            a = pic("plain")
                            edit({"fabric": {"enabled": True}, "sheen": {"weight": 1.0, "roughness": 0.4}}); steps += 1
                            b = pic("full")
                            edit({"fabric": {"mode": "sottile", "see": 0.9}}); steps += 1
                            c = pic("thin")
                            rec["diff"] = [round(dif(a, b), 2), round(dif(b, c), 2), times]
                            if 0 <= dif(a, b) < 0.2:
                                bad.append(f"the fuzz changes nothing ({dif(a, b):.2f})")
                            if 0 <= dif(b, c) < 0.5:
                                bad.append(f"the thin cloth is not seen through ({dif(b, c):.2f})")
                            rt, _e = eng.call("POST", "realtime/materials", {"ids": [obj["id"]]})
                            fm = [m_ for m_ in ((rt or {}).get("objects") or {}).get(obj["id"]) or [] if m_ and m_.get("fabric")]
                            if not fm or not fm[0]["fabric"].get("thin"):
                                bad.append(f"the view does not get the fabric: {fm[:1]}")
                            if max(times) > 4.0:
                                bad.append(f"an edit of a fabric material waits {max(times)} s ({times})")
                        except ImportError:
                            rec["status"] = "skip"
                    for _i in range(steps):
                        eng.call("POST", "undo", {}, timeout=600)
                    eng.idle()
                if bad:
                    rec["status"], rec["error"] = "FAIL", "; ".join(bad)[:300]
                    out["errors"] += 1
                rec["secs"] = round(time.time() - t, 2)
                out["steps"].append(rec)
                print(f"  {name:16s} {rec['status']:5s} {rec['secs']:8.2f} s  {rec.get('error', '')} {rec.get('diff', '')}", flush=True)
                continue
            if method == "VEGETATION":
                rec = {"step": name, "secs": 0.0, "idle": 0.0, "rssGB": round(eng.rss(), 2), "status": "ok"}
                t = time.time()
                bad = []
                exe = os.environ.get("SIMPLER_RENDER_EXE") or ""
                glb = os.path.join(eng.tmp, "reg_tree.glb")
                script = os.path.join(eng.tmp, "mktree.py")
                with open(script, "w") as f:
                    f.write("import bpy, sys\nout = sys.argv[-1]\nbpy.ops.wm.read_factory_settings(use_empty=True)\n"
                            "bpy.ops.mesh.primitive_cylinder_add(radius=0.2, depth=3, location=(0, 0, 1.5)); t = bpy.context.object\n"
                            "m = bpy.data.materials.new('Bark_01'); m.use_nodes = True; t.data.materials.append(m)\n"
                            "bpy.ops.mesh.primitive_ico_sphere_add(radius=1.5, location=(0, 0, 4)); l = bpy.context.object\n"
                            "m2 = bpy.data.materials.new('Material.003'); m2.use_nodes = True\n"
                            "m2.node_tree.nodes['Principled BSDF'].inputs['Base Color'].default_value = (0.1, 0.4, 0.05, 1)\n"
                            "l.data.materials.append(m2)\nbpy.ops.export_scene.gltf(filepath=out)\n")
                if not exe or subprocess.run([exe, "-b", "--python", script, "--", glb], capture_output=True).returncode != 0 or not os.path.isfile(glb):
                    rec["status"] = "skip"
                else:
                    def wait_job(what, kind):
                        t1 = time.time()
                        while time.time() - t1 < 600:
                            if kind == "preview":
                                st, _e = eng.call("GET", f"material/preview/status?id={what}")
                                if (st or {}).get("state") not in ("running", ""):
                                    return st
                            else:
                                st, _e = eng.call("GET", "matbulk/status")
                                if (st or {}).get("state") != "running":
                                    return st
                            time.sleep(0.5)
                        return None
                    r, e = eng.call("POST", "models/import", {"path": glb, "name": "reg_tree", "folder": "", "pivot": "base"}, timeout=300)
                    mid = (r or {}).get("id")
                    if e or not mid:
                        bad.append(f"import: {e}")
                    else:
                        wait_job(r.get("pending"), "preview")
                        t2 = time.time()
                        _r, e2 = eng.call("POST", "models/vegetation", {"ids": [mid]}, timeout=120)
                        st = wait_job(None, "bulk")
                        rec["diff"] = [round(time.time() - t2, 1)]
                        lib = {m_["id"]: m_ for m_ in ((eng.call("GET", "models")[0] or {}).get("models") or [])}
                        ent = lib.get(mid) or {}
                        veg = ent.get("veg") or {}
                        if e2 or (st or {}).get("state") != "done":
                            bad.append(f"vegetation job: {e2} {(st or {}).get('error')}")
                        elif veg.get("leaves") != ["Material.003"] or veg.get("wood") != ["Bark_01"]:
                            bad.append(f"leaves/wood not recognised: {veg}")
                        if not (ent.get("folder") or "").startswith("Vegetazione/") and not (ent.get("folder") or "").startswith("Vegetation/"):
                            bad.append(f"the plant not in Vegetazione: {ent.get('folder')}")
                        if veg.get("type") != "albero":
                            bad.append(f"a 5.5 m plant not a tree: {veg.get('type')}")
                        # by hand: the crown taken for wood
                        eng.call("POST", "models/vegetation", {"ids": [mid], "parts": {mid: {"Material.003": "legno"}}}, timeout=120)
                        wait_job(None, "bulk")
                        eng.call("POST", "models/vegetation", {"ids": [mid], "dry": True}, timeout=120)
                        st = wait_job(None, "bulk") or {}
                        mats = {m_["name"]: m_ for m_ in (((st.get("result") or {}).get("models") or [{}])[0].get("materials") or [])}
                        ent = {m_["id"]: m_ for m_ in ((eng.call("GET", "models")[0] or {}).get("models") or [])}.get(mid) or {}
                        if "Material.003" not in ((ent.get("veg") or {}).get("wood") or []):
                            bad.append(f"«Foglie e legno» by hand not kept: {ent.get('veg')}")
                        if (mats.get("Material.003") or {}).get("part") != "legno":
                            bad.append(f"the dry look does not show the choice made by hand: {mats.get('Material.003')}")
                        eng.call("POST", "models/delete", {"id": mid}, timeout=120)
                if bad:
                    rec["status"], rec["error"] = "FAIL", "; ".join(bad)[:300]
                    out["errors"] += 1
                rec["secs"] = round(time.time() - t, 2)
                out["steps"].append(rec)
                print(f"  {name:16s} {rec['status']:5s} {rec['secs']:8.2f} s  {rec.get('error', '')} {rec.get('diff', '')}", flush=True)
                continue
            if method == "SCENEVEG":
                rec = {"step": name, "secs": 0.0, "idle": 0.0, "rssGB": round(eng.rss(), 2), "status": "ok"}
                t = time.time()
                bad = []
                exe = os.environ.get("SIMPLER_RENDER_EXE") or ""
                d = os.path.join(eng.tmp, "lad", "Simpler", "library", "polyhaven", "models", "reg_bush")
                os.makedirs(d, exist_ok=True)
                script = os.path.join(eng.tmp, "mkbush.py")
                with open(script, "w") as f:
                    f.write("import bpy, os, sys\nout = sys.argv[-1]\nfor o in list(bpy.data.objects): bpy.data.objects.remove(o)\n"
                            "bpy.ops.mesh.primitive_ico_sphere_add(radius=0.5)\no = bpy.context.object; o.name = 'reg_bush'\n"
                            "m = bpy.data.materials.new('reg_bush_leaf'); o.data.materials.append(m)\n"
                            "bpy.data.libraries.write(os.path.join(out, 'm.blend'), {o}, fake_user=True)\n")
                if not exe or subprocess.run([exe, "-b", "--python", script, "--", d], capture_output=True).returncode != 0:
                    rec["status"] = "skip"
                else:
                    with open(os.path.join(d, "model.json"), "w") as f:
                        json.dump({"format": "blend", "file": "m.blend", "v": 2}, f)
                    r, e = eng.call("POST", "library/models/insert", {"id": "reg_bush"}, timeout=900)
                    eng.idle()
                    obj = next((o for o in (eng.call("GET", "scene")[0] or {}).get("objects", []) if "reg_bush" in (o.get("name") or "")
                                and o.get("materials")), None)
                    if e or obj is None:
                        bad.append(f"test bush not in the scene: {e}")
                    else:
                        mn = obj["materials"][0]

                        def fol():
                            ed = eng.call("GET", "material/edit?name=" + urllib.parse.quote(mn))[0] or {}
                            return ((ed.get("params") or {}).get("foliage") or {})
                        t1 = time.time()
                        r2, e2 = eng.call("POST", "scene/vegetation", {"ids": [obj["id"]]}, timeout=300)
                        eng.idle()
                        rec["diff"] = [round(time.time() - t1, 2)]
                        got = [m_.get("part") for m_ in (r2 or {}).get("materials") or []]
                        if e2 or got != ["foglie"] or not fol().get("enabled"):
                            bad.append(f"scene conversion: {e2} {got} {fol()}")
                        eng.call("POST", "undo", {}, timeout=600); eng.idle()
                        if fol().get("enabled"):
                            bad.append("Ctrl+Z did not take the conversion away")
                        if time.time() - t1 > 8:
                            bad.append(f"the conversion of one object took {time.time() - t1:.1f} s")
                    eng.call("POST", "undo", {}, timeout=600); eng.idle()
                if bad:
                    rec["status"], rec["error"] = "FAIL", "; ".join(bad)[:300]
                    out["errors"] += 1
                rec["secs"] = round(time.time() - t, 2)
                out["steps"].append(rec)
                print(f"  {name:16s} {rec['status']:5s} {rec['secs']:8.2f} s  {rec.get('error', '')} {rec.get('diff', '')}", flush=True)
                continue
            if method == "PATHSFOLDERS":
                rec = {"step": name, "secs": 0.0, "idle": 0.0, "rssGB": round(eng.rss(), 2), "status": "ok"}
                t = time.time()
                bad = []
                fl = {x["key"]: x for x in ((eng.call("GET", "paths")[0] or {}).get("folders") or [])}
                if not {"ecosystems", "decals"} <= set(fl):
                    bad.append(f"folders: {sorted(fl)}")
                else:
                    eco0, mod0 = fl["ecosystems"]["path"], fl["models"]["path"]
                    newm = os.path.join(eng.tmp, "moved_models")
                    _r, e1 = eng.call("POST", "paths/set", {"key": "models", "path": newm})
                    fl2 = {x["key"]: x for x in ((eng.call("GET", "paths")[0] or {}).get("folders") or [])}
                    if e1 or os.path.normcase(os.path.normpath(fl2["ecosystems"]["path"])) != os.path.normcase(os.path.normpath(eco0)):
                        bad.append(f"moving the models moved the ecosystems: {e1} {eco0} -> {fl2.get('ecosystems', {}).get('path')}")
                    eng.call("POST", "paths/set", {"key": "models", "path": mod0})
                if bad:
                    rec["status"], rec["error"] = "FAIL", "; ".join(bad)[:300]
                    out["errors"] += 1
                rec["secs"] = round(time.time() - t, 2)
                out["steps"].append(rec)
                print(f"  {name:16s} {rec['status']:5s} {rec['secs']:8.2f} s  {rec.get('error', '')}", flush=True)
                continue
            if method == "SIMPLERLOCK":
                rec = {"step": name, "secs": 0.0, "idle": 0.0, "rssGB": round(eng.rss(), 2), "status": "ok"}
                t = time.time()
                bad = []
                lib = eng.call("GET", "models")[0] or {}
                veg = (lib.get("vegRoot") or "Vegetazione") + "/Simpler"
                # a small model of the scene saved in the library (Simpler unlocked: also one inside Simpler)
                ob_ = next((o for o in (eng.call("GET", "scene")[0] or {}).get("objects", []) if o.get("kind") == "mesh" and not o.get("parent")), None)
                mid = sid = None
                if ob_:
                    r1, _e = eng.call("POST", "models/save", {"ids": [ob_["id"]], "name": "reg_lock", "folder": "reg_lock"}, timeout=300)
                    r2, _e = eng.call("POST", "models/save", {"ids": [ob_["id"]], "name": "reg_lock_s", "folder": "Simpler/reg_lock"}, timeout=300)
                    mid, sid = (r1 or {}).get("id"), (r2 or {}).get("id")
                if not (mid and sid):
                    bad.append(f"test models not saved: {ob_ and ob_.get('name')}")
                eng.call("POST", "models/lock", {"on": True})
                for what, path_, data_ in (("a new folder in Simpler", "models/folder", {"action": "create", "path": "Simpler/reg_x"}),
                                           ("a new folder in Vegetazione Simpler", "models/folder", {"action": "create", "path": veg + "/reg_x"}),
                                           ("renaming the folder that holds Vegetazione Simpler", "models/folder",
                                            {"action": "rename", "path": veg.split("/")[0], "newPath": "reg_veg"}),
                                           ("a model moved into Simpler", "models/move", {"id": mid, "folder": "Simpler"}),
                                           ("a model of Simpler moved out", "models/move", {"id": sid, "folder": "reg_lock"}),
                                           ("a model of Simpler renamed", "models/rename", {"id": sid, "name": "x"}),
                                           ("a model of Simpler deleted", "models/delete", {"id": sid}),
                                           ("a model saved into Simpler", "models/save", {"ids": [ob_ and ob_["id"]], "name": "x", "folder": "Simpler"}),
                                           ("a new folder in Materiali Simpler", "material/library/folder", {"action": "create", "path": "Simpler/reg_x"}),
                                           ("a material moved into Materiali Simpler", "material/library/move", {"id": "reg_none", "folder": "Simpler"})):
                    if path_.startswith("models/") and path_ != "models/folder" and not (mid and sid):
                        continue
                    _r, e_ = eng.call("POST", path_, data_)
                    if not e_:
                        bad.append(f"locked, yet allowed: {what}")
                _r, e_ = eng.call("POST", "models/folder", {"action": "create", "path": "Simpler"})
                if e_:
                    bad.append(f"locked: the root «Simpler» refused: {e_}")
                _r, e_ = eng.call("POST", "models/move", {"id": mid, "folder": ""}) if mid else (None, None)
                if e_:
                    bad.append(f"locked: my own models refused: {e_}")
                eng.call("POST", "models/lock", {"on": False})
                # (Luca: «c'è ancora delete folder») the packs stay read only with the lock off too
                for what, path_, data_ in (("a new folder in Packages (unlocked)", "models/folder", {"action": "create", "path": "Packages/reg_pack/x"}),
                                           ("a model moved into Packages (unlocked)", "models/move", {"id": mid, "folder": "Packages/reg_pack"})):
                    if path_ == "models/move" and not mid:
                        continue
                    _r, e_ = eng.call("POST", path_, data_)
                    if not e_:
                        bad.append(f"unlocked, yet allowed: {what}")
                for x_ in (mid, sid):
                    if x_:
                        _r, e_ = eng.call("POST", "models/delete", {"id": x_}, timeout=120)
                        if e_:
                            bad.append(f"unlocked, a delete refused: {e_}")
                eng.call("POST", "models/folder", {"action": "delete", "path": "Simpler/reg_lock"})
                eng.call("POST", "models/folder", {"action": "delete", "path": "reg_lock"})
                _r, e_ = eng.call("POST", "models/folder", {"action": "create", "path": "Simpler/reg_x"})
                if e_:
                    bad.append(f"unlocked, yet refused: {e_}")
                else:
                    eng.call("POST", "models/folder", {"action": "delete", "path": "Simpler/reg_x"})
                if bad:
                    rec["status"], rec["error"] = "FAIL", "; ".join(bad)[:300]
                    out["errors"] += 1
                rec["secs"] = round(time.time() - t, 2)
                out["steps"].append(rec)
                print(f"  {name:16s} {rec['status']:5s} {rec['secs']:8.2f} s  {rec.get('error', '')}", flush=True)
                continue
            if method == "MATEDITFAST":
                # (1.76.56, Luca: «sto semplicemente aggiungendo delle mappe a un materiale e devo attendere 20-30
                # secondi ogni volta») an edit of a terrain zone's material answers at once (the six materials of
                # the terrain left for later), and Cycles still draws the edit (made before the picture)
                rec = {"step": name, "secs": 0.0, "idle": 0.0, "rssGB": round(eng.rss(), 2), "status": "ok"}
                t = time.time()
                bad = []
                steps = 0
                r, e = eng.call("POST", "terrain/create", {"preset": "montagne", "seed": 4, "rocky": 0.8}, timeout=900)
                eng.idle()
                if e or not r:
                    bad.append(f"terrain not made: {e}")
                else:
                    steps = 1
                    try:
                        from PIL import Image
                        import numpy as _np
                        eng.call("POST", "camera", {"action": "lookat", "position": [-30000, -24000, 24000], "target": [0, 0, 16000], "vfov": 30, "aspect": 1.78})

                        def pic(tag):
                            pth = os.path.join(eng.tmp, f"medit_{tag}.png")
                            eng.call("POST", "render", {"path": pth, "width": 192, "height": 108, "samples": 8, "denoise": False, "inProcess": True}, timeout=1200)
                            eng.idle()
                            return _np.asarray(Image.open(pth).convert("RGB"), dtype=_np.float32) if os.path.isfile(pth) else None
                        a = pic("before")
                        st, _e = eng.call("GET", "terrain/state?id=" + r["id"])
                        rm = (((st or {}).get("zones") or {}).get("roccia") or {}).get("material")
                        times = []
                        for tint in ([0.9, 0.5, 0.4], [0.3, 0.35, 0.6], [0.8, 0.8, 0.8]):
                            t1 = time.time()
                            _r, ee = eng.call("POST", "material/edit", {"name": rm, "params": {"color": {"tint": tint}}}, timeout=900)
                            eng.idle()
                            times.append(round(time.time() - t1, 2))
                            steps += 1
                            if ee:
                                bad.append(f"edit: {ee}")
                        rec["diff"] = times
                        if max(times) > 4.0:
                            bad.append(f"an edit of a terrain material still waits {max(times)} s")
                        n0 = len(open(eng.log).read())
                        b = pic("after")
                        made = re.findall(r"(\d+) materials made for Cycles \(left for later\) in ([\d.]+) s", open(eng.log).read()[n0:])
                        if not made:
                            bad.append("the materials left for later not made before the picture")
                        elif float(made[-1][1]) > 6.0:
                            # (1.76.56, Luca: «ha funzionato ma dopo un sacco di attesa» - 53 s before the path tracing)
                            bad.append(f"the terrain's materials took {made[-1][1]} s to make for Cycles")
                        else:
                            rec["diff"] = times + [f"made {made[-1][0]} in {made[-1][1]} s"]
                        if a is not None and b is not None and float(_np.abs(a - b).mean()) < 0.5:
                            bad.append("the edit of the material not in the picture")
                    except ImportError:
                        rec["status"] = "skip"
                    for _i in range(steps):
                        eng.call("POST", "undo", {}, timeout=600)
                    eng.idle()
                if bad:
                    rec["status"], rec["error"] = "FAIL", "; ".join(bad)[:300]
                    out["errors"] += 1
                rec["secs"] = round(time.time() - t, 2)
                out["steps"].append(rec)
                print(f"  {name:16s} {rec['status']:5s} {rec['secs']:8.2f} s  {rec.get('error', '')} {rec.get('diff', '')}", flush=True)
                continue
            if method == "ROCKDISP":
                # (1.76.55, Luca: «metterei in avanzate il displacement, spento di default») «Displacement vero» of
                # «Rilievo 3D»: the relief becomes geometry in the final render only (nothing sent to the view), its
                # numbers in place, the final render in its own process works, off gives the picture of before
                rec = {"step": name, "secs": 0.0, "idle": 0.0, "rssGB": round(eng.rss(), 2), "status": "ok"}
                t = time.time()
                bad = []
                steps = 0
                sea = bool(((eng.call("GET", "ambience")[0] or {}).get("ocean") or {}).get("on"))
                if sea:
                    eng.call("POST", "landscape/ocean", {"on": False}, timeout=600); eng.idle()
                r, e = eng.call("POST", "terrain/create", {"preset": "montagne", "seed": 4, "rocky": 0.8}, timeout=900)
                eng.idle()
                if e or not r:
                    bad.append(f"terrain not made: {e}")
                else:
                    steps = 1
                    try:
                        from PIL import Image
                        import numpy as _np
                        eng.call("POST", "camera", {"action": "lookat", "position": [-30000, -24000, 24000], "target": [0, 0, 16000], "vfov": 30, "aspect": 1.78})
                        eng.call("POST", "terrain/update", {"id": r["id"], "params": {}}, timeout=900); eng.idle(); steps += 1
                        eng.call("POST", "terrain/tone", {"id": r["id"], "on": False, "relief": 0.9}); eng.idle(); steps += 1

                        def pic(tag, own=False):
                            pth = os.path.join(eng.tmp, f"rdisp_{tag}.png")
                            body = {"path": pth, "width": 320 if own else 192, "height": 180 if own else 108, "samples": 4 if own else 8, "denoise": False}
                            if not own:
                                body["inProcess"] = True
                            rr_, er_ = eng.call("POST", "render", body, timeout=1200)
                            eng.idle()
                            if er_ or not os.path.isfile(pth):
                                bad.append(f"render {tag}: {str(er_)[:120]}")
                                return None
                            return _np.asarray(Image.open(pth).convert("RGB"), dtype=_np.float32)
                        dif = lambda a, b: float(_np.abs(a - b).mean()) if a is not None and b is not None else -1.0
                        a = pic("off")
                        n0 = open(eng.log).read()
                        tr_, et_ = eng.call("POST", "terrain/tone", {"id": r["id"], "rdisp": True}); eng.idle(); steps += 1
                        log_ = open(eng.log).read()[len(n0):]
                        if et_ or not (tr_ or {}).get("tone", {}).get("rdisp"):
                            bad.append(f"rdisp not set: {et_}")
                        if "true relief weights" not in log_:
                            bad.append("no weights for the true relief")
                        if (tr_ or {}).get("terrainBlend"):
                            bad.append(f"the view got materials again for the true relief: {(tr_ or {}).get('terrainBlend')}")
                        b = pic("on")
                        # (1.76.56: the trees - and their subdivision - made when Cycles draws them)
                        if "SIMPLER_DISP" not in open(eng.log).read()[len(n0):]:
                            bad.append("no subdivision for the true relief")
                        rec["diff"] = round(dif(a, b), 2)
                        if 0 <= dif(a, b) < 0.3:
                            bad.append(f"Displacement vero changes nothing ({dif(a, b):.2f})")
                        n1 = open(eng.log).read().count("only its relief numbers changed")
                        tr_, et_ = eng.call("POST", "terrain/tone", {"id": r["id"], "ramp": 2.0, "rfine": 0.0}); eng.idle(); steps += 1
                        if et_ or (tr_ or {}).get("terrainBlend") or open(eng.log).read().count("only its relief numbers changed") <= n1:
                            bad.append(f"Ampiezza/Finezza not set in place: {et_} {(tr_ or {}).get('terrainBlend')}")
                        c = pic("amp2")
                        if 0 <= dif(b, c) < 0.3:
                            bad.append(f"Ampiezza 200% changes nothing ({dif(b, c):.2f})")
                        n2 = len(open(eng.log).read())
                        if pic("own", own=True) is not None and "px for a picture of 320" not in open(eng.log).read()[n2:]:
                            bad.append("the true relief not sized for the picture")
                        tr_, et_ = eng.call("POST", "terrain/tone", {"id": r["id"], "rdisp": False}); eng.idle(); steps += 1
                        d_ = pic("off2")
                        if dif(a, d_) > 0.3:
                            bad.append(f"Displacement vero off: not the picture of before ({dif(a, d_):.2f})")
                    except ImportError:
                        rec["status"] = "skip"
                    for _i in range(steps):
                        eng.call("POST", "undo", {}, timeout=600)
                    eng.idle()
                if sea:
                    eng.call("POST", "undo", {}, timeout=600); eng.idle()
                if bad:
                    rec["status"], rec["error"] = "FAIL", "; ".join(bad)[:300]
                    out["errors"] += 1
                rec["secs"] = round(time.time() - t, 2)
                out["steps"].append(rec)
                print(f"  {name:16s} {rec['status']:5s} {rec['secs']:8.2f} s  {rec.get('error', '')} {rec.get('diff', '')}", flush=True)
                continue
            if method == "ROCKKINDS":
                # (1.76.54, Luca: «voglio che siano usati per modificare la maglia della roccia») the kinds of «Rilievo
                # 3D» change the real shape of the rock; «Attuale» chosen gives the shape of before exactly
                rec = {"step": name, "secs": 0.0, "idle": 0.0, "rssGB": round(eng.rss(), 2), "status": "ok"}
                t = time.time()
                bad = []
                steps = 0
                sea = bool(((eng.call("GET", "ambience")[0] or {}).get("ocean") or {}).get("on"))
                if sea:
                    eng.call("POST", "landscape/ocean", {"on": False}, timeout=600); eng.idle()
                r, e = eng.call("POST", "terrain/create", {"preset": "montagne", "seed": 4, "rocky": 0.8}, timeout=900)
                eng.idle()
                if e or not r:
                    bad.append(f"terrain not made: {e}")
                else:
                    steps += 1
                    try:
                        from PIL import Image
                        import numpy as _np
                        eng.call("POST", "camera", {"action": "lookat", "position": [-30000, -24000, 24000], "target": [0, 0, 16000], "vfov": 30, "aspect": 1.78})
                        eng.call("POST", "terrain/tone", {"id": r["id"], "on": False, "relief": 0.0}); eng.idle(); steps += 1
                        # (made again for this camera first: the fine part of the grid follows the camera)
                        eng.call("POST", "terrain/update", {"id": r["id"], "params": {}}, timeout=900); eng.idle(); steps += 1
                        def shot(nm):
                            pth = os.path.join(eng.tmp, f"kind_{nm}.png")
                            eng.call("POST", "render", {"path": pth, "width": 192, "height": 108, "samples": 8, "denoise": False, "inProcess": True, "seed": 1}, timeout=900)
                            return _np.asarray(Image.open(pth).convert("RGB"), dtype=_np.float32)
                        base = shot("before")
                        pics = {}
                        for kd in ("canaloni", "fratture", "cenge", "attuale"):
                            u, eu = eng.call("POST", "terrain/update", {"id": r["id"], "params": {"rockKind": kd}}, timeout=900); eng.idle()
                            steps += 1
                            if eu:
                                bad.append(f"{kd}: {eu}")
                            pics[kd] = shot(kd)
                        for kd in ("canaloni", "fratture", "cenge"):
                            dk = float(_np.abs(pics[kd] - base).mean())
                            if dk < 1.0:
                                bad.append(f"«{kd}» does not change the shape ({dk:.2f})")
                        d0 = float(_np.abs(pics["attuale"] - base).mean())
                        rec["diff"] = round(d0, 3)
                        if d0 > 0.3:
                            bad.append(f"«Attuale» chosen is not the shape of before ({d0:.2f})")
                    except ImportError:
                        rec["status"] = "skip"
                    for _i in range(steps):
                        eng.call("POST", "undo", {}, timeout=600)
                    eng.idle()
                if sea:
                    eng.call("POST", "undo", {}, timeout=600); eng.idle()
                if bad:
                    rec["status"], rec["error"] = "FAIL", "; ".join(bad)[:300]
                    out["errors"] += 1
                rec["secs"] = round(time.time() - t, 2)
                out["steps"].append(rec)
                print(f"  {name:16s} {rec['status']:5s} {rec['secs']:8.2f} s  {rec.get('error', '')} {rec.get('diff', '')}", flush=True)
                continue
            if method == "OCEANFOLLOW":
                # (1.76.39, Luca: «io non uso sempre e solo la fotocamera?») «Segue l'inquadratura»: the camera looking far
                # away, still - the fine part of the sea goes there; a small move inside it - nothing is done again
                rec = {"step": name, "secs": 0.0, "idle": 0.0, "rssGB": round(eng.rss(), 2), "status": "ok"}
                t = time.time()
                bad = []
                amb = lambda: (eng.call("GET", "ambience")[0] or {}).get("ocean") or {}
                had = bool(amb().get("on"))
                eng.call("POST", "landscape/ocean", {"preset": "mosso", "settings": {"center": "camera", "level": 0.0}}, timeout=900)
                eng.idle()
                lv = float((amb().get("settings") or {}).get("level", 0))
                def look(x, y, z=12.0, tx=None, ty=None):
                    eng.call("POST", "camera", {"action": "lookat", "position": [x * 100, y * 100, (lv + z) * 100],
                                                "target": [(tx if tx is not None else x + 40) * 100, (ty if ty is not None else y) * 100, lv * 100],
                                                "vfov": 45, "aspect": 1.78})
                look(3000.0, 2000.0)
                time.sleep(1.5); eng.idle()
                topo1 = amb().get("topo") or ""
                try:
                    cx, cy = (float(v) for v in topo1.split(",")[:2])
                except ValueError:
                    cx, cy = 0.0, 0.0
                if abs(cx - 3040.0) > 60 or abs(cy - 2000.0) > 60:
                    bad.append(f"the sea did not follow the view: {topo1} (looking at 3040, 2000)")
                look(3010.0, 2005.0)
                time.sleep(1.5); eng.idle()
                if (amb().get("topo") or "") != topo1:
                    bad.append(f"a small move inside the fine part made the sea again: {amb().get('topo')}")
                eng.call("POST", "landscape/ocean", {"settings": {"center": "scena"}}, timeout=900)
                look(-3000.0, -2000.0)
                time.sleep(1.5); eng.idle()
                topo3 = amb().get("topo") or ""
                if topo3.split(",")[:2] == ["-2960.00", "-2000.00"]:
                    bad.append("«Ferma sulla scena» followed the camera")
                eng.call("POST", "landscape/ocean", {"on": False} if not had else {"settings": {"center": "camera"}}, timeout=900)
                eng.idle()
                if bad:
                    rec["status"], rec["error"] = "FAIL", "; ".join(bad)[:300]
                    out["errors"] += 1
                rec["secs"] = round(time.time() - t, 2)
                out["steps"].append(rec)
                print(f"  {name:16s} {rec['status']:5s} {rec['secs']:8.2f} s  {rec.get('error', '')}", flush=True)
                continue
            if method == "ECOBENCH":
                # (1.76.31, Luca) the bench of an ecosystem alone: the rest of the scene hidden (shown again from the
                # scene panel), in one undo step
                rec = {"step": name, "secs": 0.0, "idle": 0.0, "rssGB": round(eng.rss(), 2), "status": "ok"}
                t = time.time()
                bad = []
                vis = lambda: {o["id"]: o.get("visible", True) for o in (eng.call("GET", "scene")[0] or {}).get("objects", [])}
                v0 = vis()
                r, e = eng.call("POST", "ecosystems/plot", {"size": 20}, timeout=300)
                eng.idle()
                if e or not r:
                    bad.append(f"bench not made: {e}")
                else:
                    v1 = vis()
                    hid = r.get("hidden") or []
                    if not hid and sum(1 for k, on in v0.items() if on) > 0:
                        bad.append("bench: nothing of the scene hidden")
                    if any(v1.get(h, False) for h in hid) or not v1.get(r["id"], False):
                        bad.append("bench: hidden ones still visible, or the bench hidden")
                    eng.call("POST", "undo", {}, timeout=300)
                    eng.idle()
                    v2 = vis()
                    if r["id"] in v2 or any(not v2.get(h, True) for h in hid if h in v0 and v0[h]):
                        bad.append("bench: Ctrl+Z did not bring the scene back")
                if bad:
                    rec["status"], rec["error"] = "FAIL", "; ".join(bad)[:300]
                    out["errors"] += 1
                rec["secs"] = round(time.time() - t, 2)
                out["steps"].append(rec)
                print(f"  {name:16s} {rec['status']:5s} {rec['secs']:8.2f} s  {rec.get('error', '')}", flush=True)
                continue
            if method == "TERROCEAN":
                rec = {"step": name, "secs": 0.0, "idle": 0.0, "rssGB": round(eng.rss(), 2), "status": "ok"}
                t = time.time()
                bad = []
                had_sea = bool(((eng.call("GET", "ambience")[0] or {}).get("ocean") or {}).get("on"))
                r, e = eng.call("POST", "terrain/create", {"preset": "colline", "seed": 6}, timeout=900)
                eng.idle()
                info = (r or {}).get("info") or {}
                if e or not r:
                    bad.append(f"terrain not made: {e}")
                else:
                    lo, hi = float(info["min"]), float(info["max"])
                    want = lo + max(1.0, 0.02 * (hi - lo))
                    if not (r.get("params") or {}).get("edgeNatural"):
                        bad.append("a new terrain has the straight edge (1.76.19: bays and headlands)")
                    o, eo = eng.call("POST", "landscape/ocean", {"preset": "mosso"}, timeout=900)
                    lv = lambda: float(((((eng.call("GET", "ambience")[0] or {}).get("ocean") or {}).get("settings")) or {}).get("level", 0))
                    if eo or abs(lv() - want) > 0.6:
                        bad.append(f"sea not at the foot of the terrain: {eo} {lv()} (foot {lo:.1f}, want {want:.1f})")
                    # (1.76.20) a camera 5 m from its target still sees the terrain and the sea far away (Luca: the
                    # path tracing without the mountain - the far clip was 100 x the orbit distance)
                    eng.call("POST", "camera", {"action": "lookat", "position": [0, -150000, 3000], "target": [0, -149500, 2950],
                                                "vfov": 40, "aspect": 1.7})
                    sc_, _e = eng.call("GET", "selfcheck")
                    if "camera_far" in ((sc_ or {}).get("problems") or {}):
                        bad.append("camera: " + "; ".join(sc_["problems"]["camera_far"])[:200])
                    # (1.76.36, Luca: «Acqua mossa sul bordo» did nothing) the sea at the foot of a terrain: the ripples of
                    # the shore have the shape of its water line
                    if "ocean_maps" in ((sc_ or {}).get("problems") or {}):
                        bad.append("sea: " + "; ".join(sc_["problems"]["ocean_maps"])[:200])
                    eng.call("POST", "transform", {"id": r["id"], "location": [0, 0, 5000]})     # (cm: 50 m up)
                    eng.idle()
                    if abs(lv() - (want + 50.0)) > 0.6:
                        bad.append(f"sea did not follow the terrain moved up 50 m: {lv()} (want {want + 50:.1f})")
                    # (1.76.30, Luca: an object moved in the water left «ground» where it had been) the view's poll
                    # brings the coast's map of now, not only the surface
                    am = ((eng.call("GET", "ambience")[0] or {}).get("ocean") or {}).get("coastMap")
                    ri = ((eng.call("GET", "rain/info")[0] or {}).get("ocean") or {})
                    if am and (ri.get("coastMap") or {}).get("rev") != am.get("rev"):
                        bad.append(f"the view's poll has an old coast map: {ri.get('coastMap')} instead of {am}")
                    if not am:
                        bad.append("no coast map with the terrain in the sea")
                    eng.call("POST", "undo", {})
                    eng.idle()
                    if abs(lv() - want) > 0.6:
                        bad.append(f"Ctrl+Z: the sea did not go back with the terrain: {lv()}")
                    eng.call("POST", "landscape/ocean", {"settings": {"level": 0.0}})
                    eng.call("POST", "terrain/update", {"id": r["id"], "params": {"height": 60}}, timeout=900)
                    eng.idle()
                    if abs(lv()) > 0.01:
                        bad.append(f"a level set by hand moved with the terrain: {lv()}")
                    for _i in range(4):
                        eng.call("POST", "undo", {}, timeout=900)
                    eng.idle()
                    if not had_sea:
                        eng.call("POST", "landscape/ocean", {"on": False})
                    eng.call("POST", "undo", {}, timeout=900)
                    eng.idle()
                if bad:
                    rec["status"], rec["error"] = "FAIL", "; ".join(bad)[:300]
                    out["errors"] += 1
                rec["secs"] = round(time.time() - t, 2)
                out["steps"].append(rec)
                print(f"  {name:16s} {rec['status']:5s} {rec['secs']:8.2f} s  {rec.get('error', '')}", flush=True)
                continue
            if method == "SNOWPAINT":
                rec = {"step": name, "secs": 0.0, "idle": 0.0, "rssGB": round(eng.rss(), 2), "status": "ok"}
                t = time.time()
                bad = []

                def whats(secs):
                    seen, t_end = set(), time.time() + secs
                    while time.time() < t_end:
                        b = eng.call("GET", "busy", timeout=10)[0] or {}
                        if b.get("busy"):
                            seen.add(str(b.get("what") or ""))
                        time.sleep(0.15)
                    return seen

                def settle(limit=240):
                    t_end = time.time() + limit
                    quiet = 0
                    while time.time() < t_end and quiet < 8:
                        b = eng.call("GET", "busy", timeout=10)[0] or {}
                        quiet = 0 if b.get("busy") else quiet + 1
                        time.sleep(0.25)

                eng.call("POST", "ambience", {"snow": {"amount": 0.7, "depth": 0.1}})
                settle()
                cam = (eng.call("GET", "scene")[0] or {}).get("camera") or {}
                tgt = cam.get("target") or [0, 0, 0]
                r, err = eng.call("POST", "rain/paint", {"layer": "snow", "points": [[tgt[0], tgt[1], tgt[2]], [tgt[0] + 0.5, tgt[1], tgt[2]]],
                                                        "radius": 0.5, "mode": "add", "strength": 1})
                if err:
                    bad.append(f"stroke: {err}")
                seen = whats(6.0)
                if any(("riparo" in w.lower()) or ("shelter" in w.lower()) or ("costa" in w.lower()) or ("coast" in w.lower()) for w in seen):
                    bad.append("the stroke started the shelter or the coast again: " + ", ".join(sorted(seen)))
                settle()
                eng.call("POST", "rain/paint/clear", {"layer": "snow"})
                settle()
                eng.call("POST", "ambience", {"snow": {"amount": 0.0}})
                settle()
                if bad:
                    rec["status"], rec["error"] = "FAIL", "; ".join(bad)[:300]
                    out["errors"] += 1
                rec["secs"] = round(time.time() - t, 2)
                out["steps"].append(rec)
                print(f"  {name:16s} {rec['status']:5s} {rec['secs']:8.2f} s  {rec.get('error', '')}", flush=True)
                continue
            if method == "PACKS":
                rec = {"step": name, "secs": 0.0, "idle": 0.0, "rssGB": round(eng.rss(), 2), "status": "ok"}
                t = time.time()
                here = os.path.dirname(os.path.abspath(__file__))
                cmd = (["bash", os.path.join(here, "packtest", "run.sh")] if os.name != "nt"
                       else ["dotnet", "run", "--project", os.path.join(here, "packtest"), "-c", "Release"])
                try:
                    cp = subprocess.run(cmd, capture_output=True, text=True, timeout=900)
                    line = next((l for l in cp.stdout.splitlines() if l.startswith("PACKS_")), "FAIL no answer " + cp.stderr[-200:])
                except (OSError, subprocess.TimeoutExpired) as e:
                    line = f"skip {e}"
                if line.startswith("skip"):
                    rec["status"] = "skip"
                elif not line.startswith("PACKS_OK"):
                    rec["status"], rec["error"] = "FAIL", line[:300]
                    out["errors"] += 1
                rec["secs"] = round(time.time() - t, 2)
                out["steps"].append(rec)
                print(f"  {name:16s} {rec['status']:5s} {rec['secs']:8.2f} s  {rec.get('error', '')}", flush=True)
                continue
            if method == "TRANSPMAP":
                rec = {"step": name, "secs": 0.0, "idle": 0.0, "rssGB": round(eng.rss(), 2), "status": "ok"}
                t = time.time()
                exe = os.environ.get("SIMPLER_RENDER_EXE") or ""
                if not exe:
                    rec["status"] = "skip"
                else:
                    script_ = path or "transparency_check.py"
                    cp = subprocess.run([exe, "-b", "--factory-startup", "--python", os.path.join(os.path.dirname(os.path.abspath(__file__)), script_)],
                                        capture_output=True, text=True, timeout=600,
                                        env=dict(os.environ, SIMPLER_CHECK_SCENE=os.path.abspath(scene)))
                    line = next((l for l in cp.stdout.splitlines() if l.startswith(("TRANSP_", "HEAL_", "EMISSION_", "TEXNAME_", "KERB_", "FOLDERDEL_", "LOCK_"))), "FAIL no answer")
                    if line not in ("TRANSP_OK", "HEAL_OK", "EMISSION_OK", "TEXNAME_OK", "KERB_OK", "FOLDERDEL_OK", "LOCK_OK"):
                        rec["status"], rec["error"] = "FAIL", line[:300]
                        out["errors"] += 1
                rec["secs"] = round(time.time() - t, 2)
                out["steps"].append(rec)
                print(f"  {name:16s} {rec['status']:5s} {rec['secs']:8.2f} s  {rec.get('error', '')}", flush=True)
                continue
            if method == "PIVOTPAINT":
                rec = {"step": name, "secs": 0.0, "idle": 0.0, "rssGB": round(eng.rss(), 2), "status": "ok"}
                t = time.time()
                mid = _test_model(eng, args) if args.eco else None
                if not mid:
                    rec["status"] = "skip"
                else:
                    bad = []
                    last_st = [{}]

                    def base_now():
                        st_ = {}
                        for _i in range(150):
                            st_ = eng.call("GET", f"paint/proto?model={mid}")[0] or {}
                            if st_.get("state") != "running":
                                break
                            time.sleep(0.4)
                        last_st[0] = st_
                        return [round(float(v), 4) for v in (st_.get("base") or [])]
                    ri, ei = eng.call("POST", "models/insert", {"id": mid, "location": [0, 0, 0]}, timeout=600)
                    rid = (ri or {}).get("id")
                    items = [{"model": mid, "m": [1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1, 0, 500.0, 500.0, 0.0, 1]}]
                    ps, ep = eng.call("POST", "paint/set", {"items": items, "name": "test pivot"}, timeout=900)
                    eng.idle()
                    b0 = base_now()
                    if ei or not rid or ep or not b0:
                        bad.append(f"model or distribution not made: {ei} {ep} {b0}")
                    else:
                        pv = [round(b0[0] + 0.03, 4), round(b0[1] - 0.02, 4), round(b0[2] + 0.05, 4)]      # (own space, metres)
                        _r, e_ = eng.call("POST", "pivot", {"id": rid, "pivot": pv})
                        eng.idle()
                        try:
                            ent = json.load(open(os.path.join(eng.tmp, "rad", "Simpler", "models", mid + ".json"), encoding="utf-8"))
                        except (OSError, ValueError):
                            ent = {}
                        b1 = base_now()
                        if e_ or [round(v, 4) for v in ent.get("pivot") or []] != pv:
                            bad.append(f"pivot not kept in the library: {e_} {ent.get('pivot')}")
                        if any(abs(a - b) > 1e-3 for a, b in zip(b1, pv)) or len(b1) != 3:
                            bad.append(f"the distribution made before does not stand on the pivot: {b0} -> {b1} (pivot {pv})")
                        # a new copy placed at a point: the pivot lands there
                        r2, e2 = eng.call("POST", "models/insert", {"id": mid, "location": [100, 200, 0]}, timeout=600)
                        ob2 = next((o for o in (eng.call("GET", "scene")[0] or {}).get("objects", []) if o.get("id") == (r2 or {}).get("id")), None)
                        if e2 or not ob2:
                            bad.append(f"second copy not made: {e2}")
                        else:
                            import numpy as _np
                            M = _np.array(ob2["matrixWorld"]).reshape(4, 4).T
                            w = M @ _np.array(pv + [1.0])
                            if not _np.allclose(w[:3], [1.0, 2.0, 0.0], atol=1e-3) or ob2.get("pivot") is None:
                                bad.append(f"a new copy does not stand on its pivot: {w[:3].round(4).tolist()} {ob2.get('pivot')}")
                        # back to automatic: the lowest point again
                        eng.call("POST", "pivot", {"id": rid, "pivot": None})
                        eng.idle()
                        b2 = base_now()
                        if any(abs(a - b) > 1e-3 for a, b in zip(b2, b0)) or len(b2) != 3:
                            bad.append(f"automatic pivot: the base does not come back {b0} -> {b2}")
                        rec["diff"] = [b0, pv, b1, b2, len(last_st[0].get("mats") or {})]
                        # (1.78.4) the prototype brings its materials of Simpler as the view draws them
                        if not isinstance(last_st[0].get("mats"), dict):
                            bad.append("the prototype does not bring its materials (mats)")
                    if bad:
                        rec["status"], rec["error"] = "FAIL", "; ".join(bad)[:300]
                        out["errors"] += 1
                rec["secs"] = round(time.time() - t, 2)
                out["steps"].append(rec)
                print(f"  {name:16s} {rec['status']:5s} {rec['secs']:8.2f} s  {rec.get('error', '')}", flush=True)
                continue
            if method == "PAINTDROP":
                rec = {"step": name, "secs": 0.0, "idle": 0.0, "rssGB": round(eng.rss(), 2), "status": "ok"}
                t = time.time()
                mid = _test_model(eng, args) if args.eco else None
                if not mid:
                    rec["status"] = "skip"
                else:
                    bad = []
                    r, e = eng.call("POST", "terrain/create", {"preset": "colline", "seed": 7}, timeout=900)
                    eng.idle()
                    if e or not r:
                        bad.append(f"terrain not made: {e}")
                    else:
                        items = [{"model": mid, "m": [1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1, 0, x, y, 300.0, 1]} for x, y in ((80, 40), (-60, 90), (120, -110))]
                        ps, ep = eng.call("POST", "paint/set", {"items": items, "name": "test drop"}, timeout=900)
                        gid = (ps or {}).get("group")
                        def zs_of():
                            pi = eng.call("GET", f"paint/points?group={gid}")[0] or {}
                            import glob, numpy as _np
                            f = glob.glob(os.path.join(eng.tmp, "**", "points", pi.get("file", "-")), recursive=True)
                            return sorted(round(float(v), 2) for v in _np.fromfile(f[0], dtype=_np.float32).reshape(-1, 16)[:, 14]) if f else []
                        if ep or not gid:
                            bad.append(f"distribution not made: {ep}")
                        else:
                            z0 = zs_of()
                            d1, ed = eng.call("POST", "paint/drop", {"ids": [gid]}, timeout=900)
                            z1 = zs_of()
                            if ed or (d1 or {}).get("moved") != 3 or not z1 or max(z1) > 120 or min(z1) < -60:
                                bad.append(f"pieces not dropped on the terrain: {ed} {d1} {z0} -> {z1}")
                            u, eu = eng.call("POST", "terrain/update", {"id": r["id"], "params": {"height": 160}}, timeout=900)
                            eng.idle()
                            z2 = zs_of()
                            if eu or z2 == z1 or ((u or {}).get("ecosystems") or {}).get("dropped") != 3:
                                bad.append(f"pieces did not follow the terrain: {eu} {(u or {}).get('ecosystems')} {z1} -> {z2}")
                            eng.call("POST", "undo", {}, timeout=900)
                            eng.idle()
                            if zs_of() != z1:
                                bad.append(f"Ctrl+Z did not put the pieces back: {zs_of()} (want {z1})")
                            eng.call("POST", "undo", {}, timeout=900)
                            if zs_of() != z0:
                                bad.append(f"Ctrl+Z of the drop: {zs_of()} (want {z0})")
                            eng.call("POST", "undo", {}, timeout=900)
                        eng.call("POST", "undo", {}, timeout=900)
                        eng.idle()
                    if bad:
                        rec["status"], rec["error"] = "FAIL", "; ".join(bad)[:300]
                        out["errors"] += 1
                rec["secs"] = round(time.time() - t, 2)
                out["steps"].append(rec)
                print(f"  {name:16s} {rec['status']:5s} {rec['secs']:8.2f} s  {rec.get('error', '')}", flush=True)
                continue
            if method == "SCREE":
                rec = {"step": name, "secs": 0.0, "idle": 0.0, "rssGB": round(eng.rss(), 2), "status": "ok"}
                t = time.time()
                bad = []
                lib = os.path.join(eng.tmp, "rad", "Simpler", "models")
                os.makedirs(lib, exist_ok=True)
                td = os.path.join(ROOT, "tools", "testdata", "models")
                stones = ["m_teststone1", "m_teststone2"]
                for m in stones:
                    if not os.path.isdir(os.path.join(lib, m)):
                        shutil.copytree(os.path.join(td, m), os.path.join(lib, m))
                        shutil.copy(os.path.join(td, m + ".json"), os.path.join(lib, m + ".json"))
                r, e = eng.call("POST", "terrain/create", {"preset": "montagne", "seed": 3}, timeout=900)
                eng.idle()
                if e or not r:
                    bad.append(f"terrain not made: {e}")
                else:
                    tid = r["id"]
                    st = lambda: ((eng.call("GET", "terrain/state?id=" + tid)[0] or {}).get("scree") or [])
                    eng.call("POST", "camview", {"scree": False})        # (the whole terrain: the counts below)
                    a, ea = eng.call("POST", "scree/apply", {"terrain": tid, "models": stones}, timeout=1800)
                    eng.idle()
                    if ea or not a or a.get("pieces", 0) < 200:
                        bad.append(f"stones not laid: {ea} {a and a.get('pieces')}")
                    else:
                        if not a.get("recoloured"):
                            bad.append("the colour of the stones not moved to the rock's")
                        s0 = st()
                        if len(s0) != 1 or s0[0]["pieces"] != a["pieces"] or [m["id"] for m in s0[0]["models"]] != stones:
                            bad.append(f"terrain state: {s0}")
                        u, eu = eng.call("POST", "terrain/update", {"id": tid, "params": {"height": 500}}, timeout=1800)
                        eng.idle()
                        s1 = st()
                        if eu or not s1 or s1[0]["pieces"] == a["pieces"] or ((u or {}).get("ecosystems") or {}).get("done", 0) < 1:
                            bad.append(f"stones not laid again with the terrain: {eu} {(u or {}).get('ecosystems')} {s1 and s1[0]['pieces']}")
                        eng.call("POST", "undo", {}, timeout=900)
                        eng.idle()
                        if (st() or [{}])[0].get("pieces") != a["pieces"]:
                            bad.append(f"Ctrl+Z of the terrain: stones {(st() or [{}])[0].get('pieces')} (want {a['pieces']})")
                        b, eb = eng.call("POST", "scree/apply", {"group": a["group"], "amount": 0.25}, timeout=1800)
                        eng.idle()
                        if eb or not b or not (0.3 * a["pieces"] < b["pieces"] < 0.75 * a["pieces"]) or (st() or [{}])[0].get("settings", {}).get("amount") != 0.25:
                            bad.append(f"half the amount: {eb} {b and b.get('pieces')} of {a['pieces']}")
                        eng.call("POST", "undo", {}, timeout=900)
                        eng.idle()
                        # (1.76.31, Luca) «Grandezza» of all the stones: twice as big, as covered - about a quarter
                        g2, eg2 = eng.call("POST", "scree/apply", {"group": a["group"], "size": 2.0}, timeout=1800)
                        eng.idle()
                        if eg2 or not g2 or not (0.12 * a["pieces"] < g2["pieces"] < 0.45 * a["pieces"]) \
                                or (st() or [{}])[0].get("settings", {}).get("size") != 2.0:
                            bad.append(f"size of all the stones: {eg2} {g2 and g2.get('pieces')} of {a['pieces']}")
                        eng.call("POST", "undo", {}, timeout=900)
                        eng.idle()
                        # (1.76.24) only where the camera looks («Calcola solo l'area inquadrata · Ecosistemi»): a
                        # camera on the foot of a wall - fewer stones, all of them there; per stone size and amount
                        eng.call("POST", "camview", {"scree": True})
                        eng.call("POST", "camera", {"action": "lookat", "position": [(392 - 0.96 * 60) * 100, (-275 - 0.27 * 60) * 100, (72 + 25) * 100],
                                                    "target": [(392 + 0.96 * 20) * 100, (-275 + 0.27 * 20) * 100, 77 * 100], "vfov": 45, "aspect": 1.78})
                        c, ec = eng.call("POST", "scree/apply", {"group": a["group"], "camRefresh": True,
                                                                 "modelScale": {stones[0]: 2.0}, "modelWeight": {stones[1]: 0.0}}, timeout=1800)
                        eng.idle()
                        sc_ = (st() or [{}])[0]
                        if ec or not c or not (0 < c["pieces"] < a["pieces"]) or not sc_.get("camOnly") \
                                or sc_.get("settings", {}).get("modelScale", {}).get(stones[0]) != 2.0:
                            bad.append(f"stones only in the frame / per stone: {ec} {c and c.get('pieces')} of {a['pieces']} {sc_.get('camOnly')}")
                        # (1.76.25) the camera moved: «Ricalcola» counts the stones too, and makes them again
                        eng.call("POST", "camera", {"action": "lookat", "position": [(392 - 0.96 * 200) * 100, (-275 - 0.27 * 200) * 100, (72 + 120) * 100],
                                                    "target": [392 * 100, -275 * 100, 72 * 100], "vfov": 45, "aspect": 1.78})
                        cv = eng.call("GET", "camview")[0] or {}
                        # (1.76.31, Luca: with stones and no ecosystem «Ricalcola» never showed bottom left) the app
                        # asks after a camera move when there are stones: they are counted
                        if cv.get("screeTotal") != 1:
                            bad.append(f"camview: stones not counted ({cv.get('screeTotal')}): «Ricalcola» would not show")
                        if cv.get("screeStale") != 1:
                            bad.append(f"camera moved: stones not to recalculate ({cv.get('screeStale')})")
                        else:
                            eng.call("POST", "camview/refresh", {}, timeout=1800)
                            eng.idle()
                            if (eng.call("GET", "camview")[0] or {}).get("screeStale"):
                                bad.append("«Ricalcola» did not make the stones again")
                            eng.call("POST", "undo", {}, timeout=900)
                            eng.idle()
                        eng.call("POST", "undo", {}, timeout=900)
                        eng.idle()
                        eng.call("POST", "camview", {"scree": False})
                        s2 = (st() or [{}])[0]
                        if s2.get("pieces") != a["pieces"] or s2.get("settings", {}).get("amount") != 0.5:
                            bad.append(f"Ctrl+Z of the amount: {s2.get('pieces')} {s2.get('settings', {}).get('amount')}")
                        eng.call("POST", "undo", {}, timeout=900)
                        eng.idle()
                        if st():
                            bad.append("Ctrl+Z: the stones are still there")
                    eng.call("POST", "undo", {}, timeout=900)
                    eng.idle()
                if bad:
                    rec["status"], rec["error"] = "FAIL", "; ".join(bad)[:300]
                    out["errors"] += 1
                rec["secs"] = round(time.time() - t, 2)
                out["steps"].append(rec)
                print(f"  {name:16s} {rec['status']:5s} {rec['secs']:8.2f} s  {rec.get('error', '')}", flush=True)
                continue
            if method == "PHLOD":
                rec = {"step": name, "secs": 0.0, "idle": 0.0, "rssGB": round(eng.rss(), 2), "status": "ok"}
                t = time.time()
                bad = []
                exe = os.environ.get("SIMPLER_RENDER_EXE") or ""
                d = os.path.join(eng.tmp, "lad", "Simpler", "library", "polyhaven", "models", "reg_lod_rock")
                os.makedirs(os.path.join(d, "textures"), exist_ok=True)
                script = os.path.join(eng.tmp, "mklod.py")
                with open(script, "w") as f:
                    f.write("import bpy, os, sys\nout = sys.argv[-1]\nfor o in list(bpy.data.objects): bpy.data.objects.remove(o)\nobs = set()\n"
                            "for k, sub in enumerate((4, 3, 2)):\n    bpy.ops.mesh.primitive_ico_sphere_add(subdivisions=sub, radius=0.5)\n"
                            "    o = bpy.context.object; o.name = 'reg_lod_rock_LOD%d' % k; obs.add(o)\n"
                            "bpy.data.libraries.write(os.path.join(out, 'm.blend'), obs, fake_user=True)\n")
                if not exe or subprocess.run([exe, "-b", "--python", script, "--", d], capture_output=True).returncode != 0:
                    rec["status"] = "skip"
                else:
                    with open(os.path.join(d, "model.json"), "w") as f:
                        json.dump({"format": "blend", "file": "m.blend", "v": 2}, f)
                    lv, e1 = eng.call("POST", "library/models/lods", {"id": "reg_lod_rock"})
                    if e1 or [x["level"] for x in (lv or {}).get("lods") or []] != [0, 1, 2]:
                        bad.append(f"levels of detail not found: {e1} {lv}")
                    r, e2 = eng.call("POST", "library/models/insert", {"id": "reg_lod_rock", "lod": 1})
                    eng.idle()
                    txt = json.dumps(eng.call("GET", "scene")[0] or {})
                    if e2 or "reg_lod_rock_LOD1" not in txt or "reg_lod_rock_LOD0" in txt or "reg_lod_rock_LOD2" in txt:
                        bad.append(f"not only LOD1 in the scene: {e2}")
                    a, e3 = eng.call("POST", "library/models/tolibrary", {"id": "reg_lod_rock", "lod": 2})
                    b, e4 = eng.call("POST", "library/models/tolibrary", {"id": "reg_lod_rock", "lod": 0})
                    if e3 or e4 or not a or not b or a["id"] == b["id"] or not a["name"].endswith("LOD2"):
                        bad.append(f"library entries per level: {e3} {e4} {a} {b}")
                    eng.idle()
                    eng.call("POST", "undo", {}, timeout=300)
                    eng.idle()
                if bad:
                    rec["status"], rec["error"] = "FAIL", "; ".join(bad)[:300]
                    out["errors"] += 1
                rec["secs"] = round(time.time() - t, 2)
                out["steps"].append(rec)
                print(f"  {name:16s} {rec['status']:5s} {rec['secs']:8.2f} s  {rec.get('error', '')}", flush=True)
                continue
            if method == "PERFTERR":
                rec = {"step": name, "secs": 0.0, "idle": 0.0, "rssGB": round(eng.rss(), 2), "status": "ok"}
                t = time.time()
                bad = []
                eid = _test_eco(eng, args) if state.get("eco") else None
                steps = 0
                sea = bool(((eng.call("GET", "ambience")[0] or {}).get("ocean") or {}).get("on"))
                if sea:
                    eng.call("POST", "landscape/ocean", {"on": False}, timeout=600); eng.idle()
                eng.call("POST", "camera", {"action": "lookat", "position": [-30000, -25000, 6000], "target": [0, 0, 500], "vfov": 50, "aspect": 1.78})
                r, e = eng.call("POST", "terrain/create", {"preset": "colline", "size": 1200.0, "seed": 4}, timeout=900)
                eng.idle()
                if e or not r:
                    bad.append(f"terrain not made: {e}")
                else:
                    steps += 1
                    times = {}
                    if eid:
                        a, ea = eng.call("POST", "ecosystems/apply", {"id": eid, "target": r["zones"]["prato"], "camOnly": True, "camRefresh": True, "density": 0.02, "camFalloff": 0.7}, timeout=1800)
                        eng.idle()
                        if ea:
                            bad.append(f"ecosystem not placed: {ea}")
                        else:
                            steps += 1
                    t1 = time.time()
                    n_same = open(eng.log).read().count("pieces as counted")
                    u, eu = eng.call("POST", "terrain/update", {"id": r["id"], "params": {"sculptAdd": [
                        {"tool": "raise", "r": 15.0, "k": 0.2, "soft": 0.7, "pts": [[200.0, 150.0]] * 5}]}}, timeout=900)
                    eng.idle()
                    times["update"] = round(time.time() - t1, 1)
                    # (1.76.52) an ecosystem made again on the sculpted terrain: its pieces made once, not twice
                    if eid and not eu and open(eng.log).read().count("pieces as counted") <= n_same:
                        bad.append("the pieces of the ecosystem made twice (count, then again)")
                    if eu:
                        bad.append(f"update: {eu}")
                    else:
                        steps += 1
                        if (u or {}).get("terrainBlend"):
                            bad.append(f"the materials of the zones made again for a sculpting: {len(u['terrainBlend'])}")
                    eng.call("POST", "camera", {"action": "lookat", "position": [-28000, -27000, 6000], "target": [3000, 0, 500], "vfov": 50, "aspect": 1.78})
                    t1 = time.time()
                    _c, ec = eng.call("POST", "camview/refresh", {}, timeout=1800)
                    eng.idle()
                    times["refresh"] = round(time.time() - t1, 1)
                    steps += 1
                    rec["times"] = times
                    # (here, a cloud CPU without GPU: 1.76.46 took about the same - the limits catch a step that
                    # comes back, as the 109 s of 1.76.44-46 on Luca's PC)
                    if times["update"] > PERF_LIMITS["update"] or times["refresh"] > PERF_LIMITS["refresh"]:
                        bad.append(f"too slow: {times} (limits {PERF_LIMITS})")
                    for _i in range(steps):
                        eng.call("POST", "undo", {}, timeout=600)
                    eng.idle()
                if sea:
                    eng.call("POST", "undo", {}, timeout=600); eng.idle()
                if bad:
                    rec["status"], rec["error"] = "FAIL", "; ".join(bad)[:300]
                    out["errors"] += 1
                rec["secs"] = round(time.time() - t, 2)
                out["steps"].append(rec)
                print(f"  {name:16s} {rec['status']:5s} {rec['secs']:8.2f} s  {rec.get('error', '')} {rec.get('times', '')}", flush=True)
                continue
            if method == "BLENDINPLACE":
                rec = {"step": name, "secs": 0.0, "idle": 0.0, "rssGB": round(eng.rss(), 2), "status": "ok"}
                t = time.time()
                bad = []
                steps = 0
                sea = bool(((eng.call("GET", "ambience")[0] or {}).get("ocean") or {}).get("on"))
                if sea:
                    eng.call("POST", "landscape/ocean", {"on": False}, timeout=600); eng.idle()
                r, e = eng.call("POST", "terrain/create", {"preset": "colline", "size": 400.0, "seed": 5}, timeout=900)
                eng.idle()
                if e or not r:
                    bad.append(f"terrain not made: {e}")
                else:
                    steps += 1
                    from PIL import Image
                    import numpy as _np
                    eng.call("POST", "camera", {"action": "lookat", "position": [-15000, -12000, 6000], "target": [0, 0, 0], "vfov": 45, "aspect": 1.78})
                    def shot(nm):
                        pth = os.path.join(eng.tmp, f"blend_{nm}.png")
                        eng.call("POST", "render", {"path": pth, "width": 192, "height": 108, "samples": 8, "denoise": False, "inProcess": True}, timeout=900)
                        return _np.asarray(Image.open(pth).convert("RGB"), dtype=_np.float32)
                    shot("first")                   # (1.76.56: the trees are made when Cycles first draws them)
                    n0 = open(eng.log).read().count("set on a copy")
                    t1 = time.time()
                    b1, e1 = eng.call("POST", "terrain/blend", {"id": r["id"], "width": 4.0, "irregular": 0.9}, timeout=900)
                    eng.idle()
                    rec["inplace_s"] = round(time.time() - t1, 1)
                    steps += 1
                    if e1 or not (b1 or {}).get("terrainBlend"):
                        bad.append(f"blend: {e1} {(b1 or {}).get('terrainBlend')}")
                    if open(eng.log).read().count("set on a copy") <= n0:
                        bad.append("the materials were made again, not their numbers set")
                    A = shot("inplace")
                    for w_ in (0.0, 4.0):           # (through no blend at all: made again from nothing)
                        eng.call("POST", "terrain/blend", {"id": r["id"], "width": w_}, timeout=900); eng.idle(); steps += 1
                    B = shot("rebuilt")
                    dif = float(_np.abs(A - B).mean())
                    rec["diff"] = round(dif, 3)
                    if dif > 0.5:
                        bad.append(f"set in place differs from made again: {dif:.2f}")
                    for _i in range(steps):
                        eng.call("POST", "undo", {}, timeout=600)
                    eng.idle()
                if sea:
                    eng.call("POST", "undo", {}, timeout=600); eng.idle()
                if bad:
                    rec["status"], rec["error"] = "FAIL", "; ".join(bad)[:300]
                    out["errors"] += 1
                rec["secs"] = round(time.time() - t, 2)
                out["steps"].append(rec)
                print(f"  {name:16s} {rec['status']:5s} {rec['secs']:8.2f} s  {rec.get('error', '')} {rec.get('inplace_s', '')} {rec.get('diff', '')}", flush=True)
                continue
            if method == "TERRREOPEN":
                # (1.76.51, audit: Luca's terrain opened again made its five materials again, 23 s each opening) a
                # terrain saved and opened again keeps its materials: nothing made again, nothing set
                rec = {"step": name, "secs": 0.0, "idle": 0.0, "rssGB": round(eng.rss(), 2), "status": "ok"}
                t = time.time()
                bad = []
                y = os.path.join(eng.tmp, "before_terrain.simpler")
                x = os.path.join(eng.tmp, "terrain_reopen.simpler")
                eng.call("POST", "save", {"path": y}, timeout=900)
                r, e = eng.call("POST", "terrain/create", {"preset": "colline", "size": 400.0, "seed": 6}, timeout=900)
                eng.idle()
                if e or not r:
                    bad.append(f"terrain not made: {e}")
                else:
                    eng.call("POST", "terrain/tone", {"id": r["id"], "on": True, "relief": 0.5}, timeout=900); eng.idle()
                    eng.call("POST", "save", {"path": x}, timeout=900)
                    n0 = len(open(eng.log).read())
                    t1 = time.time()
                    _o, eo = eng.call("POST", "open", {"path": x}, timeout=900)
                    eng.idle()
                    rec["open_s"] = round(time.time() - t1, 1)
                    tail = open(eng.log).read()[n0:]
                    again = [l_ for l_ in tail.splitlines() if "made again:" in l_ and "SIMPLER_TERRAIN" in l_]
                    if eo or again:
                        bad.append(f"materials of the terrain made again at the opening: {eo} {again[:3]}")
                eng.call("POST", "open", {"path": y}, timeout=900); eng.idle()
                eng.call("POST", "save", {"path": os.path.join(state["tmp"], "again.simpler")})   # (back to its own path)
                if bad:
                    rec["status"], rec["error"] = "FAIL", "; ".join(bad)[:300]
                    out["errors"] += 1
                rec["secs"] = round(time.time() - t, 2)
                out["steps"].append(rec)
                print(f"  {name:16s} {rec['status']:5s} {rec['secs']:8.2f} s  {rec.get('error', '')} {rec.get('open_s', '')}", flush=True)
                continue
            if method == "TERRSCULPT":
                rec = {"step": name, "secs": 0.0, "idle": 0.0, "rssGB": round(eng.rss(), 2), "status": "ok"}
                t = time.time()
                bad = []
                steps = 0
                r, e = eng.call("POST", "terrain/create", {"preset": "colline", "size": 300.0, "height": 10.0, "seed": 3}, timeout=900)
                eng.idle()
                if e or not r:
                    bad.append(f"terrain not made: {e}")
                else:
                    steps += 1
                    tid = r["id"]
                    mx0, mn0 = float(r["info"]["max"]), float(r["info"]["min"])

                    def upd(prm):
                        nonlocal steps
                        r_, e_ = eng.call("POST", "terrain/update", {"id": tid, "params": prm}, timeout=900)
                        eng.idle()
                        if e_ or not r_:
                            bad.append(f"update {list(prm)}: {e_}")
                            return {}
                        steps += 1
                        return r_
                    st = lambda tool, x, y, rr, n: {"tool": tool, "r": rr, "k": 1.0, "soft": 0.7, "pts": [[x, y]] * n}
                    a = upd({"sculptAdd": [st("raise", 0.0, 0.0, 10.0, 100)]})
                    mx1 = float((a.get("info") or {}).get("max", 0))
                    if abs(mx1 - 30.0) > 0.6:
                        bad.append(f"raise: top {mx1:.2f} m, expected 30 (before {mx0:.2f})")
                    b = upd({"sculptAdd": [st("lower", 100.0, 100.0, 20.0, 50)]})
                    mn1 = float((b.get("info") or {}).get("min", 0))
                    if mn1 > mn0 - 20.0:
                        bad.append(f"lower: bottom {mn1:.2f} m (before {mn0:.2f})")
                    c = upd({"sculptAdd": [st("smooth", 0.0, 0.0, 15.0, 100)]})
                    mx2 = float((c.get("info") or {}).get("max", 0))
                    if not mx2 < mx1 - 1.0:
                        bad.append(f"smooth: top {mx2:.2f} m (before {mx1:.2f})")
                    if len((c.get("params") or {}).get("sculpt") or []) != 3:
                        bad.append(f"strokes kept: {len((c.get('params') or {}).get('sculpt') or [])} of 3")
                    eng.call("POST", "undo", {}, timeout=600); eng.idle(); steps -= 1
                    sx = eng.call("GET", f"terrain/state?id={tid}")[0] or {}
                    if len((sx.get("params") or {}).get("sculpt") or []) != 2:
                        bad.append(f"Ctrl+Z: {len((sx.get('params') or {}).get('sculpt') or [])} strokes, expected 2")
                    d_ = upd({"seed": 4})
                    if len((d_.get("params") or {}).get("sculpt") or []) != 2 or float((d_.get("info") or {}).get("max", 0)) < 25.0:
                        bad.append(f"another version: strokes {len((d_.get('params') or {}).get('sculpt') or [])}, top {(d_.get('info') or {}).get('max')}")
                    f_ = upd({"sculpt": []})
                    if (f_.get("params") or {}).get("sculpt") or float((f_.get("info") or {}).get("max", 99)) > 20.0:
                        bad.append(f"remove all: {len((f_.get('params') or {}).get('sculpt') or [])} strokes, top {(f_.get('info') or {}).get('max')}")
                    for _i in range(steps):
                        eng.call("POST", "undo", {}, timeout=600)
                    eng.idle()
                if bad:
                    rec["status"], rec["error"] = "FAIL", "; ".join(bad)[:300]
                    out["errors"] += 1
                rec["secs"] = round(time.time() - t, 2)
                out["steps"].append(rec)
                print(f"  {name:16s} {rec['status']:5s} {rec['secs']:8.2f} s  {rec.get('error', '')}", flush=True)
                continue
            if method == "TERRDEM":
                rec = {"step": name, "secs": 0.0, "idle": 0.0, "rssGB": round(eng.rss(), 2), "status": "ok"}
                t = time.time()
                bad = []
                import numpy as _np
                d = os.path.join(eng.tmp, "dem")
                os.makedirs(d, exist_ok=True)
                yy, xx = _np.mgrid[0:121, 0:121]
                z = 200.0 + 150.0 * _np.exp(-((xx - 60) ** 2 + (yy - 40) ** 2) / 900.0)      # (a hill to the north)
                asc = os.path.join(d, "hill.asc")
                with open(asc, "w") as f:
                    f.write("ncols 121\nnrows 121\nxllcorner 0\nyllcorner 0\ncellsize 20\nNODATA_value -9999\n")
                    for row in z:
                        f.write(" ".join(f"{v:.2f}" for v in row) + "\n")
                hgt = os.path.join(d, "N45E009.hgt")
                (_np.full((1201, 1201), 300) + _np.arange(1201)[None, :] // 4).astype(">i2").tofile(hgt)     # (big-endian, as SRTM)
                # (1.76.34, Luca: «non ci serve portare 100 km di terreno») the SRTM tile is ~92 km: with no square chosen
                # its middle 5 km (the ramp across it: 300 m over 1200 cells, so ~16 m there); a square chosen on the
                # .asc: half of it, the hill inside
                for path, want_size, want_h, crop in ((asc, 2400.0, 150.0, None), (hgt, 5000.0, 16.3, None),
                                                      (asc, 1200.0, 150.0, [0.25, 0.0, 0.5])):
                    body = {"heightmap": path, "size": 1000.0, "hmHeight": 100.0}
                    if crop:
                        body["hmCrop"] = crop
                    r, e = eng.call("POST", "terrain/create", body, timeout=900)
                    eng.idle()
                    p_ = (r or {}).get("params") or {}
                    if e or not r:
                        bad.append(f"{os.path.basename(path)} not made: {e}")
                    else:
                        if want_size and abs(p_.get("size", 0) - want_size) > max(1.0, 0.03 * want_size):
                            bad.append(f"{os.path.basename(path)}: size {p_.get('size')} (want {want_size})")
                        if abs(p_.get("hmHeight", 0) - want_h) > 0.08 * want_h or p_.get("hmErosion") != 0.0:
                            bad.append(f"{os.path.basename(path)}: relief {p_.get('hmHeight')} erosion {p_.get('hmErosion')}")
                        info = r.get("info") or {}
                        if info and abs(float(info.get("height", 0)) - want_h) > 0.25 * want_h:
                            bad.append(f"{os.path.basename(path)}: mesh relief {info.get('height')}")
                        if path == asc and not crop:
                            # («Scegli un'altra parte del file…»: the same file, another square)
                            u, eu = eng.call("POST", "terrain/update", {"id": r["id"], "params": {"hmCrop": [0.5, 0.5, 0.5]}}, timeout=900)
                            eng.idle()
                            pu = (u or {}).get("params") or {}
                            if eu or abs(pu.get("size", 0) - 1200.0) > 36 or not (20 < pu.get("hmHeight", 999) < 130):
                                bad.append(f"another part of the file: {eu} size {pu.get('size')} relief {pu.get('hmHeight')}")
                            eng.call("POST", "undo", {}, timeout=300)
                            eng.idle()
                    eng.call("POST", "undo", {}, timeout=300)
                    eng.idle()
                pv, epv = eng.call("POST", "terrain/dem/preview", {"path": hgt}, timeout=300)
                if epv or not pv or len(pv.get("png") or "") < 1000 or not (4999 < pv.get("maxSide", 0) <= 10000.0) \
                        or pv.get("size", 0) < 50000:
                    bad.append(f"preview of the file for its square: {epv} {pv and {k: v for k, v in pv.items() if k != 'png'}}")
                if bad:
                    rec["status"], rec["error"] = "FAIL", "; ".join(bad)[:300]
                    out["errors"] += 1
                rec["secs"] = round(time.time() - t, 2)
                out["steps"].append(rec)
                print(f"  {name:16s} {rec['status']:5s} {rec['secs']:8.2f} s  {rec.get('error', '')}", flush=True)
                continue
            if method == "PROJFILES":
                rec = {"step": name, "secs": 0.0, "idle": 0.0, "rssGB": round(eng.rss(), 2), "status": "ok"}
                t = time.time()
                bad = []
                mats = (eng.call("GET", "scene/materials")[0] or {}).get("materials") or []
                mname = next((m.get("name") for m in mats if m.get("simpler") and (m.get("users") or 0) > 0), None) \
                    or next((m.get("name") for m in mats if (m.get("users") or 0) > 0), None)
                if not mname:
                    rec["status"] = "skip"
                else:
                    src = os.path.join(state["tmp"], "pf_src")
                    proj = os.path.join(state["tmp"], "pf_proj")
                    os.makedirs(src, exist_ok=True); os.makedirs(proj, exist_ok=True)
                    import struct, zlib
                    def png(path, rgb):
                        raw = b"".join(b"\0" + bytes(rgb) * 8 for _ in range(8))
                        ch = lambda t_, d_: struct.pack(">I", len(d_)) + t_ + d_ + struct.pack(">I", zlib.crc32(t_ + d_) & 0xffffffff)
                        with open(path, "wb") as f:
                            f.write(b"\x89PNG\r\n\x1a\n" + ch(b"IHDR", struct.pack(">IIBBBBB", 8, 8, 8, 2, 0, 0, 0)) + ch(b"IDAT", zlib.compress(raw)) + ch(b"IEND", b""))
                    png(os.path.join(src, "pf_a.png"), (200, 10, 10)); png(os.path.join(src, "pf_b.png"), (10, 200, 10))
                    x = os.path.join(proj, "X.simpler")
                    tdir = os.path.join(proj, "X texture")
                    edits = 0
                    for f in ("pf_a.png", "pf_b.png"):
                        _r, e = eng.call("POST", "material/edit", {"name": mname, "params": {"color": {"map": {"file": os.path.join(src, f)}}}})
                        edits += 0 if e else 1
                        if e:
                            bad.append(f"edit: {e}")
                        r1, e1 = eng.call("POST", "save", {"path": x})
                        if e1 or not os.path.isfile(os.path.join(tdir, f)):
                            bad.append(f"{f} not copied next to the project: {e1}")
                        if (r1 or {}).get("trash"):
                            bad.append(f"a texture still in use (or by the save before) taken away: {r1.get('trash')}")
                    r3, _e = eng.call("POST", "save", {"path": x})
                    tr = [os.path.basename(p) for p in (r3 or {}).get("trash") or []]
                    if tr != ["pf_a.png"]:
                        bad.append(f"the texture no longer used not taken away after two saves: {tr}")
                    ov, eo = eng.call("POST", "project/overwrite", {"path": x})
                    of = [os.path.basename(p) for p in (ov or {}).get("files") or []]
                    if eo or "X.simpler" not in of or "pf_b.png" in of:
                        bad.append(f"overwrite plan wrong (old project listed, the texture in use kept): {eo} {of}")
                    for _ in range(edits):
                        eng.call("POST", "undo", {})
                    eng.call("POST", "save", {"path": os.path.join(state["tmp"], "again.simpler")})   # (back to its own path)
                if bad:
                    rec["status"], rec["error"] = "FAIL", "; ".join(bad)[:300]
                    out["errors"] += 1
                rec["secs"] = round(time.time() - t, 2)
                out["steps"].append(rec)
                print(f"  {name:16s} {rec['status']:5s} {rec['secs']:8.2f} s  {rec.get('error', '')}", flush=True)
                continue
            if method == "TERRSPLIT":
                rec = {"step": name, "secs": 0.0, "idle": 0.0, "rssGB": round(eng.rss(), 2), "status": "ok"}
                t = time.time()
                bad = []
                n0 = len((eng.call("GET", "scene")[0] or {}).get("objects", []))
                r, e = eng.call("POST", "terrain/create", {"preset": "pianura", "seed": 3}, timeout=900)
                eng.idle()
                if e or not r:
                    bad.append(f"not made: {e}")
                else:
                    tid = r["id"]
                    zs = lambda: ((eng.call("GET", f"terrain/state?id={tid}")[0] or {}).get("zones") or {})
                    f0 = zs().get("prato", {}).get("faces", 0)
                    upd = lambda splits: eng.call("POST", "terrain/update", {"id": tid, "params": {"splits": splits}}, timeout=900)
                    t1 = time.time()
                    _u, e1 = upd([{"zone": "prato", "rule": "umido", "amount": 0.3, "irregular": 0.5}])
                    tsplit = time.time() - t1
                    z1 = zs()
                    sk = next((k for k, v in z1.items() if (v.get("split") or {}).get("rule") == "umido"), None)
                    if e1 or not sk or not z1[sk].get("faces") or z1["prato"]["faces"] >= f0:
                        bad.append(f"split not made: {e1} {list(z1)}")
                    else:
                        fa = z1[sk]["faces"]
                        sp = dict(z1[sk]["split"]); sp["amount"] = 0.6
                        upd([sp])
                        fb = zs()[sk]["faces"]
                        if fb <= fa:
                            bad.append(f"more of the zone did not give a bigger part: {fa} -> {fb}")
                        eng.call("POST", "undo", {})
                        if zs()[sk]["faces"] != fa:
                            bad.append("undo did not give the part back as it was")
                        sid = (z1[sk] or {}).get("id")
                        upd([])
                        z2 = zs()
                        # (1.76.31, Luca) the part taken away is gone from the scene tree too
                        if sid and any(o["id"] == sid for o in (eng.call("GET", "scene")[0] or {}).get("objects", [])):
                            bad.append("the split taken away is still in the scene tree")
                        if sk in z2 or abs(z2["prato"]["faces"] - f0) > max(50, f0 * 0.002):
                            bad.append(f"taking the split away did not give the meadow back: {f0} -> {z2.get('prato', {}).get('faces')}")
                        eng.call("POST", "undo", {})
                        if not zs().get(sk, {}).get("faces"):
                            bad.append("undo did not give the part back")
                        eng.call("POST", "undo", {})          # (the split)
                        if zs().get("prato", {}).get("faces") != f0:
                            bad.append("undo of the split did not give the whole meadow back")
                        if tsplit > 60:
                            bad.append(f"a split took {tsplit:.0f} s (the shape is kept: it should not run the erosion again)")
                    eng.call("POST", "undo", {})              # (the terrain)
                    if len((eng.call("GET", "scene")[0] or {}).get("objects", [])) != n0:
                        bad.append("undo did not remove the terrain")
                if bad:
                    rec["status"], rec["error"] = "FAIL", "; ".join(bad)[:300]
                    out["errors"] += 1
                rec["secs"] = round(time.time() - t, 2)
                out["steps"].append(rec)
                print(f"  {name:16s} {rec['status']:5s} {rec['secs']:8.2f} s  {rec.get('error', '')}", flush=True)
                continue
            if method == "RENDERLOCK":
                rec = {"step": name, "secs": 0.0, "idle": 0.0, "rssGB": round(eng.rss(), 2), "status": "ok"}
                t = time.time()
                want = os.path.join(eng.tmp, "locked.png")
                os.makedirs(want, exist_ok=True)          # (a folder with the file's name: it cannot be written)
                r, e = eng.call("POST", "render", {"path": want, "width": 96, "height": 54, "samples": 2, "denoise": False})
                eng.idle()
                got = (r or {}).get("path") or ""
                if e or not got or got == want or not os.path.isfile(got):
                    rec["status"], rec["error"] = "FAIL", f"error {e}, saved as {got!r}"
                    out["errors"] += 1
                rec["secs"] = round(time.time() - t, 2)
                out["steps"].append(rec)
                print(f"  {name:16s} {rec['status']:5s} {rec['secs']:8.2f} s  {rec.get('error', '')}", flush=True)
                continue
            if method == "TILEPROG":
                rec = {"step": name, "secs": 0.0, "idle": 0.0, "rssGB": round(eng.rss(), 2), "status": "ok"}
                sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "engine"))
                from simpler.sampleprog import SampleProgress
                sp, tot, tiles, bad = SampleProgress(), 512, 4, ""
                lines = [("Mem: 1M | Rendered 0/4 Tiles, Sample 0/512", 0)]   # (line, the samples it really means)
                for k in range(tiles):            # (the order Cycles 5 writes them, read from a real tiled render)
                    lines += [(f"Mem: 1M | Rendered {k}/4 Tiles, Sample {s}/512", round((k + s / tot) / tiles * tot))
                              for s in (1, 100, 300, 512)]
                    if k < tiles - 1:             # the next tile, with the samples of this one still at the end
                        lines.append((f"Mem: 1M | Rendered {k + 1}/4 Tiles, Sample 512/512", round((k + 1) / tiles * tot)))
                lines.append(("Mem: 1M | Rendered 3/4 Tiles, Sample 0/512", tot))  # (after the last tile)
                for ln, want in lines:
                    sp.feed(ln)
                    if sp.done != want:
                        bad = f"{ln!r}: {sp.done} samples instead of {want}"
                        break
                if bad:
                    rec["status"], rec["error"] = "FAIL", bad
                    out["errors"] += 1
                out["steps"].append(rec)
                print(f"  {name:16s} {rec['status']:5s}  {rec.get('error', '')}", flush=True)
                continue
            if method == "SEAGLOW":
                rec = {"step": name, "secs": 0.0, "idle": 0.0, "rssGB": round(eng.rss(), 2), "status": "ok"}
                t = time.time()
                info, _e = eng.call("GET", "settings")
                sea = bool(((info or {}).get("refCaustics") or {}) is not None) and \
                    any(str(o.get("name", "")).lower().startswith(("ocean", "oceano", "mare"))
                        for o in (eng.call("GET", "scene")[0] or {}).get("objects", []))
                if not sea:
                    rec["status"] = "skip"
                else:
                    eng.call("POST", "ambience", {"rain": {"wet": 0.6, "puddles": 0.3}}); eng.idle()
                    means = []
                    for i, on in enumerate((True, False, True)):
                        eng.call("POST", "settings", {"config": {"causticsReflected": on}}); eng.idle()
                        path = os.path.join(eng.tmp, f"glow{i}.png")
                        _r, e = eng.call("POST", "render", {"path": path, "width": 160, "height": 90, "samples": 8,
                                                            "denoise": False, "inProcess": True})
                        eng.idle()
                        if e or not os.path.isfile(path):
                            rec["status"], rec["error"] = "FAIL", f"render {i}: {e}"
                            break
                        from PIL import Image
                        import numpy as np
                        means.append(float(np.asarray(Image.open(path).convert("L"), float).mean()))
                    eng.call("POST", "settings", {"config": {"causticsReflected": False}})
                    eng.call("POST", "ambience", {"rain": {"wet": 0.0, "puddles": 0.0}}); eng.idle()
                    if rec["status"] == "ok" and len(means) == 3:
                        rec["means"] = [round(m, 1) for m in means]
                        if abs(means[2] - means[0]) > 2.0:
                            rec["status"], rec["error"] = "FAIL", f"on {means[0]:.1f}, off {means[1]:.1f}, on again {means[2]:.1f}: not the same image"
                    if rec["status"] == "FAIL":
                        out["errors"] += 1
                rec["secs"] = round(time.time() - t, 2)
                out["steps"].append(rec)
                print(f"  {name:16s} {rec['status']:5s} {rec['secs']:8.2f} s  {rec.get('means', '')} {rec.get('error', '')}", flush=True)
                continue
            if method == "QUIET":
                # (1.73.9) at rest the engine must be quiet: with the rain off the shelter stayed «to do» for ever
                # and the engine was busy every 10 ms - a few seconds after the last command, no work at all
                eng.idle()
                busy = 0
                for _ in range(20):
                    b, _e = eng.call("GET", "busy", timeout=10)
                    busy += 1 if (b and b.get("busy")) else 0
                    time.sleep(0.15)
                rec = {"step": name, "secs": 0.0, "idle": 0.0, "rssGB": round(eng.rss(), 2), "status": "ok" if busy == 0 else "FAIL"}
                if busy:
                    rec["error"] = f"busy {busy} times out of 20 with nothing to do"
                    out["errors"] += 1
                out["steps"].append(rec)
                print(f"  {name:16s} {rec['status']:5s}  {rec.get('error', '')}", flush=True)
                continue
            tb0 = eng.tracebacks()
            t = time.time()
            r, err = eng.call(method, path, body)
            dt = time.time() - t
            idle = eng.idle()
            rec = {"step": name, "secs": round(dt, 3), "idle": round(max(0.0, idle), 2), "rssGB": round(eng.rss(), 2)}
            if err == "404":
                rec["status"] = "skip"
            elif err is not None and any(m in err for m in EXPECTED):
                rec["status"] = "ok"                # (an answer, not a failure: e.g. a ground all under the sea)
                rec["note"] = err[:120]
            elif err is None and name.startswith("selfcheck") and isinstance(r, dict) and not r.get("holds", True):
                rec["status"] = "FAIL"
                rec["error"] = json.dumps(r.get("problems"))[:300]
                out["errors"] += 1
            elif err is not None or eng.tracebacks() > tb0:
                rec["status"] = "FAIL"
                rec["error"] = (err or "traceback in the engine log")[:300]
                out["errors"] += 1
            else:
                rec["status"] = "ok"
                if name == "export_view" and isinstance(r, dict) and r.get("state") == "running":
                    t2 = time.time()
                    while time.time() - t2 < 1800:
                        p, _ = eng.call("GET", "preview/status", timeout=10)
                        if not p or p.get("state") != "running":
                            break
                        time.sleep(1)
                    rec["secs"] = round(dt + time.time() - t2, 2)
                if name == "dirt_paint" and isinstance(r, dict):
                    state["dirt"] = r.get("amount")
                    state["probe"] = r.get("probe")
                    if idle > 1.0:
                        rec["status"], rec["error"] = "FAIL", f"a stroke of dirt left {idle:.1f} s of work (shelter, mantle?)"
                        out["errors"] += 1
                elif name == "dirt_repaint" and isinstance(r, dict) and state.get("dirt") is not None:
                    if (r.get("amount") or 0) < state["dirt"]:
                        rec["status"], rec["error"] = "FAIL", f"painting again erased dirt: {state['dirt']} -> {r.get('amount')}"
                        out["errors"] += 1
                elif name == "dirt_step" and isinstance(r, dict) and state.get("probe"):
                    if (r.get("probe") or 0) < state["probe"]:
                        rec["status"], rec["error"] = "FAIL", f"a stroke nearby took the dirt of the floor: {state['probe']} -> {r.get('probe')}"
                        out["errors"] += 1
                if isinstance(r, dict):
                    for k in ("pieces", "tooMany", "farCut", "points"):
                        if k in r:
                            rec[k] = r[k]
            out["steps"].append(rec)
            print(f"  {name:16s} {rec['status']:5s} {rec.get('secs', 0):8.2f} s  idle {rec.get('idle', 0):6.2f} s  "
                  f"{rec.get('rssGB', 0):5.2f} GB  {rec.get('error', '')}", flush=True)
        out["peakGB"] = round(eng.peak, 2)
    finally:
        eng.stop(keep=out["errors"] > 0)
        out["log"] = eng.log if out["errors"] > 0 else None
    return out


def compare(rep, base):
    """Slower than the baseline by more than 50% and 0.5 s (time + idle): a regression."""
    worse = []
    bs = {s["scene"]: s for s in base.get("scenes", [])}
    for s in rep["scenes"]:
        b = bs.get(s["scene"])
        if not b:
            continue
        bsteps = {x["step"]: x for x in b["steps"]}
        # the work of each step (its answer and the idle work after it); the idle work (shelter, mantle, coast) may
        # fall after one step or inside the next, depending on when the engine is free: a step is slower only if it
        # is slower together with the step before it too. The idle work also over the whole scene, with the opening
        idle_a = max(0.0, s.get("open_idle", 0.0)); idle_c = max(0.0, b.get("open_idle", 0.0))
        peak_a = peak_c = 0.0
        prev = None
        new_step = False
        steps = s["steps"]
        for ix, x in enumerate(steps):
            y = bsteps.get(x["step"])
            if not y and x.get("status") == "ok" and not x["step"].startswith(("selfcheck", "quiet")):
                new_step = True             # (a check only reads: it changes nothing)             # (the memory it takes stays: the peak is compared up to here)
            if not y or x.get("status") != "ok" or y.get("status") != "ok" or new_step:
                # (after a step the base did not have - the save and reopen - the engine is in another state: the
                # steps that follow are not compared)
                prev = None
                continue
            a, c = x["secs"] + x["idle"], y["secs"] + y["idle"]
            idle_a += x["idle"]; idle_c += y["idle"]
            if not new_step:
                peak_a = max(peak_a, x.get("rssGB", 0)); peak_c = max(peak_c, y.get("rssGB", 0))
            pa, pc = (prev if prev else (0.0, 0.0))
            # (and with the step after it: the idle work of this step may also fall inside the next one in the base)
            nx_ = steps[ix + 1] if ix + 1 < len(steps) else None
            ny_ = bsteps.get(nx_["step"]) if nx_ else None
            na = nx_["secs"] + nx_["idle"] if nx_ and ny_ and nx_.get("status") == "ok" and ny_.get("status") == "ok" else 0.0
            nc = ny_["secs"] + ny_["idle"] if nx_ and ny_ and nx_.get("status") == "ok" and ny_.get("status") == "ok" else 0.0
            if a > c * 1.5 and a - c > 0.5 and a + pa > (c + pc) * 1.5 and (a + pa) - (c + pc) > 0.5 \
                    and a + pa + na > (c + pc + nc) * 1.5 and (a + pa + na) - (c + pc + nc) > 0.5:
                worse.append((s["scene"], x["step"], round(c, 2), round(a, 2)))
            prev = (a, c)
        if idle_a > idle_c * 1.5 and idle_a - idle_c > 1.0:
            worse.append((s["scene"], "idle work, all steps", round(idle_c, 2), round(idle_a, 2)))
        if s.get("open", 0) > b.get("open", 0) * 1.5 and s.get("open", 0) - b.get("open", 0) > 1.0:
            worse.append((s["scene"], "open", b.get("open"), s.get("open")))
        # (memory after the steps both versions have: a new step - the final render - does not count against the old)
        if peak_a > peak_c * 1.3 and peak_a - peak_c > 0.5:
            worse.append((s["scene"], "memory after the steps in common, GB", peak_c, peak_a))
    return worse


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--scene", action="append", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--base")
    ap.add_argument("--engine", default=os.path.join(ROOT, "engine"))
    ap.add_argument("--eco")
    ap.add_argument("--port", type=int, default=8811)
    ap.add_argument("--compare", help="only compare this report with --base (no run)")
    ap.add_argument("--quick", action="store_true", help="only opening, self-check, engine at rest, save and reopen")
    ap.add_argument("--only", action="append", default=[], help="only these steps (after the opening): a targeted test")
    ap.add_argument("--skip", action="append", default=[], help="scene.simpler:step left out (a step the test computer cannot do)")
    args = ap.parse_args()
    if args.compare:
        with open(args.compare, encoding="utf8") as f, open(args.base, encoding="utf8") as g:
            for w in compare(json.load(f), json.load(g)):
                print("SLOWER", w)
        return
    rep = {"engine": args.engine, "when": time.strftime("%Y-%m-%d %H:%M"), "scenes": []}
    for sc in args.scene:
        print("==", os.path.basename(sc), flush=True)
        rep["scenes"].append(run_scene(args, sc))
    fails = sum(s["errors"] for s in rep["scenes"])
    if args.base and os.path.isfile(args.base):
        with open(args.base, encoding="utf8") as f:
            rep["slower"] = compare(rep, json.load(f))
    with open(args.out, "w", encoding="utf8") as f:
        json.dump(rep, f, indent=1)
    print(f"\nerrors: {fails}")
    for w in rep.get("slower", []):
        print("SLOWER", w)
    sys.exit(1 if fails or rep.get("slower") else 0)


if __name__ == "__main__":
    main()
