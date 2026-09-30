# 先导入 config：它在导入期就把配置目录里的 .env 写进 os.environ，
# 后面的 ui / api / device 模块才能读到正确的 API_BASE_URL、SECRET_KEY 等。
import config  # noqa: F401

from ui.main_window import MainWindow
from PyQt6.QtWidgets import QApplication, QStyleFactory
from PyQt6.QtGui import QFont, QPalette, QColor
import sys

# 应用统一为浅色主题，与 ui 各页面的 COLORS 保持一致
_LIGHT_PALETTE = {
    QPalette.ColorRole.Window: "#FAFAFA",
    QPalette.ColorRole.WindowText: "#2D2D2D",
    QPalette.ColorRole.Base: "#FFFFFF",
    QPalette.ColorRole.AlternateBase: "#F5F5F5",
    QPalette.ColorRole.Text: "#2D2D2D",
    QPalette.ColorRole.Button: "#FFFFFF",
    QPalette.ColorRole.ButtonText: "#2D2D2D",
    QPalette.ColorRole.ToolTipBase: "#FFFFFF",
    QPalette.ColorRole.ToolTipText: "#2D2D2D",
    QPalette.ColorRole.Highlight: "#4A90A4",
    QPalette.ColorRole.HighlightedText: "#FFFFFF",
}


def _apply_light_theme(app: QApplication) -> None:
    """固定 Fusion 风格 + 浅色调色板。

    Windows 深色主题下 Qt 6.5+ 会直接采用系统深色 palette（前景为白色），
    而自定义样式表只写了浅色背景、部分控件未指定前景，就会出现白字白底；
    Linux 桌面默认浅色，所以此前一切正常。这里显式钉住浅色 palette，
    让系统主题不再影响未显式着色的控件（下拉列表、Tooltip、系统对话框等）。
    """
    if "Fusion" in QStyleFactory.keys():
        app.setStyle("Fusion")
    palette = app.palette()
    for role, color in _LIGHT_PALETTE.items():
        palette.setColor(role, QColor(color))
    app.setPalette(palette)


if __name__ == "__main__":
    app = QApplication(sys.argv)

    _apply_light_theme(app)

    font = QFont()
    font.setPointSize(12)
    app.setFont(font)

    window = MainWindow()
    window.show()
    sys.exit(app.exec())
