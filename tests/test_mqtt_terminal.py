"""mqtt.terminal — PTY 真终端测试。

验证的是「真实终端」语义，而不仅是「结果正确」：
同一个常驻 shell 进程、`isatty()` 为真、shell 函数 / umask / cd / 环境变量
等状态跨命令真实保留、挂起命令可被中断且终端能恢复、shell 退出后自动重启。

非 POSIX 平台没有 pty 模块，整体跳过。
"""
import os

import pytest

from mqtt import commands
from mqtt import terminal as terminal_mod
from mqtt.commands import CommandHandler

pytestmark = pytest.mark.skipif(not hasattr(os, "openpty"), reason="需要 POSIX pty")


@pytest.fixture
def term():
    """每个用例独享一个终端实例，避免相互污染。"""
    t = terminal_mod.Terminal()
    t.start()
    yield t
    t.close()


class TestRealTerminal:
    """Terminal 类：常驻 shell + 伪终端。"""

    @staticmethod
    def _run(term, command, timeout=10):
        """执行并返回 (stdout, exit_code)。"""
        res = term.run(command, timeout=timeout)
        return res["stdout"], res["exit_code"]

    def test_is_a_real_tty(self, term):
        """程序看到的是真终端 —— 状态外部化方案下 isatty() 为假。"""
        out, _ = self._run(term, "test -t 1 && echo TTY || echo NOT_TTY")
        assert out.strip() == "TTY"

    def test_shell_reports_terminal_size(self, term):
        """窗口尺寸已设定，依赖 COLUMNS/LINES 的程序行为与本地终端一致。"""
        term.resize(rows=40, cols=120)
        out, _ = self._run(term, "stty size")
        assert out.strip() == "40 120"

    def test_cd_then_ls_lists_new_directory(self, term, tmp_path):
        (tmp_path / "marker.txt").write_text("x")
        self._run(term, f"cd {tmp_path}")
        out, _ = self._run(term, "ls")
        assert out.strip() == "marker.txt"

    def test_shell_function_persists(self, term):
        """shell 函数是状态外部化方案无法保留的状态。"""
        self._run(term, "gtfn() { echo from-fn; }")
        out, code = self._run(term, "gtfn")
        assert out.strip() == "from-fn"
        assert code == 0

    def test_umask_persists(self, term):
        self._run(term, "umask 077")
        out, _ = self._run(term, "umask")
        assert out.strip() == "0077"

    def test_exported_var_persists(self, term):
        self._run(term, "export GT_TERM=kept")
        out, _ = self._run(term, "echo $GT_TERM")
        assert out.strip() == "kept"

    def test_alias_persists(self, term):
        self._run(term, "alias gtalias='echo aliased'")
        out, _ = self._run(term, "gtalias")
        assert "aliased" in out

    def test_exit_code_is_reported(self, term):
        _, code = self._run(term, "false")
        assert code == 1

    def test_dollar_question_not_polluted_by_probe(self, term):
        """哨兵不得污染 $? —— `false` 之后的 `echo $?` 必须是 1。"""
        self._run(term, "false")
        out, _ = self._run(term, "echo $?")
        assert out.strip() == "1"

    def test_output_has_no_ansi_escapes(self, term):
        """回传的是干净文本：不含终端控制序列与提示符噪音。"""
        out, _ = self._run(term, "echo hello")
        assert "\x1b" not in out
        assert "hello" in out

    def test_hanging_command_is_interrupted(self, term):
        """挂起命令在超时后被 Ctrl+C 中断，而非永久卡死。"""
        res = term.run("sleep 30", timeout=1.5)
        assert res["timed_out"] is True
        assert res["exit_code"] in (130, -1)          # 130 = 128+SIGINT

    def test_terminal_recovers_after_interruption(self, term):
        term.run("sleep 30", timeout=1.5)
        out, code = self._run(term, "echo recovered")
        assert "recovered" in out
        assert code == 0

    def test_interactive_command_does_not_kill_terminal(self, term):
        """`cat` 会一直等 stdin —— 中断后终端必须仍可用。"""
        term.run("cat", timeout=1.5)
        out, code = self._run(term, "echo after-cat")
        assert "after-cat" in out
        assert code == 0

    def test_shell_exit_restarts_terminal(self, term):
        """`exit` 会结束 shell；终端必须自动重启而不是永久失效。"""
        self._run(term, "exit")
        out, code = self._run(term, "echo alive", timeout=15)
        assert "alive" in out
        assert code == 0

    def test_reset_discards_state(self, term, tmp_path):
        self._run(term, f"cd {tmp_path}")
        term.reset()
        out, _ = self._run(term, "pwd", timeout=15)
        assert os.path.realpath(out.strip()) != os.path.realpath(str(tmp_path))

    def test_long_output_is_returned(self, term):
        """放大 max_output 后可拿到完整输出（默认上限会截断，见命令层用例）。"""
        res = term.run("seq 1 3000", timeout=20, max_output=100000)
        assert res["stdout"].strip().endswith("3000")
        assert len(res["stdout"]) > 8000

    def test_runs_as_current_user(self, term):
        out, _ = self._run(term, "id -u")
        assert out.strip() == str(os.getuid())


class TestTerminalCommands:
    """命令层：execute_shell / terminal_reset / terminal_interrupt / terminal_info。"""

    @pytest.fixture(autouse=True)
    def _reset_global(self):
        """全局单例终端在用例之间归零，避免状态泄漏。"""
        terminal_mod.get_terminal().reset()
        yield
        terminal_mod.get_terminal().reset()

    @staticmethod
    def _run(command, **params):
        result = CommandHandler.execute("execute_shell", {"command": command, **params})
        assert result["success"] is True, result.get("error")
        return result["result"]

    def test_execute_shell_reports_tty_backend(self):
        body = self._run("echo hi")
        assert body["tty"] is True
        assert body["backend"] == "pty"
        assert "hi" in body["stdout"]

    def test_state_continuity_across_commands(self, tmp_path):
        """云端视角：依次下发的两条命令共享同一终端。"""
        (tmp_path / "marker.txt").write_text("x")
        self._run(f"cd {tmp_path}")
        assert self._run("ls")["stdout"].strip() == "marker.txt"

    def test_reset_parameter_restarts_terminal(self, tmp_path):
        self._run(f"cd {tmp_path}")
        self._run("pwd", reset=True)
        body = self._run("pwd")
        assert os.path.realpath(body["stdout"].strip()) != os.path.realpath(str(tmp_path))

    def test_terminal_reset_command(self):
        body = CommandHandler.execute("terminal_reset")["result"]
        assert body["restarted"] is True

    def test_terminal_interrupt_command(self):
        body = CommandHandler.execute("terminal_interrupt")["result"]
        assert body["interrupted"] is True

    def test_terminal_info_command(self):
        body = CommandHandler.execute("terminal_info")["result"]
        assert body["alive"] is True
        assert body["tty"] is True
        assert body["shell"]
        assert body["rows"] > 0 and body["cols"] > 0

    def test_terminal_resize_command(self):
        body = CommandHandler.execute("terminal_resize", {"rows": 30, "cols": 100})["result"]
        assert body["rows"] == 30
        assert body["cols"] == 100
        assert self._run("stty size")["stdout"].strip() == "30 100"

    def test_timeout_is_capped(self, monkeypatch):
        """超时仍被收敛到上限，避免阻塞 MQTT 网络线程。"""
        captured = {}
        terminal = terminal_mod.get_terminal()
        original = terminal.run

        def spy(command, timeout, max_output):
            captured["timeout"] = timeout
            return original(command, timeout=1.0, max_output=max_output)

        monkeypatch.setattr(terminal, "run", spy)
        self._run("echo hi", timeout=99999)
        assert captured["timeout"] == commands._SHELL_MAX_TIMEOUT

    def test_long_output_is_truncated(self):
        body = self._run("seq 1 20000", max_output=100, timeout=30)
        assert "已截断" in body["stdout"]
        assert len(body["stdout"]) < 20000

    def test_cwd_parameter_changes_directory(self, tmp_path):
        body = self._run("pwd", cwd=str(tmp_path))
        assert os.path.realpath(body["stdout"].strip()) == os.path.realpath(str(tmp_path))
