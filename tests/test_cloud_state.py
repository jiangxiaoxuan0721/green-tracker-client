"""云端能力状态（api/cloud_state）测试 —— TDD。

设备不解析权限含义，只认云端下发的 `capabilities`；
本状态是整个进程判断「能不能上传 / 能不能受控」的唯一事实源。

拉取采集任务不在此列 —— 它是设备作业通道的默认能力，
云端对 `active_sessions` 不做权限校验，因此本状态没有对应的开关。
"""
import threading

import pytest

from api import cloud_state as cs


@pytest.fixture(autouse=True)
def _isolated_state():
    """每个用例使用全新状态，避免单例互相污染。"""
    state = cs.CloudState()
    original = cs._global_state
    cs._global_state = state
    yield state
    cs._global_state = original


def _heartbeat(**overrides):
    data = {
        "device_id": "dev-1",
        "registered": True,
        "capabilities": {
            "upload_data": True,
            "receive_commands": True,
        },
        "command_channel": "mqtt",
        "poll_interval_seconds": None,
    }
    data.update(overrides)
    return data


class TestDefaults:
    def test_before_first_heartbeat(self, _isolated_state):
        state = _isolated_state

        # 指令通道：未拿到云端结论前不接受控制指令
        assert state.can_receive_commands() is False
        # 数据面：未同步前沿用本地旧行为（fail-open），避免云端抖动打断采集
        assert state.can_upload() is True
        assert state.is_revoked() is False
        assert state.command_channel is None

    def test_after_sync_cloud_conclusion_wins(self, _isolated_state):
        state = _isolated_state

        state.update_from_heartbeat({
            "registered": True,
            "capabilities": {"upload_data": False, "receive_commands": False},
            "command_channel": None,
        })

        assert state.synced is True
        assert state.can_upload() is False


class TestPullTasksIsDefaultCapability:
    """拉取采集任务是设备作业通道的默认能力，不是权限项。

    云端对 `active_sessions` 不再校验 `data_read`，`capabilities.pull_tasks`
    恒为 true，因此本状态不再跟踪它，也不提供对应的开关方法。
    """

    def test_state_has_no_pull_tasks_switch(self, _isolated_state):
        state = _isolated_state
        state.update_from_heartbeat(_heartbeat())

        assert "pull_tasks" not in state.snapshot()["capabilities"]
        assert not hasattr(state, "can_pull_tasks")

    def test_payload_pull_tasks_is_ignored(self, _isolated_state):
        state = _isolated_state
        state.update_from_heartbeat(_heartbeat(
            capabilities={"upload_data": True, "pull_tasks": False,
                          "receive_commands": True},
        ))

        # 即便云端给了 false，也再没有「无权拉任务」这条结论可言
        assert "pull_tasks" not in state.snapshot()["capabilities"]


class TestUpdateFromHeartbeat:
    def test_applies_capabilities_and_channel(self, _isolated_state):
        state = _isolated_state

        state.update_from_heartbeat(_heartbeat())

        assert state.registered is True
        assert state.upload_data is True
        assert state.receive_commands is True
        assert state.command_channel == "mqtt"
        assert state.can_receive_commands() is True

    def test_null_channel_means_no_command_pulling(self, _isolated_state):
        state = _isolated_state

        state.update_from_heartbeat(_heartbeat(
            command_channel=None,
            capabilities={"upload_data": True, "receive_commands": False},
        ))

        assert state.command_channel is None
        assert state.can_receive_commands() is False
        assert state.can_upload() is True

    def test_http_channel_uses_default_poll_interval(self, _isolated_state):
        state = _isolated_state

        state.update_from_heartbeat(_heartbeat(
            command_channel="http", poll_interval_seconds=None))

        assert state.poll_interval == cs.DEFAULT_POLL_INTERVAL

    def test_missing_capabilities_denies_all(self, _isolated_state):
        state = _isolated_state

        state.update_from_heartbeat(_heartbeat(capabilities=None))

        assert state.can_upload() is False
        assert state.can_receive_commands() is False


class TestRevoked:
    def test_revoked_blocks_commands_and_upload(self, _isolated_state):
        state = _isolated_state
        state.update_from_heartbeat(_heartbeat())

        state.mark_revoked("密钥已禁用")

        assert state.is_revoked() is True
        assert state.revoke_reason == "密钥已禁用"
        assert state.can_receive_commands() is False
        assert state.can_upload() is False

    def test_re_signin_with_control_restores(self, _isolated_state):
        state = _isolated_state
        state.update_from_heartbeat(_heartbeat())
        state.mark_revoked("临时撤销")

        state.update_from_heartbeat(_heartbeat())

        assert state.is_revoked() is False
        assert state.can_receive_commands() is True

    def test_re_signin_without_control_keeps_revoked(self, _isolated_state):
        state = _isolated_state
        state.update_from_heartbeat(_heartbeat())
        state.mark_revoked("密钥已禁用")

        state.update_from_heartbeat(_heartbeat(
            capabilities={"upload_data": True, "receive_commands": False},
            command_channel=None,
        ))

        assert state.is_revoked() is True
        assert state.can_receive_commands() is False


class TestSnapshotAndListeners:
    def test_snapshot_exposes_flat_view(self, _isolated_state):
        state = _isolated_state
        state.update_from_heartbeat(_heartbeat())

        snap = state.snapshot()

        assert snap["registered"] is True
        assert snap["command_channel"] == "mqtt"
        assert snap["capabilities"]["receive_commands"] is True
        assert "revoked" in snap

    def test_listener_notified_on_change(self, _isolated_state):
        state = _isolated_state
        seen = []
        state.add_listener(lambda s: seen.append(s.snapshot()["command_channel"]))

        state.update_from_heartbeat(_heartbeat(command_channel="http"))

        assert seen == ["http"]

    def test_updates_are_thread_safe(self, _isolated_state):
        state = _isolated_state

        def worker():
            for _ in range(50):
                state.update_from_heartbeat(_heartbeat())
                state.snapshot()

        threads = [threading.Thread(target=worker) for _ in range(4)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert state.can_receive_commands() is True
