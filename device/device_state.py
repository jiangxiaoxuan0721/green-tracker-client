"""
设备状态管理 - 持久化设备与任务的分配关系
"""
import json
import os
from typing import Dict, List, Optional
from datetime import datetime
from dataclasses import dataclass, asdict
from enum import Enum


class DeviceStatus(str, Enum):
    """设备状态"""
    IDLE = "idle"       # 空闲
    BUSY = "busy"       # 忙碌（分配给任务且任务运行中）
    ASSIGNED = "assigned"  # 已分配但未启动


@dataclass
class DeviceInfo:
    """设备信息"""
    ip: str
    device_type: str
    mac: Optional[str] = None
    hostname: Optional[str] = None
    last_seen: Optional[str] = None
    assigned_session_id: Optional[str] = None
    status: str = DeviceStatus.IDLE
    assigned_time: Optional[str] = None


class DeviceStateManager:
    """设备状态管理器 - 持久化存储设备-任务分配关系"""

    def __init__(self, storage_dir: str = "~/green_tracker_data"):
        self.storage_dir = os.path.expanduser(storage_dir)
        os.makedirs(self.storage_dir, exist_ok=True)
        self.device_file = os.path.join(self.storage_dir, "device_assignments.json")
        self._ensure_file()

    def _ensure_file(self):
        """确保存储文件存在"""
        if not os.path.exists(self.device_file):
            with open(self.device_file, "w") as f:
                json.dump({"devices": {}, "sessions": {}}, f)

    def _load_data(self) -> dict:
        """加载数据"""
        try:
            with open(self.device_file, "r") as f:
                return json.load(f)
        except (FileNotFoundError, json.JSONDecodeError):
            return {"devices": {}, "sessions": {}}

    def _save_data(self, data: dict):
        """保存数据"""
        with open(self.device_file, "w") as f:
            json.dump(data, f, indent=2, default=str)

    def register_device(self, ip: str, device_type: str, **kwargs):
        """注册或更新设备信息"""
        data = self._load_data()
        device_data = data["devices"].get(ip, {})

        # 如果设备已存在，只更新 last_seen 和基本信息，不修改状态和分配信息
        if device_data:
            device_data["ip"] = ip
            device_data["device_type"] = device_type
            device_data["last_seen"] = datetime.now().isoformat()
            # 可选地更新 mac 和 hostname
            if "mac" in kwargs and kwargs["mac"]:
                device_data["mac"] = kwargs["mac"]
            if "hostname" in kwargs and kwargs["hostname"]:
                device_data["hostname"] = kwargs["hostname"]
            data["devices"][ip] = device_data
            self._save_data(data)
            return

        # 新设备，初始化设备信息
        device_data.update({
            "ip": ip,
            "device_type": device_type,
            "last_seen": datetime.now().isoformat(),
            "status": DeviceStatus.IDLE,
            "assigned_session_id": None,
            "assigned_time": None,
            **{k: v for k, v in kwargs.items() if v is not None}
        })

        data["devices"][ip] = device_data
        self._save_data(data)

    def get_device(self, ip: str) -> Optional[DeviceInfo]:
        """获取单个设备信息"""
        data = self._load_data()
        device_data = data["devices"].get(ip)
        if device_data:
            return DeviceInfo(**device_data)
        return None

    def get_all_devices(self, status_filter: Optional[DeviceStatus] = None) -> List[DeviceInfo]:
        """获取所有设备，可选按状态过滤"""
        data = self._load_data()
        devices = []
        for device_data in data["devices"].values():
            device = DeviceInfo(**device_data)
            if status_filter is None or device.status == status_filter:
                devices.append(device)
        return devices

    def assign_device_to_session(self, ip: str, session_id: str, session_name: str) -> bool:
        """分配设备给任务"""
        data = self._load_data()
        
        # 检查设备是否存在
        if ip not in data["devices"]:
            return False
        
        # 检查设备是否空闲
        device_data = data["devices"][ip]
        if device_data.get("status") == DeviceStatus.BUSY:
            return False
        
        # 更新设备状态
        device_data["assigned_session_id"] = session_id
        device_data["status"] = DeviceStatus.ASSIGNED
        device_data["assigned_time"] = datetime.now().isoformat()
        data["devices"][ip] = device_data
        
        # 更新会话设备列表
        if session_id not in data["sessions"]:
            data["sessions"][session_id] = {
                "session_id": session_id,
                "session_name": session_name,
                "devices": [],
                "status": "ready"
            }
        
        if ip not in data["sessions"][session_id]["devices"]:
            data["sessions"][session_id]["devices"].append(ip)
        
        self._save_data(data)
        return True

    def unassign_device(self, ip: str) -> bool:
        """取消设备分配"""
        data = self._load_data()
        
        if ip not in data["devices"]:
            return False
        
        device_data = data["devices"][ip]
        session_id = device_data.get("assigned_session_id")
        
        # 更新设备状态为空闲
        device_data["assigned_session_id"] = None
        device_data["status"] = DeviceStatus.IDLE
        device_data["assigned_time"] = None
        data["devices"][ip] = device_data
        
        # 从会话设备列表中移除
        if session_id and session_id in data["sessions"]:
            data["sessions"][session_id]["devices"] = [
                d for d in data["sessions"][session_id].get("devices", [])
                if d != ip
            ]
        
        self._save_data(data)
        return True

    def get_session_devices(self, session_id: str) -> List[DeviceInfo]:
        """获取任务的所有设备"""
        data = self._load_data()
        session_data = data["sessions"].get(session_id)
        if not session_data:
            return []
        
        devices = []
        for ip in session_data.get("devices", []):
            device_data = data["devices"].get(ip)
            if device_data:
                devices.append(DeviceInfo(**device_data))
        return devices

    def set_session_status(self, session_id: str, status: str):
        """设置任务状态，会同步更新关联设备状态"""
        data = self._load_data()
        
        if session_id not in data["sessions"]:
            data["sessions"][session_id] = {"session_id": session_id, "devices": []}
        
        data["sessions"][session_id]["status"] = status
        
        # 更新设备状态
        if status == "running":
            for ip in data["sessions"][session_id].get("devices", []):
                if ip in data["devices"]:
                    data["devices"][ip]["status"] = DeviceStatus.BUSY
        elif status in ["stopped", "completed"]:
            for ip in data["sessions"][session_id].get("devices", []):
                if ip in data["devices"]:
                    data["devices"][ip]["status"] = DeviceStatus.IDLE
                    data["devices"][ip]["assigned_session_id"] = None
                    data["devices"][ip]["assigned_time"] = None
            # 清空会话设备列表
            data["sessions"][session_id]["devices"] = []
        
        self._save_data(data)

    def cleanup_stale_devices(self, offline_threshold_hours: int = 24) -> int:
        """清理长时间未发现的设备"""
        data = self._load_data()
        cutoff_time = datetime.now().timestamp() - offline_threshold_hours * 3600
        
        stale_devices = []
        for ip, device_data in list(data["devices"].items()):
            last_seen = device_data.get("last_seen")
            if last_seen:
                try:
                    last_seen_time = datetime.fromisoformat(last_seen).timestamp()
                    if last_seen_time < cutoff_time:
                        stale_devices.append(ip)
                except:
                    pass
        
        for ip in stale_devices:
            # 从会话中移除
            session_id = data["devices"][ip].get("assigned_session_id")
            if session_id and session_id in data["sessions"]:
                data["sessions"][session_id]["devices"] = [
                    d for d in data["sessions"][session_id].get("devices", [])
                    if d != ip
                ]
            del data["devices"][ip]
        
        if stale_devices:
            self._save_data(data)
        
        return len(stale_devices)


# 全局单例
_device_state_manager: Optional[DeviceStateManager] = None


def get_device_state_manager() -> DeviceStateManager:
    """获取设备状态管理器单例"""
    global _device_state_manager
    if _device_state_manager is None:
        _device_state_manager = DeviceStateManager()
    return _device_state_manager


__all__ = [
    "DeviceStatus",
    "DeviceInfo",
    "DeviceStateManager",
    "get_device_state_manager",
]
