from ui.main_window import MainWindow
from PyQt6.QtWidgets import QApplication
from PyQt6.QtGui import QFont
import sys

if __name__ == "__main__":
    app = QApplication(sys.argv)

    # 设置字体（带回退机制）
    font = QFont()
    font.setPointSize(12)
    app.setFont(font)

    window = MainWindow()
    window.show()
    sys.exit(app.exec())
