from PySide6.QtCore import QEvent, QObject, Qt
from PySide6.QtWidgets import (
    QApplication, QCheckBox, QComboBox, QLineEdit, QListWidget, QPushButton,
    QTextEdit,
)


class FocusClearFilter(QObject):

    _KEEP_FOCUS = (
        QLineEdit, QComboBox, QPushButton, QCheckBox, QListWidget, QTextEdit,
    )

    def __init__(self, window):
        super().__init__(window)
        self._window = window

    def eventFilter(self, obj, event):
        if event.type() == QEvent.MouseButtonPress and event.button() == Qt.LeftButton:
            widget = QApplication.widgetAt(event.globalPos())
            if widget is not None and not isinstance(widget, self._KEEP_FOCUS):
                focus_widget = self._window.focusWidget()
                if focus_widget is not None:
                    focus_widget.clearFocus()
        return super().eventFilter(obj, event)
