from PySide6.QtWidgets import QDialog, QGridLayout

from .. import i18n
from . import sizing


class KeyConfigWindow(QDialog):

    def __init__(self, player):
        super().__init__(player)
        self.player = player
        i18n.title(self, "window.key_config")
        self.setModal(False)

        # Output keys stay full width; the trigger and the offset box share a row.
        layout = QGridLayout(self)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setHorizontalSpacing(10)
        layout.setVerticalSpacing(10)

        layout.addWidget(player.output_keys_box, 0, 0, 1, 2)
        layout.addWidget(player.trigger_box, 1, 0)
        layout.addWidget(player.delay_box, 1, 1)
        layout.setColumnStretch(1, 1)

        self.refit_to_content(grow_only=False)

    def refit_to_content(self, grow_only=True):
        """Re-measure the dialog; used after a language switch."""
        sizing.fit_window_to_content(self, grow_only=grow_only)
