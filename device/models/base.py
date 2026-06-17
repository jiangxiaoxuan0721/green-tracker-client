"""
设备能力与采集结果 — 抽象层通用数据结构。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import List, Optional, Any


class DataCategory(str, Enum):
    """数据大类（用于声明设备支持的数据类别）"""
    ENVIRONMENTAL = "environmental"
    SOIL = "soil"
    IMAGE = "image"
    VIDEO = "video"
    CUSTOM = "custom"


@dataclass
class DeviceCapabilities:
    """设备能力描述 — 声明本设备能做什么。

    每个 AbstractBaseDevice 子类通过 get_capabilities() 返回此对象，
    让上层调度器无需知道具体类型即可判断设备能力。
    """
    device_type: str                                    # 设备类型名称，如 "ESP32-CAM"、"VirtualSensor"
    supports_numeric: bool                              # 是否能采集数值型数据
    supports_file: bool                                 # 是否能采集文件型数据（图片/视频等）
    numeric_categories: List[DataCategory] = field(default_factory=list)  # 支持的数值类别
    file_subtypes: List[str] = field(default_factory=list)                # 支持的文件子类型名
    is_virtual: bool = False                            # 是否为虚拟设备
    description: str = ""                               # 可读描述

    # ---- 便捷查询 ----

    def can_collect(self, category: DataCategory) -> bool:
        return self.supports_numeric and category in self.numeric_categories

    def can_capture_image(self) -> bool:
        return self.supports_file and len(self.file_subtypes) > 0


@dataclass
class CaptureResult:
    """单次采集结果 — 数值或文件的统一包装。"""
    success: bool
    data_type: Optional[str] = None           # "numeric" | "file" | None(失败时)
    record: Optional[Any] = None              # LocalDataRecord | LocalFileRecord
    error: Optional[str] = None
    timestamp: Optional[str] = None           # ISO8601


@dataclass
class CaptureBatch:
    """批量采集结果 — 一次 collect() 调用可能产生多条记录。"""
    device_id: str
    results: List[CaptureResult] = field(default_factory=list)
    started_at: Optional[str] = None          # ISO8601
    finished_at: Optional[str] = None         # ISO8601
    total_count: int = 0
    success_count: int = 0
    error_count: int = 0

    def add_result(self, result: CaptureResult):
        self.results.append(result)
        self.total_count += 1
        if result.success:
            self.success_count += 1
        else:
            self.error_count += 1

    @property
    def has_errors(self) -> bool:
        return self.error_count > 0

    @property
    def records(self) -> list:
        return [r.record for r in self.results if r.record is not None]


__all__ = [
    "DataCategory",
    "DeviceCapabilities",
    "CaptureResult",
    "CaptureBatch",
]
