"""Shared helper for sizing a window to its contents.

Qt computes ``sizeHint`` lazily: changing a widget's text only *posts* a
``LayoutRequest`` event, so reading ``sizeHint()`` immediately afterwards
returns the previous value.  Refreshing every nested layout explicitly (group
boxes own their own layouts, so the window layout alone is not enough) gives a
reliable measurement right away.

Typical use: every window exposes ``refit_to_content()`` and the language
switch calls it after retranslating the widgets.
"""

from PySide6.QtWidgets import QWidget

WINDOW_PAD_W = 14
WINDOW_PAD_H = 10


def refresh_layouts(window):
    """Force *window* and every descendant widget to re-measure its layout."""
    for widget in [window, *window.findChildren(QWidget)]:
        layout = widget.layout()
        if layout is None:
            continue
        layout.invalidate()
        layout.activate()


def content_size(window, passes=2):
    """Return the ``(width, height)`` *window* needs for its contents."""
    for _ in range(max(1, passes)):
        refresh_layouts(window)
        window.adjustSize()
    hint = window.sizeHint()
    return hint.width(), hint.height()


def fit_window_to_content(window, grow_only=False,
                          pad_w=WINDOW_PAD_W, pad_h=WINDOW_PAD_H):
    """Resize *window* so that its contents fit.

    With ``grow_only`` the window is never shrunk, so a window the user
    enlarged keeps its size when the language changes back.
    """
    width, height = content_size(window)
    width += pad_w
    height += pad_h
    window.setMinimumSize(width, height)
    if grow_only:
        current = window.size()
        width = max(current.width(), width)
        height = max(current.height(), height)
    window.resize(width, height)
    return width, height
