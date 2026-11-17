"""The textures of a project travel with it (1.68.2).

A picture applied from a folder that may be emptied (Downloads, the desktop, the folder of an imported model) was
used where it was: moved or deleted, the project lost it without a word. Now:

- saving (project_save, not the automatic copy): every image used by the project that is outside the safe places
  (the library folders, the folders of Simpler, the project's own folder) is copied into «<project> texture» next
  to the project, and the project points to the copy. The same file is copied once (also between saves: a copy
  already there with the same size and start is used again). The option «copyTextures» of the project (on by
  default) turns it off.
- opening (project_open): images that are not where they were are looked for by file name in the project's folders,
  the libraries and the folders the user pointed to before; the ones found are linked again, the others are
  unplugged (the material keeps name, colour and settings: textures.disconnect) and listed for the app, which asks
  for a folder (searched with its subfolders).
"""
import hashlib
import os

import bpy

from . import paths, proxies, textures
from .core import log

FOLDER_SUFFIX = " texture"


def folder_for(project_path):
    base = os.path.splitext(os.path.basename(project_path))[0]
    return os.path.join(os.path.dirname(os.path.abspath(project_path)), base + FOLDER_SUFFIX)


def _norm(p):
    return os.path.normcase(os.path.normpath(os.path.abspath(p))) if p else ""


def _under(path, root):
    n, r = _norm(path), _norm(root)
    return bool(r) and (n == r or n.startswith(r.rstrip("\\/") + os.sep))


def _safe_roots(project_path):
    roots = [os.path.dirname(os.path.abspath(project_path))]
    for key in paths.KEYS:
        try:
            roots.append(paths.get(key))
        except OSError:
            pass
    try:
        roots.append(os.path.dirname(paths.get("materials")))        # %APPDATA%\Simpler (decals, ground...)
        roots.append(os.path.join(paths._localappdata(), "Simpler"))  # caches, ground, previews
    except Exception:
        pass
    roots.append(proxies.cache_dir())
    try:
        from . import ambience
        roots.append(ambience._tex_dir())                            # the grounds Simpler makes
    except Exception:
        pass
    roots.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))   # the engine (its own pictures)
    return [r for r in roots if r]


def _sig(path):
    """Size and the first megabyte: the same picture (a copy made at an earlier save)."""
    try:
        with open(path, "rb") as f:
            head = f.read(1 << 20)
        return os.path.getsize(path), hashlib.sha1(head).hexdigest()
    except OSError:
        return None


def _images():
    """The original images the project uses (also those shown through a reduced copy, kept by a fake user)."""
    out = []
    for im in bpy.data.images:
        if im.source not in ("FILE", "TILED") or im.packed_file is not None or im.get(proxies.PROXY_TAG):
            continue
        if im.get("simpler_refcaustics_img"):
            continue                    # (Simpler's own light of the water, made again: not the project's to copy)
        if not im.filepath or not (im.users or im.use_fake_user):
            continue
        out.append(im)
    return out


def collect(project_path):
    """Copies the images outside the safe places next to the project; returns (copied files, bytes)."""
    import shutil
    safe = _safe_roots(project_path)
    dest = folder_for(project_path)
    done, copied, size = {}, 0, 0
    for im in _images():
        src = bpy.path.abspath(im.filepath)
        if im.source == "TILED" or not os.path.isfile(src) or any(_under(src, r) for r in safe):
            continue
        key = _norm(src)
        if key not in done:
            os.makedirs(dest, exist_ok=True)
            name = os.path.basename(src)
            stem, ext = os.path.splitext(name)
            target, n = os.path.join(dest, name), 1
            sig = None
            while os.path.exists(target):
                sig = sig or _sig(src)
                if _sig(target) == sig:
                    break                                       # (the same picture, copied before)
                n += 1
                target = os.path.join(dest, f"{stem}_{n}{ext}")
            if not os.path.exists(target):
                shutil.copyfile(src, target + ".part")
                os.replace(target + ".part", target)
                copied += 1
                size += os.path.getsize(target)
            done[key] = target
        im.filepath = done[key]
        proxies.forget(im.name)                                # (the source of its reduced copies: the new file)
    if copied:
        log("SIMPLER_PROJTEX", f"{copied} textures ({size / 1e6:.0f} MB) copied to {dest}")
    return copied, size


def check_missing(project_path, extra_folders=()):
    """After opening: the images not found where they were, looked for in the project's folders, the libraries and
    the folders given; returns (found names, missing file names)."""
    missing = [im for im in _images() if textures.is_missing(im)]
    if not missing:
        return [], []
    folders = []
    if project_path:
        tex = folder_for(project_path)
        if os.path.isdir(tex):
            folders.append((tex, 6))
        folders.append((os.path.dirname(os.path.abspath(project_path)), 3))
    for key in ("materials", "phTextures", "models", "phModels"):
        try:
            folders.append((paths.get(key), 6))
        except OSError:
            pass
    for f in extra_folders or ():
        if f and os.path.isdir(f):
            folders.append((f, 6))
    found, still = textures.resolve(missing, folders)
    log("SIMPLER_PROJTEX", f"missing textures at opening: {len(missing)}, found again {len(found)}, still missing {len(still)}")
    return found, still
