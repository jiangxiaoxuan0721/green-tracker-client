#!/usr/bin/env python3
"""生成用户配置模板 —— 已存在的文件**绝不覆盖**。

安装 / 升级时调用：

    python3 packaging/common/prepare_config.py [配置目录]

不传配置目录时按 `config.config_dir()` 解析（Linux: ~/.config/green-tracker-client，
Windows: %APPDATA%\\GreenTrackerClient），也可由 GREEN_TRACKER_CONFIG_DIR 指定。

输出一行 JSON 摘要，便于安装脚本打印：`{"config_dir": ..., "files": {".env": "created", ...}}`
每个文件的取值为 created（新生成）/ kept（已存在，保留）/ missing_source（源模板缺失）。
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
from pathlib import Path
from typing import Dict

REPO_ROOT = Path(__file__).resolve().parents[2]

TEMPLATES = (
    (".env.example", ".env"),
    (os.path.join("config", "command_policy.json"), "command_policy.json"),
)


def repo_root() -> Path:
    """仓库根目录（packaging/common/ 的上两级）。"""
    return REPO_ROOT


def default_config_dir() -> str:
    """默认配置目录：GREEN_TRACKER_CONFIG_DIR > config.config_dir()。"""
    raw = (os.getenv("GREEN_TRACKER_CONFIG_DIR") or "").strip()
    if raw:
        return os.path.expanduser(raw)

    sys.path.insert(0, str(repo_root()))
    import config  # 延迟导入：本脚本可能被直接以文件路径方式执行

    return config.config_dir()


def _copy_if_absent(source: Path, target: Path) -> str:
    """目标已存在则原样保留；否则从源模板复制。"""
    if target.exists():
        return "kept"
    if not source.exists():
        return "missing_source"
    shutil.copyfile(source, target)
    return "created"


def prepare(config_dir: str) -> Dict[str, object]:
    """在 config_dir 下补齐配置模板，返回摘要。"""
    target_dir = Path(config_dir).expanduser()
    target_dir.mkdir(parents=True, exist_ok=True)

    files = {}
    for rel_source, rel_target in TEMPLATES:
        files[rel_target] = _copy_if_absent(
            repo_root() / rel_source, target_dir / rel_target)

    return {"config_dir": str(target_dir), "files": files}


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="生成 green-tracker-client 配置模板")
    parser.add_argument("config_dir", nargs="?",
                        help="目标配置目录，缺省时按 config.config_dir() 解析")
    args = parser.parse_args(argv)

    print(json.dumps(prepare(args.config_dir or default_config_dir()),
                     ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
