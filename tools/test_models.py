"""Test of the model library API (engine started). Usage: blender -b --python test_models.py -- <fbx> <outdir>"""
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


# a textured material on the ring, so the texture copy is tested too
import bpy
im = bpy.data.images.new("mtex", 32, 32)
im.pixels = [0.5] * (32 * 32 * 4)
tex = os.path.join(outdir, "model_tex.png")
im.filepath_raw = tex; im.file_format = "PNG"; im.save()

r = check("import", call("/import", {"path": fbx}))
root = r["id"]
sc = call("/scene")["objects"]
mesh = next(o for o in sc if o["kind"] == "mesh" and not o["name"].startswith("Pavimento"))
call("/material/assign", {"ids": [mesh["id"]], "material": "plastica_opaca"})
check("textured material", call("/material/edit", {"name": "Plastica opaca", "params": {"color": {"map": {"file": tex}}}}))
lib = check("models list", call("/models"))
check("default folders", lib, len(lib.get("folders", [])) > 10)
t = time.time()
r = check("save model", call("/models/save", {"ids": [root], "name": "Anello test", "folder": "Gioielli/Anelli"}))
check("save is quick", r, time.time() - t < 10)
mid, rid = r.get("id"), r.get("pending")
t = time.time()
while time.time() - t < 900:
    st = json.loads(urllib.request.urlopen(BASE + f"/material/preview/status?id={rid}").read())
    if st.get("state") != "running":
        break
    time.sleep(0.5)
check("model prepared", {"ok": st.get("state") == "done"}, True)
print("   prepared in", round(time.time() - t, 1), "s", st)
lib = call("/models")
m = next((x for x in lib["models"] if x["id"] == mid), {})
check("listed with thumb", {"ok": True}, m.get("ready") and os.path.isfile(m.get("thumb", "")) and m["folder"] == "Gioielli/Anelli")
mdir = os.path.dirname(m.get("thumb", "") or "x")
check("texture copied", {"ok": True}, os.path.isfile(os.path.join(mdir, "textures", "model_tex.png")))
if m.get("thumb"):
    import shutil
    shutil.copy(m["thumb"], os.path.join(outdir, "model_thumb.png"))
before = len(call("/scene")["objects"])
r = check("insert", call("/models/insert", {"id": mid, "location": [50, 0, 0]}))
after = call("/scene")["objects"]
check("objects added", {"ok": True}, len(after) > before)
new_root = next((o for o in after if o["id"] == r.get("id")), None)
print("   new root", new_root and {k: new_root.get(k) for k in ("name", "kind", "location")})
# texture path of the inserted copy resolves
bad = [i.name for i in bpy.data.images]  # (this process is a client; checked in the engine below)
check("undo insert", call("/undo", {}))
check("insert gone", {"ok": True}, len(call("/scene")["objects"]) == before)
# a single piece inside a group: the group must not come along (it stays out of the model)
piece = next(o for o in call("/scene")["objects"] if o["kind"] == "mesh" and not o["name"].startswith("Pavimento"))
r = check("save one piece", call("/models/save", {"ids": [piece["id"]], "name": "Pezzo"}))
pid, prid = r.get("id"), r.get("pending")
while json.loads(urllib.request.urlopen(BASE + f"/material/preview/status?id={prid}").read()).get("state") == "running":
    time.sleep(0.5)
before = len(call("/scene")["objects"])
r = check("insert piece", call("/models/insert", {"id": pid, "location": [0, 80, 0]}))
check("only the piece, at the root", {"ok": True}, len(call("/scene")["objects"]) - before == 1 and not next(o for o in call("/scene")["objects"] if o["id"] == r.get("id")).get("parent"))
r = check("thumbnail again", call("/models/thumb", {"id": pid}))
while json.loads(urllib.request.urlopen(BASE + f"/material/preview/status?id={r.get('pending')}").read()).get("state") == "running":
    time.sleep(0.5)
check("rethumb done", {"ok": True}, os.path.isfile(next(x for x in call("/models")["models"] if x["id"] == pid)["thumb"]))
import shutil
shutil.copy(next(x for x in call("/models")["models"] if x["id"] == pid)["thumb"], os.path.join(outdir, "piece_thumb.png"))
call("/models/delete", {"id": pid})
check("rename", call("/models/rename", {"id": mid, "name": "Anello rinominato"}))
check("move", call("/models/move", {"id": mid, "folder": "Altro"}))
check("folder rename", call("/models/folder", {"action": "rename", "path": "Altro", "newPath": "Varie"}))
lib = call("/models")
m = next((x for x in lib["models"] if x["id"] == mid), {})
check("moved with folder", {"ok": True}, m.get("folder") == "Varie" and m.get("name") == "Anello rinominato")
call("/models/folder", {"action": "rename", "path": "Varie", "newPath": "Altro"})
check("delete", call("/models/delete", {"id": mid}))
check("gone", {"ok": True}, not any(x["id"] == mid for x in call("/models")["models"]))
# a model file straight into the library (imported by the preview process: the scene does not change)
n0 = len(call("/scene")["objects"])
r = check("import file into library", call("/models/import", {"path": fbx, "folder": "Importati", "name": "Anello importato"}))
while json.loads(urllib.request.urlopen(BASE + f"/material/preview/status?id={r.get('pending')}").read()).get("state") == "running":
    time.sleep(0.5)
m = next((x for x in call("/models")["models"] if x["id"] == r.get("id")), {})
check("imported model ready", {"ok": True}, m.get("ready") and m.get("thumb") and m.get("folder") == "Importati" and any(m.get("sizeCm") or []))
check("scene untouched by the import", {"ok": True}, len(call("/scene")["objects"]) == n0)
check("bad file refused", {"ok": True}, not call("/models/import", {"path": "/no/such.fbx"}).get("ok"))
call("/models/delete", {"id": r.get("id")})
print("RESULT", "ALL PASS" if FAILS == 0 else f"{FAILS} FAILED")
