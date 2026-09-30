"""
远程终端 —— 常驻 shell + 伪终端（PTY）。

与「每条命令开一个子进程、再把状态搬来搬去」的做法不同，这里维护
**一个常驻的交互式 shell 进程**，并通过伪终端与之相连。因此：

* **状态天然连续** —— cd / export / alias / shell 函数 / umask / trap
  全部真实保留，因为自始至终是同一个进程（无需任何状态搬运）；
* **程序看到的是真终端** —— `isatty()` 为真，依赖终端的程序（分页器、
  进度条、交互式解释器、sudo 密码提示）行为与本地终端一致；
* **输出即时可读** —— PTY 是行缓冲，不存在管道块缓冲造成的读取死锁；
* **可以中断** —— 挂起的命令通过写入 Ctrl+C（`\\x03`）由 tty 驱动向前台
  进程组发 SIGINT，无需杀掉整个 shell；shell 退出（`exit`）会被检测到并
  自动重启，不会让终端永久失效。

代价：输出中混有终端控制序列与提示符，需净化后才能回传；且同一时刻
只能串行执行一条命令 —— 但需求本身只要一个终端。
"""
import errno
import logging
import os
import re
import select
import shlex
import signal
import struct
import threading
import time
import uuid

# 以下三个模块只在 POSIX 平台提供。Windows 上导入失败即视为不支持 PTY；
# 注意必须在导入期就降级，否则 import mqtt.terminal 会直接抛 ModuleNotFoundError，
# 连带让整个 MQTT 服务无法启动。
try:
    import fcntl
    import termios
except ImportError:  # pragma: no cover - 平台相关
    fcntl = None    # type: ignore[assignment]
    termios = None  # type: ignore[assignment]

try:  # Windows 没有 pty 模块，导入失败即视为不支持
    import pty
except ImportError:  # pragma: no cover - 平台相关
    pty = None  # type: ignore[assignment]

logger = logging.getLogger(__name__)

# 终端控制序列：CSI / OSC / 字符集切换 / 键盘模式
_ANSI_RE = re.compile(
    r"\x1b\[[0-9;?]*[ -/]*[@-~]"
    r"|\x1b\][^\x07\x1b]*(?:\x07|\x1b\\)"
    r"|\x1b[()][0-9A-Za-z]"
    r"|\x1b[=>]"
)

# 关闭提示符与括号粘贴，避免它们混进回传输出
_QUIET_SETUP = (
    "PS1='';PS2='';unset PROMPT_COMMAND 2>/dev/null;"
    "bind 'set enable-bracketed-paste off' 2>/dev/null;true"
)

# 启动握手：只发**一次**哨兵并一直读到它出现。反复重发会让哨兵在 shell
# 的输入队列里堆积（rc 文件越慢堆积越多），反而把握手拖到几十秒。
_HANDSHAKE_TIMEOUT = 20.0         # 单次就绪探测的读超时（rc 加载可能较慢）
_HANDSHAKE_ATTEMPTS = 3           # 仅在 shell 立即退出时重试
_INTERRUPT_GRACE = 2.0        # Ctrl+C 之后等待哨兵的宽限时间
_INTR = b"\x03"               # Ctrl+C


def supported() -> bool:
    """当前平台能否提供 PTY 真终端。"""
    return (
        pty is not None
        and fcntl is not None
        and termios is not None
        and hasattr(os, "fork")
    )


def default_shell() -> str:
    """登录 shell；语法不兼容 POSIX 的（fish/csh 等）回退到 /bin/sh。"""
    shell = os.environ.get("SHELL") or "/bin/sh"
    if os.path.basename(shell) in {"fish", "csh", "tcsh", "nu", "xonsh", "elvish"}:
        shell = "/bin/sh"
    return shell


def truncate_output(text: object, limit: int, encoding: str = "utf-8") -> str:
    """截断超长输出，避免撑爆 MQTT 报文。"""
    if text is None:
        return ""
    if isinstance(text, bytes):
        text = text.decode(encoding, errors="replace")
    text = str(text)
    if len(text) <= limit:
        return text
    return f"{text[:limit]}...[已截断，共 {len(text)} 字符]"


class Terminal:
    """
    一个常驻 shell 进程 + 伪终端。

    命令边界靠**哨兵**确定：命令写完后补发一行 `printf`，把退出码与当前
    目录以唯一标记回显，读取端据此判定命令结束。哨兵末尾的 `(exit $ec)`
    会把 `$?` 还原为用户命令的退出码，因此哨兵不会污染 `echo $?`。
    """

    def __init__(self, shell: str = None, rows: int = 24, cols: int = 200):
        self.shell = shell or default_shell()
        self.rows = rows
        self.cols = cols
        self._pid = None
        self._fd = None
        self._cwd = os.getcwd()
        self._started_at = None
        self._lock = threading.RLock()

    # -----------------------------------------------------------------
    # 生命周期
    # -----------------------------------------------------------------

    @property
    def alive(self) -> bool:
        """shell 进程是否仍在运行（顺带回收已退出的子进程，避免僵尸）。"""
        if self._fd is None:
            return False
        if self._pid is None:
            return False
        try:
            pid, _status = os.waitpid(self._pid, os.WNOHANG)
        except ChildProcessError:
            return False
        return pid == 0

    def start(self) -> None:
        """启动（或重启）终端并完成握手。"""
        with self._lock:
            self._spawn()
            self._handshake()

    def reset(self) -> bool:
        """销毁并重建终端 —— 丢弃全部累积状态，回到初始工作目录。"""
        with self._lock:
            self._kill()
            self.start()
            self._cwd = os.getcwd()
            return True

    def close(self) -> None:
        with self._lock:
            self._kill()

    def info(self) -> dict:
        return {
            "shell": self.shell,
            "pid": self._pid,
            "alive": self.alive,
            "tty": supported(),
            "backend": "pty" if supported() else "unsupported",
            "rows": self.rows,
            "cols": self.cols,
            "cwd": self._cwd,
            "uptime_seconds": round(time.time() - self._started_at, 1)
            if self._started_at else 0.0,
        }

    # -----------------------------------------------------------------
    # 对外操作
    # -----------------------------------------------------------------

    def run(self, command: str, timeout: float = 30.0, max_output: int = 8000) -> dict:
        """在当前终端中执行一条命令。"""
        with self._lock:
            restarted = False
            if not self.alive:
                self.start()
                restarted = True

            started = time.time()
            text, code, dead, cwd, interrupted = self._exchange(command, timeout)

            if dead:                       # shell 中途退出（如执行了 exit）
                self.start()
                restarted = True

            # 中断成功时 code 为 130（128+SIGINT）；中断也没救回来则为 None
            timed_out = interrupted or code is None
            exit_code = -1 if code is None else code
            if cwd:
                self._cwd = cwd

            duration = round(time.time() - started, 3)
            return {
                "command": command,
                "exit_code": exit_code,
                "stdout": truncate_output(
                    self._clean(text[0], text[1]), max_output),
                "stderr": "",              # PTY 下 stdout/stderr 本就合并（真终端语义）
                "ok": exit_code == 0 and not timed_out,
                "timed_out": timed_out,
                "duration": duration,
                "cwd": self._cwd,
                "shell": self.shell,
                "tty": True,
                "backend": "pty",
                "restarted": restarted,
            }

    def interrupt(self) -> bool:
        """向前台进程组发送 Ctrl+C（等价用户在终端按下）。"""
        with self._lock:
            return self._send_intr()

    def resize(self, rows: int, cols: int) -> bool:
        with self._lock:
            self.rows, self.cols = int(rows), int(cols)
            return self._apply_size()

    def cd(self, path: str) -> None:
        """把终端切换到指定目录（供 cwd 参数使用）。"""
        with self._lock:
            if not self.alive:
                self.start()
            self._exchange(f"cd {shlex.quote(path)}", timeout=10)

    # -----------------------------------------------------------------
    # 内部：进程与终端属性
    # -----------------------------------------------------------------

    def _spawn(self) -> None:
        if not supported():
            raise RuntimeError("当前平台不支持 PTY（需要 POSIX pty）")

        self._kill()
        pid, fd = pty.fork()
        if pid == 0:                                   # 子进程
            try:
                os.environ.setdefault("TERM", "xterm")
                os.execvp(self.shell, [self.shell, "-i"])
            except Exception:                          # pragma: no cover
                os._exit(1)
            os._exit(1)                                # pragma: no cover

        self._pid, self._fd = pid, fd
        self._started_at = time.time()
        self._apply_termios()
        self._apply_size()

    def _apply_termios(self) -> None:
        """关闭回显：否则写入的命令会被 tty 原样回显，混入输出。"""
        try:
            attrs = termios.tcgetattr(self._fd)
        except (termios.error, ValueError):            # pragma: no cover
            return
        attrs[3] &= ~termios.ECHO
        try:
            termios.tcsetattr(self._fd, termios.TCSANOW, attrs)
        except (termios.error, OSError):               # pragma: no cover
            pass

    def _apply_size(self) -> bool:
        if self._fd is None:
            return False
        try:
            fcntl.ioctl(
                self._fd, termios.TIOCSWINSZ,
                struct.pack("HHHH", self.rows, self.cols, 0, 0),
            )
            return True
        except OSError:                                # pragma: no cover
            return False

    def _kill(self) -> None:
        if self._pid is not None:
            try:
                os.kill(self._pid, signal.SIGKILL)
            except OSError:
                pass
            try:
                os.waitpid(self._pid, 0)
            except (ChildProcessError, OSError):
                pass
            self._pid = None
        if self._fd is not None:
            try:
                os.close(self._fd)
            except OSError:
                pass
            self._fd = None

    # -----------------------------------------------------------------
    # 内部：读写与哨兵
    # -----------------------------------------------------------------

    def _write(self, data: bytes) -> None:
        if self._fd is None:
            raise RuntimeError("终端未启动")
        os.write(self._fd, data)

    def _send_intr(self) -> bool:
        try:
            self._write(_INTR)
            return True
        except (OSError, RuntimeError):
            return False

    def _handshake(self) -> None:
        """等待 shell 就绪 —— 其 rc 文件（conda/nvm 等）可能加载数秒。

        只发一次哨兵并读到它出现；握手期间**不**发 Ctrl+C，否则会打断
        正在加载的 rc。仅当 shell 立即退出时才重建重试。
        """
        for attempt in range(_HANDSHAKE_ATTEMPTS):
            started = time.time()
            _, code, dead, _, _ = self._exchange(
                "", _HANDSHAKE_TIMEOUT, interrupt_on_timeout=False)
            elapsed = time.time() - started
            logger.debug("[terminal] 握手 attempt=%s code=%s 耗时=%.2fs",
                         attempt, code, elapsed)
            if elapsed > 3:
                logger.warning("[terminal] shell 就绪耗时 %.1fs（rc 文件加载较慢）", elapsed)
            if code is not None:
                break
            if dead:
                logger.warning("[terminal] shell 启动即退出，重建重试")
                self._spawn()
            # 未就绪且未退出：继续等（哨兵只此一个，不会堆积）
        else:                                          # pragma: no cover
            raise RuntimeError(f"终端启动失败：{self.shell} 未就绪")

        self._exchange(_QUIET_SETUP, _HANDSHAKE_TIMEOUT, interrupt_on_timeout=False)

    def _exchange(self, command: str, timeout: float, interrupt_on_timeout: bool = True):
        """写命令 + 哨兵，读回 (输出, 退出码, shell 是否死亡, cwd, 是否超时中断)。"""
        marker = f"__GT_{uuid.uuid4().hex}"
        if command:
            self._write(command.encode() + b"\n")
        sentinel = (
            f"__gt_ec=$?;printf '\\n%s_%d__\\n' {marker} \"$__gt_ec\";"
            f"printf '%s_PWD__%s__\\n' {marker} \"$(pwd)\";"
            f"(exit $__gt_ec)\n"
        ).encode()
        self._write(sentinel)

        text, dead = self._read_until(marker, timeout)
        code, cwd = self._parse(text, marker)

        interrupted = False
        if code is None and not dead and interrupt_on_timeout:
            # 命令卡住了：Ctrl+C 中断。注意 INTR 会冲刷输入队列，
            # 之前排队的哨兵已被丢弃，必须补发一次。
            interrupted = True
            self._send_intr()
            time.sleep(0.4)
            self._write(sentinel)
            extra, dead = self._read_until(marker, _INTERRUPT_GRACE)
            text += extra
            code, cwd = self._parse(text, marker)

        return (text, marker), code, dead, cwd, interrupted

    def _read_until(self, marker: str, timeout: float):
        """读输出直到出现哨兵标记。

        Returns:
            (文本, shell 是否已退出)
        """
        chunks = []
        pending = ""
        deadline = time.monotonic() + timeout
        # 必须等哨兵**完整**输出（含 PWD 行）才返回：只读到退出码行就返回的话，
        # PWD 行会残留在 pty 缓冲里，污染下一条命令的输出。
        needle = f"{marker}_PWD__"
        # 窗口要能装下 marker + 一整行 PWD（路径可能很长），否则会漏检
        keep = len(needle) + 4096

        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                return "".join(chunks), False
            try:
                ready, _, _ = select.select([self._fd], [], [], min(remaining, 0.2))
            except (OSError, ValueError):
                return "".join(chunks), True
            if not ready:
                continue
            try:
                chunk = os.read(self._fd, 65536)
            except OSError as exc:
                if exc.errno in (errno.EIO, errno.EBADF):
                    return "".join(chunks), True      # pty 关闭 = shell 退出
                raise                                  # pragma: no cover
            if not chunk:
                return "".join(chunks), True
            chunk = chunk.decode("utf-8", errors="replace")
            chunks.append(chunk)
            pending = (pending + chunk)[-keep:]
            if needle in pending:
                return "".join(chunks), False

    @staticmethod
    def _parse(text: str, marker: str):
        """从哨兵输出中提取退出码与当前目录。"""
        code_match = re.search(re.escape(marker) + r"_(-?\d+)__", text)
        pwd_match = re.search(re.escape(marker) + r"_PWD__(.*)__", text)
        code = int(code_match.group(1)) if code_match else None
        cwd = pwd_match.group(1) if pwd_match else None
        return code, cwd

    @staticmethod
    def _clean(text: str, marker: str) -> str:
        """净化输出：去掉哨兵行、终端控制序列与回车。"""
        lines = [line for line in text.split("\n") if marker not in line]
        cleaned = _ANSI_RE.sub("", "\n".join(lines))
        return cleaned.replace("\r\n", "\n").replace("\r", "").strip("\n")


# ---------------------------------------------------------------------------
# 进程内共享的单终端
# ---------------------------------------------------------------------------

_terminal: "Terminal" = None
_terminal_lock = threading.Lock()


def get_terminal() -> Terminal:
    """获取进程内共享的终端实例（惰性创建，真正启动推迟到首次执行）。"""
    global _terminal
    with _terminal_lock:
        if _terminal is None:
            _terminal = Terminal()
        return _terminal
