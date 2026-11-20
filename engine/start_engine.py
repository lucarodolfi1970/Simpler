"""Entry point of the Simpler render engine.

Started by Simpler.exe as:
    blender.exe --background --factory-startup --python start_engine.py -- --port 8787
(For development it also works with the `bpy` Python module: python start_engine.py --port 8787)
"""
import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

argv = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else sys.argv[1:]
parser = argparse.ArgumentParser(prog="simpler-engine")
parser.add_argument("--port", type=int, default=8787)
parser.add_argument("--open", default="", help="project (.simpler) to open at startup")
parser.add_argument("--parent-pid", type=int, default=0, help="exit when this process ends (Simpler.exe)")
parser.add_argument("--lang", default="it", help="language of engine messages: it | en")
parser.add_argument("--app-version", default="", help="version of Simpler.exe, written in the projects saved")
args = parser.parse_args(argv)

from simpler import fullspeed, i18n, server  # noqa: E402

# (no slow cores when Simpler is not the program in front: the app asks it too)
print("SIMPLER_FULLSPEED engine", "on" if fullspeed.apply() else "not available", flush=True)

i18n.set_lang(args.lang)
from simpler import core  # noqa: E402
core.APP_VERSION = args.app_version

if args.open:
    server.project_open({"path": args.open})
    server.serve(args.port, new_scene=False, parent_pid=args.parent_pid)
else:
    server.serve(args.port, new_scene=True, parent_pid=args.parent_pid)
