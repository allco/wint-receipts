"""Application-wide font scaling that can change while the app runs."""
from __future__ import annotations

from PySide6.QtGui import QFont
from PySide6.QtWidgets import QApplication

PRESETS = [round(0.5 + 0.1 * i, 1) for i in range(16)]  # 0.5 … 2.0
_base: QFont | None = None  # the system font before any scaling


def apply_font_scale(scale: float) -> None:
    """Set the app font to the system font × scale. Widgets without their own font update at once."""
    global _base
    app = QApplication.instance()
    if app is None:
        return
    if _base is None:
        _base = QFont(app.font())
    font = QFont(_base)
    font.setPointSizeF(_base.pointSizeF() * scale)
    app.setFont(font)
    # Widgets under a style sheet keep the font resolved when the sheet was applied and ignore
    # app.setFont; re-applying the sheet makes them pick up the new size.
    for w in app.topLevelWidgets():
        if w.styleSheet():
            w.setStyleSheet(w.styleSheet())
