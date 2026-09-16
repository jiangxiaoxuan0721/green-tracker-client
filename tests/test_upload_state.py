"""storage.upload_state 测试 — images_status.json 的读写与降级。"""
import json
import os

from storage.upload_state import UploadState


def _state(tmp_path, session_id="sess-1"):
    return UploadState(session_id, base_dir=str(tmp_path))


class TestLoadSave:
    def test_missing_file_returns_empty(self, tmp_path):
        assert _state(tmp_path).load() == {}

    def test_roundtrip(self, tmp_path):
        st = _state(tmp_path)
        st.save({"a.jpg": {"uploaded": True, "upload_time": "2024-01-01T00:00:00"}})
        assert st.load()["a.jpg"]["uploaded"] is True

    def test_save_creates_parent_directory(self, tmp_path):
        st = _state(tmp_path, "nested-session")
        st.save({"a.jpg": {"uploaded": True}})
        assert os.path.isfile(st.path)

    def test_corrupt_json_degrades_to_empty(self, tmp_path):
        st = _state(tmp_path)
        os.makedirs(os.path.dirname(st.path), exist_ok=True)
        with open(st.path, "w", encoding="utf-8") as f:
            f.write("{ not json")
        assert st.load() == {}

    def test_non_dict_json_degrades_to_empty(self, tmp_path):
        st = _state(tmp_path)
        os.makedirs(os.path.dirname(st.path), exist_ok=True)
        with open(st.path, "w", encoding="utf-8") as f:
            json.dump(["unexpected"], f)
        assert st.load() == {}

    def test_written_file_is_utf8_json(self, tmp_path):
        st = _state(tmp_path)
        st.save({"图像.jpg": {"uploaded": True}})
        with open(st.path, encoding="utf-8") as f:
            raw = json.load(f)
        assert "图像.jpg" in raw


class TestQueries:
    def test_is_uploaded(self, tmp_path):
        st = _state(tmp_path)
        st.save({"a.jpg": {"uploaded": True}, "b.jpg": {"uploaded": False}})
        assert st.is_uploaded("a.jpg") is True
        assert st.is_uploaded("b.jpg") is False
        assert st.is_uploaded("missing.jpg") is False

    def test_mark_uploaded_returns_state_without_saving(self, tmp_path):
        st = _state(tmp_path)
        state = st.mark_uploaded("a.jpg", state={})
        assert state["a.jpg"]["uploaded"] is True
        assert state["a.jpg"]["upload_time"]
        assert st.load() == {}  # 未落盘

    def test_mark_uploaded_then_save(self, tmp_path):
        st = _state(tmp_path)
        st.save(st.mark_uploaded("a.jpg"))
        assert st.is_uploaded("a.jpg") is True

    def test_pending_images(self, tmp_path):
        st = _state(tmp_path)
        st.save({"a.jpg": {"uploaded": True}})
        pending = st.pending_images(["a.jpg", "b.jpg", "c.jpg"])
        assert pending == ["b.jpg", "c.jpg"]

    def test_pending_images_accepts_preloaded_state(self, tmp_path):
        st = _state(tmp_path)
        state = {"a.jpg": {"uploaded": True}}
        assert st.pending_images(["a.jpg", "b.jpg"], state=state) == ["b.jpg"]


def test_path_uses_session_subdirectory(tmp_path):
    st = _state(tmp_path)
    assert st.path == os.path.join(str(tmp_path), "sess-1", "images_status.json")
