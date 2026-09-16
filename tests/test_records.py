"""本地数据记录模型测试。"""
from datetime import datetime

from device.models.data_types import DataType, DataSubType
from device.models.records import LocalDataRecord, LocalFileRecord


def _numeric(session_id="sess-1", **overrides):
    data = dict(
        session_id=session_id,
        data_type=DataType.ENVIRONMENTAL,
        data_subtype=DataSubType.TEMPERATURE,
        data_value="22.5",
    )
    data.update(overrides)
    return LocalDataRecord(**data)


def _file(session_id="sess-1", **overrides):
    data = dict(
        session_id=session_id,
        data_subtype=DataSubType.RGB,
        local_path="/tmp/a.jpg",
        file_size_bytes=100,
    )
    data.update(overrides)
    return LocalFileRecord(**data)


# ============================================================
# 模型默认值
# ============================================================

class TestRecordModels:
    def test_numeric_defaults(self):
        rec = _numeric()
        assert rec.id
        assert rec.is_uploaded is False
        assert rec.is_valid is True
        assert isinstance(rec.capture_time, datetime)
        assert rec.upload_time is None
        assert rec.server_data_id is None

    def test_ids_are_unique(self):
        assert _numeric().id != _numeric().id

    def test_file_record_requires_size(self):
        rec = _file()
        assert rec.file_size_bytes == 100
        assert rec.is_uploaded is False
