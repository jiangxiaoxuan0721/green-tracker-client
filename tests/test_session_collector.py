"""device.collector 测试 — 采集引擎与 UI / 设备类型解耦的验证。

这些测试全程不导入 PyQt，证明采集逻辑已可从界面独立测试。
"""
import pytest

from device.collector import SessionCollector
from device.models.base import CaptureBatch, CaptureResult
from device.models.data_types import DataSubType, DataType
from device.models.records import LocalDataRecord, LocalFileRecord
from device.models.state import DeviceInfo
from device.registry import registry
from device.virtual import VIRTUAL_UNIT_ID, VIRTUAL_UNIT_TYPE
from storage.batch import SessionStore


# ============================================================
# 测试替身
# ============================================================

class _StubStateManager:
    """只实现 collector 依赖的 get_session_devices。"""

    def __init__(self, devices):
        self._devices = list(devices)

    def get_session_devices(self, session_id):
        return list(self._devices)


class _FakeDevice:
    """只实现 collector 依赖的 collect() 多态接口。"""

    last_file_subtype = "__unset__"

    def __init__(self, records=None, raises=False):
        self._records = records or []
        self._raises = raises

    def collect(self, session_id, file_subtype=None):
        if self._raises:
            raise RuntimeError("设备采集失败")
        _FakeDevice.last_file_subtype = file_subtype
        batch = CaptureBatch(device_id="fake")
        for r in self._records:
            batch.add_result(CaptureResult(success=True, data_type="x", record=r))
        return batch


def _num_record(session_id="s1"):
    return LocalDataRecord(
        session_id=session_id,
        data_type=DataType.ENVIRONMENTAL,
        data_subtype=DataSubType.TEMPERATURE,
        data_value="22.5",
    )


def _file_record(session_id="s1"):
    return LocalFileRecord(
        session_id=session_id,
        data_subtype=DataSubType.RGB,
        local_path="/tmp/a.jpg",
        file_size_bytes=10,
    )


FAKE_TYPE = "test:fake"


@pytest.fixture
def fake_device(monkeypatch):
    """注册一个可控的假设备类型，测后自动清理。"""
    holder = {"device": _FakeDevice()}
    registry.register(FAKE_TYPE, lambda info: holder["device"])

    def set_device(device):
        holder["device"] = device

    yield set_device
    registry.unregister(FAKE_TYPE)


def _make(tmp_path, devices, **kwargs):
    store = SessionStore("s1", "测试任务", base_dir=str(tmp_path))
    return SessionCollector(
        "s1", "测试任务",
        store=store,
        state_manager=_StubStateManager(devices),
        **kwargs,
    )


def _info(device_type, ip="10.0.0.1"):
    return DeviceInfo(ip=ip, device_type=device_type)


# ============================================================
# 初始化
# ============================================================

class TestPrepare:
    def test_prepare_creates_session_layout(self, tmp_path):
        collector = _make(tmp_path, [])
        data_dir = collector.prepare()

        assert collector.store.data_dir == data_dir
        assert collector.store.read_rows() == []
        assert collector.store.read_meta()["session_id"] == "s1"


# ============================================================
# 单轮采集
# ============================================================

class TestCollectOnce:
    def test_no_devices_yields_zero(self, tmp_path):
        assert _make(tmp_path, []).collect_once() == 0

    def test_unregistered_device_is_skipped(self, tmp_path):
        """未注册类型必须被安全跳过，而不是抛错或误采。"""
        collector = _make(tmp_path, [_info("Router")])
        assert collector.collect_once() == 0
        assert collector.store.read_rows() == []

    def test_numeric_records_are_persisted(self, tmp_path, fake_device):
        fake_device(_FakeDevice([_num_record()]))
        collector = _make(tmp_path, [_info(FAKE_TYPE)])

        assert collector.collect_once() == 1
        rows = collector.store.read_rows()
        assert len(rows) == 1
        assert rows[0]["sensor_id"] == "temperature"
        assert rows[0]["value"] == "22.5"

    def test_file_records_are_counted_but_not_written_to_csv(self, tmp_path, fake_device):
        fake_device(_FakeDevice([_file_record()]))
        collector = _make(tmp_path, [_info(FAKE_TYPE)])

        assert collector.collect_once() == 1
        assert collector.store.read_rows() == []

    def test_multiple_records_in_one_batch(self, tmp_path, fake_device):
        fake_device(_FakeDevice([_num_record(), _num_record(), _file_record()]))
        collector = _make(tmp_path, [_info(FAKE_TYPE)])

        assert collector.collect_once() == 3
        assert len(collector.store.read_rows()) == 2

    def test_multiple_devices_are_all_collected(self, tmp_path, fake_device):
        fake_device(_FakeDevice([_num_record()]))
        collector = _make(
            tmp_path,
            [_info(VIRTUAL_UNIT_TYPE, VIRTUAL_UNIT_ID), _info(FAKE_TYPE)],
        )

        # 虚拟传感器每次生成 1 条；假设备每次 1 条
        assert collector.collect_once() == 2
        assert len(collector.store.read_rows()) == 2

    def test_file_subtype_is_forwarded(self, tmp_path, fake_device):
        fake_device(_FakeDevice([]))
        collector = _make(
            tmp_path, [_info(FAKE_TYPE)], file_subtype=DataSubType.THERMAL
        )
        collector.collect_once()
        assert _FakeDevice.last_file_subtype == DataSubType.THERMAL

    def test_file_subtype_none_disables_file_capture(self, tmp_path, fake_device):
        fake_device(_FakeDevice([]))
        collector = _make(tmp_path, [_info(FAKE_TYPE)], file_subtype=None)
        collector.collect_once()
        assert _FakeDevice.last_file_subtype is None

    def test_repeated_calls_accumulate(self, tmp_path, fake_device):
        fake_device(_FakeDevice([_num_record()]))
        collector = _make(tmp_path, [_info(FAKE_TYPE)])

        collector.collect_once()
        collector.collect_once()
        assert len(collector.store.read_rows()) == 2

    def test_builtin_virtual_device_end_to_end(self, tmp_path):
        """使用真实注册表中的内置虚拟设备，不借助任何替身。"""
        collector = _make(tmp_path, [_info(VIRTUAL_UNIT_TYPE, VIRTUAL_UNIT_ID)])
        assert collector.collect_once() == 1

        row = collector.store.read_rows()[0]
        assert row["sensor_id"]
        assert row["data_type"] in ("environmental", "soil")


# ============================================================
# 采集循环
# ============================================================

class TestRunLoop:
    def test_exits_immediately_when_should_continue_false(self, tmp_path):
        collector = _make(tmp_path, [])
        collector.run(lambda: False, interval=0)
        assert collector.store.read_rows() == []

    def test_runs_until_flagged_to_stop(self, tmp_path, fake_device):
        fake_device(_FakeDevice([_num_record()]))
        collector = _make(tmp_path, [_info(FAKE_TYPE)])

        flag = {"run": True}
        rounds = []

        def on_round(total, count):
            rounds.append((total, count))
            if len(rounds) >= 2:
                flag["run"] = False

        collector.run(lambda: flag["run"], interval=0, on_round=on_round)

        assert rounds == [(1, 1), (2, 1)]
        assert len(collector.store.read_rows()) == 2

    def test_device_error_does_not_break_the_loop(self, tmp_path, fake_device):
        fake_device(_FakeDevice(raises=True))
        collector = _make(tmp_path, [_info(FAKE_TYPE)])

        flag = {"run": True}
        rounds = []

        def on_round(total, count):
            rounds.append(total)
            flag["run"] = False

        # 设备抛错时 run 内部应吞掉异常并继续
        collector.run(lambda: flag["run"], interval=0, on_round=on_round)
        assert rounds == [0]
