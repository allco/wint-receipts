"""Data models shared by recognition, review and upload."""
from __future__ import annotations

import datetime
import uuid
from datetime import date
from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, Field


class PageKind(StrEnum):
    RECEIPT = "receipt"
    CONTINUATION = "continuation"  # second page of the receipt on the previous page
    BLANK = "blank"
    BACK_SIDE = "back_side"
    NOT_A_RECEIPT = "not_a_receipt"


class Person(BaseModel):
    """Someone from the Wint receipt address book, e.g. a guest on a representation receipt."""

    id: int
    name: str
    company: str = ""


class VatLine(BaseModel):
    rate: float  # percent, e.g. 25
    net: float | None = None
    amount: float


class Recognition(BaseModel):
    """What the claude CLI returns for one page. Mirrors RECOGNITION_SCHEMA in recognize.py."""

    page_kind: PageKind
    date: str | None = None  # YYYY-MM-DD
    total: float | None = None  # amount paid, incl. VAT
    currency: str | None = None  # ISO 4217
    supplier_name: str | None = None
    supplier_org_number: str | None = None
    vat: list[VatLine] = Field(default_factory=list)
    category_id: int | None = None
    payment_hint: Literal["card", "cash", "swish", "invoice", "unknown"] = "unknown"
    uncertain_fields: list[str] = Field(default_factory=list)
    notes: str = ""
    rotation_needed: int = 0  # clockwise turn the AI says the image it saw needs to read upright


class PageStatus(StrEnum):
    NEW = "new"
    RECOGNIZING = "recognizing"
    NEEDS_REVIEW = "needs_review"
    APPROVED = "approved"
    SKIPPED = "skipped"
    UPLOADING = "uploading"
    UPLOADED = "uploaded"
    FAILED = "failed"


class ReceiptDraft(BaseModel):
    """The reviewed, editable values that become a Wint receipt."""

    # datetime.date, not date: the field name shadows the type inside the class body.
    date: datetime.date | None = None
    amount: float | None = None
    currency: str = "SEK"
    supplier_name: str = ""  # internal: matches AI learnings; not shown on the form or sent to Wint
    category_id: int | None = None
    payment_method_id: int | None = None
    vat: list[VatLine] = Field(default_factory=list)
    persons: list[Person] = Field(default_factory=list)  # participants of a representation receipt
    # Pages of the source PDF attached to this receipt (0-based). Normally just the page itself;
    # continuation pages get merged into the receipt before them.
    pages: list[int] = Field(default_factory=list)

    @classmethod
    def from_recognition(cls, rec: Recognition, page: int, default_payment_method: int | None) -> ReceiptDraft:
        parsed: date | None = None
        if rec.date:
            try:
                parsed = date.fromisoformat(rec.date)
            except ValueError:
                parsed = None
        return cls(
            date=parsed,
            amount=rec.total,
            currency=(rec.currency or "SEK").upper(),
            supplier_name=rec.supplier_name or "",
            category_id=rec.category_id,
            payment_method_id=default_payment_method,
            vat=rec.vat,
            pages=[page],
        )


class PageState(BaseModel):
    index: int  # 0-based page number in the PDF
    status: PageStatus = PageStatus.NEW
    recognition: Recognition | None = None
    draft: ReceiptDraft | None = None
    # Stable per receipt; sent as ClientId so a retried upload can be detected in Wint.
    client_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    wint_receipt_id: int | None = None
    error: str | None = None
    recognition_cost_usd: float | None = None
    # Removed from the review by the user (the PDF itself is untouched); can be restored.
    deleted: bool = False
    # Clockwise turn (0/90/180/270) applied when showing, reading and uploading the page; the PDF is untouched.
    rotation: int = 0


class Session(BaseModel):
    """Everything about one source PDF; saved next to it as <name>.wint.json."""

    version: int = 1
    pdf_path: str
    pdf_sha256: str
    pages: list[PageState]


class Category(BaseModel):
    id: int
    name: str


class PaymentMethod(BaseModel):
    id: int
    name: str
    type: int | None = None  # ReceiptPaymentMethodType integer as returned by Wint


class ReferenceData(BaseModel):
    company_id: int
    company_name: str
    categories: list[Category]
    payment_methods: list[PaymentMethod]
    lock_date: date | None = None
    no_vat: bool = False
    # The receipt address book: the most used people first (Wint's "common" list), then the rest by name.
    persons: list[Person] = Field(default_factory=list)
    common_person_ids: list[int] = Field(default_factory=list)
