import multiprocessing
import sys

from PySide6.QtGui import QFont
from PySide6.QtWidgets import QApplication

from app import console
from app.ui.main_window import ADOFAIPlayer, APP_QSS

ENABLE_PARSE_LOG = False


def main():
    multiprocessing.freeze_support()
    console.init()

    app = QApplication(sys.argv)
    app.setQuitOnLastWindowClosed(True)
    app.setStyle("Fusion")
    app.setFont(QFont("Microsoft YaHei", 10))
    app.setStyleSheet(APP_QSS)

    window = ADOFAIPlayer(enable_parse_log=ENABLE_PARSE_LOG)
    window.show()

    sys.exit(app.exec())


if __name__ == "__main__":
    main()
