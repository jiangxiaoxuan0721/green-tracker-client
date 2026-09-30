"""packaging/common/prepare_config.py —— 安装时生成配置模板。

核心约束：用户已经改过的配置**绝不覆盖**（重装 / 升级都要保住）。
"""
import importlib.util
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
MODULE_PATH = ROOT / "packaging" / "common" / "prepare_config.py"


def _load():
    spec = importlib.util.spec_from_file_location("prepare_config", MODULE_PATH)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_creates_both_templates(tmp_path):
    prepare_config = _load()
    result = prepare_config.prepare(str(tmp_path))

    assert (tmp_path / ".env").exists()
    assert (tmp_path / "command_policy.json").exists()
    assert result["files"] == {".env": "created",
                               "command_policy.json": "created"}


def test_existing_files_are_never_overwritten(tmp_path):
    prepare_config = _load()
    prepare_config.prepare(str(tmp_path))

    (tmp_path / ".env").write_text("SECRET_KEY=my-own-key\n", encoding="utf-8")
    (tmp_path / "command_policy.json").write_text('{"reboot": false}',
                                                  encoding="utf-8")

    result = prepare_config.prepare(str(tmp_path))

    assert (tmp_path / ".env").read_text(encoding="utf-8") == \
        "SECRET_KEY=my-own-key\n"
    assert (tmp_path / "command_policy.json").read_text(encoding="utf-8") == \
        '{"reboot": false}'
    assert result["files"] == {".env": "kept", "command_policy.json": "kept"}


def test_creates_config_dir_when_missing(tmp_path):
    prepare_config = _load()
    target = tmp_path / "nested" / "config"

    prepare_config.prepare(str(target))

    assert target.is_dir()
    assert (target / ".env").exists()


def test_templates_come_from_repo(tmp_path):
    prepare_config = _load()
    prepare_config.prepare(str(tmp_path))

    env_example = (ROOT / ".env.example").read_text(encoding="utf-8")
    assert (tmp_path / ".env").read_text(encoding="utf-8") == env_example
