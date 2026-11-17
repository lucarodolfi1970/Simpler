"""The folders next to a project, kept in order (1.76.7).

A project «X.simpler» has folders of its own next to it: «X texture» (pictures copied in by projtex), «X - Video AI»
(the keyframes of the AI video), «X AI» (the AI results: the app keeps that one). Before, saving another scene over
X added its files to the old ones (textures, keyframes) and nothing was ever taken away.

- every real save (not the automatic copy): in «X texture» and «X - Video AI/frames» the files the project does not
  use go to the Recycle Bin - except the ones the save before used (the backup «X.simpler1» may still need them).
  Which files a save used is written in the folder (TRACK). A folder without it (made before 1.76.7): nothing is
  taken away the first time, only written down.
- «Salva con nome» over another project (overwrite_plan): the old project, its backup and automatic copy and the
  files of its folders go to the Recycle Bin first - except the ones the scene being saved uses (a scene opened from
  X uses the pictures in «X texture» where they are).

The engine says what; the app moves the files to the Recycle Bin (Windows: they can be taken back).
"""
import json
import os

import bpy

from .core import log

TRACK = ".simpler-files.json"
VIDEO_SUFFIX = " - Video AI"


def _norm(p):
    return os.path.normcase(os.path.normpath(os.path.abspath(p))) if p else ""


def texture_folder(project_path):
    from . import projtex
    return projtex.folder_for(project_path)


def frames_folder(project_path):
    base = os.path.splitext(os.path.basename(project_path))[0]
    return os.path.join(os.path.dirname(os.path.abspath(project_path)), base + VIDEO_SUFFIX, "frames")


def _used_images():
    """Absolute, normalised paths of the picture files the scene uses (originals, also through reduced copies)."""
    from . import projtex
    out = set()
    for im in projtex._images():
        try:
            out.add(_norm(bpy.path.abspath(im.filepath)))
        except Exception:
            pass
    return out


def _used_frames():
    from . import videoframes
    out = set()
    for f in videoframes._load().values():
        if isinstance(f, dict) and f.get("image"):
            out.add(_norm(f["image"]))
    return out


def _files(folder):
    try:
        return [os.path.join(folder, n) for n in os.listdir(folder)
                if n != TRACK and os.path.isfile(os.path.join(folder, n))]
    except OSError:
        return []


def _clean(folder, used):
    """The files of the folder neither this save nor the one before uses; writes down this save's."""
    if not os.path.isdir(folder):
        return []
    files = _files(folder)
    now = sorted(os.path.basename(f) for f in files if _norm(f) in used)
    track = os.path.join(folder, TRACK)
    prev, known = [], os.path.isfile(track)
    if known:
        try:
            with open(track, encoding="utf-8") as fh:
                prev = list(json.load(fh).get("now") or [])
        except (OSError, ValueError):
            known = False
    try:
        with open(track, "w", encoding="utf-8") as fh:
            json.dump({"now": now, "prev": prev}, fh)
    except OSError:
        return []
    if not known:
        return []                   # (a folder from before: its files may be used by the backup - left alone)
    keep = {n.lower() for n in now + prev}
    return [f for f in files if os.path.basename(f).lower() not in keep]


def after_save(project_path):
    """The files to move to the Recycle Bin after a real save of the project."""
    out = _clean(texture_folder(project_path), _used_images()) + _clean(frames_folder(project_path), _used_frames())
    if out:
        log("SIMPLER_PROJFILES", f"{len(out)} files no longer used by {os.path.basename(project_path)}")
    return out


def overwrite_plan(data):
    """POST project/overwrite {path}: saving the open scene over another project - what of the old one goes to the
    Recycle Bin first: the project, its backup and automatic copy, the files of its folders the scene does not use.
    -> {files: [...], folders: [...]} (folders: to take away when they are left empty)."""
    path = (data or {}).get("path") or ""
    if not path.lower().endswith(".simpler"):
        path += ".simpler"
    base = path[:-8]
    files = [p for p in (path, path + "1", base + ".autosave.simpler") if os.path.isfile(p)]
    used = _used_images() | _used_frames()
    folders = []
    for folder in (texture_folder(path), frames_folder(path)):
        if not os.path.isdir(folder):
            continue
        for f in _files(folder):
            if _norm(f) not in used:
                files.append(f)
        tr = os.path.join(folder, TRACK)
        if os.path.isfile(tr):
            files.append(tr)
        folders.append(folder)
    vf = os.path.dirname(frames_folder(path))
    if os.path.isdir(vf):
        folders.append(vf)
    return {"files": files, "folders": folders}
