import os

from PySide6.QtCore import QEvent, QObject, QRegularExpression, Qt, QTimer, Signal
from PySide6.QtGui import QAction, QColor, QFont, QRegularExpressionValidator, QTextCharFormat, QTextCursor
from PySide6.QtWidgets import (
    QApplication, QCheckBox, QComboBox, QDialog, QFileDialog, QGroupBox,
    QHBoxLayout, QLabel, QLineEdit, QListWidget, QMainWindow, QMessageBox,
    QPushButton, QTextEdit, QVBoxLayout, QWidget,
)

import keyboard
from colorama import Fore, Style

from parser import ADOAngle, ADOLevelData

from .. import config as config_module
from .. import console
from ..constants import COLOR_MAP, DEFAULT_KEYS
from ..hotkey import DirectionHook, bound_control_keys
from ..multipress import annotate_multi_press, track_angle_limit
from ..playback_process import RemotePlaybackEngine as PlaybackEngine
from ..technique import STYLE_NAMES, STYLE_NAMES_LEGACY, AdvancedTechnique
from ..timeline import build_timeline
from .bind_window import BindWindow
from .falling_notes_window import FallingNotesWindow
from .focus_filter import FocusClearFilter
from .key_config_window import KeyConfigWindow
from .other_settings_window import OtherSettingsWindow
from .rhythm_hint_window import RhythmHintWindow

APP_QSS = """
QMainWindow { background: #f0f2f5; }
QMenuBar { background: #ffffff; color: #263238; border-bottom: 1px solid #d8dce3; }
QMenuBar::item { padding: 5px 12px; background: transparent; color: #263238; }
QMenuBar::item:selected { background: #e3edf7; color: #0b57d0; border-radius: 4px; }
QMenu { background: #ffffff; color: #263238; border: 1px solid #d8dce3; padding: 4px; }
QMenu::item { padding: 5px 24px 5px 12px; border-radius: 4px; color: #263238; }
QMenu::item:selected { background: #e3edf7; color: #0b57d0; }
QLabel, QCheckBox { color: #263238; }
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


RHYTHM_HINT_DIVISIONS = (4, 8, 16, 32)
DEFAULT_RHYTHM_HINT_SPEED = 100
DEFAULT_RHYTHM_HINT_DIVISION = 4


FALLING_NOTES_LANES = (4, 8)
DEFAULT_FALLING_NOTES_LANES = 4


def _falling_notes_lanes_text(lanes):
    try:
        value = int(lanes)
    except (TypeError, ValueError):
        value = DEFAULT_FALLING_NOTES_LANES
    return "8(16)K" if value == 8 else f"{value}K"


WINDOW_SIZE_LIMIT = 4000


class _UIEvents(QObject):

    toggle = Signal()
    offset = Signal(float)
    offset_display = Signal(float)
    playback_finished = Signal()
    debounce_schedule = Signal()


def _append_colored(text_edit, line, color=None):
    fmt = QTextCharFormat()
    if color:
        fmt.setForeground(QColor(color))
    cursor = text_edit.textCursor()
    cursor.movePosition(QTextCursor.End)
    cursor.insertText(line + "\n", fmt)


class ADOFAIPlayer(QMainWindow):
    def __init__(self, enable_parse_log=False):
        super().__init__()
        self._parse_log_enabled = enable_parse_log
        self.setWindowTitle("ADOFAI Macro v5.1")
        self.setAcceptDrops(True)

        self._focus_manager = FocusClearFilter(self)
        self.installEventFilter(self._focus_manager)

        self.events = _UIEvents(self)
        self.events.toggle.connect(self.toggle_play)
        self.events.offset.connect(self._apply_offset)
        self.events.offset_display.connect(self._update_offset_display)
        self.events.playback_finished.connect(self._on_playback_finished)
        self._debounce_timer = QTimer(self)
        self._debounce_timer.setSingleShot(True)
        self._debounce_timer.timeout.connect(self._reset_debounce)
        self.events.debounce_schedule.connect(self._start_debounce_timer)

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
        self.offset_left_key = str(self.config.get("offset_left_key", "left") or "left")
        self.offset_right_key = str(self.config.get("offset_right_key", "right") or "right")
        self.realtime_offset_enabled = bool(self.config.get("realtime_offset_enabled", True))
        _mode = self.config.get("macro_end_mode", "both")
        self.macro_end_mode = _mode if _mode in ("trigger", "esc", "both") else "both"
        self.disable_key_output = bool(self.config.get("disable_key_output", False))
        self.suppress_bound_keys = bool(
            self.config.get(
                "suppress_bound_keys",
                self.config.get("suppress_control_keys", True),
            )
        )
        self.key_config_window = None
        self.other_settings_window = None
        self.rhythm_hint_window = None
        self.rhythm_hint_enabled = bool(self.config.get("rhythm_hint_enabled", False))
        self.rhythm_hint_speed = self._migrate_rhythm_hint_speed(
            self.config.get("rhythm_hint_speed", DEFAULT_RHYTHM_HINT_SPEED)
        )
        self.rhythm_hint_division = self._coerce_rhythm_hint_division(
            self.config.get("rhythm_hint_division", DEFAULT_RHYTHM_HINT_DIVISION)
        )
        self.rhythm_hint_hit_effect = bool(
            self.config.get("rhythm_hint_hit_effect", True)
        )
        self.rhythm_hint_multi_fix = bool(
            self.config.get(
                "rhythm_hint_multi_fix",
                self.config.get("rhythm_hint_multi_press", True),
            )
        )
        self.falling_notes_window = None
        self.falling_notes_enabled = bool(self.config.get("falling_notes_enabled", False))
        self.falling_notes_speed = self._migrate_rhythm_hint_speed(
            self.config.get("falling_notes_speed", DEFAULT_RHYTHM_HINT_SPEED)
        )
        self.falling_notes_division = self._coerce_rhythm_hint_division(
            self.config.get("falling_notes_division", DEFAULT_RHYTHM_HINT_DIVISION)
        )
        self.falling_notes_lanes = self._coerce_falling_notes_lanes(
            self.config.get("falling_notes_lanes", DEFAULT_FALLING_NOTES_LANES)
        )
        self.falling_notes_multi_fix = bool(
            self.config.get("falling_notes_multi_fix", True)
        )
        self.falling_notes_hit_effect = bool(
            self.config.get("falling_notes_hit_effect", False)
        )
        self.rhythm_hint_width = self._coerce_window_size(
            self.config.get("rhythm_hint_width"),
            RhythmHintWindow.DEFAULT_WIDTH,
            RhythmHintWindow.MIN_WIDTH,
        )
        self.falling_notes_width = self._coerce_window_size(
            self.config.get("falling_notes_width"),
            FallingNotesWindow.DEFAULT_WIDTH,
            FallingNotesWindow.MIN_WIDTH,
        )
        self.falling_notes_height = self._coerce_window_size(
            self.config.get("falling_notes_height"),
            FallingNotesWindow.DEFAULT_HEIGHT,
            FallingNotesWindow.MIN_HEIGHT,
        )
        self.window_on_top = False
        self.disable_trigger = False

        self._trigger_hook = None
        self._trigger_release_hook = None
        self._trigger_down = False
        self._trigger_latch_enabled = False
        self._escape_hook = None
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
        self.playback.key_output_enabled = not self.disable_key_output
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
        self._fit_window_to_content()
        if self.rhythm_hint_enabled:
            self.open_rhythm_hint()
        if self.falling_notes_enabled:
            self.open_falling_notes()


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
        self._apply_window_flag(win, self.window_on_top)

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
            elif line.startswith("[BPM_LIST]"):
                color = "#7b1fa2"
            else:
                color = None
            _append_colored(text, line, color)

        win.exec()


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

        act_other_settings = QAction("其他设置", self)
        act_other_settings.setToolTip("打开其他设置窗口")
        act_other_settings.triggered.connect(self.open_other_settings)
        menubar.addAction(act_other_settings)

        self.act_window_on_top = QAction("窗口置顶：关", self)
        self.act_window_on_top.setCheckable(True)
        self.act_window_on_top.setToolTip("切换程序所有窗口的窗口置顶状态")
        self.act_window_on_top.toggled.connect(self._on_window_on_top_toggled)
        menubar.addAction(self.act_window_on_top)

    def _all_app_windows(self):
        windows = [self]
        if getattr(self, "key_config_window", None) is not None:
            windows.append(self.key_config_window)
        if getattr(self, "other_settings_window", None) is not None:
            windows.append(self.other_settings_window)
        if getattr(self, "rhythm_hint_window", None) is not None:
            windows.append(self.rhythm_hint_window)
        if getattr(self, "falling_notes_window", None) is not None:
            windows.append(self.falling_notes_window)
        return windows

    def _apply_window_flag(self, window, enabled):
        if window is None:
            return
        try:
            was_visible = window.isVisible()
            flags = window.windowFlags()
            if enabled:
                new_flags = flags | Qt.WindowStaysOnTopHint
            else:
                new_flags = Qt.WindowType(
                    int(flags) & ~int(Qt.WindowStaysOnTopHint)
                )
            if new_flags != flags:
                window.setWindowFlags(new_flags)
            if was_visible:
                window.show()
                window.raise_()
        except Exception as e:
            self.log_message(f"设置窗口置顶失败: {e}", "error")

    def _apply_window_on_top_to_all(self):
        console.set_always_on_top(self.window_on_top)
        for window in self._all_app_windows():
            self._apply_window_flag(window, self.window_on_top)

    def _update_window_on_top_action(self):
        if not hasattr(self, "act_window_on_top"):
            return
        self.act_window_on_top.blockSignals(True)
        self.act_window_on_top.setChecked(self.window_on_top)
        self.act_window_on_top.setText("窗口置顶：开" if self.window_on_top else "窗口置顶：关")
        self.act_window_on_top.blockSignals(False)

    def _on_window_on_top_toggled(self, checked):
        self.window_on_top = bool(checked)
        self._apply_window_on_top_to_all()
        self._update_window_on_top_action()

    def create_widgets(self):
        central = QWidget()
        self.setCentralWidget(central)
        main_layout = QVBoxLayout(central)
        main_layout.setContentsMargins(12, 8, 12, 8)
        main_layout.setSpacing(8)

        self._create_menu_bar()

        file_box = QGroupBox()
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
        btn_key_config = QPushButton("按键配置")
        btn_key_config.setToolTip("打开按键配置窗口")
        btn_key_config.clicked.connect(self.open_key_config)
        file_layout.addWidget(btn_key_config)
        main_layout.addWidget(file_box)

        self.output_keys_box = self._build_output_keys_box()
        self.trigger_box = self._build_trigger_box()
        self.delay_box = self._build_delay_box()
        self.key_output_box = self._build_key_output_box()
        self.macro_end_box = self._build_macro_end_box()
        self.rhythm_hint_box = self._build_rhythm_hint_box()
        self.falling_notes_box = self._build_falling_notes_box()

        control_box = QGroupBox("播放控制")
        control_layout = QVBoxLayout(control_box)
        control_layout.setSpacing(6)

        row1 = QHBoxLayout()
        row1.setSpacing(8)
        row1.addWidget(QLabel("倍速:"))
        self.speed_edit = QLineEdit("1.0")
        self.speed_edit.setValidator(self._make_validator(r"\d*\.?\d*"))
        self.speed_edit.setFixedWidth(50)
        self.speed_edit.setToolTip("播放倍速")
        self.speed_edit.editingFinished.connect(self._on_speed_changed)
        row1.addWidget(self.speed_edit)
        row1.addWidget(QLabel("x"))
        row1.addStretch(1)
        control_layout.addLayout(row1)

        row2 = QHBoxLayout()
        row2.setSpacing(8)
        row2.addWidget(QLabel("按键时长:"))
        self.press_duration_edit = QLineEdit(str(self.config.get("press_duration", 40)))
        self.press_duration_edit.setValidator(self._make_validator(r"\d*"))
        self.press_duration_edit.setFixedWidth(50)
        self.press_duration_edit.setToolTip("普通按键的按下持续时间(ms)")
        self.press_duration_edit.editingFinished.connect(self._on_speed_changed)
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
        self.technique_check.toggled.connect(self._on_speed_changed)
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
        self.single_kps_edit.editingFinished.connect(self._on_speed_changed)
        technique_layout.addWidget(self.single_kps_edit)
        technique_layout.addWidget(QLabel("主手:"))
        self.main_hand_combo = QComboBox()
        self.main_hand_combo.addItems(["右手", "左手"])
        self.main_hand_combo.setCurrentText(
            "右手" if self.technique_main_hand == "right" else "左手"
        )
        self.main_hand_combo.setFixedWidth(70)
        self.main_hand_combo.currentIndexChanged.connect(self._on_speed_changed)
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
        self._update_window_on_top_action()

    def _fit_window_to_content(self):
        self.adjustSize()
        hint = self.sizeHint()
        self.setFixedSize(hint.width() + 12, hint.height() + 8)

    def _build_output_keys_box(self):
        box = QGroupBox("输出按键设置")
        layout = QHBoxLayout(box)
        layout.setSpacing(16)
        self._create_key_list(box, "左手按键", "left", "left_listbox",
                              "left_del_btn", "left_up_btn", "left_down_btn")
        self._create_key_list(box, "右手按键", "right", "right_listbox",
                              "right_del_btn", "right_up_btn", "right_down_btn")
        return box

    def _build_trigger_box(self):
        box = QGroupBox("触发键设置")
        layout = QHBoxLayout(box)
        layout.addWidget(QLabel("触发键:"))
        self.lbl_hotkey = QLabel(self.macro_hotkey)
        self.lbl_hotkey.setStyleSheet("color: #0b57d0; font-weight: 600;")
        layout.addWidget(self.lbl_hotkey)
        btn_bind_trigger = QPushButton("绑定")
        btn_bind_trigger.setToolTip("重新绑定全局触发键")
        btn_bind_trigger.clicked.connect(lambda: self.bind_key("trigger"))
        layout.addWidget(btn_bind_trigger)
        layout.addStretch(1)
        return box

    def _build_delay_box(self):
        box = QGroupBox("延迟调整")
        layout = QVBoxLayout(box)
        layout.setSpacing(6)

        row = QHBoxLayout()
        row.setSpacing(8)
        row.addWidget(QLabel("提前:"))
        self.lbl_offset_left = QLabel(self.offset_left_key)
        self.lbl_offset_left.setStyleSheet("color: #0b57d0; font-weight: 600;")
        self.lbl_offset_left.setMinimumWidth(70)
        row.addWidget(self.lbl_offset_left)
        btn_left = QPushButton("绑定")
        btn_left.clicked.connect(lambda: self.bind_key("offset_left"))
        row.addWidget(btn_left)

        row.addSpacing(24)
        row.addWidget(QLabel("延后:"))
        self.lbl_offset_right = QLabel(self.offset_right_key)
        self.lbl_offset_right.setStyleSheet("color: #0b57d0; font-weight: 600;")
        self.lbl_offset_right.setMinimumWidth(70)
        row.addWidget(self.lbl_offset_right)
        btn_right = QPushButton("绑定")
        btn_right.clicked.connect(lambda: self.bind_key("offset_right"))
        row.addWidget(btn_right)
        row.addStretch(1)
        layout.addLayout(row)

        self.realtime_offset_check = QCheckBox("实时延迟调节")
        self.realtime_offset_check.setChecked(self.realtime_offset_enabled)
        self.realtime_offset_check.setToolTip("开启后可在播放时用「提前/延后」键实时调整延迟")
        self.realtime_offset_check.toggled.connect(self._on_realtime_offset_toggled)
        layout.addWidget(self.realtime_offset_check)
        return box

    @staticmethod
    def _macro_end_mode_from_text(text):
        return {
            "仅触发键": "trigger",
            "仅 ESC": "esc",
            "均生效": "both",
        }.get(text, "both")

    @staticmethod
    def _macro_end_mode_to_text(mode):
        return {
            "trigger": "仅触发键",
            "esc": "仅 ESC",
            "both": "均生效",
        }.get(mode, "均生效")

    def _bound_control_keys(self):
        return bound_control_keys(
            self.macro_hotkey,
            self.offset_left_key,
            self.offset_right_key,
            self.macro_end_mode,
            self.left_keys + self.right_keys,
        )

    def _should_suppress(self, key):
        if not self.suppress_bound_keys:
            return False
        name = str(key or "").strip().lower()
        return name in self._bound_control_keys()

    def _refresh_suppress_targets(self):
        self._apply_key_output_options()

    def _build_key_output_box(self):
        box = QGroupBox("按键输出")
        layout = QHBoxLayout(box)
        layout.setSpacing(8)

        self.disable_key_output_check = QCheckBox("禁用 Macro 按键输出")
        self.disable_key_output_check.setChecked(self.disable_key_output)
        self.disable_key_output_check.setToolTip(
            "勾选后 Macro 不再向游戏输出按键，只保留节奏提示 / 下落式窗口的播放\n"
            "(可以用来只看谱面、或手动跟着提示打)"
        )
        self.disable_key_output_check.toggled.connect(
            self._on_disable_key_output_toggled
        )
        layout.addWidget(self.disable_key_output_check)

        layout.addSpacing(10)
        self.suppress_bound_keys_check = QCheckBox("屏蔽已绑定按键输入")
        self.suppress_bound_keys_check.setChecked(self.suppress_bound_keys)
        self.suppress_bound_keys_check.setToolTip(
            "勾选(默认)：除了输出按键以外，程序里已绑定的按键都不会传给游戏\n"
            "（触发键、偏移调节键、结束键 ESC），避免误触发游戏自身的按键功能\n"
            "取消勾选：这些绑定键同时也会被游戏收到"
        )
        self.suppress_bound_keys_check.toggled.connect(
            self._on_suppress_bound_keys_toggled
        )
        layout.addWidget(self.suppress_bound_keys_check)

        layout.addStretch(1)
        return box

    def _on_disable_key_output_toggled(self, checked):
        self.disable_key_output = bool(checked)
        self.config["disable_key_output"] = self.disable_key_output
        self._apply_key_output_options()

    def _on_suppress_bound_keys_toggled(self, checked):
        self.suppress_bound_keys = bool(checked)
        self.config["suppress_bound_keys"] = self.suppress_bound_keys
        self._apply_key_output_options()

    def _apply_key_output_options(self):
        self.playback.key_output_enabled = not self.disable_key_output
        self._register_trigger_key()
        self._refresh_escape_hook()
        if self._direction_hook is not None:
            left, right = self.offset_left_key, self.offset_right_key
            self._direction_hook.set_suppress(
                self._should_suppress(left) or self._should_suppress(right)
            )

    def _build_macro_end_box(self):
        box = QGroupBox("Macro 结束方式")
        layout = QHBoxLayout(box)
        layout.addWidget(QLabel("结束方式:"))
        self.macro_end_combo = QComboBox()
        self.macro_end_combo.addItems(["仅触发键", "仅 ESC", "均生效"])
        self.macro_end_combo.setCurrentText(self._macro_end_mode_to_text(self.macro_end_mode))
        self.macro_end_combo.setFixedWidth(120)
        self.macro_end_combo.setToolTip("指定结束 Macro 的条件，修改后立即生效")
        self.macro_end_combo.currentTextChanged.connect(self._on_macro_end_mode_changed)
        layout.addWidget(self.macro_end_combo)
        layout.addStretch(1)
        return box

    def _on_macro_end_mode_changed(self, text):
        self.macro_end_mode = self._macro_end_mode_from_text(text)
        self.config["macro_end_mode"] = self.macro_end_mode
        self._refresh_escape_hook()

    def open_key_config(self):
        if self.key_config_window is None:
            self.key_config_window = KeyConfigWindow(self)
            self._apply_window_flag(self.key_config_window, self.window_on_top)
        self.key_config_window.show()
        self.key_config_window.raise_()
        self.key_config_window.activateWindow()

    def open_other_settings(self):
        if self.other_settings_window is None:
            self.other_settings_window = OtherSettingsWindow(self)
            self._apply_window_flag(self.other_settings_window, self.window_on_top)
        self.other_settings_window.show()
        self.other_settings_window.raise_()
        self.other_settings_window.activateWindow()

    def _build_rhythm_hint_box(self):
        box = QGroupBox("节奏提示")
        layout = QHBoxLayout(box)
        layout.setSpacing(8)
        self.rhythm_hint_check = QCheckBox("启用节奏提示窗口")
        self.rhythm_hint_check.setChecked(self.rhythm_hint_enabled)
        self.rhythm_hint_check.setToolTip(
            "开启后自动打开独立的节奏提示窗口\n"
            "(太鼓达人风格谱面：红圈=普通按键，黄圈=长按按键)"
        )
        self.rhythm_hint_check.toggled.connect(self._on_rhythm_hint_toggled)
        layout.addWidget(self.rhythm_hint_check)

        layout.addSpacing(10)
        layout.addWidget(QLabel("流速:"))
        self.rhythm_hint_speed_edit = QLineEdit(str(int(self.rhythm_hint_speed)))
        self.rhythm_hint_speed_edit.setValidator(self._make_validator(r"\d*"))
        self.rhythm_hint_speed_edit.setFixedWidth(56)
        self.rhythm_hint_speed_edit.setToolTip(
            "音符向左移动的速度(整数)：100 = 1x，200 = 2x，50 = 0.5x"
        )
        self.rhythm_hint_speed_edit.editingFinished.connect(
            self._on_rhythm_hint_options_changed
        )
        layout.addWidget(self.rhythm_hint_speed_edit)

        layout.addSpacing(10)
        layout.addWidget(QLabel("切分:"))
        self.rhythm_hint_division_combo = QComboBox()
        for division in RHYTHM_HINT_DIVISIONS:
            self.rhythm_hint_division_combo.addItem(f"{division}分")
        division_text = f"{self.rhythm_hint_division}分"
        division_idx = self.rhythm_hint_division_combo.findText(division_text)
        if division_idx < 0:
            division_idx = 0
        self.rhythm_hint_division_combo.setCurrentIndex(division_idx)
        self.rhythm_hint_division_combo.setFixedWidth(70)
        self.rhythm_hint_division_combo.setToolTip("切分线密度：按 4/8/16/32 分切割")
        self.rhythm_hint_division_combo.currentTextChanged.connect(
            self._on_rhythm_hint_options_changed
        )
        layout.addWidget(self.rhythm_hint_division_combo)

        self.rhythm_hint_hit_effect_check = QCheckBox("判定特效")
        self.rhythm_hint_hit_effect_check.setChecked(self.rhythm_hint_hit_effect)
        self.rhythm_hint_hit_effect_check.setToolTip(
            "是否显示判定特效(音符到达判定点时放大的白色圆环)"
        )
        self.rhythm_hint_hit_effect_check.toggled.connect(
            self._on_rhythm_hint_options_changed
        )
        layout.addWidget(self.rhythm_hint_hit_effect_check)

        self.rhythm_hint_multi_fix_check = QCheckBox("多押提示")
        self.rhythm_hint_multi_fix_check.setChecked(self.rhythm_hint_multi_fix)
        self.rhythm_hint_multi_fix_check.setToolTip(
            "多押只显示组内第一个按键，并在圈内用数字标出这一押要同时按几个键\n"
            "(多押判据：相邻音符按下间隔 <50ms，且后一格轨道夹角 <=30°(轨道 BPM>=300) / <=15°(轨道 BPM<300))"
        )
        self.rhythm_hint_multi_fix_check.toggled.connect(
            self._on_rhythm_hint_options_changed
        )
        layout.addWidget(self.rhythm_hint_multi_fix_check)

        self.rhythm_hint_default_size_btn = QPushButton("默认大小")
        self.rhythm_hint_default_size_btn.setToolTip(
            "把节奏提示窗口恢复到默认大小(900×150)"
        )
        self.rhythm_hint_default_size_btn.clicked.connect(self.reset_rhythm_hint_size)
        layout.addWidget(self.rhythm_hint_default_size_btn)

        self.rhythm_hint_render_btn = QPushButton("重新渲染")
        self.rhythm_hint_render_btn.setToolTip(
            "重新渲染节奏提示窗口(不需要按触发键，窗口回到谱面起点)"
        )
        self.rhythm_hint_render_btn.clicked.connect(self.re_render_rhythm_hint)
        layout.addWidget(self.rhythm_hint_render_btn)

        layout.addStretch(1)
        return box

    def _build_falling_notes_box(self):
        box = QGroupBox("下落式")
        layout = QHBoxLayout(box)
        layout.setSpacing(8)
        self.falling_notes_check = QCheckBox("启用下落式窗口")
        self.falling_notes_check.setChecked(self.falling_notes_enabled)
        self.falling_notes_check.setToolTip(
            "开启后自动打开独立的下落式窗口\n"
            "(按键从上往下坠落，落到判定线时消失；左侧红色，右侧蓝色)"
        )
        self.falling_notes_check.toggled.connect(self._on_falling_notes_toggled)
        layout.addWidget(self.falling_notes_check)

        layout.addSpacing(10)
        layout.addWidget(QLabel("流速:"))
        self.falling_notes_speed_edit = QLineEdit(str(int(self.falling_notes_speed)))
        self.falling_notes_speed_edit.setValidator(self._make_validator(r"\d*"))
        self.falling_notes_speed_edit.setFixedWidth(56)
        self.falling_notes_speed_edit.setToolTip(
            "音符下落的快慢(整数)：100 = 1x，200 = 2x，50 = 0.5x"
        )
        self.falling_notes_speed_edit.editingFinished.connect(
            self._on_falling_notes_options_changed
        )
        layout.addWidget(self.falling_notes_speed_edit)

        layout.addSpacing(10)
        layout.addWidget(QLabel("切分:"))
        self.falling_notes_division_combo = QComboBox()
        for division in RHYTHM_HINT_DIVISIONS:
            self.falling_notes_division_combo.addItem(f"{division}分")
        division_text = f"{self.falling_notes_division}分"
        division_idx = self.falling_notes_division_combo.findText(division_text)
        if division_idx < 0:
            division_idx = 0
        self.falling_notes_division_combo.setCurrentIndex(division_idx)
        self.falling_notes_division_combo.setFixedWidth(70)
        self.falling_notes_division_combo.setToolTip("切分线密度：按 4/8/16/32 分切割")
        self.falling_notes_division_combo.currentTextChanged.connect(
            self._on_falling_notes_options_changed
        )
        layout.addWidget(self.falling_notes_division_combo)

        layout.addSpacing(10)
        layout.addWidget(QLabel("轨道数:"))
        self.falling_notes_lanes_combo = QComboBox()
        for lanes in FALLING_NOTES_LANES:
            self.falling_notes_lanes_combo.addItem(_falling_notes_lanes_text(lanes))
        lanes_text = _falling_notes_lanes_text(self.falling_notes_lanes)
        lanes_idx = self.falling_notes_lanes_combo.findText(lanes_text)
        if lanes_idx < 0:
            lanes_idx = 0
        self.falling_notes_lanes_combo.setCurrentIndex(lanes_idx)
        self.falling_notes_lanes_combo.setFixedWidth(88)
        self.falling_notes_lanes_combo.setToolTip(
            "轨道数量：4K(每手 2 轨) 或 8(16)K(每手 4 轨，支持到16键)，左右各占一半"
        )
        self.falling_notes_lanes_combo.currentTextChanged.connect(
            self._on_falling_notes_options_changed
        )
        layout.addWidget(self.falling_notes_lanes_combo)

        self.falling_notes_hit_effect_check = QCheckBox("判定特效")
        self.falling_notes_hit_effect_check.setChecked(
            self.falling_notes_hit_effect
        )
        self.falling_notes_hit_effect_check.setToolTip(
            "是否显示判定特效(音符到达判定线时白色长方形由内向外扩散)"
        )
        self.falling_notes_hit_effect_check.toggled.connect(
            self._on_falling_notes_options_changed
        )
        layout.addWidget(self.falling_notes_hit_effect_check)

        self.falling_notes_multi_fix_check = QCheckBox("多押提示")
        self.falling_notes_multi_fix_check.setChecked(self.falling_notes_multi_fix)
        self.falling_notes_multi_fix_check.setToolTip(
            "被识别为多押的一组按键，在下落式中按下时间对齐到组内第一个按键\n"
            "(多押判据：相邻音符按下间隔 <50ms，且后一格轨道夹角 "
            "<=30°(轨道 BPM>=300) / <=15°(轨道 BPM<300))"
        )
        self.falling_notes_multi_fix_check.toggled.connect(
            self._on_falling_notes_options_changed
        )
        layout.addWidget(self.falling_notes_multi_fix_check)

        self.falling_notes_default_size_btn = QPushButton("默认大小")
        self.falling_notes_default_size_btn.setToolTip(
            "把下落式窗口恢复到默认大小(380×820)"
        )
        self.falling_notes_default_size_btn.clicked.connect(self.reset_falling_notes_size)
        layout.addWidget(self.falling_notes_default_size_btn)

        self.falling_notes_render_btn = QPushButton("重新渲染")
        self.falling_notes_render_btn.setToolTip(
            "重新渲染下落式窗口(不需要按触发键，窗口回到谱面起点)"
        )
        self.falling_notes_render_btn.clicked.connect(self.re_render_falling_notes)
        layout.addWidget(self.falling_notes_render_btn)

        layout.addStretch(1)
        return box

    def _on_rhythm_hint_toggled(self, checked):
        self.set_rhythm_hint_enabled(bool(checked))

    def set_rhythm_hint_enabled(self, enabled):
        enabled = bool(enabled)
        self.rhythm_hint_enabled = enabled
        self.config["rhythm_hint_enabled"] = enabled
        if hasattr(self, "rhythm_hint_check"):
            self.rhythm_hint_check.blockSignals(True)
            self.rhythm_hint_check.setChecked(enabled)
            self.rhythm_hint_check.blockSignals(False)
        if enabled:
            self.open_rhythm_hint()
        elif self.rhythm_hint_window is not None:
            self.rhythm_hint_window.hide()
        self._save_config_file("节奏提示开关")

    def _on_rhythm_hint_closed(self):
        self.rhythm_hint_enabled = False
        self.config["rhythm_hint_enabled"] = False
        if hasattr(self, "rhythm_hint_check"):
            self.rhythm_hint_check.blockSignals(True)
            self.rhythm_hint_check.setChecked(False)
            self.rhythm_hint_check.blockSignals(False)
        self._save_config_file("关闭节奏提示窗口")

    @staticmethod
    def _coerce_rhythm_hint_speed(value):
        try:
            speed = int(round(float(value)))
        except (TypeError, ValueError):
            return DEFAULT_RHYTHM_HINT_SPEED
        if speed <= 0:
            return DEFAULT_RHYTHM_HINT_SPEED
        return min(speed, 10000)

    @staticmethod
    def _migrate_rhythm_hint_speed(value):

        if isinstance(value, bool):
            return DEFAULT_RHYTHM_HINT_SPEED
        if isinstance(value, float):
            if value.is_integer() and value >= 10:
                return min(int(value), 10000)
            return DEFAULT_RHYTHM_HINT_SPEED
        try:
            speed = int(value)
        except (TypeError, ValueError):
            return DEFAULT_RHYTHM_HINT_SPEED
        if speed <= 0:
            return DEFAULT_RHYTHM_HINT_SPEED
        return min(speed, 10000)

    @staticmethod
    def _coerce_rhythm_hint_division(value):
        try:
            division = int(value)
        except (TypeError, ValueError):
            return DEFAULT_RHYTHM_HINT_DIVISION
        if division in RHYTHM_HINT_DIVISIONS:
            return division
        return DEFAULT_RHYTHM_HINT_DIVISION

    def _on_rhythm_hint_options_changed(self, *args):
        if hasattr(self, "rhythm_hint_speed_edit"):
            text = self.rhythm_hint_speed_edit.text().strip()
            speed = self._coerce_rhythm_hint_speed(text)
            self.rhythm_hint_speed = speed
            if text != str(speed):
                self.rhythm_hint_speed_edit.blockSignals(True)
                self.rhythm_hint_speed_edit.setText(str(speed))
                self.rhythm_hint_speed_edit.blockSignals(False)
        if hasattr(self, "rhythm_hint_division_combo"):
            text = self.rhythm_hint_division_combo.currentText().removesuffix("分")
            self.rhythm_hint_division = self._coerce_rhythm_hint_division(text)
        if hasattr(self, "rhythm_hint_hit_effect_check"):
            self.rhythm_hint_hit_effect = bool(
                self.rhythm_hint_hit_effect_check.isChecked()
            )
        if hasattr(self, "rhythm_hint_multi_fix_check"):
            self.rhythm_hint_multi_fix = bool(
                self.rhythm_hint_multi_fix_check.isChecked()
            )
        self.config["rhythm_hint_speed"] = self.rhythm_hint_speed
        self.config["rhythm_hint_division"] = self.rhythm_hint_division
        self.config["rhythm_hint_hit_effect"] = self.rhythm_hint_hit_effect
        self.config["rhythm_hint_multi_fix"] = self.rhythm_hint_multi_fix
        self._apply_rhythm_hint_options()

    def _apply_rhythm_hint_options(self):
        if self.rhythm_hint_window is not None:
            self.rhythm_hint_window.set_options(
                self.rhythm_hint_speed / 100.0,
                self.rhythm_hint_division,
                self.rhythm_hint_hit_effect,
                self.rhythm_hint_multi_fix,
            )

    def _sync_rhythm_hint_options(self):
        if hasattr(self, "rhythm_hint_speed_edit"):
            self.rhythm_hint_speed_edit.blockSignals(True)
            self.rhythm_hint_speed_edit.setText(str(int(self.rhythm_hint_speed)))
            self.rhythm_hint_speed_edit.blockSignals(False)
        if hasattr(self, "rhythm_hint_division_combo"):
            text = f"{self.rhythm_hint_division}分"
            self.rhythm_hint_division_combo.blockSignals(True)
            self.rhythm_hint_division_combo.setCurrentText(text)
            self.rhythm_hint_division_combo.blockSignals(False)
        if hasattr(self, "rhythm_hint_hit_effect_check"):
            self.rhythm_hint_hit_effect_check.blockSignals(True)
            self.rhythm_hint_hit_effect_check.setChecked(
                bool(self.rhythm_hint_hit_effect)
            )
            self.rhythm_hint_hit_effect_check.blockSignals(False)
        if hasattr(self, "rhythm_hint_multi_fix_check"):
            self.rhythm_hint_multi_fix_check.blockSignals(True)
            self.rhythm_hint_multi_fix_check.setChecked(
                bool(self.rhythm_hint_multi_fix)
            )
            self.rhythm_hint_multi_fix_check.blockSignals(False)
        self._apply_rhythm_hint_options()

    def reset_rhythm_hint_size(self):
        if self.rhythm_hint_window is not None:
            self.rhythm_hint_window.reset_size()
            self._remember_hint_window_sizes()
            self._save_config_file("节奏提示分辨率")

    def re_render_rhythm_hint(self):
        if self.rhythm_hint_window is None:
            return
        self._refresh_rhythm_hint()
        self._apply_rhythm_hint_options()
        self.rhythm_hint_window.show()
        self.rhythm_hint_window.raise_()

    def open_rhythm_hint(self):
        if self.rhythm_hint_window is None:
            self.rhythm_hint_window = RhythmHintWindow(self, self.rhythm_hint_width)
            self._apply_window_flag(self.rhythm_hint_window, self.window_on_top)
        self._refresh_rhythm_hint()
        self._apply_rhythm_hint_options()
        self.rhythm_hint_window.show()
        self.rhythm_hint_window.raise_()

    def _refresh_rhythm_hint(self):
        if self.rhythm_hint_window is None:
            return
        notes = []
        angles = None
        if self.adofai_angle is not None and self.macro_key_info:
            notes = self.macro_key_info
            angles = self._rhythm_hint_multi_angles(notes)
        self.rhythm_hint_window.set_chart(
            self._chart_bpm(), notes, self._chart_bpm_timeline(), angles
        )

    def _rhythm_hint_multi_angles(self, notes):



        angle = self.adofai_angle
        turns = getattr(angle, "originRotateAngleList", None)
        if not turns:
            turns = self._travel_from_angle_data(
                getattr(angle, "angleData", None)
            )
        if not turns:
            return None

        first_real = self._first_real_floor(getattr(angle, "angleData", None))

        result = []
        found = False
        for note in notes:
            index = None
            if isinstance(note, dict):
                index = note.get("floor")
                if index is None:
                    index = note.get("raw_idx")
            value = None
            try:
                floor = int(index)
                if floor != first_real and 0 <= floor < len(turns):
                    value = float(turns[floor])
                    if value == 999.0:
                        value = None
            except (TypeError, ValueError, IndexError, KeyError):
                value = None
            if value is not None:
                found = True
            result.append(value)
        return result if found else None

    @staticmethod
    def _first_real_floor(angle_data):
        if not angle_data:
            return None
        for index, value in enumerate(angle_data):
            try:
                if float(value) != 999.0:
                    return index
            except (TypeError, ValueError):
                continue
        return None

    @staticmethod
    def _travel_from_angle_data(angle_data):

        if not angle_data:
            return None
        result = [None] * len(angle_data)
        for index in range(1, len(angle_data)):
            try:
                current = float(angle_data[index])
            except (TypeError, ValueError):
                continue
            if current == 999.0:
                continue

            prev_index = index - 1
            offset = 1
            previous = None
            while prev_index >= 0:
                try:
                    previous = float(angle_data[prev_index])
                except (TypeError, ValueError):
                    previous = None
                if previous is not None and previous != 999.0:
                    break
                prev_index -= 1
                offset += 1
            if previous is None or prev_index < 0:
                continue
            result[index] = (previous + offset * 180.0 - current) % 360.0
        return result

    def _chart_bpm_timeline(self):
        if self.adofai_angle is None:
            return []
        try:
            return self.adofai_angle.getBpmTimeline()
        except Exception as e:
            self.log_message(f"读取谱面 BPM 变化失败,按固定 BPM 显示: {e}", "error")
            return []

    def _chart_bpm(self):
        if self.adofai_angle is None:
            return 0.0
        try:
            return float(self.adofai_angle.settings.get("bpm", 0.0))
        except (TypeError, ValueError, AttributeError):
            return 0.0

    @staticmethod
    def _bpm_at_points(bpm_points, chart_time):
        if not bpm_points:
            return 0.0
        bpm = bpm_points[0][1]
        for time_ms, value in bpm_points:
            if time_ms > chart_time:
                break
            bpm = value
        return bpm

    def _multi_limits_for_notes(self, notes):
        bpm_points = self._chart_bpm_timeline()
        limits = []
        for note in notes:
            try:
                press = float(note.get("press_time", 0.0))
            except (TypeError, ValueError, AttributeError):
                press = 0.0
            limits.append(
                track_angle_limit(self._bpm_at_points(bpm_points, press))
            )
        return limits

    @staticmethod
    def _copy_multi_fields(target, source):
        target["multi_count"] = int(source.get("multi_count", 1) or 1)
        target["multi_slot"] = int(source.get("multi_slot", 0) or 0)
        target["multi_lead"] = bool(source.get("multi_lead"))
        target["multi_angle"] = source.get("multi_angle")

    def _on_falling_notes_toggled(self, checked):
        self.set_falling_notes_enabled(bool(checked))

    def set_falling_notes_enabled(self, enabled):
        enabled = bool(enabled)
        self.falling_notes_enabled = enabled
        self.config["falling_notes_enabled"] = enabled
        if hasattr(self, "falling_notes_check"):
            self.falling_notes_check.blockSignals(True)
            self.falling_notes_check.setChecked(enabled)
            self.falling_notes_check.blockSignals(False)
        if enabled:
            self.open_falling_notes()
        elif self.falling_notes_window is not None:
            self.falling_notes_window.hide()
        self._save_config_file("下落式开关")

    def _on_falling_notes_closed(self):
        self.falling_notes_enabled = False
        self.config["falling_notes_enabled"] = False
        if hasattr(self, "falling_notes_check"):
            self.falling_notes_check.blockSignals(True)
            self.falling_notes_check.setChecked(False)
            self.falling_notes_check.blockSignals(False)
        self._save_config_file("关闭下落式窗口")

    @staticmethod
    def _coerce_falling_notes_lanes(value):
        try:
            lanes = int(value)
        except (TypeError, ValueError):
            return DEFAULT_FALLING_NOTES_LANES
        if lanes in FALLING_NOTES_LANES:
            return lanes
        return DEFAULT_FALLING_NOTES_LANES

    @staticmethod
    def _coerce_window_size(value, default, minimum, maximum=WINDOW_SIZE_LIMIT):
        if value is None:
            return int(default)
        try:
            size = int(round(float(value)))
        except (TypeError, ValueError):
            return int(default)
        return max(int(minimum), min(size, int(maximum)))

    def _remember_hint_window_sizes(self):
        window = self.rhythm_hint_window
        if window is not None:
            self.rhythm_hint_width = self._coerce_window_size(
                window.width(),
                RhythmHintWindow.DEFAULT_WIDTH,
                RhythmHintWindow.MIN_WIDTH,
            )
        window = self.falling_notes_window
        if window is not None:
            self.falling_notes_width = self._coerce_window_size(
                window.width(),
                FallingNotesWindow.DEFAULT_WIDTH,
                FallingNotesWindow.MIN_WIDTH,
            )
            self.falling_notes_height = self._coerce_window_size(
                window.height(),
                FallingNotesWindow.DEFAULT_HEIGHT,
                FallingNotesWindow.MIN_HEIGHT,
            )

    def _on_falling_notes_options_changed(self, *args):
        lanes_before = self.falling_notes_lanes
        if hasattr(self, "falling_notes_speed_edit"):
            text = self.falling_notes_speed_edit.text().strip()
            speed = self._coerce_rhythm_hint_speed(text)
            self.falling_notes_speed = speed
            if text != str(speed):
                self.falling_notes_speed_edit.blockSignals(True)
                self.falling_notes_speed_edit.setText(str(speed))
                self.falling_notes_speed_edit.blockSignals(False)
        if hasattr(self, "falling_notes_division_combo"):
            text = self.falling_notes_division_combo.currentText().removesuffix("分")
            self.falling_notes_division = self._coerce_rhythm_hint_division(text)
        if hasattr(self, "falling_notes_lanes_combo"):
            text = self.falling_notes_lanes_combo.currentText()
            text = text.split("(")[0].removesuffix("K")
            self.falling_notes_lanes = self._coerce_falling_notes_lanes(text)
        if hasattr(self, "falling_notes_hit_effect_check"):
            self.falling_notes_hit_effect = bool(
                self.falling_notes_hit_effect_check.isChecked()
            )
        if hasattr(self, "falling_notes_multi_fix_check"):
            self.falling_notes_multi_fix = bool(
                self.falling_notes_multi_fix_check.isChecked()
            )
        self.config["falling_notes_speed"] = self.falling_notes_speed
        self.config["falling_notes_division"] = self.falling_notes_division
        self.config["falling_notes_lanes"] = self.falling_notes_lanes
        self.config["falling_notes_hit_effect"] = self.falling_notes_hit_effect
        self.config["falling_notes_multi_fix"] = self.falling_notes_multi_fix
        self._apply_falling_notes_options()
        if self.falling_notes_lanes != lanes_before:
            self._refresh_falling_notes()

    def _apply_falling_notes_options(self):
        if self.falling_notes_window is not None:
            self.falling_notes_window.set_options(
                self.falling_notes_speed / 100.0,
                self.falling_notes_division,
                lanes=self.falling_notes_lanes,
                multi_press=self.falling_notes_multi_fix,
                hit_effect=self.falling_notes_hit_effect,
            )

    def _sync_falling_notes_options(self):
        if hasattr(self, "falling_notes_speed_edit"):
            self.falling_notes_speed_edit.blockSignals(True)
            self.falling_notes_speed_edit.setText(str(int(self.falling_notes_speed)))
            self.falling_notes_speed_edit.blockSignals(False)
        if hasattr(self, "falling_notes_division_combo"):
            self.falling_notes_division_combo.blockSignals(True)
            self.falling_notes_division_combo.setCurrentText(
                f"{self.falling_notes_division}分"
            )
            self.falling_notes_division_combo.blockSignals(False)
        if hasattr(self, "falling_notes_lanes_combo"):
            self.falling_notes_lanes_combo.blockSignals(True)
            self.falling_notes_lanes_combo.setCurrentText(
                _falling_notes_lanes_text(self.falling_notes_lanes)
            )
            self.falling_notes_lanes_combo.blockSignals(False)
        if hasattr(self, "falling_notes_hit_effect_check"):
            self.falling_notes_hit_effect_check.blockSignals(True)
            self.falling_notes_hit_effect_check.setChecked(
                bool(self.falling_notes_hit_effect)
            )
            self.falling_notes_hit_effect_check.blockSignals(False)
        if hasattr(self, "falling_notes_multi_fix_check"):
            self.falling_notes_multi_fix_check.blockSignals(True)
            self.falling_notes_multi_fix_check.setChecked(
                bool(self.falling_notes_multi_fix)
            )
            self.falling_notes_multi_fix_check.blockSignals(False)
        self._apply_falling_notes_options()

    def reset_falling_notes_size(self):
        if self.falling_notes_window is not None:
            self.falling_notes_window.reset_size()
            self._remember_hint_window_sizes()
            self._save_config_file("下落式分辨率")

    def re_render_falling_notes(self):
        if self.falling_notes_window is None:
            return
        self._refresh_falling_notes()
        self._apply_falling_notes_options()
        self.falling_notes_window.show()
        self.falling_notes_window.raise_()

    def open_falling_notes(self):
        if self.falling_notes_window is None:
            self.falling_notes_window = FallingNotesWindow(
                self, (self.falling_notes_width, self.falling_notes_height)
            )
            self._apply_window_flag(self.falling_notes_window, self.window_on_top)
        self._refresh_falling_notes()
        self._apply_falling_notes_options()
        self.falling_notes_window.show()
        self.falling_notes_window.raise_()

    def _refresh_falling_notes(self):
        if self.falling_notes_window is None:
            return
        notes = []
        angles = None
        annotate_multi = True
        if self.adofai_angle is not None and self.timeline:
            notes = self._selected_falling_notes()
            if notes:
                source_notes = self.macro_key_info
                if source_notes and len(source_notes) == len(notes):
                    source = [dict(note) for note in source_notes]
                    source_angles = self._rhythm_hint_multi_angles(source_notes)
                    annotate_multi_press(
                        source,
                        source_angles,
                        limit=self._multi_limits_for_notes(source),
                    )
                    for note, source_note in zip(notes, source):
                        self._copy_multi_fields(note, source_note)
                    annotate_multi = False
                else:
                    angles = self._rhythm_hint_multi_angles(notes)
        self.falling_notes_window.set_chart(
            self._chart_bpm(),
            notes,
            self.falling_notes_lanes,
            self._chart_bpm_timeline(),
            angles,
            annotate_multi=annotate_multi,
        )

    def _selected_falling_notes(self):

        if not self.timeline:
            return []
        per_hand = max(1, self.falling_notes_lanes // 2)
        infos = self.macro_key_info
        notes = []
        pending = {}
        info_index = 0
        for event_time, key, action in self.timeline:
            if action == "D":
                info = infos[info_index] if info_index < len(infos) else {}
                info_index += 1
                note = {
                    "press_time": float(event_time),
                    "release_time": None,
                    "is_hold": bool(info.get("is_hold")),
                    "lane": self._falling_lane_of(key, per_hand),
                    "key_row": self._falling_key_row_of(key, per_hand),
                    "floor": info.get("floor"),
                    "raw_idx": info.get("raw_idx"),
                }
                notes.append(note)
                pending.setdefault(key, []).append(note)
                continue
            queue = pending.get(key)
            if not queue:
                continue
            queue.pop(0)["release_time"] = float(event_time)
        return notes

    def _falling_lane_of(self, key, per_hand):

        per_hand = max(1, int(per_hand))
        if key in self.left_keys:
            return per_hand - 1 - (self.left_keys.index(key) % per_hand)
        if key in self.right_keys:
            return per_hand + (self.right_keys.index(key) % per_hand)
        return 0

    def _falling_key_row_of(self, key, per_hand):

        per_hand = max(1, int(per_hand))
        if key in self.left_keys:
            index = self.left_keys.index(key)
        elif key in self.right_keys:
            index = self.right_keys.index(key)
        else:
            return 0
        return (index // per_hand) % 2

    def _refresh_hint_windows(self):
        self._refresh_rhythm_hint()
        self._refresh_falling_notes()

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

    def _ui_parent(self):
        if self.key_config_window is not None and self.key_config_window.isVisible():
            return self.key_config_window
        return self

    @staticmethod
    def _offset_key_attr(key_type):
        return "offset_left_key" if key_type == "offset_left" else "offset_right_key"

    @staticmethod
    def _offset_label_attr(key_type):
        return "lbl_offset_left" if key_type == "offset_left" else "lbl_offset_right"

    def _refresh_direction_keys(self):
        if self._direction_hook is not None:
            self._direction_hook.configure(self.offset_left_key, self.offset_right_key)

    def bind_key(self, key_type):
        self.disable_trigger = True
        try:
            title = {
                "trigger": "绑定触发键",
                "left": "绑定左手按键",
                "right": "绑定右手按键",
                "offset_left": "绑定提前键",
                "offset_right": "绑定延后键",
            }[key_type]
        except KeyError:
            self.disable_trigger = False
            return

        parent = self._ui_parent()
        win = BindWindow(parent, title)
        self._apply_window_flag(win, self.window_on_top)
        try:
            accepted = win.exec() == QDialog.Accepted
        finally:
            self.disable_trigger = False

        if not (accepted and win.key):
            return

        key = win.key
        output_keys = self.left_keys + self.right_keys
        if key_type == "trigger":
            if key in output_keys:
                QMessageBox.warning(parent, "冲突", "触发键不能与输出键重复！")
                return
            if key in (self.offset_left_key, self.offset_right_key):
                QMessageBox.warning(parent, "冲突", "触发键不能与延迟调整键重复！")
                return
            self.macro_hotkey = key
            self.config["hotkey"] = self.macro_hotkey
            self.lbl_hotkey.setText(key)
            self._register_trigger_key()
            return

        if key_type in ("offset_left", "offset_right"):
            other_key = self.offset_right_key if key_type == "offset_left" else self.offset_left_key
            if key == self.macro_hotkey:
                QMessageBox.warning(parent, "冲突", "延迟调整键不能与触发键相同！")
                return
            if key in output_keys:
                QMessageBox.warning(parent, "冲突", "延迟调整键不能与输出键重复！")
                return
            if key == other_key:
                QMessageBox.warning(parent, "冲突", "提前键和延后键不能相同！")
                return
            attr = self._offset_key_attr(key_type)
            setattr(self, attr, key)
            self.config[attr] = key
            getattr(self, self._offset_label_attr(key_type)).setText(key)
            self._refresh_direction_keys()
            return

        if key == self.macro_hotkey:
            QMessageBox.warning(parent, "冲突", "输出键不能与触发键相同！")
            return
        if key in output_keys:
            QMessageBox.warning(parent, "冲突", "该按键已存在于按键列表中！")
            return
        if key in (self.offset_left_key, self.offset_right_key):
            QMessageBox.warning(parent, "冲突", "输出键不能与延迟调整键重复！")
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
        parent = self._ui_parent()
        win = BindWindow(parent, "修改按键")
        self._apply_window_flag(win, self.window_on_top)
        try:
            accepted = win.exec() == QDialog.Accepted
        finally:
            self.disable_trigger = False
        if not (accepted and win.key):
            return
        key = win.key
        if key == current:
            return
        if key == self.macro_hotkey:
            QMessageBox.warning(parent, "冲突", "输出键不能与触发键相同！")
            return
        if key in self.left_keys + self.right_keys:
            QMessageBox.warning(parent, "冲突", "该按键已存在于按键列表中！")
            return
        if key in (self.offset_left_key, self.offset_right_key):
            QMessageBox.warning(parent, "冲突", "输出键不能与延迟调整键重复！")
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
        for attr in ("_trigger_hook", "_trigger_release_hook"):
            hook = getattr(self, attr, None)
            if hook is not None:
                try:
                    keyboard.unhook(hook)
                except Exception:
                    pass
                setattr(self, attr, None)

        self._trigger_down = False
        self._trigger_latch_enabled = False
        try:
            if hasattr(keyboard, "hook_key"):
                self._trigger_hook = keyboard.hook_key(
                    self.macro_hotkey.lower(),
                    self._on_hotkey_event,
                    suppress=self._should_suppress(self.macro_hotkey)
                )
                self._trigger_latch_enabled = True
            else:
                self._trigger_hook = keyboard.on_press_key(
                    self.macro_hotkey.lower(),
                    self._on_hotkey_trigger,
                    suppress=self._should_suppress(self.macro_hotkey)
                )
        except Exception as e:
            self.log_message(f"注册触发键失败: {e}", "error")

    def _register_escape_hook(self):
        if self._escape_hook is not None:
            try:
                keyboard.unhook(self._escape_hook)
            except Exception:
                pass
            self._escape_hook = None
        try:
            self._escape_hook = keyboard.on_press_key(
                "esc",
                self._on_hotkey_escape,
                suppress=self._should_suppress("esc")
            )
        except Exception as e:
            self.log_message(f"注册 ESC 结束键失败: {e}", "error")

    def _unregister_escape_hook(self):
        if self._escape_hook is not None:
            try:
                keyboard.unhook(self._escape_hook)
            except Exception:
                pass
            self._escape_hook = None

    def _refresh_escape_hook(self):
        if not hasattr(self, "playback"):
            return
        should_register = (
            self.playback.is_playing
            and self.macro_end_mode in ("esc", "both")
        )
        if should_register:
            self._register_escape_hook()
        else:
            self._unregister_escape_hook()

    def _register_direction_keys(self):
        if self._direction_hook is None:
            self._direction_hook = DirectionHook(self.offset_left_key, self.offset_right_key)
        else:
            self._direction_hook.configure(self.offset_left_key, self.offset_right_key)
        self._direction_hook.on_left = self._on_hotkey_left
        self._direction_hook.on_right = self._on_hotkey_right
        self._direction_hook.set_suppress(
            self._should_suppress(self.offset_left_key)
            or self._should_suppress(self.offset_right_key)
        )
        if not self._direction_hook.install():
            self.log_message("注册延迟调整键钩子失败", "error")

    def _on_realtime_offset_toggled(self, checked):
        self.realtime_offset_enabled = bool(checked)
        self.config["realtime_offset_enabled"] = self.realtime_offset_enabled
        if not hasattr(self, "playback"):
            return
        if self.playback.is_playing:
            self._register_direction_keys()

    def _clear_direction_hooks(self):
        if self._direction_hook is not None:
            self._direction_hook.uninstall()

    def _start_debounce_timer(self):
        self._debounce_timer.start(200)

    def _schedule_toggle(self):
        self._toggle_debounce = True
        self.events.debounce_schedule.emit()
        self.events.toggle.emit()

    def _on_hotkey_event(self, event=None):
        event_type = getattr(event, "event_type", event)
        if event_type == "up":
            self._on_hotkey_release(event)
            return True
        self._on_hotkey_trigger(event)
        return not self._should_suppress(self.macro_hotkey)

    def _on_hotkey_trigger(self, event=None):
        if getattr(self, "_trigger_latch_enabled", False):
            if getattr(self, "_trigger_down", False):
                return
            self._trigger_down = True
        if self.disable_trigger or self._toggle_debounce:
            return
        if self.playback.is_playing and self.macro_end_mode == "esc":
            return
        self._schedule_toggle()

    def _on_hotkey_release(self, event=None):
        self._trigger_down = False
        self._toggle_debounce = False

    def _on_hotkey_escape(self, event=None):
        if self.disable_trigger or self._toggle_debounce:
            return
        if not self.playback.is_playing:
            return
        self._schedule_toggle()

    def _reset_debounce(self):
        self._toggle_debounce = False

    def _on_hotkey_left(self, event=None):
        if not self.playback.is_playing or not self.realtime_offset_enabled:
            return
        self.events.offset.emit(-1.0)

    def _on_hotkey_right(self, event=None):
        if not self.playback.is_playing or not self.realtime_offset_enabled:
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
        self.cumulative_times = []
        self.macro_key_info = []
        self.hold_dict = {}
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
        self._refresh_hint_windows()

    def _on_speed_changed(self):
        if not self.file_path or self.playback.is_playing:
            return
        if self.macro_key_info:
            self.generate_timeline()
        speed = self._bpm_value(self.speed_edit, 1.0)
        self.playback.preload_timeline(self.timeline, speed)
        self._refresh_falling_notes()

    def _selected_key_limits(self, infos):
        if not infos or self.adofai_angle is None:
            return None
        events = self.adofai_angle.getKeyLimiterList()
        if not events:
            return None

        limits = []
        event_idx = 0
        current = None
        for info in infos:
            floor = info.get('floor', 0)
            while event_idx < len(events) and events[event_idx][0] <= floor:
                current = events[event_idx][1]
                event_idx += 1
            limits.append(current)
        return limits

    def _main_hand(self):
        if hasattr(self, "main_hand_combo"):
            return "right" if self.main_hand_combo.currentText() == "右手" else "left"
        return getattr(self, "technique_main_hand", "right")

    def _keys_for_limit(self, limit):
        left = list(self.left_keys)
        right = list(self.right_keys)
        if not left and not right:
            return []
        main_hand = self._main_hand()
        main_list = right if main_hand == "right" else left
        sub_list = left if main_hand == "right" else right

        main_count = min(len(main_list), (limit + 1) // 2)
        sub_count = min(len(sub_list), limit // 2)

        left_slice = left[:sub_count] if main_hand == "right" else left[:main_count]
        right_slice = right[:main_count] if main_hand == "right" else right[:sub_count]

        allowed = []
        for i in range(max(len(left_slice), len(right_slice))):
            if i < len(left_slice):
                allowed.append(left_slice[i])
            if i < len(right_slice):
                allowed.append(right_slice[i])
        return allowed

    def _selected_allowed_keys(self, infos, limits):
        if not limits:
            return None
        result = []
        for limit in limits:
            if limit is None:
                result.append(None)
            else:
                result.append(self._keys_for_limit(int(limit)))
        return result

    def generate_timeline(self):
        selected_macro_key_info = self.macro_key_info
        key_limits = self._selected_key_limits(selected_macro_key_info)
        key_allowed = self._selected_allowed_keys(selected_macro_key_info, key_limits)
        key_assignments = None
        key_hold_ms = None
        key_groups = None
        key_list = self.custom_keys
        speed = self._bpm_value(self.speed_edit, 1.0)

        if selected_macro_key_info and self.technique_check.isChecked():
            press_times = [k['press_time'] for k in selected_macro_key_info]
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
                default_hold_ms=self.press_duration_edit.text() or 40,
            )
            hold_mask = [bool(k.get('is_hold')) for k in selected_macro_key_info]
            key_assignments, key_hold_ms, key_groups = simulator.simulate_with_groups(
                press_times, hold_mask=hold_mask
            )
            if follow_speed:
                key_hold_ms = [h * speed for h in key_hold_ms]

        self.timeline = build_timeline(
            selected_macro_key_info,
            key_list,
            self.press_duration_edit.text() or 40,
            key_assignments,
            key_hold_ms,
            speed,
            key_allowed,
            left_keys=self.left_keys,
            right_keys=self.right_keys,
            key_groups=key_groups,
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
        self._remember_hint_window_sizes()
        return {
            "left_keys": list(self.left_keys),
            "right_keys": list(self.right_keys),
            "keys": list(self.left_keys) + list(self.right_keys),
            "hotkey": self.macro_hotkey,
            "offset_left_key": self.offset_left_key,
            "offset_right_key": self.offset_right_key,
            "realtime_offset_enabled": bool(self.realtime_offset_enabled),
            "disable_key_output": bool(self.disable_key_output),
            "suppress_bound_keys": bool(self.suppress_bound_keys),
            "macro_end_mode": self.macro_end_mode,
            "press_duration": int(self.press_duration_edit.text() or 40),
            "technique": {
                "enabled": self.technique_check.isChecked(),
                "style": self.technique_style_combo.currentText(),
                "single_kps": self._bpm_value(self.single_kps_edit, 6.5),
                "main_hand": "right" if self.main_hand_combo.currentText() == "右手" else "left",
                "follow_speed": self.technique_follow_speed_check.isChecked(),
            },
            "verbose": self.verbose_check.isChecked(),
            "rhythm_hint_enabled": bool(self.rhythm_hint_enabled),
            "rhythm_hint_speed": int(self.rhythm_hint_speed),
            "rhythm_hint_division": int(self.rhythm_hint_division),
            "rhythm_hint_hit_effect": bool(self.rhythm_hint_hit_effect),
            "rhythm_hint_multi_fix": bool(self.rhythm_hint_multi_fix),
            "falling_notes_enabled": bool(self.falling_notes_enabled),
            "falling_notes_speed": int(self.falling_notes_speed),
            "falling_notes_division": int(self.falling_notes_division),
            "falling_notes_lanes": int(self.falling_notes_lanes),
            "falling_notes_hit_effect": bool(self.falling_notes_hit_effect),
            "falling_notes_multi_fix": bool(self.falling_notes_multi_fix),
            "rhythm_hint_width": int(self.rhythm_hint_width),
            "falling_notes_width": int(self.falling_notes_width),
            "falling_notes_height": int(self.falling_notes_height),
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

        output_lower = [k.lower() for k in self.left_keys + self.right_keys]

        offset_left = data.get("offset_left_key")
        if isinstance(offset_left, str) and offset_left:
            if (offset_left.lower() != self.macro_hotkey.lower()
                    and offset_left.lower() not in output_lower
                    and offset_left != self.offset_right_key):
                self.offset_left_key = offset_left
            else:
                self.log_message(
                    f"导入配置: 提前键 '{offset_left}' 存在冲突,保留当前值 '{self.offset_left_key}'",
                    "warning",
                )

        offset_right = data.get("offset_right_key")
        if isinstance(offset_right, str) and offset_right:
            if (offset_right.lower() != self.macro_hotkey.lower()
                    and offset_right.lower() not in output_lower
                    and offset_right != self.offset_left_key):
                self.offset_right_key = offset_right
            else:
                self.log_message(
                    f"导入配置: 延后键 '{offset_right}' 存在冲突,保留当前值 '{self.offset_right_key}'",
                    "warning",
                )

        hotkey = data.get("hotkey")
        if isinstance(hotkey, str) and hotkey:
            conflict = (hotkey.lower() in output_lower
                        or hotkey in (self.offset_left_key, self.offset_right_key))
            if conflict:
                self.log_message(
                    f"导入配置: 触发键 '{hotkey}' 与其它按键冲突,保留当前触发键 '{self.macro_hotkey}'",
                    "warning",
                )
            else:
                self.macro_hotkey = hotkey
                self.lbl_hotkey.setText(hotkey)
                self._register_trigger_key()
        else:
            self.log_message("导入配置: 未找到有效的 hotkey,保留当前触发键", "warning")

        self.lbl_offset_left.setText(self.offset_left_key)
        self.lbl_offset_right.setText(self.offset_right_key)
        if isinstance(data.get("realtime_offset_enabled"), bool):
            self.realtime_offset_enabled = data["realtime_offset_enabled"]
        self.realtime_offset_check.setChecked(self.realtime_offset_enabled)
        if isinstance(data.get("disable_key_output"), bool):
            self.disable_key_output = data["disable_key_output"]
        if isinstance(data.get("suppress_bound_keys"), bool):
            self.suppress_bound_keys = data["suppress_bound_keys"]
        elif isinstance(data.get("suppress_control_keys"), bool):
            self.suppress_bound_keys = data["suppress_control_keys"]
        if hasattr(self, "disable_key_output_check"):
            self.disable_key_output_check.blockSignals(True)
            self.disable_key_output_check.setChecked(self.disable_key_output)
            self.disable_key_output_check.blockSignals(False)
        if hasattr(self, "suppress_bound_keys_check"):
            self.suppress_bound_keys_check.blockSignals(True)
            self.suppress_bound_keys_check.setChecked(self.suppress_bound_keys)
            self.suppress_bound_keys_check.blockSignals(False)
        self._apply_key_output_options()
        self._refresh_direction_keys()

        mode = data.get("macro_end_mode", self.macro_end_mode)
        if mode not in ("trigger", "esc", "both"):
            mode = "both"
        self.macro_end_mode = mode
        if hasattr(self, "macro_end_combo"):
            self.macro_end_combo.blockSignals(True)
            self.macro_end_combo.setCurrentText(self._macro_end_mode_to_text(mode))
            self.macro_end_combo.blockSignals(False)
        if self.playback.is_playing:
            self._refresh_escape_hook()

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

        if data.get("rhythm_hint_speed") is not None:
            self.rhythm_hint_speed = self._migrate_rhythm_hint_speed(
                data.get("rhythm_hint_speed")
            )
        if data.get("rhythm_hint_division") is not None:
            self.rhythm_hint_division = self._coerce_rhythm_hint_division(
                data.get("rhythm_hint_division")
            )
        if isinstance(data.get("rhythm_hint_hit_effect"), bool):
            self.rhythm_hint_hit_effect = data["rhythm_hint_hit_effect"]
        if isinstance(data.get("rhythm_hint_multi_fix"), bool):
            self.rhythm_hint_multi_fix = data["rhythm_hint_multi_fix"]
        elif isinstance(data.get("rhythm_hint_multi_press"), bool):
            self.rhythm_hint_multi_fix = data["rhythm_hint_multi_press"]
        self._sync_rhythm_hint_options()

        if isinstance(data.get("rhythm_hint_enabled"), bool):
            self.set_rhythm_hint_enabled(data["rhythm_hint_enabled"])

        if data.get("falling_notes_speed") is not None:
            self.falling_notes_speed = self._migrate_rhythm_hint_speed(
                data.get("falling_notes_speed")
            )
        if data.get("falling_notes_division") is not None:
            self.falling_notes_division = self._coerce_rhythm_hint_division(
                data.get("falling_notes_division")
            )
        if data.get("falling_notes_lanes") is not None:
            self.falling_notes_lanes = self._coerce_falling_notes_lanes(
                data.get("falling_notes_lanes")
            )
        if isinstance(data.get("falling_notes_hit_effect"), bool):
            self.falling_notes_hit_effect = data["falling_notes_hit_effect"]
        if isinstance(data.get("falling_notes_multi_fix"), bool):
            self.falling_notes_multi_fix = data["falling_notes_multi_fix"]
        self._sync_falling_notes_options()

        if isinstance(data.get("falling_notes_enabled"), bool):
            self.set_falling_notes_enabled(data["falling_notes_enabled"])

        if data.get("rhythm_hint_width") is not None:
            self.rhythm_hint_width = self._coerce_window_size(
                data.get("rhythm_hint_width"),
                RhythmHintWindow.DEFAULT_WIDTH,
                RhythmHintWindow.MIN_WIDTH,
            )
            if self.rhythm_hint_window is not None:
                self.rhythm_hint_window.resize(
                    self.rhythm_hint_width, RhythmHintWindow.DEFAULT_HEIGHT
                )
        size_changed = False
        if data.get("falling_notes_width") is not None:
            self.falling_notes_width = self._coerce_window_size(
                data.get("falling_notes_width"),
                FallingNotesWindow.DEFAULT_WIDTH,
                FallingNotesWindow.MIN_WIDTH,
            )
            size_changed = True
        if data.get("falling_notes_height") is not None:
            self.falling_notes_height = self._coerce_window_size(
                data.get("falling_notes_height"),
                FallingNotesWindow.DEFAULT_HEIGHT,
                FallingNotesWindow.MIN_HEIGHT,
            )
            size_changed = True
        if size_changed and self.falling_notes_window is not None:
            self.falling_notes_window.resize(
                self.falling_notes_width, self.falling_notes_height
            )

        self.config.update(self._collect_config())

        if self.file_path:
            self.generate_timeline()
            speed = float(self.speed_edit.text() or 1.0)
            self.playback.preload_timeline(self.timeline, speed)
            self._refresh_hint_windows()
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
        if self.rhythm_hint_window is not None:
            self.rhythm_hint_window.reset_position()
        if self.falling_notes_window is not None:
            self.falling_notes_window.reset_position()
        self._set_status("运行中...", "blue")

        self._register_direction_keys()

        try:
            self.playback.start(
                self.verbose_check.isChecked(),
                on_stopped=self.events.playback_finished.emit,
            )
        except Exception as e:
            self.log_message(f"启动 Macro 失败: {e}", "error")
            self._set_status("启动失败", "red")
            self._clear_direction_hooks()
            return
        self._refresh_escape_hook()

    def stop_play(self, force=False):
        self._clear_direction_hooks()
        self._unregister_escape_hook()
        self.playback.stop()
        self._set_status("已停止", "gray")

    def _on_playback_finished(self):
        self._toggle_debounce = False
        if hasattr(self, "_debounce_timer"):
            self._debounce_timer.stop()
        if self.falling_notes_window is not None:
            self.falling_notes_window.release_active_holds()
        self._set_status("就绪", "gray")
        self._clear_direction_hooks()
        self._unregister_escape_hook()


    def log_message(self, message, msg_type="system"):
        try:
            color = COLOR_MAP.get(msg_type, "")
            print(f"{color}{message}{Style.RESET_ALL}", flush=True)
        except Exception as e:
            print(f"[RAW] {message}", flush=True)

    def closeEvent(self, event):
        self.stop_play(force=True)
        try:
            self.playback.shutdown()
        except Exception:
            pass
        self._clear_direction_hooks()
        self._unregister_escape_hook()
        for hook in (self._trigger_hook, self._trigger_release_hook):
            if hook is not None:
                try:
                    keyboard.unhook(hook)
                except Exception:
                    pass
        self.config.pop("macro_start", None)
        self.config.pop("macro_end", None)
        self._save_config_file()
        event.accept()
        console.cleanup()
        os._exit(0)

    def _save_config_file(self, reason=""):

        self._remember_hint_window_sizes()
        ok = config_module.save_config(
            self.config,
            left_keys=self.left_keys,
            right_keys=self.right_keys,
            macro_hotkey=self.macro_hotkey,
            press_duration=self.press_duration_edit.text(),
            offset_left_key=self.offset_left_key,
            offset_right_key=self.offset_right_key,
            realtime_offset_enabled=self.realtime_offset_enabled,
            disable_key_output=self.disable_key_output,
            suppress_bound_keys=self.suppress_bound_keys,
            macro_end_mode=self.macro_end_mode,
            technique={
                "enabled": self.technique_check.isChecked(),
                "style": self.technique_style_combo.currentText(),
                "single_kps": self._bpm_value(self.single_kps_edit, 6.5),
                "main_hand": "right" if self.main_hand_combo.currentText() == "右手" else "left",
                "follow_speed": self.technique_follow_speed_check.isChecked(),
            },
            verbose=self.verbose_check.isChecked(),
            rhythm_hint_enabled=self.rhythm_hint_enabled,
            rhythm_hint_speed=self.rhythm_hint_speed,
            rhythm_hint_division=self.rhythm_hint_division,
            rhythm_hint_hit_effect=self.rhythm_hint_hit_effect,
            rhythm_hint_multi_fix=self.rhythm_hint_multi_fix,
            falling_notes_enabled=self.falling_notes_enabled,
            falling_notes_speed=self.falling_notes_speed,
            falling_notes_division=self.falling_notes_division,
            falling_notes_lanes=self.falling_notes_lanes,
            falling_notes_hit_effect=self.falling_notes_hit_effect,
            falling_notes_multi_fix=self.falling_notes_multi_fix,
            rhythm_hint_width=self.rhythm_hint_width,
            falling_notes_width=self.falling_notes_width,
            falling_notes_height=self.falling_notes_height,
        )
        if reason and not ok:
            self.log_message(f"配置保存失败({reason})", "error")
        return ok
