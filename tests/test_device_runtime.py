"""device.runtime 测试 — 全局虚拟传感器单例。"""
import pytest

from device import runtime
from device.virtual import VirtualSensorDevice


@pytest.fixture(autouse=True)
def _always_reset():
    runtime.reset_data_sensor()
    yield
    runtime.reset_data_sensor()


def test_get_returns_none_before_init():
    assert runtime.get_data_sensor() is None


def test_init_starts_sensor():
    sensor = runtime.init_data_sensor(interval=0.05)
    assert isinstance(sensor, VirtualSensorDevice)
    assert sensor.running is True
    assert runtime.get_data_sensor() is sensor


def test_init_is_idempotent():
    first = runtime.init_data_sensor(interval=0.05)
    second = runtime.init_data_sensor(interval=0.05)
    assert second is first


def test_reset_stops_and_clears():
    sensor = runtime.init_data_sensor(interval=0.05)
    runtime.reset_data_sensor()
    assert runtime.get_data_sensor() is None
    assert sensor.running is False


def test_init_uses_config_default_interval(monkeypatch):
    monkeypatch.setenv("VIRTUAL_SENSOR_INTERVAL", "0.05")
    assert runtime.init_data_sensor().interval == 0.05


def test_explicit_interval_overrides_config(monkeypatch):
    monkeypatch.setenv("VIRTUAL_SENSOR_INTERVAL", "99")
    assert runtime.init_data_sensor(interval=0.05).interval == 0.05


def test_get_data_sensor_returns_none_after_reset_twice():
    runtime.reset_data_sensor()
    runtime.reset_data_sensor()
    assert runtime.get_data_sensor() is None
