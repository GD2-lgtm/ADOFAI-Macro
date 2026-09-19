import sys

from PyQt5.QtCore import Qt
from PyQt5.QtGui import QFont
from PyQt5.QtWidgets import QApplication

from app import console
from app.ui.main_window import ADOFAIPlayer, APP_QSS

ENABLE_PARSE_LOG = False


def main():
    console.init()

    QApplication.setAttribute(Qt.AA_EnableHighDpiScaling, True)
    QApplication.setAttribute(Qt.AA_UseHighDpiPixmaps, True)

    app = QApplication(sys.argv)
    app.setQuitOnLastWindowClosed(True)
    app.setStyle("Fusion")
    app.setFont(QFont("Microsoft YaHei", 10))
    app.setStyleSheet(APP_QSS)

    window = ADOFAIPlayer(enable_parse_log=ENABLE_PARSE_LOG)
    window.show()

    sys.exit(app.exec_())


if __name__ == "__main__":
    main()
