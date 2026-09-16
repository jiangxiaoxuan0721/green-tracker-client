"""device.device_scanner — 局域网扫描与设备识别测试。

全部依赖（socket / subprocess / requests / ping / 并发）均被打桩，不会真正出网。
"""
import importlib
from types import SimpleNamespace

import pytest
import requests

from _util import FakeSocket

scanner = importlib.import_module("device.device_scanner")


def _patch_socket(monkeypatch, sock=None, raise_exc=None):
    """把模块内的 socket 模块替换为最简替身。"""
    def factory(*_args, **_kwargs):
        if raise_exc is not None:
            raise raise_exc
        return sock

    monkeypatch.setattr(scanner, "socket", SimpleNamespace(
        socket=factory, AF_INET=2, SOCK_STREAM=1, SOCK_DGRAM=2))


def _router(routes):
    """按 URL 后缀分派假响应的 requests.get 替身。"""
    def fake_get(url, **_kwargs):
        for suffix, response in routes.items():
            if url.endswith(suffix):
                return SimpleNamespace(
                    status_code=response.get("status", 200),
                    headers=response.get("headers", {}),
                    text=response.get("text", ""),
                    close=lambda: None,
                )
        raise requests.exceptions.ConnectionError(url)

    return fake_get


# ============================================================
# 网络信息辅助函数
# ============================================================

class TestNetworkHelpers:
    def test_network_range_assumes_slash_24(self, monkeypatch):
        monkeypatch.setattr(scanner, "get_local_ip", lambda: "192.168.5.37")
        assert scanner.get_network_range() == ("192.168.5.1", "192.168.5.254")

    def test_local_ip_falls_back_on_socket_error(self, monkeypatch):
        _patch_socket(monkeypatch, raise_exc=OSError("no network"))
        assert scanner.get_local_ip() == "127.0.0.1"


class TestGatewayIp:
    def test_linux_route_parsing(self, monkeypatch):
        monkeypatch.setattr(scanner, "platform", SimpleNamespace(system=lambda: "Linux"))
        monkeypatch.setattr(scanner, "subprocess", SimpleNamespace(run=lambda *a, **k: SimpleNamespace(
            stdout="default via 192.168.1.1 dev eth0 proto dhcp src 192.168.1.20\n")))
        assert scanner.get_gateway_ip() == "192.168.1.1"

    def test_windows_ipconfig_parsing(self, monkeypatch):
        monkeypatch.setattr(scanner, "platform", SimpleNamespace(system=lambda: "Windows"))
        monkeypatch.setattr(scanner, "subprocess", SimpleNamespace(run=lambda *a, **k: SimpleNamespace(
            stdout="   Default Gateway . . . . . . . . . : 10.0.0.1\n")))
        assert scanner.get_gateway_ip() == "10.0.0.1"

    def test_returns_empty_when_command_fails(self, monkeypatch):
        def boom(*_args, **_kwargs):
            raise OSError("ip 命令不存在")

        monkeypatch.setattr(scanner, "platform", SimpleNamespace(system=lambda: "Linux"))
        monkeypatch.setattr(scanner, "subprocess", SimpleNamespace(run=boom))
        assert scanner.get_gateway_ip() == ""

    def test_returns_empty_when_no_via_token(self, monkeypatch):
        monkeypatch.setattr(scanner, "platform", SimpleNamespace(system=lambda: "Linux"))
        monkeypatch.setattr(scanner, "subprocess", SimpleNamespace(
            run=lambda *a, **k: SimpleNamespace(stdout="")))
        assert scanner.get_gateway_ip() == ""


# ============================================================
# 端口扫描
# ============================================================

class TestScanPort:
    def test_open_port_returns_true_and_closes_socket(self, monkeypatch):
        sock = FakeSocket(connect_result=0)
        _patch_socket(monkeypatch, sock)
        assert scanner.scan_port("10.0.0.1", 80) is True
        assert sock.closed is True

    def test_closed_port_returns_false(self, monkeypatch):
        _patch_socket(monkeypatch, FakeSocket(connect_result=1))
        assert scanner.scan_port("10.0.0.1", 80) is False

    def test_socket_error_returns_false(self, monkeypatch):
        _patch_socket(monkeypatch, raise_exc=OSError("boom"))
        assert scanner.scan_port("10.0.0.1", 80) is False


class TestScanPortsBatch:
    def test_returns_only_open_ports(self, monkeypatch):
        monkeypatch.setattr(scanner, "scan_port",
                            lambda ip, port, timeout=0: port == 8080)
        assert scanner.scan_ports_batch("10.0.0.1", ports=[80, 8080, 443]) == [8080]

    def test_stops_after_two_open_ports(self, monkeypatch):
        scanned = []

        def fake_scan(ip, port, timeout=0):
            scanned.append(port)
            return True

        monkeypatch.setattr(scanner, "scan_port", fake_scan)
        result = scanner.scan_ports_batch("10.0.0.1", ports=[80, 8080, 443, 8443])

        assert result == [80, 8080]
        assert scanned == [80, 8080]      # 已提前退出，后两个端口未扫描

    def test_fast_mode_uses_fast_ports(self, monkeypatch):
        scanned = []
        monkeypatch.setattr(scanner, "scan_port",
                            lambda ip, port, timeout=0: scanned.append(port) or False)
        scanner.scan_ports_batch("10.0.0.1", fast=True)
        assert scanned == scanner.FAST_PORTS

    def test_full_mode_uses_common_ports(self, monkeypatch):
        scanned = []
        monkeypatch.setattr(scanner, "scan_port",
                            lambda ip, port, timeout=0: scanned.append(port) or False)
        scanner.scan_ports_batch("10.0.0.1", fast=False)
        assert scanned == scanner.COMMON_PORTS


# ============================================================
# ESP32-CAM 指纹探测（多特征加权计分）
# ============================================================

class TestEsp32Probe:
    def test_jpeg_capture_scores_two(self, monkeypatch):
        monkeypatch.setattr(scanner, "requests", SimpleNamespace(get=_router({
            "/capture": {"headers": {"Content-Type": "image/jpeg"}},
        })))
        assert scanner._probe_esp32_cam("10.0.0.9") is True

    def test_sensor_register_json_scores_two(self, monkeypatch):
        monkeypatch.setattr(scanner, "requests", SimpleNamespace(get=_router({
            "/status": {"headers": {"Content-Type": "application/json"},
                        "text": '{"0x3400":1606,"0x3500":12544}'},
        })))
        assert scanner._probe_esp32_cam("10.0.0.9") is True

    def test_two_weak_signals_reach_threshold(self, monkeypatch):
        # 非 JPEG 图片(+1) + MJPEG 流(+1) = 2
        monkeypatch.setattr(scanner, "requests", SimpleNamespace(get=_router({
            "/capture": {"headers": {"Content-Type": "image/png"}},
            "/stream": {"headers": {"Content-Type": "multipart/x-mixed-replace"}},
        })))
        assert scanner._probe_esp32_cam("10.0.0.9") is True

    def test_single_weak_signal_is_not_enough(self, monkeypatch):
        # 仅命中摄像头参数字眼 → 1 分，低于阈值
        monkeypatch.setattr(scanner, "requests", SimpleNamespace(get=_router({
            "/status": {"headers": {"Content-Type": "text/plain"},
                        "text": "resolution: 800x600 brightness: 1"},
        })))
        assert scanner._probe_esp32_cam("10.0.0.9") is False

    def test_all_endpoints_unreachable(self, monkeypatch):
        def boom(*_args, **_kwargs):
            raise requests.exceptions.ConnectionError("refused")

        monkeypatch.setattr(scanner, "requests", SimpleNamespace(get=boom))
        assert scanner._probe_esp32_cam("10.0.0.9") is False


# ============================================================
# 设备类型识别
# ============================================================

class TestIdentifyDevice:
    def test_no_open_ports_returns_none(self, monkeypatch):
        calls = []
        monkeypatch.setattr(scanner, "scan_ports_batch",
                            lambda ip, fast=True: calls.append(fast) or [])
        assert scanner.identify_device("10.0.0.1") is None
        assert calls == [True, False]      # 先快速扫，未命中再完整扫

    def test_esp32_fingerprint_has_highest_priority(self, monkeypatch):
        monkeypatch.setattr(scanner, "_probe_esp32_cam", lambda ip, port=80: True)
        assert scanner.identify_device("10.0.0.5", open_ports=[80]) == {
            "ip": "10.0.0.5", "type": "ESP32-CAM",
            "port": 80, "info": "ESP32-CAM CameraWebServer",
        }

    def test_server_header_match(self, monkeypatch):
        monkeypatch.setattr(scanner, "_probe_esp32_cam", lambda ip, port=80: False)
        monkeypatch.setattr(scanner, "get_gateway_ip", lambda: "10.0.0.254")
        monkeypatch.setattr(scanner, "requests", SimpleNamespace(get=lambda url, **k: SimpleNamespace(
            headers={"Server": "nginx/1.18"}, text="<html/>", status_code=200)))

        device = scanner.identify_device("10.0.0.9", open_ports=[80])

        assert device["type"] == "Linux Server"
        assert device["info"] == "nginx/1.18"

    def test_body_content_match_when_header_is_unhelpful(self, monkeypatch):
        monkeypatch.setattr(scanner, "_probe_esp32_cam", lambda ip, port=80: False)
        monkeypatch.setattr(scanner, "get_gateway_ip", lambda: "10.0.0.254")
        monkeypatch.setattr(scanner, "requests", SimpleNamespace(get=lambda url, **k: SimpleNamespace(
            headers={}, text="Welcome to Raspberry Pi", status_code=200)))

        device = scanner.identify_device("10.0.0.9", open_ports=[80])

        assert device["type"] == "Raspberry Pi"
        assert device["info"] == "HTTP 200"

    def test_gateway_on_port_80_is_router(self, monkeypatch):
        monkeypatch.setattr(scanner, "_probe_esp32_cam", lambda ip, port=80: False)
        monkeypatch.setattr(scanner, "get_gateway_ip", lambda: "10.0.0.1")
        monkeypatch.setattr(scanner, "requests", SimpleNamespace(get=lambda url, **k: SimpleNamespace(
            headers={"Server": "nginx"}, text="", status_code=200)))

        assert scanner.identify_device("10.0.0.1", open_ports=[80])["type"] == "Router"

    def test_unknown_device_when_no_pattern_matches(self, monkeypatch):
        monkeypatch.setattr(scanner, "_probe_esp32_cam", lambda ip, port=80: False)
        monkeypatch.setattr(scanner, "get_gateway_ip", lambda: "10.0.0.254")
        monkeypatch.setattr(scanner, "requests", SimpleNamespace(get=lambda url, **k: SimpleNamespace(
            headers={"Server": "custom-thing"}, text="nothing here", status_code=200)))

        assert scanner.identify_device("10.0.0.9", open_ports=[80])["type"] == "Unknown Device"

    def test_http_failure_on_web_port_reports_unknown(self, monkeypatch):
        monkeypatch.setattr(scanner, "_probe_esp32_cam", lambda ip, port=80: False)
        monkeypatch.setattr(scanner, "get_gateway_ip", lambda: "10.0.0.254")

        def boom(url, **_kwargs):
            raise requests.exceptions.RequestException("refused")

        monkeypatch.setattr(scanner, "requests",
                            SimpleNamespace(get=boom, exceptions=requests.exceptions))

        assert scanner.identify_device("10.0.0.9", open_ports=[80]) == {
            "ip": "10.0.0.9", "type": "Unknown Device",
            "port": 80, "info": "Port 80 open",
        }

    def test_https_port_uses_https_scheme(self, monkeypatch):
        monkeypatch.setattr(scanner, "_probe_esp32_cam", lambda ip, port=80: False)
        monkeypatch.setattr(scanner, "get_gateway_ip", lambda: "10.0.0.254")
        seen = {}

        def fake_get(url, **_kwargs):
            seen["url"] = url
            return SimpleNamespace(headers={"Server": "nginx"}, text="", status_code=200)

        monkeypatch.setattr(scanner, "requests", SimpleNamespace(get=fake_get))
        scanner.identify_device("10.0.0.9", open_ports=[443])

        assert seen["url"] == "https://10.0.0.9:443/"


# ============================================================
# 三阶段扫描流程
# ============================================================

class TestScanPipeline:
    @pytest.fixture
    def stub_network(self, monkeypatch):
        monkeypatch.setattr(scanner, "get_local_ip", lambda: "192.168.1.10")
        monkeypatch.setattr(scanner, "get_gateway_ip", lambda: "192.168.1.1")

    def test_full_pipeline_collects_devices_and_reports_progress(
            self, monkeypatch, stub_network):
        monkeypatch.setattr(scanner, "ping_sweep", lambda *a, **k: [
            "192.168.1.20", "192.168.1.30"])
        monkeypatch.setattr(scanner, "scan_ports_batch",
                            lambda ip, fast=True: [80] if ip == "192.168.1.20" else [])
        monkeypatch.setattr(scanner, "identify_device",
                            lambda ip, ports: {"ip": ip, "type": "ESP32-CAM", "port": 80})

        found, progress = [], []
        device_scanner = scanner.DeviceScanner(on_device_found=found.append)
        result = device_scanner.start_scan(
            progress_callback=lambda current, total: progress.append((current, total)))

        expected = [{"ip": "192.168.1.20", "type": "ESP32-CAM", "port": 80}]
        assert result == expected
        assert found == expected                                   # 回调被触发
        assert progress[0] == (0, device_scanner._total_count)      # 起始进度
        assert progress[-1] == (1, 1)                               # 仅 1 个 IP 有开放端口

    def test_returns_empty_when_nothing_alive(self, monkeypatch, stub_network):
        monkeypatch.setattr(scanner, "ping_sweep", lambda *a, **k: [])
        monkeypatch.setattr(scanner, "scan_ports_batch",
                            lambda *a, **k: pytest.fail("不应进入端口扫描阶段"))

        assert scanner.DeviceScanner().start_scan() == []

    def test_local_and_gateway_ips_are_excluded(self, monkeypatch, stub_network):
        captured = {}

        def fake_ping(ips, **_kwargs):
            captured["ips"] = ips
            return []

        monkeypatch.setattr(scanner, "ping_sweep", fake_ping)
        scanner.DeviceScanner().start_scan()

        assert "192.168.1.10" not in captured["ips"]
        assert "192.168.1.1" not in captured["ips"]

    def test_stop_during_ping_aborts_remaining_phases(self, monkeypatch, stub_network):
        device_scanner = scanner.DeviceScanner()
        monkeypatch.setattr(scanner, "ping_sweep",
                            lambda *a, **k: device_scanner.stop() or ["192.168.1.20"])
        monkeypatch.setattr(scanner, "scan_ports_batch",
                            lambda *a, **k: pytest.fail("停止后不应继续端口扫描"))

        assert device_scanner.start_scan() == []
        assert device_scanner.running is False
