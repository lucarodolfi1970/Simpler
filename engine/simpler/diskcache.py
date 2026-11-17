"""(1.76.49, Luca: «è importante che non accumuli spazzatura, occupa giga») The caches on disk of the engine: the shape of
the terrains (terrcache) and the simplified models that tell what hides the view (occcache). Both are only a help:
whatever is missing is computed again. Kept small: at most LIMITS (size and files), nothing older than MAX_DAYS
unused (a file read is «used»: its date is renewed), half-written files away. Pruned after every write and at every
opening of a scene."""
import os
import tempfile
import time

MAX_DAYS = 30
LIMITS = {"terrcache": (150e6, 12), "occcache": (400e6, 60),     # bytes, files
          # (1.76.51, audit: 23 GB of the view cache and 11 GB of reduced textures on Luca's PC, never cleaned) the
          # caches of the real-time view: the points of the distributions, the prototypes of the models (.glb and its
          # .json, together), the reduced textures. All made again when missing (a prototype: a few seconds)
          "viewcache/points": (2e9, 2000), "viewcache/proto": (4e9, 1600), "texcache": (3e9, 15000)}
EXTS = {"viewcache/points": (".bin",), "viewcache/proto": (".glb", ".json"), "texcache": (".png", ".jpg", ".jpeg", ".exr", ".hdr", ".tif", ".tiff", ".tga", ".bmp", ".webp")}
KEEP = {"viewcache/points": 86400, "viewcache/proto": 86400, "texcache": 86400}    # (s) used this recently: never taken
NEVER = {"packed_index.json"}
_LAST = {}


def folder(name):
    return os.path.join(os.environ.get("LOCALAPPDATA") or tempfile.gettempdir(), "Simpler", name)


def prune(name, protect=()):
    """The cache within its limits: the oldest (by last use) out first; never a file in protect (normcased absolute
    paths: the images the open scene shows). -> bytes freed."""
    d = folder(name)
    if not os.path.isdir(d):
        return 0
    max_bytes, max_files = LIMITS.get(name, (200e6, 30))
    exts, keep = EXTS.get(name, (".npz",)), KEEP.get(name, 0)
    now = time.time()
    _LAST[name] = now
    units, freed = {}, 0          # (the files of one stem go together: a prototype's .glb and .json)
    for n in os.listdir(d):
        p = os.path.join(d, n)
        if n in NEVER or not os.path.isfile(p) or (protect and os.path.normcase(os.path.abspath(p)) in protect):
            continue
        try:
            st = os.stat(p)
        except OSError:
            continue
        # (a half-written file of a write that died, older than a minute; anything not ours; unused for too long)
        if ".tmp" in n and now - st.st_mtime > 60 or not n.lower().endswith(exts) or now - st.st_mtime > MAX_DAYS * 86400:
            if ".tmp" not in n and not n.lower().endswith(exts) and name in EXTS:
                continue              # (a view cache: a file of another kind is left alone)
            try:
                os.remove(p); freed += st.st_size
            except OSError:
                pass
            continue
        u = units.setdefault(n.split(".")[0], [0.0, 0, []])
        u[0] = max(u[0], st.st_mtime); u[1] += st.st_size; u[2].append(p)
    files = sorted(units.values(), key=lambda u: u[0])
    total, count = sum(u[1] for u in files), sum(len(u[2]) for u in files)
    while files and (total > max_bytes or count > max_files) and now - files[0][0] > keep:
        _t, sz, ps = files.pop(0)
        for p in ps:
            try:
                os.remove(p)
            except OSError:
                pass
        freed += sz; total -= sz; count -= len(ps)
    return freed


def prune_soon(name, every=300):
    """prune(name) at most every few minutes (after the writes of a busy session)."""
    if time.time() - _LAST.get(name, 0) > every:
        try:
            prune(name)
        except OSError:
            pass


def touch(path):
    """A cached file used: its date renewed (the cache keeps the files used last)."""
    try:
        os.utime(path)
    except OSError:
        pass


VIEW_FILES_AGE = 2 * 3600     # (s) a file of the view of another engine session: away after two hours


def prune_view_files():
    """(1.76.51, audit) The maps of the view (rain/: shelter, snow mantle, ice, painted dirt and wet, flakes - named
    <kind>_<pid>_<rev>): each kind took away only its own older files when it wrote a new one, so the last one of
    a session stayed forever (132 MB of a snow mantle, Luca). Files of another engine session, not touched for
    two hours, go (a final render still reading one has long finished). -> bytes freed."""
    d = folder("rain")
    if not os.path.isdir(d):
        return 0
    me, now, freed = str(os.getpid()), time.time(), 0
    for n in os.listdir(d):
        parts = n.split("_")
        if len(parts) < 3 or parts[1] == me:
            continue
        p = os.path.join(d, n)
        try:
            st = os.stat(p)
            if now - st.st_mtime > VIEW_FILES_AGE:
                os.remove(p); freed += st.st_size
        except OSError:
            pass
    return freed


def prune_all(protect=()):
    freed = sum(prune(n, protect) for n in LIMITS) + prune_view_files()
    if freed > 1e6:
        print(f"SIMPLER_CACHE {freed / 1e6:.0f} MB of old caches taken away", flush=True)
    return freed
