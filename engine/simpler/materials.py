"""Curated material library: a handful of presets with simple, meaningful controls."""
import bpy

from .core import ApiError, find, tree_kids
from .i18n import tr

# id -> (display name, category, swatch sRGB hex for the UI, Principled BSDF inputs)
PRESETS = {
    "oro_giallo":   ("Oro giallo 18k", "Metalli", "#E8B64A", {"Base Color": (1.0, 0.766, 0.336), "Metallic": 1.0, "Roughness": 0.12}),
    "oro_rosa":     ("Oro rosa", "Metalli", "#D99577", {"Base Color": (0.955, 0.637, 0.538), "Metallic": 1.0, "Roughness": 0.12}),
    "oro_bianco":   ("Oro bianco", "Metalli", "#C9CED6", {"Base Color": (0.86, 0.85, 0.80), "Metallic": 1.0, "Roughness": 0.08}),
    "platino":      ("Platino", "Metalli", "#AEB5BF", {"Base Color": (0.672, 0.637, 0.585), "Metallic": 1.0, "Roughness": 0.10}),
    "argento":      ("Argento", "Metalli", "#E6E8EA", {"Base Color": (0.972, 0.960, 0.915), "Metallic": 1.0, "Roughness": 0.10}),
    "cromo":        ("Cromo", "Metalli", "#DADDE0", {"Base Color": (0.90, 0.90, 0.90), "Metallic": 1.0, "Roughness": 0.03}),
    "acciaio_satinato": ("Acciaio satinato", "Metalli", "#9AA1A8", {"Base Color": (0.56, 0.57, 0.58), "Metallic": 1.0, "Roughness": 0.35, "Anisotropic": 0.6}),
    "diamante":     ("Diamante", "Gemme", "#DDEBFF", {"Base Color": (1.0, 1.0, 1.0), "Transmission Weight": 1.0, "IOR": 2.417, "Roughness": 0.0}),
    "zaffiro":      ("Zaffiro", "Gemme", "#2E5BD8", {"Base Color": (0.08, 0.22, 0.85), "Transmission Weight": 1.0, "IOR": 1.77, "Roughness": 0.0}),
    "rubino":       ("Rubino", "Gemme", "#C8283F", {"Base Color": (0.85, 0.04, 0.10), "Transmission Weight": 1.0, "IOR": 1.77, "Roughness": 0.0}),
    "smeraldo":     ("Smeraldo", "Gemme", "#1E9E62", {"Base Color": (0.05, 0.62, 0.30), "Transmission Weight": 1.0, "IOR": 1.58, "Roughness": 0.0}),
    "vetro":        ("Vetro", "Vetri", "#B7D3E6", {"Base Color": (1.0, 1.0, 1.0), "Transmission Weight": 1.0, "IOR": 1.5, "Roughness": 0.0}),
    "vetro_satinato": ("Vetro satinato", "Vetri", "#D6E2EA", {"Base Color": (1.0, 1.0, 1.0), "Transmission Weight": 1.0, "IOR": 1.5, "Roughness": 0.25}),
    "acqua":        ("Acqua", "Vetri", "#9CC8E0", {"Base Color": (0.92, 0.97, 1.0), "Transmission Weight": 1.0, "IOR": 1.333, "Roughness": 0.0}),
    "ceramica":     ("Ceramica bianca", "Superfici", "#F4F2EE", {"Base Color": (0.90, 0.89, 0.86), "Roughness": 0.35, "Coat Weight": 1.0, "Coat Roughness": 0.03}),
    "plastica_lucida": ("Plastica lucida", "Superfici", "#2B2F36", {"Base Color": (0.03, 0.035, 0.04), "Roughness": 0.15, "Coat Weight": 0.6}),
    "bianco":       ("Bianco", "Superfici", "#E6E6E3", {"Base Color": (0.80, 0.80, 0.79), "Roughness": 0.5}),
    "plastica_opaca":  ("Plastica opaca", "Superfici", "#7C8188", {"Base Color": (0.20, 0.21, 0.22), "Roughness": 0.65}),
    "marmo_bianco": ("Marmo bianco", "Superfici", "#E3E1DC", {"Base Color": (0.86, 0.85, 0.82), "Roughness": 0.18, "Subsurface Weight": 0.15}),
    "velluto_blu":  ("Velluto blu notte", "Tessuti", "#241A45", {"Base Color": (0.02, 0.03, 0.10), "Roughness": 0.9, "Sheen Weight": 1.0, "Sheen Roughness": 0.4}),
    "velluto_nero": ("Velluto nero", "Tessuti", "#141414", {"Base Color": (0.01, 0.01, 0.01), "Roughness": 0.9, "Sheen Weight": 1.0, "Sheen Roughness": 0.35}),
    "pavimento_studio": ("Fondale studio", "Superfici", "#C8C5BF", {"Base Color": (0.62, 0.61, 0.58), "Roughness": 0.55}),
    # (1.79) paints, more metals, plastics and rubber, glass, surfaces and lights: values only, no pictures
    "pittura_opaca": ("Pittura murale opaca", "Pitture", "#E2DED6", {"Base Color": (0.75, 0.73, 0.68), "Roughness": 0.85, "Specular IOR Level": 0.3}),
    "vernice_satinata": ("Vernice satinata", "Pitture", "#8FA393", {"Base Color": (0.26, 0.36, 0.28), "Roughness": 0.4}),
    "smalto_lucido": ("Smalto lucido", "Pitture", "#1E3A6E", {"Base Color": (0.015, 0.045, 0.16), "Roughness": 0.2, "Coat Weight": 1.0, "Coat Roughness": 0.02}),
    "vernice_metallizzata": ("Vernice metallizzata auto", "Pitture", "#8E1A22", {"Base Color": (0.30, 0.012, 0.02), "Metallic": 0.6, "Roughness": 0.3, "Coat Weight": 1.0, "Coat Roughness": 0.01}),
    "alluminio_spazzolato": ("Alluminio spazzolato", "Metalli", "#C9CCCF", {"Base Color": (0.91, 0.92, 0.92), "Metallic": 1.0, "Roughness": 0.3, "Anisotropic": 0.7}),
    "rame": ("Rame", "Metalli", "#C97B57", {"Base Color": (0.955, 0.638, 0.538), "Metallic": 1.0, "Roughness": 0.18}),
    "ottone": ("Ottone", "Metalli", "#D2B263", {"Base Color": (0.91, 0.78, 0.42), "Metallic": 1.0, "Roughness": 0.2}),
    "ferro_grezzo": ("Ferro grezzo", "Metalli", "#6E6A66", {"Base Color": (0.53, 0.51, 0.49), "Metallic": 1.0, "Roughness": 0.55}),
    "acciaio_nero": ("Acciaio verniciato nero", "Metalli", "#232323", {"Base Color": (0.018, 0.018, 0.018), "Roughness": 0.45, "Coat Weight": 0.3, "Coat Roughness": 0.3}),
    "plastica_colorata": ("Plastica colorata lucida", "Plastiche e gomme", "#E2552A", {"Base Color": (0.75, 0.10, 0.02), "Roughness": 0.2, "Coat Weight": 0.5}),
    "gomma_nera": ("Gomma nera", "Plastiche e gomme", "#1C1C1C", {"Base Color": (0.015, 0.015, 0.015), "Roughness": 0.9, "Specular IOR Level": 0.3}),
    "silicone": ("Silicone", "Plastiche e gomme", "#E8E6E0", {"Base Color": (0.80, 0.79, 0.75), "Roughness": 0.4, "Subsurface Weight": 0.4}),
    "vetro_fume": ("Vetro fumé", "Vetri", "#5D5A55", {"Base Color": (0.30, 0.28, 0.26), "Transmission Weight": 1.0, "IOR": 1.5, "Roughness": 0.0}),
    "vetro_acidato": ("Vetro acidato", "Vetri", "#DCE8E4", {"Base Color": (0.92, 0.97, 0.95), "Transmission Weight": 1.0, "IOR": 1.5, "Roughness": 0.45}),
    "cemento_liscio": ("Cemento liscio", "Superfici", "#7A7873", {"Base Color": (0.18, 0.175, 0.165), "Roughness": 0.8}),
    "intonaco": ("Intonaco", "Superfici", "#D8D2C6", {"Base Color": (0.68, 0.64, 0.56), "Roughness": 0.95, "Specular IOR Level": 0.4}),
    "pelle": ("Pelle marrone", "Superfici", "#5A3420", {"Base Color": (0.10, 0.035, 0.015), "Roughness": 0.5, "Sheen Weight": 0.2, "Coat Weight": 0.3, "Coat Roughness": 0.3}),
    "carta": ("Carta bianca", "Superfici", "#EEECE6", {"Base Color": (0.84, 0.83, 0.79), "Roughness": 0.9, "Subsurface Weight": 0.15}),
    "schermo_acceso": ("Schermo acceso", "Luci", "#DCE6FF", {"Base Color": (0.0, 0.0, 0.0), "Roughness": 0.05, "Emission Color": (0.85, 0.90, 1.0), "Emission Strength": 0.37}),
    "striscia_led": ("Striscia LED", "Luci", "#FFD9A8", {"Base Color": (0.8, 0.8, 0.8), "Roughness": 0.4, "Emission Color": (1.0, 0.78, 0.55), "Emission Strength": 2.2}),
    "pannello_luminoso": ("Pannello luminoso", "Luci", "#F6F8FF", {"Base Color": (0.9, 0.9, 0.9), "Roughness": 0.5, "Emission Color": (1.0, 1.0, 1.0), "Emission Strength": 4.4}),
    # volumetric (volumetric.py): the model is filled; the values here are only the colour of the swatch
    "vol_nuvola":   ("Nuvola", "Volumi", "#E8EEF6", {"Base Color": (0.95, 0.96, 0.98)}),
    "vol_fumo":     ("Fumo", "Volumi", "#7C7F84", {"Base Color": (0.45, 0.46, 0.48)}),
    "vol_nebbia":   ("Banco di nebbia", "Volumi", "#D5DBE3", {"Base Color": (0.85, 0.87, 0.90)}),
    "vol_vapore":   ("Vapore", "Volumi", "#F2F4F7", {"Base Color": (0.97, 0.97, 0.98)}),
    "vol_polvere":  ("Polvere", "Volumi", "#C8B08A", {"Base Color": (0.75, 0.65, 0.50)}),
    "vol_fuoco":    ("Fuoco", "Volumi", "#F07A28", {"Base Color": (1.0, 0.45, 0.12)}),
}

PRESET_KEY = "simpler_preset"


# (1.79) materials of Simpler added after the first ones: an install that already had its library gets each of them
# once (written in "presetsKnown"); one the user deletes stays deleted
ADDED_PRESETS = ("pittura_opaca", "vernice_satinata", "smalto_lucido", "vernice_metallizzata", "alluminio_spazzolato",
                 "rame", "ottone", "ferro_grezzo", "acciaio_nero", "plastica_colorata", "gomma_nera", "silicone",
                 "vetro_fume", "vetro_acidato", "cemento_liscio", "intonaco", "pelle", "carta", "schermo_acceso",
                 "striscia_led", "pannello_luminoso")
KNOWN_KEY = "presetsKnown"


VOLUME_PRESETS = {"vol_nuvola": "nuvola", "vol_fumo": "fumo", "vol_nebbia": "nebbia", "vol_vapore": "vapore",
                  "vol_polvere": "polvere", "vol_fuoco": "fuoco"}
DRAFT_KEY = "simpler_lib_draft"     # on a library material edited while on no object of the scene (a draft)
LIB_REV_KEY = "simpler_lib_rev"     # on a material made from the library: the revision it was built from
_user_cache = {"stamp": None, "entries": {}}


def user_dir():
    """The user's material library (survives reinstalls): %APPDATA%\\Simpler\\materials."""
    import os
    from . import paths
    d = paths.get("materials")
    os.makedirs(os.path.join(d, "textures"), exist_ok=True)
    return d


def _user_entries():
    import json
    import os
    _ensure_migrated()
    d = user_dir()
    files = sorted(f for f in os.listdir(d) if f.endswith(".json"))
    stamp = tuple((f, os.path.getmtime(os.path.join(d, f))) for f in files)
    if stamp != _user_cache["stamp"]:
        entries = {}
        for f in files:
            try:
                with open(os.path.join(d, f), encoding="utf-8") as fh:
                    e = json.load(fh)
                entries[e["id"]] = e
            except (OSError, ValueError, KeyError):
                continue
        _user_cache.update(stamp=stamp, entries=entries)
    return _user_cache["entries"]


# ---------------------------------------------------------------- the materials of Simpler become the user's (1.68.1)
# Before, the materials that come with Simpler lived in the code (PRESETS): a folder «Simpler» that could not be
# changed, and «Salva» on one of them replaced it for good with the user's version under the same id - a «Bianco»
# turned into a stained glass window became the Bianco of every new object. Now, once per library folder, every one
# of them is written as a library file like the user's own (folder «Simpler/<category>»): moved, renamed, deleted,
# overwritten (with a confirmation) as any other. PRESETS stay as the originals for «Ripristina i materiali di
# Simpler». A preset the user had overwritten under ANOTHER name (the window) becomes a material of its own, the
# original comes back; one overwritten keeping its name stays as the user made it.
MIGRATED_KEY = "presetsMigrated"
_migrating = {"dir": None, "busy": False}


def _write_entry(e):
    import json
    import os
    path = os.path.join(user_dir(), e["id"] + ".json")
    with open(path + ".part", "w", encoding="utf-8") as f:
        json.dump(e, f, indent=1)
    os.replace(path + ".part", path)
    _user_cache["stamp"] = None


def _base_name(n):
    import re
    return re.sub(r"\.\d{3}$", "", str(n or "")).strip()


def _preset_entry(mid, folder):
    """The library entry of a material of Simpler, as the code makes it."""
    import hashlib
    import json
    from . import matedit, volumetric
    mat = _make(mid, None, None)
    try:
        params, _adv = matedit.read_material(mat)
        stored = _params_to_files(params)
        vol = volumetric.library_settings(mat)
    finally:
        bpy.data.materials.remove(mat)
    rev = hashlib.sha1((json.dumps(stored, sort_keys=True) + (vol or "")).encode()).hexdigest()[:10]
    name, cat, sw = PRESETS[mid][0], PRESETS[mid][1], PRESETS[mid][2]
    e = {"id": mid, "name": tr(name), "category": tr(cat), "swatch": sw, "rev": rev, "params": stored, "version": 1,
         "folder": folder, "simpler": True}
    if vol:
        e["volumetric"] = vol
    return e


def _simpler_folder(mid, d=None):
    d = d or _folders()
    pf = d["presetFolders"]
    sub = _clean_folder(pf[mid]) if mid in pf else tr(PRESETS[mid][1])    # ("" = moved to the top of «Simpler»)
    return _clean_folder("Simpler/" + sub)


def _category_names():
    """The names the categories of Simpler had as folders (in Italian and English: the language may have changed)."""
    from .i18n import EN
    out = set()
    for v in PRESETS.values():
        out |= {v[1], tr(v[1]), EN.get(v[1], v[1])}
    return out


def _ensure_migrated():
    import os
    try:
        here = user_dir()
    except OSError:
        return
    if _migrating["dir"] == here or _migrating["busy"]:
        return
    d = _folders()
    if d.get(MIGRATED_KEY):
        _migrating["dir"] = here
        _add_new_presets(d)
        return
    _migrating["busy"] = True
    try:
        _user_cache["stamp"] = None
        entries = _user_entries()
        cats = _category_names()
        relinked = d.setdefault("relinked", {})
        for mid in PRESETS:
            folder = _simpler_folder(mid, d)
            e = entries.get(mid)
            if e is not None:
                if _base_name(e.get("name")) in (tr(PRESETS[mid][0]), PRESETS[mid][0]):
                    f = _clean_folder(e.get("folder"))
                    if not f or f in cats:
                        f = folder                     # (its category: where the others of Simpler go)
                    elif f != "Simpler" and not f.startswith("Simpler/"):
                        f = _clean_folder("Simpler/" + f)
                    e["folder"] = f
                    e["simpler"] = True
                    _write_entry(e)
                    continue
                # overwritten with another name: a material of its own, next to the original
                new = dict(e)
                new["id"] = _slug(e["name"])
                new["folder"] = folder
                new.pop("simpler", None)
                _write_entry(new)
                relinked[e.get("rev", "")] = new["id"]     # (projects with it: their copy links to the new one)
                print("SIMPLER_LIBRARY", mid, "overwritten as", repr(e.get("name")), "->", new["id"], flush=True)
            _write_entry(_preset_entry(mid, folder))
        d[MIGRATED_KEY] = True
        d[KNOWN_KEY] = sorted(PRESETS)
        d["presetFolders"] = {}
        # the folders named as a category of Simpler («Surfaces», «Gemme»), with nothing of the user's: they held only
        # materials of Simpler, now under «Simpler»
        _user_cache["stamp"] = None
        used = {_clean_folder(e.get("folder")) for k, e in _user_entries().items() if not e.get("simpler")}
        d["folders"] = [f for f in d["folders"] if not (f in cats and not any(u == f or u.startswith(f + "/") for u in used))] + ["Simpler"]
        _save_folders(d)
        _migrating["dir"] = here
    except Exception as ex:                        # (the library must open anyway: next time again)
        print("SIMPLER_LIBRARY migration failed:", ex, flush=True)
    finally:
        _migrating["busy"] = False
        _user_cache["stamp"] = None


def _add_new_presets(d):
    """The materials of Simpler the library has never had (added by an update): written once, in their folder."""
    known = d.get(KNOWN_KEY)
    if known is None:
        known = [m for m in PRESETS if m not in ADDED_PRESETS]     # (a library from before the list)
    todo = [m for m in PRESETS if m not in known]
    if not todo and KNOWN_KEY in d:
        return
    try:
        entries = _user_entries()
        for mid in todo:
            folder = _simpler_folder(mid, d)
            if mid not in entries:
                _write_entry(_preset_entry(mid, folder))
            if folder not in d["folders"]:
                d["folders"].append(folder)
        d[KNOWN_KEY] = sorted(set(known) | set(todo))
        _save_folders(d)
        if todo:
            print("SIMPLER_LIBRARY new materials of Simpler:", len(todo), flush=True)
    except Exception as ex:                        # (the library must open anyway: next time again)
        print("SIMPLER_LIBRARY new materials failed:", ex, flush=True)
    finally:
        _user_cache["stamp"] = None


def migrated():
    return bool(_folders().get(MIGRATED_KEY))


def relink(mat):
    """A project's copy of a material of Simpler that had been overwritten under another name (the window made from
    Bianco): it belongs to that material now, not to the restored original."""
    if mat is None or not mat.get(PRESET_KEY):
        return
    to = _folders().get("relinked", {}).get(mat.get(LIB_REV_KEY) or "")
    if to and to in _user_entries():
        mat[PRESET_KEY] = to


def restore_presets(data):
    """POST material/library/restore {id?}: the materials of Simpler back in the library - the deleted ones again, the
    changed ones as they were made (the changed version stays, as «<name> (modificato)» if it kept the name). The
    projects do not change."""
    ids = [data["id"]] if data.get("id") else list(PRESETS)
    entries = _user_entries()
    back, kept = 0, 0
    for mid in ids:
        if mid not in PRESETS:
            raise ApiError(tr("Solo i materiali di Simpler hanno un originale"))
        e = entries.get(mid)
        folder = (e or {}).get("folder") or _simpler_folder(mid)
        fresh = _preset_entry(mid, folder)
        if e is not None and e.get("rev") == fresh["rev"]:
            continue
        if e is not None:
            old = dict(e)
            name = old.get("name") or fresh["name"]
            if _base_name(name) == fresh["name"]:
                name = name + " (" + tr("modificato") + ")"
            old["name"] = name
            old["id"] = _slug(name)
            old.pop("simpler", None)
            _write_entry(old)
            kept += 1
        _write_entry(fresh)
        back += 1
    return {"restored": back, "kept": kept}


def _folders_file():
    import os
    return os.path.join(user_dir(), "folders.json")


def _folders():
    """{"folders": [paths], "presetFolders": {preset id: path}} - the library's folder tree (empty folders too)."""
    import json
    try:
        with open(_folders_file(), encoding="utf-8") as f:
            d = json.load(f)
    except (OSError, ValueError):
        d = {}
    d.setdefault("folders", [])
    d.setdefault("presetFolders", {})
    return d


def _save_folders(d):
    import json
    import os
    d["folders"] = sorted(set(_clean_folder(f) for f in d["folders"] if _clean_folder(f)), key=str.lower)
    with open(_folders_file() + ".part", "w", encoding="utf-8") as f:
        json.dump(d, f, indent=1)
    os.replace(_folders_file() + ".part", _folders_file())


def _clean_folder(path):
    return "/".join(p.strip() for p in str(path or "").replace("\\", "/").split("/") if p.strip())


def _default_folder(mid):
    if mid in PRESETS:
        return tr(PRESETS[mid][1])
    return tr("I miei materiali")


def library_entry(mid):
    """Library material: a user entry (saved from the editor) or a built-in preset. None if unknown."""
    e = _user_entries().get(mid)
    if e is not None:
        folder = _clean_folder(e.get("folder") or _folders()["presetFolders"].get(mid) or _default_folder(mid))
        return {"id": mid, "name": e["name"], "category": e.get("category", ""), "swatch": e.get("swatch", "#999999"),
                "rev": e["rev"], "user": True, "overrides": False, "folder": folder, "simpler": bool(e.get("simpler"))}
    if mid in PRESETS:
        p = PRESETS[mid]
        folder = _clean_folder(_folders()["presetFolders"].get(mid) or _default_folder(mid))
        return {"id": mid, "name": tr(p[0]), "category": tr(p[1]), "swatch": p[2], "rev": "base", "user": False,
                "overrides": False, "folder": folder}
    return None


def library_json():
    # (after the move to the user's library the materials of Simpler are files like the others: one deleted is gone)
    ue = _user_entries()
    ids = ([] if migrated() else [i for i in PRESETS if i not in ue]) + sorted(ue, key=lambda i: ue[i]["name"].lower())
    entries = [library_entry(i) for i in ids]
    folders = set()
    for f in list(_folders()["folders"]) + [e["folder"] for e in entries]:   # every folder, with its parents
        parts = f.split("/") if f else []
        for k in range(1, len(parts) + 1):
            folders.add("/".join(parts[:k]))
    return {"materials": entries, "folders": sorted(folders, key=str.lower)}


def folder_op(data):
    """POST material/library/folder {action: create|rename|delete, path, newPath}.
    Deleting a folder moves what it contains to the folder above (nothing is lost)."""
    import json
    import os
    action = data.get("action")
    path = _clean_folder(data.get("path"))
    d = _folders()
    if action == "create":
        if not path:
            raise ApiError(tr("Nome vuoto"))
        d["folders"].append(path)
        _save_folders(d)
        return {"path": path}
    if not path:
        raise ApiError(tr("Cartella non valida"))
    parent = "/".join(path.split("/")[:-1])
    target = _clean_folder(data.get("newPath")) if action == "rename" else parent
    if action == "rename" and not target:
        raise ApiError(tr("Nome vuoto"))
    if action == "rename" and (target + "/").startswith(path + "/"):
        raise ApiError(tr("Una cartella non può andare dentro sé stessa"))

    def moved(f):
        # (1.78.5, Luca: «se elimino un folder padre i figli devono essere eliminati») deleting takes the subfolders
        # with it: what they contain goes to the folder above the deleted one
        if action == "delete" and (f == path or f.startswith(path + "/")):
            return target
        if f == path:
            return target
        if f.startswith(path + "/"):
            return (target + "/" if target else "") + f[len(path) + 1:]
        return f
    d["folders"] = [moved(f) for f in d["folders"] if not (action == "delete" and (f == path or f.startswith(path + "/")))]
    if action == "rename":
        d["folders"].append(target)
    # materials inside: built-in ones through presetFolders, the user's in their files
    for mid in PRESETS:
        cur = _clean_folder(d["presetFolders"].get(mid) or _default_folder(mid))
        if cur == path or cur.startswith(path + "/"):
            d["presetFolders"][mid] = moved(cur)
    for mid, e in _user_entries().items():
        cur = _clean_folder(e.get("folder") or _default_folder(mid))
        if cur == path or cur.startswith(path + "/"):
            e["folder"] = moved(cur)
            fpath = os.path.join(user_dir(), mid + ".json")
            with open(fpath + ".part", "w", encoding="utf-8") as f:
                json.dump(e, f, indent=1)
            os.replace(fpath + ".part", fpath)
    _user_cache["stamp"] = None
    _save_folders(d)
    return {"path": target}


# (1.78.4) the materials of Simpler: the folder «Simpler» of the material library (models.LOCK makes it read only)
SIMPLER_FOLDER = "Simpler"


def in_simpler(folder):
    f = _clean_folder(folder)
    return f == SIMPLER_FOLDER or f.startswith(SIMPLER_FOLDER + "/")


def locked_change(key, d):
    """True when the request would change the folder «Simpler» of the materials (models.lock_check)."""
    def entry_folder(mid):
        # (Luca: «nel menu si possono togliere materiali dalle cartelle rosse»: also the built-in ones, whose folder is in
        # presetFolders / their default, not in a file of the user)
        e = library_entry(mid or "")
        return (e or {}).get("folder", "")
    if key == "POST /api/material/library/folder":
        path = _clean_folder(d.get("path"))
        if d.get("action") == "create" and path == SIMPLER_FOLDER:
            return False
        return in_simpler(path) or in_simpler(d.get("newPath") or "")
    if key == "POST /api/material/library/move":
        return in_simpler(d.get("folder") or "") or in_simpler(entry_folder(d.get("id")))
    if key in ("POST /api/material/library/delete", "POST /api/material/library/reset"):
        return in_simpler(entry_folder(d.get("id")))
    if key == "POST /api/material/library/restore":
        return True
    if key == "POST /api/material/save":
        if d.get("asNew"):
            return in_simpler(d.get("folder") or "")
        mat = bpy.data.materials.get(d.get("name") or "")
        mid = (mat.get(PRESET_KEY) if mat is not None else None) or _slug(d.get("name") or "")
        return in_simpler(entry_folder(mid)) or ("folder" in d and in_simpler(d.get("folder") or ""))
    return False


def move_to_folder(data):
    """POST material/library/move {id, folder}."""
    import json
    import os
    mid = data.get("id") or ""
    folder = _clean_folder(data.get("folder"))
    e = _user_entries().get(mid)
    d = _folders()
    if folder:
        d["folders"].append(folder)
    if e is not None:
        e["folder"] = folder
        fpath = os.path.join(user_dir(), mid + ".json")
        with open(fpath + ".part", "w", encoding="utf-8") as f:
            json.dump(e, f, indent=1)
        os.replace(fpath + ".part", fpath)
        _user_cache["stamp"] = None
    elif mid in PRESETS:
        d["presetFolders"][mid] = folder
    else:
        raise ApiError(tr("Materiale sconosciuto: {0}", mid))
    _save_folders(d)
    return {"id": mid, "folder": folder}


def _swatch(tint):
    def s(c):
        c = max(0.0, min(1.0, float(c)))
        return 12.92 * c if c <= 0.0031308 else 1.055 * c ** (1 / 2.4) - 0.055
    return "#{:02X}{:02X}{:02X}".format(*[int(round(s(c) * 255)) for c in tint[:3]])


def _params_from_files(params):
    """Library params carry texture files ("file"): they become images of the project."""
    import copy
    import os
    p = copy.deepcopy(params)

    def walk(d):
        if isinstance(d, dict):
            f = d.get("file")
            if isinstance(f, str) and f:
                from . import paths
                f = paths.resolve(f)                    # the library folder may have moved
                d.pop("file")
                d["image"] = bpy.data.images.load(f, check_existing=True).name if os.path.isfile(f) else ""
            for v in d.values():
                walk(v)
    walk(p)
    return p


def _params_to_files(params):
    """Images of the material copied into the library (so a library material never depends on a project)."""
    import copy
    import hashlib
    import os
    import shutil
    from . import proxies
    p = copy.deepcopy(params)
    tex_dir = os.path.join(user_dir(), "textures")

    def walk(d):
        if isinstance(d, dict):
            name = d.get("image")
            if isinstance(name, str) and name:
                im = bpy.data.images.get(name)
                src = proxies.source_of(im) if im is not None else None
                d.pop("image")
                if src and os.path.isfile(src):
                    st = os.stat(src)
                    h = hashlib.sha1(f"{os.path.normcase(src)}|{st.st_size}|{int(st.st_mtime)}".encode()).hexdigest()[:16]
                    dst = os.path.join(tex_dir, h + os.path.splitext(src)[1].lower())
                    if not os.path.isfile(dst):
                        shutil.copyfile(src, dst + ".part")
                        os.replace(dst + ".part", dst)
                    d["file"] = dst
                else:
                    d["file"] = ""
            for v in d.values():
                walk(v)
    walk(p)
    return p


def _slug(name):
    import re
    s = re.sub(r"[^a-z0-9]+", "_", name.lower()).strip("_") or "materiale"
    base, i = "u_" + s, 1
    out = base
    while out in PRESETS or out in _user_entries():
        i += 1
        out = f"{base}_{i}"
    return out


def save_to_library(data):
    """POST material/save {name, asNew, newName}: the material (as edited) into the user's library.
    Default: overwrites the library material it comes from (or adds it with its name). asNew: a new library material
    with newName; the material the editor started from goes back to its saved state."""
    import hashlib
    import json
    import os
    from . import matedit
    mat = bpy.data.materials.get(data.get("name") or "")
    if mat is None:
        raise ApiError(tr("Materiale non trovato"))
    relink(mat)
    params, advanced = matedit.read_material(mat)
    if advanced:
        raise ApiError(tr("Materiale avanzato: convertilo prima in materiale Simpler"))
    as_new = bool(data.get("asNew"))
    if as_new:
        new_name = (data.get("newName") or "").strip()
        if not new_name:
            raise ApiError(tr("Nome vuoto"))
        mid = _slug(new_name)
        entry_name, category = new_name, tr("I miei materiali")
        folder = _clean_folder(data.get("folder")) if "folder" in data else tr("I miei materiali")
    else:
        mid = mat.get(PRESET_KEY) or _slug(mat.name)
        old = library_entry(mid)
        # renamed in the editor: the library material takes the new name too (Blender's ".001" of copies aside)
        import re as _re
        base = _re.sub(r"\.\d{3}$", "", mat.name)
        entry_name = (data.get("newName") or "").strip() or (base if not old or base != old["name"] else old["name"])
        category = old["category"] if old else tr("I miei materiali")
        folder = _clean_folder(data["folder"]) if "folder" in data else (old["folder"] if old else tr("I miei materiali"))
    if folder:
        fd = _folders()
        fd["folders"].append(folder)
        _save_folders(fd)
    stored = _params_to_files(params)
    from . import volumetric
    vol = volumetric.library_settings(mat)
    rev = hashlib.sha1((json.dumps(stored, sort_keys=True) + (vol or "")).encode()).hexdigest()[:10]
    entry = {"id": mid, "name": entry_name, "category": category, "swatch": _swatch(params["color"]["tint"]),
             "rev": rev, "params": stored, "version": 1, "folder": folder}
    if not as_new and (old or {}).get("user") and _user_entries().get(mid, {}).get("simpler"):
        entry["simpler"] = True                # (still the material of Simpler, changed: «Ripristina» knows it)
    if vol:
        entry["volumetric"] = vol             # (fog, smoke, cloud: the volume settings go with it)
    path = os.path.join(user_dir(), mid + ".json")
    with open(path + ".part", "w", encoding="utf-8") as f:
        json.dump(entry, f, indent=1)
    os.replace(path + ".part", path)
    _user_cache["stamp"] = None
    if as_new:
        # the material of the project becomes the new library material (its objects keep the look they have); before
        # 1.68.1 a copy went to the library and the project's material went back to the old one - the objects lost
        # their edits
        if _base_name(mat.name) != entry_name:
            mat.name = entry_name
        mat[PRESET_KEY] = mid
        mat[LIB_REV_KEY] = rev
        for k in ("simpler_lib_dirty", DRAFT_KEY):
            if k in mat:
                del mat[k]
        return {"id": mid, "name": mat.name, "rev": rev, "created": True}
    mat[PRESET_KEY] = mid
    mat[LIB_REV_KEY] = rev
    if "simpler_lib_dirty" in mat:
        del mat["simpler_lib_dirty"]
    return {"id": mid, "name": mat.name, "rev": rev, "created": False}


def _back_to_library(mat):
    """A material made from the library, rebuilt as the library has it (drops unsaved edits)."""
    from . import matedit
    mid = mat.get(PRESET_KEY)
    e = _user_entries().get(mid)
    if "simpler_lib_dirty" in mat:
        del mat["simpler_lib_dirty"]
    if e is not None:
        matedit.apply(mat, _params_from_files(e["params"]), keep_original=False)
        mat[LIB_REV_KEY] = e["rev"]
        if e.get("volumetric"):
            from . import volumetric
            volumetric.from_library(mat, e["volumetric"])
    elif mid in PRESETS:
        _apply_preset_values(mat, mid)         # the built-in values
        from . import proxies
        proxies.apply(proxies.CURRENT["px"])


def reset_library(data):
    """POST material/library/reset {id}: a built-in material back to the original in the library (1.68.1: the
    changed version kept as a material of its own; the project does not change)."""
    if migrated():
        return restore_presets(data)
    """(before the move to the user's library: the saved changes dropped)"""
    import os
    mid = data.get("id") or ""
    if mid not in PRESETS:
        raise ApiError(tr("Solo i materiali di Simpler hanno un originale"))
    path = os.path.join(user_dir(), mid + ".json")
    if os.path.isfile(path):
        os.remove(path)
    _user_cache["stamp"] = None
    mat = next((m for m in bpy.data.materials if m.get(PRESET_KEY) == mid), None)
    if mat is not None and mat.get(LIB_REV_KEY):
        del mat[LIB_REV_KEY]
        _apply_preset_values(mat, mid)
    return {"id": mid}


def delete_library(data):
    """POST material/library/delete {id}: a material saved by the user leaves the library (scene untouched)."""
    import os
    mid = data.get("id") or ""
    if mid in PRESETS and not migrated():
        raise ApiError(tr("I materiali di Simpler non si eliminano (si possono ripristinare)"))
    path = os.path.join(user_dir(), mid + ".json")
    if os.path.isfile(path):
        os.remove(path)
    _user_cache["stamp"] = None
    return {"id": mid}


def _principled(mat):
    if mat.node_tree is None:
        mat.use_nodes = True
    for node in mat.node_tree.nodes:
        if node.type == "BSDF_PRINCIPLED":
            return node
    return None


def get_or_create(preset_id, fresh=False):
    """The material of a library entry in this project: the one already made (with its edits, saved or not), or a
    new one from the library (user version first, then the built-in preset).
    fresh: the material exactly as the library makes it (drag and drop, a new primitive): one already in the project
    is reused only when it is an exact copy of it (dedupe.material_key: every node, value, link, image and setting),
    otherwise a new one is made (Blender names it "Bianco.001"). Before 1.55.1 a copy that had been edited and saved
    (a "Bianco" turned into a number plate on a car) was reused: a new sphere came with the number plate."""
    user = _user_entries().get(preset_id)
    if preset_id not in PRESETS and user is None:
        raise ApiError(tr("Materiale sconosciuto: {0}", preset_id))
    mine = [m for m in bpy.data.materials if m.get(PRESET_KEY) == preset_id and not m.get("simpler_mat_original")]
    if not fresh:
        # opening it to edit («Materiali» with nothing selected, a click in the library): the copy on objects of the
        # scene, or a draft being edited without objects (DRAFT_KEY); a copy left only on deleted objects - the
        # «Bianco» made into the number plate of a car that is gone - is not it: the material as in the library
        from . import matedit
        live = [m for m in mine if matedit._users(m)] or [m for m in mine if m.get(DRAFT_KEY)]
        if not live:
            fresh = True
        mine = live or mine
    if fresh:
        made = _make(preset_id, None, user)
        from . import dedupe
        ctx = {"trees": {}, "names": {}}
        want = dedupe.material_key(made, ctx)
        same = next((m for m in mine if m is not made and dedupe.material_key(m, ctx) == want), None)
        if same is None:
            return made
        bpy.data.materials.remove(made)
        return same
    mat = mine[0] if mine else None
    # the project's copy is kept as it is, always (1.68.1): before, a copy made before the library kept revisions (the
    # Bianco of every project) was rebuilt from the library at a click on it - an old project changed by a material
    # saved in another one. What changes the library reaches only new uses (drag and drop)
    if mat is not None:
        return mat
    return _make(preset_id, None, user)


DEFAULT_KEY = "simpler_default_white"


def default_white():
    """The material of a new object (cube, sphere...): a plain white of Simpler, not the library's «Bianco» (that one
    can be changed or deleted by the user: a cube came with a stained glass window, 1.68.1). A copy in the project
    exactly like it is reused."""
    from . import dedupe
    made = bpy.data.materials.new(tr(PRESETS["bianco"][0]))
    _apply_preset_values(made, "bianco")
    made[DEFAULT_KEY] = 1
    ctx = {"trees": {}, "names": {}}
    want = dedupe.material_key(made, ctx)
    same = next((m for m in bpy.data.materials if m is not made and m.get(DEFAULT_KEY)
                 and dedupe.material_key(m, ctx) == want), None)
    if same is None:
        return made
    bpy.data.materials.remove(made)
    return same


def _make(preset_id, mat, user):
    """A material of a library entry built from the library (into mat, or a new one)."""
    if user is not None:
        from . import matedit
        mat = mat or bpy.data.materials.new(user["name"])
        mat[PRESET_KEY] = preset_id
        matedit.apply(mat, _params_from_files(user["params"]), keep_original=False)
        mat[LIB_REV_KEY] = user["rev"]
        if user.get("volumetric"):
            from . import volumetric
            volumetric.from_library(mat, user["volumetric"])
        return mat
    name = PRESETS[preset_id][0]
    mat = mat or bpy.data.materials.new(name)
    mat[PRESET_KEY] = preset_id
    _apply_preset_values(mat, preset_id)
    if preset_id in VOLUME_PRESETS:
        from . import volumetric
        volumetric.preset_to(mat, VOLUME_PRESETS[preset_id])
    return mat


def _apply_preset_values(mat, preset_id):
    _name, _cat, _sw, values = PRESETS[preset_id]
    if mat.node_tree is None:
        mat.use_nodes = True
    for k in ("simpler_mat",):
        if k in mat:
            del mat[k]
    mat.node_tree.nodes.clear()
    out = mat.node_tree.nodes.new("ShaderNodeOutputMaterial")
    bsdf = mat.node_tree.nodes.new("ShaderNodeBsdfPrincipled")
    mat.node_tree.links.new(bsdf.outputs[0], out.inputs["Surface"])
    for key, val in values.items():
        if key in bsdf.inputs:
            sock = bsdf.inputs[key]
            sock.default_value = (*val, 1.0) if isinstance(val, tuple) and len(val) == 3 and len(sock.default_value) == 4 else val


def _graded_alpha(p):
    from .matedit import graded_opacity
    o = p["opacity"]
    if o["useAlpha"]:
        return graded_opacity(p["color"]["map"].get("image"), "A")
    return graded_opacity(o["map"].get("image"), o["map"].get("channel") or "")


def is_transmissive(mat):
    """Glass-like material that can cast sharp (MNEE) caustics."""
    if not mat:
        return False
    from . import matedit
    mp = matedit.params_of(mat)
    if mp is not None:
        # dispersive glass too: its plain-glass share gives the sharp caustic (white; the coloured share uses
        # the regular caustics), see matedit.dispersive_glass
        return mp["transmission"]["weight"] > 0.5
    bsdf = _principled(mat) if mat.node_tree else None
    if bsdf is None:
        return False
    tw = bsdf.inputs.get("Transmission Weight")
    return bool(tw and not tw.is_linked and tw.default_value > 0.5)


def assign_undo_ids(obj_ids):
    """The objects an assignment can change: the ones chosen, their parts and every instance sharing a geometry
    with them (for undo)."""
    from .core import ID_KEY
    obs, stack = [], _expand_scatter([find(i, required=False) for i in obj_ids])
    kids = tree_kids(stack)                    # (Object.children per piece: seconds on big models)
    while stack:
        ob = stack.pop()
        if ob is None:
            continue
        obs.append(ob)
        stack.extend(kids.get(ob, ()))
    meshes = {o.data for o in obs if o.type == "MESH" and o.data is not None}
    out = {o.get(ID_KEY) for o in obs if o.get(ID_KEY)}
    if meshes:
        for o in bpy.context.scene.objects:
            if o.type == "MESH" and o.data in meshes and o.get(ID_KEY):
                out.add(o.get(ID_KEY))
    return list(out)


def _expand_scatter(obs):
    """A distribution stands for its models (they are not in the scene): their meshes get the material."""
    from . import paint
    out = []
    for ob in obs:
        out.append(ob)
        if ob is not None and ob.get("simpler_paint"):
            c = bpy.data.collections.get(ob.get(paint.SCATTER_COLL) or "")
            if c is not None:
                out.extend(o for o in c.all_objects if not o.get("simpler_trashed"))
    return out


def assign(obj_ids, preset_id, slot=None, name=None, replace=None):
    """Assign a library material (preset_id) - or a material of the project (name) - to objects (and the meshes under
    groups). Per-object, so instanced meshes can carry different materials."""
    if name:
        mat = bpy.data.materials.get(name)
        if mat is None:
            raise ApiError(tr("Materiale non trovato"))
    else:
        mat = get_or_create(preset_id, fresh=True)
    count = 0
    # instances (objects sharing one geometry: copies made as "Istanza", library models and their copies, painted
    # pieces) change all together: the material goes on the shared geometry and every instance follows it. A piece
    # with a geometry of its own keeps the material on the object, as before ("Solo per questo oggetto" still gives
    # one object a material of its own).
    users = {}
    for o in bpy.context.scene.objects:
        if o.type == "MESH" and o.data is not None and not o.get("simpler_twin") and not o.get("simpler_water_body"):
            users.setdefault(o.data, []).append(o)    # (the body of a water shares its mesh but keeps its own material)
    for o in [o for o in _expand_scatter([find(i) for i in obj_ids]) if o.get("simpler_paint_model") and not o.get("simpler_paint")]:
        if o.type == "MESH" and o.data is not None and o not in users.get(o.data, []):
            users.setdefault(o.data, []).append(o)        # (models of distributions share with their instances)
    stack = _expand_scatter([find(i) for i in obj_ids])
    kids = tree_kids(stack)                    # (Object.children per piece: seconds on big models)
    done = set()
    while stack:
        ob = stack.pop()
        stack.extend(kids.get(ob, ()))
        if ob.type != "MESH" or ob in done or ob.get("simpler_paint_data"):
            continue
        done.add(ob)
        if replace:
            # (a piece of a distribution under the mouse: only the surfaces with that material)
            slots = [i for i, sl in enumerate(ob.material_slots) if sl.material and sl.material.name == replace]
        else:
            if not ob.material_slots:
                ob.data.materials.append(None)
            slots = range(len(ob.material_slots)) if slot is None else [int(slot)]
        shared = [u for u in users.get(ob.data, []) if u is not ob]
        for i in slots:
            if not 0 <= i < len(ob.material_slots):
                continue
            if shared:
                ob.data.materials[i] = mat
                for u in [ob] + shared:
                    if i < len(u.material_slots) and u.material_slots[i].link != "DATA":
                        u.material_slots[i].link = "DATA"
                        done.add(u)
            else:
                ob.material_slots[i].link = "OBJECT"
                ob.material_slots[i].material = mat
            count += 1
    try:
        from . import matedit
        matedit.ensure_pieces(mat)            # «Centra ogni pezzo»: the new objects get their pieces
    except Exception as e:
        print("SIMPLER_PIECES", mat.name, e, flush=True)
    if not name and done and not any(o.get("simpler_paint_model") for o in done):
        # a material of the library with a texture: centred on what it was put on (matedit.centre_on)
        from . import matedit
        try:
            matedit.centre_on(mat, list(done))
        except Exception as e:                # (a help: never in the way of the assignment)
            print("SIMPLER_AUTOCENTRE", mat.name, e, flush=True)
    from . import volumetric
    volumetric.sync_objects([o for o in done if o.type == "MESH"])      # (a volumetric material on, or off, this piece)
    if mat.get(PRESET_KEY) == "acqua" and not mat.get("simpler_water"):
        # the water of the library is water (waves and body of the water on): it can be changed in its editor
        from . import water
        water.set_material({"name": mat.name, "on": True})
    else:
        from . import water
        for ob in [o for o in done if o.get("simpler_water_body") is None]:
            try:
                if ob.type == "MESH":
                    water._sync(ob)                   # (a water material on, or off, this piece)
            except ReferenceError:                    # (removed meanwhile)
                pass
    return {"assigned": count, "material": mat.name}


def set_params(name, data):
    """Simple controls on a material: color (linear RGB 0-1), roughness, metallic."""
    mat = bpy.data.materials.get(name)
    if not mat:
        raise ApiError(tr("Materiale non trovato"))
    bsdf = _principled(mat)
    if not bsdf:
        raise ApiError(tr("Materiale non modificabile"))
    if "color" in data:
        c = data["color"]
        bsdf.inputs["Base Color"].default_value = (float(c[0]), float(c[1]), float(c[2]), 1.0)
    for key, inp in (("roughness", "Roughness"), ("metallic", "Metallic"), ("ior", "IOR")):
        if key in data:
            bsdf.inputs[inp].default_value = float(data[key])
    return {}


# ---------------------------------------------------------------- real-time view

def _socket(node, *names, default=None):
    for n in names:
        s = node.inputs.get(n)
        if s is not None and hasattr(s, "default_value"):
            v = s.default_value
            return list(v) if hasattr(v, "__len__") else float(v)
    return default


def realtime_params(mat):
    """Approximate PBR values of a material for the real-time view (three.js MeshPhysicalMaterial).
    textured=True when the material uses image textures: then the view needs a new export to show it."""
    out = {"name": mat.name if mat else "", "color": [0.8, 0.8, 0.8], "metallic": 0.0, "roughness": 0.5,
           "transmission": 0.0, "ior": 1.5, "alpha": 1.0, "emission": [0, 0, 0], "emissionStrength": 0.0,
           "coat": 0.0, "textured": False}
    if mat is None or not mat.use_nodes or not mat.node_tree:
        if mat is not None:
            out["color"] = list(mat.diffuse_color)[:3]
        return out
    from . import volumetric
    if volumetric.is_on(mat):
        # a volume: the view draws it by itself (viewer.js volMaterial), from these settings
        out.update({"volume": volumetric.realtime(mat), "simpler": True, "textured": False})
        return out
    if mat.get("simpler_ground_image") and bpy.data.images.get(mat["simpler_ground_image"]) is not None:
        # the ground of the Ambiente: its texture, tiled by the mesh UVs (the large variations are Cycles only)
        out.update({"color": [1.0, 1.0, 1.0], "roughness": float(mat.get("simpler_ground_rough", 0.9)), "specular": 0.4,
                    "maps": {"color": {"image": mat["simpler_ground_image"], "channel": "", "invert": False, "strength": 1.0, "color": True}},
                    "uv": {"mode": "uv", "scale": 1.0, "stretch": [1.0, 1.0], "rotation": 0.0, "offset": [0.0, 0.0]},
                    "simpler": True, "textured": False, "rev": "ground_" + mat["simpler_ground_image"]})
        return out
    from . import matedit
    mp = matedit.params_of(mat)
    if mp is not None:
        return _realtime_from_params(mat, mp, out)
    nodes = mat.node_tree.nodes
    out["textured"] = any(n.type == "TEX_IMAGE" and n.image is not None and any(o.is_linked for o in n.outputs) for n in nodes)
    p = next((n for n in nodes if n.type == "BSDF_PRINCIPLED"), None)
    if p is None:
        out["textured"] = True     # unknown shader graph: export it
        return out
    out["color"] = (_socket(p, "Base Color", default=[0.8, 0.8, 0.8, 1]) or [0.8, 0.8, 0.8])[:3]
    out["metallic"] = _socket(p, "Metallic", default=0.0)
    out["roughness"] = _socket(p, "Roughness", default=0.5)
    out["transmission"] = _socket(p, "Transmission Weight", "Transmission", default=0.0)
    out["ior"] = _socket(p, "IOR", default=1.5)
    out["alpha"] = _socket(p, "Alpha", default=1.0)
    out["emission"] = (_socket(p, "Emission Color", "Emission", default=[0, 0, 0, 1]) or [0, 0, 0])[:3]
    out["emissionStrength"] = _socket(p, "Emission Strength", default=0.0)
    out["coat"] = _socket(p, "Coat Weight", "Clearcoat", default=0.0)
    # base colour driven by another node (procedural): not representable in place
    bc = p.inputs.get("Base Color")
    if bc is not None and bc.is_linked:
        out["textured"] = True
    return out


def _image_rev(name):
    """(1.78.4) which picture a name means now: the view keeps the pictures it loaded by name, and the generic names of
    imported plants («color map.015») come back for another picture - the leaves of one plant showed another's."""
    import hashlib
    im = bpy.data.images.get(name)
    if im is None:
        return ""
    try:
        size = im.packed_file.size if im.packed_file is not None else -1
    except Exception:
        size = -1
    return hashlib.md5(f"{im.filepath}|{size}|{im.get('simpler_src', '')}".encode("utf-8")).hexdigest()[:10]


def _realtime_from_params(mat, p, out):
    """Materials edited in Simpler: every channel for the real-time view, maps loaded by the view itself
    (GET /api/texture), so an edit never needs a new preparation of the whole scene."""
    from . import dusk
    import hashlib
    import json as _json
    import colorsys
    c = p["color"]
    tint = [float(v) for v in c["tint"]]
    if abs(c["saturation"] - 1) > 1e-4 or abs(c["brightness"] - 1) > 1e-4:
        h, sat, v = colorsys.rgb_to_hsv(*tint)
        tint = list(colorsys.hsv_to_rgb(h, max(0.0, min(1.0, sat * c["saturation"])), v * c["brightness"]))
    t = p["transmission"]

    def m(d, color=False):
        if not d or not d.get("image") or bpy.data.images.get(d["image"]) is None:
            return None
        from .matedit import map_scale
        return {"image": d["image"], "channel": d.get("channel", ""), "invert": bool(d.get("invert")),
                "strength": float(d.get("strength", 1.0)), "color": color, "scale": map_scale(d), "rev": _image_rev(d["image"])}
    rmap = m(p["roughness"]["map"])
    if rmap and p["roughness"].get("glossy"):
        rmap["invert"] = not rmap["invert"]
    out.update({
        "color": tint, "metallic": float(p["metallic"]["value"]), "roughness": float(p["roughness"]["value"]),
        "transmission": float(t["weight"]), "ior": float(t["ior"]), "thin": bool(t["thin"]),
        "dispersion": bool(t["dispersion"]) and float(t["weight"]) > 0,
        "coat": float(p["coat"]["weight"]), "coatRoughness": float(p["coat"]["roughness"]),
        "sheen": float(p["sheen"]["weight"]), "sheenRoughness": float(p["sheen"]["roughness"]), "sheenColor": p["sheen"]["tint"],
        "emission": [p["emission"]["color"][i] for i in range(3)],
        "emissionStrength": (float(p["emission"]["nits"]) / 683.0) if dusk.mat_lit(p) else 0.0, "kelvin": float(p["emission"]["kelvin"]),
        "specular": float(p["specular"]),
        "maps": {"color": m(c["map"], True), "roughness": rmap, "metallic": m(p["metallic"]["map"]),
                 "normal": m(p["normal"]["map"]), "bump": m(p["normal"]["bumpMap"]), "emission": m(p["emission"]["map"], True),
                 "alpha": (dict(m(c["map"], True), channel="A", invert=bool(p["opacity"]["invert"]))
                           if p["opacity"]["useAlpha"] and m(c["map"], True) else
                           (dict(m(p["opacity"]["map"]), invert=bool(p["opacity"]["invert"]) != bool(p["opacity"]["map"].get("invert")))
                            if m(p["opacity"]["map"]) else None))},
        "alphaCutout": bool(p["opacity"].get("cutout", True)) and not _graded_alpha(p),
        "normalStrength": float(p["normal"]["strength"]), "directx": bool(p["normal"]["directx"]),
        "bumpStrength": float(p["normal"]["bump"]),
        "uv": p["uv"], "simpler": True, "textured": False,
    })
    out["alpha"] = 1.0
    from . import matedit as _me
    if _me.grunge_on(p):
        # «Sporco» for the view: the same picture, projected from three sides in the world, as the path tracing
        g = p["grunge"]
        mask = g["map"].get("image") if g["map"].get("image") and bpy.data.images.get(g["map"]["image"]) else _me.grunge_image().name
        out["grunge"] = {"amount": float(g["amount"]), "opacity": float(g.get("opacity", 1.0)), "sizeCm": float(g["sizeCm"]),
                         "color": [float(v) for v in g["color"][:3]], "roughness": float(g["roughness"]),
                         "randomize": bool(g.get("randomize", True)), "mask": mask,
                         "invert": bool(g["map"].get("invert")) and mask == g["map"].get("image"),
                         "colorMap": g["colorMap"].get("image") if g["colorMap"].get("image") and bpy.data.images.get(g["colorMap"]["image"]) else None,
                         "paint": bool(g.get("paint")), "seed": int(g.get("seed", 0) or 0)}
    mc = p.get("macro")
    if isinstance(mc, dict):
        # (1.76.6) «Variazione su grande scala» for the view (viewer.js useMacro): the big picture's pattern/colour
        # over the detail and the slow variation of tone
        img = (mc.get("map") or {}).get("image")
        img = img if img and bpy.data.images.get(img) else None
        st = float(mc.get("strength", 0)) if img else 0.0
        if st > 0 or float(mc.get("tone", 0)) > 0:
            out["macro"] = {"image": img, "sizeCm": float(mc.get("sizeCm", 2000.0)), "strength": st,
                            "colour": float(mc.get("colour", 0.0)), "mean": mc.get("mean") or [0.5, 0.5, 0.5],
                            "detailMean": mc.get("detailMean") or mc.get("mean") or [0.5, 0.5, 0.5],
                            "tone": float(mc.get("tone", 0.0)), "toneSizeM": float(mc.get("toneSizeM", 30.0))}
    b = p.get("blend")
    if isinstance(b, dict) and b.get("partners") and float(b.get("width") or 0) > 0:
        # (1.76.4) «Sfumatura dei bordi» of the terrain for the view (viewer.js useEdgeBlend): the colour and the
        # roughness of each zone next to this one, with its projection
        parts = []
        for q in b["partners"]:
            qp = _me._merge(_me.DEFAULTS, q.get("params") or {})
            qc = qp["color"]
            qt = [float(v) for v in qc["tint"]]
            if abs(qc["saturation"] - 1) > 1e-4 or abs(qc["brightness"] - 1) > 1e-4:
                h_, s_, v_ = colorsys.rgb_to_hsv(*qt)
                qt = list(colorsys.hsv_to_rgb(h_, max(0.0, min(1.0, s_ * qc["saturation"])), v_ * qc["brightness"]))
            img = qc["map"].get("image") if qc["map"].get("image") and bpy.data.images.get(qc["map"]["image"]) else None
            parts.append({"uv": "uv" + str(1 + ["simpler_tb01", "simpler_tb23", "simpler_tb45"].index(q["attr"])),
                          "comp": int(q.get("comp", 0)), "sign": 1 if float(q.get("sign", 1)) >= 0 else -1,
                          "color": qt, "map": img, "roughness": float(qp["roughness"]["value"]), "proj": qp["uv"],
                          "width": float(q.get("width") or b["width"])})
        out["blend"] = {"width": float(b["width"]), "irregular": float(b.get("irregular", 0.6)), "partners": parts}
    t = p.get("tone")
    if isinstance(t, dict) and t.get("on", True):
        # (1.76.14) «Colori dal terreno» for the view (viewer.js useTone), as matedit tone_color
        out["tone"] = {k: float(t.get(k, 0.0)) for k in ("streaks", "bands", "ridges", "wet")}
    if isinstance(t, dict) and float(t.get("relief", 0) or 0) > 0 and t.get("rtype") != "nessuno":
        # (1.76.58) the colour map of «Rilievo 3D» (viewer.js useReliefColor, as matedit relief_color)
        rp = _me.relief_params(t)
        if rp["cmap"]:
            out["reliefColor"] = {"image": rp["cmap"], "amount": rp["ca"], "sizeM": rp["ms"], "rot": rp["mr"], "where": rp["w"]}
    fb = p.get("fabric")
    if isinstance(fb, dict) and fb.get("enabled"):
        # (1.77.1) type «Tessuto» for the view (viewer.js useFabric)
        out["fabric"] = {"thin": fb.get("mode") == "sottile", "see": float(fb.get("see", 0.6)), "light": float(fb.get("light", 0.5)),
                         "edge": float(fb.get("edge", 0.6)), "fuzzMask": m(fb.get("fuzzMap")), "tintMask": m(fb.get("tintMap")),
                         "tint": [float(v) for v in (fb.get("tint") or [1, 1, 1])[:3]]}
    f = p.get("foliage")
    if isinstance(f, dict) and f.get("enabled"):
        # (1.77.0) type «Fogliame» for the view (viewer.js useFoliage): the same ramps and moments as matedit.foliage_color
        leaves = f.get("part", "foglie") != "legno"
        out["foliage"] = {"leaves": leaves, "season": float(f.get("season", 0.0)) if leaves else 0.0,
                          "translucency": float(f.get("translucency", 0.5)) if leaves else 0.0,
                          "back": float(f.get("back", 0.3)) if leaves else 0.0, "variation": float(f.get("variation", 0.3)),
                          "red": float(f.get("red", 0.5)), "drop": _me.FOLIAGE_DROP, "noiseM": _me.FOLIAGE_NOISE_M,
                          "spread": _me.FOLIAGE_SPREAD,
                          "start": _me.FOLIAGE_START, "life": _me.FOLIAGE_LIFE, "stretch": _me.FOLIAGE_STRETCH, "ramps": {k: [list(v) for v in r] for k, r in _me.FOLIAGE_RAMPS.items()}}
    it = p.get("interior")
    if isinstance(it, dict) and it.get("enabled"):
        # (1.79.0) type «Interni» for the view (viewer.js useInterior): the same cells, box and picture as matedit.interior
        atlas = _me.interior_atlas(it)
        im = atlas or _me.interior_image(it.get("room"))
        if im is not None:
            out["interior"] = {"image": im.name, "rev": _image_rev(im.name), "w": float(it.get("roomW", 4.0)),
                               "h": float(it.get("roomH", 3.0)), "d": float(it.get("depthM", 4.0)),
                               "bright": _me.interior_bright(it), "back": _me.INTERIOR_BACK, "flat": _me.INTERIOR_FLAT,
                               "night": _me.interior_night(it), "kelvin": float(it.get("kelvin", 3000.0)),
                               "share": float(it.get("share", 0.6)), "atlas": atlas is not None, "stretch": bool(it.get("stretch")),
                               # («Si adatta al modello»: the scale each object had when it was switched on - matedit.interior_pass)
                               "refs": {o.get("simpler_id"): [float(o[k]) for k in _me.INTERIOR_REF] for o in (_me._users(mat) if it.get("stretch") else [])
                                        if o.get("simpler_id") and all(k in o for k in _me.INTERIOR_REF)},
                               "layers": list(_me.INTERIOR_LAYERS), "edge": _me.INTERIOR_EDGE}
    out["rev"] = hashlib.sha1((_json.dumps(p, sort_keys=True)
                               + ("|n%.3f|b%.3f" % (out["interior"]["night"], out["interior"]["bright"]) if "interior" in out else "")).encode()).hexdigest()[:12]
    return out


def realtime_json(data):
    from .core import find
    out = {}
    for oid in data.get("ids") or []:
        ob = find(oid, required=False)
        if ob is None or ob.type != "MESH":
            continue
        out[oid] = [realtime_params(sl.material) for sl in ob.material_slots]
    return {"objects": out}
