import os

from PyQt5.QtCore import QEvent, QObject, QRegularExpression, Qt, QTimer, pyqtSignal
from PyQt5.QtGui import QColor, QFont, QRegularExpressionValidator, QTextCharFormat, QTextCursor
from PyQt5.QtWidgets import (
    QAction, QApplication, QCheckBox, QComboBox, QDialog, QFileDialog, QGroupBox,
    QHBoxLayout, QLabel, QLineEdit, QListWidget, QMainWindow, QMessageBox,
    QPushButton, QTextEdit, QVBoxLayout, QWidget,
)

import keyboard
from colorama import Fore, Style

from parser import ADOAngle, ADOLevelData

from .. import config as config_module
from .. import console
from ..constants import COLOR_MAP, DEFAULT_KEYS
from ..hotkey import DirectionHook
from ..playback import PlaybackEngine
from ..technique import STYLE_NAMES, STYLE_NAMES_LEGACY, AdvancedTechnique
from ..timeline import build_timeline
from .bind_window import BindWindow

APP_QSS = """
QMainWindow { background: #f0f2f5; }
QMenuBar { background: #ffffff; border-bottom: 1px solid #d8dce3; }
QMenuBar::item { padding: 5px 12px; background: transparent; }
QMenuBar::item:selected { background: #e3edf7; color: #0b57d0; border-radius: 4px; }
QMenu { background: #ffffff; border: 1px solid #d8dce3; padding: 4px; }
QMenu::item { padding: 5px 24px 5px 12px; border-radius: 4px; }
QMenu::item:selected { background: #e3edf7; }
QGroupBox {
    background: #ffffff;
    border: 1px solid #d8dce3;
    border-radius: 8px;
    margin-top: 12px;
    padding: 14px 10px 8px 10px;
    font-weight: 600;
    color: #33404f;
}
QGroupBox::title { subcontrol-origin: margin; left: 12px; padding: 0 5px; }
QPushButton {
    background: #ffffff; color: #263238;
    border: 1px solid #c9d1da; border-radius: 5px;
    padding: 5px 14px;
}
QPushButton:hover { background: #eef3f9; border-color: #8fb6d9; }
QPushButton:pressed { background: #e0e9f2; }
QPushButton:disabled { color: #aeb6c0; background: #f4f6f8; border-color: #e2e6ec; }
QPushButton#primaryBtn {
    background: #1a73e8; color: white; border: none; font-weight: 600;
}
QPushButton#primaryBtn:hover { background: #2f80ee; }
QLineEdit, QComboBox, QListWidget {
    background: #fbfcfe; border: 1px solid #c9d1da; border-radius: 5px;
    padding: 3px 6px; color: #1f2937;
}
QLineEdit:focus, QComboBox:focus { border-color: #1a73e8; }
QComboBox::drop-down { border: none; width: 20px; }
QListWidget { padding: 3px; }
QListWidget::item { padding: 3px 6px; border-radius: 4px; }
QListWidget::item:selected { background: #dce9fa; color: #0b57d0; }
QStatusBar { background: #e6eaf0; color: #44505e; }
QTextEdit, QPlainTextEdit { font-family: Consolas, monospace; }
"""


class _UIEvents(QObject):

    toggle = pyqtSignal()
    offset = pyqtSignal(float)
    offset_display = pyqtSignal(float)
    playback_finished = pyqtSignal()
    debounce_schedule = pyqtSignal()


def _append_colored(text_edit, line, color=None):
    fmt = QTextCharFormat()
    if color:
        fmt.setForeground(QColor(color))
    cursor = text_edit.textCursor()
    cursor.movePosition(QTextCursor.End)
    cursor.insertText(line + "\n", fmt)


class _FocusClearFilter(QObject):

    _KEEP_FOCUS = (
        QLineEdit, QComboBox, QPushButton, QCheckBox, QListWidget, QTextEdit,
    )

    def __init__(self, window):
        super().__init__(window)
        self._window = window

    def eventFilter(self, obj, event):
        if event.type() == QEvent.MouseButtonPress and event.button() == Qt.LeftButton:
            widget = QApplication.widgetAt(event.globalPos())
            if widget is not None and not isinstance(widget, self._KEEP_FOCUS):
                focus_widget = self._window.focusWidget()
                if focus_widget is not None:
                    focus_widget.clearFocus()
        return super().eventFilter(obj, event)


class ADOFAIPlayer(QMainWindow):
    def __init__(self, enable_parse_log=False):
        super().__init__()
        self._parse_log_enabled = enable_parse_log
        self.setWindowTitle("ADOFAI Macro v4.0")
        self.resize(780, 640)
        self.setMinimumSize(740, 560)
        self.setAcceptDrops(True)

        self._focus_manager = _FocusClearFilter(self)
        self.installEventFilter(self._focus_manager)

        self.events = _UIEvents(self)
        self.events.toggle.connect(self.toggle_play)
        self.events.offset.connect(self._apply_offset)
        self.events.offset_display.connect(self._update_offset_display)
        self.events.playback_finished.connect(self._on_playback_finished)
        self._debounce_timer = QTimer(self)
        self._debounce_timer.setSingleShot(True)
        self._debounce_timer.timeout.connect(self._reset_debounce)
        self.events.debounce_schedule.connect(lambda: self._debounce_timer.start(200))

        self.config = config_module.load_config()
        left = self.config.get("left_keys")
        right = self.config.get("right_keys")
        if left is None or right is None:
            old_keys = self.config.get("keys", DEFAULT_KEYS.copy())
            mid = len(old_keys) // 2
            left, right = old_keys[:mid], old_keys[mid:]
        self.left_keys = list(left)
        self.right_keys = list(right)
        self.macro_hotkey = self.config.get("hotkey", "insert")
        self.disable_trigger = False

        self._trigger_hook = None
        self._direction_hook = None
        self._hotkey_configs = []
        self._toggle_debounce = False

        self.file_path = ""
        self.timeline = []

        self.adofai_angle = None
        self.cumulative_times = []
        self.macro_key_info = []
        self.hold_dict = {}

        self.parse_logs = []

        self.playback = PlaybackEngine(self.log_message)
        self._sync_custom_keys()

        tech = self.config.get("technique")
        self.technique_enabled = tech.get("enabled", False) if isinstance(tech, dict) else bool(tech)
        style_cfg = tech.get("style", 0) if isinstance(tech, dict) else 0
        if isinstance(style_cfg, str):
            self.technique_style = style_cfg if style_cfg in STYLE_NAMES else STYLE_NAMES[0]
        else:
            idx = int(style_cfg)
            if 0 <= idx < len(STYLE_NAMES_LEGACY):
                self.technique_style = STYLE_NAMES_LEGACY[idx]
            else:
                self.technique_style = STYLE_NAMES[0]
        if isinstance(tech, dict) and "single_kps" in tech:
            self.technique_single_kps = float(tech.get("single_kps", 6.5))
        else:
            old_slow = tech.get("slow_bpm", 780.0) if isinstance(tech, dict) else 780.0
            self.technique_single_kps = old_slow / 2.0 / 60.0
        self.technique_main_hand = tech.get("main_hand", "right") if isinstance(tech, dict) else "right"
        self.technique_follow_speed = tech.get("follow_speed", True) if isinstance(tech, dict) else True
        self.verbose = self.config.get("verbose", True)

        self.create_widgets()
        self._register_trigger_key()
        self.update_buttons_state()


    def _update_log_count(self):
        if self._parse_log_enabled and hasattr(self, "lbl_log_count"):
            self.lbl_log_count.setText(f"日志: {len(self.parse_logs)} 条")

    def _parse_logger(self, tag, message):
        if not self._parse_log_enabled:
            return
        line = f"[{tag}] {message}"
        self.parse_logs.append(line)
        self.log_message(line, "system")

    def save_parse_logs(self):
        if not self.parse_logs:
            QMessageBox.information(self, "提示", "没有可保存的日志")
            return
        file_path, _ = QFileDialog.getSaveFileName(
            self,
            "保存谱面解析日志",
            f"adofai_parse_log_{os.path.basename(self.file_path) if self.file_path else 'unknown'}.txt",
            "文本文件 (*.txt);;所有文件 (*.*)",
        )
        if file_path:
            try:
                with open(file_path, "w", encoding="utf-8") as f:
                    f.write("\n".join(self.parse_logs))
                self.log_message(f"日志已保存: {file_path}", "system")
            except Exception as e:
                self.log_message(f"保存日志失败: {e}", "error")

    def show_parse_logs(self):
        win = QDialog(self)
        win.setWindowTitle("谱面解析日志")
        win.resize(900, 700)

        layout = QVBoxLayout(win)
        text = QTextEdit()
        text.setReadOnly(True)
        text.setFont(QFont("Consolas", 9))
        layout.addWidget(text)

        btn_layout = QHBoxLayout()
        btn_save = QPushButton("保存到文件")
        btn_save.clicked.connect(self.save_parse_logs)
        btn_close = QPushButton("关闭")
        btn_close.clicked.connect(win.close)
        btn_layout.addWidget(btn_save)
        btn_layout.addStretch(1)
        btn_layout.addWidget(btn_close)
        layout.addLayout(btn_layout)

        for line in self.parse_logs:
            if line.startswith("[ERROR]") or line.startswith("[WARNING]"):
                color = "#d32f2f"
            elif line.startswith("[HOLD_FLOOR]"):
                color = "#ff9800"
            elif line.startswith("[ABS_BEAT]"):
                color = "#1976d2"
            elif line.startswith("[KEYINFO]"):
                color = "#388e3c"
            else:
                color = None
            _append_colored(text, line, color)

        win.exec_()


    def _create_menu_bar(self):
        menubar = self.menuBar()

        file_menu = menubar.addMenu("文件(&F)")
        act_open = QAction("加载谱面...", self)
        act_open.setShortcut("Ctrl+O")
        act_open.triggered.connect(self.select_file)
        file_menu.addAction(act_open)
        file_menu.addSeparator()
        act_import = QAction("导入配置...", self)
        act_import.triggered.connect(self.import_config_file)
        file_menu.addAction(act_import)
        act_export = QAction("导出配置...", self)
        act_export.triggered.connect(self.export_config_file)
        file_menu.addAction(act_export)
        file_menu.addSeparator()
        act_quit = QAction("退出", self)
        act_quit.setShortcut("Ctrl+Q")
        act_quit.triggered.connect(self.close)
        file_menu.addAction(act_quit)

    def create_widgets(self):
        central = QWidget()
        self.setCentralWidget(central)
        main_layout = QVBoxLayout(central)
        main_layout.setContentsMargins(12, 8, 12, 8)
        main_layout.setSpacing(8)

        self._create_menu_bar()

        file_box = QGroupBox("谱面")
        file_layout = QHBoxLayout(file_box)
        btn_select = QPushButton("加载谱面")
        btn_select.setObjectName("primaryBtn")
        btn_select.setToolTip("选择 .adofai 谱面文件 (Ctrl+O),或直接拖放文件到窗口")
        btn_select.clicked.connect(self.select_file)
        file_layout.addWidget(btn_select)
        self.lbl_file = QLabel("未选择谱面")
        self.lbl_file.setStyleSheet("color: #7a8694;")
        self.lbl_file.setToolTip("")
        file_layout.addWidget(self.lbl_file, 1)
        main_layout.addWidget(file_box)

        keys_box = QGroupBox("输出按键")
        keys_layout = QHBoxLayout(keys_box)
        keys_layout.setSpacing(16)
        self._create_key_list(keys_box, "左手按键", "left", "left_listbox",
                              "left_del_btn", "left_up_btn", "left_down_btn")
        self._create_key_list(keys_box, "右手按键", "right", "right_listbox",
                              "right_del_btn", "right_up_btn", "right_down_btn")
        main_layout.addWidget(keys_box)

        control_box = QGroupBox("播放控制")
        control_layout = QVBoxLayout(control_box)
        control_layout.setSpacing(6)

        row1 = QHBoxLayout()
        row1.setSpacing(8)
        row1.addWidget(QLabel("触发键:"))
        self.lbl_hotkey = QLabel(self.macro_hotkey)
        self.lbl_hotkey.setStyleSheet("color: #0b57d0; font-weight: 600;")
        row1.addWidget(self.lbl_hotkey)
        btn_bind_trigger = QPushButton("绑定")
        btn_bind_trigger.setToolTip("重新绑定全局触发键")
        btn_bind_trigger.clicked.connect(lambda: self.bind_key("trigger"))
        row1.addWidget(btn_bind_trigger)

        row1.addStretch(1)
        row1.addWidget(QLabel("倍速:"))
        self.speed_edit = QLineEdit("1.0")
        self.speed_edit.setValidator(self._make_validator(r"\d*\.?\d*"))
        self.speed_edit.setFixedWidth(50)
        self.speed_edit.setToolTip("播放倍速")
        self.speed_edit.editingFinished.connect(self._on_speed_changed)
        row1.addWidget(self.speed_edit)
        row1.addWidget(QLabel("x"))
        control_layout.addLayout(row1)

        row2 = QHBoxLayout()
        row2.setSpacing(8)
        row2.addWidget(QLabel("按键时长:"))
        self.press_duration_edit = QLineEdit(str(self.config.get("press_duration", 40)))
        self.press_duration_edit.setValidator(self._make_validator(r"\d*"))
        self.press_duration_edit.setFixedWidth(50)
        self.press_duration_edit.setToolTip("普通按键的按下持续时间(ms)")
        row2.addWidget(self.press_duration_edit)
        row2.addWidget(QLabel("ms"))

        row2.addSpacing(14)
        row2.addWidget(QLabel("偏移:"))
        self.offset_label = QLabel("+0")
        self.offset_label.setStyleSheet("color: black; font-weight: 600;")
        self.offset_label.setMinimumWidth(44)
        row2.addWidget(self.offset_label)
        row2.addWidget(QLabel("ms"))
        row2.addWidget(QLabel("(←提前 延后→)"))

        row2.addStretch(1)
        self.verbose_check = QCheckBox("详细输出")
        self.verbose_check.setChecked(self.verbose)
        self.verbose_check.setToolTip("打印每个按键的按下 / 释放时间")
        row2.addWidget(self.verbose_check)
        control_layout.addLayout(row2)

        main_layout.addWidget(control_box)

        technique_box = QGroupBox("手法模拟")
        technique_layout = QHBoxLayout(technique_box)
        technique_layout.setSpacing(10)
        self.technique_check = QCheckBox("启用手法模拟")
        self.technique_check.setChecked(self.technique_enabled)
        self.technique_check.setToolTip("用拟人双手多指手法分配按键(内轮 V3.3)")
        technique_layout.addWidget(self.technique_check)
        technique_layout.addWidget(QLabel("风格:"))
        self.technique_style_combo = QComboBox()
        self.technique_style_combo.addItems(STYLE_NAMES)
        self.technique_style_combo.setCurrentText(self.technique_style)
        self.technique_style_combo.setFixedWidth(90)
        technique_layout.addWidget(self.technique_style_combo)
        technique_layout.addWidget(QLabel("单指KPS:"))
        self.single_kps_edit = QLineEdit(str(self.technique_single_kps))
        self.single_kps_edit.setValidator(self._make_validator(r"\d*\.?\d*"))
        self.single_kps_edit.setFixedWidth(55)
        self.single_kps_edit.setToolTip("单手单指可达到的按键速度(次/秒),决定轮指阈值")
        technique_layout.addWidget(self.single_kps_edit)
        technique_layout.addWidget(QLabel("主手:"))
        self.main_hand_combo = QComboBox()
        self.main_hand_combo.addItems(["右手", "左手"])
        self.main_hand_combo.setCurrentText(
            "右手" if self.technique_main_hand == "right" else "左手"
        )
        self.main_hand_combo.setFixedWidth(70)
        technique_layout.addWidget(self.main_hand_combo)
        self.technique_follow_speed_check = QCheckBox("根据倍速进行解析")
        self.technique_follow_speed_check.setChecked(self.technique_follow_speed)
        self.technique_follow_speed_check.setToolTip(
            "勾选后,手法模拟按倍速缩放按键间隔再分配手指\n"
            "(如 2x 倍速时按 2 倍按键密度解析手法);\n"
            "不勾选则始终按 1x 原速解析"
        )
        self.technique_follow_speed_check.toggled.connect(self._on_speed_changed)
        technique_layout.addWidget(self.technique_follow_speed_check)
        technique_layout.addStretch(1)
        main_layout.addWidget(technique_box)

        if self._parse_log_enabled:
            log_box = QGroupBox("谱面解析日志")
            log_layout = QHBoxLayout(log_box)
            btn_view = QPushButton("查看日志")
            btn_view.clicked.connect(self.show_parse_logs)
            btn_save_log = QPushButton("保存日志")
            btn_save_log.clicked.connect(self.save_parse_logs)
            log_layout.addWidget(btn_view)
            log_layout.addWidget(btn_save_log)
            self.lbl_log_count = QLabel("日志: 0 条")
            self.lbl_log_count.setStyleSheet("color: gray;")
            log_layout.addWidget(self.lbl_log_count)
            log_layout.addStretch(1)
            main_layout.addWidget(log_box)

        status = self.statusBar()
        self.status_label = QLabel("就绪")
        self.status_label.setStyleSheet("color: gray;")
        status.addWidget(self.status_label)

        self.refresh_key_list()

    def _make_validator(self, pattern):
        return QRegularExpressionValidator(QRegularExpression(pattern), self)

    def _set_status(self, text, color="gray"):
        self.status_label.setText(text)
        self.status_label.setStyleSheet(f"color: {color};")


    def _create_key_list(self, parent, title, key_type, listbox_attr,
                         del_attr, up_attr, down_attr):
        panel = QWidget()
        vlayout = QVBoxLayout(panel)
        vlayout.setContentsMargins(0, 0, 0, 0)
        vlayout.setSpacing(6)

        header = QLabel(title)
        header.setStyleSheet("color: #33404f; font-weight: 600;")
        vlayout.addWidget(header)

        listbox = QListWidget()
        listbox.setFixedHeight(130)
        listbox.setToolTip("双击列表项可直接修改该按键")
        listbox.itemDoubleClicked.connect(lambda item: self._rebind_key(listbox, key_type))
        vlayout.addWidget(listbox)
        setattr(self, listbox_attr, listbox)

        btn_row = QHBoxLayout()
        btn_row.setSpacing(6)
        add_btn = QPushButton("＋ 添加")
        add_btn.setToolTip("绑定一个新按键")
        add_btn.clicked.connect(lambda: self.bind_key(key_type))
        del_btn = QPushButton("－ 删除")
        del_btn.setToolTip("删除选中按键")
        del_btn.clicked.connect(lambda: self._delete_selected(listbox, key_type))
        up_btn = QPushButton("↑ 上移")
        up_btn.clicked.connect(lambda: self._move_item(listbox, key_type, -1))
        down_btn = QPushButton("↓ 下移")
        down_btn.clicked.connect(lambda: self._move_item(listbox, key_type, 1))
        for btn in (add_btn, del_btn, up_btn, down_btn):
            btn_row.addWidget(btn, 1)
        vlayout.addLayout(btn_row)

        parent.layout().addWidget(panel, 1)

        setattr(self, del_attr, del_btn)
        setattr(self, up_attr, up_btn)
        setattr(self, down_attr, down_btn)

    def _keys_of(self, key_type):
        return self.left_keys if key_type == "left" else self.right_keys

    def _sync_custom_keys(self):
        self.custom_keys = self.left_keys + self.right_keys
        self.playback.keys = self.custom_keys

    def bind_key(self, key_type):
        self.disable_trigger = True
        title = {
            "trigger": "绑定触发键",
            "left": "绑定左手按键",
            "right": "绑定右手按键",
        }[key_type]
        win = BindWindow(self, title)
        try:
            accepted = win.exec_() == QDialog.Accepted
        finally:
            self.disable_trigger = False

        if accepted and win.key:
            key = win.key
            if key_type == "trigger":
                if key in self.left_keys + self.right_keys:
                    QMessageBox.warning(self, "冲突", "触发键不能与输出键重复！")
                    return
                self.macro_hotkey = key
                self.config["hotkey"] = self.macro_hotkey
                self.lbl_hotkey.setText(key)
                self._register_trigger_key()
            else:
                if key == self.macro_hotkey:
                    QMessageBox.warning(self, "冲突", "输出键不能与触发键相同！")
                    return
                if key in self.left_keys + self.right_keys:
                    QMessageBox.warning(self, "冲突", "该按键已存在于按键列表中！")
                    return
                self._keys_of(key_type).append(key)
                self._sync_custom_keys()
                self.refresh_key_list()
                self.update_buttons_state()

    def _rebind_key(self, listbox, key_type):
        row = listbox.currentRow()
        if row < 0:
            return
        current = self._keys_of(key_type)[row]
        self.disable_trigger = True
        win = BindWindow(self, "修改按键")
        try:
            accepted = win.exec_() == QDialog.Accepted
        finally:
            self.disable_trigger = False
        if not (accepted and win.key):
            return
        key = win.key
        if key == current:
            return
        if key == self.macro_hotkey:
            QMessageBox.warning(self, "冲突", "输出键不能与触发键相同！")
            return
        if key in self.left_keys + self.right_keys:
            QMessageBox.warning(self, "冲突", "该按键已存在于按键列表中！")
            return
        self._keys_of(key_type)[row] = key
        self._sync_custom_keys()
        self.refresh_key_list()
        listbox.setCurrentRow(row)
        self.update_buttons_state()

    def _delete_selected(self, listbox, key_type):
        row = listbox.currentRow()
        if row >= 0:
            del self._keys_of(key_type)[row]
            self._sync_custom_keys()
            self.refresh_key_list()
            self.update_buttons_state()

    def _move_item(self, listbox, key_type, direction):
        row = listbox.currentRow()
        if row < 0:
            return
        keys = self._keys_of(key_type)
        new_row = row + direction
        if 0 <= new_row < len(keys):
            keys.insert(new_row, keys.pop(row))
            self._sync_custom_keys()
            self.refresh_key_list()
            listbox.setCurrentRow(new_row)
            self.update_buttons_state()

    def refresh_key_list(self):
        for listbox, keys in [
            (self.left_listbox, self.left_keys),
            (self.right_listbox, self.right_keys),
        ]:
            listbox.clear()
            for key in keys:
                listbox.addItem(key)

    def update_buttons_state(self):
        for listbox, del_attr, up_attr, down_attr in [
            (self.left_listbox, "left_del_btn", "left_up_btn", "left_down_btn"),
            (self.right_listbox, "right_del_btn", "right_up_btn", "right_down_btn"),
        ]:
            has_items = listbox.count() > 0
            for attr in [del_attr, up_attr, down_attr]:
                getattr(self, attr).setEnabled(has_items)

    def _register_trigger_key(self):
        if self._trigger_hook is not None:
            try:
                keyboard.unhook(self._trigger_hook)
            except Exception:
                pass

        try:
            self._trigger_hook = keyboard.on_press_key(
                self.macro_hotkey.lower(),
                self._on_hotkey_trigger,
                suppress=True
            )
        except Exception as e:
            self.log_message(f"注册触发键失败: {e}", "error")

    def _register_direction_keys(self):
        if self._direction_hook is None:
            self._direction_hook = DirectionHook()
        self._direction_hook.on_left = self._on_hotkey_left
        self._direction_hook.on_right = self._on_hotkey_right
        if not self._direction_hook.install():
            self.log_message("注册方向键钩子失败", "error")

    def _clear_direction_hooks(self):
        if self._direction_hook is not None:
            self._direction_hook.uninstall()

    def _on_hotkey_trigger(self, event=None):
        if self.disable_trigger or self._toggle_debounce:
            return
        self._toggle_debounce = True
        self.events.debounce_schedule.emit()
        self.events.toggle.emit()

    def _reset_debounce(self):
        self._toggle_debounce = False

    def _on_hotkey_left(self, event=None):
        if not self.playback.is_playing:
            return
        self.events.offset.emit(-1.0)

    def _on_hotkey_right(self, event=None):
        if not self.playback.is_playing:
            return
        self.events.offset.emit(1.0)

    def _apply_offset(self, delta: float):
        offset = self.playback.adjust_offset(delta)
        self._update_offset_display(offset)


    def select_file(self):
        file_path, _ = QFileDialog.getOpenFileName(self, "选择谱面文件", "", "ADOFAI文件 (*.adofai)")
        if file_path:
            self.load_chart(file_path)

    def load_chart(self, file_path):
        self.reset_state()
        self.file_path = file_path.replace("\\", "/")
        self.lbl_file.setText(os.path.basename(self.file_path))
        self.lbl_file.setToolTip(self.file_path)
        self.process_file()

    def dragEnterEvent(self, event):
        if event.mimeData().hasUrls():
            event.acceptProposedAction()

    def dropEvent(self, event):
        for url in event.mimeData().urls():
            path = url.toLocalFile()
            if path.lower().endswith(".adofai"):
                self.load_chart(path)
                event.acceptProposedAction()
                return

    def reset_state(self):
        self.playback.reset_offset()
        self._update_offset_display(0)
        self.speed_edit.setText("1.0")
        self.playback.stop()
        self.timeline = []
        self.parse_logs = []
        self._update_log_count()

    def _update_offset_display(self, offset_ms: float):
        self.offset_label.setText(f"{offset_ms:+.0f}")
        self._set_offset_color(offset_ms)

    def _set_offset_color(self, offset_ms: float):
        if offset_ms > 0:
            self.offset_label.setStyleSheet("color: red; font-weight: 600;")
        elif offset_ms < 0:
            self.offset_label.setStyleSheet("color: green; font-weight: 600;")
        else:
            self.offset_label.setStyleSheet("color: black; font-weight: 600;")

    def process_file(self):
        try:
            self.parse_logs = []
            self._parse_logger("MAIN", f"开始处理文件: {self.file_path}")

            ald = ADOLevelData.new(self.file_path)
            ald.set_logger(self._parse_logger)
            ald.decode()

            self.adofai_angle = ADOAngle(ald)
            self.adofai_angle.set_logger(self._parse_logger)

            self.cumulative_times = self.adofai_angle.getMacroCumulativeTimes()
            self.macro_key_info = self.adofai_angle.getMacroKeyInfo()
            self.hold_dict = self.adofai_angle.getHoldDict()

            self.generate_timeline()

            self.log_message(f"文件解析完成: {len(self.timeline)//2} 个按键事件", "system")
            if self.hold_dict:
                self.log_message(f"检测到长按事件: {len(self.hold_dict)} 个", "status")
            self._set_status(f"已加载: {os.path.basename(self.file_path)}", "green")

            self._update_log_count()
            self._parse_logger("MAIN", f"处理完成，共生成 {len(self.parse_logs)} 条日志")

        except Exception as e:
            self.log_message(f"解析错误: {str(e)}", "error")
            self._set_status("解析失败", "red")
            import traceback
            traceback.print_exc()
            self.parse_logs.append(f"[ERROR] {str(e)}")
            self.parse_logs.append(traceback.format_exc())
            self._update_log_count()

        speed = float(self.speed_edit.text() or 1.0)
        self.playback.preload_timeline(self.timeline, speed)

    def _on_speed_changed(self):
        if not self.file_path or self.playback.is_playing:
            return
        if self.macro_key_info:
            self.generate_timeline()
        speed = self._bpm_value(self.speed_edit, 1.0)
        self.playback.preload_timeline(self.timeline, speed)

    def generate_timeline(self):
        key_assignments = None
        key_hold_ms = None
        cyclic_keys = self.custom_keys
        speed = self._bpm_value(self.speed_edit, 1.0)

        if self.technique_check.isChecked():
            press_times = [k['press_time'] for k in self.macro_key_info]
            left_keys = self._reverse_key_groups(self.left_keys, 4)
            right_keys = list(self.right_keys)
            main_hand = "right" if self.main_hand_combo.currentText() == "右手" else "left"

            single_kps = self._bpm_value(self.single_kps_edit, 6.5)

            follow_speed = self.technique_follow_speed_check.isChecked() and speed != 1.0
            if follow_speed:
                press_times = [t / speed for t in press_times]

            simulator = AdvancedTechnique(
                left_keys, right_keys,
                single_finger_bpm=single_kps * 60.0,
                main_hand=main_hand,
            )
            key_assignments, key_hold_ms = simulator.simulate(press_times)
            if follow_speed:
                key_hold_ms = [h * speed for h in key_hold_ms]
            cyclic_keys = left_keys + right_keys

        self.timeline = build_timeline(
            self.macro_key_info,
            cyclic_keys,
            self.press_duration_edit.text() or 40,
            key_assignments,
            key_hold_ms,
            speed,
        )

    @staticmethod
    def _bpm_value(edit, default):
        try:
            value = float(edit.text())
            return value if value > 0 else default
        except ValueError:
            return default

    @staticmethod
    def _reverse_key_groups(keys, group_size=4):
        result = []
        for i in range(0, len(keys), group_size):
            group = keys[i:i + group_size]
            result.extend(reversed(group))
        return result


    def _collect_config(self):
        return {
            "left_keys": list(self.left_keys),
            "right_keys": list(self.right_keys),
            "keys": list(self.left_keys) + list(self.right_keys),
            "hotkey": self.macro_hotkey,
            "press_duration": int(self.press_duration_edit.text() or 40),
            "technique": {
                "enabled": self.technique_check.isChecked(),
                "style": self.technique_style_combo.currentText(),
                "single_kps": self._bpm_value(self.single_kps_edit, 6.5),
                "main_hand": "right" if self.main_hand_combo.currentText() == "右手" else "left",
                "follow_speed": self.technique_follow_speed_check.isChecked(),
            },
            "verbose": self.verbose_check.isChecked(),
        }

    def export_config_file(self):
        file_path, _ = QFileDialog.getSaveFileName(
            self,
            "导出配置文件",
            "adofai_macro_config.json",
            "JSON 配置文件 (*.json);;所有文件 (*.*)",
        )
        if not file_path:
            return
        if config_module.export_config(file_path, self._collect_config()):
            self.log_message(f"配置已导出: {file_path}", "system")
            self._set_status(f"配置已导出: {os.path.basename(file_path)}", "green")
        else:
            QMessageBox.critical(self, "导出失败", f"无法写入文件:\n{file_path}")

    def import_config_file(self):
        file_path, _ = QFileDialog.getOpenFileName(
            self,
            "导入配置文件",
            "",
            "JSON 配置文件 (*.json);;所有文件 (*.*)",
        )
        if not file_path:
            return
        data = config_module.import_config(file_path)
        if data is None:
            QMessageBox.critical(self, "导入失败", f"无法读取配置文件:\n{file_path}")
            return

        self.stop_play()
        self._apply_config(data)
        self.log_message(f"配置已导入: {file_path}", "system")
        self._set_status(f"配置已导入: {os.path.basename(file_path)}", "green")

    def _apply_config(self, data):
        left = data.get("left_keys")
        right = data.get("right_keys")
        if not isinstance(left, list) or not left:
            left = self.left_keys
        if not isinstance(right, list) or not right:
            right = self.right_keys
        self.left_keys = [str(k) for k in left]
        self.right_keys = [str(k) for k in right]
        self._sync_custom_keys()
        self.refresh_key_list()
        self.update_buttons_state()

        hotkey = data.get("hotkey")
        if isinstance(hotkey, str) and hotkey:
            conflict = hotkey.lower() in [k.lower() for k in self.left_keys + self.right_keys]
            if conflict:
                self.log_message(
                    f"导入配置: 触发键 '{hotkey}' 与输出键冲突,保留当前触发键 '{self.macro_hotkey}'",
                    "warning",
                )
            else:
                self.macro_hotkey = hotkey
                self.lbl_hotkey.setText(hotkey)
                self._register_trigger_key()
        else:
            self.log_message("导入配置: 未找到有效的 hotkey,保留当前触发键", "warning")

        try:
            press_duration = max(1, int(data.get("press_duration", 40)))
        except (TypeError, ValueError):
            press_duration = 40
        self.press_duration_edit.setText(str(press_duration))

        tech = data.get("technique")
        if isinstance(tech, dict):
            self.technique_check.setChecked(bool(tech.get("enabled", self.technique_enabled)))
            style = tech.get("style")
            if isinstance(style, str) and style in ("内轮(new)", "内轮(old)"):
                style = "内轮"
            if isinstance(style, str) and style in STYLE_NAMES:
                self.technique_style_combo.setCurrentText(style)
            elif isinstance(style, int) and 0 <= style < len(STYLE_NAMES_LEGACY):
                self.technique_style_combo.setCurrentText(STYLE_NAMES_LEGACY[style])
            try:
                kps = float(tech.get("single_kps", self.technique_single_kps))
                if kps > 0:
                    self.single_kps_edit.setText(str(kps))
            except (TypeError, ValueError):
                pass
            hand = tech.get("main_hand", self.technique_main_hand)
            self.main_hand_combo.setCurrentText("右手" if hand in ("right", "右手") else "左手")
            self.technique_follow_speed_check.setChecked(bool(tech.get("follow_speed", True)))

        if isinstance(data.get("verbose"), bool):
            self.verbose_check.setChecked(data["verbose"])

        self.config.update(self._collect_config())

        if self.file_path:
            self.generate_timeline()
            speed = float(self.speed_edit.text() or 1.0)
            self.playback.preload_timeline(self.timeline, speed)
            self.log_message("时间线已按新配置重新生成", "system")


    def toggle_play(self):
        if self.disable_trigger:
            return
        if not self.playback.is_playing:
            self.start_play()
        else:
            self.stop_play()

    def start_play(self):
        if not self.file_path:
            QMessageBox.warning(self, "警告", "请先选择谱面文件")
            return

        self.playback.reset_offset()
        self._update_offset_display(0)
        self._set_status("运行中...", "blue")

        self._register_direction_keys()

        self.playback.start(
            self.verbose_check.isChecked(),
            on_stopped=self.events.playback_finished.emit,
        )

    def stop_play(self, force=False):
        self.playback.stop()
        self._clear_direction_hooks()
        self._set_status("已停止", "gray")

    def _on_playback_finished(self):
        self._set_status("就绪", "gray")
        self._clear_direction_hooks()


    def log_message(self, message, msg_type="system"):
        try:
            color = COLOR_MAP.get(msg_type, "")
            print(f"{color}{message}{Style.RESET_ALL}", flush=True)
        except Exception as e:
            print(f"[RAW] {message}", flush=True)

    def closeEvent(self, event):
        self.stop_play(force=True)
        self._clear_direction_hooks()
        if self._trigger_hook is not None:
            try:
                keyboard.unhook(self._trigger_hook)
            except Exception:
                pass
        config_module.save_config(
            self.config,
            left_keys=self.left_keys,
            right_keys=self.right_keys,
            macro_hotkey=self.macro_hotkey,
            press_duration=self.press_duration_edit.text(),
            technique={
                "enabled": self.technique_check.isChecked(),
                "style": self.technique_style_combo.currentText(),
                "single_kps": self._bpm_value(self.single_kps_edit, 6.5),
                "main_hand": "right" if self.main_hand_combo.currentText() == "右手" else "left",
                "follow_speed": self.technique_follow_speed_check.isChecked(),
            },
            verbose=self.verbose_check.isChecked(),
        )
        event.accept()
        console.cleanup()
        os._exit(0)
