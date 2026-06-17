"""
数据模型模块 — 统一定义系统中使用的全部数据类型与模型。

子模块：
  - base         : 设备能力描述、采集结果容器
  - data_types   : DataType / DataSubType / DataUnit 枚举
  - records      : LocalDataRecord / LocalFileRecord / DataStore
  - state        : DeviceStatus / DeviceInfo / DeviceStateManager
"""

from .base import DeviceCapabilities, CaptureResult, CaptureBatch, DataCategory
from .data_types import DataType, DataSubType, DataUnit, SUBTYPE_UNIT_MAP
from .records import LocalDataRecord, LocalFileRecord, DataStore
from .state import (
    DeviceStatus,
    DeviceInfo,
    DeviceStateManager,
    get_device_state_manager,
)

__all__ = [
    # base
    "DeviceCapabilities",
    "CaptureResult",
    "CaptureBatch",
    "DataCategory",
    # data_types
    "DataType",
    "DataSubType",
    "DataUnit",
    "SUBTYPE_UNIT_MAP",
    # records
    "LocalDataRecord",
    "LocalFileRecord",
    "DataStore",
    # state
    "DeviceStatus",
    "DeviceInfo",
    "DeviceStateManager",
    "get_device_state_manager",
]
