import json
import os
import sys
from pathlib import Path


def _config_dir():
    if getattr(sys, "frozen", False) or "__compiled__" in globals():
        onefile_dir = os.environ.get("NUITKA_ONEFILE_DIRECTORY")
        if onefile_dir:
            return Path(onefile_dir)
        original_argv0 = os.environ.get("NUITKA_ORIGINAL_ARGV0")
        if original_argv0:
            return Path(original_argv0).resolve().parent
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent.parent


CONFIG_FILE = _config_dir() / "config.json"


def load_config():
    try:
        if CONFIG_FILE.exists():
            with open(CONFIG_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        return {}
    except Exception as e:
        print(f"加载配置失败: {e}")
        return {}


def save_config(config, *, left_keys, right_keys, macro_hotkey, press_duration,
                technique, verbose):
    try:
        config.pop("death_key", None)
        config["left_keys"] = left_keys
        config["right_keys"] = right_keys
        config["keys"] = left_keys + right_keys
        config["hotkey"] = macro_hotkey
        config["press_duration"] = int(press_duration or 40)
        config["technique"] = technique
        config["verbose"] = verbose
        with open(CONFIG_FILE, "w", encoding="utf-8") as f:
            json.dump(config, f, indent=2, ensure_ascii=False)
    except Exception as e:
        print(f"保存配置失败: {e}")


def export_config(path, config):
    try:
        with open(path, "w", encoding="utf-8") as f:
            json.dump(config, f, indent=2, ensure_ascii=False)
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
