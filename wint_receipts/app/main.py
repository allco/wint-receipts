"""Entry point: `wint-receipts [file.pdf]`."""
from __future__ import annotations

import sys
from pathlib import Path

from PySide6.QtWidgets import QApplication

from ..core.config import Settings
from . import theme
from .fonts import apply_font_scale
from .main_window import MainWindow


def main() -> int:
    app = QApplication(sys.argv)
    app.setApplicationName("wint-receipts")
    app.setDesktopFileName("wint-receipts")
    theme.apply(app)
    settings = Settings.load()
    apply_font_scale(settings.font_scale)
    window = MainWindow(settings)
    window.show()
    args = [a for a in app.arguments()[1:] if not a.startswith("-")]
    if args:
        window.open_pdf(Path(args[0]))
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
