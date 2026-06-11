# Green Tracker MQTT 通信模块
#
# 模块说明：
#   mqtt.client       — 设备端 MQTT 客户端（心跳上报、指令接收）
#   mqtt.manager      — 服务管理器（QThread 封装 + Qt 信号事件总线，推荐 UI 使用）
#   mqtt.server       — 云端 MQTT 客户端（设备监控、命令下发，预留）
#   mqtt.commands     — 命令处理器注册表与内置命令
#   mqtt.topics       — Topic 定义常量

from .client import DeviceMQTTClient, create_mqtt_client, get_mqtt_client
from .manager import MQTTService, MQTTSignals
from .commands import CommandHandler
from .topics import TOPIC_PREFIX, status_topic, response_topic, command_topic, lwt_topic

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
]
