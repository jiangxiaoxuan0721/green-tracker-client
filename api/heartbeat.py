"""
云端签到编排 —— 启动时一次，之后周期性签到，并按能力开关驱动指令通道。

职责边界：
  * 本模块只做**编排**（何时签到、失败怎么退避、要不要轮询指令）
  * 传输细节在 `api/device_commands.py`
  * 能力结论在 `api/cloud_state.py`（唯一事实源）

退避策略（见《设备端接入说明》第 6 节）：
  * 401 → 固定 5 分钟退避（凭证问题，重试无益）
  * 403 → 静默降级，保持原间隔（等下次签到结果变化）
  * 5xx / 网络错误 → 1 → 2 → 4 … → 60s 指数退避
"""
from __future__ import annotations

import logging
import threading
from typing import Optional

from . import device_commands as dc
from .cloud_state import CloudState, get_cloud_state

try:  # 配置可选，便于测试与最小依赖运行
    from config import heartbeat_interval
except Exception:  # pragma: no cover
    def heartbeat_interval() -> float:
        return 300.0

logger = logging.getLogger("cloud-heartbeat")

AUTH_BACKOFF = 300.0        # 401 固定退避
TRANSIENT_BASE = 1.0        # 5xx 退避起点
TRANSIENT_MAX = 60.0        # 5xx 退避上限


class PendingPoller(threading.Thread):
    """HTTP 指令通道轮询器（`command_channel == "http"` 时启用）。"""

    daemon = True

    def __init__(self, client=None, interval: float = None):
        super().__init__(daemon=True)
        self._client = client or dc
        self._interval = float(interval or 5.0)
        self._stop = threading.Event()

    def set_interval(self, interval: float) -> None:
        self._interval = float(interval)

    def stop(self) -> None:
        self._stop.set()

    def run(self) -> None:
        logger.info("[pending] HTTP 指令轮询已启动，间隔 %.1fs", self._interval)
        while not self._stop.is_set():
            self.pull_once()
            self._stop.wait(self._interval)
        logger.debug("[pending] HTTP 指令轮询已停止")

    def pull_once(self) -> None:
        """拉一次待执行指令并逐条回执（任何异常都不外泄）。"""
        try:
            commands = self._client.fetch_pending()
        except dc.ForbiddenError as e:
            logger.debug("[pending] 无拉取权限，静默跳过: %s", e)
            return
        except dc.DeviceCommandError as e:
            logger.debug("[pending] 拉取失败: %s", e)
            return
        except Exception as e:  # 兜底：轮询线程不能因异常退出
            logger.warning("[pending] 拉取异常: %s", e)
            return

        for item in commands or []:
            self._execute(item)

    # -----------------------------------------------------------------

    def _execute(self, item: dict) -> None:
        from mqtt.commands import CommandHandler  # 延迟导入，避免循环依赖

        command_id = item.get("command_id") or ""
        name = item.get("command") or ""
        params = item.get("params") or {}

        outcome = CommandHandler.execute(name, params)

        if outcome.get("success"):
            status, result, error = dc.STATUS_ACKED, outcome.get("result"), None
        else:
            status, result, error = dc.STATUS_FAILED, None, outcome.get("error")

        if not command_id:
            logger.warning("[pending] 指令缺少 command_id，跳过回执: %s", name)
            return

        try:
            self._client.report_result(command_id, status, result, error)
        except Exception as e:
            logger.warning("[pending] 回执失败 [%s]: %s", command_id, e)


class HeartbeatService:
    """周期性签到 + 能力驱动通道管理（后台守护线程）。"""

    def __init__(self, client=None, state: Optional[CloudState] = None,
                 interval: Optional[float] = None):
        self._client = client or dc
        self._state = state or get_cloud_state()
        self._interval = float(interval if interval is not None else heartbeat_interval())
        self._stop = threading.Event()
        self._wake = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self._poller: Optional[PendingPoller] = None
        self._poller_lock = threading.Lock()
        self._backoff = 0.0

    # -----------------------------------------------------------------
    # 生命周期
    # -----------------------------------------------------------------

    @property
    def is_running(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    def start(self) -> None:
        if self.is_running:
            return
        self._stop.clear()
        self._thread = threading.Thread(
            target=self._loop, name="cloud-heartbeat", daemon=True)
        self._thread.start()
        logger.info("[heartbeat] 签到服务已启动，间隔 %.0fs", self._interval)

    def stop(self) -> None:
        self._stop.set()
        self._wake.set()
        self._stop_poller()
        if self._thread is not None:
            self._thread.join(timeout=2.0)
            self._thread = None

    def trigger_immediate(self) -> None:
        """请求立即重新签到（`revoke_control` 后调用）。"""
        self._wake.set()

    # -----------------------------------------------------------------
    # 单次签到
    # -----------------------------------------------------------------

    def beat_now(self) -> bool:
        """执行一次签到。返回是否成功（异常已在内部分类处理）。"""
        try:
            data = self._client.heartbeat()
        except dc.AuthError as e:
            self._state.record_error(str(e))
            self._backoff = AUTH_BACKOFF
            logger.warning("[heartbeat] 凭证无效，%ss 后重试: %s",
                           int(AUTH_BACKOFF), e)
            return False
        except dc.ForbiddenError as e:
            # 静默降级：不加速重试，等下次签到结果变化
            self._state.record_error(str(e))
            logger.debug("[heartbeat] 能力未开放，静默降级: %s", e)
            return False
        except dc.DeviceCommandError as e:
            self._state.record_error(str(e))
            self._backoff = min(max(self._backoff * 2, TRANSIENT_BASE),
                                TRANSIENT_MAX)
            logger.warning("[heartbeat] 签到失败，%.0fs 后重试: %s",
                           self._backoff, e)
            return False

        self._backoff = 0.0
        self._state.update_from_heartbeat(data)
        self._sync_poller()
        return True

    def next_delay(self) -> float:
        """下一次签到的等待秒数（考虑退避）。"""
        return self._backoff if self._backoff > 0 else self._interval

    # -----------------------------------------------------------------
    # 指令通道
    # -----------------------------------------------------------------

    def is_polling(self) -> bool:
        with self._poller_lock:
            return self._poller is not None and self._poller.is_alive()

    def _sync_poller(self) -> None:
        """按 `command_channel` 启停 HTTP 轮询器。"""
        snapshot = self._state.snapshot()
        should_poll = (self._state.can_receive_commands()
                       and snapshot.get("command_channel") == "http")

        with self._poller_lock:
            if should_poll:
                interval = snapshot.get("poll_interval") or 5.0
                if self._poller is None or not self._poller.is_alive():
                    self._poller = PendingPoller(client=self._client,
                                                 interval=interval)
                    self._poller.start()
                else:
                    self._poller.set_interval(interval)
            elif self._poller is not None:
                self._poller.stop()
                self._poller = None

    def _stop_poller(self) -> None:
        with self._poller_lock:
            if self._poller is not None:
                self._poller.stop()
                self._poller = None

    # -----------------------------------------------------------------

    def _loop(self) -> None:
        while not self._stop.is_set():
            self.beat_now()
            self._wake.wait(self.next_delay())
            self._wake.clear()


# ============================================================
# 进程级单例（供 revoke_control 触发立即重签、UI 启动/停止）
# ============================================================

_global_service: Optional[HeartbeatService] = None
_service_lock = threading.Lock()


def start_heartbeat(client=None, state: Optional[CloudState] = None,
                    interval: Optional[float] = None) -> HeartbeatService:
    """启动（幂等）全局签到服务，返回该服务实例。"""
    global _global_service
    with _service_lock:
        if _global_service is None:
            _global_service = HeartbeatService(
                client=client, state=state, interval=interval)
        _global_service.start()
        return _global_service


def get_heartbeat_service() -> Optional[HeartbeatService]:
    """获取全局签到服务（未启动时返回 None）。"""
    return _global_service


def stop_heartbeat() -> None:
    """停止并清除全局签到服务。"""
    global _global_service
    with _service_lock:
        if _global_service is not None:
            _global_service.stop()
            _global_service = None
