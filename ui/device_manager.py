"""
设备管理页面 - 管理已发现的设备
"""
import os
import threading
from PyQt6.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QPushButton,
                               QLabel, QTableWidget, QTableWidgetItem,
                               QHeaderView, QMessageBox, QProgressBar, QComboBox,
                               QDialog, QDialogButtonBox, QScrollArea, QFrame, QGridLayout)
from PyQt6.QtCore import Qt, QThread, pyqtSignal
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
    """设备扫描线程"""
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


class DeviceManagerPage(QWidget):
    """设备管理页面"""

    def __init__(self, main_window):
        super().__init__()
        self.main_window = main_window
        self.device_manager = get_device_state_manager()
        self.scanned_devices = []
        self.thread = None  # type: ignore
        self.init_ui()
        # 初始化时自动刷新状态（不扫描设备）
        self.refresh_devices()

    def closeEvent(self, a0):
        """页面关闭时清理资源"""
        if self.thread and self.thread.isRunning(): # type: ignore
            self.thread.quit() # type: ignore
            self.thread.wait() # type: ignore
        a0.accept() # type: ignore
    
    def init_ui(self):
        self.setStyleSheet(f"background-color: {COLORS['bg']};")
        layout = QVBoxLayout()
        layout.setContentsMargins(20, 20, 20, 20)

        # 标题栏
        title_layout = QHBoxLayout()

        page_title = QLabel("设备管理")
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
        
        self.btn_scan = QPushButton("扫描设备")
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
        
        # 设备统计
        self.stats_label = QLabel("设备总数: 0 | 空闲: 0 | 忙碌: 0")
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

    def on_page_show(self):
        """页面显示时刷新设备状态"""
        self.refresh_devices()
    
    def start_scan(self):
        """开始扫描设备"""
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
        
    def _refresh_devices_immediate(self):
        """立即刷新设备列表，不检查线程状态"""
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

        # 创建设备卡片（每行2列，从左上到右下排列）
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
            f"设备总数: {len(devices)} | 空闲: {idle_count} | 已分配: {assigned_count} | 忙碌: {busy_count}"
        )

    def _create_device_card(self, device):
        """创建设备卡片"""
        card = QFrame()
        card.setFrameStyle(QFrame.Shape.NoFrame)
        card.setFixedHeight(120)
        card.setObjectName("deviceCard")
        card.setStyleSheet(f"""
            #deviceCard {{
                background-color: {COLORS['card']};
                border: 2px solid {COLORS['border']};
                border-radius: 8px;
            }}
            #deviceCard:hover {{
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

        # 标题行（IP + 状态）
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

        # 设备类型
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

        # 空闲或已分配的设备可以切换任务
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

        # 已分配但不是忙碌状态的设备可以取消分配
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
        """刷新设备列表"""
        # 如果有扫描线程正在运行，先不刷新
        if self.thread and self.thread.isRunning(): # type: ignore
            return

        self._refresh_devices_immediate()
    
    def unassign_device(self, ip: str):
        """取消设备分配"""
        reply = QMessageBox.question(
            self,
            "确认取消分配",
            f"确定要取消设备 {ip} 的任务分配吗？",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
        )

        if reply == QMessageBox.StandardButton.Yes:
            success = self.device_manager.unassign_device(ip)
            if success:
                QMessageBox.information(self, "成功", f"设备 {ip} 已取消分配")
                # 延迟刷新，避免在消息框显示时刷新
                from PyQt6.QtCore import QTimer
                QTimer.singleShot(100, self.refresh_devices)
            else:
                QMessageBox.warning(self, "失败", f"取消分配失败")

    def switch_task_for_device(self, ip: str):
        """为设备切换任务"""
        # 获取所有可用的任务
        data = self.device_manager._load_data()
        sessions = data.get("sessions", {})

        if not sessions:
            QMessageBox.information(self, "提示", "当前没有可用的任务，请先创建任务。")
            return

        # 创建任务选择对话框
        dialog = QDialog(self)
        dialog.setWindowTitle(f"切换任务 - {ip}")
        dialog.setModal(True)
        dialog.setMinimumWidth(400)

        layout = QVBoxLayout()
        layout.setSpacing(12)
        layout.setContentsMargins(20, 20, 20, 20)

        # 当前设备信息
        device = self.device_manager.get_device(ip)
        current_task = device.assigned_session_id if device else None

        info_label = QLabel()
        if current_task:
            session_info = sessions.get(current_task, {})
            session_name = session_info.get("session_name", current_task)
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
        for session_id, session_info in sessions.items():
            session_name = session_info.get("session_name", session_id)
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

            # 分配到新任务
            session_info = sessions.get(new_session_id, {})
            session_name = session_info.get("session_name", new_session_id)
            success = self.device_manager.assign_device_to_session(ip, new_session_id, session_name)

            if success:
                QMessageBox.information(self, "成功", f"设备 {ip} 已切换到任务 {session_name}")
                from PyQt6.QtCore import QTimer
                QTimer.singleShot(100, self.refresh_devices)
            else:
                QMessageBox.warning(self, "失败", f"切换任务失败，设备可能正忙碌")

