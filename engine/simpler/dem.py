"""(1.76.25) Real elevation files as terrains (Luca: «i file .dem non possono esserci utili nei terreni?»).

- USGS DEM (.dem): the ASCII format of the US Geological Survey (7.5' quads, 10-30 m): a header record (A) with the
  units and the corners, then one profile (B) per column, each starting on a 1024-byte block, its heights as
  integers × the z resolution, in feet or metres. The quad is not square in its own grid: the part outside it is void.
- SRTM (.hgt): a square of big-endian 16-bit metres, 1201 or 3601 a side, 1 or 3 arc-seconds (-32768 = void).
- ESRI ASCII grid (.asc): ncols, nrows, cellsize, NODATA_value, then the rows from the north.

read(path) -> (heights in metres, rows from the north, NaN where void; cell size in metres). Pure numpy: no GDAL.
"""
import math
import os

import numpy as np

EXTS = (".dem", ".hgt", ".asc")


def _num(t):
    return float(t.replace("D", "E").replace("d", "e"))


def _usgs(path):
    raw = open(path, "rb").read()
    a = raw[:1024].decode("latin-1")
    f = lambda i, j: a[i - 1:j]
    xy_units = int(f(529, 534) or 2)                 # 0 radians, 1 feet, 2 metres, 3 arc-seconds
    z_units = int(f(535, 540) or 2)                  # 1 feet, 2 metres
    res = f(817, 852)
    try:
        dx, dy, dz = (float(res[k * 12:(k + 1) * 12].replace("D", "E")) for k in range(3))
    except ValueError:
        dx, dy, dz = 30.0, 30.0, 1.0
    cols = int(f(859, 864))
    if xy_units == 3:                                # (arc-seconds: metres at the latitude of the quad)
        lat = 0.0
        try:
            corners = [_num(t) for t in f(547, 738).split()]
            lat = sum(corners[1::2]) / 4.0 / 3600.0
        except (ValueError, ZeroDivisionError):
            pass
        sx, sy = dx * 30.87 * math.cos(math.radians(lat)), dy * 30.87
    else:
        k = 0.3048 if xy_units == 1 else 1.0
        sx, sy = dx * k, dy * k
    zk = (0.3048 if z_units == 1 else 1.0) * (dz or 1.0)
    profiles = []
    pos = 1024
    while len(profiles) < cols and pos < len(raw):
        # one profile: from the start of a block, the header of 9 numbers then m heights, on as many blocks as needed
        toks = []
        block = pos
        need = None
        while block < len(raw):
            toks.extend(raw[block:block + 1024].decode("latin-1").split())
            block += 1024
            if need is None and len(toks) >= 9:
                need = 9 + int(toks[2]) * int(toks[3])
            if need is not None and len(toks) >= need:
                break
        if need is None or len(toks) < need:
            break
        y0 = _num(toks[5])
        z = np.array([int(t) for t in toks[9:need]], dtype=np.float64)
        profiles.append((int(toks[1]), y0, z))
        pos = block
    if not profiles:
        raise ValueError("no profiles")
    k_y = 0.3048 if xy_units == 1 else 1.0
    ys = [p[1] * k_y for p in profiles]
    y_lo = min(ys)
    rows = int(round(max(p[1] * k_y + (len(p[2]) - 1) * sy for p in profiles) - y_lo) / sy) + 1
    out = np.full((rows, len(profiles)), np.nan)
    for j, (_c, y0, z) in enumerate(profiles):
        i0 = int(round((y0 * k_y - y_lo) / sy))
        v = np.where(z <= -32767, np.nan, z * zk)
        out[i0:i0 + len(v), j] = v[:max(0, rows - i0)]
    return out[::-1], (sx + sy) / 2.0                # (rows from the north)


def _hgt(path):
    n = int(round(math.sqrt(os.path.getsize(path) / 2)))
    a = np.fromfile(path, dtype=">i2").astype(np.float64)
    if a.size != n * n:
        raise ValueError("not square")
    a = a.reshape(n, n)
    a[a <= -32767] = np.nan
    arc = 1.0 if n > 2000 else 3.0
    lat = 0.0
    name = os.path.basename(path).upper()
    try:
        lat = (1 if name[0] == "N" else -1) * int(name[1:3]) + 0.5
    except (ValueError, IndexError):
        pass
    cell = arc * 30.87 * math.sqrt(math.cos(math.radians(lat)))     # (the mean of the two directions)
    return a, cell


def _asc(path):
    head, n = {}, 0
    with open(path, encoding="latin-1") as fh:
        while True:
            pos = fh.tell()
            line = fh.readline()
            parts = line.split()
            if len(parts) == 2 and parts[0].replace("_", "").isalpha():
                head[parts[0].lower()] = float(parts[1])
                n += 1
                continue
            fh.seek(pos)
            break
        data = np.array(fh.read().split(), dtype=np.float64)
    nc, nr = int(head["ncols"]), int(head["nrows"])
    a = data[:nc * nr].reshape(nr, nc)
    nd = head.get("nodata_value")
    if nd is not None:
        a[a == nd] = np.nan
    return a, float(head.get("cellsize", 30.0))


def _fill(a):
    """Voids filled from their neighbours (a few rounds of averaging), the rest with the lowest height."""
    a = a.copy()
    for _ in range(64):
        m = np.isnan(a)
        if not m.any():
            break
        p = np.pad(a, 1, mode="edge")
        nb = np.stack([p[:-2, 1:-1], p[2:, 1:-1], p[1:-1, :-2], p[1:-1, 2:]])
        cnt = np.sum(~np.isnan(nb), axis=0)
        s = np.nansum(nb, axis=0)
        fill = m & (cnt > 0)
        a[fill] = s[fill] / cnt[fill]
    a[np.isnan(a)] = np.nanmin(a) if np.isfinite(np.nanmin(a)) else 0.0
    return a


def _square(a):
    """The largest square with (almost) no void: a quad of the USGS is a slanted figure in its own grid."""
    valid = ~np.isnan(a)
    r = np.nonzero(valid.mean(axis=1) > 0.98)[0]
    c = np.nonzero(valid.mean(axis=0) > 0.98)[0]
    if len(r) and len(c):
        a = a[r[0]:r[-1] + 1, c[0]:c[-1] + 1]
    side = min(a.shape)
    i0, j0 = (a.shape[0] - side) // 2, (a.shape[1] - side) // 2
    return a[i0:i0 + side, j0:j0 + side]


def read(path):
    """-> (heights in metres, square, rows from the north, voids filled; cell size in metres)"""
    ext = os.path.splitext(path)[1].lower()
    if ext == ".dem":
        a, cell = _usgs(path)
    elif ext == ".hgt":
        a, cell = _hgt(path)
    elif ext == ".asc":
        a, cell = _asc(path)
    else:
        raise ValueError(ext)
    a = _square(a)
    return _fill(a), float(cell)


_INFO = {}
_READ = {}

# (1.76.34, Luca: «non ci serve portare 100 km di terreno») a big file: a square of it, chosen on its picture. The
# terrain keeps at most MAX_SIDE of it (the grid of the terrain has 512 points: at 10 km, one every 20 m)
MAX_SIDE = 10000.0
DEFAULT_SIDE = 5000.0


def read_cached(path):
    """read(), kept for the last file (a 100 km file takes a few seconds: the preview, the info and the terrain)."""
    key = (path, os.path.getmtime(path))
    if key not in _READ:
        _READ.clear()
        _READ[key] = read(path)
    return _READ[key]


def crop(a, c):
    """The square [x0, y0, side] (fractions of the file's side; x from the west, y from the north) of a (rows
    from the north). None or a bad one: the whole."""
    if not c or len(c) < 3:
        return a
    n = a.shape[0]
    try:
        x0, y0, side = (float(v) for v in c[:3])
    except (TypeError, ValueError):
        return a
    k = int(round(max(2.0 / n, min(1.0, side)) * (n - 1))) + 1
    i0 = int(round(max(0.0, min(1.0, y0)) * (n - 1)))
    j0 = int(round(max(0.0, min(1.0, x0)) * (n - 1)))
    i0, j0 = min(i0, n - k), min(j0, n - k)
    return a[i0:i0 + k, j0:j0 + k]


def info(path, c=None):
    """{size (m), height (m: from the lowest to the highest point), full (m: the whole file)} of an elevation file,
    or of its square c (crop)."""
    a, cell = read_cached(path)
    full = cell * (a.shape[0] - 1)
    b = crop(a, c)
    return {"size": round(cell * (b.shape[0] - 1), 1), "height": round(float(np.ptp(b)), 1),
            "min": float(b.min()), "cell": cell, "full": round(full, 1)}


def preview(d):
    """POST terrain/dem/preview {path}: the file as a shaded relief (PNG, base64, at most 512 a side, north up) for
    the window where its square is chosen, with its size, cell and relief."""
    import base64
    from .core import ApiError
    from .i18n import tr
    path = (d or {}).get("path") or ""
    if not path or not os.path.isfile(path):
        raise ApiError(tr("Mappa di altezze non trovata"))
    try:
        a, cell = read_cached(path)
    except Exception as exc:  # noqa: BLE001
        raise ApiError(tr("Questo file di quote non si legge: {0}", str(exc)[:120]))
    n = a.shape[0]
    step = max(1, int(math.ceil(n / 512)))
    b = a[::step, ::step]
    # shaded relief: light from the north-west, plus the height (low dark, high light)
    gy, gx = np.gradient(b, cell * step)
    shade = np.clip((-gx * 0.7071 + gy * 0.7071) * 1.5 + 0.55, 0.0, 1.0)
    hn = (b - b.min()) / max(1e-6, float(np.ptp(b)))
    v = np.clip(0.25 + 0.55 * shade + 0.25 * hn, 0.0, 1.0)
    rgb = np.stack([v * 0.92, v * 0.95, v], -1)
    from .ocean import _png
    png = _png(np.clip(rgb * 255 + 0.5, 0, 255).astype(np.uint8))
    full = cell * (n - 1)
    return {"png": base64.b64encode(png).decode("ascii"), "size": round(full, 1), "cell": cell,
            "height": round(float(np.ptp(a)), 1), "maxSide": min(full, MAX_SIDE), "defaultSide": min(full, DEFAULT_SIDE)}
