"""
执行单元状态管理 - 持久化执行单元与任务的分配关系
"""
import json
import os
import socket
from typing import Dict, List, Optional
from datetime import datetime
from dataclasses import dataclass, asdict
from enum import Enum


class DeviceStatus(str, Enum):
    """执行单元状态"""
    IDLE = "idle"       # 空闲（在线）
    BUSY = "busy"       # 忙碌（分配给任务且任务运行中）
    ASSIGNED = "assigned"  # 已分配但未启动
    OFFLINE = "offline"   # 离线（超时未上报）


@dataclass
class DeviceInfo:
    """执行单元信息"""
    ip: str
    device_type: str
    mac: Optional[str] = None
    hostname: Optional[str] = None
    last_seen: Optional[str] = None
    assigned_session_id: Optional[str] = None
    status: str = DeviceStatus.IDLE
    assigned_time: Optional[str] = None
    is_virtual: bool = False  # 虚拟执行单元（如 DataGenerator），不会被超时清理


class DeviceStateManager:
    """设备状态管理器 - 内存缓存 + 持久化存储"""

    def __init__(self, storage_dir: str = "~/green_tracker_data"):
        self.storage_dir = os.path.expanduser(storage_dir)
        os.makedirs(self.storage_dir, exist_ok=True)
        self.device_file = os.path.join(self.storage_dir, "device_assignments.json")
        self._ensure_file()
        # 内存缓存：所有读操作走这里，避免每次磁盘 I/O
        self._cache: dict = self._load_data()

    def _ensure_file(self):
        """确保存储文件存在"""
        if not os.path.exists(self.device_file):
            with open(self.device_file, "w") as f:
                json.dump({"devices": {}, "sessions": {}}, f)

    def _load_data(self) -> dict:
        """从文件加载数据"""
        try:
            with open(self.device_file, "r") as f:
                return json.load(f)
        except (FileNotFoundError, json.JSONDecodeError):
            return {"devices": {}, "sessions": {}}

    def _save_data(self, data: dict):
        """同步内存缓存并持久化到文件"""
        self._cache = data
        with open(self.device_file, "w") as f:
            json.dump(data, f, indent=2, default=str)

    def register_device(self, ip: str, device_type: str, **kwargs):
        """注册或更新执行单元信息"""
        data = dict(self._cache)  # 浅拷贝避免并发修改
        device_data = data["devices"].get(ip, {})

        # 如果执行单元已存在，只更新 last_seen 和基本信息
        # 若之前标记为离线则恢复为空闲/已分配状态
        if device_data:
            device_data["ip"] = ip
            device_data["device_type"] = device_type
            device_data["last_seen"] = datetime.now().isoformat()
            # 设备重新上线：从离线恢复
            if device_data.get("status") == DeviceStatus.OFFLINE:
                device_data["status"] = DeviceStatus.IDLE if not device_data.get("assigned_session_id") else DeviceStatus.ASSIGNED
            # 可选地更新 mac 和 hostname
            if "mac" in kwargs and kwargs["mac"]:
                device_data["mac"] = kwargs["mac"]
            if "hostname" in kwargs and kwargs["hostname"]:
                device_data["hostname"] = kwargs["hostname"]
            data["devices"][ip] = device_data
            self._save_data(data)
            return

        # 新执行单元，初始化信息
        device_data.update({
            "ip": ip,
            "device_type": device_type,
            "last_seen": datetime.now().isoformat(),
            "status": DeviceStatus.IDLE,
            "assigned_session_id": None,
            "assigned_time": None,
            "is_virtual": kwargs.get("is_virtual", False),
            **{k: v for k, v in kwargs.items() if v is not None and k != "is_virtual"}
        })

        data["devices"][ip] = device_data
        self._save_data(data)

    def register_virtual_unit(self, unit_id: str, unit_type: str, **kwargs):
        """注册虚拟执行单元（不会被超时清理）。

        Args:
            unit_id: 虚拟执行单元唯一标识（如 'virtual:datagenerator'）
            unit_type: 执行单元类型名称
            **kwargs: 其他可选字段（hostname 等）
        """
        data = dict(self._cache)
        existing = data["devices"].get(unit_id)

        if existing:
            # 已存在则仅更新基本信息
            existing["last_seen"] = datetime.now().isoformat()
            existing["device_type"] = unit_type
            for k, v in kwargs.items():
                if v is not None:
                    existing[k] = v
            data["devices"][unit_id] = existing
        else:
            device_data = {
                "ip": unit_id,
                "device_type": unit_type,
                "mac": None,
                "hostname": kwargs.get("hostname", unit_type),
                "last_seen": datetime.now().isoformat(),
                "status": DeviceStatus.IDLE,
                "assigned_session_id": None,
                "assigned_time": None,
                "is_virtual": True,
            }
            data["devices"][unit_id] = device_data

        self._save_data(data)

    def get_device(self, ip: str) -> Optional[DeviceInfo]:
        """获取单个设备信息（读内存缓存，无 I/O）"""
        data = self._cache
        device_data = data["devices"].get(ip)
        if device_data:
            return DeviceInfo(**device_data)
        return None

    def get_all_devices(self, status_filter: Optional[DeviceStatus] = None) -> List[DeviceInfo]:
        """获取所有设备（读内存缓存，无 I/O）"""
        data = self._cache
        devices = []
        for device_data in data["devices"].values():
            device = DeviceInfo(**device_data)
            if status_filter is None or device.status == status_filter:
                devices.append(device)
        return devices

    def assign_device_to_session(self, ip: str, session_id: str, session_name: str) -> bool:
        """分配设备给任务"""
        data = dict(self._cache)
        
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
        data = dict(self._cache)
        
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
        """获取任务的所有设备（读内存缓存，无 I/O）"""
        data = self._cache
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
        data = dict(self._cache)
        
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

    def cleanup_stale_devices(self, offline_threshold_hours: float = 24.0) -> int:
        """清理超时未发现的执行单位（跳过虚拟单位）。"""
        data = dict(self._cache)
        cutoff_time = datetime.now().timestamp() - offline_threshold_hours * 3600
        
        stale_devices = []
        for ip, device_data in list(data["devices"].items()):
            # 虚拟执行单元不参与超时清理
            if device_data.get("is_virtual", False):
                continue
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

    def mark_offline_devices(self, timeout_seconds: int = 90) -> int:
        """根据 last_seen 将超时未上报的设备标记为离线（不删除设备）。

        Args:
            timeout_seconds: 超时阈值（秒），建议设为 MQTT 心跳间隔的 3 倍

        Returns:
            被标记为离线的设备数量
        """
        data = dict(self._cache)
        cutoff_time = datetime.now().timestamp() - timeout_seconds
        marked_count = 0

        for ip, device_data in data["devices"].items():
            # 跳过虚拟执行单元
            if device_data.get("is_virtual", False):
                continue
            # 已经是离线状态的跳过
            if device_data.get("status") == DeviceStatus.OFFLINE:
                continue
            last_seen = device_data.get("last_seen")
            if last_seen:
                try:
                    last_seen_time = datetime.fromisoformat(last_seen).timestamp()
                    if last_seen_time < cutoff_time:
                        device_data["status"] = DeviceStatus.OFFLINE
                        marked_count += 1
                except (ValueError, TypeError):
                    # 无效的 last_seen，直接标记离线
                    if device_data.get("status") != DeviceStatus.OFFLINE:
                        device_data["status"] = DeviceStatus.OFFLINE
                        marked_count += 1

        if marked_count > 0:
            self._save_data(data)

        return marked_count

    def health_check_all(self, timeout: float = 0.5, ports: List[int] = None) -> Dict[str, bool]:
        """主动 TCP 探测所有已注册设备的在线状态。

        对每个已知设备 IP 尝试 TCP 连接（默认探测端口 80），
        返回 {ip: is_online} 映射，用于驱动 UI 实时更新。

        Args:
            timeout: 每个连接的超时时间（秒）
            ports: 待探测的端口列表，默认 [80]

        Returns:
            {ip: True/False} 在线状态字典
        """
        if ports is None:
            ports = [80]

        data = self._cache
        results: Dict[str, bool] = {}
        ips_to_check = [
            ip for ip, d in data.get("devices", {}).items()
            if not d.get("is_virtual", False)
        ]

        for ip in ips_to_check:
            online = False
            for port in ports:
                try:
                    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                    sock.settimeout(timeout)
                    if sock.connect_ex((ip, port)) == 0:
                        online = True
                        sock.close()
                        break
                    sock.close()
                except Exception:
                    pass
            results[ip] = online

        return results


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
