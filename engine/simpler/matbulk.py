"""The "Correggi materiali" wizard: material fixes on many models of the personal library at once.

Scan: every chosen model is read by a separate Blender (../matbulk_job.py) - its materials with the editor's channels
and a category (glass, fake glass, glass with a metal map, metal, glossy, ...). Apply: the chosen materials of the
chosen models get the changes (set / multiply / add a channel, remove a map), each model.blend is written again and
its thumbnail rendered again. A copy of every model.blend is kept first (backup, on by default): "Ripristina" puts
the last correction back. The scene open in the app is never touched (models already placed stay as they are).
"""
import json
import os
import shutil
import subprocess
import tempfile
import threading
import time

import bpy

from . import fullspeed
from .core import ApiError, log
from .i18n import tr
from . import tempdirs

JOB = {"state": "idle", "mode": "", "done": 0, "total": 0, "current": "", "result": None, "error": "", "proc": None,
       "lock": threading.Lock(), "started": 0.0}
KEEP_BACKUPS = 3


def _backup_root():
    from .models import user_dir
    d = os.path.join(os.path.dirname(user_dir()), "models_backup")
    os.makedirs(d, exist_ok=True)
    return d


def _model_list(ids):
    from .models import _entries, user_dir
    entries = _entries()
    out = []
    for mid in ids or []:
        e = entries.get(mid)
        if e is None:
            continue
        blend = os.path.join(user_dir(), mid, "model.blend")
        if os.path.isfile(blend):
            out.append({"id": mid, "name": e.get("name", mid), "folder": e.get("folder", ""), "blend": blend})
    return out


def _start(mode, req, after=None):
    with JOB["lock"]:
        if JOB["state"] == "running":
            raise ApiError(tr("Una correzione dei materiali è già in corso"))
        JOB.update(state="running", mode=mode, done=0, total=len(req["models"]), current="", result=None, error="",
                   started=time.time())
    exe = os.environ.get("SIMPLER_RENDER_EXE") or bpy.app.binary_path
    script = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "matbulk_job.py")
    work = tempdirs.make("simpler_matbulk_")
    rq, out = os.path.join(work, "request.json"), os.path.join(work, "result.json")
    with open(rq, "w", encoding="utf-8") as f:
        json.dump(dict(req, mode=mode), f)

    def run():
        err, result = "", None
        try:
            from .render import cpu_threads
            flags = (0x08000000 | 0x00004000) if os.name == "nt" else 0       # no window, below normal priority
            proc = fullspeed.popen([exe, "--factory-startup", "-t", str(cpu_threads()), "-b", "--python", script, "--", rq, out],
                                    stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, encoding="utf-8",
                                    errors="replace", creationflags=flags, bufsize=1)
            with JOB["lock"]:
                JOB["proc"] = proc
            tail = []
            for line in proc.stdout:
                line = line.rstrip()
                tail = (tail + [line])[-8:]
                if line.startswith("SIMPLER_BULK "):
                    parts = line.split(" ", 3)
                    try:
                        with JOB["lock"]:
                            JOB.update(done=int(parts[1]), total=int(parts[2]), current=parts[3] if len(parts) > 3 else "")
                    except (ValueError, IndexError):
                        pass
            proc.wait()
            if JOB["state"] == "cancelled":
                return
            if os.path.isfile(out):
                with open(out, encoding="utf-8") as f:
                    result = json.load(f)
                err = result.get("error", "") if isinstance(result, dict) else ""
            else:
                err = "\n".join(tail[-4:]) or "job failed"
            if after is not None and not err:
                after(result)
        except Exception as exc:
            err = str(exc)
        finally:
            shutil.rmtree(work, ignore_errors=True)
            with JOB["lock"]:
                JOB["proc"] = None
                if JOB["state"] != "cancelled":
                    JOB.update(state="error" if err else "done", error=err, result=result)
            log("SIMPLER_MATBULK", mode, "error" if err else "done", f"{time.time() - JOB['started']:.1f}s", err[-300:])

    threading.Thread(target=run, daemon=True).start()
    return status()


def status(_data=None):
    with JOB["lock"]:
        out = {k: JOB[k] for k in ("state", "mode", "done", "total", "current", "error")}
        if JOB["state"] == "done":
            out["result"] = JOB["result"]
    out["backup"] = last_backup()
    return out


def cancel(_data=None):
    with JOB["lock"]:
        proc = JOB["proc"]
        if JOB["state"] == "running":
            JOB["state"] = "cancelled"
    if proc is not None and proc.poll() is None:
        try:
            proc.kill()
        except OSError:
            pass
    return status()


def scan(data):
    """POST matbulk/scan {ids}: the materials of these library models (then GET matbulk/status)."""
    models = _model_list(data.get("ids"))
    if not models:
        raise ApiError(tr("Scegli almeno un modello della libreria"))
    return _start("scan", {"models": models})


def apply(data):
    """POST matbulk/apply {items: [{id, materials}], ops: [{param, mode, value}], backup: bool}."""
    items = {it.get("id"): list(it.get("materials") or []) for it in data.get("items") or [] if it.get("materials")}
    models = _model_list(list(items))
    for m in models:
        m["materials"] = items[m["id"]]
    ops = [o for o in data.get("ops") or [] if o.get("param")]
    if not models or not ops:
        raise ApiError(tr("Niente da correggere: scegli dei materiali e almeno una modifica"))
    bdir = ""
    if data.get("backup", True):
        bdir = os.path.join(_backup_root(), time.strftime("%Y%m%d-%H%M%S"))
        os.makedirs(bdir, exist_ok=True)
        with open(os.path.join(bdir, "run.json"), "w", encoding="utf-8") as f:
            json.dump({"ids": [m["id"] for m in models], "names": {m["id"]: m["name"] for m in models},
                       "ops": ops, "when": time.strftime("%Y-%m-%d %H:%M")}, f)
        _trim_backups()

    def after(result):
        # every changed model: a new thumbnail (and the library sees a new revision)
        from . import models as M
        for it in (result or {}).get("models") or []:
            if it.get("changed") and not it.get("error"):
                try:
                    M.rethumb({"id": it["id"]})
                except Exception as exc:
                    log("SIMPLER_MATBULK", "thumb", it["id"], exc)

    return _start("apply", {"models": models, "ops": ops, "backup": bdir}, after)


# ---------------------------------------------------------------- vegetation (1.78.0)
VEG_TYPES = ("albero", "arbusto", "erba", "fiore")
VEG_FOLDERS = {"albero": "Alberi", "arbusto": "Arbusti e siepi", "erba": "Erbe e prati", "fiore": "Fiori e coprenti"}


def veg_root():
    return tr("Vegetazione")


def veg_type_of(size_cm):
    """The kind of plant proposed from its height: tree, shrub or grass (a flower is chosen by hand)."""
    h = float((size_cm or [0, 0, 0])[2] or 0)
    return "albero" if h >= 300 else "arbusto" if h >= 60 else "erba"


def veg_folder(kind):
    return veg_root() + "/" + tr(VEG_FOLDERS.get(kind, "Alberi"))


def vegetation(data):
    """POST models/vegetation {ids, types: {id: kind}, parts: {id: {material: foglie|legno|altro}}, dry}: the models
    become plants - every material of the type Fogliame (leaves or wood), the model marked as vegetation and moved
    into Vegetazione/<kind> (when it is not there yet), a new thumbnail. dry: only the leaves/wood guess (GET status)."""
    models = _model_list(data.get("ids"))
    if not models:
        raise ApiError(tr("Scegli almeno un modello della libreria"))
    types = data.get("types") or {}
    dry = bool(data.get("dry"))

    def after(result):
        from . import models as M
        entries = M._entries()
        root = veg_root()
        for it in (result or {}).get("models") or []:
            e = entries.get(it.get("id"))
            if e is None or it.get("error"):
                continue
            mats = it.get("materials") or []
            kind = types.get(e["id"]) if types.get(e["id"]) in VEG_TYPES else (e.get("veg") or {}).get("type") \
                or veg_type_of(M._entry_json(e).get("sizeCm"))
            e["veg"] = {"type": kind, "leaves": [m["name"] for m in mats if m["part"] == "foglie"],
                        "wood": [m["name"] for m in mats if m["part"] == "legno"]}
            folder = M._clean(e.get("folder"))
            # into Vegetazione/<kind>: from outside the vegetation, from its top folder, or when the kind is chosen
            # (a subfolder chosen by the user inside Vegetazione stays)
            if not folder.startswith(root + "/") or types.get(e["id"]) in VEG_TYPES:
                # (1.78.3) a model of the folder «Simpler» (what goes into the installation) stays among Simpler's plants
                simpler = folder == "Simpler" or folder.startswith("Simpler/") or folder.startswith(root + "/Simpler")
                e["folder"] = (root + "/Simpler/" + tr(VEG_FOLDERS.get(kind, "Alberi"))) if simpler else veg_folder(kind)
                d = M._folders()
                d["folders"].append(e["folder"])
                M._save_folders(d)
            e["rev"] = str(int(time.time()))
            M._write_json(os.path.join(M.user_dir(), e["id"] + ".json"), e)
            if it.get("changed"):
                try:
                    M.rethumb({"id": e["id"]})
                except Exception as exc:
                    log("SIMPLER_MATBULK", "thumb", e["id"], exc)

    return _start("veg", {"models": models, "parts": data.get("parts") or {}, "dry": dry}, None if dry else after)


def _trim_backups():
    root = _backup_root()
    runs = sorted(d for d in os.listdir(root) if os.path.isdir(os.path.join(root, d)))
    for d in runs[:-KEEP_BACKUPS]:
        shutil.rmtree(os.path.join(root, d), ignore_errors=True)


def last_backup():
    root = _backup_root()
    runs = sorted(d for d in os.listdir(root) if os.path.isfile(os.path.join(root, d, "run.json")))
    for d in reversed(runs):
        try:
            with open(os.path.join(root, d, "run.json"), encoding="utf-8") as f:
                info = json.load(f)
        except (OSError, ValueError):
            continue
        if info.get("restored"):
            continue
        return {"run": d, "when": info.get("when", ""), "count": len(info.get("ids") or [])}
    return None


def restore(data):
    """POST matbulk/restore {run}: the models of that correction back as they were (their backup copies)."""
    from . import models as M
    root = _backup_root()
    run = data.get("run") or (last_backup() or {}).get("run")
    if not run or not os.path.isfile(os.path.join(root, run, "run.json")):
        raise ApiError(tr("Nessuna correzione da ripristinare"))
    with open(os.path.join(root, run, "run.json"), encoding="utf-8") as f:
        info = json.load(f)
    done = 0
    entries = M._entries()
    for mid in info.get("ids") or []:
        # (1.78.4) the models of the locked Simpler parts stay as they are
        if M.is_locked((entries.get(mid) or {}).get("folder", "")):
            continue
        src = os.path.join(root, run, mid, "model.blend")
        dst = os.path.join(M.user_dir(), mid, "model.blend")
        if os.path.isfile(src) and os.path.isdir(os.path.dirname(dst)):
            shutil.copy2(src, dst)
            done += 1
            try:
                M.rethumb({"id": mid})
            except Exception:
                pass
    info["restored"] = True
    with open(os.path.join(root, run, "run.json"), "w", encoding="utf-8") as f:
        json.dump(info, f)
    return {"restored": done}
