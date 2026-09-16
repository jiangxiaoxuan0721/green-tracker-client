"""
虚拟传感器设备 — 基于 AbstractBaseDevice 的虚拟执行单元实现。

继承统一抽象范式，可通过 AbstractBaseDevice 接口被上层调度器
（如 device.collector.SessionCollector）无差别调用。
"""
import random
import threading
import time
from datetime import datetime, timezone
from typing import List, Optional, Dict, Any

from ..base import AbstractBaseDevice
from ..models.base import (
    DeviceCapabilities,
    DataCategory,
)
from ..models.data_types import DataType, DataSubType, DataUnit
from ..models.records import LocalDataRecord
from ..models.state import DeviceStatus, get_device_state_manager


# 常量
VIRTUAL_UNIT_ID = "virtual:datagenerator"
VIRTUAL_UNIT_TYPE = "VirtualSensor (虚拟传感器)"


class VirtualSensorDevice(AbstractBaseDevice):
    """虚拟传感器设备 — 后台线程持续生成模拟环境/土壤数据。"""

    ENV_RANGES: Dict[DataSubType, tuple] = {
        DataSubType.TEMPERATURE: (15.0, 35.0),
        DataSubType.HUMIDITY: (30.0, 90.0),
        DataSubType.CO2: (300.0, 800.0),
        DataSubType.LIGHT: (100.0, 50000.0),
        DataSubType.PRESSURE: (990.0, 1030.0),
    }

    SOIL_RANGES: Dict[DataSubType, tuple] = {
        DataSubType.MOISTURE: (20.0, 80.0),
        DataSubType.PH: (5.0, 8.5),
        DataSubType.EC: (100.0, 2000.0),
        DataSubType.TEMPERATURE_SOIL: (10.0, 30.0),
    }

    def __init__(self, interval: float = 5.0):
        super().__init__()
        self.device_id = VIRTUAL_UNIT_ID
        self.device_type = VIRTUAL_UNIT_TYPE
        self.is_virtual = True

        self.interval = interval
        self.latest_data: Optional[Dict[str, Any]] = None
        self._lock = threading.Lock()
        self._thread: Optional[threading.Thread] = None
        self._stop_event = threading.Event()
        self._generate_count = 0

        # 默认位置
        self.location_geom = "POINT(116.397428 39.90923)"
        self.altitude_m = 100.0
        self.heading = 0.0

        # 自动注册到状态管理器
        self._register_self()

    # -----------------------------------------------------------------
    # AbstractBaseDevice 实现
    # -----------------------------------------------------------------

    def get_capabilities(self) -> DeviceCapabilities:
        return DeviceCapabilities(
            device_type=self.device_type,
            supports_numeric=True,
            supports_file=False,
            numeric_categories=[DataCategory.ENVIRONMENTAL, DataCategory.SOIL],
            file_subtypes=[],
            is_virtual=True,
            description="模拟环境+土壤传感器数据生成器",
        )

    def initialize(self) -> bool:
        if self._initialized:
            return True
        self._initialized = True
        self._register_self()
        return True

    def health_check(self) -> bool:
        return self._initialized and self._running

    def collect_numeric_data(
        self,
        session_id: str,
        location_geom: Optional[str] = None,
        altitude_m: Optional[float] = None,
        heading: Optional[float] = None,
    ) -> List[LocalDataRecord]:
        """生成一条随机模拟传感器记录（每次只生成 1 条）。

        从环境/土壤共 9 个子类型中随机选取一个，模拟真实传感器
        按独立频率上报数据的场景。
        """
        now = datetime.now(timezone.utc)
        loc = location_geom or self.location_geom
        alt = altitude_m if altitude_m is not None else self.altitude_m
        hdg = heading if heading is not None else self.heading

        # 合并所有子类型及其范围与所属大类
        all_types: List[tuple] = []
        for st, rng in self.ENV_RANGES.items():
            all_types.append((st, DataType.ENVIRONMENTAL, rng))
        for st, rng in self.SOIL_RANGES.items():
            all_types.append((st, DataType.SOIL, rng))

        # 随机选取 1 个子类型
        subtype, data_type, (lo, hi) = random.choice(all_types)
        value = round(random.uniform(lo, hi), 2)

        record = LocalDataRecord(  # type: ignore[call-arg]
            session_id=session_id,
            data_type=data_type,
            data_subtype=subtype,
            data_value=str(value),
            capture_time=now,
            location_geom=loc,
            altitude_m=alt,
            heading=hdg,
            sensor_meta={"source": "virtual", "range": f"{lo}-{hi}"},
        )

        with self._lock:
            self.latest_data = {subtype.value: str(value)}
            self._generate_count += 1

        return [record]

    def can_capture_file_data(self) -> bool:
        return False

    # -----------------------------------------------------------------
    # 生命周期覆写 — 加入后台生成线程
    # -----------------------------------------------------------------

    def start(self) -> bool:
        if not super().start():
            return False
        if self._thread and self._thread.is_alive():
            return True
        self._thread = threading.Thread(target=self._bg_loop, daemon=True, name="VirtualSensor")
        self._thread.start()
        return True

    def stop(self) -> bool:
        self._running = False
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=5)
        super().stop()
        return True

    # -----------------------------------------------------------------
    # 内部方法
    # -----------------------------------------------------------------

    def _bg_loop(self):
        """后台生成循环（保持 latest_data 更新）。"""
        while self._running:
            try:
                self.collect_numeric_data(session_id="_background_")
            except Exception:
                pass
            # 通过 Event.wait 既能正常退避 interval，又能在 stop() 调用时
            # 被 set() 立刻唤醒，避免被 join(timeout=...) 长时间阻塞。
            if self._stop_event.wait(self.interval):
                return

    def _register_self(self):
        """注册到 DeviceStateManager。"""
        try:
            mgr = get_device_state_manager()
            mgr.register_virtual_unit(VIRTUAL_UNIT_ID, VIRTUAL_UNIT_TYPE)
        except Exception:
            pass

    def ensure_registered(self):
        """外部调用确保已注册。"""
        self._register_self()

    @property
    def generate_count(self) -> int:
        with self._lock:
            return self._generate_count

    def get_latest_data(self) -> Optional[Dict[str, Any]]:
        with self._lock:
            return dict(self.latest_data) if self.latest_data else None
