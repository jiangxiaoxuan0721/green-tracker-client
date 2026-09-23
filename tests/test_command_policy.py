"""指令预设元数据（公有 / 拓展 + 启用开关）与启用策略测试。"""
import importlib
import os
import time

import pytest

import config
from mqtt.commands import (
    CommandHandler,
    VISIBILITY_EXTENSION,
    VISIBILITY_PUBLIC,
)


@pytest.fixture
def registry(monkeypatch):
    """每个用例在注册表副本上运行，并清空策略，避免污染全局状态。"""
    monkeypatch.setattr(CommandHandler, "_registry", dict(CommandHandler._registry))
    monkeypatch.setattr(CommandHandler, "_specs", dict(CommandHandler._specs))
    monkeypatch.setattr(CommandHandler, "_policy", {})
    monkeypatch.setattr(CommandHandler, "_file_cache", None)
    return CommandHandler._registry


# ============================================================
# 预设元数据
# ============================================================

class TestPresetMetadata:
    def test_builtin_public_commands(self):
        """公有指令：跨平台通用契约。"""
        specs = {s["name"]: s for s in CommandHandler.describe_commands()}
        expected = {"ping", "get_info", "get_metrics", "list_commands",
                    "revoke_control", "reboot"}
        for name in expected:
            assert specs[name]["visibility"] == VISIBILITY_PUBLIC, name

    def test_builtin_extension_commands(self):
        """拓展指令：能力可选，平台侧按需开关。"""
        specs = {s["name"]: s for s in CommandHandler.describe_commands()}
        expected = {"set_config", "cloud_probe", "execute_shell",
                    "terminal_reset", "terminal_interrupt",
                    "terminal_info"}
        for name in expected:
            assert specs[name]["visibility"] == VISIBILITY_EXTENSION, name

    def test_all_builtin_enabled_by_default(self):
        specs = CommandHandler.describe_commands()
        assert all(s["enabled"] for s in specs)
        assert all(s["source"] == "default" for s in specs)

    def test_metadata_carries_name_and_description(self):
        specs = {s["name"]: s for s in CommandHandler.describe_commands()}
        assert specs["ping"]["description"]
        assert specs["ping"]["default_enabled"] is True

    def test_register_with_keywords(self, registry):
        @CommandHandler.register("ext_only", visibility=VISIBILITY_EXTENSION,
                                 enabled=False, description="默认关闭的拓展指令")
        def handler(params):
            return {"ok": True}

        spec = CommandHandler.describe("ext_only")
        assert spec == {
            "name": "ext_only",
            "visibility": VISIBILITY_EXTENSION,
            "enabled": False,
            "default_enabled": False,
            "description": "默认关闭的拓展指令",
            "source": "default",
        }

    def test_register_defaults_to_extension_and_enabled(self, registry):
        CommandHandler.register("plain")(lambda p: None)
        spec = CommandHandler.describe("plain")
        assert spec["visibility"] == VISIBILITY_EXTENSION
        assert spec["enabled"] is True

    def test_description_falls_back_to_docstring_first_line(self, registry):
        @CommandHandler.register("documented")
        def handler(params):
            """首行说明。

            其余段落不应进入描述。
            """

        assert CommandHandler.describe("documented")["description"] == "首行说明。"


# ============================================================
# 启用门控
# ============================================================

class TestDisabledCommandIsBlocked:
    def test_preset_disabled_command_cannot_execute(self, registry):
        CommandHandler.register("off_by_default", enabled=False)(lambda p: {"v": 1})

        result = CommandHandler.execute("off_by_default")
        assert result == {"success": False, "error": "命令已被禁用: off_by_default"}

    def test_disabled_command_is_hidden_from_discovery(self, registry):
        CommandHandler.register("off_by_default", enabled=False)(lambda p: None)

        assert "off_by_default" not in CommandHandler.list_commands()
        assert "off_by_default" in CommandHandler.list_commands(include_disabled=True)

    def test_disabled_applies_to_local_panel_execution(self, registry):
        """面板本地调试也不能绕过「未启用」这道门（它是能力开关，不是权限）。"""
        CommandHandler.register("off_by_default", enabled=False)(lambda p: None)
        assert CommandHandler.execute("off_by_default", local=True)["success"] is False


# ============================================================
# 云端 / 其他平台下发的策略
# ============================================================

class TestApplyPolicy:
    def test_policy_disables_command(self, registry):
        assert CommandHandler.apply_policy({"cloud_probe": False}) == {"cloud_probe": False}
        assert CommandHandler.is_enabled("cloud_probe") is False
        assert "cloud_probe" not in CommandHandler.list_commands()

    def test_policy_can_enable_preset_disabled_command(self, registry):
        CommandHandler.register("opt_in", enabled=False)(lambda p: None)
        CommandHandler.apply_policy({"opt_in": True})

        assert CommandHandler.is_enabled("opt_in") is True
        assert "opt_in" in CommandHandler.list_commands()

    def test_source_is_reported_as_cloud(self, registry):
        CommandHandler.apply_policy({"cloud_probe": False})
        assert CommandHandler.describe("cloud_probe")["source"] == "cloud"

    def test_protected_commands_cannot_be_disabled(self, registry):
        for name in ("ping", "list_commands", "revoke_control"):
            assert CommandHandler.apply_policy({name: False}) == {}
            assert CommandHandler.is_enabled(name) is True

    def test_unparsable_value_is_ignored(self, registry):
        assert CommandHandler.apply_policy({"cloud_probe": "maybe"}) == {}
        assert CommandHandler.is_enabled("cloud_probe") is True

    def test_reset_policy_restores_preset(self, registry):
        CommandHandler.apply_policy({"cloud_probe": False})
        CommandHandler.reset_policy()
        assert CommandHandler.is_enabled("cloud_probe") is True

    def test_execute_reports_disabled_from_cloud_policy(self, registry):
        CommandHandler.apply_policy({"cloud_probe": False})
        result = CommandHandler.execute("cloud_probe")
        assert result["success"] is False
        assert "已被禁用" in result["error"]


# ============================================================
# 本地策略文件（部署方最终否决权）
# ============================================================

class TestFilePolicy:
    @staticmethod
    def _write(path, text):
        """写入策略文件，并强制推进 mtime，保证缓存判定稳定。"""
        path.write_text(text, encoding="utf-8")
        os.utime(path, (time.time() + 1, time.time() + 1))
        return path

    @pytest.fixture
    def policy_path(self, tmp_path, monkeypatch):
        """把策略文件路径指向临时目录，避免触碰仓库内的真实文件。"""
        path = tmp_path / "command_policy.json"
        monkeypatch.setenv("GREEN_TRACKER_COMMAND_POLICY_FILE", str(path))
        return path

    def test_disabled_commands_in_file(self, registry, policy_path):
        self._write(policy_path, '{"execute_shell": false, "terminal_reset": false}')

        assert CommandHandler.is_enabled("execute_shell") is False
        assert CommandHandler.is_enabled("terminal_reset") is False
        assert CommandHandler.is_enabled("ping") is True
        assert "execute_shell" not in CommandHandler.list_commands()

    def test_file_can_enable_preset_disabled_command(self, registry, policy_path):
        CommandHandler.register("opt_in", enabled=False)(lambda p: None)
        self._write(policy_path, '{"opt_in": true}')

        assert CommandHandler.is_enabled("opt_in") is True

    def test_source_is_reported_as_file(self, registry, policy_path):
        self._write(policy_path, '{"cloud_probe": false, "set_config": "off"}')

        assert CommandHandler.is_enabled("cloud_probe") is False
        assert CommandHandler.is_enabled("set_config") is False
        assert CommandHandler.describe("cloud_probe")["source"] == "file"

    def test_invalid_json_is_ignored(self, registry, policy_path):
        self._write(policy_path, "{not json")
        assert CommandHandler.is_enabled("cloud_probe") is True

    def test_non_object_json_is_ignored(self, registry, policy_path):
        self._write(policy_path, '["cloud_probe"]')
        assert CommandHandler.is_enabled("cloud_probe") is True

    def test_missing_file_falls_back_to_preset(self, registry, policy_path):
        assert not policy_path.exists()
        assert CommandHandler.is_enabled("cloud_probe") is True

    def test_protected_commands_cannot_be_disabled(self, registry, policy_path):
        self._write(policy_path, '{"ping": false, "list_commands": false}')
        assert CommandHandler.is_enabled("ping") is True
        assert CommandHandler.is_enabled("list_commands") is True

    def test_file_overrides_cloud_policy(self, registry, policy_path):
        """本地部署方拥有最终否决权：策略文件压过云端策略。"""
        self._write(policy_path, '{"cloud_probe": true}')
        CommandHandler.apply_policy({"cloud_probe": False})

        assert CommandHandler.is_enabled("cloud_probe") is True

    def test_cache_invalidates_when_file_changes(self, registry, policy_path):
        self._write(policy_path, '{"cloud_probe": false}')
        assert CommandHandler.is_enabled("cloud_probe") is False

        self._write(policy_path, '{}')
        assert CommandHandler.is_enabled("cloud_probe") is True


# ============================================================
# 策略文件位置
# ============================================================

class TestPolicyFilePath:
    def test_default_points_into_repo_config_dir(self, monkeypatch):
        """默认取仓库内 config/command_policy.json。"""
        monkeypatch.delenv("GREEN_TRACKER_COMMAND_POLICY_FILE", raising=False)
        path = config.command_policy_file()

        assert path.endswith(os.path.join("config", "command_policy.json"))
        assert os.path.exists(path), "仓库内应提供默认策略文件"

    def test_env_overrides_path(self, monkeypatch):
        """部署方可把策略放到仓库之外（只读部署 / 多实例共用）。"""
        monkeypatch.setenv("GREEN_TRACKER_COMMAND_POLICY_FILE",
                           "/etc/green-tracker/policy.json")
        assert config.command_policy_file() == "/etc/green-tracker/policy.json"


# ============================================================
# 能力发现报文
# ============================================================

class TestListCommandsPayload:
    def test_returns_enabled_names_and_full_specs(self, registry):
        CommandHandler.register("off_by_default", enabled=False)(lambda p: None)

        body = CommandHandler.execute("list_commands")["result"]
        assert "off_by_default" not in body["commands"]
        assert "list_commands" in body["commands"]

        names = {s["name"] for s in body["specs"]}
        assert "off_by_default" in names          # 禁用的也要上报，供平台侧渲染开关

    def test_disabled_spec_reports_enabled_false(self, registry):
        CommandHandler.register("off_by_default", enabled=False)(lambda p: None)

        spec = next(s for s in CommandHandler.execute("list_commands")["result"]["specs"]
                    if s["name"] == "off_by_default")
        assert spec["enabled"] is False
        assert spec["default_enabled"] is False


# ============================================================
# 服务层入口
# ============================================================

class TestServiceEntryPoints:
    def test_register_handler_with_keywords(self, registry):
        from mqtt.manager import MQTTService

        service = MQTTService.__new__(MQTTService)
        service.register_command_handler("ext_off", lambda p: None, enabled=False)

        assert "ext_off" not in service.list_available_commands()
        assert "ext_off" in service.list_available_commands(include_disabled=True)

    def test_apply_command_policy_delegates(self, registry):
        from mqtt.manager import MQTTService

        service = MQTTService.__new__(MQTTService)
        assert service.apply_command_policy({"cloud_probe": False}) == {"cloud_probe": False}
        assert CommandHandler.is_enabled("cloud_probe") is False

    def test_describe_commands_matches_registry(self, registry):
        from mqtt.manager import MQTTService

        service = MQTTService.__new__(MQTTService)
        assert {s["name"] for s in service.describe_commands()} == \
            set(service.list_available_commands(include_disabled=True))


def test_constants_are_importable_from_package():
    pkg = importlib.import_module("mqtt")
    assert pkg.VISIBILITY_PUBLIC == "public"
    assert pkg.VISIBILITY_EXTENSION == "extension"
