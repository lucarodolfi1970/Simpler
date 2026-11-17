"""(1.78.4, Luca: «l'utente può fare azioni nelle cartelle rosse di Simpler che non deve fare») With SimplerLocked the
engine refuses every change of the Simpler parts: rename, move in or out, delete, folders, orientation, size,
thumbnail, conversion, material fixes; copying a model of Simpler into one's own folder is allowed; the library
clean-up («broken») and the restore of material fixes leave them alone.
Run inside Blender: blender -b --factory-startup --python tools/lock_check.py   Prints LOCK_OK or LOCK_FAIL <why>."""
import json
import os
import shutil
import sys
import tempfile

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "engine"))

bad = []
tmp = tempfile.mkdtemp(prefix="simpler_lock_")
try:
    from simpler import models, matbulk, libstats
    from simpler.core import ApiError
    models.user_dir = lambda: tmp
    matbulk.veg_root = lambda: "Vegetazione"

    def model(mid, folder, blend=True):
        os.makedirs(os.path.join(tmp, mid), exist_ok=True)
        if blend:
            open(os.path.join(tmp, mid, "model.blend"), "w").write("x")
        json.dump({"id": mid, "name": mid, "folder": folder}, open(os.path.join(tmp, mid + ".json"), "w"))
    json.dump({"folders": ["Simpler", "Simpler/Characters", "Vegetazione", "Vegetazione/Simpler", "Mine"]}, open(os.path.join(tmp, "folders.json"), "w"))
    model("m_sim", "Simpler/Characters")
    model("m_plant", "Vegetazione/Simpler")
    model("m_mine", "Mine")
    model("m_simbroken", "Simpler/Characters", blend=False)
    models.LOCK["on"] = True

    def refused(key, data):
        try:
            models.lock_check(key, data)
            return False
        except ApiError:
            return True
    for key, data, what in [
        ("POST /api/models/rename", {"id": "m_sim", "name": "x"}, "rename"),
        ("POST /api/models/delete", {"id": "m_sim"}, "delete"),
        ("POST /api/models/delete", {"id": "m_plant"}, "delete a plant"),
        ("POST /api/models/move", {"id": "m_sim", "folder": "Mine"}, "move out"),
        ("POST /api/models/move", {"id": "m_mine", "folder": "Simpler/Characters"}, "move in"),
        ("POST /api/models/copy", {"id": "m_mine", "folder": "Simpler"}, "copy in"),
        ("POST /api/models/folder", {"action": "delete", "path": "Simpler/Characters"}, "delete a folder"),
        ("POST /api/models/folder", {"action": "delete", "path": "Simpler/Characters", "items": True}, "delete a folder with its models"),
        ("POST /api/models/folder", {"action": "rename", "path": "Simpler/Characters", "newPath": "Simpler/X"}, "rename a folder"),
        ("POST /api/models/folder", {"action": "create", "path": "Simpler/New"}, "new folder"),
        ("POST /api/models/orient", {"id": "m_sim"}, "orientation"),
        ("POST /api/models/rescale", {"id": "m_sim"}, "size"),
        ("POST /api/models/thumb", {"id": "m_sim"}, "thumbnail"),
        ("POST /api/models/vegetation", {"ids": ["m_sim"]}, "convert to vegetation"),
        ("POST /api/matbulk/apply", {"items": [{"id": "m_sim"}]}, "material fix"),
        ("POST /api/models/save", {"folder": "Simpler"}, "save into"),
        ("POST /api/models/import", {"folder": "Vegetazione/Simpler"}, "import into"),
    ]:
        if not refused(key, data):
            bad.append("allowed: " + what)
    for key, data, what in [
        ("POST /api/models/copy", {"id": "m_sim", "folder": "Mine"}, "copy out"),
        ("POST /api/models/rename", {"id": "m_mine", "name": "y"}, "rename one's own"),
        ("POST /api/models/move", {"id": "m_mine", "folder": ""}, "move one's own"),
    ]:
        if refused(key, data):
            bad.append("refused: " + what)
    libstats.clean({"action": "broken"})
    if not os.path.isfile(os.path.join(tmp, "m_simbroken.json")):
        bad.append("library clean-up deleted a model of Simpler")
    print("LOCK_FAIL " + "; ".join(bad) if bad else "LOCK_OK")
except Exception as e:                                  # noqa: BLE001
    print(f"LOCK_FAIL {e!r}")
finally:
    shutil.rmtree(tmp, ignore_errors=True)
