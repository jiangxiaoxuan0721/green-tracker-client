# Green Tracker 客户端

绿色追踪器客户端应用，用于环境/农业数据采集、设备管理和数据上传。

## 功能特性

- **任务管理**：从远程服务器获取采集任务，多任务并行管理
- **设备扫描**：局域网设备自动发现（ESP32-CAM、传感器等）
- **数据采集**：
  - 模拟传感器数据（环境数据、土壤数据）
  - ESP32-CAM 摄像头图像采集
- **本地存储**：支持断网续传，数据本地缓存
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
│   ├── device_state.py        # 设备状态管理
│   ├── esp32_cam.py           # ESP32-CAM 控制
│   ├── simu_sensor.py         # 模拟传感器
│   └── task_manager.py        # 任务管理器
└── ui/                      # PyQt6 图形界面
    ├── __init__.py
    ├── main_window.py        # 主窗口
    ├── device_manager.py     # 设备管理页面
    ├── device_assign.py      # 设备分配页面
    ├── collection_monitor.py # 任务监控页面
    ├── task_window.py        # 任务执行页面
    ├── upload_window.py      # 单次上传页面
    └── batch_upload.py       # 批量上传页面
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
API_BASE_URL=http://your-server.com   # 后端 API 地址
SECRET_KEY=your_secret_key            # 用户 API 密钥
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
| 设备管理 | 扫描和管理局域网设备 |

### 任务管理

1. 点击「获取可用任务」同步服务器任务
2. 进入「任务管理」页面
3. 为任务分配设备（点击「分配设备」）
4. 点击「开始」启动数据采集

采集过程中会：

- 生成模拟传感器数据保存到 `data.csv`
- 从分配的 ESP32-CAM 设备采集图像保存到 `images/` 目录

### 设备管理

1. 点击「扫描设备」发现局域网内的设备
2. 查看设备状态（空闲/已分配/忙碌）
3. 为空闲或已分配的设备切换任务
4. 取消设备分配

### 数据上传

#### 单次上传

在任务执行页面点击「上传数据」：

- 上传当前缓存的数字数据
- 上传指定文件

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

- 温度 (temperature)
- 湿度 (humidity)
- CO2 浓度 (co2)
- 光照强度 (light)
- 气压 (pressure)

### 土壤数据

- 土壤湿度 (moisture)
- 土壤 pH 值 (ph)
- 电导率 (ec)
- 土壤温度 (temperature_soil)

### 文件数据

- RGB 图像
- NIR 近红外图像
- 热成像图像
- 多光谱图像

## 依赖库

| 库 | 版本 | 用途 |
|----|------|------|
| PyQt6 | 6.7.0 | GUI 框架 |
| requests | 2.32.5 | HTTP 请求 |
| pydantic | 2.12.5 | 数据验证 |
| python-dotenv | 1.2.2 | 环境变量 |

## 技术架构

### 设备状态管理

设备有三种状态：

| 状态 | 说明 |
|------|------|
| IDLE (空闲) | 设备未被分配，可分配给任务 |
| ASSIGNED (已分配) | 已分配给任务，但任务未启动 |
| BUSY (忙碌) | 任务运行中，正在采集数据 |

### 采集流程

```
服务器任务 → 设备分配 → 任务启动
    ↓                        ↓
生成模拟数据            ESP32-CAM 采集图像
    ↓                        ↓
写入 data.csv           保存到 images/
    ↓                        ↓
    ←────── 上传到服务器 ──────→
         （支持断网续传）
```

## 开发说明

### 运行模式

- **生产模式**：连接真实后端服务器
- **模拟模式**：使用模拟数据生成器，无需真实传感器

### 线程安全

- 设备扫描使用独立线程
- 数据采集在后台线程执行
- UI 更新通过 Qt 信号机制

## 许可证

MIT License
