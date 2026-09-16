"""采集能力与结果容器（models.base）测试。"""
from device.models.base import (
    DataCategory,
    DeviceCapabilities,
    CaptureResult,
    CaptureBatch,
)


def _caps(**overrides):
    base = dict(
        device_type="TestDevice",
        supports_numeric=True,
        supports_file=False,
        numeric_categories=[DataCategory.ENVIRONMENTAL, DataCategory.SOIL],
        file_subtypes=[],
    )
    base.update(overrides)
    return DeviceCapabilities(**base)


def test_capabilities_can_collect():
    caps = _caps()
    assert caps.can_collect(DataCategory.ENVIRONMENTAL) is True
    assert caps.can_collect(DataCategory.SOIL) is True
    assert caps.can_collect(DataCategory.IMAGE) is False


def test_capabilities_can_collect_false_when_numeric_unsupported():
    caps = _caps(supports_numeric=False)
    assert caps.can_collect(DataCategory.ENVIRONMENTAL) is False


def test_capabilities_can_capture_image():
    assert _caps().can_capture_image() is False
    assert _caps(
        supports_file=True, file_subtypes=["rgb"]
    ).can_capture_image() is True


def test_capture_batch_counters_and_records():
    batch = CaptureBatch(device_id="dev-1", started_at="t0")
    assert batch.total_count == 0 and batch.success_count == 0

    batch.add_result(CaptureResult(success=True, data_type="numeric", record="r1"))
    batch.add_result(CaptureResult(success=False, error="boom"))

    assert batch.total_count == 2
    assert batch.success_count == 1
    assert batch.error_count == 1
    assert batch.has_errors is True
    # records 仅包含非 None 记录
    assert batch.records == ["r1"]


def test_capture_batch_has_no_errors_by_default():
    batch = CaptureBatch(device_id="dev-2")
    assert batch.has_errors is False
    assert batch.records == []
