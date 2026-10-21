"""The app's own toolbar icons: 24×24 outline SVGs in the design colours.

{fg} is the text colour, {accent} the design accent; both come from theme.py.
"""
from __future__ import annotations

from PySide6.QtCore import QByteArray, QPoint, QRect, QRectF, QSize, Qt
from PySide6.QtGui import QIcon, QIconEngine, QPainter, QPixmap
from PySide6.QtSvg import QSvgRenderer

from . import theme

_HEAD = '<svg xmlns="http://www.w3.org/2000/svg" width="24" height="24" viewBox="0 0 24 24" fill="none" ' \
        'stroke="{fg}" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round">'

SVGS = {
    # folder with a receipt sticking out
    "open": '<path d="M3 7.5V18a1.5 1.5 0 0 0 1.5 1.5h15A1.5 1.5 0 0 0 21 18v-8a1.5 1.5 0 0 0-1.5-1.5h-7L10.5 6h-6A1.5 1.5 0 0 0 3 7.5z"/>'
            '<path d="M8 12.5h8M8 15.5h5" stroke="{accent}"/>',
    # receipt with AI sparkles
    "recognise": '<path d="M3.5 3.5h9v17l-1.5-1-1.5 1-1.5-1-1.5 1-1.5-1-1.5 1z"/><path d="M6.5 8h3M6.5 11h3M6.5 14h2"/>'
                 '<path d="M17.5 8.5l1.2 3.3 3.3 1.2-3.3 1.2-1.2 3.3-1.2-3.3-3.3-1.2 3.3-1.2z" fill="{accent}" stroke="{accent}" stroke-width="1"/>'
                 '<path d="M19.5 3l.6 1.4 1.4.6-1.4.6-.6 1.4-.6-1.4-1.4-.6 1.4-.6z" fill="{accent}" stroke="{accent}" stroke-width="0.8"/>',
    "previous": '<path d="M14.5 6l-6 6 6 6"/>',
    "next": '<path d="M9.5 6l6 6-6 6"/>',
    # corners pointing outward around a page
    "fit": '<path d="M4 9V4h5M20 9V4h-5M4 15v5h5M20 15v5h-5"/><rect x="8.5" y="8.5" width="7" height="7" rx="1"/>',
    # page with code brackets
    "preview": '<path d="M6 3.5h8l4 4v13H6z"/><path d="M14 3.5v4h4"/><path d="M10.5 12l-2 2 2 2M13.5 12l2 2-2 2" stroke="{accent}"/>',
    # cloud with an up arrow
    "upload": '<path d="M7 18.5a4.5 4.5 0 0 1-.6-8.96A6 6 0 0 1 18 9a4 4 0 0 1-.5 9.5"/>'
              '<path d="M12 20.5v-8M9 15l3-3 3 3" stroke="{accent}"/>',
    # circular arrows
    "reload": '<path d="M19.5 12a7.5 7.5 0 0 1-13 5.1M4.5 12a7.5 7.5 0 0 1 13-5.1"/><path d="M17.5 3.5v3.6h-3.6M6.5 20.5v-3.6h3.6"/>',
    # sliders
    "settings": '<path d="M4 7h9M17 7h3M4 17h3M11 17h9"/><circle cx="15" cy="7" r="2"/><circle cx="9" cy="17" r="2"/>'
                '<path d="M4 12h5M13 12h7"/><circle cx="11" cy="12" r="2" stroke="{accent}"/>',
}


def svg(name: str, fg: str = theme.TEXT, accent: str = theme.ACCENT) -> str:
    return (_HEAD + SVGS[name] + "</svg>").replace("{fg}", fg).replace("{accent}", accent)


class _SvgEngine(QIconEngine):
    """Renders the SVG at whatever size and pixel ratio Qt asks for; greyed out when disabled."""

    def __init__(self, name: str):
        super().__init__()
        self._name = name

    def paint(self, painter: QPainter, rect, mode, state):
        disabled = mode == QIcon.Mode.Disabled
        data = svg(self._name, theme.BORDER if disabled else theme.TEXT, theme.BORDER if disabled else theme.ACCENT)
        # Draw into the left square of the rect; any extra width is the gap before the label.
        side = min(rect.width(), rect.height())
        target = QRectF(rect.x(), rect.y() + (rect.height() - side) / 2, side, side)
        QSvgRenderer(QByteArray(data.encode())).render(painter, target)

    def pixmap(self, size: QSize, mode, state) -> QPixmap:
        pix = QPixmap(size)
        pix.fill(Qt.GlobalColor.transparent)
        p = QPainter(pix)
        self.paint(p, pix.rect(), mode, state)
        p.end()
        return pix

    def scaledPixmap(self, size: QSize, mode, state, scale: float) -> QPixmap:  # noqa: N802 - Qt API
        # Render at device resolution so icons stay sharp on HiDPI / fractional scaling.
        pix = QPixmap(size * scale)
        pix.setDevicePixelRatio(scale)
        pix.fill(Qt.GlobalColor.transparent)
        p = QPainter(pix)
        self.paint(p, QRect(QPoint(0, 0), size), mode, state)
        p.end()
        return pix

    def clone(self):
        return _SvgEngine(self._name)


def icon(name: str) -> QIcon:
    return QIcon(_SvgEngine(name))
