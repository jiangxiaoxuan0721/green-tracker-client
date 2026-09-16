"""mqtt.client — 设备端 MQTT 客户端测试（消息路由 / 命令响应 / 状态 / 宣告）。

不会建立真实连接：把内部 ``_client`` 换成假实现来捕获 publish / subscribe。
项目根目录可能存在真实 ``.env``，因此所有用例都显式传入凭据并使用 monkeypatch。
"""
import importlib
import json
from datetime import datetime

import pytest

from _util import make_msg, make_raw_msg

client_mod = importlib.import_module("mqtt.client")
DeviceMQTTClient = client_mod.DeviceMQTTClient


class FakePublishResult:
    def __init__(self, rc=0):
        self.rc = rc


class FakePaho:
    """替代 paho.mqtt.client.Client 的最小假实现。"""

    def __init__(self, rc=0):
        self.published = []
        self.subscribed = []
        self._rc = rc

    def publish(self, topic, payload=None, qos=0, retain=False):
        self.published.append({
            "topic": topic, "payload": payload, "qos": qos, "retain": retain,
        })
        return FakePublishResult(self._rc)

    def subscribe(self, topic, qos=0):
        self.subscribed.append((topic, qos))
        return (0, 1)

    # --- 断言辅助 ---
    def topics(self):
        return [p["topic"] for p in self.published]

    def last_payload(self):
        return json.loads(self.published[-1]["payload"])


@pytest.fixture
def client():
    """已注入假 paho 客户端的 DeviceMQTTClient。"""
    c = DeviceMQTTClient(
        device_id="dev-1", device_secret="secret",
        broker_host="broker.test", broker_port=1883, status_interval=1,
    )
    c._client = FakePaho()
    return c


# ============================================================
# 构造与配置校验
# ============================================================

class TestInit:
    def test_missing_device_id_raises(self, monkeypatch):
        monkeypatch.setattr(client_mod, "DEVICE_ID", "")
        with pytest.raises(ValueError, match="MQTT_DEVICE_ID"):
            DeviceMQTTClient(device_id="", device_secret="s")

    def test_missing_secret_raises(self, monkeypatch):
        monkeypatch.setattr(client_mod, "DEVICE_ID", "")
        monkeypatch.setattr(client_mod, "DEVICE_SECRET", "")
        with pytest.raises(ValueError, match="MQTT_DEVICE_SECRET"):
            DeviceMQTTClient(device_id="d", device_secret="")

    def test_client_id_is_unique_per_device_and_time(self):
        c = DeviceMQTTClient(device_id="dev-77", device_secret="s")
        assert c.client_id.startswith("dev-77_client_")
        assert c.client_id.rsplit("_", 1)[-1].isdigit()

    def test_initial_state_is_disconnected_and_stopped(self, client):
        assert client.connected is False
        assert client.running is False


# ============================================================
# topic → device_id 解析
# ============================================================

class TestExtractDeviceId:
    @pytest.mark.parametrize("topic, suffix, expected", [
        ("green-tracker/device/abc123/status", "/status", "abc123"),
        ("green-tracker/device/abc123/lwt", "/lwt", "abc123"),
        ("green-tracker/device//status", "/status", None),          # 空 id
        ("other-prefix/device/abc/status", "/status", None),        # 前缀不符
        ("green-tracker/device/abc/command", "/status", None),      # 后缀不符
        ("green-tracker/device", "/status", None),                  # 层级不足
    ])
    def test_extract(self, topic, suffix, expected):
        assert DeviceMQTTClient._extract_device_id_from_topic(topic, suffix) == expected


# ============================================================
# 命令处理 → 响应
# ============================================================

class TestHandleCommand:
    def test_success_response_goes_to_response_topic(self, client):
        client._handle_command({"command_id": "c1", "command": "ping", "params": {}})

        pub = client._client.published[-1]
        assert pub["topic"] == "green-tracker/device/dev-1/response"
        assert pub["qos"] == 1

        payload = client._client.last_payload()
        assert payload["command_id"] == "c1"
        assert payload["command"] == "ping"
        assert payload["device_id"] == "dev-1"
        assert payload["success"] is True
        assert payload["result"]["pong"] is True
        assert payload["error"] is None
        assert datetime.fromisoformat(payload["timestamp"]).tzinfo is not None

    def test_unknown_command_reports_failure(self, client):
        client._handle_command({"command_id": "c2", "command": "nope"})

        payload = client._client.last_payload()
        assert payload["success"] is False
        assert payload["result"] is None
        assert "未知命令" in payload["error"]

    def test_missing_command_id_defaults_to_unknown(self, client):
        client._handle_command({"command": "ping"})
        assert client._client.last_payload()["command_id"] == "unknown"

    def test_params_are_forwarded_to_handler(self, client):
        client._handle_command(
            {"command_id": "c3", "command": "reboot", "params": {"delay": 42}})
        assert client._client.last_payload()["result"]["delay"] == 42


# ============================================================
# 消息路由
# ============================================================

class TestOnMessage:
    def test_command_message_triggers_response(self, client):
        msg = make_msg("green-tracker/device/dev-1/command",
                       {"command_id": "x", "command": "ping"})
        client._on_message(client._client, None, msg)
        assert client._client.last_payload()["command_id"] == "x"

    def test_peer_status_invokes_callback(self, client):
        seen = {}
        client._peer_status_callback = lambda device_id, ip, payload: seen.update(
            device_id=device_id, ip=ip, payload=payload)

        payload = {"device_id": "peer-1", "status": "online", "ip": "10.0.0.7"}
        client._on_message(client._client, None,
                           make_msg("green-tracker/device/peer-1/status", payload))

        assert seen["device_id"] == "peer-1"
        assert seen["ip"] == "10.0.0.7"
        assert seen["payload"] == payload

    def test_peer_status_ip_falls_back_to_device_id(self, client):
        seen = {}
        client._peer_status_callback = lambda d, ip, p: seen.update(ip=ip)
        client._on_message(client._client, None,
                           make_msg("green-tracker/device/peer-2/status",
                                    {"status": "online"}))
        assert seen["ip"] == "peer-2"

    def test_own_status_is_ignored(self, client):
        calls = []
        client._peer_status_callback = lambda *a: calls.append(a)
        client._on_message(client._client, None,
                           make_msg("green-tracker/device/dev-1/status",
                                    {"status": "online"}))
        assert calls == []

    def test_peer_lwt_invokes_offline_callback(self, client):
        seen = []
        client._peer_offline_callback = seen.append
        client._on_message(client._client, None,
                           make_msg("green-tracker/device/peer-3/lwt",
                                    {"status": "offline"}))
        assert seen == ["peer-3"]

    def test_own_lwt_is_ignored(self, client):
        seen = []
        client._peer_offline_callback = seen.append
        client._on_message(client._client, None,
                           make_msg("green-tracker/device/dev-1/lwt",
                                    {"status": "offline"}))
        assert seen == []

    def test_peer_callback_exception_is_swallowed(self, client):
        def boom(*_args):
            raise RuntimeError("callback 内部异常")

        client._peer_status_callback = boom
        client._on_message(client._client, None,
                           make_msg("green-tracker/device/peer-4/status",
                                    {"status": "online"}))
        # 到这一步即说明异常未向外抛出

    def test_invalid_json_is_ignored_without_publishing(self, client):
        client._on_message(client._client, None,
                           make_raw_msg("green-tracker/device/peer/status", b"{not json"))
        assert client._client.published == []


# ============================================================
# 状态上报
# ============================================================

class TestReportStatus:
    def test_payload_and_topic(self, client):
        client._report_status("online")

        pub = client._client.published[-1]
        assert pub["topic"] == "green-tracker/device/dev-1/status"
        assert pub["qos"] == 1

        payload = client._client.last_payload()
        assert payload["device_id"] == "dev-1"
        assert payload["status"] == "online"
        assert payload["client_id"] == client.client_id
        assert payload["metadata"]["version"] == "1.0.0"
        assert payload["metadata"]["protocol_version"] == "MQTTv311"
        assert payload["ip"]
        assert datetime.fromisoformat(payload["timestamp"]).tzinfo is not None

    def test_offline_status(self, client):
        client._report_status("offline")
        assert client._client.last_payload()["status"] == "offline"

    def test_publish_failure_is_logged_not_raised(self, client):
        client._client._rc = 4
        client._report_status("online")
        assert client._client.published[-1]["topic"].endswith("/status")


# ============================================================
# Topic Discovery 宣告
# ============================================================

class TestPublishAnnounce:
    def test_announce_payload_topics_and_retain(self, client):
        client._publish_announce(client._client)

        pub = client._client.published[-1]
        assert pub["topic"] == "green-tracker/device/dev-1/announce"
        assert pub["retain"] is True
        assert pub["qos"] == 1

        payload = client._client.last_payload()
        assert payload["protocol_version"] == "1.0"
        assert payload["device_id"] == "dev-1"
        assert payload["topics"] == {
            "status": "green-tracker/device/dev-1/status",
            "response": "green-tracker/device/dev-1/response",
            "command": "green-tracker/device/dev-1/command",
        }
        assert payload["lwt_topic"] == "green-tracker/device/dev-1/lwt"


# ============================================================
# 连接 / 断连回调
# ============================================================

class TestOnConnect:
    def test_successful_connect_subscribes_and_announces(self, client):
        fake = client._client
        client._on_connect(fake, None, {}, 0)

        assert client.connected is True

        subscribed = [topic for topic, _ in fake.subscribed]
        assert "green-tracker/device/dev-1/command" in subscribed
        assert "green-tracker/device/+/status" in subscribed
        assert "green-tracker/device/+/lwt" in subscribed

        topics = fake.topics()
        assert "green-tracker/device/dev-1/status" in topics       # 上线状态
        assert "green-tracker/device/dev-1/announce" in topics     # 话题宣告

    def test_failed_connect_stays_disconnected(self, client):
        fake = client._client
        client._on_connect(fake, None, {}, 4)

        assert client.connected is False
        assert fake.published == []
        assert fake.subscribed == []


class TestOnDisconnect:
    def test_marks_disconnected(self, client):
        client._connected = True
        client._on_disconnect(client._client, None, None, 0)
        assert client.connected is False


# ============================================================
# 工厂与全局实例
# ============================================================

class TestFactory:
    def test_get_returns_none_when_never_created(self, monkeypatch):
        monkeypatch.setattr(client_mod, "_global_client", None)
        assert client_mod.get_mqtt_client() is None

    def test_create_caches_global_instance(self, monkeypatch):
        monkeypatch.setattr(client_mod, "_global_client", None)
        created = client_mod.create_mqtt_client(device_id="dev-f", device_secret="s")
        assert client_mod.get_mqtt_client() is created
