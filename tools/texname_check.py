"""(1.78.4, Luca: flowers yellow in path tracing, violet in the real-time view; Rumex with solid leaf cards) Pictures
for the real-time view:
- a name used again for another picture (generic names of imported plants, «color map.015») gives the new picture,
  not the file remembered for the old one;
- a GIF (a cut-out mask: Blender opens it as a movie) is served as a still PNG with the same pixels;
- the materials sent to the view say which picture a name means (rev), so the view does not reuse an old one.
Run inside Blender:
    blender -b --factory-startup --python tools/texname_check.py
Prints TEXNAME_OK or TEXNAME_FAIL <why>."""
import os
import struct
import sys
import tempfile

import bpy

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "engine"))
from simpler import materials, matedit, proxies, stillgif     # noqa: E402

bad = []
tmp = tempfile.mkdtemp(prefix="simpler_texname_")
try:
    def png(path, rgb):
        w = h = 8
        stillgif.write_png(path, w, h, bytes(list(rgb) + [255]) * (w * h))

    a, b = os.path.join(tmp, "a.png"), os.path.join(tmp, "b.png")
    png(a, (255, 255, 0))
    png(b, (160, 0, 200))
    im = bpy.data.images.load(a)
    im.name = "color map.015"
    if os.path.normcase(proxies.source_of(im) or "") != os.path.normcase(a):
        bad.append("first picture not found")
    bpy.data.images.remove(im)
    im2 = bpy.data.images.load(b)
    im2.name = "color map.015"
    got = proxies.source_of(im2) or ""
    if os.path.normcase(got) != os.path.normcase(b):
        bad.append(f"the name used again gives the old picture: {os.path.basename(got)}")
    # a GIF: a still PNG with the same pixels
    gif = os.path.join(tmp, "mask.gif")
    w, h = 5, 3
    pal = bytes([0, 0, 0, 255, 255, 255]) + bytes(6)             # 4 colours: black, white
    idx = bytes([1, 0, 1, 0, 1] * 3)
    # (an uncompressed-looking LZW stream: clear code before every 2 pixels keeps the code size at 3 bits)
    codes, clear, end = [], 4, 5
    for i in range(0, len(idx), 2):
        codes += [clear] + list(idx[i:i + 2])
    codes.append(end)
    bits = nb = 0
    data = bytearray()
    for c in codes:
        bits |= c << nb
        nb += 3
        while nb >= 8:
            data.append(bits & 255)
            bits >>= 8
            nb -= 8
    if nb:
        data.append(bits & 255)
    body = b"GIF89a" + struct.pack("<HHBBB", w, h, 0x81, 0, 0) + pal + b"\x2c" + struct.pack("<HHHHB", 0, 0, w, h, 0) + \
        b"\x02" + bytes([len(data)]) + bytes(data) + b"\x00\x3b"
    with open(gif, "wb") as f:
        f.write(body)
    got = stillgif.read(gif)
    if not got or got[0] != w or got[1] != h or got[2][0:4] != bytes((255, 255, 255, 255)) or got[2][4:8] != bytes((0, 0, 0, 255)):
        bad.append("GIF not read")
    if proxies.dims(gif) != (w, h):
        bad.append(f"GIF size not read: {proxies.dims(gif)}")
    gi = bpy.data.images.load(gif)
    src = proxies.source_of(gi) or ""
    if not src.lower().endswith(".png") or not os.path.isfile(src):
        bad.append(f"GIF not served as a PNG: {src}")
    # rev: another picture under the same name, another rev
    mat = bpy.data.materials.new("Leaf")
    p = matedit._merge(matedit.DEFAULTS, {})
    p["color"]["map"]["image"] = "color map.015"
    matedit._Builder(mat, p).build()
    mat[matedit.PARAMS_KEY] = __import__("json").dumps(p)
    r1 = (materials.realtime_params(mat).get("maps") or {}).get("color") or {}
    bpy.data.images["color map.015"].filepath = a
    r2 = (materials.realtime_params(mat).get("maps") or {}).get("color") or {}
    if not r1.get("rev") or r1.get("rev") == r2.get("rev"):
        bad.append(f"rev not telling the pictures apart: {r1.get('rev')} {r2.get('rev')}")
except Exception as exc:
    import traceback
    traceback.print_exc()
    bad.append(f"error: {exc}")
finally:
    import shutil
    shutil.rmtree(tmp, ignore_errors=True)
print("TEXNAME_FAIL " + "; ".join(bad) if bad else "TEXNAME_OK", flush=True)
