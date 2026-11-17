"""(1.80.0, Luca: «le cartelle rosse non consentono modifiche») The lock of the engine for the materials and the ecosystems
of the red Simpler folders, tried without Blender (bpy stubbed): python tools/lock_check_stub.py  -> LOCK_STUB_OK / _FAIL."""
import json, os, sys, tempfile
from unittest.mock import MagicMock
for m in ("bpy", "mathutils", "bmesh", "numpy", "bpy_extras", "gpu"):
    sys.modules.setdefault(m, MagicMock())
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "engine"))
from simpler import models, materials, ecosystems
from simpler.core import ApiError

tmp = tempfile.mkdtemp()
for e, f in (("e_a", "Simpler/Grass"), ("e_b", "")):
    os.makedirs(os.path.join(tmp, e))
    json.dump({"folder": f, "layers": []}, open(os.path.join(tmp, e, "eco.json"), "w"))
ecosystems.root = lambda: tmp
materials.library_entry = lambda mid: {"folder": "Simpler/Lights"} if mid == "led" else {"folder": "Mine"} if mid == "mine" else None
bad = []


def chk(on, key, d, refused):
    models.LOCK["on"] = on
    try:
        models.lock_check(key, d)
        r = False
    except ApiError:
        r = True
    if r != refused:
        bad.append((on, key, d, r))


E, M = "POST /api/ecosystems/", "POST /api/material/library/"
for k, d in ((E + "rename", {"id": "e_a"}), (E + "delete", {"id": "e_a"}), (E + "thumb", {"id": "e_a"}), (E + "defaults", {"id": "e_a"}),
             (E + "move", {"id": "e_b", "folder": "Simpler/Grass"}), (E + "move", {"id": "e_a", "folder": ""}),
             (E + "copy", {"id": "e_a", "folder": "Simpler"}), (E + "folder", {"action": "delete", "path": "Simpler/Grass"}),
             (M + "move", {"id": "led", "folder": ""}), (M + "move", {"id": "mine", "folder": "Simpler/Lights"}),
             (M + "delete", {"id": "led"}), (M + "reset", {"id": "led"}), (M + "restore", {})):
    chk(True, k, d, True)
    chk(False, k, d, False)
for k, d in ((E + "move", {"id": "e_b", "folder": "Mine"}), (E + "copy", {"id": "e_a", "folder": ""}),
             (E + "folder", {"action": "create", "path": "Simpler"}), (M + "move", {"id": "mine", "folder": "Other"}),
             (M + "reset", {"id": "mine"})):
    chk(True, k, d, False)
print("LOCK_STUB_OK" if not bad else "LOCK_STUB_FAIL %s" % bad)
