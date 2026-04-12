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
import time

# 忽略 SSL 警告
warnings.filterwarnings('ignore')

# 扫描配置
MAX_WORKERS = 100  # 最大并发数
PORT_SCAN_TIMEOUT = 0.3  # 端口扫描超时（秒）
HTTP_TIMEOUT = 1.5  # HTTP 识别超时（秒）
# 常用端口（按设备可能性排序）
COMMON_PORTS = [80, 8080, 443, 8443, 5000, 3000, 53, 22, 21]


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


def scan_ports_batch(ip: str, ports: List[int] = None) -> List[int]: # type: ignore
    """批量扫描端口，返回开放的端口列表"""
    if ports is None:
        ports = COMMON_PORTS
    
    open_ports = []
    
    for port in ports:
        if scan_port(ip, port, timeout=PORT_SCAN_TIMEOUT):
            open_ports.append(port)
        if len(open_ports) >= 2:  # 找到2个开放端口就足够识别了
            break
    
    return open_ports


def identify_device(ip: str, open_ports: List[int] = None) -> Optional[Dict]: # type: ignore
    """识别 IP 设备的类型"""
    
    # 如果没有传入开放端口，先快速扫描
    if open_ports is None:
        open_ports = scan_ports_batch(ip)
    
    if not open_ports:
        return None
    
    # 按优先级尝试识别
    for port in open_ports:
        if port not in [80, 443, 8080, 8443, 5000, 3000]:
            continue
            
        try:
            protocol = "https" if port in [443, 8443] else "http"
            url = f"{protocol}://{ip}:{port}/"
            response = requests.get(url, timeout=HTTP_TIMEOUT)
                
            # 获取 HTTP 响应信息
            server = response.headers.get("Server", "")
            content_type = response.headers.get("Content-Type", "")
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
        """开始扫描局域网设备 - 两阶段扫描优化"""
        self.running = True
        self.found_devices.clear()
        self._scanned_count = 0
        
        # 获取 IP 列表
        start_ip, end_ip = get_network_range()
        start_num = int(start_ip.split('.')[-1])
        end_num = int(end_ip.split('.')[-1])
        
        # 生成所有 IP
        network_prefix = '.'.join(get_local_ip().split('.')[:3])
        all_ips = [f"{network_prefix}.{i}" for i in range(start_num, end_num + 1)]
        
        # 排除本机 IP 和网关 IP（已知不是设备）
        local_ip = get_local_ip()
        gateway_ip = get_gateway_ip()
        exclude_ips = [local_ip, gateway_ip, ""]
        all_ips = [ip for ip in all_ips if ip not in exclude_ips]
        
        self._total_count = len(all_ips)
        
        # 使用线程池快速扫描
        with concurrent.futures.ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
            # 提交所有端口扫描任务
            port_results = list(executor.map(
                lambda ip: (ip, scan_ports_batch(ip)),
                all_ips
            ))
        
        # 筛选出有开放端口的 IP
        active_ips = [(ip, ports) for ip, ports in port_results if ports]
        completed = 0
        
        with concurrent.futures.ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
            # 提交所有识别任务
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
