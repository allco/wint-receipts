"""Colours of the app design.

The app uses the Fusion style with this palette, so it looks the same on any desktop theme.
"""
from __future__ import annotations

from PySide6.QtGui import QColor, QPalette
from PySide6.QtWidgets import QApplication

from ..core.models import PageStatus

SURFACE_WINDOW = "#EFEFEF"
SURFACE_BASE = "#FFFFFF"
SURFACE_WARNING = "#FBEFC9"
SURFACE_ERROR = "#F8DADA"
BORDER = "#C9C9C9"
TEXT = "#1F1F1F"
TEXT_MUTED = "#6E6E6E"
TEXT_ON_ACCENT = "#FFFFFF"
ACCENT = "#308CC6"
ACCENT_HOVER = "#2878AB"  # accent darkened for hover; not a design variable
SURFACE_HOVER = "#E3E3E3"  # toolbar button hover; not a design variable
SURFACE_PRESSED = "#D6D6D6"
ILLUSTRATION_MUTED = "#B5B5B5"  # secondary shapes in the empty-state illustrations

STATUS = {
    PageStatus.NEW: "#9E9E9E",
    PageStatus.RECOGNIZING: "#1E88E5",
    PageStatus.NEEDS_REVIEW: "#F9A825",
    PageStatus.APPROVED: "#43A047",
    PageStatus.SKIPPED: "#757575",
    PageStatus.UPLOADING: "#1E88E5",
    PageStatus.UPLOADED: "#2E7D32",
    PageStatus.FAILED: "#E53935",
}
WARNING_TEXT = STATUS[PageStatus.NEEDS_REVIEW]
ERROR_TEXT = STATUS[PageStatus.FAILED]
OK_TEXT = STATUS[PageStatus.UPLOADED]

STYLE_SHEET = f"""
QPushButton {{
    background: {SURFACE_BASE}; color: {TEXT};
    border: 1px solid {BORDER}; border-radius: 5px; padding: 5px 14px;
}}
QPushButton:hover {{ background: {SURFACE_HOVER}; }}
QPushButton:pressed {{ background: {SURFACE_PRESSED}; }}
QPushButton:disabled {{ background: {SURFACE_WINDOW}; color: {TEXT_MUTED}; }}
QMenu {{ background: {SURFACE_BASE}; border: 1px solid {BORDER}; border-radius: 6px; padding: 4px; }}
QMenu::item {{ padding: 6px 28px 6px 14px; border-radius: 4px; color: {TEXT}; }}
QMenu::item:selected {{ background: {ACCENT}; color: {TEXT_ON_ACCENT}; }}
QMenu::item:disabled {{ color: {TEXT_MUTED}; background: transparent; }}
QMenu::separator {{ height: 1px; background: {BORDER}; margin: 4px 6px; }}
QPushButton#link {{ background: transparent; border: none; color: {ACCENT}; padding: 0 6px; text-decoration: underline; }}
QPushButton#primary {{
    background: {ACCENT}; color: {TEXT_ON_ACCENT};
    border: none; border-radius: 5px; padding: 6px 18px; font-weight: 600;
}}
QPushButton#primary:hover {{ background: {ACCENT_HOVER}; }}
QPushButton#primary:disabled {{ background: {BORDER}; color: {SURFACE_BASE}; }}
QListWidget#pages {{ border: none; }}
QListWidget#pages::item {{ padding: 6px 4px; }}
QListWidget#pages::item:selected {{ background: {ACCENT}; color: {TEXT_ON_ACCENT}; }}
QSplitter::handle {{ background: {BORDER}; }}
QToolBar {{
    background: {SURFACE_WINDOW}; border: none; border-bottom: 1px solid {BORDER};
    padding: 4px 6px; spacing: 2px;
}}
QToolBar::separator {{ background: {BORDER}; width: 1px; margin: 4px 6px; }}
QToolBar QToolButton {{
    background: transparent; border: 1px solid transparent; border-radius: 5px;
    padding: 4px 8px; color: {TEXT};
}}
QToolBar QToolButton:hover {{ background: {SURFACE_HOVER}; border-color: {BORDER}; }}
QToolBar QToolButton:pressed {{ background: {SURFACE_PRESSED}; }}
QToolBar QToolButton:disabled {{ color: {TEXT_MUTED}; }}
"""


def palette() -> QPalette:
    p = QPalette()
    roles = {
        QPalette.ColorRole.Window: SURFACE_WINDOW,
        QPalette.ColorRole.WindowText: TEXT,
        QPalette.ColorRole.Base: SURFACE_BASE,
        QPalette.ColorRole.AlternateBase: SURFACE_WINDOW,
        QPalette.ColorRole.Text: TEXT,
        QPalette.ColorRole.PlaceholderText: TEXT_MUTED,
        QPalette.ColorRole.Button: SURFACE_BASE,
        QPalette.ColorRole.ButtonText: TEXT,
        QPalette.ColorRole.BrightText: TEXT_ON_ACCENT,
        QPalette.ColorRole.Highlight: ACCENT,
        QPalette.ColorRole.HighlightedText: TEXT_ON_ACCENT,
        QPalette.ColorRole.Link: ACCENT,
        QPalette.ColorRole.ToolTipBase: SURFACE_BASE,
        QPalette.ColorRole.ToolTipText: TEXT,
        QPalette.ColorRole.Light: SURFACE_BASE,
        QPalette.ColorRole.Midlight: SURFACE_WINDOW,
        QPalette.ColorRole.Mid: BORDER,
        QPalette.ColorRole.Dark: BORDER,
        QPalette.ColorRole.Shadow: TEXT_MUTED,
    }
    for role, color in roles.items():
        p.setColor(role, QColor(color))
    for role in (QPalette.ColorRole.WindowText, QPalette.ColorRole.Text, QPalette.ColorRole.ButtonText):
        p.setColor(QPalette.ColorGroup.Disabled, role, QColor(TEXT_MUTED))
    p.setColor(QPalette.ColorGroup.Disabled, QPalette.ColorRole.Button, QColor(SURFACE_WINDOW))
    return p


def apply(app: QApplication) -> None:
    app.setStyle("Fusion")
    app.setPalette(palette())
