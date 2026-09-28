import ctypes
import sys
import win32console
from colorama import just_fix_windows_console

kernel32 = ctypes.windll.kernel32
_user32 = ctypes.WinDLL('user32', use_last_error=True)
_GetConsoleWindow = kernel32.GetConsoleWindow
_GetConsoleWindow.restype = ctypes.c_void_p
_SetWindowPos = _user32.SetWindowPos
_SetWindowPos.argtypes = (
    ctypes.c_void_p, ctypes.c_void_p,
    ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int,
    ctypes.c_uint,
)
_SetWindowPos.restype = ctypes.c_bool

HWND_TOPMOST = ctypes.c_void_p(-1)
HWND_NOTOPMOST = ctypes.c_void_p(-2)
SWP_NOSIZE = 0x0001
SWP_NOMOVE = 0x0002
SWP_NOACTIVATE = 0x0010

try:
    freq_counter = ctypes.c_int64()
    kernel32.QueryPerformanceFrequency(ctypes.byref(freq_counter))
    PERF_FREQ = freq_counter.value
except Exception:
    PERF_FREQ = 10000000

_winmm = None

def _stdout_is_idle():
    try:
        if sys.stdout is not None:
            mod = sys.stdout.__class__.__module__ or ""
            if "idlelib" in mod:
                return True
    except Exception:
        pass
    return "idlelib" in sys.modules

def get_console_window():
    try:
        return _GetConsoleWindow()
    except Exception:
        return 0

def set_always_on_top(enabled):
    hwnd = get_console_window()
    if not hwnd:
        return False
    try:
        insert_after = HWND_TOPMOST if enabled else HWND_NOTOPMOST
        result = _SetWindowPos(
            hwnd, insert_after,
            0, 0, 0, 0,
            SWP_NOMOVE | SWP_NOSIZE | SWP_NOACTIVATE,
        )
        return bool(result)
    except Exception:
        return False

def init():
    global _winmm
    kernel32.SetConsoleOutputCP(65001)
    allocated = False
    try:
        win32console.AllocConsole()
        allocated = True
    except Exception:
        pass
    just_fix_windows_console()
    handle = kernel32.GetStdHandle(-11)
    mode = ctypes.c_uint32()
    kernel32.GetConsoleMode(handle, ctypes.byref(mode))
    mode.value |= 0x0004
    kernel32.SetConsoleMode(handle, mode)
    if allocated or _stdout_is_idle():
        try:
            sys.stdout = open("CONOUT$", "w", encoding="utf-8", buffering=1)
            sys.stderr = sys.stdout
        except Exception:
            pass
    try:
        _winmm = ctypes.WinDLL('winmm')
        _winmm.timeBeginPeriod(1)
    except Exception:
        _winmm = None

def cleanup():
    global _winmm
    if _winmm is not None:
        try:
            _winmm.timeEndPeriod(1)
        except Exception:
            pass
    _winmm = None

def get_perf_counter_ms():
    counter = ctypes.c_int64()
    kernel32.QueryPerformanceCounter(ctypes.byref(counter))
    return counter.value * 1000.0 / PERF_FREQ

def get_perf_counter_raw():
    counter = ctypes.c_int64()
    kernel32.QueryPerformanceCounter(ctypes.byref(counter))
    return counter.value