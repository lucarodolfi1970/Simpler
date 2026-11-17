"""End-to-end test of the Simpler engine API. Usage: python test_engine.py <fbx> <outdir>"""
import json
import os
import sys
import time
import urllib.request

BASE = "http://127.0.0.1:8787/api"
_args = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else sys.argv[1:]
fbx, outdir = _args[0], _args[1]
os.makedirs(outdir, exist_ok=True)


def call(path, body=None):
    req = urllib.request.Request(BASE + path, data=None if body is None else json.dumps(body).encode(),
                                 headers={"Content-Type": "application/json"}, method="GET" if body is None else "POST")
    try:
        with urllib.request.urlopen(req, timeout=3600) as r:
            return json.loads(r.read())
    except urllib.error.HTTPError as e:
        return json.loads(e.read())


def check(label, res, cond=True):
    ok = res.get("ok") and cond
    print(("PASS " if ok else "FAIL ") + label, "" if ok else json.dumps(res)[:300])
    if not ok:
        globals()["FAILS"] = globals().get("FAILS", 0) + 1
    return res


def wait_frames(final_pass, timeout=900):
    t = time.time()
    while time.time() - t < timeout:
        info = json.loads(urllib.request.urlopen(BASE + "/frame/info").read())
        if info.get("pass", -1) >= final_pass:
            return info
        time.sleep(0.5)
    return info


def save_frame(name):
    with urllib.request.urlopen(BASE + "/frame") as r:
        open(os.path.join(outdir, name), "wb").write(r.read())


for _ in range(120):
    try:
        ping = call("/ping"); break
    except Exception:
        time.sleep(1)
check("ping " + json.dumps({k: ping.get(k) for k in ("version", "blender", "device")}), ping)

check("settings viewport small", call("/settings", {"viewport": [640, 400], "quality": "bozza", "live": True}))
scene0 = check("scene (studio)", call("/scene"))
names0 = [o["name"] for o in scene0["objects"]]
print("   studio objects:", names0)

imp = check("import FBX", call("/import", {"path": fbx}))
print("   import:", {k: imp.get(k) for k in ("nodes", "meshes", "uniqueMeshes", "materials", "warnings")})
scene = call("/scene")["objects"]
by_name = {o["name"]: o for o in scene}
def children(pid): return [o["name"] for o in scene if o["parent"] == pid]
root = next(o for o in scene if o["kind"] == "file")
anello = by_name["Anello"]
check("hierarchy: file > Anello", {"ok": True}, children(root["id"]) == ["Anello"])
check("hierarchy: Anello > Montatura, Pietre", {"ok": True}, sorted(children(anello["id"])) == ["Montatura", "Pietre"])
castone = by_name["Castone"]
check("hierarchy: Castone > 4 griffe", {"ok": True}, sorted(children(castone["id"])) == [f"Griffa_0{i}" for i in range(1, 5)])

# Transform: the ring is ~2 cm; lift it 1 cm and rotate 30 deg
check("transform", call("/transform", {"id": root["id"], "location": [0, 0, 0.5], "rotation": [0, 0, 30]}))
obj = call(f"/object?id={root['id']}")
check("transform readback", obj, obj["location"] == [0, 0, 0.5] and abs(obj["rotation"][2] - 30) < 1e-3)

dup = check("duplicate (with children)", call("/duplicate", {"id": anello["id"]}))
check("move duplicate", call("/transform", {"id": dup["id"], "location": [3, 1.5, 0]}))
n_after = len(call("/scene")["objects"])
check(f"duplicate created subtree ({n_after - len(scene)} new)", {"ok": True}, n_after - len(scene) == 10)

check("material oro_giallo on duplicate", call("/material/assign", {"id": dup["id"], "material": "oro_rosa"}))
gem = by_name["Diamante_Centrale"]
check("material diamante on gem", call("/material/assign", {"id": gem["id"], "material": "diamante"}))
sl = check("add spot light", call("/add", {"kind": "spot", "name": "Spot gemma"}))
check("light props", call("/light", {"id": sl["id"], "power": 80, "radius": 0.5, "coneAngle": 30, "aimAt": gem["id"]}))
check("reparent spot under Anello", call("/parent", {"id": sl["id"], "parent": anello["id"]}))
check("cycle protection", call("/parent", {"id": anello["id"], "parent": castone["id"]}), True) if False else None
bad = call("/parent", {"id": anello["id"], "parent": castone["id"]})
check("cycle protection refuses", {"ok": True}, bad.get("ok") is False)
check("rename", call("/rename", {"id": sl["id"], "name": "Luce diamante"}))
t0 = time.time()
check("environment", call("/environment", {"id": "studio_contrasto"}))
print(f"   command latency while rendering: {time.time()-t0:.1f}s")
check("caustics on", call("/settings", {"caustics": True}))
check("camera frame", call("/camera", {"action": "frame", "ids": [root["id"], dup["id"]]}))
check("camera orbit", call("/camera", {"action": "orbit", "dx": 20, "dy": 10}))

info = wait_frames(3)
print("   viewport:", info)
save_frame("viewport.jpg")
pk = call("/pick", {"u": 0.5, "v": 0.5})
print("   pick center:", pk.get("id"), "path len", len(pk.get("path", [])))

r = check("final render", call("/render", {"path": os.path.join(outdir, "finale.png"), "width": 960, "height": 600, "quality": "bozza", "samples": 96}))
print("   render:", {k: r.get(k) for k in ("seconds", "samples")})
s = check("save project", call("/save", {"path": os.path.join(outdir, "test")}))
check("delete duplicate subtree", call("/delete", {"id": dup["id"]}))
# undo / redo (Wave 1)
n_before = len(call("/scene")["objects"])
t0 = time.time()
u = check("undo delete", call("/undo", {}), True)
print(f"   undo of a delete: {time.time()-t0:.2f}s, structural={u.get('structural')}")
check("undo restores objects", {"ok": True}, len(call("/scene")["objects"]) > n_before)
check("redo delete", call("/redo", {}))
check("redo removes them again", {"ok": True}, len(call("/scene")["objects"]) == n_before)
mw = call("/object?id=" + anello["id"])["matrixWorld"]
moved = list(mw); moved[12] += 0.03
check("matrices (multi-selection)", call("/matrices", {"items": [{"id": anello["id"], "matrix": moved}]}))
check("undo transform", call("/undo", {}))
check("transform restored", {"ok": True}, abs(call("/object?id=" + anello["id"])["matrixWorld"][12] - mw[12]) < 1e-5)
check("light type + kelvin", call("/light", {"id": sl["id"], "type": "point", "kelvin": 2700, "shadow": False}))
check("undo light", call("/undo", {}))
check("light restored", {"ok": True}, call("/object?id=" + sl["id"])["kind"] == "spot")
# 1.1.0: camera, scenes, material previews
check("camera dof + format", call("/camera", {"action": "settings", "dof": True, "fstop": 2.8, "focus": 20, "format": "4:5"}))
t0 = time.time()
v = check("save scene", call("/views/save", {"name": "Test"}))
print(f"   scene thumbnail: {time.time()-t0:.1f}s")
check("apply scene", call("/views/apply", {"id": v.get("view", {}).get("id", "")}))
check("two-point perspective", call("/camera", {"action": "twoPoint"}))
t0 = time.time()
check("material preview", call("/materials/preview", {"id": "oro_rosa", "folder": os.path.join(outdir, "previews"), "wait": True}))
print(f"   material preview: {time.time()-t0:.1f}s")
print("RESULT", "ALL PASS" if not globals().get("FAILS") else f"{FAILS} FAIL")
call("/shutdown", {})
