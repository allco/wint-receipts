"""Recognition log: one JSON line per recognition attempt and per approval.

Events:
  recognized — claude returned fields (with model, timing, cost, tokens and the full recognition)
  failed     — recognition errored
  approved   — the user approved a receipt; the final values and which fields differ from claude's
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
        "supplier_name": (rec.supplier_name or "", draft.supplier_name),
        "description": (rec.description or "", draft.comment),
        "category_id": (rec.category_id, draft.category_id),
    }
    def differs(a, b) -> bool:
        if isinstance(a, float) and isinstance(b, float):
            return abs(a - b) > 0.005
        return a != b

    return [name for name, (a, b) in pairs.items() if differs(a, b)]
