"""«Terreno» (1.76.0): the shape of a terrain, made with numpy only (no Blender here: tested on its own).

Realism comes from erosion, not from noise (Luca: «non devono sembrare picchi e valli senza senso»):

1. a base shape for the preset - gradient noise in octaves (fBm), the ridges of mountains (ridged multifractal), the
   whole bent by another noise (domain warping) so nothing looks gridded; octaves damped where the slope is already
   strong (derivative-damped fBm: smooth valleys, detailed ridges, as erosion leaves them);
2. hydraulic erosion on a grid (virtual pipes, Mei, Decaudin and Hu 2007; Jákó and Tóth 2011): rain, water flowing
   downhill through pipes to the 4 neighbours, sediment taken where water is fast and left where it slows down - the
   valleys join into a drainage network, fans of deposits at the foot of the slopes;
3. thermal erosion: what is steeper than the natural angle of the material slides down (talus).

Besides the height it keeps the maps the erosion leaves - flow (where water ran), deposit, wear - and computes slope and
curvature: they decide the zones of the terrain (grass, rock, gravel along channels and fans, snow in hollows high up).
Everything is in metres; the grid is N × N over size × size metres.
"""
import math

import numpy as np

# ---------------------------------------------------------------- gradient noise

_GRADS = np.array([[math.cos(a), math.sin(a)] for a in np.linspace(0, 2 * math.pi, 16, endpoint=False)], dtype=np.float32)
_GX, _GY = np.ascontiguousarray(_GRADS[:, 0]), np.ascontiguousarray(_GRADS[:, 1])


def _perm(rng):
    p = rng.permutation(256).astype(np.int32)
    return np.concatenate([p, p])


def noise(x, y, perm):
    """Perlin gradient noise at the points (x, y) (arrays of the same shape), about -1..1."""
    xi = np.floor(x).astype(np.int32)
    yi = np.floor(y).astype(np.int32)
    xf = (x - xi).astype(np.float32)
    yf = (y - yi).astype(np.float32)
    xi &= 255
    yi &= 255
    u = xf * xf * xf * (xf * (xf * 6 - 15) + 10)
    v = yf * yf * yf * (yf * (yf * 6 - 15) + 10)

    def g(ix, iy, dx, dy):
        h = perm[perm[ix] + iy] & 15
        return _GX[h] * dx + _GY[h] * dy
    n00 = g(xi, yi, xf, yf)
    n10 = g(xi + 1, yi, xf - 1, yf)
    n01 = g(xi, yi + 1, xf, yf - 1)
    n11 = g(xi + 1, yi + 1, xf - 1, yf - 1)
    a = n00 + u * (n10 - n00)
    b = n01 + u * (n11 - n01)
    return (a + v * (b - a)) * 1.414


def fbm(x, y, perm, octaves, lac=2.0, gain=0.5):
    out = np.zeros_like(x, dtype=np.float32)
    amp, f, norm = 1.0, 1.0, 0.0
    for o in range(octaves):
        out += amp * noise(x * f + o * 17.31, y * f - o * 9.73, perm)
        norm += amp
        amp *= gain
        f *= lac
    return out / norm


def ridged(x, y, perm, octaves, lac=2.0, gain=0.5, sharp=2.0):
    """Ridged multifractal: sharp crests that branch, each octave stronger where the one before was high (on the
    ridges) - mountain ranges instead of round bumps. 0..1."""
    out = np.zeros_like(x, dtype=np.float32)
    w = np.ones_like(x, dtype=np.float32)
    amp, f, norm = 1.0, 1.0, 0.0
    for o in range(octaves):
        n = 1.0 - np.abs(noise(x * f + o * 31.7, y * f + o * 7.1, perm))
        n = n ** sharp
        n *= w
        w = np.clip(n * 1.6, 0.0, 1.0)
        out += amp * n
        norm += amp
        amp *= gain
        f *= lac
    return out / norm


def worley(x, y, seed=0):
    """Cellular noise: (F1, F2, id) - the distance to the nearest and second nearest of one jittered point per unit
    cell, and a random 0..1 of the nearest one's cell (blocks of rock, their cracks)."""
    xi = np.floor(x).astype(np.int64)
    yi = np.floor(y).astype(np.int64)
    f1 = np.full(x.shape, 9.0, np.float32)
    f2 = np.full(x.shape, 9.0, np.float32)
    cid = np.zeros(x.shape, np.float32)

    def hsh(a, b, k):
        v = (a * 73856093) ^ (b * 19349663) ^ (k * 83492791) ^ (seed * 2654435761)
        v = (v ^ (v >> 13)) * 1274126177
        return ((v ^ (v >> 16)) & 0xFFFF).astype(np.float32) / 65535.0
    for dy in (-1, 0, 1):
        for dx in (-1, 0, 1):
            cx, cy = xi + dx, yi + dy
            px = cx + hsh(cx, cy, 1)
            py = cy + hsh(cx, cy, 2)
            d = np.hypot(x - px, y - py).astype(np.float32)
            closer = d < f1
            f2 = np.where(closer, f1, np.minimum(f2, d))
            cid = np.where(closer, hsh(cx, cy, 3), cid)
            f1 = np.where(closer, d, f1)
    return f1, f2, cid


def damped_fbm(x, y, perm, octaves, cell, lac=2.0, gain=0.5, k=1.2):
    """fBm whose finer octaves fade where the sum so far is already steep (the slope measured): smooth slopes and
    valleys, detail on flats and crests - a cheap first erosion."""
    out = np.zeros_like(x, dtype=np.float32)
    amp, f, norm = 1.0, 1.0, 0.0
    for o in range(octaves):
        n = noise(x * f + o * 13.1, y * f - o * 5.7, perm)
        if o > 0:
            gy, gx = np.gradient(out, cell)
            n = n / (1.0 + k * (gx * gx + gy * gy))
        out += amp * n
        norm += amp
        amp *= gain
        f *= lac
    return out / norm


# ---------------------------------------------------------------- erosion

def _shift(a, dx, dy):
    """a moved by one cell (edges repeated)."""
    out = np.empty_like(a)
    if dx == 1:
        out[:, 1:] = a[:, :-1]; out[:, 0] = a[:, 0]
    elif dx == -1:
        out[:, :-1] = a[:, 1:]; out[:, -1] = a[:, -1]
    elif dy == 1:
        out[1:, :] = a[:-1, :]; out[0, :] = a[0, :]
    else:
        out[:-1, :] = a[1:, :]; out[-1, :] = a[-1, :]
    return out


def _bilinear(H, x, y):
    n1 = H.shape[1]
    ix = x.astype(np.int32); iy = y.astype(np.int32)
    fx = x - ix; fy = y - iy
    i = iy * n1 + ix
    Hf = H.ravel()
    h00 = Hf[i]; h10 = Hf[i + 1]; h01 = Hf[i + n1]; h11 = Hf[i + n1 + 1]
    return i, fx, fy, h00, h10, h01, h11


def _brush(r):
    out = []
    for oy in range(-r, r + 1):
        for ox in range(-r, r + 1):
            d = math.hypot(ox, oy)
            if d <= r:
                out.append((ox, oy, max(0.0, 1 - d / (r + 0.5))))
    t = sum(w for *_, w in out)
    return [(ox, oy, w / t) for ox, oy, w in out]


_BRUSH = _brush(3)


def hydraulic(h, cell, drops=1.0, life=48, inertia=0.08, capacity=6.0, min_slope=0.01, erode=0.35, deposit=0.3,
              evaporate=0.015, gravity=4.0, batch=None, seed=7, progress=None):
    """Droplet erosion (the method of Hans Theobald Beyer, 2015), many drops at once with numpy: each drop runs
    downhill with some inertia, takes material where it speeds up and its capacity allows, leaves it where it slows
    down or the ground rises. The paths of many drops join into gullies and valleys, the material settles in fans at the
    foot of the slopes. drops: drops per cell of the grid. Returns (h, flow, deposit, wear) in metres."""
    H = (h / cell).astype(np.float32).copy()
    n0, n1 = H.shape
    flow = np.zeros(n0 * n1, np.float32)
    dep = np.zeros(n0 * n1, np.float32)
    wear = np.zeros(n0 * n1, np.float32)
    rng = np.random.default_rng(seed)
    total = int(drops * n0 * n1)
    batch = batch or max(2000, n0 * n1 // 12)
    done = 0
    while done < total:
        m = min(batch, total - done)
        x = rng.random(m, dtype=np.float32) * (n1 - 2)
        y = rng.random(m, dtype=np.float32) * (n0 - 2)
        dx = np.zeros(m, np.float32); dy = np.zeros(m, np.float32)
        speed = np.ones(m, np.float32); water = np.ones(m, np.float32); sed = np.zeros(m, np.float32)
        alive = np.ones(m, bool)
        before = H.copy()
        for _ in range(life):
            a = np.nonzero(alive)[0]
            if a.size == 0:
                break
            xa, ya = x[a], y[a]
            i, fx, fy, h00, h10, h01, h11 = _bilinear(H, xa, ya)
            gx = (h10 - h00) * (1 - fy) + (h11 - h01) * fy
            gy = (h01 - h00) * (1 - fx) + (h11 - h10) * fx
            hold = h00 * (1 - fx) * (1 - fy) + h10 * fx * (1 - fy) + h01 * (1 - fx) * fy + h11 * fx * fy
            ndx = dx[a] * inertia - gx * (1 - inertia)
            ndy = dy[a] * inertia - gy * (1 - inertia)
            ln = np.sqrt(ndx * ndx + ndy * ndy)
            ok = ln > 1e-6
            ndx = np.where(ok, ndx / np.maximum(ln, 1e-6), 0.0); ndy = np.where(ok, ndy / np.maximum(ln, 1e-6), 0.0)
            nx = xa + ndx; ny = ya + ndy
            inside = ok & (nx >= 0) & (nx < n1 - 2) & (ny >= 0) & (ny < n0 - 2)
            _, fx2, fy2, a00, a10, a01, a11 = _bilinear(H, np.clip(nx, 0, n1 - 2.001), np.clip(ny, 0, n0 - 2.001))
            hnew = a00 * (1 - fx2) * (1 - fy2) + a10 * fx2 * (1 - fy2) + a01 * (1 - fx2) * fy2 + a11 * fx2 * fy2
            dh = np.where(inside, hnew - hold, 0.0)
            s = sed[a]
            cap = np.maximum(-dh, min_slope) * speed[a] * water[a] * capacity
            depo = np.where(dh > 0, np.minimum(dh, s), np.maximum(s - cap, 0.0) * deposit)
            depo = np.where(inside, depo, s)                       # a drop that leaves drops what it carries
            ero = np.where((dh <= 0) & (s <= cap) & inside, np.minimum(np.minimum((cap - s) * erode, -dh), 0.3), 0.0)
            depo = np.minimum(depo, 0.5 + 0.0 * depo)
            w00 = (1 - fx) * (1 - fy); w10 = fx * (1 - fy); w01 = (1 - fx) * fy; w11 = fx * fy
            Hf = H.ravel()
            # deposit on the 4 corners (bilinear); erosion with a round brush of radius r (as the original): wider
            # channels, no rills of one cell
            for off, w in ((0, w00), (1, w10), (n1, w01), (n1 + 1, w11)):
                np.add.at(Hf, i + off, depo * w)
            ix0 = i % n1; iy0 = i // n1
            for ox, oy, bw in _BRUSH:
                jx = np.clip(ix0 + ox, 0, n1 - 1); jy = np.clip(iy0 + oy, 0, n0 - 1)
                np.add.at(Hf, jy * n1 + jx, -ero * bw)
            np.add.at(flow, i, water[a] * speed[a])
            np.add.at(dep, i, depo)
            np.add.at(wear, i, ero)
            sed[a] = s - depo + ero
            speed[a] = np.minimum(np.sqrt(np.maximum(0.0, speed[a] * speed[a] - dh * gravity)), 6.0)
            water[a] *= (1 - evaporate)
            x[a] = nx; y[a] = ny; dx[a] = ndx; dy[a] = ndy
            alive[a] = inside
        # the change of this batch softened a little (as the brush of the original): no pits of one cell
        # (many drops move at once and read the same ground: the change of a batch is kept within bounds)
        H = before + np.clip(smooth(H - before, 1), -1.0, 1.0)
        done += m
        if progress:
            progress(done / total)
    f = flow.reshape(n0, n1) / max(1.0, drops)
    return H * cell, f, dep.reshape(n0, n1) * cell, wear.reshape(n0, n1) * cell


def thermal(h, cell, talus_deg=33.0, iters=40, rate=0.5):
    """Material slides to the neighbours lower by more than the natural angle (talus): no impossible walls."""
    h = h.astype(np.float32).copy()
    lim = math.tan(math.radians(talus_deg)) * cell
    for _ in range(iters):
        moved = np.zeros_like(h)
        for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1)):
            nb = _shift(h, dx, dy)
            diff = h - nb - lim
            m = np.where(diff > 0, diff * rate * 0.25, 0.0)
            moved -= m
            # what leaves this cell arrives at the neighbour: shifted back
            moved += _shift(m, -dx, -dy)
        h += moved
    return h


def resample(a, m):
    """a (N × N) to M × M, bilinear."""
    n = a.shape[0]
    if n == m:
        return a.copy()
    src = np.linspace(0, n - 1, m)
    i = np.clip(src.astype(np.int32), 0, n - 2)
    f = (src - i).astype(np.float32)
    rows = a[i] * (1 - f)[:, None] + a[i + 1] * f[:, None]
    return rows[:, i] * (1 - f)[None, :] + rows[:, i + 1] * f[None, :]


def smooth(a, passes=1):
    for _ in range(passes):
        a = (a * 4 + _shift(a, 1, 0) + _shift(a, -1, 0) + _shift(a, 0, 1) + _shift(a, 0, -1)) / 8.0
    return a


# ---------------------------------------------------------------- presets

MACRO_GRID = 192

PRESETS = {
    # size m, relief m; macro: grown by rivers (lo: uplift of the lowest parts, kf: strength of the rivers, D: creep
    # of the slopes, steps); drops: droplets per cell on the fine grid; detail: noise for the drops to work on;
    # crag: broken rock on steep high parts; talus: natural angle (degrees)
    "pianura": {"size": 800.0, "height": 10.0, "drops": 0.4, "detail": 0.01, "talus": 25.0},
    "colline": {"size": 1200.0, "height": 90.0, "macro": True, "lo": 0.35, "kf": 20.0, "D": 0.7, "steps": 80,
                "drops": 0.6, "detail": 0.006, "talus": 30.0},
    "montagne": {"size": 3000.0, "height": 650.0, "macro": True, "lo": 0.6, "kf": 30.0, "D": 0.4, "steps": 100,
                 "drops": 1.0, "detail": 0.01, "crag": 0.025, "talus": 40.0},
    "dune": {"size": 800.0, "height": 25.0, "drops": 0.0, "talus": 32.0},
    "valle": {"size": 1500.0, "height": 380.0, "macro": True, "lo": 0.1, "kf": 25.0, "D": 0.6, "steps": 90,
              "drops": 0.8, "detail": 0.008, "talus": 34.0},
    "canyon": {"size": 1500.0, "height": 180.0, "drops": 0.4, "detail": 0.004, "talus": 55.0},
}


def base_shape(preset, n, size, height, seed, rough=0.5, warp=0.5, direction=0.0):
    """The shape before erosion, in metres (N × N)."""
    rng = np.random.default_rng(seed)
    perm = _perm(rng)
    perm2 = _perm(rng)
    t = np.linspace(0.0, 1.0, n, dtype=np.float32)
    x, y = np.meshgrid(t, t)
    cell = size / (n - 1)
    # domain warping: the coordinates bent by a large, slow noise
    wf = 2.0
    wx = noise(x * wf + 3.3, y * wf + 1.7, perm2)
    wy = noise(x * wf - 5.1, y * wf + 8.2, perm2)
    W = 0.12 * warp
    xw, yw = x + W * wx, y + W * wy
    octs = int(max(5, min(10, math.log2(n))))
    a = math.radians(direction)
    cosa, sina = math.cos(a), math.sin(a)
    du = 1.0 / (n - 1)                       # one cell, in units of the terrain

    def broad(f, o=4):
        return 0.5 + 0.5 * fbm(x * f + 7.7, y * f - 3.1, perm2, o)
    if preset == "pianura":
        z = 0.5 + 0.5 * damped_fbm(xw * 3.0, yw * 3.0, perm, octs, du * 3.0, gain=0.40 + 0.1 * rough, k=1.0)
        z = z * z * (3 - 2 * z)
    elif preset == "colline":
        z = 0.5 + 0.5 * damped_fbm(xw * 2.2, yw * 2.2, perm, octs, du * 2.2, gain=0.42 + 0.08 * rough, k=1.0)
        z = z * (0.55 + 0.45 * broad(0.8))
    elif preset == "montagne":
        r = ridged(xw * 1.4, yw * 1.4, perm, octs, gain=0.44 + 0.08 * rough, sharp=1.3)
        mass = broad(0.7, 3)
        z = r * (0.2 + 0.9 * mass) + 0.25 * mass
    elif preset == "dune":
        # transverse dunes: crests across the wind (direction), long gentle slope where the wind comes from, slip face
        # at the natural angle behind; crests bend, break and join (phase bent by two noises along and across), their
        # height changes along the crest, smaller dunes ride on the backs of the big ones
        f = size / 90.0
        u = (xw * cosa + yw * sina) * f
        v = (-xw * sina + yw * cosa) * f
        u2 = u + 1.6 * noise(v * 0.18, u * 0.06 + 5, perm2) + 0.7 * noise(v * 0.55 + 3, u * 0.15, perm) \
            + 0.25 * noise(v * 1.4 + 9, u * 0.4, perm2)
        ph = u2 - np.floor(u2)
        prof = np.where(ph < 0.72, ph / 0.72, (1.0 - ph) / 0.28)
        prof = np.sin(prof * math.pi / 2) ** 1.8
        along = 0.5 + 0.5 * noise(v * 0.35 + 21, np.floor(u2) * 0.37, perm)      # height along each crest
        big = prof * (0.35 + 0.65 * along)
        u3 = u * 3.1 + 0.8 * noise(v * 0.9, u * 0.5, perm2)
        ph3 = u3 - np.floor(u3)
        small = np.where(ph3 < 0.75, ph3 / 0.75, (1.0 - ph3) / 0.25) * 0.12
        z = big + small * (1 - big) + 0.25 * broad(1.0)
    elif preset == "valle":
        hills = 0.5 + 0.5 * damped_fbm(xw * 2.4, yw * 2.4, perm, octs, du * 2.4, gain=0.42 + 0.08 * rough, k=1.0)
        c = (x - 0.5) * cosa + (y - 0.5) * sina
        along = -(x - 0.5) * sina + (y - 0.5) * cosa
        mean = 0.10 * noise(along * 2.0 + 4.0, np.full_like(along, 0.37), perm2) + 0.03 * noise(along * 6.0, np.full_like(along, 2.1), perm2)
        dist = np.abs(c - mean)
        prof = np.clip((dist - 0.01) / 0.18, 0, 1) ** 0.7
        prof = prof * prof * (3 - 2 * prof)
        z = 0.03 + prof * (0.45 + 0.55 * hills)
    elif preset == "canyon":
        plateau = 0.5 + 0.5 * fbm(xw * 1.6, yw * 1.6, perm, 6, gain=0.45)
        c = (x - 0.5) * cosa + (y - 0.5) * sina
        along = -(x - 0.5) * sina + (y - 0.5) * cosa
        mean = 0.09 * noise(along * 2.5 + 1.0, np.full_like(along, 0.4), perm2) + 0.025 * noise(along * 8.0, np.full_like(along, 1.7), perm)
        dist = np.abs(c - mean) + 0.025 * fbm(x * 12, y * 12, perm2, 3)
        cut = np.clip((dist - 0.015) / 0.18, 0, 1)
        cut = cut ** 0.6
        z = 0.12 + 0.88 * cut * (0.82 + 0.18 * plateau)
    else:
        raise ValueError(preset)
    z = z - float(z.min())
    z = z / max(1e-6, float(z.max()))
    return (z * height).astype(np.float32)


def strata(h, height, layers=9, hardness=0.75, seed=0):
    """Geological layers (canyons, cliffs): the height pulled towards steps of hard rock with soft slopes between."""
    rng = np.random.default_rng(seed + 99)
    edges = np.sort(rng.random(layers)) * height
    out = h.copy()
    t = h / max(height, 1e-6)
    step = height / layers
    q = np.floor(h / step)
    f = (h - q * step) / step
    f2 = np.where(f < hardness, f / hardness * 0.25, 0.25 + (f - hardness) / (1 - hardness) * 0.75)
    out = (q + f2) * step
    return 0.35 * h + 0.65 * out


def _stage(progress, a, b):
    """progress of a part of the work (a..b of the whole)."""
    if progress is None:
        return None
    return lambda f: progress(a + (b - a) * max(0.0, min(1.0, f)))


def macro_relief(preset, size, height, seed, rough, warp, direction, P, progress=None):
    """The large shape, grown by uplift and rivers (fluvial) on a domain half again as large, cut in the middle (no
    edge effects: rivers leave by the borders of the larger domain). Heights 0..1 on a grid of MACRO_GRID."""
    pad, m1 = 1.5, MACRO_GRID
    base = base_shape(preset, m1, size * pad, height, seed, rough, warp, direction) / height
    rng = np.random.default_rng(seed)
    c = size * pad / (m1 - 1)
    k = P["kf"] * c / ((size * pad) ** 2) ** 0.45
    lo = P["lo"]
    U = (lo + (1 - lo) * base ** 1.5) * 0.03
    z = fluvial(rng.random(base.shape).astype(np.float32) * 0.01, c, steps=P["steps"], k=k, diffusion=P["D"],
                uplift=U, progress=progress)[0]
    a = int(round(m1 * (1 - 1 / pad) / 2))
    z = z[a:m1 - a, a:m1 - a]
    return (z - z.min()) / max(1e-6, float(np.ptp(z)))


def generate(preset="colline", n=384, size=None, height=None, seed=1, rough=0.5, warp=0.5, direction=0.0,
             erosion=1.0, age=1.0, talus=None, progress=None):
    """The terrain: {"h", "flow", "deposit", "wear", "slope" (degrees), "curv", "cell", "size"}.

    Mountains, hills and valleys: macro relief grown by rivers (macro_relief), then droplet erosion on the fine grid
    with heights 0..1 (the scale of the original method: gentle, measured) - gullies, ridges sharpened, valley floors
    filled with what came down; then the natural angle (thermal). Plains: their gentle shape and a light erosion.
    Dunes: their own shape, the slip faces at the natural angle of sand. Canyon: layers of rock and the river cut."""
    P = PRESETS[preset]
    size = float(size or P["size"])
    height = float(height or P["height"])
    cell = size / (n - 1)
    t = np.linspace(0.0, 1.0, n, dtype=np.float32)
    X, Y = np.meshgrid(t, t)
    perm = _perm(np.random.default_rng(seed + 5))
    if P.get("macro"):
        z = macro_relief(preset, size, height, seed, rough, warp, direction, P, _stage(progress, 0.0, 0.45))
        h = smooth(resample(z, n), 1)
    else:
        h = base_shape(preset, n, size, height, seed, rough, warp, direction) / height
        if preset == "canyon":
            h = strata(h, 1.0, seed=seed)
    h = h + P.get("detail", 0.0) * fbm(X * 20, Y * 20, perm, 5, gain=0.5)
    flow = np.zeros_like(h); dep = np.zeros_like(h); wear = np.zeros_like(h)
    drops = P["drops"] * max(0.0, age)
    if erosion > 0 and drops > 0:
        he, flow, dep, wear = hydraulic(h.astype(np.float32), 1.0, drops=drops, life=30, inertia=0.05, capacity=4.0,
                                        min_slope=0.01, erode=0.3 * erosion, deposit=0.3, evaporate=0.01, gravity=4.0,
                                        seed=seed, progress=_stage(progress, 0.45, 0.95))
        h = he
    h = (h - h.min()) / max(1e-6, float(np.ptp(h))) * height
    crag = P.get("crag", 0.0)
    if crag > 0:
        # broken rock on the high, steep parts: crests and peaks not smooth
        gy, gx = np.gradient(h, cell)
        steep = np.clip((np.degrees(np.arctan(np.hypot(gx, gy))) - 25.0) / 20.0, 0, 1)
        high = np.clip((h / height - 0.35) / 0.4, 0, 1)
        r = ridged(X * 40, Y * 40, perm, 4, gain=0.5, sharp=2.0)
        h = h + crag * height * (r - 0.4) * steep * high
    # (on gentle ground the drops leave small pits where they stopped: smoothed there, slopes untouched)
    gy, gx = np.gradient(h, cell)
    gentle = np.clip(1.0 - np.degrees(np.arctan(np.hypot(gx, gy))) / 8.0, 0, 1)
    h = h + gentle * (smooth(h, 3) - h)
    tal = float(talus or P["talus"])
    h = thermal(h, cell, tal, iters=15 if preset != "dune" else 60)
    # (the outermost cells: the drops leave there and leave a ragged rim)
    for i in range(3):
        h[2 - i, :] = h[3, :]; h[-3 + i, :] = h[-4, :]
    for i in range(3):
        h[:, 2 - i] = h[:, 3]; h[:, -3 + i] = h[:, -4]
    if progress:
        progress(1.0)
    gy, gx = np.gradient(h, cell)
    slope = np.degrees(np.arctan(np.sqrt(gx * gx + gy * gy)))
    lap = (_shift(h, 1, 0) + _shift(h, -1, 0) + _shift(h, 0, 1) + _shift(h, 0, -1) - 4 * h) / (cell * cell)
    return {"h": h.astype(np.float32), "flow": flow, "deposit": dep * height, "wear": wear * height,
            "slope": slope.astype(np.float32), "curv": lap.astype(np.float32), "cell": cell, "size": size,
            "height": height, "preset": preset}


def hillshade(h, cell, az=315, alt=40):
    gy, gx = np.gradient(h, cell)
    slope = np.arctan(np.sqrt(gx * gx + gy * gy))
    aspect = np.arctan2(-gx, gy)
    a, e = math.radians(az), math.radians(alt)
    return np.clip(np.sin(e) * np.cos(slope) + np.cos(e) * np.sin(slope) * np.cos(a - aspect), 0, 1)


# ---------------------------------------------------------------- fluvial erosion (stream power), the main shaping

_NB8 = [(-1, -1), (0, -1), (1, -1), (-1, 0), (1, 0), (-1, 1), (0, 1), (1, 1)]


def _fill(h, eps):
    """Priority flood (Barnes, Lehman and Mulla 2014): every hollow raised to its spill point (+ a tiny slope), so
    all water reaches the border of the terrain. Python with heapq: a grid of about 200 × 200 in a fraction of a s."""
    import heapq
    n0, n1 = h.shape
    hf = h.ravel().astype(np.float64).tolist()
    done = bytearray(n0 * n1)
    pq = []
    for x in range(n1):
        for y in (0, n0 - 1):
            i = y * n1 + x
            if not done[i]:
                done[i] = 1; pq.append((hf[i], i))
    for y in range(1, n0 - 1):
        for x in (0, n1 - 1):
            i = y * n1 + x
            done[i] = 1; pq.append((hf[i], i))
    heapq.heapify(pq)
    offs = [(dx, dy, dy * n1 + dx) for dx, dy in _NB8]
    pop, push = heapq.heappop, heapq.heappush
    while pq:
        z, i = pop(pq)
        y, x = divmod(i, n1)
        for dx, dy, o in offs:
            xx = x + dx; yy = y + dy
            if 0 <= xx < n1 and 0 <= yy < n0:
                j = i + o
                if not done[j]:
                    done[j] = 1
                    if hf[j] <= z:
                        hf[j] = z + eps
                    push(pq, (hf[j], j))
    return np.array(hf, dtype=np.float64).reshape(n0, n1)


def _receivers(hf, cell):
    """Steepest descent neighbour (of 8) of every cell, and its distance; border cells and outlets: themselves."""
    n0, n1 = hf.shape
    idx = np.arange(n0 * n1).reshape(n0, n1)
    best = np.zeros((n0, n1)); rcv = idx.copy(); dist = np.full((n0, n1), cell)
    pad = np.pad(hf, 1, mode="edge")
    ipad = np.pad(idx, 1, mode="edge")
    for dx, dy in _NB8:
        d = cell * (1.4142135 if dx and dy else 1.0)
        nb = pad[1 + dy:1 + dy + n0, 1 + dx:1 + dx + n1]
        s = (hf - nb) / d
        better = s > best
        best = np.where(better, s, best)
        rcv = np.where(better, ipad[1 + dy:1 + dy + n0, 1 + dx:1 + dx + n1], rcv)
        dist = np.where(better, d, dist)
    return rcv.ravel(), dist.ravel()


def fluvial(h, cell, steps=60, k=None, m=0.45, diffusion=0.6, uplift=None, dt=1.0, progress=None):
    """Landscape evolution: dh/dt = uplift - K A^m S + D ∇²h (rivers cut in proportion to the water they carry and to
    the slope, hillslopes creep). The stream-power part implicit along the flow (Braun and Willett 2013): stable with
    long steps. A = drained area (m²). The valleys organise into a branching network, ridges between them, hilltops
    round - the look of real relief. h in metres; returns (h, area)."""
    n0, n1 = h.shape
    z = h.astype(np.float64).copy()
    U = np.zeros_like(z) if uplift is None else uplift.astype(np.float64)
    k = k if k is not None else 2e-4
    area = np.ones(n0 * n1)
    border = np.zeros((n0, n1), bool)
    border[0, :] = border[-1, :] = border[:, 0] = border[:, -1] = True
    bflat = border.ravel()
    rng = np.random.default_rng(11)
    for st in range(steps):
        rel = max(float(np.ptp(z)), 1e-6)                     # (in the units of the heights given)
        hf = _fill(z, 1e-7 * rel)
        # (a little noise on the routing: no straight lines along the grid's 8 directions)
        rcv, dist = _receivers(hf + 0.002 * rel * rng.random(hf.shape), cell)
        order = np.argsort(hf.ravel(), kind="stable")          # low to high
        a = np.full(n0 * n1, cell * cell)
        r_l = rcv.tolist(); a_l = a.tolist()
        for i in order[::-1].tolist():                         # high to low: give the area downstream
            j = r_l[i]
            if j != i:
                a_l[j] += a_l[i]
        area = np.array(a_l)
        z = hf.copy()                                          # (the hollows filled: lakes become flats)
        zf = z.ravel()
        zf += U.ravel() * dt
        f = k * dt * np.power(area, m) / dist
        z_l = zf.tolist(); f_l = f.tolist()
        for i in order.tolist():                               # low to high: implicit stream power (n = 1)
            j = r_l[i]
            if j != i and not bflat[i]:
                zi = (z_l[i] + f_l[i] * z_l[j]) / (1.0 + f_l[i])
                z_l[i] = zi if zi > z_l[j] else z_l[j] + 1e-6
        z = np.array(z_l).reshape(n0, n1)
        if diffusion > 0:
            lap = (np.pad(z, 1, mode="edge")[1:-1, 2:] + np.pad(z, 1, mode="edge")[1:-1, :-2]
                   + np.pad(z, 1, mode="edge")[2:, 1:-1] + np.pad(z, 1, mode="edge")[:-2, 1:-1] - 4 * z)
            z += diffusion * 0.2 * lap
        if progress:
            progress((st + 1) / steps)
    return z.astype(np.float32), area.reshape(n0, n1).astype(np.float32)


# ---------------------------------------------------------------- erosion filter (gullies that follow the slope)

def gullies(h, size, octaves=5, base_cells=12.0, strength=0.12, seed=0, sharp=1.0):
    """Branching gullies carved along the slope, made analytically (the idea of the «erosion filter» of Rune Skovbo
    Johansen, 2023): for every octave, a kernel of jittered cells gives stripes that run downhill (across the
    contour lines), their depth growing with the slope; each finer octave follows the slopes the coarser ones
    made, so small gullies join bigger ones. Seconds, no simulation. h in metres; returns h."""
    n = h.shape[0]
    rng = np.random.default_rng(seed + 31)
    t = np.linspace(0.0, 1.0, n, dtype=np.float32)
    X, Y = np.meshgrid(t, t)
    cell = size / (n - 1)
    out = h.astype(np.float32).copy()
    relief = float(np.ptp(h)) or 1.0
    amp = strength * relief
    f = base_cells
    jit = rng.random((4096, 2)).astype(np.float32)
    for o in range(octaves):
        gy, gx = np.gradient(out, cell)
        s = np.sqrt(gx * gx + gy * gy) + 1e-9
        # direction across the slope (stripes along the downhill direction)
        px, py = -gy / s, gx / s
        px = smooth(px, 2); py = smooth(py, 2)
        pn = np.sqrt(px * px + py * py) + 1e-9
        px /= pn; py /= pn
        ux, uy = X * f, Y * f
        cx, cy = np.floor(ux), np.floor(uy)
        val = np.zeros_like(out); wsum = np.zeros_like(out)
        for oy in (-1, 0, 1):
            for ox in (-1, 0, 1):
                kx = cx + ox; ky = cy + oy
                hidx = ((kx.astype(np.int64) * 73856093) ^ (ky.astype(np.int64) * 19349663) ^ (o * 83492791)) & 4095
                jx = kx + jit[hidx, 0]; jy = ky + jit[hidx, 1]
                dx = ux - jx; dy = uy - jy
                w = np.exp(-(dx * dx + dy * dy) * 1.6)
                val += w * np.cos(2 * math.pi * (dx * px + dy * py))
                wsum += w
        g = val / np.maximum(wsum, 1e-6)                    # -1 .. 1: ridges +, gullies -
        g = np.sign(g) * np.abs(g) ** sharp
        slope_f = np.clip(np.degrees(np.arctan(s)) / 25.0, 0.0, 1.0)
        out += amp * g * slope_f
        amp *= 0.5
        f *= 2.0
    return out
