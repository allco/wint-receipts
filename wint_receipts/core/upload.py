"""Upload one reviewed page (or merged pages) as a Wint receipt."""
from __future__ import annotations

from pathlib import Path

from . import pdf
from .models import PageState, PageStatus
from .wint import WintClient


def attachment_name(pdf_path: Path, pages: list[int]) -> str:
    span = f"p{pages[0] + 1}" if len(pages) == 1 else f"p{pages[0] + 1}-{pages[-1] + 1}"
    return f"{pdf_path.stem}-{span}.pdf"


def upload_page(client: WintClient, pdf_path: Path, page: PageState) -> int:
    """Create the receipt in Wint and return its id. Idempotent per page.client_id."""
    if page.draft is None:
        raise ValueError("page has no reviewed draft")
    if page.status is not PageStatus.APPROVED:
        raise ValueError(f"page {page.index + 1} is {page.status}, not approved")
    # A previous attempt may have reached Wint before the app lost the response.
    existing = client.find_by_client_id(page.client_id)
    if existing:
        return int(existing[0]["Id"])
    pages = page.draft.pages or [page.index]
    data = pdf.extract_pages(pdf_path, pages)
    return client.create_receipt(page.draft, data, page.client_id, attachment_name(pdf_path, pages))
