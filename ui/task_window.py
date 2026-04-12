import os
import json
from datetime import datetime
from PyQt6.QtWidgets import QWidget, QVBoxLayout, QHBoxLayout, QPushButton, QLabel, QTextEdit, QMessageBox
from PyQt6.QtCore import QThread, pyqtSignal
from device import DataGenerator


# 全局数据生成器（在应用启动时创建）
data_generator = None


def init_data_generator(interval: float = 5.0):
    """初始化并启动全局数据生成器"""
    global data_generator
    if data_generator is None:
        data_generator = DataGenerator(interval=interval)
        data_generator.start()
    return data_generator


def get_data_generator() -> DataGenerator:
    """获取全局数据生成器"""
    return data_generator # type: ignore


class BatchCollector:
    """本地批次数据收集器"""

    def __init__(self, session_id: str, session_name: str, base_dir: str = None): # type: ignore
        self.session_id = session_id
        self.session_name = session_name
        self.base_dir = base_dir or os.path.expanduser("~/green_tracker_data")

        # 使用 session_id 作为文件夹名称
        self.batch_dir = os.path.join(self.base_dir, self.session_id)
        self.images_dir = os.path.join(self.batch_dir, "images")
        self.data_file = os.path.join(self.batch_dir, "data.csv")
        self.meta_file = os.path.join(self.batch_dir, "meta.json")

    def create_structure(self):
        """创建目录结构，如果存在则直接使用"""
        os.makedirs(self.batch_dir, exist_ok=True)
        os.makedirs(self.images_dir, exist_ok=True)

        # 如果 data.csv 不存在，创建带表头的空文件
        if not os.path.exists(self.data_file):
            with open(self.data_file, 'w', encoding='utf-8') as f:
                f.write("timestamp,sensor_id,data_type,value,unit,is_uploaded\n")

        # 如果 meta.json 不存在，创建它
        if not os.path.exists(self.meta_file):
            meta = {
                "session_id": self.session_id,
                "session_name": self.session_name,
                "created_at": datetime.now().isoformat(),
                "start_time": datetime.now().isoformat(),
                "end_time": None,
                "image_count": 0,
                "data_count": 0
            }
            with open(self.meta_file, 'w', encoding='utf-8') as f:
                json.dump(meta, f, ensure_ascii=False, indent=2)

        return self.batch_dir

    def add_data(self, sensor_id: str, data_type: str, value: str, unit: str = "", is_uploaded: bool = False):
        """添加传感器数据到 data.csv"""
        timestamp = datetime.now().isoformat()
        with open(self.data_file, 'a', encoding='utf-8') as f:
            f.write(f"{timestamp},{sensor_id},{data_type},{value},{unit},{is_uploaded}\n")

        # 更新 meta.json
        with open(self.meta_file, 'r', encoding='utf-8') as f:
            meta = json.load(f)
        meta["data_count"] += 1
        with open(self.meta_file, 'w', encoding='utf-8') as f:
            json.dump(meta, f, ensure_ascii=False, indent=2)

    def add_image(self, source_image_path: str, sensor_id: str) -> str:
        """复制图片到 images 目录"""
        ext = os.path.splitext(source_image_path)[1]
        timestamp = datetime.now().strftime('%Y%m%d%H%M%S')

        # 查找当前 sensor_id 下的图片数量
        existing = [f for f in os.listdir(self.images_dir) if f.startswith(f"sensor_{sensor_id}_")]
        img_count = len(existing) + 1

        dest_filename = f"sensor_{sensor_id}_{img_count:03d}{ext}"
        dest_path = os.path.join(self.images_dir, dest_filename)

        # 复制文件
        with open(source_image_path, 'rb') as src:
            with open(dest_path, 'wb') as dst:
                dst.write(src.read())

        # 更新 meta.json
        with open(self.meta_file, 'r', encoding='utf-8') as f:
            meta = json.load(f)
        meta["image_count"] += 1
        with open(self.meta_file, 'w', encoding='utf-8') as f:
            json.dump(meta, f, ensure_ascii=False, indent=2)

        return dest_filename

    def finish(self):
        """完成任务，更新 end_time"""
        with open(self.meta_file, 'r', encoding='utf-8') as f:
            meta = json.load(f)
        meta["end_time"] = datetime.now().isoformat()
        with open(self.meta_file, 'w', encoding='utf-8') as f:
            json.dump(meta, f, ensure_ascii=False, indent=2)


class StartTaskThread(QThread):
    """持续采集线程"""
    finished = pyqtSignal(dict)
    error = pyqtSignal(str)
    progress = pyqtSignal(int)  # 发送采集条数

    def __init__(self, session_id: str, session_name: str, base_dir: str, interval: float = 1.0):
        super().__init__()
        self.session_id = session_id
        self.session_name = session_name
        self.base_dir = base_dir
        self.interval = interval  # 采集间隔（秒）
        self.running = True
        self.collected_count = 0

    def stop(self):
        """停止采集"""
        self.running = False

    def run(self):
        try:
            # 创建批次目录结构
            collector = BatchCollector(self.session_id, self.session_name, self.base_dir)
            batch_dir = collector.create_structure()

            # 获取全局数据生成器
            generator = get_data_generator()

            while self.running:
                # 每次生成一条新数据并采集
                data = generator.generate()
                collector.add_data(
                    sensor_id=data["data_subtype"].value,
                    data_type=data["data_type"].value,
                    value=data["data_value"],
                    unit=data["unit"].value,
                    is_uploaded=False
                )
                self.collected_count += 1

                # 发送进度
                self.progress.emit(self.collected_count)

                # 等待下一个采集周期
                import time
                time.sleep(self.interval)

            # 完成任务
            collector.finish()

            self.finished.emit({
                "status": "success",
                "message": f"任务已完成，数据保存在: {batch_dir}",
                "batch_dir": batch_dir,
                "data_count": self.collected_count
            })
        except Exception as e:
            self.error.emit(str(e))


class TaskPage(QWidget):
    """任务执行页面"""
    def __init__(self, task: dict, main_window):
        super().__init__()
        self.task = task
        self.main_window = main_window
        self.thread = None # type: ignore
        self.is_running = False
        self.init_ui()

    def init_ui(self):
        layout = QVBoxLayout()
        layout.setContentsMargins(20, 20, 20, 20)

        # 标题栏：标题 + 返回按钮
        title_layout = QHBoxLayout()

        # 页面标题
        page_title = QLabel("任务执行")
        page_title.setStyleSheet("font-size: 20px; font-weight: 600; color: #2D2D2D;")
        title_layout.addWidget(page_title)

        title_layout.addStretch()

        # 返回按钮
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

        # 主体部分
        self.info_label = QLabel()
        self.info_label.setStyleSheet("font-size: 16px; padding: 10px;")
        layout.addWidget(self.info_label)

        # 状态显示
        self.status_label = QLabel("状态: 就绪")
        self.status_label.setStyleSheet("font-size: 14px; padding: 10px;")
        layout.addWidget(self.status_label)

        # 日志显示
        self.log_text = QTextEdit()
        self.log_text.setReadOnly(True)
        self.log_text.setStyleSheet("font-size: 12px;")
        layout.addWidget(self.log_text)

        # 开始按钮
        self.btn_start = QPushButton("开始执行")
        self.btn_start.setFixedHeight(40)
        self.btn_start.setMinimumWidth(120)
        self.btn_start.setStyleSheet("""
            QPushButton {
                font-size: 15px;
                padding: 8px 20px;
                background-color: #4CAF50;
                color: white;
                border: 2px solid #BDBDBD;
                border-radius: 4px;
            }
            QPushButton:hover { background-color: #45a049; }
        """)
        self.btn_start.clicked.connect(self.toggle_task)
        layout.addWidget(self.btn_start)

        self.setLayout(layout)
        self.update_task(self.task)

    def update_task(self, task):
        self.task = task
        task_id = task.get("id", "")
        task_name = task.get("mission_name", "未命名")
        task_desc = task.get("description", "")

        self.info_label.setText(f"任务名称: {task_name}\n任务描述: {task_desc}\nSession ID: {task_id}")
        self.status_label.setText("状态: 就绪")
        self.log_text.clear()
        self.is_running = False
        self.btn_start.setText("开始执行")
        self.btn_start.setFixedHeight(40)
        self.btn_start.setMinimumWidth(120)
        self.btn_start.setStyleSheet("""
            QPushButton {
                font-size: 15px;
                padding: 8px 20px;
                background-color: #4CAF50;
                color: white;
                border: 2px solid #BDBDBD;
                border-radius: 4px;
            }
            QPushButton:hover { background-color: #45a049; }
        """)
        self.btn_start.setEnabled(True)

    def toggle_task(self):
        if self.is_running:
            self.stop_task()
        else:
            self.start_task()

    def start_task(self):
        session_id = self.task.get("id", "")
        session_name = self.task.get("mission_name", "未命名")

        # 自动使用用户主目录下的 green_tracker_data
        base_dir = os.path.expanduser("~/green_tracker_data")

        self.is_running = True
        self.btn_start.setText("停止")
        self.btn_start.setFixedHeight(40)
        self.btn_start.setMinimumWidth(120)
        self.btn_start.setStyleSheet("""
            QPushButton {
                font-size: 15px;
                padding: 8px 20px;
                background-color: #f44336;
                color: white;
                border: 2px solid #BDBDBD;
                border-radius: 4px;
            }
            QPushButton:hover { background-color: #d32f2f; }
        """)
        self.status_label.setText("状态: 执行中...")
        self.log_text.append(f"正在启动任务...")
        self.log_text.append(f"数据将保存到: {base_dir}/{session_id}")
        self.log_text.append("开始持续采集数据...")

        self.thread = StartTaskThread(session_id, session_name, base_dir, interval=1.0) # type: ignore
        self.thread.finished.connect(self.on_task_finished) # type: ignore
        self.thread.error.connect(self.on_task_error) # type: ignore
        self.thread.progress.connect(self.on_progress) # type: ignore
        self.thread.start() # type: ignore

    def on_progress(self, count):
        """实时更新采集条数"""
        self.status_label.setText(f"状态: 采集 中... 已采集 {count} 条")

    def on_task_finished(self, result):
        self.is_running = False
        self.btn_start.setText("开始执行")
        self.btn_start.setFixedHeight(40)
        self.btn_start.setMinimumWidth(120)
        self.btn_start.setStyleSheet("""
            QPushButton {
                font-size: 15px;
                padding: 8px 20px;
                background-color: #4CAF50;
                color: white;
                border: 2px solid #BDBDBD;
                border-radius: 4px;
            }
            QPushButton:hover { background-color: #45a049; }
        """)
        self.btn_start.setEnabled(True)
        self.status_label.setText("状态: 已完成")
        self.log_text.append(f"任务执行完成")
        self.log_text.append(f"采集数据: {result.get('data_count', 0)} 条")
        self.log_text.append(f"数据目录: {result.get('batch_dir', '')}")

    def stop_task(self):
        """停止任务"""
        if self.thread and self.thread.isRunning(): # type: ignore
            self.thread.stop() # type: ignore
            self.thread.wait() # type: ignore
        self.is_running = False
        self.btn_start.setText("开始执行")
        self.btn_start.setFixedHeight(40)
        self.btn_start.setMinimumWidth(120)
        self.btn_start.setStyleSheet("""
            QPushButton {
                font-size: 15px;
                padding: 8px 20px;
                background-color: #4CAF50;
                color: white;
                border: 2px solid #BDBDBD;
                border-radius: 4px;
            }
            QPushButton:hover { background-color: #45a049; }
        """)
        self.status_label.setText("状态: 已停止")
        self.log_text.append("已停止采集，数据生成器继续运行")

    def on_task_error(self, error_msg):
        self.is_running = False
        self.btn_start.setText("开始执行")
        self.btn_start.setFixedHeight(40)
        self.btn_start.setMinimumWidth(120)
        self.btn_start.setStyleSheet("""
            QPushButton {
                font-size: 15px;
                padding: 8px 20px;
                background-color: #4CAF50;
                color: white;
                border: 2px solid #BDBDBD;
                border-radius: 4px;
            }
            QPushButton:hover { background-color: #45a049; }
        """)
        self.btn_start.setEnabled(True)
        self.status_label.setText("状态: 失败")
        self.log_text.append(f"错误: {error_msg}")
        QMessageBox.critical(self, "错误", f"任务执行失败: {error_msg}")

    def go_back(self):
        self.main_window.show_home_page()
