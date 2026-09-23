"""ui.mqtt_panel — 云端受控指示灯测试。

指示灯状态只来自云端签到结论，与「已连接」徽章同款样式。
"""
import pytest

from api import cloud_state as cs
from ui.mqtt_panel import CloudBadge, MqttPanel


@pytest.fixture(autouse=True)
def _isolated_state():
    state = cs.CloudState()
    cs._global_state = state
    yield state
    cs._global_state = None


class TestCloudBadge:
    def test_state_texts_and_colors(self, qapp):
        badge = CloudBadge()

        badge.set_state("syncing")
        assert "同步中" in badge.text()

        badge.set_state("unauthorized")
        assert "未授权" in badge.text()

        badge.set_state("controlled")
        assert "已受控" in badge.text()
        assert "background-color" in badge.styleSheet()

        badge.set_state("revoked")
        assert "已撤销" in badge.text()

    def test_tooltip_explains_current_state(self, qapp):
        badge = CloudBadge()

        badge.set_state("revoked", "控制权限已被撤销：密钥已禁用")

        assert "密钥已禁用" in badge.toolTip()


class TestPanelBadgeBinding:
    def test_badge_follows_cloud_state(self, qapp, _isolated_state):
        panel = MqttPanel()
        state = _isolated_state

        panel._update_cloud_badge()          # 未签到
        assert "同步中" in panel.cloud_badge.text()

        state.update_from_heartbeat({
            "registered": True,
            "capabilities": {"upload_data": True, "pull_tasks": True,
                             "receive_commands": True},
            "command_channel": "mqtt",
        })
        panel._update_cloud_badge()
        assert "已受控" in panel.cloud_badge.text()

        state.mark_revoked("密钥已禁用")
        panel._update_cloud_badge()
        assert "已撤销" in panel.cloud_badge.text()

    def test_unauthorized_when_cloud_denies_control(self, qapp, _isolated_state):
        panel = MqttPanel()

        _isolated_state.update_from_heartbeat({
            "registered": True,
            "capabilities": {"upload_data": True, "pull_tasks": True,
                             "receive_commands": False},
            "command_channel": None,
        })

        panel._update_cloud_badge()

        assert "未授权" in panel.cloud_badge.text()
