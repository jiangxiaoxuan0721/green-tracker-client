"""mqtt.topics — Topic 构造规则测试。

契约：``green-tracker/device/{device_id}/{msg_type}``
``device_id`` 省略时回退到环境变量 ``MQTT_DEVICE_ID``。
"""
import importlib

import pytest

topics = importlib.import_module("mqtt.topics")


@pytest.fixture(autouse=True)
def _no_env_device_id(monkeypatch):
    """默认清空环境变量，避免开发机上的真实 .env 影响断言。"""
    monkeypatch.delenv("MQTT_DEVICE_ID", raising=False)


class TestPrefix:
    def test_prefix_constant(self):
        assert topics.TOPIC_PREFIX == "green-tracker"


class TestDeviceScopedTopics:
    def test_explicit_device_id(self):
        assert topics.status_topic("dev1") == "green-tracker/device/dev1/status"
        assert topics.response_topic("dev1") == "green-tracker/device/dev1/response"
        assert topics.command_topic("dev1") == "green-tracker/device/dev1/command"
        assert topics.lwt_topic("dev1") == "green-tracker/device/dev1/lwt"
        assert topics.announce_topic("dev1") == "green-tracker/device/dev1/announce"

    def test_env_fallback_when_id_omitted(self, monkeypatch):
        monkeypatch.setenv("MQTT_DEVICE_ID", "env-dev")
        assert topics.status_topic() == "green-tracker/device/env-dev/status"
        assert topics.response_topic() == "green-tracker/device/env-dev/response"
        assert topics.command_topic() == "green-tracker/device/env-dev/command"
        assert topics.lwt_topic() == "green-tracker/device/env-dev/lwt"
        assert topics.announce_topic() == "green-tracker/device/env-dev/announce"

    def test_explicit_id_takes_precedence_over_env(self, monkeypatch):
        monkeypatch.setenv("MQTT_DEVICE_ID", "env-dev")
        assert topics.status_topic("explicit") == "green-tracker/device/explicit/status"

    def test_all_device_topics_have_four_levels(self, monkeypatch):
        """所有单播 topic 均为 4 层，通配订阅才能按位置匹配。"""
        monkeypatch.setenv("MQTT_DEVICE_ID", "abc")
        builders = (
            topics.status_topic,
            topics.response_topic,
            topics.command_topic,
            topics.lwt_topic,
            topics.announce_topic,
        )
        for build in builders:
            assert len(build().split("/")) == 4

    def test_empty_device_id_yields_empty_segment(self):
        """记录当前行为：device_id 缺失时不会报错，但会产出空段 topic。"""
        assert topics.status_topic("") == "green-tracker/device//status"


class TestWildcards:
    def test_status_wildcard(self):
        assert topics.all_device_status_topic() == "green-tracker/device/+/status"

    def test_lwt_wildcard(self):
        assert topics.all_device_lwt_topic() == "green-tracker/device/+/lwt"

    def test_announce_wildcard(self):
        assert topics.all_announce_topic() == "green-tracker/device/+/announce"

    @pytest.mark.parametrize("wildcard_builder, suffix", [
        ("all_device_status_topic", "status"),
        ("all_device_lwt_topic", "lwt"),
        ("all_announce_topic", "announce"),
    ])
    def test_wildcard_matches_single_device_topic(self, wildcard_builder, suffix):
        """通配 topic 与单播 topic 层数一致，且 '+' 恰好占据 device_id 所在层。"""
        wildcard = getattr(topics, wildcard_builder)()
        concrete = f"green-tracker/device/some-device-id/{suffix}"

        assert len(wildcard.split("/")) == len(concrete.split("/"))
        assert wildcard.split("/")[2] == "+"

        matched = all(
            w == "+" or w == c
            for w, c in zip(wildcard.split("/"), concrete.split("/"))
        )
        assert matched is True
