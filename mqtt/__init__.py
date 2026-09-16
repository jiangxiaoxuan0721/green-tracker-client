# Green Tracker MQTT 通信模块
#
# 模块说明：
#   mqtt.client       — 设备端 MQTT 客户端（心跳上报、指令接收）
#   mqtt.manager      — 服务管理器（QThread 封装 + Qt 信号事件总线，推荐 UI 使用）
#   mqtt.commands     — 命令处理器注册表与内置命令
#   mqtt.terminal     — PTY 真终端（常驻 shell，供 execute_shell 使用）
#   mqtt.topics       — Topic 定义常量

from .client import DeviceMQTTClient, create_mqtt_client, get_mqtt_client
from .manager import MQTTService, MQTTSignals
from .commands import CommandHandler
from . import terminal
from .terminal import Terminal, get_terminal
from .topics import (
    TOPIC_PREFIX,
    status_topic,
    response_topic,
    command_topic,
    lwt_topic,
    announce_topic,
    all_device_status_topic,
    all_device_lwt_topic,
    all_announce_topic,
)

__all__ = [
    # 核心
    "DeviceMQTTClient",
    "create_mqtt_client",
    "get_mqtt_client",
    # 服务管理（UI 集成首选）
    "MQTTService",
    "MQTTSignals",
    # 命令 & Topic
    "CommandHandler",
    "TOPIC_PREFIX",
    "status_topic",
    "response_topic",
    "command_topic",
    "lwt_topic",
    "announce_topic",
    # 通配订阅（供云端订阅者使用）
    "all_device_status_topic",
    "all_device_lwt_topic",
    "all_announce_topic",
]
