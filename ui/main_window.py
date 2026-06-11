import sys
import os
from PyQt6.QtWidgets import (QFrame, QWidget, QVBoxLayout, QHBoxLayout, QPushButton, QListWidget,
                             QLabel, QMessageBox, QListWidgetItem, QStackedWidget)
from PyQt6.QtCore import Qt, QThread, pyqtSignal
from PyQt6.QtGui import QColor
from api import get_active_sessions
from ui.task_window import init_data_generator
from device import get_task_manager


# 设计系统 - 干净专业配色
COLORS = {
    "bg": "#FAFAFA",          # 页面背景
    "card": "#FFFFFF",         # 卡片背景
    "text_primary": "#2D2D2D", # 主要文字
    "text_secondary": "#757575", # 辅助文字
    "border": "#BDBDBD",       # 边框 - 加粗
    "accent": "#4A90A4",       # 主强调色 - 青蓝
    "accent_hover": "#3D7A8C",# 强调色悬停
    "success": "#66BB6A",      # 成功 - 柔和绿
    "warning": "#FFA726",      # 进行中 - 柔和橙
    "danger": "#EF5350",       # 停止/错误 - 柔和红
    "muted": "#BDBDBD",        # 禁用状态
}


class FetchTasksThread(QThread):
    finished = pyqtSignal(list)
    error = pyqtSignal(str)

    def run(self):
        try:
            tasks = get_active_sessions()
            self.finished.emit(tasks)
        except Exception as e:
            self.error.emit(str(e))


class HomePage(QWidget):
    """主页 - 任务列表"""
    def __init__(self, main_window):
        super().__init__()
        self.main_window = main_window
        self.thread = None # type: ignore
        self.init_ui()

    def init_ui(self):
        self.setStyleSheet(f"""
            QWidget {{ background-color: {COLORS['bg']}; }}
            QLabel {{ color: {COLORS['text_primary']}; }}
        """)

        layout = QVBoxLayout()
        layout.setContentsMargins(20, 20, 20, 20)

        # 按钮区域
        btn_layout = QHBoxLayout()

        # 获取任务按钮
        self.btn_fetch = QPushButton("获取可用任务")
        self.btn_fetch.setFixedHeight(40)
        self.btn_fetch.setMinimumWidth(110)
        self.btn_fetch.setStyleSheet(f"""
            QPushButton {{
                font-size: 14px;
                font-weight: 500;
                padding: 0 20px;
                background-color: {COLORS['card']};
                color: {COLORS['text_primary']};
                border: 2px solid {COLORS['border']};
                border-radius: 4px;
            }}
            QPushButton:hover {{ background-color: {COLORS['bg']}; }}
        """)
        self.btn_fetch.clicked.connect(self.fetch_tasks)
        btn_layout.addWidget(self.btn_fetch)

        # 任务管理按钮
        self.btn_monitor = QPushButton("任务管理")
        self.btn_monitor.setFixedHeight(40)
        self.btn_monitor.setMinimumWidth(110)
        self.btn_monitor.setStyleSheet(f"""
            QPushButton {{
                font-size: 14px;
                font-weight: 500;
                padding: 0 20px;
                background-color: {COLORS['card']};
                color: {COLORS['text_primary']};
                border: 2px solid {COLORS['border']};
                border-radius: 4px;
            }}
            QPushButton:hover {{ background-color: {COLORS['bg']}; }}
        """)
        self.btn_monitor.clicked.connect(self.show_monitor)
        btn_layout.addWidget(self.btn_monitor)

        # 设备管理按钮
        self.btn_device = QPushButton("执行单元")
        self.btn_device.setFixedHeight(40)
        self.btn_device.setMinimumWidth(110)
        self.btn_device.setStyleSheet(f"""
            QPushButton {{
                font-size: 14px;
                font-weight: 500;
                padding: 0 20px;
                background-color: {COLORS['card']};
                color: {COLORS['text_primary']};
                border: 2px solid {COLORS['border']};
                border-radius: 4px;
            }}
            QPushButton:hover {{ background-color: {COLORS['bg']}; }}
        """)
        self.btn_device.clicked.connect(self.show_device_manager)
        btn_layout.addWidget(self.btn_device)

        # MQTT 控制台按钮
        self.btn_mqtt = QPushButton("MQTT 控制台")
        self.btn_mqtt.setFixedHeight(40)
        self.btn_mqtt.setMinimumWidth(120)
        self.btn_mqtt.setStyleSheet(f"""
            QPushButton {{
                font-size: 14px;
                font-weight: 500;
                padding: 0 20px;
                background-color: {COLORS['card']};
                color: {COLORS['text_primary']};
                border: 2px solid {COLORS['border']};
                border-radius: 4px;
            }}
            QPushButton:hover {{ background-color: {COLORS['bg']}; }}
        """)
        self.btn_mqtt.clicked.connect(self.show_mqtt_panel)
        btn_layout.addWidget(self.btn_mqtt)

        btn_layout.addStretch()
        layout.addLayout(btn_layout)

        # 任务列表
        self.task_list = QListWidget()
        self.task_list.setStyleSheet(f"""
            QListWidget {{
                background-color: {COLORS['card']};
            }}
            QListWidget::item:selected {{
                background-color: {COLORS['bg']};
            }}
        """)
        layout.addWidget(self.task_list)

        self.setLayout(layout)

    def show_monitor(self):
        """显示任务管理页面"""
        self.main_window.show_monitor_page()

    def show_device_manager(self):
        """显示设备管理页面"""
        self.main_window.show_device_manager_page()

    def show_mqtt_panel(self):
        """显示 MQTT 远程控制面板"""
        self.main_window.show_mqtt_panel_page()

    def add_and_show_monitor(self, session_id: str, session_name: str, base_dir: str):
        """添加任务并显示管理页面"""
        self.main_window.show_monitor_page()
        self.main_window.monitor_page.add_task(session_id, session_name, base_dir)

    def fetch_tasks(self):
        self.btn_fetch.setEnabled(False)
        self.task_list.clear()
        self.task_list.addItem("正在获取任务...")

        self.thread = FetchTasksThread() # type: ignore
        self.thread.finished.connect(self.on_tasks_finished) # type: ignore
        self.thread.error.connect(self.on_tasks_error) # type: ignore
        self.thread.start() # type: ignore

    def on_tasks_finished(self, tasks):
        self.btn_fetch.setEnabled(True)
        self.task_list.clear()
        if not tasks:
            self.task_list.addItem("暂无活跃任务")
            # 清空云端缓存（无任务）
            self.main_window._cloud_tasks = []
            return

        # 缓存云端任务列表（作为分配任务的唯一数据源）
        self.main_window._cloud_tasks = tasks
        # 同步本地缓存：清理已不在云端的过期任务
        self._sync_local_sessions(tasks)

        for task in tasks:
                task_name = task.get("mission_name", "未命名")
                task_desc = task.get("description", "")

                item = QListWidgetItem()
                self.task_list.addItem(item)

                container = QWidget()
                container_layout = QVBoxLayout()
                container_layout.setContentsMargins(8, 8, 8, 8)

                info_label = QLabel(f"{task_name}")
                info_label.setStyleSheet(f"font-size: 14px; font-weight: 500; color: {COLORS['text_primary']};")
                container_layout.addWidget(info_label)

                if task_desc:
                    desc_label = QLabel(task_desc)
                    desc_label.setStyleSheet(f"font-size: 12px; color: {COLORS['text_secondary']}; margin-top: 2px;")
                    container_layout.addWidget(desc_label)

                btn_layout = QHBoxLayout()

                # 按钮样式
                btn_base_style = f"""
                    QPushButton {{
                        font-size: 13px;
                        padding: 0 14px;
                        background-color: {COLORS['card']};
                        color: {COLORS['text_primary']};
                        border: 2px solid {COLORS['border']};
                        border-radius: 4px;
                    }}
                    QPushButton:hover {{ background-color: {COLORS['bg']}; }}
                """

                btn_start = QPushButton("开始任务")
                btn_start.setFixedHeight(38)
                btn_start.setMinimumWidth(90)
                btn_start.setStyleSheet(btn_base_style)

                btn_upload = QPushButton("上传数据")
                btn_upload.setFixedHeight(38)
                btn_upload.setMinimumWidth(90)
                btn_upload.setStyleSheet(btn_base_style)

                btn_batch = QPushButton("批量上传")
                btn_batch.setFixedHeight(38)
                btn_batch.setMinimumWidth(90)
                btn_batch.setStyleSheet(btn_base_style)

                btn_assign = QPushButton("分配单元")
                btn_assign.setFixedHeight(38)
                btn_assign.setMinimumWidth(90)
                btn_assign.setStyleSheet(btn_base_style)

                task_copy = task.copy()
                session_id = task_copy.get("id", "")
                session_name = task_copy.get("mission_name", "未命名")

                # 将任务添加到任务管理器
                base_dir = os.path.expanduser("~/green_tracker_data")
                from device import get_task_manager
                get_task_manager().create_task(session_id, session_name, base_dir)

                # 点击开始任务 -> 切换到管理页面并添加该任务
                btn_start.clicked.connect(
                    lambda checked, s_id=session_id, s_name=session_name, b_dir=base_dir:
                    self.add_and_show_monitor(s_id, s_name, b_dir)
                )

                # 点击上传数据 -> 跳转到单次上传页面
                btn_upload.clicked.connect(lambda checked, t=task_copy: self.main_window.show_upload_page(t))

                # 点击批量上传 -> 跳转到批量上传页面
                btn_batch.clicked.connect(lambda checked, t=task_copy: self.main_window.show_batch_upload_page(t))

                # 点击分配设备 -> 跳转到设备分配页面
                btn_assign.clicked.connect(
                    lambda checked, s_id=session_id, s_name=session_name:
                    self.main_window.show_device_assign_page(s_id, s_name, return_to="home")
                )

                btn_layout.addWidget(btn_start)
                btn_layout.addWidget(btn_upload)
                btn_layout.addWidget(btn_batch)
                btn_layout.addWidget(btn_assign)
                btn_layout.addStretch()

                container_layout.addLayout(btn_layout)
                container.setLayout(container_layout)

                item.setSizeHint(container.sizeHint())
                self.task_list.setItemWidget(item, container)

    def _sync_local_sessions(self, cloud_tasks: list[dict]):
        """用云端任务列表同步本地会话缓存，清理已失效的本地任务。"""
        cloud_ids = {t.get("id", "") for t in cloud_tasks if t.get("id")}
        from device import get_device_state_manager
        mgr = get_device_state_manager()
        data = mgr._load_data()
        local_sessions = data.get("sessions", {})
        stale_ids = [sid for sid in local_sessions if sid not in cloud_ids]
        if stale_ids:
            for sid in stale_ids:
                session = local_sessions[sid]
                for ip in session.get("devices", []):
                    if ip in data.get("devices", {}):
                        data["devices"][ip]["assigned_session_id"] = None
                        data["devices"][ip]["status"] = "idle"
                        data["devices"][ip]["assigned_time"] = None
                del data["sessions"][sid]
            mgr._save_data(data)
            print(f"[任务同步] 已清理 {len(stale_ids)} 个本地过期任务: {stale_ids}")

    def on_tasks_error(self, error_msg):
        self.btn_fetch.setEnabled(True)
        self.task_list.clear()
        QMessageBox.critical(self, "错误", f"获取任务失败: {error_msg}")


class MainWindow(QWidget):
    def __init__(self):
        super().__init__()
        # 启动后台数据生成器（每5秒生成一次）
        init_data_generator(interval=5.0)
        # 初始化时扫描设备
        self.scan_devices_on_init()
        # 自动启动 MQTT
        self._auto_start_mqtt()
        # 云端任务缓存（仅包含从API获取的真实任务）
        self._cloud_tasks: list[dict] = []
        self.init_ui()

    def scan_devices_on_init(self):
        """初始化时扫描设备"""
        from device import scan_devices, get_device_state_manager
        import threading

        def scan():
            print("[初始化扫描] 开始扫描局域网设备...")
            devices = scan_devices()
            print(f"[初始化扫描] 完成，发现 {len(devices)} 个设备")

            # 注册发现的设备到设备状态管理器
            device_manager = get_device_state_manager()
            for device in devices:
                device_manager.register_device(
                    ip=device["ip"],
                    device_type=device.get("type", "Unknown Device"),
                    mac=device.get("mac"),
                    hostname=device.get("hostname")
                )

        thread = threading.Thread(target=scan, daemon=True)
        thread.start()

    def _auto_start_mqtt(self):
        """启动时自动连接 MQTT（静默失败，不阻塞 UI）。"""
        try:
            from mqtt.manager import MQTTService
            service = MQTTService.get_instance()
            service.start()
            print("[MQTT] 后台服务已启动")
        except Exception as e:
            print(f"[MQTT] 启动跳过: {e}")

    def init_ui(self):
        self.setWindowTitle("Green Tracker")
        self.resize(720, 480)
        self.setStyleSheet(f"background-color: {COLORS['bg']};")

        # 使用 QStackedWidget 管理多个页面
        self.stack = QStackedWidget()
        self.stack.setStyleSheet(f"background-color: {COLORS['bg']};")

        # 创建各个页面
        self.home_page = HomePage(self)
        self.task_page = None
        self.upload_page = None
        self.monitor_page = None
        self.batch_upload_page = None
        self.device_manager_page = None
        self.device_assign_page = None
        self.mqtt_panel_page = None

        # 将主页添加到堆栈
        self.stack.addWidget(self.home_page)

        # 主布局
        layout = QVBoxLayout()
        layout.addWidget(self.stack)
        self.setLayout(layout)

    def show_task_page(self, task):
        if self.task_page is None:
            from ui.task_window import TaskPage
            self.task_page = TaskPage(task, self)
            self.stack.addWidget(self.task_page)

        # 更新任务数据
        self.task_page.update_task(task)

        # 切换到任务页面
        self.stack.setCurrentWidget(self.task_page)

    def show_upload_page(self, task):
        if self.upload_page is None:
            from ui.upload_window import UploadPage
            self.upload_page = UploadPage(task, self)
            self.stack.addWidget(self.upload_page)

        # 更新任务数据
        self.upload_page.update_task(task)

        # 切换到上传页面
        self.stack.setCurrentWidget(self.upload_page)

    def show_home_page(self):
        self.stack.setCurrentWidget(self.home_page)

    def get_cloud_tasks(self) -> list[dict]:
        """获取云端缓存的任务列表（仅包含从API获取的真实任务）。"""
        return list(self._cloud_tasks)

    def show_monitor_page(self):
        """显示任务管理页面"""
        if self.monitor_page is None:
            from ui.collection_monitor import CollectionMonitorPage
            self.monitor_page = CollectionMonitorPage(self)
            self.stack.addWidget(self.monitor_page)
        self.stack.setCurrentWidget(self.monitor_page)

    def show_batch_upload_page(self, task):
        """显示批量上传页面"""
        session_id = task.get("id", "")
        session_name = task.get("mission_name", "未命名")

        # 移除旧的批量上传页面（如果存在）
        if hasattr(self, 'batch_upload_page') and self.batch_upload_page:
            self.stack.removeWidget(self.batch_upload_page)
            self.batch_upload_page.deleteLater()

        # 创建新实例，确保正确识别session
        from ui.batch_upload import BatchUploadPage
        self.batch_upload_page = BatchUploadPage(task, self)
        self.stack.addWidget(self.batch_upload_page)
        self.stack.setCurrentWidget(self.batch_upload_page)

    def show_device_manager_page(self):
        """显示执行单元管理页面"""
        if self.device_manager_page is None:
            from ui.device_manager import DeviceManagerPage
            self.device_manager_page = DeviceManagerPage(self)
            self.stack.addWidget(self.device_manager_page)
        self.stack.setCurrentWidget(self.device_manager_page)
        # 进入页面时刷新状态
        if hasattr(self.device_manager_page, 'on_page_show'):
            self.device_manager_page.on_page_show()

    def show_device_assign_page(self, session_id: str, session_name: str, return_to: str = "monitor"):
        """显示设备分配页面"""
        from ui.device_assign import DeviceAssignPage

        # 移除旧的设备分配页面（如果存在）
        if hasattr(self, 'device_assign_page') and self.device_assign_page:
            self.stack.removeWidget(self.device_assign_page)
            self.device_assign_page.deleteLater()

        self.device_assign_page = DeviceAssignPage(session_id, session_name, self, return_to=return_to)
        self.stack.addWidget(self.device_assign_page)
        self.stack.setCurrentWidget(self.device_assign_page)

    def show_mqtt_panel_page(self):
        """显示 MQTT 远程控制面板"""
        if self.mqtt_panel_page is None:
            from ui.mqtt_panel import MqttPanel
            self.mqtt_panel_page = MqttPanel(self)
            self.stack.addWidget(self.mqtt_panel_page)
        self.stack.setCurrentWidget(self.mqtt_panel_page)
