"""«Aggiorna dalla libreria»: the library models used in the project made again as the library has them now.

A distribution (brush, area, spacing, the layers of an ecosystem) keeps in the project a copy of every model it uses
(its original, paint._ensure_original), and a model placed in the scene is a copy too: a model corrected in the
library afterwards (materials, «Senza mantello» on the inside of a car...) stayed old in the projects made before -
and a new distribution in such a project copied the old original again. Here, for every chosen model, in the whole
project:
  distributions  the original of each one is loaded again from the library into the same place of its collection
                 (same index: the points do not change), its base and rest computed as when it is first used; the
                 points object is copied (a new version for the real-time view, which then asks for the new model)
  placed models  a copy of the new model where the old one was (same world matrix, parent, collections, name,
                 visibility); objects the user put under it move to the new one
The old ones go to the trash (one undo step that covers the originals of the distributions too: history «allobjects»).

The version of the library a model came from is kept (LIB_REV, on the collection of a distribution's model and on a
placed model): at opening, the models changed in the library since then are listed (outdated)."""
import json
import os

import bpy

from .core import ApiError, INTERNAL_KEY, claim_name, ensure_id, find, new_id, refresh, tree_kids
from .i18n import tr

LIB_REV = "simpler_lib_rev"
LIB_PART = "simpler_lib_part"         # on the lamps and cameras of a placed model: its library model


def _paint():
    from . import paint
    return paint


def _subs(mid=None):
    """[(collection of the distribution, sub-collection of the model)] of every distribution of the project (also
    the deleted ones kept for undo: restored, they would bring the old model back)."""
    paint = _paint()
    refs = paint._scatter_refs()
    out = []
    for c in bpy.data.collections:
        if not c.get(paint.SCATTER_TAG) or c.name not in refs:
            continue
        for sub in c.children:
            m = sub.get(paint.MODEL_KEY)
            if m and (mid is None or m == mid) and any(not o.get("simpler_trashed") for o in sub.objects):
                out.append((c, sub))
    return out


def _is_placed_root(o):
    paint = _paint()
    m = o.get(paint.MODEL_KEY)
    if not m or o.get("simpler_trashed") or o.get(INTERNAL_KEY) or not o.users_scene:
        return False
    p = o.parent
    if p is not None and (p.get(paint.MODEL_KEY) == m or p.get(paint.PAINT_KEY)):
        return False                    # (a part of the model, or a piece painted before 1.8)
    return True


def _placed(mid=None):
    paint = _paint()
    return [o for o in bpy.context.scene.objects if _is_placed_root(o) and (mid is None or o.get(paint.MODEL_KEY) == mid)]


def _groups_of(coll_name, live=True):
    """The distributions (their groups) that draw the models of this collection."""
    paint = _paint()
    return [g for g in bpy.data.objects if g.get(paint.PAINT_KEY) and g.get(paint.SCATTER_COLL) == coll_name
            and (not live or (g.users_scene and not g.get("simpler_trashed")))]


def _models_of(ids):
    """The library models used by these objects (a distribution, an ecosystem, a placed model, a group with them)."""
    paint = _paint()
    out = []
    for i in ids or []:
        ob = find(i, required=False)
        if ob is None:
            continue
        for o in [ob] + list(ob.children_recursive):
            if o.get("simpler_trashed"):
                continue
            if o.get(paint.PAINT_KEY):
                c = bpy.data.collections.get(o.get(paint.SCATTER_COLL) or "")
                for sub in (c.children if c is not None else []):
                    m = sub.get(paint.MODEL_KEY)
                    if m and m not in out and len(sub.objects):
                        out.append(m)
            elif _is_placed_root(o) and o[paint.MODEL_KEY] not in out:
                out.append(o[paint.MODEL_KEY])
    return out


def _usage(mid, entries):
    from .ecosystems import LAYER_KEY
    dist, ecos, revs = 0, set(), []
    for c, sub in _subs(mid):
        revs.append(sub.get(LIB_REV))
        for g in _groups_of(c.name):
            if g.get(LAYER_KEY):
                ecos.add(g.get(LAYER_KEY))
            else:
                dist += 1
    placed = _placed(mid)
    revs += [o.get(LIB_REV) for o in placed]
    e = entries.get(mid)
    known = [str(r) for r in revs if r]
    out = {"id": mid, "name": (e or {}).get("name") or mid, "inLibrary": e is not None,
           "distributions": dist, "ecosystems": len(ecos), "placed": len(placed),
           # (True: made from an older version of the library; None: not known - a project made before 1.59)
           "outdated": (any(r != str(e.get("rev", "")) for r in known) if known else None) if e is not None else False}
    return out


def usage(d):
    """GET models/usage?ids=a,b -> {models: [{id, name, inLibrary, distributions, ecosystems, placed, outdated}]}"""
    from . import models
    ids = d.get("ids") or []
    if isinstance(ids, str):
        ids = [i for i in ids.split(",") if i]
    entries = models._entries()
    return {"models": [_usage(m, entries) for m in _models_of(ids)]}


def outdated(_d=None):
    """GET models/outdated -> {models: [...]}: the models of the project whose library version is newer than the one
    they were made from (only where that is known)."""
    from . import models
    paint = _paint()
    entries = models._entries()
    mids = []
    for _c, sub in _subs():
        m = sub.get(paint.MODEL_KEY)
        if sub.get(LIB_REV) and m not in mids:
            mids.append(m)
    for o in _placed():
        m = o.get(paint.MODEL_KEY)
        if o.get(LIB_REV) and m not in mids:
            mids.append(m)
    out = []
    for m in mids:
        u = _usage(m, entries)
        if u["inLibrary"] and u["outdated"]:
            out.append(u)
    return {"models": out}


def _tree(root):
    return [root] + list(root.children_recursive)


def _copy_tree(root):
    """A copy of a model (its objects share meshes and materials with it: identical)."""
    mapping = {}
    for o in _tree(root):
        mapping[o] = o.copy()
    for o, c in mapping.items():
        c.parent = mapping.get(o.parent)
        if o.parent is not None and o.parent in mapping:
            c.matrix_parent_inverse = o.matrix_parent_inverse.copy()
        new_id(c)
    return mapping[root], list(mapping.values())


def _model_parts(root, mid, entry):
    """The objects of a placed model (its pieces, its lamps and cameras) and the objects the user put under it."""
    from .models import _stem
    paint = _paint()
    names = {_stem(n) for n in (entry.get("objects") or [])}
    parts, extra = [root], []
    kids = tree_kids([root])                   # (Object.children per piece: seconds on big models)
    stack = list(kids.get(root, ()))
    while stack:
        o = stack.pop()
        if o.get("simpler_trashed"):
            continue
        if o.get(paint.MODEL_KEY) == mid or (o.type in ("LIGHT", "CAMERA") and not o.get(paint.MODEL_KEY) and (
                o.get(LIB_PART) == mid or (not o.get(LIB_PART) and _stem(o.name) in names))):
            # (lamps and cameras of the model carry no model key - paint.tag_pieces: marked since 1.59, by their
            # name in the library before; a lamp the user put under the model stays and moves to the new one)
            parts.append(o)
            stack.extend(kids.get(o, ()))
        else:
            extra.append(o)
    return parts, extra


def _lib_info(entry):
    try:
        from . import models
        with open(os.path.join(models.user_dir(), entry["id"], "info.json"), encoding="utf-8") as fh:
            return json.load(fh)
    except (OSError, ValueError):
        return {}


def _update_model(mid, entry):
    """One model in the whole project. Returns (distributions, placed)."""
    from . import models, trash
    paint = _paint()
    path = os.path.join(models.user_dir(), entry["id"], "model.blend")
    if not os.path.isfile(path):
        raise ApiError(tr("Il modello è ancora in preparazione: riprova tra qualche secondo"))
    subs = _subs(mid)
    placed = _placed(mid)
    if not subs and not placed:
        return 0, 0
    rev = str(entry.get("rev", ""))
    serial = _lib_info(entry).get("orientSerial")
    r = models.insert_blend(path, entry["name"], entry=entry, location=None)
    fresh = find(r["id"])
    used = False
    first = None
    groups = []
    for c, sub in subs:
        old = [o for o in sub.objects if not o.get("simpler_trashed")]
        for o in old:
            ensure_id(o)
        trash.trash(old)
        if first is None:
            first = paint._adopt(c, mid, fresh, sub=sub)
            used = True
        else:
            paint._adopt(c, mid, first, copy=True, sub=sub)
        sub[LIB_REV] = rev
        if serial:
            sub["simpler_orient_serial"] = serial
        elif "simpler_orient_serial" in sub:
            del sub["simpler_orient_serial"]
        for g in _groups_of(c.name):
            if g not in groups:
                groups.append(g)
    # the points of those distributions: a new version (the real-time view asks again for what it draws)
    for g in groups:
        pts = paint._holder(g)
        if pts is None:
            continue
        cp = pts.copy()
        new_id(cp)
        for col in pts.users_collection:
            col.objects.link(cp)
        cp.parent = g
        cp.matrix_parent_inverse = pts.matrix_parent_inverse.copy()
        cp.matrix_basis = pts.matrix_basis.copy()
        trash.trash([pts])
    src = first if first is not None else fresh
    for P in placed:
        parts, extra = _model_parts(P, mid, entry)
        if not used:
            root, tree = fresh, _tree(fresh)
            for o in tree:
                for col in list(o.users_collection):
                    col.objects.unlink(o)
            used = True
        else:
            root, tree = _copy_tree(src)
        for o in tree:
            for k in ("simpler_paint_gen", "simpler_paint_rest", "simpler_paint_base", "simpler_instance_of"):
                if k in o:
                    del o[k]
        cols = list(P.users_collection) or [bpy.context.scene.collection]
        for o in tree:
            for col in cols:
                if o.name not in col.objects:
                    col.objects.link(o)
        refresh()
        root.parent = P.parent
        root.matrix_parent_inverse.identity()
        root.matrix_world = P.matrix_world.copy()
        root.hide_render, root.hide_viewport = P.hide_render, P.hide_viewport
        paint.tag_pieces(root, mid)
        root[LIB_REV] = rev
        refresh()
        from . import history
        for x in extra:
            history.note_parent(ensure_id(x), ensure_id(x.parent), ensure_id(root))
            w = x.matrix_world.copy()
            x.parent = root
            x.matrix_parent_inverse.identity()
            x.matrix_world = w
        name = P.name
        trash.trash(parts)
        claim_name(root, name)
    if not used:
        # (only for copies: the loaded one itself goes)
        bpy.data.batch_remove(list(_tree(fresh)))      # (in one call: one by one is quadratic)
    refresh()
    return len(subs), len(placed)


def update(d):
    """POST models/refresh {models: [ids]} -> {models, distributions, placed, missing}"""
    from . import models, progress, snow
    entries = models._entries()
    mids = [m for m in (d.get("models") or []) if m]
    if not mids:
        raise ApiError(tr("Nessun modello da aggiornare"))
    nd = npl = done = 0
    missing = []
    progress.begin("libupdate", tr("Aggiorna dalla libreria"))
    try:
        for k, m in enumerate(mids):
            e = entries.get(m)
            if e is None:
                missing.append(m)
                continue
            progress.update(tr("Aggiorna dalla libreria"), k / len(mids), e.get("name") or m)
            a, b = _update_model(m, e)
            nd += a
            npl += b
            done += 1 if (a or b) else 0
    finally:
        progress.end()
    try:
        snow.touch()            # (the snow mantle looks again at the models)
    except Exception:
        pass
    return {"models": done, "distributions": nd, "placed": npl, "missing": len(missing)}
