"""Statistics of the personal model library and suggestions to save disk space ("Statistiche della libreria").

GET-like job (POST libstats/run {folders: [...] | all}) in a background thread - only files are read, never Blender
data, so the engine stays free: how many models, how much space in model files, textures and thumbnails, per folder,
the biggest models, texture formats and sizes, the original files the models were imported from. Then suggestions:
copies kept by the material fixes (backups), texture folders of deleted models, identical textures in several models,
models saved twice, caches that Simpler makes again by itself, broken models. Each suggestion that can be acted on
has an action (POST libstats/clean {action, ...}); the ones that may affect old projects say so.
"""
import hashlib
import json
import os
import shutil
import threading
import time

import bpy

from .core import ApiError, log
from .i18n import tr

JOB = {"state": "idle", "done": 0, "total": 0, "phase": "", "result": None, "error": "", "lock": threading.Lock()}
IMG_EXT = {".png", ".jpg", ".jpeg", ".tif", ".tiff", ".exr", ".hdr", ".tga", ".bmp", ".webp", ".dds"}


def _size(path):
    try:
        return os.path.getsize(path)
    except OSError:
        return 0


def _tree_size(root):
    total, n = 0, 0
    for dp, _dn, fn in os.walk(root):
        for f in fn:
            total += _size(os.path.join(dp, f))
            n += 1
    return total, n


def _hash(path, size):
    """Same size + same first and last MB + same size = the same file (fast enough for many GB)."""
    h = hashlib.sha1(str(size).encode())
    try:
        with open(path, "rb") as f:
            h.update(f.read(1 << 20))
            if size > 2 << 20:
                f.seek(-(1 << 20), 2)
                h.update(f.read(1 << 20))
    except OSError:
        return None
    return h.hexdigest()


def _in_folders(folder, chosen):
    if chosen is None:
        return True
    return any(folder == c or folder.startswith(c + "/") or (c == "" and folder == "") for c in chosen)


def _scan(chosen):
    from . import models as M, render, proxies, paths, matbulk
    lib = M.user_dir()
    entries = M._entries()
    sel = {mid: e for mid, e in entries.items() if _in_folders(M._clean(e.get("folder")), chosen)}
    with JOB["lock"]:
        JOB.update(total=len(entries) + 6, phase=tr("Lettura dei modelli"))
    per_model, per_folder = [], {}
    tex_all = []          # (model id, path, size) for the whole library: duplicates are a library matter
    exts, res = {}, {"4k": 0, "8k": 0, "big_bytes": 0}
    totals = {"models": 0, "blend": 0, "textures": 0, "texFiles": 0, "thumbs": 0, "sources": 0, "sourceFiles": 0,
              "sourceMissing": 0}
    broken, blend_hash = [], {}
    for i, (mid, e) in enumerate(sorted(entries.items())):
        with JOB["lock"]:
            JOB["done"] = i
        d = os.path.join(lib, mid)
        blend = os.path.join(d, "model.blend")
        bsize = _size(blend)
        tdir = os.path.join(d, "textures")
        tsize, tcount = 0, 0
        if os.path.isdir(tdir):
            for dp, _dn, fn in os.walk(tdir):
                for f in fn:
                    p = os.path.join(dp, f)
                    s = _size(p)
                    tex_all.append((mid, p, s))
                    if mid in sel:
                        tsize += s
                        tcount += 1
                        ext = os.path.splitext(f)[1].lower() or "?"
                        exts[ext] = exts.get(ext, 0) + s
                        dims = proxies._dimensions(p) if ext in (".png", ".jpg", ".jpeg") else None
                        if dims and max(dims) >= 8000:
                            res["8k"] += 1
                            res["big_bytes"] += s
                        elif dims and max(dims) >= 4000:
                            res["4k"] += 1
                            res["big_bytes"] += s
        if not os.path.isfile(blend):
            broken.append({"id": mid, "name": e.get("name", mid), "folder": M._clean(e.get("folder"))})
        elif bsize:
            blend_hash.setdefault(_hash(blend, bsize), []).append(mid)
        if mid not in sel:
            continue
        thumb = _size(os.path.join(d, "thumb.png"))
        src = e.get("source") or ""
        ssize = _size(src) if src else 0
        folder = M._clean(e.get("folder"))
        totals["models"] += 1
        totals["blend"] += bsize
        totals["textures"] += tsize
        totals["texFiles"] += tcount
        totals["thumbs"] += thumb
        if src:
            if ssize:
                totals["sources"] += ssize
                totals["sourceFiles"] += 1
            else:
                totals["sourceMissing"] += 1
        f = per_folder.setdefault(folder, {"folder": folder, "models": 0, "bytes": 0, "textures": 0})
        f["models"] += 1
        f["bytes"] += bsize + tsize + thumb
        f["textures"] += tsize
        per_model.append({"id": mid, "name": e.get("name", mid), "folder": folder, "blend": bsize, "textures": tsize,
                          "texFiles": tcount, "bytes": bsize + tsize + thumb})

    suggestions = []
    with JOB["lock"]:
        JOB.update(done=len(entries), phase=tr("Ricerca dei duplicati"))
    # 1. identical textures in several models
    by_size = {}
    for mid, p, s in tex_all:
        if s > 64 * 1024:
            by_size.setdefault(s, []).append((mid, p))
    groups, wasted = [], 0
    for s, items in by_size.items():
        if len({m for m, _ in items}) < 2:
            continue
        by_hash = {}
        for mid, p in items:
            h = _hash(p, s)
            if h:
                by_hash.setdefault(h, []).append((mid, p))
        for h, same in by_hash.items():
            ms = sorted({m for m, _ in same})
            if len(ms) > 1:
                groups.append({"file": os.path.basename(same[0][1]), "bytes": s, "copies": len(same),
                               "models": [entries[m].get("name", m) for m in ms if m in entries][:8]})
                wasted += s * (len(same) - 1)
    if groups:
        groups.sort(key=lambda g: -g["bytes"] * (g["copies"] - 1))
        suggestions.append({"kind": "dupTextures", "bytes": wasted, "count": len(groups), "items": groups[:30],
                            "title": tr("Texture uguali in più modelli"),
                            "text": tr("La stessa texture è copiata nella cartella di ogni modello che la usa (per esempio una collezione importata a pezzi, o lo stesso materiale su più modelli). Non è un errore: ogni modello resta indipendente. Se lo spazio conta, conviene tenere questi modelli in una sola collezione."),
                            "action": ""})
    # 2. the same model saved twice
    dup_models = [[{"id": m, "name": entries[m].get("name", m), "folder": M._clean(entries[m].get("folder"))} for m in ms]
                  for h, ms in blend_hash.items() if h and len(ms) > 1]
    if dup_models:
        b = sum(_size(os.path.join(lib, g[1]["id"], "model.blend")) * (len(g) - 1) for g in dup_models)
        suggestions.append({"kind": "dupModels", "bytes": b, "count": len(dup_models), "items": dup_models[:30],
                            "title": tr("Modelli salvati due volte"),
                            "text": tr("Questi modelli hanno lo stesso identico file: probabilmente sono stati importati o salvati due volte. Puoi eliminare la copia che non ti serve dalla libreria (tasto destro sul modello)."),
                            "action": ""})
    # 3. copies kept by the material fixes
    with JOB["lock"]:
        JOB.update(done=len(entries) + 2, phase=tr("Copie di sicurezza e cache"))
    broot = matbulk._backup_root()
    runs = []
    for r in sorted(os.listdir(broot)):
        p = os.path.join(broot, r)
        if not os.path.isdir(p):
            continue
        size, _ = _tree_size(p)
        info = {}
        try:
            with open(os.path.join(p, "run.json"), encoding="utf-8") as f:
                info = json.load(f)
        except (OSError, ValueError):
            pass
        runs.append({"run": r, "bytes": size, "when": info.get("when", r), "models": len(info.get("ids") or []),
                     "restored": bool(info.get("restored"))})
    if runs:
        suggestions.append({"kind": "backups", "bytes": sum(r["bytes"] for r in runs), "count": len(runs), "items": runs,
                            "title": tr("Copie di sicurezza di «Correggi materiali»"),
                            "text": tr("Prima di ogni correzione Simpler tiene una copia dei modelli com'erano (non si vede nella libreria). Se le correzioni ti vanno bene, puoi eliminarle: non potrai più usare «Ripristina» per quelle correzioni."),
                            "action": "backups"})
    # 4. texture folders of models deleted from the library
    orphans = []
    for f in sorted(os.listdir(lib)):
        p = os.path.join(lib, f)
        if f.startswith("m_") and os.path.isdir(p) and f not in entries:
            size, n = _tree_size(p)
            if size:
                orphans.append({"id": f, "bytes": size, "files": n})
    if orphans:
        suggestions.append({"kind": "orphans", "bytes": sum(o["bytes"] for o in orphans), "count": len(orphans), "items": orphans,
                            "title": tr("Texture di modelli eliminati"),
                            "text": tr("Quando elimini un modello dalla libreria le sue texture restano, perché le copie già messe nei progetti le leggono da lì. Eliminale solo se sei sicuro che nessun progetto salvato usi quei modelli: altrimenti quei progetti si riapriranno con i materiali rosa."),
                            "action": "orphans", "warning": True})
    # 5. broken models (no model.blend)
    if broken:
        suggestions.append({"kind": "broken", "bytes": 0, "count": len(broken), "items": broken,
                            "title": tr("Modelli senza file"),
                            "text": tr("Questi modelli sono nella libreria ma il loro file non c'è (un import interrotto, o cancellato fuori da Simpler): non si possono inserire. Puoi toglierli dall'elenco."),
                            "action": "broken"})
    # 6. caches Simpler makes again by itself
    caches = []
    for key, d in (("viewcache", render.view_cache_dir()), ("texcache", proxies.cache_dir())):
        size, n = _tree_size(d)
        if size:
            caches.append({"id": key, "bytes": size, "files": n})
    if caches:
        suggestions.append({"kind": "caches", "bytes": sum(c["bytes"] for c in caches), "count": len(caches), "items": caches,
                            "title": tr("Cache della vista 3D e delle texture ridotte"),
                            "text": tr("Copie ridotte delle texture e scene già preparate per la vista 3D: servono solo a fare prima, Simpler le rifà quando servono (la prima apertura dei progetti sarà un po' più lenta). Quelle usate dalla scena aperta restano."),
                            "action": "caches"})
    # 7. very big textures (information: the views use reduced copies anyway)
    if res["8k"] + res["4k"] > 0:
        suggestions.append({"kind": "bigTextures", "bytes": res["big_bytes"], "count": res["8k"] + res["4k"], "items": [],
                            "title": tr("Texture molto grandi (4K e 8K)"),
                            "text": tr("{0} texture da 8K e {1} da 4K. La vista 3D ne usa comunque copie ridotte; nel render finale servono solo per oggetti molto vicini alla camera. Non c'è niente da fare: è un'informazione per scegliere i modelli.", res["8k"], res["4k"]),
                            "action": ""})
    # textures packed inside the model file (no textures folder, a big .blend): normal for some imports, worth knowing
    packed = [m for m in per_model if m["texFiles"] == 0 and m["blend"] > 50e6]
    if packed:
        packed.sort(key=lambda m: -m["blend"])
        suggestions.append({"kind": "packed", "bytes": sum(m["blend"] for m in packed), "count": len(packed),
                            "items": [{"name": m["name"], "folder": m["folder"], "bytes": m["blend"]} for m in packed[:30]],
                            "title": tr("Modelli con le texture dentro il file"),
                            "text": tr("Questi modelli non hanno una cartella di texture: le texture sono incorporate nel file del modello (succede con alcuni formati e pacchetti). Funzionano lo stesso; il loro peso è contato nei file dei modelli."),
                            "action": ""})
    # other places Simpler keeps files (information)
    other = []
    for key, label in (("phTextures", tr("Materiali Poly Haven scaricati")), ("phModels", tr("Modelli Poly Haven scaricati"))):
        try:
            d = paths.get(key)
        except Exception:
            d = ""
        if d and os.path.isdir(d):
            size, n = _tree_size(d)
            other.append({"label": label, "bytes": size, "files": n, "dir": d})
    per_model.sort(key=lambda m: -m["bytes"])
    return {"totals": totals, "folders": sorted(per_folder.values(), key=lambda f: -f["bytes"]), "biggest": per_model[:12],
            "exts": sorted(({"ext": k, "bytes": v} for k, v in exts.items()), key=lambda x: -x["bytes"]),
            "res": res, "suggestions": suggestions, "other": other, "library": lib, "all": chosen is None}


def run(data):
    """POST libstats/run {folders: [..]} (none = the whole library)."""
    chosen = data.get("folders")
    chosen = None if chosen is None or data.get("all") else [str(f).strip("/") for f in chosen]
    with JOB["lock"]:
        if JOB["state"] == "running":
            raise ApiError(tr("Le statistiche sono già in calcolo"))
        JOB.update(state="running", done=0, total=0, phase="", result=None, error="")

    def work():
        t0 = time.time()
        try:
            r = _scan(chosen)
            with JOB["lock"]:
                JOB.update(state="done", result=r)
        except Exception as exc:
            with JOB["lock"]:
                JOB.update(state="error", error=str(exc))
        log("SIMPLER_LIBSTATS", f"{time.time() - t0:.1f}s", JOB["error"])

    threading.Thread(target=work, daemon=True).start()
    return status()


def status(_data=None):
    with JOB["lock"]:
        out = {k: JOB[k] for k in ("state", "done", "total", "phase", "error")}
        if JOB["state"] == "done":
            out["result"] = JOB["result"]
    return out


def _images_in_use():
    used = set()
    for im in bpy.data.images:
        if im.source in ("FILE", "TILED") and im.filepath:
            used.add(os.path.normcase(os.path.abspath(bpy.path.abspath(im.filepath))))
    return used


def clean(data):
    """POST libstats/clean {action: backups|orphans|broken|caches, ids: [...]}: frees the space of a suggestion."""
    from . import models as M, render, proxies, matbulk
    action, ids = data.get("action"), set(data.get("ids") or [])
    freed, n = 0, 0
    if action == "backups":
        root = matbulk._backup_root()
        for r in os.listdir(root):
            p = os.path.join(root, r)
            if os.path.isdir(p) and (not ids or r in ids):
                freed += _tree_size(p)[0]
                shutil.rmtree(p, ignore_errors=True)
                n += 1
    elif action == "orphans":
        lib = M.user_dir()
        entries = M._entries()
        used = _images_in_use()
        for f in os.listdir(lib):
            p = os.path.join(lib, f)
            if not (f.startswith("m_") and os.path.isdir(p) and f not in entries and (not ids or f in ids)):
                continue
            if time.time() - os.path.getmtime(p) < 600:
                continue                              # (a model of the cloud arriving now: its json is written last)
            busy = any(os.path.normcase(os.path.join(dp, x)) in used for dp, _dn, fn in os.walk(p) for x in fn)
            if busy:
                continue                              # the scene open now shows them
            freed += _tree_size(p)[0]
            shutil.rmtree(p, ignore_errors=True)
            n += 1
    elif action == "broken":
        lib = M.user_dir()
        for mid, e in M._entries().items():
            # (1.78.4) never a model of the locked Simpler parts
            if M.is_locked(e.get("folder", "")):
                continue
            if (not ids or mid in ids) and not os.path.isfile(os.path.join(lib, mid, "model.blend")):
                M.delete({"id": mid})
                n += 1
    elif action == "caches":
        used = _images_in_use()
        keep = {os.path.normcase(os.path.abspath(render.PREVIEW.get("path") or ""))}
        for key, d in (("viewcache", render.view_cache_dir()), ("texcache", proxies.cache_dir())):
            if ids and key not in ids:
                continue
            for dp, _dn, fn in os.walk(d):
                for f in fn:
                    p = os.path.join(dp, f)
                    np_ = os.path.normcase(os.path.abspath(p))
                    if np_ in used or np_ in keep:
                        continue
                    s = _size(p)
                    try:
                        os.remove(p)
                        freed += s
                        n += 1
                    except OSError:
                        pass
        with proxies._lock:
            proxies.READY.clear()
        proxies._SEEN.clear() if hasattr(proxies, "_SEEN") else None
    else:
        raise ApiError(tr("Azione sconosciuta"))
    log("SIMPLER_LIBSTATS", "clean", action, n, f"{freed / 1e6:.0f} MB")
    return {"action": action, "count": n, "bytes": freed}
