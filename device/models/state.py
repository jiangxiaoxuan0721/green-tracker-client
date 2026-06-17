"""设备状态管理 — 执行单元注册、分配关系持久化、在线检测。"""
import json
import os
import socket
from typing import Dict, List, Optional
from datetime import datetime
from dataclasses import dataclass
from enum import Enum


class DeviceStatus(str, Enum):
    """执行单元状态"""
    IDLE = "idle"
    BUSY = "busy"
    ASSIGNED = "assigned"
    OFFLINE = "offline"


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
    is_virtual: bool = False


class DeviceStateManager:
    """设备状态管理器 — 内存缓存 + JSON 持久化双写。"""

    def __init__(self, storage_dir: str = "~/green_tracker_data"):
        self.storage_dir = os.path.expanduser(storage_dir)
        os.makedirs(self.storage_dir, exist_ok=True)
        self.device_file = os.path.join(self.storage_dir, "device_assignments.json")
        self._ensure_file()
        self._cache: dict = self._load_data()

    def _ensure_file(self):
        if not os.path.exists(self.device_file):
            with open(self.device_file, "w") as f:
                json.dump({"devices": {}, "sessions": {}}, f)

    def _load_data(self) -> dict:
        try:
            with open(self.device_file, "r") as f:
                return json.load(f)
        except (FileNotFoundError, json.JSONDecodeError):
            return {"devices": {}, "sessions": {}}

    def _save_data(self, data: dict):
        self._cache = data
        with open(self.device_file, "w") as f:
            json.dump(data, f, indent=2, default=str)

    def register_device(self, ip: str, device_type: str, **kwargs):
        data = dict(self._cache)
        device_data = data["devices"].get(ip, {})
        if device_data:
            device_data["ip"] = ip
            device_data["device_type"] = device_type
            device_data["last_seen"] = datetime.now().isoformat()
            if device_data.get("status") == DeviceStatus.OFFLINE:
                device_data["status"] = DeviceStatus.IDLE if not device_data.get("assigned_session_id") else DeviceStatus.ASSIGNED
            if "mac" in kwargs and kwargs["mac"]:
                device_data["mac"] = kwargs["mac"]
            if "hostname" in kwargs and kwargs["hostname"]:
                device_data["hostname"] = kwargs["hostname"]
            data["devices"][ip] = device_data
            self._save_data(data)
            return
        device_data.update({
            "ip": ip, "device_type": device_type,
            "last_seen": datetime.now().isoformat(),
            "status": DeviceStatus.IDLE,
            "assigned_session_id": None, "assigned_time": None,
            "is_virtual": kwargs.get("is_virtual", False),
            **{k: v for k, v in kwargs.items() if v is not None and k != "is_virtual"}
        })
        data["devices"][ip] = device_data
        self._save_data(data)

    def register_virtual_unit(self, unit_id: str, unit_type: str, **kwargs):
        data = dict(self._cache)
        existing = data["devices"].get(unit_id)
        if existing:
            existing["last_seen"] = datetime.now().isoformat()
            existing["device_type"] = unit_type
            for k, v in kwargs.items():
                if v is not None:
                    existing[k] = v
            data["devices"][unit_id] = existing
        else:
            device_data = {
                "ip": unit_id, "device_type": unit_type, "mac": None,
                "hostname": kwargs.get("hostname", unit_type),
                "last_seen": datetime.now().isoformat(),
                "status": DeviceStatus.IDLE, "assigned_session_id": None,
                "assigned_time": None, "is_virtual": True,
            }
            data["devices"][unit_id] = device_data
        self._save_data(data)

    def get_device(self, ip: str) -> Optional[DeviceInfo]:
        data = self._cache
        device_data = data["devices"].get(ip)
        return DeviceInfo(**device_data) if device_data else None

    def get_all_devices(self, status_filter: Optional[DeviceStatus] = None) -> List[DeviceInfo]:
        data = self._cache
        devices = []
        for dd in data["devices"].values():
            dev = DeviceInfo(**dd)
            if status_filter is None or dev.status == status_filter:
                devices.append(dev)
        return devices

    def assign_device_to_session(self, ip: str, session_id: str, session_name: str) -> bool:
        data = dict(self._cache)
        if ip not in data["devices"]:
            return False
        dd = data["devices"][ip]
        if dd.get("status") == DeviceStatus.BUSY:
            return False
        dd["assigned_session_id"] = session_id
        dd["status"] = DeviceStatus.ASSIGNED
        dd["assigned_time"] = datetime.now().isoformat()
        data["devices"][ip] = dd
        if session_id not in data["sessions"]:
            data["sessions"][session_id] = {"session_id": session_id, "session_name": session_name, "devices": [], "status": "ready"}
        if ip not in data["sessions"][session_id]["devices"]:
            data["sessions"][session_id]["devices"].append(ip)
        self._save_data(data)
        return True

    def unassign_device(self, ip: str) -> bool:
        data = dict(self._cache)
        if ip not in data["devices"]:
            return False
        dd = data["devices"][ip]
        sid = dd.get("assigned_session_id")
        dd["assigned_session_id"] = None
        dd["status"] = DeviceStatus.IDLE
        dd["assigned_time"] = None
        data["devices"][ip] = dd
        if sid and sid in data["sessions"]:
            data["sessions"][sid]["devices"] = [d for d in data["sessions"][sid].get("devices", []) if d != ip]
        self._save_data(data)
        return True

    def get_session_devices(self, session_id: str) -> List[DeviceInfo]:
        data = self._cache
        sd = data["sessions"].get(session_id)
        if not sd:
            return []
        devs = []
        for ip in sd.get("devices", []):
            dd = data["devices"].get(ip)
            if dd:
                devs.append(DeviceInfo(**dd))
        return devs

    def set_session_status(self, session_id: str, status: str):
        data = dict(self._cache)
        if session_id not in data["sessions"]:
            data["sessions"][session_id] = {"session_id": session_id, "devices": []}
        data["sessions"][session_id]["status"] = status
        if status == "running":
            for ip in data["sessions"][session_id].get("devices", []):
                if ip in data["devices"]:
                    data["devices"][ip]["status"] = DeviceStatus.BUSY
        elif status in ("stopped", "completed"):
            for ip in data["sessions"][session_id].get("devices", []):
                if ip in data["devices"]:
                    data["devices"][ip]["status"] = DeviceStatus.IDLE
                    data["devices"][ip]["assigned_session_id"] = None
                    data["devices"][ip]["assigned_time"] = None
            data["sessions"][session_id]["devices"] = []
        self._save_data(data)

    def cleanup_stale_devices(self, offline_threshold_hours: float = 24.0) -> int:
        data = dict(self._cache)
        cutoff = datetime.now().timestamp() - offline_threshold_hours * 3600
        stale = []
        for ip, dd in list(data["devices"].items()):
            if dd.get("is_virtual", False):
                continue
            last_seen = dd.get("last_seen")
            if last_seen:
                try:
                    if datetime.fromisoformat(last_seen).timestamp() < cutoff:
                        stale.append(ip)
                except Exception:
                    pass
        for ip in stale:
            sid = data["devices"][ip].get("assigned_session_id")
            if sid and sid in data["sessions"]:
                data["sessions"][sid]["devices"] = [d for d in data["sessions"][sid].get("devices", []) if d != ip]
            del data["devices"][ip]
        if stale:
            self._save_data(data)
        return len(stale)

    def mark_offline_devices(self, timeout_seconds: int = 90) -> int:
        data = dict(self._cache)
        cutoff = datetime.now().timestamp() - timeout_seconds
        marked = 0
        for ip, dd in data["devices"].items():
            if dd.get("is_virtual", False) or dd.get("status") == DeviceStatus.OFFLINE:
                continue
            last_seen = dd.get("last_seen")
            try:
                if last_seen and datetime.fromisoformat(last_seen).timestamp() < cutoff:
                    dd["status"] = DeviceStatus.OFFLINE
                    marked += 1
                elif not last_seen:
                    dd["status"] = DeviceStatus.OFFLINE
                    marked += 1
            except (ValueError, TypeError):
                dd["status"] = DeviceStatus.OFFLINE
                marked += 1
        if marked > 0:
            self._save_data(data)
        return marked

    def health_check_all(self, timeout: float = 0.5, ports: Optional[List[int]] = None) -> Dict[str, bool]:
        if ports is None:
            ports = [80]
        data = self._cache
        results: Dict[str, bool] = {}
        ips = [ip for ip, d in data.get("devices", {}).items() if not d.get("is_virtual", False)]
        for ip in ips:
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
    global _device_state_manager
    if _device_state_manager is None:
        _device_state_manager = DeviceStateManager()
    return _device_state_manager


__all__ = [
    "DeviceStatus", "DeviceInfo", "DeviceStateManager",
    "get_device_state_manager",
]
