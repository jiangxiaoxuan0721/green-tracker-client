"""images_status.json 的上传状态管理。

文件结构：
    {"<文件名>": {"uploaded": true, "upload_time": "<iso8601>"}, ...}
"""
from __future__ import annotations

import json
import os
from datetime import datetime
from typing import Dict, List, Optional

from . import paths


class UploadState:
    """某个会话内图片的上传状态。读写失败均安全降级，不影响上传主流程。"""

    def __init__(self, session_id: str, base_dir: Optional[str] = None):
        self.session_id = session_id
        self.base_dir = base_dir or paths.data_root()
        if base_dir:
            self.path = os.path.join(
                self.base_dir, session_id, paths.IMAGE_STATUS_FILENAME
            )
        else:
            self.path = paths.images_status_json(session_id)

    def load(self) -> Dict[str, dict]:
        """读取状态；文件缺失或损坏时返回空字典。"""
        if not os.path.exists(self.path):
            return {}
        try:
            with open(self.path, "r", encoding="utf-8") as f:
                data = json.load(f)
            return data if isinstance(data, dict) else {}
        except Exception as e:
            print(f"加载图片状态失败: {e}")
            return {}

    def save(self, state: Dict[str, dict]) -> None:
        try:
            paths.ensure_dir(os.path.dirname(self.path))
            with open(self.path, "w", encoding="utf-8") as f:
                json.dump(state, f, ensure_ascii=False, indent=2)
        except Exception as e:
            print(f"保存图片状态失败: {e}")

    def is_uploaded(self, filename: str, state: Optional[Dict[str, dict]] = None) -> bool:
        state = self.load() if state is None else state
        return bool(state.get(filename, {}).get("uploaded", False))

    def mark_uploaded(self, filename: str,
                      state: Optional[Dict[str, dict]] = None) -> Dict[str, dict]:
        """标记已上传并返回状态字典（不落盘，由调用方批量 save）。"""
        state = self.load() if state is None else state
        state[filename] = {
            "uploaded": True,
            "upload_time": datetime.now().isoformat(),
        }
        return state

    def pending_images(self, filenames: List[str],
                       state: Optional[Dict[str, dict]] = None) -> List[str]:
        """筛出尚未上传的文件名。"""
        state = self.load() if state is None else state
        return [f for f in filenames if not state.get(f, {}).get("uploaded", False)]
