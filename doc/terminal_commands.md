# 远程终端命令对接说明（`execute_shell` / `terminal_*`）

> 面向**云端服务与 Agent**：说明如何通过 MQTT 在设备上远程执行命令，
> 以及终端的行为语义、边界与对接最佳实践。
>
> 对应实现：`mqtt/terminal.py`（常驻 PTY 终端）、`mqtt/commands.py`（命令处理器）。

---

## 1. 能力概述

设备端只维护**一个常驻终端**：`pty.fork()` + 常驻交互式 shell（默认取 `$SHELL`，
`fish` / `csh` / `nu` 等非 POSIX 语法自动回退 `/bin/sh`）。

与「每条命令一个子进程」的实现相比，它的语义等价于**有人在机器旁开了一个终端**：

| 特性 | 说明 |
|------|------|
| 真实 TTY | 进程内 `isatty()` / `[ -t 1 ]` 为真，`vim` / `top` / 进度条类程序行为正常 |
| 状态真实连续 | 同一个 shell 进程：`cd`、`export`、`alias`、shell 函数、`umask`、`set -e`、`trap`、未闭合的多行结构全部保留 |
| 可中断 | 挂起的命令会被超时机制或 `terminal_interrupt` 以 Ctrl+C 中断，终端不销毁 |
| 自愈 | 命令里写了 `exit`、或 shell 意外死亡，下次调用自动重建终端并标记 `restarted=true` |
| 串行 | 全局一个终端 + 锁，命令按到达顺序串行执行，输出不会互相穿插 |
| 降级 | 非 POSIX 平台（无 `pty`）回退子进程模式，返回 `backend="subprocess"`、`tty=false` |

安全前提（当前阶段未做鉴权之外的限制）：以**启动客户端的操作系统用户**运行，不提权。

---

## 2. 调用通道

设备上线后会向宣告 topic 发布（retain）自己的三个 topic，云端可据此自动发现：

```
green-tracker/device/{device_id}/announce
```

| 用途 | Topic | 方向 |
|------|-------|------|
| 命令下发 | `green-tracker/device/{device_id}/command` | 云端 → 设备 |
| 命令响应 | `green-tracker/device/{device_id}/response` | 设备 → 云端 |
| 状态上报 | `green-tracker/device/{device_id}/status` | 设备 → 云端 |
| 遗嘱 LWT | `green-tracker/device/{device_id}/lwt` | 设备异常掉线 |

### 下发报文

```json
{
  "command_id": "req-20260916-0001",
  "command": "execute_shell",
  "params": { "command": "uname -a", "timeout": 10 }
}
```

- `command_id`：**必填**，响应原样回传，用于请求-响应关联（建议 UUID 或业务单号）
- `command`：命令名，可用 `list_commands` 动态发现
- `params`：命令参数对象，缺省 `{}`
- QoS：建议 `1`

### 响应报文

```json
{
  "command_id": "req-20260916-0001",
  "command": "execute_shell",
  "device_id": "dev-001",
  "success": true,
  "result": { "...": "命令自身的返回体" },
  "error": null,
  "timestamp": "2026-09-16T13:04:05.123456+00:00"
}
```

- `success=false` 时 `result` 为 `null`，`error` 为中文错误串（参数校验失败、命令被禁用、执行抛错等）
- 响应只会发到 `response` topic，**不会**回发到 `command` topic

---

## 3. 命令一览

`分类` = 指令预设关键字：`公有` 是跨平台通用契约，`拓展` 是可选能力、由平台侧按需开关。

| 命令 | 分类 | 作用 | 参数 |
|------|------|------|------|
| `list_commands` | 公有 | 发现设备支持的命令名 **与各指令元数据** | 无 |
| `ping` | 公有 | 心跳探活 | 无 |
| `execute_shell` | 拓展 | 在常驻终端执行一条命令行 | `command`, `timeout?`, `cwd?`, `max_output?`, `reset?` |
| `terminal_reset` | 拓展 | 重启终端，清空全部累积状态 | 无 |
| `terminal_interrupt` | 拓展 | 向终端前台发 Ctrl+C | 无 |
| `terminal_info` | 拓展 | 查询终端状态 | 无 |

### 3.1 能力发现与启用开关

`list_commands` 的返回体同时给出「可用清单」和「全部元数据」：

```json
{
  "commands": ["ping", "get_info", "..."],
  "specs": [
    {"name": "ping", "visibility": "public", "enabled": true,
     "default_enabled": true, "description": "...", "source": "default"},
    {"name": "execute_shell", "visibility": "extension", "enabled": false,
     "default_enabled": true, "description": "...", "source": "cloud"}
  ]
}
```

- `commands`：当前**启用**的命令名（老字段，语义不变）—— 只下发这里出现的命令
- `specs`：全部指令（含已禁用的）的元数据，供平台侧渲染开关
  - `visibility`：`public` 公有 / `extension` 拓展
  - `enabled`：当前是否可用；`default_enabled`：代码内预设值
  - `source`：`default` 预设 / `cloud` 平台下发 / `file` 本地策略文件
    （`config/command_policy.json`，路径可用 `GREEN_TRACKER_COMMAND_POLICY_FILE` 覆盖）
- 下发被禁用的命令会得到 `success=false`、`error="命令已被禁用: xxx"`
- `ping` / `list_commands` / `revoke_control` 为维持链路所必需，不可被禁用

> 远程 shell 可被 `.env` 中的 `GREEN_TRACKER_ENABLE_SHELL=false` 整体关闭；
> 关闭后 `execute_shell` / `terminal_reset` 直接返回 `success=false`，
> `error="execute_shell 已被禁用（GREEN_TRACKER_ENABLE_SHELL=false）"`。

---

## 4. `execute_shell`

### 4.1 参数

| 参数 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| `command` | string | **必填** | 完整命令行字符串，原样交给 shell 解析，可用管道/重定向/通配符/多行 |
| `timeout` | number | `30` | 超时秒数；超过 `300` 自动压到 `300`；必须为正数 |
| `cwd` | string | 不切换 | 先把终端 `cd` 到该目录再执行；**必须是设备本机存在的真实目录**，否则报错 |
| `max_output` | int | `8000` | `stdout` 截断长度（超出追加 `...[已截断，共 N 字符]`） |
| `reset` | bool | `false` | 执行前先重启终端（等价于先调 `terminal_reset`） |

`command` 为空/非字符串 → `error="缺少参数 command 或其不是非空字符串"`。

### 4.2 返回体（`result`）

```json
{
  "command": "ls -la | head -5",
  "exit_code": 0,
  "stdout": "total 48\ndrwxr-xr-x ...",
  "stderr": "",
  "ok": true,
  "timed_out": false,
  "duration": 0.031,
  "cwd": "/home/user/green-tracker-client",
  "user": "user",
  "shell": "/bin/bash",
  "tty": true,
  "backend": "pty",
  "restarted": false
}
```

| 字段 | 含义 |
|------|------|
| `exit_code` | 命令退出码；**超时/中断未救回时为 `-1`**，被 Ctrl+C 中断通常为 `130` |
| `stdout` | 命令输出（已剥离 ANSI 转义与提示符），按 `max_output` 截断 |
| `stderr` | **恒为空串** —— PTY 下 stdout/stderr 本就合并进同一条流（真终端语义） |
| `ok` | `exit_code == 0 且未超时` |
| `timed_out` | 是否被超时中断 |
| `duration` | 实际耗时（秒，3 位小数） |
| `cwd` | 命令执行后终端所在目录（可用于下一轮判断） |
| `user` | 执行该命令的操作系统用户 |
| `shell` | 终端使用的 shell 路径 |
| `tty` | 是否真终端；`false` 表示走了子进程降级 |
| `backend` | `"pty"` 或 `"subprocess"` |
| `restarted` | 本次调用是否重建过终端（`exit` 致死、进程崩溃、或 `reset=true`） |

### 4.3 状态连续性示例

依次下发 6 条，全程同一个 shell：

```json
{"command": "execute_shell", "params": {"command": "cd /tmp"}}
{"command": "execute_shell", "params": {"command": "ls"}}                          // 列出 /tmp
{"command": "execute_shell", "params": {"command": "export GT=1"}}
{"command": "execute_shell", "params": {"command": "echo $GT"}}                    // 1
{"command": "execute_shell", "params": {"command": "greet() { echo hi-$1; }"}}
{"command": "execute_shell", "params": {"command": "greet bob"}}                   // hi-bob
```

要点：

- **不需要**把状态塞进下一条命令，直接依赖终端即可
- `$?` 不会被内部机制污染：`false; echo $?` 输出 `1`
- 命令里执行 `exit` 不会让终端失效：会返回 `restarted=true`，下一轮从初始目录重新开始
- 想回到干净状态：下发 `terminal_reset`，或本次带 `"reset": true`

### 4.4 超时与中断

1. 命令在 `timeout` 秒内没有结束 → 自动向前台进程组发送 `\x03`（Ctrl+C）
2. 给一个短暂宽限期回收输出；成功回收则 `timed_out=true`、`exit_code=130`（或命令自身码）
3. 仍无响应 → `timed_out=true`、`exit_code=-1`，终端保留
4. 若命令长期霸占（如 `sleep 1000` 且 Ctrl+C 无效），可补发一次 `terminal_interrupt`

> 命令在 MQTT 网络线程中**同步**执行：挂起会阻塞心跳上报，设备可能被判离线，
> 因此超时上限硬顶 300s，且建议 Agent 侧默认用较小超时（10–30s）。

### 4.5 典型错误

| `error` | 原因 |
|---------|------|
| `缺少参数 command 或其不是非空字符串` | `command` 缺失或类型不对 |
| `timeout 必须是数字` / `timeout 必须为正数` | 参数类型/取值非法 |
| `cwd 不是有效目录: xxx` | 目录在设备本机不存在 |
| `execute_shell 已被禁用（GREEN_TRACKER_ENABLE_SHELL=false）` | 设备关闭了远程 shell |
| `命令已被禁用: xxx` | 该指令未启用（预设关闭 / 被平台策略或本地策略文件关闭） |
| `未知命令: xxx` | 命令名未注册 |

---

## 5. `terminal_*` 辅助命令

### `terminal_reset`

重启终端，丢弃全部累积状态（cwd / 环境变量 / 函数 / 别名）。

```json
{"command_id": "r1", "command": "terminal_reset", "params": {}}
```

```json
{"success": true, "result": {"restarted": true, "backend": "pty", "message": "终端已重启，状态已清空"}}
```

### `terminal_interrupt`

向终端前台进程发 Ctrl+C，用于挽回被挂起的命令（**不销毁终端**）。

```json
{"success": true, "result": {"interrupted": true, "message": "已发送 Ctrl+C"}}
```

`interrupted=false` 表示终端当前没有在运行（无需中断）；无 PTY 平台返回
`{"interrupted": false, "message": "当前平台无 PTY 终端，无需中断"}`。

### `terminal_info`

```json
{"success": true, "result": {
  "shell": "/bin/bash", "pid": 12345, "alive": true,
  "tty": true, "backend": "pty", "rows": 24, "cols": 200,
  "cwd": "/home/user/green-tracker-client", "uptime_seconds": 128.4
}}
```

`backend="subprocess"` / `tty=false` 表示当前平台无 PTY，走的是降级路径。

---

## 6. Agent 对接建议

1. **先发现再调用**：`list_commands` 拿命令清单 → `ping` 探活 → 再发业务命令。
2. **一条命令一件事**：依赖终端状态是允许的，但 Agent 侧应显式下发 `cd`，
   或用 `cwd` 参数，避免假设当前目录。
3. **给每条命令设置合理 `timeout`**：探索性命令 10s，构建/安装类按需要放大（≤300）。
   超时后先按 `timed_out` 处理，必要时补 `terminal_interrupt`，而不是立刻重试。
4. **解析输出**：只看 `stdout`（`stderr` 恒空）；大输出调大 `max_output`，
   或让命令自限（`| head -50`、`| tail -20`）。
5. **避免交互式程序**：`vim`、`top`、`ssh` 登录等会挂到超时，
   改为非交互等价命令（`sed -i`、`ps aux --sort=-%cpu | head`、批处理参数）。
6. **收尾清理**：一次任务结束前发 `terminal_reset`，避免残留状态影响下一次会话。
7. **不可重放**：命令有副作用且终端是有状态的，失败重试前先判断是否安全
   （例如 `mkdir` 前先 `test -d`，写文件用幂等方式）。
8. **审计**：设备侧每条命令都会记录 `user` / 命令行 / 退出码 / 耗时（WARNING 级日志）。

### paho-mqtt 最小示例

```python
import json, uuid
import paho.mqtt.client as mqtt

DEVICE_ID = "dev-001"
CMD_TOPIC = f"green-tracker/device/{DEVICE_ID}/command"
RESP_TOPIC = f"green-tracker/device/{DEVICE_ID}/response"

client = mqtt.Client()
client.username_pw_set(DEVICE_ID, "<secret>")
client.connect("broker.host", 1883, 60)
client.subscribe(RESP_TOPIC, qos=1)
client.loop_start()

def execute(command: str, timeout: int = 20, **params) -> dict:
    req_id = str(uuid.uuid4())
    payload = {
        "command_id": req_id,
        "command": "execute_shell",
        "params": {"command": command, "timeout": timeout, **params},
    }
    client.publish(CMD_TOPIC, json.dumps(payload), qos=1)
    # 在 on_message 里按 command_id == req_id 匹配响应并取出 result
```

---

## 7. 降级模式（无 PTY）

Windows 等无 `pty` 模块的环境自动回退到子进程实现（`ShellSessionManager`），差异：

| 项 | PTY | 降级 |
|----|-----|------|
| `backend` / `tty` | `pty` / `true` | `subprocess` / `false` |
| `isatty()` | 真 | 假 |
| stdout / stderr | 合并 | 分开（`stderr` 有内容） |
| 交互程序 / Ctrl+C | 支持 | 不支持 |
| 状态保留范围 | 全部（含函数、`umask`、`trap`） | cwd / 环境变量 / 别名（靠每轮回传重建） |

Agent 侧**只需判断 `tty`**：为 `false` 时不要依赖 TTY 行为与 `terminal_interrupt`。
