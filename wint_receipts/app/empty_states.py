"""Illustrated placeholders for panes with nothing to show yet.

Illustrations are small SVGs coloured from the current palette, so they follow light/dark themes.
"""
from __future__ import annotations

from PySide6.QtCore import QByteArray, QEvent, QRectF, QSize, Qt
from PySide6.QtGui import QColor, QIcon, QPainter, QPalette, QPen, QPixmap
from PySide6.QtSvg import QSvgRenderer
from PySide6.QtWidgets import QGridLayout, QHBoxLayout, QLabel, QPushButton, QSizePolicy, QVBoxLayout, QWidget

from ..core.models import PageStatus
from . import theme

# {fg} outlines, {muted} fills/secondary lines, {accent} highlights, {bg} paper.
RECEIPTS_SVG = """
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 240 200">
  <g transform="rotate(-8 90 110)">
    <path d="M50 30h80v130l-10-6-10 6-10-6-10 6-10-6-10 6-10-6-10 6z" fill="{bg}" stroke="{muted}" stroke-width="3"/>
  </g>
  <g transform="rotate(6 150 110)">
    <path d="M110 34h80v130l-10-6-10 6-10-6-10 6-10-6-10 6-10-6-10 6z" fill="{bg}" stroke="{muted}" stroke-width="3"/>
  </g>
  <path d="M78 20h86v146l-10.75-6-10.75 6-10.75-6-10.75 6-10.75-6-10.75 6-10.75-6-10.75 6z"
        fill="{bg}" stroke="{fg}" stroke-width="3.5" stroke-linejoin="round"/>
  <rect x="92" y="38" width="40" height="7" rx="3.5" fill="{fg}"/>
  <rect x="92" y="58" width="58" height="5" rx="2.5" fill="{muted}"/>
  <rect x="92" y="72" width="50" height="5" rx="2.5" fill="{muted}"/>
  <rect x="92" y="86" width="58" height="5" rx="2.5" fill="{muted}"/>
  <rect x="92" y="100" width="36" height="5" rx="2.5" fill="{muted}"/>
  <line x1="92" y1="120" x2="150" y2="120" stroke="{muted}" stroke-width="2" stroke-dasharray="4 4"/>
  <rect x="92" y="130" width="24" height="7" rx="3.5" fill="{fg}"/>
  <rect x="126" y="130" width="24" height="7" rx="3.5" fill="{accent}"/>
  <circle cx="186" cy="150" r="24" fill="{accent}"/>
  <path d="M186 162v-24M175 149l11-11 11 11" stroke="{bg}" stroke-width="5" fill="none"
        stroke-linecap="round" stroke-linejoin="round"/>
</svg>
"""

PAGES_SVG = """
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 160 140">
  <g fill="{bg}" stroke="{muted}" stroke-width="3">
    <rect x="20" y="14" width="120" height="30" rx="6"/>
    <rect x="20" y="54" width="120" height="30" rx="6"/>
    <rect x="20" y="94" width="120" height="30" rx="6"/>
  </g>
  <circle cx="38" cy="29" r="7" fill="{approved}"/>
  <circle cx="38" cy="69" r="7" fill="{review}"/>
  <circle cx="38" cy="109" r="7" fill="{muted}"/>
  <g fill="{muted}">
    <rect x="54" y="25" width="70" height="8" rx="4"/>
    <rect x="54" y="65" width="56" height="8" rx="4"/>
    <rect x="54" y="105" width="64" height="8" rx="4"/>
  </g>
</svg>
"""

FORM_SVG = """
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 180 150">
  <rect x="20" y="10" width="140" height="130" rx="10" fill="{bg}" stroke="{fg}" stroke-width="3"/>
  <g fill="{muted}">
    <rect x="34" y="28" width="30" height="6" rx="3"/><rect x="74" y="24" width="72" height="14" rx="4"/>
    <rect x="34" y="52" width="30" height="6" rx="3"/><rect x="74" y="48" width="72" height="14" rx="4"/>
    <rect x="34" y="76" width="30" height="6" rx="3"/><rect x="74" y="72" width="72" height="14" rx="4"/>
  </g>
  <rect x="74" y="104" width="72" height="22" rx="6" fill="{accent}"/>
  <path d="M100 115l6 6 12-12" stroke="{bg}" stroke-width="4" fill="none" stroke-linecap="round" stroke-linejoin="round"/>
</svg>
"""

READING_SVG = """
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 180 150">
  <path d="M50 14h72v118l-9-5-9 5-9-5-9 5-9-5-9 5-9-5-9 5z" fill="{bg}" stroke="{fg}" stroke-width="3"/>
  <g fill="{muted}">
    <rect x="62" y="34" width="48" height="5" rx="2.5"/><rect x="62" y="48" width="40" height="5" rx="2.5"/>
    <rect x="62" y="62" width="48" height="5" rx="2.5"/><rect x="62" y="76" width="30" height="5" rx="2.5"/>
  </g>
  <rect x="40" y="56" width="92" height="6" rx="3" fill="{accent}" opacity="0.8"/>
  <circle cx="128" cy="98" r="22" fill="none" stroke="{accent}" stroke-width="6"/>
  <line x1="144" y1="114" x2="160" y2="130" stroke="{accent}" stroke-width="8" stroke-linecap="round"/>
</svg>
"""


def _colors(palette: QPalette) -> dict[str, str]:
    return {"fg": palette.color(QPalette.ColorRole.WindowText).name(),
            "bg": palette.color(QPalette.ColorRole.Base).name(),
            "muted": theme.ILLUSTRATION_MUTED,
            "accent": palette.color(QPalette.ColorRole.Highlight).name(),
            "approved": theme.STATUS[PageStatus.APPROVED], "review": theme.STATUS[PageStatus.NEEDS_REVIEW]}


def svg_pixmap(svg: str, size: QSize, palette: QPalette, ratio: float = 1.0) -> QPixmap:
    data = svg.format(**_colors(palette))
    renderer = QSvgRenderer(QByteArray(data.encode("utf-8")))
    vb = renderer.viewBoxF()
    w = size.width()
    h = int(w * vb.height() / vb.width()) if vb.width() else size.height()
    pix = QPixmap(int(w * ratio), int(h * ratio))
    pix.setDevicePixelRatio(ratio)
    pix.fill(Qt.GlobalColor.transparent)
    p = QPainter(pix)
    renderer.render(p)
    p.end()
    return pix


def status_dot(color: str, diameter: int = 12) -> QIcon:
    pix = QPixmap(diameter * 2, diameter * 2)
    pix.setDevicePixelRatio(2)
    pix.fill(Qt.GlobalColor.transparent)
    p = QPainter(pix)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    p.setBrush(QColor(color))
    p.setPen(QPen(QColor("white"), 1.5))  # keeps the dot visible on a selected (highlighted) row
    p.drawEllipse(QRectF(1, 1, diameter - 2, diameter - 2))
    p.end()
    return QIcon(pix)


class EmptyState(QWidget):
    """Illustration + title + explanatory text + optional buttons, centred in the pane."""

    def __init__(self, svg: str, title: str, body: str, width_em: float = 14, parent=None):
        super().__init__(parent)
        self._svg = svg
        self._width_em = width_em
        self.art = QLabel(alignment=Qt.AlignmentFlag.AlignCenter)
        self.title = QLabel(title, alignment=Qt.AlignmentFlag.AlignCenter)
        self.title.setWordWrap(True)
        self.body = QLabel(body, alignment=Qt.AlignmentFlag.AlignCenter)
        self.body.setWordWrap(True)
        self.body.setTextFormat(Qt.TextFormat.RichText)
        self.body.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Minimum)
        self.buttons = QHBoxLayout()
        self.buttons.addStretch()

        col = QVBoxLayout()
        col.addStretch(2)
        col.addWidget(self.art)
        col.addSpacing(8)
        col.addWidget(self.title)
        col.addWidget(self.body)
        # Optional left-aligned list (legend, steps), centred as one block like in the design.
        self.rows = QWidget()
        self.rows_grid = QGridLayout(self.rows)
        self.rows_grid.setContentsMargins(0, 8, 0, 0)
        self.rows_grid.setHorizontalSpacing(10)
        self.rows_grid.setVerticalSpacing(4)
        self.rows.hide()
        col.addWidget(self.rows, 0, Qt.AlignmentFlag.AlignHCenter)
        self._muted: list[QLabel] = [self.body]
        col.addSpacing(8)
        col.addLayout(self.buttons)
        col.addStretch(3)
        outer = QHBoxLayout(self)
        outer.addStretch()
        outer.addLayout(col, 6)
        outer.addStretch()
        self._restyle()

    def add_row(self, text: str, lead: str | None = None, icon: QIcon | None = None) -> None:
        """One line of the list: a status dot or a bold lead word, then muted text."""
        r = self.rows_grid.rowCount()
        if icon is not None:
            dot = QLabel()
            dot.setPixmap(icon.pixmap(QSize(16, 16), self.devicePixelRatioF()))
            self.rows_grid.addWidget(dot, r, 0, Qt.AlignmentFlag.AlignVCenter)
        elif lead:
            l = QLabel(lead)
            f = l.font()
            f.setBold(True)
            l.setFont(f)
            self.rows_grid.addWidget(l, r, 0, Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop)
        t = QLabel(text)
        t.setWordWrap(True)
        self._muted.append(t)
        self.rows_grid.addWidget(t, r, 1, Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop)
        self.rows.show()
        self._restyle()

    def add_button(self, text: str, slot, primary: bool = False, icon: QIcon | None = None) -> QPushButton:
        b = QPushButton(text)
        if icon:
            b.setIcon(icon)
        if primary:
            b.setObjectName("primary")
        b.clicked.connect(slot)
        self.buttons.addWidget(b)
        return b

    def finish_buttons(self) -> None:
        self.buttons.addStretch()

    def set_text(self, title: str, body: str) -> None:
        self.title.setText(title)
        self.body.setText(body)

    def _restyle(self) -> None:
        f = self.font()
        tf = self.title.font()
        tf.setBold(True)
        tf.setPointSizeF(f.pointSizeF() * 1.35)
        self.title.setFont(tf)
        em = self.fontMetrics().height()
        width = int(em * self._width_em)
        self.art.setPixmap(svg_pixmap(self._svg, QSize(width, width), self.palette(), self.devicePixelRatioF()))
        self.body.setMaximumWidth(int(em * 26))
        self.rows.setMaximumWidth(int(em * 42))
        # Word-wrapping labels prefer a narrow width; ask for the text's natural width (capped) so
        # list lines stay on one line when the pane has room, as in the design.
        for label in getattr(self, "_muted", [])[1:]:
            label.setMinimumWidth(min(label.fontMetrics().horizontalAdvance(label.text()) + 4, int(em * 26)))
        muted = self.palette().color(QPalette.ColorRole.PlaceholderText)
        for label in getattr(self, "_muted", [self.body]):
            pal = label.palette()
            pal.setColor(QPalette.ColorRole.WindowText, muted)
            label.setPalette(pal)
        for i in range(self.rows_grid.count() if hasattr(self, "rows_grid") else 0):
            w = self.rows_grid.itemAt(i).widget()
            if isinstance(w, QLabel) and w not in self._muted and w.pixmap().isNull():
                f = self.font()
                f.setBold(True)
                w.setFont(f)  # bold lead follows font-size changes

    def changeEvent(self, event):  # noqa: N802 - Qt API
        if event.type() in (QEvent.Type.FontChange, QEvent.Type.PaletteChange):
            self._restyle()
        super().changeEvent(event)
