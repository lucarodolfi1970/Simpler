"""(1.78.4, Luca: «ho eliminato la cartella con i modelli dentro: è sparita ma i modelli ci sono tutti») Deleting a
folder of models: with «items» the models inside it and in its subfolders go too (and its subfolders), the others
stay; without, as before, the contents go up to the folder above.
Run inside Blender: blender -b --factory-startup --python tools/folderdelete_check.py   Prints FOLDERDEL_OK or FOLDERDEL_FAIL <why>."""
import json
import os
import shutil
import sys
import tempfile

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "engine"))

bad = []
tmp = tempfile.mkdtemp(prefix="simpler_folderdel_")
try:
    from simpler import models
    models.user_dir = lambda: tmp

    def model(mid, folder):
        os.makedirs(os.path.join(tmp, mid), exist_ok=True)
        open(os.path.join(tmp, mid, "model.blend"), "w").write("x")
        json.dump({"id": mid, "name": mid, "folder": folder}, open(os.path.join(tmp, mid + ".json"), "w"))

    def setup():
        for f in os.listdir(tmp):
            p = os.path.join(tmp, f)
            shutil.rmtree(p) if os.path.isdir(p) else os.remove(p)
        json.dump({"folders": ["Simpler", "Simpler/Characters", "Simpler/Characters/Victorian era", "Simpler/Characters/Victorian era/Kids", "Altro"]},
                  open(os.path.join(tmp, "folders.json"), "w"))
        model("m_a", "Simpler/Characters/Victorian era")
        model("m_b", "Simpler/Characters/Victorian era/Kids")
        model("m_c", "Simpler/Characters")
        model("m_d", "Altro")

    folders = lambda: json.load(open(os.path.join(tmp, "folders.json")))["folders"]
    has = lambda mid: os.path.isfile(os.path.join(tmp, mid + ".json"))
    folder_of = lambda mid: json.load(open(os.path.join(tmp, mid + ".json")))["folder"]

    setup()
    r = models.folder_op({"action": "delete", "path": "Simpler/Characters/Victorian era", "items": True})
    if r.get("deleted") != 2:
        bad.append(f"deleted {r.get('deleted')} of 2")
    if has("m_a") or has("m_b"):
        bad.append("models inside the folder still there")
    if not (has("m_c") and has("m_d")):
        bad.append("models outside the folder deleted")
    if any(f.startswith("Simpler/Characters/Victorian era") for f in folders()):
        bad.append("folder or subfolder still listed: " + str(folders()))
    if "Simpler/Characters" not in folders():
        bad.append("the folder above went away")

    setup()
    models.folder_op({"action": "delete", "path": "Simpler/Characters/Victorian era"})
    if not (has("m_a") and folder_of("m_a") == "Simpler/Characters"):
        bad.append("without items: the model did not go up")
    if not (has("m_b") and folder_of("m_b") == "Simpler/Characters/Kids"):
        bad.append("without items: the subfolder's model did not go up with its subfolder")
    print("FOLDERDEL_FAIL " + "; ".join(bad) if bad else "FOLDERDEL_OK")
except Exception as e:                                  # noqa: BLE001
    print(f"FOLDERDEL_FAIL {e!r}")
finally:
    shutil.rmtree(tmp, ignore_errors=True)
