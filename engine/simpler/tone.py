"""Shadows and highlights: the two sliders of a photo editor ("Ombre" / "Luci"), on the finished picture.

On the brightness of each pixel, keeping its colour (the three channels scaled together, as Lightroom does: a
curve per channel turned a warm sunset sky grey). Brightness Y = Rec.709 luminance of the display values, then
Y' = f(Y) and RGB' = RGB * Y'/Y.

shadows s (0..1): Y + 2.2 s Y (1 - Y)^6 - strongest on the near blacks: at 100% 3% -> 8.5%, 10% -> 22%,
30% -> 38%, 50% -> 52%; black stays black.
highlights h (0..1): Y - 0.8 h Y^4 (1 - Y) - at 100% 90% -> 85%, 80% -> 73%; white stays white.
Both keep the curve rising at any setting.

Where: the final render (apply_file on the saved PNG / JPEG / TIFF; EXR left alone: it holds the light before tone
mapping), the path tracing frame of the view (render.retone: the raw frame is kept, the curve is applied again when
the sliders move - no new render), the real-time view (viewer.js: the same formulas in the tone mapping shader).
"""
import os


def _f(y, s, h):
    return y + 2.2 * s * y * (1.0 - y) ** 6 - 0.8 * h * y ** 4 * (1.0 - y)


def active(shadows, highlights):
    return float(shadows) > 0.001 or float(highlights) > 0.001


def apply_rgb(px, shadows, highlights):
    """px: float array (..., 3 or 4) of display values 0..1, changed in place."""
    import numpy as np
    s = max(0.0, min(1.0, float(shadows)))
    h = max(0.0, min(1.0, float(highlights)))
    rgb = np.clip(px[..., :3], 0.0, 1.0)
    y = rgb @ np.array([0.2126, 0.7152, 0.0722], dtype=np.float32)
    y2 = np.clip(_f(y, s, h), 0.0, 1.0)
    k = np.where(y > 1e-5, y2 / np.maximum(y, 1e-5), 1.0)[..., None]
    out = rgb * k
    # a saturated colour lifted past 1 in one channel: the excess goes to the others (towards white), not clipped
    over = np.max(out, axis=-1, keepdims=True)
    t = np.clip((over - 1.0) / np.maximum(over, 1e-5), 0.0, 1.0)
    out = np.minimum(out, 1.0) * (1 - t) + t
    px[..., :3] = np.clip(out, 0.0, 1.0)
    return px


def apply_file(path, shadows, highlights):
    """The curve on a saved picture (PNG 8/16 bit, JPEG, TIFF). Returns True if applied."""
    return finish_file(path, {"toneShadows": shadows, "toneHighlights": highlights})


def finish_file(path, cfg, aspect=0.0):
    """Ombre / Luci and the camera effects (post.py) on a saved picture (PNG 8/16 bit, JPEG, TIFF): what the render
    settings ask, nothing when all is neutral. aspect: the frame inside the picture (the view: the whole viewport).
    Returns True if applied."""
    from . import post
    cfg = cfg or {}
    shadows, highlights = cfg.get("toneShadows", 0.0) or 0.0, cfg.get("toneHighlights", 0.0) or 0.0
    fx = post.active(cfg)
    if not active(shadows, highlights) and not fx:
        return False
    ext = os.path.splitext(path)[1].lower()
    fmt = {".png": "PNG", ".jpg": "JPEG", ".jpeg": "JPEG", ".tif": "TIFF", ".tiff": "TIFF"}.get(ext)
    if fmt is None:
        return False
    import bpy
    import numpy as np
    im = bpy.data.images.load(path, check_existing=False)
    try:
        im.colorspace_settings.name = "Non-Color"          # the values of the file, as they are (display values)
        w, h = im.size[:]
        px = np.empty(w * h * 4, dtype=np.float32)
        im.pixels.foreach_get(px)
        px = px.reshape(-1, 4)
        if active(shadows, highlights):
            apply_rgb(px, shadows, highlights)
        if fx:
            img = px.reshape(h, w, 4)[::-1, :, :3]                   # (Blender: the bottom row first)
            px.reshape(h, w, 4)[::-1, :, :3] = post.apply_rgb(img, cfg, aspect)
        im.pixels.foreach_set(px.ravel())
        deep = im.is_float or im.depth > 32
        scene = bpy.context.scene
        st = scene.render.image_settings
        keep = (st.file_format, st.color_depth, st.quality, getattr(st, "color_management", "FOLLOW_SCENE"), st.color_mode)
        try:
            try:
                st.media_type = "IMAGE"
            except (AttributeError, TypeError):
                pass
            st.file_format = fmt
            if fmt in ("PNG", "TIFF"):
                st.color_depth = "16" if deep else "8"
            st.color_mode = "RGBA" if im.channels >= 4 and fmt != "JPEG" else "RGB"
            if fmt == "JPEG":
                st.quality = 92
            try:
                st.color_management = "OVERRIDE"            # written as they are: no view transform a second time
                st.view_settings.view_transform = "Standard"
                st.view_settings.look = "None"
                st.view_settings.exposure = 0.0
                st.view_settings.gamma = 1.0
                st.display_settings.display_device = "sRGB"
                st.linear_colorspace_settings.name = "Non-Color"
            except (AttributeError, TypeError):
                pass
            im.save_render(path, scene=scene)
        finally:
            st.file_format, st.color_depth, st.quality = keep[0], keep[1], keep[2]
            try:
                st.color_mode = keep[4]
            except TypeError:
                pass
            try:
                st.color_management = keep[3]
            except (AttributeError, TypeError):
                pass
        return True
    finally:
        bpy.data.images.remove(im)
