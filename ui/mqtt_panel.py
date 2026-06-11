#!/usr/bin/env python3
"""
MQTT 远程控制调试面板。

功能：
  - 实时连接状态指示
  - 心跳/状态上报日志
  - 命令收发历史
  - 手动发送测试命令（本地/远程）
  - 设备信息展示
  - 已注册命令列表

模块化设计：可作为独立 QWidget 嵌入任何 QStackedWidget / QDockWidget。
"""

import json
from datetime import datetime

from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QTextEdit, QLineEdit, QComboBox, QGroupBox, QScrollArea,
    QSplitter, QFrame, QListWidgetItem, QListWidget,
)
from PyQt6.QtCore import Qt, QTimer
from PyQt6.QtGui import QFont, QColor

from mqtt.manager import MQTTService


# ============================================================
# 样式常量
# ============================================================

C = {
    "bg": "#FAFAFA",
    "card": "#FFFFFF",
    "text": "#2D2D2D",
    "text_sub": "#757575",
    "border": "#BDBDBD",
    "accent": "#4A90A4",
    "accent_hover": "#3D7A8C",
    "success": "#66BB6A",
    "danger": "#EF5350",
    "warning": "#FFA726",
    "muted": "#E0E0E0",
    "log_bg": "#1E1E1E",
    "log_text": "#D4D4D4",
}

STYLES = {
    "panel": f"""
        QWidget#MqttPanel {{ background-color: {C['bg']}; }}
        QLabel {{ color: {C['text']}; font-size: 13px; }}
        QGroupBox {{
            font-size: 13px;
            font-weight: 600;
            color: {C['text']};
            border: 1px solid {C['border']};
            border-radius: 6px;
            margin-top: 8px;
            padding-top: 16px;
        }}
        QGroupBox::title {{
            subcontrol-origin: margin;
            left: 12px;
            padding: 0 6px;
        }}
        QPushButton {{
            font-size: 13px;
            font-weight: 500;
            padding: 6px 16px;
            border-radius: 4px;
            border: 1px solid {C['border']};
        }}
        QLineEdit, QComboBox {{
            font-size: 13px;
            padding: 6px 10px;
            border: 1px solid {C['border']};
            border-radius: 4px;
            background-color: {C['card']};
        }}
        QTextEdit, QListWidget {{
            font-family: 'JetBrains Mono', 'Consolas', 'Monospace';
            font-size: 12px;
            border: 1px solid {C['border']};
            border-radius: 4px;
            background-color: {C['card']};
        }}
    """,
}


# ============================================================
# 状态徽章组件
# ============================================================

class StatusBadge(QLabel):
    """连接状态圆角徽章。"""

    def __init__(self):
        super().__init__("未连接")
        self.setFixedSize(90, 26)
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._set_disconnected()

    def _set_connected(self):
        self.setText("● 已连接")
        self.setStyleSheet(
            f"background-color: {C['success']}; color: white; "
            f"font-weight: 600;"
        )

    def _set_connecting(self):
        self.setText("○ 连接中...")
        self.setStyleSheet(
            f"background-color: {C['warning']}; color: white; "
            f"font-weight: 600;"
        )

    def _set_disconnected(self):
        self.setText("✕ 未连接")
        self.setStyleSheet(
            f"background-color: {C['muted']}; color: {C['text']}; "
            f"font-weight: 600;"
        )

    def update_status(self, connected: bool):
        if connected:
            self._set_connected()
        else:
            self._set_disconnected()


# ============================================================
# 日志查看器（带自动滚动 + 着色）
# ============================================================

class LogViewer(QTextEdit):
    """终端风格的日志输出区。"""

    MAX_LINES = 2000

    def __init__(self):
        super().__init__()
        self.setReadOnly(True)
        self.setMinimumHeight(120)
        self.setStyleSheet(f"""
            QTextEdit {{
                background-color: {C['log_bg']};
                color: {C['log_text']};
                border: 1px solid #333333;
                border-radius: 4px;
                font-family: 'JetBrains Mono', 'Consolas', monospace;
                font-size: 12px;
            }}
        """)
        self._line_count = 0

    def append_log(self, level: str, message: str):
        """追加一条日志，带时间戳和级别着色。"""
        ts = datetime.now().strftime("%H:%M:%S")

        color_map = {
            "INFO": "#4EC9B0",
            "ERROR": "#F44747",
            "WARN": "#DCDCAA",
            "WARNING": "#DCDCAA",
            "DEBUG": "#9CDCFE",
            "CMD_IN": "#CE9178",   # 收到命令
            "CMD_OUT": "#569CD6",  # 发出响应
            "STATUS": "#DCA600",   # 状态上报
            "SYSTEM": "#C586C0",   # 系统消息
        }
        color = color_map.get(level.upper(), C["log_text"])

        formatted = (
            f'<span style="color:#888888;">[{ts}]</span> '
            f'<span style="color:{color}; font-weight:bold;">'
            f'[{level}]</span> '
            f'{message}'
        )
        self.append(formatted)
        self._line_count += 1

        # 自动滚动到底部
        sb = self.verticalScrollBar()
        sb.setValue(sb.maximum())

        # 超过上限时清理
        if self._line_count > self.MAX_LINES:
            cursor = self.textCursor()
            cursor.movePosition(cursor.MoveOperation.Start)
            cursor.movePosition(cursor.MoveOperation.Down, cursor.MoveMode.KeepAnchor, int(self.MAX_LINES * 0.5))
            cursor.removeSelectedText()
            self._line_count = int(self.MAX_LINES * 0.5)

    def clear_log(self):
        self.clear()
        self._line_count = 0


# ============================================================
# 主面板
# ============================================================

class MqttPanel(QWidget):
    """
    MQTT 远程控制调试面板。

    使用方式：
        panel = MqttPanel()           # 自动绑定全局 MQTTService
        stack.addWidget(panel)         # 或放入任意布局
    """

    objectName = "MqttPanel"

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("MqttPanel")
        self.service = MQTTService.get_instance()

        self._init_ui()
        self._connect_signals()

        # 定时器：定期刷新命令列表和设备信息
        self._refresh_timer = QTimer(self)
        self._refresh_timer.timeout.connect(self._refresh_info)
        self._refresh_timer.start(10000)

        # 定时器：定期轮询连接状态（解决无网络→有网络后状态不同步的问题）
        self._status_poll_timer = QTimer(self)
        self._status_poll_timer.timeout.connect(self._poll_connection_status)
        self._status_poll_timer.start(3000)  # 每3秒轮询一次

        # 同步当前连接状态（面板可能晚于信号创建，需要补偿初始状态）
        self._sync_initial_state()

        # 延迟刷新命令列表，确保 QComboBox 完全初始化
        QTimer.singleShot(100, self._refresh_commands)

    # -----------------------------------------------------------------
    # UI 构建
    # -----------------------------------------------------------------

    def _init_ui(self):
        self.setStyleSheet(STYLES["panel"])

        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(16, 16, 16, 16)
        main_layout.setSpacing(12)

        # ===== 顶部工具栏 =====
        toolbar = QHBoxLayout()

        # 标题（左侧，与其他页面一致）
        title_label = QLabel("MQTT 控制台")
        title_label.setStyleSheet(f"font-size: 20px; font-weight: 600; color: {C['text']};")
        toolbar.addWidget(title_label)

        toolbar.addStretch()

        # 状态徽章（右侧）
        self.status_badge = StatusBadge()
        toolbar.addWidget(self.status_badge)

        # 启动/停止按钮
        self.btn_toggle = QPushButton("启动 MQTT")
        self.btn_toggle.setFixedHeight(36)
        self.btn_toggle.setMinimumWidth(110)
        self.btn_toggle.setStyleSheet(f"""
            QPushButton {{
                font-size: 14px;
                padding: 8px 16px;
                background-color: {C['accent']};
                color: white;
                border: 2px solid {C['border']};
                border-radius: 4px;
            }}
            QPushButton:hover {{ background-color: {C['accent_hover']}; }}
        """)
        self.btn_toggle.clicked.connect(self._on_toggle_clicked)
        toolbar.addWidget(self.btn_toggle)

        # 返回按钮（最右侧，与其他页面位置统一）
        btn_back = QPushButton("← 返回")
        btn_back.setFixedHeight(36)
        btn_back.setMinimumWidth(90)
        btn_back.setStyleSheet("""
            QPushButton {
                font-size: 14px;
                padding: 8px 16px;
                background-color: #757575;
                color: white;
                border: 2px solid #BDBDBD;
                border-radius: 4px;
            }
            QPushButton:hover { background-color: #616161; }
        """)
        btn_back.clicked.connect(self._go_back)
        toolbar.addWidget(btn_back)

        main_layout.addLayout(toolbar)

        # ===== 分割布局 =====
        splitter = QSplitter(Qt.Orientation.Vertical)

        # --- 上部：状态 + 命令 ---
        top_widget = QWidget()
        top_layout = QHBoxLayout(top_widget)
        top_layout.setContentsMargins(0, 0, 0, 0)
        top_layout.setSpacing(12)

        # 左侧：设备信息 + 命令列表
        left_panel = QWidget()
        left_layout = QVBoxLayout(left_panel)
        left_layout.setContentsMargins(0, 0, 0, 0)

        # 客户端信息组
        info_group = QGroupBox("客户端信息")
        info_layout = QVBoxLayout(info_group)
        self.info_labels: dict[str, QLabel] = {}
        for key, label_text in [
            ("device_id", "设备 ID"),
            ("broker", "Broker"),
            ("client_id", "客户端 ID"),
            ("ip", "本地 IP"),
            ("uptime", "运行时长"),
        ]:
            row = QHBoxLayout()
            name_lbl = QLabel(f"{label_text}:")
            name_lbl.setStyleSheet(f"color: {C['text_sub']}; min-width: 70px;")
            val_lbl = QLabel("--")
            val_lbl.setTextFormat(Qt.TextFormat.PlainText)
            val_lbl.setStyleSheet(f"""
                color: {C['text']}; font-weight: 500;
                background-color: transparent;
            """)
            val_lbl.setSizePolicy(
                val_lbl.sizePolicy().Policy.Expanding,
                val_lbl.sizePolicy().Policy.Preferred
            )
            row.addWidget(name_lbl)
            row.addWidget(val_lbl, 1)
            info_layout.addLayout(row)
            self.info_labels[key] = val_lbl
        info_layout.addStretch()
        left_layout.addWidget(info_group, 1)

        # 已注册命令列表
        cmd_group = QGroupBox("已注册命令")
        cmd_layout = QVBoxLayout(cmd_group)
        self.cmd_list = QListWidget()
        self.cmd_list.setMaximumHeight(140)
        cmd_layout.addWidget(self.cmd_list)
        left_layout.addWidget(cmd_group, 1)

        top_layout.addWidget(left_panel, 1)

        # 右侧：手动命令发送
        right_panel = QWidget()
        right_layout = QVBoxLayout(right_panel)
        right_layout.setContentsMargins(0, 0, 0, 0)

        send_group = QGroupBox("命令调试")
        send_layout = QVBoxLayout(send_group)

        # 命令选择
        sel_row = QHBoxLayout()
        sel_row.addWidget(QLabel("命令:"))
        self.combo_command = QComboBox()
        self.combo_command.setEditable(True)
        self.combo_command.setPlaceholderText("输入或选择命令...")
        sel_row.addWidget(self.combo_command)
        send_layout.addLayout(sel_row)

        # 参数输入
        param_row = QHBoxLayout()
        param_row.addWidget(QLabel("参数 (JSON):"))
        self.input_params = QLineEdit()
        self.input_params.setPlaceholderText('{"key":"value"} (可选)')
        param_row.addWidget(self.input_params)
        send_layout.addLayout(param_row)

        # 执行模式 & 按钮
        btn_row = QHBoxLayout()
        btn_local = QPushButton("本地执行")
        btn_local.setFixedHeight(36)
        btn_local.setMinimumWidth(90)
        btn_local.setStyleSheet(f"""
            QPushButton {{
                font-size: 14px;
                padding: 8px 16px;
                background-color: {C['card']};
                color: {C['text']};
                border: 2px solid {C['border']};
                border-radius: 4px;
            }}
            QPushButton:hover {{ background-color: {C['bg']}; border-color: {C['accent']}; }}
        """)
        btn_local.clicked.connect(self._on_send_local)
        btn_row.addWidget(btn_local)

        btn_remote = QPushButton("远程发送")
        btn_remote.setFixedHeight(36)
        btn_remote.setMinimumWidth(90)
        btn_remote.setStyleSheet(f"""
            QPushButton {{
                font-size: 14px;
                padding: 8px 16px;
                background-color: {C['accent']};
                color: white;
                border: 2px solid {C['border']};
                border-radius: 4px;
            }}
            QPushButton:hover {{ background-color: {C['accent_hover']}; }}
        """)
        btn_remote.clicked.connect(self._on_send_remote)
        btn_row.addWidget(btn_remote)

        btn_refresh = QPushButton("刷新")
        btn_refresh.setFixedHeight(36)
        btn_refresh.setMinimumWidth(90)
        btn_refresh.setStyleSheet(f"""
            QPushButton {{
                font-size: 14px;
                padding: 8px 16px;
                background-color: {C['card']};
                color: {C['text']};
                border: 2px solid {C['border']};
                border-radius: 4px;
            }}
            QPushButton:hover {{ background-color: {C['bg']}; border-color: {C['accent']}; }}
        """)
        btn_refresh.clicked.connect(self._refresh_commands)
        btn_row.addWidget(btn_refresh)
        btn_row.addStretch()
        send_layout.addLayout(btn_row)

        # 结果显示
        result_label = QLabel("执行结果:")
        result_label.setStyleSheet(f"margin-top: 8px;")
        send_layout.addWidget(result_label)
        self.result_view = QTextEdit()
        self.result_view.setMaximumHeight(120)
        self.result_view.setReadOnly(True)
        self.result_view.setStyleSheet(f"""
            QTextEdit {{
                background-color: {C['log_bg']};
                color: {C['log_text']};
                font-family: monospace;
                font-size: 12px;
            }}
        """)
        send_layout.addWidget(self.result_view)

        right_layout.addWidget(send_group, 1)
        top_layout.addWidget(right_panel, 1)

        splitter.addWidget(top_widget)

        # --- 下部：日志查看器 ---
        log_group = QGroupBox("消息日志")
        log_outer = QVBoxLayout(log_group)
        self.log_viewer = LogViewer()
        log_outer.addWidget(self.log_viewer)

        log_toolbar = QHBoxLayout()
        btn_clear_log = QPushButton("清空日志")
        btn_clear_log.setFixedHeight(32)
        btn_clear_log.setMinimumWidth(90)
        btn_clear_log.setStyleSheet(f"""
            QPushButton {{
                font-size: 13px;
                padding: 6px 14px;
                background-color: {C['card']};
                color: {C['text']};
                border: 2px solid {C['border']};
                border-radius: 4px;
            }}
            QPushButton:hover {{ background-color: {C['bg']}; border-color: {C['accent']}; }}
        """)
        btn_clear_log.clicked.connect(lambda: self.log_viewer.clear_log())
        log_toolbar.addWidget(btn_clear_log)
        log_toolbar.addStretch()
        log_outer.addLayout(log_toolbar)

        splitter.addWidget(log_group)

        # 分割比例
        splitter.setSizes([300, 250])

        main_layout.addWidget(splitter, 1)

        # 初始化按钮状态
        self._update_toggle_button()

    # -----------------------------------------------------------------
    # 信号连接
    # -----------------------------------------------------------------

    def _connect_signals(self):
        sigs = self.service.signals

        sigs.connected.connect(self._on_connected)
        sigs.disconnected.connect(self._on_disconnected)
        sigs.connection_failed.connect(self._on_connection_failed)
        sigs.ready.connect(self._on_ready)
        sigs.status_published.connect(self._on_status_published)
        sigs.command_received.connect(self._on_command_received)
        sigs.response_sent.connect(self._on_response_sent)
        sigs.log_message.connect(self._on_log_message)

    # -----------------------------------------------------------------
    # 事件处理
    # -----------------------------------------------------------------

    def _on_connected(self, broker_addr: str):
        self.log_viewer.append_log("SYSTEM", f"已连接至 Broker: <b>{broker_addr}</b>")
        self.status_badge.update_status(True)
        self.info_labels["broker"].setText(broker_addr)
        self._update_toggle_button()

    def _on_disconnected(self, reason: str):
        self.log_viewer.append_log("WARN", f"连接断开: {reason}")
        self.status_badge.update_status(False)
        self._update_toggle_button()

    def _on_connection_failed(self, error: str):
        self.log_viewer.append_log("ERROR", f"连接失败: {error}")
        self.status_badge.update_status(False)
        self._update_toggle_button()

    def _on_ready(self):
        self._refresh_info()
        self.log_viewer.append_log("SYSTEM", "MQTT 服务就绪")

    def _on_status_published(self, status_dict: dict):
        status = status_dict.get("status", "?")
        ts = status_dict.get("timestamp", "")[:19]
        ip = status_dict.get("ip", "")
        self.info_labels["ip"].setText(ip)
        self.log_viewer.append_log("STATUS", f"[{status}] ip={ip} time={ts}")

    def _on_command_received(self, cmd_msg: dict):
        command = cmd_msg.get("command", "?")
        params = cmd_msg.get("params", {})
        cmd_id = cmd_msg.get("command_id", "?")
        source = cmd_msg.get("_source", "remote")
        source_tag = "[本地]" if source == "local" else "[远程]"

        self.log_viewer.append_log(
            "CMD_IN",
            f"{source_tag} <b>{command}</b>(id={cmd_id}) "
            f'params={json.dumps(params, ensure_ascii=False)}'
        )

    def _on_response_sent(self, resp: dict):
        success = resp.get("success", False)
        command = resp.get("command", "?")
        error = resp.get("error", "")
        icon = "+" if success else "-"
        detail = "ok" if success else f"err={error}"
        self.log_viewer.append_log("CMD_OUT", f"{icon} 响应: <b>{command}</b> -> {detail}")

    def _on_log_message(self, level: str, msg: str):
        self.log_viewer.append_log(level, msg)

    # -----------------------------------------------------------------
    # 用户操作
    # -----------------------------------------------------------------

    def _go_back(self):
        """返回主页。"""
        main_window = self.window()
        if hasattr(main_window, 'show_home_page'):
            main_window.show_home_page()

    def _on_toggle_clicked(self):
        """启动/停止按钮点击。"""
        if self.service.is_running:
            self.service.stop()
        else:
            self.service.start()
        self._update_toggle_button()

    def _update_toggle_button(self):
        """更新启停按钮状态。"""
        running = self.service.is_running
        self.btn_toggle.setText("停止 MQTT" if running else "启动 MQTT")
        if running:
            self.btn_toggle.setStyleSheet(f"""
                QPushButton {{
                    font-size: 14px;
                    padding: 8px 16px;
                    background-color: {C['danger']};
                    color: white;
                    border: 2px solid {C['border']};
                    border-radius: 4px;
                }}
                QPushButton:hover {{ background-color: #D32F2F; }}
            """)
        else:
            self.btn_toggle.setStyleSheet(f"""
                QPushButton {{
                    font-size: 14px;
                    padding: 8px 16px;
                    background-color: {C['accent']};
                    color: white;
                    border: 2px solid {C['border']};
                    border-radius: 4px;
                }}
                QPushButton:hover {{ background-color: {C['accent_hover']}; }}
            """)

    def _on_send_local(self):
        """本地执行命令（不经过 Broker）。"""
        cmd = self.combo_command.currentText().strip()
        if not cmd:
            return

        params_str = self.input_params.text().strip()
        params = {}
        if params_str:
            try:
                params = json.loads(params_str)
            except json.JSONDecodeError as e:
                self._show_result(False, {}, f"JSON 解析错误: {e}")
                return

        result = self.service.send_command_to_self(cmd, params)
        self._show_result(result.get("success", False), result.get("result"), result.get("error"))

    def _on_send_remote(self):
        """通过 Broker 发送命令到自己的 command topic（模拟云端下发）。"""
        if not self.service.client or not self.service.is_connected:
            self._show_result(False, None, "MQTT 未连接，无法发送远程命令")
            return

        cmd = self.combo_command.currentText().strip()
        if not cmd:
            return

        params_str = self.input_params.text().strip()
        params = {}
        if params_str:
            try:
                params = json.loads(params_str)
            except json.JSONDecodeError as e:
                self._show_result(False, None, f"JSON 解析错误: {e}")
                return

        import time as _time
        payload = {
            "command_id": f"manual_{int(_time.time())}",
            "command": cmd,
            "params": params,
        }

        client = self.service.client
        from mqtt.topics import command_topic
        import paho.mqtt.client as mqtt_mod

        topic = command_topic(client.device_id)
        pub_result = client._client.publish(topic, json.dumps(payload), qos=1)

        if pub_result.rc == mqtt_mod.MQTT_ERR_SUCCESS:
            self._show_result(True, {"topic": topic}, "命令已发布到 Broker")
            self.log_viewer.append_log(
                "CMD_OUT",
                f"-> 远程发布: <b>{cmd}</b> -> {topic}"
            )
        else:
            self._show_result(False, None, f"发布失败: rc={pub_result.rc}")

    def _show_result(self, success: bool, result, error: str = ""):
        """在结果区域显示执行结果。"""
        text = json.dumps(
            {"success": success, "result": result, "error": error},
            ensure_ascii=False,
            indent=2,
        )
        self.result_view.setPlainText(text)

    # -----------------------------------------------------------------
    # 刷新辅助
    # -----------------------------------------------------------------

    def _refresh_commands(self):
        """刷新已注册命令列表。"""
        commands = self.service.list_available_commands()

        # 保存用户输入
        current = self.combo_command.currentText().strip() if self.combo_command.count() > 0 else ""

        # 完全重建（比 clear+addItems 更可靠）
        self.combo_command.blockSignals(True)
        try:
            # 移除所有项
            while self.combo_command.count() > 0:
                self.combo_command.removeItem(0)
            for cmd in commands:
                self.combo_command.addItem(cmd)

            # 恢复用户输入（仅当输入不在选项中时才设置）
            if current and not any(self.combo_command.itemText(i) == current for i in range(self.combo_command.count())):
                self.combo_command.setEditText(current)
            elif current:
                idx = self.combo_command.findText(current)
                if idx >= 0:
                    self.combo_command.setCurrentIndex(idx)
                else:
                    self.combo_command.setEditText(current)
        finally:
            self.combo_command.blockSignals(False)

        # 刷新左侧命令列表
        self.cmd_list.clear()
        for cmd_name in commands:
            item = QListWidgetItem(cmd_name)
            item.setForeground(QColor(C["accent"]))
            self.cmd_list.addItem(item)

    def _refresh_info(self):
        """刷新设备信息显示。"""
        svc = self.service
        client = svc.client

        if client:
            self._set_info("device_id", client.device_id)
            self._set_info("broker", f"{client.broker_host}:{client.broker_port}")
            self._set_info("client_id", client.client_id)

            import time as _time
            from mqtt.commands import _start_time
            uptime_sec = int(_time.time() - _start_time)
            mins, secs = divmod(uptime_sec, 60)
            hours, mins = divmod(mins, 60)
            self._set_info("uptime", f"{hours}h{mins:02d}m{secs:02d}s")

    def _sync_initial_state(self):
        """面板创建时同步 MQTT 当前状态（补偿信号时序问题）。"""
        svc = self.service

        # 同步连接状态徽章
        if svc.is_connected:
            client = svc.client
            broker = f"{client.broker_host}:{client.broker_port}" if client else ""
            self.status_badge.update_status(True)
            self.info_labels["broker"].setText(broker)
            self._update_toggle_button()
            self.log_viewer.append_log("SYSTEM", "面板已加载，当前状态：已连接")
        elif svc.is_running:
            self.log_viewer.append_log("SYSTEM", "面板已加载，MQTT 运行中但未连接")
        else:
            self.log_viewer.append_log("SYSTEM", "面板已加载，MQTT 未启动")

        # 刷新设备信息
        self._refresh_info()

    def _poll_connection_status(self):
        """定期轮询连接状态，确保 UI 与实际 MQTT 状态一致。

        解决场景：启动时无网络 → 后续有网络，paho 自动重连成功，
        但信号可能因时序问题未被 UI 正确接收。
        """
        svc = self.service
        current_ui_connected = self.status_badge.text().startswith("● 已连接")
        actual_connected = svc.is_connected

        if actual_connected != current_ui_connected:
            if actual_connected:
                # 从未连接变为已连接
                client = svc.client
                broker = f"{client.broker_host}:{client.broker_port}" if client else ""
                self.status_badge.update_status(True)
                self.info_labels["broker"].setText(broker)
                self._update_toggle_button()
                self.log_viewer.append_log(
                    "SYSTEM",
                    f"检测到连接恢复: <b>{broker}</b>"
                )
            else:
                # 从已连接变为断开
                self.status_badge.update_status(False)
                self._update_toggle_button()

    def _set_info(self, key: str, text: str, max_chars: int = 35):
        """设置信息标签文本：超出长度省略号截断，悬浮显示完整内容。"""
        label = self.info_labels.get(key)
        if not label:
            return
        full_text = str(text)
        if len(full_text) > max_chars:
            display = full_text[:max_chars] + "…"
            label.setToolTip(full_text)
        else:
            display = full_text
            label.setToolTip("")
        label.setText(display)
