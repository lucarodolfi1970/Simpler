"""(1.76.37, Luca: «ci sono molti slider che sembrano non funzionare ... cosa ce ne facciamo?») Every slider of a panel
moved from one end to the other must change the picture. A scene with a terrain, its sea and a sphere at the water
line; for each slider: a small path-traced picture at both ends, the mean difference of the pixels. Under LIMIT: the
slider does nothing you can see there - it goes in the report (to fix, to explain, or to take away).

python tools/slider_audit.py --out report.json [--only height,wind] [--port 8851]"""
import argparse
import json
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import regression as R  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
LIMIT = 1.0              # mean difference of the pixels (0..255) under which a slider «does nothing»

# (panel, label, endpoint, body(value), low, high)
def ocean(k, **pre):
    return lambda v: ("landscape/ocean", {"settings": dict(pre, **{k: v})})


SLIDERS = [
    ("Oceano", "Altezza onde", ocean("height"), 0.2, 3.0),
    ("Oceano", "Vento", ocean("wind"), 3.0, 20.0),
    ("Oceano", "Creste", ocean("chop"), 0.0, 2.0),
    ("Oceano", "Direzione", ocean("direction"), 0.0, 120.0),
    ("Oceano", "Schiuma", ocean("foam"), 0.0, 1.0),
    ("Oceano › Avanzate", "Increspature", ocean("ripples"), 0.0, 1.0),
    ("Oceano › Avanzate", "Allineamento", ocean("align"), 0.0, 1.0),
    ("Oceano › Avanzate", "Onde più piccole", ocean("smallest"), 0.01, 1.0),
    ("Oceano › Avanzate", "Smorzamento", ocean("damping"), 0.0, 1.0),
    ("Oceano › Avanzate", "Profondità", ocean("depth"), 5.0, 200.0),
    ("Oceano › Avanzate (spettro con picco)", "Distanza dal vento", ocean("fetch", spectrum="sharp"), 1.0, 1000.0),
    ("Oceano › Avanzate", "Istante", ocean("time"), 0.0, 30.0),
    ("Costa", "Schiuma della costa", ocean("coastFoam"), 0.0, 2.0),
    ("Costa › Avanzate", "Limpidezza", ocean("clarity"), 0.2, 4.0),
    ("Costa › Avanzate", "Fascia bagnata", ocean("wetBand"), 0.0, 3.0),
    ("Costa › Avanzate", "Acqua mossa sul bordo", ocean("edgeMove"), 0.0, 3.0),
]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", required=True)
    ap.add_argument("--engine", default=os.path.join(ROOT, "engine"))
    ap.add_argument("--scene", default="/mnt/user-data/uploads/Scene--Simpler/auto.simpler")
    ap.add_argument("--port", type=int, default=8851)
    ap.add_argument("--only", default="")
    a = ap.parse_args()
    import numpy as np
    from PIL import Image
    eng = R.Engine(a.engine, a.scene, a.port, None)
    eng.idle(300)
    out = {"limit": LIMIT, "sliders": []}
    try:
        eng.call("POST", "terrain/create", {"preset": "colline"}, timeout=900); eng.idle()
        eng.call("POST", "landscape/ocean", {"preset": "mosso"}, timeout=900); eng.idle()
        lv = eng.call("GET", "ambience")[0]["ocean"]["settings"]["level"]
        # (a point of the shore of «colline», the sea towards -x: the camera a few metres out, low, looking at it)
        px, py, ux, uy = -271.09, -189.99, -0.9756, 0.2195
        eng.call("POST", "models/primitive", {"kind": "sphere"})          # (if there is no such route, no sphere)
        eng.call("POST", "camera", {"action": "lookat", "position": [(px + ux * 18) * 100, (py + uy * 18) * 100, (lv + 4) * 100],
                                    "target": [(px + ux * 3) * 100, (py + uy * 3) * 100, lv * 100], "vfov": 45, "aspect": 1.78})
        eng.idle()
        tmp = eng.tmp

        def shot(tag):
            p = os.path.join(tmp, f"a_{tag}.png")
            eng.call("POST", "render", {"path": p, "width": 192, "height": 108, "samples": 12, "denoise": False, "inProcess": True,
                                        "seed": 1}, timeout=900)
            return np.asarray(Image.open(p).convert("RGB"), dtype=np.float32)

        only = set(x.strip() for x in a.only.split(",") if x.strip())
        for panel, label, body, lo, hi in SLIDERS:
            if only and label not in only:
                continue
            t = time.time()
            path, b = body(lo); eng.call("POST", path, b, timeout=900); eng.idle()
            A = shot("lo")
            path, b = body(hi); eng.call("POST", path, b, timeout=900); eng.idle()
            B = shot("hi")
            diff = float(np.abs(A - B).mean())
            eng.call("POST", "undo", {}, timeout=300); eng.call("POST", "undo", {}, timeout=300); eng.idle()
            rec = {"panel": panel, "label": label, "low": lo, "high": hi, "diff": round(diff, 2), "ok": diff >= LIMIT,
                   "secs": round(time.time() - t, 1)}
            out["sliders"].append(rec)
            print(f"  {'ok ' if rec['ok'] else 'NO '} {diff:7.2f}  {panel} · {label}", flush=True)
    finally:
        eng.stop()
        json.dump(out, open(a.out, "w"), ensure_ascii=False, indent=1)
    bad = [s for s in out["sliders"] if not s["ok"]]
    print(f"\n{len(bad)} of {len(out['sliders'])} sliders change nothing visible", flush=True)


if __name__ == "__main__":
    main()
