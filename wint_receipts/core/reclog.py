"""The app's event log (recognition.log): one JSON line per event, good news and errors alike.

Events:
  app_started, app_closed
  pdf_opened, open_failed
  wint_data_loaded, wint_data_failed
  recognized — claude returned fields (with model, timing, cost, tokens and the full recognition)
  failed     — recognition errored
  approved   — the user approved a receipt; the final values and which fields differ from claude's
  upload_started, uploaded, upload_duplicate, upload_failed, upload_finished
  error      — anything else that went wrong, with a traceback when there is one
  crash      — an unhandled exception
"""
from __future__ import annotations

import json
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .models import ReceiptDraft, Recognition

_lock = threading.Lock()


def now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def write(path: Path | None, entry: dict[str, Any]) -> None:
    if not path:
        return
    line = json.dumps({"ts": now(), **entry}, ensure_ascii=False, default=str)
    path.parent.mkdir(parents=True, exist_ok=True)
    with _lock, path.open("a", encoding="utf-8") as f:
        f.write(line + "\n")


def changed_fields(rec: Recognition | None, draft: ReceiptDraft) -> list[str]:
    """Fields where the approved value differs from what claude read."""
    if rec is None:
        return []
    pairs = {
        "date": (rec.date, draft.date.isoformat() if draft.date else None),
        "total": (rec.total, draft.amount),
        "currency": ((rec.currency or "").upper() or None, draft.currency or None),
        "category_id": (rec.category_id, draft.category_id),
    }
    def differs(a, b) -> bool:
        if isinstance(a, float) and isinstance(b, float):
            return abs(a - b) > 0.005
        return a != b

    return [name for name, (a, b) in pairs.items() if differs(a, b)]
