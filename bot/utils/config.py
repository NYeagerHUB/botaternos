"""
Utility: Quản lý config.json
Đọc/ghi cấu hình động không cần restart bot
"""

import json
import logging
import os
from pathlib import Path
from typing import Any

logger = logging.getLogger("bot.config")

CONFIG_PATH = Path(__file__).parent.parent / "config.json"

DEFAULT_CONFIG: dict[str, Any] = {
    "minecraft_server_ip": "play.example.com",
    "minecraft_server_port": 25565,
    "discord_minecraft_role_id": 0,
    "discord_announce_channel_id": 0,
    "reminder_time": "19:00",
    "reminder_min_players": 2,
    "aternos_username": "",
    "aternos_server_name": "",
}


def load_config() -> dict[str, Any]:
    """Đọc config.json. Nếu chưa tồn tại thì tạo mới với giá trị mặc định."""
    if not CONFIG_PATH.exists():
        save_config(DEFAULT_CONFIG)
        logger.info("Đã tạo config.json với giá trị mặc định.")
        return DEFAULT_CONFIG.copy()

    try:
        with open(CONFIG_PATH, "r", encoding="utf-8") as f:
            data = json.load(f)
        # Merge với default để đảm bảo có đủ key
        merged = {**DEFAULT_CONFIG, **data}
        return merged
    except json.JSONDecodeError as e:
        logger.error(f"config.json bị lỗi JSON: {e}. Dùng giá trị mặc định.")
        return DEFAULT_CONFIG.copy()


def save_config(config: dict[str, Any]) -> bool:
    """Ghi config vào file. Trả về True nếu thành công."""
    try:
        CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
        with open(CONFIG_PATH, "w", encoding="utf-8") as f:
            json.dump(config, f, indent=2, ensure_ascii=False)
        logger.debug("Đã lưu config.json")
        return True
    except Exception as e:
        logger.error(f"Không thể lưu config.json: {e}")
        return False


def get(key: str, default: Any = None) -> Any:
    """Lấy một giá trị từ config."""
    return load_config().get(key, default)


def set_value(key: str, value: Any) -> bool:
    """Cập nhật một giá trị trong config."""
    config = load_config()
    config[key] = value
    return save_config(config)
