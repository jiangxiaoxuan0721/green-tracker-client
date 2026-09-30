"""api 模块测试 — 通过 mock requests 验证请求构造与响应处理。"""
from importlib import import_module
from types import SimpleNamespace

import pytest

from _util import DummyResponse

gs = import_module("api.get_active_sessions")
un = import_module("api.upload_numeric_data")
uf = import_module("api.upload_file_data")


# ============================================================
# get_active_sessions
# ============================================================

class TestGetActiveSessions:
    def test_uses_env_api_key_and_builds_url(self, monkeypatch):
        captured = {}

        def fake_post(url, headers=None, **kwargs):
            captured["url"] = url
            captured["headers"] = headers
            return DummyResponse(json_data=[{"id": "1", "mission_name": "m"}])

        monkeypatch.setattr(gs, "requests", SimpleNamespace(post=fake_post))
        monkeypatch.setenv("API_BASE_URL", "http://server:9000")
        monkeypatch.setenv("SECRET_KEY", "env-secret")

        result = gs.get_active_sessions()

        assert result == [{"id": "1", "mission_name": "m"}]
        assert captured["url"] == "http://server:9000/api/collection-sessions/active_sessions"
        assert captured["headers"]["x-api-key"] == "env-secret"

    def test_explicit_api_key_overrides_env(self, monkeypatch):
        captured = {}

        def fake_post(url, headers=None, **kwargs):
            captured["headers"] = headers
            return DummyResponse(json_data=[])

        monkeypatch.setattr(gs, "requests", SimpleNamespace(post=fake_post))
        monkeypatch.setenv("API_BASE_URL", "http://server")
        monkeypatch.setenv("SECRET_KEY", "env-secret")

        gs.get_active_sessions(api_key="explicit")

        assert captured["headers"]["x-api-key"] == "explicit"

    def test_http_error_is_propagated(self, monkeypatch):
        monkeypatch.setattr(
            gs, "requests",
            SimpleNamespace(post=lambda *a, **k: DummyResponse(status_code=500)),
        )
        monkeypatch.setenv("API_BASE_URL", "http://server")
        with pytest.raises(RuntimeError, match="HTTP 500"):
            gs.get_active_sessions(api_key="k")


# ============================================================
# upload_numeric_data
# ============================================================

class TestUploadNumericData:
    def _patch(self, monkeypatch, captured):
        def fake_post(url, headers=None, json=None, **kwargs):
            captured.update(url=url, headers=headers, payload=json)
            return DummyResponse(json_data={"ok": True})

        monkeypatch.setattr(un, "requests", SimpleNamespace(post=fake_post))
        monkeypatch.setenv("API_BASE_URL", "http://server")
        monkeypatch.setenv("SECRET_KEY", "key-123")

    def test_payload_and_headers(self, monkeypatch):
        captured = {}
        self._patch(monkeypatch, captured)

        result = un.upload_numeric_data("sess-1", "temperature", "20.5")

        assert result == {"ok": True}
        assert captured["url"] == "http://server/api/raw-data/upload-data"
        assert captured["headers"]["x-api-key"] == "key-123"
        assert captured["payload"] == {
            "session_id": "sess-1",
            "data_type": "environmental",
            "data_subtype": "temperature",
            "data_value": "20.5",
        }

    def test_soil_subtype_mapping(self, monkeypatch):
        captured = {}
        self._patch(monkeypatch, captured)
        un.upload_numeric_data("s", "ph", "6.8")
        assert captured["payload"]["data_type"] == "soil"

    def test_optional_fields_included_only_when_provided(self, monkeypatch):
        captured = {}
        self._patch(monkeypatch, captured)
        un.upload_numeric_data(
            "s", "moisture", "45.0",
            description="d", location_geom="POINT(1 2)",
            altitude_m=12.0, heading=90.0,
        )
        payload = captured["payload"]
        assert payload["description"] == "d"
        assert payload["location_geom"] == "POINT(1 2)"
        assert payload["altitude_m"] == 12.0
        assert payload["heading"] == 90.0

    def test_unsupported_subtype_raises(self):
        with pytest.raises(ValueError, match="不支持的 data_subtype"):
            un.upload_numeric_data("s", "unknown_type", "1")


# ============================================================
# upload_file_data
# ============================================================

class TestUploadFileData:
    def test_missing_file_raises(self):
        with pytest.raises(FileNotFoundError):
            uf.upload_file_data("/no/such/file.jpg", "sess", "rgb")

    def test_successful_upload(self, tmp_path, monkeypatch):
        file_path = tmp_path / "a.jpg"
        file_path.write_bytes(b"abc")
        captured = {}

        def fake_post(url, headers=None, files=None, data=None, **kwargs):
            captured.update(url=url, headers=headers, files=files, data=data)
            return DummyResponse(json_data={"ok": 1})

        monkeypatch.setattr(uf, "requests", SimpleNamespace(post=fake_post))
        monkeypatch.setenv("API_BASE_URL", "http://server")
        monkeypatch.setenv("SECRET_KEY", "key-abc")

        result = uf.upload_file_data(
            str(file_path), "sess-1", "rgb",
            description="desc", altitude_m=12.5,
        )

        assert result == {"ok": 1}
        assert captured["url"] == "http://server/api/raw-data/upload-file"
        assert captured["headers"]["x-api-key"] == "key-abc"
        assert captured["data"]["session_id"] == "sess-1"
        assert captured["data"]["data_subtype"] == "rgb"
        assert captured["data"]["description"] == "desc"
        assert captured["data"]["altitude_m"] == 12.5
        assert "location_geom" not in captured["data"]

        filename, content = captured["files"]["file"]
        assert filename == "a.jpg"
        assert content == b"abc"
