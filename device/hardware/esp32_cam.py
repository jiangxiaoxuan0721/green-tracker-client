"""
ESP32-CAM 硬件设备 — 基于 AbstractBaseDevice 的真实摄像头设备实现。

继承统一抽象范式，支持：
  - 图片拍摄（HTTP REST API）
  - 视频流获取
  - 在线状态检测
  - 统一的数据采集接口（产出 LocalFileRecord）
"""
import os
from datetime import datetime, timezone
from typing import List, Optional

import requests

from ..base import AbstractBaseDevice
from ..models.base import DeviceCapabilities
from ..models.data_types import DataSubType
from ..models.records import LocalFileRecord, LocalDataRecord

# 局域网设备通信必须绕过系统代理（同 device_scanner.py 的原因）
_NO_PROXY = {"http": None, "https": None}  # type: ignore

# 设备类型标识 — registry 注册键与扫描器识别结果共用此单一来源
DEVICE_TYPE_ESP32_CAM = "ESP32-CAM"


class ESP32CameraDevice(AbstractBaseDevice):
    """ESP32-CAM 摄像头设备。"""

    DEFAULT_PORT = 80
    CAPTURE_TIMEOUT = 10.0
    STATUS_TIMEOUT = 3.0

    SUPPORTED_IMAGE_SUBTYPES = [
        DataSubType.RGB.value,
        DataSubType.NIR.value,
        DataSubType.THERMAL.value,
        DataSubType.MULTISPECTRAL.value,
    ]

    def __init__(self, ip: str, port: int = DEFAULT_PORT):
        super().__init__()
        self.device_id = ip
        self.device_type = DEVICE_TYPE_ESP32_CAM
        self.is_virtual = False

        self.ip = ip
        self.port = port
        self.base_url = f"http://{ip}:{port}"

        # 内部状态
        self._last_image_path: Optional[str] = None
        self._last_status: Optional[dict] = None

    # -----------------------------------------------------------------
    # AbstractBaseDevice 实现
    # -----------------------------------------------------------------

    def get_capabilities(self) -> DeviceCapabilities:
        return DeviceCapabilities(
            device_type=self.device_type,
            supports_numeric=False,
            supports_file=True,
            numeric_categories=[],
            file_subtypes=list(self.SUPPORTED_IMAGE_SUBTYPES),
            is_virtual=False,
            description="ESP32-CAM 摄像头设备，支持 RGB/NIR/热成像图片采集",
        )

    def initialize(self) -> bool:
        """尝试连接设备确认在线。"""
        if self._initialized:
            return True
        ok = self.health_check()
        if ok:
            self._initialized = True
        return ok

    def health_check(self) -> bool:
        """TCP 连接检测 + HTTP 状态检测。"""
        import socket as _sock
        # TCP 快速探测
        try:
            s = _sock.socket(_sock.AF_INET, _sock.SOCK_STREAM)
            s.settimeout(1.0)
            result = s.connect_ex((self.ip, self.port)) == 0
            s.close()
            if not result:
                return False
        except Exception:
            return False
        # HTTP 状态确认
        status_info = self.status()
        online = status_info.get("status") == "online"
        self._last_status = status_info
        return online

    def collect_numeric_data(
        self,
        session_id: str,
        location_geom=None,
        altitude_m=None,
        heading=None,
    ) -> List[LocalDataRecord]:  # type: ignore[override]
        """摄像头不产生数值数据。"""
        return []

    def can_capture_file_data(self) -> bool:
        return True

    def capture_file_data(
        self,
        session_id: str,
        data_subtype: str = DataSubType.RGB,
        location_geom: Optional[str] = None,
        altitude_m: Optional[float] = None,
        heading: Optional[float] = None,
    ) -> Optional[LocalFileRecord]:
        """拍摄一张照片并保存为本地文件，返回 LocalFileRecord。

        图片保存在 ~/green_tracker_data/{session_id}/images/ 目录下。
        """
        image_bytes = self.capture(timeout=self.CAPTURE_TIMEOUT)
        if image_bytes is None:
            return None

        now = datetime.now(timezone.utc)
        timestamp = now.strftime("%Y%m%d_%H%M%S")
        safe_ip = self.ip.replace(".", "_")
        filename = f"{safe_ip}_{timestamp}.jpg"

        # 确定保存目录
        base_dir = os.path.expanduser("~/green_tracker_data")
        save_dir = os.path.join(base_dir, session_id, "images")
        os.makedirs(save_dir, exist_ok=True)

        local_path = os.path.join(save_dir, filename)
        with open(local_path, "wb") as f:
            f.write(image_bytes)

        file_size = os.path.getsize(local_path)

        record = LocalFileRecord(  # type: ignore[call-arg]
            session_id=session_id,
            data_subtype=data_subtype,
            local_path=local_path,
            file_size_bytes=file_size,
            capture_time=now,
            location_geom=location_geom,
            altitude_m=altitude_m,
            heading=heading,
            description=f"ESP32-CAM {self.ip}",
        )
        self._last_image_path = local_path
        return record

    # -----------------------------------------------------------------
    # ESP32-CAM 特有操作
    # -----------------------------------------------------------------

    def capture(self, timeout: float = CAPTURE_TIMEOUT) -> Optional[bytes]:
        """从摄像头获取一张图片的原始字节。"""
        try:
            url = f"{self.base_url}/capture"
            resp = requests.get(url, timeout=timeout,
                                proxies=_NO_PROXY)  # type: ignore[arg-type]
            if resp.status_code == 200:
                return resp.content
        except requests.exceptions.RequestException as e:
            pass
        return None

    def get_stream_url(self) -> str:
        """获取 MJPEG 视频流 URL。"""
        return f"{self.base_url}/stream"

    def status(self, timeout: float = STATUS_TIMEOUT) -> dict:
        """查询设备 HTTP 状态。"""
        endpoints = ["/status", "/", "/info"]
        for endpoint in endpoints:
            try:
                resp = requests.get(
                    f"{self.base_url}{endpoint}", timeout=timeout,
                    proxies=_NO_PROXY,  # type: ignore[arg-type]
                )
                if resp.status_code == 200:
                    return {
                        "ip": self.ip,
                        "port": self.port,
                        "status": "online",
                        "response": resp.text[:200] if resp.text else "OK",
                    }
            except requests.exceptions.RequestException:
                continue
        return {
            "ip": self.ip,
            "port": self.port,
            "status": "offline",
        }

    # -----------------------------------------------------------------
    # 内省
    # -----------------------------------------------------------------

    @property
    def last_image_path(self) -> Optional[str]:
        return self._last_image_path

    @property
    def last_status(self) -> Optional[dict]:
        return self._last_status


__all__ = ["ESP32CameraDevice", "DEVICE_TYPE_ESP32_CAM"]
