import sys, time
sys.path.insert(0, "/home/claude/simpler/engine/simpler")
import numpy as np, terrain_gen as T
from PIL import Image
tiles = []
for p in sys.argv[2].split(","):
    t = time.time(); r = T.generate(p, n=384, seed=3)
    print(p, round(time.time() - t, 1), np.percentile(r["slope"], [50, 95]).round(1), flush=True)
    np.save(f"{sys.argv[1]}_{p}.npy", r["h"])
    tiles.append((T.hillshade(r["h"], r["cell"]) * 255).astype(np.uint8))
Image.fromarray(np.concatenate(tiles, 1)).save(sys.argv[1] + ".png")
