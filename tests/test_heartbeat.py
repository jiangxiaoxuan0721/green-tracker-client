"""云端签到编排测试 —— TDD。

覆盖：启动即签到、能力刷新、401/403/5xx 的差异化退避、
`revoke_control` 触发的立即重签、以及 HTTP 通道的指令轮询与回执。
"""
import threading
import time

import pytest

from api import cloud_state as cs
from api import device_commands as dc
from api import heartbeat as hb


class FakeClient:
    """记录调用并可注入异常的假云端客户端。"""

    def __init__(self, heartbeat_data=None, error=None, pending=None):
        self.heartbeat_data = heartbeat_data if heartbeat_data is not None else {
            "registered": True,
            "capabilities": {"upload_data": True, "pull_tasks": True,
                             "receive_commands": True},
            "command_channel": "mqtt",
            "poll_interval_seconds": None,
        }
        self.error = error
        self.pending = pending or []
        self.heartbeat_calls = 0
        self.pending_calls = 0
        self.results = []

    def heartbeat(self):
        self.heartbeat_calls += 1
        if self.error:
            raise self.error
        return self.heartbeat_data

    def fetch_pending(self):
        self.pending_calls += 1
        if isinstance(self.pending, Exception):
            raise self.pending
        return self.pending

    def report_result(self, command_id, status, result=None, error_message=None):
        self.results.append((command_id, status, result, error_message))


@pytest.fixture
def state():
    return cs.CloudState()


def _wait(predicate, timeout=2.0):
    deadline = time.time() + timeout
    while time.time() < deadline:
        if predicate():
            return True
        time.sleep(0.01)
    return False


# ============================================================
# 签到与能力刷新
# ============================================================

class TestBeat:
    def test_successful_beat_updates_state(self, state):
        client = FakeClient()
        svc = hb.HeartbeatService(client=client, state=state, interval=300)

        assert svc.beat_now() is True

        assert client.heartbeat_calls == 1
        assert state.can_upload() is True
        assert state.can_receive_commands() is True
        assert state.command_channel == "mqtt"

    def test_start_beats_immediately_then_stops(self, state):
        client = FakeClient()
        svc = hb.HeartbeatService(client=client, state=state, interval=300)

        svc.start()
        try:
            assert _wait(lambda: state.last_heartbeat_at is not None)
            assert client.heartbeat_calls >= 1
        finally:
            svc.stop()

        assert svc.is_running is False

    def test_trigger_immediate_rebeats_without_waiting(self, state):
        client = FakeClient()
        svc = hb.HeartbeatService(client=client, state=state, interval=300)
        svc.start()
        try:
            assert _wait(lambda: client.heartbeat_calls == 1)
            svc.trigger_immediate()
            assert _wait(lambda: client.heartbeat_calls == 2)
        finally:
            svc.stop()


# ============================================================
# 错误码差异化退避
# ============================================================

class TestBackoff:
    def test_auth_error_uses_fixed_long_backoff(self, state):
        client = FakeClient(error=dc.AuthError("401"))
        svc = hb.HeartbeatService(client=client, state=state, interval=300)

        assert svc.beat_now() is False
        assert svc.next_delay() == hb.AUTH_BACKOFF

    def test_forbidden_degrades_silently_at_normal_interval(self, state):
        client = FakeClient(error=dc.ForbiddenError("403"))
        svc = hb.HeartbeatService(client=client, state=state, interval=300)

        assert svc.beat_now() is False
        # 静默降级：不加速重试，等下次签到结果变化
        assert svc.next_delay() == 300

    def test_transient_error_backs_off_exponentially(self, state):
        client = FakeClient(error=dc.TransientError("500"))
        svc = hb.HeartbeatService(client=client, state=state, interval=300)

        delays = []
        for _ in range(5):
            svc.beat_now()
            delays.append(svc.next_delay())

        assert delays[0] == 1
        assert delays[1] == 2
        assert delays[2] == 4
        assert delays[3] == 8
        assert delays[4] == 16

    def test_transient_backoff_is_capped(self, state):
        client = FakeClient(error=dc.TransientError("500"))
        svc = hb.HeartbeatService(client=client, state=state, interval=300)

        for _ in range(12):
            svc.beat_now()

        assert svc.next_delay() == hb.TRANSIENT_MAX

    def test_success_resets_backoff(self, state):
        client = FakeClient()
        svc = hb.HeartbeatService(client=client, state=state, interval=300)
        client.error = dc.TransientError("500")
        svc.beat_now()
        assert svc.next_delay() != 300

        client.error = None
        svc.beat_now()

        assert svc.next_delay() == 300


# ============================================================
# HTTP 通道：轮询取指令 + 回执
# ============================================================

class TestPendingPoller:
    def test_http_channel_starts_poller(self, state):
        client = FakeClient(heartbeat_data={
            "registered": True,
            "capabilities": {"upload_data": True, "pull_tasks": True,
                             "receive_commands": True},
            "command_channel": "http",
            "poll_interval_seconds": 5,
        })
        svc = hb.HeartbeatService(client=client, state=state, interval=300)

        svc.beat_now()

        assert svc.is_polling() is True
        svc.stop()

    def test_mqtt_channel_does_not_poll(self, state):
        client = FakeClient()
        svc = hb.HeartbeatService(client=client, state=state, interval=300)

        svc.beat_now()

        assert svc.is_polling() is False

    def test_no_command_channel_stops_poller(self, state):
        client = FakeClient(heartbeat_data={
            "registered": True,
            "capabilities": {"upload_data": True, "pull_tasks": True,
                             "receive_commands": False},
            "command_channel": None,
        })
        svc = hb.HeartbeatService(client=client, state=state, interval=300)
        svc.beat_now()
        assert svc.is_polling() is False
        svc.stop()

    def test_pending_commands_executed_and_acked(self, state, monkeypatch):
        from mqtt.commands import CommandHandler

        CommandHandler.register("_hb_probe")(lambda params: {"ok": True})
        try:
            client = FakeClient(pending=[
                {"command_id": "c1", "command": "_hb_probe", "params": {}},
            ])
            svc = hb.HeartbeatService(client=client, state=state, interval=300)
            svc.beat_now()  # 先建立 http 通道? 直接测轮询器

            poller = hb.PendingPoller(client=client, interval=0.01)
            poller.pull_once()

            assert client.results[0][0] == "c1"
            assert client.results[0][1] == "acked"
        finally:
            CommandHandler._registry.pop("_hb_probe", None)
            svc.stop()

    def test_failed_command_reports_failed_with_error(self, state):
        from mqtt.commands import CommandHandler

        def boom(params):
            raise RuntimeError("执行炸了")

        CommandHandler.register("_hb_boom")(boom)
        try:
            client = FakeClient(pending=[
                {"command_id": "c2", "command": "_hb_boom", "params": {}},
            ])
            poller = hb.PendingPoller(client=client, interval=0.01)

            poller.pull_once()

            assert client.results[0][1] == "failed"
            assert "执行炸了" in (client.results[0][3] or "")
        finally:
            CommandHandler._registry.pop("_hb_boom", None)

    def test_poller_survives_fetch_error(self, state):
        client = FakeClient(pending=dc.TransientError("500"))
        poller = hb.PendingPoller(client=client, interval=0.01)

        poller.pull_once()  # 不应抛异常

        assert client.results == []
