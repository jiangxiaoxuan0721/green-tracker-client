# Green Tracker 客户端

绿色追踪器客户端应用，用于环境/农业数据采集、设备管理和数据上传。

## 功能特性

- **任务管理**：从远程服务器获取采集任务，多任务并行管理
- **设备扫描**：局域网设备自动发现（ESP32-CAM、传感器等）
- **MQTT 通信**：
  - Topic Discovery 话题发现机制（announce 宣告 + retain 持久化）
  - 设备心跳上报与 LWT 遗嘱离线检测
  - 命令下发 / 响应收发（支持 `list_commands` 动态能力发现）
  - TCP 主动探测 + MQTT 信号辅助的双层设备在线检测
- **数据采集**：
  - 模拟传感器数据（环境数据、土壤数据）
  - ESP32-CAM 摄像头图像采集
- **本地存储**：支持断网续传，内存缓存层 + 文件持久化双写
- **批量上传**：智能扫描未上传数据，支持断点续传

## 项目结构

```bash
green-tracker-client/
├── main.py                 # 应用入口
├── requirements.txt         # 依赖列表
├── .env.example             # 环境变量模板
├── api/                     # API 通信模块
│   ├── __init__.py
│   ├── get_active_sessions.py   # 获取活跃任务
│   ├── upload_numeric_data.py  # 上传数字数据
│   └── upload_file_data.py     # 上传文件数据
├── device/                  # 设备与数据模块
│   ├── __init__.py
│   ├── data_models.py          # 数据模型定义
│   ├── device_scanner.py       # 设备扫描器
│   ├── device_state.py        # 设备状态管理（内存缓存 + JSON 持久化）
│   ├── esp32_cam.py           # ESP32-CAM 控制
│   ├── simu_sensor.py         # 模拟传感器 / DataGenerator 虚拟单元
│   └── task_manager.py        # 任务管理器
├── mqtt/                    # MQTT 通信模块
│   ├── __init__.py           # 模块导出（含 announce_topic）
│   ├── client.py             # 设备端 MQTT 客户端（announce/LWT/command/response）
│   ├── manager.py            # 服务管理器（QThread 封装 + Qt 信号事件总线）
│   ├── commands.py           # 命令处理器注册表（内置 ping/get_info/reboot/set_config/get_metrics/list_commands）
│   └── topics.py             # Topic 定义常量（4 层通配，支持 announce）
└── ui/                      # PyQt6 图形界面
    ├── __init__.py
    ├── main_window.py        # 主窗口
    ├── device_manager.py     # 设备管理页面（TCP 探测 + 心跳刷新 + 统计修复）
    ├── device_assign.py      # 设备分配页面（扫描后自动刷新）
    ├── collection_monitor.py # 任务监控页面
    ├── task_window.py        # 任务执行页面
    ├── upload_window.py      # 单次上传页面
    ├── batch_upload.py       # 批量上传页面
    └── mqtt_panel.py         # MQTT 控制台面板（按钮样式统一）
```

## 快速开始

### 1. 安装依赖

```bash
pip install -r requirements.txt
```

### 2. 配置环境变量

复制配置文件模板并填写实际值：

```bash
cp .env.example .env
```

编辑 `.env` 文件：

```env
API_BASE_URL=http://your-server.com       # 后端 API 地址
SECRET_KEY=your_secret_key                # 用户 API 密钥
MQTT_DEVICE_ID=your-device-id            # 设备唯一 ID
MQTT_DEVICE_SECRET=your-device-secret    # 设备密钥
MQTT_BROKER_HOST=green-tracker.cn        # MQTT Broker 地址
MQTT_BROKER_PORT=1883                    # MQTT Broker 端口
```

### 3. 运行应用

```bash
python main.py
```

## 使用说明

### 主界面

应用启动后进入主界面，提供以下功能入口：

| 功能 | 说明 |
|------|------|
| 获取可用任务 | 从服务器同步采集任务列表 |
| 任务管理 | 监控和管理多个采集任务 |
| 设备管理 | 扫描和管理局域网设备（TCP 探测 + MQTT 双层检测） |
| MQTT 控制台 | 查看 MQTT 连接状态、消息日志、命令调试 |

### MQTT 通信

#### 连接时序

```
connect Broker (MQTTv311, username=device_id, password=secret)
  ↓
set LWT will (topic: .../lwt, retain=True, qos=1)
  ↓
on_connect 回调:
  ├─ subscribe(.../command)           ← 接收云端指令
  ├─ subscribe(device/+/status)      ← 感知其他设备上线
  ├─ subscribe(device/+/lwt)         ← 感知其他设备离线
  ├─ report status("online")          ← 上报本机状态
  └─ ★ publish announce (retain=True) ← 宣告话题映射
  ↓
进入心跳循环（每30s 上报 status）
```

#### Topic Discovery（话题发现）

设备连接成功后自动发布宣告消息（retain=True），云端订阅 `+/device/+/announce` 即可动态获取所有设备的话题映射：

```json
{
  "protocol_version": "1.0",
  "device_id": "xxx",
  "topics": {
    "status":   "green-tracker/device/{id}/status",
    "response": "green-tracker/device/{id}/response",
    "command":  "green-tracker/device/{id}/command"
  },
  "lwt_topic": "green-tracker/device/{id}/lwt"
}
```

#### 内置命令

| 命令 | 说明 | 参数 | 返回 |
|------|------|------|------|
| `ping` | 心跳检测 | 无 | `{pong, timestamp, uptime}` |
| `get_info` | 设备信息 | 无 | `{device_id, hostname, platform, local_ip}` |
| `reboot` | 重启设备 | `delay`(秒) | `{message, delay}` |
| `set_config` | 设置配置 | `key`, `value` | `{message, key, value}` |
| `get_metrics` | 运行指标 | 无 | `{cpu_usage, memory_usage, temperature, uptime_seconds}` |
| `list_commands` | **命令列表** | 无 | `{commands: [...]}` |

云端通过下发 `list_commands` 可动态获取设备支持的完整能力列表。

### 任务管理

1. 点击「获取可用任务」同步服务器任务
2. 进入「任务管理」页面
3. 为任务分配设备（点击「分配设备」）
4. 点击「开始」启动数据采集

### 设备管理

1. 点击「扫描执行单元」发现局域网内的设备
2. 扫描完成后**自动刷新**设备状态和列表
3. 后台 **TCP 主动探测**（每 5s，超时 0.5s）+ MQTT 心跳信号双层检测在线状态
4. 离线设备自动清理（不显示，直接移除）

### 数据上传

#### 单次上传

在任务执行页面点击「上传数据」

#### 批量上传

在主界面选择任务进入批量上传页面：
- 自动扫描未上传的数据
- 智能跳过已上传文件（通过 `images_status.json` 记录状态）
- 支持断点续传

## 数据存储

本地数据存储在 `~/green_tracker_data/` 目录：

```
~/green_tracker_data/
├── device_assignments.json   # 设备分配关系
├── sensor_data.json          # 传感器记录
└── {session_id}/
    ├── data.csv              # 采集数据
    ├── images/               # 采集图像
    │   └── {ip}_{timestamp}.jpg
    ├── meta.json             # 批次元数据
    └── images_status.json    # 图片上传状态
```

## 支持的数据类型

### 环境数据

- 温度 (temperature)、湿度 (humidity)、CO2 浓度 (co2)
- 光照强度 (light)、气压 (pressure)

### 土壤数据

- 土壤湿度 (moisture)、土壤 pH 值 (ph)
- 电导率 (ec)、土壤温度 (temperature_soil)

### 文件数据

- RGB 图像、NIR 近红外图像、热成像图像、多光谱图像

## 技术架构

### 设备状态管理

| 状态 | 说明 |
|------|------|
| IDLE (空闲) | 设备未被分配，可分配给任务 |
| ASSIGNED (已分配) | 已分配给任务，但任务未启动 |
| BUSY (忙碌) | 任务运行中，正在采集数据 |

**性能优化**：
- 内存缓存层 (`self._cache`) 替代频繁文件 I/O
- TCP socket 主动探测（`connect_ex`）作为主要在线检测手段
- MQTT pub/sub 信号作为辅助实时感知
- 设备离线后自动清理（不保留 OFFLINE 显示）

### 线程安全

- 设备扫描使用独立 QThread
- TCP 健康检查使用独立后台线程（HealthCheckThread）
- MQTT 客户端在 _MQTTWorker(QThread) 中运行
- UI 更新通过 Qt pyqtSignal 跨线程投递

### UI 样式规范

所有页面按钮统一风格：

- `font-size: 14px`（小按钮 13px）
- `padding: 8px 16px`
- `border: 2px solid`
- `border-radius: 4px`
- 固定高度 32~40px
- hover 态带 border-color 变化

## 依赖库

| 库 | 版本 | 用途 |
|----|------|------|
| PyQt6 | >=6.7 | GUI 框架 |
| requests | >=2.31 | HTTP 请求 |
| paho-mqtt | >=1.6 | MQTT 客户端 |
| python-dotenv | >=1.0 | 环境变量 |

## 许可证

MIT License
