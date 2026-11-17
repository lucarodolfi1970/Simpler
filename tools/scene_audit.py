"""(15/11, Luca: «verifica uno per uno che tutti i comandi siano salvati as is quando si salva una scena»)
Run with the engine started on a new scene:  python tools/scene_audit.py <port> [file to save]
Scene audit: every setting of the Ambiente and of the render changed to a value of its own, a scene saved, everything
changed again, the scene opened: what comes back, key by key. Then the project saved, the engine started again on it."""
import json, sys, time, urllib.request, copy, subprocess, os
PORT = int(sys.argv[1]) if len(sys.argv) > 1 else 8811
def call(method, path, body=None, port=PORT, timeout=300):
    req = urllib.request.Request(f"http://localhost:{port}/api/{path}", data=None if body is None else json.dumps(body).encode(), method=method, headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r: return json.loads(r.read() or b"{}")
    except urllib.error.HTTPError as e:
        return {"__error": e.read().decode()[:300]}
def flat(d, pre=""):
    out = {}
    for k, v in (d or {}).items():
        if isinstance(v, dict): out.update(flat(v, pre + k + "."))
        else: out[pre + k] = v
    return out
def other(v, key=""):
    if isinstance(v, bool): return not v
    if isinstance(v, int): return v + 3
    if isinstance(v, float): return round(v * 0.8 + 0.07, 4) if v != 0 else 0.23
    if isinstance(v, list) and v and all(isinstance(x, (int, float)) for x in v): return [round(min(1.0, x * 0.7 + 0.1), 4) for x in v]
    return v
def same(a, b):
    if isinstance(a, float) or isinstance(b, float):
        try: return abs(float(a) - float(b)) < 1e-6
        except Exception: return a == b
    if isinstance(a, list) and isinstance(b, list): return len(a) == len(b) and all(same(x, y) for x, y in zip(a, b))
    return a == b
report = {}
THUMB = '/9j/4AAQSkZJRgABAQAAAQABAAD/2wBDAAgGBgcGBQgHBwcJCQgKDBQNDAsLDBkSEw8UHRofHh0aHBwgJC4nICIsIxwcKDcpLDAxNDQ0Hyc5PTgyPC4zNDL/2wBDAQkJCQwLDBgNDRgyIRwhMjIyMjIyMjIyMjIyMjIyMjIyMjIyMjIyMjIyMjIyMjIyMjIyMjIyMjIyMjIyMjIyMjL/wAARCADIAUADASIAAhEBAxEB/8QAHwAAAQUBAQEBAQEAAAAAAAAAAAECAwQFBgcICQoL/8QAtRAAAgEDAwIEAwUFBAQAAAF9AQIDAAQRBRIhMUEGE1FhByJxFDKBkaEII0KxwRVS0fAkM2JyggkKFhcYGRolJicoKSo0NTY3ODk6Q0RFRkdISUpTVFVWV1hZWmNkZWZnaGlqc3R1dnd4eXqDhIWGh4iJipKTlJWWl5iZmqKjpKWmp6ipqrKztLW2t7i5usLDxMXGx8jJytLT1NXW19jZ2uHi4+Tl5ufo6erx8vP09fb3+Pn6/8QAHwEAAwEBAQEBAQEBAQAAAAAAAAECAwQFBgcICQoL/8QAtREAAgECBAQDBAcFBAQAAQJ3AAECAxEEBSExBhJBUQdhcRMiMoEIFEKRobHBCSMzUvAVYnLRChYkNOEl8RcYGRomJygpKjU2Nzg5OkNERUZHSElKU1RVVldYWVpjZGVmZ2hpanN0dXZ3eHl6goOEhYaHiImKkpOUlZaXmJmaoqOkpaanqKmqsrO0tba3uLm6wsPExcbHyMnK0tPU1dbX2Nna4uPk5ebn6Onq8vP09fb3+Pn6/9oADAMBAAIRAxEAPwDLooormOMKKKKACiiigAooooAKKKKACiiigAooooAKKKKACiiigAooooAKKKKACiiigAooooAKKKKACiiigAooooAKKKKACiiigAooooAKKKKACiiigAooooAKKKKACiiigAooooAKKKKACiiigAooooAKKKKACiiigAooooAKKKKACiiigAooooAKKKKACiiigAooooAKKKKACiiigAooooAKKKKACiiigAooooAKKKKACiiigAooooAKKKKACiiigAooooAKKKKACiiigAooooAKKKKACiiigAooooAKKKKACiiigAooooAKKKKACiiigAooooAKKKKACiiigAooooAKKKKACiiigAooooAKKKKACiiigAooooAKKKKACiiigAooooAKKKKACiiigAooooAKKKKACiiigAooooAKKKKACiiigAooooAKKKKACiiigAooooAKKKKACiiigAooooAKKKKACiiigAooooAKKKKACiiigAooooAKKKKACiiigAooooAKKKKACiiigAooooAKKKKACiiigAooooAKKKKACiiigAooooAKKKKACiiigAooooAKKKKACiiigAooooAKKKKACiiigAooooAKKKKACiiigAooooAKKKKACiiigAooooAKKKKACiiigAooooAKKKKACiiigAooooAKKKKACiiigAooooAKKKKACiiigAooooAKKKKACiiigAooooAKKKKACiiigAooooAKKKKACiiigAooooAKKKKACiiigAooooAKKKKACiiigAooooAKKKKACiiigAooooAKKKKACiiigAooooAKKKKACiiigAooooAKKKKACiiigAooooAKKKKACiiigAooooAKKKKACiiigAooooAKKKKACiiigAooooAKKKKACiiigAooooAKKKKACiiigAooooAKKKKACiiigAooooAKKKKACiiigAooooAKKKKACiiigAooooAKKKKACiiigAooooAKKKKACiiigAooooAKKKKACiiigAooooAKKKKACiiigAooooAKKKKACiiigAooooAKKKKACiiigAooooAKKKKACiiigAooooAKKKKACiiigAooooAKKKKACiiigAooooAKKKKACiiigAooooAKKKKACiiigAooooAKKKKACiiigAooooAKKKKACiiigAooooAKKKKACiiigAooooAKKKKACiiigAooooAKKKKACiiigAooooAKKKKACiiigAooooAKKKKACiiigAooooAKKKKACiiigAooooAKKKKACiiigAooooAKKKKACiiigAooooAKKKKACiiigAooooAKKKKACiiigAooooAKKKKACiiigAooooAKKKKACiiigAooooAKKKKAP//Z'
# ---- 1. the Ambiente: every value changed, group by group (as the panel does: one partial change per group)
st0 = call("GET", "ambience")["state"]
SKIP_GROUPS = {"hdri", "exposure", "ground"}          # (looked at apart: a photo sky, the meter, the ground type)
for g, vals in st0.items():
    if not isinstance(vals, dict) or g in SKIP_GROUPS: continue
    part = {k: other(v) for k, v in vals.items() if not isinstance(v, str)}
    if g == "clouds": part["volumetric"] = True; part.pop("type", None)
    if g == "fog": part["volumetric"] = False; part["low"] = True; part["tint"] = True
    r = call("POST", "ambience", {g: part})
    if "__error" in r: print("ambience", g, r["__error"])
A = flat(call("GET", "ambience")["state"])
# ---- 2. the render settings
s0 = call("GET", "settings")
cfg0 = s0.get("config", s0)
ch = {}
for k, v in cfg0.items():
    if isinstance(v, (bool, int, float)) and k not in ("textureLimit", "realtimeTextures", "samples", "previewSamples"): ch[k] = other(v)
r = call("POST", "settings", {"config": ch})
if "__error" in r: print("settings", r["__error"])
B = flat(call("GET", "settings"))
# ---- 3. the scene saved
vid = call("POST", "views/save", {"name": "audit", "thumb": THUMB})["view"]["id"]
# ---- 4. everything changed AGAIN, value by value (and another preset first), the render settings too
call("POST", "ambience", {"preset": "notte"})
stA = call("GET", "ambience")["state"]
for g, vals in st0.items():
    if not isinstance(vals, dict) or g in SKIP_GROUPS: continue
    part = {k: other(other(v)) for k, v in vals.items() if not isinstance(v, str)}
    if g == "clouds": part["volumetric"] = False; part.pop("type", None)
    if g == "fog": part["volumetric"] = False; part["low"] = False; part["tint"] = False
    call("POST", "ambience", {g: part})
call("POST", "settings", {"config": {k: other(other(v)) for k, v in cfg0.items() if k in ch}})
mid = flat(call("GET", "ambience")["state"]); MIDS = flat(call("GET", "settings"))
# ---- 5. the scene opened
r = call("POST", "views/apply", {"id": vid})
if "__error" in r: print("apply", r["__error"])
A2 = flat(call("GET", "ambience")["state"]); B2 = flat(call("GET", "settings"))
def diff(name, want, got, changed_ref):
    bad = [(k, want[k], got.get(k)) for k in want if not same(want[k], got.get(k))]
    moved = sum(1 for k in want if not same(want[k], changed_ref.get(k)))
    print(f"{name}: {len(want)} values looked at, {moved} of them had been changed in between, {len(bad)} NOT back as saved")
    for k, w, g in bad: print(f"   LOST  {k}: saved {w!r}, came back {g!r}")
    return bad
print("== scene saved and opened again in the same session")
b1 = diff("Ambiente", A, A2, mid)
b2 = diff("Render settings", B, B2, MIDS)
# ---- 6. the project saved with the scene, and with a state DIFFERENT from the scene (as Luca: changes after the scene)
call("POST", "ambience", {"fog": {"height": 77.0}, "clouds": {"puff": 0.33}})
P = flat(call("GET", "ambience")["state"]); PS = flat(call("GET", "settings"))
path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "_scene_audit.simpler") if len(sys.argv) < 3 else sys.argv[2]
r = call("POST", "save", {"path": path})
if "__error" in r: print("save", r["__error"])
json.dump({"A": A, "B": B, "P": P, "PS": PS, "vid": vid, "path": path}, open(path + ".state.json", "w"))
print("saved", os.path.exists(path))
