"""Final render in a separate Blender process (so it can be cancelled and the engine stays light).

Started by the engine as:
    blender.exe --factory-startup -b scene.blend --python render_job.py -- <output> <device>
Prints SIMPLER_STATS lines (Cycles progress) and SIMPLER_DONE at the end.
With a third argument (a folder): the measurement of where the time goes (see _measure).
"""
import os
import sys
import time

import bpy

argv = sys.argv[sys.argv.index("--") + 1:]
out, device = argv[0], (argv[1] if len(argv) > 1 else "CPU")
measure = argv[2] if len(argv) > 2 else ""
T = {"start": time.time(), "sampling": None, "denoise": None, "quiet": False}

scene = bpy.context.scene
# path tracing view helpers (simpler/twins.py): not needed for one image, where the static layout is the fastest
# (in one call, 1.70.3: one by one each removal looks through all the objects - 42 s for the cathedral's 3,800 twins)
bpy.data.batch_remove([o for o in bpy.data.objects if o.get("simpler_twin")])
scene.render.engine = "CYCLES"
# (1.75.18) the rain as this copy carries it: the same line as SIMPLER_FINALDIAG of the engine, from the loaded file
try:
    _g = next((g for g in bpy.data.node_groups if g.name.startswith("Simpler Pioggia v") and "BSDF" not in g.name), None)
    if _g is None:
        print("SIMPLER_DIAG rain group: none", flush=True)
    else:
        _v = {k: round(_g.nodes[k].outputs[0].default_value, 3) for k in ("wet", "puddles", "sh_on") if _g.nodes.get(k)}
        _t = _g.nodes.get("shelter")
        _im = _t.image if _t is not None else None
        _p = bpy.path.abspath(_im.filepath) if _im is not None else ""
        _wet = sum(1 for m in bpy.data.materials if m.node_tree is not None and m.node_tree.nodes.get("simpler_wet_out") is not None)
        print(f"SIMPLER_DIAG rain {_g.name} {_v}, shelter {_im.name if _im else None} {_p} exists={os.path.isfile(_p) if _p else False} "
              f"size={tuple(_im.size) if _im else None} has_data={_im.has_data if _im else None}, wet materials {_wet}", flush=True)
except Exception as _exc:
    print(f"SIMPLER_DIAG failed: {_exc}", flush=True)
if device != "CPU":
    try:
        prefs = bpy.context.preferences.addons["cycles"].preferences
        prefs.compute_device_type = device
        (prefs.refresh_devices if hasattr(prefs, "refresh_devices") else prefs.get_devices)()
        for d in prefs.devices:
            d.use = d.type == device
        scene.cycles.device = "GPU"
        used = [f"{d.name} ({d.type})" for d in prefs.devices if d.use]
        print("SIMPLER_DEVICE " + (", ".join(used) or "none: CPU"), flush=True)
        if not used:
            scene.cycles.device = "CPU"
    except Exception as exc:  # fall back to CPU, the render still completes
        print("SIMPLER_WARN GPU non disponibile:", exc, flush=True)
        scene.cycles.device = "CPU"


def _stats(stats):
    if T["sampling"] is None and "Sample" in stats:
        T["sampling"] = time.time()
    if T["denoise"] is None and "Denois" in stats:
        T["denoise"] = time.time()
    if not T["quiet"]:
        print("SIMPLER_STATS " + stats.replace("\n", " "), flush=True)


bpy.app.handlers.render_stats.append(_stats)
print(f"SIMPLER_JOB {scene.render.resolution_x}x{scene.render.resolution_y} samples={scene.cycles.samples} "
      f"device={scene.cycles.device} simplify={scene.render.use_simplify} images={len(bpy.data.images)}", flush=True)
scene.render.filepath = out
# (18/11, the squares of light on the sofa under the water: Luca's scene cannot be rendered outside his PC) with the file
# test_out/luce.on in the Simpler folder this render also keeps the light apart (emission = the light reflected by
# the water, direct and indirect diffuse, colour, glossy, transmission) and writes it to test_out/luce/luce.exr, with
# the images of the light reflected by the water and where they are projected. One render: the flag is removed.
_luce = None
try:
    _root0 = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    if os.path.isfile(os.path.join(_root0, "test_out", "luce.on")):
        os.remove(os.path.join(_root0, "test_out", "luce.on"))
        _luce = os.path.join(_root0, "test_out", "luce")
        os.makedirs(_luce, exist_ok=True)
        for _vl in scene.view_layers:
            for _a in ("use_pass_emit", "use_pass_diffuse_direct", "use_pass_diffuse_indirect", "use_pass_diffuse_color",
                       "use_pass_glossy_direct", "use_pass_glossy_indirect", "use_pass_transmission_direct",
                       "use_pass_transmission_indirect", "use_pass_z", "use_pass_normal"):
                setattr(_vl, _a, True)
        print("SIMPLER_LIGHTPASSES on", flush=True)
except Exception as _exc:
    print(f"SIMPLER_LIGHTPASSES not set: {_exc}", flush=True)
_meter = scene.get("simpler_meter")
if _meter:
    # (1.79.0) «Esposizione sull'inquadratura» (simpler/meter.py): the image itself is measured, then saved with its
    # exposure - no second render. With the «Luce di riempimento» (it follows the exposure, it must be right before
    # the image) a 160-point render is measured first.
    import json
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    from simpler import meter as _m
    _cfg = json.loads(_meter)
    _fill = next((o for o in scene.objects if o.get("simpler_fill")), None)
    _dir = os.path.dirname(os.path.abspath(out))

    def _expose(ev):
        auto = _m.combine(_cfg["auto"], ev, _cfg["night"])
        scene.view_settings.exposure = _cfg["user"] + auto
        if _fill is not None:
            _fill.data.energy = _m.fill_energy(_cfg["fill"], auto)
        print(f"SIMPLER_METER job ev={ev} exposure={scene.view_settings.exposure:.2f}", flush=True)
    if _fill is not None:
        T["quiet"] = True
        try:
            _expose(_m.tiny(scene, _dir, scene.render.resolution_x, scene.render.resolution_y))
        finally:
            T.update(quiet=False, sampling=None, denoise=None)
        bpy.ops.render.render(write_still=True)
    else:
        bpy.ops.render.render(write_still=False)
        _expose(_m.measure(scene, _dir))
        bpy.data.images["Render Result"].save_render(out, scene=scene)
else:
    bpy.ops.render.render(write_still=True)
T["end"] = time.time()
if _luce:
    try:
        import shutil
        _st = scene.render.image_settings
        _keep = (getattr(_st, "media_type", None), _st.file_format, _st.color_depth, _st.exr_codec)
        if hasattr(_st, "media_type"):
            _st.media_type = "MULTI_LAYER_IMAGE"
        _st.file_format = "OPEN_EXR_MULTILAYER"
        _st.color_depth = "16"; _st.exr_codec = "DWAA"
        try:
            bpy.data.images["Render Result"].save_render(os.path.join(_luce, "luce.exr"), scene=scene)
        finally:
            if _keep[0] is not None:
                _st.media_type = _keep[0]
            _st.file_format, _st.color_depth, _st.exr_codec = _keep[1:]
        with open(os.path.join(_luce, "info.txt"), "w", encoding="utf-8") as _f:
            _cam = scene.camera
            _f.write(f"{scene.render.resolution_x}x{scene.render.resolution_y} samples={scene.cycles.samples}\n")
            if _cam is not None:
                _f.write(f"camera\t{[list(r) for r in _cam.matrix_world]}\tlens={_cam.data.lens}\tsensor={_cam.data.sensor_width}\n")
            for _o in scene.objects:
                if _o.type == "LIGHT":
                    _f.write(f"light\t{_o.name}\t{_o.data.type}\t{_o.data.energy}\t{list(_o.matrix_world.translation)}\t"
                             f"hide={_o.hide_render}\tcaustics={_o.data.cycles.is_caustics_light}\n")
                elif _o.type == "MESH" and (_o.cycles.is_caustics_caster or _o.get("simpler_caster") or "Plane.002" in _o.name
                                            or "sofa" in _o.name.lower()):
                    _bb = [_o.matrix_world @ __import__("mathutils").Vector(c) for c in _o.bound_box]
                    _f.write(f"mesh\t{_o.name}\tcaster={_o.cycles.is_caustics_caster}\tsimpler_caster={_o.get('simpler_caster')}\t"
                             f"hide={_o.hide_render}\tz={min(p.z for p in _bb):.3f}..{max(p.z for p in _bb):.3f}\t"
                             f"x={min(p.x for p in _bb):.2f}..{max(p.x for p in _bb):.2f}\ty={min(p.y for p in _bb):.2f}..{max(p.y for p in _bb):.2f}\t"
                             f"mats={[sl.material.name for sl in _o.material_slots if sl.material]}\t"
                             f"mods={[(m.name, m.type, m.show_render) for m in _o.modifiers]}\n")
            try:
                _dg = bpy.context.evaluated_depsgraph_get()
                for _o in scene.objects:
                    if _o.type == "MESH" and (_o.get("simpler_caster") or "Plane.002" in _o.name):
                        _e = _o.evaluated_get(_dg)
                        _f.write(f"evaluated\t{_o.name}\tverts={len(_e.data.vertices)}\tpolys={len(_e.data.polygons)}\t"
                                 f"scale={list(_o.scale)}\tprops={ {k: (v if isinstance(v, (int, float, str)) else str(v)[:300]) for k, v in _o.items()} }\n")
                        for _m in _o.material_slots:
                            if _m.material is not None:
                                _f.write(f"watermat\t{_m.material.name}\t{ {k: str(v)[:600] for k, v in _m.material.items()} }\n")
            except Exception as _exc:
                _f.write(f"evaluated failed: {_exc}\n")
            _g = bpy.data.node_groups.get("Simpler Reflected Caustics")
            if _g is not None:
                for _k in range(24):
                    _t = _g.nodes.get(f"img{_k}"); _on = _g.nodes.get(f"on{_k}"); _mp = _g.nodes.get(f"map{_k}")
                    if _t is None or _t.image is None:
                        continue
                    _src = bpy.path.abspath(_t.image.filepath)
                    _f.write(f"slot\t{_k}\ton={_on.inputs[1].default_value}\tscale={list(_mp.inputs[1].default_value)}\t"
                             f"offset={list(_mp.inputs[2].default_value)}\tlo={_g.nodes[f'lo{_k}'].inputs[1].default_value}\t"
                             f"hi={_g.nodes[f'hi{_k}'].inputs[1].default_value}\tsize={list(_t.image.size)}\t{_src}\n")
                    if 16 <= _k < 20 and os.path.isfile(_src):
                        shutil.copy(_src, os.path.join(_luce, f"slot{_k}.exr"))
        print(f"SIMPLER_LIGHTPASSES written to {_luce}", flush=True)
    except Exception as _exc:
        print(f"SIMPLER_LIGHTPASSES not written: {_exc}", flush=True)
# (17/11, the dots of the haze on the clouds: Luca's scene cannot be rendered outside his PC) with the file
# test_out/passi.on in the Simpler folder, the passes of this render (picture, Mist, Depth, alpha, Environment, guides of
# the denoiser) are also written to test_out/passi/passi.exr - to rebuild the haze of the compositor on them and try
# corrections on the real thing. One render: the flag is removed.
try:
    _root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    _flag = os.path.join(_root, "test_out", "passi.on")
    if os.path.isfile(_flag):
        os.remove(_flag)
        _pdir = os.path.join(_root, "test_out", "passi")
        os.makedirs(_pdir, exist_ok=True)
        _st = scene.render.image_settings
        _keep = (getattr(_st, "media_type", None), _st.file_format, _st.color_depth, _st.exr_codec)
        if hasattr(_st, "media_type"):          # (Blender 5: all the passes = «Multi-Layer Image»)
            _st.media_type = "MULTI_LAYER_IMAGE"
        _st.file_format = "OPEN_EXR_MULTILAYER"
        _st.color_depth = "32"; _st.exr_codec = "ZIP"
        try:
            bpy.data.images["Render Result"].save_render(os.path.join(_pdir, "passi.exr"), scene=scene)
        finally:
            if _keep[0] is not None:
                _st.media_type = _keep[0]
            _st.file_format, _st.color_depth, _st.exr_codec = _keep[1:]
        with open(os.path.join(_pdir, "info.txt"), "w", encoding="utf-8") as _f:
            _f.write(f"{scene.render.resolution_x}x{scene.render.resolution_y} samples={scene.cycles.samples} "
                     f"mist start={scene.world.mist_settings.start} depth={scene.world.mist_settings.depth}\n")
            _tree = scene.compositing_node_group
            if _tree is not None:
                for _n in _tree.nodes:
                    if _n.bl_idname == "ShaderNodeMath" and (_n.label or _n.name.startswith(("fog_", "keep_", "z_to"))):
                        _f.write(f"{_n.name}\t{_n.label}\t{_n.operation}\t{[round(i.default_value, 6) for i in _n.inputs]}\n")
                    elif _n.name in ("fog_color", "fog_smooth"):
                        _f.write(f"{_n.name}\tmute={_n.mute}\t{list(_n.outputs[0].default_value) if _n.name == 'fog_color' else ''}\n")
        print(f"SIMPLER_PASSES written to {_pdir}", flush=True)
except Exception as _exc:
    print(f"SIMPLER_PASSES failed {_exc}", flush=True)


def _measure(folder):
    """Where the time of a final render goes. Writes into the folder:
    campioni.exr - the picture with the samples each pixel took (Debug Sample Count): where adaptive sampling stops;
    finale_principale.png - the render itself, to compare;
    misura.txt   - the settings that decide the cost, the time of each phase, the time of short renders (128 samples,
                   every pixel) with one setting changed at a time (volume guiding off, light tree off, no clouds);
    variante_*.png - those renders, to compare the quality.
    (First measurement, 1.17.1: the clouds are 94% of the time; volume bounces 24 -> 6 and the step rate of the
    scene changed nothing, not even the picture.)"""
    os.makedirs(folder, exist_ok=True)
    cy = scene.cycles
    lines = [f"risoluzione {scene.render.resolution_x}x{scene.render.resolution_y}  device {cy.device}"]
    for k in ("samples", "use_adaptive_sampling", "adaptive_threshold", "adaptive_min_samples", "max_bounces",
              "diffuse_bounces", "glossy_bounces", "transmission_bounces", "transparent_max_bounces", "volume_bounces",
              "volume_biased", "volume_step_rate", "volume_max_steps", "use_volume_guiding", "use_guiding",
              "caustics_reflective", "caustics_refractive", "sample_clamp_direct", "sample_clamp_indirect",
              "blur_glossy", "use_denoising", "denoiser", "denoising_quality", "use_light_tree"):
        if hasattr(cy, k):
            lines.append(f"{k} = {getattr(cy, k)}")
    lines.append(f"esposizione = {scene.view_settings.exposure}")
    clouds = [o for o in bpy.data.objects if o.get("simpler_clouds") or o.get("simpler_cloud_sun")]
    lines.append(f"nuvole volumetriche: {'sì' if any(o.get('simpler_clouds') for o in clouds) else 'no'}")
    s0, s1, s2, s3 = T["start"], T["sampling"] or T["start"], T["denoise"] or T["end"], T["end"]
    lines.append(f"TEMPO preparazione (caricamento, BVH, texture) {s1 - s0:.1f} s")
    lines.append(f"TEMPO campionamento {s2 - s1:.1f} s")
    lines.append(f"TEMPO denoiser e fine {s3 - s2:.1f} s")
    lines.append(f"TEMPO totale {s3 - s0:.1f} s")
    st = scene.render.image_settings
    img = bpy.data.images["Render Result"]
    try:
        try:
            st.media_type = "MULTI_LAYER_IMAGE"
        except (AttributeError, TypeError):
            pass
        st.file_format = "OPEN_EXR_MULTILAYER"
        st.color_depth = "32"
        img.save_render(os.path.join(folder, "campioni.exr"), scene=scene)
    except Exception as exc:
        lines.append(f"campioni.exr non salvato: {exc}")
    for k in ("media_type",):
        try:
            setattr(st, k, "IMAGE")
        except (AttributeError, TypeError):
            pass
    st.file_format = "PNG"
    st.color_depth = "8"
    st.color_mode = "RGB"

    try:
        img.save_render(os.path.join(folder, "finale_principale.png"), scene=scene)    # (to compare the quality)
    except Exception as exc:
        lines.append(f"finale_principale.png non salvato: {exc}")
    mats = {m for o in clouds if o.type == "VOLUME" or getattr(o.data, "materials", None)
            for m in (getattr(o.data, "materials", None) or []) if m is not None}
    lines.append(f"passo nel materiale delle nuvole: {sorted(round(m.cycles.volume_step_rate, 3) for m in mats)}")

    # 1) short renders, every pixel 128 samples, one setting of the clouds changed at a time
    T["quiet"] = True                   # (the progress bar of the app stays at the end)
    vl = scene.view_layers[0]
    keep = {"samples": cy.samples, "min": cy.adaptive_min_samples, "steps": cy.volume_max_steps,
            "mat": {m.name: m.cycles.volume_step_rate for m in mats}}

    def reset(short=True):
        cy.volume_max_steps = keep["steps"]
        for m in mats:
            m.cycles.volume_step_rate = keep["mat"][m.name]
        cy.samples = 128 if short else keep["samples"]
        cy.use_adaptive_sampling = not short
        cy.adaptive_min_samples = keep["min"]
        try:
            vl.cycles.pass_debug_sample_count = not short
        except AttributeError:
            pass

    def steps(n):
        def f():
            cy.volume_max_steps = n
        return f

    def mat_step(k):
        def f():
            for m in mats:
                m.cycles.volume_step_rate = keep["mat"][m.name] * k
        return f

    def write():
        with open(os.path.join(folder, "misura.txt"), "w", encoding="utf-8") as f:
            f.write("\n".join(lines) + "\n")

    def run(name, change, short=True):
        reset(short)
        if change:
            change()
        t0 = time.time()
        print(f"SIMPLER_MEASURE {name}", flush=True)
        bpy.ops.render.render(write_still=False)
        dt = time.time() - t0
        lines.append(f"{name}: {dt:.1f} s")
        try:
            st.media_type = "IMAGE"         # (after a multilayer EXR: PNG is not an option of MULTI_LAYER_IMAGE)
        except (AttributeError, TypeError):
            pass
        st.file_format = "PNG"
        st.color_depth = "8"
        st.color_mode = "RGB"
        try:
            img.save_render(os.path.join(folder, f"variante_{name}.png"), scene=scene)
        except Exception as exc:
            lines.append(f"  (immagine non salvata: {exc})")
        write()

    lines.append("")
    lines.append("RENDER BREVI (128 campioni su ogni pixel, senza campionamento adattivo):")
    run("base", None)
    if mats:
        # (second measurement, 1.17.3: most steps per ray 2048/1024/512 and the step of the cloud material x2
        # changed nothing either, not even the picture: the Biased ray marching options seem not to apply)
        def attr(name, value):
            def f():
                if hasattr(cy, name):
                    setattr(cy, name, value)
            return f
        keep_extra = {k: getattr(cy, k) for k in ("volume_biased", "use_volume_guiding", "use_light_tree") if hasattr(cy, k)}
        # (third measurement, 1.17.5: without Biased a 128 samples render took over 8 minutes instead of 25 s:
        # Biased stays; that variant is not tried any more)
        for name, change in (("senza_guida_volumi", attr("use_volume_guiding", False)),
                             ("senza_light_tree", attr("use_light_tree", False))):
            for k, v in keep_extra.items():
                setattr(cy, k, v)
            run(name, change)
        for k, v in keep_extra.items():
            setattr(cy, k, v)
        run("senza_nuvole", lambda: [setattr(o, "hide_render", True) for o in clouds])
        for o in clouds:
            o.hide_render = False

    print("SIMPLER_MEASURE done", flush=True)


if measure:
    try:
        _measure(measure)
    except Exception as exc:
        print(f"SIMPLER_MEASURE failed {exc}", flush=True)
print("SIMPLER_DONE", flush=True)
