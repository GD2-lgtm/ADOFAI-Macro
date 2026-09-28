from colorama import Fore

COLOR_MAP = {
    "header": Fore.LIGHTCYAN_EX,
    "key": Fore.CYAN,
    "delay": Fore.GREEN,
    "system": Fore.MAGENTA,
    "status": Fore.WHITE,
    "error": Fore.RED,
}

DEFAULT_KEYS = ["d", "k"]

TK_KEYSYM_TO_KEY = {
    "minus": "-",
    "quoteleft": "`",
    "quoteright": "'",
    "kp_minus": "num minus",
    "kp_plus": "num plus",
    "control_r": "right ctrl",
    "control_l": "left ctrl",
    "shift_r": "right shift",
    "shift_l": "left shift",
    "alt_r": "right alt",
    "alt_l": "left alt",
    "win_r": "right windows",
    "win_l": "left windows",
    "return": "enter",
    "escape": "esc",
    "space": "spacebar",
    "prior": "page up",
    "next": "page down",
    "print": "print screen",
}