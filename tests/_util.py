"""测试共享工具（被多个测试文件引用）。"""
import json
from types import SimpleNamespace


class DummyResponse:
    """模拟 requests.Response 的最小实现。"""

    def __init__(self, json_data=None, status_code=200, text="", headers=None,
                 content=b""):
        self._json = json_data if json_data is not None else {}
        self.status_code = status_code
        self.text = text
        self.headers = headers or {}
        self.content = content

    def json(self):
        return self._json

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")

    def close(self):
        pass


class FakeSocket:
    """模拟 socket.socket，用于端口探测测试。"""

    def __init__(self, connect_result=0):
        self._result = connect_result
        self.closed = False

    def settimeout(self, timeout):
        pass

    def connect_ex(self, address):
        return self._result

    def close(self):
        self.closed = True


def make_msg(topic, payload):
    """构造一个模拟的 paho MQTTMessage。"""
    return SimpleNamespace(topic=topic, payload=json.dumps(payload).encode("utf-8"))


def make_raw_msg(topic, raw_bytes):
    """构造一个 payload 为原始字节的模拟 MQTTMessage。"""
    return SimpleNamespace(topic=topic, payload=raw_bytes)
