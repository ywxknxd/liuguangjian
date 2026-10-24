"""流光笺 主题与配置管理"""
import json
import os
import sys
from typing import Dict, Optional


def _get_data_dir() -> str:
    """返回 data 目录路径，兼容开发环境和 PyInstaller 打包。"""
    if getattr(sys, "frozen", False):
        # PyInstaller 打包后，数据目录在 exe 同级
        return os.path.join(os.path.dirname(sys.executable), "data")
    return os.path.join(os.path.dirname(__file__), "..", "data")


CONFIG_DIR = _get_data_dir()
CONFIG_PATH = os.path.join(CONFIG_DIR, "config.json")

THEMES: Dict[str, Dict] = {
    "dark": {
        "name": "深色",
        "bg": "#1a1a1a",
        "fg": "#e0e0e0",
        "frame_bg": "#2a2a2a",
        "entry_bg": "#2a2a2a",
        "entry_fg": "#e0e0e0",
        "button_bg": "#3a3a3a",
        "button_fg": "#e0e0e0",
        "tree_bg": "#2a2a2a",
        "tree_fg": "#e0e0e0",
        "select_bg": "#0078d4",
        "select_fg": "#ffffff",
        "alpha": 0.95,
    },
    "transparent": {
        "name": "白色",
        "bg": "#f0f0f0",
        "fg": "#1a1a1a",
        "frame_bg": "#ffffff",
        "entry_bg": "#ffffff",
        "entry_fg": "#1a1a1a",
        "button_bg": "#e0e0e0",
        "button_fg": "#1a1a1a",
        "tree_bg": "#ffffff",
        "tree_fg": "#1a1a1a",
        "select_bg": "#0078d4",
        "select_fg": "#ffffff",
        "alpha": 0.85,
    },
}

DEFAULT_THEME = "transparent"


def load_config() -> Dict:
    """加载配置文件，若不存在则返回默认值。"""
    os.makedirs(CONFIG_DIR, exist_ok=True)
    if not os.path.exists(CONFIG_PATH):
        return {"theme": DEFAULT_THEME}
    try:
        with open(CONFIG_PATH, "r", encoding="utf-8") as f:
            data = json.load(f)
            if isinstance(data, dict) and "theme" in data and data["theme"] in THEMES:
                return data
    except (json.JSONDecodeError, OSError):
        pass
    return {"theme": DEFAULT_THEME}


def save_config(data: Dict) -> None:
    """保存配置到文件。"""
    os.makedirs(CONFIG_DIR, exist_ok=True)
    with open(CONFIG_PATH, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def get_theme(theme_key: Optional[str] = None) -> Dict:
    """获取主题配色字典。"""
    key = theme_key or load_config().get("theme", DEFAULT_THEME)
    return THEMES.get(key, THEMES[DEFAULT_THEME])
