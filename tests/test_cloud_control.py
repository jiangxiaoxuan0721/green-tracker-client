"""云端控制门控与指令回执测试 —— TDD。

1. `revoke_control` 之后：仅保留连接相关命令（`ping`），其余一律拒绝
2. 重新签到且云端恢复控制权限后，命令自动恢复
3. MQTT 通道收到的指令除原有 response 外，补发 HTTP 回执
"""
import json

import pytest

from api import cloud_state as cs
from api import device_commands as dc
from api import heartbeat as hb
from mqtt.commands import CommandHandler
import mqtt.client as client_mod


def _heartbeat_data(receive=True, channel="mqtt"):
    return {
        "registered": True,
        "capabilities": {"upload_data": True, "pull_tasks": True,
                         "receive_commands": receive},
        "command_channel": channel,
        "poll_interval_seconds": None,
    }


@pytest.fixture(autouse=True)
def _isolated_state():
    state = cs.CloudState()
    cs._global_state = state
    yield state
    cs._global_state = None


# ============================================================
# 控制门控
# ============================================================

class TestRevokedGating:
    def test_commands_allowed_before_revoke(self, _isolated_state):
        assert CommandHandler.execute("get_metrics")["success"] is True

    def test_ping_is_still_allowed_after_revoke(self, _isolated_state):
        _isolated_state.mark_revoked("密钥已禁用")

        assert CommandHandler.execute("ping")["success"] is True

    @pytest.mark.parametrize("name,params", [
        ("reboot", {}),
        ("set_config", {"key": "k", "value": "v"}),
        ("get_metrics", {}),
        ("get_info", {}),
        ("list_commands", {}),
        ("cloud_probe", {}),
        ("execute_shell", {"command": "echo hi"}),
        ("terminal_info", {}),
    ])
    def test_control_commands_are_blocked(self, _isolated_state, name, params):
        _isolated_state.mark_revoked("密钥已禁用")

        result = CommandHandler.execute(name, params)

        assert result["success"] is False
        assert "撤销" in result["error"]

    def test_restored_after_re_signin_grants_control(self, _isolated_state):
        _isolated_state.mark_revoked("密钥已禁用")

        _isolated_state.update_from_heartbeat(_heartbeat_data(receive=True))

        assert CommandHandler.execute("get_metrics")["success"] is True

    def test_blocked_while_cloud_still_denies_control(self, _isolated_state):
        _isolated_state.mark_revoked("密钥已禁用")

        _isolated_state.update_from_heartbeat(_heartbeat_data(receive=False))

        outcome = CommandHandler.execute("get_metrics")
        assert outcome["success"] is False
        assert outcome.get("result") is None


# ============================================================
# revoke_control 系统指令
# ============================================================

class FakeService:
    def __init__(self):
        self.triggers = 0
        self.is_running = True

    def trigger_immediate(self):
        self.triggers += 1


class TestRevokeControlCommand:
    def test_registered(self):
        assert "revoke_control" in CommandHandler.list_commands()

    def test_marks_revoked_and_requests_immediate_re_signin(
            self, _isolated_state, monkeypatch):
        svc = FakeService()
        monkeypatch.setattr(hb, "get_heartbeat_service", lambda: svc)

        body = CommandHandler.execute(
            "revoke_control", {"reason": "密钥已删除"})["result"]

        assert body["revoked"] is True
        assert _isolated_state.is_revoked() is True
        assert _isolated_state.revoke_reason == "密钥已删除"
        assert svc.triggers == 1

    def test_idempotent_when_already_revoked(self, _isolated_state, monkeypatch):
        monkeypatch.setattr(hb, "get_heartbeat_service", lambda: FakeService())
        _isolated_state.mark_revoked("first")

        result = CommandHandler.execute("revoke_control", {})

        assert result["success"] is True
        assert _isolated_state.is_revoked() is True

    def test_tolerates_missing_heartbeat_service(self, _isolated_state, monkeypatch):
        monkeypatch.setattr(hb, "get_heartbeat_service", lambda: None)

        result = CommandHandler.execute("revoke_control", {})

        assert result["success"] is True
        assert _isolated_state.is_revoked() is True


# ============================================================
# MQTT 指令的 HTTP 回执
# ============================================================

class FakePublishResult:
    def __init__(self, rc=0):
        self.rc = rc


class FakePaho:
    def __init__(self):
        self.published = []

    def publish(self, topic, payload=None, qos=0, retain=False):
        self.published.append({"topic": topic, "payload": payload})
        return FakePublishResult()

    def subscribe(self, topic, qos=0):
        return (0, 1)


@pytest.fixture
def device():
    c = client_mod.DeviceMQTTClient(
        device_id="dev-1", device_secret="s",
        broker_host="broker.test", broker_port=1883, status_interval=1,
    )
    c._client = FakePaho()
    return c


class TestHttpReceipt:
    def test_success_is_acked_over_http(self, device, monkeypatch):
        captured = {}

        def fake_report(command_id, status, result=None, error_message=None):
            captured.update(command_id=command_id, status=status, result=result,
                            error_message=error_message)

        monkeypatch.setattr(dc, "report_result", fake_report)

        device._handle_command({"command_id": "c1", "command": "ping",
                                "params": {}})

        assert captured["command_id"] == "c1"
        assert captured["status"] == "acked"
        assert captured["error_message"] is None

    def test_failure_is_reported_with_error_message(self, device, monkeypatch):
        captured = {}
        monkeypatch.setattr(
            dc, "report_result",
            lambda cid, st, result=None, error_message=None: captured.update(
                status=st, error_message=error_message))

        device._handle_command({"command_id": "c2", "command": "nope",
                                "params": {}})

        assert captured["status"] == "failed"
        assert "未知命令" in (captured["error_message"] or "")

    def test_local_debug_command_is_not_reported(self, device, monkeypatch):
        calls = []
        monkeypatch.setattr(dc, "report_result",
                            lambda *a, **k: calls.append(a))

        device._handle_command({"command_id": "local_123", "command": "ping",
                                "params": {}})

        assert calls == []

    def test_mqtt_response_is_still_published(self, device, monkeypatch):
        monkeypatch.setattr(dc, "report_result", lambda *a, **k: None)

        device._handle_command({"command_id": "c3", "command": "ping",
                                "params": {}})

        topics = [p["topic"] for p in device._client.published]
        assert any(t.endswith("/response") for t in topics)
        payload = json.loads(device._client.published[-1]["payload"])
        assert payload["command_id"] == "c3"

    def test_report_failure_does_not_break_command(self, device, monkeypatch):
        def boom(*a, **k):
            raise RuntimeError("云端不可达")

        monkeypatch.setattr(dc, "report_result", boom)

        device._handle_command({"command_id": "c4", "command": "ping",
                                "params": {}})  # 不应抛出
