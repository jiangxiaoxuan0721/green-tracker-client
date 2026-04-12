"""
任务管理器 - 管理多个采集任务
"""
import threading
from typing import Dict, Optional
from datetime import datetime


class CollectionTask:
    """单个采集任务"""

    def __init__(self, session_id: str, session_name: str, data_dir: str):
        self.session_id = session_id
        self.session_name = session_name
        self.data_dir = data_dir
        self.is_running = False
        self.collected_count = 0
        self.start_time: Optional[datetime] = None
        self.end_time: Optional[datetime] = None
        self.thread: Optional[threading.Thread] = None
        self.stop_event = threading.Event()

    def is_active(self) -> bool:
        return self.is_running


class TaskManager:
    """任务管理器 - 单例"""

    _instance = None
    _lock = threading.Lock()

    def __new__(cls):
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = super().__new__(cls)
                    cls._instance._tasks: Dict[str, CollectionTask] = {}
                    cls._instance._task_lock = threading.Lock()
        return cls._instance

    def create_task(self, session_id: str, session_name: str, data_dir: str) -> CollectionTask:
        """创建或获取任务"""
        with self._task_lock:
            if session_id not in self._tasks:
                self._tasks[session_id] = CollectionTask(session_id, session_name, data_dir)
            return self._tasks[session_id]

    def get_task(self, session_id: str) -> Optional[CollectionTask]:
        """获取任务"""
        with self._task_lock:
            return self._tasks.get(session_id)

    def get_all_tasks(self) -> Dict[str, CollectionTask]:
        """获取所有任务"""
        with self._task_lock:
            return dict(self._tasks)

    def remove_task(self, session_id: str):
        """移除任务"""
        with self._task_lock:
            if session_id in self._tasks:
                task = self._tasks[session_id]
                if task.is_running:
                    task.stop_event.set()
                del self._tasks[session_id]

    def get_active_count(self) -> int:
        """获取活跃任务数"""
        with self._task_lock:
            return sum(1 for t in self._tasks.values() if t.is_running)


# 全局任务管理器
task_manager = TaskManager()


def get_task_manager() -> TaskManager:
    return task_manager
