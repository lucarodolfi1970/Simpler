"""Material editor: a material as a few clear channels (like Twinmotion), built into a Cycles node tree.

The editor never shows Blender nodes. A material edited in Simpler keeps its settings as JSON in the material
(PARAMS_KEY) and its node tree is rebuilt from them at every change ("canonical" tree). Materials coming from FBX
files are read once into the same channels (image textures, normal maps, bump, alpha...); if a material is too
complex to be read without losing something it is left untouched and shown as "advanced" (it can be converted on
request). The first edit keeps a hidden copy of the original material, so "Ripristina originale" and undo can put it
back.

Extras beyond the usual PBR channels:
- dispersion for glass and gems: three refractions with the IOR of red, green and blue light (Cauchy formula from the
  Abbe number), so the stones show coloured "fire" and the path-traced caustics split into colours. Cycles has no
  spectral rendering: the band is chosen again at every surface, so "Intensità" doses the share of dispersive glass
  mixed with plain glass. Sharp (MNEE) caustics follow the plain share (white, a little dimmer).
- true displacement: the surface is really moved by the height map, with adaptive subdivision (detail measured in
  pixels on screen, so far objects stay light). Objects using it get a "Simpler Displacement" modifier.
"""
import copy
import time
import json
import math
import os

import bpy

from .core import ApiError, find
from .i18n import tr

PARAMS_KEY = "simpler_mat"
BACKUP_KEY = "simpler_mat_backup"     # name of the hidden copy of the original material
BACKUP_TAG = "simpler_mat_original"
DISP_MOD = "Simpler Displacement"
VERSION = 3          # 2: UV offset as in the view (Location = -offset × scale, 1.32.1); 3: Box in world space turned with the object (1.36.6)

UV_MODES = ("uv", "box", "planar", "cylinder", "sphere")
DETAIL_PX = {"bassa": 4.0, "media": 2.0, "alta": 1.0}
# reference indices of refraction and Abbe numbers (dispersion)
GLASS_PRESETS = {"vetro": (1.52, 58.0), "acqua": (1.333, 55.7), "diamante": (2.417, 55.3), "zaffiro": (1.77, 72.0),
                 "rubino": (1.77, 72.0), "smeraldo": (1.58, 56.0), "cristallo": (1.60, 36.0), "zirconia": (2.17, 34.0),
                 "plastica": (1.49, 57.0)}


def _map():
    # scale (1.75.60): the map bigger (2 = twice as big) than the material's UV, on its own - a glossiness or normal map
    # over many tiles of a floor instead of the same stain on every tile (Luca, as in 3ds Max)
    return {"image": "", "channel": "", "strength": 1.0, "invert": False, "scale": 1.0}


def map_scale(m):
    try:
        return max(0.01, min(100.0, float((m or {}).get("scale", 1.0) or 1.0)))
    except (TypeError, ValueError):
        return 1.0


DEFAULTS = {
    "version": VERSION,
    "color": {"tint": [0.8, 0.8, 0.8], "map": _map(), "brightness": 1.0, "saturation": 1.0, "contrast": 0.0},
    "roughness": {"value": 0.5, "map": _map(), "glossy": False},
    "metallic": {"value": 0.0, "map": _map()},
    "specular": 0.5,
    "normal": {"map": _map(), "strength": 1.0, "directx": False, "bumpMap": _map(), "bump": 0.0, "bumpDistanceMm": 1.0},
    "coat": {"weight": 0.0, "roughness": 0.03},
    "transmission": {"weight": 0.0, "ior": 1.5, "thin": False, "absorbColor": [1.0, 1.0, 1.0], "absorbCm": 0.0,
                     "dispersion": False, "abbe": 55.0, "dispersionBoost": 1.0, "dispersionAmount": 0.35},
    "sheen": {"weight": 0.0, "roughness": 0.5, "tint": [1.0, 1.0, 1.0]},
    "subsurface": {"weight": 0.0, "radiusMm": 1.0, "color": [1.0, 0.35, 0.2]},
    "emission": {"nits": 0.0, "kelvin": 6500.0, "color": [1.0, 1.0, 1.0], "map": _map(), "on": True, "dusk": False},
    "opacity": {"useAlpha": False, "map": _map(), "invert": False, "cutout": True},
    # type «Fogliame» of the editor (1.77.0): leaves, needles, petals (part "foglie") or the wood of a plant ("legno").
    # season 0 = summer … 1 = winter (every leaf gone); translucency = light through the leaf; back = the back of the
    # leaf lighter; inner = darker inside the crown; variation = every plant and leaf a little different; red = how
    # many plants turn red in autumn (the others gold)
    # type «Tessuto» of the editor (1.77.1): mode pieno = opaque cloth (the fuzz is the sheen of the Principled, sheen.*;
    # fuzzMap says where it is), sottile = a thin cloth one sees through (see = how much, edge = more opaque seen edge
    # on, light = light through); tintMap + tint = a colour laid on the parts the mask makes white
    "fabric": {"enabled": False, "mode": "pieno", "fuzzMap": _map(), "see": 0.6, "light": 0.5, "edge": 0.6,
               "tintMap": _map(), "tint": [0.6, 0.15, 0.12]},
    "foliage": {"enabled": False, "part": "foglie", "season": 0.0, "translucency": 0.5, "back": 0.3, "inner": 0.3,
                "variation": 0.3, "red": 0.5},
    # type «Interni» of the editor (1.79.0, Luca: «parallax room»): a room behind every window of a flat glass - the
    # surface split in cells of roomW × roomH (metres, along the axes of the object), each one a box depthM deep
    # seen through the glass (interior mapping); room = a picture of engine/assets/interiors; bright = its light
    # night lights: lightsOn = lit, dusk = only when the Ambiente is dark (dusk.py), power = their strength, kelvin =
    # warm or cold, share = the part of the rooms that have the light on (each room picked by its place)
    # map (Luca: «queste sono parallax credo standard ma se le carico il tuo materiale non funziona»): a room picture in
    # the usual 3×3 cross (INTERIOR_TILES) instead of the picture of engine/assets/interiors
    "interior": {"enabled": False, "room": "room_test", "roomW": 4.0, "roomH": 3.0, "depthM": 4.0, "bright": 0.4,
                 "lightsOn": False, "dusk": True, "power": 1.5, "kelvin": 3000.0, "share": 0.6, "map": _map(), "stretch": False},
    # type "Displacement" of the editor (enabled): mode true = the surface really moves, both = moves + fine bump,
    # bump = only the look of relief (no geometry, fast). Adaptive subdivision in pixels on screen or in cm (same
    # dicing for every copy: distributions). weld closes the cracks on UV seams, remesh rebuilds a bad mesh first.
    "displacement": {"enabled": False, "map": _map(), "heightCm": 1.0, "midlevel": 0.5, "detail": "media",
                     "mode": "both", "vector": _map(), "vectorScale": 1.0, "vectorMid": 0.0, "space": "pixel",
                     "edgeCm": 1.0, "maxLevel": 10, "weld": True, "remesh": False, "remeshCm": 2.0,
                     "finalOnly": False, "offscreen": True},
    "uv": {"mode": "uv", "space": "object", "blend": 0.2, "scale": 1.0, "sizeCm": 100.0, "stretch": [1.0, 1.0],
           "rotation": 0.0, "offset": [0.0, 0.0], "randomize": False,
           # centerAt: the point the texture is centred on («Centra sull'oggetto», or by itself when a picture is
           # put on): kept centred when scale or rotation change; None once the offset is moved by hand
           "centerAt": None,
           # perPiece («Centra ogni pezzo»): every separate piece of the objects centred on its own middle (the two
           # lamps of a car in one object, the lenses of a lamp): coordinates measured from the middle of each
           # piece (attributes PIECE_CENTRE / PIECE_UV on the meshes, piece_attributes)
           "perPiece": False,
           # "Rompi la ripetizione" (Randomize UV of Twinmotion): the texture shown in zones (cells of a Voronoi
           # pattern, cellRepeats repetitions wide), each shifted and turned at random, blended at the edges
           "antitile": False, "cellRepeats": 3.0, "antitileBlend": 0.25, "antitileRotate": True},
    # «Sporco» (grunge, 1.69.0): a layer of dirt over the material, projected from three sides in the world (its size
    # does not depend on the UV nor on the model's units); amount = how much of the picture is dirt, opacity = how
    # strongly it covers (1.69.4; «Sui bordi» taken away: what looked like edges were often other models meeting).
    # The picture is Simpler's own (assets/grunge/grunge.png, made by make_grunge.py) unless a mask is given.
    # paint: dirt painted by hand shows on this material (dirtpaint.py, «Dipingi lo sporco»; set by the brush)
    "grunge": {"amount": 0.0, "opacity": 1.0, "sizeCm": 50.0, "color": [0.09, 0.075, 0.06],
               "roughness": 0.3, "relief": 0.0, "randomize": True, "map": _map(), "colorMap": _map(),
               "normal": _map(), "normalStrength": 0.5, "paint": False, "seed": 0},
}
def grunge_seed_offset(seed):
    """«Seme casuale» of the dirt: a shift in metres (golden ratios: every seed lands elsewhere), None for 0."""
    s = int(seed or 0)
    if not s:
        return None
    return tuple(math.modf(s * k)[0] * 37.0 for k in (0.7548776662, 0.5698402910, 0.4142135624))


GRUNGE_FILE = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "assets", "grunge", "grunge.png")


def grunge_image():
    """The picture of the dirt of Simpler (loaded once in the project, data not colour)."""
    im = next((i for i in bpy.data.images if i.get("simpler_grunge")), None)
    if im is None or not os.path.isfile(bpy.path.abspath(im.filepath)):
        im = bpy.data.images.load(GRUNGE_FILE, check_existing=True)
        im["simpler_grunge"] = 1
    try:
        im.colorspace_settings.name = "Non-Color"
    except TypeError:
        pass
    return im


def grunge_on(p):
    g = p.get("grunge") or {}
    return (float(g.get("amount", 0)) > 0 or bool(g.get("paint"))) and float(g.get("opacity", 1.0)) > 0
NITS_PER_UNIT = 683.0        # Cycles emission strength 1 = radiance 1 W/(m²·sr) ≈ 683 cd/m² for white light


# ---------------------------------------------------------------- small helpers

# (1.77.0) «Stagione» of the type Fogliame: every leaf has its own moment (earliness from a slow noise over the plant,
# its own random and the plant's random); its phase t goes 0 → 1 as the season moves on, and walks one of two ramps,
# gold or red (which one: «Rossi d'autunno» against the plant's random). Each point: t, hue shift (turns of the colour
# wheel, applied to the leaf's own colour so its texture stays), saturation ×, value ×. From FOLIAGE_DROP the leaf
# is gone (transparent). The view (viewer.js useFoliage) gets the same tables through realtime_params.
FOLIAGE_RAMPS = {
    "gold": [(0.0, 0.0, 1.0, 1.0), (0.1, 0.0, 1.0, 1.0), (0.35, -0.12, 1.15, 1.1), (0.6, -0.155, 1.2, 1.05),
             (0.74, -0.18, 0.85, 0.75), (0.84, -0.19, 0.55, 0.5), (1.0, -0.19, 0.55, 0.5)],
    "red": [(0.0, 0.0, 1.0, 1.0), (0.1, 0.0, 1.0, 1.0), (0.33, -0.11, 1.15, 1.1), (0.5, -0.2, 1.25, 1.0),
            (0.64, -0.27, 1.2, 0.85), (0.76, -0.24, 0.8, 0.6), (0.84, -0.2, 0.5, 0.45), (1.0, -0.2, 0.5, 0.45)],
}
FOLIAGE_DROP = 0.86          # phase past which a leaf has fallen
FOLIAGE_NOISE_M = 1.2        # size of the slow noise that makes whole branches turn together (metres)
# when a leaf starts to turn: FOLIAGE_START + FOLIAGE_SPREAD × its earliness (stretched ×FOLIAGE_STRETCH around the
# middle: the randoms averaged together are close to 0.5); it walks its ramp in FOLIAGE_LIFE of the season. So 0-10%
# all green, ~25-50% yellowing, ~50-70% orange and red with the first leaves falling, ~70-90% most fallen, 100% bare
FOLIAGE_START, FOLIAGE_SPREAD, FOLIAGE_LIFE, FOLIAGE_STRETCH = 0.1, 0.5, 0.45, 2.2


# (1.79.0, Luca: «se è una vegetazione puoi aggiungere season, così posso fare un mix di colori di foglie») a leaf
# material used by a scatter with its own season per model: its season is read from the piece (instancer attribute
# PIECE_SEASON = 1 + season; 0 = the material's own) - only these materials get the extra nodes
PIECE_SEASON = "simpler_season"
PIECE_SEASON_MAT = "simpler_season_per_piece"


def season_per_piece(mats):
    """The leaf materials of models scattered with a season of their own: built again to read the season of each
    piece (once; the others are left as they are)."""
    from . import proxies
    done = 0
    for m in {x for x in mats if x is not None}:
        if m.get(PIECE_SEASON_MAT):
            continue
        p = params_of(m)
        if p is None or not foliage_on(p) or (p.get("foliage") or {}).get("part", "foglie") == "legno":
            continue
        m[PIECE_SEASON_MAT] = 1
        if m.node_tree is None:
            m.use_nodes = True
        _Builder(m, p).build()
        proxies.apply(proxies.CURRENT["px"], [m.node_tree])
        done += 1
    return done


# (1.79.0) «Interni»: the rooms are pictures rendered from outside their window (assets/interiors/make_interiors.py):
# the camera as far as the room is deep, so the back wall fills the middle INTERIOR_BACK of the picture
INTERIOR_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "assets", "interiors")
INTERIOR_BACK = 0.5
INTERIOR_FLAT = 0.7          # faces whose normal is more vertical than this (|z|): no room, only the glass
INTERIOR_BB = ("simpler_bb_x", "simpler_bb_y", "simpler_bb_z")    # on the objects: the corner the rooms start from
INTERIOR_SC = ("simpler_sc_x", "simpler_sc_y", "simpler_sc_z")    # and their scale: the rooms in metres of the scene
INTERIOR_REF = ("simpler_sc_ref_x", "simpler_sc_ref_y", "simpler_sc_ref_z")   # «Si adatta al modello»: the scale it had
INTERIOR_UP = ("simpler_up", "simpler_up_s")   # and which of their axes is up in the scene (1, 2, 3 = X, Y, Z) and its sign
INTERIOR_NIGHT_NODE = "simpler_interior_night"                     # the strength of the night lights (dusk.py)
INTERIOR_BRIGHT_NODE = "simpler_interior_bright"                   # the daylight of the room now (dusk.py)
# (Luca: «se light on è spento di notte la stanza NON deve emettere luce … room light deve diventare 0,05») the light
# of the room when the Ambiente is dark: at most this, as a very faint night glow - the real light is «Luci accese»
# (Luca, 12/11: «anche con 0,01 la luce di notte è forte, immagina una stanza in un grattacielo al buio … serve un
# equivalente 0,005»: the night exposure makes 0.05 look like a lit room)
INTERIOR_DARK_ROOM = 0.005
# (1.79.0) a room picture in the usual 3×3 cross, the tiles (column, row from the bottom): the back wall in the middle,
# the ceiling above it, the floor under it, the left and right walls at its sides (each tile touching the back wall
# with the edge that meets it); in the corners, with their transparency, the frame of the window (on the glass) and two
# rows of furniture standing in the room, the front one at INTERIOR_LAYERS[0] of the depth, the other at [1]
INTERIOR_TILES = {"back": (1, 1), "ceiling": (1, 2), "floor": (1, 0), "left": (0, 1), "right": (2, 1),
                  "frame": (0, 2), "front": (2, 0), "behind": (0, 0)}
INTERIOR_LAYERS = (1.0 / 3.0, 2.0 / 3.0)
INTERIOR_EDGE = 0.002        # the tile read this far inside its edges (no colour of the next tile)


def interior_night(it, dark=None):
    """The strength of the night lights of an «Interni» material now (0: off - by day with «Dalla sera all'alba»)."""
    if not it.get("lightsOn"):
        return 0.0
    if it.get("dusk", True):
        from . import dusk
        if not (dusk.is_dark() if dark is None else dark):
            return 0.0
    return max(0.0, float(it.get("power", 1.5)))


def interior_bright(it, dark=None):
    """The daylight look of the rooms of an «Interni» material now: «Luce della stanza» by day, at most
    INTERIOR_DARK_ROOM when the Ambiente is dark (the value of the panel stays as the user set it)."""
    b = max(0.0, float(it.get("bright", 0.4)))
    from . import dusk
    if dusk.is_dark() if dark is None else dark:
        return min(b, INTERIOR_DARK_ROOM)
    return b


def interior_pass(mats=None):
    """(1.79.0, Luca: «è giusto che si veda così in 4 sezioni?») the rooms start from the lowest corner of each object
    (its box, in its own space): the bottom of a building is a floor, its edge a wall - not the origin of the object,
    which cut a small object in four rooms. Stored on the objects that use an «Interni» material."""
    for mat in (mats if mats is not None else list(bpy.data.materials)):
        if mat is None or not mat.get(PARAMS_KEY):
            continue
        p = params_of(mat)
        if p is None or not (p.get("interior") or {}).get("enabled"):
            continue
        for ob in _users(mat):
            if ob.type != "MESH":
                continue
            lo = [min(c[i] for c in ob.bound_box) for i in range(3)]
            # (Luca: «non è vero questi sono cubi molto grandi») a cube made big with the scale: its own space is
            # still 1 m, so a room of 4 m filled more than the whole cube - the size of the object in the scene
            sc = [max(1e-6, abs(v)) for v in ob.matrix_world.to_scale()]
            # (Luca: «con fit the model spento metto le dimensioni corrette, poi lo accendo: l'immagine resta uguale a
            # quella sistemata ma posso ingrandire il modello a piacimento») «Si adatta al modello»: the scale the object
            # had when it was switched on stays the one of the rooms - as they were then; scaling it later stretches them
            if (p.get("interior") or {}).get("stretch"):
                if not all(k in ob for k in INTERIOR_REF):
                    for k, v in zip(INTERIOR_REF, sc):
                        ob[k] = float(v)
                sc = [max(1e-6, float(ob[k])) for k in INTERIOR_REF]
            else:
                for k in INTERIOR_REF:
                    if k in ob:
                        del ob[k]
            # (Luca: «su un piano poi non si vede proprio niente») a plane stood up: its own Z is horizontal in the scene,
            # its face was taken for a roof - up is the axis of the object nearest to the up of the scene (the floors
            # from its lowest side: the other end of that axis when it points down)
            m3 = ob.matrix_world.to_3x3()
            zs = [m3[2][i] / max(1e-9, m3.col[i].length) for i in range(3)]
            up = max(range(3), key=lambda i: abs(zs[i]))
            sign = 1.0 if zs[up] >= 0 else -1.0
            if sign < 0:
                lo[up] = max(c[up] for c in ob.bound_box)
            for k, v in list(zip(INTERIOR_BB, lo)) + list(zip(INTERIOR_SC, sc)) + list(zip(INTERIOR_UP, (up + 1.0, sign))):
                if abs(float(ob.get(k, 1e9)) - v) > 1e-5:
                    ob[k] = float(v)


def interior_atlas(it):
    """The Blender image of the room picture (3×3 cross) chosen in an «Interni» material, or None."""
    name = ((it or {}).get("map") or {}).get("image") or ""
    im = bpy.data.images.get(name) if name else None
    if im is not None and im.is_float and not im.get("simpler_view_srgb"):
        im["simpler_view_srgb"] = 1             # (shown as colour in the view: proxies.VIEW_SRGB)
    return im


def interior_image(room):
    """The Blender image of a room of the type «Interni» (loaded once), or None."""
    name = "Simpler Interni · " + os.path.basename(str(room or "room_test"))
    im = bpy.data.images.get(name)
    if im is not None:
        return im
    path = os.path.join(INTERIOR_DIR, os.path.basename(str(room or "room_test")) + ".jpg")
    if not os.path.isfile(path):
        return None
    im = bpy.data.images.load(path, check_existing=False)
    im.name = name
    return im


def foliage_on(p):
    f = p.get("foliage") or {}
    return bool(f.get("enabled"))


def _merge(base, patch):
    out = copy.deepcopy(base)
    for k, v in (patch or {}).items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = _merge(out[k], v)
        else:
            out[k] = copy.deepcopy(v)
    return out


def _mat(name):
    mat = bpy.data.materials.get(name or "")
    if mat is None:
        raise ApiError(tr("Materiale non trovato"))
    return mat


_SUFFIX = __import__("re").compile(r"\.\d{3}$")


def used_images(mat):
    """The pictures the material's nodes really use (a node showing a reduced copy counts with its original:
    proxies.py), its groups included."""
    used = set()
    if mat is None or mat.node_tree is None:
        return used
    for n in mat.node_tree.nodes:
        if n.type in ("TEX_IMAGE", "TEX_ENVIRONMENT") and n.image is not None:
            used.add(n.image.name)
            if n.get("simpler_orig"):
                used.add(str(n["simpler_orig"]))
        elif n.type == "GROUP" and n.node_tree is not None:
            used.update(x.image.name for x in n.node_tree.nodes if x.type == "TEX_IMAGE" and x.image is not None)
    return used


def _heal_images(mat, stored):
    """Image names in the channels that the material's own nodes no longer use: Blender renames an image that
    comes with a model or a project when the scene already has one with that name (targa.jpg -> targa.jpg.001), and
    the channels still said targa.jpg - another picture, or none. The next change rebuilt the material with the wrong
    texture, the editor and the view showed it (or "texture not available"), saving to the library copied it.
    Each such name is put back to the image the nodes really use (same name but for Blender's suffix). True if fixed."""
    if mat.node_tree is None:
        return False
    used = used_images(mat)
    if not used:
        return False
    fixed = False
    # (1.78.4) the node built for a channel knows the name the channel gave it (simpler_map): after a rename by
    # Blender that is the sure way back. Older materials: by the name, then by what the picture is for - Maxtree calls
    # every picture «Bitmaptexture.0NN» and two trees in a project renumber them: the leaf's colour channel ended on
    # another tree's normal map (fuchsia leaves in the view, the path tracing right)
    tagged = {}
    for n in mat.node_tree.nodes:
        if n.type == "TEX_IMAGE" and n.image is not None and n.get("simpler_map"):
            tagged.setdefault(str(n["simpler_map"]), set()).add(n.image.name)

    def role_fits(u, role):
        img = bpy.data.images.get(u)
        if img is None:
            return True
        try:
            cs_ok = (img.colorspace_settings.name != "Non-Color") == (role in ("color", "emission", "sheen"))
        except Exception:
            cs_ok = True
        f = (img.filepath or u).lower()
        is_normal = "normal" in f or "nrm" in f
        return cs_ok and (is_normal if role == "normal" else not is_normal)

    def walk(d, role=""):
        nonlocal fixed
        if isinstance(d, dict):
            name = d.get("image")
            if isinstance(name, str) and name and name not in used:
                cand = sorted(tagged.get(name, ()))
                if not cand:     # the same name with Blender's suffix added
                    cand = [u for u in used if _SUFFIX.sub("", u) == name]
                if not cand:
                    base = _SUFFIX.sub("", name)
                    cand = [u for u in used if _SUFFIX.sub("", u) == base]
                    if len(cand) > 1:
                        cand = [u for u in cand if role_fits(u, role)]
                if len(cand) == 1:
                    d["image"] = cand[0]
                    fixed = True
            for k, v in d.items():
                walk(v, role or k)
        elif isinstance(d, list):
            for v in d:
                walk(v, role)
    walk(stored)
    return fixed


def params_of(mat):
    raw = mat.get(PARAMS_KEY)
    if raw:
        try:
            stored = json.loads(raw)
        except ValueError:
            return None
        if _heal_images(mat, stored):
            mat[PARAMS_KEY] = json.dumps(stored)
        return _merge(DEFAULTS, stored)
    return None


def is_dispersive(mat):
    p = params_of(mat) if mat is not None else None
    return bool(p and p["transmission"]["weight"] > 0 and p["transmission"]["dispersion"] and not p["transmission"]["thin"])


def _lin(c):
    return [float(x) for x in list(c)[:3]]


def _original_image(node):
    """Image of a texture node, the original one when the node shows a reduced copy (proxies.py)."""
    name = node.get("simpler_orig")
    if name and bpy.data.images.get(name) is not None:
        return bpy.data.images[name]
    return node.image


# ---------------------------------------------------------------- reading an existing material

class _Unreadable(Exception):
    pass


def _source(sock):
    """What drives an input: None (value), or (node, output socket) after skipping reroutes."""
    if not sock.is_linked:
        return None
    link = sock.links[0]
    node, out = link.from_node, link.from_socket
    while node.type == "REROUTE" or (node.type == "GROUP" and node.node_tree is not None
                                      and node.node_tree.name in ("Simpler Glass Shadow", "Simpler Reflected Caustics")):   # (glass.py: not part of the look)
        if not node.inputs[0].is_linked:
            return None
        link = node.inputs[0].links[0]
        node, out = link.from_node, link.from_socket
    return node, out


def _read_uv(node, uv):
    """Texture coordinates of an image node into the uv settings (first image found decides)."""
    if uv.get("_read"):
        return
    uv["_read"] = True
    proj = getattr(node, "projection", "FLAT")
    vec = node.inputs.get("Vector")
    src = _source(vec) if vec is not None else None
    mapping = None
    if src and src[0].type == "MAPPING":
        mapping = src[0]
        src = _source(mapping.inputs["Vector"])
    coord = src[1].name if src else "UV"
    if proj == "BOX":
        uv["mode"] = "box"
        uv["blend"] = float(getattr(node, "projection_blend", 0.2))
    elif proj == "SPHERE":
        uv["mode"] = "sphere"
    elif proj == "TUBE":
        uv["mode"] = "cylinder"
    elif coord in ("Object", "Generated", "Position"):
        uv["mode"] = "planar"
    if coord == "Position":
        uv["space"] = "world"
    if mapping is not None and mapping.vector_type in ("POINT", "TEXTURE"):
        s = mapping.inputs["Scale"].default_value
        loc = mapping.inputs["Location"].default_value
        rot = mapping.inputs["Rotation"].default_value
        if uv["mode"] == "uv":
            uv["scale"] = float(s[0])
            uv["stretch"] = [1.0, float(s[1] / s[0]) if s[0] else 1.0]
        else:
            uv["sizeCm"] = 100.0 / float(s[0]) if s[0] else 100.0
        if uv["mode"] == "uv":
            # (the inverse of _Builder.coords: Location = -offset × scale)
            uv["offset"] = [-float(loc[0]) / float(s[0]) if s[0] else 0.0, -float(loc[1]) / float(s[1]) if s[1] else 0.0]
        else:
            uv["offset"] = [float(loc[0]), float(loc[1])]
        uv["rotation"] = math.degrees(float(rot[2]))


def _read_map(sock, uv, allow_color=False):
    """An input driven by an image (optionally through Separate Color / Invert). Returns (map dict, used invert)."""
    src = _source(sock)
    if src is None:
        return None
    node, out = src
    m = _map()
    if node.type == "INVERT":
        m["invert"] = True
        if node.inputs["Fac"].is_linked or node.inputs["Fac"].default_value < 0.99:
            raise _Unreadable()
        src = _source(node.inputs["Color"])
        if src is None:
            raise _Unreadable()
        node, out = src
    if node.type in ("SEPARATE_COLOR", "SEPRGB"):
        m["channel"] = {"Red": "R", "Green": "G", "Blue": "B", "R": "R", "G": "G", "B": "B"}.get(out.name, "")
        src = _source(node.inputs[0])
        if src is None:
            raise _Unreadable()
        node, out = src
    if node.type != "TEX_IMAGE" or node.image is None:
        raise _Unreadable()
    if out.name == "Alpha":
        m["channel"] = "A"
    im = _original_image(node)
    m["image"] = im.name
    _read_uv(node, uv)
    return m


def _image_has_alpha(name):
    """False only when the picture is known to have no alpha channel (8-bit grey, RGB: depth 8, 24, 48, 96); a picture
    that can't be read keeps the old reading."""
    img = bpy.data.images.get(str(name or ""))
    if img is None:
        return True
    try:
        img.size[0]                      # (loads the header)
        return img.depth not in (8, 24, 48, 96)
    except Exception:
        return True


def _leads_to_image(sock):
    """True when an image texture drives this input (directly, or through Separate Color / Invert / Mapping)."""
    seen = 0
    src = _source(sock)
    while src is not None and seen < 6:
        node = src[0]
        if node.type == "TEX_IMAGE":
            return node.image is not None
        if node.type not in ("SEPARATE_COLOR", "SEPRGB", "INVERT"):
            return False
        src = _source(node.inputs["Color"] if node.type == "INVERT" else node.inputs[0])
        seen += 1
    return False


# (1.78.4, Luca: «problema di opacità con plantfactory») a map called «Transparency» (PlantFactory, other plant and
# 3D programs) can be white where the surface is NOT there - the opposite of an opacity map - or (same name, other
# plants of the same program) an opacity map: which one is told by its border (map_background)
def transparency_named(image):
    """image: the name of the picture in the project (its file name is looked at too: «alpha map» → …_Transparency.png)."""
    import os
    import re

    def says(n):
        base = os.path.basename(str(n or "").replace("\\", "/")).lower()
        return bool(re.search(r"transparen|transp(\b|_|\.)", base)) and not re.search(r"opacit|alpha|opaque", base)
    img = bpy.data.images.get(str(image or ""))
    if img is not None and img.filepath:
        return says(img.filepath)
    return says(image)


_BG = {}


def map_background(image, channel=""):
    """«white» / «black»: the value of a cut-out map along its border (the border of a card is never the leaf), None
    when the border is mixed (a tiling map) or the picture can't be read. Cached by file and time."""
    import os
    img = bpy.data.images.get(str(image or ""))
    if img is None:
        return None
    try:
        path = bpy.path.abspath(img.filepath) if img.filepath else ""
        key = (path or img.name, os.path.getmtime(path) if path and os.path.isfile(path) else 0, channel or "")
        if key in _BG:
            return _BG[key]
        w, h = img.size
        if w < 4 or h < 4 or w * h > 4096 * 4096:
            return None
        import numpy as np
        px = np.empty(w * h * 4, np.float32)
        img.pixels.foreach_get(px)
        px = px.reshape(h, w, 4)
        ch = {"R": 0, "G": 1, "B": 2, "A": 3}.get(channel or "")
        band = np.concatenate([px[0], px[-1], px[:, 0], px[:, -1]])
        v = band[:, ch] if ch is not None else band[:, :3].mean(axis=1)
        mean = float(v.mean())
        res = "white" if mean > 0.85 else "black" if mean < 0.15 else None
        _BG[key] = res
        return res
    except Exception:
        return None


def fix_transparency_map(p, card=False):
    """The opacity map turned the right way: the border of a cut-out card is where the surface is NOT. A white border
    means a «transparency» map (white = no surface: read inverted), a black one an opacity map (read as it is) -
    plant programs export both under the same «Transparency» name. card: (converting to vegetation) every opacity map
    of the plant is a card; otherwise only maps named as a transparency are looked at. The user's «Inverti» stays:
    only the map's own invert changes, so the result (the two together) is the right one. True if changed."""
    o = p.get("opacity") or {}
    m = o.get("map") or {}
    if not m.get("image") or o.get("useAlpha"):
        return False
    if not card and not transparency_named(m["image"]):
        return False
    bg = map_background(m["image"], m.get("channel") or "")
    if bg is None:
        return False
    want = bg == "white"                        # (the map read inverted, in the end)
    now = bool(o.get("invert")) != bool(m.get("invert"))
    if now == want:
        return False
    m["invert"] = not bool(m.get("invert"))
    return True


def read_material(mat):
    """Channels of a material (canonical or imported). Returns (params, advanced: bool)."""
    try:
        from . import ice
        ice.strip(mat)          # (frozen water: its nodes out while it is read or changed - made again by ice.update)
        from . import ripples
        ripples.strip(mat)      # (the rings of the rain likewise: made again by ripples.update)
    except Exception:
        pass
    p = params_of(mat)
    if p is not None:
        return p, False
    p = copy.deepcopy(DEFAULTS)
    if mat is None or mat.node_tree is None:
        if mat is not None:
            p["color"]["tint"] = _lin(mat.diffuse_color)
        return p, False
    nt = mat.node_tree
    out = next((n for n in nt.nodes if n.type == "OUTPUT_MATERIAL" and n.is_active_output), None) or \
        next((n for n in nt.nodes if n.type == "OUTPUT_MATERIAL"), None)
    if out is None:
        return p, True
    src = _source(out.inputs["Surface"])
    bsdf = src[0] if src else None
    if bsdf is not None and bsdf.type != "BSDF_PRINCIPLED":
        # shaders mixed together (a Principled inside, the "unlit" scans of the glTF importer: Emission for the
        # camera, Transparent for the rest): the main one is read, the material stays "advanced"
        main = _main_shader(bsdf)
        if main is not None and main.type == "BSDF_PRINCIPLED":
            p, _adv = _read_principled(mat, out, main)
            return p, True
        p["color"]["tint"] = _lin(mat.diffuse_color)
        if main is not None:
            _read_simple_shader(p, main)
        return p, True
    if bsdf is None:
        p["color"]["tint"] = _lin(mat.diffuse_color)
        return p, True
    return _read_principled(mat, out, bsdf)


def _main_shader(node, depth=0):
    """The shader that gives a mix its look: a Principled first, else a diffuse / emission / glossy one (never the
    Transparent half of an unlit or cut-out material)."""
    if node is None or depth > 6:
        return None
    if node.type in ("MIX_SHADER", "ADD_SHADER"):
        socks = [i for i in node.inputs if i.type == "SHADER"]
        found = [_main_shader(_source(sk)[0] if _source(sk) else None, depth + 1) for sk in socks]
        found = [f for f in found if f is not None]
        for kind in ("BSDF_PRINCIPLED", "BSDF_DIFFUSE", "EMISSION", "BSDF_GLOSSY", "BSDF_SHEEN", "BSDF_TOON"):
            for f in found:
                if f.type == kind:
                    return f
        return found[0] if found else None
    if node.type in ("BSDF_TRANSPARENT", "HOLDOUT"):
        return None
    if node.type in ("BSDF_PRINCIPLED", "BSDF_DIFFUSE", "EMISSION", "BSDF_GLOSSY", "BSDF_SHEEN", "BSDF_TOON"):
        return node
    return None


def _read_simple_shader(p, node):
    """Colour (and its texture) of a Diffuse / Emission / Glossy shader. An Emission is the "unlit" material of a
    scan with its light baked in the texture: as a Simpler material it becomes that colour, matte."""
    uv = p["uv"]
    col = node.inputs.get("Color")
    if col is None:
        return
    try:
        if col.is_linked and _leads_to_image(col):
            p["color"]["tint"] = [1.0, 1.0, 1.0]
            p["color"]["map"] = _read_map(col, uv)
        elif not col.is_linked:
            p["color"]["tint"] = _lin(col.default_value)
    except (_Unreadable, KeyError, IndexError, AttributeError, TypeError, ValueError):
        pass
    if node.type in ("EMISSION", "BSDF_DIFFUSE"):
        p["roughness"]["value"] = 0.9
        p["specular"] = 0.3
    elif node.type == "BSDF_GLOSSY" and "Roughness" in node.inputs and not node.inputs["Roughness"].is_linked:
        p["roughness"]["value"] = float(node.inputs["Roughness"].default_value)
    if p["color"].get("map") is None:
        p["color"]["map"] = _map()
    uv.pop("_read", None)


def _read_principled(mat, out, bsdf):
    p = copy.deepcopy(DEFAULTS)
    uv = p["uv"]
    # every channel is read on its own: one the editor cannot read (a vertex colour, a node it does not know) makes
    # the material "advanced" but does not lose the others - converting it keeps all the maps that could be read
    # (before, a colour multiplied by the vertex colours left a white material without its texture)
    unread = []

    def channel(name, fn):
        try:
            fn()
        except (_Unreadable, KeyError, IndexError, AttributeError, TypeError, ValueError):
            unread.append(name)

    def base_color():
        bc = bsdf.inputs["Base Color"]
        s = _source(bc)
        if s is None:
            p["color"]["tint"] = _lin(bc.default_value)
            return
        node = s[0]
        if node.type in ("MIX", "MIX_RGB") and getattr(node, "blend_type", "") == "MULTIPLY":
            a, b = (node.inputs[6], node.inputs[7]) if node.type == "MIX" else (node.inputs[1], node.inputs[2])
            ia, ib = _leads_to_image(a), _leads_to_image(b)
            if ia == ib:
                raise _Unreadable()
            img_sock, col_sock = (a, b) if ia else (b, a)
            # the other factor: a colour, or the vertex colours of the model (left out: white)
            p["color"]["tint"] = [1.0, 1.0, 1.0] if col_sock.is_linked else _lin(col_sock.default_value)
            p["color"]["map"] = _read_map(img_sock, uv)
            if col_sock.is_linked:
                raise _Unreadable()          # (still "advanced": converting it leaves the vertex colours out)
        else:
            p["color"]["tint"] = [1.0, 1.0, 1.0]
            p["color"]["map"] = _read_map(bc, uv)

    def value_map(key, inp):
        def run():
            sock = bsdf.inputs[inp]
            if sock.is_linked:
                p[key]["map"] = _read_map(sock, uv)
                p[key]["value"] = 1.0
            else:
                p[key]["value"] = float(sock.default_value)
        return run

    def normal():
        ns = _source(bsdf.inputs["Normal"])
        if ns is None:
            return
        node = ns[0]
        if node.type == "BUMP":
            p["normal"]["bump"] = float(node.inputs["Strength"].default_value)
            p["normal"]["bumpDistanceMm"] = float(node.inputs["Distance"].default_value) * 1000.0
            p["normal"]["bumpMap"] = _read_map(node.inputs["Height"], uv)
            inner = _source(node.inputs["Normal"])
            node = inner[0] if inner else None
        if node is not None:
            if node.type != "NORMAL_MAP":
                raise _Unreadable()
            p["normal"]["strength"] = float(node.inputs["Strength"].default_value)
            p["normal"]["map"] = _read_map(node.inputs["Color"], uv)

    def values():
        p["specular"] = float(bsdf.inputs["Specular IOR Level"].default_value)
        p["coat"]["weight"] = float(bsdf.inputs["Coat Weight"].default_value)
        p["coat"]["roughness"] = float(bsdf.inputs["Coat Roughness"].default_value)
        p["transmission"]["weight"] = float(bsdf.inputs["Transmission Weight"].default_value)
        p["transmission"]["ior"] = float(bsdf.inputs["IOR"].default_value)
        p["transmission"]["thin"] = bool(bsdf.inputs["Thin Wall"].default_value) if "Thin Wall" in bsdf.inputs else False
        p["sheen"]["weight"] = float(bsdf.inputs["Sheen Weight"].default_value)
        p["sheen"]["roughness"] = float(bsdf.inputs["Sheen Roughness"].default_value)
        p["sheen"]["tint"] = _lin(bsdf.inputs["Sheen Tint"].default_value)
        p["subsurface"]["weight"] = float(bsdf.inputs["Subsurface Weight"].default_value)
        p["subsurface"]["radiusMm"] = float(bsdf.inputs["Subsurface Scale"].default_value) * 1000.0
        p["subsurface"]["color"] = _lin(bsdf.inputs["Subsurface Radius"].default_value)

    def emission():
        es = bsdf.inputs["Emission Strength"]
        ec = bsdf.inputs["Emission Color"]
        if not es.is_linked:
            p["emission"]["nits"] = float(es.default_value) * NITS_PER_UNIT
        if ec.is_linked:
            p["emission"]["map"] = _read_map(ec, uv)
        elif p["emission"]["nits"] > 0 or sum(ec.default_value[:3]) > 0.003:
            p["emission"]["color"] = _lin(ec.default_value)
        # (1.78.4, Luca: «cambio lo slider stagione e boom foglie bianche») a black colour with the default strength
        # (1 in Blender: every imported file) is no emission at all: read as off, not as 683 nits of black light
        # that the next change turned into a white glow
        if not ec.is_linked and not es.is_linked and sum(ec.default_value[:3]) <= 0.003:
            p["emission"]["nits"] = 0.0
        # (no emission: the colour stays white - a black one, the default of imported files, would keep it dark
        # once «Emette luce» is switched on)

    def alpha():
        al = bsdf.inputs["Alpha"]
        if not al.is_linked:
            return
        sock = al
        s = _source(al)
        # (Luca: cespugli con le foglie piene) a glTF «MASK» material: the importer of Blender links 1 - (alpha < cut-off),
        # read as the alpha of the texture (cut out). Before, the material was unreadable and the leaves came out solid
        if (s and s[0].type == "MATH" and s[0].operation == "SUBTRACT" and not s[0].inputs[0].is_linked
                and abs(s[0].inputs[0].default_value - 1.0) < 1e-6):
            t = _source(s[0].inputs[1])
            if t and t[0].type == "MATH" and t[0].operation == "LESS_THAN" and t[0].inputs[0].is_linked and not t[0].inputs[1].is_linked:
                sock = t[0].inputs[0]
                s = _source(sock)
        # the alpha of the texture times the alpha of the vertex colours (glTF): the texture's
        if s and s[0].type == "MATH" and s[0].operation == "MULTIPLY":
            a, b = s[0].inputs[0], s[0].inputs[1]
            ia, ib = _leads_to_image(a), _leads_to_image(b)
            if ia == ib:
                raise _Unreadable()
            sock, other = (a, b) if ia else (b, a)
        else:
            other = None
        m = _read_map(sock, uv)
        if m["channel"] == "A" and not _image_has_alpha(m["image"]):
            # (Luca: «i materiali hanno qualche problema», trees of OBJ files) the Alpha of a picture with no alpha
            # channel (the OBJ import of Blender links «map_d» this way) is always 1: a grey opacity map is read by its
            # grey - read as alpha it was all «surface», then turned inside out by its white border: no leaves at all.
            # The colour picture's own «alpha» likewise is no cut-out.
            if p["color"]["map"] and m["image"] == p["color"]["map"]["image"]:
                return
            m["channel"] = ""
        if m["channel"] == "A" and p["color"]["map"] and m["image"] == p["color"]["map"]["image"]:
            p["opacity"]["useAlpha"] = True
        else:
            p["opacity"]["map"] = m
            fix_transparency_map(p)
        if other is not None and other.is_linked:
            raise _Unreadable()

    def displacement():
        if not out.inputs["Displacement"].is_linked:
            return
        ds = _source(out.inputs["Displacement"])
        if ds[0].type == "DISPLACEMENT":
            d = ds[0]
            p["displacement"]["map"] = _read_map(d.inputs["Height"], uv)
            p["displacement"]["heightCm"] = float(d.inputs["Scale"].default_value) * 100.0
            p["displacement"]["midlevel"] = float(d.inputs["Midlevel"].default_value)
        elif ds[0].type == "VECTOR_DISPLACEMENT":
            d = ds[0]
            p["displacement"]["vector"] = _read_map(d.inputs["Vector"], uv, allow_color=True)
            p["displacement"]["vectorScale"] = float(d.inputs["Scale"].default_value)
            p["displacement"]["vectorMid"] = float(d.inputs["Midlevel"].default_value)
        else:
            raise _Unreadable()
        p["displacement"]["enabled"] = mat.displacement_method in ("DISPLACEMENT", "BOTH")
        p["displacement"]["mode"] = "true" if mat.displacement_method == "DISPLACEMENT" else "both"

    def volume():
        if out.inputs["Volume"].is_linked:
            raise _Unreadable()

    channel("color", base_color)
    channel("roughness", value_map("roughness", "Roughness"))
    channel("metallic", value_map("metallic", "Metallic"))
    channel("normal", normal)
    channel("values", values)
    channel("emission", emission)
    channel("opacity", alpha)
    channel("displacement", displacement)
    channel("volume", volume)
    for key in ("color", "roughness", "metallic", "emission", "opacity", "displacement"):
        if p[key].get("map") is None:
            p[key]["map"] = _map()
    for key in ("map", "bumpMap"):
        if p["normal"][key] is None:
            p["normal"][key] = _map()
    uv.pop("_read", None)
    return p, bool(unread)


# ---------------------------------------------------------------- building the canonical node tree

RELIEF_TYPES = ("attuale", "nessuno", "canaloni", "fratture", "cenge")
RELIEF_DEF = {"rtype": "attuale", "rsize": 1.0, "rdetail": 0.5, "rwhere": 0.5, "rorient": 0.0,
              "rdisp": False, "ramp": 1.0, "rfine": 0.5,
              # (1.76.58, Luca: «true displacement deve avere anche l'opzione per caricare una displacement») a map of
              # the user's own in place of the kind, a colour map of the same set, their size and turn on the walls
              "rmap": "", "rcolor": "", "rcamt": 1.0, "rmsize": 10.0, "rmrot": 0.0, "rmanti": False}
# (set in place: update_relief_values; rfine: the subdivision of the zones, _sync_displacement)
RELIEF_NUMS = ("relief", "rsize", "rdetail", "rwhere", "rorient", "thick", "ramp", "rfine", "rcamt", "rmsize", "rmrot")
RELIEF_VIEW = ("rcamt", "rmsize", "rmrot", "rwhere")   # (1.76.58: the view draws the colour map: these reach it)
RELIEF_RANGE = {"rsize": (0.25, 4.0), "rdetail": (0.0, 1.0), "rwhere": (0.0, 1.0), "rorient": (-90.0, 90.0),
                "ramp": (0.0, 2.0), "rfine": (0.0, 1.0), "rcamt": (0.0, 1.0), "rmsize": (0.5, 500.0), "rmrot": (-180.0, 180.0)}
RELIEF_MAP_HEIGHT = 0.2       # (1.76.58) a relief map from black to white: this share of its size in metres (10 m: 2 m)
# (1.76.55) «Displacement vero» of «Rilievo 3D»: the micro-triangles of the adaptive subdivision, in pixels of a 1920
# picture (relief_disp_px); at most RELIEF_DISP_LEVELS levels (the zones have a point every 2-15 m: 64 times finer)
RELIEF_DISP_LEVELS = 6
RELIEF_RW = "simpler_rw"        # (1.76.55) the part of the relief made real, per point of a terrain zone (terrain)


RELIEF_DISP_REF = 1920.0     # (the pixels of Finezza are those of a picture this wide: displacement_pass)


def relief_disp_px(fine):
    """Finezza 0 -> 8 px, 50% -> 4 px, 100% -> 2 px (of a 1920 picture: 0.5-2 m triangles on a wall 1 km away;
    1 px asked 5 GB more on a 960 picture)."""
    return 8.0 / (4.0 ** max(0.0, min(1.0, float(fine))))


def relief_params(t):
    """(1.76.53) «Rilievo 3D» of a terrain's tone: its kind and numbers, clamped, with the defaults (a terrain made
    before: «Attuale», 100%, 50%, 50%, 0° - the relief as it was). T: the size in metres (the thickness of the layers
    × Dimensione)."""
    t = t if isinstance(t, dict) else {}
    def num(k, lo, hi):
        v = t.get(k)
        return max(lo, min(hi, float(RELIEF_DEF[k] if v is None else v)))
    kind = t.get("rtype") if t.get("rtype") in RELIEF_TYPES else "attuale"
    s_ = num("rsize", 0.25, 4.0)
    return {"type": kind, "k": max(0.0, min(1.0, float(t.get("relief", 0.5) or 0.0))), "s": s_,
            "T": max(2.0, float(t.get("thick", 10.0) or 10.0)) * s_, "d": num("rdetail", 0.0, 1.0),
            "w": num("rwhere", 0.0, 1.0), "o": math.radians(num("rorient", -90.0, 90.0)),
            "disp": bool(t.get("rdisp")), "a": num("ramp", 0.0, 2.0), "f": num("rfine", 0.0, 1.0),
            "map": _relief_image(t.get("rmap")), "cmap": _relief_image(t.get("rcolor")), "ca": num("rcamt", 0.0, 1.0),
            "ms": num("rmsize", 0.5, 500.0), "mr": math.radians(num("rmrot", -180.0, 180.0)), "anti": bool(t.get("rmanti"))}


def _relief_image(name):
    """(1.76.58) A map of «Rilievo 3D» by its image name: "" when none or no longer in the project."""
    return name if isinstance(name, str) and name and bpy.data.images.get(name) is not None else ""


BLEND_LUM_M = 10.0      # (1.76.56) textures up to this size (metres) lead the border with their light parts, fully


def blend_lum_weight(p):
    """(1.76.56) How much the brightness of a material's texture leads the border blend of a terrain («Sfumatura dei
    bordi»): 1 up to BLEND_LUM_M metres, then less (a 120 m photo of a cliff: 0.08); UV-mapped: 1. Same in the view."""
    uv = (p or {}).get("uv") or {}
    if uv.get("mode", "uv") == "uv":
        return 1.0
    size = max(0.01, float(uv.get("sizeCm") or 100.0) / 100.0)
    return round(min(1.0, BLEND_LUM_M / size), 4)


class _Builder:
    def __init__(self, mat, p, layer=False, shared=None):
        self.mat, self.p = mat, p
        self.layer = layer          # (1.76.4) built into a tree that has one already: returns its surface (edge blend)
        # (1.76.56) what the layers of one tree compute alike - the terrain's tone and relief: the same land under every
        # zone - made once and shared (a terrain material was ~1000 nodes, 93% of them the tone and relief repeated in
        # each of its 5-6 layers; Blender makes each node slower the bigger the tree: 6-9 s a material, 53 s the terrain)
        self.shared = shared if shared is not None else {}
        self.nt = mat.node_tree
        self.x = -1400
        self.images = {}
        self.vector = None

    def node(self, kind, **props):
        n = self.nt.nodes.new(kind)
        for k, v in props.items():
            setattr(n, k, v)
        return n

    def link(self, a, b):
        self.nt.links.new(a, b)

    def coords(self):
        """Texture coordinates after projection, scale, rotation, offset and the random variation per object."""
        if self.vector is not None:
            return self.vector
        uv = self.p["uv"]
        tc = self.node("ShaderNodeTexCoord")
        tc.location = (-1700, 0)
        mode = uv["mode"] if uv["mode"] in UV_MODES else "uv"
        per = bool(uv.get("perPiece"))
        if mode == "uv":
            src = tc.outputs["UV"]
            if per:
                # «Centra ogni pezzo»: the UV of each separate piece measured from the middle of its own UV
                pa = self.node("ShaderNodeAttribute")
                pa.attribute_name = PIECE_UV
                pa.location = (-1900, 150)
                sub = self.node("ShaderNodeVectorMath", operation="SUBTRACT")
                self.link(tc.outputs["UV"], sub.inputs[0])
                self.link(pa.outputs["Vector"], sub.inputs[1])
                src = sub.outputs["Vector"]
            k = max(1e-4, float(uv["scale"]))
            scale = (k * float(uv["stretch"][0]), k * float(uv["stretch"][1]), 1.0)
        else:
            if per:
                # «Centra ogni pezzo»: every separate piece (each lens of a lamp, each tile...) measured from its own
                # middle, in the object's space at its real size: the same picture centred on each of them
                pa = self.node("ShaderNodeAttribute")
                pa.attribute_name = PIECE_CENTRE
                pa.location = (-2100, 150)
                sub = self.node("ShaderNodeVectorMath", operation="SUBTRACT")
                self.link(tc.outputs["Object"], sub.inputs[0])
                self.link(pa.outputs["Vector"], sub.inputs[1])
                attr = self.node("ShaderNodeAttribute")
                attr.attribute_type = "OBJECT"
                attr.attribute_name = "scale"
                attr.location = (-2100, -150)
                mul = self.node("ShaderNodeVectorMath", operation="MULTIPLY")
                self.link(sub.outputs["Vector"], mul.inputs[0])
                self.link(attr.outputs["Vector"], mul.inputs[1])
                src = mul.outputs["Vector"]
            elif uv["space"] == "world" and mode == "box":
                # Box in world space: the world position turned back by the rotation of the object (not moved, not
                # scaled). Cycles picks the face of the box from the normal in the object's own space: with the
                # plain world position a turned object (a car turned 90°, a wall) read the wrong pair of axes and the
                # texture came out smeared in the path tracing, while the view (world normal) showed it right.
                # Now projection and coordinates are both in the object's orientation, here and in the view; the
                # texture still stays put when the object moves and continues between objects turned the same way.
                geo = self.node("ShaderNodeNewGeometry")
                geo.location = (-2100, -200)
                vt = self.node("ShaderNodeVectorTransform")
                vt.vector_type = "VECTOR"
                vt.convert_from = "WORLD"
                vt.convert_to = "OBJECT"
                vt.location = (-1900, -200)
                self.link(geo.outputs["Position"], vt.inputs["Vector"])
                attr = self.node("ShaderNodeAttribute")
                attr.attribute_type = "OBJECT"
                attr.attribute_name = "scale"
                attr.location = (-1900, -400)
                mul = self.node("ShaderNodeVectorMath", operation="MULTIPLY")
                self.link(vt.outputs["Vector"], mul.inputs[0])
                self.link(attr.outputs["Vector"], mul.inputs[1])
                src = mul.outputs["Vector"]
            elif uv["space"] == "world":
                geo = self.node("ShaderNodeNewGeometry")
                geo.location = (-1700, -200)
                src = geo.outputs["Position"]
            else:
                # object space at the object's real size: object coordinates times the object's scale, so a scaled
                # floor or wall keeps "one repeat every sizeCm" (the texture still moves with the object)
                attr = self.node("ShaderNodeAttribute")
                attr.attribute_type = "OBJECT"
                attr.attribute_name = "scale"
                attr.location = (-1900, -150)
                mul = self.node("ShaderNodeVectorMath", operation="MULTIPLY")
                self.link(tc.outputs["Object"], mul.inputs[0])
                self.link(attr.outputs["Vector"], mul.inputs[1])
                src = mul.outputs["Vector"]
            k = 100.0 / max(0.1, float(uv["sizeCm"]))      # coordinates in metres: one repeat every sizeCm
            scale = (k * float(uv["stretch"][0]), k * float(uv["stretch"][1]), k)
        mp = self.node("ShaderNodeMapping")
        mp.vector_type = "POINT"
        mp.location = (-1500, 0)
        mp.inputs["Scale"].default_value = scale
        o = list(uv["offset"]) + [0.0, 0.0, 0.0]
        # (a third value, only from «Centra sull'oggetto»: up and down on walls in the projections)
        offset = (float(o[0]), float(o[1]), float(o[2]) if mode != "uv" else 0.0)
        if mode == "uv":
            # UV: the offset moves the picture on the model by that fraction of the UV square, whatever the scale -
            # as the real-time view does (three.js offset = -offset × repeat). The Mapping node adds its Location after
            # the scale: before, Cycles moved by «offset» repeats and the view by «offset × scale» - a plate placed to
            # the millimetre in the view came out shifted in the path tracing
            offset = (-offset[0] * scale[0], -offset[1] * scale[1], 0.0)
        rot = math.radians(float(uv["rotation"]))
        if uv.get("randomize"):
            info = self.node("ShaderNodeObjectInfo")
            info.location = (-1900, -300)
            loc = self.node("ShaderNodeCombineXYZ")
            for i, (axis, f) in enumerate((("X", 17.31), ("Y", 7.13))):
                m = self.node("ShaderNodeMath", operation="MULTIPLY_ADD")
                self.link(info.outputs["Random"], m.inputs[0])
                m.inputs[1].default_value = f
                m.inputs[2].default_value = offset[i]
                self.link(m.outputs[0], loc.inputs[axis])
            loc.inputs["Z"].default_value = offset[2]
            self.link(loc.outputs[0], mp.inputs["Location"])
            r = self.node("ShaderNodeCombineXYZ")
            m = self.node("ShaderNodeMath", operation="MULTIPLY_ADD")
            self.link(info.outputs["Random"], m.inputs[0])
            m.inputs[1].default_value = 2 * math.pi
            m.inputs[2].default_value = rot
            self.link(m.outputs[0], r.inputs["Z"])
            self.link(r.outputs[0], mp.inputs["Rotation"])
        else:
            mp.inputs["Location"].default_value = offset
            mp.inputs["Rotation"].default_value = (0.0, 0.0, rot)
        self.link(src, mp.inputs["Vector"])
        self.vector = mp.outputs["Vector"]
        return self.vector

    def _antitile(self):
        """Two layers of zones (Voronoi cells, cellRepeats repetitions wide), each zone showing the texture moved and
        turned at random. The second layer has its cells elsewhere; it shows near the edges of the first one, so
        the seams of a layer are covered by the other and the plain repeating texture never shows.
        Returns (b1, b1 shift-only, b2, b2 shift-only, mask: 1 = first layer)."""
        if getattr(self, "_at", None) is not None:
            return self._at
        uv = self.p["uv"]
        a = self.coords()
        dim = "2D" if uv["mode"] == "uv" else "3D"
        cell = max(0.5, float(uv.get("cellRepeats", 3.0)))
        rotate = uv.get("antitileRotate", True)

        def layer(vec, seed_shift):
            src = vec
            if seed_shift:
                off = self.node("ShaderNodeVectorMath", operation="ADD")      # cells of the second layer elsewhere
                self.link(vec, off.inputs[0])
                off.inputs[1].default_value = (cell * 0.5 + 13.7, cell * 0.5 + 5.3, 3.1)
                src = off.outputs["Vector"]
            vc = self.node("ShaderNodeTexVoronoi")
            vc.voronoi_dimensions = dim
            vc.feature = "F1"
            vc.inputs["Scale"].default_value = 1.0 / cell
            vc.inputs["Randomness"].default_value = 1.0
            self.link(src, vc.inputs["Vector"])
            shift = self.node("ShaderNodeVectorMath", operation="SCALE")
            self.link(vc.outputs["Color"], shift.inputs[0])
            shift.inputs["Scale"].default_value = 7.31
            moved = self.node("ShaderNodeVectorMath", operation="ADD")        # shift only (normal maps)
            self.link(vec, moved.inputs[0])
            self.link(shift.outputs[0], moved.inputs[1])
            if not rotate:
                return moved.outputs["Vector"], moved.outputs["Vector"], src
            sep = self.node("ShaderNodeSeparateColor")
            self.link(vc.outputs["Color"], sep.inputs[0])
            ang = self.node("ShaderNodeMath", operation="MULTIPLY")
            self.link(sep.outputs[0], ang.inputs[0])
            ang.inputs[1].default_value = 2 * math.pi
            rz = self.node("ShaderNodeCombineXYZ")
            self.link(ang.outputs[0], rz.inputs["Z"])
            mp = self.node("ShaderNodeMapping")
            mp.vector_type = "POINT"
            self.link(vec, mp.inputs["Vector"])
            self.link(shift.outputs[0], mp.inputs["Location"])
            self.link(rz.outputs[0], mp.inputs["Rotation"])
            return mp.outputs["Vector"], moved.outputs["Vector"], src

        b1, b1n, src1 = layer(a, False)
        b2, b2n, _ = layer(a, True)
        # how far from the edge of its zone of the first layer (0 at the edge, about 0.5 at the centre, in cells)
        ve = self.node("ShaderNodeTexVoronoi")
        ve.voronoi_dimensions = dim
        ve.feature = "DISTANCE_TO_EDGE"
        ve.inputs["Scale"].default_value = 1.0 / cell
        ve.inputs["Randomness"].default_value = 1.0
        self.link(src1, ve.inputs["Vector"])
        w = max(0.02, min(0.5, float(uv.get("antitileBlend", 0.25)))) * 0.4
        mask = self.node("ShaderNodeMapRange")
        mask.interpolation_type = "SMOOTHSTEP"
        self.link(ve.outputs["Distance"], mask.inputs["Value"])
        mask.inputs["From Min"].default_value = 0.0
        mask.inputs["From Max"].default_value = w
        self._at = (b1, b1n, b2, b2n, mask.outputs["Result"])
        return self._at

    class _Mixed:
        """Two image samples blended by the zone mask: used like an image node (outputs Color and Alpha)."""
        def __init__(self, color, alpha):
            self.outputs = {"Color": color, "Alpha": alpha}

    def image(self, name, color, normal=False, scale=1.0):
        """Image texture node (one per image and scale), with the right colour space and projection. scale (1.75.60):
        the coordinates of the material divided by it - the map that many times bigger (without «Rompi la
        ripetizione» for that map: a bigger map is already the cure for the repetition)."""
        scale = 1.0 if abs(scale - 1.0) < 1e-4 else round(float(scale), 4)
        key = (name, bool(color), bool(normal)) if scale == 1.0 else (name, bool(color), bool(normal), scale)
        if key in self.images:
            return self.images[key]
        im = bpy.data.images.get(name)
        if im is None:
            return None
        try:
            want = "sRGB" if color else "Non-Color"
            if im.colorspace_settings.name != want and not im.get("simpler_proxy"):
                # the same picture as colour in one map and as data in another (a copied map, the same file loaded
                # twice): a colour space is one per image, so the other use gets its own copy instead of spoiling this one
                if any(k[0] == name and k[1] != bool(color) for k in self.images) or _used_elsewhere(im, self.nt):
                    im = _colorspace_variant(im, want)
                else:
                    im.colorspace_settings.name = want
        except TypeError:
            pass
        n = self.node("ShaderNodeTexImage")
        n.image = im
        n["simpler_map"] = name                  # (1.78.4: the name the channels give it - _heal_images)
        n.location = (-1200, 300 - 280 * len(self.images))
        n.interpolation = "Linear"
        mode = self.p["uv"]["mode"]
        n.projection = {"box": "BOX", "sphere": "SPHERE", "cylinder": "TUBE"}.get(mode, "FLAT")
        if mode == "box":
            n.projection_blend = max(0.0, min(1.0, float(self.p["uv"]["blend"])))
        if scale != 1.0:
            sv = self.node("ShaderNodeVectorMath", operation="SCALE")
            sv.inputs["Scale"].default_value = 1.0 / scale
            self.link(self.coords(), sv.inputs[0])
            self.link(sv.outputs["Vector"], n.inputs["Vector"])
            self.images[key] = n
            return n
        if not self.p["uv"].get("antitile"):
            self.link(self.coords(), n.inputs["Vector"])
        if self.p["uv"].get("antitile"):
            b, bn, b2, b2n, mask = self._antitile()
            self.link(b2n if normal else b2, n.inputs["Vector"])      # the second layer (near the zone edges)
            n2 = self.node("ShaderNodeTexImage")
            n2.image = n.image
            n2.interpolation = n.interpolation
            n2.projection = n.projection
            n2.projection_blend = n.projection_blend
            n2.location = (n.location.x, n.location.y - 140)
            self.link(bn if normal else b, n2.inputs["Vector"])
            mc = self.node("ShaderNodeMix", data_type="RGBA")
            self.link(mask, mc.inputs["Factor"])
            self.link(n.outputs["Color"], mc.inputs[6])
            self.link(n2.outputs["Color"], mc.inputs[7])
            ma = self.node("ShaderNodeMix", data_type="FLOAT")
            self.link(mask, ma.inputs["Factor"])
            self.link(n.outputs["Alpha"], ma.inputs["A"])
            self.link(n2.outputs["Alpha"], ma.inputs["B"])
            mixed = self._Mixed(mc.outputs[2], ma.outputs["Result"])
            self.images[key] = mixed
            return mixed
        self.images[key] = n
        return n

    def scalar(self, m):
        """Grey value of a map (a channel, or the luminance), inverted if asked. None when there is no map."""
        if not m or not m.get("image"):
            return None
        n = self.image(m["image"], color=False, scale=map_scale(m))
        if n is None:
            return None
        ch = m.get("channel") or ""
        if ch == "A":
            out = n.outputs["Alpha"]
        elif ch in ("R", "G", "B"):
            sep = self.node("ShaderNodeSeparateColor")
            self.link(n.outputs["Color"], sep.inputs[0])
            out = sep.outputs[{"R": 0, "G": 1, "B": 2}[ch]]
        else:
            out = n.outputs["Color"]
        if m.get("invert"):
            inv = self.node("ShaderNodeMath", operation="SUBTRACT")
            inv.inputs[0].default_value = 1.0
            self.link(out, inv.inputs[1])
            out = inv.outputs[0]
        return out

    def mixed(self, value, m):
        """value, or value blended with a map by the map's strength (1 = the map alone)."""
        s = self.scalar(m)
        if s is None:
            return value
        mix = self.node("ShaderNodeMix", data_type="FLOAT")
        mix.inputs["Factor"].default_value = max(0.0, min(1.0, float(m.get("strength", 1.0))))
        mix.inputs["A"].default_value = value
        self.link(s, mix.inputs["B"])
        return mix.outputs["Result"]

    def put(self, sock, val):
        if isinstance(val, bpy.types.NodeSocket):
            self.link(val, sock)
        elif hasattr(sock.default_value, "__len__") and not isinstance(val, (int, float)):
            sock.default_value = (*val[:3], 1.0)[:len(sock.default_value)]
        else:
            sock.default_value = val

    # ---- «Sporco» (grunge)
    def _grunge_vector(self):
        """Position in the WORLD in metres (1.69.1: in the object's own coordinates a model made in inches or
        millimetres - the cathedral's FBX - had its dirt 40 times too small, a uniform grain), shifted at random per
        object (by its place) when asked, at the size of the dirt."""
        if getattr(self, "_gvec", None) is not None:
            return self._gvec
        g = self.p["grunge"]
        geo = self.node("ShaderNodeNewGeometry")
        geo.location = (-1900, -900)
        self._ggeo = geo
        v = geo.outputs["Position"]
        if g.get("randomize", True):
            # shift per object from its place: fract(location × (0.1031, 0.1030, 0.0973)) × 37 m - the same formula as
            # the real-time view (useGrunge), so the stains are in the same places in both (1.69.3)
            oi = self.node("ShaderNodeObjectInfo")
            mu = self.node("ShaderNodeVectorMath", operation="MULTIPLY")
            mu.inputs[1].default_value = (0.1031, 0.1030, 0.0973)
            self.link(oi.outputs["Location"], mu.inputs[0])
            fr = self.node("ShaderNodeVectorMath", operation="FRACTION")
            self.link(mu.outputs["Vector"], fr.inputs[0])
            sc = self.node("ShaderNodeVectorMath", operation="SCALE")
            sc.inputs["Scale"].default_value = 37.0
            self.link(fr.outputs["Vector"], sc.inputs[0])
            add = self.node("ShaderNodeVectorMath", operation="ADD")
            self.link(v, add.inputs[0])
            self.link(sc.outputs["Vector"], add.inputs[1])
            v = add.outputs["Vector"]
        off = grunge_seed_offset(g.get("seed", 0))
        if off is not None:
            # «Seme casuale» (1.71.0): the whole picture of the dirt shifted to another place - the same in the view
            sd = self.node("ShaderNodeVectorMath", operation="ADD")
            sd.inputs[1].default_value = off
            self.link(v, sd.inputs[0])
            v = sd.outputs["Vector"]
        k = self.node("ShaderNodeVectorMath", operation="SCALE")
        k.inputs["Scale"].default_value = 100.0 / max(0.1, float(g.get("sizeCm", 50.0)))
        self.link(v, k.inputs[0])
        sep = self.node("ShaderNodeSeparateXYZ")
        self.link(k.outputs["Vector"], sep.inputs[0])
        planes = []
        for a_, b_ in ((1, 2), (0, 2), (0, 1)):            # seen along X, Y, Z
            c = self.node("ShaderNodeCombineXYZ")
            self.link(sep.outputs[a_], c.inputs[0])
            self.link(sep.outputs[b_], c.inputs[1])
            planes.append(c.outputs[0])
        # weights of the three projections: |world normal|^4, normalised
        ab = self.node("ShaderNodeVectorMath", operation="ABSOLUTE")
        self.link(geo.outputs["Normal"], ab.inputs[0])
        sq = self.node("ShaderNodeVectorMath", operation="MULTIPLY")
        self.link(ab.outputs["Vector"], sq.inputs[0]); self.link(ab.outputs["Vector"], sq.inputs[1])
        q4 = self.node("ShaderNodeVectorMath", operation="MULTIPLY")
        self.link(sq.outputs["Vector"], q4.inputs[0]); self.link(sq.outputs["Vector"], q4.inputs[1])
        ws = self.node("ShaderNodeSeparateXYZ")
        self.link(q4.outputs["Vector"], ws.inputs[0])
        s1 = self.node("ShaderNodeMath", operation="ADD")
        self.link(ws.outputs[0], s1.inputs[0]); self.link(ws.outputs[1], s1.inputs[1])
        s2 = self.node("ShaderNodeMath", operation="ADD")
        self.link(s1.outputs[0], s2.inputs[0]); self.link(ws.outputs[2], s2.inputs[1])
        s3 = self.node("ShaderNodeMath", operation="MAXIMUM")
        self.link(s2.outputs[0], s3.inputs[0]); s3.inputs[1].default_value = 1e-5
        weights = []
        for i in range(3):
            d = self.node("ShaderNodeMath", operation="DIVIDE")
            self.link(ws.outputs[i], d.inputs[0]); self.link(s3.outputs[0], d.inputs[1])
            weights.append(d.outputs[0])
        self._gvec = (planes, weights)
        return self._gvec

    def _grunge_tex(self, im, color):
        """The picture projected from the three sides of the world, blended by the normal: a Color-like socket."""
        planes, weights = self._grunge_vector()
        acc = None
        for vec, w in zip(planes, weights):
            n = self.node("ShaderNodeTexImage")
            n.image = im
            n.interpolation = "Linear"
            n.extension = "REPEAT"
            self.link(vec, n.inputs["Vector"])
            sc = self.node("ShaderNodeVectorMath", operation="SCALE")
            self.link(n.outputs["Color"], sc.inputs[0])
            self.link(w, sc.inputs["Scale"])
            if acc is None:
                acc = sc.outputs["Vector"]
            else:
                add = self.node("ShaderNodeVectorMath", operation="ADD")
                self.link(acc, add.inputs[0]); self.link(sc.outputs["Vector"], add.inputs[1])
                acc = add.outputs["Vector"]
        return acc

    def grunge(self):
        """The mask of the dirt (0 = clean, 1 = dirty), or None when it is off."""
        if not grunge_on(self.p):
            return None
        g = self.p["grunge"]
        custom = bpy.data.images.get(g["map"].get("image") or "") if g["map"].get("image") else None
        im = custom or grunge_image()
        if custom is not None:
            try:
                custom.colorspace_settings.name = "Non-Color"
            except TypeError:
                pass
        t = self._grunge_tex(im, False)
        lum = self.node("ShaderNodeSeparateXYZ")           # (a grey picture: its first channel)
        self.link(t, lum.inputs[0])
        val = lum.outputs[0]
        if custom is not None and g["map"].get("invert"):
            inv = self.node("ShaderNodeMath", operation="SUBTRACT")
            inv.inputs[0].default_value = 1.0
            self.link(val, inv.inputs[1])
            val = inv.outputs[0]
        amount = max(0.0, float(g.get("amount", 0)))
        m = self.node("ShaderNodeMath", operation="MULTIPLY", use_clamp=True)
        self.link(val, m.inputs[0])
        m.inputs[1].default_value = amount * 2.0      # (50% = the picture as it is, 100% = twice as dirty)
        total = m.outputs[0]
        if g.get("paint"):
            # the dirt painted by hand (dirtpaint.py): its three maps, weighted as the picture (normalised |N|^4)
            from . import dirtpaint
            gn = self.node("ShaderNodeGroup")
            gn.node_tree = dirtpaint.group()
            self.link(self._ggeo.outputs["Position"], gn.inputs["Position"])
            planes, weights = self._gvec
            wv = self.node("ShaderNodeCombineXYZ")
            for i, w in enumerate(weights):
                self.link(w, wv.inputs[i])
            self.link(wv.outputs[0], gn.inputs["Weights"])
            add = self.node("ShaderNodeMath", operation="ADD", use_clamp=True)
            self.link(total, add.inputs[0])
            self.link(gn.outputs["Dirt"], add.inputs[1])
            total = add.outputs[0]
        # opacity: how strongly the dirt covers the material (1% = barely a veil)
        o = self.node("ShaderNodeMath", operation="MULTIPLY", use_clamp=True)
        self.link(total, o.inputs[0])
        o.inputs[1].default_value = max(0.0, min(1.0, float(g.get("opacity", 1.0))))
        return o.outputs[0]

    def grunge_color(self, base, mask):
        g = self.p["grunge"]
        dirt = [max(0.0, min(1.0, float(v))) for v in g.get("color", [0.09, 0.075, 0.06])[:3]]
        dsock = None
        cm = bpy.data.images.get(g["colorMap"].get("image") or "") if g["colorMap"].get("image") else None
        if cm is not None:
            try:
                cm.colorspace_settings.name = "sRGB"
            except TypeError:
                pass
            t = self._grunge_tex(cm, True)
            mul = self.node("ShaderNodeMix", data_type="RGBA", blend_type="MULTIPLY")
            mul.inputs["Factor"].default_value = 1.0
            self.link(t, mul.inputs[6])
            mul.inputs[7].default_value = (*dirt, 1.0)
            dsock = mul.outputs[2]
        mix = self.node("ShaderNodeMix", data_type="RGBA", blend_type="MIX")
        self.link(mask, mix.inputs["Factor"])
        self.put(mix.inputs[6], base)
        if dsock is not None:
            self.link(dsock, mix.inputs[7])
        else:
            mix.inputs[7].default_value = (*dirt, 1.0)
        return mix.outputs[2]

    def grunge_rough(self, rough, mask):
        add = float(self.p["grunge"].get("roughness", 0.3))
        if abs(add) < 1e-4:
            return rough
        ma = self.node("ShaderNodeMath", operation="MULTIPLY_ADD", use_clamp=True)
        self.link(mask, ma.inputs[0])
        ma.inputs[1].default_value = add
        self.put(ma.inputs[2], rough)
        return ma.outputs[0]

    def grunge_normal(self, nrm, mask):
        g = self.p["grunge"]
        nim = bpy.data.images.get(g["normal"].get("image") or "") if g["normal"].get("image") else None
        if nim is not None:
            try:
                nim.colorspace_settings.name = "Non-Color"
            except TypeError:
                pass
            t = self._grunge_tex(nim, False)
            nm = self.node("ShaderNodeNormalMap")
            nm.inputs["Strength"].default_value = max(0.0, float(g.get("normalStrength", 0.5)))
            self.link(t, nm.inputs["Color"])
            if nrm is None:
                geo = self.node("ShaderNodeNewGeometry")
                nrm = geo.outputs["Normal"]
            mv = self.node("ShaderNodeMix", data_type="VECTOR")
            self.link(mask, mv.inputs["Factor"])
            self.link(nrm, mv.inputs[4])
            self.link(nm.outputs["Normal"], mv.inputs[5])
            nn = self.node("ShaderNodeVectorMath", operation="NORMALIZE")
            self.link(mv.outputs[1], nn.inputs[0])
            nrm = nn.outputs["Vector"]
        relief = float(g.get("relief", 0.0))
        if relief > 0:
            bump = self.node("ShaderNodeBump")
            bump.inputs["Strength"].default_value = max(0.0, min(1.0, relief))
            bump.inputs["Distance"].default_value = 0.002
            self.link(mask, bump.inputs["Height"])
            if nrm is not None:
                self.link(nrm, bump.inputs["Normal"])
            nrm = bump.outputs["Normal"]
        return nrm

    # ---- «Variazione su grande scala» (1.76.6): big surfaces (terrains, kilometres of ground) where a texture of a
    # metre or two repeats into a flat colour from afar. macro: a large picture (Poly Haven aerial textures: 15-90 m)
    # laid over the detail - its patterns (rock outcrops in a meadow, patches of scree) multiply the detail's colour
    # (strength), and with «colour» its own colour takes over, the detail keeping its grain; tone: a slow variation of
    # brightness and hue over tens of metres, with no picture. In params only when used (no change to the others).
    def _macro_on(self):
        m = self.p.get("macro") or {}
        return bool(((m.get("map") or {}).get("image") and float(m.get("strength", 0)) > 0) or float(m.get("tone", 0)) > 0)

    def _macro_sub(self):
        if getattr(self, "_msub", None) is None:
            m = self.p["macro"]
            q = json.loads(json.dumps(self.p))
            q.pop("macro", None); q.pop("blend", None)
            q["uv"]["sizeCm"] = max(10.0, float(m.get("sizeCm", 2000.0)))
            q["uv"]["randomize"] = False
            self._msub = _Builder(self.mat, q, layer=True, shared=self.shared)
        return self._msub

    def _const_rgb(self, v):
        n = self.node("ShaderNodeRGB")
        n.outputs[0].default_value = (float(v[0]), float(v[1]), float(v[2]), 1.0)
        return n.outputs[0]

    def macro_color(self, src):
        m = self.p["macro"]
        if isinstance(src, (list, tuple)):
            src = self._const_rgb(src)
        img = None
        if (m.get("map") or {}).get("image") and float(m.get("strength", 0)) > 0:
            img = self._macro_sub().image(m["map"]["image"], color=True)
        if img is not None:
            M = img.outputs["Color"]
            mm = [max(1e-3, float(v)) for v in (m.get("mean") or [0.5, 0.5, 0.5])[:3]]
            dm = [max(1e-3, float(v)) for v in (m.get("detailMean") or mm)[:3]]
            ratio = self.node("ShaderNodeVectorMath", operation="DIVIDE")       # macro / its mean: the pattern
            self.link(M, ratio.inputs[0])
            ratio.inputs[1].default_value = mm
            pat = self.node("ShaderNodeMix", data_type="RGBA", blend_type="MIX")
            pat.inputs["Factor"].default_value = max(0.0, min(1.0, float(m.get("strength", 0.6))))
            pat.inputs[6].default_value = (1.0, 1.0, 1.0, 1.0)
            self.link(ratio.outputs[0], pat.inputs[7])
            p_ = self.node("ShaderNodeMix", data_type="RGBA", blend_type="MULTIPLY")
            p_.inputs["Factor"].default_value = 1.0
            self.link(src, p_.inputs[6]); self.link(pat.outputs[2], p_.inputs[7])
            out = p_.outputs[2]
            c = max(0.0, min(1.0, float(m.get("colour", 0.0))))
            if c > 0:
                # the macro's colour, the detail's grain (detail / its mean)
                grain = self.node("ShaderNodeVectorMath", operation="DIVIDE")
                self.link(src, grain.inputs[0])
                grain.inputs[1].default_value = dm
                mc = self.node("ShaderNodeVectorMath", operation="MULTIPLY")
                self.link(M, mc.inputs[0]); self.link(grain.outputs[0], mc.inputs[1])
                mx = self.node("ShaderNodeMix", data_type="RGBA", blend_type="MIX")
                mx.inputs["Factor"].default_value = c
                self.link(out, mx.inputs[6]); self.link(mc.outputs[0], mx.inputs[7])
                out = mx.outputs[2]
            src = out
        t = float(m.get("tone", 0.0))
        if t > 0:
            geo = self.node("ShaderNodeNewGeometry")
            nz = self.node("ShaderNodeTexNoise")
            nz.inputs["Scale"].default_value = 1.0 / max(1.0, float(m.get("toneSizeM", 30.0)))
            nz.inputs["Detail"].default_value = 3.0
            nz.inputs["Roughness"].default_value = 0.5
            self.link(geo.outputs["Position"], nz.inputs["Vector"])
            sep = self.node("ShaderNodeSeparateColor")
            self.link(nz.outputs["Color"], sep.inputs[0])
            hsv = self.node("ShaderNodeHueSaturation")
            self.link(src, hsv.inputs["Color"])
            hue = self._math("MULTIPLY_ADD", sep.outputs[1], 0.08 * t, 0.5 - 0.04 * t)
            val = self._math("MULTIPLY_ADD", nz.outputs["Fac"], 1.4 * t, 1.0 - 0.7 * t)
            sat = self._math("MULTIPLY_ADD", sep.outputs[2], 0.6 * t, 1.0 - 0.3 * t)
            self.link(hue, hsv.inputs["Hue"]); self.link(val, hsv.inputs["Value"]); self.link(sat, hsv.inputs["Saturation"])
            src = hsv.outputs["Color"]
        return src

    def macro_normal(self, out):
        m = self.p["macro"]
        if not (m.get("normal") or {}).get("image") or float(m.get("strength", 0)) <= 0:
            return out
        img = self._macro_sub().image(m["normal"]["image"], color=False, normal=True)
        if img is None:
            return out
        nm = self.node("ShaderNodeNormalMap")
        nm.inputs["Strength"].default_value = max(0.0, min(1.0, float(m.get("strength", 0.6))))
        self.link(img.outputs["Color"], nm.inputs["Color"])
        if out is None:
            return nm.outputs["Normal"]
        mix = self.node("ShaderNodeMix", data_type="VECTOR")
        mix.inputs[0].default_value = 0.5
        self.link(out, mix.inputs[4]); self.link(nm.outputs["Normal"], mix.inputs[5])
        nrm = self.node("ShaderNodeVectorMath", operation="NORMALIZE")
        self.link(mix.outputs[1], nrm.inputs[0])
        return nrm.outputs["Vector"]

    def base_color(self):
        src = self._base_color()
        if self._macro_on():
            src = self.macro_color(src)
        if self._relief_on() and relief_params(self.p["tone"])["cmap"]:
            src = self.relief_color(src)
        if self._tone_on():
            src = self.tone_color(src)
        return src

    # ---- «Colori dal terreno» (1.76.14): the colour of a terrain zone guided by the shape of the land, as it is in
    # nature - crests lighter and worn, gullies darker; darker and richer where water gathers; bands that follow
    # the layers of the rock on its walls; dark streaks running down the steep faces. The data per point of the
    # mesh: the UV maps TONE (terrain._tone_data: crest 0..1 and water + 2, layer coordinate); a mesh without: nothing.
    # Same formulas in the view (viewer.js useTone; its noises have the same character, not the same values).
    TONE = ("simpler_tc1", "simpler_tc2")

    def _tone_on(self):
        """The colours from the land (1.76.41: the relief of the rock is not one of them - see _relief_on)."""
        t = self.p.get("tone")
        return isinstance(t, dict) and bool(t.get("on", True)) and any(float(t.get(k, 0)) > 0 for k in ("streaks", "bands", "ridges", "wet"))

    def _relief_on(self):
        """(1.76.41, Luca: «dovrebbe essere in Forma e roccia») the relief of the rock, with or without the colours."""
        t = self.p.get("tone")
        return isinstance(t, dict) and float(t.get("relief", 0)) > 0 and relief_params(t)["type"] != "nessuno"

    def _wall_groups(self, geo, conv, across_m, tall_m):
        """(1.76.43, Luca: the walls «a pettine» - the same creases and streaks side by side over the whole wall) where
        the creases and streaks of a wall go: in groups (a noise <across_m> wide, <tall_m> tall: patches of wall with
        them, smooth slabs without), many in the gullies, few on the crests (conv: crest 1, gully 0). 0..1."""
        pos = self.node("ShaderNodeSeparateXYZ")
        self.link(geo.outputs["Position"], pos.inputs[0])
        v = self.node("ShaderNodeCombineXYZ")
        self.link(self._math("MULTIPLY", pos.outputs[0], 1.0 / across_m), v.inputs["X"])
        self.link(self._math("MULTIPLY", pos.outputs[1], 1.0 / across_m), v.inputs["Y"])
        self.link(self._math("MULTIPLY", pos.outputs[2], 1.0 / tall_m), v.inputs["Z"])
        nz_ = self.node("ShaderNodeTexNoise")
        self.link(v.outputs[0], nz_.inputs["Vector"])
        nz_.inputs["Scale"].default_value = 1.0
        nz_.inputs["Detail"].default_value = 1.0
        g = self.node("ShaderNodeMapRange")
        g.interpolation_type = "SMOOTHSTEP"
        g.clamp = True
        self.link(nz_.outputs["Fac"], g.inputs["Value"])
        g.inputs["From Min"].default_value = 0.44
        g.inputs["From Max"].default_value = 0.6
        gl = self.node("ShaderNodeMapRange")
        gl.clamp = True
        self.link(conv, gl.inputs["Value"])
        gl.inputs["From Min"].default_value = 0.7
        gl.inputs["From Max"].default_value = 0.3
        gl.inputs["To Min"].default_value = 0.2
        gl.inputs["To Max"].default_value = 1.0
        return self._math("MULTIPLY", g.outputs["Result"], gl.outputs["Result"])

    def tone_color(self, src):
        t = self.p["tone"]
        if isinstance(src, (list, tuple)):
            src = self._const_rgb(src)
        ks, kb, kr, kw = (max(0.0, min(1.0, float(t.get(k, 0)))) for k in ("streaks", "bands", "ridges", "wet"))
        key = ("tone_color", ks, kb, kr, kw)
        if key in self.shared:
            out = self.node("ShaderNodeVectorMath", operation="MULTIPLY")
            self.link(src, out.inputs[0])
            self.link(self.shared[key], out.inputs[1])
            return out.outputs[0]
        seps = []
        for nm in self.TONE:
            attr = self.node("ShaderNodeAttribute")
            attr.attribute_type = "GEOMETRY"
            attr.attribute_name = nm
            sp_ = self.node("ShaderNodeSeparateXYZ")
            self.link(attr.outputs["Vector"], sp_.inputs[0])
            seps.append(sp_)
        conv, wraw, u = seps[0].outputs[0], seps[0].outputs[1], seps[1].outputs[0]
        has = self._math("GREATER_THAN", wraw, 1.5)                   # (water stored + 2)
        wet = self._math("MAXIMUM", self._math("SUBTRACT", wraw, 2.0), 0.0)
        geo = self.node("ShaderNodeNewGeometry")
        nsep = self.node("ShaderNodeSeparateXYZ")
        self.link(geo.outputs["Normal"], nsep.inputs[0])
        steep_r = self.node("ShaderNodeMapRange")                   # 1 on walls (nz < 0.55), 0 below 33°
        steep_r.clamp = True
        self.link(nsep.outputs[2], steep_r.inputs["Value"])
        steep_r.inputs["From Min"].default_value = 0.85
        steep_r.inputs["From Max"].default_value = 0.55
        steep = steep_r.outputs["Result"]
        # brightness: crests and gullies, water
        val = self._math("MULTIPLY_ADD", self._math("SUBTRACT", conv, 0.5), 1.2 * kr, 1.0)
        val = self._math("MULTIPLY", val, self._math("MULTIPLY_ADD", wet, -0.45 * kw, 1.0))
        warm = None
        if kb > 0:
            # the layers: a slow random per layer (warm and light / cool and dark), and thin bands inside
            n1 = self.node("ShaderNodeTexNoise", noise_dimensions="1D")
            self.link(u, n1.inputs["W"])
            n1.inputs["Scale"].default_value = 1.0
            n1.inputs["Detail"].default_value = 1.0
            n2 = self.node("ShaderNodeTexNoise", noise_dimensions="1D")
            self.link(self._math("MULTIPLY", u, 5.0), n2.inputs["W"])
            n2.inputs["Scale"].default_value = 1.0
            n2.inputs["Detail"].default_value = 0.0
            b1 = self._math("MULTIPLY", self._math("SUBTRACT", n1.outputs["Fac"], 0.5), 2.0)
            b2 = self._math("MULTIPLY", self._math("SUBTRACT", n2.outputs["Fac"], 0.5), 2.0)
            warm = self._math("MULTIPLY", self._math("MULTIPLY", b1, steep), 0.6 * kb)
            val = self._math("MULTIPLY", val, self._math("MULTIPLY_ADD", self._math("MULTIPLY", b2, steep), 0.2 * kb, 1.0))
        if ks > 0:
            # streaks down the walls: a noise long in height, thin across - seen from the side the wall faces
            pos = self.node("ShaderNodeSeparateXYZ")
            self.link(geo.outputs["Position"], pos.inputs[0])
            ax = self._math("POWER", self._math("ABSOLUTE", nsep.outputs[0]), 4.0)     # (sharp: no cross-hatch)
            ay = self._math("POWER", self._math("ABSOLUTE", nsep.outputs[1]), 4.0)
            wx = self._math("DIVIDE", ax, self._math("ADD", self._math("ADD", ax, ay), 1e-4))

            def streak(across):
                v = self.node("ShaderNodeCombineXYZ")
                self.link(self._math("MULTIPLY", across, 1.0 / 0.8), v.inputs["X"])
                self.link(self._math("MULTIPLY", pos.outputs[2], 1.0 / 9.0), v.inputs["Y"])
                nz_ = self.node("ShaderNodeTexNoise")
                self.link(v.outputs[0], nz_.inputs["Vector"])
                nz_.inputs["Scale"].default_value = 1.0
                nz_.inputs["Detail"].default_value = 2.0
                return nz_.outputs["Fac"]
            sn = self._math("ADD", self._math("MULTIPLY", streak(pos.outputs[1]), wx),
                            self._math("MULTIPLY", streak(pos.outputs[0]), self._math("SUBTRACT", 1.0, wx)))
            sm = self.node("ShaderNodeMapRange")
            sm.clamp = True
            self.link(sn, sm.inputs["Value"])
            sm.inputs["From Min"].default_value = 0.52
            sm.inputs["From Max"].default_value = 0.68
            st = self._math("MULTIPLY", self._math("MULTIPLY", sm.outputs["Result"], steep), 0.45 * ks)
            st = self._math("MULTIPLY", st, self._wall_groups(geo, conv, 10.0, 25.0))
            val = self._math("MULTIPLY", val, self._math("SUBTRACT", 1.0, st))
        cmb = self.node("ShaderNodeCombineXYZ")
        if warm is not None:
            self.link(self._math("MULTIPLY", val, self._math("ADD", warm, 1.0)), cmb.inputs["X"])
            self.link(self._math("MULTIPLY", val, self._math("MULTIPLY_ADD", warm, 0.7, 1.0)), cmb.inputs["Y"])
            self.link(self._math("MULTIPLY", val, self._math("MULTIPLY_ADD", warm, 0.4, 1.0)), cmb.inputs["Z"])
        else:
            for k in ("X", "Y", "Z"):
                self.link(val, cmb.inputs[k])
        # nothing where the mesh has no data
        f = self.node("ShaderNodeMix", data_type="VECTOR")
        self.link(has, f.inputs[0])
        f.inputs[4].default_value = (1.0, 1.0, 1.0)
        self.link(cmb.outputs[0], f.inputs[5])
        self.shared[key] = f.outputs[1]
        out = self.node("ShaderNodeVectorMath", operation="MULTIPLY")
        self.link(src, out.inputs[0])
        self.link(f.outputs[1], out.inputs[1])
        return out.outputs[0]

    def _base_color(self):
        c = self.p["color"]
        tint = [max(0.0, min(1.0, float(v))) for v in c["tint"]]
        m = c["map"]
        adjust = abs(c["brightness"] - 1) > 1e-4 or abs(c["saturation"] - 1) > 1e-4 or abs(c["contrast"]) > 1e-4
        if not m.get("image") or self.image(m["image"], color=True) is None:
            if not adjust:
                return tint
            src = None
        else:
            img = self.image(m["image"], color=True)
            src = img.outputs["Color"]
            if m.get("invert"):
                inv = self.node("ShaderNodeInvert")
                self.link(src, inv.inputs["Color"])
                src = inv.outputs["Color"]
            mix = self.node("ShaderNodeMix", data_type="RGBA", blend_type="MULTIPLY")
            mix.inputs["Factor"].default_value = 1.0
            self.link(src, mix.inputs[6])
            mix.inputs[7].default_value = (*tint, 1.0)
            src = mix.outputs[2]
        if adjust:
            hsv = self.node("ShaderNodeHueSaturation")
            hsv.inputs["Saturation"].default_value = float(c["saturation"])
            hsv.inputs["Value"].default_value = float(c["brightness"])
            if src is None:
                hsv.inputs["Color"].default_value = (*tint, 1.0)
            else:
                self.link(src, hsv.inputs["Color"])
            src = hsv.outputs["Color"]
            if abs(c["contrast"]) > 1e-4:
                bc = self.node("ShaderNodeBrightContrast")
                bc.inputs["Contrast"].default_value = float(c["contrast"])
                self.link(src, bc.inputs["Color"])
                src = bc.outputs["Color"]
        return src

    def normal(self):
        out = self._normal()
        if self._macro_on():
            out = self.macro_normal(out)
        if self._relief_on():
            out = self.tone_relief(out)
        return out

    def _rl_value(self, name, v):
        """(1.76.53) A number of the relief on a node of its own (simpler_rl_<name>): a slider of «Rilievo 3D» sets it
        in place (update_relief_values), the tree is not made again."""
        if ("rl", name) in self.shared:          # (1.76.58: one node per number in a tree - set in place by name)
            return self.shared[("rl", name)]
        n = self.node("ShaderNodeValue")
        n.name = n.label = "simpler_rl_" + name
        n.outputs[0].default_value = float(v)
        self.shared[("rl", name)] = n.outputs[0]
        return n.outputs[0]

    def tone_relief(self, nrm):
        """(1.76.40, Luca: «tutto molto convincente tranne la parte dietro dei monti») The rock's own relief in the
        shading, where the mesh cannot hold it: far from the camera the terrain has a point every 6-20 m and its walls
        came out smooth, like clay. On the steep faces, in metres, sized by the thickness of the layers. A bump on the
        normal: the shape stays, the light reads it.
        (1.76.53, Luca: «Rilievo 3D», a card of its own with pictures) the kind of relief (relief_params): «Attuale»
        (risers and benches of the layers, creases down the wall, a broken ridged surface - as before), «Canaloni
        erosi», «Parete fratturata», «Strati a cenge»; and its numbers - size, depth, detail, where, orientation - on
        value nodes set in place."""
        t = self.p["tone"]
        if "relief" in self.shared:
            # (1.76.56) a layer of the border blend: the relief of the land made by the material's own layer, on this
            # layer's normal (before, each layer made it again - with the thickness of the layers missing, 10 m)
            hb, strength, kN = self.shared["relief"]
            return self._relief_bump(nrm, hb, strength, kN)
        rp = relief_params(t)
        Tn = self._rl_value("T", rp["T"])
        sN = self._rl_value("s", rp["s"])
        kN = self._rl_value("k", rp["k"])
        wN = self._rl_value("w", rp["w"])
        dN = self._rl_value("d", rp["d"])
        oN = self._rl_value("o", rp["o"])
        M = lambda c: self._math("MULTIPLY", Tn, float(c))                 # c × T metres
        IV = lambda c: self._math("DIVIDE", 1.0 / float(c), Tn)            # 1 / (c × T)
        DET = lambda base: self._math("MULTIPLY", dN, 2.0 * float(base))   # (Dettaglio 50% = the base detail)
        attr = self.node("ShaderNodeAttribute")
        attr.attribute_type = "GEOMETRY"
        attr.attribute_name = self.TONE[1]
        usep = self.node("ShaderNodeSeparateXYZ")
        self.link(attr.outputs["Vector"], usep.inputs[0])
        u = usep.outputs[0]
        att0 = self.node("ShaderNodeAttribute")
        att0.attribute_type = "GEOMETRY"
        att0.attribute_name = self.TONE[0]
        s0 = self.node("ShaderNodeSeparateXYZ")
        self.link(att0.outputs["Vector"], s0.inputs[0])
        geo = self.node("ShaderNodeNewGeometry")
        nsep = self.node("ShaderNodeSeparateXYZ")
        self.link(geo.outputs["Normal"], nsep.inputs[0])
        mask = self._relief_mask()
        pos = self.node("ShaderNodeSeparateXYZ")
        self.link(geo.outputs["Position"], pos.inputs[0])
        kind = rp["type"]
        if rp["map"]:
            # (1.76.58) the user's own map in place of the kind: grey 50% = the wall as it is, white out, black in
            msN = self._rl_value("ms", rp["ms"])
            v = self._relief_tri(rp["map"], False, rp["anti"])
            h = self._math("MULTIPLY", self._math("SUBTRACT", v, 0.5), self._math("MULTIPLY", msN, RELIEF_MAP_HEIGHT))
        elif kind == "canaloni":
            h = self._relief_gullies(geo, pos, M, IV, DET)
        elif kind == "fratture":
            h = self._relief_fractured(geo, oN, M, IV, DET)
        elif kind == "cenge":
            h = self._relief_ledges(geo, pos, u, sN, M, IV, DET)
        else:
            h = self._relief_current(geo, pos, nsep, u, s0, M, IV, DET)
        # (Dettaglio past 50%: a fine broken grain on top - none at 50% and below)
        fine = self.node("ShaderNodeTexNoise")
        self.link(geo.outputs["Position"], fine.inputs["Vector"])
        self.link(IV(0.12), fine.inputs["Scale"])
        fine.inputs["Detail"].default_value = 3.0
        fr_ = self._math("SUBTRACT", 1.0, self._math("MULTIPLY", self._math("ABSOLUTE", self._math("SUBTRACT", fine.outputs["Fac"], 0.5)), 4.0))
        amt = self._math("MAXIMUM", self._math("MULTIPLY", self._math("SUBTRACT", dN, 0.5), 2.0), 0.0)
        h = self._math("ADD", h, self._math("MULTIPLY", self._math("MULTIPLY", fr_, M(0.06)), amt))
        h = self._math("MULTIPLY", h, mask)
        if rp["disp"]:
            # (1.76.55, Luca: «Displacement vero» in the Avanzate of «Rilievo 3D») the same relief made real geometry in
            # the final render (adaptive subdivision of the zone: _disp_settings): its part rw - the zone's
            # simpler_rw, 0 on the borders with the other zones (each zone is a mesh of its own: moved there they
            # would part) - goes to the displacement, × Ampiezza; the rest stays the bump. In the path tracing of the
            # view the material is «bump only» (Cycles makes a bump of the displacement): the same look, nothing more.
            aN = self._rl_value("a", rp["a"])
            rw = self.node("ShaderNodeAttribute")
            rw.attribute_type = "GEOMETRY"
            rw.attribute_name = RELIEF_RW
            rr = self._math("MINIMUM", self._math("MAXIMUM", rw.outputs["Fac"], 0.0), 1.0)
            dn = self.node("ShaderNodeDisplacement")
            dn.name = dn.label = "simpler_rl_disp"
            dn.inputs["Midlevel"].default_value = 0.0
            self.link(kN, dn.inputs["Scale"])
            self.link(self._math("MULTIPLY", self._math("MULTIPLY", h, rr), aN), dn.inputs["Height"])
            self._rel = dn.outputs["Displacement"]
            h = self._math("MULTIPLY", h, self._math("SUBTRACT", 1.0, rr))
        strength = self._math("MINIMUM", self._math("ADD", self._math("MULTIPLY", kN, 0.75), 0.25), 1.0)
        self.shared["relief"] = (h, strength, kN)
        return self._relief_bump(nrm, h, strength, kN)

    def _relief_mask(self):
        """(1.76.58) Where «Rilievo 3D» acts: the walls chosen by «Dove» (0 only the steepest, 50% the walls - normal up
        0.9 -> 0.6 -, 100% also the steep slopes), where the mesh has the terrain's data. Shared by the relief and the
        colour of the map, one per tree."""
        if "relief_mask" in self.shared:
            return self.shared["relief_mask"]
        wN = self._rl_value("w", relief_params(self.p["tone"])["w"])
        att0 = self.node("ShaderNodeAttribute")
        att0.attribute_type = "GEOMETRY"
        att0.attribute_name = self.TONE[0]
        s0 = self.node("ShaderNodeSeparateXYZ")
        self.link(att0.outputs["Vector"], s0.inputs[0])
        has = self._math("GREATER_THAN", s0.outputs[1], 1.5)
        geo = self.node("ShaderNodeNewGeometry")
        nsep = self.node("ShaderNodeSeparateXYZ")
        self.link(geo.outputs["Normal"], nsep.inputs[0])
        steep_r = self.node("ShaderNodeMapRange")
        steep_r.clamp = True
        self.link(nsep.outputs[2], steep_r.inputs["Value"])
        self.link(self._math("MINIMUM", self._math("ADD", self._math("MULTIPLY", wN, 0.3), 0.75), 0.99), steep_r.inputs["From Min"])
        self.link(self._math("ADD", self._math("MULTIPLY", wN, 0.3), 0.45), steep_r.inputs["From Max"])
        m = self._math("MULTIPLY", steep_r.outputs["Result"], has)
        self.shared["relief_mask"] = m
        return m

    def _relief_tri(self, name, color, anti):
        """(1.76.58) A map of «Rilievo 3D» on the terrain from three sides (triplanar, world metres): Grandezza metres a
        repeat, turned by Rotazione in the plane of each side - on a wall the strata of the picture lean as asked, the
        same on every face. «Rompi la ripetizione»: the picture moved (never turned: the direction stays) in cells of
        three repeats, a second layer over their seams. Grey (height) or colour; one per tree and map."""
        key = ("rtri", name, bool(color))
        if key in self.shared:
            return self.shared[key]
        im = bpy.data.images.get(name)
        want = "sRGB" if color else "Non-Color"
        try:
            if im.colorspace_settings.name != want and not im.get("simpler_proxy"):
                im = _colorspace_variant(im, want) if _used_elsewhere(im, self.nt) else im
                im.colorspace_settings.name = want
        except TypeError:
            pass
        msN = self._rl_value("ms", relief_params(self.p["tone"])["ms"])
        mrN = self._rl_value("mr", relief_params(self.p["tone"])["mr"])
        c = self._math("COSINE", mrN)
        sn = self._math("SINE", mrN)
        geo = self.node("ShaderNodeNewGeometry")
        P = self.node("ShaderNodeSeparateXYZ")
        self.link(geo.outputs["Position"], P.inputs[0])
        N = self.node("ShaderNodeSeparateXYZ")
        self.link(geo.outputs["Normal"], N.inputs[0])
        w = [self._math("POWER", self._math("ABSOLUTE", N.outputs[i]), 4.0) for i in range(3)]
        wsum = self._math("ADD", self._math("ADD", w[0], w[1]), self._math("ADD", w[2], 1e-5))

        def sample(vec):
            n = self.node("ShaderNodeTexImage")
            n.image = im
            n.interpolation = "Linear"
            self.link(vec, n.inputs["Vector"])
            return n.outputs["Color"]

        def face(a, b):
            u = self._math("DIVIDE", P.outputs[a], msN)
            v = self._math("DIVIDE", P.outputs[b], msN)
            ur = self._math("SUBTRACT", self._math("MULTIPLY", u, c), self._math("MULTIPLY", v, sn))
            vr = self._math("ADD", self._math("MULTIPLY", u, sn), self._math("MULTIPLY", v, c))
            uv = self.node("ShaderNodeCombineXYZ")
            self.link(ur, uv.inputs["X"])
            self.link(vr, uv.inputs["Y"])
            vec = uv.outputs[0]
            if not anti:
                return sample(vec)

            def moved(src):
                vc = self.node("ShaderNodeTexVoronoi")
                vc.voronoi_dimensions = "2D"
                vc.inputs["Scale"].default_value = 1.0 / 3.0
                self.link(src, vc.inputs["Vector"])
                sh = self.node("ShaderNodeVectorMath", operation="SCALE")
                self.link(vc.outputs["Color"], sh.inputs[0])
                sh.inputs["Scale"].default_value = 7.31
                mv = self.node("ShaderNodeVectorMath", operation="ADD")
                self.link(vec, mv.inputs[0])
                self.link(sh.outputs[0], mv.inputs[1])
                return mv.outputs[0]
            off = self.node("ShaderNodeVectorMath", operation="ADD")
            self.link(vec, off.inputs[0])
            off.inputs[1].default_value = (14.2, 6.8, 0.0)
            ve = self.node("ShaderNodeTexVoronoi")
            ve.voronoi_dimensions = "2D"
            ve.feature = "DISTANCE_TO_EDGE"
            ve.inputs["Scale"].default_value = 1.0 / 3.0
            self.link(vec, ve.inputs["Vector"])
            mk = self.node("ShaderNodeMapRange")
            mk.interpolation_type = "SMOOTHSTEP"
            self.link(ve.outputs["Distance"], mk.inputs["Value"])
            mk.inputs["From Min"].default_value = 0.0
            mk.inputs["From Max"].default_value = 0.1
            mx = self.node("ShaderNodeMix", data_type="RGBA")
            self.link(mk.outputs["Result"], mx.inputs["Factor"])
            self.link(sample(moved(off.outputs[0])), mx.inputs[6])
            self.link(sample(moved(vec)), mx.inputs[7])
            return mx.outputs[2]
        # X faces: (Y, Z); Y faces: (X, Z); Z faces: (X, Y)
        cols = [face(1, 2), face(0, 2), face(0, 1)]
        acc = None
        for i in range(3):
            sc = self.node("ShaderNodeVectorMath", operation="SCALE")
            self.link(cols[i], sc.inputs[0])
            self.link(self._math("DIVIDE", w[i], wsum), sc.inputs["Scale"])
            if acc is None:
                acc = sc.outputs[0]
            else:
                ad = self.node("ShaderNodeVectorMath", operation="ADD")
                self.link(acc, ad.inputs[0])
                self.link(sc.outputs[0], ad.inputs[1])
                acc = ad.outputs[0]
        if color:
            out = acc
        else:
            bw = self.node("ShaderNodeRGBToBW")
            self.link(acc, bw.inputs["Color"])
            out = bw.outputs["Val"]
        self.shared[key] = out
        return out

    def relief_color(self, src):
        """(1.76.58) The colour map of «Rilievo 3D» over the zone's colour, on the walls where the relief acts, ×
        «Colore dalla mappa»: drawn with the relief map of its set, its cracks fall in the relief's cracks. Before the
        colours from the land (they still lighten the crests and darken the gullies over it)."""
        rp = relief_params(self.p["tone"])
        caN = self._rl_value("ca", rp["ca"])
        if isinstance(src, (list, tuple)):
            src = self._const_rgb(src)
        mx = self.node("ShaderNodeMix", data_type="RGBA")
        self.link(self._math("MULTIPLY", self._relief_mask(), caN), mx.inputs["Factor"])
        self.link(src, mx.inputs[6])
        self.link(self._relief_tri(rp["cmap"], True, rp["anti"]), mx.inputs[7])
        return mx.outputs[2]

    def _relief_bump(self, nrm, h, strength, kN):
        bump = self.node("ShaderNodeBump")
        bump.name = bump.label = "simpler_rl_bump"
        self.link(strength, bump.inputs["Strength"])
        self.link(kN, bump.inputs["Distance"])
        self.link(h, bump.inputs["Height"])
        if nrm is not None:
            self.link(nrm, bump.inputs["Normal"])
        return bump.outputs["Normal"]

    def _relief_current(self, geo, pos, nsep, u, s0, M, IV, DET):
        """«Attuale» (1.76.40-43): the risers and benches of the layers, creases down the wall in groups, a broken
        ridged surface (with Dimensione 100%, Dettaglio 50%: the same numbers as before)."""
        # 1. risers and benches: in every layer a slow slope, then a step (a sawtooth in height, metres)
        fr = self._math("FRACT", u)
        stp = self.node("ShaderNodeMapRange")
        stp.interpolation_type = "SMOOTHSTEP"
        stp.clamp = True
        self.link(fr, stp.inputs["Value"])
        stp.inputs["From Min"].default_value = 0.62
        stp.inputs["From Max"].default_value = 0.92
        h1 = self._math("MULTIPLY", self._math("SUBTRACT", stp.outputs["Result"], fr), M(0.45))
        # (strong and faint layers, as the ledges of the mesh: not the same step in every layer - contour lines)
        ln = self.node("ShaderNodeTexNoise", noise_dimensions="1D")
        self.link(self._math("MULTIPLY", self._math("FLOOR", u), 0.43), ln.inputs["W"])
        ln.inputs["Scale"].default_value = 1.0
        ln.inputs["Detail"].default_value = 0.0
        lr = self.node("ShaderNodeMapRange")
        lr.interpolation_type = "SMOOTHSTEP"
        lr.clamp = True
        self.link(ln.outputs["Fac"], lr.inputs["Value"])
        lr.inputs["From Min"].default_value = 0.4
        lr.inputs["From Max"].default_value = 0.62
        lr.inputs["To Min"].default_value = 0.15
        h1 = self._math("MULTIPLY", h1, lr.outputs["Result"])
        # 2. creases down the wall: a noise long in height, narrow across; its middle line cut in
        ax = self._math("POWER", self._math("ABSOLUTE", nsep.outputs[0]), 4.0)
        ay = self._math("POWER", self._math("ABSOLUTE", nsep.outputs[1]), 4.0)
        wx = self._math("DIVIDE", ax, self._math("ADD", self._math("ADD", ax, ay), 1e-4))
        # (1.76.43) the line of each crease wanders and their spacing changes (a slow noise added across), not
        # a comb of parallel lines
        wn = self.node("ShaderNodeTexNoise")
        self.link(geo.outputs["Position"], wn.inputs["Vector"])
        self.link(IV(1.6), wn.inputs["Scale"])
        wn.inputs["Detail"].default_value = 1.0
        warp = self._math("MULTIPLY", self._math("SUBTRACT", wn.outputs["Fac"], 0.5), M(1.4))

        def crease(across):
            v = self.node("ShaderNodeCombineXYZ")
            self.link(self._math("MULTIPLY", self._math("ADD", across, warp), IV(0.35)), v.inputs["X"])
            self.link(self._math("MULTIPLY", pos.outputs[2], IV(2.5)), v.inputs["Y"])
            nz_ = self.node("ShaderNodeTexNoise")
            self.link(v.outputs[0], nz_.inputs["Vector"])
            nz_.inputs["Scale"].default_value = 1.0
            self.link(DET(2.0), nz_.inputs["Detail"])
            return nz_.outputs["Fac"]
        cn = self._math("ADD", self._math("MULTIPLY", crease(pos.outputs[1]), wx),
                        self._math("MULTIPLY", crease(pos.outputs[0]), self._math("SUBTRACT", 1.0, wx)))
        cr = self.node("ShaderNodeMapRange")
        cr.clamp = True
        self.link(self._math("ABSOLUTE", self._math("SUBTRACT", cn, 0.5)), cr.inputs["Value"])
        cr.inputs["From Min"].default_value = 0.0
        cr.inputs["From Max"].default_value = 0.07
        h2 = self._math("MULTIPLY", self._math("SUBTRACT", cr.outputs["Result"], 1.0), M(0.25))
        # (1.76.43) deep and faint creases side by side (a noise long in height: the same along one crease), and only
        # where the wall has them (_wall_groups)
        dn = self.node("ShaderNodeCombineXYZ")
        self.link(self._math("MULTIPLY", pos.outputs[0], IV(0.9)), dn.inputs["X"])
        self.link(self._math("MULTIPLY", pos.outputs[1], IV(0.9)), dn.inputs["Y"])
        self.link(self._math("MULTIPLY", pos.outputs[2], IV(6.0)), dn.inputs["Z"])
        dnz = self.node("ShaderNodeTexNoise")
        self.link(dn.outputs[0], dnz.inputs["Vector"])
        dnz.inputs["Scale"].default_value = 1.0
        dnz.inputs["Detail"].default_value = 0.0
        dep = self.node("ShaderNodeMapRange")
        dep.clamp = True
        self.link(dnz.outputs["Fac"], dep.inputs["Value"])
        dep.inputs["From Min"].default_value = 0.35
        dep.inputs["From Max"].default_value = 0.65
        dep.inputs["To Min"].default_value = 0.2
        T0 = float(relief_params(self.p["tone"])["T"])
        h2 = self._math("MULTIPLY", h2, self._math("MULTIPLY", dep.outputs["Result"],
                                                   self._wall_groups(geo, s0.outputs[0], max(8.0, 1.5 * T0), max(20.0, 4.0 * T0))))
        # 3. a broken, ridged surface (blocks a few metres across, sharp edges)
        rn = self.node("ShaderNodeTexNoise")
        self.link(geo.outputs["Position"], rn.inputs["Vector"])
        self.link(IV(0.6), rn.inputs["Scale"])
        self.link(DET(4.0), rn.inputs["Detail"])
        rn.inputs["Roughness"].default_value = 0.6
        ridge = self._math("SUBTRACT", 1.0, self._math("MULTIPLY", self._math("ABSOLUTE", self._math("SUBTRACT", rn.outputs["Fac"], 0.5)), 4.0))
        h3 = self._math("MULTIPLY", self._math("MULTIPLY", ridge, ridge), M(0.18))
        return self._math("ADD", self._math("ADD", h1, h2), h3)

    def _relief_gullies(self, geo, pos, M, IV, DET):
        """«Canaloni erosi»: the wall carved by water into gullies running down it, sharp spurs between them, smaller
        gullies branching off and fine rills - cells long in height (a Voronoi stretched along Z: its edges are the
        spurs, its middles the gullies), their lines wandering."""
        sc = self.node("ShaderNodeCombineXYZ")
        self.link(IV(1.6), sc.inputs["X"])
        self.link(IV(1.6), sc.inputs["Y"])
        self.link(IV(7.0), sc.inputs["Z"])
        wn = self.node("ShaderNodeTexNoise")
        self.link(geo.outputs["Position"], wn.inputs["Vector"])
        self.link(IV(3.0), wn.inputs["Scale"])
        wn.inputs["Detail"].default_value = 2.0
        wv = self.node("ShaderNodeVectorMath", operation="SUBTRACT")
        self.link(wn.outputs["Color"], wv.inputs[0])
        wv.inputs[1].default_value = (0.5, 0.5, 0.5)
        ws = self.node("ShaderNodeVectorMath", operation="SCALE")
        self.link(wv.outputs[0], ws.inputs[0])
        self.link(M(0.9), ws.inputs["Scale"])
        wp = self.node("ShaderNodeVectorMath", operation="ADD")
        self.link(geo.outputs["Position"], wp.inputs[0])
        self.link(ws.outputs[0], wp.inputs[1])
        mp = self.node("ShaderNodeVectorMath", operation="MULTIPLY")
        self.link(wp.outputs[0], mp.inputs[0])
        self.link(sc.outputs[0], mp.inputs[1])

        def gullies(scale, width, depth):
            v = self.node("ShaderNodeTexVoronoi", voronoi_dimensions="3D", feature="DISTANCE_TO_EDGE")
            self.link(mp.outputs[0], v.inputs["Vector"])
            v.inputs["Scale"].default_value = scale
            g = self.node("ShaderNodeMapRange")
            g.interpolation_type = "SMOOTHSTEP"
            g.clamp = True
            self.link(v.outputs["Distance"], g.inputs["Value"])
            g.inputs["From Min"].default_value = 0.0
            g.inputs["From Max"].default_value = width
            return self._math("MULTIPLY", self._math("POWER", g.outputs["Result"], 0.8), M(-depth))
        h = self._math("ADD", gullies(1.0, 0.45, 0.9), gullies(2.3, 0.4, 0.3))
        # fine rills down the spurs (Dettaglio)
        rv = self.node("ShaderNodeCombineXYZ")
        self.link(self._math("MULTIPLY", pos.outputs[0], IV(0.25)), rv.inputs["X"])
        self.link(self._math("MULTIPLY", pos.outputs[1], IV(0.25)), rv.inputs["Y"])
        self.link(self._math("MULTIPLY", pos.outputs[2], IV(1.5)), rv.inputs["Z"])
        rn = self.node("ShaderNodeTexNoise")
        self.link(rv.outputs[0], rn.inputs["Vector"])
        rn.inputs["Scale"].default_value = 1.0
        self.link(DET(2.0), rn.inputs["Detail"])
        rl = self.node("ShaderNodeMapRange")
        rl.clamp = True
        self.link(self._math("ABSOLUTE", self._math("SUBTRACT", rn.outputs["Fac"], 0.5)), rl.inputs["Value"])
        rl.inputs["From Min"].default_value = 0.0
        rl.inputs["From Max"].default_value = 0.08
        return self._math("ADD", h, self._math("MULTIPLY", self._math("SUBTRACT", rl.outputs["Result"], 1.0), M(0.08)))

    def _relief_fractured(self, geo, oN, M, IV, DET):
        """«Parete fratturata»: the wall broken into angular blocks of different sizes, each a flat face of its own
        tilt, standing out or set back, so the light breaks on it block by block (a Voronoi: each cell a block and
        its own plane - the cells a little longer along «Orientamento», turned about the vertical); thin cracks
        inside the blocks (Dettaglio)."""
        rot = self.node("ShaderNodeCombineXYZ")
        self.link(oN, rot.inputs["Z"])
        sc = self.node("ShaderNodeCombineXYZ")
        self.link(IV(0.75), sc.inputs["X"])
        self.link(IV(0.5), sc.inputs["Y"])
        self.link(IV(0.6), sc.inputs["Z"])
        mp = self.node("ShaderNodeMapping", vector_type="POINT")
        self.link(geo.outputs["Position"], mp.inputs["Vector"])
        self.link(rot.outputs[0], mp.inputs["Rotation"])
        self.link(sc.outputs[0], mp.inputs["Scale"])
        # (the edges of the blocks not straight lines: the coordinates bent a little)
        wn = self.node("ShaderNodeTexNoise")
        self.link(mp.outputs[0], wn.inputs["Vector"])
        wn.inputs["Scale"].default_value = 0.6
        wn.inputs["Detail"].default_value = 2.0
        wv = self.node("ShaderNodeVectorMath", operation="SUBTRACT")
        self.link(wn.outputs["Color"], wv.inputs[0])
        wv.inputs[1].default_value = (0.5, 0.5, 0.5)
        wp = self.node("ShaderNodeVectorMath", operation="MULTIPLY_ADD")
        self.link(wv.outputs[0], wp.inputs[0])
        wp.inputs[1].default_value = (0.5, 0.5, 0.5)
        self.link(mp.outputs[0], wp.inputs[2])
        v1 = self.node("ShaderNodeTexVoronoi", voronoi_dimensions="3D", feature="F1")
        self.link(wp.outputs[0], v1.inputs["Vector"])
        v1.inputs["Scale"].default_value = 1.0
        tilt = self.node("ShaderNodeVectorMath", operation="SUBTRACT")
        self.link(v1.outputs["Color"], tilt.inputs[0])
        tilt.inputs[1].default_value = (0.5, 0.5, 0.5)
        rel = self.node("ShaderNodeVectorMath", operation="SUBTRACT")
        self.link(wp.outputs[0], rel.inputs[0])
        self.link(v1.outputs["Position"], rel.inputs[1])
        dot = self.node("ShaderNodeVectorMath", operation="DOT_PRODUCT")
        self.link(rel.outputs[0], dot.inputs[0])
        self.link(tilt.outputs[0], dot.inputs[1])
        csep = self.node("ShaderNodeSeparateColor")
        self.link(v1.outputs["Color"], csep.inputs[0])
        h = self._math("ADD", self._math("MULTIPLY", dot.outputs["Value"], M(1.1)),
                       self._math("MULTIPLY", self._math("SUBTRACT", csep.outputs[2], 0.5), M(0.3)))
        # thin cracks inside the blocks (Dettaglio)
        ce = self.node("ShaderNodeTexVoronoi", voronoi_dimensions="3D", feature="DISTANCE_TO_EDGE")
        self.link(wp.outputs[0], ce.inputs["Vector"])
        ce.inputs["Scale"].default_value = 2.7
        cr = self.node("ShaderNodeMapRange")
        cr.clamp = True
        self.link(ce.outputs["Distance"], cr.inputs["Value"])
        cr.inputs["From Min"].default_value = 0.0
        cr.inputs["From Max"].default_value = 0.02
        # (in places only: a wall is not a dried mud)
        cm = self.node("ShaderNodeTexNoise")
        self.link(geo.outputs["Position"], cm.inputs["Vector"])
        self.link(IV(1.5), cm.inputs["Scale"])
        cm.inputs["Detail"].default_value = 1.0
        cmr = self.node("ShaderNodeMapRange")
        cmr.interpolation_type = "SMOOTHSTEP"
        cmr.clamp = True
        self.link(cm.outputs["Fac"], cmr.inputs["Value"])
        cmr.inputs["From Min"].default_value = 0.5
        cmr.inputs["From Max"].default_value = 0.65
        crack = self._math("MULTIPLY", self._math("SUBTRACT", cr.outputs["Result"], 1.0), M(0.025))
        h = self._math("ADD", h, self._math("MULTIPLY", self._math("MULTIPLY", crack, DET(0.5)), cmr.outputs["Result"]))
        # (the faces not smooth as plastic: a light broken grain)
        rn = self.node("ShaderNodeTexNoise")
        self.link(geo.outputs["Position"], rn.inputs["Vector"])
        self.link(IV(0.3), rn.inputs["Scale"])
        self.link(DET(3.0), rn.inputs["Detail"])
        rn.inputs["Roughness"].default_value = 0.6
        ridge = self._math("SUBTRACT", 1.0, self._math("MULTIPLY", self._math("ABSOLUTE", self._math("SUBTRACT", rn.outputs["Fac"], 0.5)), 4.0))
        return self._math("ADD", h, self._math("MULTIPLY", self._math("MULTIPLY", ridge, ridge), M(0.035)))

    def _relief_ledges(self, geo, pos, u, sN, M, IV, DET):
        """«Strati a cenge»: the layers of the rock (the same as the bands and the ledges of «Roccia scolpita», their
        thickness × Dimensione) as strong ledges: a bench, then a riser, layer after layer, hard and soft layers
        side by side, the risers worn in streaks along the layer."""
        uu = self._math("DIVIDE", u, sN)
        fr = self._math("FRACT", uu)
        stp = self.node("ShaderNodeMapRange")
        stp.interpolation_type = "SMOOTHSTEP"
        stp.clamp = True
        self.link(fr, stp.inputs["Value"])
        stp.inputs["From Min"].default_value = 0.5
        stp.inputs["From Max"].default_value = 0.95
        h1 = self._math("MULTIPLY", self._math("SUBTRACT", stp.outputs["Result"], fr), M(0.7))
        ln = self.node("ShaderNodeTexNoise", noise_dimensions="1D")
        self.link(self._math("MULTIPLY", self._math("FLOOR", uu), 0.43), ln.inputs["W"])
        ln.inputs["Scale"].default_value = 1.0
        ln.inputs["Detail"].default_value = 0.0
        lr = self.node("ShaderNodeMapRange")
        lr.interpolation_type = "SMOOTHSTEP"
        lr.clamp = True
        self.link(ln.outputs["Fac"], lr.inputs["Value"])
        lr.inputs["From Min"].default_value = 0.35
        lr.inputs["From Max"].default_value = 0.6
        lr.inputs["To Min"].default_value = 0.3
        h1 = self._math("MULTIPLY", h1, lr.outputs["Result"])
        # streaks along the layer on the risers (worn edges), long across, short in height
        sv = self.node("ShaderNodeCombineXYZ")
        self.link(self._math("MULTIPLY", pos.outputs[0], IV(1.5)), sv.inputs["X"])
        self.link(self._math("MULTIPLY", pos.outputs[1], IV(1.5)), sv.inputs["Y"])
        self.link(self._math("MULTIPLY", uu, 6.0), sv.inputs["Z"])
        sn = self.node("ShaderNodeTexNoise")
        self.link(sv.outputs[0], sn.inputs["Vector"])
        sn.inputs["Scale"].default_value = 1.0
        self.link(DET(2.0), sn.inputs["Detail"])
        h1 = self._math("ADD", h1, self._math("MULTIPLY", self._math("SUBTRACT", sn.outputs["Fac"], 0.5), M(0.25)))
        # the rock itself broken (as in «Attuale», lighter)
        rn = self.node("ShaderNodeTexNoise")
        self.link(geo.outputs["Position"], rn.inputs["Vector"])
        self.link(IV(0.5), rn.inputs["Scale"])
        self.link(DET(4.0), rn.inputs["Detail"])
        rn.inputs["Roughness"].default_value = 0.6
        ridge = self._math("SUBTRACT", 1.0, self._math("MULTIPLY", self._math("ABSOLUTE", self._math("SUBTRACT", rn.outputs["Fac"], 0.5)), 4.0))
        return self._math("ADD", h1, self._math("MULTIPLY", self._math("MULTIPLY", ridge, ridge), M(0.1)))

    def _normal(self):
        n = self.p["normal"]
        out = None
        nm = n["map"]
        if nm.get("image"):
            img = self.image(nm["image"], color=False, normal=True, scale=map_scale(nm))
            if img is not None:
                col = img.outputs["Color"]
                if n.get("directx"):
                    sep = self.node("ShaderNodeSeparateColor")
                    self.link(col, sep.inputs[0])
                    g = self.node("ShaderNodeMath", operation="SUBTRACT")
                    g.inputs[0].default_value = 1.0
                    self.link(sep.outputs[1], g.inputs[1])
                    comb = self.node("ShaderNodeCombineColor")
                    self.link(sep.outputs[0], comb.inputs[0])
                    self.link(g.outputs[0], comb.inputs[1])
                    self.link(sep.outputs[2], comb.inputs[2])
                    col = comb.outputs[0]
                nmap = self.node("ShaderNodeNormalMap")
                nmap.inputs["Strength"].default_value = max(0.0, float(n["strength"]))
                self.link(col, nmap.inputs["Color"])
                out = nmap.outputs["Normal"]
        h = self.scalar(n["bumpMap"])
        if h is not None and float(n["bump"]) > 0:
            bump = self.node("ShaderNodeBump")
            bump.inputs["Strength"].default_value = max(0.0, min(1.0, float(n["bump"])))
            bump.inputs["Distance"].default_value = max(1e-5, float(n["bumpDistanceMm"]) / 1000.0)
            self.link(h, bump.inputs["Height"])
            if out is not None:
                self.link(out, bump.inputs["Normal"])
            out = bump.outputs["Normal"]
        return out

    def build(self):
        p, nt, mat = self.p, self.nt, self.mat
        out = None
        if not self.layer:
            nt.nodes.clear()
            out = self.node("ShaderNodeOutputMaterial")
            out.location = (600, 0)
        bsdf = self.node("ShaderNodeBsdfPrincipled")
        bsdf.location = (200, 0)
        base = self.base_color()
        fol = p.get("foliage") or {}
        fab = p.get("fabric") or {}
        keep = None
        if fol.get("enabled"):
            base, keep = self.foliage_color(base, fol)
        elif fab.get("enabled"):
            base, keep = self.fabric_color(base, fab)
        gmask = self.grunge()
        if gmask is not None:
            base = self.grunge_color(base, gmask)
        self.put(bsdf.inputs["Base Color"], base)
        rmap = dict(p["roughness"]["map"])
        if p["roughness"].get("glossy"):            # a glossiness map: white = shiny, so it is inverted
            rmap["invert"] = not rmap.get("invert")
        rough = self.mixed(float(p["roughness"]["value"]), rmap)
        if gmask is not None:
            rough = self.grunge_rough(rough, gmask)
        self.put(bsdf.inputs["Roughness"], rough)
        self.put(bsdf.inputs["Metallic"], self.mixed(float(p["metallic"]["value"]), p["metallic"]["map"]))
        bsdf.inputs["Specular IOR Level"].default_value = float(p["specular"])
        nrm = self.normal()
        if gmask is not None:
            nrm = self.grunge_normal(nrm, gmask)
        if nrm is not None:
            self.link(nrm, bsdf.inputs["Normal"])
        bsdf.inputs["Coat Weight"].default_value = float(p["coat"]["weight"])
        bsdf.inputs["Coat Roughness"].default_value = float(p["coat"]["roughness"])
        t = p["transmission"]
        tw = max(0.0, min(1.0, float(t["weight"])))
        bsdf.inputs["IOR"].default_value = max(1.0, float(t["ior"]))
        if "Thin Wall" in bsdf.inputs:
            bsdf.inputs["Thin Wall"].default_value = bool(t["thin"])
        bsdf.inputs["Sheen Weight"].default_value = float(p["sheen"]["weight"])
        if fab.get("enabled"):
            fm = self.scalar(fab.get("fuzzMap"))
            if fm is not None:        # (the fuzz only where the mask is white: velvet bands on a plain cloth)
                self.link(self._math("MULTIPLY", fm, float(p["sheen"]["weight"])), bsdf.inputs["Sheen Weight"])
        bsdf.inputs["Sheen Roughness"].default_value = float(p["sheen"]["roughness"])
        bsdf.inputs["Sheen Tint"].default_value = (*p["sheen"]["tint"][:3], 1.0)
        bsdf.inputs["Subsurface Weight"].default_value = float(p["subsurface"]["weight"])
        bsdf.inputs["Subsurface Scale"].default_value = max(0.0, float(p["subsurface"]["radiusMm"])) / 1000.0
        bsdf.inputs["Subsurface Radius"].default_value = tuple(max(1e-3, float(v)) for v in p["subsurface"]["color"][:3])
        self.emission(bsdf)
        itr = p.get("interior") or {}
        if itr.get("enabled"):
            self.interior(bsdf, itr)
        alpha = self.opacity(bsdf, keep)
        surface = bsdf.outputs["BSDF"]
        if fol.get("enabled") and fol.get("part", "foglie") != "legno" and float(fol.get("translucency", 0)) > 0:
            surface = self.foliage_translucent(surface, base, nrm, alpha, float(fol["translucency"]))
        elif fab.get("enabled") and fab.get("mode") == "sottile" and float(fab.get("light", 0)) > 0:
            surface = self.foliage_translucent(surface, base, nrm, alpha, float(fab["light"]))
        if tw > 0 and t["dispersion"] and not t["thin"]:
            bsdf.inputs["Transmission Weight"].default_value = 0.0
            glass = self.dispersive_glass(base, nrm)
            mix = self.node("ShaderNodeMixShader")
            mix.location = (420, 0)
            mix.inputs["Fac"].default_value = tw
            self.link(surface, mix.inputs[1])
            self.link(glass, mix.inputs[2])
            surface = mix.outputs[0]
        else:
            bsdf.inputs["Transmission Weight"].default_value = tw
        if self.layer:
            return surface, base, self._disp_socket()
        if isinstance(p.get("blend"), dict) and p["blend"].get("partners") and float(p["blend"].get("width") or 0) > 0:
            surface = self.edge_blend(surface, base)
        self.link(surface, out.inputs["Surface"])
        if tw > 0 and not t["thin"] and float(t["absorbCm"]) > 0:
            vol = self.node("ShaderNodeVolumeAbsorption")
            vol.inputs["Color"].default_value = (*t["absorbColor"][:3], 1.0)
            vol.inputs["Density"].default_value = 100.0 / max(0.01, float(t["absorbCm"]))
            self.link(vol.outputs[0], out.inputs["Volume"])
        d = p["displacement"]
        disp = self._disp_socket()
        if getattr(self, "_eb", None):
            # (1.76.4) the relief blended with the same factors as the colours: on the border the two sides move the
            # surface by the same amount (true displacement: no step between the two meshes)
            for fac, db in self._eb:
                if disp is None and db is None:
                    continue
                mv = self.node("ShaderNodeMix", data_type="VECTOR")
                self.link(fac, mv.inputs[0])
                if disp is not None:
                    self.link(disp, mv.inputs[4])
                if db is not None:
                    self.link(db, mv.inputs[5])
                disp = mv.outputs[1]
        rel = getattr(self, "_rel", None)
        if rel is not None:
            # (1.76.55) the true relief of the rock («Rilievo 3D», Displacement vero): only in the final render
            if disp is not None:
                add = self.node("ShaderNodeVectorMath", operation="ADD")
                self.link(disp, add.inputs[0]); self.link(rel, add.inputs[1])
                disp = add.outputs[0]
            else:
                disp = rel
            if not d["enabled"]:
                d = dict(d, enabled=True, mode="both", finalOnly=True)
        if disp is not None and not d["enabled"]:
            # (only the zones next to this one have a relief: their settings decide how it is drawn)
            d = next((dd for dd in (_merge(DEFAULTS, q.get("params") or {})["displacement"]
                                    for q in ((p.get("blend") or {}).get("partners") or [])) if dd["enabled"]), d)
        if disp is not None:
            self.link(disp, out.inputs["Displacement"])
            method = {"true": "DISPLACEMENT", "bump": "BUMP"}.get(d["mode"], "BOTH")
            mat["simpler_disp_method"] = method
            if d["finalOnly"] and method != "BUMP":
                mat["simpler_disp_final_only"] = 1
                method = "BUMP" if not _FINAL["on"] else method
            elif "simpler_disp_final_only" in mat:
                del mat["simpler_disp_final_only"]
            mat.displacement_method = method
        else:
            mat.displacement_method = "BUMP"
            for k in ("simpler_disp_method", "simpler_disp_final_only"):
                if k in mat:
                    del mat[k]
        mat.diffuse_color = (*[float(v) for v in p["color"]["tint"][:3]], 1.0)

    def _disp_socket(self):
        """The displacement of this material (height map and/or vector map) as a vector socket, or None."""
        d = self.p["displacement"]
        h = self.scalar(d["map"]) if d["enabled"] else None
        disp = None
        if h is not None:
            dn = self.node("ShaderNodeDisplacement")
            dn.inputs["Midlevel"].default_value = float(d["midlevel"])
            dn.inputs["Scale"].default_value = float(d["heightCm"]) / 100.0
            self.link(h, dn.inputs["Height"])
            disp = dn.outputs[0]
        vimg = self.image(d["vector"]["image"], color=False) if d["enabled"] and d["vector"].get("image") else None
        if vimg is not None:
            # vector displacement map (tangent space): the surface can move sideways too (overhangs, tiles, rocks)
            vn = self.node("ShaderNodeVectorDisplacement")
            vn.space = "TANGENT"
            vn.inputs["Midlevel"].default_value = float(d["vectorMid"])
            vn.inputs["Scale"].default_value = float(d["vectorScale"])
            self.link(vimg.outputs["Color"], vn.inputs["Vector"])
            if disp is not None:
                add = self.node("ShaderNodeVectorMath", operation="ADD")
                self.link(disp, add.inputs[0]); self.link(vn.outputs[0], add.inputs[1])
                disp = add.outputs[0]
            else:
                disp = vn.outputs[0]
        return disp

    def _lum(self, base):
        """Brightness of a base colour (socket or RGB list) as a socket: the «height» of a texture for the blend
        (stones are lighter than the soil between them) - the view uses the same."""
        if isinstance(base, (list, tuple)):
            v = self.node("ShaderNodeValue")
            v.outputs[0].default_value = 0.2126 * base[0] + 0.7152 * base[1] + 0.0722 * base[2]
            return v.outputs[0]
        bw = self.node("ShaderNodeRGBToBW")
        self.link(base, bw.inputs["Color"])
        return bw.outputs["Val"]

    def _math(self, op, a, b=None, c=None):
        m = self.node("ShaderNodeMath", operation=op)
        for i, v in enumerate((a, b, c)):
            if v is None:
                continue
            if isinstance(v, (int, float)):
                m.inputs[i].default_value = float(v)
            else:
                self.link(v, m.inputs[i])
        return m.outputs[0]

    def edge_blend(self, surface, base):
        """(1.76.4) «Sfumatura dei bordi» of the terrain: near the border with another zone this material shows that
        zone's material, mixed in where the border is - not a fade, a ragged edge: the lighter (higher) texture
        comes through first (stones out of the grass, grass between the stones) and a noise breaks the line. The
        distance to each zone: UV maps of the mesh (terrain._blend_uv: distance + 1, 0 = none). The two sides use
        the same numbers with opposite sign, so on the border one is exactly the other's complement: no line.
        Same formula in the view (viewer.js useEdgeBlend)."""
        b = self.p["blend"]
        self._eb = []
        W = max(0.05, float(b.get("width") or 1.0))
        irr = max(0.0, min(1.0, float(b.get("irregular", 0.6))))
        geo = self.node("ShaderNodeNewGeometry")
        noise = self.node("ShaderNodeTexNoise")
        noise.name = "simpler_eb_noise"           # (1.76.50: named - update_blend_values changes them in place)
        noise.inputs["Scale"].default_value = 1.0 / max(0.3, W)
        noise.inputs["Detail"].default_value = 4.0
        noise.inputs["Roughness"].default_value = 0.6
        self.link(geo.outputs["Position"], noise.inputs["Vector"])
        hA = self._lum(base)
        for i_part, part in enumerate(b["partners"]):
            sub = _Builder(self.mat, _merge(DEFAULTS, part.get("params") or {}), layer=True, shared=self.shared)
            sub.x = self.x
            surfB, baseB, dispB = sub.build()
            hB = self._lum(baseB)
            attr = self.node("ShaderNodeAttribute")
            attr.attribute_type = "GEOMETRY"
            attr.attribute_name = part["attr"]
            sep = self.node("ShaderNodeSeparateXYZ")
            self.link(attr.outputs["Vector"], sep.inputs[0])
            raw = sep.outputs[int(part.get("comp", 0))]
            d = self._math("SUBTRACT", raw, 1.0)                           # (stored + 1)
            have = self._math("GREATER_THAN", raw, 0.5)                    # (0: no data on this object)
            sign = 1.0 if float(part.get("sign", 1)) >= 0 else -1.0
            Wp = max(0.05, float(part.get("width") or W))                 # (1.76.12: the snow, wider)
            t = self._math("MULTIPLY_ADD", d, -0.5 / Wp, 0.5)             # 0.5 at the border, 0 at W
            t.node.name = f"simpler_eb_t{i_part}"
            nsrc = noise
            if abs(Wp - W) > 1e-6:
                nsrc = self.node("ShaderNodeTexNoise")                     # (its own size of the patches)
                nsrc.name = f"simpler_eb_noise{i_part}"
                nsrc.inputs["Scale"].default_value = 1.0 / max(0.3, Wp)
                nsrc.inputs["Detail"].default_value = 4.0
                nsrc.inputs["Roughness"].default_value = 0.6
                self.link(geo.outputs["Position"], nsrc.inputs["Vector"])
            nz = self._math("MULTIPLY_ADD", nsrc.outputs["Fac"], sign * irr, -0.5 * sign * irr)
            nz.node.name = f"simpler_eb_nz{i_part}"
            # (1.76.56, Luca: «guarda in basso com'è tutto seghettato») the lighter texture comes through first - right
            # for stones of a texture of a metre or two; a photo of a whole cliff (tens of metres) put its light
            # and dark patches, with their sharp outlines, as the border: teeth of metres. Its share fades with its
            # size (blend_lum_weight); the same on both sides, so the two borders stay each other's complement.
            wA, wB = blend_lum_weight(self.p), blend_lum_weight(_merge(DEFAULTS, part.get("params") or {}))
            if wA == 1.0 and wB == 1.0:
                hd = self._math("MULTIPLY", self._math("SUBTRACT", hB, hA), 0.5)
            else:
                hd = self._math("SUBTRACT", self._math("MULTIPLY_ADD", hB, 0.5 * wB, -0.25 * wB),
                                self._math("MULTIPLY_ADD", hA, 0.5 * wA, -0.25 * wA))
            arg = self._math("ADD", self._math("ADD", t, nz), hd)
            mr = self.node("ShaderNodeMapRange")
            mr.clamp = True
            self.link(arg, mr.inputs["Value"])
            mr.inputs["From Min"].default_value = 0.5 - 0.125
            mr.inputs["From Max"].default_value = 0.5 + 0.125
            fac = self._math("MULTIPLY", mr.outputs["Result"], have)
            mix = self.node("ShaderNodeMixShader")
            self.link(fac, mix.inputs["Fac"])
            self.link(surface, mix.inputs[1])
            self.link(surfB, mix.inputs[2])
            surface = mix.outputs[0]
            self._eb.append((fac, dispB))
        return surface

    def emission(self, bsdf):
        e = self.p["emission"]
        nits = max(0.0, float(e["nits"]))
        # switched off, or "from dusk to dawn" in daytime (dusk.py): strength 0, the luminance stays in the channels
        from . import dusk
        lit = dusk.mat_lit(self.p)
        self.mat["simpler_lit"] = int(lit)
        bsdf.inputs["Emission Strength"].default_value = nits / NITS_PER_UNIT if lit else 0.0
        if nits <= 0:
            bsdf.inputs["Emission Color"].default_value = (0, 0, 0, 1)
            return
        bb = self.node("ShaderNodeBlackbody")
        bb.inputs["Temperature"].default_value = max(800.0, min(40000.0, float(e["kelvin"])))
        mix = self.node("ShaderNodeMix", data_type="RGBA", blend_type="MULTIPLY")
        mix.inputs["Factor"].default_value = 1.0
        self.link(bb.outputs[0], mix.inputs[6])
        img = self.image(e["map"]["image"], color=True) if e["map"].get("image") else None
        if img is not None:
            tint = self.node("ShaderNodeMix", data_type="RGBA", blend_type="MULTIPLY")
            tint.inputs["Factor"].default_value = 1.0
            self.link(img.outputs["Color"], tint.inputs[6])
            tint.inputs[7].default_value = (*e["color"][:3], 1.0)
            self.link(tint.outputs[2], mix.inputs[7])
        else:
            mix.inputs[7].default_value = (*e["color"][:3], 1.0)
        self.link(mix.outputs[2], bsdf.inputs["Emission Color"])

    def opacity(self, bsdf, keep=None):
        """Alpha of the surface (cut-out at 50% unless graded). keep: (Fogliame) 0 where the leaf has fallen.
        Returns the alpha socket, or None when the surface is whole."""
        o = self.p["opacity"]
        src = None
        if o["useAlpha"] and self.p["color"]["map"].get("image"):
            img = self.image(self.p["color"]["map"]["image"], color=True)
            src = img.outputs["Alpha"] if img is not None else None
            if src is not None and o["invert"]:
                inv = self.node("ShaderNodeMath", operation="SUBTRACT")
                inv.inputs[0].default_value = 1.0
                self.link(src, inv.inputs[1])
                src = inv.outputs[0]
        elif o["map"].get("image"):
            m = dict(o["map"])
            m["invert"] = bool(o["invert"]) != bool(m.get("invert"))
            src = self.scalar(m)
        if o["useAlpha"]:
            ref = (self.p["color"]["map"].get("image"), "A")
        else:
            ref = (o["map"].get("image"), o["map"].get("channel") or "")
        if src is not None and o.get("cutout", True) and not graded_opacity(*ref):
            # clean cut at 50%, as the real-time view does (alphaTest 0.5): leaf textures often have a background
            # that is only partly transparent, which path tracing would show as grey veils around every leaf.
            # A narrow ramp instead of a step keeps the edges of the leaves smooth.
            cut = self.node("ShaderNodeMapRange")
            cut.clamp = True
            cut.inputs["From Min"].default_value = 0.45
            cut.inputs["From Max"].default_value = 0.55
            self.link(src, cut.inputs["Value"])
            src = cut.outputs["Result"]
        if keep is not None:
            src = keep if src is None else self._math("MULTIPLY", src, keep)
        if src is not None:
            self.link(src, bsdf.inputs["Alpha"])
        else:
            bsdf.inputs["Alpha"].default_value = 1.0
        return src

    # ---- «Fogliame» (1.77.0): variation, season, back of the leaf, darker inside the crown, light through the leaf.
    # The randoms: Random Per Island (each leaf, when the leaves are separate pieces), the object's random (each
    # plant, each copy of a distribution) and a slow noise in metres around the plant (whole branches together).
    # The view (viewer.js useFoliage) does the same with its own randoms: the same character, not the same leaves.
    def _fract(self, v, k, o):
        return self._math("FRACT", self._math("MULTIPLY_ADD", v, k, o))

    def _const(self, v):
        n = self.node("ShaderNodeValue")
        n.outputs[0].default_value = float(v)
        return n.outputs[0]

    def interior(self, bsdf, it):
        """(1.79.0) «Interni»: the room seen through the glass, as light coming out of it (the reflections of the
        glass stay the Principled's). Interior mapping in the space of the object: the face looks along X or Y (the
        larger of its normal); the cell of the point; the ray from the eye into the cell's box (0..1 across, up, deep);
        the point it hits is projected as the camera of the picture saw it (picture = room from outside its window)."""
        atlas = interior_atlas(it)
        im = atlas or interior_image(it.get("room"))
        if im is None:
            return
        W = max(0.2, float(it.get("roomW", 4.0)))
        H = max(0.2, float(it.get("roomH", 3.0)))
        D = max(0.2, float(it.get("depthM", 4.0)))
        M = self._math
        tc = self.node("ShaderNodeTexCoord")
        geo = self.node("ShaderNodeNewGeometry")
        # (the point from the lowest corner of the object: interior_pass)
        bb = self.node("ShaderNodeCombineXYZ")
        for i, k in enumerate(INTERIOR_BB):
            at = self.node("ShaderNodeAttribute", attribute_type="OBJECT", attribute_name=k)
            self.link(at.outputs["Fac"], bb.inputs[i])
        rel = self.node("ShaderNodeVectorMath", operation="SUBTRACT")
        self.link(tc.outputs["Object"], rel.inputs[0]); self.link(bb.outputs[0], rel.inputs[1])
        vt = self.node("ShaderNodeVectorTransform", vector_type="VECTOR", convert_from="WORLD", convert_to="OBJECT")
        self.link(geo.outputs["Incoming"], vt.inputs[0])
        ntf = self.node("ShaderNodeVectorTransform", vector_type="NORMAL", convert_from="WORLD", convert_to="OBJECT")
        self.link(geo.outputs["True Normal"], ntf.inputs[0])
        # the space of the object in metres of the scene (its scale: interior_pass; 1 where not written yet)
        sc = self.node("ShaderNodeCombineXYZ")
        for i, k in enumerate(INTERIOR_SC):
            at = self.node("ShaderNodeAttribute", attribute_type="OBJECT", attribute_name=k)
            self.link(M("ADD", at.outputs["Fac"], M("LESS_THAN", at.outputs["Fac"], 1e-6)), sc.inputs[i])

        # («Si adatta al modello»: interior_pass writes the scale the object had when it was switched on)
        def by(v, op):
            n = self.node("ShaderNodeVectorMath", operation=op)
            self.link(v, n.inputs[0]); self.link(sc.outputs[0], n.inputs[1])
            return n.outputs[0]
        sp, sv, sn = (self.node("ShaderNodeSeparateXYZ") for _ in range(3))
        self.link(by(rel.outputs[0], "MULTIPLY"), sp.inputs[0]); self.link(by(vt.outputs[0], "MULTIPLY"), sv.inputs[0])
        self.link(by(ntf.outputs[0], "DIVIDE"), sn.inputs[0])
        # the axes turned so that Z is the axis of the object that is up in the scene (interior_pass; Z if not written)
        ua = self.node("ShaderNodeAttribute", attribute_type="OBJECT", attribute_name=INTERIOR_UP[0]).outputs["Fac"]
        us = self.node("ShaderNodeAttribute", attribute_type="OBJECT", attribute_name=INTERIOR_UP[1]).outputs["Fac"]
        e0 = M("LESS_THAN", M("ABSOLUTE", M("SUBTRACT", ua, 1.0)), 0.5)
        e1 = M("LESS_THAN", M("ABSOLUTE", M("SUBTRACT", ua, 2.0)), 0.5)
        e2 = M("SUBTRACT", M("SUBTRACT", 1.0, e0), e1)
        sg = M("MULTIPLY_ADD", M("GREATER_THAN", us, -0.5), 2.0, -1.0)

        def turn(v):                                # (x, y, z) of the object -> (across, across, up), right-handed
            a, b, c = v.outputs[0], v.outputs[1], v.outputs[2]
            pick3 = lambda p, q, r: M("ADD", M("ADD", M("MULTIPLY", e2, p), M("MULTIPLY", e0, q)), M("MULTIPLY", e1, r))
            return pick3(a, b, c), M("MULTIPLY", pick3(b, c, a), sg), M("MULTIPLY", pick3(c, a, b), sg)
        px, py, pz = turn(sp)
        rx, ry, rz = (M("MULTIPLY", c, -1.0) for c in turn(sv))       # the ray: from the eye inwards
        nx, ny, nz = turn(sn)
        use_x = M("GREATER_THAN", M("ABSOLUTE", nx), M("ABSOLUTE", ny))
        sx, sy = M("SIGN", nx), M("SIGN", ny)
        face = M("LESS_THAN", M("ABSOLUTE", nz), INTERIOR_FLAT)

        def pick(a_y, b_x):                         # the facade along X (b) or along Y (a)
            return M("MULTIPLY_ADD", M("SUBTRACT", b_x, a_y), use_x, a_y)
        # across the facade, left to right seen from outside; up; into the room
        u = pick(M("MULTIPLY", M("MULTIPLY", px, sy), -1.0), M("MULTIPLY", py, sx))
        ru = pick(M("MULTIPLY", M("MULTIPLY", rx, sy), -1.0), M("MULTIPLY", ry, sx))
        rw = pick(M("MULTIPLY", M("MULTIPLY", ry, sy), -1.0), M("MULTIPLY", M("MULTIPLY", rx, sx), -1.0))
        cu, cv = M("DIVIDE", u, W), M("DIVIDE", pz, H)
        fu, fv = M("FRACT", cu), M("FRACT", cv)
        du = M("ADD", M("DIVIDE", ru, W), 1e-6)
        dv = M("ADD", M("DIVIDE", rz, H), 1e-6)
        dw = M("MAXIMUM", M("DIVIDE", rw, D), 1e-4)
        tx = M("DIVIDE", M("SUBTRACT", M("GREATER_THAN", du, 0.0), fu), du)
        ty = M("DIVIDE", M("SUBTRACT", M("GREATER_THAN", dv, 0.0), fv), dv)
        tz = M("DIVIDE", 1.0, dw)
        t = M("MINIMUM", M("MINIMUM", tx, ty), tz)
        hx = M("MULTIPLY_ADD", du, t, fu)
        hy = M("MULTIPLY_ADD", dv, t, fv)
        hz = M("MULTIPLY", dw, t)
        if atlas is not None:
            room = self.interior_atlas(im, t, tx, ty, tz, du, dv, dw, fu, fv, hx, hy, hz)
        else:
            s = M("DIVIDE", 1.0, M("MULTIPLY_ADD", hz, 1.0 / INTERIOR_BACK - 1.0, 1.0))
            ix = M("MULTIPLY_ADD", M("SUBTRACT", hx, 0.5), s, 0.5)
            iy = M("MULTIPLY_ADD", M("SUBTRACT", hy, 0.5), s, 0.5)
            uv = self.node("ShaderNodeCombineXYZ")
            self.link(ix, uv.inputs[0]); self.link(iy, uv.inputs[1])
            tex = self.node("ShaderNodeTexImage")
            tex.image = im
            tex.extension = "EXTEND"
            tex.interpolation = "Linear"
            self.link(uv.outputs[0], tex.inputs["Vector"])
            room = tex.outputs["Color"]
        # the light of the room: its daylight look (bright) + the night lights (warm or cold) in a share of the rooms
        night = self.node("ShaderNodeValue")
        night.name = INTERIOR_NIGHT_NODE
        night.outputs[0].default_value = interior_night(it)
        cell = self.node("ShaderNodeCombineXYZ")
        self.link(M("FLOOR", cu), cell.inputs[0]); self.link(M("FLOOR", cv), cell.inputs[1])
        self.link(M("ADD", M("MULTIPLY", use_x, 2.0), pick(sy, sx)), cell.inputs[2])
        wn = self.node("ShaderNodeTexWhiteNoise", noise_dimensions="3D")
        self.link(cell.outputs[0], wn.inputs["Vector"])
        on = M("LESS_THAN", wn.outputs["Value"], max(0.0, min(1.0, float(it.get("share", 0.6)))))
        bbk = self.node("ShaderNodeBlackbody")
        bbk.inputs["Temperature"].default_value = max(1000.0, min(12000.0, float(it.get("kelvin", 3000.0))))
        k = self.node("ShaderNodeVectorMath", operation="SCALE")
        self.link(bbk.outputs[0], k.inputs[0]); self.link(M("MULTIPLY", night.outputs[0], on), k.inputs["Scale"])
        light = self.node("ShaderNodeVectorMath", operation="ADD")
        self.link(k.outputs[0], light.inputs[0])
        bright = self.node("ShaderNodeValue")
        bright.name = INTERIOR_BRIGHT_NODE
        bright.outputs[0].default_value = interior_bright(it)
        self.link(bright.outputs[0], light.inputs[1])
        col = self.node("ShaderNodeVectorMath", operation="MULTIPLY")
        self.link(room, col.inputs[0]); self.link(light.outputs[0], col.inputs[1])
        self.link(col.outputs[0], bsdf.inputs["Emission Color"])
        self.link(face, bsdf.inputs["Emission Strength"])

    def interior_atlas(self, im, t, tx, ty, tz, du, dv, dw, fu, fv, hx, hy, hz):
        """(1.79.0) The room of a picture in the 3×3 cross (INTERIOR_TILES): the wall the ray hits read on its own tile,
        the two rows of furniture (planes across the room) and the frame of the window over it, by their transparency.
        Returns the colour socket."""
        M = self._math
        e = INTERIOR_EDGE

        def tile(name, a, b):                       # the colour and alpha of tile name at a, b (0..1 in the tile)
            c, r = INTERIOR_TILES[name]
            uv = self.node("ShaderNodeCombineXYZ")
            self.link(M("DIVIDE", M("ADD", self._clamp(a, e, 1.0 - e), c), 3.0), uv.inputs[0])
            self.link(M("DIVIDE", M("ADD", self._clamp(b, e, 1.0 - e), r), 3.0), uv.inputs[1])
            tex = self.node("ShaderNodeTexImage")
            tex.image = im
            tex.extension = "EXTEND"
            tex.interpolation = "Linear"
            self.link(uv.outputs[0], tex.inputs["Vector"])
            return tex.outputs["Color"], tex.outputs["Alpha"]

        def pick(a, b, w):                          # a + (b - a) w
            return M("MULTIPLY_ADD", M("SUBTRACT", b, a), w, a)
        # which wall: the back (the ray ends on its far plane), a side wall (across) or the ceiling / floor (up)
        fz = M("LESS_THAN", tz, M("MINIMUM", tx, ty))
        side = M("MULTIPLY", M("SUBTRACT", 1.0, fz), M("LESS_THAN", tx, ty))
        flat = M("MULTIPLY", M("SUBTRACT", 1.0, fz), M("SUBTRACT", 1.0, M("LESS_THAN", tx, ty)))
        right, up = M("GREATER_THAN", du, 0.0), M("GREATER_THAN", dv, 0.0)
        # along the wall from the window: the left wall and the floor meet the back wall at their far edge (1), the
        # right wall and the ceiling at their near edge (0) - as their tiles touch the back wall in the cross
        hzc = self._clamp(hz, 0.0, 1.0)
        away = lambda flip: M("MULTIPLY_ADD", flip, M("SUBTRACT", 1.0, M("MULTIPLY", hzc, 2.0)), hzc)
        col = M("ADD", M("ADD", fz, M("MULTIPLY", side, M("MULTIPLY", right, 2.0))), flat)
        row = M("ADD", M("ADD", fz, side), M("MULTIPLY", flat, M("MULTIPLY", up, 2.0)))
        a = M("ADD", M("MULTIPLY", M("ADD", fz, flat), hx), M("MULTIPLY", side, away(right)))
        b = M("ADD", M("MULTIPLY", M("ADD", fz, side), hy), M("MULTIPLY", flat, away(up)))
        uv = self.node("ShaderNodeCombineXYZ")          # on the tile (column, row) of the wall hit
        self.link(M("DIVIDE", M("ADD", self._clamp(a, e, 1.0 - e), col), 3.0), uv.inputs[0])
        self.link(M("DIVIDE", M("ADD", self._clamp(b, e, 1.0 - e), row), 3.0), uv.inputs[1])
        tex = self.node("ShaderNodeTexImage")
        tex.image = im
        tex.extension = "EXTEND"
        tex.interpolation = "Linear"
        self.link(uv.outputs[0], tex.inputs["Vector"])
        color = tex.outputs["Color"]
        # the furniture: planes across the room at their depth, seen where the ray reaches them before the walls
        for name, k in (("behind", INTERIOR_LAYERS[1]), ("front", INTERIOR_LAYERS[0])):
            tk = M("DIVIDE", k, dw)
            lx, ly = M("MULTIPLY_ADD", du, tk, fu), M("MULTIPLY_ADD", dv, tk, fv)
            inside = M("MULTIPLY", M("MULTIPLY", M("GREATER_THAN", lx, 0.0), M("LESS_THAN", lx, 1.0)),
                       M("MULTIPLY", M("GREATER_THAN", ly, 0.0), M("LESS_THAN", ly, 1.0)))
            seen = M("MULTIPLY", inside, M("LESS_THAN", tk, t))
            lc, la = tile(name, lx, ly)
            color = self._mix_col(color, lc, M("MULTIPLY", la, seen))
        fc, fa = tile("frame", fu, fv)
        return self._mix_col(color, fc, fa)

    def _clamp(self, v, lo, hi):
        return self._math("MINIMUM", self._math("MAXIMUM", v, lo), hi)

    def _mix_col(self, a, b, f):
        mx = self.node("ShaderNodeMix", data_type="RGBA")
        self.link(f, mx.inputs[0]); self.link(a, mx.inputs[6]); self.link(b, mx.inputs[7])
        return mx.outputs[2]

    def foliage_color(self, base, f):
        """The colour of a leaf (or of the wood) through the season; returns (colour socket, keep socket or None)."""
        leaves = f.get("part", "foglie") != "legno"
        season = max(0.0, min(1.0, float(f.get("season", 0.0)))) if leaves else 0.0
        var = max(0.0, min(1.0, float(f.get("variation", 0.3))))
        # (1.79.0) the season of the piece of a scatter, when it has one (1 + season; 0: the material's)
        per_piece = leaves and bool(self.mat.get(PIECE_SEASON_MAT))
        S = season
        if per_piece:
            at = self.node("ShaderNodeAttribute", attribute_type="INSTANCER", attribute_name=PIECE_SEASON)
            has = self._math("GREATER_THAN", at.outputs["Fac"], 0.5)
            S = self._math("MULTIPLY_ADD", has, self._math("SUBTRACT", self._math("SUBTRACT", at.outputs["Fac"], 1.0), season), season)
        geo = self.node("ShaderNodeNewGeometry")
        obi = self.node("ShaderNodeObjectInfo")
        rL = geo.outputs["Random Per Island"]
        rO = obi.outputs["Random"]
        rL2, rL3, rO2 = self._fract(rL, 7.31, 0.13), self._fract(rL, 3.77, 0.61), self._fract(rO, 5.17, 0.29)
        # variation (any season): hue and brightness a little different per plant and per leaf
        hue = self._math("ADD", self._math("MULTIPLY_ADD", rO, 0.04 * var, 0.5 - 0.02 * var),
                         self._math("MULTIPLY_ADD", rL3, 0.012 * var, -0.006 * var))
        val = self._math("ADD", self._math("MULTIPLY_ADD", rO2, 0.25 * var, 1.0 - 0.125 * var),
                         self._math("MULTIPLY_ADD", rL, 0.2 * var, -0.1 * var))
        sat = None
        keep = None
        if season > 0 or per_piece:
            # the moment of each leaf: early ones (low e) turn first
            rel = self.node("ShaderNodeVectorMath", operation="SUBTRACT")
            self.link(geo.outputs["Position"], rel.inputs[0]); self.link(obi.outputs["Location"], rel.inputs[1])
            nz = self.node("ShaderNodeTexNoise", noise_dimensions="4D")
            self.link(rel.outputs[0], nz.inputs["Vector"])
            self.link(self._math("MULTIPLY", rO, 31.0), nz.inputs["W"])
            nz.inputs["Scale"].default_value = 1.0 / FOLIAGE_NOISE_M
            nz.inputs["Detail"].default_value = 1.0
            e = self._math("MULTIPLY_ADD", nz.outputs["Fac"], 0.5,
                           self._math("MULTIPLY_ADD", rL, 0.35, self._math("MULTIPLY", rO, 0.15)))
            e = self._math("MULTIPLY_ADD", e, FOLIAGE_STRETCH, 0.5 - 0.5 * FOLIAGE_STRETCH)
            e.node.use_clamp = True
            start = self._math("MULTIPLY_ADD", e, FOLIAGE_SPREAD, FOLIAGE_START)
            t = self._math("DIVIDE", self._math("SUBTRACT", S, start), FOLIAGE_LIFE)
            t.node.use_clamp = True
            ramps = []
            for key in ("gold", "red"):
                rn = self.node("ShaderNodeValToRGB")
                els = rn.color_ramp.elements
                pts = FOLIAGE_RAMPS[key]
                while len(els) < len(pts):
                    els.new(0.5)
                for el, (pos, h, sa, va) in zip(els, pts):
                    el.position = pos
                    el.color = (0.5 + h, sa / 2.0, va / 2.0, 1.0)
                self.link(t, rn.inputs["Fac"])
                ramps.append(rn.outputs["Color"])
            red = max(0.0, min(1.0, float(f.get("red", 0.5))))
            x = self._math("MULTIPLY_ADD", rO, 0.75, self._math("MULTIPLY", rL2, 0.25))
            pick = self._math("MULTIPLY_ADD", x, -10.0, red * 10.0 + 0.5)
            pick.node.use_clamp = True
            mix = self.node("ShaderNodeMix", data_type="RGBA")
            self.link(pick, mix.inputs[0]); self.link(ramps[0], mix.inputs[6]); self.link(ramps[1], mix.inputs[7])
            sep = self.node("ShaderNodeSeparateColor")
            self.link(mix.outputs[2], sep.inputs[0])
            # a light random mix: each leaf a touch warmer or cooler, lighter or darker
            if per_piece:
                sq = self._math("POWER", S, 0.5)
                hue = self._math("ADD", self._math("SUBTRACT", hue, 0.5), self._math("ADD", sep.outputs[0],
                                 self._math("MULTIPLY", self._math("MULTIPLY_ADD", rL3, 0.03, -0.015), sq)))
                sat = self._math("MULTIPLY", sep.outputs[1], 2.0)
                val = self._math("MULTIPLY", val, self._math("MULTIPLY", sep.outputs[2],
                                                             self._math("MULTIPLY_ADD", self._math("MULTIPLY_ADD", rL2, 0.24, -0.12), S, 2.0)))
                keep = self._math("LESS_THAN", t, FOLIAGE_DROP)
            else:
                hue = self._math("ADD", self._math("SUBTRACT", hue, 0.5), self._math("ADD", sep.outputs[0],
                                 self._math("MULTIPLY_ADD", rL3, 0.03 * season ** 0.5, -0.015 * season ** 0.5)))
                sat = self._math("MULTIPLY", sep.outputs[1], 2.0)
                val = self._math("MULTIPLY", val, self._math("MULTIPLY", sep.outputs[2],
                                                             self._math("MULTIPLY_ADD", rL2, 0.24 * season, 2.0 - 0.12 * season)))
            if per_piece:
                pass
            elif season >= 0.999:
                keep = self._const(0.0)
            else:
                keep = self._math("LESS_THAN", t, FOLIAGE_DROP)
        hs = self.node("ShaderNodeHueSaturation")
        self.link(hue, hs.inputs["Hue"])
        if sat is not None:
            self.link(sat, hs.inputs["Saturation"])
        self.link(val, hs.inputs["Value"])
        self.put(hs.inputs["Color"], base)
        col = hs.outputs["Color"]
        back = max(0.0, min(1.0, float(f.get("back", 0.3)))) if leaves else 0.0
        if back > 0:
            # the back of the leaf: lighter, a little yellower
            bm = self.node("ShaderNodeMix", data_type="RGBA", blend_type="MULTIPLY")
            self.link(self._math("MULTIPLY", geo.outputs["Backfacing"], back), bm.inputs[0])
            self.link(col, bm.inputs[6])
            bm.inputs[7].default_value = (1.35, 1.38, 1.15, 1.0)
            col = bm.outputs[2]
        inner = max(0.0, min(1.0, float(f.get("inner", 0.3))))
        if inner > 0:
            # darker in the middle of the plant (its box: Generated coordinates), lighter on the outside
            tc = self.node("ShaderNodeTexCoord")
            d = self.node("ShaderNodeVectorMath", operation="SUBTRACT")
            self.link(tc.outputs["Generated"], d.inputs[0]); d.inputs[1].default_value = (0.5, 0.5, 0.5)
            fl = self.node("ShaderNodeVectorMath", operation="MULTIPLY")
            self.link(d.outputs[0], fl.inputs[0]); fl.inputs[1].default_value = (1.0, 1.0, 0.0)
            ln = self.node("ShaderNodeVectorMath", operation="LENGTH")
            self.link(fl.outputs[0], ln.inputs[0])
            k = self._math("MULTIPLY_ADD", ln.outputs["Value"], -2.4, 1.2)
            k.node.use_clamp = True
            im = self.node("ShaderNodeMix", data_type="RGBA", blend_type="MULTIPLY")
            self.link(self._math("MULTIPLY", k, 0.6 * inner), im.inputs[0])
            self.link(col, im.inputs[6])
            im.inputs[7].default_value = (0.4, 0.42, 0.38, 1.0)
            col = im.outputs[2]
        return col, keep

    # ---- «Tessuto» (1.77.1): the tint laid by a mask; a thin cloth seen through, more opaque edge on (Layer Weight
    # Facing), the light through it with the same mix as the leaves. View: viewer.js useFabric.
    def fabric_color(self, base, f):
        col = base
        tm = self.scalar(f.get("tintMap"))
        if tm is not None:
            mx = self.node("ShaderNodeMix", data_type="RGBA", blend_type="MULTIPLY")
            self.link(tm, mx.inputs[0])
            self.put(mx.inputs[6], base)
            mx.inputs[7].default_value = (*[float(v) for v in (f.get("tint") or [1, 1, 1])[:3]], 1.0)
            col = mx.outputs[2]
        keep = None
        if f.get("mode") == "sottile":
            see = max(0.0, min(1.0, float(f.get("see", 0.6))))
            edge = max(0.0, min(1.0, float(f.get("edge", 0.6))))
            if see > 0:
                lw = self.node("ShaderNodeLayerWeight")
                lw.inputs["Blend"].default_value = 0.5
                # alpha = 1 - see × (1 - edge × facing): face on as see-through as asked, edge on more opaque
                k = self._math("MULTIPLY_ADD", lw.outputs["Facing"], -edge, 1.0)
                keep = self._math("MULTIPLY_ADD", k, -see, 1.0)
                keep.node.use_clamp = True
        return col, keep

    def foliage_translucent(self, surface, base, nrm, alpha, amount):
        """The light through the leaf: a Translucent shader with the leaf's colour mixed in (cut out like the leaf)."""
        tr = self.node("ShaderNodeBsdfTranslucent")
        self.put(tr.inputs["Color"], base)
        if nrm is not None:
            self.link(nrm, tr.inputs["Normal"])
        out = tr.outputs[0]
        if alpha is not None:
            tp = self.node("ShaderNodeBsdfTransparent")
            am = self.node("ShaderNodeMixShader")
            self.link(alpha, am.inputs["Fac"])
            self.link(tp.outputs[0], am.inputs[1])
            self.link(out, am.inputs[2])
            out = am.outputs[0]
        mx = self.node("ShaderNodeMixShader")
        mx.inputs["Fac"].default_value = 0.5 * max(0.0, min(1.0, amount))
        self.link(surface, mx.inputs[1])
        self.link(out, mx.inputs[2])
        return mx.outputs[0]

    def dispersive_glass(self, base, nrm):
        """Glass whose index of refraction depends on the colour: three glass shaders for red, green and blue
        light. Cauchy: n(λ) = A + B/λ², B from the Abbe number (n_F - n_C = (n_d - 1)/V_d), times the boost."""
        t = self.p["transmission"]
        nd = max(1.01, float(t["ior"]))
        abbe = max(5.0, float(t["abbe"]))
        boost = max(0.0, float(t["dispersionBoost"]))
        B = (nd - 1.0) / abbe / (1 / 0.4861 ** 2 - 1 / 0.6563 ** 2) * boost
        A = nd - B / 0.5893 ** 2
        rough = self.p["roughness"]["value"]
        acc = None
        for i, (lam, channel) in enumerate(spectral_bands()):
            g = self.node("ShaderNodeBsdfGlass")
            g.location = (0, -400 - 180 * i)
            g.inputs["IOR"].default_value = A + B / lam ** 2
            g.inputs["Roughness"].default_value = float(rough)
            if isinstance(base, bpy.types.NodeSocket):
                mix = self.node("ShaderNodeMix", data_type="RGBA", blend_type="MULTIPLY")
                mix.inputs["Factor"].default_value = 1.0
                self.link(base, mix.inputs[6])
                mix.inputs[7].default_value = (*channel, 1.0)
                self.link(mix.outputs[2], g.inputs["Color"])
            else:
                g.inputs["Color"].default_value = (*[channel[k] * base[k] for k in range(3)], 1.0)
            if nrm is not None:
                self.link(nrm, g.inputs["Normal"])
            if acc is None:
                acc = g.outputs[0]
            else:
                add = self.node("ShaderNodeAddShader")
                self.link(acc, add.inputs[0])
                self.link(g.outputs[0], add.inputs[1])
                acc = add.outputs[0]
        # Cycles picks the colour band again at every surface, so a ray that crosses a gem many times mixes bands:
        # the colours are right on average but come with coloured noise. "Intensità" blends the dispersive glass
        # with plain glass: the share of rays split into colours, so the effect can be dosed without the noise.
        amount = max(0.0, min(1.0, float(t.get("dispersionAmount", 0.35))))
        plain = self.node("ShaderNodeBsdfGlass")
        plain.inputs["IOR"].default_value = nd
        plain.inputs["Roughness"].default_value = float(rough)
        if isinstance(base, bpy.types.NodeSocket):
            self.link(base, plain.inputs["Color"])
        else:
            plain.inputs["Color"].default_value = (*base[:3], 1.0)
        if nrm is not None:
            self.link(nrm, plain.inputs["Normal"])
        mix = self.node("ShaderNodeMixShader")
        mix.inputs["Fac"].default_value = amount
        self.link(plain.outputs[0], mix.inputs[1])
        self.link(acc, mix.inputs[2])
        return mix.outputs[0]


def spectral_bands():
    """(wavelength µm, RGB weight) of the light bands used for dispersion. Several overlapping bands instead of pure
    red, green and blue: neighbouring colours blend like in a real spectrum, so the "fire" is natural and not
    three saturated copies. The weights of each channel add up to 1: without dispersion the glass is exactly white."""
    n = int(os.environ.get("SIMPLER_DISP_BANDS", "3"))
    if n <= 3:
        return [(0.610, [1.0, 0.0, 0.0]), (0.550, [0.0, 1.0, 0.0]), (0.465, [0.0, 0.0, 1.0])]
    lams = [0.43 + (0.67 - 0.43) * i / (n - 1) for i in range(n)]

    def g(x, mu, s):
        return math.exp(-0.5 * ((x - mu) / s) ** 2)
    # simple smooth colour-matching curves (red has a small violet lobe, like the CIE ones)
    raw = [[g(l, 0.600, 0.040) + 0.15 * g(l, 0.445, 0.020), g(l, 0.550, 0.045), g(l, 0.455, 0.030)] for l in lams]
    tot = [sum(r[c] for r in raw) for c in range(3)]
    return [(l, [r[c] / tot[c] for c in range(3)]) for l, r in zip(lams, raw)]


def _users(mat):
    from . import paint
    return [ob for ob in list(bpy.context.scene.objects) + paint.scatter_originals()
            if ob.type == "MESH" and not ob.get("simpler_internal") and not ob.get("simpler_paint_data")
            and any(s.material == mat for s in ob.material_slots)]


WELD_MOD = "Simpler Displacement · chiudi fessure"
REMESH_MOD = "Simpler Displacement · rifai maglia"
_FINAL = {"on": False}          # a final render is running: "only in the final render" displacements are on


def image_mean(name):
    """The average colour of a picture, linear (as the shader sees it), from a 32 × 32 copy; kept on the image."""
    import numpy as np
    im = bpy.data.images.get(name or "")
    if im is None:
        return None
    k = "simpler_mean"
    if im.get(k) is not None:
        return [float(v) for v in im[k]]
    cp = im.copy()
    try:
        cp.scale(32, 32)
        px = np.array(cp.pixels[:], dtype=np.float64).reshape(-1, 4)[:, :3]
    finally:
        bpy.data.images.remove(cp)
    if not len(px):
        return None
    if im.colorspace_settings.name.lower().startswith("srgb") and not im.is_float:
        px = np.where(px <= 0.04045, px / 12.92, ((px + 0.055) / 1.055) ** 2.4)
    mean = [float(v) for v in px.mean(axis=0)]
    im[k] = mean
    return mean


def _disp_settings(ob):
    """The strongest displacement settings among the materials of an object (None: no real displacement)."""
    best = None
    for sl in ob.material_slots:
        p = params_of(sl.material) if sl.material else None
        if not p:
            continue
        # (1.76.4) a zone of a terrain blending into a zone with real displacement needs the subdivision too
        # (never their voxel remesh: it would rebuild this mesh and lose the distances of the blend)
        ds = [p["displacement"]] + [dict(_merge(DEFAULTS, q.get("params") or {})["displacement"], remesh=False)
                                    for q in ((p.get("blend") or {}).get("partners") or [])]
        for d in ds:
            if not d["enabled"] or d["mode"] == "bump" or not (d["map"].get("image") or d["vector"].get("image")):
                continue
            best = _disp_best(best, d)
        # (1.76.55) «Rilievo 3D» Displacement vero of a terrain zone: only in the final render, in pixels (Finezza),
        # no weld (the zone's own mesh), only a zone with some of it (simpler_rw: not one all border or flat)
        t = p.get("tone")
        if isinstance(t, dict) and t.get("rdisp") and float(t.get("relief", 0) or 0) > 0 and ob.data is not None \
                and ob.data.get(RELIEF_RW + "_any") and sl.material.get("simpler_disp_method"):
            rp = relief_params(t)
            best = _disp_best(best, dict(DEFAULTS["displacement"], enabled=True, px=relief_disp_px(rp["f"]),
                                         maxLevel=RELIEF_DISP_LEVELS, weld=False, finalOnly=True, rl=True))
    return best


def _disp_best(best, d):
    """best merged with d: the finest detail, the smallest edge, the most levels..."""
    if best is None:
        return dict(d)
    if DETAIL_PX.get(d["detail"], 2) < DETAIL_PX.get(best["detail"], 2):
        best["detail"] = d["detail"]
    if d.get("rl"):
        best["rl"] = True
    if d.get("px") is not None:
        best["px"] = min(float(best.get("px") or DETAIL_PX.get(best["detail"], 2.0)), float(d["px"]))
    best["edgeCm"] = min(float(best["edgeCm"]), float(d["edgeCm"]))
    best["maxLevel"] = max(int(best["maxLevel"]), int(d["maxLevel"]))
    best["weld"] = best["weld"] or d["weld"]
    best["remesh"] = best["remesh"] or d["remesh"]
    best["remeshCm"] = min(float(best["remeshCm"]), float(d["remeshCm"]))
    best["finalOnly"] = best["finalOnly"] and d["finalOnly"]
    best["offscreen"] = best["offscreen"] and d["offscreen"]
    if d["space"] == "object":
        best["space"] = "object"
    return best


# ---- safety: a voxel remesh or a fine subdivision in centimetres on a large surface (a 4 km ground!) asks for
# billions of faces: Blender fills the memory and Windows stops. Estimated before, refused above these limits.
REMESH_MAX_FACES = 15e6        # ≈ 3-4 GB for the remesh in Blender
SUBDIV_MAX_FACES = 60e6        # ≈ 6-10 GB of micro-triangles in Cycles


def _area(ob):
    import numpy as np
    me = ob.data
    n = len(me.polygons)
    if not n:
        return 0.0, np.zeros(0)
    a = np.empty(n, dtype=np.float64)
    me.polygons.foreach_get("area", a)
    sc = ob.matrix_world.to_scale()
    k = abs(sc.x * sc.y * sc.z) ** (2.0 / 3.0)
    return float(a.sum() * k), a * k


def displacement_estimate(ob, d):
    """(remesh faces, subdivision faces in object space) the settings d would make on ob (0 when not used)."""
    import numpy as np
    if not d or not d["enabled"] or d["mode"] == "bump":
        return 0.0, 0.0
    area, faces = _area(ob)
    rem = area / max(1e-6, (float(d["remeshCm"]) / 100.0) ** 2) if d["remesh"] else 0.0
    sub = 0.0
    if d["space"] == "object":
        e2 = max(1e-8, (float(d["edgeCm"]) / 100.0) ** 2)
        cap = 4.0 ** int(d["maxLevel"])
        if d["remesh"]:
            sub = min(area / e2, rem * cap)
        else:
            sub = float(np.minimum(faces / e2, cap).sum())
    return rem, sub


def displacement_check(data):
    """POST material/dispcheck {name, params}: would these displacement settings be too heavy for the objects using
    the material? -> {safe, object, remeshFaces, subdivFaces, suggestRemeshCm, suggestEdgeCm}"""
    import math
    mat = _mat(data.get("name"))
    current, _adv = read_material(mat)
    d = _merge(current, data.get("params") or {})["displacement"]
    worst = {"safe": True, "object": "", "remeshFaces": 0.0, "subdivFaces": 0.0, "suggestRemeshCm": None, "suggestEdgeCm": None}
    for ob in _users(mat):
        rem, sub = displacement_estimate(ob, d)
        if rem > worst["remeshFaces"] or sub > worst["subdivFaces"]:
            area, _f = _area(ob)
            if rem > worst["remeshFaces"]:
                worst["remeshFaces"] = rem
                worst["object"] = ob.name
                worst["suggestRemeshCm"] = math.ceil(100.0 * math.sqrt(area / REMESH_MAX_FACES) * 10) / 10
            if sub > worst["subdivFaces"]:
                worst["subdivFaces"] = sub
                worst["object"] = worst["object"] or ob.name
                worst["suggestEdgeCm"] = math.ceil(100.0 * math.sqrt(area / SUBDIV_MAX_FACES) * 10) / 10
    worst["safe"] = worst["remeshFaces"] <= REMESH_MAX_FACES and worst["subdivFaces"] <= SUBDIV_MAX_FACES
    worst["remeshMax"] = REMESH_MAX_FACES
    worst["subdivMax"] = SUBDIV_MAX_FACES
    return worst


def _higher_level_elsewhere(ob, lv):
    """Another displaced object of the scene wants more than lv subdivisions (the cap is one for the scene)."""
    for o in bpy.context.scene.objects:
        if o is ob or o.type != "MESH" or o.modifiers.get(DISP_MOD) is None:
            continue
        d = _disp_settings(o)
        if d and int(d["maxLevel"]) > lv:
            return True
    return False


def _sync_displacement(objects):
    """Objects whose materials use true displacement get adaptive subdivision (Blender 5: Subdivision Surface,
    adaptive in pixels or in object space), with a Weld before it (no cracks on UV seams) and optionally a voxel
    Remesh; the others lose them. The modifiers stay first in the stack, so the waves of water etc. come after."""
    scene = bpy.context.scene
    for ob in objects:
        if ob.type != "MESH":
            continue
        d = _disp_settings(ob)
        if d is not None:
            # last safety (the editor asks first): settings that would fill the memory are not applied
            rem, sub = displacement_estimate(ob, dict(d, enabled=True))
            if d["remesh"] and rem > REMESH_MAX_FACES * 1.5:
                print(f"SIMPLER_DISP {ob.name}: remesh skipped ({rem / 1e6:.0f} M faces)", flush=True)
                d = dict(d, remesh=False)
                rem, sub = displacement_estimate(ob, dict(d, enabled=True))
            if d["space"] == "object" and sub > SUBDIV_MAX_FACES * 1.5:
                print(f"SIMPLER_DISP {ob.name}: object-space dicing too fine ({sub / 1e6:.0f} M faces): pixels", flush=True)
                d = dict(d, space="pixel")
        for name, kind, on in ((REMESH_MOD, "REMESH", bool(d and d["remesh"])), (WELD_MOD, "WELD", bool(d and d["weld"])),
                               (DISP_MOD, "SUBSURF", d is not None)):
            mod = ob.modifiers.get(name)
            if not on:
                if mod is not None:
                    ob.modifiers.remove(mod)
                continue
            if mod is None:
                mod = ob.modifiers.new(name, kind)
                mod.show_in_editmode = False
            if kind == "REMESH":
                mod.mode = "VOXEL"
                vs = max(0.002, float(d["remeshCm"]) / 100.0)
                if abs(mod.voxel_size - vs) > 1e-7:
                    mod.voxel_size = vs
            elif kind == "WELD":
                mod.merge_threshold = 0.0001
            else:
                mod.subdivision_type = "SIMPLE"
                mod.levels = 0
                mod.render_levels = 0
                mod.use_adaptive_subdivision = True
                if d["space"] == "object":
                    mod.adaptive_space = "OBJECT"
                    e = max(0.001, float(d["edgeCm"]) / 100.0)
                    if abs(mod.adaptive_object_edge_length - e) > 1e-7:
                        mod.adaptive_object_edge_length = e
                else:
                    mod.adaptive_space = "PIXEL"
                    px = float(d.get("px") or DETAIL_PX.get(d["detail"], 2.0))
                    if abs(mod.adaptive_pixel_size - px) > 1e-6:
                        mod.adaptive_pixel_size = px
                        print(f"SIMPLER_DISP {ob.name}: {px:.2f} px, up to {int(d['maxLevel'])} levels"
                              + (" (final render only)" if d["finalOnly"] else ""), flush=True)
                if d.get("rl"):
                    ob["simpler_rl_px"] = float(d["px"])      # (displacement_pass: for the size of the picture)
                elif "simpler_rl_px" in ob:
                    del ob["simpler_rl_px"]
                final_only = bool(d["finalOnly"])
                show = (not final_only) or _FINAL["on"]
                if mod.show_render != show:
                    mod.show_render = show
                ob["simpler_disp_final_only"] = 1 if final_only else 0
                # (scene settings: the highest cap among the displaced materials, fewer details off screen)
                lv = max(1, min(16, int(d["maxLevel"])))
                if scene.cycles.max_subdivisions != lv and (scene.cycles.max_subdivisions < lv or not _higher_level_elsewhere(ob, lv)):
                    scene.cycles.max_subdivisions = lv
                scene.cycles.offscreen_dicing_scale = 8.0 if d["offscreen"] else 1.0
        # the stack order: remesh, weld, subdivision first
        for i, name in enumerate(n for n in (REMESH_MOD, WELD_MOD, DISP_MOD) if ob.modifiers.get(n)):
            idx = ob.modifiers.find(name)
            if idx != i:
                try:
                    ob.modifiers.move(idx, i)
                except (AttributeError, RuntimeError):
                    pass


def sanitize_displacement():
    """After opening a project: the objects with displacement modifiers are checked again (too heavy: taken off)."""
    obs = [o for o in bpy.context.scene.objects if o.type == "MESH" and (o.modifiers.get(REMESH_MOD) or o.modifiers.get(DISP_MOD))]
    if obs:
        _sync_displacement(obs)


def displacement_pass(final, size=None):
    """Before a picture: "only in the final render" displacements are off in the path tracing of the view (only
    their bump) and on in the final render. Nothing changes (no new geometry) when nothing uses that option.
    size: the long side of the final picture (1.76.55: the true relief of «Rilievo 3D» in pixels of a 1920 picture -
    as many micro-triangles at every size, the same memory and time; in pixels of the picture its memory grew with
    the square of the size)."""
    if final and size:
        k = max(0.05, float(size) / RELIEF_DISP_REF)
        for ob in bpy.context.scene.objects:
            ref = ob.get("simpler_rl_px") if ob.type == "MESH" else None
            mod = ob.modifiers.get(DISP_MOD) if ref else None
            if mod is not None and abs(mod.adaptive_pixel_size - float(ref) * k) > 1e-4:
                mod.adaptive_pixel_size = float(ref) * k
                print(f"SIMPLER_DISP {ob.name}: {float(ref) * k:.2f} px for a picture of {int(size)}", flush=True)
    if _FINAL["on"] == bool(final):
        return
    _FINAL["on"] = bool(final)
    for mat in bpy.data.materials:
        if mat.get("simpler_disp_final_only"):
            want = mat.get("simpler_disp_method", "BOTH") if final else "BUMP"
            if mat.displacement_method != want:
                mat.displacement_method = want
    for ob in bpy.context.scene.objects:
        if ob.get("simpler_disp_final_only"):
            mod = ob.modifiers.get(DISP_MOD)
            if mod is not None and mod.show_render != bool(final):
                mod.show_render = bool(final)


def _keep_original(mat):
    """First edit of a material that was not made in Simpler: a hidden copy of the original stays in the project."""
    if mat.get(PARAMS_KEY) or mat.get(BACKUP_KEY):
        return
    orig = mat.copy()
    orig.name = "·orig·" + mat.name
    orig[BACKUP_TAG] = 1
    orig.use_fake_user = True
    mat[BACKUP_KEY] = orig.name


def apply(mat, params, keep_original=True):
    """Builds the material from its channels and stores them in it."""
    from . import proxies
    if keep_original:
        _keep_original(mat)
    p = _merge(DEFAULTS, params)
    p["version"] = VERSION
    mc = p.get("macro")
    if isinstance(mc, dict) and (mc.get("map") or {}).get("image"):
        # (1.76.6) the average colours the large texture is measured against: again when a picture changes
        det = ((p["color"].get("map") or {}).get("image")) or ""
        key = mc["map"]["image"] + "|" + det
        if mc.get("meanOf") != key:
            mc["mean"] = image_mean(mc["map"]["image"]) or [0.5, 0.5, 0.5]
            mc["detailMean"] = image_mean(det) or mc["mean"]
            mc["meanOf"] = key
    if mat.node_tree is None:
        mat.use_nodes = True
    _Builder(mat, p).build()
    mat[PARAMS_KEY] = json.dumps(p)
    if (p.get("interior") or {}).get("enabled"):
        interior_pass([mat])
    if p["uv"].get("perPiece"):
        ensure_pieces(mat)
    proxies.apply(proxies.CURRENT["px"], [mat.node_tree])     # the previews keep showing reduced copies of the textures
    _sync_displacement(_users(mat))
    return p


PENDING_KEY = "simpler_build_pending"     # (1.76.56) params stored, node tree not made yet (flush_pending)


def apply_deferred(mat, params):
    """(1.76.56, Luca: «ogni azione … innesca un'attesa infinita») The params of a material stored at once, its node
    tree made only when Cycles needs it (flush_pending: the path tracing of the view, the final render, an export).
    The terrain's six materials were made again at every edit of one of them - each holds the others in its border
    blend, thousands of nodes, 25-31 s per click - also in SmartView, where nothing draws them: the real-time view
    reads the params (materials.realtime_params), never the nodes. Ten edits in a row: made once, as the last one."""
    p = _merge(DEFAULTS, params)
    p["version"] = VERSION
    mc = p.get("macro")
    if isinstance(mc, dict) and (mc.get("map") or {}).get("image"):
        det = ((p["color"].get("map") or {}).get("image")) or ""
        key = mc["map"]["image"] + "|" + det
        if mc.get("meanOf") != key:
            mc["mean"] = image_mean(mc["map"]["image"]) or [0.5, 0.5, 0.5]
            mc["detailMean"] = image_mean(det) or mc["mean"]
            mc["meanOf"] = key
    mat[PARAMS_KEY] = json.dumps(p)
    mat[PENDING_KEY] = 1
    # (the colour of the solid view and of the thumbnails, as build sets it)
    mat.diffuse_color = (*[float(v) for v in p["color"]["tint"][:3]], 1.0)
    return p


def flush_pending(mats=None):
    """(1.76.56) The node trees left for later (apply_deferred) made now, before Cycles draws them. Nothing pending:
    a loop over the materials, no cost. -> how many were made."""
    from . import proxies
    # (only those drawn: a copy kept for Ctrl+Z waits until it is put back - Luca's log: 7 made, one an old copy)
    todo = [m for m in (mats if mats is not None else bpy.data.materials)
            if m is not None and m.get(PENDING_KEY) and m.users - int(m.use_fake_user) > 0]
    if not todo:
        return 0
    t0 = time.time()
    for m in todo:
        p = params_of(m)
        del m[PENDING_KEY]
        if p is None:
            continue
        if m.node_tree is None:
            m.use_nodes = True
        _Builder(m, _merge(DEFAULTS, p)).build()
        proxies.apply(proxies.CURRENT["px"], [m.node_tree])
    users = []
    for m in todo:
        users += _users(m)
    _sync_displacement(users)
    print(f"SIMPLER_MAT {len(todo)} materials made for Cycles (left for later) in {time.time() - t0:.1f} s: "
          + ", ".join(m.name for m in todo[:8]), flush=True)
    return len(todo)


def update_blend_values(mat, params):
    """(1.76.50, Luca: «Sfumatura dei bordi» 28 s) A terrain material whose border blend changes only in its numbers
    (how wide, how irregular): those numbers set in place on the nodes edge_blend named, no tree made again (a
    material of a terrain is hundreds of nodes, and Blender makes each one slower the bigger the tree). -> False when
    the tree is not the same shape (then it is made again as before)."""
    nt = mat.node_tree
    b = (params or {}).get("blend") or {}
    parts = b.get("partners") or []
    if nt is None or not parts or float(b.get("width") or 0) <= 0:
        return False
    n0 = nt.nodes.get("simpler_eb_noise")
    if n0 is None:
        return False
    W = max(0.05, float(b.get("width") or 1.0))
    irr = max(0.0, min(1.0, float(b.get("irregular", 0.6))))
    plan = []
    for i, part in enumerate(parts):
        t = nt.nodes.get(f"simpler_eb_t{i}")
        nz = nt.nodes.get(f"simpler_eb_nz{i}")
        Wp = max(0.05, float(part.get("width") or W))
        ni = nt.nodes.get(f"simpler_eb_noise{i}")
        if t is None or nz is None or (abs(Wp - W) > 1e-6) != (ni is not None):
            return False
        plan.append((t, nz, ni, Wp, 1.0 if float(part.get("sign", 1)) >= 0 else -1.0))
    if nt.nodes.get(f"simpler_eb_t{len(parts)}") is not None:
        return False                     # (more partners in the tree than now)
    n0.inputs["Scale"].default_value = 1.0 / max(0.3, W)
    for t, nz, ni, Wp, sign in plan:
        t.inputs[1].default_value = -0.5 / Wp
        nz.inputs[1].default_value = sign * irr
        nz.inputs[2].default_value = -0.5 * sign * irr
        if ni is not None:
            ni.inputs["Scale"].default_value = 1.0 / max(0.3, Wp)
    store_params(mat, params)
    return True


def store_params(mat, params):
    """The parameters a material was made with (or set in place to)."""
    p = _merge(DEFAULTS, params)
    p["version"] = VERSION
    mat[PARAMS_KEY] = json.dumps(p)


def update_relief_values(mat, params):
    """(1.76.53) A terrain material whose «Rilievo 3D» changes only in its numbers (depth, size, detail, where,
    orientation; the thickness of the layers): set on its simpler_rl_* value nodes, the tree not made again. -> False
    when the tree has none of them (made before: then it is made again once)."""
    nt = mat.node_tree
    t = (params or {}).get("tone")
    if nt is None or not isinstance(t, dict):
        return False
    rp = relief_params(t)
    ks = ("T", "s", "k", "w", "d", "o") + (("a",) if rp["disp"] else ()) + (("ms", "mr") if rp["map"] or rp["cmap"] else ()) \
        + (("ca",) if rp["cmap"] else ())
    nodes = {k: nt.nodes.get("simpler_rl_" + k) for k in ks}
    if any(n is None for n in nodes.values()):
        return False
    for k, n in nodes.items():
        n.outputs[0].default_value = float(rp[k])
    return True


def restore_original(mat):
    """Back to the material as it was imported (the hidden copy), or to the defaults."""
    from . import proxies
    name = mat.get(BACKUP_KEY)
    orig = bpy.data.materials.get(name) if name else None
    if orig is None:
        if mat.get(PARAMS_KEY):
            del mat[PARAMS_KEY]
        return
    users = _users(mat)
    fresh = orig.copy()
    fresh.use_fake_user = False
    if BACKUP_TAG in fresh:
        del fresh[BACKUP_TAG]
    keep = mat.name
    mat.user_remap(fresh)
    mat.name = keep + "·old"
    fresh.name = keep
    fresh[BACKUP_KEY] = orig.name
    if mat.get("simpler_rain_drops"):                  # («Con la pioggia» is a choice of the user, not of the material)
        fresh["simpler_rain_drops"] = mat["simpler_rain_drops"]
    bpy.data.materials.remove(mat)
    proxies.apply(proxies.CURRENT["px"])
    _sync_displacement(users)


# ---------------------------------------------------------------- API

def _image_info(name):
    im = bpy.data.images.get(name) if name else None
    if im is None:
        return None
    from . import proxies
    path = proxies.source_of(im) if im.source in ("FILE", "TILED") else None
    size = proxies.dims(path) if path else None        # from the file header (no decoding)
    return {"name": im.name, "file": os.path.basename(path or im.filepath or im.name), "path": path or "",
            "width": int(size[0]) if size else 0, "height": int(size[1]) if size else 0,
            "packed": im.packed_file is not None, "missing": bool(path is None and im.packed_file is None)}


def editor_json(data):
    mat = _mat(data.get("name"))
    p, advanced = read_material(mat)
    images = {}
    for m in _maps(p):
        if m.get("image") and m["image"] not in images:
            images[m["image"]] = _image_info(m["image"])
    has_uv = None
    flat = False
    if data.get("id"):
        ob = find(data["id"], required=False)
        if ob is not None and ob.type == "MESH":
            has_uv = len(ob.data.uv_layers) > 0
            # a sheet without thickness (a pane, a plane): as solid glass it refracts into a block that never ends
            # and looks like a mirror - the editor suggests the thin wall
            d = sorted(ob.dimensions)
            flat = d[2] > 0 and (d[0] < 0.01 * d[2] or d[0] < 0.002)
    from . import materials
    materials.relink(mat)                       # (a copy of a material of Simpler overwritten under another name)
    lib = materials.library_entry(mat.get("simpler_preset")) if mat.get("simpler_preset") else None
    return {"name": mat.name, "params": p, "advanced": advanced, "simpler": bool(mat.get(PARAMS_KEY)), "hasUv": has_uv, "flat": flat,
            "library": lib, "dirty": bool(mat.get("simpler_lib_dirty")),
            "hasOriginal": bool(mat.get(BACKUP_KEY)), "users": len(_users(mat)), "images": images,
            "dispersive": is_dispersive(mat), "glassPresets": {k: list(v) for k, v in GLASS_PRESETS.items()},
            "water": _water_info(mat), "volumetric": __import__("simpler.volumetric", fromlist=["x"]).editor_info(mat),
            "rainDrops": str(mat.get("simpler_rain_drops") or "auto")}


def _water_info(mat):
    from . import water
    return water.editor_info(mat)


CS_OF = "simpler_cs_of"      # on a copy of an image made only to read it in the other colour space


def _used_elsewhere(im, tree):
    """Is the image in an image node of another material?"""
    for m in bpy.data.materials:
        nt = m.node_tree
        if nt is None or nt == tree:
            continue
        for n in nt.nodes:
            if n.type == "TEX_IMAGE" and n.image == im:
                return True
    return False


def _colorspace_variant(im, want):
    """The copy of the image read in the colour space wanted (made once, then reused)."""
    for other in bpy.data.images:
        if other.get(CS_OF) == im.name and other.colorspace_settings.name == want:
            return other
    c = im.copy()
    c[CS_OF] = im.name
    c.colorspace_settings.name = want
    c.name = im.name + (" ·dati" if want == "Non-Color" else " ·colore")
    return c


def _maps(p):
    return [p["color"]["map"], p["roughness"]["map"], p["metallic"]["map"], p["normal"]["map"], p["normal"]["bumpMap"],
            p["emission"]["map"], p["opacity"]["map"], p["displacement"]["map"], p["fabric"]["fuzzMap"], p["fabric"]["tintMap"],
            (p.get("interior") or {}).get("map") or {}]


def _load_files(params):
    """Maps given as files ("file": path) become images of the project."""
    def walk(d):
        if isinstance(d, dict):
            pack = bool(d.pop("pack", False))      # a generated map of an embedded one: embedded too
            if "file" in d and isinstance(d.get("file"), str) and d["file"]:
                path = d.pop("file")
                if not os.path.isfile(path):
                    raise ApiError(tr("File non trovato: {0}", path))
                im = bpy.data.images.load(path, check_existing=True)
                if pack and not im.packed_file:
                    im.pack()
                d["image"] = im.name
            for v in d.values():
                walk(v)
    walk(params)
    return params


def upgrade_alpha():
    """Simpler materials saved before the cut-out existed and using a see-through texture: rebuilt once with it."""
    for mat in list(bpy.data.materials):
        raw = mat.get(PARAMS_KEY)
        if not raw or '"cutout"' in raw:
            continue
        try:
            stored = json.loads(raw)
        except ValueError:
            continue
        o = stored.get("opacity") or {}
        if o.get("useAlpha") or (o.get("map") or {}).get("image"):
            try:
                apply(mat, _merge(DEFAULTS, stored), keep_original=False)
            except Exception:
                pass


def upgrade_graded():
    """Materials cut at 50% on a graded opacity map (built before 1.14.4): rebuilt once with soft alpha."""
    n = 0
    for mat in list(bpy.data.materials):
        raw = mat.get(PARAMS_KEY)
        if not raw or not mat.users or mat.get("simpler_graded_ok"):
            continue
        try:
            stored = json.loads(raw)
        except ValueError:
            continue
        o = stored.get("opacity") or {}
        if not o.get("cutout", True):
            continue
        if o.get("useAlpha"):
            ref = (((stored.get("color") or {}).get("map") or {}).get("image"), "A")
        else:
            ref = ((o.get("map") or {}).get("image"), (o.get("map") or {}).get("channel") or "")
        if ref[0] and graded_opacity(*ref):
            try:
                apply(mat, _merge(DEFAULTS, stored), keep_original=False)
                n += 1
            except Exception:
                pass
        mat["simpler_graded_ok"] = 1
    return n


def upgrade_uv_offset():
    """Materials built before 1.32.1 with a UV offset: Cycles moved them by «offset» repeats, the view by
    «offset × scale» (a plate centred in the view came out cut in two in the path tracing). Before 1.36.6, Box in
    world space: coordinates not turned with the object (smeared on turned objects). Rebuilt once."""
    n = 0
    for mat in list(bpy.data.materials):
        raw = mat.get(PARAMS_KEY)
        if not raw or not mat.users:
            continue
        try:
            stored = json.loads(raw)
        except ValueError:
            continue
        if int(stored.get("version", 1)) >= VERSION:
            continue
        uv = stored.get("uv") or {}
        off = uv.get("offset") or [0.0, 0.0]
        ver = int(stored.get("version", 1))
        if (ver < 2 and uv.get("mode", "uv") == "uv" and any(abs(float(v)) > 1e-9 for v in off)) \
                or (uv.get("mode") == "box" and uv.get("space") == "world"):
            try:
                apply(mat, _merge(DEFAULTS, stored), keep_original=False)
                n += 1
                continue
            except Exception:
                pass
        stored["version"] = VERSION
        mat[PARAMS_KEY] = json.dumps(stored)
    return n


def graded_opacity(name, channel=""):
    """Is this opacity map made of shades (frosted or engraved glass, a dirty pane, a lamp shade) rather than of
    full and empty (leaves, grids)? Cut at 50% such a map turns into salt and pepper finer than the pixels: opaque
    and empty texels side by side that sparkle as white dots on lamp shades and salt shakers, with any number of
    samples. On a map 512 px wide (fine patterns average to grey too: soft alpha is right for them as well): more
    than 4% of it between 0.3 and 0.7 = graded. Cached on the image."""
    im = bpy.data.images.get(name) if name else None
    if im is None:
        return False
    key = "simpler_graded_" + (channel or "L")
    if key in im:
        return bool(im[key])
    graded = False
    tmp = None
    try:
        import numpy as np
        w, h = im.size[:]
        if w * h > 0:
            src = im
            if w * h > 2048 * 2048 and (im.packed_file or im.filepath):
                tmp = im.copy()                 # (a copy of a generated image has no pixels: those are read whole)
                s = 512.0 / max(w, h)
                tmp.scale(max(1, int(w * s)), max(1, int(h * s)))
                src = tmp
            tw, th = src.size[:]
            nc = src.channels
            px = np.empty(tw * th * nc, dtype=np.float32)
            src.pixels.foreach_get(px)
            px = px.reshape(-1, nc)
            if nc == 1:
                px = np.concatenate([px.repeat(3, 1), np.ones((px.shape[0], 1), np.float32)], 1)
            elif nc == 2:
                px = np.concatenate([px[:, :1].repeat(3, 1), px[:, 1:2]], 1)
            elif nc == 3:
                px = np.concatenate([px, np.ones((px.shape[0], 1), np.float32)], 1)
            px = px[::max(1, px.shape[0] // 262144)]
            if channel == "A":
                v = px[:, 3]
            elif channel in ("R", "G", "B"):
                v = px[:, "RGB".index(channel)]
            else:
                v = px[:, :3] @ np.array([0.2126, 0.7152, 0.0722], dtype=np.float32)
            graded = bool(((v > 0.3) & (v < 0.7)).mean() > 0.04)
    except Exception:
        graded = False
    finally:
        if tmp is not None:
            bpy.data.images.remove(tmp)
    try:
        im[key] = int(graded)
    except Exception:
        pass
    return graded


def _has_transparency(name):
    """True when the image has an alpha channel that is not all opaque (checked on at most ~64k pixels)."""
    im = bpy.data.images.get(name)
    if im is None or im.channels < 4:
        return False
    try:
        import numpy as np
        w, h = im.size[:]
        if w * h == 0:
            return False
        px = np.empty(w * h * 4, dtype=np.float32)
        im.pixels.foreach_get(px)
        a = px[3::4]
        step = max(1, a.size // 65536)
        return bool((a[::step] < 0.98).any())
    except Exception:
        return False


def mark_draft(mat):
    """A library material edited on no object of the scene is a draft: opened again, it is the one (materials.py)."""
    from .materials import DRAFT_KEY, PRESET_KEY
    if not mat.get(PRESET_KEY):
        return
    if _users(mat):
        if DRAFT_KEY in mat:
            del mat[DRAFT_KEY]
    else:
        mat[DRAFT_KEY] = 1


def edit(data):
    """POST /api/material/edit {name, params (only what changes), convert}"""
    mat = _mat(data.get("name"))
    mark_draft(mat)
    current, advanced = read_material(mat)
    if advanced and not data.get("convert"):
        raise ApiError(tr("Materiale avanzato: convertilo prima in materiale Simpler"))
    patch = _load_files(copy.deepcopy(data.get("params") or {}))
    new_img = ((patch.get("color") or {}).get("map") or {}).get("image")
    if new_img and new_img != current["color"]["map"].get("image") and "opacity" not in patch and _has_transparency(new_img):
        # a colour texture with see-through parts (leaves, grids, decals): use its alpha, as the real-time view does
        patch["opacity"] = {"useAlpha": True}
    # a glass cannot be a metal: in the Principled BSDF the metal wins over the transparency (a window with a
    # "metalness" map stays a mirror at 100% transparency). Turning the transparency on takes the metal away.
    metal_off = False
    tw = (patch.get("transmission") or {}).get("weight")
    if tw is not None and float(tw) > 0 and "metallic" not in patch and (
            float(current["metallic"].get("value") or 0) > 0 or current["metallic"]["map"].get("image")):
        patch["metallic"] = {"value": 0.0, "map": _map()}
        metal_off = True
    merged = _merge(current, patch)
    if not data.get("_centre"):
        def obs_of():
            ob = find(data["id"], required=False) if data.get("id") else None
            return [ob] if ob is not None and ob.type == "MESH" else _scene_users(mat)
        try:
            _auto_centre(mat, current, merged, patch, obs_of)
        except Exception as e:                  # (centring is a help: never in the way of the change itself)
            print("SIMPLER_AUTOCENTRE", mat.name, e, flush=True)
    # an emission switched on with a black colour filter emits nothing: imported materials (FBX, glTF) carry a black
    # emission colour when they do not glow - turning «Emette luce» on kept it, and the light stayed off
    # (1.78.4) only when this change is the one switching the light on: any other change (the season of a leaf) left
    # the black emission of an imported material as it was - it turned it into a white glow
    em = merged.get("emission") or {}
    pe = patch.get("emission") or {}
    if float(em.get("nits") or 0) > 0 and sum(float(c) for c in (em.get("color") or [1, 1, 1])[:3]) < 0.003 \
            and "color" not in pe and ("nits" in pe or "on" in pe):
        em["color"] = [1.0, 1.0, 1.0]
    import time as _t
    t0 = _t.time()
    p = apply(mat, merged)
    t1 = _t.time()
    if mat.get("simpler_preset"):
        mat["simpler_lib_dirty"] = 1             # changed since it came from (or was saved to) the library
    from . import render
    if render.STATE.caustics:
        render.apply_caustics(True)       # dispersion on/off changes who casts sharp caustics
    t2 = _t.time()
    if t2 - t0 > 1.0:
        # (1.78.3) an edit that waits: which part (a rare 4-5 s seen in the long checks, never alone)
        print(f"SIMPLER_SLOWEDIT {mat.name}: build {t1 - t0:.2f} s, caustics {t2 - t1:.2f} s ({bool(render.STATE.caustics)}), "
              f"nodes {len(mat.node_tree.nodes) if mat.node_tree else 0}", flush=True)
    return {"name": mat.name, "params": p, "dispersive": is_dispersive(mat), "metalRemoved": metal_off}


CENTRE_KEYS = ("mode", "space", "sizeCm", "scale", "stretch", "rotation", "perPiece")
PIECE_CENTRE = "_simpler_pc"      # face corner: middle of the separate piece it belongs to (object space)
PIECE_UV = "_simpler_puv"         # face corner: middle of the UV of that piece
PIECE_SIG = "simpler_piece_sig"   # on the mesh: what the attributes were computed for


def piece_attributes(me, force=False):
    """The separate pieces of a mesh and the middle of each, written on every face corner. A piece is a group of faces
    with the same material that touch (by position: vertices split at seams or hard edges still join), so two lamps
    in one object, or the two lenses of a lamp, are two pieces. The real-time view finds the same pieces in its own
    copy of the geometry (viewer.js piecesOf). Done once per mesh (shared by its instances) and again when the
    geometry changes."""
    import numpy as np
    if me is None or not len(me.polygons):
        return False
    sig = f"{len(me.vertices)}:{len(me.polygons)}:{len(me.loops)}"
    if not force and me.get(PIECE_SIG) == sig and PIECE_CENTRE in me.attributes:
        return False
    nv, nf, nl = len(me.vertices), len(me.polygons), len(me.loops)
    co = np.empty(nv * 3); me.vertices.foreach_get("co", co); co = co.reshape(-1, 3)
    vi = np.empty(nl, dtype=np.int64); me.loops.foreach_get("vertex_index", vi)
    ls = np.empty(nf, dtype=np.int64); me.polygons.foreach_get("loop_start", ls)
    lt = np.empty(nf, dtype=np.int64); me.polygons.foreach_get("loop_total", lt)
    mi = np.empty(nf, dtype=np.int64); me.polygons.foreach_get("material_index", mi)
    face_of = np.repeat(np.arange(nf), lt)
    # a node per (position, material): corners at the same place with the same material are the same node
    q = np.round(co[vi] * 1e4).astype(np.int64)
    keys = np.concatenate([q, mi[face_of][:, None]], axis=1)
    _u, node = np.unique(keys, axis=0, return_inverse=True)
    node = node.ravel()
    parent = list(range(int(node.max()) + 1))

    def root(a):
        while parent[a] != a:
            parent[a] = parent[parent[a]]
            a = parent[a]
        return a
    first = node[ls]
    for c in range(nl):                      # every corner joins the first corner of its face
        a, b = root(int(node[c])), root(int(first[face_of[c]]))
        if a != b:
            parent[a] = b
    comp = np.array([root(int(n)) for n in node])
    _c, comp = np.unique(comp, return_inverse=True)
    comp = comp.ravel()
    k = int(comp.max()) + 1
    pos = co[vi]
    lo = np.full((k, 3), np.inf); hi = np.full((k, 3), -np.inf)
    np.minimum.at(lo, comp, pos); np.maximum.at(hi, comp, pos)
    centre = ((lo + hi) / 2)[comp]
    a = me.attributes.get(PIECE_CENTRE)
    if a is not None and (a.domain != "CORNER" or a.data_type != "FLOAT_VECTOR"):
        me.attributes.remove(a); a = None
    if a is None:
        a = me.attributes.new(PIECE_CENTRE, "FLOAT_VECTOR", "CORNER")
    a.data.foreach_set("vector", centre.astype(np.float32).ravel())
    lay = me.uv_layers.active
    if lay is not None:
        uv = np.empty(nl * 2); lay.data.foreach_get("uv", uv); uv = uv.reshape(-1, 2)
        lo2 = np.full((k, 2), np.inf); hi2 = np.full((k, 2), -np.inf)
        np.minimum.at(lo2, comp, uv); np.maximum.at(hi2, comp, uv)
        cuv = ((lo2 + hi2) / 2)[comp]
        b = me.attributes.get(PIECE_UV)
        if b is not None and (b.domain != "CORNER" or b.data_type != "FLOAT2"):
            me.attributes.remove(b); b = None
        if b is None:
            b = me.attributes.new(PIECE_UV, "FLOAT2", "CORNER")
        b.data.foreach_set("vector", cuv.astype(np.float32).ravel())
    me[PIECE_SIG] = sig
    return True


def ensure_pieces(mat):
    """The meshes using a material with «Centra ogni pezzo» have their pieces (piece_attributes)."""
    p = params_of(mat)
    if not p or not (p.get("uv") or {}).get("perPiece"):
        return 0
    n = 0
    for me in {o.data for o in _users(mat) if o.type == "MESH" and o.data is not None}:
        try:
            n += bool(piece_attributes(me))
        except Exception as e:
            print("SIMPLER_PIECES", me.name, e, flush=True)
    return n


def _centre_point(uv, mat, obs):
    if uv.get("perPiece"):
        # every piece measured from its own middle: the middle is 0 (UV and projections alike)
        return [0.0, 0.0] if (uv["mode"] if uv["mode"] in UV_MODES else "uv") == "uv" else [0.0, 0.0, 0.0]
    return _centre_point_of(uv, mat, obs)


def _centre_point_of(uv, mat, obs):
    """The middle of the part of the objects with this material (their faces with it; all, if none), in the space the
    projection reads: UV coordinates in UV mode, else world or object coordinates (at the object's size)."""
    import numpy as np
    mode = uv["mode"] if uv["mode"] in UV_MODES else "uv"
    lo = hi = None
    for ob in obs:
        if ob.type != "MESH" or ob.data is None or not len(ob.data.polygons):
            continue
        me = ob.data
        slots = [i for i, sl in enumerate(ob.material_slots) if sl.material == mat]
        nf = len(me.polygons)
        mi = np.empty(nf, dtype=np.int32)
        me.polygons.foreach_get("material_index", mi)
        faces = np.isin(mi, slots) if slots else np.ones(nf, dtype=bool)
        if not faces.any():
            faces[:] = True
        lt = np.empty(nf, dtype=np.int64)
        me.polygons.foreach_get("loop_total", lt)
        keep = np.repeat(faces, lt)
        if mode == "uv":
            lay = me.uv_layers.active
            if lay is None:
                continue
            co = np.empty(len(me.loops) * 2)
            lay.data.foreach_get("uv", co)
            pts = co.reshape(-1, 2)[keep]
        else:
            co = np.empty(len(me.vertices) * 3)
            me.vertices.foreach_get("co", co)
            vi = np.empty(len(me.loops), dtype=np.int64)
            me.loops.foreach_get("vertex_index", vi)
            pts = co.reshape(-1, 3)[np.unique(vi[keep])]
            if uv.get("space") == "world":
                m = np.array(ob.matrix_world)
                pts = pts @ m[:3, :3].T + m[:3, 3]
                if mode == "box":                  # (turned back by the object's rotation, as coords())
                    r = np.array(ob.matrix_world.to_quaternion().to_matrix())
                    pts = pts @ r
            else:
                pts = pts * np.array(ob.scale)     # object coordinates at the object's real size (as coords())
        if not len(pts):
            continue
        a, b = pts.min(axis=0), pts.max(axis=0)
        lo = a if lo is None else np.minimum(lo, a)
        hi = b if hi is None else np.maximum(hi, b)
    if lo is None:
        return None
    return [round(float(v), 6) for v in (lo + hi) / 2]


def _centre_offset(uv, point):
    """The offset that puts the middle of a repeat of the picture on the point (the same coordinates as Cycles'
    Mapping node and the view: t = R(S·p) + L)."""
    mode = uv["mode"] if uv["mode"] in UV_MODES else "uv"
    rot = math.radians(float(uv.get("rotation") or 0.0))
    c_, s_ = math.cos(rot), math.sin(rot)
    st = list(uv.get("stretch") or [1.0, 1.0]) + [1.0, 1.0]
    wrap = lambda x: x - math.floor(x + 0.5)            # into -0.5 .. 0.5
    if mode == "uv":
        k = max(1e-4, float(uv["scale"]))
        sc = (k * float(st[0]), k * float(st[1]))
        ax, ay = point[0] * sc[0], point[1] * sc[1]
        a = (c_ * ax - s_ * ay, s_ * ax + c_ * ay)
        # L = -offset × scale (coords()): the middle of a repeat (0.5) on the point
        off = [-wrap(0.5 - a[0]) / sc[0], -wrap(0.5 - a[1]) / sc[1]]
    else:
        k = 100.0 / max(0.1, float(uv["sizeCm"]))
        b = (point[0] * k * float(st[0]), point[1] * k * float(st[1]), point[2] * k)
        a = (c_ * b[0] - s_ * b[1], s_ * b[0] + c_ * b[1], b[2])
        if mode in ("cylinder", "sphere"):
            off = [-a[0], -a[1], -a[2]]             # the projection around the middle of the object
        else:
            off = [wrap(0.5 - a[0]), wrap(0.5 - a[1]), wrap(0.5 - a[2])]
    return [round(float(v), 5) for v in off]


def _scene_users(mat):
    return [ob for ob in bpy.context.scene.objects
            if ob.type == "MESH" and not ob.get("simpler_internal") and not ob.get("simpler_paint_data")
            and not ob.get("simpler_twin") and any(s.material == mat for s in ob.material_slots)]


AUTO_CENTRE_MAX = 50        # objects: beyond (a crowd of copies, distributions) the texture is left where it is


def _auto_centre(mat, current, merged, patch, obs_of):
    """The texture follows the middle of the object by itself (uv.centerAt: the point it is centred on):
    - a picture put on a material whose texture was never moved (offset 0) or is centred: centred on the object;
    - scale, stretch, rotation changed on a centred texture: centred again on the same point;
    - projection or space changed: the point is found again on the objects;
    - the offset moved by hand: no longer centred (it stays where it was put)."""
    uvp = patch.get("uv") or {}
    uv = merged["uv"]
    if "offset" in uvp:
        uv["centerAt"] = None
        return
    at = uv.get("centerAt")
    zero = all(abs(float(v)) < 1e-9 for v in (current["uv"].get("offset") or [0, 0]))
    before = {m.get("image") for m in _maps(current) if m.get("image")}
    new_pic = any(m.get("image") and m.get("image") not in before for m in _maps(merged))
    if new_pic and (zero or at):
        at = None
    elif "perPiece" in uvp and bool(uvp["perPiece"]) != bool(current["uv"].get("perPiece")):
        at = None                            # (switched on: centred on every piece; off: on the object again)
    elif at and any(k in uvp and uvp[k] != current["uv"].get(k) for k in ("mode", "space")):
        at = None
    elif not (at and any(k in uvp for k in CENTRE_KEYS)):
        return
    if at is None and uv.get("perPiece"):
        at = _centre_point(uv, mat, [])
    if at is None:
        obs = obs_of()
        if not obs or len(obs) > AUTO_CENTRE_MAX:
            uv["centerAt"] = None
            return
        at = _centre_point(uv, mat, obs)
        if at is None:
            return
    uv["centerAt"] = at
    uv["offset"] = _centre_offset(uv, at)


def centre_on(mat, obs):
    """After a material of the library is put on objects: its texture centred on them (as _auto_centre), when it
    was never moved by hand. Not a change of the material (no «changed since the library»)."""
    p = params_of(mat)
    if not p or not any(m.get("image") for m in _maps(_merge(DEFAULTS, p))):
        return False
    p = _merge(DEFAULTS, p)
    uv = p["uv"]
    zero = all(abs(float(v)) < 1e-9 for v in (uv.get("offset") or [0, 0]))
    if not (zero or uv.get("centerAt")):
        return False
    obs = [o for o in obs if o.type == "MESH" and not o.get("simpler_paint_model")] or obs
    users = _scene_users(mat) or obs
    if len(users) > AUTO_CENTRE_MAX:
        return False
    at = _centre_point(uv, mat, users)
    if at is None:
        return False
    off = _centre_offset(uv, at)
    if uv.get("centerAt") == at and list(uv.get("offset") or []) == off:
        return False
    uv["centerAt"], uv["offset"] = at, off
    dirty = mat.get("simpler_lib_dirty")
    apply(mat, p)
    if not dirty and "simpler_lib_dirty" in mat:
        del mat["simpler_lib_dirty"]
    return True


def center(data):
    """POST /api/material/center {name, id}: the texture centred on the selected object - the middle of the picture
    on the middle of the part of the object with this material (its faces with it; all, if none). It only sets the
    offset: UV = middle of its UV, Triplanare and Piana = middle of the object in the projection (world or object
    space, as set), Cilindro and Sfera = the projection around the middle of the object. It stays centred when the
    scale or the rotation change (uv.centerAt)."""
    mat = _mat(data.get("name"))
    ob = find(data.get("id"))
    if ob.type != "MESH" or ob.data is None:
        raise ApiError(tr("Seleziona un oggetto con questo materiale"))
    p = _merge(DEFAULTS, params_of(mat) or read_material(mat)[0])
    uv = p["uv"]
    at = _centre_point(uv, mat, [ob])
    if at is None:
        raise ApiError(tr("Questo oggetto non ha coordinate UV: scegli Box per vedere la texture."))
    return edit({"name": mat.name, "params": {"uv": {"offset": _centre_offset(uv, at), "centerAt": at}}, "_centre": True})


def fit(data):
    """POST /api/material/fit {name, id?}: one picture, whole, over the part of the object with this material. The
    model's own UV are not to be trusted for that (a stained glass window had its panes unwrapped one by one, in
    strips: the picture came out in streaks, 1.67.5): the faces with this material get new UV, a flat projection on
    the plane they lie in, seen from the side they face, up = the object's up, filling the square 0..1 once; the
    texture is set to 1 repeat, not moved. Only those faces change (the other materials keep their UV); undo
    restores them (step of kind file).
    Without id (material opened from the list of the scene, 1.67.8): every object with this material, each fitted to
    its own shape (objects sharing one mesh: once)."""
    mat = _mat(data.get("name"))
    _FIT_MESHES.clear()
    if data.get("ids"):
        # the pieces chosen (the selection): one picture over all of them together
        group, seen = [], set()
        for oid in data["ids"]:
            o = find(oid, required=False)
            if o is None:
                continue
            for x in [o] + list(o.children_recursive):
                if x.type == "MESH" and x.data is not None and len(x.data.polygons) and x.data.as_pointer() not in seen \
                        and any(sl.material == mat for sl in x.material_slots) and not x.get("simpler_twin"):
                    seen.add(x.data.as_pointer())
                    group.append(x)
        if not group:
            raise ApiError(tr("Seleziona un oggetto con questo materiale"))
        _fit_objects(group, mat)
        try:
            from . import rain
            rain.touch()
        except Exception:
            pass
        out = edit({"name": mat.name, "params": {"uv": {"mode": "uv", "scale": 1.0, "stretch": [1.0, 1.0], "rotation": 0.0,
                                                        "perPiece": False, "antitile": False, "offset": [0.0, 0.0],
                                                        "centerAt": None}}, "_centre": True})
        out["fitted"] = 1
        out["pieces"] = len(group)
        out["geometry"] = _fit_users()
        return out
    if data.get("id"):
        obs = [find(data.get("id"))]
    else:
        obs = _scene_users(mat)
        if not obs:
            raise ApiError(tr("Nessun oggetto usa questo materiale"))
    done, seen, last_err = 0, set(), None
    for ob in obs:
        if ob.type != "MESH" or ob.data is None or not len(ob.data.polygons):
            continue
        key = ob.data.as_pointer()
        if key in seen:
            continue
        seen.add(key)
        try:
            _fit_object(ob, mat)
            done += 1
        except ApiError as e:
            last_err = e
    if not done:
        raise last_err or ApiError(tr("Seleziona un oggetto con questo materiale"))
    try:
        from . import rain
        rain.touch()
    except Exception:
        pass
    out = edit({"name": mat.name, "params": {"uv": {"mode": "uv", "scale": 1.0, "stretch": [1.0, 1.0], "rotation": 0.0,
                                                    "perPiece": False, "antitile": False, "offset": [0.0, 0.0],
                                                    "centerAt": None}}, "_centre": True})
    out["fitted"] = done
    out["geometry"] = _fit_users()
    return out


_FIT_MESHES = set()       # meshes given new UV by the last fit


def _fit_users():
    """The objects whose geometry the fit changed (every user of those meshes): the real-time view takes only them
    again, not the whole scene (1.70.3: «Adatta all'oggetto» prepared the cathedral again, 20 s)."""
    from .core import ID_KEY
    return [o[ID_KEY] for o in bpy.context.scene.objects
            if o.type == "MESH" and o.data is not None and o.data.as_pointer() in _FIT_MESHES and o.get(ID_KEY)
            and not o.get("simpler_twin")]


def _fit_gather(ob, mat):
    """The faces of ob with mat, in the world: (mesh, loops selected, points of those loops, area vectors)."""
    import numpy as np
    me = ob.data
    slots = [i for i, sl in enumerate(ob.material_slots) if sl.material == mat]
    nf = len(me.polygons)
    mi = np.empty(nf, dtype=np.int32)
    me.polygons.foreach_get("material_index", mi)
    faces = np.isin(mi, slots) if slots else np.ones(nf, dtype=bool)
    if not faces.any():
        faces[:] = True
    nv = len(me.vertices)
    co = np.empty(nv * 3)
    me.vertices.foreach_get("co", co)
    # in the WORLD: up = the scene's up, whatever the object's own axes (an FBX model has Y up inside, turned by its
    # parent: with the object's own Z the picture came out turned, 1.67.8), proportions with every scale above it
    M = np.array(ob.matrix_world.to_3x3())
    co = co.reshape(-1, 3) @ M.T + np.array(ob.matrix_world.translation)   # (with its place: pieces fitted together)
    lt = np.empty(nf, dtype=np.int64)
    me.polygons.foreach_get("loop_total", lt)
    lsel = np.repeat(faces, lt)
    vi = np.empty(len(me.loops), dtype=np.int64)
    me.loops.foreach_get("vertex_index", vi)
    P = co[vi[lsel]]
    # the plane: the area-weighted normal of the faces; for panes made of both sides (normals cancel) the plane of
    # least spread of their points, turned to the object's front (-Y) as Blender's views do
    fn = np.empty(nf * 3)
    me.polygons.foreach_get("normal", fn)
    fa = np.empty(nf)
    me.polygons.foreach_get("area", fa)
    # area vectors in the world: the cofactor matrix (det · M^-T) turns an area vector of the object into the world's
    # (size and side right also with a mirror)
    try:
        cof = np.linalg.det(M) * np.linalg.inv(M).T
    except np.linalg.LinAlgError:
        raise ApiError(tr("Seleziona un oggetto con questo materiale"))
    av = (fn.reshape(-1, 3)[faces] * fa[faces][:, None]) @ cof.T
    return me, lsel, P, av


def _fit_frame(P, av):
    """The plane of the faces (area-weighted normal; panes made of both sides: the plane of least spread turned to the
    scene's front -Y) and its axes: right u, up v (the scene's up)."""
    import numpy as np
    n = av.sum(axis=0)
    if np.linalg.norm(n) < 0.3 * float(np.linalg.norm(av, axis=1).sum()):
        c = P - P.mean(axis=0)
        w, vecs = np.linalg.eigh(c.T @ c)
        n = vecs[:, 0]
        if n[1] > 0:
            n = -n
    n = n / max(float(np.linalg.norm(n)), 1e-12)
    up = np.array([0.0, 0.0, 1.0])
    if abs(float(n @ up)) > 0.95:                          # (a flat face up: the scene's -Y... is the bottom)
        up = np.array([0.0, 1.0, 0.0])
    v = up - n * float(up @ n)
    v /= max(float(np.linalg.norm(v)), 1e-12)
    u = np.cross(v, n)                                     # (right, seen from the side the faces look to)
    return u, v


def bump_geometry(me):
    """A new revision of the geometry with the same counts (new UV, faces turned): the real-time view file made before
    is not the same any more (render.view_fingerprint reads it)."""
    me["simpler_georev"] = int(me.get("simpler_georev", 0)) + 1


def _fit_write(me, lsel, uvs):
    import numpy as np
    if not len(me.uv_layers):
        me.uv_layers.new(name="UVMap")
    for lay in me.uv_layers:                               # (every UV map: the path tracing reads the render one, the
        allv = np.empty(len(me.loops) * 2)                 # view the first - only these faces change)
        lay.data.foreach_get("uv", allv)
        allv = allv.reshape(-1, 2)
        allv[lsel] = uvs
        lay.data.foreach_set("uv", allv.ravel())
    me.update()
    bump_geometry(me)
    _FIT_MESHES.add(me.as_pointer())


def _fit_objects(obs, mat):
    """One picture over the faces with mat of all these objects together (a window made of several pieces, 1.68.6):
    one plane, one frame, the square 0..1 filled once by all of them."""
    import numpy as np
    parts = [_fit_gather(ob, mat) for ob in obs]
    P = np.concatenate([p[2] for p in parts])
    av = np.concatenate([p[3] for p in parts])
    u, v = _fit_frame(P, av)
    s_, t_ = P @ u, P @ v
    w_, h_ = float(s_.max() - s_.min()), float(t_.max() - t_.min())
    if w_ < 1e-6 or h_ < 1e-6:
        raise ApiError(tr("Le coordinate UV di questo oggetto sono piatte: scegli Box o Piana per vedere la texture."))
    for me, lsel, Pi, _avi in parts:
        uvs = np.stack([(Pi @ u - s_.min()) / w_, (Pi @ v - t_.min()) / h_], axis=1)
        _fit_write(me, lsel, uvs)


def _fit_object(ob, mat):
    """New UV for the faces of ob with mat (see fit)."""
    _fit_objects([ob], mat)


def reset(data):
    mat = _mat(data.get("name"))
    restore_original(mat)
    return {"name": data.get("name")}


def duplicate(data):
    """A copy of the material; with id (and slot) the object gets the copy."""
    mat = _mat(data.get("name"))
    new = mat.copy()
    base = data.get("newName") or (mat.name + " " + tr("copia"))
    new.name = base
    if BACKUP_KEY in new:
        del new[BACKUP_KEY]
    assigned = None
    if data.get("ids"):
        # «Solo qui» (1.68.5): the objects chosen (the selection, or the piece clicked) and their pieces that use the
        # material get the copy - nothing else, also inside the same model (one window of a cathedral, not all 69)
        targets, seen = [], set()
        for oid in data["ids"]:
            o = find(oid, required=False)
            if o is None:
                continue
            for x in [o] + list(o.children_recursive):
                if x.name not in seen and any(sl.material == mat for sl in x.material_slots):
                    seen.add(x.name)
                    targets.append(x)
        assigned = 0
        for o in targets:
            for sl in o.material_slots:
                if sl.material == mat:
                    sl.link = "OBJECT"
                    sl.material = new
                    assigned += 1
        if assigned == 0:
            bpy.data.materials.remove(new)
            return {"name": mat.name, "assigned": 0}
        _sync_displacement(targets)
        return {"name": new.name, "assigned": assigned, "objects": len(targets)}
    if data.get("id"):
        ob = find(data["id"])
        within = find(data["within"], required=False) if data.get("within") else None
        if within is not None:
            # «Solo questo modello»: every piece of the model the object belongs to that uses the material (both
            # tail lights of a car), and nothing outside it
            targets = [o for o in [within] + list(within.children_recursive) if any(s.material == mat for s in o.material_slots)]
            data = dict(data, slot=None)
        else:
            # the object itself, or - a group, a model of the library chosen in the tree - its pieces that use the material
            targets = [ob] if any(s.material == mat for s in ob.material_slots) else \
                [c for c in ob.children_recursive if any(s.material == mat for s in c.material_slots)]
        assigned = 0
        for o in targets:
            slots = [int(data["slot"])] if data.get("slot") is not None and o == ob and within is None else range(len(o.material_slots))
            for i in slots:
                if 0 <= i < len(o.material_slots) and o.material_slots[i].material == mat:
                    o.material_slots[i].link = "OBJECT"
                    o.material_slots[i].material = new
                    assigned += 1
        if assigned == 0:
            # nothing to give the copy to: no copy (it would be edited on no object - "changes do not show")
            bpy.data.materials.remove(new)
            return {"name": mat.name, "assigned": 0}
        _sync_displacement(targets)
    return {"name": new.name, "assigned": assigned}


def rename(data):
    mat = _mat(data.get("name"))
    new = (data.get("newName") or "").strip()
    if not new:
        raise ApiError(tr("Nome vuoto"))
    mat.name = new
    return {"name": mat.name}


def replace(data):
    """Every object using material 'name' gets 'with' (a material of the scene or a library preset id); with ids, only
    the objects inside those."""
    mat = _mat(data.get("name"))
    target = None if data.get("preset") else bpy.data.materials.get(data.get("with") or "")
    if target is None:
        from . import materials
        target = materials.get_or_create(data.get("with") or "", fresh=True)
    if target == mat:
        return {"replaced": 0, "material": target.name}
    users = _users(mat)
    if data.get("ids"):
        # «Sostituisci nella selezione»: only the users inside these objects (themselves or their pieces)
        from .core import find, descendants_many
        scope = set(descendants_many([find(i, required=False) for i in data["ids"]]))
        users = [u for u in users if u in scope]
    for ob in users:
        for sl in ob.material_slots:
            if sl.material == mat:
                sl.link = "OBJECT"
                sl.material = target
    _sync_displacement(users)
    return {"replaced": len(users), "material": target.name}


def users_of(name):
    """Ids of the objects using a material (for undo of slot changes)."""
    from .core import ID_KEY
    mat = bpy.data.materials.get(name or "")
    return [ob.get(ID_KEY) for ob in _users(mat)] if mat else []


def scene_materials(_data=None):
    out = []
    for mat in bpy.data.materials:
        if mat.get(BACKUP_TAG) or mat.name.startswith("Simpler Preview"):
            continue
        n = len(_users(mat))
        if n == 0:
            continue
        p, advanced = read_material(mat)
        out.append({"name": mat.name, "users": n, "color": p["color"]["tint"], "textured": bool(p["color"]["map"].get("image")),
                    "advanced": advanced, "simpler": bool(mat.get(PARAMS_KEY))})
    out.sort(key=lambda m: m["name"].lower())
    return {"materials": out}


# ---------------------------------------------------------------- undo (history.py, kind "material")

def snapshot(names):
    out = {}
    for n in names:
        mat = bpy.data.materials.get(n)
        if mat is not None:
            out[n] = {"params": mat.get(PARAMS_KEY), "backup": mat.get(BACKUP_KEY), "water": mat.get("simpler_water"),
                      "volumetric": mat.get("simpler_volumetric"), "rainDrops": mat.get("simpler_rain_drops")}
    return out


def restore(snap):
    for n, st in snap.items():
        mat = bpy.data.materials.get(n)
        if mat is None:
            continue
        if st["params"]:
            apply(mat, json.loads(st["params"]))
        elif mat.get(PARAMS_KEY):
            restore_original(mat)
    from . import water
    for n, st in snap.items():
        mat = bpy.data.materials.get(n)
        if mat is None or "water" not in st:
            continue
        if st["water"]:
            mat["simpler_water"] = st["water"]
        elif "simpler_water" in mat:
            del mat["simpler_water"]
        bm = bpy.data.materials.get(f"{mat.name} · corpo")
        if bm is not None:
            water._volume_nodes(bm, dict(water.mat_settings(mat)["body"]))
        for ob in water._users(mat):
            water._sync(ob, force=True)
    from . import volumetric
    for n, st in snap.items():
        mat = bpy.data.materials.get(n)
        if mat is not None and "volumetric" in st:
            volumetric.restore(mat, st["volumetric"])
    # «Con la pioggia» (rain.DROPS_KEY): the materials are wrapped again with the mode of then
    from . import rain
    changed = False
    for n, st in snap.items():
        mat = bpy.data.materials.get(n)
        if mat is None or "rainDrops" not in st:
            continue
        if mat.get(rain.DROPS_KEY) != st["rainDrops"]:
            if st["rainDrops"]:
                mat[rain.DROPS_KEY] = st["rainDrops"]
            elif rain.DROPS_KEY in mat:
                del mat[rain.DROPS_KEY]
            changed = True
    if changed:
        rain.touch()


# ---------------------------------------------------------------- vegetation (1.78.0)
# «Importa vegetazione» / «Converti in vegetazione» (library: ../matbulk_job.py; scene: scene_vegetation): every material
# of the plant gets the type Fogliame, as leaves or as wood.
LEAF_WORDS = ("leaf", "leaves", "foglia", "foglie", "needle", "aghi", "ago_", "frond", "petal", "petalo", "flower", "fiore",
              "fiori", "grass", "erba", "blade", "foliage", "fogliame", "canopy", "chioma", "twig", "hedge", "siepe", "blatt",
              "feuille", "hoja", "moss", "muschio", "clover", "trifoglio", "fern", "felce", "ivy", "edera", "bloom")
WOOD_WORDS = ("bark", "trunk", "wood", "branch", "stem", "corteccia", "tronco", "legno", "ramo", "rami", "fusto", "stelo",
              "root", "radice", "rinde", "stamm", "ecorce", "tronc", "corteza", "tronco")


def _image_green(name):
    try:
        mean = image_mean(name)
    except Exception:
        mean = None
    return mean


def foliage_part_guess(m, p):
    """(1.78.0) Leaves or wood for a material of a plant: what it is set to, its name, a cut-out, green; else wood.
    Returns (part, why)."""
    f = p.get("foliage") or {}
    if f.get("enabled"):                     # (already a plant: what it was made, by Simpler or by hand)
        return f.get("part", "foglie"), "set"
    low = m.name.lower()
    if any(w in low for w in WOOD_WORDS):
        # (not «a branch with a cut-out is foliage»: the bare twig cards of the plants of the library, «Acacia Branch»,
        # have one too and must stay wood - a name says wood, «Foglie e legno…» corrects one plant)
        return "legno", "name"
    if any(w in low for w in LEAF_WORDS):
        return "foglie", "name"
    if p["opacity"]["useAlpha"] or p["opacity"]["map"].get("image"):
        return "foglie", "cutout"
    c = None
    if p["color"]["map"].get("image"):
        c = _image_green(p["color"]["map"]["image"])
    if c is None:
        c = p["color"]["tint"]
    if c is not None and len(c) >= 3 and c[1] > c[0] * 1.05 and c[1] > c[2]:
        return "foglie", "colour"
    return "legno", "default"




def scene_vegetation(data):
    """POST /api/scene/vegetation {ids, parts: {material: foglie|legno|altro}, dry}: «Converti in vegetazione» on objects
    of the scene (and their pieces): Fogliame on their materials, leaves or wood (as the library's conversion).
    Returns {materials: [{name, part, why}]}; dry: only the guess."""
    from .core import find
    parts = data.get("parts") or {}
    obs, seen = [], set()

    def walk(o):
        if o is None or o.name in seen:
            return
        seen.add(o.name)
        obs.append(o)
        for c in o.children:
            walk(c)
    for oid in data.get("ids") or []:
        walk(find(oid, required=False))
    mats = []
    for o in obs:
        if o.type != "MESH":
            continue
        for sl in o.material_slots:
            if sl.material is not None and sl.material not in mats and not sl.material.get(BACKUP_TAG):
                mats.append(sl.material)
    if not mats:
        raise ApiError(tr("Nessun materiale negli oggetti scelti"))
    out = []
    for m in mats:
        p, _adv = read_material(m)
        p = _merge(DEFAULTS, p)
        part, why = foliage_part_guess(m, p)
        if parts.get(m.name) in ("foglie", "legno", "altro"):
            part, why = parts[m.name], "user"
        out.append({"name": m.name, "part": part, "why": why})
        if data.get("dry") or part == "altro":
            continue
        f = p["foliage"]
        if f.get("enabled") and f.get("part") == part:
            continue
        f["enabled"], f["part"] = True, part
        p["fabric"]["enabled"] = False
        if part == "foglie":
            p["subsurface"]["weight"] = 0.0
        mark_draft(m)
        apply(m, p)
    return {"materials": out}


def scene_vegetation_materials(data):
    """The materials scene_vegetation may change (for its Ctrl+Z)."""
    from .core import find
    names = []

    def walk(o):
        if o is None:
            return
        if o.type == "MESH":
            names.extend(sl.material.name for sl in o.material_slots if sl.material is not None and sl.material.name not in names)
        for c in o.children:
            walk(c)
    for oid in data.get("ids") or []:
        walk(find(oid, required=False))
    return names
