"""
执行单元分配页面 - 将执行单元分配给任务
"""
import threading
from PyQt6.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QPushButton,
                               QLabel, QTableWidget, QTableWidgetItem,
                               QHeaderView, QMessageBox, QCheckBox)
from PyQt6.QtCore import Qt, QThread, pyqtSignal
from PyQt6.QtGui import QColor
from device import scan_devices, get_device_state_manager, DeviceStatus


COLORS = {
    "bg": "#FAFAFA",
    "card": "#FFFFFF",
    "text_primary": "#2D2D2D",
    "text_secondary": "#757575",
    "border": "#BDBDBD",
    "accent": "#4A90A4",
    "success": "#66BB6A",
}


class ScanDevicesThread(QThread):
    """设备扫描线程"""
    finished = pyqtSignal(list)
    progress = pyqtSignal(str)
    
    def __init__(self):
        super().__init__()
    
    def run(self):
        try:
            self.progress.emit("正在扫描局域网执行单元...")
            devices = scan_devices()
            self.finished.emit(devices)
        except Exception as e:
            self.finished.emit([])


class DeviceAssignPage(QWidget):
    """执行单元分配页面"""

    device_assigned = pyqtSignal(str, str)

    def __init__(self, session_id: str, session_name: str, main_window, return_to: str = "monitor"):
        super().__init__()
        self.session_id = session_id
        self.session_name = session_name
        self.main_window = main_window
        self.return_to = return_to  # "home" 或 "monitor"
        self.device_manager = get_device_state_manager()
        self.scanned_devices = []
        self.selected_devices = set()
        self.thread = None  # type: ignore
        self.init_ui()
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

        page_title = QLabel(f"分配执行单元 - {self.session_name}")
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
        
        self.btn_refresh = QPushButton("刷新")
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
        
        # 已分配统计
        self.assigned_label = QLabel("已分配执行单元: 0")
        self.assigned_label.setStyleSheet(f"font-size: 14px; color: {COLORS['text_secondary']};")
        btn_bar.addWidget(self.assigned_label)

        layout.addLayout(btn_bar)

        # 设备列表表格
        self.device_table = QTableWidget()
        self.device_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.device_table.setColumnCount(5)
        self.device_table.setHorizontalHeaderLabels([
            "选择", "标识", "单元类型", "状态", "分配任务"
        ])
        
        header = self.device_table.horizontalHeader()
        header.setStretchLastSection(True) # type: ignore
        header.setMinimumHeight(40) # type: ignore
        header.setStyleSheet( # type: ignore
            f"""QHeaderView::section {{
                background-color: {COLORS['card']};
                color: {COLORS['text_primary']};
                font-size: 14px;
                font-weight: 600;
                border: 2px solid {COLORS['border']};
                padding: 8px;
            }}
        """)
        
        self.device_table.setAlternatingRowColors(True)
        self.device_table.setStyleSheet(f"""
            QTableWidget {{
                background-color: {COLORS['card']};
                border: 2px solid {COLORS['border']};
                border-radius: 4px;
                gridline-color: {COLORS['border']};
            }}
            QTableWidget::item {{
                padding: 8px;
                color: {COLORS['text_primary']};
            }}
            QTableWidget::item:alternate {{
                background-color: #F5F5F5;
            }}
        """)
        
        layout.addWidget(self.device_table)
        
        # 确认按钮
        confirm_layout = QHBoxLayout()
        confirm_layout.addStretch()
        
        self.btn_confirm = QPushButton("确认分配")
        self.btn_confirm.setFixedHeight(40)
        self.btn_confirm.setMinimumWidth(120)
        self.btn_confirm.setStyleSheet(f"""
            QPushButton {{
                font-size: 14px;
                font-weight: 600;
                padding: 10px 24px;
                background-color: {COLORS['success']};
                color: white;
                border: 2px solid {COLORS['border']};
                border-radius: 4px;
            }}
            QPushButton:hover {{ background-color: {COLORS['success']}; }}
        """)
        self.btn_confirm.clicked.connect(self.confirm_assignment)
        confirm_layout.addWidget(self.btn_confirm)
        
        layout.addLayout(confirm_layout)
        self.setLayout(layout)

    def start_scan(self):
        """开始扫描执行单元"""
        self.btn_scan.setEnabled(False)

        self.thread = ScanDevicesThread() # type: ignore
        self.thread.progress.connect( # type: ignore
            lambda msg: None,
            Qt.ConnectionType.QueuedConnection
        ) # type: ignore
        self.thread.finished.connect( # type: ignore
            self.on_scan_finished,
            Qt.ConnectionType.QueuedConnection
        ) # type: ignore
        self.thread.start() # type: ignore
    
    def on_scan_finished(self, devices):
        """扫描完成"""
        self.scanned_devices = devices
        self.btn_scan.setEnabled(True)

        # 注册发现的设备
        for device in devices:
            self.device_manager.register_device(
                ip=device["ip"],
                device_type=device.get("type", "Unknown Device"),
                mac=device.get("mac"),
                hostname=device.get("hostname")
            )
        
        self.refresh_devices()
    
    def refresh_devices(self):
        """刷新执行单元列表"""
        # 确保 DataGenerator 虚拟单元已注册
        try:
            from ui.task_window import get_data_generator
            gen = get_data_generator()
            gen.ensure_registered()
        except Exception:
            pass
        # 如果有扫描线程正在运行，先不刷新
        if self.thread and self.thread.isRunning(): # type: ignore
            return

        # 只显示空闲执行单元
        devices = self.device_manager.get_all_devices(status_filter=DeviceStatus.IDLE)

        # 同时获取当前任务的已分配设备
        session_devices = self.device_manager.get_session_devices(self.session_id)
        assigned_ips = {d.ip for d in session_devices}

        # 合并显示：空闲执行单元 + 当前任务的已分配执行单元
        all_ips = {d.ip for d in devices} | assigned_ips
        all_devices = []
        for ip in all_ips:
            if ip in assigned_ips:
                # 已分配的执行单元
                for sd in session_devices:
                    if sd.ip == ip:
                        all_devices.append(sd)
                        break
            else:
                # 空闲设备
                for d in devices:
                    if d.ip == ip:
                        all_devices.append(d)
                        break

        # 清空表格以断开所有旧的信号连接
        self.device_table.clearContents()
        self.device_table.setRowCount(len(all_devices))
        self.selected_devices = assigned_ips

        for row, device in enumerate(all_devices):
            # 选择框
            checkbox = QCheckBox()
            checkbox.setChecked(device.ip in assigned_ips)
            checkbox.setEnabled(device.status == DeviceStatus.IDLE)
            checkbox.stateChanged.connect(
                lambda state, ip=device.ip: self.on_checkbox_changed(ip, state)
            )
            self.device_table.setCellWidget(row, 0, checkbox)
            
            # 标识（IP 或虚拟单元 ID）
            display_id = device.ip
            self.device_table.setItem(row, 1, QTableWidgetItem(display_id))
            
            # 设备类型
            self.device_table.setItem(row, 2, QTableWidgetItem(device.device_type))
            
            # 状态
            status_item = QTableWidgetItem()
            if device.ip in assigned_ips:
                status_item.setText("已分配")
                status_item.setBackground(Qt.GlobalColor.blue if hasattr(Qt.GlobalColor, 'blue') else Qt.GlobalColor(0x0000FF))
            elif device.status == DeviceStatus.IDLE:
                status_item.setText("空闲")
                status_item.setBackground(Qt.GlobalColor.green if hasattr(Qt.GlobalColor, 'green') else Qt.GlobalColor(0x00FF00))
            status_item.setForeground(Qt.GlobalColor.white)
            self.device_table.setItem(row, 3, status_item)
            
            # 分配任务
            if device.assigned_session_id:
                self.device_table.setItem(row, 4, QTableWidgetItem(device.assigned_session_id))
            elif device.ip in assigned_ips:
                self.device_table.setItem(row, 4, QTableWidgetItem(self.session_name))
            else:
                self.device_table.setItem(row, 4, QTableWidgetItem("-"))
        
        # 更新统计标签
        self.assigned_label.setText(f"已分配执行单元: {len(assigned_ips)}")
    
    def on_checkbox_changed(self, ip: str, state: int):
        """复选框状态改变"""
        if state == 2:  # 选中
            self.selected_devices.add(ip)
        else:  # 取消选中
            self.selected_devices.discard(ip)
        
        self.assigned_label.setText(f"已分配执行单元: {len(self.selected_devices)}")
    
    def confirm_assignment(self):
        """确认分配"""
        if not self.selected_devices:
            QMessageBox.warning(self, "提示", "请选择要分配的执行单元")
            return

        # 获取当前任务的已分配设备
        session_devices = self.device_manager.get_session_devices(self.session_id)
        current_assigned = {d.ip for d in session_devices}

        # 取消不再选中的设备
        for ip in current_assigned:
            if ip not in self.selected_devices:
                self.device_manager.unassign_device(ip)

        # 分配新选中的设备
        for ip in self.selected_devices:
            if ip not in current_assigned:
                success = self.device_manager.assign_device_to_session(
                    ip, self.session_id, self.session_name
                )
                if not success:
                    QMessageBox.warning(self, "错误", f"执行单元 {ip} 分配失败")

        QMessageBox.information(self, "成功", f"已分配 {len(self.selected_devices)} 个执行单元到任务")

        # 延迟刷新，避免在消息框显示时刷新
        from PyQt6.QtCore import QTimer
        QTimer.singleShot(100, self.refresh_devices)

        # 发射信号通知其他页面
        for ip in self.selected_devices:
            self.device_assigned.emit(self.session_id, ip)
    
    def go_back(self):
        if self.return_to == "home":
            self.main_window.show_home_page()
        else:
            self.main_window.show_monitor_page()
