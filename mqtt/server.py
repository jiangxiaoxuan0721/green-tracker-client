#!/usr/bin/env python3
"""
Green Tracker 云端 MQTT 客户端（预留模块）。

功能：
  1. 作为 MQTT Client 连接 Broker
  2. 订阅设备状态上报 / 命令响应 / 遗嘱消息
  3. 管理设备在线状态
  4. 通过 REST API 向设备下发命令

注意：本文件为云端 Server 侧实现，客户端项目仅作参考/预留。
实际部署时应在云端服务器上运行。
"""

import json
import logging
import threading
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

try:
    import paho.mqtt.client as mqtt
except ImportError:
    raise ImportError("请安装 paho-mqtt: pip install paho-mqtt")

# 同模块导入
from .topics import TOPIC_PREFIX


logger = logging.getLogger("mqtt-server")


# ============================================================
# Topic 常量（服务端用通配符）
# ============================================================
TOPIC_STATUS = f"{TOPIC_PREFIX}/device/+/status"
TOPIC_RESPONSE = f"{TOPIC_PREFIX}/device/+/response"
TOPIC_COMMAND_TEMPLATE = f"{TOPIC_PREFIX}/device/{{device_id}}/command"
TOPIC_LWT = f"{TOPIC_PREFIX}/device/+/lwt"


# ============================================================
# 设备状态管理器
# ============================================================

class DeviceManager:
    """管理所有设备的在线状态、元数据和命令追踪。"""

    def __init__(self):
        self.devices: Dict[str, dict] = {}
        self.pending_commands: Dict[str, dict] = {}
        self._lock = threading.Lock()

    def update_status(
        self,
        device_id: str,
        status: str,
        client_id: Optional[str] = None,
        ip: Optional[str] = None,
        metadata: Optional[Dict] = None,
    ):
        """更新设备状态。"""
        with self._lock:
            now = datetime.now(timezone.utc).isoformat()
            if device_id not in self.devices:
                self.devices[device_id] = {
                    "device_id": device_id,
                    "status": status,
                    "registered": False,
                    "last_seen": now,
                    "ip_address": ip,
                    "client_id": client_id,
                    "metadata": metadata or {},
                    "connect_history": [],
                }
                logger.info(f"新设备发现: {device_id}")
            else:
                dev = self.devices[device_id]
                dev["status"] = status
                dev["last_seen"] = now
                if ip:
                    dev["ip_address"] = ip
                if client_id:
                    dev["client_id"] = client_id
                if metadata:
                    dev["metadata"].update(metadata)

                entry = {
                    "time": now,
                    "event": "connected" if status == "online" else "disconnected",
                }
                dev["connect_history"].append(entry)
                if len(dev["connect_history"]) > 50:
                    dev["connect_history"] = dev["connect_history"][-50:]

            logger.info(f"设备状态更新: {device_id} -> {status}")

    def get_device(self, device_id: str) -> Optional[dict]:
        return self.devices.get(device_id)

    def get_all_devices(self) -> List[dict]:
        with self._lock:
            return list(self.devices.values())

    def get_online_count(self) -> int:
        with self._lock:
            return sum(1 for d in self.devices.values() if d["status"] == "online")

    def add_pending_command(self, command_id: str, device_id: str, command: str, payload: dict):
        with self._lock:
            self.pending_commands[command_id] = {
                "command_id": command_id,
                "device_id": device_id,
                "command": command,
                "payload": payload,
                "sent_at": datetime.now(timezone.utc).isoformat(),
                "response": None,
                "acknowledged": False,
            }

    def update_command_response(self, command_id: str, response: dict):
        with self._lock:
            if command_id in self.pending_commands:
                self.pending_commands[command_id]["response"] = response
                self.pending_commands[command_id]["acknowledged"] = True
                self.pending_commands[command_id]["responded_at"] = datetime.now(timezone.utc).isoformat()


# ============================================================
# 云端 MQTT 客户端
# ============================================================

class CloudMQTTClient:
    """云端 MQTT 客户端：订阅消息、下发命令。"""

    def __init__(
        self,
        broker_host: str = "",
        broker_port: int = 0,
        broker_username: str = "",
        broker_password: str = "",
        device_manager: DeviceManager = None,
    ):
        import time

        self.broker_host = broker_host or "localhost"
        self.broker_port = broker_port or 1883
        self.device_manager = device_manager or DeviceManager()

        self.client_id = f"cloud-server-{int(time.time())}"
        self._client = mqtt.Client(
            client_id=self.client_id,
            protocol=mqtt.MQTTv311,
            callback_api_version=mqtt.CallbackAPIVersion.VERSION2,
        )
        if broker_username and broker_password:
            self._client.username_pw_set(broker_username, broker_password)

        self._client.on_connect = self._on_connect
        self._client.on_message = self._on_message
        self._client.on_disconnect = self._on_disconnect

        self.connected: bool = False

    # -----------------------------------------------------------------
    # 回调
    # -----------------------------------------------------------------

    def _on_connect(self, client, userdata, flags, rc, properties=None):
        """连接成功回调 — 订阅所有相关 topic。"""
        if rc == 0:
            self.connected = True
            logger.info(f"Mqtt Broker 已连接 (client_id={self.client_id})")

            client.subscribe(TOPIC_STATUS, qos=1)
            logger.info(f"  已订阅: {TOPIC_STATUS}")
            client.subscribe(TOPIC_RESPONSE, qos=1)
            logger.info(f"  已订阅: {TOPIC_RESPONSE}")
            client.subscribe(TOPIC_LWT, qos=1)
            logger.info(f"  已订阅: {TOPIC_LWT}")
        else:
            logger.error(f"Mqt 连接失败! rc={rc}")

    def _on_message(self, client, userdata, msg):
        """消息到达回调：分发到对应处理器。"""
        try:
            payload = json.loads(msg.payload.decode())
            parts = msg.topic.split("/")
            if len(parts) >= 4:
                device_id = parts[2]
                msg_type = parts[3]

                if msg_type == "status":
                    self.device_manager.update_status(
                        device_id=device_id,
                        status=payload.get("status", "unknown"),
                        client_id=payload.get("client_id"),
                        ip=payload.get("ip"),
                        metadata=payload.get("metadata"),
                    )
                elif msg_type == "response":
                    cmd_id = payload.get("command_id")
                    if cmd_id:
                        self.device_manager.update_command_response(cmd_id, payload)
                        logger.info(f"收到命令响应: cmd={cmd_id}, device={device_id}")
                elif msg_type == "lwt":
                    self.device_manager.update_status(device_id=device_id, status="offline")
                    logger.warning(f"设备异常断线(遗嘱): {device_id}")
        except json.JSONDecodeError as e:
            logger.error(f"JSON 解析失败: {e}")
        except Exception as e:
            logger.error(f"处理消息异常: {e}", exc_info=True)

    def _on_disconnect(self, client, userdata, rc, properties=None):
        self.connected = False
        if rc != 0:
            logger.warning(f"MQTT 意外断开! rc={rc}")

    # -----------------------------------------------------------------
    # 命令下发
    # -----------------------------------------------------------------

    def send_command(self, device_id: str, command: str, params: Optional[Dict] = None) -> Optional[str]:
        """
        向指定设备下发命令。

        Returns:
            command_id 或 None（失败时）
        """
        import time

        if not self.connected:
            logger.error("MQTT 未连接，无法发送命令")
            return None

        device = self.device_manager.get_device(device_id)
        if not device or device.get("status") != "online":
            logger.error(f"设备不在线: {device_id}")
            return None

        command_id = f"cmd_{int(time.time() * 1000)}"
        message = {
            "command_id": command_id,
            "command": command,
            "params": params or {},
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "source": "cloud-server",
        }

        topic = TOPIC_COMMAND_TEMPLATE.format(device_id=device_id)
        result = self._client.publish(topic, json.dumps(message), qos=1)
        if result.rc == mqtt.MQTT_ERR_SUCCESS:
            self.device_manager.add_pending_command(command_id, device_id, command, message)
            logger.info(f"命令已发送: {command} -> {device_id} (id={command_id})")
            return command_id
        else:
            logger.error(f"命令发送失败: rc={result.rc}")
            return None

    # -----------------------------------------------------------------
    # 生命周期
    # -----------------------------------------------------------------

    def start(self):
        """启动 MQTT 客户端（独立线程 loop_forever）。"""
        try:
            self._client.connect(self.broker_host, self.broker_port, keepalive=60)
            self._thread = threading.Thread(target=self._loop_thread, daemon=False, name="mqtt-server-loop")
            self._thread.start()
            logger.info("Cloud MQTT 客户端已启动")
        except Exception as e:
            logger.error(f"连接 Broker 失败: {e}")
            raise

    def stop(self):
        """停止 MQTT 客户端。"""
        self._client.disconnect()
        if hasattr(self, "_thread") and self._thread.is_alive():
            self._thread.join(timeout=5)
        logger.info("Cloud MQTT 客户端已停止")

    def _loop_thread(self):
        try:
            self._client.loop_forever()
        except Exception as e:
            logger.error(f"MQTT 循环退出: {e}")


if __name__ == "__main__":
    print("这是云端 MQTT 服务端模块，不应在客户端直接运行。")
    print("请在云端服务器上部署此模块，配合 Flask/FastAPI 使用。")
