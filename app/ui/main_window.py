import os
import copy
from PySide6.QtCore import QEvent, QObject, QRegularExpression, Qt, QTimer, Signal
from PySide6.QtGui import (
    QAction, QActionGroup, QColor, QFont, QFontDatabase,
    QRegularExpressionValidator, QTextCharFormat, QTextCursor,
)
from PySide6.QtWidgets import (
    QApplication, QCheckBox, QComboBox, QDialog, QFileDialog, QGridLayout,
    QGroupBox, QHBoxLayout, QLabel, QLineEdit, QListWidget, QMainWindow,
    QMessageBox, QPushButton, QTextEdit, QVBoxLayout, QWidget, QSpinBox,
)
import keyboard
from colorama import Fore, Style
from parser import ADOAngle, ADOLevelData
from .. import config as config_module
from .. import console
from .. import i18n
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
from . import sizing

APP_QSS = """
QMainWindow { background: #f0f2f5; }
QDialog { background: #f0f2f5; }
QMenuBar { background: #ffffff; color: #263238; border-bottom: 1px solid #d8dce3; }
QMenuBar::item { padding: 5px 12px; background: transparent; color: #263238; }
QMenuBar::item:selected { background: #e3edf7; color: #0b57d0; border-radius: 4px; }
QMenu { background: #ffffff; color: #263238; border: 1px solid #d8dce3; padding: 4px; }
QMenu::item { padding: 5px 24px 5px 12px; border-radius: 4px; color: #263238; }
QMenu::item:selected { background: #e3edf7; color: #0b57d0; }
QMenu::separator { height: 1px; background: #e2e6ec; margin: 4px 8px; }
QLabel, QCheckBox { color: #263238; }
QLabel#fieldLabel { color: #44505e; }
QLabel#hintLabel { color: #7a8694; }
QGroupBox {
    background: #ffffff;
    border: 1px solid #d8dce3;
    border-radius: 8px;
    margin-top: 12px;
    padding: 14px 12px 10px 12px;
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

# --- shared layout metrics -------------------------------------------------
# Keeping the number fields and the label column at a fixed width makes every
# box line up on the same vertical grid, in both languages.
FIELD_WIDTH = 58
FIELD_WIDTH_WIDE = 76
LABEL_MIN_WIDTH = 72
VALUE_MIN_WIDTH = 76
ROW_SPACING = 8
COL_SPACING = 14

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
        self.config = config_module.load_config()
        i18n.set_language(self.config.get("language"))
        i18n.title(self, "app.title")
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
        
        self.regular_offset_ms = float(self.config.get("regular_offset_ms", 5.0))
        self.irregular_offset_ms = float(self.config.get("irregular_offset_ms", 10.0))
        
        self.font_name = self.config.get("font_name", "Microsoft YaHei")
        self.font_size = int(self.config.get("font_size", 9))
        self._apply_global_font()

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
        self.playback.language = i18n.get_language()
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

    def _apply_global_font(self):
        try:
            font = QFont(self.font_name, self.font_size)
            if self.font_name in QFontDatabase.families():
                QApplication.setFont(font)
        except Exception:
            pass

    def _on_font_changed(self):
        self.font_name = self.font_combo.currentText()
        self.font_size = self.font_size_spin.value()
        self._apply_global_font()
        self.config["font_name"] = self.font_name
        self.config["font_size"] = self.font_size

    def _update_log_count(self):
        if self._parse_log_enabled and hasattr(self, "lbl_log_count"):
            self.lbl_log_count.setText(
                i18n.tr("logbox.count", count=len(self.parse_logs))
            )

    def _parse_logger(self, tag, message):
        if not self._parse_log_enabled:
            return
        line = f"[{tag}] {message}"
        self.parse_logs.append(line)
        self.log_message(line, "system")

    def save_parse_logs(self):
        if not self.parse_logs:
            QMessageBox.information(
                self, i18n.tr("dialog.info"), i18n.tr("logbox.no_logs")
            )
            return
        file_path, _ = QFileDialog.getSaveFileName(
            self,
            i18n.tr("logbox.save_dialog"),
            f"adofai_parse_log_{os.path.basename(self.file_path) if self.file_path else 'unknown'}.txt",
            i18n.tr("filter.text"),
        )
        if file_path:
            try:
                with open(file_path, "w", encoding="utf-8") as f:
                    f.write("\n".join(self.parse_logs))
                self.log_message(
                    i18n.tr("logbox.saved", path=file_path), "system"
                )
            except Exception as e:
                self.log_message(
                    i18n.tr("logbox.save_failed", error=e), "error"
                )

    def show_parse_logs(self):
        win = QDialog(self)
        i18n.title(win, "logbox.window")
        win.resize(900, 700)
        self._apply_window_flag(win, self.window_on_top)
        layout = QVBoxLayout(win)
        text = QTextEdit()
        text.setReadOnly(True)
        text.setFont(QFont("Consolas", 9))
        layout.addWidget(text)
        btn_layout = QHBoxLayout()
        btn_save = QPushButton()
        i18n.text(btn_save, "logbox.save_to_file")
        btn_save.clicked.connect(self.save_parse_logs)
        btn_close = QPushButton()
        i18n.text(btn_close, "common.close")
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
        self.file_menu = menubar.addMenu(i18n.tr("menu.file"))
        i18n.on_retranslate(
            self.file_menu, lambda m: m.setTitle(i18n.tr("menu.file"))
        )
        act_open = QAction(self)
        i18n.text(act_open, "menu.load_chart")
        act_open.setShortcut("Ctrl+O")
        act_open.triggered.connect(self.select_file)
        self.file_menu.addAction(act_open)
        self.file_menu.addSeparator()
        act_import = QAction(self)
        i18n.text(act_import, "menu.import_config")
        act_import.triggered.connect(self.import_config_file)
        self.file_menu.addAction(act_import)
        act_export = QAction(self)
        i18n.text(act_export, "menu.export_config")
        act_export.triggered.connect(self.export_config_file)
        self.file_menu.addAction(act_export)
        self.file_menu.addSeparator()
        act_quit = QAction(self)
        i18n.text(act_quit, "menu.quit")
        act_quit.setShortcut("Ctrl+Q")
        act_quit.triggered.connect(self.close)
        self.file_menu.addAction(act_quit)

        act_other_settings = QAction(self)
        i18n.text(act_other_settings, "menu.other_settings")
        i18n.tip(act_other_settings, "menu.other_settings.tip")
        act_other_settings.triggered.connect(self.open_other_settings)
        menubar.addAction(act_other_settings)

        self.act_window_on_top = QAction(self)
        self.act_window_on_top.setCheckable(True)
        i18n.tip(self.act_window_on_top, "menu.window_on_top.tip")
        self.act_window_on_top.toggled.connect(self._on_window_on_top_toggled)
        menubar.addAction(self.act_window_on_top)

        self.language_menu = menubar.addMenu(i18n.tr("menu.language"))
        i18n.on_retranslate(
            self.language_menu, lambda m: m.setTitle(i18n.tr("menu.language"))
        )
        i18n.tip(self.language_menu.menuAction(), "menu.language.tip")
        self._language_actions = {}
        language_group = QActionGroup(self)
        language_group.setExclusive(True)
        for code in i18n.SUPPORTED_LANGUAGES:
            action = QAction(i18n.LANGUAGE_LABELS[code], self)
            action.setCheckable(True)
            action.setChecked(code == i18n.get_language())
            action.triggered.connect(
                lambda _checked=False, c=code: self.set_language(c)
            )
            language_group.addAction(action)
            self.language_menu.addAction(action)
            self._language_actions[code] = action
        self._language_group = language_group

        self._update_window_on_top_action()

    def set_language(self, code):
        """Switch the interface language and refresh every open window."""
        if not i18n.set_language(code):
            return
        i18n.retranslate_all()
        self.config["language"] = i18n.get_language()
        self.playback.language = i18n.get_language()
        action = getattr(self, "_language_actions", {}).get(i18n.get_language())
        if action is not None:
            action.setChecked(True)
        self._update_window_on_top_action()
        self._retranslate_dynamic()
        for window in self._all_app_windows()[1:]:
            refit = getattr(window, "refit_to_content", None)
            if callable(refit):
                refit()
        self._fit_window_to_content(grow_only=True)
        self._save_config_file()

    def _retranslate_dynamic(self):
        """Refresh the few texts that are not owned by a single widget."""
        self._update_log_count()
        self._update_window_on_top_action()
        self._update_offset_display(self.playback.offset_ms)
        if hasattr(self, "lbl_file") and not self.file_path:
            self.lbl_file.setText(i18n.tr("file.none"))
        state = getattr(self, "_status_state", None)
        if state:
            key, color, fmt = state
            self._set_status_key(key, color, **fmt)

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
            self.log_message(i18n.tr("log.window_on_top_failed", error=e), "error")

    def _apply_window_on_top_to_all(self):
        console.set_always_on_top(self.window_on_top)
        for window in self._all_app_windows():
            self._apply_window_flag(window, self.window_on_top)

    def _update_window_on_top_action(self):
        if not hasattr(self, "act_window_on_top"):
            return
        self.act_window_on_top.blockSignals(True)
        self.act_window_on_top.setChecked(self.window_on_top)
        self.act_window_on_top.setText(i18n.tr(
            "menu.window_on_top",
            state=i18n.tr("state.on" if self.window_on_top else "state.off"),
        ))
        self.act_window_on_top.blockSignals(False)

    def _on_window_on_top_toggled(self, checked):
        self.window_on_top = bool(checked)
        self._apply_window_on_top_to_all()
        self._update_window_on_top_action()

    # ------------------------------------------------------------ ui helpers
    @staticmethod
    def _field_label(key, minimum=LABEL_MIN_WIDTH):
        label = QLabel()
        i18n.text(label, key)
        label.setObjectName("fieldLabel")
        if minimum:
            label.setMinimumWidth(minimum)
        return label

    def _field(self, key, widget, unit_key=None, minimum=LABEL_MIN_WIDTH):
        """Pack ``label + widget [+ unit]`` into one aligned grid cell."""
        holder = QWidget()
        row = QHBoxLayout(holder)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(6)
        row.addWidget(self._field_label(key, minimum))
        row.addWidget(widget)
        if unit_key:
            unit = QLabel()
            i18n.text(unit, unit_key)
            unit.setObjectName("fieldLabel")
            row.addWidget(unit)
        return holder

    @staticmethod
    def _numbered_edit(text, pattern, width=FIELD_WIDTH, validator_owner=None):
        edit = QLineEdit(text)
        edit.setValidator(
            QRegularExpressionValidator(QRegularExpression(pattern), validator_owner)
        )
        edit.setFixedWidth(width)
        return edit

    def create_widgets(self):
        central = QWidget()
        self.setCentralWidget(central)
        main_layout = QVBoxLayout(central)
        main_layout.setContentsMargins(12, 10, 12, 10)
        main_layout.setSpacing(10)
        self._create_menu_bar()

        file_box = QGroupBox()
        file_layout = QHBoxLayout(file_box)
        file_layout.setSpacing(ROW_SPACING)
        btn_select = QPushButton()
        i18n.text(btn_select, "file.load")
        btn_select.setObjectName("primaryBtn")
        i18n.tip(btn_select, "file.load.tip")
        btn_select.clicked.connect(self.select_file)
        file_layout.addWidget(btn_select)
        self.lbl_file = QLabel()
        i18n.text(self.lbl_file, "file.none")
        self.lbl_file.setObjectName("hintLabel")
        self.lbl_file.setToolTip("")
        file_layout.addWidget(self.lbl_file, 1)
        btn_key_config = QPushButton()
        i18n.text(btn_key_config, "file.key_config")
        i18n.tip(btn_key_config, "file.key_config.tip")
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

        # --- playback control: a grid keeps every label/field pair aligned ---
        control_box = QGroupBox()
        i18n.group_title(control_box, "control.title")
        control_layout = QGridLayout(control_box)
        control_layout.setHorizontalSpacing(COL_SPACING)
        control_layout.setVerticalSpacing(ROW_SPACING)

        self.speed_edit = self._numbered_edit("1.0", r"\d*\.?\d*", FIELD_WIDTH, self)
        i18n.tip(self.speed_edit, "control.speed.tip")
        self.speed_edit.editingFinished.connect(self._on_speed_changed)
        speed_cell = QWidget()
        speed_row = QHBoxLayout(speed_cell)
        speed_row.setContentsMargins(0, 0, 0, 0)
        speed_row.setSpacing(6)
        speed_row.addWidget(self._field_label("control.speed"))
        speed_row.addWidget(self.speed_edit)
        speed_row.addWidget(QLabel("x"))
        control_layout.addWidget(speed_cell, 0, 0)

        self.press_duration_edit = self._numbered_edit(
            str(self.config.get("press_duration", 40)), r"\d*", FIELD_WIDTH, self
        )
        i18n.tip(self.press_duration_edit, "control.press_duration.tip")
        self.press_duration_edit.editingFinished.connect(self._on_speed_changed)
        control_layout.addWidget(
            self._field("control.press_duration", self.press_duration_edit, "common.ms"),
            0, 1,
        )

        self.offset_label = QLabel("+0")
        self.offset_label.setStyleSheet("color: black; font-weight: 600;")
        self.offset_label.setMinimumWidth(VALUE_MIN_WIDTH)
        offset_cell = QWidget()
        offset_row = QHBoxLayout(offset_cell)
        offset_row.setContentsMargins(0, 0, 0, 0)
        offset_row.setSpacing(6)
        offset_row.addWidget(self._field_label("control.offset"))
        offset_row.addWidget(self.offset_label)
        offset_row.addWidget(self._field_label("common.ms", 0))
        offset_hint = QLabel()
        i18n.text(offset_hint, "control.offset.hint")
        offset_hint.setObjectName("hintLabel")
        offset_row.addWidget(offset_hint)
        offset_row.addStretch(1)
        control_layout.addWidget(offset_cell, 1, 0)

        self.verbose_check = QCheckBox()
        i18n.text(self.verbose_check, "control.verbose")
        self.verbose_check.setChecked(self.verbose)
        i18n.tip(self.verbose_check, "control.verbose.tip")
        control_layout.addWidget(
            self.verbose_check, 1, 1, alignment=Qt.AlignLeft | Qt.AlignVCenter
        )

        self.regular_offset_edit = self._numbered_edit(
            str(self.regular_offset_ms), r"\d*\.?\d*", FIELD_WIDTH, self
        )
        i18n.tip(self.regular_offset_edit, "control.regular_offset.tip")
        self.regular_offset_edit.editingFinished.connect(self._on_offset_changed)
        control_layout.addWidget(
            self._field("control.regular_offset", self.regular_offset_edit, "common.ms"),
            2, 0,
        )

        self.irregular_offset_edit = self._numbered_edit(
            str(self.irregular_offset_ms), r"\d*\.?\d*", FIELD_WIDTH, self
        )
        i18n.tip(self.irregular_offset_edit, "control.irregular_offset.tip")
        self.irregular_offset_edit.editingFinished.connect(self._on_offset_changed)
        control_layout.addWidget(
            self._field(
                "control.irregular_offset", self.irregular_offset_edit, "common.ms"
            ),
            2, 1,
        )

        self.font_combo = QComboBox()
        self.font_combo.addItems(sorted(QFontDatabase.families()))
        idx = self.font_combo.findText(self.font_name)
        if idx >= 0:
            self.font_combo.setCurrentIndex(idx)
        self.font_combo.setFixedWidth(170)
        i18n.tip(self.font_combo, "control.font.tip")
        self.font_combo.currentTextChanged.connect(self._on_font_changed)
        font_cell = QWidget()
        font_row = QHBoxLayout(font_cell)
        font_row.setContentsMargins(0, 0, 0, 0)
        font_row.setSpacing(6)
        font_row.addWidget(self._field_label("control.font"))
        font_row.addWidget(self.font_combo)
        font_row.addSpacing(6)
        self.font_size_spin = QSpinBox()
        self.font_size_spin.setRange(8, 20)
        self.font_size_spin.setValue(self.font_size)
        self.font_size_spin.setFixedWidth(FIELD_WIDTH_WIDE)
        i18n.tip(self.font_size_spin, "control.font_size.tip")
        self.font_size_spin.valueChanged.connect(self._on_font_changed)
        font_row.addWidget(self._field_label("control.font_size", 0))
        font_row.addWidget(self.font_size_spin)
        font_row.addStretch(1)
        control_layout.addWidget(font_cell, 3, 0, 1, 2)
        control_layout.setColumnStretch(1, 1)

        main_layout.addWidget(control_box)

        # --- technique: switches on the first row, parameters on the second ---
        technique_box = QGroupBox()
        i18n.group_title(technique_box, "technique.title")
        self.technique_layout = QGridLayout(technique_box)
        self.technique_layout.setHorizontalSpacing(COL_SPACING)
        self.technique_layout.setVerticalSpacing(ROW_SPACING)

        self.technique_check = QCheckBox()
        i18n.text(self.technique_check, "technique.enabled")
        self.technique_check.setChecked(self.technique_enabled)
        i18n.tip(self.technique_check, "technique.enabled.tip")
        self.technique_check.toggled.connect(self._on_technique_toggled)
        self.technique_layout.addWidget(self.technique_check, 0, 0)

        self.technique_follow_speed_check = QCheckBox()
        i18n.text(self.technique_follow_speed_check, "technique.follow_speed")
        self.technique_follow_speed_check.setChecked(self.technique_follow_speed)
        i18n.tip(self.technique_follow_speed_check, "technique.follow_speed.tip")
        self.technique_follow_speed_check.toggled.connect(self._on_speed_changed)
        self.technique_layout.addWidget(self.technique_follow_speed_check, 0, 2)

        self.technique_style_combo = QComboBox()
        self.technique_style_combo.setFixedWidth(110)
        self._fill_technique_styles()
        self.technique_layout.addWidget(
            self._field("technique.style", self.technique_style_combo), 1, 0
        )

        self.single_kps_edit = self._numbered_edit(
            str(self.technique_single_kps), r"\d*\.?\d*", FIELD_WIDTH, self
        )
        i18n.tip(self.single_kps_edit, "technique.single_kps.tip")
        self.single_kps_edit.editingFinished.connect(self._on_speed_changed)
        self.technique_layout.addWidget(
            self._field("technique.single_kps", self.single_kps_edit), 1, 1
        )

        self.main_hand_combo = QComboBox()
        self.main_hand_combo.setFixedWidth(100)
        self._fill_main_hands()
        self.main_hand_combo.currentIndexChanged.connect(self._on_speed_changed)
        self.technique_layout.addWidget(
            self._field("technique.main_hand", self.main_hand_combo), 1, 2
        )
        self.technique_layout.setColumnStretch(3, 1)

        main_layout.addWidget(technique_box)

        # 初始化时更新一次置灰状态
        self._update_technique_controls_state(self.technique_enabled)

        if self._parse_log_enabled:
            log_box = QGroupBox()
            i18n.group_title(log_box, "logbox.title")
            log_layout = QHBoxLayout(log_box)
            btn_view = QPushButton()
            i18n.text(btn_view, "logbox.view")
            btn_view.clicked.connect(self.show_parse_logs)
            btn_save_log = QPushButton()
            i18n.text(btn_save_log, "logbox.save")
            btn_save_log.clicked.connect(self.save_parse_logs)
            log_layout.addWidget(btn_view)
            log_layout.addWidget(btn_save_log)
            self.lbl_log_count = QLabel()
            i18n.text(self.lbl_log_count, "logbox.count", count=0)
            self.lbl_log_count.setObjectName("hintLabel")
            log_layout.addWidget(self.lbl_log_count)
            log_layout.addStretch(1)
            main_layout.addWidget(log_box)
        status = self.statusBar()
        self.status_label = QLabel()
        self.status_label.setObjectName("hintLabel")
        status.addWidget(self.status_label)
        self._set_status_key("status.ready")
        self.refresh_key_list()
        self._update_window_on_top_action()

    def _fill_technique_styles(self):
        """Fill the style combo; the stored value stays language independent."""
        entries = []
        for name in STYLE_NAMES:
            key = {
                "内轮": "technique.style.inner_wheel",
            }.get(name, name)
            entries.append((name, key))
        i18n.fill_combo(self.technique_style_combo, entries)
        self._select_combo_data(self.technique_style_combo, self.technique_style)

    def _fill_main_hands(self):
        i18n.fill_combo(
            self.main_hand_combo,
            [("right", "technique.hand.right"), ("left", "technique.hand.left")],
        )
        self._select_combo_data(self.main_hand_combo, self.technique_main_hand)

    @staticmethod
    def _select_combo_data(combo, data, default=0):
        index = combo.findData(data)
        combo.setCurrentIndex(index if index >= 0 else default)

    def _current_technique_style(self):
        data = self.technique_style_combo.currentData()
        return data if isinstance(data, str) and data else STYLE_NAMES[0]

    def _current_main_hand(self):
        data = self.main_hand_combo.currentData()
        return data if data in ("left", "right") else "right"

    def _fit_window_to_content(self, grow_only=False):
        """Size the window to its contents, optionally never shrinking it."""
        sizing.fit_window_to_content(self, grow_only=grow_only)

    def _build_output_keys_box(self):
        box = QGroupBox()
        i18n.group_title(box, "output.title")
        layout = QHBoxLayout(box)
        layout.setSpacing(16)
        self._create_key_list(box, "output.left", "left", "left_listbox",
                              "left_del_btn", "left_up_btn", "left_down_btn")
        self._create_key_list(box, "output.right", "right", "right_listbox",
                              "right_del_btn", "right_up_btn", "right_down_btn")
        return box

    def _build_trigger_box(self):
        box = QGroupBox()
        i18n.group_title(box, "trigger.title")
        layout = QHBoxLayout(box)
        layout.setSpacing(ROW_SPACING)
        layout.addWidget(self._field_label("trigger.key", 0))
        self.lbl_hotkey = QLabel(self.macro_hotkey)
        self.lbl_hotkey.setStyleSheet("color: #0b57d0; font-weight: 600;")
        self.lbl_hotkey.setMinimumWidth(VALUE_MIN_WIDTH)
        layout.addWidget(self.lbl_hotkey)
        btn_bind_trigger = QPushButton()
        i18n.text(btn_bind_trigger, "common.bind")
        i18n.tip(btn_bind_trigger, "trigger.bind.tip")
        btn_bind_trigger.clicked.connect(lambda: self.bind_key("trigger"))
        layout.addWidget(btn_bind_trigger)
        layout.addStretch(1)
        return box

    def _build_delay_box(self):
        box = QGroupBox()
        i18n.group_title(box, "delay.title")
        layout = QVBoxLayout(box)
        layout.setSpacing(ROW_SPACING)
        # Earlier / later stacked on their own rows keeps this box about as
        # narrow as the trigger box it sits next to.
        self.lbl_offset_left, btn_left = self._offset_row(
            layout, "delay.earlier", self.offset_left_key, "offset_left"
        )
        self.lbl_offset_right, btn_right = self._offset_row(
            layout, "delay.later", self.offset_right_key, "offset_right"
        )
        self.realtime_offset_check = QCheckBox()
        i18n.text(self.realtime_offset_check, "delay.realtime")
        self.realtime_offset_check.setChecked(self.realtime_offset_enabled)
        i18n.tip(self.realtime_offset_check, "delay.realtime.tip")
        self.realtime_offset_check.toggled.connect(self._on_realtime_offset_toggled)
        layout.addWidget(self.realtime_offset_check)
        return box

    def _offset_row(self, layout, label_key, key_name, key_type):
        row = QHBoxLayout()
        row.setSpacing(6)
        row.addWidget(self._field_label(label_key))
        value = QLabel(key_name)
        value.setStyleSheet("color: #0b57d0; font-weight: 600;")
        value.setMinimumWidth(VALUE_MIN_WIDTH)
        row.addWidget(value)
        btn = QPushButton()
        i18n.text(btn, "common.bind")
        btn.clicked.connect(lambda _checked=False, k=key_type: self.bind_key(k))
        row.addWidget(btn)
        row.addStretch(1)
        layout.addLayout(row)
        return value, btn

    @staticmethod
    def _coerce_macro_end_mode(mode):
        return mode if mode in ("trigger", "esc", "both") else "both"

    def _current_macro_end_mode(self):
        return self._coerce_macro_end_mode(self.macro_end_combo.currentData())

    def _set_macro_end_mode(self, mode):
        index = self.macro_end_combo.findData(self._coerce_macro_end_mode(mode))
        if index >= 0:
            self.macro_end_combo.setCurrentIndex(index)

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
        box = QGroupBox()
        i18n.group_title(box, "key_output.title")
        layout = QHBoxLayout(box)
        layout.setSpacing(16)
        self.disable_key_output_check = QCheckBox()
        i18n.text(self.disable_key_output_check, "key_output.disable")
        self.disable_key_output_check.setChecked(self.disable_key_output)
        i18n.tip(self.disable_key_output_check, "key_output.disable.tip")
        self.disable_key_output_check.toggled.connect(
            self._on_disable_key_output_toggled
        )
        layout.addWidget(self.disable_key_output_check)
        self.suppress_bound_keys_check = QCheckBox()
        i18n.text(self.suppress_bound_keys_check, "key_output.suppress")
        self.suppress_bound_keys_check.setChecked(self.suppress_bound_keys)
        i18n.tip(self.suppress_bound_keys_check, "key_output.suppress.tip")
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
        box = QGroupBox()
        i18n.group_title(box, "macro_end.title")
        layout = QHBoxLayout(box)
        layout.setSpacing(ROW_SPACING)
        layout.addWidget(self._field_label("macro_end.label", 0))
        self.macro_end_combo = QComboBox()
        i18n.fill_combo(
            self.macro_end_combo,
            [
                ("trigger", "macro_end.trigger"),
                ("esc", "macro_end.esc"),
                ("both", "macro_end.both"),
            ],
        )
        self._set_macro_end_mode(self.macro_end_mode)
        self.macro_end_combo.setFixedWidth(140)
        i18n.tip(self.macro_end_combo, "macro_end.tip")
        self.macro_end_combo.currentIndexChanged.connect(
            self._on_macro_end_mode_changed
        )
        layout.addWidget(self.macro_end_combo)
        layout.addStretch(1)
        return box

    def _on_macro_end_mode_changed(self, *_args):
        self.macro_end_mode = self._current_macro_end_mode()
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

    def _division_entries(self):
        return [(d, "division.item", {"n": d}) for d in RHYTHM_HINT_DIVISIONS]

    def _build_rhythm_hint_box(self):
        box = QGroupBox()
        i18n.group_title(box, "rhythm.title")
        layout = QVBoxLayout(box)
        layout.setSpacing(ROW_SPACING)

        self.rhythm_hint_check = QCheckBox()
        i18n.text(self.rhythm_hint_check, "rhythm.enabled")
        self.rhythm_hint_check.setChecked(self.rhythm_hint_enabled)
        i18n.tip(self.rhythm_hint_check, "rhythm.enabled.tip")
        self.rhythm_hint_check.toggled.connect(self._on_rhythm_hint_toggled)
        layout.addWidget(self.rhythm_hint_check)

        params = QHBoxLayout()
        params.setSpacing(COL_SPACING)
        self.rhythm_hint_speed_edit = QLineEdit(str(int(self.rhythm_hint_speed)))
        self.rhythm_hint_speed_edit.setValidator(self._make_validator(r"\d*"))
        self.rhythm_hint_speed_edit.setFixedWidth(FIELD_WIDTH)
        i18n.tip(self.rhythm_hint_speed_edit, "rhythm.speed.tip")
        self.rhythm_hint_speed_edit.editingFinished.connect(
            self._on_rhythm_hint_options_changed
        )
        params.addWidget(
            self._field("common.speed", self.rhythm_hint_speed_edit, minimum=0)
        )

        self.rhythm_hint_division_combo = QComboBox()
        i18n.fill_combo(self.rhythm_hint_division_combo, self._division_entries())
        self._select_combo_data(
            self.rhythm_hint_division_combo, self.rhythm_hint_division
        )
        self.rhythm_hint_division_combo.setFixedWidth(FIELD_WIDTH_WIDE)
        i18n.tip(self.rhythm_hint_division_combo, "division.tip")
        self.rhythm_hint_division_combo.currentIndexChanged.connect(
            self._on_rhythm_hint_options_changed
        )
        params.addWidget(
            self._field("common.division", self.rhythm_hint_division_combo, minimum=0)
        )
        params.addStretch(1)
        layout.addLayout(params)

        extras = QHBoxLayout()
        extras.setSpacing(COL_SPACING)
        self.rhythm_hint_hit_effect_check = QCheckBox()
        i18n.text(self.rhythm_hint_hit_effect_check, "common.hit_effect")
        self.rhythm_hint_hit_effect_check.setChecked(self.rhythm_hint_hit_effect)
        i18n.tip(self.rhythm_hint_hit_effect_check, "rhythm.hit_effect.tip")
        self.rhythm_hint_hit_effect_check.toggled.connect(
            self._on_rhythm_hint_options_changed
        )
        extras.addWidget(self.rhythm_hint_hit_effect_check)

        self.rhythm_hint_multi_fix_check = QCheckBox()
        i18n.text(self.rhythm_hint_multi_fix_check, "common.multi_fix")
        self.rhythm_hint_multi_fix_check.setChecked(self.rhythm_hint_multi_fix)
        i18n.tip(self.rhythm_hint_multi_fix_check, "rhythm.multi_fix.tip")
        self.rhythm_hint_multi_fix_check.toggled.connect(
            self._on_rhythm_hint_options_changed
        )
        extras.addWidget(self.rhythm_hint_multi_fix_check)

        self.rhythm_hint_default_size_btn = QPushButton()
        i18n.text(self.rhythm_hint_default_size_btn, "common.default_size")
        i18n.tip(self.rhythm_hint_default_size_btn, "rhythm.default_size.tip")
        self.rhythm_hint_default_size_btn.clicked.connect(self.reset_rhythm_hint_size)
        extras.addWidget(self.rhythm_hint_default_size_btn)

        self.rhythm_hint_render_btn = QPushButton()
        i18n.text(self.rhythm_hint_render_btn, "common.re_render")
        i18n.tip(self.rhythm_hint_render_btn, "rhythm.re_render.tip")
        self.rhythm_hint_render_btn.clicked.connect(self.re_render_rhythm_hint)
        extras.addWidget(self.rhythm_hint_render_btn)
        extras.addStretch(1)
        layout.addLayout(extras)
        return box

    def _build_falling_notes_box(self):
        box = QGroupBox()
        i18n.group_title(box, "falling.title")
        layout = QVBoxLayout(box)
        layout.setSpacing(ROW_SPACING)

        self.falling_notes_check = QCheckBox()
        i18n.text(self.falling_notes_check, "falling.enabled")
        self.falling_notes_check.setChecked(self.falling_notes_enabled)
        i18n.tip(self.falling_notes_check, "falling.enabled.tip")
        self.falling_notes_check.toggled.connect(self._on_falling_notes_toggled)
        layout.addWidget(self.falling_notes_check)

        params = QHBoxLayout()
        params.setSpacing(COL_SPACING)
        self.falling_notes_speed_edit = QLineEdit(str(int(self.falling_notes_speed)))
        self.falling_notes_speed_edit.setValidator(self._make_validator(r"\d*"))
        self.falling_notes_speed_edit.setFixedWidth(FIELD_WIDTH)
        i18n.tip(self.falling_notes_speed_edit, "falling.speed.tip")
        self.falling_notes_speed_edit.editingFinished.connect(
            self._on_falling_notes_options_changed
        )
        params.addWidget(
            self._field("common.speed", self.falling_notes_speed_edit, minimum=0)
        )

        self.falling_notes_division_combo = QComboBox()
        i18n.fill_combo(self.falling_notes_division_combo, self._division_entries())
        self._select_combo_data(
            self.falling_notes_division_combo, self.falling_notes_division
        )
        self.falling_notes_division_combo.setFixedWidth(FIELD_WIDTH_WIDE)
        i18n.tip(self.falling_notes_division_combo, "division.tip")
        self.falling_notes_division_combo.currentIndexChanged.connect(
            self._on_falling_notes_options_changed
        )
        params.addWidget(
            self._field("common.division", self.falling_notes_division_combo, minimum=0)
        )

        self.falling_notes_lanes_combo = QComboBox()
        self._fill_lanes_combo()
        self.falling_notes_lanes_combo.setFixedWidth(FIELD_WIDTH_WIDE + 16)
        i18n.tip(self.falling_notes_lanes_combo, "falling.lanes.tip")
        self.falling_notes_lanes_combo.currentIndexChanged.connect(
            self._on_falling_notes_options_changed
        )
        params.addWidget(
            self._field("falling.lanes", self.falling_notes_lanes_combo, minimum=0)
        )
        params.addStretch(1)
        layout.addLayout(params)

        extras = QHBoxLayout()
        extras.setSpacing(COL_SPACING)
        self.falling_notes_hit_effect_check = QCheckBox()
        i18n.text(self.falling_notes_hit_effect_check, "common.hit_effect")
        self.falling_notes_hit_effect_check.setChecked(self.falling_notes_hit_effect)
        i18n.tip(self.falling_notes_hit_effect_check, "falling.hit_effect.tip")
        self.falling_notes_hit_effect_check.toggled.connect(
            self._on_falling_notes_options_changed
        )
        extras.addWidget(self.falling_notes_hit_effect_check)

        self.falling_notes_multi_fix_check = QCheckBox()
        i18n.text(self.falling_notes_multi_fix_check, "common.multi_fix")
        self.falling_notes_multi_fix_check.setChecked(self.falling_notes_multi_fix)
        i18n.tip(self.falling_notes_multi_fix_check, "falling.multi_fix.tip")
        self.falling_notes_multi_fix_check.toggled.connect(
            self._on_falling_notes_options_changed
        )
        extras.addWidget(self.falling_notes_multi_fix_check)

        self.falling_notes_default_size_btn = QPushButton()
        i18n.text(self.falling_notes_default_size_btn, "common.default_size")
        i18n.tip(self.falling_notes_default_size_btn, "falling.default_size.tip")
        self.falling_notes_default_size_btn.clicked.connect(self.reset_falling_notes_size)
        extras.addWidget(self.falling_notes_default_size_btn)

        self.falling_notes_render_btn = QPushButton()
        i18n.text(self.falling_notes_render_btn, "common.re_render")
        i18n.tip(self.falling_notes_render_btn, "falling.re_render.tip")
        self.falling_notes_render_btn.clicked.connect(self.re_render_falling_notes)
        extras.addWidget(self.falling_notes_render_btn)
        extras.addStretch(1)
        layout.addLayout(extras)
        return box

    def _fill_lanes_combo(self):
        entries = []
        for lanes in FALLING_NOTES_LANES:
            if lanes == 8:
                entries.append((lanes, "falling.lanes.item_wide"))
            else:
                entries.append((lanes, "falling.lanes.item", {"n": lanes}))
        i18n.fill_combo(self.falling_notes_lanes_combo, entries)
        self._select_combo_data(self.falling_notes_lanes_combo, self.falling_notes_lanes)

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
        self._save_config_file(i18n.tr("reason.rhythm_toggle"))

    def _on_rhythm_hint_closed(self):
        self.rhythm_hint_enabled = False
        self.config["rhythm_hint_enabled"] = False
        if hasattr(self, "rhythm_hint_check"):
            self.rhythm_hint_check.blockSignals(True)
            self.rhythm_hint_check.setChecked(False)
            self.rhythm_hint_check.blockSignals(False)
        self._save_config_file(i18n.tr("reason.rhythm_closed"))

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
            self.rhythm_hint_division = self._coerce_rhythm_hint_division(
                self.rhythm_hint_division_combo.currentData()
            )
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
            self.rhythm_hint_division_combo.blockSignals(True)
            self._select_combo_data(
                self.rhythm_hint_division_combo, self.rhythm_hint_division
            )
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
            self._save_config_file(i18n.tr("reason.rhythm_size"))

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
            self.log_message(
                i18n.tr("log.bpm_timeline_failed", error=e), "error"
            )
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
        self._save_config_file(i18n.tr("reason.falling_toggle"))

    def _on_falling_notes_closed(self):
        self.falling_notes_enabled = False
        self.config["falling_notes_enabled"] = False
        if hasattr(self, "falling_notes_check"):
            self.falling_notes_check.blockSignals(True)
            self.falling_notes_check.setChecked(False)
            self.falling_notes_check.blockSignals(False)
        self._save_config_file(i18n.tr("reason.falling_closed"))

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
            self.falling_notes_division = self._coerce_rhythm_hint_division(
                self.falling_notes_division_combo.currentData()
            )
        if hasattr(self, "falling_notes_lanes_combo"):
            self.falling_notes_lanes = self._coerce_falling_notes_lanes(
                self.falling_notes_lanes_combo.currentData()
            )
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
            self._select_combo_data(
                self.falling_notes_division_combo, self.falling_notes_division
            )
            self.falling_notes_division_combo.blockSignals(False)
        if hasattr(self, "falling_notes_lanes_combo"):
            self.falling_notes_lanes_combo.blockSignals(True)
            self._select_combo_data(
                self.falling_notes_lanes_combo, self.falling_notes_lanes
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
            self._save_config_file(i18n.tr("reason.falling_size"))

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

    def _set_status_key(self, key, color="gray", **fmt):
        """Set the status bar from a translation key and remember it."""
        self._status_state = (key, color, dict(fmt))
        self._set_status(i18n.tr(key, **fmt), color)

    def _create_key_list(self, parent, title_key, key_type, listbox_attr,
                         del_attr, up_attr, down_attr):
        panel = QWidget()
        vlayout = QVBoxLayout(panel)
        vlayout.setContentsMargins(0, 0, 0, 0)
        vlayout.setSpacing(6)
        header = QLabel()
        i18n.text(header, title_key)
        header.setStyleSheet("color: #33404f; font-weight: 600;")
        vlayout.addWidget(header)
        listbox = QListWidget()
        listbox.setFixedHeight(140)
        i18n.tip(listbox, "output.list.tip")
        listbox.itemDoubleClicked.connect(lambda item: self._rebind_key(listbox, key_type))
        vlayout.addWidget(listbox)
        setattr(self, listbox_attr, listbox)
        btn_row = QHBoxLayout()
        btn_row.setSpacing(6)
        add_btn = QPushButton()
        i18n.text(add_btn, "output.add")
        i18n.tip(add_btn, "output.add.tip")
        add_btn.clicked.connect(lambda: self.bind_key(key_type))
        del_btn = QPushButton()
        i18n.text(del_btn, "output.delete")
        i18n.tip(del_btn, "output.delete.tip")
        del_btn.clicked.connect(lambda: self._delete_selected(listbox, key_type))
        up_btn = QPushButton()
        i18n.text(up_btn, "output.up")
        up_btn.clicked.connect(lambda: self._move_item(listbox, key_type, -1))
        down_btn = QPushButton()
        i18n.text(down_btn, "output.down")
        down_btn.clicked.connect(lambda: self._move_item(listbox, key_type, 1))
        for btn in (add_btn, del_btn, up_btn, down_btn):
            # Natural width + a trailing stretch: the labels are never clipped
            # and the row adapts on its own when the language changes.
            btn_row.addWidget(btn)
        btn_row.addStretch(1)
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
            title_key = {
                "trigger": "bind.title.trigger",
                "left": "bind.title.left",
                "right": "bind.title.right",
                "offset_left": "bind.title.offset_left",
                "offset_right": "bind.title.offset_right",
            }[key_type]
        except KeyError:
            self.disable_trigger = False
            return
        parent = self._ui_parent()
        win = BindWindow(parent, i18n.tr(title_key))
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
                self._warn_conflict(parent, "msg.trigger_conflict_output")
                return
            if key in (self.offset_left_key, self.offset_right_key):
                self._warn_conflict(parent, "msg.trigger_conflict_offset")
                return
            self.macro_hotkey = key
            self.config["hotkey"] = self.macro_hotkey
            self.lbl_hotkey.setText(key)
            self._register_trigger_key()
            return
        if key_type in ("offset_left", "offset_right"):
            other_key = self.offset_right_key if key_type == "offset_left" else self.offset_left_key
            if key == self.macro_hotkey:
                self._warn_conflict(parent, "msg.offset_conflict_trigger")
                return
            if key in output_keys:
                self._warn_conflict(parent, "msg.offset_conflict_output")
                return
            if key == other_key:
                self._warn_conflict(parent, "msg.offset_conflict_each_other")
                return
            attr = self._offset_key_attr(key_type)
            setattr(self, attr, key)
            self.config[attr] = key
            getattr(self, self._offset_label_attr(key_type)).setText(key)
            self._refresh_direction_keys()
            return
        if key == self.macro_hotkey:
            self._warn_conflict(parent, "msg.output_conflict_trigger")
            return
        if key in output_keys:
            self._warn_conflict(parent, "msg.duplicate_key")
            return
        if key in (self.offset_left_key, self.offset_right_key):
            self._warn_conflict(parent, "msg.output_conflict_offset")
            return
        self._keys_of(key_type).append(key)
        self._sync_custom_keys()
        self.refresh_key_list()
        self.update_buttons_state()

    @staticmethod
    def _warn_conflict(parent, message_key):
        QMessageBox.warning(parent, i18n.tr("dialog.conflict"), i18n.tr(message_key))

    def _rebind_key(self, listbox, key_type):
        row = listbox.currentRow()
        if row < 0:
            return
        current = self._keys_of(key_type)[row]
        self.disable_trigger = True
        parent = self._ui_parent()
        win = BindWindow(parent, i18n.tr("bind.title.rebind"))
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
            self._warn_conflict(parent, "msg.output_conflict_trigger")
            return
        if key in self.left_keys + self.right_keys:
            self._warn_conflict(parent, "msg.duplicate_key")
            return
        if key in (self.offset_left_key, self.offset_right_key):
            self._warn_conflict(parent, "msg.output_conflict_offset")
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
            self.log_message(i18n.tr("log.trigger_register_failed", error=e), "error")

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
            self.log_message(i18n.tr("log.esc_register_failed", error=e), "error")

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
            self.log_message(i18n.tr("log.direction_hook_failed"), "error")

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
        file_path, _ = QFileDialog.getOpenFileName(
            self, i18n.tr("dialog.select_chart"), "", i18n.tr("filter.adofai")
        )
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
            self._parse_logger(
                "MAIN", i18n.tr("log.processing_start", path=self.file_path)
            )
            ald = ADOLevelData.new(self.file_path)
            ald.set_logger(self._parse_logger)
            ald.decode()
            self.adofai_angle = ADOAngle(ald)
            self.adofai_angle.set_logger(self._parse_logger)
            self.cumulative_times = self.adofai_angle.getMacroCumulativeTimes()
            self.macro_key_info = self.adofai_angle.getMacroKeyInfo()
            self.hold_dict = self.adofai_angle.getHoldDict()
            self.generate_timeline()
            self.log_message(
                i18n.tr("log.parse_done", count=len(self.timeline) // 2), "system"
            )
            self._set_status_key(
                "status.loaded", "green", name=os.path.basename(self.file_path)
            )
            self._update_log_count()
            self._parse_logger(
                "MAIN", i18n.tr("log.parse_logs_done", count=len(self.parse_logs))
            )
        except Exception as e:
            self.log_message(i18n.tr("log.parse_error", error=str(e)), "error")
            self._set_status_key("status.parse_failed", "red")
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

    def _on_offset_changed(self):
        try:
            self.regular_offset_ms = float(self.regular_offset_edit.text())
        except ValueError:
            self.regular_offset_ms = 5.0
        try:
            self.irregular_offset_ms = float(self.irregular_offset_edit.text())
        except ValueError:
            self.irregular_offset_ms = 10.0
        if not self.file_path or self.playback.is_playing:
            return
        if self.macro_key_info:
            self.generate_timeline()
        speed = self._bpm_value(self.speed_edit, 1.0)
        self.playback.preload_timeline(self.timeline, speed)

    def _on_technique_toggled(self, checked):
        """当勾选/取消勾选启用手法模拟时触发"""
        self._update_technique_controls_state(checked)
        self._on_speed_changed()

    def _update_technique_controls_state(self, enabled):
        """根据开关状态，自动置灰或启用手法模拟下方的控件"""
        for i in range(self.technique_layout.count()):
            widget = self.technique_layout.itemAt(i).widget()
            # 排除开关按钮本身，其余控件随开关状态启用/禁用
            if widget and widget != self.technique_check:
                widget.setEnabled(enabled)

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
            return self._current_main_hand()
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
            main_hand = self._current_main_hand()
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
                
        angles = None
        if self.adofai_angle is not None:
            angles = self.adofai_angle.getMacroTurnAngles(selected_macro_key_info)
            
        if angles and selected_macro_key_info:
            notes_temp = [copy.deepcopy(n) for n in selected_macro_key_info]
            current_bpm = self._chart_bpm()
            limit = track_angle_limit(current_bpm) if current_bpm > 0 else None
            annotate_multi_press(notes_temp, angles=angles, limit=limit)
            for i in range(len(selected_macro_key_info)):
                selected_macro_key_info[i]['multi_count'] = notes_temp[i].get('multi_count', 1)

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
            angles=angles,
            regular_offset_ms=self.regular_offset_ms,
            irregular_offset_ms=self.irregular_offset_ms,
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
                "style": self._current_technique_style(),
                "single_kps": self._bpm_value(self.single_kps_edit, 6.5),
                "main_hand": self._current_main_hand(),
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
            "regular_offset_ms": self.regular_offset_ms,
            "irregular_offset_ms": self.irregular_offset_ms,
            "font_name": self.font_name,
            "font_size": self.font_size,
        }

    def export_config_file(self):
        file_path, _ = QFileDialog.getSaveFileName(
            self,
            i18n.tr("dialog.export_config"),
            "adofai_macro_config.json",
            i18n.tr("filter.json"),
        )
        if not file_path:
            return
        if config_module.export_config(file_path, self._collect_config()):
            self.log_message(i18n.tr("log.config_exported", path=file_path), "system")
            self._set_status_key(
                "status.config_exported", "green", name=os.path.basename(file_path)
            )
        else:
            QMessageBox.critical(
                self, i18n.tr("msg.export_failed"),
                i18n.tr("msg.export_failed.body", path=file_path),
            )

    def import_config_file(self):
        file_path, _ = QFileDialog.getOpenFileName(
            self,
            i18n.tr("dialog.import_config"),
            "",
            i18n.tr("filter.json"),
        )
        if not file_path:
            return
        data = config_module.import_config(file_path)
        if data is None:
            QMessageBox.critical(
                self, i18n.tr("msg.import_failed"),
                i18n.tr("msg.import_failed.body", path=file_path),
            )
            return
        self.stop_play()
        self._apply_config(data)
        self.log_message(i18n.tr("log.config_imported", path=file_path), "system")
        self._set_status_key(
            "status.config_imported", "green", name=os.path.basename(file_path)
        )

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
                    i18n.tr(
                        "log.import_offset_left_conflict",
                        key=offset_left, current=self.offset_left_key,
                    ),
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
                    i18n.tr(
                        "log.import_offset_right_conflict",
                        key=offset_right, current=self.offset_right_key,
                    ),
                    "warning",
                )
        hotkey = data.get("hotkey")
        if isinstance(hotkey, str) and hotkey:
            conflict = (hotkey.lower() in output_lower
                        or hotkey in (self.offset_left_key, self.offset_right_key))
            if conflict:
                self.log_message(
                    i18n.tr(
                        "log.import_hotkey_conflict",
                        key=hotkey, current=self.macro_hotkey,
                    ),
                    "warning",
                )
            else:
                self.macro_hotkey = hotkey
                self.lbl_hotkey.setText(hotkey)
                self._register_trigger_key()
        else:
            self.log_message(i18n.tr("log.import_hotkey_missing"), "warning")
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
        mode = self._coerce_macro_end_mode(data.get("macro_end_mode", self.macro_end_mode))
        self.macro_end_mode = mode
        if hasattr(self, "macro_end_combo"):
            self.macro_end_combo.blockSignals(True)
            self._set_macro_end_mode(mode)
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
                self._select_combo_data(self.technique_style_combo, style)
            elif isinstance(style, int) and 0 <= style < len(STYLE_NAMES_LEGACY):
                self._select_combo_data(
                    self.technique_style_combo, STYLE_NAMES_LEGACY[style]
                )
            try:
                kps = float(tech.get("single_kps", self.technique_single_kps))
                if kps > 0:
                    self.single_kps_edit.setText(str(kps))
            except (TypeError, ValueError):
                pass
            hand = tech.get("main_hand", self.technique_main_hand)
            self._select_combo_data(
                self.main_hand_combo, "right" if hand in ("right", "右手") else "left"
            )
            self.technique_follow_speed_check.setChecked(bool(tech.get("follow_speed", True)))
        
        # 在这里补充一行：当导入配置时，同步更新界面置灰状态
        self._update_technique_controls_state(self.technique_check.isChecked())

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
            
        if data.get("regular_offset_ms") is not None:
            self.regular_offset_ms = float(data.get("regular_offset_ms", 5.0))
        if data.get("irregular_offset_ms") is not None:
            self.irregular_offset_ms = float(data.get("irregular_offset_ms", 10.0))
        if hasattr(self, "regular_offset_edit"):
            self.regular_offset_edit.blockSignals(True)
            self.regular_offset_edit.setText(str(self.regular_offset_ms))
            self.regular_offset_edit.blockSignals(False)
        if hasattr(self, "irregular_offset_edit"):
            self.irregular_offset_edit.blockSignals(True)
            self.irregular_offset_edit.setText(str(self.irregular_offset_ms))
            self.irregular_offset_edit.blockSignals(False)

        if data.get("font_name") is not None:
            self.font_name = str(data.get("font_name", "Microsoft YaHei"))
        if data.get("font_size") is not None:
            self.font_size = int(data.get("font_size", 9))
            
        if hasattr(self, "font_combo"):
            self.font_combo.blockSignals(True)
            idx = self.font_combo.findText(self.font_name)
            if idx >= 0:
                self.font_combo.setCurrentIndex(idx)
            self.font_combo.blockSignals(False)
        if hasattr(self, "font_size_spin"):
            self.font_size_spin.blockSignals(True)
            self.font_size_spin.setValue(self.font_size)
            self.font_size_spin.blockSignals(False)
            
        self._apply_global_font()

        if data.get("language") is not None:
            self.set_language(data.get("language"))

        self.config.update(self._collect_config())
        if self.file_path:
            self.generate_timeline()
            speed = float(self.speed_edit.text() or 1.0)
            self.playback.preload_timeline(self.timeline, speed)
            self._refresh_hint_windows()
            self.log_message(i18n.tr("log.timeline_regenerated"), "system")

    def toggle_play(self):
        if self.disable_trigger:
            return
        if not self.playback.is_playing:
            self.start_play()
        else:
            self.stop_play()

    def start_play(self):
        if not self.file_path:
            QMessageBox.warning(
                self, i18n.tr("dialog.warning"), i18n.tr("msg.select_chart_first")
            )
            return
        self.playback.reset_offset()
        self._update_offset_display(0)
        if self.rhythm_hint_window is not None:
            self.rhythm_hint_window.reset_position()
        if self.falling_notes_window is not None:
            self.falling_notes_window.reset_position()
        self._set_status_key("status.running", "blue")
        self._register_direction_keys()
        try:
            self.playback.start(
                self.verbose_check.isChecked(),
                on_stopped=self.events.playback_finished.emit,
            )
        except Exception as e:
            self.log_message(i18n.tr("log.start_failed", error=e), "error")
            self._set_status_key("status.start_failed", "red")
            self._clear_direction_hooks()
            return
        self._refresh_escape_hook()

    def stop_play(self, force=False):
        self._clear_direction_hooks()
        self._unregister_escape_hook()
        self.playback.stop()
        self._set_status_key("status.stopped", "gray")

    def _on_playback_finished(self):
        self._toggle_debounce = False
        if hasattr(self, "_debounce_timer"):
            self._debounce_timer.stop()
        if self.falling_notes_window is not None:
            self.falling_notes_window.release_active_holds()
        self._set_status_key("status.ready", "gray")
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
                "style": self._current_technique_style(),
                "single_kps": self._bpm_value(self.single_kps_edit, 6.5),
                "main_hand": self._current_main_hand(),
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
            regular_offset_ms=self.regular_offset_ms,
            irregular_offset_ms=self.irregular_offset_ms,
            font_name=self.font_name,
            font_size=self.font_size,
            language=i18n.get_language(),
        )
        if reason and not ok:
            self.log_message(i18n.tr("log.config_save_failed", reason=reason), "error")
        return ok