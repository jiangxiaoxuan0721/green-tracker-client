#!/usr/bin/env python3
"""
Green Tracker 设备端 MQTT 客户端。

功能：
  1. 使用预注册身份认证连接云端 Broker
  2. 定期上报心跳/在线状态
  3. 监听并执行云端下发的命令，返回响应
  4. 断线时发送遗嘱消息 (LWT) 通知云端

配置来源：项目根目录 .env 文件（MQTT_DEVICE_ID / MQTT_DEVICE_SECRET / MQTT_BROKER_HOST / MQTT_BROKER_PORT）

Topic 格式（与云端 Server 保持一致）：
  - 状态上报:   green-tracker/device/{device_id}/status
  - 命令下发:   green-tracker/device/{device_id}/command
  - 命令响应:   green-tracker/device/{device_id}/response
  - 遗嘱消息:   green-tracker/device/{device_id}/lwt
"""

import json
import logging
import os
import signal
import socket
import time
from datetime import datetime, timezone
from pathlib import Path
from threading import Event
from typing import Any, Optional

try:
    import paho.mqtt.client as mqtt
except ImportError:
    raise ImportError("请安装 paho-mqtt: pip install paho-mqtt")

# 同模块导入
from .commands import CommandHandler
from .topics import (
    TOPIC_PREFIX,
    status_topic as _status_topic,
    response_topic as _response_topic,
    command_topic as _command_topic,
    lwt_topic as _lwt_topic,
    all_device_status_topic as _all_device_status_topic,
    all_device_lwt_topic as _all_device_lwt_topic,
)

# ============================================================
# 日志
# ============================================================
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s - %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger("mqtt-client")

# ============================================================
# 配置加载（从 .env 文件）
# ============================================================

def _load_env():
    """从项目根目录 .env 加载环境变量。"""
    try:
        from dotenv import dotenv_values
    except ImportError:
        pass  # dotenv 可选

    root = Path(__file__).resolve().parent.parent
    env_file = root / ".env"
    if not env_file.exists():
        # 向上查找
        for _ in range(2):
            root = root.parent
            env_file = root / ".env"
            if env_file.exists():
                break

    if env_file.exists():
        try:
            from dotenv import dotenv_values

            cfg = dict(dotenv_values(env_file))
            for k, v in cfg.items():
                if k not in os.environ:  # 已设的环境变量优先级更高
                    os.environ[k] = v
            logger.info(f"已加载环境变量: {env_file}")
        except Exception:
            pass


_load_env()

# 配置常量
DEVICE_ID: str = os.getenv("MQTT_DEVICE_ID", "")
DEVICE_SECRET: str = os.getenv("MQTT_DEVICE_SECRET", "")
BROKER_HOST: str = os.getenv("MQTT_BROKER_HOST", "green-tracker.cn")
BROKER_PORT: int = int(os.getenv("MQTT_BROKER_PORT", "1883"))
STATUS_INTERVAL: int = int(os.getenv("MQTT_STATUS_INTERVAL", "30"))


def _get_local_ip() -> str:
    """获取本机公网/局域网 IP。"""
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except Exception:
        return "127.0.0.1"


# ============================================================
# 设备 MQTT 客户端
# ============================================================

class DeviceMQTTClient:
    """设备端 MQTT 客户端：连接 Broker、状态上报、命令接收与响应。"""

    def __init__(
        self,
        device_id: str = "",
        device_secret: str = "",
        broker_host: str = "",
        broker_port: int = 0,
        status_interval: int = 30,
    ):
        self.device_id = device_id or DEVICE_ID
        self.device_secret = device_secret or DEVICE_SECRET
        self.broker_host = broker_host or BROKER_HOST
        self.broker_port = broker_port or BROKER_PORT
        self.status_interval = status_interval or STATUS_INTERVAL

        # 校验必填项
        if not self.device_id:
            raise ValueError("缺少设备 ID，请在 .env 中设置 MQTT_DEVICE_ID")
        if not self.device_secret:
            raise ValueError("缺少设备密钥，请在 .env 中设置 MQTT_DEVICE_SECRET")

        # 动态 client_id（避免重连 session 冲突）
        self.client_id = f"{self.device_id}_client_{int(time.time())}"

        # 创建 paho-mqtt 客户端
        self._client = mqtt.Client(
            client_id=self.client_id,
            protocol=mqtt.MQTTv311,
            callback_api_version=mqtt.CallbackAPIVersion.VERSION2,
        )
        self._client.username_pw_set(self.device_id, self.device_secret)

        # 遗嘱消息 — 异常断连时 Broker 自动发布
        will_payload = json.dumps({
            "device_id": self.device_id,
            "status": "offline",
            "reason": "unexpected_disconnect",
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "client_id": self.client_id,
        })
        self._client.will_set(
            topic=_lwt_topic(self.device_id),
            payload=will_payload,
            qos=1,
            retain=False,  # 注意：status 不用 retain，否则会被 LWT 覆盖
        )
        logger.info(f"Will Message 已设置: {_lwt_topic(self.device_id)} -> 'offline'")

        # 回调绑定
        self._client.on_connect = self._on_connect
        self._client.on_message = self._on_message
        self._client.on_disconnect = self._on_disconnect

        # 状态
        self._connected: bool = False
        self._running: bool = False
        self._stop_event: Event = Event()

    # -----------------------------------------------------------------
    # 回调
    # -----------------------------------------------------------------

    def _on_connect(
        self,
        client: mqtt.Client,
        userdata: Any,
        flags: dict,
        rc: mqtt.ReasonCode,
        properties=None,
    ):
        """连接成功回调。"""
        if rc == 0:
            self._connected = True
            logger.info(
                f"已连接 Broker: {self.broker_host}:{self.broker_port} "
                f"(client_id={self.client_id})"
            )

            # 订阅命令下发主题（仅本机）
            cmd_tp = _command_topic(self.device_id)
            client.subscribe(cmd_tp, qos=1)
            logger.info(f"已订阅命令主题: {cmd_tp}")

            # 订阅所有设备状态上报 topic（用于感知其他设备在线）
            status_wildcard = _all_device_status_topic()
            client.subscribe(status_wildcard, qos=1)
            logger.info(f"已订阅全局状态主题: {status_wildcard}")

            # 订阅所有设备 LWT 遗嘱消息（用于感知其他设备离线）
            lwt_wildcard = _all_device_lwt_topic()
            client.subscribe(lwt_wildcard, qos=1)
            logger.info(f"已订阅全局 LWT 主题: {lwt_wildcard}")

            # 立即上报一次上线状态
            self._report_status("online")
            error_msg = f"连接失败, rc={rc}"
            logger.error(error_msg)
            if hasattr(rc, "value") and rc.value == 4:
                logger.error("用户名或密钥错误! 请检查 MQTT_DEVICE_ID 和 MQTT_DEVICE_SECRET")

    def _on_disconnect(
        self,
        client: mqtt.Client,
        userdata: Any,
        flags: Any,
        rc: mqtt.ReasonCode,
        properties=None,
    ):
        """断连回调。"""
        self._connected = False
        if rc != 0:
            logger.warning(f"意外断开 (rc={rc})，将自动重连...")

    def _on_message(self, client: mqtt.Client, userdata: Any, msg: mqtt.MQTTMessage):
        """收到消息回调（命令下发 / 其他设备状态 / LWT 遗嘱）。"""
        try:
            payload = json.loads(msg.payload.decode("utf-8"))
            topic = msg.topic

            # --- 本机命令下发 ---
            if "command" in payload:
                self._handle_command(payload)
                return

            # --- 其他设备状态上报 (green-tracker/+/device/{device_id}/status) ---
            if topic.endswith("/status"):
                device_id = self._extract_device_id_from_topic(topic, "/status")
                if device_id and device_id != self.device_id:
                    self._on_peer_status(device_id, payload)
                    return

            # --- 其他设备 LWT 离线消息 (green-tracker/+/device/{device_id}/lwt) ---
            if topic.endswith("/lwt"):
                device_id = self._extract_device_id_from_topic(topic, "/lwt")
                if device_id and device_id != self.device_id:
                    self._on_peer_lwt(device_id, payload)
                    return

            logger.debug(f"收到消息: topic={topic}, payload={payload}")
        except json.JSONDecodeError as e:
            logger.error(f"JSON 解析失败: {e}, raw={msg.payload[:200]}")
        except Exception as e:
            logger.error(f"消息处理异常: {e}", exc_info=True)

    @staticmethod
    def _extract_device_id_from_topic(topic: str, suffix: str) -> Optional[str]:
        """从 topic 中提取 device_id。
        例: 'green-tracker/device/abc123/status' → 'abc123'
        """
        prefix = f"{TOPIC_PREFIX}/device/"
        if not topic.startswith(prefix):
            return None
        rest = topic[len(prefix):]  # 'abc123/status'
        if not rest.endswith(suffix):
            return None
        return rest[:-len(suffix)] or None

    # -----------------------------------------------------------------
    # 其他设备状态感知
    # -----------------------------------------------------------------

    def _on_peer_status(self, device_id: str, payload: dict):
        """处理其他设备的状态上报消息。"""
        status = payload.get("status", "?")
        ip = payload.get("ip", device_id)
        logger.info(f"[设备状态] device_id={device_id} ip={ip} status={status}")
        # 通过回调钩子通知外部（由 manager.py 的 patch 注入信号发射）
        if hasattr(self, '_peer_status_callback'):
            try:
                self._peer_status_callback(device_id, ip, payload)
            except Exception:
                pass

    def _on_peer_lwt(self, device_id: str, payload: dict):
        """处理其他设备的 LWT 遗嘱（离线）消息。"""
        logger.info(f"[设备离线] device_id={device_id} (LWT 遗嘱)")
        if hasattr(self, '_peer_offline_callback'):
            try:
                self._peer_offline_callback(device_id)
            except Exception:
                pass

    # -----------------------------------------------------------------
    # 命令处理
    # -----------------------------------------------------------------

    def _handle_command(self, command_msg: dict):
        """解析并执行云端下发的命令，发送响应。"""
        command_id = command_msg.get("command_id", "unknown")
        command = command_msg.get("command", "")
        params = command_msg.get("params", {})

        logger.info(f"执行命令: {command} (id={command_id})")

        # 执行命令
        result = CommandHandler.execute(command, params)

        # 构造响应
        response = {
            "command_id": command_id,
            "command": command,
            "device_id": self.device_id,
            "success": result.get("success", False),
            "result": result.get("result"),
            "error": result.get("error"),
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }

        # 发送响应
        resp_topic = _response_topic(self.device_id)
        self._client.publish(resp_topic, json.dumps(response), qos=1)
        icon = "+" if result.get("success") else "-"
        logger.info(f"{icon} 命令响应已发送: {command} -> success={result.get('success')}")

    # -----------------------------------------------------------------
    # 状态上报
    # -----------------------------------------------------------------

    def _report_status(self, status: str) -> None:
        """向云端上报设备在线/离线状态。"""
        message = {
            "device_id": self.device_id,
            "status": status,
            "ip": _get_local_ip(),
            "client_id": self.client_id,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "metadata": {
                "version": "1.0.0",
                "protocol_version": "MQTTv311",
            },
        }

        tp = _status_topic(self.device_id)
        pub_result = self._client.publish(tp, json.dumps(message), qos=1)
        if pub_result.rc == mqtt.MQTT_ERR_SUCCESS:
            logger.info(f"状态已上报: {status} -> {tp}")
        else:
            logger.error(f"状态上报失败: rc={pub_result.rc}, topic={tp}")

    # -----------------------------------------------------------------
    # 生命周期
    # -----------------------------------------------------------------

    def start(self) -> None:
        """启动客户端：连接 Broker → 订阅 → 心跳循环。"""
        if self._running:
            logger.warning("客户端已在运行中")
            return

        self._running = True
        self._stop_event.clear()
        self._connected = False

        logger.info("=" * 50)
        logger.info(f"  设备 MQTT 客户端启动: {self.device_id}")
        logger.info(f"  Broker: {self.broker_host}:{self.broker_port}")
        logger.info(f"  心跳间隔: {self.status_interval}s")
        logger.info(f"  Status Topic: {_status_topic(self.device_id)}")
        logger.info(f"  Command Topic: {_command_topic(self.device_id)}")
        logger.info("=" * 50)

        # 自动重连策略
        self._client.reconnect_delay_set(min_delay=1, max_delay=60)

        # 连接 Broker（失败时 paho 会自动重连）
        try:
            self._client.connect(self.broker_host, self.broker_port, keepalive=60)
        except Exception as e:
            logger.error(f"初始连接失败（paho 将自动重试）: {e}")

        # 启动后台消息循环
        self._client.loop_start()

        # 注册信号（仅在主线程中有效，QThread 中跳过）
        import threading
        if threading.current_thread() is threading.main_thread():
            signal.signal(signal.SIGINT, lambda s, f: self.stop())
            signal.signal(signal.SIGTERM, lambda s, f: self.stop())

        # 主循环：定期心跳
        logger.info("设备运行中...")
        while self._running and not self._stop_event.is_set():
            self._stop_event.wait(timeout=self.status_interval)
            if self._running and self._connected and not self._stop_event.is_set():
                self._report_status("online")
            elif self._running and not self._connected and not self._stop_event.is_set():
                logger.warning("未连接，跳过本次心跳...")

    def stop(self) -> None:
        """优雅停止：上报离线 → 断开连接。"""
        logger.info("\n正在关闭 MQTT 客户端...")
        self._running = False
        self._stop_event.set()

        if self._connected:
            self._report_status("offline")
            time.sleep(0.5)  # 等待离线消息发送完成

        self._client.loop_stop()
        self._client.disconnect()
        logger.info(f"Mqtt 客户端已关闭: {self.device_id}")

    @property
    def connected(self) -> bool:
        """当前是否与 Broker 连接。"""
        return self._connected

    @property
    def running(self) -> bool:
        """当前是否在运行。"""
        return self._running


# ============================================================
# 工厂函数 & 全局实例管理
# ============================================================

_global_client: Optional[DeviceMQTTClient] = None


def get_mqtt_client() -> Optional[DeviceMQTTClient]:
    """获取全局 MQTT 客户端实例（如已创建）。"""
    return _global_client


def create_mqtt_client(
    device_id: str = "",
    device_secret: str = "",
    broker_host: str = "",
    broker_port: int = 0,
    status_interval: int = 30,
) -> DeviceMQTTClient:
    """
    工厂函数：创建并返回 DeviceMQTTClient。

    同时缓存为全局实例，可通过 get_mqtt_client() 获取。
    """
    global _global_client
    _global_client = DeviceMQTTClient(
        device_id=device_id,
        device_secret=device_secret,
        broker_host=broker_host,
        broker_port=broker_port,
        status_interval=status_interval,
    )
    return _global_client


# ============================================================
# 入口（支持直接 python -m mqtt 或作为脚本运行）
# ============================================================

def main():
    """独立运行入口。"""
    global _global_client

    print("""
╔════════════════════════════════════════╗
║     Green Tracker MQTT 客户端           ║
╚════════════════════════════════════════╝
""")

    client = create_mqtt_client()
    client.start()


if __name__ == "__main__":
    main()
