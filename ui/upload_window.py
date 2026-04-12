from PyQt6.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QPushButton, QLabel,
                             QComboBox, QLineEdit, QFileDialog, QTextEdit, QMessageBox)
from PyQt6.QtCore import QThread, pyqtSignal
from api import upload_numeric_data, upload_file_data


class UploadDataThread(QThread):
    finished = pyqtSignal(dict)
    error = pyqtSignal(str)

    def __init__(self, data_type: str, **kwargs):
        super().__init__()
        self.data_type = data_type
        self.kwargs = kwargs

    def run(self):
        try:
            if self.data_type == "numeric":
                result = upload_numeric_data(**self.kwargs)
            else:
                result = upload_file_data(**self.kwargs)
            self.finished.emit(result)
        except Exception as e:
            self.error.emit(str(e))


class UploadPage(QWidget):
    """上传数据页面"""
    def __init__(self, task: dict, main_window):
        super().__init__()
        self.task = task
        self.main_window = main_window
        self.thread = None # type: ignore
        self.selected_file = None
        self.label_file_path = None
        self.init_ui()

    def init_ui(self):
        # 下拉框样式 - 提高对比度
        self.setStyleSheet("""
            QComboBox {
                background-color: #FFFFFF;
                color: #2D2D2D;
                border: 2px solid #BDBDBD;
                border-radius: 4px;
                padding: 4px 8px;
                font-size: 13px;
            }
            QComboBox:hover {
                border-color: #4A90A4;
            }
            QComboBox::drop-down {
                border: none;
                width: 20px;
            }
            QComboBox::down-arrow {
                width: 12px;
                height: 12px;
            }
            QComboBox QAbstractItemView {
                background-color: #FFFFFF;
                color: #2D2D2D;
                selection-background-color: #4A90A4;
                selection-color: #FFFFFF;
                border: 1px solid #BDBDBD;
            }
            QLineEdit {
                background-color: #FFFFFF;
                color: #2D2D2D;
                border: 2px solid #BDBDBD;
                border-radius: 4px;
                padding: 4px 8px;
                font-size: 13px;
            }
            QLineEdit:hover {
                border-color: #4A90A4;
            }
            QLineEdit:focus {
                border-color: #4A90A4;
            }
        """)

        layout = QVBoxLayout()
        layout.setContentsMargins(20, 20, 20, 20)

        # 标题栏：标题 + 返回按钮
        title_layout = QHBoxLayout()

        # 页面标题
        page_title = QLabel("上传数据")
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
        self.info_label.setStyleSheet("font-size: 14px; padding: 5px;")
        layout.addWidget(self.info_label)

        # 选择数据类型
        type_layout = QHBoxLayout()
        type_layout.addWidget(QLabel("数据类型:"))
        self.combo_type = QComboBox()
        self.combo_type.setFixedHeight(36)
        self.combo_type.addItems(["数字数据", "文件数据"])
        self.combo_type.currentTextChanged.connect(self.on_type_changed)
        type_layout.addWidget(self.combo_type)
        layout.addLayout(type_layout)

        # 数字数据选项
        self.numeric_widget = QWidget()
        numeric_layout = QVBoxLayout()

        subtype_layout = QHBoxLayout()
        subtype_layout.addWidget(QLabel("数据子类型:"))
        self.combo_subtype = QComboBox()
        self.combo_subtype.setFixedHeight(36)
        self.combo_subtype.addItems(["temperature", "humidity", "co2", "light", "pressure",
                                     "moisture", "ph", "ec", "temperature_soil"])
        subtype_layout.addWidget(self.combo_subtype)
        numeric_layout.addLayout(subtype_layout)

        value_layout = QHBoxLayout()
        value_layout.addWidget(QLabel("数据值:"))
        self.edit_value = QLineEdit()
        self.edit_value.setPlaceholderText("输入数值")
        value_layout.addWidget(self.edit_value)
        numeric_layout.addLayout(value_layout)

        self.numeric_widget.setLayout(numeric_layout)
        layout.addWidget(self.numeric_widget)

        # 文件数据选项
        self.file_widget = QWidget()
        file_layout = QVBoxLayout()

        file_btn_layout = QHBoxLayout()
        file_btn_layout.addWidget(QLabel("选择文件:"))
        self.btn_select_file = QPushButton("浏览...")
        self.btn_select_file.setFixedHeight(40)
        self.btn_select_file.setMinimumWidth(90)
        self.btn_select_file.setStyleSheet("""
            QPushButton {
                font-size: 13px;
                padding: 6px 12px;
                background-color: #FFFFFF;
                color: #2D2D2D;
                border: 2px solid #BDBDBD;
                border-radius: 4px;
            }
            QPushButton:hover { background-color: #F5F5F5; }
        """)
        self.btn_select_file.clicked.connect(self.select_file)
        file_btn_layout.addWidget(self.btn_select_file)
        self.label_file_path = QLabel("未选择文件")
        file_btn_layout.addWidget(self.label_file_path)
        file_btn_layout.addStretch()
        file_layout.addLayout(file_btn_layout)

        subtype_file_layout = QHBoxLayout()
        subtype_file_layout.addWidget(QLabel("数据子类型:"))
        self.combo_subtype_file = QComboBox()
        self.combo_subtype_file.setFixedHeight(36)
        self.combo_subtype_file.addItems(["rgb", "nir", "red_edge", "thermal", "multispectral", "video"])
        subtype_file_layout.addWidget(self.combo_subtype_file)
        file_layout.addLayout(subtype_file_layout)

        self.file_widget.setLayout(file_layout)
        self.file_widget.hide()
        layout.addWidget(self.file_widget)

        # 描述输入
        desc_layout = QHBoxLayout()
        desc_layout.addWidget(QLabel("描述:"))
        self.edit_desc = QLineEdit()
        self.edit_desc.setPlaceholderText("可选描述")
        desc_layout.addWidget(self.edit_desc)
        layout.addLayout(desc_layout)

        # 上传按钮
        self.btn_upload = QPushButton("上传数据")
        self.btn_upload.setFixedHeight(40)
        self.btn_upload.setMinimumWidth(120)
        self.btn_upload.setStyleSheet("""
            QPushButton {
                font-size: 15px;
                padding: 8px 20px;
                background-color: #FF9800;
                color: white;
                border: 2px solid #BDBDBD;
                border-radius: 4px;
            }
            QPushButton:hover { background-color: #F57C00; }
        """)
        self.btn_upload.clicked.connect(self.upload_data)
        layout.addWidget(self.btn_upload)

        # 日志显示
        self.log_text = QTextEdit()
        self.log_text.setReadOnly(True)
        self.log_text.setStyleSheet("font-size: 12px;")
        layout.addWidget(self.log_text)

        self.setLayout(layout)
        self.on_type_changed("数字数据")
        self.update_task(self.task)

    def update_task(self, task):
        self.task = task
        task_name = task.get("mission_name", "未命名")
        task_id = task.get("id", "")
        self.info_label.setText(f"任务: {task_name}\nSession ID: {task_id}")

    def on_type_changed(self, text):
        if text == "数字数据":
            self.numeric_widget.show()
            self.file_widget.hide()
        else:
            self.numeric_widget.hide()
            self.file_widget.show()

    def select_file(self):
        file_path, _ = QFileDialog.getOpenFileName(self, "选择文件", "", "Images (*.png *.jpg *.jpeg *.bmp *.gif);;All Files (*)")
        if file_path:
            self.selected_file = file_path
            self.label_file_path.setText(file_path.split("/")[-1]) # type: ignore

    def upload_data(self):
        session_id = self.task.get("id", "")
        description = self.edit_desc.text() or None

        if self.combo_type.currentText() == "数字数据":
            data_subtype = self.combo_subtype.currentText()
            data_value = self.edit_value.text()

            if not data_value:
                QMessageBox.warning(self, "警告", "请输入数据值")
                return

            self.btn_upload.setEnabled(False)
            self.log_text.append(f"正在上传数字数据 ({data_subtype})...")

            self.thread = UploadDataThread(
                "numeric",
                session_id=session_id,
                data_subtype=data_subtype,
                data_value=data_value,
                description=description
            ) # type: ignore
        else:
            if not self.selected_file:
                QMessageBox.warning(self, "警告", "请选择文件")
                return

            data_subtype = self.combo_subtype_file.currentText()

            self.btn_upload.setEnabled(False)
            self.log_text.append(f"正在上传文件数据 ({data_subtype})...")

            self.thread = UploadDataThread(
                "file",
                file_path=self.selected_file,
                session_id=session_id,
                data_subtype=data_subtype,
                description=description
            ) # type: ignore

        self.thread.finished.connect(self.on_upload_finished) # type: ignore
        self.thread.error.connect(self.on_upload_error) # type: ignore
        self.thread.start() # type: ignore

    def on_upload_finished(self, result):
        self.btn_upload.setEnabled(True)
        self.log_text.append(f"上传成功: {result}")
        QMessageBox.information(self, "成功", "数据上传成功")

    def on_upload_error(self, error_msg):
        self.btn_upload.setEnabled(True)
        self.log_text.append(f"上传失败: {error_msg}")
        QMessageBox.critical(self, "错误", f"上传失败: {error_msg}")

    def go_back(self):
        self.main_window.show_home_page()
