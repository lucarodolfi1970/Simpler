"""Simpler's temporary folders: made with the id of the engine that uses them, and removed at the next start when
that engine is gone.

Before 1.74.0 they were never removed: the engine is closed by the app (killed), and every session left in %TEMP%
its folders - the render one about 240 MB (copies of the scene, pictures of the light reflected by the water),
plus undo and previews. Found when the test computer filled its disk: 2415 folders, 12 GB.
"""
import os
import shutil
import tempfile
import time

PREFIXES = ("simpler_", "refcaustics_")
OWNER = ".simpler_pid"
OLD_WITHOUT_OWNER = 24 * 3600          # folders of older versions (no owner written): removed after a day


def make(prefix):
    d = tempfile.mkdtemp(prefix=prefix)
    try:
        with open(os.path.join(d, OWNER), "w") as f:
            f.write(str(os.getpid()))
    except OSError:
        pass
    return d


def _alive(pid):
    if pid <= 0:
        return False
    if os.name == "nt":
        import ctypes
        k = ctypes.windll.kernel32
        h = k.OpenProcess(0x1000, False, pid)          # PROCESS_QUERY_LIMITED_INFORMATION
        if not h:
            return False
        try:
            code = ctypes.c_ulong()
            ok = k.GetExitCodeProcess(h, ctypes.byref(code))
            return bool(ok) and code.value == 259     # STILL_ACTIVE
        finally:
            k.CloseHandle(h)
    try:
        os.kill(pid, 0)                                # (posix only: on Windows os.kill would end the process)
        return True
    except ProcessLookupError:
        return False
    except OSError:
        return True


def stale():
    """The folders of engines that are gone (or of older versions, after a day)."""
    base = tempfile.gettempdir()
    out = []
    try:
        names = os.listdir(base)
    except OSError:
        return out
    now = time.time()
    for n in names:
        if not n.startswith(PREFIXES) or n.startswith("simpler_reg_"):     # (the check's own folders: it removes them)
            continue
        d = os.path.join(base, n)
        if not os.path.isdir(d):
            continue
        try:
            with open(os.path.join(d, OWNER)) as f:
                pid = int(f.read().strip() or 0)
            if pid == os.getpid() or _alive(pid):
                continue
        except (OSError, ValueError):
            try:
                if now - os.path.getmtime(d) < OLD_WITHOUT_OWNER:
                    continue
            except OSError:
                continue
        out.append(d)
    return out


def sweep():
    """At the start of the engine: the folders left by the engines before, removed (in the background: a few
    seconds with thousands of them). Returns how many."""
    dirs = stale()
    for d in dirs:
        shutil.rmtree(d, ignore_errors=True)
    return len(dirs)
