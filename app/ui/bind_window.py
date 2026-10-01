import ctypes

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QDialog, QHBoxLayout, QLabel, QPushButton, QVBoxLayout

from .. import i18n

_user32 = ctypes.WinDLL('user32', use_last_error=True)


def _vk_down(vk):
    try:
        return bool(_user32.GetAsyncKeyState(vk) & 0x8000)
    except Exception:
        return False

QT_KEY_TO_NAME = {
    Qt.Key_Escape: "esc",
    Qt.Key_Backspace: "backspace",
    Qt.Key_Return: "enter",
    Qt.Key_Enter: "enter",
    Qt.Key_Insert: "insert",
    Qt.Key_Delete: "delete",
    Qt.Key_Home: "home",
    Qt.Key_End: "end",
    Qt.Key_PageUp: "page up",
    Qt.Key_PageDown: "page down",
    Qt.Key_Up: "up",
    Qt.Key_Down: "down",
    Qt.Key_Left: "left",
    Qt.Key_Right: "right",
    Qt.Key_Space: "spacebar",
    Qt.Key_Print: "print screen",
    Qt.Key_ScrollLock: "scroll lock",
    Qt.Key_Pause: "pause",
    Qt.Key_CapsLock: "caps lock",
    Qt.Key_NumLock: "num lock",
    Qt.Key_Menu: "menu",
    Qt.Key_Backtab: "tab",
    Qt.Key_Tab: "tab",
}
for _i in range(1, 25):
    QT_KEY_TO_NAME[getattr(Qt, "Key_F%d" % _i)] = "f%d" % _i

CHAR_TO_NAME = {
    ";": "semicolon",
    ",": "comma",
    ".": "period",
    "`": "grave",
    "\\": "backslash",
    "'": "apostrophe",
    "/": "slash",
}

SHIFTED_TO_BASE = {
    "!": "1", "@": "2", "#": "3", "$": "4", "%": "5",
    "^": "6", "&": "7", "*": "8", "(": "9", ")": "0",
    "~": "grave", "_": "-", "+": "=",
    "{": "[", "}": "]", "|": "backslash",
    ":": "semicolon", '"': "apostrophe",
    "<": "comma", ">": "period", "?": "slash",
}

MODIFIER_DEFAULT = {
    Qt.Key_Shift: "left shift",
    Qt.Key_Control: "left ctrl",
    Qt.Key_Alt: "left alt",
    Qt.Key_Meta: "left windows",
}
MODIFIER_SCAN_TO_NAME = {
    0x2A: "left shift", 0x36: "right shift",
    0x1D: "left ctrl", 0xE01D: "right ctrl",
    0x38: "left alt", 0xE038: "right alt",
    0x5B: "left windows", 0x5C: "left windows",
    0xE05B: "left windows", 0xE05C: "right windows",
}
MODIFIER_VK_TO_NAME = {
    0xA0: "left shift", 0xA1: "right shift",
    0xA2: "left ctrl", 0xA3: "right ctrl",
    0xA4: "left alt", 0xA5: "right alt",
    0x5B: "left windows", 0x5C: "right windows",
}
MODIFIER_STATE_VKS = {
    Qt.Key_Shift: (0xA0, 0xA1, "left shift", "right shift"),
    Qt.Key_Control: (0xA2, 0xA3, "left ctrl", "right ctrl"),
    Qt.Key_Alt: (0xA4, 0xA5, "left alt", "right alt"),
    Qt.Key_Meta: (0x5B, 0x5C, "left windows", "right windows"),
}


def _modifier_from_state(key):
    left_vk, right_vk, left_name, right_name = MODIFIER_STATE_VKS[key]
    if _vk_down(left_vk):
        return left_name
    if _vk_down(right_vk):
        return right_name
    return None

_IGNORED_KEYS = (Qt.Key_CapsLock,)


class BindWindow(QDialog):

    def __init__(self, parent, title):
        super().__init__(parent)
        self.setWindowTitle(title)
        self.setFixedSize(300, 150)
        self.setModal(True)
        self.setFocusPolicy(Qt.StrongFocus)
        self.key = None

        layout = QVBoxLayout(self)

        self.label = QLabel()
        i18n.text(self.label, "bind.prompt")
        self.label.setAlignment(Qt.AlignCenter)
        layout.addWidget(self.label)

        self.btn_layout = QHBoxLayout()
        layout.addLayout(self.btn_layout)

    def showEvent(self, event):
        super().showEvent(event)
        self.setFocus()

    def keyPressEvent(self, event):
        key = event.key()
        if key in _IGNORED_KEYS:
            event.ignore()
            return

        name = None
        if key in MODIFIER_DEFAULT:
            if event.isAutoRepeat():
                return
            name = MODIFIER_SCAN_TO_NAME.get(event.nativeScanCode() & 0xFFFF)
            if name is None:
                name = MODIFIER_VK_TO_NAME.get(event.nativeVirtualKey())
            if name is None:
                name = _modifier_from_state(key)
            if name is None:
                name = MODIFIER_DEFAULT[key]
        else:
            text = event.text()
            if text and text.isprintable() and not text.isspace():
                t = text.lower()
                name = CHAR_TO_NAME.get(t, SHIFTED_TO_BASE.get(t, t))
            else:
                name = QT_KEY_TO_NAME.get(key)
        if name is None:
            return

        # The window is modal, so the language cannot change while it is open.
        self.label.setText(i18n.tr("bind.confirm", name=name))

        while self.btn_layout.count():
            item = self.btn_layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()

        ok_btn = QPushButton()
        i18n.text(ok_btn, "common.ok")
        ok_btn.clicked.connect(lambda: self.finish_bind(name))
        cancel_btn = QPushButton()
        i18n.text(cancel_btn, "common.cancel")
        cancel_btn.clicked.connect(self.reject)
        self.btn_layout.addWidget(ok_btn)
        self.btn_layout.addStretch(1)
        self.btn_layout.addWidget(cancel_btn)

    def finish_bind(self, key):
        self.key = key
        self.accept()
