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
├── config.py               # 唯一配置源（DATA_ROOT / API_BASE_URL / 采集间隔…）
├── requirements.txt         # 依赖列表
├── .env.example             # 环境变量模板
├── doc/                     # 文档
│   └── terminal_commands.md # 远程终端命令对接说明（云端 / Agent 参考）
├── api/                     # API 通信模块
│   ├── client.py            # 公共传输层（headers / post_json / post_file）
│   ├── get_active_sessions.py   # 获取活跃任务
│   ├── upload_numeric_data.py  # 上传数字数据
│   └── upload_file_data.py     # 上传文件数据
├── device/                  # 设备与数据模块
│   ├── base.py              # AbstractBaseDevice（多态接口）
│   ├── registry.py          # device_type → 设备工厂
│   ├── runtime.py           # 全局虚拟传感器单例
│   ├── collector.py         # 会话采集引擎（与 UI 解耦）
│   ├── device_scanner.py    # 设备扫描器
│   ├── task_manager.py      # 任务管理器
│   ├── models/              # base / data_types / records / state
│   ├── virtual/             # 虚拟传感器设备
│   └── hardware/            # ESP32-CAM 等硬件设备
├── storage/                 # 本地文件系统单一边界（paths / batch / upload_state）
├── mqtt/                    # MQTT 通信模块
│   ├── __init__.py           # 模块导出（含 announce_topic）
│   ├── client.py             # 设备端 MQTT 客户端（announce/LWT/command/response）
│   ├── manager.py            # 服务管理器（QThread 封装 + Qt 信号事件总线）
│   ├── commands.py           # 命令处理器注册表（内置 ping/get_info/reboot/set_config/get_metrics/list_commands/cloud_probe/execute_shell/terminal_*）
│   ├── terminal.py           # 常驻 PTY 终端（execute_shell 的真实环境后端）
│   └── topics.py             # Topic 定义常量（4 层通配，支持 announce）
├── tests/                   # pytest 测试（346 条）
└── ui/                      # PyQt6 图形界面
    ├── main_window.py        # 主窗口（仅做导航装配）
    ├── device_manager.py     # 设备管理页面（TCP 探测 + 心跳刷新）
    ├── device_assign.py      # 设备分配页面（扫描后自动刷新）
    ├── collection_monitor.py # 任务监控页面
    ├── upload_window.py      # 单次上传页面
    ├── batch_upload.py       # 批量上传页面
    └── mqtt_panel.py         # MQTT 控制台面板（左：信息/命令/日志，右：命令调试）
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
| MQTT 控制台 | 查看 MQTT 连接状态、消息日志、命令调试（左：客户端信息 / 已注册命令 / 消息日志；右：命令调试与执行结果） |

### MQTT 通信

#### 控制台布局

`ui/mqtt_panel.py` 采用左右分区（可拖拽）：

- **左半区**：客户端信息 → 已注册命令 → 消息日志（日志占据左列剩余高度）
- **右半区**：命令调试（命令 / 参数 / 本地执行 / 远程发送 / 刷新），
  其中「执行结果」标题固定高度，下方结果面板吃掉全部剩余空间（不换行，便于查看终端输出）

执行结果按可读文本渲染：多行字段（`stdout` 等）以**真实换行**展开，不再显示成 `\n` 字面量；
其余字段以 `key: value` 单行呈现，嵌套结构用 JSON。

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
| `execute_shell` | **远程执行 Shell**（高危，见下方说明） | `command`, `reset?`, `timeout?`, `cwd?`, `max_output?` | `{exit_code, stdout, stderr, ok, timed_out, duration, cwd, user, shell, tty, backend, restarted}` |
| `terminal_reset` | 重启远程终端（清空全部状态） | 无 | `{restarted, backend, message}` |
| `terminal_interrupt` | 向终端前台发送 Ctrl+C | 无 | `{interrupted, message}` |
| `terminal_resize` | 调整终端窗口尺寸 | `rows?`(默认 24), `cols?`(默认 200) | `{rows, cols}` |
| `terminal_info` | 查询终端状态 | 无 | `{shell, pid, alive, tty, backend, rows, cols, cwd, uptime_seconds}` |

云端 / Agent 的完整对接说明（报文格式、参数与返回字段、超时与中断语义、最佳实践）
见 **[`doc/terminal_commands.md`](doc/terminal_commands.md)**。

云端通过下发 `list_commands` 可动态获取设备支持的完整能力列表。

#### `execute_shell` 说明

以**当前启动程序的用户身份**执行一整条命令行 —— 不切换用户、不提权，权限与客户端进程完全一致。
`command` 被视为可含空格的完整字符串，原样交给系统真实 shell 解析，
因此管道、重定向、通配符等 shell 语法均可用。

```json
{
  "command": "execute_shell",
  "params": { "command": "ls -la /tmp | head -5", "timeout": 10 }
}
```

##### 单一真实终端：所有命令共享同一个常驻 shell

客户端内部只维护**一个**常驻终端（`mqtt/terminal.py`）：PTY + 常驻交互式 shell。
`cd`、环境变量、别名、shell 函数、`umask`、`set -e`、`trap`、未闭合的多行结构
**全部真实保留**，与本地打开一个终端逐条敲命令完全等价。依次下发：

```json
{"command": "execute_shell", "params": {"command": "cd /tmp"}}
{"command": "execute_shell", "params": {"command": "ls"}}
{"command": "execute_shell", "params": {"command": "export GT=1"}}
{"command": "execute_shell", "params": {"command": "echo $GT"}}
{"command": "execute_shell", "params": {"command": "greet() { echo hi-$1; }"}}
{"command": "execute_shell", "params": {"command": "greet bob"}}
```

第二条 `ls` 列出 `/tmp`，第四条输出 `1`，第六条输出 `hi-bob`。
命令内 `[ -t 1 ]`、`python -c "import sys;print(sys.stdout.isatty())"` 等 TTY 判断均为真，
因此 `vim` / `top` / `cat` 这类交互程序也能正常工作。

实现要点：

| 机制 | 说明 |
|------|------|
| **PTY** | `pty.fork` 分配伪终端，关闭回显并抑制提示符，读取到的输出剥除 ANSI 转义序列 |
| **哨兵协议** | 命令后追加 `printf`，回显 UUID 标记 + 退出码 + `PWD` 以判定结束；结尾 `(exit $__gt_ec)` 还原 `$?`，不污染后续命令 |
| **中断与自愈** | 超时即向前台进程组发 `\x03`（Ctrl+C）回收终端；`exit` 或 shell 意外死亡时自动重启，该次调用返回 `restarted=true` |
| **串行执行** | 只有一个终端，命令加锁串行执行，不会互相穿插 |
| **降级** | 非 POSIX 平台（无 `pty`）自动回退到子进程模式，此时返回 `tty=false`、`backend="subprocess"` |

因为 PTY 上 stdout / stderr 是同一条流，返回体中 `stderr` 恒为空串，**全部输出合并到 `stdout`**。

| 边界 | 规则 |
|------|------|
| **起点** | 首次调用时惰性创建，加载 shell rc（如 conda）后就绪；初始工作目录为客户端进程目录（或显式 `cwd`） |
| **终点** | 显式重置（`terminal_reset` 命令或 `reset: true` 参数）、或客户端进程退出 |
| **隔离** | 只有一个终端，**不再提供多会话隔离**（`session_id` 已移除） |
| **重置** | `{"command": "terminal_reset"}` 或 `{"command": "execute_shell", "params": {"command": "...", "reset": true}}` |

##### 安全约束

该能力等价于向云端开放远程命令执行，因此实现中强制施加三重约束：

- **超时上限**：默认 30s，调用方最多可放大到 300s。命令在 MQTT 网络线程中同步执行，
  挂起会阻塞心跳上报并导致设备假离线，故超时不允许无限放大。
  超时后终端会收到 Ctrl+C，无法被中断时可再下发 `terminal_interrupt`。
- **输出截断**：`stdout` 截断至 8000 字符（可用 `max_output` 调整），避免撑爆 MQTT 报文。
- **审计日志**：每次执行前后均记录执行用户、命令行、退出码与耗时。

如需彻底关闭该能力，在 `.env` 中设置 `GREEN_TRACKER_ENABLE_SHELL=false`，此后调用将直接返回错误。

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
