import ctypes
from ctypes import wintypes
import keyboard

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
_MapVirtualKeyW = _user32.MapVirtualKeyW
_MapVirtualKeyW.argtypes = (wintypes.UINT, wintypes.UINT)
_MapVirtualKeyW.restype = wintypes.UINT

def _key_name_to_vks(key_name):
    if not key_name:
        return set()
    name = str(key_name).strip().lower()
    if name == "left":
        return {VK_LEFT}
    if name == "right":
        return {VK_RIGHT}
    try:
        scan_codes = keyboard.key_to_scan_codes(name) or ()
    except Exception:
        return set()
    result = set()
    for scan_code in scan_codes:
        try:
            vk = _MapVirtualKeyW(int(scan_code), 3)
        except Exception:
            vk = 0
        if vk:
            result.add(int(vk))
    return result

def bound_control_keys(hotkey, offset_left_key, offset_right_key,
                       macro_end_mode="both", output_keys=()):
    output = {str(key).strip().lower() for key in (output_keys or ())}
    candidates = [hotkey, offset_left_key, offset_right_key]
    if macro_end_mode in ("esc", "both"):
        candidates.append("esc")
    result = []
    for key in candidates:
        name = str(key or "").strip().lower()
        if not name or name in output or name in result:
            continue
        result.append(name)
    return result

class DirectionHook:
    def __init__(self, left_key="left", right_key="right", suppress=True):
        self._hook = None
        self._proc = None
        self.on_left = None
        self.on_right = None
        self._left_vks = set()
        self._right_vks = set()
        self.suppress = bool(suppress)
        self.configure(left_key, right_key)

    def configure(self, left_key, right_key):
        self._left_vks = _key_name_to_vks(left_key)
        self._right_vks = _key_name_to_vks(right_key)

    def set_suppress(self, suppress):
        self.suppress = bool(suppress)

    def _handle_key_event(self, vk_code, injected=False):
        if injected:
            return False
        if vk_code in self._left_vks and self.on_left is not None:
            self.on_left()
            return self.suppress
        if vk_code in self._right_vks and self.on_right is not None:
            self.on_right()
            return self.suppress
        return False

    def install(self):
        if self._hook is not None:
            return True
        def proc(nCode, wParam, lParam):
            try:
                if nCode == 0 and wParam == WM_KEYDOWN:
                    kb = ctypes.cast(lParam, ctypes.POINTER(_KBDLLHOOKSTRUCT)).contents
                    if self._handle_key_event(kb.vkCode,
                                              bool(kb.flags & LLKHF_INJECTED)):
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