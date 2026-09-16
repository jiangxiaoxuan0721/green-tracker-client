"""会话本地落盘 — CSV / meta.json / images 的统一读写。

CSV 表头与列序是全项目唯一约定，任何写盘处都必须经过本模块：

    timestamp,sensor_id,data_type,value,unit,is_uploaded

设计说明：计数（data_count / image_count）不写入 meta.json，而是以
CSV 行数与 images 目录为准，避免每次追加记录都要「读-改-写」meta，
也避免计数与实际数据漂移。
"""
from __future__ import annotations

import csv
import json
import os
from datetime import datetime
from typing import Any, Dict, Iterable, List, Optional

from . import paths

# ============================================================
# CSV 约定
# ============================================================
CSV_HEADER = "timestamp,sensor_id,data_type,value,unit,is_uploaded"
CSV_FIELDNAMES = ["timestamp", "sensor_id", "data_type", "value", "unit", "is_uploaded"]

DEFAULT_UNIT = "-"
IMAGE_EXTENSIONS = (".jpg", ".png", ".jpeg")
_UPLOADED_TRUE = {"true", "1", "yes"}


def format_unit(unit: Any) -> str:
    """统一单位取值：优先枚举的 .value，缺失时回退 '-'。"""
    value = getattr(unit, "value", unit)
    return str(value) if value else DEFAULT_UNIT


def is_uploaded(value: Any) -> bool:
    """CSV 中的 is_uploaded 判定（大小写不敏感）。"""
    return str(value).strip().lower() in _UPLOADED_TRUE


def record_to_row(record: Any, timestamp: Optional[str] = None) -> Dict[str, str]:
    """LocalDataRecord → CSV 行。全项目唯一的记录转换点。"""
    return {
        "timestamp": timestamp or datetime.now().isoformat(),
        "sensor_id": record.data_subtype.value,
        "data_type": record.data_type.value,
        "value": record.data_value,
        "unit": format_unit(getattr(record, "unit", None)),
        "is_uploaded": "False",
    }


# ============================================================
# 会话存储
# ============================================================
class SessionStore:
    """单个会话目录的读写。

    base_dir 决定数据根目录，默认取 config.data_root()；
    会话数据落在 {base_dir}/{session_id}/ 下。
    """

    def __init__(self, session_id: str, session_name: str = "",
                 base_dir: Optional[str] = None):
        self.session_id = session_id
        self.session_name = session_name
        self.base_dir = base_dir or paths.data_root()
        self.data_dir = os.path.join(self.base_dir, session_id)

    # ---------------- 路径 ----------------
    @property
    def csv_path(self) -> str:
        return os.path.join(self.data_dir, paths.DATA_CSV_FILENAME)

    @property
    def meta_path(self) -> str:
        return os.path.join(self.data_dir, paths.META_FILENAME)

    @property
    def images_dir(self) -> str:
        return os.path.join(self.data_dir, paths.IMAGES_DIRNAME)

    # ---------------- 初始化 ----------------
    def ensure(self) -> str:
        """建目录、建 CSV 表头、建 meta.json（幂等）。返回会话目录。"""
        paths.ensure_dir(self.data_dir)
        paths.ensure_dir(self.images_dir)

        if not os.path.exists(self.csv_path):
            with open(self.csv_path, "w", encoding="utf-8") as f:
                f.write(CSV_HEADER + "\n")

        if not os.path.exists(self.meta_path):
            now = datetime.now().isoformat()
            self.write_meta({
                "session_id": self.session_id,
                "session_name": self.session_name,
                "created_at": now,
                "start_time": now,
                "end_time": None,
            })
        return self.data_dir

    def finish(self) -> None:
        """标记会话结束（写入 meta.json 的 end_time）。"""
        if not os.path.exists(self.meta_path):
            return
        meta = self.read_meta()
        meta["end_time"] = datetime.now().isoformat()
        self.write_meta(meta)

    # ---------------- meta ----------------
    def read_meta(self) -> Dict[str, Any]:
        if not os.path.exists(self.meta_path):
            return {}
        try:
            with open(self.meta_path, "r", encoding="utf-8") as f:
                data = json.load(f)
            return data if isinstance(data, dict) else {}
        except Exception as e:
            print(f"读取 meta 失败: {e}")
            return {}

    def write_meta(self, meta: Dict[str, Any]) -> None:
        try:
            paths.ensure_dir(self.data_dir)
            with open(self.meta_path, "w", encoding="utf-8") as f:
                json.dump(meta, f, ensure_ascii=False, indent=2)
        except Exception as e:
            print(f"写入 meta 失败: {e}")

    # ---------------- CSV 写入 ----------------
    def append_rows(self, rows: Iterable[Dict[str, Any]]) -> int:
        """追加若干行（自动补齐缺失列）。返回追加行数。"""
        rows = list(rows)
        if not rows:
            return 0
        paths.ensure_dir(self.data_dir)
        with open(self.csv_path, "a", encoding="utf-8", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=CSV_FIELDNAMES)
            for row in rows:
                writer.writerow({k: row.get(k, "") for k in CSV_FIELDNAMES})
        return len(rows)

    def append_numeric(self, record: Any) -> Dict[str, str]:
        """追加一条数值记录，返回实际落盘的行。"""
        row = record_to_row(record)
        self.append_rows([row])
        return row

    def write_rows(self, rows: Iterable[Dict[str, Any]]) -> None:
        """整表回写（用于更新 is_uploaded 标记），总是写出标准表头。"""
        paths.ensure_dir(self.data_dir)
        with open(self.csv_path, "w", encoding="utf-8", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=CSV_FIELDNAMES)
            writer.writeheader()
            for row in rows:
                writer.writerow({k: row.get(k, "") for k in CSV_FIELDNAMES})

    # ---------------- CSV 读取 ----------------
    def read_rows(self) -> List[Dict[str, str]]:
        """安全读取 CSV 行，自动修复缺失表头。

        三种情形（沿用原 UploadWorker 的兼容语义）：
          1. 标准表头        → 按文件自身表头解析
          2. 无表头（首行是时间戳）→ 套用 CSV_FIELDNAMES
          3. 非标准表头      → 按文件自身表头解析，并跳过被误读的表头行
        """
        if not os.path.exists(self.csv_path):
            return []
        try:
            with open(self.csv_path, "r", encoding="utf-8") as f:
                first_line = f.readline().strip()
                if not first_line:
                    return []

                has_header = first_line.replace(" ", "") == CSV_HEADER.replace(" ", "")
                if not has_header and not first_line.startswith("20"):
                    has_header = True  # 首行看起来是表头（非时间戳开头）

                f.seek(0)
                reader = csv.DictReader(
                    f, fieldnames=None if has_header else CSV_FIELDNAMES
                )
                rows: List[Dict[str, str]] = []
                for row in reader:
                    if not has_header and (
                        row.get("timestamp") == CSV_FIELDNAMES[0]
                        or row.get("sensor_id") == "sensor_id"
                    ):
                        continue  # 跳过被误读的表头行
                    rows.append(row)  # type: ignore[arg-type]
                return rows
        except Exception as e:
            print(f"读取CSV失败: {e}")
            return []

    # ---------------- images ----------------
    def list_images(self) -> List[str]:
        """会话图片目录下的图片文件名（已排序）。"""
        if not os.path.isdir(self.images_dir):
            return []
        return sorted(
            f for f in os.listdir(self.images_dir)
            if f.lower().endswith(IMAGE_EXTENSIONS)
        )

    # ---------------- 汇总 ----------------
    def stats(self) -> Dict[str, int]:
        """已上传/待上传统计（图片状态取自 images_status.json）。"""
        from .upload_state import UploadState

        rows = self.read_rows()
        numeric_uploaded = sum(1 for r in rows if is_uploaded(r.get("is_uploaded")))
        numeric_pending = len(rows) - numeric_uploaded

        images = self.list_images()
        state = UploadState(self.session_id, base_dir=self.base_dir).load()
        image_uploaded = sum(1 for f in images if state.get(f, {}).get("uploaded", False))
        image_pending = len(images) - image_uploaded

        return {
            "numeric_total": len(rows),
            "numeric_uploaded": numeric_uploaded,
            "numeric_pending": numeric_pending,
            "image_total": len(images),
            "image_uploaded": image_uploaded,
            "image_pending": image_pending,
            "pending_total": numeric_pending + image_pending,
            "uploaded_total": numeric_uploaded + image_uploaded,
        }
