"""Receipts already in Wint: server-side filters, sorting and paging, cached in the temp folder."""
from __future__ import annotations

import base64
import hashlib
import json
import os
import tempfile
import time
from datetime import date
from pathlib import Path
from typing import Any

from pydantic import BaseModel

from .wint import WintClient

PAGE_SIZE = 100
LIST_TTL = 600  # seconds

STATES = {0: "Received", 1: "Booked", 2: "Canceled", 3: "Waiting acceptance", 4: "Investigation",
          5: "Sent back", 6: "Sent back by admin", 7: "Payment sign", 8: "Stopped", 9: "Payout rescheduled",
          10: "Draft", 100: "Purchased", 101: "Paid"}
STATE_API_NAMES = {0: "Received", 1: "Booked", 2: "Canceled", 3: "WaitingAcceptance", 4: "Investigation",
                   5: "SentBackToCustomer", 6: "SentBackFromReceiptAdmin", 7: "PaymentSign", 8: "Stopped",
                   9: "PayoutRescheduled", 10: "Draft", 100: "Purchased", 101: "Paid"}
SORTABLE = {"serial": "SerialNumber", "date": "DateTime", "amount": "Amount", "category": "CategoryName",
            "state": "State", "updated": "LastUpdated"}


def cache_dir() -> Path:
    d = Path(tempfile.gettempdir()) / f"wint-receipts-{os.getuid() if hasattr(os, 'getuid') else 'user'}"
    d.mkdir(mode=0o700, parents=True, exist_ok=True)
    return d


class Query(BaseModel):
    date_from: date | None = None
    date_to: date | None = None
    states: list[int] = []
    category_id: int | None = None
    paid: bool | None = None
    amount_from: float | None = None
    amount_to: float | None = None
    sort: str = "date"
    descending: bool = True

    def params(self, page: int, size: int = PAGE_SIZE) -> dict[str, Any]:
        return {
            "CreatedFromDate": self.date_from.isoformat() if self.date_from else None,
            "CreatedToDate": self.date_to.isoformat() + "T23:59:59" if self.date_to else None,
            "States": [STATE_API_NAMES[s] for s in self.states] or None,
            "ReceiptCategoryId": self.category_id,
            "PaymentState": None if self.paid is None else ("Paid" if self.paid else "Unpaid"),
            "AmountFrom": self.amount_from, "AmountTo": self.amount_to,
            "OrderByProperty": SORTABLE[self.sort], "OrderByDescending": str(self.descending).lower(),
            "ThenByProperty": "SerialNumber", "ThenByDescending": str(self.descending).lower(),
            "Page": page, "NumPerPage": size,
        }


class Row(BaseModel):
    id: int
    serial: int | None = None
    date: str = ""
    amount: float = 0.0
    currency: str = ""
    category: str = ""
    payment_method: str = ""
    state: int | None = None
    paid: bool = False
    created_by: str = ""
    comment: str = ""
    intent: str = ""
    supplier: str = ""
    persons: list[str] = []
    attachments: list[tuple[int, str]] = []  # (id, content type)

    @property
    def state_name(self) -> str:
        return STATES.get(self.state, str(self.state)) if self.state is not None else ""

    @classmethod
    def from_api(cls, r: dict) -> Row:
        return cls(
            id=r["Id"], serial=r.get("SerialNumber"), date=str(r.get("DateTime") or "")[:10],
            amount=r.get("Amount") or 0.0, currency=r.get("Currency") or "", category=r.get("CategoryName") or "",
            payment_method=r.get("PaymentMethodName") or "", state=r.get("State"),
            paid=r.get("PaymentState") == 1,
            created_by=r.get("CreatedByPersonName") or "", comment=r.get("Comment") or "",
            intent=r.get("Intent") or "", supplier=r.get("SupplierName") or "",
            persons=[p.get("Name") or "" for p in r.get("Persons") or []],
            attachments=[(a["Id"], a.get("ContentType") or "") for a in r.get("Attachments") or [] if a.get("Id")],
        )

    def matches(self, text: str) -> bool:
        hay = " ".join([str(self.serial or ""), self.date, f"{self.amount:.2f}", self.currency, self.category,
                        self.payment_method, self.state_name, self.created_by, self.comment, self.intent,
                        self.supplier, *self.persons]).lower()
        return all(word in hay for word in text.lower().split())


class Page(BaseModel):
    rows: list[Row]
    total: int
    fetched_at: float


def _key(query: Query, page: int) -> str:
    return hashlib.sha256(json.dumps(query.params(page), sort_keys=True, default=str).encode()).hexdigest()[:24]


def fetch_page(client: WintClient, query: Query, page: int, use_cache: bool = True) -> Page:
    """One page of receipts (0-based); served from the cache while it's younger than LIST_TTL."""
    path = cache_dir() / f"list-{_key(query, page)}.json"
    if use_cache:
        try:
            cached = Page.model_validate_json(path.read_text(encoding="utf-8"))
            if time.time() - cached.fetched_at < LIST_TTL:
                return cached
        except (OSError, ValueError):
            pass
    data = client.receipts(**query.params(page)) or {}
    result = Page(rows=[Row.from_api(r) for r in data.get("Items") or []], total=data.get("TotalItems") or 0,
                  fetched_at=time.time())
    try:
        path.write_text(result.model_dump_json(), encoding="utf-8")
    except OSError:
        pass
    return result


def fetch_attachment(client: WintClient, receipt_id: int, attachment_id: int) -> Path:
    """The attachment as a file in the cache; attachments never change, so it never expires."""
    for path in cache_dir().glob(f"attachment-{receipt_id}-{attachment_id}.*"):
        return path
    data = client.get_json(f"/api/Receipt/{receipt_id}/Attachments/{attachment_id}", note="load attachment") or {}
    raw = base64.b64decode(data.get("Data") or "")
    if not raw:
        raise ValueError("Wint returned an empty attachment")
    ext = "pdf" if raw.startswith(b"%PDF") else "png" if raw.startswith(b"\x89PNG") else "jpg"
    path = cache_dir() / f"attachment-{receipt_id}-{attachment_id}.{ext}"
    tmp = path.with_suffix(".part")
    tmp.write_bytes(raw)
    tmp.replace(path)
    return path


def clear_cache() -> None:
    for p in cache_dir().glob("list-*.json"):
        p.unlink(missing_ok=True)
