import signal
import sys

from PyQt6.QtWidgets import QApplication
from translator import AppController


def main():
    signal.signal(signal.SIGINT, signal.SIG_DFL)
    app = QApplication(sys.argv)
    app.setQuitOnLastWindowClosed(False)
    controller = AppController()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
