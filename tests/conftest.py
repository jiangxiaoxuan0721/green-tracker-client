"""pytest 全局配置与共享 fixture。"""
import os
import sys
from pathlib import Path

# 必须在导入任何 PyQt6 模块之前设置，保证 headless 环境可用
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


@pytest.fixture(autouse=True)
def isolate_environment(tmp_path, monkeypatch):
    """将 HOME 重定向到临时目录，并重置设备状态管理器单例。

    - 避免测试污染真实的 ~/green_tracker_data
    - 重置 DeviceStateManager 单例，保证用例之间相互隔离
    """
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("USERPROFILE", str(tmp_path))

    try:
        import device.models.state as state_mod
    except Exception:  # pragma: no cover - 防御性
        state_mod = None
    if state_mod is not None:
        monkeypatch.setattr(state_mod, "_device_state_manager", None, raising=False)
    yield


@pytest.fixture(scope="session")
def qapp():
    """会话级 QApplication（offscreen 平台，供 MQTT 信号测试使用）。"""
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PyQt6.QtWidgets import QApplication

    app = QApplication.instance() or QApplication([])
    yield app
