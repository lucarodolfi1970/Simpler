"""Neve scolpita: footprints, tyre tracks and the snow dug or heaped by hand (Neve > Avanzate > Scolpisci).

A map seen from above, in tiles of TILE x TILE pixels of PX metres (1.5 cm), only where something was done: two
channels per pixel, D (metres added to the snow: below 0 dug, above 0 heaped) and C (how pressed the snow is: 0..1,
for the colour of the trodden snow, and under footprints and tyres a thin pressed layer stays: only digging
reaches the ground). It lives in the project (a text data-block, compressed) and every stroke is a
step of undo. The mantle of the ground (snow.py, the grid from above) is made finer where the map has something:
the cells touched are cut into small squares of about PX (the rest of the ground stays light) and the height of the
snow there is top + max(thickness + D, 0) - deeper than the snow, the ground shows. The models (mantle on their
shape) are not sculpted.

Brushes (stroke): dig / raise (a soft dab, its strength in metres per dab), smooth, steps (footprints left and right
along the stroke, turned along it, with the rim of the snow pushed aside), tyres (two grooves with a tread, at a
gauge, with their berms).
"""
import base64
import json
import math
import zlib

import bpy

from .core import log

TILE = 256
PX = 0.015
TEXT = "Simpler Neve scolpita"
S = {"tiles": None, "rev": 0, "loaded": False, "blobs": {}}      # blobs: the tiles compressed (for the project, undo)


def _np():
    import numpy as np
    return np


# ---------------------------------------------------------------- storage

def _pack(a):
    np = _np()
    return zlib.compress(a.astype(np.float16).tobytes(), 3)


def _unpack(b):
    np = _np()
    return np.frombuffer(zlib.decompress(b), dtype=np.float16).astype(np.float32).reshape(TILE, TILE, 2).copy()


def _tiles():
    """{(tx, ty): float32 (TILE, TILE, 2)} read once from the project."""
    if S["loaded"] and S["tiles"] is not None:
        return S["tiles"]
    tiles, blobs = {}, {}
    txt = bpy.data.texts.get(TEXT)
    if txt is not None:
        try:
            head = json.loads(txt.as_string())
            for k, blob in head.get("tiles", {}).items():
                tx, ty = (int(v) for v in k.split(","))
                blobs[(tx, ty)] = base64.b64decode(blob)
                tiles[(tx, ty)] = _unpack(blobs[(tx, ty)])
        except (ValueError, KeyError, zlib.error) as exc:
            log(f"SIMPLER_SNOW sculpt unreadable: {exc}")
            tiles, blobs = {}, {}
    S.update(tiles=tiles, blobs=blobs, loaded=True)
    return tiles


def _store(tiles, changed=None, blobs=None):
    """The tiles kept (changed: the keys to compress again; None: all; blobs: already compressed)."""
    np = _np()
    # (tiles with nothing left: away)
    tiles = {k: a for k, a in tiles.items()
             if (changed is not None and k not in changed) or np.abs(a[..., 0]).max() > 1e-4 or a[..., 1].max() > 1e-3}
    old = S["blobs"]
    if blobs is not None:
        nb = {k: blobs[k] for k in tiles}
    else:
        nb = {k: (old[k] if (changed is not None and k not in changed and k in old) else _pack(a)) for k, a in tiles.items()}
    S.update(tiles=tiles, blobs=nb, loaded=True, unsaved=True)
    S["rev"] += 1
    from . import rain, snow
    rain.touch(geometry=False)       # (1.78.4: sculpting the snow changes no shape of the scene - the mantle follows)
    snow.touch()
    try:
        snow.press_update()          # (1.79.0) the copies of the distributions pressed by it: at once, for the view
    except Exception as exc:  # noqa: BLE001
        log(f"SIMPLER_SNOW pressed copies failed: {exc}")
    rain.refresh_info()


def flush():
    """Into the project (a text data-block): only when it is written (saving, a snapshot of undo) - writing the text
    at every stroke cost a tenth of a second and more."""
    if not S.get("unsaved"):
        return
    S["unsaved"] = False
    tiles, nb = S["tiles"] or {}, S["blobs"]
    txt = bpy.data.texts.get(TEXT)
    if not tiles:
        if txt is not None:
            bpy.data.texts.remove(txt)
    else:
        if txt is None:
            txt = bpy.data.texts.new(TEXT)
            txt.use_fake_user = True
        txt.from_string(json.dumps({"v": 1, "px": PX, "tile": TILE, "tiles": {
            f"{tx},{ty}": base64.b64encode(b).decode("ascii") for (tx, ty), b in nb.items()}}))


def after_open():
    S.update(tiles=None, blobs={}, loaded=False, unsaved=False)
    S["rev"] += 1


def rev():
    return S["rev"]


def extent():
    """(x0, y0, x1, y1) in metres of the tiles sculpted, or None."""
    tiles = _tiles()
    if not tiles:
        return None
    xs = [k[0] for k in tiles]
    ys = [k[1] for k in tiles]
    return (min(xs) * TILE * PX, min(ys) * TILE * PX, (max(xs) + 1) * TILE * PX, (max(ys) + 1) * TILE * PX)


def present():
    return bool(_tiles())


def info():
    return {"rev": S["rev"], "tiles": len(_tiles())}


def snapshot():
    _tiles()
    return dict(S["blobs"])


def restore(snap):
    snap = snap or {}
    log(f"SIMPLER_SNOW sculpt restored by undo/redo: {len(snap)} tiles (were {len(S['blobs'])})")
    _store({k: _unpack(v) for k, v in snap.items()}, blobs=snap)


def clear(_d=None):
    log(f"SIMPLER_SNOW sculpt cleared («Cancella la neve scolpita»): {len(_tiles())} tiles")
    _store({})
    from . import rain
    return rain.info()


# ---------------------------------------------------------------- reading

def sample(X, Y):
    """D and C at these world points (bilinear; 0 where nothing was done)."""
    np = _np()
    tiles = _tiles()
    D = np.zeros(np.shape(X), dtype=np.float32)
    C = np.zeros(np.shape(X), dtype=np.float32)
    if not tiles:
        return D, C
    fx = np.asarray(X) / PX - 0.5
    fy = np.asarray(Y) / PX - 0.5
    x0 = np.floor(fx).astype(np.int64)
    y0 = np.floor(fy).astype(np.int64)
    wx, wy = (fx - x0).astype(np.float32), (fy - y0).astype(np.float32)
    for (tx, ty), a in tiles.items():
        bx, by = tx * TILE, ty * TILE
        sel = (x0 >= bx - 1) & (x0 < bx + TILE) & (y0 >= by - 1) & (y0 < by + TILE)
        if not sel.any():
            continue
        for dy, dx, w in ((0, 0, (1 - wx) * (1 - wy)), (0, 1, wx * (1 - wy)), (1, 0, (1 - wx) * wy), (1, 1, wx * wy)):
            px, py = x0 + dx - bx, y0 + dy - by
            ok = sel & (px >= 0) & (px < TILE) & (py >= 0) & (py < TILE)
            if ok.any():
                D[ok] += a[py[ok], px[ok], 0] * w[ok]
                C[ok] += a[py[ok], px[ok], 1] * w[ok]
    return D, C


def touched_cells(x0, y0, n, cell, ny=None):
    """The cells of the grid of the mantle with something sculpted near them (ny x n, rows from y0)."""
    np = _np()
    ny = n if ny is None else ny
    out = np.zeros((ny, n), dtype=bool)
    for (tx, ty), a in _tiles().items():
        live = (np.abs(a[..., 0]) > 1e-4) | (a[..., 1] > 1e-3)
        if not live.any():
            continue
        py, px = np.nonzero(live)
        wx = (tx * TILE + px + 0.5) * PX
        wy = (ty * TILE + py + 0.5) * PX
        j = np.floor((wx - x0) / cell).astype(np.int64)
        i = np.floor((wy - y0) / cell).astype(np.int64)
        ok = (i >= 0) & (i < ny) & (j >= 0) & (j < n)
        out[i[ok], j[ok]] = True
    if out.any():                                   # (one cell around: the edge of the fine part is flat)
        grown = out.copy()
        grown[1:] |= out[:-1]; grown[:-1] |= out[1:]
        grown[:, 1:] |= grown[:, :-1].copy(); grown[:, :-1] |= grown[:, 1:].copy()
        out = grown
    return out


# ---------------------------------------------------------------- writing

class _Region:
    """A rectangle of pixels (global indices) gathered from the tiles, written back after the brush."""

    def __init__(self, tiles, xa, ya, xb, yb):
        np = _np()
        self.tiles, self.xa, self.ya = tiles, xa, ya
        self.a = np.zeros((yb - ya, xb - xa, 2), dtype=np.float32)
        for ty in range(ya // TILE, (yb - 1) // TILE + 1):
            for tx in range(xa // TILE, (xb - 1) // TILE + 1):
                t = tiles.get((tx, ty))
                if t is None:
                    continue
                self._copy(tx, ty, t, into=True)

    def _box(self, tx, ty):
        h, w = self.a.shape[:2]
        x0, y0 = max(self.xa, tx * TILE), max(self.ya, ty * TILE)
        x1, y1 = min(self.xa + w, (tx + 1) * TILE), min(self.ya + h, (ty + 1) * TILE)
        return x0, y0, x1, y1

    def _copy(self, tx, ty, t, into):
        x0, y0, x1, y1 = self._box(tx, ty)
        if x1 <= x0 or y1 <= y0:
            return
        rs = (slice(y0 - self.ya, y1 - self.ya), slice(x0 - self.xa, x1 - self.xa))
        ts = (slice(y0 - ty * TILE, y1 - ty * TILE), slice(x0 - tx * TILE, x1 - tx * TILE))
        if into:
            self.a[rs] = t[ts]
        else:
            t[ts] = self.a[rs]

    def coords(self):
        np = _np()
        h, w = self.a.shape[:2]
        X = (self.xa + np.arange(w) + 0.5) * PX
        Y = (self.ya + np.arange(h) + 0.5) * PX
        return np.meshgrid(X, Y)

    def write(self):
        """Back into the tiles; the keys of the tiles written."""
        np = _np()
        h, w = self.a.shape[:2]
        done = set()
        for ty in range(self.ya // TILE, (self.ya + h - 1) // TILE + 1):
            for tx in range(self.xa // TILE, (self.xa + w - 1) // TILE + 1):
                t = self.tiles.get((tx, ty))
                if t is None:
                    x0, y0, x1, y1 = self._box(tx, ty)
                    sub = self.a[y0 - self.ya:y1 - self.ya, x0 - self.xa:x1 - self.xa]
                    if not (np.abs(sub[..., 0]).max(initial=0) > 1e-4 or sub[..., 1].max(initial=0) > 1e-3):
                        continue
                    t = np.zeros((TILE, TILE, 2), dtype=np.float32)
                    self.tiles[(tx, ty)] = t
                self._copy(tx, ty, t, into=False)
                done.add((tx, ty))
        return done


def _smooth(e0, e1, x):
    np = _np()
    t = np.clip((x - e0) / (e1 - e0), 0.0, 1.0)
    return t * t * (3 - 2 * t)


def _resample(pts, step):
    """The stroke as points every `step` metres along it, with the direction there."""
    np = _np()
    P = np.array(pts, dtype=np.float64)[:, :2]
    if len(P) == 1:
        return P, np.array([[0.0, 1.0]])
    seg = np.linalg.norm(np.diff(P, axis=0), axis=1)
    s = np.concatenate([[0.0], np.cumsum(seg)])
    if s[-1] < 1e-6:
        return P[:1], np.array([[0.0, 1.0]])
    q = np.arange(0.0, s[-1] + 1e-9, step)
    X = np.interp(q, s, P[:, 0])
    Y = np.interp(q, s, P[:, 1])
    Q = np.stack([X, Y], axis=1)
    d = np.gradient(Q, axis=0) if len(Q) > 1 else np.array([[0.0, 1.0]])
    d /= np.maximum(np.linalg.norm(d, axis=1), 1e-9)[:, None]
    return Q, d


def stroke(data):
    """POST rain/sculpt {points [[x, y, z]...] (m), mode: dig | raise | smooth | steps | tyres, radius (m),
    depth (m), size (0.5..2, footprints), gauge (m, tyres), width (m, tyres)}."""
    np = _np()
    import time
    t0 = time.time()
    from . import rain
    pts = [p for p in (data.get("points") or []) if isinstance(p, (list, tuple)) and len(p) >= 2]
    if not pts:
        return rain.info()
    mode = str(data.get("mode") or "dig")
    r = max(0.03, min(10.0, float(data.get("radius", 0.4))))
    depth = max(0.005, min(1.0, float(data.get("depth", 0.08))))
    size = max(0.5, min(2.0, float(data.get("size", 1.0))))
    gauge = max(0.3, min(4.0, float(data.get("gauge", 1.5))))
    width = max(0.05, min(1.0, float(data.get("width", 0.2))))
    tiles = dict(_tiles())
    xs = [p[0] for p in pts]
    ys = [p[1] for p in pts]
    reach = r if mode in ("dig", "raise", "smooth") else (0.35 * size if mode == "steps" else gauge / 2 + width + 0.1)
    xa, xb = int(math.floor((min(xs) - reach - 0.05) / PX)), int(math.ceil((max(xs) + reach + 0.05) / PX))
    ya, yb = int(math.floor((min(ys) - reach - 0.05) / PX)), int(math.ceil((max(ys) + reach + 0.05) / PX))
    if (xb - xa) * (yb - ya) > 60_000_000:
        from .core import ApiError
        from .i18n import tr
        raise ApiError(tr("Tratto troppo lungo: dividilo in più tratti"))
    reg = _Region(tiles, xa, ya, xb, yb)
    X, Y = reg.coords()
    D, C = reg.a[..., 0], reg.a[..., 1]
    if mode in ("dig", "raise", "smooth"):
        Q, _d = _resample(pts, max(r * 0.25, PX))
        for x, y in Q:
            j0, j1 = max(0, int((x - r) / PX) - xa), min(X.shape[1], int((x + r) / PX) - xa + 2)
            i0, i1 = max(0, int((y - r) / PX) - ya), min(X.shape[0], int((y + r) / PX) - ya + 2)
            if j0 >= j1 or i0 >= i1:
                continue
            dist = np.hypot(X[i0:i1, j0:j1] - x, Y[i0:i1, j0:j1] - y) / r
            f = 1.0 - _smooth(0.4, 1.0, dist)
            if mode == "dig":
                D[i0:i1, j0:j1] = np.maximum(D[i0:i1, j0:j1] - depth * 0.25 * f, -1.0)
                C[i0:i1, j0:j1] *= 1.0 - f            # (shovelled: down to the ground, no pressed snow left)
            elif mode == "raise":
                D[i0:i1, j0:j1] = np.minimum(D[i0:i1, j0:j1] + depth * 0.25 * f, 1.0)
            else:
                sub = D[max(0, i0 - 3):i1 + 3, max(0, j0 - 3):j1 + 3]
                k = 3
                pad = np.pad(sub, k, mode="edge")
                blur = sum(pad[k + dy:k + dy + sub.shape[0], k + dx:k + dx + sub.shape[1]]
                           for dy in range(-k, k + 1) for dx in range(-k, k + 1)) / float((2 * k + 1) ** 2)
                oi, oj = i0 - max(0, i0 - 3), j0 - max(0, j0 - 3)
                bl = blur[oi:oi + (i1 - i0), oj:oj + (j1 - j0)]
                D[i0:i1, j0:j1] += (bl - D[i0:i1, j0:j1]) * f * 0.6
    elif mode == "steps":
        # one foot every 0.33 m (a stride of 0.66 m), left and right of the line, turned along it
        Q, Dir = _resample(pts, 0.33 * size)
        for k, ((x, y), (dx, dy)) in enumerate(zip(Q, Dir)):
            side = 1.0 if k % 2 == 0 else -1.0
            cx, cy = x - dy * side * 0.09 * size, y + dx * side * 0.09 * size
            ext = 0.25 * size
            j0, j1 = max(0, int((cx - ext) / PX) - xa), min(X.shape[1], int((cx + ext) / PX) - xa + 2)
            i0, i1 = max(0, int((cy - ext) / PX) - ya), min(X.shape[0], int((cy + ext) / PX) - ya + 2)
            if j0 >= j1 or i0 >= i1:
                continue
            u = ((X[i0:i1, j0:j1] - cx) * dx + (Y[i0:i1, j0:j1] - cy) * dy) / size        # along the foot
            v = (-(X[i0:i1, j0:j1] - cx) * dy + (Y[i0:i1, j0:j1] - cy) * dx) / size       # across
            heel = np.sqrt(((u + 0.085) / 0.048) ** 2 + (v / 0.042) ** 2)
            fore = np.sqrt(((u - 0.04) / 0.085) ** 2 + ((v - side * 0.006) / 0.05) ** 2)
            q = np.minimum(heel, fore)
            inside = 1.0 - _smooth(0.82, 1.0, q)
            rim = _smooth(1.0, 1.12, q) * (1.0 - _smooth(1.12, 1.6, q))
            # (the sole: shallow grooves across)
            sole = 1.0 - 0.12 * (np.sin(u * 2.0 * math.pi / 0.018) > 0.3)
            Dk = -depth * inside * sole + 0.3 * depth * rim
            D[i0:i1, j0:j1] = np.where(inside > 0.01, np.minimum(D[i0:i1, j0:j1], Dk), D[i0:i1, j0:j1] + 0.3 * depth * rim)
            C[i0:i1, j0:j1] = np.maximum(C[i0:i1, j0:j1], inside)
    elif mode == "tyres":
        # two grooves at the gauge, with a tread across them and the snow pushed to their sides
        P = np.array(pts, dtype=np.float64)[:, :2]
        seg = np.linalg.norm(np.diff(P, axis=0), axis=1) if len(P) > 1 else np.zeros(0)
        cum = np.concatenate([[0.0], np.cumsum(seg)])
        best_d = np.full(X.shape, np.inf)
        best_v = np.zeros(X.shape)
        best_s = np.zeros(X.shape)
        for a in range(max(1, len(P) - 1)):
            p0 = P[a]
            p1 = P[a + 1] if len(P) > 1 else P[a] + np.array([0.0, 0.01])
            sv = p1 - p0
            L = max(np.linalg.norm(sv), 1e-9)
            t_ = sv / L
            rx, ry = X - p0[0], Y - p0[1]
            along = np.clip(rx * t_[0] + ry * t_[1], 0.0, L)
            across = -rx * t_[1] + ry * t_[0]
            dd = np.hypot(rx - along * t_[0], ry - along * t_[1])
            better = dd < best_d
            best_d = np.where(better, dd, best_d)
            best_v = np.where(better, across, best_v)
            best_s = np.where(better, cum[a] + along, best_s)
        near = best_d < gauge / 2 + width + 0.1
        for off in (-gauge / 2, gauge / 2):
            e = np.abs(best_v - off) / (width / 2)                  # 0 at the middle of the groove, 1 at its edge
            # (walls sloping like a rut: the snow gives way at the edge of the tyre)
            groove = (1.0 - _smooth(0.55, 1.05, e)) * near
            # (the tread: blocks in a chevron, a third of the depth, on the bottom - not on the walls)
            tread = 1.0 - 0.33 * (np.mod(best_s + np.abs(best_v - off) * 0.6, 0.06) < 0.025) * (1.0 - _smooth(0.45, 0.7, e))
            berm = _smooth(1.0, 1.3, e) * (1.0 - _smooth(1.3, 2.1, e)) * near
            D[:] = np.where(groove > 0.01, np.minimum(D, -depth * groove * tread), D + 0.25 * depth * berm)
            C[:] = np.maximum(C, groove)
    reg.a[..., 0], reg.a[..., 1] = D, np.clip(C, 0.0, 1.0)
    reg.a = reg.a.astype(np.float16).astype(np.float32)      # (as kept: undo and the project give the same snow)
    changed = reg.write()
    t1 = time.time()
    _store(tiles, changed)
    log(f"SIMPLER_SNOW sculpt {mode}: {len(pts)} points, {reg.a.shape[1]}x{reg.a.shape[0]} px, {len(tiles)} tiles, "
        f"{t1 - t0:.2f} + {time.time() - t1:.2f} s")
    return rain.info()
