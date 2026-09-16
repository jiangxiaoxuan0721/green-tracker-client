"""storage.batch 测试 — 表头约定、表头修复、行计数与上传统计。"""
import json
import os

from device.models.data_types import DataSubType, DataType
from device.models.records import LocalDataRecord
from storage import paths
from storage.batch import (
    CSV_FIELDNAMES,
    CSV_HEADER,
    SessionStore,
    format_unit,
    is_uploaded,
    record_to_row,
)
from storage.upload_state import UploadState


def _store(tmp_path, session_id="sess-1"):
    return SessionStore(session_id, "测试任务", base_dir=str(tmp_path))


def _record(subtype=DataSubType.TEMPERATURE, value="22.5"):
    return LocalDataRecord(
        session_id="sess-1",
        data_type=DataType.ENVIRONMENTAL,
        data_subtype=subtype,
        data_value=value,
    )


# ============================================================
# 纯函数
# ============================================================

class TestHelpers:
    def test_format_unit_falls_back_to_dash(self):
        # LocalDataRecord 没有 unit 字段 → 恒为 "-"（与原实现语义一致）
        assert format_unit(None) == "-"
        assert format_unit("") == "-"
        assert format_unit("ppm") == "ppm"

    def test_format_unit_unwraps_enum_value(self):
        class _U:
            value = "\u00b0C"
        assert format_unit(_U()) == "\u00b0C"

    def test_is_uploaded_case_insensitive(self):
        assert is_uploaded("True") is True
        assert is_uploaded("true") is True
        assert is_uploaded(" False ") is False
        assert is_uploaded("") is False
        assert is_uploaded(None) is False

    def test_record_to_row_maps_fields(self):
        row = record_to_row(_record())
        assert row["sensor_id"] == "temperature"
        assert row["data_type"] == "environmental"
        assert row["value"] == "22.5"
        assert row["unit"] == "-"
        assert row["is_uploaded"] == "False"
        assert row["timestamp"]

    def test_record_to_row_accepts_explicit_timestamp(self):
        row = record_to_row(_record(), timestamp="2024-01-01T00:00:00")
        assert row["timestamp"] == "2024-01-01T00:00:00"


# ============================================================
# 会话初始化
# ============================================================

class TestEnsure:
    def test_creates_full_layout(self, tmp_path):
        store = _store(tmp_path)
        assert store.ensure() == store.data_dir

        assert os.path.isfile(store.csv_path)
        assert os.path.isdir(store.images_dir)
        assert os.path.isfile(store.meta_path)

        with open(store.csv_path, encoding="utf-8") as f:
            assert f.read().strip() == CSV_HEADER

    def test_meta_descriptor_content(self, tmp_path):
        store = _store(tmp_path)
        store.ensure()
        meta = store.read_meta()
        assert meta["session_id"] == "sess-1"
        assert meta["session_name"] == "测试任务"
        assert meta["end_time"] is None
        assert meta["created_at"]

    def test_idempotent(self, tmp_path):
        store = _store(tmp_path)
        store.ensure()
        store.append_numeric(_record())
        first_meta = store.read_meta()

        store.ensure()  # 再次调用不得清空数据或覆盖 meta

        assert len(store.read_rows()) == 1
        assert store.read_meta()["created_at"] == first_meta["created_at"]
        with open(store.csv_path, encoding="utf-8") as f:
            assert f.read().count(CSV_HEADER) == 1

    def test_finish_sets_end_time(self, tmp_path):
        store = _store(tmp_path)
        store.ensure()
        store.finish()
        assert store.read_meta()["end_time"]

    def test_finish_without_meta_is_noop(self, tmp_path):
        store = _store(tmp_path)
        store.finish()  # 不应抛异常
        assert store.read_meta() == {}


# ============================================================
# 写入
# ============================================================

class TestWrite:
    def test_append_numeric_then_read(self, tmp_path):
        store = _store(tmp_path)
        store.ensure()
        store.append_numeric(_record())
        store.append_numeric(_record(DataSubType.CO2, "410"))

        rows = store.read_rows()
        assert len(rows) == 2
        assert rows[0]["sensor_id"] == "temperature"
        assert rows[1]["sensor_id"] == "co2"
        assert rows[1]["value"] == "410"

    def test_append_rows_returns_count(self, tmp_path):
        store = _store(tmp_path)
        store.ensure()
        assert store.append_rows([]) == 0
        assert store.append_rows([{"timestamp": "t", "value": "1"}]) == 1

    def test_append_rows_fills_missing_columns(self, tmp_path):
        store = _store(tmp_path)
        store.ensure()
        store.append_rows([{"timestamp": "t1", "value": "9"}])
        row = store.read_rows()[0]
        assert set(row.keys()) == set(CSV_FIELDNAMES)
        assert row["sensor_id"] == ""

    def test_write_rows_rewrites_with_standard_header(self, tmp_path):
        store = _store(tmp_path)
        store.ensure()
        store.append_numeric(_record())
        rows = store.read_rows()
        rows[0]["is_uploaded"] = "True"
        store.write_rows(rows)

        with open(store.csv_path, encoding="utf-8") as f:
            assert f.readline().strip() == CSV_HEADER
        reread = store.read_rows()
        assert len(reread) == 1
        assert reread[0]["is_uploaded"] == "True"


# ============================================================
# 读取兼容性（沿用原 UploadWorker 的表头修复语义）
# ============================================================

class TestReadCompat:
    def test_missing_file_returns_empty(self, tmp_path):
        assert _store(tmp_path).read_rows() == []

    def test_empty_file_returns_empty(self, tmp_path):
        store = _store(tmp_path)
        os.makedirs(store.data_dir, exist_ok=True)
        open(store.csv_path, "w").close()
        assert store.read_rows() == []

    def test_standard_header(self, tmp_path):
        store = _store(tmp_path)
        os.makedirs(store.data_dir, exist_ok=True)
        with open(store.csv_path, "w", encoding="utf-8") as f:
            f.write(CSV_HEADER + "\n2024-01-01T00:00:00,temperature,environmental,22.5,-,False\n")
        rows = store.read_rows()
        assert len(rows) == 1
        assert rows[0]["sensor_id"] == "temperature"

    def test_repairs_missing_header(self, tmp_path):
        """首行是时间戳 → 无表头，套用 CSV_FIELDNAMES 解析。"""
        store = _store(tmp_path)
        os.makedirs(store.data_dir, exist_ok=True)
        with open(store.csv_path, "w", encoding="utf-8") as f:
            f.write("2024-01-01T00:00:00,temperature,environmental,22.5,-,False\n")
            f.write("2024-01-01T00:00:01,co2,environmental,410,-,False\n")
        rows = store.read_rows()
        assert len(rows) == 2
        assert rows[0]["value"] == "22.5"
        assert rows[1]["sensor_id"] == "co2"

    def test_skips_misread_header_row(self, tmp_path):
        """无表头文件里混入表头行时不得被当成数据。"""
        store = _store(tmp_path)
        os.makedirs(store.data_dir, exist_ok=True)
        with open(store.csv_path, "w", encoding="utf-8") as f:
            f.write("2024-01-01T00:00:00,temperature,environmental,22.5,-,False\n")
            f.write("timestamp,sensor_id,data_type,value,unit,is_uploaded\n")
        rows = store.read_rows()
        assert len(rows) == 1
        assert rows[0]["sensor_id"] == "temperature"

    def test_corrupt_file_returns_empty(self, tmp_path):
        """目录被当成文件等异常情况必须安全降级。"""
        store = _store(tmp_path)
        os.makedirs(store.csv_path, exist_ok=True)  # csv_path 是目录 → open 失败
        assert store.read_rows() == []


# ============================================================
# 图片与统计
# ============================================================

class TestImagesAndStats:
    def _touch(self, store, names):
        os.makedirs(store.images_dir, exist_ok=True)
        for n in names:
            with open(os.path.join(store.images_dir, n), "wb") as f:
                f.write(b"x")

    def test_list_images_filters_and_sorts(self, tmp_path):
        store = _store(tmp_path)
        self._touch(store, ["b.jpg", "a.PNG", "c.jpeg", "note.txt"])
        assert store.list_images() == ["a.PNG", "b.jpg", "c.jpeg"]

    def test_list_images_without_dir(self, tmp_path):
        assert _store(tmp_path).list_images() == []

    def test_stats_numeric_only(self, tmp_path):
        store = _store(tmp_path)
        store.ensure()
        store.append_numeric(_record())
        rows = store.read_rows()
        rows[0]["is_uploaded"] = "True"
        store.write_rows(rows)

        stats = store.stats()
        assert stats["numeric_total"] == 1
        assert stats["numeric_uploaded"] == 1
        assert stats["numeric_pending"] == 0
        assert stats["image_total"] == 0
        assert stats["pending_total"] == 0

    def test_stats_with_images_and_status(self, tmp_path):
        store = _store(tmp_path)
        store.ensure()
        store.append_numeric(_record())
        self._touch(store, ["a.jpg", "b.jpg"])

        state = UploadState("sess-1", base_dir=str(tmp_path))
        state.save(state.mark_uploaded("a.jpg"))

        stats = store.stats()
        assert stats["image_total"] == 2
        assert stats["image_uploaded"] == 1
        assert stats["image_pending"] == 1
        assert stats["numeric_pending"] == 1
        assert stats["pending_total"] == 2
        assert stats["uploaded_total"] == 1

    def test_stats_on_empty_session(self, tmp_path):
        stats = _store(tmp_path).stats()
        assert stats["pending_total"] == 0
        assert stats["numeric_total"] == 0


# ============================================================
# 与 storage.paths 的一致性
# ============================================================

def test_default_base_dir_is_data_root(tmp_path, monkeypatch):
    monkeypatch.delenv("GREEN_TRACKER_DATA_DIR", raising=False)
    monkeypatch.setenv("HOME", str(tmp_path))
    store = SessionStore("s1")
    assert store.base_dir == paths.data_root()
    assert store.data_dir == os.path.join(paths.data_root(), "s1")
    assert store.csv_path == paths.data_csv("s1")
    assert store.images_dir == paths.images_dir("s1")
    assert store.meta_path == paths.meta_json("s1")


def test_upload_state_path_matches_paths_module(tmp_path, monkeypatch):
    monkeypatch.delenv("GREEN_TRACKER_DATA_DIR", raising=False)
    monkeypatch.setenv("HOME", str(tmp_path))
    assert UploadState("s1").path == paths.images_status_json("s1")
    assert json.loads(json.dumps({})) == {}
