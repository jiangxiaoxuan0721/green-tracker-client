"""AbstractBaseDevice 统一范式测试（生命周期 + collect 路由）。"""
import pytest

from device.base import AbstractBaseDevice
from device.models.base import DeviceCapabilities, DataCategory
from device.models.data_types import DataType, DataSubType
from device.models.records import LocalDataRecord, LocalFileRecord


class FakeDevice(AbstractBaseDevice):
    """可配置的测试用设备。"""

    def __init__(self, supports_numeric=True, supports_file=False,
                 numeric_result=None, numeric_error=None,
                 file_mode="record", initialize_ok=True, health=True):
        super().__init__()
        self.device_id = "fake-1"
        self.device_type = "FakeDevice"
        self._supports_numeric = supports_numeric
        self._supports_file = supports_file
        self._numeric_result = numeric_result
        self._numeric_error = numeric_error
        self._file_mode = file_mode          # "record" | "none" | "raise"
        self._initialize_ok = initialize_ok
        self._health = health
        self.init_calls = 0

    def get_capabilities(self):
        return DeviceCapabilities(
            device_type=self.device_type,
            supports_numeric=self._supports_numeric,
            supports_file=self._supports_file,
            numeric_categories=[DataCategory.ENVIRONMENTAL] if self._supports_numeric else [],
            file_subtypes=["rgb"] if self._supports_file else [],
        )

    def initialize(self):
        self.init_calls += 1
        self._initialized = self._initialize_ok
        return self._initialize_ok

    def health_check(self):
        return self._health

    def collect_numeric_data(self, session_id, location_geom=None,
                             altitude_m=None, heading=None):
        if self._numeric_error:
            raise RuntimeError(self._numeric_error)
        if self._numeric_result is not None:
            return self._numeric_result
        return [LocalDataRecord(
            session_id=session_id,
            data_type=DataType.ENVIRONMENTAL,
            data_subtype=DataSubType.TEMPERATURE,
            data_value="20",
        )]

    def can_capture_file_data(self):
        return self._supports_file

    def capture_file_data(self, session_id, data_subtype="rgb",
                          location_geom=None, altitude_m=None, heading=None):
        if self._file_mode == "raise":
            raise RuntimeError("capture failed")
        if self._file_mode == "none":
            return None
        return LocalFileRecord(
            session_id=session_id,
            data_subtype=DataSubType.RGB,
            local_path="/tmp/x.jpg",
            file_size_bytes=1,
        )


class MinimalDevice(AbstractBaseDevice):
    """仅实现抽象方法的设备，用于验证默认实现。"""

    def get_capabilities(self):
        return DeviceCapabilities(
            device_type="Minimal", supports_numeric=True, supports_file=False)

    def initialize(self):
        self._initialized = True
        return True

    def health_check(self):
        return True

    def collect_numeric_data(self, session_id, location_geom=None,
                             altitude_m=None, heading=None):
        return []


# ============================================================
# 抽象契约与默认实现
# ============================================================

def test_abstract_base_cannot_be_instantiated():
    with pytest.raises(TypeError):
        AbstractBaseDevice()  # type: ignore[abstract]


def test_default_file_capture_is_disabled():
    dev = MinimalDevice()
    assert dev.can_capture_file_data() is False
    # 默认实现直接返回 None（data_subtype 为必填参数）
    assert dev.capture_file_data("s", "rgb") is None


# ============================================================
# 生命周期
# ============================================================

class TestLifecycle:
    def test_start_initializes_when_needed(self):
        dev = FakeDevice()
        assert dev.start() is True
        assert dev.initialized is True
        assert dev.running is True
        assert dev.init_calls == 1
        # 再次 start 不会重复初始化
        dev.start()
        assert dev.init_calls == 1

    def test_start_fails_when_initialize_fails(self):
        dev = FakeDevice(initialize_ok=False)
        assert dev.start() is False
        assert dev.running is False

    def test_stop(self):
        dev = FakeDevice()
        dev.start()
        assert dev.stop() is True
        assert dev.running is False

    def test_reset(self):
        dev = FakeDevice()
        dev.start()
        assert dev.reset() is True
        assert dev.initialized is True
        assert dev.running is False

    def test_status_label_transitions(self):
        dev = FakeDevice()
        assert dev.status_label == "未初始化"
        dev.start()
        assert dev.status_label == "运行中"
        dev.stop()
        assert dev.status_label == "已停止"


# ============================================================
# collect 统一入口路由
# ============================================================

class TestCollectRouting:
    def test_numeric_success(self):
        dev = FakeDevice()
        batch = dev.collect(session_id="sess-1")
        assert batch.device_id == "fake-1"
        assert batch.total_count == 1
        assert batch.success_count == 1
        assert batch.has_errors is False
        assert batch.started_at and batch.finished_at

    def test_numeric_exception_is_wrapped(self):
        dev = FakeDevice(numeric_error="sensor boom")
        batch = dev.collect(session_id="sess-1")
        assert batch.error_count == 1
        assert batch.results[0].success is False
        assert "sensor boom" in batch.results[0].error

    def test_numeric_skipped_when_unsupported(self):
        dev = FakeDevice(supports_numeric=False)
        batch = dev.collect(session_id="sess-1")
        assert batch.total_count == 0

    def test_file_capture_success(self):
        dev = FakeDevice(supports_numeric=True, supports_file=True)
        batch = dev.collect(session_id="sess-1", file_subtype="rgb")
        types = [r.data_type for r in batch.results]
        assert "numeric" in types and "file" in types
        assert batch.success_count == 2

    def test_file_capture_returns_none_yields_error(self):
        dev = FakeDevice(supports_file=True, file_mode="none")
        batch = dev.collect(session_id="sess-1", file_subtype="rgb")
        # 数值 1 条成功 + 文件 1 条失败
        assert batch.total_count == 2
        assert batch.error_count == 1
        failed = [r for r in batch.results if not r.success]
        assert len(failed) == 1
        assert "文件采集返回空结果" in failed[0].error

    def test_file_capture_exception_is_wrapped(self):
        dev = FakeDevice(supports_file=True, file_mode="raise")
        batch = dev.collect(session_id="sess-1", file_subtype="rgb")
        assert batch.error_count == 1
        failed = [r for r in batch.results if not r.success]
        assert len(failed) == 1
        assert "capture failed" in failed[0].error

    def test_error_results_carry_no_data_type(self):
        """契约：CaptureResult.data_type 仅标识成功负载类型，失败时为 None。

        因此调用方不能靠 data_type 区分失败来源，需依赖 success 标志。
        """
        dev = FakeDevice(numeric_error="boom", supports_file=True, file_mode="raise")
        batch = dev.collect(session_id="sess-1", file_subtype="rgb")
        assert batch.error_count == 2
        assert all(r.data_type is None for r in batch.results if not r.success)

    def test_file_not_attempted_without_subtype(self):
        dev = FakeDevice(supports_file=True)
        batch = dev.collect(session_id="sess-1")
        assert all(r.data_type != "file" for r in batch.results)

    def test_file_not_attempted_when_unsupported(self):
        dev = FakeDevice(supports_numeric=True, supports_file=False)
        batch = dev.collect(session_id="sess-1", file_subtype="rgb")
        assert all(r.data_type != "file" for r in batch.results)


# ============================================================
# 内省
# ============================================================

def test_to_dict_and_repr():
    dev = FakeDevice(supports_file=True)
    info = dev.to_dict()
    assert info["device_id"] == "fake-1"
    assert info["device_type"] == "FakeDevice"
    assert info["capabilities"]["supports_numeric"] is True
    assert info["capabilities"]["supports_file"] is True
    assert info["capabilities"]["file_subtypes"] == ["rgb"]
    assert "is_virtual" in info
    assert "FakeDevice" in repr(dev)
