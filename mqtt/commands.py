"""
命令处理器注册表与内置命令。

使用装饰器注册命令处理函数，支持动态扩展。
"""

import json
import locale
import logging
import os
import platform
import socket
import subprocess
import threading
import time
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Callable, Dict, List, Optional, Tuple

from config import command_policy_file

from api import heartbeat as _heartbeat
from api.cloud_state import get_cloud_state
from . import terminal


logger = logging.getLogger("mqtt-commands")


# 收到 `revoke_control` 后仍可执行的命令 —— 只保留连接维持相关能力
REVOKED_ALLOWED_COMMANDS = {"ping", "revoke_control"}
REVOKE_BLOCKED_MESSAGE = "控制权限已被云端撤销，仅保留连接相关命令"
NO_CONTROL_MESSAGE = "云端未向本设备开放控制能力（等下次签到结果变化）"


# ============================================================
# 指令预设元数据：公有 / 拓展 + 启用开关
#
# * visibility="public"    —— 公有指令：跨平台通用契约，任何接入方都可依赖
# * visibility="extension" —— 拓展指令：能力可选，由平台侧按需开关
#
# 每条指令在注册时用一个关键字声明「默认是否启用」（enabled），
# 其他平台即可据此做拓展配置，无需改动本仓库代码。启用判定按
# **后者覆盖前者**：
#
#   1. 注册时声明的 enabled          —— 代码内预设（本仓库给出的默认值）
#   2. apply_command_policy(...)     —— 云端 / 其他平台运行时下发的策略
#   3. 本地策略文件                  —— 部署方的最终否决权
#      config/command_policy.json，路径可用
#      GREEN_TRACKER_COMMAND_POLICY_FILE 覆盖
#
# 例：关闭高危远程终端（config/command_policy.json）
#   {"execute_shell": false, "terminal_reset": false, "cloud_probe": true}
# ============================================================

VISIBILITY_PUBLIC = "public"
VISIBILITY_EXTENSION = "extension"

# 维持链路所必需的公有指令 —— 不允许被任何外部策略禁用（否则设备不可恢复）
PROTECTED_COMMANDS = frozenset({"ping", "list_commands", "revoke_control"})

DISABLED_MESSAGE = "命令已被禁用: {name}"

_TRUE_WORDS = ("1", "true", "yes", "on", "enable", "enabled")
_FALSE_WORDS = ("0", "false", "no", "off", "disable", "disabled")


@dataclass
class CommandSpec:
    """一条指令预设的元数据（不含处理函数本身）。"""

    name: str
    visibility: str = VISIBILITY_EXTENSION
    default_enabled: bool = True
    description: str = ""


def _as_bool(raw: object) -> Optional[bool]:
    """把外部配置值收敛为 bool；无法识别返回 None（表示忽略该项）。"""
    if isinstance(raw, bool):
        return raw
    if isinstance(raw, (int, float)):
        return bool(raw)
    if isinstance(raw, str):
        text = raw.strip().lower()
        if text in _TRUE_WORDS:
            return True
        if text in _FALSE_WORDS:
            return False
    return None


def _first_line(doc: Optional[str]) -> str:
    """取文档字符串首行作为默认描述。"""
    for line in (doc or "").splitlines():
        if line.strip():
            return line.strip()
    return ""


def _parse_policy_file(path: str) -> Dict[str, bool]:
    """读取本地策略文件，解析成 {命令名: 是否启用}。

    文件缺失 = 不覆盖任何预设（不是错误）；内容非法则记 WARNING 并整体忽略。
    """
    try:
        with open(path, "r", encoding="utf-8") as fh:
            raw = fh.read()
    except FileNotFoundError:
        logger.debug("策略文件不存在，沿用预设: %s", path)
        return {}
    except OSError as e:
        logger.warning("策略文件读取失败，已忽略: %s (%s)", path, e)
        return {}

    if not raw.strip():
        return {}

    try:
        parsed = json.loads(raw)
    except ValueError as e:
        logger.warning("策略文件不是合法 JSON，已忽略: %s (%s)", path, e)
        return {}

    if not isinstance(parsed, dict):
        logger.warning("策略文件应为 {命令名: 是否启用} 对象，已忽略: %s", path)
        return {}

    policy: Dict[str, bool] = {}
    for name, value in parsed.items():
        if name in PROTECTED_COMMANDS and not _as_bool(value):
            logger.warning("公有基础指令不允许被禁用，已忽略: %s", name)
            continue
        flag = _as_bool(value)
        if flag is None:
            logger.warning("策略项无法识别，已忽略: %s=%r", name, value)
            continue
        policy[str(name)] = flag

    if policy:
        logger.info("[command-policy] 载入本地策略 %s: %s", path, policy)
    return policy


class CommandHandler:
    """命令处理器：管理命令名称到处理函数的映射，及其预设元数据。"""

    _registry: Dict[str, Callable[[dict], dict]] = {}
    # 指令预设元数据（公有/拓展 + 默认启用关键字），与 _registry 一一对应
    _specs: Dict[str, CommandSpec] = {}
    # 云端 / 其他平台运行时下发的启用策略（见 apply_command_policy）
    _policy: Dict[str, bool] = {}
    # 本地策略文件缓存: (路径, mtime, 大小, 解析结果)
    _file_cache: Optional[Tuple[str, float, int, Dict[str, bool]]] = None

    @classmethod
    def register(cls, command_name: str, *, visibility: str = VISIBILITY_EXTENSION,
                 enabled: bool = True, description: str = "") -> Callable:
        """
        装饰器：将函数注册为指定命令的处理器，并声明其预设元数据。

        Args:
            command_name: 命令名
            visibility:   "public"（公有指令，跨平台通用契约）
                          或 "extension"（拓展指令，按平台需要开关）
            enabled:      预设是否启用 —— 其他平台据此做拓展配置的默认值
            description:  简短说明，随 list_commands 一起暴露给平台侧
        """

        def decorator(func: Callable[[dict], dict]) -> Callable:
            cls._registry[command_name] = func
            cls._specs[command_name] = CommandSpec(
                name=command_name,
                visibility=visibility,
                default_enabled=enabled,
                description=description or _first_line(func.__doc__),
            )
            logger.debug("已注册命令: %s (visibility=%s, enabled=%s)",
                         command_name, visibility, enabled)
            return func

        return decorator

    # -----------------------------------------------------------------
    # 启用开关（预设 < 云端策略 < 本地策略文件）
    # -----------------------------------------------------------------

    @classmethod
    def is_enabled(cls, command: str) -> bool:
        """该命令当前是否可用（综合预设、云端策略与本地策略文件）。"""
        file_policy = cls._file_policy()
        if command in file_policy:
            return file_policy[command]
        if command in cls._policy:
            return cls._policy[command]
        spec = cls._specs.get(command)
        return spec.default_enabled if spec else True

    @classmethod
    def apply_policy(cls, policy: Optional[dict], *, source: str = "cloud") -> Dict[str, bool]:
        """
        应用外部下发的启用策略，如 {"execute_shell": false, "cloud_probe": true}。

        公有基础指令（PROTECTED_COMMANDS）不可被禁用，对应项会被忽略。
        返回实际生效的部分。

        优先级：预设 < 本策略 < 本地策略文件（部署方保留最终否决权）。
        """
        applied: Dict[str, bool] = {}
        for name, raw in (policy or {}).items():
            if not isinstance(name, str):
                continue
            flag = _as_bool(raw)
            if flag is None:
                logger.warning("策略项无法识别，已忽略: %s=%r", name, raw)
                continue
            if name in PROTECTED_COMMANDS and not flag:
                logger.warning("公有基础指令不允许被禁用，已忽略: %s", name)
                continue
            cls._policy[name] = flag
            applied[name] = flag

        if applied:
            logger.info("[command-policy] 应用 %s 策略: %s", source, applied)
        return applied

    @classmethod
    def reset_policy(cls) -> None:
        """清空运行时下发的策略（回到预设 + 本地策略文件）。"""
        cls._policy = {}

    @classmethod
    def _file_policy(cls) -> Dict[str, bool]:
        """本地策略文件（按路径 + mtime + 大小缓存，改文件后立即生效）。"""
        path = command_policy_file()
        try:
            stat = os.stat(path)
        except OSError:
            # 文件不存在：与「空策略」等价，避免每次调用都打日志
            cache = (path, -1.0, -1, {})
            cls._file_cache = cache
            return cache[3]

        stamp = (path, stat.st_mtime, stat.st_size)
        cached = cls._file_cache
        if cached is not None and cached[:3] == stamp:
            return cached[3]

        parsed = _parse_policy_file(path)
        cls._file_cache = (*stamp, parsed)
        return parsed

    # -----------------------------------------------------------------
    # 能力发现
    # -----------------------------------------------------------------

    @classmethod
    def list_commands(cls, include_disabled: bool = False) -> list:
        """列出命令名；默认只列当前启用的（供云端动态发现）。"""
        if include_disabled:
            return list(cls._registry.keys())
        return [name for name in cls._registry if cls.is_enabled(name)]

    @classmethod
    def describe(cls, command: str) -> dict:
        """单条指令的元数据快照（供平台侧做拓展配置）。"""
        spec = cls._specs.get(command)
        if command in cls._file_policy():
            source = "file"
        elif command in cls._policy:
            source = "cloud"
        else:
            source = "default"

        return {
            "name": command,
            "visibility": spec.visibility if spec else VISIBILITY_EXTENSION,
            "enabled": cls.is_enabled(command),
            "default_enabled": spec.default_enabled if spec else True,
            "description": spec.description if spec else "",
            "source": source,
        }

    @classmethod
    def describe_commands(cls) -> List[dict]:
        """全部指令的元数据快照（含已禁用的，便于平台侧渲染开关）。"""
        return [cls.describe(name) for name in cls._registry]

    @classmethod
    def execute(cls, command: str, params: Optional[dict] = None,
                local: bool = False) -> dict:
        """
        执行指定命令并返回结果字典。

        门控放在这里（而非只放在 MQTT 回调里），使 MQTT 下发、HTTP 轮询、
        面板本地调试三条入口同时受控：
          * 未启用（预设为关 / 被平台策略或环境变量关掉）的命令一律拒绝
          * 收到 `revoke_control` 后仅 `REVOKED_ALLOWED_COMMANDS` 仍可执行
          * 已同步过且云端未开放控制能力时，云端指令一律拒绝
            （`local=True` 的面板本地调试不受此条限制）

        Returns:
            {"success": True, "result": ...} 或 {"success": False, "error": ...}
        """
        if not cls.is_enabled(command):
            logger.warning("命令未启用，拒绝执行: %s", command)
            return {"success": False, "error": DISABLED_MESSAGE.format(name=command)}

        state = get_cloud_state()
        if state.is_revoked() and command not in REVOKED_ALLOWED_COMMANDS:
            logger.warning("控制权限已撤销，拒绝执行指令: %s", command)
            return {"success": False, "error": REVOKE_BLOCKED_MESSAGE}

        if not local and state.synced and not state.can_receive_commands():
            logger.warning("云端未开放控制能力，拒绝执行指令: %s", command)
            return {"success": False, "error": NO_CONTROL_MESSAGE}

        handler = cls._registry.get(command)
        if handler is None:
            return {"success": False, "error": f"未知命令: {command}"}

        try:
            result = handler(params or {})
            return {"success": True, "result": result}
        except Exception as e:
            logger.error(f"命令执行异常 [{command}]: {e}", exc_info=True)
            return {"success": False, "error": str(e)}


# 记录启动时间（用于 uptime 计算）
_start_time = time.time()


# ============================================================
# 内置命令
# ============================================================

@CommandHandler.register("ping", visibility=VISIBILITY_PUBLIC, enabled=True,
                         description="心跳探活 —— 公有指令，任何平台都可依赖")
def cmd_ping(params: dict) -> dict:
    """心跳检测 — 立即响应。"""
    return {
        "pong": True,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "uptime": round(time.time() - _start_time, 2),
    }


@CommandHandler.register("get_info", visibility=VISIBILITY_PUBLIC, enabled=True,
                         description="设备基本信息 —— 公有指令")
def cmd_get_info(params: dict) -> dict:
    """获取设备基本信息。"""
    # 获取本机 IP
    _ip = "127.0.0.1"
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        _ip = s.getsockname()[0]
        s.close()
    except Exception:
        pass

    return {
        "device_id": __get_device_id(),
        "hostname": socket.gethostname(),
        "platform": platform.platform(),
        "python_version": platform.python_version(),
        "local_ip": _ip,
    }


@CommandHandler.register("reboot", visibility=VISIBILITY_PUBLIC, enabled=True,
                         description="重启设备 —— 公有指令（客户端侧仅记录日志）")
def cmd_reboot(params: dict) -> dict:
    """模拟重启设备（客户端侧仅记录日志）。"""
    delay = params.get("delay", 5)
    logger.warning(f"设备将在 {delay} 秒后重启...")
    return {"message": f"设备已接收重启指令，{delay}秒后重启", "delay": delay}


@CommandHandler.register("set_config", visibility=VISIBILITY_EXTENSION, enabled=True,
                         description="设置/更新设备配置 —— 拓展指令（占位实现，语义未定型）")
def cmd_set_config(params: dict) -> dict:
    """设置/更新设备配置（占位实现）。"""
    key = params.get("key")
    value = params.get("value")
    if not key or value is None:
        raise ValueError("缺少参数 key 或 value")

    logger.info(f"配置已更新: {key}={value}")
    return {"message": "配置更新成功", "key": key, "value": value}


@CommandHandler.register("get_metrics", visibility=VISIBILITY_PUBLIC, enabled=True,
                         description="设备运行指标 —— 公有指令")
def cmd_get_metrics(params: dict) -> dict:
    """获取设备运行指标（模拟数据，可接入真实传感器）。"""
    import random

    return {
        "cpu_usage": round(random.uniform(10, 80), 2),
        "memory_usage": round(random.uniform(30, 70), 2),
        "temperature": round(random.uniform(35, 65), 1),
        "uptime_seconds": int(time.time() - _start_time),
    }


@CommandHandler.register("list_commands", visibility=VISIBILITY_PUBLIC, enabled=True,
                         description="能力发现 —— 公有指令，返回启用清单与各指令元数据")
def cmd_list_commands(params: dict) -> dict:
    """列出设备支持的所有可用命令（供云端动态发现）。

    返回体：
        commands —— 当前**启用**的命令名（向后兼容，云端仍按此字段发现能力）
        specs    —— 全部指令的元数据（含已禁用的），供平台侧渲染开关：
                    {name, visibility, enabled, default_enabled, description, source}
    """
    return {
        "commands": CommandHandler.list_commands(),
        "specs": CommandHandler.describe_commands(),
    }


@CommandHandler.register("cloud_probe", visibility=VISIBILITY_EXTENSION, enabled=True,
                         description="云端探测 —— 拓展指令，验证 command discovery 链路")
def cmd_cloud_probe(params: dict) -> dict:
    """云端探测指令 — 验证云端能否通过 list_commands 发现并下发此命令。"""
    return {
        "probe_response": "ok",
        "device_id": __get_device_id(),
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "note": "如果你看到这条消息，说明云端已成功完成 command discovery 并下发指令",
    }


# ============================================================
# Shell 执行
#
# 高危能力：等价于向云端开放远程命令执行（RCE）。
# 因此本命令强制施加三重约束：
#   1. 超时上限 —— 命令在 MQTT 网络线程中同步执行（见 client._handle_command），
#      一旦挂起会阻塞心跳上报，导致设备被判定离线，故超时不可由调用方无限放大；
#   2. 输出截断 —— stdout/stderr 单独截断，避免撑爆 MQTT 报文；
#   3. 审计日志 —— 每条命令执行前后均落 WARNING/INFO 日志。
#
# 如需彻底关闭该能力，可在 .env 中设置 GREEN_TRACKER_ENABLE_SHELL=false。
# ============================================================

_SHELL_DEFAULT_TIMEOUT = 30.0    # 默认超时（秒）
_SHELL_MAX_TIMEOUT = 300.0       # 单次调用允许的超时上限
_SHELL_MAX_OUTPUT = 8000         # stdout / stderr 各自的最大返回字符数
_SHELL_ENCODING = locale.getpreferredencoding(False) or "utf-8"


def _shell_enabled() -> bool:
    """总开关（默认开启，置为 false 可彻底禁用远程 shell）。"""
    return os.getenv("GREEN_TRACKER_ENABLE_SHELL", "true").strip().lower() not in (
        "0", "false", "no", "off", "",
    )


def _shell_path() -> str:
    """系统真实 shell 路径（即 subprocess(shell=True) 实际调用的解释器）。"""
    if os.name == "nt":
        return os.environ.get("COMSPEC", "cmd.exe")
    # POSIX 下 subprocess(shell=True) 固定调用 /bin/sh，与 $SHELL 环境变量无关
    return "/bin/sh"


def _truncate_output(text: object, limit: int) -> str:
    """截断超长输出，避免撑爆 MQTT 报文。"""
    if text is None:
        return ""
    if isinstance(text, bytes):
        text = text.decode(_SHELL_ENCODING, errors="replace")
    if len(text) <= limit:
        return text
    return f"{text[:limit]}...[已截断，共 {len(text)} 字符]"


def _current_user() -> str:
    """当前进程所属用户名（无法获取时返回空串）。"""
    try:
        import getpass

        return getpass.getuser()
    except Exception:
        return ""


# ============================================================
# Shell 会话上下文
#
# 目标：把命令序列当作**同一个 shell 会话**来执行 ——
# `cd /tmp` 之后的 `ls` 必须列出 /tmp，export / alias 同理。
#
# 实现：**状态外部化**（externalized state），而非常驻 shell 进程。
# 每条命令仍在独立 shell 进程中执行，结束时由 shell 回传退出码、PWD、
# 全部环境变量与别名；Python 侧据此更新会话状态，并作为下一条命令的
# 初始状态注入。
#
# 之所以不用常驻 shell 进程（Popen 保持 stdin 常开）：
#   1. 非交互 shell 的 stdout 是块缓冲，写完命令后 readline 会永久阻塞，
#      要绕过就得上 pty —— Windows 无原生支持；
#   2. 交互式命令（cat / python REPL）会挂住整个会话，只能靠超时杀死，
#      而杀死 shell 又会连带丢失全部累积状态；
#   3. 常驻进程有泄漏风险，输出边界要靠哨兵、实现脆弱。
# 状态外部化没有上述问题：每条命令独立超时、无缓冲死锁、无进程泄漏。
#
# 代价 —— 以下状态**不保留**，需由单条命令自包含：
#   shell 函数定义、`set -e` 等 shell 选项、umask、trap、
#   未完成的多行结构（未闭合的 if / heredoc）。
# ============================================================

_SESSION_DEFAULT_ID = "default"   # 未指定 session_id 时共用的会话
_SESSION_MAX_IDLE = 1800.0        # 空闲 30 分钟后回收
_SESSION_MAX_COUNT = 32           # 会话数量上限（超出按最久未用驱逐）


def _split_state_block(output: str, token: str) -> Tuple[str, dict]:
    """
    从 shell 输出中剥离状态同步块。

    Returns:
        (用户可见输出, 状态字典)；未识别到状态块时状态为空字典。
    """
    begin = f"__GT_CTX_{token}_BEGIN__"
    end = f"__GT_CTX_{token}_END__"
    b = output.find(begin)
    e = output.find(end)
    if b == -1 or e == -1 or e < b:
        # 拿不到状态（如命令把输出重定向了）时，全部按用户输出处理
        return output, {}

    state: Dict[str, Any] = {"env": {}, "aliases": []}
    section: Optional[str] = None
    for line in output[b + len(begin):e].splitlines():
        line = line.rstrip("\r")
        if line in ("ALIAS_BEGIN", "ALIAS_END", "ENV_BEGIN", "ENV_END"):
            section = line.split("_")[0].lower() if line.endswith("_BEGIN") else None
            continue
        if line.startswith("EC="):
            try:
                state["exit_code"] = int(line[3:].strip())
            except ValueError:
                pass
            continue
        if line.startswith("PWD="):
            state["pwd"] = line[4:]
            continue
        if section == "alias" and line.strip():
            # dash 输出 `ll='ls -l'`，bash 输出 `alias ll='ls -l'` —— 统一成裸定义
            normalized = line.strip()
            if normalized.startswith("alias "):
                normalized = normalized[len("alias "):]
            state["aliases"].append(normalized)
        elif section == "env" and "=" in line:
            key, value = line.split("=", 1)
            state["env"][key] = value

    return output[:b], state


class ShellSession:
    """
    一个连续的 shell 上下文：跨命令保留工作目录、环境变量与别名。

    会话内的 lock 保证同一上下文串行执行，避免并发命令交错污染状态。
    生命周期边界见 ShellSessionManager。
    """

    def __init__(self, session_id: str, cwd: Optional[str] = None,
                 env: Optional[dict] = None):
        self.session_id = session_id
        self.cwd = os.path.realpath(cwd) if cwd and os.path.isdir(cwd) else os.getcwd()
        self.env: Dict[str, str] = dict(env) if env is not None else dict(os.environ)
        self.aliases: List[str] = []
        self.created_at = time.time()
        self.last_used = self.created_at
        self.lock = threading.RLock()

    # -----------------------------------------------------------------
    # 脚本构造
    # -----------------------------------------------------------------

    def _build_script(self, command: str, token: str) -> str:
        """把用户命令包装成「执行 + 状态回传」脚本。"""
        begin = f"__GT_CTX_{token}_BEGIN__"
        end = f"__GT_CTX_{token}_END__"

        if os.name == "nt":
            # cmd.exe 在 `&` 链中不会延迟展开 %ERRORLEVEL% / %CD%，
            # 用 `call echo %%VAR%%` 触发二次解析以取到当前值。
            # （`&` 无条件执行，因此命令失败时状态块同样会回传。）
            tail = (
                f"&echo {begin}"
                f"&call echo EC=%%ERRORLEVEL%%"
                f"&call echo PWD=%%CD%%"
                f"&echo ALIAS_BEGIN&echo ALIAS_END"
                f"&echo ENV_BEGIN&set&echo ENV_END"
                f"&echo {end}"
            )
            return f"{command}{tail}"

        # POSIX：先恢复别名 → 执行命令 → 回传状态（用换行分隔，无条件执行）
        head = "".join(f"alias {a}\n" for a in self.aliases)
        tail = (
            f"\n__gt_ec=$?\n"
            f'echo "{begin}"\n'
            f'echo "EC=$__gt_ec"\n'
            f'echo "PWD=$(pwd)"\n'
            f'echo "ALIAS_BEGIN"\n'
            f"alias 2>/dev/null\n"
            f'echo "ALIAS_END"\n'
            f'echo "ENV_BEGIN"\n'
            f"env\n"
            f'echo "ENV_END"\n'
            f'echo "{end}"'
        )
        return f"{head}{command}{tail}"

    # -----------------------------------------------------------------
    # 执行
    # -----------------------------------------------------------------

    def run(self, command: str, timeout: float, max_output: int,
            cwd: Optional[str] = None) -> dict:
        """在当前上下文中执行一条命令，并把结束状态写回上下文。"""
        with self.lock:
            self.last_used = time.time()
            if cwd:
                self.cwd = os.path.realpath(cwd)

            token = uuid.uuid4().hex
            script = self._build_script(command, token)
            started = time.time()

            try:
                completed = subprocess.run(
                    script,
                    shell=True,
                    capture_output=True,
                    text=True,
                    encoding=_SHELL_ENCODING,
                    errors="replace",
                    timeout=timeout,
                    cwd=self.cwd,
                    env=self.env,
                )
                raw_out = completed.stdout or ""
                raw_err = completed.stderr or ""
                timed_out = False
                fallback_code = completed.returncode
            except subprocess.TimeoutExpired as exc:
                # 超时时状态未知，保持会话原有状态不变
                raw_out = exc.stdout or ""
                raw_err = exc.stderr or ""
                timed_out = True
                fallback_code = -1

            user_output, state = _split_state_block(raw_out, token)
            if not timed_out and state:
                self._apply_state(state)

            exit_code = state["exit_code"] if state.get("exit_code") is not None \
                else fallback_code
            if timed_out:
                exit_code = -1

            duration = round(time.time() - started, 3)
            return {
                "command": command,
                "exit_code": exit_code,
                "stdout": _truncate_output(user_output, max_output),
                "stderr": _truncate_output(raw_err, max_output),
                "ok": exit_code == 0 and not timed_out,
                "timed_out": timed_out,
                "duration": duration,
                "cwd": self.cwd,
                "shell": _shell_path(),
            }

    def _apply_state(self, state: Dict[str, Any]) -> None:
        """把 shell 回传的状态写回会话。"""
        pwd = state.get("pwd")
        if pwd and os.path.isdir(pwd):
            self.cwd = pwd
        if state.get("env"):
            self.env = dict(state["env"])
        self.aliases = list(state.get("aliases") or [])


class ShellSessionManager:
    """
    shell 会话上下文注册表 —— 定义上下文的边界与隔离规则。

    **降级路径**：仅在平台不支持 PTY（非 POSIX）时由 `execute_shell` 使用，
    正常路径走 `mqtt.terminal.Terminal`（常驻 PTY 真终端）。

    * 起点：某个 session_id **首次被使用时惰性创建**。初始工作目录为客户端
      进程工作目录（或显式传入的 cwd），初始环境为客户端进程环境。
    * 终点：显式重置（`reset=true` 参数）、客户端进程退出、或空闲超过
      `_SESSION_MAX_IDLE` 被自动回收。
    * 隔离：不同 session_id 各自持有独立的 cwd / env / 别名，互不干扰。
      未指定 session_id 时共用 `"default"`，即云端视角下的「同一个会话」。
    """

    _sessions: Dict[str, "ShellSession"] = {}
    _lock = threading.RLock()

    @classmethod
    def get(cls, session_id: str = _SESSION_DEFAULT_ID, cwd: Optional[str] = None,
            env: Optional[dict] = None, reset: bool = False) -> "ShellSession":
        """获取（必要时创建）指定会话。"""
        with cls._lock:
            cls._evict_locked()
            if reset or session_id not in cls._sessions:
                cls._sessions[session_id] = ShellSession(session_id, cwd=cwd, env=env)
            return cls._sessions[session_id]

    @classmethod
    def reset(cls, session_id: Optional[str] = None) -> int:
        """重置会话（None 表示重置全部），返回被销毁的会话数。"""
        with cls._lock:
            if session_id is None:
                count = len(cls._sessions)
                cls._sessions.clear()
                return count
            return 1 if cls._sessions.pop(session_id, None) is not None else 0

    @classmethod
    def list(cls) -> List[dict]:
        """列出活跃会话的上下文摘要。"""
        with cls._lock:
            cls._evict_locked()
            now = time.time()
            return [
                {
                    "session_id": s.session_id,
                    "cwd": s.cwd,
                    "idle_seconds": round(now - s.last_used, 1),
                    "age_seconds": round(now - s.created_at, 1),
                    "alias_count": len(s.aliases),
                    "env_count": len(s.env),
                }
                for s in cls._sessions.values()
            ]

    @classmethod
    def _evict_locked(cls) -> None:
        """回收空闲会话，并把总数压回上限（LRU）。"""
        now = time.time()
        for sid in [k for k, s in cls._sessions.items()
                    if now - s.last_used > _SESSION_MAX_IDLE]:
            cls._sessions.pop(sid, None)

        overflow = len(cls._sessions) - _SESSION_MAX_COUNT
        if overflow > 0:
            oldest = sorted(cls._sessions,
                            key=lambda k: cls._sessions[k].last_used)[:overflow]
            for sid in oldest:
                cls._sessions.pop(sid, None)


@CommandHandler.register("execute_shell", visibility=VISIBILITY_EXTENSION, enabled=True,
                         description="远程执行 Shell —— 高危拓展指令，"
                                     "另受 GREEN_TRACKER_ENABLE_SHELL 总开关约束")
def cmd_execute_shell(params: dict) -> dict:
    """
    在**常驻终端**中执行一条命令行 —— 命令序列共享同一个 shell。

    以**当前启动程序的用户身份**运行 —— 不切换用户、不提权，权限与客户端
    进程完全一致。命令交给一个常驻的交互式 shell 进程（经伪终端 PTY 相连，
    见 mqtt/terminal.py），因此：

    * 状态**真实**连续 —— 始终是同一个进程，cd / export / alias /
      shell 函数 / umask / trap 全部自然保留（先 `cd /tmp` 再 `ls`，
      列出的就是 /tmp），无需任何状态搬运；
    * 程序看到的是**真终端** —— `isatty()` 为真，管道、重定向、通配符可用，
      交互式程序与进度条的行为与本地终端一致；
    * 挂起的命令可被 Ctrl+C 中断；shell 被 `exit` 结束会自动重启。

    全程只有一个终端，命令串行执行（需求只要一个终端，故不做多会话隔离）。

    params:
        command (str, 必填): 完整命令行，如 `ls -la | head -5`
        reset (bool, 可选): 执行前先重启终端，丢弃全部累积状态
        timeout (float, 可选): 超时秒数，默认 30，上限 300
        cwd (str, 可选): 先把终端切换到该目录再执行
        max_output (int, 可选): stdout 截断长度，默认 8000

    Returns:
        dict: exit_code / stdout / ok / timed_out / duration / cwd /
              user / shell / tty / backend / restarted
    """
    if not _shell_enabled():
        raise RuntimeError("execute_shell 已被禁用（GREEN_TRACKER_ENABLE_SHELL=false）")

    command = params.get("command")
    if not isinstance(command, str) or not command.strip():
        raise ValueError("缺少参数 command 或其不是非空字符串")
    command = command.strip()

    try:
        timeout = float(params.get("timeout", _SHELL_DEFAULT_TIMEOUT))
    except (TypeError, ValueError):
        raise ValueError("timeout 必须是数字")
    if timeout <= 0:
        raise ValueError("timeout 必须为正数")
    timeout = min(timeout, _SHELL_MAX_TIMEOUT)

    try:
        max_output = int(params.get("max_output", _SHELL_MAX_OUTPUT))
    except (TypeError, ValueError):
        raise ValueError("max_output 必须是整数")
    if max_output <= 0:
        raise ValueError("max_output 必须为正数")

    cwd = params.get("cwd")
    if cwd is not None and not (isinstance(cwd, str) and os.path.isdir(cwd)):
        raise ValueError(f"cwd 不是有效目录: {cwd}")

    user = _current_user()
    logger.warning(
        "[execute_shell] user=%s cmd=%r timeout=%s cwd=%s", user, command, timeout, cwd
    )

    result = _run_in_context(command, timeout=timeout, max_output=max_output,
                             cwd=cwd, reset=bool(params.get("reset", False)))
    result["user"] = user

    if result["timed_out"]:
        logger.error("[execute_shell] 超时: %r (%.1fs)", command, timeout)
    else:
        logger.info("[execute_shell] exit=%s duration=%ss cwd=%s",
                    result["exit_code"], result["duration"], result.get("cwd"))
    return result


def _run_in_context(command: str, timeout: float, max_output: int,
                    cwd: Optional[str], reset: bool) -> dict:
    """在共享上下文中执行命令；POSIX 走 PTY 真终端，其他平台降级。"""
    if not terminal.supported():
        # 无 PTY（Windows）：降级为「状态外部化」实现，仍保持 cd/env 连续
        session = ShellSessionManager.get(_SESSION_DEFAULT_ID, cwd=cwd, reset=reset)
        result = session.run(command, timeout=timeout, max_output=max_output, cwd=cwd)
        result["tty"] = False
        result["backend"] = "subprocess"
        result.setdefault("restarted", False)
        return result

    term = terminal.get_terminal()
    if reset:
        term.reset()
    if cwd:
        term.cd(cwd)
    return term.run(command, timeout=timeout, max_output=max_output)


@CommandHandler.register("terminal_reset", visibility=VISIBILITY_EXTENSION, enabled=True,
                         description="重启远程终端 —— 拓展指令，随 execute_shell 一起开关")
def cmd_terminal_reset(params: dict) -> dict:
    """
    重启终端 —— 丢弃全部累积状态（工作目录、环境变量、函数、别名）。

    这是上下文的**重置**手段：终端随后以初始工作目录重新开始。
    """
    if not _shell_enabled():
        raise RuntimeError("execute_shell 已被禁用（GREEN_TRACKER_ENABLE_SHELL=false）")

    if not terminal.supported():
        ShellSessionManager.reset()
        return {"restarted": True, "backend": "subprocess",
                "message": "已重置命令上下文"}

    terminal.get_terminal().reset()
    logger.warning("[terminal_reset] 终端已重启")
    return {"restarted": True, "backend": "pty", "message": "终端已重启，状态已清空"}


@CommandHandler.register("terminal_interrupt", visibility=VISIBILITY_EXTENSION, enabled=True,
                         description="向终端前台发 Ctrl+C —— 拓展指令")
def cmd_terminal_interrupt(params: dict) -> dict:
    """
    向终端前台进程发送 Ctrl+C —— 中断当前正在运行的命令。

    用于挽回被挂起的命令：只中断命令，终端本身保留，可继续使用。
    """
    if not terminal.supported():
        return {"interrupted": False, "message": "当前平台无 PTY 终端，无需中断"}

    interrupted = terminal.get_terminal().interrupt()
    logger.warning("[terminal_interrupt] interrupted=%s", interrupted)
    return {
        "interrupted": interrupted,
        "message": "已发送 Ctrl+C" if interrupted else "终端未在运行",
    }


@CommandHandler.register("terminal_info", visibility=VISIBILITY_EXTENSION, enabled=True,
                         description="查询远程终端状态 —— 拓展指令")
def cmd_terminal_info(params: dict) -> dict:
    """查看终端状态：shell 路径、进程号、窗口尺寸、当前目录、是否存活。"""
    if not terminal.supported():
        return {"tty": False, "backend": "subprocess", "alive": False}
    return terminal.get_terminal().info()


# ============================================================
# 权限撤销（系统指令）
# ============================================================

@CommandHandler.register("revoke_control", visibility=VISIBILITY_PUBLIC, enabled=True,
                         description="系统指令 —— 公有指令，云端撤销控制权限（不可禁用）")
def cmd_revoke_control(params: dict) -> dict:
    """
    系统指令：云端在密钥被删除 / 禁用 / 去掉控制权限时下发。

    设备必须：
      1. 立即置「不可受控」，拒绝后续控制指令（仅保留 `ping` 等连接命令）
      2. 立即重新调用 heartbeat，按新的 capabilities 恢复或继续保持关闭
    """
    reason = params.get("reason") or "云端已撤销本设备的控制权限"
    state = get_cloud_state()
    state.mark_revoked(reason)

    service = _heartbeat.get_heartbeat_service()
    if service is not None and service.is_running:
        service.trigger_immediate()
    else:
        logger.warning("签到服务未运行，无法立即重新签到（下次周期签到时恢复）")

    return {
        "message": "已停止接受控制指令，正在重新签到",
        "reason": reason,
        "revoked": True,
    }


# ============================================================
# 辅助
# ============================================================

def __get_device_id() -> str:
    import os

    return os.getenv("MQTT_DEVICE_ID", "unknown_device")
