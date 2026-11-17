"""The table of sky colours for "Colori da una foto" (simpler/skyphoto.py), made once with Simpler itself.

Started by the engine (server.py, when the file test_out/tabella_cielo.on is there) as:
    blender.exe --factory-startup -b --python sky_table_job.py -- <device> <progress.txt>
For every combination of height of the sun, haze, ozone and clouds: a small render of the sky only (camera towards
the sun, 10 degrees up), through the same pipeline as the final render (sky, volumetric clouds, haze, exposure,
colour rendering), reduced to its main colours. Written to assets/sky_table.json as it goes: when stopped, it goes
on from where it was the next time.
"""
import copy
import json
import math
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import bpy  # noqa: E402
import numpy as np  # noqa: E402

argv = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
device = argv[0] if argv else "CPU"
log_path = argv[1] if len(argv) > 1 else ""

from simpler import ambience, clouds, progress, render, scene_ops, server, skyphoto  # noqa: E402

ELEVS = [-4.0, -2.5, -1.0, 0.0, 1.0, 2.0, 3.5, 6.0, 10.0, 18.0, 35.0]
AEROSOL = [0.6, 1.2, 2.2, 4.0]
OZONE = [0.8, 1.5]
CLOUDS = [("cumuli_grandi", 0.35), ("altocumuli", 0.6), ("strati", 0.9),
          ("cumuli_grandi", 0.7)]     # (1.17.12: a covered sky "in banks", dark masses with gaps, for Nuvoloso)
# version 2: the exposure of the camera and the colour rendering too. Version 1 (only the sky) came out pale next
# to photos (chroma 5-25 against 40-60): a sunset photo is exposed for the bright sky, and AgX fades the bright
# colours towards white; with Vivid they stay saturated
EXPOSURES = [0.0, -1.0, -2.0]
RENDERS = ["natural", "vivid"]
VERSION = 2
PROBE = {"elev": (1.0, -2.5), "aerosol": (2.2,), "ozone": (1.5,)}     # these are also saved as pictures, to look at
W, H = 192, 108
SAMPLES = 32
SKY_ROWS = 0.68          # rows above the horizon (camera 10 degrees up, 24 mm)


def say(text):
    print("SIMPLER_SKYTABLE " + text, flush=True)
    if log_path:
        with open(log_path, "a", encoding="utf-8") as f:
            f.write(time.strftime("%H:%M:%S ") + text + "\n")


def read_png(path):
    im = bpy.data.images.load(path, check_existing=False)
    try:
        im.colorspace_settings.name = "Non-Color"
        w, h = im.size[:]
        px = np.empty(w * h * 4, dtype=np.float32)
        im.pixels.foreach_get(px)
        return px.reshape(h, w, 4)[::-1, :, :3]          # (Blender: bottom row first)
    finally:
        bpy.data.images.remove(im)


def main():
    progress.install()
    server.project_new({})
    render.STATE.device = device if device else render.STATE.device
    table = {"version": VERSION, "size": [W, H], "samples": SAMPLES, "entries": []}
    if os.path.isfile(skyphoto.TABLE):
        try:
            with open(skyphoto.TABLE, encoding="utf-8") as f:
                old = json.load(f)
            if old.get("version") == VERSION:
                table = old
        except ValueError:
            pass
    done = {json.dumps(e["params"], sort_keys=True) for e in table["entries"]}
    combos = [(e, a, o, t, c, ev, cr) for e in ELEVS for a in AEROSOL for o in OZONE for t, c in CLOUDS
              for ev in EXPOSURES for cr in RENDERS]
    probe_dir = os.path.join(os.path.dirname(log_path), "tabella_prova") if log_path else ""
    if probe_dir:
        os.makedirs(probe_dir, exist_ok=True)
    tmp = os.path.join(render.STATE.tmp, "skytable.png")
    say(f"start: {len(combos)} combinations, {len(done)} already in the table")
    t_start = time.time()
    n_new = 0
    for i, (elev, aer, ozo, ctype, cover, ev, cr) in enumerate(combos):
        params = {"elev": elev, "aerosol": aer, "ozone": ozo, "type": ctype, "cover": cover, "ev": ev, "render": cr}
        key = json.dumps(params, sort_keys=True)
        if key in done:
            continue
        s = copy.deepcopy(ambience.DEFAULTS)
        s["mode"], s["preset"] = "sky", "custom"
        s["sun"]["hour"] = ambience._hour_for_elev(elev, True, s["sun"])
        s["sky"].update(aerosol=aer, ozone=ozo)
        s["clouds"].update(dict(clouds.TYPES[ctype], volumetric=True, type=ctype, cover=cover))
        s["fog"]["density"] = 0.2
        ambience.apply(new=s)
        v = ambience._sun_dir(s)
        az = math.degrees(math.atan2(v.y, v.x))
        render.STATE.camera = {"target": [0.0, 0.0, 160.0], "distance": 600.0, "yaw": az + 180.0, "pitch": -10.0,
                               "lens": 24.0}
        render.STATE.config["exposure"] = ev
        render.STATE.config["colorRender"] = cr
        t0 = time.time()
        try:
            render.final_render({"path": tmp, "width": W, "height": H, "quality": "attuale", "samples": SAMPLES,
                                 "inProcess": True, "textures": 1024})
            rgb = read_png(tmp)
            if probe_dir and elev in PROBE["elev"] and aer in PROBE["aerosol"] and ozo in PROBE["ozone"]:
                import shutil
                shutil.copyfile(tmp, os.path.join(probe_dir, f"sole{elev:+.1f}_{ctype}_ev{ev:+.0f}_{cr}.png"))
        except Exception as ex:
            say(f"{key} failed: {ex}")
            continue
        sky = rgb[: int(rgb.shape[0] * SKY_ROWS)]
        table["entries"].append({"params": params, "hour": s["sun"]["hour"], "desc": skyphoto.describe(sky)})
        n_new += 1
        if n_new % 5 == 0 or i == len(combos) - 1:
            with open(skyphoto.TABLE, "w", encoding="utf-8") as f:
                json.dump(table, f)
        left = (time.time() - t_start) / n_new * (len(combos) - len(done) - n_new)
        say(f"{len(table['entries'])}/{len(combos)} {key} {time.time() - t0:.1f}s, about {left / 60:.0f} min left")
    with open(skyphoto.TABLE, "w", encoding="utf-8") as f:
        json.dump(table, f)
    say(f"done: {len(table['entries'])} combinations in {(time.time() - t_start) / 60:.1f} min")
    if log_path:                        # complete: the flag that asks for it goes away
        try:
            os.remove(os.path.join(os.path.dirname(log_path), "tabella_cielo.on"))
        except OSError:
            pass


try:
    main()
except Exception as exc:
    import traceback
    traceback.print_exc()
    say(f"failed: {exc}")
print("SIMPLER_DONE", flush=True)
