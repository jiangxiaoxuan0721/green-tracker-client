"""DeviceStateManager 设备状态管理测试（内存缓存 + JSON 持久化）。"""
import socket
from datetime import datetime, timedelta

import pytest

import device.models.state as state_mod
from device.models.state import (
    DeviceStatus,
    DeviceInfo,
    DeviceStateManager,
    get_device_state_manager,
)

from _util import FakeSocket


@pytest.fixture
def mgr():
    return DeviceStateManager()


# ============================================================
# 注册与查询
# ============================================================

class TestRegistration:
    def test_register_new_device(self, mgr):
        mgr.register_device("192.168.1.10", "ESP32-CAM", mac="aa:bb", hostname="cam1")
        dev = mgr.get_device("192.168.1.10")
        assert isinstance(dev, DeviceInfo)
        assert dev.device_type == "ESP32-CAM"
        assert dev.mac == "aa:bb"
        assert dev.hostname == "cam1"
        assert dev.status == DeviceStatus.IDLE
        assert dev.assigned_session_id is None

    def test_register_existing_device_updates_fields(self, mgr):
        mgr.register_device("192.168.1.10", "ESP32-CAM")
        mgr.register_device("192.168.1.10", "ESP32-CAM-v2", hostname="cam2")
        dev = mgr.get_device("192.168.1.10")
        assert dev.device_type == "ESP32-CAM-v2"
        assert dev.hostname == "cam2"

    def test_register_virtual_unit(self, mgr):
        mgr.register_virtual_unit("virtual:1", "VirtualSensor", hostname="v1")
        dev = mgr.get_device("virtual:1")
        assert dev.is_virtual is True
        assert dev.status == DeviceStatus.IDLE

    def test_get_all_devices_with_filter(self, mgr):
        mgr.register_device("10.0.0.1", "ESP32-CAM")
        mgr.register_device("10.0.0.2", "ESP32-CAM")
        mgr.assign_device_to_session("10.0.0.2", "sess-1", "任务")

        assert len(mgr.get_all_devices()) == 2
        assigned = mgr.get_all_devices(status_filter=DeviceStatus.ASSIGNED)
        assert [d.ip for d in assigned] == ["10.0.0.2"]

    def test_get_unknown_device_returns_none(self, mgr):
        assert mgr.get_device("0.0.0.0") is None


# ============================================================
# 分配 / 取消分配
# ============================================================

class TestAssignment:
    def test_assign_success(self, mgr):
        mgr.register_device("10.0.0.1", "ESP32-CAM")
        assert mgr.assign_device_to_session("10.0.0.1", "sess-1", "任务A") is True

        dev = mgr.get_device("10.0.0.1")
        assert dev.status == DeviceStatus.ASSIGNED
        assert dev.assigned_session_id == "sess-1"
        assert [d.ip for d in mgr.get_session_devices("sess-1")] == ["10.0.0.1"]

    def test_assign_unknown_device_fails(self, mgr):
        assert mgr.assign_device_to_session("9.9.9.9", "s", "n") is False

    def test_assign_busy_device_fails(self, mgr):
        mgr.register_device("10.0.0.1", "ESP32-CAM")
        mgr.set_session_status("sess-1", "running")  # 无设备，无副作用
        mgr.assign_device_to_session("10.0.0.1", "sess-1", "任务A")
        mgr.set_session_status("sess-1", "running")

        assert mgr.get_device("10.0.0.1").status == DeviceStatus.BUSY
        assert mgr.assign_device_to_session("10.0.0.1", "sess-2", "任务B") is False

    def test_unassign_device(self, mgr):
        mgr.register_device("10.0.0.1", "ESP32-CAM")
        mgr.assign_device_to_session("10.0.0.1", "sess-1", "任务A")

        assert mgr.unassign_device("10.0.0.1") is True
        dev = mgr.get_device("10.0.0.1")
        assert dev.status == DeviceStatus.IDLE
        assert dev.assigned_session_id is None
        assert mgr.get_session_devices("sess-1") == []

    def test_unassign_unknown_device_fails(self, mgr):
        assert mgr.unassign_device("9.9.9.9") is False


# ============================================================
# 会话状态
# ============================================================

class TestSessionStatus:
    def test_running_marks_devices_busy(self, mgr):
        mgr.register_device("10.0.0.1", "ESP32-CAM")
        mgr.assign_device_to_session("10.0.0.1", "sess-1", "任务A")

        mgr.set_session_status("sess-1", "running")
        assert mgr.get_device("10.0.0.1").status == DeviceStatus.BUSY

    def test_stopped_releases_devices(self, mgr):
        mgr.register_device("10.0.0.1", "ESP32-CAM")
        mgr.assign_device_to_session("10.0.0.1", "sess-1", "任务A")
        mgr.set_session_status("sess-1", "running")

        mgr.set_session_status("sess-1", "stopped")
        dev = mgr.get_device("10.0.0.1")
        assert dev.status == DeviceStatus.IDLE
        assert dev.assigned_session_id is None
        assert mgr.get_session_devices("sess-1") == []

    def test_get_session_devices_unknown_returns_empty(self, mgr):
        assert mgr.get_session_devices("nope") == []


# ============================================================
# 在线检测与清理
# ============================================================

class TestHealthAndCleanup:
    def test_mark_offline_devices(self, mgr):
        mgr.register_device("10.0.0.1", "ESP32-CAM")
        # 将 last_seen 改为过期
        data = mgr._load_data()
        old = (datetime.now() - timedelta(seconds=120)).isoformat()
        data["devices"]["10.0.0.1"]["last_seen"] = old
        mgr._save_data(data)

        assert mgr.mark_offline_devices(timeout_seconds=90) == 1
        assert mgr.get_device("10.0.0.1").status == DeviceStatus.OFFLINE

    def test_mark_offline_skips_virtual(self, mgr):
        mgr.register_virtual_unit("virtual:1", "VirtualSensor")
        assert mgr.mark_offline_devices(timeout_seconds=0) == 0
        assert mgr.get_device("virtual:1").status != DeviceStatus.OFFLINE

    def test_cleanup_stale_devices(self, mgr):
        mgr.register_device("10.0.0.1", "ESP32-CAM")
        mgr.register_virtual_unit("virtual:1", "VirtualSensor")

        data = mgr._load_data()
        old = (datetime.now() - timedelta(hours=48)).isoformat()
        data["devices"]["10.0.0.1"]["last_seen"] = old
        mgr._save_data(data)

        removed = mgr.cleanup_stale_devices(offline_threshold_hours=24)
        assert removed == 1
        assert mgr.get_device("10.0.0.1") is None
        # 虚拟设备不受影响
        assert mgr.get_device("virtual:1") is not None

    def test_health_check_all_ignores_virtual(self, mgr):
        mgr.register_virtual_unit("virtual:1", "VirtualSensor")
        assert mgr.health_check_all() == {}

    def test_health_check_all_tcp_probe(self, mgr, monkeypatch):
        mgr.register_device("10.0.0.1", "ESP32-CAM")
        monkeypatch.setattr(socket, "socket", lambda *a, **k: FakeSocket(0))
        assert mgr.health_check_all() == {"10.0.0.1": True}

        monkeypatch.setattr(socket, "socket", lambda *a, **k: FakeSocket(1))
        assert mgr.health_check_all() == {"10.0.0.1": False}


# ============================================================
# 单例
# ============================================================

def test_get_device_state_manager_singleton():
    first = get_device_state_manager()
    second = get_device_state_manager()
    assert first is second
    assert isinstance(first, DeviceStateManager)


def test_persistence_round_trip(tmp_path):
    dir_a = tmp_path / "store"
    mgr_a = DeviceStateManager(str(dir_a))
    mgr_a.register_device("10.1.1.1", "ESP32-CAM")

    mgr_b = DeviceStateManager(str(dir_a))
    assert mgr_b.get_device("10.1.1.1") is not None
