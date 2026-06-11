"""
任务管理页面 - 显示多个任务同时采集状态
"""
import os
import time
import threading
from datetime import datetime
from typing import Dict
from PyQt6.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QPushButton,
                             QLabel, QFrame, QScrollArea, QGridLayout)
from PyQt6.QtCore import Qt, pyqtSignal, QThread
from PyQt6.QtGui import QColor
from device import get_task_manager


# 设计系统
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


class TaskCard(QFrame):
    """单个任务卡片"""
    status_changed = pyqtSignal(str, bool)  # session_id, is_running
    assign_device = pyqtSignal(str, str)  # session_id, session_name

    def __init__(self, session_id: str, session_name: str, data_dir: str, parent=None):
        super().__init__(parent)
        self.session_id = session_id
        self.session_name = session_name
        self.data_dir = data_dir
        self.is_running = False
        self.collected_count = 0
        self.thread = None # type: ignore
        self.stop_event = threading.Event()
        self.init_ui()

    def init_ui(self):
        # 使用卡片边框样式，紧凑型
        self.setFrameStyle(QFrame.Shape.NoFrame)
        self.setObjectName("taskCard")
        self.setFixedHeight(100)  # 固定卡片高度
        self.setStyleSheet(f"""
            #taskCard {{
                background-color: {COLORS['card']};
                border: 2px solid {COLORS['border']};
                border-radius: 8px;
            }}
            #taskCard:hover {{
                border-color: {COLORS['accent']};
            }}
        """)

        # 极紧凑的内边距
        layout = QVBoxLayout()
        layout.setContentsMargins(12, 8, 12, 8)
        layout.setSpacing(4)
        layout.setAlignment(Qt.AlignmentFlag.AlignTop)  # 顶部对齐，不居中

        # 第一行：任务名称
        name_label = QLabel(self.session_name)
        name_label.setStyleSheet(f"font-size: 15px; font-weight: 600; color: {COLORS['text_primary']};")
        layout.addWidget(name_label)

        # 第二行：状态 + 数据计数
        info_layout = QHBoxLayout()
        info_layout.setSpacing(0)

        # 状态标签
        self.status_label = QLabel("已停止")
        self.status_label.setStyleSheet(f"""
            font-size: 12px;
            color: {COLORS['text_secondary']};
            background-color: #F5F5F5;
            padding: 2px 8px;
            border-radius: 4px;
        """)
        info_layout.addWidget(self.status_label)

        # 数据计数 - 大数字显示
        self.count_label = QLabel("0")
        self.count_label.setStyleSheet(f"""
            font-size: 18px;
            font-weight: 700;
            color: {COLORS['accent']};
        """)
        info_layout.addWidget(self.count_label)

        info_layout.addStretch()
        layout.addLayout(info_layout)

        # 第三行：ID + 按钮
        bottom_layout = QHBoxLayout()
        bottom_layout.setSpacing(0)

        # Session ID
        id_label = QLabel(f"ID: {self.session_id[:12]}...")
        id_label.setStyleSheet(f"font-size: 11px; color: {COLORS['text_secondary']};")
        bottom_layout.addWidget(id_label)

        bottom_layout.addStretch()

        # 设备分配按钮
        self.btn_assign = QPushButton("分配单元")
        self.btn_assign.setFixedHeight(30)
        self.btn_assign.setMinimumWidth(70)
        self.btn_assign.setStyleSheet(f"""
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
        self.btn_assign.clicked.connect(self.on_assign_device)
        bottom_layout.addWidget(self.btn_assign)

        # 开始/停止按钮
        self.btn_toggle = QPushButton("开始")
        self.btn_toggle.setFixedHeight(30)
        self.btn_toggle.setMinimumWidth(60)
        self.btn_toggle.setStyleSheet(f"""
            QPushButton {{
                font-size: 13px;
                font-weight: 500;
                padding: 4px 16px;
                background-color: {COLORS['success']};
                color: white;
                border: 2px solid {COLORS['border']};
                border-radius: 6px;
            }}
            QPushButton:hover {{ background-color: #57A65A; border-color: {COLORS['success']}; }}
        """)
        self.btn_toggle.clicked.connect(self.toggle)
        bottom_layout.addWidget(self.btn_toggle)

        layout.addLayout(bottom_layout)
        self.setLayout(layout)

    def on_assign_device(self):
        """点击分配设备按钮"""
        self.assign_device.emit(self.session_id, self.session_name)

    def toggle(self):
        if self.is_running:
            self.stop()
        else:
            self.start()

    def start(self):
        if self.is_running:
            return

        self.is_running = True
        self.stop_event.clear()
        self.collected_count = 0

        self.btn_toggle.setText("停止")
        self.btn_toggle.setFixedHeight(30)
        self.btn_toggle.setMinimumWidth(80)
        self.btn_toggle.setStyleSheet(f"""
            QPushButton {{
                font-size: 13px;
                font-weight: 500;
                padding: 4px 16px;
                background-color: {COLORS['danger']};
                color: white;
                border: 2px solid {COLORS['border']};
                border-radius: 6px;
            }}
            QPushButton:hover {{ background-color: #D74340; border-color: {COLORS['danger']}; }}
        """)
        self.status_label.setText("采集中")
        self.status_label.setStyleSheet(f"""
            font-size: 12px;
            color: white;
            background-color: {COLORS['success']};
            padding: 2px 8px;
            border-radius: 4px;
            font-weight: 500;
        """)

        # 创建目录
        os.makedirs(self.data_dir, exist_ok=True)
        csv_file = os.path.join(self.data_dir, "data.csv")
        if not os.path.exists(csv_file):
            with open(csv_file, 'w', encoding='utf-8') as f:
                f.write("timestamp,sensor_id,data_type,value,unit,is_uploaded\n")

        # 启动采集线程
        self.thread = threading.Thread(target=self._collect_loop, daemon=True) # type: ignore
        self.thread.start() # type: ignore

        self.status_changed.emit(self.session_id, True)

    def stop(self):
        if not self.is_running:
            return

        self.is_running = False
        self.stop_event.set()

        self.btn_toggle.setText("开始")
        self.btn_toggle.setFixedHeight(30)
        self.btn_toggle.setMinimumWidth(80)
        self.btn_toggle.setStyleSheet(f"""
            QPushButton {{
                font-size: 13px;
                font-weight: 500;
                padding: 4px 16px;
                background-color: {COLORS['success']};
                color: white;
                border: 2px solid {COLORS['border']};
                border-radius: 6px;
            }}
            QPushButton:hover {{ background-color: #57A65A; border-color: {COLORS['success']}; }}
        """)
        self.status_label.setText("已停止")
        self.status_label.setStyleSheet(f"""
            font-size: 12px;
            color: {COLORS['text_secondary']};
            background-color: #F5F5F5;
            padding: 2px 8px;
            border-radius: 4px;
        """)

        if self.thread:
            self.thread.join(timeout=2) # type: ignore

        self.status_changed.emit(self.session_id, False)

    def _collect_loop(self):
        """采集循环 - 同时生成模拟数据和采集设备图像"""
        from ui.task_window import get_data_generator
        from device import get_device_state_manager, ESP32CAM
        generator = get_data_generator()
        device_manager = get_device_state_manager()
        csv_file = os.path.join(self.data_dir, "data.csv")

        # 创建图像保存目录
        images_dir = os.path.join(self.data_dir, "images")
        os.makedirs(images_dir, exist_ok=True)

        while self.is_running and not self.stop_event.is_set():
            try:
                # 1. 生成并采集模拟数据（保留原有逻辑）
                data = generator.generate()

                # 写入CSV
                timestamp = datetime.now().isoformat()
                with open(csv_file, 'a', encoding='utf-8') as f:
                    f.write(f"{timestamp},{data['data_subtype'].value},{data['data_type'].value},"
                           f"{data['data_value']},{data['unit'].value},False\n")

                # 2. 从分配给当前任务的设备采集图像
                devices = device_manager.get_session_devices(self.session_id)
                for device in devices:
                    if device.device_type == "ESP32-CAM":
                        try:
                            cam = ESP32CAM(device.ip)
                            image_data = cam.get_capture(timeout=5.0)
                            if image_data:
                                # 保存图像到 images 目录，文件名格式: IP_时间戳.jpg
                                timestamp_str = datetime.now().strftime("%Y%m%d_%H%M%S")
                                filename = f"{device.ip}_{timestamp_str}.jpg"
                                filepath = os.path.join(images_dir, filename)
                                with open(filepath, 'wb') as f:
                                    f.write(image_data)
                                print(f"图像已保存: {filepath}")
                            else:
                                print(f"获取设备 {device.ip} 图像失败")
                        except Exception as e:
                            print(f"设备 {device.ip} 采集错误: {e}")

                self.collected_count += 1

                # 更新UI（需在主线程）
                self.count_label.setText(f"{self.collected_count} 条")

            except Exception as e:
                print(f"采集错误: {e}")

            time.sleep(1.0)  # 每秒采集一次


class CollectionMonitorPage(QWidget):
    """任务管理页面 - 同时显示多个任务"""

    def __init__(self, main_window):
        super().__init__()
        self.main_window = main_window
        self.task_cards: Dict[str, TaskCard] = {}
        self.scanned_devices = []  # 扫描到的设备列表
        self.init_ui()

    def init_ui(self):
        self.setStyleSheet(f"background-color: {COLORS['bg']};")
        layout = QVBoxLayout()
        layout.setContentsMargins(12, 8, 12, 8)
        layout.setSpacing(0)

        # 标题栏
        title_layout = QHBoxLayout()
        title = QLabel("任务管理")
        title.setStyleSheet(f"font-size: 20px; font-weight: 600; color: {COLORS['text_primary']};")
        title_layout.addWidget(title)

        title_layout.addStretch()

        btn_back = QPushButton("← 返回")
        btn_back.setFixedHeight(40)
        btn_back.setMinimumWidth(90)
        btn_back.setStyleSheet(f"""
            QPushButton {{
                font-size: 14px;
                padding: 8px 16px;
                background-color: #757575;
                color: white;
                border: 2px solid #BDBDBD;
                border-radius: 4px;
            }}
            QPushButton:hover {{ background-color: #616161; }}
        """)
        btn_back.clicked.connect(self.go_back)
        title_layout.addWidget(btn_back)

        layout.addLayout(title_layout)

        # 说明
        info_label = QLabel("点击「开始」按钮启动采集")
        info_label.setStyleSheet(f"font-size: 11px; color: {COLORS['text_secondary']}; margin-bottom: 6px;")
        layout.addWidget(info_label)

        # 滚动区域 - 紧凑的 Grid 布局
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setStyleSheet(f"""
            QScrollArea {{
                background-color: transparent;
                border: none;
            }}
        """)

        # 父容器 - 卡片区域背景
        self.card_container = QWidget()
        self.card_container.setObjectName("cardContainer")
        self.card_container.setStyleSheet(f"""
            #cardContainer {{
                background-color: transparent;
            }}
        """)

        # 使用 Grid 布局，每行 2 列，从左上到右下排列
        self.card_layout = QGridLayout()
        self.card_layout.setSpacing(8)
        self.card_layout.setContentsMargins(4, 4, 4, 4)
        # 设置列均匀分配
        self.card_layout.setColumnStretch(0, 1)
        self.card_layout.setColumnStretch(1, 1)
        self.card_layout.setAlignment(Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignLeft)

        # 无任务占位提示
        self.empty_label = QLabel("无任务")
        self.empty_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.empty_label.setStyleSheet(f"""
            font-size: 16px; color: {COLORS['text_secondary']};
            padding: 60px 0px;
        """)
        self.card_layout.addWidget(self.empty_label, 0, 0, 1, 2, Qt.AlignmentFlag.AlignCenter)

        self.card_container.setLayout(self.card_layout)
        scroll.setAlignment(Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignLeft)
        scroll.setWidget(self.card_container)
        layout.addWidget(scroll)

        self.setLayout(layout)

    def add_task(self, session_id: str, session_name: str, base_dir: str):
        """添加任务卡片"""
        if session_id in self.task_cards:
            return

        data_dir = os.path.join(base_dir, session_id)
        card = TaskCard(session_id, session_name, data_dir)
        card.status_changed.connect(self.on_task_status_changed)
        card.assign_device.connect(self.on_assign_device)

        # 动态计算网格位置（每行2列，从左上到右下排列）
        cols = 2  # 每行显示2个卡片
        row = len(self.task_cards) // cols
        col = len(self.task_cards) % cols
        self.card_layout.addWidget(card, row, col)

        self.task_cards[session_id] = card
        self.empty_label.hide()

    def on_assign_device(self, session_id: str, session_name: str):
        """处理设备分配点击"""
        self.main_window.show_device_assign_page(session_id, session_name)

    def remove_task(self, session_id: str):
        """移除任务卡片"""
        if session_id in self.task_cards:
            card = self.task_cards[session_id]
            card.stop()
            self.card_layout.removeWidget(card)
            card.deleteLater()
            del self.task_cards[session_id]
        if not self.task_cards:
            self.empty_label.show()

    def on_task_status_changed(self, session_id: str, is_running: bool):
        """任务状态变化回调"""
        # 同步更新设备状态
        from device import get_device_state_manager
        device_manager = get_device_state_manager()
        status = "running" if is_running else "stopped"
        device_manager.set_session_status(session_id, status)

    def go_back(self):
        self.main_window.show_home_page()


class CollectionMonitorThread(QThread):
    """后台管理线程 - 监听新任务"""
    new_task = pyqtSignal(str, str)  # session_id, session_name

    def __init__(self, monitor_page):
        super().__init__()
        self.monitor_page = monitor_page
        self.running = True

    def run(self):
        task_manager = get_task_manager()
        while self.running:
            tasks = task_manager.get_all_tasks()
            for session_id, task in tasks.items():
                if session_id not in self.monitor_page.task_cards:
                    self.new_task.emit(session_id, task.session_name)
            time.sleep(1)

    def stop(self):
        self.running = False
