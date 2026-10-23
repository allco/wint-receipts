"""The page image: a zoomable view plus a bar with rotate and zoom controls.

Wheel to zoom, drag to pan, double-click to fit.
"""
from __future__ import annotations

from PySide6.QtCore import QEvent, QSize, Qt, Signal
from PySide6.QtGui import QAction, QKeySequence, QPainter, QPixmap
from PySide6.QtWidgets import (
    QGraphicsPixmapItem, QGraphicsScene, QGraphicsView, QLabel, QSizePolicy, QToolBar, QVBoxLayout, QWidget,
)

from . import icons as app_icons

ZOOM_STEP = 1.25
MIN_ZOOM, MAX_ZOOM = 0.05, 8.0


class ImageView(QGraphicsView):
    zoom_changed = Signal(float)  # current scale, 1.0 = one image pixel per screen pixel

    def __init__(self, parent=None):
        super().__init__(parent)
        self._scene = QGraphicsScene(self)
        self._item = QGraphicsPixmapItem()
        self._item.setTransformationMode(Qt.TransformationMode.SmoothTransformation)
        self._scene.addItem(self._item)
        self.setScene(self._scene)
        self.setRenderHints(QPainter.RenderHint.Antialiasing | QPainter.RenderHint.SmoothPixmapTransform)
        self.setDragMode(QGraphicsView.DragMode.ScrollHandDrag)
        self.setTransformationAnchor(QGraphicsView.ViewportAnchor.AnchorUnderMouse)
        self._fit = True

    def set_png(self, png: bytes | None, keep_view: bool = False) -> None:
        pix = QPixmap()
        if png:
            pix.loadFromData(png, "PNG")
        self._item.setPixmap(pix)
        self._scene.setSceneRect(self._item.boundingRect())
        if keep_view and not self._fit:
            self.zoom_changed.emit(self.scale_factor())
        else:
            self.fit()

    def scale_factor(self) -> float:
        return self.transform().m11()

    def fit(self) -> None:
        self._fit = True
        self.resetTransform()
        if not self._item.pixmap().isNull():
            self.fitInView(self._item, Qt.AspectRatioMode.KeepAspectRatio)
        self.zoom_changed.emit(self.scale_factor())

    def actual_size(self) -> None:
        """1:1, one image pixel per screen pixel."""
        self._fit = False
        self.resetTransform()
        self.zoom_changed.emit(1.0)

    def zoom(self, factor: float) -> None:
        target = min(MAX_ZOOM, max(MIN_ZOOM, self.scale_factor() * factor))
        factor = target / self.scale_factor()
        self._fit = False
        self.scale(factor, factor)
        self.zoom_changed.emit(self.scale_factor())

    def zoom_in(self) -> None:
        self.zoom(ZOOM_STEP)

    def zoom_out(self) -> None:
        self.zoom(1 / ZOOM_STEP)

    def wheelEvent(self, event):  # noqa: N802 - Qt API
        self.zoom(ZOOM_STEP if event.angleDelta().y() > 0 else 1 / ZOOM_STEP)

    def mouseDoubleClickEvent(self, event):  # noqa: N802
        self.fit()

    def resizeEvent(self, event):  # noqa: N802
        super().resizeEvent(event)
        if self._fit:
            self.fit()


class ImagePane(QWidget):
    """The view with a control bar under it. Rotation is per page and owned by the main window."""

    rotate_requested = Signal(int)  # +90 clockwise, -90 counter-clockwise

    def __init__(self, parent=None):
        super().__init__(parent)
        self.view = ImageView()
        self.bar = QToolBar("Image")
        self.bar.setObjectName("imagebar")
        self.bar.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)

        def act(text, slot, shortcuts, tip, icon=None, text_only=False):
            a = QAction(text, self)
            if icon:
                a.setIcon(app_icons.icon(icon))
            a.setShortcuts([QKeySequence(s) for s in shortcuts])
            a.setShortcutContext(Qt.ShortcutContext.WindowShortcut)
            a.setToolTip(f"{tip} ({QKeySequence(shortcuts[0]).toString(QKeySequence.SequenceFormat.NativeText)})")
            a.triggered.connect(slot)
            self.bar.addAction(a)
            w = self.bar.widgetForAction(a)
            w.setFocusPolicy(Qt.FocusPolicy.NoFocus)
            if text_only:
                w.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextOnly)
            return a

        self.rotate_left = act("Rotate left", lambda: self.rotate_requested.emit(-90), ["Ctrl+Shift+R"],
                               "Turn the page a quarter counter-clockwise", "rotate-left")
        self.rotate_right = act("Rotate right", lambda: self.rotate_requested.emit(90), ["Ctrl+R"],
                                "Turn the page a quarter clockwise", "rotate-right")
        spacer = QWidget()
        spacer.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        self.bar.addWidget(spacer)
        self.zoom_out = act("Zoom out", self.view.zoom_out, ["Ctrl+-"], "Zoom out", "zoom-out")
        self.zoom_label = QLabel("100%")
        self.zoom_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.bar.addWidget(self.zoom_label)
        self.zoom_in = act("Zoom in", self.view.zoom_in, ["Ctrl++", "Ctrl+="], "Zoom in", "zoom-in")
        for a in (self.zoom_out, self.zoom_in):  # icon only; the label says it
            self.bar.widgetForAction(a).setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonIconOnly)
        self.bar.addSeparator()
        self.actual = act("1:1", self.view.actual_size, ["Ctrl+1"], "Actual size", text_only=True)
        self.fit = act("Fit", self.view.fit, ["Ctrl+0"], "Fit the page in the pane", "fit")

        self.view.zoom_changed.connect(lambda s: self.zoom_label.setText(f"{round(s * 100)}%"))

        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)
        lay.addWidget(self.view)
        lay.addWidget(self.bar)
        self._fit_icons()

    def set_rotation_enabled(self, enabled: bool) -> None:
        self.rotate_left.setEnabled(enabled)
        self.rotate_right.setEnabled(enabled)

    def _fit_icons(self) -> None:
        h = round(self.fontMetrics().height() * 1.15)
        self.bar.setIconSize(QSize(h + max(4, round(h * 0.3)), h))
        self.zoom_label.setMinimumWidth(self.fontMetrics().horizontalAdvance("8888%") + 8)

    def changeEvent(self, event):  # noqa: N802 - Qt API
        if event.type() == QEvent.Type.FontChange:
            self._fit_icons()
        super().changeEvent(event)
