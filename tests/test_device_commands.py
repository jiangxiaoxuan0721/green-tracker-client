"""云端设备指令通道（/api/device-commands）客户端测试 —— TDD。

设备侧只做三件事：签到、取指令、回执。本文件验证：
  * 请求头 / URL / 方法构造正确
  * 响应信封 `data` 解包
  * 401 / 403 / 5xx / 网络错误被翻译成可退避的异常类型
"""
from importlib import import_module
from types import SimpleNamespace

import pytest

from _util import DummyResponse

dc = import_module("api.device_commands")


def _patch(monkeypatch, handler):
    """替换模块内的 requests，捕获调用参数。"""
    captured = {}

    def fake_request(method, url, headers=None, params=None, json=None, timeout=None):
        captured.update(method=method, url=url, headers=headers,
                        params=params, json=json, timeout=timeout)
        return handler(captured)

    monkeypatch.setattr(dc, "requests", SimpleNamespace(
        request=fake_request, RequestException=RuntimeError))
    monkeypatch.setattr(dc, "api_base_url", lambda: "http://cloud")
    monkeypatch.setattr(dc, "secret_key", lambda: "green-abc")
    monkeypatch.setattr(dc, "device_id", lambda: "dev-1")
    monkeypatch.setattr(dc, "api_timeout", lambda: 7.0)
    return captured


def _ok(data=None, status_code=200):
    payload = {"code": status_code, "message": "success", "data": data}
    return DummyResponse(json_data=payload, status_code=status_code)


# ============================================================
# 通用约定：双头
# ============================================================

class TestCommonHeaders:
    def test_every_request_carries_api_key_and_device_id(self, monkeypatch):
        captured = _patch(monkeypatch, lambda c: _ok({"registered": True}))

        dc.heartbeat()

        assert captured["headers"]["X-API-Key"] == "green-abc"
        assert captured["headers"]["X-Device-Id"] == "dev-1"
        assert captured["timeout"] == 7.0

    def test_missing_api_key_raises(self, monkeypatch):
        _patch(monkeypatch, lambda c: _ok({}))
        monkeypatch.setattr(dc, "secret_key", lambda: None)

        with pytest.raises(dc.AuthError, match="SECRET_KEY"):
            dc.heartbeat()


# ============================================================
# 接口一：签到
# ============================================================

class TestHeartbeat:
    def test_posts_to_heartbeat_and_unwraps_data(self, monkeypatch):
        data = {"registered": True, "capabilities": {"upload_data": True}}
        captured = _patch(monkeypatch, lambda c: _ok(data))

        result = dc.heartbeat()

        assert captured["method"] == "POST"
        assert captured["url"] == "http://cloud/api/device-commands/heartbeat"
        assert result == data

    def test_401_raises_auth_error(self, monkeypatch):
        _patch(monkeypatch, lambda c: DummyResponse(json_data={}, status_code=401))

        with pytest.raises(dc.AuthError):
            dc.heartbeat()

    def test_403_raises_forbidden_error(self, monkeypatch):
        _patch(monkeypatch, lambda c: DummyResponse(json_data={}, status_code=403))

        with pytest.raises(dc.ForbiddenError):
            dc.heartbeat()

    def test_500_raises_transient_error(self, monkeypatch):
        _patch(monkeypatch, lambda c: DummyResponse(json_data={}, status_code=500))

        with pytest.raises(dc.TransientError):
            dc.heartbeat()

    def test_network_error_raises_transient_error(self, monkeypatch):
        def boom(c):
            raise RuntimeError("connection refused")

        _patch(monkeypatch, boom)

        with pytest.raises(dc.TransientError):
            dc.heartbeat()


# ============================================================
# 接口二：取指令（HTTP 通道）
# ============================================================

class TestFetchPending:
    def test_gets_pending_with_device_id_param(self, monkeypatch):
        captured = _patch(monkeypatch, lambda c: _ok([{"command_id": "1"}]))

        result = dc.fetch_pending()

        assert captured["method"] == "GET"
        assert captured["url"] == "http://cloud/api/device-commands/pending"
        assert captured["params"] == {"device_id": "dev-1"}
        assert result == [{"command_id": "1"}]

    def test_unwraps_commands_envelope(self, monkeypatch):
        _patch(monkeypatch, lambda c: _ok({"commands": [{"command_id": "1"}]}))

        assert dc.fetch_pending() == [{"command_id": "1"}]

    def test_returns_empty_list_when_no_data(self, monkeypatch):
        _patch(monkeypatch, lambda c: _ok(None))

        assert dc.fetch_pending() == []


# ============================================================
# 接口三：回执
# ============================================================

class TestReportResult:
    def test_posts_acked_payload(self, monkeypatch):
        captured = _patch(monkeypatch, lambda c: _ok({"ok": True}))

        dc.report_result("cmd-9", "acked", {"uptime_seconds": 12})

        assert captured["method"] == "POST"
        assert captured["url"] == "http://cloud/api/device-commands/cmd-9/result"
        assert captured["json"] == {
            "status": "acked", "result": {"uptime_seconds": 12}}

    def test_failed_includes_error_message(self, monkeypatch):
        captured = _patch(monkeypatch, lambda c: _ok({"ok": True}))

        dc.report_result("cmd-9", "failed", None, error_message="boom")

        assert captured["json"]["status"] == "failed"
        assert captured["json"]["error_message"] == "boom"

    def test_invalid_status_rejected(self, monkeypatch):
        _patch(monkeypatch, lambda c: _ok({}))

        with pytest.raises(ValueError, match="status"):
            dc.report_result("cmd-9", "unknown")

    def test_empty_command_id_rejected(self, monkeypatch):
        _patch(monkeypatch, lambda c: _ok({}))

        with pytest.raises(ValueError):
            dc.report_result("", "acked")
