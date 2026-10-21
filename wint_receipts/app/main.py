"""Entry point: `wint-receipts [file.pdf]`."""
from __future__ import annotations

import os
import sys
from pathlib import Path

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication

from ..core.config import Settings
from . import theme
from .fonts import apply_font_scale
from .main_window import MainWindow

SMOKE_TEST_ENV = "WINT_RECEIPTS_SMOKE_TEST"


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
    if os.environ.get(SMOKE_TEST_ENV):
        # scripts/smoke_test.py: prove the full UI starts, then exit 0 by ourselves. A crash
        # (or a windowed build's error dialog) never reaches this exit, so the test fails.
        QTimer.singleShot(3000, app.quit)
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
