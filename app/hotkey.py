import ctypes
from ctypes import wintypes

WH_KEYBOARD_LL = 13
WM_KEYDOWN = 0x0100
LLKHF_INJECTED = 0x00000010
VK_LEFT = 0x25
VK_RIGHT = 0x27

_HOOKPROC = ctypes.WINFUNCTYPE(
    ctypes.c_long, ctypes.c_int, wintypes.WPARAM, wintypes.LPARAM
)


class _KBDLLHOOKSTRUCT(ctypes.Structure):
    _fields_ = [
        ('vkCode', wintypes.DWORD),
        ('scanCode', wintypes.DWORD),
        ('flags', wintypes.DWORD),
        ('time', wintypes.DWORD),
        ('dwExtraInfo', ctypes.c_void_p),
    ]


_user32 = ctypes.WinDLL('user32', use_last_error=True)
_CallNextHookEx = _user32.CallNextHookEx
_CallNextHookEx.argtypes = (wintypes.HHOOK, ctypes.c_int,
                            wintypes.WPARAM, wintypes.LPARAM)
_CallNextHookEx.restype = ctypes.c_long
_SetWindowsHookExW = _user32.SetWindowsHookExW
_SetWindowsHookExW.argtypes = (ctypes.c_int, _HOOKPROC,
                               wintypes.HINSTANCE, wintypes.DWORD)
_SetWindowsHookExW.restype = wintypes.HHOOK
_UnhookWindowsHookEx = _user32.UnhookWindowsHookEx
_UnhookWindowsHookEx.argtypes = (wintypes.HHOOK,)
_UnhookWindowsHookEx.restype = wintypes.BOOL


class DirectionHook:

    def __init__(self):
        self._hook = None
        self._proc = None
        self.on_left = None
        self.on_right = None

    def install(self):
        if self._hook is not None:
            return True

        def proc(nCode, wParam, lParam):
            try:
                if nCode == 0 and wParam == WM_KEYDOWN:
                    kb = ctypes.cast(lParam, ctypes.POINTER(_KBDLLHOOKSTRUCT)).contents
                    if not (kb.flags & LLKHF_INJECTED):
                        if kb.vkCode == VK_LEFT and self.on_left is not None:
                            self.on_left()
                            return 1
                        if kb.vkCode == VK_RIGHT and self.on_right is not None:
                            self.on_right()
                            return 1
            except Exception:
                pass
            return _CallNextHookEx(None, nCode, wParam, lParam)

        self._proc = _HOOKPROC(proc)
        self._hook = _SetWindowsHookExW(WH_KEYBOARD_LL, self._proc, None, 0)
        return self._hook is not None

    def uninstall(self):
        if self._hook is not None:
            try:
                _UnhookWindowsHookEx(self._hook)
            except Exception:
                pass
            self._hook = None
        self._proc = None
