"""
bbox_visualizer.py — BBox 模式已合併入 translator.py。

啟動方式（與以前相同）：
    uv run bbox_visualizer.py

直接呼叫 translator.py 的主程式，並在 ROI 選取後自動進入 BBox 模式。
若想在執行中切換模式，請直接 `uv run translator.py`。
"""

import sys
from PyQt6.QtWidgets import QApplication
from translator import AppController, BBoxOverlay, VisControl
from config_manager import load_config


class BBoxOnlyController(AppController):
    """AppController subclass that always launches in BBox mode."""

    def launch_overlay(self, roi: tuple) -> None:
        if self.selector:
            self.selector.close()
        self._roi = roi
        config = load_config()
        self.overlay = BBoxOverlay(roi, config)
        self.overlay.show()
        self.control = VisControl(roi[0], roi[1])
        self.control.stop_requested.connect(self.show_selector)
        self.control.show()


if __name__ == "__main__":
    import signal
    signal.signal(signal.SIGINT, signal.SIG_DFL)

    app = QApplication(sys.argv)
    app.setQuitOnLastWindowClosed(False)
    controller = BBoxOnlyController()
    sys.exit(app.exec())
