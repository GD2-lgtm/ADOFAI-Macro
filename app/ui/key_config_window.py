from PySide6.QtWidgets import QDialog, QVBoxLayout


class KeyConfigWindow(QDialog):

    def __init__(self, player):
        super().__init__(player)
        self.player = player
        self.setWindowTitle("按键配置")
        self.setModal(False)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(10)

        layout.addWidget(player.output_keys_box)
        layout.addWidget(player.trigger_box)
        layout.addWidget(player.delay_box)

        self.adjustSize()
        size_hint = self.sizeHint()
        self.setFixedSize(size_hint.width() + 12, size_hint.height() + 8)
