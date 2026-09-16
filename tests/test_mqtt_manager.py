"""mqtt.manager — 服务管理器 / 信号总线 / 工作线程回调注入测试。

不启动真实 QThread，也不建立网络连接：
  - ``create_mqtt_client`` 与 ``_MQTTWorker`` 都被替换为假实现
  - 信号为同线程直连（DirectConnection），无需事件循环
"""
import importlib
import json

import pytest

manager = importlib.import_module("mqtt.manager")
MQTTService = manager.MQTTService
MQTTSignals = manager.MQTTSignals


class FakeWorker:
    """替代 _MQTTWorker：记录 start/stop，不创建线程。"""

    def __init__(self, client, signals):
        self.client = client
        self.signals = signals
        self.started = False
        self.stopped = False

    def start(self):
        self.started = True

    def stop(self):
        self.stopped = True


@pytest.fixture
def service(monkeypatch):
    """每个用例拿到全新的单例，避免跨用例状态污染。"""
    monkeypatch.setattr(MQTTService, "_instance", None)
    return MQTTService.get_instance()


# ============================================================
# 单例与初始状态
# ============================================================

class TestSingleton:
    def test_get_instance_returns_same_object(self, service):
        assert MQTTService.get_instance() is service

    def test_initial_state(self, service):
        assert service.is_running is False
        assert service.is_connected is False
        assert service.client is None

    def test_signals_is_lazy_singleton(self, service, qapp):
        assert service.signals is service.signals
        assert isinstance(service.signals, MQTTSignals)

    def test_signal_bus_exposes_expected_signals(self, service, qapp):
        bus = service.signals
        for name in (
            "connected", "disconnected", "connection_failed", "status_published",
            "command_received", "response_sent", "log_message", "ready",
            "device_heartbeat", "device_offline",
        ):
            assert hasattr(bus, name), f"缺少信号: {name}"


# ============================================================
# 启停
# ============================================================

class TestStart:
    def test_start_wires_client_and_worker(self, service, monkeypatch, qapp):
        captured = {}
        fake_client = object()

        def fake_create(**kwargs):
            captured.update(kwargs)
            return fake_client

        monkeypatch.setattr(manager, "create_mqtt_client", fake_create)
        monkeypatch.setattr(manager, "_MQTTWorker", FakeWorker)

        ok = service.start(device_id="d1", device_secret="s1",
                           broker_host="h", broker_port=1883, status_interval=5)

        assert ok is True
        assert service.is_running is True
        assert service.client is fake_client
        assert captured == {
            "device_id": "d1", "device_secret": "s1",
            "broker_host": "h", "broker_port": 1883, "status_interval": 5,
        }
        assert service._worker.started is True

    def test_second_start_is_noop(self, service, monkeypatch, qapp):
        calls = []
        monkeypatch.setattr(manager, "create_mqtt_client",
                            lambda **kw: calls.append(kw) or object())
        monkeypatch.setattr(manager, "_MQTTWorker", FakeWorker)

        assert service.start(device_id="d", device_secret="s") is True
        assert service.start(device_id="d", device_secret="s") is True
        assert len(calls) == 1

    def test_start_returns_false_when_client_creation_fails(self, service, monkeypatch, qapp):
        def boom(**_kwargs):
            raise ValueError("缺少设备 ID")

        monkeypatch.setattr(manager, "create_mqtt_client", boom)

        errors = []
        service.signals.connection_failed.connect(errors.append)

        assert service.start() is False
        assert service.is_running is False
        assert errors == ["缺少设备 ID"]


class TestStop:
    def test_stop_clears_worker_and_client(self, service, monkeypatch, qapp):
        monkeypatch.setattr(manager, "create_mqtt_client", lambda **kw: object())
        monkeypatch.setattr(manager, "_MQTTWorker", FakeWorker)

        service.start(device_id="d", device_secret="s")
        worker = service._worker

        service.stop()

        assert worker.stopped is True
        assert service.is_running is False
        assert service.client is None
        assert service._worker is None

    def test_stop_when_idle_is_noop(self, service):
        service.stop()
        assert service.is_running is False


class TestRestart:
    def test_restart_stops_then_starts(self, service, monkeypatch, qapp):
        monkeypatch.setattr(manager, "create_mqtt_client", lambda **kw: object())
        monkeypatch.setattr(manager, "_MQTTWorker", FakeWorker)
        monkeypatch.setattr(manager.time, "sleep", lambda _seconds: None)

        service.start(device_id="d", device_secret="s")
        assert service.restart() is True
        assert service.is_running is True


# ============================================================
# 命令 API
# ============================================================

class TestCommandApi:
    def test_send_command_to_self_executes_and_emits(self, service, qapp):
        received = []
        service.signals.command_received.connect(received.append)

        result = service.send_command_to_self("ping")

        assert result["success"] is True
        assert result["result"]["pong"] is True

        assert len(received) == 1
        assert received[0]["command"] == "ping"
        assert received[0]["_source"] == "local"
        assert received[0]["command_id"].startswith("local_")

    def test_send_command_to_self_reports_unknown_command(self, service, qapp):
        assert service.send_command_to_self("no_such_cmd")["success"] is False

    def test_list_available_commands_matches_registry(self, service):
        from mqtt.commands import CommandHandler
        assert service.list_available_commands() == CommandHandler.list_commands()

    def test_register_command_handler_is_immediately_usable(self, service, monkeypatch, qapp):
        from mqtt.commands import CommandHandler
        monkeypatch.setattr(CommandHandler, "_registry", dict(CommandHandler._registry))

        service.register_command_handler("custom_thing", lambda p: {"v": p.get("x")})

        assert "custom_thing" in service.list_available_commands()
        assert service.send_command_to_self(
            "custom_thing", {"x": 7})["result"] == {"v": 7}


class TestPublishCustomMessage:
    def test_raises_without_client(self, service):
        with pytest.raises(RuntimeError, match="MQTT 未连接"):
            service.publish_custom_message("t", {"a": 1})

    def test_raises_when_disconnected(self, service):
        class DisconnectedClient:
            _connected = False
            _client = None

        service._client = DisconnectedClient()
        with pytest.raises(RuntimeError, match="MQTT 未连接"):
            service.publish_custom_message("t", {"a": 1})

    def test_publishes_json_when_connected(self, service):
        published = []

        class InnerClient:
            def publish(self, topic, payload, qos=0):
                published.append((topic, payload, qos))

        class ConnectedClient:
            _connected = True
            _client = InnerClient()

        service._client = ConnectedClient()
        service.publish_custom_message("my/topic", {"a": 1}, qos=2)

        assert published == [("my/topic", json.dumps({"a": 1}), 2)]


# ============================================================
# 工作线程回调注入
# ============================================================

class FakeDeviceClient:
    """_patch_callbacks 所需的最小客户端替身。"""

    device_id = "dev-1"
    client_id = "dev-1_client_1"
    broker_host = "h"
    broker_port = 1883

    def __init__(self):
        self._on_connect = lambda *a, **k: None
        self._on_disconnect = lambda *a, **k: None
        self._on_message = lambda *a, **k: None
        self._report_status = lambda status: None
        self._handle_command = lambda msg: None


class TestWorkerCallbackPatch:
    def test_patch_is_idempotent_and_injects_hooks(self, qapp):
        fake = FakeDeviceClient()
        signals = MQTTSignals()
        worker = manager._MQTTWorker(fake, signals)  # type: ignore[arg-type]

        worker._patch_callbacks()
        first_patch = fake._on_connect
        worker._patch_callbacks()

        assert fake._on_connect is first_patch          # 幂等
        assert callable(fake._peer_status_callback)     # 钩子已注入
        assert callable(fake._peer_offline_callback)

    def test_signals_emitted_on_client_events(self, qapp):
        fake = FakeDeviceClient()
        signals = MQTTSignals()
        worker = manager._MQTTWorker(fake, signals)  # type: ignore[arg-type]

        events = []
        connected, ready, heartbeats, offline = [], [], [], []
        signals.connected.connect(connected.append)
        signals.ready.connect(lambda: events.append("ready"))
        signals.status_published.connect(events.append)
        signals.command_received.connect(lambda msg: events.append(("cmd", msg)))
        signals.device_heartbeat.connect(lambda d, p: heartbeats.append((d, p)))
        signals.device_offline.connect(offline.append)

        worker._patch_callbacks()

        # 连接成功 → connected + ready
        fake._on_connect(fake, None, {}, 0)
        assert connected == ["h:1883"]
        assert "ready" in events

        # 状态上报 → status_published
        fake._report_status("online")
        assert events[-1]["status"] == "online"
        assert events[-1]["device_id"] == "dev-1"

        # 命令下发 → command_received
        fake._handle_command({"command": "ping"})
        assert ("cmd", {"command": "ping"}) in events

        # 其他设备心跳 / 离线
        fake._peer_status_callback("peer", "1.2.3.4", {"status": "online"})
        fake._peer_offline_callback("peer")
        assert heartbeats == [("peer", {"status": "online"})]
        assert offline == ["peer"]
