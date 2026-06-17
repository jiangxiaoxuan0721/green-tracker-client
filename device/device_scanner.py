"""
局域网设备扫描器 - 发现网络设备 (高性能版)
"""
import socket
import threading
import requests
import concurrent.futures
from typing import List, Dict, Callable, Optional
import subprocess
import platform
import warnings

# 忽略 SSL 警告
warnings.filterwarnings('ignore')

# 扫描配置
MAX_WORKERS = 150          # 最大并发数
PING_TIMEOUT = 0.15        # Ping 探测超时（秒）
PORT_SCAN_TIMEOUT = 0.12   # 端口扫描超时（秒）— 局域网内足够
HTTP_TIMEOUT = 0.6         # HTTP 识别超时（秒）— 局域网内足够
ESP32_PROBE_TIMEOUT = 0.8  # ESP32-CAM 专用探测超时

# 局域网探测必须绕过系统代理，否则请求被转发到代理服务器导致超时
_NO_PROXY = {"http": None, "https": None}  # type: ignore

# 常用端口（按设备可能性排序），第一阶段只扫最关键的几个
FAST_PORTS = [80, 8080]
COMMON_PORTS = [80, 8080, 443, 8443, 5000, 3000]  # 第二阶段扩展


# 设备类型识别规则
DEVICE_PATTERNS = {
    # ESP 系列
    "ESP32-CAM": ["esp32", "esp32-cam", "m5stack"],
    "ESP8266": ["esp8266", "nodemcu"],
    
    # 摄像头
    "IP Camera": ["camera", "ipcam", "webcam", "dvr", "nvr"],
    "RTSP Camera": ["rtsp"],
    
    # 路由器/网关
    "Router": ["router", "gateway", "openwrt", "lede"],
    "ASUS Router": ["asus"],
    "TP-Link Router": ["tp-link", "tplink"],
    "Mi WiFi": ["miwifi", "xiaomi router"],
    
    # 智能家居
    "Home Assistant": ["home assistant"],
    "Smart Home Hub": ["hub", "smartthings", "homekit"],
    
    # 开发板
    "Raspberry Pi": ["raspberry", "rpi", "raspbian"],
    "Arduino": ["arduino"],
    "Jetson": ["jetson"],
    
    # 电脑/服务器
    "Windows PC": ["microsoft", "iis", "asp.net"],
    "Linux Server": ["ubuntu", "debian", "centos", "apache", "nginx"],
    "Synology NAS": ["synology", "diskstation"],
    "QNAP NAS": ["qnap", "qnap nas"],
    
    # 手机/平板
    "Mobile Device": ["android", "iphone", "ios"],
    
    # 打印机
    "Printer": ["printer", "cups", "print"],
    
    # 电视/投屏
    "Smart TV": ["tv", "roku", "firetv", "chromecast", "apple tv"],
    
    # 游戏主机
    "Game Console": ["playstation", "xbox", "nintendo"],
    
    # 网络存储
    "NAS": ["nas", "truenas", "openmediavault"],
}


def get_local_ip() -> str:
    """获取本机 IP 地址"""
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        local_ip = s.getsockname()[0]
        s.close()
        return local_ip
    except Exception:
        return "127.0.0.1"


def get_network_range() -> tuple:
    """获取本地网络的 IP 范围 (起始IP, 结束IP)"""
    local_ip = get_local_ip()
    parts = local_ip.split('.')
    
    # 假设 /24 子网 (如 192.168.1.x)
    network_prefix = '.'.join(parts[:3])
    
    return f"{network_prefix}.1", f"{network_prefix}.254"


def get_gateway_ip() -> str:
    """获取网关 IP (路由器地址)"""
    try:
        if platform.system() == "Windows":
            result = subprocess.run(["ipconfig"], capture_output=True, text=True)
            for line in result.stdout.split('\n'):
                if "Default Gateway" in line or "网关" in line:
                    parts = line.split(':')
                    if len(parts) > 1:
                        ip = parts[1].strip()
                        if ip and ip != "":
                            return ip
        else:
            result = subprocess.run(["ip", "route", "show", "default"], 
                                  capture_output=True, text=True)
            if result.stdout:
                parts = result.stdout.split()
                if "via" in parts:
                    idx = parts.index("via")
                    return parts[idx + 1]
    except Exception:
        pass
    return ""


def ping_sweep(ips: List[str], timeout: float = PING_TIMEOUT,
               max_workers: int = MAX_WORKERS) -> List[str]:
    """ICMP/ARP ping 批量探测，快速筛出在线主机。"""
    alive = []

    def _ping_one(ip: str) -> Optional[str]:
        try:
            # Linux/macOS 用 ping -c 1 -W，Windows 用 ping -n 1 -w
            if platform.system() == "Windows":
                cmd = ["ping", "-n", "1", "-w", str(int(timeout * 1000)), ip]
            else:
                cmd = ["ping", "-c", "1", "-W", str(int(timeout)), ip]
            proc = subprocess.run(
                cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                timeout=timeout + 0.2,
            )
            if proc.returncode == 0:
                return ip
        except Exception:
            pass
        return None

    with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = {executor.submit(_ping_one, ip): ip for ip in ips}
        for future in concurrent.futures.as_completed(futures):
            result = future.result()
            if result:
                alive.append(result)

    return alive


def scan_port(ip: str, port: int, timeout: float = PORT_SCAN_TIMEOUT) -> bool:
    """扫描指定 IP 的端口是否开放"""
    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(timeout)
        result = sock.connect_ex((ip, port))
        sock.close()
        return result == 0
    except Exception:
        return False


def scan_ports_batch(ip: str, ports: Optional[List[int]] = None,
                     fast: bool = True) -> List[int]:  # type: ignore
    """批量扫描端口，返回开放的端口列表。

    Args:
        ip: 目标 IP
        ports: 待扫描端口列表，None 时使用 FAST_PORTS 或 COMMON_PORTS
        fast: True 只扫 FAST_PORTS(2个)，False 扫 COMMON_PORTS(6个)
    """
    if ports is None:
        ports = FAST_PORTS if fast else COMMON_PORTS
    
    open_ports = []
    
    for port in ports:
        if scan_port(ip, port, timeout=PORT_SCAN_TIMEOUT):
            open_ports.append(port)
        if len(open_ports) >= 2:  # 找到2个开放端口就足够识别了
            break
    
    return open_ports


def _probe_esp32_cam(ip: str, port: int = 80,
                      timeout: float = ESP32_PROBE_TIMEOUT) -> bool:
    """探测是否为 ESP32-CAM 设备（多端点交叉验证）。
    
    ESP32-CAM CameraWebServer 固件独有特征组合：
      - GET /capture 返回 JPEG 图片
      - GET /status 返回传感器寄存器 JSON (含 0x34xx/0x35xx 地址)
      - GET /stream 返回 multipart/x-mixed-replace (MJPEG)
    
    判定策略：多维度交叉验证，至少匹配 2 项才确认为 ESP32-CAM，
    避免单一特征误判（其他 IP 摄像头也可能有 /capture 路径）。
    """
    base = f"http://{ip}:{port}"
    scores = 0

    # ---- 特征1: /capture 返回 JPEG 图片 ----
    try:
        r = requests.get(f"{base}/capture", timeout=timeout,
                          proxies=_NO_PROXY)  # type: ignore[arg-type]
        ct = r.headers.get("Content-Type", "")
        if "image/jpeg" in ct:
            scores += 2          # JPEG 是强特征，加权 2 分
        elif "image" in ct and r.status_code == 200:
            scores += 1          # 其他图片类型，弱特征
    except Exception:
        pass

    # ---- 特征2: /status 返回 ESP32 传感器寄存器 JSON ----
    #     CameraWebServer 的 /status 格式: {"0x3400":1606, "0x3500":12544, ...}
    #     这些是 OV2640/OV3660 传感器的 I2C 寄存器地址，极具辨识度
    try:
        r = requests.get(f"{base}/status", timeout=timeout,
                          proxies=_NO_PROXY)  # type: ignore[arg-type]
        if r.status_code == 200 and r.headers.get("Content-Type", "").startswith(
            ("application/json", "text/plain")
        ):
            text = r.text.strip()
            # 检查 ESP32 CameraWebServer 特有的传感器寄存器模式
            if any(pattern in text for pattern in (
                '"0x3400"', '"0x3500"', '"0x5480"',   # OV2640/OV3660 寄存器
                'led_control', 'xclk', 'frame_size',   # 控制字段
            )):
                scores += 2      # 寄存器 JSON 是最强特征，加权 2 分
            elif any(kw in text.lower() for kw in (
                "flash", "resolution", "brightness", "contrast"
            )):
                # 含摄像头参数词，但不带寄存器 — 中等置信度
                scores += 1
    except Exception:
        pass

    # ---- 特征3: /stream 返回 MJPEG 流 ----
    try:
        r = requests.get(
            f"{base}/stream", timeout=timeout,
            stream=True, headers={"Range": "bytes=0-1023"},
            proxies=_NO_PROXY,  # type: ignore[arg-type]
        )
        ct = r.headers.get("Content-Type", "")
        if "multipart" in ct or "mjpeg" in ct.lower():
            scores += 1
        r.close()
    except Exception:
        pass

    # 至少需要 2 分（即至少一个强特征 + 一个弱特征，或两个中等特征）
    return scores >= 2


def identify_device(ip: str, open_ports: List[int] = None) -> Optional[Dict]: # type: ignore
    """识别 IP 设备的类型"""
    
    # 如果没有传入开放端口，先快速扫描
    if open_ports is None:
        open_ports = scan_ports_batch(ip, fast=True)
        if not open_ports:
            # 快速模式没扫到，再用完整端口列表试一次
            open_ports = scan_ports_batch(ip, fast=False)
    
    if not open_ports:
        return None
    
    # ---- 0: ESP32-CAM 专用指纹探测（最高优先级）----
    for port in open_ports:
        if port in (80, 443, 8080, 8443):
            if _probe_esp32_cam(ip, port=port):
                return {
                    "ip": ip,
                    "type": "ESP32-CAM",
                    "port": port,
                    "info": "ESP32-CAM CameraWebServer",
                }
    
    # ---- 1: 按优先级尝试 HTTP 识别 ----
    for port in open_ports:
        if port not in [80, 443, 8080, 8443, 5000, 3000]:
            continue
            
        try:
            protocol = "https" if port in [443, 8443] else "http"
            url = f"{protocol}://{ip}:{port}/"
            response = requests.get(url, timeout=HTTP_TIMEOUT, proxies=_NO_PROXY)  # type: ignore[arg-type]
                
            # 获取 HTTP 响应信息
            server = response.headers.get("Server", "")
            content = response.text.lower()
            
            # 检查是否为网关/路由器
            if port == 80 and ip == get_gateway_ip():
                return {
                    "ip": ip,
                    "type": "Router",
                    "port": port,
                    "info": server or "Gateway/Router"
                }
            
            # 尝试匹配设备类型
            device_type = "Unknown Device"
            device_info = server or f"HTTP {response.status_code}"
            
            # 检查 Server 头
            if server:
                server_lower = server.lower()
                for dev_type, patterns in DEVICE_PATTERNS.items():
                    for pattern in patterns:
                        if pattern in server_lower:
                            device_type = dev_type
                            break
                    if device_type != "Unknown Device":
                        break
            
            # 如果 Server 头没匹配，检查页面内容
            if device_type == "Unknown Device":
                for dev_type, patterns in DEVICE_PATTERNS.items():
                    for pattern in patterns:
                        if pattern in content:
                            device_type = dev_type
                            break
                    if device_type != "Unknown Device":
                        break
            
            return {
                "ip": ip,
                "type": device_type,
                "port": port,
                "info": device_info
            }
            
        except requests.exceptions.RequestException:
            # 端口开放但无法访问 HTTP
            if port == 80 or port == 8080:
                return {
                    "ip": ip,
                    "type": "Unknown Device",
                    "port": port,
                    "info": f"Port {port} open"
                }
    
    return None


class DeviceScanner:
    """设备扫描器 - 高性能版"""
    
    def __init__(self, on_device_found: Optional[Callable[[Dict], None]] = None):
        self.on_device_found = on_device_found
        self.running = False
        self.found_devices: List[Dict] = []
        self.lock = threading.Lock()
        self._scanned_count = 0
        self._total_count = 0
    
    def start_scan(self, progress_callback: Optional[Callable[[int, int], None]] = None):
        """开始扫描局域网设备 — 三阶段优化：ping → 端口 → 识别"""
        self.running = True
        self.found_devices.clear()
        self._scanned_count = 0
        
        # 获取 IP 列表
        start_ip, end_ip = get_network_range()
        start_num = int(start_ip.split('.')[-1])
        end_num = int(end_ip.split('.')[-1])
        
        network_prefix = '.'.join(get_local_ip().split('.')[:3])
        all_ips = [f"{network_prefix}.{i}" for i in range(start_num, end_num + 1)]
        
        local_ip = get_local_ip()
        gateway_ip = get_gateway_ip()
        exclude_ips = [local_ip, gateway_ip, ""]
        all_ips = [ip for ip in all_ips if ip not in exclude_ips]
        
        self._total_count = len(all_ips)
        
        # ===== 阶段 1: Ping 探测筛出在线主机 =====
        if progress_callback:
            progress_callback(0, self._total_count)
        alive_ips = ping_sweep(all_ips)
        print(f"[扫描器] Ping 筛选: {len(all_ips)} IPs -> {len(alive_ips)} 在线")
        
        if not alive_ips or not self.running:
            return self.found_devices
        
        # ===== 阶段 2: 对在线主机做快速端口扫描 =====
        with concurrent.futures.ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
            port_results = list(executor.map(
                lambda ip: (ip, scan_ports_batch(ip, fast=True)),
                alive_ips
            ))
        
        active_ips = [(ip, ports) for ip, ports in port_results if ports]
        print(f"[扫描器] 端口扫描: {len(alive_ips)} 活跃 -> {len(active_ips)} 有开放端口")
        
        if not active_ips or not self.running:
            return self.found_devices
        
        # ===== 阶段 3: 设备识别 =====
        completed = 0
        with concurrent.futures.ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
            futures = {
                executor.submit(identify_device, ip, ports): ip 
                for ip, ports in active_ips
            }
            
            for future in concurrent.futures.as_completed(futures):
                if not self.running:
                    break
                completed += 1
                
                try:
                    device = future.result()
                    if device:
                        with self.lock:
                            self.found_devices.append(device)
                        if self.on_device_found:
                            self.on_device_found(device)
                except Exception:
                    pass
                
                if progress_callback:
                    progress_callback(completed, len(active_ips))
        
        print(f"[扫描器] 扫描完成，共发现 {len(self.found_devices)} 个设备")
        return self.found_devices
    
    def stop(self):
        """停止扫描"""
        self.running = False


def scan_devices(
    on_found: Optional[Callable[[Dict], None]] = None,
    progress: Optional[Callable[[int, int], None]] = None
) -> List[Dict]:
    """
    便捷函数：扫描局域网内的所有设备
    
    Args:
        on_found: 发现设备时的回调函数
        progress: 进度回调 (current, total)
    
    Returns:
        发现的设备列表
    """
    scanner = DeviceScanner(on_device_found=on_found)
    return scanner.start_scan(progress_callback=progress)


if __name__ == "__main__":
    # 测试代码
    print(f"本机 IP: {get_local_ip()}")
    print("开始扫描局域网设备...")
    
    def on_found(device):
        print(f"发现设备: {device}")
    
    devices = scan_devices(on_found=on_found, progress=lambda c, t: print(f"\r扫描进度: {c}/{t}", end=""))
    
    print(f"\n\n扫描完成，发现 {len(devices)} 个设备:")
    for d in devices:
        print(f"  - {d['ip']} ({d['type']})")
