"""Memory used on the NVIDIA graphics card (NVML, installed with the NVIDIA driver).

While Cycles uploads the textures it sends no news for minutes on big scenes; the memory the card fills is the
only sign of how far it is. If NVML is missing (no NVIDIA card, other systems) used_bytes() returns None.
"""
import ctypes
import os
import threading

_lock = threading.Lock()
_nvml = None
_handle = None
_failed = False


class _Memory(ctypes.Structure):
    _fields_ = [("total", ctypes.c_ulonglong), ("free", ctypes.c_ulonglong), ("used", ctypes.c_ulonglong)]


def _init():
    global _nvml, _handle, _failed
    if _nvml is not None or _failed:
        return _nvml is not None
    try:
        if os.name == "nt":
            lib = None
            for path in ("nvml.dll", os.path.join(os.environ.get("SystemRoot", r"C:\Windows"), "System32", "nvml.dll"),
                         os.path.join(os.environ.get("ProgramFiles", r"C:\Program Files"), "NVIDIA Corporation", "NVSMI", "nvml.dll")):
                try:
                    lib = ctypes.CDLL(path)
                    break
                except OSError:
                    continue
            if lib is None:
                raise OSError("nvml.dll not found")
        else:
            lib = ctypes.CDLL("libnvidia-ml.so.1")
        if lib.nvmlInit_v2() != 0:
            raise OSError("nvmlInit failed")
        handle = ctypes.c_void_p()
        if lib.nvmlDeviceGetHandleByIndex_v2(0, ctypes.byref(handle)) != 0:
            raise OSError("no device")
        _nvml, _handle = lib, handle
        return True
    except Exception:
        _failed = True
        return False


def used_bytes():
    with _lock:
        if not _init():
            return None
        mem = _Memory()
        if _nvml.nvmlDeviceGetMemoryInfo(_handle, ctypes.byref(mem)) != 0:
            return None
        return int(mem.used)


class _Util(ctypes.Structure):
    _fields_ = [("gpu", ctypes.c_uint), ("memory", ctypes.c_uint)]


def info():
    """Name, memory and load of the graphics card, or None."""
    with _lock:
        if not _init():
            return None
        out = {}
        mem = _Memory()
        if _nvml.nvmlDeviceGetMemoryInfo(_handle, ctypes.byref(mem)) == 0:
            out.update(total=int(mem.total), used=int(mem.used))
        util = _Util()
        if _nvml.nvmlDeviceGetUtilizationRates(_handle, ctypes.byref(util)) == 0:
            out["load"] = int(util.gpu)
        name = ctypes.create_string_buffer(96)
        if _nvml.nvmlDeviceGetName(_handle, name, 96) == 0:
            out["name"] = name.value.decode("utf-8", "replace")
        temp = ctypes.c_uint()
        if _nvml.nvmlDeviceGetTemperature(_handle, 0, ctypes.byref(temp)) == 0:
            out["temperature"] = int(temp.value)
        return out


def total_bytes():
    i = info()
    return i.get("total") if i else None


# ---------------------------------------------------------------- the computer's memory (for the final render screen)

def process_ram(pid_or_proc):
    """Memory in use by a process (bytes), or None. Windows: the working set (psapi); elsewhere /proc."""
    try:
        if os.name == "nt":
            class _PMC(ctypes.Structure):
                _fields_ = [("cb", ctypes.c_ulong), ("PageFaultCount", ctypes.c_ulong), ("PeakWorkingSetSize", ctypes.c_size_t),
                            ("WorkingSetSize", ctypes.c_size_t), ("QuotaPeakPagedPoolUsage", ctypes.c_size_t),
                            ("QuotaPagedPoolUsage", ctypes.c_size_t), ("QuotaPeakNonPagedPoolUsage", ctypes.c_size_t),
                            ("QuotaNonPagedPoolUsage", ctypes.c_size_t), ("PagefileUsage", ctypes.c_size_t),
                            ("PeakPagefileUsage", ctypes.c_size_t), ("PrivateUsage", ctypes.c_size_t)]
            handle = getattr(pid_or_proc, "_handle", None)
            if handle is None:
                return None
            pmc = _PMC()
            pmc.cb = ctypes.sizeof(_PMC)
            if not ctypes.WinDLL("psapi").GetProcessMemoryInfo(ctypes.c_void_p(int(handle)), ctypes.byref(pmc), pmc.cb):
                return None
            return int(pmc.WorkingSetSize)
        pid = getattr(pid_or_proc, "pid", pid_or_proc)
        with open(f"/proc/{int(pid)}/status") as f:
            for line in f:
                if line.startswith("VmRSS:"):
                    return int(line.split()[1]) * 1024
    except Exception:
        return None
    return None


def system_ram():
    """(used, total) bytes of the computer's memory, or (None, None)."""
    try:
        if os.name == "nt":
            class _MS(ctypes.Structure):
                _fields_ = [("dwLength", ctypes.c_ulong), ("dwMemoryLoad", ctypes.c_ulong), ("ullTotalPhys", ctypes.c_ulonglong),
                            ("ullAvailPhys", ctypes.c_ulonglong), ("ullTotalPageFile", ctypes.c_ulonglong),
                            ("ullAvailPageFile", ctypes.c_ulonglong), ("ullTotalVirtual", ctypes.c_ulonglong),
                            ("ullAvailVirtual", ctypes.c_ulonglong), ("ullAvailExtendedVirtual", ctypes.c_ulonglong)]
            ms = _MS()
            ms.dwLength = ctypes.sizeof(_MS)
            if not ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(ms)):
                return None, None
            return int(ms.ullTotalPhys - ms.ullAvailPhys), int(ms.ullTotalPhys)
        info = {}
        with open("/proc/meminfo") as f:
            for line in f:
                k, v = line.split(":", 1)
                info[k] = int(v.split()[0]) * 1024
        return info["MemTotal"] - info.get("MemAvailable", info.get("MemFree", 0)), info["MemTotal"]
    except Exception:
        return None, None
