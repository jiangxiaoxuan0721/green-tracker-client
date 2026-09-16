"""mqtt.commands — 命令注册表与内置命令测试。"""
import getpass
import importlib
import os
import sys
from datetime import datetime

import pytest

commands = importlib.import_module("mqtt.commands")
CommandHandler = commands.CommandHandler


@pytest.fixture
def registry(monkeypatch):
    """让每个用例在注册表副本上运行，避免污染全局注册状态。"""
    monkeypatch.setattr(CommandHandler, "_registry", dict(CommandHandler._registry))
    return CommandHandler._registry


# ============================================================
# 注册表调度
# ============================================================

class TestExecute:
    def test_unknown_command(self, registry):
        assert CommandHandler.execute("nope") == {
            "success": False, "error": "未知命令: nope"}

    def test_success_wraps_result(self, registry):
        registry["echo"] = lambda p: {"got": p}
        assert CommandHandler.execute("echo", {"a": 1}) == {
            "success": True, "result": {"got": {"a": 1}}}

    def test_missing_params_passed_as_empty_dict(self, registry):
        seen = {}

        def handler(params):
            seen.update(params)
            return {"ok": True}

        registry["probe"] = handler
        CommandHandler.execute("probe")
        assert seen == {}

    def test_explicit_empty_params(self, registry):
        registry["probe"] = lambda p: {"ok": True}
        assert CommandHandler.execute("probe", {})["success"] is True

    def test_handler_exception_is_captured_not_raised(self, registry):
        def boom(params):
            raise RuntimeError("炸了")

        registry["boom"] = boom
        assert CommandHandler.execute("boom") == {"success": False, "error": "炸了"}


class TestRegisterDecorator:
    def test_registers_and_returns_original_function(self, registry):
        @CommandHandler.register("my_cmd")
        def handler(params):
            return {"v": 1}

        assert "my_cmd" in CommandHandler.list_commands()
        assert CommandHandler.execute("my_cmd")["result"] == {"v": 1}
        assert handler({}) == {"v": 1}

    def test_same_name_is_overwritten(self, registry):
        CommandHandler.register("dup")(lambda p: 1)
        CommandHandler.register("dup")(lambda p: 2)
        assert CommandHandler.execute("dup")["result"] == 2

    def test_list_commands_reflects_dynamic_registration(self, registry):
        CommandHandler.register("brand_new")(lambda p: None)
        assert "brand_new" in CommandHandler.list_commands()


class TestBuiltinRegistration:
    def test_all_builtin_commands_registered(self):
        names = set(CommandHandler.list_commands())
        expected = {"ping", "get_info", "reboot", "set_config",
                    "get_metrics", "list_commands", "cloud_probe",
                    "execute_shell", "terminal_reset", "terminal_interrupt",
                    "terminal_resize", "terminal_info"}
        assert expected <= names


# ============================================================
# 内置命令
# ============================================================

class TestPing:
    def test_pong_payload(self):
        result = CommandHandler.execute("ping")
        assert result["success"] is True

        body = result["result"]
        assert body["pong"] is True
        assert isinstance(body["uptime"], float)
        assert body["uptime"] >= 0
        # timestamp 必须是合法 ISO8601（带时区）
        assert datetime.fromisoformat(body["timestamp"]).tzinfo is not None


class TestGetInfo:
    def test_fields(self, monkeypatch):
        monkeypatch.setenv("MQTT_DEVICE_ID", "dev-42")
        body = CommandHandler.execute("get_info")["result"]

        assert body["device_id"] == "dev-42"
        assert body["hostname"]
        assert body["platform"]
        assert body["python_version"].count(".") == 2
        assert isinstance(body["local_ip"], str) and body["local_ip"]

    def test_device_id_falls_back_to_unknown(self, monkeypatch):
        monkeypatch.delenv("MQTT_DEVICE_ID", raising=False)
        assert CommandHandler.execute("get_info")["result"]["device_id"] == "unknown_device"


class TestReboot:
    def test_default_delay_is_five_seconds(self):
        body = CommandHandler.execute("reboot")["result"]
        assert body["delay"] == 5
        assert "5" in body["message"]

    def test_custom_delay(self):
        assert CommandHandler.execute("reboot", {"delay": 30})["result"]["delay"] == 30


class TestSetConfig:
    def test_valid_config_echoes_key_and_value(self):
        body = CommandHandler.execute("set_config", {"key": "k", "value": "v"})["result"]
        assert body == {"message": "配置更新成功", "key": "k", "value": "v"}

    @pytest.mark.parametrize("params", [
        {},
        {"key": "k"},
        {"value": "v"},
        {"key": "k", "value": None},
    ])
    def test_missing_params_surface_as_error_result(self, params):
        result = CommandHandler.execute("set_config", params)
        assert result["success"] is False
        assert "缺少参数" in result["error"]


class TestGetMetrics:
    def test_metric_ranges_and_types(self):
        body = CommandHandler.execute("get_metrics")["result"]

        assert 10 <= body["cpu_usage"] <= 80
        assert 30 <= body["memory_usage"] <= 70
        assert 35 <= body["temperature"] <= 65
        assert isinstance(body["uptime_seconds"], int)
        assert body["uptime_seconds"] >= 0


class TestListCommands:
    def test_returns_full_registry_including_itself(self):
        body = CommandHandler.execute("list_commands")["result"]
        assert "list_commands" in body["commands"]
        assert set(body["commands"]) == set(CommandHandler.list_commands())


class TestCloudProbe:
    def test_probe_response(self, monkeypatch):
        monkeypatch.setenv("MQTT_DEVICE_ID", "dev-9")
        body = CommandHandler.execute("cloud_probe")["result"]

        assert body["probe_response"] == "ok"
        assert body["device_id"] == "dev-9"
        assert datetime.fromisoformat(body["timestamp"]).tzinfo is not None
        assert body["note"]


# ============================================================
# execute_shell
# ============================================================

def _py_cmd(code: str) -> str:
    """构造跨平台命令行：即便解释器路径含空格，也能被真实 shell 正确解析。"""
    return f'"{sys.executable}" -c "{code}"'


def _ok_result(stdout="ok", exit_code=0, ok=True, timed_out=False):
    """构造一个上下文执行结果 —— 供替换调度层的用例使用。"""
    return {"exit_code": exit_code, "stdout": stdout, "ok": ok,
            "timed_out": timed_out, "duration": 0.1, "cwd": "/"}


class TestExecuteShell:
    """execute_shell — 以当前用户在真实 shell 中执行整条命令字符串。"""

    def test_runs_command_with_spaces_in_real_shell(self):
        """核心：含空格与引号的整串交由真实 shell 解析并正确执行。"""
        body = CommandHandler.execute(
            "execute_shell", {"command": _py_cmd("print('hello world')")}
        )["result"]

        assert body["exit_code"] == 0, body
        assert "hello world" in body["stdout"]
        assert body["ok"] is True
        assert body["timed_out"] is False
        assert body["shell"]                    # 真实 shell 路径
        assert body["command"]
        assert isinstance(body["duration"], float)

    def test_nonzero_exit_code_and_stderr(self):
        body = CommandHandler.execute("execute_shell", {
            "command": _py_cmd("import sys; sys.stderr.write('oops'); sys.exit(3)"),
        })["result"]

        assert body["exit_code"] == 3
        assert body["ok"] is False
        # PTY 真终端下 stdout/stderr 本就合并（与本地终端一致），降级后端才分离
        assert "oops" in body["stdout"] or "oops" in body["stderr"]

    @pytest.mark.skipif(not hasattr(os, "getuid"), reason="POSIX only")
    def test_runs_as_the_current_process_user(self):
        """以当前启动程序的用户身份执行（uid 与客户端进程一致）。"""
        body = CommandHandler.execute("execute_shell", {
            "command": _py_cmd("import os; print(os.getuid())"),
        })["result"]

        assert body["stdout"].strip() == str(os.getuid())
        try:
            expected_user = getpass.getuser()
        except Exception:
            expected_user = ""
        assert body["user"] == expected_user

    def test_cwd_is_honoured(self, tmp_path):
        body = CommandHandler.execute("execute_shell", {
            "command": _py_cmd("import os; print(os.getcwd())"),
            "cwd": str(tmp_path),
        })["result"]

        assert os.path.realpath(body["stdout"].strip()) == os.path.realpath(str(tmp_path))
        assert body["cwd"] == str(tmp_path)

    @pytest.mark.parametrize("params", [
        {},
        {"command": ""},
        {"command": "   "},
        {"command": 123},
        {"command": "echo hi", "timeout": 0},
        {"command": "echo hi", "timeout": -1},
        {"command": "echo hi", "timeout": "abc"},
        {"command": "echo hi", "max_output": 0},
        {"command": "echo hi", "cwd": "/definitely/not/a/dir"},
    ])
    def test_invalid_params_surface_as_error(self, params):
        """参数非法时收敛为 error 结果，且不执行任何命令。"""
        result = CommandHandler.execute("execute_shell", params)
        assert result["success"] is False
        assert result["error"]

    def test_disabled_by_env_switch(self, monkeypatch):
        monkeypatch.setenv("GREEN_TRACKER_ENABLE_SHELL", "false")
        result = CommandHandler.execute("execute_shell", {"command": "echo hi"})
        assert result["success"] is False

    # 以下三条替换掉上下文调度层（commands._run_in_context），
    # 与底层是 PTY 还是降级后端无关，只验证参数处理与结果透传。

    def test_timeout_is_capped(self, monkeypatch):
        """超时被强制收敛到上限，避免阻塞 MQTT 网络线程。"""
        captured = {}

        def fake_context(command, timeout, max_output, cwd, reset):
            captured["timeout"] = timeout
            return _ok_result()

        monkeypatch.setattr(commands, "_run_in_context", fake_context)
        CommandHandler.execute("execute_shell", {"command": "x", "timeout": 99999})

        assert captured["timeout"] == commands._SHELL_MAX_TIMEOUT

    def test_timed_out_result_is_propagated(self, monkeypatch):
        def fake_context(command, timeout, max_output, cwd, reset):
            return _ok_result(stdout="partial", exit_code=-1, ok=False, timed_out=True)

        monkeypatch.setattr(commands, "_run_in_context", fake_context)
        body = CommandHandler.execute("execute_shell", {"command": "sleep 100"})["result"]

        assert body["timed_out"] is True
        assert body["exit_code"] == -1
        assert body["ok"] is False
        assert "partial" in body["stdout"]

    def test_max_output_is_forwarded(self, monkeypatch):
        """max_output 原样传给上下文层（截断由后端负责，此处只验证校验与透传）。"""
        captured = {}

        def fake_context(command, timeout, max_output, cwd, reset):
            captured["max_output"] = max_output
            return _ok_result()

        monkeypatch.setattr(commands, "_run_in_context", fake_context)
        CommandHandler.execute("execute_shell", {"command": "x", "max_output": 100})

        assert captured["max_output"] == 100
