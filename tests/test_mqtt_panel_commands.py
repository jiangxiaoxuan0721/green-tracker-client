"""ui.mqtt_panel — 命令列表自动刷新与结果区按宽度换行。

命令的启用状态会在运行时被改变（云端下发策略、本地策略文件改盘），
面板必须自己跟上，而不是等用户点「刷新」。
"""
import pytest
from PyQt6.QtGui import QTextOption
from PyQt6.QtWidgets import QTextEdit

from mqtt.commands import CommandHandler
from ui.mqtt_panel import MqttPanel


def _combo_items(panel) -> list:
    return [panel.combo_command.itemText(i)
            for i in range(panel.combo_command.count())]


def _list_labels(panel) -> list:
    return [panel.cmd_list.item(i).text()
            for i in range(panel.cmd_list.count())]


@pytest.fixture
def registry(monkeypatch):
    """隔离命令策略，避免污染其他用例。"""
    monkeypatch.setattr(CommandHandler, "_policy", {})
    monkeypatch.setattr(CommandHandler, "_file_cache", None)
    yield
    CommandHandler.reset_policy()


# ============================================================
# 结果区换行
# ============================================================

class TestResultViewWrapping:
    def test_wraps_at_widget_width(self, qapp):
        """结果按控件宽度换行，不再出现横向滚动条。"""
        panel = MqttPanel()
        view = panel.result_view

        assert view.lineWrapMode() == QTextEdit.LineWrapMode.WidgetWidth
        # 超长无空格行（JSON / base64）也要硬断，否则仍会溢出
        assert view.wordWrapMode() == \
            QTextOption.WrapMode.WrapAtWordBoundaryOrAnywhere

    def test_content_is_not_truncated(self, qapp):
        panel = MqttPanel()
        panel._show_result(True, {"stdout": "第一行\n第二行"})

        text = panel.result_view.toPlainText()
        assert "第一行" in text and "第二行" in text


# ============================================================
# 命令列表自动刷新
# ============================================================

class TestCommandListAutoRefresh:
    def test_disabled_command_drops_out_of_combo(self, qapp, registry):
        """云端策略禁用后：下拉框摘掉，左侧清单保留并标注「已禁用」。"""
        panel = MqttPanel()
        panel._refresh_commands()
        assert "cloud_probe" in _combo_items(panel)

        CommandHandler.apply_policy({"cloud_probe": False})
        panel._refresh_commands_if_changed()

        assert "cloud_probe" not in _combo_items(panel)
        assert any(t.startswith("cloud_probe") and "已禁用" in t
                   for t in _list_labels(panel))

    def test_re_enabled_command_comes_back(self, qapp, registry):
        panel = MqttPanel()
        CommandHandler.apply_policy({"cloud_probe": False})
        panel._refresh_commands()
        assert "cloud_probe" not in _combo_items(panel)

        CommandHandler.apply_policy({"cloud_probe": True})
        panel._refresh_commands_if_changed()

        assert "cloud_probe" in _combo_items(panel)

    def test_local_policy_file_change_is_picked_up(self, qapp, registry,
                                                   tmp_path, monkeypatch):
        """改本地策略文件后同样能在 2s 轮询内跟上（无需重启）。"""
        policy = tmp_path / "command_policy.json"
        policy.write_text('{"terminal_info": false}', encoding="utf-8")
        monkeypatch.setenv("GREEN_TRACKER_COMMAND_POLICY_FILE", str(policy))

        panel = MqttPanel()
        panel._refresh_commands()
        assert "terminal_info" not in _combo_items(panel)

    def test_no_rebuild_when_nothing_changed(self, qapp, registry, monkeypatch):
        """签名未变时不重建，避免每 2s 打断用户输入。"""
        panel = MqttPanel()
        panel._refresh_commands()

        calls = []
        monkeypatch.setattr(panel, "_refresh_commands", lambda: calls.append(1))
        panel._refresh_commands_if_changed()
        panel._refresh_commands_if_changed()

        assert calls == []

    def test_source_change_also_triggers_rebuild(self, qapp, registry):
        """同一命令的开关来源变化（default -> cloud）也要刷新（tooltip 会变）。"""
        panel = MqttPanel()
        panel._refresh_commands()

        CommandHandler.apply_policy({"cloud_probe": False})
        panel._refresh_commands_if_changed()

        spec = next(s for s in panel.service.describe_commands()
                    if s["name"] == "cloud_probe")
        assert spec["source"] == "cloud"
