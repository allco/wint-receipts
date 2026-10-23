"""Every receipt uploaded to Wint, one JSON line each, never rewritten.

Survives deleted session files: when a PDF is opened again, its pages that are in the ledger are
shown as uploaded. It also catches the same receipt in a different scan (same date and amount).
"""
from __future__ import annotations

import json
import threading
from datetime import datetime, timezone
from pathlib import Path

from pydantic import BaseModel

_lock = threading.Lock()


class Entry(BaseModel):
    ts: str
    pdf_sha256: str
    pdf: str
    page: int  # 0-based
    client_id: str
    wint_receipt_id: int
    date: str | None
    amount: float | None
    currency: str
    supplier: str = ""
    org: str = ""


class Ledger:
    def __init__(self, path: Path):
        self.path = path

    def entries(self) -> list[Entry]:
        try:
            lines = self.path.read_text(encoding="utf-8").splitlines()
        except FileNotFoundError:
            return []
        out = []
        for line in lines:
            try:
                out.append(Entry.model_validate_json(line))
            except ValueError:
                continue  # a damaged line shouldn't hide the others
        return out

    def add(self, **fields) -> Entry:
        entry = Entry(ts=datetime.now(timezone.utc).isoformat(timespec="seconds"), **fields)
        with _lock:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            with self.path.open("a", encoding="utf-8") as f:
                f.write(entry.model_dump_json() + "\n")
        return entry

    def for_page(self, pdf_sha256: str, page: int) -> Entry | None:
        return next((e for e in reversed(self.entries()) if e.pdf_sha256 == pdf_sha256 and e.page == page), None)

    def same_receipt(self, date: str | None, amount: float | None, exclude_client_id: str = "") -> list[Entry]:
        """Uploads with the same date and amount (another scan of the same receipt, typically)."""
        if not date or amount is None:
            return []
        return [e for e in self.entries() if e.date == date and e.amount is not None
                and abs(e.amount - amount) < 0.005 and e.client_id != exclude_client_id]
