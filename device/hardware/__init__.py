"""真实硬件设备模块。"""

from .esp32_cam import ESP32CameraDevice, DEVICE_TYPE_ESP32_CAM

__all__ = ["ESP32CameraDevice", "DEVICE_TYPE_ESP32_CAM"]
