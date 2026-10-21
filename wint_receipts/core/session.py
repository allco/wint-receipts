"""Per-PDF review state, saved next to the PDF as <name>.wint.json."""
from __future__ import annotations

import os
from pathlib import Path

from . import pdf
from .models import PageState, PageStatus, Session


def session_path(pdf_path: Path) -> Path:
    return pdf_path.with_name(pdf_path.name + ".wint.json")


def open_session(pdf_path: Path) -> Session:
    """Load the saved session for this PDF, or start a new one if none exists or the PDF changed."""
    pdf_path = pdf_path.resolve()
    digest = pdf.sha256(pdf_path)
    path = session_path(pdf_path)
    if path.exists():
        saved = Session.model_validate_json(path.read_text(encoding="utf-8"))
        if saved.pdf_sha256 == digest:
            # A crash mid-recognition or mid-upload leaves transient states behind.
            for p in saved.pages:
                if p.status is PageStatus.RECOGNIZING:
                    p.status = PageStatus.NEW
                elif p.status is PageStatus.UPLOADING:
                    # Unknown whether Wint got it; the uploader checks ClientId before retrying.
                    p.status = PageStatus.APPROVED
            return saved
    n = pdf.page_count(pdf_path)
    return Session(pdf_path=str(pdf_path), pdf_sha256=digest, pages=[PageState(index=i) for i in range(n)])


def save_session(session: Session) -> None:
    path = session_path(Path(session.pdf_path))
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(session.model_dump_json(indent=2), encoding="utf-8")
    os.replace(tmp, path)
