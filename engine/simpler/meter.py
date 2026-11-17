"""(1.79.0) Esposizione sull'inquadratura: the exposure a camera's light meter would choose for what the camera sees.

(Luca, «test GI»: a forest at noon came out almost black at exposure 0 - the light of sun and sky was right, but the
camera saw only the shade under the trees; a photographer opens up 3-4 stops there.) From the linear light of a render
(before exposure and look): the mean brightness (log average, on small blocks so the grain of a quick pass does not pull
it down) and the brightest 3%. The exposure that brings the mean to KEY without taking the brightest 3% over TOP is
used when it OPENS more than the automatic exposure of the Ambiente: never darker than before, at most MAX stops more,
less and less at dusk and none at night (a night stays a night). The «Esposizione» slider adds to it.
Used by the engine (render.py: the path tracing view, the final render) and by the final render job (render_job.py),
so it imports nothing else of Simpler.
"""
import math
import os

import bpy

KEY = 0.10
TOP = 0.9
MAX = 6.0


def measure(scene, folder):
    """EV that exposes the last render (the Render Result) as a camera meter would, or None."""
    import numpy as np
    img = bpy.data.images.get("Render Result")
    if img is None:
        return None
    path = os.path.join(folder, "meter.exr")
    st = scene.render.image_settings
    fmt, depth, codec = st.file_format, st.color_depth, getattr(st, "exr_codec", None)
    try:
        st.file_format = "OPEN_EXR"
        st.color_depth = "16"
        if codec is not None:
            st.exr_codec = "NONE"                 # (quick to write and read: it is removed at once)
        img.save_render(path, scene=scene)        # (EXR: the linear light, before exposure and look)
    finally:
        st.file_format = fmt
        try:
            st.color_depth = depth
            if codec is not None:
                st.exr_codec = codec
        except TypeError:
            pass
    m = bpy.data.images.load(path, check_existing=False)
    try:
        w, h = m.size
        if w > 480:                               # (a final image: measured on a small copy, little memory)
            w, h = 480, max(4, int(round(h * 480.0 / w)))
            m.scale(w, h)
        px = np.empty(w * h * 4, np.float32)
        m.pixels.foreach_get(px)
    finally:
        bpy.data.images.remove(m)
        try:
            os.remove(path)
        except OSError:
            pass
    if w < 4 or h < 4:
        return None
    lum = px.reshape(h, w, 4)[..., :3] @ np.array([0.2126, 0.7152, 0.0722], np.float32)
    b = max(1, int(round(w / 48.0)))          # (blocks of about 1/48 of the width)
    hh, ww = h - h % b, w - w % b
    lum = lum[:hh, :ww].reshape(hh // b, b, ww // b, b).mean(axis=(1, 3))
    lum = lum[np.isfinite(lum)]
    if lum.size == 0:
        return None
    mean = float(np.exp(np.mean(np.log(np.clip(lum, 1e-4, None)))))
    top = float(np.percentile(lum, 97))
    return min(math.log2(KEY / max(mean, 1e-6)), math.log2(TOP / max(top, 1e-6)))


def combine(auto, ev, night_ev):
    """The automatic exposure (EV) with the measurement: auto of the Ambiente, opened up to ev (see above)."""
    auto = float(auto)
    if ev is None:
        return auto
    room = MAX * max(0.0, 1.0 - max(0.0, auto) / night_ev)
    return max(auto, min(float(ev), auto + room))


def fill_energy(fraction, ev):
    """Strength of the «Luce di riempimento» at the automatic exposure ev (as render.fill_energy)."""
    return max(0.0, float(fraction)) * 0.18 * math.pi / (0.5 * 2.0 ** float(ev))


def tiny(scene, folder, width, height):
    """A 160-point render of the framing, measured (when the image itself cannot be measured first)."""
    r, cy = scene.render, scene.cycles
    saved = (r.resolution_x, r.resolution_y, r.resolution_percentage, cy.samples, cy.use_denoising, cy.time_limit)
    k = 160.0 / max(width, height, 1)
    try:
        r.resolution_x, r.resolution_y = max(16, int(width * k)), max(16, int(height * k))
        r.resolution_percentage = 100
        cy.samples, cy.use_denoising, cy.time_limit = 8, False, 0.0
        bpy.ops.render.render(write_still=False)
        return measure(scene, folder)
    finally:
        r.resolution_x, r.resolution_y, r.resolution_percentage, cy.samples, cy.use_denoising, cy.time_limit = saved
