import ctypes
import keyboard

KEYEVENTF_EXTENDEDKEY = 0x0001
KEYEVENTF_KEYUP = 0x0002
KEYEVENTF_SCANCODE = 0x0008
INPUT_KEYBOARD = 1

class KEYBDINPUT(ctypes.Structure):
    _fields_ = (('wVk', ctypes.c_ushort), ('wScan', ctypes.c_ushort),
                ('dwFlags', ctypes.c_uint), ('time', ctypes.c_uint),
                ('dwExtraInfo', ctypes.POINTER(ctypes.c_ulong)))

class MOUSEINPUT(ctypes.Structure):
    _fields_ = (('dx', ctypes.c_long), ('dy', ctypes.c_long),
                ('mouseData', ctypes.c_uint), ('dwFlags', ctypes.c_uint),
                ('time', ctypes.c_uint), ('dwExtraInfo', ctypes.POINTER(ctypes.c_ulong)))

class INPUT_UNION(ctypes.Union):
    _fields_ = (('mi', MOUSEINPUT), ('ki', KEYBDINPUT))

class INPUT(ctypes.Structure):
    _fields_ = (('type', ctypes.c_uint), ('u', INPUT_UNION))

_user32 = ctypes.WinDLL('user32', use_last_error=True)
_SendInput = _user32.SendInput
_SendInput.argtypes = (ctypes.c_uint, ctypes.POINTER(INPUT), ctypes.c_int)
_SendInput.restype = ctypes.c_uint

MAPVK_VSC_TO_VK = 1
MAPVK_VSC_TO_VK_EX = 3
_MapVirtualKeyW = _user32.MapVirtualKeyW
_MapVirtualKeyW.argtypes = (ctypes.c_uint, ctypes.c_uint)
_MapVirtualKeyW.restype = ctypes.c_uint

_GetMessageExtraInfo = _user32.GetMessageExtraInfo
_GetMessageExtraInfo.argtypes = []
_GetMessageExtraInfo.restype = ctypes.c_ulong

INJECTED_SIGNATURE = 0xAD0FA100

def is_injected_input():
    try:
        return (_GetMessageExtraInfo() & 0xFFFFFFFF) == (INJECTED_SIGNATURE & 0xFFFFFFFF)
    except Exception:
        return False

KEY_NAME_ALIASES = {
    "control r": "right ctrl",
    "control l": "left ctrl",
    "shift r": "right shift",
    "shift l": "left shift",
    "alt r": "right alt",
    "alt l": "left alt",
    "win r": "right windows",
    "win l": "left windows",
    "meta r": "right windows",
    "meta l": "left windows",
    "return": "enter",
    "escape": "esc",
    "space": "spacebar",
    "prior": "page up",
    "next": "page down",
    "print": "print screen",
}

def _resolve_entries(key_name):
    if isinstance(key_name, int):
        return None
    try:
        os_kb = keyboard._os_keyboard
        os_kb._setup_name_tables()
        normalized = keyboard._canonical_names.normalize_name(key_name)
        if normalized not in os_kb.from_name:
            normalized = KEY_NAME_ALIASES.get(normalized)
        if normalized:
            normalized = keyboard._canonical_names.normalize_name(normalized)
        entries = os_kb.from_name.get(normalized, [])
        if not entries:
            raise ValueError(f"Key {key_name!r} is not mapped to any known key.")
        
        keypad_canon = {
            (e[0] & 0xFF, e[1], bool(e[2] or e[0] >= 0xE000))
            for e in os_kb.keypad_keys
        }
        preferred = [
            e for _, e in entries
            if (e[0] & 0xFF, e[1], bool(e[2] or e[0] >= 0xE000)) not in keypad_canon
        ]
        return preferred if preferred else [e for _, e in entries]
    except Exception:
        return None

def resolve_key_codes(key_name):
    if isinstance(key_name, int):
        return [key_name]
    entries = _resolve_entries(key_name)
    if entries:
        best = {}
        for scan, vk, extended, _ in entries:
            code = (scan | (0x100 if extended else 0)) if scan else -vk
            prev = best.get(vk)
            if prev is None or (prev[1] and not extended):
                best[vk] = (code, extended)
        codes = [c for c, _ in best.values()]
        return codes
    return list(keyboard.key_to_scan_codes(key_name))

def resolve_key_vk(key_name):
    if isinstance(key_name, int):
        return -key_name if key_name < 0 else key_name
    code = resolve_key_codes(key_name)[0]
    if code < 0:
        return -code
    if code >= 0x100:
        vk = _MapVirtualKeyW(0xE000 | (code & 0xFF), MAPVK_VSC_TO_VK_EX)
        if vk:
            return vk
    return _MapVirtualKeyW(code & 0xFF, MAPVK_VSC_TO_VK_EX)

class KeyInjector:
    def __init__(self):
        self._cache = {}

    def _make(self, code, keyup):
        inp = INPUT()
        inp.type = INPUT_KEYBOARD
        flags = KEYEVENTF_KEYUP if keyup else 0
        if code > 0:
            if code >= 0x100:
                inp.u.ki.wScan = code & 0xFF
                flags |= KEYEVENTF_EXTENDEDKEY
            else:
                inp.u.ki.wScan = code
            flags |= KEYEVENTF_SCANCODE
        else:
            inp.u.ki.wVk = -code
        inp.u.ki.dwFlags = flags
        inp.u.ki.dwExtraInfo = ctypes.cast(
            INJECTED_SIGNATURE, ctypes.POINTER(ctypes.c_ulong)
        )
        return inp

    def input_for(self, code, keyup=False):
        key = (code, keyup)
        inp = self._cache.get(key)
        if inp is None:
            inp = self._cache[key] = self._make(code, keyup)
        return inp

    def send(self, inputs):
        n = len(inputs)
        if n == 0:
            return True
        arr = (INPUT * n)(*inputs)
        return _SendInput(n, arr, ctypes.sizeof(INPUT)) == n