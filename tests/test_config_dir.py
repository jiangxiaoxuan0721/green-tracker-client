"""配置目录解析 —— 安装后 .env 与指令策略文件的定位。

安装态下 CWD 不再是仓库根目录，配置必须由「配置目录」解析出来，
否则一键安装后的程序读不到 .env 与 command_policy.json。
"""
import os
import subprocess
import sys
from pathlib import Path

import pytest

import config

ROOT = Path(__file__).resolve().parent.parent


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch):
    monkeypatch.delenv("GREEN_TRACKER_CONFIG_DIR", raising=False)
    monkeypatch.delenv("GREEN_TRACKER_COMMAND_POLICY_FILE", raising=False)
    monkeypatch.delenv("XDG_CONFIG_HOME", raising=False)


class TestConfigDir:
    def test_default_under_home(self, monkeypatch, tmp_path):
        monkeypatch.setenv("HOME", str(tmp_path))
        assert config.config_dir() == str(
            tmp_path / ".config" / "green-tracker-client")

    def test_env_overrides(self, monkeypatch, tmp_path):
        monkeypatch.setenv("GREEN_TRACKER_CONFIG_DIR", str(tmp_path / "cfg"))
        assert config.config_dir() == str(tmp_path / "cfg")

    def test_xdg_config_home_is_honoured(self, monkeypatch, tmp_path):
        monkeypatch.setenv("HOME", str(tmp_path / "home"))
        monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "xdg"))
        assert config.config_dir() == str(tmp_path / "xdg" / "green-tracker-client")

    def test_resolved_on_every_call(self, monkeypatch, tmp_path):
        """惰性解析：HOME 变化后结果随之变化（模块常量会在 import 时冻结）。"""
        monkeypatch.setenv("HOME", str(tmp_path / "a"))
        first = config.config_dir()
        monkeypatch.setenv("HOME", str(tmp_path / "b"))
        assert config.config_dir() != first


class TestCommandPolicyFile:
    def test_explicit_env_wins(self, monkeypatch):
        monkeypatch.setenv("GREEN_TRACKER_COMMAND_POLICY_FILE",
                           "/etc/green-tracker/policy.json")
        assert config.command_policy_file() == "/etc/green-tracker/policy.json"

    def test_config_dir_wins_over_repo_default(self, monkeypatch, tmp_path):
        cfg = tmp_path / "cfg"
        cfg.mkdir()
        (cfg / "command_policy.json").write_text("{}", encoding="utf-8")
        monkeypatch.setenv("GREEN_TRACKER_CONFIG_DIR", str(cfg))

        assert config.command_policy_file() == str(cfg / "command_policy.json")

    def test_falls_back_to_repo_config(self, monkeypatch, tmp_path):
        monkeypatch.setenv("GREEN_TRACKER_CONFIG_DIR", str(tmp_path / "empty"))
        path = config.command_policy_file()

        assert path.endswith(os.path.join("config", "command_policy.json"))
        assert os.path.exists(path)


class TestEnvLoading:
    @staticmethod
    def _run(code: str, env_extra: dict) -> str:
        # 宿主机可能已被仓库根目录 .env 污染过同名变量，先清掉再测
        env = {k: v for k, v in os.environ.items()
               if k not in ("MQTT_DEVICE_ID", "PACKAGING_TEST_KEY")}
        env.update(env_extra)
        return subprocess.run(
            [sys.executable, "-c", code], cwd=str(ROOT), env=env,
            capture_output=True, text=True, check=True).stdout.strip()

    def test_config_dir_env_is_loaded_by_config_module(self, tmp_path):
        cfg = tmp_path / "cfg"
        cfg.mkdir()
        (cfg / ".env").write_text("PACKAGING_TEST_KEY=from_config_dir\n",
                                  encoding="utf-8")

        out = self._run(
            "import config, os; print(os.getenv('PACKAGING_TEST_KEY'))",
            {"GREEN_TRACKER_CONFIG_DIR": str(cfg)})
        assert out == "from_config_dir"

    def test_config_dir_env_is_loaded_by_mqtt_client(self, tmp_path):
        cfg = tmp_path / "cfg"
        cfg.mkdir()
        (cfg / ".env").write_text("MQTT_DEVICE_ID=device-from-config-dir\n",
                                  encoding="utf-8")

        out = self._run(
            "from mqtt.client import DEVICE_ID; print(DEVICE_ID)",
            {"GREEN_TRACKER_CONFIG_DIR": str(cfg)})
        assert out == "device-from-config-dir"
