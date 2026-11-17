"""Interrupting a Cycles render that runs in this process (the path tracing view).

Blender in background mode stops a render when its global "break" flag is set; its own Ctrl+C handler sets that
flag (source/creator/creator_signals.cc, sig_handle_blender_esc). The render operator clears the flag when a
render starts (render_internal.cc, screen_render_exec), so a stale break never leaks into the next render.

We call that same C handler with a signal number other than SIGINT: it sets the flag and nothing else (only for
SIGINT does it count presses and quit at the second). The handler is taken from the C runtime once, at start,
and used only if it really belongs to the Blender executable; otherwise interrupting is simply not available
and the view waits for the end of the pass, as before.
"""
import ctypes
import os
import signal
import sys

_handler = None
_reason = ""


def _crt():
    if os.name == "nt":
        return ctypes.CDLL("ucrtbase")
    return ctypes.CDLL(None)


def _module_of(addr):
    """File of the module that contains a code address."""
    if os.name == "nt":
        k32 = ctypes.WinDLL("kernel32", use_last_error=True)
        h = ctypes.c_void_p()
        FROM_ADDRESS, UNCHANGED_REFCOUNT = 0x4, 0x2
        k32.GetModuleHandleExW.argtypes = [ctypes.c_uint32, ctypes.c_void_p, ctypes.POINTER(ctypes.c_void_p)]
        if not k32.GetModuleHandleExW(FROM_ADDRESS | UNCHANGED_REFCOUNT, ctypes.c_void_p(addr), ctypes.byref(h)):
            return ""
        buf = ctypes.create_unicode_buffer(1024)
        k32.GetModuleFileNameW.argtypes = [ctypes.c_void_p, ctypes.c_wchar_p, ctypes.c_uint32]
        k32.GetModuleFileNameW(h, buf, 1024)
        return buf.value

    class DlInfo(ctypes.Structure):
        _fields_ = [("dli_fname", ctypes.c_char_p), ("dli_fbase", ctypes.c_void_p),
                    ("dli_sname", ctypes.c_char_p), ("dli_saddr", ctypes.c_void_p)]
    info = DlInfo()
    libdl = ctypes.CDLL(None)
    libdl.dladdr.argtypes = [ctypes.c_void_p, ctypes.POINTER(DlInfo)]
    if not libdl.dladdr(ctypes.c_void_p(addr), ctypes.byref(info)):
        return ""
    return (info.dli_fname or b"").decode("utf-8", "replace")


def install():
    """Called once on the main thread at start."""
    global _handler, _reason
    try:
        crt = _crt()
        crt.signal.restype = ctypes.c_void_p
        crt.signal.argtypes = [ctypes.c_int, ctypes.c_void_p]
        SIG_IGN = ctypes.c_void_p(1)
        old = crt.signal(signal.SIGINT, SIG_IGN)       # read the current handler...
        crt.signal(signal.SIGINT, ctypes.c_void_p(old))  # ...and put it back at once
        if not old or old in (1, 0xFFFFFFFFFFFFFFFF):
            _reason = "no handler"
            return False
        module = _module_of(old)
        import bpy
        exe = os.path.normcase(os.path.realpath(bpy.app.binary_path or sys.executable))
        if (not module or os.path.normcase(os.path.realpath(module)) != exe
                or not os.path.basename(exe).startswith("blender")):
            _reason = f"handler in {module or '?'}"
            return False
        _handler = ctypes.CFUNCTYPE(None, ctypes.c_int)(old)
        _reason = "ok"
        return True
    except Exception as exc:   # any platform surprise: no interruption, nothing else changes
        _reason = f"{exc.__class__.__name__}: {exc}"
        _handler = None
        return False


def available():
    return _handler is not None


def info():
    return _reason


def interrupt():
    """Sets Blender's break flag: the running render stops at its next check. Safe from any thread."""
    if _handler is None:
        return False
    _handler(15)       # not SIGINT: the handler only sets the flag
    return True
