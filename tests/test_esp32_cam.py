"""ESP32CameraDevice 硬件设备测试（mock 网络请求）。"""
import os
import socket
from importlib import import_module

import pytest
import requests

from device.hardware.esp32_cam import ESP32CameraDevice
from device.models.data_types import DataSubType

from _util import DummyResponse, FakeSocket

cam_mod = import_module("device.hardware.esp32_cam")


# ============================================================
# 能力声明
# ============================================================

def test_capabilities():
    cam = ESP32CameraDevice("192.168.1.10")
    caps = cam.get_capabilities()
    assert caps.supports_file is True
    assert caps.supports_numeric is False
    assert caps.is_virtual is False
    assert DataSubType.RGB.value in caps.file_subtypes
    assert DataSubType.NIR.value in caps.file_subtypes


def test_collect_numeric_returns_empty():
    cam = ESP32CameraDevice("192.168.1.10")
    assert cam.collect_numeric_data("sess") == []


def test_can_capture_file_data():
    assert ESP32CameraDevice("1.1.1.1").can_capture_file_data() is True


# ============================================================
# HTTP 交互
# ============================================================

class TestHttp:
    def test_capture_success(self, monkeypatch):
        cam = ESP32CameraDevice("1.2.3.4")
        monkeypatch.setattr(
            cam_mod.requests, "get",
            lambda *a, **k: DummyResponse(status_code=200, content=b"IMG"),
        )
        assert cam.capture() == b"IMG"

    def test_capture_non_200_returns_none(self, monkeypatch):
        cam = ESP32CameraDevice("1.2.3.4")
        monkeypatch.setattr(
            cam_mod.requests, "get",
            lambda *a, **k: DummyResponse(status_code=404),
        )
        assert cam.capture() is None

    def test_capture_network_error_returns_none(self, monkeypatch):
        cam = ESP32CameraDevice("1.2.3.4")

        def raiser(*a, **k):
            raise requests.exceptions.RequestException("boom")

        monkeypatch.setattr(cam_mod.requests, "get", raiser)
        assert cam.capture() is None

    def test_status_online(self, monkeypatch):
        cam = ESP32CameraDevice("1.2.3.4")
        monkeypatch.setattr(
            cam_mod.requests, "get",
            lambda *a, **k: DummyResponse(status_code=200, text="hello"),
        )
        status = cam.status()
        assert status["status"] == "online"
        assert status["ip"] == "1.2.3.4"

    def test_status_offline(self, monkeypatch):
        cam = ESP32CameraDevice("1.2.3.4")

        def raiser(*a, **k):
            raise requests.exceptions.RequestException("unreachable")

        monkeypatch.setattr(cam_mod.requests, "get", raiser)
        assert cam.status()["status"] == "offline"

    def test_get_stream_url(self):
        cam = ESP32CameraDevice("1.2.3.4", port=8080)
        assert cam.get_stream_url() == "http://1.2.3.4:8080/stream"


# ============================================================
# 在线检测
# ============================================================

class TestHealthCheck:
    def test_health_check_online(self, monkeypatch):
        cam = ESP32CameraDevice("10.0.0.6")
        monkeypatch.setattr(socket, "socket", lambda *a, **k: FakeSocket(0))
        monkeypatch.setattr(cam, "status", lambda timeout=None: {"status": "online"})
        assert cam.health_check() is True

    def test_health_check_tcp_closed(self, monkeypatch):
        cam = ESP32CameraDevice("10.0.0.6")
        monkeypatch.setattr(socket, "socket", lambda *a, **k: FakeSocket(1))
        assert cam.health_check() is False

    def test_health_check_http_offline(self, monkeypatch):
        cam = ESP32CameraDevice("10.0.0.6")
        monkeypatch.setattr(socket, "socket", lambda *a, **k: FakeSocket(0))
        monkeypatch.setattr(cam, "status", lambda timeout=None: {"status": "offline"})
        assert cam.health_check() is False

    def test_initialize_uses_health_check(self, monkeypatch):
        cam = ESP32CameraDevice("10.0.0.6")
        calls = {"n": 0}

        def fake_health():
            calls["n"] += 1
            return True

        monkeypatch.setattr(cam, "health_check", fake_health)
        assert cam.initialize() is True
        assert cam.initialize() is True  # 第二次短路，不再探测
        assert calls["n"] == 1


# ============================================================
# 文件采集
# ============================================================

class TestCaptureFileData:
    def test_saves_file_and_builds_record(self, monkeypatch):
        cam = ESP32CameraDevice("10.0.0.5")
        monkeypatch.setattr(cam, "capture", lambda timeout=None: b"JPEGBYTES")

        rec = cam.capture_file_data(
            "sess-1", DataSubType.RGB.value, altitude_m=5.0,
        )

        assert rec is not None
        assert rec.session_id == "sess-1"
        assert rec.local_path.endswith(".jpg")
        assert "10_0_0_5" in os.path.basename(rec.local_path)
        assert os.path.exists(rec.local_path)
        assert rec.file_size_bytes == len(b"JPEGBYTES")
        assert rec.altitude_m == 5.0
        assert cam.last_image_path == rec.local_path

    def test_returns_none_when_capture_fails(self, monkeypatch):
        cam = ESP32CameraDevice("10.0.0.5")
        monkeypatch.setattr(cam, "capture", lambda timeout=None: None)
        assert cam.capture_file_data("sess-1", DataSubType.RGB.value) is None

    def test_file_saved_under_session_dir(self, monkeypatch, tmp_path):
        cam = ESP32CameraDevice("10.0.0.5")
        monkeypatch.setattr(cam, "capture", lambda timeout=None: b"X")
        rec = cam.capture_file_data("my-session", DataSubType.RGB.value)
        expected_dir = os.path.join(str(tmp_path), "green_tracker_data", "my-session", "images")
        assert os.path.dirname(rec.local_path) == expected_dir
