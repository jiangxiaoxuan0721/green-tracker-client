"""
云端能力状态 —— 全进程唯一的「我此刻能做什么」事实源。

设备**不解析权限含义**，也不缓存权限结论：只保存最近一次签到回传的
`capabilities` 与 `command_channel`，供命令门控、上传入口、UI 指示灯查询。

注意：拉取云端采集任务（`active_sessions`）是设备作业通道的**默认能力**，
不是权限项 —— 任意有效密钥都能拉，云端不再对 `data_read` 做校验，
因此本状态不再跟踪 `capabilities.pull_tasks`（该值恒为 true）。

状态来源只有两个：
  * `update_from_heartbeat(data)` —— 签到成功，按云端结论刷新
  * `mark_revoked(reason)`        —— 收到 `revoke_control` 系统指令
"""
from __future__ import annotations

import logging
import threading
from datetime import datetime, timezone
from typing import Callable, Dict, List, Optional

logger = logging.getLogger("cloud-state")

DEFAULT_POLL_INTERVAL = 5.0  # 云端未给 poll_interval_seconds 时的默认轮询间隔


class CloudState:
    """云端能力状态（线程安全）。"""

    def __init__(self):
        self._lock = threading.RLock()
        self._listeners: List[Callable[["CloudState"], None]] = []

        self.registered: bool = False
        self.upload_data: bool = False
        self.receive_commands: bool = False
        self.command_channel: Optional[str] = None       # mqtt / http / None
        self.poll_interval: Optional[float] = None       # 仅 http 通道有意义
        self.revoked: bool = False
        self.revoke_reason: Optional[str] = None
        self.last_heartbeat_at: Optional[str] = None
        self.last_error: Optional[str] = None

    # -----------------------------------------------------------------
    # 写入
    # -----------------------------------------------------------------

    def update_from_heartbeat(self, data: Optional[dict]) -> None:
        """按签到响应刷新能力开关。"""
        data = data or {}
        caps = data.get("capabilities") or {}

        with self._lock:
            self.registered = bool(data.get("registered", False))
            self.upload_data = bool(caps.get("upload_data", False))
            self.receive_commands = bool(caps.get("receive_commands", False))
            self.command_channel = data.get("command_channel") or None
            self.poll_interval = self._parse_poll_interval(
                data.get("poll_interval_seconds"))
            self.last_heartbeat_at = datetime.now(timezone.utc).isoformat()
            self.last_error = None

            # 云端重新开放控制权限 → 撤销状态自动解除
            if self.receive_commands:
                self.revoked = False
                self.revoke_reason = None

        logger.debug(
            "[cloud-state] 能力刷新: channel=%s upload=%s commands=%s",
            self.command_channel, self.upload_data,
            self.receive_commands,
        )
        self._notify()

    def mark_revoked(self, reason: str = "") -> None:
        """收到 `revoke_control`：立即停止受控，直到下次签到恢复。"""
        with self._lock:
            self.revoked = True
            self.revoke_reason = reason or "控制权限已被云端撤销"

        logger.warning("[cloud-state] 控制权限已撤销: %s", self.revoke_reason)
        self._notify()

    def record_error(self, message: str) -> None:
        """记录一次签到失败（不改变已有能力，避免抖动导致功能闪断）。"""
        with self._lock:
            self.last_error = message
        logger.debug("[cloud-state] 签到失败: %s", message)

    def reset(self) -> None:
        """清空为初始状态（供测试与客户端重启使用）。"""
        with self._lock:
            self.registered = False
            self.upload_data = False
            self.receive_commands = False
            self.command_channel = None
            self.poll_interval = None
            self.revoked = False
            self.revoke_reason = None
            self.last_heartbeat_at = None
            self.last_error = None
        self._notify()

    # -----------------------------------------------------------------
    # 查询
    # -----------------------------------------------------------------

    def is_revoked(self) -> bool:
        return self.revoked

    @property
    def synced(self) -> bool:
        """是否至少成功签到过一次。

        未同步前（云端签到接口不可达 / 尚未返回）数据面沿用本地旧行为，
        避免云端抖动就把上传全部打断；一旦同步过就以云端结论为准。

        注意：拉取采集任务**不走**这里 —— 它是设备作业通道的默认能力，
        不是权限项，因此不受本状态约束（见 fetch_tasks）。
        """
        return self.last_heartbeat_at is not None

    def can_upload(self) -> bool:
        """是否允许上传采集数据。"""
        if self.revoked:
            return False
        if not self.synced:
            return True
        return self.upload_data

    def can_receive_commands(self) -> bool:
        """是否允许接受并执行云端指令。"""
        return self.receive_commands and not self.revoked

    def snapshot(self) -> Dict[str, object]:
        """扁平快照（供 UI / 日志 / 测试使用）。"""
        with self._lock:
            return {
                "registered": self.registered,
                "capabilities": {
                    "upload_data": self.upload_data,
                    "receive_commands": self.receive_commands,
                },
                "command_channel": self.command_channel,
                "poll_interval": self.poll_interval,
                "revoked": self.revoked,
                "revoke_reason": self.revoke_reason,
                "last_heartbeat_at": self.last_heartbeat_at,
                "last_error": self.last_error,
            }

    def add_listener(self, callback: Callable[["CloudState"], None]) -> None:
        """注册变更回调（能力变化时通知 UI / 轮询器）。"""
        with self._lock:
            self._listeners.append(callback)

    # -----------------------------------------------------------------
    # 内部
    # -----------------------------------------------------------------

    @staticmethod
    def _parse_poll_interval(raw) -> Optional[float]:
        if raw in (None, ""):
            return DEFAULT_POLL_INTERVAL
        try:
            return float(raw)
        except (TypeError, ValueError):
            return DEFAULT_POLL_INTERVAL

    def _notify(self) -> None:
        with self._lock:
            listeners = list(self._listeners)
        for cb in listeners:
            try:
                cb(self)
            except Exception as e:  # 回调异常不能影响状态更新
                logger.warning("[cloud-state] 变更回调异常: %s", e)


_global_state: Optional[CloudState] = None
_state_lock = threading.Lock()


def get_cloud_state() -> CloudState:
    """进程内唯一的能力状态实例。"""
    global _global_state
    if _global_state is None:
        with _state_lock:
            if _global_state is None:
                _global_state = CloudState()
    return _global_state
