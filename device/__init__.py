"""
设备模块 — 执行器设备的抽象体系与具体实现。

目录结构：
  device/
  ├── base.py              # AbstractBaseDevice 抽象基类（统一范式）
  ├── models/               # 数据类型 & 模型定义
  │   ├── base.py          # DeviceCapabilities / CaptureResult / CaptureBatch
  │   ├── data_types.py    # DataType / DataSubType / DataUnit
  │   ├── records.py       # LocalDataRecord / LocalFileRecord / DataStore
  │   └── state.py         # DeviceStatus / DeviceInfo / DeviceStateManager
  ├── virtual/             # 虚拟设备实现
  │   └── sensor_simulator.py  # VirtualSensorDevice
  ├── hardware/            # 真实硬件设备实现
  │   └── esp32_cam.py     # ESP32CameraDevice
  ├── device_scanner.py    # 局域网设备扫描器
  └── task_manager.py      # 任务管理器

使用范式：
  from device.base import AbstractBaseDevice
  from device.virtual import VirtualSensorDevice
  from device.hardware import ESP32CameraDevice

  device: AbstractBaseDevice = VirtualSensorDevice()
  device.initialize()
  device.start()
  batch = device.collect(session_id="...")
"""

# ============================================================
# 抽象基类
# ============================================================
from .base import AbstractBaseDevice

# ============================================================
# 模型层
# ============================================================
from .models import (
    DataType,
    DataSubType,
    DataUnit,
    SUBTYPE_UNIT_MAP,
    LocalDataRecord,
    LocalFileRecord,
    DataStore,
    DeviceStatus,
    DeviceInfo,
    DeviceStateManager,
    get_device_state_manager,
    DeviceCapabilities,
    CaptureResult,
    CaptureBatch,
    DataCategory,
)

# ============================================================
# 具体设备实现
# ============================================================
from .virtual import VirtualSensorDevice, VIRTUAL_UNIT_ID, VIRTUAL_UNIT_TYPE
from .hardware import ESP32CameraDevice

# 向后兼容别名（旧名称映射到新实现）
# ============================================================
DataGenerator = VirtualSensorDevice          # 旧 simu_sensor.DataGenerator → VirtualSensorDevice
ESP32CAM = ESP32CameraDevice                 # 旧 esp32_cam.ESP32CAM → ESP32CameraDevice

# ============================================================
# 工具模块
# ============================================================
from .device_scanner import DeviceScanner, scan_devices, get_local_ip, get_gateway_ip
from .task_manager import TaskManager, task_manager, get_task_manager


__all__ = [
    # 抽象基类
    "AbstractBaseDevice",
    # 数据模型
    "DataType", "DataSubType", "DataUnit", "SUBTYPE_UNIT_MAP",
    "LocalDataRecord", "LocalFileRecord", "DataStore",
    "DeviceStatus", "DeviceInfo", "DeviceStateManager", "get_device_state_manager",
    "DeviceCapabilities", "CaptureResult", "CaptureBatch", "DataCategory",
    # 虚拟设备
    "VirtualSensorDevice", "VIRTUAL_UNIT_ID", "VIRTUAL_UNIT_TYPE",
    # 硬件设备
    "ESP32CameraDevice",
    # 向后兼容别名
    "DataGenerator", "ESP32CAM",
    # 工具
    "TaskManager", "task_manager", "get_task_manager",
    "DeviceScanner", "scan_devices", "get_local_ip", "get_gateway_ip",
]
