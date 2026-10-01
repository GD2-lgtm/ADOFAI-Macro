"""Runtime internationalisation (Simplified Chinese / English) for the UI.

The module keeps a flat table of ``key -> (zh, en)`` pairs and a registry of
widgets that need to be refreshed when the language changes.  Widgets register
themselves through the small helpers below, so no window has to implement a
hand written ``retranslate`` pass.

Typical use::

    from .. import i18n

    i18n.text(self.verbose_check, "control.verbose")
    i18n.tip(self.verbose_check, "control.verbose.tip")
    i18n.fill_combo(combo, [(4, "division.item"), (8, "division.item")])

``division.item`` may contain ``{n}``; pass the value when filling the entry
instead (see :func:`fill_combo`).
"""

from __future__ import annotations

import weakref

DEFAULT_LANGUAGE = "zh"
SUPPORTED_LANGUAGES = ("zh", "en")

# Label shown in the language menu; deliberately never translated.
LANGUAGE_LABELS = {
    "zh": "简体中文",
    "en": "English",
}

_INDEX = {code: index for index, code in enumerate(SUPPORTED_LANGUAGES)}

_current_language = DEFAULT_LANGUAGE
_bindings = []


def _entry(zh, en):
    return (zh, en)


STRINGS = {
    # ---------------------------------------------------------------- general
    "app.title": _entry("ADOFAI Macro", "ADOFAI Macro"),
    "common.ms": _entry("ms", "ms"),
    "common.bind": _entry("绑定", "Bind"),
    "common.speed": _entry("流速:", "Speed:"),
    "common.division": _entry("切分:", "Division:"),
    "common.hit_effect": _entry("判定特效", "Hit Effect"),
    "common.multi_fix": _entry("多押提示", "Multi-Press Hint"),
    "common.default_size": _entry("默认大小", "Default Size"),
    "common.re_render": _entry("重新渲染", "Re-render"),
    "common.ok": _entry("确定", "OK"),
    "common.cancel": _entry("取消", "Cancel"),
    "common.close": _entry("关闭", "Close"),

    # ------------------------------------------------------------------- menu
    "menu.file": _entry("文件(&F)", "&File"),
    "menu.load_chart": _entry("加载谱面...", "Load Chart..."),
    "menu.import_config": _entry("导入配置...", "Import Config..."),
    "menu.export_config": _entry("导出配置...", "Export Config..."),
    "menu.quit": _entry("退出", "Quit"),
    "menu.other_settings": _entry("其他设置", "Other Settings"),
    "menu.other_settings.tip": _entry(
        "打开其他设置窗口", "Open the other settings window"
    ),
    "menu.window_on_top": _entry("窗口置顶：{state}", "Always on Top: {state}"),
    "menu.window_on_top.tip": _entry(
        "切换程序所有窗口的窗口置顶状态",
        "Toggle always-on-top for every window of this app",
    ),
    "menu.language": _entry("语言(&L)", "&Language"),
    "menu.language.tip": _entry(
        "切换界面语言，立即生效并保存到配置",
        "Switch the interface language; applied immediately and saved to the config",
    ),
    "state.on": _entry("开", "On"),
    "state.off": _entry("关", "Off"),

    # --------------------------------------------------------------- file bar
    "file.load": _entry("加载谱面", "Load Chart"),
    "file.load.tip": _entry(
        "选择 .adofai 谱面文件 (Ctrl+O)，或直接拖放文件到窗口",
        "Pick a .adofai chart (Ctrl+O), or drag a file onto the window",
    ),
    "file.none": _entry("未选择谱面", "No chart selected"),
    "file.key_config": _entry("按键配置", "Key Bindings"),
    "file.key_config.tip": _entry(
        "打开按键配置窗口", "Open the key binding window"
    ),

    # -------------------------------------------------------- playback control
    "control.title": _entry("播放控制", "Playback"),
    "control.speed": _entry("倍速:", "Speed:"),
    "control.speed.tip": _entry("播放倍速", "Playback speed multiplier"),
    "control.press_duration": _entry("按键时长:", "Key Hold:"),
    "control.press_duration.tip": _entry(
        "普通按键的按下持续时间(ms)", "How long a normal key stays pressed (ms)"
    ),
    "control.offset": _entry("偏移:", "Offset:"),
    "control.offset.hint": _entry("(←提前 延后→)", "(← earlier / later →)"),
    "control.verbose": _entry("详细输出", "Verbose Output"),
    "control.verbose.tip": _entry(
        "打印每个按键的按下 / 释放时间", "Print press / release time of every key"
    ),
    "control.regular_offset": _entry("正常偏移 ±", "Regular Offset ±"),
    "control.regular_offset.tip": _entry(
        "正常角度(如 90°、180°)及双押/三连音的随机偏移量(ms)",
        "Random offset for regular angles (e.g. 90°, 180°) and double / "
        "triple presses (ms)",
    ),
    "control.irregular_offset": _entry("不规则偏移 ±", "Irregular Offset ±"),
    "control.irregular_offset.tip": _entry(
        "不规则角度(如 45°、58°)的随机偏移量(ms)",
        "Random offset for irregular angles (e.g. 45°, 58°) (ms)",
    ),
    "control.font": _entry("界面字体:", "UI Font:"),
    "control.font.tip": _entry(
        "更改程序界面的显示字体", "Change the font used by the interface"
    ),
    "control.font_size": _entry("字号:", "Font Size:"),
    "control.font_size.tip": _entry(
        "更改程序界面的字体大小", "Change the interface font size"
    ),

    # --------------------------------------------------------------- technique
    "technique.title": _entry("手法模拟", "Technique Simulation"),
    "technique.enabled": _entry("启用手法模拟", "Enable Technique Simulation"),
    "technique.enabled.tip": _entry(
        "用拟人双手多指手法分配按键(内轮 V3.3)",
        "Assign keys with a human-like two-hand multi-finger technique "
        "(Inner Wheel V3.3)",
    ),
    "technique.style": _entry("风格:", "Style:"),
    "technique.style.inner_wheel": _entry("内轮", "Inner Wheel"),
    "technique.single_kps": _entry("单指KPS:", "Finger KPS:"),
    "technique.single_kps.tip": _entry(
        "单手单指可达到的按键速度(次/秒)，决定轮指阈值",
        "Key presses per second a single finger can reach; decides the "
        "rolling threshold",
    ),
    "technique.main_hand": _entry("主手:", "Main Hand:"),
    "technique.hand.right": _entry("右手", "Right"),
    "technique.hand.left": _entry("左手", "Left"),
    "technique.follow_speed": _entry("根据倍速进行解析", "Scale with Speed"),
    "technique.follow_speed.tip": _entry(
        "勾选后，手法模拟按倍速缩放按键间隔再分配手指\n"
        "(如 2x 倍速时按 2 倍按键密度解析手法);\n"
        "不勾选则始终按 1x 原速解析",
        "When checked, the technique simulation scales the key intervals by "
        "the speed\nmultiplier before assigning fingers (2x speed is simulated "
        "at 2x key density);\nunchecked always simulates at 1x",
    ),

    # ---------------------------------------------------------- parse log box
    "logbox.title": _entry("谱面解析日志", "Chart Parse Log"),
    "logbox.view": _entry("查看日志", "View Log"),
    "logbox.save": _entry("保存日志", "Save Log"),
    "logbox.count": _entry("日志: {count} 条", "Log: {count} entries"),
    "logbox.window": _entry("谱面解析日志", "Parse Log"),
    "logbox.save_to_file": _entry("保存到文件", "Save to File"),
    "logbox.save_dialog": _entry("保存谱面解析日志", "Save Parse Log"),
    "logbox.no_logs": _entry("没有可保存的日志", "There is no log to save"),
    "logbox.saved": _entry("日志已保存: {path}", "Log saved: {path}"),
    "logbox.save_failed": _entry(
        "保存日志失败: {error}", "Failed to save the log: {error}"
    ),
    "filter.text": _entry(
        "文本文件 (*.txt);;所有文件 (*.*)", "Text Files (*.txt);;All Files (*.*)"
    ),
    "filter.json": _entry(
        "JSON 配置文件 (*.json);;所有文件 (*.*)",
        "JSON Config (*.json);;All Files (*.*)",
    ),
    "filter.adofai": _entry("ADOFAI文件 (*.adofai)", "ADOFAI Chart (*.adofai)"),

    # -------------------------------------------------------- output keys box
    "output.title": _entry("输出按键设置", "Output Keys"),
    "output.left": _entry("左手按键", "Left Hand Keys"),
    "output.right": _entry("右手按键", "Right Hand Keys"),
    "output.list.tip": _entry(
        "双击列表项可直接修改该按键", "Double-click an entry to change that key"
    ),
    "output.add": _entry("＋ 添加", "＋ Add"),
    "output.add.tip": _entry("绑定一个新按键", "Bind a new key"),
    "output.delete": _entry("－ 删除", "－ Delete"),
    "output.delete.tip": _entry("删除选中按键", "Delete the selected key"),
    "output.up": _entry("↑ 上移", "↑ Up"),
    "output.down": _entry("↓ 下移", "↓ Down"),

    # ------------------------------------------------------------ trigger box
    "trigger.title": _entry("触发键设置", "Trigger Key"),
    "trigger.key": _entry("触发键:", "Trigger:"),
    "trigger.bind.tip": _entry("重新绑定全局触发键", "Rebind the global trigger key"),

    # -------------------------------------------------------------- delay box
    "delay.title": _entry("延迟调整", "Offset Adjustment"),
    "delay.earlier": _entry("提前:", "Earlier:"),
    "delay.later": _entry("延后:", "Later:"),
    "delay.realtime": _entry("实时延迟调节", "Realtime Offset Adjustment"),
    "delay.realtime.tip": _entry(
        "开启后可在播放时用「提前/延后」键实时调整延迟",
        "When enabled, the Earlier / Later keys adjust the delay while playing",
    ),

    # --------------------------------------------------------- key output box
    "key_output.title": _entry("按键输出", "Key Output"),
    "key_output.disable": _entry("禁用 Macro 按键输出", "Disable Macro Key Output"),
    "key_output.disable.tip": _entry(
        "勾选后 Macro 不再向游戏输出按键，只保留节奏提示 / 下落式窗口的播放\n"
        "(可以用来只看谱面、或手动跟着提示打)",
        "When checked the macro stops sending keys to the game and only keeps "
        "the\nrhythm hint / falling notes playback (useful to watch a chart or "
        "to play along)",
    ),
    "key_output.suppress": _entry("屏蔽已绑定按键输入", "Suppress Bound Key Input"),
    "key_output.suppress.tip": _entry(
        "勾选(默认)：除了输出按键以外，程序里已绑定的按键都不会传给游戏\n"
        "（触发键、偏移调节键、结束键 ESC），避免误触发游戏自身的按键功能\n"
        "取消勾选：这些绑定键同时也会被游戏收到",
        "Checked (default): apart from the output keys, every key bound in this "
        "app is\nswallowed (trigger, offset keys, the ESC end key) so the game "
        "does not react to\nthem.\nUnchecked: those bound keys are delivered to "
        "the game as well",
    ),

    # ---------------------------------------------------------- macro end box
    "macro_end.title": _entry("Macro 结束方式", "Macro End Mode"),
    "macro_end.label": _entry("结束方式:", "End Mode:"),
    "macro_end.trigger": _entry("仅触发键", "Trigger Key Only"),
    "macro_end.esc": _entry("仅 ESC", "ESC Only"),
    "macro_end.both": _entry("均生效", "Both"),
    "macro_end.tip": _entry(
        "指定结束 Macro 的条件，修改后立即生效",
        "Choose what stops the macro; applied immediately",
    ),

    # -------------------------------------------------------- rhythm hint box
    "rhythm.title": _entry("节奏提示", "Rhythm Hint"),
    "rhythm.enabled": _entry("启用节奏提示窗口", "Enable Rhythm Hint Window"),
    "rhythm.enabled.tip": _entry(
        "开启后自动打开独立的节奏提示窗口\n"
        "(太鼓达人风格谱面：红圈=普通按键，黄圈=长按按键)",
        "Opens a separate rhythm hint window automatically\n"
        "(Taiko-style chart: red circle = normal key, yellow circle = hold key)",
    ),
    "rhythm.speed.tip": _entry(
        "音符向左移动的速度(整数)：100 = 1x，200 = 2x，50 = 0.5x",
        "How fast notes travel left (integer): 100 = 1x, 200 = 2x, 50 = 0.5x",
    ),
    "division.item": _entry("{n}分", "1/{n}"),
    "division.tip": _entry(
        "切分线密度：按 4/8/16/32 分切割",
        "Beat line density: split into 1/4, 1/8, 1/16 or 1/32",
    ),
    "rhythm.hit_effect.tip": _entry(
        "是否显示判定特效(音符到达判定点时放大的白色圆环)",
        "Show a hit effect (an expanding white ring when a note reaches the "
        "judgement point)",
    ),
    "rhythm.multi_fix.tip": _entry(
        "多押只显示组内第一个按键，并在圈内用数字标出这一押要同时按几个键\n"
        "(多押判据：相邻音符按下间隔 <50ms，且后一格轨道夹角 "
        "<=30°(轨道 BPM>=300) / <=15°(轨道 BPM<300))",
        "For a multi-press only the first key of the group is shown, with a "
        "number inside\nthe circle telling how many keys to press at once\n"
        "(criteria: press gap < 50ms and the next tile's turn angle <= 30° at "
        "BPM >= 300,\nor <= 15° below 300 BPM)",
    ),
    "rhythm.default_size.tip": _entry(
        "把节奏提示窗口恢复到默认大小(900×150)",
        "Restore the rhythm hint window to its default size (900×150)",
    ),
    "rhythm.re_render.tip": _entry(
        "重新渲染节奏提示窗口(不需要按触发键，窗口回到谱面起点)",
        "Re-render the rhythm hint window (no trigger key needed; it returns "
        "to the chart start)",
    ),

    # ------------------------------------------------------- falling notes box
    "falling.title": _entry("下落式", "Falling Notes"),
    "falling.enabled": _entry("启用下落式窗口", "Enable Falling Notes Window"),
    "falling.enabled.tip": _entry(
        "开启后自动打开独立的下落式窗口\n"
        "(按键从上往下坠落，落到判定线时消失；左侧红色，右侧蓝色)",
        "Opens a separate falling notes window automatically\n"
        "(keys fall from the top and vanish on the judgement line; left red, "
        "right blue)",
    ),
    "falling.speed.tip": _entry(
        "音符下落的快慢(整数)：100 = 1x，200 = 2x，50 = 0.5x",
        "How fast notes fall (integer): 100 = 1x, 200 = 2x, 50 = 0.5x",
    ),
    "falling.lanes": _entry("轨道数:", "Lanes:"),
    "falling.lanes.item": _entry("{n}K", "{n}K"),
    "falling.lanes.item_wide": _entry("8(16)K", "8(16)K"),
    "falling.lanes.tip": _entry(
        "轨道数量：4K(每手 2 轨) 或 8(16)K(每手 4 轨，支持到16键)，左右各占一半",
        "Number of lanes: 4K (2 per hand) or 8(16)K (4 per hand, up to 16 "
        "keys), split evenly between the two hands",
    ),
    "falling.hit_effect.tip": _entry(
        "是否显示判定特效(音符到达判定线时白色长方形由内向外扩散)",
        "Show a hit effect (a white rectangle expanding outwards when a note "
        "reaches the judgement line)",
    ),
    "falling.multi_fix.tip": _entry(
        "被识别为多押的一组按键，在下落式中按下时间对齐到组内第一个按键\n"
        "(多押判据：相邻音符按下间隔 <50ms，且后一格轨道夹角 "
        "<=30°(轨道 BPM>=300) / <=15°(轨道 BPM<300))",
        "For a group detected as a multi-press, the falling notes align their "
        "press time to\nthe first key of the group\n"
        "(criteria: press gap < 50ms and the next tile's turn angle <= 30° at "
        "BPM >= 300,\nor <= 15° below 300 BPM)",
    ),
    "falling.default_size.tip": _entry(
        "把下落式窗口恢复到默认大小(380×820)",
        "Restore the falling notes window to its default size (380×820)",
    ),
    "falling.re_render.tip": _entry(
        "重新渲染下落式窗口(不需要按触发键，窗口回到谱面起点)",
        "Re-render the falling notes window (no trigger key needed; it returns "
        "to the chart start)",
    ),

    # ---------------------------------------------------------- child windows
    "window.key_config": _entry("按键配置", "Key Bindings"),
    "window.other_settings": _entry("其他设置", "Other Settings"),
    "window.rhythm_hint": _entry("节奏提示", "Rhythm Hint"),
    "window.falling_notes": _entry("下落式", "Falling Notes"),
    "canvas.placeholder": _entry("未加载谱面", "No chart loaded"),

    # ------------------------------------------------------------ bind window
    "bind.prompt": _entry("请按下需要绑定的按键", "Press the key you want to bind"),
    "bind.confirm": _entry("是否绑定 [{name}]？", "Bind [{name}]?"),
    "bind.title.trigger": _entry("绑定触发键", "Bind Trigger Key"),
    "bind.title.left": _entry("绑定左手按键", "Bind Left Hand Key"),
    "bind.title.right": _entry("绑定右手按键", "Bind Right Hand Key"),
    "bind.title.offset_left": _entry("绑定提前键", "Bind Earlier Key"),
    "bind.title.offset_right": _entry("绑定延后键", "Bind Later Key"),
    "bind.title.rebind": _entry("修改按键", "Change Key"),

    # --------------------------------------------------------------- messages
    "dialog.conflict": _entry("冲突", "Conflict"),
    "dialog.warning": _entry("警告", "Warning"),
    "dialog.info": _entry("提示", "Notice"),
    "msg.trigger_conflict_output": _entry(
        "触发键不能与输出键重复！", "The trigger key cannot be one of the output keys!"
    ),
    "msg.trigger_conflict_offset": _entry(
        "触发键不能与延迟调整键重复！",
        "The trigger key cannot be one of the offset keys!",
    ),
    "msg.offset_conflict_trigger": _entry(
        "延迟调整键不能与触发键相同！", "An offset key cannot be the trigger key!"
    ),
    "msg.offset_conflict_output": _entry(
        "延迟调整键不能与输出键重复！", "An offset key cannot be one of the output keys!"
    ),
    "msg.offset_conflict_each_other": _entry(
        "提前键和延后键不能相同！", "The earlier and later keys must differ!"
    ),
    "msg.output_conflict_trigger": _entry(
        "输出键不能与触发键相同！", "An output key cannot be the trigger key!"
    ),
    "msg.output_conflict_offset": _entry(
        "输出键不能与延迟调整键重复！", "An output key cannot be one of the offset keys!"
    ),
    "msg.duplicate_key": _entry(
        "该按键已存在于按键列表中！", "That key is already in the key list!"
    ),
    "msg.select_chart_first": _entry("请先选择谱面文件", "Load a chart first"),
    "msg.export_failed": _entry("导出失败", "Export Failed"),
    "msg.export_failed.body": _entry(
        "无法写入文件:\n{path}", "Cannot write the file:\n{path}"
    ),
    "msg.import_failed": _entry("导入失败", "Import Failed"),
    "msg.import_failed.body": _entry(
        "无法读取配置文件:\n{path}", "Cannot read the config file:\n{path}"
    ),
    "dialog.select_chart": _entry("选择谱面文件", "Select Chart File"),
    "dialog.export_config": _entry("导出配置文件", "Export Config"),
    "dialog.import_config": _entry("导入配置文件", "Import Config"),

    # ---------------------------------------------------------------- status
    "status.ready": _entry("就绪", "Ready"),
    "status.running": _entry("运行中...", "Running..."),
    "status.stopped": _entry("已停止", "Stopped"),
    "status.parse_failed": _entry("解析失败", "Parse Failed"),
    "status.start_failed": _entry("启动失败", "Failed to Start"),
    "status.loaded": _entry("已加载: {name}", "Loaded: {name}"),
    "status.config_exported": _entry("配置已导出: {name}", "Config exported: {name}"),
    "status.config_imported": _entry("配置已导入: {name}", "Config imported: {name}"),

    # ------------------------------------------------- console / parse log
    "log.config_exported": _entry("配置已导出: {path}", "Config exported: {path}"),
    "log.config_imported": _entry("配置已导入: {path}", "Config imported: {path}"),
    "log.window_on_top_failed": _entry(
        "设置窗口置顶失败: {error}", "Failed to set always-on-top: {error}"
    ),
    "log.bpm_timeline_failed": _entry(
        "读取谱面 BPM 变化失败，按固定 BPM 显示: {error}",
        "Failed to read the chart BPM timeline; using a fixed BPM: {error}",
    ),
    "log.trigger_register_failed": _entry(
        "注册触发键失败: {error}", "Failed to register the trigger key: {error}"
    ),
    "log.esc_register_failed": _entry(
        "注册 ESC 结束键失败: {error}", "Failed to register the ESC end key: {error}"
    ),
    "log.direction_hook_failed": _entry(
        "注册延迟调整键钩子失败", "Failed to register the offset key hook"
    ),
    "log.processing_start": _entry("开始处理文件: {path}", "Processing file: {path}"),
    "log.parse_done": _entry(
        "文件解析完成: {count} 个按键事件", "Chart parsed: {count} key events"
    ),
    "log.parse_logs_done": _entry(
        "处理完成，共生成 {count} 条日志", "Done; {count} log entries generated"
    ),
    "log.parse_error": _entry("解析错误: {error}", "Parse error: {error}"),
    "log.import_offset_left_conflict": _entry(
        "导入配置: 提前键 '{key}' 存在冲突，保留当前值 '{current}'",
        "Import: earlier key '{key}' conflicts; keeping '{current}'",
    ),
    "log.import_offset_right_conflict": _entry(
        "导入配置: 延后键 '{key}' 存在冲突，保留当前值 '{current}'",
        "Import: later key '{key}' conflicts; keeping '{current}'",
    ),
    "log.import_hotkey_conflict": _entry(
        "导入配置: 触发键 '{key}' 与其它按键冲突，保留当前触发键 '{current}'",
        "Import: trigger key '{key}' conflicts with another key; keeping '{current}'",
    ),
    "log.import_hotkey_missing": _entry(
        "导入配置: 未找到有效的 hotkey，保留当前触发键",
        "Import: no valid hotkey found; keeping the current trigger key",
    ),
    "log.timeline_regenerated": _entry(
        "时间线已按新配置重新生成", "Timeline regenerated with the new config"
    ),
    "log.start_failed": _entry(
        "启动 Macro 失败: {error}", "Failed to start the macro: {error}"
    ),
    "log.config_save_failed": _entry(
        "配置保存失败({reason})", "Failed to save the config ({reason})"
    ),
    "log.playback_start": _entry("=== Macro 开始 ===", "=== Macro start ==="),
    "log.playback_end": _entry("=== Macro 结束 ===", "=== Macro end ==="),
    "log.key_failed": _entry("按键失败 [{key}]: {error}", "Key failed [{key}]: {error}"),
    "log.sendinput_fallback": _entry(
        "SendInput 注入失败，已回退", "SendInput injection failed; fell back"
    ),
    "log.playback_error": _entry("错误: {error}", "Error: {error}"),
    "log.preload_failed": _entry(
        "预热 Macro 子进程失败: {error}", "Failed to preload the macro subprocess: {error}"
    ),
    "log.load_config_failed": _entry(
        "加载配置失败: {error}", "Failed to load the config: {error}"
    ),
    "log.save_config_failed": _entry(
        "保存配置失败: {error}", "Failed to save the config: {error}"
    ),
    "log.export_config_failed": _entry(
        "导出配置失败: {error}", "Failed to export the config: {error}"
    ),
    "log.import_config_failed": _entry(
        "导入配置失败: {error}", "Failed to import the config: {error}"
    ),
    "log.import_config_not_object": _entry(
        "导入配置失败: 文件内容不是 JSON 对象: {path}",
        "Failed to import the config: the file is not a JSON object: {path}",
    ),
    "parse.no_angle_data": _entry(
        "谱面里既没有 angleData 也没有 pathData",
        "The chart contains neither angleData nor pathData",
    ),
    "parse.path_unknown_chars": _entry(
        "pathData 里有 {count} 种角度表外的字符: {details}。"
        "这些格子已按「沿用上一格角度(直行)」处理，请检查该处谱面。",
        "pathData contains {count} character(s) outside the angle table: "
        "{details}. Those tiles were treated as \"keep the previous angle "
        "(straight)\"; please check the chart there.",
    ),
    "parse.warning_prefix": _entry("[解析警告] ", "[Parse warning] "),

    # ------------------------------------------------------ config save reasons
    "reason.rhythm_toggle": _entry("节奏提示开关", "rhythm hint toggle"),
    "reason.rhythm_closed": _entry("关闭节奏提示窗口", "closing the rhythm hint window"),
    "reason.rhythm_size": _entry("节奏提示分辨率", "rhythm hint resolution"),
    "reason.falling_toggle": _entry("下落式开关", "falling notes toggle"),
    "reason.falling_closed": _entry("关闭下落式窗口", "closing the falling notes window"),
    "reason.falling_size": _entry("下落式分辨率", "falling notes resolution"),
}


def normalize_language(code, default=DEFAULT_LANGUAGE):
    """Return a supported language code for *code*, or *default*."""
    if isinstance(code, str):
        text = code.strip().lower().replace("_", "-")
        if text in _INDEX:
            return text
        if text.startswith("zh"):
            return "zh"
        if text.startswith("en"):
            return "en"
    return default


def get_language():
    return _current_language


def set_language(code):
    """Switch the active language; returns True when it actually changed."""
    global _current_language
    resolved = normalize_language(code, _current_language)
    if resolved == _current_language:
        return False
    _current_language = resolved
    return True


def tr(key, **kwargs):
    """Translate *key* into the active language; unknown keys echo back."""
    entry = STRINGS.get(key)
    if entry is None:
        return key
    index = _INDEX.get(_current_language, 0)
    text = entry[index] if index < len(entry) else entry[0]
    if not text:
        text = entry[0] or key
    if kwargs:
        try:
            return text.format(**kwargs)
        except (KeyError, IndexError, ValueError):
            return text
    return text


# --------------------------------------------------------------------- registry

def on_retranslate(widget, apply):
    """Run ``apply(widget)`` again whenever the language changes."""
    if widget is None:
        return widget
    try:
        ref = weakref.ref(widget)
    except TypeError:
        return widget
    _bindings.append((ref, apply))
    return widget


def retranslate_all():
    """Refresh every registered widget. Safe to call at any time."""
    live = []
    for ref, apply in _bindings:
        widget = ref()
        if widget is None:
            continue
        try:
            apply(widget)
        except RuntimeError:
            # Underlying C++ object already deleted.
            continue
        live.append((ref, apply))
    _bindings[:] = live


def clear_bindings():
    """Drop every registration."""
    _bindings.clear()


# ------------------------------------------------------------------ convenience

def text(widget, key, **kwargs):
    """Set a widget's text from *key* and keep it in sync with the language."""
    widget.setText(tr(key, **kwargs))
    return on_retranslate(widget, lambda w, k=key, a=dict(kwargs): w.setText(tr(k, **a)))


def group_title(widget, key, **kwargs):
    """Set a ``QGroupBox`` title from *key* and keep it in sync."""
    widget.setTitle(tr(key, **kwargs))
    return on_retranslate(
        widget, lambda w, k=key, a=dict(kwargs): w.setTitle(tr(k, **a))
    )


def tip(widget, key, **kwargs):
    """Set a widget's tooltip from *key* and keep it in sync."""
    widget.setToolTip(tr(key, **kwargs))
    return on_retranslate(
        widget, lambda w, k=key, a=dict(kwargs): w.setToolTip(tr(k, **a))
    )


def title(widget, key, **kwargs):
    """Set a window title from *key* and keep it in sync."""
    widget.setWindowTitle(tr(key, **kwargs))
    return on_retranslate(
        widget, lambda w, k=key, a=dict(kwargs): w.setWindowTitle(tr(k, **a))
    )


def fill_combo(combo, entries):
    """Replace a combo box's items with translatable ``(data, key, fmt)`` entries.

    Each entry is ``(data, key)`` or ``(data, key, format_kwargs)``.  The
    user data always keeps the language independent value, so reading the
    current selection never depends on the visible text.
    """
    items = []
    for entry in entries:
        if len(entry) == 2:
            data, key = entry
            fmt = {}
        else:
            data, key, fmt = entry
        items.append((data, key, dict(fmt)))
    combo.clear()
    for data, key, fmt in items:
        combo.addItem(tr(key, **fmt), data)

    def apply(widget, items=items):
        for index, (data, key, fmt) in enumerate(items):
            if index < widget.count():
                widget.setItemText(index, tr(key, **fmt))

    return on_retranslate(combo, apply)
