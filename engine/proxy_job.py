"""Texture proxies: smaller copies of big textures for the previews (real-time view and path tracing view).

Started by the engine, several at once (one per CPU core it can use):
    blender.exe --factory-startup -b --python proxy_job.py -- <jobs.json>
jobs.json: [[source, destination without extension, max px (0 = exact local copy)], ...]
Prints "SIMPLER_PROXY <source>\t<px>\t<written file>" for every texture (written file empty when it failed).

The proxies live in a cache on the local disk and are reused by every project that uses the same texture file:
the second time a model is opened, nothing has to be converted again. Final renders always use the originals.
"""
import json
import os
import sys

import bpy

argv = sys.argv[sys.argv.index("--") + 1:]
with open(argv[0], encoding="utf-8") as f:
    jobs = json.load(f)

import shutil

for src, dst, max_px in jobs:
    out = ""
    if max_px <= 0:
        # texture on a network drive: an exact copy on the local disk, nothing decoded
        try:
            ext = os.path.splitext(src)[1].lower()
            tmp = dst + "_copy.part" + ext
            shutil.copyfile(src, tmp)
            os.replace(tmp, dst + "_copy" + ext)
            out = dst + "_copy" + ext
        except OSError as exc:
            print("SIMPLER_WARN", src, exc, flush=True)
        print(f"SIMPLER_PROXY {src}\t0\t{out}", flush=True)
        continue
    try:
        im = bpy.data.images.load(src, check_existing=False)
        try:
            w, h = im.size
            if w * h > 0:
                k = min(1.0, max_px / max(w, h))
                if k < 1.0:
                    im.scale(max(1, int(w * k)), max(1, int(h * k)))
                alpha = im.channels == 4 and im.alpha_mode != "NONE" and os.path.splitext(src)[1].lower() not in (".jpg", ".jpeg")
                ext = ".png" if alpha else ".jpg"
                tmp = dst + ".part" + ext
                im.filepath_raw = tmp
                im.file_format = "PNG" if alpha else "JPEG"
                if alpha:
                    bpy.context.scene.render.image_settings.compression = 15
                im.save(quality=90) if not alpha else im.save()
                os.replace(tmp, dst + ext)
                out = dst + ext
        finally:
            bpy.data.images.remove(im)
    except Exception as exc:  # unreadable texture: the preview keeps the original
        print("SIMPLER_WARN", src, exc, flush=True)
    print(f"SIMPLER_PROXY {src}\t{max_px}\t{out}", flush=True)
print("SIMPLER_DONE", flush=True)
