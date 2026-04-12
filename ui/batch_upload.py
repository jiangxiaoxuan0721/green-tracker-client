"""
批量上传页面 - 检测并上传未上传的数据
"""
import os
import csv
import json
import threading
from datetime import datetime
from PyQt6.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QPushButton,
                             QLabel, QTextEdit, QProgressBar, QTableWidget,
                             QTableWidgetItem, QHeaderView, QMessageBox, QFrame)
from PyQt6.QtCore import pyqtSignal
from PyQt6.QtGui import QBrush, QColor


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


class UploadWorker(threading.Thread):
    """上传工作线程"""

    def __init__(self, session_id: str, data_dir: str, progress_callback, finished_callback):
        super().__init__(daemon=True)
        self.session_id = session_id
        self.data_dir = data_dir
        self.progress_callback = progress_callback
        self.finished_callback = finished_callback
        self.running = True
        # 图片上传状态文件
        self.image_status_file = os.path.join(data_dir, "images_status.json")

    def _load_image_status(self) -> dict:
        """加载图片上传状态"""
        if os.path.exists(self.image_status_file):
            try:
                with open(self.image_status_file, 'r', encoding='utf-8') as f:
                    return json.load(f)
            except Exception as e:
                print(f"加载图片状态失败: {e}")
        return {}

    def _save_image_status(self, status: dict):
        """保存图片上传状态"""
        try:
            with open(self.image_status_file, 'w', encoding='utf-8') as f:
                json.dump(status, f, ensure_ascii=False, indent=2)
        except Exception as e:
            print(f"保存图片状态失败: {e}")

    def run(self):
        results = {"success": 0, "failed": 0, "details": []}
        csv_file = os.path.join(self.data_dir, "data.csv")

        if not os.path.exists(csv_file):
            self.finished_callback(results)
            return

        # 读取CSV
        rows = []
        with open(csv_file, 'r', encoding='utf-8') as f:
            reader = csv.DictReader(f)
            rows = list(reader)

        # 只统计待上传的行
        pending_rows = []
        for row in rows:
            is_uploaded = row.get('is_uploaded', 'False').strip().lower() == 'true'
            if not is_uploaded:
                pending_rows.append(row)

        total = len(pending_rows)
        if total == 0:
            self.finished_callback(results)
            return

        # 只遍历待上传的行
        for i, row in enumerate(pending_rows):
            if not self.running:
                break

            try:
                # 上传数字数据
                from api.upload_numeric_data import upload_numeric_data
                result = upload_numeric_data(
                    session_id=self.session_id,
                    data_subtype=row['sensor_id'],
                    data_value=row['value'],
                    location_geom=None,
                    altitude_m=None,
                    heading=None
                )
                results["success"] += 1
                results["details"].append({
                    "type": "numeric",
                    "sensor_id": row['sensor_id'],
                    "value": row['value'],
                    "status": "success",
                    "time": datetime.now().strftime("%H:%M:%S")
                })
                # 标记为已上传
                row['is_uploaded'] = 'True'

            except Exception as e:
                results["failed"] += 1
                results["details"].append({
                    "type": "numeric",
                    "sensor_id": row['sensor_id'],
                    "value": row['value'],
                    "status": "failed",
                    "error": str(e),
                    "time": datetime.now().strftime("%H:%M:%S")
                })

            # 更新进度 - 使用实际处理的行数
            latest_detail = results["details"][-1] if results["details"] else {}
            self.progress_callback(i + 1, total, results["success"], results["failed"], latest_detail)

        # 保存更新后的CSV
        with open(csv_file, 'w', encoding='utf-8', newline='') as f:
            fieldnames = ['timestamp', 'sensor_id', 'data_type', 'value', 'unit', 'is_uploaded']
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            writer.writeheader()
            writer.writerows(rows)

        # 上传图片
        images_dir = os.path.join(self.data_dir, "images")
        if os.path.exists(images_dir) and self.running:
            # 加载图片上传状态
            image_status = self._load_image_status()

            image_files = [f for f in os.listdir(images_dir) if f.endswith(('.jpg', '.png', '.jpeg'))]

            # 只上传未标记为已上传的图片
            pending_images = [f for f in image_files if not image_status.get(f, {}).get("uploaded", False)]
            total_images = len(pending_images)

            for idx, img_file in enumerate(pending_images):
                if not self.running:
                    break
                try:
                    from api.upload_file_data import upload_file_data
                    img_path = os.path.join(images_dir, img_file)
                    # 根据文件名判断类型
                    subtype = "rgb"  # 默认
                    if "nir" in img_file.lower():
                        subtype = "nir"
                    elif "thermal" in img_file.lower():
                        subtype = "thermal"
                    elif "multi" in img_file.lower():
                        subtype = "multispectral"

                    result = upload_file_data(
                        file_path=img_path,
                        session_id=self.session_id,
                        data_subtype=subtype,
                        description=img_file
                    )
                    results["success"] += 1
                    results["details"].append({
                        "type": "file",
                        "file": img_file,
                        "status": "success",
                        "time": datetime.now().strftime("%H:%M:%S")
                    })
                    # 标记为已上传
                    image_status[img_file] = {
                        "uploaded": True,
                        "upload_time": datetime.now().isoformat()
                    }
                except Exception as e:
                    results["failed"] += 1
                    results["details"].append({
                        "type": "file",
                        "file": img_file,
                        "status": "failed",
                        "error": str(e),
                        "time": datetime.now().strftime("%H:%M:%S")
                    })

                latest_detail = results["details"][-1] if results["details"] else {}
                self.progress_callback(total + idx + 1, total + total_images, results["success"], results["failed"], latest_detail)

            # 保存图片上传状态
            self._save_image_status(image_status)

        self.finished_callback(results)

    def stop(self):
        self.running = False


class BatchUploadPage(QWidget):
    """批量上传页面"""

    # 定义信号
    progress_updated = pyqtSignal(int, int, int, int, dict)  # current, total, success, failed, latest_detail
    upload_finished = pyqtSignal(dict)  # results

    def __init__(self, task: dict, main_window):
        super().__init__()
        self.task = task
        self.main_window = main_window
        self.session_id = task.get("id", "")
        self.session_name = task.get("mission_name", "未命名")
        self.base_dir = os.path.expanduser("~/green_tracker_data")
        self.data_dir = os.path.join(self.base_dir, self.session_id)
        self.worker = None

        # 连接信号
        self.progress_updated.connect(self._on_progress_signal)
        self.upload_finished.connect(self._on_finished_signal)

        self.init_ui()
        self.scan_pending()

    def init_ui(self):
        self.setStyleSheet(f"background-color: {COLORS['bg']};")
        layout = QVBoxLayout()
        layout.setContentsMargins(16, 16, 16, 16)

        # 标题栏：标题 + 返回按钮
        title_layout = QHBoxLayout()

        title = QLabel(f"批量上传")
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

        # 扫描结果
        info_layout = QVBoxLayout()

        self.info_label = QLabel("正在扫描...")
        self.info_label.setStyleSheet(f"font-size: 13px; color: {COLORS['text_primary']}; font-weight: 500;")
        info_layout.addWidget(self.info_label)

        layout.addLayout(info_layout)

        # 进度区域
        progress_layout = QVBoxLayout()

        # 进度条
        self.progress_bar = QProgressBar()
        self.progress_bar.setStyleSheet(f"""
            QProgressBar {{
                border: none;
                background-color: {COLORS['bg']};
                border-radius: 2px;
                height: 6px;
                text-align: center;
            }}
            QProgressBar::chunk {{
                background-color: {COLORS['accent']};
                border-radius: 2px;
            }}
        """)
        progress_layout.addWidget(self.progress_bar)

        # 进度信息
        self.progress_label = QLabel("")
        self.progress_label.setStyleSheet(f"font-size: 11px; color: {COLORS['text_secondary']};")
        progress_layout.addWidget(self.progress_label)

        layout.addLayout(progress_layout)

        # 详情表格
        detail_label = QLabel("上传详情")
        detail_label.setStyleSheet(f"font-size: 13px; font-weight: 600; color: {COLORS['text_primary']};")
        layout.addWidget(detail_label)

        self.detail_table = QTableWidget()
        self.detail_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.detail_table.setColumnCount(5)
        self.detail_table.setHorizontalHeaderLabels(["时间", "类型", "内容", "状态", "详情"])
        self.detail_table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch) # type: ignore
        self.detail_table.setStyleSheet(f"""
            QTableWidget {{
                background-color: {COLORS['card']};
                font-size: 11px;
            }}
            QTableWidget::item {{
                padding: 4px;
            }}
            QHeaderView::section {{
                background-color: {COLORS['bg']};
                padding: 6px;
                border: none;
                font-weight: 500;
            }}
        """)
        self.detail_table.setMaximumHeight(250)
        layout.addWidget(self.detail_table)

        # 按钮 - 简洁风格
        btn_layout = QHBoxLayout()

        self.btn_scan = QPushButton("重新扫描")
        self.btn_scan.setFixedHeight(40)
        self.btn_scan.setMinimumWidth(100)
        self.btn_scan.setStyleSheet(f"""
            QPushButton {{
                font-size: 13px;
                padding: 6px 14px;
                background-color: {COLORS['card']};
                color: {COLORS['text_primary']};
                border: 2px solid {COLORS['border']};
                border-radius: 4px;
            }}
            QPushButton:hover {{ background-color: {COLORS['bg']}; }}
        """)
        self.btn_scan.clicked.connect(self.scan_pending)
        btn_layout.addWidget(self.btn_scan)

        self.btn_upload = QPushButton("开始上传")
        self.btn_upload.setFixedHeight(40)
        self.btn_upload.setMinimumWidth(100)
        self.btn_upload.setStyleSheet(f"""
            QPushButton {{
                font-size: 13px;
                padding: 6px 14px;
                background-color: {COLORS['accent']};
                color: white;
                border: 2px solid {COLORS['border']};
                border-radius: 4px;
            }}
            QPushButton:hover {{ background-color: {COLORS['accent_hover']}; }}
            QPushButton:disabled {{ background-color: {COLORS['muted']}; }}
        """)
        self.btn_upload.clicked.connect(self.start_upload)
        btn_layout.addWidget(self.btn_upload)

        self.btn_stop = QPushButton("停止")
        self.btn_stop.setFixedHeight(40)
        self.btn_stop.setMinimumWidth(90)
        self.btn_stop.setStyleSheet(f"""
            QPushButton {{
                font-size: 13px;
                padding: 6px 14px;
                background-color: {COLORS['danger']};
                color: white;
                border: 2px solid {COLORS['border']};
                border-radius: 4px;
            }}
            QPushButton:hover {{ background-color: #D74340; }}
        """)
        self.btn_stop.setEnabled(False)
        self.btn_stop.clicked.connect(self.stop_upload)
        btn_layout.addWidget(self.btn_stop)

        btn_layout.addStretch()
        layout.addLayout(btn_layout)

        self.setLayout(layout)

    def scan_pending(self):
        """扫描待上传数据"""
        self.detail_table.setRowCount(0)
        pending_numeric = 0
        pending_files = 0
        uploaded_numeric = 0
        uploaded_files = 0

        # 扫描CSV
        csv_file = os.path.join(self.data_dir, "data.csv")
        if os.path.exists(csv_file):
            with open(csv_file, 'r', encoding='utf-8') as f:
                reader = csv.DictReader(f)
                for row in reader:
                    is_uploaded = row.get('is_uploaded', 'False').strip().lower() == 'true'
                    if is_uploaded:
                        uploaded_numeric += 1
                    else:
                        pending_numeric += 1

        # 扫描图片
        images_dir = os.path.join(self.data_dir, "images")
        image_status_file = os.path.join(self.data_dir, "images_status.json")
        if os.path.exists(images_dir):
            image_files = [f for f in os.listdir(images_dir) if f.endswith(('.jpg', '.png', '.jpeg'))]

            # 加载图片上传状态
            image_status = {}
            if os.path.exists(image_status_file):
                try:
                    with open(image_status_file, 'r', encoding='utf-8') as f:
                        image_status = json.load(f)
                except Exception as e:
                    print(f"加载图片状态失败: {e}")

            # 统计待上传和已上传的图片
            for img_file in image_files:
                if image_status.get(img_file, {}).get("uploaded", False):
                    uploaded_files += 1
                else:
                    pending_files += 1

        total_pending = pending_numeric + pending_files
        self.info_label.setText(
            f"待上传: {total_pending} 项 (数字数据: {pending_numeric}, 图片: {pending_files})\n"
            f"已上传: {uploaded_numeric + uploaded_files} 项"
        )
        self.btn_upload.setEnabled(total_pending > 0)

    def start_upload(self):
        if not os.path.exists(self.data_dir):
            QMessageBox.warning(self, "警告", "数据目录不存在")
            return

        self.btn_scan.setEnabled(False)
        self.btn_upload.setEnabled(False)
        self.btn_stop.setEnabled(True)
        self.progress_bar.setValue(0)
        self.detail_table.setRowCount(0)

        self.worker = UploadWorker(
            self.session_id,
            self.data_dir,
            self.on_progress,
            self.on_finished
        )
        self.worker.start()

    def stop_upload(self):
        if self.worker:
            self.worker.stop()
        self.btn_scan.setEnabled(True)
        self.btn_upload.setEnabled(True)
        self.btn_stop.setEnabled(False)

    def on_progress(self, current, total, success, failed, latest_detail=None):
        # 发射信号到主线程（捕获可能的异常）
        try:
            self.progress_updated.emit(current, total, success, failed, latest_detail or {})
        except RuntimeError as e:
            # 页面已被删除，忽略错误
            print(f"进度更新失败（页面已关闭）: {e}")

    def _on_progress_signal(self, current: int, total: int, success: int, failed: int, latest_detail: dict):
        """在主线程中更新进度"""
        if total > 0:
            pct = int(current * 100 / total)
            self.progress_bar.setValue(pct)
        self.progress_label.setText(f"进度: {current}/{total} | 成功: {success} | 失败: {failed}")

        # 实时显示详情
        if latest_detail:
            row = self.detail_table.rowCount()
            self.detail_table.insertRow(row)
            self.detail_table.setItem(row, 0, QTableWidgetItem(latest_detail.get("time", "")))
            self.detail_table.setItem(row, 1, QTableWidgetItem(latest_detail.get("type", "")))

            if latest_detail.get("type") == "numeric":
                content = f"{latest_detail.get('sensor_id', '')}: {latest_detail.get('value', '')}"
            else:
                content = latest_detail.get("file", "")
            self.detail_table.setItem(row, 2, QTableWidgetItem(content))

            status = latest_detail.get("status", "")
            status_item = QTableWidgetItem("成功" if status == "success" else "失败")
            if status == "success":
                status_item.setBackground(QBrush(QColor("#c8e6c9")))
            else:
                status_item.setBackground(QBrush(QColor("#ffcdd2")))
            self.detail_table.setItem(row, 3, status_item)

            error = latest_detail.get("error", "")
            self.detail_table.setItem(row, 4, QTableWidgetItem(error))

            # 自动滚动到底部
            self.detail_table.scrollToBottom()

    def on_finished(self, results):
        # 发射信号到主线程（捕获可能的异常）
        try:
            self.upload_finished.emit(results)
        except RuntimeError as e:
            # 页面已被删除，忽略错误
            print(f"完成信号发送失败（页面已关闭）: {e}")

    def _on_finished_signal(self, results: dict):
        """在主线程中更新UI"""
        self.btn_scan.setEnabled(True)
        self.btn_upload.setEnabled(True)
        self.btn_stop.setEnabled(False)

        # 显示详情
        self.detail_table.setRowCount(0)
        details = results.get("details", [])

        if not details:
            self.detail_table.insertRow(0)
            self.detail_table.setItem(0, 0, QTableWidgetItem(""))
            self.detail_table.setItem(0, 1, QTableWidgetItem("无"))
            self.detail_table.setItem(0, 2, QTableWidgetItem("没有待上传的数据"))
            self.detail_table.setItem(0, 3, QTableWidgetItem(""))
            self.detail_table.setItem(0, 4, QTableWidgetItem(""))

        for detail in details:
            row = self.detail_table.rowCount()
            self.detail_table.insertRow(row)
            self.detail_table.setItem(row, 0, QTableWidgetItem(detail.get("time", "")))
            self.detail_table.setItem(row, 1, QTableWidgetItem(detail.get("type", "")))

            if detail.get("type") == "numeric":
                content = f"{detail.get('sensor_id', '')}: {detail.get('value', '')}"
            else:
                content = detail.get("file", "")
            self.detail_table.setItem(row, 2, QTableWidgetItem(content))

            status = detail.get("status", "")
            status_item = QTableWidgetItem("成功" if status == "success" else "失败")
            if status == "success":
                status_item.setBackground(QBrush(QColor("#c8e6c9")))
            else:
                status_item.setBackground(QBrush(QColor("#ffcdd2")))
            self.detail_table.setItem(row, 3, status_item)

            error = detail.get("error", "")
            self.detail_table.setItem(row, 4, QTableWidgetItem(error))



    def go_back(self):
        if self.worker and self.worker.is_alive():
            self.worker.stop()
        self.main_window.show_home_page()
