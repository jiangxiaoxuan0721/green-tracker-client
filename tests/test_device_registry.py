"""device.registry 测试 — 设备可拓展性的契约。"""
import pytest

from device.hardware import DEVICE_TYPE_ESP32_CAM, ESP32CameraDevice
from device.models.state import DeviceInfo
from device.registry import DeviceRegistry, registry
from device.virtual import VIRTUAL_UNIT_ID, VIRTUAL_UNIT_TYPE, VirtualSensorDevice


@pytest.fixture
def fresh():
    """独立的注册表实例，避免污染全局注册表。"""
    return DeviceRegistry()


def _info(device_type, ip="10.0.0.1"):
    return DeviceInfo(ip=ip, device_type=device_type)


# ============================================================
# 内置设备
# ============================================================

class TestBuiltins:
    def test_builtin_types_are_registered(self):
        assert registry.is_registered(VIRTUAL_UNIT_TYPE)
        assert registry.is_registered(DEVICE_TYPE_ESP32_CAM)

    def test_known_types_are_sorted(self):
        assert registry.known_types() == sorted(
            [VIRTUAL_UNIT_TYPE, DEVICE_TYPE_ESP32_CAM]
        )

    def test_create_virtual_device(self):
        dev = registry.create(_info(VIRTUAL_UNIT_TYPE, VIRTUAL_UNIT_ID))
        assert isinstance(dev, VirtualSensorDevice)
        assert dev.is_virtual is True

    def test_create_esp32_cam_uses_device_ip(self):
        dev = registry.create(_info(DEVICE_TYPE_ESP32_CAM, "192.168.1.50"))
        assert isinstance(dev, ESP32CameraDevice)
        assert dev.ip == "192.168.1.50"
        assert dev.device_type == DEVICE_TYPE_ESP32_CAM


# ============================================================
# 未注册类型
# ============================================================

class TestUnknownTypes:
    def test_unregistered_type_returns_none(self):
        """替代原先 UI 里的 device_type 硬编码判断。"""
        assert registry.create(_info("Router")) is None

    def test_is_registered_false(self):
        assert registry.is_registered("Unknown Device") is False


# ============================================================
# 自定义注册（扩展点）
# ============================================================

class TestCustomRegistration:
    def test_register_then_create(self, fresh):
        fresh.register("test:custom", lambda info: ("made", info.ip))
        assert fresh.create(_info("test:custom", "1.1.1.1")) == ("made", "1.1.1.1")

    def test_register_overrides_existing(self, fresh):
        fresh.register("test:x", lambda info: "first")
        fresh.register("test:x", lambda info: "second")
        assert fresh.create(_info("test:x")) == "second"

    def test_empty_device_type_rejected(self, fresh):
        with pytest.raises(ValueError):
            fresh.register("", lambda info: None)

    def test_factory_exception_is_contained(self, fresh):
        """单个设备工厂异常不得向上抛出，否则会中断整轮采集。"""
        def boom(info):
            raise RuntimeError("boom")

        fresh.register("test:boom", boom)
        assert fresh.create(_info("test:boom")) is None

    def test_unregister(self, fresh):
        fresh.register("test:x", lambda info: None)
        fresh.unregister("test:x")
        assert fresh.is_registered("test:x") is False
        assert fresh.create(_info("test:x")) is None

    def test_unregister_missing_is_noop(self, fresh):
        fresh.unregister("never-registered")

    def test_contains_and_len(self, fresh):
        assert len(fresh) == 0
        fresh.register("test:x", lambda info: None)
        assert "test:x" in fresh
        assert len(fresh) == 1
