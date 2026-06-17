"""
执行器设备抽象基类 — 定义所有设备必须遵循的统一范式。

使用方式：
  class MyDevice(AbstractBaseDevice):
      def initialize(self) -> bool: ...
      def start(self) -> bool: ...
      ...

  device = MyDevice(device_id="xxx")
  device.initialize()
  device.start()
  batch = device.collect(session_id="...")    # 统一采集接口
  device.stop()

设计原则：
  - 所有设备（虚拟 / 真实硬件）共享同一套生命周期 + 数据采集接口
  - 上层调度器只依赖 AbstractBaseDevice 类型，不关心具体实现
  - 通过 DeviceCapabilities 声明能力，上层按能力分发任务
"""
from __future__ import annotations

import time
from abc import ABC, abstractmethod
from typing import Any, Dict, List, Optional

from .models.base import (
    DataCategory,
    DeviceCapabilities,
    CaptureResult,
    CaptureBatch,
)
from .models.records import LocalDataRecord, LocalFileRecord
from .models.state import DeviceStatus


class AbstractBaseDevice(ABC):
    """执行器设备抽象基类 — 虚拟设备和真实硬件设备的统一契约。

    子类只需实现带 @abstractmethod 的方法即可接入系统。
    可选覆写的方法有默认空实现。
    """

    # ---- 必须在子类中设置或通过 __init__ 赋值的属性 ----

    device_id: str = ""           # 设备唯一标识（IP 或自定义 ID）
    device_type: str = ""         # 设备类型名，如 "ESP32-CAM"、"VirtualSensor"
    is_virtual: bool = False      # 是否为虚拟设备

    # ---- 内部状态 ----

    _initialized: bool = False
    _running: bool = False

    # ================================================================
    # 抽象方法 — 子类必须实现
    # ================================================================

    @abstractmethod
    def get_capabilities(self) -> DeviceCapabilities:
        """返回设备能力描述。

        用于上层判断本设备能采集什么类型的数据。
        """
        ...

    @abstractmethod
    def initialize(self) -> bool:
        """初始化设备（建立连接、加载配置等）。

        Returns:
            True 初始化成功，False 失败
        """
        ...

    @abstractmethod
    def health_check(self) -> bool:
        """检查设备是否在线/可用（轻量级探测）。

        Returns:
            True 设备可用，False 不可用
        """
        ...

    # ================================================================
    # 数据采集 — 核心业务接口
    # ================================================================

    @abstractmethod
    def collect_numeric_data(
        self,
        session_id: str,
        location_geom: str | None = None,
        altitude_m: float | None = None,
        heading: float | None = None,
    ) -> List[LocalDataRecord]:
        """执行一次数值数据采集。

        Args:
            session_id:     所属会话 ID
            location_geom:  WKT 格式位置信息
            altitude_m:     采集高度（米）
            heading:        朝向（度）

        Returns:
            本次产生的 LocalDataRecord 列表（可能为空）
        """
        ...

    def can_capture_file_data(self) -> bool:
        """是否支持文件型数据采集（默认不支持）。子类可覆写。"""
        return False

    def capture_file_data(
        self,
        session_id: str,
        data_subtype: str,
        location_geom: str | None = None,
        altitude_m: float | None = None,
    ) -> Optional[LocalFileRecord]:
        """执行一次文件数据采集（默认返回 None）。

        仅当 can_capture_file_data() 返回 True 时才应调用此方法。

        Args:
            session_id:     所属会话 ID
            data_subtype:   文件子类型 (DataSubType 枚举值)
            location_geom:  WKT 格式位置信息
            altitude_m:     采集高度（米）

        Returns:
            LocalFileRecord 或 None
        """
        return None

    # ================================================================
    # 生命周期管理
    # ================================================================

    def start(self) -> bool:
        """启动设备进入工作状态（可覆写）。

        默认实现仅标记运行状态。对于需要后台循环的设备，
        应在此方法中启动线程/定时器。
        """
        if not self._initialized:
            if not self.initialize():
                return False
        self._running = True
        return True

    def stop(self) -> bool:
        """停止设备（可覆写）。"""
        self._running = False
        return True

    def reset(self) -> bool:
        """重置设备到初始状态（可覆写）。"""
        self.stop()
        self._initialized = False
        return self.initialize()

    # ================================================================
    # 统一采集入口 — 对外暴露的便捷方法
    # ================================================================

    def collect(
        self,
        session_id: str,
        location_geom: str | None = None,
        altitude_m: float | None = None,
        heading: float | None = None,
        file_subtype: str | None = None,
    ) -> CaptureBatch:
        """统一采集入口 — 按设备能力自动路由到对应采集方法。

        这是上层调度器调用的主入口。内部自动处理：
          - 数值数据采集 → collect_numeric_data()
          - 文件数据采集（可选）→ capture_file_data()
          - 错误捕获与包装为 CaptureBatch

        Args:
            session_id:     会话 ID
            location_geom:  位置信息
            altitude_m:     高度
            heading:        朝向
            file_subtype:   若指定且设备支持，额外触发一次文件采集

        Returns:
            CaptureBatch 包含所有结果
        """
        from datetime import datetime as _dt

        caps = self.get_capabilities()
        batch = CaptureBatch(
            device_id=self.device_id,
            started_at=_dt.utcnow().isoformat(),
        )

        # --- 数值采集 ---
        if caps.supports_numeric:
            try:
                records = self.collect_numeric_data(
                    session_id=session_id,
                    location_geom=location_geom,
                    altitude_m=altitude_m,
                    heading=heading,
                )
                for r in records:
                    batch.add_result(CaptureResult(
                        success=True, data_type="numeric", record=r))
            except Exception as e:
                batch.add_result(CaptureResult(
                    success=False, error=str(e)))

        # --- 文件采集（可选）---
        if file_subtype and caps.supports_file and self.can_capture_file_data():
            try:
                record = self.capture_file_data(
                    session_id=session_id,
                    data_subtype=file_subtype,
                    location_geom=location_geom,
                    altitude_m=altitude_m,
                )
                if record:
                    batch.add_result(CaptureResult(
                        success=True, data_type="file", record=record))
                else:
                    batch.add_result(CaptureResult(
                        success=False, error="文件采集返回空结果"))
            except Exception as e:
                batch.add_result(CaptureResult(
                    success=False, error=str(e)))

        batch.finished_at = _dt.utcnow().isoformat()
        return batch

    # ================================================================
    # 辅助与内省
    # ================================================================

    @property
    def initialized(self) -> bool:
        return self._initialized

    @property
    def running(self) -> bool:
        return self._running

    @property
    def status_label(self) -> str:
        if not self._initialized:
            return "未初始化"
        elif self._running:
            return "运行中"
        else:
            return "已停止"

    def __repr__(self) -> str:
        return (
            f"<{self.__class__.__name__} "
            f"id={self.device_id!r} type={self.device_type!r} "
            f"virtual={self.is_virtual} running={self._running}>"
        )

    def to_dict(self) -> Dict[str, Any]:
        """序列化为字典（用于 UI 展示 / JSON 导出）。"""
        caps = self.get_capabilities()
        return {
            "device_id": self.device_id,
            "device_type": self.device_type,
            "is_virtual": self.is_virtual,
            "status": self.status_label,
            "capabilities": {
                "supports_numeric": caps.supports_numeric,
                "supports_file": caps.supports_file,
                "categories": [c.value for c in caps.numeric_categories],
                "file_subtypes": caps.file_subtypes,
            },
        }


__all__ = ["AbstractBaseDevice"]
