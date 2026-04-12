"""
ESP32-CAM 设备控制模块
"""
import requests
from typing import Optional
import time


class ESP32CAM:
    """ESP32-CAM 设备控制类"""
    
    def __init__(self, ip: str, port: int = 80):
        """
        初始化 ESP32-CAM 设备
        
        Args:
            ip: 设备 IP 地址
            port: 端口号，默认 80
        """
        self.ip = ip
        self.port = port
        self.base_url = f"http://{ip}:{port}"
    
    def get_capture(self, timeout: float = 5.0) -> Optional[bytes]:
        """
        获取摄像头拍摄的图片
        
        Args:
            timeout: 请求超时时间（秒）
        
        Returns:
            图片的字节数据，失败返回 None
        """
        try:
            url = f"{self.base_url}/capture"
            response = requests.get(url, timeout=timeout)
            if response.status_code == 200:
                return response.content
        except requests.exceptions.RequestException as e:
            print(f"获取图片失败: {e}")
        return None
    
    def get_stream(self) -> str:
        """
        获取视频流地址
        
        Returns:
            视频流 URL
        """
        return f"{self.base_url}/stream"
    
    def status(self, timeout: float = 3.0) -> dict:
        """
        获取设备状态
        
        Args:
            timeout: 请求超时时间（秒）
        
        Returns:
            状态信息字典
        """
        try:
            # 尝试多个可能的端点
            for endpoint in ["/status", "/", "/info"]:
                url = f"{self.base_url}{endpoint}"
                response = requests.get(url, timeout=timeout)
                if response.status_code == 200:
                    return {
                        "ip": self.ip,
                        "port": self.port,
                        "status": "online",
                        "response": response.text[:200] if response.text else "OK"
                    }
        except requests.exceptions.RequestException as e:
            return {
                "ip": self.ip,
                "port": self.port,
                "status": "offline",
                "error": str(e)
            }
        
        return {
            "ip": self.ip,
            "port": self.port,
            "status": "unknown"
        }
    
    def save_photo(self, save_path: str, timeout: float = 5.0) -> bool:
        """
        获取图片并保存到文件
        
        Args:
            save_path: 保存路径
            timeout: 请求超时时间（秒）
        
        Returns:
            是否成功
        """
        image_data = self.get_capture(timeout)
        if image_data:
            try:
                with open(save_path, 'wb') as f:
                    f.write(image_data)
                return True
            except IOError as e:
                print(f"保存图片失败: {e}")
        return False


def discover_and_capture(ip: str = None) -> Optional[bytes]: # type: ignore
    """
    便捷函数：发现设备并获取照片
    
    Args:
        ip: 设备 IP，如果为 None 则尝试自动发现
    
    Returns:
        图片字节数据
    """
    # 如果提供了 IP，直接使用
    if ip:
        cam = ESP32CAM(ip)
        return cam.get_capture()
    
    # 否则扫描网络发现设备
    from device import scan_devices
    
    print("未提供 IP，正在扫描网络...")
    devices = scan_devices()
    
    # 查找 ESP32-CAM 设备
    for dev in devices:
        if "ESP32" in dev.get("type", "") or "CAM" in dev.get("type", ""):
            print(f"发现 ESP32-CAM 设备: {dev['ip']}")
            cam = ESP32CAM(dev["ip"])
            return cam.get_capture()
    
    print("未发现 ESP32-CAM 设备")
    return None


if __name__ == "__main__":
    import sys
    
    # 从命令行参数获取 IP，或提示用户输入
    if len(sys.argv) > 1:
        ip = sys.argv[1]
    else:
        ip = input("请输入 ESP32-CAM 设备 IP 地址: ").strip()
    
    if not ip:
        print("未输入 IP，退出")
        sys.exit(1)
    
    # 创建设备实例
    cam = ESP32CAM(ip)
    
    # 获取状态
    print(f"\n获取设备状态: {ip}...")
    status = cam.status()
    print(f"状态: {status}")
    
    # 获取照片
    print(f"\n获取照片...")
    image_data = cam.get_capture()
    
    if image_data:
        # 保存到文件
        filename = f"esp32_cam_{int(time.time())}.jpg"
        with open(filename, 'wb') as f:
            f.write(image_data)
        print(f"照片已保存到: {filename}")
        print(f"文件大小: {len(image_data)} bytes")
    else:
        print("获取照片失败")
