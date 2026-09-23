"""
云端设备指令通道 HTTP 客户端（`/api/device-commands`）。

设备侧只认三件事 —— 签到、取指令、回执；权限由云端在密钥上开关，
本模块**不解析权限含义**，只把 HTTP 状态翻译成可退避的异常类型。

约定（见《设备端接入说明》）：
  * 所有请求带 `X-API-Key`（= SECRET_KEY）与 `X-Device-Id`（= MQTT_DEVICE_ID）
  * 响应信封：`{"code": 200, "message": "success", "data": ...}`
  * 401 凭证无效 → `AuthError`（固定退避重试）
  * 403 未开放该能力 → `ForbiddenError`（静默降级，等下次签到）
  * 5xx / 网络错误 → `TransientError`（指数退避）
"""
from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

import requests

from config import api_base_url, api_timeout, device_id, secret_key

logger = logging.getLogger("device-commands")

BASE_PATH = "/api/device-commands"

STATUS_ACKED = "acked"
STATUS_FAILED = "failed"
_VALID_STATUS = (STATUS_ACKED, STATUS_FAILED)


class DeviceCommandError(Exception):
    """设备指令通道错误基类。"""

    def __init__(self, message: str, status_code: Optional[int] = None):
        super().__init__(message)
        self.status_code = status_code


class AuthError(DeviceCommandError):
    """401 — 凭证无效或缺失。"""


class ForbiddenError(DeviceCommandError):
    """403 — 云端未向本设备开放该能力。"""


class TransientError(DeviceCommandError):
    """5xx / 网络错误 — 可重试。"""


def _headers() -> Dict[str, str]:
    key = secret_key()
    if not key:
        raise AuthError("缺少云端凭证，请在 .env 中配置 SECRET_KEY")
    return {"X-API-Key": key, "X-Device-Id": device_id()}


def _unwrap(payload: Any) -> Any:
    """解包云端响应信封 `{code, message, data}`。"""
    if isinstance(payload, dict) and "data" in payload:
        return payload["data"]
    return payload


def _request(method: str, path: str, *, params: Optional[dict] = None,
             json_body: Optional[dict] = None) -> Any:
    url = f"{api_base_url()}{BASE_PATH}{path}"
    try:
        resp = requests.request(
            method, url, headers=_headers(), params=params, json=json_body,
            timeout=api_timeout(),
        )
    except requests.RequestException as e:
        raise TransientError(f"网络错误: {e}")

    code = getattr(resp, "status_code", 200)
    if code == 401:
        raise AuthError("凭证无效或缺失", code)
    if code == 403:
        raise ForbiddenError("云端未向本设备开放该能力", code)
    if code >= 500:
        raise TransientError(f"云端异常: HTTP {code}", code)
    if code >= 400:
        raise DeviceCommandError(f"请求失败: HTTP {code}", code)

    try:
        return _unwrap(resp.json())
    except ValueError:
        logger.warning("云端返回非 JSON 响应: %s %s", method, url)
        return None


def heartbeat() -> dict:
    """签到 —— 告诉云端「我在线」，拿回能力开关。

    Returns:
        `data` 字典：`{device_id, registered, capabilities, command_channel,
        poll_interval_seconds, server_time}`；云端不可达时抛异常。
    """
    data = _request("POST", "/heartbeat") or {}
    return data if isinstance(data, dict) else {}


def fetch_pending() -> List[dict]:
    """取指令（HTTP 通道）—— 返回待执行指令数组，无指令时为空列表。"""
    data = _request("GET", "/pending", params={"device_id": device_id()})
    if isinstance(data, dict):
        data = data.get("commands") or []
    if not isinstance(data, list):
        return []
    return [c for c in data if isinstance(c, dict)]


def report_result(command_id: str, status: str, result: Any = None,
                  error_message: Optional[str] = None) -> None:
    """回执 —— 每条指令都要回，不回执会被云端判定超时。

    Args:
        command_id: 指令 ID（MQTT 报文里的原值）
        status: 仅 `acked` / `failed`
        result: 成功时的返回体
        error_message: 失败原因（建议提供）
    """
    if not command_id:
        raise ValueError("command_id 不能为空")
    if status not in _VALID_STATUS:
        raise ValueError(f"status 只能是 {' / '.join(_VALID_STATUS)}，收到: {status}")

    body: Dict[str, Any] = {"status": status}
    if result is not None:
        body["result"] = result
    if error_message:
        body["error_message"] = error_message

    _request("POST", f"/{command_id}/result", json_body=body)
