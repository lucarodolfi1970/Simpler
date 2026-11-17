"""Progress of the long command currently running, readable from the HTTP thread at any time.

The main thread updates it; GET /api/progress reads it without waiting for the job queue, so the app can show
a real progress bar while an import, a texture search or a final render is running.
"""
import re
import threading
import time

import bpy

from .i18n import tr

_lock = threading.Lock()
_state = {"active": False, "task": "", "phase": "", "fraction": None, "started": 0.0, "detail": "",
          "samples": 0, "samplesTotal": 0}   # (1.75.20) the samples of the final render, for its chart
_SAMPLE = re.compile(r"Sample (\d+)/(\d+)")
_PEAK = re.compile(r"(?:Peak|Mem):?\s*([\d.]+)\s*([KMG])", re.I)

# Path-tracing view: what Cycles is doing during a viewport pass. On a very big scene the first pass
# synchronises every object, builds the BVH and loads every texture onto the GPU; that can take minutes,
# so the view shows the phase instead of a bare "calcolo…".
_vp = {"active": False, "started": 0.0, "phase": "", "detail": "", "memory": "", "error": "", "stats": "",
       "objects": 0, "objectsTotal": 0, "images": 0, "imagesTotal": 0, "fraction": None, "eta": None,
       "phaseStarted": 0.0, "seenImages": set(), "seenObjects": set(), "expectedBytes": 0, "gpuBase": None}

# Cycles status -> (label, order) — the phase words come from Cycles' own status line
_PHASES = [
    ("kernel", "Caricamento del motore GPU (solo la prima volta può richiedere minuti)"),
    ("Synchroniz", "Lettura degli oggetti"),
    ("Image", "Caricamento delle texture"),
    ("BVH", "Costruzione della struttura di accelerazione"),
    ("Mesh", "Preparazione delle geometrie"),
    ("Geometry", "Preparazione delle geometrie"),
    ("Object", "Preparazione degli oggetti"),
    ("Shader", "Compilazione dei materiali"),
    ("Light", "Preparazione delle luci"),
    ("Background", "Preparazione dell'ambiente"),
    ("Device", "Trasferimento della scena alla GPU"),
    ("Denois", "Riduzione del rumore"),
    ("Sample", "Calcolo dell'immagine"),
    ("Path Trac", "Calcolo dell'immagine"),
]


def _status_parts(stats):
    """Cycles' status line: 'Fra:1 Mem:… | Time:… | Mem:…, Peak:… | Scene, ViewLayer | Phase | detail'."""
    parts = [p.strip() for p in stats.split("|")]
    keep = [p for p in parts if p and not p.startswith(("Fra:", "Time:", "Remaining:", "Mem:", "Peak", "Frame"))
            and not re.match(r"^[\d.]+[KMG]", p)]
    return keep


def _phase_label(text):
    for key, label in _PHASES:
        if key.lower() in text.lower():
            return tr(label)
    return ""


def viewport_begin(objects_total=0, images_total=0, expected_bytes=0):
    with _lock:
        _vp.update(active=True, started=time.time(), sampleAt=0.0, phase=tr("Preparazione della scena"), detail="", error="", stats="",
                   objects=0, objectsTotal=objects_total, images=0, imagesTotal=images_total, fraction=None,
                   eta=None, phaseStarted=time.time(), seenImages=set(), seenObjects=set(),
                   expectedBytes=expected_bytes, gpuBase=None)


def viewport_phase(phase, detail="", fraction=None):
    """A step of Simpler's own before Cycles starts (e.g. the light reflected by water): shown as the phase."""
    with _lock:
        if not _vp["active"]:
            _vp.update(active=True, started=time.time(), error="", stats="", memory="", eta=None)
        if _vp["phase"] != phase:
            _vp["phaseStarted"] = time.time()
        _vp.update(phase=phase, detail=detail, fraction=fraction)


def viewport_end(error=""):
    with _lock:
        _vp.update(active=False, error=error or "")


def viewport_snapshot():
    with _lock:
        out = {k: v for k, v in _vp.items() if not k.startswith("seen")}
    out["elapsed"] = round(time.time() - out["started"], 1) if out["active"] else 0
    # uploading textures: Cycles sends no news for minutes on big scenes, but the graphics card fills up.
    # Progress = memory added since the phase began / memory the textures need (estimated from their sizes).
    if out["active"] and out["phase"] == tr("Caricamento delle texture") and out["gpuBase"] is not None \
            and out["expectedBytes"] > 0 and out.get("fraction") is None:
        from . import gpu
        used = gpu.used_bytes()
        if used is not None:
            f = max(0.0, min(0.97, (used - out["gpuBase"]) / out["expectedBytes"]))
            spent = time.time() - out["phaseStarted"]
            out["fraction"] = f
            out["eta"] = round(spent / f * (1 - f)) if f > 0.03 and spent > 3 else None
            if out["imagesTotal"]:
                out["detail"] = f"≈ {int(f * out['imagesTotal'])}/{out['imagesTotal']}"
            out["memory"] = f"{used / 1073741824:.1f} GB"
    out.pop("gpuBase", None)
    out.pop("expectedBytes", None)
    return out


def _viewport_stats(stats):
    parts = _status_parts(stats)
    m = _PEAK.search(stats)
    mem = ""
    if m:
        v, unit = float(m.group(1)), m.group(2).upper()
        gb = v / 1024 if unit == "M" else (v if unit == "G" else v / 1048576)
        mem = f"{gb:.1f} GB" if gb >= 1 else f"{gb * 1024:.0f} MB"
    # skip the "Scene, ViewLayer" part: the phase is the first part with a known word, the detail what follows
    phase, detail = "", ""
    for i, p in enumerate(parts):
        if ", " in p and i < len(parts) - 1:
            continue   # "Scene, ViewLayer"
        label = _phase_label(p)
        if label:
            phase = label
            rest = parts[i + 1:]
            last = rest[-1] if rest else ""
            if "Synchroniz" in p:
                detail = last                                   # object name
            elif last.startswith("Loading "):
                detail = last[8:]                               # texture file name
            else:
                pm = re.search(r"(\d+%)", last)
                sm = _SAMPLE.search(p)
                detail = pm.group(0) if pm else (tr("campione {0} di {1}", sm.group(1), sm.group(2)) if sm else "")
            break
    err = ""
    low = stats.lower()
    if "out of memory" in low or any(p.lower().startswith("error") for p in parts):
        err = parts[-1] if parts else stats
    with _lock:
        _vp["stats"] = stats[-300:]
        now = time.time()
        if phase and phase != _vp["phase"]:
            _vp["phaseStarted"] = now
            if phase == tr("Calcolo dell'immagine") and not _vp.get("sampleAt"):
                _vp["sampleAt"] = now       # (1.76.50: how long Cycles prepared the scene before sampling)
            _vp["fraction"] = None
            _vp["eta"] = None
            _vp["seenImages"] = set()        # Cycles goes through the textures twice (sizes, then pixels)
            if phase == tr("Caricamento delle texture"):
                from . import gpu
                _vp["gpuBase"] = gpu.used_bytes()
            # in the log: what Cycles does and when (to understand slow scenes)
            print(f"SIMPLER_VP {now - _vp['started']:7.1f}s {phase} | {stats[-160:]}", flush=True)
        done = total = 0
        if "Synchronizing object" in stats:
            _vp["seenObjects"].add(detail)
            done, total = len(_vp["seenObjects"]), _vp["objectsTotal"]
        elif "Images" in stats:
            if detail:
                _vp["seenImages"].add(detail)
            done, total = len(_vp["seenImages"]), _vp["imagesTotal"]
        if total and done:
            done = min(done, total)
            detail = f"{done}/{total}" + (f" · {detail}" if detail else "")
            _vp["fraction"] = done / total
            spent = now - _vp["phaseStarted"]
            _vp["eta"] = round(spent / done * (total - done)) if done >= 3 and spent > 2 else None
        elif phase:
            pm = re.search(r"(\d+)%", stats)
            _vp["fraction"] = int(pm.group(1)) / 100 if pm and "BVH" in stats else None
            _vp["eta"] = None
        if phase:
            _vp["phase"] = phase
            _vp["detail"] = detail[:120]
        if mem and not mem.startswith("0 "):
            _vp["memory"] = mem
        if err and not _vp["error"]:
            _vp["error"] = err[:300]


def begin(task, phase=""):
    with _lock:
        _state.update(active=True, task=task, phase=phase, fraction=None, started=time.time(), detail="",
                      samples=0, samplesTotal=0)


def update(phase=None, fraction=None, detail=None, samples=None):
    """samples: (done, total) of the final render, read by the busy screen's chart of the samples over time."""
    with _lock:
        if samples is not None:
            _state["samples"], _state["samplesTotal"] = int(samples[0]), int(samples[1])
        if phase is not None:
            _state["phase"] = phase
        _state["fraction"] = None if fraction is None else max(0.0, min(1.0, float(fraction)))
        if detail is not None:
            _state["detail"] = detail


def end():
    with _lock:
        _state.update(active=False, phase="", fraction=None, detail="", samples=0, samplesTotal=0)


def snapshot():
    with _lock:
        out = dict(_state)
    out["elapsed"] = round(time.time() - out["started"], 1) if out["active"] else 0
    return out


# Cycles reports its progress through render_stats ("Sample 12/128", "Loading images", ...)
# persistent: the handler must survive opening projects and undo snapshots
@bpy.app.handlers.persistent
def _render_stats(stats):
    with _lock:
        vp = _vp["active"]
        final = _state["active"] and _state["task"] == "render"
    if vp and not final:
        _viewport_stats(stats)
        return
    if not final:
        return
    m = _SAMPLE.search(stats)
    if m:
        done, total = int(m.group(1)), max(1, int(m.group(2)))
        update(tr("Calcolo dell'immagine"), 0.05 + 0.9 * done / total, tr("campione {0} di {1}", done, total), (done, total))
    elif "Synchroniz" in stats:
        update(tr("Preparazione della scena"), 0.02)
    elif "Loading" in stats or "Updating" in stats:
        update(tr("Caricamento di geometrie e texture"), 0.04)
    elif "Denois" in stats:
        update(tr("Riduzione del rumore"), 0.97)


def install():
    if _render_stats not in bpy.app.handlers.render_stats:
        bpy.app.handlers.render_stats.append(_render_stats)
