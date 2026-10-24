"""Entry point: `wint-receipts [file.pdf]`."""
from __future__ import annotations

import argparse
import os
import sys
import traceback
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication

from ..core.config import Settings
from . import theme
from .fonts import apply_font_scale
from .main_window import MainWindow

SMOKE_TEST_ENV = "WINT_RECEIPTS_SMOKE_TEST"


def _version() -> str:
    try:
        return version("wint-receipts")
    except PackageNotFoundError:
        return "unknown"


def parse_args(argv: list[str]) -> tuple[argparse.Namespace, list[str]]:
    """Our options; anything else (e.g. Qt's -platform) is passed on to Qt."""
    parser = argparse.ArgumentParser(
        prog="wint-receipts",
        description="Scan receipts into one PDF; Claude AI reads each page; you check and upload them to Wint.")
    parser.add_argument("pdf", nargs="?", type=Path, help="PDF of scanned receipts to open")
    parser.add_argument("--version", action="version", version=f"%(prog)s {_version()}")
    args, qt_args = parser.parse_known_args(argv)
    if args.pdf is not None:
        if not args.pdf.is_file():
            parser.error(f"no such file: {args.pdf}")
        if args.pdf.suffix.lower() != ".pdf":
            parser.error(f"not a PDF: {args.pdf}")
        args.pdf = args.pdf.resolve()
    return args, qt_args


def main() -> int:
    args, qt_args = parse_args(sys.argv[1:])
    app = QApplication([sys.argv[0], *qt_args])
    app.setApplicationName("wint-receipts")
    app.setDesktopFileName("wint-receipts")
    theme.apply(app)
    settings = Settings.load()
    apply_font_scale(settings.font_scale)
    window = MainWindow(settings)
    window.log_event("app_started", version=_version(), platform=sys.platform,
                     pdf=str(args.pdf) if args.pdf else None)
    default_hook = sys.excepthook

    def crash(kind, value, tb):
        window.log_event("crash", error=f"{kind.__name__}: {value}",
                         traceback="".join(traceback.format_exception(kind, value, tb)))
        default_hook(kind, value, tb)

    sys.excepthook = crash
    window.show()
    if args.pdf:
        window.open_pdf(args.pdf)
    if os.environ.get(SMOKE_TEST_ENV):
        # scripts/smoke_test.py: prove the full UI starts, then exit 0 by ourselves. A crash
        # (or a windowed build's error dialog) never reaches this exit, so the test fails.
        QTimer.singleShot(3000, app.quit)
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
