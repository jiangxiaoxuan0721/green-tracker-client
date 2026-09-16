"""device.task_manager — 任务管理器单例与增删查测试。"""
import importlib
import threading

import pytest

tm = importlib.import_module("device.task_manager")
TaskManager = tm.TaskManager
CollectionTask = tm.CollectionTask


@pytest.fixture
def manager(monkeypatch):
    """每个用例拿到全新的单例实例。"""
    monkeypatch.setattr(TaskManager, "_instance", None)
    return TaskManager()


# ============================================================
# 单例
# ============================================================

class TestSingleton:
    def test_new_always_returns_same_instance(self, manager):
        assert TaskManager() is manager

    def test_multiple_calls_share_state(self, manager):
        manager.create_task("s1", "任务一", "/d")
        assert TaskManager().get_task("s1") is not None

    def test_global_accessor_returns_module_instance(self):
        assert tm.get_task_manager() is tm.task_manager


# ============================================================
# CollectionTask
# ============================================================

class TestCollectionTask:
    def test_initial_state(self):
        task = CollectionTask("s1", "任务一", "/tmp/data")

        assert task.session_id == "s1"
        assert task.session_name == "任务一"
        assert task.data_dir == "/tmp/data"
        assert task.is_running is False
        assert task.is_active() is False
        assert task.collected_count == 0
        assert task.start_time is None
        assert task.end_time is None
        assert task.thread is None
        assert isinstance(task.stop_event, threading.Event)
        assert task.stop_event.is_set() is False


# ============================================================
# 增删查
# ============================================================

class TestCreateTask:
    def test_creates_and_stores_task(self, manager):
        task = manager.create_task("s1", "任务一", "/d")
        assert isinstance(task, CollectionTask)
        assert manager.get_task("s1") is task

    def test_same_session_id_is_idempotent(self, manager):
        first = manager.create_task("s1", "任务一", "/d")
        second = manager.create_task("s1", "被忽略的新名字", "/other")

        assert second is first
        assert second.session_name == "任务一"      # 已存在时不覆盖
        assert second.data_dir == "/d"

    def test_different_sessions_are_independent(self, manager):
        a = manager.create_task("a", "A", "/d")
        b = manager.create_task("b", "B", "/d")
        assert a is not b
        assert set(manager.get_all_tasks()) == {"a", "b"}


class TestQueryTasks:
    def test_get_missing_returns_none(self, manager):
        assert manager.get_task("nope") is None

    def test_get_all_tasks_returns_defensive_copy(self, manager):
        manager.create_task("s1", "任务一", "/d")

        snapshot = manager.get_all_tasks()
        snapshot.clear()

        assert manager.get_task("s1") is not None

    def test_get_all_tasks_empty_by_default(self, manager):
        assert manager.get_all_tasks() == {}


class TestRemoveTask:
    def test_removes_existing_task(self, manager):
        manager.create_task("s1", "任务一", "/d")
        manager.remove_task("s1")
        assert manager.get_task("s1") is None

    def test_removing_missing_task_is_noop(self, manager):
        manager.remove_task("nope")          # 不应抛出

    def test_removing_running_task_signals_stop(self, manager):
        task = manager.create_task("s1", "任务一", "/d")
        task.is_running = True

        manager.remove_task("s1")

        assert task.stop_event.is_set() is True
        assert manager.get_task("s1") is None

    def test_removing_idle_task_does_not_set_stop_event(self, manager):
        task = manager.create_task("s1", "任务一", "/d")
        manager.remove_task("s1")
        assert task.stop_event.is_set() is False


class TestActiveCount:
    def test_counts_only_running_tasks(self, manager):
        a = manager.create_task("a", "A", "/d")
        b = manager.create_task("b", "B", "/d")
        manager.create_task("c", "C", "/d")

        assert manager.get_active_count() == 0

        a.is_running = True
        b.is_running = True
        assert manager.get_active_count() == 2

        a.is_running = False
        assert manager.get_active_count() == 1


class TestIsolation:
    def test_new_instance_starts_empty(self, manager, monkeypatch):
        manager.create_task("s1", "任务一", "/d")

        monkeypatch.setattr(TaskManager, "_instance", None)
        assert TaskManager().get_all_tasks() == {}
