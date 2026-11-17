"""Night sky: the real stars and the Moon, for the Ambiente (ambience.py) and the real-time view.

- Stars: NASA SVS "Deep Star Maps 2020" (Hipparcos-2, Tycho-2, UCAC3, Gaia DR2): a plate carrée picture of the whole
  sky in celestial coordinates (centred at 0h of right ascension, which grows to the left), with the Milky Way. It
  is turned to the sky of the scene by its latitude, day and hour (local sidereal time, the same simple astronomy as
  the sun of scene_ops.sun_vector), so the stars stand where they would. Brightness: the picture is measured once
  (a very bright star = 1), then «Stelle» decides.
- Moon: NASA SVS "CGI Moon Kit" (LRO, LROC colour map): its near side drawn on a disc in the sky where the moonlight
  comes from, lit by the phase (the shadow of a real sphere, with a hint of earthshine), any size.

Both are downloaded the first time a night needs them (about 35 MB), into the library folder; until then the
stars are the drawn ones of before and the moon is only its light. Credit: NASA's Scientific Visualization Studio
(Gaia data: ESA/Gaia/DPAC) - credits/Crediti.md.
"""
import json
import math
import os
import threading
import time

import bpy

BASE = "https://svs.gsfc.nasa.gov/vis/a000000/"
FILES = {
    "stars": ("starmap_2020_4k.exr", BASE + "a004800/a004851/starmap_2020_4k.exr", 35_000_000),
    "moon": ("lroc_color_2k.jpg", BASE + "a004700/a004720/lroc_color_2k.jpg", 460_000),
}
VIEW_STARS = "stars_view.png"           # the stars for the real-time view (8 bits, square root: see prepare)
INFO = "night.json"
REV = 1

# (re-entrant: download() asks status() while holding it - with a plain lock a second call during a download, two
# changes of the Ambiente within two minutes on a slow network, stopped the engine for good; found by the check, 1.73.8)
_lock = threading.RLock()
_job = {"state": "none", "done": 0, "total": 0, "error": "", "seen": 0.0}


def root():
    from . import paths
    d = os.path.join(paths.get("phTextures"), "night")
    os.makedirs(d, exist_ok=True)
    return d


def file_of(kind):
    p = os.path.join(root(), FILES[kind][0])
    return p if os.path.isfile(p) and os.path.getsize(p) > 0 else ""


def ready():
    return bool(file_of("stars") and file_of("moon"))


def status(_d=None):
    with _lock:
        j = dict(_job)
    if ready():
        j["state"] = "done"
    j["fraction"] = j["done"] / j["total"] if j.get("total") else None
    return j


def download(_d=None):
    """Starts the download of what is missing (stars, moon). Returns status()."""
    if ready():
        return status()
    with _lock:
        if _job["state"] == "running" and time.time() - _job["seen"] < 120:
            return status()
        _job.update(state="running", done=0, total=sum(f[2] for k, f in FILES.items() if not file_of(k)), error="",
                    seen=time.time())

    def advance(n):
        with _lock:
            _job["done"] += n
            _job["seen"] = time.time()

    def run():
        from . import library
        try:
            for kind in ("moon", "stars"):
                if file_of(kind):
                    continue
                name, url, _size = FILES[kind]
                library._download(url, os.path.join(root(), name), advance, timeout=60)
            with _lock:
                _job["state"] = "done"
        except Exception as exc:
            with _lock:
                _job.update(state="error", error=library.explain(exc))
    threading.Thread(target=run, daemon=True).start()
    return status()


def _image(path, colorspace):
    name = "Simpler Night · " + os.path.basename(path)
    im = bpy.data.images.get(name)
    if im is None or bpy.path.abspath(im.filepath) != path:
        if im is not None:
            bpy.data.images.remove(im)
        im = bpy.data.images.load(path, check_existing=False)
        im.name = name
    im.colorspace_settings.name = colorspace
    return im


def prepare():
    """Once per downloaded file (main thread): the brightness of the star map (99.99th percentile of the luminance =
    1), the picture of the stars for the view (square root in 8 bits: the faint Milky Way and the bright stars both
    survive; the view squares it back) and the average whiteness of the moon. Returns the info, or None."""
    if not ready():
        return None
    sp, mp = file_of("stars"), file_of("moon")
    sig = [REV, os.path.getsize(sp), int(os.path.getmtime(sp)), os.path.getsize(mp), int(os.path.getmtime(mp))]
    ip = os.path.join(root(), INFO)
    try:
        with open(ip, encoding="utf-8") as f:
            info = json.load(f)
        if info.get("sig") == sig and os.path.isfile(os.path.join(root(), VIEW_STARS)):
            return info
    except (OSError, ValueError):
        pass
    import numpy as np
    st = _image(sp, "Linear Rec.709")
    w, h = st.size
    px = np.empty(w * h * 4, dtype=np.float32)
    st.pixels.foreach_get(px)
    px = px.reshape(-1, 4)
    lum = 0.2126 * px[:, 0] + 0.7152 * px[:, 1] + 0.0722 * px[:, 2]
    norm = float(np.percentile(lum, 99.99)) or 1.0
    view = np.sqrt(np.clip(px[:, :3] / norm, 0.0, 1.0))
    out = np.ones((w * h, 4), dtype=np.float32)
    out[:, :3] = view
    vi = bpy.data.images.new("Simpler Night · view", w, h, alpha=False, float_buffer=False)
    try:
        vi.colorspace_settings.name = "Non-Color"
        vi.pixels.foreach_set(out.ravel())
        vi.filepath_raw = os.path.join(root(), VIEW_STARS)
        vi.file_format = "PNG"
        vi.save()
    finally:
        bpy.data.images.remove(vi)
    mo = _image(mp, "sRGB")
    mw, mh = mo.size
    mpx = np.empty(mw * mh * 4, dtype=np.float32)
    mo.pixels.foreach_get(mpx)
    mpx = mpx.reshape(-1, 4)
    # (linear whiteness: the pixels of an 8-bit picture come as it is stored, sRGB)
    lin = np.power(np.clip(mpx[:, :3], 0.0, 1.0), 2.2)
    mean = float((0.2126 * lin[:, 0] + 0.7152 * lin[:, 1] + 0.0722 * lin[:, 2]).mean()) or 0.2
    info = {"sig": sig, "norm": norm, "moonMean": mean, "w": w, "h": h}
    with open(ip, "w", encoding="utf-8") as f:
        json.dump(info, f)
    return info


def view_file(kind):
    """Path of a picture for the real-time view: "stars" (prepared) or "moon"."""
    if kind == "stars":
        p = os.path.join(root(), VIEW_STARS)
        return p if os.path.isfile(p) else ""
    if kind == "moon":
        return file_of("moon")
    return ""


# ---------------------------------------------------------------- geometry of the night sky

def frames(sun_s):
    """The constant vectors that turn a direction of the scene into celestial coordinates (see ambience: stars):
    pole P (sin of the declination = d·P), A and B (hour angle = atan2(d·B, d·A)), and the local sidereal time."""
    from mathutils import Vector
    phi = math.radians(float(sun_s["lat"]))
    t = math.radians(float(sun_s["north"]))
    n_dir = Vector((math.sin(t), math.cos(t), 0.0))
    e_dir = Vector((math.cos(t), -math.sin(t), 0.0))
    up = Vector((0.0, 0.0, 1.0))
    P = up * math.sin(phi) + n_dir * math.cos(phi)
    A = up * math.cos(phi) - n_dir * math.sin(phi)
    B = -e_dir
    # local sidereal time (radians): the sun's right ascension (from the day: 0 at the March equinox) plus the hour
    # angle of the sun (local solar time)
    lst = math.radians(15.0 * (float(sun_s["hour"]) - 12.0) + 360.0 / 365.2422 * (float(sun_s["day"]) - 80.0))
    return P, A, B, lst


def phase_angle(phase):
    """phase 0..1 (0 new, 0.25 first quarter, 0.5 full, 0.75 last quarter) -> elongation in radians."""
    return (float(phase) % 1.0) * 2.0 * math.pi


def phase_light(phase):
    """Moonlight at this phase against the full moon (the phase law of the Moon: a quarter gives about a tenth)."""
    a = abs(180.0 - math.degrees(phase_angle(phase)))            # phase angle: 0 = full
    if a > 170.0:
        return 0.0
    return 10.0 ** (-0.4 * (0.026 * a + 4e-9 * a ** 4))


def lit_dir(phase):
    """Where the sunlight comes from on the disc, in its own frame (x right, z towards the viewer): new = from behind,
    first quarter = from the right (the lit half on the right, as from the northern hemisphere), full = from the
    viewer, last quarter = from the left."""
    e = phase_angle(phase)
    return math.sin(e), -math.cos(e)
