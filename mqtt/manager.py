#!/usr/bin/env python3
"""
MQTT 服务管理器。

将 DeviceMQTTClient 封装为后台线程运行，
通过独立的 MQTTSignals (QObject) 事件总线与 UI 层通信。

线程安全设计：
  - MQTTService: 纯 Python 类（无 QObject），可在任意线程调用
  - MQTTSignals: QObject，必须且仅在主线程创建/使用信号连接
  - _MQTTWorker: QThread，通过 emit() 跨线程投递事件到主线程
  - Qt 的 pyqtSignal 默认 AutoConnection 自动处理跨线程排队
"""

import json
import logging
import threading
import time
from datetime import datetime, timezone
from typing import Any, Callable, Dict, Optional

from PyQt6.QtCore import QObject, pyqtSignal, QThread

from .client import (
    DeviceMQTTClient,
    create_mqtt_client,
    get_mqtt_client,
    _get_local_ip,
)
from .commands import CommandHandler
from .topics import status_topic as _status_topic, command_topic as _command_topic, response_topic as _response_topic

logger = logging.getLogger("mqtt-manager")


# ============================================================
# 信号定义（QObject — 仅在主线程使用）
# ============================================================

class MQTTSignals(QObject):
    """
    MQTT 事件信号集合。

    所有 pyqtSignal 均支持跨线程自动排队（AutoConnection / QueuedConnection）。
    此对象必须在 GUI 主线程中创建和使用。
    """

    connected = pyqtSignal(str)          # broker 地址
    disconnected = pyqtSignal(str)       # 断开原因
    connection_failed = pyqtSignal(str)  # 错误信息
    status_published = pyqtSignal(dict)  # 状态 payload (本机上报)
    command_received = pyqtSignal(dict)  # 命令消息
    response_sent = pyqtSignal(dict)     # 响应字典
    log_message = pyqtSignal(str, str)   # (level, message)
    ready = pyqtSignal()                 # 服务就绪
    device_heartbeat = pyqtSignal(str, dict)   # (device_id, status_dict) 其他设备上线心跳
    device_offline = pyqtSignal(str)           # (device_id) 其他设备离线(LWT)


# ============================================================
# MQTT 工作线程
# ============================================================

class _MQTTWorker(QThread):
    """
    后台运行 MQTT 客户端的工作线程。

    通过 monkey-patch 拦截 client 回调，
    通过 signals.emit() 将事件投递到主线程（Qt AutoConnection 自动排队）。
    """

    def __init__(self, client: DeviceMQTTClient, signals: MQTTSignals):
        super().__init__()
        self._client = client
        self._s = signals
        self._patched = False

    def run(self):
        """启动 MQTT 客户端（阻塞在心跳循环中）。"""
        self._patch_callbacks()
        try:
            self._client.start()
        except Exception as e:
            logger.error(f"MQTT 工作线程异常退出: {e}")
            try:
                self._s.connection_failed.emit(str(e))
            except RuntimeError:
                logger.error(f"连接失败（信号发射异常）: {e}")

    def stop(self):
        """请求停止 MQTT 客户端。"""
        self._client.stop()
        if self.isRunning():
            self.wait(5000)

    def _patch_callbacks(self):
        """替换 client 内部回调，注入信号发射。"""
        if self._patched:
            return
        self._patched = True

        s = self._s
        client = self._client

        orig_on_connect = client._on_connect
        orig_on_disconnect = client._on_disconnect
        orig_on_message = client._on_message
        orig_report_status = client._report_status
        orig_handle_command = client._handle_command

        def patched_on_connect(c, userdata, flags, rc, properties=None):
            orig_on_connect(c, userdata, flags, rc, properties)
            if rc == 0:
                try:
                    s.connected.emit(f"{client.broker_host}:{client.broker_port}")
                    s.ready.emit()
                except RuntimeError:
                    pass

        def patched_on_disconnect(c, userdata, flags, rc, properties=None):
            orig_on_disconnect(c, userdata, flags, rc, properties)
            if rc != 0:
                try:
                    s.disconnected.emit(f"rc={rc}")
                except RuntimeError:
                    pass

        def patched_on_message(c, userdata, msg):
            orig_on_message(c, userdata, msg)

        def patched_handle_command(command_msg: dict):
            try:
                s.command_received.emit(command_msg)
            except RuntimeError:
                pass
            orig_handle_command(command_msg)

        def patched_report_status(status: str):
            orig_report_status(status)
            snapshot = {
                "status": status,
                "device_id": client.device_id,
                "ip": _get_local_ip(),
                "client_id": client.client_id,
                "timestamp": datetime.now(timezone.utc).isoformat(),
            }
            try:
                s.status_published.emit(snapshot)
            except RuntimeError:
                pass

        # 其他设备状态回调 → 信号发射
        def _on_peer_heartbeat(device_id: str, ip: str, status_dict: dict):
            try:
                s.device_heartbeat.emit(device_id, status_dict)
            except RuntimeError:
                pass

        def _on_peer_offline(device_id: str):
            try:
                s.device_offline.emit(device_id)
            except RuntimeError:
                pass

        # 注册到 client 的回调钩子
        client._peer_status_callback = _on_peer_heartbeat
        client._peer_offline_callback = _on_peer_offline

        client._on_connect = patched_on_connect
        client._on_disconnect = patched_on_disconnect
        client._handle_command = patched_handle_command
        client._report_status = patched_report_status


# ============================================================
# MQTT 服务管理器（纯 Python 类）
# ============================================================

class MQTTService:
    """
    MQTT 服务管理器 — 单例入口（纯 Python，不继承 QObject）。

    用法：
        service = MQTTService.get_instance()
        service.signals.connected.connect(on_connected)   # 必须在主线程
        service.start()                                    # 可在任意线程
    """

    _instance: Optional["MQTTService"] = None

    def __init__(self):
        self._signals: Optional[MQTTSignals] = None
        self._client: Optional[DeviceMQTTClient] = None
        self._worker: Optional[_MQTTWorker] = None
        self._running = False

    @classmethod
    def get_instance(cls) -> "MQTTService":
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    @property
    def signals(self) -> MQTTSignals:
        """获取信号总线对象（懒初始化，首次访问时在当前线程创建 QObject）。"""
        if self._signals is None:
            self._signals = MQTTSignals()
        return self._signals

    @property
    def client(self) -> Optional[DeviceMQTTClient]:
        return self._client

    @property
    def is_running(self) -> bool:
        return self._running

    @property
    def is_connected(self) -> bool:
        if self._client:
            return self._client.connected
        return False

    def start(
        self,
        device_id: str = "",
        device_secret: str = "",
        broker_host: str = "",
        broker_port: int = 0,
        status_interval: int = 30,
    ) -> bool:
        """启动 MQTT 服务（后台线程，不阻塞）。Returns: 是否成功发起启动"""
        if self._running:
            logger.warning("MQTT 服务已在运行中")
            return True

        try:
            self._client = create_mqtt_client(
                device_id=device_id,
                device_secret=device_secret,
                broker_host=broker_host,
                broker_port=broker_port,
                status_interval=status_interval,
            )
        except Exception as e:
            logger.error(f"创建 MQTT 客户端失败: {e}")
            if self._signals is not None:
                try:
                    self._signals.connection_failed.emit(str(e))
                except RuntimeError:
                    pass
            return False

        self._worker = _MQTTWorker(self._client, self.signals)
        self._running = True
        self._worker.start()

        logger.info("MQTT 服务已启动（后台线程）")
        if self._signals is not None:
            try:
                self._signals.log_message.emit("INFO", "MQTT 服务正在启动...")
            except RuntimeError:
                pass
        return True

    def stop(self):
        """停止 MQTT 服务。"""
        if not self._running:
            return

        logger.info("正在停止 MQTT 服务...")
        self._running = False

        if self._worker:
            self._worker.stop()
            self._worker = None

        self._client = None
        if self._signals is not None:
            try:
                self._signals.log_message.emit("INFO", "MQTT 服务已停止")
            except RuntimeError:
                pass

    def restart(self) -> bool:
        """重启 MQTT 服务。"""
        self.stop()
        time.sleep(1)
        return self.start()

    # -----------------------------------------------------------------
    # 命令 API
    # -----------------------------------------------------------------

    def send_command_to_self(self, command: str, params: Optional[dict] = None) -> dict:
        """向自身发送一条本地命令（不经过 Broker），用于调试。"""
        result = CommandHandler.execute(command, params)
        if self._signals is not None:
            try:
                self._signals.command_received.emit({
                    "command": command,
                    "params": params or {},
                    "command_id": f"local_{int(time.time())}",
                    "_source": "local",
                })
            except RuntimeError:
                pass
        return result

    def list_available_commands(self) -> list:
        """列出所有已注册的可用命令。"""
        return CommandHandler.list_commands()

    def register_command_handler(self, name: str, handler: Callable):
        """动态注册自定义命令处理器。"""
        CommandHandler._registry[name] = handler
        logger.info(f"已注册自定义命令: {name}")

    def publish_custom_message(self, topic: str, payload: dict, qos: int = 1):
        """发送自定义消息到指定 Topic。"""
        if not self._client or not self._client._connected:
            raise RuntimeError("MQTT 未连接")
        self._client._client.publish(topic, json.dumps(payload), qos=qos)
