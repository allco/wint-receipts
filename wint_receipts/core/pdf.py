"""PDF splitting and rendering with pypdfium2."""
from __future__ import annotations

import hashlib
import io
import threading
from collections.abc import Mapping, Sequence
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


def render_png(path: Path, index: int, dpi: int = 200, rotation: int = 0, max_side: int | None = None) -> bytes:
    """Render one page (0-based) to PNG bytes, turned clockwise by `rotation` degrees (0/90/180/270).

    `max_side` caps the longer edge in pixels: scans are often far larger than anyone needs, and
    rendering them at full DPI is slow.
    """
    with _lock:
        pdf = pdfium.PdfDocument(path)
        try:
            page = pdf[index]
            try:
                scale = dpi / 72
                if max_side:
                    scale = min(scale, max_side / max(page.get_width(), page.get_height()))
                image = page.render(scale=scale, rotation=rotation % 360).to_pil()
            finally:
                page.close()
        finally:
            pdf.close()
    buf = io.BytesIO()
    image.save(buf, format="PNG", compress_level=1)  # speed over size; it's only kept in memory
    return buf.getvalue()


def extract_pages(path: Path, indices: Sequence[int], rotations: Mapping[int, int] | None = None) -> bytes:
    """Copy the given pages (0-based, in order) into a new PDF, without re-encoding them.

    `rotations` maps a source page index to an extra clockwise turn, set as the page's /Rotate.
    """
    if not indices:
        raise ValueError("no pages to extract")
    with _lock:
        src = pdfium.PdfDocument(path)
        dst = pdfium.PdfDocument.new()
        try:
            dst.import_pages(src, list(indices))
            for pos, index in enumerate(indices):
                if turn := (rotations or {}).get(index, 0) % 360:
                    page = dst[pos]
                    page.set_rotation((page.get_rotation() + turn) % 360)
                    page.close()
            buf = io.BytesIO()
            dst.save(buf)
            return buf.getvalue()
        finally:
            dst.close()
            src.close()
