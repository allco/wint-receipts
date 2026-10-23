"""Upload one reviewed page (or merged pages) as a Wint receipt."""
from __future__ import annotations

from pathlib import Path

from . import pdf
from .models import PageState, PageStatus
from .wint import Attachment, WintClient


def build_attachments(pdf_path: Path, pages: list[int], rotations: dict[int, int] | None = None,
                      fmt: str = "jpeg") -> list[Attachment]:
    """The receipt's page(s) as Wint attachments: one JPEG per page (default), or a single PDF."""
    rotations = rotations or {}
    if fmt == "pdf":
        return [Attachment(attachment_name(pdf_path, pages), "application/pdf", pdf.extract_pages(pdf_path, pages, rotations))]
    return [Attachment(f"{pdf_path.stem}-p{i + 1}.jpg", "image/jpeg", pdf.render_jpeg(pdf_path, i, rotations.get(i, 0)))
            for i in pages]


def attachment_name(pdf_path: Path, pages: list[int]) -> str:
    span = f"p{pages[0] + 1}" if len(pages) == 1 else f"p{pages[0] + 1}-{pages[-1] + 1}"
    return f"{pdf_path.stem}-{span}.pdf"


class DuplicateSuspected(Exception):
    """Wint already has a receipt with the same date and amount."""

    def __init__(self, receipts: list[dict]):
        super().__init__(", ".join(f"#{r.get('Id')}" for r in receipts))
        self.receipts = receipts


def upload_page(client: WintClient, pdf_path: Path, page: PageState,
                rotations: dict[int, int] | None = None, allow_similar: bool = False, fmt: str = "jpeg") -> int:
    """Create the receipt in Wint and return its id. Idempotent per page.client_id.

    `rotations` maps page index → clockwise turn chosen in the app; the attachment is turned to match.
    """
    if page.draft is None:
        raise ValueError("page has no reviewed draft")
    if page.status is not PageStatus.APPROVED:
        raise ValueError(f"page {page.index + 1} is {page.status}, not approved")
    # A previous attempt may have reached Wint before the app lost the response.
    existing = client.find_by_client_id(page.client_id)
    if existing:
        return int(existing[0]["Id"])
    if not allow_similar and page.draft.date and page.draft.amount is not None:
        if similar := client.find_similar(page.draft.date, page.draft.amount):
            raise DuplicateSuspected(similar)
    pages = page.draft.pages or [page.index]
    return client.create_receipt(page.draft, build_attachments(pdf_path, pages, rotations, fmt), page.client_id)
