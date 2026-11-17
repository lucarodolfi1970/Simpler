"""Camera effects on the finished picture (display values 0..1), as a photo editor would: no new render.

Order (the same in the real-time view, viewer.js FX): chromatic aberration and sharpening (they sample the
picture), bloom, white balance and tint, contrast, saturation, LUT, vignette, grain. «Schiarisci ombre» and
«Recupera luci» (tone.py) come before all of them.

Sizes follow the frame, not the pixels, so the view (small) and the final render (large) look the same: bloom radius
2% of the diagonal, aberration up to 0.6% from the centre, grain cells from the height (1080 = 1 to 4 pixels).
Sharpening works on the pixels (as in a photo editor).

Keys of the render settings (render.CONFIG_KEYS), all neutral by default:
    fxTemp 2000..12000 K (6500)  fxTint -1..1  fxContrast -1..1  fxSaturation 0..2 (1)  fxLut "" | id  fxLutAmount 0..1
    fxBloom 0..1  fxVignette 0..1  fxCA 0..1  fxGrain 0..1  fxGrainSize 0..1 (0.3)  fxSharpen 0..1
"""
import math

DEFAULTS = {"fxTemp": 6500.0, "fxTint": 0.0, "fxContrast": 0.0, "fxSaturation": 1.0, "fxLut": "", "fxLutAmount": 1.0,
            "fxBloom": 0.0, "fxVignette": 0.0, "fxCA": 0.0, "fxGrain": 0.0, "fxGrainSize": 0.3, "fxSharpen": 0.0}
KEYS = tuple(DEFAULTS)
BLOOM_THRESHOLD = 0.7
BLOOM_RADIUS = 0.02          # sigma, share of the diagonal of the frame
CA_MAX = 0.006
GRAIN_AMP = 0.10
VIGNETTE_MAX = 0.75


def _v(cfg, k):
    v = cfg.get(k, DEFAULTS[k])
    return DEFAULTS[k] if v is None else v


def active(cfg):
    from . import luts
    c = cfg or {}
    return (abs(float(_v(c, "fxTemp")) - 6500.0) > 1.0 or abs(float(_v(c, "fxTint"))) > 1e-3
            or abs(float(_v(c, "fxContrast"))) > 1e-3 or abs(float(_v(c, "fxSaturation")) - 1.0) > 1e-3
            or (bool(_v(c, "fxLut")) and float(_v(c, "fxLutAmount")) > 1e-3 and luts.table(_v(c, "fxLut")) is not None)
            or any(float(_v(c, k)) > 1e-3 for k in ("fxBloom", "fxVignette", "fxCA", "fxGrain", "fxSharpen")))


def kelvin_rgb(t):
    """Colour of a black body (display, Tanner Helland's fit) - only its ratios are used."""
    t = max(1000.0, min(40000.0, float(t))) / 100.0
    r = 255.0 if t <= 66 else 329.698727446 * (t - 60) ** -0.1332047592
    g = 99.4708025861 * math.log(t) - 161.1195681661 if t <= 66 else 288.1221695283 * (t - 60) ** -0.0755148492
    b = 255.0 if t >= 66 else (0.0 if t <= 19 else 138.5177312231 * math.log(t - 10) - 305.0447927307)
    return [max(1.0, min(255.0, x)) / 255.0 for x in (r, g, b)]


def wb_gain(temp, tint):
    """Gains on the linear values: the picture as if the light were 6500 K (lower = bluer, higher = warmer, as
    in a photo editor), tint + magenta / - green; brightness kept."""
    a, b = kelvin_rgb(6500.0), kelvin_rgb(temp)
    g = [((a[i] / b[i]) ** 2.2) for i in range(3)]
    t = max(-1.0, min(1.0, float(tint)))
    g = [g[0] * (1 + 0.2 * t), g[1] * (1 - 0.2 * t), g[2] * (1 + 0.2 * t)]
    y = 0.2126 * g[0] + 0.7152 * g[1] + 0.0722 * g[2]
    return [x / y for x in g]


def frame_rect(w, h, aspect):
    """The rectangle of the frame inside a picture of w x h (the view shows the whole viewport; the frame of the
    chosen format sits centred in it). aspect 0: all of it."""
    if not aspect or aspect <= 0:
        return 0.0, 0.0, float(w), float(h)
    fw, fh = float(w), w / aspect
    if fh > h:
        fh, fw = float(h), h * aspect
    return (w - fw) / 2.0, (h - fh) / 2.0, fw, fh


def _axis_weights(coords, n):
    """Index and weight of linear interpolation along one axis (coords in pixels of a line of n)."""
    import numpy as np
    c = np.clip(np.asarray(coords, np.float32), 0.0, n - 1.001)
    i0 = np.floor(c).astype(np.int32)
    return i0, (c - i0).astype(np.float32)


def _sep_sample(img, xs, ys):
    """img (h, w, c) sampled at the columns xs and the rows ys (linear, separable: a radial scaling about a point
    and a resize are separable - 2 one-dimensional passes instead of 4 two-dimensional gathers)."""
    i, f = _axis_weights(ys, img.shape[0])
    rows = img[i] * (1.0 - f)[:, None, None] + img[i + 1] * f[:, None, None]
    j, g = _axis_weights(xs, img.shape[1])
    return rows[:, j] * (1.0 - g)[None, :, None] + rows[:, j + 1] * g[None, :, None]


def _resize(img, w, h):
    import numpy as np
    H, W = img.shape[:2]
    return _sep_sample(img, (np.arange(w, dtype=np.float32) + 0.5) * W / w - 0.5,
                       (np.arange(h, dtype=np.float32) + 0.5) * H / h - 0.5)


def _blur_small(img):
    """3 x 3 gaussian (1 2 1), edges repeated."""
    import numpy as np
    p = np.pad(img, ((1, 1), (1, 1), (0, 0)), mode="edge")
    h = (p[:, :-2] + 2 * p[:, 1:-1] + p[:, 2:]) * 0.25
    return (h[:-2] + 2 * h[1:-1] + h[2:]) * 0.25


def _gauss_blur(img, sigma):
    """Gaussian blur of a small picture (separable, edges repeated)."""
    import numpy as np
    r = max(1, int(math.ceil(sigma * 3)))
    k = np.exp(-0.5 * (np.arange(-r, r + 1) / max(sigma, 1e-3)) ** 2).astype(np.float32)
    k /= k.sum()
    p = np.pad(img, ((0, 0), (r, r), (0, 0)), mode="edge")
    out = sum(k[i] * p[:, i:i + img.shape[1]] for i in range(2 * r + 1))
    p = np.pad(out, ((r, r), (0, 0), (0, 0)), mode="edge")
    return sum(k[i] * p[i:i + img.shape[0]] for i in range(2 * r + 1))


def _down(img, f):
    """Average of f x f blocks (the bloom works on a small copy)."""
    H, W = img.shape[:2]
    h, w = max(1, H // f), max(1, W // f)
    return img[:h * f, :w * f].reshape(h, f, w, f, -1).mean(axis=(1, 3))


def colour_ops(x, c):
    """The effects that depend only on the colour of a pixel: white balance and tint, contrast, saturation, LUT.
    x: (..., 3) display values."""
    import numpy as np
    from . import luts
    temp, tint = float(c["fxTemp"]), float(c["fxTint"])
    if abs(temp - 6500.0) > 1.0 or abs(tint) > 1e-3:
        g = np.array(wb_gain(temp, tint), np.float32) ** (1 / 2.2)        # ((x^2.2) g)^(1/2.2) = x g^(1/2.2)
        x = np.clip(x * g, 0.0, 1.0)
    con = float(c["fxContrast"])
    if abs(con) > 1e-3:
        x = x + con * (x * x * (3.0 - 2.0 * x) - x)
    sat = float(c["fxSaturation"])
    if abs(sat - 1.0) > 1e-3:
        y = (x @ np.array([0.2126, 0.7152, 0.0722], np.float32))[..., None]
        x = np.clip(y + (x - y) * sat, 0.0, 1.0)
    t = luts.table(c["fxLut"]) if c["fxLut"] else None
    if t is not None and float(c["fxLutAmount"]) > 1e-3:
        x = luts.apply(x, t, float(c["fxLutAmount"]))
    return np.clip(x, 0.0, 1.0).astype(np.float32)


_BAKED = {"key": None, "table": None}


def _colour_table(c):
    """colour_ops on a 33 x 33 x 33 grid, kept while the settings stay the same: the picture then needs one lookup
    per pixel whatever the number of colour effects (a 4K picture: 1.5 s instead of 6)."""
    from . import luts
    key = tuple(c[k] for k in ("fxTemp", "fxTint", "fxContrast", "fxSaturation", "fxLut", "fxLutAmount"))
    if _BAKED["key"] != key:
        _BAKED.update(key=key, table=colour_ops(luts._grid(luts.SIZE).astype("float32"), c))
    return _BAKED["table"]


def _colour_active(c):
    from . import luts
    return (abs(float(c["fxTemp"]) - 6500.0) > 1.0 or abs(float(c["fxTint"])) > 1e-3 or abs(float(c["fxContrast"])) > 1e-3
            or abs(float(c["fxSaturation"]) - 1.0) > 1e-3
            or (bool(c["fxLut"]) and float(c["fxLutAmount"]) > 1e-3 and luts.table(c["fxLut"]) is not None))


def apply_rgb(img, cfg, aspect=0.0, seed=7):
    """img: float32 array (H, W, 3) of display values, row 0 at the top. Returns the new picture."""
    import numpy as np
    from . import luts
    c = {k: _v(cfg or {}, k) for k in KEYS}
    H, W = img.shape[:2]
    fx0, fy0, fw, fh = frame_rect(W, H, aspect)
    cx, cy = fx0 + fw / 2.0, fy0 + fh / 2.0
    half = 0.5 * math.hypot(fw, fh)
    img = np.clip(img.astype(np.float32), 0.0, 1.0)
    ca, sharpen = float(c["fxCA"]), float(c["fxSharpen"])
    if ca > 1e-3:
        k = ca * CA_MAX
        xs, ys = np.arange(W, dtype=np.float32), np.arange(H, dtype=np.float32)
        r = _sep_sample(img[..., 0:1], cx + (xs - cx) * (1 - k), cy + (ys - cy) * (1 - k))
        b = _sep_sample(img[..., 2:3], cx + (xs - cx) * (1 + k), cy + (ys - cy) * (1 + k))
        img = np.concatenate([r, img[..., 1:2], b], axis=-1)
    if sharpen > 1e-3:
        img = np.clip(img + sharpen * 1.5 * (img - _blur_small(img)), 0.0, 1.0)
    bloom = float(c["fxBloom"])
    if bloom > 1e-3:
        f = max(1, int(round(max(W, H) / 256)))
        # (the bright pass on every pixel, then the small copy: the same glow whatever the size of the picture)
        y = img @ np.array([0.2126, 0.7152, 0.0722], np.float32)
        small = _down(img * (np.clip((y - BLOOM_THRESHOLD) / (1 - BLOOM_THRESHOLD), 0, 1) ** 2)[..., None], f)
        glow = _resize(_gauss_blur(small, BLOOM_RADIUS * 2 * half / f), W, H)
        img = 1.0 - (1.0 - img) * (1.0 - np.clip(glow * (bloom * 2.0), 0, 1))
    if _colour_active(c):
        img = luts.apply(img, _colour_table(c))
    vig = float(c["fxVignette"])
    if vig > 1e-3:
        xs, ys = np.arange(W, dtype=np.float32) + 0.5 - cx, np.arange(H, dtype=np.float32) + 0.5 - cy
        r = np.sqrt(xs[None, :] ** 2 + ys[:, None] ** 2) / half
        s = np.clip((r - 0.35) / 0.7, 0, 1)
        k = (1.0 - vig * VIGNETTE_MAX * (s * s * (3 - 2 * s))) ** (1 / 2.2)   # (on the light: x (k)^(1/2.2))
        img = img * k[..., None]
    grain = float(c["fxGrain"])
    if grain > 1e-3:
        cell = max(1.0, (1.0 + 3.0 * float(c["fxGrainSize"])) * fh / 1080.0)
        rng = np.random.default_rng(seed)
        gw, gh = max(2, int(math.ceil(W / cell)) + 1), max(2, int(math.ceil(H / cell)) + 1)
        n = rng.standard_normal((gh, gw, 1)).astype(np.float32)
        noise = _sep_sample(n, np.arange(W, dtype=np.float32) / cell, np.arange(H, dtype=np.float32) / cell)[..., 0]
        if cell > 1.0:
            noise *= 1.4                               # (interpolated noise is softer)
        y = img @ np.array([0.2126, 0.7152, 0.0722], np.float32)
        img = img + (noise * (grain * GRAIN_AMP) * (0.25 + 3.0 * y * (1.0 - y)))[..., None]
    return np.clip(img, 0.0, 1.0)
