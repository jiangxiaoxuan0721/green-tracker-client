"""pytest 全局配置与共享 fixture。"""
import os
import sys
from pathlib import Path
from types import SimpleNamespace

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
    - 指令启用策略指向临时目录下的**不存在**文件：测试结果不随仓库内
      config/command_policy.json 的改动而变化（该文件是真实生效的默认策略）
    """
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("USERPROFILE", str(tmp_path))
    # 测试期间禁止真实云端签到（避免打到本地/线上后端并污染能力状态）
    monkeypatch.setenv("GREEN_TRACKER_HEARTBEAT", "0")
    monkeypatch.setenv("GREEN_TRACKER_COMMAND_POLICY_FILE",
                       str(tmp_path / "command_policy.json"))

    try:
        import device.models.state as state_mod
    except Exception:  # pragma: no cover - 防御性
        state_mod = None
    if state_mod is not None:
        monkeypatch.setattr(state_mod, "_device_state_manager", None, raising=False)

    # 重置云端能力状态单例，避免用例之间互相污染
    try:
        import api.cloud_state as cloud_mod
    except Exception:  # pragma: no cover - 防御性
        cloud_mod = None
    if cloud_mod is not None:
        monkeypatch.setattr(cloud_mod, "_global_state", None, raising=False)

    # 云端指令通道默认打桩传输层：任何测试都不应发起真实 HTTP
    # （打桩 requests 而非业务函数，保证 api/device_commands 自身测试仍可替换它）
    try:
        import api.device_commands as dc_mod
    except Exception:  # pragma: no cover - 防御性
        dc_mod = None
    if dc_mod is not None:
        def _no_network(*_args, **_kwargs):
            raise dc_mod.TransientError("测试环境禁止真实 HTTP 请求")

        monkeypatch.setattr(
            dc_mod, "requests",
            SimpleNamespace(request=_no_network,
                            RequestException=RuntimeError),
            raising=False)
    yield


@pytest.fixture(scope="session")
def qapp():
    """会话级 QApplication（offscreen 平台，供 MQTT 信号测试使用）。"""
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PyQt6.QtWidgets import QApplication

    app = QApplication.instance() or QApplication([])
    yield app
