"""全局配置 — 应用配置项的唯一来源。

约定：
  * 与 HOME 相关的路径**必须惰性解析**（用函数而非模块常量）。
    测试通过重定向 HOME 做隔离（见 tests/conftest.py），
    模块级常量会在 import 时被冻结，导致写入真实家目录。
  * 环境变量通过 .env 加载；已存在的真实环境变量优先级更高。

不在本模块管辖的范围：MQTT 连接参数由 mqtt/client.py 自行加载
（该逻辑自洽且被完整测试覆盖，改动收益低于回归风险）。
"""
from __future__ import annotations

import os
from typing import Optional

from dotenv import load_dotenv

load_dotenv()

# ============================================================
# 本地文件系统
# ============================================================
DEFAULT_DATA_DIRNAME = "green_tracker_data"


def data_root() -> str:
    """数据根目录（每次调用重新解析，兼容 HOME 重定向）。"""
    raw = os.getenv("GREEN_TRACKER_DATA_DIR") or f"~/{DEFAULT_DATA_DIRNAME}"
    return os.path.expanduser(raw)


# ============================================================
# 云端 HTTP
# ============================================================
DEFAULT_API_BASE_URL = "http://localhost:8000"


def api_base_url() -> str:
    """云端 API 基地址。总是返回非空值，避免拼出 "None/api/..." 形式的 URL。"""
    return (os.getenv("API_BASE_URL") or DEFAULT_API_BASE_URL).rstrip("/")


def secret_key() -> Optional[str]:
    """云端 API 鉴权密钥（未配置时返回 None）。"""
    return os.getenv("SECRET_KEY")


def api_timeout() -> float:
    """HTTP 请求超时（秒）。"""
    return float(os.getenv("API_TIMEOUT", "10"))


# ============================================================
# 采集
# ============================================================
def collect_interval() -> float:
    """会话采集轮询间隔（秒）。"""
    return float(os.getenv("COLLECT_INTERVAL", "1.0"))


def virtual_sensor_interval() -> float:
    """后台虚拟传感器上报间隔（秒）。"""
    return float(os.getenv("VIRTUAL_SENSOR_INTERVAL", "5.0"))
