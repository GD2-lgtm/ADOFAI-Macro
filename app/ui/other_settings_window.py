from PySide6.QtWidgets import QDialog, QVBoxLayout

from .focus_filter import FocusClearFilter


class OtherSettingsWindow(QDialog):

    def __init__(self, player):
        super().__init__(player)
        self.player = player
        self.setWindowTitle("其他设置")
        self.setModal(False)

        self._focus_manager = FocusClearFilter(self)
        self.installEventFilter(self._focus_manager)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(10)

        layout.addWidget(player.key_output_box)
        layout.addWidget(player.macro_end_box)
        layout.addWidget(player.rhythm_hint_box)
        layout.addWidget(player.falling_notes_box)

        self.adjustSize()
        size_hint = self.sizeHint()
        self.setFixedSize(size_hint.width() + 12, size_hint.height() + 8)
