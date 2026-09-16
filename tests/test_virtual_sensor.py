"""VirtualSensorDevice 虚拟传感器测试。"""
from device.virtual.sensor_simulator import (
    VirtualSensorDevice,
    VIRTUAL_UNIT_ID,
    VIRTUAL_UNIT_TYPE,
)
from device.models.base import DataCategory
from device.models.data_types import DataType, DataSubType


def test_identity_and_capabilities():
    dev = VirtualSensorDevice()
    assert dev.device_id == VIRTUAL_UNIT_ID
    assert dev.device_type == VIRTUAL_UNIT_TYPE
    assert dev.is_virtual is True

    caps = dev.get_capabilities()
    assert caps.supports_numeric is True
    assert caps.supports_file is False
    assert DataCategory.ENVIRONMENTAL in caps.numeric_categories
    assert DataCategory.SOIL in caps.numeric_categories


def test_collect_numeric_data_produces_valid_record():
    dev = VirtualSensorDevice()
    records = dev.collect_numeric_data(session_id="sess-1")
    assert len(records) == 1

    rec = records[0]
    assert rec.session_id == "sess-1"
    assert rec.data_type in (DataType.ENVIRONMENTAL, DataType.SOIL)
    assert rec.sensor_meta["source"] == "virtual"

    # 数值必须落在该子类型对应的范围内
    ranges = {**VirtualSensorDevice.ENV_RANGES, **VirtualSensorDevice.SOIL_RANGES}
    assert rec.data_subtype in ranges
    low, high = ranges[rec.data_subtype]
    assert low <= float(rec.data_value) <= high


def test_collect_applies_location_overrides():
    dev = VirtualSensorDevice()
    rec = dev.collect_numeric_data(
        session_id="s", location_geom="POINT(1 1)",
        altitude_m=42.0, heading=180.0,
    )[0]
    assert rec.location_geom == "POINT(1 1)"
    assert rec.altitude_m == 42.0
    assert rec.heading == 180.0


def test_generate_count_and_latest_data():
    dev = VirtualSensorDevice()
    assert dev.generate_count == 0
    assert dev.get_latest_data() is None

    dev.collect_numeric_data(session_id="s")
    assert dev.generate_count == 1
    latest = dev.get_latest_data()
    assert isinstance(latest, dict) and len(latest) == 1


def test_collect_through_base_entry():
    dev = VirtualSensorDevice()
    batch = dev.collect(session_id="sess-1")
    assert batch.success_count == 1
    assert batch.records  # 非空


def test_start_stop_lifecycle():
    dev = VirtualSensorDevice(interval=0.05)
    try:
        assert dev.start() is True
        assert dev.running is True
        assert dev.health_check() is True
    finally:
        assert dev.stop() is True
    assert dev.running is False
    assert dev._thread is None or not dev._thread.is_alive()


def test_health_check_before_start():
    dev = VirtualSensorDevice()
    assert dev.health_check() is False
