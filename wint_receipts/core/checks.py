"""Sanity checks on a reviewed receipt before upload."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from enum import StrEnum

from .models import ReceiptDraft, Recognition, ReferenceData

SWEDISH_VAT_RATES = {0.0, 6.0, 12.0, 25.0}
TOLERANCE = 0.02
REVIEWED_FIELDS = {"date", "total", "currency", "category_id", "vat"}  # AI fields shown on the form  # öre rounding


class Level(StrEnum):
    ERROR = "error"  # blocks upload
    WARNING = "warning"  # shown, does not block


@dataclass(frozen=True)
class Issue:
    level: Level
    field: str
    message: str


def check(
    draft: ReceiptDraft,
    reference: ReferenceData | None = None,
    recognition: Recognition | None = None,
    today: date | None = None,
) -> list[Issue]:
    today = today or date.today()
    issues: list[Issue] = []
    err = lambda f, m: issues.append(Issue(Level.ERROR, f, m))  # noqa: E731
    warn = lambda f, m: issues.append(Issue(Level.WARNING, f, m))  # noqa: E731

    if draft.date is None:
        err("date", "Date is missing")
    else:
        if draft.date > today:
            err("date", "Date is in the future")
        if reference and reference.lock_date and draft.date <= reference.lock_date:
            warn("date", f"Date is in a locked period (locked up to {reference.lock_date})")
        if (today - draft.date).days > 365:
            warn("date", "Receipt is more than a year old")

    if draft.amount is None:
        err("amount", "Amount is missing")
    elif draft.amount <= 0:
        err("amount", "Amount must be positive")

    if not draft.currency or len(draft.currency) != 3 or not draft.currency.isalpha():
        err("currency", "Currency must be a 3-letter code, e.g. SEK")

    if draft.category_id is None:
        err("category", "Category is not chosen")
    elif reference and draft.category_id not in {c.id for c in reference.categories}:
        err("category", "Category is not one of the company's receipt categories")

    if draft.payment_method_id is None:
        err("payment_method", "Payment method is not chosen")

    if not draft.pages:
        err("pages", "No page attached")

    for line in draft.vat:
        if line.rate not in SWEDISH_VAT_RATES and draft.currency == "SEK":
            warn("vat", f"Unusual VAT rate {line.rate:g} %")
        if line.net is not None and abs(line.net * line.rate / 100 - line.amount) > max(TOLERANCE, line.amount * 0.01):
            warn("vat", f"VAT {line.amount:.2f} is not {line.rate:g} % of {line.net:.2f}")
    if draft.amount is not None and draft.vat and all(v.net is not None for v in draft.vat):
        total = sum(v.net + v.amount for v in draft.vat)  # type: ignore[operator]
        if abs(total - draft.amount) > TOLERANCE:
            warn("amount", f"Net + VAT is {total:.2f}, not {draft.amount:.2f}")

    if recognition:
        for f in recognition.uncertain_fields:
            if f in REVIEWED_FIELDS:  # e.g. the supplier is read but not shown, so doubt about it doesn't matter
                warn(f, f"The AI wasn't sure about the {f.replace('_', ' ')} — check it against the image")

    return issues


def blocking(issues: list[Issue]) -> bool:
    return any(i.level is Level.ERROR for i in issues)
