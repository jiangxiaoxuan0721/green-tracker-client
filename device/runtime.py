"""应用级设备运行时 — 全局虚拟传感器单例。

从 ui/task_window.py 迁出（该模块因此得以删除），
使 UI 不再持有具体设备实现，也消除了 ui.device_assign → ui.task_window
的反向依赖。
"""
from __future__ import annotations

from typing import Optional

import config

from .virtual import VirtualSensorDevice

_virtual_sensor: Optional[VirtualSensorDevice] = None


def init_data_sensor(interval: Optional[float] = None) -> VirtualSensorDevice:
    """创建并启动后台虚拟传感器（幂等：已在运行则直接返回）。

    Args:
        interval: 后台生成间隔（秒），默认取 config.virtual_sensor_interval()
    """
    global _virtual_sensor
    if _virtual_sensor is not None and _virtual_sensor.running:
        return _virtual_sensor

    _virtual_sensor = VirtualSensorDevice(
        interval=interval if interval is not None else config.virtual_sensor_interval()
    )
    _virtual_sensor.initialize()
    _virtual_sensor.start()
    return _virtual_sensor


def get_data_sensor() -> Optional[VirtualSensorDevice]:
    """返回已启动的虚拟传感器；尚未初始化时返回 None。"""
    return _virtual_sensor


def reset_data_sensor() -> None:
    """停止并清除单例（供测试或重启流程使用）。"""
    global _virtual_sensor
    if _virtual_sensor is not None:
        _virtual_sensor.stop()
    _virtual_sensor = None


__all__ = ["init_data_sensor", "get_data_sensor", "reset_data_sensor"]
