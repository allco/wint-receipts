"""PDF splitting and rendering with pypdfium2."""
from __future__ import annotations

import hashlib
import io
import threading
from collections.abc import Sequence
from pathlib import Path

import pypdfium2 as pdfium

# pdfium is not thread-safe; recognition renders pages from worker threads.
_lock = threading.RLock()


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def page_count(path: Path) -> int:
    with _lock:
        pdf = pdfium.PdfDocument(path)
        try:
            return len(pdf)
        finally:
            pdf.close()


def render_png(path: Path, index: int, dpi: int = 200) -> bytes:
    """Render one page (0-based) to PNG bytes."""
    with _lock:
        pdf = pdfium.PdfDocument(path)
        try:
            page = pdf[index]
            try:
                image = page.render(scale=dpi / 72).to_pil()
            finally:
                page.close()
        finally:
            pdf.close()
    buf = io.BytesIO()
    image.save(buf, format="PNG")
    return buf.getvalue()


def extract_pages(path: Path, indices: Sequence[int]) -> bytes:
    """Copy the given pages (0-based, in order) into a new PDF, without re-encoding them."""
    if not indices:
        raise ValueError("no pages to extract")
    with _lock:
        src = pdfium.PdfDocument(path)
        dst = pdfium.PdfDocument.new()
        try:
            dst.import_pages(src, list(indices))
            buf = io.BytesIO()
            dst.save(buf)
            return buf.getvalue()
        finally:
            dst.close()
            src.close()
