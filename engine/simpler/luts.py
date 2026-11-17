"""Colour looks (3D LUT) for the camera effects (post.py): Simpler's own presets and the .cube files of the user.

- Simpler's presets are formulas on the display values (lift, gamma, gain per channel, split toning, contrast,
  saturation): the table (33 x 33 x 33) is computed when first used. Nothing to license.
- The user's LUTs: .cube files (also inside .zip archives) imported into %APPDATA%\\Simpler\\luts, grouped by the
  folder or archive they came from. Ids: "simpler/<name>" and "user/<path inside luts>".
- Favourites (the black heart of the panel): %APPDATA%\\Simpler\\luts\\favorites.json, for every project.

A table is an array (n, n, n, 3) indexed [b, g, r] (the order of the .cube files: red changes fastest), values
0..1 on display values; apply() samples it with trilinear interpolation, as the real-time view does with its 3D
texture.
"""
import json
import os
import re
import shutil
import zipfile

from .core import ApiError
from .i18n import tr

SIZE = 33

# ---------------------------------------------------------------- Simpler's presets

_W = (0.2126, 0.7152, 0.0722)


def _lum(x):
    return x[..., 0] * _W[0] + x[..., 1] * _W[1] + x[..., 2] * _W[2]


def _sat(x, s):
    y = _lum(x)[..., None]
    return y + (x - y) * s


def _contrast(x, c):
    import numpy as np
    x = np.clip(x, 0.0, 1.0)
    return x + c * (x * x * (3.0 - 2.0 * x) - x)


def _lgg(x, lift=(0, 0, 0), gamma=(1, 1, 1), gain=(1, 1, 1)):
    import numpy as np
    x = np.clip(x, 0.0, 1.0)
    lift, gamma, gain = np.array(lift, np.float64), np.array(gamma, np.float64), np.array(gain, np.float64)
    x = x * (1.0 - lift) + lift
    return np.clip(x, 0.0, None) ** (1.0 / gamma) * gain


def _split(x, shadows=(0.5, 0.5, 0.5), highlights=(0.5, 0.5, 0.5), amount=0.2, balance=0.0):
    """Split toning: the dark tones towards one colour, the light ones towards another (0.5 = no tint)."""
    import numpy as np
    y = np.clip(_lum(x) + balance, 0.0, 1.0)[..., None]
    s = np.array(shadows, np.float64) - 0.5
    h = np.array(highlights, np.float64) - 0.5
    return x + amount * ((1.0 - y) ** 2 * s + y ** 2 * h)


def _vibrance(x, v):
    import numpy as np
    mx, mn = x.max(axis=-1, keepdims=True), x.min(axis=-1, keepdims=True)
    sat = mx - mn
    return _sat(x, 1.0 + v * (1.0 - np.clip(sat, 0, 1)))


def _mono(x, tint=(1.0, 1.0, 1.0)):
    import numpy as np
    y = _lum(np.clip(x, 0, 1))[..., None]
    return y * np.array(tint, np.float64)


def _fade(x, black=0.06, white=0.95):
    return black + x * (white - black)


PRESETS = [
    # id, Italian name, recipe
    ("pellicola-calda", "Pellicola calda", lambda x: _fade(_split(_sat(_contrast(_lgg(x, gain=(1.04, 1.0, 0.92)), 0.25), 0.9),
                                                                   (0.45, 0.52, 0.55), (0.62, 0.52, 0.4), 0.25), 0.03, 0.98)),
    ("pellicola-fredda", "Pellicola fredda", lambda x: _fade(_split(_sat(_contrast(_lgg(x, gain=(0.94, 1.0, 1.06)), 0.25), 0.88),
                                                                     (0.42, 0.5, 0.6), (0.52, 0.53, 0.55), 0.25), 0.03, 0.98)),
    ("teal-orange", "Teal & orange", lambda x: _split(_sat(_contrast(x, 0.2), 1.08), (0.32, 0.55, 0.62), (0.68, 0.52, 0.36), 0.35)),
    ("cinema", "Cinematografico", lambda x: _split(_sat(_contrast(x, 0.35), 0.95), (0.4, 0.52, 0.58), (0.6, 0.53, 0.45), 0.22)),
    ("architettura", "Architettura pulita", lambda x: _split(_sat(_contrast(x, 0.12), 0.92), (0.47, 0.5, 0.54), (0.51, 0.5, 0.49), 0.12)),
    ("vivido", "Vivido naturale", lambda x: _vibrance(_contrast(x, 0.1), 0.35)),
    ("oro", "Luce dorata", lambda x: _split(_sat(_lgg(x, gain=(1.07, 1.0, 0.84)), 1.04), (0.52, 0.5, 0.46), (0.64, 0.56, 0.4), 0.25)),
    ("notte", "Notte blu", lambda x: _sat(_lgg(x, gamma=(0.88, 0.9, 1.0), gain=(0.84, 0.92, 1.1)), 0.7)),
    ("sbiadito", "Sbiadito", lambda x: _fade(_sat(_contrast(x, -0.25), 0.8), 0.09, 0.93)),
    ("vintage", "Vintage", lambda x: _fade(_split(_sat(_contrast(x, 0.12), 0.82), (0.48, 0.56, 0.46), (0.6, 0.57, 0.46), 0.3), 0.05, 0.96)),
    ("istantanea", "Istantanea", lambda x: _fade(_split(_sat(x, 0.88), (0.4, 0.56, 0.58), (0.64, 0.54, 0.44), 0.3), 0.07, 0.95)),
    ("bn", "Bianco e nero", lambda x: _contrast(_mono(x), 0.1)),
    ("bn-contrasto", "Bianco e nero contrastato", lambda x: _contrast(_contrast(_mono(x), 0.6), 0.3)),
    ("seppia", "Seppia", lambda x: _contrast(_mono(x, (1.08, 0.98, 0.8)), 0.12)),
]
_BY_ID = {p[0]: p for p in PRESETS}


def _grid(n):
    import numpy as np
    v = np.linspace(0.0, 1.0, n)
    b, g, r = np.meshgrid(v, v, v, indexing="ij")
    return np.stack([r, g, b], axis=-1)            # [b, g, r, (r, g, b)]


def _preset_table(pid, n=SIZE):
    import numpy as np
    return np.clip(_BY_ID[pid][2](_grid(n)), 0.0, 1.0).astype(np.float32)


# ---------------------------------------------------------------- .cube files

def parse_cube(text):
    """A 3D LUT from the text of a .cube file -> array (n, n, n, 3) [b, g, r]. 1D LUTs are not supported."""
    import numpy as np
    n, lo, hi, rows = 0, [0.0, 0.0, 0.0], [1.0, 1.0, 1.0], []
    for line in text.splitlines():
        s = line.strip()
        if not s or s.startswith("#"):
            continue
        up = s.upper()
        if up.startswith("LUT_3D_SIZE"):
            n = int(s.split()[1])
        elif up.startswith("LUT_1D_SIZE"):
            raise ValueError("1D LUT")
        elif up.startswith("DOMAIN_MIN"):
            lo = [float(v) for v in s.split()[1:4]]
        elif up.startswith("DOMAIN_MAX"):
            hi = [float(v) for v in s.split()[1:4]]
        elif up.startswith("TITLE") or up[0].isalpha():
            continue
        else:
            p = s.split()
            if len(p) >= 3:
                rows.append((float(p[0]), float(p[1]), float(p[2])))
    if n < 2 or len(rows) != n ** 3:
        raise ValueError(f"size {n}, {len(rows)} rows")
    t = np.array(rows, dtype=np.float32).reshape(n, n, n, 3)
    if lo != [0.0, 0.0, 0.0] or hi != [1.0, 1.0, 1.0]:
        t = (t - np.array(lo, np.float32)) / np.maximum(np.array(hi, np.float32) - np.array(lo, np.float32), 1e-6)
    return np.clip(t, 0.0, 1.0)


def apply(px, table, amount=1.0):
    """px: float array (..., 3) of display values 0..1 -> the LUT applied (trilinear), mixed by amount. In blocks
    of 256k pixels on several threads (numpy lets them run together): a 4K picture 4 s -> 1.5 s on 2 cores."""
    import numpy as np
    from concurrent.futures import ThreadPoolExecutor
    n = table.shape[0]
    T = np.ascontiguousarray(table.reshape(-1, 3), dtype=np.float32)
    flat = np.ascontiguousarray(px, dtype=np.float32).reshape(-1, 3)
    out = np.empty_like(flat)
    offs = (0, 1, n, n + 1, n * n, n * n + 1, n * n + n, n * n + n + 1)
    step = 1 << 18
    k = float(amount)

    def block(s):
        src = flat[s:s + step]
        x = np.clip(src, 0.0, 1.0) * (n - 1)
        i0 = np.minimum(x.astype(np.int32), n - 2)
        f = x - i0
        base = (i0[:, 2] * n + i0[:, 1]) * n + i0[:, 0]
        fr, fg, fb = f[:, 0:1], f[:, 1:2], f[:, 2:3]
        c = [np.take(T, base + o, axis=0) for o in offs]
        c00 = c[0] + (c[1] - c[0]) * fr
        c01 = c[2] + (c[3] - c[2]) * fr
        c10 = c[4] + (c[5] - c[4]) * fr
        c11 = c[6] + (c[7] - c[6]) * fr
        a0 = c00 + (c01 - c00) * fg
        a1 = c10 + (c11 - c10) * fg
        r = a0 + (a1 - a0) * fb
        out[s:s + step] = r if k >= 0.999 else src + (r - src) * k
    starts = range(0, len(flat), step)
    if len(flat) <= step:
        for s in starts:
            block(s)
    else:
        with ThreadPoolExecutor(max(1, min(8, os.cpu_count() or 2))) as ex:
            list(ex.map(block, starts))
    return out.reshape(np.shape(px))


# ---------------------------------------------------------------- the library

def user_dir():
    from .paths import _appdata
    d = os.path.join(_appdata(), "Simpler", "luts")
    os.makedirs(d, exist_ok=True)
    return d


def _fav_file():
    return os.path.join(user_dir(), "favorites.json")


def favorites():
    try:
        with open(_fav_file(), encoding="utf-8") as f:
            v = json.load(f)
        return [str(x) for x in v] if isinstance(v, list) else []
    except (OSError, ValueError):
        return []


def _user_items():
    root = user_dir()
    out = []
    for dirpath, _dirs, files in os.walk(root):
        for fn in files:
            if not fn.lower().endswith(".cube"):
                continue
            rel = os.path.relpath(os.path.join(dirpath, fn), root).replace("\\", "/")
            group = os.path.dirname(rel) or tr("Importati")
            out.append({"id": "user/" + rel, "name": os.path.splitext(fn)[0].replace("_", " "), "group": group, "user": True})
    out.sort(key=lambda it: (it["group"].lower(), it["name"].lower()))
    return out


def library(_data=None):
    """GET /api/luts -> {items: [{id, name, group, fav, user}], favorites: [ids]}."""
    favs = favorites()
    items = [{"id": "simpler/" + pid, "name": tr(name), "group": "Simpler", "user": False} for pid, name, _f in PRESETS]
    items += _user_items()
    for it in items:
        it["fav"] = it["id"] in favs
    return {"items": items, "favorites": favs}


def set_favorite(data):
    """POST /api/luts/favorite {id, on}."""
    lid = str(data.get("id") or "")
    if not lid:
        raise ApiError(tr("LUT non trovata"))
    favs = [f for f in favorites() if f != lid]
    if data.get("on", True):
        favs.append(lid)
    p = _fav_file()
    with open(p + ".part", "w", encoding="utf-8") as f:
        json.dump(favs, f, indent=1)
    os.replace(p + ".part", p)
    return library()


def _safe(name):
    return re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", name).strip(" .") or "LUT"


def import_files(data):
    """POST /api/luts/import {paths: [.cube files, .zip archives or folders]}: copied into the user's folder (a folder
    or archive becomes a group with its name). Files that are not valid 3D LUTs are skipped."""
    root = user_dir()
    done, bad = 0, 0
    for p in data.get("paths") or []:
        if os.path.isdir(p):
            group = _safe(os.path.basename(os.path.normpath(p)))
            for dirpath, _d, files in os.walk(p):
                for fn in files:
                    if fn.lower().endswith(".cube"):
                        with open(os.path.join(dirpath, fn), "rb") as f:
                            ok = _store(root, group, fn, f.read())
                        done, bad = done + ok, bad + (not ok)
        elif p.lower().endswith(".zip") and os.path.isfile(p):
            group = _safe(os.path.splitext(os.path.basename(p))[0])
            with zipfile.ZipFile(p) as z:
                for info in z.infolist():
                    if info.filename.lower().endswith(".cube") and not info.is_dir() and info.file_size < 64 * 1024 * 1024:
                        ok = _store(root, group, os.path.basename(info.filename), z.read(info))
                        done, bad = done + ok, bad + (not ok)
        elif p.lower().endswith(".cube") and os.path.isfile(p):
            with open(p, "rb") as f:
                ok = _store(root, tr("Importati"), os.path.basename(p), f.read())
            done, bad = done + ok, bad + (not ok)
    _CACHE.clear()
    _THUMBS.clear()
    out = library()
    out.update(imported=done, skipped=bad)
    return out


def _store(root, group, fn, raw):
    try:
        parse_cube(raw.decode("utf-8", "replace"))
    except (ValueError, IndexError):
        return False
    d = os.path.join(root, _safe(group))
    os.makedirs(d, exist_ok=True)
    with open(os.path.join(d, _safe(fn)), "wb") as f:
        f.write(raw)
    return True


def delete(data):
    """POST /api/luts/delete {id} (an imported LUT) or {group} (all the LUTs of an imported group)."""
    root = user_dir()
    if data.get("group"):
        d = os.path.normpath(os.path.join(root, data["group"]))
        if os.path.dirname(d) == os.path.normpath(root) and os.path.isdir(d):
            shutil.rmtree(d, ignore_errors=True)
    else:
        lid = str(data.get("id") or "")
        p = _user_path(lid)
        if p and os.path.isfile(p):
            os.remove(p)
            try:
                os.remove(os.path.join(os.path.dirname(p), ".cache", os.path.basename(p) + ".npy"))
            except OSError:
                pass
    _CACHE.clear()
    _THUMBS.clear()
    return library()


def _user_path(lid):
    if not lid.startswith("user/"):
        return ""
    root = os.path.normpath(user_dir())
    p = os.path.normpath(os.path.join(root, lid[5:]))
    return p if p.startswith(root + os.sep) else ""


_CACHE = {}


def table(lid):
    """The table of a LUT id (None when it does not exist any more: a project from another computer)."""
    if not lid:
        return None
    t = _CACHE.get(lid)
    if t is not None:
        return t
    try:
        if lid.startswith("simpler/") and lid[8:] in _BY_ID:
            t = _preset_table(lid[8:])
        else:
            p = _user_path(lid)
            if not p or not os.path.isfile(p):
                return None
            t = _read_user(p)
    except (OSError, ValueError):
        return None
    if len(_CACHE) > 64:
        _CACHE.clear()
    _CACHE[lid] = t
    return t


def _read_user(p):
    """An imported .cube, read once: a binary copy is kept next to it (reading the text of a 33^3 table takes
    50-100 ms, the copy 1 ms - the previews of many looks read them all)."""
    import numpy as np
    bin_ = os.path.join(os.path.dirname(p), ".cache", os.path.basename(p) + ".npy")
    try:
        if os.path.getmtime(bin_) >= os.path.getmtime(p):
            return np.load(bin_)
    except OSError:
        pass
    with open(p, encoding="utf-8", errors="replace") as f:
        t = parse_cube(f.read())
    try:
        os.makedirs(os.path.dirname(bin_), exist_ok=True)
        np.save(bin_, t)
    except OSError:
        pass
    return t


def table_bytes(lid):
    """GET /api/lut/table?id=: the table for the real-time view - 4 bytes (n), then n^3 RGB bytes [b][g][r]."""
    import numpy as np
    t = table(lid)
    if t is None:
        return b""
    n = t.shape[0]
    return int(n).to_bytes(4, "little") + np.round(np.clip(t, 0, 1) * 255.0).astype(np.uint8).tobytes()


def _chart(w=128, h=80):
    """The picture of a look's thumbnail: the colours of the circle in light and shade above, a grey ramp below."""
    import numpy as np
    x = (np.arange(w) + 0.5) / w
    y = (np.arange(h) + 0.5) / h
    hue = x[None, :] * 6.0
    r = np.clip(np.abs(hue - 3.0) - 1.0, 0, 1)
    g = np.clip(2.0 - np.abs(hue - 2.0), 0, 1)
    b = np.clip(2.0 - np.abs(hue - 4.0), 0, 1)
    col = np.stack([r, g, b], -1).repeat(h, 0)                     # (h, w, 3)
    t = y[:, None, None]
    light = np.where(t < 0.5, 1.0 - (0.5 - t) * 1.6, 1.0)           # pale at the top
    shade = np.where(t >= 0.5, 1.0 - (t - 0.5) * 1.7, 1.0)          # dark at the bottom of the colours
    img = (col * 0.75 + 0.25 * (1 - light)) * shade * 0.9 + (1 - light) * 0.55
    ramp = int(h * 0.78)
    img[ramp:] = x[None, :, None].repeat(h - ramp, 0).repeat(3, 2)
    return np.clip(img, 0, 1).astype(np.float32)


def _png(img):
    import struct
    import zlib
    import numpy as np
    h, w = img.shape[:2]
    raw = b"".join(b"\x00" + row.tobytes() for row in np.round(np.clip(img, 0, 1) * 255).astype(np.uint8))

    def chunk(t, d):
        return struct.pack(">I", len(d)) + t + d + struct.pack(">I", zlib.crc32(t + d) & 0xFFFFFFFF)
    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 2, 0, 0, 0))
            + chunk(b"IDAT", zlib.compress(raw, 6)) + chunk(b"IEND", b""))


_SRC = {"key": "", "img": None}
_THUMBS = {}


def set_source(data):
    """POST /api/lut/source {w, h, rgb: base64 of w*h*3 bytes}: the small picture of the view the previews of the
    looks are made from (the app takes it when the list opens). Returns {key} for the URLs of the previews."""
    import base64
    import hashlib
    import numpy as np
    w, h = int(data.get("w") or 0), int(data.get("h") or 0)
    raw = base64.b64decode(data.get("rgb") or "")
    if w <= 0 or h <= 0 or len(raw) != w * h * 3 or w * h > 640 * 640:
        raise ApiError(tr("Immagine non valida"))
    key = hashlib.sha1(raw).hexdigest()[:12]
    if key != _SRC["key"]:
        _SRC.update(key=key, img=np.frombuffer(raw, np.uint8).reshape(h, w, 3).astype(np.float32) / 255.0)
        _THUMBS.clear()
    return {"key": key}


def thumb_png(lid, key=""):
    """GET /api/lut/thumb?id=&k=: the look applied to the picture of the view (set_source) - or, without one, to a
    chart of colours and greys (PNG)."""
    ck = (lid, key if key and key == _SRC["key"] else "")
    got = _THUMBS.get(ck)
    if got is not None:
        return got
    t = table(lid) if lid else None
    if t is None and lid:
        return b""
    src = _SRC["img"] if ck[1] else _chart()
    out = _png(apply(src, t) if t is not None else src)             # (no id: the picture as it is - «Nessuno»)
    if len(_THUMBS) > 400:
        _THUMBS.clear()
    _THUMBS[ck] = out
    return out
