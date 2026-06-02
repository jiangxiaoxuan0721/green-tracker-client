"""
MQTT Topic 定义常量。

Topic 格式: green-tracker/device/{device_id}/{msg_type}
与云端 Server 保持一致。
"""

import os


TOPIC_PREFIX = "green-tracker"


def _get_device_id() -> str:
    return os.getenv("MQTT_DEVICE_ID", "")


def status_topic(device_id: str = "") -> str:
    """设备状态上报 topic"""
    did = device_id or _get_device_id()
    return f"{TOPIC_PREFIX}/device/{did}/status"


def response_topic(device_id: str = "") -> str:
    """命令响应 topic"""
    did = device_id or _get_device_id()
    return f"{TOPIC_PREFIX}/device/{did}/response"


def command_topic(device_id: str = "") -> str:
    """命令下发 topic"""
    did = device_id or _get_device_id()
    return f"{TOPIC_PREFIX}/device/{did}/command"


def lwt_topic(device_id: str = "") -> str:
    """遗嘱消息 topic（异常断线检测）"""
    did = device_id or _get_device_id()
    return f"{TOPIC_PREFIX}/device/{did}/lwt"
