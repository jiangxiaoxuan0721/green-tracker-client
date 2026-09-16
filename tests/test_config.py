"""config 模块测试 — 重点是路径的惰性解析与环境变量回退。"""
import os

import config


def test_data_root_default(monkeypatch):
    monkeypatch.delenv("GREEN_TRACKER_DATA_DIR", raising=False)
    assert config.data_root() == os.path.expanduser("~/green_tracker_data")


def test_data_root_env_override(monkeypatch, tmp_path):
    monkeypatch.setenv("GREEN_TRACKER_DATA_DIR", str(tmp_path / "custom"))
    assert config.data_root() == str(tmp_path / "custom")


def test_data_root_follows_home_redirection(monkeypatch, tmp_path):
    """惰性解析：HOME 被重定向后必须跟随，否则测试会污染真实家目录。"""
    monkeypatch.delenv("GREEN_TRACKER_DATA_DIR", raising=False)
    monkeypatch.setenv("HOME", str(tmp_path))
    assert config.data_root() == str(tmp_path / "green_tracker_data")


def test_api_base_url_default(monkeypatch):
    monkeypatch.delenv("API_BASE_URL", raising=False)
    assert config.api_base_url() == config.DEFAULT_API_BASE_URL


def test_api_base_url_never_empty(monkeypatch):
    """修复点：原先 env 未配置时会拼出 "None/api/..." 形式的 URL。"""
    monkeypatch.setenv("API_BASE_URL", "")
    assert config.api_base_url() == config.DEFAULT_API_BASE_URL


def test_api_base_url_strips_trailing_slash(monkeypatch):
    monkeypatch.setenv("API_BASE_URL", "https://api.example.com/")
    assert config.api_base_url() == "https://api.example.com"


def test_secret_key(monkeypatch):
    monkeypatch.delenv("SECRET_KEY", raising=False)
    assert config.secret_key() is None
    monkeypatch.setenv("SECRET_KEY", "abc")
    assert config.secret_key() == "abc"


def test_api_timeout_default_and_override(monkeypatch):
    monkeypatch.delenv("API_TIMEOUT", raising=False)
    assert config.api_timeout() == 10.0
    monkeypatch.setenv("API_TIMEOUT", "2.5")
    assert config.api_timeout() == 2.5


def test_collect_intervals(monkeypatch):
    monkeypatch.delenv("COLLECT_INTERVAL", raising=False)
    monkeypatch.delenv("VIRTUAL_SENSOR_INTERVAL", raising=False)
    assert config.collect_interval() == 1.0
    assert config.virtual_sensor_interval() == 5.0
