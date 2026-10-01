from PySide6.QtWidgets import QDialog, QVBoxLayout

from .. import i18n
from . import sizing
from .focus_filter import FocusClearFilter


class OtherSettingsWindow(QDialog):

    def __init__(self, player):
        super().__init__(player)
        self.player = player
        i18n.title(self, "window.other_settings")
        self.setModal(False)

        self._focus_manager = FocusClearFilter(self)
        self.installEventFilter(self._focus_manager)

        # Stacked boxes keep the dialog narrow; the hint/falling rows inside
        # each box use two rows so nothing stretches the dialog sideways.
        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(10)

        layout.addWidget(player.key_output_box)
        layout.addWidget(player.macro_end_box)
        layout.addWidget(player.rhythm_hint_box)
        layout.addWidget(player.falling_notes_box)

        self.refit_to_content(grow_only=False)

    def refit_to_content(self, grow_only=True):
        """Re-measure the dialog; used after a language switch."""
        sizing.fit_window_to_content(self, grow_only=grow_only)
