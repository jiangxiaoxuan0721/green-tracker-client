"""
执行单元管理页面 - 管理已发现的执行单元
"""
import os
import threading
from typing import Optional
from PyQt6.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QPushButton,
                               QLabel, QTableWidget, QTableWidgetItem,
                               QHeaderView, QMessageBox, QProgressBar, QComboBox,
                               QDialog, QDialogButtonBox, QScrollArea, QFrame, QGridLayout)
from PyQt6.QtCore import Qt, QThread, QTimer, pyqtSignal
from PyQt6.QtGui import QColor, QPalette
from device import scan_devices, get_device_state_manager, DeviceStatus


COLORS = {
    "bg": "#FAFAFA",
    "card": "#FFFFFF",
    "text_primary": "#2D2D2D",
    "text_secondary": "#757575",
    "border": "#BDBDBD",
    "accent": "#4A90A4",
    "accent_hover": "#3D7A8C",
    "success": "#66BB6A",
    "warning": "#FFA726",
    "danger": "#EF5350",
    "muted": "#BDBDBD",
}


class ScanDevicesThread(QThread):
    """执行单元扫描线程"""
    finished = pyqtSignal(list)
    progress = pyqtSignal(str)
    
    def __init__(self):
        super().__init__()
    
    def run(self):
        try:
            self.progress.emit("正在扫描局域网设备...")
            devices = scan_devices()
            self.finished.emit(devices)
        except Exception as e:
            self.finished.emit([])


class HealthCheckThread(QThread):
    """后台 TCP 探测线程：主动检测所有设备在线状态"""
    results = pyqtSignal(dict)  # {ip: bool}

    def __init__(self, device_manager):
        super().__init__()
        self.device_manager = device_manager
        self._running = True

    def run(self):
        while self._running:
            try:
                result = self.device_manager.health_check_all(timeout=0.5)
                self.results.emit(result)
            except Exception:
                pass
            # 每 5 秒探测一轮
            self.msleep(5000)

    def stop(self):
        self._running = False


class DeviceManagerPage(QWidget):
    """执行单元管理页面（TCP 主动探测 + MQTT 信号辅助）"""

    def __init__(self, main_window):
        super().__init__()
        self.main_window = main_window
        self.device_manager = get_device_state_manager()
        self.scanned_devices = []
        self.thread = None  # type: ignore
        self._health_thread: Optional[HealthCheckThread] = None
        self.init_ui()

        # ===== MQTT 信号（辅助：其他设备通过 MQTT 上报时立即感知）=====
        try:
            from mqtt import MQTTService
            svc = MQTTService.get_instance()
            svc.signals.device_heartbeat.connect(self._on_peer_heartbeat)
            svc.signals.device_offline.connect(self._on_peer_offline)
        except Exception:
            pass

        # 初始加载
        self.refresh_devices()

        # ===== 核心：TCP 探测后台线程 =====
        self._health_thread = HealthCheckThread(self.device_manager)
        self._health_thread.results.connect(self._on_health_results)
        self._health_thread.start()

    def closeEvent(self, a0):
        """页面关闭时清理资源"""
        # 停止 TCP 探测线程
        if self._health_thread and self._health_thread.isRunning():
            self._health_thread.stop()
            self._health_thread.wait(3000)
        # 停止扫描线程
        if self.thread and self.thread.isRunning():  # type: ignore
            self.thread.quit()  # type: ignore
            self.thread.wait()  # type: ignore
        a0.accept()  # type: ignore
    
    def init_ui(self):
        self.setStyleSheet(f"background-color: {COLORS['bg']};")
        layout = QVBoxLayout()
        layout.setContentsMargins(20, 20, 20, 20)

        # 标题栏
        title_layout = QHBoxLayout()

        page_title = QLabel("执行单元管理")
        page_title.setStyleSheet("font-size: 20px; font-weight: 600; color: #2D2D2D;")
        title_layout.addWidget(page_title)

        title_layout.addStretch()

        btn_back = QPushButton("← 返回")
        btn_back.setFixedHeight(40)
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
        btn_back.clicked.connect(self.go_back)
        title_layout.addWidget(btn_back)

        layout.addLayout(title_layout)

        # 操作按钮栏
        btn_bar = QHBoxLayout()
        
        self.btn_scan = QPushButton("扫描执行单元")
        self.btn_scan.setFixedHeight(36)
        self.btn_scan.setMinimumWidth(100)
        self.btn_scan.setStyleSheet(f"""
            QPushButton {{
                font-size: 14px;
                padding: 8px 16px;
                background-color: {COLORS['accent']};
                color: white;
                border: 2px solid {COLORS['border']};
                border-radius: 4px;
            }}
            QPushButton:hover {{ background-color: {COLORS['accent']}; }}
            QPushButton:disabled {{ background-color: {COLORS['border']}; }}
        """)
        self.btn_scan.clicked.connect(self.start_scan)
        btn_bar.addWidget(self.btn_scan)
        
        self.btn_refresh = QPushButton("刷新状态")
        self.btn_refresh.setFixedHeight(36)
        self.btn_refresh.setMinimumWidth(100)
        self.btn_refresh.setStyleSheet(f"""
            QPushButton {{
                font-size: 14px;
                padding: 8px 16px;
                background-color: {COLORS['card']};
                color: {COLORS['text_primary']};
                border: 2px solid {COLORS['border']};
                border-radius: 4px;
            }}
            QPushButton:hover {{ background-color: {COLORS['bg']}; }}
        """)
        self.btn_refresh.clicked.connect(self.refresh_devices)
        btn_bar.addWidget(self.btn_refresh)
        
        btn_bar.addStretch()
        
        # 执行单元统计
        self.stats_label = QLabel("执行单元总数: 0 | 空闲: 0 | 忙碌: 0")
        self.stats_label.setStyleSheet(f"font-size: 14px; color: {COLORS['text_secondary']};")
        btn_bar.addWidget(self.stats_label)

        layout.addLayout(btn_bar)

        # 进度条
        self.progress_bar = QProgressBar()
        self.progress_bar.setVisible(False)
        self.progress_bar.setStyleSheet(f"""
            QProgressBar {{
                border: 2px solid {COLORS['border']};
                border-radius: 4px;
                text-align: center;
                height: 8px;
            }}
            QProgressBar::chunk {{
                background-color: {COLORS['accent']};
                border-radius: 2px;
            }}
        """)
        layout.addWidget(self.progress_bar)

        # 滚动区域
        self.scroll_area = QScrollArea()
        self.scroll_area.setWidgetResizable(True)
        self.scroll_area.setStyleSheet(f"""
            QScrollArea {{
                background-color: transparent;
                border: none;
            }}
        """)

        # 卡片容器
        self.cards_container = QWidget()
        self.cards_container.setObjectName("cardContainer")
        self.cards_container.setStyleSheet(f"""
            #cardContainer {{
                background-color: transparent;
            }}
        """)

        # 使用 Grid 布局，每行 2 列，从左上到右下排列
        self.cards_grid = QGridLayout()
        self.cards_grid.setSpacing(8)
        self.cards_grid.setContentsMargins(4, 4, 4, 4)
        # 设置列均匀分配
        self.cards_grid.setColumnStretch(0, 1)
        self.cards_grid.setColumnStretch(1, 1)
        self.cards_grid.setAlignment(Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignLeft)
        self.cards_container.setLayout(self.cards_grid)
        self.scroll_area.setAlignment(Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignLeft)
        self.scroll_area.setWidget(self.cards_container)
        layout.addWidget(self.scroll_area)
        self.setLayout(layout)
    
    def go_back(self):
        self.main_window.show_home_page()

    def _on_peer_heartbeat(self, device_id: str, status_dict: dict):
        """MQTT 信号：其他设备上线心跳 → 立即注册/更新 + 刷新 UI"""
        ip = status_dict.get("ip", device_id)
        # 注册或更新设备（写内存缓存，O(1)）
        self.device_manager.register_device(
            ip=ip,
            device_type=status_dict.get("device_type", "MQTT Device"),
        )
        self.refresh_devices()

    def _on_peer_offline(self, device_id: str):
        """MQTT 信号：其他设备 LWT 离线 → 从内存缓存移除 + 刷新 UI"""
        data = self.device_manager._cache
        # 查找匹配的设备（按 ip 或 device_id 字段）
        target_ip = None
        for ip, d in data.get("devices", {}).items():
            if ip == device_id or d.get("device_id") == device_id:
                target_ip = ip
                break

        if target_ip:
            session_id = data["devices"][target_ip].get("assigned_session_id")
            if session_id and session_id in data.get("sessions", {}):
                data["sessions"][session_id]["devices"] = [
                    d for d in data["sessions"][session_id].get("devices", [])
                    if d != target_ip
                ]
            del data["devices"][target_ip]
            print(f"[设备离线] 已移除: {target_ip} (device_id={device_id})")

        self.refresh_devices()

    def _on_health_results(self, results: dict):
        """TCP 探测结果：立即处理离线/上线状态变化"""
        data = self.device_manager._cache
        changed = False

        for ip, online in results.items():
            device = data.get("devices", {}).get(ip)
            if not device:
                continue
            if online:
                # 设备在线：确保在缓存中（如果之前被移除则重新注册）
                if ip not in data["devices"]:
                    self.device_manager.register_device(
                        ip=ip,
                        device_type=device.get("device_type", "Unknown Device"),
                    )
                    changed = True
            else:
                # 设备离线：从缓存中移除
                session_id = device.get("assigned_session_id")
                if session_id and session_id in data.get("sessions", {}):
                    data["sessions"][session_id]["devices"] = [
                        d for d in data["sessions"][session_id].get("devices", [])
                        if d != ip
                    ]
                del data["devices"][ip]
                changed = True

        # 仅在有变化时刷新 UI（避免不必要的重绘）
        if changed:
            self.refresh_devices()

    def on_page_show(self):
        """页面显示时刷新执行单元状态"""
        self.refresh_devices()
    
    def start_scan(self):
        """开始扫描执行单元"""
        self.btn_scan.setEnabled(False)
        self.progress_bar.setVisible(True)
        self.progress_bar.setRange(0, 0)  # 不确定进度

        self.thread = ScanDevicesThread() # type: ignore
        self.thread.finished.connect(self.on_scan_finished) # type: ignore
        # 使用 Qt.ConnectionType.BlockingQueuedConnection 确保信号安全
        self.thread.progress.connect( # type: ignore
            self.on_scan_progress,
            Qt.ConnectionType.QueuedConnection
        ) # type: ignore
        self.thread.start() # type: ignore
    
    def on_scan_progress(self, message):
        self.progress_bar.setFormat(message)
    
    def on_scan_finished(self, devices):
        """扫描完成"""
        self.scanned_devices = devices
        self.btn_scan.setEnabled(True)
        self.progress_bar.setVisible(False)

        # 注册发现的设备
        for device in devices:
            self.device_manager.register_device(
                ip=device["ip"],
                device_type=device.get("type", "Unknown Device"),
                mac=device.get("mac"),
                hostname=device.get("hostname")
            )

        # 扫描完成后自动刷新状态
        self.refresh_devices()
        
    def _refresh_devices_immediate(self):
        """立即刷新执行单元列表（读内存缓存，无磁盘 I/O）"""
        devices = self.device_manager.get_all_devices()

        # 清理超时设备
        cleaned = self.device_manager.cleanup_stale_devices(offline_threshold_hours=24)
        if cleaned > 0:
            devices = self.device_manager.get_all_devices()

        # 清空卡片网格
        while self.cards_grid.count():
            item = self.cards_grid.takeAt(0)
            widget = item.widget() # type: ignore
            if widget:
                widget.deleteLater()

        # 统计数据
        idle_count = 0
        busy_count = 0
        assigned_count = 0

        # 创建执行单元卡片（每行2列，从左上到右下排列）
        cols = 2  # 每行显示2个卡片
        for index, device in enumerate(devices):
            # 动态计算网格位置（每行2列，从左上到右下排列）
            row = index // cols
            col = index % cols
            card = self._create_device_card(device)
            self.cards_grid.addWidget(card, row, col)

            # 统计
            if device.status == DeviceStatus.IDLE:
                idle_count += 1
            elif device.status == DeviceStatus.BUSY:
                busy_count += 1
            else:
                assigned_count += 1

        # 更新统计标签
        self.stats_label.setText(
            f"执行单元总数: {len(devices)} | 空闲: {idle_count} | 已分配: {assigned_count} | 忙碌: {busy_count}"
        )

    def _create_device_card(self, device):
        """创建执行单元卡片"""
        is_virtual = getattr(device, 'is_virtual', False)

        card = QFrame()
        card.setFrameStyle(QFrame.Shape.NoFrame)
        card.setFixedHeight(120)
        object_name = "virtualUnitCard" if is_virtual else "deviceCard"
        card.setObjectName(object_name)

        # 统一样式：虚拟单元与物理设备保持一致
        card.setStyleSheet(f"""
            #{object_name} {{
                background-color: {COLORS['card']};
                border: 2px solid {COLORS['border']};
                border-radius: 8px;
            }}
            #{object_name}:hover {{
                border-color: {COLORS['accent']};
                background-color: #F8FCFD;
            }}
        """)

        layout = QVBoxLayout()
        layout.setContentsMargins(12, 10, 12, 10)
        layout.setSpacing(6)
        layout.setAlignment(Qt.AlignmentFlag.AlignTop)

        # 状态颜色
        if device.status == DeviceStatus.IDLE:
            status_color = COLORS['success']
            status_text = "空闲"
        elif device.status == DeviceStatus.BUSY:
            status_color = COLORS['warning']
            status_text = "忙碌"
        else:
            status_color = COLORS['accent']
            status_text = "已分配"

        # 标题行（标识 + 虚拟标签 + 状态）
        title_layout = QHBoxLayout()
        title_layout.setContentsMargins(0, 0, 0, 0)

        ip_label = QLabel(device.ip)
        ip_label.setStyleSheet(f"font-size: 16px; font-weight: 600; color: {COLORS['text_primary']};")
        title_layout.addWidget(ip_label)

        title_layout.addStretch()

        status_badge = QLabel(status_text)
        status_badge.setStyleSheet(f"""
            font-size: 12px;
            color: {COLORS['text_secondary']};
            background-color: #F5F5F5;
            padding: 2px 8px;
            border-radius: 4px;
        """)
        title_layout.addWidget(status_badge)

        layout.addLayout(title_layout)

        # 单元类型
        type_label = QLabel(device.device_type)
        type_label.setStyleSheet(f"font-size: 13px; color: {COLORS['text_secondary']};")
        layout.addWidget(type_label)

        # 分配任务
        if device.assigned_session_id:
            task_label = QLabel(f"任务: {device.assigned_session_id}")
            task_label.setStyleSheet(f"font-size: 13px; color: {COLORS['text_secondary']};")
            layout.addWidget(task_label)


        # 操作按钮栏
        btn_layout = QHBoxLayout()
        btn_layout.setContentsMargins(0, 4, 0, 0)
        btn_layout.setSpacing(8)

        # 空闲或已分配的执行单元可以切换任务
        if device.status == DeviceStatus.IDLE or device.status == DeviceStatus.ASSIGNED:
            btn_switch = QPushButton("切换任务")
            btn_switch.setFixedHeight(30)
            btn_switch.setMinimumWidth(70)
            btn_switch.setStyleSheet(f"""
                QPushButton {{
                    font-size: 12px;
                    font-weight: 500;
                    padding: 4px 12px;
                    background-color: {COLORS['card']};
                    color: {COLORS['text_primary']};
                    border: 2px solid {COLORS['border']};
                    border-radius: 6px;
                }}
                QPushButton:hover {{ background-color: {COLORS['bg']}; border-color: {COLORS['accent']}; }}
            """)
            btn_switch.clicked.connect(
                lambda checked, ip=device.ip: self.switch_task_for_device(ip)
            )
            btn_layout.addWidget(btn_switch)

        # 已分配但不是忙碌状态的执行单元可以取消分配
        if device.assigned_session_id and device.status != DeviceStatus.BUSY:
            btn_unassign = QPushButton("取消分配")
            btn_unassign.setFixedHeight(30)
            btn_unassign.setMinimumWidth(70)
            btn_unassign.setStyleSheet(f"""
                QPushButton {{
                    font-size: 12px;
                    font-weight: 500;
                    padding: 4px 12px;
                    background-color: {COLORS['card']};
                    color: {COLORS['text_primary']};
                    border: 2px solid {COLORS['border']};
                    border-radius: 6px;
                }}
                QPushButton:hover {{ background-color: {COLORS['bg']}; border-color: {COLORS['accent']}; }}
            """)
            btn_unassign.clicked.connect(
                lambda checked, ip=device.ip: self.unassign_device(ip)
            )
            btn_layout.addWidget(btn_unassign)

        btn_layout.addStretch()
        layout.addLayout(btn_layout)
        layout.addStretch()

        card.setLayout(layout)
        return card

    def refresh_devices(self):
        """刷新执行单元列表"""
        # 如果有扫描线程正在运行，先不刷新
        if self.thread and self.thread.isRunning(): # type: ignore
            return

        # 确保 DataGenerator 虚拟执行单元已注册
        try:
            from ui.task_window import get_data_generator
            gen = get_data_generator()
            gen.ensure_registered()
        except Exception:
            pass

        self._refresh_devices_immediate()
    
    def unassign_device(self, ip: str):
        """取消执行单元分配"""
        reply = QMessageBox.question(
            self,
            "确认取消分配",
            f"确定要取消执行单元 {ip} 的任务分配吗？",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
        )

        if reply == QMessageBox.StandardButton.Yes:
            success = self.device_manager.unassign_device(ip)
            if success:
                QMessageBox.information(self, "成功", f"执行单元 {ip} 已取消分配")
                # 延迟刷新，避免在消息框显示时刷新
                from PyQt6.QtCore import QTimer
                QTimer.singleShot(100, self.refresh_devices)
            else:
                QMessageBox.warning(self, "失败", f"取消分配失败")

    def switch_task_for_device(self, ip: str):
        """为执行单元切换任务（仅允许选择云端API返回的真实任务）"""
        # 从 MainWindow 获取云端缓存的实时任务列表
        cloud_tasks = self.main_window.get_cloud_tasks()

        if not cloud_tasks:
            QMessageBox.information(
                self, "提示",
                "当前没有可用的云端任务，请先在主页点击「获取可用任务」联网同步。"
            )
            return

        # 构建 {session_id: session_name} 映射
        cloud_task_map = {
            t.get("id", ""): t.get("mission_name", "未命名")
            for t in cloud_tasks if t.get("id")
        }

        # 创建任务选择对话框
        dialog = QDialog(self)
        dialog.setWindowTitle(f"切换任务 - {ip}")
        dialog.setModal(True)
        dialog.setMinimumWidth(400)

        layout = QVBoxLayout()
        layout.setSpacing(12)
        layout.setContentsMargins(20, 20, 20, 20)

        # 当前执行单元信息
        device = self.device_manager.get_device(ip)
        current_task = device.assigned_session_id if device else None

        info_label = QLabel()
        if current_task:
            session_name = cloud_task_map.get(current_task, current_task)
            info_label.setText(f"当前任务: {session_name}")
        else:
            info_label.setText("当前状态: 空闲")
        info_label.setStyleSheet(f"font-size: 14px; font-weight: 600; color: {COLORS['text_primary']}; margin-bottom: 4px;")
        layout.addWidget(info_label)

        prompt_label = QLabel("选择要分配的任务:")
        prompt_label.setStyleSheet(f"font-size: 13px; color: {COLORS['text_secondary']};")
        layout.addWidget(prompt_label)

        # 任务下拉框
        combo = QComboBox()
        combo.setFixedHeight(38)
        combo.setStyleSheet(f"""
            QComboBox {{
                font-size: 14px;
                background-color: white;
                color: {COLORS['text_primary']};
                border: 2px solid {COLORS['border']};
                border-radius: 4px;
                padding: 6px 10px;
            }}
            QComboBox:hover {{
                border-color: {COLORS['accent']};
            }}
            QComboBox::drop-down {{
                border: none;
            }}
            QComboBox QAbstractItemView {{
                background-color: white;
                color: {COLORS['text_primary']};
                border: 2px solid {COLORS['border']};
                selection-background-color: {COLORS['accent']};
                selection-color: white;
                font-size: 14px;
            }}
        """)
        for session_id, session_name in cloud_task_map.items():
            combo.addItem(f"{session_name} ({session_id})", session_id)
        layout.addWidget(combo)

        # 如果设备已分配，选中当前任务
        if current_task:
            index = combo.findData(current_task)
            if index >= 0:
                combo.setCurrentIndex(index)

        # 按钮栏
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.setStyleSheet(f"""
            QDialogButtonBox QPushButton {{
                font-size: 13px;
                font-weight: 500;
                padding: 4px 16px;
                background-color: {COLORS['card']};
                color: {COLORS['text_primary']};
                border: 2px solid {COLORS['border']};
                border-radius: 6px;
            }}
            QDialogButtonBox QPushButton:hover {{
                background-color: {COLORS['bg']};
                border-color: {COLORS['accent']};
            }}
        """)
        buttons.accepted.connect(dialog.accept)
        buttons.rejected.connect(dialog.reject)
        layout.addWidget(buttons)

        dialog.setLayout(layout)

        # 显示对话框
        if dialog.exec() == QDialog.DialogCode.Accepted:
            new_session_id = combo.currentData()
            if not new_session_id:
                QMessageBox.warning(self, "错误", "请选择一个任务")
                return

            # 取消原有分配
            if current_task:
                self.device_manager.unassign_device(ip)

            # 分配到新任务（使用云端任务信息）
            session_name = cloud_task_map.get(new_session_id, new_session_id)
            success = self.device_manager.assign_device_to_session(ip, new_session_id, session_name)

            if success:
                QMessageBox.information(self, "成功", f"执行单元 {ip} 已切换到任务 {session_name}")
                from PyQt6.QtCore import QTimer
                QTimer.singleShot(100, self.refresh_devices)
            else:
                QMessageBox.warning(self, "失败", f"切换任务失败，执行单元可能正忙碌")

