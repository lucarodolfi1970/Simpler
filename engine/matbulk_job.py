"""Bulk material fixes for the models of the personal library (the "Correggi materiali" wizard), in its own Blender.

Started by the engine (simpler/matbulk.py) as:
    blender.exe --factory-startup -b --python matbulk_job.py -- <request.json> <result.json>
request: {"mode": "scan", "models": [{"id", "name", "blend"}]}
         {"mode": "apply", "models": [{"id", "name", "blend", "materials": [names]}], "ops": [...], "backup": dir|""}
Prints "SIMPLER_BULK <done> <total> <name>" for the progress; the result is written to <result.json>.

The models are read from their model.blend in an empty session (the scene the user works on is not touched), the
materials are read and rebuilt with the editor's code (simpler.matedit: the same channels as the material editor) and
the model is written back with relative texture paths, as when it was saved to the library.
"""
import json
import os
import shutil
import sys
import traceback

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import bpy  # noqa: E402

argv = sys.argv[sys.argv.index("--") + 1:]
with open(argv[0], encoding="utf-8") as f:
    REQ = json.load(f)
OUT = argv[1]

from simpler import matedit  # noqa: E402

GLASS_WORDS = ("glass", "vetro", "glas", "verre", "vidrio", "window", "finestra", "crystal", "cristallo")


def _empty():
    bpy.ops.wm.read_factory_settings(use_empty=True)


def _load(blend):
    with bpy.data.libraries.load(blend, link=False) as (src, dst):
        names = list(src.objects)
        dst.objects = list(src.objects)
        dst.images = list(src.images)
    return [o for o in dst.objects if o is not None], names


def _hex(c):
    c = [max(0.0, min(1.0, float(v))) for v in c[:3]]
    srgb = [(12.92 * v if v <= 0.0031308 else 1.055 * v ** (1 / 2.4) - 0.055) for v in c]
    return "#" + "".join(f"{int(round(v * 255)):02X}" for v in srgb)


def _category(name, p, advanced):
    if advanced:
        return "advanced"
    t = float(p["transmission"]["weight"])
    metal = float(p["metallic"]["value"]) if not p["metallic"]["map"].get("image") else 1.0
    glassy_name = any(w in name.lower() for w in GLASS_WORDS)
    if t > 0.05 and metal > 0.0:
        return "glassmetal"
    if t > 0.05:
        return "glass"
    if glassy_name or (p["opacity"]["map"].get("image") and glassy_name):
        return "fakeglass"
    if metal >= 0.5:
        return "metal"
    if float(p["emission"]["nits"]) > 0:
        return "emissive"
    if not p["roughness"]["map"].get("image") and float(p["roughness"]["value"]) < 0.15:
        return "glossy"
    if p["color"]["map"].get("image"):
        return "textured"
    return "plain"


def _summary(p):
    has = lambda m: bool(m.get("image"))  # noqa: E731
    return {
        "color": _hex(p["color"]["tint"]), "colorMap": has(p["color"]["map"]),
        "roughness": round(float(p["roughness"]["value"]), 3), "roughnessMap": has(p["roughness"]["map"]),
        "metallic": round(float(p["metallic"]["value"]), 3), "metallicMap": has(p["metallic"]["map"]),
        "transmission": round(float(p["transmission"]["weight"]), 3), "ior": round(float(p["transmission"]["ior"]), 3),
        "thin": bool(p["transmission"]["thin"]), "normalMap": has(p["normal"]["map"]) or has(p["normal"]["bumpMap"]),
        "alpha": bool(p["opacity"]["useAlpha"] or has(p["opacity"]["map"])), "emission": float(p["emission"]["nits"]),
        "coat": round(float(p["coat"]["weight"]), 3), "brightness": round(float(p["color"]["brightness"]), 3),
    }


def _materials(objs):
    seen, out = set(), []
    for o in objs:
        for sl in o.material_slots:
            m = sl.material
            if m is not None and m not in seen and not m.get(matedit.BACKUP_TAG):
                seen.add(m)
                out.append(m)
    return out


def scan():
    models = REQ["models"]
    res = []
    for i, e in enumerate(models):
        print(f"SIMPLER_BULK {i} {len(models)} {e.get('name', '')}", flush=True)
        item = {"id": e["id"], "name": e.get("name", ""), "folder": e.get("folder", ""), "materials": [], "error": ""}
        try:
            _empty()
            objs, _ = _load(e["blend"])
            for m in _materials(objs):
                p, adv = matedit.read_material(m)
                item["materials"].append({"name": m.name, "category": _category(m.name, p, adv), "advanced": adv,
                                          "simpler": bool(m.get(matedit.PARAMS_KEY)), "values": _summary(p),
                                          "users": sum(1 for o in objs if any(s.material == m for s in o.material_slots))})
        except Exception as exc:
            item["error"] = str(exc)[:300]
            traceback.print_exc()
        res.append(item)
    print(f"SIMPLER_BULK {len(models)} {len(models)} ", flush=True)
    return {"models": res}


# ---------------------------------------------------------------- changes

def _num(p, path):
    d = p
    for k in path[:-1]:
        d = d[k]
    return d, path[-1]


# parameter -> (path in the editor's channels, min, max)
PARAMS = {
    "roughness": (("roughness", "value"), 0.0, 1.0),
    "metallic": (("metallic", "value"), 0.0, 1.0),
    "specular": (("specular",), 0.0, 1.0),
    "brightness": (("color", "brightness"), 0.0, 4.0),
    "saturation": (("color", "saturation"), 0.0, 4.0),
    "transmission": (("transmission", "weight"), 0.0, 1.0),
    "ior": (("transmission", "ior"), 1.0, 3.0),
    "coat": (("coat", "weight"), 0.0, 1.0),
    "emission": (("emission", "nits"), 0.0, 1e6),
}
MAPS = {"colorMap": ("color", "map"), "roughnessMap": ("roughness", "map"), "metallicMap": ("metallic", "map"),
        "normalMap": ("normal", "map"), "bumpMap": ("normal", "bumpMap"), "opacityMap": ("opacity", "map")}


def _apply_ops(p, ops):
    """Returns (changed, skipped: reasons)."""
    changed, skipped = False, []
    for op in ops:
        prm, mode = op.get("param", ""), op.get("mode", "set")
        if prm in PARAMS:
            path, lo, hi = PARAMS[prm]
            d, k = _num(p, path)
            v = float(op.get("value", 0))
            mapkey = {"roughness": "roughness", "metallic": "metallic"}.get(prm)
            if mapkey and p[mapkey]["map"].get("image"):
                if mode != "set":
                    skipped.append(prm + ":map")       # the value comes from a texture: only "set" replaces it
                    continue
                p[mapkey]["map"] = matedit._map()      # set: a plain value instead of the texture
            old = float(d[k])
            new = v if mode == "set" else old * v if mode == "mul" else old + v
            new = max(lo, min(hi, new))
            if abs(new - old) > 1e-9:
                d[k] = new
                changed = True
            if mapkey:
                changed = True if mode == "set" else changed
        elif prm == "tint" and mode == "set":
            c = str(op.get("value", "#FFFFFF")).lstrip("#")
            try:
                rgb = [int(c[i:i + 2], 16) / 255.0 for i in (0, 2, 4)]
            except ValueError:
                continue
            lin = [(v / 12.92 if v <= 0.04045 else ((v + 0.055) / 1.055) ** 2.4) for v in rgb]
            p["color"]["tint"] = lin
            changed = True
        elif prm == "thin" and mode == "set":
            p["transmission"]["thin"] = bool(op.get("value"))
            changed = True
        elif prm == "alpha" and mode == "set" and not op.get("value"):
            if p["opacity"]["useAlpha"] or p["opacity"]["map"].get("image"):
                p["opacity"]["useAlpha"] = False
                p["opacity"]["map"] = matedit._map()
                changed = True
        elif prm in MAPS and mode == "remove":
            a, b = MAPS[prm]
            if p[a][b].get("image"):
                p[a][b] = matedit._map()
                if prm == "colorMap":
                    p["color"]["tint"] = p["color"]["tint"]
                changed = True
    # a glass cannot be a metal (the metal wins in the Principled BSDF): as in the editor
    if float(p["transmission"]["weight"]) > 0 and (float(p["metallic"]["value"]) > 0 or p["metallic"]["map"].get("image")):
        p["metallic"]["value"] = 0.0
        p["metallic"]["map"] = matedit._map()
        changed = True
    return changed, skipped


def apply():
    models, ops, backup = REQ["models"], REQ.get("ops") or [], REQ.get("backup") or ""
    res = []
    for i, e in enumerate(models):
        print(f"SIMPLER_BULK {i} {len(models)} {e.get('name', '')}", flush=True)
        item = {"id": e["id"], "changed": 0, "skipped": [], "error": ""}
        try:
            if backup:
                bdir = os.path.join(backup, e["id"])
                os.makedirs(bdir, exist_ok=True)
                shutil.copy2(e["blend"], os.path.join(bdir, "model.blend"))
            _empty()
            objs, _ = _load(e["blend"])
            want = set(e.get("materials") or [])
            for m in _materials(objs):
                if m.name not in want:
                    continue
                p, adv = matedit.read_material(m)
                if adv:
                    item["skipped"].append(m.name + ":advanced")
                    continue
                p = matedit._merge(matedit.DEFAULTS, p)
                changed, sk = _apply_ops(p, ops)
                item["skipped"] += [f"{m.name}:{s}" for s in sk]
                if not changed:
                    continue
                p["version"] = matedit.VERSION
                if m.node_tree is None:
                    m.use_nodes = True
                matedit._Builder(m, p).build()
                m[matedit.PARAMS_KEY] = json.dumps(p)
                item["changed"] += 1
            if item["changed"]:
                tmp = e["blend"] + ".part"
                bpy.data.libraries.write(tmp, set(objs), fake_user=True, path_remap="RELATIVE", compress=True)
                os.replace(tmp, e["blend"])
        except Exception as exc:
            item["error"] = str(exc)[:300]
            traceback.print_exc()
        res.append(item)
    print(f"SIMPLER_BULK {len(models)} {len(models)} ", flush=True)
    return {"models": res}


# ---------------------------------------------------------------- vegetation (1.78.0)
# «Importa vegetazione» / «Converti in vegetazione»: every material of the plant gets the type Fogliame, as leaves or
# as wood. Which is which: the name first (leaf, bark… in several languages), then a cut-out (a leaf card), then the
# colour (green = leaves); otherwise wood (the season leaves wood alone: the safe guess). REQ "parts" {material: part}
# overrides; "dry" only reports.
LEAF_WORDS, WOOD_WORDS = matedit.LEAF_WORDS, matedit.WOOD_WORDS
_part_of = matedit.foliage_part_guess


def vegetation():
    models, parts, dry = REQ["models"], REQ.get("parts") or {}, bool(REQ.get("dry"))
    res = []
    for i, e in enumerate(models):
        print(f"SIMPLER_BULK {i} {len(models)} {e.get('name', '')}", flush=True)
        item = {"id": e["id"], "materials": [], "changed": 0, "error": ""}
        try:
            _empty()
            objs, _ = _load(e["blend"])
            own = parts.get(e["id"]) or {}
            for m in _materials(objs):
                p, adv = matedit.read_material(m)
                part, why = _part_of(m, p)
                if own.get(m.name) in ("foglie", "legno", "altro"):
                    part, why = own[m.name], "user"
                item["materials"].append({"name": m.name, "part": part, "why": why, "advanced": adv})
                if dry or part == "altro":
                    continue
                p = matedit._merge(matedit.DEFAULTS, p)
                f = p["foliage"]
                # (1.78.4) the cut-out map turned the right way by its border (plants converted before too)
                fixed = matedit.fix_transparency_map(p, card=True)
                if f.get("enabled") and f.get("part") == part and not fixed:
                    continue
                f["enabled"], f["part"] = True, part
                p["fabric"]["enabled"] = False
                if part == "foglie":
                    # (the old way of the leaves: Subsurface + Foglio sottile - the light through is the type's now)
                    p["subsurface"]["weight"] = 0.0
                p["version"] = matedit.VERSION
                if m.node_tree is None:
                    m.use_nodes = True
                matedit._Builder(m, p).build()
                m[matedit.PARAMS_KEY] = json.dumps(p)
                item["changed"] += 1
            if item["changed"] and not dry:
                tmp = e["blend"] + ".part"
                bpy.data.libraries.write(tmp, set(objs), fake_user=True, path_remap="RELATIVE", compress=True)
                os.replace(tmp, e["blend"])
        except Exception as exc:
            item["error"] = str(exc)[:300]
            traceback.print_exc()
        res.append(item)
    print(f"SIMPLER_BULK {len(models)} {len(models)} ", flush=True)
    return {"models": res}


try:
    mode = REQ.get("mode")
    result = scan() if mode == "scan" else vegetation() if mode == "veg" else apply()
except Exception as exc:
    traceback.print_exc()
    result = {"error": str(exc)}
with open(OUT + ".part", "w", encoding="utf-8") as f:
    json.dump(result, f)
os.replace(OUT + ".part", OUT)
print("SIMPLER_DONE", flush=True)
