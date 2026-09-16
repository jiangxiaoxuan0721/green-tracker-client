"""storage.paths 测试 — 路径必须挂在 DATA_ROOT 下且层级正确。"""
import os

from storage import paths


def test_data_root_delegates_to_config():
    import config
    assert paths.data_root() == config.data_root()


def test_session_layout_paths():
    sid = "sess-123"
    root = paths.data_root()

    assert paths.session_dir(sid) == os.path.join(root, sid)
    assert paths.data_csv(sid) == os.path.join(root, sid, "data.csv")
    assert paths.meta_json(sid) == os.path.join(root, sid, "meta.json")
    assert paths.images_dir(sid) == os.path.join(root, sid, "images")
    assert paths.images_status_json(sid) == os.path.join(
        root, sid, "images_status.json"
    )


def test_device_assignment_file_at_root():
    assert paths.device_assignment_json() == os.path.join(
        paths.data_root(), "device_assignments.json"
    )


def test_all_paths_are_under_data_root():
    root = paths.data_root()
    sid = "../weird-id"  # 非预期输入也不应脱离根目录之外的其他层级
    for p in (
        paths.session_dir(sid),
        paths.data_csv(sid),
        paths.meta_json(sid),
        paths.images_dir(sid),
        paths.images_status_json(sid),
        paths.device_assignment_json(),
    ):
        assert os.path.isabs(p)
        assert p.startswith(root)


def test_ensure_dir_creates_and_is_idempotent(tmp_path):
    target = str(tmp_path / "a" / "b")
    assert paths.ensure_dir(target) == target
    assert os.path.isdir(target)
    assert paths.ensure_dir(target) == target


def test_paths_follow_home_redirection(monkeypatch, tmp_path):
    """HOME 重定向后路径必须跟随（惰性解析，不缓存）。"""
    monkeypatch.delenv("GREEN_TRACKER_DATA_DIR", raising=False)
    monkeypatch.setenv("HOME", str(tmp_path))
    assert paths.session_dir("s1") == str(tmp_path / "green_tracker_data" / "s1")
