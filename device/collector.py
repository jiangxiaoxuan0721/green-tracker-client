"""会话采集引擎 — 按会话驱动已分配设备采集并落盘。

设计目标：把采集逻辑从 UI 中完全剥离。

  * 不 import 任何 PyQt，可脱离 Qt 用纯 Python 测试
  * 设备类型差异全部由 device.registry + AbstractBaseDevice 多态接口吸收，
    新增设备类型不需要改动本模块或任何 UI 代码
  * 落盘约定统一走 storage.batch.SessionStore

对应原先 ui/collection_monitor.py 中 TaskCard._collect_loop 里
`if dev.device_type == "ESP32-CAM"` 这类硬编码分支。
"""
from __future__ import annotations

import time
from typing import Callable, Optional

from storage.batch import SessionStore

from .models.data_types import DataSubType
from .models.records import LocalDataRecord, LocalFileRecord
from .models.state import DeviceInfo, DeviceStateManager, get_device_state_manager
from .registry import registry


class SessionCollector:
    """一次会话的采集执行器。

    实例本身不保存循环状态，可对同一会话反复调用 collect_once()。
    """

    def __init__(
        self,
        session_id: str,
        session_name: str = "",
        store: Optional[SessionStore] = None,
        state_manager: Optional[DeviceStateManager] = None,
        file_subtype: Optional[DataSubType] = DataSubType.RGB,
    ):
        self.session_id = session_id
        self.session_name = session_name
        self.store = store or SessionStore(session_id, session_name)
        self.state_manager = state_manager or get_device_state_manager()
        # 传给支持文件采集的设备；None 表示本轮不做文件采集
        self.file_subtype = file_subtype

    # -----------------------------------------------------------------
    # 单轮采集
    # -----------------------------------------------------------------

    def prepare(self) -> str:
        """建目录、CSV 表头与 meta.json（幂等）。返回会话目录。"""
        return self.store.ensure()

    def collect_once(self) -> int:
        """对会话下所有已分配设备各执行一次采集。

        Returns:
            本轮实际落盘的记录数（数值行 + 文件）
        """
        total = 0
        for info in self.state_manager.get_session_devices(self.session_id):
            total += self._collect_device(info)
        return total

    def _collect_device(self, info: DeviceInfo) -> int:
        """通过注册表创建设备并采集。未注册的类型安全跳过。"""
        device = registry.create(info)
        if device is None:
            return 0

        batch = device.collect(
            session_id=self.session_id,
            file_subtype=self.file_subtype,
        )

        written = 0
        for record in batch.records:
            if isinstance(record, LocalDataRecord):
                self.store.append_numeric(record)
                written += 1
            elif isinstance(record, LocalFileRecord):
                # 文件已由设备自身写入 images 目录，此处仅计数
                written += 1
        return written

    # -----------------------------------------------------------------
    # 采集循环（供后台线程调用）
    # -----------------------------------------------------------------

    def run(
        self,
        should_continue: Callable[[], bool],
        interval: float = 1.0,
        on_round: Optional[Callable[[int, int], None]] = None,
    ) -> None:
        """阻塞式采集循环，直到 should_continue() 返回 False。

        Args:
            should_continue: 无参回调，返回 False 时退出
            interval:        每轮间隔（秒）
            on_round:        每轮回调，参数为 (累计条数, 本轮条数)
        """
        self.prepare()
        total = 0
        while should_continue():
            try:
                round_count = self.collect_once()
                total += round_count
            except Exception as e:
                # 单台设备故障不应中断整轮循环，本轮按 0 条上报
                print(f"采集错误: {e}")
                round_count = 0

            # 无论成功或出错都回调，调用方才能刷新进度并决定是否停止
            if on_round is not None:
                on_round(total, round_count)

            if not should_continue():
                break
            time.sleep(interval)


__all__ = ["SessionCollector"]
