import copy
import json
import os
import sys
from pathlib import Path

def _config_dir():
    if getattr(sys, "frozen", False) or "compiled" in globals():
        onefile_dir = os.environ.get("NUITKA_ONEFILE_DIRECTORY")
        if onefile_dir:
            return Path(onefile_dir)
        original_argv0 = os.environ.get("NUITKA_ORIGINAL_ARGV0")
        if original_argv0:
            return Path(original_argv0).resolve().parent
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent.parent

CONFIG_FILE = _config_dir() / "config.json"
_DEFAULT_CONFIG_FILE = Path(__file__).resolve().parent.parent / "config.json"

_DEFAULT_CONFIG = {
    "left_keys": [
        "f", "d", "s", "a",
        "n", "b", "v", "c",
        "x", "z", "y", "t",
        "r", "e", "w", "q"
    ],
    "right_keys": [
        "j", "k", "l", "semicolon",
        "m", "comma", "period", "right shift",
        "up", "down", "u", "i",
        "o", "p", "[", "]"
    ],
    "keys": [
        "f", "d", "s", "a",
        "n", "b", "v", "c",
        "x", "z", "y", "t",
        "r", "e", "w", "q",
        "j", "k", "l", "semicolon",
        "m", "comma", "period", "right shift",
        "up", "down", "u", "i",
        "o", "p", "[", "]"
    ],
    "hotkey": "insert",
    "press_duration": 50,
    "technique": {
        "enabled": True,
        "style": "内轮",
        "single_kps": 7.3,
        "main_hand": "right",
        "follow_speed": True,
    },
    "verbose": False,
    "offset_left_key": "left",
    "offset_right_key": "right",
    "realtime_offset_enabled": True,
    "macro_end_mode": "both",
    "rhythm_hint_enabled": True,
    "rhythm_hint_speed": 100,
    "rhythm_hint_division": 4,
    "rhythm_hint_hit_effect": True,
    "falling_notes_enabled": True,
    "falling_notes_speed": 200,
    "falling_notes_division": 8,
    "falling_notes_lanes": 8,
    "rhythm_hint_width": 1372,
    "falling_notes_width": 478,
    "falling_notes_height": 681,
    "rhythm_hint_multi_fix": True,
    "disable_key_output": False,
    "suppress_bound_keys": True,
    "falling_notes_multi_fix": True,
    "falling_notes_hit_effect": True,
    "regular_offset_ms": 5.0,
    "irregular_offset_ms": 10.0,
    "font_name": "Microsoft YaHei",
    "font_size": 9,
}

try:
    with open(_DEFAULT_CONFIG_FILE, "r", encoding="utf-8") as _f:
        _loaded_default_config = json.load(_f)
    DEFAULT_CONFIG = (
        _loaded_default_config if isinstance(_loaded_default_config, dict)
        else copy.deepcopy(_DEFAULT_CONFIG)
    )
except Exception:
    DEFAULT_CONFIG = copy.deepcopy(_DEFAULT_CONFIG)

_KEY_ARRAY_FIELDS = ("left_keys", "right_keys", "keys")
_KEY_CHUNK_SIZE = 4

def _format_key_array(name, values):
    lines = []
    for start in range(0, len(values), _KEY_CHUNK_SIZE):
        chunk = values[start:start + _KEY_CHUNK_SIZE]
        lines.append("    " + ", ".join(
            json.dumps(value, ensure_ascii=False) for value in chunk
        ))
    if not lines:
        return f'  "{name}": []'
    return f'  "{name}": [\n' + ",\n".join(lines) + "\n  ]"

def _dump_config_text(config):
    data = dict(config)
    markers = {}
    for field in _KEY_ARRAY_FIELDS:
        values = data.get(field)
        if isinstance(values, list):
            marker = f"_ADOFAI_KEY_ARRAY{field}__"
            markers[marker] = (field, values)
            data[field] = marker
    text = json.dumps(data, indent=2, ensure_ascii=False)
    for marker, (field, values) in markers.items():
        old = f'  "{field}": {json.dumps(marker, ensure_ascii=False)}'
        text = text.replace(old, _format_key_array(field, values), 1)
    return text

def load_config():
    try:
        if CONFIG_FILE.exists():
            with open(CONFIG_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        return copy.deepcopy(DEFAULT_CONFIG)
    except Exception as e:
        print(f"加载配置失败: {e}")
        return copy.deepcopy(DEFAULT_CONFIG)

def save_config(config, *, left_keys, right_keys, macro_hotkey, press_duration,
                technique, verbose, offset_left_key="left", offset_right_key="right",
                realtime_offset_enabled=True, macro_end_mode="both",
                disable_key_output=False, suppress_bound_keys=True,
                rhythm_hint_enabled=False, rhythm_hint_speed=100,
                rhythm_hint_division=4, rhythm_hint_hit_effect=True,
                rhythm_hint_multi_fix=True,
                falling_notes_enabled=False, falling_notes_speed=100,
                falling_notes_division=4, falling_notes_lanes=4,
                falling_notes_hit_effect=False,
                falling_notes_multi_fix=True,
                rhythm_hint_width=900, falling_notes_width=380,
                falling_notes_height=820,
                regular_offset_ms=5.0, irregular_offset_ms=10.0,
                font_name="Microsoft YaHei", font_size=9):
    try:
        config.pop("death_key", None)
        for key in ("rhythm_hint_multi_threshold", "rhythm_hint_multi_press",
                    "rhythm_hint_multi_gap", "rhythm_hint_multi_turn",
                    "rhythm_hint_multi_gap_follow_bpm",
                    "rhythm_hint_multi_gap_beats",
                    "falling_notes_multi_threshold"):
            config.pop(key, None)
        
        config["left_keys"] = left_keys
        config["right_keys"] = right_keys
        config["keys"] = left_keys + right_keys
        config["hotkey"] = macro_hotkey
        config["press_duration"] = int(press_duration or 40)
        config["technique"] = technique
        config["verbose"] = verbose
        config["offset_left_key"] = offset_left_key
        config["offset_right_key"] = offset_right_key
        config["realtime_offset_enabled"] = bool(realtime_offset_enabled)
        config["disable_key_output"] = bool(disable_key_output)
        config["suppress_bound_keys"] = bool(suppress_bound_keys)
        config.pop("suppress_control_keys", None)
        config["macro_end_mode"] = macro_end_mode
        config["rhythm_hint_enabled"] = bool(rhythm_hint_enabled)
        config["rhythm_hint_speed"] = int(rhythm_hint_speed)
        config["rhythm_hint_division"] = int(rhythm_hint_division)
        config["rhythm_hint_hit_effect"] = bool(rhythm_hint_hit_effect)
        config["rhythm_hint_multi_fix"] = bool(rhythm_hint_multi_fix)
        config["falling_notes_enabled"] = bool(falling_notes_enabled)
        config["falling_notes_speed"] = int(falling_notes_speed)
        config["falling_notes_division"] = int(falling_notes_division)
        config["falling_notes_lanes"] = int(falling_notes_lanes)
        config["falling_notes_hit_effect"] = bool(falling_notes_hit_effect)
        config["falling_notes_multi_fix"] = bool(falling_notes_multi_fix)
        config["rhythm_hint_width"] = int(rhythm_hint_width)
        config["falling_notes_width"] = int(falling_notes_width)
        config["falling_notes_height"] = int(falling_notes_height)
        config["regular_offset_ms"] = float(regular_offset_ms)
        config["irregular_offset_ms"] = float(irregular_offset_ms)
        config["font_name"] = str(font_name)
        config["font_size"] = int(font_size)
        
        with open(CONFIG_FILE, "w", encoding="utf-8") as f:
            f.write(_dump_config_text(config) + "\n")
        return True
    except Exception as e:
        print(f"保存配置失败: {e}")
        return False

def export_config(path, config):
    try:
        with open(path, "w", encoding="utf-8") as f:
            f.write(_dump_config_text(config) + "\n")
        return True
    except Exception as e:
        print(f"导出配置失败: {e}")
        return False

def import_config(path):
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        if not isinstance(data, dict):
            print(f"导入配置失败: 文件内容不是 JSON 对象: {path}")
            return None
        return data
    except Exception as e:
        print(f"导入配置失败: {e}")
        return None