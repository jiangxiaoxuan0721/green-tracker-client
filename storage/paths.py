"""本地文件系统的目录约定 — 全项目唯一的路径拼接处。

目录布局：
    {DATA_ROOT}/
    ├── device_assignments.json      # 执行单元分配关系
    └── {session_id}/
        ├── data.csv                 # 采集数据（CSV_HEADER 见 storage.batch）
        ├── meta.json                # 会话元信息
        ├── images/                  # 采集的图片文件
        └── images_status.json       # 图片上传状态

所有路径均为惰性解析，不缓存 HOME。
"""
from __future__ import annotations

import os

import config

ASSIGNMENT_FILENAME = "device_assignments.json"
DATA_CSV_FILENAME = "data.csv"
META_FILENAME = "meta.json"
IMAGES_DIRNAME = "images"
IMAGE_STATUS_FILENAME = "images_status.json"


def data_root() -> str:
    """数据根目录。"""
    return config.data_root()


def ensure_dir(path: str) -> str:
    """确保目录存在并返回该路径。"""
    os.makedirs(path, exist_ok=True)
    return path


def device_assignment_json() -> str:
    """执行单元分配关系文件路径。"""
    return os.path.join(data_root(), ASSIGNMENT_FILENAME)


def session_dir(session_id: str) -> str:
    """会话目录。"""
    return os.path.join(data_root(), str(session_id))


def data_csv(session_id: str) -> str:
    """会话数据 CSV 路径。"""
    return os.path.join(session_dir(session_id), DATA_CSV_FILENAME)


def meta_json(session_id: str) -> str:
    """会话元信息路径。"""
    return os.path.join(session_dir(session_id), META_FILENAME)


def images_dir(session_id: str) -> str:
    """会话图片目录。"""
    return os.path.join(session_dir(session_id), IMAGES_DIRNAME)


def images_status_json(session_id: str) -> str:
    """会话图片上传状态文件路径。"""
    return os.path.join(session_dir(session_id), IMAGE_STATUS_FILENAME)
