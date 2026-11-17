"""(1.78.4, Luca: «se tolgo il focus da Simpler … rallenta tantissimo») Full speed when Simpler is not in front.

Windows 11 runs the work of a process with no window in front at a low quality of service: on processors with two
kinds of cores (performance and efficiency) its threads are moved to the slow cores and the clock is lowered. The
engine and its jobs (imports, thumbnails, renders, exports) have no window at all, so as soon as another program is
in front an import crawled. Each of them asks Windows not to be throttled (SetProcessInformation, power throttling
off: «high QoS»). The priority stays below normal - the computer keeps answering first to the program in use - but
the work runs at full speed when the computer is free. Nothing on other systems."""
import os
import subprocess

_EXECUTION_SPEED = 0x1
_IGNORE_TIMER_RESOLUTION = 0x4
_PROCESS_POWER_THROTTLING = 4           # (PROCESS_INFORMATION_CLASS.ProcessPowerThrottling)
_LOGGED = []                            # (the first job says in the log whether Windows took it)


def apply(handle=None):
    """Power throttling off for a process (its handle; None = this process). True when Windows took it."""
    if os.name != "nt":
        return False
    try:
        import ctypes
        from ctypes import wintypes

        class _State(ctypes.Structure):
            _fields_ = [("Version", wintypes.ULONG), ("ControlMask", wintypes.ULONG), ("StateMask", wintypes.ULONG)]
        k32 = ctypes.WinDLL("kernel32", use_last_error=True)
        k32.SetProcessInformation.argtypes = [wintypes.HANDLE, ctypes.c_int, ctypes.c_void_p, wintypes.DWORD]
        k32.SetProcessInformation.restype = wintypes.BOOL
        k32.GetCurrentProcess.restype = wintypes.HANDLE
        st = _State(1, _EXECUTION_SPEED | _IGNORE_TIMER_RESOLUTION, 0)     # (controlled, and off)
        h = k32.GetCurrentProcess() if handle is None else wintypes.HANDLE(int(handle))
        return bool(k32.SetProcessInformation(h, _PROCESS_POWER_THROTTLING, ctypes.byref(st), ctypes.sizeof(st)))
    except Exception:
        return False


def popen(cmd, **kw):
    """subprocess.Popen, the new process at full speed."""
    proc = subprocess.Popen(cmd, **kw)
    if os.name == "nt":
        ok = apply(getattr(proc, "_handle", None))
        if not _LOGGED:
            _LOGGED.append(ok)
            print("SIMPLER_FULLSPEED jobs", "on" if ok else "not available", flush=True)
    return proc


def run(cmd, **kw):
    """subprocess.run (output captured as asked), the new process at full speed."""
    timeout = kw.pop("timeout", None)
    with popen(cmd, **kw) as proc:
        try:
            out, err = proc.communicate(timeout=timeout)
        except BaseException:
            proc.kill()
            proc.wait()
            raise
        return subprocess.CompletedProcess(proc.args, proc.returncode, out, err)
