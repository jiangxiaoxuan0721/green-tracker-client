"""
设备模块 — 执行器设备的抽象体系与具体实现。

目录结构：
  device/
  ├── base.py              # AbstractBaseDevice 抽象基类（统一范式）
  ├── registry.py          # DeviceRegistry：device_type → 设备工厂
  ├── runtime.py           # 全局虚拟传感器单例
  ├── collector.py         # SessionCollector：会话采集引擎
  ├── models/               # 数据类型 & 模型定义
  │   ├── base.py          # DeviceCapabilities / CaptureResult / CaptureBatch
  │   ├── data_types.py    # DataType / DataSubType / DataUnit
  │   ├── records.py       # LocalDataRecord / LocalFileRecord
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
from .hardware import ESP32CameraDevice, DEVICE_TYPE_ESP32_CAM

# ============================================================
# 设备注册表与运行时（必须在具体设备之后导入）
# ============================================================
from .registry import DeviceRegistry, registry
from .runtime import init_data_sensor, get_data_sensor, reset_data_sensor
from .collector import SessionCollector

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
    "LocalDataRecord", "LocalFileRecord",
    "DeviceStatus", "DeviceInfo", "DeviceStateManager", "get_device_state_manager",
    "DeviceCapabilities", "CaptureResult", "CaptureBatch", "DataCategory",
    # 虚拟设备
    "VirtualSensorDevice", "VIRTUAL_UNIT_ID", "VIRTUAL_UNIT_TYPE",
    # 硬件设备
    "ESP32CameraDevice", "DEVICE_TYPE_ESP32_CAM",
    # 注册表与运行时
    "DeviceRegistry", "registry",
    "init_data_sensor", "get_data_sensor", "reset_data_sensor",
    "SessionCollector",
    # 工具
    "TaskManager", "task_manager", "get_task_manager",
    "DeviceScanner", "scan_devices", "get_local_ip", "get_gateway_ip",
]
