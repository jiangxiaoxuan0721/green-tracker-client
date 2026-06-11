"""
命令处理器注册表与内置命令。

使用装饰器注册命令处理函数，支持动态扩展。
"""

import json
import logging
import platform
import socket
import time
from datetime import datetime, timezone
from typing import Any, Callable, Dict, Optional


logger = logging.getLogger("mqtt-commands")


class CommandHandler:
    """命令处理器：管理命令名称到处理函数的映射。"""

    _registry: Dict[str, Callable[[dict], dict]] = {}

    @classmethod
    def register(cls, command_name: str) -> Callable:
        """装饰器：将函数注册为指定命令的处理器。"""

        def decorator(func: Callable[[dict], dict]) -> Callable:
            cls._registry[command_name] = func
            logger.debug(f"已注册命令: {command_name}")
            return func

        return decorator

    @classmethod
    def execute(cls, command: str, params: Optional[dict] = None) -> dict:
        """
        执行指定命令并返回结果字典。

        Returns:
            {"success": True, "result": ...} 或 {"success": False, "error": ...}
        """
        handler = cls._registry.get(command)
        if handler is None:
            return {"success": False, "error": f"未知命令: {command}"}

        try:
            result = handler(params or {})
            return {"success": True, "result": result}
        except Exception as e:
            logger.error(f"命令执行异常 [{command}]: {e}", exc_info=True)
            return {"success": False, "error": str(e)}

    @classmethod
    def list_commands(cls) -> list:
        """列出所有已注册的命令名。"""
        return list(cls._registry.keys())


# 记录启动时间（用于 uptime 计算）
_start_time = time.time()


# ============================================================
# 内置命令
# ============================================================

@CommandHandler.register("ping")
def cmd_ping(params: dict) -> dict:
    """心跳检测 — 立即响应。"""
    return {
        "pong": True,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "uptime": round(time.time() - _start_time, 2),
    }


@CommandHandler.register("get_info")
def cmd_get_info(params: dict) -> dict:
    """获取设备基本信息。"""
    # 获取本机 IP
    _ip = "127.0.0.1"
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        _ip = s.getsockname()[0]
        s.close()
    except Exception:
        pass

    return {
        "device_id": __get_device_id(),
        "hostname": socket.gethostname(),
        "platform": platform.platform(),
        "python_version": platform.python_version(),
        "local_ip": _ip,
    }


@CommandHandler.register("reboot")
def cmd_reboot(params: dict) -> dict:
    """模拟重启设备（客户端侧仅记录日志）。"""
    delay = params.get("delay", 5)
    logger.warning(f"设备将在 {delay} 秒后重启...")
    return {"message": f"设备已接收重启指令，{delay}秒后重启", "delay": delay}


@CommandHandler.register("set_config")
def cmd_set_config(params: dict) -> dict:
    """设置/更新设备配置（占位实现）。"""
    key = params.get("key")
    value = params.get("value")
    if not key or value is None:
        raise ValueError("缺少参数 key 或 value")

    logger.info(f"配置已更新: {key}={value}")
    return {"message": "配置更新成功", "key": key, "value": value}


@CommandHandler.register("get_metrics")
def cmd_get_metrics(params: dict) -> dict:
    """获取设备运行指标（模拟数据，可接入真实传感器）。"""
    import random

    return {
        "cpu_usage": round(random.uniform(10, 80), 2),
        "memory_usage": round(random.uniform(30, 70), 2),
        "temperature": round(random.uniform(35, 65), 1),
        "uptime_seconds": int(time.time() - _start_time),
    }


@CommandHandler.register("list_commands")
def cmd_list_commands(params: dict) -> dict:
    """列出设备支持的所有可用命令（供云端动态发现）。"""
    return {"commands": CommandHandler.list_commands()}


# ============================================================
# 辅助
# ============================================================

def __get_device_id() -> str:
    import os

    return os.getenv("MQTT_DEVICE_ID", "unknown_device")
