"""GPU setup, quality presets, caustics, camera, progressive viewport, picking and final render."""
import math
import os
import tempfile
import threading
import time

import bpy
from mathutils import Vector

from .core import CM, ID_KEY, INTERNAL_KEY, ApiError, find, log, managed_objects
from . import materials, proxies, twins
from .i18n import tr
from . import tempdirs
from . import fullspeed

CAMERA_NAME = "Simpler Camera"

QUALITY = {
    "personalizzata": (512, 16, 0.01),
    # samples, max bounces, adaptive threshold
    "bozza":  (64, 8, 0.05),
    "alta":   (512, 16, 0.01),
    "finale": (2048, 24, 0.005),
}

# Full path-tracing configuration (what the "Rendering" panel edits). A quality preset fills every field;
# editing a single field turns the preset into "personalizzata".
PRESETS = {
    "bozza": dict(samples=64, viewportSamples=128, noiseThreshold=0.05, bounces=8, diffuse=3, glossy=4,
                  transmission=8, transparent=8, volume=0, clampDirect=0.0, clampIndirect=10.0, blurGlossy=1.0,
                  fastGI=False, aoBounces=1),
    "alta": dict(samples=512, viewportSamples=256, noiseThreshold=0.01, bounces=16, diffuse=4, glossy=8,
                 transmission=16, transparent=16, volume=0, clampDirect=0.0, clampIndirect=10.0, blurGlossy=0.5,
                 fastGI=False, aoBounces=1),
    "finale": dict(samples=2048, viewportSamples=512, noiseThreshold=0.005, bounces=24, diffuse=6, glossy=12,
                   transmission=24, transparent=24, volume=2, clampDirect=0.0, clampIndirect=20.0, blurGlossy=0.25,
                   fastGI=False, aoBounces=1),
}
CONFIG_KEYS = {
    "samples": (int, 1, 65536), "viewportSamples": (int, 1, 4096), "noiseThreshold": (float, 0.0005, 0.5),
    "bounces": (int, 0, 128), "diffuse": (int, 0, 128), "glossy": (int, 0, 128), "transmission": (int, 0, 128),
    "transparent": (int, 0, 256), "volume": (int, 0, 128), "clampDirect": (float, 0.0, 10000.0),
    "clampIndirect": (float, 0.0, 10000.0), "blurGlossy": (float, 0.0, 10.0), "fastGI": (bool, 0, 1),
    "aoBounces": (int, 0, 16), "denoise": (bool, 0, 1), "causticsReflective": (bool, 0, 1),
    "causticsRefractive": (bool, 0, 1), "causticsReflected": (bool, 0, 1), "exposure": (float, -10.0, 10.0), "look": (str, 0, 0),
    "textureLimit": (int, -1, 8192), "realtimeTextures": (int, -1, 8192),
    "toneShadows": (float, 0.0, 1.0), "toneHighlights": (float, 0.0, 1.0), "fill": (float, 0.0, 1.0),
    "colorRender": (str, 0, 0), "meterExposure": (bool, 0, 1),
    # camera effects (post.py): on the picture, no new render
    "fxTemp": (float, 2000.0, 12000.0), "fxTint": (float, -1.0, 1.0), "fxContrast": (float, -1.0, 1.0),
    "fxSaturation": (float, 0.0, 2.0), "fxLut": (str, 0, 0), "fxLutAmount": (float, 0.0, 1.0), "fxBloom": (float, 0.0, 1.0),
    "fxVignette": (float, 0.0, 1.0), "fxCA": (float, 0.0, 1.0), "fxGrain": (float, 0.0, 1.0), "fxGrainSize": (float, 0.0, 1.0),
    "fxSharpen": (float, 0.0, 1.0),
}
TONE_KEYS = ("toneShadows", "toneHighlights", "fxTemp", "fxTint", "fxContrast", "fxSaturation", "fxLut", "fxLutAmount",
             "fxBloom", "fxVignette", "fxCA", "fxGrain", "fxGrainSize", "fxSharpen")     # on the picture shown or saved (tone.py, post.py): no new render
TEXTURE_LIMITS = [-1, 0, 512, 1024, 2048, 4096, 8192]   # -1 = automatic, 0 = full size
LOOKS = ["None", "AgX - Very Low Contrast", "AgX - Low Contrast", "AgX - Medium Low Contrast", "AgX - Base Contrast",
         "AgX - Medium High Contrast", "AgX - High Contrast", "AgX - Very High Contrast", "AgX - Punchy"]


def default_config(preset="alta"):
    cfg = dict(PRESETS[preset])
    cfg.update(denoise=True, causticsReflective=True, causticsRefractive=True, causticsReflected=False, exposure=0.0,
               look="AgX - Base Contrast", textureLimit=-1, realtimeTextures=0, toneShadows=0.0, toneHighlights=0.0, fill=0.0, colorRender="natural",
               meterExposure=True)
    # (1.79.0) new projects: «Contrasto base» (Luca: the deep shadows of the forest; Medium High darkened them more) and
    # «Esposizione sull'inquadratura» on (see exposure_auto)
    from . import post
    cfg.update(post.DEFAULTS)
    return cfg


# Progressive viewport passes: (resolution scale, samples, denoise, time limit in seconds).
# The time limits keep the engine responsive: a command never waits more than ~one pass.
# The last pass has no time limit: a command arriving meanwhile interrupts it at once (breaker.py), so the view can
# reach all the samples asked for (with a 4 s limit a heavy scene - water, volumes, caustics - stopped at a few dozen
# samples and stayed grainy while the badge said 512). The 4 s pass before it gives a good picture quickly.
VIEWPORT_PASSES = [(0.25, 2, False, 0), (0.5, 8, True, 0.5), (1.0, 32, True, 1.5), (1.0, 256, True, 4.0), (1.0, 100000, True, 0)]
PREP_SLOW = 1.5                # (1.76.50) seconds of preparing a pass over which the in-between passes are left out
PASSES_SKIPPABLE = (1, 3)


class RenderState:
    def __init__(self):
        self.device = "CPU"
        self.quality = "alta"
        self.caustics = False
        self.config = default_config("alta")
        self.live = False  # progressive Cycles viewport on/off ("Realistica" view)
        self.vp_size = (1280, 720)
        self.camera = {"target": [0.0, 0.0, 160.0], "distance": 600.0, "yaw": -60.0, "pitch": 1.5, "lens": 50.0}
        # viewport
        self.dirty = True
        self.pass_index = 0
        self.epoch = 0  # bumped by every change: a frame is current only if rendered in the current epoch
        self.changed_at = time.time()   # when the image became out of date (for the timing lines in the log)
        self.last_prep = 0.0            # (1.76.50) seconds Cycles prepared the scene in the last pass
        self.waited_textures = 0.0      # seconds this image waited for the reduced textures
        self.frame = b""
        self.frame_info = {"version": 0, "pass": -1, "samples": 0, "width": 0, "height": 0, "ms": 0}
        self.vp_error = ""  # why the last path-tracing pass failed (shown in the view)
        self.meter_ev = None      # (1.79.0) exposure measured on what the camera sees (exposure_auto), None = not yet
        self.meter_epoch = -1     # the epoch of the scene it was measured in
        self.rendering = False    # a path tracing pass is running (it can be interrupted)
        self.interrupted = False
        self.lock = threading.Lock()
        self.tmp = tempdirs.make("simpler_")       # (removed at the next start when this engine is gone)


STATE = RenderState()


# ---------------------------------------------------------------- device

def setup_device():
    scene = bpy.context.scene
    scene.render.engine = "CYCLES"
    scene.render.use_persistent_data = True  # keep BVH/textures between renders
    try:
        prefs = bpy.context.preferences.addons["cycles"].preferences
    except KeyError:
        prefs = None
    chosen = "CPU"
    if prefs is not None:
        for backend in ("OPTIX", "CUDA", "HIP", "ONEAPI", "METAL"):
            try:
                prefs.compute_device_type = backend
            except TypeError:
                continue
            (prefs.refresh_devices if hasattr(prefs, "refresh_devices") else prefs.get_devices)()
            gpus = [d for d in prefs.devices if d.type == backend]
            if gpus:
                for d in prefs.devices:
                    d.use = d.type == backend
                chosen = backend
                break
    scene.cycles.device = "GPU" if chosen != "CPU" else "CPU"
    STATE.device = chosen
    return chosen


import contextlib
import json


@contextlib.contextmanager
def _nothing():
    yield


def cpu_threads():
    """Leave two CPU cores to Windows and the app, so heavy work never freezes the computer."""
    n = os.cpu_count() or 4
    return max(1, n - 2) if n > 4 else max(1, n - 1)


def limit_threads(scene):
    if scene.render.threads_mode != "FIXED":
        scene.render.threads_mode = "FIXED"
    if scene.render.threads != cpu_threads():
        scene.render.threads = cpu_threads()


_DIAG = {"last": None}


def _diag_file():
    """Diagnostics on request: with the file diag.on in %LOCALAPPDATA%\\Simpler the last pass of the view is also
    saved as diag.exr there, with the image before the denoiser, its albedo and normal and the samples of every pixel
    (to see why the denoiser makes blotches on a scene that cannot be copied elsewhere). The file is removed after."""
    base = os.path.join(os.environ.get("LOCALAPPDATA") or tempfile.gettempdir(), "Simpler")
    flag = os.path.join(base, "diag.on")
    return os.path.join(base, "diag.exr") if os.path.isfile(flag) else None


def _diag_passes(scene, on):
    vl = scene.view_layers[0]
    for attr in ("denoising_store_passes", "pass_debug_sample_count"):
        try:
            setattr(vl.cycles, attr, on)
        except (AttributeError, TypeError):
            pass


def _diag_materials():
    """The glowing pieces and every piece around them (lamps: bulb, shade, cage) with their materials node by node:
    the grain on lamp shades depends on how light, glass and opacity are put together."""
    glows = [o for o in bpy.context.scene.objects if o.type == "MESH" and not twins.is_twin(o) and not o.hide_render
             and any(_emissive(s.material) for s in o.material_slots)]
    near, out = [], []
    for g in glows:
        c = g.matrix_world.translation
        for o in bpy.context.scene.objects:
            if o.type == "MESH" and not twins.is_twin(o) and o not in near:
                bb = [o.matrix_world @ Vector(v) for v in o.bound_box]
                lo = Vector(map(min, *bb)) - Vector((0.3, 0.3, 0.3)); hi = Vector(map(max, *bb)) + Vector((0.3, 0.3, 0.3))
                if lo.x <= c.x <= hi.x and lo.y <= c.y <= hi.y and lo.z <= c.z <= hi.z:
                    near.append(o)
    mats = []
    for o in near[:40]:
        bb = [o.matrix_world @ Vector(v) for v in o.bound_box]
        size = Vector(map(max, *bb)) - Vector(map(min, *bb))
        out.append(f"OBJ {o.name} glow={o in glows} size={tuple(round(x, 3) for x in size)} faces={len(o.data.polygons)} "
                   f"thick={round(_thickness(o), 4)} mats={[s.material.name if s.material else None for s in o.material_slots]} "
                   f"vis_shadow={o.visible_shadow} caster={o.cycles.is_caustics_caster}")
        for s in o.material_slots:
            if s.material is not None and s.material not in mats:
                mats.append(s.material)
    for m in mats:
        out.append(f"MAT {m.name} blend={getattr(m, 'surface_render_method', '')} "
                   f"transparent_shadow={getattr(m, 'use_transparent_shadow', '')}")
        if not m.use_nodes or m.node_tree is None:
            continue
        for n in m.node_tree.nodes:
            vals = []
            for i in n.inputs:
                if i.is_linked:
                    vals.append(f"{i.name}<-{i.links[0].from_node.name}")
                elif hasattr(i, "default_value") and i.name in ("Base Color", "Roughness", "Alpha", "Transmission Weight",
                                                                 "Emission Color", "Emission Strength", "Strength",
                                                                 "Color", "IOR", "Fac", "Metallic", "Weight"):
                    v = i.default_value
                    vals.append(f"{i.name}={tuple(round(x, 3) for x in v) if hasattr(v, '__len__') else round(v, 3)}")
            img = getattr(n, "image", None)
            out.append(f"   {n.type} '{n.name}' {' '.join(vals)}" + (f" image={img.name} {tuple(img.size)}" if img else ""))
    return "\n".join(out)


def _diag_alpha_blend(path):
    """The pieces whose material uses an opacity map (at most 12, the selection first), with materials and images,
    in a small .blend: to reproduce their grain elsewhere."""
    try:
        def has_alpha(o):
            for s in o.material_slots:
                m = s.material
                if m and m.use_nodes and m.node_tree:
                    for n in m.node_tree.nodes:
                        if n.type == "BSDF_PRINCIPLED" and n.inputs["Alpha"].is_linked:
                            return True
            return False
        obs = [o for o in bpy.context.scene.objects if o.type == "MESH" and not twins.is_twin(o)
               and not o.get(INTERNAL_KEY) and has_alpha(o)]
        try:
            with open(os.path.join(os.path.dirname(path), "diag.on"), encoding="utf-8") as f:
                words = [w.strip().lower() for w in f.read().replace(",", "\n").splitlines() if w.strip()]
        except OSError:
            words = []

        def wanted(o):          # (names written in diag.on: those pieces first, also without an opacity map)
            names = [o.name.lower()] + [s.material.name.lower() for s in o.material_slots if s.material]
            return any(w in n for w in words for n in names)
        if words:
            obs = [o for o in bpy.context.scene.objects if o.type == "MESH" and not twins.is_twin(o)
                   and not o.get(INTERNAL_KEY) and wanted(o)] + [o for o in obs if not wanted(o)]
        obs.sort(key=lambda o: (not wanted(o), not o.select_get(), len(o.data.polygons)))
        obs = obs[:12]
        bpy.data.libraries.write(path, set(obs), fake_user=True, path_remap="ABSOLUTE", compress=True)
        print(f"SIMPLER_DIAG alpha pieces {[o.name for o in obs]} -> {path}", flush=True)
    except Exception as ex:
        print(f"SIMPLER_DIAG alpha failed {ex}", flush=True)


def _image_format_back(scene):
    """Single images again (the diagnostics switch the output to multilayer EXR: left that way, every later image
    of the view failed with 'enum JPEG not found')."""
    st = scene.render.image_settings
    try:
        st.media_type = "IMAGE"
    except (AttributeError, TypeError):
        pass


def _diag_save(scene, path):
    try:
        img = bpy.data.images.get("Render Result")
        st = scene.render.image_settings
        old = (st.media_type, st.file_format, st.color_depth) if hasattr(st, "media_type") else None
        try:
            st.media_type = "MULTI_LAYER_IMAGE"
        except (AttributeError, TypeError):
            pass
        st.file_format = "OPEN_EXR_MULTILAYER"
        st.color_depth = "32"
        try:
            if os.path.isfile(path):
                os.remove(path)               # (an old diag.exr still open in another program cannot be replaced)
        except OSError:
            path = path[:-4] + time.strftime("-%H%M%S") + ".exr"
        try:
            img.save_render(path, scene=scene)
        finally:
            _image_format_back(scene)
        cfg = {k: getattr(scene.cycles, k) for k in ("samples", "adaptive_threshold", "adaptive_min_samples",
                                                     "caustics_reflective", "caustics_refractive", "blur_glossy",
                                                     "sample_clamp_indirect", "sample_clamp_direct", "max_bounces",
                                                     "diffuse_bounces", "glossy_bounces", "transmission_bounces",
                                                     "use_light_tree", "denoiser", "denoising_prefilter",
                                                     "denoising_quality", "denoising_use_gpu", "time_limit")
               if hasattr(scene.cycles, k)}
        cfg["exposure"] = scene.view_settings.exposure
        cfg["look"] = scene.view_settings.look
        with open(path + ".txt", "w", encoding="utf-8") as f:
            f.write(repr(cfg) + "\n\n" + _diag_materials())
        _diag_alpha_blend(os.path.join(os.path.dirname(path), "diag_alpha.blend"))
        os.remove(os.path.join(os.path.dirname(path), "diag.on"))
        print(f"SIMPLER_DIAG saved {path}", flush=True)
    except Exception as ex:
        print(f"SIMPLER_DIAG failed {ex}", flush=True)


def _diag_line():
    """One log line when what drives the noise changes: the pieces with real caustics (MNEE), the lights inside
    glass, the exposure. For the grain that comes and goes on lamp shades and glass (to find what differs)."""
    casters = sorted(o.name for o in bpy.context.scene.objects if o.type == "MESH" and o.cycles.is_caustics_caster
                     and not twins.is_twin(o))
    lights = sum(1 for o in bpy.context.scene.objects if o.type == "LIGHT" and o.data.cycles.is_caustics_light)
    emit = sum(1 for m in bpy.data.materials if m.users and _emissive(m))
    # the lamps (for the night: which are lit, and how many sit inside the models of distributions, which the
    # real-time view does not draw as lights)
    lamps = [o for o in bpy.context.scene.objects if o.type == "LIGHT" and not o.get("simpler_cloud_sun")]
    lit = sum(1 for o in lamps if "simpler_power" not in o and o.data.energy > 0)
    try:
        from . import paint
        inside = sum(1 for ob in paint.scatter_originals() for o in [ob] + list(ob.children_recursive) if o.type == "LIGHT")
    except Exception:
        inside = -1
    key = (STATE.caustics, tuple(casters), lights, emit, len(lamps), lit, inside)
    if key != _DIAG["last"]:
        _DIAG["last"] = key
        print(f"SIMPLER_DIAG caustics={STATE.caustics} casters={len(casters)} {casters[:12]} caustic_lights={lights} "
              f"emissive_materials={emit} lamps={len(lamps)} lit={lit} lamps_in_distributions={inside}", flush=True)


def _toned_frame(path):
    """The frame of the view with Ombre / Luci (tone.py): the raw frame is kept next to it, so moving the sliders
    only applies the curve again (retone), without a new render."""
    import shutil
    from . import tone
    raw = path[:-4] + "_raw.jpg"
    try:
        shutil.copyfile(path, raw)
        tone.finish_file(path, STATE.config, _view_aspect())
    except Exception as ex:
        log("SIMPLER_TONE", f"view: {ex}")
    with open(path, "rb") as f:
        return f.read()


def retone():
    """Ombre / Luci changed: the last frame of the view again from its raw copy (a new version for the viewer)."""
    import shutil
    path = os.path.join(STATE.tmp, "viewport.jpg")
    raw = path[:-4] + "_raw.jpg"
    if not os.path.isfile(raw) or not STATE.frame:
        return
    try:
        shutil.copyfile(raw, path)
        data = _toned_frame_from(path)
    except Exception as ex:
        log("SIMPLER_TONE", f"retone: {ex}")
        return
    with STATE.lock:
        STATE.frame = data
        info = dict(STATE.frame_info)
        info["version"] = info["version"] + 1
        STATE.frame_info = info


def _toned_frame_from(path):
    from . import tone
    tone.finish_file(path, STATE.config, _view_aspect())
    with open(path, "rb") as f:
        return f.read()


def _view_aspect():
    """The frame of the chosen format inside the view (the view frame covers the whole viewport): the camera effects
    centre on it (vignette, aberration) and take their sizes from it, as in the final render."""
    try:
        return FORMATS.get(cam_get("format")) or 0.0
    except Exception:
        return 0.0


def adaptive_sampling(scene, threshold, samples, min_div=8, min_floor=16):
    """Adaptive sampling that keeps its promise after the exposure. Cycles stops a pixel when its noise, measured on
    the linear values, falls under the threshold - relative to the square root of the brightness, so with +4 EV
    (a dark interior lit by two windows, a night) every pixel looked 4 times noisier than allowed, and the dark
    pixels stopped first: next to pixels that went on, the denoiser turned them into black blotches (with 512 or
    2048 samples worse than with 256, where the cap stopped all of them alike). The threshold follows the exposure
    (/ 2^(EV/2)) and no pixel stops before half of the samples in the view, a quarter in the final render (rare
    light, through a window, has been found: diag.exr of a kitchen showed 22% of the pixels stopped at 80 of 512,
    in a salt-and-pepper pattern the denoiser made into blotches). Final render since 1.17.4: an eighth, never under
    256 (measured on a volumetric sunset, 2048 samples: 1/4 -> 1/8 = 15% less time, 99% of the pixels the same to
    1/255; the kitchen blotches came from a minimum of 80)."""
    ev = float(scene.view_settings.exposure)
    cy = scene.cycles
    cy.adaptive_threshold = max(0.0005, threshold / (2.0 ** (max(0.0, ev) / 2.0)))
    cy.adaptive_min_samples = min(samples, max(min_floor, samples // min_div))
    try:
        cy.denoising_quality = "HIGH"
    except (AttributeError, TypeError):
        pass


# ---------------------------------------------------------------- exposure on the framing (1.79.0, see meter.py)
METER_STEP = 0.15         # a new measurement closer than this keeps the old value (no flicker while moving)


def exposure_auto():
    """The automatic part of the exposure (EV): the Ambiente's, opened up by the measurement of the framing."""
    from . import ambience, meter
    a = float(ambience.auto_ev())
    if not STATE.config.get("meterExposure") or not ambience.auto_exposure_on():
        return a
    return meter.combine(a, STATE.meter_ev, ambience.NIGHT_EV)


def _meter_store(ev, epoch):
    old = STATE.meter_ev
    STATE.meter_epoch = epoch
    if ev is None or (old is not None and abs(ev - old) < METER_STEP):
        return False
    STATE.meter_ev = ev
    return True


def _meter_final(scene, width, height, fresh, own_process):
    """Before a final render. The measurement of the path tracing view when it is of this same scene (fresh); else
    the render job measures the image itself (render_job.py: scene["simpler_meter"]), or here a 160-point render."""
    from . import ambience, meter
    scene.pop("simpler_meter", None)
    c = STATE.config
    if fresh or not c.get("meterExposure") or not ambience.auto_exposure_on():
        return
    if own_process:
        import json
        scene["simpler_meter"] = json.dumps({"user": float(c["exposure"]), "auto": float(ambience.auto_ev()),
                                             "night": ambience.NIGHT_EV, "fill": float(c.get("fill", 0.0))})
        return
    try:
        _meter_store(meter.tiny(scene, STATE.tmp, width, height), STATE.epoch)
    except Exception as ex:  # noqa: BLE001 - the render goes on with the automatic exposure of the Ambiente
        log("SIMPLER_METER", f"final: {ex}")


def fog_denoise(scene, final):
    """(16/11, v15 of the haze, ambience._fog_tree) the denoising of the amount of haze - the grain on volumetric clouds in front
    of a hillside in the haze - only in the final render: in the view it would cost a denoising at every pass.
    (17/11, v16 of the haze) now off everywhere: the haze of the pixels of a volume is taken from the surfaces around,
    already without grain. The denoising changed nothing any more (0.46 without, 0.47 with, on the cloud in front of a
    hillside) and on Luca's valley, before v16, it even turned the dark dots into bright ones (its guides change at random
    inside a volume); it cost a denoising at every final render. To turn it on again in the final render: FOG_DENOISE = True."""
    tree = getattr(scene, "compositing_node_group", None)
    node = tree.nodes.get("fog_smooth") if tree is not None else None
    off = not (final and FOG_DENOISE)
    if node is not None and node.mute != off:
        node.mute = off


FOG_DENOISE = False


def _apply_common(scene, final=False):
    limit_threads(scene)
    c = STATE.config
    cy = scene.cycles
    cy.use_adaptive_sampling = True
    cy.use_denoising = bool(c["denoise"])
    # OpenImageDenoise (on the graphics card when it can): cleaner than OptiX on glass, water and volumes, where the
    # OptiX denoiser kept the grain of the waves
    try:
        cy.denoiser = "OPENIMAGEDENOISE"
    except TypeError:
        pass
    for attr, val in (("denoising_use_gpu", STATE.device in ("OPTIX", "CUDA", "HIP", "ONEAPI", "METAL")), ("denoising_prefilter", "ACCURATE")):
        try:
            setattr(cy, attr, val)
        except (AttributeError, TypeError):
            pass
    if c.get("colorRender") == "vivid":
        # "Vivida": Khronos PBR Neutral keeps saturated bright colours (sunsets, coloured lights) where AgX turns
        # them pale towards white; it has no looks
        scene.view_settings.view_transform = "Khronos PBR Neutral"
        scene.view_settings.look = "None"
    else:
        scene.view_settings.view_transform = "AgX"
        try:
            scene.view_settings.look = c["look"]
        except TypeError:
            pass
    from . import ambience
    scene.view_settings.exposure = c["exposure"] + exposure_auto()     # (automatic exposure: Ambiente + framing)
    # The total limit counts every bounce: at 0 (or below the refractions) a ray stops on the first glass or water
    # surface and they turn black, from above and from below. With glass or water in the scene the total is at least
    # the refractions: only the rays that really cross a glass go on, the others stop at their own limits (diffuse,
    # glossy...), so the cost stays that of the glass alone.
    from . import glass
    total = c["bounces"]
    if glass.PRESENT["glass"]:
        total = max(total, c["transmission"])
    vol = c["volume"]
    if any(o.get("simpler_fog_domain") or o.get("simpler_water_body") for o in scene.objects):
        # volumetric fog or the body of the water: the light must be able to scatter in it once at least
        total = max(total, 2)
        vol = max(vol, 1)
        if any(o.get("simpler_fog_domain") for o in scene.objects):
            # (1.75.50) the fog: light scattered several times by the droplets - a real fog glows from within and
            # around every light (one bounce: greyer and darker than a photo). 2 in the view, 4 in the final render
            vol = max(vol, 4 if final else 2)
            total = max(total, vol + 1)
    from . import volumetric
    vb = volumetric.bounces_wanted(scene)
    vol_models = vb > 0
    if vol_models:
        # volumetric models (clouds, smoke): white only with light scattered several times inside them (with one
        # bounce a cloud is grey). Their «Rimbalzi della luce», the same in the view and in the final render.
        # (16/11, Luca: «perché c'è 12?») the final render used at least 12 whatever the panel said: the value chosen
        # was ignored exactly where it matters (fewer bounces = less grain in a thin cloud). What you set is what you get.
        total = max(total, vb)
        vol = max(vol, vb)
    cy.max_bounces = total
    cy.diffuse_bounces = c["diffuse"]
    cy.glossy_bounces = c["glossy"]
    cy.transmission_bounces = c["transmission"]
    cy.transparent_max_bounces = c["transparent"]
    cy.volume_bounces = vol
    fog_denoise(scene, final)
    cy.sample_clamp_direct = c["clampDirect"]
    cy.sample_clamp_indirect = c["clampIndirect"]
    cy.blur_glossy = c["blurGlossy"]
    cy.caustics_refractive = bool(c["causticsRefractive"])
    cy.caustics_reflective = bool(c["causticsReflective"])
    cy.use_fast_gi = bool(c["fastGI"])
    cy.ao_bounces = c["aoBounces"]
    cy.ao_bounces_render = c["aoBounces"]
    try:
        # (volumetric clouds: clouds.render_settings). Volumetric models: ray marching too - 3 to 6 times faster
        # than null scattering on their noise, the same picture (measured: 59 s -> 10 s, volumetric.py)
        cy.volume_biased = vol_models
        cy.volume_step_rate = 1.0
    except AttributeError:
        pass


# ---------------------------------------------------------------- caustics

def apply_caustics(enabled):
    """One switch for the user: glass, gems and water cast shadow caustics (MNEE) onto everything else, lit by every
    light (the sun of the Ambiente too)."""
    STATE.caustics = enabled
    refresh_caustics(force=True)


def is_caustic_caster(ob):
    """Does this piece draw sharp caustics (MNEE)? Glass, gems and water that bend the light - not the thin flat
    panes of windows and glass doors: through MNEE they would only stop the sun (a room behind a window went dark
    with the caustics on), and they make no caustic worth the cost anyway. Water with real waves always does."""
    if ob.type != "MESH" or not any(materials.is_transmissive(s.material) for s in ob.material_slots):
        return False
    from . import water
    wm = water.water_material(ob)
    if wm is not None and water.shape_of(ob) != "shell":
        return water.mat_settings(wm)["waves"]["on"]      # flat water makes no caustic: only with real waves
    # (water on an open object with walls - a glass, a vase: its surface only, as a glass)
    return _thickness(ob) >= 0.02              # thicker than 2 cm: a solid piece of glass, a gem, a vase


_THICK = {}


def _thickness(ob):
    """How thick a piece is, in metres: 2 × volume / surface of its closed mesh (a pane: its thickness; a sphere: 2/3
    of its radius). Open meshes (a single plane): 0. Cached per mesh and scale. Windows joined into one object stay
    thin, whatever their overall size."""
    me = ob.data
    sc = ob.matrix_world.to_scale()
    key = (me.name, len(me.polygons), round(sc.x, 4), round(sc.y, 4), round(sc.z, 4))
    if key in _THICK:
        return _THICK[key]
    import bmesh
    bm = bmesh.new()
    try:
        bm.from_mesh(me)
        bm.transform(__import__("mathutils").Matrix.Diagonal((*sc, 1.0)))
        if any(not e.is_manifold for e in bm.edges):
            t = 0.0
        else:
            area = sum(f.calc_area() for f in bm.faces)
            t = 2.0 * abs(bm.calc_volume()) / area if area > 0 else 0.0
    finally:
        bm.free()
    if len(_THICK) > 5000:
        _THICK.clear()
    _THICK[key] = t
    return t


def caustic_materials():
    """Materials of the pieces that draw caustics now (glass.ensure turns their shadow shortcut off)."""
    if not STATE.caustics:
        return set()
    out = set()
    for ob in bpy.context.scene.objects:
        if ob.type == "MESH" and not twins.is_twin(ob) and not ob.get("simpler_water_body") and is_caustic_caster(ob):
            out.update(s.material for s in ob.material_slots if s.material is not None)
    return out


def _emissive(mat):
    if mat is None or not mat.use_nodes or mat.node_tree is None:
        return False
    for n in mat.node_tree.nodes:
        if n.type == "EMISSION":
            return True
        if n.type == "BSDF_PRINCIPLED":
            s = n.inputs.get("Emission Strength")
            c = n.inputs.get("Emission Color")
            if s is not None and (s.is_linked or s.default_value > 0) and c is not None \
                    and (c.is_linked or max(c.default_value[:3]) > 0):
                return True
    return False


def _glowing_points():
    """Centres of the glowing pieces (a bulb, a filament: meshes with an emissive material)."""
    out = []
    for ob in bpy.context.scene.objects:
        if ob.type == "MESH" and not twins.is_twin(ob) and not ob.hide_render \
                and any(_emissive(s.material) for s in ob.material_slots):
            bb = [ob.matrix_world @ Vector(c) for c in ob.bound_box]
            out.append(sum(bb, Vector()) / 8.0)
    return out


def _encloses(ob, points):
    """A glass around a glowing piece (the shade of a lamp, a bulb): no MNEE caustics for it. MNEE only works with
    lamps: the light of a glowing mesh inside would cross the glass only by chance - the shades sparkled with grain
    that came and went - while with the glass shortcut it simply shines through (glass.py)."""
    if not points:
        return False
    bb = [ob.matrix_world @ Vector(c) for c in ob.bound_box]
    lo = Vector(map(min, *bb)); hi = Vector(map(max, *bb))
    return any(lo.x <= p.x <= hi.x and lo.y <= p.y <= hi.y and lo.z <= p.z <= hi.z for p in points)


def refresh_caustics(force=False):
    """Caustics flags of every object and light, before each path-traced image: pieces and lights added after the
    switch (an imported glass, the sun of the Ambiente, a water surface) take part too. Only real changes are tagged:
    with persistent data a tag makes Cycles sync that object again."""
    enabled = STATE.caustics
    if not enabled and not force and not STATE.__dict__.get("caustics_flagged"):
        return
    glows = _glowing_points() if enabled else []
    for ob in bpy.context.scene.objects:
        changed = False
        if ob.type == "MESH":
            if twins.is_twin(ob) or ob.get("simpler_water_body") or ob.get("simpler_fog_domain") or ob.get("simpler_clouds") or ob.get("simpler_ocean"):
                continue                  # (the body of the water stays out of MNEE, see water.py)
            caster = enabled and is_caustic_caster(ob) and not _encloses(ob, glows)
            receiver = enabled and not caster
            if ob.cycles.is_caustics_caster != caster or ob.cycles.is_caustics_receiver != receiver:
                ob.cycles.is_caustics_caster = caster
                ob.cycles.is_caustics_receiver = receiver
                changed = True
            if float(ob.get("simpler_caster", 0.0)) != (1.0 if caster else 0.0):
                ob["simpler_caster"] = 1.0 if caster else 0.0      # (its glass shadow shortcut off: glass.py)
                changed = True
        elif ob.type == "LIGHT":
            from . import refcaustics
            want = enabled and not refcaustics.lamp_under_water(ob) and not ob.get("simpler_cloud_sun") \
                and not ob.get(FILL_KEY)
            if ob.data.cycles.is_caustics_light != want:
                ob.data.cycles.is_caustics_light = want
                ob.data.update_tag()
                changed = True
        # Cycles add-on properties do not notify the depsgraph by themselves: with persistent data the
        # renderer would keep the old flags and MNEE would never switch on or off.
        if changed:
            ob.update_tag(refresh={"OBJECT", "DATA"})
    STATE.caustics_flagged = enabled


def set_settings(data):
    if "lang" in data:
        from . import i18n
        i18n.set_lang(data["lang"])
    if "quality" in data:
        if data["quality"] not in PRESETS:
            raise ApiError(tr("Qualità non valida (bozza, alta, finale)"))
        STATE.quality = data["quality"]
        STATE.config.update(PRESETS[STATE.quality])
        invalidate()
    if isinstance(data.get("config"), dict):
        changed = False
        render_changed = False
        for k, v in data["config"].items():
            if k not in CONFIG_KEYS:
                continue
            typ, lo, hi = CONFIG_KEYS[k]
            if typ is bool:
                v = bool(v)
            elif typ is str:
                if k == "look" and v not in LOOKS:
                    continue
                if k == "colorRender" and v not in ("natural", "vivid"):
                    continue
            elif k == "realtimeTextures":
                v = min(REALTIME_TEXTURES, key=lambda t: abs(t - float(v)))
            elif k == "textureLimit":
                v = min(TEXTURE_LIMITS, key=lambda t: abs(t - float(v)))
            else:
                v = typ(max(lo, min(hi, float(v))))
            if STATE.config.get(k) != v:
                STATE.config[k] = v
                changed = True
                render_changed = render_changed or k not in TONE_KEYS
        base = PRESETS.get(STATE.quality)
        if changed and base and any(STATE.config[k] != base[k] for k in base):
            STATE.quality = "personalizzata"
        if render_changed or not changed:
            invalidate()
        else:
            retone()
    if "caustics" in data:
        apply_caustics(bool(data["caustics"]))
    if "viewport" in data:
        w, h = int(data["viewport"][0]), int(data["viewport"][1])
        STATE.vp_size = (max(64, min(w, 7680)), max(64, min(h, 4320)))
    if "live" in data:
        was = STATE.live
        STATE.live = bool(data["live"])
        if STATE.live:
            if not was:
                STATE.changed_at = time.time()     # timing of the first image from the moment it was asked for
                STATE.waited_textures = 0.0
            invalidate()
    if "exposure" in data:
        bpy.context.scene.view_settings.exposure = float(data["exposure"])
    return settings_json()


def camera_view():
    """Camera as position/target/vertical fov (cm, degrees) for the real-time viewport."""
    c = STATE.camera
    yaw, pitch = math.radians(c["yaw"]), math.radians(c["pitch"])
    t = Vector(c["target"])
    pos = t + Vector((math.cos(pitch) * math.cos(yaw), math.cos(pitch) * math.sin(yaw), math.sin(pitch))) * c["distance"]
    w, h = STATE.vp_size
    aspect = w / h
    half = math.atan(18.0 / c["lens"])
    vfov = 2 * math.atan(math.tan(half) / aspect) if aspect >= 1 else 2 * half
    out = {"position": list(pos), "target": list(t), "vfov": math.degrees(vfov), "lens": c["lens"]}
    for key in CAMERA_DEFAULTS:
        out[key] = cam_get(key)
    return out


def _base_preset():
    """The quality preset the current settings come from (for "personalizzata": the one closest to them)."""
    if STATE.quality in PRESETS:
        return STATE.quality
    return max(PRESETS, key=lambda q: sum(1 for k, v in PRESETS[q].items() if STATE.config.get(k) == v))


def settings_json():
    from . import refcaustics
    return {
        "defaults": default_config(_base_preset()),        # the "Avanzate" boxes show a dot when a value differs
        "view": camera_view(),
        "device": STATE.device,
        "quality": STATE.quality,
        "config": STATE.config,
        "looks": LOOKS,
        "caustics": STATE.caustics,
        "live": STATE.live,
        "viewport": list(STATE.vp_size),
        "exposure": bpy.context.scene.view_settings.exposure,
        "camera": STATE.camera,
        "refCaustics": refcaustics.info(),
    }


# ---------------------------------------------------------------- camera

def camera_object():
    cam = bpy.data.objects.get(CAMERA_NAME)
    if cam is None or cam.type != "CAMERA":
        data = bpy.data.cameras.new(CAMERA_NAME)
        cam = bpy.data.objects.new(CAMERA_NAME, data)
        bpy.context.scene.collection.objects.link(cam)
        cam[INTERNAL_KEY] = True
    if bpy.context.scene.camera != cam:
        # assigning scene.camera (even the same one) rebuilds the dependency graph: with persistent data
        # Cycles would then re-read every object and rebuild the BVH at every viewport pass
        bpy.context.scene.camera = cam
    return cam


CAMERA_DEFAULTS = {"dof": False, "fstop": 2.8, "focus": 100.0, "blades": 0, "bladeRotation": 0.0,
                   "shiftX": 0.0, "shiftY": 0.0, "format": ""}
FORMATS = {"": None, "16:9": 16 / 9, "3:2": 3 / 2, "4:3": 4 / 3, "1:1": 1.0, "4:5": 4 / 5, "2:3": 2 / 3, "9:16": 9 / 16,
           "A4": 297 / 210, "A4v": 210 / 297}


def cam_get(key):
    return STATE.camera.get(key, CAMERA_DEFAULTS.get(key))


FILL_KEY = "simpler_fill"


def fill_energy(fraction, ev):
    """Strength of the fill light: at 100% a 50% grey surface facing the camera gets a mid grey (18%) at the
    exposure of the picture (ev, the total in stops) - the same in every scene, bright noon or dark interior."""
    return max(0.0, float(fraction)) * 0.18 * math.pi / (0.5 * 2.0 ** float(ev))


def fill_light(scene):
    """Luce di riempimento: the photographer's reflector. A soft Sun light from the camera, a little above it, that
    lights what the camera sees: invisible, no highlights on glossy surfaces (diffuse only), soft shadows that fall
    behind the objects. It follows the camera; strength in fill_energy. Off: removed."""
    frac = float(STATE.config.get("fill", 0.0))
    ob = next((o for o in bpy.data.objects if o.get(FILL_KEY)), None)
    if frac <= 0.0005:
        if ob is not None:
            data = ob.data
            bpy.data.objects.remove(ob, do_unlink=True)
            if data is not None and data.users == 0:
                bpy.data.lights.remove(data)
        return
    if ob is None:
        data = bpy.data.lights.new("Simpler Riempimento", "SUN")
        ob = bpy.data.objects.new("Simpler Riempimento", data)
        ob[FILL_KEY] = True
        ob[INTERNAL_KEY] = 1
        ob.hide_select = True
        scene.collection.objects.link(ob)
    ob.hide_viewport = True
    for attr, val in (("visible_glossy", False), ("visible_transmission", True), ("visible_diffuse", True),
                      ("visible_volume_scatter", False)):
        try:
            if getattr(ob, attr) != val:
                setattr(ob, attr, val)
        except AttributeError:
            pass
    d = ob.data
    if hasattr(d.cycles, "is_caustics_light") and d.cycles.is_caustics_light:
        d.cycles.is_caustics_light = False
    d.color = (1.0, 1.0, 1.0)
    d.angle = math.radians(25.0)
    # (relative to the automatic exposure only: the Esposizione slider still brightens or darkens the fill too)
    e = fill_energy(frac, scene.view_settings.exposure - float(STATE.config.get("exposure", 0.0)))
    if abs(d.energy - e) > 1e-6 * max(1.0, e):
        d.energy = e
    cam = scene.camera
    if cam is not None:
        q = cam.matrix_basis.to_quaternion()      # (matrix_world is not updated yet right after apply_camera)
        fwd = (q @ Vector((0.0, 0.0, -1.0))).normalized()
        right = (q @ Vector((1.0, 0.0, 0.0))).normalized()
        from mathutils import Matrix
        down = (Matrix.Rotation(math.radians(-20.0), 3, right) @ fwd).normalized()   # from a little above the camera
        rot = down.to_track_quat("-Z", "Y").to_euler("XYZ")
        if any(abs(a - b) > 1e-5 for a, b in zip(ob.rotation_euler, rot)):
            ob.rotation_euler = rot


CLIP_FAR = 300000.0          # metres: past the edge of the sea (ocean.EDGE_FAR 200 km)


def far_clip():
    """The camera of a project saved before 1.76.20 sees the whole world too (its far clip was 100 x the orbit
    distance, at least 1 km)."""
    cam = bpy.context.scene.camera
    if cam is not None and cam.type == "CAMERA" and cam.data.clip_end < CLIP_FAR:
        cam.data.clip_end = CLIP_FAR


def apply_camera():
    c = STATE.camera
    cam = camera_object()
    target = Vector(c["target"]) * CM
    yaw, pitch = math.radians(c["yaw"]), math.radians(c["pitch"])
    d = c["distance"] * CM
    offset = Vector((math.cos(pitch) * math.cos(yaw), math.cos(pitch) * math.sin(yaw), math.sin(pitch))) * d
    cam.location = target + offset
    cam.rotation_mode = "XYZ"
    cam.rotation_euler = (target - cam.location).to_track_quat("-Z", "Y").to_euler("XYZ")
    cam.data.lens = c["lens"]
    cam.data.sensor_fit = "AUTO"
    cam.data.sensor_width = 36.0
    cam.data.clip_start = max(0.001, d * 0.001)
    # (1.76.20) far enough for the whole world: a terrain of kilometres, the sea to the horizon (ocean.EDGE_FAR). With
    # 100 x the orbit distance (min 1 km) a camera close to its target cut everything past 1 km - Luca's path tracing
    # of a 3 km terrain: no mountain, the sea ending in the grey of the sky below the horizon. In Cycles the far clip
    # only ends the camera rays: no cost, no loss of precision.
    cam.data.clip_end = max(CLIP_FAR, d * 100)
    dof = cam.data.dof
    dof.use_dof = bool(cam_get("dof"))
    dof.aperture_fstop = max(0.5, float(cam_get("fstop")))
    dof.focus_distance = max(0.001, float(cam_get("focus")) * CM)
    dof.aperture_blades = int(cam_get("blades"))
    dof.aperture_rotation = math.radians(float(cam_get("bladeRotation")))
    cam.data.shift_x = float(cam_get("shiftX"))
    cam.data.shift_y = float(cam_get("shiftY"))


def fit_camera_to_render(width, height):
    """WYSIWYG final render: the image shows exactly the frame guide drawn in the view (the largest rectangle
    with the render's proportions inside the viewport), whatever the render size."""
    c = STATE.camera
    cam = camera_object()
    vw, vh = STATE.vp_size
    av, ar = vw / vh, width / height
    lens = c["lens"]
    if av >= 1:
        hfov = 2 * math.atan(18.0 / lens)
        vfov = 2 * math.atan(math.tan(hfov / 2) / av)
    else:
        vfov = 2 * math.atan(18.0 / lens)
        hfov = 2 * math.atan(math.tan(vfov / 2) * av)
    rect_h = hfov if ar >= av else 2 * math.atan(math.tan(vfov / 2) * ar)
    cam.data.sensor_fit = "HORIZONTAL"
    cam.data.sensor_width = 36.0
    cam.data.lens = 18.0 / math.tan(rect_h / 2)


def camera_command(data):
    c = STATE.camera
    action = data.get("action", "set")
    if action == "orbit":
        c["yaw"] -= float(data.get("dx", 0))
        c["pitch"] = max(-89.0, min(89.0, c["pitch"] + float(data.get("dy", 0))))
    elif action == "zoom":
        c["distance"] = max(1.0, c["distance"] * float(data.get("factor", 1.0)))
    elif action == "pan":
        cam = camera_object()
        right = cam.matrix_world.to_3x3() @ Vector((1, 0, 0))
        up = cam.matrix_world.to_3x3() @ Vector((0, 1, 0))
        k = c["distance"]  # dx/dy are fractions of the view
        t = Vector(c["target"]) - right * float(data.get("dx", 0)) * k - up * float(data.get("dy", 0)) * k
        c["target"] = list(t)
    elif action == "frame":
        _frame_objects([find(i) for i in data.get("ids", [])] or managed_objects())
    elif action == "lookat":
        # Camera owned by the real-time viewport: position/target in cm, vertical fov in degrees.
        pos = Vector(data["position"])
        tgt = Vector(data["target"])
        off = pos - tgt
        dist = max(off.length, 0.1)
        c["target"] = list(tgt)
        c["distance"] = dist
        c["pitch"] = math.degrees(math.asin(max(-1.0, min(1.0, off.z / dist))))
        c["yaw"] = math.degrees(math.atan2(off.y, off.x))
        vfov = math.radians(float(data.get("vfov", 40)))
        aspect = float(data.get("aspect", STATE.vp_size[0] / STATE.vp_size[1]))
        # Blender sensor fit AUTO: the 36 mm sensor spans the larger image side.
        half = math.atan(math.tan(vfov / 2) * aspect) if aspect >= 1 else vfov / 2
        c["lens"] = 18.0 / math.tan(half)
    elif action == "twoPoint":
        # level the camera (vertical lines stay vertical) and keep the framing with a vertical lens shift
        yaw, pitch = math.radians(c["yaw"]), math.radians(c["pitch"])
        t = Vector(c["target"])
        pos = t + Vector((math.cos(pitch) * math.cos(yaw), math.cos(pitch) * math.sin(yaw), math.sin(pitch))) * c["distance"]
        dh = max(1.0, c["distance"] * math.cos(pitch))
        new_t = pos - Vector((math.cos(yaw), math.sin(yaw), 0.0)) * dh
        new_t.z = pos.z
        c["target"] = list(new_t)
        c["pitch"] = 0.0
        c["distance"] = dh
        c["shiftY"] = max(-2.0, min(2.0, -math.tan(pitch) * c["lens"] / 36.0))
    elif action == "settings":
        # photographic options: depth of field, lens shift, frame format
        for key, default in CAMERA_DEFAULTS.items():
            if key in data:
                v = data[key]
                if key == "format":
                    if v not in FORMATS:
                        raise ApiError(tr("Formato non valido"))
                    c[key] = v
                elif isinstance(default, bool):
                    c[key] = bool(v)
                elif isinstance(default, int):
                    c[key] = int(v)
                else:
                    c[key] = float(v)
        if "lens" in data:
            c["lens"] = max(4.0, min(1200.0, float(data["lens"])))
    elif action == "set":
        for key in ("target", "distance", "yaw", "pitch", "lens"):
            if key in data:
                c[key] = data[key]
    else:
        raise ApiError(tr("Comando camera non valido"))
    apply_camera()
    return {"camera": c}


def _frame_objects(objs):
    pts = []
    for ob in objs:
        if ob.type == "MESH" and not ob.get("simpler_ground") and not ob.name.lower().startswith(("pavimento", "floor", "suolo", "ground")):
            pts.extend(ob.matrix_world @ Vector(v) for v in ob.bound_box)
        for child in ob.children_recursive:
            if child.type == "MESH":
                pts.extend(child.matrix_world @ Vector(v) for v in child.bound_box)
    if not pts:
        return
    lo = Vector((min(p.x for p in pts), min(p.y for p in pts), min(p.z for p in pts)))
    hi = Vector((max(p.x for p in pts), max(p.y for p in pts), max(p.z for p in pts)))
    center = (lo + hi) / 2
    radius = max((hi - lo).length / 2, 0.01)
    fov = 2 * math.atan(18.0 / STATE.camera["lens"])  # 36 mm sensor
    STATE.camera["target"] = list(center / CM)
    STATE.camera["distance"] = radius / math.sin(fov / 2) * 1.1 / CM


# ---------------------------------------------------------------- picking

def pick(u, v):
    """u, v in 0..1 from the top-left of the viewport image -> object id."""
    scene = bpy.context.scene
    cam = camera_object()
    scene.render.resolution_x, scene.render.resolution_y = STATE.vp_size
    frame = cam.data.view_frame(scene=scene)
    xs = [p.x for p in frame]
    ys = [p.y for p in frame]
    z = frame[0].z
    local = Vector((min(xs) + u * (max(xs) - min(xs)), max(ys) - v * (max(ys) - min(ys)), z))
    origin = cam.matrix_world.translation
    direction = (cam.matrix_world.to_3x3() @ local).normalized()
    depsgraph = bpy.context.evaluated_depsgraph_get()
    hit, location, _normal, _index, obj, _matrix = scene.ray_cast(depsgraph, origin, direction)
    if not hit or obj is None:
        return {"id": "", "path": []}
    obj = twins.original_of(obj.original)
    slot = -1
    if obj.type == "MESH" and obj.data is not None and 0 <= _index < len(obj.data.polygons):
        slot = obj.data.polygons[_index].material_index
    material = obj.material_slots[slot].material.name if 0 <= slot < len(obj.material_slots) and obj.material_slots[slot].material else ""
    path = []
    o = obj
    while o is not None and not o.get(INTERNAL_KEY):
        path.append(o.get(ID_KEY, ""))
        o = o.parent
    return {"id": obj.get(ID_KEY, ""), "path": path, "point": list(location / CM), "slot": slot, "material": material}


# ---------------------------------------------------------------- viewport

def invalidate():
    STATE.vp_error = ""
    if not STATE.dirty or STATE.pass_index > 0:
        STATE.changed_at = time.time()
        STATE.waited_textures = 0.0
    STATE.epoch += 1
    STATE.dirty = True
    STATE.pass_index = 0
    STATE.pass_interrupts = 0


def apply_texture_limit(scene, limit):
    """Path-tracing view only: smaller textures on the GPU for huge scenes (the final render always uses them full)."""
    limit = int(limit or 0)
    want = "OFF" if limit <= 0 else str(limit)
    if scene.render.use_simplify != (limit > 0):
        scene.render.use_simplify = limit > 0
    if scene.cycles.texture_limit_render != want:
        scene.cycles.texture_limit_render = want


INTERRUPTS_PER_PASS = 3     # then the pass is let finish: commands coming every second or two (a status read by
                            # the app) restarted the same pass for ever («pass 2/5» that never went on)


def interrupt_pass(route=""):
    """From the HTTP thread: a command arrived (or the real-time view was chosen) while a path tracing pass runs."""
    from . import breaker
    if STATE.rendering and breaker.available():
        n = getattr(STATE, "pass_interrupts", 0)
        if n >= INTERRUPTS_PER_PASS and route != "live/off" and STATE.pass_index > 0:
            if n == INTERRUPTS_PER_PASS:
                log("SIMPLER_PASS", f"pass {STATE.pass_index + 1} interrupted {n} times: this time it finishes ({route})")
                STATE.pass_interrupts = n + 1
            return False
        STATE.pass_interrupts = n + 1
        STATE.interrupted = True
        breaker.interrupt()
        log("SIMPLER_PASS", f"pass {STATE.pass_index + 1} interrupted by {route or '?'}")
        return True
    return False


def viewport_needs_pass():
    from . import rain
    if rain.SMART["on"]:
        return False            # (1.75.9) SmartView: no path tracing pass (the app keeps the real-time view)
    return STATE.live and STATE.dirty and STATE.pass_index < len(VIEWPORT_PASSES)


def preview_proxy_px():
    """Texture size of the path tracing view: 0 = original size. Automatic: 2048, or 1024 when the 2048 versions
    would still need more than about 4 GB of GPU memory (hundreds of big textures)."""
    lim = int(STATE.config.get("textureLimit", -1))
    if lim == 0 or lim > proxies.PROXY_PX:
        return 0
    if lim > 0:
        return lim
    return 1024 if proxies.texture_bytes(2048) > 4e9 else 2048


def preview_textures_ready():
    """Path tracing view with reduced textures (2K/1K): use the proxies, and wait for them while they are being
    made (minutes saved on big models). False = not ready yet: try again in a moment, the engine stays free."""
    px = preview_proxy_px()
    if px == 0:
        # original size; exact local copies of the textures on network drives still help (not waited for)
        proxies.ensure_async(sizes=(1 << 30,))
    elif proxies.ensure_async(sizes=(px,)):
        return False
    if proxies.use(px):
        invalidate()
    return True


def _scene_texture_names(scene):
    """File names of the image textures Cycles will load for this scene (what it reports as "Loading <name>")."""
    names, seen_trees = set(), set()

    def walk(tree):
        if tree is None or tree.as_pointer() in seen_trees:
            return
        seen_trees.add(tree.as_pointer())
        for n in tree.nodes:
            if n.type in ("TEX_IMAGE", "TEX_ENVIRONMENT") and getattr(n, "image", None) is not None:
                im = n.image
                if im.source in ("FILE", "TILED"):
                    names.add(im.name if im.packed_file is not None else os.path.basename(bpy.path.abspath(im.filepath)))
            elif n.type == "GROUP":
                walk(n.node_tree)

    mats = set()
    for ob in scene.objects:
        if ob.hide_render or ob.type not in ("MESH", "CURVE", "SURFACE", "META", "FONT"):
            continue
        for sl in ob.material_slots:
            if sl.material is not None and sl.material.use_nodes:
                mats.add(sl.material)
    for m in mats:
        walk(m.node_tree)
    if scene.world is not None and scene.world.use_nodes:
        walk(scene.world.node_tree)
    return names


def preview_texture_limit():
    """Extra reduction made by Cycles on top of the proxies. Automatic: 2K (the proxies), 1K when even the 2K
    textures would fill too much of the GPU memory (about 16 MB each)."""
    lim = int(STATE.config.get("textureLimit", -1))
    return lim if lim > proxies.PROXY_PX else 0      # 4K: originals reduced by Cycles; smaller: the proxies


def render_viewport_pass():
    if not preview_textures_ready():
        time.sleep(0.1)
        STATE.waited_textures += 0.1
        return
    twins.ensure()               # a change to the scene must not make Cycles rebuild all the geometry (see twins.py)
    apply_camera()               # (1.75.3) first: the water's grid and the sea's caustics are made for this view
    from . import matedit
    matedit.flush_pending()      # (1.76.56) the material trees left for later: made now, Cycles draws them
    matedit.interior_pass()      # (1.79.0) the rooms of «Interni» from the corner of each object
    matedit.displacement_pass(False)   # "only in the final render" displacements: only their bump here
    from . import glass
    glass.ensure()  # the light of lamps and sun through glass and water (see glass.py)
    from . import water
    water.ensure()                # the body of the water (volume) in its materials (see water.py)
    from . import volumetric
    volumetric.ensure()           # fog, smoke, clouds, fire in models (see volumetric.py)
    refresh_caustics()
    from . import refcaustics
    refcaustics.safe_ensure(False)   # light reflected by the waves onto walls (see refcaustics.py)
    from . import rain
    rain.ensure()                 # wet surfaces and puddles (after the others: it copies what they put in the materials)
    epoch0 = STATE.epoch
    if STATE.pass_index == 0:
        _diag_line()
    scale, samples, denoise, time_limit = VIEWPORT_PASSES[STATE.pass_index]
    from . import breaker
    if time_limit == 0 and STATE.pass_index > 0 and not breaker.available():
        time_limit = 10.0             # (no way to interrupt a pass here: commands must not wait for minutes)
    scene = bpy.context.scene
    apply_camera()
    from . import ambience
    ambience.fog_follow_camera(Vector(camera_view()["position"]) * CM)   # (from the settings: the object may not be updated yet)
    _apply_common(scene)
    fill_light(scene)
    from . import clouds
    clouds.render_settings(scene, final=False)
    w, h = STATE.vp_size
    scene.render.resolution_x, scene.render.resolution_y = w, h
    scene.render.resolution_percentage = max(1, int(scale * 100))
    ambience.fog_camera(scene)       # (1.75.49) the height fog needs the frame of this image
    c = STATE.config
    last = STATE.pass_index == len(VIEWPORT_PASSES) - 1
    scene.cycles.samples = max(1, c["viewportSamples"] if last else min(samples, c["viewportSamples"]))
    adaptive_sampling(scene, max(c["noiseThreshold"], 0.01), scene.cycles.samples, 2)
    scene.cycles.use_denoising = denoise and bool(c["denoise"])
    scene.cycles.time_limit = time_limit
    _image_format_back(scene)
    scene.render.image_settings.file_format = "JPEG"
    scene.render.image_settings.quality = 100       # (Luca, 18/11: «il 100 jpg mettilo ovunque»; «Salva immagine» saves this file)
    apply_texture_limit(scene, preview_texture_limit())
    path = os.path.join(STATE.tmp, "viewport.jpg")
    scene.render.filepath = path
    try:
        os.remove(path)
    except OSError:
        pass
    from . import progress
    progress.viewport_begin(sum(1 for o in scene.objects if o.type in ("MESH", "CURVE", "LIGHT") and not twins.is_twin(o)),
                            len(_scene_texture_names(scene)), proxies.texture_bytes(preview_proxy_px()))
    t0 = time.time()
    error = ""
    STATE.interrupted = False
    STATE.rendering = True
    # (17/11, Luca: «modificare lo slider Ghiaccio ha impiegato 40 secondi») a command that arrived while this pass was being
    # prepared (above: volumes, rain, materials - seconds in a big scene) found no pass running to interrupt and waited for
    # the whole pass: the slider let go at 15:17:30.73, the last pass (256 samples) began right after and ran 40 s before
    # the command. Now a command already waiting means no pass: it runs first, the pass starts again after it - counted
    # as an interruption of this pass (INTERRUPTS_PER_PASS: the status reads of the app must not hold a pass back for ever).
    from . import server as _srv
    n_int = getattr(STATE, "pass_interrupts", 0)
    if not _srv.JOBS.empty() and (n_int < INTERRUPTS_PER_PASS or STATE.pass_index == 0):
        STATE.pass_interrupts = n_int + 1
        STATE.rendering = False
        progress.viewport_end()
        log("SIMPLER_PASS", f"pass {STATE.pass_index + 1} not started: a command is waiting")
        return
    diag = _diag_file() if last else None
    if diag:
        _diag_passes(scene, True)
    try:
        bpy.ops.render.render(write_still=True)
        if diag:
            _diag_save(scene, diag)
    except Exception as ex:      # e.g. out of GPU memory
        error = str(ex).strip() or ex.__class__.__name__
    finally:
        if diag:
            _diag_passes(scene, False)
        STATE.rendering = False
        snap = progress.viewport_snapshot()
        progress.viewport_end()
    ms = int((time.time() - t0) * 1000)
    if STATE.interrupted:
        # stopped to run a command at once: the same pass starts again afterwards (scene data stay on the GPU)
        STATE.interrupted = False
        return
    error = error or snap.get("error", "")
    if not error and not os.path.isfile(path):
        error = tr("Cycles non ha prodotto l'immagine")
    if error:
        STATE.vp_error = error
        STATE.dirty = False      # don't retry in a loop: the next change of the scene tries again
        print(f"SIMPLER_VIEWPORT_ERROR {error}", flush=True)
        return
    if STATE.epoch == epoch0 and STATE.meter_epoch != epoch0 and c.get("meterExposure"):
        try:
            before = scene.view_settings.exposure
            from . import meter
            _meter_store(meter.measure(scene, STATE.tmp), epoch0)
            scene.view_settings.exposure = c["exposure"] + exposure_auto()
            if abs(scene.view_settings.exposure - before) > 1e-4:
                scene.render.image_settings.file_format = "JPEG"
                bpy.data.images["Render Result"].save_render(path, scene=scene)   # (this frame at once, not one pass later)
                log("SIMPLER_METER", f"ev={STATE.meter_ev:.2f} exposure {before:.2f} -> {scene.view_settings.exposure:.2f}")
        except Exception as ex:  # noqa: BLE001
            log("SIMPLER_METER", f"view: {ex}")
    data = _toned_frame(path)
    if STATE.epoch != epoch0:
        return                   # the scene or the view changed meanwhile: this frame is already old
    with STATE.lock:
        STATE.frame = data
        STATE.frame_info = {
            "version": STATE.frame_info["version"] + 1,
            "pass": STATE.pass_index,
            "passes": len(VIEWPORT_PASSES),
            "samples": scene.cycles.samples,
            "width": int(w * scale), "height": int(h * scale),
            "ms": ms,
            "epoch": STATE.epoch,
        }
    log("SIMPLER_PASS", f"pass={STATE.pass_index + 1}/{len(VIEWPORT_PASSES)}", f"samples={scene.cycles.samples}",
        f"size={int(w * scale)}x{int(h * scale)}", f"pass_ms={ms}",
        f"since_change_ms={int((time.time() - STATE.changed_at) * 1000)}",
        f"waited_textures_s={STATE.waited_textures:.1f}")
    STATE.pass_index += 1
    STATE.pass_interrupts = 0
    # (1.76.50, logs of Luca: every pass of a big scene spent 3-5 s preparing it before the first sample - five passes,
    # 15-25 s of preparing for one picture) when preparing is the slow part, the in-between previews are left out:
    # the quick first look, the half-quality one and the final
    try:
        from . import progress as _pg
        sa, st = _pg._vp.get("sampleAt") or 0.0, _pg._vp.get("started") or 0.0
        if sa and st:
            STATE.last_prep = max(0.0, sa - st)
    except Exception:  # noqa: BLE001
        pass
    if STATE.last_prep >= PREP_SLOW:
        while STATE.pass_index in PASSES_SKIPPABLE:
            STATE.pass_index += 1
    if STATE.pass_index >= len(VIEWPORT_PASSES):
        STATE.dirty = False


def get_frame():
    with STATE.lock:
        info = dict(STATE.frame_info)
        info["current"] = STATE.epoch
        info["live"] = STATE.live
        frame = STATE.frame
    from . import progress
    prep = progress.viewport_snapshot()
    if prep["active"]:
        info["prep"] = {k: prep[k] for k in ("phase", "detail", "memory", "elapsed", "fraction", "eta")}
    ps = proxies.status()
    if ps["running"] and STATE.live and "prep" not in info:
        done, total, spent = ps["done"], max(1, ps["total"]), ps.get("elapsed", 1)
        info["prep"] = {"phase": tr("Ottimizzazione delle texture per l'anteprima"), "detail": f"{done}/{ps['total']}",
                        "memory": "", "elapsed": spent, "fraction": done / total,
                        "eta": round(spent / done * (total - done)) if done >= 2 and spent > 2 else None}
    if STATE.vp_error:
        info["error"] = STATE.vp_error
    return frame, info


# ---------------------------------------------------------------- final render

RENDER_JOB = {"proc": None, "cancel": False, "vram0": None, "cyclesMem": None}


def render_hardware():
    """For the screen of the final render (GET progress): the graphics card (memory used, load, temperature), the
    memory Cycles says it uses, the computer's memory of the render and the whole computer - and how much of the
    render did not fit on the card (then it runs from the computer's memory, much slower). None when no render."""
    from . import gpu
    proc = RENDER_JOB.get("proc")
    if proc is None:
        return None
    g = gpu.info() or {}
    out = {"gpu": g.get("name"), "vramUsed": g.get("used"), "vramTotal": g.get("total"), "load": g.get("load"),
           "temperature": g.get("temperature"), "cyclesMem": RENDER_JOB.get("cyclesMem"), "procRam": gpu.process_ram(proc)}
    out["ramUsed"], out["ramTotal"] = gpu.system_ram()
    # what the render holds on the card = card now - card before it started; Cycles' own figure beyond that is in
    # the computer's memory (an estimate: Windows and other programs also move the card's figure a little)
    base, cm, used = RENDER_JOB.get("vram0"), out["cyclesMem"], out["vramUsed"]
    if base is not None and cm and used is not None:
        spill = cm - max(0, used - base)
        out["spill"] = spill if spill > 0.5e9 else 0
    return out


def cancel_render():
    """Called from the HTTP thread: stops the final render running in its own process."""
    RENDER_JOB["cancel"] = True
    proc = RENDER_JOB["proc"]
    if proc is not None and proc.poll() is None:
        try:
            proc.kill()
        except OSError:
            pass
    return {"cancelled": True}


def final_render(data):
    path = data.get("path")
    if not path:
        raise ApiError(tr("Percorso del file mancante"))
    width = int(data.get("width", 3840))
    height = int(data.get("height", 2160))
    quality = data.get("quality", "attuale")
    saved = dict(STATE.config)
    if quality in PRESETS:
        STATE.config.update(PRESETS[quality])      # only for this render
    from . import camview, ocean
    try:
        ocean.idle_follow(now=True)       # (1.76.39: the sea where this image looks, if the camera has just moved)
    except Exception as exc:  # noqa: BLE001
        print("SIMPLER_OCEAN follow before render", exc, flush=True)
    camview.FRAME["aspect"] = width / max(1, height)      # (what follows the camera: for the frame of this image)
    try:
        return _final_render(path, width, height, data)
    finally:
        camview.FRAME["aspect"] = None
        STATE.config.clear()
        STATE.config.update(saved)


def final_texture_px(choice, width=1920, height=1080):
    """Texture size for the final render. -1 = automatic: the largest that fits in about 60% of the video
    memory (geometry and the image need the rest) - and in what is free on the card now (other programs, the 3D
    view, Windows); if the originals do not fit, Cycles has to work in the computer's memory and the render
    becomes many times slower."""
    choice = int(choice if choice is not None else -1)
    if choice >= 0:
        return choice
    from . import gpu
    total = gpu.total_bytes() or 16 * 1024 ** 3
    budget = total * 0.6
    used = gpu.used_bytes()
    if used is not None:
        # what is free, less the geometry and the image of the render (about 2 GB on a big scene, plus the film)
        budget = min(budget, total - used - 2.0e9 - width * height * FILM_BYTES_PER_PIXEL)
    for px in (0, 4096, 2048, 1024):
        if proxies.texture_bytes(px) <= budget:
            return px
    return 1024


def texture_estimate(_data=None):
    from . import gpu
    return {"full": proxies.texture_bytes(0), "px4096": proxies.texture_bytes(4096),
            "px2048": proxies.texture_bytes(2048), "px1024": proxies.texture_bytes(1024),
            "count": len(proxies.originals_in_use()), "auto": final_texture_px(-1), "gpu": gpu.info()}


def _final_textures_ready(px):
    """Reduced copies for the final render (made once, cached), waiting here with the progress shown."""
    from . import progress
    if px <= 0:
        return
    proxies.ensure_async(sizes=(px,))
    while proxies.status()["running"]:
        if RENDER_JOB["cancel"]:
            RENDER_JOB["cancel"] = False
            raise ApiError(tr("Render annullato"))
        st = proxies.status()
        progress.update(tr("Ottimizzazione delle texture"), 0.02 * st["done"] / max(1, st["total"]),
                        tr("{0} di {1}", st["done"], st["total"]))
        time.sleep(0.25)


FILM_BYTES_PER_PIXEL = 160     # Cycles image buffers with denoising passes and adaptive sampling, with margin


def set_final_tiles(scene, width, height):
    """The whole image in one go when its buffers fit comfortably in the video memory: faster than tiles and the
    remaining time shown is reliable. Tiles only for very large images or small graphics cards."""
    from . import gpu
    total = gpu.total_bytes() or 0
    need = width * height * FILM_BYTES_PER_PIXEL
    cy = scene.cycles
    if STATE.device != "CPU" and total and need <= total * 0.15:
        cy.use_auto_tile = False
        return "off"
    cy.use_auto_tile = True
    cy.tile_size = 4096 if (not total or need <= total * 0.3) else 2048
    return str(cy.tile_size)


def _final_render(path, width, height, data):
    fresh = STATE.meter_epoch == STATE.epoch     # (1.79.0) the view measured this same scene (exposure_auto)
    # (1.75.0) the camera of the image first: the water around the camera (water.py) is made for it
    apply_camera()
    fit_camera_to_render(width, height)
    from . import matedit
    matedit.flush_pending()      # (1.76.56) the material trees left for later
    matedit.interior_pass()      # (1.79.0) the rooms of «Interni» from the corner of each object
    matedit.displacement_pass(True, max(int(width), int(height)))
    from . import glass
    glass.ensure()
    from . import water
    water.ensure()
    from . import volumetric
    volumetric.ensure()
    refresh_caustics()
    from . import refcaustics
    refcaustics.safe_ensure(True)
    from . import rain
    rain.ensure()
    c = STATE.config
    scene = bpy.context.scene
    apply_camera()
    fit_camera_to_render(width, height)
    from . import ambience
    ambience.fog_follow_camera(Vector(camera_view()["position"]) * CM)   # (from the settings: the object may not be updated yet)
    _apply_common(scene, final=True)
    fill_light(scene)
    from . import clouds
    clouds.render_settings(scene, final=True)
    apply_texture_limit(scene, 0)
    scene.render.resolution_x, scene.render.resolution_y = width, height
    scene.render.resolution_percentage = 100
    ambience.fog_camera(scene)       # (1.75.49) the height fog needs the frame of this image
    scene.cycles.samples = int(data.get("samples", c["samples"]))
    adaptive_sampling(scene, c["noiseThreshold"], scene.cycles.samples, 8, 256)
    scene.cycles.use_denoising = bool(data.get("denoise", c["denoise"]))
    scene.cycles.time_limit = float(data.get("timeLimit", 0))
    ext = os.path.splitext(path)[1].lower()
    fmt = {".png": "PNG", ".jpg": "JPEG", ".jpeg": "JPEG", ".exr": "OPEN_EXR", ".tif": "TIFF", ".tiff": "TIFF"}.get(ext, "PNG")
    _image_format_back(scene)
    scene.render.image_settings.file_format = fmt
    if fmt in ("PNG", "TIFF"):
        scene.render.image_settings.color_depth = "16"
    elif fmt == "JPEG":
        scene.render.image_settings.quality = 100   # (said here: before it was whatever the view had left, 90)
    scene.render.filepath = path
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    t0 = time.time()
    from . import progress, gpu
    progress.begin("render", tr("Preparazione della scena"))
    # the path tracing view keeps its whole scene on the graphics card (persistent data: 4-5 GB on a big project)
    # while the final render, in its own process, needs the card too: together they did not fit in 16 GB and Cycles
    # went on in the computer's memory - 20 times slower (1 s per sample at 1920 x 1080, 1.71.3). The view's copy
    # is let go for the final render (the view prepares it again afterwards, once).
    exe = os.environ.get("SIMPLER_RENDER_EXE") or bpy.app.binary_path
    own_process = bool(exe and os.path.isfile(exe) and not data.get("inProcess"))
    _meter_final(scene, width, height, fresh, own_process)
    scene.view_settings.exposure = c["exposure"] + exposure_auto()
    fill_light(scene)
    persistent = scene.render.use_persistent_data
    used0 = gpu.used_bytes()
    if own_process and persistent:
        scene.render.use_persistent_data = False            # (Blender frees the view's render data at once)
    used1 = gpu.used_bytes()
    RENDER_JOB.update(vram0=used1, cyclesMem=None, stats=None)
    tex_px = final_texture_px(data.get("textures", -1), width, height)
    # tile settings are session parameters: put back afterwards, or the path tracing view would rebuild everything
    tiles_before = (scene.cycles.use_auto_tile, scene.cycles.tile_size)
    tiles = set_final_tiles(scene, width, height)
    gb = lambda b: f"{b / 1e9:.1f}" if b is not None else "?"
    print(f"SIMPLER_FINAL textures={tex_px or 'originals'} estimate={proxies.texture_bytes(tex_px) / 1e9:.1f} GB "
          f"tiles={tiles} card used {gb(used0)} -> {gb(used1)} GB of {gb(gpu.total_bytes())} (view's copy let go)", flush=True)
    try:
        RENDER_JOB["cancel"] = False
        _final_textures_ready(tex_px)
        RENDER_JOB["tex_px"] = tex_px
        if own_process:
            measure = _measure_dir()
            if measure:
                _diag_passes(scene, True)              # (samples of every pixel, in the saved copy of the scene)
                print(f"SIMPLER_MEASURE into {measure}", flush=True)
            try:
                path = _render_in_subprocess(exe, path, scene, measure)
            finally:
                if measure:
                    _diag_passes(scene, False)
        else:
            # development (bpy module): no separate process - the same writing in a folder of its own and then in place
            out_dir = tempfile.mkdtemp(prefix="simpler_out_", dir=STATE.tmp)
            out_tmp = os.path.join(out_dir, os.path.basename(path))
            scene.render.filepath = out_tmp
            try:
                with proxies.for_render(tex_px):
                    bpy.ops.render.render(write_still=True)
            finally:
                scene.render.filepath = path
            if not os.path.isfile(out_tmp):
                shutil_rm(out_dir)
                raise ApiError(tr("Il render non ha prodotto il file"))
            path = _place_render(out_tmp, out_dir, path)
    finally:
        progress.end()
        scene.pop("simpler_meter", None)
        if (scene.cycles.use_auto_tile, scene.cycles.tile_size) != tiles_before:
            scene.cycles.use_auto_tile, scene.cycles.tile_size = tiles_before
        if scene.render.use_persistent_data != persistent:
            scene.render.use_persistent_data = persistent
        fog_denoise(scene, False)          # (the view without it again)
    invalidate()
    if not os.path.isfile(path):
        raise ApiError(tr("Il render non ha prodotto il file"))
    from . import tone
    try:
        tone.finish_file(path, c)
    except Exception as ex:
        log("SIMPLER_TONE", f"failed: {ex}")
    return {"path": path, "seconds": round(time.time() - t0, 1), "width": width, "height": height, "samples": scene.cycles.samples,
            "stats": _final_stats(t0, used0, used1)}


def _final_stats(t0, used0, used1):
    """(1.75.10) What the window of the image shows: the time of each phase, the peaks of the card and of the memory."""
    from . import gpu
    st = RENDER_JOB.get("stats") or {}
    end = time.time()
    out = {"total": round(end - t0, 1), "device": STATE.device}
    if st.get("start"):
        s0, s1 = st["start"], st.get("sampling") or st.get("end") or end
        s2 = st.get("denoise") or st.get("end") or end
        out.update(prepare=round(s0 - t0, 1), load=round(s1 - s0, 1), sampling=round(max(0.0, s2 - s1), 1),
                   denoise=round(max(0.0, (st.get("end") or end) - s2), 1) if st.get("denoise") else 0.0,
                   finish=round(max(0.0, end - (st.get("end") or end)), 1))
    g = gpu.info() or {}
    out.update(gpu=g.get("name"), vramTotal=g.get("total"), vramPeak=st.get("vramPeak"), vramBefore=used0,
               vramFree=used1, cyclesPeak=st.get("cyclesPeak"), ramPeak=st.get("ramPeak"))
    out["ramTotal"] = gpu.system_ram()[1]
    return out


def _measure_dir():
    """Measurement of a final render on request: with the file test_out/misura.on in the Simpler folder, the next final
    render also writes test_out/misura/ (render_job._measure). The flag is removed: one measurement."""
    root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    flag = os.path.join(root, "test_out", "misura.on")
    if not os.path.isfile(flag):
        return ""
    try:
        os.remove(flag)
    except OSError:
        pass
    return os.path.join(root, "test_out", "misura")


def _render_in_subprocess(exe, path, scene, measure=""):
    """Render a saved copy of the scene in a second Blender: it can be cancelled (kill) and reports progress."""
    import re
    import subprocess
    from . import progress

    job_dir = tempfile.mkdtemp(prefix="simpler_render_", dir=STATE.tmp)
    blend = os.path.join(job_dir, "scene.blend")
    try:
        bpy.ops.file.make_paths_absolute()
    except RuntimeError:
        pass
    from . import trash
    try:
        from . import rain as _rain
        print("SIMPLER_FINALDIAG " + _rain.diag(), flush=True)
    except Exception as exc:
        print(f"SIMPLER_FINALDIAG failed: {exc}", flush=True)
    with trash.excluded(), proxies.for_render(RENDER_JOB.get("tex_px", 0)):   # originals (or exact copies), or reduced
        try:                        # (1.75.38) as the copy will really carry it: after the swap of the images
            from . import rain as _rain
            print("SIMPLER_FINALDIAG saved " + _rain.diag(), flush=True)
        except Exception as exc:
            print(f"SIMPLER_FINALDIAG failed: {exc}", flush=True)
        bpy.ops.wm.save_as_mainfile(filepath=blend, copy=True, compress=False, relative_remap=False, check_existing=False)
    script = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "render_job.py")
    # (1.75.23) the image is written in the job's folder and moved to its place by the engine: Blender could not
    # write it there (the file open in another program) and went on as if nothing were wrong - Simpler then showed
    # the old file with that name, 11 minutes of 4K lost (Luca: «il bagnato è scomparso»). A python error in the job
    # now ends Blender with an error code too.
    out_dir = tempfile.mkdtemp(prefix="simpler_out_", dir=STATE.tmp)
    out_tmp = os.path.join(out_dir, os.path.basename(path))
    cmd = [exe, "--factory-startup", "-t", str(cpu_threads()), "-b", blend, "--python-exit-code", "1",
           "--python", script, "--", out_tmp, STATE.device]
    if measure:
        cmd.append(measure)
    # CREATE_NO_WINDOW | BELOW_NORMAL_PRIORITY_CLASS: the final render must never make Windows unresponsive
    flags = (0x08000000 | 0x00004000) if os.name == "nt" else 0
    RENDER_JOB["cancel"] = False
    proc = fullspeed.popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, encoding="utf-8",
                            errors="replace", creationflags=flags, bufsize=1)
    RENDER_JOB["proc"] = proc
    # (1.75.10) for the window of the image: the times of the phases and the peaks of memory (Luca)
    from . import gpu
    st = RENDER_JOB["stats"] = {"start": time.time(), "sampling": None, "denoise": None, "end": None,
                                "vramPeak": None, "cyclesPeak": None, "ramPeak": None, "at": 0.0}

    def _peaks():
        now_ = time.time()
        if now_ - st["at"] < 0.5:
            return
        st["at"] = now_
        for k, v in (("vramPeak", gpu.used_bytes()), ("ramPeak", gpu.process_ram(proc)),
                     ("cyclesPeak", RENDER_JOB.get("cyclesMem"))):
            if v is not None and (st[k] is None or v > st[k]):
                st[k] = v
    from .sampleprog import SampleProgress
    sprog = SampleProgress()
    remaining = re.compile(r"Remaining:\s*([\d:.]+)")
    mem_re = re.compile(r"Mem:\s*([\d.]+)M")
    tail = []
    hist = []                 # (time, sample): the speed of the last seconds, for the time left
    try:
        n_stats = 0
        last_phase = ""
        for line in proc.stdout:
            line = line.rstrip()
            tail = (tail + [line])[-15:]
            try:
                _peaks()
            except Exception:
                pass
            if not line.startswith("SIMPLER_STATS"):
                if line.startswith(("SIMPLER_", "Error", "Warning")) or "error" in line.lower():
                    print("FINAL| " + line, flush=True)       # in engine.log, to understand slow renders
                continue
            n_stats += 1
            mm = mem_re.search(line)
            if mm:
                RENDER_JOB["cyclesMem"] = float(mm.group(1)) * 1024 * 1024     # (Cycles: «Mem: 11050M», MiB)
            phase = line.split("|")[-2].strip() if line.count("|") >= 2 else ""
            if phase != last_phase or n_stats % 200 == 0:
                last_phase = phase
                print("FINAL| " + line[:220], flush=True)
            r = remaining.search(line)
            if sprog.feed(line):
                if st["sampling"] is None:
                    st["sampling"] = time.time()
                # (with tiles the bar goes through every tile once; 1.75.23: never a tile ahead, never back)
                done, total = sprog.done, sprog.total
                frac = done / total
                # the time left: from the speed of the last 15 s, not Cycles' own figure - it counts every
                # sample at the speed of the first ones, while adaptive sampling makes the later ones much faster
                # (33 minutes announced, 3 taken); shown only after a few samples, it shrinks as the render speeds up
                now = time.time()
                # (the window keeps at least the point before it: with a sample every 20 s or more - a heavy 4K
                # image - there is still a speed to show)
                old = [x for x in hist if now - x[0] > 15.0]
                hist = old[-1:] + [x for x in hist if now - x[0] <= 15.0] + [(now, done)]
                eta = ""
                if done >= max(3, total * 0.02) and len(hist) >= 2 and hist[-1][1] > hist[0][1] and now - hist[0][0] >= 3.0:
                    rate = (hist[-1][1] - hist[0][1]) / (now - hist[0][0])
                    left = int((total - done) / max(rate, 1e-6))
                    eta = f"{left // 60}:{left % 60:02d}" if left < 3600 else f"{left // 3600}:{(left % 3600) // 60:02d}:{left % 60:02d}"
                progress.update(tr("Calcolo dell'immagine"), 0.05 + 0.9 * min(1.0, frac),
                                tr("campione {0} di {1} · al massimo {2}", done, total, eta) if eta else tr("campione {0} di {1}", done, total),
                                (done, total))
            elif "Denois" in line:
                if st["denoise"] is None:
                    st["denoise"] = time.time()
                progress.update(tr("Riduzione del rumore"), 0.97)
            elif "Loading" in line or "Updating" in line or "Synchroniz" in line:
                progress.update(tr("Caricamento di geometrie e texture"), 0.03)
        proc.wait()
        st["end"] = time.time()
    finally:
        RENDER_JOB["proc"] = None
        try:
            import shutil
            shutil.rmtree(job_dir, ignore_errors=True)
        except OSError:
            pass
    if RENDER_JOB["cancel"]:
        RENDER_JOB["cancel"] = False
        raise ApiError(tr("Render annullato"))
    if proc.returncode != 0 or not os.path.isfile(out_tmp):
        shutil_rm(out_dir)
        raise ApiError(tr("Il render si è interrotto:\n{0}", "\n".join(tail[-6:])))
    return _place_render(out_tmp, out_dir, path)


def shutil_rm(folder):
    import shutil
    shutil.rmtree(folder, ignore_errors=True)


def _place_render(src, src_dir, path):
    """The finished image to the file chosen by the user; when that file cannot be written (open in another program,
    a folder without permission) next to it with a number, so that the render is never lost. Returns where it went."""
    import shutil
    base, ext = os.path.splitext(path)
    tries = [path] + [f"{base} ({n}){ext}" for n in range(2, 10)]
    err = None
    try:
        for dst in tries:
            if dst != path and os.path.exists(dst):
                continue
            try:
                shutil.copyfile(src, dst)
                if dst != path:
                    log("SIMPLER_RENDER_SAVE", f"{path} could not be written ({err}): saved as {dst}")
                return dst
            except OSError as exc:
                err = exc
        raise ApiError(tr("Non è stato possibile salvare l'immagine in {0}: {1}", path, err))
    finally:
        shutil.rmtree(src_dir, ignore_errors=True)


# ---------------------------------------------------------------- gizmo projection

def _project(scene, cam, world_point):
    from bpy_extras.object_utils import world_to_camera_view
    co = world_to_camera_view(scene, cam, world_point)
    return [co.x, 1.0 - co.y, co.z]  # u, v from top-left; z > 0 in front of the camera


def gizmo(obj_id):
    """Screen-space handles for the selected object: origin and the tips of the
    world X/Y/Z axes, each `length` cm long (about 12% of the camera distance)."""
    scene = bpy.context.scene
    cam = camera_object()
    apply_camera()
    scene.render.resolution_x, scene.render.resolution_y = STATE.vp_size
    scene.render.resolution_percentage = 100
    ob = find(obj_id)
    origin = ob.matrix_world.translation.copy()
    length = STATE.camera["distance"] * CM * 0.12
    o = _project(scene, cam, origin)
    axes = {}
    for name, d in (("x", (1, 0, 0)), ("y", (0, 1, 0)), ("z", (0, 0, 1))):
        axes[name] = _project(scene, cam, origin + Vector(d) * length)
    return {"origin": o, "axes": axes, "length": length / CM, "visible": o[2] > 0}


# ---------------------------------------------------------------- real-time preview export

PREVIEW = {"version": 0, "path": "", "bytes": 0}
# the export running in its own Blender process (state: idle | running | done | error | cancelled)
EXPORT = {"state": "idle", "proc": None, "id": 0, "phase": "", "fraction": None, "detail": "", "started": 0.0,
          "error": "", "lock": threading.Lock()}
REALTIME_TEXTURES = [-1, 0, 1024, 2048, 4096]   # -1 = full size, 0 = automatic


def realtime_texture_px():
    """Largest texture side in the real-time view. Automatic: 2048, or 1024 when the scene has many big maps."""
    v = int(STATE.config.get("realtimeTextures", 0))
    if v < 0:
        return 0
    if v > 0:
        return v
    # sizes from the file headers: reading im.size would load every texture into memory
    return 1024 if proxies.texture_bytes(2048) > 0.8e9 else 2048


def warm_texture_cache():
    """After an import or opening a project: reduced copies for both views, in the background."""
    sizes = set()
    pt = preview_proxy_px()
    if pt > 0:
        sizes.add(pt)
    rt = realtime_texture_px()
    if rt > 0:
        sizes.add(rt)
    proxies.ensure_async(sizes=tuple(sorted(sizes)))


VIEW_CACHE_KEEP = 4               # prepared 3D views kept on disk (the most recently used)


def view_cache_dir():
    base = os.environ.get("LOCALAPPDATA") or tempfile.gettempdir()
    d = os.path.join(base, "Simpler", "viewcache")
    os.makedirs(d, exist_ok=True)
    return d


def view_fingerprint(max_px):
    """What the real-time view file depends on: objects, hierarchy, meshes, materials and textures - not the
    positions (the view receives them separately) nor the visibility. Same fingerprint = same file."""
    import hashlib
    from . import VERSION
    h = hashlib.sha1(f"{VERSION}|{max_px}".encode())

    def put(*parts):
        h.update(("|".join(str(p) for p in parts) + "\n").encode("utf-8", "replace"))

    def val(v):
        try:
            return tuple(round(float(x), 5) for x in v)
        except (TypeError, ValueError):                 # (a text socket: an attribute name, a menu)
            return round(float(v), 5) if isinstance(v, (int, float)) else str(v)

    mats = {}
    for ob in sorted(bpy.context.scene.objects, key=lambda o: o.name):
        if twins.is_twin(ob) or ob.get(INTERNAL_KEY) or ob.get("simpler_paint_model") or ob.get("simpler_paint_data"):
            continue                       # (painted pieces: drawn by the view from their model, see paint.py)
        put("ob", ob.name, ob.get(ID_KEY, ""), ob.type, ob.data.name if ob.data else "",
            ob.parent.name if ob.parent else "", [m.type for m in ob.modifiers if m.name != "Simpler Displacement"])
        if ob.type == "MESH" and ob.data is not None:
            me = ob.data
            put("me", len(me.vertices), len(me.polygons), len(me.uv_layers), me.get("simpler_georev", 0))   # (new UV...)
        if ob.type == "LIGHT":
            put("li", ob.data.type)
        for sl in ob.material_slots:
            put("sl", sl.material.name if sl.material else "")
            if sl.material is not None:
                mats[sl.material.name] = sl.material
    trees, seen = [], set()
    for name in sorted(mats):
        if mats[name].node_tree is not None:
            trees.append((name, mats[name].node_tree))
    while trees:
        name, tree = trees.pop(0)
        if tree.as_pointer() in seen:
            continue
        seen.add(tree.as_pointer())
        put("tree", name)
        for n in tree.nodes:
            im = getattr(n, "image", None)
            put("n", n.bl_idname, n.name, im.name if im else "",
                bpy.path.abspath(im.filepath) if im else "", im.packed_file.size if im and im.packed_file else "")
            for sock in n.inputs:
                if not sock.is_linked and hasattr(sock, "default_value"):
                    put("i", sock.identifier, val(sock.default_value))
            if n.type == "GROUP" and n.node_tree is not None:
                trees.append((n.node_tree.name, n.node_tree))
        for ln in tree.links:
            put("l", ln.from_node.name, ln.from_socket.identifier, ln.to_node.name, ln.to_socket.identifier)
    return h.hexdigest()[:24]


def _store_in_cache(path, cache_path):
    """The new view file goes into the cache (oldest files removed). Returns the path to use."""
    if not cache_path:
        return path
    try:
        import shutil
        shutil.move(path, cache_path)
    except OSError:
        return path
    files = sorted((os.path.join(view_cache_dir(), f) for f in os.listdir(view_cache_dir()) if f.endswith(".glb")),
                   key=lambda f: os.path.getmtime(f), reverse=True)
    for old in files[VIEW_CACHE_KEEP:]:
        if old != PREVIEW.get("path"):
            try:
                os.remove(old)
            except OSError:
                pass
    return cache_path


def _finish_export(path):
    old = PREVIEW["path"]
    PREVIEW["version"] += 1
    PREVIEW["path"] = path
    PREVIEW["bytes"] = os.path.getsize(path)
    in_cache = old and os.path.dirname(os.path.abspath(old)) == os.path.abspath(view_cache_dir())
    if old and not in_cache and os.path.isfile(old) and old != path:
        try:
            os.remove(old)
        except OSError:
            pass


def preview_status(_data=None):
    with EXPORT["lock"]:
        out = {k: EXPORT[k] for k in ("state", "id", "phase", "fraction", "detail", "error")}
        out["elapsed"] = round(time.time() - EXPORT["started"], 1) if EXPORT["started"] else 0
    out.update(version=PREVIEW["version"], url=f"preview.glb?v={PREVIEW['version']}", bytes=PREVIEW["bytes"])
    return out


def cancel_preview(_data=None):
    """From the HTTP thread: stops the running export (the view keeps showing the previous one)."""
    with EXPORT["lock"]:
        proc = EXPORT["proc"]
        if EXPORT["state"] == "running":
            EXPORT["state"] = "cancelled"
    if proc is not None and proc.poll() is None:
        try:
            proc.kill()
        except OSError:
            pass
    return preview_status()


def export_preview(data=None):
    """Whole scene as GLB (Z-up, metres, object ids in node extras) for the real-time viewport.
    Runs in a second Blender process: returns at once, GET preview/status tells when the file is ready."""
    data = data or {}
    import subprocess
    cancel_preview()                                          # a newer scene replaces an export still running
    with EXPORT["lock"]:
        EXPORT.update(state="running", id=EXPORT["id"] + 1, phase=tr("Preparazione della vista 3D"), fraction=None,
                      detail=tr("copia della scena"), started=time.time(), error="", proc=None)
        job_id = EXPORT["id"]
    max_px = realtime_texture_px()
    path = os.path.join(STATE.tmp, f"preview_{job_id}.glb")
    t0 = time.time()
    fp = view_fingerprint(max_px)
    cached = os.path.join(view_cache_dir(), fp + ".glb")
    if os.path.isfile(cached) and not data.get("noCache"):
        # the same scene was already prepared (reopening a project, undo, a restart): no export at all
        try:
            os.utime(cached)
        except OSError:
            pass
        with EXPORT["lock"]:
            _finish_export(cached)
            EXPORT.update(state="done", phase="", detail="", fraction=1.0)
        log("SIMPLER_EXPORT", f"id={job_id}", f"from cache in {time.time() - t0:.2f}s",
            f"{os.path.getsize(cached) / 1e6:.0f} MB")
        return preview_status()
    EXPORT["cache_to"] = cached
    log("SIMPLER_EXPORT", f"id={job_id}", "start", f"fingerprint {time.time() - t0:.2f}s")
    exe = os.environ.get("SIMPLER_RENDER_EXE") or bpy.app.binary_path
    if not exe or not os.path.isfile(exe) or data.get("inProcess"):
        return _export_in_process(path, job_id)
    job_dir = tempfile.mkdtemp(prefix="simpler_export_", dir=STATE.tmp)
    blend = os.path.join(job_dir, "scene.blend")
    try:
        bpy.ops.file.make_paths_absolute()
    except RuntimeError:
        pass
    from . import trash
    with trash.excluded(), (proxies.originals() if max_px <= 0 else _nothing()):
        bpy.ops.wm.save_as_mainfile(filepath=blend, copy=True, compress=False, relative_remap=False, check_existing=False)
    script = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "export_job.py")
    use_proxies = max_px > 0
    if use_proxies:
        proxies.ensure_async(sizes=(max_px,))   # reduced copies at this size first (parallel, cached for next time)
    done = threading.Event()

    def launch():
        # waits for the texture proxies (other threads keep the engine free), then exports
        try:
            while use_proxies and proxies.status()["running"]:
                st = proxies.status()
                with EXPORT["lock"]:
                    if EXPORT["id"] != job_id or EXPORT["state"] != "running":
                        return
                    EXPORT.update(phase=tr("Ottimizzazione delle texture"), fraction=0.5 * st["done"] / max(1, st["total"]),
                                  detail=tr("{0} di {1}", st["done"], st["total"]))
                time.sleep(0.25)
            map_file = ""
            if use_proxies:
                map_file = os.path.join(job_dir, "proxies.json")
                with open(map_file, "w", encoding="utf-8") as f:
                    json.dump(proxies.proxy_map(max_px), f)
            cmd = [exe, "--factory-startup", "-t", str(cpu_threads()), "-b", blend, "--python", script, "--",
                   path, str(max_px), map_file]
            flags = (0x08000000 | 0x00004000) if os.name == "nt" else 0   # no window, below normal priority
            with EXPORT["lock"]:
                if EXPORT["id"] != job_id or EXPORT["state"] != "running":
                    return
                proc = fullspeed.popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, encoding="utf-8",
                                        errors="replace", creationflags=flags, bufsize=1)
                EXPORT["proc"] = proc
                EXPORT.update(phase=tr("Preparazione della vista 3D"), fraction=None,
                              detail=tr("esportazione di geometrie, materiali e texture"))
            _watch_export(proc, job_id, path, job_dir)
        finally:
            done.set()

    threading.Thread(target=launch, daemon=True).start()
    out = preview_status()
    if data.get("wait"):
        done.wait()
        out = preview_status()
        if out["state"] != "done":
            raise ApiError(out["error"] or tr("Esportazione non riuscita"))
    return out


def _watch_export(proc, job_id, path, job_dir):
    import shutil
    tail = []
    for line in proc.stdout:
        line = line.rstrip()
        tail = (tail + [line])[-12:]
        if line.startswith("SIMPLER_PHASE textures"):
            parts = line.split(" ", 4)
            try:
                i, n = int(parts[2]), max(1, int(parts[3]))
            except (ValueError, IndexError):
                continue
            with EXPORT["lock"]:
                if EXPORT["id"] == job_id:
                    EXPORT.update(phase=tr("Riduzione delle texture per la vista"), fraction=0.6 * i / n,
                                  detail=tr("{0} di {1}", i, n))
        elif line.startswith("SIMPLER_PHASE export"):
            with EXPORT["lock"]:
                if EXPORT["id"] == job_id:
                    EXPORT.update(phase=tr("Preparazione della vista 3D"), fraction=None,
                                  detail=tr("esportazione di geometrie, materiali e texture"))
    proc.wait()
    shutil.rmtree(job_dir, ignore_errors=True)
    with EXPORT["lock"]:
        if EXPORT["id"] != job_id:
            return
        EXPORT["proc"] = None
        if EXPORT["state"] == "cancelled":
            return
        if proc.returncode == 0 and os.path.isfile(path):
            path = _store_in_cache(path, EXPORT.get("cache_to"))
            _finish_export(path)
            EXPORT.update(state="done", phase="", detail="", fraction=1.0)
            log("SIMPLER_EXPORT", f"id={job_id}", f"done in {time.time() - EXPORT['started']:.1f}s",
                f"{os.path.getsize(path) / 1e6:.0f} MB")
        else:
            EXPORT.update(state="error", error=tr("Esportazione della vista non riuscita:\n{0}", "\n".join(tail[-6:])))
            print("SIMPLER_EXPORT_ERROR", "\n".join(tail), flush=True)


def _export_in_process(path, job_id):
    """Development (bpy module): no second Blender available."""
    from . import progress
    progress.begin("preview", tr("Preparazione della vista 3D"))
    try:
        bpy.ops.export_scene.gltf(
            filepath=path, export_format="GLB", use_selection=False, use_visible=False, use_active_scene=True,
            export_extras=True, export_yup=False, export_apply=False, export_cameras=False,
            export_lights=True, export_materials="EXPORT", export_image_format="AUTO",
            export_gpu_instances=True,
        )
    except Exception as exc:
        with EXPORT["lock"]:
            EXPORT.update(state="error", error=str(exc))
        raise
    finally:
        progress.end()
    _finish_export(path)
    with EXPORT["lock"]:
        if EXPORT["id"] == job_id:
            EXPORT.update(state="done", phase="", detail="", fraction=1.0)
    return preview_status()


# ---------------------------------------------------------------- new objects only (a primitive, a model dropped in)
# Before, any new geometry exported the whole scene again (a big interior: 450 MB, 20 s for one cube). Now the view
# gets a small file with only the new objects and adds them to what it has.
PART = {"n": 0, "jobs": {}, "lock": threading.Lock()}
PART_MAX_IN_PROCESS_FACES = 200_000


def _part_objects(ids):
    from .core import PIECE_TYPES
    want = set(ids or [])
    out = []
    for ob in bpy.context.scene.objects:
        if ob.get(ID_KEY) in want and not ob.get(INTERNAL_KEY) and not ob.get("simpler_trashed") and ob.type in PIECE_TYPES \
                and not ob.get("simpler_paint_model") and not ob.get("simpler_paint_data"):
            out.append(ob)
    return out


def _part_in_process_ok(objs):
    """Small and plain (no image textures, no glass shadow trick): exported here in a blink, no second Blender."""
    faces = 0
    for ob in objs:
        if ob.type == "MESH" and ob.data is not None:
            faces += len(ob.data.polygons)
        for slot in ob.material_slots:
            m = slot.material
            if m is None or m.node_tree is None:
                continue
            for n in m.node_tree.nodes:
                if n.type in ("TEX_IMAGE", "TEX_ENVIRONMENT") or n.type == "GROUP":
                    return False
    return faces <= PART_MAX_IN_PROCESS_FACES


def export_part(data=None):
    """Only the objects listed (ids) as a small GLB for the real-time view. Returns at once:
    {"state": "done"|"running", "key"}; GET preview/part/status?k= and preview/part.glb?k= follow."""
    import subprocess
    ids = list((data or {}).get("ids") or [])
    objs = _part_objects(ids)
    if not objs:
        # (1.75.9) nothing drawable among them (paint parts, internal pieces...): nothing to add, and it is not a
        # failure - before, the app read the error as «could not be added» and prepared the WHOLE view again, at
        # every click on a model of such a scene (archmodel palazzi, Luca)
        return {"state": "empty", "key": ""}
    with PART["lock"]:
        PART["n"] += 1
        key = str(PART["n"])
        for k in [k for k, j in PART["jobs"].items() if time.time() - j["t"] > 600]:   # old files: away
            _drop_part(k)
    path = os.path.join(STATE.tmp, f"part_{key}.glb")
    t0 = time.time()
    # (1.76.48, Luca: «ancora molto lento») only a new shape for objects already in the view (a terrain made again
    # after a sculpting, a change of its form): the view keeps its own materials and textures (viewer.js
    # replaceGeometry) - here, without them: no second Blender and no texture written (18 s on a terrain of 3 km)
    geometry_only = bool((data or {}).get("geometry"))
    if geometry_only or _part_in_process_ok(objs):
        layer = bpy.context.view_layer
        was = [o for o in bpy.context.scene.objects if o.select_get()]
        active = layer.objects.active
        try:
            for o in was:
                o.select_set(False)
            for o in objs:
                o.select_set(True)
            if all(o.select_get() for o in objs):
                bpy.ops.export_scene.gltf(
                    filepath=path, export_format="GLB", use_selection=True, use_visible=False, use_active_scene=True,
                    export_extras=True, export_yup=False, export_apply=False, export_cameras=False, export_lights=False,
                    export_materials="PLACEHOLDER" if geometry_only else "EXPORT", export_image_format="AUTO",
                    export_gpu_instances=True)
        except Exception as exc:
            log("SIMPLER_PART", "in process failed", exc)
        finally:
            for o in objs:
                o.select_set(False)
            for o in was:
                try:
                    o.select_set(True)
                except RuntimeError:
                    pass
            layer.objects.active = active
        if os.path.isfile(path):
            with PART["lock"]:
                PART["jobs"][key] = {"state": "done", "path": path, "t": time.time(), "error": ""}
            log("SIMPLER_PART", key, f"{len(objs)} objects in process{' (shape only)' if geometry_only else ''} {time.time() - t0:.2f}s", f"{os.path.getsize(path) / 1e6:.1f} MB")
            return {"state": "done", "key": key}
    # textured or big: the same job as the whole view (reduced textures), on a file with these objects only
    max_px = realtime_texture_px()
    job_dir = tempfile.mkdtemp(prefix="simpler_part_", dir=STATE.tmp)
    blend = os.path.join(job_dir, "part.blend")
    coll = bpy.data.collections.new("SimplerPart")
    try:
        for o in objs:
            coll.objects.link(o)
        bpy.data.libraries.write(blend, {coll}, path_remap="ABSOLUTE", compress=False)
    finally:
        bpy.data.collections.remove(coll)
    if max_px > 0:
        proxies.ensure_async(sizes=(max_px,))
    with PART["lock"]:
        PART["jobs"][key] = {"state": "running", "path": "", "t": time.time(), "error": ""}

    def run():
        import shutil
        err = ""
        tmp_out = os.path.join(job_dir, "part.glb")
        try:
            while max_px > 0 and proxies.status()["running"]:
                time.sleep(0.25)
            map_file = ""
            if max_px > 0:
                map_file = os.path.join(job_dir, "proxies.json")
                with open(map_file, "w", encoding="utf-8") as f:
                    json.dump(proxies.proxy_map(max_px), f)
            exe = os.environ.get("SIMPLER_RENDER_EXE") or bpy.app.binary_path
            script = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "export_job.py")
            cmd = [exe, "--factory-startup", "-t", str(cpu_threads()), "-b", "--python", script, "--",
                   tmp_out, str(max_px), map_file, "--append", blend, "--keep"]
            flags = (0x08000000 | 0x00004000) if os.name == "nt" else 0
            r = fullspeed.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, encoding="utf-8",
                               errors="replace", creationflags=flags)
            if r.returncode == 0 and os.path.isfile(tmp_out):
                os.replace(tmp_out, path)
            else:
                err = "\n".join(r.stdout.splitlines()[-6:]) or "export failed"
        except Exception as exc:
            err = str(exc)
        finally:
            shutil.rmtree(job_dir, ignore_errors=True)
        with PART["lock"]:
            if key in PART["jobs"]:
                PART["jobs"][key].update(state="error" if err else "done", path="" if err else path, error=err)
        log("SIMPLER_PART", key, f"{len(objs)} objects", "error" if err else "done", f"{time.time() - t0:.1f}s", err[-300:])

    threading.Thread(target=run, daemon=True).start()
    return {"state": "running", "key": key}


def part_status(key):
    with PART["lock"]:
        j = PART["jobs"].get(key or "")
        return {"state": j["state"], "error": j["error"]} if j else {"state": "missing", "error": ""}


def part_file(key):
    """The file of a finished part; served once, then removed (the view keeps it in memory)."""
    with PART["lock"]:
        j = PART["jobs"].get(key or "")
        return j["path"] if j and j["state"] == "done" and os.path.isfile(j["path"]) else ""


def _drop_part(key):
    j = PART["jobs"].pop(key, None)
    if j and j.get("path"):
        try:
            os.remove(j["path"])
        except OSError:
            pass
