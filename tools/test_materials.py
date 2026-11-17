"""Test of the material editor API (run like test_engine.py, with the engine started).
Usage: blender -b --python test_materials.py -- <fbx> <outdir>"""
import json
import os
import sys
import time
import urllib.request

BASE = "http://127.0.0.1:8787/api"
_args = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else sys.argv[1:]
fbx, outdir = _args[0], _args[1]
os.makedirs(outdir, exist_ok=True)
FAILS = 0


def call(path, body=None):
    req = urllib.request.Request(BASE + path, data=None if body is None else json.dumps(body).encode(),
                                 headers={"Content-Type": "application/json"}, method="GET" if body is None else "POST")
    try:
        with urllib.request.urlopen(req, timeout=3600) as r:
            return json.loads(r.read())
    except urllib.error.HTTPError as e:
        return json.loads(e.read())


def check(label, res, cond=True):
    global FAILS
    ok = bool(res.get("ok")) and cond
    print(("PASS " if ok else "FAIL ") + label, "" if ok else json.dumps(res)[:400])
    FAILS += 0 if ok else 1
    return res


def make_textures():
    """Small test maps (colour with alpha, grey, normal) written as PNG."""
    import bpy
    paths = {}
    for name, fill in (("col", lambda x, y: ((x // 8 + y // 8) % 2 * 0.8 + 0.1, 0.4, 0.2, 1.0 if x < 48 else 0.0)),
                       ("rough", lambda x, y: (x / 63, x / 63, x / 63, 1.0)),
                       ("nrm", lambda x, y: (0.5, 0.5 + 0.3 * ((y // 8) % 2), 1.0, 1.0)),
                       ("height", lambda x, y: (((x // 16) + (y // 16)) % 2, 0, 0, 1.0))):
        im = bpy.data.images.new(name, 64, 64, alpha=True)
        px = []
        for y in range(64):
            for x in range(64):
                px.extend(fill(x, y))
        im.pixels = px
        path = os.path.join(outdir, f"tex_{name}.png")
        im.filepath_raw = path
        im.file_format = "PNG"
        im.save()
        paths[name] = path
    return paths


tex = make_textures()
check("import FBX", call("/import", {"path": fbx}))
scene = call("/scene")["objects"]
mesh = next(o for o in scene if o["kind"] == "mesh" and o.get("materials"))
mname = mesh["materials"][0]
check("assign preset first", call("/material/assign", {"ids": [mesh["id"]], "material": "plastica_opaca"}))
mname = "Plastica opaca"

r = check("read material", call("/material/edit?name=" + urllib.parse.quote(mname)))
check("not advanced", r, r.get("advanced") is False)

r = check("edit color map + roughness map + normal", call("/material/edit", {"name": mname, "params": {
    "color": {"map": {"file": tex["col"]}, "tint": [1, 1, 1]},
    "roughness": {"map": {"file": tex["rough"], "strength": 1.0}},
    "normal": {"map": {"file": tex["nrm"]}, "strength": 0.8, "directx": True},
    "opacity": {"useAlpha": True},
    "uv": {"mode": "box", "sizeCm": 20, "randomize": True}}}))
p = r.get("params", {})
check("params stored", r, p.get("color", {}).get("map", {}).get("image") == "tex_col.png" and p["uv"]["mode"] == "box")

r = call("/material/edit?name=" + urllib.parse.quote(mname))
check("read back canonical", r, r.get("simpler") is True and r["params"]["normal"]["directx"] is True)

r = check("glass with dispersion", call("/material/edit", {"name": mname, "params": {
    "transmission": {"weight": 1.0, "ior": 2.417, "dispersion": True, "abbe": 55.3, "dispersionBoost": 2.0},
    "color": {"map": {"image": ""}}, "opacity": {"useAlpha": False}}}))
check("dispersive flag", r, r.get("dispersive") is True)
check("caustics on with dispersive glass", call("/settings", {"caustics": True}))

r = check("displacement", call("/material/edit", {"name": mname, "params": {
    "displacement": {"enabled": True, "map": {"file": tex["height"]}, "heightCm": 0.5, "detail": "media"}}}))

# rt params
r = call("/realtime/materials", {"ids": [mesh["id"]]})
slots = r.get("objects", {}).get(mesh["id"], [])
check("realtime params", r, bool(slots) and slots[0].get("simpler") is True and slots[0].get("dispersion") is True)

# path tracing pass with all of it
call("/settings", {"viewport": [320, 200], "live": True})
t = time.time()
while time.time() - t < 600:
    info = json.loads(urllib.request.urlopen(BASE + "/frame/info").read())
    if info.get("pass", -1) >= 1 and info.get("epoch") == info.get("current"):
        break
    if info.get("error"):
        break
    time.sleep(0.5)
check("path tracing with new material", {"ok": not info.get("error")}, info.get("pass", -1) >= 1)
data = urllib.request.urlopen(BASE + "/frame").read()
open(os.path.join(outdir, "material_viewport.jpg"), "wb").write(data)

# undo / redo of material edits (no file copy)
t = time.time()
h = check("undo material", call("/undo", {}))
check("undo is light", h, h.get("kind") == "material" and time.time() - t < 5)
r = call("/material/edit?name=" + urllib.parse.quote(mname))
check("undo removed displacement", r, r["params"]["displacement"]["enabled"] is False)
check("redo material", call("/redo", {}))
r = call("/material/edit?name=" + urllib.parse.quote(mname))
check("redo restored displacement", r, r["params"]["displacement"]["enabled"] is True)

r = check("duplicate material", call("/material/duplicate", {"name": mname, "id": mesh["id"], "slot": 0}))
dup = r.get("name")
check("rename material", call("/material/rename", {"name": dup, "newName": "Mio vetro"}))
r = check("scene materials", call("/scene/materials"))
check("renamed listed", r, any(m["name"] == "Mio vetro" for m in r.get("materials", [])))
check("replace everywhere", call("/material/replace", {"name": "Mio vetro", "with": "oro_giallo"}))
check("reset", call("/material/reset", {"name": mname}))

# texture endpoint for the real-time view
req = urllib.request.urlopen(BASE + "/texture?image=tex_rough.png&px=256")
check("texture served", {"ok": req.status == 200}, len(req.read()) > 50)

# pick reports slot and material
r = check("pick with material", call("/pick", {"u": 0.5, "v": 0.5}))
print("   pick:", r)
# live preview of the editor (separate Blender process) and the user's library
def wait_preview(rid, timeout=600):
    t = time.time()
    while time.time() - t < timeout:
        st = json.loads(urllib.request.urlopen(BASE + f"/material/preview/status?id={rid}").read())
        if st.get("state") != "running":
            return st
        time.sleep(0.3)
    return {"state": "timeout"}
r = check("live preview request", call("/material/livepreview", {"name": "Oro giallo 18k"}))
st = wait_preview(r.get("id"))
check("live preview rendered", {"ok": st.get("state") == "done"}, os.path.isfile(st.get("path", "")))
png = urllib.request.urlopen(BASE + f"/material/preview/file?id={r.get('id')}").read()
check("live preview served", {"ok": png[:4] == b"\x89PNG"})
r = check("open library material", call("/material/open", {"id": "argento"}))
lib_name = r.get("name")
check("edit library material", call("/material/edit", {"name": lib_name, "params": {"color": {"tint": [0.9, 0.2, 0.2]}}}))
r = call("/material/edit?name=" + urllib.parse.quote(lib_name))
check("dirty after edit", r, r.get("dirty") is True and (r.get("library") or {}).get("id") == "argento")
r = check("save (overwrite)", call("/material/save", {"name": lib_name}))
lib = call("/materials")["materials"]
arg = next(m for m in lib if m["id"] == "argento")
check("library overridden", {"ok": True}, arg["user"] and arg["overrides"] and arg["rev"] != "base")
r = check("save as new", call("/material/save", {"name": lib_name, "asNew": True, "newName": "Argento rosso test"}))
new_id = r.get("id")
lib = call("/materials")["materials"]
check("new in library", {"ok": True}, any(m["id"] == new_id for m in lib))
r = check("thumbnail of new material", call("/materials/preview", {"id": new_id, "folder": os.path.join(outdir, "previews"), "wait": True}))
check("thumbnail file", {"ok": True}, os.path.isfile(r.get("path", "")))
# folders of the library
check("create folder", call("/material/library/folder", {"action": "create", "path": "Test cartelle/Legno"}))
r = check("save as new into folder", call("/material/save", {"name": lib_name, "asNew": True, "newName": "Rovere test", "folder": "Test cartelle/Legno/Parquet"}))
oak = r.get("id")
lib = call("/materials")
check("folder tree", lib, {"Test cartelle", "Test cartelle/Legno", "Test cartelle/Legno/Parquet"} <= set(lib.get("folders", [])))
check("material in folder", lib, next(m for m in lib["materials"] if m["id"] == oak)["folder"] == "Test cartelle/Legno/Parquet")
check("move built-in", call("/material/library/move", {"id": "cromo", "folder": "Test cartelle/Metallo"}))
check("rename folder", call("/material/library/folder", {"action": "rename", "path": "Test cartelle/Legno", "newPath": "Test cartelle/Legni"}))
lib = call("/materials")
check("renamed with contents", lib, next(m for m in lib["materials"] if m["id"] == oak)["folder"] == "Test cartelle/Legni/Parquet")
check("delete folder", call("/material/library/folder", {"action": "delete", "path": "Test cartelle"}))
lib = call("/materials")
check("contents moved up", lib, next(m for m in lib["materials"] if m["id"] == oak)["folder"] == "Legni/Parquet"
      and next(m for m in lib["materials"] if m["id"] == "cromo")["folder"] == "Metallo")
call("/material/library/move", {"id": "cromo", "folder": "Metalli"})
for f in ("Legni", "Metallo"):
    call("/material/library/folder", {"action": "delete", "path": f})
check("delete oak", call("/material/library/delete", {"id": oak}))
check("reset built-in", call("/material/library/reset", {"id": "argento"}))
check("delete user material", call("/material/library/delete", {"id": new_id}))
lib = call("/materials")["materials"]
check("library back", {"ok": True}, not next(m for m in lib if m["id"] == "argento")["user"] and not any(m["id"] == new_id for m in lib))
call("/settings", {"live": False})
print("RESULT", "ALL PASS" if FAILS == 0 else f"{FAILS} FAILED")
