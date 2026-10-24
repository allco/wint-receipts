"""Background jobs. Workers never touch the Session; they report results through signals
and the main window applies them on the UI thread."""
from __future__ import annotations

import traceback
from collections.abc import Callable
from typing import Any

from PySide6.QtCore import QObject, QRunnable, Signal

on_error: Callable[[Any, str, str], None] | None = None  # (tag, message, traceback), called from the worker thread


class JobSignals(QObject):
    done = Signal(object, object)  # (tag, result)
    failed = Signal(object, str)  # (tag, message)


class Job(QRunnable):
    """Runs fn() in the thread pool; `tag` identifies the job to the receiver (e.g. page index)."""

    def __init__(self, tag: Any, fn: Callable[[], Any]):
        super().__init__()
        self.tag = tag
        self.fn = fn
        self.signals = JobSignals()

    def run(self) -> None:
        try:
            result = self.fn()
        except Exception as e:  # noqa: BLE001 - reported to the UI
            msg = str(e) or type(e).__name__
            traceback.print_exc()
            if on_error is not None:
                try:
                    on_error(self.tag, msg, traceback.format_exc())
                except Exception:  # noqa: BLE001 - logging must never break the job
                    pass
            self._emit(self.signals.failed, msg)
        else:
            self._emit(self.signals.done, result)

    def _emit(self, signal, value: Any) -> None:
        try:
            signal.emit(self.tag, value)
        except RuntimeError:
            pass  # the app quit while the job ran; its signals object is gone and nobody is listening
