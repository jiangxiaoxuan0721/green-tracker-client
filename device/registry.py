"""设备注册表 — device_type → 设备工厂。

这是设备可拓展性的核心：新增一种设备只需两件事
  1. 实现 AbstractBaseDevice 子类
  2. registry.register("<device_type>", factory)

采集引擎（device.collector）与所有 UI 代码都只依赖抽象基类，
因此新增设备类型不需要改动它们中的任何一行。

未注册的 device_type 返回 None，由调用方安全跳过 —— 这替代了
原先散落在 UI 中的 `if dev.device_type == "ESP32-CAM"` 硬编码判断。
"""
from __future__ import annotations

from typing import Callable, Dict, List, Optional

from .base import AbstractBaseDevice
from .models.state import DeviceInfo

# 工厂：接收 DeviceInfo，返回设备实例（或 None 表示无法创建）
DeviceFactory = Callable[[DeviceInfo], Optional[AbstractBaseDevice]]


class DeviceRegistry:
    """device_type 到设备工厂的映射表。"""

    def __init__(self) -> None:
        self._factories: Dict[str, DeviceFactory] = {}

    def register(self, device_type: str, factory: DeviceFactory) -> None:
        """注册（或覆盖）某个设备类型的工厂。"""
        if not device_type:
            raise ValueError("device_type 不能为空")
        self._factories[device_type] = factory

    def unregister(self, device_type: str) -> None:
        self._factories.pop(device_type, None)

    def is_registered(self, device_type: str) -> bool:
        return device_type in self._factories

    def known_types(self) -> List[str]:
        return sorted(self._factories)

    def create(self, device_info: DeviceInfo) -> Optional[AbstractBaseDevice]:
        """按 device_info.device_type 创建设备。

        未注册的类型或构造失败均返回 None（不抛出），
        保证单个设备的异常不会中断整个会话的采集。
        """
        factory = self._factories.get(device_info.device_type)
        if factory is None:
            return None
        try:
            return factory(device_info)
        except Exception as e:
            print(f"[registry] 创建 {device_info.device_type} 失败: {e}")
            return None

    def __contains__(self, device_type: object) -> bool:
        return device_type in self._factories

    def __len__(self) -> int:
        return len(self._factories)


# ============================================================
# 全局注册表与内置设备
# ============================================================
registry = DeviceRegistry()


def _register_builtins() -> None:
    """注册内置设备类型。

    延迟导入设备实现，避免 device 包初始化期的循环导入。
    """
    from .virtual import VirtualSensorDevice, VIRTUAL_UNIT_TYPE
    from .hardware import ESP32CameraDevice, DEVICE_TYPE_ESP32_CAM

    registry.register(VIRTUAL_UNIT_TYPE, lambda info: VirtualSensorDevice())
    registry.register(DEVICE_TYPE_ESP32_CAM, lambda info: ESP32CameraDevice(info.ip))


_register_builtins()


__all__ = ["DeviceRegistry", "DeviceFactory", "registry"]
